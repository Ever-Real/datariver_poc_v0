"""Persist governed Knowledge source analysis, GraphRAG audit, and verified projection evidence.

Revision ID: 0037
Revises: 0036
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0037"
down_revision: str | Sequence[str] | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
EXPECTED_OBJECT_COUNT = 16


def _existing_object_count() -> int:
    return int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    (SELECT count(*) FROM information_schema.columns
                     WHERE table_schema = 'knowledge'
                       AND table_name = 'projection_deployments'
                       AND column_name IN (
                         'graph_id', 'job_id', 'verification_hash', 'verified_at', 'error_code'))
                    + (SELECT count(*) FROM pg_class AS item
                       JOIN pg_namespace AS namespace ON namespace.oid = item.relnamespace
                       WHERE namespace.nspname = 'knowledge'
                         AND item.relname IN (
                           'source_snapshots', 'source_pages', 'source_page_embeddings',
                           'extraction_runs', 'graphrag_audits')
                         AND item.relkind = 'r')
                    + (SELECT count(*) FROM pg_constraint
                       WHERE conrelid = to_regclass('knowledge.projection_deployments')
                         AND conname LIKE
                           'fk_projection_deployments_workspace_id_graph_id_release_%')
                    + (SELECT count(*) FROM pg_policies
                       WHERE schemaname = 'knowledge'
                         AND tablename IN (
                           'source_snapshots', 'source_pages', 'source_page_embeddings',
                           'extraction_runs', 'graphrag_audits')
                         AND policyname = 'workspace_isolation')
                """
            )
        )
        .scalar_one()
    )


def _install_security_contract() -> None:
    op.execute(
        """DO $datariver$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
            GRANT SELECT, INSERT, UPDATE ON knowledge.source_snapshots TO datariver_app;
            GRANT SELECT, INSERT ON knowledge.source_pages,
                knowledge.source_page_embeddings, knowledge.extraction_runs,
                knowledge.graphrag_audits TO datariver_app;
            GRANT SELECT, INSERT, UPDATE ON knowledge.projection_deployments TO datariver_app;
        END IF;
        END $datariver$"""
    )


def _workspace_rls(table_name: str) -> None:
    op.execute(f"ALTER TABLE knowledge.{table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE knowledge.{table_name} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY workspace_isolation ON knowledge.{table_name} "
        "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid) "
        "WITH CHECK (workspace_id = "
        "NULLIF(current_setting('app.workspace_id', true), '')::uuid)"
    )


def upgrade() -> None:
    existing_objects = _existing_object_count()
    if existing_objects:
        if existing_objects != EXPECTED_OBJECT_COUNT:
            raise RuntimeError("The Knowledge pipeline schema is only partially present.")
        _install_security_contract()
        return
    op.add_column(
        "projection_deployments",
        sa.Column("graph_id", sa.Uuid(), nullable=True),
        schema="knowledge",
    )
    op.add_column(
        "projection_deployments", sa.Column("job_id", sa.Uuid(), nullable=True), schema="knowledge"
    )
    op.add_column(
        "projection_deployments",
        sa.Column("verification_hash", sa.String(length=64), nullable=True),
        schema="knowledge",
    )
    op.add_column(
        "projection_deployments",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        schema="knowledge",
    )
    op.add_column(
        "projection_deployments",
        sa.Column("error_code", sa.String(length=100), nullable=True),
        schema="knowledge",
    )
    op.execute(
        """UPDATE knowledge.projection_deployments AS deployment
        SET graph_id = release.graph_id
        FROM knowledge.releases AS release
        WHERE release.workspace_id = deployment.workspace_id
          AND release.id = deployment.release_id"""
    )
    op.alter_column("projection_deployments", "graph_id", nullable=False, schema="knowledge")
    op.drop_constraint(
        op.f("fk_projection_deployments_workspace_id_release_id_releases"),
        "projection_deployments",
        schema="knowledge",
        type_="foreignkey",
    )
    op.create_foreign_key(
        op.f("fk_projection_deployments_workspace_id_graph_id_release_id_releases"),
        "projection_deployments",
        "releases",
        ["workspace_id", "graph_id", "release_id"],
        ["workspace_id", "graph_id", "id"],
        source_schema="knowledge",
        referent_schema="knowledge",
        ondelete="CASCADE",
    )

    op.create_table(
        "source_snapshots",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("graph_id", sa.Uuid(), nullable=False),
        sa.Column("upload_id", sa.Uuid(), nullable=False),
        sa.Column("bucket", sa.String(length=255), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("storage_version", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=100), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("classification", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint(
            "byte_size > 0 AND byte_size <= 52428800", name="ck_source_snapshots_bounded_size"
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_source_snapshots_content_sha256"
        ),
        sa.CheckConstraint(
            "media_type = 'application/pdf'", name="ck_source_snapshots_pdf_media_type"
        ),
        sa.CheckConstraint(
            "state IN ('PENDING', 'ANALYZED', 'FAILED')",
            name="ck_source_snapshots_state_vocabulary",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id"],
            ["knowledge.graphs.workspace_id", "knowledge.graphs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "upload_id"],
            ["integration.object_manifests.workspace_id", "integration.object_manifests.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "graph_id", "upload_id"),
        sa.UniqueConstraint("workspace_id", "id"),
        schema="knowledge",
    )
    op.create_index(
        "ix_source_snapshots_graph_created",
        "source_snapshots",
        ["graph_id", "created_at"],
        schema="knowledge",
    )
    _workspace_rls("source_snapshots")

    op.create_table(
        "source_pages",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_source_pages_content_sha256"
        ),
        sa.CheckConstraint("page_number > 0", name="ck_source_pages_page_number_positive"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_snapshot_id"],
            ["knowledge.source_snapshots.workspace_id", "knowledge.source_snapshots.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "source_snapshot_id", "page_number"),
        schema="knowledge",
    )
    _workspace_rls("source_pages")

    op.create_table(
        "source_page_embeddings",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model_identity", sa.String(length=200), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("embedding", postgresql.JSONB(none_as_null=True), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
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
        sa.CheckConstraint(
            "dimension > 0 AND dimension <= 16384",
            name="ck_source_page_embeddings_bounded_dimension",
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_source_page_embeddings_content_sha256"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_snapshot_id", "page_number"],
            [
                "knowledge.source_pages.workspace_id",
                "knowledge.source_pages.source_snapshot_id",
                "knowledge.source_pages.page_number",
            ],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_snapshot_id", "page_number", "provider", "model_identity"),
        schema="knowledge",
    )
    op.create_index(
        "ix_source_page_embeddings_source",
        "source_page_embeddings",
        ["source_snapshot_id", "page_number"],
        schema="knowledge",
    )
    _workspace_rls("source_page_embeddings")

    op.create_table(
        "extraction_runs",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("graph_id", sa.Uuid(), nullable=False),
        sa.Column("source_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("proposed_changeset_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("parser_config_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding_binding", postgresql.JSONB(none_as_null=True), nullable=False),
        sa.Column("extraction_binding", postgresql.JSONB(none_as_null=True), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("output_hash", sa.String(length=64), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
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
        sa.CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="ck_extraction_runs_input_hash"),
        sa.CheckConstraint("output_hash ~ '^[0-9a-f]{64}$'", name="ck_extraction_runs_output_hash"),
        sa.CheckConstraint(
            "state IN ('SUCCEEDED', 'FAILED')", name="ck_extraction_runs_state_vocabulary"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id"],
            ["knowledge.graphs.workspace_id", "knowledge.graphs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "proposed_changeset_id"],
            ["knowledge.changesets.workspace_id", "knowledge.changesets.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_snapshot_id"],
            ["knowledge.source_snapshots.workspace_id", "knowledge.source_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "id"),
        schema="knowledge",
    )
    op.create_index(
        "ix_extraction_runs_graph_created",
        "extraction_runs",
        ["graph_id", "created_at"],
        schema="knowledge",
    )
    _workspace_rls("extraction_runs")

    op.create_table(
        "graphrag_audits",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("graph_id", sa.Uuid(), nullable=False),
        sa.Column("release_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.String(length=100), nullable=False),
        sa.Column("question_sha256", sa.String(length=64), nullable=False),
        sa.Column("evidence_ids", postgresql.JSONB(none_as_null=True), nullable=False),
        sa.Column("cited_evidence_ids", postgresql.JSONB(none_as_null=True), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model_identity", sa.String(length=200), nullable=False),
        sa.Column("prompt_version", sa.String(length=200), nullable=False),
        sa.Column("tool_schema_version", sa.String(length=200), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
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
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ck_graphrag_audits_input_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_graphrag_audits_output_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "question_sha256 ~ '^[0-9a-f]{64}$'", name="ck_graphrag_audits_question_sha256"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id", "release_id"],
            [
                "knowledge.releases.workspace_id",
                "knowledge.releases.graph_id",
                "knowledge.releases.id",
            ],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "request_id"),
        schema="knowledge",
    )
    op.create_index(
        "ix_graphrag_audits_release_created",
        "graphrag_audits",
        ["release_id", "created_at"],
        schema="knowledge",
    )
    _workspace_rls("graphrag_audits")

    _install_security_contract()


def downgrade() -> None:
    # Compatibility bridge: regenerated 0001 owns the canonical Knowledge pipeline schema.
    pass
