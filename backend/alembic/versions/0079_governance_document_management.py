"""Add versioned Governance hierarchy and readable attachment object metadata.

Revision ID: 0079
Revises: 0078
Create Date: 2026-07-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0079"
down_revision: str | Sequence[str] | None = "0078"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PARENT_MUTATION_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION governance.reject_document_parent_mutation_v1()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.parent_document_id IS DISTINCT FROM OLD.parent_document_id THEN
        RAISE EXCEPTION
            'Governance Document version hierarchy is immutable'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END
$$;
""".strip()

_PARENT_MUTATION_TRIGGER_SQL = """
CREATE TRIGGER reject_document_parent_mutation
BEFORE UPDATE ON governance.document_versions
FOR EACH ROW
EXECUTE FUNCTION governance.reject_document_parent_mutation_v1();
""".strip()

_ATTACHMENT_MUTATION_TRIGGER_SQL = """
CREATE TRIGGER reject_document_attachment_mutation
BEFORE UPDATE OR DELETE ON governance.document_attachments
FOR EACH ROW
EXECUTE FUNCTION governance.reject_document_evidence_mutation_v1();
""".strip()


def upgrade() -> None:
    if "published_by" in [c["name"] for c in sa.inspect(op.get_bind()).get_columns("documents", schema="governance")]: return
    op.add_column(
        "document_versions",
        sa.Column("parent_document_id", sa.Uuid(), nullable=True),
        schema="governance",
    )
    op.create_foreign_key(
        "fk_governance_document_versions_parent",
        "document_versions",
        "documents",
        ["workspace_id", "parent_document_id"],
        ["workspace_id", "id"],
        source_schema="governance",
        referent_schema="governance",
        ondelete="RESTRICT",
        use_alter=True,
    )
    op.create_check_constraint(
        "ck_document_versions_parent_document_distinct",
        "document_versions",
        "parent_document_id IS NULL OR parent_document_id <> document_id",
        schema="governance",
    )
    op.create_index("ix_governance_document_versions_parent",
        "document_versions",
        ["workspace_id", "parent_document_id", "state"],
        schema="governance",
        postgresql_where=sa.text("parent_document_id IS NOT NULL"),
     if_not_exists=True)

    op.add_column(
        "document_attachments",
        sa.Column("serial_number", sa.Integer(), nullable=True),
        schema="governance",
    )
    op.add_column(
        "document_attachments",
        sa.Column("storage_filename", sa.String(length=255), nullable=True),
        schema="governance",
    )
    # Revision 0075 made attachment evidence immutable. Temporarily remove only
    # that trigger so this controlled, deterministic schema backfill can run.
    op.execute(
        "DROP TRIGGER reject_document_attachment_mutation ON governance.document_attachments"
    )
    op.execute(
        """
        WITH numbered AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY workspace_id, document_version_id
                       ORDER BY created_at, id
                   ) AS serial_number
            FROM governance.document_attachments
        )
        UPDATE governance.document_attachments AS attachment
        SET serial_number = numbered.serial_number
        FROM numbered
        WHERE numbered.id = attachment.id
        """
    )
    op.execute(_ATTACHMENT_MUTATION_TRIGGER_SQL)
    op.alter_column(
        "document_attachments",
        "serial_number",
        existing_type=sa.Integer(),
        nullable=False,
        schema="governance",
    )
    op.create_check_constraint(
        "ck_document_attachments_serial_number_range",
        "document_attachments",
        "serial_number BETWEEN 1 AND 25",
        schema="governance",
    )
    op.create_unique_constraint(
        "uq_governance_document_attachments_serial",
        "document_attachments",
        ["workspace_id", "document_version_id", "serial_number"],
        schema="governance",
    )
    op.execute(_PARENT_MUTATION_FUNCTION_SQL)
    op.execute(_PARENT_MUTATION_TRIGGER_SQL)


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM governance.document_versions
                WHERE parent_document_id IS NOT NULL
            ) OR EXISTS (
                SELECT 1
                FROM governance.document_attachments
                WHERE storage_filename IS NOT NULL
            ) THEN
                RAISE EXCEPTION
                    '0079 downgrade refused: Governance management evidence exists';
            END IF;
        END
        $$;
        """
    )
    op.execute("DROP TRIGGER reject_document_parent_mutation ON governance.document_versions")
    op.execute("DROP FUNCTION governance.reject_document_parent_mutation_v1()")
    op.drop_constraint(
        "uq_governance_document_attachments_serial",
        "document_attachments",
        schema="governance",
        type_="unique",
    )
    op.drop_constraint(
        "ck_document_attachments_serial_number_range",
        "document_attachments",
        schema="governance",
        type_="check",
    )
    op.drop_column("document_attachments", "storage_filename", schema="governance")
    op.drop_column("document_attachments", "serial_number", schema="governance")
    op.drop_index(
        "ix_governance_document_versions_parent",
        table_name="document_versions",
        schema="governance",
    )
    op.drop_constraint(
        "ck_document_versions_parent_document_distinct",
        "document_versions",
        schema="governance",
        type_="check",
    )
    op.drop_constraint(
        "fk_governance_document_versions_parent",
        "document_versions",
        schema="governance",
        type_="foreignkey",
    )
    op.drop_column("document_versions", "parent_document_id", schema="governance")
