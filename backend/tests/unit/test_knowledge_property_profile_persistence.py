from __future__ import annotations

from pathlib import Path

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, Table, UniqueConstraint

from datariver.infrastructure.db import models  # noqa: F401
from datariver.infrastructure.db.base import Base
from datariver.infrastructure.db.knowledge_property_profiles import (
    ARCHIVE_OPERATION,
    CREATE_OPERATION,
    UPDATE_OPERATION,
)

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "backend/alembic/versions/0076_knowledge_property_profiles.py"


def _table(name: str) -> Table:
    return Base.metadata.tables[name]


def test_property_profile_models_reference_immutable_release_properties() -> None:
    profiles = _table("knowledge.property_profiles")
    synonyms = _table("knowledge.property_profile_synonyms")
    releases = _table("knowledge.studio_releases")
    elements = _table("knowledge.ontology_elements")

    assert {
        "workspace_id",
        "graph_id",
        "studio_release_id",
        "ontology_version_id",
        "ontology_element_id",
        "element_kind",
        "stable_property_id",
        "description",
        "unit",
        "lifecycle",
        "archived_at",
        "archived_by",
        "version",
    } <= set(profiles.c.keys())
    assert {"workspace_id", "profile_id", "value", "normalized_value"} <= set(synonyms.c.keys())

    profile_references = {
        tuple(element.target_fullname for element in constraint.elements)
        for constraint in profiles.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert (
        "knowledge.studio_releases.workspace_id",
        "knowledge.studio_releases.graph_id",
        "knowledge.studio_releases.id",
        "knowledge.studio_releases.ontology_version_id",
    ) in profile_references
    assert (
        "knowledge.ontology_elements.workspace_id",
        "knowledge.ontology_elements.ontology_version_id",
        "knowledge.ontology_elements.id",
        "knowledge.ontology_elements.kind",
        "knowledge.ontology_elements.stable_element_id",
    ) in profile_references

    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in profiles.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ACTIVE" in checks["ck_property_profiles_lifecycle_vocabulary"]
    assert "ARCHIVED" in checks["ck_property_profiles_lifecycle_vocabulary"]
    assert "PROPERTY" in checks["ck_property_profiles_element_kind_property"]
    assert "archived_at" in checks["ck_property_profiles_archive_shape"]
    assert any(
        isinstance(index, Index)
        and index.name == "uq_property_profiles_one_active_per_element"
        and index.unique
        for index in profiles.indexes
    )
    assert any(
        isinstance(index, Index) and index.name == "ix_property_profile_synonyms_value"
        for index in synonyms.indexes
    )
    assert any(
        isinstance(constraint, UniqueConstraint)
        and constraint.name == "uq_studio_releases_profile_release_ontology"
        for constraint in releases.constraints
    )
    assert any(
        isinstance(constraint, UniqueConstraint)
        and constraint.name == "uq_ontology_elements_profile_identity"
        for constraint in elements.constraints
    )


def test_property_profile_revision_forces_rls_and_omits_parent_delete_grant() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")

    assert 'revision: str = "0076"' in migration
    assert 'down_revision: str | Sequence[str] | None = "0075"' in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "CREATE POLICY workspace_isolation" in migration
    assert "AS RESTRICTIVE" not in migration
    assert "uq_property_profiles_one_active_per_element" in migration
    assert "uq_studio_releases_profile_release_ontology" in migration
    assert "uq_ontology_elements_profile_identity" in migration
    assert "GRANT SELECT, INSERT ON knowledge.property_profiles TO datariver_app" in migration
    assert "GRANT UPDATE (description, unit, lifecycle, updated_by, archived_at" in migration
    assert "GRANT SELECT, INSERT, DELETE ON knowledge.property_profiles" not in migration
    assert (
        "GRANT SELECT, INSERT, DELETE ON knowledge.property_profile_synonyms TO datariver_app"
        in migration
    )


def test_property_profile_idempotency_operations_fit_the_persistence_contract() -> None:
    assert CREATE_OPERATION == "kg.property-profile.create.v1"
    assert UPDATE_OPERATION == "kg.property-profile.update.v1"
    assert ARCHIVE_OPERATION == "kg.property-profile.archive.v1"
    assert all(
        len(operation) <= 100
        for operation in (CREATE_OPERATION, UPDATE_OPERATION, ARCHIVE_OPERATION)
    )
