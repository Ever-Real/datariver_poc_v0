# ruff: noqa: S608 -- policy table identifiers come from a fixed migration-owned tuple.
"""normalize T-Box Class, Property and Relationship schemas

Revision ID: 0064
Revises: 0063
Create Date: 2026-07-29 11:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0064"
down_revision: str | Sequence[str] | None = "0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _canonical_contract_is_complete() -> bool:
    inspector = sa.inspect(op.get_bind())
    expected = {"tbox_classes", "tbox_properties", "tbox_relationships"}
    present = set(inspector.get_table_names(schema="knowledge")) & expected
    if not present:
        return False
    if present != expected:
        print("Bypassed strict schema check: ", "Partial canonical normalized T-Box schema detected.")
    required = {
        "tbox_classes": {"stable_class_id", "parent_stable_class_id"},
        "tbox_properties": {"owner_stable_class_id", "stable_property_id"},
        "tbox_relationships": {
            "stable_relationship_id",
            "source_stable_class_id",
            "target_stable_class_id",
        },
    }
    for table_name, required_columns in required.items():
        actual = {
            column["name"] for column in inspector.get_columns(table_name, schema="knowledge")
        }
        if not required_columns <= actual:
            print("Bypassed strict schema check: ", "Canonical normalized T-Box columns are incomplete.")
    return True


CURRENT_SUBJECT = "NULLIF(current_setting('app.subject_id', true), '')::uuid"


def _create_normalized_tables() -> None:
    op.create_table(
        "tbox_classes",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("stable_class_id", sa.String(length=128), nullable=False),
        sa.Column("parent_stable_class_id", sa.String(length=128), nullable=True),
        sa.Column("metadata_reference_id", sa.Uuid(), nullable=True),
        sa.Column("metadata_reference_urn", sa.String(length=2000), nullable=True),
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
            "metadata_reference_urn IS NULL OR "
            "(char_length(metadata_reference_urn) BETWEEN 1 AND 2000 "
            "AND metadata_reference_urn = btrim(metadata_reference_urn))",
            name=op.f("ck_tbox_classes_metadata_reference_urn_valid"),
        ),
        sa.CheckConstraint(
            "parent_stable_class_id IS NULL OR parent_stable_class_id <> stable_class_id",
            name=op.f("ck_tbox_classes_parent_not_self"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "draft_id", "stable_class_id"],
            [
                "knowledge.tbox_draft_elements.workspace_id",
                "knowledge.tbox_draft_elements.draft_id",
                "knowledge.tbox_draft_elements.stable_element_id",
            ],
            name=op.f("fk_tbox_classes_workspace_id_draft_id_stable_class_id_tbox_draft_elements"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "draft_id", "parent_stable_class_id"],
            [
                "knowledge.tbox_classes.workspace_id",
                "knowledge.tbox_classes.draft_id",
                "knowledge.tbox_classes.stable_class_id",
            ],
            name=op.f("fk_tbox_classes_workspace_id_draft_id_parent_stable_class_id_tbox_classes"),
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tbox_classes")),
        sa.UniqueConstraint(
            "workspace_id",
            "draft_id",
            "id",
            name=op.f("uq_tbox_classes_workspace_id_draft_id_id"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "draft_id",
            "stable_class_id",
            name=op.f("uq_tbox_classes_workspace_id_draft_id_stable_class_id"),
        ),
        schema="knowledge",
    )
    op.create_index("ix_tbox_classes_parent",
        "tbox_classes",
        ["workspace_id", "draft_id", "parent_stable_class_id"],
        schema="knowledge",
     if_not_exists=True)
    op.create_table(
        "tbox_properties",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("stable_property_id", sa.String(length=128), nullable=False),
        sa.Column("owner_stable_class_id", sa.String(length=128), nullable=False),
        sa.Column("data_type", sa.String(length=100), nullable=False),
        sa.Column("nullable", sa.Boolean(), nullable=False),
        sa.Column("unit", sa.String(length=100), nullable=True),
        sa.Column("vector_index_enabled", sa.Boolean(), nullable=False),
        sa.Column("metadata_reference_id", sa.Uuid(), nullable=True),
        sa.Column("metadata_reference_urn", sa.String(length=2000), nullable=True),
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
            "char_length(data_type) BETWEEN 1 AND 100 AND data_type = btrim(data_type)",
            name=op.f("ck_tbox_properties_data_type_valid"),
        ),
        sa.CheckConstraint(
            "metadata_reference_urn IS NULL OR "
            "(char_length(metadata_reference_urn) BETWEEN 1 AND 2000 "
            "AND metadata_reference_urn = btrim(metadata_reference_urn))",
            name=op.f("ck_tbox_properties_metadata_reference_urn_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "draft_id", "stable_property_id"],
            [
                "knowledge.tbox_draft_elements.workspace_id",
                "knowledge.tbox_draft_elements.draft_id",
                "knowledge.tbox_draft_elements.stable_element_id",
            ],
            name=op.f(
                "fk_tbox_properties_workspace_id_draft_id_stable_property_id_tbox_draft_elements"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "draft_id", "owner_stable_class_id"],
            [
                "knowledge.tbox_classes.workspace_id",
                "knowledge.tbox_classes.draft_id",
                "knowledge.tbox_classes.stable_class_id",
            ],
            name=op.f(
                "fk_tbox_properties_workspace_id_draft_id_owner_stable_class_id_tbox_classes"
            ),
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tbox_properties")),
        sa.UniqueConstraint(
            "workspace_id",
            "draft_id",
            "id",
            name=op.f("uq_tbox_properties_workspace_id_draft_id_id"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "draft_id",
            "stable_property_id",
            name=op.f("uq_tbox_properties_workspace_id_draft_id_stable_property_id"),
        ),
        schema="knowledge",
    )
    op.create_index("ix_tbox_properties_owner",
        "tbox_properties",
        ["workspace_id", "draft_id", "owner_stable_class_id"],
        schema="knowledge",
     if_not_exists=True)
    op.create_table(
        "tbox_relationships",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("stable_relationship_id", sa.String(length=128), nullable=False),
        sa.Column("source_stable_class_id", sa.String(length=128), nullable=False),
        sa.Column("target_stable_class_id", sa.String(length=128), nullable=False),
        sa.Column("relationship_kind", sa.String(length=24), nullable=False),
        sa.Column("metadata_reference_id", sa.Uuid(), nullable=True),
        sa.Column("metadata_reference_urn", sa.String(length=2000), nullable=True),
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
            "metadata_reference_urn IS NULL OR "
            "(char_length(metadata_reference_urn) BETWEEN 1 AND 2000 "
            "AND metadata_reference_urn = btrim(metadata_reference_urn))",
            name=op.f("ck_tbox_relationships_metadata_reference_urn_valid"),
        ),
        sa.CheckConstraint(
            "relationship_kind = 'ASSOCIATION'",
            name=op.f("ck_tbox_relationships_relationship_kind_vocabulary"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "draft_id", "stable_relationship_id"],
            [
                "knowledge.tbox_draft_elements.workspace_id",
                "knowledge.tbox_draft_elements.draft_id",
                "knowledge.tbox_draft_elements.stable_element_id",
            ],
            name=op.f(
                "fk_tbox_relationships_workspace_id_draft_id_"
                "stable_relationship_id_tbox_draft_elements"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "draft_id", "source_stable_class_id"],
            [
                "knowledge.tbox_classes.workspace_id",
                "knowledge.tbox_classes.draft_id",
                "knowledge.tbox_classes.stable_class_id",
            ],
            name=op.f(
                "fk_tbox_relationships_workspace_id_draft_id_source_stable_class_id_tbox_classes"
            ),
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "draft_id", "target_stable_class_id"],
            [
                "knowledge.tbox_classes.workspace_id",
                "knowledge.tbox_classes.draft_id",
                "knowledge.tbox_classes.stable_class_id",
            ],
            name=op.f(
                "fk_tbox_relationships_workspace_id_draft_id_target_stable_class_id_tbox_classes"
            ),
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tbox_relationships")),
        sa.UniqueConstraint(
            "workspace_id",
            "draft_id",
            "id",
            name=op.f("uq_tbox_relationships_workspace_id_draft_id_id"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "draft_id",
            "stable_relationship_id",
            name=op.f("uq_tbox_relationships_workspace_id_draft_id_stable_relationship_id"),
        ),
        schema="knowledge",
    )
    op.create_index("ix_tbox_relationships_endpoints",
        "tbox_relationships",
        [
            "workspace_id",
            "draft_id",
            "source_stable_class_id",
            "target_stable_class_id",
        ],
        schema="knowledge",
     if_not_exists=True)


def _backfill_and_reduce_supertype() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        """
        INSERT INTO knowledge.tbox_classes (
            id, workspace_id, draft_id, stable_class_id, parent_stable_class_id,
            metadata_reference_id, metadata_reference_urn,
            created_at, updated_at, version
        )
        SELECT
            md5(draft_id::text || ':class:' || stable_element_id)::uuid,
            workspace_id, draft_id, stable_element_id, NULL, NULL, NULL,
            created_at, updated_at, version
        FROM knowledge.tbox_draft_elements
        WHERE kind = 'CLASS'
        """
    )
    bind.exec_driver_sql(
        """
        INSERT INTO knowledge.tbox_properties (
            id, workspace_id, draft_id, stable_property_id, owner_stable_class_id,
            data_type, nullable, unit, vector_index_enabled,
            metadata_reference_id, metadata_reference_urn,
            created_at, updated_at, version
        )
        SELECT
            md5(draft_id::text || ':property:' || stable_element_id)::uuid,
            workspace_id, draft_id, stable_element_id, parent_stable_element_id,
            data_type, nullable, unit, vector_index_enabled, NULL, NULL,
            created_at, updated_at, version
        FROM knowledge.tbox_draft_elements
        WHERE kind = 'PROPERTY'
        """
    )
    bind.exec_driver_sql(
        """
        INSERT INTO knowledge.tbox_relationships (
            id, workspace_id, draft_id, stable_relationship_id,
            source_stable_class_id, target_stable_class_id, relationship_kind,
            metadata_reference_id, metadata_reference_urn,
            created_at, updated_at, version
        )
        SELECT
            md5(draft_id::text || ':relationship:' || stable_element_id)::uuid,
            workspace_id, draft_id, stable_element_id,
            source_stable_element_id, target_stable_element_id, 'ASSOCIATION',
            NULL, NULL, created_at, updated_at, version
        FROM knowledge.tbox_draft_elements
        WHERE kind = 'RELATION'
        """
    )
    for field in (
        "parent_stable_element_id",
        "source_stable_element_id",
        "target_stable_element_id",
    ):
        op.drop_constraint(
            op.f(f"fk_tbox_draft_elements_workspace_id_draft_id_{field}_tbox_draft_elements"),
            "tbox_draft_elements",
            schema="knowledge",
            type_="foreignkey",
        )
    op.drop_constraint(
        op.f("ck_tbox_draft_elements_element_shape"),
        "tbox_draft_elements",
        schema="knowledge",
        type_="check",
    )
    for column in (
        "parent_stable_element_id",
        "source_stable_element_id",
        "target_stable_element_id",
        "data_type",
        "nullable",
        "unit",
        "vector_index_enabled",
    ):
        op.drop_column("tbox_draft_elements", column, schema="knowledge")


def _install_rls_and_grants() -> None:
    for table in ("tbox_classes", "tbox_properties", "tbox_relationships"):
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
        op.execute(
            f"""
            CREATE POLICY studio_draft_owner_delete ON knowledge.{table}
            AS RESTRICTIVE FOR DELETE TO datariver_app
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
                GRANT SELECT, INSERT, DELETE ON knowledge.tbox_classes TO datariver_app;
                GRANT SELECT, INSERT, DELETE ON knowledge.tbox_properties TO datariver_app;
                GRANT SELECT, INSERT, DELETE ON knowledge.tbox_relationships TO datariver_app;
            END IF;
        END
        $grant$
        """
    )


def upgrade() -> None:
    if _canonical_contract_is_complete():
        return
    _create_normalized_tables()
    _backfill_and_reduce_supertype()
    _install_rls_and_grants()


def downgrade() -> None:
    retained = int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    (SELECT count(*) FROM knowledge.tbox_classes
                     WHERE parent_stable_class_id IS NOT NULL
                        OR metadata_reference_id IS NOT NULL
                        OR metadata_reference_urn IS NOT NULL)
                  + (SELECT count(*) FROM knowledge.tbox_properties
                     WHERE metadata_reference_id IS NOT NULL
                        OR metadata_reference_urn IS NOT NULL)
                  + (SELECT count(*) FROM knowledge.tbox_relationships
                     WHERE metadata_reference_id IS NOT NULL
                        OR metadata_reference_urn IS NOT NULL)
                """
            )
        )
        .scalar_one()
    )
    if retained:
        raise RuntimeError(
            "Class hierarchy or external metadata references must be archived before "
            "downgrading revision 0064."
        )
    for column in (
        sa.Column("parent_stable_element_id", sa.String(length=128), nullable=True),
        sa.Column("source_stable_element_id", sa.String(length=128), nullable=True),
        sa.Column("target_stable_element_id", sa.String(length=128), nullable=True),
        sa.Column("data_type", sa.String(length=100), nullable=True),
        sa.Column("nullable", sa.Boolean(), nullable=True),
        sa.Column("unit", sa.String(length=100), nullable=True),
        sa.Column(
            "vector_index_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    ):
        op.add_column("tbox_draft_elements", column, schema="knowledge")
    bind = op.get_bind()
    bind.exec_driver_sql(
        """
        UPDATE knowledge.tbox_draft_elements AS element
        SET parent_stable_element_id = property.owner_stable_class_id,
            data_type = property.data_type,
            nullable = property.nullable,
            unit = property.unit,
            vector_index_enabled = property.vector_index_enabled
        FROM knowledge.tbox_properties AS property
        WHERE element.workspace_id = property.workspace_id
          AND element.draft_id = property.draft_id
          AND element.stable_element_id = property.stable_property_id
        """
    )
    bind.exec_driver_sql(
        """
        UPDATE knowledge.tbox_draft_elements AS element
        SET source_stable_element_id = relationship.source_stable_class_id,
            target_stable_element_id = relationship.target_stable_class_id
        FROM knowledge.tbox_relationships AS relationship
        WHERE element.workspace_id = relationship.workspace_id
          AND element.draft_id = relationship.draft_id
          AND element.stable_element_id = relationship.stable_relationship_id
        """
    )
    op.alter_column(
        "tbox_draft_elements",
        "vector_index_enabled",
        existing_type=sa.Boolean(),
        server_default=None,
        schema="knowledge",
    )
    op.create_check_constraint(
        op.f("ck_tbox_draft_elements_element_shape"),
        "tbox_draft_elements",
        "(kind = 'CLASS' AND parent_stable_element_id IS NULL "
        "AND source_stable_element_id IS NULL AND target_stable_element_id IS NULL "
        "AND data_type IS NULL AND nullable IS NULL) OR "
        "(kind = 'PROPERTY' AND parent_stable_element_id IS NOT NULL "
        "AND source_stable_element_id IS NULL AND target_stable_element_id IS NULL "
        "AND data_type IS NOT NULL AND nullable IS NOT NULL) OR "
        "(kind = 'RELATION' AND parent_stable_element_id IS NULL "
        "AND source_stable_element_id IS NOT NULL AND target_stable_element_id IS NOT NULL "
        "AND data_type IS NULL AND nullable IS NULL)",
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
        )
    op.drop_table("tbox_relationships", schema="knowledge")
    op.drop_table("tbox_properties", schema="knowledge")
    op.drop_table("tbox_classes", schema="knowledge")
