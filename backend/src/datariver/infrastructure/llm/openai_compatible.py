from __future__ import annotations

from collections.abc import Sequence

from datariver.application.dto import ChatDraft, ChatEvidence
from datariver.domain.chat import ChatRetrievalMode
from datariver.infrastructure.knowledge.openai_compatible import (
    OpenAICompatibleChatRequestOptions,
    OpenAIJsonTransport,
)
from datariver.infrastructure.llm.ollama import (
    general_chat_request_payload,
    grounded_chat_request_payload,
    parse_general_chat_response,
    parse_grounded_chat_response,
    parse_route_classification_response,
    route_classification_request_payload,
)


class OpenAICompatibleGroundedChatComposer:
    """Use one fixed tool-call contract against an operator-approved endpoint."""

    def __init__(
        self,
        *,
        model: str,
        transport: OpenAIJsonTransport,
        temperature: float = 0.0,
        top_p: float | None = None,
        repetition_penalty: float | None = None,
        enable_thinking: bool = False,
    ) -> None:
        self._model = model
        self._transport = transport
        self._chat_options = OpenAICompatibleChatRequestOptions(
            temperature=temperature,
            top_p=top_p,
            repetition_penalty=repetition_penalty,
            enable_thinking=enable_thinking,
        )
        self._route_options = OpenAICompatibleChatRequestOptions(
            temperature=0.0,
            enable_thinking=False,
        )

    async def compose(
        self,
        *,
        question: str,
        evidence: Sequence[ChatEvidence],
    ) -> ChatDraft:
        if not evidence:
            return ChatDraft(answer="", cited_chunk_ids=())
        result = await self._transport.post_json(
            path="/chat/completions",
            document=self._chat_options.apply(
                grounded_chat_request_payload(
                    model=self._model,
                    question=question,
                    evidence=evidence,
                )
            ),
        )
        return parse_grounded_chat_response(result)

    async def compose_general(
        self,
        *,
        question: str,
    ) -> ChatDraft:
        result = await self._transport.post_json(
            path="/chat/completions",
            document=self._chat_options.apply(
                general_chat_request_payload(
                    model=self._model,
                    question=question,
                )
            ),
        )
        return parse_general_chat_response(result)

    async def classify_route(
        self,
        *,
        question: str,
    ) -> ChatRetrievalMode:
        result = await self._transport.post_json(
            path="/chat/completions",
            document=self._route_options.apply(
                route_classification_request_payload(
                    model=self._model,
                    question=question,
                )
            ),
        )
        return parse_route_classification_response(result)
