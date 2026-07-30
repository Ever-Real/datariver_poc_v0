from __future__ import annotations

from pathlib import Path
from typing import cast

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
        if isinstance(constraint, CheckConstraint) and isinstance(constraint.name, str)
    }


def test_change_request_schedule_fields_are_typed_and_vocabulary_constrained() -> None:
    table = cast(Table, ChangeRequestModel.__table__)

    assert {"requested_due_date", "priority", "urgency"} <= set(table.c.keys())
    assert {
        "ck_change_requests_priority_vocabulary",
        "ck_change_requests_urgency_vocabulary",
    } <= _check_names(table)


def test_system_master_models_have_workspace_scoped_integrity_and_no_secret_column() -> None:
    system = cast(Table, DataSystemModel.__table__)
    scope = cast(Table, SystemSchemaScopeModel.__table__)
    assignee = cast(Table, SystemAssigneeModel.__table__)
    profile = cast(Table, ExternalServiceProfileModel.__table__)

    assert {"workspace_id", "code", "name", "active", "version"} <= set(system.c.keys())
    assert {"workspace_id", "system_id", "platform", "database_name", "schema_name"} <= set(
        scope.c.keys()
    )
    assert {"workspace_id", "system_id", "subject_id", "responsibility", "priority"} <= set(
        assignee.c.keys()
    )
    assert {
        "workspace_id",
        "service_key",
        "endpoint_url",
        "secret_reference",
        "configuration_yaml",
        "updated_by",
    } <= set(profile.c.keys())
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

    assert REQUIRED_DATABASE_REVISION == "0069"
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "GRANT SELECT, INSERT, UPDATE ON platform.data_systems" in migration
    assert "secret_reference" in migration
    assert "password" not in migration.casefold()
    assert "DROP TABLE" not in migration


def test_external_redis_connector_migration_extends_only_bounded_vocabularies() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (
        root / "backend/alembic/versions/0040_external_redis_and_s3_connectors.py"
    ).read_text(encoding="utf-8")

    assert 'revision: str = "0040"' in migration
    assert 'down_revision: str | Sequence[str] | None = "0039"' in migration
    assert "REDIS_CACHE" in migration
    assert "REDIS_DELIVERY" in migration
    assert "REDIS_PING" in migration
    assert "redis|rediss" in migration
    assert "GRANT SELECT ON platform.external_service_profiles" in migration
    assert "TO datariver_relay" in migration
    assert "password" not in migration.casefold()
    assert "DROP TABLE" not in migration


def test_connector_probe_scope_migration_matches_runtime_evidence() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (
        root / "backend/alembic/versions/0043_system_configuration_probe_scope.py"
    ).read_text(encoding="utf-8")

    assert 'revision: str = "0043"' in migration
    assert "Downgrade would falsify connector probe evidence" in migration
    assert "SET test_scope = 'REDIS_PING'" not in migration
    assert 'down_revision: str | Sequence[str] | None = "0042"' in migration
    assert "REDIS_POLICY" in migration
    assert "S3_HEAD_BUCKET" in migration
    assert "REDIS_PING" in migration
    assert "_constraint_definition()" in migration
    assert "_scope_definition(_LATER_CANONICAL_SCOPES)" in migration
    assert "if definition in {" in migration
    assert "if definition != _LEGACY_SCOPE_DEFINITION:" in migration
    assert "op.drop_constraint(" in migration
    assert "op.f(_CONSTRAINT)" in migration
    assert "DROP TABLE" not in migration


def test_reranking_probe_scope_migration_matches_runtime_evidence() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (root / "backend/alembic/versions/0053_reranking_probe_scope.py").read_text(
        encoding="utf-8"
    )
    initial = (root / "backend/alembic/versions/0001_initial_schema.py").read_text(encoding="utf-8")

    assert 'revision: str = "0053"' in migration
    assert 'down_revision: str | Sequence[str] | None = "0052"' in migration
    assert "RERANKING_INFERENCE" in migration
    assert "Downgrade would falsify reranking probe evidence" in migration
    assert "_constraint_definition()" in migration
    assert "_scope_definition(_CURRENT_SCOPES)" in migration
    assert "op.drop_constraint(" in migration
    assert "DROP TABLE" not in migration
    assert "RERANKING_INFERENCE" in initial
