from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from datariver.application.classification_access import (
    ClassificationAccessSnapshot,
    static_classification_access_floor,
)
from datariver.application.dto import (
    CatalogAssetDetail,
    CatalogAssetIndex,
    CatalogPage,
    ChatEvidence,
    ChatMessageRecord,
    ChatSessionRecord,
)
from datariver.application.errors import ChatExternalAdapterInvocationError
from datariver.application.evidence import build_evidence_chunk
from datariver.application.services.authorization import (
    AuthorizationService,
    NullDecisionWriter,
)
from datariver.application.services.chat_history import ChatHistoryService
from datariver.application.services.chat_routing import DeterministicChatQuestionRouter
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.chat import (
    ChatAdapterState,
    ChatRetrievalMode,
    ChatRouteReason,
)
from datariver.domain.common import ForbiddenError
from datariver.domain.knowledge_pipeline import (
    EmbeddingBatch,
    ModelBinding,
    PageEmbedding,
    PdfPage,
)
from datariver.infrastructure.llm.reranker import LocalLlamaCppEvidenceReranker
from datariver.infrastructure.llm.vector_catalog import BoundedCatalogVectorReader


def test_router_preserves_explicit_modes_and_never_silently_falls_back() -> None:
    router = DeterministicChatQuestionRouter()

    unavailable = router.route(
        question="show downstream impact",
        requested_mode=ChatRetrievalMode.GRAPH,
        vector_available=True,
        graph_available=False,
    )
    semantic = router.route(
        question="설명이 비슷한 테이블을 찾아줘",
        requested_mode=ChatRetrievalMode.AUTO,
        vector_available=True,
        graph_available=False,
    )

    assert unavailable.selected_mode is ChatRetrievalMode.GRAPH
    assert unavailable.reason is ChatRouteReason.EXPLICIT_SELECTION
    assert unavailable.adapter_state is ChatAdapterState.UNAVAILABLE
    assert semantic.selected_mode is ChatRetrievalMode.VECTOR
    assert semantic.reason is ChatRouteReason.SEMANTIC_INTENT
    assert semantic.adapter_state is ChatAdapterState.READY


class _CatalogIndex:
    def __init__(self, items: Sequence[CatalogAssetIndex]) -> None:
        self.items = tuple(items)
        self.seen_limit: int | None = None
        self.seen_query: str | None = None

    async def search(
        self,
        *,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        query: str,
        filters: dict[str, Any],
        cursor: str | None,
        limit: int,
    ) -> CatalogPage:
        del subject, access, filters, cursor
        self.seen_limit = limit
        self.seen_query = query
        return CatalogPage(
            items=self.items[:limit],
            next_cursor=None,
            observed_at=datetime.now(UTC),
        )

    async def get_authorized_asset(
        self,
        *,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        asset_id: UUID,
    ) -> CatalogAssetDetail | None:
        del subject, access, asset_id
        return None

    async def get_authorized_assets_by_external_urns(
        self,
        *,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        external_urns: Sequence[str],
    ) -> Sequence[CatalogAssetIndex]:
        del subject, access, external_urns
        return ()


class _Embedding:
    async def embed_pages(
        self,
        *,
        pages: Sequence[PdfPage],
        binding: ModelBinding,
    ) -> EmbeddingBatch:
        assert len(pages) == 3
        return EmbeddingBatch(
            binding=binding,
            embeddings=(
                PageEmbedding(page_number=1, vector=(1.0, 0.0)),
                PageEmbedding(page_number=2, vector=(0.0, 1.0)),
                PageEmbedding(page_number=3, vector=(1.0, 0.0)),
            ),
            input_tokens=None,
        )


class _FailingEmbedding:
    async def embed_pages(
        self,
        *,
        pages: Sequence[PdfPage],
        binding: ModelBinding,
    ) -> EmbeddingBatch:
        del pages, binding
        raise RuntimeError("provider unavailable")


class _MalformedEmbedding:
    async def embed_pages(
        self,
        *,
        pages: Sequence[PdfPage],
        binding: ModelBinding,
    ) -> EmbeddingBatch:
        del pages
        return EmbeddingBatch(
            binding=binding,
            embeddings=(PageEmbedding(page_number=1, vector=(1.0, 0.0)),),
            input_tokens=None,
        )


async def test_vector_reader_ranks_only_the_bounded_catalog_window() -> None:
    workspace_id = uuid4()
    first = _asset(workspace_id, name="First")
    second = _asset(workspace_id, name="Second")
    index = _CatalogIndex((first, second))
    binding = ModelBinding.activated(
        provider="test-provider",
        model="operator-selected-embedding",
        prompt_version="embedding-v1",
        tool_schema_version="openai-embeddings-v1",
        configuration_version=None,
        configuration_hash=None,
        adapter_contract="openai-compatible-embeddings-v1",
        deployment_configuration_hash="a" * 64,
    )
    reader = BoundedCatalogVectorReader(
        catalog_index=index,
        embedding=_Embedding(),
        binding=binding,
    )

    result = await reader.search(
        subject=_subject(workspace_id),
        access=static_classification_access_floor(),
        question="find a matching description",
        limit=2,
    )

    assert result.items == (second, first)
    assert result.provider_invoked is True
    assert index.seen_query == ""
    assert index.seen_limit == 8


async def test_vector_reader_marks_only_failures_after_embedding_invocation() -> None:
    workspace_id = uuid4()
    index = _CatalogIndex((_asset(workspace_id, name="First"),))
    binding = ModelBinding.activated(
        provider="test-provider",
        model="operator-selected-embedding",
        prompt_version="embedding-v1",
        tool_schema_version="openai-embeddings-v1",
        configuration_version=None,
        configuration_hash=None,
        adapter_contract="openai-compatible-embeddings-v1",
        deployment_configuration_hash="a" * 64,
    )
    reader = BoundedCatalogVectorReader(
        catalog_index=index,
        embedding=_FailingEmbedding(),
        binding=binding,
    )

    with pytest.raises(ChatExternalAdapterInvocationError) as captured:
        await reader.search(
            subject=_subject(workspace_id),
            access=static_classification_access_floor(),
            question="find a matching description",
            limit=2,
        )

    assert captured.value.stage == "embedding"


async def test_vector_reader_marks_malformed_post_invocation_result() -> None:
    workspace_id = uuid4()
    index = _CatalogIndex((_asset(workspace_id, name="First"),))
    binding = ModelBinding.activated(
        provider="test-provider",
        model="operator-selected-embedding",
        prompt_version="embedding-v1",
        tool_schema_version="openai-embeddings-v1",
        configuration_version=None,
        configuration_hash=None,
        adapter_contract="openai-compatible-embeddings-v1",
        deployment_configuration_hash="a" * 64,
    )
    reader = BoundedCatalogVectorReader(
        catalog_index=index,
        embedding=_MalformedEmbedding(),
        binding=binding,
    )

    with pytest.raises(ChatExternalAdapterInvocationError) as captured:
        await reader.search(
            subject=_subject(workspace_id),
            access=static_classification_access_floor(),
            question="find a matching description",
            limit=2,
        )

    assert captured.value.stage == "embedding"


async def test_reranker_validates_and_returns_the_provider_order() -> None:
    workspace_id = uuid4()
    evidence = (
        _evidence(workspace_id, name="First"),
        _evidence(workspace_id, name="Second"),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("http://127.0.0.1:11435/v1/rerank")
        return httpx.Response(
            200,
            json={
                "model": "operator-selected-reranker",
                "results": [
                    {"index": 1, "relevance_score": 5.0},
                    {"index": 0, "relevance_score": 1.0},
                ],
            },
        )

    adapter = LocalLlamaCppEvidenceReranker(
        base_url="http://127.0.0.1:11435/v1",
        model="operator-selected-reranker",
        timeout_seconds=5,
        top_n=2,
        transport=httpx.MockTransport(handler),
    )

    assert await adapter.rerank(question="catalog", evidence=evidence) == (
        evidence[1].chunk_id,
        evidence[0].chunk_id,
    )


class _History:
    def __init__(self) -> None:
        self.owner_id: UUID | None = None
        self.session_owner_id: UUID | None = None

    async def get_session_owner(
        self,
        *,
        workspace_id: UUID,
        session_id: UUID,
    ) -> UUID | None:
        del workspace_id, session_id
        return self.session_owner_id

    async def list_sessions(
        self,
        *,
        workspace_id: UUID,
        owner_id: UUID,
        limit: int,
    ) -> Sequence[ChatSessionRecord]:
        del workspace_id, limit
        self.owner_id = owner_id
        return ()

    async def list_messages(
        self,
        *,
        workspace_id: UUID,
        owner_id: UUID,
        session_id: UUID,
        limit: int,
    ) -> Sequence[ChatMessageRecord]:
        del workspace_id, owner_id, session_id, limit
        return ()

    async def set_favorite(
        self,
        *,
        workspace_id: UUID,
        owner_id: UUID,
        session_id: UUID,
        expected_version: int,
        is_favorite: bool,
    ) -> ChatSessionRecord:
        del workspace_id, owner_id, session_id, expected_version, is_favorite
        raise AssertionError("not used")


async def test_history_service_authorizes_before_owner_scoped_access() -> None:
    workspace_id = uuid4()
    allowed = _subject(workspace_id, allowed_actions=frozenset({Action.CHAT_QUERY}))
    denied = _subject(workspace_id, allowed_actions=frozenset())
    history = _History()
    service = ChatHistoryService(
        history=history,
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    )
    environment = EnvironmentAttributes(requested_at=datetime.now(UTC))

    assert (
        await service.list_sessions(
            workspace_id=workspace_id,
            subject=allowed,
            environment=environment,
            request_id="history-allowed",
            limit=50,
        )
        == ()
    )
    assert history.owner_id == allowed.subject_id

    history.owner_id = None
    with pytest.raises(ForbiddenError):
        await service.list_sessions(
            workspace_id=workspace_id,
            subject=denied,
            environment=environment,
            request_id="history-denied",
            limit=50,
        )
    assert history.owner_id is None


async def test_history_service_rejects_non_owner_before_session_read() -> None:
    workspace_id = uuid4()
    subject = _subject(
        workspace_id,
        allowed_actions=frozenset({Action.CHAT_QUERY}),
    )
    history = _History()
    history.session_owner_id = uuid4()
    service = ChatHistoryService(
        history=history,
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    )

    with pytest.raises(ForbiddenError):
        await service.list_messages(
            workspace_id=workspace_id,
            session_id=uuid4(),
            subject=subject,
            environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
            request_id="history-owner-mismatch",
            limit=200,
        )


def _asset(workspace_id: UUID, *, name: str) -> CatalogAssetIndex:
    return CatalogAssetIndex(
        asset_id=uuid4(),
        workspace_id=workspace_id,
        external_urn=f"urn:test:{name}",
        asset_type="DATASET",
        name=name,
        description=f"{name} description",
        platform="postgres",
        domain_id=None,
        system_id=None,
        owner_department_id=None,
        classification=Classification.INTERNAL,
        lifecycle="ACTIVE",
        source_version="v1",
        observed_at=datetime.now(UTC),
    )


def _subject(
    workspace_id: UUID,
    *,
    allowed_actions: frozenset[Action] = frozenset(),
) -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function=None,
        clearance=Classification.INTERNAL,
        allowed_actions=allowed_actions,
    )


def _evidence(workspace_id: UUID, *, name: str) -> ChatEvidence:
    return build_evidence_chunk(
        workspace_id=workspace_id,
        resource_id=uuid4(),
        classification=Classification.INTERNAL,
        system_id=None,
        domain_id=None,
        owner_department_id=None,
        name=name,
        description=f"{name} description",
        source_locator=f"urn:test:{name}",
        source_version="v1",
        effective_from=datetime.now(UTC),
        extraction_method="CATALOG_PROJECTION_V1",
    )
