from __future__ import annotations

from pathlib import Path

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, Table, UniqueConstraint

from datariver.infrastructure.db import models  # noqa: F401
from datariver.infrastructure.db.base import Base

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "backend/alembic/versions/0080_knowledge_asset_delivery_policies.py"
CANONICAL_MIGRATION = ROOT / "backend/alembic/versions/0001_initial_schema.py"


def _table(name: str) -> Table:
    return Base.metadata.tables[name]


def test_delivery_policy_model_is_workspace_scoped_and_graph_bound() -> None:
    policies = _table("knowledge.delivery_policies")

    assert {
        "workspace_id",
        "graph_id",
        "api_enabled",
        "chat_enabled",
        "priority",
        "match_any_terms",
        "match_all_terms",
        "excluded_terms",
        "created_by",
        "updated_by",
        "version",
    } <= set(policies.c.keys())
    references = {
        tuple(element.target_fullname for element in constraint.elements)
        for constraint in policies.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert (
        "knowledge.graphs.workspace_id",
        "knowledge.graphs.id",
    ) in references
    assert (
        "iam.workspace_memberships.workspace_id",
        "iam.workspace_memberships.subject_id",
    ) in references
    assert any(
        isinstance(constraint, UniqueConstraint)
        and {column.name for column in constraint.columns} == {"workspace_id", "graph_id"}
        for constraint in policies.constraints
    )
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in policies.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "priority BETWEEN 0 AND 1000" in checks["ck_delivery_policies_priority_range"]
    assert "jsonb_typeof" in checks["ck_delivery_policies_route_terms_arrays"]
    assert (
        "jsonb_array_length(match_any_terms) <= 50"
        in checks["ck_delivery_policies_route_terms_arrays"]
    )
    assert "NOT chat_enabled" in checks["ck_delivery_policies_chat_route_has_positive_term"]
    assert any(
        isinstance(index, Index) and index.name == "ix_delivery_policies_chat_match"
        for index in policies.indexes
    )


def test_delivery_policy_revision_forces_rls_and_limits_application_mutation() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")

    assert 'revision: str = "0080"' in migration
    assert 'down_revision: str | Sequence[str] | None = "0079"' in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "CREATE POLICY workspace_isolation" in migration
    assert "GRANT SELECT, INSERT ON knowledge.delivery_policies TO datariver_app" in migration
    assert "GRANT UPDATE (api_enabled, chat_enabled, priority, match_any_terms" in migration
    assert "GRANT DELETE ON knowledge.delivery_policies" not in migration
    assert "0080 downgrade refused" in migration


def test_canonical_schema_contains_the_same_delivery_policy_security_contract() -> None:
    canonical = CANONICAL_MIGRATION.read_text(encoding="utf-8")

    assert "op.create_table('delivery_policies'" in canonical
    assert "ALTER TABLE knowledge.delivery_policies FORCE ROW LEVEL SECURITY" in canonical
    assert "knowledge.property_profiles, knowledge.delivery_policies" in canonical
    assert "ON knowledge.delivery_policies TO datariver_app" in canonical
