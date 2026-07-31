"""Add governed Knowledge Property profiles.

Revision ID: 0076
Revises: 0075
Create Date: 2026-07-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0076"
down_revision: str | Sequence[str] | None = "0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_studio_releases_profile_release_ontology",
        "studio_releases",
        ["workspace_id", "graph_id", "id", "ontology_version_id"],
        schema="knowledge",
    )
    op.create_unique_constraint(
        "uq_ontology_elements_profile_identity",
        "ontology_elements",
        ["workspace_id", "ontology_version_id", "id", "kind", "stable_element_id"],
        schema="knowledge",
    )
    op.create_table(
        "property_profiles",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("graph_id", sa.Uuid(), nullable=False),
        sa.Column("studio_release_id", sa.Uuid(), nullable=False),
        sa.Column("ontology_version_id", sa.Uuid(), nullable=False),
        sa.Column("ontology_element_id", sa.Uuid(), nullable=False),
        sa.Column("element_kind", sa.String(length=16), nullable=False),
        sa.Column("stable_property_id", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("unit", sa.String(length=100), nullable=True),
        sa.Column("lifecycle", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_by", sa.Uuid(), nullable=True),
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
            "lifecycle IN ('ACTIVE', 'ARCHIVED')",
            name=op.f("ck_property_profiles_lifecycle_vocabulary"),
        ),
        sa.CheckConstraint(
            "element_kind = 'PROPERTY'",
            name=op.f("ck_property_profiles_element_kind_property"),
        ),
        sa.CheckConstraint(
            "char_length(stable_property_id) BETWEEN 1 AND 128 "
            "AND stable_property_id = btrim(stable_property_id)",
            name=op.f("ck_property_profiles_stable_property_id_valid"),
        ),
        sa.CheckConstraint(
            "description IS NULL OR "
            "(char_length(description) BETWEEN 1 AND 2000 "
            "AND description = btrim(description))",
            name=op.f("ck_property_profiles_description_valid"),
        ),
        sa.CheckConstraint(
            "unit IS NULL OR (char_length(unit) BETWEEN 1 AND 100 AND unit = btrim(unit))",
            name=op.f("ck_property_profiles_unit_valid"),
        ),
        sa.CheckConstraint(
            "(lifecycle = 'ACTIVE' AND archived_at IS NULL AND archived_by IS NULL) OR "
            "(lifecycle = 'ARCHIVED' AND archived_at IS NOT NULL AND archived_by IS NOT NULL)",
            name=op.f("ck_property_profiles_archive_shape"),
        ),
        sa.ForeignKeyConstraint(
            [
                "workspace_id",
                "graph_id",
                "studio_release_id",
                "ontology_version_id",
            ],
            [
                "knowledge.studio_releases.workspace_id",
                "knowledge.studio_releases.graph_id",
                "knowledge.studio_releases.id",
                "knowledge.studio_releases.ontology_version_id",
            ],
            name=op.f("fk_property_profiles_studio_release"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id", "ontology_version_id"],
            [
                "knowledge.ontology_versions.workspace_id",
                "knowledge.ontology_versions.graph_id",
                "knowledge.ontology_versions.id",
            ],
            name=op.f("fk_property_profiles_ontology_version"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "workspace_id",
                "ontology_version_id",
                "ontology_element_id",
                "element_kind",
                "stable_property_id",
            ],
            [
                "knowledge.ontology_elements.workspace_id",
                "knowledge.ontology_elements.ontology_version_id",
                "knowledge.ontology_elements.id",
                "knowledge.ontology_elements.kind",
                "knowledge.ontology_elements.stable_element_id",
            ],
            name=op.f("fk_property_profiles_ontology_element"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "created_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name=op.f("fk_property_profiles_created_by"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "updated_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name=op.f("fk_property_profiles_updated_by"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "archived_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name=op.f("fk_property_profiles_archived_by"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_property_profiles")),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name=op.f("uq_property_profiles_workspace_id_id"),
        ),
        schema="knowledge",
    )
    op.create_index(
        "ix_property_profiles_graph_stable_property",
        "property_profiles",
        ["workspace_id", "graph_id", "stable_property_id"],
        schema="knowledge",
    )
    op.create_index(
        "uq_property_profiles_one_active_per_element",
        "property_profiles",
        ["workspace_id", "ontology_element_id"],
        unique=True,
        schema="knowledge",
        postgresql_where=sa.text("lifecycle = 'ACTIVE'"),
    )
    op.create_table(
        "property_profile_synonyms",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("value", sa.String(length=200), nullable=False),
        sa.Column("normalized_value", sa.String(length=600), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "char_length(value) BETWEEN 1 AND 200 AND value = btrim(value)",
            name=op.f("ck_property_profile_synonyms_value_valid"),
        ),
        sa.CheckConstraint(
            "char_length(normalized_value) BETWEEN 1 AND 600 "
            "AND normalized_value = btrim(normalized_value)",
            name=op.f("ck_property_profile_synonyms_normalized_value_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "profile_id"],
            ["knowledge.property_profiles.workspace_id", "knowledge.property_profiles.id"],
            name=op.f("fk_property_profile_synonyms_profile"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_property_profile_synonyms")),
        sa.UniqueConstraint(
            "workspace_id",
            "profile_id",
            "id",
            name=op.f("uq_property_profile_synonyms_workspace_profile_id"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "profile_id",
            "normalized_value",
            name=op.f("uq_property_profile_synonyms_workspace_profile_value"),
        ),
        schema="knowledge",
    )
    op.create_index(
        "ix_property_profile_synonyms_value",
        "property_profile_synonyms",
        ["workspace_id", "normalized_value"],
        schema="knowledge",
    )
    for table in ("property_profiles", "property_profile_synonyms"):
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
    op.execute("GRANT SELECT, INSERT ON knowledge.property_profiles TO datariver_app")
    op.execute(
        "GRANT UPDATE (description, unit, lifecycle, updated_by, archived_at, "
        "archived_by, updated_at, version) "
        "ON knowledge.property_profiles TO datariver_app"
    )
    op.execute(
        "GRANT SELECT, INSERT, DELETE ON knowledge.property_profile_synonyms TO datariver_app"
    )


def downgrade() -> None:
    op.drop_table("property_profile_synonyms", schema="knowledge")
    op.drop_table("property_profiles", schema="knowledge")
    op.drop_constraint(
        "uq_ontology_elements_profile_identity",
        "ontology_elements",
        type_="unique",
        schema="knowledge",
    )
    op.drop_constraint(
        "uq_studio_releases_profile_release_ontology",
        "studio_releases",
        type_="unique",
        schema="knowledge",
    )
