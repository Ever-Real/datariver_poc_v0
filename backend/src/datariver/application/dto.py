from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any
from uuid import UUID

from datariver.application.classification_access import ClassificationAccessSnapshot
from datariver.domain.admin_access import AdminAccessRequest, AdminOperation
from datariver.domain.authz import (
    Action,
    AuthenticationAssurance,
    Classification,
    Decision,
    SubjectAttributes,
)
from datariver.domain.governance import ChangeRequest
from datariver.domain.retention import ArchiveCapability, ImmutableArchiveReceipt

MAX_CATALOG_SCHEMA_FIELDS = 1_000


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
    owner: str | None = None
    domain: str | None = None
    tags: tuple[str, ...] = ()
    glossary_terms: tuple[str, ...] = ()
    created_at: datetime | None = None
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
    schema_fields_total: int | None = None
    schema_fields_truncated: bool = False
    schema_fields_total_exact: bool = True


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
    created_at: datetime | None = None
    description: str | None = None
    schema_fields_total: int | None = None
    schema_fields_truncated: bool = False
    schema_fields_total_exact: bool = True


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
    tags: tuple[str, ...] = ()
    glossary_terms: tuple[str, ...] = ()
    # Column paths are a bounded search projection only. The detailed column
    # metadata remains an authorized, typed DataHub enrichment on asset open.
    column_names: tuple[str, ...] = ()
    created_at: datetime | None = None


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
    total: int = 0
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
    databases: tuple[CatalogFacetBucket, ...] = ()
    schemas: tuple[CatalogFacetBucket, ...] = ()
    domains: tuple[CatalogFacetBucket, ...] = ()
    lifecycles: tuple[CatalogFacetBucket, ...] = ()


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
class CatalogVocabulary:
    items: tuple[str, ...]
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
class CatalogControlledMetadataPreview:
    asset_id: UUID
    target_ref: str
    aspect_name: str
    current_refs: tuple[str, ...]
    proposed_refs: tuple[str, ...]
    before_hash: str
    after_hash: str
    preview_etag: str
    source_version: str
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class ChangeRequestAssigneeRecord:
    subject_id: UUID
    display_name: str
    responsibility: str
    priority: int


@dataclass(frozen=True, slots=True)
class ChangeRequestSchemaOverview:
    platform: str
    database_name: str
    schema_name: str
    system_id: UUID | None
    system_code: str | None
    system_name: str | None
    assignees: tuple[ChangeRequestAssigneeRecord, ...]
    pending_count: int
    total_count: int
    received_count: int
    recheck_count: int
    testing_count: int
    final_review_count: int
    completed_count: int


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
    email: str | None = None
    last_login_at: datetime | None = None
    last_login_ip: str | None = None
    owned_table_count: int = 0
    change_request_count: int = 0
    joined_at: datetime | None = None
    access_expires_at: datetime | None = None
    renewal_eligible_at: datetime | None = None
    access_expired: bool = False
    renewal_request_eligible: bool = False
    pending_renewal_request_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class WorkspaceMembershipPage:
    items: tuple[WorkspaceMembershipSummary, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class MembershipRenewalRecord:
    renewal_request_id: UUID
    workspace_id: UUID
    target_subject_id: UUID
    requester_id: UUID
    requester_display_name: str
    reason: str
    current_expires_at: datetime
    requested_expires_at: datetime
    state: str
    version: int
    created_at: datetime
    checker_id: UUID | None = None
    checker_display_name: str | None = None
    decision_reason: str | None = None
    decided_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class MembershipRenewalPage:
    items: tuple[MembershipRenewalRecord, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class MembershipRoleAssignmentEvidence:
    workspace_id: UUID
    subject_id: UUID
    role_id: UUID
    role_version: int
    membership_version: int
    access_payload_hash: str
    assigned_by: UUID
    assignment_version: int
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class WorkspaceMembershipAccessRecord:
    summary: WorkspaceMembershipSummary
    groups: frozenset[str]
    allowed_actions: frozenset[Action]
    denied_actions: frozenset[Action]
    allowed_system_ids: frozenset[UUID]
    allowed_domain_ids: frozenset[UUID]
    role_assignment: MembershipRoleAssignmentEvidence | None = None


@dataclass(frozen=True, slots=True)
class SystemDirectoryAssignee:
    subject_id: UUID
    display_name: str
    responsibility: str
    priority: int
    active: bool


@dataclass(frozen=True, slots=True)
class SystemDirectoryEntry:
    system_id: UUID
    code: str
    name: str
    description: str
    active: bool
    version: int
    assignees: tuple[SystemDirectoryAssignee, ...] = ()
    assignee_count: int = 0


@dataclass(frozen=True, slots=True)
class SystemDirectoryPage:
    items: tuple[SystemDirectoryEntry, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class SystemAssigneePage:
    items: tuple[SystemDirectoryAssignee, ...]
    system_version: int
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class AdminAccessRequestPage:
    items: tuple[AdminAccessRequest, ...]
    next_cursor: str | None


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
    persistence: str = "PERSISTED"


@dataclass(frozen=True, slots=True)
class RetentionExecutionClaim:
    job_id: UUID
    attempt_id: UUID
    workspace_id: UUID
    erasure_request_id: UUID
    erasure_request_version: int
    erasure_request_payload_hash: str
    command_hash: str
    target_type: str
    target_id: UUID
    target_version: int
    target_snapshot_hash: str
    classification: str
    retention_policy_id: UUID
    retention_policy_hash: str
    policy_number: int
    request_decided_at: datetime
    planned_at: datetime
    archive_retain_until: datetime
    lease_token: str
    lease_epoch: int
    attempt_count: int
    maximum_attempts: int
    worker_principal_fingerprint: str
    archive_configuration_hash: str
    encryption_profile_fingerprint: str
    archive_bucket: str
    archive_prefix: str
    correlation_id: str
    recovery_only: bool = False


@dataclass(frozen=True, slots=True)
class RetentionExecutionAttemptEvidence:
    attempt_no: int
    state: str
    stage: str
    evidence_hash: str
    destructive_effect_count: int
    started_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class RetentionExecutionEventEvidence:
    sequence: int
    event_type: str
    attempt_no: int | None
    evidence_hash: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class RetentionArchiveReceiptEvidenceSummary:
    receipt_id: UUID
    manifest_hash: str
    content_sha256: str
    row_count: int
    byte_count: int
    retention_until: datetime
    legal_hold: bool
    content_verified_at: datetime
    retention_verified_at: datetime
    verified_at: datetime
    payload_hash: str


@dataclass(frozen=True, slots=True)
class RetentionExecutionEvidence:
    job_id: UUID
    erasure_request_id: UUID
    erasure_request_version: int
    erasure_request_payload_hash: str
    target_type: str
    target_id: UUID
    target_version: int
    classification: Classification
    retention_policy_id: UUID
    retention_policy_hash: str
    policy_number: int
    execution_authorization_valid_until: datetime
    archive_disposition: str
    command_hash: str
    archive_retain_until: datetime
    state: str
    next_attempt_at: datetime
    attempt_count: int
    maximum_attempts: int
    archive_manifest_hash: str | None
    destructive_state: str
    separation_of_duties_verified: bool
    version: int
    created_at: datetime
    updated_at: datetime
    attempts: tuple[RetentionExecutionAttemptEvidence, ...]
    attempts_truncated: bool
    events: tuple[RetentionExecutionEventEvidence, ...]
    events_truncated: bool
    receipt: RetentionArchiveReceiptEvidenceSummary | None


@dataclass(frozen=True, slots=True)
class ArchiveCapabilityEvidence:
    encryption_profile_fingerprint: str
    runtime_principal_fingerprint: str
    probe_contract_version: str
    challenge_hash: str
    object_bucket: str
    failure_code: str | None = None


@dataclass(frozen=True, slots=True)
class ArchiveCapabilityRecord:
    attestation_id: UUID
    capability: ArchiveCapability
    evidence: ArchiveCapabilityEvidence


@dataclass(frozen=True, slots=True)
class ArchiveReceiptEvidence:
    source_start: datetime
    source_end: datetime
    retention_policy_id: UUID
    retention_policy_hash: str
    manifest_hash: str
    provider_checksum_algorithm: str
    provider_checksum_encoding: str
    provider_checksum_type: str
    readback_sha256: str
    readback_byte_count: int
    requested_retention_until: datetime
    readback_retention_until: datetime
    written_at: datetime
    content_verified_at: datetime
    retention_verified_at: datetime
    canonicalization_version: str
    media_type: str
    media_type_version: str
    compression: str
    compression_version: str
    worker_principal_fingerprint: str
    correlation_id: str
    encryption_profile_fingerprint: str


@dataclass(frozen=True, slots=True)
class RetentionArchiveVerification:
    capability_attestation_id: UUID
    capability: ArchiveCapability
    capability_evidence: ArchiveCapabilityEvidence
    receipt: ImmutableArchiveReceipt
    evidence: ArchiveReceiptEvidence
