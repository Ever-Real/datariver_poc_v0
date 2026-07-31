from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from uuid import UUID

import pytest

from datariver.application.errors import ExternalDependencyError
from datariver.application.services.knowledge_studio_ingestion_worker import (
    KnowledgeStudioIngestionMapper,
    KnowledgeStudioIngestionWorker,
)
from datariver.domain.common import ValidationError
from datariver.domain.knowledge_pipeline import (
    EmbeddingBatch,
    ModelBinding,
    PageEmbedding,
    PdfPage,
)
from datariver.domain.knowledge_studio_ingestion import (
    StudioIngestionBindingClaim,
    StudioIngestionClaim,
    StudioIngestionMaterialization,
    StudioIngestionRule,
    StudioSourceRead,
    StudioVectorReceipt,
)

_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000001")
_JOB_ID = UUID("00000000-0000-4000-8000-000000000002")
_GRAPH_ID = UUID("00000000-0000-4000-8000-000000000003")
_DRAFT_ID = UUID("00000000-0000-4000-8000-000000000004")
_RELEASE_ID = UUID("00000000-0000-4000-8000-000000000005")
_ONTOLOGY_ID = UUID("00000000-0000-4000-8000-000000000006")
_REQUESTER_ID = UUID("00000000-0000-4000-8000-000000000007")
_WORKER_SUBJECT_ID = UUID("00000000-0000-4000-8000-000000000008")
_PIN_ID = UUID("00000000-0000-4000-8000-000000000009")
_BINDING_VERSION_ID = UUID("00000000-0000-4000-8000-00000000000a")
_SOURCE_REFERENCE_ID = UUID("00000000-0000-4000-8000-00000000000b")
_SOURCE_ASSET_ID = UUID("00000000-0000-4000-8000-00000000000c")
_CHANGESET_ID = UUID("00000000-0000-4000-8000-00000000000d")
_SOURCE_READ_DEADLINE = datetime(2026, 7, 31, 12, 30, tzinfo=UTC)


def _embedding_binding(*, model: str = "embedding-v1") -> ModelBinding:
    return ModelBinding(
        provider="test-provider",
        model=model,
        prompt_version="studio-ingestion-v1",
        tool_schema_version="studio-vector-v1",
        configuration_source="DEPLOYMENT",
        configuration_version=None,
        configuration_hash="1" * 64,
    )


def _subject_rule() -> StudioIngestionRule:
    return StudioIngestionRule(
        method="SUBJECT_ID",
        source_field_path="subject_id",
        target_stable_element_id="class:customer",
        target_canonical_name="Customer",
        target_data_type=None,
        target_nullable=None,
        vector_index_enabled=False,
        transform_id="IDENTITY",
        transform_version="1",
    )


def _property_rule(*, vector_index_enabled: bool = True) -> StudioIngestionRule:
    return StudioIngestionRule(
        method="PROPERTY",
        source_field_path="display_name",
        target_stable_element_id="property:customer:display_name",
        target_canonical_name="display_name",
        target_data_type="TEXT",
        target_nullable=False,
        vector_index_enabled=vector_index_enabled,
        transform_id="IDENTITY",
        transform_version="1",
    )


def _binding_claim(
    *,
    source_classification: int = 1,
    vector_index_enabled: bool = True,
) -> StudioIngestionBindingClaim:
    return StudioIngestionBindingClaim(
        pin_id=_PIN_ID,
        binding_version_id=_BINDING_VERSION_ID,
        source_reference_id=_SOURCE_REFERENCE_ID,
        source_asset_id=_SOURCE_ASSET_ID,
        source_version="catalog-source-v7",
        projection_source_version="catalog-projection-v11",
        source_classification=source_classification,
        target_class_stable_id="class:customer",
        target_class_canonical_name="Customer",
        mapping_hash="2" * 64,
        connection_profile_id="warehouse-readonly",
        connection_profile_version=3,
        connection_profile_hash="3" * 64,
        rules=(
            _subject_rule(),
            _property_rule(vector_index_enabled=vector_index_enabled),
        ),
    )


def _claim(
    *,
    graph_classification: int = 1,
    source_classification: int = 1,
    vector_index_enabled: bool = True,
) -> StudioIngestionClaim:
    return StudioIngestionClaim(
        workspace_id=_WORKSPACE_ID,
        job_id=_JOB_ID,
        graph_id=_GRAPH_ID,
        draft_id=_DRAFT_ID,
        studio_release_id=_RELEASE_ID,
        ontology_version_id=_ONTOLOGY_ID,
        requested_by=_REQUESTER_ID,
        graph_classification=graph_classification,
        manifest_id="studio-db-manifest",
        manifest_version=4,
        manifest_hash="4" * 64,
        pin_hash="5" * 64,
        embedding_binding=(_embedding_binding() if vector_index_enabled else None),
        bindings=(
            _binding_claim(
                source_classification=source_classification,
                vector_index_enabled=vector_index_enabled,
            ),
        ),
        attempt_id=UUID("00000000-0000-4000-8000-00000000000e"),
        attempt_no=1,
        lease_epoch=1,
        worker_fingerprint="studio-ingestion-worker-1",
        lease_token="opaque-lease-token",
    )


def _reads(
    *,
    row: dict[str, str | int | float | bool | None] | None = None,
) -> tuple[StudioSourceRead, ...]:
    return (
        StudioSourceRead(
            binding_pin_id=_PIN_ID,
            rows=(
                row
                or {
                    "subject_id": "customer-001",
                    "display_name": "  Alice   Example  ",
                },
            ),
            source_read_receipt_hash="6" * 64,
        ),
    )


class _Store:
    def __init__(
        self,
        claim: StudioIngestionClaim,
        *,
        ensure_results: Sequence[str | None] = (),
    ) -> None:
        self._claim: StudioIngestionClaim | None = claim
        self._ensure_results = list(ensure_results)
        self.events: list[str] = []
        self.failures: list[tuple[str, bool, bool]] = []
        self.completed: (
            tuple[
                StudioIngestionMaterialization,
                tuple[StudioVectorReceipt, ...],
                str,
            ]
            | None
        ) = None
        self.completed_changeset_id: UUID | None = None
        self.fenced_claims: list[StudioIngestionClaim] = []
        self.renewals: list[tuple[str, int]] = []

    async def claim_next(
        self,
        *,
        workspace_id: UUID,
        worker_subject_id: UUID,
        worker_fingerprint: str,
        lease_seconds: int,
    ) -> StudioIngestionClaim | None:
        assert workspace_id == _WORKSPACE_ID
        assert worker_subject_id == _WORKER_SUBJECT_ID
        assert worker_fingerprint == "studio-ingestion-worker-1"
        assert lease_seconds == 300
        self.events.append("claim")
        claim, self._claim = self._claim, None
        return claim

    async def freeze_source_access(
        self,
        *,
        claim: StudioIngestionClaim,
        worker_subject_id: UUID,
        hard_timeout_seconds: int,
        completion_margin_seconds: int,
    ) -> datetime:
        assert claim.source_access_deadline is None
        assert worker_subject_id == _WORKER_SUBJECT_ID
        assert hard_timeout_seconds == 120
        assert completion_margin_seconds == 15
        self.events.append("freeze")
        return _SOURCE_READ_DEADLINE

    async def assert_source_statement_fence(
        self,
        *,
        claim: StudioIngestionClaim,
        worker_subject_id: UUID,
    ) -> None:
        assert claim.source_access_deadline == _SOURCE_READ_DEADLINE
        assert worker_subject_id == _WORKER_SUBJECT_ID
        self.events.append("fence")
        self.fenced_claims.append(claim)

    async def renew(
        self,
        *,
        claim: StudioIngestionClaim,
        worker_subject_id: UUID,
        lease_seconds: int,
        stage: str,
        progress_percent: int,
    ) -> None:
        assert claim.source_access_deadline == _SOURCE_READ_DEADLINE
        assert worker_subject_id == _WORKER_SUBJECT_ID
        assert lease_seconds == 300
        self.events.append(f"renew:{stage}")
        self.renewals.append((stage, progress_percent))

    async def ensure_current(
        self,
        *,
        claim: StudioIngestionClaim,
        worker_subject_id: UUID,
        manifest_id: str,
        manifest_version: int,
        manifest_hash: str,
        current_embedding_binding: ModelBinding | None,
    ) -> str | None:
        assert claim.workspace_id == _WORKSPACE_ID
        assert worker_subject_id == _WORKER_SUBJECT_ID
        assert manifest_id == "studio-db-manifest"
        assert manifest_version == 4
        assert manifest_hash == "4" * 64
        assert current_embedding_binding == claim.embedding_binding
        self.events.append("ensure")
        return self._ensure_results.pop(0) if self._ensure_results else None

    async def complete(
        self,
        *,
        claim: StudioIngestionClaim,
        worker_subject_id: UUID,
        call_id: str,
        materialization: StudioIngestionMaterialization,
        vector_receipts: tuple[StudioVectorReceipt, ...],
        result_hash: str,
    ) -> UUID:
        assert claim.source_access_deadline == _SOURCE_READ_DEADLINE
        assert worker_subject_id == _WORKER_SUBJECT_ID
        assert UUID(call_id)
        assert result_hash == materialization.result_hash(vector_receipts=vector_receipts)
        self.events.append("complete")
        self.completed = (materialization, vector_receipts, result_hash)
        self.completed_changeset_id = _CHANGESET_ID
        return _CHANGESET_ID

    async def fail(
        self,
        *,
        claim: StudioIngestionClaim,
        worker_subject_id: UUID,
        call_id: str,
        failure_code: str,
        retryable: bool,
        stale: bool,
    ) -> None:
        assert claim.workspace_id == _WORKSPACE_ID
        assert worker_subject_id == _WORKER_SUBJECT_ID
        assert UUID(call_id)
        self.events.append("fail")
        self.failures.append((failure_code, retryable, stale))


class _SourceReader:
    manifest_id = "studio-db-manifest"
    manifest_version = 4
    manifest_hash = "4" * 64

    def __init__(
        self,
        reads: tuple[StudioSourceRead, ...],
        *,
        events: list[str],
        error: Exception | None = None,
    ) -> None:
        self._reads = reads
        self._events = events
        self._error = error
        self.calls = 0

    async def read(
        self,
        *,
        claim: StudioIngestionClaim,
        statement_fence: Callable[[], Awaitable[None]],
    ) -> tuple[StudioSourceRead, ...]:
        assert claim.source_access_deadline == _SOURCE_READ_DEADLINE
        self.calls += 1
        self._events.append("read")
        await statement_fence()
        await statement_fence()
        if self._error is not None:
            raise self._error
        return self._reads


class _EmbeddingProvider:
    def __init__(
        self,
        *,
        returned_binding: ModelBinding,
        events: list[str],
    ) -> None:
        self._returned_binding = returned_binding
        self._events = events
        self.calls = 0

    async def embed_pages(
        self,
        *,
        pages: Sequence[PdfPage],
        binding: ModelBinding,
    ) -> EmbeddingBatch:
        assert binding == _embedding_binding()
        self.calls += 1
        self._events.append("embed")
        return EmbeddingBatch(
            binding=self._returned_binding,
            embeddings=tuple(
                PageEmbedding(
                    page_number=page.page_number,
                    vector=(float(page.page_number), 0.25),
                )
                for page in pages
            ),
            input_tokens=4,
        )


def _worker(
    *,
    store: _Store,
    source_reader: _SourceReader,
    embedding_provider: _EmbeddingProvider | None,
    current_embedding_binding: ModelBinding | None = None,
) -> KnowledgeStudioIngestionWorker:
    return KnowledgeStudioIngestionWorker(
        store=store,
        source_reader=source_reader,
        embedding_provider=embedding_provider,
        current_embedding_binding=lambda: (
            current_embedding_binding
            if current_embedding_binding is not None
            else _embedding_binding()
        ),
        workspace_id=_WORKSPACE_ID,
        worker_subject_id=_WORKER_SUBJECT_ID,
        worker_fingerprint="studio-ingestion-worker-1",
        lease_seconds=300,
        source_hard_timeout_seconds=120,
        completion_margin_seconds=15,
    )


def test_mapper_builds_deterministic_typed_identity_and_vector_input() -> None:
    claim = _claim()

    first = KnowledgeStudioIngestionMapper.materialize(
        claim=claim,
        reads=_reads(),
    )
    second = KnowledgeStudioIngestionMapper.materialize(
        claim=claim,
        reads=_reads(),
    )

    assert first == second
    assert len(first.operations) == 1
    operation = first.operations[0]
    assert operation.stable_entity_id == second.operations[0].stable_entity_id
    assert operation.document == {
        "entity_type": "Customer",
        "properties": {"display_name": "  Alice   Example  "},
        "classification": 1,
    }
    assert operation.provenance[0].source_ref == (f"knowledge-studio-binding:{_BINDING_VERSION_ID}")
    assert len(first.vector_inputs) == 1
    assert first.vector_inputs[0].entity_id == operation.stable_entity_id
    assert first.vector_inputs[0].property_stable_id == ("property:customer:display_name")
    assert first.vector_inputs[0].text == "Alice Example"


def test_mapper_rejects_fields_outside_the_released_mapping() -> None:
    claim = _claim()

    with pytest.raises(ValidationError, match="unrequested field"):
        KnowledgeStudioIngestionMapper.materialize(
            claim=claim,
            reads=_reads(
                row={
                    "subject_id": "customer-001",
                    "display_name": "Alice",
                    "credential": "must-not-cross-boundary",
                }
            ),
        )


def test_mapper_enforces_the_graph_classification_ceiling() -> None:
    claim = _claim(graph_classification=1, source_classification=2)

    with pytest.raises(
        ValidationError,
        match="exceeds the graph classification envelope",
    ):
        KnowledgeStudioIngestionMapper.materialize(
            claim=claim,
            reads=_reads(),
        )


@pytest.mark.asyncio
async def test_worker_fences_source_statements_and_completes_one_typed_draft() -> None:
    claim = _claim()
    store = _Store(claim)
    reader = _SourceReader(_reads(), events=store.events)
    embedding = _EmbeddingProvider(
        returned_binding=_embedding_binding(),
        events=store.events,
    )

    processed = await _worker(
        store=store,
        source_reader=reader,
        embedding_provider=embedding,
    ).run_once()

    assert processed is True
    assert reader.calls == 1
    assert len(store.fenced_claims) == 2
    assert store.renewals == [
        ("MAPPING", 65),
        ("EMBEDDING", 80),
        ("FINALIZING", 95),
    ]
    assert store.events == [
        "claim",
        "ensure",
        "freeze",
        "read",
        "fence",
        "fence",
        "renew:MAPPING",
        "renew:EMBEDDING",
        "embed",
        "renew:FINALIZING",
        "ensure",
        "complete",
    ]
    assert store.failures == []
    assert store.completed is not None
    materialization, receipts, result_hash = store.completed
    assert len(materialization.operations) == 1
    assert len(receipts) == 1
    assert receipts[0].entity_id == materialization.operations[0].stable_entity_id
    assert receipts[0].vector == (1.0, 0.25)
    assert result_hash == materialization.result_hash(vector_receipts=receipts)
    assert store.completed_changeset_id == _CHANGESET_ID


@pytest.mark.asyncio
async def test_worker_marks_manifest_or_authorization_drift_stale_before_source_access() -> None:
    claim = _claim()
    store = _Store(claim, ensure_results=("STALE_REQUESTER_AUTHORIZATION",))
    reader = _SourceReader(_reads(), events=store.events)

    processed = await _worker(
        store=store,
        source_reader=reader,
        embedding_provider=_EmbeddingProvider(
            returned_binding=_embedding_binding(),
            events=store.events,
        ),
    ).run_once()

    assert processed is True
    assert reader.calls == 0
    assert store.events == ["claim", "ensure", "fail"]
    assert store.failures == [("STALE_REQUESTER_AUTHORIZATION", False, True)]
    assert store.completed is None


@pytest.mark.asyncio
async def test_worker_marks_embedding_provider_binding_drift_stale() -> None:
    claim = _claim()
    store = _Store(claim)
    reader = _SourceReader(_reads(), events=store.events)
    embedding = _EmbeddingProvider(
        returned_binding=_embedding_binding(model="embedding-v2"),
        events=store.events,
    )

    processed = await _worker(
        store=store,
        source_reader=reader,
        embedding_provider=embedding,
    ).run_once()

    assert processed is True
    assert embedding.calls == 1
    assert store.failures == [("STALE_EMBEDDING_BINDING", False, True)]
    assert store.completed is None


@pytest.mark.asyncio
async def test_worker_marks_retryable_source_failure_without_completion() -> None:
    claim = _claim(vector_index_enabled=False)
    store = _Store(claim)
    reader = _SourceReader(
        _reads(),
        events=store.events,
        error=ExternalDependencyError(
            "source unavailable",
            dependency="studio_source",
            retryable=True,
            provider_code="SOURCE_TIMEOUT",
        ),
    )

    worker = KnowledgeStudioIngestionWorker(
        store=store,
        source_reader=reader,
        embedding_provider=None,
        current_embedding_binding=lambda: None,
        workspace_id=_WORKSPACE_ID,
        worker_subject_id=_WORKER_SUBJECT_ID,
        worker_fingerprint="studio-ingestion-worker-1",
        lease_seconds=300,
        source_hard_timeout_seconds=120,
        completion_margin_seconds=15,
    )
    processed = await worker.run_once()

    assert processed is True
    assert store.failures == [("SOURCE_TIMEOUT", True, False)]
    assert store.completed is None


@pytest.mark.asyncio
async def test_worker_returns_false_when_no_job_is_claimed() -> None:
    claim = _claim()
    store = _Store(claim)
    store._claim = None
    reader = _SourceReader(_reads(), events=store.events)

    processed = await _worker(
        store=store,
        source_reader=reader,
        embedding_provider=_EmbeddingProvider(
            returned_binding=_embedding_binding(),
            events=store.events,
        ),
    ).run_once()

    assert processed is False
    assert store.events == ["claim"]
    assert store.failures == []
    assert store.completed is None
