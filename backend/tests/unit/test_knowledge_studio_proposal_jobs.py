from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from datariver.application.dto import (
    KnowledgeStudioDraftRecord,
    KnowledgeStudioTBoxBlockRecord,
    KnowledgeStudioTBoxElementRecord,
    KnowledgeStudioTBoxRecord,
)
from datariver.application.knowledge_studio_proposal_job_contracts import (
    KnowledgeStudioProposalCompletion,
    KnowledgeStudioProposalDocument,
    KnowledgeStudioProposalJobClaim,
    KnowledgeStudioProposalJobRecord,
    KnowledgeStudioProposalRuntime,
    KnowledgeStudioProposalSourceLocator,
)
from datariver.application.services.knowledge_studio_proposal_jobs import (
    knowledge_studio_proposal_base_tbox_document,
    knowledge_studio_proposal_base_tbox_hash,
)
from datariver.application.services.knowledge_studio_proposal_worker import (
    KnowledgeStudioProposalWorker,
)
from datariver.domain.authz import Action, Classification, SubjectAttributes
from datariver.domain.common import ConflictError, ValidationError
from datariver.domain.knowledge_pipeline import ModelBinding
from datariver.domain.knowledge_studio import (
    TBoxElementInput,
    TBoxElementKind,
    TBoxProposalMode,
)
from datariver.domain.knowledge_studio_proposal_jobs import (
    KNOWLEDGE_STUDIO_CATALOG_SOURCE_PIN_V2,
    KnowledgeStudioAcceptedUploadPin,
    KnowledgeStudioCatalogFieldMetadataPin,
    KnowledgeStudioCatalogSourcePin,
    KnowledgeStudioProposalInputKind,
    KnowledgeStudioProposalJobPins,
    KnowledgeStudioProposalJobStage,
    KnowledgeStudioProposalJobState,
    knowledge_studio_proposal_requester_authorization_document,
    knowledge_studio_proposal_requester_authorization_hash,
    render_knowledge_studio_catalog_prompt,
)
from datariver.infrastructure.cache import redis as redis_cache
from datariver.infrastructure.cache.redis import DeliveredEvent, RedisEventDelivery
from datariver.infrastructure.db.knowledge_studio_proposal_jobs import _catalog_source_pin
from datariver.infrastructure.db.models.knowledge_studio import (
    KnowledgeStudioProposalAttemptModel,
    KnowledgeStudioProposalEventModel,
    KnowledgeStudioProposalJobModel,
)
from datariver.infrastructure.knowledge.proposal_document import (
    ObjectStoreKnowledgeStudioProposalDocumentReader,
)
from datariver.workers import knowledge_tbox_proposal as proposal_worker_module

WORKSPACE_ID = UUID("10000000-0000-4000-8000-000000000001")
DRAFT_ID = UUID("10000000-0000-4000-8000-000000000002")
ACTOR_ID = UUID("10000000-0000-4000-8000-000000000003")
JOB_ID = UUID("10000000-0000-4000-8000-000000000004")
ATTEMPT_ID = UUID("10000000-0000-4000-8000-000000000005")
MANIFEST_ID = UUID("10000000-0000-4000-8000-000000000006")
WORKER_ID = UUID("10000000-0000-4000-8000-000000000007")
BLOCK_ID = UUID("10000000-0000-4000-8000-000000000008")
NOW = datetime(2026, 7, 31, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _binding(*, model: str = "schema-model") -> ModelBinding:
    return ModelBinding(
        provider="enterprise-gateway",
        model=model,
        prompt_version="tbox-proposal-v1",
        tool_schema_version="tbox-schema-v1",
        configuration_source="DEPLOYMENT",
        configuration_hash=SHA_C,
    )


def _document_pins(content: bytes) -> KnowledgeStudioProposalJobPins:
    return KnowledgeStudioProposalJobPins(
        workspace_id=WORKSPACE_ID,
        draft_id=DRAFT_ID,
        requested_by=ACTOR_ID,
        input_kind=KnowledgeStudioProposalInputKind.DOCUMENT_SCHEMA,
        mode=TBoxProposalMode.MERGE_INTO_CURRENT,
        target_block_id=BLOCK_ID,
        base_draft_version=4,
        base_tbox_hash=SHA_A,
        source=KnowledgeStudioAcceptedUploadPin(
            manifest_id=MANIFEST_ID,
            manifest_version=3,
            content_sha256=hashlib.sha256(content).hexdigest(),
            media_type="text/plain",
            size_bytes=len(content),
            classification=1,
            content_profile="KNOWLEDGE_STUDIO_DOCUMENT_V1",
            validation_evidence_hash=SHA_B,
            filename="schema.txt",
        ),
        parser_configuration_hash=SHA_B,
        schema_binding=_binding(),
        requester_authorization_hash=SHA_C,
        prepared_at=NOW,
    )


def _record() -> KnowledgeStudioProposalJobRecord:
    return KnowledgeStudioProposalJobRecord(
        job_id=JOB_ID,
        workspace_id=WORKSPACE_ID,
        draft_id=DRAFT_ID,
        requested_by=ACTOR_ID,
        input_kind=KnowledgeStudioProposalInputKind.DOCUMENT_SCHEMA,
        mode=TBoxProposalMode.MERGE_INTO_CURRENT,
        target_block_id=BLOCK_ID,
        state=KnowledgeStudioProposalJobState.RUNNING,
        stage=KnowledgeStudioProposalJobStage.SOURCE_VALIDATION,
        progress_percent=5,
        attempt_count=1,
        maximum_attempts=3,
        next_attempt_at=NOW,
        last_failure_code=None,
        version=2,
        created_at=NOW,
        updated_at=NOW,
        completed_at=None,
        result=None,
    )


def _claim(content: bytes) -> KnowledgeStudioProposalJobClaim:
    return KnowledgeStudioProposalJobClaim(
        job=_record(),
        pins=_document_pins(content),
        current_elements=(),
        attempt_id=ATTEMPT_ID,
        attempt_no=1,
        lease_epoch=1,
        worker_fingerprint="proposal-worker-1",
        lease_token="secret-lease-token",
        source_locator=KnowledgeStudioProposalSourceLocator(
            bucket="accepted",
            object_key="knowledge-eligible/private-object",
        ),
    )


class _Assistant:
    def __init__(self, proposed: tuple[TBoxElementInput, ...] | None = None) -> None:
        self.calls = 0
        self.proposed = (
            proposed
            if proposed is not None
            else (
                TBoxElementInput(
                    stable_element_id="asset",
                    kind=TBoxElementKind.CLASS,
                    canonical_name="Asset",
                    display_name="Asset",
                ),
            )
        )

    async def propose(self, **_kwargs: object) -> tuple[TBoxElementInput, ...]:
        self.calls += 1
        return self.proposed


class _Reader:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.calls = 0

    async def read_document(
        self,
        *,
        claim: KnowledgeStudioProposalJobClaim,
    ) -> KnowledgeStudioProposalDocument:
        assert claim.source_locator is not None
        self.calls += 1
        return KnowledgeStudioProposalDocument(
            filename="schema.txt",
            media_type="text/plain",
            content=self.content,
        )


class _ObjectStore:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self.chunks = chunks
        self.calls: list[tuple[str, str]] = []

    async def iter_object_chunks(
        self,
        *,
        bucket: str,
        object_key: str,
    ) -> AsyncIterator[bytes]:
        self.calls.append((bucket, object_key))
        for chunk in self.chunks:
            yield chunk


class _Store:
    def __init__(self, claim: KnowledgeStudioProposalJobClaim) -> None:
        self.claim = claim
        self.renewed: list[tuple[str, int]] = []
        self.completed: KnowledgeStudioProposalCompletion | None = None
        self.failed: list[tuple[str, bool, bool]] = []
        self.drift: str | None = None

    async def claim_next(self, **_kwargs: object) -> KnowledgeStudioProposalJobClaim | None:
        return self.claim

    async def renew(self, **kwargs: object) -> datetime:
        progress_percent = kwargs["progress_percent"]
        assert isinstance(progress_percent, int)
        self.renewed.append((str(kwargs["stage"]), progress_percent))
        return NOW

    async def ensure_current(self, **_kwargs: object) -> str | None:
        return self.drift

    async def complete(self, **kwargs: object) -> KnowledgeStudioProposalJobRecord:
        completion = kwargs["completion"]
        assert isinstance(completion, KnowledgeStudioProposalCompletion)
        self.completed = completion
        return self.claim.job

    async def fail(self, **kwargs: object) -> None:
        self.failed.append(
            (
                str(kwargs["failure_code"]),
                bool(kwargs["retryable"]),
                bool(kwargs["stale"]),
            )
        )


def test_proposal_job_pins_never_persist_object_coordinates_or_document_text() -> None:
    pins = _document_pins(b"Schema title")
    claim = _claim(b"Schema title")

    document = pins.to_document()

    assert pins.evidence_hash() == pins.evidence_hash()
    assert "bucket" not in str(document).lower()
    assert "object_key" not in str(document).lower()
    assert "Schema title" not in str(document)
    assert "secret-lease-token" not in repr(claim)
    assert "knowledge-eligible/private-object" not in repr(claim)


@pytest.mark.asyncio
async def test_object_reader_streams_and_rechecks_the_exact_immutable_pin(
    tmp_path: Path,
) -> None:
    content = b"bounded schema source"
    object_store = _ObjectStore((content[:7], content[7:]))
    reader = ObjectStoreKnowledgeStudioProposalDocumentReader(
        object_store=object_store,  # type: ignore[arg-type]
        memory_spool_bytes=4_096,
        spool_directory=str(tmp_path),
    )

    document = await reader.read_document(claim=_claim(content))

    assert document.content == content
    assert object_store.calls == [("accepted", "knowledge-eligible/private-object")]
    assert content.decode() not in repr(document)


@pytest.mark.asyncio
async def test_object_reader_rejects_content_hash_drift(tmp_path: Path) -> None:
    reader = ObjectStoreKnowledgeStudioProposalDocumentReader(
        object_store=_ObjectStore((b"tampered",)),  # type: ignore[arg-type]
        memory_spool_bytes=4_096,
        spool_directory=str(tmp_path),
    )

    with pytest.raises(ConflictError, match="immutable pin"):
        await reader.read_document(claim=_claim(b"expected"))


def test_catalog_source_pin_rejects_duplicate_selected_fields() -> None:
    pin = KnowledgeStudioCatalogSourcePin(
        asset_id=MANIFEST_ID,
        name="orders",
        asset_type="TABLE",
        classification=1,
        source_version="v1",
        projection_source_version="projection-v1",
        selected_field_paths=("order_id", "order_id"),
    )

    with pytest.raises(ValidationError, match="unique"):
        pin.validate()


def _catalog_v2_pin() -> KnowledgeStudioCatalogSourcePin:
    return KnowledgeStudioCatalogSourcePin(
        asset_id=MANIFEST_ID,
        name="orders",
        asset_type="TABLE",
        classification=1,
        source_version="datahub-v7",
        projection_source_version="projection-v4",
        selected_field_paths=("order_id", "amount"),
        platform="postgres",
        database_name="sales",
        schema_name="public",
        domain="Finance",
        tags=("gold",),
        glossary_terms=("Order",),
        contract_version=KNOWLEDGE_STUDIO_CATALOG_SOURCE_PIN_V2,
        description="Governed order facts",
        field_metadata=(
            KnowledgeStudioCatalogFieldMetadataPin(
                field_path="order_id",
                field_type="KEY",
                native_data_type="uuid",
                description="Order identifier",
                tags=("gold",),
                glossary_terms=("Order",),
            ),
            KnowledgeStudioCatalogFieldMetadataPin(
                field_path="amount",
                native_data_type="numeric(18,2)",
                description="Gross amount",
                glossary_terms=("Amount",),
            ),
        ),
    ).with_computed_metadata_fingerprint()


def test_catalog_v2_source_pin_is_bounded_ordered_and_hashes_exact_metadata() -> None:
    pin = _catalog_v2_pin()
    document = pin.to_document()

    assert document["contract_version"] == KNOWLEDGE_STUDIO_CATALOG_SOURCE_PIN_V2
    assert document["selected_field_paths"] == ["order_id", "amount"]
    field_metadata = cast(list[dict[str, object]], document["field_metadata"])
    assert [item["field_path"] for item in field_metadata] == [
        "order_id",
        "amount",
    ]
    assert document["metadata_fingerprint"] == pin.metadata_fingerprint
    assert len(render_knowledge_studio_catalog_prompt(pin)) <= 4_000

    changed = replace(
        pin,
        field_metadata=(
            replace(pin.field_metadata[0], description="Changed description"),
            pin.field_metadata[1],
        ),
        metadata_fingerprint=None,
    ).with_computed_metadata_fingerprint()
    assert changed.metadata_fingerprint != pin.metadata_fingerprint
    assert changed.evidence_hash() != pin.evidence_hash()


def test_catalog_v1_document_is_unchanged_and_v2_decoder_rejects_tampering() -> None:
    legacy = KnowledgeStudioCatalogSourcePin(
        asset_id=MANIFEST_ID,
        name="orders",
        asset_type="TABLE",
        classification=1,
        source_version="v1",
        projection_source_version="projection-v1",
        selected_field_paths=("order_id",),
    ).to_document()
    assert "contract_version" not in legacy
    assert "field_metadata" not in legacy

    document = _catalog_v2_pin().to_document()
    assert _catalog_source_pin(document).to_document() == document
    tampered = dict(document)
    tampered["description"] = "Tampered"
    with pytest.raises(ValidationError, match="fingerprint"):
        _catalog_source_pin(tampered)
    extra = dict(document)
    extra["browser_metadata"] = {"trusted": True}
    with pytest.raises(ValidationError, match="fields do not match"):
        _catalog_source_pin(extra)


def test_catalog_v2_source_pin_rejects_metadata_order_and_oversized_prompt() -> None:
    pin = _catalog_v2_pin()
    reordered = replace(
        pin,
        field_metadata=tuple(reversed(pin.field_metadata)),
    )
    with pytest.raises(ValidationError, match="match the selected fields in order"):
        reordered.validate()

    large = replace(
        pin,
        field_metadata=(
            replace(pin.field_metadata[0], description="가" * 1_000),
            replace(pin.field_metadata[1], description="나" * 1_000),
        ),
        description="다" * 1_000,
        metadata_fingerprint=None,
    ).with_computed_metadata_fingerprint()
    with pytest.raises(ValidationError, match="Select fewer fields"):
        render_knowledge_studio_catalog_prompt(large)


def test_catalog_v2_source_pin_enforces_authoritative_metadata_bounds() -> None:
    pin = _catalog_v2_pin()
    with pytest.raises(ValidationError, match="between 1 and 100"):
        replace(
            pin,
            selected_field_paths=tuple(f"field_{index}" for index in range(101)),
        ).validate()
    with pytest.raises(ValidationError, match="field path"):
        replace(pin.field_metadata[0], field_path="x" * 2_001).validate()
    with pytest.raises(ValidationError, match="field type"):
        replace(pin.field_metadata[0], field_type="x" * 501).validate()
    with pytest.raises(ValidationError, match="field tag set"):
        replace(
            pin.field_metadata[0],
            tags=tuple(f"tag-{index}" for index in range(21)),
        ).validate()
    with pytest.raises(ValidationError, match="field glossary term"):
        replace(pin.field_metadata[0], glossary_terms=("x" * 241,)).validate()
    with pytest.raises(ValidationError, match="catalog tag set"):
        replace(pin, tags=tuple(f"tag-{index}" for index in range(101))).validate()
    with pytest.raises(ValidationError, match="catalog glossary term"):
        replace(pin, glossary_terms=("x" * 256,)).validate()

    paths = tuple(f"field_{index}" for index in range(100))
    oversized_document = replace(
        pin,
        selected_field_paths=paths,
        field_metadata=tuple(
            KnowledgeStudioCatalogFieldMetadataPin(
                field_path=path,
                description="x" * 1_000,
            )
            for path in paths
        ),
        metadata_fingerprint=None,
    ).with_computed_metadata_fingerprint()
    with pytest.raises(ValidationError, match="source document"):
        oversized_document.validate()


def test_completion_rejects_object_coordinates_and_raw_provider_payloads() -> None:
    completion = KnowledgeStudioProposalCompletion(
        elements=(
            TBoxElementInput(
                stable_element_id="asset",
                kind=TBoxElementKind.CLASS,
                canonical_name="Asset",
                display_name="Asset",
            ),
        ),
        conflicts=(),
        prompt_label="Document schema proposal",
        model_binding=_binding().to_document(),
        source_reference={"nested": {"object_key": "private/source.txt"}},
        result_hash=SHA_A,
    )

    with pytest.raises(ValidationError, match="sensitive payload"):
        completion.validate()


def test_proposal_base_tbox_and_authorization_hashes_are_order_stable() -> None:
    draft = KnowledgeStudioDraftRecord(
        draft_id=DRAFT_ID,
        workspace_id=WORKSPACE_ID,
        author_id=ACTOR_ID,
        kind="CREATE",
        state="DRAFT",
        current_step="TBOX",
        name="Asset",
        endpoint_alias="asset",
        endpoint_aliases=("asset",),
        domain_id=MANIFEST_ID,
        domain_source_version="domain-v1",
        classification=Classification.INTERNAL,
        base_graph_id=None,
        base_ontology_version_id=None,
        base_release_id=None,
        last_autosaved_at=NOW,
        version=4,
        created_at=NOW,
        updated_at=NOW,
    )
    first = KnowledgeStudioTBoxElementRecord(
        stable_element_id="z",
        kind="CLASS",
        canonical_name="Zulu",
        display_name="Zulu",
        parent_stable_element_id=None,
        source_stable_element_id=None,
        target_stable_element_id=None,
        data_type=None,
        nullable=None,
        ordinal=2,
        version=1,
    )
    second = KnowledgeStudioTBoxElementRecord(
        stable_element_id="a",
        kind="CLASS",
        canonical_name="Alpha",
        display_name="Alpha",
        parent_stable_element_id=None,
        source_stable_element_id=None,
        target_stable_element_id=None,
        data_type=None,
        nullable=None,
        ordinal=1,
        version=1,
    )
    block = KnowledgeStudioTBoxBlockRecord(
        block_id=BLOCK_ID,
        kind="DIRECT",
        title="Core",
        weight=50,
        ordinal=0,
        collapsed=True,
        version=8,
        source_reference={"must_not_be_folded": True},
        elements=(first, second),
        created_at=NOW,
        updated_at=NOW,
    )
    record = KnowledgeStudioTBoxRecord(draft=draft, blocks=(block,))

    folded = knowledge_studio_proposal_base_tbox_document(record)

    assert folded["contract"] == "KNOWLEDGE_STUDIO_PROPOSAL_BASE_TBOX_V1"
    raw_blocks = folded["blocks"]
    assert isinstance(raw_blocks, list)
    assert [item["stable_element_id"] for item in raw_blocks[0]["elements"]] == [
        "a",
        "z",
    ]
    assert "collapsed" not in raw_blocks[0]
    assert "source_reference" not in raw_blocks[0]
    assert knowledge_studio_proposal_base_tbox_hash(record) == (
        knowledge_studio_proposal_base_tbox_hash(record)
    )

    subject = SubjectAttributes(
        subject_id=ACTOR_ID,
        workspace_id=WORKSPACE_ID,
        active=True,
        department_id=None,
        groups=frozenset({"authors", "knowledge"}),
        job_function="Knowledge Worker",
        clearance=Classification.INTERNAL,
        allowed_actions=frozenset({Action.KG_EDIT, Action.KG_READ}),
        denied_actions=frozenset(),
    )
    authorization = knowledge_studio_proposal_requester_authorization_document(subject)
    assert authorization["groups"] == ["authors", "knowledge"]
    assert authorization["allowed_actions"] == ["kg.edit", "kg.read"]
    assert knowledge_studio_proposal_requester_authorization_hash(subject) == (
        knowledge_studio_proposal_requester_authorization_hash(subject)
    )


@pytest.mark.asyncio
async def test_worker_completes_ready_proposal_without_persisting_document_excerpt() -> None:
    content = "고객과 주문의 논리 스키마".encode()
    claim = _claim(content)
    store = _Store(claim)
    reader = _Reader(content)
    assistant = _Assistant()

    async def runtime(
        _claim: KnowledgeStudioProposalJobClaim,
    ) -> KnowledgeStudioProposalRuntime:
        return KnowledgeStudioProposalRuntime(assistant=assistant, binding=_binding())

    worker = KnowledgeStudioProposalWorker(
        store=store,
        document_reader=reader,
        runtime_resolver=runtime,
        workspace_id=WORKSPACE_ID,
        worker_subject_id=WORKER_ID,
        worker_fingerprint="proposal-worker-1",
        lease_seconds=60,
    )

    assert await worker.run_once() is True
    assert assistant.calls == 1
    assert reader.calls == 1
    assert store.failed == []
    assert store.completed is not None
    assert store.completed.prompt_label == "Document schema proposal: schema.txt"
    assert "고객" not in str(store.completed.source_reference)
    assert [stage for stage, _progress in store.renewed] == [
        "PARSING",
        "INFERENCE",
        "VALIDATING",
        "FINALIZING",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("proposed", "expected_code"),
    [
        (
            (
                TBoxElementInput(
                    stable_element_id="invalid id",
                    kind=TBoxElementKind.CLASS,
                    canonical_name="Invalid",
                    display_name="Invalid",
                ),
            ),
            "TBOX_TYPED_SCHEMA_INVALID",
        ),
        (
            (
                TBoxElementInput(
                    stable_element_id="class:asset-one",
                    kind=TBoxElementKind.CLASS,
                    canonical_name="Asset",
                    display_name="Asset one",
                ),
                TBoxElementInput(
                    stable_element_id="class:asset-two",
                    kind=TBoxElementKind.CLASS,
                    canonical_name="Asset",
                    display_name="Asset two",
                ),
            ),
            "TBOX_DUPLICATE_IDENTITY",
        ),
        (
            (
                TBoxElementInput(
                    stable_element_id="relation:owns",
                    kind=TBoxElementKind.RELATION,
                    canonical_name="OWNS",
                    display_name="Owns",
                    source_stable_element_id="class:owner",
                    target_stable_element_id="class:asset",
                ),
            ),
            "TBOX_UNKNOWN_CLASS",
        ),
        (
            (
                TBoxElementInput(
                    stable_element_id="class:left",
                    kind=TBoxElementKind.CLASS,
                    canonical_name="Left",
                    display_name="Left",
                    parent_stable_element_id="class:right",
                ),
                TBoxElementInput(
                    stable_element_id="class:right",
                    kind=TBoxElementKind.CLASS,
                    canonical_name="Right",
                    display_name="Right",
                    parent_stable_element_id="class:left",
                ),
            ),
            "TBOX_HIERARCHY_CYCLE",
        ),
    ],
)
async def test_worker_fails_closed_with_fixed_safe_validation_codes(
    proposed: tuple[TBoxElementInput, ...],
    expected_code: str,
) -> None:
    content = b"schema"
    claim = _claim(content)
    store = _Store(claim)
    reader = _Reader(content)
    assistant = _Assistant(proposed)

    async def runtime(
        _claim: KnowledgeStudioProposalJobClaim,
    ) -> KnowledgeStudioProposalRuntime:
        return KnowledgeStudioProposalRuntime(assistant=assistant, binding=_binding())

    worker = KnowledgeStudioProposalWorker(
        store=store,
        document_reader=reader,
        runtime_resolver=runtime,
        workspace_id=WORKSPACE_ID,
        worker_subject_id=WORKER_ID,
        worker_fingerprint="proposal-worker-1",
        lease_seconds=60,
    )

    assert await worker.run_once() is True
    assert assistant.calls == 1
    assert store.completed is None
    assert store.failed == [(expected_code, False, False)]
    assert [stage for stage, _progress in store.renewed] == [
        "PARSING",
        "INFERENCE",
        "VALIDATING",
    ]


@pytest.mark.asyncio
async def test_worker_marks_model_binding_drift_stale_before_source_read() -> None:
    content = b"schema"
    claim = _claim(content)
    store = _Store(claim)
    reader = _Reader(content)
    assistant = _Assistant()

    async def runtime(
        _claim: KnowledgeStudioProposalJobClaim,
    ) -> KnowledgeStudioProposalRuntime:
        return KnowledgeStudioProposalRuntime(
            assistant=assistant,
            binding=_binding(model="new-model"),
        )

    worker = KnowledgeStudioProposalWorker(
        store=store,
        document_reader=reader,
        runtime_resolver=runtime,
        workspace_id=WORKSPACE_ID,
        worker_subject_id=WORKER_ID,
        worker_fingerprint="proposal-worker-1",
        lease_seconds=60,
    )

    assert await worker.run_once() is True
    assert assistant.calls == 0
    assert reader.calls == 0
    assert store.completed is None
    assert store.failed == [("STALE_MODEL_BINDING", False, True)]


@pytest.mark.asyncio
async def test_worker_stops_when_database_fence_completes_cancellation() -> None:
    content = b"schema"
    claim = _claim(content)
    store = _Store(claim)
    store.drift = "CANCELLED"
    reader = _Reader(content)
    assistant = _Assistant()

    async def runtime(
        _claim: KnowledgeStudioProposalJobClaim,
    ) -> KnowledgeStudioProposalRuntime:
        return KnowledgeStudioProposalRuntime(assistant=assistant, binding=_binding())

    worker = KnowledgeStudioProposalWorker(
        store=store,
        document_reader=reader,
        runtime_resolver=runtime,
        workspace_id=WORKSPACE_ID,
        worker_subject_id=WORKER_ID,
        worker_fingerprint="proposal-worker-1",
        lease_seconds=60,
    )

    assert await worker.run_once() is True
    assert assistant.calls == 0
    assert reader.calls == 0
    assert store.completed is None
    assert store.failed == []


@pytest.mark.asyncio
async def test_worker_marks_accepted_source_hash_drift_stale() -> None:
    claim = _claim(b"expected")
    store = _Store(claim)
    reader = _Reader(b"tampered")
    assistant = _Assistant()

    async def runtime(
        _claim: KnowledgeStudioProposalJobClaim,
    ) -> KnowledgeStudioProposalRuntime:
        return KnowledgeStudioProposalRuntime(assistant=assistant, binding=_binding())

    worker = KnowledgeStudioProposalWorker(
        store=store,
        document_reader=reader,
        runtime_resolver=runtime,
        workspace_id=WORKSPACE_ID,
        worker_subject_id=WORKER_ID,
        worker_fingerprint="proposal-worker-1",
        lease_seconds=60,
    )

    assert await worker.run_once() is True
    assert assistant.calls == 0
    assert store.completed is None
    assert store.failed == [("STALE_SOURCE_CONTENT", False, True)]


def test_proposal_job_models_exclude_raw_object_coordinates() -> None:
    job_columns = set(KnowledgeStudioProposalJobModel.__table__.columns.keys())

    assert str(KnowledgeStudioProposalJobModel.__table__) == "knowledge.tbox_proposal_jobs"
    assert str(KnowledgeStudioProposalAttemptModel.__table__) == (
        "knowledge.tbox_proposal_attempts"
    )
    assert str(KnowledgeStudioProposalEventModel.__table__) == ("knowledge.tbox_proposal_events")
    assert "bucket" not in job_columns
    assert "object_key" not in job_columns
    assert "prompt" not in job_columns


class _RedisClientDouble:
    def __init__(self) -> None:
        self.xgroup_create = AsyncMock()
        self.xautoclaim = AsyncMock(return_value=(b"0-0", []))
        self.xreadgroup = AsyncMock(return_value=[])
        self.xack = AsyncMock()
        self.ping = AsyncMock(return_value=True)
        self.aclose = AsyncMock()


def _redis_delivery_double(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[RedisEventDelivery, _RedisClientDouble, _RedisClientDouble, list[dict[str, object]]]:
    clients = (_RedisClientDouble(), _RedisClientDouble())
    configurations: list[dict[str, object]] = []

    def from_url(_url: str, **configuration: object) -> object:
        configurations.append(configuration)
        return clients[len(configurations) - 1]

    monkeypatch.setattr(redis_cache, "Redis", SimpleNamespace(from_url=from_url))
    delivery = RedisEventDelivery("redis://delivery:6379/0", password="secret")
    return delivery, clients[0], clients[1], configurations


@pytest.mark.asyncio
async def test_event_delivery_separates_bounded_blocking_and_nonblocking_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delivery, nonblocking, blocking, configurations = _redis_delivery_double(monkeypatch)

    events = await delivery.read_events(
        group="proposal-v1",
        consumer="worker-1",
        block_milliseconds=30_000,
        visibility_timeout_milliseconds=60_000,
    )

    assert events == ()
    assert configurations[0]["socket_connect_timeout"] == 1
    assert configurations[0]["socket_timeout"] == 2
    assert configurations[1]["socket_connect_timeout"] == 1
    assert configurations[1]["socket_timeout"] == 32
    nonblocking.xautoclaim.assert_awaited_once()
    nonblocking.xreadgroup.assert_not_awaited()
    blocking.xreadgroup.assert_awaited_once_with(
        "proposal-v1",
        "worker-1",
        {"datariver:events": ">"},
        count=20,
        block=30_000,
    )

    with pytest.raises(ValueError, match="between 1 and 30000"):
        await delivery.read_events(
            group="proposal-v1",
            consumer="worker-1",
            block_milliseconds=30_001,
            visibility_timeout_milliseconds=60_000,
        )

    await delivery.close()
    blocking.aclose.assert_awaited_once_with()
    nonblocking.aclose.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_proposal_worker_polls_database_before_exact_signal_wakeups_and_acks_all() -> None:
    call_order: list[str] = []

    async def run_once() -> bool:
        call_order.append("database")
        return False

    worker = SimpleNamespace(run_once=AsyncMock(side_effect=run_once))
    events = (
        DeliveredEvent(
            "1-0", MANIFEST_ID, "knowledge.tbox-proposal-job.queued.v1", WORKSPACE_ID, JOB_ID
        ),
        DeliveredEvent(
            "2-0",
            BLOCK_ID,
            "knowledge.tbox-proposal-job.retry_wait.v1",
            WORKSPACE_ID,
            JOB_ID,
        ),
        DeliveredEvent("3-0", WORKER_ID, "unrelated.event.v1", WORKSPACE_ID, JOB_ID),
        DeliveredEvent(
            "4-0",
            ATTEMPT_ID,
            "knowledge.tbox-proposal-job.queued.v1",
            UUID("20000000-0000-4000-8000-000000000001"),
            JOB_ID,
        ),
    )

    async def read_events(**_kwargs: object) -> tuple[DeliveredEvent, ...]:
        call_order.append("redis")
        return events

    delivery = SimpleNamespace(
        read_events=AsyncMock(side_effect=read_events),
        acknowledge=AsyncMock(),
    )

    await proposal_worker_module._run_cycle(
        worker=cast(Any, worker),
        event_delivery=cast(Any, delivery),
        workspace_id=WORKSPACE_ID,
        group="knowledge-tbox-proposal-v1",
        consumer="worker-1",
        block_milliseconds=1_000,
        visibility_timeout_milliseconds=60_000,
    )

    assert proposal_worker_module.SIGNAL_EVENT_TYPES == frozenset(
        {
            "knowledge.tbox-proposal-job.queued.v1",
            "knowledge.tbox-proposal-job.retry_wait.v1",
        }
    )
    assert call_order == ["database", "redis", "database", "database"]
    assert delivery.acknowledge.await_count == 4
    assert [call.kwargs["message_id"] for call in delivery.acknowledge.await_args_list] == [
        "1-0",
        "2-0",
        "3-0",
        "4-0",
    ]


class _HealthSessionContext:
    def __init__(self, scalar_result: object) -> None:
        self.session = SimpleNamespace(scalar=AsyncMock(return_value=scalar_result))

    async def __aenter__(self) -> object:
        return self.session

    async def __aexit__(self, *_args: object) -> None:
        return None


@pytest.mark.asyncio
async def test_proposal_worker_healthcheck_reads_database_and_pings_delivery_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _HealthSessionContext(1)
    delivery = SimpleNamespace(ping=AsyncMock(return_value=True))
    container = SimpleNamespace(
        database=SimpleNamespace(session_factory=lambda: context),
        event_delivery=delivery,
        close=AsyncMock(),
    )
    monkeypatch.setattr(proposal_worker_module, "get_settings", lambda: object())
    monkeypatch.setattr(
        proposal_worker_module,
        "build_knowledge_tbox_proposal_container",
        lambda _settings: container,
    )

    await proposal_worker_module.healthcheck()

    context.session.scalar.assert_awaited_once()
    assert str(context.session.scalar.await_args.args[0]) == "SELECT 1"
    delivery.ping.assert_awaited_once_with()
    container.close.assert_awaited_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("database_result", "delivery_result", "message"),
    [(0, True, "database"), (1, False, "Redis delivery")],
)
async def test_proposal_worker_healthcheck_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    database_result: int,
    delivery_result: bool,
    message: str,
) -> None:
    context = _HealthSessionContext(database_result)
    delivery = SimpleNamespace(ping=AsyncMock(return_value=delivery_result))
    container = SimpleNamespace(
        database=SimpleNamespace(session_factory=lambda: context),
        event_delivery=delivery,
        close=AsyncMock(),
    )
    monkeypatch.setattr(proposal_worker_module, "get_settings", lambda: object())
    monkeypatch.setattr(
        proposal_worker_module,
        "build_knowledge_tbox_proposal_container",
        lambda _settings: container,
    )

    with pytest.raises(RuntimeError, match=message):
        await proposal_worker_module.healthcheck()

    container.close.assert_awaited_once_with()
