from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class Database:
    def __init__(
        self,
        database_url: str,
        *,
        password: str,
        pool_size: int = 10,
        max_overflow: int = 10,
        pool_timeout_seconds: float = 10,
        application_name: str = "datariver-next-api",
    ) -> None:
        self._configured_pool_size = pool_size
        self._configured_max_overflow = max_overflow
        self.engine: AsyncEngine = create_async_engine(
            database_url,
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout_seconds,
            connect_args={
                "password": password,
                "server_settings": {
                    "application_name": application_name,
                    "statement_timeout": "15000",
                    "idle_in_transaction_session_timeout": "30000",
                },
            },
        )
        self.session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
            autoflush=False,
        )

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as session:
            yield session

    async def close(self) -> None:
        await self.engine.dispose()

    def pool_snapshot(self) -> DatabasePoolSnapshot:
        pool = self.engine.sync_engine.pool
        return DatabasePoolSnapshot(
            configured_size=self._configured_pool_size,
            configured_max_overflow=self._configured_max_overflow,
            checked_in=int(pool.checkedin()),  # type: ignore[attr-defined]
            checked_out=int(pool.checkedout()),  # type: ignore[attr-defined]
            overflow=max(0, int(pool.overflow())),  # type: ignore[attr-defined]
        )

    async def readiness(
        self,
        *,
        required_revision: str,
        timeout_seconds: float,
    ) -> DatabaseReadiness:
        """Lease the configured pool and verify the database is at the packaged sole head."""
        try:
            async with asyncio.timeout(timeout_seconds):
                async with self.engine.connect() as connection:
                    revisions = tuple(
                        (
                            await connection.execute(
                                text(
                                    "SELECT version_num FROM public.alembic_version "
                                    "ORDER BY version_num"
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
        except (TimeoutError, SQLAlchemyTimeoutError):
            return DatabaseReadiness(ready=False, code="DATABASE_READINESS_TIMEOUT")
        except SQLAlchemyError:
            return DatabaseReadiness(ready=False, code="DATABASE_UNAVAILABLE")
        if revisions != (required_revision,):
            return DatabaseReadiness(ready=False, code="SCHEMA_REVISION_MISMATCH")
        return DatabaseReadiness(ready=True, code=None)


@dataclass(frozen=True, slots=True)
class DatabaseReadiness:
    ready: bool
    code: str | None


@dataclass(frozen=True, slots=True)
class DatabasePoolSnapshot:
    configured_size: int
    configured_max_overflow: int
    checked_in: int
    checked_out: int
    overflow: int
