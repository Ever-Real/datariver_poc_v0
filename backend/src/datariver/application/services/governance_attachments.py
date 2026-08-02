from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from datariver.application.dto import ObjectMetadata
from datariver.application.ports import GovernanceUnitOfWork
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import (
    ConflictError,
    DomainError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
    utc_now,
)
from datariver.domain.governance import (
    ApprovalAuthority,
    ApprovalAuthorityKind,
    ChangeRequest,
    ChangeState,
)

ATTACHMENT_UPLOAD_RECONCILE_STATES = frozenset({"STARTED", "STORED"})
_KNOWN_CREATE_REJECTION_CODES = frozenset({"OBJECT_KEY_ALREADY_EXISTS"})


@dataclass(frozen=True, slots=True)
class AttachmentUploadIntent:
    attachment_id: UUID
    workspace_id: UUID
    change_request_id: UUID
    round_id: UUID
    kind: str
    original_name: str
    serial_number: int
    bucket: str
    object_key: str
    content_type: str
    expected_size_bytes: int
    expected_content_sha256: str
    uploaded_by: UUID
    state: str
    size_bytes: int | None = None
    content_sha256: str | None = None
    provider_checksum: str | None = None
    stored_at: datetime | None = None
    finalized_at: datetime | None = None
    failed_at: datetime | None = None
    failure_code: str | None = None


@dataclass(frozen=True, slots=True)
class FinalizedAttachment:
    id: UUID
    kind: str
    round_id: UUID
    original_name: str
    serial_number: int
    content_type: str
    size_bytes: int
    content_sha256: str
    created_at: datetime


class AttachmentTargetAuthorizer(Protocol):
    async def filter_authorized_change_requests(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        change_requests: Sequence[ChangeRequest],
        action: Action,
        environment: EnvironmentAttributes,
        request_id: str,
        strict_binding: bool,
    ) -> tuple[ChangeRequest, ...]: ...


class AttachmentUploadIntentStore(Protocol):
    async def lock_current_subject(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
    ) -> SubjectAttributes: ...

    async def lock_authorization_dependencies(
        self,
        *,
        change_request: ChangeRequest,
        subject_id: UUID,
    ) -> None: ...

    async def refresh_effective_subject(
        self,
        *,
        subject: SubjectAttributes,
        observed_at: datetime,
    ) -> SubjectAttributes: ...

    async def allocate_serial_number(
        self,
        *,
        workspace_id: UUID,
        change_request_id: UUID,
        kind: str,
        original_name: str,
    ) -> int: ...

    async def add_started(self, intent: AttachmentUploadIntent) -> None: ...

    async def get(
        self,
        *,
        workspace_id: UUID,
        attachment_id: UUID,
    ) -> AttachmentUploadIntent | None: ...

    async def mark_stored(
        self,
        *,
        intent: AttachmentUploadIntent,
        size_bytes: int,
        content_sha256: str,
        provider_checksum: str | None,
        occurred_at: datetime,
    ) -> AttachmentUploadIntent: ...

    async def mark_failed(
        self,
        *,
        intent: AttachmentUploadIntent,
        failure_code: str,
        occurred_at: datetime,
    ) -> AttachmentUploadIntent: ...

    async def finalize(
        self,
        *,
        intent: AttachmentUploadIntent,
        expected_change_request_version: int,
        occurred_at: datetime,
    ) -> FinalizedAttachment: ...

    async def list_reconcilable(
        self,
        *,
        workspace_id: UUID,
        change_request_id: UUID | None,
        round_id: UUID | None,
        states: frozenset[str],
        before_or_at: datetime,
        limit: int,
    ) -> tuple[AttachmentUploadIntent, ...]: ...


class AttachmentEvidenceObjectStore(Protocol):
    async def head_object(self, *, bucket: str, object_key: str) -> ObjectMetadata: ...

    def iter_object_chunks(
        self,
        *,
        bucket: str,
        object_key: str,
        chunk_size: int = 1024 * 1024,
    ) -> AsyncIterator[bytes]: ...


class AttachmentReconciliationStore(Protocol):
    async def next_started(
        self,
        *,
        before_or_at: datetime,
    ) -> AttachmentUploadIntent | None: ...

    async def attest_stored(
        self,
        *,
        intent: AttachmentUploadIntent,
        size_bytes: int,
        content_sha256: str,
        provider_checksum: str,
    ) -> None: ...

    async def defer(self, *, intent: AttachmentUploadIntent) -> None: ...


class AttachmentReconciliationWorker:
    """Independently read provider bytes before the upload role attests a STARTED intent."""

    _MAXIMUM_BYTES = 10 * 1024 * 1024
    _MINIMUM_INTENT_AGE = timedelta(seconds=5)

    def __init__(
        self,
        *,
        store: AttachmentReconciliationStore,
        object_store: AttachmentEvidenceObjectStore,
    ) -> None:
        self._store = store
        self._object_store = object_store

    async def run_once(self) -> bool:
        intent = await self._store.next_started(
            before_or_at=utc_now() - self._MINIMUM_INTENT_AGE,
        )
        if intent is None:
            return False
        try:
            size_bytes, content_sha256, provider_checksum = await self._provider_evidence(intent)
            await self._store.attest_stored(
                intent=intent,
                size_bytes=size_bytes,
                content_sha256=content_sha256,
                provider_checksum=provider_checksum,
            )
        except DomainError:
            # Preserve ambiguous bytes. A same-state, server-timed fence prevents a hot retry
            # loop without falsely classifying an unavailable or mismatched object as absent.
            await self._store.defer(intent=intent)
        return True

    async def _provider_evidence(
        self,
        intent: AttachmentUploadIntent,
    ) -> tuple[int, str, str]:
        metadata = await self._object_store.head_object(
            bucket=intent.bucket,
            object_key=intent.object_key,
        )
        expected_metadata = {
            "workspace-id": str(intent.workspace_id),
            "change-request-id": str(intent.change_request_id),
            "attachment-id": str(intent.attachment_id),
            "attachment-kind": intent.kind,
            "content-sha256": intent.expected_content_sha256,
        }
        if (
            metadata.bucket != intent.bucket
            or metadata.object_key != intent.object_key
            or metadata.size_bytes != intent.expected_size_bytes
            or metadata.content_type != intent.content_type
            or any(
                metadata.user_metadata.get(key) != value for key, value in expected_metadata.items()
            )
        ):
            raise ConflictError(
                "The provider object metadata does not match its precommitted upload intent.",
                details={"code": "ATTACHMENT_PROVIDER_METADATA_MISMATCH"},
            )

        digest = hashlib.sha256()
        size_bytes = 0
        async for chunk in self._object_store.iter_object_chunks(
            bucket=intent.bucket,
            object_key=intent.object_key,
        ):
            size_bytes += len(chunk)
            if size_bytes > self._MAXIMUM_BYTES:
                raise ConflictError(
                    "The provider object exceeds the attachment reconciliation limit.",
                    details={"code": "ATTACHMENT_PROVIDER_BYTE_LIMIT"},
                )
            digest.update(chunk)
        content_sha256 = digest.hexdigest()
        if (
            size_bytes != intent.expected_size_bytes
            or content_sha256 != intent.expected_content_sha256
        ):
            raise ConflictError(
                "The provider object bytes do not match the precommitted upload intent.",
                details={"code": "ATTACHMENT_PROVIDER_READBACK_MISMATCH"},
            )
        provider_checksum = (
            f"sha256:{metadata.checksum_sha256}"
            if metadata.checksum_sha256
            else f"etag:{metadata.etag}"
        )
        if len(provider_checksum) > 255 or (not metadata.etag and not metadata.checksum_sha256):
            raise ConflictError(
                "The provider did not return a bounded object checksum.",
                details={"code": "ATTACHMENT_PROVIDER_CHECKSUM_MISSING"},
            )
        return size_bytes, content_sha256, provider_checksum


class GovernanceAttachmentUploadService:
    """Authorize, evidence and finalize CR attachment writes around a fallible object store."""

    def __init__(
        self,
        uow_factory: Callable[[], GovernanceUnitOfWork],
        authorization: AuthorizationService,
        *,
        store: AttachmentUploadIntentStore,
        target_authorizer: AttachmentTargetAuthorizer,
    ) -> None:
        self._uow_factory = uow_factory
        self._authorization = authorization
        self._store = store
        self._target_authorizer = target_authorizer

    @staticmethod
    def _resource(change_request: ChangeRequest) -> ResourceAttributes:
        item = change_request.items[0] if len(change_request.items) == 1 else None
        target_classification = (
            item.target_classification
            if item is not None and item.target_classification is not None
            else change_request.classification
        )
        return ResourceAttributes(
            resource_id=change_request.change_request_id,
            workspace_id=change_request.workspace_id,
            resource_type="change_request",
            owner_department_id=item.target_owner_department_id if item is not None else None,
            system_id=(
                item.routing_system_id or item.target_system_id if item is not None else None
            ),
            domain_id=item.target_domain_id if item is not None else None,
            classification=max(change_request.classification, target_classification),
            lifecycle=change_request.state.value,
            requester_id=change_request.requester_id,
        )

    @staticmethod
    async def _require_current_developer_assignment(
        uow: GovernanceUnitOfWork,
        *,
        change_request: ChangeRequest,
        subject_id: UUID,
    ) -> None:
        authorities = await uow.workflow_authorities.get_authorities(
            workspace_id=change_request.workspace_id,
            subject_id=subject_id,
            system_ids=change_request.required_system_ids(),
        )
        relevant = {
            ApprovalAuthority(ApprovalAuthorityKind.SYSTEM_DEVELOPER, system_id)
            for system_id in change_request.required_system_ids()
        }
        if not relevant & set(authorities):
            raise ForbiddenError(
                "Developer assignment is required for a target system in this stage."
            )

    async def _authorize_locked(
        self,
        *,
        uow: GovernanceUnitOfWork,
        change_request: ChangeRequest,
        kind: str,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> None:
        if kind == "TEST":
            if change_request.state is not ChangeState.TESTING:
                raise ValidationError(
                    "Test evidence can only be attached during the TESTING state."
                )
            action = Action.CHANGE_REVIEW
            await self._require_current_developer_assignment(
                uow,
                change_request=change_request,
                subject_id=subject.subject_id,
            )
        else:
            if change_request.state not in {
                ChangeState.REGISTERED,
                ChangeState.CHANGES_REQUESTED,
            }:
                raise ValidationError(
                    "Request attachments can only be changed before review or after a "
                    "change request."
                )
            action = Action.CHANGE_EDIT
        await self._authorization.authorize(
            subject=subject,
            resource=self._resource(change_request),
            action=action,
            environment=environment,
            request_id=request_id,
        )
        authorized = await self._target_authorizer.filter_authorized_change_requests(
            workspace_id=change_request.workspace_id,
            subject=subject,
            change_requests=(change_request,),
            action=action,
            environment=environment,
            request_id=request_id,
            strict_binding=True,
        )
        if not authorized:
            raise ForbiddenError("The change target is not available.")

    async def _locked_authorization_context(
        self,
        *,
        uow: GovernanceUnitOfWork,
        workspace_id: UUID,
        change_request_id: UUID,
        kind: str,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[ChangeRequest, SubjectAttributes]:
        current_subject = await self._store.lock_current_subject(
            workspace_id=workspace_id,
            subject=subject,
        )
        change_request = await uow.change_requests.get_for_update(
            workspace_id=workspace_id,
            change_request_id=change_request_id,
        )
        if change_request is None:
            raise NotFoundError("The change request does not exist.")
        await self._store.lock_authorization_dependencies(
            change_request=change_request,
            subject_id=current_subject.subject_id,
        )
        current_subject = await self._store.refresh_effective_subject(
            subject=current_subject,
            observed_at=environment.requested_at,
        )
        await self._authorize_locked(
            uow=uow,
            change_request=change_request,
            kind=kind,
            subject=current_subject,
            environment=environment,
            request_id=request_id,
        )
        return change_request, current_subject

    async def start(
        self,
        *,
        attachment_id: UUID,
        workspace_id: UUID,
        change_request_id: UUID,
        kind: str,
        original_name: str,
        bucket: str,
        object_key: str,
        content_type: str,
        expected_size_bytes: int,
        expected_content_sha256: str,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> AttachmentUploadIntent:
        if kind not in {"REQUEST", "TEST"}:
            raise ValidationError("The change-request attachment kind is invalid.")
        if not 1 <= expected_size_bytes <= 10 * 1024 * 1024:
            raise ValidationError("The attachment size is outside the supported range.")
        if len(expected_content_sha256) != 64 or any(
            value not in "0123456789abcdef" for value in expected_content_sha256
        ):
            raise ValidationError("The attachment digest is invalid.")
        async with self._uow_factory() as uow:
            await uow.set_security_context(
                workspace_id=workspace_id,
                subject_id=subject.subject_id,
            )
            change_request, current_subject = await self._locked_authorization_context(
                uow=uow,
                workspace_id=workspace_id,
                change_request_id=change_request_id,
                kind=kind,
                subject=subject,
                environment=environment,
                request_id=request_id,
            )
            serial_number = await self._store.allocate_serial_number(
                workspace_id=workspace_id,
                change_request_id=change_request_id,
                kind=kind,
                original_name=original_name,
            )
            intent = AttachmentUploadIntent(
                attachment_id=attachment_id,
                workspace_id=workspace_id,
                change_request_id=change_request_id,
                round_id=change_request.current_round_id,
                kind=kind,
                original_name=original_name,
                serial_number=serial_number,
                bucket=bucket,
                object_key=object_key,
                content_type=content_type,
                expected_size_bytes=expected_size_bytes,
                expected_content_sha256=expected_content_sha256,
                uploaded_by=current_subject.subject_id,
                state="STARTED",
            )
            await self._store.add_started(intent)
            await uow.flush()
            await uow.commit()
            return intent

    async def record_stored(
        self,
        *,
        workspace_id: UUID,
        attachment_id: UUID,
        subject_id: UUID,
        size_bytes: int,
        content_sha256: str,
        provider_checksum: str | None,
        occurred_at: datetime,
    ) -> AttachmentUploadIntent:
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject_id)
            intent = await self._store.get(
                workspace_id=workspace_id,
                attachment_id=attachment_id,
            )
            if intent is None or intent.uploaded_by != subject_id:
                raise NotFoundError("The attachment upload intent does not exist.")
            stored = await self._store.mark_stored(
                intent=intent,
                size_bytes=size_bytes,
                content_sha256=content_sha256,
                provider_checksum=provider_checksum,
                occurred_at=occurred_at,
            )
            await uow.flush()
            await uow.commit()
            return stored

    async def record_known_create_rejection(
        self,
        *,
        workspace_id: UUID,
        attachment_id: UUID,
        subject_id: UUID,
        failure_code: str,
        occurred_at: datetime,
    ) -> AttachmentUploadIntent:
        if failure_code not in _KNOWN_CREATE_REJECTION_CODES:
            raise ValidationError("The object-store failure is not a proven create rejection.")
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject_id)
            intent = await self._store.get(
                workspace_id=workspace_id,
                attachment_id=attachment_id,
            )
            if intent is None or intent.uploaded_by != subject_id:
                raise NotFoundError("The attachment upload intent does not exist.")
            failed = await self._store.mark_failed(
                intent=intent,
                failure_code=failure_code,
                occurred_at=occurred_at,
            )
            await uow.flush()
            await uow.commit()
            return failed

    async def finalize(
        self,
        *,
        workspace_id: UUID,
        change_request_id: UUID,
        attachment_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        occurred_at: datetime,
    ) -> FinalizedAttachment:
        async with self._uow_factory() as uow:
            await uow.set_security_context(
                workspace_id=workspace_id,
                subject_id=subject.subject_id,
            )
            intent = await self._store.get(
                workspace_id=workspace_id,
                attachment_id=attachment_id,
            )
            if (
                intent is None
                or intent.uploaded_by != subject.subject_id
                or intent.change_request_id != change_request_id
            ):
                raise NotFoundError("The attachment upload intent does not exist.")
            if intent.state not in {"STORED", "FINALIZED"}:
                raise ConflictError(
                    "The attachment upload is not ready to finalize.",
                    details={"code": "ATTACHMENT_UPLOAD_NOT_STORED", "state": intent.state},
                )
            change_request, _ = await self._locked_authorization_context(
                uow=uow,
                workspace_id=workspace_id,
                change_request_id=intent.change_request_id,
                kind=intent.kind,
                subject=subject,
                environment=environment,
                request_id=request_id,
            )
            if change_request.current_round_id != intent.round_id:
                raise ConflictError(
                    "The attachment authorization round is no longer current.",
                    details={"code": "ATTACHMENT_AUTHORIZATION_STALE"},
                )
            finalized = await self._store.finalize(
                intent=intent,
                expected_change_request_version=change_request.version,
                occurred_at=occurred_at,
            )
            await uow.flush()
            await uow.commit()
            return finalized

    async def get_upload_intent(
        self,
        *,
        workspace_id: UUID,
        attachment_id: UUID,
        subject_id: UUID,
    ) -> AttachmentUploadIntent:
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject_id)
            intent = await self._store.get(
                workspace_id=workspace_id,
                attachment_id=attachment_id,
            )
            if intent is None or intent.uploaded_by != subject_id:
                raise NotFoundError("The attachment upload intent does not exist.")
            await uow.commit()
            return intent

    async def list_reconcilable(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        before_or_at: datetime,
        change_request_id: UUID | None = None,
        round_id: UUID | None = None,
        states: frozenset[str] = ATTACHMENT_UPLOAD_RECONCILE_STATES,
        limit: int = 100,
    ) -> tuple[AttachmentUploadIntent, ...]:
        if not 1 <= limit <= 100:
            raise ValidationError("Attachment reconciliation limit must be between 1 and 100.")
        if not states or not states.issubset(ATTACHMENT_UPLOAD_RECONCILE_STATES):
            raise ValidationError("Attachment reconciliation states are invalid.")
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject_id)
            values = await self._store.list_reconcilable(
                workspace_id=workspace_id,
                change_request_id=change_request_id,
                round_id=round_id,
                states=states,
                before_or_at=before_or_at,
                limit=limit,
            )
            await uow.commit()
            return values
