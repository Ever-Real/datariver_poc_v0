from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import BinaryIO, Protocol
from uuid import UUID

from datariver.domain.knowledge import GraphSnapshot
from datariver.domain.knowledge_pipeline import (
    EmbeddingBatch,
    ExtractionDraft,
    GraphRagAuditRecord,
    GraphRagCompletion,
    GraphRagEvidence,
    KnowledgeSourceSnapshot,
    ModelBinding,
    PdfPage,
    ProjectionReceipt,
)


class KnowledgeSourceReader(Protocol):
    async def read_snapshot(self, *, source: KnowledgeSourceSnapshot) -> bytes: ...


class SpooledKnowledgeSource(Protocol):
    @property
    def stream(self) -> BinaryIO: ...

    @property
    def size_bytes(self) -> int: ...

    @property
    def content_sha256(self) -> str: ...

    def close(self) -> None: ...


class KnowledgeSourceSpoolReader(KnowledgeSourceReader, Protocol):
    async def spool_snapshot(
        self, *, source: KnowledgeSourceSnapshot
    ) -> SpooledKnowledgeSource: ...


class PageAwarePdfParser(Protocol):
    def parse(self, payload: bytes) -> tuple[PdfPage, ...]: ...


class StreamingPageAwarePdfParser(PageAwarePdfParser, Protocol):
    def parse_stream(self, source: BinaryIO) -> tuple[PdfPage, ...]: ...


class KnowledgeEmbeddingProvider(Protocol):
    async def embed_pages(
        self, *, pages: Sequence[PdfPage], binding: ModelBinding
    ) -> EmbeddingBatch: ...


class TypedKnowledgeExtractor(Protocol):
    async def propose(
        self,
        *,
        pages: Sequence[PdfPage],
        entity_types: frozenset[str],
        edge_types: frozenset[str],
        binding: ModelBinding,
    ) -> ExtractionDraft: ...


@dataclass(frozen=True, slots=True)
class KnowledgeRuntimeBindings:
    embedding: ModelBinding
    extraction: ModelBinding
    graphrag: ModelBinding


class KnowledgePipelineRuntime(Protocol):
    @property
    def embedding(self) -> KnowledgeEmbeddingProvider: ...

    @property
    def extractor(self) -> TypedKnowledgeExtractor: ...

    @property
    def bindings(self) -> KnowledgeRuntimeBindings: ...


class VerifiedKnowledgeProjectionWriter(Protocol):
    async def replace_shadow_release(
        self,
        *,
        deployment_id: UUID,
        workspace_id: UUID,
        graph_id: UUID,
        release_id: UUID,
        release_hash: str,
        snapshot: GraphSnapshot,
    ) -> ProjectionReceipt: ...


class ScopedGraphEvidenceRetriever(Protocol):
    async def retrieve(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        release_id: UUID,
        question: str,
        start_node_id: UUID | None,
        direction: str,
        edge_types: frozenset[str],
        maximum_classification: int,
        maximum_hops: int,
        maximum_nodes: int,
    ) -> tuple[GraphRagEvidence, ...]: ...


class KnowledgeAnswerComposer(Protocol):
    async def compose(
        self,
        *,
        question: str,
        evidence: Sequence[GraphRagEvidence],
        binding: ModelBinding,
    ) -> GraphRagCompletion: ...


class KnowledgeInferenceAuditWriter(Protocol):
    async def record_success(self, *, record: GraphRagAuditRecord) -> None: ...
