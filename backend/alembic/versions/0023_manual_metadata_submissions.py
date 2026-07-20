"""Add independent Manual metadata submission receipts.

Revision ID: 0023
Revises: 0022
Create Date: 2026-07-18
"""

# ruff: noqa: S608

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: str | Sequence[str] | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_SETTING = "NULLIF(current_setting('app.workspace_id', true), '')::uuid"
# The generated initial schema owns the table, constraints, index and RLS policy.
# The per-workspace serial sequence is installed by this bridge so it is also
# available on a clean database created from regenerated ``0001``.
EXPECTED_OBJECT_COUNT = 15


def _existing_object_count() -> int:
    return int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    CASE WHEN to_regclass('governance.manual_metadata_submissions') IS NOT NULL
                        THEN 1 ELSE 0 END
                    + (SELECT count(*) FROM pg_constraint
                       WHERE conname IN (
                           'uq_assets_projection_workspace_id',
                           'uq_manual_metadata_submissions_workspace_id_id',
                           'uq_manual_metadata_submissions_workspace_id_serial_number',
                           'uq_manual_metadata_submissions_bucket_object_key',
                           'fk_manual_metadata_submissions_asset',
                           'fk_manual_metadata_submissions_requester',
                           'ck_manual_metadata_submissions_serial_number_positive',
                           'ck_manual_metadata_submissions_csv_sha256_valid',
                           'ck_manual_metadata_submissions_csv_size_bytes_positive',
                           'ck_manual_metadata_submissions_row_count_positive',
                           'ck_manual_metadata_submissions_state_vocabulary',
                           'ck_manual_metadata_submissions_payload_object'
                       ))
                    + (SELECT count(*) FROM pg_indexes
                       WHERE schemaname = 'governance'
                         AND indexname = 'ix_manual_metadata_submissions_workspace_state')
                    + (SELECT count(*) FROM pg_policies
                       WHERE schemaname = 'governance'
                         AND tablename = 'manual_metadata_submissions'
                         AND policyname = 'workspace_isolation')
                """
            )
        )
        .scalar_one()
    )


def _install_security_contract() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS governance.manual_metadata_submission_serial_seq")
    op.execute("ALTER TABLE governance.manual_metadata_submissions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE governance.manual_metadata_submissions FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        DO $datariver$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE schemaname = 'governance'
                  AND tablename = 'manual_metadata_submissions'
                  AND policyname = 'workspace_isolation'
            ) THEN
                CREATE POLICY workspace_isolation ON governance.manual_metadata_submissions
                USING (workspace_id = {RLS_SETTING})
                WITH CHECK (workspace_id = {RLS_SETTING});
            END IF;
        END
        $datariver$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION governance.reject_manual_metadata_payload_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY INVOKER
        AS $function$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'manual metadata submission history is append-only'
                    USING ERRCODE = '23514';
            END IF;
            IF OLD.workspace_id <> NEW.workspace_id
               OR OLD.asset_id <> NEW.asset_id
               OR OLD.requester_id <> NEW.requester_id
               OR OLD.external_urn <> NEW.external_urn
               OR OLD.source_version <> NEW.source_version
               OR OLD.serial_number <> NEW.serial_number
               OR OLD.payload <> NEW.payload
               OR OLD.bucket <> NEW.bucket
               OR OLD.object_key <> NEW.object_key
               OR OLD.csv_sha256 <> NEW.csv_sha256
               OR OLD.csv_size_bytes <> NEW.csv_size_bytes
               OR OLD.row_count <> NEW.row_count
               OR OLD.created_at <> NEW.created_at THEN
                RAISE EXCEPTION 'manual metadata submission evidence is immutable'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END
        $function$
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS reject_manual_metadata_payload_mutation "
        "ON governance.manual_metadata_submissions"
    )
    op.execute(
        """
        CREATE TRIGGER reject_manual_metadata_payload_mutation
        BEFORE UPDATE OR DELETE ON governance.manual_metadata_submissions
        FOR EACH ROW
        EXECUTE FUNCTION governance.reject_manual_metadata_payload_mutation()
        """
    )
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
                GRANT USAGE ON SCHEMA governance TO datariver_app;
                GRANT USAGE, SELECT ON SEQUENCE governance.manual_metadata_submission_serial_seq
                    TO datariver_app;
                GRANT SELECT, INSERT, UPDATE ON governance.manual_metadata_submissions
                    TO datariver_app;
            END IF;
        END
        $datariver$
        """
    )


def upgrade() -> None:
    existing_objects = _existing_object_count()
    if existing_objects:
        if existing_objects != EXPECTED_OBJECT_COUNT:
            raise RuntimeError("The manual metadata submission schema is only partially present.")
        _install_security_contract()
        return

    op.create_unique_constraint(
        "uq_assets_projection_workspace_id",
        "assets_projection",
        ["workspace_id", "id"],
        schema="catalog",
    )
    op.create_table(
        "manual_metadata_submissions",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("requester_id", sa.Uuid(), nullable=False),
        sa.Column("external_urn", sa.Text(), nullable=False),
        sa.Column("source_version", sa.String(length=255), nullable=False),
        sa.Column("serial_number", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(none_as_null=True), nullable=False),
        sa.Column("bucket", sa.String(length=255), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("csv_sha256", sa.String(length=64), nullable=False),
        sa.Column("csv_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(length=100)),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "serial_number > 0", name="ck_manual_metadata_submissions_serial_number_positive"
        ),
        sa.CheckConstraint(
            "csv_sha256 ~ '^[0-9a-f]{64}$'", name="ck_manual_metadata_submissions_csv_sha256_valid"
        ),
        sa.CheckConstraint(
            "csv_size_bytes > 0", name="ck_manual_metadata_submissions_csv_size_bytes_positive"
        ),
        sa.CheckConstraint(
            "row_count > 0", name="ck_manual_metadata_submissions_row_count_positive"
        ),
        sa.CheckConstraint(
            "state IN ('QUEUED', 'APPLYING', 'APPLIED', 'FAILED')",
            name="ck_manual_metadata_submissions_state_vocabulary",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name="ck_manual_metadata_submissions_payload_object"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "asset_id"],
            ["catalog.assets_projection.workspace_id", "catalog.assets_projection.id"],
            name="fk_manual_metadata_submissions_asset",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "requester_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_manual_metadata_submissions_requester",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "id"),
        sa.UniqueConstraint("workspace_id", "serial_number"),
        sa.UniqueConstraint("bucket", "object_key"),
        schema="governance",
    )
    op.create_index(
        "ix_manual_metadata_submissions_workspace_state",
        "manual_metadata_submissions",
        ["workspace_id", "state", "created_at"],
        schema="governance",
    )
    _install_security_contract()


def downgrade() -> None:
    # Compatibility migrations are intentionally forward-only.
    pass
