from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import StreamingResponse

from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.dto import (
    ChatAuthorizedDiscovery,
    ChatCompositionAudit,
    ChatEvidence,
    ChatEvidenceRanking,
    ChatMessageRecord,
    ChatSessionRecord,
    ChatWorkflowEvent,
)
from datariver.application.governance_document_chat import (
    GovernanceDocumentChatEvidenceReader,
)
from datariver.application.ports import (
    ChatAnswerComposer,
    ChatConversationContextCompressor,
    ChatGeneralAnswerComposer,
    ChatRouteIntentClassifier,
    ChatWorkflowProgressObserver,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.chat import ChatService
from datariver.application.services.chat_history import ChatHistoryService
from datariver.application.services.chat_routing import SemanticChatQuestionRouter
from datariver.application.services.governance_documents import GovernanceDocumentService
from datariver.application.services.knowledge_assets import KnowledgeGraphScopeService
from datariver.domain.chat import ChatWorkflowStage, ChatWorkflowStatus
from datariver.infrastructure.db.authz import SqlDecisionWriter, SqlSubjectReader
from datariver.infrastructure.db.catalog import SqlCatalogIndexReader
from datariver.infrastructure.db.chat import (
    SqlChatHistoryStore,
    SqlChatPersistenceUnitOfWork,
)
from datariver.infrastructure.db.classification_access import (
    SqlClassificationAccessSnapshotReader,
)
from datariver.infrastructure.db.governance_documents import (
    SqlGovernanceDocumentRepository,
)
from datariver.infrastructure.db.knowledge_assets import SqlKnowledgeAssetRepository
from datariver.infrastructure.db.knowledge_evidence import SqlKnowledgeEvidenceReader
from datariver.infrastructure.knowledge.openai_compatible import HttpxOpenAIJsonTransport
from datariver.infrastructure.knowledge.runtime import build_knowledge_runtime_adapters
from datariver.infrastructure.llm.ollama import LocalOllamaChatComposer
from datariver.infrastructure.llm.openai_compatible import (
    OpenAICompatibleGroundedChatComposer,
)
from datariver.infrastructure.llm.reranker import (
    IntranetEvidenceReranker,
    LocalLlamaCppEvidenceReranker,
)
from datariver.infrastructure.llm.runtime_binding import (
    resolve_interactive_runtime_bindings,
)
from datariver.infrastructure.llm.vector_catalog import BoundedCatalogVectorReader
from datariver.infrastructure.secrets import SecretResolver
from datariver.interfaces.http.container import AppContainer
from datariver.interfaces.http.dependencies import ContextDep, SessionDep, get_container
from datariver.interfaces.http.schemas import (
    ChatAuthorizedDiscoveryItemResponse,
    ChatAuthorizedDiscoveryResponse,
    ChatEvidenceResponse,
    ChatFavoriteRequest,
    ChatMessageResponse,
    ChatQueryRequest,
    ChatQueryResponse,
    ChatRequestPerformanceResponse,
    ChatRouteResponse,
    ChatSessionResponse,
    ChatWorkflowEventResponse,
)

router = APIRouter(prefix="/chat", tags=["assistant"])


class _ChatRequestTimingObserver:
    """Measure server-observed request stages without changing persisted workflow evidence."""

    _MEASURED_STAGES = frozenset(
        {
            ChatWorkflowStage.ROUTING,
            ChatWorkflowStage.RETRIEVAL,
            ChatWorkflowStage.RERANKING,
            ChatWorkflowStage.COMPOSITION,
        }
    )

    def __init__(
        self,
        delegate: ChatWorkflowProgressObserver | None,
        *,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._delegate = delegate
        self._clock = clock
        self._request_started = clock()
        self._stage_started: dict[ChatWorkflowStage, float] = {}
        self._duration_ms: dict[ChatWorkflowStage, int] = {}

    def publish(self, *, event: ChatWorkflowEvent) -> None:
        now = self._clock()
        if event.stage in self._MEASURED_STAGES:
            if event.status is ChatWorkflowStatus.IN_PROGRESS:
                self._stage_started.setdefault(event.stage, now)
            elif (started := self._stage_started.get(event.stage)) is not None:
                self._duration_ms[event.stage] = max(0, round((now - started) * 1_000))
        if self._delegate is not None:
            self._delegate.publish(event=event)

    def response(self) -> ChatRequestPerformanceResponse:
        return ChatRequestPerformanceResponse(
            routing_ms=self._duration_ms.get(ChatWorkflowStage.ROUTING),
            retrieval_ms=self._duration_ms.get(ChatWorkflowStage.RETRIEVAL),
            reranking_ms=self._duration_ms.get(ChatWorkflowStage.RERANKING),
            composition_ms=self._duration_ms.get(ChatWorkflowStage.COMPOSITION),
            total_ms=max(0, round((self._clock() - self._request_started) * 1_000)),
        )


def _development_composer(
    container: AppContainer,
) -> tuple[
    ChatAnswerComposer | None,
    ChatGeneralAnswerComposer | None,
    ChatRouteIntentClassifier | None,
    ChatConversationContextCompressor | None,
    ChatCompositionAudit | None,
]:
    settings = container.settings
    if settings.app_env != "development":
        return None, None, None, None, None
    if settings.local_ollama_chat_enabled:
        assert settings.local_ollama_chat_base_url is not None
        assert settings.local_ollama_chat_model is not None
        local_composer = LocalOllamaChatComposer(
            base_url=str(settings.local_ollama_chat_base_url),
            model=settings.local_ollama_chat_model,
            timeout_seconds=settings.local_ollama_chat_timeout_seconds,
            context_tokens=settings.local_ollama_chat_context_tokens,
            allowed_hosts=settings.effective_local_inference_allowed_hosts,
        )
        return (
            local_composer,
            local_composer,
            local_composer,
            local_composer,
            ChatCompositionAudit(
                provider="ollama-native-chat",
                model=settings.local_ollama_chat_model,
                prompt_template_version="grounded-chat-tool-v3",
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
            temperature=settings.intranet_openai_compatible_chat_temperature,
            top_p=settings.intranet_openai_compatible_chat_top_p,
            repetition_penalty=(settings.intranet_openai_compatible_chat_repetition_penalty),
            enable_thinking=settings.intranet_openai_compatible_chat_enable_thinking,
        )
        return (
            intranet_composer,
            intranet_composer,
            intranet_composer,
            intranet_composer,
            ChatCompositionAudit(
                provider="intranet-openai-compatible",
                model=settings.intranet_openai_compatible_chat_model,
                prompt_template_version="grounded-chat-tool-v3",
                external_service_used=True,
                provider_profile_version_id=(settings.chat_composition_provider_profile_version_id),
            ),
        )
    return None, None, None, None, None


def _conversation_context_tokens(container: AppContainer) -> int:
    settings = container.settings
    if settings.local_ollama_chat_enabled:
        provider_tokens = settings.local_ollama_chat_context_tokens
    elif settings.intranet_openai_compatible_chat_enabled:
        provider_tokens = settings.intranet_openai_compatible_chat_context_tokens
    else:
        return settings.chat_conversation_context_max_tokens
    return min(
        settings.chat_conversation_context_max_tokens,
        provider_tokens - 1_024,
    )


async def _query_response(
    payload: ChatQueryRequest,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    workflow_observer: ChatWorkflowProgressObserver | None = None,
) -> ChatQueryResponse:
    timing = _ChatRequestTimingObserver(workflow_observer)
    container = get_container(request)
    settings = container.settings
    catalog_index = SqlCatalogIndexReader(session)
    chat_history = SqlChatHistoryStore(session)
    (
        composer,
        general_composer,
        route_classifier,
        context_compressor,
        composition_audit,
    ) = _development_composer(container)
    vector_catalog_enabled = (
        settings.app_env == "development"
        and (settings.local_ollama_chat_enabled and settings.local_ollama_embedding_enabled)
    ) or (
        settings.app_env == "development"
        and (
            settings.intranet_openai_compatible_chat_enabled
            and settings.intranet_openai_compatible_embedding_enabled
        )
    )
    runtime = None
    if vector_catalog_enabled or settings.governance_document_worker_enabled:
        runtime = build_knowledge_runtime_adapters(settings)
    vector_catalog = None
    if vector_catalog_enabled and runtime is not None:
        vector_catalog = BoundedCatalogVectorReader(
            catalog_index=catalog_index,
            embedding=runtime.embedding,
            binding=runtime.bindings.embedding,
        )
    governance_evidence = None
    if settings.governance_document_worker_enabled and runtime is not None:
        governance_evidence = GovernanceDocumentChatEvidenceReader(
            GovernanceDocumentService(
                repository=SqlGovernanceDocumentRepository(session),
                authorization=AuthorizationService(
                    decision_writer=SqlDecisionWriter(container.database.session_factory)
                ),
                attachment_store=container.governance_document_attachments,
                artifact_storage_ready=container.governance_document_attachments is not None,
                knowledge_projection_ready=container.knowledge_neo4j is not None,
                knowledge_embedding=runtime.embedding,
                knowledge_embedding_binding=runtime.bindings.embedding,
                attachment_download_ttl_seconds=settings.presigned_url_ttl_seconds,
            )
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
            allowed_hosts=settings.effective_local_inference_allowed_hosts,
        )
    elif settings.app_env == "development" and settings.intranet_reranker_enabled:
        assert settings.intranet_reranker_base_url is not None
        assert settings.intranet_reranker_model is not None
        assert settings.intranet_reranker_api_key_secret_ref is not None
        api_key = SecretResolver(
            virtual_secret_root=settings.system_configuration_secret_root
        ).resolve(settings.intranet_reranker_api_key_secret_ref)
        reranker = IntranetEvidenceReranker(
            base_url=str(settings.intranet_reranker_base_url),
            model=settings.intranet_reranker_model,
            api_key=api_key,
            timeout_seconds=settings.intranet_reranker_timeout_seconds,
            top_n=min(settings.intranet_reranker_top_n, payload.maximum_evidence),
            allowed_hosts=frozenset(settings.intranet_openai_compatible_allowed_hosts),
        )
    exchange = await ChatService(
        catalog_index=catalog_index,
        vector_catalog=vector_catalog,
        governance_evidence=governance_evidence,
        graph_evidence=SqlKnowledgeEvidenceReader(session),
        graph_scope_resolver=KnowledgeGraphScopeService(
            repository=SqlKnowledgeAssetRepository(session),
            authorization=AuthorizationService(
                decision_writer=SqlDecisionWriter(container.database.session_factory)
            ),
        ),
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
        conversation_context_reader=chat_history,
        conversation_context_compressor=context_compressor,
        conversation_memory_enabled=settings.chat_conversation_memory_enabled,
        conversation_compression_start_after_user_turns=(
            settings.chat_conversation_compression_start_after_user_turns
        ),
        conversation_context_max_tokens=_conversation_context_tokens(container),
        classification_access=ClassificationAccessResolver(
            SqlClassificationAccessSnapshotReader(session)
        ),
        composer=composer,
        general_composer=general_composer,
        question_router=SemanticChatQuestionRouter(classifier=route_classifier),
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
        requested_graph_id=payload.graph_id,
        workflow_observer=timing,
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
        discovery=(
            _discovery_response(exchange.discovery) if exchange.discovery is not None else None
        ),
        performance=timing.response(),
    )


@router.post("/query", response_model=ChatQueryResponse)
async def query(
    payload: ChatQueryRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> ChatQueryResponse:
    response.headers["Cache-Control"] = "no-store"
    return await _query_response(
        payload=payload,
        request=request,
        context=context,
        session=session,
    )


class _WorkflowQueueObserver:
    """Bridge server-observed Chat transitions into one bounded SSE request."""

    def __init__(self, queue: asyncio.Queue[ChatWorkflowEvent]) -> None:
        self._queue = queue

    def publish(self, *, event: ChatWorkflowEvent) -> None:
        self._queue.put_nowait(event)


def _workflow_event_response(event: ChatWorkflowEvent) -> ChatWorkflowEventResponse:
    return ChatWorkflowEventResponse(
        stage=event.stage,
        status=event.status,
        detail_code=event.detail_code,
    )


def _sse_event(*, name: str, payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {name}\ndata: {encoded}\n\n"


async def _stream_chat_query(
    *,
    payload: ChatQueryRequest,
    request: Request,
    context: ContextDep,
    session: SessionDep,
) -> AsyncIterator[str]:
    """Emit actual server stages before the unchanged final Chat response."""

    queue: asyncio.Queue[ChatWorkflowEvent] = asyncio.Queue(maxsize=32)
    task = asyncio.create_task(
        _query_response(
            payload=payload,
            request=request,
            context=context,
            session=session,
            workflow_observer=_WorkflowQueueObserver(queue),
        )
    )
    try:
        while not task.done() or not queue.empty():
            if queue.empty():
                next_event = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait(
                    {task, next_event},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if next_event not in done:
                    next_event.cancel()
                    with suppress(asyncio.CancelledError):
                        await next_event
                    continue
                event = next_event.result()
            else:
                event = queue.get_nowait()
            yield _sse_event(
                name="workflow",
                payload=_workflow_event_response(event).model_dump(mode="json"),
            )
        result = await task
    except Exception:
        # The ordinary endpoint remains the source of detailed RFC 9457 failures.
        # Streaming exposes no internal adapter or policy detail before a final result.
        yield _sse_event(
            name="error",
            payload={
                "code": "CHAT_WORKFLOW_STREAM_FAILED",
                "detail": "응답 처리 중 문제가 발생했습니다. 다시 시도하세요.",
            },
        )
    else:
        yield _sse_event(name="result", payload=result.model_dump(mode="json"))
    finally:
        if not task.done():
            task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await task


@router.post("/query/stream", response_class=StreamingResponse)
async def query_stream(
    payload: ChatQueryRequest,
    request: Request,
    context: ContextDep,
    session: SessionDep,
) -> StreamingResponse:
    return StreamingResponse(
        _stream_chat_query(
            payload=payload,
            request=request,
            context=context,
            session=session,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
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


@router.delete("/sessions/{session_id}", status_code=204)
async def archive_session(
    session_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    expected_version: int = Query(ge=1),
) -> None:
    response.headers["Cache-Control"] = "no-store"
    container = get_container(request)
    await ChatHistoryService(
        history=SqlChatHistoryStore(session),
        authorization=AuthorizationService(
            decision_writer=SqlDecisionWriter(container.database.session_factory)
        ),
    ).archive_session(
        workspace_id=context.workspace_id,
        session_id=session_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        expected_version=expected_version,
    )


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
        # Citation rows are not a durable copy of the wider authorized discovery window.
        discovery_json=None,
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


def _discovery_response(
    discovery: ChatAuthorizedDiscovery,
) -> ChatAuthorizedDiscoveryResponse:
    rankings = {item.chunk_id: item for item in discovery.rankings}
    return ChatAuthorizedDiscoveryResponse(
        items=[
            _discovery_item_response(item, ranking=rankings[item.chunk_id])
            for item in discovery.items
        ],
        returned_count=discovery.returned_count,
        limit=discovery.limit,
        truncated=discovery.truncated,
        retrieved_count=discovery.retrieved_count,
        reranked_count=discovery.reranked_count,
        answer_context_count=discovery.answer_context_count,
        total=discovery.total,
        total_exact=discovery.total_exact,
        next_cursor=discovery.next_cursor,
    )


def _discovery_item_response(
    item: ChatEvidence,
    *,
    ranking: ChatEvidenceRanking,
) -> ChatAuthorizedDiscoveryItemResponse:
    return ChatAuthorizedDiscoveryItemResponse(
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
