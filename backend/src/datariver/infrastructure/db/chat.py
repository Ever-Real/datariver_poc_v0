from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from types import TracebackType
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.application.dto import ChatEvidence, ChatExchange, ChatRetentionBinding
from datariver.application.ports import ChatPersistenceUnitOfWork, ChatStore
from datariver.domain.common import ConflictError, ForbiddenError, uuid7
from datariver.infrastructure.db.models.assistant import (
    AssistantRunModel,
    ChatMessageModel,
    ChatSessionModel,
    EvidenceCitationModel,
)
from datariver.infrastructure.db.retention import SqlRetentionPolicyRepository
from datariver.infrastructure.db.rls import set_security_context

ACTIVE_RETENTION_BINDING = "ACTIVE_POLICY_V1"


class SqlChatStore(ChatStore):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_exchange(
        self,
        *,
        workspace_id: UUID,
        owner_id: UUID,
        session_id: UUID | None,
        question: str,
        answer: str,
        evidence: Sequence[ChatEvidence],
        policy_decision_id: UUID,
        retention: ChatRetentionBinding,
    ) -> ChatExchange:
        if any(item.workspace_id != workspace_id for item in evidence):
            raise ValueError("Evidence chunks must belong to the exchange workspace.")
        now = retention.binding_basis_at
        if session_id is None:
            session = ChatSessionModel(
                id=uuid7(),
                workspace_id=workspace_id,
                owner_id=owner_id,
                title=question.strip()[:100],
                scope={"mode": "authorized-catalog-and-knowledge-evidence"},
                retention_until=now + timedelta(days=retention.chat_content_days),
                retention_policy_id=retention.policy_id,
                retention_policy_hash=retention.policy_hash,
                retention_basis_at=now,
                retention_binding_version=ACTIVE_RETENTION_BINDING,
                version=1,
            )
            self._session.add(session)
            session_id = session.id
        else:
            existing_session = (
                await self._session.scalars(
                    select(ChatSessionModel)
                    .where(
                        ChatSessionModel.id == session_id,
                        ChatSessionModel.workspace_id == workspace_id,
                        ChatSessionModel.owner_id == owner_id,
                    )
                    .with_for_update()
                )
            ).one_or_none()
            if existing_session is None:
                raise ForbiddenError("The chat session is not available.")
            if (
                existing_session.retention_binding_version != ACTIVE_RETENTION_BINDING
                or existing_session.retention_policy_id != retention.policy_id
                or existing_session.retention_policy_hash != retention.policy_hash
                or existing_session.retention_basis_at is None
                or existing_session.retention_until is None
                or existing_session.retention_until <= now
            ):
                raise ConflictError(
                    "The chat session retention binding is no longer current; start a new session."
                )
            existing_session.version += 1

        request_message_id = uuid7()
        response_message_id = uuid7()
        run_id = uuid7()
        self._session.add_all(
            [
                ChatMessageModel(
                    id=request_message_id,
                    workspace_id=workspace_id,
                    session_id=session_id,
                    actor="USER",
                    content=question,
                    created_at=now,
                ),
                ChatMessageModel(
                    id=response_message_id,
                    workspace_id=workspace_id,
                    session_id=session_id,
                    actor="ASSISTANT",
                    content=answer,
                    created_at=now,
                ),
                AssistantRunModel(
                    id=run_id,
                    workspace_id=workspace_id,
                    session_id=session_id,
                    request_message_id=request_message_id,
                    provider="datariver",
                    model="authorized-evidence-v1",
                    prompt_template_version="catalog-knowledge-evidence-v1",
                    policy_decision_id=policy_decision_id,
                    state="COMPLETED",
                    metrics={"evidence_count": len(evidence), "external_llm_used": False},
                    started_at=now,
                    finished_at=now,
                ),
            ]
        )
        self._session.add_all(
            [
                EvidenceCitationModel(
                    id=uuid7(),
                    workspace_id=workspace_id,
                    run_id=run_id,
                    chunk_id=item.chunk_id,
                    resource_id=item.resource_id,
                    classification=int(item.classification),
                    system_id=item.system_id,
                    domain_id=item.domain_id,
                    owner_department_id=item.owner_department_id,
                    source_type=item.source_type,
                    source_locator=item.source_locator,
                    source_version=item.source_version,
                    content_hash=item.content_hash,
                    effective_from=item.effective_from,
                    effective_until=item.effective_until,
                    extraction_method=item.extraction_method,
                    rank=rank,
                )
                for rank, item in enumerate(evidence, start=1)
            ]
        )
        return ChatExchange(
            session_id=session_id,
            request_message_id=request_message_id,
            response_message_id=response_message_id,
            answer=answer,
            evidence=tuple(evidence),
        )


class SqlChatPersistenceUnitOfWork(ChatPersistenceUnitOfWork):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self.chats: SqlChatStore
        self.retention_policies: SqlRetentionPolicyRepository
        self._committed = False

    async def __aenter__(self) -> SqlChatPersistenceUnitOfWork:
        self._session = self._session_factory()
        self.chats = SqlChatStore(self._session)
        self.retention_policies = SqlRetentionPolicyRepository(self._session)
        self._committed = False
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

    async def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await self._session.commit()
        self._committed = True

    async def rollback(self) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await self._session.rollback()

    async def lock_retention_workspace(self, *, workspace_id: UUID) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"datariver:retention:workspace:{workspace_id}"},
        )

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await set_security_context(self._session, workspace_id=workspace_id, subject_id=subject_id)

    async def transaction_time(self) -> datetime:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        value = await self._session.scalar(text("SELECT transaction_timestamp()"))
        if not isinstance(value, datetime):
            raise RuntimeError("Database transaction time is unavailable.")
        return value
