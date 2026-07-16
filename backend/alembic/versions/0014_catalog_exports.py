"""Add snapshot-bound governed catalog export requests.

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "export_requests",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("request_document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("permission_scope_hash", sa.String(length=64), nullable=False),
        sa.Column("classification_access_hash", sa.String(length=64), nullable=False),
        sa.Column("builtin_policy_version", sa.String(length=100), nullable=False),
        sa.Column("classification_policy_id", sa.Uuid(), nullable=True),
        sa.Column("classification_policy_hash", sa.String(length=64), nullable=True),
        sa.Column("classification_policy_version", sa.Integer(), nullable=True),
        sa.Column("authorization_generation", sa.BigInteger(), nullable=True),
        sa.Column("source_projection_version", sa.BigInteger(), nullable=False),
        sa.Column("classification_ceiling", sa.Integer(), nullable=False),
        sa.Column("csv_safety_version", sa.String(length=32), nullable=False),
        sa.Column("object_bucket", sa.String(length=255), nullable=True),
        sa.Column("object_key", sa.Text(), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("mime", sa.String(length=100), nullable=False),
        sa.Column("row_count", sa.BigInteger(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("provider_checksum", sa.String(length=255), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("access_until", sa.DateTime(timezone=True), nullable=False),
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
            "classification_access_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_export_requests_classification_access_hash_sha256"),
        ),
        sa.CheckConstraint(
            "permission_scope_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_export_requests_permission_scope_hash_sha256"),
        ),
        sa.CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_export_requests_request_hash_sha256"),
        ),
        sa.CheckConstraint(
            "classification_ceiling BETWEEN 0 AND 2",
            name=op.f("ck_export_requests_classification_ceiling_nonrestricted"),
        ),
        sa.CheckConstraint(
            "content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_export_requests_content_sha256_valid"),
        ),
        sa.CheckConstraint(
            "(object_bucket IS NULL AND object_key IS NULL AND row_count IS NULL "
            "AND size_bytes IS NULL AND content_sha256 IS NULL AND completed_at IS NULL) "
            "OR (object_bucket IS NOT NULL AND object_key IS NOT NULL AND row_count IS NOT NULL "
            "AND size_bytes IS NOT NULL AND content_sha256 IS NOT NULL "
            "AND completed_at IS NOT NULL)",
            name=op.f("ck_export_requests_artifact_shape"),
        ),
        sa.CheckConstraint(
            "(classification_policy_id IS NULL AND classification_policy_hash IS NULL "
            "AND classification_policy_version IS NULL AND authorization_generation IS NULL) "
            "OR (classification_policy_id IS NOT NULL AND classification_policy_hash IS NOT NULL "
            "AND classification_policy_version IS NOT NULL "
            "AND authorization_generation IS NOT NULL)",
            name=op.f("ck_export_requests_classification_policy_binding_shape"),
        ),
        sa.CheckConstraint(
            "row_count IS NULL OR row_count >= 0",
            name=op.f("ck_export_requests_row_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0",
            name=op.f("ck_export_requests_size_bytes_nonnegative"),
        ),
        sa.CheckConstraint(
            "source_projection_version >= 0",
            name=op.f("ck_export_requests_source_projection_version_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "job_id"],
            ["integration.jobs.workspace_id", "integration.jobs.id"],
            name="fk_catalog_export_requests_workspace_job",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "requested_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name=op.f("fk_export_requests_workspace_id_requested_by_workspace_memberships"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_export_requests")),
        sa.UniqueConstraint(
            "object_bucket",
            "object_key",
            name=op.f("uq_export_requests_object_bucket_object_key"),
        ),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_export_requests_workspace_id_id")),
        sa.UniqueConstraint(
            "workspace_id",
            "job_id",
            name=op.f("uq_export_requests_workspace_id_job_id"),
        ),
        schema="catalog",
    )
    op.create_index(
        "ix_catalog_exports_owner_time",
        "export_requests",
        ["workspace_id", "requested_by", "created_at"],
        unique=False,
        schema="catalog",
    )
    op.execute("ALTER TABLE catalog.export_requests ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE catalog.export_requests FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY workspace_isolation ON catalog.export_requests "
        "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) "
        "WITH CHECK (workspace_id = "
        "NULLIF(current_setting('app.workspace_id', true), '')::uuid)"
    )
    op.execute(
        "CREATE POLICY catalog_export_owner_select ON catalog.export_requests "
        "AS RESTRICTIVE FOR SELECT USING (current_user <> 'datariver_app' OR requested_by = "
        "NULLIF(current_setting('app.subject_id', true), '')::uuid)"
    )
    op.execute(
        "DO $datariver$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN "
        "GRANT SELECT, INSERT ON catalog.export_requests TO datariver_app; "
        "GRANT INSERT ON integration.jobs TO datariver_app; "
        "END IF; END $datariver$"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_catalog_exports_owner_time",
        table_name="export_requests",
        schema="catalog",
    )
    op.drop_table("export_requests", schema="catalog")
