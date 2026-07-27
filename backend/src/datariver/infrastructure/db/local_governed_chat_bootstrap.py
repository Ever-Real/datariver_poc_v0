from __future__ import annotations

from types import TracebackType
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.infrastructure.db.admin_access import SqlMembershipAccessRepository
from datariver.infrastructure.db.classification_access import (
    SqlClassificationPolicyRepository,
)
from datariver.infrastructure.db.governance import SqlOutboxWriter
from datariver.infrastructure.db.inference import SqlInferenceProviderProfileRepository
from datariver.infrastructure.db.retention import SqlRetentionPolicyRepository
from datariver.infrastructure.db.rls import set_security_context


class SqlLocalGovernedChatBootstrapUnitOfWork:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._committed = False

    async def __aenter__(self) -> SqlLocalGovernedChatBootstrapUnitOfWork:
        self._session = self._session_factory()
        self.profiles = SqlInferenceProviderProfileRepository(self._session)
        self.classification_policies = SqlClassificationPolicyRepository(self._session)
        self.retention_policies = SqlRetentionPolicyRepository(self._session)
        self.memberships = SqlMembershipAccessRepository(self._session)
        self.outbox = SqlOutboxWriter(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_value, traceback
        if self._session is None:
            return
        if exc_type is not None or not self._committed:
            await self._session.rollback()
        await self._session.close()

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await set_security_context(
            self._session,
            workspace_id=workspace_id,
            subject_id=subject_id,
        )

    async def lock_workspace(self, *, workspace_id: UUID) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"datariver:local-governed-chat:{workspace_id}"},
        )

    async def flush(self) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await self._session.flush()

    async def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await self._session.commit()
        self._committed = True
