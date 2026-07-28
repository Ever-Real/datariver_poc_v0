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
            "AND published_at IS NULL AND discarded_at IS NULL AND discarded_by IS NULL) OR "
            "(state = 'REVIEW' AND review_requested_at IS NOT NULL "
            "AND published_at IS NULL AND discarded_at IS NULL AND discarded_by IS NULL) OR "
            "(state = 'PUBLISHED' AND review_requested_at IS NOT NULL "
            "AND published_at IS NOT NULL AND discarded_at IS NULL AND discarded_by IS NULL) OR "
            "(state = 'DISCARDED' AND published_at IS NULL "
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
    published_at: Mapped[datetime | None]
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
