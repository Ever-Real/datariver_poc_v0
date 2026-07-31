from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from types import TracebackType
from uuid import UUID

from sqlalchemy import desc, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.application.dto import (
    ChatCompositionAudit,
    ChatEvidence,
    ChatEvidenceRanking,
    ChatExchange,
    ChatMessageRecord,
    ChatRetentionBinding,
    ChatRouteDecision,
    ChatSessionRecord,
    ChatWorkflowEvent,
    default_chat_route,
)
from datariver.application.evidence import evidence_chunk_is_valid
from datariver.application.ports import (
    ChatHistoryStore,
    ChatPersistenceUnitOfWork,
    ChatStore,
)
from datariver.domain.authz import Classification
from datariver.domain.chat import (
    ChatAdapterState,
    ChatRetrievalMode,
    ChatRouteReason,
    ChatWorkflowStage,
    ChatWorkflowStatus,
)
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


class SqlChatHistoryStore(ChatHistoryStore):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_session_owner(
        self,
        *,
        workspace_id: UUID,
        session_id: UUID,
    ) -> UUID | None:
        owner_id = await self._session.scalar(
            select(ChatSessionModel.owner_id).where(
                ChatSessionModel.workspace_id == workspace_id,
                ChatSessionModel.id == session_id,
                ChatSessionModel.is_archived.is_(False),
            )
        )
        return owner_id if isinstance(owner_id, UUID) else None

    async def list_sessions(
        self,
        *,
        workspace_id: UUID,
        owner_id: UUID,
        limit: int,
    ) -> Sequence[ChatSessionRecord]:
        if not 1 <= limit <= 50:
            raise ValueError("Chat session history limit must be between 1 and 50.")
        rows = (
            await self._session.execute(
                select(
                    ChatSessionModel,
                    func.count(ChatMessageModel.id).label("message_count"),
                )
                .outerjoin(
                    ChatMessageModel,
                    (
                        (ChatMessageModel.workspace_id == ChatSessionModel.workspace_id)
                        & (ChatMessageModel.session_id == ChatSessionModel.id)
                    ),
                )
                .where(
                    ChatSessionModel.workspace_id == workspace_id,
                    ChatSessionModel.owner_id == owner_id,
                    ChatSessionModel.is_archived.is_(False),
                )
                .group_by(ChatSessionModel.id)
                .order_by(
                    desc(ChatSessionModel.is_favorite),
                    desc(ChatSessionModel.updated_at),
                    desc(ChatSessionModel.id),
                )
                .limit(limit)
            )
        ).all()
        return tuple(
            self._session_record(session=row.ChatSessionModel, message_count=row.message_count)
            for row in rows
        )

    async def list_messages(
        self,
        *,
        workspace_id: UUID,
        owner_id: UUID,
        session_id: UUID,
        limit: int,
    ) -> Sequence[ChatMessageRecord]:
        if not 1 <= limit <= 200:
            raise ValueError("Chat message history limit must be between 1 and 200.")
        owned = await self._session.scalar(
            select(ChatSessionModel.id).where(
                ChatSessionModel.workspace_id == workspace_id,
                ChatSessionModel.owner_id == owner_id,
                ChatSessionModel.id == session_id,
                ChatSessionModel.is_archived.is_(False),
            )
        )
        if owned is None:
            raise ForbiddenError("The chat session is not available.")
        messages = list(
            (
                await self._session.scalars(
                    select(ChatMessageModel)
                    .where(
                        ChatMessageModel.workspace_id == workspace_id,
                        ChatMessageModel.session_id == session_id,
                    )
                    .order_by(
                        desc(ChatMessageModel.created_at),
                        desc(ChatMessageModel.id),
                    )
                    .limit(limit)
                )
            ).all()
        )
        # A persisted exchange assigns one timestamp to its user request and assistant response.
        # UUIDv7 remains time-sortable across milliseconds but is intentionally random within the
        # same millisecond, so reversing a UUID-sorted database page can interleave a pair.
        # Keep the bounded newest page, then restore the conversational order with the actor as
        # the deterministic tie-breaker.
        messages.sort(key=self._chronological_message_key)
        request_ids = tuple(message.id for message in messages if message.actor == "USER")
        runs = (
            list(
                (
                    await self._session.scalars(
                        select(AssistantRunModel).where(
                            AssistantRunModel.workspace_id == workspace_id,
                            AssistantRunModel.session_id == session_id,
                            AssistantRunModel.request_message_id.in_(request_ids),
                        )
                    )
                ).all()
            )
            if request_ids
            else []
        )
        citations_by_run: dict[UUID, list[EvidenceCitationModel]] = {}
        if runs:
            citations = (
                await self._session.scalars(
                    select(EvidenceCitationModel)
                    .where(
                        EvidenceCitationModel.workspace_id == workspace_id,
                        EvidenceCitationModel.run_id.in_(tuple(run.id for run in runs)),
                    )
                    .order_by(EvidenceCitationModel.run_id, EvidenceCitationModel.rank)
                )
            ).all()
            for citation in citations:
                citations_by_run.setdefault(citation.run_id, []).append(citation)
        run_by_request = {run.request_message_id: run for run in runs}
        active_run: AssistantRunModel | None = None
        records: list[ChatMessageRecord] = []
        for message in messages:
            evidence: tuple[ChatEvidence, ...] = ()
            route: ChatRouteDecision | None = None
            workflow: tuple[ChatWorkflowEvent, ...] = ()
            if message.actor == "USER":
                active_run = run_by_request.get(message.id)
            elif message.actor == "ASSISTANT" and active_run is not None:
                evidence = self._rehydrate_evidence(
                    workspace_id=workspace_id,
                    citations=citations_by_run.get(active_run.id, ()),
                )
                route = self._rehydrate_route(active_run.metrics)
                workflow = self._rehydrate_workflow(active_run.metrics)
                active_run = None
            records.append(
                ChatMessageRecord(
                    id=message.id,
                    session_id=message.session_id,
                    role="user" if message.actor == "USER" else "assistant",
                    content=message.content or "",
                    evidence=evidence,
                    created_at=message.created_at,
                    route=route,
                    workflow=workflow,
                )
            )
        return tuple(records)

    @staticmethod
    def _chronological_message_key(message: ChatMessageModel) -> tuple[datetime, int, str]:
        return (
            message.created_at,
            0 if message.actor == "USER" else 1,
            str(message.id),
        )

    async def set_favorite(
        self,
        *,
        workspace_id: UUID,
        owner_id: UUID,
        session_id: UUID,
        expected_version: int,
        is_favorite: bool,
    ) -> ChatSessionRecord:
        if expected_version < 1:
            raise ConflictError("The Chat session version is invalid.")
        updated_id = await self._session.scalar(
            update(ChatSessionModel)
            .where(
                ChatSessionModel.workspace_id == workspace_id,
                ChatSessionModel.owner_id == owner_id,
                ChatSessionModel.id == session_id,
                ChatSessionModel.version == expected_version,
                ChatSessionModel.is_archived.is_(False),
            )
            .values(
                is_favorite=is_favorite,
                version=ChatSessionModel.version + 1,
                updated_at=func.now(),
            )
            .returning(ChatSessionModel.id)
        )
        if updated_id is None:
            await self._session.rollback()
            raise ConflictError("The Chat session changed or is not available.")
        row = (
            await self._session.execute(
                select(
                    ChatSessionModel,
                    func.count(ChatMessageModel.id).label("message_count"),
                )
                .outerjoin(
                    ChatMessageModel,
                    (
                        (ChatMessageModel.workspace_id == ChatSessionModel.workspace_id)
                        & (ChatMessageModel.session_id == ChatSessionModel.id)
                    ),
                )
                .where(
                    ChatSessionModel.workspace_id == workspace_id,
                    ChatSessionModel.owner_id == owner_id,
                    ChatSessionModel.id == session_id,
                    ChatSessionModel.is_archived.is_(False),
                )
                .group_by(ChatSessionModel.id)
            )
        ).one()
        await self._session.commit()
        return self._session_record(
            session=row.ChatSessionModel,
            message_count=row.message_count,
        )

    async def archive_session(
        self,
        *,
        workspace_id: UUID,
        owner_id: UUID,
        session_id: UUID,
        expected_version: int,
    ) -> None:
        if expected_version < 1:
            raise ConflictError("The Chat session version is invalid.")
        updated_id = await self._session.scalar(
            update(ChatSessionModel)
            .where(
                ChatSessionModel.workspace_id == workspace_id,
                ChatSessionModel.owner_id == owner_id,
                ChatSessionModel.id == session_id,
                ChatSessionModel.version == expected_version,
                ChatSessionModel.is_archived.is_(False),
            )
            .values(
                is_archived=True,
                is_favorite=False,
                version=ChatSessionModel.version + 1,
                updated_at=func.now(),
            )
            .returning(ChatSessionModel.id)
        )
        if updated_id is None:
            await self._session.rollback()
            raise ConflictError("The Chat session changed or is not available.")
        await self._session.commit()

    @staticmethod
    def _session_record(
        *,
        session: ChatSessionModel,
        message_count: int,
    ) -> ChatSessionRecord:
        return ChatSessionRecord(
            id=session.id,
            title=session.title,
            is_favorite=session.is_favorite,
            version=session.version,
            created_at=session.created_at,
            updated_at=session.updated_at,
            message_count=int(message_count),
        )

    @staticmethod
    def _rehydrate_evidence(
        *,
        workspace_id: UUID,
        citations: Sequence[EvidenceCitationModel],
    ) -> tuple[ChatEvidence, ...]:
        values: list[ChatEvidence] = []
        for citation in citations:
            if not citation.display_name:
                continue
            value = ChatEvidence(
                chunk_id=citation.chunk_id,
                workspace_id=workspace_id,
                resource_id=citation.resource_id,
                classification=Classification(citation.classification),
                system_id=citation.system_id,
                domain_id=citation.domain_id,
                owner_department_id=citation.owner_department_id,
                name=citation.display_name,
                description=citation.description,
                source_type=citation.source_type,
                source_locator=citation.source_locator,
                source_version=citation.source_version,
                content_hash=citation.content_hash,
                effective_from=citation.effective_from,
                effective_until=citation.effective_until,
                extraction_method=citation.extraction_method,
            )
            if evidence_chunk_is_valid(value):
                values.append(value)
        return tuple(values)

    @staticmethod
    def _rehydrate_route(metrics: dict[str, object]) -> ChatRouteDecision | None:
        try:
            selected = ChatRetrievalMode(str(metrics["retrieval_mode"]))
            requested = ChatRetrievalMode(str(metrics.get("requested_mode", selected.value)))
            reason = ChatRouteReason(str(metrics["route_reason"]))
            adapter_state = ChatAdapterState(str(metrics.get("adapter_state", "READY")))
        except (KeyError, ValueError):
            return None
        return ChatRouteDecision(
            requested_mode=requested,
            selected_mode=selected,
            reason=reason,
            adapter_state=adapter_state,
        )

    @staticmethod
    def _rehydrate_workflow(metrics: dict[str, object]) -> tuple[ChatWorkflowEvent, ...]:
        document = metrics.get("workflow")
        if not isinstance(document, list) or len(document) > 20:
            return ()
        values: list[ChatWorkflowEvent] = []
        try:
            for item in document:
                if not isinstance(item, dict):
                    return ()
                detail_code = item.get("detail_code")
                if not isinstance(detail_code, str) or not 1 <= len(detail_code) <= 100:
                    return ()
                values.append(
                    ChatWorkflowEvent(
                        stage=ChatWorkflowStage(str(item["stage"])),
                        status=ChatWorkflowStatus(str(item["status"])),
                        detail_code=detail_code,
                    )
                )
        except (KeyError, ValueError):
            return ()
        return tuple(values)


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
        route: ChatRouteDecision | None = None,
        workflow: Sequence[ChatWorkflowEvent] = (),
        evidence_ranking: Sequence[ChatEvidenceRanking] = (),
        composition_audit: ChatCompositionAudit | None = None,
    ) -> ChatExchange:
        if any(item.workspace_id != workspace_id for item in evidence):
            raise ValueError("Evidence chunks must belong to the exchange workspace.")
        now = retention.binding_basis_at
        resolved_route = route
        resolved_audit = composition_audit or ChatCompositionAudit(
            provider="datariver",
            model="deterministic-evidence-v1",
            prompt_template_version="catalog-evidence-v1",
            external_service_used=False,
        )
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
            await self._session.flush((session,))
            session_id = session.id
        else:
            existing_session = (
                await self._session.scalars(
                    select(ChatSessionModel)
                    .where(
                        ChatSessionModel.id == session_id,
                        ChatSessionModel.workspace_id == workspace_id,
                        ChatSessionModel.owner_id == owner_id,
                        ChatSessionModel.is_archived.is_(False),
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
        request_message = ChatMessageModel(
            id=request_message_id,
            workspace_id=workspace_id,
            session_id=session_id,
            actor="USER",
            content=question,
            created_at=now,
        )
        response_message = ChatMessageModel(
            id=response_message_id,
            workspace_id=workspace_id,
            session_id=session_id,
            actor="ASSISTANT",
            content=answer,
            created_at=now,
        )
        self._session.add_all([request_message, response_message])
        await self._session.flush((request_message, response_message))
        run = AssistantRunModel(
            id=run_id,
            workspace_id=workspace_id,
            session_id=session_id,
            request_message_id=request_message_id,
            provider=resolved_audit.provider,
            model=resolved_audit.model,
            prompt_template_version=resolved_audit.prompt_template_version,
            policy_decision_id=policy_decision_id,
            state="COMPLETED",
            metrics={
                "evidence_count": len(evidence),
                "external_service_used": resolved_audit.external_service_used,
                "external_stages": list(resolved_audit.external_stages),
                "external_stage_provider_profile_version_ids": {
                    stage: str(profile_id)
                    for stage, profile_id in (
                        resolved_audit.external_stage_provider_profile_version_ids
                    )
                },
                "provider_profile_version_id": (
                    str(resolved_audit.provider_profile_version_id)
                    if resolved_audit.provider_profile_version_id is not None
                    else None
                ),
                "classification_policy_id": (
                    str(resolved_audit.classification_policy_id)
                    if resolved_audit.classification_policy_id is not None
                    else None
                ),
                "classification_policy_hash": (resolved_audit.classification_policy_hash),
                "classification_policy_version": (resolved_audit.classification_policy_version),
                "authorization_generation": (resolved_audit.authorization_generation),
                "retrieval_mode": (
                    resolved_route.selected_mode.value if resolved_route else "GENERAL"
                ),
                "requested_mode": (
                    resolved_route.requested_mode.value if resolved_route else "GENERAL"
                ),
                "route_reason": (
                    resolved_route.reason.value if resolved_route else "GENERAL_DEFAULT"
                ),
                "adapter_state": (
                    resolved_route.adapter_state.value if resolved_route else "READY"
                ),
                "evidence_ranking": [
                    {
                        "chunk_id": str(item.chunk_id),
                        "rank": item.rank,
                        "retrieval_method": item.retrieval_method,
                    }
                    for item in evidence_ranking
                ],
                "workflow": [
                    {
                        "stage": item.stage.value,
                        "status": item.status.value,
                        "detail_code": item.detail_code,
                    }
                    for item in workflow
                ],
            },
            started_at=now,
            finished_at=now,
        )
        self._session.add(run)
        await self._session.flush((run,))
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
                    display_name=item.name,
                    description=item.description,
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
            route=resolved_route or default_chat_route(),
            workflow=tuple(workflow),
            evidence_ranking=tuple(evidence_ranking),
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
