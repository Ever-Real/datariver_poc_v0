from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.dto import (
    ChatCompositionAudit,
    ChatEvidence,
    ChatEvidenceRanking,
    ChatMessageRecord,
    ChatSessionRecord,
)
from datariver.application.ports import ChatAnswerComposer, ChatGeneralAnswerComposer
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.chat import ChatService
from datariver.application.services.chat_history import ChatHistoryService
from datariver.infrastructure.db.authz import SqlDecisionWriter, SqlSubjectReader
from datariver.infrastructure.db.catalog import SqlCatalogIndexReader
from datariver.infrastructure.db.chat import (
    SqlChatHistoryStore,
    SqlChatPersistenceUnitOfWork,
)
from datariver.infrastructure.db.classification_access import (
    SqlClassificationAccessSnapshotReader,
)
from datariver.infrastructure.knowledge.openai_compatible import HttpxOpenAIJsonTransport
from datariver.infrastructure.knowledge.runtime import build_knowledge_runtime_adapters
from datariver.infrastructure.llm.ollama import LocalOllamaChatComposer
from datariver.infrastructure.llm.openai_compatible import (
    OpenAICompatibleGroundedChatComposer,
)
from datariver.infrastructure.llm.reranker import LocalLlamaCppEvidenceReranker
from datariver.infrastructure.llm.runtime_binding import (
    resolve_interactive_runtime_bindings,
)
from datariver.infrastructure.llm.vector_catalog import BoundedCatalogVectorReader
from datariver.infrastructure.secrets import SecretResolver
from datariver.interfaces.http.container import AppContainer
from datariver.interfaces.http.dependencies import ContextDep, SessionDep, get_container
from datariver.interfaces.http.schemas import (
    ChatEvidenceResponse,
    ChatFavoriteRequest,
    ChatMessageResponse,
    ChatQueryRequest,
    ChatQueryResponse,
    ChatRouteResponse,
    ChatSessionResponse,
    ChatWorkflowEventResponse,
)

router = APIRouter(prefix="/chat", tags=["assistant"])


def _development_composer(
    container: AppContainer,
) -> tuple[
    ChatAnswerComposer | None,
    ChatGeneralAnswerComposer | None,
    ChatCompositionAudit | None,
]:
    settings = container.settings
    if settings.app_env != "development":
        return None, None, None
    if settings.local_ollama_chat_enabled:
        assert settings.local_ollama_chat_base_url is not None
        assert settings.local_ollama_chat_model is not None
        local_composer = LocalOllamaChatComposer(
            base_url=str(settings.local_ollama_chat_base_url),
            model=settings.local_ollama_chat_model,
            timeout_seconds=settings.local_ollama_chat_timeout_seconds,
            context_tokens=settings.local_ollama_chat_context_tokens,
        )
        return (
            local_composer,
            local_composer,
            ChatCompositionAudit(
                provider="ollama-native-chat",
                model=settings.local_ollama_chat_model,
                prompt_template_version="grounded-chat-tool-v2",
                external_service_used=True,
                provider_profile_version_id=(settings.chat_composition_provider_profile_version_id),
            ),
        )
    if settings.intranet_openai_compatible_chat_enabled:
        assert settings.intranet_openai_compatible_chat_base_url is not None
        assert settings.intranet_openai_compatible_chat_model is not None
        assert settings.intranet_openai_compatible_chat_api_key_secret_ref is not None
        api_key = SecretResolver(
            virtual_secret_root=settings.system_configuration_secret_root
        ).resolve(settings.intranet_openai_compatible_chat_api_key_secret_ref)
        intranet_composer = OpenAICompatibleGroundedChatComposer(
            model=settings.intranet_openai_compatible_chat_model,
            transport=HttpxOpenAIJsonTransport(
                base_url=str(settings.intranet_openai_compatible_chat_base_url),
                allowed_hosts=frozenset(settings.intranet_openai_compatible_allowed_hosts),
                api_key=api_key,
                timeout_seconds=settings.intranet_openai_compatible_chat_timeout_seconds,
            ),
        )
        return (
            intranet_composer,
            intranet_composer,
            ChatCompositionAudit(
                provider="intranet-openai-compatible",
                model=settings.intranet_openai_compatible_chat_model,
                prompt_template_version="grounded-chat-tool-v1",
                external_service_used=True,
                provider_profile_version_id=(settings.chat_composition_provider_profile_version_id),
            ),
        )
    return None, None, None


@router.post("/query", response_model=ChatQueryResponse)
async def query(
    payload: ChatQueryRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> ChatQueryResponse:
    response.headers["Cache-Control"] = "no-store"
    container = get_container(request)
    settings = container.settings
    catalog_index = SqlCatalogIndexReader(session)
    chat_history = SqlChatHistoryStore(session)
    composer, general_composer, composition_audit = _development_composer(container)
    vector_catalog = None
    if (
        settings.app_env == "development"
        and (settings.local_ollama_chat_enabled and settings.local_ollama_embedding_enabled)
    ) or (
        settings.app_env == "development"
        and (
            settings.intranet_openai_compatible_chat_enabled
            and settings.intranet_openai_compatible_embedding_enabled
        )
    ):
        runtime = build_knowledge_runtime_adapters(settings)
        vector_catalog = BoundedCatalogVectorReader(
            catalog_index=catalog_index,
            embedding=runtime.embedding,
            binding=runtime.bindings.embedding,
        )
    reranker = None
    if settings.app_env == "development" and settings.local_llama_cpp_reranker_enabled:
        assert settings.local_llama_cpp_reranker_base_url is not None
        assert settings.local_llama_cpp_reranker_model is not None
        reranker = LocalLlamaCppEvidenceReranker(
            base_url=str(settings.local_llama_cpp_reranker_base_url),
            model=settings.local_llama_cpp_reranker_model,
            timeout_seconds=settings.local_llama_cpp_reranker_timeout_seconds,
            top_n=min(
                settings.local_llama_cpp_reranker_top_n,
                payload.maximum_evidence,
            ),
        )
    exchange = await ChatService(
        catalog_index=catalog_index,
        vector_catalog=vector_catalog,
        # The governed asset-graph adapter is intentionally opened by the port but
        # remains unavailable until the next asset-graph scope is implemented.
        graph_evidence=None,
        reranker=reranker,
        budget_guard=container.chat_budget,
        request_limit_per_minute=settings.chat_rate_limit_requests_per_minute,
        token_limit_per_minute=settings.chat_rate_limit_tokens_per_minute,
        uow_factory=lambda: SqlChatPersistenceUnitOfWork(container.database.session_factory),
        authorization=AuthorizationService(
            decision_writer=SqlDecisionWriter(container.database.session_factory)
        ),
        session_ownership=chat_history,
        subject_access=SqlSubjectReader(session),
        classification_access=ClassificationAccessResolver(
            SqlClassificationAccessSnapshotReader(session)
        ),
        composer=composer,
        general_composer=general_composer,
        composition_audit=composition_audit,
        inference_runtime_bindings=resolve_interactive_runtime_bindings(settings),
        allow_ephemeral_without_retention=(
            settings.chat_ephemeral_admin_without_retention_enabled
            and settings.app_env == "development"
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
        requested_mode=payload.mode,
    )
    rankings = {item.chunk_id: item for item in exchange.evidence_ranking}
    return ChatQueryResponse(
        session_id=exchange.session_id,
        request_message_id=exchange.request_message_id,
        response_message_id=exchange.response_message_id,
        answer=exchange.answer,
        persistence=exchange.persistence,
        route=ChatRouteResponse(
            requested_mode=exchange.route.requested_mode,
            selected_mode=exchange.route.selected_mode,
            reason=exchange.route.reason,
            adapter_state=exchange.route.adapter_state,
        ),
        workflow=[
            ChatWorkflowEventResponse(
                stage=item.stage,
                status=item.status,
                detail_code=item.detail_code,
            )
            for item in exchange.workflow
        ],
        evidence=[
            _evidence_response(
                item,
                ranking=rankings[item.chunk_id],
            )
            for item in exchange.evidence
        ],
    )


@router.get("/sessions", response_model=list[ChatSessionResponse])
async def list_sessions(
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=50),
) -> list[ChatSessionResponse]:
    response.headers["Cache-Control"] = "no-store"
    container = get_container(request)
    records = await ChatHistoryService(
        history=SqlChatHistoryStore(session),
        authorization=AuthorizationService(
            decision_writer=SqlDecisionWriter(container.database.session_factory)
        ),
    ).list_sessions(
        workspace_id=context.workspace_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        limit=limit,
    )
    return [_session_response(item) for item in records]


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageResponse])
async def get_messages(
    session_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    limit: int = Query(default=200, ge=1, le=200),
) -> list[ChatMessageResponse]:
    response.headers["Cache-Control"] = "no-store"
    container = get_container(request)
    records = await ChatHistoryService(
        history=SqlChatHistoryStore(session),
        authorization=AuthorizationService(
            decision_writer=SqlDecisionWriter(container.database.session_factory)
        ),
    ).list_messages(
        workspace_id=context.workspace_id,
        session_id=session_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        limit=limit,
    )
    return [_message_response(item) for item in records]


@router.patch(
    "/sessions/{session_id}/favorite",
    response_model=ChatSessionResponse,
)
async def set_favorite(
    session_id: UUID,
    payload: ChatFavoriteRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> ChatSessionResponse:
    response.headers["Cache-Control"] = "no-store"
    container = get_container(request)
    record = await ChatHistoryService(
        history=SqlChatHistoryStore(session),
        authorization=AuthorizationService(
            decision_writer=SqlDecisionWriter(container.database.session_factory)
        ),
    ).set_favorite(
        workspace_id=context.workspace_id,
        session_id=session_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        expected_version=payload.expected_version,
        is_favorite=payload.is_favorite,
    )
    return _session_response(record)


def _session_response(item: ChatSessionRecord) -> ChatSessionResponse:
    return ChatSessionResponse(
        id=item.id,
        title=item.title,
        is_favorite=item.is_favorite,
        version=item.version,
        created_at=item.created_at,
        updated_at=item.updated_at,
        message_count=item.message_count,
    )


def _message_response(item: ChatMessageRecord) -> ChatMessageResponse:
    return ChatMessageResponse(
        id=item.id,
        session_id=item.session_id,
        role=item.role,
        content=item.content,
        evidence_json=[
            _evidence_response(
                evidence,
                ranking=ChatEvidenceRanking(
                    chunk_id=evidence.chunk_id,
                    rank=index,
                    retrieval_method="PERSISTED_CITATION_ORDER",
                ),
            )
            for index, evidence in enumerate(item.evidence, start=1)
        ],
        created_at=item.created_at,
        route=(
            ChatRouteResponse(
                requested_mode=item.route.requested_mode,
                selected_mode=item.route.selected_mode,
                reason=item.route.reason,
                adapter_state=item.route.adapter_state,
            )
            if item.route is not None
            else None
        ),
        workflow=[
            ChatWorkflowEventResponse(
                stage=event.stage,
                status=event.status,
                detail_code=event.detail_code,
            )
            for event in item.workflow
        ],
    )


def _evidence_response(
    item: ChatEvidence,
    *,
    ranking: ChatEvidenceRanking,
) -> ChatEvidenceResponse:
    return ChatEvidenceResponse(
        chunk_id=item.chunk_id,
        resource_id=item.resource_id,
        classification=item.classification.name,
        system_id=item.system_id,
        domain_id=item.domain_id,
        owner_department_id=item.owner_department_id,
        name=item.name,
        description=item.description,
        source_type=item.source_type,
        source_locator=item.source_locator,
        source_version=item.source_version,
        content_hash=item.content_hash,
        effective_from=item.effective_from,
        effective_until=item.effective_until,
        extraction_method=item.extraction_method,
        rank=ranking.rank,
        retrieval_method=ranking.retrieval_method,
    )
