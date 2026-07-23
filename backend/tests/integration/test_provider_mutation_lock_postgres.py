from __future__ import annotations

import asyncio
import os
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from datariver.infrastructure.db.provider_mutation import SqlProviderMutationLock
from datariver.infrastructure.secrets import SecretResolver

_DATABASE_URL_ENV = "DATARIVER_REGISTRATION_RLS_TEST_DATABASE_URL"
_SECRET_REF_ENV = "DATARIVER_REGISTRATION_RLS_TEST_DATABASE_SECRET_REF"
_CONFIRM_ISOLATED_ENV = "DATARIVER_REGISTRATION_RLS_TEST_CONFIRM_ISOLATED"
_POSTGRES_ENABLED = bool(os.getenv(_DATABASE_URL_ENV)) and os.getenv(_CONFIRM_ISOLATED_ENV) == "1"


def _engine(*, application_name: str) -> AsyncEngine:
    return create_async_engine(
        os.environ[_DATABASE_URL_ENV],
        connect_args={
            "password": SecretResolver().resolve(
                os.getenv(_SECRET_REF_ENV, "file:/run/secrets/postgres_password")
            ),
            "server_settings": {"application_name": application_name},
        },
    )


@pytest.mark.skipif(not _POSTGRES_ENABLED, reason="isolated PostgreSQL evidence is not configured")
@pytest.mark.asyncio
async def test_provider_lock_serializes_without_idle_transaction() -> None:
    application_name = f"datariver-provider-lock-{uuid4().hex}"
    engine = _engine(application_name=application_name)
    observer = _engine(application_name=f"{application_name}-observer")
    first = SqlProviderMutationLock(engine)
    second = SqlProviderMutationLock(engine)
    workspace_id = uuid4()
    other_workspace_id = uuid4()
    provider = "DATAHUB"
    target_ref = "urn:li:dataset:test"
    aspect_name = "datasetProperties"
    second_entered = asyncio.Event()
    wait_heartbeats = 0

    async def contend_from_other_workspace() -> None:
        async def heartbeat() -> None:
            nonlocal wait_heartbeats
            wait_heartbeats += 1

        async with second.hold(
            workspace_id=other_workspace_id,
            provider=provider,
            target_ref=target_ref,
            aspect_name=aspect_name,
            on_wait=heartbeat,
        ):
            second_entered.set()

    try:
        async with first.hold(
            workspace_id=workspace_id,
            provider=provider,
            target_ref=target_ref,
            aspect_name=aspect_name,
        ):
            async with observer.connect() as connection:
                states = tuple(
                    (
                        await connection.execute(
                            text(
                                "SELECT state FROM pg_stat_activity "
                                "WHERE application_name = :application_name"
                            ),
                            {"application_name": application_name},
                        )
                    ).scalars()
                )
            assert states == ("idle",)
            contender = asyncio.create_task(contend_from_other_workspace())
            await asyncio.sleep(0.2)
            assert not second_entered.is_set()

        await asyncio.wait_for(contender, timeout=2)
        assert second_entered.is_set()
        assert wait_heartbeats > 0
    finally:
        await engine.dispose()
        await observer.dispose()


@pytest.mark.skipif(not _POSTGRES_ENABLED, reason="isolated PostgreSQL evidence is not configured")
@pytest.mark.asyncio
async def test_provider_lock_cancellation_releases_the_pooled_backend() -> None:
    engine = _engine(application_name=f"datariver-provider-cancel-{uuid4().hex}")
    first = SqlProviderMutationLock(engine)
    second = SqlProviderMutationLock(engine)
    workspace_id = uuid4()
    entered = asyncio.Event()

    async def hold_until_cancelled() -> None:
        async with first.hold(
            workspace_id=workspace_id,
            provider="DATAHUB",
            target_ref="urn:li:dataset:cancel-test",
            aspect_name="datasetProperties",
        ):
            entered.set()
            await asyncio.Event().wait()

    try:
        task = asyncio.create_task(hold_until_cancelled())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        async with second.hold(
            workspace_id=uuid4(),
            provider="DATAHUB",
            target_ref="urn:li:dataset:cancel-test",
            aspect_name="datasetProperties",
        ):
            pass
    finally:
        await engine.dispose()


@pytest.mark.skipif(not _POSTGRES_ENABLED, reason="isolated PostgreSQL evidence is not configured")
@pytest.mark.asyncio
async def test_provider_lock_cancellation_during_ambiguous_acquisition_closes_backend() -> None:
    engine = _engine(application_name=f"datariver-provider-acquire-cancel-{uuid4().hex}")
    contender_engine = _engine(
        application_name=f"datariver-provider-acquire-contender-{uuid4().hex}"
    )
    acquired = asyncio.Event()
    workspace_id = uuid4()
    provider = "DATAHUB"
    target_ref = "urn:li:dataset:acquisition-cancel-test"
    aspect_name = "datasetProperties"

    class DelayedConnection:
        def __init__(self, connection: Any) -> None:
            self._connection = connection

        async def scalar(self, statement: Any) -> Any:
            result = await self._connection.scalar(statement)
            if result is True:
                acquired.set()
                await asyncio.Event().wait()
            return result

        async def commit(self) -> None:
            await self._connection.commit()

        async def invalidate(self) -> None:
            await self._connection.invalidate()

        async def close(self) -> None:
            await self._connection.close()

    class DelayedEngine:
        async def connect(self) -> DelayedConnection:
            return DelayedConnection(await engine.connect())

    ambiguous = SqlProviderMutationLock(cast(AsyncEngine, DelayedEngine()))
    contender = SqlProviderMutationLock(contender_engine)

    async def acquire_until_cancelled() -> None:
        async with ambiguous.hold(
            workspace_id=workspace_id,
            provider=provider,
            target_ref=target_ref,
            aspect_name=aspect_name,
        ):
            raise AssertionError("The delayed acquisition must not yield.")

    try:
        task = asyncio.create_task(acquire_until_cancelled())
        await asyncio.wait_for(acquired.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        async with asyncio.timeout(2):
            async with contender.hold(
                workspace_id=uuid4(),
                provider=provider,
                target_ref=target_ref,
                aspect_name=aspect_name,
            ):
                pass
    finally:
        await engine.dispose()
        await contender_engine.dispose()


@pytest.mark.skipif(not _POSTGRES_ENABLED, reason="isolated PostgreSQL evidence is not configured")
@pytest.mark.asyncio
async def test_provider_lock_backend_loss_cancels_owner_before_a_later_effect() -> None:
    application_name = f"datariver-provider-lock-loss-{uuid4().hex}"
    engine = _engine(application_name=application_name)
    observer = _engine(application_name=f"{application_name}-observer")
    contender_engine = _engine(application_name=f"{application_name}-contender")
    first = SqlProviderMutationLock(engine)
    second = SqlProviderMutationLock(contender_engine)
    entered = asyncio.Event()
    cancelled = asyncio.Event()
    provider_effect_reached = False
    workspace_id = uuid4()
    target_ref = "urn:li:dataset:lost-lock-test"

    async def own_until_database_loss() -> None:
        nonlocal provider_effect_reached
        try:
            async with first.hold(
                workspace_id=workspace_id,
                provider="DATAHUB",
                target_ref=target_ref,
                aspect_name="*",
            ):
                entered.set()
                await asyncio.sleep(5)
                provider_effect_reached = True
        except asyncio.CancelledError:
            cancelled.set()
            raise

    try:
        owner = asyncio.create_task(own_until_database_loss())
        await asyncio.wait_for(entered.wait(), timeout=2)
        async with observer.begin() as connection:
            backend_pid = await connection.scalar(
                text(
                    """
                    SELECT pid
                    FROM pg_catalog.pg_stat_activity
                    WHERE application_name = :application_name
                    """
                ),
                {"application_name": application_name},
            )
            assert isinstance(backend_pid, int)
            assert (
                await connection.scalar(
                    text("SELECT pg_catalog.pg_terminate_backend(:backend_pid)"),
                    {"backend_pid": backend_pid},
                )
                is True
            )

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(owner, timeout=2)
        assert cancelled.is_set()
        assert not provider_effect_reached

        async with asyncio.timeout(2):
            async with second.hold(
                workspace_id=uuid4(),
                provider="DATAHUB",
                target_ref=target_ref,
                aspect_name="*",
            ):
                pass
    finally:
        await engine.dispose()
        await observer.dispose()
        await contender_engine.dispose()
