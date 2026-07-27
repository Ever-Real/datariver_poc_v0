from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from datariver.application.dto import ChatEvidence
from datariver.application.evidence import build_evidence_chunk
from datariver.application.services.chat import ChatService
from datariver.domain.authz import Classification
from datariver.domain.common import ValidationError
from datariver.infrastructure.llm.ollama import (
    LocalOllamaChatComposer,
    ollama_native_general_chat_request_payload,
    ollama_native_grounded_chat_request_payload,
)


def _evidence() -> ChatEvidence:
    return build_evidence_chunk(
        workspace_id=uuid4(),
        resource_id=uuid4(),
        classification=Classification.INTERNAL,
        system_id=None,
        domain_id=None,
        owner_department_id=None,
        name="Authorized wafer yield evidence",
        description="Yield is measured after final inspection.",
        source_locator="urn:datariver:test:wafer-yield",
        source_version="v1",
        effective_from=datetime(2026, 7, 20, tzinfo=UTC),
        extraction_method="CATALOG_PROJECTION_V1",
    )


def test_budget_envelope_covers_the_maximum_serialized_provider_request() -> None:
    question = "𐀀" * 4_000
    maximum_evidence = tuple(
        replace(
            _evidence(),
            chunk_id=uuid4(),
            name="𐀀" * 500,
            description="𐀀" * 10_000,
            source_locator="𐀀" * 4_096,
            source_version="𐀀" * 255,
        )
        for _ in range(10)
    )
    payload = ollama_native_grounded_chat_request_payload(
        model="operator-selected-model",
        question=question,
        evidence=maximum_evidence,
        context_tokens=8_192,
    )
    serialized_request_bytes = len(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )

    assert (
        ChatService._estimated_token_envelope(
            question,
            maximum_evidence=len(maximum_evidence),
        )
        >= serialized_request_bytes + 1_024
    )


@pytest.mark.asyncio
async def test_composer_uses_one_fixed_tool_and_returns_its_untrusted_draft() -> None:
    evidence = _evidence()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("http://models.wsl.internal:11434/api/chat")
        payload = json.loads(request.content)
        assert payload["model"] == "gemma4:e2b-it-qat"
        assert payload["think"] is False
        assert payload["tools"][0]["function"]["name"] == "submit_grounded_answer"
        assert payload["options"] == {
            "temperature": 0,
            "num_ctx": 8192,
            "num_predict": 1024,
        }
        assert "tool_choice" not in payload
        return httpx.Response(
            200,
            json={
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "submit_grounded_answer",
                                "arguments": {
                                    "answer": "Final inspection yield is measured.",
                                    "cited_chunk_ids": [str(evidence.chunk_id)],
                                },
                            },
                        }
                    ]
                }
            },
        )

    async with httpx.AsyncClient(
        base_url="http://models.wsl.internal:11434/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        draft = await LocalOllamaChatComposer(
            base_url="http://models.wsl.internal:11434/v1",
            model="gemma4:e2b-it-qat",
            timeout_seconds=45,
            context_tokens=8192,
            allowed_hosts=frozenset({"models.wsl.internal"}),
            client=client,
        ).compose(question="How is yield measured?", evidence=(evidence,))

    assert draft.answer == "Final inspection yield is measured."
    assert draft.cited_chunk_ids == (evidence.chunk_id,)


@pytest.mark.asyncio
async def test_composer_uses_separate_fixed_tool_for_general_knowledge() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload == ollama_native_general_chat_request_payload(
            model="gemma4:e2b-it-qat",
            question="온톨로지가 뭐야?",
            context_tokens=8192,
        )
        assert payload["tools"][0]["function"]["name"] == "submit_general_answer"
        assert "authorized_evidence" not in payload["messages"][1]["content"]
        return httpx.Response(
            200,
            json={
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "submit_general_answer",
                                "arguments": {
                                    "answer": "온톨로지는 개념과 관계를 구조화합니다.",
                                },
                            },
                        }
                    ]
                }
            },
        )

    async with httpx.AsyncClient(
        base_url="http://host.docker.internal:11434/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        draft = await LocalOllamaChatComposer(
            base_url="http://host.docker.internal:11434/v1",
            model="gemma4:e2b-it-qat",
            timeout_seconds=45,
            context_tokens=8192,
            allowed_hosts=frozenset({"host.docker.internal"}),
            client=client,
        ).compose_general(question="온톨로지가 뭐야?")

    assert draft.answer == "온톨로지는 개념과 관계를 구조화합니다."
    assert draft.cited_chunk_ids == ()


@pytest.mark.asyncio
async def test_composer_rejects_text_or_unknown_tool_output() -> None:
    evidence = _evidence()

    async with httpx.AsyncClient(
        base_url="http://host.docker.internal:11434/v1",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"choices": [{"message": {"content": "untrusted prose"}}]},
            )
        ),
    ) as client:
        draft = await LocalOllamaChatComposer(
            base_url="http://host.docker.internal:11434/v1",
            model="gemma4:e2b-it-qat",
            timeout_seconds=45,
            context_tokens=8192,
            allowed_hosts=frozenset({"host.docker.internal"}),
            client=client,
        ).compose(question="How is yield measured?", evidence=(evidence,))

    assert draft.answer == ""
    assert draft.cited_chunk_ids == ()


@pytest.mark.asyncio
async def test_composer_rejects_an_oversized_response_before_json_parsing() -> None:
    evidence = _evidence()
    async with httpx.AsyncClient(
        base_url="http://host.docker.internal:11434/v1",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=b"{" + b"x" * 1_048_576 + b"}",
            )
        ),
    ) as client:
        composer = LocalOllamaChatComposer(
            base_url="http://host.docker.internal:11434/v1",
            model="gemma4:e2b-it-qat",
            timeout_seconds=45,
            context_tokens=8192,
            allowed_hosts=frozenset({"host.docker.internal"}),
            client=client,
        )
        with pytest.raises(ValidationError, match="exceeded"):
            await composer.compose(question="How is yield measured?", evidence=(evidence,))
