from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKeyConstraint, Index, String, Text, UniqueConstraint, Uuid
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
            ("workspace_id", "release_id"),
            ("knowledge.releases.workspace_id", "knowledge.releases.id"),
            ondelete="CASCADE",
        ),
        {"schema": "knowledge"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    release_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    adapter: Mapped[str] = mapped_column(String(100), nullable=False)
    target_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    node_count: Mapped[int | None]
    edge_count: Mapped[int | None]
