from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from datariver.interfaces.http.schemas import PageMeta


class QualityCapabilityAxisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Literal[
        "read_access",
        "profile_readiness",
        "rule_authoring",
        "review",
        "activation",
        "manual_execution",
        "scheduling",
        "operations",
    ]
    state: Literal["AVAILABLE", "DENIED", "UNAVAILABLE"]
    reason_code: str | None = None


class QualityCapabilityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["QUALITY_CAPABILITY_V2"] = "QUALITY_CAPABILITY_V2"
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


class QualityAssetSummaryBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_ids: list[UUID] = Field(min_length=1, max_length=100)

    @field_validator("asset_ids")
    @classmethod
    def unique_assets(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("asset_ids must be unique")
        return value


class QualityAssetSummaryBatchResponse(QualityReadMetadata):
    items: list[QualityAssetResponse]


class QualityAuthoringFieldResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_identifier: str = Field(min_length=1, max_length=255)
    display_path: str = Field(min_length=1, max_length=255)
    logical_type: Literal[
        "STRING",
        "INTEGER",
        "DECIMAL",
        "DATE",
        "TIMESTAMP",
        "BOOLEAN",
        "OTHER",
    ]
    supported_rule_kinds: list[Literal["NOT_NULL", "RANGE"]]


class QualityAssetAuthoringResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: Literal["READY", "UNAVAILABLE"]
    reason_code: str | None
    source_version: str
    schema_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    fields: list[QualityAuthoringFieldResponse]


class QualityAssetDetailResponse(QualityReadMetadata):
    item: QualityAssetResponse
    authoring: QualityAssetAuthoringResponse


class QualityAssetWorkspaceItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset: QualityAssetResponse
    rule_sets: list[QualityRuleSetResponse] = Field(max_length=50)
    runs: list[QualityRunResponse] = Field(max_length=50)
    trend: list[QualityTrendPointResponse] = Field(max_length=90)


class QualityAssetWorkspaceResponse(QualityReadMetadata):
    item: QualityAssetWorkspaceItemResponse


class QualityRuleDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_identifier: str = Field(min_length=1, max_length=255)
    kind: Literal["NOT_NULL", "RANGE"]
    severity: Literal["BLOCKING", "ADVISORY"]
    parameters: dict[str, object] = Field(default_factory=dict)


class QualityRuleBatchProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_prefix: str = Field(min_length=1, max_length=100)
    asset_ids: list[UUID] = Field(min_length=1, max_length=25)
    rules: list[QualityRuleDraftRequest] = Field(min_length=1, max_length=100)

    @field_validator("asset_ids")
    @classmethod
    def unique_assets(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("asset_ids must be unique")
        return value


class QualityRuleProposalItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: UUID
    rule_set_id: UUID
    version_id: UUID
    version: int = Field(ge=1)


class QualityRuleBatchProposalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[QualityRuleProposalItemResponse]
    replayed: bool


class QualityCommonRuleTemplateCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    rules: list[QualityRuleDraftRequest] = Field(min_length=1, max_length=100)


class QualityCommonRuleTemplateMapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_ids: list[UUID] = Field(min_length=1, max_length=25)

    @field_validator("asset_ids")
    @classmethod
    def unique_assets(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("asset_ids must be unique")
        return value


class QualityCommonRuleTemplateCreateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: UUID
    replayed: bool


class QualityCommonRuleTemplateRuleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_identifier: str
    kind: Literal["NOT_NULL", "RANGE"]
    severity: Literal["BLOCKING", "ADVISORY"]
    parameters: dict[str, object]


class QualityCommonRuleTemplateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: UUID
    name: str
    description: str | None
    rules: list[QualityCommonRuleTemplateRuleResponse] = Field(max_length=100)
    mapping_count: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime


class QualityCommonRuleTemplateMappingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: UUID
    asset_name: str
    platform: str | None
    database_name: str | None
    schema_name: str | None
    rule_set_id: UUID
    rule_set_name: str
    mapped_at: datetime


class QualityCommonRuleTemplateListResponse(QualityReadMetadata):
    items: list[QualityCommonRuleTemplateResponse] = Field(max_length=100)


class QualityCommonRuleTemplateDetailItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: QualityCommonRuleTemplateResponse
    mappings: list[QualityCommonRuleTemplateMappingResponse] = Field(max_length=500)


class QualityCommonRuleTemplateDetailResponse(QualityReadMetadata):
    item: QualityCommonRuleTemplateDetailItemResponse


class QualityRuleReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["APPROVE", "REJECT"]
    reason: str = Field(min_length=1, max_length=4000)


class QualityRuleVersionCommandResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_set_id: UUID
    version_id: UUID
    state: str
    version: int = Field(ge=1)


class QualityManualRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_set_id: UUID


class QualityManualRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    state: str
    created_at: datetime
    replayed: bool


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
