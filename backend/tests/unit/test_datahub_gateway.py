from __future__ import annotations

import json

import httpx
import pytest

from datariver.application.errors import ExternalDependencyError
from datariver.domain.authz import Classification
from datariver.domain.common import canonical_json_hash
from datariver.infrastructure.datahub.http import HttpDataHubGateway


async def test_asset_contract_uses_fixed_graphql_and_service_identity() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/graphql"
        assert request.headers["Authorization"] == "Bearer service-token"
        body = json.loads(request.content)
        assert body["variables"] == {"urn": "urn:li:dataset:test"}
        return httpx.Response(
            200,
            json={
                "data": {
                    "entity": {
                        "urn": "urn:li:dataset:test",
                        "type": "DATASET",
                        "ownership": {"owners": []},
                        "globalTags": {"tags": [{"tag": {"urn": "tag:one", "name": "One"}}]},
                        "glossaryTerms": {"terms": []},
                        "schemaMetadata": {"fields": [{"fieldPath": "id", "type": "STRING"}]},
                    }
                }
            },
        )

    client = httpx.AsyncClient(
        base_url="https://datahub.example",
        headers={"Authorization": "Bearer service-token"},
        transport=httpx.MockTransport(handler),
    )
    gateway = HttpDataHubGateway(
        base_url="https://datahub.example",
        token="unused-with-injected-client",
        timeout_seconds=1,
        client=client,
    )

    asset = await gateway.get_asset("urn:li:dataset:test")

    assert asset.tags == ("One",)
    assert asset.schema_fields[0]["fieldPath"] == "id"
    await client.aclose()


async def test_graphql_contract_errors_are_non_retryable_and_sanitized() -> None:
    client = httpx.AsyncClient(
        base_url="https://datahub.example",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"errors": [{"message": "provider secret"}]})
        ),
    )
    gateway = HttpDataHubGateway(
        base_url="https://datahub.example",
        token="unused",
        timeout_seconds=1,
        client=client,
    )

    with pytest.raises(ExternalDependencyError) as caught:
        await gateway.get_asset("urn:li:dataset:test")

    assert caught.value.details["retryable"] is False
    assert caught.value.details["provider_code"] == "GRAPHQL_ERROR"
    assert "provider secret" not in caught.value.message
    await client.aclose()


async def test_aspect_reread_hashes_only_the_typed_value() -> None:
    document = {"description": "governed", "customProperties": {"tier": "gold"}}
    client = httpx.AsyncClient(
        base_url="https://datahub.example",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"aspect": {"value": json.dumps(document), "contentType": "application/json"}},
                headers={"etag": "version-2"},
            )
        ),
    )
    gateway = HttpDataHubGateway(
        base_url="https://datahub.example", token="unused", timeout_seconds=1, client=client
    )

    snapshot = await gateway.read_aspect(
        external_urn="urn:li:dataset:test", aspect_name="datasetProperties"
    )

    assert snapshot.content_hash == canonical_json_hash(document)
    assert snapshot.source_version == "version-2"
    await client.aclose()


async def test_catalog_scan_maps_a_fixed_datahub_contract_and_paginates() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["variables"]["input"] == {
            "types": ["DATASET"],
            "query": "*",
            "start": 0,
            "count": 1,
        }
        return httpx.Response(
            200,
            json={
                "data": {
                    "searchAcrossEntities": {
                        "start": 0,
                        "count": 1,
                        "total": 2,
                        "searchResults": [
                            {
                                "entity": {
                                    "urn": "urn:li:dataset:test",
                                    "type": "DATASET",
                                    "name": "fallback",
                                    "platform": {
                                        "urn": "urn:li:dataPlatform:snowflake",
                                        "name": "snowflake",
                                    },
                                    "properties": {"name": "wafer_events", "description": "events"},
                                    "domain": {"domain": {"urn": "urn:li:domain:manufacturing"}},
                                    "ownership": {
                                        "owners": [{"owner": {"urn": "urn:li:corpGroup:yield"}}]
                                    },
                                    "globalTags": {
                                        "tags": [{"tag": {"name": "classification:confidential"}}]
                                    },
                                }
                            }
                        ],
                    }
                }
            },
        )

    client = httpx.AsyncClient(
        base_url="https://datahub.example", transport=httpx.MockTransport(handler)
    )
    gateway = HttpDataHubGateway(
        base_url="https://datahub.example", token="unused", timeout_seconds=1, client=client
    )

    page = await gateway.scan_assets(offset=0, limit=1)

    assert page.items[0].name == "wafer_events"
    assert page.items[0].platform == "snowflake"
    assert page.items[0].domain_ref == "urn:li:domain:manufacturing"
    assert page.items[0].system_ref == "urn:li:dataPlatform:snowflake"
    assert page.items[0].classification is Classification.CONFIDENTIAL
    assert page.next_offset == 1
    assert page.total == 2
    await client.aclose()


async def test_circuit_breaker_opens_after_bounded_retryable_failures() -> None:
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"message": "unavailable"})

    client = httpx.AsyncClient(
        base_url="https://datahub.example", transport=httpx.MockTransport(handler)
    )
    gateway = HttpDataHubGateway(
        base_url="https://datahub.example",
        token="unused",
        timeout_seconds=1,
        circuit_failure_threshold=2,
        circuit_open_seconds=60,
        client=client,
    )

    for expected_code in ("503", "503", "CIRCUIT_OPEN"):
        with pytest.raises(ExternalDependencyError) as caught:
            await gateway.get_asset("urn:li:dataset:test")
        assert caught.value.details["provider_code"] == expected_code

    assert calls == 2
    await client.aclose()
