"""Bind CR workflow systems and immutable role authority evidence.

Revision ID: 0033
Revises: 0032
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033"
down_revision: str | Sequence[str] | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
EXPECTED_OBJECT_COUNT = 4


def _existing_object_count() -> int:
    return int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    (SELECT count(*) FROM information_schema.columns
                     WHERE table_schema = 'governance'
                       AND table_name = 'change_request_items'
                       AND column_name = 'routing_system_id')
                    + (SELECT count(*) FROM information_schema.columns
                       WHERE table_schema = 'governance' AND table_name = 'approvals'
                         AND column_name = 'authority_snapshot')
                    + (SELECT count(*) FROM pg_constraint
                       WHERE conrelid = to_regclass('governance.change_request_items')
                         AND conname = 'fk_change_items_routing_system')
                    + (SELECT count(*) FROM pg_constraint
                       WHERE conrelid = to_regclass('governance.approvals')
                         AND conname = 'ck_approvals_authority_array')
                """
            )
        )
        .scalar_one()
    )


def upgrade() -> None:
    existing_objects = _existing_object_count()
    if existing_objects:
        if existing_objects != EXPECTED_OBJECT_COUNT:
            raise RuntimeError("The CR role-authority schema is only partially present.")
        return
    op.add_column(
        "change_request_items",
        sa.Column("routing_system_id", sa.Uuid(), nullable=True),
        schema="governance",
    )
    op.execute(
        """
        UPDATE governance.change_request_items
        SET routing_system_id = target_system_id
        WHERE target_system_id IS NOT NULL
        """
    )
    op.create_foreign_key(
        "fk_change_items_routing_system",
        "change_request_items",
        "data_systems",
        ["workspace_id", "routing_system_id"],
        ["workspace_id", "id"],
        source_schema="governance",
        referent_schema="platform",
        ondelete="RESTRICT",
    )
    op.add_column(
        "approvals",
        sa.Column(
            "authority_snapshot",
            postgresql.JSONB(none_as_null=True),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        schema="governance",
    )
    op.create_check_constraint(
        "authority_array",
        "approvals",
        "jsonb_typeof(authority_snapshot) = 'array'",
        schema="governance",
    )
    op.alter_column(
        "approvals",
        "authority_snapshot",
        server_default=None,
        schema="governance",
    )


def downgrade() -> None:
    # Compatibility bridge: regenerated 0001 owns the canonical CR authority shape.
    pass
