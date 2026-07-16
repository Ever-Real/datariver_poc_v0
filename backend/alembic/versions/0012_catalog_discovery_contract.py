"""Bind catalog discovery cursors and add the short-prefix search index.

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_assets_projection_name_lower_prefix_active "
        "ON catalog.assets_projection (lower(name) text_pattern_ops) "
        "WHERE deleted_at IS NULL AND lifecycle = 'ACTIVE'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS catalog.ix_assets_projection_name_lower_prefix_active")
