"""seed Knowledge domains and add governed graph archival

Revision ID: 0062
Revises: 0061
Create Date: 2026-07-28 18:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0062"
down_revision: str | Sequence[str] | None = "0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _seed_default_domains() -> None:
    # Use the driver's SQL path so the canonical-id separator is not parsed as
    # a SQLAlchemy ``:bind_parameter`` inside this literal migration statement.
    op.get_bind().exec_driver_sql(
        """
        INSERT INTO catalog.vocabulary_entries (
            id,
            workspace_id,
            kind,
            provider_ref,
            display_name,
            lifecycle,
            source_version,
            observed_at,
            updated_at
        )
        SELECT
            md5(
                workspace.id::text || ':knowledge-default-domain:' || value.slug
            )::uuid,
            workspace.id,
            'DOMAIN',
            'urn:li:domain:datariver-default-' || value.slug,
            value.display_name,
            'ACTIVE',
            'datariver-default-domains-v1',
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        FROM platform.workspaces AS workspace
        CROSS JOIN (
            VALUES
                ('general', 'General'),
                ('data-governance', 'Data Governance'),
                ('research-development', 'R&D'),
                ('finance', 'Finance'),
                ('space-system', 'Space System')
        ) AS value(slug, display_name)
        ON CONFLICT (workspace_id, kind, provider_ref) DO NOTHING
        """
    )


def upgrade() -> None:
    op.add_column(
        "graphs",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        schema="knowledge",
    )
    op.add_column(
        "graphs",
        sa.Column("archived_by", sa.Uuid(), nullable=True),
        schema="knowledge",
    )
    op.create_foreign_key(
        op.f("fk_graphs_workspace_id_archived_by_workspace_memberships"),
        "graphs",
        "workspace_memberships",
        ["workspace_id", "archived_by"],
        ["workspace_id", "subject_id"],
        source_schema="knowledge",
        referent_schema="iam",
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        op.f("ck_graphs_status_vocabulary"),
        "graphs",
        schema="knowledge",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_graphs_status_vocabulary"),
        "graphs",
        "status IN ('DRAFT', 'REVIEW', 'PUBLISHED', 'ARCHIVED')",
        schema="knowledge",
    )
    op.create_check_constraint(
        op.f("ck_graphs_archive_shape"),
        "graphs",
        "(status = 'ARCHIVED' AND archived_at IS NOT NULL AND archived_by IS NOT NULL) "
        "OR (status <> 'ARCHIVED' AND archived_at IS NULL AND archived_by IS NULL)",
        schema="knowledge",
    )
    _seed_default_domains()


def downgrade() -> None:
    archived = int(
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM knowledge.graphs WHERE status = 'ARCHIVED'"))
        .scalar_one()
    )
    if archived:
        raise RuntimeError(
            "Archived Knowledge graph evidence must be restored before downgrading revision 0062."
        )
    op.drop_constraint(
        op.f("ck_graphs_archive_shape"),
        "graphs",
        schema="knowledge",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_graphs_status_vocabulary"),
        "graphs",
        schema="knowledge",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_graphs_status_vocabulary"),
        "graphs",
        "status IN ('DRAFT', 'REVIEW', 'PUBLISHED')",
        schema="knowledge",
    )
    op.drop_constraint(
        op.f("fk_graphs_workspace_id_archived_by_workspace_memberships"),
        "graphs",
        schema="knowledge",
        type_="foreignkey",
    )
    op.drop_column("graphs", "archived_by", schema="knowledge")
    op.drop_column("graphs", "archived_at", schema="knowledge")
