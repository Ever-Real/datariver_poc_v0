from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Any, Protocol, Self, runtime_checkable
from uuid import UUID

from datariver.application.assistant_inference import (
    AuthorizedInferencePackage,
    InferenceGroundingAssessment,
    ProviderInferenceDraft,
)
from datariver.application.classification_access import ClassificationAccessSnapshot
from datariver.application.dto import (
    AdminAccessRequestPage,
    ApiProductRecord,
    ApiProductVersionRecord,
    ArchiveCapabilityEvidence,
    ArchiveCapabilityRecord,
    CapabilityStatus,
    CatalogAssetDetail,
    CatalogAssetIndex,
    CatalogExportArtifact,
    CatalogExportClaim,
    CatalogExportRecord,
    CatalogExportRequest,
    CatalogFacets,
    CatalogMetadataBindingCommand,
    CatalogMetadataCandidateEvidence,
    CatalogMetadataVocabularyPage,
    CatalogPage,
    CatalogSuggestions,
    CatalogSyncProgress,
    CatalogSyncReservation,
    CatalogSyncResult,
    CatalogTreePage,
    CatalogVocabulary,
    CatalogVocabularySyncReservation,
    CatalogVocabularySyncResult,
    ChangeRequestSchemaOverview,
    ChangeRequestSummaryRecord,
    ChatCompositionAudit,
    ChatDraft,
    ChatEvidence,
    ChatEvidenceRanking,
    ChatExchange,
    ChatMessageRecord,
    ChatRetentionBinding,
    ChatRouteDecision,
    ChatSessionRecord,
    ChatVectorSearchResult,
    ChatWorkflowEvent,
    ConsumerGrantRecord,
    DataHubApplyReceipt,
    DataHubAspectSnapshot,
    DataHubAssetEnrichment,
    DataHubLineagePage,
    DataHubScanAsset,
    DataHubScanPage,
    DataHubVocabularyScanPage,
    DecisionAuditItem,
    GovernanceApplyAuthorizationContext,
    GovernanceApplyClaim,
    IdempotencyRecord,
    InvocationAuthorizationRecord,
    InvocationResultRecord,
    KnowledgeChangeSetRecord,
    KnowledgeEvidenceCandidate,
    KnowledgeGraphRecord,
    KnowledgeReleaseRecord,
    KnowledgeStudioABoxRecord,
    KnowledgeStudioBindingRecord,
    KnowledgeStudioDomainOption,
    KnowledgeStudioDraftRecord,
    KnowledgeStudioIngestionJobRecord,
    KnowledgeStudioManagedDomainRecord,
    KnowledgeStudioPreflightRecord,
    KnowledgeStudioReleaseRecord,
    KnowledgeStudioSamplePage,
    KnowledgeStudioSampleRequest,
    KnowledgeStudioSourceAccess,
    KnowledgeStudioSourceDetail,
    KnowledgeStudioSourcePage,
    KnowledgeStudioSourceProbe,
    KnowledgeStudioTBoxProposalRecord,
    KnowledgeStudioTBoxRecord,
    KnowledgeStudioValidationEvidence,
    ManualMetadataApplyAttemptEvidence,
    MembershipChangeRequestActivityPage,
    MembershipOwnedTablePage,
    MembershipRenewalPage,
    MembershipRenewalRecord,
    MultipartUpload,
    ObjectMetadata,
    RegistrationCandidateBindingCommand,
    RetentionArchiveVerification,
    RetentionExecutionClaim,
    RetentionExecutionEvidence,
    SystemAssigneePage,
    SystemDirectoryEntry,
    SystemDirectoryPage,
    UploadPreparationReceiptEvidence,
    UploadRegistrationCandidateEvidence,
    WorkspaceMembershipAccessRecord,
    WorkspaceMembershipPage,
)
from datariver.application.identity_admin import ProvisionedWorkspaceUser
from datariver.domain.admin_access import (
    AdminAccessRequest,
    MembershipAccessUpdate,
    SystemAssigneePatchCommand,
    SystemAssigneeUpdateCommand,
)
from datariver.domain.authz import (
    Classification,
    Decision,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.chat import ChatRetrievalMode
from datariver.domain.common import DomainEvent
from datariver.domain.governance import ApprovalAuthority, ChangeRequest
from datariver.domain.knowledge import ChangeSetState, GraphChangeOperation, GraphSnapshot
from datariver.domain.knowledge_pipeline import ModelBinding
from datariver.domain.knowledge_studio import TBoxElementInput
from datariver.domain.manual_metadata import (
    ManualMetadataApplyClaim,
    ManualMetadataAspectReport,
    ManualMetadataSubmission,
)
from datariver.domain.membership_renewal import MembershipRenewalRequest
from datariver.domain.registration import CompletedUploadPart, UploadManifest, UploadPreparation
from datariver.domain.registration_worker import (
    RegistrationWorkerCallIdentity,
    RegistrationWorkerCallReplay,
)
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


@dataclass(frozen=True, slots=True)
class RetentionPolicyPage:
    items: tuple[RetentionPolicyVersion, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class LegalHoldPage:
    items: tuple[LegalHold, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class ErasureRequestPage:
    items: tuple[ErasureRequest, ...]
    next_cursor: str | None


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


class CatalogChangeTargetReader(Protocol):
    async def get_authorized_assets_by_external_urns(
        self,
        *,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        external_urns: Sequence[str],
        lock_for_share: bool = False,
    ) -> Sequence[CatalogAssetIndex]: ...


class CatalogCandidateTargetReader(Protocol):
    async def get_authorized_assets_by_ids(
        self,
        *,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        asset_ids: Sequence[UUID],
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

    async def vocabulary(
        self,
        *,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        kind: str,
        query: str,
        limit: int,
    ) -> CatalogVocabulary: ...


class CatalogWatermarkReader(Protocol):
    async def get_search_watermark(self, *, workspace_id: UUID) -> int: ...


class CatalogTelemetry(Protocol):
    def catalog_cache_access(self, *, cache: str, outcome: str) -> None: ...

    def catalog_detail_source(self, *, source: str) -> None: ...


class CatalogExportStore(Protocol):
    async def create(
        self,
        *,
        workspace_id: UUID,
        requested_by: UUID,
        request: CatalogExportRequest,
        request_hash: str,
        permission_scope_hash: str,
        classification_access_hash: str,
        builtin_policy_version: str,
        classification_policy_id: UUID | None,
        classification_policy_hash: str | None,
        classification_policy_version: int | None,
        authorization_generation: int | None,
        source_projection_version: int,
        classification_ceiling: int,
        csv_safety_version: str,
        access_until: datetime,
        idempotency_key: str,
    ) -> CatalogExportRecord: ...

    async def get_owned(
        self, *, workspace_id: UUID, export_id: UUID, requested_by: UUID
    ) -> CatalogExportRecord | None: ...


class CatalogExportWorkerStore(Protocol):
    async def claim_next(
        self,
        *,
        worker_id: str,
        system_actor_id: UUID,
        lease_seconds: int,
        maximum_attempts: int,
    ) -> CatalogExportClaim | None: ...

    async def read_page(
        self,
        *,
        claim: CatalogExportClaim,
        cursor: str | None,
        limit: int,
    ) -> CatalogPage: ...

    async def snapshot_is_current(self, *, claim: CatalogExportClaim) -> bool: ...

    async def mark_completed(
        self,
        *,
        claim: CatalogExportClaim,
        system_actor_id: UUID,
        bucket: str,
        object_key: str,
        artifact: CatalogExportArtifact,
        row_count: int,
    ) -> None: ...

    async def mark_failed(
        self,
        *,
        claim: CatalogExportClaim,
        system_actor_id: UUID,
        error_code: str,
        retryable: bool,
        maximum_attempts: int,
    ) -> None: ...


class CatalogExportObjectStore(Protocol):
    async def write_immutable_receipt(
        self,
        *,
        bucket: str,
        object_key: str,
        content: bytes,
        metadata: dict[str, str],
        maximum_bytes: int,
        content_type: str = "text/csv; charset=utf-8",
    ) -> CatalogExportArtifact: ...

    async def write_export(
        self,
        *,
        bucket: str,
        object_key: str,
        chunks: AsyncIterator[bytes],
        metadata: dict[str, str],
        maximum_bytes: int,
        content_type: str = "text/csv; charset=utf-8",
    ) -> CatalogExportArtifact: ...

    async def delete_export(self, *, bucket: str, object_key: str) -> None: ...


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

    async def scan_assets(self, *, cursor: str | None, limit: int) -> DataHubScanPage: ...

    async def scan_vocabulary(
        self, *, kind: str, cursor: str | None, limit: int
    ) -> DataHubVocabularyScanPage: ...

    async def search_vocabulary(self, *, kind: str, query: str, limit: int) -> tuple[str, ...]: ...


class CatalogMetadataVocabularyProjection(Protocol):
    async def reserve_scan(
        self,
        *,
        workspace_id: UUID,
        sync_id: UUID,
        kind: str,
        offset: int,
        idempotency_key: str,
        request_hash: str,
        operation: str,
    ) -> CatalogVocabularySyncReservation: ...

    async def release_scan(self) -> None: ...

    async def abandon_scan(
        self,
        *,
        workspace_id: UUID,
        sync_id: UUID,
        kind: str,
    ) -> None: ...

    async def upsert_scan(
        self,
        *,
        workspace_id: UUID,
        sync_id: UUID,
        kind: str,
        offset: int,
        cursor: str | None,
        next_offset: int | None,
        page: DataHubVocabularyScanPage,
        idempotency_key: str,
        request_hash: str,
        operation: str,
    ) -> CatalogVocabularySyncResult: ...

    async def list_active(
        self,
        *,
        workspace_id: UUID,
        kind: str,
        query: str | None,
        cursor: str | None,
        limit: int,
    ) -> CatalogMetadataVocabularyPage: ...


class CatalogProjectionWriter(Protocol):
    async def reserve_scan(
        self,
        *,
        workspace_id: UUID,
        sync_id: UUID,
        offset: int,
        idempotency_key: str,
        request_hash: str,
        operation: str,
    ) -> CatalogSyncReservation: ...

    async def release_scan(self) -> None: ...

    async def abandon_scan(
        self,
        *,
        workspace_id: UUID,
        sync_id: UUID,
    ) -> None: ...

    async def replay_scan(
        self,
        *,
        workspace_id: UUID,
        idempotency_key: str,
        request_hash: str,
        operation: str,
    ) -> CatalogSyncResult | None: ...

    async def expected_cursor(
        self,
        *,
        workspace_id: UUID,
        sync_id: UUID,
        offset: int,
    ) -> str | None: ...

    async def scan_progress(
        self,
        *,
        workspace_id: UUID,
        sync_id: UUID,
    ) -> CatalogSyncProgress: ...

    async def upsert_scan(
        self,
        *,
        workspace_id: UUID,
        sync_id: UUID,
        offset: int,
        cursor: str | None,
        next_offset: int | None,
        next_cursor: str | None,
        total: int,
        snapshot_consistent: bool,
        snapshot_evidence_reference: str | None,
        snapshot_contract_hash: str | None,
        snapshot_provider_version: str | None,
        items: Sequence[DataHubScanAsset],
        observed_at: datetime,
        idempotency_key: str,
        request_hash: str,
        operation: str,
    ) -> CatalogSyncResult: ...


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

    async def list_summaries(
        self,
        *,
        workspace_id: UUID,
        maximum_classification: int,
        state: str | None,
        before_created_at: datetime | None,
        before_id: UUID | None,
        limit: int,
    ) -> Sequence[ChangeRequestSummaryRecord]: ...

    async def save(self, change_request: ChangeRequest) -> None: ...


class RegistrationContentBindingRepository(Protocol):
    async def verify_and_add(
        self,
        *,
        command: RegistrationCandidateBindingCommand,
        change_request_id: UUID,
        change_item_id: UUID,
        created_by: UUID,
    ) -> None: ...


class RegistrationMetadataContentBindingRepository(Protocol):
    async def verify_and_add(
        self,
        *,
        command: CatalogMetadataBindingCommand,
        change_request_id: UUID,
        change_item_id: UUID,
        created_by: UUID,
    ) -> None: ...


class ChangeRequestOverviewReader(Protocol):
    async def list_schema_overview(
        self,
        *,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        change_requests: Sequence[ChangeRequest | ChangeRequestSummaryRecord],
        limit: int,
    ) -> Sequence[ChangeRequestSchemaOverview]: ...


class ChangeWorkflowAuthorityReader(Protocol):
    async def get_authorities(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        system_ids: frozenset[UUID],
    ) -> tuple[ApprovalAuthority, ...]: ...


class OutboxWriter(Protocol):
    async def add_events(self, events: Sequence[DomainEvent]) -> None: ...


class GovernanceUnitOfWork(Protocol):
    change_requests: ChangeRequestRepository
    registration_content_bindings: RegistrationContentBindingRepository
    registration_metadata_content_bindings: RegistrationMetadataContentBindingRepository
    workflow_authorities: ChangeWorkflowAuthorityReader
    manual_metadata_submissions: ManualMetadataSubmissionRepository
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

    async def flush(self) -> None: ...

    async def rollback(self) -> None: ...

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None: ...


class ManualMetadataSubmissionRepository(Protocol):
    async def allocate_serial_number(self) -> int: ...

    async def add(self, submission: ManualMetadataSubmission) -> None: ...

    async def get(
        self, *, workspace_id: UUID, submission_id: UUID
    ) -> ManualMetadataSubmission | None: ...

    async def claim_next(
        self,
        *,
        workspace_id: UUID,
        worker_subject_id: UUID,
        now: datetime,
        lease_seconds: int,
        maximum_attempts: int,
        run_call: RegistrationWorkerCallIdentity | None = None,
    ) -> ManualMetadataApplyClaim | RegistrationWorkerCallReplay | None: ...

    async def save(self, submission: ManualMetadataSubmission) -> None: ...

    async def record_aspect_report(
        self,
        *,
        claim: ManualMetadataApplyClaim,
        report: ManualMetadataAspectReport,
    ) -> bool: ...

    async def renew_lease(
        self,
        *,
        claim: ManualMetadataApplyClaim,
        lease_seconds: int,
    ) -> bool: ...

    async def complete(
        self, *, claim: ManualMetadataApplyClaim, now: datetime
    ) -> ManualMetadataSubmission | None: ...

    async def fail(
        self,
        *,
        claim: ManualMetadataApplyClaim,
        now: datetime,
        error_code: str,
        retryable: bool,
        maximum_attempts: int,
    ) -> str | None: ...

    async def list(
        self,
        *,
        workspace_id: UUID,
        requester_id: UUID | None,
        state: str | None,
        before_created_at: datetime | None,
        before_id: UUID | None,
        limit: int,
    ) -> Sequence[ManualMetadataSubmission]: ...

    async def list_attempts(
        self,
        *,
        workspace_id: UUID,
        submission_id: UUID,
        limit: int,
    ) -> Sequence[ManualMetadataApplyAttemptEvidence]: ...


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
        self,
        *,
        workspace_id: UUID,
        state: str | None,
        limit: int,
        cursor: str | None = None,
    ) -> RetentionPolicyPage: ...

    async def next_policy_number(self, *, workspace_id: UUID) -> int: ...

    async def save(self, policy: RetentionPolicyVersion) -> None: ...


class LegalHoldRepository(Protocol):
    async def add(self, hold: LegalHold) -> None: ...

    async def get(self, *, workspace_id: UUID, hold_id: UUID) -> LegalHold | None: ...

    async def get_for_update(self, *, workspace_id: UUID, hold_id: UUID) -> LegalHold | None: ...

    async def list(
        self,
        *,
        workspace_id: UUID,
        state: str | None,
        limit: int,
        cursor: str | None = None,
    ) -> LegalHoldPage: ...

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
        self,
        *,
        workspace_id: UUID,
        state: str | None,
        limit: int,
        cursor: str | None = None,
    ) -> ErasureRequestPage: ...

    async def save(self, request: ErasureRequest) -> None: ...


class ErasureTargetReader(Protocol):
    async def get_erasure_target_snapshot(
        self,
        *,
        workspace_id: UUID,
        target_type: ErasureTargetType,
        target_id: UUID,
    ) -> ErasureTargetSnapshot | None: ...


class RetentionExecutionEvidenceReader(Protocol):
    async def assert_admin_reader_eligible(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
    ) -> None: ...

    async def get_for_erasure_request(
        self,
        *,
        workspace_id: UUID,
        erasure_request_id: UUID,
    ) -> RetentionExecutionEvidence | None: ...


class RetentionUnitOfWork(Protocol):
    policies: RetentionPolicyRepository
    legal_holds: LegalHoldRepository
    erasure_requests: ErasureRequestRepository
    erasure_targets: ErasureTargetReader
    execution_evidence: RetentionExecutionEvidenceReader
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
        self,
        *,
        workspace_id: UUID,
        state: str | None,
        limit: int,
        cursor: str | None = None,
    ) -> AdminAccessRequestPage: ...

    async def save(self, request: AdminAccessRequest) -> None: ...


class MembershipAccessRepository(Protocol):
    async def list(
        self,
        *,
        workspace_id: UUID,
        limit: int,
        query: str | None = None,
        active: bool | None = None,
        cursor: str | None = None,
    ) -> WorkspaceMembershipPage: ...

    async def get_access(
        self, *, workspace_id: UUID, subject_id: UUID
    ) -> WorkspaceMembershipAccessRecord | None: ...

    async def list_change_request_activity(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        limit: int,
        cursor: str | None = None,
    ) -> MembershipChangeRequestActivityPage: ...

    async def list_owned_tables(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        limit: int,
        cursor: str | None = None,
    ) -> MembershipOwnedTablePage: ...

    async def apply(self, command: MembershipAccessUpdate) -> int: ...

    async def record_role_assignment(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        role_id: UUID | None,
        role_version: int | None,
        role_marker: str | None,
        membership_version: int,
        access_payload_hash: str,
        actor_id: UUID,
    ) -> None: ...

    async def assert_current_version(self, command: MembershipAccessUpdate) -> None: ...

    async def assert_manual_access_update_allowed(
        self, *, workspace_id: UUID, subject_id: UUID
    ) -> None: ...

    async def assert_eligible_human_administrators(
        self, *, workspace_id: UUID, subject_ids: frozenset[UUID]
    ) -> None: ...

    async def get_expiration_for_update(
        self, *, workspace_id: UUID, subject_id: UUID
    ) -> datetime: ...

    async def extend_expiration(
        self, *, workspace_id: UUID, subject_id: UUID, expected: datetime, extended: datetime
    ) -> int: ...

    async def provision_identity_membership(
        self,
        *,
        subject_id: UUID,
        workspace_id: UUID,
        issuer: str,
        external_subject: str,
        username: str,
        display_name: str,
        email: str,
        department_id: UUID | None,
        job_function: str | None,
        role_id: UUID | None,
        access_expires_at: datetime,
    ) -> ProvisionedWorkspaceUser: ...


class MembershipRenewalRepository(Protocol):
    async def add(self, request: MembershipRenewalRequest) -> None: ...

    async def get_for_update(
        self, *, workspace_id: UUID, renewal_request_id: UUID
    ) -> MembershipRenewalRequest | None: ...

    async def list_records(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID | None,
        state: str | None,
        limit: int,
        cursor: str | None = None,
    ) -> MembershipRenewalPage: ...

    async def get_record(
        self, *, workspace_id: UUID, renewal_request_id: UUID
    ) -> MembershipRenewalRecord | None: ...

    async def save(self, request: MembershipRenewalRequest) -> None: ...


class SystemDirectoryRepository(Protocol):
    async def list(
        self,
        *,
        workspace_id: UUID,
        limit: int,
        query: str | None = None,
        active: bool | None = None,
        cursor: str | None = None,
    ) -> SystemDirectoryPage: ...

    async def list_assignees(
        self,
        *,
        workspace_id: UUID,
        system_id: UUID,
        limit: int,
        cursor: str | None = None,
    ) -> SystemAssigneePage: ...

    async def patch_assignees(self, command: SystemAssigneePatchCommand) -> int: ...

    async def replace_assignees(self, command: SystemAssigneeUpdateCommand) -> int: ...

    async def create(
        self,
        *,
        workspace_id: UUID,
        code: str,
        name: str,
        description: str,
    ) -> SystemDirectoryEntry: ...


class AdminAccessUnitOfWork(Protocol):
    requests: AdminAccessRequestRepository
    memberships: MembershipAccessRepository
    renewals: MembershipRenewalRepository
    systems: SystemDirectoryRepository
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

    async def renew_lease(
        self,
        *,
        claim: GovernanceApplyClaim,
        lease_seconds: int,
    ) -> bool: ...


class GovernanceApplyReauthorizer(Protocol):
    async def reauthorize(self, *, context: GovernanceApplyAuthorizationContext) -> bool:
        """Re-read human membership, typed binding, target and policy state before apply."""
        ...


class ProviderMutationLock(Protocol):
    def hold(
        self,
        *,
        workspace_id: UUID,
        provider: str,
        target_ref: str,
        aspect_name: str,
        on_wait: Callable[[], Awaitable[None]] | None = None,
    ) -> AbstractAsyncContextManager[None]: ...


class JobDelivery(Protocol):
    async def publish_job_id(self, *, event_id: UUID, job_id: UUID) -> None: ...


class IdempotencyStore(Protocol):
    async def acquire_key_lock(self, *, workspace_id: UUID, key: str, operation: str) -> None: ...

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
    async def write_create_only(
        self,
        *,
        bucket: str,
        object_key: str,
        chunks: AsyncIterator[bytes],
        metadata: dict[str, str],
        maximum_bytes: int,
        content_type: str = "application/octet-stream",
    ) -> CatalogExportArtifact: ...

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

    async def find_archive(
        self,
        *,
        object_key: str,
        size_bytes: int,
        sha256: str,
        retain_until: datetime,
        expected_metadata: dict[str, str],
    ) -> ArchiveWriteReceipt | None: ...

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


class RetentionExecutionStore(Protocol):
    async def plan_next(
        self,
        *,
        workspace_id: UUID,
        executor_id: UUID,
        archive_configuration_hash: str,
        maximum_attempts: int,
    ) -> bool: ...

    async def claim_next(
        self,
        *,
        workspace_id: UUID,
        worker_id: str,
        worker_principal_fingerprint: str,
        lease_seconds: int,
    ) -> RetentionExecutionClaim | None: ...

    async def revalidate_before_archive(self, *, claim: RetentionExecutionClaim) -> bool: ...

    async def record_archive_capability(
        self,
        *,
        claim: RetentionExecutionClaim,
        capability: ArchiveCapability,
        evidence: ArchiveCapabilityEvidence,
    ) -> ArchiveCapabilityRecord: ...

    async def get_archive_capability_for_write(
        self,
        *,
        claim: RetentionExecutionClaim,
        attestation_id: UUID,
        written_at: datetime,
    ) -> ArchiveCapabilityRecord | None: ...

    async def complete_archive(
        self,
        *,
        claim: RetentionExecutionClaim,
        verification: RetentionArchiveVerification,
    ) -> None: ...

    async def mark_failed(
        self,
        *,
        claim: RetentionExecutionClaim,
        error_code: str,
        retryable: bool,
        orphan_verification: RetentionArchiveVerification | None = None,
    ) -> str | None: ...


class UploadRepository(Protocol):
    async def add(self, manifest: UploadManifest) -> None: ...

    async def get(self, *, workspace_id: UUID, upload_id: UUID) -> UploadManifest | None: ...

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


class UploadPreparationRepository(Protocol):
    async def add(self, preparation: UploadPreparation) -> None: ...

    async def get(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        preparation_id: UUID,
    ) -> UploadPreparation | None: ...

    async def find_source_configuration(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        source_manifest_version: int,
        content_profile: str,
        configuration_hash: str,
    ) -> UploadPreparation | None: ...

    async def list(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        state: str | None,
        limit: int,
    ) -> Sequence[UploadPreparation]: ...


class UploadCandidateReader(Protocol):
    async def get_ready_receipt(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        preparation_id: UUID,
    ) -> UploadPreparationReceiptEvidence | None: ...

    async def get_candidate(
        self,
        *,
        workspace_id: UUID,
        receipt_id: UUID,
        candidate_id: UUID,
    ) -> UploadRegistrationCandidateEvidence | None: ...

    async def list_candidates(
        self,
        *,
        workspace_id: UUID,
        receipt_id: UUID,
        after_ordinal: int,
        limit: int,
    ) -> Sequence[UploadRegistrationCandidateEvidence]: ...


class CatalogMetadataCandidateReader(Protocol):
    async def get_ready_receipt(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        preparation_id: UUID,
    ) -> UploadPreparationReceiptEvidence | None: ...

    async def get_candidate(
        self,
        *,
        workspace_id: UUID,
        receipt_id: UUID,
        candidate_id: UUID,
    ) -> CatalogMetadataCandidateEvidence | None: ...

    async def list_candidates(
        self,
        *,
        workspace_id: UUID,
        receipt_id: UUID,
        after_ordinal: int,
        limit: int,
    ) -> Sequence[CatalogMetadataCandidateEvidence]: ...


class UploadUnitOfWork(Protocol):
    uploads: UploadRepository
    preparations: UploadPreparationRepository
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
        validated_sha256: str,
        validation_summary: dict[str, object],
    ) -> bool: ...

    async def mark_failed(
        self,
        *,
        manifest: UploadManifest,
        error_code: str,
        retryable: bool,
        maximum_attempts: int,
    ) -> None: ...


class KnowledgeStudioStore(Protocol):
    async def list_domains(
        self,
        *,
        workspace_id: UUID,
        allowed_domain_ids: frozenset[UUID] | None,
        creator_id: UUID | None,
        query: str | None,
        limit: int,
    ) -> tuple[KnowledgeStudioDomainOption, ...]: ...

    async def is_managed_domain_creator(
        self,
        *,
        workspace_id: UUID,
        domain_id: UUID,
        creator_id: UUID,
        source_version: str,
    ) -> bool: ...

    async def list_managed_domains(
        self,
        *,
        workspace_id: UUID,
        limit: int,
    ) -> tuple[KnowledgeStudioManagedDomainRecord, ...]: ...

    async def create_managed_domain(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        display_name: str,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioManagedDomainRecord: ...

    async def update_managed_domain(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        domain_id: UUID,
        display_name: str,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioManagedDomainRecord: ...

    async def archive_managed_domain(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        domain_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioManagedDomainRecord: ...

    async def get_draft(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        draft_id: UUID,
    ) -> KnowledgeStudioDraftRecord | None: ...

    async def get_owned_live_draft_by_endpoint_alias(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        endpoint_alias: str,
    ) -> KnowledgeStudioDraftRecord | None: ...

    async def get_tbox(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        draft_id: UUID,
    ) -> KnowledgeStudioTBoxRecord | None: ...

    async def create_tbox_block(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
        kind: str,
        title: str,
        weight: int,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioTBoxRecord: ...

    async def update_tbox_block(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
        block_id: UUID,
        title: str,
        weight: int,
        collapsed: bool,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioTBoxRecord: ...

    async def delete_tbox_block(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
        block_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioTBoxRecord: ...

    async def save_tbox_block_elements(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
        block_id: UUID,
        elements_by_block: tuple[tuple[UUID, tuple[TBoxElementInput, ...]], ...],
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioTBoxRecord: ...

    async def save_tbox_proposal(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
        base_draft_version: int,
        target_block_id: UUID | None,
        mode: str,
        prompt: str,
        elements: tuple[TBoxElementInput, ...],
        conflicts: tuple[dict[str, object], ...],
        model_binding: dict[str, object],
        source_reference: dict[str, object] | None,
    ) -> KnowledgeStudioTBoxProposalRecord: ...

    async def get_tbox_proposal(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        draft_id: UUID,
        proposal_id: UUID,
    ) -> KnowledgeStudioTBoxProposalRecord | None: ...

    async def apply_tbox_proposal(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
        proposal_id: UUID,
        target_block_id: UUID | None,
        elements_by_block: tuple[tuple[UUID, tuple[TBoxElementInput, ...]], ...],
        appended_elements: tuple[TBoxElementInput, ...],
        conflicts: tuple[dict[str, object], ...],
        merge_strategy: str,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioTBoxRecord: ...

    async def create_ingestion_job(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
        expected_version: int,
        embedding_binding: dict[str, object] | None,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioIngestionJobRecord: ...

    async def get_ingestion_job(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        draft_id: UUID,
        job_id: UUID,
    ) -> KnowledgeStudioIngestionJobRecord | None: ...

    async def list_ingestion_jobs(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        draft_id: UUID,
        limit: int,
    ) -> tuple[KnowledgeStudioIngestionJobRecord, ...]: ...

    async def get_edit_graph(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        clearance: int,
    ) -> KnowledgeGraphRecord | None: ...

    async def create_edit_draft(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        graph_id: UUID,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioDraftRecord: ...

    async def create_draft(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        name: str,
        endpoint_alias: str,
        endpoint_aliases: tuple[str, ...],
        domain_id: UUID,
        domain_source_version: str,
        classification: int,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioDraftRecord: ...

    async def autosave_draft(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
        name: str,
        endpoint_alias: str,
        endpoint_aliases: tuple[str, ...],
        domain_id: UUID,
        domain_source_version: str,
        classification: int,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioDraftRecord: ...

    async def advance_to_tbox(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioDraftRecord: ...

    async def advance_to_abox(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioDraftRecord: ...

    async def get_abox(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        draft_id: UUID,
    ) -> KnowledgeStudioABoxRecord | None: ...

    async def save_abox_binding(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
        target_stable_element_id: str,
        source_asset_id: UUID,
        source_version: str,
        projection_source_version: str,
        source_classification: int,
        source_name: str,
        rules: tuple[tuple[str, str, str], ...],
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> tuple[KnowledgeStudioDraftRecord, KnowledgeStudioBindingRecord]: ...

    async def record_preflight(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        draft_id: UUID,
        expected_version: int,
        status: str,
        valid: bool,
        evidence: tuple[KnowledgeStudioValidationEvidence, ...],
        checked_at: datetime,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioPreflightRecord: ...

    async def submit_review(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioDraftRecord: ...

    async def discard_draft(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioDraftRecord: ...

    async def publish_draft(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        draft_id: UUID,
        review_reason: str,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> tuple[KnowledgeStudioDraftRecord, KnowledgeStudioReleaseRecord]: ...


class KnowledgeStudioSourceReader(Protocol):
    async def search_datasets(
        self,
        *,
        subject: SubjectAttributes,
        maximum_classification: Classification,
        query: str,
        cursor: str | None,
        limit: int,
        environment: EnvironmentAttributes,
        request_id: str,
        domain: str | None = None,
        search_fields: str | None = None,
    ) -> KnowledgeStudioSourcePage: ...

    async def get_dataset(
        self,
        *,
        subject: SubjectAttributes,
        asset_id: UUID,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeStudioSourceDetail | None: ...

    async def validate_dataset_access(
        self,
        *,
        subject: SubjectAttributes,
        asset_ids: tuple[UUID, ...],
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[KnowledgeStudioSourceAccess, ...]: ...


class KnowledgeStudioSchemaAssistant(Protocol):
    async def propose(
        self,
        *,
        prompt: str,
        current_elements: tuple[TBoxElementInput, ...],
        binding: ModelBinding,
    ) -> tuple[TBoxElementInput, ...]: ...


class KnowledgeStudioSampleReader(Protocol):
    async def sample_rows(
        self,
        *,
        subject: SubjectAttributes,
        source: KnowledgeStudioSampleRequest,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeStudioSamplePage: ...

    async def probe_access(
        self,
        *,
        subject: SubjectAttributes,
        sources: tuple[KnowledgeStudioSampleRequest, ...],
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[KnowledgeStudioSourceProbe, ...]: ...


class KnowledgeStore(Protocol):
    async def create_graph(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
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
        self,
        *,
        workspace_id: UUID,
        clearance: int,
        allowed_domain_ids: frozenset[UUID],
    ) -> tuple[KnowledgeGraphRecord, ...]: ...

    async def get_graph(
        self, *, workspace_id: UUID, graph_id: UUID, clearance: int
    ) -> KnowledgeGraphRecord | None: ...

    async def get_graph_for_archive(
        self, *, workspace_id: UUID, graph_id: UUID, clearance: int
    ) -> KnowledgeGraphRecord | None: ...

    async def archive_graph(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        actor_id: UUID,
        expected_version: int,
        reason: str,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeGraphRecord: ...

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

    async def publish_approved_changeset(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        changeset_id: UUID,
        published_by: UUID,
        idempotency_key: str,
        request_hash: str,
    ) -> tuple[KnowledgeChangeSetRecord, KnowledgeReleaseRecord]: ...

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
        retention: ChatRetentionBinding,
        route: ChatRouteDecision | None = None,
        workflow: Sequence[ChatWorkflowEvent] = (),
        evidence_ranking: Sequence[ChatEvidenceRanking] = (),
        composition_audit: ChatCompositionAudit | None = None,
    ) -> ChatExchange: ...


class ChatPersistenceUnitOfWork(Protocol):
    chats: ChatStore
    retention_policies: RetentionPolicyRepository

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...

    async def lock_retention_workspace(self, *, workspace_id: UUID) -> None: ...

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None: ...

    async def transaction_time(self) -> datetime: ...


class ChatAnswerComposer(Protocol):
    async def compose(
        self,
        *,
        question: str,
        evidence: Sequence[ChatEvidence],
    ) -> ChatDraft: ...


class ChatGeneralAnswerComposer(Protocol):
    async def compose_general(
        self,
        *,
        question: str,
    ) -> ChatDraft: ...


class ChatRouteIntentClassifier(Protocol):
    """Classify a bounded question into a non-executable retrieval contract."""

    async def classify_route(
        self,
        *,
        question: str,
    ) -> ChatRetrievalMode: ...


class ChatQuestionRouter(Protocol):
    @property
    def requires_composition_inference(self) -> bool: ...

    async def route(
        self,
        *,
        question: str,
        requested_mode: ChatRetrievalMode,
        vector_available: bool,
        graph_available: bool,
        inference_allowed: bool,
    ) -> ChatRouteDecision: ...


class ChatWorkflowProgressObserver(Protocol):
    """Receive non-persisted, server-observed Chat workflow transitions."""

    def publish(self, *, event: ChatWorkflowEvent) -> None: ...


class ChatVectorCatalogReader(Protocol):
    async def search(
        self,
        *,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        question: str,
        limit: int,
    ) -> ChatVectorSearchResult: ...


class GovernanceChatEvidenceReader(Protocol):
    async def search(
        self,
        *,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        question: str,
        limit: int,
    ) -> tuple[ChatEvidence, ...]: ...

    async def get_current(
        self,
        *,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        resource_ids: Sequence[UUID],
    ) -> tuple[ChatEvidence, ...]: ...


class ChatEvidenceReranker(Protocol):
    async def rerank(
        self,
        *,
        question: str,
        evidence: Sequence[ChatEvidence],
    ) -> tuple[UUID, ...]: ...


class ChatRequestBudgetGuard(Protocol):
    async def reserve(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        policy_scope: str,
        estimated_tokens: int,
        request_limit: int,
        token_limit: int,
        window_seconds: int,
    ) -> None: ...


class ChatHistoryStore(Protocol):
    async def get_session_owner(
        self,
        *,
        workspace_id: UUID,
        session_id: UUID,
    ) -> UUID | None: ...

    async def list_sessions(
        self,
        *,
        workspace_id: UUID,
        owner_id: UUID,
        limit: int,
    ) -> Sequence[ChatSessionRecord]: ...

    async def list_messages(
        self,
        *,
        workspace_id: UUID,
        owner_id: UUID,
        session_id: UUID,
        limit: int,
    ) -> Sequence[ChatMessageRecord]: ...

    async def set_favorite(
        self,
        *,
        workspace_id: UUID,
        owner_id: UUID,
        session_id: UUID,
        expected_version: int,
        is_favorite: bool,
    ) -> ChatSessionRecord: ...

    async def archive_session(
        self,
        *,
        workspace_id: UUID,
        owner_id: UUID,
        session_id: UUID,
        expected_version: int,
    ) -> None: ...


class ChatSessionOwnershipReader(Protocol):
    async def get_session_owner(
        self,
        *,
        workspace_id: UUID,
        session_id: UUID,
    ) -> UUID | None: ...


class ChatSubjectAccessReader(Protocol):
    async def refresh_subject(
        self,
        *,
        subject: SubjectAttributes,
        now: datetime,
    ) -> SubjectAttributes: ...


class AssistantInferenceAdapter(Protocol):
    async def infer(
        self,
        *,
        package: AuthorizedInferencePackage,
    ) -> ProviderInferenceDraft: ...


class AssistantGroundingVerifier(Protocol):
    async def assess(
        self,
        *,
        package: AuthorizedInferencePackage,
        draft: ProviderInferenceDraft,
    ) -> InferenceGroundingAssessment: ...


class KnowledgeEvidenceReader(Protocol):
    async def search_active_nodes(
        self,
        *,
        workspace_id: UUID,
        query: str,
        maximum_classification: int,
        limit: int,
    ) -> Sequence[KnowledgeEvidenceCandidate]: ...

    async def get_active_nodes_by_resource_ids(
        self,
        *,
        workspace_id: UUID,
        resource_ids: Sequence[UUID],
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
        consumer_subject_id: UUID,
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

    async def execute_invocation(
        self,
        *,
        workspace_id: UUID,
        product_id: UUID,
        actor_id: UUID,
        consumer_issuer: str,
        consumer_client_id: str,
        security_scopes: frozenset[str],
        effective_classification: int,
        requested_scope: str,
        operation: str,
        result_type: str,
        payload_document: dict[str, Any],
        invocation_key: str,
        request_id: str,
        result_builder: Callable[[InvocationAuthorizationRecord], Awaitable[dict[str, Any]]],
    ) -> InvocationResultRecord: ...
