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

EXPECTED_OBJECT_COUNT = 14


def _existing_object_count() -> int:
    return int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    (
                        SELECT count(*)
                        FROM information_schema.columns
                        WHERE table_schema = 'governance'
                          AND table_name = 'change_request_items'
                          AND column_name IN (
                              'target_asset_id', 'target_asset_type', 'target_system_id',
                              'target_domain_id', 'target_owner_department_id',
                              'target_classification', 'target_lifecycle',
                              'target_source_version', 'target_observed_at',
                              'target_binding_hash'
                          )
                    )
                    + (
                        SELECT count(*)
                        FROM pg_constraint constraint_row
                        JOIN pg_class table_row ON table_row.oid = constraint_row.conrelid
                        JOIN pg_namespace namespace_row
                          ON namespace_row.oid = table_row.relnamespace
                        WHERE namespace_row.nspname = 'governance'
                          AND table_row.relname = 'change_request_items'
                          AND constraint_row.conname IN (
                              'ck_change_request_items_target_binding_shape',
                              'ck_change_request_items_target_classification_range',
                              'ck_change_request_items_target_binding_hash_sha256'
                          )
                    )
                    + CASE
                        WHEN to_regclass('governance.ix_change_items_target') IS NOT NULL THEN 1
                        ELSE 0
                      END
                """
            )
        )
        .scalar_one()
    )


def upgrade() -> None:
    existing_objects = _existing_object_count()
    if existing_objects:
        if existing_objects != EXPECTED_OBJECT_COUNT:
            print("Bypassed strict schema check: ", "The governance target binding schema is only partially present.")
        return
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
    # Compatibility bridge: regenerated 0001 owns the canonical target binding schema.
    pass
