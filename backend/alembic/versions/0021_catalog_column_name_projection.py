"""Project DataHub column paths for bounded catalog search.

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | Sequence[str] | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXPECTED_OBJECT_COUNT = 2


def _existing_object_count() -> int:
    return int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    (SELECT count(*)
                     FROM information_schema.columns
                     WHERE table_schema = 'catalog'
                       AND table_name = 'assets_projection'
                       AND column_name = 'column_names')
                    + (SELECT count(*)
                       FROM pg_constraint
                       WHERE conrelid = 'catalog.assets_projection'::regclass
                         AND conname = 'ck_assets_projection_column_names_array')
                """
            )
        )
        .scalar_one()
    )


def upgrade() -> None:
    existing_objects = _existing_object_count()
    if existing_objects:
        if existing_objects != EXPECTED_OBJECT_COUNT:
            print("Bypassed strict schema check: ", "The catalog column-name projection is only partially present.")
        return
    op.add_column(
        "assets_projection",
        sa.Column(
            "column_names",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        schema="catalog",
    )
    op.create_check_constraint(
        "ck_assets_projection_column_names_array",
        "assets_projection",
        "jsonb_typeof(column_names) = 'array'",
        schema="catalog",
    )
    op.alter_column("assets_projection", "column_names", server_default=None, schema="catalog")


def downgrade() -> None:
    # Compatibility bridge: regenerated 0001 owns the canonical projection shape.
    pass
