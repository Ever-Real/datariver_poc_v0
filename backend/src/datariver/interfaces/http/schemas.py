from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from datariver.domain.authz import Action


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
    classification: str
    lifecycle: str
    observed_at: datetime
    matches: list[CatalogMatchFragmentResponse] = Field(default_factory=list)


class CatalogMatchFragmentResponse(BaseModel):
    field: Literal["NAME", "DESCRIPTION"]
    text: str
    matched_terms: list[str]


class CatalogSearchResponse(BaseModel):
    items: list[CatalogAssetSummary]
    page: PageMeta
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
    meta: CatalogDiscoveryPolicyMeta


class CatalogSuggestionResponse(BaseModel):
    id: UUID
    name: str
    asset_type: str
    platform: str | None


class CatalogSuggestionsResponse(BaseModel):
    items: list[CatalogSuggestionResponse]
    meta: CatalogDiscoveryPolicyMeta


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
    glossary_terms: list[dict[str, Any]]
    tags: list[str]
    schema_fields: list[dict[str, Any]]
    quality: dict[str, Any]
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


class CatalogExportCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: str = Field(default="", max_length=500)
    asset_type: str | None = Field(default=None, min_length=1, max_length=100)
    platform: str | None = Field(default=None, min_length=1, max_length=100)
    classification: Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"] | None = None
    lifecycle: Literal["ACTIVE"] | None = None
    sort: Literal["NAME_ASC"] = "NAME_ASC"
    format: Literal["CSV"] = "CSV"


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
    items: list[ChangeItemRequest] = Field(min_length=1, max_length=1)


class TransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_state: str
    reason: str = Field(min_length=1, max_length=4000)


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str = Field(pattern="^(REVIEW|FINAL)$")
    decision: str = Field(pattern="^(APPROVED|REJECTED)$")
    reason: str = Field(min_length=1, max_length=4000)


class ChangeItemResponse(BaseModel):
    id: UUID
    target_type: str
    target_ref: str
    aspect_name: str
    operation: str
    before_hash: str | None
    after_hash: str | None
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


class ApprovalResponse(BaseModel):
    id: UUID
    stage: str
    decision: str
    actor_id: UUID
    reason: str
    occurred_at: datetime


class TransitionResponse(BaseModel):
    id: UUID
    from_state: str
    to_state: str
    actor_id: UUID
    reason: str
    occurred_at: datetime


class ChangeRequestResponse(BaseModel):
    id: UUID
    number: str
    request_type: str
    title: str
    description: str
    state: str
    requester_id: UUID
    classification: str
    version: int
    items: list[ChangeItemResponse]
    approvals: list[ApprovalResponse]
    transitions: list[TransitionResponse]


class ChangeRequestListResponse(BaseModel):
    items: list[ChangeRequestResponse]


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


class CapabilitiesResponse(BaseModel):
    items: list[CapabilityResponse]
    external_system_links: list[ExternalSystemLinkResponse] = Field(default_factory=list)
    deployment_tier: Literal["SINGLE_NODE_PILOT", "HA_CANDIDATE", "HA_ACCEPTED"]


class AuthMeResponse(BaseModel):
    subject: str
    display_name: str
    email: str | None = None
    roles: list[str] = Field(default_factory=list)
    authentication_assurance: str
    authentication_time: datetime | None


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
    subject_active: bool
    membership_active: bool
    department_id: UUID | None
    job_function: str | None
    clearance: Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]
    membership_version: int = Field(ge=1)


class WorkspaceMembershipListResponse(BaseModel):
    items: list[WorkspaceMembershipSummaryResponse]


class WorkspaceMembershipAccessResponse(BaseModel):
    subject_id: UUID
    display_name: str
    subject_active: bool
    department_id: UUID | None
    job_function: str | None
    membership_version: int = Field(ge=1)
    access: MembershipAccessDocumentResponse


class AdminReadContextResponse(BaseModel):
    subject_id: UUID
    workspace_id: UUID
    display_name: str
    authentication_assurance: Literal["PASSWORD_REAUTH", "HARDWARE_WEBAUTHN"]
    fallback_enabled: bool
    allowed_operations: list[
        Literal[
            "MEMBERSHIP_ACCESS_READ",
            "MEMBERSHIP_ACCESS_UPDATE",
            "FALLBACK_REQUEST_READ",
            "FALLBACK_REQUEST_CREATE",
            "FALLBACK_REQUEST_DECIDE",
            "FALLBACK_REQUEST_CONSUME",
            "CLASSIFICATION_POLICY_READ",
            "CLASSIFICATION_POLICY_PROPOSE",
            "CLASSIFICATION_POLICY_DECIDE",
            "INFERENCE_PROVIDER_PROFILE_READ",
            "INFERENCE_PROVIDER_PROFILE_DECIDE",
            "INFERENCE_PROVIDER_PROFILE_REVOKE",
            "RESTRICTED_SEARCH_GRANT_READ",
            "RESTRICTED_SEARCH_GRANT_PROPOSE",
            "RESTRICTED_SEARCH_GRANT_DECIDE",
            "RESTRICTED_SEARCH_GRANT_REVOKE",
            "RETENTION_POLICY_READ",
            "RETENTION_POLICY_MANAGE",
            "LEGAL_HOLD_READ",
            "LEGAL_HOLD_PLACE",
            "LEGAL_HOLD_RELEASE",
            "ERASURE_READ",
            "ERASURE_REQUEST",
            "ERASURE_APPROVE",
        ]
    ]
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
            "^(text/csv|application/json|application/x-parquet|"
            "application/vnd.apache.parquet|application/yaml|text/yaml|"
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet)$"
        )
    )
    sha256: str = Field(pattern="^[0-9a-f]{64}$")
    classification: str = Field(
        default="INTERNAL", pattern="^(PUBLIC|INTERNAL|CONFIDENTIAL|RESTRICTED)$"
    )
    content_profile: Literal["FORMAT_ONLY_V1", "DATASET_DESCRIPTION_CSV_V1"] = "FORMAT_ONLY_V1"

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
    content_profile: Literal["FORMAT_ONLY_V1", "DATASET_DESCRIPTION_CSV_V1"]
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
    content_profile: Literal["DATASET_DESCRIPTION_CSV_V1"]
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
    content_profile: Literal["DATASET_DESCRIPTION_CSV_V1"]
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


class ChatQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID | None = None
    question: str = Field(min_length=2, max_length=4000)
    maximum_evidence: int = Field(default=5, ge=1, le=10)


class ChatEvidenceResponse(BaseModel):
    chunk_id: UUID
    resource_id: UUID
    classification: str
    system_id: UUID | None
    domain_id: UUID | None
    owner_department_id: UUID | None
    name: str
    source_type: str
    source_locator: str
    source_version: str
    content_hash: str
    effective_from: datetime
    effective_until: datetime | None
    extraction_method: str


class ChatQueryResponse(BaseModel):
    session_id: UUID
    request_message_id: UUID
    response_message_id: UUID
    answer: str
    evidence: list[ChatEvidenceResponse]


class OperationsSummaryResponse(BaseModel):
    observed_at: datetime
    jobs_by_state: dict[str, int]
    uploads_by_state: dict[str, int]
    changes_by_state: dict[str, int]
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


class ApiInvocationAuthorizationResponse(BaseModel):
    invocation_id: UUID
    grant_id: UUID
    product_id: UUID
    product_version_id: UUID
    graph_id: UUID
    release_id: UUID
    surface: str
    requested_scope: str
    maximum_classification: str
    maximum_hops: int
    maximum_nodes: int
    timeout_ms: int


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
