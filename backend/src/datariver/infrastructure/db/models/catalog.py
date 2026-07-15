from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Computed, Index, String, Text, UniqueConstraint, Uuid, text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from datariver.infrastructure.db.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class AssetProjectionModel(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "assets_projection"
    __table_args__ = (
        UniqueConstraint("workspace_id", "urn_hash"),
        Index(
            "ix_assets_projection_scope",
            "workspace_id",
            "classification",
            "system_id",
            "domain_id",
        ),
        Index(
            "ix_assets_projection_active_scope_order",
            "workspace_id",
            "classification",
            "name",
            "id",
            postgresql_where=text("deleted_at IS NULL AND lifecycle = 'ACTIVE'"),
        ),
        Index(
            "ix_assets_projection_search_fts_active",
            "search_vector",
            postgresql_using="gin",
            postgresql_where=text("deleted_at IS NULL AND lifecycle = 'ACTIVE'"),
        ),
        Index(
            "ix_assets_projection_name_trgm_active",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
            postgresql_where=text("deleted_at IS NULL AND lifecycle = 'ACTIVE'"),
        ),
        Index(
            "ix_assets_projection_workspace_watermark",
            "workspace_id",
            "updated_at",
        ),
        {"schema": "catalog"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    external_urn: Mapped[str] = mapped_column(Text, nullable=False)
    urn_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('simple'::regconfig, "
            "coalesce(name, '') || ' ' || coalesce(description, ''))",
            persisted=True,
        ),
        nullable=False,
    )
    platform: Mapped[str | None] = mapped_column(String(100))
    domain_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    system_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    owner_department_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    classification: Mapped[int] = mapped_column(default=0, nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(50), default="ACTIVE", nullable=False)
    source_version: Mapped[str] = mapped_column(String(255), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(nullable=False)
    deleted_at: Mapped[datetime | None]
    last_seen_sync_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    projection_source: Mapped[str] = mapped_column(String(32), default="DATAHUB", nullable=False)


class CatalogSyncRunModel(Base):
    __tablename__ = "sync_runs"
    __table_args__ = (
        Index("ix_catalog_sync_runs_workspace_state", "workspace_id", "state", "started_at"),
        {"schema": "catalog"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    sync_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    next_offset: Mapped[int] = mapped_column(nullable=False)
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(nullable=False)
    completed_at: Mapped[datetime | None]
