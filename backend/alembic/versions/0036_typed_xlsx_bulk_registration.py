"""Add the governed XLSX BULK profile and API-owned preparation publication grants.

Revision ID: 0036
Revises: 0035
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: str | Sequence[str] | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
EXPECTED_OBJECT_COUNT = 3


def _existing_object_count() -> int:
    return int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT count(*)
                FROM pg_constraint
                WHERE conname IN (
                    'ck_object_manifests_content_profile_allowlist',
                    'ck_upload_preparation_jobs_typed_profile_allowlist',
                    'ck_upload_preparation_receipts_typed_profile_allowlist'
                )
                  AND pg_get_constraintdef(oid) LIKE '%DATASET_DESCRIPTION_XLSX_V1%'
                """
            )
        )
        .scalar_one()
    )


def _install_security_contract() -> None:
    op.execute(
        """DO $datariver$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
            GRANT UPDATE (
                state, lease_token, lease_until, attempts, rows_processed,
                total_rows, last_error_code, version, updated_at
            ) ON integration.upload_preparation_jobs TO datariver_app;
            GRANT INSERT ON integration.upload_preparation_receipts TO datariver_app;
            GRANT INSERT ON integration.upload_registration_candidates TO datariver_app;
        END IF;
        END $datariver$"""
    )


def upgrade() -> None:
    existing_objects = _existing_object_count()
    if existing_objects:
        if existing_objects != EXPECTED_OBJECT_COUNT:
            raise RuntimeError("The typed XLSX registration schema is only partially present.")
        _install_security_contract()
        return
    checks = (
        (
            "object_manifests",
            "ck_object_manifests_content_profile_allowlist",
            "content_profile IN ('FORMAT_ONLY_V1', 'DATASET_DESCRIPTION_CSV_V1', "
            "'DATASET_DESCRIPTION_XLSX_V1')",
        ),
        (
            "upload_preparation_jobs",
            "ck_upload_preparation_jobs_typed_profile_allowlist",
            "content_profile IN ('DATASET_DESCRIPTION_CSV_V1', 'DATASET_DESCRIPTION_XLSX_V1')",
        ),
        (
            "upload_preparation_receipts",
            "ck_upload_preparation_receipts_typed_profile_allowlist",
            "content_profile IN ('DATASET_DESCRIPTION_CSV_V1', 'DATASET_DESCRIPTION_XLSX_V1')",
        ),
    )
    for table_name, constraint_name, condition in checks:
        op.drop_constraint(
            op.f(constraint_name),
            table_name,
            schema="integration",
            type_="check",
        )
        op.create_check_constraint(
            op.f(constraint_name),
            table_name,
            condition,
            schema="integration",
        )
    _install_security_contract()


def downgrade() -> None:
    # Compatibility bridge: regenerated 0001 owns the canonical XLSX profile constraints.
    pass
