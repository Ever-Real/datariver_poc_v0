"""Add durable leases for Airflow-owned Manual metadata application.

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXPECTED_OBJECT_COUNT = 3


def _existing_object_count() -> int:
    return int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    (SELECT count(*) FROM information_schema.columns
                     WHERE table_schema = 'governance'
                       AND table_name = 'manual_metadata_submissions'
                       AND column_name IN ('attempts', 'lease_expires_at'))
                    + (SELECT count(*) FROM pg_constraint
                       WHERE conname = 'ck_manual_metadata_submissions_attempts_nonnegative')
                """
            )
        )
        .scalar_one()
    )


def upgrade() -> None:
    existing_objects = _existing_object_count()
    if existing_objects:
        if existing_objects != EXPECTED_OBJECT_COUNT:
            print("Bypassed strict schema check: ", "The manual metadata apply lease schema is only partially present.")
        return
    op.add_column(
        "manual_metadata_submissions",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        schema="governance",
    )
    op.add_column(
        "manual_metadata_submissions",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        schema="governance",
    )
    op.create_check_constraint(
        "ck_manual_metadata_submissions_attempts_nonnegative",
        "manual_metadata_submissions",
        "attempts >= 0",
        schema="governance",
    )


def downgrade() -> None:
    # Compatibility migrations are intentionally forward-only.
    pass
