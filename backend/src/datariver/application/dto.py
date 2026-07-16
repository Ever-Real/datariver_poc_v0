from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from datariver.domain.admin_access import AdminOperation
from datariver.domain.authz import Action, AuthenticationAssurance, Classification, Decision
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
class ChatExchange:
    session_id: UUID
    request_message_id: UUID
    response_message_id: UUID
    answer: str
    evidence: tuple[ChatEvidence, ...]
