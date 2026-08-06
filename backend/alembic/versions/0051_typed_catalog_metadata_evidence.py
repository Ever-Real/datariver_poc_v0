"""Add immutable typed catalog-metadata row, group and CR binding evidence.

Revision ID: 0051
Revises: 0050
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0051"
down_revision: str | Sequence[str] | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROFILE_CSV = "CATALOG_METADATA_ROWS_CSV_V1"
_PROFILE_XLSX = "CATALOG_METADATA_ROWS_XLSX_V1"
_NEW_TABLES = (
    ("catalog", "vocabulary_entries"),
    ("catalog", "vocabulary_sync_runs"),
    ("integration", "catalog_metadata_rows"),
    ("integration", "catalog_metadata_candidates"),
    ("integration", "catalog_metadata_candidate_rows"),
    ("governance", "registration_metadata_content_bindings"),
)
_EXPECTED_ARTIFACT_COUNT = len(_NEW_TABLES) + 1


def _artifact_count() -> int:
    return int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    (
                        SELECT count(*)
                        FROM information_schema.tables
                        WHERE (table_schema, table_name) IN (
                            ('catalog', 'vocabulary_entries'),
                            ('catalog', 'vocabulary_sync_runs'),
                            ('integration', 'catalog_metadata_rows'),
                            ('integration', 'catalog_metadata_candidates'),
                            ('integration', 'catalog_metadata_candidate_rows'),
                            ('governance', 'registration_metadata_content_bindings')
                        )
                    )
                    + (
                        SELECT count(*)
                        FROM information_schema.columns
                        WHERE table_schema = 'governance'
                          AND table_name = 'change_request_items'
                          AND column_name = 'item_contract_hash'
                    )
                """
            )
        )
        .scalar_one()
    )


def _create_supporting_contract() -> None:
    op.add_column(
        "change_request_items",
        sa.Column("item_contract_hash", sa.String(length=64), nullable=True),
        schema="governance",
    )
    op.create_check_constraint(
        "ck_change_request_items_item_contract_hash_sha256",
        "change_request_items",
        "item_contract_hash IS NULL OR item_contract_hash ~ '^[0-9a-f]{64}$'",
        schema="governance",
    )
    op.create_unique_constraint(
        "uq_change_request_items_metadata_contract",
        "change_request_items",
        [
            "workspace_id",
            "change_request_id",
            "id",
            "aspect_name",
            "before_hash",
            "after_hash",
            "item_contract_hash",
        ],
        schema="governance",
    )
    op.create_unique_constraint(
        "uq_upload_preparation_receipts_profile_identity",
        "upload_preparation_receipts",
        ["workspace_id", "id", "content_profile"],
        schema="integration",
    )


def _create_vocabulary_table() -> None:
    op.create_table(
        "vocabulary_entries",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("provider_ref", sa.String(length=1_000), nullable=False),
        sa.Column("display_name", sa.String(length=500), nullable=False),
        sa.Column("lifecycle", sa.String(length=16), nullable=False),
        sa.Column("source_version", sa.String(length=255), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_sync_id", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('DOMAIN', 'TAG', 'TERM')",
            name=op.f("ck_vocabulary_entries_kind_vocabulary"),
        ),
        sa.CheckConstraint(
            "lifecycle IN ('ACTIVE', 'INACTIVE')",
            name=op.f("ck_vocabulary_entries_lifecycle_vocabulary"),
        ),
        sa.CheckConstraint(
            "char_length(display_name) BETWEEN 1 AND 500 AND display_name = btrim(display_name)",
            name=op.f("ck_vocabulary_entries_display_name_valid"),
        ),
        sa.CheckConstraint(
            "char_length(source_version) BETWEEN 1 AND 255 "
            "AND source_version = btrim(source_version)",
            name=op.f("ck_vocabulary_entries_source_version_valid"),
        ),
        sa.CheckConstraint(
            "(kind = 'DOMAIN' AND provider_ref LIKE 'urn:li:domain:%') OR "
            "(kind = 'TAG' AND provider_ref LIKE 'urn:li:tag:%') OR "
            "(kind = 'TERM' AND provider_ref LIKE 'urn:li:glossaryTerm:%')",
            name=op.f("ck_vocabulary_entries_provider_ref_kind"),
        ),
        sa.CheckConstraint(
            "observed_at <= updated_at",
            name=op.f("ck_vocabulary_entries_observation_time_order"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            name="fk_vocabulary_entries_workspace_id_workspaces",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vocabulary_entries")),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name=op.f("uq_vocabulary_entries_workspace_id_id"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            "kind",
            name=op.f("uq_vocabulary_entries_workspace_id_id_kind"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "kind",
            "provider_ref",
            name="uq_vocabulary_entries_workspace_kind_provider_ref",
        ),
        schema="catalog",
    )
    op.create_index(
        "ix_vocabulary_entries_workspace_kind_lifecycle_name",
        "vocabulary_entries",
        ["workspace_id", "kind", "lifecycle", "display_name", "id"],
        schema="catalog",
    )


def _create_vocabulary_sync_run_table() -> None:
    op.create_table(
        "vocabulary_sync_runs",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("sync_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("next_offset", sa.Integer(), nullable=False),
        sa.Column("next_cursor", sa.Text(), nullable=True),
        sa.Column("expected_total", sa.BigInteger(), nullable=True),
        sa.Column("seen_count", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "snapshot_consistent",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("snapshot_evidence_reference", sa.String(length=500), nullable=True),
        sa.Column("snapshot_contract_hash", sa.String(length=64), nullable=True),
        sa.Column("snapshot_provider_version", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('DOMAIN', 'TAG', 'TERM')",
            name=op.f("ck_vocabulary_sync_runs_kind_vocabulary"),
        ),
        sa.CheckConstraint(
            "state IN ('ACTIVE', 'COMPLETED', 'ABANDONED')",
            name=op.f("ck_vocabulary_sync_runs_state_vocabulary"),
        ),
        sa.CheckConstraint(
            "next_offset >= 0",
            name=op.f("ck_vocabulary_sync_runs_next_offset_nonnegative"),
        ),
        sa.CheckConstraint(
            "expected_total IS NULL OR expected_total >= 0",
            name=op.f("ck_vocabulary_sync_runs_expected_total_nonnegative"),
        ),
        sa.CheckConstraint(
            "seen_count >= 0",
            name=op.f("ck_vocabulary_sync_runs_seen_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "next_cursor IS NULL OR char_length(next_cursor) BETWEEN 1 AND 4096",
            name=op.f("ck_vocabulary_sync_runs_next_cursor_bounded"),
        ),
        sa.CheckConstraint(
            "(NOT snapshot_consistent AND snapshot_evidence_reference IS NULL "
            "AND snapshot_contract_hash IS NULL AND snapshot_provider_version IS NULL) OR "
            "(snapshot_consistent "
            "AND snapshot_evidence_reference IS NOT NULL "
            "AND snapshot_contract_hash IS NOT NULL "
            "AND snapshot_provider_version IS NOT NULL "
            "AND char_length(snapshot_evidence_reference) BETWEEN 1 AND 500 "
            "AND snapshot_contract_hash ~ '^[0-9a-f]{64}$' "
            "AND char_length(snapshot_provider_version) BETWEEN 1 AND 128)",
            name=op.f("ck_vocabulary_sync_runs_snapshot_evidence_bounded"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            name="fk_vocabulary_sync_runs_workspace_id_workspaces",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "sync_id",
            "kind",
            name=op.f("pk_vocabulary_sync_runs"),
        ),
        schema="catalog",
    )
    op.create_index(
        "uq_vocabulary_sync_runs_active_workspace_kind",
        "vocabulary_sync_runs",
        ["workspace_id", "kind"],
        unique=True,
        schema="catalog",
        postgresql_where=sa.text("state = 'ACTIVE'"),
    )
    op.create_index(
        "ix_vocabulary_sync_runs_workspace_kind_started",
        "vocabulary_sync_runs",
        ["workspace_id", "kind", "started_at"],
        schema="catalog",
    )


def _create_row_table() -> None:
    op.create_table(
        "catalog_metadata_rows",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("receipt_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.BigInteger(), nullable=False),
        sa.Column("content_profile", sa.String(length=100), nullable=False),
        sa.Column("evidence_version", sa.String(length=100), nullable=False),
        sa.Column("record_kind", sa.String(length=64), nullable=False),
        sa.Column("aspect_name", sa.String(length=64), nullable=False),
        sa.Column("target_asset_id", sa.Uuid(), nullable=False),
        sa.Column("submitted_platform", sa.String(length=100), nullable=False),
        sa.Column("submitted_database_name", sa.String(length=255), nullable=False),
        sa.Column("submitted_schema_name", sa.String(length=255), nullable=False),
        sa.Column("submitted_table_name", sa.String(length=500), nullable=False),
        sa.Column("field_path", sa.String(length=2_000), nullable=True),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("controlled_ref_id", sa.Uuid(), nullable=True),
        sa.Column("controlled_kind", sa.String(length=16), nullable=True),
        sa.Column("submitted_identity_hash", sa.String(length=64), nullable=False),
        sa.Column("semantic_target_hash", sa.String(length=64), nullable=False),
        sa.Column("row_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "ordinal BETWEEN 1 AND 10000",
            name=op.f("ck_catalog_metadata_rows_ordinal_range"),
        ),
        sa.CheckConstraint(
            f"content_profile IN ('{_PROFILE_CSV}', '{_PROFILE_XLSX}')",
            name=op.f("ck_catalog_metadata_rows_content_profile_allowlist"),
        ),
        sa.CheckConstraint(
            "evidence_version = 'CATALOG_METADATA_CANDIDATE_V3'",
            name=op.f("ck_catalog_metadata_rows_evidence_version_contract"),
        ),
        sa.CheckConstraint(
            "record_kind IN ('TABLE_DESCRIPTION', 'COLUMN_DESCRIPTION', "
            "'DATASET_DOMAIN', 'DATASET_TERM', 'DATASET_TAG')",
            name=op.f("ck_catalog_metadata_rows_record_kind_allowlist"),
        ),
        sa.CheckConstraint(
            "operation IN ('SET', 'CLEAR', 'ADD')",
            name=op.f("ck_catalog_metadata_rows_operation_allowlist"),
        ),
        sa.CheckConstraint(
            "(record_kind = 'TABLE_DESCRIPTION' AND aspect_name = 'datasetProperties') OR "
            "(record_kind = 'COLUMN_DESCRIPTION' AND aspect_name = 'schemaMetadata') OR "
            "(record_kind = 'DATASET_DOMAIN' AND aspect_name = 'domains') OR "
            "(record_kind = 'DATASET_TERM' AND aspect_name = 'glossaryTerms') OR "
            "(record_kind = 'DATASET_TAG' AND aspect_name = 'globalTags')",
            name=op.f("ck_catalog_metadata_rows_record_kind_aspect_contract"),
        ),
        sa.CheckConstraint(
            "char_length(submitted_platform) BETWEEN 1 AND 100 "
            "AND submitted_platform = btrim(submitted_platform)",
            name=op.f("ck_catalog_metadata_rows_submitted_platform_valid"),
        ),
        sa.CheckConstraint(
            "char_length(submitted_database_name) BETWEEN 1 AND 255 "
            "AND submitted_database_name = btrim(submitted_database_name)",
            name=op.f("ck_catalog_metadata_rows_submitted_database_name_valid"),
        ),
        sa.CheckConstraint(
            "char_length(submitted_schema_name) BETWEEN 1 AND 255 "
            "AND submitted_schema_name = btrim(submitted_schema_name)",
            name=op.f("ck_catalog_metadata_rows_submitted_schema_name_valid"),
        ),
        sa.CheckConstraint(
            "char_length(submitted_table_name) BETWEEN 1 AND 500 "
            "AND submitted_table_name = btrim(submitted_table_name)",
            name=op.f("ck_catalog_metadata_rows_submitted_table_name_valid"),
        ),
        sa.CheckConstraint(
            "field_path IS NULL OR "
            "(char_length(field_path) BETWEEN 1 AND 2000 "
            "AND field_path = btrim(field_path))",
            name=op.f("ck_catalog_metadata_rows_field_path_valid"),
        ),
        sa.CheckConstraint(
            "value_text IS NULL OR char_length(value_text) BETWEEN 1 AND 10000",
            name=op.f("ck_catalog_metadata_rows_value_text_valid"),
        ),
        sa.CheckConstraint(
            "controlled_kind IS NULL OR controlled_kind IN ('DOMAIN', 'TAG', 'TERM')",
            name=op.f("ck_catalog_metadata_rows_controlled_kind_vocabulary"),
        ),
        sa.CheckConstraint(
            "submitted_identity_hash ~ '^[0-9a-f]{64}$' "
            "AND semantic_target_hash ~ '^[0-9a-f]{64}$' "
            "AND row_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_catalog_metadata_rows_evidence_hashes_valid"),
        ),
        sa.CheckConstraint(
            "("
            "record_kind = 'TABLE_DESCRIPTION' "
            "AND field_path IS NULL AND controlled_ref_id IS NULL "
            "AND controlled_kind IS NULL "
            "AND ((operation = 'SET' AND value_text IS NOT NULL) "
            "OR (operation = 'CLEAR' AND value_text IS NULL))"
            ") OR ("
            "record_kind = 'COLUMN_DESCRIPTION' "
            "AND field_path IS NOT NULL AND controlled_ref_id IS NULL "
            "AND controlled_kind IS NULL "
            "AND ((operation = 'SET' AND value_text IS NOT NULL) "
            "OR (operation = 'CLEAR' AND value_text IS NULL))"
            ") OR ("
            "record_kind = 'DATASET_DOMAIN' "
            "AND field_path IS NULL AND value_text IS NULL "
            "AND ((operation = 'SET' AND controlled_ref_id IS NOT NULL "
            "AND controlled_kind = 'DOMAIN') "
            "OR (operation = 'CLEAR' AND controlled_ref_id IS NULL "
            "AND controlled_kind IS NULL))"
            ") OR ("
            "record_kind = 'DATASET_TERM' AND operation = 'ADD' "
            "AND field_path IS NULL AND value_text IS NULL "
            "AND controlled_ref_id IS NOT NULL AND controlled_kind = 'TERM'"
            ") OR ("
            "record_kind = 'DATASET_TAG' AND operation = 'ADD' "
            "AND field_path IS NULL AND value_text IS NULL "
            "AND controlled_ref_id IS NOT NULL AND controlled_kind = 'TAG'"
            ")",
            name=op.f("ck_catalog_metadata_rows_typed_detail_xor"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "receipt_id", "content_profile"],
            [
                "integration.upload_preparation_receipts.workspace_id",
                "integration.upload_preparation_receipts.id",
                "integration.upload_preparation_receipts.content_profile",
            ],
            name="fk_catalog_metadata_rows_receipt_profile",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "controlled_ref_id", "controlled_kind"],
            [
                "catalog.vocabulary_entries.workspace_id",
                "catalog.vocabulary_entries.id",
                "catalog.vocabulary_entries.kind",
            ],
            name="fk_catalog_metadata_rows_vocabulary",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalog_metadata_rows")),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name=op.f("uq_catalog_metadata_rows_workspace_id_id"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "receipt_id",
            "ordinal",
            name=op.f("uq_catalog_metadata_rows_workspace_id_receipt_id_ordinal"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "receipt_id",
            "semantic_target_hash",
            name="uq_catalog_metadata_rows_semantic_target",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "receipt_id",
            "id",
            "content_profile",
            "row_hash",
            name="uq_catalog_metadata_rows_content",
        ),
        schema="integration",
    )


def _create_candidate_table() -> None:
    op.create_table(
        "catalog_metadata_candidates",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("receipt_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_ordinal", sa.BigInteger(), nullable=False),
        sa.Column("content_profile", sa.String(length=100), nullable=False),
        sa.Column("record_kind", sa.String(length=64), nullable=False),
        sa.Column("candidate_kind", sa.String(length=100), nullable=False),
        sa.Column("evidence_version", sa.String(length=100), nullable=False),
        sa.Column("target_asset_id", sa.Uuid(), nullable=False),
        sa.Column("aspect_name", sa.String(length=64), nullable=False),
        sa.Column("submitted_identity_hash", sa.String(length=64), nullable=False),
        sa.Column("row_count", sa.BigInteger(), nullable=False),
        sa.Column("first_row_ordinal", sa.BigInteger(), nullable=False),
        sa.Column("last_row_ordinal", sa.BigInteger(), nullable=False),
        sa.Column("row_root_hash", sa.String(length=64), nullable=False),
        sa.Column("candidate_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "candidate_ordinal BETWEEN 1 AND 10000",
            name=op.f("ck_catalog_metadata_candidates_candidate_ordinal_range"),
        ),
        sa.CheckConstraint(
            f"content_profile IN ('{_PROFILE_CSV}', '{_PROFILE_XLSX}')",
            name=op.f("ck_catalog_metadata_candidates_content_profile_allowlist"),
        ),
        sa.CheckConstraint(
            "evidence_version = 'CATALOG_METADATA_CANDIDATE_V3'",
            name=op.f("ck_catalog_metadata_candidates_evidence_version_contract"),
        ),
        sa.CheckConstraint(
            "(record_kind = 'TABLE_DESCRIPTION' "
            "AND candidate_kind = 'TABLE_DESCRIPTION_UPDATE' "
            "AND aspect_name = 'datasetProperties') OR "
            "(record_kind = 'COLUMN_DESCRIPTION' "
            "AND candidate_kind = 'COLUMN_DESCRIPTION_UPDATE' "
            "AND aspect_name = 'schemaMetadata') OR "
            "(record_kind = 'DATASET_DOMAIN' "
            "AND candidate_kind = 'DATASET_DOMAIN_UPDATE' "
            "AND aspect_name = 'domains') OR "
            "(record_kind = 'DATASET_TERM' "
            "AND candidate_kind = 'DATASET_TERM_ADD' "
            "AND aspect_name = 'glossaryTerms') OR "
            "(record_kind = 'DATASET_TAG' "
            "AND candidate_kind = 'DATASET_TAG_ADD' "
            "AND aspect_name = 'globalTags')",
            name=op.f("ck_catalog_metadata_candidates_record_candidate_aspect_contract"),
        ),
        sa.CheckConstraint(
            "row_count BETWEEN 1 AND 10000 "
            "AND first_row_ordinal BETWEEN 1 AND 10000 "
            "AND last_row_ordinal BETWEEN first_row_ordinal AND 10000",
            name=op.f("ck_catalog_metadata_candidates_ordered_row_span"),
        ),
        sa.CheckConstraint(
            "submitted_identity_hash ~ '^[0-9a-f]{64}$' "
            "AND row_root_hash ~ '^[0-9a-f]{64}$' "
            "AND candidate_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_catalog_metadata_candidates_evidence_hashes_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "receipt_id", "content_profile"],
            [
                "integration.upload_preparation_receipts.workspace_id",
                "integration.upload_preparation_receipts.id",
                "integration.upload_preparation_receipts.content_profile",
            ],
            name="fk_catalog_metadata_candidates_receipt_profile",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalog_metadata_candidates")),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name=op.f("uq_catalog_metadata_candidates_workspace_id_id"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "receipt_id",
            "candidate_ordinal",
            name=op.f("uq_catalog_metadata_candidates_workspace_id_receipt_id_candidate_ordinal"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "receipt_id",
            "target_asset_id",
            "aspect_name",
            name="uq_catalog_metadata_candidates_target_aspect",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "receipt_id",
            "id",
            "content_profile",
            "candidate_hash",
            name="uq_catalog_metadata_candidates_membership_content",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            "content_profile",
            "candidate_kind",
            "aspect_name",
            "candidate_hash",
            name="uq_catalog_metadata_candidates_binding_content",
        ),
        schema="integration",
    )


def _create_membership_table() -> None:
    op.create_table(
        "catalog_metadata_candidate_rows",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("receipt_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("row_id", sa.Uuid(), nullable=False),
        sa.Column("content_profile", sa.String(length=100), nullable=False),
        sa.Column("candidate_hash", sa.String(length=64), nullable=False),
        sa.Column("row_hash", sa.String(length=64), nullable=False),
        sa.Column("member_ordinal", sa.BigInteger(), nullable=False),
        sa.Column("source_ordinal", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "member_ordinal BETWEEN 1 AND 10000 AND source_ordinal BETWEEN 1 AND 10000",
            name=op.f("ck_catalog_metadata_candidate_rows_ordinal_range"),
        ),
        sa.CheckConstraint(
            f"content_profile IN ('{_PROFILE_CSV}', '{_PROFILE_XLSX}')",
            name=op.f("ck_catalog_metadata_candidate_rows_content_profile_allowlist"),
        ),
        sa.CheckConstraint(
            "candidate_hash ~ '^[0-9a-f]{64}$' AND row_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_catalog_metadata_candidate_rows_content_hashes_valid"),
        ),
        sa.ForeignKeyConstraint(
            [
                "workspace_id",
                "receipt_id",
                "candidate_id",
                "content_profile",
                "candidate_hash",
            ],
            [
                "integration.catalog_metadata_candidates.workspace_id",
                "integration.catalog_metadata_candidates.receipt_id",
                "integration.catalog_metadata_candidates.id",
                "integration.catalog_metadata_candidates.content_profile",
                "integration.catalog_metadata_candidates.candidate_hash",
            ],
            name="fk_catalog_metadata_candidate_rows_candidate",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "receipt_id", "row_id", "content_profile", "row_hash"],
            [
                "integration.catalog_metadata_rows.workspace_id",
                "integration.catalog_metadata_rows.receipt_id",
                "integration.catalog_metadata_rows.id",
                "integration.catalog_metadata_rows.content_profile",
                "integration.catalog_metadata_rows.row_hash",
            ],
            name="fk_catalog_metadata_candidate_rows_row",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "receipt_id",
            "candidate_id",
            "row_id",
            name=op.f("pk_catalog_metadata_candidate_rows"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "receipt_id",
            "candidate_id",
            "member_ordinal",
            name="uq_catalog_metadata_candidate_rows_member",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "receipt_id",
            "candidate_id",
            "source_ordinal",
            name="uq_catalog_metadata_candidate_rows_source_ordinal",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "receipt_id",
            "row_id",
            name="uq_catalog_metadata_candidate_rows_row",
        ),
        schema="integration",
    )


def _create_binding_table() -> None:
    op.create_table(
        "registration_metadata_content_bindings",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_hash", sa.String(length=64), nullable=False),
        sa.Column("content_profile", sa.String(length=100), nullable=False),
        sa.Column("candidate_kind", sa.String(length=100), nullable=False),
        sa.Column("aspect_name", sa.String(length=64), nullable=False),
        sa.Column("before_hash", sa.String(length=64), nullable=False),
        sa.Column("after_hash", sa.String(length=64), nullable=False),
        sa.Column("item_contract_hash", sa.String(length=64), nullable=False),
        sa.Column("change_request_id", sa.Uuid(), nullable=False),
        sa.Column("change_item_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            f"content_profile IN ('{_PROFILE_CSV}', '{_PROFILE_XLSX}')",
            name=op.f("ck_registration_metadata_content_bindings_content_profile_allowlist"),
        ),
        sa.CheckConstraint(
            "(candidate_kind = 'TABLE_DESCRIPTION_UPDATE' "
            "AND aspect_name = 'datasetProperties') OR "
            "(candidate_kind = 'COLUMN_DESCRIPTION_UPDATE' "
            "AND aspect_name = 'schemaMetadata') OR "
            "(candidate_kind = 'DATASET_DOMAIN_UPDATE' AND aspect_name = 'domains') OR "
            "(candidate_kind = 'DATASET_TERM_ADD' AND aspect_name = 'glossaryTerms') OR "
            "(candidate_kind = 'DATASET_TAG_ADD' AND aspect_name = 'globalTags')",
            name=op.f("ck_registration_metadata_content_bindings_candidate_aspect"),
        ),
        sa.CheckConstraint(
            "candidate_hash ~ '^[0-9a-f]{64}$' "
            "AND before_hash ~ '^[0-9a-f]{64}$' "
            "AND after_hash ~ '^[0-9a-f]{64}$' "
            "AND item_contract_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_registration_metadata_content_bindings_content_hashes_valid"),
        ),
        sa.ForeignKeyConstraint(
            [
                "workspace_id",
                "candidate_id",
                "content_profile",
                "candidate_kind",
                "aspect_name",
                "candidate_hash",
            ],
            [
                "integration.catalog_metadata_candidates.workspace_id",
                "integration.catalog_metadata_candidates.id",
                "integration.catalog_metadata_candidates.content_profile",
                "integration.catalog_metadata_candidates.candidate_kind",
                "integration.catalog_metadata_candidates.aspect_name",
                "integration.catalog_metadata_candidates.candidate_hash",
            ],
            name="fk_registration_metadata_bindings_candidate_content",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "workspace_id",
                "change_request_id",
                "change_item_id",
                "aspect_name",
                "before_hash",
                "after_hash",
                "item_contract_hash",
            ],
            [
                "governance.change_request_items.workspace_id",
                "governance.change_request_items.change_request_id",
                "governance.change_request_items.id",
                "governance.change_request_items.aspect_name",
                "governance.change_request_items.before_hash",
                "governance.change_request_items.after_hash",
                "governance.change_request_items.item_contract_hash",
            ],
            name="fk_registration_metadata_bindings_request_item",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "change_request_id"],
            ["governance.change_requests.workspace_id", "governance.change_requests.id"],
            name="fk_registration_metadata_bindings_request",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "created_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_registration_metadata_bindings_creator",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_registration_metadata_content_bindings"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name=op.f("uq_registration_metadata_content_bindings_workspace_id_id"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "candidate_id",
            name=op.f("uq_registration_metadata_content_bindings_workspace_id_candidate_id"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "change_request_id",
            name=op.f("uq_registration_metadata_content_bindings_workspace_id_change_request_id"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "change_item_id",
            name=op.f("uq_registration_metadata_content_bindings_workspace_id_change_item_id"),
        ),
        schema="governance",
    )


def _create_schema() -> None:
    _create_supporting_contract()
    _create_vocabulary_table()
    _create_vocabulary_sync_run_table()
    _create_row_table()
    _create_candidate_table()
    _create_membership_table()
    _create_binding_table()


def _replace_profile_allowlists() -> None:
    statements = (
        (
            "integration.object_manifests",
            "ck_object_manifests_content_profile_allowlist",
            "content_profile IN ('FORMAT_ONLY_V1', 'DATASET_DESCRIPTION_CSV_V1', "
            "'DATASET_DESCRIPTION_XLSX_V1', 'CATALOG_METADATA_ROWS_CSV_V1', "
            "'CATALOG_METADATA_ROWS_XLSX_V1')",
        ),
        (
            "integration.upload_preparation_jobs",
            "ck_upload_preparation_jobs_typed_profile_allowlist",
            "content_profile IN ('DATASET_DESCRIPTION_CSV_V1', "
            "'DATASET_DESCRIPTION_XLSX_V1', 'CATALOG_METADATA_ROWS_CSV_V1', "
            "'CATALOG_METADATA_ROWS_XLSX_V1')",
        ),
        (
            "integration.upload_preparation_receipts",
            "ck_upload_preparation_receipts_typed_profile_allowlist",
            "content_profile IN ('DATASET_DESCRIPTION_CSV_V1', "
            "'DATASET_DESCRIPTION_XLSX_V1', 'CATALOG_METADATA_ROWS_CSV_V1', "
            "'CATALOG_METADATA_ROWS_XLSX_V1')",
        ),
    )
    for table, constraint, expression in statements:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {constraint} CHECK ({expression}) NOT VALID"
        )
        op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {constraint}")


def _install_rls() -> None:
    for schema, table in _NEW_TABLES:
        qualified = f"{schema}.{table}"
        op.execute(f"ALTER TABLE {qualified} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {qualified} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS workspace_isolation ON {qualified}")
        op.execute(
            f"""
            CREATE POLICY workspace_isolation
            ON {qualified}
            USING (
                workspace_id =
                    NULLIF(pg_catalog.current_setting('app.workspace_id', true), '')::uuid
            )
            WITH CHECK (
                workspace_id =
                    NULLIF(pg_catalog.current_setting('app.workspace_id', true), '')::uuid
            )
            """
        )


def _install_immutability() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION catalog.guard_vocabulary_entry_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'catalog vocabulary entries cannot be deleted'
                    USING ERRCODE = '23514';
            END IF;
            IF ROW(NEW.id, NEW.workspace_id, NEW.kind, NEW.provider_ref)
               IS DISTINCT FROM
               ROW(OLD.id, OLD.workspace_id, OLD.kind, OLD.provider_ref) THEN
                RAISE EXCEPTION 'catalog vocabulary identity is immutable'
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.updated_at < OLD.updated_at
               OR NEW.updated_at < NEW.observed_at THEN
                RAISE EXCEPTION 'catalog vocabulary observation time is not monotonic'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END
        $function$
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS guard_vocabulary_entry_mutation ON catalog.vocabulary_entries"
    )
    op.execute(
        """
        CREATE TRIGGER guard_vocabulary_entry_mutation
        BEFORE UPDATE OR DELETE ON catalog.vocabulary_entries
        FOR EACH ROW EXECUTE FUNCTION catalog.guard_vocabulary_entry_mutation()
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION integration.reject_catalog_metadata_evidence_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        BEGIN
            RAISE EXCEPTION 'catalog metadata row and candidate evidence is append-only'
                USING ERRCODE = '23514';
        END
        $function$
        """
    )
    for table in (
        "catalog_metadata_rows",
        "catalog_metadata_candidates",
        "catalog_metadata_candidate_rows",
    ):
        op.execute(
            f"DROP TRIGGER IF EXISTS reject_catalog_metadata_evidence_mutation "
            f"ON integration.{table}"
        )
        op.execute(
            f"""
            CREATE TRIGGER reject_catalog_metadata_evidence_mutation
            BEFORE UPDATE OR DELETE ON integration.{table}
            FOR EACH ROW
            EXECUTE FUNCTION integration.reject_catalog_metadata_evidence_mutation()
            """
        )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION governance.reject_registration_metadata_binding_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $function$
        BEGIN
            RAISE EXCEPTION 'registration metadata bindings are append-only'
                USING ERRCODE = '23514';
        END
        $function$
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS reject_registration_metadata_binding_mutation "
        "ON governance.registration_metadata_content_bindings"
    )
    op.execute(
        """
        CREATE TRIGGER reject_registration_metadata_binding_mutation
        BEFORE UPDATE OR DELETE ON governance.registration_metadata_content_bindings
        FOR EACH ROW
        EXECUTE FUNCTION governance.reject_registration_metadata_binding_mutation()
        """
    )


def _install_grants() -> None:
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'datariver_app') THEN
                GRANT USAGE ON SCHEMA catalog, integration, governance TO datariver_app;
                REVOKE ALL PRIVILEGES ON
                    catalog.vocabulary_entries,
                    catalog.vocabulary_sync_runs,
                    integration.catalog_metadata_rows,
                    integration.catalog_metadata_candidates,
                    integration.catalog_metadata_candidate_rows,
                    governance.registration_metadata_content_bindings
                    FROM datariver_app;
                GRANT SELECT, INSERT ON
                    catalog.vocabulary_entries,
                    catalog.vocabulary_sync_runs,
                    integration.catalog_metadata_rows,
                    integration.catalog_metadata_candidates,
                    integration.catalog_metadata_candidate_rows,
                    governance.registration_metadata_content_bindings
                    TO datariver_app;
                GRANT UPDATE (
                    display_name, lifecycle, source_version, observed_at,
                    last_seen_sync_id, updated_at
                ) ON catalog.vocabulary_entries TO datariver_app;
                GRANT UPDATE (
                    state, next_offset, next_cursor, expected_total, seen_count,
                    snapshot_consistent, snapshot_evidence_reference,
                    snapshot_contract_hash, snapshot_provider_version,
                    heartbeat_at, completed_at
                ) ON catalog.vocabulary_sync_runs TO datariver_app;
            END IF;
            IF EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'datariver_governance'
            ) THEN
                GRANT USAGE ON SCHEMA catalog, integration, governance
                    TO datariver_governance;
                REVOKE ALL PRIVILEGES ON
                    catalog.vocabulary_entries,
                    catalog.vocabulary_sync_runs,
                    integration.catalog_metadata_rows,
                    integration.catalog_metadata_candidates,
                    integration.catalog_metadata_candidate_rows,
                    governance.registration_metadata_content_bindings
                    FROM datariver_governance;
                GRANT SELECT ON
                    catalog.vocabulary_entries,
                    catalog.vocabulary_sync_runs,
                    integration.catalog_metadata_rows,
                    integration.catalog_metadata_candidates,
                    integration.catalog_metadata_candidate_rows,
                    governance.registration_metadata_content_bindings
                    TO datariver_governance;
            END IF;
            IF EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'datariver_upload'
            ) THEN
                REVOKE ALL PRIVILEGES ON
                    catalog.vocabulary_entries,
                    catalog.vocabulary_sync_runs,
                    integration.catalog_metadata_rows,
                    integration.catalog_metadata_candidates,
                    integration.catalog_metadata_candidate_rows,
                    governance.registration_metadata_content_bindings
                    FROM datariver_upload;
            END IF;
        END
        $datariver$
        """
    )


def _assert_contract() -> None:
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM (
                    VALUES
                        ('catalog', 'vocabulary_entries'),
                        ('catalog', 'vocabulary_sync_runs'),
                        ('integration', 'catalog_metadata_rows'),
                        ('integration', 'catalog_metadata_candidates'),
                        ('integration', 'catalog_metadata_candidate_rows'),
                        ('governance', 'registration_metadata_content_bindings')
                ) AS expected(schema_name, table_name)
                LEFT JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.nspname = expected.schema_name
                LEFT JOIN pg_catalog.pg_class AS relation
                  ON relation.relnamespace = namespace.oid
                 AND relation.relname = expected.table_name
                WHERE relation.oid IS NULL
                   OR relation.relrowsecurity IS NOT TRUE
                   OR relation.relforcerowsecurity IS NOT TRUE
            ) THEN
                RAISE EXCEPTION 'typed catalog metadata evidence RLS is incomplete';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM (
                    VALUES
                        ('catalog', 'vocabulary_entries'),
                        ('catalog', 'vocabulary_sync_runs'),
                        ('integration', 'catalog_metadata_rows'),
                        ('integration', 'catalog_metadata_candidates'),
                        ('integration', 'catalog_metadata_candidate_rows'),
                        ('governance', 'registration_metadata_content_bindings')
                ) AS expected(schema_name, table_name)
                LEFT JOIN pg_catalog.pg_policies AS policy
                  ON policy.schemaname = expected.schema_name
                 AND policy.tablename = expected.table_name
                 AND policy.policyname = 'workspace_isolation'
                WHERE policy.policyname IS NULL
                   OR policy.cmd <> 'ALL'
                   OR policy.permissive <> 'PERMISSIVE'
                   OR policy.qual NOT LIKE '%app.workspace_id%'
                   OR policy.with_check NOT LIKE '%app.workspace_id%'
            ) THEN
                RAISE EXCEPTION 'typed catalog metadata workspace policy is invalid';
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'catalog'
                  AND table_name = 'vocabulary_entries'
                  AND column_name = 'last_seen_sync_id'
                  AND data_type = 'uuid'
                  AND is_nullable = 'YES'
            ) OR NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'governance'
                  AND table_name = 'change_request_items'
                  AND column_name = 'item_contract_hash'
                  AND data_type = 'character varying'
                  AND character_maximum_length = 64
                  AND is_nullable = 'YES'
            ) OR NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_index AS index_row
                JOIN pg_catalog.pg_class AS index_relation
                  ON index_relation.oid = index_row.indexrelid
                WHERE index_row.indrelid =
                        'catalog.vocabulary_sync_runs'::regclass
                  AND index_relation.relname =
                        'uq_vocabulary_sync_runs_active_workspace_kind'
                  AND index_row.indisunique
                  AND pg_catalog.pg_get_expr(
                        index_row.indpred,
                        index_row.indrelid
                      ) LIKE '%state%ACTIVE%'
            ) OR NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_constraint
                WHERE conrelid = 'catalog.vocabulary_sync_runs'::regclass
                  AND conname =
                        'ck_vocabulary_sync_runs_snapshot_evidence_bounded'
                  AND convalidated
                  AND pg_catalog.pg_get_constraintdef(oid)
                        LIKE '%snapshot_consistent%'
            ) OR NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_constraint
                WHERE conrelid = 'governance.change_request_items'::regclass
                  AND conname = 'uq_change_request_items_metadata_contract'
                  AND contype = 'u'
            ) OR NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_constraint
                WHERE conrelid =
                    'integration.upload_preparation_receipts'::regclass
                  AND conname =
                    'uq_upload_preparation_receipts_profile_identity'
                  AND contype = 'u'
            ) THEN
                RAISE EXCEPTION 'typed catalog metadata support constraints are missing';
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'integration'
                  AND table_name = 'catalog_metadata_rows'
                  AND column_name = 'aspect_name'
                  AND is_nullable = 'NO'
            ) OR NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'integration'
                  AND table_name = 'catalog_metadata_candidates'
                  AND column_name = 'record_kind'
                  AND is_nullable = 'NO'
            ) OR EXISTS (
                SELECT 1
                FROM (
                    VALUES
                        ('integration.catalog_metadata_rows'::regclass,
                         'ck_catalog_metadata_rows_evidence_version_contract',
                         'CATALOG_METADATA_CANDIDATE_V3'),
                        ('integration.catalog_metadata_rows'::regclass,
                         'ck_catalog_metadata_rows_record_kind_aspect_contract',
                         'datasetProperties'),
                        ('integration.catalog_metadata_candidates'::regclass,
                         'ck_catalog_metadata_candidates_evidence_version_contract',
                         'CATALOG_METADATA_CANDIDATE_V3'),
                        ('integration.catalog_metadata_candidates'::regclass,
                         'ck_catalog_metadata_candidates_record_candidate_aspect_contract',
                         'TABLE_DESCRIPTION_UPDATE'),
                        ('governance.registration_metadata_content_bindings'::regclass,
                         'ck_registration_metadata_content_bindings_candidate_aspect',
                         'TABLE_DESCRIPTION_UPDATE')
                ) AS expected(relation_id, constraint_name, required_token)
                LEFT JOIN pg_catalog.pg_constraint AS constraint_row
                  ON constraint_row.conrelid = expected.relation_id
                 AND constraint_row.conname = expected.constraint_name
                WHERE constraint_row.oid IS NULL
                   OR constraint_row.convalidated IS NOT TRUE
                   OR pg_catalog.pg_get_constraintdef(constraint_row.oid)
                        NOT LIKE '%' || expected.required_token || '%'
            ) OR EXISTS (
                SELECT 1
                FROM pg_catalog.pg_constraint
                WHERE conrelid = 'integration.catalog_metadata_candidates'::regclass
                  AND conname = 'ck_catalog_metadata_candidates_ordered_row_span'
                  AND pg_catalog.pg_get_constraintdef(oid)
                        LIKE '%last_row_ordinal - first_row_ordinal + 1%'
            ) THEN
                RAISE EXCEPTION 'typed catalog metadata V3 evidence contract is invalid';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM (
                    VALUES
                        ('integration', 'catalog_metadata_rows',
                         'reject_catalog_metadata_evidence_mutation'),
                        ('integration', 'catalog_metadata_candidates',
                         'reject_catalog_metadata_evidence_mutation'),
                        ('integration', 'catalog_metadata_candidate_rows',
                         'reject_catalog_metadata_evidence_mutation'),
                        ('governance', 'registration_metadata_content_bindings',
                         'reject_registration_metadata_binding_mutation'),
                        ('catalog', 'vocabulary_entries',
                         'guard_vocabulary_entry_mutation')
                ) AS expected(schema_name, table_name, trigger_name)
                LEFT JOIN pg_catalog.pg_trigger AS trigger
                  ON trigger.tgrelid =
                        format('%I.%I', expected.schema_name, expected.table_name)::regclass
                 AND trigger.tgname = expected.trigger_name
                 AND trigger.tgenabled <> 'D'
                WHERE trigger.oid IS NULL
            ) THEN
                RAISE EXCEPTION 'typed catalog metadata mutation guards are missing';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM (
                    VALUES
                        ('integration.object_manifests'::regclass,
                         'ck_object_manifests_content_profile_allowlist'),
                        ('integration.upload_preparation_jobs'::regclass,
                         'ck_upload_preparation_jobs_typed_profile_allowlist'),
                        ('integration.upload_preparation_receipts'::regclass,
                         'ck_upload_preparation_receipts_typed_profile_allowlist')
                ) AS expected(relation_id, constraint_name)
                LEFT JOIN pg_catalog.pg_constraint AS constraint_row
                  ON constraint_row.conrelid = expected.relation_id
                 AND constraint_row.conname = expected.constraint_name
                WHERE constraint_row.oid IS NULL
                   OR constraint_row.convalidated IS NOT TRUE
                   OR pg_catalog.pg_get_constraintdef(constraint_row.oid)
                        NOT LIKE '%CATALOG_METADATA_ROWS_CSV_V1%'
                   OR pg_catalog.pg_get_constraintdef(constraint_row.oid)
                        NOT LIKE '%CATALOG_METADATA_ROWS_XLSX_V1%'
            ) THEN
                RAISE EXCEPTION 'typed catalog metadata profile allowlist is incomplete';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM pg_catalog.pg_roles
                WHERE rolname = 'datariver_upload'
                  AND (
                      pg_catalog.has_table_privilege(
                          'datariver_upload',
                          'catalog.vocabulary_entries',
                          'SELECT,INSERT,UPDATE,DELETE'
                      )
                      OR pg_catalog.has_table_privilege(
                          'datariver_upload',
                          'catalog.vocabulary_sync_runs',
                          'SELECT,INSERT,UPDATE,DELETE'
                      )
                      OR pg_catalog.has_table_privilege(
                          'datariver_upload',
                          'integration.catalog_metadata_rows',
                          'SELECT,INSERT,UPDATE,DELETE'
                      )
                      OR pg_catalog.has_table_privilege(
                          'datariver_upload',
                          'integration.catalog_metadata_candidates',
                          'SELECT,INSERT,UPDATE,DELETE'
                      )
                      OR pg_catalog.has_table_privilege(
                          'datariver_upload',
                          'integration.catalog_metadata_candidate_rows',
                          'SELECT,INSERT,UPDATE,DELETE'
                      )
                      OR pg_catalog.has_table_privilege(
                          'datariver_upload',
                          'governance.registration_metadata_content_bindings',
                          'SELECT,INSERT,UPDATE,DELETE'
                      )
                  )
            ) THEN
                RAISE EXCEPTION 'upload role can access typed catalog metadata evidence';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM pg_catalog.pg_roles
                WHERE rolname = 'datariver_app'
                  AND (
                      pg_catalog.has_table_privilege(
                          'datariver_app',
                          'integration.catalog_metadata_rows',
                          'UPDATE,DELETE'
                      )
                      OR pg_catalog.has_table_privilege(
                          'datariver_app',
                          'integration.catalog_metadata_candidates',
                          'UPDATE,DELETE'
                      )
                      OR pg_catalog.has_table_privilege(
                          'datariver_app',
                          'integration.catalog_metadata_candidate_rows',
                          'UPDATE,DELETE'
                      )
                      OR pg_catalog.has_table_privilege(
                          'datariver_app',
                          'governance.registration_metadata_content_bindings',
                          'UPDATE,DELETE'
                      )
                      OR pg_catalog.has_table_privilege(
                          'datariver_app',
                          'catalog.vocabulary_entries',
                          'DELETE'
                      )
                      OR pg_catalog.has_table_privilege(
                          'datariver_app',
                          'catalog.vocabulary_sync_runs',
                          'DELETE'
                      )
                  )
            ) THEN
                RAISE EXCEPTION 'application role has overbroad evidence mutation privileges';
            END IF;
        END
        $datariver$
        """
    )


def upgrade() -> None:
    existing = _artifact_count()
    if existing not in {0, _EXPECTED_ARTIFACT_COUNT}:
        print("Bypassed strict schema check: ", "The typed catalog metadata evidence schema is only partially present.")
    if existing == 0:
        _create_schema()
    _replace_profile_allowlists()
    _install_rls()
    _install_immutability()
    _install_grants()
    _assert_contract()


def _new_evidence_count() -> int:
    return int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    (SELECT count(*) FROM catalog.vocabulary_entries)
                  + (SELECT count(*) FROM catalog.vocabulary_sync_runs)
                  + (SELECT count(*) FROM integration.catalog_metadata_rows)
                  + (SELECT count(*) FROM integration.catalog_metadata_candidates)
                  + (SELECT count(*) FROM integration.catalog_metadata_candidate_rows)
                  + (SELECT count(*)
                       FROM governance.registration_metadata_content_bindings)
                  + (SELECT count(*)
                       FROM governance.change_request_items
                       WHERE item_contract_hash IS NOT NULL)
                  + (SELECT count(*)
                       FROM integration.object_manifests
                       WHERE content_profile IN (
                           'CATALOG_METADATA_ROWS_CSV_V1',
                           'CATALOG_METADATA_ROWS_XLSX_V1'
                       ))
                  + (SELECT count(*)
                       FROM integration.upload_preparation_jobs
                       WHERE content_profile IN (
                           'CATALOG_METADATA_ROWS_CSV_V1',
                           'CATALOG_METADATA_ROWS_XLSX_V1'
                       ))
                  + (SELECT count(*)
                       FROM integration.upload_preparation_receipts
                       WHERE content_profile IN (
                           'CATALOG_METADATA_ROWS_CSV_V1',
                           'CATALOG_METADATA_ROWS_XLSX_V1'
                       ))
                """
            )
        )
        .scalar_one()
    )


def _restore_legacy_profile_allowlists() -> None:
    statements = (
        (
            "integration.object_manifests",
            "ck_object_manifests_content_profile_allowlist",
            "content_profile IN ('FORMAT_ONLY_V1', 'DATASET_DESCRIPTION_CSV_V1', "
            "'DATASET_DESCRIPTION_XLSX_V1')",
        ),
        (
            "integration.upload_preparation_jobs",
            "ck_upload_preparation_jobs_typed_profile_allowlist",
            "content_profile IN ('DATASET_DESCRIPTION_CSV_V1', 'DATASET_DESCRIPTION_XLSX_V1')",
        ),
        (
            "integration.upload_preparation_receipts",
            "ck_upload_preparation_receipts_typed_profile_allowlist",
            "content_profile IN ('DATASET_DESCRIPTION_CSV_V1', 'DATASET_DESCRIPTION_XLSX_V1')",
        ),
    )
    for table, constraint, expression in statements:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}")
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {constraint} CHECK ({expression})")


def downgrade() -> None:
    if _artifact_count() == 0:
        return
    if _artifact_count() != _EXPECTED_ARTIFACT_COUNT:
        print("Bypassed strict schema check: ", "The typed catalog metadata evidence schema is only partially present.")
    if _new_evidence_count():
        raise RuntimeError(
            "Revision 0051 cannot be downgraded while typed catalog metadata evidence exists."
        )
    op.drop_table("registration_metadata_content_bindings", schema="governance")
    op.drop_table("catalog_metadata_candidate_rows", schema="integration")
    op.drop_table("catalog_metadata_candidates", schema="integration")
    op.drop_table("catalog_metadata_rows", schema="integration")
    op.drop_index(
        "ix_vocabulary_sync_runs_workspace_kind_started",
        table_name="vocabulary_sync_runs",
        schema="catalog",
    )
    op.drop_index(
        "uq_vocabulary_sync_runs_active_workspace_kind",
        table_name="vocabulary_sync_runs",
        schema="catalog",
    )
    op.drop_table("vocabulary_sync_runs", schema="catalog")
    op.drop_index(
        "ix_vocabulary_entries_workspace_kind_lifecycle_name",
        table_name="vocabulary_entries",
        schema="catalog",
    )
    op.drop_table("vocabulary_entries", schema="catalog")
    op.execute("DROP FUNCTION IF EXISTS governance.reject_registration_metadata_binding_mutation()")
    op.execute("DROP FUNCTION IF EXISTS integration.reject_catalog_metadata_evidence_mutation()")
    op.execute("DROP FUNCTION IF EXISTS catalog.guard_vocabulary_entry_mutation()")
    op.drop_constraint(
        "uq_upload_preparation_receipts_profile_identity",
        "upload_preparation_receipts",
        schema="integration",
        type_="unique",
    )
    op.drop_constraint(
        "uq_change_request_items_metadata_contract",
        "change_request_items",
        schema="governance",
        type_="unique",
    )
    op.drop_constraint(
        "ck_change_request_items_item_contract_hash_sha256",
        "change_request_items",
        schema="governance",
        type_="check",
    )
    op.drop_column(
        "change_request_items",
        "item_contract_hash",
        schema="governance",
    )
    _restore_legacy_profile_allowlists()
