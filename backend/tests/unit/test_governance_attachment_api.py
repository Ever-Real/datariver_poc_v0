from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import Response, UploadFile
from fastapi.routing import APIRoute
from starlette.datastructures import Headers

from datariver.application.errors import ExternalDependencyError
from datariver.domain.common import ConflictError, ForbiddenError, ValidationError
from datariver.interfaces.http.routes import governance
from datariver.interfaces.http.schemas import (
    ChangeRequestAttachmentListResponse,
    ChangeRequestAttachmentPageResponse,
    ChangeRequestAttachmentUploadListResponse,
    ChangeRequestAttachmentUploadResponse,
)


class _ScalarRows:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows

    def all(self) -> list[SimpleNamespace]:
        return self._rows


class _Session:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = rows
        self.statement: Any | None = None

    async def scalars(self, statement: Any) -> _ScalarRows:
        self.statement = statement
        return _ScalarRows(self.rows)


class _Service:
    async def get_change_request(self, **_: Any) -> SimpleNamespace:
        return SimpleNamespace()


class _AttachmentService:
    def __init__(
        self,
        *,
        start_error: BaseException | None = None,
        finalize_error: BaseException | None = None,
        upload_intents: tuple[SimpleNamespace, ...] = (),
    ) -> None:
        self.start_error = start_error
        self.finalize_error = finalize_error
        self.upload_intents = upload_intents
        self.started: list[dict[str, Any]] = []
        self.stored: list[dict[str, Any]] = []
        self.failed: list[dict[str, Any]] = []
        self.finalized: list[dict[str, Any]] = []
        self.listed: list[dict[str, Any]] = []

    async def start(self, **values: Any) -> SimpleNamespace:
        if self.start_error is not None:
            raise self.start_error
        self.started.append(values)
        return SimpleNamespace(
            attachment_id=values["attachment_id"],
            change_request_id=values["change_request_id"],
            round_id=uuid4(),
            kind=values["kind"],
            original_name=values["original_name"],
            expected_content_sha256=values["expected_content_sha256"],
            expected_size_bytes=values["expected_size_bytes"],
            state="STARTED",
            provider_checksum=None,
            failure_code=None,
        )

    async def record_stored(self, **values: Any) -> SimpleNamespace:
        self.stored.append(values)
        return SimpleNamespace()

    async def record_known_create_rejection(self, **values: Any) -> SimpleNamespace:
        self.failed.append(values)
        return SimpleNamespace()

    async def finalize(self, **values: Any) -> SimpleNamespace:
        if self.finalize_error is not None:
            raise self.finalize_error
        self.finalized.append(values)
        started = self.started[-1]
        stored = self.stored[-1]
        return SimpleNamespace(
            id=started["attachment_id"],
            kind=started["kind"],
            round_id=uuid4(),
            original_name=started["original_name"],
            serial_number=1,
            content_type=started["content_type"],
            size_bytes=stored["size_bytes"],
            content_sha256=stored["content_sha256"],
            created_at=values["occurred_at"],
        )

    async def list_reconcilable(self, **values: Any) -> tuple[SimpleNamespace, ...]:
        self.listed.append(values)
        return self.upload_intents


class _AttachmentStore:
    def __init__(self, *, write_error: BaseException | None = None) -> None:
        self.write_error = write_error
        self.writes: list[dict[str, Any]] = []
        self.deletes: list[dict[str, str]] = []

    async def write_create_only(self, **values: Any) -> SimpleNamespace:
        content = bytearray()
        async for chunk in values["chunks"]:
            content.extend(chunk)
        self.writes.append({**values, "chunks": bytes(content)})
        if self.write_error is not None:
            raise self.write_error
        return SimpleNamespace(
            size_bytes=len(content),
            content_sha256=hashlib.sha256(content).hexdigest(),
            provider_checksum="etag:attachment",
        )

    async def delete_export(self, **values: str) -> None:
        self.deletes.append(values)


def _attachment(
    *,
    created_at: datetime,
    attachment_id: UUID | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=attachment_id or uuid4(),
        kind="REQUEST",
        round_id=uuid4(),
        original_name="evidence.csv",
        serial_number=1,
        content_type="text/csv",
        size_bytes=17,
        content_sha256="a" * 64,
        created_at=created_at,
    )


def _context() -> Any:
    return SimpleNamespace(
        workspace_id=uuid4(),
        subject=SimpleNamespace(subject_id=uuid4()),
        environment=SimpleNamespace(),
        request_id="request-1",
    )


def _request() -> Any:
    return SimpleNamespace()


def _upload(filename: str = "same evidence.csv") -> UploadFile:
    return UploadFile(
        file=BytesIO(b"private attachment"),
        filename=filename,
        headers=Headers({"content-type": "text/csv"}),
    )


@pytest.mark.asyncio
async def test_legacy_attachment_list_returns_more_than_default_page_without_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started_at = datetime(2026, 7, 23, tzinfo=UTC)
    rows = [_attachment(created_at=started_at + timedelta(seconds=index)) for index in range(30)]
    session = _Session(rows)
    context = _context()
    response = Response()
    monkeypatch.setattr(governance, "_service", lambda *_: _Service())

    async def _set_security_context(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(governance, "set_security_context", _set_security_context)

    result = await governance.list_change_request_attachments(
        change_request_id=uuid4(),
        request=_request(),
        response=response,
        context=context,
        session=session,  # type: ignore[arg-type]
    )

    assert len(result.items) == 30
    assert not hasattr(result, "page")
    assert response.headers["Cache-Control"] == "private, no-store"


@pytest.mark.asyncio
async def test_attachment_page_uses_scoped_keyset_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    change_request_id = uuid4()
    started_at = datetime(2026, 7, 23, tzinfo=UTC)
    first_page_rows = [
        _attachment(created_at=started_at + timedelta(seconds=index)) for index in range(3)
    ]
    context = _context()
    monkeypatch.setattr(governance, "_service", lambda *_: _Service())

    async def _set_security_context(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(governance, "set_security_context", _set_security_context)
    first_session = _Session(first_page_rows)

    first = await governance.list_change_request_attachment_page(
        change_request_id=change_request_id,
        request=_request(),
        response=Response(),
        context=context,
        session=first_session,  # type: ignore[arg-type]
        cursor=None,
        limit=2,
    )

    assert len(first.items) == 2
    assert first.page.limit == 2
    assert first.page.next_cursor is not None
    cursor_created_at, cursor_id = governance._parse_attachment_cursor(
        first.page.next_cursor,
        change_request_id=change_request_id,
    )
    assert cursor_created_at == first_page_rows[1].created_at
    assert cursor_id == first_page_rows[1].id

    second_session = _Session([first_page_rows[2]])
    second = await governance.list_change_request_attachment_page(
        change_request_id=change_request_id,
        request=_request(),
        response=Response(),
        context=context,
        session=second_session,  # type: ignore[arg-type]
        cursor=first.page.next_cursor,
        limit=2,
    )

    assert [item.id for item in second.items] == [first_page_rows[2].id]
    assert second.page.next_cursor is None
    assert "change_request_attachments.created_at >" in str(second_session.statement)
    assert "change_request_attachments.id >" in str(second_session.statement)
    with pytest.raises(ValidationError, match="stale or invalid"):
        governance._parse_attachment_cursor(
            first.page.next_cursor,
            change_request_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_legacy_attachment_list_fails_explicitly_above_safe_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started_at = datetime(2026, 7, 23, tzinfo=UTC)
    rows = [
        _attachment(created_at=started_at + timedelta(seconds=index))
        for index in range(governance._MAXIMUM_LEGACY_ATTACHMENTS + 1)
    ]
    session = _Session(rows)
    context = _context()
    monkeypatch.setattr(governance, "_service", lambda *_: _Service())

    async def _set_security_context(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(governance, "set_security_context", _set_security_context)

    with pytest.raises(ValidationError, match="safe list limit"):
        await governance.list_change_request_attachments(
            change_request_id=uuid4(),
            request=_request(),
            response=Response(),
            context=context,
            session=session,  # type: ignore[arg-type]
        )


def test_attachment_routes_publish_legacy_and_additive_page_response_models() -> None:
    routes = [route for route in governance.router.routes if isinstance(route, APIRoute)]
    legacy = next(
        route
        for route in routes
        if route.path == "/change-requests/{change_request_id}/attachments"
        and route.methods == {"GET"}
    )
    page = next(
        route
        for route in routes
        if route.path == "/change-requests/{change_request_id}/attachments/page"
        and route.methods == {"GET"}
    )
    download = next(
        route
        for route in routes
        if route.path == "/change-requests/{change_request_id}/attachments/{attachment_id}/download"
    )

    assert legacy.response_model is ChangeRequestAttachmentListResponse
    assert "page" not in ChangeRequestAttachmentListResponse.model_fields
    assert page.response_model is ChangeRequestAttachmentPageResponse
    assert "page" in ChangeRequestAttachmentPageResponse.model_fields
    assert routes.index(page) < routes.index(download)

    upload = next(
        route
        for route in routes
        if route.path == "/change-requests/{change_request_id}/attachments"
        and route.methods == {"POST"}
    )
    assert upload.response_model is ChangeRequestAttachmentUploadResponse
    assert upload.status_code == 202
    upload_list = next(
        route
        for route in routes
        if route.path == "/change-requests/{change_request_id}/attachment-uploads"
        and route.methods == {"GET"}
    )
    assert upload_list.response_model is ChangeRequestAttachmentUploadListResponse


@pytest.mark.asyncio
async def test_attachment_keys_separate_identical_names_and_numbers_across_workspaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _AttachmentStore()
    container = SimpleNamespace(
        settings=SimpleNamespace(s3_bucket_filefolder="datariver-filefolder"),
        object_store=store,
    )
    monkeypatch.setattr(governance, "get_container", lambda _: container)
    attachment_ids = iter((uuid4(), uuid4()))
    monkeypatch.setattr(governance, "uuid7", lambda: next(attachment_ids))
    expected_identities: list[tuple[UUID, UUID, UUID]] = []

    for _ in range(2):
        workspace_id = uuid4()
        change_request_id = uuid4()
        service = _AttachmentService()
        monkeypatch.setattr(
            governance,
            "_attachment_service",
            lambda *_args, service=service: service,
        )
        context = _context()
        context.workspace_id = workspace_id

        result = await governance.upload_change_request_attachment(
            change_request_id=change_request_id,
            request=_request(),
            context=context,
            session=SimpleNamespace(),  # type: ignore[arg-type]
            file=_upload(),
            kind="REQUEST",
        )
        expected_identities.append((workspace_id, change_request_id, result.id))

    keys = [str(write["object_key"]) for write in store.writes]
    assert len(keys) == 2
    assert keys[0] != keys[1]
    for object_key, identity in zip(keys, expected_identities, strict=True):
        workspace_id, change_request_id, attachment_id = identity
        assert str(workspace_id) in object_key
        assert str(change_request_id) in object_key
        assert str(attachment_id) in object_key
    assert all("same_evidence.csv" not in object_key for object_key in keys)
    assert all("CR-2026-000001" not in object_key for object_key in keys)


@pytest.mark.asyncio
async def test_attachment_authoritative_reauthorization_failure_happens_before_s3_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = uuid4()
    change_request_id = uuid4()
    service = _AttachmentService(
        start_error=ForbiddenError("The current workspace role was revoked.")
    )
    store = _AttachmentStore()
    container = SimpleNamespace(
        settings=SimpleNamespace(s3_bucket_filefolder="datariver-filefolder"),
        object_store=store,
    )
    context = _context()
    context.workspace_id = workspace_id
    monkeypatch.setattr(governance, "get_container", lambda _: container)
    monkeypatch.setattr(
        governance,
        "_attachment_service",
        lambda *_: service,
    )

    with pytest.raises(ForbiddenError, match="role was revoked"):
        await governance.upload_change_request_attachment(
            change_request_id=change_request_id,
            request=_request(),
            context=context,
            session=SimpleNamespace(),  # type: ignore[arg-type]
            file=_upload(),
            kind="REQUEST",
        )

    assert store.writes == []
    assert store.deletes == []
    assert service.started == []
    assert service.stored == []


@pytest.mark.asyncio
async def test_attachment_upload_returns_durable_pending_handoff_without_app_attestation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = uuid4()
    change_request_id = uuid4()
    service = _AttachmentService()
    store = _AttachmentStore()
    container = SimpleNamespace(
        settings=SimpleNamespace(s3_bucket_filefolder="datariver-filefolder"),
        object_store=store,
    )
    context = _context()
    context.workspace_id = workspace_id
    monkeypatch.setattr(governance, "get_container", lambda _: container)
    monkeypatch.setattr(
        governance,
        "_attachment_service",
        lambda *_: service,
    )

    upload_id = uuid4()
    result = await governance.upload_change_request_attachment(
        change_request_id=change_request_id,
        request=_request(),
        context=context,
        session=SimpleNamespace(),  # type: ignore[arg-type]
        file=_upload(),
        kind="REQUEST",
        upload_id=upload_id,
    )

    assert len(store.writes) == 1
    assert len(service.started) == 1
    assert service.stored == []
    assert service.finalized == []
    assert store.deletes == []
    assert result.state == "STARTED"
    assert result.id == upload_id
    assert str(result.id) in result.status_url
    assert str(result.id) in result.finalize_url


@pytest.mark.asyncio
async def test_attachment_upload_list_rediscovers_owner_pending_intent_without_object_coordinates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    change_request_id = uuid4()
    attachment_id = uuid4()
    intent = SimpleNamespace(
        attachment_id=attachment_id,
        change_request_id=change_request_id,
        round_id=uuid4(),
        kind="REQUEST",
        original_name="evidence.csv",
        expected_size_bytes=17,
        expected_content_sha256="a" * 64,
        state="STORED",
        provider_checksum="etag:evidence",
        failure_code=None,
        bucket="private-bucket",
        object_key="private/object/key",
    )
    service = _AttachmentService(upload_intents=(intent,))
    monkeypatch.setattr(governance, "_attachment_service", lambda *_: service)
    response = Response()

    result = await governance.list_change_request_attachment_uploads(
        change_request_id=change_request_id,
        request=_request(),
        response=response,
        context=_context(),
        session=SimpleNamespace(),  # type: ignore[arg-type]
        round_id=intent.round_id,
        limit=10,
    )

    assert [item.id for item in result.items] == [attachment_id]
    assert service.listed[0]["round_id"] == intent.round_id
    assert service.listed[0]["states"] == frozenset({"STORED"})
    assert service.listed[0]["limit"] == 10
    payload = result.model_dump(mode="json")
    assert "private-bucket" not in str(payload)
    assert "private/object/key" not in str(payload)
    assert response.headers["Cache-Control"] == "private, no-store"


@pytest.mark.asyncio
async def test_attachment_known_create_collision_marks_intent_failed_without_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = uuid4()
    change_request_id = uuid4()
    service = _AttachmentService()
    store = _AttachmentStore(
        write_error=ConflictError(
            "The create-only object key already exists.",
            details={"code": "OBJECT_KEY_ALREADY_EXISTS"},
        )
    )
    container = SimpleNamespace(
        settings=SimpleNamespace(s3_bucket_filefolder="datariver-filefolder"),
        object_store=store,
    )
    context = _context()
    context.workspace_id = workspace_id
    monkeypatch.setattr(governance, "get_container", lambda _: container)
    monkeypatch.setattr(
        governance,
        "_attachment_service",
        lambda *_: service,
    )

    with pytest.raises(ConflictError) as captured:
        await governance.upload_change_request_attachment(
            change_request_id=change_request_id,
            request=_request(),
            context=context,
            session=SimpleNamespace(),  # type: ignore[arg-type]
            file=_upload(),
            kind="REQUEST",
        )

    assert captured.value.details == {"code": "OBJECT_KEY_ALREADY_EXISTS"}
    assert len(store.writes) == 1
    assert len(service.started) == 1
    assert len(service.failed) == 1
    assert service.failed[0]["failure_code"] == "OBJECT_KEY_ALREADY_EXISTS"
    assert service.stored == []
    assert store.deletes == []


@pytest.mark.asyncio
async def test_attachment_s3_success_then_head_failure_leaves_started_intent_for_reconcile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _AttachmentService()
    store = _AttachmentStore(
        write_error=ExternalDependencyError(
            "Object HEAD failed after PUT.",
            dependency="object_store",
            retryable=True,
            provider_code="HEAD_FAILED",
        )
    )
    container = SimpleNamespace(
        settings=SimpleNamespace(s3_bucket_filefolder="datariver-filefolder"),
        object_store=store,
    )
    monkeypatch.setattr(governance, "get_container", lambda _: container)
    monkeypatch.setattr(governance, "_attachment_service", lambda *_: service)

    with pytest.raises(ExternalDependencyError, match="HEAD failed"):
        await governance.upload_change_request_attachment(
            change_request_id=uuid4(),
            request=_request(),
            context=_context(),
            session=SimpleNamespace(),  # type: ignore[arg-type]
            file=_upload(),
            kind="REQUEST",
        )

    assert len(store.writes) == 1
    assert len(service.started) == 1
    assert service.stored == []
    assert service.failed == []
    assert store.deletes == []


@pytest.mark.asyncio
async def test_attachment_cancellation_leaves_started_intent_and_never_deletes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _AttachmentService()
    store = _AttachmentStore(write_error=asyncio.CancelledError())
    container = SimpleNamespace(
        settings=SimpleNamespace(s3_bucket_filefolder="datariver-filefolder"),
        object_store=store,
    )
    monkeypatch.setattr(governance, "get_container", lambda _: container)
    monkeypatch.setattr(governance, "_attachment_service", lambda *_: service)

    with pytest.raises(asyncio.CancelledError):
        await governance.upload_change_request_attachment(
            change_request_id=uuid4(),
            request=_request(),
            context=_context(),
            session=SimpleNamespace(),  # type: ignore[arg-type]
            file=_upload(),
            kind="REQUEST",
        )

    assert len(store.writes) == 1
    assert len(service.started) == 1
    assert service.stored == []
    assert store.deletes == []
