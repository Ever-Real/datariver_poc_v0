"""Add workspace monitoring dashboard tabs.

Revision ID: 0078
Revises: 0077
Create Date: 2026-07-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0078"
down_revision: str | Sequence[str] | None = "0077"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("monitoring_dashboard_tabs", schema="platform"): return
    op.create_table(
        "monitoring_configurations",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column(
            "dashboards",
            postgresql.JSONB(astext_type=sa.Text(), none_as_null=True),
            nullable=False,
        ),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
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
        sa.CheckConstraint(
            "jsonb_typeof(dashboards) = 'array'",
            name=op.f("ck_monitoring_configurations_dashboards_array"),
        ),
        sa.CheckConstraint(
            "jsonb_array_length(dashboards) <= 8",
            name=op.f("ck_monitoring_configurations_dashboards_bounded"),
        ),
        sa.CheckConstraint(
            "payload_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_monitoring_configurations_payload_hash_sha256"),
        ),
        sa.CheckConstraint(
            "version > 0",
            name=op.f("ck_monitoring_configurations_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            name=op.f("fk_monitoring_configurations_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "updated_by"],
            [
                "iam.workspace_memberships.workspace_id",
                "iam.workspace_memberships.subject_id",
            ],
            name="fk_monitoring_configurations_updater",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            name=op.f("pk_monitoring_configurations"),
        ),
        schema="platform",
    )
    op.execute("ALTER TABLE platform.monitoring_configurations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE platform.monitoring_configurations FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY workspace_isolation ON platform.monitoring_configurations
        USING (
            workspace_id =
            NULLIF(current_setting('app.workspace_id', true), '')::uuid
        )
        WITH CHECK (
            workspace_id =
            NULLIF(current_setting('app.workspace_id', true), '')::uuid
        )
        """
    )
    op.execute("GRANT SELECT, INSERT ON platform.monitoring_configurations TO datariver_app")
    op.execute(
        "GRANT UPDATE (dashboards, payload_hash, updated_by, updated_at, version) "
        "ON platform.monitoring_configurations TO datariver_app"
    )


def downgrade() -> None:
    op.drop_table("monitoring_configurations", schema="platform")
