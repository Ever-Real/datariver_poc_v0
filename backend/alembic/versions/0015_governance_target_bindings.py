"""Persist immutable governance target bindings.

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "change_request_items",
        sa.Column("target_asset_id", sa.Uuid(), nullable=True),
        schema="governance",
    )
    op.add_column(
        "change_request_items",
        sa.Column("target_asset_type", sa.String(length=100), nullable=True),
        schema="governance",
    )
    op.add_column(
        "change_request_items",
        sa.Column("target_system_id", sa.Uuid(), nullable=True),
        schema="governance",
    )
    op.add_column(
        "change_request_items",
        sa.Column("target_domain_id", sa.Uuid(), nullable=True),
        schema="governance",
    )
    op.add_column(
        "change_request_items",
        sa.Column("target_owner_department_id", sa.Uuid(), nullable=True),
        schema="governance",
    )
    op.add_column(
        "change_request_items",
        sa.Column("target_classification", sa.Integer(), nullable=True),
        schema="governance",
    )
    op.add_column(
        "change_request_items",
        sa.Column("target_lifecycle", sa.String(length=50), nullable=True),
        schema="governance",
    )
    op.add_column(
        "change_request_items",
        sa.Column("target_source_version", sa.String(length=255), nullable=True),
        schema="governance",
    )
    op.add_column(
        "change_request_items",
        sa.Column("target_observed_at", sa.DateTime(timezone=True), nullable=True),
        schema="governance",
    )
    op.add_column(
        "change_request_items",
        sa.Column("target_binding_hash", sa.String(length=64), nullable=True),
        schema="governance",
    )
    op.create_check_constraint(
        "ck_change_request_items_target_binding_shape",
        "change_request_items",
        "(target_asset_id IS NULL AND target_asset_type IS NULL "
        "AND target_system_id IS NULL AND target_domain_id IS NULL "
        "AND target_owner_department_id IS NULL AND target_classification IS NULL "
        "AND target_lifecycle IS NULL AND target_source_version IS NULL "
        "AND target_observed_at IS NULL AND target_binding_hash IS NULL) OR "
        "(target_asset_id IS NOT NULL AND target_asset_type IS NOT NULL "
        "AND target_classification IS NOT NULL AND target_lifecycle IS NOT NULL "
        "AND target_source_version IS NOT NULL AND target_observed_at IS NOT NULL "
        "AND target_binding_hash IS NOT NULL)",
        schema="governance",
    )
    op.create_check_constraint(
        "ck_change_request_items_target_classification_range",
        "change_request_items",
        "target_classification IS NULL OR target_classification BETWEEN 0 AND 3",
        schema="governance",
    )
    op.create_check_constraint(
        "ck_change_request_items_target_binding_hash_sha256",
        "change_request_items",
        "target_binding_hash IS NULL OR target_binding_hash ~ '^[0-9a-f]{64}$'",
        schema="governance",
    )
    op.create_index(
        "ix_change_items_target",
        "change_request_items",
        ["workspace_id", "target_asset_id", "aspect_name"],
        unique=False,
        schema="governance",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_change_items_target",
        table_name="change_request_items",
        schema="governance",
    )
    op.drop_constraint(
        "ck_change_request_items_target_binding_hash_sha256",
        "change_request_items",
        schema="governance",
        type_="check",
    )
    op.drop_constraint(
        "ck_change_request_items_target_classification_range",
        "change_request_items",
        schema="governance",
        type_="check",
    )
    op.drop_constraint(
        "ck_change_request_items_target_binding_shape",
        "change_request_items",
        schema="governance",
        type_="check",
    )
    for column in (
        "target_binding_hash",
        "target_observed_at",
        "target_source_version",
        "target_lifecycle",
        "target_classification",
        "target_owner_department_id",
        "target_domain_id",
        "target_system_id",
        "target_asset_type",
        "target_asset_id",
    ):
        op.drop_column("change_request_items", column, schema="governance")
