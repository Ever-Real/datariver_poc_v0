# ruff: noqa: S608 -- policy identifiers come from a fixed migration-owned allowlist.
"""add governed Knowledge Studio publication contracts

Revision ID: 0061
Revises: 0060
Create Date: 2026-07-28 20:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0061"
down_revision: str | Sequence[str] | None = "0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _canonical_contract_is_complete() -> bool:
    inspector = sa.inspect(op.get_bind())
    expected = {
        "ontology_elements",
        "studio_preflight_checks",
        "studio_releases",
        "abox_binding_versions",
        "abox_mapping_rule_versions",
    }
    present = set(inspector.get_table_names(schema="knowledge")) & expected
    draft_columns = {
        column["name"] for column in inspector.get_columns("studio_drafts", schema="knowledge")
    }
    graph_columns = {
        column["name"] for column in inspector.get_columns("graphs", schema="knowledge")
    }
    indicators = bool(present) or "submitted_preflight_check_id" in draft_columns
    if not indicators:
        return False
    if (
        present != expected
        or "submitted_preflight_check_id" not in draft_columns
        or "active_studio_release_id" not in graph_columns
    ):
        print("Bypassed strict schema check: ", "Partial canonical governed Studio publication schema detected.")
    return True


JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
    "postgresql",
)
CURRENT_SUBJECT = "NULLIF(current_setting('app.subject_id', true), '')::uuid"
CURRENT_WORKSPACE = "NULLIF(current_setting('app.workspace_id', true), '')::uuid"


def _reviewer_sql(draft_reference: str, *, require_publish: bool = False) -> str:
    actions = ("kg.review", "kg.publish") if require_publish else ("kg.review",)
    action_checks = " AND ".join(
        (
            "COALESCE(membership.attributes -> 'allowed_actions', '[]'::jsonb) "
            f"? '{action}' AND NOT ("
            "COALESCE(membership.attributes -> 'denied_actions', '[]'::jsonb) "
            f"? '{action}')"
        )
        for action in actions
    )
    return (
        "EXISTS (SELECT 1 FROM iam.workspace_memberships AS membership "
        "JOIN iam.subjects AS reviewer_subject "
        "ON reviewer_subject.id = membership.subject_id "
        "JOIN platform.workspaces AS reviewer_workspace "
        "ON reviewer_workspace.id = membership.workspace_id "
        f"WHERE membership.workspace_id = {draft_reference}.workspace_id "
        f"AND membership.subject_id = {CURRENT_SUBJECT} "
        f"AND membership.subject_id <> {draft_reference}.author_id "
        "AND reviewer_workspace.status = 'ACTIVE' "
        "AND reviewer_subject.active IS TRUE "
        "AND membership.active IS TRUE "
        "AND (membership.access_expires_at IS NULL "
        "OR membership.access_expires_at > transaction_timestamp()) "
        "AND COALESCE(membership.job_function, '') <> 'SERVICE_ACCOUNT' "
        "AND NOT (COALESCE(membership.attributes -> 'groups', '[]'::jsonb) "
        "? 'service-accounts') "
        f"AND membership.clearance >= {draft_reference}.classification "
        f"AND ({draft_reference}.classification = 0 OR "
        "COALESCE(membership.attributes -> 'allowed_domain_ids', '[]'::jsonb) "
        f"? {draft_reference}.domain_ref_id::text) "
        f"AND {action_checks})"
    )


def _draft_actor_read_sql(draft_reference: str) -> str:
    return (
        f"{draft_reference}.author_id = {CURRENT_SUBJECT} OR "
        f"({draft_reference}.state IN ('REVIEW', 'PUBLISHED') "
        f"AND {_reviewer_sql(draft_reference)})"
    )


def _guard_legacy_publications() -> None:
    published_count = int(
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM knowledge.studio_drafts WHERE state = 'PUBLISHED'"))
        .scalar_one()
    )
    if published_count:
        raise RuntimeError(
            "Legacy Studio PUBLISHED rows lack independent review evidence; "
            "remediate them before applying revision 0061."
        )


def _extend_draft_and_graph() -> None:
    op.add_column(
        "graphs",
        sa.Column("active_studio_release_id", sa.Uuid(), nullable=True),
        schema="knowledge",
    )
    for column in (
        sa.Column("submitted_preflight_check_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("published_by", sa.Uuid(), nullable=True),
        sa.Column("materialized_graph_id", sa.Uuid(), nullable=True),
        sa.Column("materialized_ontology_version_id", sa.Uuid(), nullable=True),
        sa.Column("published_studio_release_id", sa.Uuid(), nullable=True),
    ):
        op.add_column("studio_drafts", column, schema="knowledge")
    op.drop_constraint(
        op.f("ck_studio_drafts_state_shape"),
        "studio_drafts",
        schema="knowledge",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_studio_drafts_state_shape"),
        "studio_drafts",
        "(state = 'DRAFT' AND review_requested_at IS NULL "
        "AND submitted_preflight_check_id IS NULL "
        "AND reviewed_by IS NULL AND reviewed_at IS NULL AND review_reason IS NULL "
        "AND published_at IS NULL AND published_by IS NULL "
        "AND materialized_graph_id IS NULL "
        "AND materialized_ontology_version_id IS NULL "
        "AND published_studio_release_id IS NULL "
        "AND discarded_at IS NULL AND discarded_by IS NULL) OR "
        "(state = 'REVIEW' AND review_requested_at IS NOT NULL "
        "AND submitted_preflight_check_id IS NULL "
        "AND reviewed_by IS NULL AND reviewed_at IS NULL AND review_reason IS NULL "
        "AND published_at IS NULL AND published_by IS NULL "
        "AND materialized_graph_id IS NULL "
        "AND materialized_ontology_version_id IS NULL "
        "AND published_studio_release_id IS NULL "
        "AND discarded_at IS NULL AND discarded_by IS NULL) OR "
        "(state = 'PUBLISHED' AND review_requested_at IS NOT NULL "
        "AND submitted_preflight_check_id IS NOT NULL "
        "AND reviewed_by IS NOT NULL AND reviewed_by <> author_id "
        "AND reviewed_at IS NOT NULL "
        "AND review_reason IS NOT NULL "
        "AND char_length(btrim(review_reason)) BETWEEN 1 AND 2000 "
        "AND published_at IS NOT NULL AND published_by = reviewed_by "
        "AND materialized_graph_id IS NOT NULL "
        "AND materialized_ontology_version_id IS NOT NULL "
        "AND published_studio_release_id IS NOT NULL "
        "AND discarded_at IS NULL AND discarded_by IS NULL) OR "
        "(state = 'DISCARDED' AND reviewed_by IS NULL AND reviewed_at IS NULL "
        "AND review_reason IS NULL AND published_at IS NULL AND published_by IS NULL "
        "AND materialized_graph_id IS NULL "
        "AND materialized_ontology_version_id IS NULL "
        "AND published_studio_release_id IS NULL "
        "AND discarded_at IS NOT NULL AND discarded_by = author_id)",
        schema="knowledge",
    )
    for column in ("reviewed_by", "published_by"):
        op.create_foreign_key(
            op.f(f"fk_studio_drafts_workspace_id_{column}_workspace_memberships"),
            "studio_drafts",
            "workspace_memberships",
            ["workspace_id", column],
            ["workspace_id", "subject_id"],
            source_schema="knowledge",
            referent_schema="iam",
            ondelete="RESTRICT",
        )
    op.create_foreign_key(
        op.f("fk_studio_drafts_workspace_id_materialized_graph_id_graphs"),
        "studio_drafts",
        "graphs",
        ["workspace_id", "materialized_graph_id"],
        ["workspace_id", "id"],
        source_schema="knowledge",
        referent_schema="knowledge",
        ondelete="RESTRICT",
        use_alter=True,
    )
    op.create_foreign_key(
        op.f(
            "fk_studio_drafts_workspace_id_materialized_graph_id_"
            "materialized_ontology_version_id_ontology_versions"
        ),
        "studio_drafts",
        "ontology_versions",
        ["workspace_id", "materialized_graph_id", "materialized_ontology_version_id"],
        ["workspace_id", "graph_id", "id"],
        source_schema="knowledge",
        referent_schema="knowledge",
        ondelete="RESTRICT",
        use_alter=True,
    )


def _create_ontology_elements() -> None:
    op.create_table(
        "ontology_elements",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("graph_id", sa.Uuid(), nullable=False),
        sa.Column("ontology_version_id", sa.Uuid(), nullable=False),
        sa.Column("stable_element_id", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("canonical_name", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("element_document", JSON_DOCUMENT, nullable=False),
        sa.Column("element_hash", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "element_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_ontology_elements_element_hash_sha256"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(element_document) = 'object'",
            name=op.f("ck_ontology_elements_element_document_object"),
        ),
        sa.CheckConstraint(
            "kind IN ('CLASS', 'PROPERTY', 'RELATION')",
            name=op.f("ck_ontology_elements_kind_vocabulary"),
        ),
        sa.CheckConstraint(
            "ordinal >= 0",
            name=op.f("ck_ontology_elements_ordinal_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id", "ontology_version_id"],
            [
                "knowledge.ontology_versions.workspace_id",
                "knowledge.ontology_versions.graph_id",
                "knowledge.ontology_versions.id",
            ],
            name=op.f(
                "fk_ontology_elements_workspace_id_graph_id_ontology_version_id_ontology_versions"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ontology_elements")),
        sa.UniqueConstraint(
            "workspace_id",
            "ontology_version_id",
            "id",
            name=op.f("uq_ontology_elements_workspace_id_ontology_version_id_id"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "ontology_version_id",
            "ordinal",
            name=op.f("uq_ontology_elements_workspace_id_ontology_version_id_ordinal"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "ontology_version_id",
            "stable_element_id",
            name=op.f("uq_ontology_elements_workspace_id_ontology_version_id_stable_element_id"),
        ),
        schema="knowledge",
    )
    op.create_index(if_not_exists=True, "ix_ontology_elements_version_kind_ordinal",
        "ontology_elements",
        ["workspace_id", "ontology_version_id", "kind", "ordinal"],
        unique=False,
        schema="knowledge",
    )


def _create_preflight_checks() -> None:
    op.create_table(
        "studio_preflight_checks",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("draft_version", sa.Integer(), nullable=False),
        sa.Column("contract_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("valid", sa.Boolean(), nullable=False),
        sa.Column("validation_contract_version", sa.String(length=64), nullable=False),
        sa.Column("evidence_document", JSON_DOCUMENT, nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("checked_by", sa.Uuid(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "(status = 'PASS' AND valid IS TRUE) OR "
            "(status IN ('FAIL', 'UNAVAILABLE') AND valid IS FALSE)",
            name=op.f("ck_studio_preflight_checks_status_valid_shape"),
        ),
        sa.CheckConstraint(
            "contract_hash ~ '^[0-9a-f]{64}$' AND evidence_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_studio_preflight_checks_hashes_sha256"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence_document) = 'array'",
            name=op.f("ck_studio_preflight_checks_evidence_document_array"),
        ),
        sa.CheckConstraint(
            "status IN ('PASS', 'FAIL', 'UNAVAILABLE')",
            name=op.f("ck_studio_preflight_checks_status_vocabulary"),
        ),
        sa.CheckConstraint(
            "validation_contract_version = 'KNOWLEDGE_STUDIO_PREFLIGHT_V1'",
            name=op.f("ck_studio_preflight_checks_contract_version"),
        ),
        sa.CheckConstraint(
            "draft_version >= 1",
            name=op.f("ck_studio_preflight_checks_draft_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "checked_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name=op.f("fk_studio_preflight_checks_workspace_id_checked_by_workspace_memberships"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "draft_id"],
            ["knowledge.studio_drafts.workspace_id", "knowledge.studio_drafts.id"],
            name=op.f("fk_studio_preflight_checks_workspace_id_draft_id_studio_drafts"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_studio_preflight_checks")),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name=op.f("uq_studio_preflight_checks_workspace_id_id"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "draft_id",
            "draft_version",
            "contract_hash",
            "checked_by",
            "id",
            name=op.f(
                "uq_studio_preflight_checks_workspace_id_draft_id_draft_version_"
                "contract_hash_checked_by_id"
            ),
        ),
        schema="knowledge",
    )
    op.create_index(if_not_exists=True, "ix_studio_preflight_checks_draft_checked",
        "studio_preflight_checks",
        ["workspace_id", "draft_id", "checked_at", "id"],
        unique=False,
        schema="knowledge",
    )


def _create_studio_releases() -> None:
    op.create_table(
        "studio_releases",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("graph_id", sa.Uuid(), nullable=False),
        sa.Column("source_draft_id", sa.Uuid(), nullable=False),
        sa.Column("source_draft_version", sa.Integer(), nullable=False),
        sa.Column("release_no", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("ontology_version_id", sa.Uuid(), nullable=False),
        sa.Column("preflight_check_id", sa.Uuid(), nullable=False),
        sa.Column("supersedes_studio_release_id", sa.Uuid(), nullable=True),
        sa.Column("contract_version", sa.String(length=64), nullable=False),
        sa.Column("contract_hash", sa.String(length=64), nullable=False),
        sa.Column("tbox_hash", sa.String(length=64), nullable=False),
        sa.Column("abox_hash", sa.String(length=64), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=False),
        sa.Column("review_reason", sa.Text(), nullable=False),
        sa.Column("published_by", sa.Uuid(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "(state = 'ACTIVE' AND archived_at IS NULL AND archived_by IS NULL) OR "
            "(state = 'ARCHIVED' AND archived_at IS NOT NULL AND archived_by IS NOT NULL)",
            name=op.f("ck_studio_releases_state_shape"),
        ),
        sa.CheckConstraint(
            "contract_hash ~ '^[0-9a-f]{64}$' "
            "AND tbox_hash ~ '^[0-9a-f]{64}$' "
            "AND abox_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_studio_releases_hashes_sha256"),
        ),
        sa.CheckConstraint(
            "contract_version = 'KNOWLEDGE_STUDIO_RELEASE_V1'",
            name=op.f("ck_studio_releases_contract_version"),
        ),
        sa.CheckConstraint(
            "state IN ('ACTIVE', 'ARCHIVED')",
            name=op.f("ck_studio_releases_state_vocabulary"),
        ),
        sa.CheckConstraint(
            "release_no >= 1",
            name=op.f("ck_studio_releases_release_no_positive"),
        ),
        sa.CheckConstraint(
            "source_draft_version >= 1",
            name=op.f("ck_studio_releases_source_draft_version_positive"),
        ),
        sa.CheckConstraint(
            "reviewed_by <> author_id AND published_by = reviewed_by "
            "AND char_length(btrim(review_reason)) BETWEEN 1 AND 2000",
            name=op.f("ck_studio_releases_independent_review"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "archived_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name=op.f("fk_studio_releases_workspace_id_archived_by_workspace_memberships"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "author_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name=op.f("fk_studio_releases_workspace_id_author_id_workspace_memberships"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id", "ontology_version_id"],
            [
                "knowledge.ontology_versions.workspace_id",
                "knowledge.ontology_versions.graph_id",
                "knowledge.ontology_versions.id",
            ],
            name=op.f(
                "fk_studio_releases_workspace_id_graph_id_ontology_version_id_ontology_versions"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id"],
            ["knowledge.graphs.workspace_id", "knowledge.graphs.id"],
            name=op.f("fk_studio_releases_workspace_id_graph_id_graphs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "preflight_check_id"],
            [
                "knowledge.studio_preflight_checks.workspace_id",
                "knowledge.studio_preflight_checks.id",
            ],
            name=op.f("fk_studio_releases_workspace_id_preflight_check_id_studio_preflight_checks"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "workspace_id",
                "source_draft_id",
                "source_draft_version",
                "contract_hash",
                "reviewed_by",
                "preflight_check_id",
            ],
            [
                "knowledge.studio_preflight_checks.workspace_id",
                "knowledge.studio_preflight_checks.draft_id",
                "knowledge.studio_preflight_checks.draft_version",
                "knowledge.studio_preflight_checks.contract_hash",
                "knowledge.studio_preflight_checks.checked_by",
                "knowledge.studio_preflight_checks.id",
            ],
            name=op.f(
                "fk_studio_releases_workspace_id_source_draft_id_"
                "source_draft_version_contract_hash_reviewed_by_"
                "preflight_check_id_studio_preflight_checks"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "published_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name=op.f("fk_studio_releases_workspace_id_published_by_workspace_memberships"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "reviewed_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name=op.f("fk_studio_releases_workspace_id_reviewed_by_workspace_memberships"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_draft_id"],
            ["knowledge.studio_drafts.workspace_id", "knowledge.studio_drafts.id"],
            name=op.f("fk_studio_releases_workspace_id_source_draft_id_studio_drafts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "supersedes_studio_release_id"],
            ["knowledge.studio_releases.workspace_id", "knowledge.studio_releases.id"],
            name=op.f(
                "fk_studio_releases_workspace_id_supersedes_studio_release_id_studio_releases"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_studio_releases")),
        sa.UniqueConstraint(
            "graph_id",
            "contract_hash",
            name=op.f("uq_studio_releases_graph_id_contract_hash"),
        ),
        sa.UniqueConstraint(
            "graph_id",
            "release_no",
            name=op.f("uq_studio_releases_graph_id_release_no"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "graph_id",
            "id",
            name=op.f("uq_studio_releases_workspace_id_graph_id_id"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name=op.f("uq_studio_releases_workspace_id_id"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "source_draft_id",
            name=op.f("uq_studio_releases_workspace_id_source_draft_id"),
        ),
        schema="knowledge",
    )
    op.create_index(if_not_exists=True, "ix_studio_releases_graph_state_published",
        "studio_releases",
        ["workspace_id", "graph_id", "state", "published_at"],
        unique=False,
        schema="knowledge",
    )
    op.create_index(if_not_exists=True, "uq_studio_releases_one_active_per_graph",
        "studio_releases",
        ["graph_id"],
        unique=True,
        schema="knowledge",
        postgresql_where=sa.text("state = 'ACTIVE'"),
    )


def _create_binding_versions() -> None:
    op.create_table(
        "abox_binding_versions",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("graph_id", sa.Uuid(), nullable=False),
        sa.Column("studio_release_id", sa.Uuid(), nullable=False),
        sa.Column("ontology_version_id", sa.Uuid(), nullable=False),
        sa.Column("target_ontology_element_id", sa.Uuid(), nullable=False),
        sa.Column("target_stable_element_id", sa.String(length=128), nullable=False),
        sa.Column("source_reference_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("mapping_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "mapping_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_abox_binding_versions_mapping_hash_sha256"),
        ),
        sa.CheckConstraint(
            "ordinal >= 0",
            name=op.f("ck_abox_binding_versions_ordinal_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "created_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name=op.f("fk_abox_binding_versions_workspace_id_created_by_workspace_memberships"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id", "ontology_version_id"],
            [
                "knowledge.ontology_versions.workspace_id",
                "knowledge.ontology_versions.graph_id",
                "knowledge.ontology_versions.id",
            ],
            name=op.f(
                "fk_abox_binding_versions_workspace_id_graph_id_"
                "ontology_version_id_ontology_versions"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id", "studio_release_id"],
            [
                "knowledge.studio_releases.workspace_id",
                "knowledge.studio_releases.graph_id",
                "knowledge.studio_releases.id",
            ],
            name=op.f(
                "fk_abox_binding_versions_workspace_id_graph_id_studio_release_id_studio_releases"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "ontology_version_id", "target_ontology_element_id"],
            [
                "knowledge.ontology_elements.workspace_id",
                "knowledge.ontology_elements.ontology_version_id",
                "knowledge.ontology_elements.id",
            ],
            name=op.f(
                "fk_abox_binding_versions_workspace_id_ontology_version_id_"
                "target_ontology_element_id_ontology_elements"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_reference_id"],
            ["knowledge.source_references.workspace_id", "knowledge.source_references.id"],
            name=op.f(
                "fk_abox_binding_versions_workspace_id_source_reference_id_source_references"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_abox_binding_versions")),
        sa.UniqueConstraint(
            "workspace_id",
            "studio_release_id",
            "id",
            name=op.f("uq_abox_binding_versions_workspace_id_studio_release_id_id"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "studio_release_id",
            "ordinal",
            name=op.f("uq_abox_binding_versions_workspace_id_studio_release_id_ordinal"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "studio_release_id",
            "target_stable_element_id",
            name=op.f(
                "uq_abox_binding_versions_workspace_id_studio_release_id_target_stable_element_id"
            ),
        ),
        schema="knowledge",
    )
    op.create_index(if_not_exists=True, "ix_abox_binding_versions_release_ordinal",
        "abox_binding_versions",
        ["workspace_id", "studio_release_id", "ordinal"],
        unique=False,
        schema="knowledge",
    )
    op.create_table(
        "abox_mapping_rule_versions",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("studio_release_id", sa.Uuid(), nullable=False),
        sa.Column("binding_version_id", sa.Uuid(), nullable=False),
        sa.Column("ontology_version_id", sa.Uuid(), nullable=False),
        sa.Column("target_ontology_element_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("source_field_path", sa.Text(), nullable=False),
        sa.Column("target_stable_element_id", sa.String(length=128), nullable=False),
        sa.Column("transform_id", sa.String(length=64), nullable=False),
        sa.Column("transform_version", sa.String(length=32), nullable=False),
        sa.Column("source_unit", sa.String(length=100), nullable=True),
        sa.Column("canonical_unit", sa.String(length=100), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "method IN ('SUBJECT_ID', 'PROPERTY', 'EDGE_LINK', 'EDGE_PROPERTY')",
            name=op.f("ck_abox_mapping_rule_versions_method_vocabulary"),
        ),
        sa.CheckConstraint(
            "ordinal >= 0",
            name=op.f("ck_abox_mapping_rule_versions_ordinal_nonnegative"),
        ),
        sa.CheckConstraint(
            "transform_id = 'IDENTITY' AND transform_version = '1'",
            name=op.f("ck_abox_mapping_rule_versions_identity_transform_only"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "ontology_version_id", "target_ontology_element_id"],
            [
                "knowledge.ontology_elements.workspace_id",
                "knowledge.ontology_elements.ontology_version_id",
                "knowledge.ontology_elements.id",
            ],
            name=op.f(
                "fk_abox_mapping_rule_versions_workspace_id_ontology_version_id_"
                "target_ontology_element_id_ontology_elements"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "studio_release_id", "binding_version_id"],
            [
                "knowledge.abox_binding_versions.workspace_id",
                "knowledge.abox_binding_versions.studio_release_id",
                "knowledge.abox_binding_versions.id",
            ],
            name=op.f(
                "fk_abox_mapping_rule_versions_workspace_id_studio_release_id_"
                "binding_version_id_abox_binding_versions"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_abox_mapping_rule_versions")),
        sa.UniqueConstraint(
            "workspace_id",
            "binding_version_id",
            "id",
            name=op.f("uq_abox_mapping_rule_versions_workspace_id_binding_version_id_id"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "binding_version_id",
            "ordinal",
            name=op.f("uq_abox_mapping_rule_versions_workspace_id_binding_version_id_ordinal"),
        ),
        schema="knowledge",
    )
    op.create_index(if_not_exists=True, "ix_abox_mapping_rule_versions_binding_ordinal",
        "abox_mapping_rule_versions",
        ["workspace_id", "binding_version_id", "ordinal"],
        unique=False,
        schema="knowledge",
    )


def _add_deferred_foreign_keys() -> None:
    op.create_foreign_key(
        op.f("fk_graphs_workspace_id_id_active_studio_release_id_studio_releases"),
        "graphs",
        "studio_releases",
        ["workspace_id", "id", "active_studio_release_id"],
        ["workspace_id", "graph_id", "id"],
        source_schema="knowledge",
        referent_schema="knowledge",
        ondelete="RESTRICT",
        use_alter=True,
    )
    op.create_foreign_key(
        op.f("fk_studio_drafts_workspace_id_submitted_preflight_check_id_studio_preflight_checks"),
        "studio_drafts",
        "studio_preflight_checks",
        ["workspace_id", "submitted_preflight_check_id"],
        ["workspace_id", "id"],
        source_schema="knowledge",
        referent_schema="knowledge",
        ondelete="RESTRICT",
        use_alter=True,
    )
    op.create_foreign_key(
        op.f(
            "fk_studio_drafts_workspace_id_materialized_graph_id_"
            "published_studio_release_id_studio_releases"
        ),
        "studio_drafts",
        "studio_releases",
        ["workspace_id", "materialized_graph_id", "published_studio_release_id"],
        ["workspace_id", "graph_id", "id"],
        source_schema="knowledge",
        referent_schema="knowledge",
        ondelete="RESTRICT",
        use_alter=True,
    )


def _enable_workspace_rls() -> None:
    for table in (
        "ontology_elements",
        "studio_preflight_checks",
        "studio_releases",
        "abox_binding_versions",
        "abox_mapping_rule_versions",
    ):
        op.execute(f"ALTER TABLE knowledge.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE knowledge.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY workspace_isolation ON knowledge.{table}
            USING (workspace_id = {CURRENT_WORKSPACE})
            WITH CHECK (workspace_id = {CURRENT_WORKSPACE})
            """
        )


def _replace_draft_rls() -> None:
    op.execute("DROP POLICY studio_draft_owner_access ON knowledge.studio_drafts")
    owner = f"author_id = {CURRENT_SUBJECT}"
    reviewer = _reviewer_sql("studio_drafts")
    publisher = _reviewer_sql("studio_drafts", require_publish=True)
    op.execute(
        f"""
        CREATE POLICY studio_draft_actor_select ON knowledge.studio_drafts
        AS RESTRICTIVE FOR SELECT TO datariver_app
        USING (
            {owner}
            OR (state IN ('REVIEW', 'PUBLISHED') AND {reviewer})
        )
        """
    )
    op.execute(
        f"""
        CREATE POLICY studio_draft_author_insert ON knowledge.studio_drafts
        AS RESTRICTIVE FOR INSERT TO datariver_app
        WITH CHECK ({owner} AND state = 'DRAFT')
        """
    )
    op.execute(
        f"""
        CREATE POLICY studio_draft_governed_update ON knowledge.studio_drafts
        AS RESTRICTIVE FOR UPDATE TO datariver_app
        USING (
            ({owner} AND state IN ('DRAFT', 'REVIEW'))
            OR (state = 'REVIEW' AND {publisher})
        )
        WITH CHECK (
            ({owner} AND state IN ('DRAFT', 'REVIEW', 'DISCARDED'))
            OR (
                state = 'PUBLISHED'
                AND reviewed_by = {CURRENT_SUBJECT}
                AND published_by = {CURRENT_SUBJECT}
                AND {publisher}
            )
        )
        """
    )
    for table in (
        "tbox_draft_elements",
        "abox_binding_drafts",
        "abox_mapping_rule_drafts",
    ):
        op.execute(f"DROP POLICY studio_draft_owner_access ON knowledge.{table}")
        owner_parent = (
            "EXISTS (SELECT 1 FROM knowledge.studio_drafts AS owned_draft "
            f"WHERE owned_draft.workspace_id = {table}.workspace_id "
            f"AND owned_draft.id = {table}.draft_id "
            f"AND owned_draft.author_id = {CURRENT_SUBJECT} "
            "AND owned_draft.state = 'DRAFT')"
        )
        actor_parent = (
            "EXISTS (SELECT 1 FROM knowledge.studio_drafts AS visible_draft "
            f"WHERE visible_draft.workspace_id = {table}.workspace_id "
            f"AND visible_draft.id = {table}.draft_id "
            f"AND ({_draft_actor_read_sql('visible_draft')}))"
        )
        op.execute(
            f"""
            CREATE POLICY studio_draft_actor_select ON knowledge.{table}
            AS RESTRICTIVE FOR SELECT TO datariver_app
            USING ({actor_parent})
            """
        )
        op.execute(
            f"""
            CREATE POLICY studio_draft_owner_insert ON knowledge.{table}
            AS RESTRICTIVE FOR INSERT TO datariver_app
            WITH CHECK ({owner_parent})
            """
        )
        op.execute(
            f"""
            CREATE POLICY studio_draft_owner_update ON knowledge.{table}
            AS RESTRICTIVE FOR UPDATE TO datariver_app
            USING ({owner_parent})
            WITH CHECK ({owner_parent})
            """
        )
        op.execute(
            f"""
            CREATE POLICY studio_draft_owner_delete ON knowledge.{table}
            AS RESTRICTIVE FOR DELETE TO datariver_app
            USING ({owner_parent})
            """
        )
    op.execute("DROP POLICY source_reference_owner_access ON knowledge.source_references")
    op.execute(
        f"""
        CREATE POLICY source_reference_actor_select ON knowledge.source_references
        AS RESTRICTIVE FOR SELECT TO datariver_app
        USING (
            created_by = {CURRENT_SUBJECT}
            OR EXISTS (
                SELECT 1
                FROM knowledge.abox_binding_drafts AS binding
                JOIN knowledge.studio_drafts AS bound_draft
                  ON bound_draft.workspace_id = binding.workspace_id
                 AND bound_draft.id = binding.draft_id
                WHERE binding.workspace_id = source_references.workspace_id
                  AND binding.source_reference_id = source_references.id
                  AND bound_draft.state IN ('REVIEW', 'PUBLISHED')
                  AND {_reviewer_sql("bound_draft")}
            )
        )
        """
    )
    op.execute(
        f"""
        CREATE POLICY source_reference_owner_insert ON knowledge.source_references
        AS RESTRICTIVE FOR INSERT TO datariver_app
        WITH CHECK (created_by = {CURRENT_SUBJECT})
        """
    )


def _install_preflight_rls() -> None:
    visible_parent = (
        "EXISTS (SELECT 1 FROM knowledge.studio_drafts AS visible_draft "
        "WHERE visible_draft.workspace_id = studio_preflight_checks.workspace_id "
        "AND visible_draft.id = studio_preflight_checks.draft_id "
        f"AND ({_draft_actor_read_sql('visible_draft')}))"
    )
    insert_parent = (
        "EXISTS (SELECT 1 FROM knowledge.studio_drafts AS target_draft "
        "WHERE target_draft.workspace_id = studio_preflight_checks.workspace_id "
        "AND target_draft.id = studio_preflight_checks.draft_id "
        "AND ((target_draft.state = 'DRAFT' "
        f"AND target_draft.author_id = {CURRENT_SUBJECT}) "
        "OR (target_draft.state = 'REVIEW' "
        f"AND {_reviewer_sql('target_draft')})))"
    )
    op.execute(
        f"""
        CREATE POLICY studio_preflight_actor_select
        ON knowledge.studio_preflight_checks
        AS RESTRICTIVE FOR SELECT TO datariver_app
        USING ({visible_parent})
        """
    )
    op.execute(
        f"""
        CREATE POLICY studio_preflight_actor_insert
        ON knowledge.studio_preflight_checks
        AS RESTRICTIVE FOR INSERT TO datariver_app
        WITH CHECK (
            checked_by = {CURRENT_SUBJECT}
            AND {insert_parent}
        )
        """
    )


def _install_release_rls() -> None:
    insert_parent = (
        "EXISTS (SELECT 1 FROM knowledge.studio_drafts AS source_draft "
        "WHERE source_draft.workspace_id = studio_releases.workspace_id "
        "AND source_draft.id = studio_releases.source_draft_id "
        "AND source_draft.state = 'REVIEW' "
        f"AND {_reviewer_sql('source_draft', require_publish=True)})"
    )
    archive_parent = (
        "EXISTS (SELECT 1 FROM knowledge.studio_drafts AS source_draft "
        "WHERE source_draft.workspace_id = studio_releases.workspace_id "
        "AND source_draft.id = studio_releases.source_draft_id "
        "AND source_draft.state = 'PUBLISHED' "
        f"AND {_reviewer_sql('source_draft', require_publish=True)})"
    )
    op.execute(
        f"""
        CREATE POLICY studio_release_publisher_insert
        ON knowledge.studio_releases
        AS RESTRICTIVE FOR INSERT TO datariver_app
        WITH CHECK (
            reviewed_by = {CURRENT_SUBJECT}
            AND published_by = {CURRENT_SUBJECT}
            AND {insert_parent}
        )
        """
    )
    op.execute(
        f"""
        CREATE POLICY studio_release_publisher_archive
        ON knowledge.studio_releases
        AS RESTRICTIVE FOR UPDATE TO datariver_app
        USING (
            state = 'ACTIVE'
            AND {archive_parent}
        )
        WITH CHECK (
            state = 'ARCHIVED'
            AND archived_by = {CURRENT_SUBJECT}
            AND {archive_parent}
        )
        """
    )


def _grant_application_access() -> None:
    op.execute(
        """
        DO $grant$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
                GRANT SELECT, INSERT ON knowledge.studio_preflight_checks
                    TO datariver_app;
                GRANT SELECT, INSERT ON knowledge.studio_releases,
                    knowledge.ontology_elements,
                    knowledge.abox_binding_versions,
                    knowledge.abox_mapping_rule_versions
                    TO datariver_app;
                GRANT UPDATE (state, archived_at, archived_by)
                    ON knowledge.studio_releases TO datariver_app;
                GRANT UPDATE (
                    submitted_preflight_check_id,
                    reviewed_by, reviewed_at, review_reason,
                    published_by, published_at,
                    materialized_graph_id, materialized_ontology_version_id,
                    published_studio_release_id,
                    version, updated_at
                ) ON knowledge.studio_drafts TO datariver_app;
            END IF;
        END
        $grant$
        """
    )


def upgrade() -> None:
    if _canonical_contract_is_complete():
        return
    _guard_legacy_publications()
    _extend_draft_and_graph()
    _create_ontology_elements()
    _create_preflight_checks()
    _create_studio_releases()
    _create_binding_versions()
    _add_deferred_foreign_keys()
    _enable_workspace_rls()
    _replace_draft_rls()
    _install_preflight_rls()
    _install_release_rls()
    _grant_application_access()


def downgrade() -> None:
    row_count = int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    (SELECT count(*) FROM knowledge.studio_preflight_checks)
                  + (SELECT count(*) FROM knowledge.studio_releases)
                  + (SELECT count(*) FROM knowledge.ontology_elements)
                  + (SELECT count(*) FROM knowledge.abox_binding_versions)
                  + (SELECT count(*) FROM knowledge.abox_mapping_rule_versions)
                """
            )
        )
        .scalar_one()
    )
    published_draft_count = int(
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM knowledge.studio_drafts WHERE state = 'PUBLISHED'"))
        .scalar_one()
    )
    if row_count or published_draft_count:
        raise RuntimeError(
            "Governed Studio publication evidence exists; downgrade would destroy history."
        )
    op.execute(
        """
        DO $revoke$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datariver_app') THEN
                REVOKE ALL ON knowledge.studio_preflight_checks,
                    knowledge.studio_releases,
                    knowledge.ontology_elements,
                    knowledge.abox_binding_versions,
                    knowledge.abox_mapping_rule_versions
                    FROM datariver_app;
            END IF;
        END
        $revoke$
        """
    )
    op.execute("DROP POLICY studio_draft_actor_select ON knowledge.studio_drafts")
    op.execute("DROP POLICY studio_draft_author_insert ON knowledge.studio_drafts")
    op.execute("DROP POLICY studio_draft_governed_update ON knowledge.studio_drafts")
    op.execute(
        f"""
        CREATE POLICY studio_draft_owner_access ON knowledge.studio_drafts
        AS RESTRICTIVE FOR ALL TO datariver_app
        USING (author_id = {CURRENT_SUBJECT})
        WITH CHECK (author_id = {CURRENT_SUBJECT})
        """
    )
    for table in (
        "tbox_draft_elements",
        "abox_binding_drafts",
        "abox_mapping_rule_drafts",
    ):
        for policy in (
            "studio_draft_actor_select",
            "studio_draft_owner_insert",
            "studio_draft_owner_update",
            "studio_draft_owner_delete",
        ):
            op.execute(f"DROP POLICY {policy} ON knowledge.{table}")
        owner = (
            "EXISTS (SELECT 1 FROM knowledge.studio_drafts AS draft "
            f"WHERE draft.workspace_id = {table}.workspace_id "
            f"AND draft.id = {table}.draft_id "
            f"AND draft.author_id = {CURRENT_SUBJECT})"
        )
        op.execute(
            f"""
            CREATE POLICY studio_draft_owner_access ON knowledge.{table}
            AS RESTRICTIVE FOR ALL TO datariver_app
            USING ({owner}) WITH CHECK ({owner})
            """
        )
    op.execute("DROP POLICY source_reference_actor_select ON knowledge.source_references")
    op.execute("DROP POLICY source_reference_owner_insert ON knowledge.source_references")
    op.execute(
        f"""
        CREATE POLICY source_reference_owner_access ON knowledge.source_references
        AS RESTRICTIVE FOR ALL TO datariver_app
        USING (created_by = {CURRENT_SUBJECT})
        WITH CHECK (created_by = {CURRENT_SUBJECT})
        """
    )
    op.drop_constraint(
        op.f(
            "fk_studio_drafts_workspace_id_materialized_graph_id_"
            "published_studio_release_id_studio_releases"
        ),
        "studio_drafts",
        schema="knowledge",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_studio_drafts_workspace_id_submitted_preflight_check_id_studio_preflight_checks"),
        "studio_drafts",
        schema="knowledge",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_graphs_workspace_id_id_active_studio_release_id_studio_releases"),
        "graphs",
        schema="knowledge",
        type_="foreignkey",
    )
    op.drop_table("abox_mapping_rule_versions", schema="knowledge")
    op.drop_table("abox_binding_versions", schema="knowledge")
    op.drop_table("studio_releases", schema="knowledge")
    op.drop_table("studio_preflight_checks", schema="knowledge")
    op.drop_table("ontology_elements", schema="knowledge")
    op.drop_constraint(
        op.f(
            "fk_studio_drafts_workspace_id_materialized_graph_id_"
            "materialized_ontology_version_id_ontology_versions"
        ),
        "studio_drafts",
        schema="knowledge",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_studio_drafts_workspace_id_materialized_graph_id_graphs"),
        "studio_drafts",
        schema="knowledge",
        type_="foreignkey",
    )
    for column in ("published_by", "reviewed_by"):
        op.drop_constraint(
            op.f(f"fk_studio_drafts_workspace_id_{column}_workspace_memberships"),
            "studio_drafts",
            schema="knowledge",
            type_="foreignkey",
        )
    op.drop_constraint(
        op.f("ck_studio_drafts_state_shape"),
        "studio_drafts",
        schema="knowledge",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_studio_drafts_state_shape"),
        "studio_drafts",
        "(state = 'DRAFT' AND review_requested_at IS NULL "
        "AND published_at IS NULL AND discarded_at IS NULL AND discarded_by IS NULL) OR "
        "(state = 'REVIEW' AND review_requested_at IS NOT NULL "
        "AND published_at IS NULL AND discarded_at IS NULL AND discarded_by IS NULL) OR "
        "(state = 'PUBLISHED' AND review_requested_at IS NOT NULL "
        "AND published_at IS NOT NULL AND discarded_at IS NULL AND discarded_by IS NULL) OR "
        "(state = 'DISCARDED' AND published_at IS NULL "
        "AND discarded_at IS NOT NULL AND discarded_by = author_id)",
        schema="knowledge",
    )
    for column in (
        "published_studio_release_id",
        "materialized_ontology_version_id",
        "materialized_graph_id",
        "published_by",
        "review_reason",
        "reviewed_at",
        "reviewed_by",
        "submitted_preflight_check_id",
    ):
        op.drop_column("studio_drafts", column, schema="knowledge")
    op.drop_column("graphs", "active_studio_release_id", schema="knowledge")
