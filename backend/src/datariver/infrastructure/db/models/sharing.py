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


class ApiProductModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "api_products"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug"),
        UniqueConstraint("workspace_id", "graph_id", "id"),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id"),
            ("knowledge.graphs.workspace_id", "knowledge.graphs.id"),
        ),
        ForeignKeyConstraint(
            ("workspace_id", "id", "current_version_id"),
            (
                "sharing.api_product_versions.workspace_id",
                "sharing.api_product_versions.product_id",
                "sharing.api_product_versions.id",
            ),
            use_alter=True,
        ),
        Index("ix_api_products_workspace_state", "workspace_id", "state", "updated_at"),
        {"schema": "sharing"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    graph_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    classification: Mapped[int] = mapped_column(nullable=False)
    owner_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    current_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))


class ApiProductVersionModel(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "api_product_versions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "product_id", "id"),
        UniqueConstraint("workspace_id", "product_id", "version_no"),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id", "product_id"),
            (
                "sharing.api_products.workspace_id",
                "sharing.api_products.graph_id",
                "sharing.api_products.id",
            ),
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id", "release_id"),
            (
                "knowledge.releases.workspace_id",
                "knowledge.releases.graph_id",
                "knowledge.releases.id",
            ),
        ),
        Index("ix_api_product_versions_product_state", "product_id", "state", "version_no"),
        {"schema": "sharing"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    product_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    graph_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    release_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version_no: Mapped[int] = mapped_column(nullable=False)
    surface: Mapped[str] = mapped_column(String(32), nullable=False)
    contract_document: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    maximum_hops: Mapped[int] = mapped_column(nullable=False)
    maximum_nodes: Mapped[int] = mapped_column(nullable=False)
    timeout_ms: Mapped[int] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    published_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    published_at: Mapped[datetime | None]


class ConsumerGrantModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "consumer_grants"
    __table_args__ = (
        UniqueConstraint("workspace_id", "product_version_id", "consumer_client_id"),
        UniqueConstraint("workspace_id", "id"),
        ForeignKeyConstraint(
            ("workspace_id", "product_id", "product_version_id"),
            (
                "sharing.api_product_versions.workspace_id",
                "sharing.api_product_versions.product_id",
                "sharing.api_product_versions.id",
            ),
            ondelete="CASCADE",
        ),
        Index("ix_consumer_grants_client_state", "workspace_id", "consumer_client_id", "state"),
        {"schema": "sharing"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    product_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    product_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    consumer_client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, nullable=False)
    maximum_classification: Mapped[int] = mapped_column(nullable=False)
    requests_per_minute: Mapped[int] = mapped_column(nullable=False)
    monthly_quota: Mapped[int] = mapped_column(nullable=False)
    valid_from: Mapped[datetime] = mapped_column(nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    revoked_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    revoked_at: Mapped[datetime | None]


class ApiInvocationModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "api_invocations"
    __table_args__ = (
        UniqueConstraint("workspace_id", "grant_id", "invocation_key"),
        ForeignKeyConstraint(
            ("workspace_id", "grant_id"),
            ("sharing.consumer_grants.workspace_id", "sharing.consumer_grants.id"),
            ondelete="CASCADE",
        ),
        Index("ix_api_invocations_grant_time", "grant_id", "occurred_at"),
        {"schema": "sharing"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    grant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    invocation_key: Mapped[str] = mapped_column(String(200), nullable=False)
    requested_scope: Mapped[str] = mapped_column(String(100), nullable=False)
    request_id: Mapped[str] = mapped_column(String(100), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)
    units: Mapped[int] = mapped_column(default=1, nullable=False)
