from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, Table

from datariver.application.dto import (
    IdempotencyRecord,
    KnowledgeStudioBindingRecord,
    KnowledgeStudioDraftRecord,
    KnowledgeStudioMappingRuleRecord,
)
from datariver.domain.authz import Classification
from datariver.domain.common import ConflictError
from datariver.infrastructure.db import models  # noqa: F401
from datariver.infrastructure.db.base import Base
from datariver.infrastructure.db.knowledge_studio import (
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
INITIAL_MIGRATION = ROOT / "backend/alembic/versions/0001_initial_schema.py"
GENERATOR = ROOT / "scripts/generate_initial_migration.py"


def _table(name: str) -> Table:
    return Base.metadata.tables[name]


def test_studio_draft_model_is_separate_persistent_author_state() -> None:
    draft = _table("knowledge.studio_drafts")
    assert REQUIRED_DATABASE_REVISION == "0060"
    assert {
        "workspace_id",
        "author_id",
        "kind",
        "state",
        "current_step",
        "name",
        "endpoint_alias",
        "domain_ref_id",
        "domain_ref_kind",
        "domain_source_version",
        "classification",
        "base_graph_id",
        "base_ontology_version_id",
        "base_release_id",
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


def test_abox_mapping_is_a_normalized_child_aggregate_not_draft_json() -> None:
    draft = _table("knowledge.studio_drafts")
    elements = _table("knowledge.tbox_draft_elements")
    sources = _table("knowledge.source_references")
    bindings = _table("knowledge.abox_binding_drafts")
    rules = _table("knowledge.abox_mapping_rule_drafts")

    assert "mapping_document" not in draft.columns
    assert "abox" not in draft.columns
    assert {
        "stable_element_id",
        "kind",
        "parent_stable_element_id",
        "source_stable_element_id",
        "target_stable_element_id",
        "version",
    } <= set(elements.c.keys())
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
    for table in (elements, sources, bindings, rules):
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


def test_additive_and_canonical_migrations_keep_owner_rls_and_no_delete_grant() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    generator = GENERATOR.read_text(encoding="utf-8")
    for source in (migration, generator):
        assert "studio_draft_owner_access" in source
        assert "AS RESTRICTIVE FOR ALL" in source
        assert "app.subject_id" in source
        assert "knowledge.studio_drafts" in source
        assert "GRANT UPDATE (" in source
        studio_update = source.split(
            ") ON knowledge.studio_drafts",
            1,
        )[0].rsplit("GRANT UPDATE (", 1)[1]
        assert "published_at" not in studio_update
    assert "GRANT DELETE ON knowledge.studio_drafts" not in migration
    assert "GRANT DELETE ON knowledge.studio_drafts" not in generator
    assert "downgrade would destroy canonical state" in migration


def test_abox_migrations_force_owner_rls_and_only_allow_rule_replacement_delete() -> None:
    migration = ABOX_MIGRATION.read_text(encoding="utf-8")
    initial = INITIAL_MIGRATION.read_text(encoding="utf-8")
    table_names = (
        "tbox_draft_elements",
        "source_references",
        "abox_binding_drafts",
        "abox_mapping_rule_drafts",
    )
    assert 'f"ALTER TABLE knowledge.{table} FORCE ROW LEVEL SECURITY"' in migration
    for table in table_names:
        assert f'"{table}"' in migration
        assert f"ALTER TABLE knowledge.{table} FORCE ROW LEVEL SECURITY" in initial
    for source in (migration, initial):
        assert "source_reference_owner_access" in source
        assert "studio_draft_owner_access" in source
        assert "app.subject_id" in source
        assert "GRANT DELETE ON knowledge.abox_mapping_rule_drafts" in source or (
            "GRANT SELECT, INSERT, DELETE" in source
            and "ON knowledge.abox_mapping_rule_drafts" in source
        )
        assert "GRANT DELETE ON knowledge.abox_binding_drafts" not in source
        assert "GRANT UPDATE ON knowledge.tbox_draft_elements" not in source
    for field in (
        "parent_stable_element_id",
        "source_stable_element_id",
        "target_stable_element_id",
    ):
        assert (
            initial.count(
                "fk_tbox_draft_elements_workspace_id_draft_id_"
                f"{field}_tbox_draft_elements"
            )
            == 1
        )
    assert "downgrade would destroy state" in migration


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
