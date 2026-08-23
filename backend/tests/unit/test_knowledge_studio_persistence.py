from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, String, Table
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.dto import (
    IdempotencyRecord,
    KnowledgeStudioBindingRecord,
    KnowledgeStudioDraftRecord,
    KnowledgeStudioMappingRuleRecord,
)
from datariver.domain.authz import Classification
from datariver.domain.common import ConflictError, ValidationError
from datariver.domain.knowledge_studio import (
    DEFAULT_KNOWLEDGE_DOMAIN_SOURCE_VERSION,
    DEFAULT_KNOWLEDGE_DOMAINS,
    default_knowledge_domain_id,
)
from datariver.infrastructure.db import models  # noqa: F401
from datariver.infrastructure.db.base import Base
from datariver.infrastructure.db.knowledge_studio import (
    ABOX_BINDING_OPERATION,
    TBOX_BLOCK_CREATE_OPERATION,
    TBOX_BLOCK_DELETE_OPERATION,
    TBOX_BLOCK_UPDATE_OPERATION,
    TBOX_OPERATIONS_OPERATION,
    TBOX_PROPOSAL_APPLY_OPERATION,
    SqlKnowledgeStudioStore,
    _claim_tbox_block_source_mode,
    _decode_asset_release_cursor,
    _encode_asset_release_cursor,
    abox_binding_result,
    resolve_abox_idempotent_replay,
    resolve_studio_idempotent_replay,
    studio_draft_record_from_result,
    studio_draft_result,
)
from datariver.infrastructure.db.models.knowledge import GraphModel
from datariver.infrastructure.db.models.knowledge_studio import (
    KnowledgeStudioReleaseModel,
    TBoxDraftBlockModel,
)

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "backend/alembic/versions/0059_knowledge_studio_foundation.py"
ABOX_MIGRATION = ROOT / "backend/alembic/versions/0060_knowledge_studio_abox_bindings.py"
PUBLICATION_MIGRATION = (
    ROOT / "backend/alembic/versions/0061_knowledge_studio_governed_publication.py"
)
PROPOSAL_JOB_MIGRATION = (
    ROOT / "backend/alembic/versions/0084_governed_knowledge_studio_tbox_proposal_jobs.py"
)
QA_MIGRATION = ROOT / "backend/alembic/versions/0062_knowledge_qa_domain_archive.py"
BUILDER_MIGRATION = ROOT / "backend/alembic/versions/0063_ontology_builder_and_ingestion_jobs.py"
HIERARCHY_MIGRATION = ROOT / "backend/alembic/versions/0064_normalize_tbox_hierarchy.py"
SESSION_MIGRATION = ROOT / "backend/alembic/versions/0066_knowledge_studio_session_domains.py"
INGESTION_MIGRATION = ROOT / "backend/alembic/versions/0081_governed_studio_database_ingestion.py"
CATALOG_PIN_MIGRATION = (
    ROOT / "backend/alembic/versions/0086_knowledge_studio_catalog_metadata_pin_v2.py"
)
PROPOSAL_IDEMPOTENCY_FIX_MIGRATION = (
    ROOT / "backend/alembic/versions/0087_fix_knowledge_studio_proposal_job_idempotency.py"
)
PROPOSAL_CONTRACT_RESTORE_MIGRATION = (
    ROOT / "backend/alembic/versions/0088_restore_knowledge_studio_proposal_contracts.py"
)
PROPOSAL_TRANSITION_IDEMPOTENCY_FIX_MIGRATION = (
    ROOT / "backend/alembic/versions/0093_fix_knowledge_studio_proposal_job_idempotency.py"
)
PROPOSAL_AUTHORIZATION_SCOPE_MIGRATION = (
    ROOT / "backend/alembic/versions/0094_align_knowledge_proposal_authorization_scope.py"
)
PROPOSAL_CONTROL_GUARD_MIGRATION = (
    ROOT / "backend/alembic/versions/0095_fix_tbox_proposal_control_character_guard.py"
)
INITIAL_MIGRATION = ROOT / "backend/alembic/versions/0001_initial_schema.py"
GENERATOR = ROOT / "scripts/generate_initial_migration.py"


def _table(name: str) -> Table:
    return Base.metadata.tables[name]


def _catalog_pin_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "test_knowledge_studio_catalog_pin_v2",
        CATALOG_PIN_MIGRATION,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _proposal_job_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "test_governed_knowledge_studio_tbox_proposal_jobs",
        PROPOSAL_JOB_MIGRATION,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _proposal_idempotency_fix_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "test_knowledge_studio_proposal_idempotency_fix",
        PROPOSAL_IDEMPOTENCY_FIX_MIGRATION,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _proposal_contract_restore_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "test_knowledge_studio_proposal_contract_restore",
        PROPOSAL_CONTRACT_RESTORE_MIGRATION,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _proposal_transition_idempotency_fix_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "test_knowledge_studio_proposal_transition_idempotency_fix",
        PROPOSAL_TRANSITION_IDEMPOTENCY_FIX_MIGRATION,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _proposal_authorization_scope_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "test_knowledge_studio_proposal_authorization_scope",
        PROPOSAL_AUTHORIZATION_SCOPE_MIGRATION,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _proposal_control_guard_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "test_knowledge_studio_proposal_control_guard",
        PROPOSAL_CONTROL_GUARD_MIGRATION,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_asset_release_cursor_is_canonical_and_rejects_tampering() -> None:
    release_id = UUID("019fa57b-52de-74c0-9f5e-06ae7b1c1101")
    published_at = datetime(2026, 7, 31, 1, 2, 3, tzinfo=UTC)
    cursor = _encode_asset_release_cursor(
        published_at=published_at,
        release_id=release_id,
    )

    assert _decode_asset_release_cursor(cursor) == (published_at, release_id)
    with pytest.raises(ValidationError, match="cursor is invalid"):
        _decode_asset_release_cursor(cursor + "=")


def test_asset_release_picker_sql_is_workspace_and_abac_scoped() -> None:
    workspace_id = UUID("019fa57b-52de-74c0-9f5e-06ae7b1c1102")
    domain_id = UUID("019fa57b-52de-74c0-9f5e-06ae7b1c1103")
    statement = SqlKnowledgeStudioStore._tbox_asset_release_statement(workspace_id).where(
        *SqlKnowledgeStudioStore._tbox_asset_release_scope(
            maximum_classification=int(Classification.INTERNAL),
            allowed_domain_ids=frozenset({domain_id}),
        )
    )

    compiled = str(
        statement.compile(
            dialect=postgresql.dialect(),  # type: ignore[no-untyped-call]
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "knowledge.graphs.workspace_id" in compiled
    assert "knowledge.graphs.status != 'ARCHIVED'" in compiled
    assert "knowledge.graphs.classification <= 1" in compiled
    assert "knowledge.graphs.domain_ref_id IN" in compiled
    assert str(domain_id) in compiled


@pytest.mark.asyncio
async def test_asset_release_read_rejects_aggregate_ontology_hash_mismatch() -> None:
    graph_id = UUID("019fa57b-52de-74c0-9f5e-06ae7b1c1104")
    release_id = UUID("019fa57b-52de-74c0-9f5e-06ae7b1c1105")
    ontology_id = UUID("019fa57b-52de-74c0-9f5e-06ae7b1c1106")
    graph = SimpleNamespace(
        id=graph_id,
        name="Governed glossary",
        slug="governed-glossary",
        classification=int(Classification.INTERNAL),
    )
    release = SimpleNamespace(
        id=release_id,
        release_no=2,
        state="ACTIVE",
        contract_hash="a" * 64,
        tbox_hash="b" * 64,
        published_at=datetime(2026, 7, 31, 1, 2, 3, tzinfo=UTC),
        ontology_version_id=ontology_id,
    )
    row = SimpleNamespace(
        _mapping={
            GraphModel: graph,
            KnowledgeStudioReleaseModel: release,
            "domain_name": "Data Governance",
            "class_count": 1,
            "property_count": 0,
            "relationship_count": 0,
        }
    )
    ontology = SimpleNamespace(
        checksum="b" * 64,
        schema_document={"contract_version": "tampered"},
    )
    session = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(one_or_none=lambda: row)),
        scalars=AsyncMock(return_value=SimpleNamespace(one_or_none=lambda: ontology)),
    )
    store = SqlKnowledgeStudioStore(cast(AsyncSession, session))

    with pytest.raises(ConflictError, match="contract hash is invalid"):
        await store.get_tbox_asset_release_source(
            workspace_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1c1107"),
            studio_release_id=release_id,
            maximum_classification=int(Classification.INTERNAL),
            allowed_domain_ids=frozenset({UUID("019fa57b-52de-74c0-9f5e-06ae7b1c1108")}),
        )


def test_studio_draft_model_is_separate_persistent_author_state() -> None:
    draft = _table("knowledge.studio_drafts")
    assert {
        "workspace_id",
        "author_id",
        "kind",
        "state",
        "current_step",
        "name",
        "endpoint_alias",
        "endpoint_aliases",
        "domain_ref_id",
        "domain_ref_kind",
        "domain_source_version",
        "classification",
        "base_graph_id",
        "base_ontology_version_id",
        "base_release_id",
        "submitted_preflight_check_id",
        "reviewed_by",
        "reviewed_at",
        "review_reason",
        "published_by",
        "materialized_graph_id",
        "materialized_ontology_version_id",
        "published_studio_release_id",
        "last_autosaved_at",
        "version",
    } <= set(draft.c.keys())
    assert "expires_at" not in draft.columns

    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in draft.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "DRAFT" in checks["ck_studio_drafts_state_vocabulary"]
    assert "REVIEW" in checks["ck_studio_drafts_state_vocabulary"]
    assert "PUBLISHED" in checks["ck_studio_drafts_state_vocabulary"]
    assert "DISCARDED" in checks["ck_studio_drafts_state_vocabulary"]
    assert "endpoint_alias" in checks["ck_studio_drafts_endpoint_alias_shape"]
    assert (
        "endpoint_aliases ->> 0 = endpoint_alias"
        in (checks["ck_studio_drafts_endpoint_aliases_shape"])
    )

    foreign_keys = {
        constraint.name: constraint
        for constraint in draft.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert (
        foreign_keys["fk_studio_drafts_workspace_id_author_id_workspace_memberships"].ondelete
        == "RESTRICT"
    )
    assert (
        foreign_keys[
            "fk_studio_drafts_workspace_id_domain_ref_id_domain_ref_kind_vocabulary_entries"
        ].ondelete
        == "RESTRICT"
    )

    live_alias = next(
        index
        for index in draft.indexes
        if isinstance(index, Index) and index.name == "uq_studio_drafts_live_endpoint_alias"
    )
    assert live_alias.unique is True
    live_alias_predicate = str(live_alias.dialect_options["postgresql"]["where"])
    assert "DRAFT" in live_alias_predicate
    assert "REVIEW" in live_alias_predicate
    assert next(
        index
        for index in draft.indexes
        if index.name == "ix_studio_drafts_workspace_endpoint_aliases_live"
    )


def test_qa_domain_seed_and_graph_archive_are_deterministic_and_auditable() -> None:
    graph = _table("knowledge.graphs")
    assert {"archived_at", "archived_by"} <= set(graph.c.keys())
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in graph.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ARCHIVED" in checks["ck_graphs_status_vocabulary"]
    assert "archived_by" in checks["ck_graphs_archive_shape"]

    migration = QA_MIGRATION.read_text(encoding="utf-8")
    assert "datariver-default-domains-v1" in migration
    assert "exec_driver_sql" in migration
    assert "knowledge.graphs" in migration
    assert "ARCHIVED" in migration
    assert "Archived Knowledge graph evidence must be restored" in migration
    assert DEFAULT_KNOWLEDGE_DOMAIN_SOURCE_VERSION in migration
    assert tuple(name for _slug, name in DEFAULT_KNOWLEDGE_DOMAINS) == (
        "General",
        "Data Governance",
        "R&D",
        "Finance",
        "Space System",
    )
    assert default_knowledge_domain_id(
        UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b1"),
        "general",
    ) == UUID("3e43b772-b1f5-747c-52c0-bd1c154e595e")


def test_ontology_builder_and_ingestion_models_are_typed_and_rls_governed() -> None:
    blocks = _table("knowledge.tbox_draft_blocks")
    elements = _table("knowledge.tbox_draft_elements")
    classes = _table("knowledge.tbox_classes")
    properties = _table("knowledge.tbox_properties")
    relationships = _table("knowledge.tbox_relationships")
    proposals = _table("knowledge.tbox_proposals")
    jobs = _table("knowledge.studio_ingestion_jobs")
    binding_pins = _table("knowledge.studio_ingestion_binding_pins")
    attempts = _table("knowledge.studio_ingestion_attempts")
    events = _table("knowledge.studio_ingestion_events")
    vector_receipts = _table("knowledge.studio_ingestion_vector_receipts")

    assert {
        "kind",
        "title",
        "weight",
        "ordinal",
        "collapsed",
        "source_reference",
        "version",
    } <= set(blocks.c.keys())
    assert {
        "block_id",
        "definition",
        "aliases",
        "layout_x",
        "layout_y",
    } <= set(elements.c.keys())
    assert {
        "parent_stable_class_id",
        "metadata_reference_id",
        "metadata_reference_urn",
    } <= set(classes.c.keys())
    assert {
        "owner_stable_class_id",
        "data_type",
        "nullable",
        "unit",
        "vector_index_enabled",
        "metadata_reference_id",
        "metadata_reference_urn",
    } <= set(properties.c.keys())
    assert {
        "source_stable_class_id",
        "target_stable_class_id",
        "relationship_kind",
        "metadata_reference_id",
        "metadata_reference_urn",
    } <= set(relationships.c.keys())
    assert {
        "parent_stable_element_id",
        "source_stable_element_id",
        "target_stable_element_id",
        "data_type",
        "nullable",
        "unit",
        "vector_index_enabled",
    }.isdisjoint(elements.c.keys())
    assert elements.c.block_id.nullable is False
    assert {
        "base_draft_version",
        "proposal_document",
        "conflicts_document",
        "model_binding_document",
        "source_reference_document",
        "merge_strategy",
    } <= set(proposals.c.keys())
    assert {
        "state",
        "progress_percent",
        "studio_release_id",
        "ontology_version_id",
        "manifest_hash",
        "pin_hash",
        "requester_authorization_hash",
        "embedding_binding_document",
        "current_attempt_id",
        "lease_epoch",
        "lease_token_hash",
        "lease_owner_fingerprint",
        "result_changeset_id",
    } <= set(jobs.c.keys())
    assert {
        "binding_version_id",
        "source_reference_id",
        "connection_profile_hash",
        "selection_hash",
        "mapping_hash",
        "rules_document",
    } <= set(binding_pins.c.keys())
    assert {
        "attempt_no",
        "lease_epoch",
        "lease_token_hash",
        "worker_fingerprint",
        "source_read_receipt_hash",
        "materialization_hash",
    } <= set(attempts.c.keys())
    assert {"sequence", "state", "actor_kind", "evidence_hash"} <= set(events.c.keys())
    assert {
        "changeset_id",
        "property_ontology_element_id",
        "entity_id",
        "content_hash",
        "embedding_binding_hash",
        "vector_hash",
    } <= set(vector_receipts.c.keys())

    migration = BUILDER_MIGRATION.read_text(encoding="utf-8")
    assert 'revision: str = "0063"' in migration
    assert 'down_revision: str | Sequence[str] | None = "0062"' in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "studio_draft_owner_insert" in migration
    assert "GRANT SELECT, INSERT" in migration
    assert "knowledge.studio_ingestion_jobs" in migration
    assert "vector_index_enabled" in migration
    hierarchy_migration = HIERARCHY_MIGRATION.read_text(encoding="utf-8")
    assert 'revision: str = "0064"' in hierarchy_migration
    assert 'down_revision: str | Sequence[str] | None = "0063"' in hierarchy_migration
    assert "knowledge.tbox_classes" in hierarchy_migration
    assert "knowledge.tbox_properties" in hierarchy_migration
    assert "knowledge.tbox_relationships" in hierarchy_migration
    assert "FORCE ROW LEVEL SECURITY" in hierarchy_migration
    assert "GRANT SELECT, INSERT, DELETE ON knowledge.tbox_classes" in hierarchy_migration
    assert "GRANT UPDATE ON knowledge.tbox_classes" not in hierarchy_migration
    session_migration = SESSION_MIGRATION.read_text(encoding="utf-8")
    assert 'revision: str = "0066"' in session_migration
    assert 'down_revision: str | Sequence[str] | None = "0065"' in session_migration
    assert "endpoint_aliases" in session_migration
    assert "source_reference_document" in session_migration
    assert "created_by" in session_migration
    assert "version >= 1" in session_migration
    assert "GRANT UPDATE (version)" in session_migration
    assert "GRANT UPDATE (created_by" not in session_migration
    ingestion_migration = INGESTION_MIGRATION.read_text(encoding="utf-8")
    assert 'revision: str = "0081"' in ingestion_migration
    assert 'down_revision: str | Sequence[str] | None = "0080"' in ingestion_migration
    assert "datariver_knowledge_ingestion" in ingestion_migration
    assert "STUDIO_INGESTION_ALL_FUNCTION_SQL" in ingestion_migration
    assert "0081 requires explicit reconciliation of legacy Studio ingestion jobs" in (
        ingestion_migration
    )
    vocabulary = _table("catalog.vocabulary_entries")
    assert {"created_by", "version"} <= set(vocabulary.c.keys())
    store_source = (ROOT / "backend/src/datariver/infrastructure/db/knowledge_studio.py").read_text(
        encoding="utf-8"
    )
    assert "SqlKnowledgeStudioIngestionCommandStore(self._session).request(" in (store_source)
    assert '"preflight_receipt_id": str(preflight.id)' not in store_source


def test_studio_typed_mutation_operation_names_fit_the_persisted_bound() -> None:
    operation_column = _table("integration.idempotency_keys").c.operation
    operation_type = operation_column.type
    assert isinstance(operation_type, String)
    assert operation_type.length == 100
    assert operation_type.length is not None
    operations = {
        TBOX_BLOCK_CREATE_OPERATION,
        TBOX_BLOCK_UPDATE_OPERATION,
        TBOX_BLOCK_DELETE_OPERATION,
        TBOX_OPERATIONS_OPERATION,
        TBOX_PROPOSAL_APPLY_OPERATION,
        ABOX_BINDING_OPERATION,
    }
    assert all(len(operation) <= operation_type.length for operation in operations)
    assert len(operations) == 6


def _draft_block(
    *, kind: str = "DIRECT", source: dict[str, object] | None = None
) -> TBoxDraftBlockModel:
    now = datetime(2026, 8, 1, 1, 2, 3, tzinfo=UTC)
    return TBoxDraftBlockModel(
        id=UUID("019fbaae-8a76-76f3-9838-38927d59edf2"),
        workspace_id=UUID("00000000-0000-4000-8000-000000000100"),
        draft_id=UUID("019fbaae-8a76-76f3-9838-38927d59edf3"),
        kind=kind,
        title="통합 스키마",
        weight=50,
        ordinal=0,
        collapsed=False,
        source_reference=source,
        created_at=now,
        updated_at=now,
        version=1,
    )


def test_empty_direct_block_claims_one_proposal_source_mode_and_preserves_first_provenance() -> (
    None
):
    block = _draft_block()
    proposal_id = UUID("019fbaae-8a76-76f3-9838-38927d59edf4")
    source: dict[str, object] = {
        "contract_version": "KNOWLEDGE_STUDIO_DOCUMENT_SOURCE_PIN_V1",
        "manifest_id": "019fbaae-8a76-76f3-9838-38927d59edf5",
    }
    now = datetime(2026, 8, 1, 2, 3, 4, tzinfo=UTC)

    _claim_tbox_block_source_mode(
        block=block,
        source_reference=source,
        proposal_id=proposal_id,
        persisted_element_count=0,
        now=now,
    )

    assert block.kind == "DOCUMENT_SCHEMA"
    assert block.source_reference == {
        **source,
        "kind": "TBOX_PROPOSAL",
        "proposal_id": str(proposal_id),
    }
    assert block.version == 2
    first_reference = dict(block.source_reference)

    _claim_tbox_block_source_mode(
        block=block,
        source_reference={
            "contract_version": "KNOWLEDGE_STUDIO_DOCUMENT_SOURCE_V1",
            "manifest_id": "019fbaae-8a76-76f3-9838-38927d59edf6",
        },
        proposal_id=UUID("019fbaae-8a76-76f3-9838-38927d59edf7"),
        persisted_element_count=3,
        now=datetime(2026, 8, 1, 3, 4, 5, tzinfo=UTC),
    )

    assert block.source_reference == first_reference
    assert block.version == 2


def test_block_source_mode_rejects_mixed_provenance_and_requires_append_layer() -> None:
    now = datetime(2026, 8, 1, 2, 3, 4, tzinfo=UTC)
    with pytest.raises(ConflictError, match="new block"):
        _claim_tbox_block_source_mode(
            block=_draft_block(),
            source_reference={
                "contract_version": "KNOWLEDGE_STUDIO_CATALOG_SOURCE_PIN_V1",
            },
            proposal_id=UUID("019fbaae-8a76-76f3-9838-38927d59edf8"),
            persisted_element_count=1,
            now=now,
        )

    claimed = _draft_block(
        kind="CATALOG_METADATA",
        source={
            "contract_version": "KNOWLEDGE_STUDIO_CATALOG_SOURCE_PIN_V1",
            "kind": "TBOX_PROPOSAL",
            "proposal_id": "019fbaae-8a76-76f3-9838-38927d59edf9",
        },
    )
    with pytest.raises(ConflictError, match="different source mode"):
        _claim_tbox_block_source_mode(
            block=claimed,
            source_reference={
                "contract_version": "KNOWLEDGE_STUDIO_ASSISTANT_INPUT_V1",
            },
            proposal_id=UUID("019fbaae-8a76-76f3-9838-38927d59edfa"),
            persisted_element_count=2,
            now=now,
        )


@pytest.mark.asyncio
async def test_empty_domain_table_uses_only_deterministic_abac_scoped_fallbacks() -> None:
    session = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [])),
    )
    store = SqlKnowledgeStudioStore(cast(AsyncSession, session))
    workspace_id = UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b1")
    finance_id = default_knowledge_domain_id(workspace_id, "finance")

    values = await store.list_domains(
        workspace_id=workspace_id,
        allowed_domain_ids=frozenset({finance_id}),
        creator_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b2"),
        query=None,
        limit=100,
    )

    assert tuple((value.domain_id, value.display_name) for value in values) == (
        (finance_id, "Finance"),
    )
    assert values[0].source_version == DEFAULT_KNOWLEDGE_DOMAIN_SOURCE_VERSION
    statement = str(session.execute.await_args.args[0])
    assert "vocabulary_entries.created_by" in statement
    assert "iam.subjects" in statement


@pytest.mark.asyncio
async def test_alias_availability_uses_jsonb_containment_instead_of_string_like() -> None:
    session = SimpleNamespace(
        execute=AsyncMock(),
        scalar=AsyncMock(side_effect=(None, None)),
    )
    store = SqlKnowledgeStudioStore(cast(AsyncSession, session))

    await store._require_alias_available(
        workspace_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b1"),
        endpoint_alias="semiconductor_materials",
    )

    statement = session.scalar.await_args_list[1].args[0]
    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
    compiled = str(statement.compile(dialect=dialect))
    assert "CAST(knowledge.studio_drafts.endpoint_aliases AS JSONB) @>" in compiled
    assert " LIKE " not in compiled


@pytest.mark.asyncio
async def test_resumable_draft_lookup_is_scoped_to_workspace_author_alias_and_draft_state() -> None:
    scalar_result = SimpleNamespace(one_or_none=lambda: None)
    session = SimpleNamespace(scalars=AsyncMock(return_value=scalar_result))
    store = SqlKnowledgeStudioStore(cast(AsyncSession, session))

    result = await store.get_owned_live_draft_by_endpoint_alias(
        workspace_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b1"),
        author_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b2"),
        endpoint_alias="semiconductor_materials",
    )

    assert result is None
    statement = session.scalars.await_args.args[0]
    compiled = str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[no-untyped-call]
    assert "studio_drafts.workspace_id" in compiled
    assert "studio_drafts.author_id" in compiled
    assert "CAST(knowledge.studio_drafts.endpoint_aliases AS JSONB) @>" in compiled
    assert "studio_drafts.state" in compiled


def test_abox_mapping_is_a_normalized_child_aggregate_not_draft_json() -> None:
    draft = _table("knowledge.studio_drafts")
    elements = _table("knowledge.tbox_draft_elements")
    classes = _table("knowledge.tbox_classes")
    properties = _table("knowledge.tbox_properties")
    relationships = _table("knowledge.tbox_relationships")
    sources = _table("knowledge.source_references")
    bindings = _table("knowledge.abox_binding_drafts")
    rules = _table("knowledge.abox_mapping_rule_drafts")

    assert "mapping_document" not in draft.columns
    assert "abox" not in draft.columns
    assert {
        "stable_element_id",
        "kind",
        "version",
    } <= set(elements.c.keys())
    assert "parent_stable_class_id" in classes.c
    assert "owner_stable_class_id" in properties.c
    assert {"source_stable_class_id", "target_stable_class_id"} <= set(relationships.c.keys())
    assert {
        "catalog_asset_id",
        "source_version",
        "projection_source_version",
        "classification",
        "selection_document",
        "selection_hash",
        "created_by",
    } <= set(sources.c.keys())
    assert {
        "draft_id",
        "target_stable_element_id",
        "source_reference_id",
        "readiness",
        "tbox_version",
        "version",
    } <= set(bindings.c.keys())
    assert {
        "binding_id",
        "method",
        "source_field_path",
        "target_stable_element_id",
        "transform_id",
        "transform_version",
    } <= set(rules.c.keys())
    assert {"external_urn", "provider_query", "credential"}.isdisjoint(sources.c.keys())

    source_checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in sources.constraints
        if isinstance(constraint, CheckConstraint)
    }
    rule_checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in rules.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "CATALOG_DATASET" in source_checks["ck_source_references_kind_vocabulary"]
    assert "IDENTITY" in rule_checks["ck_abox_mapping_rule_drafts_identity_transform_only"]
    assert "EDGE_LINK" in rule_checks["ck_abox_mapping_rule_drafts_method_vocabulary"]
    for table in (elements, classes, properties, relationships, sources, bindings, rules):
        for constraint in table.constraints:
            if isinstance(constraint, ForeignKeyConstraint):
                assert constraint.ondelete == "RESTRICT"


def test_graph_and_ontology_provenance_is_additive_and_legacy_nullable() -> None:
    graph = _table("knowledge.graphs")
    ontology = _table("knowledge.ontology_versions")
    for column in (
        "domain_ref_id",
        "domain_ref_kind",
        "domain_source_version",
        "created_by",
        "updated_by",
    ):
        assert graph.c[column].nullable is True
    for column in ("schema_contract_version", "base_ontology_version_id", "created_by"):
        assert ontology.c[column].nullable is True


def test_catalog_pin_v2_migration_is_function_only_asyncpg_safe_and_canonical() -> None:
    migration_source = CATALOG_PIN_MIGRATION.read_text(encoding="utf-8")
    migration = _catalog_pin_migration()
    statements = migration.split_postgresql_statements(
        migration.TBOX_PROPOSAL_JOB_CATALOG_PIN_V2_FUNCTION_SQL
    )

    assert 'revision: str = "0086"' in migration_source
    assert 'down_revision: str | Sequence[str] | None = "0085"' in migration_source
    assert len(statements) == 11
    assert all(statement.count("CREATE OR REPLACE FUNCTION") == 1 for statement in statements)
    assert "CREATE TABLE" not in migration_source
    assert "ALTER TABLE" not in migration_source
    assert "knowledge.tbox_proposal_jobs" in migration._DOWNGRADE_REFUSAL_SQL
    assert "contract_version" in migration._DOWNGRADE_REFUSAL_SQL

    generator = GENERATOR.read_text(encoding="utf-8")
    initial = INITIAL_MIGRATION.read_text(encoding="utf-8")
    assert "TBOX_PROPOSAL_JOB_CATALOG_PIN_V2_FUNCTION_SQL" in generator
    assert "KNOWLEDGE_STUDIO_CATALOG_SOURCE_PIN_V2" in initial
    assert "metadata_fingerprint" in initial


def test_proposal_idempotency_fix_is_function_only_reversible_and_canonical() -> None:
    migration_source = PROPOSAL_IDEMPOTENCY_FIX_MIGRATION.read_text(encoding="utf-8")
    migration = _proposal_idempotency_fix_migration()
    fixed = migration.fixed_command_function_sql()
    legacy = migration.legacy_command_function_sql()

    assert 'revision: str = "0087"' in migration_source
    assert 'down_revision: str | Sequence[str] | None = "0086"' in migration_source
    assert fixed.count("CREATE OR REPLACE FUNCTION") == 1
    assert "idempotency_key_hash text :=" in fixed
    assert "FROM integration.idempotency_keys AS stored_replay" in fixed
    assert "stored_replay.key_hash = idempotency_key_hash" in fixed
    assert "key_hash text := encode" in legacy
    assert "integration.idempotency_keys.key_hash = key_hash" in legacy
    for source in (fixed, legacy):
        assert "CREATE TABLE" not in source
        assert "ALTER TABLE" not in source

    generator = GENERATOR.read_text(encoding="utf-8")
    initial = INITIAL_MIGRATION.read_text(encoding="utf-8")
    assert "0087_fix_knowledge_studio_proposal_job_idempotency.py" in generator
    assert "idempotency_key_hash text :=" in initial
    assert "FROM integration.idempotency_keys AS stored_replay" in initial


def test_proposal_contract_restore_is_pinned_reversible_and_canonical() -> None:
    migration_source = PROPOSAL_CONTRACT_RESTORE_MIGRATION.read_text(encoding="utf-8")
    migration = _proposal_contract_restore_migration()
    request = migration._pinned(
        migration.TBOX_PROPOSAL_JOB_PIN_V2_IDEMPOTENT_REQUEST_FUNCTION_SQL,
        migration._REQUEST_FUNCTION_SHA256,
        label="composed Proposal request",
    )
    safety = migration._pinned(
        migration.TBOX_PROPOSAL_CONTENT_SAFETY_STRUCTURAL_FUNCTION_SQL,
        migration._STRUCTURAL_SAFETY_FUNCTION_SHA256,
        label="structural content-safety",
    )

    assert 'revision: str = "0088"' in migration_source
    assert 'down_revision: str | Sequence[str] | None = "0087"' in migration_source
    assert request.count("CREATE OR REPLACE FUNCTION") == 1
    assert "KNOWLEDGE_STUDIO_CATALOG_SOURCE_PIN_V2" in request
    assert "idempotency_key_hash text :=" in request
    assert "stored_replay.key_hash = idempotency_key_hash" in request
    assert safety.count("CREATE OR REPLACE FUNCTION") == 1
    assert "WITH RECURSIVE source_nodes" in safety
    assert "jsonb_object_keys" in safety
    assert "content_sha256" not in safety
    assert "CREATE TABLE" not in migration_source
    assert "ALTER TABLE" not in migration_source
    assert "DELETE FROM" not in migration_source
    assert "UPDATE knowledge.tbox_proposals" not in migration_source
    assert "0088 downgrade requires reconciliation" in migration._DOWNGRADE_PREFLIGHT_SQL

    generator = GENERATOR.read_text(encoding="utf-8")
    initial = INITIAL_MIGRATION.read_text(encoding="utf-8")
    assert "0088_restore_knowledge_studio_proposal_contracts.py" in generator
    assert "WITH RECURSIVE source_nodes" in initial
    assert "KNOWLEDGE_STUDIO_CATALOG_SOURCE_PIN_V2" in initial
    assert initial.find("WITH RECURSIVE source_nodes") > initial.find(
        "stored_replay.key_hash = idempotency_key_hash"
    )


def test_proposal_transition_idempotency_fix_is_pinned_and_reversible() -> None:
    source = PROPOSAL_TRANSITION_IDEMPOTENCY_FIX_MIGRATION.read_text(encoding="utf-8")
    migration = _proposal_transition_idempotency_fix_migration()
    current = migration.current_function_sqls()
    legacy = migration.legacy_function_sqls()

    assert 'revision: str = "0093"' in source
    assert 'down_revision: str | Sequence[str] | None = "0092"' in source
    assert len(current) == len(legacy) == 4
    assert all(statement.count("CREATE OR REPLACE FUNCTION") == 1 for statement in current)
    assert all("idempotency_key_hash text :=" in statement for statement in current)
    assert all(
        "FROM integration.idempotency_keys AS stored_replay" in statement for statement in current
    )
    assert all("stored_replay.workspace_id = p_workspace_id" in statement for statement in current)
    assert all("stored_replay.operation = operation_name" in statement for statement in current)
    assert all(
        "stored_replay.key_hash = idempotency_key_hash" in statement for statement in current
    )
    assert all("key_hash text := encode" in statement for statement in legacy)
    assert all(
        "integration.idempotency_keys.key_hash = key_hash" in statement for statement in legacy
    )
    for statement in (*current, *legacy):
        assert "CREATE TABLE" not in statement
        assert "ALTER TABLE" not in statement
        assert "GRANT " not in statement

    generator = GENERATOR.read_text(encoding="utf-8")
    initial = INITIAL_MIGRATION.read_text(encoding="utf-8")
    assert "0093_fix_knowledge_studio_proposal_job_idempotency.py" in generator
    assert initial.count("FROM integration.idempotency_keys AS stored_replay") >= 5


def test_proposal_authorization_scope_is_pinned_reversible_and_canonical() -> None:
    source = PROPOSAL_AUTHORIZATION_SCOPE_MIGRATION.read_text(encoding="utf-8")
    migration = _proposal_authorization_scope_migration()
    current = migration.current_authorization_function_sql()
    legacy = migration.legacy_authorization_function_sql()

    assert 'revision: str = "0094"' in source
    assert 'down_revision: str | Sequence[str] | None = "0093"' in source
    assert current.count("CREATE OR REPLACE FUNCTION") == 1
    assert legacy.count("CREATE OR REPLACE FUNCTION") == 1
    assert "iam.canonical_admin_bindings AS admin_binding" in current
    assert "iam.profile_role_assignments AS profile_assignment" in current
    assert "platform.system_assignees AS assignee" in current
    assert "platform.data_systems AS data_system" in current
    assert "assignee.active IS TRUE" in current
    assert "data_system.active IS TRUE" in current
    assert "iam.canonical_admin_bindings AS admin_binding" not in legacy
    assert "membership.attributes -> 'allowed_system_ids'" in legacy
    for statement in (current, legacy):
        assert "CREATE TABLE" not in statement
        assert "ALTER TABLE" not in statement
        assert "GRANT " not in statement

    generator = GENERATOR.read_text(encoding="utf-8")
    initial = INITIAL_MIGRATION.read_text(encoding="utf-8")
    assert "0094_align_knowledge_proposal_authorization_scope.py" in generator
    assert initial.count("iam.canonical_admin_bindings AS admin_binding") == 2
    assert initial.count("platform.system_assignees AS assignee") >= 1
    assert initial.rfind("iam.canonical_admin_bindings AS admin_binding") > initial.rfind(
        "CREATE OR REPLACE FUNCTION knowledge.fail_tbox_proposal_job_v1("
    )


def test_revision_0084_pins_pre_role_authorization_until_revision_0094(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proposal_job = _proposal_job_migration()
    authorization_scope = _proposal_authorization_scope_migration()
    revision_0084_sql = proposal_job._revision_0084_function_sql()
    revision_0094_sql = authorization_scope.current_authorization_function_sql()

    assert proposal_job.revision == "0084"
    assert proposal_job.down_revision == "0083"
    assert authorization_scope.revision == "0094"
    assert authorization_scope.down_revision == "0093"
    assert "iam.canonical_admin_bindings" not in revision_0084_sql
    assert "iam.profile_role_assignments" not in revision_0084_sql
    assert "membership.attributes -> 'allowed_system_ids'" in revision_0084_sql
    assert "iam.canonical_admin_bindings" in revision_0094_sql
    assert "iam.profile_role_assignments" in revision_0094_sql

    scripts: list[str] = []
    monkeypatch.setattr(proposal_job, "_execute_sql_script", scripts.append)
    monkeypatch.setattr(proposal_job, "op", SimpleNamespace(execute=lambda _sql: None))

    proposal_job.upgrade()

    assert scripts[2] == revision_0084_sql


def test_proposal_control_guard_is_pinned_reversible_and_canonical() -> None:
    source = PROPOSAL_CONTROL_GUARD_MIGRATION.read_text(encoding="utf-8")
    migration = _proposal_control_guard_migration()
    current = migration.current_function_sqls()
    legacy = migration.legacy_function_sqls()

    assert 'revision: str = "0095"' in source
    assert 'down_revision: str | Sequence[str] | None = "0094"' in source
    assert len(current) == len(legacy) == 2
    assert all(statement.count("CREATE OR REPLACE FUNCTION") == 1 for statement in current)
    assert all(statement.count("[[:cntrl:]]") == 1 for statement in current)
    assert all(statement.count(r"[\\x00-\\x1F\\x7F]") == 1 for statement in legacy)
    assert current[0].startswith(
        "CREATE OR REPLACE FUNCTION knowledge.complete_tbox_proposal_job_v1("
    )
    assert current[1].startswith(
        "CREATE OR REPLACE FUNCTION knowledge.enforce_tbox_proposal_content_safety_v1()"
    )
    for current_statement, legacy_statement in zip(current, legacy, strict=True):
        assert (
            current_statement.replace(
                "~ '[[:cntrl:]]'",
                r"~ '[\\x00-\\x1F\\x7F]'",
                1,
            )
            == legacy_statement
        )
        assert "CREATE TABLE" not in current_statement
        assert "ALTER TABLE" not in current_statement
        assert "GRANT " not in current_statement

    generator = GENERATOR.read_text(encoding="utf-8")
    initial = INITIAL_MIGRATION.read_text(encoding="utf-8")
    assert "0095_fix_tbox_proposal_control_character_guard.py" in generator
    assert initial.rfind("[[:cntrl:]]") > initial.rfind(
        "iam.canonical_admin_bindings AS admin_binding"
    )


def test_publication_migration_replaces_owner_only_rls_with_maker_checker_policy() -> None:
    foundation = MIGRATION.read_text(encoding="utf-8")
    migration = PUBLICATION_MIGRATION.read_text(encoding="utf-8")
    generator = GENERATOR.read_text(encoding="utf-8")
    assert "studio_draft_owner_access" in foundation
    for source in (migration, generator):
        assert "studio_draft_actor_select" in source
        assert "studio_draft_governed_update" in source
        assert "kg.review" in source
        assert "kg.publish" in source
        assert "reviewed_by" in source
        assert "published_by" in source
        assert "membership.subject_id <>" in source
        assert "HARDWARE_WEBAUTHN" not in source
        assert "app.subject_id" in source
        assert "knowledge.studio_drafts" in source
        assert "GRANT UPDATE (" in source
        assert "submitted_preflight_check_id" in source
        assert "published_studio_release_id" in source
    assert "GRANT DELETE ON knowledge.studio_drafts" not in migration
    assert "GRANT DELETE ON knowledge.studio_drafts" not in generator
    assert "downgrade would destroy history" in migration


def test_abox_rls_allows_review_reads_but_keeps_draft_writes_owner_only() -> None:
    migration = ABOX_MIGRATION.read_text(encoding="utf-8")
    publication = PUBLICATION_MIGRATION.read_text(encoding="utf-8")
    initial = INITIAL_MIGRATION.read_text(encoding="utf-8")
    abox_table_names = (
        "tbox_draft_elements",
        "source_references",
        "abox_binding_drafts",
        "abox_mapping_rule_drafts",
    )
    normalized_table_names = (
        "tbox_classes",
        "tbox_properties",
        "tbox_relationships",
    )
    hierarchy = HIERARCHY_MIGRATION.read_text(encoding="utf-8")
    assert 'f"ALTER TABLE knowledge.{table} FORCE ROW LEVEL SECURITY"' in migration
    for table in abox_table_names:
        assert f'"{table}"' in migration
        assert f"ALTER TABLE knowledge.{table} FORCE ROW LEVEL SECURITY" in initial
    for table in normalized_table_names:
        assert f'"{table}"' in hierarchy
        assert f"ALTER TABLE knowledge.{table} FORCE ROW LEVEL SECURITY" in initial
    assert "source_reference_owner_access" in migration
    assert "studio_draft_owner_access" in migration
    for source in (publication, initial):
        assert "source_reference_actor_select" in source
        assert "source_reference_owner_insert" in source
        assert "studio_draft_actor_select" in source
        assert "studio_draft_owner_insert" in source
        assert "studio_draft_owner_update" in source
        assert "studio_draft_owner_delete" in source
        assert "app.subject_id" in source
        assert "GRANT DELETE ON knowledge.abox_binding_drafts" not in source
        assert "GRANT UPDATE ON knowledge.tbox_draft_elements" not in source
        assert "GRANT UPDATE ON knowledge.tbox_classes" not in source
    for source in (migration, initial):
        assert "GRANT DELETE ON knowledge.abox_mapping_rule_drafts" in source or (
            "GRANT SELECT, INSERT, DELETE" in source
            and "ON knowledge.abox_mapping_rule_drafts" in source
        )
    assert (
        initial.count("fk_tbox_classes_workspace_id_draft_id_parent_stable_class_id_tbox_classes")
        == 1
    )
    assert (
        initial.count("fk_tbox_properties_workspace_id_draft_id_owner_stable_class_id_tbox_classes")
        == 1
    )
    for field in ("source_stable_class_id", "target_stable_class_id"):
        assert (
            initial.count(f"fk_tbox_relationships_workspace_id_draft_id_{field}_tbox_classes") == 1
        )
    assert "downgrade would destroy state" in migration


def test_publication_models_are_immutable_schema_and_mapping_contracts() -> None:
    graph = _table("knowledge.graphs")
    drafts = _table("knowledge.studio_drafts")
    receipts = _table("knowledge.studio_preflight_checks")
    releases = _table("knowledge.studio_releases")
    elements = _table("knowledge.ontology_elements")
    bindings = _table("knowledge.abox_binding_versions")
    rules = _table("knowledge.abox_mapping_rule_versions")

    assert "active_studio_release_id" in graph.columns
    assert {
        "draft_version",
        "contract_hash",
        "validation_contract_version",
        "evidence_document",
        "evidence_hash",
        "checked_by",
    } <= set(receipts.c.keys())
    assert {
        "source_draft_id",
        "source_draft_version",
        "ontology_version_id",
        "preflight_check_id",
        "contract_hash",
        "tbox_hash",
        "abox_hash",
        "author_id",
        "reviewed_by",
        "published_by",
    } <= set(releases.c.keys())
    assert {
        "stable_element_id",
        "element_document",
        "element_hash",
    } <= set(elements.c.keys())
    assert {
        "studio_release_id",
        "ontology_version_id",
        "target_ontology_element_id",
        "source_reference_id",
        "mapping_hash",
    } <= set(bindings.c.keys())
    assert {
        "studio_release_id",
        "binding_version_id",
        "ontology_version_id",
        "target_ontology_element_id",
    } <= set(rules.c.keys())
    assert "submitted_preflight_check_id" in drafts.columns

    exact_receipt_reference = next(
        constraint
        for constraint in releases.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and tuple(constraint.column_keys)
        == (
            "workspace_id",
            "source_draft_id",
            "source_draft_version",
            "contract_hash",
            "reviewed_by",
            "preflight_check_id",
        )
    )
    assert exact_receipt_reference.ondelete == "RESTRICT"
    assert [element.target_fullname for element in exact_receipt_reference.elements] == [
        "knowledge.studio_preflight_checks.workspace_id",
        "knowledge.studio_preflight_checks.draft_id",
        "knowledge.studio_preflight_checks.draft_version",
        "knowledge.studio_preflight_checks.contract_hash",
        "knowledge.studio_preflight_checks.checked_by",
        "knowledge.studio_preflight_checks.id",
    ]

    active_release = next(
        index
        for index in releases.indexes
        if isinstance(index, Index) and index.name == "uq_studio_releases_one_active_per_graph"
    )
    assert active_release.unique is True
    assert "ACTIVE" in str(active_release.dialect_options["postgresql"]["where"])

    release_checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in releases.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "reviewed_by <> author_id" in release_checks["ck_studio_releases_independent_review"]
    assert "KNOWLEDGE_STUDIO_RELEASE_V1" in release_checks["ck_studio_releases_contract_version"]

    publication = PUBLICATION_MIGRATION.read_text(encoding="utf-8")
    for table in (
        "studio_preflight_checks",
        "studio_releases",
        "ontology_elements",
        "abox_binding_versions",
        "abox_mapping_rule_versions",
    ):
        assert f'"{table}"' in publication
        assert "ALTER TABLE knowledge.{table} FORCE ROW LEVEL SECURITY" in publication
    assert "GRANT DELETE ON knowledge.studio_releases" not in publication
    assert "studio_release_publisher_insert" in publication
    assert "studio_release_publisher_archive" in publication
    assert "source_draft_version" in publication
    assert "Legacy Studio PUBLISHED rows lack independent review evidence" in publication


def test_idempotency_snapshot_round_trips_the_exact_draft_response() -> None:
    observed_at = datetime(2026, 7, 28, 1, 2, 3, tzinfo=UTC)
    record = KnowledgeStudioDraftRecord(
        draft_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b0"),
        workspace_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b1"),
        author_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b2"),
        kind="CREATE",
        state="DRAFT",
        current_step="BASIC",
        name="반도체 소재 그래프",
        endpoint_alias="semiconductor_materials",
        endpoint_aliases=("semiconductor_materials", "materials_kg"),
        domain_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b3"),
        domain_source_version="domain-v3",
        classification=Classification.INTERNAL,
        base_graph_id=None,
        base_ontology_version_id=None,
        base_release_id=None,
        last_autosaved_at=observed_at,
        version=7,
        created_at=observed_at,
        updated_at=observed_at,
    )

    assert studio_draft_record_from_result(studio_draft_result(record)) == record

    corrupted = studio_draft_result(record)
    corrupted["state"] = "PUBLISHED_BY_LLM"
    with pytest.raises(ConflictError):
        studio_draft_record_from_result(corrupted)

    replay = IdempotencyRecord(
        request_hash="request-hash",
        result=studio_draft_result(record),
    )
    assert (
        resolve_studio_idempotent_replay(
            replay,
            workspace_id=record.workspace_id,
            author_id=record.author_id,
            request_hash="request-hash",
        )
        == record
    )
    with pytest.raises(ConflictError, match="different request"):
        resolve_studio_idempotent_replay(
            replay,
            workspace_id=record.workspace_id,
            author_id=record.author_id,
            request_hash="changed-hash",
        )
    with pytest.raises(ConflictError, match="another author"):
        resolve_studio_idempotent_replay(
            replay,
            workspace_id=record.workspace_id,
            author_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b4"),
            request_hash="request-hash",
        )


def test_abox_idempotency_snapshot_round_trips_exact_draft_and_binding() -> None:
    observed_at = datetime(2026, 7, 28, 1, 2, 3, tzinfo=UTC)
    draft_record = KnowledgeStudioDraftRecord(
        draft_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b0"),
        workspace_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b1"),
        author_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b2"),
        kind="CREATE",
        state="DRAFT",
        current_step="ABOX",
        name="반도체 소재 그래프",
        endpoint_alias="semiconductor_materials",
        endpoint_aliases=("semiconductor_materials", "materials_kg"),
        domain_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3b3"),
        domain_source_version="domain-v3",
        classification=Classification.INTERNAL,
        base_graph_id=None,
        base_ontology_version_id=None,
        base_release_id=None,
        last_autosaved_at=observed_at,
        version=8,
        created_at=observed_at,
        updated_at=observed_at,
    )
    binding = KnowledgeStudioBindingRecord(
        binding_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3c0"),
        target_stable_element_id="class.employee",
        source_reference_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3c1"),
        source_asset_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3c2"),
        source_name="hr_employee",
        source_version="source-v1",
        projection_source_version="projection-v3",
        source_classification=Classification.INTERNAL,
        readiness="DRAFT",
        tbox_version=3,
        version=2,
        rules=(
            KnowledgeStudioMappingRuleRecord(
                rule_id=UUID("019fa57b-52de-74c0-9f5e-06ae7b1bf3c3"),
                ordinal=0,
                method="SUBJECT_ID",
                source_field_path="emp_id",
                target_stable_element_id="class.employee",
                transform_id="IDENTITY",
                transform_version="1",
                source_unit=None,
                canonical_unit=None,
            ),
        ),
        created_at=observed_at,
        updated_at=observed_at,
    )
    replay = IdempotencyRecord(
        request_hash="request-hash",
        result=abox_binding_result(draft_record, binding),
    )

    assert resolve_abox_idempotent_replay(
        replay,
        workspace_id=draft_record.workspace_id,
        author_id=draft_record.author_id,
        request_hash="request-hash",
    ) == (draft_record, binding)

    corrupted = abox_binding_result(draft_record, binding)
    corrupted_binding = corrupted["binding"]
    assert isinstance(corrupted_binding, dict)
    corrupted_binding["readiness"] = "READY_BY_LLM"
    with pytest.raises(ConflictError, match="invalid"):
        resolve_abox_idempotent_replay(
            IdempotencyRecord(request_hash="request-hash", result=corrupted),
            workspace_id=draft_record.workspace_id,
            author_id=draft_record.author_id,
            request_hash="request-hash",
        )


@pytest.mark.asyncio
@patch.object(SqlKnowledgeStudioStore, "_require_alias_available")
async def test_materialization_target_validates_managed_binding(
    mock_require_alias: AsyncMock,
) -> None:
    from unittest.mock import AsyncMock, Mock
    from uuid import uuid4

    from datariver.infrastructure.db.knowledge_studio import SqlKnowledgeStudioStore
    from datariver.infrastructure.db.models.knowledge_studio import KnowledgeStudioDraftModel

    session = AsyncMock()
    session.add = Mock()
    store = SqlKnowledgeStudioStore(session)

    workspace_id = uuid4()
    draft = KnowledgeStudioDraftModel(
        id=uuid4(),
        workspace_id=workspace_id,
        kind="CREATE",
        name="test",
        endpoint_alias="test",
        endpoint_aliases=["test"],
        classification="normal",
        domain_ref_id=uuid4(),
        domain_source_version="1",
        author_id=uuid4(),
        managed_intent="metadata-lineage",
        managed_graph_type="CATALOG_MIRROR",
        accepted_proposal_id="contract.semantic.metadata-lineage",
        accepted_proposal_hash="9b6a5e0e07624df4520d333b5d673fbe77f7ab84b0f352bbe3c647b262523e96",
        source_contract_hash="8d8cba3f1b46f997e234207f956238bf4a87e752d7566c20bb41a1e08d2a5feb",
        mapping_contract_hash="f923778369eda84d0b2942d7fd1b1b837f64125fc3a2f5dd4dc72bcdc9d99bf3",
    )

    # Valid binding
    graph, _release = await store._materialization_target(
        workspace_id=workspace_id, draft=draft, actor_id=uuid4()
    )
    assert graph.graph_type == "CATALOG_MIRROR"

    # positive data-glossary -> CURATED_KNOWLEDGE
    draft.managed_intent = "data-glossary"
    draft.managed_graph_type = "CURATED_KNOWLEDGE"
    draft.accepted_proposal_id = "contract.semantic.data-glossary"
    draft.accepted_proposal_hash = (
        "670ac1d49ab091debe23bc706cc479576af226ea55d73fa5ffd2c1a4993836d1"
    )
    draft.source_contract_hash = "12cba3de9e71c2453d94c2f625839593d627ea60f6143097a49a9d3782a089d8"
    draft.mapping_contract_hash = "ed3160311a3058f9e61bc8478b07175d96b6fe3c035b55fb4fe94455a6098e7f"
    graph, _release = await store._materialization_target(
        workspace_id=workspace_id, draft=draft, actor_id=uuid4()
    )
    assert graph.graph_type == "CURATED_KNOWLEDGE"

    # Unknown intent
    draft.managed_intent = "unknown"
    with pytest.raises(ConflictError, match="unknown managed intent"):
        await store._materialization_target(
            workspace_id=workspace_id, draft=draft, actor_id=uuid4()
        )

    # Mismatched graph type
    draft.managed_intent = "metadata-lineage"
    draft.managed_graph_type = "CURATED_KNOWLEDGE"
    with pytest.raises(ConflictError, match="Inconsistent managed binding"):
        await store._materialization_target(
            workspace_id=workspace_id, draft=draft, actor_id=uuid4()
        )

    # Missing proposal hash rejection
    draft.managed_graph_type = "CATALOG_MIRROR"
    draft.accepted_proposal_hash = None
    with pytest.raises(ConflictError, match="Inconsistent managed binding"):
        await store._materialization_target(
            workspace_id=workspace_id, draft=draft, actor_id=uuid4()
        )

    # Mismatched proposal hash rejection
    draft.accepted_proposal_hash = "wrong"
    with pytest.raises(ConflictError, match="Inconsistent managed binding"):
        await store._materialization_target(
            workspace_id=workspace_id, draft=draft, actor_id=uuid4()
        )

    # Generic CREATE
    draft.managed_intent = None
    draft.managed_graph_type = None
    draft.accepted_proposal_id = None
    draft.accepted_proposal_hash = None
    draft.source_contract_hash = None
    draft.mapping_contract_hash = None
    graph, _release = await store._materialization_target(
        workspace_id=workspace_id, draft=draft, actor_id=uuid4()
    )
    assert graph.graph_type == "CURATED_KNOWLEDGE"


@pytest.mark.asyncio
async def test_load_contract_and_verify_managed_binding() -> None:
    from unittest.mock import AsyncMock, Mock
    from uuid import uuid4

    from datariver.infrastructure.db.knowledge_studio import SqlKnowledgeStudioStore
    from datariver.infrastructure.db.models.knowledge_studio import (
        KnowledgeStudioDraftModel,
        KnowledgeStudioReleaseModel,
    )

    session = AsyncMock()

    # Provide empty bindings and elements
    result_mock = Mock()
    result_mock.all.return_value = []

    session.execute.return_value = result_mock
    session.scalars.return_value = result_mock

    store = SqlKnowledgeStudioStore(session)

    workspace_id = uuid4()
    draft = KnowledgeStudioDraftModel(
        id=uuid4(),
        workspace_id=workspace_id,
        kind="CREATE",
        name="test",
        endpoint_alias="test",
        endpoint_aliases=["test"],
        classification="normal",
        domain_ref_id=uuid4(),
        domain_source_version="1",
        author_id=uuid4(),
        managed_intent="metadata-lineage",
        managed_graph_type="CATALOG_MIRROR",
        accepted_proposal_id="contract.semantic.metadata-lineage",
        accepted_proposal_hash="9b6a5e0e07624df4520d333b5d673fbe77f7ab84b0f352bbe3c647b262523e96",
        source_contract_hash="8d8cba3f1b46f997e234207f956238bf4a87e752d7566c20bb41a1e08d2a5feb",
        mapping_contract_hash="f923778369eda84d0b2942d7fd1b1b837f64125fc3a2f5dd4dc72bcdc9d99bf3",
    )

    contract = await store._load_contract(workspace_id=workspace_id, draft=draft, lock=False)
    from typing import Any, cast

    doc = cast(dict[str, Any], contract.contract_document)
    assert "managed_publication" in doc
    assert doc["managed_publication"]["managed_intent"] == "metadata-lineage"

    release = KnowledgeStudioReleaseModel(
        id=uuid4(),
        workspace_id=workspace_id,
        tbox_hash=contract.tbox_hash,
        abox_hash=contract.abox_hash,
        contract_hash=contract.contract_hash,
        ontology_version_id=uuid4(),
        managed_intent="metadata-lineage",
        managed_graph_type="CATALOG_MIRROR",
        accepted_proposal_id="contract.semantic.metadata-lineage",
        accepted_proposal_hash="9b6a5e0e07624df4520d333b5d673fbe77f7ab84b0f352bbe3c647b262523e96",
        source_contract_hash="8d8cba3f1b46f997e234207f956238bf4a87e752d7566c20bb41a1e08d2a5feb",
        mapping_contract_hash="f923778369eda84d0b2942d7fd1b1b837f64125fc3a2f5dd4dc72bcdc9d99bf3",
    )

    # Exact read-back passes
    await store._verify_materialized_contract(
        workspace_id=workspace_id, studio_release=release, contract=contract
    )

    # Tampering fails: managed_graph_type
    original_graph_type = release.managed_graph_type
    release.managed_graph_type = "TAMPERED"
    with pytest.raises(ConflictError, match="manifest read-back verification failed"):
        await store._verify_materialized_contract(
            workspace_id=workspace_id, studio_release=release, contract=contract
        )
    release.managed_graph_type = original_graph_type

    # Tampering fails: accepted_proposal_hash
    release.accepted_proposal_hash = "TAMPERED"
    with pytest.raises(ConflictError, match="manifest read-back verification failed"):
        await store._verify_materialized_contract(
            workspace_id=workspace_id, studio_release=release, contract=contract
        )


def test_tbox_element_records_lock_invariant() -> None:
    # Ensure _load_tbox_element_records only locks the parent draft_elements
    # and explicitly omits locking the detail tables (classes/properties/relationships).
    # This ensures we don't need Postgres UPDATE privileges for FOR SHARE on detail tables.
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    ks_path = root / "backend/src/datariver/infrastructure/db/knowledge_studio.py"
    source = ks_path.read_text()

    tree = ast.parse(source)

    found_tbox_fn = False
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_load_tbox_element_records":
            found_tbox_fn = True
            # Find the elements_statement lock
            found_elements_lock = False
            for child in ast.walk(node):
                if isinstance(child, ast.Assign):
                    for target in child.targets:
                        if isinstance(target, ast.Name) and target.id == "elements_statement":
                            if (
                                isinstance(child.value, ast.Call)
                                and getattr(child.value.func, "attr", "") == "with_for_update"
                            ):
                                found_elements_lock = True

            assert found_elements_lock, "Must lock tbox_draft_elements"

            # Now verify the nested load_details function does not contain with_for_update
            found_load_details = False
            for child in ast.walk(node):
                if isinstance(child, ast.AsyncFunctionDef) and child.name == "load_details":
                    found_load_details = True
                    for sub_child in ast.walk(child):
                        if (
                            isinstance(sub_child, ast.Call)
                            and getattr(sub_child.func, "attr", "") == "with_for_update"
                        ):
                            raise AssertionError(
                                "load_details must not use with_for_update to avoid "
                                "FOR SHARE on detail tables"
                            )

            assert found_load_details, "Could not find load_details inner function"
            break
    assert found_tbox_fn, "Could not find _load_tbox_element_records"

    found_contract_fn = False
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_load_contract":
            found_contract_fn = True
            found_bindings_lock = False
            found_rules_lock = False

            for child in ast.walk(node):
                if isinstance(child, ast.Assign):
                    for target in child.targets:
                        if isinstance(target, ast.Name):
                            if target.id == "bindings_statement":
                                if (
                                    isinstance(child.value, ast.Call)
                                    and getattr(child.value.func, "attr", "") == "with_for_update"
                                ):
                                    found_bindings_lock = True
                                    has_read_true = any(
                                        kw.arg == "read"
                                        and getattr(kw.value, "value", None) is True
                                        for kw in child.value.keywords
                                    )
                                    assert has_read_true, "with_for_update must specify read=True"

                                    has_of_kwarg = any(
                                        kw.arg == "of"
                                        and isinstance(kw.value, ast.Name)
                                        and kw.value.id == "ABoxBindingDraftModel"
                                        for kw in child.value.keywords
                                    )
                                    assert has_of_kwarg, (
                                        "bindings_statement.with_for_update must specify "
                                        "'of=ABoxBindingDraftModel'"
                                    )
                            if target.id == "rules_statement":
                                if (
                                    isinstance(child.value, ast.Call)
                                    and getattr(child.value.func, "attr", "") == "with_for_update"
                                ):
                                    found_rules_lock = True

            assert found_bindings_lock, "Must qualify lock for bindings_statement"
            assert not found_rules_lock, (
                "Must omit lock for rules_statement to avoid FOR SHARE on detail tables"
            )
            break
    assert found_contract_fn, "Could not find _load_contract"
