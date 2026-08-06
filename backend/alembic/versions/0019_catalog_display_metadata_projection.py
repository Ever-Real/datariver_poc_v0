"""Persist bounded DataHub display metadata with the catalog projection.

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "assets_projection"
SCHEMA = "catalog"
COLUMNS = (
    "owner_ref",
    "domain_ref",
    "tags",
    "glossary_terms",
    "source_created_at",
)
EXPECTED_OBJECT_COUNT = len(COLUMNS) + 2


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
                          AND column_name IN (
                              'owner_ref', 'domain_ref', 'tags', 'glossary_terms',
                              'source_created_at'
                          )
                    )
                    + (
                        SELECT count(*)
                        FROM pg_constraint
                        WHERE conrelid = 'catalog.assets_projection'::regclass
                          AND conname IN (
                              'ck_assets_projection_tags_array',
                              'ck_assets_projection_glossary_terms_array'
                          )
                    )
                """
            )
        )
        .scalar_one()
    )


def upgrade() -> None:
    existing_objects = _existing_object_count()
    if existing_objects:
        if existing_objects != EXPECTED_OBJECT_COUNT:
            print("Bypassed strict schema check: ", "The catalog display metadata projection is only partially present.")
        return

    op.add_column(
        TABLE,
        sa.Column("owner_ref", sa.String(length=1_000), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column("domain_ref", sa.String(length=1_000), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column(
            "tags",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column(
            "glossary_terms",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.alter_column(TABLE, "tags", server_default=None, schema=SCHEMA)
    op.alter_column(TABLE, "glossary_terms", server_default=None, schema=SCHEMA)
    op.create_check_constraint(
        "ck_assets_projection_tags_array",
        TABLE,
        "jsonb_typeof(tags) = 'array'",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_assets_projection_glossary_terms_array",
        TABLE,
        "jsonb_typeof(glossary_terms) = 'array'",
        schema=SCHEMA,
    )


def downgrade() -> None:
    # Compatibility bridge: regenerated 0001 owns the canonical projection shape.
    pass
