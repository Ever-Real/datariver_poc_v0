from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from datariver.application.catalog_profile_contracts import (
    DataHubProfileObservation,
    ProfileCompleteness,
    ProfileKind,
)
from datariver.application.errors import ExternalDependencyError
from datariver.infrastructure.datahub.profile_http import (
    PROFILE_QUERY,
    HttpDataHubProfileGateway,
    parse_profile_response,
)

WORKSPACE_ID = uuid4()
ASSET_ID = uuid4()
URN = "urn:li:dataset:(urn:li:dataPlatform:postgres,quality.orders,PROD)"
OBSERVED_AT = datetime(2026, 7, 30, 12, tzinfo=UTC)
PROVIDER_CONFIG_HASH = "a" * 64
KEY = b"k" * 32


def _payload(
    *,
    partition_type: str = "FULL_TABLE",
    partition: str = "FULL_TABLE_SNAPSHOT",
) -> dict[str, object]:
    return {
        "entity": {
            "urn": URN,
            "type": "DATASET",
            "profiles": [
                {
                    "timestampMillis": 1785411000000,
                    "rowCount": 4,
                    "columnCount": 2,
                    "sizeInBytes": 512,
                    "partitionSpec": {
                        "type": partition_type,
                        "partition": partition,
                    },
                    "fieldProfiles": [
                        {
                            "fieldPath": "customer_id",
                            "nullCount": 0,
                            "nullProportion": 0.0,
                            "uniqueCount": 4,
                            "uniqueProportion": 1.0,
                        },
                        {
                            "fieldPath": "status",
                            "nullCount": 1,
                            "nullProportion": 0.25,
                            "uniqueCount": 2,
                            "uniqueProportion": 0.5,
                        },
                    ],
                }
            ],
        }
    }


def _parse(payload: object, **overrides: object) -> DataHubProfileObservation | None:
    arguments = {
        "external_urn": URN,
        "workspace_id": WORKSPACE_ID,
        "asset_id": ASSET_ID,
        "observed_at": OBSERVED_AT,
        "freshness_sla_seconds": 3600,
        "provider_version": "v1.6.0",
        "provider_config_hash": PROVIDER_CONFIG_HASH,
        "provenance_key_id": "profile-hmac-2026-07",
        "provenance_key": KEY,
    }
    arguments.update(overrides)
    return parse_profile_response(payload, **arguments)  # type: ignore[arg-type]


def test_query_is_a_frozen_privacy_allowlist() -> None:
    for required in (
        "partitionSpec",
        "type",
        "partition",
        "fieldPath",
        "nullCount",
        "nullProportion",
        "uniqueCount",
        "uniqueProportion",
    ):
        assert required in PROFILE_QUERY
    for forbidden in (
        "profileType",
        "sampleValues",
        "distinctValueFrequencies",
        "min",
        "max",
        "mean",
        "median",
        "stdev",
        "quantiles",
        "histogram",
    ):
        assert forbidden not in PROFILE_QUERY


def test_full_profile_is_normalized_and_ordered_without_raw_partition() -> None:
    observation = _parse(_payload())

    assert observation is not None
    assert observation.kind is ProfileKind.FULL
    assert observation.completeness is ProfileCompleteness.COMPLETE
    assert tuple(metric.field_path for metric in observation.columns) == (
        "customer_id",
        "status",
    )
    assert observation.provenance_fingerprint is None
    assert observation.provenance_key_id is None
    assert "FULL_TABLE_SNAPSHOT" not in repr(observation)


@pytest.mark.parametrize(
    ("partition_type", "partition", "kind"),
    (
        ("QUERY", "SAMPLE", ProfileKind.SAMPLE),
        ("QUERY", "SAMPLE (sample rows 400)", ProfileKind.SAMPLE),
        ("PARTITION", "event_date=2026-07-30", ProfileKind.PARTITION),
        ("QUERY", "approved bounded query", ProfileKind.QUERY),
        ("FULL_TABLE", "not-canonical", ProfileKind.UNKNOWN),
        ("OTHER", "provider drift", ProfileKind.UNKNOWN),
    ),
)
def test_profile_kind_and_keyed_provenance_are_closed(
    partition_type: str,
    partition: str,
    kind: ProfileKind,
) -> None:
    observation = _parse(_payload(partition_type=partition_type, partition=partition))

    assert observation is not None
    assert observation.kind is kind
    if kind in {ProfileKind.PARTITION, ProfileKind.QUERY}:
        assert observation.provenance_key_id == "profile-hmac-2026-07"
        assert observation.provenance_fingerprint is not None
        assert len(observation.provenance_fingerprint) == 64
    else:
        assert observation.provenance_key_id is None
        assert observation.provenance_fingerprint is None
    if partition not in {item.value for item in ProfileKind}:
        assert partition not in repr(observation)


def test_hmac_is_scoped_and_key_rotation_changes_lineage() -> None:
    payload = _payload(partition_type="PARTITION", partition="tenant=private")
    first = _parse(payload)
    other_asset = _parse(payload, asset_id=uuid4())
    rotated = _parse(payload, provenance_key=b"r" * 32, provenance_key_id="rotated")

    assert first is not None and other_asset is not None and rotated is not None
    assert first.provenance_fingerprint != other_asset.provenance_fingerprint
    assert first.provenance_fingerprint != rotated.provenance_fingerprint
    assert "tenant=private" not in repr((first, other_asset, rotated))


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("nullCount", True),
        ("nullCount", -1),
        ("nullProportion", float("nan")),
        ("nullProportion", 1.1),
        ("uniqueCount", 5),
    ),
)
def test_invalid_or_inconsistent_metrics_fail_closed(field: str, value: object) -> None:
    payload = _payload()
    profile = payload["entity"]["profiles"][0]  # type: ignore[index]
    profile["fieldProfiles"][0][field] = value

    with pytest.raises(ExternalDependencyError) as caught:
        _parse(payload)

    assert caught.value.details["provider_code"] == "PROFILE_CONTRACT_DRIFT"
    assert "tenant=private" not in caught.value.message


def test_duplicate_field_and_mismatched_entity_fail_closed() -> None:
    duplicate = _payload()
    profile = duplicate["entity"]["profiles"][0]  # type: ignore[index]
    profile["fieldProfiles"][1]["fieldPath"] = "customer_id"
    with pytest.raises(ExternalDependencyError):
        _parse(duplicate)

    mismatched = _payload()
    mismatched["entity"]["urn"] = "urn:li:dataset:other"  # type: ignore[index]
    with pytest.raises(ExternalDependencyError):
        _parse(mismatched)


def test_missing_metric_and_unknown_provenance_are_partial_not_zero_filled() -> None:
    payload = _payload(partition_type="FULL_TABLE", partition="ambiguous")
    profile = payload["entity"]["profiles"][0]  # type: ignore[index]
    profile["fieldProfiles"][0]["nullCount"] = None

    observation = _parse(payload)

    assert observation is not None
    assert observation.kind is ProfileKind.UNKNOWN
    assert observation.completeness is ProfileCompleteness.PARTIAL
    assert observation.columns[0].null_count is None


async def test_gateway_uses_only_server_urn_and_verified_v160_contract() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/config":
            return httpx.Response(
                200,
                json={"versions": {"acryldata/datahub": {"version": "v1.6.0"}}},
            )
        body = json.loads(request.content)
        assert request.url.path == "/api/graphql"
        assert body == {"query": PROFILE_QUERY, "variables": {"urn": URN}}
        return httpx.Response(200, json={"data": _payload()})

    client = httpx.AsyncClient(
        base_url="https://datahub.example",
        transport=httpx.MockTransport(handler),
    )
    gateway = HttpDataHubProfileGateway(
        base_url="https://datahub.example",
        token="unused",
        timeout_seconds=1,
        expected_version="v1.6.0",
        version_enforcement="enforce",
        provider_config_hash=PROVIDER_CONFIG_HASH,
        freshness_sla_seconds=3600,
        provenance_key_id="profile-hmac-2026-07",
        provenance_key=KEY,
        client=client,
    )

    observation = await gateway.get_profile(
        external_urn=URN,
        workspace_id=WORKSPACE_ID,
        asset_id=ASSET_ID,
    )

    assert observation is not None
    assert observation.provider_version == "v1.6.0"
    await client.aclose()
