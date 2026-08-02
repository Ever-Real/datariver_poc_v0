from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import CheckConstraint, Table
from sqlalchemy.dialects import postgresql

from datariver.domain.authz import Classification, SubjectAttributes
from datariver.domain.common import ForbiddenError, ValidationError
from datariver.infrastructure.db.admin_access import SqlSystemDirectoryRepository
from datariver.infrastructure.db.catalog import (
    SqlCatalogChangeTargetReader,
    SqlCatalogIndexReader,
)
from datariver.infrastructure.db.models.governance import ChangeRequestModel
from datariver.infrastructure.db.models.platform import (
    DataSystemModel,
    ExternalServiceProfileModel,
    SystemAssigneeModel,
    SystemSchemaScopeModel,
)


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


def test_change_target_schema_routing_filter_is_cr_reader_only_and_fail_closed() -> None:
    system_id = uuid4()
    dialect = cast(Any, postgresql.dialect)()

    with pytest.raises(ValidationError, match="Unsupported catalog filters"):
        SqlCatalogIndexReader._filter_conditions({"routing_system_id": system_id})

    conditions = SqlCatalogChangeTargetReader._filter_conditions(
        {"asset_types": ("TABLE",), "routing_system_id": system_id}
    )
    rendered = " ".join(str(condition.compile(dialect=dialect)) for condition in conditions)
    assert "platform.system_schema_scopes" in rendered
    assert "platform.data_systems" in rendered
    assert "system_schema_scopes.active IS true" in rendered
    assert "data_systems.active IS true" in rendered
    assert (
        "catalog.assets_projection.system_id = platform.system_schema_scopes.system_id" in rendered
    )


def test_change_target_scope_uses_system_responsibility_for_nonrestricted_rows_only() -> None:
    workspace_id, system_id, subject_id = (uuid4() for _ in range(3))
    dialect = cast(Any, postgresql.dialect)()
    subject = SubjectAttributes(
        subject_id=subject_id,
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset({"data-engineers"}),
        job_function="DATA_ENGINEER",
        clearance=Classification.CONFIDENTIAL,
        allowed_system_ids=frozenset({system_id}),
        allowed_domain_ids=frozenset(),
    )

    change_scope = " ".join(
        str(
            condition.compile(
                dialect=dialect,
                compile_kwargs={"literal_binds": True},
            )
        )
        for condition in SqlCatalogChangeTargetReader(cast(Any, object()))._scope_conditions(
            subject
        )
    )
    generic_scope = " ".join(
        str(
            condition.compile(
                dialect=dialect,
                compile_kwargs={"literal_binds": True},
            )
        )
        for condition in SqlCatalogIndexReader(cast(Any, object()))._scope_conditions(subject)
    )

    assert "assets_projection.classification != 3" in change_scope
    assert "assets_projection.classification = 3" in change_scope
    assert "assets_projection.domain_id IS NOT NULL" in change_scope
    assert "platform.system_schema_scopes" in change_scope
    assert "assets_projection.classification != 3" not in generic_scope
    assert "assets_projection.domain_id IS NOT NULL" in generic_scope


def test_system_schema_scope_asset_predicate_is_actor_scoped_and_excludes_restricted() -> None:
    workspace_id, system_id, subject_id, domain_id = (uuid4() for _ in range(4))
    dialect = cast(Any, postgresql.dialect)()
    subject = SubjectAttributes(
        subject_id=subject_id,
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset({"security-administrators"}),
        job_function="SECURITY_ADMINISTRATOR",
        clearance=Classification.CONFIDENTIAL,
        allowed_domain_ids=frozenset({domain_id}),
    )

    compiled = [
        condition.compile(dialect=dialect)
        for condition in SqlSystemDirectoryRepository._schema_scope_asset_conditions(
            workspace_id=workspace_id,
            system_id=system_id,
            subject=subject,
        )
    ]
    rendered = " ".join(str(condition) for condition in compiled)
    parameter_documents = [condition.params for condition in compiled]

    assert "assets_projection.lifecycle" in rendered
    assert "assets_projection.deleted_at IS NULL" in rendered
    assert "assets_projection.domain_id IS NOT NULL" in rendered
    assert "assets_projection.system_id IS NULL" in rendered
    classification_parameters = next(
        document for document in parameter_documents if "classification_2" in document
    )
    assert classification_parameters["classification_1"] == int(Classification.PUBLIC)
    assert classification_parameters["classification_2"] == [
        int(Classification.INTERNAL),
        int(Classification.CONFIDENTIAL),
    ]
    assert int(Classification.RESTRICTED) not in classification_parameters.values()
    assert classification_parameters["domain_id_1"] == [domain_id]
    candidate_source = inspect.getsource(SqlSystemDirectoryRepository.list_schema_scope_candidates)
    patch_source = inspect.getsource(SqlSystemDirectoryRepository.patch_schema_scopes)
    assert "_schema_scope_asset_conditions(" in candidate_source
    assert "_schema_scope_asset_conditions(" in patch_source
    assert ".with_for_update(read=True)" in patch_source


@pytest.mark.parametrize(
    ("active", "workspace_matches", "job_function", "groups"),
    [
        (False, True, "SECURITY_ADMINISTRATOR", frozenset({"security-administrators"})),
        (True, False, "SECURITY_ADMINISTRATOR", frozenset({"security-administrators"})),
        (True, True, "SERVICE_ACCOUNT", frozenset({"service-accounts"})),
    ],
)
def test_system_schema_scope_asset_predicate_rejects_nonhuman_actor_before_query(
    active: bool,
    workspace_matches: bool,
    job_function: str,
    groups: frozenset[str],
) -> None:
    workspace_id = uuid4()
    subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id if workspace_matches else uuid4(),
        active=active,
        department_id=None,
        groups=groups,
        job_function=job_function,
        clearance=Classification.RESTRICTED,
    )

    with pytest.raises(ForbiddenError, match="active human administrator"):
        SqlSystemDirectoryRepository._schema_scope_asset_conditions(
            workspace_id=workspace_id,
            system_id=uuid4(),
            subject=subject,
        )


def test_system_master_migration_is_forced_rls_and_uses_redacted_connection_profiles() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (root / "backend/alembic/versions/0022_cr_schedule_and_system_master.py").read_text(
        encoding="utf-8"
    )

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
