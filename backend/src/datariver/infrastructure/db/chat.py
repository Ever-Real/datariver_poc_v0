from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.dto import ChatEvidence, ChatExchange
from datariver.application.ports import ChatStore
from datariver.domain.common import ForbiddenError, utc_now, uuid7
from datariver.infrastructure.db.models.assistant import (
    AssistantRunModel,
    ChatMessageModel,
    ChatSessionModel,
    EvidenceCitationModel,
)


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
    ) -> ChatExchange:
        now = utc_now()
        if session_id is None:
            session = ChatSessionModel(
                id=uuid7(),
                workspace_id=workspace_id,
                owner_id=owner_id,
                title=question.strip()[:100],
                scope={"mode": "authorized-catalog-and-knowledge-evidence"},
                retention_until=now + timedelta(days=90),
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
                    resource_id=item.resource_id,
                    source_type=item.source_type,
                    source_locator=item.source_locator,
                    source_version=item.source_version,
                    excerpt_hash=hashlib.sha256(
                        f"{item.name}\n{item.description or ''}".encode()
                    ).hexdigest(),
                    rank=rank,
                )
                for rank, item in enumerate(evidence, start=1)
            ]
        )
        await self._session.commit()
        return ChatExchange(
            session_id=session_id,
            request_message_id=request_message_id,
            response_message_id=response_message_id,
            answer=answer,
            evidence=tuple(evidence),
        )
