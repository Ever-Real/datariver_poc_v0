# ruff: noqa: E501, S608 -- fixed source-owned IAM table vocabulary only.
"""Add normalized policy-book role rules and assignment evidence.

Revision ID: 0041
Revises: 0040
Create Date: 2026-07-23
"""

import re
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0041"
down_revision: str | Sequence[str] | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = {
    "access_role_data_rules",
    "access_role_assignments",
    "access_role_assignment_events",
}

_EXPECTED_COLUMNS: dict[str, dict[str, tuple[str, bool, int | None, bool | None, str | None]]] = {
    "access_role_data_rules": {
        "workspace_id": ("uuid", False, None, None, None),
        "role_id": ("uuid", False, None, None, None),
        "role_version": ("integer", False, None, None, None),
        "classification": ("integer", False, None, None, None),
        "access_level": ("string", False, 24, None, None),
        "partial_treatment": ("string", True, 24, None, None),
        "allowed_residency_regions": ("jsonb", False, None, None, None),
        "allowed_processing_purposes": ("jsonb", False, None, None, None),
        "payload_hash": ("string", False, 64, None, None),
        "created_by": ("uuid", False, None, None, None),
        "id": ("uuid", False, None, None, None),
        "created_at": ("datetime", False, None, True, "current_timestamp"),
        "updated_at": ("datetime", False, None, True, "current_timestamp"),
    },
    "access_role_assignments": {
        "workspace_id": ("uuid", False, None, None, None),
        "subject_id": ("uuid", False, None, None, None),
        "role_id": ("uuid", False, None, None, None),
        "role_version": ("integer", False, None, None, None),
        "membership_version": ("integer", False, None, None, None),
        "access_payload_hash": ("string", False, 64, None, None),
        "assigned_by": ("uuid", False, None, None, None),
        "active": ("boolean", False, None, None, None),
        "id": ("uuid", False, None, None, None),
        "created_at": ("datetime", False, None, True, "current_timestamp"),
        "updated_at": ("datetime", False, None, True, "current_timestamp"),
        "version": ("integer", False, None, None, None),
    },
    "access_role_assignment_events": {
        "workspace_id": ("uuid", False, None, None, None),
        "subject_id": ("uuid", False, None, None, None),
        "event_type": ("string", False, 20, None, None),
        "previous_role_id": ("uuid", True, None, None, None),
        "previous_role_version": ("integer", True, None, None, None),
        "role_id": ("uuid", True, None, None, None),
        "role_version": ("integer", True, None, None, None),
        "membership_version": ("integer", False, None, None, None),
        "access_payload_hash": ("string", False, 64, None, None),
        "actor_id": ("uuid", False, None, None, None),
        "occurred_at": ("datetime", False, None, True, "current_timestamp"),
        "id": ("uuid", False, None, None, None),
    },
}

_EXPECTED_CHECK_SQL = {
    "access_role_data_rules": {
        "ck_access_role_data_rules_access_level_vocabulary": "access_level::text = ANY (ARRAY['NO_ACCESS'::character varying, 'PARTIAL_ACCESS'::character varying, 'FULL_ACCESS'::character varying]::text[])",
        "ck_access_role_data_rules_access_scope_shape": "access_level::text = 'NO_ACCESS'::text AND jsonb_array_length(allowed_residency_regions) = 0 AND jsonb_array_length(allowed_processing_purposes) = 0 OR access_level::text <> 'NO_ACCESS'::text AND jsonb_array_length(allowed_residency_regions) > 0 AND jsonb_array_length(allowed_processing_purposes) > 0",
        "ck_access_role_data_rules_access_treatment_shape": "access_level::text = 'PARTIAL_ACCESS'::text AND partial_treatment IS NOT NULL OR access_level::text <> 'PARTIAL_ACCESS'::text AND partial_treatment IS NULL",
        "ck_access_role_data_rules_classification_range": "classification >= 0 AND classification <= 3",
        "ck_access_role_data_rules_partial_treatment_vocabulary": "partial_treatment IS NULL OR (partial_treatment::text = ANY (ARRAY['MASK'::character varying, 'REDACT'::character varying, 'TOKENIZE'::character varying]::text[]))",
        "ck_access_role_data_rules_payload_hash_sha256": "payload_hash::text ~ '^[0-9a-f]{64}$'::text",
        "ck_access_role_data_rules_role_version_positive": "role_version > 0",
        "ck_access_role_data_rules_scope_arrays": "jsonb_typeof(allowed_residency_regions) = 'array'::text AND jsonb_typeof(allowed_processing_purposes) = 'array'::text",
        "ck_access_role_data_rules_scope_item_vocabulary": 'jsonb_array_length(jsonb_path_query_array(allowed_residency_regions, \'$[*]?(@.type() == "string" && @ like_regex "^[A-Z0-9][A-Z0-9._:-]{0,63}$")\'::jsonpath)) = jsonb_array_length(allowed_residency_regions) AND allowed_processing_purposes <@ \'["METADATA_READ", "DATA_READ", "EXPORT", "ANALYTICS", "MODEL_TRAINING"]\'::jsonb',
    },
    "access_role_assignments": {
        "ck_access_role_assignments_membership_version_positive": "membership_version > 0",
        "ck_access_role_assignments_payload_hash_sha256": "access_payload_hash::text ~ '^[0-9a-f]{64}$'::text",
        "ck_access_role_assignments_role_version_positive": "role_version > 0",
    },
    "access_role_assignment_events": {
        "ck_access_role_assignment_events_event_type": "event_type::text = ANY (ARRAY['ASSIGNED'::character varying, 'REASSIGNED'::character varying, 'REMOVED'::character varying]::text[])",
        "ck_access_role_assignment_events_membership_version_positive": "membership_version > 0",
        "ck_access_role_assignment_events_payload_hash_sha256": "access_payload_hash::text ~ '^[0-9a-f]{64}$'::text",
        "ck_access_role_assignment_events_role_versions_positive": "previous_role_version IS NULL OR previous_role_version > 0) AND (role_version IS NULL OR role_version > 0",
        "ck_access_role_assignment_events_state_shape": "event_type::text = 'ASSIGNED'::text AND previous_role_id IS NULL AND previous_role_version IS NULL AND role_id IS NOT NULL AND role_version IS NOT NULL OR event_type::text = 'REASSIGNED'::text AND previous_role_id IS NOT NULL AND previous_role_version IS NOT NULL AND role_id IS NOT NULL AND role_version IS NOT NULL OR event_type::text = 'REMOVED'::text AND previous_role_id IS NOT NULL AND previous_role_version IS NOT NULL AND role_id IS NULL AND role_version IS NULL",
    },
}

_EXPECTED_FOREIGN_KEYS = {
    "access_role_data_rules": {
        "fk_access_role_data_rules_creator": (
            ("workspace_id", "created_by"),
            "iam",
            "workspace_memberships",
            ("workspace_id", "subject_id"),
            "RESTRICT",
        ),
        "fk_access_role_data_rules_role": (
            ("workspace_id", "role_id"),
            "iam",
            "access_roles",
            ("workspace_id", "id"),
            "RESTRICT",
        ),
        "fk_access_role_data_rules_workspace_id_workspaces": (
            ("workspace_id",),
            "platform",
            "workspaces",
            ("id",),
            "CASCADE",
        ),
    },
    "access_role_assignments": {
        "fk_access_role_assignments_actor": (
            ("workspace_id", "assigned_by"),
            "iam",
            "workspace_memberships",
            ("workspace_id", "subject_id"),
            "RESTRICT",
        ),
        "fk_access_role_assignments_membership": (
            ("workspace_id", "subject_id"),
            "iam",
            "workspace_memberships",
            ("workspace_id", "subject_id"),
            "RESTRICT",
        ),
        "fk_access_role_assignments_role": (
            ("workspace_id", "role_id"),
            "iam",
            "access_roles",
            ("workspace_id", "id"),
            "RESTRICT",
        ),
        "fk_access_role_assignments_workspace_id_workspaces": (
            ("workspace_id",),
            "platform",
            "workspaces",
            ("id",),
            "CASCADE",
        ),
    },
    "access_role_assignment_events": {
        "fk_access_role_assignment_events_actor": (
            ("workspace_id", "actor_id"),
            "iam",
            "workspace_memberships",
            ("workspace_id", "subject_id"),
            "RESTRICT",
        ),
        "fk_access_role_assignment_events_membership": (
            ("workspace_id", "subject_id"),
            "iam",
            "workspace_memberships",
            ("workspace_id", "subject_id"),
            "RESTRICT",
        ),
        "fk_access_role_assignment_events_previous_role": (
            ("workspace_id", "previous_role_id"),
            "iam",
            "access_roles",
            ("workspace_id", "id"),
            "RESTRICT",
        ),
        "fk_access_role_assignment_events_role": (
            ("workspace_id", "role_id"),
            "iam",
            "access_roles",
            ("workspace_id", "id"),
            "RESTRICT",
        ),
        "fk_access_role_assignment_events_workspace_id_workspaces": (
            ("workspace_id",),
            "platform",
            "workspaces",
            ("id",),
            "CASCADE",
        ),
    },
}

_EXPECTED_UNIQUES = {
    "access_role_data_rules": {
        ("workspace_id", "id"),
        ("workspace_id", "role_id", "role_version", "classification"),
    },
    "access_role_assignments": {
        ("workspace_id", "id"),
        ("workspace_id", "subject_id"),
    },
    "access_role_assignment_events": {("workspace_id", "id")},
}

_EXPECTED_INDEXES = {
    "access_role_data_rules": {
        "ix_access_role_data_rules_workspace_role_version": (
            ("workspace_id", "role_id", "role_version"),
            False,
        )
    },
    "access_role_assignments": {
        "ix_access_role_assignments_workspace_role": (("workspace_id", "role_id", "active"), False)
    },
    "access_role_assignment_events": {
        "ix_access_role_assignment_events_workspace_subject_occurred": (
            ("workspace_id", "subject_id", "occurred_at"),
            False,
        )
    },
}

_EXPECTED_RLS_PREDICATE = (
    "(workspace_id = (NULLIF(current_setting('app.workspace_id'::text, true), ''::text))::uuid)"
)


def _normalize_sql(value: object) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def _normalize_default(value: object | None) -> str | None:
    if value is None:
        return None
    normalized = _normalize_sql(value).lower()
    return "current_timestamp" if normalized in {"current_timestamp", "now()"} else normalized


def _column_fingerprint(
    column: dict[str, Any],
) -> tuple[str, bool, int | None, bool | None, str | None]:
    column_type = column["type"]
    if isinstance(column_type, postgresql.JSONB):
        type_name, length, timezone = "jsonb", None, None
    elif isinstance(column_type, sa.String):
        type_name, length, timezone = "string", column_type.length, None
    elif isinstance(column_type, sa.DateTime):
        type_name, length, timezone = "datetime", None, bool(column_type.timezone)
    elif isinstance(column_type, sa.Uuid):
        type_name, length, timezone = "uuid", None, None
    elif isinstance(column_type, sa.Integer):
        type_name, length, timezone = "integer", None, None
    elif isinstance(column_type, sa.Boolean):
        type_name, length, timezone = "boolean", None, None
    else:
        type_name, length, timezone = type(column_type).__name__.lower(), None, None
    return (
        type_name,
        bool(column["nullable"]),
        length,
        timezone,
        _normalize_default(column.get("default")),
    )


def _load_rls_contract(connection: Any) -> list[dict[str, object]]:
    rows = connection.execute(
        sa.text(
            """
            SELECT table_state.relname AS table_name,
                   table_state.relrowsecurity AS rls_enabled,
                   table_state.relforcerowsecurity AS rls_forced,
                   policy.policyname,
                   policy.permissive,
                   array_to_string(policy.roles, ',') AS roles,
                   policy.cmd,
                   policy.qual,
                   policy.with_check
            FROM pg_class AS table_state
            JOIN pg_namespace AS namespace ON namespace.oid = table_state.relnamespace
            LEFT JOIN pg_policies AS policy
              ON policy.schemaname = namespace.nspname
             AND policy.tablename = table_state.relname
            WHERE namespace.nspname = 'iam'
              AND table_state.relname IN (
                  'access_role_data_rules',
                  'access_role_assignments',
                  'access_role_assignment_events'
              )
            ORDER BY table_state.relname, policy.policyname
            """
        )
    ).mappings()
    return [dict(row) for row in rows]


def _assert_existing_schema_complete(
    inspector: Any, rls_contract: Sequence[dict[str, object]]
) -> None:
    issues: list[str] = []
    for table_name in sorted(_TABLES):
        expected_columns = _EXPECTED_COLUMNS[table_name]
        columns = {
            column["name"]: column for column in inspector.get_columns(table_name, schema="iam")
        }
        if set(columns) != set(expected_columns):
            issues.append(f"{table_name}:columns")
        for column_name, expected_fingerprint in expected_columns.items():
            column = columns.get(column_name)
            if column is None:
                continue
            if _column_fingerprint(column) != expected_fingerprint:
                issues.append(f"{table_name}:column:{column_name}")
        primary_key = inspector.get_pk_constraint(table_name, schema="iam")
        if primary_key.get("constrained_columns") != ["id"]:
            issues.append(f"{table_name}:primary-key")
        observed_checks = {
            str(value.get("name")): _normalize_sql(value.get("sqltext"))
            for value in inspector.get_check_constraints(table_name, schema="iam")
        }
        if observed_checks != _EXPECTED_CHECK_SQL[table_name]:
            issues.append(f"{table_name}:checks")
        observed_foreign_keys = {
            str(value.get("name")): (
                tuple(value.get("constrained_columns") or ()),
                value.get("referred_schema"),
                value.get("referred_table"),
                tuple(value.get("referred_columns") or ()),
                (value.get("options") or {}).get("ondelete"),
            )
            for value in inspector.get_foreign_keys(table_name, schema="iam")
        }
        if observed_foreign_keys != _EXPECTED_FOREIGN_KEYS[table_name]:
            issues.append(f"{table_name}:foreign-keys")
        observed_uniques = {
            tuple(value.get("column_names") or value.get("constrained_columns") or ())
            for value in inspector.get_unique_constraints(table_name, schema="iam")
        }
        if observed_uniques != _EXPECTED_UNIQUES[table_name]:
            issues.append(f"{table_name}:uniques")
        observed_indexes = {
            str(value.get("name")): (
                tuple(value.get("column_names") or ()),
                bool(value.get("unique")),
            )
            for value in inspector.get_indexes(table_name, schema="iam")
            if value.get("duplicates_constraint") is None
        }
        if observed_indexes != _EXPECTED_INDEXES[table_name]:
            issues.append(f"{table_name}:indexes")
    observed_rls: dict[str, tuple[object, ...]] = {}
    for row in rls_contract:
        table_name = str(row.get("table_name"))
        if table_name in observed_rls:
            issues.append(f"{table_name}:rls-policy-count")
            continue
        observed_rls[table_name] = (
            row.get("rls_enabled"),
            row.get("rls_forced"),
            row.get("policyname"),
            row.get("permissive"),
            row.get("roles"),
            row.get("cmd"),
            _normalize_sql(row.get("qual")),
            _normalize_sql(row.get("with_check")),
        )
    expected_rls = {
        table_name: (
            True,
            True,
            "workspace_isolation",
            "PERMISSIVE",
            "public",
            "ALL",
            _EXPECTED_RLS_PREDICATE,
            _EXPECTED_RLS_PREDICATE,
        )
        for table_name in _TABLES
    }
    if observed_rls != expected_rls:
        issues.append("rls-contract")
    if issues:
        raise RuntimeError(
            "Incomplete policy-book RBAC schema detected; refusing unsafe repair: "
            + ", ".join(sorted(set(issues)))
        )


def _create_tables() -> None:
    op.create_table(
        "access_role_data_rules",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("role_version", sa.Integer(), nullable=False),
        sa.Column("classification", sa.Integer(), nullable=False),
        sa.Column("access_level", sa.String(length=24), nullable=False),
        sa.Column("partial_treatment", sa.String(length=24), nullable=True),
        sa.Column("allowed_residency_regions", postgresql.JSONB(none_as_null=True), nullable=False),
        sa.Column(
            "allowed_processing_purposes", postgresql.JSONB(none_as_null=True), nullable=False
        ),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "access_level IN ('NO_ACCESS', 'PARTIAL_ACCESS', 'FULL_ACCESS')",
            name=op.f("ck_access_role_data_rules_access_level_vocabulary"),
        ),
        sa.CheckConstraint(
            "(access_level = 'PARTIAL_ACCESS' AND partial_treatment IS NOT NULL) OR "
            "(access_level <> 'PARTIAL_ACCESS' AND partial_treatment IS NULL)",
            name=op.f("ck_access_role_data_rules_access_treatment_shape"),
        ),
        sa.CheckConstraint(
            "classification BETWEEN 0 AND 3",
            name=op.f("ck_access_role_data_rules_classification_range"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(allowed_residency_regions) = 'array' AND "
            "jsonb_typeof(allowed_processing_purposes) = 'array'",
            name=op.f("ck_access_role_data_rules_scope_arrays"),
        ),
        sa.CheckConstraint(
            "(access_level = 'NO_ACCESS' AND "
            "jsonb_array_length(allowed_residency_regions) = 0 AND "
            "jsonb_array_length(allowed_processing_purposes) = 0) OR "
            "(access_level <> 'NO_ACCESS' AND "
            "jsonb_array_length(allowed_residency_regions) > 0 AND "
            "jsonb_array_length(allowed_processing_purposes) > 0)",
            name=op.f("ck_access_role_data_rules_access_scope_shape"),
        ),
        sa.CheckConstraint(
            "jsonb_array_length(jsonb_path_query_array(allowed_residency_regions, "
            '\'$[*] ? (@.type() == "string" && '
            '@ like_regex "^[A-Z0-9][A-Z0-9._:-]{0,63}$")\')) = '
            "jsonb_array_length(allowed_residency_regions) AND "
            "allowed_processing_purposes <@ "
            '\'["METADATA_READ", "DATA_READ", "EXPORT", "ANALYTICS", '
            '"MODEL_TRAINING"]\'::jsonb',
            name=op.f("ck_access_role_data_rules_scope_item_vocabulary"),
        ),
        sa.CheckConstraint(
            "partial_treatment IS NULL OR partial_treatment IN ('MASK', 'REDACT', 'TOKENIZE')",
            name=op.f("ck_access_role_data_rules_partial_treatment_vocabulary"),
        ),
        sa.CheckConstraint(
            "payload_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_access_role_data_rules_payload_hash_sha256"),
        ),
        sa.CheckConstraint(
            "role_version > 0", name=op.f("ck_access_role_data_rules_role_version_positive")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "created_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_access_role_data_rules_creator",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "role_id"],
            ["iam.access_roles.workspace_id", "iam.access_roles.id"],
            name="fk_access_role_data_rules_role",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["platform.workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "id"),
        sa.UniqueConstraint("workspace_id", "role_id", "role_version", "classification"),
        schema="iam",
    )
    op.create_index(
        "ix_access_role_data_rules_workspace_role_version",
        "access_role_data_rules",
        ["workspace_id", "role_id", "role_version"],
        schema="iam",
    )
    op.create_table(
        "access_role_assignments",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("role_version", sa.Integer(), nullable=False),
        sa.Column("membership_version", sa.Integer(), nullable=False),
        sa.Column("access_payload_hash", sa.String(length=64), nullable=False),
        sa.Column("assigned_by", sa.Uuid(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "access_payload_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_access_role_assignments_payload_hash_sha256"),
        ),
        sa.CheckConstraint(
            "membership_version > 0",
            name=op.f("ck_access_role_assignments_membership_version_positive"),
        ),
        sa.CheckConstraint(
            "role_version > 0", name=op.f("ck_access_role_assignments_role_version_positive")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "assigned_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_access_role_assignments_actor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "subject_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_access_role_assignments_membership",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "role_id"],
            ["iam.access_roles.workspace_id", "iam.access_roles.id"],
            name="fk_access_role_assignments_role",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["platform.workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "id"),
        sa.UniqueConstraint("workspace_id", "subject_id"),
        schema="iam",
    )
    op.create_index(
        "ix_access_role_assignments_workspace_role",
        "access_role_assignments",
        ["workspace_id", "role_id", "active"],
        schema="iam",
    )
    op.create_table(
        "access_role_assignment_events",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("previous_role_id", sa.Uuid(), nullable=True),
        sa.Column("previous_role_version", sa.Integer(), nullable=True),
        sa.Column("role_id", sa.Uuid(), nullable=True),
        sa.Column("role_version", sa.Integer(), nullable=True),
        sa.Column("membership_version", sa.Integer(), nullable=False),
        sa.Column("access_payload_hash", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('ASSIGNED', 'REASSIGNED', 'REMOVED')",
            name=op.f("ck_access_role_assignment_events_event_type"),
        ),
        sa.CheckConstraint(
            "(event_type = 'ASSIGNED' AND previous_role_id IS NULL "
            "AND previous_role_version IS NULL AND role_id IS NOT NULL "
            "AND role_version IS NOT NULL) OR "
            "(event_type = 'REASSIGNED' AND previous_role_id IS NOT NULL "
            "AND previous_role_version IS NOT NULL AND role_id IS NOT NULL "
            "AND role_version IS NOT NULL) OR "
            "(event_type = 'REMOVED' AND previous_role_id IS NOT NULL "
            "AND previous_role_version IS NOT NULL AND role_id IS NULL "
            "AND role_version IS NULL)",
            name=op.f("ck_access_role_assignment_events_state_shape"),
        ),
        sa.CheckConstraint(
            "membership_version > 0",
            name=op.f("ck_access_role_assignment_events_membership_version_positive"),
        ),
        sa.CheckConstraint(
            "(previous_role_version IS NULL OR previous_role_version > 0) AND "
            "(role_version IS NULL OR role_version > 0)",
            name=op.f("ck_access_role_assignment_events_role_versions_positive"),
        ),
        sa.CheckConstraint(
            "access_payload_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_access_role_assignment_events_payload_hash_sha256"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "actor_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_access_role_assignment_events_actor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "subject_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_access_role_assignment_events_membership",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "previous_role_id"],
            ["iam.access_roles.workspace_id", "iam.access_roles.id"],
            name="fk_access_role_assignment_events_previous_role",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "role_id"],
            ["iam.access_roles.workspace_id", "iam.access_roles.id"],
            name="fk_access_role_assignment_events_role",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["platform.workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "id"),
        schema="iam",
    )
    op.create_index(
        "ix_access_role_assignment_events_workspace_subject_occurred",
        "access_role_assignment_events",
        ["workspace_id", "subject_id", "occurred_at"],
        schema="iam",
    )


def _install_security_contract() -> None:
    op.execute(
        """DO $datariver$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid =
            'iam.access_role_data_rules'::regclass AND
            conname = 'ck_access_role_data_rules_scope_arrays') THEN
            ALTER TABLE iam.access_role_data_rules ADD CONSTRAINT
                ck_access_role_data_rules_scope_arrays CHECK (
                    jsonb_typeof(allowed_residency_regions) = 'array' AND
                    jsonb_typeof(allowed_processing_purposes) = 'array');
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid =
            'iam.access_role_data_rules'::regclass AND
            conname = 'ck_access_role_data_rules_access_scope_shape') THEN
            ALTER TABLE iam.access_role_data_rules ADD CONSTRAINT
                ck_access_role_data_rules_access_scope_shape CHECK (
                    (access_level = 'NO_ACCESS' AND
                     jsonb_array_length(allowed_residency_regions) = 0 AND
                     jsonb_array_length(allowed_processing_purposes) = 0) OR
                    (access_level <> 'NO_ACCESS' AND
                     jsonb_array_length(allowed_residency_regions) > 0 AND
                     jsonb_array_length(allowed_processing_purposes) > 0));
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid =
            'iam.access_role_data_rules'::regclass AND
            conname = 'ck_access_role_data_rules_scope_item_vocabulary') THEN
            ALTER TABLE iam.access_role_data_rules ADD CONSTRAINT
                ck_access_role_data_rules_scope_item_vocabulary CHECK (
                    jsonb_array_length(jsonb_path_query_array(
                        allowed_residency_regions,
                        '$[*] ? (@.type() == "string" &&
                            @ like_regex "^[A-Z0-9][A-Z0-9._:-]{0,63}$")')) =
                        jsonb_array_length(allowed_residency_regions) AND
                    allowed_processing_purposes <@
                        '["METADATA_READ", "DATA_READ", "EXPORT", "ANALYTICS",
                          "MODEL_TRAINING"]'::jsonb);
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid =
            'iam.access_role_assignment_events'::regclass AND
            conname = 'ck_access_role_assignment_events_state_shape') THEN
            ALTER TABLE iam.access_role_assignment_events ADD CONSTRAINT
                ck_access_role_assignment_events_state_shape CHECK (
                    (event_type = 'ASSIGNED' AND previous_role_id IS NULL AND
                     previous_role_version IS NULL AND role_id IS NOT NULL AND
                     role_version IS NOT NULL) OR
                    (event_type = 'REASSIGNED' AND previous_role_id IS NOT NULL AND
                     previous_role_version IS NOT NULL AND role_id IS NOT NULL AND
                     role_version IS NOT NULL) OR
                    (event_type = 'REMOVED' AND previous_role_id IS NOT NULL AND
                     previous_role_version IS NOT NULL AND role_id IS NULL AND
                    role_version IS NULL));
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid =
            'iam.access_role_assignment_events'::regclass AND
            conname = 'ck_access_role_assignment_events_role_versions_positive') THEN
            ALTER TABLE iam.access_role_assignment_events ADD CONSTRAINT
                ck_access_role_assignment_events_role_versions_positive CHECK (
                    (previous_role_version IS NULL OR previous_role_version > 0) AND
                    (role_version IS NULL OR role_version > 0));
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid =
            'iam.access_role_assignment_events'::regclass AND
            conname = 'fk_access_role_assignment_events_previous_role') THEN
            ALTER TABLE iam.access_role_assignment_events ADD CONSTRAINT
                fk_access_role_assignment_events_previous_role
                FOREIGN KEY (workspace_id, previous_role_id)
                REFERENCES iam.access_roles (workspace_id, id) ON DELETE RESTRICT;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid =
            'iam.access_role_assignment_events'::regclass AND
            conname = 'fk_access_role_assignment_events_role') THEN
            ALTER TABLE iam.access_role_assignment_events ADD CONSTRAINT
                fk_access_role_assignment_events_role
                FOREIGN KEY (workspace_id, role_id)
                REFERENCES iam.access_roles (workspace_id, id) ON DELETE RESTRICT;
        END IF;
        END $datariver$"""
    )
    op.execute("ALTER TABLE iam.access_role_data_rules ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE iam.access_role_data_rules FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE iam.access_role_assignments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE iam.access_role_assignments FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE iam.access_role_assignment_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE iam.access_role_assignment_events FORCE ROW LEVEL SECURITY")
    for table_name in sorted(_TABLES):
        op.execute(
            f"""DO $datariver$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE schemaname = 'iam' AND tablename = '{table_name}'
                  AND policyname = 'workspace_isolation'
            ) THEN
                CREATE POLICY workspace_isolation ON iam.{table_name}
                USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)
                WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid);
            END IF;
            END $datariver$"""
        )
    op.execute(
        "COMMENT ON TABLE iam.access_role_data_rules IS "
        "'Missing classification rule resolves to ROLE_DATA_RULE_MISSING (deny)'"
    )
    op.execute(
        """DO $datariver$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
            REVOKE UPDATE ON iam.access_roles FROM datariver_app;
            GRANT UPDATE (name, description, clearance, groups, allowed_actions, denied_actions,
                allowed_system_ids, allowed_domain_ids, active, updated_by, version, updated_at)
                ON iam.access_roles TO datariver_app;
            GRANT SELECT, INSERT ON iam.access_role_data_rules,
                iam.access_role_assignment_events TO datariver_app;
            GRANT SELECT, INSERT ON iam.access_role_assignments TO datariver_app;
            GRANT UPDATE (role_id, role_version, membership_version, access_payload_hash,
                assigned_by, active, version, updated_at)
                ON iam.access_role_assignments TO datariver_app;
        END IF;
        END $datariver$"""
    )


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing = set(inspector.get_table_names(schema="iam")) & _TABLES
    if existing and existing != _TABLES:
        raise RuntimeError("Partial policy-book RBAC schema detected; refusing unsafe repair.")
    if not existing:
        _create_tables()
    _install_security_contract()
    inspector.clear_cache()
    _assert_existing_schema_complete(inspector, _load_rls_contract(connection))


def downgrade() -> None:
    # Canonical 0001 owns the evidence schema; destructive downgrade is intentionally disabled.
    pass
