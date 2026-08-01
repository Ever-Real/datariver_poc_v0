from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Mapping
from typing import Any
from uuid import uuid4

import httpx
import pytest

from datariver.application.errors import ExternalDependencyError
from datariver.domain.common import ValidationError
from datariver.domain.knowledge_pipeline import GraphRagEvidence, ModelBinding, PdfPage
from datariver.domain.knowledge_studio import TBoxElementInput, TBoxElementKind
from datariver.infrastructure.knowledge.openai_compatible import (
    MAX_INFERENCE_RESPONSE_BYTES,
    HttpxOpenAIJsonTransport,
    OpenAICompatibleEmbeddingProvider,
    OpenAICompatibleKnowledgeAnswerComposer,
    OpenAICompatibleTBoxSchemaAssistant,
    OpenAICompatibleTypedKnowledgeExtractor,
)


class _Transport:
    def __init__(self, response: Mapping[str, Any]) -> None:
        self.response = response
        self.calls: list[tuple[str, Mapping[str, object]]] = []

    async def post_json(self, *, path: str, document: Mapping[str, object]) -> Mapping[str, Any]:
        self.calls.append((path, document))
        return self.response


class _ChunkedStream(httpx.AsyncByteStream):
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk


def _binding(model: str) -> ModelBinding:
    return ModelBinding("ollama", model, "knowledge-v1", "knowledge-schema-v1")


def test_model_binding_records_deployment_or_activated_configuration_revision() -> None:
    deployment = ModelBinding.activated(
        provider="ollama",
        model="gemma4:latest",
        prompt_version="knowledge-v1",
        tool_schema_version="knowledge-schema-v1",
        configuration_version=None,
        configuration_hash=None,
        adapter_contract="openai-compatible-chat-json-schema-v1",
    )
    activated = ModelBinding.activated(
        provider="ollama",
        model="gemma4:latest",
        prompt_version="knowledge-v1",
        tool_schema_version="knowledge-schema-v1",
        configuration_version=7,
        configuration_hash="c" * 64,
        adapter_contract="openai-compatible-chat-json-schema-v1",
    )
    routed_deployment = ModelBinding.activated(
        provider="ollama",
        model="gemma4:latest",
        prompt_version="knowledge-v1",
        tool_schema_version="knowledge-schema-v1",
        configuration_version=None,
        configuration_hash=None,
        adapter_contract="openai-compatible-chat-json-schema-v1",
        deployment_configuration_hash="d" * 64,
    )

    assert deployment.configuration_source == "DEPLOYMENT"
    assert deployment.configuration_version is None
    assert deployment.configuration_hash is not None
    assert len(deployment.configuration_hash) == 64
    assert activated.configuration_source == "SYSTEM_CONFIGURATION"
    assert activated.configuration_version == 7
    assert activated.configuration_hash == "c" * 64
    assert routed_deployment.configuration_hash == "d" * 64


@pytest.mark.asyncio
async def test_openai_transport_sends_an_operator_secret_only_to_the_allowlisted_origin() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://10.42.0.15/v1/embeddings")
        assert request.headers["Authorization"] == "Bearer intranet-api-key"
        return httpx.Response(200, request=request, json={"data": []})

    transport = HttpxOpenAIJsonTransport(
        base_url="https://10.42.0.15/v1",
        allowed_hosts=frozenset({"10.42.0.15"}),
        api_key="intranet-api-key",
        timeout_seconds=30,
        transport=httpx.MockTransport(handler),
    )

    assert await transport.post_json(path="/embeddings", document={"input": ["probe"]}) == {
        "data": []
    }


@pytest.mark.asyncio
async def test_openai_transport_preserves_an_operator_gateway_path_prefix() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://10.42.0.15/api/llm/openai/v1/embeddings")
        return httpx.Response(200, request=request, json={"data": []})

    transport = HttpxOpenAIJsonTransport(
        base_url="https://10.42.0.15/api/llm/openai/v1",
        allowed_hosts=frozenset({"10.42.0.15"}),
        api_key="shared-intranet-api-key",
        timeout_seconds=30,
        transport=httpx.MockTransport(handler),
    )

    assert await transport.post_json(path="/embeddings", document={"input": ["probe"]}) == {
        "data": []
    }


@pytest.mark.asyncio
async def test_embedding_provider_preserves_page_order_and_actual_binding() -> None:
    transport = _Transport(
        {
            "data": [
                {"index": 1, "embedding": [0.3, 0.4]},
                {"index": 0, "embedding": [0.1, 0.2]},
            ],
            "usage": {"prompt_tokens": 9},
        }
    )
    binding = _binding("bge-m3:latest")

    result = await OpenAICompatibleEmbeddingProvider(transport=transport).embed_pages(
        pages=(
            PdfPage.create(page_number=1, text="one"),
            PdfPage.create(page_number=2, text="two"),
        ),
        binding=binding,
    )

    assert result.binding == binding
    assert [item.vector for item in result.embeddings] == [(0.1, 0.2), (0.3, 0.4)]
    assert transport.calls[0][0] == "/embeddings"


@pytest.mark.asyncio
async def test_extractor_uses_fixed_json_schema_and_typed_page_evidence() -> None:
    content = json.dumps(
        {
            "nodes": [
                {
                    "local_key": "WaferFab",
                    "entity_type": "Facility",
                    "properties": {"name": "Wafer fab"},
                    "classification": 2,
                    "evidence_id": "p00001_u0001",
                    "confidence": 0.9,
                },
                {
                    "local_key": "LithographyTool",
                    "entity_type": "Tool",
                    "properties": {"name": "Lithography tool"},
                    "classification": 2,
                    "evidence_id": "p00001_u0001",
                    "confidence": 0.9,
                },
            ],
            "edges": [
                {
                    "local_key": "FabUsesTool",
                    "source_key": "WaferFab",
                    "target_key": "LithographyTool",
                    "edge_type": "USES",
                    "properties": {},
                    "classification": 2,
                    "evidence_id": "p00001_u0001",
                    "confidence": 0.88,
                }
            ],
        }
    )
    transport = _Transport(
        {
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 30, "completion_tokens": 20},
        }
    )

    result = await OpenAICompatibleTypedKnowledgeExtractor(transport=transport).propose(
        pages=(PdfPage.create(page_number=1, text="Wafer fab uses a lithography tool"),),
        entity_types=frozenset({"Facility", "Tool"}),
        edge_types=frozenset({"USES"}),
        binding=_binding("gemma4:latest"),
    )

    request = transport.calls[0][1]
    response_format = request["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["type"] == "json_schema"
    json_schema = response_format["json_schema"]
    assert isinstance(json_schema, dict)
    assert request["max_tokens"] == 2_048
    schema = json_schema["schema"]
    assert isinstance(schema, dict)
    properties = schema["properties"]
    assert isinstance(properties, dict)
    nodes_schema = properties["nodes"]
    edges_schema = properties["edges"]
    assert isinstance(nodes_schema, dict)
    assert isinstance(edges_schema, dict)
    assert nodes_schema["maxItems"] == 4
    assert edges_schema["maxItems"] == 2
    messages = request["messages"]
    assert isinstance(messages, list)
    system_message = messages[0]
    assert isinstance(system_message, dict)
    assert "reference exactly one evidence_id" in system_message["content"]
    assert "must be unique" in system_message["content"]
    user_document = json.loads(messages[1]["content"])
    assert user_document["evidence_units"] == [
        {
            "evidence_id": "p00001_u0001",
            "page_number": 1,
            "text": "Wafer fab uses a lithography tool",
        }
    ]
    assert result.edges[0].source_key == "WaferFab"
    assert result.edges[0].page_number == 1
    assert result.edges[0].evidence_text == "Wafer fab uses a lithography tool"
    assert result.input_tokens == 30


@pytest.mark.asyncio
async def test_extractor_rejects_evidence_ids_not_owned_by_the_server() -> None:
    transport = _Transport(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "nodes": [
                                    {
                                        "local_key": "Fabricated",
                                        "entity_type": "Facility",
                                        "properties": {},
                                        "classification": 2,
                                        "evidence_id": "invented",
                                        "confidence": 0.9,
                                    }
                                ],
                                "edges": [],
                            }
                        )
                    }
                }
            ]
        }
    )

    with pytest.raises(ValidationError, match="unknown page evidence"):
        await OpenAICompatibleTypedKnowledgeExtractor(transport=transport).propose(
            pages=(PdfPage.create(page_number=1, text="Grounded source evidence"),),
            entity_types=frozenset({"Facility"}),
            edge_types=frozenset(),
            binding=_binding("gemma4:latest"),
        )


@pytest.mark.asyncio
async def test_tbox_schema_assistant_rejects_duplicate_model_identities() -> None:
    transport = _Transport(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "classes": [
                                    {
                                        "stable_element_id": "class:document-one",
                                        "canonical_name": "Document",
                                        "display_name": "Document",
                                    },
                                    {
                                        "stable_element_id": "class:document-two",
                                        "canonical_name": "Document",
                                        "display_name": "Duplicate Document",
                                    },
                                ],
                                "properties": [],
                                "relations": [],
                            }
                        )
                    }
                }
            ]
        }
    )

    with pytest.raises(ValidationError, match="duplicate typed identity"):
        await OpenAICompatibleTBoxSchemaAssistant(transport=transport).propose(
            prompt="Document schema를 제안해 줘.",
            current_elements=(),
            binding=_binding("gemma4:latest"),
        )


@pytest.mark.asyncio
async def test_tbox_schema_assistant_uses_bounded_grammar_compatible_schema() -> None:
    transport = _Transport(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "classes": [
                                    {
                                        "stable_element_id": "class:document",
                                        "canonical_name": "Document",
                                        "display_name": "Document",
                                    }
                                ],
                                "properties": [],
                                "relations": [],
                            }
                        )
                    }
                }
            ]
        }
    )

    result = await OpenAICompatibleTBoxSchemaAssistant(transport=transport).propose(
        prompt="Document schema를 제안해 줘.",
        current_elements=(),
        binding=_binding("gemma4:latest"),
    )

    assert len(result) == 1
    request = transport.calls[0][1]
    response_format = request["response_format"]
    assert isinstance(response_format, dict)
    schema_contract = response_format["json_schema"]
    assert isinstance(schema_contract, dict)
    schema = schema_contract["schema"]
    assert isinstance(schema, dict)
    serialized = json.dumps(schema)
    assert "$ref" not in serialized
    assert "$defs" not in serialized
    assert "anyOf" not in serialized
    assert "maxLength" not in serialized
    assert schema_contract["name"] == "knowledge_studio_tbox_proposal_v2"
    groups = schema["properties"]
    assert isinstance(groups, dict)
    assert set(groups) == {"classes", "properties", "relations"}
    relation_items = groups["relations"]
    assert isinstance(relation_items, dict)
    relation_schema = relation_items["items"]
    assert isinstance(relation_schema, dict)
    relation_properties = relation_schema["properties"]
    assert isinstance(relation_properties, dict)
    assert {"source_stable_element_id", "target_stable_element_id"} <= set(
        relation_schema["required"]
    )
    assert not {
        "parent_stable_element_id",
        "hierarchy_relation",
        "data_type",
        "nullable",
        "unit",
        "vector_index_enabled",
    } & set(relation_properties)
    assert relation_schema["additionalProperties"] is False


@pytest.mark.asyncio
async def test_tbox_schema_assistant_maps_kind_specific_elements_and_current_scope() -> None:
    transport = _Transport(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "classes": [
                                    {
                                        "stable_element_id": "class:process",
                                        "canonical_name": "Process",
                                        "display_name": "Process",
                                    }
                                ],
                                "properties": [
                                    {
                                        "stable_element_id": "property:facility-name",
                                        "canonical_name": "facility_name",
                                        "display_name": "Facility name",
                                        "parent_stable_element_id": "class:facility",
                                        "data_type": "STRING",
                                        "nullable": False,
                                        "vector_index_enabled": True,
                                    }
                                ],
                                "relations": [
                                    {
                                        "stable_element_id": "relation:runs",
                                        "canonical_name": "RUNS",
                                        "display_name": "Runs",
                                        "source_stable_element_id": "class:facility",
                                        "target_stable_element_id": "class:process",
                                    }
                                ],
                            }
                        )
                    }
                }
            ]
        }
    )
    current = (
        TBoxElementInput(
            stable_element_id="class:facility",
            kind=TBoxElementKind.CLASS,
            canonical_name="Facility",
            display_name="Facility",
        ),
    )

    result = await OpenAICompatibleTBoxSchemaAssistant(transport=transport).propose(
        prompt="Facility process schema를 제안해 줘.",
        current_elements=current,
        binding=_binding("gemma4:latest"),
    )

    assert [item.kind for item in result] == [
        TBoxElementKind.CLASS,
        TBoxElementKind.PROPERTY,
        TBoxElementKind.RELATION,
    ]
    assert result[1].parent_stable_element_id == "class:facility"
    assert result[2].source_stable_element_id == "class:facility"
    assert result[2].target_stable_element_id == "class:process"
    request = transport.calls[0][1]
    messages = request["messages"]
    assert isinstance(messages, list)
    user_document = json.loads(messages[1]["content"])
    current_document = user_document["current_tbox"]
    assert set(current_document) == {"classes", "properties", "relations"}
    assert current_document["classes"][0]["stable_element_id"] == "class:facility"
    assert "source_stable_element_id" not in current_document["classes"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "relation",
    [
        {
            "stable_element_id": "relation:missing-target",
            "canonical_name": "CONNECTS",
            "display_name": "Connects",
            "source_stable_element_id": "class:left",
        },
        {
            "stable_element_id": "relation:cross-kind",
            "canonical_name": "CONNECTS",
            "display_name": "Connects",
            "source_stable_element_id": "class:left",
            "target_stable_element_id": "class:right",
            "nullable": False,
        },
    ],
)
async def test_tbox_schema_assistant_rejects_invalid_relation_shape(
    relation: dict[str, object],
) -> None:
    transport = _Transport(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"classes": [], "properties": [], "relations": [relation]}
                        )
                    }
                }
            ]
        }
    )

    with pytest.raises(ValidationError, match="typed schema"):
        await OpenAICompatibleTBoxSchemaAssistant(transport=transport).propose(
            prompt="Invalid relation을 거부해 줘.",
            current_elements=(),
            binding=_binding("gemma4:latest"),
        )


@pytest.mark.asyncio
async def test_tbox_schema_assistant_rejects_unknown_relation_class_and_aggregate_overflow() -> (
    None
):
    unknown_transport = _Transport(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "classes": [],
                                "properties": [],
                                "relations": [
                                    {
                                        "stable_element_id": "relation:unknown",
                                        "canonical_name": "CONNECTS",
                                        "display_name": "Connects",
                                        "source_stable_element_id": "class:left",
                                        "target_stable_element_id": "class:right",
                                    }
                                ],
                            }
                        )
                    }
                }
            ]
        }
    )
    with pytest.raises(ValidationError, match="unknown Class"):
        await OpenAICompatibleTBoxSchemaAssistant(transport=unknown_transport).propose(
            prompt="Unknown relation을 거부해 줘.",
            current_elements=(),
            binding=_binding("gemma4:latest"),
        )

    overflow_transport = _Transport(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "classes": [
                                    {
                                        "stable_element_id": f"class:item-{index}",
                                        "canonical_name": f"Item_{index}",
                                        "display_name": f"Item {index}",
                                    }
                                    for index in range(101)
                                ],
                                "properties": [],
                                "relations": [],
                            }
                        )
                    }
                }
            ]
        }
    )
    with pytest.raises(ValidationError, match="typed schema"):
        await OpenAICompatibleTBoxSchemaAssistant(transport=overflow_transport).propose(
            prompt="Oversized schema를 거부해 줘.",
            current_elements=(),
            binding=_binding("gemma4:latest"),
        )


@pytest.mark.asyncio
async def test_extractor_drops_edges_with_model_invented_endpoints() -> None:
    transport = _Transport(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "nodes": [
                                    {
                                        "local_key": "KnownNode",
                                        "entity_type": "Facility",
                                        "properties": {},
                                        "classification": 2,
                                        "evidence_id": "p00001_u0001",
                                        "confidence": 0.9,
                                    }
                                ],
                                "edges": [
                                    {
                                        "local_key": "InvalidEdge",
                                        "source_key": "KnownNode",
                                        "target_key": "InventedNode",
                                        "edge_type": "USES",
                                        "properties": {},
                                        "classification": 2,
                                        "evidence_id": "p00001_u0001",
                                        "confidence": 0.7,
                                    }
                                ],
                            }
                        )
                    }
                }
            ]
        }
    )

    result = await OpenAICompatibleTypedKnowledgeExtractor(transport=transport).propose(
        pages=(PdfPage.create(page_number=1, text="Grounded source evidence"),),
        entity_types=frozenset({"Facility"}),
        edge_types=frozenset({"USES"}),
        binding=_binding("gemma4:latest"),
    )

    assert [node.local_key for node in result.nodes] == ["KnownNode"]
    assert result.edges == ()


@pytest.mark.asyncio
async def test_answer_composer_returns_only_typed_citation_ids() -> None:
    transport = _Transport(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"answer": "근거 기반 답변", "cited_evidence_ids": ["E001"]}
                        )
                    }
                }
            ],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4},
        }
    )
    source_id = uuid4()
    target_id = uuid4()
    excerpt = "Wafer fab uses a lithography tool"
    evidence = GraphRagEvidence(
        "kg:r:n",
        uuid4(),
        "USES",
        {"criticality": "high"},
        "private/report.pdf#page=1",
        "a" * 64,
        1,
        2,
        entity_kind="EDGE",
        source_entity_id=source_id,
        target_entity_id=target_id,
        edge_type="USES",
        evidence_excerpt=excerpt,
        evidence_sha256=hashlib.sha256(excerpt.encode()).hexdigest(),
        source_page_sha256="b" * 64,
    )

    result = await OpenAICompatibleKnowledgeAnswerComposer(transport=transport).compose(
        question="Fab은 무엇인가?",
        evidence=(evidence,),
        binding=_binding("gemma4:latest"),
    )

    assert result.cited_evidence_ids == ("kg:r:n",)
    assert result.binding.model == "gemma4:latest"
    messages = transport.calls[0][1]["messages"]
    assert isinstance(messages, list)
    user_document = json.loads(messages[1]["content"])
    edge_document = user_document["evidence"][0]
    assert edge_document["evidence_id"] == "E001"
    assert edge_document["entity_kind"] == "EDGE"
    assert edge_document["source_entity_id"] == str(source_id)
    assert edge_document["target_entity_id"] == str(target_id)
    assert edge_document["edge_type"] == "USES"
    assert edge_document["evidence_excerpt"] == excerpt
    assert transport.calls[0][1]["max_tokens"] == 512
    assert "think" not in transport.calls[0][1]


@pytest.mark.asyncio
async def test_local_structured_chat_can_disable_provider_reasoning_output() -> None:
    extraction_transport = _Transport(
        {
            "choices": [{"message": {"content": json.dumps({"nodes": [], "edges": []})}}],
        }
    )
    answer_transport = _Transport(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"answer": "근거가 부족합니다.", "cited_evidence_ids": ["E001"]}
                        )
                    }
                }
            ],
        }
    )

    await OpenAICompatibleTypedKnowledgeExtractor(
        transport=extraction_transport,
        reasoning_effort="none",
    ).propose(
        pages=(PdfPage.create(page_number=1, text="bounded evidence"),),
        entity_types=frozenset({"Facility"}),
        edge_types=frozenset(),
        binding=_binding("gemma4:latest"),
    )
    await OpenAICompatibleKnowledgeAnswerComposer(
        transport=answer_transport,
        reasoning_effort="none",
    ).compose(
        question="근거는?",
        evidence=(
            GraphRagEvidence(
                "kg:r:n",
                uuid4(),
                "Facility",
                {},
                "private/report.pdf#page=1",
                "a" * 64,
                1,
                2,
            ),
        ),
        binding=_binding("gemma4:latest"),
    )

    assert extraction_transport.calls[0][1]["reasoning_effort"] == "none"
    assert answer_transport.calls[0][1]["reasoning_effort"] == "none"


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["   ", "x" * 20_001])
async def test_answer_composer_enforces_string_bounds_after_provider_parsing(answer: str) -> None:
    transport = _Transport(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"answer": answer, "cited_evidence_ids": ["kg:release:node"]}
                        )
                    }
                }
            ]
        }
    )

    with pytest.raises(ValidationError, match="typed schema"):
        await OpenAICompatibleKnowledgeAnswerComposer(transport=transport).compose(
            question="bounded answer",
            evidence=(),
            binding=_binding("gemma4:latest"),
        )


def test_http_transport_rejects_endpoints_outside_server_allowlist() -> None:
    with pytest.raises(ValueError, match="allowlist"):
        HttpxOpenAIJsonTransport(
            base_url="http://metadata.internal/v1",
            allowed_hosts=frozenset({"host.docker.internal"}),
            api_key=None,
            timeout_seconds=60,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_type", "provider_code"),
    [(httpx.ReadTimeout, "TIMEOUT"), (httpx.ConnectError, "NETWORK")],
)
async def test_http_transport_maps_retryable_network_failures_without_leaking_details(
    error_type: type[httpx.RequestError], provider_code: str
) -> None:
    async def fail(request: httpx.Request) -> httpx.Response:
        raise error_type("secret-bearing-provider-detail", request=request)

    transport = HttpxOpenAIJsonTransport(
        base_url="http://host.docker.internal/v1",
        allowed_hosts=frozenset({"host.docker.internal"}),
        api_key="secret-api-key",
        timeout_seconds=60,
        transport=httpx.MockTransport(fail),
    )

    with pytest.raises(ExternalDependencyError) as caught:
        await transport.post_json(path="/embeddings", document={"input": ["one"]})

    assert caught.value.details["retryable"] is True
    assert caught.value.details["provider_code"] == provider_code
    assert "secret" not in caught.value.message


@pytest.mark.asyncio
@pytest.mark.parametrize(("status_code", "retryable"), [(503, True), (400, False)])
async def test_http_transport_classifies_provider_status_without_returning_body(
    status_code: int, retryable: bool
) -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            text="secret-bearing-response-body",
            request=request,
        )

    transport = HttpxOpenAIJsonTransport(
        base_url="http://host.docker.internal/v1",
        allowed_hosts=frozenset({"host.docker.internal"}),
        api_key=None,
        timeout_seconds=60,
        transport=httpx.MockTransport(respond),
    )

    with pytest.raises(ExternalDependencyError) as caught:
        await transport.post_json(path="/chat/completions", document={"messages": []})

    assert caught.value.details["retryable"] is retryable
    assert caught.value.details["provider_code"] == f"HTTP_{status_code}"
    assert "secret-bearing" not in caught.value.message


@pytest.mark.asyncio
async def test_http_transport_treats_invalid_success_json_as_contract_validation() -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json", request=request)

    transport = HttpxOpenAIJsonTransport(
        base_url="http://host.docker.internal/v1",
        allowed_hosts=frozenset({"host.docker.internal"}),
        api_key=None,
        timeout_seconds=60,
        transport=httpx.MockTransport(respond),
    )

    with pytest.raises(ValidationError, match="valid JSON object"):
        await transport.post_json(path="/embeddings", document={"input": ["one"]})


@pytest.mark.asyncio
@pytest.mark.parametrize("declare_size", [True, False])
async def test_http_transport_rejects_oversized_success_response_without_returning_body(
    declare_size: bool,
) -> None:
    secret_body = b'{"secret":"' + (b"x" * MAX_INFERENCE_RESPONSE_BYTES) + b'"}'

    class BodyStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield secret_body

    async def respond(request: httpx.Request) -> httpx.Response:
        if declare_size:
            return httpx.Response(200, content=secret_body, request=request)
        return httpx.Response(200, stream=BodyStream(), request=request)

    transport = HttpxOpenAIJsonTransport(
        base_url="http://host.docker.internal/v1",
        allowed_hosts=frozenset({"host.docker.internal"}),
        api_key=None,
        timeout_seconds=60,
        transport=httpx.MockTransport(respond),
    )

    with pytest.raises(ExternalDependencyError) as caught:
        await transport.post_json(path="/chat/completions", document={"messages": []})

    assert caught.value.details["retryable"] is False
    assert caught.value.details["provider_code"] == "RESPONSE_TOO_LARGE"
    assert "secret" not in caught.value.message


@pytest.mark.asyncio
async def test_http_transport_enforces_response_limit_across_stream_chunks() -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            stream=_ChunkedStream(
                (
                    b'{"answer":"',
                    b"x" * (MAX_INFERENCE_RESPONSE_BYTES - 12),
                    b'"}',
                )
            ),
            request=request,
        )

    transport = HttpxOpenAIJsonTransport(
        base_url="http://host.docker.internal/v1",
        allowed_hosts=frozenset({"host.docker.internal"}),
        api_key=None,
        timeout_seconds=60,
        transport=httpx.MockTransport(respond),
    )

    with pytest.raises(ExternalDependencyError) as caught:
        await transport.post_json(path="/chat/completions", document={"messages": []})

    assert caught.value.details["provider_code"] == "RESPONSE_TOO_LARGE"
