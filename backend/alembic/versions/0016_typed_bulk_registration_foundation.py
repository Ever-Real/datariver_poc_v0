"""Add durable typed BULK registration preparation evidence.

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-17
"""

# ruff: noqa: S608

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_SETTING = "NULLIF(current_setting('app.workspace_id', true), '')::uuid"
EXPECTED_OBJECT_COUNT = 10
RLS_TABLES = frozenset(
    {
        ("integration", "upload_preparation_jobs"),
        ("integration", "upload_preparation_receipts"),
        ("integration", "upload_registration_candidates"),
        ("governance", "registration_content_bindings"),
    }
)


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
                          AND table_name = 'object_manifests'
                          AND column_name = 'content_profile'
                    )
                    + (
                        SELECT count(*)
                        FROM pg_constraint constraint_row
                        JOIN pg_class table_row ON table_row.oid = constraint_row.conrelid
                        JOIN pg_namespace namespace_row
                          ON namespace_row.oid = table_row.relnamespace
                        WHERE (
                            namespace_row.nspname = 'integration'
                            AND table_row.relname = 'object_manifests'
                            AND constraint_row.conname IN (
                                'ck_object_manifests_content_profile_allowlist',
                                'uq_object_manifests_workspace_id_id'
                            )
                        ) OR (
                            namespace_row.nspname = 'governance'
                            AND table_row.relname = 'change_request_items'
                            AND constraint_row.conname IN (
                                'uq_change_request_items_workspace_id_id',
                                'uq_change_request_item_request_identity'
                            )
                        )
                    )
                    + (
                        SELECT count(*)
                        FROM (VALUES
                            ('integration.upload_preparation_jobs'),
                            ('integration.upload_preparation_receipts'),
                            ('integration.upload_registration_candidates'),
                            ('governance.registration_content_bindings')
                        ) AS expected(relation_name)
                        WHERE to_regclass(relation_name) IS NOT NULL
                    )
                    + CASE
                        WHEN to_regclass('integration.ix_upload_preparation_jobs_claim')
                            IS NOT NULL THEN 1
                        ELSE 0
                      END
                """
            )
        )
        .scalar_one()
    )


def _enable_workspace_rls(schema: str, table: str) -> None:
    if (schema, table) not in RLS_TABLES:
        raise ValueError(f"unsupported RLS table: {schema}.{table}")
    op.execute(f"ALTER TABLE {schema}.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {schema}.{table} FORCE ROW LEVEL SECURITY")
    # Identifiers are interpolated only after validation against the closed RLS_TABLES set.
    policy_statement = f"""
        DO $datariver$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE schemaname = '{schema}'
                  AND tablename = '{table}'
                  AND policyname = 'workspace_isolation'
            ) THEN
                CREATE POLICY workspace_isolation ON {schema}.{table}
                USING (workspace_id = {RLS_SETTING})
                WITH CHECK (workspace_id = {RLS_SETTING});
            END IF;
        END
        $datariver$
        """
    op.execute(policy_statement)


def upgrade() -> None:
    existing_objects = _existing_object_count()
    if existing_objects:
        if existing_objects != EXPECTED_OBJECT_COUNT:
            raise RuntimeError("The typed BULK registration schema is only partially present.")
        _install_security_contract()
        return
    op.add_column(
        "object_manifests",
        sa.Column(
            "content_profile",
            sa.String(length=100),
            server_default="FORMAT_ONLY_V1",
            nullable=False,
        ),
        schema="integration",
    )
    op.create_check_constraint(
        "ck_object_manifests_content_profile_allowlist",
        "object_manifests",
        "content_profile IN ('FORMAT_ONLY_V1', 'DATASET_DESCRIPTION_CSV_V1')",
        schema="integration",
    )
    op.create_unique_constraint(
        "uq_object_manifests_workspace_id_id",
        "object_manifests",
        ["workspace_id", "id"],
        schema="integration",
    )
    op.create_unique_constraint(
        "uq_change_request_items_workspace_id_id",
        "change_request_items",
        ["workspace_id", "id"],
        schema="governance",
    )
    op.create_unique_constraint(
        "uq_change_request_item_request_identity",
        "change_request_items",
        ["workspace_id", "change_request_id", "id"],
        schema="governance",
    )
    op.create_table(
        "upload_preparation_jobs",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("upload_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("content_profile", sa.String(length=100), nullable=False),
        sa.Column("source_manifest_version", sa.Integer(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("rows_processed", sa.BigInteger(), nullable=False),
        sa.Column("total_rows", sa.BigInteger(), nullable=True),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
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
            "content_profile = 'DATASET_DESCRIPTION_CSV_V1'",
            name=op.f("ck_upload_preparation_jobs_typed_profile_allowlist"),
        ),
        sa.CheckConstraint(
            "state IN ('QUEUED', 'PREPARING', 'READY', 'FAILED', 'CANCELLED', 'STALE')",
            name=op.f("ck_upload_preparation_jobs_state_allowlist"),
        ),
        sa.CheckConstraint(
            "source_manifest_version > 0",
            name=op.f("ck_upload_preparation_jobs_source_manifest_version_positive"),
        ),
        sa.CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_upload_preparation_jobs_source_sha256_valid"),
        ),
        sa.CheckConstraint(
            "configuration_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_upload_preparation_jobs_configuration_hash_valid"),
        ),
        sa.CheckConstraint(
            "attempts >= 0",
            name=op.f("ck_upload_preparation_jobs_attempts_nonnegative"),
        ),
        sa.CheckConstraint(
            "rows_processed >= 0",
            name=op.f("ck_upload_preparation_jobs_rows_processed_nonnegative"),
        ),
        sa.CheckConstraint(
            "total_rows IS NULL OR total_rows >= rows_processed",
            name=op.f("ck_upload_preparation_jobs_total_rows_bounds"),
        ),
        sa.CheckConstraint(
            "(state = 'PREPARING' AND lease_token IS NOT NULL AND lease_until IS NOT NULL) "
            "OR (state <> 'PREPARING' AND lease_token IS NULL AND lease_until IS NULL)",
            name=op.f("ck_upload_preparation_jobs_lease_shape"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "upload_id"],
            ["integration.object_manifests.workspace_id", "integration.object_manifests.id"],
            name="fk_upload_prep_jobs_workspace_upload",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "requested_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_upload_prep_jobs_workspace_requester",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_upload_preparation_jobs")),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name=op.f("uq_upload_preparation_jobs_workspace_id_id"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            "upload_id",
            "source_manifest_version",
            "source_sha256",
            "content_profile",
            "configuration_hash",
            name="uq_upload_preparation_job_source_evidence",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "upload_id",
            "source_manifest_version",
            "content_profile",
            "configuration_hash",
            name="uq_upload_preparation_job_source_configuration",
        ),
        schema="integration",
    )
    op.create_index(
        "ix_upload_preparation_jobs_claim",
        "upload_preparation_jobs",
        ["state", "lease_until", "created_at"],
        unique=False,
        schema="integration",
    )
    op.create_table(
        "upload_preparation_receipts",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("preparation_job_id", sa.Uuid(), nullable=False),
        sa.Column("upload_id", sa.Uuid(), nullable=False),
        sa.Column("manifest_version", sa.Integer(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("accepted_sha256", sa.String(length=64), nullable=False),
        sa.Column("object_locator_hash", sa.String(length=64), nullable=False),
        sa.Column("accepted_etag", sa.String(length=512), nullable=True),
        sa.Column("accepted_version_id", sa.String(length=1024), nullable=True),
        sa.Column("content_profile", sa.String(length=100), nullable=False),
        sa.Column("parser_version", sa.String(length=100), nullable=False),
        sa.Column("scanner_version", sa.String(length=100), nullable=False),
        sa.Column("schema_version", sa.String(length=100), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column("item_count", sa.BigInteger(), nullable=False),
        sa.Column("rejected_count", sa.BigInteger(), nullable=False),
        sa.Column("candidate_root_hash", sa.String(length=64), nullable=False),
        sa.Column("receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "manifest_version > 0",
            name=op.f("ck_upload_preparation_receipts_manifest_version_positive"),
        ),
        sa.CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_upload_preparation_receipts_source_sha256_valid"),
        ),
        sa.CheckConstraint(
            "accepted_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_upload_preparation_receipts_accepted_sha256_valid"),
        ),
        sa.CheckConstraint(
            "accepted_sha256 = source_sha256",
            name=op.f("ck_upload_preparation_receipts_accepted_source_sha256_equal"),
        ),
        sa.CheckConstraint(
            "object_locator_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_upload_preparation_receipts_object_locator_hash_valid"),
        ),
        sa.CheckConstraint(
            "configuration_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_upload_preparation_receipts_configuration_hash_valid"),
        ),
        sa.CheckConstraint(
            "candidate_root_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_upload_preparation_receipts_candidate_root_hash_valid"),
        ),
        sa.CheckConstraint(
            "receipt_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_upload_preparation_receipts_receipt_hash_valid"),
        ),
        sa.CheckConstraint(
            "item_count >= 0 AND rejected_count >= 0",
            name=op.f("ck_upload_preparation_receipts_row_counts_nonnegative"),
        ),
        sa.CheckConstraint(
            "content_profile = 'DATASET_DESCRIPTION_CSV_V1'",
            name=op.f("ck_upload_preparation_receipts_typed_profile_allowlist"),
        ),
        sa.ForeignKeyConstraint(
            [
                "workspace_id",
                "preparation_job_id",
                "upload_id",
                "manifest_version",
                "source_sha256",
                "content_profile",
                "configuration_hash",
            ],
            [
                "integration.upload_preparation_jobs.workspace_id",
                "integration.upload_preparation_jobs.id",
                "integration.upload_preparation_jobs.upload_id",
                "integration.upload_preparation_jobs.source_manifest_version",
                "integration.upload_preparation_jobs.source_sha256",
                "integration.upload_preparation_jobs.content_profile",
                "integration.upload_preparation_jobs.configuration_hash",
            ],
            name="fk_upload_prep_receipts_source_evidence",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "upload_id"],
            ["integration.object_manifests.workspace_id", "integration.object_manifests.id"],
            name="fk_upload_prep_receipts_workspace_upload",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_upload_preparation_receipts")),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name=op.f("uq_upload_preparation_receipts_workspace_id_id"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "preparation_job_id",
            name=op.f("uq_upload_preparation_receipts_workspace_id_preparation_job_id"),
        ),
        schema="integration",
    )
    op.create_table(
        "upload_registration_candidates",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("receipt_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.BigInteger(), nullable=False),
        sa.Column("target_asset_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_kind", sa.String(length=100), nullable=False),
        sa.Column("proposed_description", sa.Text(), nullable=False),
        sa.Column("candidate_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "ordinal > 0",
            name=op.f("ck_upload_registration_candidates_ordinal_positive"),
        ),
        sa.CheckConstraint(
            "candidate_kind = 'DATASET_DESCRIPTION_UPDATE'",
            name=op.f("ck_upload_registration_candidates_candidate_kind_allowlist"),
        ),
        sa.CheckConstraint(
            "char_length(proposed_description) <= 10000",
            name=op.f("ck_upload_registration_candidates_description_length"),
        ),
        sa.CheckConstraint(
            "candidate_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_upload_registration_candidates_candidate_hash_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "receipt_id"],
            [
                "integration.upload_preparation_receipts.workspace_id",
                "integration.upload_preparation_receipts.id",
            ],
            name="fk_upload_reg_candidates_workspace_receipt",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_upload_registration_candidates")),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name=op.f("uq_upload_registration_candidates_workspace_id_id"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            "candidate_hash",
            name="uq_upload_registration_candidate_content",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "receipt_id",
            "ordinal",
            name=op.f("uq_upload_registration_candidates_workspace_id_receipt_id_ordinal"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "receipt_id",
            "target_asset_id",
            name=op.f("uq_upload_registration_candidates_workspace_id_receipt_id_target_asset_id"),
        ),
        schema="integration",
    )
    op.create_table(
        "registration_content_bindings",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_hash", sa.String(length=64), nullable=False),
        sa.Column("change_request_id", sa.Uuid(), nullable=False),
        sa.Column("change_item_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "candidate_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_registration_content_bindings_candidate_hash_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "candidate_id", "candidate_hash"],
            [
                "integration.upload_registration_candidates.workspace_id",
                "integration.upload_registration_candidates.id",
                "integration.upload_registration_candidates.candidate_hash",
            ],
            name="fk_reg_content_bindings_candidate_content",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "change_request_id"],
            ["governance.change_requests.workspace_id", "governance.change_requests.id"],
            name="fk_reg_content_bindings_workspace_request",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "change_request_id", "change_item_id"],
            [
                "governance.change_request_items.workspace_id",
                "governance.change_request_items.change_request_id",
                "governance.change_request_items.id",
            ],
            name="fk_reg_content_bindings_request_item",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "created_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_reg_content_bindings_workspace_creator",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_registration_content_bindings")),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name=op.f("uq_registration_content_bindings_workspace_id_id"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "candidate_id",
            name=op.f("uq_registration_content_bindings_workspace_id_candidate_id"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "change_item_id",
            name=op.f("uq_registration_content_bindings_workspace_id_change_item_id"),
        ),
        schema="governance",
    )
    _install_security_contract()


def _install_security_contract() -> None:
    _install_content_profile_contract()
    for schema, table in (
        ("integration", "upload_preparation_jobs"),
        ("integration", "upload_preparation_receipts"),
        ("integration", "upload_registration_candidates"),
        ("governance", "registration_content_bindings"),
    ):
        _enable_workspace_rls(schema, table)
    op.execute(
        "DO $datariver$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN "
        "GRANT SELECT, INSERT ON integration.upload_preparation_jobs TO datariver_app; "
        "GRANT SELECT ON integration.upload_preparation_receipts, "
        "integration.upload_registration_candidates TO datariver_app; "
        "GRANT SELECT, INSERT ON governance.registration_content_bindings TO datariver_app; "
        "END IF; END $datariver$"
    )


def _install_content_profile_contract() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION integration.reject_object_manifest_content_profile_change()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY INVOKER
        SET search_path = pg_catalog
        AS $function$
        BEGIN
            IF NEW.content_profile IS DISTINCT FROM OLD.content_profile THEN
                RAISE EXCEPTION 'object manifest content_profile is immutable'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END
        $function$
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS reject_object_manifest_content_profile_change "
        "ON integration.object_manifests"
    )
    op.execute(
        """
        CREATE TRIGGER reject_object_manifest_content_profile_change
        BEFORE UPDATE OF content_profile ON integration.object_manifests
        FOR EACH ROW
        EXECUTE FUNCTION integration.reject_object_manifest_content_profile_change()
        """
    )


def downgrade() -> None:
    # Compatibility bridge: regenerated 0001 owns the canonical typed BULK schema.
    pass
