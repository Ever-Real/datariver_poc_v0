from __future__ import annotations

from datariver.application.dto import ChatRouteDecision
from datariver.application.ports import ChatQuestionRouter
from datariver.domain.chat import (
    ChatAdapterState,
    ChatRetrievalMode,
    ChatRouteReason,
)

_GRAPH_TERMS = frozenset(
    {
        "lineage",
        "upstream",
        "downstream",
        "impact",
        "dependency",
        "relationship",
        "계보",
        "상류",
        "하류",
        "영향",
        "의존",
        "관계",
        "연결",
    }
)
_SEMANTIC_TERMS = frozenset(
    {
        "semantic",
        "similar",
        "meaning",
        "description",
        "discover",
        "vector",
        "embedding",
        "의미",
        "유사",
        "설명",
        "찾아",
        "어떤 테이블",
        "벡터",
        "임베딩",
    }
)


class DeterministicChatQuestionRouter(ChatQuestionRouter):
    """Select one retrieval contract without calling a model or accepting executable input."""

    def route(
        self,
        *,
        question: str,
        requested_mode: ChatRetrievalMode,
        vector_available: bool,
        graph_available: bool,
    ) -> ChatRouteDecision:
        if requested_mode is not ChatRetrievalMode.AUTO:
            return ChatRouteDecision(
                requested_mode=requested_mode,
                selected_mode=requested_mode,
                reason=ChatRouteReason.EXPLICIT_SELECTION,
                adapter_state=self._state(
                    requested_mode,
                    vector_available=vector_available,
                    graph_available=graph_available,
                ),
            )

        normalized = " ".join(question.casefold().split())
        if any(term in normalized for term in _GRAPH_TERMS):
            selected = ChatRetrievalMode.GRAPH
            reason = ChatRouteReason.GRAPH_INTENT
        elif any(term in normalized for term in _SEMANTIC_TERMS):
            selected = ChatRetrievalMode.VECTOR
            reason = ChatRouteReason.SEMANTIC_INTENT
        else:
            selected = ChatRetrievalMode.GENERAL
            reason = ChatRouteReason.GENERAL_DEFAULT
        return ChatRouteDecision(
            requested_mode=requested_mode,
            selected_mode=selected,
            reason=reason,
            adapter_state=self._state(
                selected,
                vector_available=vector_available,
                graph_available=graph_available,
            ),
        )

    @staticmethod
    def _state(
        selected: ChatRetrievalMode,
        *,
        vector_available: bool,
        graph_available: bool,
    ) -> ChatAdapterState:
        if selected is ChatRetrievalMode.VECTOR and not vector_available:
            return ChatAdapterState.UNAVAILABLE
        if selected is ChatRetrievalMode.GRAPH and not graph_available:
            return ChatAdapterState.UNAVAILABLE
        return ChatAdapterState.READY
