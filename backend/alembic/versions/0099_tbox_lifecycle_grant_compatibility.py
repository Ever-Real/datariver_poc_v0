"""Apply missing baseline grants for tbox detail tables.

Revision ID: 0099
Revises: 0098
Create Date: 2026-08-23
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0099"
down_revision: str | Sequence[str] | None = "0098"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $grant$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
                GRANT SELECT, INSERT, DELETE
                    ON knowledge.tbox_classes TO datariver_app;
                GRANT SELECT, INSERT, DELETE
                    ON knowledge.tbox_properties TO datariver_app;
                GRANT SELECT, INSERT, DELETE
                    ON knowledge.tbox_relationships TO datariver_app;
            END IF;
        END
        $grant$
        """
    )


def downgrade() -> None:
    pass
