from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from io import BytesIO
from uuid import UUID, uuid4

import pytest

from datariver.application.services.knowledge_pipeline import (
    KnowledgeGraphRagService,
    KnowledgeSourcePipeline,
    VerifiedProjectionService,
)
from datariver.domain.common import ValidationError
from datariver.domain.knowledge import GraphEdge, GraphNode, GraphSnapshot, Provenance
from datariver.domain.knowledge_pipeline import (
    CitedGraphRagAnswer,
    EmbeddingBatch,
    ExtractedEdgeDraft,
    ExtractedNodeDraft,
    ExtractionDraft,
    GraphRagAuditRecord,
    GraphRagCompletion,
    GraphRagEvidence,
    KnowledgeSourceSnapshot,
    ModelBinding,
    PageEmbedding,
    PdfPage,
)
from datariver.infrastructure.knowledge.neo4j import (
    CypherStatement,
    Neo4jKnowledgeProjectionAdapter,
    Neo4jScopedEvidenceRetriever,
)
from datariver.infrastructure.knowledge.pdf import PypdfPageAwareParser


def _generated_pdf_fixture() -> bytes:
    # A small, deterministic PDF fixture. The parser adapter's injected reader emulates pypdf in
    # unit tests; the runtime dependency integration test can consume this same private fixture.
    content = b"BT /F1 12 Tf 72 720 Td (Wafer fab uses lithography tool) Tj ET"
    objects = (
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Count 1/Kids[3 0 R]>>",
        (
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
            b"/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>"
        ),
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
        b"<</Length " + str(len(content)).encode() + b">>stream\n" + content + b"\nendstream",
    )
    document = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, value in enumerate(objects, start=1):
        offsets.append(len(document))
        document.extend(f"{number} 0 obj\n".encode())
        document.extend(value)
        document.extend(b"\nendobj\n")
    xref_offset = len(document)
    document.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    document.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        document.extend(f"{offset:010d} 00000 n \n".encode())
    document.extend(
        (
            f"trailer\n<</Size {len(objects) + 1}/Root 1 0 R>>\nstartxref\n{xref_offset}\n%%EOF\n"
        ).encode()
    )
    return bytes(document)


@dataclass
class _Page:
    text: str

    def extract_text(self) -> str:
        return self.text


@dataclass
class _Reader:
    pages: Sequence[_Page]
    is_encrypted: bool = False


class _SourceReader:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    async def read_snapshot(self, *, source: KnowledgeSourceSnapshot) -> bytes:
        del source
        return self.payload


class _Embedding:
    async def embed_pages(
        self, *, pages: Sequence[PdfPage], binding: ModelBinding
    ) -> EmbeddingBatch:
        return EmbeddingBatch(
            binding=binding,
            embeddings=tuple(
                PageEmbedding(page_number=page.page_number, vector=(0.1, 0.2, 0.3))
                for page in pages
            ),
            input_tokens=12,
        )


class _Extractor:
    async def propose(
        self,
        *,
        pages: Sequence[PdfPage],
        entity_types: frozenset[str],
        edge_types: frozenset[str],
        binding: ModelBinding,
    ) -> ExtractionDraft:
        del pages, entity_types, edge_types
        return ExtractionDraft(
            binding=binding,
            nodes=(
                ExtractedNodeDraft(
                    "WaferFab",
                    "Facility",
                    {"name": "Wafer fab"},
                    1,
                    1,
                    "Wafer  fab uses\n lithography tool",
                    0.95,
                ),
                ExtractedNodeDraft(
                    "LithographyTool",
                    "Tool",
                    {"name": "Lithography tool"},
                    1,
                    1,
                    "Wafer  fab uses\n lithography tool",
                    0.94,
                ),
            ),
            edges=(
                ExtractedEdgeDraft(
                    "FabUsesTool",
                    "WaferFab",
                    "LithographyTool",
                    "USES",
                    {},
                    1,
                    1,
                    "Wafer  fab uses\n lithography tool",
                    0.9,
                ),
            ),
            input_tokens=30,
            output_tokens=20,
        )


def _binding(model: str) -> ModelBinding:
    return ModelBinding("ollama", model, "knowledge-v1", "typed-knowledge-v1")


def test_generated_pdf_fixture_is_parsed_by_the_runtime_pypdf_adapter() -> None:
    pytest.importorskip("pypdf")

    pages = PypdfPageAwareParser().parse(_generated_pdf_fixture())

    assert len(pages) == 1
    assert pages[0].page_number == 1
    assert "Wafer fab uses lithography tool" in pages[0].text


@pytest.mark.asyncio
async def test_generated_pdf_becomes_page_aware_typed_operations_without_url_fetch() -> None:
    payload = _generated_pdf_fixture()
    source = KnowledgeSourceSnapshot(
        snapshot_id=uuid4(),
        workspace_id=uuid4(),
        graph_id=uuid4(),
        bucket="accepted",
        object_key="knowledge/private/samilpwc-semiconductor.pdf",
        storage_version="version-1",
        media_type="application/pdf",
        byte_size=len(payload),
        content_sha256=hashlib.sha256(payload).hexdigest(),
        classification=1,
    )
    parser = PypdfPageAwareParser(
        reader_factory=lambda value: _Reader(
            pages=[_Page("Wafer fab uses lithography tool")] if isinstance(value, BytesIO) else []
        )
    )
    pipeline = KnowledgeSourcePipeline(
        reader=_SourceReader(payload),
        parser=parser,
        embedding=_Embedding(),
        extractor=_Extractor(),
    )

    analysis = await pipeline.analyze_pdf(
        source=source,
        entity_types=frozenset({"Facility", "Tool"}),
        edge_types=frozenset({"USES"}),
        embedding_binding=_binding("bge-m3:latest"),
        extraction_binding=_binding("gemma4:latest"),
    )
    operations = pipeline.to_typed_operations(analysis)

    assert [page.page_number for page in analysis.pages] == [1]
    assert [operation.stable_entity_id.version for operation in operations] == [5, 5, 5]
    assert operations[-1].document["source_id"] == str(operations[0].stable_entity_id)
    assert operations[-1].provenance[0].source_locator.endswith("#page=1")
    assert operations[-1].provenance[0].evidence_excerpt == ("Wafer fab uses lithography tool")
    assert (
        operations[-1].provenance[0].evidence_sha256
        == hashlib.sha256(b"Wafer fab uses lithography tool").hexdigest()
    )
    assert operations[-1].provenance[0].source_page_sha256 == analysis.pages[0].content_sha256
    assert analysis.evidence_hash() == analysis.evidence_hash()


@pytest.mark.asyncio
async def test_analysis_evidence_hash_binds_full_typed_output_and_model_configuration() -> None:
    payload = _generated_pdf_fixture()
    source = KnowledgeSourceSnapshot(
        snapshot_id=uuid4(),
        workspace_id=uuid4(),
        graph_id=uuid4(),
        bucket="accepted",
        object_key="knowledge/private/source.pdf",
        storage_version="manifest-v7",
        media_type="application/pdf",
        byte_size=len(payload),
        content_sha256=hashlib.sha256(payload).hexdigest(),
        classification=1,
    )
    pipeline = KnowledgeSourcePipeline(
        reader=_SourceReader(payload),
        parser=PypdfPageAwareParser(
            reader_factory=lambda _: _Reader([_Page("Wafer fab uses lithography tool")])
        ),
        embedding=_Embedding(),
        extractor=_Extractor(),
    )
    embedding_binding = ModelBinding.activated(
        provider="ollama",
        model="bge-m3:latest",
        prompt_version="embedding-v1",
        tool_schema_version="openai-embeddings-v1",
        configuration_version=3,
        configuration_hash="a" * 64,
        adapter_contract="openai-compatible-embeddings-v1",
    )
    extraction_binding = ModelBinding.activated(
        provider="ollama",
        model="gemma4:latest",
        prompt_version="knowledge-v1",
        tool_schema_version="typed-knowledge-v1",
        configuration_version=4,
        configuration_hash="b" * 64,
        adapter_contract="openai-compatible-chat-json-schema-v1",
    )
    analysis = await pipeline.analyze_pdf(
        source=source,
        entity_types=frozenset({"Facility", "Tool"}),
        edge_types=frozenset({"USES"}),
        embedding_binding=embedding_binding,
        extraction_binding=extraction_binding,
    )
    baseline_hash = analysis.evidence_hash()

    changed_property = replace(
        analysis,
        extraction=replace(
            analysis.extraction,
            nodes=(
                replace(
                    analysis.extraction.nodes[0],
                    properties={"name": "Different governed value"},
                ),
                *analysis.extraction.nodes[1:],
            ),
        ),
    )
    changed_endpoint = replace(
        analysis,
        extraction=replace(
            analysis.extraction,
            edges=(
                replace(
                    analysis.extraction.edges[0],
                    target_key="WaferFab",
                ),
            ),
        ),
    )
    changed_configuration = replace(
        analysis,
        extraction=replace(
            analysis.extraction,
            binding=replace(
                analysis.extraction.binding,
                configuration_hash="c" * 64,
            ),
        ),
    )

    assert baseline_hash != changed_property.evidence_hash()
    assert baseline_hash != changed_endpoint.evidence_hash()
    assert baseline_hash != changed_configuration.evidence_hash()


@pytest.mark.asyncio
async def test_generated_provenance_uses_opaque_source_urn_not_private_object_key() -> None:
    payload = _generated_pdf_fixture()
    source = KnowledgeSourceSnapshot(
        snapshot_id=uuid4(),
        workspace_id=uuid4(),
        graph_id=uuid4(),
        bucket="accepted-secret-bucket",
        object_key="tenant/private/topology/source.pdf",
        storage_version="manifest-v1",
        media_type="application/pdf",
        byte_size=len(payload),
        content_sha256=hashlib.sha256(payload).hexdigest(),
        classification=1,
    )
    pipeline = KnowledgeSourcePipeline(
        reader=_SourceReader(payload),
        parser=PypdfPageAwareParser(
            reader_factory=lambda _: _Reader([_Page("Wafer fab uses lithography tool")])
        ),
        embedding=_Embedding(),
        extractor=_Extractor(),
    )

    analysis = await pipeline.analyze_pdf(
        source=source,
        entity_types=frozenset({"Facility", "Tool"}),
        edge_types=frozenset({"USES"}),
        embedding_binding=_binding("bge-m3:latest"),
        extraction_binding=_binding("gemma4:latest"),
    )
    operations = pipeline.to_typed_operations(analysis)

    for operation in operations:
        locator = operation.provenance[0].source_locator
        assert locator == f"knowledge-source:{source.snapshot_id}#page=1"
        assert source.bucket not in locator
        assert source.object_key not in locator


@pytest.mark.asyncio
async def test_page_embeddings_are_sent_in_bounded_character_batches() -> None:
    class TrackingEmbedding(_Embedding):
        def __init__(self) -> None:
            self.batch_sizes: list[int] = []
            self.batch_characters: list[int] = []

        async def embed_pages(
            self, *, pages: Sequence[PdfPage], binding: ModelBinding
        ) -> EmbeddingBatch:
            self.batch_sizes.append(len(pages))
            self.batch_characters.append(sum(len(page.text) for page in pages))
            return await super().embed_pages(pages=pages, binding=binding)

    class EmptyExtractor:
        async def propose(
            self,
            *,
            pages: Sequence[PdfPage],
            entity_types: frozenset[str],
            edge_types: frozenset[str],
            binding: ModelBinding,
        ) -> ExtractionDraft:
            del pages, entity_types, edge_types
            return ExtractionDraft(
                binding=binding,
                nodes=(),
                edges=(),
                input_tokens=0,
                output_tokens=0,
            )

    tracking = TrackingEmbedding()
    source = KnowledgeSourceSnapshot(
        snapshot_id=uuid4(),
        workspace_id=uuid4(),
        graph_id=uuid4(),
        bucket="accepted",
        object_key="knowledge/private/source.pdf",
        storage_version="manifest-v1",
        media_type="application/pdf",
        byte_size=1,
        content_sha256="a" * 64,
        classification=1,
    )
    pages = tuple(
        PdfPage.create(
            page_number=number,
            text=("bounded text " * 1_000) + str(number),
        )
        for number in range(1, 11)
    )
    pipeline = KnowledgeSourcePipeline(
        reader=_SourceReader(b"x"),
        parser=PypdfPageAwareParser(reader_factory=lambda _: _Reader([])),
        embedding=tracking,
        extractor=EmptyExtractor(),
    )

    analysis = await pipeline.analyze_pages(
        source=source,
        pages=pages,
        entity_types=frozenset({"Facility", "Tool"}),
        edge_types=frozenset({"USES"}),
        embedding_binding=_binding("bge-m3:latest"),
        extraction_binding=_binding("gemma4:latest"),
    )

    assert len(tracking.batch_sizes) > 1
    assert sum(tracking.batch_sizes) == len(pages)
    assert max(tracking.batch_characters) <= 40_000
    assert [item.page_number for item in analysis.embeddings.embeddings] == list(range(1, 11))


@pytest.mark.asyncio
async def test_single_oversized_page_fails_before_any_provider_call() -> None:
    class TrackingEmbedding(_Embedding):
        def __init__(self) -> None:
            self.calls = 0

        async def embed_pages(
            self, *, pages: Sequence[PdfPage], binding: ModelBinding
        ) -> EmbeddingBatch:
            self.calls += 1
            return await super().embed_pages(pages=pages, binding=binding)

    class TrackingExtractor(_Extractor):
        def __init__(self) -> None:
            self.calls = 0

        async def propose(
            self,
            *,
            pages: Sequence[PdfPage],
            entity_types: frozenset[str],
            edge_types: frozenset[str],
            binding: ModelBinding,
        ) -> ExtractionDraft:
            self.calls += 1
            return await super().propose(
                pages=pages,
                entity_types=entity_types,
                edge_types=edge_types,
                binding=binding,
            )

    embedding = TrackingEmbedding()
    extractor = TrackingExtractor()
    source = KnowledgeSourceSnapshot(
        snapshot_id=uuid4(),
        workspace_id=uuid4(),
        graph_id=uuid4(),
        bucket="accepted",
        object_key="knowledge/private/source.pdf",
        storage_version="manifest-v1",
        media_type="application/pdf",
        byte_size=1,
        content_sha256="a" * 64,
        classification=1,
    )
    pipeline = KnowledgeSourcePipeline(
        reader=_SourceReader(b"x"),
        parser=PypdfPageAwareParser(reader_factory=lambda _: _Reader([])),
        embedding=embedding,
        extractor=extractor,
    )

    with pytest.raises(ValidationError, match="bounded provider request size"):
        await pipeline.analyze_pages(
            source=source,
            pages=(PdfPage.create(page_number=1, text="x" * 40_001),),
            entity_types=frozenset({"Facility"}),
            edge_types=frozenset(),
            embedding_binding=_binding("bge-m3:latest"),
            extraction_binding=_binding("gemma4:latest"),
        )

    assert embedding.calls == 0
    assert extractor.calls == 0


class _FabricatingExtractor(_Extractor):
    async def propose(self, **kwargs: object) -> ExtractionDraft:
        draft = await super().propose(**kwargs)  # type: ignore[arg-type]
        return replace(
            draft,
            nodes=(replace(draft.nodes[0], evidence_text="Unsupported fabricated claim"),),
            edges=(),
        )


@pytest.mark.asyncio
async def test_llm_evidence_not_present_on_the_claimed_page_fails_closed() -> None:
    payload = _generated_pdf_fixture()
    source = KnowledgeSourceSnapshot(
        snapshot_id=uuid4(),
        workspace_id=uuid4(),
        graph_id=uuid4(),
        bucket="accepted",
        object_key="knowledge/private/source.pdf",
        storage_version="version-1",
        media_type="application/pdf",
        byte_size=len(payload),
        content_sha256=hashlib.sha256(payload).hexdigest(),
        classification=1,
    )
    pipeline = KnowledgeSourcePipeline(
        reader=_SourceReader(payload),
        parser=PypdfPageAwareParser(
            reader_factory=lambda _: _Reader([_Page("Wafer fab uses lithography tool")])
        ),
        embedding=_Embedding(),
        extractor=_FabricatingExtractor(),
    )

    with pytest.raises(ValidationError, match="exact whitespace-normalized"):
        await pipeline.analyze_pdf(
            source=source,
            entity_types=frozenset({"Facility", "Tool"}),
            edge_types=frozenset({"USES"}),
            embedding_binding=_binding("bge-m3:latest"),
            extraction_binding=_binding("gemma4:latest"),
        )


@pytest.mark.asyncio
async def test_source_hash_mismatch_stops_before_embedding_or_llm() -> None:
    payload = _generated_pdf_fixture()
    source = KnowledgeSourceSnapshot(
        snapshot_id=uuid4(),
        workspace_id=uuid4(),
        graph_id=uuid4(),
        bucket="accepted",
        object_key="knowledge/private/source.pdf",
        storage_version="version-1",
        media_type="application/pdf",
        byte_size=len(payload),
        content_sha256="0" * 64,
        classification=1,
    )
    pipeline = KnowledgeSourcePipeline(
        reader=_SourceReader(payload),
        parser=PypdfPageAwareParser(reader_factory=lambda _: _Reader([_Page("content")])),
        embedding=_Embedding(),
        extractor=_Extractor(),
    )

    with pytest.raises(ValidationError, match="immutable snapshot"):
        await pipeline.analyze_pdf(
            source=source,
            entity_types=frozenset({"Facility", "Tool"}),
            edge_types=frozenset({"USES"}),
            embedding_binding=_binding("bge-m3:latest"),
            extraction_binding=_binding("gemma4:latest"),
        )


@pytest.mark.asyncio
async def test_restricted_source_stops_before_object_read_embedding_or_llm() -> None:
    payload = _generated_pdf_fixture()

    class NeverReader:
        async def read_snapshot(self, *, source: KnowledgeSourceSnapshot) -> bytes:
            del source
            raise AssertionError("restricted source bytes must not leave the governed store")

    source = KnowledgeSourceSnapshot(
        snapshot_id=uuid4(),
        workspace_id=uuid4(),
        graph_id=uuid4(),
        bucket="accepted",
        object_key="knowledge/private/restricted.pdf",
        storage_version="version-1",
        media_type="application/pdf",
        byte_size=len(payload),
        content_sha256=hashlib.sha256(payload).hexdigest(),
        classification=3,
    )
    pipeline = KnowledgeSourcePipeline(
        reader=NeverReader(),
        parser=PypdfPageAwareParser(reader_factory=lambda _: _Reader([_Page("content")])),
        embedding=_Embedding(),
        extractor=_Extractor(),
    )

    with pytest.raises(ValidationError, match="classification is not eligible"):
        await pipeline.analyze_pdf(
            source=source,
            entity_types=frozenset({"Facility", "Tool"}),
            edge_types=frozenset({"USES"}),
            embedding_binding=_binding("bge-m3:latest"),
            extraction_binding=_binding("gemma4:latest"),
        )


@pytest.mark.asyncio
async def test_model_cannot_down_classify_immutable_source_evidence() -> None:
    payload = _generated_pdf_fixture()

    class DownClassifyingExtractor(_Extractor):
        async def propose(self, **kwargs: object) -> ExtractionDraft:
            draft = await super().propose(**kwargs)  # type: ignore[arg-type]
            return replace(
                draft,
                nodes=tuple(replace(node, classification=0) for node in draft.nodes),
                edges=tuple(replace(edge, classification=0) for edge in draft.edges),
            )

    source = KnowledgeSourceSnapshot(
        snapshot_id=uuid4(),
        workspace_id=uuid4(),
        graph_id=uuid4(),
        bucket="accepted",
        object_key="knowledge/private/internal.pdf",
        storage_version="version-1",
        media_type="application/pdf",
        byte_size=len(payload),
        content_sha256=hashlib.sha256(payload).hexdigest(),
        classification=1,
    )
    pipeline = KnowledgeSourcePipeline(
        reader=_SourceReader(payload),
        parser=PypdfPageAwareParser(
            reader_factory=lambda _: _Reader([_Page("Wafer fab uses lithography tool")])
        ),
        embedding=_Embedding(),
        extractor=DownClassifyingExtractor(),
    )

    with pytest.raises(ValidationError, match="inherit the immutable source classification"):
        await pipeline.analyze_pdf(
            source=source,
            entity_types=frozenset({"Facility", "Tool"}),
            edge_types=frozenset({"USES"}),
            embedding_binding=_binding("bge-m3:latest"),
            extraction_binding=_binding("gemma4:latest"),
        )


def test_source_above_graph_envelope_is_rejected() -> None:
    source = KnowledgeSourceSnapshot(
        snapshot_id=uuid4(),
        workspace_id=uuid4(),
        graph_id=uuid4(),
        bucket="accepted",
        object_key="knowledge/private/internal.pdf",
        storage_version="version-1",
        media_type="application/pdf",
        byte_size=1,
        content_sha256="a" * 64,
        classification=1,
    )

    with pytest.raises(ValidationError, match="exceeds its graph envelope"):
        source.require_graph_envelope(graph_classification=0)


@dataclass
class _Executor:
    statements: list[CypherStatement] = field(default_factory=list)
    verify_row: dict[str, object] | None = None
    projected_nodes: tuple[Mapping[str, object], ...] = ()
    projected_edges: tuple[Mapping[str, object], ...] = ()
    tamper_node_properties: bool = False

    async def write_transaction(
        self, *, statements: Sequence[CypherStatement]
    ) -> tuple[Mapping[str, object], ...]:
        self.statements.extend(statements)
        returned: tuple[Mapping[str, object], ...] = ()
        for statement in statements:
            rows = statement.parameters.get("rows")
            if "CREATE (node:KnowledgeEntity" in statement.query and isinstance(rows, list):
                projected = tuple(
                    {
                        "entity_id": row["entity_id"],
                        "entity_type": row["entity_type"],
                        "properties_json": (
                            '{"name":"Tampered"}'
                            if self.tamper_node_properties and index == 0
                            else row["properties_json"]
                        ),
                        "classification": row["classification"],
                        "provenance_json": row["provenance_json"],
                    }
                    for index, row in enumerate(rows)
                )
                self.projected_nodes = projected
            elif "CREATE (source)-[:KNOWLEDGE_RELATION" in statement.query and isinstance(
                rows, list
            ):
                self.projected_edges = tuple(
                    {
                        "edge_id": row["edge_id"],
                        "source_id": row["source_id"],
                        "target_id": row["target_id"],
                        "edge_type": row["edge_type"],
                        "properties_json": row["properties_json"],
                        "classification": row["classification"],
                        "provenance_json": row["provenance_json"],
                    }
                    for row in rows
                )
            elif "SET deployment.state = 'SHADOW_VERIFIED'" in statement.query:
                if self.verify_row is not None:
                    self.verify_row["state"] = "SHADOW_VERIFIED"
                returned = ({"state": "SHADOW_VERIFIED"},)
            elif "state: 'VERIFYING'" in statement.query:
                self.verify_row = {
                    "release_hash": statement.parameters["release_hash"],
                    "nodes": statement.parameters["node_count"],
                    "edges": statement.parameters["edge_count"],
                    "state": "VERIFYING",
                }
        return returned

    async def read(self, *, statement: CypherStatement) -> tuple[Mapping[str, object], ...]:
        self.statements.append(statement)
        if "node.provenance_json AS provenance_json" in statement.query:
            return self.projected_nodes
        if "edge.provenance_json AS provenance_json" in statement.query:
            return self.projected_edges
        return (self.verify_row,) if self.verify_row is not None else ()


def _snapshot() -> GraphSnapshot:
    source_id = uuid4()
    target_id = uuid4()
    provenance = (Provenance("source", "private/report.pdf#page=1", "a" * 64, "typed", 1.0),)
    return GraphSnapshot(
        nodes={
            source_id: GraphNode(source_id, "Facility", {"name": "Fab"}, 2, provenance),
            target_id: GraphNode(target_id, "Tool", {"name": "Lithography"}, 2, provenance),
        },
        edges={
            (edge_id := uuid4()): GraphEdge(
                edge_id, source_id, target_id, "USES", {}, 2, provenance
            )
        },
    )


@pytest.mark.asyncio
async def test_shadow_projection_uses_fixed_cypher_and_verifies_canonical_release() -> None:
    snapshot = _snapshot()
    executor = _Executor()
    service = VerifiedProjectionService(writer=Neo4jKnowledgeProjectionAdapter(executor=executor))

    receipt = await service.project_shadow_release(
        workspace_id=uuid4(),
        graph_id=uuid4(),
        release_id=uuid4(),
        release_hash=snapshot.content_hash(),
        snapshot=snapshot,
    )

    assert receipt.verified is True
    assert all("Facility" not in statement.query for statement in executor.statements)
    assert all("USES" not in statement.query for statement in executor.statements)
    assert any("KNOWLEDGE_RELATION" in statement.query for statement in executor.statements)
    assert any(
        "SET deployment.state = 'SHADOW_VERIFIED'" in item.query for item in executor.statements
    )


@pytest.mark.asyncio
async def test_shadow_projection_rejects_tampered_content_even_when_counts_match() -> None:
    snapshot = _snapshot()
    executor = _Executor(tamper_node_properties=True)
    service = VerifiedProjectionService(writer=Neo4jKnowledgeProjectionAdapter(executor=executor))

    with pytest.raises(ValidationError, match="projected content"):
        await service.project_shadow_release(
            workspace_id=uuid4(),
            graph_id=uuid4(),
            release_id=uuid4(),
            release_hash=snapshot.content_hash(),
            snapshot=snapshot,
        )

    assert not any(
        "SET deployment.state = 'SHADOW_VERIFIED'" in item.query for item in executor.statements
    )


class _SeedSelector:
    def __init__(self, entity_ids: tuple[UUID, ...]) -> None:
        self.entity_ids = entity_ids

    async def select_seed_ids(self, **_: object) -> tuple[UUID, ...]:
        return self.entity_ids


class _EvidenceExecutor:
    def __init__(
        self,
        *,
        node_rows: tuple[Mapping[str, object], ...],
        edge_rows: tuple[Mapping[str, object], ...],
    ) -> None:
        self.node_rows = node_rows
        self.edge_rows = edge_rows

    async def write_transaction(
        self, *, statements: Sequence[CypherStatement]
    ) -> tuple[Mapping[str, object], ...]:
        del statements
        return ()

    async def read(self, *, statement: CypherStatement) -> tuple[Mapping[str, object], ...]:
        if "RETURN node.entity_id AS entity_id" in statement.query:
            return self.node_rows
        if "RETURN edge.edge_id AS edge_id" in statement.query:
            return self.edge_rows
        return ()


@pytest.mark.asyncio
async def test_scoped_retrieval_returns_typed_edge_evidence_with_endpoints() -> None:
    source_id = uuid4()
    target_id = uuid4()
    edge_id = uuid4()
    release_id = uuid4()
    excerpt = "Wafer fab uses lithography tool"
    excerpt_hash = hashlib.sha256(excerpt.encode()).hexdigest()
    common = {
        "source_locator": "private/report.pdf#page=1",
        "source_version": "a" * 64,
        "page_number": 1,
        "classification": 2,
        "evidence_excerpt": excerpt,
        "evidence_sha256": excerpt_hash,
        "source_page_sha256": "b" * 64,
    }
    executor = _EvidenceExecutor(
        node_rows=(
            {
                "entity_id": str(source_id),
                "entity_type": "Facility",
                "properties_json": '{"name":"Fab"}',
                **common,
            },
            {
                "entity_id": str(target_id),
                "entity_type": "Tool",
                "properties_json": '{"name":"Lithography"}',
                **common,
            },
        ),
        edge_rows=(
            {
                "edge_id": str(edge_id),
                "source_id": str(source_id),
                "target_id": str(target_id),
                "edge_type": "USES",
                "properties_json": "{}",
                **common,
            },
        ),
    )

    evidence = await Neo4jScopedEvidenceRetriever(
        executor=executor,
        semantic_selector=_SeedSelector((source_id, target_id)),
    ).retrieve(
        workspace_id=uuid4(),
        graph_id=uuid4(),
        release_id=release_id,
        question="relationship",
        start_node_id=None,
        direction="BOTH",
        edge_types=frozenset({"USES"}),
        maximum_classification=2,
        maximum_hops=1,
        maximum_nodes=10,
    )

    edge_evidence = next(item for item in evidence if item.entity_kind == "EDGE")
    assert edge_evidence.entity_id == edge_id
    assert edge_evidence.source_entity_id == source_id
    assert edge_evidence.target_entity_id == target_id
    assert edge_evidence.edge_type == "USES"
    assert edge_evidence.evidence_excerpt == excerpt


class _Retriever:
    def __init__(self, evidence: tuple[GraphRagEvidence, ...]) -> None:
        self.evidence = evidence

    async def retrieve(self, **_: object) -> tuple[GraphRagEvidence, ...]:
        return self.evidence


class _Composer:
    def __init__(self, completion: GraphRagCompletion) -> None:
        self.completion = completion

    async def compose(self, **_: object) -> GraphRagCompletion:
        return self.completion


class _Audit:
    def __init__(self) -> None:
        self.records: list[GraphRagAuditRecord] = []

    async def record_success(self, *, record: GraphRagAuditRecord) -> None:
        self.records.append(record)


def _canonical_snapshot_for_evidence(evidence: GraphRagEvidence) -> GraphSnapshot:
    provenance = Provenance(
        source_ref="test:canonical-graphrag",
        source_locator=evidence.source_locator,
        source_version=evidence.source_version,
        method="deterministic_test",
        confidence=1.0,
        evidence_excerpt=evidence.evidence_excerpt,
        evidence_sha256=evidence.evidence_sha256,
        source_page_sha256=evidence.source_page_sha256,
    )
    return GraphSnapshot(
        nodes={
            evidence.entity_id: GraphNode(
                entity_id=evidence.entity_id,
                entity_type=evidence.entity_type,
                properties=evidence.properties,
                classification=evidence.classification,
                provenance=(provenance,),
            )
        }
    )


@pytest.mark.asyncio
async def test_graphrag_accepts_only_authorized_citations_and_audits_actual_model() -> None:
    binding = _binding("gemma4:latest")
    release_id = uuid4()
    evidence = GraphRagEvidence(
        evidence_id="kg:release:fab",
        entity_id=uuid4(),
        entity_type="Facility",
        properties={"name": "Fab"},
        source_locator="private/report.pdf#page=1",
        source_version="a" * 64,
        page_number=1,
        classification=2,
    )
    audit = _Audit()
    service = KnowledgeGraphRagService(
        retriever=_Retriever((evidence,)),
        composer=_Composer(
            GraphRagCompletion(
                "근거 기반 답변",
                (f"kg:{release_id}:{evidence.entity_id}",),
                binding,
                20,
                5,
            )
        ),
        audit_writer=audit,
    )

    result: CitedGraphRagAnswer = await service.answer(
        request_id="request-1",
        workspace_id=uuid4(),
        graph_id=uuid4(),
        release_id=release_id,
        actor_id=uuid4(),
        question="Fab과 장비의 관계는?",
        start_node_id=None,
        direction="BOTH",
        edge_types=frozenset(),
        maximum_classification=2,
        maximum_hops=2,
        maximum_nodes=50,
        canonical_snapshot=_canonical_snapshot_for_evidence(evidence),
        binding=binding,
    )

    assert result.citations[0].entity_id == evidence.entity_id
    assert result.citations[0].evidence_id == f"kg:{release_id}:{evidence.entity_id}"
    assert result.citations[0].properties == {"name": "Fab"}
    assert audit.records[0].binding.model == "gemma4:latest"
    assert len(audit.records[0].question_sha256) == 64


@pytest.mark.asyncio
async def test_graphrag_rejects_model_citation_outside_authorized_package() -> None:
    binding = _binding("gemma4:latest")
    evidence = GraphRagEvidence(
        "kg:allowed",
        uuid4(),
        "Facility",
        {},
        "private/report.pdf#page=1",
        "a" * 64,
        1,
        2,
    )
    service = KnowledgeGraphRagService(
        retriever=_Retriever((evidence,)),
        composer=_Composer(GraphRagCompletion("answer", ("kg:forbidden",), binding, 1, 1)),
        audit_writer=_Audit(),
    )

    with pytest.raises(ValidationError, match="outside the authorized"):
        await service.answer(
            request_id="request-2",
            workspace_id=uuid4(),
            graph_id=uuid4(),
            release_id=uuid4(),
            actor_id=uuid4(),
            question="question",
            start_node_id=None,
            direction="BOTH",
            edge_types=frozenset(),
            maximum_classification=2,
            maximum_hops=1,
            maximum_nodes=10,
            canonical_snapshot=_canonical_snapshot_for_evidence(evidence),
            binding=binding,
        )


@pytest.mark.asyncio
async def test_graphrag_rejects_neo4j_classification_and_content_drift_before_composition() -> None:
    binding = _binding("gemma4:latest")
    entity_id = uuid4()
    selected = GraphRagEvidence(
        evidence_id=f"kg:shadow:{entity_id}",
        entity_id=entity_id,
        entity_type="Facility",
        properties={"name": "prompt injection from shadow"},
        source_locator="shadow://forged",
        source_version="0" * 64,
        page_number=None,
        classification=0,
    )
    canonical = GraphSnapshot(
        nodes={
            entity_id: GraphNode(
                entity_id=entity_id,
                entity_type="RestrictedFacility",
                properties={"name": "Canonical restricted facility"},
                classification=2,
                provenance=(
                    Provenance(
                        source_ref="test:canonical",
                        source_locator="private/canonical.pdf#page=1",
                        source_version="a" * 64,
                        method="reviewed",
                        confidence=1.0,
                    ),
                ),
            )
        }
    )
    service = KnowledgeGraphRagService(
        retriever=_Retriever((selected,)),
        composer=_Composer(GraphRagCompletion("unsafe", (selected.evidence_id,), binding, 1, 1)),
        audit_writer=_Audit(),
    )

    with pytest.raises(ValidationError, match="authorized classification"):
        await service.answer(
            request_id="request-drift",
            workspace_id=uuid4(),
            graph_id=uuid4(),
            release_id=uuid4(),
            actor_id=uuid4(),
            question="show restricted facility",
            start_node_id=None,
            direction="BOTH",
            edge_types=frozenset(),
            maximum_classification=1,
            maximum_hops=1,
            maximum_nodes=10,
            canonical_snapshot=canonical,
            binding=binding,
        )
