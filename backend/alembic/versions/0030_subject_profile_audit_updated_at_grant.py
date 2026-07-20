"""Grant API role access to the timestamp written with login-profile audit updates.

Revision ID: 0030
Revises: 0029
Create Date: 2026-07-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0030"
down_revision: str | Sequence[str] | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLAlchemy's TimestampMixin writes updated_at alongside the token-sourced
    # login audit fields. Grant only those four columns to the API role.
    op.execute(
        "GRANT UPDATE (email, last_login_at, last_login_ip, updated_at) "
        "ON iam.subjects TO datariver_app"
    )


def downgrade() -> None:
    # 0029 already grants the three token-sourced profile columns; restore its
    # exact privilege surface when moving back to that revision.
    op.execute("REVOKE UPDATE (updated_at) ON iam.subjects FROM datariver_app")
