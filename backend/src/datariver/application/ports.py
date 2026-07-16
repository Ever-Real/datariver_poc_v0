from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from types import TracebackType
from typing import Any, Protocol, Self, runtime_checkable
from uuid import UUID

from datariver.application.assistant_inference import (
    AuthorizedInferencePackage,
    ProviderInferenceDraft,
)
from datariver.application.classification_access import ClassificationAccessSnapshot
from datariver.application.dto import (
    ApiProductRecord,
    ApiProductVersionRecord,
    CapabilityStatus,
    CatalogAssetDetail,
    CatalogAssetIndex,
    CatalogFacets,
    CatalogPage,
    CatalogSuggestions,
    CatalogTreePage,
    ChatDraft,
    ChatEvidence,
    ChatExchange,
    ConsumerGrantRecord,
    DataHubApplyReceipt,
    DataHubAspectSnapshot,
    DataHubAssetEnrichment,
    DataHubLineagePage,
    DataHubScanAsset,
    DataHubScanPage,
    DecisionAuditItem,
    GovernanceApplyClaim,
    IdempotencyRecord,
    InvocationAuthorizationRecord,
    KnowledgeChangeSetRecord,
    KnowledgeEvidenceCandidate,
    KnowledgeGraphRecord,
    KnowledgeReleaseRecord,
    MultipartUpload,
    ObjectMetadata,
    WorkspaceMembershipAccessRecord,
    WorkspaceMembershipSummary,
)
from datariver.domain.admin_access import AdminAccessRequest, MembershipAccessUpdate
from datariver.domain.authz import Decision, SubjectAttributes
from datariver.domain.common import DomainEvent
from datariver.domain.governance import ChangeRequest
from datariver.domain.knowledge import ChangeSetState, GraphChangeOperation, GraphSnapshot
from datariver.domain.registration import CompletedUploadPart, UploadManifest
from datariver.domain.retention import (
    ArchiveCapability,
    ArchiveRetentionObservation,
    ArchiveWriteReceipt,
    ErasureRequest,
    ErasureTargetSnapshot,
    ErasureTargetType,
    LegalHold,
    RetentionPolicyVersion,
)


class DecisionWriter(Protocol):
    async def append_decision(
        self,
        *,
        decision: Decision,
        subject_id: UUID,
        workspace_id: UUID,
        resource_id: UUID,
        action: str,
        request_id: str,
    ) -> None: ...


@runtime_checkable
class DecisionSetWriter(Protocol):
    async def append_decision_set(
        self,
        *,
        decision_id: UUID,
        items: Sequence[DecisionAuditItem],
        subject_id: UUID,
        workspace_id: UUID,
        parent_resource_id: UUID,
        action: str,
        request_id: str,
    ) -> None: ...


class SubjectReader(Protocol):
    async def get_subject(
        self, *, issuer: str, external_subject: str, workspace_id: UUID
    ) -> SubjectAttributes: ...


class CatalogIndexReader(Protocol):
    async def search(
        self,
        *,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        query: str,
        filters: dict[str, Any],
        cursor: str | None,
        limit: int,
    ) -> CatalogPage: ...

    async def get_authorized_asset(
        self,
        *,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        asset_id: UUID,
    ) -> CatalogAssetDetail | None: ...

    async def get_authorized_assets_by_external_urns(
        self,
        *,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        external_urns: Sequence[str],
    ) -> Sequence[CatalogAssetIndex]: ...


class CatalogDiscoveryReader(Protocol):
    async def facets(
        self,
        *,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        query: str,
        filters: dict[str, Any],
        limit: int,
    ) -> CatalogFacets: ...

    async def suggestions(
        self,
        *,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        query: str,
        limit: int,
    ) -> CatalogSuggestions: ...

    async def tree_nodes(
        self,
        *,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        query: str,
        parent_kind: str,
        platform: str | None,
        database_name: str | None,
        schema_name: str | None,
        cursor: str | None,
        limit: int,
    ) -> CatalogTreePage: ...


class CatalogWatermarkReader(Protocol):
    async def get_search_watermark(self, *, workspace_id: UUID) -> int: ...


class CatalogTelemetry(Protocol):
    def catalog_cache_access(self, *, cache: str, outcome: str) -> None: ...

    def catalog_detail_source(self, *, source: str) -> None: ...


class DataHubGateway(Protocol):
    async def get_asset(self, external_urn: str) -> DataHubAssetEnrichment: ...

    async def get_lineage(
        self, *, external_urn: str, direction: str, depth: int
    ) -> DataHubLineagePage: ...

    async def apply_change(
        self, *, external_urn: str, aspect_name: str, document: dict[str, Any], idempotency_key: str
    ) -> DataHubApplyReceipt: ...

    async def read_aspect(
        self, *, external_urn: str, aspect_name: str
    ) -> DataHubAspectSnapshot: ...

    async def capability(self) -> CapabilityStatus: ...

    async def scan_assets(self, *, offset: int, limit: int) -> DataHubScanPage: ...


class CatalogProjectionWriter(Protocol):
    async def upsert_scan(
        self,
        *,
        workspace_id: UUID,
        sync_id: UUID,
        offset: int,
        next_offset: int | None,
        items: Sequence[DataHubScanAsset],
        observed_at: datetime,
        idempotency_key: str,
        request_hash: str,
        operation: str,
    ) -> tuple[int, int]: ...


class Cache(Protocol):
    async def get_json(self, key: str) -> dict[str, Any] | list[Any] | None: ...

    async def set_json(
        self, key: str, value: dict[str, Any] | list[Any], *, ttl_seconds: int
    ) -> None: ...

    async def delete(self, *keys: str) -> int: ...


class ChangeRequestRepository(Protocol):
    async def add(self, change_request: ChangeRequest) -> None: ...

    async def get_for_update(
        self, *, workspace_id: UUID, change_request_id: UUID
    ) -> ChangeRequest | None: ...

    async def get(self, *, workspace_id: UUID, change_request_id: UUID) -> ChangeRequest | None: ...

    async def list(
        self,
        *,
        workspace_id: UUID,
        maximum_classification: int,
        state: str | None,
        limit: int,
    ) -> Sequence[ChangeRequest]: ...

    async def save(self, change_request: ChangeRequest) -> None: ...


class OutboxWriter(Protocol):
    async def add_events(self, events: Sequence[DomainEvent]) -> None: ...


class GovernanceUnitOfWork(Protocol):
    change_requests: ChangeRequestRepository
    outbox: OutboxWriter
    idempotency: IdempotencyStore

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None: ...


class RetentionPolicyRepository(Protocol):
    async def add(self, policy: RetentionPolicyVersion) -> None: ...

    async def get(
        self, *, workspace_id: UUID, policy_id: UUID
    ) -> RetentionPolicyVersion | None: ...

    async def get_for_update(
        self, *, workspace_id: UUID, policy_id: UUID
    ) -> RetentionPolicyVersion | None: ...

    async def get_active(self, *, workspace_id: UUID) -> RetentionPolicyVersion | None: ...

    async def get_active_for_update(
        self, *, workspace_id: UUID, excluding_policy_id: UUID | None = None
    ) -> RetentionPolicyVersion | None: ...

    async def list(
        self, *, workspace_id: UUID, state: str | None, limit: int
    ) -> Sequence[RetentionPolicyVersion]: ...

    async def next_policy_number(self, *, workspace_id: UUID) -> int: ...

    async def save(self, policy: RetentionPolicyVersion) -> None: ...


class LegalHoldRepository(Protocol):
    async def add(self, hold: LegalHold) -> None: ...

    async def get(self, *, workspace_id: UUID, hold_id: UUID) -> LegalHold | None: ...

    async def get_for_update(self, *, workspace_id: UUID, hold_id: UUID) -> LegalHold | None: ...

    async def list(
        self, *, workspace_id: UUID, state: str | None, limit: int
    ) -> Sequence[LegalHold]: ...

    async def save(self, hold: LegalHold) -> None: ...

    async def has_active_for_erasure_target(
        self,
        *,
        workspace_id: UUID,
        target_type: ErasureTargetType,
        target_id: UUID,
        target_owner_id: UUID | None,
    ) -> bool: ...


class ErasureRequestRepository(Protocol):
    async def add(self, request: ErasureRequest) -> None: ...

    async def get(
        self, *, workspace_id: UUID, erasure_request_id: UUID
    ) -> ErasureRequest | None: ...

    async def get_for_update(
        self, *, workspace_id: UUID, erasure_request_id: UUID
    ) -> ErasureRequest | None: ...

    async def list(
        self, *, workspace_id: UUID, state: str | None, limit: int
    ) -> Sequence[ErasureRequest]: ...

    async def save(self, request: ErasureRequest) -> None: ...


class ErasureTargetReader(Protocol):
    async def get_erasure_target_snapshot(
        self,
        *,
        workspace_id: UUID,
        target_type: ErasureTargetType,
        target_id: UUID,
    ) -> ErasureTargetSnapshot | None: ...


class RetentionUnitOfWork(Protocol):
    policies: RetentionPolicyRepository
    legal_holds: LegalHoldRepository
    erasure_requests: ErasureRequestRepository
    erasure_targets: ErasureTargetReader
    outbox: OutboxWriter
    idempotency: IdempotencyStore

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def lock_workspace(self, *, workspace_id: UUID) -> None: ...

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None: ...


class AdminAccessRequestRepository(Protocol):
    async def add(self, request: AdminAccessRequest) -> None: ...

    async def get_for_update(
        self, *, workspace_id: UUID, access_request_id: UUID
    ) -> AdminAccessRequest | None: ...

    async def get(
        self, *, workspace_id: UUID, access_request_id: UUID
    ) -> AdminAccessRequest | None: ...

    async def list(
        self, *, workspace_id: UUID, state: str | None, limit: int
    ) -> Sequence[AdminAccessRequest]: ...

    async def save(self, request: AdminAccessRequest) -> None: ...


class MembershipAccessRepository(Protocol):
    async def list(
        self, *, workspace_id: UUID, limit: int
    ) -> Sequence[WorkspaceMembershipSummary]: ...

    async def get_access(
        self, *, workspace_id: UUID, subject_id: UUID
    ) -> WorkspaceMembershipAccessRecord | None: ...

    async def apply(self, command: MembershipAccessUpdate) -> int: ...

    async def assert_current_version(self, command: MembershipAccessUpdate) -> None: ...

    async def assert_eligible_human_administrators(
        self, *, workspace_id: UUID, subject_ids: frozenset[UUID]
    ) -> None: ...


class AdminAccessUnitOfWork(Protocol):
    requests: AdminAccessRequestRepository
    memberships: MembershipAccessRepository
    outbox: OutboxWriter
    idempotency: IdempotencyStore

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def lock_workspace_access(self, *, workspace_id: UUID) -> None: ...

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None: ...


class GovernanceApplyStore(Protocol):
    async def claim_next(
        self,
        *,
        worker_id: str,
        system_actor_id: UUID,
        lease_seconds: int,
        maximum_attempts: int,
    ) -> GovernanceApplyClaim | None: ...

    async def mark_applied(
        self,
        *,
        claim: GovernanceApplyClaim,
        system_actor_id: UUID,
        expected_hash: str,
        observed_hash: str,
        item_results: Sequence[dict[str, Any]],
    ) -> None: ...

    async def mark_failed(
        self,
        *,
        claim: GovernanceApplyClaim,
        system_actor_id: UUID,
        error_code: str,
        retryable: bool,
        maximum_attempts: int,
    ) -> None: ...


class JobDelivery(Protocol):
    async def publish_job_id(self, *, event_id: UUID, job_id: UUID) -> None: ...


class IdempotencyStore(Protocol):
    async def get_result(
        self, *, workspace_id: UUID, key: str, operation: str
    ) -> IdempotencyRecord | None: ...

    async def save_result(
        self,
        *,
        workspace_id: UUID,
        key: str,
        operation: str,
        request_hash: str,
        result: dict[str, Any],
    ) -> None: ...


class ObjectStore(Protocol):
    async def create_multipart_upload(
        self,
        *,
        bucket: str,
        object_key: str,
        content_type: str,
        metadata: dict[str, str],
    ) -> MultipartUpload: ...

    async def presign_upload_part(
        self,
        *,
        upload: MultipartUpload,
        part_number: int,
        expires_seconds: int,
        checksum_sha256: str | None = None,
    ) -> str: ...

    async def complete_multipart_upload(
        self, *, upload: MultipartUpload, parts: Sequence[CompletedUploadPart]
    ) -> ObjectMetadata: ...

    async def abort_multipart_upload(self, *, upload: MultipartUpload) -> None: ...

    async def head_object(self, *, bucket: str, object_key: str) -> ObjectMetadata: ...

    async def presign_download(
        self,
        *,
        bucket: str,
        object_key: str,
        download_name: str,
        expires_seconds: int,
    ) -> str: ...

    def iter_object_chunks(
        self, *, bucket: str, object_key: str, chunk_size: int = 1024 * 1024
    ) -> AsyncIterator[bytes]: ...

    async def copy_object(
        self,
        *,
        source_bucket: str,
        source_key: str,
        destination_bucket: str,
        destination_key: str,
    ) -> ObjectMetadata: ...

    async def delete_object(self, *, bucket: str, object_key: str) -> None: ...


class ImmutableArchiveStore(Protocol):
    """Dedicated WORM boundary. Deliberately exposes no delete or retention-bypass operation."""

    async def verify_capability(self) -> ArchiveCapability: ...

    async def write_archive(
        self,
        *,
        object_key: str,
        chunks: AsyncIterator[bytes],
        size_bytes: int,
        sha256: str,
        retain_until: datetime,
        metadata: dict[str, str],
    ) -> ArchiveWriteReceipt: ...

    def iter_archive_chunks(
        self, *, object_key: str, version_id: str, chunk_size: int = 1024 * 1024
    ) -> AsyncIterator[bytes]: ...

    async def read_retention(
        self, *, object_key: str, version_id: str
    ) -> ArchiveRetentionObservation: ...


class UploadRepository(Protocol):
    async def add(self, manifest: UploadManifest) -> None: ...

    async def get_for_update(
        self, *, workspace_id: UUID, upload_id: UUID
    ) -> UploadManifest | None: ...

    async def save(self, manifest: UploadManifest) -> None: ...

    async def list(
        self,
        *,
        workspace_id: UUID,
        owner_id: UUID | None,
        maximum_classification: int,
        state: str | None,
        limit: int,
    ) -> Sequence[UploadManifest]: ...


class UploadUnitOfWork(Protocol):
    uploads: UploadRepository
    outbox: OutboxWriter
    idempotency: IdempotencyStore

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None: ...


class UploadCompletionStore(Protocol):
    async def claim_next(
        self, *, lease_seconds: int, maximum_attempts: int
    ) -> UploadManifest | None: ...

    async def mark_quarantined(
        self, *, manifest: UploadManifest, metadata: ObjectMetadata
    ) -> None: ...

    async def mark_failed(
        self,
        *,
        manifest: UploadManifest,
        error_code: str,
        retryable: bool,
        maximum_attempts: int,
    ) -> None: ...


class UploadValidationStore(Protocol):
    async def claim_next(
        self, *, lease_seconds: int, maximum_attempts: int
    ) -> UploadManifest | None: ...

    async def mark_accepted(
        self,
        *,
        manifest: UploadManifest,
        accepted_bucket: str,
        accepted_object_key: str,
        validation_summary: dict[str, object],
    ) -> None: ...

    async def mark_failed(
        self,
        *,
        manifest: UploadManifest,
        error_code: str,
        retryable: bool,
        maximum_attempts: int,
    ) -> None: ...


class KnowledgeStore(Protocol):
    async def create_graph(
        self,
        *,
        workspace_id: UUID,
        slug: str,
        name: str,
        graph_type: str,
        classification: int,
        entity_types: frozenset[str],
        edge_types: frozenset[str],
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeGraphRecord: ...

    async def list_graphs(
        self, *, workspace_id: UUID, clearance: int
    ) -> tuple[KnowledgeGraphRecord, ...]: ...

    async def get_graph(
        self, *, workspace_id: UUID, graph_id: UUID, clearance: int
    ) -> KnowledgeGraphRecord | None: ...

    async def create_changeset(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        title: str,
        author_id: UUID,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeChangeSetRecord: ...

    async def list_changesets(
        self, *, workspace_id: UUID, graph_id: UUID
    ) -> tuple[KnowledgeChangeSetRecord, ...]: ...

    async def get_changeset(
        self, *, workspace_id: UUID, graph_id: UUID, changeset_id: UUID
    ) -> KnowledgeChangeSetRecord | None: ...

    async def append_change_operation(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        changeset_id: UUID,
        actor_id: UUID,
        expected_version: int,
        operation: GraphChangeOperation,
    ) -> KnowledgeChangeSetRecord: ...

    async def submit_changeset(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        changeset_id: UUID,
        actor_id: UUID,
        expected_version: int,
    ) -> KnowledgeChangeSetRecord: ...

    async def review_changeset(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        changeset_id: UUID,
        actor_id: UUID,
        decision: ChangeSetState,
        reason: str,
        expected_version: int,
    ) -> KnowledgeChangeSetRecord: ...

    async def prepare_changeset_publication(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        changeset_id: UUID,
    ) -> tuple[KnowledgeChangeSetRecord, GraphSnapshot, str | None]: ...

    async def mark_changeset_published(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        changeset_id: UUID,
        release_id: UUID,
        expected_version: int,
    ) -> KnowledgeChangeSetRecord: ...

    async def list_releases(
        self, *, workspace_id: UUID, graph_id: UUID
    ) -> tuple[KnowledgeReleaseRecord, ...]: ...

    async def activate_release(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        release_id: UUID,
        expected_graph_version: int,
    ) -> KnowledgeGraphRecord: ...

    async def publish_release(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        snapshot: GraphSnapshot,
        expected_base_hash: str | None,
        published_by: UUID,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeReleaseRecord: ...

    async def get_release_snapshot(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        release_id: UUID,
        clearance: int,
        maximum_nodes: int,
    ) -> tuple[KnowledgeReleaseRecord, GraphSnapshot] | None: ...


class ChatStore(Protocol):
    async def save_exchange(
        self,
        *,
        workspace_id: UUID,
        owner_id: UUID,
        session_id: UUID | None,
        question: str,
        answer: str,
        evidence: Sequence[ChatEvidence],
        policy_decision_id: UUID,
    ) -> ChatExchange: ...


class ChatAnswerComposer(Protocol):
    async def compose(
        self,
        *,
        question: str,
        evidence: Sequence[ChatEvidence],
    ) -> ChatDraft: ...


class AssistantInferenceAdapter(Protocol):
    async def infer(
        self,
        *,
        package: AuthorizedInferencePackage,
    ) -> ProviderInferenceDraft: ...


class KnowledgeEvidenceReader(Protocol):
    async def search_active_nodes(
        self,
        *,
        workspace_id: UUID,
        query: str,
        maximum_classification: int,
        limit: int,
    ) -> Sequence[KnowledgeEvidenceCandidate]: ...


class SharingStore(Protocol):
    async def create_product(
        self,
        *,
        workspace_id: UUID,
        slug: str,
        name: str,
        description: str,
        graph_id: UUID,
        release_id: UUID,
        classification: int,
        owner_id: UUID,
        surface: str,
        contract_document: dict[str, Any],
        maximum_hops: int,
        maximum_nodes: int,
        timeout_ms: int,
        idempotency_key: str,
        request_hash: str,
    ) -> ApiProductRecord: ...

    async def list_products(
        self, *, workspace_id: UUID, clearance: int
    ) -> tuple[ApiProductRecord, ...]: ...

    async def get_product(
        self, *, workspace_id: UUID, product_id: UUID, clearance: int
    ) -> ApiProductRecord | None: ...

    async def create_version(
        self,
        *,
        workspace_id: UUID,
        product_id: UUID,
        release_id: UUID,
        actor_id: UUID,
        surface: str,
        contract_document: dict[str, Any],
        maximum_hops: int,
        maximum_nodes: int,
        timeout_ms: int,
        idempotency_key: str,
        request_hash: str,
    ) -> ApiProductVersionRecord: ...

    async def publish_version(
        self,
        *,
        workspace_id: UUID,
        product_id: UUID,
        version_id: UUID,
        actor_id: UUID,
        expected_version: int,
    ) -> ApiProductRecord: ...

    async def create_grant(
        self,
        *,
        workspace_id: UUID,
        product_id: UUID,
        consumer_client_id: str,
        scopes: frozenset[str],
        maximum_classification: int,
        requests_per_minute: int,
        monthly_quota: int,
        valid_from: datetime,
        expires_at: datetime,
        actor_id: UUID,
        idempotency_key: str,
        request_hash: str,
    ) -> ConsumerGrantRecord: ...

    async def list_grants(
        self, *, workspace_id: UUID, product_id: UUID
    ) -> tuple[ConsumerGrantRecord, ...]: ...

    async def revoke_grant(
        self,
        *,
        workspace_id: UUID,
        product_id: UUID,
        grant_id: UUID,
        actor_id: UUID,
        expected_version: int,
    ) -> ConsumerGrantRecord: ...

    async def authorize_invocation(
        self,
        *,
        workspace_id: UUID,
        product_id: UUID,
        consumer_client_id: str,
        requested_scope: str,
        invocation_key: str,
        request_id: str,
    ) -> InvocationAuthorizationRecord: ...
