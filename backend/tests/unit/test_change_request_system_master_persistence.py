from __future__ import annotations

from pathlib import Path

from sqlalchemy import CheckConstraint, Table

from datariver.infrastructure.db.models.governance import ChangeRequestModel
from datariver.infrastructure.db.models.platform import (
    DataSystemModel,
    ExternalServiceProfileModel,
    SystemAssigneeModel,
    SystemSchemaScopeModel,
)
from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION


def _check_names(table: Table) -> set[str]:
    return {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name is not None
    }


def test_change_request_schedule_fields_are_typed_and_vocabulary_constrained() -> None:
    table = ChangeRequestModel.__table__

    assert {"requested_due_date", "priority", "urgency"} <= set(table.c.keys())
    assert {
        "ck_change_requests_priority_vocabulary",
        "ck_change_requests_urgency_vocabulary",
    } <= _check_names(table)


def test_system_master_models_have_workspace_scoped_integrity_and_no_secret_column() -> None:
    system = DataSystemModel.__table__
    scope = SystemSchemaScopeModel.__table__
    assignee = SystemAssigneeModel.__table__
    profile = ExternalServiceProfileModel.__table__

    assert {"workspace_id", "code", "name", "active", "version"} <= set(system.c.keys())
    assert {"workspace_id", "system_id", "platform", "database_name", "schema_name"} <= set(
        scope.c.keys()
    )
    assert {"workspace_id", "system_id", "subject_id", "responsibility", "priority"} <= set(
        assignee.c.keys()
    )
    assert {"workspace_id", "service_key", "endpoint_url", "secret_reference", "updated_by"} <= set(
        profile.c.keys()
    )
    assert "secret" not in set(profile.c.keys())
    assert "password" not in set(profile.c.keys())
    assert {
        "ck_data_systems_code_shape",
    } <= _check_names(system)
    assert {
        "ck_system_schema_scopes_platform_present",
        "ck_system_schema_scopes_database_present",
        "ck_system_schema_scopes_schema_present",
    } <= _check_names(scope)
    assert {
        "ck_system_assignees_responsibility_vocabulary",
        "ck_system_assignees_priority_range",
    } <= _check_names(assignee)
    assert {
        "ck_external_service_profiles_service_key_vocabulary",
        "ck_external_service_profiles_endpoint_url_scheme",
        "ck_external_service_profiles_secret_reference_present",
    } <= _check_names(profile)


def test_system_master_migration_is_forced_rls_and_uses_redacted_connection_profiles() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (root / "backend/alembic/versions/0022_cr_schedule_and_system_master.py").read_text(
        encoding="utf-8"
    )

    assert REQUIRED_DATABASE_REVISION == "0023"
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "GRANT SELECT, INSERT, UPDATE ON platform.data_systems" in migration
    assert "secret_reference" in migration
    assert "password" not in migration.casefold()
    assert "DROP TABLE" not in migration
