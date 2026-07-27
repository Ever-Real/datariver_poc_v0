from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    SecretStr,
    field_validator,
    model_validator,
)

from datariver.domain.admin_access import AdminOperation
from datariver.domain.authz import Action
from datariver.domain.chat import (
    ChatAdapterState,
    ChatRetrievalMode,
    ChatRouteReason,
    ChatWorkflowStage,
    ChatWorkflowStatus,
)
from datariver.domain.knowledge_pipeline import MAX_GRAPHRAG_QUERY_NODES


class PageMeta(BaseModel):
    next_cursor: str | None
    limit: int


class ObservationMeta(BaseModel):
    observed_at: datetime
    stale_at: datetime | None = None


class CatalogPolicyMeta(ObservationMeta):
    projection_version: int = Field(ge=0)
    policy_version: str
    classification_policy_version: int | None = Field(default=None, ge=1)
    authorization_generation: int | None = Field(default=None, ge=0)


class CatalogAssetSummary(BaseModel):
    id: UUID
    external_urn: str
    asset_type: str
    name: str
    description: str | None
    platform: str | None
    database_name: str | None
    schema_name: str | None
    owner: str | None
    domain: str | None
    tags: list[str] = Field(default_factory=list)
    terms: list[str] = Field(default_factory=list)
    description_truncated: bool = False
    tags_truncated: bool = False
    terms_truncated: bool = False
    created_at: datetime | None
    classification: str
    lifecycle: str
    observed_at: datetime
    matches: list[CatalogMatchFragmentResponse] = Field(default_factory=list)


class CatalogMatchFragmentResponse(BaseModel):
    field: Literal["NAME", "DESCRIPTION", "SCHEMA", "COLUMN", "TAG", "TERM"]
    text: str
    matched_terms: list[str]


class CatalogSearchResponse(BaseModel):
    items: list[CatalogAssetSummary]
    page: PageMeta
    total: int = Field(ge=0)
    total_exact: bool
    meta: CatalogPolicyMeta
    match_mode: Literal["ALL"] = "ALL"


class CatalogFacetBucketResponse(BaseModel):
    value: str | None
    count: int = Field(ge=0)


class CatalogDiscoveryPolicyMeta(BaseModel):
    observed_at: datetime | None
    projection_version: int = Field(ge=0)
    policy_version: str
    classification_policy_version: int | None = Field(default=None, ge=1)
    authorization_generation: int | None = Field(default=None, ge=0)


class CatalogFacetsResponse(BaseModel):
    asset_types: list[CatalogFacetBucketResponse]
    platforms: list[CatalogFacetBucketResponse]
    classifications: list[CatalogFacetBucketResponse]
    databases: list[CatalogFacetBucketResponse]
    schemas: list[CatalogFacetBucketResponse]
    domains: list[CatalogFacetBucketResponse]
    lifecycles: list[CatalogFacetBucketResponse]
    meta: CatalogDiscoveryPolicyMeta


class CatalogSuggestionResponse(BaseModel):
    id: UUID
    name: str
    asset_type: str
    platform: str | None
    database_name: str | None
    schema_name: str | None
    matches: list[CatalogMatchFragmentResponse] = Field(default_factory=list)


class CatalogSuggestionsResponse(BaseModel):
    items: list[CatalogSuggestionResponse]
    meta: CatalogDiscoveryPolicyMeta
    match_mode: Literal["ALL"] = "ALL"


class CatalogVocabularyResponse(BaseModel):
    items: list[str]
    meta: CatalogDiscoveryPolicyMeta


class CatalogMetadataVocabularySyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sync_id: UUID
    kind: Literal["DOMAIN", "TAG", "TERM"]
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=100)


class CatalogMetadataVocabularySyncResponse(BaseModel):
    kind: Literal["DOMAIN", "TAG", "TERM"]
    upserted: int = Field(ge=0)
    inactivated: int = Field(ge=0)
    next_offset: int | None = Field(default=None, ge=0)
    total: int = Field(ge=0)
    observed_at: datetime
    inactivation_status: Literal[
        "NOT_FINAL",
        "APPLIED",
        "SUPPRESSED_UNVERIFIED_SNAPSHOT",
    ]


class CatalogMetadataVocabularyItemResponse(BaseModel):
    id: UUID
    kind: Literal["DOMAIN", "TAG", "TERM"]
    display_name: str = Field(min_length=1, max_length=500)
    source_version: str = Field(min_length=1, max_length=255)


class CatalogMetadataVocabularyListResponse(BaseModel):
    items: list[CatalogMetadataVocabularyItemResponse] = Field(max_length=50)
    page: PageMeta


class CatalogTreeNodeResponse(BaseModel):
    id: UUID
    kind: Literal["PLATFORM", "DATABASE", "SCHEMA", "ASSET"]
    label: str
    asset_count: int = Field(ge=1)
    has_children: bool
    platform: str | None
    database_name: str | None
    schema_name: str | None
    asset: CatalogAssetSummary | None


class CatalogTreeResponse(BaseModel):
    items: list[CatalogTreeNodeResponse]
    page: PageMeta
    meta: CatalogDiscoveryPolicyMeta


class CatalogLineageEdgeResponse(BaseModel):
    source_asset_id: UUID
    target_asset_id: UUID


class CatalogLineageResponse(BaseModel):
    center_asset_id: UUID
    nodes: list[CatalogAssetSummary]
    edges: list[CatalogLineageEdgeResponse]
    direction: Literal["UPSTREAM", "DOWNSTREAM", "BOTH"]
    depth: int = Field(ge=1, le=3)
    truncated: bool
    meta: CatalogPolicyMeta


class CatalogAssetResponse(CatalogAssetSummary):
    ownership: list[dict[str, Any]]
    ownership_truncated: bool = False
    glossary_terms: list[dict[str, Any]]
    tags: list[str]
    schema_fields: list[dict[str, Any]]
    schema_fields_total: int = Field(ge=0)
    schema_fields_available: int = Field(ge=0, le=1_000)
    schema_fields_truncated: bool
    schema_fields_total_exact: bool
    schema_fields_offset: int = Field(ge=0)
    schema_fields_limit: int = Field(ge=1, le=200)
    schema_fields_has_more: bool
    quality: dict[str, Any]
    projection_source_version: str
    source_version: str
    stale_at: datetime | None = None


class CatalogDataHubEmbedResponse(BaseModel):
    state: Literal["AVAILABLE", "UNAVAILABLE"]
    url: HttpUrl | None = None
    reason_code: Literal["DISABLED", "NOT_CONFIGURED"] | None = None


class CatalogDescriptionPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(max_length=10_000)

    @field_validator("description")
    @classmethod
    def reject_description_nul(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("Description must not contain NUL characters.")
        return value


class CatalogDescriptionChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(max_length=10_000)
    title: str = Field(min_length=1, max_length=500)
    change_description: str = Field(min_length=1, max_length=10_000)
    requested_due_date: date | None = None
    priority: Literal["LOW", "NORMAL", "HIGH", "CRITICAL"] | None = None
    urgency: Literal["NORMAL", "URGENT", "EMERGENCY"] | None = None

    @field_validator("description", "title", "change_description")
    @classmethod
    def reject_text_nul(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("Text fields must not contain NUL characters.")
        return value

    @field_validator("title", "change_description")
    @classmethod
    def require_auditable_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Title and change_description must contain visible text.")
        return value


class CatalogDescriptionPreviewResponse(BaseModel):
    asset_id: UUID
    target_ref: str
    aspect_name: Literal["datasetProperties"]
    current_description: str | None
    proposed_description: str
    before_hash: str = Field(pattern="^[0-9a-f]{64}$")
    after_hash: str = Field(pattern="^[0-9a-f]{64}$")
    preview_etag: str = Field(pattern='^"[0-9a-f]{64}"$')
    source_version: str
    observed_at: datetime


class CatalogColumnDescriptionPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_path: str = Field(min_length=1, max_length=2_000)
    description: str = Field(max_length=10_000)

    @field_validator("field_path", "description")
    @classmethod
    def reject_column_description_nul(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("Column description fields must not contain NUL characters.")
        return value


class CatalogColumnDescriptionChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_path: str = Field(min_length=1, max_length=2_000)
    description: str = Field(max_length=10_000)
    title: str = Field(min_length=1, max_length=500)
    change_description: str = Field(min_length=1, max_length=10_000)

    @field_validator("field_path", "description", "title", "change_description")
    @classmethod
    def reject_column_change_nul(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("Column change fields must not contain NUL characters.")
        return value

    @field_validator("title", "change_description")
    @classmethod
    def require_column_auditable_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Title and change_description must contain visible text.")
        return value


class CatalogColumnDescriptionPreviewResponse(BaseModel):
    asset_id: UUID
    target_ref: str
    aspect_name: Literal["schemaMetadata"]
    field_path: str
    current_description: str | None
    proposed_description: str
    before_hash: str = Field(pattern="^[0-9a-f]{64}$")
    after_hash: str = Field(pattern="^[0-9a-f]{64}$")
    preview_etag: str = Field(pattern='^"[0-9a-f]{64}"$')
    source_version: str
    observed_at: datetime


class CatalogControlledMetadataPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aspect_name: Literal["domains", "globalTags", "glossaryTerms"]
    refs: list[str] = Field(max_length=100)

    @field_validator("refs")
    @classmethod
    def require_unique_nonempty_refs(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value) or any(not item or "\x00" in item for item in value):
            raise ValueError("Controlled metadata references must be unique non-empty text.")
        return value


class CatalogControlledMetadataChangeRequest(CatalogControlledMetadataPreviewRequest):
    title: str = Field(min_length=1, max_length=500)
    change_description: str = Field(min_length=1, max_length=10_000)

    @field_validator("title", "change_description")
    @classmethod
    def require_controlled_metadata_auditable_text(cls, value: str) -> str:
        if "\x00" in value or not value.strip():
            raise ValueError("Title and change_description must contain visible text.")
        return value


class CatalogControlledMetadataPreviewResponse(BaseModel):
    asset_id: UUID
    target_ref: str
    aspect_name: Literal["domains", "globalTags", "glossaryTerms"]
    current_refs: list[str]
    proposed_refs: list[str]
    before_hash: str = Field(pattern="^[0-9a-f]{64}$")
    after_hash: str = Field(pattern="^[0-9a-f]{64}$")
    preview_etag: str = Field(pattern='^"[0-9a-f]{64}"$')
    source_version: str
    observed_at: datetime


class CatalogSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sync_id: UUID
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=100)


class CatalogSyncResponse(BaseModel):
    upserted: int
    tombstoned: int
    next_offset: int | None
    total: int
    observed_at: datetime
    tombstone_status: Literal[
        "NOT_FINAL",
        "APPLIED",
        "SUPPRESSED_UNVERIFIED_SNAPSHOT",
    ]


class CatalogSyncProgressResponse(BaseModel):
    state: Literal["NOT_STARTED", "ACTIVE", "COMPLETED", "ABANDONED"]
    next_offset: int | None
    seen_count: int = Field(ge=0)
    expected_total: int | None = Field(default=None, ge=0)
    snapshot_consistent: bool


class CatalogExportCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: str = Field(default="", max_length=500)
    asset_type: str | None = Field(default=None, min_length=1, max_length=100)
    platform: str | None = Field(default=None, min_length=1, max_length=100)
    database_name: str | None = Field(default=None, min_length=1, max_length=255)
    schema_name: str | None = Field(default=None, min_length=1, max_length=255)
    domain: str | None = Field(default=None, min_length=1, max_length=1000)
    search_fields: str | None = Field(default=None, min_length=1, max_length=100)
    classification: Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"] | None = None
    lifecycle: Literal["ACTIVE"] | None = None
    sort: Literal["NAME_ASC"] = "NAME_ASC"
    format: Literal["CSV", "XLSX"] = "CSV"


class CatalogExportCreateResponse(BaseModel):
    export_id: UUID
    job_id: UUID
    state: str


class CatalogExportStatusResponse(BaseModel):
    export_id: UUID
    job_id: UUID
    state: str
    last_error_code: str | None
    row_count: int | None = Field(default=None, ge=0)
    size_bytes: int | None = Field(default=None, ge=0)
    content_sha256: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    display_name: str
    created_at: datetime
    completed_at: datetime | None
    access_until: datetime


class CatalogExportDownloadResponse(BaseModel):
    url: str
    expires_seconds: int = Field(ge=60, le=900)


class CatalogExportCapabilityResponse(BaseModel):
    enabled: bool


class ChangeItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: str = Field(pattern="^DATAHUB_ASPECT$")
    target_ref: str = Field(min_length=16, max_length=4096, pattern="^urn:li:dataset:")
    aspect_name: Literal[
        "datasetProperties",
        "domains",
        "globalTags",
        "glossaryTerms",
        "ownership",
        "schemaMetadata",
    ]
    operation: str = Field(pattern="^UPSERT$")
    before_hash: str = Field(pattern="^[0-9a-f]{64}$")
    after_document: dict[str, Any]
    after_hash: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")


class ChangeRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_type: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=10_000)
    classification: str = Field(
        default="INTERNAL", pattern="^(PUBLIC|INTERNAL|CONFIDENTIAL|RESTRICTED)$"
    )
    requested_due_date: date | None = None
    priority: Literal["LOW", "NORMAL", "HIGH", "CRITICAL"] | None = None
    urgency: Literal["NORMAL", "URGENT", "EMERGENCY"] | None = None
    items: list[ChangeItemRequest] = Field(min_length=1, max_length=1)


class ChangeIntakeColumnRequest(BaseModel):
    """A requested table-column change; source values are re-read on the server."""

    model_config = ConfigDict(extra="forbid")

    field_path: str = Field(min_length=1, max_length=2_000)
    data_type: str = Field(default="", max_length=1_000)
    description: str = Field(default="", max_length=10_000)
    requested_change: str = Field(default="", max_length=10_000)
    tags: list[str] = Field(default_factory=list, max_length=100)
    terms: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("field_path", "data_type", "description", "requested_change", "tags", "terms")
    @classmethod
    def reject_nul(cls, value: str | list[str]) -> str | list[str]:
        values = (value,) if isinstance(value, str) else value
        if any("\x00" in item for item in values):
            raise ValueError("Change intake values cannot contain NUL bytes.")
        return value


class ChangeIntakeExistingTargetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["EXISTING"]
    asset_id: UUID
    description: str = Field(default="", max_length=10_000)
    requested_change: str = Field(default="", max_length=10_000)
    tags: list[str] = Field(default_factory=list, max_length=100)
    terms: list[str] = Field(default_factory=list, max_length=100)
    columns: list[ChangeIntakeColumnRequest] = Field(default_factory=list, max_length=2_000)

    @field_validator("description", "requested_change", "tags", "terms")
    @classmethod
    def reject_nul(cls, value: str | list[str]) -> str | list[str]:
        values = (value,) if isinstance(value, str) else value
        if any("\x00" in item for item in values):
            raise ValueError("Change intake values cannot contain NUL bytes.")
        return value


class ChangeIntakeManualTargetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["MANUAL"]
    database_name: str = Field(default="", max_length=255)
    schema_name: str = Field(default="", max_length=255)
    table_name: str = Field(min_length=1, max_length=500)
    owner: str = Field(default="", max_length=1_000)
    description: str = Field(default="", max_length=10_000)
    requested_change: str = Field(default="", max_length=10_000)
    tags: list[str] = Field(default_factory=list, max_length=100)
    terms: list[str] = Field(default_factory=list, max_length=100)
    columns: list[ChangeIntakeColumnRequest] = Field(default_factory=list, max_length=2_000)

    @field_validator(
        "database_name",
        "schema_name",
        "table_name",
        "owner",
        "description",
        "requested_change",
        "tags",
        "terms",
    )
    @classmethod
    def reject_nul(cls, value: str | list[str]) -> str | list[str]:
        values = (value,) if isinstance(value, str) else value
        if any("\x00" in item for item in values):
            raise ValueError("Change intake values cannot contain NUL bytes.")
        return value


class ChangeRequestIntakeCreate(BaseModel):
    """Legacy-shaped CR registration without browser-owned provider write authority."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    system_id: UUID
    request_date: date | None = None
    request_department: str = Field(default="", max_length=500)
    request_reason: str = Field(min_length=1, max_length=10_000)
    request_content: str = Field(default="", max_length=10_000)
    requested_due_date: date | None = None
    priority: Literal["LOW", "NORMAL", "HIGH", "CRITICAL"] = "NORMAL"
    urgency: Literal["NORMAL", "URGENT", "EMERGENCY"] = "NORMAL"
    security_level: Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"] = "INTERNAL"
    targets: list[ChangeIntakeExistingTargetRequest | ChangeIntakeManualTargetRequest] = Field(
        min_length=1, max_length=200
    )


class IntakeCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=4_000)


class TransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_state: str
    reason: str = Field(min_length=1, max_length=4000)


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str = Field(pattern="^(REVIEW|TEST|FINAL)$")
    decision: str = Field(pattern="^(APPROVED|REJECTED)$")
    reason: str = Field(min_length=1, max_length=4000)


class ChangeTestRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system_id: UUID
    attachment_id: UUID
    state: Literal["PASSED", "FAILED"]
    bounded_summary: dict[str, Any]


class ChangeItemResponse(BaseModel):
    id: UUID
    target_type: str
    target_ref: str
    aspect_name: str
    operation: str
    before_hash: str | None
    after_hash: str | None
    after_document: dict[str, Any]
    target_asset_id: UUID | None
    target_asset_type: str | None
    target_system_id: UUID | None
    target_domain_id: UUID | None
    target_owner_department_id: UUID | None
    target_classification: str | None
    target_lifecycle: str | None
    target_source_version: str | None
    target_observed_at: datetime | None
    target_binding_hash: str | None
    routing_system_id: UUID | None


class ApprovalAuthorityResponse(BaseModel):
    kind: Literal["SYSTEM_DEVELOPER", "SYSTEM_DATA_STEWARD", "GLOBAL_ADMIN"]
    system_id: UUID | None


class ApprovalResponse(BaseModel):
    id: UUID
    stage: str
    decision: str
    actor_id: UUID
    reason: str
    occurred_at: datetime
    round_id: UUID
    authorities: list[ApprovalAuthorityResponse]


class TransitionResponse(BaseModel):
    id: UUID
    from_state: str
    to_state: str
    actor_id: UUID
    reason: str
    occurred_at: datetime
    round_id: UUID


class ChangeRequestRoundResponse(BaseModel):
    id: UUID
    round_number: int = Field(ge=1)
    submitted_by: UUID
    submitted_at: datetime
    closed_at: datetime | None
    evidence_hash: str


class ChangeTestRunResponse(BaseModel):
    id: UUID
    round_id: UUID
    system_id: UUID
    attachment_id: UUID
    state: Literal["PASSED", "FAILED"]
    plan_hash: str
    result_hash: str
    bounded_summary: dict[str, Any]
    recorded_by: UUID
    occurred_at: datetime


class ChangeRequestResponse(BaseModel):
    id: UUID
    number: str
    request_type: str
    title: str
    description: str
    state: str
    requester_id: UUID
    requester_department_id: UUID | None
    current_round_id: UUID
    current_round_number: int = Field(ge=1)
    created_at: datetime
    requested_due_date: date | None
    priority: str | None
    urgency: str | None
    classification: str
    version: int
    items: list[ChangeItemResponse] = Field(max_length=200)
    approvals: list[ApprovalResponse] = Field(max_length=600)
    transitions: list[TransitionResponse] = Field(max_length=200)
    rounds: list[ChangeRequestRoundResponse] = Field(max_length=50)
    test_runs: list[ChangeTestRunResponse] = Field(max_length=200)


class ChangeRequestAttachmentResponse(BaseModel):
    id: UUID
    kind: Literal["REQUEST", "TEST"]
    round_id: UUID
    original_name: str
    serial_number: int
    content_type: str
    size_bytes: int
    content_sha256: str
    created_at: datetime


class ChangeRequestAttachmentUploadResponse(BaseModel):
    id: UUID
    change_request_id: UUID
    round_id: UUID
    kind: Literal["REQUEST", "TEST"]
    original_name: str = Field(min_length=1, max_length=500)
    state: Literal["STARTED", "STORED", "FINALIZED", "FAILED"]
    expected_size_bytes: int = Field(ge=1, le=10 * 1024 * 1024)
    expected_content_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    provider_checksum: str | None = Field(default=None, max_length=255)
    failure_code: str | None = Field(default=None, max_length=100)
    status_url: str
    finalize_url: str


class ChangeRequestAttachmentUploadListResponse(BaseModel):
    items: list[ChangeRequestAttachmentUploadResponse] = Field(max_length=50)


class ChangeRequestAttachmentListResponse(BaseModel):
    items: list[ChangeRequestAttachmentResponse] = Field(max_length=200)


class ChangeRequestAttachmentPageResponse(BaseModel):
    items: list[ChangeRequestAttachmentResponse] = Field(max_length=50)
    page: PageMeta


class ChangeRequestAssigneeResponse(BaseModel):
    subject_id: UUID
    display_name: str
    responsibility: Literal["DEVELOPER", "DATA_STEWARD"]
    priority: int = Field(ge=1, le=999)


class ChangeRequestSchemaOverviewResponse(BaseModel):
    platform: str
    database_name: str
    schema_name: str
    system_id: UUID | None
    system_code: str | None
    system_name: str | None
    assignees: list[ChangeRequestAssigneeResponse]
    pending_count: int = Field(ge=0)
    total_count: int = Field(ge=0)
    received_count: int = Field(ge=0)
    recheck_count: int = Field(ge=0)
    testing_count: int = Field(ge=0)
    final_review_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)


class ChangeRequestSummaryItemResponse(BaseModel):
    target_ref: str
    aspect_name: str
    operation: str


class ChangeRequestSummaryResponse(BaseModel):
    id: UUID
    number: str
    request_type: str
    title: str
    state: str
    requester_id: UUID
    requester_department_id: UUID | None
    current_round_number: int = Field(ge=1)
    created_at: datetime
    requested_due_date: date | None
    priority: str | None
    urgency: str | None
    classification: str
    version: int = Field(ge=1)
    item_count: int = Field(ge=1, le=200)
    first_item: ChangeRequestSummaryItemResponse


class ChangeRequestSummaryListResponse(BaseModel):
    items: list[ChangeRequestSummaryResponse]
    overview: list[ChangeRequestSchemaOverviewResponse] = Field(
        default_factory=list,
        max_length=100,
    )
    overview_truncated: bool = False
    page: PageMeta


class ChangeRequestListResponse(BaseModel):
    """Stable `/api/v1/change-requests` compatibility envelope."""

    items: list[ChangeRequestResponse]
    overview: list[ChangeRequestSchemaOverviewResponse] = Field(default_factory=list)


class GovernanceApplyAttemptResponse(BaseModel):
    id: UUID
    attempt_no: int = Field(ge=1)
    state: str
    failure_code: str | None
    external_response_hash: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    started_at: datetime
    finished_at: datetime | None


class GovernanceApplyItemResponse(BaseModel):
    item_id: UUID
    expected_hash: str = Field(pattern="^[0-9a-f]{64}$")
    observed_hash: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    source_version: str | None
    provider_version: str | None


class GovernanceApplyReportResponse(BaseModel):
    change_request_id: UUID
    job_id: UUID | None
    state: str
    attempt_count: int = Field(ge=0, le=20)
    last_error_code: str | None
    expected_hash: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    observed_hash: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    reconciled: bool
    created_at: datetime | None
    updated_at: datetime | None
    items: list[GovernanceApplyItemResponse] = Field(max_length=200)
    attempts: list[GovernanceApplyAttemptResponse] = Field(max_length=20)


class ChangeRequestSystemResponse(BaseModel):
    id: UUID
    code: str
    name: str


class ChangeRequestSystemListResponse(BaseModel):
    items: list[ChangeRequestSystemResponse]


class CapabilityResponse(BaseModel):
    name: str
    state: str
    observed_at: datetime
    latency_ms: int | None = None
    detail_code: str | None = None


class ExternalSystemLinkResponse(BaseModel):
    system_id: Literal["datahub", "airflow", "grafana", "prometheus", "graph"]
    label: str
    url: HttpUrl


class GrafanaEmbedResponse(BaseModel):
    """A server-owned descriptor; the browser never submits an iframe URL."""

    state: Literal["AVAILABLE", "DISABLED", "NOT_CONFIGURED"]
    url: HttpUrl | None = None


class CapabilitiesResponse(BaseModel):
    items: list[CapabilityResponse]
    external_system_links: list[ExternalSystemLinkResponse] = Field(default_factory=list)
    grafana_embed: GrafanaEmbedResponse
    deployment_tier: Literal["SINGLE_NODE_PILOT", "HA_CANDIDATE", "HA_ACCEPTED"]


class AuthMeResponse(BaseModel):
    subject: str
    display_name: str
    email: str | None = None
    roles: list[str] = Field(default_factory=list)
    authentication_assurance: str
    authentication_time: datetime | None
    default_workspace_id: UUID | None = None
    workspace_selection_enabled: bool = False
    hardware_webauthn_enabled: bool = False
    password_change_supported: bool = False


class IdentityUserProvisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]+$")
    email: str = Field(min_length=3, max_length=320)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    department_id: UUID | None = None
    job_function: str | None = Field(default=None, max_length=100)
    role_id: UUID | None = None
    temporary_password: SecretStr = Field(min_length=12, max_length=128)

    @field_validator("username", "email", "first_name", "last_name", "job_function")
    @classmethod
    def normalize_identity_profile(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Identity profile values cannot be blank.")
        return normalized

    @field_validator("email")
    @classmethod
    def validate_identity_email(cls, value: str) -> str:
        local, separator, domain = value.rpartition("@")
        if (
            not separator
            or not local
            or "." not in domain
            or domain.startswith(".")
            or domain.endswith(".")
        ):
            raise ValueError("A valid email address is required.")
        return value


class IdentityUserProvisionResponse(BaseModel):
    subject_id: UUID
    username: str
    display_name: str
    email: str
    workspace_id: UUID
    role_id: UUID | None
    access_expires_at: datetime
    temporary_password_required: bool


class ProblemDetails(BaseModel):
    type: str
    title: str
    status: int
    detail: str
    instance: str
    code: str
    request_id: str
    violations: list[dict[str, Any]] | None = None


class MembershipAccessDocumentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool
    clearance: Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]
    groups: list[str] = Field(max_length=100)
    allowed_actions: list[Action] = Field(max_length=100)
    denied_actions: list[Action] = Field(max_length=100)
    allowed_system_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    allowed_domain_ids: list[UUID] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def reject_server_managed_role_markers(self) -> MembershipAccessDocumentRequest:
        if any(group.startswith("datariver-role-") for group in self.groups):
            raise ValueError("Manual access documents cannot contain a reserved role marker.")
        return self


class MembershipAccessDocumentResponse(BaseModel):
    active: bool
    clearance: Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]
    groups: list[str] = Field(max_length=100)
    allowed_actions: list[Action] = Field(max_length=100)
    denied_actions: list[Action] = Field(max_length=100)
    allowed_system_ids: list[UUID] = Field(max_length=1000)
    allowed_domain_ids: list[UUID] = Field(max_length=1000)


class WorkspaceMembershipSummaryResponse(BaseModel):
    subject_id: UUID
    display_name: str
    email: str | None
    last_login_at: datetime | None
    last_login_ip: str | None
    owned_table_count: int = Field(ge=0)
    change_request_count: int = Field(ge=0)
    joined_at: datetime | None
    access_expires_at: datetime | None
    renewal_eligible_at: datetime | None
    access_expired: bool
    renewal_request_eligible: bool
    pending_renewal_request_id: UUID | None
    subject_active: bool
    membership_active: bool
    department_id: UUID | None
    job_function: str | None
    clearance: Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]
    membership_version: int = Field(ge=1)


class WorkspaceMembershipListResponse(BaseModel):
    items: list[WorkspaceMembershipSummaryResponse]
    page: PageMeta


class MembershipChangeRequestActivityResponse(BaseModel):
    change_request_id: UUID
    number: str
    title: str
    request_type: str
    state: str
    relationship: Literal["REQUESTER", "APPROVER", "REQUESTER_AND_APPROVER"]
    classification: Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]
    updated_at: datetime


class MembershipChangeRequestActivityListResponse(BaseModel):
    items: list[MembershipChangeRequestActivityResponse]
    page: PageMeta


class MembershipOwnedTableResponse(BaseModel):
    asset_id: UUID
    name: str
    platform: str | None
    database_name: str | None
    schema_name: str | None
    classification: Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]
    source_version: str
    observed_at: datetime


class MembershipOwnedTableListResponse(BaseModel):
    items: list[MembershipOwnedTableResponse]
    page: PageMeta


class MembershipRenewalCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=4000)


class MembershipRenewalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["APPROVED", "REJECTED"]
    reason: str = Field(min_length=1, max_length=4000)


class MembershipRenewalResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    target_subject_id: UUID
    requester_id: UUID
    requester_display_name: str
    reason: str
    current_expires_at: datetime
    requested_expires_at: datetime
    state: Literal["PENDING", "APPROVED", "REJECTED"]
    version: int = Field(ge=1)
    created_at: datetime
    checker_id: UUID | None
    checker_display_name: str | None
    decision_reason: str | None
    decided_at: datetime | None
    membership_version: int | None = Field(default=None, ge=1)


class MembershipRenewalListResponse(BaseModel):
    items: list[MembershipRenewalResponse]
    page: PageMeta


class AccessRoleDataRuleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classification: Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]
    access_level: Literal["NO_ACCESS", "PARTIAL_ACCESS", "FULL_ACCESS"]
    partial_treatment: Literal["MASK", "REDACT", "TOKENIZE"] | None = None
    allowed_residency_regions: list[str] = Field(default_factory=list, max_length=50)
    allowed_processing_purposes: list[
        Literal["METADATA_READ", "DATA_READ", "EXPORT", "ANALYTICS", "MODEL_TRAINING"]
    ] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_rule_shape(self) -> AccessRoleDataRuleRequest:
        regions = [region.strip().upper() for region in self.allowed_residency_regions]
        if len(regions) != len(set(regions)) or any(
            re.fullmatch(r"[A-Z0-9][A-Z0-9._:-]{0,63}", region) is None for region in regions
        ):
            raise ValueError("Residency regions must be unique bounded uppercase identifiers.")
        if len(self.allowed_processing_purposes) != len(set(self.allowed_processing_purposes)):
            raise ValueError("Processing purposes must be unique.")
        if self.access_level == "NO_ACCESS":
            if self.partial_treatment is not None or regions or self.allowed_processing_purposes:
                raise ValueError("No-access rules cannot declare treatment or processing scope.")
        else:
            if not regions or not self.allowed_processing_purposes:
                raise ValueError("Granted rules require residency and processing scope.")
            if (self.access_level == "PARTIAL_ACCESS") != (self.partial_treatment is not None):
                raise ValueError("Exactly partial access requires a treatment.")
        self.allowed_residency_regions = regions
        return self


class AccessRoleWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_key: str = Field(pattern=r"^[a-z][a-z0-9-]{1,79}$")
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=4000)
    clearance: Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]
    groups: list[str] = Field(default_factory=list, max_length=100)
    allowed_actions: list[Action] = Field(max_length=100)
    denied_actions: list[Action] = Field(default_factory=list, max_length=100)
    allowed_system_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    allowed_domain_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    data_access_rules: list[AccessRoleDataRuleRequest] = Field(default_factory=list, max_length=4)
    active: bool = True

    @field_validator("data_access_rules", mode="before")
    @classmethod
    def reject_null_data_access_rules(cls, value: object) -> object:
        if value is None:
            raise ValueError("data_access_rules must be omitted or supplied as an array.")
        return value

    @model_validator(mode="after")
    def validate_access_document(self) -> AccessRoleWriteRequest:
        if len(self.groups) != len(set(self.groups)) or any(
            re.fullmatch(r"[a-z][a-z0-9-]{1,99}", group) is None for group in self.groups
        ):
            raise ValueError("Role groups must be unique bounded lowercase identifiers.")
        if any(group.startswith("datariver-role-") for group in self.groups):
            raise ValueError("Role groups cannot contain a reserved role marker.")
        if len(self.allowed_actions) != len(set(self.allowed_actions)) or len(
            self.denied_actions
        ) != len(set(self.denied_actions)):
            raise ValueError("Role actions must be unique.")
        if set(self.allowed_actions) & set(self.denied_actions):
            raise ValueError("A role action cannot be both allowed and denied.")
        if len(self.allowed_system_ids) != len(set(self.allowed_system_ids)) or len(
            self.allowed_domain_ids
        ) != len(set(self.allowed_domain_ids)):
            raise ValueError("Role resource scopes must be unique.")
        classifications = [rule.classification for rule in self.data_access_rules]
        if len(classifications) != len(set(classifications)):
            raise ValueError("A role can contain only one data rule per classification.")
        return self


class AccessRoleResponse(BaseModel):
    id: UUID
    role_key: str
    name: str
    description: str
    clearance: Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]
    groups: list[str]
    allowed_actions: list[Action]
    denied_actions: list[Action]
    allowed_system_ids: list[UUID]
    allowed_domain_ids: list[UUID]
    data_access_rules: list[AccessRoleDataRuleRequest]
    active: bool
    assigned_count: int = Field(ge=0)
    version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class AccessRoleListResponse(BaseModel):
    items: list[AccessRoleResponse]
    page: PageMeta


class MembershipRoleAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_id: UUID | None


class MembershipRoleAssignmentResponse(BaseModel):
    subject_id: UUID
    role_id: UUID | None
    membership_version: int = Field(ge=1)
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class SystemDirectoryAssigneeResponse(BaseModel):
    subject_id: UUID
    display_name: str
    responsibility: Literal["DEVELOPER", "DATA_STEWARD"]
    priority: int = Field(ge=1, le=999)
    active: bool


class SystemDirectoryEntryResponse(BaseModel):
    system_id: UUID
    code: str
    name: str
    description: str
    active: bool
    version: int = Field(ge=1)
    assignee_count: int = Field(ge=0)
    assignees: list[SystemDirectoryAssigneeResponse]


class SystemDirectoryListResponse(BaseModel):
    items: list[SystemDirectoryEntryResponse]
    page: PageMeta


class SystemCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(
        min_length=2,
        max_length=100,
        pattern=r"^[A-Za-z][A-Za-z0-9_-]{1,99}$",
        description="시스템 고유 코드 (영문자로 시작, 영숫자·_·- 허용)",
    )
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=4000)


class SystemAssigneeUpdateRequest(BaseModel):
    subject_id: UUID
    responsibility: Literal["DEVELOPER", "DATA_STEWARD"]
    priority: int = Field(ge=1, le=999)


class SystemAssigneeUpdateListRequest(BaseModel):
    assignees: list[SystemAssigneeUpdateRequest] = Field(min_length=2, max_length=500)


class SystemAssigneeKeyRequest(BaseModel):
    subject_id: UUID
    responsibility: Literal["DEVELOPER", "DATA_STEWARD"]


class SystemAssigneePatchRequest(BaseModel):
    upserts: list[SystemAssigneeUpdateRequest] = Field(default_factory=list, max_length=100)
    removals: list[SystemAssigneeKeyRequest] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def require_changes(self) -> SystemAssigneePatchRequest:
        if not self.upserts and not self.removals:
            raise ValueError("A system-assignee patch cannot be empty.")
        return self


class SystemAssigneeListResponse(BaseModel):
    system_version: int = Field(ge=1)
    items: list[SystemDirectoryAssigneeResponse]
    page: PageMeta


class SystemAssigneeUpdateResponse(BaseModel):
    system_id: UUID
    system_version: int = Field(ge=1)
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


SystemConfigurationId = Literal[
    "PLATFORM_RUNTIME",
    "POSTGRESQL",
    "OIDC_IDENTITY",
    "RETENTION_ARCHIVE",
    "DATAHUB_GMS",
    "DATAHUB_FRONTEND",
    "AIRFLOW",
    "REDIS_CACHE",
    "REDIS_DELIVERY",
    "S3_STORAGE",
    "LLM_CHAT_MODEL",
    "LLM_EMBEDDING",
    "LLM_RERANKER",
    "NEO4J",
    "PROMETHEUS",
    "GRAFANA_DASHBOARD",
]


class SystemConnectionRequirementResponse(BaseModel):
    key: str
    label: str
    required: bool
    secret: bool = False
    example: str | None = None


class SystemConfigurationEntryResponse(BaseModel):
    """Read-only deployment configuration inventory; secret values are never returned."""

    system_id: SystemConfigurationId
    label: str
    category: Literal["PLATFORM", "CATALOG", "ORCHESTRATION", "STORAGE", "AI", "OBSERVABILITY"]
    requirement: Literal["BOOTSTRAP_REQUIRED", "CORE_CONNECTOR", "FEATURE_CONNECTOR"]
    description: str
    connection_requirements: list[SystemConnectionRequirementResponse]
    state: Literal["CONFIGURED", "NOT_CONFIGURED", "GOVERNED_PROFILE_REQUIRED"]
    management_plane: Literal["DEPLOYMENT"]
    secret_reference_configured: bool
    embedding_state: Literal["NOT_APPLICABLE", "AVAILABLE", "DISABLED", "NOT_CONFIGURED"]
    configuration_yaml: str = ""
    template_yaml: str = ""
    display_yaml: str = ""
    environment_template: str = ""
    effective_configuration_yaml: str = ""
    version: int = Field(ge=0)
    configured_at: datetime | None = None
    runtime_supported: bool = False
    restart_scope: Literal["API_ONLY", "WORKERS_ONLY", "API_AND_WORKERS", "NOT_IMPLEMENTED"] = (
        "NOT_IMPLEMENTED"
    )
    activation_state: Literal[
        "NOT_CONFIGURED",
        "SAVED_UNTESTED",
        "TEST_NOT_AVAILABLE",
        "TESTED",
        "ACTIVATED_RESTART_REQUIRED",
        "APPLIED_TO_API_PROCESS",
        "DEPLOYMENT_MANAGED",
        "RUNTIME_NOT_IMPLEMENTED",
    ] = "NOT_CONFIGURED"
    tested_version: int | None = Field(default=None, ge=1)
    test_status: Literal["AVAILABLE", "AUTHENTICATION_REQUIRED", "UNAVAILABLE"] | None = None
    tested_at: datetime | None = None
    activated_version: int | None = Field(default=None, ge=1)
    activated_at: datetime | None = None
    applied_version: int | None = Field(default=None, ge=1)
    is_core: bool = False


class SystemConfigurationListResponse(BaseModel):
    items: list[SystemConfigurationEntryResponse]


class SystemConfigurationVersionResponse(BaseModel):
    configuration_version: int = Field(ge=1)
    configuration_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_by: UUID
    created_at: datetime
    test_status: Literal["AVAILABLE", "AUTHENTICATION_REQUIRED", "UNAVAILABLE"] | None = None
    test_scope: (
        Literal[
            "HTTP_HEALTH",
            "MODEL_DISCOVERY",
            "MODEL_INFERENCE",
            "EMBEDDING_INFERENCE",
            "RERANKING_INFERENCE",
            "AUTHENTICATED_QUERY",
            "REDIS_PING",
            "REDIS_POLICY",
            "S3_HEAD_BUCKET",
        ]
        | None
    ) = None
    test_latency_ms: int | None = Field(default=None, ge=0)
    tested_by: UUID | None = None
    tested_at: datetime | None = None
    activated_by: UUID | None = None
    activated_at: datetime | None = None
    current: bool
    activated: bool


class SystemConfigurationVersionListResponse(BaseModel):
    system_id: SystemConfigurationId
    current_version: int = Field(ge=0)
    activated_version: int | None = Field(default=None, ge=1)
    items: list[SystemConfigurationVersionResponse]


class SystemConfigurationTestResponse(BaseModel):
    system_id: SystemConfigurationId
    status: Literal["AVAILABLE", "AUTHENTICATION_REQUIRED", "UNAVAILABLE"]
    scope: Literal[
        "HTTP_HEALTH",
        "MODEL_DISCOVERY",
        "MODEL_INFERENCE",
        "EMBEDDING_INFERENCE",
        "RERANKING_INFERENCE",
        "AUTHENTICATED_QUERY",
        "REDIS_PING",
        "REDIS_POLICY",
        "S3_HEAD_BUCKET",
    ]
    latency_ms: int = Field(ge=0)
    detail: str
    configuration_version: int | None = Field(default=None, ge=1)
    tested_at: datetime


class SystemConfigurationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configuration_yaml: str = Field(min_length=1, max_length=100_000)


class MembershipRoleAssignmentEvidenceResponse(BaseModel):
    status: Literal["VERIFIED", "MANUAL", "LEGACY_UNVERIFIED", "EVIDENCE_MISMATCH"]
    role_id: UUID | None = None
    role_version: int | None = Field(default=None, ge=1)
    assignment_version: int | None = Field(default=None, ge=1)
    membership_version: int | None = Field(default=None, ge=1)
    access_payload_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    assigned_by: UUID | None = None
    updated_at: datetime | None = None
    legacy_markers: list[str] = Field(default_factory=list, max_length=100)


class WorkspaceMembershipAccessResponse(BaseModel):
    subject_id: UUID
    display_name: str
    subject_active: bool
    department_id: UUID | None
    job_function: str | None
    membership_version: int = Field(ge=1)
    access: MembershipAccessDocumentResponse
    role_assignment: MembershipRoleAssignmentEvidenceResponse


class AdminReadContextResponse(BaseModel):
    subject_id: UUID
    workspace_id: UUID
    display_name: str
    # `/admin/me` is a read-only profile/context hydration endpoint.  It must
    # report the current verified assurance at ordinary login strength; strong
    # assurance remains enforced by each sensitive mutation's authorization.
    authentication_assurance: Literal[
        "UNKNOWN", "PASSWORD", "OTHER_MFA", "PASSWORD_REAUTH", "HARDWARE_WEBAUTHN"
    ]
    fallback_enabled: bool
    allowed_operations: list[AdminOperation]
    action_vocabulary: list[Action]


class AdminFallbackCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_subject_id: UUID
    reason: str = Field(min_length=1, max_length=4000)
    access: MembershipAccessDocumentRequest


class AdminFallbackDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["APPROVED", "REJECTED"]
    reason: str = Field(min_length=1, max_length=4000)


class AdminFallbackConsumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed_payload_hash: str = Field(pattern="^[0-9a-f]{64}$")


class MembershipAccessCommandResponse(BaseModel):
    command_type: Literal["WORKSPACE_MEMBERSHIP_ACCESS_UPDATE_V1"]
    workspace_id: UUID
    target_subject_id: UUID
    expected_membership_version: int
    access: MembershipAccessDocumentRequest


class AdminAccessApprovalResponse(BaseModel):
    id: UUID
    decision: str
    actor_id: UUID
    reason: str
    policy_decision_id: UUID
    payload_hash: str
    request_version: int
    occurred_at: datetime


class AdminAccessRequestResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    requester_id: UUID
    request_reason: str
    request_policy_decision_id: UUID
    command: MembershipAccessCommandResponse
    payload_hash: str
    state: str
    version: int
    expires_at: datetime
    checker_id: UUID | None
    consumed_by: UUID | None
    consumed_at: datetime | None
    consume_policy_decision_id: UUID | None
    approvals: list[AdminAccessApprovalResponse]


class AdminAccessRequestListResponse(BaseModel):
    items: list[AdminAccessRequestResponse]
    page: PageMeta


class MembershipAccessUpdateResponse(BaseModel):
    target_subject_id: UUID
    membership_version: int
    payload_hash: str


class AdminAccessConsumeResponse(BaseModel):
    request: AdminAccessRequestResponse
    membership_version: int


class UploadInitiateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=500)
    size_bytes: int = Field(ge=1, le=5 * 1024 * 1024 * 1024)
    content_type: str = Field(
        pattern=(
            "^(application/pdf|text/csv|application/json|application/x-parquet|"
            "application/vnd.apache.parquet|application/yaml|text/yaml|"
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet)$"
        )
    )
    sha256: str = Field(pattern="^[0-9a-f]{64}$")
    classification: str = Field(
        default="INTERNAL", pattern="^(PUBLIC|INTERNAL|CONFIDENTIAL|RESTRICTED)$"
    )
    content_profile: Literal[
        "FORMAT_ONLY_V1",
        "CATALOG_METADATA_ROWS_CSV_V1",
        "CATALOG_METADATA_ROWS_XLSX_V1",
        "DATASET_DESCRIPTION_CSV_V1",
        "DATASET_DESCRIPTION_XLSX_V1",
    ] = "FORMAT_ONLY_V1"

    @field_validator("display_name")
    @classmethod
    def safe_display_name(cls, value: str) -> str:
        cleaned = value.strip().replace("\\", "/").split("/")[-1]
        if not cleaned or any(ord(character) < 32 for character in cleaned):
            raise ValueError("The display filename is invalid.")
        return cleaned


class UploadResponse(BaseModel):
    id: UUID
    display_name: str
    state: str
    size_bytes: int
    content_type: str
    sha256: str
    classification: str
    content_profile: Literal[
        "FORMAT_ONLY_V1",
        "CATALOG_METADATA_ROWS_CSV_V1",
        "CATALOG_METADATA_ROWS_XLSX_V1",
        "DATASET_DESCRIPTION_CSV_V1",
        "DATASET_DESCRIPTION_XLSX_V1",
    ]
    expires_at: datetime
    version: int
    validation_summary: dict[str, object]
    last_error_code: str | None
    recommended_part_size_bytes: int = 16 * 1024 * 1024


class UploadListResponse(BaseModel):
    items: list[UploadResponse]


class UploadPreparationResponse(BaseModel):
    id: UUID
    upload_id: UUID
    content_profile: Literal[
        "CATALOG_METADATA_ROWS_CSV_V1",
        "CATALOG_METADATA_ROWS_XLSX_V1",
        "DATASET_DESCRIPTION_CSV_V1",
        "DATASET_DESCRIPTION_XLSX_V1",
    ]
    source_manifest_version: int = Field(ge=1)
    source_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    configuration_hash: str = Field(pattern="^[0-9a-f]{64}$")
    state: Literal["QUEUED", "PREPARING", "READY", "FAILED", "CANCELLED", "STALE"]
    attempts: int = Field(ge=0)
    rows_processed: int = Field(ge=0)
    total_rows: int | None = Field(default=None, ge=0)
    last_error_code: str | None
    created_at: datetime
    updated_at: datetime
    version: int = Field(ge=1)


class UploadPreparationListResponse(BaseModel):
    items: list[UploadPreparationResponse]


class RegistrationOperatorCapabilityResponse(BaseModel):
    eligible: bool
    can_view_workspace_history: bool
    reason_code: Literal[
        "ELIGIBLE",
        "ACTIVE_HUMAN_ADMIN_OR_DATA_STEWARD_REQUIRED",
    ]
    allowed_roles: tuple[Literal["ADMIN"], Literal["DATA_STEWARD"]]


class UploadCandidateSubmittedIdentityResponse(BaseModel):
    platform: str
    database_name: str
    schema_name: str
    table_name: str
    identity_hash: str = Field(pattern="^[0-9a-f]{64}$")


class UploadCandidateCurrentTargetResponse(BaseModel):
    id: UUID
    asset_type: Literal["DATASET"]
    name: str
    platform: str
    database_name: str
    schema_name: str
    classification: Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]
    lifecycle: Literal["ACTIVE"]
    source_version: str
    observed_at: datetime


class UploadRegistrationCandidateResponse(BaseModel):
    id: UUID
    ordinal: int = Field(ge=1)
    evidence_version: Literal["DATASET_DESCRIPTION_CANDIDATE_V2"]
    candidate_kind: Literal["DATASET_DESCRIPTION_UPDATE"]
    proposed_description: str = Field(max_length=10_000)
    submitted_identity: UploadCandidateSubmittedIdentityResponse
    candidate_hash: str = Field(pattern="^[0-9a-f]{64}$")
    created_at: datetime
    current_target: UploadCandidateCurrentTargetResponse


class UploadCandidateReceiptResponse(BaseModel):
    id: UUID
    preparation_id: UUID
    manifest_version: int = Field(ge=1)
    source_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    content_profile: Literal["DATASET_DESCRIPTION_CSV_V1", "DATASET_DESCRIPTION_XLSX_V1"]
    parser_version: str
    scanner_version: str
    schema_version: str
    configuration_hash: str = Field(pattern="^[0-9a-f]{64}$")
    candidate_root_hash: str = Field(pattern="^[0-9a-f]{64}$")
    receipt_hash: str = Field(pattern="^[0-9a-f]{64}$")
    observed_at: datetime
    created_at: datetime


class UploadCandidatePolicyMetaResponse(BaseModel):
    projection_version: int = Field(ge=0)
    policy_version: str
    classification_policy_version: int | None = Field(default=None, ge=1)
    authorization_generation: int | None = Field(default=None, ge=0)


class UploadRegistrationCandidateListResponse(BaseModel):
    items: list[UploadRegistrationCandidateResponse]
    page: PageMeta
    receipt: UploadCandidateReceiptResponse
    meta: UploadCandidatePolicyMetaResponse


class TypedBulkCandidatePreviewResponse(BaseModel):
    candidate_id: UUID
    target_asset_id: UUID
    target_ref: str
    platform: str
    database_name: str
    schema_name: str
    table_name: str
    current_description: str | None
    proposed_description: str
    before_hash: str = Field(pattern="^[0-9a-f]{64}$")
    after_hash: str = Field(pattern="^[0-9a-f]{64}$")
    source_version: str
    observed_at: datetime
    preview_etag: str = Field(pattern='^"[0-9a-f]{64}"$')


class TypedBulkChangeRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=10_000)

    @field_validator("title", "reason")
    @classmethod
    def require_auditable_text(cls, value: str) -> str:
        if "\x00" in value or not value.strip():
            raise ValueError("Typed BULK change fields must contain safe visible text.")
        return value


class CatalogMetadataCandidateResponse(BaseModel):
    id: UUID
    ordinal: int = Field(ge=1, le=10_000)
    evidence_version: Literal["CATALOG_METADATA_CANDIDATE_V3"]
    record_kind: Literal[
        "TABLE_DESCRIPTION",
        "COLUMN_DESCRIPTION",
        "DATASET_DOMAIN",
        "DATASET_TERM",
        "DATASET_TAG",
    ]
    candidate_kind: Literal[
        "TABLE_DESCRIPTION_UPDATE",
        "COLUMN_DESCRIPTION_UPDATE",
        "DATASET_DOMAIN_UPDATE",
        "DATASET_TERM_ADD",
        "DATASET_TAG_ADD",
    ]
    operation_count: int = Field(ge=1, le=10_000)
    field_path_sample: list[str] = Field(max_length=20)
    controlled_reference_count: int = Field(ge=0, le=10_000)
    row_summary_truncated: bool
    submitted_identity: UploadCandidateSubmittedIdentityResponse
    candidate_hash: str = Field(pattern="^[0-9a-f]{64}$")
    created_at: datetime
    current_target: UploadCandidateCurrentTargetResponse


class CatalogMetadataCandidateReceiptResponse(BaseModel):
    id: UUID
    preparation_id: UUID
    manifest_version: int = Field(ge=1)
    source_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    content_profile: Literal[
        "CATALOG_METADATA_ROWS_CSV_V1",
        "CATALOG_METADATA_ROWS_XLSX_V1",
    ]
    parser_version: str
    scanner_version: str
    schema_version: str
    configuration_hash: str = Field(pattern="^[0-9a-f]{64}$")
    item_count: int = Field(ge=1, le=10_000)
    candidate_count: int = Field(ge=1, le=10_000)
    candidate_root_hash: str = Field(pattern="^[0-9a-f]{64}$")
    receipt_hash: str = Field(pattern="^[0-9a-f]{64}$")
    observed_at: datetime
    created_at: datetime


class CatalogMetadataCandidateListResponse(BaseModel):
    items: list[CatalogMetadataCandidateResponse] = Field(max_length=50)
    page: PageMeta
    receipt: CatalogMetadataCandidateReceiptResponse
    meta: UploadCandidatePolicyMetaResponse


class CatalogMetadataDescriptionChangeResponse(BaseModel):
    field_path: str | None
    current_description: str | None
    proposed_description: str | None


class TypedCatalogMetadataPreviewResponse(BaseModel):
    candidate_id: UUID
    target_asset_id: UUID
    platform: str
    database_name: str
    schema_name: str
    table_name: str
    record_kind: Literal[
        "TABLE_DESCRIPTION",
        "COLUMN_DESCRIPTION",
        "DATASET_DOMAIN",
        "DATASET_TERM",
        "DATASET_TAG",
    ]
    candidate_kind: Literal[
        "TABLE_DESCRIPTION_UPDATE",
        "COLUMN_DESCRIPTION_UPDATE",
        "DATASET_DOMAIN_UPDATE",
        "DATASET_TERM_ADD",
        "DATASET_TAG_ADD",
    ]
    operation_count: int = Field(ge=1, le=10_000)
    description_change_count: int = Field(ge=0, le=10_000)
    description_change_sample: list[CatalogMetadataDescriptionChangeResponse] = Field(max_length=20)
    description_changes_truncated: bool
    current_reference_count: int = Field(ge=0, le=100)
    proposed_reference_count: int = Field(ge=0, le=100)
    before_hash: str = Field(pattern="^[0-9a-f]{64}$")
    after_hash: str = Field(pattern="^[0-9a-f]{64}$")
    source_version: str
    observed_at: datetime
    preview_etag: str = Field(pattern='^"[0-9a-f]{64}"$')


class TypedCatalogMetadataChangeRequestResponse(BaseModel):
    id: UUID
    number: str
    request_type: Literal["BULK_CATALOG_METADATA"]
    state: str


class UploadPartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part_number: int = Field(ge=1, le=10_000)
    checksum_sha256: str | None = Field(default=None, min_length=20, max_length=100)


class UploadPartResponse(BaseModel):
    part_number: int
    url: str
    expires_in_seconds: int


class CompletedPartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part_number: int = Field(ge=1, le=10_000)
    etag: str = Field(min_length=1, max_length=200)
    checksum_sha256: str | None = Field(default=None, min_length=20, max_length=100)


class UploadCompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parts: list[CompletedPartRequest] = Field(min_length=1, max_length=10_000)


class UploadRegistrationProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_ref: str = Field(min_length=16, max_length=4096, pattern="^urn:li:dataset:")
    aspect_name: Literal[
        "datasetProperties",
        "domains",
        "globalTags",
        "glossaryTerms",
        "ownership",
        "schemaMetadata",
    ]
    before_hash: str = Field(pattern="^[0-9a-f]{64}$")
    after_document: dict[str, Any]
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=8000)


ControlledMetadataReference = Annotated[str, Field(min_length=1, max_length=1_000)]


class ManualMetadataColumnEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_path: str = Field(min_length=1, max_length=2_000)
    description: str = Field(default="", max_length=10_000)
    tags: list[ControlledMetadataReference] = Field(default_factory=list, max_length=100)
    terms: list[ControlledMetadataReference] = Field(default_factory=list, max_length=100)

    @field_validator("field_path", "description", "tags", "terms")
    @classmethod
    def reject_nul(cls, value: str | list[str]) -> str | list[str]:
        values = (value,) if isinstance(value, str) else value
        if any("\x00" in item for item in values):
            raise ValueError("Manual metadata text must not contain NUL characters.")
        return value


class ManualMetadataSubmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: UUID
    source_version: str = Field(min_length=1, max_length=255)
    provider_source_version: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    description: str = Field(default="", max_length=10_000)
    domain: str | None = Field(default=None, max_length=1_000)
    tags: list[ControlledMetadataReference] = Field(default_factory=list, max_length=100)
    terms: list[ControlledMetadataReference] = Field(default_factory=list, max_length=100)
    # `columns` preserves the original `/api/v1` full-schema request. New clients send sparse
    # `column_edits`; accepting both shapes is an additive v1 evolution, not a replacement.
    columns: list[ManualMetadataColumnEditRequest] | None = Field(
        default=None,
        min_length=1,
        max_length=2_000,
    )
    column_edits: list[ManualMetadataColumnEditRequest] | None = Field(
        default=None,
        max_length=1_000,
    )

    @field_validator(
        "source_version",
        "provider_source_version",
        "description",
        "domain",
        "tags",
        "terms",
    )
    @classmethod
    def reject_manual_submission_nul(cls, value: str | list[str] | None) -> str | list[str] | None:
        if value is None:
            return value
        values = (value,) if isinstance(value, str) else value
        if any("\x00" in item for item in values):
            raise ValueError("Manual metadata text must not contain NUL characters.")
        return value

    @model_validator(mode="after")
    def require_one_column_contract(self) -> ManualMetadataSubmissionRequest:
        if self.columns is not None and self.column_edits is not None:
            raise ValueError("Use either legacy columns or sparse column_edits, not both.")
        if self.columns is None and self.column_edits is None:
            raise ValueError("Manual metadata requires columns or column_edits.")
        return self


class ManualMetadataSubmissionResponse(BaseModel):
    id: UUID
    state: Literal["QUEUED", "APPLYING", "APPLIED", "FAILED"]
    serial_number: int = Field(ge=1)
    row_count: int = Field(ge=1)
    source_version: str
    provider_source_version: str = Field(pattern="^[0-9a-f]{64}$")
    created_at: datetime
    version: int = Field(ge=1)


class ManualMetadataSubmissionStatusResponse(ManualMetadataSubmissionResponse):
    updated_at: datetime
    applied_at: datetime | None
    attempts: int = Field(ge=0, le=20)
    next_attempt_at: datetime | None
    last_error_code: str | None


class ManualMetadataSubmissionListResponse(BaseModel):
    items: list[ManualMetadataSubmissionStatusResponse]
    page: PageMeta


class ManualMetadataAspectReportResponse(BaseModel):
    aspect_name: Literal[
        "datasetProperties",
        "domains",
        "globalTags",
        "glossaryTerms",
        "schemaMetadata",
    ]
    aspect_ordinal: int = Field(ge=1, le=5)
    outcome: Literal[
        "ALREADY_MATCHED",
        "APPLIED_VERIFIED",
        "FAILED_BEFORE_WRITE",
        "WRITE_REJECTED",
        "READBACK_FAILED",
        "READBACK_MISMATCH",
    ]
    before_hash: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    expected_hash: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    observed_hash: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    write_attempted: bool
    failure_code: str | None
    provider_version: str | None
    provider_response_hash: str | None
    observed_at: datetime


class ManualMetadataApplyAttemptResponse(BaseModel):
    id: UUID
    attempt_no: int = Field(ge=1, le=20)
    lease_epoch: int = Field(ge=1)
    state: Literal["RUNNING", "APPLIED", "RETRY_WAIT", "FAILED", "SUPERSEDED"]
    failure_code: str | None
    report_root_hash: str | None
    started_at: datetime
    finished_at: datetime | None
    aspects: list[ManualMetadataAspectReportResponse]


class ManualMetadataSubmissionReportResponse(BaseModel):
    submission: ManualMetadataSubmissionStatusResponse
    attempts: list[ManualMetadataApplyAttemptResponse]


class ManualMetadataApplyResponse(BaseModel):
    processed: bool
    submission_id: UUID | None = None
    serial_number: int | None = Field(default=None, ge=1)
    state: Literal["QUEUED", "FAILED", "APPLIED", "SUPERSEDED"] | None = None


class BulkPreparationExecuteResponse(BaseModel):
    processed: bool
    preparation_id: UUID | None = None
    state: Literal["READY", "QUEUED", "FAILED", "SUPERSEDED"] | None = None
    item_count: int | None = Field(default=None, ge=1)


class OntologyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_types: set[str] = Field(min_length=1, max_length=200)
    edge_types: set[str] = Field(min_length=1, max_length=200)


class KnowledgeGraphCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern="^[a-z][a-z0-9-]{2,99}$")
    name: str = Field(min_length=1, max_length=255)
    graph_type: str = Field(pattern="^(CATALOG_MIRROR|CURATED_KNOWLEDGE|ANALYTIC_PRODUCT)$")
    classification: str = Field(
        default="INTERNAL", pattern="^(PUBLIC|INTERNAL|CONFIDENTIAL|RESTRICTED)$"
    )
    ontology: OntologyRequest


class KnowledgeGraphResponse(BaseModel):
    id: UUID
    slug: str
    name: str
    graph_type: str
    status: str
    classification: str
    active_release_id: UUID | None
    version: int


class ProvenanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_ref: str = Field(min_length=1, max_length=2000)
    source_locator: str = Field(min_length=1, max_length=4000)
    source_version: str = Field(min_length=1, max_length=500)
    method: str = Field(min_length=1, max_length=100)
    confidence: float = Field(ge=0, le=1)
    evidence_excerpt: str | None = Field(default=None, min_length=1, max_length=1000)
    evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_page_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class GraphNodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    entity_type: str = Field(min_length=1, max_length=100)
    properties: dict[str, Any]
    classification: int = Field(ge=0, le=3)
    provenance: list[ProvenanceRequest] = Field(min_length=1, max_length=100)


class GraphEdgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    source_id: UUID
    target_id: UUID
    edge_type: str = Field(min_length=1, max_length=100)
    properties: dict[str, Any]
    classification: int = Field(ge=0, le=3)
    provenance: list[ProvenanceRequest] = Field(min_length=1, max_length=100)


class KnowledgeReleasePublish(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[GraphNodeRequest] = Field(max_length=2000)
    edges: list[GraphEdgeRequest] = Field(max_length=5000)


class KnowledgeReleaseResponse(BaseModel):
    id: UUID
    graph_id: UUID
    release_no: int
    ontology_version_id: UUID
    content_hash: str
    node_count: int
    edge_count: int
    published_at: datetime


class KnowledgeChangeSetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)


class KnowledgeChangeOperationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1, le=10_000)
    operation: str = Field(pattern="^(UPSERT|DELETE)$")
    entity_kind: str = Field(pattern="^(NODE|EDGE)$")
    stable_entity_id: UUID
    document: dict[str, Any]
    provenance: list[ProvenanceRequest] = Field(min_length=1, max_length=100)
    confidence: float = Field(ge=0, le=1)


class KnowledgeChangeOperationResponse(BaseModel):
    id: UUID
    sequence: int
    operation: str
    entity_kind: str
    stable_entity_id: UUID
    document: dict[str, Any]
    provenance: list[ProvenanceRequest]
    confidence: float


class KnowledgeValidationResponse(BaseModel):
    id: UUID
    severity: str
    code: str
    location: str
    message: str
    validator: str
    validator_version: str


class KnowledgeChangeSetResponse(BaseModel):
    id: UUID
    graph_id: UUID
    base_release_id: UUID | None
    ontology_version_id: UUID
    title: str
    state: str
    author_id: UUID
    reviewed_by: UUID | None
    review_reason: str | None
    published_release_id: UUID | None
    version: int
    created_at: datetime
    updated_at: datetime
    operations: list[KnowledgeChangeOperationResponse]
    validations: list[KnowledgeValidationResponse]


class KnowledgeChangeSetReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(pattern="^(APPROVED|REJECTED)$")
    reason: str = Field(min_length=1, max_length=4000)


class KnowledgeChangeSetPublishResponse(BaseModel):
    changeset: KnowledgeChangeSetResponse
    release: KnowledgeReleaseResponse


class GraphNodeResponse(GraphNodeRequest):
    pass


class GraphEdgeResponse(GraphEdgeRequest):
    pass


class KnowledgeSnapshotResponse(BaseModel):
    release: KnowledgeReleaseResponse
    nodes: list[GraphNodeResponse]
    edges: list[GraphEdgeResponse]
    filtered: bool


class NeighborAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: UUID
    direction: str = Field(default="BOTH", pattern="^(IN|OUT|BOTH)$")
    edge_types: set[str] = Field(default_factory=set, max_length=100)
    maximum_hops: int = Field(default=1, ge=1, le=3)
    maximum_nodes: int = Field(default=100, ge=1, le=500)


class NeighborAnalysisResponse(BaseModel):
    release: KnowledgeReleaseResponse
    nodes: list[GraphNodeResponse]
    edges: list[GraphEdgeResponse]
    truncated: bool


class KnowledgeSourceAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)


class KnowledgeSourceJobResultResponse(BaseModel):
    changeset_id: UUID
    page_count: int = Field(ge=1)
    proposed_node_count: int = Field(ge=0)
    proposed_edge_count: int = Field(ge=0)
    evidence_hash: str = Field(pattern="^[0-9a-f]{64}$")
    embedding_model: str
    extraction_model: str


class KnowledgeSourceJobResponse(BaseModel):
    id: UUID
    graph_id: UUID
    source_snapshot_id: UUID
    upload_id: UUID
    title: str
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
    stage: Literal[
        "QUEUED",
        "SOURCE_READ",
        "PARSED",
        "EMBEDDED",
        "EXTRACTED",
        "FINALIZING",
        "COMPLETED",
    ]
    progress: dict[str, int]
    attempt_count: int = Field(ge=0)
    maximum_attempts: int = Field(ge=1)
    next_attempt_at: datetime
    last_failure_code: str | None
    version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    result: KnowledgeSourceJobResultResponse | None


class KnowledgeSourceJobPageResponse(BaseModel):
    items: list[KnowledgeSourceJobResponse]
    next_cursor: str | None


class KnowledgeSourceJobCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1000)


class KnowledgeProjectionResponse(BaseModel):
    deployment_id: UUID
    release_id: UUID
    release_hash: str = Field(pattern="^[0-9a-f]{64}$")
    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    state: Literal["SHADOW_VERIFIED"]


class KnowledgeGraphRagRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=2, max_length=4000)
    start_node_id: UUID | None = None
    direction: Literal["IN", "OUT", "BOTH"] = "BOTH"
    edge_types: set[str] = Field(default_factory=set, max_length=50)
    maximum_hops: int = Field(default=1, ge=1, le=3)
    maximum_nodes: int = Field(
        default=MAX_GRAPHRAG_QUERY_NODES,
        ge=1,
        le=MAX_GRAPHRAG_QUERY_NODES,
    )


class KnowledgeGraphRagCitationResponse(BaseModel):
    evidence_id: str
    source_locator: str
    source_version: str
    page_number: int | None
    entity_kind: Literal["NODE", "EDGE"] | None = None
    entity_id: UUID | None = None
    source_entity_id: UUID | None = None
    target_entity_id: UUID | None = None
    edge_type: str | None = None
    evidence_excerpt: str | None = None
    evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_page_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class KnowledgeModelAuditResponse(BaseModel):
    provider: str
    model: str
    prompt_version: str
    tool_schema_version: str
    configuration_source: Literal["DEPLOYMENT", "SYSTEM_CONFIGURATION"] | None = None
    configuration_version: int | None = Field(default=None, ge=1)
    configuration_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class KnowledgeGraphRagResponse(NeighborAnalysisResponse):
    answer: str
    citations: list[KnowledgeGraphRagCitationResponse]
    model_audit: KnowledgeModelAuditResponse


class ChatQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID | None = None
    question: str = Field(min_length=2, max_length=4000)
    maximum_evidence: int = Field(default=5, ge=1, le=10)
    mode: ChatRetrievalMode = ChatRetrievalMode.AUTO


class ChatEvidenceResponse(BaseModel):
    chunk_id: UUID
    resource_id: UUID
    classification: str
    system_id: UUID | None
    domain_id: UUID | None
    owner_department_id: UUID | None
    name: str
    description: str | None
    source_type: str
    source_locator: str
    source_version: str
    content_hash: str
    effective_from: datetime
    effective_until: datetime | None
    extraction_method: str
    rank: int = Field(ge=1, le=10)
    retrieval_method: str = Field(min_length=1, max_length=100)


class ChatRouteResponse(BaseModel):
    requested_mode: ChatRetrievalMode
    selected_mode: ChatRetrievalMode
    reason: ChatRouteReason
    adapter_state: ChatAdapterState


class ChatWorkflowEventResponse(BaseModel):
    stage: ChatWorkflowStage
    status: ChatWorkflowStatus
    detail_code: str = Field(min_length=1, max_length=100)


class ChatQueryResponse(BaseModel):
    session_id: UUID
    request_message_id: UUID
    response_message_id: UUID
    answer: str
    persistence: Literal["PERSISTED", "EPHEMERAL_NO_STORE"]
    route: ChatRouteResponse
    workflow: list[ChatWorkflowEventResponse] = Field(max_length=20)
    evidence: list[ChatEvidenceResponse]


class ChatSessionResponse(BaseModel):
    id: UUID
    title: str
    is_favorite: bool
    version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime
    message_count: int


class ChatMessageResponse(BaseModel):
    id: UUID
    session_id: UUID
    role: Literal["user", "assistant"]
    content: str
    evidence_json: list[ChatEvidenceResponse] | None
    created_at: datetime
    route: ChatRouteResponse | None = None
    workflow: list[ChatWorkflowEventResponse] = Field(default_factory=list, max_length=20)


class ChatFavoriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_favorite: bool
    expected_version: int = Field(ge=1)


class CatalogSchemaMetricResponse(BaseModel):
    """Current typed DataHub projection coverage for one source hierarchy branch."""

    platform: str | None
    database_name: str | None
    schema_name: str | None
    asset_count: int
    described_asset_count: int


class OperationsSummaryResponse(BaseModel):
    observed_at: datetime
    jobs_by_state: dict[str, int]
    uploads_by_state: dict[str, int]
    changes_by_state: dict[str, int]
    catalog_asset_count: int
    catalog_described_asset_count: int
    catalog_schema_metrics: list[CatalogSchemaMetricResponse]
    catalog_schema_metrics_truncated: bool
    unpublished_outbox_events: int
    dead_lettered_outbox_events: int
    oldest_unpublished_age_seconds: int | None
    retention_automation_state: Literal["DISABLED_NOT_READY"]


class ApiContractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scopes: list[str] = Field(min_length=1, max_length=20)
    response_schema: dict[str, Any]
    query_template: str = Field(min_length=1, max_length=100)

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, value: list[str]) -> list[str]:
        allowed = {"snapshot.read", "neighbors.query", "chat.query"}
        scopes = [item.strip() for item in value]
        if len(set(scopes)) != len(scopes) or not set(scopes).issubset(allowed):
            raise ValueError("Contract scopes must be unique supported scopes.")
        return scopes


class ApiProductVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    release_id: UUID
    surface: str = Field(pattern="^(SNAPSHOT|NEIGHBORS|CHAT)$")
    contract: ApiContractRequest
    maximum_hops: int = Field(default=1, ge=1, le=3)
    maximum_nodes: int = Field(default=100, ge=1, le=500)
    timeout_ms: int = Field(default=5000, ge=100, le=30_000)

    @model_validator(mode="after")
    def surface_scope_matches(self) -> ApiProductVersionCreate:
        required = {
            "SNAPSHOT": "snapshot.read",
            "NEIGHBORS": "neighbors.query",
            "CHAT": "chat.query",
        }[self.surface]
        if required not in self.contract.scopes:
            raise ValueError(f"The {self.surface} surface requires the {required} scope.")
        return self


class ApiProductCreate(ApiProductVersionCreate):
    slug: str = Field(pattern="^[a-z][a-z0-9-]{2,99}$")
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=10_000)
    graph_id: UUID


class ApiProductVersionResponse(BaseModel):
    id: UUID
    product_id: UUID
    graph_id: UUID
    release_id: UUID
    version_no: int
    surface: str
    contract: dict[str, Any]
    maximum_hops: int
    maximum_nodes: int
    timeout_ms: int
    state: str
    published_at: datetime | None


class ApiProductResponse(BaseModel):
    id: UUID
    slug: str
    name: str
    description: str
    graph_id: UUID
    classification: str
    owner_id: UUID
    state: str
    current_version_id: UUID | None
    version: int
    versions: list[ApiProductVersionResponse]


class ConsumerGrantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consumer_subject_id: UUID
    consumer_client_id: str = Field(min_length=3, max_length=255, pattern="^[A-Za-z0-9._:-]+$")
    scopes: set[str] = Field(min_length=1, max_length=20)
    maximum_classification: str = Field(pattern="^(PUBLIC|INTERNAL|CONFIDENTIAL|RESTRICTED)$")
    requests_per_minute: int = Field(default=60, ge=1, le=10_000)
    monthly_quota: int = Field(default=100_000, ge=1, le=100_000_000)
    valid_from: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def validate_period(self) -> ConsumerGrantCreate:
        if self.valid_from.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("Grant timestamps must include a timezone.")
        if self.expires_at <= self.valid_from:
            raise ValueError("Grant expiration must be after its start time.")
        return self


class ConsumerGrantResponse(BaseModel):
    id: UUID
    product_id: UUID
    product_version_id: UUID
    contract_version: str
    consumer_subject_id: UUID | None
    consumer_issuer: str | None
    consumer_client_id: str
    scopes: list[str]
    maximum_classification: str
    requests_per_minute: int
    monthly_quota: int
    valid_from: datetime
    expires_at: datetime
    state: str
    version: int


class ApiInvocationAuthorizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_scope: str = Field(pattern="^(snapshot.read|neighbors.query|chat.query)$")


class ApiSnapshotInvokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    maximum_nodes: int = Field(default=100, ge=1, le=500)


class ApiProductChatInvokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=2, max_length=4000)
    maximum_evidence: int = Field(default=5, ge=1, le=10)


class ApiProductChatEvidenceResponse(BaseModel):
    entity_id: UUID
    entity_type: str
    name: str
    source_locator: str
    source_version: str


class ApiProductChatInvokeResponse(BaseModel):
    invocation_id: UUID
    answer: str
    evidence: list[ApiProductChatEvidenceResponse]
