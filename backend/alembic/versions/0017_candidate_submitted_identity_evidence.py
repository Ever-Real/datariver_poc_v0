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
EXPECTED_OBJECT_COUNT = 12


def _existing_object_count() -> int:
    return int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    (
                        SELECT count(*)
                        FROM information_schema.columns
                        WHERE table_schema = 'integration'
                          AND table_name = 'upload_registration_candidates'
                          AND column_name IN (
                              'evidence_version', 'submitted_platform',
                              'submitted_database_name', 'submitted_schema_name',
                              'submitted_table_name', 'submitted_identity_hash'
                          )
                    )
                    + (
                        SELECT count(*)
                        FROM pg_constraint constraint_row
                        JOIN pg_class table_row ON table_row.oid = constraint_row.conrelid
                        JOIN pg_namespace namespace_row
                          ON namespace_row.oid = table_row.relnamespace
                        WHERE namespace_row.nspname = 'integration'
                          AND table_row.relname = 'upload_registration_candidates'
                          AND (
                              constraint_row.conname IN (
                                  'ck_upload_registration_candidates_evidence_version_allowlist',
                                  'ck_upload_registration_candidates_submitted_platform_valid',
                                  'ck_upload_registration_candidates_submitted_database_name_valid',
                                  'ck_upload_registration_candidates_submitted_schema_name_valid',
                                  'ck_upload_registration_candidates_submitted_table_name_valid'
                              )
                              OR constraint_row.conname LIKE
                                  'ck_upload_registration_candidates_submitted_identity_ev_%'
                          )
                    )
                """
            )
        )
        .scalar_one()
    )


def upgrade() -> None:
    existing_objects = _existing_object_count()
    if existing_objects:
        if existing_objects != EXPECTED_OBJECT_COUNT:
            raise RuntimeError(
                "The submitted candidate identity evidence schema is only partially present."
            )
        _install_immutability_contract()
        return
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
    _install_immutability_contract()


def _install_immutability_contract() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION
            integration.reject_upload_registration_candidate_evidence_mutation()
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
        "DROP TRIGGER IF EXISTS reject_upload_registration_candidate_evidence_mutation "
        "ON integration.upload_registration_candidates"
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
    # Compatibility bridge: regenerated 0001 owns the canonical candidate evidence schema.
    pass
