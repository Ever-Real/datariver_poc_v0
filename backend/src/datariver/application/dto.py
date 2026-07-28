from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from types import MappingProxyType
from typing import Any, Literal
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
from datariver.domain.chat import (
    ChatAdapterState,
    ChatRetrievalMode,
    ChatRouteReason,
    ChatWorkflowStage,
    ChatWorkflowStatus,
)
from datariver.domain.governance import ChangeRequest, ChangeState
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
    column_names: tuple[str, ...] = ()
    created_at: datetime | None = None
    matches: tuple[CatalogMatchFragment, ...] = ()
    description_truncated: bool = False
    tags_truncated: bool = False
    glossary_terms_truncated: bool = False
    column_names_truncated: bool = False


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
    ownership_truncated: bool = False
    glossary_terms_truncated: bool = False
    tags_truncated: bool = False
    description_truncated: bool = False


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
    ownership_truncated: bool = False
    glossary_terms_truncated: bool = False
    tags_truncated: bool = False
    description_truncated: bool = False


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
    description_truncated: bool = False
    tags_truncated: bool = False
    glossary_terms_truncated: bool = False
    column_names_truncated: bool = False


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
    next_cursor: str | None
    total: int
    observed_at: datetime
    snapshot_consistent: bool = False
    snapshot_evidence_reference: str | None = None
    snapshot_contract_hash: str | None = None
    snapshot_provider_version: str | None = None


@dataclass(frozen=True, slots=True)
class DataHubVocabularyEntry:
    provider_ref: str
    kind: str
    display_name: str
    source_version: str


@dataclass(frozen=True, slots=True)
class DataHubVocabularyScanPage:
    items: tuple[DataHubVocabularyEntry, ...]
    next_cursor: str | None
    total: int
    observed_at: datetime
    snapshot_consistent: bool = False
    snapshot_evidence_reference: str | None = None
    snapshot_contract_hash: str | None = None
    snapshot_provider_version: str | None = None


@dataclass(frozen=True, slots=True)
class CatalogVocabularySyncResult:
    upserted: int
    inactivated: int
    next_offset: int | None
    total: int
    observed_at: datetime
    inactivation_status: str = "NOT_FINAL"


@dataclass(frozen=True, slots=True)
class CatalogVocabularySyncReservation:
    cursor: str | None
    replayed: CatalogVocabularySyncResult | None = None


@dataclass(frozen=True, slots=True)
class CatalogMetadataVocabularyListItem:
    vocabulary_id: UUID
    kind: str
    display_name: str
    source_version: str


@dataclass(frozen=True, slots=True)
class CatalogMetadataVocabularyPage:
    items: tuple[CatalogMetadataVocabularyListItem, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class CatalogSyncResult:
    upserted: int
    tombstoned: int
    next_offset: int | None
    total: int
    observed_at: datetime
    tombstone_status: str = "NOT_FINAL"


@dataclass(frozen=True, slots=True)
class CatalogSyncReservation:
    cursor: str | None
    replayed: CatalogSyncResult | None = None


@dataclass(frozen=True, slots=True)
class CatalogSyncProgress:
    state: str
    next_offset: int | None
    seen_count: int
    expected_total: int | None
    snapshot_consistent: bool


@dataclass(frozen=True, slots=True)
class CatalogPage:
    items: tuple[CatalogAssetIndex, ...]
    next_cursor: str | None
    observed_at: datetime
    total: int = 0
    total_exact: bool = False
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
    database_name: str | None = None
    schema_name: str | None = None
    matches: tuple[CatalogMatchFragment, ...] = ()


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
    object_locator_hash: str | None = None
    accepted_etag: str | None = None
    accepted_version_id: str | None = None


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
class RegistrationCandidateBindingCommand:
    workspace_id: UUID
    upload_id: UUID
    preparation_id: UUID
    receipt_id: UUID
    receipt_hash: str
    candidate_id: UUID
    candidate_hash: str
    target_asset_id: UUID
    target_source_version: str
    target_binding_hash: str


@dataclass(frozen=True, slots=True)
class CatalogMetadataRowEvidenceRecord:
    row_id: UUID
    ordinal: int
    record_kind: str
    aspect_name: str
    operation: str
    field_path: str | None
    value_text: str | None
    controlled_ref_id: UUID | None
    controlled_kind: str | None
    semantic_target_hash: str
    row_hash: str


@dataclass(frozen=True, slots=True)
class CatalogMetadataCandidateEvidence:
    candidate_id: UUID
    workspace_id: UUID
    receipt_id: UUID
    ordinal: int
    content_profile: str
    evidence_version: str
    record_kind: str
    candidate_kind: str
    target_asset_id: UUID
    aspect_name: str
    submitted_platform: str
    submitted_database_name: str
    submitted_schema_name: str
    submitted_table_name: str
    submitted_identity_hash: str
    row_root_hash: str
    candidate_hash: str
    rows: tuple[CatalogMetadataRowEvidenceRecord, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CatalogMetadataCandidateView:
    evidence: CatalogMetadataCandidateEvidence
    current_target: CatalogAssetIndex


@dataclass(frozen=True, slots=True)
class CatalogMetadataCandidatePage:
    items: tuple[CatalogMetadataCandidateView, ...]
    next_cursor: str | None
    receipt: UploadPreparationReceiptEvidence
    projection_version: int
    policy_version: str
    classification_policy_version: int | None
    authorization_generation: int | None


@dataclass(frozen=True, slots=True)
class CatalogMetadataBindingCommand:
    workspace_id: UUID
    upload_id: UUID
    preparation_id: UUID
    receipt_id: UUID
    receipt_hash: str
    content_profile: str
    candidate_id: UUID
    candidate_kind: str
    candidate_hash: str
    aspect_name: str
    before_hash: str
    after_hash: str
    item_contract_hash: str
    target_asset_id: UUID
    target_source_version: str
    target_binding_hash: str


@dataclass(frozen=True, slots=True)
class TypedCatalogMetadataPreview:
    candidate_id: UUID
    target_asset_id: UUID
    target_ref: str
    platform: str
    database_name: str
    schema_name: str
    table_name: str
    classification: Classification
    record_kind: str
    candidate_kind: str
    aspect_name: str
    operation_count: int
    description_change_count: int
    description_change_sample: tuple[tuple[str | None, str | None, str | None], ...]
    description_changes_truncated: bool
    current_reference_count: int
    proposed_reference_count: int
    before_hash: str
    after_hash: str
    source_version: str
    observed_at: datetime
    preview_etag: str
    binding: CatalogMetadataBindingCommand
    proposed_document: Mapping[str, Any] = field(repr=False)


@dataclass(frozen=True, slots=True)
class TypedBulkCandidatePreview:
    candidate_id: UUID
    target_asset_id: UUID
    target_ref: str
    platform: str
    database_name: str
    schema_name: str
    table_name: str
    classification: Classification
    current_description: str | None
    proposed_description: str
    before_hash: str
    after_hash: str
    source_version: str
    observed_at: datetime
    preview_etag: str
    binding: RegistrationCandidateBindingCommand
    proposed_document: Mapping[str, Any] = field(repr=False)


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
class ChangeRequestSummaryTarget:
    item_id: UUID
    target_type: str
    target_ref: str
    aspect_name: str
    operation: str
    target_asset_id: UUID | None
    target_asset_type: str | None
    target_system_id: UUID | None
    target_domain_id: UUID | None
    target_owner_department_id: UUID | None
    target_classification: Classification | None
    target_lifecycle: str | None
    target_source_version: str | None
    target_observed_at: datetime | None
    target_binding_hash: str | None
    routing_system_id: UUID | None


@dataclass(frozen=True, slots=True)
class ChangeRequestSummaryRecord:
    change_request_id: UUID
    number: str
    request_type: str
    title: str
    state: ChangeState
    requester_id: UUID
    requester_department_id: UUID | None
    current_round_number: int
    created_at: datetime
    requested_due_date: date | None
    priority: str | None
    urgency: str | None
    classification: Classification
    version: int
    targets: tuple[ChangeRequestSummaryTarget, ...]


@dataclass(frozen=True, slots=True)
class ChangeRequestSummaryPage:
    items: tuple[ChangeRequestSummaryRecord, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class GovernanceApplyClaim:
    change_request: ChangeRequest
    job_id: UUID
    attempt_id: UUID
    attempt_no: int
    lease_token: str
    worker_subject_id: UUID


@dataclass(frozen=True, slots=True)
class GovernanceApplyAuthorizationContext:
    """Server-derived identity and target scope for apply-time human reauthorization."""

    workspace_id: UUID
    change_request_id: UUID
    change_request_version: int
    request_type: str
    requester_id: UUID
    request_classification: Classification
    item_id: UUID
    action: Action
    target_type: str
    target_ref: str
    operation: str
    aspect_name: str
    before_hash: str
    after_hash: str
    target_asset_id: UUID
    target_asset_type: str
    target_system_id: UUID | None
    target_domain_id: UUID | None
    target_owner_department_id: UUID | None
    target_classification: Classification
    target_lifecycle: str
    target_source_version: str
    target_binding_hash: str
    job_id: UUID
    attempt_id: UUID
    attempt_no: int
    worker_subject_id: UUID
    lease_token_hash: str


@dataclass(frozen=True, slots=True)
class GovernanceApplyAttemptEvidence:
    attempt_id: UUID
    attempt_no: int
    state: str
    failure_code: str | None
    external_response_hash: str | None
    started_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class GovernanceApplyItemEvidence:
    item_id: UUID
    expected_hash: str
    observed_hash: str | None
    source_version: str | None
    provider_version: str | None


@dataclass(frozen=True, slots=True)
class GovernanceApplyReport:
    change_request_id: UUID
    job_id: UUID | None
    state: str
    attempt_count: int
    last_error_code: str | None
    expected_hash: str | None
    observed_hash: str | None
    reconciled: bool
    created_at: datetime | None
    updated_at: datetime | None
    items: tuple[GovernanceApplyItemEvidence, ...]
    attempts: tuple[GovernanceApplyAttemptEvidence, ...]


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
class MembershipChangeRequestActivity:
    change_request_id: UUID
    number: str
    title: str
    request_type: str
    state: str
    relationship: Literal["REQUESTER", "APPROVER", "REQUESTER_AND_APPROVER"]
    classification: Classification
    requester_id: UUID
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MembershipChangeRequestActivityPage:
    items: tuple[MembershipChangeRequestActivity, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class MembershipOwnedTable:
    asset_id: UUID
    name: str
    platform: str | None
    database_name: str | None
    schema_name: str | None
    classification: Classification
    system_id: UUID | None
    domain_id: UUID | None
    owner_department_id: UUID | None
    source_version: str
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class MembershipOwnedTablePage:
    items: tuple[MembershipOwnedTable, ...]
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
class KnowledgeStudioDomainOption:
    domain_id: UUID
    display_name: str
    source_version: str


@dataclass(frozen=True, slots=True)
class KnowledgeStudioDraftRecord:
    draft_id: UUID
    workspace_id: UUID
    author_id: UUID
    kind: str
    state: str
    current_step: str
    name: str
    endpoint_alias: str
    domain_id: UUID
    domain_source_version: str
    classification: Classification
    base_graph_id: UUID | None
    base_ontology_version_id: UUID | None
    base_release_id: UUID | None
    last_autosaved_at: datetime
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class KnowledgeStudioTBoxElementRecord:
    stable_element_id: str
    kind: str
    canonical_name: str
    display_name: str
    parent_stable_element_id: str | None
    source_stable_element_id: str | None
    target_stable_element_id: str | None
    data_type: str | None
    nullable: bool | None
    ordinal: int
    version: int


@dataclass(frozen=True, slots=True)
class KnowledgeStudioMappingRuleRecord:
    rule_id: UUID
    ordinal: int
    method: str
    source_field_path: str
    target_stable_element_id: str
    transform_id: str
    transform_version: str
    source_unit: str | None
    canonical_unit: str | None


@dataclass(frozen=True, slots=True)
class KnowledgeStudioBindingRecord:
    binding_id: UUID
    target_stable_element_id: str
    source_reference_id: UUID
    source_asset_id: UUID
    source_name: str
    source_version: str
    projection_source_version: str
    source_classification: Classification
    readiness: str
    tbox_version: int
    version: int
    rules: tuple[KnowledgeStudioMappingRuleRecord, ...]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class KnowledgeStudioABoxRecord:
    draft: KnowledgeStudioDraftRecord
    tbox_elements: tuple[KnowledgeStudioTBoxElementRecord, ...]
    bindings: tuple[KnowledgeStudioBindingRecord, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeStudioSourceDataset:
    asset_id: UUID
    name: str
    asset_type: str
    platform: str | None
    database_name: str | None
    schema_name: str | None
    classification: Classification
    source_version: str
    projection_source_version: str
    field_paths: tuple[str, ...]
    fields_truncated: bool


@dataclass(frozen=True, slots=True)
class KnowledgeStudioSourcePage:
    items: tuple[KnowledgeStudioSourceDataset, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class KnowledgeStudioSourceDetail:
    dataset: KnowledgeStudioSourceDataset
    observed_at: datetime
    stale_at: datetime | None


@dataclass(frozen=True, slots=True)
class KnowledgeStudioSourceAccess:
    asset_id: UUID
    classification: Classification
    projection_source_version: str


KnowledgeStudioSampleScalar = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class KnowledgeStudioSampleRequest:
    source_reference_id: UUID
    asset_id: UUID
    source_version: str
    projection_source_version: str
    field_paths: tuple[str, ...]
    limit: int


@dataclass(frozen=True, slots=True)
class KnowledgeStudioSamplePage:
    source_reference_id: UUID
    source_version: str
    projection_source_version: str
    rows: tuple[Mapping[str, KnowledgeStudioSampleScalar], ...]
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class KnowledgeStudioSourceProbe:
    source_reference_id: UUID
    source_version: str
    projection_source_version: str
    accessible: bool
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class KnowledgeStudioValidationEvidence:
    severity: str
    code: str
    location: str
    message: str


@dataclass(frozen=True, slots=True)
class KnowledgeStudioPreviewNode:
    node_id: str
    stable_element_id: str
    type_name: str
    identity: KnowledgeStudioSampleScalar
    properties: Mapping[str, KnowledgeStudioSampleScalar]


@dataclass(frozen=True, slots=True)
class KnowledgeStudioPreviewEdge:
    edge_id: str
    stable_element_id: str
    type_name: str
    source_node_id: str
    target_node_id: str
    properties: Mapping[str, KnowledgeStudioSampleScalar]


@dataclass(frozen=True, slots=True)
class KnowledgeStudioPreviewGraph:
    nodes: tuple[KnowledgeStudioPreviewNode, ...]
    edges: tuple[KnowledgeStudioPreviewEdge, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeStudioPreviewRecord:
    status: str
    draft_version: int
    binding_version: int | None
    target_stable_element_id: str
    dry_run: bool
    sample_size: int
    graph: KnowledgeStudioPreviewGraph
    evidence: tuple[KnowledgeStudioValidationEvidence, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeStudioPreflightRecord:
    status: str
    valid: bool
    draft_version: int
    checked_at: datetime
    evidence: tuple[KnowledgeStudioValidationEvidence, ...]


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
    contract_version: str
    consumer_subject_id: UUID | None
    consumer_issuer: str | None
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
class InvocationResultRecord:
    authorization: InvocationAuthorizationRecord
    result_document: dict[str, Any]
    replayed: bool


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
class ChatRouteDecision:
    requested_mode: ChatRetrievalMode
    selected_mode: ChatRetrievalMode
    reason: ChatRouteReason
    adapter_state: ChatAdapterState


@dataclass(frozen=True, slots=True)
class ChatWorkflowEvent:
    stage: ChatWorkflowStage
    status: ChatWorkflowStatus
    detail_code: str


@dataclass(frozen=True, slots=True)
class ChatEvidenceRanking:
    chunk_id: UUID
    rank: int
    retrieval_method: str


@dataclass(frozen=True, slots=True)
class ChatVectorSearchResult:
    items: tuple[CatalogAssetIndex, ...]
    provider_invoked: bool


@dataclass(frozen=True, slots=True)
class ChatCompositionAudit:
    provider: str
    model: str
    prompt_template_version: str
    external_service_used: bool
    provider_profile_version_id: UUID | None = None
    classification_policy_id: UUID | None = None
    classification_policy_hash: str | None = None
    classification_policy_version: int | None = None
    authorization_generation: int | None = None
    external_stages: tuple[str, ...] = ()
    external_stage_provider_profile_version_ids: tuple[tuple[str, UUID], ...] = ()


def default_chat_route() -> ChatRouteDecision:
    return ChatRouteDecision(
        requested_mode=ChatRetrievalMode.GENERAL,
        selected_mode=ChatRetrievalMode.GENERAL,
        reason=ChatRouteReason.GENERAL_DEFAULT,
        adapter_state=ChatAdapterState.READY,
    )


@dataclass(frozen=True, slots=True)
class ChatExchange:
    session_id: UUID
    request_message_id: UUID
    response_message_id: UUID
    answer: str
    evidence: tuple[ChatEvidence, ...]
    persistence: str = "PERSISTED"
    route: ChatRouteDecision = field(default_factory=default_chat_route)
    workflow: tuple[ChatWorkflowEvent, ...] = ()
    evidence_ranking: tuple[ChatEvidenceRanking, ...] = ()


@dataclass(frozen=True, slots=True)
class ChatSessionRecord:
    id: UUID
    title: str
    is_favorite: bool
    version: int
    created_at: datetime
    updated_at: datetime
    message_count: int


@dataclass(frozen=True, slots=True)
class ChatMessageRecord:
    id: UUID
    session_id: UUID
    role: Literal["user", "assistant"]
    content: str
    evidence: tuple[ChatEvidence, ...]
    created_at: datetime
    route: ChatRouteDecision | None = None
    workflow: tuple[ChatWorkflowEvent, ...] = ()


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


@dataclass(frozen=True, slots=True)
class ManualMetadataAspectReportEvidence:
    aspect_name: str
    aspect_ordinal: int
    outcome: str
    before_hash: str | None
    expected_hash: str | None
    observed_hash: str | None
    write_attempted: bool
    failure_code: str | None
    provider_version: str | None
    provider_response_hash: str | None
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class ManualMetadataApplyAttemptEvidence:
    attempt_id: UUID
    attempt_no: int
    lease_epoch: int
    state: str
    failure_code: str | None
    report_root_hash: str | None
    started_at: datetime
    finished_at: datetime | None
    aspects: tuple[ManualMetadataAspectReportEvidence, ...]
