"""add managed Knowledge domains and endpoint alias arrays

Revision ID: 0066
Revises: 0065
Create Date: 2026-07-29 12:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0066"
down_revision: str | Sequence[str] | None = "0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _canonical_contract_is_complete() -> bool:
    inspector = sa.inspect(op.get_bind())
    vocabulary_columns = {
        column["name"] for column in inspector.get_columns("vocabulary_entries", schema="catalog")
    }
    draft_columns = {
        column["name"] for column in inspector.get_columns("studio_drafts", schema="knowledge")
    }
    proposal_columns = {
        column["name"] for column in inspector.get_columns("tbox_proposals", schema="knowledge")
    }
    expected = (
        {"created_by", "version"} <= vocabulary_columns
        and "endpoint_aliases" in draft_columns
        and "source_reference_document" in proposal_columns
    )
    indicators = (
        bool({"created_by", "version"} & vocabulary_columns)
        or "endpoint_aliases" in draft_columns
        or "source_reference_document" in proposal_columns
    )
    if indicators and not expected:
        raise RuntimeError("Partial canonical managed Knowledge domain schema detected.")
    return expected


def upgrade() -> None:
    if _canonical_contract_is_complete():
        return
    op.add_column(
        "vocabulary_entries",
        sa.Column("created_by", sa.Uuid(), nullable=True),
        schema="catalog",
    )
    op.add_column(
        "vocabulary_entries",
        sa.Column("version", sa.Integer(), nullable=True),
        schema="catalog",
    )
    op.execute("UPDATE catalog.vocabulary_entries SET version = 1 WHERE version IS NULL")
    op.alter_column(
        "vocabulary_entries",
        "version",
        nullable=False,
        schema="catalog",
    )
    op.create_check_constraint(
        op.f("ck_vocabulary_entries_version_positive"),
        "vocabulary_entries",
        "version >= 1",
        schema="catalog",
    )
    op.create_foreign_key(
        op.f("fk_vocabulary_entries_workspace_id_created_by_workspace_memberships"),
        "vocabulary_entries",
        "workspace_memberships",
        ["workspace_id", "created_by"],
        ["workspace_id", "subject_id"],
        source_schema="catalog",
        referent_schema="iam",
        ondelete="RESTRICT",
    )

    op.add_column(
        "studio_drafts",
        sa.Column(
            "endpoint_aliases",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        schema="knowledge",
    )
    op.execute(
        """
        UPDATE knowledge.studio_drafts
        SET endpoint_aliases = jsonb_build_array(endpoint_alias)
        WHERE endpoint_aliases IS NULL
        """
    )
    op.alter_column(
        "studio_drafts",
        "endpoint_aliases",
        nullable=False,
        schema="knowledge",
    )
    op.create_check_constraint(
        op.f("ck_studio_drafts_endpoint_aliases_shape"),
        "studio_drafts",
        "jsonb_typeof(endpoint_aliases) = 'array' "
        "AND jsonb_array_length(endpoint_aliases) BETWEEN 1 AND 10 "
        "AND endpoint_aliases ->> 0 = endpoint_alias",
        schema="knowledge",
    )
    op.create_index(
        "ix_studio_drafts_workspace_endpoint_aliases_live",
        "studio_drafts",
        ["endpoint_aliases"],
        unique=False,
        schema="knowledge",
        postgresql_using="gin",
        postgresql_where=sa.text("state IN ('DRAFT', 'REVIEW')"),
    )
    op.add_column(
        "tbox_proposals",
        sa.Column(
            "source_reference_document",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        schema="knowledge",
    )
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'datariver_app'
            ) THEN
                GRANT UPDATE (version)
                    ON catalog.vocabulary_entries TO datariver_app;
                GRANT UPDATE (
                    endpoint_aliases
                ) ON knowledge.studio_drafts TO datariver_app;
            END IF;
        END
        $datariver$
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $datariver$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'datariver_app'
            ) THEN
                REVOKE UPDATE (endpoint_aliases)
                    ON knowledge.studio_drafts FROM datariver_app;
                REVOKE UPDATE (version)
                    ON catalog.vocabulary_entries FROM datariver_app;
            END IF;
        END
        $datariver$
        """
    )
    op.drop_index(
        "ix_studio_drafts_workspace_endpoint_aliases_live",
        table_name="studio_drafts",
        schema="knowledge",
        postgresql_using="gin",
    )
    op.drop_constraint(
        op.f("ck_studio_drafts_endpoint_aliases_shape"),
        "studio_drafts",
        schema="knowledge",
        type_="check",
    )
    op.drop_column("studio_drafts", "endpoint_aliases", schema="knowledge")
    op.drop_column(
        "tbox_proposals",
        "source_reference_document",
        schema="knowledge",
    )
    op.drop_constraint(
        op.f("fk_vocabulary_entries_workspace_id_created_by_workspace_memberships"),
        "vocabulary_entries",
        schema="catalog",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("ck_vocabulary_entries_version_positive"),
        "vocabulary_entries",
        schema="catalog",
        type_="check",
    )
    op.drop_column("vocabulary_entries", "version", schema="catalog")
    op.drop_column("vocabulary_entries", "created_by", schema="catalog")
