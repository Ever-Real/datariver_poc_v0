from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from datariver.domain.authz import Classification


class ProfileKind(StrEnum):
    FULL = "FULL"
    SAMPLE = "SAMPLE"
    PARTITION = "PARTITION"
    QUERY = "QUERY"
    UNKNOWN = "UNKNOWN"


class ProfileCompleteness(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"


@dataclass(frozen=True, slots=True)
class ColumnProfileMetric:
    field_path: str
    null_count: int | None
    null_proportion: float | None
    unique_count: int | None
    unique_proportion: float | None


@dataclass(frozen=True, slots=True)
class DataHubProfileObservation:
    kind: ProfileKind
    completeness: ProfileCompleteness
    profiled_at: datetime
    observed_at: datetime
    stale_at: datetime
    row_count: int | None
    column_count: int | None
    size_bytes: int | None
    columns: tuple[ColumnProfileMetric, ...]
    provenance_key_id: str | None
    provenance_fingerprint: str | None
    provider_version: str
    provider_contract_hash: str
    query_hash: str
    provider_config_hash: str
    normalized_payload_hash: str


@dataclass(frozen=True, slots=True)
class CatalogProfileTarget:
    workspace_id: UUID
    asset_id: UUID
    external_urn: str
    source_version: str
    classification: Classification
    system_id: UUID | None
    domain_id: UUID | None


@dataclass(frozen=True, slots=True)
class CatalogProfileProjectionCommand:
    target: CatalogProfileTarget
    observation: DataHubProfileObservation
    source_watermark_hash: str


@dataclass(frozen=True, slots=True)
class CatalogProfileProjectionResult:
    snapshot_id: UUID
    snapshot_identity_hash: str
    created: bool
    last_observed_at: datetime


@dataclass(frozen=True, slots=True)
class CatalogProfileCollectionResult:
    availability: str
    failure_code: str | None
    projection: CatalogProfileProjectionResult | None
