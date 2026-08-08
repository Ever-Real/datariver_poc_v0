import sqlalchemy as sa
"""Grant the API its RLS-scoped Quality profile read capability.

Revision ID: 0073
Revises: 0072
Create Date: 2026-07-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0073"
down_revision: str | Sequence[str] | None = "0072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "quality.profile.read" in op.get_bind().execute(sa.text("SELECT allowed_actions FROM iam.access_roles WHERE role_key = 'canonical-admin'")).scalar(): return
    op.execute("GRANT SELECT ON catalog.asset_profile_snapshots TO datariver_app")
    op.execute("GRANT SELECT ON catalog.column_profile_metrics TO datariver_app")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON catalog.column_profile_metrics FROM datariver_app")
    op.execute("REVOKE SELECT ON catalog.asset_profile_snapshots FROM datariver_app")
