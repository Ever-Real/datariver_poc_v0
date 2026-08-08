"""Add reusable Quality common Rule templates and asset mappings.

Revision ID: 0074
Revises: 0073
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0074"
down_revision: str | Sequence[str] | None = "0073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("common_rule_templates", schema="quality"): return
    op.create_table(
        "common_rule_templates",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
            "description IS NULL OR char_length(description) <= 1000",
            name=op.f("ck_common_rule_templates_description_bounded"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(name)) BETWEEN 1 AND 100",
            name=op.f("ck_common_rule_templates_name_bounded"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(rules) = 'array'", name=op.f("ck_common_rule_templates_rules_array")
        ),
        sa.CheckConstraint(
            "jsonb_array_length(rules) BETWEEN 1 AND 100",
            name=op.f("ck_common_rule_templates_rules_bounded"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "created_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_quality_common_rule_templates_creator",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            name=op.f("fk_common_rule_templates_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_common_rule_templates")),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_quality_common_rule_templates_workspace_id"
        ),
        sa.UniqueConstraint("workspace_id", "name", name="uq_quality_common_rule_templates_name"),
        schema="quality",
    )
    op.create_index("ix_quality_common_rule_templates_list",
        "common_rule_templates",
        ["workspace_id", sa.literal_column("updated_at DESC"), sa.literal_column("id DESC")],
        unique=False,
        schema="quality",
     if_not_exists=True)
    op.create_table(
        "common_rule_template_mappings",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("rule_set_id", sa.Uuid(), nullable=False),
        sa.Column("mapped_by", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["workspace_id", "asset_id"],
            ["catalog.assets_projection.workspace_id", "catalog.assets_projection.id"],
            name="fk_quality_common_rule_template_mappings_asset",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "mapped_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_quality_common_rule_template_mappings_actor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "rule_set_id"],
            ["quality.rule_sets.workspace_id", "quality.rule_sets.id"],
            name="fk_quality_common_rule_template_mappings_rule_set",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "template_id"],
            ["quality.common_rule_templates.workspace_id", "quality.common_rule_templates.id"],
            name="fk_quality_common_rule_template_mappings_template",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            name=op.f("fk_common_rule_template_mappings_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_common_rule_template_mappings")),
        sa.UniqueConstraint(
            "workspace_id", "rule_set_id", name="uq_quality_common_rule_template_mappings_rule_set"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "template_id",
            "asset_id",
            name="uq_quality_common_rule_template_mappings_asset",
        ),
        schema="quality",
    )
    op.create_index("ix_quality_common_rule_template_mappings_template",
        "common_rule_template_mappings",
        ["workspace_id", "template_id", sa.literal_column("created_at DESC")],
        unique=False,
        schema="quality",
     if_not_exists=True)
    for table in ("common_rule_templates", "common_rule_template_mappings"):
        op.execute(f"ALTER TABLE quality.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE quality.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY workspace_isolation ON quality.{table} "
            "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) "
            "WITH CHECK (workspace_id = NULLIF("
            "current_setting('app.workspace_id', true), '')::uuid)"
        )
    op.execute(
        "GRANT SELECT, INSERT ON quality.common_rule_templates, "
        "quality.common_rule_template_mappings TO datariver_app"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_quality_common_rule_template_mappings_template",
        table_name="common_rule_template_mappings",
        schema="quality",
    )
    op.drop_table("common_rule_template_mappings", schema="quality")
    op.drop_index(
        "ix_quality_common_rule_templates_list",
        table_name="common_rule_templates",
        schema="quality",
    )
    op.drop_table("common_rule_templates", schema="quality")
