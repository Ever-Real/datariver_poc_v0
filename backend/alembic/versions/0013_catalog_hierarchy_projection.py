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

EXPECTED_OBJECT_COUNT = 3


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
                        WHERE table_schema = 'catalog'
                          AND table_name = 'assets_projection'
                          AND column_name IN ('database_name', 'schema_name')
                    )
                    + CASE
                        WHEN to_regclass('catalog.ix_assets_projection_tree_active')
                            IS NOT NULL THEN 1
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
            raise RuntimeError("The catalog hierarchy projection is only partially present.")
        return
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
    # Compatibility bridge: regenerated 0001 owns the canonical hierarchy projection.
    pass
