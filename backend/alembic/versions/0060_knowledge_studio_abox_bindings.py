# ruff: noqa: S608 -- policy identifiers come from a fixed migration-owned allowlist.
"""add normalized Knowledge Studio A-Box binding drafts

Revision ID: 0060
Revises: 0059
Create Date: 2026-07-28 15:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0060"
down_revision: str | Sequence[str] | None = "0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _canonical_contract_is_complete() -> bool:
    inspector = sa.inspect(op.get_bind())
    expected = {
        "tbox_draft_elements",
        "source_references",
        "abox_binding_drafts",
        "abox_mapping_rule_drafts",
    }
    present = set(inspector.get_table_names(schema="knowledge")) & expected
    if not present:
        return False
    if present != expected:
        raise RuntimeError("Partial canonical Knowledge Studio A-Box schema detected.")
    forced_rls = int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT count(*)
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'knowledge'
                  AND relation.relname = ANY(CAST(:tables AS text[]))
                  AND relation.relrowsecurity
                  AND relation.relforcerowsecurity
                """
            ),
            {"tables": sorted(expected)},
        )
        .scalar_one()
    )
    if forced_rls != len(expected):
        raise RuntimeError("Canonical Knowledge Studio A-Box RLS is incomplete.")
    return True


JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
    "postgresql",
)


def _create_tbox_elements() -> None:
    op.create_table(
        "tbox_draft_elements",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("stable_element_id", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("canonical_name", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("parent_stable_element_id", sa.String(length=128), nullable=True),
        sa.Column("source_stable_element_id", sa.String(length=128), nullable=True),
        sa.Column("target_stable_element_id", sa.String(length=128), nullable=True),
        sa.Column("data_type", sa.String(length=100), nullable=True),
        sa.Column("nullable", sa.Boolean(), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
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
            "(kind = 'CLASS' AND parent_stable_element_id IS NULL "
            "AND source_stable_element_id IS NULL AND target_stable_element_id IS NULL "
            "AND data_type IS NULL AND nullable IS NULL) OR "
            "(kind = 'PROPERTY' AND parent_stable_element_id IS NOT NULL "
            "AND source_stable_element_id IS NULL AND target_stable_element_id IS NULL "
            "AND data_type IS NOT NULL AND nullable IS NOT NULL) OR "
            "(kind = 'RELATION' AND parent_stable_element_id IS NULL "
            "AND source_stable_element_id IS NOT NULL AND target_stable_element_id IS NOT NULL "
            "AND data_type IS NULL AND nullable IS NULL)",
            name=op.f("ck_tbox_draft_elements_element_shape"),
        ),
        sa.CheckConstraint(
            "kind IN ('CLASS', 'PROPERTY', 'RELATION')",
            name=op.f("ck_tbox_draft_elements_kind_vocabulary"),
        ),
        sa.CheckConstraint(
            "char_length(canonical_name) BETWEEN 1 AND 255 "
            "AND canonical_name = btrim(canonical_name)",
            name=op.f("ck_tbox_draft_elements_canonical_name_valid"),
        ),
        sa.CheckConstraint(
            "char_length(display_name) BETWEEN 1 AND 255 AND display_name = btrim(display_name)",
            name=op.f("ck_tbox_draft_elements_display_name_valid"),
        ),
        sa.CheckConstraint(
            "ordinal >= 0",
            name=op.f("ck_tbox_draft_elements_ordinal_nonnegative"),
        ),
        sa.CheckConstraint(
            "char_length(stable_element_id) BETWEEN 1 AND 128 "
            "AND stable_element_id = btrim(stable_element_id)",
            name=op.f("ck_tbox_draft_elements_stable_element_id_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "draft_id"],
            ["knowledge.studio_drafts.workspace_id", "knowledge.studio_drafts.id"],
            name=op.f("fk_tbox_draft_elements_workspace_id_draft_id_studio_drafts"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tbox_draft_elements")),
        sa.UniqueConstraint(
            "workspace_id",
            "draft_id",
            "id",
            name=op.f("uq_tbox_draft_elements_workspace_id_draft_id_id"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "draft_id",
            "ordinal",
            name=op.f("uq_tbox_draft_elements_workspace_id_draft_id_ordinal"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "draft_id",
            "stable_element_id",
            name=op.f("uq_tbox_draft_elements_workspace_id_draft_id_stable_element_id"),
        ),
        schema="knowledge",
    )
    for field in (
        "parent_stable_element_id",
        "source_stable_element_id",
        "target_stable_element_id",
    ):
        op.create_foreign_key(
            op.f(f"fk_tbox_draft_elements_workspace_id_draft_id_{field}_tbox_draft_elements"),
            "tbox_draft_elements",
            "tbox_draft_elements",
            ["workspace_id", "draft_id", field],
            ["workspace_id", "draft_id", "stable_element_id"],
            source_schema="knowledge",
            referent_schema="knowledge",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        )
    op.create_index("ix_tbox_draft_elements_draft_kind_ordinal",
        "tbox_draft_elements",
        ["workspace_id", "draft_id", "kind", "ordinal"],
        unique=False,
        schema="knowledge",
     if_not_exists=True)


def _create_source_references() -> None:
    op.create_table(
        "source_references",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("catalog_asset_id", sa.Uuid(), nullable=False),
        sa.Column("source_version", sa.String(length=255), nullable=False),
        sa.Column("projection_source_version", sa.String(length=255), nullable=False),
        sa.Column("classification", sa.Integer(), nullable=False),
        sa.Column("selection_document", JSON_DOCUMENT, nullable=False),
        sa.Column("selection_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "classification BETWEEN 0 AND 3",
            name=op.f("ck_source_references_classification_range"),
        ),
        sa.CheckConstraint(
            "kind = 'CATALOG_DATASET'",
            name=op.f("ck_source_references_kind_vocabulary"),
        ),
        sa.CheckConstraint(
            "char_length(projection_source_version) BETWEEN 1 AND 255 "
            "AND projection_source_version = btrim(projection_source_version)",
            name=op.f("ck_source_references_projection_source_version_valid"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(selection_document) = 'object'",
            name=op.f("ck_source_references_selection_document_object"),
        ),
        sa.CheckConstraint(
            "selection_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_source_references_selection_hash_sha256"),
        ),
        sa.CheckConstraint(
            "char_length(source_version) BETWEEN 1 AND 255 "
            "AND source_version = btrim(source_version)",
            name=op.f("ck_source_references_source_version_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "catalog_asset_id"],
            ["catalog.assets_projection.workspace_id", "catalog.assets_projection.id"],
            name=op.f("fk_source_references_workspace_id_catalog_asset_id_assets_projection"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "created_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name=op.f("fk_source_references_workspace_id_created_by_workspace_memberships"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_references")),
        sa.UniqueConstraint(
            "workspace_id",
            "created_by",
            "kind",
            "catalog_asset_id",
            "source_version",
            "projection_source_version",
            "selection_hash",
            name="uq_source_references_actor_contract",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name=op.f("uq_source_references_workspace_id_id"),
        ),
        schema="knowledge",
    )
    op.create_index("ix_source_references_workspace_asset_version",
        "source_references",
        ["workspace_id", "catalog_asset_id", "source_version"],
        unique=False,
        schema="knowledge",
     if_not_exists=True)


def _create_bindings() -> None:
    op.create_table(
        "abox_binding_drafts",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("target_stable_element_id", sa.String(length=128), nullable=False),
        sa.Column("source_reference_id", sa.Uuid(), nullable=False),
        sa.Column("readiness", sa.String(length=16), nullable=False),
        sa.Column("tbox_version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
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
            "readiness IN ('DRAFT', 'VALIDATED', 'STALE')",
            name=op.f("ck_abox_binding_drafts_readiness_vocabulary"),
        ),
        sa.CheckConstraint(
            "tbox_version >= 1",
            name=op.f("ck_abox_binding_drafts_tbox_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "created_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name=op.f("fk_abox_binding_drafts_workspace_id_created_by_workspace_memberships"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "draft_id"],
            ["knowledge.studio_drafts.workspace_id", "knowledge.studio_drafts.id"],
            name=op.f("fk_abox_binding_drafts_workspace_id_draft_id_studio_drafts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "draft_id", "target_stable_element_id"],
            [
                "knowledge.tbox_draft_elements.workspace_id",
                "knowledge.tbox_draft_elements.draft_id",
                "knowledge.tbox_draft_elements.stable_element_id",
            ],
            name=op.f(
                "fk_abox_binding_drafts_workspace_id_draft_id_"
                "target_stable_element_id_tbox_draft_elements"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_reference_id"],
            ["knowledge.source_references.workspace_id", "knowledge.source_references.id"],
            name=op.f("fk_abox_binding_drafts_workspace_id_source_reference_id_source_references"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "updated_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name=op.f("fk_abox_binding_drafts_workspace_id_updated_by_workspace_memberships"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_abox_binding_drafts")),
        sa.UniqueConstraint(
            "workspace_id",
            "draft_id",
            "id",
            name=op.f("uq_abox_binding_drafts_workspace_id_draft_id_id"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "draft_id",
            "target_stable_element_id",
            name=op.f("uq_abox_binding_drafts_workspace_id_draft_id_target_stable_element_id"),
        ),
        schema="knowledge",
    )
    op.create_index("ix_abox_binding_drafts_draft_readiness",
        "abox_binding_drafts",
        ["workspace_id", "draft_id", "readiness", "target_stable_element_id"],
        unique=False,
        schema="knowledge",
     if_not_exists=True)
    op.create_table(
        "abox_mapping_rule_drafts",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("source_field_path", sa.Text(), nullable=False),
        sa.Column("target_stable_element_id", sa.String(length=128), nullable=False),
        sa.Column("transform_id", sa.String(length=64), nullable=False),
        sa.Column("transform_version", sa.String(length=32), nullable=False),
        sa.Column("source_unit", sa.String(length=100), nullable=True),
        sa.Column("canonical_unit", sa.String(length=100), nullable=True),
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
            "transform_id = 'IDENTITY' AND transform_version = '1'",
            name=op.f("ck_abox_mapping_rule_drafts_identity_transform_only"),
        ),
        sa.CheckConstraint(
            "method IN ('SUBJECT_ID', 'PROPERTY', 'EDGE_LINK', 'EDGE_PROPERTY')",
            name=op.f("ck_abox_mapping_rule_drafts_method_vocabulary"),
        ),
        sa.CheckConstraint(
            "ordinal >= 0",
            name=op.f("ck_abox_mapping_rule_drafts_ordinal_nonnegative"),
        ),
        sa.CheckConstraint(
            "char_length(source_field_path) BETWEEN 1 AND 2000 "
            "AND source_field_path = btrim(source_field_path)",
            name=op.f("ck_abox_mapping_rule_drafts_source_field_path_valid"),
        ),
        sa.CheckConstraint(
            "char_length(target_stable_element_id) BETWEEN 1 AND 128 "
            "AND target_stable_element_id = btrim(target_stable_element_id)",
            name=op.f("ck_abox_mapping_rule_drafts_target_stable_element_id_valid"),
        ),
        sa.CheckConstraint(
            "(source_unit IS NULL AND canonical_unit IS NULL) OR "
            "(source_unit IS NOT NULL AND canonical_unit IS NOT NULL "
            "AND char_length(source_unit) BETWEEN 1 AND 100 "
            "AND char_length(canonical_unit) BETWEEN 1 AND 100)",
            name=op.f("ck_abox_mapping_rule_drafts_unit_pair"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "draft_id", "binding_id"],
            [
                "knowledge.abox_binding_drafts.workspace_id",
                "knowledge.abox_binding_drafts.draft_id",
                "knowledge.abox_binding_drafts.id",
            ],
            name=op.f(
                "fk_abox_mapping_rule_drafts_workspace_id_draft_id_binding_id_abox_binding_drafts"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "draft_id", "target_stable_element_id"],
            [
                "knowledge.tbox_draft_elements.workspace_id",
                "knowledge.tbox_draft_elements.draft_id",
                "knowledge.tbox_draft_elements.stable_element_id",
            ],
            name=op.f(
                "fk_abox_mapping_rule_drafts_workspace_id_draft_id_"
                "target_stable_element_id_tbox_draft_elements"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_abox_mapping_rule_drafts")),
        sa.UniqueConstraint(
            "workspace_id",
            "draft_id",
            "binding_id",
            "id",
            name=op.f("uq_abox_mapping_rule_drafts_workspace_id_draft_id_binding_id_id"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "binding_id",
            "ordinal",
            name=op.f("uq_abox_mapping_rule_drafts_workspace_id_binding_id_ordinal"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "binding_id",
            "method",
            "target_stable_element_id",
            name="uq_abox_mapping_rule_drafts_target_method",
        ),
        schema="knowledge",
    )
    op.create_index("ix_abox_mapping_rule_drafts_binding_ordinal",
        "abox_mapping_rule_drafts",
        ["workspace_id", "binding_id", "ordinal"],
        unique=False,
        schema="knowledge",
     if_not_exists=True)


def _install_rls() -> None:
    for table in (
        "tbox_draft_elements",
        "source_references",
        "abox_binding_drafts",
        "abox_mapping_rule_drafts",
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
        """
        CREATE POLICY source_reference_owner_access ON knowledge.source_references
        AS RESTRICTIVE FOR ALL TO datariver_app
        USING (
            created_by =
            NULLIF(current_setting('app.subject_id', true), '')::uuid
        )
        WITH CHECK (
            created_by =
            NULLIF(current_setting('app.subject_id', true), '')::uuid
        )
        """
    )
    for table in (
        "tbox_draft_elements",
        "abox_binding_drafts",
        "abox_mapping_rule_drafts",
    ):
        op.execute(
            f"""
            CREATE POLICY studio_draft_owner_access ON knowledge.{table}
            AS RESTRICTIVE FOR ALL TO datariver_app
            USING (
                EXISTS (
                    SELECT 1
                    FROM knowledge.studio_drafts AS draft
                    WHERE draft.workspace_id = {table}.workspace_id
                      AND draft.id = {table}.draft_id
                      AND draft.author_id =
                          NULLIF(current_setting('app.subject_id', true), '')::uuid
                )
            )
            WITH CHECK (
                EXISTS (
                    SELECT 1
                    FROM knowledge.studio_drafts AS draft
                    WHERE draft.workspace_id = {table}.workspace_id
                      AND draft.id = {table}.draft_id
                      AND draft.author_id =
                          NULLIF(current_setting('app.subject_id', true), '')::uuid
                )
            )
            """
        )


def _grant_application_access() -> None:
    op.execute(
        """
        DO $grant$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
                GRANT SELECT ON knowledge.tbox_draft_elements TO datariver_app;
                GRANT SELECT, INSERT ON knowledge.source_references TO datariver_app;
                GRANT SELECT, INSERT ON knowledge.abox_binding_drafts TO datariver_app;
                GRANT UPDATE (
                    source_reference_id, readiness, tbox_version, updated_by,
                    version, updated_at
                ) ON knowledge.abox_binding_drafts TO datariver_app;
                GRANT SELECT, INSERT, DELETE
                    ON knowledge.abox_mapping_rule_drafts TO datariver_app;
            END IF;
        END
        $grant$
        """
    )


def upgrade() -> None:
    if _canonical_contract_is_complete():
        return
    _create_tbox_elements()
    _create_source_references()
    _create_bindings()
    _install_rls()
    _grant_application_access()


def downgrade() -> None:
    row_count = int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    (SELECT count(*) FROM knowledge.tbox_draft_elements)
                  + (SELECT count(*) FROM knowledge.source_references)
                  + (SELECT count(*) FROM knowledge.abox_binding_drafts)
                  + (SELECT count(*) FROM knowledge.abox_mapping_rule_drafts)
                """
            )
        )
        .scalar_one()
    )
    if row_count:
        raise RuntimeError(
            "Knowledge Studio T-Box/A-Box Draft data exists; downgrade would destroy state."
        )
    op.drop_table("abox_mapping_rule_drafts", schema="knowledge")
    op.drop_table("abox_binding_drafts", schema="knowledge")
    op.drop_table("source_references", schema="knowledge")
    op.drop_table("tbox_draft_elements", schema="knowledge")
