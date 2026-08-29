from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace
from datetime import datetime
from uuid import UUID

from datariver.application.classification_access import (
    ClassificationAccessPosture,
    ClassificationAccessResolver,
    ClassificationAccessSnapshot,
    ClassificationRuleRecord,
    InferenceRuntimeBinding,
    InferenceStage,
    ProviderProfileRecord,
    static_classification_access_floor,
)
from datariver.application.dto import (
    CatalogAssetIndex,
    ChatAuthorizedDiscovery,
    ChatCatalogSearchScope,
    ChatCompositionAudit,
    ChatConversationContextDraft,
    ChatConversationHistory,
    ChatDraft,
    ChatEvidence,
    ChatEvidenceRanking,
    ChatExchange,
    ChatRetentionBinding,
    ChatRouteDecision,
    ChatWorkflowEvent,
)
from datariver.application.errors import ChatExternalAdapterInvocationError
from datariver.application.evidence import build_evidence_chunk, evidence_chunk_is_valid
from datariver.application.knowledge_asset_contracts import KnowledgeGraphChatScope
from datariver.application.knowledge_asset_ports import KnowledgeGraphScopeResolver
from datariver.application.ports import (
    CatalogIndexReader,
    ChatAnswerComposer,
    ChatConversationContextCompressor,
    ChatConversationContextReader,
    ChatEvidenceReranker,
    ChatGeneralAnswerComposer,
    ChatPersistenceUnitOfWork,
    ChatQuestionRouter,
    ChatRequestBudgetGuard,
    ChatSessionOwnershipReader,
    ChatSubjectAccessReader,
    ChatVectorCatalogReader,
    ChatWorkflowProgressObserver,
    GovernanceChatEvidenceReader,
    KnowledgeEvidenceReader,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.chat_routing import DeterministicChatQuestionRouter
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.chat import (
    MAXIMUM_CHAT_VECTOR_CANDIDATES,
    MAXIMUM_CHAT_VECTOR_TEXT_CHARACTERS,
    ChatAdapterState,
    ChatRetrievalMode,
    ChatWorkflowStage,
    ChatWorkflowStatus,
)
from datariver.domain.classification_access import ChatMode, SearchMode
from datariver.domain.common import ConflictError, ForbiddenError, utc_now, uuid7
from datariver.domain.retention import RetentionPolicyState

UNVERIFIABLE_ANSWER = "검증 불가"
GENERAL_KNOWLEDGE_PREFIX = "※ 사내 인용 근거가 없어 일반 지식으로 답변합니다.\n\n"
CONTEXT_DEGRADED_PREFIX = (
    "※ 이전 대화 맥락을 안전하게 준비하지 못해 현재 질문만으로 답변합니다.\n\n"
)
_MAXIMUM_CHAT_ANSWER_CHARACTERS = 4_000
_MAXIMUM_CHAT_CONTEXT_USER_TURNS = 100
_MINIMUM_CHAT_DISCOVERY_CANDIDATES = 8
_MAXIMUM_CONTEXTUAL_QUESTION_CHARACTERS = 4_000
_MAXIMUM_CATALOG_EVIDENCE_DESCRIPTION_CHARACTERS = 1_000
_INTERNAL_EVIDENCE_MARKUP = re.compile(r"\[\[[^\]\r\n]*\]\]")
_UUID_TOKEN = re.compile(
    r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{8}-(?:[0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}(?![0-9A-Fa-f])"
)
_RESOURCE_LOCATOR_TOKEN = re.compile(
    r"(?:\burn:[^\s]+|\b[a-z][a-z0-9+.-]*://[^\s]+)",
    re.IGNORECASE,
)
_CONTROL_CHARACTER = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_EMPTY_CITATION_LIST = re.compile(r"\[\s*(?:[,;]\s*)*\]")
_CONTEXT_FORBIDDEN_IDENTIFIER = re.compile(
    r"(?:\burn:|https?://|\bsource[_ -]?locator\b|\bchunk[_ -]?id\b)",
    re.IGNORECASE,
)
_DETERMINISTIC_AUDIT = ChatCompositionAudit(
    provider="datariver",
    model="deterministic-evidence-v1",
    prompt_template_version="catalog-evidence-v1",
    external_service_used=False,
)


def _bounded_catalog_evidence_description(asset: CatalogAssetIndex) -> str | None:
    """Project authorized catalog hierarchy without exposing internal identifiers."""

    context_values = (
        ("데이터 플랫폼", _sanitize_catalog_evidence_text(asset.platform, limit=100)),
        (
            "데이터베이스",
            _sanitize_catalog_evidence_text(asset.database_name, limit=255),
        ),
        ("스키마", _sanitize_catalog_evidence_text(asset.schema_name, limit=255)),
    )
    context = " · ".join(f"{label}: {value}" for label, value in context_values if value)
    description = _sanitize_catalog_evidence_text(
        asset.description,
        limit=_MAXIMUM_CATALOG_EVIDENCE_DESCRIPTION_CHARACTERS,
    )
    parts = ([f"카탈로그 위치 — {context}."] if context else []) + (
        [description] if description else []
    )
    if not parts:
        return None
    return " ".join(parts)[:_MAXIMUM_CATALOG_EVIDENCE_DESCRIPTION_CHARACTERS].rstrip()


def _sanitize_catalog_evidence_text(value: str | None, *, limit: int) -> str | None:
    if value is None:
        return None
    sanitized = _CONTROL_CHARACTER.sub(" ", value)
    sanitized = _INTERNAL_EVIDENCE_MARKUP.sub(" ", sanitized)
    sanitized = _RESOURCE_LOCATOR_TOKEN.sub(" ", sanitized)
    sanitized = _UUID_TOKEN.sub(" ", sanitized)
    sanitized = " ".join(sanitized.split()).strip(" ,;:-")
    if not sanitized:
        return None
    return sanitized[:limit].rstrip()


class _ObservedChatWorkflow(list[ChatWorkflowEvent]):
    """Keep the persisted terminal workflow and optional UI progress in lockstep."""

    def __init__(self, observer: ChatWorkflowProgressObserver | None) -> None:
        super().__init__()
        self._observer = observer

    def append(self, event: ChatWorkflowEvent) -> None:
        super().append(event)
        self._publish(event)

    def extend(self, events: Iterable[ChatWorkflowEvent]) -> None:
        for event in events:
            self.append(event)

    def publish_progress(
        self,
        *,
        stage: ChatWorkflowStage,
        detail_code: str,
    ) -> None:
        self._publish(
            ChatWorkflowEvent(
                stage=stage,
                status=ChatWorkflowStatus.IN_PROGRESS,
                detail_code=detail_code,
            )
        )

    def _publish(self, event: ChatWorkflowEvent) -> None:
        if self._observer is None:
            return
        try:
            self._observer.publish(event=event)
        except Exception:
            # Browser progress is observational; it must never change the governed result.
            return


class DeterministicChatAnswerComposer:
    async def compose(
        self,
        *,
        question: str,
        evidence: Sequence[ChatEvidence],
        prior_user_utterances: Sequence[str] = (),
    ) -> ChatDraft:
        del question, prior_user_utterances
        if not evidence:
            return ChatDraft(answer=UNVERIFIABLE_ANSWER, cited_chunk_ids=())
        lines = ["접근 권한이 확인된 사내 근거는 다음과 같습니다."]
        for index, item in enumerate(evidence, start=1):
            description = (item.description or "설명이 등록되지 않았습니다.").strip()
            lines.append(f"[{index}] {item.name}: {description[:500]}")
        return ChatDraft(
            answer="\n".join(lines),
            cited_chunk_ids=tuple(item.chunk_id for item in evidence),
        )


class ChatService:
    def __init__(
        self,
        *,
        catalog_index: CatalogIndexReader,
        uow_factory: Callable[[], ChatPersistenceUnitOfWork],
        authorization: AuthorizationService,
        session_ownership: ChatSessionOwnershipReader,
        subject_access: ChatSubjectAccessReader,
        conversation_context_reader: ChatConversationContextReader | None = None,
        conversation_context_compressor: ChatConversationContextCompressor | None = None,
        conversation_memory_enabled: bool = False,
        conversation_compression_start_after_user_turns: int = 3,
        conversation_context_max_tokens: int = 2_048,
        classification_access: ClassificationAccessResolver | None = None,
        composer: ChatAnswerComposer | None = None,
        general_composer: ChatGeneralAnswerComposer | None = None,
        composition_audit: ChatCompositionAudit | None = None,
        inference_runtime_bindings: tuple[InferenceRuntimeBinding, ...] = (),
        question_router: ChatQuestionRouter | None = None,
        vector_catalog: ChatVectorCatalogReader | None = None,
        governance_evidence: GovernanceChatEvidenceReader | None = None,
        graph_evidence: KnowledgeEvidenceReader | None = None,
        knowledge_evidence: KnowledgeEvidenceReader | None = None,
        graph_scope_resolver: KnowledgeGraphScopeResolver | None = None,
        reranker: ChatEvidenceReranker | None = None,
        budget_guard: ChatRequestBudgetGuard | None = None,
        request_limit_per_minute: int = 30,
        token_limit_per_minute: int = 1_000_000,
        allow_ephemeral_without_retention: bool = False,
    ) -> None:
        if graph_evidence is not None and knowledge_evidence is not None:
            raise ValueError("Only one governed graph evidence adapter may be supplied.")
        self._catalog_index = catalog_index
        self._vector_catalog = vector_catalog
        self._governance_evidence = governance_evidence
        self._graph_evidence = graph_evidence or knowledge_evidence
        self._graph_scope_resolver = graph_scope_resolver
        self._reranker = reranker
        self._budget_guard = budget_guard
        self._request_limit_per_minute = request_limit_per_minute
        self._token_limit_per_minute = token_limit_per_minute
        self._uow_factory = uow_factory
        self._authorization = authorization
        self._session_ownership = session_ownership
        self._subject_access = subject_access
        self._conversation_context_reader = conversation_context_reader
        self._conversation_context_compressor = conversation_context_compressor
        self._conversation_memory_enabled = conversation_memory_enabled
        if not (
            1 <= conversation_compression_start_after_user_turns <= _MAXIMUM_CHAT_CONTEXT_USER_TURNS
        ):
            raise ValueError("Chat conversation compression start is outside its bound.")
        if not 128 <= conversation_context_max_tokens <= 4_096:
            raise ValueError("Chat conversation context token budget is outside its bound.")
        self._conversation_compression_start_after_user_turns = (
            conversation_compression_start_after_user_turns
        )
        self._conversation_context_max_tokens = conversation_context_max_tokens
        self._classification_access = classification_access
        self._composer = composer or DeterministicChatAnswerComposer()
        self._general_composer = general_composer
        self._composition_audit = composition_audit or _DETERMINISTIC_AUDIT
        if len({binding.stage for binding in inference_runtime_bindings}) != len(
            inference_runtime_bindings
        ):
            raise ValueError("Interactive inference stages require unique runtime bindings.")
        self._inference_runtime_bindings = {
            binding.stage: binding for binding in inference_runtime_bindings
        }
        composition_binding = self._inference_runtime_bindings.get(InferenceStage.COMPOSITION)
        if self._composition_audit.provider_profile_version_id is not None and (
            composition_binding is None
            or composition_binding.provider_profile_version_id
            != self._composition_audit.provider_profile_version_id
        ):
            raise ValueError("The Chat composer and deployment provider-profile bindings differ.")
        self._question_router = question_router or DeterministicChatQuestionRouter()
        self._allow_ephemeral_without_retention = allow_ephemeral_without_retention

    async def query(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        session_id: UUID | None,
        question: str,
        maximum_evidence: int,
        environment: EnvironmentAttributes,
        request_id: str,
        requested_mode: ChatRetrievalMode = ChatRetrievalMode.AUTO,
        requested_graph_id: UUID | None = None,
        workflow_observer: ChatWorkflowProgressObserver | None = None,
    ) -> ChatExchange:
        workflow = _ObservedChatWorkflow(workflow_observer)
        workflow.publish_progress(
            stage=ChatWorkflowStage.AUTHORIZATION,
            detail_code="AUTHORIZATION_IN_PROGRESS",
        )
        owner_id = subject.subject_id
        if session_id is not None:
            current_owner_id = await self._session_ownership.get_session_owner(
                workspace_id=workspace_id,
                session_id=session_id,
            )
            if current_owner_id is None or current_owner_id != subject.subject_id:
                raise ForbiddenError("The chat session is not available.")
            owner_id = current_owner_id
        chat_decision = await self._authorization.authorize(
            subject=subject,
            resource=ResourceAttributes(
                resource_id=session_id or workspace_id,
                workspace_id=workspace_id,
                resource_type="chat_session",
                owner_department_id=None,
                system_id=None,
                domain_id=None,
                classification=Classification.INTERNAL,
                lifecycle="ACTIVE",
                owner_subject_id=owner_id,
            ),
            action=Action.CHAT_QUERY,
            environment=environment,
            request_id=request_id,
        )
        workflow.append(
            self._event(
                ChatWorkflowStage.AUTHORIZATION,
                ChatWorkflowStatus.COMPLETED,
                "CHAT_QUERY_AUTHORIZED",
            )
        )
        access = await self._resolve_classification_access(
            subject=subject,
            now=environment.requested_at,
        )
        chat_access = self._chat_retrieval_access(access, subject=subject)
        context_history, context_read_degraded = await self._read_conversation_context(
            workspace_id=workspace_id,
            subject=subject,
            session_id=session_id,
            requested_at=environment.requested_at,
        )
        bounded_user_utterances = self._bounded_user_utterances(
            context_history.user_utterances,
            maximum_bytes=self._conversation_context_max_tokens,
        )
        context_compression_requested = bool(
            session_id is not None
            and context_history.completed_user_turns
            >= self._conversation_compression_start_after_user_turns
        )
        route_classifier_requested = (
            requested_mode is ChatRetrievalMode.AUTO
            and self._question_router.requires_composition_inference
        )
        route_classifier_allowed = True
        if route_classifier_requested:
            route_classifier_allowed = bool(
                self._provider_bound_classifications(
                    chat_access,
                    required_stages=(InferenceStage.COMPOSITION,),
                )
            )
        workflow.publish_progress(
            stage=ChatWorkflowStage.BUDGET_RESERVATION,
            detail_code="BUDGET_RESERVATION_IN_PROGRESS",
        )
        if self._budget_guard is not None:
            await self._budget_guard.reserve(
                workspace_id=workspace_id,
                subject_id=subject.subject_id,
                policy_scope=self._budget_policy_scope(access),
                estimated_tokens=self._estimated_token_envelope(
                    question,
                    maximum_evidence=maximum_evidence,
                    retrieval_mode=(
                        requested_mode
                        if requested_mode is not ChatRetrievalMode.AUTO
                        else ChatRetrievalMode.VECTOR
                    ),
                    reranker_enabled=self._reranker is not None,
                    route_classifier_enabled=route_classifier_requested,
                    conversation_context_bytes=sum(
                        len(item.encode("utf-8")) for item in bounded_user_utterances
                    ),
                    context_compression_enabled=context_compression_requested,
                ),
                request_limit=self._request_limit_per_minute,
                token_limit=self._token_limit_per_minute,
                window_seconds=60,
            )
        (
            contextual_question,
            prior_user_utterances,
            context_status,
            context_compressor_invoked,
        ) = await self._contextualize_question(
            question=question,
            history=context_history,
            bounded_user_utterances=bounded_user_utterances,
            read_degraded=context_read_degraded,
            compression_allowed=(
                not self._composition_audit.external_service_used
                or bool(
                    self._provider_bound_classifications(
                        chat_access,
                        required_stages=(InferenceStage.COMPOSITION,),
                    )
                )
            ),
        )
        workflow.append(
            self._event(
                ChatWorkflowStage.BUDGET_RESERVATION,
                ChatWorkflowStatus.COMPLETED,
                self._context_budget_detail_code(context_status),
            )
        )
        workflow.publish_progress(
            stage=ChatWorkflowStage.ROUTING,
            detail_code="ROUTING_IN_PROGRESS",
        )
        route = await self._question_router.route(
            question=contextual_question,
            requested_mode=requested_mode,
            vector_available=(
                self._vector_catalog is not None or self._governance_evidence is not None
            ),
            graph_available=self._graph_evidence is not None,
            inference_allowed=route_classifier_allowed,
            prior_user_utterances=prior_user_utterances,
        )
        retrieval_question = route.resolved_question or self._retrieval_question(
            question=contextual_question,
            prior_user_utterances=prior_user_utterances,
        )
        composition_question = contextual_question
        composition_prior_user_utterances = prior_user_utterances
        if route.requested_mode is ChatRetrievalMode.AUTO and route.resolved_question is not None:
            composition_question = route.resolved_question
            composition_prior_user_utterances = ()
        general_composer = self._general_composer
        general_fallback_requested = (
            route.adapter_state is ChatAdapterState.UNAVAILABLE
            and route.selected_mode is ChatRetrievalMode.GRAPH
            and general_composer is not None
        )
        general_fallback_external_required = (
            general_fallback_requested and self._composition_audit.external_service_used
        )
        required_external_stages = (
            self._required_external_stages(route)
            if route.adapter_state is ChatAdapterState.READY
            else ((InferenceStage.COMPOSITION,) if general_fallback_external_required else ())
        )
        external_path_required = bool(required_external_stages)
        general_fallback_allowed = general_fallback_requested
        route_unavailable_detail = f"{route.selected_mode.value}_ADAPTER_UNAVAILABLE"
        if (
            route_classifier_requested
            and route.selected_mode is ChatRetrievalMode.GENERAL
            and route.adapter_state is ChatAdapterState.UNAVAILABLE
        ):
            route_unavailable_detail = (
                "ROUTE_CLASSIFIER_UNAVAILABLE"
                if route_classifier_allowed
                else "INFERENCE_PROVIDER_POLICY_BINDING_UNAVAILABLE"
            )
        allowed_chat_classifications = {
            rule.classification for rule in chat_access.rules if rule.search_mode is SearchMode.ABAC
        }
        if external_path_required:
            provider_bound = self._provider_bound_classifications(
                chat_access,
                required_stages=required_external_stages,
            )
            if not provider_bound:
                route = replace(route, adapter_state=ChatAdapterState.UNAVAILABLE)
                route_unavailable_detail = "INFERENCE_PROVIDER_POLICY_BINDING_UNAVAILABLE"
                allowed_chat_classifications = set()
                general_fallback_allowed = False
            else:
                allowed_chat_classifications.intersection_update(provider_bound)
        retrieval_subject = replace(
            subject,
            clearance=self._chat_ceiling(
                allowed_chat_classifications,
                subject=subject,
            ),
        )
        retrieval_access = self._retrieval_access_for_allowed(
            chat_access,
            allowed_chat_classifications,
        )
        request_composition_audit = self._audit_for_access(
            access,
            external_stages=(),
        )
        graph_scope: KnowledgeGraphChatScope | None = None
        discovery: ChatAuthorizedDiscovery | None = None
        external_stages: list[str] = []
        if context_compressor_invoked and self._composition_audit.external_service_used:
            external_stages.append("composition")
        if route_classifier_requested and route_classifier_allowed:
            external_stages.append("composition")
        if route.adapter_state is ChatAdapterState.UNAVAILABLE:
            cited_evidence: tuple[ChatEvidence, ...] = ()
            rankings: tuple[ChatEvidenceRanking, ...] = ()
            workflow.extend(
                (
                    self._event(
                        ChatWorkflowStage.ROUTING,
                        ChatWorkflowStatus.UNAVAILABLE,
                        route_unavailable_detail,
                    ),
                    self._event(
                        ChatWorkflowStage.RETRIEVAL,
                        ChatWorkflowStatus.UNAVAILABLE,
                        "RETRIEVAL_NOT_EXECUTED",
                    ),
                    self._event(
                        ChatWorkflowStage.RERANKING,
                        ChatWorkflowStatus.SKIPPED,
                        "NO_RETRIEVED_EVIDENCE",
                    ),
                )
            )
            if general_fallback_allowed and general_composer is not None:
                try:
                    workflow.publish_progress(
                        stage=ChatWorkflowStage.COMPOSITION,
                        detail_code="COMPOSITION_IN_PROGRESS",
                    )
                    if self._composition_audit.external_service_used:
                        external_stages.append("composition")
                    draft = await general_composer.compose_general(
                        question=composition_question,
                        prior_user_utterances=composition_prior_user_utterances,
                    )
                    answer = self._validate_general_draft(draft)
                except Exception:
                    route = replace(route, adapter_state=ChatAdapterState.FAILED)
                    answer = UNVERIFIABLE_ANSWER
                    workflow.extend(
                        (
                            self._event(
                                ChatWorkflowStage.COMPOSITION,
                                ChatWorkflowStatus.FAILED,
                                "GENERAL_KNOWLEDGE_COMPOSER_FAILED",
                            ),
                            self._event(
                                ChatWorkflowStage.CITATION_VALIDATION,
                                ChatWorkflowStatus.SKIPPED,
                                "NO_DRAFT",
                            ),
                        )
                    )
                else:
                    if answer == UNVERIFIABLE_ANSWER:
                        workflow.extend(
                            (
                                self._event(
                                    ChatWorkflowStage.COMPOSITION,
                                    ChatWorkflowStatus.REFUSED,
                                    "INVALID_GENERAL_KNOWLEDGE_DRAFT",
                                ),
                                self._event(
                                    ChatWorkflowStage.CITATION_VALIDATION,
                                    ChatWorkflowStatus.SKIPPED,
                                    "NO_DRAFT",
                                ),
                            )
                        )
                    else:
                        workflow.extend(
                            (
                                self._event(
                                    ChatWorkflowStage.COMPOSITION,
                                    ChatWorkflowStatus.COMPLETED,
                                    "GRAPH_UNAVAILABLE_GENERAL_KNOWLEDGE_COMPOSED",
                                ),
                                self._event(
                                    ChatWorkflowStage.CITATION_VALIDATION,
                                    ChatWorkflowStatus.SKIPPED,
                                    "NO_INTERNAL_CITATIONS_GENERAL_ANSWER",
                                ),
                            )
                        )
            else:
                answer = UNVERIFIABLE_ANSWER
                workflow.extend(
                    (
                        self._event(
                            ChatWorkflowStage.COMPOSITION,
                            ChatWorkflowStatus.REFUSED,
                            "UNAVAILABLE_ROUTE_REFUSED",
                        ),
                        self._event(
                            ChatWorkflowStage.CITATION_VALIDATION,
                            ChatWorkflowStatus.SKIPPED,
                            "NO_DRAFT",
                        ),
                    )
                )
        else:
            workflow.append(
                self._event(
                    ChatWorkflowStage.ROUTING,
                    ChatWorkflowStatus.COMPLETED,
                    f"{route.selected_mode.value}_ROUTE_SELECTED",
                )
            )
            try:
                workflow.publish_progress(
                    stage=ChatWorkflowStage.RETRIEVAL,
                    detail_code="RETRIEVAL_IN_PROGRESS",
                )
                retrieval = await self._retrieve(
                    route=route,
                    workspace_id=workspace_id,
                    subject=subject,
                    retrieval_subject=retrieval_subject,
                    access=retrieval_access,
                    allowed_classifications=allowed_chat_classifications,
                    question=retrieval_question,
                    maximum_evidence=maximum_evidence,
                    environment=environment,
                    request_id=request_id,
                    parent_resource_id=session_id or workspace_id,
                    requested_graph_id=requested_graph_id,
                )
                evidence, retrieval_stages, graph_scope, catalog_search_scope = retrieval
                external_stages.extend(retrieval_stages)
            except ChatExternalAdapterInvocationError as error:
                external_stages.append(error.stage)
                route = replace(route, adapter_state=ChatAdapterState.FAILED)
                workflow.extend(
                    (
                        self._event(
                            ChatWorkflowStage.RETRIEVAL,
                            ChatWorkflowStatus.FAILED,
                            f"{route.selected_mode.value}_RETRIEVAL_FAILED",
                        ),
                        self._event(
                            ChatWorkflowStage.RERANKING,
                            ChatWorkflowStatus.SKIPPED,
                            "RETRIEVAL_FAILED",
                        ),
                        self._event(
                            ChatWorkflowStage.COMPOSITION,
                            ChatWorkflowStatus.REFUSED,
                            "RETRIEVAL_FAILURE_REFUSED",
                        ),
                        self._event(
                            ChatWorkflowStage.CITATION_VALIDATION,
                            ChatWorkflowStatus.SKIPPED,
                            "NO_DRAFT",
                        ),
                    )
                )
                evidence = ()
                answer = UNVERIFIABLE_ANSWER
                cited_evidence = ()
                rankings = ()
            except Exception:
                route = replace(route, adapter_state=ChatAdapterState.FAILED)
                workflow.extend(
                    (
                        self._event(
                            ChatWorkflowStage.RETRIEVAL,
                            ChatWorkflowStatus.FAILED,
                            f"{route.selected_mode.value}_RETRIEVAL_FAILED",
                        ),
                        self._event(
                            ChatWorkflowStage.RERANKING,
                            ChatWorkflowStatus.SKIPPED,
                            "RETRIEVAL_FAILED",
                        ),
                        self._event(
                            ChatWorkflowStage.COMPOSITION,
                            ChatWorkflowStatus.REFUSED,
                            "RETRIEVAL_FAILURE_REFUSED",
                        ),
                        self._event(
                            ChatWorkflowStage.CITATION_VALIDATION,
                            ChatWorkflowStatus.SKIPPED,
                            "NO_DRAFT",
                        ),
                    )
                )
                evidence = ()
                answer = UNVERIFIABLE_ANSWER
                cited_evidence = ()
                rankings = ()
            else:
                workflow.append(
                    self._event(
                        ChatWorkflowStage.RETRIEVAL,
                        ChatWorkflowStatus.COMPLETED,
                        f"{route.selected_mode.value}_RETRIEVAL_COMPLETED",
                    )
                )
                if evidence:
                    workflow.publish_progress(
                        stage=ChatWorkflowStage.RERANKING,
                        detail_code="RERANKING_IN_PROGRESS",
                    )
                (
                    ranked_evidence,
                    rankings,
                    rerank_failed,
                    reranker_invoked,
                    reranked_count,
                ) = await self._rank(
                    question=retrieval_question,
                    evidence=evidence,
                    route=route,
                    workflow=workflow,
                )
                if not rerank_failed:
                    discovery_limit = self._discovery_limit(maximum_evidence)
                    answer_context_count = min(
                        reranked_count if reranker_invoked else len(ranked_evidence),
                        maximum_evidence,
                    )
                    catalog_search_query = self._catalog_search_handoff_query(
                        scope=catalog_search_scope,
                        evidence=ranked_evidence,
                    )
                    discovery = ChatAuthorizedDiscovery(
                        items=ranked_evidence,
                        rankings=rankings,
                        returned_count=len(ranked_evidence),
                        limit=discovery_limit,
                        retrieved_count=len(evidence),
                        reranked_count=reranked_count,
                        answer_context_count=answer_context_count,
                        catalog_search_query=catalog_search_query,
                        catalog_search_fields=(
                            catalog_search_scope.search_fields
                            if catalog_search_scope is not None
                            and catalog_search_query is not None
                            else ()
                        ),
                        truncated=(
                            len(ranked_evidence) < len(evidence) or len(evidence) >= discovery_limit
                        ),
                    )
                # Discovery recall and answer context are separate bounds.  Every item in the
                # wider candidate window has already passed the route's authorization checks;
                # only this request-bounded prefix may reach composition or citation validation.
                answer_context_count = (
                    min(reranked_count, maximum_evidence)
                    if reranker_invoked
                    else maximum_evidence
                )
                ranked_evidence = ranked_evidence[:answer_context_count]
                rankings = rankings[:answer_context_count]
                if reranker_invoked:
                    external_stages.append("reranker")
                if rerank_failed:
                    route = replace(route, adapter_state=ChatAdapterState.FAILED)
                    answer = UNVERIFIABLE_ANSWER
                    cited_evidence = ()
                    rankings = ()
                    workflow.extend(
                        (
                            self._event(
                                ChatWorkflowStage.COMPOSITION,
                                ChatWorkflowStatus.REFUSED,
                                "RERANKER_FAILURE_REFUSED",
                            ),
                            self._event(
                                ChatWorkflowStage.CITATION_VALIDATION,
                                ChatWorkflowStatus.SKIPPED,
                                "NO_DRAFT",
                            ),
                        )
                    )
                elif not ranked_evidence:
                    cited_evidence = ()
                    rankings = ()
                    if self._general_composer is None:
                        answer = UNVERIFIABLE_ANSWER
                        workflow.extend(
                            (
                                self._event(
                                    ChatWorkflowStage.COMPOSITION,
                                    ChatWorkflowStatus.REFUSED,
                                    "NO_AUTHORIZED_EVIDENCE",
                                ),
                                self._event(
                                    ChatWorkflowStage.CITATION_VALIDATION,
                                    ChatWorkflowStatus.SKIPPED,
                                    "NO_DRAFT",
                                ),
                            )
                        )
                    else:
                        try:
                            workflow.publish_progress(
                                stage=ChatWorkflowStage.COMPOSITION,
                                detail_code="COMPOSITION_IN_PROGRESS",
                            )
                            if self._composition_audit.external_service_used:
                                external_stages.append("composition")
                            draft = await self._general_composer.compose_general(
                                question=composition_question,
                                prior_user_utterances=composition_prior_user_utterances,
                            )
                            answer = self._validate_general_draft(draft)
                        except Exception:
                            route = replace(route, adapter_state=ChatAdapterState.FAILED)
                            answer = UNVERIFIABLE_ANSWER
                            workflow.extend(
                                (
                                    self._event(
                                        ChatWorkflowStage.COMPOSITION,
                                        ChatWorkflowStatus.FAILED,
                                        "GENERAL_KNOWLEDGE_COMPOSER_FAILED",
                                    ),
                                    self._event(
                                        ChatWorkflowStage.CITATION_VALIDATION,
                                        ChatWorkflowStatus.SKIPPED,
                                        "NO_DRAFT",
                                    ),
                                )
                            )
                        else:
                            if answer == UNVERIFIABLE_ANSWER:
                                workflow.extend(
                                    (
                                        self._event(
                                            ChatWorkflowStage.COMPOSITION,
                                            ChatWorkflowStatus.REFUSED,
                                            "INVALID_GENERAL_KNOWLEDGE_DRAFT",
                                        ),
                                        self._event(
                                            ChatWorkflowStage.CITATION_VALIDATION,
                                            ChatWorkflowStatus.SKIPPED,
                                            "NO_DRAFT",
                                        ),
                                    )
                                )
                            else:
                                workflow.extend(
                                    (
                                        self._event(
                                            ChatWorkflowStage.COMPOSITION,
                                            ChatWorkflowStatus.COMPLETED,
                                            "GENERAL_KNOWLEDGE_DRAFT_COMPOSED",
                                        ),
                                        self._event(
                                            ChatWorkflowStage.CITATION_VALIDATION,
                                            ChatWorkflowStatus.SKIPPED,
                                            "NO_INTERNAL_CITATIONS_GENERAL_ANSWER",
                                        ),
                                    )
                                )
                else:
                    try:
                        workflow.publish_progress(
                            stage=ChatWorkflowStage.COMPOSITION,
                            detail_code="COMPOSITION_IN_PROGRESS",
                        )
                        if self._composition_audit.external_service_used:
                            external_stages.append("composition")
                        draft = await self._composer.compose(
                            question=composition_question,
                            evidence=ranked_evidence,
                            prior_user_utterances=composition_prior_user_utterances,
                        )
                    except Exception:
                        route = replace(route, adapter_state=ChatAdapterState.FAILED)
                        answer = UNVERIFIABLE_ANSWER
                        cited_evidence = ()
                        rankings = ()
                        workflow.extend(
                            (
                                self._event(
                                    ChatWorkflowStage.COMPOSITION,
                                    ChatWorkflowStatus.FAILED,
                                    "COMPOSER_FAILED",
                                ),
                                self._event(
                                    ChatWorkflowStage.CITATION_VALIDATION,
                                    ChatWorkflowStatus.SKIPPED,
                                    "NO_DRAFT",
                                ),
                            )
                        )
                    else:
                        answer, cited_evidence = self._validate_draft(
                            draft=draft,
                            authorized_evidence=ranked_evidence,
                            workspace_id=workspace_id,
                        )
                        if not cited_evidence:
                            rankings = ()
                            workflow.extend(
                                (
                                    self._event(
                                        ChatWorkflowStage.COMPOSITION,
                                        ChatWorkflowStatus.REFUSED,
                                        "INVALID_GROUNDED_DRAFT_CITATIONS",
                                    ),
                                    self._event(
                                        ChatWorkflowStage.CITATION_VALIDATION,
                                        ChatWorkflowStatus.SKIPPED,
                                        "NO_VALID_GROUNDED_CITATIONS",
                                    ),
                                )
                            )
                        else:
                            workflow.append(
                                self._event(
                                    ChatWorkflowStage.COMPOSITION,
                                    ChatWorkflowStatus.COMPLETED,
                                    "GROUNDED_DRAFT_COMPOSED",
                                )
                            )
                            workflow.publish_progress(
                                stage=ChatWorkflowStage.CITATION_VALIDATION,
                                detail_code="CITATION_VALIDATION_IN_PROGRESS",
                            )
                            pre_validation_answer = answer
                            pre_validation_citations = cited_evidence
                            if discovery is not None:
                                answer, validated_discovery = (
                                    await self._final_reauthorize_citations(
                                        answer=pre_validation_answer,
                                        evidence=discovery.items,
                                        initial_access=access,
                                        required_external_stages=required_external_stages,
                                        workspace_id=workspace_id,
                                        subject=subject,
                                        environment=environment,
                                        request_id=f"{request_id}:discovery-final",
                                        parent_resource_id=session_id or workspace_id,
                                        question=retrieval_question,
                                        requested_graph_id=requested_graph_id,
                                        initial_graph_scope=graph_scope,
                                    )
                                )
                                validated_discovery_ids = {
                                    item.chunk_id for item in validated_discovery
                                }
                                if len(validated_discovery) == len(discovery.items) and all(
                                    item.chunk_id in validated_discovery_ids
                                    for item in pre_validation_citations
                                ):
                                    discovery = replace(discovery, items=validated_discovery)
                                    cited_evidence = pre_validation_citations
                                else:
                                    discovery = None
                                    answer, cited_evidence = (
                                        await self._final_reauthorize_citations(
                                            answer=pre_validation_answer,
                                            evidence=pre_validation_citations,
                                            initial_access=access,
                                            required_external_stages=required_external_stages,
                                            workspace_id=workspace_id,
                                            subject=subject,
                                            environment=environment,
                                            request_id=request_id,
                                            parent_resource_id=session_id or workspace_id,
                                            question=retrieval_question,
                                            requested_graph_id=requested_graph_id,
                                            initial_graph_scope=graph_scope,
                                        )
                                    )
                            else:
                                answer, cited_evidence = (
                                    await self._final_reauthorize_citations(
                                        answer=pre_validation_answer,
                                        evidence=pre_validation_citations,
                                        initial_access=access,
                                        required_external_stages=required_external_stages,
                                        workspace_id=workspace_id,
                                        subject=subject,
                                        environment=environment,
                                        request_id=request_id,
                                        parent_resource_id=session_id or workspace_id,
                                        question=retrieval_question,
                                        requested_graph_id=requested_graph_id,
                                        initial_graph_scope=graph_scope,
                                    )
                                )
                            if cited_evidence:
                                workflow.append(
                                    self._event(
                                        ChatWorkflowStage.CITATION_VALIDATION,
                                        ChatWorkflowStatus.COMPLETED,
                                        "CITATIONS_VALIDATED",
                                    )
                                )
                                ranking_by_id = {item.chunk_id: item for item in rankings}
                                rankings = tuple(
                                    ranking_by_id[item.chunk_id] for item in cited_evidence
                                )
                            else:
                                rankings = ()
                                workflow.append(
                                    self._event(
                                        ChatWorkflowStage.CITATION_VALIDATION,
                                        ChatWorkflowStatus.REFUSED,
                                        "FINAL_CITATION_REAUTHORIZATION_FAILED",
                                    )
                                )
        if not cited_evidence:
            discovery = None
        request_composition_audit = self._audit_for_access(
            access,
            external_stages=tuple(dict.fromkeys(external_stages)),
        )
        if context_compressor_invoked:
            request_composition_audit = replace(
                request_composition_audit,
                prompt_template_version=(
                    f"{request_composition_audit.prompt_template_version}+conversation-context-v1"
                ),
            )
        if graph_scope is not None:
            request_composition_audit = replace(
                request_composition_audit,
                knowledge_graph_id=graph_scope.graph_id,
                knowledge_release_id=graph_scope.release_id,
                knowledge_delivery_policy_id=graph_scope.policy_id,
                knowledge_delivery_policy_version=graph_scope.policy_version,
                knowledge_delivery_policy_hash=graph_scope.policy_hash,
            )
        if context_status == "CONTEXT_DEGRADED" and answer != UNVERIFIABLE_ANSWER:
            answer = self._with_context_degraded_disclosure(answer)
        async with self._uow_factory() as uow:
            await uow.set_security_context(
                workspace_id=workspace_id,
                subject_id=subject.subject_id,
            )
            await uow.lock_retention_workspace(workspace_id=workspace_id)
            policy = await uow.retention_policies.get_active_for_update(workspace_id=workspace_id)
            if policy is None or policy.state is not RetentionPolicyState.ACTIVE:
                if self._allow_ephemeral_without_retention:
                    workflow.publish_progress(
                        stage=ChatWorkflowStage.PERSISTENCE,
                        detail_code="PERSISTENCE_IN_PROGRESS",
                    )
                    persistence_event = self._event(
                        ChatWorkflowStage.PERSISTENCE,
                        ChatWorkflowStatus.SKIPPED,
                        "EPHEMERAL_NO_STORE",
                    )
                    ephemeral_workflow = (
                        *workflow,
                        persistence_event,
                    )
                    workflow.append(persistence_event)
                    return ChatExchange(
                        session_id=session_id or uuid7(),
                        request_message_id=uuid7(),
                        response_message_id=uuid7(),
                        answer=answer,
                        evidence=cited_evidence,
                        persistence="EPHEMERAL_NO_STORE",
                        route=route,
                        workflow=ephemeral_workflow,
                        evidence_ranking=rankings,
                        discovery=discovery,
                    )
                raise ConflictError(
                    "An active retention policy is required to persist Chat content."
                )
            binding = ChatRetentionBinding(
                policy_id=policy.policy_id,
                policy_hash=policy.payload_hash,
                binding_basis_at=await uow.transaction_time(),
                chat_content_days=policy.rules.chat_content_days,
            )
            workflow.publish_progress(
                stage=ChatWorkflowStage.PERSISTENCE,
                detail_code="PERSISTENCE_IN_PROGRESS",
            )
            persistence_event = self._event(
                ChatWorkflowStage.PERSISTENCE,
                ChatWorkflowStatus.COMPLETED,
                "RETENTION_BOUND_EXCHANGE_PERSISTED",
            )
            persisted_workflow = (
                *workflow,
                persistence_event,
            )
            exchange = await uow.chats.save_exchange(
                workspace_id=workspace_id,
                owner_id=owner_id,
                session_id=session_id,
                question=question,
                answer=answer,
                evidence=cited_evidence,
                policy_decision_id=chat_decision.decision_id,
                retention=binding,
                route=route,
                workflow=persisted_workflow,
                evidence_ranking=rankings,
                composition_audit=request_composition_audit,
            )
            await uow.commit()
            workflow.append(persistence_event)
            # The wider discovery window is intentionally immediate-response state only.
            # Citation persistence remains separate until a bounded durable contract is reviewed.
            return replace(exchange, discovery=discovery)

    async def _read_conversation_context(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        session_id: UUID | None,
        requested_at: datetime,
    ) -> tuple[ChatConversationHistory, bool]:
        empty = ChatConversationHistory(completed_user_turns=0, user_utterances=())
        if not self._conversation_memory_enabled or session_id is None:
            return empty, False
        if self._conversation_context_reader is None:
            return empty, True
        try:
            refreshed = await self._subject_access.refresh_subject(
                subject=subject,
                now=requested_at,
            )
            if not refreshed.active or self._subject_security_identity(
                refreshed
            ) != self._subject_security_identity(subject):
                return empty, True
            history = await self._conversation_context_reader.read_user_intent_context(
                workspace_id=workspace_id,
                owner_id=subject.subject_id,
                session_id=session_id,
                limit=_MAXIMUM_CHAT_CONTEXT_USER_TURNS,
            )
        except Exception:
            return empty, True
        return history, False

    async def _contextualize_question(
        self,
        *,
        question: str,
        history: ChatConversationHistory,
        bounded_user_utterances: tuple[str, ...],
        read_degraded: bool,
        compression_allowed: bool,
    ) -> tuple[str, tuple[str, ...], str, bool]:
        if read_degraded:
            return question, (), "CONTEXT_DEGRADED", False
        if not bounded_user_utterances or history.completed_user_turns == 0:
            return question, (), "CONTEXT_NOT_NEEDED", False
        if history.completed_user_turns < self._conversation_compression_start_after_user_turns:
            return (
                question,
                bounded_user_utterances,
                "RAW_CONTEXT_USED",
                False,
            )
        if self._conversation_context_compressor is None or not compression_allowed:
            return question, (), "CONTEXT_DEGRADED", False
        try:
            draft = await self._conversation_context_compressor.compress_context(
                question=question,
                user_utterances=bounded_user_utterances,
            )
            resolved_question = self._validate_context_draft(draft)
        except Exception:
            return question, (), "CONTEXT_DEGRADED", True
        return resolved_question, (), "COMPRESSED_CONTEXT_USED", True

    def _context_budget_detail_code(self, context_status: str) -> str:
        if self._budget_guard is None:
            prefix = "CHAT_BUDGET_GUARD_NOT_CONFIGURED"
        else:
            prefix = "CHAT_RATE_AND_TOKEN_BUDGET_RESERVED"
        return prefix if context_status == "CONTEXT_NOT_NEEDED" else f"{prefix}_{context_status}"

    @staticmethod
    def _with_context_degraded_disclosure(answer: str) -> str:
        maximum_body = _MAXIMUM_CHAT_ANSWER_CHARACTERS - len(CONTEXT_DEGRADED_PREFIX)
        return f"{CONTEXT_DEGRADED_PREFIX}{answer[:maximum_body].rstrip()}"

    @staticmethod
    def _retrieval_question(
        *,
        question: str,
        prior_user_utterances: Sequence[str],
    ) -> str:
        return "\n".join((question, *prior_user_utterances))

    @staticmethod
    def _bounded_user_utterances(
        user_utterances: Sequence[str],
        *,
        maximum_bytes: int,
    ) -> tuple[str, ...]:
        retained: list[str] = []
        remaining = maximum_bytes
        for utterance in reversed(user_utterances):
            normalized = utterance.strip()
            if not normalized or remaining <= 0:
                continue
            bounded = ChatService._truncate_utf8(normalized, maximum_bytes=remaining)
            if bounded:
                retained.append(bounded)
                remaining -= len(bounded.encode("utf-8"))
        retained.reverse()
        return tuple(retained)

    @staticmethod
    def _truncate_utf8(value: str, *, maximum_bytes: int) -> str:
        encoded = value.encode("utf-8")
        if len(encoded) <= maximum_bytes:
            return value
        return encoded[:maximum_bytes].decode("utf-8", errors="ignore").strip()

    @staticmethod
    def _validate_context_draft(draft: ChatConversationContextDraft) -> str:
        question = draft.resolved_question.strip()
        if (
            not question
            or len(question) > _MAXIMUM_CONTEXTUAL_QUESTION_CHARACTERS
            or _INTERNAL_EVIDENCE_MARKUP.search(question)
            or _UUID_TOKEN.search(question)
            or _CONTEXT_FORBIDDEN_IDENTIFIER.search(question)
        ):
            raise ValueError("The conversation context draft violates its bounded contract.")
        return question

    async def _retrieve(
        self,
        *,
        route: ChatRouteDecision,
        workspace_id: UUID,
        subject: SubjectAttributes,
        retrieval_subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        allowed_classifications: set[Classification],
        question: str,
        maximum_evidence: int,
        environment: EnvironmentAttributes,
        request_id: str,
        parent_resource_id: UUID,
        requested_graph_id: UUID | None,
    ) -> tuple[
        tuple[ChatEvidence, ...],
        tuple[str, ...],
        KnowledgeGraphChatScope | None,
        ChatCatalogSearchScope | None,
    ]:
        discovery_limit = self._discovery_limit(maximum_evidence)
        if route.selected_mode is ChatRetrievalMode.GRAPH:
            evidence, scope = await self._retrieve_graph(
                workspace_id=workspace_id,
                subject=subject,
                allowed_classifications=allowed_classifications,
                question=question,
                maximum_evidence=discovery_limit,
                environment=environment,
                request_id=request_id,
                parent_resource_id=parent_resource_id,
                requested_graph_id=requested_graph_id,
            )
            return evidence, (), scope, None
        retrieval_stages: tuple[str, ...] = ()
        catalog_search_scope: ChatCatalogSearchScope | None = None
        if route.selected_mode is ChatRetrievalMode.VECTOR:
            catalog_items: Sequence[CatalogAssetIndex] = ()
            governance_items: tuple[ChatEvidence, ...] = ()
            if self._vector_catalog is not None:
                vector_result = await self._vector_catalog.search(
                    subject=retrieval_subject,
                    access=access,
                    question=question,
                    limit=discovery_limit,
                )
                catalog_items = vector_result.items
                catalog_search_scope = vector_result.catalog_search_scope
                if vector_result.provider_invoked:
                    retrieval_stages = ("embedding",)
            if self._governance_evidence is not None:
                governance_items = await self._governance_evidence.search(
                    subject=retrieval_subject,
                    environment=environment,
                    request_id=f"{request_id}:governance-retrieval",
                    question=question,
                    limit=discovery_limit,
                )
                retrieval_stages = ("embedding",)
        else:
            governance_items = ()
            catalog_search_scope = ChatCatalogSearchScope(query=self._search_term(question))
            page = await self._catalog_index.search(
                subject=retrieval_subject,
                access=access,
                query=catalog_search_scope.query,
                filters={},
                cursor=None,
                limit=discovery_limit,
            )
            catalog_items = page.items
        catalog_evidence = await self._authorize_catalog_items(
            subject=subject,
            catalog_items=catalog_items,
            allowed_classifications=allowed_classifications,
            environment=environment,
            request_id=request_id,
            parent_resource_id=parent_resource_id,
        )
        eligible_governance = tuple(
            item
            for item in governance_items
            if item.workspace_id == workspace_id and item.classification in allowed_classifications
        )
        return (
            self._fuse_evidence(
                catalog_evidence,
                eligible_governance,
                limit=discovery_limit,
            ),
            retrieval_stages,
            None,
            catalog_search_scope,
        )

    @staticmethod
    def _discovery_limit(maximum_evidence: int) -> int:
        """Return a bounded recall window independent from the answer-context limit."""

        return min(
            max(maximum_evidence * 4, _MINIMUM_CHAT_DISCOVERY_CANDIDATES),
            MAXIMUM_CHAT_VECTOR_CANDIDATES,
        )

    @staticmethod
    def _catalog_search_handoff_query(
        *,
        scope: ChatCatalogSearchScope | None,
        evidence: Sequence[ChatEvidence],
    ) -> str | None:
        """Expose the exact canonical candidate query only when Catalog evidence is visible."""

        if scope is None or len(scope.query) > 500:
            return None
        if not any(item.source_type == "CATALOG_ASSET" for item in evidence):
            return None
        return scope.query

    @staticmethod
    def _fuse_evidence(
        catalog_evidence: Sequence[ChatEvidence],
        governance_evidence: Sequence[ChatEvidence],
        *,
        limit: int,
    ) -> tuple[ChatEvidence, ...]:
        """Interleave unique authorized evidence without expanding the discovery bound."""

        if limit <= 0:
            return ()
        sources = (catalog_evidence, governance_evidence)
        positions = [0] * len(sources)
        seen: set[UUID] = set()
        fused: list[ChatEvidence] = []
        while len(fused) < limit:
            appended = False
            for source_index, source in enumerate(sources):
                while positions[source_index] < len(source):
                    candidate = source[positions[source_index]]
                    positions[source_index] += 1
                    if candidate.chunk_id in seen:
                        continue
                    seen.add(candidate.chunk_id)
                    fused.append(candidate)
                    appended = True
                    break
                if len(fused) == limit:
                    break
            if not appended:
                break
        return tuple(fused)

    async def _authorize_catalog_items(
        self,
        *,
        subject: SubjectAttributes,
        catalog_items: Sequence[CatalogAssetIndex],
        allowed_classifications: set[Classification],
        environment: EnvironmentAttributes,
        request_id: str,
        parent_resource_id: UUID,
    ) -> tuple[ChatEvidence, ...]:
        eligible_items = tuple(
            item for item in catalog_items if item.classification in allowed_classifications
        )
        resources = tuple(
            ResourceAttributes(
                resource_id=asset.asset_id,
                workspace_id=asset.workspace_id,
                resource_type="catalog_asset",
                owner_department_id=asset.owner_department_id,
                system_id=asset.system_id,
                domain_id=asset.domain_id,
                classification=asset.classification,
                lifecycle=asset.lifecycle,
            )
            for asset in eligible_items
        )
        authorized_ids = {
            resource.resource_id
            for resource in await self._authorization.filter_authorized(
                subject=subject,
                resources=resources,
                action=Action.CATALOG_READ,
                environment=environment,
                request_id=request_id,
                parent_resource_id=parent_resource_id,
            )
        }
        return tuple(
            build_evidence_chunk(
                workspace_id=asset.workspace_id,
                resource_id=asset.asset_id,
                classification=asset.classification,
                system_id=asset.system_id,
                domain_id=asset.domain_id,
                owner_department_id=asset.owner_department_id,
                name=asset.name,
                description=_bounded_catalog_evidence_description(asset),
                source_locator=asset.external_urn,
                source_version=asset.source_version,
                effective_from=asset.observed_at,
                extraction_method="CATALOG_PROJECTION_V2",
            )
            for asset in eligible_items
            if asset.asset_id in authorized_ids
        )

    async def _retrieve_graph(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        allowed_classifications: set[Classification],
        question: str,
        maximum_evidence: int,
        environment: EnvironmentAttributes,
        request_id: str,
        parent_resource_id: UUID,
        requested_graph_id: UUID | None,
    ) -> tuple[tuple[ChatEvidence, ...], KnowledgeGraphChatScope | None]:
        assert self._graph_evidence is not None
        scope: KnowledgeGraphChatScope | None = None
        if self._graph_scope_resolver is not None:
            scope = await self._graph_scope_resolver.resolve_graph_scope(
                workspace_id=workspace_id,
                subject=subject,
                question=question,
                requested_graph_id=requested_graph_id,
                environment=environment,
                request_id=request_id,
            )
            if scope is None:
                return (), None
        search_term = self._search_term(question)
        maximum_classification = int(self._chat_ceiling(allowed_classifications, subject=subject))
        if scope is None:
            candidates = await self._graph_evidence.search_active_nodes(
                workspace_id=workspace_id,
                query=search_term,
                maximum_classification=maximum_classification,
                limit=maximum_evidence,
            )
        else:
            candidates = await self._graph_evidence.search_active_nodes(
                workspace_id=workspace_id,
                graph_id=scope.graph_id,
                release_id=scope.release_id,
                query=search_term,
                maximum_classification=maximum_classification,
                limit=maximum_evidence,
            )
        eligible = tuple(
            candidate
            for candidate in candidates
            if candidate.classification in allowed_classifications
            and candidate.evidence.workspace_id == workspace_id
            and candidate.evidence.classification == candidate.classification
            and (scope is None or candidate.graph_id == scope.graph_id)
        )
        resources = tuple(
            ResourceAttributes(
                resource_id=candidate.evidence.resource_id,
                workspace_id=workspace_id,
                resource_type="knowledge_node",
                owner_department_id=candidate.evidence.owner_department_id,
                system_id=candidate.evidence.system_id,
                domain_id=candidate.evidence.domain_id,
                classification=candidate.classification,
                lifecycle="PUBLISHED",
            )
            for candidate in eligible
        )
        authorized_ids = {
            resource.resource_id
            for resource in await self._authorization.filter_authorized(
                subject=subject,
                resources=resources,
                action=Action.KG_READ,
                environment=environment,
                request_id=request_id,
                parent_resource_id=parent_resource_id,
            )
        }
        return (
            tuple(
                candidate.evidence
                for candidate in eligible
                if candidate.evidence.resource_id in authorized_ids
            ),
            scope,
        )

    async def _rank(
        self,
        *,
        question: str,
        evidence: Sequence[ChatEvidence],
        route: ChatRouteDecision,
        workflow: list[ChatWorkflowEvent],
    ) -> tuple[
        tuple[ChatEvidence, ...],
        tuple[ChatEvidenceRanking, ...],
        bool,
        bool,
        int,
    ]:
        if not evidence:
            workflow.append(
                self._event(
                    ChatWorkflowStage.RERANKING,
                    ChatWorkflowStatus.SKIPPED,
                    "NO_RETRIEVED_EVIDENCE",
                )
            )
            return (), (), False, False, 0
        if self._reranker is None:
            workflow.append(
                self._event(
                    ChatWorkflowStage.RERANKING,
                    ChatWorkflowStatus.SKIPPED,
                    "RERANKER_NOT_CONFIGURED",
                )
            )
            method = f"{route.selected_mode.value}_RETRIEVAL_V1"
            return (
                tuple(evidence),
                tuple(
                    ChatEvidenceRanking(
                        chunk_id=item.chunk_id,
                        rank=index,
                        retrieval_method=method,
                    )
                    for index, item in enumerate(evidence, start=1)
                ),
                False,
                False,
                0,
            )
        try:
            ordered_ids = await self._reranker.rerank(
                question=question,
                evidence=evidence,
            )
            by_id = {item.chunk_id: item for item in evidence}
            if (
                not ordered_ids
                or len(ordered_ids) != len(set(ordered_ids))
                or any(chunk_id not in by_id for chunk_id in ordered_ids)
            ):
                raise ValueError("The reranker returned an invalid evidence selection.")
        except Exception:
            workflow.append(
                self._event(
                    ChatWorkflowStage.RERANKING,
                    ChatWorkflowStatus.FAILED,
                    "RERANKER_FAILED",
                )
            )
            return (), (), True, True, 0
        selected_ids = set(ordered_ids)
        selected = tuple(by_id[chunk_id] for chunk_id in ordered_ids)
        # A reranker is allowed to return only its configured top-N.  Those rows own the
        # answer-context prefix; the remaining already-authorized retrieval rows stay visible
        # in deterministic retrieval order in the wider, request-only discovery window.
        remainder = tuple(item for item in evidence if item.chunk_id not in selected_ids)
        ranked = (*selected, *remainder)
        workflow.append(
            self._event(
                ChatWorkflowStage.RERANKING,
                ChatWorkflowStatus.COMPLETED,
                "EVIDENCE_RERANKED",
            )
        )
        return (
            ranked,
            tuple(
                ChatEvidenceRanking(
                    chunk_id=item.chunk_id,
                    rank=index,
                    retrieval_method=(
                        "LOCAL_RERANKER_V1"
                        if item.chunk_id in selected_ids
                        else f"{route.selected_mode.value}_RETRIEVAL_V1"
                    ),
                )
                for index, item in enumerate(ranked, start=1)
            ),
            False,
            True,
            len(selected),
        )

    @staticmethod
    def _validate_general_draft(draft: ChatDraft) -> str:
        answer = draft.answer.strip()
        if (
            draft.cited_chunk_ids
            or not answer
            or len(answer) > _MAXIMUM_CHAT_ANSWER_CHARACTERS - len(GENERAL_KNOWLEDGE_PREFIX)
        ):
            return UNVERIFIABLE_ANSWER
        return f"{GENERAL_KNOWLEDGE_PREFIX}{answer}"

    async def _resolve_classification_access(
        self,
        *,
        subject: SubjectAttributes,
        now: datetime,
    ) -> ClassificationAccessSnapshot:
        if self._classification_access is None:
            return static_classification_access_floor()
        return await self._classification_access.resolve(
            workspace_id=subject.workspace_id,
            subject_id=subject.subject_id,
            now=now,
        )

    def _provider_bound_classifications(
        self,
        access: ClassificationAccessSnapshot,
        *,
        required_stages: tuple[InferenceStage, ...],
    ) -> set[Classification]:
        if access.posture is not ClassificationAccessPosture.GOVERNED or not required_stages:
            return set()
        profiles = {
            profile.provider_profile_version_id: profile for profile in access.provider_profiles
        }
        return {
            rule.classification
            for rule in access.rules
            if rule.search_mode is SearchMode.ABAC
            and rule.chat_mode is not ChatMode.DENY
            and all(
                self._stage_binding_matches(
                    rule=rule,
                    stage=stage,
                    profiles=profiles,
                )
                for stage in required_stages
            )
        }

    def _stage_binding_matches(
        self,
        *,
        rule: ClassificationRuleRecord,
        stage: InferenceStage,
        profiles: dict[UUID, ProviderProfileRecord],
    ) -> bool:
        binding = self._inference_runtime_bindings.get(stage)
        profile_id = self._rule_profile_id(rule, stage=stage)
        if binding is None or binding.provider_profile_version_id is None:
            return False
        if profile_id != binding.provider_profile_version_id:
            return False
        profile = profiles.get(profile_id)
        return (
            profile is not None
            and profile.server_route_key == binding.server_route_key
            and profile.provider_identity == binding.provider_identity
            and profile.model_identity == binding.model_identity
            and profile.deployment_identity == binding.deployment_identity
        )

    @staticmethod
    def _rule_profile_id(
        rule: ClassificationRuleRecord,
        *,
        stage: InferenceStage,
    ) -> UUID | None:
        if stage is InferenceStage.COMPOSITION:
            return rule.provider_profile_version_id
        if stage is InferenceStage.EMBEDDING:
            return rule.embedding_provider_profile_version_id
        return rule.reranker_provider_profile_version_id

    def _required_external_stages(
        self,
        route: ChatRouteDecision,
    ) -> tuple[InferenceStage, ...]:
        stages: list[InferenceStage] = []
        if route.selected_mode is ChatRetrievalMode.VECTOR and (
            self._vector_catalog is not None or self._governance_evidence is not None
        ):
            stages.append(InferenceStage.EMBEDDING)
        if self._reranker is not None:
            stages.append(InferenceStage.RERANKER)
        if self._composition_audit.external_service_used:
            stages.append(InferenceStage.COMPOSITION)
        return tuple(stages)

    def _audit_for_access(
        self,
        access: ClassificationAccessSnapshot,
        *,
        external_stages: tuple[str, ...],
    ) -> ChatCompositionAudit:
        base = self._composition_audit
        external_service_used = bool(external_stages)
        stage_profile_ids = tuple(
            (
                stage,
                binding.provider_profile_version_id,
            )
            for stage in external_stages
            if (
                (binding := self._inference_runtime_bindings.get(InferenceStage(stage))) is not None
                and binding.provider_profile_version_id is not None
            )
        )
        composition_binding = self._inference_runtime_bindings.get(InferenceStage.COMPOSITION)
        return replace(
            base,
            external_service_used=external_service_used,
            provider_profile_version_id=(
                composition_binding.provider_profile_version_id
                if external_service_used and composition_binding is not None
                else None
            ),
            classification_policy_id=access.policy_id,
            classification_policy_hash=access.policy_hash,
            classification_policy_version=access.policy_version,
            authorization_generation=access.authorization_generation,
            external_stages=external_stages,
            external_stage_provider_profile_version_ids=stage_profile_ids,
        )

    @staticmethod
    def _chat_retrieval_access(
        access: ClassificationAccessSnapshot,
        *,
        subject: SubjectAttributes,
    ) -> ClassificationAccessSnapshot:
        rules = tuple(
            ClassificationRuleRecord(
                classification=rule.classification,
                search_mode=(
                    SearchMode.ABAC
                    if rule.chat_mode is not ChatMode.DENY
                    and rule.classification <= subject.clearance
                    and rule.classification is not Classification.RESTRICTED
                    else SearchMode.DENY
                ),
                chat_mode=rule.chat_mode,
                provider_profile_version_id=rule.provider_profile_version_id,
                embedding_provider_profile_version_id=(rule.embedding_provider_profile_version_id),
                reranker_provider_profile_version_id=(rule.reranker_provider_profile_version_id),
            )
            for rule in access.rules
        )
        return replace(
            access,
            rules=rules,
            restricted_resource_ids=frozenset(),
            restricted_system_ids=frozenset(),
            restricted_domain_ids=frozenset(),
        )

    @staticmethod
    def _retrieval_access_for_allowed(
        access: ClassificationAccessSnapshot,
        allowed: set[Classification],
    ) -> ClassificationAccessSnapshot:
        return replace(
            access,
            rules=tuple(
                replace(
                    rule,
                    search_mode=(
                        rule.search_mode if rule.classification in allowed else SearchMode.DENY
                    ),
                )
                for rule in access.rules
            ),
        )

    @staticmethod
    def _chat_ceiling(
        allowed: set[Classification],
        *,
        subject: SubjectAttributes,
    ) -> Classification:
        visible = tuple(
            classification
            for classification in allowed
            if classification <= subject.clearance
            and classification is not Classification.RESTRICTED
        )
        if not visible:
            return Classification.PUBLIC
        return max(visible)

    @staticmethod
    def _search_term(question: str) -> str:
        tokens = [token.strip(".,?!:;()[]{}") for token in question.split()]
        candidates = [token for token in tokens if len(token) >= 2]
        return max(candidates, key=len)[:100] if candidates else question.strip()[:100]

    @staticmethod
    def _validate_draft(
        *,
        draft: ChatDraft,
        authorized_evidence: Sequence[ChatEvidence],
        workspace_id: UUID,
    ) -> tuple[str, tuple[ChatEvidence, ...]]:
        authorized_by_id = {item.chunk_id: item for item in authorized_evidence}
        cited_ids = draft.cited_chunk_ids
        invalid = (
            not draft.answer.strip()
            or not cited_ids
            or len(cited_ids) != len(set(cited_ids))
            or len(authorized_by_id) != len(authorized_evidence)
            or any(chunk_id not in authorized_by_id for chunk_id in cited_ids)
        )
        if invalid:
            return UNVERIFIABLE_ANSWER, ()
        cited = tuple(authorized_by_id[chunk_id] for chunk_id in cited_ids)
        if any(
            item.workspace_id != workspace_id or not evidence_chunk_is_valid(item) for item in cited
        ):
            return UNVERIFIABLE_ANSWER, ()
        answer = ChatService._redact_internal_evidence_identifiers(
            answer=draft.answer,
            evidence=cited,
        )
        if not answer:
            return UNVERIFIABLE_ANSWER, ()
        return answer, cited

    @staticmethod
    def _redact_internal_evidence_identifiers(
        *,
        answer: str,
        evidence: Sequence[ChatEvidence],
    ) -> str:
        """Keep citation identities in the governed evidence channel, not prose."""

        redacted = _INTERNAL_EVIDENCE_MARKUP.sub("", answer)
        for locator in sorted(
            {item.source_locator for item in evidence if item.source_locator},
            key=len,
            reverse=True,
        ):
            redacted = redacted.replace(locator, "")
        redacted = _UUID_TOKEN.sub("", redacted)
        redacted = _EMPTY_CITATION_LIST.sub("", redacted)
        redacted = re.sub(r"[ \t]{2,}", " ", redacted)
        redacted = re.sub(r"(?m)^[ \t,;:·-]+$", "", redacted)
        return re.sub(r"\n{3,}", "\n\n", redacted).strip()

    async def _final_reauthorize_citations(
        self,
        *,
        answer: str,
        evidence: Sequence[ChatEvidence],
        initial_access: ClassificationAccessSnapshot,
        required_external_stages: tuple[InferenceStage, ...],
        workspace_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        parent_resource_id: UUID,
        question: str,
        requested_graph_id: UUID | None,
        initial_graph_scope: KnowledgeGraphChatScope | None,
    ) -> tuple[str, tuple[ChatEvidence, ...]]:
        try:
            validation_time = utc_now()
            refreshed_subject = await self._subject_access.refresh_subject(
                subject=subject,
                now=validation_time,
            )
            if not refreshed_subject.active or self._subject_security_identity(
                refreshed_subject
            ) != self._subject_security_identity(subject):
                return UNVERIFIABLE_ANSWER, ()
            current_access = await self._resolve_classification_access(
                subject=refreshed_subject,
                now=validation_time,
            )
            if self._access_security_identity(current_access) != self._access_security_identity(
                initial_access
            ):
                return UNVERIFIABLE_ANSWER, ()
            current_chat_access = self._chat_retrieval_access(
                current_access,
                subject=refreshed_subject,
            )
            allowed = {
                rule.classification
                for rule in current_chat_access.rules
                if rule.search_mode is SearchMode.ABAC
            }
            if required_external_stages:
                provider_bound = self._provider_bound_classifications(
                    current_chat_access,
                    required_stages=required_external_stages,
                )
                if not provider_bound:
                    return UNVERIFIABLE_ANSWER, ()
                allowed.intersection_update(provider_bound)
            current_retrieval_access = self._retrieval_access_for_allowed(
                current_chat_access,
                allowed,
            )
            if any(
                item.workspace_id != workspace_id or item.classification not in allowed
                for item in evidence
            ):
                return UNVERIFIABLE_ANSWER, ()

            final_environment = replace(
                environment,
                requested_at=validation_time,
            )
            resource_groups: dict[Action, list[ResourceAttributes]] = {
                Action.CATALOG_READ: [],
                Action.KG_READ: [],
            }
            catalog_evidence = tuple(
                item for item in evidence if item.source_type == "CATALOG_ASSET"
            )
            knowledge_evidence = tuple(
                item for item in evidence if item.source_type == "KNOWLEDGE_NODE"
            )
            governance_evidence = tuple(
                item for item in evidence if item.source_type == "GOVERNANCE_DOCUMENT"
            )
            if len(catalog_evidence) + len(knowledge_evidence) + len(governance_evidence) != len(
                evidence
            ):
                return UNVERIFIABLE_ANSWER, ()

            for item in catalog_evidence:
                detail = await self._catalog_index.get_authorized_asset(
                    subject=refreshed_subject,
                    access=current_retrieval_access,
                    asset_id=item.resource_id,
                )
                if detail is None:
                    return UNVERIFIABLE_ANSWER, ()
                index = detail.index
                canonical = build_evidence_chunk(
                    workspace_id=index.workspace_id,
                    resource_id=index.asset_id,
                    classification=index.classification,
                    system_id=index.system_id,
                    domain_id=index.domain_id,
                    owner_department_id=index.owner_department_id,
                    name=index.name,
                    description=_bounded_catalog_evidence_description(index),
                    source_locator=index.external_urn,
                    source_version=index.source_version,
                    effective_from=index.observed_at,
                    extraction_method="CATALOG_PROJECTION_V2",
                )
                if canonical != item or index.lifecycle != "ACTIVE":
                    return UNVERIFIABLE_ANSWER, ()
                resource_groups[Action.CATALOG_READ].append(
                    ResourceAttributes(
                        resource_id=index.asset_id,
                        workspace_id=index.workspace_id,
                        resource_type="catalog_asset",
                        owner_department_id=index.owner_department_id,
                        system_id=index.system_id,
                        domain_id=index.domain_id,
                        classification=index.classification,
                        lifecycle=index.lifecycle,
                    )
                )

            if knowledge_evidence:
                if self._graph_evidence is None:
                    return UNVERIFIABLE_ANSWER, ()
                if initial_graph_scope is not None:
                    if self._graph_scope_resolver is None:
                        return UNVERIFIABLE_ANSWER, ()
                    current_scope = await self._graph_scope_resolver.resolve_graph_scope(
                        workspace_id=workspace_id,
                        subject=refreshed_subject,
                        question=question,
                        requested_graph_id=requested_graph_id,
                        environment=final_environment,
                        request_id=f"{request_id}:graph-scope-final",
                    )
                    if current_scope != initial_graph_scope:
                        return UNVERIFIABLE_ANSWER, ()
                current_candidates = await self._graph_evidence.get_active_nodes_by_resource_ids(
                    workspace_id=workspace_id,
                    resource_ids=tuple(item.resource_id for item in knowledge_evidence),
                    graph_id=(
                        initial_graph_scope.graph_id if initial_graph_scope is not None else None
                    ),
                    release_id=(
                        initial_graph_scope.release_id if initial_graph_scope is not None else None
                    ),
                )
                candidates_by_id: dict[UUID, list[ChatEvidence]] = {}
                for candidate in current_candidates:
                    candidates_by_id.setdefault(
                        candidate.evidence.resource_id,
                        [],
                    ).append(candidate.evidence)
                for item in knowledge_evidence:
                    candidates = candidates_by_id.get(item.resource_id, [])
                    if len(candidates) != 1 or candidates[0] != item:
                        return UNVERIFIABLE_ANSWER, ()
                    resource_groups[Action.KG_READ].append(
                        ResourceAttributes(
                            resource_id=item.resource_id,
                            workspace_id=item.workspace_id,
                            resource_type="knowledge_node",
                            owner_department_id=item.owner_department_id,
                            system_id=item.system_id,
                            domain_id=item.domain_id,
                            classification=item.classification,
                            lifecycle="PUBLISHED",
                        )
                    )
            final_authorized_ids: set[UUID] = set()
            if governance_evidence:
                if self._governance_evidence is None:
                    return UNVERIFIABLE_ANSWER, ()
                current_governance = await self._governance_evidence.get_current(
                    subject=refreshed_subject,
                    environment=final_environment,
                    request_id=f"{request_id}:governance-citation-final",
                    resource_ids=tuple(item.resource_id for item in governance_evidence),
                )
                governance_by_resource: dict[UUID, list[ChatEvidence]] = {}
                for current in current_governance:
                    governance_by_resource.setdefault(current.resource_id, []).append(current)
                for item in governance_evidence:
                    candidates = governance_by_resource.get(item.resource_id, [])
                    if len(candidates) != 1 or candidates[0] != item:
                        return UNVERIFIABLE_ANSWER, ()
                    final_authorized_ids.add(item.resource_id)
            for action, resources in resource_groups.items():
                if not resources:
                    continue
                authorized = await self._authorization.filter_authorized(
                    subject=refreshed_subject,
                    resources=tuple(resources),
                    action=action,
                    environment=final_environment,
                    request_id=f"{request_id}:citation-final",
                    parent_resource_id=parent_resource_id,
                )
                final_authorized_ids.update(resource.resource_id for resource in authorized)
            if final_authorized_ids != {item.resource_id for item in evidence}:
                return UNVERIFIABLE_ANSWER, ()
        except Exception:
            return UNVERIFIABLE_ANSWER, ()
        return answer, tuple(evidence)

    @staticmethod
    def _subject_security_identity(subject: SubjectAttributes) -> tuple[object, ...]:
        return (
            subject.subject_id,
            subject.workspace_id,
            subject.active,
            subject.department_id,
            subject.groups,
            subject.job_function,
            subject.clearance,
            subject.allowed_system_ids,
            subject.allowed_domain_ids,
            subject.allowed_actions,
            subject.denied_actions,
            subject.authentication_time,
            subject.authentication_assurance,
        )

    @staticmethod
    def _access_security_identity(
        access: ClassificationAccessSnapshot,
    ) -> tuple[object, ...]:
        return (
            access.posture,
            access.policy_id,
            access.policy_hash,
            access.policy_version,
            access.required_jurisdiction,
            access.authorization_generation,
            access.rules,
            access.restricted_resource_ids,
            access.restricted_system_ids,
            access.restricted_domain_ids,
            access.provider_profiles,
            access.admin_quarantine_review,
        )

    @staticmethod
    def _estimated_token_envelope(
        question: str,
        *,
        maximum_evidence: int,
        retrieval_mode: ChatRetrievalMode = ChatRetrievalMode.GENERAL,
        reranker_enabled: bool = False,
        route_classifier_enabled: bool = False,
        conversation_context_bytes: int = 0,
        context_compression_enabled: bool = False,
    ) -> int:
        # One reserved token per possible UTF-8 byte deliberately overstates
        # provider tokenization. The base covers the bounded composer request
        # and output. VECTOR and reranker inputs are additive because they are
        # separate provider invocations in the same request.
        question_bytes = len(question.encode("utf-8")) + max(conversation_context_bytes, 0)
        total = question_bytes + (maximum_evidence * 16_384) + 8_192 + 1_024
        if retrieval_mode is ChatRetrievalMode.VECTOR:
            candidate_count = min(
                max(maximum_evidence * 4, 8),
                MAXIMUM_CHAT_VECTOR_CANDIDATES,
            )
            total += (
                question_bytes + (candidate_count * MAXIMUM_CHAT_VECTOR_TEXT_CHARACTERS * 4) + 8_192
            )
        if reranker_enabled:
            total += question_bytes + (maximum_evidence * 16_384) + 8_192
        if route_classifier_enabled:
            # The fixed classifier receives bounded user intent and emits one mode plus
            # one bounded search question. Reserve its full output before invocation.
            total += question_bytes + 2_048 + (_MAXIMUM_CONTEXTUAL_QUESTION_CHARACTERS * 4)
        if context_compression_enabled:
            # Compression is a separate fixed provider call. Reserve the bounded
            # source, fixed prompt and worst-case contextualized question before it runs.
            total += question_bytes + 8_192 + (_MAXIMUM_CONTEXTUAL_QUESTION_CHARACTERS * 4)
        return total

    @staticmethod
    def _budget_policy_scope(access: ClassificationAccessSnapshot) -> str:
        if access.posture is ClassificationAccessPosture.STATIC_FLOOR:
            return "static-floor-v1"
        if (
            access.policy_id is None
            or access.policy_hash is None
            or access.policy_version is None
            or access.authorization_generation is None
        ):
            raise ValueError("The governed Chat budget scope is incomplete.")
        return (
            f"governed-{access.policy_id}-{access.policy_version}-"
            f"{access.authorization_generation}-{access.policy_hash}"
        )

    @staticmethod
    def _event(
        stage: ChatWorkflowStage,
        status: ChatWorkflowStatus,
        detail_code: str,
    ) -> ChatWorkflowEvent:
        return ChatWorkflowEvent(
            stage=stage,
            status=status,
            detail_code=detail_code,
        )
