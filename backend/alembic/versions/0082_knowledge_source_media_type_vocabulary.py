"""Align Knowledge source snapshots with the governed document MIME vocabulary.

Revision ID: 0082
Revises: 0081
Create Date: 2026-07-31
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0082"
down_revision: str | Sequence[str] | None = "0081"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# This immutable migration vocabulary must remain an exact snapshot of
# domain.knowledge_pipeline.KNOWLEDGE_SOURCE_MEDIA_TYPES at revision 0082.
_SOURCE_MEDIA_TYPES = (
    "application/json",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/xhtml+xml",
    "application/xml",
    "text/csv",
    "text/html",
    "text/json",
    "text/plain",
    "text/xml",
)


def _media_type_check() -> str:
    return (
        "media_type IN (" + ", ".join(f"'{media_type}'" for media_type in _SOURCE_MEDIA_TYPES) + ")"
    )


def upgrade() -> None:
    op.drop_constraint(
        "ck_source_snapshots_pdf_media_type",
        "source_snapshots",
        schema="knowledge",
        type_="check",
    )
    op.create_check_constraint(
        "ck_source_snapshots_media_type_vocabulary",
        "source_snapshots",
        _media_type_check(),
        schema="knowledge",
    )


def downgrade() -> None:
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM knowledge.source_snapshots
                WHERE media_type <> 'application/pdf'
            ) THEN
                RAISE EXCEPTION
                    '0082 downgrade requires explicit reconciliation of non-PDF source snapshots';
            END IF;
        END
        $datariver$;
        """
    )
    op.drop_constraint(
        "ck_source_snapshots_media_type_vocabulary",
        "source_snapshots",
        schema="knowledge",
        type_="check",
    )
    op.create_check_constraint(
        "ck_source_snapshots_pdf_media_type",
        "source_snapshots",
        "media_type = 'application/pdf'",
        schema="knowledge",
    )
