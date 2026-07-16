from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.domain.common import utc_now
from datariver.infrastructure.db.models.integration import InboxMessageModel, OutboxEventModel
from datariver.infrastructure.db.rls import set_security_context


@dataclass(frozen=True, slots=True)
class LeasedOutboxEvent:
    event_id: UUID
    event_type: str
    workspace_id: UUID
    aggregate_id: UUID


class SqlOutboxRelayStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def lease_batch(self, *, limit: int, lease_seconds: int) -> tuple[LeasedOutboxEvent, ...]:
        now = utc_now()
        async with self._session_factory() as session, session.begin():
            models = list(
                (
                    await session.scalars(
                        select(OutboxEventModel)
                        .where(
                            OutboxEventModel.published_at.is_(None),
                            OutboxEventModel.dead_lettered_at.is_(None),
                            or_(
                                OutboxEventModel.lease_until.is_(None),
                                OutboxEventModel.lease_until < now,
                            ),
                        )
                        .order_by(OutboxEventModel.created_at)
                        .with_for_update(skip_locked=True)
                        .limit(limit)
                    )
                ).all()
            )
            for model in models:
                model.lease_until = now + timedelta(seconds=lease_seconds)
                model.attempts += 1
            return tuple(
                LeasedOutboxEvent(
                    event_id=model.id,
                    event_type=model.event_type,
                    workspace_id=model.workspace_id,
                    aggregate_id=model.aggregate_id,
                )
                for model in models
            )

    async def mark_published(self, event_id: UUID) -> None:
        async with self._session_factory() as session, session.begin():
            model = await session.get(OutboxEventModel, event_id, with_for_update=True)
            if model is None or model.published_at is not None:
                return
            model.published_at = utc_now()
            model.lease_until = None

    async def mark_failed(self, event_id: UUID, *, error_code: str, maximum_attempts: int) -> None:
        async with self._session_factory() as session, session.begin():
            model = await session.get(OutboxEventModel, event_id, with_for_update=True)
            if (
                model is None
                or model.published_at is not None
                or model.dead_lettered_at is not None
            ):
                return
            model.last_error_code = error_code[:100]
            model.lease_until = None
            if model.attempts >= maximum_attempts:
                model.dead_lettered_at = utc_now()


class SqlInboxStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def accept(self, *, consumer: str, event_id: UUID, workspace_id: UUID) -> bool:
        async with self._session_factory() as session, session.begin():
            await set_security_context(session, workspace_id=workspace_id, subject_id=None)
            existing = await session.get(InboxMessageModel, (consumer, event_id))
            if existing is not None:
                return existing.completed_at is None
            session.add(
                InboxMessageModel(
                    consumer=consumer,
                    event_id=event_id,
                    workspace_id=workspace_id,
                    received_at=utc_now(),
                )
            )
            return True

    async def complete(
        self, *, consumer: str, event_id: UUID, workspace_id: UUID, result_hash: str
    ) -> None:
        async with self._session_factory() as session, session.begin():
            await set_security_context(session, workspace_id=workspace_id, subject_id=None)
            message = await session.get(
                InboxMessageModel, (consumer, event_id), with_for_update=True
            )
            if message is None:
                return
            message.completed_at = utc_now()
            message.result_hash = result_hash
