from __future__ import annotations

from pathlib import Path

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, Table

from datariver.infrastructure.db import models  # noqa: F401
from datariver.infrastructure.db.base import Base
from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "backend/alembic/versions/0059_knowledge_studio_foundation.py"
GENERATOR = ROOT / "scripts/generate_initial_migration.py"


def _table(name: str) -> Table:
    return Base.metadata.tables[name]


def test_studio_draft_model_is_separate_persistent_author_state() -> None:
    draft = _table("knowledge.studio_drafts")
    assert REQUIRED_DATABASE_REVISION == "0059"
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
