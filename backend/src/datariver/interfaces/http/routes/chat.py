from __future__ import annotations

from fastapi import APIRouter, Request

from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.chat import ChatService
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.catalog import SqlCatalogIndexReader
from datariver.infrastructure.db.chat import SqlChatStore
from datariver.infrastructure.db.knowledge_evidence import SqlKnowledgeEvidenceReader
from datariver.interfaces.http.dependencies import ContextDep, SessionDep, get_container
from datariver.interfaces.http.schemas import (
    ChatEvidenceResponse,
    ChatQueryRequest,
    ChatQueryResponse,
)

router = APIRouter(prefix="/chat", tags=["assistant"])


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
        store=SqlChatStore(session),
        authorization=AuthorizationService(
            decision_writer=SqlDecisionWriter(container.database.session_factory)
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
            for item in exchange.evidence
        ],
    )
