from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from datariver.infrastructure.db.base import (
    JSON_DOCUMENT,
    Base,
    TimestampMixin,
    UuidPrimaryKeyMixin,
    VersionMixin,
)


class KnowledgeStudioDraftModel(
    Base,
    UuidPrimaryKeyMixin,
    TimestampMixin,
    VersionMixin,
):
    """Author-owned, recoverable state that is not a consumable knowledge graph."""

    __tablename__ = "studio_drafts"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        CheckConstraint("kind IN ('CREATE', 'EDIT')", name="kind_vocabulary"),
        CheckConstraint(
            "state IN ('DRAFT', 'REVIEW', 'PUBLISHED', 'DISCARDED')",
            name="state_vocabulary",
        ),
        CheckConstraint(
            "current_step IN ('BASIC', 'TBOX', 'ABOX')",
            name="current_step_vocabulary",
        ),
        CheckConstraint(
            "char_length(name) BETWEEN 1 AND 255 AND name = btrim(name)",
            name="name_valid",
        ),
        CheckConstraint(
            "endpoint_alias ~ '^[a-z][a-z0-9_]{2,99}$'",
            name="endpoint_alias_shape",
        ),
        CheckConstraint(
            "domain_ref_kind = 'DOMAIN' AND char_length(domain_source_version) BETWEEN 1 AND 255",
            name="domain_reference_shape",
        ),
        CheckConstraint(
            "classification BETWEEN 0 AND 3",
            name="classification_range",
        ),
        CheckConstraint(
            "(kind = 'CREATE' AND base_graph_id IS NULL "
            "AND base_ontology_version_id IS NULL AND base_release_id IS NULL) OR "
            "(kind = 'EDIT' AND base_graph_id IS NOT NULL "
            "AND base_ontology_version_id IS NOT NULL)",
            name="base_reference_shape",
        ),
        CheckConstraint(
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
            name="state_shape",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "author_id"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "discarded_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "reviewed_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "published_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "domain_ref_id", "domain_ref_kind"),
            (
                "catalog.vocabulary_entries.workspace_id",
                "catalog.vocabulary_entries.id",
                "catalog.vocabulary_entries.kind",
            ),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "base_graph_id"),
            ("knowledge.graphs.workspace_id", "knowledge.graphs.id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "base_graph_id", "base_ontology_version_id"),
            (
                "knowledge.ontology_versions.workspace_id",
                "knowledge.ontology_versions.graph_id",
                "knowledge.ontology_versions.id",
            ),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "base_graph_id", "base_release_id"),
            (
                "knowledge.releases.workspace_id",
                "knowledge.releases.graph_id",
                "knowledge.releases.id",
            ),
            ondelete="RESTRICT",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ("workspace_id", "submitted_preflight_check_id"),
            (
                "knowledge.studio_preflight_checks.workspace_id",
                "knowledge.studio_preflight_checks.id",
            ),
            ondelete="RESTRICT",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ("workspace_id", "materialized_graph_id"),
            ("knowledge.graphs.workspace_id", "knowledge.graphs.id"),
            ondelete="RESTRICT",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            (
                "workspace_id",
                "materialized_graph_id",
                "materialized_ontology_version_id",
            ),
            (
                "knowledge.ontology_versions.workspace_id",
                "knowledge.ontology_versions.graph_id",
                "knowledge.ontology_versions.id",
            ),
            ondelete="RESTRICT",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            (
                "workspace_id",
                "materialized_graph_id",
                "published_studio_release_id",
            ),
            (
                "knowledge.studio_releases.workspace_id",
                "knowledge.studio_releases.graph_id",
                "knowledge.studio_releases.id",
            ),
            ondelete="RESTRICT",
            use_alter=True,
        ),
        Index(
            "ix_studio_drafts_owner_updated",
            "workspace_id",
            "author_id",
            "updated_at",
            "id",
        ),
        Index(
            "uq_studio_drafts_live_endpoint_alias",
            "workspace_id",
            "endpoint_alias",
            unique=True,
            postgresql_where=text("state IN ('DRAFT', 'REVIEW')"),
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    author_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(16), default="DRAFT", nullable=False)
    current_step: Mapped[str] = mapped_column(String(16), default="BASIC", nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    endpoint_alias: Mapped[str] = mapped_column(String(100), nullable=False)
    domain_ref_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    domain_ref_kind: Mapped[str] = mapped_column(
        String(16),
        default="DOMAIN",
        nullable=False,
    )
    domain_source_version: Mapped[str] = mapped_column(String(255), nullable=False)
    classification: Mapped[int] = mapped_column(nullable=False)
    base_graph_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    base_ontology_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    base_release_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    review_requested_at: Mapped[datetime | None]
    submitted_preflight_check_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    reviewed_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    reviewed_at: Mapped[datetime | None]
    review_reason: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None]
    published_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    materialized_graph_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    materialized_ontology_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    published_studio_release_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    discarded_at: Mapped[datetime | None]
    discarded_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    last_autosaved_at: Mapped[datetime] = mapped_column(nullable=False)


class TBoxDraftElementModel(
    Base,
    UuidPrimaryKeyMixin,
    TimestampMixin,
    VersionMixin,
):
    """Typed read index of accepted Draft operations; never an A-Box mutation target."""

    __tablename__ = "tbox_draft_elements"
    __table_args__ = (
        UniqueConstraint("workspace_id", "draft_id", "id"),
        UniqueConstraint("workspace_id", "draft_id", "stable_element_id"),
        UniqueConstraint("workspace_id", "draft_id", "ordinal"),
        CheckConstraint(
            "kind IN ('CLASS', 'PROPERTY', 'RELATION')",
            name="kind_vocabulary",
        ),
        CheckConstraint(
            "char_length(stable_element_id) BETWEEN 1 AND 128 "
            "AND stable_element_id = btrim(stable_element_id)",
            name="stable_element_id_valid",
        ),
        CheckConstraint(
            "char_length(canonical_name) BETWEEN 1 AND 255 "
            "AND canonical_name = btrim(canonical_name)",
            name="canonical_name_valid",
        ),
        CheckConstraint(
            "char_length(display_name) BETWEEN 1 AND 255 AND display_name = btrim(display_name)",
            name="display_name_valid",
        ),
        CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        CheckConstraint(
            "(kind = 'CLASS' AND parent_stable_element_id IS NULL "
            "AND source_stable_element_id IS NULL AND target_stable_element_id IS NULL "
            "AND data_type IS NULL AND nullable IS NULL) OR "
            "(kind = 'PROPERTY' AND parent_stable_element_id IS NOT NULL "
            "AND source_stable_element_id IS NULL AND target_stable_element_id IS NULL "
            "AND data_type IS NOT NULL AND nullable IS NOT NULL) OR "
            "(kind = 'RELATION' AND parent_stable_element_id IS NULL "
            "AND source_stable_element_id IS NOT NULL AND target_stable_element_id IS NOT NULL "
            "AND data_type IS NULL AND nullable IS NULL)",
            name="element_shape",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "draft_id"),
            ("knowledge.studio_drafts.workspace_id", "knowledge.studio_drafts.id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "draft_id", "parent_stable_element_id"),
            (
                "knowledge.tbox_draft_elements.workspace_id",
                "knowledge.tbox_draft_elements.draft_id",
                "knowledge.tbox_draft_elements.stable_element_id",
            ),
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "draft_id", "source_stable_element_id"),
            (
                "knowledge.tbox_draft_elements.workspace_id",
                "knowledge.tbox_draft_elements.draft_id",
                "knowledge.tbox_draft_elements.stable_element_id",
            ),
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "draft_id", "target_stable_element_id"),
            (
                "knowledge.tbox_draft_elements.workspace_id",
                "knowledge.tbox_draft_elements.draft_id",
                "knowledge.tbox_draft_elements.stable_element_id",
            ),
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index(
            "ix_tbox_draft_elements_draft_kind_ordinal",
            "workspace_id",
            "draft_id",
            "kind",
            "ordinal",
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    draft_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    stable_element_id: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_stable_element_id: Mapped[str | None] = mapped_column(String(128))
    source_stable_element_id: Mapped[str | None] = mapped_column(String(128))
    target_stable_element_id: Mapped[str | None] = mapped_column(String(128))
    data_type: Mapped[str | None] = mapped_column(String(100))
    nullable: Mapped[bool | None] = mapped_column(Boolean)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)


class KnowledgeSourceReferenceModel(Base, UuidPrimaryKeyMixin):
    """Immutable, provider-opaque source pin used by Studio binding drafts."""

    __tablename__ = "source_references"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint(
            "workspace_id",
            "created_by",
            "kind",
            "catalog_asset_id",
            "source_version",
            "projection_source_version",
            "selection_hash",
            name="uq_source_references_actor_contract",
        ),
        CheckConstraint("kind = 'CATALOG_DATASET'", name="kind_vocabulary"),
        CheckConstraint(
            "char_length(source_version) BETWEEN 1 AND 255 "
            "AND source_version = btrim(source_version)",
            name="source_version_valid",
        ),
        CheckConstraint(
            "char_length(projection_source_version) BETWEEN 1 AND 255 "
            "AND projection_source_version = btrim(projection_source_version)",
            name="projection_source_version_valid",
        ),
        CheckConstraint("classification BETWEEN 0 AND 3", name="classification_range"),
        CheckConstraint(
            "jsonb_typeof(selection_document) = 'object'",
            name="selection_document_object",
        ),
        CheckConstraint(
            "selection_hash ~ '^[0-9a-f]{64}$'",
            name="selection_hash_sha256",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "catalog_asset_id"),
            ("catalog.assets_projection.workspace_id", "catalog.assets_projection.id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "created_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
        ),
        Index(
            "ix_source_references_workspace_asset_version",
            "workspace_id",
            "catalog_asset_id",
            "source_version",
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    catalog_asset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_version: Mapped[str] = mapped_column(String(255), nullable=False)
    projection_source_version: Mapped[str] = mapped_column(String(255), nullable=False)
    classification: Mapped[int] = mapped_column(Integer, nullable=False)
    selection_document: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT,
        nullable=False,
    )
    selection_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


class ABoxBindingDraftModel(
    Base,
    UuidPrimaryKeyMixin,
    TimestampMixin,
    VersionMixin,
):
    """Mutable source binding for one accepted T-Box Class or Relation."""

    __tablename__ = "abox_binding_drafts"
    __table_args__ = (
        UniqueConstraint("workspace_id", "draft_id", "id"),
        UniqueConstraint("workspace_id", "draft_id", "target_stable_element_id"),
        CheckConstraint(
            "readiness IN ('DRAFT', 'VALIDATED', 'STALE')",
            name="readiness_vocabulary",
        ),
        CheckConstraint("tbox_version >= 1", name="tbox_version_positive"),
        ForeignKeyConstraint(
            ("workspace_id", "draft_id"),
            ("knowledge.studio_drafts.workspace_id", "knowledge.studio_drafts.id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "draft_id", "target_stable_element_id"),
            (
                "knowledge.tbox_draft_elements.workspace_id",
                "knowledge.tbox_draft_elements.draft_id",
                "knowledge.tbox_draft_elements.stable_element_id",
            ),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "source_reference_id"),
            ("knowledge.source_references.workspace_id", "knowledge.source_references.id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "created_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "updated_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
        ),
        Index(
            "ix_abox_binding_drafts_draft_readiness",
            "workspace_id",
            "draft_id",
            "readiness",
            "target_stable_element_id",
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    draft_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    target_stable_element_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_reference_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    readiness: Mapped[str] = mapped_column(String(16), nullable=False)
    tbox_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    updated_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)


class ABoxMappingRuleDraftModel(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """Typed mapping row; arbitrary expressions and provider identifiers are forbidden."""

    __tablename__ = "abox_mapping_rule_drafts"
    __table_args__ = (
        UniqueConstraint("workspace_id", "draft_id", "binding_id", "id"),
        UniqueConstraint("workspace_id", "binding_id", "ordinal"),
        UniqueConstraint(
            "workspace_id",
            "binding_id",
            "method",
            "target_stable_element_id",
            name="uq_abox_mapping_rule_drafts_target_method",
        ),
        CheckConstraint(
            "method IN ('SUBJECT_ID', 'PROPERTY', 'EDGE_LINK', 'EDGE_PROPERTY')",
            name="method_vocabulary",
        ),
        CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        CheckConstraint(
            "char_length(source_field_path) BETWEEN 1 AND 2000 "
            "AND source_field_path = btrim(source_field_path)",
            name="source_field_path_valid",
        ),
        CheckConstraint(
            "char_length(target_stable_element_id) BETWEEN 1 AND 128 "
            "AND target_stable_element_id = btrim(target_stable_element_id)",
            name="target_stable_element_id_valid",
        ),
        CheckConstraint(
            "transform_id = 'IDENTITY' AND transform_version = '1'",
            name="identity_transform_only",
        ),
        CheckConstraint(
            "(source_unit IS NULL AND canonical_unit IS NULL) OR "
            "(source_unit IS NOT NULL AND canonical_unit IS NOT NULL "
            "AND char_length(source_unit) BETWEEN 1 AND 100 "
            "AND char_length(canonical_unit) BETWEEN 1 AND 100)",
            name="unit_pair",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "draft_id", "binding_id"),
            (
                "knowledge.abox_binding_drafts.workspace_id",
                "knowledge.abox_binding_drafts.draft_id",
                "knowledge.abox_binding_drafts.id",
            ),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "draft_id", "target_stable_element_id"),
            (
                "knowledge.tbox_draft_elements.workspace_id",
                "knowledge.tbox_draft_elements.draft_id",
                "knowledge.tbox_draft_elements.stable_element_id",
            ),
            ondelete="RESTRICT",
        ),
        Index(
            "ix_abox_mapping_rule_drafts_binding_ordinal",
            "workspace_id",
            "binding_id",
            "ordinal",
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    draft_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    binding_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    source_field_path: Mapped[str] = mapped_column(Text, nullable=False)
    target_stable_element_id: Mapped[str] = mapped_column(String(128), nullable=False)
    transform_id: Mapped[str] = mapped_column(String(64), nullable=False)
    transform_version: Mapped[str] = mapped_column(String(32), nullable=False)
    source_unit: Mapped[str | None] = mapped_column(String(100))
    canonical_unit: Mapped[str | None] = mapped_column(String(100))


class KnowledgeStudioPreflightCheckModel(Base, UuidPrimaryKeyMixin):
    """Append-only evidence for one exact Studio contract version."""

    __tablename__ = "studio_preflight_checks"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint(
            "workspace_id",
            "draft_id",
            "draft_version",
            "contract_hash",
            "checked_by",
            "id",
        ),
        CheckConstraint("draft_version >= 1", name="draft_version_positive"),
        CheckConstraint(
            "status IN ('PASS', 'FAIL', 'UNAVAILABLE')",
            name="status_vocabulary",
        ),
        CheckConstraint(
            "(status = 'PASS' AND valid IS TRUE) OR "
            "(status IN ('FAIL', 'UNAVAILABLE') AND valid IS FALSE)",
            name="status_valid_shape",
        ),
        CheckConstraint(
            "contract_hash ~ '^[0-9a-f]{64}$' AND evidence_hash ~ '^[0-9a-f]{64}$'",
            name="hashes_sha256",
        ),
        CheckConstraint(
            "validation_contract_version = 'KNOWLEDGE_STUDIO_PREFLIGHT_V1'",
            name="contract_version",
        ),
        CheckConstraint(
            "jsonb_typeof(evidence_document) = 'array'",
            name="evidence_document_array",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "draft_id"),
            ("knowledge.studio_drafts.workspace_id", "knowledge.studio_drafts.id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "checked_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
        ),
        Index(
            "ix_studio_preflight_checks_draft_checked",
            "workspace_id",
            "draft_id",
            "checked_at",
            "id",
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    draft_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    draft_version: Mapped[int] = mapped_column(Integer, nullable=False)
    contract_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    validation_contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_document: Mapped[list[dict[str, object]]] = mapped_column(
        JSON_DOCUMENT,
        nullable=False,
    )
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    checked_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(nullable=False)


class KnowledgeStudioReleaseModel(Base, UuidPrimaryKeyMixin):
    """Immutable T-Box/A-Box contract release with a mutable lifecycle marker only."""

    __tablename__ = "studio_releases"
    __table_args__ = (
        UniqueConstraint("workspace_id", "graph_id", "id"),
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "source_draft_id"),
        UniqueConstraint("graph_id", "release_no"),
        UniqueConstraint("graph_id", "contract_hash"),
        CheckConstraint("release_no >= 1", name="release_no_positive"),
        CheckConstraint("source_draft_version >= 1", name="source_draft_version_positive"),
        CheckConstraint("state IN ('ACTIVE', 'ARCHIVED')", name="state_vocabulary"),
        CheckConstraint(
            "(state = 'ACTIVE' AND archived_at IS NULL AND archived_by IS NULL) OR "
            "(state = 'ARCHIVED' AND archived_at IS NOT NULL AND archived_by IS NOT NULL)",
            name="state_shape",
        ),
        CheckConstraint(
            "contract_version = 'KNOWLEDGE_STUDIO_RELEASE_V1'",
            name="contract_version",
        ),
        CheckConstraint(
            "contract_hash ~ '^[0-9a-f]{64}$' "
            "AND tbox_hash ~ '^[0-9a-f]{64}$' "
            "AND abox_hash ~ '^[0-9a-f]{64}$'",
            name="hashes_sha256",
        ),
        CheckConstraint(
            "reviewed_by <> author_id AND published_by = reviewed_by "
            "AND char_length(btrim(review_reason)) BETWEEN 1 AND 2000",
            name="independent_review",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id"),
            ("knowledge.graphs.workspace_id", "knowledge.graphs.id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id", "ontology_version_id"),
            (
                "knowledge.ontology_versions.workspace_id",
                "knowledge.ontology_versions.graph_id",
                "knowledge.ontology_versions.id",
            ),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "source_draft_id"),
            ("knowledge.studio_drafts.workspace_id", "knowledge.studio_drafts.id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "preflight_check_id"),
            (
                "knowledge.studio_preflight_checks.workspace_id",
                "knowledge.studio_preflight_checks.id",
            ),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            (
                "workspace_id",
                "source_draft_id",
                "source_draft_version",
                "contract_hash",
                "reviewed_by",
                "preflight_check_id",
            ),
            (
                "knowledge.studio_preflight_checks.workspace_id",
                "knowledge.studio_preflight_checks.draft_id",
                "knowledge.studio_preflight_checks.draft_version",
                "knowledge.studio_preflight_checks.contract_hash",
                "knowledge.studio_preflight_checks.checked_by",
                "knowledge.studio_preflight_checks.id",
            ),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "supersedes_studio_release_id"),
            ("knowledge.studio_releases.workspace_id", "knowledge.studio_releases.id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "author_id"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "reviewed_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "published_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "archived_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
        ),
        Index(
            "ix_studio_releases_graph_state_published",
            "workspace_id",
            "graph_id",
            "state",
            "published_at",
        ),
        Index(
            "uq_studio_releases_one_active_per_graph",
            "graph_id",
            unique=True,
            postgresql_where=text("state = 'ACTIVE'"),
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    graph_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_draft_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_draft_version: Mapped[int] = mapped_column(Integer, nullable=False)
    release_no: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    ontology_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    preflight_check_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    supersedes_studio_release_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    tbox_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    abox_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    author_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reviewed_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    review_reason: Mapped[str] = mapped_column(Text, nullable=False)
    published_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    published_at: Mapped[datetime] = mapped_column(nullable=False)
    archived_at: Mapped[datetime | None]
    archived_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))


class OntologyElementModel(Base, UuidPrimaryKeyMixin):
    """Immutable searchable index derived from one ontology schema document."""

    __tablename__ = "ontology_elements"
    __table_args__ = (
        UniqueConstraint("workspace_id", "ontology_version_id", "id"),
        UniqueConstraint(
            "workspace_id",
            "ontology_version_id",
            "stable_element_id",
        ),
        UniqueConstraint("workspace_id", "ontology_version_id", "ordinal"),
        CheckConstraint(
            "kind IN ('CLASS', 'PROPERTY', 'RELATION')",
            name="kind_vocabulary",
        ),
        CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        CheckConstraint(
            "element_hash ~ '^[0-9a-f]{64}$'",
            name="element_hash_sha256",
        ),
        CheckConstraint(
            "jsonb_typeof(element_document) = 'object'",
            name="element_document_object",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id", "ontology_version_id"),
            (
                "knowledge.ontology_versions.workspace_id",
                "knowledge.ontology_versions.graph_id",
                "knowledge.ontology_versions.id",
            ),
            ondelete="RESTRICT",
        ),
        Index(
            "ix_ontology_elements_version_kind_ordinal",
            "workspace_id",
            "ontology_version_id",
            "kind",
            "ordinal",
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    graph_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ontology_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    stable_element_id: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    element_document: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    element_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ABoxBindingVersionModel(Base, UuidPrimaryKeyMixin):
    """Immutable mapping-spec header published with a Studio Release."""

    __tablename__ = "abox_binding_versions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "studio_release_id", "id"),
        UniqueConstraint(
            "workspace_id",
            "studio_release_id",
            "target_stable_element_id",
        ),
        UniqueConstraint("workspace_id", "studio_release_id", "ordinal"),
        CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        CheckConstraint(
            "mapping_hash ~ '^[0-9a-f]{64}$'",
            name="mapping_hash_sha256",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id", "studio_release_id"),
            (
                "knowledge.studio_releases.workspace_id",
                "knowledge.studio_releases.graph_id",
                "knowledge.studio_releases.id",
            ),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id", "ontology_version_id"),
            (
                "knowledge.ontology_versions.workspace_id",
                "knowledge.ontology_versions.graph_id",
                "knowledge.ontology_versions.id",
            ),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            (
                "workspace_id",
                "ontology_version_id",
                "target_ontology_element_id",
            ),
            (
                "knowledge.ontology_elements.workspace_id",
                "knowledge.ontology_elements.ontology_version_id",
                "knowledge.ontology_elements.id",
            ),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "source_reference_id"),
            ("knowledge.source_references.workspace_id", "knowledge.source_references.id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "created_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
        ),
        Index(
            "ix_abox_binding_versions_release_ordinal",
            "workspace_id",
            "studio_release_id",
            "ordinal",
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    graph_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    studio_release_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ontology_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    target_ontology_element_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    target_stable_element_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_reference_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    mapping_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)


class ABoxMappingRuleVersionModel(Base, UuidPrimaryKeyMixin):
    """Immutable typed rule copied from one approved Binding Draft."""

    __tablename__ = "abox_mapping_rule_versions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "binding_version_id", "id"),
        UniqueConstraint("workspace_id", "binding_version_id", "ordinal"),
        CheckConstraint(
            "method IN ('SUBJECT_ID', 'PROPERTY', 'EDGE_LINK', 'EDGE_PROPERTY')",
            name="method_vocabulary",
        ),
        CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        CheckConstraint(
            "transform_id = 'IDENTITY' AND transform_version = '1'",
            name="identity_transform_only",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "studio_release_id", "binding_version_id"),
            (
                "knowledge.abox_binding_versions.workspace_id",
                "knowledge.abox_binding_versions.studio_release_id",
                "knowledge.abox_binding_versions.id",
            ),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            (
                "workspace_id",
                "ontology_version_id",
                "target_ontology_element_id",
            ),
            (
                "knowledge.ontology_elements.workspace_id",
                "knowledge.ontology_elements.ontology_version_id",
                "knowledge.ontology_elements.id",
            ),
            ondelete="RESTRICT",
        ),
        Index(
            "ix_abox_mapping_rule_versions_binding_ordinal",
            "workspace_id",
            "binding_version_id",
            "ordinal",
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    studio_release_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    binding_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ontology_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    target_ontology_element_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    source_field_path: Mapped[str] = mapped_column(Text, nullable=False)
    target_stable_element_id: Mapped[str] = mapped_column(String(128), nullable=False)
    transform_id: Mapped[str] = mapped_column(String(64), nullable=False)
    transform_version: Mapped[str] = mapped_column(String(32), nullable=False)
    source_unit: Mapped[str | None] = mapped_column(String(100))
    canonical_unit: Mapped[str | None] = mapped_column(String(100))
