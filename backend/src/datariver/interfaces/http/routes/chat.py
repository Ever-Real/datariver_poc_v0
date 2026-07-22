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
)

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
            for item in exchange.evidence
        ],
    )
