"""Project canonical DataHub hierarchy for permission-scoped lazy browsing.

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "assets_projection",
        sa.Column("database_name", sa.String(length=255), nullable=True),
        schema="catalog",
    )
    op.add_column(
        "assets_projection",
        sa.Column("schema_name", sa.String(length=255), nullable=True),
        schema="catalog",
    )
    op.create_index(
        "ix_assets_projection_tree_active",
        "assets_projection",
        ["workspace_id", "platform", "database_name", "schema_name", "name", "id"],
        unique=False,
        schema="catalog",
        postgresql_where=sa.text("deleted_at IS NULL AND lifecycle = 'ACTIVE'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_assets_projection_tree_active",
        table_name="assets_projection",
        schema="catalog",
    )
    op.drop_column("assets_projection", "schema_name", schema="catalog")
    op.drop_column("assets_projection", "database_name", schema="catalog")
