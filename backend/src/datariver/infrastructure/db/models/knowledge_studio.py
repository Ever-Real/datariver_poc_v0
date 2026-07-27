from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from datariver.infrastructure.db.base import (
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
