from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from datariver.interfaces.http.schemas import PageMeta


class QualityCapabilityAxisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Literal[
        "read_access",
        "profile_readiness",
        "rule_authoring",
        "activation",
        "manual_execution",
        "scheduling",
        "operations",
    ]
    state: Literal["AVAILABLE", "DENIED", "UNAVAILABLE"]
    reason_code: str | None = None


class QualityCapabilityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["QUALITY_CAPABILITY_V1"] = "QUALITY_CAPABILITY_V1"
    observed_at: datetime
    valid_until: datetime
    cache_scope: str = Field(pattern=r"^[0-9a-f]{64}$")
    axes: list[QualityCapabilityAxisResponse]


class QualityRuleDefinitionContractResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["NOT_NULL", "RANGE", "REGEX"]
    available: bool
    reason_code: str | None = None
    parameter_contract: dict[str, object]


class QualityRuleDefinitionContractsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["QUALITY_TYPED_RULES_V1"] = "QUALITY_TYPED_RULES_V1"
    items: list[QualityRuleDefinitionContractResponse]


class QualityTrendPointResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bucket_start: datetime
    passed_count: int = Field(ge=0)
    advisory_failed_count: int = Field(ge=0)
    blocking_failed_count: int = Field(ge=0)
    evaluated_rule_count: int = Field(ge=0)
    score_basis_points: int | None = Field(default=None, ge=0, le=10_000)


class QualityOverviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    availability: Literal["AVAILABLE", "PARTIAL", "UNAVAILABLE"]
    freshness: Literal["CURRENT", "STALE", "UNKNOWN"]
    as_of: datetime
    authorization_valid_until: datetime
    overall_state: Literal["PASS", "WARN", "FAIL", "UNKNOWN"]
    active_rule_set_count: int = Field(ge=0)
    evaluated_rule_set_count: int = Field(ge=0)
    unknown_rule_set_count: int = Field(ge=0)
    passed_count: int = Field(ge=0)
    advisory_failed_count: int = Field(ge=0)
    blocking_failed_count: int = Field(ge=0)
    evaluated_rule_count: int = Field(ge=0)
    score_basis_points: int | None = Field(default=None, ge=0, le=10_000)
    coverage_basis_points: int | None = Field(default=None, ge=0, le=10_000)
    trend: list[QualityTrendPointResponse]
    failure_code: str | None = None


class QualityAssetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: UUID
    name: str
    platform: str | None
    database_name: str | None
    schema_name: str | None
    classification: str
    lifecycle: str
    active_rule_set_count: int = Field(ge=0)
    latest_run_state: str | None
    latest_quality_outcome: str | None
    latest_score_basis_points: int | None = Field(default=None, ge=0, le=10_000)
    profile_readiness: Literal["READY", "STALE", "UNAVAILABLE", "REDACTED"]
    profile_observed_at: datetime | None


class QualityRuleSetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_set_id: UUID
    name: str
    asset_id: UUID
    asset_name: str
    state: str
    active_version_id: UUID | None
    active_version_number: int | None
    active_version_state: str | None
    rule_count: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime
    version: int = Field(ge=1)


class QualityRuleVersionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: UUID
    version_number: int = Field(ge=1)
    state: str
    author_id: UUID
    reviewed_by: UUID | None
    activated_by: UUID | None
    rule_count: int = Field(ge=0)
    schedule_mode: str
    created_at: datetime
    updated_at: datetime
    version: int = Field(ge=1)


class QualityRuleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_definition_id: UUID
    version_id: UUID
    ordinal: int = Field(ge=1)
    field_identifier: str
    kind: str
    severity: str
    parameters: dict[str, object]


class QualityRuleSetDetailItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_set: QualityRuleSetResponse
    versions: list[QualityRuleVersionResponse]
    definitions: list[QualityRuleResponse]


class QualityRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    rule_set_id: UUID
    rule_set_name: str
    asset_id: UUID
    asset_name: str
    trigger_kind: str
    state: str
    quality_outcome: str
    score_basis_points: int | None = Field(default=None, ge=0, le=10_000)
    passed_count: int | None = Field(default=None, ge=0)
    advisory_failed_count: int | None = Field(default=None, ge=0)
    blocking_failed_count: int | None = Field(default=None, ge=0)
    created_at: datetime
    completed_at: datetime | None
    failure_code: str | None
    version: int = Field(ge=1)


class QualityResultResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_id: UUID
    rule_definition_id: UUID
    field_identifier: str
    kind: str
    severity: str
    outcome: str
    evaluated_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    unexpected_count: int = Field(ge=0)
    missing_ratio: float = Field(ge=0, le=1)
    unexpected_ratio: float = Field(ge=0, le=1)
    duration_ms: int = Field(ge=0)
    occurred_at: datetime


class QualityIssueResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    asset_id: UUID
    asset_name: str
    field_identifier: str
    kind: str
    severity: str
    outcome: str
    occurrence_count: int = Field(ge=1)
    last_observed_at: datetime


class QualityReadMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cache_scope: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_at: datetime
    authorization_valid_until: datetime


class QualityAssetListResponse(QualityReadMetadata):
    items: list[QualityAssetResponse]
    page: PageMeta


class QualityAssetDetailResponse(QualityReadMetadata):
    item: QualityAssetResponse


class QualityRuleSetListResponse(QualityReadMetadata):
    items: list[QualityRuleSetResponse]
    page: PageMeta


class QualityRuleSetDetailResponse(QualityReadMetadata):
    item: QualityRuleSetDetailItemResponse


class QualityRunListResponse(QualityReadMetadata):
    items: list[QualityRunResponse]
    page: PageMeta


class QualityRunDetailResponse(QualityReadMetadata):
    item: QualityRunResponse


class QualityResultListResponse(QualityReadMetadata):
    items: list[QualityResultResponse]
    page: PageMeta


class QualityIssueListResponse(QualityReadMetadata):
    items: list[QualityIssueResponse]
    page: PageMeta
