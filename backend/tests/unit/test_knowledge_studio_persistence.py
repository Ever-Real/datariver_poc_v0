from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
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
from datariver.domain.common import ConflictError
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
    abox_binding_result,
    resolve_abox_idempotent_replay,
    resolve_studio_idempotent_replay,
    studio_draft_record_from_result,
    studio_draft_result,
)
from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "backend/alembic/versions/0059_knowledge_studio_foundation.py"
ABOX_MIGRATION = ROOT / "backend/alembic/versions/0060_knowledge_studio_abox_bindings.py"
PUBLICATION_MIGRATION = (
    ROOT / "backend/alembic/versions/0061_knowledge_studio_governed_publication.py"
)
QA_MIGRATION = ROOT / "backend/alembic/versions/0062_knowledge_qa_domain_archive.py"
BUILDER_MIGRATION = ROOT / "backend/alembic/versions/0063_ontology_builder_and_ingestion_jobs.py"
HIERARCHY_MIGRATION = ROOT / "backend/alembic/versions/0064_normalize_tbox_hierarchy.py"
SESSION_MIGRATION = ROOT / "backend/alembic/versions/0066_knowledge_studio_session_domains.py"
INITIAL_MIGRATION = ROOT / "backend/alembic/versions/0001_initial_schema.py"
GENERATOR = ROOT / "scripts/generate_initial_migration.py"


def _table(name: str) -> Table:
    return Base.metadata.tables[name]


def test_studio_draft_model_is_separate_persistent_author_state() -> None:
    draft = _table("knowledge.studio_drafts")
    assert REQUIRED_DATABASE_REVISION == "0069"
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
        "request_document",
        "vector_policy_document",
        "lease_epoch",
        "lease_token_hash",
    } <= set(jobs.c.keys())

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
    vocabulary = _table("catalog.vocabulary_entries")
    assert {"created_by", "version"} <= set(vocabulary.c.keys())
    assert '"preflight_receipt_id": str(preflight.id)' in (
        ROOT / "backend/src/datariver/infrastructure/db/knowledge_studio.py"
    ).read_text(encoding="utf-8")


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
