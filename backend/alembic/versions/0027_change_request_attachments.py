"""Persist private request and test evidence for a governed change request.

Revision ID: 0027
Revises: 0026
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | Sequence[str] | None = "0026"
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
                    CASE WHEN to_regclass('governance.change_request_attachments') IS NOT NULL
                        THEN 1 ELSE 0 END
                    + CASE WHEN to_regclass(
                        'governance.ix_change_request_attachments_request'
                      ) IS NOT NULL THEN 1 ELSE 0 END
                    + (SELECT count(*)
                       FROM pg_policies
                       WHERE schemaname = 'governance'
                         AND tablename = 'change_request_attachments'
                         AND policyname = 'workspace_isolation')
                """
            )
        )
        .scalar_one()
    )


def _install_security_contract() -> None:
    op.execute("ALTER TABLE governance.change_request_attachments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE governance.change_request_attachments FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE schemaname = 'governance'
                  AND tablename = 'change_request_attachments'
                  AND policyname = 'workspace_isolation'
            ) THEN
                CREATE POLICY workspace_isolation ON governance.change_request_attachments
                USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)
                WITH CHECK (
                    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid
                );
            END IF;
        END
        $datariver$
        """
    )
    op.execute("GRANT SELECT, INSERT ON governance.change_request_attachments TO datariver_app")


def upgrade() -> None:
    existing_objects = _existing_object_count()
    if existing_objects:
        if existing_objects != EXPECTED_OBJECT_COUNT:
            raise RuntimeError("The change-request attachment schema is only partially present.")
        _install_security_contract()
        return
    op.create_table(
        "change_request_attachments",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("change_request_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("original_name", sa.String(length=500), nullable=False),
        sa.Column("serial_number", sa.Integer(), nullable=False),
        sa.Column("bucket", sa.String(length=255), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "id"),
        sa.UniqueConstraint(
            "workspace_id",
            "change_request_id",
            "kind",
            "original_name",
            "serial_number",
            name="uq_change_request_attachment_serial",
        ),
        sa.ForeignKeyConstraint(
            ("workspace_id", "change_request_id"),
            ("governance.change_requests.workspace_id", "governance.change_requests.id"),
            name="fk_change_request_attachments_request",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("kind IN ('REQUEST', 'TEST')", name="kind_vocabulary"),
        sa.CheckConstraint("serial_number BETWEEN 1 AND 999999", name="serial_number_range"),
        sa.CheckConstraint("size_bytes BETWEEN 1 AND 10485760", name="size_bytes_range"),
        sa.CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256_valid"),
        schema="governance",
    )
    op.create_index(
        "ix_change_request_attachments_request",
        "change_request_attachments",
        ("workspace_id", "change_request_id"),
        schema="governance",
    )
    _install_security_contract()


def downgrade() -> None:
    # Compatibility migrations are intentionally forward-only.
    pass
