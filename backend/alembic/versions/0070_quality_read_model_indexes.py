"""Add bounded Quality read-model indexes.

Revision ID: 0070
Revises: 0069
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0070"
down_revision: str | None = "0069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_quality_rule_sets_list",
        "rule_sets",
        [
            "workspace_id",
            sa.literal_column("created_at DESC"),
            sa.literal_column("id DESC"),
        ],
        schema="quality",
     if_not_exists=True)
    op.create_index("ix_quality_validation_runs_list",
        "validation_runs",
        [
            "workspace_id",
            sa.literal_column("created_at DESC"),
            sa.literal_column("id DESC"),
        ],
        schema="quality",
     if_not_exists=True)
    op.create_index("ix_quality_expectation_results_issues",
        "expectation_results",
        [
            "workspace_id",
            sa.literal_column("occurred_at DESC"),
            sa.literal_column("id DESC"),
        ],
        schema="quality",
        postgresql_where=sa.text("outcome IN ('ADVISORY_FAIL','BLOCKING_FAIL')"),
     if_not_exists=True)


def downgrade() -> None:
    op.drop_index(
        "ix_quality_expectation_results_issues",
        table_name="expectation_results",
        schema="quality",
    )
    op.drop_index(
        "ix_quality_validation_runs_list",
        table_name="validation_runs",
        schema="quality",
    )
    op.drop_index(
        "ix_quality_rule_sets_list",
        table_name="rule_sets",
        schema="quality",
    )
