from __future__ import annotations

from pathlib import Path
from typing import cast

from sqlalchemy import CheckConstraint, Table

from datariver.infrastructure.db.models.platform import AccessRoleModel
from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION


def test_access_role_model_is_workspace_scoped_and_contains_no_credential_fields() -> None:
    table = cast(Table, AccessRoleModel.__table__)

    assert {
        "workspace_id",
        "role_key",
        "name",
        "description",
        "clearance",
        "groups",
        "allowed_actions",
        "denied_actions",
        "allowed_system_ids",
        "allowed_domain_ids",
        "active",
        "updated_by",
        "version",
    } <= set(table.c.keys())
    assert {"password", "secret", "token"}.isdisjoint(table.c.keys())
    checks = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {
        "ck_access_roles_role_key_shape",
        "ck_access_roles_clearance_range",
    } <= checks


def test_access_role_migration_installs_rls_and_bounded_app_privileges() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (root / "backend/alembic/versions/0031_workspace_access_roles.py").read_text(
        encoding="utf-8"
    )
    initial = (root / "backend/alembic/versions/0001_initial_schema.py").read_text(encoding="utf-8")

    assert REQUIRED_DATABASE_REVISION == "0039"
    assert "ALTER TABLE iam.access_roles FORCE ROW LEVEL SECURITY" in migration
    assert "GRANT SELECT, INSERT, UPDATE ON iam.access_roles" in migration
    assert "GRANT DELETE ON iam.access_roles" not in migration
    assert "access_roles" in initial
