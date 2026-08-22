"""Apply missing baseline grants for tbox drafts and ingestion.

Revision ID: 0098
Revises: 0097
Create Date: 2026-08-23
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0098"
down_revision: str | Sequence[str] | None = "0097"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $grant$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON knowledge.tbox_draft_blocks TO datariver_app;
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON knowledge.tbox_draft_elements TO datariver_app;
                GRANT SELECT, INSERT, UPDATE
                    ON knowledge.tbox_proposals TO datariver_app;
                GRANT SELECT, INSERT
                    ON knowledge.studio_ingestion_jobs TO datariver_app;
            END IF;
        END
        $grant$
        """
    )


def downgrade() -> None:
    pass
