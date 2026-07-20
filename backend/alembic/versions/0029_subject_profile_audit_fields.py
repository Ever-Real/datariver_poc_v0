"""Persist IdP-sourced user profile and ordinary access audit fields.

Revision ID: 0029
Revises: 0028
Create Date: 2026-07-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0029"
down_revision: str | Sequence[str] | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Compatibility bridge: regenerated 0001 owns these columns on a clean
    # install, while an earlier populated head receives them incrementally.
    op.execute("ALTER TABLE iam.subjects ADD COLUMN IF NOT EXISTS email varchar(320)")
    op.execute("ALTER TABLE iam.subjects ADD COLUMN IF NOT EXISTS last_login_at timestamptz")
    op.execute("ALTER TABLE iam.subjects ADD COLUMN IF NOT EXISTS last_login_ip varchar(64)")
    op.execute("GRANT UPDATE (email, last_login_at, last_login_ip) ON iam.subjects TO datariver_app")


def downgrade() -> None:
    # Do not delete ordinary audit evidence during a downgrade.
    pass
