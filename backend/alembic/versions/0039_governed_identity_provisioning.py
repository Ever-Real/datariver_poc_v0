# ruff: noqa: S608 -- fixed, source-owned PostgreSQL function signatures only.
"""Add least-privilege workspace identity provisioning.

Revision ID: 0039
Revises: 0038
Create Date: 2026-07-22
"""

from collections.abc import Sequence

from alembic import op

from datariver.infrastructure.db.identity_provisioning_sql import (
    IDENTITY_PROVISIONING_FUNCTION_SQL,
    IDENTITY_PROVISIONING_SIGNATURE,
)

revision: str = "0039"
down_revision: str | Sequence[str] | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(IDENTITY_PROVISIONING_FUNCTION_SQL)
    op.execute(f"REVOKE ALL ON FUNCTION {IDENTITY_PROVISIONING_SIGNATURE} FROM PUBLIC")
    op.execute(
        f"""DO $datariver$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
            GRANT EXECUTE ON FUNCTION {IDENTITY_PROVISIONING_SIGNATURE} TO datariver_app;
        END IF;
        END $datariver$"""
    )


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {IDENTITY_PROVISIONING_SIGNATURE}")
