"""Add canonical pgvector embeddings for Governance Document chunks.

Revision ID: 0075
Revises: 0074
Create Date: 2026-07-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR

revision: str = "0075"
down_revision: str | Sequence[str] | None = "0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "embedding_vector" in [c["name"] for c in sa.inspect(op.get_bind()).get_columns("document_knowledge_chunks", schema="governance")]: return
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column(
        "document_knowledge_chunks",
        sa.Column("embedding_vector", VECTOR(), nullable=True),
        schema="governance",
    )
    op.execute(
        "ALTER TABLE governance.document_knowledge_chunks "
        "DISABLE TRIGGER reject_document_chunk_mutation"
    )
    op.execute(
        "UPDATE governance.document_knowledge_chunks "
        "SET embedding_vector = embedding::text::vector"
    )
    op.execute(
        "ALTER TABLE governance.document_knowledge_chunks "
        "ENABLE TRIGGER reject_document_chunk_mutation"
    )
    op.alter_column(
        "document_knowledge_chunks",
        "embedding_vector",
        existing_type=VECTOR(),
        nullable=False,
        schema="governance",
    )
    op.create_check_constraint(
        "ck_document_knowledge_chunks_embedding_vector_dimension_matches",
        "document_knowledge_chunks",
        "vector_dims(embedding_vector) = embedding_dimension",
        schema="governance",
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM governance.document_knowledge_chunks
            ) THEN
                RAISE EXCEPTION
                    'Refusing to remove pgvector from non-empty Governance Document evidence';
            END IF;
        END
        $$
        """
    )
    op.drop_constraint(
        "ck_document_knowledge_chunks_embedding_vector_dimension_matches",
        "document_knowledge_chunks",
        schema="governance",
        type_="check",
    )
    op.drop_column(
        "document_knowledge_chunks",
        "embedding_vector",
        schema="governance",
    )
