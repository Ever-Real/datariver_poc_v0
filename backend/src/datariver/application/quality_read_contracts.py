from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from datariver.application.classification_access import ClassificationAccessSnapshot
from datariver.domain.authz import SubjectAttributes

CapabilityState = Literal["AVAILABLE", "DENIED", "UNAVAILABLE"]
SectionAvailability = Literal["AVAILABLE", "PARTIAL", "UNAVAILABLE"]
SectionFreshness = Literal["CURRENT", "STALE", "UNKNOWN"]
ProfileReadiness = Literal["READY", "STALE", "UNAVAILABLE", "REDACTED"]


@dataclass(frozen=True, slots=True)
class QualityReadContext:
    subject: SubjectAttributes
    access: ClassificationAccessSnapshot
    observed_at: datetime
    authorization_valid_until: datetime
    cache_scope: str
    profile_allowed: bool


@dataclass(frozen=True, slots=True)
class QualityCapabilityAxis:
    id: str
    state: CapabilityState
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class QualityCapability:
    observed_at: datetime
    valid_until: datetime
    cache_scope: str
    axes: tuple[QualityCapabilityAxis, ...]


@dataclass(frozen=True, slots=True)
class QualityTrendPoint:
    bucket_start: datetime
    passed_count: int
    advisory_failed_count: int
    blocking_failed_count: int
    evaluated_rule_count: int
    score_basis_points: int | None


@dataclass(frozen=True, slots=True)
class QualityOverview:
    availability: SectionAvailability
    freshness: SectionFreshness
    as_of: datetime
    authorization_valid_until: datetime
    overall_state: str
    active_rule_set_count: int
    evaluated_rule_set_count: int
    unknown_rule_set_count: int
    passed_count: int
    advisory_failed_count: int
    blocking_failed_count: int
    evaluated_rule_count: int
    score_basis_points: int | None
    coverage_basis_points: int | None
    trend: tuple[QualityTrendPoint, ...]
    failure_code: str | None = None


@dataclass(frozen=True, slots=True)
class QualityAssetSummary:
    asset_id: UUID
    name: str
    platform: str | None
    database_name: str | None
    schema_name: str | None
    classification: str
    lifecycle: str
    active_rule_set_count: int
    latest_run_state: str | None
    latest_quality_outcome: str | None
    latest_score_basis_points: int | None
    profile_readiness: ProfileReadiness
    profile_observed_at: datetime | None


@dataclass(frozen=True, slots=True)
class QualityRuleVersionSummary:
    version_id: UUID
    version_number: int
    state: str
    author_id: UUID
    reviewed_by: UUID | None
    activated_by: UUID | None
    rule_count: int
    schedule_mode: str
    created_at: datetime
    updated_at: datetime
    version: int


@dataclass(frozen=True, slots=True)
class QualityRuleDefinitionSummary:
    rule_definition_id: UUID
    version_id: UUID
    ordinal: int
    field_identifier: str
    kind: str
    severity: str
    parameters: dict[str, object]


@dataclass(frozen=True, slots=True)
class QualityRuleSetSummary:
    rule_set_id: UUID
    name: str
    asset_id: UUID
    asset_name: str
    state: str
    active_version_id: UUID | None
    active_version_number: int | None
    active_version_state: str | None
    rule_count: int
    created_at: datetime
    updated_at: datetime
    version: int


@dataclass(frozen=True, slots=True)
class QualityRuleSetDetail:
    rule_set: QualityRuleSetSummary
    versions: tuple[QualityRuleVersionSummary, ...]
    definitions: tuple[QualityRuleDefinitionSummary, ...]


@dataclass(frozen=True, slots=True)
class QualityRunSummary:
    run_id: UUID
    rule_set_id: UUID
    rule_set_name: str
    asset_id: UUID
    asset_name: str
    trigger_kind: str
    state: str
    quality_outcome: str
    score_basis_points: int | None
    passed_count: int | None
    advisory_failed_count: int | None
    blocking_failed_count: int | None
    created_at: datetime
    completed_at: datetime | None
    failure_code: str | None
    version: int


@dataclass(frozen=True, slots=True)
class QualityResultSummary:
    result_id: UUID
    rule_definition_id: UUID
    field_identifier: str
    kind: str
    severity: str
    outcome: str
    evaluated_count: int
    missing_count: int
    unexpected_count: int
    missing_ratio: Decimal
    unexpected_ratio: Decimal
    duration_ms: int
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class QualityIssueSummary:
    issue_id: str
    asset_id: UUID
    asset_name: str
    field_identifier: str
    kind: str
    severity: str
    outcome: str
    occurrence_count: int
    last_observed_at: datetime


@dataclass(frozen=True, slots=True)
class QualityAssetPage:
    items: tuple[QualityAssetSummary, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class QualityRuleSetPage:
    items: tuple[QualityRuleSetSummary, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class QualityRunPage:
    items: tuple[QualityRunSummary, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class QualityResultPage:
    items: tuple[QualityResultSummary, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class QualityIssuePage:
    items: tuple[QualityIssueSummary, ...]
    next_cursor: str | None
