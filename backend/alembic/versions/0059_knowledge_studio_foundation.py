"""add persistent Knowledge Studio draft foundation

Revision ID: 0059
Revises: 0058
Create Date: 2026-07-28 12:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0059"
down_revision: str | Sequence[str] | None = "0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _reject_invalid_graph_rows() -> None:
    invalid = int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT count(*)
                FROM knowledge.graphs
                WHERE status NOT IN ('DRAFT', 'REVIEW', 'PUBLISHED')
                   OR classification NOT BETWEEN 0 AND 3
                """
            )
        )
        .scalar_one()
    )
    if invalid:
        raise RuntimeError(
            "Knowledge graph lifecycle/classification rows violate the Studio contract."
        )


def _create_studio_drafts() -> None:
    op.create_table(
        "studio_drafts",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("current_step", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("endpoint_alias", sa.String(length=100), nullable=False),
        sa.Column("domain_ref_id", sa.Uuid(), nullable=False),
        sa.Column("domain_ref_kind", sa.String(length=16), nullable=False),
        sa.Column("domain_source_version", sa.String(length=255), nullable=False),
        sa.Column("classification", sa.Integer(), nullable=False),
        sa.Column("base_graph_id", sa.Uuid(), nullable=True),
        sa.Column("base_ontology_version_id", sa.Uuid(), nullable=True),
        sa.Column("base_release_id", sa.Uuid(), nullable=True),
        sa.Column("review_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discarded_by", sa.Uuid(), nullable=True),
        sa.Column("last_autosaved_at", sa.DateTime(timezone=True), nullable=False),
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
            "(kind = 'CREATE' AND base_graph_id IS NULL "
            "AND base_ontology_version_id IS NULL AND base_release_id IS NULL) OR "
            "(kind = 'EDIT' AND base_graph_id IS NOT NULL "
            "AND base_ontology_version_id IS NOT NULL)",
            name=op.f("ck_studio_drafts_base_reference_shape"),
        ),
        sa.CheckConstraint(
            "classification BETWEEN 0 AND 3",
            name=op.f("ck_studio_drafts_classification_range"),
        ),
        sa.CheckConstraint(
            "current_step IN ('BASIC', 'TBOX', 'ABOX')",
            name=op.f("ck_studio_drafts_current_step_vocabulary"),
        ),
        sa.CheckConstraint(
            "domain_ref_kind = 'DOMAIN' AND char_length(domain_source_version) BETWEEN 1 AND 255",
            name=op.f("ck_studio_drafts_domain_reference_shape"),
        ),
        sa.CheckConstraint(
            "endpoint_alias ~ '^[a-z][a-z0-9_]{2,99}$'",
            name=op.f("ck_studio_drafts_endpoint_alias_shape"),
        ),
        sa.CheckConstraint(
            "kind IN ('CREATE', 'EDIT')",
            name=op.f("ck_studio_drafts_kind_vocabulary"),
        ),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 255 AND name = btrim(name)",
            name=op.f("ck_studio_drafts_name_valid"),
        ),
        sa.CheckConstraint(
            "(state = 'DRAFT' AND review_requested_at IS NULL "
            "AND published_at IS NULL AND discarded_at IS NULL AND discarded_by IS NULL) OR "
            "(state = 'REVIEW' AND review_requested_at IS NOT NULL "
            "AND published_at IS NULL AND discarded_at IS NULL AND discarded_by IS NULL) OR "
            "(state = 'PUBLISHED' AND review_requested_at IS NOT NULL "
            "AND published_at IS NOT NULL AND discarded_at IS NULL AND discarded_by IS NULL) OR "
            "(state = 'DISCARDED' AND published_at IS NULL "
            "AND discarded_at IS NOT NULL AND discarded_by = author_id)",
            name=op.f("ck_studio_drafts_state_shape"),
        ),
        sa.CheckConstraint(
            "state IN ('DRAFT', 'REVIEW', 'PUBLISHED', 'DISCARDED')",
            name=op.f("ck_studio_drafts_state_vocabulary"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "author_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name=op.f("fk_studio_drafts_workspace_id_author_id_workspace_memberships"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "base_graph_id", "base_ontology_version_id"],
            [
                "knowledge.ontology_versions.workspace_id",
                "knowledge.ontology_versions.graph_id",
                "knowledge.ontology_versions.id",
            ],
            name=op.f(
                "fk_studio_drafts_workspace_id_base_graph_id_"
                "base_ontology_version_id_ontology_versions"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "base_graph_id", "base_release_id"],
            [
                "knowledge.releases.workspace_id",
                "knowledge.releases.graph_id",
                "knowledge.releases.id",
            ],
            name=op.f("fk_studio_drafts_workspace_id_base_graph_id_base_release_id_releases"),
            ondelete="RESTRICT",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "base_graph_id"],
            ["knowledge.graphs.workspace_id", "knowledge.graphs.id"],
            name=op.f("fk_studio_drafts_workspace_id_base_graph_id_graphs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "discarded_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name=op.f("fk_studio_drafts_workspace_id_discarded_by_workspace_memberships"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "domain_ref_id", "domain_ref_kind"],
            [
                "catalog.vocabulary_entries.workspace_id",
                "catalog.vocabulary_entries.id",
                "catalog.vocabulary_entries.kind",
            ],
            name=op.f(
                "fk_studio_drafts_workspace_id_domain_ref_id_domain_ref_kind_vocabulary_entries"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_studio_drafts")),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name=op.f("uq_studio_drafts_workspace_id_id"),
        ),
        schema="knowledge",
    )
    op.create_index(
        "ix_studio_drafts_owner_updated",
        "studio_drafts",
        ["workspace_id", "author_id", "updated_at", "id"],
        unique=False,
        schema="knowledge",
    )
    op.create_index(
        "uq_studio_drafts_live_endpoint_alias",
        "studio_drafts",
        ["workspace_id", "endpoint_alias"],
        unique=True,
        schema="knowledge",
        postgresql_where=sa.text("state IN ('DRAFT', 'REVIEW')"),
    )
    op.execute("ALTER TABLE knowledge.studio_drafts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE knowledge.studio_drafts FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY workspace_isolation ON knowledge.studio_drafts
        USING (
            workspace_id =
            NULLIF(current_setting('app.workspace_id', true), '')::uuid
        )
        WITH CHECK (
            workspace_id =
            NULLIF(current_setting('app.workspace_id', true), '')::uuid
        )
        """
    )
    op.execute(
        """
        CREATE POLICY studio_draft_owner_access ON knowledge.studio_drafts
        AS RESTRICTIVE FOR ALL TO datariver_app
        USING (
            author_id =
            NULLIF(current_setting('app.subject_id', true), '')::uuid
        )
        WITH CHECK (
            author_id =
            NULLIF(current_setting('app.subject_id', true), '')::uuid
        )
        """
    )


def _grant_application_access() -> None:
    op.execute(
        """
        DO $grant$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
                GRANT SELECT, INSERT ON knowledge.studio_drafts TO datariver_app;
                GRANT UPDATE (
                    state, current_step, name, endpoint_alias,
                    domain_ref_id, domain_ref_kind, domain_source_version,
                    classification, review_requested_at, discarded_at,
                    discarded_by, last_autosaved_at,
                    version, updated_at
                ) ON knowledge.studio_drafts TO datariver_app;
            END IF;
        END
        $grant$
        """
    )


def upgrade() -> None:
    _reject_invalid_graph_rows()
    op.add_column(
        "graphs",
        sa.Column("domain_ref_id", sa.Uuid(), nullable=True),
        schema="knowledge",
    )
    op.add_column(
        "graphs",
        sa.Column("domain_ref_kind", sa.String(length=16), nullable=True),
        schema="knowledge",
    )
    op.add_column(
        "graphs",
        sa.Column("domain_source_version", sa.String(length=255), nullable=True),
        schema="knowledge",
    )
    op.add_column(
        "graphs",
        sa.Column("created_by", sa.Uuid(), nullable=True),
        schema="knowledge",
    )
    op.add_column(
        "graphs",
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        schema="knowledge",
    )
    op.create_check_constraint(
        op.f("ck_graphs_status_vocabulary"),
        "graphs",
        "status IN ('DRAFT', 'REVIEW', 'PUBLISHED')",
        schema="knowledge",
    )
    op.create_check_constraint(
        op.f("ck_graphs_classification_range"),
        "graphs",
        "classification BETWEEN 0 AND 3",
        schema="knowledge",
    )
    op.create_check_constraint(
        op.f("ck_graphs_domain_reference_shape"),
        "graphs",
        "(domain_ref_id IS NULL AND domain_ref_kind IS NULL "
        "AND domain_source_version IS NULL) OR "
        "(domain_ref_id IS NOT NULL AND domain_ref_kind = 'DOMAIN' "
        "AND domain_source_version IS NOT NULL)",
        schema="knowledge",
    )
    op.create_foreign_key(
        op.f("fk_graphs_workspace_id_domain_ref_id_domain_ref_kind_vocabulary_entries"),
        "graphs",
        "vocabulary_entries",
        ["workspace_id", "domain_ref_id", "domain_ref_kind"],
        ["workspace_id", "id", "kind"],
        source_schema="knowledge",
        referent_schema="catalog",
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_graphs_workspace_id_created_by_workspace_memberships"),
        "graphs",
        "workspace_memberships",
        ["workspace_id", "created_by"],
        ["workspace_id", "subject_id"],
        source_schema="knowledge",
        referent_schema="iam",
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_graphs_workspace_id_updated_by_workspace_memberships"),
        "graphs",
        "workspace_memberships",
        ["workspace_id", "updated_by"],
        ["workspace_id", "subject_id"],
        source_schema="knowledge",
        referent_schema="iam",
        ondelete="RESTRICT",
    )

    op.add_column(
        "ontology_versions",
        sa.Column("schema_contract_version", sa.String(length=50), nullable=True),
        schema="knowledge",
    )
    op.add_column(
        "ontology_versions",
        sa.Column("base_ontology_version_id", sa.Uuid(), nullable=True),
        schema="knowledge",
    )
    op.add_column(
        "ontology_versions",
        sa.Column("created_by", sa.Uuid(), nullable=True),
        schema="knowledge",
    )
    op.create_foreign_key(
        op.f(
            "fk_ontology_versions_workspace_id_graph_id_base_ontology_version_id_ontology_versions"
        ),
        "ontology_versions",
        "ontology_versions",
        ["workspace_id", "graph_id", "base_ontology_version_id"],
        ["workspace_id", "graph_id", "id"],
        source_schema="knowledge",
        referent_schema="knowledge",
        ondelete="RESTRICT",
        use_alter=True,
    )
    op.create_foreign_key(
        op.f("fk_ontology_versions_workspace_id_created_by_workspace_memberships"),
        "ontology_versions",
        "workspace_memberships",
        ["workspace_id", "created_by"],
        ["workspace_id", "subject_id"],
        source_schema="knowledge",
        referent_schema="iam",
        ondelete="RESTRICT",
    )

    _create_studio_drafts()
    _grant_application_access()


def downgrade() -> None:
    studio_rows = int(
        op.get_bind().execute(sa.text("SELECT count(*) FROM knowledge.studio_drafts")).scalar_one()
    )
    provenance_rows = int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    (SELECT count(*) FROM knowledge.graphs
                     WHERE domain_ref_id IS NOT NULL
                        OR created_by IS NOT NULL
                        OR updated_by IS NOT NULL)
                  + (SELECT count(*) FROM knowledge.ontology_versions
                     WHERE schema_contract_version IS NOT NULL
                        OR base_ontology_version_id IS NOT NULL
                        OR created_by IS NOT NULL)
                """
            )
        )
        .scalar_one()
    )
    if studio_rows or provenance_rows:
        raise RuntimeError(
            "Knowledge Studio/provenance data exists; downgrade would destroy canonical state."
        )

    op.drop_table("studio_drafts", schema="knowledge")

    op.drop_constraint(
        op.f("fk_ontology_versions_workspace_id_created_by_workspace_memberships"),
        "ontology_versions",
        schema="knowledge",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f(
            "fk_ontology_versions_workspace_id_graph_id_base_ontology_version_id_ontology_versions"
        ),
        "ontology_versions",
        schema="knowledge",
        type_="foreignkey",
    )
    op.drop_column("ontology_versions", "created_by", schema="knowledge")
    op.drop_column("ontology_versions", "base_ontology_version_id", schema="knowledge")
    op.drop_column("ontology_versions", "schema_contract_version", schema="knowledge")

    op.drop_constraint(
        op.f("fk_graphs_workspace_id_updated_by_workspace_memberships"),
        "graphs",
        schema="knowledge",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_graphs_workspace_id_created_by_workspace_memberships"),
        "graphs",
        schema="knowledge",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_graphs_workspace_id_domain_ref_id_domain_ref_kind_vocabulary_entries"),
        "graphs",
        schema="knowledge",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("ck_graphs_domain_reference_shape"),
        "graphs",
        schema="knowledge",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_graphs_classification_range"),
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
    op.drop_column("graphs", "updated_by", schema="knowledge")
    op.drop_column("graphs", "created_by", schema="knowledge")
    op.drop_column("graphs", "domain_source_version", schema="knowledge")
    op.drop_column("graphs", "domain_ref_kind", schema="knowledge")
    op.drop_column("graphs", "domain_ref_id", schema="knowledge")
