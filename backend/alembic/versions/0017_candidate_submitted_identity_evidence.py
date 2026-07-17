"""Bind submitted hierarchy to typed BULK candidates.

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "upload_registration_candidates"
SCHEMA = "integration"
V2 = "DATASET_DESCRIPTION_CANDIDATE_V2"


def upgrade() -> None:
    # Existing 0016 evidence cannot be reconstructed from a canonical candidate row. Preserve it
    # explicitly as legacy instead of presenting current catalog hierarchy as submitted evidence.
    op.add_column(
        TABLE,
        sa.Column(
            "evidence_version",
            sa.String(length=100),
            server_default="LEGACY_V1",
            nullable=False,
        ),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column("submitted_platform", sa.String(length=100), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column("submitted_database_name", sa.String(length=255), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column("submitted_schema_name", sa.String(length=255), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column("submitted_table_name", sa.String(length=500), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column("submitted_identity_hash", sa.String(length=64), nullable=True),
        schema=SCHEMA,
    )
    op.alter_column(
        TABLE,
        "evidence_version",
        server_default=V2,
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_upload_registration_candidates_evidence_version_allowlist",
        TABLE,
        "evidence_version IN ('LEGACY_V1', 'DATASET_DESCRIPTION_CANDIDATE_V2')",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_upload_registration_candidates_submitted_identity_evidence_shape",
        TABLE,
        "(evidence_version = 'LEGACY_V1' AND submitted_platform IS NULL "
        "AND submitted_database_name IS NULL AND submitted_schema_name IS NULL "
        "AND submitted_table_name IS NULL AND submitted_identity_hash IS NULL) OR "
        "(evidence_version = 'DATASET_DESCRIPTION_CANDIDATE_V2' "
        "AND submitted_platform IS NOT NULL AND submitted_database_name IS NOT NULL "
        "AND submitted_schema_name IS NOT NULL AND submitted_table_name IS NOT NULL "
        "AND submitted_identity_hash ~ '^[0-9a-f]{64}$')",
        schema=SCHEMA,
    )
    for column, maximum in (
        ("submitted_platform", 100),
        ("submitted_database_name", 255),
        ("submitted_schema_name", 255),
        ("submitted_table_name", 500),
    ):
        op.create_check_constraint(
            f"ck_upload_registration_candidates_{column}_valid",
            TABLE,
            f"{column} IS NULL OR (char_length({column}) BETWEEN 1 AND {maximum} "
            f"AND {column} = btrim({column}))",
            schema=SCHEMA,
        )
    op.execute(
        """
        CREATE FUNCTION integration.reject_upload_registration_candidate_evidence_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY INVOKER
        SET search_path = pg_catalog
        AS $function$
        BEGIN
            IF TG_OP = 'INSERT' AND NEW.evidence_version <> 'DATASET_DESCRIPTION_CANDIDATE_V2' THEN
                RAISE EXCEPTION 'new upload registration candidates require V2 evidence'
                    USING ERRCODE = '23514';
            END IF;
            IF TG_OP IN ('UPDATE', 'DELETE') THEN
                RAISE EXCEPTION 'upload registration candidate evidence is immutable'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END
        $function$
        """
    )
    op.execute(
        """
        CREATE TRIGGER reject_upload_registration_candidate_evidence_mutation
        BEFORE INSERT OR UPDATE OR DELETE ON integration.upload_registration_candidates
        FOR EACH ROW
        EXECUTE FUNCTION integration.reject_upload_registration_candidate_evidence_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $guard$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM integration.upload_registration_candidates
                WHERE evidence_version = 'DATASET_DESCRIPTION_CANDIDATE_V2'
            ) THEN
                RAISE EXCEPTION
                    '0017 downgrade refused: V2 submitted candidate identity evidence exists';
            END IF;
        END
        $guard$
        """
    )
    op.execute(
        "DROP TRIGGER reject_upload_registration_candidate_evidence_mutation "
        "ON integration.upload_registration_candidates"
    )
    op.execute("DROP FUNCTION integration.reject_upload_registration_candidate_evidence_mutation()")
    for column in (
        "submitted_table_name",
        "submitted_schema_name",
        "submitted_database_name",
        "submitted_platform",
    ):
        op.drop_constraint(
            f"ck_upload_registration_candidates_{column}_valid",
            TABLE,
            schema=SCHEMA,
            type_="check",
        )
    op.drop_constraint(
        "ck_upload_registration_candidates_submitted_identity_evidence_shape",
        TABLE,
        schema=SCHEMA,
        type_="check",
    )
    op.drop_constraint(
        "ck_upload_registration_candidates_evidence_version_allowlist",
        TABLE,
        schema=SCHEMA,
        type_="check",
    )
    for column in (
        "submitted_identity_hash",
        "submitted_table_name",
        "submitted_schema_name",
        "submitted_database_name",
        "submitted_platform",
        "evidence_version",
    ):
        op.drop_column(TABLE, column, schema=SCHEMA)
