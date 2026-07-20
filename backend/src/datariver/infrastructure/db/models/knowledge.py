from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from datariver.infrastructure.db.base import (
    JSON_DOCUMENT,
    Base,
    TimestampMixin,
    UuidPrimaryKeyMixin,
    VersionMixin,
)


class GraphModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "graphs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug"),
        UniqueConstraint("workspace_id", "id"),
        ForeignKeyConstraint(
            ("workspace_id", "id", "active_release_id"),
            (
                "knowledge.releases.workspace_id",
                "knowledge.releases.graph_id",
                "knowledge.releases.id",
            ),
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
    classification: Mapped[int] = mapped_column(default=0, nullable=False)


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
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    graph_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_document: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)


class ChangeSetModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "changesets"
    __table_args__ = (
        Index("ix_changesets_graph_state", "graph_id", "state", "created_at"),
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
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    graph_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    base_release_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    ontology_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    state: Mapped[str] = mapped_column(String(32), default="DRAFT", nullable=False)
    author_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
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
        CheckConstraint("media_type = 'application/pdf'", name="pdf_media_type"),
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
        CheckConstraint("state IN ('SUCCEEDED', 'FAILED')", name="state_vocabulary"),
        CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="input_hash"),
        CheckConstraint("output_hash ~ '^[0-9a-f]{64}$'", name="output_hash"),
        Index("ix_extraction_runs_graph_created", "graph_id", "created_at"),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    graph_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_snapshot_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    proposed_changeset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
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
