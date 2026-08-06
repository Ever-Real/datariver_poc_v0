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


def upgrade() -> None:
    table_exists = op.get_bind().execute(
        sa.text("SELECT (to_regclass('iam.access_roles') IS NOT NULL)::int")
    ).scalar_one()
    
    if table_exists:
        return
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
