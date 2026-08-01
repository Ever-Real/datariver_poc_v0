# ruff: noqa: S608 -- SQL is rendered only from hash-pinned server constants.
"""Add server-owned Canonical Admin definitions and protected local bindings.

Revision ID: 0089
Revises: 0088
Create Date: 2026-08-01
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from datariver.domain.capability_catalog import (
    CANONICAL_ADMIN_CAPABILITY_DOCUMENT,
    CANONICAL_ADMIN_CAPABILITY_HASH,
    CAPABILITY_CATALOG_VERSION,
)
from datariver.domain.common import canonical_json_hash
from datariver.infrastructure.db.identity_provisioning_sql import (
    IDENTITY_PROVISIONING_FUNCTION_SQL,
    IDENTITY_PROVISIONING_FUNCTION_SQL_V1,
)

revision: str = "0089"
down_revision: str | Sequence[str] | None = "0088"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CATALOG_VERSION = "ACCESS_ROLE_CAPABILITY_CATALOG_V2"
_CAPABILITY_HASH = "51cb767d682a3410c0c0ebc45160b3ed73dcdd09a8c51637e63d7d351eec74a5"
_PROVISIONING_V2_SHA256 = "a61298aa3c3e021b79e411cabae61ffe947072e497865776baeecf2560b31efb"
_PROVISIONING_V1_SHA256 = "16362a1f52030844dda309c4efcb1f0b2d082620472502448d17032c9ede5c39"


def _pinned_capability_actions_json() -> str:
    document = CANONICAL_ADMIN_CAPABILITY_DOCUMENT
    actions = document.get("allowed_actions")
    if (
        CAPABILITY_CATALOG_VERSION != _CATALOG_VERSION
        or CANONICAL_ADMIN_CAPABILITY_HASH != _CAPABILITY_HASH
        or canonical_json_hash(document) != _CAPABILITY_HASH
        or not isinstance(actions, list)
        or len(actions) != 64
        or actions != sorted(set(actions))
    ):
        raise RuntimeError("The Canonical Admin V2 capability snapshot changed after revision 0089")
    return json.dumps(actions, separators=(",", ":"))


def _pinned_provisioning_sql(sql: str, expected_sha256: str, *, label: str) -> str:
    if sql.count("CREATE OR REPLACE FUNCTION") != 1:
        raise RuntimeError(f"The {label} identity provisioning boundary changed")
    if hashlib.sha256(sql.encode()).hexdigest() != expected_sha256:
        raise RuntimeError(f"The {label} identity provisioning function changed after 0089")
    return sql


def canonical_admin_definition_security_sql() -> tuple[str, ...]:
    actions_json = _pinned_capability_actions_json().replace("'", "''")
    definition_function = f"""
CREATE OR REPLACE FUNCTION iam.ensure_canonical_admin_definition()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, iam
AS $datariver$
BEGIN
    INSERT INTO iam.access_roles (
        id, workspace_id, role_key, role_kind, management_source,
        capability_catalog_version, name, description, clearance, groups,
        allowed_actions, denied_actions, allowed_system_ids, allowed_domain_ids,
        active, updated_by, version, created_at, updated_at
    ) VALUES (
        gen_random_uuid(), NEW.id, 'canonical-admin', 'CANONICAL_ADMIN',
        'SERVER_CANONICAL', '{_CATALOG_VERSION}', 'Canonical Admin',
        'Server-owned Canonical Admin capability definition.', 3,
        '["security-administrators"]'::jsonb, '{actions_json}'::jsonb,
        '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, TRUE, NULL, 1,
        transaction_timestamp(), transaction_timestamp()
    )
    ON CONFLICT (workspace_id) WHERE role_kind = 'CANONICAL_ADMIN' DO NOTHING;
    RETURN NEW;
END
$datariver$
""".strip()
    install = f"""
DO $datariver$
DECLARE
    existing_workspace uuid;
BEGIN
    SELECT workspace_id INTO existing_workspace
    FROM iam.access_roles
    WHERE role_key = 'canonical-admin'
      AND role_kind <> 'CANONICAL_ADMIN'
    LIMIT 1;
    IF existing_workspace IS NOT NULL THEN
        RAISE EXCEPTION
            '0089 requires the reserved canonical-admin role key to be unused';
    END IF;

    INSERT INTO iam.access_roles (
        id, workspace_id, role_key, role_kind, management_source,
        capability_catalog_version, name, description, clearance, groups,
        allowed_actions, denied_actions, allowed_system_ids, allowed_domain_ids,
        active, updated_by, version, created_at, updated_at
    )
    SELECT
        gen_random_uuid(), workspace.id, 'canonical-admin', 'CANONICAL_ADMIN',
        'SERVER_CANONICAL', '{_CATALOG_VERSION}', 'Canonical Admin',
        'Server-owned Canonical Admin capability definition.', 3,
        '["security-administrators"]'::jsonb, '{actions_json}'::jsonb,
        '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, TRUE, NULL, 1,
        transaction_timestamp(), transaction_timestamp()
    FROM platform.workspaces AS workspace
    ON CONFLICT (workspace_id) WHERE role_kind = 'CANONICAL_ADMIN' DO NOTHING;
END
$datariver$
""".strip()
    policy_statements = (
        "ALTER TABLE iam.access_roles ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE iam.access_roles FORCE ROW LEVEL SECURITY",
        "DROP POLICY IF EXISTS workspace_isolation ON iam.access_roles",
        "DROP POLICY IF EXISTS access_roles_workspace_select ON iam.access_roles",
        "DROP POLICY IF EXISTS access_roles_human_insert ON iam.access_roles",
        "DROP POLICY IF EXISTS access_roles_human_update ON iam.access_roles",
        "DROP POLICY IF EXISTS access_roles_bootstrap_canonical_insert ON iam.access_roles",
        "DROP POLICY IF EXISTS access_roles_bootstrap_canonical_update ON iam.access_roles",
        """
CREATE POLICY access_roles_workspace_select ON iam.access_roles
    FOR SELECT USING (
        workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
    )
""".strip(),
        """
CREATE POLICY access_roles_human_insert ON iam.access_roles
    FOR INSERT WITH CHECK (
        workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
        AND role_kind = 'HUMAN_ROLE'
        AND management_source = 'HUMAN_ADMIN'
        AND capability_catalog_version IS NULL
        AND updated_by = NULLIF(current_setting('app.subject_id', true), '')::uuid
    )
""".strip(),
        """
CREATE POLICY access_roles_human_update ON iam.access_roles
    FOR UPDATE USING (
        workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
        AND role_kind = 'HUMAN_ROLE'
        AND management_source = 'HUMAN_ADMIN'
    ) WITH CHECK (
        workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
        AND role_kind = 'HUMAN_ROLE'
        AND management_source = 'HUMAN_ADMIN'
        AND capability_catalog_version IS NULL
        AND updated_by = NULLIF(current_setting('app.subject_id', true), '')::uuid
    )
""".strip(),
        f"""
CREATE POLICY access_roles_bootstrap_canonical_insert ON iam.access_roles
    FOR INSERT TO datariver_bootstrap WITH CHECK (
        workspace_id = '00000000-0000-4000-8000-000000000100'::uuid
        AND role_key = 'canonical-admin'
        AND role_kind = 'CANONICAL_ADMIN'
        AND management_source = 'SERVER_CANONICAL'
        AND capability_catalog_version = '{_CATALOG_VERSION}'
        AND clearance = 3
        AND groups = '["security-administrators"]'::jsonb
        AND allowed_actions = '{actions_json}'::jsonb
        AND denied_actions = '[]'::jsonb
        AND allowed_system_ids = '[]'::jsonb
        AND allowed_domain_ids = '[]'::jsonb
        AND active IS TRUE
        AND updated_by IS NULL
    )
""".strip(),
        f"""
CREATE POLICY access_roles_bootstrap_canonical_update ON iam.access_roles
    FOR UPDATE TO datariver_bootstrap USING (
        workspace_id = '00000000-0000-4000-8000-000000000100'::uuid
        AND role_kind = 'CANONICAL_ADMIN'
    ) WITH CHECK (
        workspace_id = '00000000-0000-4000-8000-000000000100'::uuid
        AND role_key = 'canonical-admin'
        AND role_kind = 'CANONICAL_ADMIN'
        AND management_source = 'SERVER_CANONICAL'
        AND capability_catalog_version = '{_CATALOG_VERSION}'
        AND clearance = 3
        AND groups = '["security-administrators"]'::jsonb
        AND allowed_actions = '{actions_json}'::jsonb
        AND denied_actions = '[]'::jsonb
        AND allowed_system_ids = '[]'::jsonb
        AND allowed_domain_ids = '[]'::jsonb
        AND active IS TRUE
        AND updated_by IS NULL
    )
""".strip(),
        "ALTER TABLE iam.canonical_admin_bindings ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE iam.canonical_admin_bindings FORCE ROW LEVEL SECURITY",
        "DROP POLICY IF EXISTS workspace_isolation ON iam.canonical_admin_bindings",
        """
CREATE POLICY canonical_admin_bindings_workspace_select
    ON iam.canonical_admin_bindings
    FOR SELECT USING (
        workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
    )
""".strip(),
        f"""
CREATE POLICY canonical_admin_bindings_local_insert ON iam.canonical_admin_bindings
    FOR INSERT TO datariver_bootstrap WITH CHECK (
        workspace_id = '00000000-0000-4000-8000-000000000100'::uuid
        AND subject_id = '00000000-0000-4000-8000-000000000101'::uuid
        AND role_kind = 'CANONICAL_ADMIN'
        AND capability_catalog_version = '{_CATALOG_VERSION}'
        AND capability_hash = '{_CAPABILITY_HASH}'
        AND state = 'ACTIVE'
        AND binding_source = 'LOCAL_DEVELOPMENT_BOOTSTRAP'
    )
""".strip(),
        f"""
CREATE POLICY canonical_admin_bindings_local_update ON iam.canonical_admin_bindings
    FOR UPDATE TO datariver_bootstrap USING (
        workspace_id = '00000000-0000-4000-8000-000000000100'::uuid
        AND subject_id = '00000000-0000-4000-8000-000000000101'::uuid
        AND binding_source = 'LOCAL_DEVELOPMENT_BOOTSTRAP'
    ) WITH CHECK (
        workspace_id = '00000000-0000-4000-8000-000000000100'::uuid
        AND subject_id = '00000000-0000-4000-8000-000000000101'::uuid
        AND role_kind = 'CANONICAL_ADMIN'
        AND capability_catalog_version = '{_CATALOG_VERSION}'
        AND capability_hash = '{_CAPABILITY_HASH}'
        AND state = 'ACTIVE'
        AND binding_source = 'LOCAL_DEVELOPMENT_BOOTSTRAP'
    )
""".strip(),
        "REVOKE ALL ON iam.canonical_admin_bindings FROM PUBLIC",
    )
    grant_block = """
DO $datariver$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
        GRANT SELECT ON iam.canonical_admin_bindings TO datariver_app;
        REVOKE INSERT, UPDATE, DELETE ON iam.canonical_admin_bindings FROM datariver_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_bootstrap') THEN
        GRANT SELECT, INSERT, UPDATE ON iam.access_roles,
            iam.canonical_admin_bindings TO datariver_bootstrap;
    END IF;
END
$datariver$;
""".strip()
    statements = (definition_function, install, *policy_statements, grant_block)
    if len(statements) != 23:
        raise RuntimeError("The Canonical Admin security statement boundary changed")
    return statements


def upgrade() -> None:
    op.add_column(
        "access_roles",
        sa.Column("role_kind", sa.String(length=32), server_default="HUMAN_ROLE", nullable=False),
        schema="iam",
    )
    op.add_column(
        "access_roles",
        sa.Column(
            "management_source",
            sa.String(length=32),
            server_default="HUMAN_ADMIN",
            nullable=False,
        ),
        schema="iam",
    )
    op.add_column(
        "access_roles",
        sa.Column("capability_catalog_version", sa.String(length=100), nullable=True),
        schema="iam",
    )
    op.alter_column("access_roles", "updated_by", nullable=True, schema="iam")
    op.create_check_constraint(
        "ck_access_roles_role_kind_vocabulary",
        "access_roles",
        "role_kind IN ('HUMAN_ROLE', 'CANONICAL_ADMIN')",
        schema="iam",
    )
    op.create_check_constraint(
        "ck_access_roles_management_source_vocabulary",
        "access_roles",
        "management_source IN ('HUMAN_ADMIN', 'SERVER_CANONICAL')",
        schema="iam",
    )
    op.create_check_constraint(
        "ck_access_roles_management_shape",
        "access_roles",
        "(role_kind = 'HUMAN_ROLE' AND management_source = 'HUMAN_ADMIN' "
        "AND capability_catalog_version IS NULL AND updated_by IS NOT NULL) OR "
        "(role_kind = 'CANONICAL_ADMIN' AND management_source = 'SERVER_CANONICAL' "
        "AND role_key = 'canonical-admin' AND capability_catalog_version IS NOT NULL "
        "AND updated_by IS NULL AND active IS TRUE AND clearance = 3)",
        schema="iam",
    )
    op.create_unique_constraint(
        "uq_access_roles_workspace_id_id_role_kind",
        "access_roles",
        ["workspace_id", "id", "role_kind"],
        schema="iam",
    )
    op.create_index(
        "uq_access_roles_workspace_canonical_admin",
        "access_roles",
        ["workspace_id"],
        unique=True,
        schema="iam",
        postgresql_where=sa.text("role_kind = 'CANONICAL_ADMIN'"),
    )

    op.add_column(
        "access_role_assignments",
        sa.Column("role_kind", sa.String(length=32), server_default="HUMAN_ROLE", nullable=False),
        schema="iam",
    )
    op.drop_constraint(
        "fk_access_role_assignments_role",
        "access_role_assignments",
        schema="iam",
        type_="foreignkey",
    )
    op.create_check_constraint(
        "ck_access_role_assignments_human_role_only",
        "access_role_assignments",
        "role_kind = 'HUMAN_ROLE'",
        schema="iam",
    )
    op.create_foreign_key(
        "fk_access_role_assignments_role",
        "access_role_assignments",
        "access_roles",
        ["workspace_id", "role_id", "role_kind"],
        ["workspace_id", "id", "role_kind"],
        source_schema="iam",
        referent_schema="iam",
        ondelete="RESTRICT",
    )

    op.create_table(
        "canonical_admin_bindings",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_role_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role_kind", sa.String(length=32), server_default="CANONICAL_ADMIN", nullable=False
        ),
        sa.Column("canonical_role_version", sa.Integer(), nullable=False),
        sa.Column("capability_catalog_version", sa.String(length=100), nullable=False),
        sa.Column("capability_hash", sa.String(length=64), nullable=False),
        sa.Column("membership_version", sa.Integer(), nullable=False),
        sa.Column("membership_access_hash", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("binding_source", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "binding_source = 'LOCAL_DEVELOPMENT_BOOTSTRAP'",
            name="ck_canonical_admin_bindings_development_bootstrap_only",
        ),
        sa.CheckConstraint(
            "role_kind = 'CANONICAL_ADMIN'",
            name="ck_canonical_admin_bindings_canonical_role_only",
        ),
        sa.CheckConstraint(
            "state IN ('ACTIVE', 'REVOKED')",
            name="ck_canonical_admin_bindings_state_vocabulary",
        ),
        sa.CheckConstraint(
            "canonical_role_version > 0",
            name="ck_canonical_admin_bindings_role_version_positive",
        ),
        sa.CheckConstraint(
            "membership_version > 0",
            name="ck_canonical_admin_bindings_membership_version_positive",
        ),
        sa.CheckConstraint(
            "capability_hash ~ '^[0-9a-f]{64}$'",
            name="ck_canonical_admin_bindings_capability_hash_sha256",
        ),
        sa.CheckConstraint(
            "membership_access_hash ~ '^[0-9a-f]{64}$'",
            name="ck_canonical_admin_bindings_access_hash_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "subject_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_canonical_admin_bindings_membership",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "canonical_role_id", "role_kind"],
            ["iam.access_roles.workspace_id", "iam.access_roles.id", "iam.access_roles.role_kind"],
            name="fk_canonical_admin_bindings_role",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "subject_id"),
        schema="iam",
    )

    for statement in canonical_admin_definition_security_sql():
        op.execute(statement)
    op.execute("DROP TRIGGER IF EXISTS ensure_canonical_admin_definition ON platform.workspaces")
    op.execute(
        "CREATE TRIGGER ensure_canonical_admin_definition "
        "AFTER INSERT ON platform.workspaces FOR EACH ROW "
        "EXECUTE FUNCTION iam.ensure_canonical_admin_definition()"
    )
    op.execute(
        _pinned_provisioning_sql(
            IDENTITY_PROVISIONING_FUNCTION_SQL,
            _PROVISIONING_V2_SHA256,
            label="human-role-only",
        )
    )


def downgrade() -> None:
    op.execute(
        """
DO $datariver$
BEGIN
    IF EXISTS (SELECT 1 FROM iam.canonical_admin_bindings) THEN
        RAISE EXCEPTION '0089 downgrade is blocked by Canonical Admin binding history';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM iam.access_roles AS role
        WHERE role.role_kind = 'CANONICAL_ADMIN'
          AND (
              EXISTS (
                  SELECT 1 FROM iam.access_role_assignments AS assignment
                  WHERE assignment.workspace_id = role.workspace_id
                    AND assignment.role_id = role.id
              )
              OR EXISTS (
                  SELECT 1 FROM iam.access_role_assignment_events AS event
                  WHERE event.workspace_id = role.workspace_id
                    AND (event.role_id = role.id OR event.previous_role_id = role.id)
              )
              OR EXISTS (
                  SELECT 1 FROM iam.access_role_data_rules AS rule
                  WHERE rule.workspace_id = role.workspace_id AND rule.role_id = role.id
              )
          )
    ) THEN
        RAISE EXCEPTION '0089 downgrade is blocked by referenced Canonical Admin definitions';
    END IF;
END
$datariver$
"""
    )
    op.execute(
        _pinned_provisioning_sql(
            IDENTITY_PROVISIONING_FUNCTION_SQL_V1,
            _PROVISIONING_V1_SHA256,
            label="pre-0089",
        )
    )
    op.execute("DROP TRIGGER IF EXISTS ensure_canonical_admin_definition ON platform.workspaces")
    op.execute("DROP FUNCTION IF EXISTS iam.ensure_canonical_admin_definition()")
    op.drop_table("canonical_admin_bindings", schema="iam")

    op.execute("DELETE FROM iam.access_roles WHERE role_kind = 'CANONICAL_ADMIN'")
    op.drop_constraint(
        "fk_access_role_assignments_role",
        "access_role_assignments",
        schema="iam",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_access_role_assignments_human_role_only",
        "access_role_assignments",
        schema="iam",
        type_="check",
    )
    op.drop_column("access_role_assignments", "role_kind", schema="iam")
    op.create_foreign_key(
        "fk_access_role_assignments_role",
        "access_role_assignments",
        "access_roles",
        ["workspace_id", "role_id"],
        ["workspace_id", "id"],
        source_schema="iam",
        referent_schema="iam",
        ondelete="RESTRICT",
    )

    op.execute("DROP POLICY IF EXISTS access_roles_human_update ON iam.access_roles")
    op.execute("DROP POLICY IF EXISTS access_roles_human_insert ON iam.access_roles")
    op.execute("DROP POLICY IF EXISTS access_roles_bootstrap_canonical_update ON iam.access_roles")
    op.execute("DROP POLICY IF EXISTS access_roles_bootstrap_canonical_insert ON iam.access_roles")
    op.execute("DROP POLICY IF EXISTS access_roles_workspace_select ON iam.access_roles")
    op.execute(
        "CREATE POLICY workspace_isolation ON iam.access_roles "
        "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) "
        "WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)"
    )
    op.drop_index(
        "uq_access_roles_workspace_canonical_admin",
        table_name="access_roles",
        schema="iam",
    )
    op.drop_constraint(
        "uq_access_roles_workspace_id_id_role_kind",
        "access_roles",
        schema="iam",
        type_="unique",
    )
    op.drop_constraint(
        "ck_access_roles_management_shape", "access_roles", schema="iam", type_="check"
    )
    op.drop_constraint(
        "ck_access_roles_management_source_vocabulary",
        "access_roles",
        schema="iam",
        type_="check",
    )
    op.drop_constraint(
        "ck_access_roles_role_kind_vocabulary",
        "access_roles",
        schema="iam",
        type_="check",
    )
    op.alter_column("access_roles", "updated_by", nullable=False, schema="iam")
    op.drop_column("access_roles", "capability_catalog_version", schema="iam")
    op.drop_column("access_roles", "management_source", schema="iam")
    op.drop_column("access_roles", "role_kind", schema="iam")
