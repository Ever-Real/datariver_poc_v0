from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from uuid import UUID, uuid5

from datariver.application.knowledge_pipeline_ports import (
    KnowledgeAnswerComposer,
    KnowledgeEmbeddingProvider,
    KnowledgeInferenceAuditWriter,
    KnowledgeSourceReader,
    PageAwarePdfParser,
    ScopedGraphEvidenceRetriever,
    TypedKnowledgeExtractor,
    VerifiedKnowledgeProjectionWriter,
)
from datariver.domain.common import ValidationError, uuid7
from datariver.domain.knowledge import (
    ChangeOperationType,
    GraphChangeOperation,
    GraphEntityKind,
    GraphSnapshot,
    Provenance,
    normalize_evidence_excerpt,
)
from datariver.domain.knowledge_pipeline import (
    MAX_GRAPHRAG_QUERY_NODES,
    MAX_PDF_PAGES,
    MAX_QUESTION_CHARACTERS,
    MAX_TOTAL_PAGE_CHARACTERS,
    CitedGraphRagAnswer,
    EmbeddingBatch,
    ExtractedEdgeDraft,
    ExtractedNodeDraft,
    ExtractionDraft,
    GraphRagAuditRecord,
    GraphRagEvidence,
    KnowledgeSourceAnalysis,
    KnowledgeSourceSnapshot,
    ModelBinding,
    PageEmbedding,
    PdfPage,
    ProjectionReceipt,
)

MAX_EXTRACTION_BATCH_PAGES = 6
MAX_EXTRACTION_BATCH_CHARACTERS = 40_000
MAX_EMBEDDING_BATCH_PAGES = 8
MAX_EMBEDDING_BATCH_CHARACTERS = 40_000
MAX_TYPED_PROPOSAL_OPERATIONS = 10_000
PipelineCheckpoint = Callable[[str, dict[str, int]], Awaitable[None]]


def _canonical_graph_evidence(
    *,
    candidate: GraphRagEvidence,
    snapshot: GraphSnapshot,
    release_id: UUID,
) -> GraphRagEvidence:
    """Treat Neo4j as an ID selector and rebuild evidence from PostgreSQL truth."""

    if candidate.entity_kind == "NODE":
        node = snapshot.nodes.get(candidate.entity_id)
        if node is None:
            raise ValidationError("Neo4j selected a node outside the canonical release.")
        entity_type = node.entity_type
        properties = dict(node.properties)
        classification = node.classification
        provenance = node.provenance
        source_entity_id = None
        target_entity_id = None
        edge_type = None
        evidence_id = f"kg:{release_id}:{node.entity_id}"
    elif candidate.entity_kind == "EDGE":
        edge = snapshot.edges.get(candidate.entity_id)
        if edge is None:
            raise ValidationError("Neo4j selected an edge outside the canonical release.")
        entity_type = edge.edge_type
        properties = dict(edge.properties)
        classification = edge.classification
        provenance = edge.provenance
        source_entity_id = edge.source_entity_id
        target_entity_id = edge.target_entity_id
        edge_type = edge.edge_type
        evidence_id = f"kg:{release_id}:edge:{edge.edge_id}"
    else:
        raise ValidationError("Neo4j returned an invalid evidence kind.")
    if not provenance:
        raise ValidationError("Canonical GraphRAG evidence requires provenance.")
    selected = next(
        (value for value in provenance if value.evidence_excerpt is not None),
        provenance[0],
    )
    selected.validate()
    page_number = None
    marker = "#page="
    if marker in selected.source_locator:
        try:
            page_number = int(selected.source_locator.rsplit(marker, maxsplit=1)[1])
        except ValueError:
            page_number = None
    return GraphRagEvidence(
        evidence_id=evidence_id,
        entity_id=candidate.entity_id,
        entity_type=entity_type,
        properties=properties,
        source_locator=selected.source_locator,
        source_version=selected.source_version,
        page_number=page_number,
        classification=classification,
        entity_kind=candidate.entity_kind,
        source_entity_id=source_entity_id,
        target_entity_id=target_entity_id,
        edge_type=edge_type,
        evidence_excerpt=selected.evidence_excerpt,
        evidence_sha256=selected.evidence_sha256,
        source_page_sha256=selected.source_page_sha256,
    )


class KnowledgeSourcePipeline:
    def __init__(
        self,
        *,
        reader: KnowledgeSourceReader,
        parser: PageAwarePdfParser,
        embedding: KnowledgeEmbeddingProvider,
        extractor: TypedKnowledgeExtractor,
    ) -> None:
        self._reader = reader
        self._parser = parser
        self._embedding = embedding
        self._extractor = extractor

    async def analyze_pdf(
        self,
        *,
        source: KnowledgeSourceSnapshot,
        entity_types: frozenset[str],
        edge_types: frozenset[str],
        embedding_binding: ModelBinding,
        extraction_binding: ModelBinding,
    ) -> KnowledgeSourceAnalysis:
        if not entity_types:
            raise ValidationError("A knowledge extraction requires an approved entity ontology.")
        # The current development adapters are deployment bindings, not governed
        # classification-provider routes. Keep the ADR-0011 portable floor:
        # PUBLIC/INTERNAL may be analyzed, while CONFIDENTIAL/RESTRICTED must
        # stop before object bytes or model bindings are touched.
        source.require_inference_eligible(maximum_classification=1)
        embedding_binding.validate()
        extraction_binding.validate()
        payload = await self._reader.read_snapshot(source=source)
        source.verify(payload)
        pages = self._parser.parse(payload)
        return await self.analyze_pages(
            source=source,
            pages=pages,
            entity_types=entity_types,
            edge_types=edge_types,
            embedding_binding=embedding_binding,
            extraction_binding=extraction_binding,
        )

    async def analyze_pages(
        self,
        *,
        source: KnowledgeSourceSnapshot,
        pages: tuple[PdfPage, ...],
        entity_types: frozenset[str],
        edge_types: frozenset[str],
        embedding_binding: ModelBinding,
        extraction_binding: ModelBinding,
        checkpoint: PipelineCheckpoint | None = None,
    ) -> KnowledgeSourceAnalysis:
        if not entity_types:
            raise ValidationError("A knowledge extraction requires an approved entity ontology.")
        source.require_inference_eligible(maximum_classification=1)
        embedding_binding.validate()
        extraction_binding.validate()
        if not pages or len(pages) > MAX_PDF_PAGES:
            raise ValidationError("The PDF has no extractable pages or exceeds the page limit.")
        numbers = [page.page_number for page in pages]
        if len(numbers) != len(set(numbers)) or numbers != sorted(numbers):
            raise ValidationError("PDF parser output must contain unique ordered page numbers.")
        if sum(len(page.text) for page in pages) > MAX_TOTAL_PAGE_CHARACTERS:
            raise ValidationError("The PDF extracted text exceeds the total character limit.")
        if checkpoint is not None:
            await checkpoint(
                "PARSED",
                {"completed_pages": len(pages), "total_pages": len(pages)},
            )

        embeddings = await self._embed_bounded_batches(
            pages=pages,
            binding=embedding_binding,
            checkpoint=checkpoint,
        )
        self._validate_embeddings(pages=pages, batch=embeddings, expected=embedding_binding)
        extraction = await self._extract_bounded_batches(
            pages=pages,
            entity_types=entity_types,
            edge_types=edge_types,
            binding=extraction_binding,
            checkpoint=checkpoint,
        )
        extraction.validate(
            entity_types=entity_types,
            edge_types=edge_types,
            page_numbers=frozenset(numbers),
        )
        if any(node.classification != source.classification for node in extraction.nodes) or any(
            edge.classification != source.classification for edge in extraction.edges
        ):
            raise ValidationError(
                "Extracted graph content must inherit the immutable source classification."
            )
        self._verify_extraction_evidence(pages=pages, extraction=extraction)
        if len(extraction.nodes) + len(extraction.edges) > MAX_TYPED_PROPOSAL_OPERATIONS:
            raise ValidationError("The Knowledge source proposal exceeds the operation limit.")
        return KnowledgeSourceAnalysis(
            source=source,
            pages=pages,
            embeddings=embeddings,
            extraction=extraction,
        )

    async def _embed_bounded_batches(
        self,
        *,
        pages: tuple[PdfPage, ...],
        binding: ModelBinding,
        checkpoint: PipelineCheckpoint | None,
    ) -> EmbeddingBatch:
        batches = self._page_batches(
            pages=pages,
            maximum_pages=MAX_EMBEDDING_BATCH_PAGES,
            maximum_characters=MAX_EMBEDDING_BATCH_CHARACTERS,
        )
        values: list[PageEmbedding] = []
        token_counts: list[int | None] = []
        completed = 0
        for batch_pages in batches:
            if checkpoint is not None:
                await checkpoint(
                    "EMBEDDED",
                    {"completed_pages": completed, "total_pages": len(pages)},
                )
            batch = await self._embedding.embed_pages(
                pages=batch_pages,
                binding=binding,
            )
            self._validate_embeddings(
                pages=batch_pages,
                batch=batch,
                expected=binding,
            )
            values.extend(batch.embeddings)
            token_counts.append(batch.input_tokens)
            completed += len(batch_pages)
            if checkpoint is not None:
                await checkpoint(
                    "EMBEDDED",
                    {"completed_pages": completed, "total_pages": len(pages)},
                )
        return EmbeddingBatch(
            binding=binding,
            embeddings=tuple(values),
            input_tokens=(
                sum(value for value in token_counts if value is not None)
                if all(value is not None for value in token_counts)
                else None
            ),
        )

    async def _extract_bounded_batches(
        self,
        *,
        pages: tuple[PdfPage, ...],
        entity_types: frozenset[str],
        edge_types: frozenset[str],
        binding: ModelBinding,
        checkpoint: PipelineCheckpoint | None = None,
    ) -> ExtractionDraft:
        batches = self._page_batches(
            pages=pages,
            maximum_pages=MAX_EXTRACTION_BATCH_PAGES,
            maximum_characters=MAX_EXTRACTION_BATCH_CHARACTERS,
        )

        drafts: list[ExtractionDraft] = []
        completed = 0
        for batch in batches:
            if checkpoint is not None:
                await checkpoint(
                    "EXTRACTED",
                    {"completed_pages": completed, "total_pages": len(pages)},
                )
            draft = await self._extractor.propose(
                pages=batch,
                entity_types=entity_types,
                edge_types=edge_types,
                binding=binding,
            )
            self._assert_binding(actual=draft.binding, expected=binding)
            draft.validate(
                entity_types=entity_types,
                edge_types=edge_types,
                page_numbers=frozenset(page.page_number for page in batch),
            )
            drafts.append(draft)
            completed += len(batch)
            if checkpoint is not None:
                await checkpoint(
                    "EXTRACTED",
                    {"completed_pages": completed, "total_pages": len(pages)},
                )
        nodes: dict[str, ExtractedNodeDraft] = {}
        edges: dict[str, ExtractedEdgeDraft] = {}
        for draft in drafts:
            for node in draft.nodes:
                previous = nodes.get(node.local_key)
                if previous is not None and previous.entity_type != node.entity_type:
                    raise ValidationError(
                        "Extraction batches assigned conflicting types to one node key."
                    )
                if previous is None or node.confidence > previous.confidence:
                    nodes[node.local_key] = node
            for edge in draft.edges:
                previous_edge = edges.get(edge.local_key)
                if previous_edge is not None and (
                    previous_edge.source_key,
                    previous_edge.target_key,
                    previous_edge.edge_type,
                ) != (edge.source_key, edge.target_key, edge.edge_type):
                    raise ValidationError(
                        "Extraction batches assigned conflicting endpoints to one edge key."
                    )
                if previous_edge is None or edge.confidence > previous_edge.confidence:
                    edges[edge.local_key] = edge

        def summed(values: list[int | None]) -> int | None:
            return (
                sum(value for value in values if value is not None)
                if all(value is not None for value in values)
                else None
            )

        return ExtractionDraft(
            binding=binding,
            nodes=tuple(nodes.values()),
            edges=tuple(edges.values()),
            input_tokens=summed([draft.input_tokens for draft in drafts]),
            output_tokens=summed([draft.output_tokens for draft in drafts]),
        )

    @staticmethod
    def _page_batches(
        *,
        pages: tuple[PdfPage, ...],
        maximum_pages: int,
        maximum_characters: int,
    ) -> tuple[tuple[PdfPage, ...], ...]:
        batches: list[tuple[PdfPage, ...]] = []
        current: list[PdfPage] = []
        characters = 0
        for page in pages:
            if len(page.text) > maximum_characters:
                raise ValidationError(
                    "A parsed PDF page exceeds the bounded provider request size."
                )
            if current and (
                len(current) >= maximum_pages or characters + len(page.text) > maximum_characters
            ):
                batches.append(tuple(current))
                current = []
                characters = 0
            current.append(page)
            characters += len(page.text)
        if current:
            batches.append(tuple(current))
        return tuple(batches)

    @staticmethod
    def to_typed_operations(analysis: KnowledgeSourceAnalysis) -> tuple[GraphChangeOperation, ...]:
        pages_by_number = {page.page_number: page for page in analysis.pages}
        node_ids = {
            node.local_key: uuid5(analysis.source.snapshot_id, f"node:{node.local_key}")
            for node in analysis.extraction.nodes
        }
        operations: list[GraphChangeOperation] = []
        sequence = 0
        for node in analysis.extraction.nodes:
            sequence += 1
            operations.append(
                GraphChangeOperation(
                    sequence=sequence,
                    operation=ChangeOperationType.UPSERT,
                    entity_kind=GraphEntityKind.NODE,
                    stable_entity_id=node_ids[node.local_key],
                    document={
                        "entity_type": node.entity_type,
                        "properties": node.properties,
                        "classification": node.classification,
                    },
                    provenance=(
                        KnowledgeSourcePipeline._provenance(
                            analysis,
                            page=pages_by_number[node.page_number],
                            evidence_text=node.evidence_text,
                            confidence=node.confidence,
                        ),
                    ),
                    confidence=node.confidence,
                )
            )
        for edge in analysis.extraction.edges:
            sequence += 1
            operations.append(
                GraphChangeOperation(
                    sequence=sequence,
                    operation=ChangeOperationType.UPSERT,
                    entity_kind=GraphEntityKind.EDGE,
                    stable_entity_id=uuid5(analysis.source.snapshot_id, f"edge:{edge.local_key}"),
                    document={
                        "source_id": str(node_ids[edge.source_key]),
                        "target_id": str(node_ids[edge.target_key]),
                        "edge_type": edge.edge_type,
                        "properties": edge.properties,
                        "classification": edge.classification,
                    },
                    provenance=(
                        KnowledgeSourcePipeline._provenance(
                            analysis,
                            page=pages_by_number[edge.page_number],
                            evidence_text=edge.evidence_text,
                            confidence=edge.confidence,
                        ),
                    ),
                    confidence=edge.confidence,
                )
            )
        for operation in operations:
            operation.validate()
        return tuple(operations)

    @staticmethod
    def _provenance(
        analysis: KnowledgeSourceAnalysis,
        *,
        page: PdfPage,
        evidence_text: str,
        confidence: float,
    ) -> Provenance:
        excerpt = normalize_evidence_excerpt(evidence_text)
        return Provenance(
            source_ref=f"knowledge-source:{analysis.source.snapshot_id}",
            source_locator=(
                f"knowledge-source:{analysis.source.snapshot_id}#page={page.page_number}"
            ),
            source_version=analysis.source.content_sha256,
            method=(
                f"typed_pdf_extraction:{analysis.extraction.binding.provider}:"
                f"{analysis.extraction.binding.model}:{analysis.extraction.binding.prompt_version}"
            ),
            confidence=confidence,
            evidence_excerpt=excerpt,
            evidence_sha256=hashlib.sha256(excerpt.encode()).hexdigest(),
            source_page_sha256=page.content_sha256,
        )

    @staticmethod
    def _verify_extraction_evidence(
        *, pages: tuple[PdfPage, ...], extraction: ExtractionDraft
    ) -> None:
        normalized_pages = {
            page.page_number: normalize_evidence_excerpt(page.text) for page in pages
        }
        items: tuple[ExtractedNodeDraft | ExtractedEdgeDraft, ...] = (
            *extraction.nodes,
            *extraction.edges,
        )
        for item in items:
            excerpt = normalize_evidence_excerpt(item.evidence_text)
            page_text = normalized_pages.get(item.page_number, "")
            if not excerpt or excerpt not in page_text:
                raise ValidationError(
                    "LLM evidence must be an exact whitespace-normalized source-page excerpt."
                )

    @staticmethod
    def _validate_embeddings(
        *, pages: tuple[PdfPage, ...], batch: EmbeddingBatch, expected: ModelBinding
    ) -> None:
        KnowledgeSourcePipeline._assert_binding(actual=batch.binding, expected=expected)
        if len(batch.embeddings) != len(pages):
            raise ValidationError("Embedding output must match the page count exactly.")
        page_numbers = tuple(page.page_number for page in pages)
        if tuple(item.page_number for item in batch.embeddings) != page_numbers:
            raise ValidationError("Embedding output must preserve PDF page order.")
        dimensions: int | None = None
        for embedding in batch.embeddings:
            embedding.validate(dimensions=dimensions)
            dimensions = len(embedding.vector)
        if dimensions is None:
            raise ValidationError("Embedding output is empty.")

    @staticmethod
    def _assert_binding(*, actual: ModelBinding, expected: ModelBinding) -> None:
        actual.validate()
        if actual != expected:
            raise ValidationError("The model execution did not use the activated provider binding.")


class VerifiedProjectionService:
    def __init__(self, *, writer: VerifiedKnowledgeProjectionWriter) -> None:
        self._writer = writer

    async def project_shadow_release(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        release_id: UUID,
        release_hash: str,
        snapshot: GraphSnapshot,
    ) -> ProjectionReceipt:
        if snapshot.content_hash() != release_hash:
            raise ValidationError(
                "Projection input does not match the canonical PostgreSQL release."
            )
        deployment_id = uuid7()
        receipt = await self._writer.replace_shadow_release(
            deployment_id=deployment_id,
            workspace_id=workspace_id,
            graph_id=graph_id,
            release_id=release_id,
            release_hash=release_hash,
            snapshot=snapshot,
        )
        expected = (
            deployment_id,
            workspace_id,
            graph_id,
            release_id,
            release_hash,
            len(snapshot.nodes),
            len(snapshot.edges),
            True,
        )
        actual = (
            receipt.deployment_id,
            receipt.workspace_id,
            receipt.graph_id,
            receipt.release_id,
            receipt.release_hash,
            receipt.node_count,
            receipt.edge_count,
            receipt.verified,
        )
        if actual != expected:
            raise ValidationError("Neo4j shadow projection verification failed.")
        return receipt


class KnowledgeGraphRagService:
    def __init__(
        self,
        *,
        retriever: ScopedGraphEvidenceRetriever,
        composer: KnowledgeAnswerComposer,
        audit_writer: KnowledgeInferenceAuditWriter,
    ) -> None:
        self._retriever = retriever
        self._composer = composer
        self._audit_writer = audit_writer

    async def answer(
        self,
        *,
        request_id: str,
        workspace_id: UUID,
        graph_id: UUID,
        release_id: UUID,
        actor_id: UUID,
        question: str,
        start_node_id: UUID | None,
        direction: str,
        edge_types: frozenset[str],
        maximum_classification: int,
        maximum_hops: int,
        maximum_nodes: int,
        canonical_snapshot: GraphSnapshot,
        binding: ModelBinding,
    ) -> CitedGraphRagAnswer:
        normalized_question = " ".join(question.split())
        if not 2 <= len(normalized_question) <= MAX_QUESTION_CHARACTERS:
            raise ValidationError("GraphRAG questions must contain between 2 and 4,000 characters.")
        if not 0 <= maximum_classification <= 3:
            raise ValidationError("GraphRAG clearance is invalid.")
        if direction not in {"IN", "OUT", "BOTH"}:
            raise ValidationError("GraphRAG traversal direction is invalid.")
        if len(edge_types) > 50:
            raise ValidationError("GraphRAG edge type filter is too large.")
        for edge_type in edge_types:
            invalid_edge_type = (
                not edge_type or len(edge_type) > 128 or not edge_type.replace("_", "a").isalnum()
            )
            if invalid_edge_type:
                raise ValidationError("GraphRAG edge type filter is invalid.")
        if not 1 <= maximum_hops <= 3 or not 1 <= maximum_nodes <= MAX_GRAPHRAG_QUERY_NODES:
            raise ValidationError("GraphRAG traversal bounds are invalid.")
        binding.validate()
        selected_evidence = await self._retriever.retrieve(
            workspace_id=workspace_id,
            graph_id=graph_id,
            release_id=release_id,
            question=normalized_question,
            start_node_id=start_node_id,
            direction=direction,
            edge_types=edge_types,
            maximum_classification=maximum_classification,
            maximum_hops=maximum_hops,
            maximum_nodes=maximum_nodes,
        )
        if not selected_evidence:
            raise ValidationError("No authorized evidence is available for this knowledge release.")
        evidence = tuple(
            _canonical_graph_evidence(
                candidate=item,
                snapshot=canonical_snapshot,
                release_id=release_id,
            )
            for item in selected_evidence
        )
        evidence_by_id = {item.evidence_id: item for item in evidence}
        if len(evidence_by_id) != len(evidence):
            raise ValidationError("GraphRAG evidence identifiers must be unique.")
        for item in evidence:
            item.validate(maximum_classification=maximum_classification)
        completion = await self._composer.compose(
            question=normalized_question,
            evidence=evidence,
            binding=binding,
        )
        KnowledgeSourcePipeline._assert_binding(actual=completion.binding, expected=binding)
        cited_ids = tuple(dict.fromkeys(completion.cited_evidence_ids))
        if not completion.answer.strip() or not cited_ids:
            raise ValidationError("A GraphRAG answer must contain text and at least one citation.")
        if any(evidence_id not in evidence_by_id for evidence_id in cited_ids):
            raise ValidationError(
                "The model cited evidence outside the authorized retrieval package."
            )
        await self._audit_writer.record_success(
            record=GraphRagAuditRecord(
                request_id=request_id,
                workspace_id=workspace_id,
                graph_id=graph_id,
                release_id=release_id,
                actor_id=actor_id,
                question_sha256=hashlib.sha256(normalized_question.encode()).hexdigest(),
                evidence_ids=tuple(evidence_by_id),
                cited_evidence_ids=cited_ids,
                binding=completion.binding,
                input_tokens=completion.input_tokens,
                output_tokens=completion.output_tokens,
            )
        )
        return CitedGraphRagAnswer(
            answer=completion.answer.strip(),
            citations=tuple(evidence_by_id[evidence_id] for evidence_id in cited_ids),
            binding=completion.binding,
        )
