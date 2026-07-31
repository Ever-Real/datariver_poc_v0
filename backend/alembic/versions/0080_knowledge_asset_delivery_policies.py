"""Add governed Knowledge Asset API and Chat delivery policies.

Revision ID: 0080
Revises: 0079
Create Date: 2026-07-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0080"
down_revision: str | Sequence[str] | None = "0079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "delivery_policies",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("graph_id", sa.Uuid(), nullable=False),
        sa.Column("api_enabled", sa.Boolean(), nullable=False),
        sa.Column("chat_enabled", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column(
            "match_any_terms",
            sa.JSON().with_variant(postgresql.JSONB(none_as_null=True), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "match_all_terms",
            sa.JSON().with_variant(postgresql.JSONB(none_as_null=True), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "excluded_terms",
            sa.JSON().with_variant(postgresql.JSONB(none_as_null=True), "postgresql"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
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
            "priority BETWEEN 0 AND 1000",
            name=op.f("ck_delivery_policies_priority_range"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(match_any_terms) = 'array' "
            "AND jsonb_typeof(match_all_terms) = 'array' "
            "AND jsonb_typeof(excluded_terms) = 'array' "
            "AND jsonb_array_length(match_any_terms) <= 50 "
            "AND jsonb_array_length(match_all_terms) <= 50 "
            "AND jsonb_array_length(excluded_terms) <= 50",
            name=op.f("ck_delivery_policies_route_terms_arrays"),
        ),
        sa.CheckConstraint(
            "NOT chat_enabled OR "
            "jsonb_array_length(match_any_terms) + jsonb_array_length(match_all_terms) > 0",
            name=op.f("ck_delivery_policies_chat_route_has_positive_term"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id"],
            ["knowledge.graphs.workspace_id", "knowledge.graphs.id"],
            name=op.f("fk_delivery_policies_workspace_id_graph_id_graphs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "created_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name=op.f("fk_delivery_policies_workspace_id_created_by_workspace_memberships"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "updated_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name=op.f("fk_delivery_policies_workspace_id_updated_by_workspace_memberships"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_delivery_policies")),
        sa.UniqueConstraint(
            "workspace_id",
            "graph_id",
            name=op.f("uq_delivery_policies_workspace_id_graph_id"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name=op.f("uq_delivery_policies_workspace_id_id"),
        ),
        schema="knowledge",
    )
    op.create_index(
        "ix_delivery_policies_chat_match",
        "delivery_policies",
        ["workspace_id", "chat_enabled", "priority", "graph_id"],
        schema="knowledge",
    )
    op.execute("ALTER TABLE knowledge.delivery_policies ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE knowledge.delivery_policies FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY workspace_isolation ON knowledge.delivery_policies
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
    op.execute("GRANT SELECT, INSERT ON knowledge.delivery_policies TO datariver_app")
    op.execute(
        "GRANT UPDATE (api_enabled, chat_enabled, priority, match_any_terms, "
        "match_all_terms, excluded_terms, updated_by, updated_at, version) "
        "ON knowledge.delivery_policies TO datariver_app"
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM knowledge.delivery_policies) THEN
                RAISE EXCEPTION
                    '0080 downgrade refused: Knowledge delivery policy evidence exists';
            END IF;
        END
        $$;
        """
    )
    op.drop_table("delivery_policies", schema="knowledge")
