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


def upgrade() -> None:
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
    op.drop_constraint(
        "ck_assets_projection_column_names_array",
        "assets_projection",
        schema="catalog",
        type_="check",
    )
    op.drop_column("assets_projection", "column_names", schema="catalog")
