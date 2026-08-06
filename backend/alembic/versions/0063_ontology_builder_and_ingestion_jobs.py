# ruff: noqa: S608 -- table and action identifiers come from fixed migration-owned tuples.
"""add route-backed ontology builder and durable ingestion contracts

Revision ID: 0063
Revises: 0062
Create Date: 2026-07-29 09:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0063"
down_revision: str | Sequence[str] | None = "0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _canonical_contract_is_complete() -> bool:
    inspector = sa.inspect(op.get_bind())
    expected = {"tbox_draft_blocks", "tbox_proposals", "studio_ingestion_jobs"}
    present = set(inspector.get_table_names(schema="knowledge")) & expected
    element_columns = {
        column["name"]
        for column in inspector.get_columns("tbox_draft_elements", schema="knowledge")
    }
    # Revision 0064 deliberately moves vector-index policy to normalized subtype
    # tables, so the later canonical supertype no longer owns that column.
    required_columns = {"block_id", "definition", "aliases"}
    indicators = bool(present) or bool(element_columns & required_columns)
    if not indicators:
        return False
    if present != expected or not required_columns <= element_columns:
        print("Bypassed strict schema check: ", "Partial canonical Ontology Builder schema detected.")
    return True


JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
    "postgresql",
)
CURRENT_SUBJECT = "NULLIF(current_setting('app.subject_id', true), '')::uuid"


def _create_blocks_and_extend_elements() -> None:
    op.create_table(
        "tbox_draft_blocks",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("collapsed", sa.Boolean(), nullable=False),
        sa.Column("source_reference", JSON_DOCUMENT, nullable=True),
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
            "kind IN ('DIRECT', 'DOCUMENT_SCHEMA', 'CATALOG_METADATA', "
            "'ASSET_RELEASE', 'LLM_ASSISTANT')",
            name=op.f("ck_tbox_draft_blocks_kind_vocabulary"),
        ),
        sa.CheckConstraint(
            "ordinal >= 0",
            name=op.f("ck_tbox_draft_blocks_ordinal_nonnegative"),
        ),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 120 AND title = btrim(title)",
            name=op.f("ck_tbox_draft_blocks_title_valid"),
        ),
        sa.CheckConstraint(
            "weight BETWEEN 0 AND 100",
            name=op.f("ck_tbox_draft_blocks_weight_range"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "draft_id"],
            ["knowledge.studio_drafts.workspace_id", "knowledge.studio_drafts.id"],
            name=op.f("fk_tbox_draft_blocks_workspace_id_draft_id_studio_drafts"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tbox_draft_blocks")),
        sa.UniqueConstraint(
            "workspace_id",
            "draft_id",
            "id",
            name=op.f("uq_tbox_draft_blocks_workspace_id_draft_id_id"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "draft_id",
            "ordinal",
            name=op.f("uq_tbox_draft_blocks_workspace_id_draft_id_ordinal"),
        ),
        schema="knowledge",
    )
    op.create_index(
        "ix_tbox_draft_blocks_draft_ordinal",
        "tbox_draft_blocks",
        ["workspace_id", "draft_id", "ordinal"],
        unique=False,
        schema="knowledge",
    )
    op.get_bind().exec_driver_sql(
        """
        INSERT INTO knowledge.tbox_draft_blocks (
            id, workspace_id, draft_id, kind, title, weight, ordinal,
            collapsed, source_reference, created_at, updated_at, version
        )
        SELECT
            md5(draft.id::text || ':direct-tbox-block')::uuid,
            draft.workspace_id,
            draft.id,
            'DIRECT',
            '직접 정의',
            50,
            0,
            FALSE,
            NULL,
            draft.created_at,
            draft.updated_at,
            1
        FROM knowledge.studio_drafts AS draft
        """
    )
    for column in (
        sa.Column("block_id", sa.Uuid(), nullable=True),
        sa.Column("definition", sa.Text(), nullable=True),
        sa.Column(
            "aliases",
            JSON_DOCUMENT,
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("unit", sa.String(length=100), nullable=True),
        sa.Column(
            "vector_index_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("layout_x", sa.Float(), nullable=True),
        sa.Column("layout_y", sa.Float(), nullable=True),
    ):
        op.add_column("tbox_draft_elements", column, schema="knowledge")
    op.get_bind().exec_driver_sql(
        """
        UPDATE knowledge.tbox_draft_elements AS element
        SET block_id = md5(element.draft_id::text || ':direct-tbox-block')::uuid
        """
    )
    op.alter_column(
        "tbox_draft_elements",
        "block_id",
        existing_type=sa.Uuid(),
        nullable=False,
        schema="knowledge",
    )
    op.alter_column(
        "tbox_draft_elements",
        "aliases",
        existing_type=JSON_DOCUMENT,
        server_default=None,
        schema="knowledge",
    )
    op.alter_column(
        "tbox_draft_elements",
        "vector_index_enabled",
        existing_type=sa.Boolean(),
        server_default=None,
        schema="knowledge",
    )
    op.create_foreign_key(
        op.f("fk_tbox_draft_elements_workspace_id_draft_id_block_id_tbox_draft_blocks"),
        "tbox_draft_elements",
        "tbox_draft_blocks",
        ["workspace_id", "draft_id", "block_id"],
        ["workspace_id", "draft_id", "id"],
        source_schema="knowledge",
        referent_schema="knowledge",
        ondelete="RESTRICT",
    )


def _create_proposals() -> None:
    op.create_table(
        "tbox_proposals",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("target_block_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("merge_strategy", sa.String(length=24), nullable=False),
        sa.Column("base_draft_version", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("proposal_document", JSON_DOCUMENT, nullable=False),
        sa.Column("conflicts_document", JSON_DOCUMENT, nullable=False),
        sa.Column("model_binding_document", JSON_DOCUMENT, nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
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
            "base_draft_version >= 1",
            name=op.f("ck_tbox_proposals_base_draft_version_positive"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(conflicts_document) = 'array'",
            name=op.f("ck_tbox_proposals_conflicts_document_array"),
        ),
        sa.CheckConstraint(
            "merge_strategy IN ('KEEP_ORIGINAL', 'ACCEPT_PROPOSAL', 'RESOLVE')",
            name=op.f("ck_tbox_proposals_merge_strategy_vocabulary"),
        ),
        sa.CheckConstraint(
            "mode IN ('MERGE_INTO_CURRENT', 'APPEND_LAYER')",
            name=op.f("ck_tbox_proposals_mode_vocabulary"),
        ),
        sa.CheckConstraint(
            "char_length(prompt) BETWEEN 1 AND 4000 AND prompt = btrim(prompt)",
            name=op.f("ck_tbox_proposals_prompt_valid"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(proposal_document) = 'object'",
            name=op.f("ck_tbox_proposals_proposal_document_object"),
        ),
        sa.CheckConstraint(
            "state IN ('READY', 'APPLIED', 'REJECTED', 'FAILED')",
            name=op.f("ck_tbox_proposals_state_vocabulary"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "created_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name=op.f("fk_tbox_proposals_workspace_id_created_by_workspace_memberships"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "draft_id"],
            ["knowledge.studio_drafts.workspace_id", "knowledge.studio_drafts.id"],
            name=op.f("fk_tbox_proposals_workspace_id_draft_id_studio_drafts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "draft_id", "target_block_id"],
            [
                "knowledge.tbox_draft_blocks.workspace_id",
                "knowledge.tbox_draft_blocks.draft_id",
                "knowledge.tbox_draft_blocks.id",
            ],
            name=op.f("fk_tbox_proposals_workspace_id_draft_id_target_block_id_tbox_draft_blocks"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tbox_proposals")),
        sa.UniqueConstraint(
            "workspace_id",
            "draft_id",
            "id",
            name=op.f("uq_tbox_proposals_workspace_id_draft_id_id"),
        ),
        schema="knowledge",
    )
    op.create_index(
        "ix_tbox_proposals_draft_created",
        "tbox_proposals",
        ["workspace_id", "draft_id", "created_at", "id"],
        unique=False,
        schema="knowledge",
    )


def _create_ingestion_jobs() -> None:
    op.create_table(
        "studio_ingestion_jobs",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("current_stage", sa.String(length=100), nullable=False),
        sa.Column("request_document", JSON_DOCUMENT, nullable=False),
        sa.Column("vector_policy_document", JSON_DOCUMENT, nullable=False),
        sa.Column("result_document", JSON_DOCUMENT, nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_epoch", sa.Integer(), nullable=False),
        sa.Column("lease_token_hash", sa.String(length=64), nullable=True),
        sa.Column("lease_owner_fingerprint", sa.String(length=255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
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
            "progress_percent BETWEEN 0 AND 100",
            name=op.f("ck_studio_ingestion_jobs_progress_range"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(request_document) = 'object'",
            name=op.f("ck_studio_ingestion_jobs_request_document_object"),
        ),
        sa.CheckConstraint(
            "(state = 'PENDING' AND progress_percent = 0 AND started_at IS NULL "
            "AND finished_at IS NULL AND error_code IS NULL) OR "
            "(state = 'RUNNING' AND progress_percent BETWEEN 0 AND 99 "
            "AND started_at IS NOT NULL AND finished_at IS NULL AND error_code IS NULL) OR "
            "(state = 'FAILED' AND started_at IS NOT NULL AND finished_at IS NOT NULL "
            "AND error_code IS NOT NULL) OR "
            "(state = 'SUCCESS' AND progress_percent = 100 AND started_at IS NOT NULL "
            "AND finished_at IS NOT NULL AND error_code IS NULL)",
            name=op.f("ck_studio_ingestion_jobs_state_shape"),
        ),
        sa.CheckConstraint(
            "state IN ('PENDING', 'RUNNING', 'FAILED', 'SUCCESS')",
            name=op.f("ck_studio_ingestion_jobs_state_vocabulary"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(vector_policy_document) = 'object'",
            name=op.f("ck_studio_ingestion_jobs_vector_policy_document_object"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "draft_id"],
            ["knowledge.studio_drafts.workspace_id", "knowledge.studio_drafts.id"],
            name=op.f("fk_studio_ingestion_jobs_workspace_id_draft_id_studio_drafts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "requested_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name=op.f("fk_studio_ingestion_jobs_workspace_id_requested_by_workspace_memberships"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_studio_ingestion_jobs")),
        sa.UniqueConstraint(
            "workspace_id",
            "draft_id",
            "id",
            name=op.f("uq_studio_ingestion_jobs_workspace_id_draft_id_id"),
        ),
        schema="knowledge",
    )
    op.create_index(
        "ix_studio_ingestion_jobs_claim",
        "studio_ingestion_jobs",
        ["state", "lease_expires_at", "created_at", "id"],
        unique=False,
        schema="knowledge",
    )
    op.create_index(
        "ix_studio_ingestion_jobs_draft_created",
        "studio_ingestion_jobs",
        ["workspace_id", "draft_id", "created_at", "id"],
        unique=False,
        schema="knowledge",
    )


def _install_rls_and_grants() -> None:
    for table in (
        "tbox_draft_blocks",
        "tbox_proposals",
        "studio_ingestion_jobs",
    ):
        op.execute(f"ALTER TABLE knowledge.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE knowledge.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY workspace_isolation ON knowledge.{table}
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
            f"""
            CREATE POLICY studio_draft_actor_select ON knowledge.{table}
            AS RESTRICTIVE FOR SELECT TO datariver_app
            USING (
                EXISTS (
                    SELECT 1 FROM knowledge.studio_drafts AS parent
                    WHERE parent.workspace_id = {table}.workspace_id
                      AND parent.id = {table}.draft_id
                )
            )
            """
        )
        op.execute(
            f"""
            CREATE POLICY studio_draft_owner_insert ON knowledge.{table}
            AS RESTRICTIVE FOR INSERT TO datariver_app
            WITH CHECK (
                EXISTS (
                    SELECT 1 FROM knowledge.studio_drafts AS parent
                    WHERE parent.workspace_id = {table}.workspace_id
                      AND parent.id = {table}.draft_id
                      AND parent.author_id = {CURRENT_SUBJECT}
                      AND parent.state = 'DRAFT'
                )
            )
            """
        )
    for table in ("tbox_draft_blocks", "tbox_proposals"):
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"""
                CREATE POLICY studio_draft_owner_{action.lower()}
                ON knowledge.{table}
                AS RESTRICTIVE FOR {action} TO datariver_app
                USING (
                    EXISTS (
                        SELECT 1 FROM knowledge.studio_drafts AS parent
                        WHERE parent.workspace_id = {table}.workspace_id
                          AND parent.id = {table}.draft_id
                          AND parent.author_id = {CURRENT_SUBJECT}
                          AND parent.state = 'DRAFT'
                    )
                )
                """
            )
    op.execute(
        """
        DO $grant$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON knowledge.tbox_draft_blocks TO datariver_app;
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON knowledge.tbox_draft_elements TO datariver_app;
                GRANT SELECT, INSERT, UPDATE
                    ON knowledge.tbox_proposals TO datariver_app;
                GRANT SELECT, INSERT
                    ON knowledge.studio_ingestion_jobs TO datariver_app;
            END IF;
        END
        $grant$
        """
    )


def upgrade() -> None:
    if _canonical_contract_is_complete():
        return
    _create_blocks_and_extend_elements()
    _create_proposals()
    _create_ingestion_jobs()
    _install_rls_and_grants()


def downgrade() -> None:
    bind = op.get_bind()
    retained = int(
        bind.execute(
            sa.text(
                """
                SELECT
                    (SELECT count(*) FROM knowledge.tbox_proposals)
                  + (SELECT count(*) FROM knowledge.studio_ingestion_jobs)
                  + (SELECT count(*) FROM knowledge.tbox_draft_blocks
                     WHERE kind <> 'DIRECT' OR ordinal <> 0)
                  + (SELECT count(*) FROM knowledge.tbox_draft_elements
                     WHERE definition IS NOT NULL
                        OR aliases <> '[]'::jsonb
                        OR unit IS NOT NULL
                        OR vector_index_enabled IS TRUE
                        OR layout_x IS NOT NULL
                        OR layout_y IS NOT NULL)
                """
            )
        ).scalar_one()
    )
    if retained:
        raise RuntimeError(
            "Ontology Builder proposal, block, vector-policy or ingestion evidence "
            "must be archived before downgrading revision 0063."
        )
    op.drop_table("studio_ingestion_jobs", schema="knowledge")
    op.drop_table("tbox_proposals", schema="knowledge")
    op.drop_constraint(
        op.f("fk_tbox_draft_elements_workspace_id_draft_id_block_id_tbox_draft_blocks"),
        "tbox_draft_elements",
        schema="knowledge",
        type_="foreignkey",
    )
    for column in (
        "layout_y",
        "layout_x",
        "vector_index_enabled",
        "unit",
        "aliases",
        "definition",
        "block_id",
    ):
        op.drop_column("tbox_draft_elements", column, schema="knowledge")
    op.drop_table("tbox_draft_blocks", schema="knowledge")
