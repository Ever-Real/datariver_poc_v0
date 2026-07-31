from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
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

from datariver.domain.knowledge_pipeline import KNOWLEDGE_SOURCE_MEDIA_TYPES
from datariver.infrastructure.db.base import (
    JSON_DOCUMENT,
    Base,
    TimestampMixin,
    UuidPrimaryKeyMixin,
    VersionMixin,
)

_KNOWLEDGE_SOURCE_MEDIA_TYPE_CHECK = (
    "media_type IN ("
    + ", ".join(f"'{media_type}'" for media_type in sorted(KNOWLEDGE_SOURCE_MEDIA_TYPES))
    + ")"
)


class GraphModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "graphs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug"),
        UniqueConstraint("workspace_id", "id"),
        CheckConstraint(
            "status IN ('DRAFT', 'REVIEW', 'PUBLISHED', 'ARCHIVED')",
            name="status_vocabulary",
        ),
        CheckConstraint(
            "(status = 'ARCHIVED' AND archived_at IS NOT NULL AND archived_by IS NOT NULL) "
            "OR (status <> 'ARCHIVED' AND archived_at IS NULL AND archived_by IS NULL)",
            name="archive_shape",
        ),
        CheckConstraint(
            "classification BETWEEN 0 AND 3",
            name="classification_range",
        ),
        CheckConstraint(
            "(domain_ref_id IS NULL AND domain_ref_kind IS NULL "
            "AND domain_source_version IS NULL) OR "
            "(domain_ref_id IS NOT NULL AND domain_ref_kind = 'DOMAIN' "
            "AND domain_source_version IS NOT NULL)",
            name="domain_reference_shape",
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
            ("workspace_id", "created_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "updated_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "archived_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "id", "active_release_id"),
            (
                "knowledge.releases.workspace_id",
                "knowledge.releases.graph_id",
                "knowledge.releases.id",
            ),
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ("workspace_id", "id", "active_studio_release_id"),
            (
                "knowledge.studio_releases.workspace_id",
                "knowledge.studio_releases.graph_id",
                "knowledge.studio_releases.id",
            ),
            ondelete="RESTRICT",
            use_alter=True,
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    graph_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT", nullable=False)
    active_release_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    active_studio_release_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    classification: Mapped[int] = mapped_column(default=0, nullable=False)
    domain_ref_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    domain_ref_kind: Mapped[str | None] = mapped_column(String(16))
    domain_source_version: Mapped[str | None] = mapped_column(String(255))
    created_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    updated_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    archived_at: Mapped[datetime | None]
    archived_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))


class KnowledgeDeliveryPolicyModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "delivery_policies"
    __table_args__ = (
        UniqueConstraint("workspace_id", "graph_id"),
        UniqueConstraint("workspace_id", "id"),
        CheckConstraint(
            "priority BETWEEN 0 AND 1000",
            name="priority_range",
        ),
        CheckConstraint(
            "jsonb_typeof(match_any_terms) = 'array' "
            "AND jsonb_typeof(match_all_terms) = 'array' "
            "AND jsonb_typeof(excluded_terms) = 'array' "
            "AND jsonb_array_length(match_any_terms) <= 50 "
            "AND jsonb_array_length(match_all_terms) <= 50 "
            "AND jsonb_array_length(excluded_terms) <= 50",
            name="route_terms_arrays",
        ),
        CheckConstraint(
            "NOT chat_enabled OR "
            "jsonb_array_length(match_any_terms) + jsonb_array_length(match_all_terms) > 0",
            name="chat_route_has_positive_term",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id"),
            ("knowledge.graphs.workspace_id", "knowledge.graphs.id"),
            ondelete="CASCADE",
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
            "ix_delivery_policies_chat_match",
            "workspace_id",
            "chat_enabled",
            "priority",
            "graph_id",
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    graph_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    api_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    chat_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    match_any_terms: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    match_all_terms: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    excluded_terms: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    updated_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)


class OntologyVersionModel(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ontology_versions"
    __table_args__ = (
        UniqueConstraint("graph_id", "version"),
        UniqueConstraint("workspace_id", "graph_id", "id"),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id"),
            ("knowledge.graphs.workspace_id", "knowledge.graphs.id"),
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id", "base_ontology_version_id"),
            (
                "knowledge.ontology_versions.workspace_id",
                "knowledge.ontology_versions.graph_id",
                "knowledge.ontology_versions.id",
            ),
            ondelete="RESTRICT",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ("workspace_id", "created_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    graph_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_document: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_contract_version: Mapped[str | None] = mapped_column(String(50))
    base_ontology_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    created_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))


class ChangeSetModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "changesets"
    __table_args__ = (
        Index("ix_changesets_graph_state", "graph_id", "state", "created_at"),
        UniqueConstraint("workspace_id", "graph_id", "id"),
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint(
            "workspace_id",
            "studio_ingestion_job_id",
            name="uq_changesets_studio_ingestion_job",
        ),
        UniqueConstraint(
            "workspace_id",
            "id",
            "studio_ingestion_job_id",
            name="uq_changesets_studio_ingestion_result",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id"),
            ("knowledge.graphs.workspace_id", "knowledge.graphs.id"),
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id", "ontology_version_id"),
            (
                "knowledge.ontology_versions.workspace_id",
                "knowledge.ontology_versions.graph_id",
                "knowledge.ontology_versions.id",
            ),
        ),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id", "base_release_id"),
            (
                "knowledge.releases.workspace_id",
                "knowledge.releases.graph_id",
                "knowledge.releases.id",
            ),
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id", "published_release_id"),
            (
                "knowledge.releases.workspace_id",
                "knowledge.releases.graph_id",
                "knowledge.releases.id",
            ),
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ("workspace_id", "source_analysis_job_id"),
            (
                "knowledge.source_analysis_jobs.workspace_id",
                "knowledge.source_analysis_jobs.id",
            ),
            ondelete="RESTRICT",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id", "studio_ingestion_job_id"),
            (
                "knowledge.studio_ingestion_jobs.workspace_id",
                "knowledge.studio_ingestion_jobs.graph_id",
                "knowledge.studio_ingestion_jobs.id",
            ),
            ondelete="RESTRICT",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "NOT (source_analysis_job_id IS NOT NULL AND studio_ingestion_job_id IS NOT NULL)",
            name="one_automated_source",
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    graph_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    base_release_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    ontology_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    state: Mapped[str] = mapped_column(String(32), default="DRAFT", nullable=False)
    author_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_analysis_job_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    studio_ingestion_job_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    reviewed_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    reviewed_at: Mapped[datetime | None]
    review_reason: Mapped[str | None] = mapped_column(Text)
    published_release_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))


class ChangeOperationModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "change_operations"
    __table_args__ = (
        UniqueConstraint("changeset_id", "sequence"),
        ForeignKeyConstraint(
            ("workspace_id", "changeset_id"),
            ("knowledge.changesets.workspace_id", "knowledge.changesets.id"),
            ondelete="CASCADE",
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    changeset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    sequence: Mapped[int] = mapped_column(nullable=False)
    operation: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    stable_entity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    document: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    provenance: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DOCUMENT, nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)


class ValidationResultModel(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "validation_results"
    __table_args__ = (
        Index("ix_validation_results_changeset", "changeset_id", "severity"),
        ForeignKeyConstraint(
            ("workspace_id", "changeset_id"),
            ("knowledge.changesets.workspace_id", "knowledge.changesets.id"),
            ondelete="CASCADE",
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    changeset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    validator: Mapped[str] = mapped_column(String(100), nullable=False)
    validator_version: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    location: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)


class ReleaseModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "releases"
    __table_args__ = (
        UniqueConstraint("graph_id", "release_no"),
        UniqueConstraint("graph_id", "content_hash"),
        UniqueConstraint("workspace_id", "graph_id", "id"),
        UniqueConstraint("workspace_id", "id"),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id"),
            ("knowledge.graphs.workspace_id", "knowledge.graphs.id"),
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id", "ontology_version_id"),
            (
                "knowledge.ontology_versions.workspace_id",
                "knowledge.ontology_versions.graph_id",
                "knowledge.ontology_versions.id",
            ),
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    graph_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    release_no: Mapped[int] = mapped_column(nullable=False)
    ontology_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    node_count: Mapped[int] = mapped_column(nullable=False)
    edge_count: Mapped[int] = mapped_column(nullable=False)
    manifest_ref: Mapped[str | None] = mapped_column(Text)
    published_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    published_at: Mapped[datetime] = mapped_column(nullable=False)
    deprecated_at: Mapped[datetime | None]


class ReleaseNodeModel(Base):
    __tablename__ = "release_nodes"
    __table_args__ = (
        ForeignKeyConstraint(
            ("workspace_id", "release_id"),
            ("knowledge.releases.workspace_id", "knowledge.releases.id"),
            ondelete="CASCADE",
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    release_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    entity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    properties: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    classification: Mapped[int] = mapped_column(nullable=False)
    provenance: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DOCUMENT, nullable=False)


class ReleaseEdgeModel(Base):
    __tablename__ = "release_edges"
    __table_args__ = (
        Index("ix_release_edges_source", "release_id", "source_entity_id", "edge_type"),
        Index("ix_release_edges_target", "release_id", "target_entity_id", "edge_type"),
        ForeignKeyConstraint(
            ("workspace_id", "release_id"),
            ("knowledge.releases.workspace_id", "knowledge.releases.id"),
            ondelete="CASCADE",
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    release_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    edge_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    source_entity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    target_entity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    edge_type: Mapped[str] = mapped_column(String(100), nullable=False)
    properties: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    classification: Mapped[int] = mapped_column(nullable=False)
    provenance: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DOCUMENT, nullable=False)


class ProjectionDeploymentModel(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "projection_deployments"
    __table_args__ = (
        Index("ix_projection_deployments_release", "release_id", "adapter"),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id", "release_id"),
            (
                "knowledge.releases.workspace_id",
                "knowledge.releases.graph_id",
                "knowledge.releases.id",
            ),
            ondelete="CASCADE",
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    graph_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    release_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    job_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    adapter: Mapped[str] = mapped_column(String(100), nullable=False)
    target_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    verification_hash: Mapped[str | None] = mapped_column(String(64))
    node_count: Mapped[int | None]
    edge_count: Mapped[int | None]
    verified_at: Mapped[datetime | None]
    error_code: Mapped[str | None] = mapped_column(String(100))


class KnowledgeSourceSnapshotModel(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "source_snapshots"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "graph_id", "upload_id"),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id"),
            ("knowledge.graphs.workspace_id", "knowledge.graphs.id"),
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "upload_id"),
            ("integration.object_manifests.workspace_id", "integration.object_manifests.id"),
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            _KNOWLEDGE_SOURCE_MEDIA_TYPE_CHECK,
            name="media_type_vocabulary",
        ),
        CheckConstraint("byte_size > 0 AND byte_size <= 52428800", name="bounded_size"),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256"),
        CheckConstraint("state IN ('PENDING', 'ANALYZED', 'FAILED')", name="state_vocabulary"),
        Index("ix_source_snapshots_graph_created", "graph_id", "created_at"),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    graph_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    upload_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    storage_version: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    classification: Mapped[int] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)


class KnowledgeSourcePageModel(Base):
    __tablename__ = "source_pages"
    __table_args__ = (
        ForeignKeyConstraint(
            ("workspace_id", "source_snapshot_id"),
            ("knowledge.source_snapshots.workspace_id", "knowledge.source_snapshots.id"),
            ondelete="CASCADE",
        ),
        CheckConstraint("page_number > 0", name="page_number_positive"),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256"),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, nullable=False)
    source_snapshot_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    page_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)


class KnowledgePageEmbeddingModel(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "source_page_embeddings"
    __table_args__ = (
        UniqueConstraint("source_snapshot_id", "page_number", "provider", "model_identity"),
        ForeignKeyConstraint(
            ("workspace_id", "source_snapshot_id", "page_number"),
            (
                "knowledge.source_pages.workspace_id",
                "knowledge.source_pages.source_snapshot_id",
                "knowledge.source_pages.page_number",
            ),
            ondelete="CASCADE",
        ),
        CheckConstraint("dimension > 0 AND dimension <= 16384", name="bounded_dimension"),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256"),
        Index("ix_source_page_embeddings_source", "source_snapshot_id", "page_number"),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_snapshot_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_identity: Mapped[str] = mapped_column(String(200), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(JSON_DOCUMENT, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class KnowledgeSourceAnalysisJobModel(
    Base,
    UuidPrimaryKeyMixin,
    TimestampMixin,
    VersionMixin,
):
    __tablename__ = "source_analysis_jobs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "source_snapshot_id"),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id"),
            ("knowledge.graphs.workspace_id", "knowledge.graphs.id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "source_snapshot_id"),
            ("knowledge.source_snapshots.workspace_id", "knowledge.source_snapshots.id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id", "base_release_id"),
            (
                "knowledge.releases.workspace_id",
                "knowledge.releases.graph_id",
                "knowledge.releases.id",
            ),
            ondelete="RESTRICT",
            use_alter=True,
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
            ("workspace_id", "graph_id", "result_changeset_id"),
            (
                "knowledge.changesets.workspace_id",
                "knowledge.changesets.graph_id",
                "knowledge.changesets.id",
            ),
            ondelete="RESTRICT",
            use_alter=True,
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
        CheckConstraint(
            "state IN ('QUEUED', 'RUNNING', 'RETRY_WAIT', 'CANCEL_REQUESTED', "
            "'SUCCEEDED', 'FAILED', 'STALE', 'CANCELLED')",
            name="state_vocabulary",
        ),
        CheckConstraint(
            "stage IN ('QUEUED', 'SOURCE_READ', 'PARSED', 'EMBEDDED', 'EXTRACTED', "
            "'FINALIZING', 'COMPLETED')",
            name="stage_vocabulary",
        ),
        CheckConstraint(
            "base_kind IN ('EMPTY', 'RELEASE') AND "
            "((base_kind = 'EMPTY' AND base_release_id IS NULL AND base_release_hash IS NULL) "
            "OR (base_kind = 'RELEASE' AND base_release_id IS NOT NULL "
            "AND base_release_hash ~ '^[0-9a-f]{64}$'))",
            name="base_binding_shape",
        ),
        CheckConstraint(
            "source_content_sha256 ~ '^[0-9a-f]{64}$' AND "
            "ontology_checksum ~ '^[0-9a-f]{64}$' AND "
            "parser_config_hash ~ '^[0-9a-f]{64}$' AND "
            "embedding_binding_hash ~ '^[0-9a-f]{64}$' AND "
            "extraction_binding_hash ~ '^[0-9a-f]{64}$' AND "
            "pin_hash ~ '^[0-9a-f]{64}$' AND "
            "request_hash ~ '^[0-9a-f]{64}$' AND "
            "requester_authorization_hash ~ '^[0-9a-f]{64}$'",
            name="evidence_hashes",
        ),
        CheckConstraint("source_classification BETWEEN 0 AND 1", name="inference_classification"),
        CheckConstraint(
            "graph_version > 0 AND attempt_count >= 0 AND maximum_attempts > 0 "
            "AND attempt_count <= maximum_attempts AND lease_epoch >= 0",
            name="counters",
        ),
        CheckConstraint(
            "lease_token_hash IS NULL OR lease_token_hash ~ '^[0-9a-f]{64}$'",
            name="lease_token_hash",
        ),
        CheckConstraint(
            "(state IN ('RUNNING', 'CANCEL_REQUESTED') "
            "AND lease_token_hash IS NOT NULL AND lease_owner_fingerprint IS NOT NULL "
            "AND lease_started_at IS NOT NULL AND lease_expires_at IS NOT NULL) OR "
            "(state NOT IN ('RUNNING', 'CANCEL_REQUESTED') "
            "AND lease_token_hash IS NULL AND lease_owner_fingerprint IS NULL "
            "AND lease_started_at IS NULL AND lease_expires_at IS NULL)",
            name="lease_shape",
        ),
        CheckConstraint(
            "((state = 'SUCCEEDED') AND result_changeset_id IS NOT NULL "
            "AND result_evidence_hash ~ '^[0-9a-f]{64}$' AND completed_at IS NOT NULL "
            "AND last_failure_code IS NULL) OR "
            "((state <> 'SUCCEEDED') AND result_changeset_id IS NULL "
            "AND result_evidence_hash IS NULL) ",
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
            "(state IN ('QUEUED', 'RETRY_WAIT') AND stage = 'QUEUED') OR "
            "(state IN ('RUNNING', 'CANCEL_REQUESTED') AND "
            "stage IN ('SOURCE_READ', 'PARSED', 'EMBEDDED', 'EXTRACTED', 'FINALIZING')) OR "
            "(state IN ('SUCCEEDED', 'FAILED', 'STALE', 'CANCELLED') "
            "AND stage = 'COMPLETED')",
            name="execution_stage_shape",
        ),
        Index(
            "ix_source_analysis_jobs_claim",
            "workspace_id",
            "next_attempt_at",
            "created_at",
            "id",
            postgresql_where=text("state IN ('QUEUED', 'RETRY_WAIT')"),
        ),
        Index(
            "ix_source_analysis_jobs_expired",
            "workspace_id",
            "lease_expires_at",
            "id",
            postgresql_where=text("state IN ('RUNNING', 'CANCEL_REQUESTED')"),
        ),
        Index(
            "ix_source_analysis_jobs_graph_created",
            "workspace_id",
            "graph_id",
            "created_at",
            "id",
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    graph_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_snapshot_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    requested_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requester_authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_storage_version: Mapped[str] = mapped_column(String(255), nullable=False)
    source_content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_classification: Mapped[int] = mapped_column(nullable=False)
    graph_version: Mapped[int] = mapped_column(nullable=False)
    base_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    base_release_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    base_release_hash: Mapped[str | None] = mapped_column(String(64))
    ontology_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ontology_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_binding: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    embedding_binding_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    extraction_binding: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    extraction_binding_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    pin_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prepared_at: Mapped[datetime] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    progress: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(nullable=False)
    attempt_count: Mapped[int] = mapped_column(nullable=False)
    maximum_attempts: Mapped[int] = mapped_column(nullable=False)
    lease_epoch: Mapped[int] = mapped_column(nullable=False)
    lease_token_hash: Mapped[str | None] = mapped_column(String(64))
    lease_owner_fingerprint: Mapped[str | None] = mapped_column(String(255))
    lease_started_at: Mapped[datetime | None]
    lease_expires_at: Mapped[datetime | None]
    cancel_requested_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    cancel_requested_at: Mapped[datetime | None]
    cancel_reason: Mapped[str | None] = mapped_column(String(1000))
    result_changeset_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    result_evidence_hash: Mapped[str | None] = mapped_column(String(64))
    last_failure_code: Mapped[str | None] = mapped_column(String(100))
    completed_at: Mapped[datetime | None]


class KnowledgeSourceAnalysisAttemptModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "source_analysis_attempts"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "job_id", "attempt_no"),
        UniqueConstraint("workspace_id", "job_id", "lease_epoch"),
        ForeignKeyConstraint(
            ("workspace_id", "job_id"),
            ("knowledge.source_analysis_jobs.workspace_id", "knowledge.source_analysis_jobs.id"),
            ondelete="RESTRICT",
        ),
        CheckConstraint("attempt_no > 0 AND lease_epoch > 0", name="counters"),
        CheckConstraint(
            "state IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'STALE', 'CANCELLED', 'SUPERSEDED')",
            name="state_vocabulary",
        ),
        CheckConstraint(
            "stage IN ('SOURCE_READ', 'PARSED', 'EMBEDDED', 'EXTRACTED', "
            "'FINALIZING', 'COMPLETED')",
            name="stage_vocabulary",
        ),
        CheckConstraint("lease_token_hash ~ '^[0-9a-f]{64}$'", name="lease_token_hash"),
        CheckConstraint(
            "input_hash ~ '^[0-9a-f]{64}$' AND "
            "(output_hash IS NULL OR output_hash ~ '^[0-9a-f]{64}$') AND "
            "(external_response_hash IS NULL "
            "OR external_response_hash ~ '^[0-9a-f]{64}$')",
            name="evidence_hashes",
        ),
        CheckConstraint(
            "(state = 'RUNNING' AND finished_at IS NULL) "
            "OR (state <> 'RUNNING' AND finished_at IS NOT NULL)",
            name="terminal_shape",
        ),
        Index("ix_source_analysis_attempts_job", "workspace_id", "job_id", "attempt_no"),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    attempt_no: Mapped[int] = mapped_column(nullable=False)
    lease_epoch: Mapped[int] = mapped_column(nullable=False)
    lease_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    worker_fingerprint: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_hash: Mapped[str | None] = mapped_column(String(64))
    external_response_hash: Mapped[str | None] = mapped_column(String(64))
    retryable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    finished_at: Mapped[datetime | None]


class KnowledgeSourceAnalysisEventModel(Base):
    __tablename__ = "source_analysis_events"
    __table_args__ = (
        UniqueConstraint("workspace_id", "job_id", "sequence"),
        ForeignKeyConstraint(
            ("workspace_id", "job_id"),
            ("knowledge.source_analysis_jobs.workspace_id", "knowledge.source_analysis_jobs.id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "attempt_id"),
            (
                "knowledge.source_analysis_attempts.workspace_id",
                "knowledge.source_analysis_attempts.id",
            ),
            ondelete="RESTRICT",
        ),
        CheckConstraint("sequence > 0", name="sequence_positive"),
        CheckConstraint("evidence_hash ~ '^[0-9a-f]{64}$'", name="evidence_hash"),
        Index("ix_source_analysis_events_job", "workspace_id", "job_id", "sequence"),
        Index(
            "ux_source_analysis_events_transition_evidence",
            "workspace_id",
            "job_id",
            "event_type",
            "occurred_at",
            unique=True,
        ),
        {"schema": "knowledge"},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    sequence: Mapped[int] = mapped_column(nullable=False)
    attempt_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(100))
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)


class KnowledgeExtractionRunModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "extraction_runs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id"),
            ("knowledge.graphs.workspace_id", "knowledge.graphs.id"),
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "source_snapshot_id"),
            ("knowledge.source_snapshots.workspace_id", "knowledge.source_snapshots.id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "proposed_changeset_id"),
            ("knowledge.changesets.workspace_id", "knowledge.changesets.id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "source_analysis_job_id"),
            ("knowledge.source_analysis_jobs.workspace_id", "knowledge.source_analysis_jobs.id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "source_analysis_attempt_id"),
            (
                "knowledge.source_analysis_attempts.workspace_id",
                "knowledge.source_analysis_attempts.id",
            ),
            ondelete="RESTRICT",
        ),
        CheckConstraint("state IN ('SUCCEEDED', 'FAILED')", name="state_vocabulary"),
        CheckConstraint(
            "contract_version IN ('LEGACY_SYNC_V1', 'DURABLE_SOURCE_V1') AND "
            "((contract_version = 'LEGACY_SYNC_V1' AND source_analysis_job_id IS NULL "
            "AND source_analysis_attempt_id IS NULL) OR "
            "(contract_version = 'DURABLE_SOURCE_V1' AND source_analysis_job_id IS NOT NULL "
            "AND source_analysis_attempt_id IS NOT NULL))",
            name="contract_shape",
        ),
        CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="input_hash"),
        CheckConstraint("output_hash ~ '^[0-9a-f]{64}$'", name="output_hash"),
        Index("ix_extraction_runs_graph_created", "graph_id", "created_at"),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    graph_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_snapshot_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    proposed_changeset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_analysis_job_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    source_analysis_attempt_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    contract_version: Mapped[str] = mapped_column(
        String(32),
        default="LEGACY_SYNC_V1",
        server_default="LEGACY_SYNC_V1",
        nullable=False,
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    parser_config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_binding: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    extraction_binding: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100))


class KnowledgeGraphRagAuditModel(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "graphrag_audits"
    __table_args__ = (
        UniqueConstraint("workspace_id", "request_id"),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id", "release_id"),
            (
                "knowledge.releases.workspace_id",
                "knowledge.releases.graph_id",
                "knowledge.releases.id",
            ),
            ondelete="RESTRICT",
        ),
        CheckConstraint("question_sha256 ~ '^[0-9a-f]{64}$'", name="question_sha256"),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0", name="input_tokens_nonnegative"
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0", name="output_tokens_nonnegative"
        ),
        CheckConstraint(
            "(configuration_source IS NULL AND configuration_version IS NULL "
            "AND configuration_hash IS NULL) OR "
            "(configuration_source = 'SYSTEM_CONFIGURATION' "
            "AND configuration_version > 0 "
            "AND configuration_hash ~ '^[0-9a-f]{64}$') OR "
            "(configuration_source = 'DEPLOYMENT' "
            "AND configuration_version IS NULL "
            "AND configuration_hash ~ '^[0-9a-f]{64}$')",
            name="configuration_evidence_shape",
        ),
        Index("ix_graphrag_audits_release_created", "release_id", "created_at"),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    graph_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    release_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    request_id: Mapped[str] = mapped_column(String(100), nullable=False)
    question_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, nullable=False)
    cited_evidence_ids: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_identity: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(200), nullable=False)
    tool_schema_version: Mapped[str] = mapped_column(String(200), nullable=False)
    configuration_source: Mapped[str | None] = mapped_column(String(32))
    configuration_version: Mapped[int | None] = mapped_column(Integer)
    configuration_hash: Mapped[str | None] = mapped_column(String(64))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
