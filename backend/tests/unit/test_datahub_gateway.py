from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from datariver.application.errors import ExternalDependencyError
from datariver.domain.authz import Classification
from datariver.domain.common import canonical_json_hash
from datariver.infrastructure.datahub.http import (
    VOCABULARY_SEARCH_QUERY,
    HttpDataHubGateway,
    _catalog_hierarchy_from_browse_path,
)
from datariver.infrastructure.observability.metrics import HttpMetrics

DATAHUB_V160_CONFIG = {"versions": {"acryldata/datahub": {"version": "v1.6.0"}}}


async def test_vocabulary_search_uses_the_fixed_tag_contract() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/graphql"
        body = json.loads(request.content)
        assert body["query"] == VOCABULARY_SEARCH_QUERY
        assert body["variables"] == {
            "input": {"types": ["TAG"], "query": "cal", "start": 0, "count": 50}
        }
        return httpx.Response(
            200,
            json={
                "data": {
                    "searchAcrossEntities": {
                        "searchResults": [
                            {"entity": {"urn": "urn:li:tag:calibration", "name": "Calibration"}},
                            {"entity": {"urn": "urn:li:tag:empty", "name": "  "}},
                        ]
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

    values = await gateway.search_vocabulary(kind="TAG", query="cal", limit=12)

    assert values == ("Calibration",)
    await client.aclose()


async def test_vocabulary_search_reads_glossary_term_properties_name() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["variables"]["input"]["types"] == ["GLOSSARY_TERM"]
        return httpx.Response(
            200,
            json={
                "data": {
                    "searchAcrossEntities": {
                        "searchResults": [
                            {
                                "entity": {
                                    "urn": "urn:li:glossaryTerm:EUV",
                                    "properties": {"name": "EUV"},
                                }
                            }
                        ]
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

    values = await gateway.search_vocabulary(kind="TERM", query="eu", limit=12)

    assert values == ("EUV",)
    await client.aclose()


async def test_vocabulary_search_accepts_the_bounded_wildcard_browse_query() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["variables"] == {
            "input": {"types": ["TAG"], "query": "*", "start": 0, "count": 50}
        }
        return httpx.Response(
            200,
            json={
                "data": {
                    "searchAcrossEntities": {
                        "searchResults": [
                            {"entity": {"urn": "urn:li:tag:quality", "name": "Quality"}},
                        ]
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

    values = await gateway.search_vocabulary(kind="TAG", query="*", limit=12)

    assert values == ("Quality",)
    await client.aclose()


async def test_vocabulary_search_reads_later_bounded_pages_before_returning_matches() -> None:
    calls: list[int] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        start = body["variables"]["input"]["start"]
        calls.append(start)
        results = [
            {"entity": {"urn": f"urn:li:tag:value-{index}", "name": f"Value {index}"}}
            for index in range(start, start + 50)
        ]
        if start == 50:
            results = [{"entity": {"urn": "urn:li:tag:later", "name": "Later match"}}]
        return httpx.Response(
            200,
            json={"data": {"searchAcrossEntities": {"searchResults": results}}},
        )

    client = httpx.AsyncClient(
        base_url="https://datahub.example", transport=httpx.MockTransport(handler)
    )
    gateway = HttpDataHubGateway(
        base_url="https://datahub.example", token="unused", timeout_seconds=1, client=client
    )

    values = await gateway.search_vocabulary(kind="TAG", query="value", limit=12)

    assert calls == [0, 50]
    assert "Later match" in values
    await client.aclose()


async def test_asset_contract_uses_fixed_graphql_and_service_identity() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/graphql"
        assert request.headers["Authorization"] == "Bearer service-token"
        body = json.loads(request.content)
        assert body["variables"] == {"urn": "urn:li:dataset:test"}
        assert "globalTags: tags" in body["query"]
        assert "editableSchemaMetadata" in body["query"]
        assert "schemaFieldEntity" in body["query"]
        assert "latestFullTableProfile: datasetProfiles" in body["query"]
        assert "FULL_TABLE_SNAPSHOT" in body["query"]
        return httpx.Response(
            200,
            json={
                "data": {
                    "entity": {
                        "urn": "urn:li:dataset:test",
                        "type": "DATASET",
                        "properties": {"created": 1767225600000},
                        "ownership": {"owners": []},
                        "globalTags": {"tags": [{"tag": {"urn": "tag:one", "name": "One"}}]},
                        "glossaryTerms": {"terms": []},
                        "schemaMetadata": {
                            "fields": [
                                {
                                    "fieldPath": "id",
                                    "type": "STRING",
                                    "description": "source description",
                                    "globalTags": {
                                        "tags": [{"tag": {"urn": "tag:source", "name": "Source"}}]
                                    },
                                    "glossaryTerms": {
                                        "terms": [
                                            {
                                                "term": {
                                                    "urn": "term:source",
                                                    "name": "Source term",
                                                }
                                            }
                                        ]
                                    },
                                    "schemaFieldEntity": {
                                        "globalTags": {
                                            "tags": [
                                                {
                                                    "tag": {
                                                        "urn": "tag:field-entity",
                                                        "name": "Field entity",
                                                    }
                                                }
                                            ]
                                        },
                                        "glossaryTerms": {"terms": []},
                                    },
                                }
                            ]
                        },
                        "editableSchemaMetadata": {
                            "editableSchemaFieldInfo": [
                                {
                                    "fieldPath": "id",
                                    "description": "governed description",
                                    "globalTags": {
                                        "tags": [{"tag": {"urn": "tag:edited", "name": "Edited"}}]
                                    },
                                    "glossaryTerms": {
                                        "terms": [
                                            {
                                                "term": {
                                                    "urn": "term:edited",
                                                    "name": "Edited term",
                                                }
                                            }
                                        ]
                                    },
                                }
                            ]
                        },
                        "latestFullTableProfile": [
                            {
                                "rowCount": 1240,
                                "columnCount": 8,
                                "sizeInBytes": 8192,
                                "timestampMillis": 1767229200000,
                            }
                        ],
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
    assert asset.schema_fields[0]["description"] == "governed description"
    assert {item["tag"]["name"] for item in asset.schema_fields[0]["globalTags"]["tags"]} == {
        "Source",
        "Field entity",
        "Edited",
    }
    assert {item["term"]["name"] for item in asset.schema_fields[0]["glossaryTerms"]["terms"]} == {
        "Source term",
        "Edited term",
    }
    assert asset.quality == {
        "rowCount": 1240,
        "columnCount": 8,
        "sizeInBytes": 8192,
        "profiledAt": "2026-01-01T01:00:00+00:00",
    }
    assert asset.created_at is not None
    assert asset.created_at.isoformat() == "2026-01-01T00:00:00+00:00"
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
    assert dict(snapshot.document) == document
    with pytest.raises(TypeError):
        snapshot.document["description"] = "mutated"  # type: ignore[index]
    with pytest.raises(TypeError):
        snapshot.document["customProperties"]["tier"] = "mutated"
    await client.aclose()


async def test_aspect_reread_unwraps_datahub_restli_typed_envelope() -> None:
    document = {"description": "governed", "customProperties": {"tier": "gold"}}
    client = httpx.AsyncClient(
        base_url="https://datahub.example",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "aspect": {"com.linkedin.dataset.DatasetProperties": document},
                    "version": 0,
                },
                headers={"etag": "version-3"},
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
    assert dict(snapshot.document) == document
    await client.aclose()


async def test_aspect_reread_maps_missing_optional_aspect_to_empty_snapshot() -> None:
    client = httpx.AsyncClient(
        base_url="https://datahub.example",
        transport=httpx.MockTransport(lambda _: httpx.Response(404)),
    )
    gateway = HttpDataHubGateway(
        base_url="https://datahub.example", token="unused", timeout_seconds=1, client=client
    )

    snapshot = await gateway.read_aspect(external_urn="urn:li:dataset:test", aspect_name="domains")

    assert snapshot.content_hash == canonical_json_hash({})
    assert snapshot.source_version == "absent"
    assert dict(snapshot.document) == {}
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
                                    "properties": {
                                        "name": "wafer_events",
                                        "description": "events",
                                        "created": 1_721_260_800_000,
                                        "customProperties": [
                                            {
                                                "key": "datariver.seed.object_kind",
                                                "value": "table",
                                            },
                                            {
                                                "key": "datariver.seed.database_name",
                                                "value": "seed_catalog",
                                            },
                                        ],
                                    },
                                    "subTypes": {"typeNames": ["Table"]},
                                    "browsePathV2": {
                                        "path": [
                                            {
                                                "name": "manufacturing",
                                                "entity": {
                                                    "type": "DATASET",
                                                },
                                            },
                                        ]
                                    },
                                    "domain": {"domain": {"urn": "urn:li:domain:manufacturing"}},
                                    "ownership": {
                                        "owners": [{"owner": {"urn": "urn:li:corpGroup:yield"}}]
                                    },
                                    "globalTags": {
                                        "tags": [
                                            {"tag": {"name": "classification:confidential"}},
                                            {"tag": {"name": "tier:gold"}},
                                        ]
                                    },
                                    "glossaryTerms": {
                                        "terms": [
                                            {
                                                "term": {
                                                    "urn": "urn:li:glossaryTerm:wafer",
                                                    "name": "Wafer",
                                                }
                                            }
                                        ]
                                    },
                                    "schemaMetadata": {
                                        "fields": [
                                            {"fieldPath": "wafer_id"},
                                            {"fieldPath": "yield_pct"},
                                        ]
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
    assert page.items[0].database_name == "seed_catalog"
    assert page.items[0].schema_name == "manufacturing"
    assert page.items[0].domain_ref == "urn:li:domain:manufacturing"
    assert page.items[0].system_ref == "urn:li:dataPlatform:snowflake"
    assert page.items[0].asset_type == "TABLE"
    assert page.items[0].tags == ("classification:confidential", "tier:gold")
    assert page.items[0].glossary_terms == ("Wafer",)
    assert page.items[0].column_names == ("wafer_id", "yield_pct")
    assert page.items[0].created_at is not None
    assert page.items[0].classification is Classification.CONFIDENTIAL
    assert page.next_offset == 1
    assert page.total == 2
    await client.aclose()


def test_oracle_browse_container_aliases_map_without_parsing_a_dataset_urn() -> None:
    database_name, schema_name = _catalog_hierarchy_from_browse_path(
        {
            "path": [
                {
                    "entity": {
                        "type": "CONTAINER",
                        "properties": {"name": "FINANCE"},
                        "subTypes": {"typeNames": ["Oracle_Database"]},
                    }
                },
                {
                    "entity": {
                        "type": "CONTAINER",
                        "properties": {"name": "AP_PAYABLE"},
                        "subTypes": {"typeNames": ["Oracle-Schema"]},
                    }
                },
            ]
        }
    )

    assert database_name == "FINANCE"
    assert schema_name == "AP_PAYABLE"


def test_browse_path_schema_segment_is_used_without_inferring_a_database() -> None:
    database_name, schema_name = _catalog_hierarchy_from_browse_path(
        {"path": [{"name": "semiconductor_seed", "entity": None}]}
    )

    assert database_name is None
    assert schema_name == "semiconductor_seed"


async def test_lineage_contract_returns_only_typed_bounded_paths() -> None:
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "dataset(urn: $urn)" in body["query"]
        assert body["variables"]["input"] == {
            "direction": "UPSTREAM",
            "start": 0,
            "count": 100,
        }
        urn = body["variables"]["urn"]
        calls.append(urn)
        relationships = {
            "urn:li:dataset:center": [
                {"entity": {"urn": "urn:li:dataset:middle", "type": "DATASET"}},
                {"entity": {"urn": "urn:li:dataJob:hidden", "type": "DATA_JOB"}},
            ],
            "urn:li:dataset:middle": [
                {"entity": {"urn": "urn:li:dataset:upstream", "type": "DATASET"}}
            ],
        }[urn]
        return httpx.Response(
            200,
            json={
                "data": {
                    "dataset": {
                        "urn": urn,
                        "lineage": {
                            "total": 3 if urn == "urn:li:dataset:center" else 1,
                            "filtered": 0,
                            "relationships": relationships,
                        },
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

    page = await gateway.get_lineage(
        external_urn="urn:li:dataset:center", direction="UPSTREAM", depth=2
    )

    assert page.partial is True
    assert page.total == 3
    assert calls == ["urn:li:dataset:center", "urn:li:dataset:middle"]
    upstream = next(item for item in page.items if item.external_urn == "urn:li:dataset:upstream")
    assert upstream.degree == 2
    assert upstream.paths == (
        (
            "urn:li:dataset:center",
            "urn:li:dataset:middle",
            "urn:li:dataset:upstream",
        ),
    )
    assert upstream.truncated_children is False
    await client.aclose()


async def test_circuit_breaker_opens_after_bounded_retryable_failures() -> None:
    calls = 0
    metrics = HttpMetrics()

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
        telemetry=metrics,
    )

    for expected_code in ("503", "503", "CIRCUIT_OPEN"):
        with pytest.raises(ExternalDependencyError) as caught:
            await gateway.get_asset("urn:li:dataset:test")
        assert caught.value.details["provider_code"] == expected_code

    assert calls == 2
    rendered_metrics = metrics.render().decode()
    assert (
        'datariver_datahub_requests_total{operation="graphql",outcome="server_error"} 2.0'
        in rendered_metrics
    )
    assert (
        'datariver_datahub_requests_total{operation="graphql",outcome="circuit_open"} 1.0'
        in rendered_metrics
    )
    assert "datariver_datahub_circuit_state 1.0" in rendered_metrics
    await client.aclose()


async def test_bulkhead_rejects_excess_work_and_records_the_rejection() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    metrics = HttpMetrics()

    async def handler(_: httpx.Request) -> httpx.Response:
        entered.set()
        await release.wait()
        return httpx.Response(
            200,
            json={
                "data": {
                    "entity": {
                        "urn": "urn:li:dataset:test",
                        "type": "DATASET",
                        "ownership": {"owners": []},
                        "globalTags": {"tags": []},
                        "glossaryTerms": {"terms": []},
                        "schemaMetadata": {"fields": []},
                    }
                }
            },
        )

    client = httpx.AsyncClient(
        base_url="https://datahub.example", transport=httpx.MockTransport(handler)
    )
    gateway = HttpDataHubGateway(
        base_url="https://datahub.example",
        token="unused",
        timeout_seconds=1,
        maximum_concurrency=1,
        queue_timeout_seconds=0.01,
        client=client,
        telemetry=metrics,
    )

    first = asyncio.create_task(gateway.get_asset("urn:li:dataset:test"))
    await entered.wait()
    with pytest.raises(ExternalDependencyError) as caught:
        await gateway.get_asset("urn:li:dataset:test")
    assert caught.value.details["provider_code"] == "OVERLOADED"
    release.set()
    await first

    rendered_metrics = metrics.render().decode()
    assert 'datariver_datahub_queue_rejections_total{operation="graphql"} 1.0' in rendered_metrics
    assert (
        'datariver_datahub_requests_total{operation="graphql",outcome="overloaded"} 1.0'
        in rendered_metrics
    )
    await client.aclose()


async def test_capability_is_healthy_for_the_approved_datahub_release() -> None:
    client = httpx.AsyncClient(
        base_url="https://datahub.example",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=DATAHUB_V160_CONFIG)
        ),
    )
    gateway = HttpDataHubGateway(
        base_url="https://datahub.example",
        token="unused",
        timeout_seconds=1,
        expected_version="v1.6.0",
        version_enforcement="enforce",
        client=client,
    )

    capability = await gateway.capability()

    assert capability.state == "healthy"
    assert capability.detail_code is None
    await client.aclose()


async def test_capability_reports_a_datahub_release_mismatch_as_degraded() -> None:
    client = httpx.AsyncClient(
        base_url="https://datahub.example",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"versions": {"acryldata/datahub": {"version": "v1.6.0rc1"}}},
            )
        ),
    )
    gateway = HttpDataHubGateway(
        base_url="https://datahub.example",
        token="unused",
        timeout_seconds=1,
        expected_version="v1.6.0",
        version_enforcement="report",
        client=client,
    )

    capability = await gateway.capability()

    assert capability.state == "degraded"
    assert capability.detail_code == "VERSION_MISMATCH"
    await client.aclose()


async def test_development_capability_bypass_accepts_release_candidate() -> None:
    client = httpx.AsyncClient(
        base_url="https://datahub.example",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"versions": {"acryldata/datahub": {"version": "v1.6.0rc1"}}},
            )
        ),
    )
    gateway = HttpDataHubGateway(
        base_url="https://datahub.example",
        token="unused",
        timeout_seconds=1,
        expected_version="v1.6.0",
        version_enforcement="report",
        development_version_bypass=True,
        client=client,
    )

    capability = await gateway.capability()

    assert capability.state == "healthy"
    assert capability.detail_code is None
    await client.aclose()


async def test_capability_is_healthy_for_an_explicitly_allowed_same_release_candidate() -> None:
    client = httpx.AsyncClient(
        base_url="https://datahub.example",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"versions": {"acryldata/datahub": {"version": "v1.6.0rc1"}}},
            )
        ),
    )
    gateway = HttpDataHubGateway(
        base_url="https://datahub.example",
        token="unused",
        timeout_seconds=1,
        expected_version="v1.6.0",
        allowed_versions=("v1.6.0rc1",),
        version_enforcement="enforce",
        client=client,
    )

    capability = await gateway.capability()

    assert capability.state == "healthy"
    assert capability.detail_code is None
    await client.aclose()


async def test_enforcement_allows_graphql_for_an_explicitly_allowed_release_candidate() -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/config":
            return httpx.Response(
                200,
                json={"versions": {"acryldata/datahub": {"version": "v1.6.0rc1"}}},
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "entity": {
                        "urn": "urn:li:dataset:test",
                        "type": "DATASET",
                        "ownership": {"owners": []},
                        "globalTags": {"tags": []},
                        "glossaryTerms": {"terms": []},
                        "schemaMetadata": {"fields": []},
                    }
                }
            },
        )

    client = httpx.AsyncClient(
        base_url="https://datahub.example",
        transport=httpx.MockTransport(handler),
    )
    gateway = HttpDataHubGateway(
        base_url="https://datahub.example",
        token="unused",
        timeout_seconds=1,
        expected_version="v1.6.0",
        allowed_versions=("v1.6.0rc1",),
        version_enforcement="enforce",
        client=client,
    )

    asset = await gateway.get_asset("urn:li:dataset:test")

    assert asset.tags == ()
    assert asset.schema_fields == ()
    assert requested_paths == ["/config", "/api/graphql"]
    await client.aclose()


async def test_enforcement_blocks_graphql_before_an_unapproved_datahub_release() -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/config":
            return httpx.Response(
                200,
                json={"versions": {"acryldata/datahub": {"version": "v1.6.0rc1"}}},
            )
        return httpx.Response(500, json={"message": "must not be called"})

    client = httpx.AsyncClient(
        base_url="https://datahub.example",
        transport=httpx.MockTransport(handler),
    )
    gateway = HttpDataHubGateway(
        base_url="https://datahub.example",
        token="unused",
        timeout_seconds=1,
        expected_version="v1.6.0",
        version_enforcement="enforce",
        client=client,
    )

    with pytest.raises(ExternalDependencyError) as caught:
        await gateway.get_asset("urn:li:dataset:test")

    assert caught.value.details["retryable"] is False
    assert caught.value.details["provider_code"] == "VERSION_MISMATCH"
    assert requested_paths == ["/config"]
    await client.aclose()
