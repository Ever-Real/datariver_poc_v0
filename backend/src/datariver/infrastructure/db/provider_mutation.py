from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from datariver.domain.common import canonical_json_hash


class SqlProviderMutationLock:
    """Serialize one DataRiver-owned provider target/aspect mutation.

    The session advisory lock uses a dedicated pooled connection. The acquisition transaction is
    committed before yielding, so provider latency never creates an idle database transaction.
    Connection loss releases the lock automatically; a hash collision only over-serializes work.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @asynccontextmanager
    async def hold(
        self,
        *,
        workspace_id: UUID,
        provider: str,
        target_ref: str,
        aspect_name: str,
        on_wait: Callable[[], Awaitable[None]] | None = None,
    ) -> AsyncIterator[None]:
        del workspace_id
        identity = canonical_json_hash(
            {
                "aspect_name": aspect_name,
                "provider": provider,
                "target_ref": target_ref,
            }
        )
        connection: AsyncConnection | None = None
        while connection is None:
            try:
                connection = await self._engine.connect()
            except SQLAlchemyTimeoutError:
                if on_wait is not None:
                    await on_wait()
        try:
            acquired = False
            while not acquired:
                try:
                    acquired = (
                        await connection.scalar(
                            select(func.pg_try_advisory_lock(func.hashtextextended(identity, 0)))
                        )
                        is True
                    )
                    await connection.commit()
                except BaseException:
                    # Cancellation or a connection error can arrive after PostgreSQL acquired the
                    # session lock but before the result/commit becomes observable. Pool check-in
                    # does not release session advisory locks, so destroy the physical backend.
                    await asyncio.shield(connection.invalidate())
                    raise
                if not acquired:
                    if on_wait is not None:
                        await on_wait()
                    await asyncio.sleep(0.1)
            owner_task = asyncio.current_task()
            if owner_task is None:  # pragma: no cover - asyncio always owns application tasks
                await connection.invalidate()
                raise RuntimeError("The provider mutation lock has no owning task.")

            ownership_lost = asyncio.Event()

            async def monitor_ownership() -> None:
                try:
                    while True:
                        await asyncio.sleep(0.25)
                        still_owned = await connection.scalar(
                            text(
                                """
                                SELECT EXISTS (
                                    SELECT 1
                                    FROM pg_catalog.pg_locks
                                    WHERE locktype = 'advisory'
                                      AND pid = pg_catalog.pg_backend_pid()
                                      AND classid = (
                                          (
                                              pg_catalog.hashtextextended(:identity, 0) >> 32
                                          ) & 4294967295
                                      )::oid
                                      AND objid = (
                                          pg_catalog.hashtextextended(:identity, 0)
                                          & 4294967295
                                      )::oid
                                      AND objsubid = 1
                                      AND granted IS TRUE
                                )
                                """
                            ),
                            {"identity": identity},
                        )
                        if still_owned is not True:
                            raise RuntimeError("The PostgreSQL provider mutation lock was lost.")
                except asyncio.CancelledError:
                    raise
                except BaseException:
                    # Stop the owner at its next await before it can continue a provider workflow
                    # under mutation authority that PostgreSQL has already released.
                    ownership_lost.set()
                    owner_task.cancel()

            monitor_task = asyncio.create_task(monitor_ownership())
            try:
                yield
            finally:
                monitor_task.cancel()
                await asyncio.gather(monitor_task, return_exceptions=True)

                async def release() -> bool:
                    released = await connection.scalar(
                        select(func.pg_advisory_unlock(func.hashtextextended(identity, 0)))
                    )
                    await connection.commit()
                    return released is True

                if ownership_lost.is_set():
                    await asyncio.shield(connection.invalidate())
                else:
                    release_task = asyncio.create_task(release())
                    try:
                        released = await asyncio.shield(release_task)
                    except asyncio.CancelledError:
                        try:
                            released = await release_task
                        except BaseException:
                            await asyncio.shield(connection.invalidate())
                            raise
                        if not released:
                            await asyncio.shield(connection.invalidate())
                        raise
                    except BaseException:
                        await asyncio.shield(connection.invalidate())
                        raise
                    if not released:
                        await connection.invalidate()
                        raise RuntimeError("PostgreSQL did not release the provider mutation lock.")
        finally:
            await connection.close()
