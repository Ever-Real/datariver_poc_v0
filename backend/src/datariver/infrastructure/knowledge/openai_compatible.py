from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

from datariver.application.errors import ExternalDependencyError
from datariver.application.knowledge_pipeline_ports import (
    KnowledgeAnswerComposer,
    KnowledgeEmbeddingProvider,
    TypedKnowledgeExtractor,
)
from datariver.application.ports import KnowledgeStudioSchemaAssistant
from datariver.domain.common import ValidationError
from datariver.domain.inference import is_safe_inference_api_base_path
from datariver.domain.knowledge import normalize_evidence_excerpt
from datariver.domain.knowledge_pipeline import (
    EmbeddingBatch,
    ExtractedEdgeDraft,
    ExtractedNodeDraft,
    ExtractionDraft,
    GraphRagCompletion,
    GraphRagEvidence,
    ModelBinding,
    PageEmbedding,
    PdfPage,
)
from datariver.domain.knowledge_studio import (
    TBoxElementInput,
    TBoxElementKind,
)

MAX_EXTRACTION_NODES_PER_BATCH = 4
MAX_EXTRACTION_EDGES_PER_BATCH = 2
MAX_EXTRACTION_OUTPUT_TOKENS = 2_048
MAX_GRAPHRAG_OUTPUT_TOKENS = 512
MAX_EVIDENCE_UNIT_CHARACTERS = 240
MAX_INFERENCE_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_TBOX_PROPOSAL_ELEMENTS = 100


@dataclass(frozen=True, slots=True)
class OpenAICompatibleChatRequestOptions:
    temperature: float = 0.0
    top_p: float | None = None
    repetition_penalty: float | None = None
    enable_thinking: bool = False

    def __post_init__(self) -> None:
        if (
            not 0.0 <= self.temperature <= 2.0
            or (self.top_p is not None and not 0.0 < self.top_p <= 1.0)
            or (self.repetition_penalty is not None and not 0.0 < self.repetition_penalty <= 2.0)
        ):
            raise ValueError("OpenAI-compatible Chat options are outside governed bounds.")

    def apply(self, document: Mapping[str, object]) -> dict[str, object]:
        configured = dict(document)
        configured["temperature"] = self.temperature
        configured["stream"] = False
        if self.top_p is not None:
            configured["top_p"] = self.top_p
        if self.repetition_penalty is not None:
            configured["repetition_penalty"] = self.repetition_penalty
        if self.enable_thinking:
            configured["chat_template_kwargs"] = {"enable_thinking": True}
        return configured


class OpenAIJsonTransport(Protocol):
    async def post_json(
        self, *, path: str, document: Mapping[str, object]
    ) -> Mapping[str, Any]: ...


class HttpxOpenAIJsonTransport:
    """Server-configured OpenAI-compatible transport with an explicit host allowlist."""

    def __init__(
        self,
        *,
        base_url: str,
        allowed_hosts: frozenset[str],
        api_key: str | None,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        host = (parsed.hostname or "").rstrip(".").lower()
        if (
            parsed.scheme not in {"http", "https"}
            or host not in allowed_hosts
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not is_safe_inference_api_base_path(
                parsed.path,
                terminal_segment="v1",
            )
        ):
            raise ValueError("The inference endpoint is outside the server allowlist.")
        if not 1 <= timeout_seconds <= 120:
            raise ValueError("The inference timeout is outside the governed limit.")
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._timeout = timeout_seconds
        self._transport = transport

    async def post_json(self, *, path: str, document: Mapping[str, object]) -> Mapping[str, Any]:
        if not path.startswith("/") or ".." in path:
            raise ValueError("Inference transport paths must be fixed absolute API paths.")
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers=self._headers,
                timeout=self._timeout,
                follow_redirects=False,
                trust_env=False,
                transport=self._transport,
            ) as client:
                async with client.stream("POST", path, json=document) as response:
                    response.raise_for_status()
                    content_length = response.headers.get("content-length")
                    if content_length is not None:
                        try:
                            declared_size = int(content_length)
                        except ValueError:
                            declared_size = 0
                        if declared_size > MAX_INFERENCE_RESPONSE_BYTES:
                            raise ExternalDependencyError(
                                "The configured inference provider response exceeded the limit.",
                                dependency="knowledge_inference",
                                retryable=False,
                                provider_code="RESPONSE_TOO_LARGE",
                            )
                    response_body = bytearray()
                    async for chunk in response.aiter_bytes():
                        response_body.extend(chunk)
                        if len(response_body) > MAX_INFERENCE_RESPONSE_BYTES:
                            raise ExternalDependencyError(
                                "The configured inference provider response exceeded the limit.",
                                dependency="knowledge_inference",
                                retryable=False,
                                provider_code="RESPONSE_TOO_LARGE",
                            )
        except httpx.TimeoutException as error:
            raise ExternalDependencyError(
                "The configured inference provider timed out.",
                dependency="knowledge_inference",
                retryable=True,
                provider_code="TIMEOUT",
            ) from error
        except httpx.HTTPStatusError as error:
            status_code = error.response.status_code
            retryable = status_code in {408, 425, 429} or status_code >= 500
            raise ExternalDependencyError(
                "The configured inference provider rejected the request.",
                dependency="knowledge_inference",
                retryable=retryable,
                provider_code=f"HTTP_{status_code}",
            ) from error
        except httpx.HTTPError as error:
            raise ExternalDependencyError(
                "The configured inference provider is unavailable.",
                dependency="knowledge_inference",
                retryable=True,
                provider_code="NETWORK",
            ) from error
        try:
            value = json.loads(response_body)
        except ValueError as error:
            raise ValidationError(
                "The inference provider response must be a valid JSON object."
            ) from error
        if not isinstance(value, dict):
            raise ValidationError("The inference provider response must be a JSON object.")
        return value


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _ExtractedNodeProposal(_StrictModel):
    local_key: str = Field(min_length=1, max_length=128)
    entity_type: str = Field(min_length=1, max_length=128)
    properties: dict[str, str | int | float | bool | None] = Field(max_length=8)
    classification: int = Field(ge=0, le=3)
    evidence_id: str = Field(min_length=1, max_length=64)
    confidence: float = Field(ge=0, le=1)


class _ExtractedEdgeProposal(_StrictModel):
    local_key: str = Field(min_length=1, max_length=128)
    source_key: str = Field(min_length=1, max_length=128)
    target_key: str = Field(min_length=1, max_length=128)
    edge_type: str = Field(min_length=1, max_length=128)
    properties: dict[str, str | int | float | bool | None] = Field(max_length=8)
    classification: int = Field(ge=0, le=3)
    evidence_id: str = Field(min_length=1, max_length=64)
    confidence: float = Field(ge=0, le=1)


class _ExtractionResponse(_StrictModel):
    nodes: list[_ExtractedNodeProposal] = Field(max_length=MAX_EXTRACTION_NODES_PER_BATCH)
    edges: list[_ExtractedEdgeProposal] = Field(max_length=MAX_EXTRACTION_EDGES_PER_BATCH)


class _GraphRagResponse(_StrictModel):
    # Ollama 0.32.1 cannot compile root string minLength/maxLength JSON grammar.
    # The same bounds are enforced immediately after parsing below.
    answer: str
    cited_evidence_ids: list[str] = Field(min_length=1, max_length=100)


class _TBoxIdentityProposal(_StrictModel):
    stable_element_id: str = Field(min_length=1, max_length=128)
    canonical_name: str = Field(
        min_length=1,
        max_length=255,
    )
    display_name: str = Field(min_length=1, max_length=255)
    definition: str | None = Field(default=None, max_length=4_000)
    aliases: list[str] = Field(default_factory=list, max_length=50)


class _TBoxClassProposal(_TBoxIdentityProposal):
    parent_stable_element_id: str | None = Field(default=None, max_length=128)
    hierarchy_relation: str | None = Field(default=None, max_length=255)


class _TBoxPropertyProposal(_TBoxIdentityProposal):
    parent_stable_element_id: str = Field(min_length=1, max_length=128)
    data_type: Literal[
        "STRING",
        "TEXT",
        "INTEGER",
        "FLOAT",
        "BOOLEAN",
        "DATE",
        "DATETIME",
    ]
    nullable: bool
    unit: str | None = Field(default=None, max_length=100)
    vector_index_enabled: bool = False


class _TBoxRelationProposal(_TBoxIdentityProposal):
    source_stable_element_id: str = Field(min_length=1, max_length=128)
    target_stable_element_id: str = Field(min_length=1, max_length=128)


class _TBoxSchemaProposalResponse(_StrictModel):
    classes: list[_TBoxClassProposal] = Field(max_length=MAX_TBOX_PROPOSAL_ELEMENTS)
    properties: list[_TBoxPropertyProposal] = Field(max_length=MAX_TBOX_PROPOSAL_ELEMENTS)
    relations: list[_TBoxRelationProposal] = Field(max_length=MAX_TBOX_PROPOSAL_ELEMENTS)


class _EvidenceUnit(BaseModel):
    model_config = ConfigDict(frozen=True)

    evidence_id: str
    page_number: int
    text: str


def _evidence_units(pages: Sequence[PdfPage]) -> tuple[_EvidenceUnit, ...]:
    """Create stable exact excerpts for model selection without model-authored evidence."""

    units: list[_EvidenceUnit] = []
    for page in pages:
        text = normalize_evidence_excerpt(page.text)
        start = 0
        sequence = 1
        while start < len(text):
            stop = min(start + MAX_EVIDENCE_UNIT_CHARACTERS, len(text))
            if stop < len(text):
                boundary = text.rfind(" ", start + (MAX_EVIDENCE_UNIT_CHARACTERS // 2), stop)
                if boundary > start:
                    stop = boundary
            excerpt = text[start:stop].strip()
            if excerpt:
                units.append(
                    _EvidenceUnit(
                        evidence_id=f"p{page.page_number:05d}_u{sequence:04d}",
                        page_number=page.page_number,
                        text=excerpt,
                    )
                )
                sequence += 1
            start = stop
            while start < len(text) and text[start].isspace():
                start += 1
    if not units:
        raise ValidationError("PDF extraction requires non-empty page evidence.")
    return tuple(units)


def _choice_content(document: Mapping[str, Any]) -> str:
    try:
        choices = document["choices"]
        if not isinstance(choices, list) or len(choices) != 1:
            raise TypeError
        choice = choices[0]
        if not isinstance(choice, dict):
            raise TypeError
        message = choice["message"]
        if not isinstance(message, dict) or not isinstance(message["content"], str):
            raise TypeError
        return message["content"]
    except (KeyError, TypeError) as error:
        raise ValidationError(
            "The inference provider returned an invalid completion shape."
        ) from error


def _usage(document: Mapping[str, Any]) -> tuple[int | None, int | None]:
    value = document.get("usage")
    if not isinstance(value, dict):
        return None, None
    prompt = value.get("prompt_tokens")
    completion = value.get("completion_tokens")
    return (
        prompt if isinstance(prompt, int) and prompt >= 0 else None,
        completion if isinstance(completion, int) and completion >= 0 else None,
    )


def _json_schema(model: type[BaseModel], *, name: str) -> dict[str, object]:
    return {
        "type": "json_schema",
        "json_schema": {"name": name, "strict": True, "schema": model.model_json_schema()},
    }


_GRAMMAR_UNSUPPORTED_SCHEMA_KEYS = frozenset(
    {
        "$schema",
        "default",
        "description",
        "examples",
        "format",
        "maxItems",
        "maxLength",
        "maximum",
        "minItems",
        "minLength",
        "minimum",
        "pattern",
        "title",
    }
)


def _bounded_grammar_json_schema(
    model: type[BaseModel],
    *,
    name: str,
) -> dict[str, object]:
    """Flatten Pydantic schema constructs rejected by bounded local grammar engines.

    Structural object/array types, enums, required fields and additional-property
    denial remain provider-enforced. Pydantic validates every returned bound and
    pattern again before a proposal can enter the application layer.
    """

    raw = model.model_json_schema()
    definitions = raw.get("$defs")
    defs = definitions if isinstance(definitions, dict) else {}

    def normalize(value: object) -> object:
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if not isinstance(value, dict):
            return value
        reference = value.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            target = defs.get(reference.removeprefix("#/$defs/"))
            if isinstance(target, dict):
                return normalize(target)
        alternatives = value.get("anyOf")
        if isinstance(alternatives, list) and alternatives:
            typed = [
                item
                for item in alternatives
                if isinstance(item, dict) and isinstance(item.get("type"), str)
            ]
            if len(typed) == len(alternatives):
                preferred = next(
                    (item for item in typed if item.get("type") != "null"),
                    typed[0],
                )
                normalized = {
                    key: normalize(item)
                    for key, item in preferred.items()
                    if key != "type" and key not in _GRAMMAR_UNSUPPORTED_SCHEMA_KEYS
                }
                normalized["type"] = [str(item["type"]) for item in typed]
                return normalized
        return {
            key: normalize(item)
            for key, item in value.items()
            if key != "$defs" and key not in _GRAMMAR_UNSUPPORTED_SCHEMA_KEYS
        }

    schema = normalize(raw)
    if not isinstance(schema, dict):  # pragma: no cover - BaseModel always yields an object
        raise TypeError("A Pydantic response schema must be an object.")
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": True,
            "schema": schema,
        },
    }


class OpenAICompatibleEmbeddingProvider(KnowledgeEmbeddingProvider):
    def __init__(self, *, transport: OpenAIJsonTransport) -> None:
        self._transport = transport

    async def embed_pages(
        self, *, pages: Sequence[PdfPage], binding: ModelBinding
    ) -> EmbeddingBatch:
        result = await self._transport.post_json(
            path="/embeddings",
            document={"model": binding.model, "input": [page.text for page in pages]},
        )
        values = result.get("data")
        if not isinstance(values, list) or len(values) != len(pages):
            raise ValidationError("Embedding provider output does not match the PDF pages.")
        indexed: dict[int, tuple[float, ...]] = {}
        for item in values:
            if not isinstance(item, dict):
                raise ValidationError("Embedding provider returned an invalid vector item.")
            index = item.get("index")
            vector = item.get("embedding")
            if not isinstance(index, int) or not isinstance(vector, list):
                raise ValidationError("Embedding provider returned an invalid vector shape.")
            invalid_value = any(
                not isinstance(value, int | float) or isinstance(value, bool) for value in vector
            )
            if invalid_value:
                raise ValidationError("Embedding provider returned a non-numeric vector.")
            indexed[index] = tuple(float(value) for value in vector)
        if set(indexed) != set(range(len(pages))):
            raise ValidationError("Embedding provider indices are incomplete or duplicated.")
        usage = result.get("usage")
        prompt_tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
        return EmbeddingBatch(
            binding=binding,
            embeddings=tuple(
                PageEmbedding(page_number=page.page_number, vector=indexed[index])
                for index, page in enumerate(pages)
            ),
            input_tokens=(
                prompt_tokens if isinstance(prompt_tokens, int) and prompt_tokens >= 0 else None
            ),
        )


class OpenAICompatibleTypedKnowledgeExtractor(TypedKnowledgeExtractor):
    def __init__(
        self,
        *,
        transport: OpenAIJsonTransport,
        reasoning_effort: Literal["none", "low", "medium", "high"] | None = None,
        chat_options: OpenAICompatibleChatRequestOptions | None = None,
    ) -> None:
        self._transport = transport
        self._reasoning_effort = reasoning_effort
        self._chat_options = chat_options or OpenAICompatibleChatRequestOptions()

    async def propose(
        self,
        *,
        pages: Sequence[PdfPage],
        entity_types: frozenset[str],
        edge_types: frozenset[str],
        binding: ModelBinding,
    ) -> ExtractionDraft:
        if sum(len(page.text) for page in pages) > 160_000:
            raise ValidationError("PDF extraction must be dispatched in bounded page batches.")
        evidence_units = _evidence_units(pages)
        evidence_by_id = {unit.evidence_id: unit for unit in evidence_units}
        evidence_document = [unit.model_dump() for unit in evidence_units]
        document: dict[str, object] = {
            "model": binding.model,
            "temperature": 0,
            "max_tokens": MAX_EXTRACTION_OUTPUT_TOKENS,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Extract only assertions explicitly supported by the supplied pages. "
                        "Use only the approved entity and edge types. local_key values must "
                        "use letters, numbers, and underscores and must be unique within the "
                        "complete response. For every node and edge, reference exactly one "
                        "evidence_id from the supplied evidence_units; never invent or rewrite "
                        "evidence. Every edge endpoint must reference a node in the same "
                        "response; omit an edge when either endpoint is absent. Omit "
                        "any item without a supporting evidence_id. Return "
                        f"at most {MAX_EXTRACTION_NODES_PER_BATCH} nodes and "
                        f"{MAX_EXTRACTION_EDGES_PER_BATCH} edges. Keep properties to at most "
                        "four short scalar values."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "entity_types": sorted(entity_types),
                            "edge_types": sorted(edge_types),
                            "evidence_units": evidence_document,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                },
            ],
            "response_format": _json_schema(_ExtractionResponse, name="knowledge_extraction_v1"),
        }
        if self._reasoning_effort is not None:
            document["reasoning_effort"] = self._reasoning_effort
        result = await self._transport.post_json(
            path="/chat/completions",
            document=self._chat_options.apply(document),
        )
        try:
            parsed = _ExtractionResponse.model_validate_json(_choice_content(result))
        except PydanticValidationError as error:
            raise ValidationError(
                "The LLM extraction proposal violates the typed schema."
            ) from error
        try:
            nodes = tuple(
                ExtractedNodeDraft(
                    **node.model_dump(exclude={"evidence_id"}),
                    page_number=evidence_by_id[node.evidence_id].page_number,
                    evidence_text=evidence_by_id[node.evidence_id].text,
                )
                for node in parsed.nodes
            )
            node_keys = {node.local_key for node in nodes}
            edges = tuple(
                ExtractedEdgeDraft(
                    **edge.model_dump(exclude={"evidence_id"}),
                    page_number=evidence_by_id[edge.evidence_id].page_number,
                    evidence_text=evidence_by_id[edge.evidence_id].text,
                )
                for edge in parsed.edges
                if edge.source_key in node_keys and edge.target_key in node_keys
            )
        except KeyError as error:
            raise ValidationError(
                "The LLM extraction proposal references unknown page evidence."
            ) from error
        input_tokens, output_tokens = _usage(result)
        return ExtractionDraft(
            binding=binding,
            nodes=nodes,
            edges=edges,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


class OpenAICompatibleTBoxSchemaAssistant(KnowledgeStudioSchemaAssistant):
    """Generate a bounded typed proposal; never executes model-authored Cypher."""

    def __init__(
        self,
        *,
        transport: OpenAIJsonTransport,
        reasoning_effort: Literal["none", "low", "medium", "high"] | None = None,
        chat_options: OpenAICompatibleChatRequestOptions | None = None,
    ) -> None:
        self._transport = transport
        self._reasoning_effort = reasoning_effort
        self._chat_options = chat_options or OpenAICompatibleChatRequestOptions()

    async def propose(
        self,
        *,
        prompt: str,
        current_elements: tuple[TBoxElementInput, ...],
        binding: ModelBinding,
    ) -> tuple[TBoxElementInput, ...]:
        if prompt != prompt.strip() or not 1 <= len(prompt) <= 4_000:
            raise ValidationError(
                "A schema-assistant prompt must contain between 1 and 4,000 characters."
            )
        current_document: dict[str, list[dict[str, object]]] = {
            "classes": [],
            "properties": [],
            "relations": [],
        }
        for item in current_elements:
            identity: dict[str, object] = {
                "stable_element_id": item.stable_element_id,
                "canonical_name": item.canonical_name,
                "display_name": item.display_name,
                "definition": item.definition,
                "aliases": list(item.aliases),
            }
            if item.kind is TBoxElementKind.CLASS:
                current_document["classes"].append(
                    {
                        **identity,
                        "parent_stable_element_id": item.parent_stable_element_id,
                        "hierarchy_relation": item.hierarchy_relation,
                    }
                )
            elif item.kind is TBoxElementKind.PROPERTY:
                current_document["properties"].append(
                    {
                        **identity,
                        "parent_stable_element_id": item.parent_stable_element_id,
                        "data_type": item.data_type,
                        "nullable": item.nullable,
                        "unit": item.unit,
                        "vector_index_enabled": item.vector_index_enabled,
                    }
                )
            else:
                current_document["relations"].append(
                    {
                        **identity,
                        "source_stable_element_id": item.source_stable_element_id,
                        "target_stable_element_id": item.target_stable_element_id,
                    }
                )
        document: dict[str, object] = {
            "model": binding.model,
            "temperature": 0,
            "max_tokens": 4_096,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Design only a logical T-Box schema. Never emit Cypher, instance data, "
                        "credentials, URLs, or executable content. Return separate classes, "
                        "properties and relations arrays through the supplied JSON schema. Stable "
                        "IDs and canonical names use normalized Unicode letters, digits and "
                        "underscores as allowed by the schema contract. Properties must reference "
                        "a proposed or current Class by its exact stable_element_id. Relations "
                        "must provide both source_stable_element_id and target_stable_element_id, "
                        "and both must be exact stable IDs of proposed or current Classes. Omit a "
                        "Property or Relation when its Class stable ID is unknown. Class entries "
                        "may have only an optional parent and hierarchy relation. Property entries "
                        "must provide parent_stable_element_id, nullable, and one data_type from "
                        "STRING, TEXT, INTEGER, FLOAT, BOOLEAN, DATE, DATETIME. Relation entries "
                        "contain only their source and target Class references besides identity, "
                        "definition and aliases. "
                        "Mark vector_index_enabled only for STRING or TEXT Properties whose "
                        "semantic text is useful for retrieval. Keep the proposal bounded and "
                        "omit uncertain elements."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "request": prompt,
                            "current_tbox": current_document,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                },
            ],
            "response_format": _bounded_grammar_json_schema(
                _TBoxSchemaProposalResponse,
                name="knowledge_studio_tbox_proposal_v2",
            ),
        }
        if self._reasoning_effort is not None:
            document["reasoning_effort"] = self._reasoning_effort
        result = await self._transport.post_json(
            path="/chat/completions",
            document=self._chat_options.apply(document),
        )
        try:
            parsed = _TBoxSchemaProposalResponse.model_validate_json(_choice_content(result))
            proposed_items = [
                TBoxElementInput(
                    stable_element_id=item.stable_element_id,
                    kind=TBoxElementKind.CLASS,
                    canonical_name=item.canonical_name,
                    display_name=item.display_name,
                    parent_stable_element_id=item.parent_stable_element_id,
                    hierarchy_relation=item.hierarchy_relation,
                    definition=item.definition,
                    aliases=tuple(item.aliases),
                )
                for item in parsed.classes
            ]
            proposed_items.extend(
                TBoxElementInput(
                    stable_element_id=item.stable_element_id,
                    kind=TBoxElementKind.PROPERTY,
                    canonical_name=item.canonical_name,
                    display_name=item.display_name,
                    parent_stable_element_id=item.parent_stable_element_id,
                    data_type=item.data_type,
                    nullable=item.nullable,
                    definition=item.definition,
                    aliases=tuple(item.aliases),
                    unit=item.unit,
                    vector_index_enabled=item.vector_index_enabled,
                )
                for item in parsed.properties
            )
            proposed_items.extend(
                TBoxElementInput(
                    stable_element_id=item.stable_element_id,
                    kind=TBoxElementKind.RELATION,
                    canonical_name=item.canonical_name,
                    display_name=item.display_name,
                    source_stable_element_id=item.source_stable_element_id,
                    target_stable_element_id=item.target_stable_element_id,
                    definition=item.definition,
                    aliases=tuple(item.aliases),
                )
                for item in parsed.relations
            )
            if len(proposed_items) > MAX_TBOX_PROPOSAL_ELEMENTS:
                raise ValueError("The aggregate T-Box proposal element limit was exceeded.")
            proposed = tuple(proposed_items)
        except (PydanticValidationError, ValueError) as error:
            raise ValidationError("The LLM T-Box proposal violates the typed schema.") from error
        proposed_ids: set[str] = set()
        proposed_names: set[tuple[TBoxElementKind, str]] = set()
        for item in proposed:
            item.validate()
            name_identity = (item.kind, item.canonical_name.casefold())
            if item.stable_element_id in proposed_ids or name_identity in proposed_names:
                raise ValidationError("The LLM T-Box proposal contains a duplicate typed identity.")
            proposed_ids.add(item.stable_element_id)
            proposed_names.add(name_identity)
        class_ids = {
            item.stable_element_id
            for item in (*current_elements, *proposed)
            if item.kind is TBoxElementKind.CLASS
        }
        for item in proposed:
            references = (
                (item.parent_stable_element_id,)
                if item.kind is TBoxElementKind.PROPERTY
                else (
                    item.source_stable_element_id,
                    item.target_stable_element_id,
                )
                if item.kind is TBoxElementKind.RELATION
                else ()
            )
            if any(reference not in class_ids for reference in references):
                raise ValidationError("The LLM T-Box proposal references an unknown Class.")
        return proposed


class OpenAICompatibleKnowledgeAnswerComposer(KnowledgeAnswerComposer):
    def __init__(
        self,
        *,
        transport: OpenAIJsonTransport,
        reasoning_effort: Literal["none", "low", "medium", "high"] | None = None,
        chat_options: OpenAICompatibleChatRequestOptions | None = None,
    ) -> None:
        self._transport = transport
        self._reasoning_effort = reasoning_effort
        self._chat_options = chat_options or OpenAICompatibleChatRequestOptions()

    async def compose(
        self,
        *,
        question: str,
        evidence: Sequence[GraphRagEvidence],
        binding: ModelBinding,
    ) -> GraphRagCompletion:
        canonical_by_alias = {
            f"E{index:03d}": item.evidence_id for index, item in enumerate(evidence, start=1)
        }
        alias_by_canonical = {
            canonical_id: alias for alias, canonical_id in canonical_by_alias.items()
        }
        evidence_document = [
            {
                "evidence_id": alias_by_canonical[item.evidence_id],
                "entity_kind": item.entity_kind,
                "entity_id": str(item.entity_id),
                "entity_type": item.entity_type,
                "properties": item.properties,
                "source_entity_id": (
                    str(item.source_entity_id) if item.source_entity_id is not None else None
                ),
                "target_entity_id": (
                    str(item.target_entity_id) if item.target_entity_id is not None else None
                ),
                "edge_type": item.edge_type,
                "source_locator": item.source_locator,
                "source_version": item.source_version,
                "page_number": item.page_number,
                "evidence_excerpt": item.evidence_excerpt,
                "evidence_sha256": item.evidence_sha256,
                "source_page_sha256": item.source_page_sha256,
            }
            for item in evidence
        ]
        document: dict[str, object] = {
            "model": binding.model,
            "temperature": 0,
            "max_tokens": MAX_GRAPHRAG_OUTPUT_TOKENS,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Answer only from the authorized evidence JSON. If it is insufficient, "
                        "say so. Every factual answer must cite one or more exact short "
                        "evidence_id aliases from the supplied JSON."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"question": question, "evidence": evidence_document},
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                },
            ],
            "response_format": _json_schema(_GraphRagResponse, name="knowledge_graphrag_v1"),
        }
        if self._reasoning_effort is not None:
            document["reasoning_effort"] = self._reasoning_effort
        result = await self._transport.post_json(
            path="/chat/completions",
            document=self._chat_options.apply(document),
        )
        try:
            parsed = _GraphRagResponse.model_validate_json(_choice_content(result))
        except PydanticValidationError as error:
            raise ValidationError("The LLM GraphRAG answer violates the typed schema.") from error
        if not parsed.answer.strip() or len(parsed.answer) > 20_000:
            raise ValidationError("The LLM GraphRAG answer violates the typed schema.")
        try:
            cited_evidence_ids = tuple(
                canonical_by_alias[alias] for alias in parsed.cited_evidence_ids
            )
        except KeyError as error:
            raise ValidationError("The LLM GraphRAG answer violates the typed schema.") from error
        input_tokens, output_tokens = _usage(result)
        return GraphRagCompletion(
            answer=parsed.answer,
            cited_evidence_ids=cited_evidence_ids,
            binding=binding,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
