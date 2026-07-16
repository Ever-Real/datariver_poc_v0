from __future__ import annotations

from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.infrastructure.db import inference_uow
from datariver.infrastructure.db.admin_access import SqlMembershipAccessRepository
from datariver.infrastructure.db.governance import SqlIdempotencyStore, SqlOutboxWriter
from datariver.infrastructure.db.inference import SqlInferenceProviderProfileRepository
from datariver.infrastructure.db.inference_uow import SqlInferenceAdminUnitOfWork


class _Session:
    def __init__(self) -> None:
        self.executions: list[tuple[object, object | None]] = []
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    async def execute(self, statement: object, parameters: object | None = None) -> object:
        self.executions.append((statement, parameters))
        return object()

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def close(self) -> None:
        self.closes += 1


@pytest.mark.asyncio
async def test_uow_wires_repositories_rls_lock_and_external_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session()
    security_contexts: list[tuple[object, object, object]] = []

    async def fake_set_security_context(
        value: object, *, workspace_id: object, subject_id: object
    ) -> None:
        security_contexts.append((value, workspace_id, subject_id))

    monkeypatch.setattr(inference_uow, "set_security_context", fake_set_security_context)
    factory = cast(async_sessionmaker[AsyncSession], lambda: session)
    uow = SqlInferenceAdminUnitOfWork(factory)
    workspace_id, subject_id = uuid4(), uuid4()

    async with uow:
        assert isinstance(uow.profiles, SqlInferenceProviderProfileRepository)
        assert isinstance(uow.memberships, SqlMembershipAccessRepository)
        assert isinstance(uow.outbox, SqlOutboxWriter)
        assert isinstance(uow.idempotency, SqlIdempotencyStore)
        await uow.set_security_context(workspace_id=workspace_id, subject_id=subject_id)
        await uow.lock_workspace(workspace_id=workspace_id)
        await uow.commit()

    assert security_contexts == [(session, workspace_id, subject_id)]
    assert "pg_advisory_xact_lock" in str(session.executions[0][0])
    assert session.executions[0][1] == {
        "lock_key": f"datariver:integration:inference-provider:{workspace_id}"
    }
    assert session.commits == 1
    assert session.rollbacks == 0
    assert session.closes == 1


@pytest.mark.asyncio
async def test_uow_rolls_back_uncommitted_scope() -> None:
    session = _Session()
    factory = cast(async_sessionmaker[AsyncSession], lambda: session)

    async with SqlInferenceAdminUnitOfWork(factory):
        pass

    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.closes == 1
