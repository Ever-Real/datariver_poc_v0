from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from datariver.domain.common import ValidationError

PDF_MEDIA_TYPE = "application/pdf"
MAX_SOURCE_BYTES = 50 * 1024 * 1024
MAX_PDF_PAGES = 500
MAX_PAGE_CHARACTERS = 100_000
MAX_TOTAL_PAGE_CHARACTERS = 5_000_000
MAX_QUESTION_CHARACTERS = 4_000


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _validate_identifier(value: str, *, field: str) -> None:
    if not value or len(value) > 128 or not value.replace("_", "a").isalnum():
        raise ValidationError(f"{field} must contain only letters, numbers, and underscores.")


def _canonical_hash(document: object) -> str:
    return hashlib.sha256(
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class KnowledgeSourceSnapshot:
    snapshot_id: UUID
    workspace_id: UUID
    graph_id: UUID
    bucket: str
    object_key: str
    storage_version: str
    media_type: str
    byte_size: int
    content_sha256: str
    classification: int

    def require_inference_eligible(self, *, maximum_classification: int) -> None:
        if not 0 <= self.classification <= 3:
            raise ValidationError("Knowledge source classification is invalid.")
        if self.classification > maximum_classification:
            raise ValidationError(
                "The knowledge source classification is not eligible for this inference route."
            )

    def require_graph_envelope(self, *, graph_classification: int) -> None:
        if not 0 <= graph_classification <= 3:
            raise ValidationError("Knowledge graph classification is invalid.")
        if self.classification > graph_classification:
            raise ValidationError("The knowledge source classification exceeds its graph envelope.")

    def verify(self, payload: bytes) -> None:
        self.verify_observation(
            byte_size=len(payload),
            content_sha256=hashlib.sha256(payload).hexdigest(),
        )

    def verify_observation(self, *, byte_size: int, content_sha256: str) -> None:
        if self.media_type != PDF_MEDIA_TYPE:
            raise ValidationError(
                "Knowledge source ingestion accepts only the PDF content profile."
            )
        if (
            not self.bucket
            or not self.object_key
            or self.bucket.startswith(("http://", "https://"))
            or self.object_key.startswith(("http://", "https://"))
        ):
            raise ValidationError(
                "Knowledge sources must use a private object-store key, not a URL."
            )
        if not self.storage_version:
            raise ValidationError("Knowledge source storage version is required.")
        if not 0 < self.byte_size <= MAX_SOURCE_BYTES or byte_size != self.byte_size:
            raise ValidationError("Knowledge source byte size does not match its snapshot.")
        if not _valid_sha256(self.content_sha256):
            raise ValidationError("Knowledge source SHA-256 is invalid.")
        if content_sha256 != self.content_sha256:
            raise ValidationError("Knowledge source content does not match its immutable snapshot.")


@dataclass(frozen=True, slots=True)
class PdfPage:
    page_number: int
    text: str
    content_sha256: str

    @classmethod
    def create(cls, *, page_number: int, text: str) -> PdfPage:
        normalized = "\n".join(
            line.rstrip() for line in text.replace("\x00", "").splitlines()
        ).strip()
        if page_number < 1:
            raise ValidationError("PDF page numbers must be positive.")
        if len(normalized) > MAX_PAGE_CHARACTERS:
            raise ValidationError("A PDF page exceeds the text extraction limit.")
        return cls(
            page_number=page_number,
            text=normalized,
            content_sha256=hashlib.sha256(normalized.encode()).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class ModelBinding:
    provider: str
    model: str
    prompt_version: str
    tool_schema_version: str
    configuration_source: str | None = None
    configuration_version: int | None = None
    configuration_hash: str | None = None

    def to_document(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "tool_schema_version": self.tool_schema_version,
            "configuration_source": self.configuration_source,
            "configuration_version": self.configuration_version,
            "configuration_hash": self.configuration_hash,
        }

    def validate(self) -> None:
        for field, value in (
            ("provider", self.provider),
            ("model", self.model),
            ("prompt_version", self.prompt_version),
            ("tool_schema_version", self.tool_schema_version),
        ):
            if not value.strip() or len(value) > 200:
                raise ValidationError(f"The activated model {field} is invalid.")
        if self.configuration_source not in {None, "DEPLOYMENT", "SYSTEM_CONFIGURATION"}:
            raise ValidationError("The model configuration source is invalid.")
        if self.configuration_version is not None and self.configuration_version < 1:
            raise ValidationError("The model configuration version must be positive.")
        if self.configuration_hash is not None and not _valid_sha256(self.configuration_hash):
            raise ValidationError("The model configuration hash is invalid.")
        if self.configuration_source == "SYSTEM_CONFIGURATION" and (
            self.configuration_version is None or self.configuration_hash is None
        ):
            raise ValidationError(
                "A system-configuration model binding requires its activated version and hash."
            )

    @classmethod
    def activated(
        cls,
        *,
        provider: str,
        model: str,
        prompt_version: str,
        tool_schema_version: str,
        configuration_version: int | None,
        configuration_hash: str | None,
        adapter_contract: str,
        deployment_configuration_hash: str | None = None,
    ) -> ModelBinding:
        if configuration_version is None:
            source = "DEPLOYMENT"
            if deployment_configuration_hash is not None:
                if not _valid_sha256(deployment_configuration_hash):
                    raise ValidationError("The deployment model configuration hash is invalid.")
                resolved_hash = deployment_configuration_hash
            else:
                resolved_hash = _canonical_hash(
                    {
                        "adapter_contract": adapter_contract,
                        "model": model,
                        "prompt_version": prompt_version,
                        "provider": provider,
                        "tool_schema_version": tool_schema_version,
                    }
                )
        else:
            source = "SYSTEM_CONFIGURATION"
            if configuration_hash is None:
                raise ValidationError(
                    "The activated system configuration is missing its immutable hash."
                )
            resolved_hash = configuration_hash
        binding = cls(
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            tool_schema_version=tool_schema_version,
            configuration_source=source,
            configuration_version=configuration_version,
            configuration_hash=resolved_hash,
        )
        binding.validate()
        return binding


@dataclass(frozen=True, slots=True)
class PageEmbedding:
    page_number: int
    vector: tuple[float, ...]

    def validate(self, *, dimensions: int | None = None) -> None:
        if self.page_number < 1 or not self.vector:
            raise ValidationError("Every page embedding requires a page and vector.")
        if dimensions is not None and len(self.vector) != dimensions:
            raise ValidationError("Embedding dimensions changed within one source snapshot.")
        invalid_value = any(not -1_000_000 < value < 1_000_000 for value in self.vector)
        if len(self.vector) > 16_384 or invalid_value:
            raise ValidationError("An embedding vector contains invalid values.")


@dataclass(frozen=True, slots=True)
class EmbeddingBatch:
    binding: ModelBinding
    embeddings: tuple[PageEmbedding, ...]
    input_tokens: int | None


@dataclass(frozen=True, slots=True)
class ExtractedNodeDraft:
    local_key: str
    entity_type: str
    properties: dict[str, Any]
    classification: int
    page_number: int
    evidence_text: str
    confidence: float

    def validate(self, *, entity_types: frozenset[str], page_numbers: frozenset[int]) -> None:
        _validate_identifier(self.local_key, field="Node local key")
        _validate_identifier(self.entity_type, field="Node entity type")
        if self.entity_type not in entity_types:
            raise ValidationError("An extracted node type is outside the approved ontology.")
        if not isinstance(self.properties, dict) or len(self.properties) > 100:
            raise ValidationError("Extracted node properties are invalid.")
        if self.page_number not in page_numbers or not self.evidence_text.strip():
            raise ValidationError("Every extracted node requires page-aware evidence.")
        if len(self.evidence_text) > 1_000 or not 0 <= self.classification <= 3:
            raise ValidationError("Extracted node evidence or classification is invalid.")
        if not 0 <= self.confidence <= 1:
            raise ValidationError("Extracted node confidence must be between 0 and 1.")


@dataclass(frozen=True, slots=True)
class ExtractedEdgeDraft:
    local_key: str
    source_key: str
    target_key: str
    edge_type: str
    properties: dict[str, Any]
    classification: int
    page_number: int
    evidence_text: str
    confidence: float

    def validate(
        self,
        *,
        node_keys: frozenset[str],
        edge_types: frozenset[str],
        page_numbers: frozenset[int],
    ) -> None:
        _validate_identifier(self.local_key, field="Edge local key")
        _validate_identifier(self.edge_type, field="Edge type")
        if self.source_key not in node_keys or self.target_key not in node_keys:
            raise ValidationError("An extracted edge references an unavailable node key.")
        if self.edge_type not in edge_types:
            raise ValidationError("An extracted edge type is outside the approved ontology.")
        if not isinstance(self.properties, dict) or len(self.properties) > 100:
            raise ValidationError("Extracted edge properties are invalid.")
        if self.page_number not in page_numbers or not self.evidence_text.strip():
            raise ValidationError("Every extracted edge requires page-aware evidence.")
        if len(self.evidence_text) > 1_000 or not 0 <= self.classification <= 3:
            raise ValidationError("Extracted edge evidence or classification is invalid.")
        if not 0 <= self.confidence <= 1:
            raise ValidationError("Extracted edge confidence must be between 0 and 1.")


@dataclass(frozen=True, slots=True)
class ExtractionDraft:
    binding: ModelBinding
    nodes: tuple[ExtractedNodeDraft, ...]
    edges: tuple[ExtractedEdgeDraft, ...]
    input_tokens: int | None
    output_tokens: int | None

    def validate(
        self,
        *,
        entity_types: frozenset[str],
        edge_types: frozenset[str],
        page_numbers: frozenset[int],
    ) -> None:
        self.binding.validate()
        node_keys = [node.local_key for node in self.nodes]
        edge_keys = [edge.local_key for edge in self.edges]
        if len(node_keys) != len(set(node_keys)) or len(edge_keys) != len(set(edge_keys)):
            raise ValidationError("Extraction local keys must be unique within one proposal.")
        for node in self.nodes:
            node.validate(entity_types=entity_types, page_numbers=page_numbers)
        for edge in self.edges:
            edge.validate(
                node_keys=frozenset(node_keys),
                edge_types=edge_types,
                page_numbers=page_numbers,
            )


@dataclass(frozen=True, slots=True)
class KnowledgeSourceAnalysis:
    source: KnowledgeSourceSnapshot
    pages: tuple[PdfPage, ...]
    embeddings: EmbeddingBatch
    extraction: ExtractionDraft

    def evidence_hash(self) -> str:
        return _canonical_hash(
            {
                "contract": "KNOWLEDGE_SOURCE_ANALYSIS_EVIDENCE_V2",
                "source_snapshot_id": str(self.source.snapshot_id),
                "source_storage_version": self.source.storage_version,
                "source_sha256": self.source.content_sha256,
                "source_classification": self.source.classification,
                "pages": [
                    {"page": page.page_number, "sha256": page.content_sha256} for page in self.pages
                ],
                "embedding": {
                    "binding": self.embeddings.binding.to_document(),
                    "input_tokens": self.embeddings.input_tokens,
                    "vectors": [
                        {
                            "page": embedding.page_number,
                            "dimensions": len(embedding.vector),
                            "sha256": _canonical_hash(list(embedding.vector)),
                        }
                        for embedding in sorted(
                            self.embeddings.embeddings,
                            key=lambda value: value.page_number,
                        )
                    ],
                },
                "extraction": {
                    "binding": self.extraction.binding.to_document(),
                    "input_tokens": self.extraction.input_tokens,
                    "output_tokens": self.extraction.output_tokens,
                    "nodes": [
                        {
                            "local_key": node.local_key,
                            "entity_type": node.entity_type,
                            "properties": node.properties,
                            "classification": node.classification,
                            "page_number": node.page_number,
                            "evidence_text": node.evidence_text,
                            "confidence": node.confidence,
                        }
                        for node in sorted(
                            self.extraction.nodes,
                            key=lambda value: value.local_key,
                        )
                    ],
                    "edges": [
                        {
                            "local_key": edge.local_key,
                            "source_key": edge.source_key,
                            "target_key": edge.target_key,
                            "edge_type": edge.edge_type,
                            "properties": edge.properties,
                            "classification": edge.classification,
                            "page_number": edge.page_number,
                            "evidence_text": edge.evidence_text,
                            "confidence": edge.confidence,
                        }
                        for edge in sorted(
                            self.extraction.edges,
                            key=lambda value: value.local_key,
                        )
                    ],
                },
            }
        )


@dataclass(frozen=True, slots=True)
class ProjectionReceipt:
    deployment_id: UUID
    workspace_id: UUID
    graph_id: UUID
    release_id: UUID
    release_hash: str
    node_count: int
    edge_count: int
    verified: bool


@dataclass(frozen=True, slots=True)
class GraphRagEvidence:
    evidence_id: str
    entity_id: UUID
    entity_type: str
    properties: dict[str, Any]
    source_locator: str
    source_version: str
    page_number: int | None
    classification: int
    entity_kind: str = "NODE"
    source_entity_id: UUID | None = None
    target_entity_id: UUID | None = None
    edge_type: str | None = None
    evidence_excerpt: str | None = None
    evidence_sha256: str | None = None
    source_page_sha256: str | None = None

    def validate(self, *, maximum_classification: int) -> None:
        if not self.evidence_id or len(self.evidence_id) > 200:
            raise ValidationError("GraphRAG evidence identifiers are invalid.")
        if not 0 <= self.classification <= maximum_classification:
            raise ValidationError("GraphRAG evidence exceeds the authorized classification.")
        if not self.source_locator or not self.source_version:
            raise ValidationError("GraphRAG evidence requires a source locator and version.")
        if self.entity_kind not in {"NODE", "EDGE"}:
            raise ValidationError("GraphRAG evidence kind is invalid.")
        if self.entity_kind == "EDGE":
            if (
                self.source_entity_id is None
                or self.target_entity_id is None
                or self.edge_type is None
            ):
                raise ValidationError("GraphRAG edge evidence requires typed endpoints.")
            _validate_identifier(self.edge_type, field="GraphRAG edge type")
        elif any(
            value is not None
            for value in (self.source_entity_id, self.target_entity_id, self.edge_type)
        ):
            raise ValidationError("GraphRAG node evidence cannot contain edge endpoints.")
        evidence_values = (
            self.evidence_excerpt,
            self.evidence_sha256,
            self.source_page_sha256,
        )
        if any(value is not None for value in evidence_values) and not all(
            value is not None for value in evidence_values
        ):
            raise ValidationError("GraphRAG evidence hashes must accompany the excerpt.")
        if self.evidence_excerpt is not None:
            normalized = " ".join(self.evidence_excerpt.split())
            if normalized != self.evidence_excerpt or not normalized or len(normalized) > 1_000:
                raise ValidationError("GraphRAG evidence excerpts must be normalized and bounded.")
            if self.evidence_sha256 != hashlib.sha256(normalized.encode()).hexdigest():
                raise ValidationError("GraphRAG evidence excerpt hash is invalid.")
            if not _valid_sha256(self.source_page_sha256 or ""):
                raise ValidationError("GraphRAG source-page hash is invalid.")


@dataclass(frozen=True, slots=True)
class GraphRagCompletion:
    answer: str
    cited_evidence_ids: tuple[str, ...]
    binding: ModelBinding
    input_tokens: int | None
    output_tokens: int | None


@dataclass(frozen=True, slots=True)
class GraphRagAuditRecord:
    request_id: str
    workspace_id: UUID
    graph_id: UUID
    release_id: UUID
    actor_id: UUID
    question_sha256: str
    evidence_ids: tuple[str, ...]
    cited_evidence_ids: tuple[str, ...]
    binding: ModelBinding
    input_tokens: int | None
    output_tokens: int | None


@dataclass(frozen=True, slots=True)
class CitedGraphRagAnswer:
    answer: str
    citations: tuple[GraphRagEvidence, ...]
    binding: ModelBinding
