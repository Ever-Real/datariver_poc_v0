"""Grant the export event consumer only its inbox receipt capability.

Revision ID: 0026
Revises: 0025
Create Date: 2026-07-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0026"
down_revision: str | Sequence[str] | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("GRANT SELECT, INSERT, UPDATE ON integration.inbox_messages TO datariver_export")


def downgrade() -> None:
    # Do not revoke an active worker's idempotency receipt capability on downgrade.
    pass
