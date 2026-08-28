"""Add workspace-managed access-role definitions.

Revision ID: 0031
Revises: 0030
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0031"
down_revision: str | Sequence[str] | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_SETTING = "NULLIF(current_setting('app.workspace_id', true), '')::uuid"
EXPECTED_OBJECT_COUNT = 6

_CANONICAL_COLUMNS = (
    "workspace_id|uuid|uuid||NO",
    "role_key|character varying|varchar|80|NO",
    "role_kind|character varying|varchar|32|NO",
    "management_source|character varying|varchar|32|NO",
    "capability_catalog_version|character varying|varchar|100|YES",
    "name|character varying|varchar|255|NO",
    "description|text|text||NO",
    "clearance|integer|int4||NO",
    "groups|jsonb|jsonb||NO",
    "allowed_actions|jsonb|jsonb||NO",
    "denied_actions|jsonb|jsonb||NO",
    "allowed_system_ids|jsonb|jsonb||NO",
    "allowed_domain_ids|jsonb|jsonb||NO",
    "active|boolean|bool||NO",
    "updated_by|uuid|uuid||YES",
    "id|uuid|uuid||NO",
    "created_at|timestamp with time zone|timestamptz||NO",
    "updated_at|timestamp with time zone|timestamptz||NO",
    "version|integer|int4||NO",
)
_CANONICAL_CONSTRAINTS = (
    "ck_access_roles_clearance_range",
    "ck_access_roles_management_shape",
    "ck_access_roles_management_source_vocabulary",
    "ck_access_roles_role_key_shape",
    "ck_access_roles_role_kind_vocabulary",
    "fk_access_roles_updater",
    "fk_access_roles_workspace_id_workspaces",
    "pk_access_roles",
    "uq_access_roles_workspace_id_id",
    "uq_access_roles_workspace_id_id_role_kind",
    "uq_access_roles_workspace_id_role_key",
)
_CANONICAL_INDEXES = (
    "ix_access_roles_workspace_active_name",
    "uq_access_roles_workspace_canonical_admin",
)
_CANONICAL_POLICIES = (
    "access_roles_bootstrap_canonical_insert",
    "access_roles_bootstrap_canonical_update",
    "access_roles_human_insert",
    "access_roles_human_update",
    "access_roles_workspace_select",
)


def _existing_object_count() -> int:
    return int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    (to_regclass('iam.access_roles') IS NOT NULL)::int
                    + (SELECT count(*) FROM pg_constraint
                       WHERE conrelid = to_regclass('iam.access_roles')
                         AND conname IN (
                           'ck_access_roles_role_key_shape',
                           'ck_access_roles_clearance_range',
                           'fk_access_roles_updater'
                         ))
                    + (to_regclass('iam.ix_access_roles_workspace_active_name') IS NOT NULL)::int
                    + (SELECT count(*) FROM pg_policies
                       WHERE schemaname = 'iam' AND tablename = 'access_roles'
                         AND policyname = 'workspace_isolation')
                """
            )
        )
        .scalar_one()
    )


def _is_canonical_schema() -> bool:
    row = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    ARRAY(
                        SELECT column_name || '|' || data_type || '|' || udt_name
                            || '|' || COALESCE(character_maximum_length::text, '')
                            || '|' || is_nullable
                        FROM information_schema.columns
                        WHERE table_schema = 'iam' AND table_name = 'access_roles'
                        ORDER BY ordinal_position
                    ) AS columns,
                    ARRAY(
                        SELECT conname
                        FROM pg_constraint
                        WHERE conrelid = to_regclass('iam.access_roles')
                        ORDER BY conname
                    ) AS constraints,
                    ARRAY(
                        SELECT index_class.relname
                        FROM pg_index AS index_state
                        JOIN pg_class AS index_class ON index_class.oid = index_state.indexrelid
                        WHERE index_state.indrelid = to_regclass('iam.access_roles')
                          AND NOT EXISTS (
                              SELECT 1 FROM pg_constraint
                              WHERE conindid = index_state.indexrelid
                          )
                        ORDER BY index_class.relname
                    ) AS indexes,
                    ARRAY(
                        SELECT polname FROM pg_policy
                        WHERE polrelid = to_regclass('iam.access_roles')
                        ORDER BY polname
                    ) AS policies,
                    COALESCE((
                        SELECT relrowsecurity AND relforcerowsecurity
                        FROM pg_class WHERE oid = to_regclass('iam.access_roles')
                    ), FALSE) AS force_rls
                """
            )
        )
        .mappings()
        .one()
    )
    return (
        tuple(sorted(row["columns"])) == tuple(sorted(_CANONICAL_COLUMNS))
        and tuple(row["constraints"]) == _CANONICAL_CONSTRAINTS
        and tuple(row["indexes"]) == _CANONICAL_INDEXES
        and tuple(row["policies"]) == _CANONICAL_POLICIES
        and bool(row["force_rls"])
    )


def upgrade() -> None:
    existing_objects = _existing_object_count()
    if existing_objects in {EXPECTED_OBJECT_COUNT - 1, EXPECTED_OBJECT_COUNT} and (
        _is_canonical_schema()
    ):
        return
    if existing_objects:
        raise RuntimeError("The Workspace access-role schema is only partially present.")
    op.create_table(
        "access_roles",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("role_key", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("clearance", sa.Integer(), nullable=False),
        sa.Column("groups", postgresql.JSONB(none_as_null=True), nullable=False),
        sa.Column("allowed_actions", postgresql.JSONB(none_as_null=True), nullable=False),
        sa.Column("denied_actions", postgresql.JSONB(none_as_null=True), nullable=False),
        sa.Column("allowed_system_ids", postgresql.JSONB(none_as_null=True), nullable=False),
        sa.Column("allowed_domain_ids", postgresql.JSONB(none_as_null=True), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
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
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "role_key ~ '^[a-z][a-z0-9-]{1,79}$'",
            name="ck_access_roles_role_key_shape",
        ),
        sa.CheckConstraint(
            "clearance BETWEEN 0 AND 3",
            name="ck_access_roles_clearance_range",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            name="fk_access_roles_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "updated_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_access_roles_updater",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_access_roles"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_access_roles_workspace_id_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "role_key",
            name="uq_access_roles_workspace_id_role_key",
        ),
        schema="iam",
    )
    op.create_index(
        "ix_access_roles_workspace_active_name",
        "access_roles",
        ["workspace_id", "active", "name"],
        unique=False,
        schema="iam",
    )
    op.execute("ALTER TABLE iam.access_roles ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE iam.access_roles FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY workspace_isolation ON iam.access_roles "
        f"USING (workspace_id = {RLS_SETTING}) "
        f"WITH CHECK (workspace_id = {RLS_SETTING})"
    )
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
                GRANT SELECT, INSERT, UPDATE ON iam.access_roles TO datariver_app;
            END IF;
        END
        $datariver$;
        """
    )


def downgrade() -> None:
    # Compatibility bridge: regenerated 0001 owns the canonical access-role shape.
    pass
