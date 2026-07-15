"""Allow the API role to verify the packaged Alembic revision.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
                GRANT USAGE ON SCHEMA public TO datariver_app;
                GRANT SELECT ON public.alembic_version TO datariver_app;
            END IF;
        END
        $datariver$
        """
    )


def downgrade() -> None:
    # Compatibility marker only. The regenerated 0001 contains this narrow readiness grant, so
    # revoking it here would make clean and upgraded databases diverge at revision 0003.
    pass
