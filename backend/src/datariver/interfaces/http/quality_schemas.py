from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class QualityManagedRuleSetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indicator_id: Literal["ACCURACY", "COMPLETENESS", "TIMELINESS"]
    name: str = Field(min_length=1, max_length=100)
    definition: str = Field(min_length=1, max_length=1_000)
    calculation: str = Field(min_length=1, max_length=1_000)
    target_grain: Literal["FIELD", "TABLE"]
    rule_kinds: list[Literal["NOT_NULL", "RANGE", "REGEX"]] = Field(max_length=3)
    contract_version: Literal["QUALITY_MANAGED_INDICATORS_V1"]


class QualityDashboardRiskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    asset_id: UUID
    asset_name: str = Field(min_length=1, max_length=500)
    field_identifier: str | None = Field(default=None, max_length=255)
    severity: Literal["BLOCKING", "ADVISORY"]
    outcome: Literal["ADVISORY_FAIL", "BLOCKING_FAIL"]
    score_basis_points: int | None = Field(default=None, ge=0, le=10_000)
    evaluated_count: int | None = Field(default=None, ge=0)
    failed_count: int | None = Field(default=None, ge=0)
    observed_at: datetime | None
    detail: str = Field(min_length=1, max_length=1_000)


class QualityDashboardIndicatorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indicator_id: Literal["ACCURACY", "COMPLETENESS", "TIMELINESS"]
    counted_target_count: int = Field(ge=0)
    target_count: int = Field(ge=0)
    coverage_basis_points: int | None = Field(default=None, ge=0, le=10_000)
    score_basis_points: int | None = Field(default=None, ge=0, le=10_000)
    outcome: Literal["PASS", "WARN", "FAIL", "UNKNOWN"]
    risk_count: int = Field(ge=0)
    evaluated_value_count: int = Field(ge=0)
    report_state: Literal["FACTS_ONLY", "LLM_GENERATED", "UNAVAILABLE"]
    report_reason_code: str | None = Field(default=None, max_length=100)
    report_summary: str = Field(min_length=1, max_length=2_000)
    risks: list[QualityDashboardRiskResponse] = Field(max_length=50)


class QualitySchemaDashboardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    platform: str | None
    database_name: str | None
    schema_name: str | None
    table_count: int = Field(ge=0)
    covered_table_count: int = Field(ge=0)
    indicators: list[QualityDashboardIndicatorResponse] = Field(min_length=3, max_length=3)


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


class QualityDashboardResponse(QualityReadMetadata):
    contract_version: Literal["QUALITY_DASHBOARD_V1"] = "QUALITY_DASHBOARD_V1"
    as_of: datetime
    schema_count: int = Field(ge=0)
    table_count: int = Field(ge=0)
    active_rule_set_count: int = Field(ge=0)
    common_rule_template_count: int = Field(ge=0)
    covered_table_count: int = Field(ge=0)
    table_coverage_basis_points: int | None = Field(default=None, ge=0, le=10_000)
    managed_rule_sets: list[QualityManagedRuleSetResponse] = Field(min_length=3, max_length=3)
    schemas: list[QualitySchemaDashboardResponse] = Field(max_length=500)
    schemas_truncated: bool


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


class QualityScorePolicyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: Literal["UNWEIGHTED_RULE_PASS_RATE_V1"]
    policy_version: Literal[1]
    policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    calculation: str
    pass_condition: str
    warn_condition: str
    fail_condition: str
    unknown_condition: str


class QualityAssetFieldResponse(QualityAuthoringFieldResponse):
    configured_rule_count: int = Field(ge=0)
    active_rule_count: int = Field(ge=0)
    evaluated_rule_count: int = Field(ge=0)
    passed_count: int = Field(ge=0)
    advisory_failed_count: int = Field(ge=0)
    blocking_failed_count: int = Field(ge=0)
    latest_score_basis_points: int | None = Field(default=None, ge=0, le=10_000)
    latest_quality_outcome: Literal["PASS", "WARN", "FAIL", "UNKNOWN"]
    latest_evaluated_at: datetime | None


class QualityAssetWorkspaceItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset: QualityAssetResponse
    rule_sets: list[QualityRuleSetResponse] = Field(max_length=50)
    runs: list[QualityRunResponse] = Field(max_length=50)
    trend: list[QualityTrendPointResponse] = Field(max_length=90)
    authoring: QualityAssetAuthoringResponse
    fields: list[QualityAssetFieldResponse] = Field(max_length=1000)
    score_policy: QualityScorePolicyResponse


class QualityAssetWorkspaceResponse(QualityReadMetadata):
    item: QualityAssetWorkspaceItemResponse


class QualityFieldRuleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_definition_id: UUID
    rule_set_id: UUID
    rule_set_name: str
    version_id: UUID
    version_number: int = Field(ge=1)
    version_state: Literal["PROPOSED", "APPROVED", "ACTIVE"]
    kind: Literal["NOT_NULL", "RANGE"]
    severity: Literal["BLOCKING", "ADVISORY"]
    parameters: dict[str, object]


class QualityFieldRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    rule_set_id: UUID
    rule_set_name: str
    state: Literal[
        "QUEUED",
        "RUNNING",
        "RETRY_WAIT",
        "CANCEL_REQUESTED",
        "SUCCEEDED",
        "FAILED",
        "STALE",
        "CANCELLED",
    ]
    run_quality_outcome: Literal["PASS", "WARN", "FAIL", "UNKNOWN"]
    field_quality_outcome: Literal["PASS", "WARN", "FAIL", "UNKNOWN"]
    score_basis_points: int | None = Field(default=None, ge=0, le=10_000)
    passed_count: int = Field(ge=0)
    advisory_failed_count: int = Field(ge=0)
    blocking_failed_count: int = Field(ge=0)
    evaluated_value_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    unexpected_count: int = Field(ge=0)
    created_at: datetime
    completed_at: datetime | None
    failure_code: str | None


class QualityFieldWorkspaceItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: UUID
    field: QualityAuthoringFieldResponse
    rules: list[QualityFieldRuleResponse] = Field(max_length=200)
    runs: list[QualityFieldRunResponse] = Field(max_length=50)
    trend: list[QualityTrendPointResponse] = Field(max_length=90)
    score_policy: QualityScorePolicyResponse


class QualityFieldWorkspaceResponse(QualityReadMetadata):
    item: QualityFieldWorkspaceItemResponse


class QualityRuleDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_identifier: str = Field(min_length=1, max_length=255)
    kind: Literal["NOT_NULL", "RANGE"]
    severity: Literal["BLOCKING", "ADVISORY"]
    parameters: dict[str, object] = Field(default_factory=dict)


class QualityRuleProposalTargetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: UUID
    rules: list[QualityRuleDraftRequest] = Field(min_length=1, max_length=100)


class QualityRuleBatchProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_prefix: str = Field(min_length=1, max_length=100)
    asset_ids: list[UUID] = Field(default_factory=list, max_length=25)
    rules: list[QualityRuleDraftRequest] = Field(default_factory=list, max_length=100)
    targets: list[QualityRuleProposalTargetRequest] = Field(default_factory=list, max_length=25)

    @field_validator("asset_ids")
    @classmethod
    def unique_assets(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("asset_ids must be unique")
        return value

    @model_validator(mode="after")
    def one_target_shape(self) -> QualityRuleBatchProposalRequest:
        legacy = bool(self.asset_ids or self.rules)
        targeted = bool(self.targets)
        if legacy == targeted:
            raise ValueError("Supply either asset_ids/rules or targets.")
        if legacy and (not self.asset_ids or not self.rules):
            raise ValueError("asset_ids and rules must both be non-empty.")
        if targeted:
            asset_ids = [target.asset_id for target in self.targets]
            if len(asset_ids) != len(set(asset_ids)):
                raise ValueError("target asset IDs must be unique")
        return self


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


class QualityCommonRuleTemplateFieldBindingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_rule_ordinal: int = Field(ge=1, le=100)
    field_identifier: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,254}$",
    )
    parameters_override: dict[str, object] | None = None


class QualityCommonRuleTemplateTargetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: UUID
    bindings: list[QualityCommonRuleTemplateFieldBindingRequest] = Field(
        min_length=1,
        max_length=100,
    )

    @field_validator("bindings")
    @classmethod
    def unique_bindings(
        cls,
        value: list[QualityCommonRuleTemplateFieldBindingRequest],
    ) -> list[QualityCommonRuleTemplateFieldBindingRequest]:
        identities = [
            (binding.template_rule_ordinal, binding.field_identifier) for binding in value
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("field bindings must be unique")
        return value


class QualityCommonRuleTemplateMapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_ids: list[UUID] = Field(default_factory=list, max_length=25)
    targets: list[QualityCommonRuleTemplateTargetRequest] = Field(
        default_factory=list,
        max_length=25,
    )

    @field_validator("asset_ids")
    @classmethod
    def unique_assets(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("asset_ids must be unique")
        return value

    @model_validator(mode="after")
    def one_mapping_shape(self) -> QualityCommonRuleTemplateMapRequest:
        if bool(self.asset_ids) == bool(self.targets):
            raise ValueError("Supply either asset_ids or field targets.")
        target_ids = [target.asset_id for target in self.targets]
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("target asset IDs must be unique")
        return self


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
