"""Remove destructive retention privileges until governed WORM archival is ready.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_relay') THEN
                REVOKE DELETE ON integration.outbox_events FROM datariver_relay;
                REVOKE DELETE ON integration.inbox_messages FROM datariver_relay;
            END IF;
        END
        $datariver$
        """
    )


def downgrade() -> None:
    # Restoring a destructive privilege would silently re-enable an unsafe historical path.
    pass
