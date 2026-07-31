from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Float,
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

from datariver.domain.knowledge_studio import DEFAULT_TBOX_BLOCK_WEIGHT
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
            "jsonb_typeof(endpoint_aliases) = 'array' "
            "AND jsonb_array_length(endpoint_aliases) BETWEEN 1 AND 10 "
            "AND endpoint_aliases ->> 0 = endpoint_alias",
            name="endpoint_aliases_shape",
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
        Index(
            "ix_studio_drafts_workspace_endpoint_aliases_live",
            "endpoint_aliases",
            postgresql_using="gin",
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
    endpoint_aliases: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT,
        nullable=False,
    )
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
    """Stable identity and block ownership shared by normalized T-Box element tables."""

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
        ForeignKeyConstraint(
            ("workspace_id", "draft_id"),
            ("knowledge.studio_drafts.workspace_id", "knowledge.studio_drafts.id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "draft_id", "block_id"),
            (
                "knowledge.tbox_draft_blocks.workspace_id",
                "knowledge.tbox_draft_blocks.draft_id",
                "knowledge.tbox_draft_blocks.id",
            ),
            ondelete="RESTRICT",
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
    block_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    stable_element_id: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    definition: Mapped[str | None] = mapped_column(Text)
    aliases: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT,
        default=list,
        nullable=False,
    )
    layout_x: Mapped[float | None] = mapped_column(Float)
    layout_y: Mapped[float | None] = mapped_column(Float)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)


class TBoxClassModel(
    Base,
    UuidPrimaryKeyMixin,
    TimestampMixin,
    VersionMixin,
):
    """Normalized T-Box Class schema, including the canonical class hierarchy."""

    __tablename__ = "tbox_classes"
    __table_args__ = (
        UniqueConstraint("workspace_id", "draft_id", "id"),
        UniqueConstraint("workspace_id", "draft_id", "stable_class_id"),
        CheckConstraint(
            "parent_stable_class_id IS NULL OR parent_stable_class_id <> stable_class_id",
            name="parent_not_self",
        ),
        CheckConstraint(
            "metadata_reference_urn IS NULL OR "
            "(char_length(metadata_reference_urn) BETWEEN 1 AND 2000 "
            "AND metadata_reference_urn = btrim(metadata_reference_urn))",
            name="metadata_reference_urn_valid",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "draft_id", "stable_class_id"),
            (
                "knowledge.tbox_draft_elements.workspace_id",
                "knowledge.tbox_draft_elements.draft_id",
                "knowledge.tbox_draft_elements.stable_element_id",
            ),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "draft_id", "parent_stable_class_id"),
            (
                "knowledge.tbox_classes.workspace_id",
                "knowledge.tbox_classes.draft_id",
                "knowledge.tbox_classes.stable_class_id",
            ),
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index(
            "ix_tbox_classes_parent",
            "workspace_id",
            "draft_id",
            "parent_stable_class_id",
            "stable_class_id",
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    draft_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    stable_class_id: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_stable_class_id: Mapped[str | None] = mapped_column(String(128))
    hierarchy_relation: Mapped[str] = mapped_column(
        String(255),
        default="SUBCLASS_OF",
        nullable=False,
    )
    metadata_reference_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    metadata_reference_urn: Mapped[str | None] = mapped_column(String(2_000))


class TBoxPropertyModel(
    Base,
    UuidPrimaryKeyMixin,
    TimestampMixin,
    VersionMixin,
):
    """Normalized Property schema owned by exactly one T-Box Class."""

    __tablename__ = "tbox_properties"
    __table_args__ = (
        UniqueConstraint("workspace_id", "draft_id", "id"),
        UniqueConstraint("workspace_id", "draft_id", "stable_property_id"),
        CheckConstraint(
            "char_length(data_type) BETWEEN 1 AND 100 AND data_type = btrim(data_type)",
            name="data_type_valid",
        ),
        CheckConstraint(
            "metadata_reference_urn IS NULL OR "
            "(char_length(metadata_reference_urn) BETWEEN 1 AND 2000 "
            "AND metadata_reference_urn = btrim(metadata_reference_urn))",
            name="metadata_reference_urn_valid",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "draft_id", "stable_property_id"),
            (
                "knowledge.tbox_draft_elements.workspace_id",
                "knowledge.tbox_draft_elements.draft_id",
                "knowledge.tbox_draft_elements.stable_element_id",
            ),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "draft_id", "owner_stable_class_id"),
            (
                "knowledge.tbox_classes.workspace_id",
                "knowledge.tbox_classes.draft_id",
                "knowledge.tbox_classes.stable_class_id",
            ),
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index(
            "ix_tbox_properties_owner",
            "workspace_id",
            "draft_id",
            "owner_stable_class_id",
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    draft_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    stable_property_id: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_stable_class_id: Mapped[str] = mapped_column(String(128), nullable=False)
    data_type: Mapped[str] = mapped_column(String(100), nullable=False)
    nullable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(100))
    vector_index_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_reference_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    metadata_reference_urn: Mapped[str | None] = mapped_column(String(2_000))


class TBoxRelationshipModel(
    Base,
    UuidPrimaryKeyMixin,
    TimestampMixin,
    VersionMixin,
):
    """Normalized non-taxonomic Class relationship schema."""

    __tablename__ = "tbox_relationships"
    __table_args__ = (
        UniqueConstraint("workspace_id", "draft_id", "id"),
        UniqueConstraint("workspace_id", "draft_id", "stable_relationship_id"),
        CheckConstraint("relationship_kind = 'ASSOCIATION'", name="relationship_kind_vocabulary"),
        CheckConstraint(
            "metadata_reference_urn IS NULL OR "
            "(char_length(metadata_reference_urn) BETWEEN 1 AND 2000 "
            "AND metadata_reference_urn = btrim(metadata_reference_urn))",
            name="metadata_reference_urn_valid",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "draft_id", "stable_relationship_id"),
            (
                "knowledge.tbox_draft_elements.workspace_id",
                "knowledge.tbox_draft_elements.draft_id",
                "knowledge.tbox_draft_elements.stable_element_id",
            ),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "draft_id", "source_stable_class_id"),
            (
                "knowledge.tbox_classes.workspace_id",
                "knowledge.tbox_classes.draft_id",
                "knowledge.tbox_classes.stable_class_id",
            ),
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "draft_id", "target_stable_class_id"),
            (
                "knowledge.tbox_classes.workspace_id",
                "knowledge.tbox_classes.draft_id",
                "knowledge.tbox_classes.stable_class_id",
            ),
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index(
            "ix_tbox_relationships_endpoints",
            "workspace_id",
            "draft_id",
            "source_stable_class_id",
            "target_stable_class_id",
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    draft_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    stable_relationship_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_stable_class_id: Mapped[str] = mapped_column(String(128), nullable=False)
    target_stable_class_id: Mapped[str] = mapped_column(String(128), nullable=False)
    relationship_kind: Mapped[str] = mapped_column(
        String(24),
        default="ASSOCIATION",
        nullable=False,
    )
    metadata_reference_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    metadata_reference_urn: Mapped[str | None] = mapped_column(String(2_000))


class TBoxDraftBlockModel(
    Base,
    UuidPrimaryKeyMixin,
    TimestampMixin,
    VersionMixin,
):
    """Ordered, independently collapsible T-Box authoring layer."""

    __tablename__ = "tbox_draft_blocks"
    __table_args__ = (
        UniqueConstraint("workspace_id", "draft_id", "id"),
        UniqueConstraint("workspace_id", "draft_id", "ordinal"),
        CheckConstraint(
            "kind IN ('DIRECT', 'DOCUMENT_SCHEMA', 'CATALOG_METADATA', "
            "'ASSET_RELEASE', 'LLM_ASSISTANT')",
            name="kind_vocabulary",
        ),
        CheckConstraint(
            "char_length(title) BETWEEN 1 AND 120 AND title = btrim(title)",
            name="title_valid",
        ),
        CheckConstraint("weight BETWEEN 0 AND 100", name="weight_range"),
        CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        ForeignKeyConstraint(
            ("workspace_id", "draft_id"),
            ("knowledge.studio_drafts.workspace_id", "knowledge.studio_drafts.id"),
            ondelete="RESTRICT",
        ),
        Index(
            "ix_tbox_draft_blocks_draft_ordinal",
            "workspace_id",
            "draft_id",
            "ordinal",
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    draft_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    weight: Mapped[int] = mapped_column(
        Integer,
        default=DEFAULT_TBOX_BLOCK_WEIGHT,
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    collapsed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_reference: Mapped[dict[str, object] | None] = mapped_column(JSON_DOCUMENT)


class TBoxProposalModel(
    Base,
    UuidPrimaryKeyMixin,
    TimestampMixin,
    VersionMixin,
):
    """Typed LLM proposal. It cannot mutate a Draft until explicitly accepted."""

    __tablename__ = "tbox_proposals"
    __table_args__ = (
        UniqueConstraint("workspace_id", "draft_id", "id"),
        CheckConstraint(
            "state IN ('READY', 'APPLIED', 'REJECTED', 'FAILED')",
            name="state_vocabulary",
        ),
        CheckConstraint(
            "mode IN ('MERGE_INTO_CURRENT', 'APPEND_LAYER')",
            name="mode_vocabulary",
        ),
        CheckConstraint(
            "merge_strategy IN ('KEEP_ORIGINAL', 'ACCEPT_PROPOSAL', 'RESOLVE')",
            name="merge_strategy_vocabulary",
        ),
        CheckConstraint(
            "char_length(prompt) BETWEEN 1 AND 4000 AND prompt = btrim(prompt)",
            name="prompt_valid",
        ),
        CheckConstraint("base_draft_version >= 1", name="base_draft_version_positive"),
        CheckConstraint(
            "jsonb_typeof(proposal_document) = 'object'",
            name="proposal_document_object",
        ),
        CheckConstraint(
            "jsonb_typeof(conflicts_document) = 'array'",
            name="conflicts_document_array",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "draft_id"),
            ("knowledge.studio_drafts.workspace_id", "knowledge.studio_drafts.id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "draft_id", "target_block_id"),
            (
                "knowledge.tbox_draft_blocks.workspace_id",
                "knowledge.tbox_draft_blocks.draft_id",
                "knowledge.tbox_draft_blocks.id",
            ),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "created_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
        ),
        Index(
            "ix_tbox_proposals_draft_created",
            "workspace_id",
            "draft_id",
            "created_at",
            "id",
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    draft_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    target_block_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    merge_strategy: Mapped[str] = mapped_column(String(24), nullable=False)
    base_draft_version: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    proposal_document: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT,
        nullable=False,
    )
    conflicts_document: Mapped[list[dict[str, object]]] = mapped_column(
        JSON_DOCUMENT,
        nullable=False,
    )
    model_binding_document: Mapped[dict[str, object] | None] = mapped_column(JSON_DOCUMENT)
    source_reference_document: Mapped[dict[str, object] | None] = mapped_column(JSON_DOCUMENT)
    error_code: Mapped[str | None] = mapped_column(String(100))
    applied_at: Mapped[datetime | None]
    rejected_at: Mapped[datetime | None]


class KnowledgeStudioProposalJobModel(
    Base,
    UuidPrimaryKeyMixin,
    TimestampMixin,
    VersionMixin,
):
    """Pinned, owner-scoped durable T-Box Proposal request."""

    __tablename__ = "tbox_proposal_jobs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "draft_id", "id"),
        CheckConstraint(
            "input_kind IN ('DOCUMENT_SCHEMA', 'CATALOG_SCHEMA')",
            name="input_kind_vocabulary",
        ),
        CheckConstraint(
            "mode IN ('MERGE_INTO_CURRENT', 'APPEND_LAYER')",
            name="mode_vocabulary",
        ),
        CheckConstraint(
            "(mode = 'MERGE_INTO_CURRENT' AND target_block_id IS NOT NULL) OR "
            "(mode = 'APPEND_LAYER' AND target_block_id IS NULL)",
            name="mode_target_shape",
        ),
        CheckConstraint(
            "state IN ('QUEUED', 'RUNNING', 'RETRY_WAIT', 'CANCEL_REQUESTED', "
            "'SUCCEEDED', 'FAILED', 'STALE', 'CANCELLED')",
            name="state_vocabulary",
        ),
        CheckConstraint(
            "stage IN ('QUEUED', 'SOURCE_VALIDATION', 'PARSING', 'INFERENCE', "
            "'VALIDATING', 'FINALIZING', 'COMPLETED')",
            name="stage_vocabulary",
        ),
        CheckConstraint(
            "progress_percent BETWEEN 0 AND 100",
            name="progress_range",
        ),
        CheckConstraint(
            "base_draft_version >= 1 AND (manifest_version IS NULL OR manifest_version >= 1)",
            name="source_versions_positive",
        ),
        CheckConstraint(
            "source_size_bytes IS NULL OR source_size_bytes BETWEEN 1 AND 10485760",
            name="source_size_range",
        ),
        CheckConstraint(
            "source_classification IS NULL OR source_classification BETWEEN 0 AND 1",
            name="source_classification_range",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND maximum_attempts BETWEEN 1 AND 20 "
            "AND attempt_count <= maximum_attempts "
            "AND lease_epoch >= attempt_count AND version >= 1",
            name="positive_counters",
        ),
        CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$' "
            "AND requester_authorization_hash ~ '^[0-9a-f]{64}$' "
            "AND base_tbox_hash ~ '^[0-9a-f]{64}$' "
            "AND parser_config_hash ~ '^[0-9a-f]{64}$' "
            "AND schema_binding_hash ~ '^[0-9a-f]{64}$' "
            "AND source_pin_hash ~ '^[0-9a-f]{64}$' "
            "AND pin_hash ~ '^[0-9a-f]{64}$'",
            name="evidence_hashes",
        ),
        CheckConstraint(
            "jsonb_typeof(schema_binding_document) = 'object' "
            "AND octet_length(schema_binding_document::text) <= 8192",
            name="schema_binding_bounded",
        ),
        CheckConstraint(
            "(input_kind = 'DOCUMENT_SCHEMA' "
            "AND manifest_id IS NOT NULL AND manifest_version IS NOT NULL "
            "AND source_content_hash ~ '^[0-9a-f]{64}$' "
            "AND source_media_type IS NOT NULL AND source_size_bytes IS NOT NULL "
            "AND source_classification IS NOT NULL AND source_content_profile IS NOT NULL "
            "AND source_validation_evidence_hash ~ '^[0-9a-f]{64}$' "
            "AND source_filename IS NOT NULL "
            "AND catalog_asset_id IS NULL "
            "AND catalog_source_document IS NULL AND catalog_source_hash IS NULL) OR "
            "(input_kind = 'CATALOG_SCHEMA' "
            "AND manifest_id IS NULL AND manifest_version IS NULL "
            "AND source_content_hash IS NULL AND source_media_type IS NULL "
            "AND source_size_bytes IS NULL AND source_content_profile IS NULL "
            "AND source_validation_evidence_hash IS NULL AND source_filename IS NULL "
            "AND source_classification IS NOT NULL AND catalog_asset_id IS NOT NULL "
            "AND jsonb_typeof(catalog_source_document) = 'object' "
            "AND octet_length(catalog_source_document::text) <= 65536 "
            "AND catalog_source_hash ~ '^[0-9a-f]{64}$')",
            name="source_pin_shape",
        ),
        CheckConstraint(
            "lease_token_hash IS NULL OR lease_token_hash ~ '^[0-9a-f]{64}$'",
            name="lease_token_hash",
        ),
        CheckConstraint(
            "(state IN ('RUNNING', 'CANCEL_REQUESTED') "
            "AND current_attempt_id IS NOT NULL AND lease_token_hash IS NOT NULL "
            "AND lease_owner_fingerprint IS NOT NULL AND lease_started_at IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR "
            "(state NOT IN ('RUNNING', 'CANCEL_REQUESTED') "
            "AND current_attempt_id IS NULL AND lease_token_hash IS NULL "
            "AND lease_owner_fingerprint IS NULL AND lease_started_at IS NULL "
            "AND lease_expires_at IS NULL)",
            name="lease_shape",
        ),
        CheckConstraint(
            "((state = 'SUCCEEDED') AND result_proposal_id IS NOT NULL "
            "AND result_evidence_hash ~ '^[0-9a-f]{64}$' "
            "AND completed_at IS NOT NULL AND last_failure_code IS NULL) OR "
            "((state <> 'SUCCEEDED') AND result_proposal_id IS NULL "
            "AND result_evidence_hash IS NULL)",
            name="result_shape",
        ),
        CheckConstraint(
            "((state IN ('FAILED', 'STALE')) AND last_failure_code IS NOT NULL "
            "AND completed_at IS NOT NULL) OR "
            "(state = 'RETRY_WAIT' AND last_failure_code IS NOT NULL "
            "AND completed_at IS NULL) OR "
            "((state NOT IN ('FAILED', 'STALE', 'RETRY_WAIT')) "
            "AND last_failure_code IS NULL)",
            name="failure_shape",
        ),
        CheckConstraint(
            "((state IN ('CANCEL_REQUESTED', 'CANCELLED')) "
            "AND cancel_requested_by IS NOT NULL AND cancel_requested_at IS NOT NULL "
            "AND cancel_reason IS NOT NULL) OR "
            "((state NOT IN ('CANCEL_REQUESTED', 'CANCELLED')) "
            "AND cancel_requested_by IS NULL AND cancel_requested_at IS NULL "
            "AND cancel_reason IS NULL)",
            name="cancel_shape",
        ),
        CheckConstraint(
            "(state IN ('SUCCEEDED', 'FAILED', 'STALE', 'CANCELLED')) = (completed_at IS NOT NULL)",
            name="terminal_completion",
        ),
        CheckConstraint(
            "(state IN ('SUCCEEDED', 'FAILED', 'STALE', 'CANCELLED')) = (stage = 'COMPLETED')",
            name="terminal_stage",
        ),
        CheckConstraint(
            "(state IN ('QUEUED', 'RETRY_WAIT') AND progress_percent = 0) OR "
            "(state IN ('RUNNING', 'CANCEL_REQUESTED') "
            "AND progress_percent BETWEEN 1 AND 99) OR "
            "(state = 'SUCCEEDED' AND progress_percent = 100) OR "
            "(state IN ('FAILED', 'STALE', 'CANCELLED') "
            "AND progress_percent BETWEEN 0 AND 99)",
            name="state_progress",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "draft_id"),
            ("knowledge.studio_drafts.workspace_id", "knowledge.studio_drafts.id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "draft_id", "target_block_id"),
            (
                "knowledge.tbox_draft_blocks.workspace_id",
                "knowledge.tbox_draft_blocks.draft_id",
                "knowledge.tbox_draft_blocks.id",
            ),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "requested_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "manifest_id"),
            ("integration.object_manifests.workspace_id", "integration.object_manifests.id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "catalog_asset_id"),
            ("catalog.assets_projection.workspace_id", "catalog.assets_projection.id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "cancel_requested_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "draft_id", "result_proposal_id"),
            (
                "knowledge.tbox_proposals.workspace_id",
                "knowledge.tbox_proposals.draft_id",
                "knowledge.tbox_proposals.id",
            ),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "supersedes_job_id"),
            ("knowledge.tbox_proposal_jobs.workspace_id", "knowledge.tbox_proposal_jobs.id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "id", "current_attempt_id"),
            (
                "knowledge.tbox_proposal_attempts.workspace_id",
                "knowledge.tbox_proposal_attempts.job_id",
                "knowledge.tbox_proposal_attempts.id",
            ),
            ondelete="RESTRICT",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        Index(
            "ix_tbox_proposal_jobs_owner_state",
            "workspace_id",
            "draft_id",
            "requested_by",
            "state",
            text("created_at DESC"),
            text("id DESC"),
        ),
        Index(
            "ix_tbox_proposal_jobs_claim",
            "workspace_id",
            "next_attempt_at",
            "created_at",
            "id",
            postgresql_where=text("state IN ('QUEUED', 'RETRY_WAIT')"),
        ),
        Index(
            "ix_tbox_proposal_jobs_expired",
            "workspace_id",
            "lease_expires_at",
            "id",
            postgresql_where=text("state IN ('RUNNING', 'CANCEL_REQUESTED')"),
        ),
        Index(
            "ux_tbox_proposal_jobs_one_successor",
            "workspace_id",
            "supersedes_job_id",
            unique=True,
            postgresql_where=text("supersedes_job_id IS NOT NULL"),
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    draft_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    target_block_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    requested_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    input_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    base_draft_version: Mapped[int] = mapped_column(Integer, nullable=False)
    base_tbox_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requester_authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_binding_document: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT,
        nullable=False,
    )
    schema_binding_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_pin_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    pin_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prepared_at: Mapped[datetime] = mapped_column(nullable=False)
    manifest_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    manifest_version: Mapped[int | None] = mapped_column(Integer)
    source_content_hash: Mapped[str | None] = mapped_column(String(64))
    source_media_type: Mapped[str | None] = mapped_column(String(255))
    source_size_bytes: Mapped[int | None] = mapped_column(Integer)
    source_classification: Mapped[int | None] = mapped_column(Integer)
    source_content_profile: Mapped[str | None] = mapped_column(String(100))
    source_validation_evidence_hash: Mapped[str | None] = mapped_column(String(64))
    source_filename: Mapped[str | None] = mapped_column(String(255))
    catalog_asset_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    catalog_source_document: Mapped[dict[str, object] | None] = mapped_column(JSON_DOCUMENT)
    catalog_source_hash: Mapped[str | None] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    maximum_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(nullable=False)
    current_attempt_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    lease_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lease_token_hash: Mapped[str | None] = mapped_column(String(64))
    lease_owner_fingerprint: Mapped[str | None] = mapped_column(String(255))
    lease_started_at: Mapped[datetime | None]
    lease_expires_at: Mapped[datetime | None]
    cancel_requested_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    cancel_requested_at: Mapped[datetime | None]
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    result_proposal_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    result_evidence_hash: Mapped[str | None] = mapped_column(String(64))
    last_failure_code: Mapped[str | None] = mapped_column(String(100))
    completed_at: Mapped[datetime | None]
    supersedes_job_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))


class KnowledgeStudioProposalAttemptModel(Base, UuidPrimaryKeyMixin):
    """Append-only worker attempt carrying a lease-token hash, never the raw token."""

    __tablename__ = "tbox_proposal_attempts"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "job_id", "id"),
        UniqueConstraint("workspace_id", "job_id", "attempt_no"),
        UniqueConstraint("workspace_id", "job_id", "lease_epoch"),
        CheckConstraint(
            "state IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'STALE', 'CANCELLED', 'SUPERSEDED')",
            name="state_vocabulary",
        ),
        CheckConstraint(
            "stage IN ('SOURCE_VALIDATION', 'PARSING', 'INFERENCE', 'VALIDATING', "
            "'FINALIZING', 'COMPLETED')",
            name="stage_vocabulary",
        ),
        CheckConstraint(
            "attempt_no >= 1 AND lease_epoch >= 1 AND lease_token_hash ~ '^[0-9a-f]{64}$'",
            name="claim_shape",
        ),
        CheckConstraint(
            "output_hash IS NULL OR output_hash ~ '^[0-9a-f]{64}$'",
            name="output_hash",
        ),
        CheckConstraint(
            "(state = 'RUNNING' AND finished_at IS NULL) OR "
            "(state <> 'RUNNING' AND finished_at IS NOT NULL)",
            name="finished_shape",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "job_id"),
            ("knowledge.tbox_proposal_jobs.workspace_id", "knowledge.tbox_proposal_jobs.id"),
            ondelete="RESTRICT",
        ),
        Index(
            "ix_tbox_proposal_attempts_job",
            "workspace_id",
            "job_id",
            "attempt_no",
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lease_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    worker_fingerprint: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(nullable=False)
    retryable: Mapped[bool | None] = mapped_column(Boolean)
    output_hash: Mapped[str | None] = mapped_column(String(64))
    failure_code: Mapped[str | None] = mapped_column(String(100))
    finished_at: Mapped[datetime | None]


class KnowledgeStudioProposalEventModel(Base):
    """Append-only bounded transition evidence for one Proposal job."""

    __tablename__ = "tbox_proposal_events"
    __table_args__ = (
        UniqueConstraint("workspace_id", "job_id", "sequence"),
        CheckConstraint("sequence >= 1", name="sequence_positive"),
        CheckConstraint(
            "state IN ('QUEUED', 'RUNNING', 'RETRY_WAIT', 'CANCEL_REQUESTED', "
            "'SUCCEEDED', 'FAILED', 'STALE', 'CANCELLED')",
            name="state_vocabulary",
        ),
        CheckConstraint(
            "stage IN ('QUEUED', 'SOURCE_VALIDATION', 'PARSING', 'INFERENCE', "
            "'VALIDATING', 'FINALIZING', 'COMPLETED')",
            name="stage_vocabulary",
        ),
        CheckConstraint(
            "actor_kind IN ('HUMAN', 'SERVICE') "
            "AND char_length(actor_ref) BETWEEN 1 AND 300 "
            "AND evidence_hash ~ '^[0-9a-f]{64}$'",
            name="evidence_shape",
        ),
        CheckConstraint(
            "jsonb_typeof(details_document) = 'object' "
            "AND octet_length(details_document::text) <= 8192",
            name="details_document_bounded",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "job_id"),
            ("knowledge.tbox_proposal_jobs.workspace_id", "knowledge.tbox_proposal_jobs.id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "job_id", "attempt_id"),
            (
                "knowledge.tbox_proposal_attempts.workspace_id",
                "knowledge.tbox_proposal_attempts.job_id",
                "knowledge.tbox_proposal_attempts.id",
            ),
            ondelete="RESTRICT",
        ),
        Index(
            "ix_tbox_proposal_events_job",
            "workspace_id",
            "job_id",
            "sequence",
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    attempt_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(100))
    details_document: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)


class KnowledgeStudioIngestionJobModel(
    Base,
    UuidPrimaryKeyMixin,
    TimestampMixin,
    VersionMixin,
):
    """Governed A-Box materialization request for one immutable Studio Release."""

    __tablename__ = "studio_ingestion_jobs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "graph_id", "id"),
        UniqueConstraint("workspace_id", "studio_release_id", "id"),
        CheckConstraint(
            "state IN ('PENDING', 'RUNNING', 'RETRY_WAIT', 'CANCEL_REQUESTED', "
            "'SUCCESS', 'FAILED', 'STALE', 'CANCELLED')",
            name="state_vocabulary",
        ),
        CheckConstraint(
            "stage IN ('QUEUED', 'SOURCE_READ', 'MAPPING', 'EMBEDDING', 'FINALIZING', 'COMPLETED')",
            name="stage_vocabulary",
        ),
        CheckConstraint(
            "progress_percent BETWEEN 0 AND 100",
            name="progress_range",
        ),
        CheckConstraint(
            "graph_classification BETWEEN 0 AND 3",
            name="classification_range",
        ),
        CheckConstraint(
            "(graph_domain_ref_id IS NULL AND graph_domain_source_version IS NULL) OR "
            "(graph_domain_ref_id IS NOT NULL AND graph_domain_source_version IS NOT NULL)",
            name="domain_reference_shape",
        ),
        CheckConstraint(
            "graph_version >= 1 AND studio_release_no >= 1 "
            "AND manifest_version >= 1 AND vector_target_count >= 0 "
            "AND attempt_count >= 0 AND maximum_attempts BETWEEN 1 AND 20 "
            "AND attempt_count <= maximum_attempts "
            "AND lease_epoch >= attempt_count AND version >= 1",
            name="positive_counters",
        ),
        CheckConstraint(
            "manifest_hash ~ '^[0-9a-f]{64}$' "
            "AND pin_hash ~ '^[0-9a-f]{64}$' "
            "AND request_hash ~ '^[0-9a-f]{64}$' "
            "AND requester_authorization_hash ~ '^[0-9a-f]{64}$' "
            "AND studio_contract_hash ~ '^[0-9a-f]{64}$' "
            "AND ontology_checksum ~ '^[0-9a-f]{64}$'",
            name="evidence_hashes",
        ),
        CheckConstraint(
            "(embedding_binding_document IS NULL AND embedding_binding_hash IS NULL) OR "
            "(jsonb_typeof(embedding_binding_document) = 'object' "
            "AND octet_length(embedding_binding_document::text) <= 8192 "
            "AND embedding_binding_hash ~ '^[0-9a-f]{64}$')",
            name="embedding_binding_shape",
        ),
        CheckConstraint(
            "(base_release_id IS NULL AND base_release_hash IS NULL) OR "
            "(base_release_id IS NOT NULL AND base_release_hash ~ '^[0-9a-f]{64}$')",
            name="base_release_shape",
        ),
        CheckConstraint(
            "lease_token_hash IS NULL OR lease_token_hash ~ '^[0-9a-f]{64}$'",
            name="lease_token_hash",
        ),
        CheckConstraint(
            "(state IN ('RUNNING', 'CANCEL_REQUESTED') "
            "AND current_attempt_id IS NOT NULL AND lease_token_hash IS NOT NULL "
            "AND lease_owner_fingerprint IS NOT NULL AND lease_started_at IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR "
            "(state NOT IN ('RUNNING', 'CANCEL_REQUESTED') "
            "AND lease_token_hash IS NULL AND lease_owner_fingerprint IS NULL "
            "AND lease_started_at IS NULL AND lease_expires_at IS NULL)",
            name="lease_shape",
        ),
        CheckConstraint(
            "((state = 'SUCCESS') AND result_changeset_id IS NOT NULL "
            "AND result_evidence_hash ~ '^[0-9a-f]{64}$' "
            "AND source_read_receipt_hash ~ '^[0-9a-f]{64}$' "
            "AND completed_at IS NOT NULL AND last_failure_code IS NULL) OR "
            "((state <> 'SUCCESS') AND result_changeset_id IS NULL "
            "AND result_evidence_hash IS NULL AND source_read_receipt_hash IS NULL)",
            name="result_shape",
        ),
        CheckConstraint(
            "((state IN ('FAILED', 'STALE')) AND last_failure_code IS NOT NULL "
            "AND completed_at IS NOT NULL) OR "
            "(state = 'RETRY_WAIT' AND last_failure_code IS NOT NULL "
            "AND completed_at IS NULL) OR "
            "((state NOT IN ('FAILED', 'STALE', 'RETRY_WAIT')) "
            "AND last_failure_code IS NULL)",
            name="failure_shape",
        ),
        CheckConstraint(
            "((state IN ('CANCEL_REQUESTED', 'CANCELLED')) "
            "AND cancel_requested_by IS NOT NULL AND cancel_requested_at IS NOT NULL "
            "AND cancel_reason IS NOT NULL) OR "
            "((state NOT IN ('CANCEL_REQUESTED', 'CANCELLED')) "
            "AND cancel_requested_by IS NULL AND cancel_requested_at IS NULL "
            "AND cancel_reason IS NULL)",
            name="cancel_shape",
        ),
        CheckConstraint(
            "(state IN ('SUCCESS', 'FAILED', 'STALE', 'CANCELLED')) = (completed_at IS NOT NULL)",
            name="terminal_completion",
        ),
        CheckConstraint(
            "(state IN ('SUCCESS', 'FAILED', 'STALE', 'CANCELLED')) = (stage = 'COMPLETED')",
            name="terminal_stage",
        ),
        CheckConstraint(
            "(state IN ('PENDING', 'RETRY_WAIT') AND progress_percent = 0) OR "
            "(state IN ('RUNNING', 'CANCEL_REQUESTED') "
            "AND progress_percent BETWEEN 1 AND 99) OR "
            "(state = 'SUCCESS' AND progress_percent = 100) OR "
            "(state IN ('FAILED', 'STALE', 'CANCELLED') "
            "AND progress_percent BETWEEN 0 AND 99)",
            name="state_progress",
        ),
        CheckConstraint(
            "source_access_deadline IS NULL OR "
            "(source_access_started_at IS NOT NULL "
            "AND source_access_deadline > source_access_started_at)",
            name="source_access_window",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id"),
            ("knowledge.graphs.workspace_id", "knowledge.graphs.id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "draft_id"),
            ("knowledge.studio_drafts.workspace_id", "knowledge.studio_drafts.id"),
            ondelete="RESTRICT",
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
            ("workspace_id", "result_changeset_id", "id"),
            (
                "knowledge.changesets.workspace_id",
                "knowledge.changesets.id",
                "knowledge.changesets.studio_ingestion_job_id",
            ),
            ondelete="RESTRICT",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "id", "current_attempt_id"),
            (
                "knowledge.studio_ingestion_attempts.workspace_id",
                "knowledge.studio_ingestion_attempts.job_id",
                "knowledge.studio_ingestion_attempts.id",
            ),
            ondelete="RESTRICT",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id", "base_release_id"),
            (
                "knowledge.releases.workspace_id",
                "knowledge.releases.graph_id",
                "knowledge.releases.id",
            ),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "requested_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "cancel_requested_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
        ),
        Index(
            "ix_studio_ingestion_jobs_graph_created",
            "workspace_id",
            "graph_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
        Index(
            "ix_studio_ingestion_jobs_claim",
            "workspace_id",
            "next_attempt_at",
            "created_at",
            "id",
            postgresql_where=text("state IN ('PENDING', 'RETRY_WAIT')"),
        ),
        Index(
            "ix_studio_ingestion_jobs_expired",
            "workspace_id",
            "lease_expires_at",
            "id",
            postgresql_where=text("state IN ('RUNNING', 'CANCEL_REQUESTED')"),
        ),
        Index(
            "ix_studio_ingestion_jobs_draft_created",
            "workspace_id",
            "draft_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    graph_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    draft_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    studio_release_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    studio_release_no: Mapped[int] = mapped_column(Integer, nullable=False)
    studio_contract_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ontology_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ontology_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    graph_version: Mapped[int] = mapped_column(Integer, nullable=False)
    graph_classification: Mapped[int] = mapped_column(Integer, nullable=False)
    graph_domain_ref_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    graph_domain_source_version: Mapped[str | None] = mapped_column(String(255))
    vector_target_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    state: Mapped[str] = mapped_column(String(24), default="PENDING", nullable=False)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stage: Mapped[str] = mapped_column(String(32), default="QUEUED", nullable=False)
    manifest_id: Mapped[str] = mapped_column(String(255), nullable=False)
    manifest_version: Mapped[int] = mapped_column(Integer, nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    pin_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requester_authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_binding_document: Mapped[dict[str, object] | None] = mapped_column(JSON_DOCUMENT)
    embedding_binding_hash: Mapped[str | None] = mapped_column(String(64))
    base_release_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    base_release_hash: Mapped[str | None] = mapped_column(String(64))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    maximum_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    current_attempt_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    next_attempt_at: Mapped[datetime] = mapped_column(nullable=False)
    lease_epoch: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    lease_token_hash: Mapped[str | None] = mapped_column(String(64))
    lease_owner_fingerprint: Mapped[str | None] = mapped_column(String(255))
    lease_started_at: Mapped[datetime | None]
    lease_expires_at: Mapped[datetime | None]
    source_access_started_at: Mapped[datetime | None]
    source_access_deadline: Mapped[datetime | None]
    result_changeset_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    result_evidence_hash: Mapped[str | None] = mapped_column(String(64))
    source_read_receipt_hash: Mapped[str | None] = mapped_column(String(64))
    last_failure_code: Mapped[str | None] = mapped_column(String(100))
    cancel_requested_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    cancel_requested_at: Mapped[datetime | None]
    cancel_reason: Mapped[str | None] = mapped_column(String(500))
    completed_at: Mapped[datetime | None]


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
        UniqueConstraint(
            "workspace_id",
            "graph_id",
            "id",
            "ontology_version_id",
            name="uq_studio_releases_profile_release_ontology",
        ),
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
        UniqueConstraint(
            "workspace_id",
            "ontology_version_id",
            "id",
            "kind",
            "stable_element_id",
            name="uq_ontology_elements_profile_identity",
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


class KnowledgePropertyProfileModel(
    Base,
    UuidPrimaryKeyMixin,
    TimestampMixin,
    VersionMixin,
):
    """Mutable semantic profile bound to one immutable released Property."""

    __tablename__ = "property_profiles"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        CheckConstraint(
            "lifecycle IN ('ACTIVE', 'ARCHIVED')",
            name="lifecycle_vocabulary",
        ),
        CheckConstraint(
            "element_kind = 'PROPERTY'",
            name="element_kind_property",
        ),
        CheckConstraint(
            "char_length(stable_property_id) BETWEEN 1 AND 128 "
            "AND stable_property_id = btrim(stable_property_id)",
            name="stable_property_id_valid",
        ),
        CheckConstraint(
            "description IS NULL OR "
            "(char_length(description) BETWEEN 1 AND 2000 "
            "AND description = btrim(description))",
            name="description_valid",
        ),
        CheckConstraint(
            "unit IS NULL OR (char_length(unit) BETWEEN 1 AND 100 AND unit = btrim(unit))",
            name="unit_valid",
        ),
        CheckConstraint(
            "(lifecycle = 'ACTIVE' AND archived_at IS NULL AND archived_by IS NULL) OR "
            "(lifecycle = 'ARCHIVED' AND archived_at IS NOT NULL AND archived_by IS NOT NULL)",
            name="archive_shape",
        ),
        ForeignKeyConstraint(
            (
                "workspace_id",
                "graph_id",
                "studio_release_id",
                "ontology_version_id",
            ),
            (
                "knowledge.studio_releases.workspace_id",
                "knowledge.studio_releases.graph_id",
                "knowledge.studio_releases.id",
                "knowledge.studio_releases.ontology_version_id",
            ),
            name="fk_property_profiles_studio_release",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id", "ontology_version_id"),
            (
                "knowledge.ontology_versions.workspace_id",
                "knowledge.ontology_versions.graph_id",
                "knowledge.ontology_versions.id",
            ),
            name="fk_property_profiles_ontology_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            (
                "workspace_id",
                "ontology_version_id",
                "ontology_element_id",
                "element_kind",
                "stable_property_id",
            ),
            (
                "knowledge.ontology_elements.workspace_id",
                "knowledge.ontology_elements.ontology_version_id",
                "knowledge.ontology_elements.id",
                "knowledge.ontology_elements.kind",
                "knowledge.ontology_elements.stable_element_id",
            ),
            name="fk_property_profiles_ontology_element",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "created_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            name="fk_property_profiles_created_by",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "updated_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            name="fk_property_profiles_updated_by",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "archived_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            name="fk_property_profiles_archived_by",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_property_profiles_graph_stable_property",
            "workspace_id",
            "graph_id",
            "stable_property_id",
        ),
        Index(
            "uq_property_profiles_one_active_per_element",
            "workspace_id",
            "ontology_element_id",
            unique=True,
            postgresql_where=text("lifecycle = 'ACTIVE'"),
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    graph_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    studio_release_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ontology_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ontology_element_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    element_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    stable_property_id: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(100))
    lifecycle: Mapped[str] = mapped_column(String(16), default="ACTIVE", nullable=False)
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    updated_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    archived_at: Mapped[datetime | None]
    archived_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))


class KnowledgePropertyProfileSynonymModel(Base, UuidPrimaryKeyMixin):
    """Normalized synonym child values for one Property profile."""

    __tablename__ = "property_profile_synonyms"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "profile_id",
            "id",
            name="uq_property_profile_synonyms_workspace_profile_id",
        ),
        UniqueConstraint(
            "workspace_id",
            "profile_id",
            "normalized_value",
            name="uq_property_profile_synonyms_workspace_profile_value",
        ),
        CheckConstraint(
            "char_length(value) BETWEEN 1 AND 200 AND value = btrim(value)",
            name="value_valid",
        ),
        CheckConstraint(
            "char_length(normalized_value) BETWEEN 1 AND 600 "
            "AND normalized_value = btrim(normalized_value)",
            name="normalized_value_valid",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "profile_id"),
            ("knowledge.property_profiles.workspace_id", "knowledge.property_profiles.id"),
            name="fk_property_profile_synonyms_profile",
            ondelete="CASCADE",
        ),
        Index(
            "ix_property_profile_synonyms_value",
            "workspace_id",
            "normalized_value",
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    profile_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    value: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(600), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)


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


class KnowledgeStudioIngestionBindingPinModel(Base, UuidPrimaryKeyMixin):
    """Immutable source, Mapping and deployment-profile pin for one worker job."""

    __tablename__ = "studio_ingestion_binding_pins"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "job_id", "ordinal"),
        UniqueConstraint("workspace_id", "job_id", "binding_version_id"),
        CheckConstraint("source_classification BETWEEN 0 AND 3", name="classification_range"),
        CheckConstraint(
            "ordinal >= 0 AND connection_profile_version >= 1 "
            "AND connection_profile_hash ~ '^[0-9a-f]{64}$' "
            "AND mapping_hash ~ '^[0-9a-f]{64}$' "
            "AND selection_hash ~ '^[0-9a-f]{64}$' "
            "AND pin_hash ~ '^[0-9a-f]{64}$'",
            name="evidence_shape",
        ),
        CheckConstraint(
            "jsonb_typeof(rules_document) = 'array' "
            "AND jsonb_array_length(rules_document) BETWEEN 1 AND 1000 "
            "AND octet_length(rules_document::text) <= 1048576",
            name="rules_document_array",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "job_id"),
            (
                "knowledge.studio_ingestion_jobs.workspace_id",
                "knowledge.studio_ingestion_jobs.id",
            ),
            ondelete="RESTRICT",
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
            ("workspace_id", "source_reference_id"),
            ("knowledge.source_references.workspace_id", "knowledge.source_references.id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "source_asset_id"),
            ("catalog.assets_projection.workspace_id", "catalog.assets_projection.id"),
            ondelete="RESTRICT",
        ),
        Index(
            "ix_studio_ingestion_binding_pins_job",
            "workspace_id",
            "job_id",
            "ordinal",
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    studio_release_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    binding_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_reference_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_asset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_version: Mapped[str] = mapped_column(String(255), nullable=False)
    projection_source_version: Mapped[str] = mapped_column(String(255), nullable=False)
    source_classification: Mapped[int] = mapped_column(Integer, nullable=False)
    selection_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    target_class_stable_id: Mapped[str] = mapped_column(String(128), nullable=False)
    target_class_canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mapping_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    connection_profile_id: Mapped[str] = mapped_column(String(255), nullable=False)
    connection_profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    connection_profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rules_document: Mapped[list[dict[str, object]]] = mapped_column(
        JSON_DOCUMENT,
        nullable=False,
    )
    pin_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)


class KnowledgeStudioIngestionAttemptModel(Base, UuidPrimaryKeyMixin):
    """Append-only lease attempt evidence owned by the dedicated Studio worker."""

    __tablename__ = "studio_ingestion_attempts"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "job_id", "id"),
        UniqueConstraint("workspace_id", "job_id", "attempt_no"),
        UniqueConstraint("workspace_id", "job_id", "lease_epoch"),
        CheckConstraint(
            "state IN ('RUNNING', 'SUCCESS', 'FAILED', 'STALE', 'CANCELLED', 'SUPERSEDED')",
            name="state_vocabulary",
        ),
        CheckConstraint(
            "attempt_no >= 1 AND lease_epoch >= 1 AND lease_token_hash ~ '^[0-9a-f]{64}$'",
            name="claim_shape",
        ),
        CheckConstraint(
            "stage IN ('SOURCE_READ', 'MAPPING', 'EMBEDDING', 'FINALIZING', 'COMPLETED')",
            name="stage_vocabulary",
        ),
        CheckConstraint(
            "source_read_receipt_hash IS NULL OR source_read_receipt_hash ~ '^[0-9a-f]{64}$'",
            name="source_read_receipt_hash",
        ),
        CheckConstraint(
            "materialization_hash IS NULL OR materialization_hash ~ '^[0-9a-f]{64}$'",
            name="materialization_hash",
        ),
        CheckConstraint(
            "result_evidence_hash IS NULL OR result_evidence_hash ~ '^[0-9a-f]{64}$'",
            name="result_evidence_hash",
        ),
        CheckConstraint(
            "source_access_deadline IS NULL OR "
            "(source_access_started_at IS NOT NULL "
            "AND source_access_deadline > source_access_started_at)",
            name="source_access_window",
        ),
        CheckConstraint(
            "(state = 'RUNNING' AND finished_at IS NULL) OR "
            "(state <> 'RUNNING' AND finished_at IS NOT NULL)",
            name="finished_shape",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "job_id"),
            (
                "knowledge.studio_ingestion_jobs.workspace_id",
                "knowledge.studio_ingestion_jobs.id",
            ),
            ondelete="RESTRICT",
        ),
        Index(
            "ix_studio_ingestion_attempts_job",
            "workspace_id",
            "job_id",
            "attempt_no",
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lease_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    worker_fingerprint: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(nullable=False)
    source_access_started_at: Mapped[datetime | None]
    source_access_deadline: Mapped[datetime | None]
    source_read_receipt_hash: Mapped[str | None] = mapped_column(String(64))
    materialization_hash: Mapped[str | None] = mapped_column(String(64))
    retryable: Mapped[bool | None] = mapped_column(Boolean)
    result_evidence_hash: Mapped[str | None] = mapped_column(String(64))
    failure_code: Mapped[str | None] = mapped_column(String(100))
    finished_at: Mapped[datetime | None]


class KnowledgeStudioIngestionEventModel(Base):
    """Append-only transition evidence for one Studio ingestion job."""

    __tablename__ = "studio_ingestion_events"
    __table_args__ = (
        UniqueConstraint("workspace_id", "job_id", "sequence"),
        UniqueConstraint(
            "workspace_id",
            "job_id",
            "state",
            "reason_code",
            "evidence_hash",
            name="uq_studio_ingestion_events_transition_evidence",
        ),
        CheckConstraint("sequence >= 1", name="sequence_positive"),
        CheckConstraint(
            "state IN ('PENDING', 'RUNNING', 'RETRY_WAIT', 'CANCEL_REQUESTED', "
            "'SUCCESS', 'FAILED', 'STALE', 'CANCELLED')",
            name="state_vocabulary",
        ),
        CheckConstraint(
            "actor_kind IN ('HUMAN', 'SERVICE') AND evidence_hash ~ '^[0-9a-f]{64}$'",
            name="evidence_shape",
        ),
        CheckConstraint(
            "jsonb_typeof(details_document) = 'object' "
            "AND octet_length(details_document::text) <= 8192",
            name="details_document_bounded",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "job_id"),
            (
                "knowledge.studio_ingestion_jobs.workspace_id",
                "knowledge.studio_ingestion_jobs.id",
            ),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "job_id", "attempt_id"),
            (
                "knowledge.studio_ingestion_attempts.workspace_id",
                "knowledge.studio_ingestion_attempts.job_id",
                "knowledge.studio_ingestion_attempts.id",
            ),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "actor_id"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
        ),
        Index(
            "ix_studio_ingestion_events_job",
            "workspace_id",
            "job_id",
            "sequence",
        ),
        {"schema": "knowledge"},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    details_document: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)


class KnowledgeStudioIngestionVectorReceiptModel(Base, UuidPrimaryKeyMixin):
    """Canonical vector receipt; Neo4j receives only a shadow projection."""

    __tablename__ = "studio_ingestion_vector_receipts"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint(
            "workspace_id",
            "job_id",
            "entity_id",
            "property_stable_id",
        ),
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$' "
            "AND embedding_binding_hash ~ '^[0-9a-f]{64}$' "
            "AND vector_hash ~ '^[0-9a-f]{64}$' "
            "AND dimension BETWEEN 1 AND 16384 "
            "AND jsonb_typeof(vector_document) = 'array' "
            "AND jsonb_array_length(vector_document) = dimension "
            "AND octet_length(vector_document::text) <= 4194304",
            name="vector_shape",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "job_id"),
            (
                "knowledge.studio_ingestion_jobs.workspace_id",
                "knowledge.studio_ingestion_jobs.id",
            ),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "job_id", "attempt_id"),
            (
                "knowledge.studio_ingestion_attempts.workspace_id",
                "knowledge.studio_ingestion_attempts.job_id",
                "knowledge.studio_ingestion_attempts.id",
            ),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "changeset_id", "job_id"),
            (
                "knowledge.changesets.workspace_id",
                "knowledge.changesets.id",
                "knowledge.changesets.studio_ingestion_job_id",
            ),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            (
                "workspace_id",
                "ontology_version_id",
                "property_ontology_element_id",
            ),
            (
                "knowledge.ontology_elements.workspace_id",
                "knowledge.ontology_elements.ontology_version_id",
                "knowledge.ontology_elements.id",
            ),
            ondelete="RESTRICT",
        ),
        Index(
            "ix_studio_ingestion_vector_receipts_job",
            "workspace_id",
            "job_id",
            "entity_id",
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    attempt_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    changeset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ontology_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    property_ontology_element_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
    )
    entity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    property_stable_id: Mapped[str] = mapped_column(String(128), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_binding_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    vector_document: Mapped[list[float]] = mapped_column(JSON_DOCUMENT, nullable=False)
    vector_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
