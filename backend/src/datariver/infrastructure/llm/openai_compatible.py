from __future__ import annotations

from collections.abc import Sequence

from datariver.application.dto import ChatDraft, ChatEvidence
from datariver.infrastructure.knowledge.openai_compatible import OpenAIJsonTransport
from datariver.infrastructure.llm.ollama import (
    grounded_chat_request_payload,
    parse_grounded_chat_response,
)


class OpenAICompatibleGroundedChatComposer:
    """Use one fixed tool-call contract against an operator-approved endpoint."""

    def __init__(self, *, model: str, transport: OpenAIJsonTransport) -> None:
        self._model = model
        self._transport = transport

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
            document=grounded_chat_request_payload(
                model=self._model,
                question=question,
                evidence=evidence,
            ),
        )
        return parse_grounded_chat_response(result)
