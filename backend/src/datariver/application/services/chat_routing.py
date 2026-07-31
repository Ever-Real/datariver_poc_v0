from __future__ import annotations

from datariver.application.dto import ChatRouteDecision
from datariver.application.ports import ChatQuestionRouter, ChatRouteIntentClassifier
from datariver.domain.chat import (
    ChatAdapterState,
    ChatRetrievalMode,
    ChatRouteReason,
)


class DeterministicChatQuestionRouter(ChatQuestionRouter):
    """Use an explicit route, otherwise retain the non-model general baseline.

    This router deliberately has no intent keyword list. Deployments that configure a
    composition-model classifier use :class:`SemanticChatQuestionRouter` instead.
    """

    @property
    def requires_composition_inference(self) -> bool:
        return False

    async def route(
        self,
        *,
        question: str,
        requested_mode: ChatRetrievalMode,
        vector_available: bool,
        graph_available: bool,
        inference_allowed: bool,
    ) -> ChatRouteDecision:
        del question, inference_allowed
        if requested_mode is not ChatRetrievalMode.AUTO:
            return self._decision(
                requested_mode=requested_mode,
                selected_mode=requested_mode,
                reason=ChatRouteReason.EXPLICIT_SELECTION,
                vector_available=vector_available,
                graph_available=graph_available,
            )
        return self._decision(
            requested_mode=requested_mode,
            selected_mode=ChatRetrievalMode.GENERAL,
            reason=ChatRouteReason.GENERAL_DEFAULT,
            vector_available=vector_available,
            graph_available=graph_available,
        )

    @classmethod
    def _decision(
        cls,
        *,
        requested_mode: ChatRetrievalMode,
        selected_mode: ChatRetrievalMode,
        reason: ChatRouteReason,
        vector_available: bool,
        graph_available: bool,
        adapter_state: ChatAdapterState | None = None,
    ) -> ChatRouteDecision:
        return ChatRouteDecision(
            requested_mode=requested_mode,
            selected_mode=selected_mode,
            reason=reason,
            adapter_state=adapter_state
            or cls._state(
                selected_mode,
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


class SemanticChatQuestionRouter(DeterministicChatQuestionRouter):
    """Classify only AUTO intent through a fixed enum-only inference contract."""

    def __init__(self, *, classifier: ChatRouteIntentClassifier | None) -> None:
        self._classifier = classifier

    @property
    def requires_composition_inference(self) -> bool:
        return self._classifier is not None

    async def route(
        self,
        *,
        question: str,
        requested_mode: ChatRetrievalMode,
        vector_available: bool,
        graph_available: bool,
        inference_allowed: bool,
    ) -> ChatRouteDecision:
        if requested_mode is not ChatRetrievalMode.AUTO:
            return await super().route(
                question=question,
                requested_mode=requested_mode,
                vector_available=vector_available,
                graph_available=graph_available,
                inference_allowed=inference_allowed,
            )
        if self._classifier is None:
            return await super().route(
                question=question,
                requested_mode=requested_mode,
                vector_available=vector_available,
                graph_available=graph_available,
                inference_allowed=inference_allowed,
            )
        if not inference_allowed:
            return self._unavailable_decision(
                requested_mode=requested_mode,
                vector_available=vector_available,
                graph_available=graph_available,
            )
        try:
            selected_mode = await self._classifier.classify_route(question=question)
        except Exception:
            return self._unavailable_decision(
                requested_mode=requested_mode,
                vector_available=vector_available,
                graph_available=graph_available,
            )
        if selected_mode not in {
            ChatRetrievalMode.GENERAL,
            ChatRetrievalMode.VECTOR,
            ChatRetrievalMode.GRAPH,
        }:
            return self._unavailable_decision(
                requested_mode=requested_mode,
                vector_available=vector_available,
                graph_available=graph_available,
            )
        return self._decision(
            requested_mode=requested_mode,
            selected_mode=selected_mode,
            reason=(
                ChatRouteReason.GRAPH_INTENT
                if selected_mode is ChatRetrievalMode.GRAPH
                else (
                    ChatRouteReason.SEMANTIC_INTENT
                    if selected_mode is ChatRetrievalMode.VECTOR
                    else ChatRouteReason.GENERAL_DEFAULT
                )
            ),
            vector_available=vector_available,
            graph_available=graph_available,
        )

    def _unavailable_decision(
        self,
        *,
        requested_mode: ChatRetrievalMode,
        vector_available: bool,
        graph_available: bool,
    ) -> ChatRouteDecision:
        return self._decision(
            requested_mode=requested_mode,
            selected_mode=ChatRetrievalMode.GENERAL,
            reason=ChatRouteReason.GENERAL_DEFAULT,
            vector_available=vector_available,
            graph_available=graph_available,
            adapter_state=ChatAdapterState.UNAVAILABLE,
        )
