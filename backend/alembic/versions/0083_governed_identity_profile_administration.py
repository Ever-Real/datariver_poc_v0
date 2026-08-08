import sqlalchemy as sa
"""Add governed administrator identity-profile projection updates.

Revision ID: 0083
Revises: 0082
Create Date: 2026-07-31
"""

from collections.abc import Sequence

from alembic import op

from datariver.infrastructure.db.identity_profile_sql import (
    IDENTITY_PROFILE_UPDATE_FUNCTION_SQL,
    IDENTITY_PROFILE_UPDATE_SIGNATURE,
)

revision: str = "0083"
down_revision: str | Sequence[str] | None = "0082"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "iam.profile_role_assignments" in op.get_bind().execute(sa.text("SELECT 1 FROM pg_tables WHERE schemaname = 'iam' AND tablename = 'profile_role_assignments'")).scalar(): return
    op.execute(IDENTITY_PROFILE_UPDATE_FUNCTION_SQL)
    op.execute(f"REVOKE ALL ON FUNCTION {IDENTITY_PROFILE_UPDATE_SIGNATURE} FROM PUBLIC")
    op.execute(
        f"""DO $datariver$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
            GRANT EXECUTE ON FUNCTION {IDENTITY_PROFILE_UPDATE_SIGNATURE} TO datariver_app;
        END IF;
        END $datariver$"""  # noqa: S608 -- fixed signature constant, not operator input.
    )


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {IDENTITY_PROFILE_UPDATE_SIGNATURE}")
