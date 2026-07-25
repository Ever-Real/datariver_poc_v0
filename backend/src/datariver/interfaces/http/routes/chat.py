from __future__ import annotations

from fastapi import APIRouter, Request

from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.ports import ChatAnswerComposer
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.chat import ChatService
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.catalog import SqlCatalogIndexReader
from datariver.infrastructure.db.chat import SqlChatPersistenceUnitOfWork
from datariver.infrastructure.db.classification_access import (
    SqlClassificationAccessSnapshotReader,
)
from datariver.infrastructure.db.knowledge_evidence import SqlKnowledgeEvidenceReader
from datariver.infrastructure.knowledge.openai_compatible import HttpxOpenAIJsonTransport
from datariver.infrastructure.llm.ollama import LocalOllamaChatComposer
from datariver.infrastructure.llm.openai_compatible import OpenAICompatibleGroundedChatComposer
from datariver.infrastructure.secrets import SecretResolver
from datariver.interfaces.http.container import AppContainer
from datariver.interfaces.http.dependencies import ContextDep, SessionDep, get_container
from datariver.interfaces.http.schemas import (
    ChatEvidenceResponse,
    ChatQueryRequest,
    ChatQueryResponse,
    ChatSessionResponse,
    ChatMessageResponse,
)
from sqlalchemy import select, func, desc
from uuid import UUID
from datariver.infrastructure.db.models.assistant import ChatSessionModel, ChatMessageModel

router = APIRouter(prefix="/chat", tags=["assistant"])


def _development_composer(container: AppContainer) -> ChatAnswerComposer | None:
    settings = container.settings
    if settings.local_ollama_chat_enabled:
        assert settings.local_ollama_chat_base_url is not None
        assert settings.local_ollama_chat_model is not None
        return LocalOllamaChatComposer(
            base_url=str(settings.local_ollama_chat_base_url),
            model=settings.local_ollama_chat_model,
            timeout_seconds=settings.local_ollama_chat_timeout_seconds,
            context_tokens=settings.local_ollama_chat_context_tokens,
        )
    if settings.intranet_openai_compatible_chat_enabled:
        assert settings.intranet_openai_compatible_chat_base_url is not None
        assert settings.intranet_openai_compatible_chat_model is not None
        assert settings.intranet_openai_compatible_chat_api_key_secret_ref is not None
        api_key = SecretResolver(
            virtual_secret_root=settings.system_configuration_secret_root
        ).resolve(settings.intranet_openai_compatible_chat_api_key_secret_ref)
        return OpenAICompatibleGroundedChatComposer(
            model=settings.intranet_openai_compatible_chat_model,
            transport=HttpxOpenAIJsonTransport(
                base_url=str(settings.intranet_openai_compatible_chat_base_url),
                allowed_hosts=frozenset(settings.intranet_openai_compatible_allowed_hosts),
                api_key=api_key,
                timeout_seconds=settings.intranet_openai_compatible_chat_timeout_seconds,
            ),
        )
    return None


@router.post("/query", response_model=ChatQueryResponse)
async def query(
    payload: ChatQueryRequest,
    request: Request,
    context: ContextDep,
    session: SessionDep,
) -> ChatQueryResponse:
    container = get_container(request)
    exchange = await ChatService(
        catalog_index=SqlCatalogIndexReader(session),
        knowledge_evidence=SqlKnowledgeEvidenceReader(session),
        uow_factory=lambda: SqlChatPersistenceUnitOfWork(container.database.session_factory),
        authorization=AuthorizationService(
            decision_writer=SqlDecisionWriter(container.database.session_factory)
        ),
        classification_access=ClassificationAccessResolver(
            SqlClassificationAccessSnapshotReader(session)
        ),
        composer=_development_composer(container),
        allow_ephemeral_without_retention=(
            container.settings.chat_ephemeral_admin_without_retention_enabled
            and container.settings.app_env == "development"
            and "security-administrators" in context.subject.groups
        ),
    ).query(
        workspace_id=context.workspace_id,
        subject=context.subject,
        session_id=payload.session_id,
        question=payload.question,
        maximum_evidence=payload.maximum_evidence,
        environment=context.environment,
        request_id=context.request_id,
    )
    return ChatQueryResponse(
        session_id=exchange.session_id,
        request_message_id=exchange.request_message_id,
        response_message_id=exchange.response_message_id,
        answer=exchange.answer,
        persistence=exchange.persistence,
        evidence=[
            ChatEvidenceResponse(
                chunk_id=item.chunk_id,
                resource_id=item.resource_id,
                classification=item.classification.name,
                system_id=item.system_id,
                domain_id=item.domain_id,
                owner_department_id=item.owner_department_id,
                name=item.name,
                source_type=item.source_type,
                source_locator=item.source_locator,
                source_version=item.source_version,
                content_hash=item.content_hash,
                effective_from=item.effective_from,
                effective_until=item.effective_until,
                extraction_method=item.extraction_method,
            )
    )

@router.get("/sessions", response_model=list[ChatSessionResponse])
async def list_sessions(
    context: ContextDep,
    session: SessionDep,
) -> list[ChatSessionResponse]:
    stmt = (
        select(
            ChatSessionModel,
            func.count(ChatMessageModel.id).label("message_count")
        )
        .outerjoin(ChatMessageModel, ChatMessageModel.session_id == ChatSessionModel.id)
        .where(
            ChatSessionModel.workspace_id == context.workspace_id,
            ChatSessionModel.owner_id == context.subject.subject_id,
        )
        .group_by(ChatSessionModel.id)
        .order_by(desc(ChatSessionModel.updated_at))
    )
    result = await session.execute(stmt)
    rows = result.all()
    return [
        ChatSessionResponse(
            id=row.ChatSessionModel.id,
            title=row.ChatSessionModel.title,
            is_favorite=False,
            created_at=row.ChatSessionModel.created_at,
            updated_at=row.ChatSessionModel.updated_at,
            message_count=row.message_count,
        )
        for row in rows
    ]

@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageResponse])
async def get_messages(
    session_id: UUID,
    context: ContextDep,
    session: SessionDep,
) -> list[ChatMessageResponse]:
    from datariver.infrastructure.db.models.assistant import AssistantRunModel, EvidenceCitationModel
    
    stmt = (
        select(ChatMessageModel)
        .where(
            ChatMessageModel.workspace_id == context.workspace_id,
            ChatMessageModel.session_id == session_id,
        )
        .order_by(ChatMessageModel.created_at.asc())
    )
    result = await session.execute(stmt)
    messages = result.scalars().all()
    
    runs_stmt = (
        select(AssistantRunModel)
        .where(
            AssistantRunModel.workspace_id == context.workspace_id,
            AssistantRunModel.session_id == session_id,
        )
    )
    runs = (await session.execute(runs_stmt)).scalars().all()
    run_by_request_id = {run.request_message_id: run.id for run in runs}
    
    evidence_by_run = {}
    if runs:
        evidence_stmt = (
            select(EvidenceCitationModel)
            .where(
                EvidenceCitationModel.workspace_id == context.workspace_id,
                EvidenceCitationModel.run_id.in_([run.id for run in runs]),
            )
            .order_by(EvidenceCitationModel.run_id, EvidenceCitationModel.rank)
        )
        evidence_rows = (await session.execute(evidence_stmt)).scalars().all()
        for ev in evidence_rows:
            evidence_by_run.setdefault(ev.run_id, []).append(ev)
            
    classification_names = {0: "PUBLIC", 1: "INTERNAL", 2: "CONFIDENTIAL", 3: "RESTRICTED"}
    
    response = []
    last_run_id = None
    for m in messages:
        evidence_json = None
        if m.actor == "USER":
            last_run_id = run_by_request_id.get(m.id)
        elif m.actor == "ASSISTANT" and last_run_id and last_run_id in evidence_by_run:
            evidence_json = [
                {
                    "chunk_id": str(ev.chunk_id),
                    "resource_id": str(ev.resource_id),
                    "classification": classification_names.get(ev.classification, "PUBLIC"),
                    "system_id": str(ev.system_id) if ev.system_id else None,
                    "domain_id": str(ev.domain_id) if ev.domain_id else None,
                    "owner_department_id": str(ev.owner_department_id) if ev.owner_department_id else None,
                    "name": ev.source_locator.split("/")[-1] if "/" in ev.source_locator else ev.source_locator,
                    "source_type": ev.source_type,
                    "source_locator": ev.source_locator,
                    "source_version": ev.source_version,
                    "content_hash": ev.content_hash,
                    "effective_from": ev.effective_from.isoformat(),
                    "effective_until": ev.effective_until.isoformat() if ev.effective_until else None,
                    "extraction_method": ev.extraction_method,
                }
                for ev in evidence_by_run[last_run_id]
            ]
            last_run_id = None
            
        response.append(
            ChatMessageResponse(
                id=m.id,
                session_id=m.session_id,
                role=m.actor.lower(),
                content=m.content or "",
                evidence_json=evidence_json,
                created_at=m.created_at,
            )
        )
    return response
