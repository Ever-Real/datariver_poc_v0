from __future__ import annotations

import hashlib
import hmac
import math
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from datariver.application.catalog_profile_contracts import (
    ColumnProfileMetric,
    DataHubProfileObservation,
    ProfileCompleteness,
    ProfileKind,
)
from datariver.application.errors import ExternalDependencyError
from datariver.domain.common import canonical_json_hash
from datariver.infrastructure.datahub.http import HttpDataHubGateway

MAX_PROFILE_FIELDS = 1_000
MAX_PROFILE_FIELD_PATH_CHARACTERS = 4_096
MAX_PROFILE_PARTITION_CHARACTERS = 4_096
MAX_PROFILE_COUNT = 9_223_372_036_854_775_807
PROFILE_QUERY_CONTRACT_VERSION = "datahub-v1.6-dataset-profile-v1"
_SAMPLE_MARKER = re.compile(r"^SAMPLE(?: \(sample rows [0-9]+\))?$")

PROFILE_QUERY = """
query DataRiverDatasetProfile($urn: String!) {
  entity(urn: $urn) {
    urn
    type
    ... on Dataset {
      profiles: datasetProfiles(limit: 1) {
        timestampMillis
        rowCount
        columnCount
        sizeInBytes
        partitionSpec {
          type
          partition
        }
        fieldProfiles {
          fieldPath
          nullCount
          nullProportion
          uniqueCount
          uniqueProportion
        }
      }
    }
  }
}
"""


def _contract_error(message: str) -> ExternalDependencyError:
    return ExternalDependencyError(
        message,
        dependency="datahub",
        retryable=False,
        provider_code="PROFILE_CONTRACT_DRIFT",
    )


def _count(value: object, *, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise _contract_error(f"DataHub returned an invalid {field}.")
    if value < 0 or value > MAX_PROFILE_COUNT:
        raise _contract_error(f"DataHub returned an out-of-range {field}.")
    return value


def _proportion(value: object, *, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _contract_error(f"DataHub returned an invalid {field}.")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0 <= normalized <= 1:
        raise _contract_error(f"DataHub returned an out-of-range {field}.")
    return normalized


def _consistent_ratio(*, count: int | None, proportion: float | None, rows: int | None) -> bool:
    if count is None or proportion is None or rows is None:
        return True
    if rows == 0:
        return count == 0 and proportion == 0
    if count > rows:
        return False
    return abs(proportion - (count / rows)) <= max(1e-9, 1 / rows)


def _profile_kind(partition_spec: object) -> tuple[ProfileKind, str | None, bool]:
    if not isinstance(partition_spec, dict):
        return ProfileKind.UNKNOWN, None, False
    raw_type = partition_spec.get("type")
    raw_partition = partition_spec.get("partition")
    if not isinstance(raw_type, str):
        return ProfileKind.UNKNOWN, None, False
    if raw_partition is not None and not isinstance(raw_partition, str):
        return ProfileKind.UNKNOWN, None, False
    partition = raw_partition.strip() if isinstance(raw_partition, str) else ""
    if len(partition) > MAX_PROFILE_PARTITION_CHARACTERS:
        return ProfileKind.UNKNOWN, None, False
    if raw_type == "FULL_TABLE" and partition == "FULL_TABLE_SNAPSHOT":
        return ProfileKind.FULL, None, True
    if raw_type == "QUERY" and _SAMPLE_MARKER.fullmatch(partition):
        return ProfileKind.SAMPLE, None, True
    if raw_type == "PARTITION" and partition:
        return ProfileKind.PARTITION, partition, True
    if raw_type == "QUERY" and partition:
        return ProfileKind.QUERY, partition, True
    return ProfileKind.UNKNOWN, None, False


def _provenance_hmac(
    *,
    raw_partition: str | None,
    kind: ProfileKind,
    workspace_id: UUID,
    asset_id: UUID,
    key: bytes,
) -> str | None:
    if raw_partition is None or kind not in {ProfileKind.PARTITION, ProfileKind.QUERY}:
        return None
    message = "\x00".join(
        (
            "DATARIVER_DATAHUB_PROFILE_PROVENANCE_V1",
            str(workspace_id),
            str(asset_id),
            kind.value,
            raw_partition,
        )
    ).encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def _timestamp(value: object) -> datetime:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _contract_error("DataHub returned an invalid profile timestamp.")
    try:
        return datetime.fromtimestamp(value / 1_000, tz=UTC)
    except (OverflowError, OSError, ValueError) as error:
        raise _contract_error("DataHub returned an invalid profile timestamp.") from error


def parse_profile_response(
    payload: object,
    *,
    external_urn: str,
    workspace_id: UUID,
    asset_id: UUID,
    observed_at: datetime,
    freshness_sla_seconds: int,
    provider_version: str,
    provider_config_hash: str,
    provenance_key_id: str,
    provenance_key: bytes,
) -> DataHubProfileObservation | None:
    if freshness_sla_seconds <= 0:
        raise ValueError("Profile freshness requires an approved positive SLA.")
    if not provenance_key_id or len(provenance_key_id) > 128 or len(provenance_key) < 32:
        raise ValueError("Profile provenance requires a bounded key ID and at least 256-bit key.")
    entity = payload.get("entity") if isinstance(payload, dict) else None
    if entity is None:
        return None
    if (
        not isinstance(entity, dict)
        or entity.get("urn") != external_urn
        or entity.get("type") != "DATASET"
    ):
        raise _contract_error("DataHub returned a mismatched profile entity.")
    raw_profiles = entity.get("profiles")
    if not isinstance(raw_profiles, list):
        raise _contract_error("DataHub returned an invalid profile collection.")
    if not raw_profiles:
        return None
    if len(raw_profiles) != 1 or not isinstance(raw_profiles[0], dict):
        raise _contract_error("DataHub returned an ambiguous profile collection.")
    raw_profile: dict[str, Any] = raw_profiles[0]
    profiled_at = _timestamp(raw_profile.get("timestampMillis"))
    row_count = _count(raw_profile.get("rowCount"), field="row count")
    column_count = _count(raw_profile.get("columnCount"), field="column count")
    size_bytes = _count(raw_profile.get("sizeInBytes"), field="size in bytes")
    kind, raw_partition, provenance_complete = _profile_kind(raw_profile.get("partitionSpec"))
    raw_fields = raw_profile.get("fieldProfiles")
    if raw_fields is None:
        raw_fields = []
    if not isinstance(raw_fields, list) or len(raw_fields) > MAX_PROFILE_FIELDS:
        raise _contract_error("DataHub returned an invalid field profile collection.")
    columns: list[ColumnProfileMetric] = []
    seen_paths: set[str] = set()
    complete = provenance_complete and all(
        value is not None for value in (row_count, column_count, size_bytes)
    )
    for raw_field in raw_fields:
        if not isinstance(raw_field, dict):
            raise _contract_error("DataHub returned an invalid field profile.")
        raw_path = raw_field.get("fieldPath")
        path = raw_path.strip() if isinstance(raw_path, str) else ""
        if not path or len(path) > MAX_PROFILE_FIELD_PATH_CHARACTERS or path in seen_paths:
            raise _contract_error("DataHub returned an invalid or duplicate field path.")
        seen_paths.add(path)
        null_count = _count(raw_field.get("nullCount"), field="field null count")
        null_proportion = _proportion(
            raw_field.get("nullProportion"),
            field="field null proportion",
        )
        unique_count = _count(raw_field.get("uniqueCount"), field="field unique count")
        unique_proportion = _proportion(
            raw_field.get("uniqueProportion"),
            field="field unique proportion",
        )
        if not _consistent_ratio(
            count=null_count,
            proportion=null_proportion,
            rows=row_count,
        ) or not _consistent_ratio(
            count=unique_count,
            proportion=unique_proportion,
            rows=row_count,
        ):
            raise _contract_error("DataHub returned inconsistent field profile metrics.")
        complete = complete and all(
            value is not None
            for value in (
                null_count,
                null_proportion,
                unique_count,
                unique_proportion,
            )
        )
        columns.append(
            ColumnProfileMetric(
                field_path=path,
                null_count=null_count,
                null_proportion=null_proportion,
                unique_count=unique_count,
                unique_proportion=unique_proportion,
            )
        )
    if column_count is not None and len(columns) != column_count:
        complete = False
    fingerprint = _provenance_hmac(
        raw_partition=raw_partition,
        kind=kind,
        workspace_id=workspace_id,
        asset_id=asset_id,
        key=provenance_key,
    )
    normalized_payload = {
        "column_count": column_count,
        "columns": [
            {
                "field_path": item.field_path,
                "null_count": item.null_count,
                "null_proportion": item.null_proportion,
                "unique_count": item.unique_count,
                "unique_proportion": item.unique_proportion,
            }
            for item in sorted(columns, key=lambda item: item.field_path)
        ],
        "kind": kind.value,
        "profiled_at": profiled_at.isoformat(),
        "provenance_fingerprint": fingerprint,
        "provenance_key_id": provenance_key_id if fingerprint is not None else None,
        "row_count": row_count,
        "size_bytes": size_bytes,
    }
    query_hash = canonical_json_hash(PROFILE_QUERY)
    provider_contract_hash = canonical_json_hash(
        {
            "contract_version": PROFILE_QUERY_CONTRACT_VERSION,
            "provider_version": provider_version,
            "query_hash": query_hash,
        }
    )
    return DataHubProfileObservation(
        kind=kind,
        completeness=(ProfileCompleteness.COMPLETE if complete else ProfileCompleteness.PARTIAL),
        profiled_at=profiled_at,
        observed_at=observed_at,
        stale_at=profiled_at + timedelta(seconds=freshness_sla_seconds),
        row_count=row_count,
        column_count=column_count,
        size_bytes=size_bytes,
        columns=tuple(sorted(columns, key=lambda item: item.field_path)),
        provenance_key_id=provenance_key_id if fingerprint is not None else None,
        provenance_fingerprint=fingerprint,
        provider_version=provider_version,
        provider_contract_hash=provider_contract_hash,
        query_hash=query_hash,
        provider_config_hash=provider_config_hash,
        normalized_payload_hash=canonical_json_hash(normalized_payload),
    )


class HttpDataHubProfileGateway(HttpDataHubGateway):
    def __init__(
        self,
        *,
        provider_config_hash: str,
        freshness_sla_seconds: int,
        provenance_key_id: str,
        provenance_key: bytes,
        **kwargs: Any,
    ) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", provider_config_hash):
            raise ValueError("DataHub profile configuration hash must be lowercase SHA-256.")
        if freshness_sla_seconds <= 0:
            raise ValueError("DataHub profile freshness SLA must be explicitly configured.")
        super().__init__(**kwargs)
        self._profile_provider_config_hash = provider_config_hash
        self._profile_freshness_sla_seconds = freshness_sla_seconds
        self._profile_provenance_key_id = provenance_key_id
        self._profile_provenance_key = provenance_key

    async def get_profile(
        self,
        *,
        external_urn: str,
        workspace_id: UUID,
        asset_id: UUID,
    ) -> DataHubProfileObservation | None:
        observed_at = datetime.now(tz=UTC)
        data = await self._graphql(PROFILE_QUERY, {"urn": external_urn})
        observed_version = self.observed_version
        if observed_version is None:
            raise _contract_error("DataHub version evidence is unavailable.")
        return parse_profile_response(
            data,
            external_urn=external_urn,
            workspace_id=workspace_id,
            asset_id=asset_id,
            observed_at=observed_at,
            freshness_sla_seconds=self._profile_freshness_sla_seconds,
            provider_version=observed_version,
            provider_config_hash=self._profile_provider_config_hash,
            provenance_key_id=self._profile_provenance_key_id,
            provenance_key=self._profile_provenance_key,
        )
