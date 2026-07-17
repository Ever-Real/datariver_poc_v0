from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any
from uuid import UUID

from datariver.application.classification_access import ClassificationAccessSnapshot
from datariver.domain.admin_access import AdminOperation
from datariver.domain.authz import (
    Action,
    AuthenticationAssurance,
    Classification,
    Decision,
    SubjectAttributes,
)
from datariver.domain.governance import ChangeRequest


@dataclass(frozen=True, slots=True)
class CatalogAssetIndex:
    asset_id: UUID
    workspace_id: UUID
    external_urn: str
    asset_type: str
    name: str
    description: str | None
    platform: str | None
    domain_id: UUID | None
    system_id: UUID | None
    owner_department_id: UUID | None
    classification: Classification
    lifecycle: str
    source_version: str
    observed_at: datetime
    database_name: str | None = None
    schema_name: str | None = None
    matches: tuple[CatalogMatchFragment, ...] = ()


@dataclass(frozen=True, slots=True)
class CatalogMatchFragment:
    field: str
    text: str
    matched_terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CatalogAssetDetail:
    index: CatalogAssetIndex
    ownership: tuple[dict[str, Any], ...]
    glossary_terms: tuple[dict[str, Any], ...]
    tags: tuple[str, ...]
    schema_fields: tuple[dict[str, Any], ...]
    quality: dict[str, Any]
    raw_version: str
    observed_at: datetime
    stale_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DecisionAuditItem:
    resource_id: UUID
    decision: Decision


@dataclass(frozen=True, slots=True)
class DataHubAssetEnrichment:
    ownership: tuple[dict[str, Any], ...]
    glossary_terms: tuple[dict[str, Any], ...]
    tags: tuple[str, ...]
    schema_fields: tuple[dict[str, Any], ...]
    quality: dict[str, Any]
    raw_version: str
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class DataHubScanAsset:
    external_urn: str
    asset_type: str
    name: str
    description: str | None
    platform: str | None
    domain_ref: str | None
    system_ref: str | None
    owner_ref: str | None
    classification: Classification | None
    source_version: str
    database_name: str | None = None
    schema_name: str | None = None


@dataclass(frozen=True, slots=True)
class DataHubLineageNode:
    external_urn: str
    degree: int
    paths: tuple[tuple[str, ...], ...]
    truncated_children: bool


@dataclass(frozen=True, slots=True)
class DataHubLineagePage:
    items: tuple[DataHubLineageNode, ...]
    total: int
    partial: bool


@dataclass(frozen=True, slots=True)
class DataHubScanPage:
    items: tuple[DataHubScanAsset, ...]
    next_offset: int | None
    total: int
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class CatalogSyncResult:
    upserted: int
    tombstoned: int
    next_offset: int | None
    total: int
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class CatalogPage:
    items: tuple[CatalogAssetIndex, ...]
    next_cursor: str | None
    observed_at: datetime
    stale_at: datetime | None = None
    projection_version: int = 0
    policy_version: str = ""
    classification_policy_version: int | None = None
    authorization_generation: int | None = None


@dataclass(frozen=True, slots=True)
class CatalogFacetBucket:
    value: str | None
    count: int


@dataclass(frozen=True, slots=True)
class CatalogFacets:
    asset_types: tuple[CatalogFacetBucket, ...]
    platforms: tuple[CatalogFacetBucket, ...]
    classifications: tuple[CatalogFacetBucket, ...]
    observed_at: datetime | None
    projection_version: int = 0
    policy_version: str = ""
    classification_policy_version: int | None = None
    authorization_generation: int | None = None


@dataclass(frozen=True, slots=True)
class CatalogSuggestion:
    asset_id: UUID
    name: str
    asset_type: str
    platform: str | None


@dataclass(frozen=True, slots=True)
class CatalogSuggestions:
    items: tuple[CatalogSuggestion, ...]
    observed_at: datetime | None
    projection_version: int = 0
    policy_version: str = ""
    classification_policy_version: int | None = None
    authorization_generation: int | None = None


@dataclass(frozen=True, slots=True)
class CatalogTreeNode:
    node_id: UUID
    kind: str
    label: str
    asset_count: int
    has_children: bool
    platform: str | None = None
    database_name: str | None = None
    schema_name: str | None = None
    asset: CatalogAssetIndex | None = None


@dataclass(frozen=True, slots=True)
class CatalogTreePage:
    items: tuple[CatalogTreeNode, ...]
    next_cursor: str | None
    observed_at: datetime | None
    projection_version: int = 0
    policy_version: str = ""
    classification_policy_version: int | None = None
    authorization_generation: int | None = None


@dataclass(frozen=True, slots=True)
class CatalogLineageEdge:
    source_asset_id: UUID
    target_asset_id: UUID


@dataclass(frozen=True, slots=True)
class CatalogLineage:
    center_asset_id: UUID
    nodes: tuple[CatalogAssetIndex, ...]
    edges: tuple[CatalogLineageEdge, ...]
    direction: str
    depth: int
    truncated: bool
    observed_at: datetime
    projection_version: int = 0
    policy_version: str = ""
    classification_policy_version: int | None = None
    authorization_generation: int | None = None


@dataclass(frozen=True, slots=True)
class UploadPreparationReceiptEvidence:
    receipt_id: UUID
    workspace_id: UUID
    preparation_id: UUID
    upload_id: UUID
    manifest_version: int
    source_sha256: str
    accepted_sha256: str
    content_profile: str
    parser_version: str
    scanner_version: str
    schema_version: str
    configuration_hash: str
    item_count: int
    rejected_count: int
    candidate_root_hash: str
    receipt_hash: str
    observed_at: datetime
    created_at: datetime
    candidate_count: int
    first_ordinal: int | None
    last_ordinal: int | None
    legacy_candidate_count: int


@dataclass(frozen=True, slots=True)
class UploadRegistrationCandidateEvidence:
    candidate_id: UUID
    workspace_id: UUID
    receipt_id: UUID
    ordinal: int
    target_asset_id: UUID
    candidate_kind: str
    proposed_description: str
    evidence_version: str
    submitted_platform: str | None
    submitted_database_name: str | None
    submitted_schema_name: str | None
    submitted_table_name: str | None
    submitted_identity_hash: str | None
    candidate_hash: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class UploadRegistrationCandidateView:
    evidence: UploadRegistrationCandidateEvidence
    current_target: CatalogAssetIndex


@dataclass(frozen=True, slots=True)
class UploadRegistrationCandidatePage:
    items: tuple[UploadRegistrationCandidateView, ...]
    next_cursor: str | None
    receipt: UploadPreparationReceiptEvidence
    projection_version: int
    policy_version: str
    classification_policy_version: int | None
    authorization_generation: int | None


@dataclass(frozen=True, slots=True)
class CatalogExportRequest:
    query: str
    filters: dict[str, str]
    sort: str = "NAME_ASC"
    format: str = "CSV"

    def document(self) -> dict[str, object]:
        return {
            "query": self.query,
            "filters": dict(sorted(self.filters.items())),
            "sort": self.sort,
            "format": self.format,
        }


@dataclass(frozen=True, slots=True)
class CatalogExportRecord:
    export_id: UUID
    workspace_id: UUID
    job_id: UUID
    requested_by: UUID
    request: CatalogExportRequest
    request_hash: str
    permission_scope_hash: str
    classification_access_hash: str
    builtin_policy_version: str
    classification_policy_id: UUID | None
    classification_policy_hash: str | None
    classification_policy_version: int | None
    authorization_generation: int | None
    source_projection_version: int
    classification_ceiling: Classification
    csv_safety_version: str
    display_name: str
    mime: str
    job_state: str
    last_error_code: str | None
    row_count: int | None
    size_bytes: int | None
    content_sha256: str | None
    provider_checksum: str | None
    object_bucket: str | None
    object_key: str | None
    created_at: datetime
    completed_at: datetime | None
    access_until: datetime


@dataclass(frozen=True, slots=True)
class CatalogExportClaim:
    export: CatalogExportRecord
    attempt_id: UUID
    attempt_no: int
    subject: SubjectAttributes
    access: ClassificationAccessSnapshot
    snapshot_valid: bool


@dataclass(frozen=True, slots=True)
class CatalogExportArtifact:
    size_bytes: int
    content_sha256: str
    provider_checksum: str | None


@dataclass(frozen=True, slots=True)
class CatalogExportDownload:
    url: str
    expires_seconds: int


@dataclass(frozen=True, slots=True)
class DataHubApplyReceipt:
    operation_id: str
    accepted_at: datetime
    provider_version: str
    response_hash: str


@dataclass(frozen=True, slots=True)
class DataHubAspectSnapshot:
    urn: str
    aspect_name: str
    content_hash: str
    source_version: str
    observed_at: datetime
    document: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True, slots=True)
class CatalogDescriptionPreview:
    asset_id: UUID
    target_ref: str
    aspect_name: str
    current_description: str | None
    proposed_description: str
    before_hash: str
    after_hash: str
    preview_etag: str
    source_version: str
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class CatalogColumnDescriptionPreview:
    asset_id: UUID
    target_ref: str
    aspect_name: str
    field_path: str
    current_description: str | None
    proposed_description: str
    before_hash: str
    after_hash: str
    preview_etag: str
    source_version: str
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class GovernanceApplyClaim:
    change_request: ChangeRequest
    job_id: UUID
    attempt_id: UUID
    attempt_no: int


@dataclass(frozen=True, slots=True)
class CapabilityStatus:
    name: str
    state: str
    observed_at: datetime
    latency_ms: int | None = None
    detail_code: str | None = None


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    request_hash: str
    result: dict[str, Any]


@dataclass(frozen=True, slots=True)
class WorkspaceMembershipSummary:
    subject_id: UUID
    display_name: str
    subject_active: bool
    membership_active: bool
    department_id: UUID | None
    job_function: str | None
    clearance: Classification
    membership_version: int


@dataclass(frozen=True, slots=True)
class WorkspaceMembershipAccessRecord:
    summary: WorkspaceMembershipSummary
    groups: frozenset[str]
    allowed_actions: frozenset[Action]
    denied_actions: frozenset[Action]
    allowed_system_ids: frozenset[UUID]
    allowed_domain_ids: frozenset[UUID]


@dataclass(frozen=True, slots=True)
class AdminReadContext:
    workspace_id: UUID
    membership: WorkspaceMembershipSummary
    authentication_assurance: AuthenticationAssurance
    allowed_operations: tuple[AdminOperation, ...]
    action_vocabulary: tuple[Action, ...]
    fallback_enabled: bool


@dataclass(frozen=True, slots=True)
class MultipartUpload:
    upload_id: str
    bucket: str
    object_key: str


@dataclass(frozen=True, slots=True)
class ObjectMetadata:
    bucket: str
    object_key: str
    size_bytes: int
    content_type: str
    etag: str
    checksum_sha256: str | None
    user_metadata: dict[str, str]


@dataclass(frozen=True, slots=True)
class KnowledgeGraphRecord:
    graph_id: UUID
    workspace_id: UUID
    slug: str
    name: str
    graph_type: str
    status: str
    classification: Classification
    active_release_id: UUID | None
    version: int


@dataclass(frozen=True, slots=True)
class KnowledgeReleaseRecord:
    release_id: UUID
    graph_id: UUID
    release_no: int
    ontology_version_id: UUID
    content_hash: str
    node_count: int
    edge_count: int
    published_at: datetime


@dataclass(frozen=True, slots=True)
class KnowledgeChangeOperationRecord:
    operation_id: UUID
    sequence: int
    operation: str
    entity_kind: str
    stable_entity_id: UUID
    document: dict[str, Any]
    provenance: tuple[dict[str, Any], ...]
    confidence: float


@dataclass(frozen=True, slots=True)
class KnowledgeValidationRecord:
    validation_id: UUID
    severity: str
    code: str
    location: str
    message: str
    validator: str
    validator_version: str


@dataclass(frozen=True, slots=True)
class KnowledgeChangeSetRecord:
    changeset_id: UUID
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
    operations: tuple[KnowledgeChangeOperationRecord, ...] = ()
    validations: tuple[KnowledgeValidationRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class ApiProductVersionRecord:
    version_id: UUID
    product_id: UUID
    graph_id: UUID
    release_id: UUID
    version_no: int
    surface: str
    contract_document: dict[str, Any]
    maximum_hops: int
    maximum_nodes: int
    timeout_ms: int
    state: str
    published_at: datetime | None


@dataclass(frozen=True, slots=True)
class ApiProductRecord:
    product_id: UUID
    workspace_id: UUID
    slug: str
    name: str
    description: str
    graph_id: UUID
    classification: Classification
    owner_id: UUID
    state: str
    current_version_id: UUID | None
    version: int
    versions: tuple[ApiProductVersionRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class ConsumerGrantRecord:
    grant_id: UUID
    product_id: UUID
    product_version_id: UUID
    consumer_client_id: str
    scopes: tuple[str, ...]
    maximum_classification: Classification
    requests_per_minute: int
    monthly_quota: int
    valid_from: datetime
    expires_at: datetime
    state: str
    version: int


@dataclass(frozen=True, slots=True)
class InvocationAuthorizationRecord:
    invocation_id: UUID
    grant_id: UUID
    product_id: UUID
    product_version_id: UUID
    graph_id: UUID
    release_id: UUID
    surface: str
    requested_scope: str
    maximum_classification: Classification
    maximum_hops: int
    maximum_nodes: int
    timeout_ms: int


@dataclass(frozen=True, slots=True)
class ChatEvidence:
    chunk_id: UUID
    workspace_id: UUID
    resource_id: UUID
    classification: Classification
    system_id: UUID | None
    domain_id: UUID | None
    owner_department_id: UUID | None
    name: str
    description: str | None
    source_locator: str
    source_version: str
    content_hash: str
    effective_from: datetime
    effective_until: datetime | None
    extraction_method: str
    source_type: str = "CATALOG_ASSET"


@dataclass(frozen=True, slots=True)
class KnowledgeEvidenceCandidate:
    evidence: ChatEvidence
    graph_id: UUID
    classification: Classification


@dataclass(frozen=True, slots=True)
class ChatDraft:
    answer: str
    cited_chunk_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class ChatRetentionBinding:
    policy_id: UUID
    policy_hash: str
    binding_basis_at: datetime
    chat_content_days: int


@dataclass(frozen=True, slots=True)
class ChatExchange:
    session_id: UUID
    request_message_id: UUID
    response_message_id: UUID
    answer: str
    evidence: tuple[ChatEvidence, ...]
