"""Normalize the Governance pgvector dimension constraint name.

Revision ID: 0077
Revises: 0076
Create Date: 2026-07-31
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0077"
down_revision: str | Sequence[str] | None = "0076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            source_exists boolean;
            target_exists boolean;
        BEGIN
            IF to_regclass('governance.document_knowledge_chunks') IS NULL THEN
                RAISE EXCEPTION 'Required Governance chunk table is missing';
            END IF;

            SELECT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_constraint
                WHERE conrelid =
                    'governance.document_knowledge_chunks'::regclass
                  AND conname =
                    'ck_document_knowledge_chunks_ck_document_knowledge_chun_801a'
            )
            INTO source_exists;

            SELECT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_constraint
                WHERE conrelid =
                    'governance.document_knowledge_chunks'::regclass
                  AND conname =
                    'ck_document_knowledge_chunks_embedding_vector_dimension_matches'
            )
            INTO target_exists;

            IF source_exists AND target_exists THEN
                RAISE EXCEPTION
                    'Both Governance pgvector dimension constraints exist';
            ELSIF target_exists THEN
                NULL;
            ELSIF source_exists THEN
                ALTER TABLE governance.document_knowledge_chunks
                    RENAME CONSTRAINT
                        ck_document_knowledge_chunks_ck_document_knowledge_chun_801a
                    TO
                        ck_document_knowledge_chunks_embedding_vector_dimension_matches;
            ELSE
                RAISE EXCEPTION
                    'Governance pgvector dimension constraint is missing';
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            source_exists boolean;
            target_exists boolean;
        BEGIN
            IF to_regclass('governance.document_knowledge_chunks') IS NULL THEN
                RAISE EXCEPTION 'Required Governance chunk table is missing';
            END IF;

            SELECT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_constraint
                WHERE conrelid =
                    'governance.document_knowledge_chunks'::regclass
                  AND conname =
                    'ck_document_knowledge_chunks_embedding_vector_dimension_matches'
            )
            INTO source_exists;

            SELECT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_constraint
                WHERE conrelid =
                    'governance.document_knowledge_chunks'::regclass
                  AND conname =
                    'ck_document_knowledge_chunks_ck_document_knowledge_chun_801a'
            )
            INTO target_exists;

            IF source_exists AND target_exists THEN
                RAISE EXCEPTION
                    'Both Governance pgvector dimension constraints exist';
            ELSIF target_exists THEN
                NULL;
            ELSIF source_exists THEN
                ALTER TABLE governance.document_knowledge_chunks
                    RENAME CONSTRAINT
                        ck_document_knowledge_chunks_embedding_vector_dimension_matches
                    TO
                        ck_document_knowledge_chunks_ck_document_knowledge_chun_801a;
            ELSE
                RAISE EXCEPTION
                    'Governance pgvector dimension constraint is missing';
            END IF;
        END
        $$;
        """
    )
