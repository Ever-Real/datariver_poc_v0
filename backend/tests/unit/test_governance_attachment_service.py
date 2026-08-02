from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace, TracebackType
from typing import Self, cast
from uuid import UUID, uuid4

import pytest

from datariver.application.dto import ObjectMetadata
from datariver.application.ports import GovernanceUnitOfWork
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.governance_attachments import (
    AttachmentReconciliationWorker,
    AttachmentUploadIntent,
    FinalizedAttachment,
    GovernanceAttachmentUploadService,
)
from datariver.domain.authz import (
    Action,
    AuthenticationAssurance,
    Classification,
    Decision,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ConflictError, ForbiddenError, NotFoundError
from datariver.domain.governance import (
    ApprovalAuthority,
    ChangeRequest,
    ChangeState,
)


class _DecisionWriter:
    async def append_decision(
        self,
        *,
        decision: Decision,
        subject_id: UUID,
        workspace_id: UUID,
        resource_id: UUID,
        action: str,
        request_id: str,
    ) -> None:
        del decision, subject_id, workspace_id, resource_id, action, request_id


class _ChangeRequests:
    def __init__(self, change_request: ChangeRequest) -> None:
        self.change_request = change_request

    async def get_for_update(
        self,
        *,
        workspace_id: UUID,
        change_request_id: UUID,
    ) -> ChangeRequest | None:
        if (
            self.change_request.workspace_id == workspace_id
            and self.change_request.change_request_id == change_request_id
        ):
            return self.change_request
        return None


class _Authorities:
    def __init__(self, values: tuple[ApprovalAuthority, ...] = ()) -> None:
        self.values = values

    async def get_authorities(self, **_: object) -> tuple[ApprovalAuthority, ...]:
        return self.values


class _UnitOfWork:
    def __init__(
        self,
        change_request: ChangeRequest,
        *,
        authorities: tuple[ApprovalAuthority, ...] = (),
    ) -> None:
        self.change_requests = _ChangeRequests(change_request)
        self.workflow_authorities = _Authorities(authorities)
        self.flush_calls = 0
        self.commit_calls = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None:
        del workspace_id, subject_id

    async def flush(self) -> None:
        self.flush_calls += 1

    async def commit(self) -> None:
        self.commit_calls += 1


class _TargetAuthorizer:
    def __init__(
        self,
        *,
        allowed: bool = True,
        required_system_id: UUID | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.allowed = allowed
        self.required_system_id = required_system_id
        self.events = events
        self.subjects: list[SubjectAttributes] = []

    async def filter_authorized_change_requests(
        self,
        *,
        subject: SubjectAttributes,
        change_requests: Sequence[ChangeRequest],
        **_: object,
    ) -> tuple[ChangeRequest, ...]:
        self.subjects.append(subject)
        if self.events is not None:
            self.events.append("target_authorize")
        system_allowed = (
            self.required_system_id is None or self.required_system_id in subject.allowed_system_ids
        )
        return tuple(change_requests) if self.allowed and system_allowed else ()


class _IntentStore:
    def __init__(
        self,
        current_subject: SubjectAttributes,
        *,
        refreshed_subject: SubjectAttributes | None = None,
        existing: AttachmentUploadIntent | None = None,
        subject_error: Exception | None = None,
        refresh_error: Exception | None = None,
    ) -> None:
        self.current_subject = current_subject
        self.refreshed_subject = refreshed_subject or current_subject
        self.existing = existing
        self.subject_error = subject_error
        self.refresh_error = refresh_error
        self.dependencies_locked = 0
        self.started: list[AttachmentUploadIntent] = []
        self.finalize_calls = 0
        self.list_calls: list[dict[str, object]] = []
        self.get_calls: list[dict[str, object]] = []
        self.refresh_calls: list[dict[str, object]] = []
        self.events: list[str] = []
        self.target_subjects: list[SubjectAttributes] = []

    async def lock_current_subject(self, **_: object) -> SubjectAttributes:
        self.events.append("lock_current_subject")
        if self.subject_error is not None:
            raise self.subject_error
        return self.current_subject

    async def lock_authorization_dependencies(self, **_: object) -> None:
        self.events.append("lock_authorization_dependencies")
        self.dependencies_locked += 1

    async def refresh_effective_subject(
        self,
        *,
        subject: SubjectAttributes,
        observed_at: datetime,
    ) -> SubjectAttributes:
        self.events.append("refresh_effective_subject")
        self.refresh_calls.append({"subject": subject, "observed_at": observed_at})
        if self.refresh_error is not None:
            raise self.refresh_error
        return self.refreshed_subject

    async def allocate_serial_number(self, **_: object) -> int:
        return 1

    async def add_started(self, intent: AttachmentUploadIntent) -> None:
        self.events.append("add_started")
        self.started.append(intent)

    async def get(self, **values: object) -> AttachmentUploadIntent | None:
        self.get_calls.append(values)
        if self.existing is None or self.existing.workspace_id != values["workspace_id"]:
            return None
        return self.existing

    async def mark_stored(
        self,
        *,
        intent: AttachmentUploadIntent,
        size_bytes: int,
        content_sha256: str,
        provider_checksum: str | None,
        occurred_at: datetime,
    ) -> AttachmentUploadIntent:
        return replace(
            intent,
            state="STORED",
            size_bytes=size_bytes,
            content_sha256=content_sha256,
            provider_checksum=provider_checksum,
            stored_at=occurred_at,
        )

    async def mark_failed(
        self,
        *,
        intent: AttachmentUploadIntent,
        failure_code: str,
        occurred_at: datetime,
    ) -> AttachmentUploadIntent:
        return replace(
            intent,
            state="FAILED",
            failure_code=failure_code,
            failed_at=occurred_at,
        )

    async def finalize(
        self,
        *,
        intent: AttachmentUploadIntent,
        expected_change_request_version: int,
        occurred_at: datetime,
    ) -> FinalizedAttachment:
        assert expected_change_request_version == 1
        self.finalize_calls += 1
        return FinalizedAttachment(
            id=intent.attachment_id,
            kind=intent.kind,
            round_id=intent.round_id,
            original_name=intent.original_name,
            serial_number=intent.serial_number,
            content_type=intent.content_type,
            size_bytes=cast(int, intent.size_bytes),
            content_sha256=cast(str, intent.content_sha256),
            created_at=occurred_at,
        )

    async def list_reconcilable(self, **values: object) -> tuple[AttachmentUploadIntent, ...]:
        self.list_calls.append(values)
        return () if self.existing is None else (self.existing,)


def _subject(workspace_id: UUID) -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=uuid4(),
        groups=frozenset({"data-stewards"}),
        job_function="DATA_STEWARD",
        clearance=Classification.CONFIDENTIAL,
        allowed_system_ids=frozenset(),
        allowed_domain_ids=frozenset(),
        allowed_actions=frozenset({Action.CHANGE_EDIT, Action.CHANGE_REVIEW}),
        denied_actions=frozenset(),
        authentication_time=datetime.now(UTC),
        authentication_assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
    )


def _change_request(
    *,
    workspace_id: UUID,
    state: ChangeState = ChangeState.REGISTERED,
    classification: Classification = Classification.INTERNAL,
    system_id: UUID | None = None,
) -> ChangeRequest:
    item = SimpleNamespace(
        target_classification=classification,
        target_owner_department_id=None,
        routing_system_id=system_id,
        target_system_id=system_id,
        target_domain_id=None,
        target_asset_id=uuid4(),
    )
    value = SimpleNamespace(
        change_request_id=uuid4(),
        workspace_id=workspace_id,
        requester_id=uuid4(),
        classification=classification,
        state=state,
        version=1,
        items=(item,),
        current_round_id=uuid4(),
        required_system_ids=lambda: frozenset() if system_id is None else frozenset({system_id}),
    )
    return cast(ChangeRequest, value)


def _service(
    *,
    change_request: ChangeRequest,
    current_subject: SubjectAttributes,
    refreshed_subject: SubjectAttributes | None = None,
    target_allowed: bool = True,
    target_system_id: UUID | None = None,
    authorities: tuple[ApprovalAuthority, ...] = (),
    existing: AttachmentUploadIntent | None = None,
    subject_error: Exception | None = None,
    refresh_error: Exception | None = None,
) -> tuple[GovernanceAttachmentUploadService, _IntentStore, _UnitOfWork]:
    uow = _UnitOfWork(change_request, authorities=authorities)
    store = _IntentStore(
        current_subject,
        refreshed_subject=refreshed_subject,
        existing=existing,
        subject_error=subject_error,
        refresh_error=refresh_error,
    )
    target_authorizer = _TargetAuthorizer(
        allowed=target_allowed,
        required_system_id=target_system_id,
        events=store.events,
    )
    store.target_subjects = target_authorizer.subjects
    service = GovernanceAttachmentUploadService(
        cast(Callable[[], GovernanceUnitOfWork], lambda: uow),
        AuthorizationService(decision_writer=_DecisionWriter()),
        store=store,
        target_authorizer=target_authorizer,
    )
    return service, store, uow


async def _start(
    service: GovernanceAttachmentUploadService,
    *,
    change_request: ChangeRequest,
    subject: SubjectAttributes,
) -> AttachmentUploadIntent:
    attachment_id = uuid4()
    return await service.start(
        attachment_id=attachment_id,
        workspace_id=change_request.workspace_id,
        change_request_id=change_request.change_request_id,
        kind="REQUEST",
        original_name="evidence.csv",
        bucket="datariver-filefolder",
        object_key=(
            f"governance/change-request-attachments/{change_request.workspace_id}/"
            f"{change_request.change_request_id}/{attachment_id}"
        ),
        content_type="text/csv",
        expected_size_bytes=17,
        expected_content_sha256="a" * 64,
        subject=subject,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="attachment-start",
    )


@pytest.mark.asyncio
async def test_started_intent_is_precommitted_after_current_authorization_locks() -> None:
    workspace_id = uuid4()
    caller = _subject(workspace_id)
    request = _change_request(workspace_id=workspace_id)
    service, store, uow = _service(
        change_request=request,
        current_subject=caller,
    )

    intent = await _start(service, change_request=request, subject=caller)

    assert intent.state == "STARTED"
    assert store.dependencies_locked == 1
    assert store.started == [intent]
    assert uow.flush_calls == 1
    assert uow.commit_calls == 1


@pytest.mark.asyncio
async def test_effective_profile_and_system_scope_are_refreshed_after_dependency_locks() -> None:
    workspace_id = uuid4()
    system_id = uuid4()
    caller = _subject(workspace_id)
    effective = replace(caller, allowed_system_ids=frozenset({system_id}))
    request = _change_request(workspace_id=workspace_id, system_id=system_id)
    service, store, uow = _service(
        change_request=request,
        current_subject=caller,
        refreshed_subject=effective,
        target_system_id=system_id,
    )

    intent = await _start(service, change_request=request, subject=caller)

    assert intent.state == "STARTED"
    assert store.target_subjects == [effective]
    assert store.refresh_calls == [
        {
            "subject": caller,
            "observed_at": store.refresh_calls[0]["observed_at"],
        }
    ]
    assert store.events == [
        "lock_current_subject",
        "lock_authorization_dependencies",
        "refresh_effective_subject",
        "target_authorize",
        "add_started",
    ]
    assert uow.commit_calls == 1


@pytest.mark.asyncio
async def test_refreshed_profile_revocation_blocks_intent_before_object_write() -> None:
    workspace_id = uuid4()
    caller = _subject(workspace_id)
    revoked = replace(
        caller,
        allowed_actions=frozenset(),
        denied_actions=frozenset({Action.CHANGE_EDIT}),
    )
    request = _change_request(workspace_id=workspace_id)
    service, store, uow = _service(
        change_request=request,
        current_subject=caller,
        refreshed_subject=revoked,
    )

    with pytest.raises(ForbiddenError):
        await _start(service, change_request=request, subject=caller)

    assert store.events == [
        "lock_current_subject",
        "lock_authorization_dependencies",
        "refresh_effective_subject",
    ]
    assert store.started == []
    assert uow.commit_calls == 0


@pytest.mark.asyncio
async def test_refreshed_responsibility_revocation_blocks_intent_before_object_write() -> None:
    workspace_id = uuid4()
    system_id = uuid4()
    caller = replace(
        _subject(workspace_id),
        allowed_system_ids=frozenset({system_id}),
    )
    revoked = replace(caller, allowed_system_ids=frozenset())
    request = _change_request(workspace_id=workspace_id, system_id=system_id)
    service, store, uow = _service(
        change_request=request,
        current_subject=caller,
        refreshed_subject=revoked,
        target_system_id=system_id,
    )

    with pytest.raises(ForbiddenError):
        await _start(service, change_request=request, subject=caller)

    assert store.target_subjects == []
    assert store.events == [
        "lock_current_subject",
        "lock_authorization_dependencies",
        "refresh_effective_subject",
    ]
    assert store.started == []
    assert uow.commit_calls == 0


@pytest.mark.asyncio
async def test_current_round_stored_recovery_filters_before_the_bounded_store_limit() -> None:
    workspace_id = uuid4()
    caller = _subject(workspace_id)
    request = _change_request(workspace_id=workspace_id)
    service, store, uow = _service(
        change_request=request,
        current_subject=caller,
    )

    values = await service.list_reconcilable(
        workspace_id=workspace_id,
        subject_id=caller.subject_id,
        change_request_id=request.change_request_id,
        round_id=request.current_round_id,
        states=frozenset({"STORED"}),
        before_or_at=datetime.now(UTC),
        limit=10,
    )

    assert values == ()
    assert store.list_calls == [
        {
            "workspace_id": workspace_id,
            "change_request_id": request.change_request_id,
            "round_id": request.current_round_id,
            "states": frozenset({"STORED"}),
            "before_or_at": store.list_calls[0]["before_or_at"],
            "limit": 10,
        }
    ]
    assert uow.commit_calls == 1


@pytest.mark.asyncio
async def test_upload_intent_read_is_subject_and_workspace_scoped() -> None:
    workspace_id = uuid4()
    caller = _subject(workspace_id)
    request = _change_request(workspace_id=workspace_id)
    intent = AttachmentUploadIntent(
        attachment_id=uuid4(),
        workspace_id=workspace_id,
        change_request_id=request.change_request_id,
        round_id=request.current_round_id,
        kind="REQUEST",
        original_name="evidence.csv",
        serial_number=1,
        bucket="datariver-filefolder",
        object_key=f"attachment/{uuid4()}",
        content_type="text/csv",
        expected_size_bytes=17,
        expected_content_sha256="a" * 64,
        uploaded_by=caller.subject_id,
        state="STARTED",
    )
    service, store, uow = _service(
        change_request=request,
        current_subject=caller,
        existing=intent,
    )

    observed = await service.get_upload_intent(
        workspace_id=workspace_id,
        attachment_id=intent.attachment_id,
        subject_id=caller.subject_id,
    )

    assert observed == intent
    assert store.get_calls == [
        {"workspace_id": workspace_id, "attachment_id": intent.attachment_id}
    ]
    assert uow.commit_calls == 1

    with pytest.raises(NotFoundError):
        await service.get_upload_intent(
            workspace_id=workspace_id,
            attachment_id=intent.attachment_id,
            subject_id=uuid4(),
        )
    with pytest.raises(NotFoundError):
        await service.get_upload_intent(
            workspace_id=uuid4(),
            attachment_id=intent.attachment_id,
            subject_id=caller.subject_id,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "current_subject",
    [
        lambda actor: replace(actor, active=False),
        lambda actor: replace(
            actor,
            allowed_actions=frozenset(),
            denied_actions=frozenset({Action.CHANGE_EDIT}),
        ),
        lambda actor: replace(actor, clearance=Classification.PUBLIC),
    ],
)
async def test_membership_role_or_classification_revocation_blocks_intent_before_object_write(
    current_subject: Callable[[SubjectAttributes], SubjectAttributes],
) -> None:
    workspace_id = uuid4()
    stale_caller = _subject(workspace_id)
    request = _change_request(
        workspace_id=workspace_id,
        classification=Classification.INTERNAL,
    )
    service, store, uow = _service(
        change_request=request,
        current_subject=current_subject(stale_caller),
    )

    with pytest.raises(ForbiddenError):
        await _start(service, change_request=request, subject=stale_caller)

    assert store.started == []
    assert uow.commit_calls == 0


@pytest.mark.asyncio
async def test_deleted_membership_or_target_binding_revocation_blocks_started_intent() -> None:
    workspace_id = uuid4()
    stale_caller = _subject(workspace_id)
    request = _change_request(workspace_id=workspace_id)
    for options in (
        {
            "subject_error": ConflictError(
                "The current workspace membership no longer exists.",
                details={"code": "ATTACHMENT_AUTHORIZATION_REVOKED"},
            )
        },
        {"target_allowed": False},
    ):
        service, store, uow = _service(
            change_request=request,
            current_subject=stale_caller,
            **options,
        )

        with pytest.raises((ConflictError, ForbiddenError)):
            await _start(service, change_request=request, subject=stale_caller)

        assert store.started == []
        assert uow.commit_calls == 0


@pytest.mark.asyncio
async def test_system_assignment_revocation_blocks_test_intent() -> None:
    workspace_id = uuid4()
    system_id = uuid4()
    stale_caller = replace(
        _subject(workspace_id),
        allowed_system_ids=frozenset({system_id}),
    )
    request = _change_request(
        workspace_id=workspace_id,
        state=ChangeState.TESTING,
        system_id=system_id,
    )
    service, store, uow = _service(
        change_request=request,
        current_subject=stale_caller,
        authorities=(),
    )

    with pytest.raises(ForbiddenError, match="Developer assignment"):
        await service.start(
            attachment_id=uuid4(),
            workspace_id=workspace_id,
            change_request_id=request.change_request_id,
            kind="TEST",
            original_name="test.txt",
            bucket="datariver-filefolder",
            object_key=f"attachment/{uuid4()}",
            content_type="text/plain",
            expected_size_bytes=4,
            expected_content_sha256="b" * 64,
            subject=stale_caller,
            environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
            request_id="test-assignment-revoked",
        )

    assert store.started == []
    assert uow.commit_calls == 0


@pytest.mark.asyncio
async def test_finalization_reauthorizes_and_leaves_stored_intent_after_revocation() -> None:
    workspace_id = uuid4()
    stale_caller = _subject(workspace_id)
    request = _change_request(workspace_id=workspace_id)
    stored = AttachmentUploadIntent(
        attachment_id=uuid4(),
        workspace_id=workspace_id,
        change_request_id=request.change_request_id,
        round_id=request.current_round_id,
        kind="REQUEST",
        original_name="evidence.csv",
        serial_number=1,
        bucket="datariver-filefolder",
        object_key=f"attachment/{uuid4()}",
        content_type="text/csv",
        expected_size_bytes=17,
        expected_content_sha256="a" * 64,
        uploaded_by=stale_caller.subject_id,
        state="STORED",
        size_bytes=17,
        content_sha256="a" * 64,
        provider_checksum="etag:evidence",
        stored_at=datetime.now(UTC),
    )
    service, store, uow = _service(
        change_request=request,
        current_subject=replace(stale_caller, active=False),
        existing=stored,
    )

    with pytest.raises(ForbiddenError):
        await service.finalize(
            workspace_id=workspace_id,
            change_request_id=request.change_request_id,
            attachment_id=stored.attachment_id,
            subject=stale_caller,
            environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
            request_id="attachment-finalize-revoked",
            occurred_at=datetime.now(UTC),
        )

    assert store.finalize_calls == 0
    assert uow.commit_calls == 0


@pytest.mark.asyncio
async def test_finalization_response_loss_can_replay_after_current_reauthorization() -> None:
    workspace_id = uuid4()
    caller = _subject(workspace_id)
    request = _change_request(workspace_id=workspace_id)
    finalized = AttachmentUploadIntent(
        attachment_id=uuid4(),
        workspace_id=workspace_id,
        change_request_id=request.change_request_id,
        round_id=request.current_round_id,
        kind="REQUEST",
        original_name="evidence.csv",
        serial_number=1,
        bucket="datariver-filefolder",
        object_key=f"attachment/{uuid4()}",
        content_type="text/csv",
        expected_size_bytes=17,
        expected_content_sha256="a" * 64,
        uploaded_by=caller.subject_id,
        state="FINALIZED",
        size_bytes=17,
        content_sha256="a" * 64,
        provider_checksum="etag:evidence",
        stored_at=datetime.now(UTC),
        finalized_at=datetime.now(UTC),
    )
    service, store, uow = _service(
        change_request=request,
        current_subject=caller,
        existing=finalized,
    )

    result = await service.finalize(
        workspace_id=workspace_id,
        change_request_id=request.change_request_id,
        attachment_id=finalized.attachment_id,
        subject=caller,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="attachment-finalize-replay",
        occurred_at=datetime.now(UTC),
    )

    assert result.id == finalized.attachment_id
    assert store.finalize_calls == 1
    assert uow.commit_calls == 1


class _ReconciliationStore:
    def __init__(self, intent: AttachmentUploadIntent | None) -> None:
        self.intent = intent
        self.attestations: list[dict[str, object]] = []
        self.deferred: list[UUID] = []

    async def next_started(self, **_: object) -> AttachmentUploadIntent | None:
        return self.intent

    async def attest_stored(self, **values: object) -> None:
        self.attestations.append(values)

    async def defer(self, *, intent: AttachmentUploadIntent) -> None:
        self.deferred.append(intent.attachment_id)


class _ReconciliationObjectStore:
    def __init__(
        self,
        *,
        content: bytes,
        metadata: dict[str, str],
    ) -> None:
        self.content = content
        self.metadata = metadata

    async def head_object(self, *, bucket: str, object_key: str) -> ObjectMetadata:
        return ObjectMetadata(
            bucket=bucket,
            object_key=object_key,
            size_bytes=len(self.content),
            content_type="text/csv",
            etag="provider-etag",
            checksum_sha256=None,
            user_metadata=self.metadata,
        )

    async def iter_object_chunks(
        self,
        *,
        bucket: str,
        object_key: str,
        chunk_size: int = 1024 * 1024,
    ) -> AsyncIterator[bytes]:
        del bucket, object_key, chunk_size
        yield self.content


def _started_reconciliation_intent(content: bytes) -> AttachmentUploadIntent:
    workspace_id = uuid4()
    change_request_id = uuid4()
    attachment_id = uuid4()
    import hashlib

    return AttachmentUploadIntent(
        attachment_id=attachment_id,
        workspace_id=workspace_id,
        change_request_id=change_request_id,
        round_id=uuid4(),
        kind="REQUEST",
        original_name="evidence.csv",
        serial_number=1,
        bucket="datariver-filefolder",
        object_key=f"governance/change-request-attachments/{attachment_id}",
        content_type="text/csv",
        expected_size_bytes=len(content),
        expected_content_sha256=hashlib.sha256(content).hexdigest(),
        uploaded_by=uuid4(),
        state="STARTED",
    )


@pytest.mark.asyncio
async def test_attachment_reconciliation_worker_full_reads_provider_before_attestation() -> None:
    content = b"independent provider evidence"
    intent = _started_reconciliation_intent(content)
    metadata = {
        "workspace-id": str(intent.workspace_id),
        "change-request-id": str(intent.change_request_id),
        "attachment-id": str(intent.attachment_id),
        "attachment-kind": intent.kind,
        "content-sha256": intent.expected_content_sha256,
    }
    store = _ReconciliationStore(intent)
    worker = AttachmentReconciliationWorker(
        store=store,
        object_store=_ReconciliationObjectStore(content=content, metadata=metadata),
    )

    assert await worker.run_once() is True

    assert len(store.attestations) == 1
    assert store.attestations[0]["intent"] == intent
    assert store.attestations[0]["size_bytes"] == len(content)
    assert store.attestations[0]["content_sha256"] == intent.expected_content_sha256
    assert store.attestations[0]["provider_checksum"] == "etag:provider-etag"
    assert store.deferred == []


@pytest.mark.asyncio
async def test_attachment_reconciliation_worker_defers_mismatched_provider_object() -> None:
    content = b"expected"
    intent = _started_reconciliation_intent(content)
    metadata = {
        "workspace-id": str(intent.workspace_id),
        "change-request-id": str(intent.change_request_id),
        "attachment-id": str(intent.attachment_id),
        "attachment-kind": intent.kind,
        "content-sha256": "f" * 64,
    }
    store = _ReconciliationStore(intent)
    worker = AttachmentReconciliationWorker(
        store=store,
        object_store=_ReconciliationObjectStore(content=b"tampered", metadata=metadata),
    )

    assert await worker.run_once() is True

    assert store.attestations == []
    assert store.deferred == [intent.attachment_id]
