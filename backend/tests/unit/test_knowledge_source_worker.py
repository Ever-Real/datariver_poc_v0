from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest

from datariver.application.knowledge_pipeline_ports import KnowledgeRuntimeBindings
from datariver.application.knowledge_source_job_contracts import (
    KnowledgeSourceJobClaim,
    KnowledgeSourceJobRecord,
)
from datariver.application.ports import ObjectStore
from datariver.application.services.knowledge_source_worker import KnowledgeSourceWorker
from datariver.domain.common import ConflictError
from datariver.domain.knowledge_pipeline import (
    EmbeddingBatch,
    ExtractedNodeDraft,
    ExtractionDraft,
    KnowledgeSourceAnalysis,
    KnowledgeSourceSnapshot,
    ModelBinding,
    PageEmbedding,
    PdfPage,
)
from datariver.domain.knowledge_source_jobs import (
    KnowledgeSourceJobPins,
    KnowledgeSourceJobStage,
    KnowledgeSourceJobState,
)
from datariver.infrastructure.knowledge.document import BoundedKnowledgeDocumentParser
from datariver.infrastructure.knowledge.object_store import ObjectStoreKnowledgeSourceReader
from datariver.infrastructure.knowledge.pdf import PypdfPageAwareParser
from datariver.infrastructure.knowledge.runtime import KnowledgeRuntimeAdapters


def _binding(model: str, configuration_hash: str) -> ModelBinding:
    return ModelBinding(
        provider="ollama",
        model=model,
        prompt_version="knowledge-v1",
        tool_schema_version="knowledge-schema-v1",
        configuration_source="DEPLOYMENT",
        configuration_version=None,
        configuration_hash=configuration_hash,
    )


class _Embedding:
    def __init__(self) -> None:
        self.calls = 0

    async def embed_pages(
        self, *, pages: Sequence[PdfPage], binding: ModelBinding
    ) -> EmbeddingBatch:
        self.calls += 1
        return EmbeddingBatch(
            binding=binding,
            embeddings=tuple(
                PageEmbedding(page_number=page.page_number, vector=(0.1, 0.2)) for page in pages
            ),
            input_tokens=5,
        )


class _Extractor:
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
        del entity_types, edge_types
        page = pages[0]
        return ExtractionDraft(
            binding=binding,
            nodes=(
                ExtractedNodeDraft(
                    local_key="AssetOne",
                    entity_type="Asset",
                    properties={"name": "asset one"},
                    classification=1,
                    page_number=page.page_number,
                    evidence_text="asset one",
                    confidence=0.9,
                ),
            ),
            edges=(),
            input_tokens=5,
            output_tokens=5,
        )


class _ObjectStore:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.reads = 0

    async def iter_object_chunks(
        self,
        *,
        bucket: str,
        object_key: str,
    ) -> AsyncIterator[bytes]:
        del bucket, object_key
        self.reads += 1
        yield self.payload


@dataclass
class _Page:
    text: str

    def extract_text(self) -> str:
        return self.text


@dataclass
class _Reader:
    pages: list[_Page]
    is_encrypted: bool = False


class _Store:
    def __init__(
        self,
        claim: KnowledgeSourceJobClaim,
        *,
        cancel_at_ensure: bool = False,
        stale_at_ensure: int | None = None,
    ) -> None:
        self.claim = claim
        self.record = claim.job
        self.cancel_at_ensure = cancel_at_ensure
        self.stale_at_ensure = stale_at_ensure
        self.ensure_calls = 0
        self.renewed: list[str] = []
        self.finalized: KnowledgeSourceAnalysis | None = None
        self.stale_code: str | None = None
        self.cancelled = False
        self.failed: tuple[str, bool] | None = None

    async def claim_next(self, **kwargs: object) -> KnowledgeSourceJobClaim | None:
        del kwargs
        claim, self.claim = self.claim, cast(Any, None)
        return claim

    async def renew(self, **kwargs: object) -> datetime:
        self.renewed.append(str(kwargs["stage"]))
        return datetime(2026, 7, 24, 2, tzinfo=UTC)

    async def ensure_current(self, **kwargs: object) -> str | None:
        del kwargs
        self.ensure_calls += 1
        if self.cancel_at_ensure:
            self.cancel_at_ensure = False
            raise ConflictError(
                "cancel",
                details={"code": "CANCEL_REQUESTED", "retryable": False},
            )
        if self.stale_at_ensure == self.ensure_calls:
            return "STALE_REQUESTER_AUTHORIZATION"
        return None

    async def mark_cancelled(self, **kwargs: object) -> None:
        del kwargs
        self.cancelled = True

    async def mark_failed(self, **kwargs: object) -> None:
        self.failed = (str(kwargs["failure_code"]), bool(kwargs["retryable"]))

    async def mark_stale(self, **kwargs: object) -> None:
        self.stale_code = str(kwargs["failure_code"])

    async def finalize(self, **kwargs: object) -> KnowledgeSourceJobRecord:
        self.finalized = cast(KnowledgeSourceAnalysis, kwargs["analysis"])
        return self.record


def _claim(
    payload: bytes,
    *,
    media_type: str = "application/pdf",
    object_key: str = "private/source.pdf",
) -> KnowledgeSourceJobClaim:
    now = datetime(2026, 7, 24, 1, tzinfo=UTC)
    workspace_id = uuid4()
    graph_id = uuid4()
    snapshot_id = uuid4()
    upload_id = uuid4()
    embedding = _binding("embed", "a" * 64)
    extraction = _binding("extract", "b" * 64)
    source = KnowledgeSourceSnapshot(
        snapshot_id=snapshot_id,
        workspace_id=workspace_id,
        graph_id=graph_id,
        bucket="accepted",
        object_key=object_key,
        storage_version="manifest-v1",
        media_type=media_type,
        byte_size=len(payload),
        content_sha256=hashlib.sha256(payload).hexdigest(),
        classification=1,
    )
    pins = KnowledgeSourceJobPins(
        workspace_id=workspace_id,
        graph_id=graph_id,
        source_snapshot_id=snapshot_id,
        upload_id=upload_id,
        source_storage_version="manifest-v1",
        source_content_sha256=source.content_sha256,
        source_classification=1,
        source_content_profile="KNOWLEDGE_SOURCE_DOCUMENT_V1",
        source_validation_evidence_hash="9" * 64,
        graph_version=1,
        base_release_id=None,
        base_release_hash=None,
        ontology_version_id=uuid4(),
        ontology_checksum="c" * 64,
        parser_configuration_hash="d" * 64,
        embedding_binding=embedding,
        extraction_binding=extraction,
        prepared_at=now,
    )
    record = KnowledgeSourceJobRecord(
        job_id=uuid4(),
        workspace_id=workspace_id,
        graph_id=graph_id,
        source_snapshot_id=snapshot_id,
        upload_id=upload_id,
        requested_by=uuid4(),
        title="proposal",
        state=KnowledgeSourceJobState.RUNNING,
        stage=KnowledgeSourceJobStage.SOURCE_READ,
        progress={},
        attempt_count=1,
        maximum_attempts=3,
        next_attempt_at=now,
        last_failure_code=None,
        version=2,
        created_at=now,
        updated_at=now,
        completed_at=None,
        result=None,
    )
    return KnowledgeSourceJobClaim(
        job=record,
        pins=pins,
        source=source,
        entity_types=frozenset({"Asset"}),
        edge_types=frozenset(),
        attempt_id=uuid4(),
        attempt_no=1,
        lease_epoch=1,
        worker_fingerprint="worker-1",
        lease_token="raw-secret-token",
    )


def _runtime(
    claim: KnowledgeSourceJobClaim,
    *,
    embedding: _Embedding | None = None,
    extractor: _Extractor | None = None,
) -> KnowledgeRuntimeAdapters:
    return KnowledgeRuntimeAdapters(
        embedding=cast(Any, embedding or _Embedding()),
        extractor=cast(Any, extractor or _Extractor()),
        composer=cast(Any, object()),
        bindings=KnowledgeRuntimeBindings(
            embedding=claim.pins.embedding_binding,
            extraction=claim.pins.extraction_binding,
            graphrag=claim.pins.extraction_binding,
        ),
    )


def _worker(
    *,
    store: _Store,
    object_store: _ObjectStore,
    runtime: KnowledgeRuntimeAdapters,
    parser: object | None = None,
) -> KnowledgeSourceWorker:
    async def resolve_runtime(_: KnowledgeSourceJobClaim) -> KnowledgeRuntimeAdapters:
        return runtime

    return KnowledgeSourceWorker(
        store=store,
        source_reader=ObjectStoreKnowledgeSourceReader(
            object_store=cast(ObjectStore, object_store)
        ),
        parser=cast(
            Any,
            parser or PypdfPageAwareParser(reader_factory=lambda _: _Reader([_Page("asset one")])),
        ),
        runtime_resolver=resolve_runtime,
        worker_fingerprint="worker-1",
        lease_seconds=300,
        maximum_attempts=3,
    )


@pytest.mark.asyncio
async def test_worker_spools_checkpoints_and_finalizes_one_typed_draft() -> None:
    payload = b"%PDF-safe"
    claim = _claim(payload)
    store = _Store(claim)
    object_store = _ObjectStore(payload)

    processed = await _worker(
        store=store,
        object_store=object_store,
        runtime=_runtime(claim),
    ).run_once()

    assert processed
    assert object_store.reads == 1
    assert store.failed is None
    assert store.finalized is not None
    assert store.finalized.extraction.nodes[0].local_key == "AssetOne"
    assert {"SOURCE_READ", "PARSED", "EMBEDDED", "EXTRACTED", "FINALIZING"}.issubset(store.renewed)


@pytest.mark.asyncio
async def test_worker_extracts_a_governed_text_document_into_the_same_draft_boundary() -> None:
    payload = b"asset one"
    claim = _claim(
        payload,
        media_type="text/plain",
        object_key="private/source.txt",
    )
    store = _Store(claim)

    processed = await _worker(
        store=store,
        object_store=_ObjectStore(payload),
        runtime=_runtime(claim),
        parser=BoundedKnowledgeDocumentParser(),
    ).run_once()

    assert processed
    assert store.failed is None
    assert store.finalized is not None
    assert store.finalized.source.media_type == "text/plain"
    operations = store.finalized.extraction.nodes
    assert operations[0].local_key == "AssetOne"


@pytest.mark.asyncio
async def test_worker_rejects_runtime_binding_drift_before_object_read() -> None:
    payload = b"%PDF-safe"
    claim = _claim(payload)
    store = _Store(claim)
    object_store = _ObjectStore(payload)
    runtime = _runtime(claim)
    runtime = KnowledgeRuntimeAdapters(
        embedding=runtime.embedding,
        extractor=runtime.extractor,
        composer=runtime.composer,
        bindings=KnowledgeRuntimeBindings(
            embedding=runtime.bindings.embedding,
            extraction=replace(
                runtime.bindings.extraction,
                configuration_hash="f" * 64,
            ),
            graphrag=runtime.bindings.graphrag,
        ),
    )

    await _worker(store=store, object_store=object_store, runtime=runtime).run_once()

    assert store.stale_code == "STALE_MODEL_BINDING"
    assert object_store.reads == 0
    assert store.finalized is None


@pytest.mark.asyncio
async def test_worker_honors_cancel_before_source_read() -> None:
    payload = b"%PDF-safe"
    claim = _claim(payload)
    store = _Store(claim, cancel_at_ensure=True)
    object_store = _ObjectStore(payload)

    await _worker(
        store=store,
        object_store=object_store,
        runtime=_runtime(claim),
    ).run_once()

    assert store.cancelled
    assert object_store.reads == 0
    assert store.finalized is None


@pytest.mark.asyncio
async def test_worker_rechecks_authorization_before_first_provider_egress() -> None:
    payload = b"%PDF-safe"
    claim = _claim(payload)
    store = _Store(claim, stale_at_ensure=3)
    object_store = _ObjectStore(payload)
    embedding = _Embedding()
    extractor = _Extractor()

    await _worker(
        store=store,
        object_store=object_store,
        runtime=_runtime(claim, embedding=embedding, extractor=extractor),
    ).run_once()

    assert object_store.reads == 1
    assert store.stale_code == "STALE_REQUESTER_AUTHORIZATION"
    assert embedding.calls == 0
    assert extractor.calls == 0
    assert store.finalized is None
