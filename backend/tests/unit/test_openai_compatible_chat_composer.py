from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from datariver.application.dto import ChatEvidence
from datariver.application.evidence import build_evidence_chunk
from datariver.domain.authz import Classification
from datariver.infrastructure.llm.openai_compatible import (
    OpenAICompatibleGroundedChatComposer,
)


class RecordingTransport:
    def __init__(self, evidence: ChatEvidence) -> None:
        self.evidence = evidence
        self.path = ""
        self.document: dict[str, object] = {}

    async def post_json(self, *, path: str, document: Mapping[str, object]) -> Mapping[str, Any]:
        self.path = path
        self.document = dict(document)
        return {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "submit_grounded_answer",
                                    "arguments": json.dumps(
                                        {
                                            "answer": "The answer is grounded.",
                                            "cited_chunk_ids": [str(self.evidence.chunk_id)],
                                        }
                                    ),
                                },
                            }
                        ],
                    },
                }
            ],
        }


class RecordingGeneralTransport:
    def __init__(self) -> None:
        self.path = ""
        self.document: dict[str, object] = {}

    async def post_json(self, *, path: str, document: Mapping[str, object]) -> Mapping[str, Any]:
        self.path = path
        self.document = dict(document)
        return {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "submit_general_answer",
                                    "arguments": json.dumps(
                                        {"answer": "A bounded general answer."}
                                    ),
                                },
                            }
                        ],
                    },
                }
            ],
        }


def evidence() -> ChatEvidence:
    return build_evidence_chunk(
        workspace_id=uuid4(),
        resource_id=uuid4(),
        classification=Classification.INTERNAL,
        system_id=None,
        domain_id=None,
        owner_department_id=None,
        name="Evidence",
        description="Authorized evidence.",
        source_locator="urn:datariver:test:evidence",
        source_version="v1",
        effective_from=datetime(2026, 7, 22, tzinfo=UTC),
        extraction_method="CATALOG_PROJECTION_V1",
    )


@pytest.mark.asyncio
async def test_openai_compatible_chat_uses_fixed_grounded_tool_contract() -> None:
    item = evidence()
    transport = RecordingTransport(item)

    draft = await OpenAICompatibleGroundedChatComposer(
        model="approved-chat-model", transport=transport
    ).compose(question="What is supported?", evidence=(item,))

    assert transport.path == "/chat/completions"
    assert transport.document["model"] == "approved-chat-model"
    assert "options" not in transport.document
    assert transport.document["tool_choice"] == {
        "type": "function",
        "function": {"name": "submit_grounded_answer"},
    }
    assert draft.answer == "The answer is grounded."
    assert draft.cited_chunk_ids == (item.chunk_id,)


@pytest.mark.asyncio
async def test_openai_compatible_chat_uses_separate_general_tool_contract() -> None:
    transport = RecordingGeneralTransport()

    draft = await OpenAICompatibleGroundedChatComposer(
        model="approved-chat-model", transport=transport
    ).compose_general(question="What is an ontology?")

    assert transport.path == "/chat/completions"
    assert transport.document["tool_choice"] == {
        "type": "function",
        "function": {"name": "submit_general_answer"},
    }
    assert draft.answer == "A bounded general answer."
    assert draft.cited_chunk_ids == ()


@pytest.mark.asyncio
async def test_openai_compatible_chat_applies_bounded_gateway_options() -> None:
    transport = RecordingGeneralTransport()

    await OpenAICompatibleGroundedChatComposer(
        model="/models/llm/gemma-4-31B-it",
        transport=transport,
        temperature=0.2,
        top_p=0.9,
        repetition_penalty=1.05,
        enable_thinking=True,
    ).compose_general(question="What is an ontology?")

    assert transport.document["temperature"] == 0.2
    assert transport.document["top_p"] == 0.9
    assert transport.document["repetition_penalty"] == 1.05
    assert transport.document["chat_template_kwargs"] == {"enable_thinking": True}
    assert transport.document["stream"] is False
