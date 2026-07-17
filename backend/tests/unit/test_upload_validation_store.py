from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.domain.authz import Classification
from datariver.domain.registration import UploadManifest, UploadState
from datariver.infrastructure.db.models.integration import ObjectManifestModel
from datariver.infrastructure.db.registration import (
    SqlUploadCompletionStore,
    SqlUploadValidationStore,
)


class _Transaction:
    def __init__(self, session: _Session) -> None:
        self._session = session

    async def __aenter__(self) -> None:
        self._session.events.append("transaction-enter")

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> None:
        del exc_value, traceback
        self._session.events.append("rollback" if exc_type else "commit")


class _Session:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.outbox_events: list[object] = []

    async def __aenter__(self) -> _Session:
        self.events.append("session-enter")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> None:
        del exc_type, exc_value, traceback
        self.events.append("session-exit")

    def begin(self) -> _Transaction:
        return _Transaction(self)

    def add_all(self, values: list[object]) -> None:
        self.outbox_events.extend(values)


def _manifest(*, version: int = 2) -> UploadManifest:
    return UploadManifest(
        upload_id=uuid4(),
        workspace_id=uuid4(),
        owner_id=uuid4(),
        bucket="quarantine",
        object_key="object",
        display_name="assets.csv",
        declared_size_bytes=10,
        declared_mime="text/csv",
        declared_sha256="a" * 64,
        classification=Classification.INTERNAL,
        multipart_upload_id="multipart",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        state=UploadState.VALIDATING,
        version=version,
        validation_attempts=1,
    )


def _model(manifest: UploadManifest, *, version: int | None = None) -> ObjectManifestModel:
    return ObjectManifestModel(
        id=manifest.upload_id,
        workspace_id=manifest.workspace_id,
        bucket=manifest.bucket,
        object_key=manifest.object_key,
        display_name=manifest.display_name,
        multipart_upload_id=manifest.multipart_upload_id,
        size_bytes=manifest.declared_size_bytes,
        mime=manifest.declared_mime,
        sha256=manifest.declared_sha256,
        actual_size_bytes=manifest.declared_size_bytes,
        actual_mime=manifest.declared_mime,
        actual_sha256=manifest.declared_sha256,
        processing_lease_until=datetime.now(UTC) + timedelta(minutes=1),
        processing_attempts=0,
        validation_attempts=manifest.validation_attempts,
        last_error_code=None,
        validation_summary={},
        completion_parts=[],
        state=manifest.state.value,
        content_profile=manifest.content_profile.value,
        classification=int(manifest.classification),
        owner_id=manifest.owner_id,
        retention_until=None,
        expires_at=manifest.expires_at,
        version=manifest.version if version is None else version,
    )


def _store(session: _Session) -> SqlUploadValidationStore:
    factory = cast(async_sessionmaker[AsyncSession], lambda: session)
    return SqlUploadValidationStore(factory)


@pytest.mark.asyncio
async def test_mark_accepted_returns_true_only_after_transaction_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest()
    model = _model(manifest)
    session = _Session()

    async def locked(_session: AsyncSession, _manifest: UploadManifest) -> ObjectManifestModel:
        del _session, _manifest
        return model

    monkeypatch.setattr(SqlUploadCompletionStore, "_locked", staticmethod(locked))

    committed = await _store(session).mark_accepted(
        manifest=manifest,
        accepted_bucket="accepted",
        accepted_object_key="accepted-object",
        validation_summary={"sha256": manifest.declared_sha256},
    )

    assert committed is True
    assert session.events == ["session-enter", "transaction-enter", "commit", "session-exit"]
    assert model.state == UploadState.ACCEPTED.value
    assert model.version == manifest.version + 1
    assert len(session.outbox_events) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [False, True])
async def test_mark_accepted_returns_false_for_stale_or_missing_manifest(
    monkeypatch: pytest.MonkeyPatch, missing: bool
) -> None:
    manifest = _manifest()
    model = None if missing else _model(manifest, version=manifest.version + 1)
    session = _Session()

    async def locked(
        _session: AsyncSession, _manifest: UploadManifest
    ) -> ObjectManifestModel | None:
        del _session, _manifest
        return model

    monkeypatch.setattr(SqlUploadCompletionStore, "_locked", staticmethod(locked))

    committed = await _store(session).mark_accepted(
        manifest=manifest,
        accepted_bucket="accepted",
        accepted_object_key="accepted-object",
        validation_summary={"sha256": manifest.declared_sha256},
    )

    assert committed is False
    assert session.events == ["session-enter", "transaction-enter", "commit", "session-exit"]
    assert session.outbox_events == []
    if model is not None:
        assert model.state == UploadState.VALIDATING.value
        assert model.version == manifest.version + 1
