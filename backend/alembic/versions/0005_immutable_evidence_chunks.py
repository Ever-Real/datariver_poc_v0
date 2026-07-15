"""Persist immutable, authorization-scoped assistant evidence chunks.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The regenerated 0001 contains the current clean-clone schema. This bridge only fills the
    # immutable chunk fields for development databases that already reached revision 0004.
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'assistant'
                  AND table_name = 'evidence_citations'
                  AND column_name = 'excerpt_hash'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'assistant'
                  AND table_name = 'evidence_citations'
                  AND column_name = 'content_hash'
            ) THEN
                ALTER TABLE assistant.evidence_citations
                    RENAME COLUMN excerpt_hash TO content_hash;
            END IF;
        END
        $datariver$
        """
    )
    op.execute(
        """
        ALTER TABLE assistant.evidence_citations
            ADD COLUMN IF NOT EXISTS chunk_id uuid,
            ADD COLUMN IF NOT EXISTS classification integer,
            ADD COLUMN IF NOT EXISTS system_id uuid,
            ADD COLUMN IF NOT EXISTS domain_id uuid,
            ADD COLUMN IF NOT EXISTS owner_department_id uuid,
            ADD COLUMN IF NOT EXISTS effective_from timestamptz,
            ADD COLUMN IF NOT EXISTS effective_until timestamptz,
            ADD COLUMN IF NOT EXISTS extraction_method varchar(100)
        """
    )
    op.execute(
        """
        UPDATE assistant.evidence_citations AS citation
        SET chunk_id = COALESCE(citation.chunk_id, citation.id),
            classification = COALESCE(citation.classification, 3),
            effective_from = COALESCE(citation.effective_from, run.started_at),
            extraction_method = COALESCE(
                citation.extraction_method,
                'LEGACY_CITATION_V1'
            )
        FROM assistant.assistant_runs AS run
        WHERE run.workspace_id = citation.workspace_id
          AND run.id = citation.run_id
          AND (
              citation.chunk_id IS NULL
              OR citation.classification IS NULL
              OR citation.effective_from IS NULL
              OR citation.extraction_method IS NULL
          )
        """
    )
    # If an abnormal legacy database has neither excerpt_hash nor content_hash this statement
    # intentionally fails instead of inventing a digest that did not bind the cited content.
    op.execute(
        """
        ALTER TABLE assistant.evidence_citations
            ALTER COLUMN chunk_id SET NOT NULL,
            ALTER COLUMN classification SET NOT NULL,
            ALTER COLUMN content_hash SET NOT NULL,
            ALTER COLUMN effective_from SET NOT NULL,
            ALTER COLUMN extraction_method SET NOT NULL
        """
    )
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'assistant.evidence_citations'::regclass
                  AND conname = 'ck_evidence_citations_classification_range'
            ) THEN
                ALTER TABLE assistant.evidence_citations
                    ADD CONSTRAINT ck_evidence_citations_classification_range
                    CHECK (classification >= 0 AND classification <= 3);
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'assistant.evidence_citations'::regclass
                  AND conname = 'ck_evidence_citations_effective_window'
            ) THEN
                ALTER TABLE assistant.evidence_citations
                    ADD CONSTRAINT ck_evidence_citations_effective_window
                    CHECK (effective_until IS NULL OR effective_until >= effective_from);
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'assistant.evidence_citations'::regclass
                  AND conname = 'ck_evidence_citations_content_hash_sha256'
            ) THEN
                ALTER TABLE assistant.evidence_citations
                    ADD CONSTRAINT ck_evidence_citations_content_hash_sha256
                    CHECK (content_hash ~ '^[0-9a-f]{64}$');
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'assistant.evidence_citations'::regclass
                  AND conname = 'ck_evidence_citations_rank_positive'
            ) THEN
                ALTER TABLE assistant.evidence_citations
                    ADD CONSTRAINT ck_evidence_citations_rank_positive CHECK (rank > 0);
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'assistant.evidence_citations'::regclass
                  AND conname = 'uq_evidence_citations_workspace_id_run_id_chunk_id'
            ) THEN
                ALTER TABLE assistant.evidence_citations
                    ADD CONSTRAINT uq_evidence_citations_workspace_id_run_id_chunk_id
                    UNIQUE (workspace_id, run_id, chunk_id);
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'assistant.evidence_citations'::regclass
                  AND conname = 'uq_evidence_citations_workspace_id_run_id_rank'
            ) THEN
                ALTER TABLE assistant.evidence_citations
                    ADD CONSTRAINT uq_evidence_citations_workspace_id_run_id_rank
                    UNIQUE (workspace_id, run_id, rank);
            END IF;
        END
        $datariver$
        """
    )


def downgrade() -> None:
    # Compatibility marker only. The regenerated 0001 contains the immutable chunk schema, so
    # removing these fields here would make clean and upgraded paths diverge at revision 0004.
    pass
