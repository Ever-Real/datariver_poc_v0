from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from datariver.application.dto import ChatEvidence
from datariver.application.evidence import build_evidence_chunk
from datariver.domain.authz import Classification
from datariver.infrastructure.llm.ollama import LocalOllamaChatComposer


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


@pytest.mark.asyncio
async def test_composer_uses_one_fixed_tool_and_returns_its_untrusted_draft() -> None:
    evidence = _evidence()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("http://host.docker.internal:11434/v1/chat/completions")
        payload = json.loads(request.content)
        assert payload["model"] == "datariver-gemma4-dev:0.1"
        assert payload["tool_choice"]["function"]["name"] == "submit_grounded_answer"
        assert payload["tools"][0]["function"]["name"] == "submit_grounded_answer"
        assert payload["options"] == {"num_ctx": 8192}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "submit_grounded_answer",
                                        "arguments": json.dumps(
                                            {
                                                "answer": "Final inspection yield is measured.",
                                                "cited_chunk_ids": [str(evidence.chunk_id)],
                                            }
                                        ),
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(
        base_url="http://host.docker.internal:11434/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        draft = await LocalOllamaChatComposer(
            base_url="http://host.docker.internal:11434/v1",
            model="datariver-gemma4-dev:0.1",
            timeout_seconds=45,
            context_tokens=8192,
            client=client,
        ).compose(question="How is yield measured?", evidence=(evidence,))

    assert draft.answer == "Final inspection yield is measured."
    assert draft.cited_chunk_ids == (evidence.chunk_id,)


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
            model="datariver-gemma4-dev:0.1",
            timeout_seconds=45,
            context_tokens=8192,
            client=client,
        ).compose(question="How is yield measured?", evidence=(evidence,))

    assert draft.answer == ""
    assert draft.cited_chunk_ids == ()
