from __future__ import annotations

import inspect
import runpy
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Table, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Dialect

from datariver.infrastructure.db.models.platform import (
    AccessRoleAssignmentEventModel,
    AccessRoleAssignmentModel,
    AccessRoleDataRuleModel,
    AccessRoleModel,
    CanonicalAdminBindingModel,
)
from datariver.interfaces.http.routes.admin import (
    _role_assigned_count,
    _role_assigned_counts,
)

POSTGRES_DIALECT = cast(Callable[[], Dialect], postgresql.dialect)()


def test_role_assignment_counts_do_not_treat_stale_legacy_markers_as_authority() -> None:
    single_source = inspect.getsource(_role_assigned_count)
    batch_source = inspect.getsource(_role_assigned_counts)

    assert "AccessRoleAssignmentModel.active.is_(True)" in single_source
    assert "~exists().where" in single_source
    assert "NOT EXISTS" in batch_source
    assert "current_assignment.active IS TRUE" in batch_source


class MetadataInspector:
    def __init__(
        self,
        *,
        check_contract: dict[str, dict[str, str]],
        foreign_key_contract: dict[str, dict[str, tuple[object, ...]]],
        index_contract: dict[str, dict[str, tuple[tuple[str, ...], bool]]],
        mutate_check: bool = False,
        mutate_foreign_key: bool = False,
        mutate_index: bool = False,
        mutate_column: bool = False,
    ) -> None:
        self._check_contract = check_contract
        self._foreign_key_contract = foreign_key_contract
        self._index_contract = index_contract
        self._mutate_check = mutate_check
        self._mutate_foreign_key = mutate_foreign_key
        self._mutate_index = mutate_index
        self._mutate_column = mutate_column
        self._tables = {
            "access_role_data_rules": cast(Table, AccessRoleDataRuleModel.__table__),
            "access_role_assignments": cast(Table, AccessRoleAssignmentModel.__table__),
            "access_role_assignment_events": cast(Table, AccessRoleAssignmentEventModel.__table__),
        }

    def get_columns(self, table_name: str, *, schema: str) -> list[dict[str, object]]:
        assert schema == "iam"
        columns: list[dict[str, object]] = [
            {
                "name": column.name,
                "type": column.type.dialect_impl(POSTGRES_DIALECT),
                "nullable": column.nullable,
                "default": (
                    str(getattr(column.server_default, "arg", column.server_default))
                    if column.server_default is not None
                    else None
                ),
            }
            for column in self._tables[table_name].columns
            if not (table_name == "access_role_assignments" and column.name == "role_kind")
        ]
        if self._mutate_column and table_name == "access_role_data_rules":
            next(column for column in columns if column["name"] == "payload_hash")["type"] = (
                postgresql.VARCHAR(length=32)
            )
        return columns

    def get_pk_constraint(self, table_name: str, *, schema: str) -> dict[str, object]:
        assert schema == "iam"
        return {
            "constrained_columns": [
                column.name for column in self._tables[table_name].primary_key.columns
            ]
        }

    def get_check_constraints(self, table_name: str, *, schema: str) -> list[dict[str, object]]:
        assert schema == "iam"
        definitions = dict(self._check_contract[table_name])
        if self._mutate_check and table_name == "access_role_assignment_events":
            definitions["ck_access_role_assignment_events_role_versions_positive"] = "TRUE"
        return [{"name": name, "sqltext": sqltext} for name, sqltext in definitions.items()]

    def get_foreign_keys(self, table_name: str, *, schema: str) -> list[dict[str, object]]:
        assert schema == "iam"
        definitions = dict(self._foreign_key_contract[table_name])
        if self._mutate_foreign_key and table_name == "access_role_assignments":
            name = "fk_access_role_assignments_role"
            constrained, referred_schema, referred_table, referred, _ = definitions[name]
            definitions[name] = (
                constrained,
                referred_schema,
                referred_table,
                referred,
                "CASCADE",
            )
        return [
            {
                "name": name,
                "constrained_columns": list(cast(tuple[str, ...], definition[0])),
                "referred_schema": definition[1],
                "referred_table": definition[2],
                "referred_columns": list(cast(tuple[str, ...], definition[3])),
                "options": {"ondelete": definition[4]},
            }
            for name, definition in definitions.items()
        ]

    def get_unique_constraints(self, table_name: str, *, schema: str) -> list[dict[str, object]]:
        assert schema == "iam"
        return [
            {
                "name": constraint.name,
                "column_names": [column.name for column in constraint.columns],
            }
            for constraint in self._tables[table_name].constraints
            if isinstance(constraint, UniqueConstraint)
        ]

    def get_indexes(self, table_name: str, *, schema: str) -> list[dict[str, object]]:
        assert schema == "iam"
        definitions = dict(self._index_contract[table_name])
        if self._mutate_index and table_name == "access_role_assignments":
            definitions["ix_access_role_assignments_workspace_role"] = (
                ("workspace_id", "active", "role_id"),
                False,
            )
        return [
            {"name": name, "column_names": list(columns), "unique": unique}
            for name, (columns, unique) in definitions.items()
        ]


def test_access_role_model_is_workspace_scoped_and_contains_no_credential_fields() -> None:
    table = cast(Table, AccessRoleModel.__table__)

    assert {
        "workspace_id",
        "role_key",
        "role_kind",
        "management_source",
        "capability_catalog_version",
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
        "ck_access_roles_role_kind_vocabulary",
        "ck_access_roles_management_source_vocabulary",
        "ck_access_roles_management_shape",
    } <= checks


def test_canonical_admin_binding_is_separate_from_generic_role_assignments() -> None:
    role_table = cast(Table, AccessRoleModel.__table__)
    assignment_table = cast(Table, AccessRoleAssignmentModel.__table__)
    binding_table = cast(Table, CanonicalAdminBindingModel.__table__)

    assert "role_kind" in assignment_table.c
    assignment_checks = {
        constraint.name
        for constraint in assignment_table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ck_access_role_assignments_human_role_only" in assignment_checks
    assignment_role_fk = next(
        constraint
        for constraint in assignment_table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and constraint.name == "fk_access_role_assignments_role"
    )
    assert [column.name for column in assignment_role_fk.columns] == [
        "workspace_id",
        "role_id",
        "role_kind",
    ]
    assert {"workspace_id", "subject_id"} == {column.name for column in binding_table.primary_key}
    assert {
        "canonical_role_id",
        "canonical_role_version",
        "capability_catalog_version",
        "capability_hash",
        "membership_version",
        "membership_access_hash",
        "state",
        "binding_source",
    } <= set(binding_table.c.keys())
    canonical_indexes = {
        index.name
        for index in role_table.indexes
        if index.unique and index.dialect_options["postgresql"].get("where") is not None
    }
    assert "uq_access_roles_workspace_canonical_admin" in canonical_indexes


def test_access_role_migration_installs_rls_and_bounded_app_privileges() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (root / "backend/alembic/versions/0041_policy_book_rbac.py").read_text(
        encoding="utf-8"
    )
    initial = (root / "backend/alembic/versions/0001_initial_schema.py").read_text(encoding="utf-8")

    for table_name in (
        "access_role_data_rules",
        "access_role_assignments",
        "access_role_assignment_events",
    ):
        assert f"ALTER TABLE iam.{table_name} FORCE ROW LEVEL SECURITY" in migration
        assert table_name in initial
    assert "GRANT DELETE" not in migration
    assert "ROLE_DATA_RULE_MISSING" in migration
    assert "REVOKE UPDATE ON iam.access_roles FROM datariver_app" in migration
    assert "GRANT UPDATE (name, description, clearance, groups" in migration
    assert "GRANT SELECT, INSERT, UPDATE ON iam.access_roles TO datariver_app" not in initial


def test_0089_migration_has_no_automatic_user_escalation_or_runtime_binding_write() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (root / "backend/alembic/versions/0089_canonical_admin_role_binding.py").read_text(
        encoding="utf-8"
    )
    initial = (root / "backend/alembic/versions/0001_initial_schema.py").read_text(encoding="utf-8")

    assert 'down_revision: str | Sequence[str] | None = "0088"' in migration
    for protected_table in (
        "iam.subjects",
        "iam.workspace_memberships",
        "iam.access_role_assignments",
        "iam.access_role_assignment_events",
        "iam.canonical_admin_bindings",
    ):
        assert f"INSERT INTO {protected_table}" not in migration
    assert "role_kind = 'HUMAN_ROLE'" in migration
    assert "fk_access_role_assignments_role" in migration
    assert "REVOKE INSERT, UPDATE, DELETE ON iam.canonical_admin_bindings FROM datariver_app" in (
        migration
    )
    assert "GRANT SELECT ON iam.canonical_admin_bindings TO datariver_app" in migration
    assert "GRANT EXECUTE" not in migration
    assert "capture_local_canonical_admin_binding" not in migration
    assert "ON iam.workspace_memberships" not in migration
    assert "binding history" in migration
    assert "FOR INSERT TO datariver_bootstrap" in migration
    assert "FOR UPDATE TO datariver_bootstrap" in migration
    assert "FOR ALL TO datariver_bootstrap" not in migration
    downgrade = migration.split("def downgrade() -> None:", maxsplit=1)[1]
    assert downgrade.index("access_roles_bootstrap_canonical_update") < downgrade.index(
        'op.drop_column("access_roles", "capability_catalog_version"'
    )
    assert downgrade.index("access_roles_bootstrap_canonical_insert") < downgrade.index(
        'op.drop_column("access_roles", "role_kind"'
    )
    for source in (migration, initial):
        assert "ALTER TABLE iam.access_roles ENABLE ROW LEVEL SECURITY" in source
        assert "ALTER TABLE iam.access_roles FORCE ROW LEVEL SECURITY" in source
        assert "canonical_admin_bindings_local_insert" in source
        assert "00000000-0000-4000-8000-000000000100" in source
        assert "00000000-0000-4000-8000-000000000101" in source


def test_policy_book_rbac_models_are_tenant_scoped_and_secret_free() -> None:
    for model in (
        AccessRoleDataRuleModel,
        AccessRoleAssignmentModel,
        AccessRoleAssignmentEventModel,
    ):
        table = cast(Table, model.__table__)
        assert "workspace_id" in table.c
        assert {"password", "secret", "token"}.isdisjoint(table.c.keys())

    rules = cast(Table, AccessRoleDataRuleModel.__table__)
    assert {
        "role_id",
        "role_version",
        "classification",
        "access_level",
        "partial_treatment",
        "allowed_residency_regions",
        "allowed_processing_purposes",
        "payload_hash",
    } <= set(rules.c.keys())
    assignments = cast(Table, AccessRoleAssignmentModel.__table__)
    assert {
        "subject_id",
        "role_id",
        "role_version",
        "membership_version",
        "access_payload_hash",
        "active",
    } <= set(assignments.c.keys())

    rule_checks = {
        constraint.name
        for constraint in rules.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {
        "ck_access_role_data_rules_scope_arrays",
        "ck_access_role_data_rules_access_scope_shape",
        "ck_access_role_data_rules_scope_item_vocabulary",
    } <= rule_checks

    events = cast(Table, AccessRoleAssignmentEventModel.__table__)
    event_checks = {
        constraint.name
        for constraint in events.constraints
        if isinstance(constraint, CheckConstraint)
    }
    event_foreign_keys = {
        constraint.name
        for constraint in events.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert "ck_access_role_assignment_events_state_shape" in event_checks
    assert "ck_access_role_assignment_events_role_versions_positive" in event_checks
    assert {
        "fk_access_role_assignment_events_previous_role",
        "fk_access_role_assignment_events_role",
    } <= event_foreign_keys


def test_0041_schema_fingerprint_accepts_metadata_and_rejects_all_table_partial_state() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = runpy.run_path(str(root / "backend/alembic/versions/0041_policy_book_rbac.py"))
    validator = cast(
        Callable[[Any, list[dict[str, object]]], None],
        migration["_assert_existing_schema_complete"],
    )
    checks = cast(dict[str, dict[str, str]], migration["_EXPECTED_CHECK_SQL"])
    foreign_keys = cast(
        dict[str, dict[str, tuple[object, ...]]], migration["_EXPECTED_FOREIGN_KEYS"]
    )
    indexes = cast(
        dict[str, dict[str, tuple[tuple[str, ...], bool]]], migration["_EXPECTED_INDEXES"]
    )
    tables = cast(set[str], migration["_TABLES"])
    predicate = cast(str, migration["_EXPECTED_RLS_PREDICATE"])

    def inspector(**mutations: bool) -> MetadataInspector:
        return MetadataInspector(
            check_contract=checks,
            foreign_key_contract=foreign_keys,
            index_contract=indexes,
            **mutations,
        )

    def rls_contract(*, mutate: bool = False) -> list[dict[str, object]]:
        return [
            {
                "table_name": table_name,
                "rls_enabled": True,
                "rls_forced": True,
                "policyname": "workspace_isolation",
                "permissive": "PERMISSIVE",
                "roles": "public",
                "cmd": "ALL",
                "qual": "TRUE" if mutate and index == 0 else predicate,
                "with_check": predicate,
            }
            for index, table_name in enumerate(sorted(tables))
        ]

    validator(inspector(), rls_contract())
    for mutation in (
        {"mutate_check": True},
        {"mutate_foreign_key": True},
        {"mutate_index": True},
        {"mutate_column": True},
    ):
        with pytest.raises(RuntimeError, match="Incomplete policy-book RBAC schema"):
            validator(inspector(**mutation), rls_contract())
    with pytest.raises(RuntimeError, match="Incomplete policy-book RBAC schema"):
        validator(inspector(), rls_contract(mutate=True))
