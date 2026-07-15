from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, ForeignKeyConstraint, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from datariver.infrastructure.db.base import (
    JSON_DOCUMENT,
    Base,
    TimestampMixin,
    UuidPrimaryKeyMixin,
    VersionMixin,
)


class JobModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_workspace_state", "workspace_id", "state", "created_at"),
        UniqueConstraint("job_type", "causation_id"),
        UniqueConstraint("workspace_id", "id"),
        {"schema": "integration"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    job_type: Mapped[str] = mapped_column(String(100), nullable=False)
    causation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    progress: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)
    result_ref: Mapped[str | None] = mapped_column(Text)
    lease_until: Mapped[datetime | None]
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(100))


class JobAttemptModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "job_attempts"
    __table_args__ = (
        UniqueConstraint("job_id", "attempt_no"),
        ForeignKeyConstraint(
            ("workspace_id", "job_id"),
            ("integration.jobs.workspace_id", "integration.jobs.id"),
            ondelete="CASCADE",
        ),
        {"schema": "integration"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    attempt_no: Mapped[int] = mapped_column(nullable=False)
    worker_id: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    error_class: Mapped[str | None] = mapped_column(String(100))
    external_response_hash: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    finished_at: Mapped[datetime | None]


class OutboxEventModel(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index("ix_outbox_unpublished", "published_at", "lease_until", "created_at"),
        {"schema": "integration"},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(200), nullable=False)
    schema_version: Mapped[int] = mapped_column(default=1, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    published_at: Mapped[datetime | None]
    dead_lettered_at: Mapped[datetime | None]
    lease_until: Mapped[datetime | None]
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(100))


class InboxMessageModel(Base):
    __tablename__ = "inbox_messages"
    __table_args__ = ({"schema": "integration"},)

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    consumer: Mapped[str] = mapped_column(String(100), primary_key=True)
    event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(nullable=False)
    completed_at: Mapped[datetime | None]
    result_hash: Mapped[str | None] = mapped_column(String(64))


class IdempotencyKeyModel(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = ({"schema": "integration"},)

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    operation: Mapped[str] = mapped_column(String(100), primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)


class ObjectManifestModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "object_manifests"
    __table_args__ = (
        UniqueConstraint("bucket", "object_key"),
        Index("ix_object_manifests_workspace_state", "workspace_id", "state"),
        {"schema": "integration"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(String(500), nullable=False)
    multipart_upload_id: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    actual_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    actual_mime: Mapped[str | None] = mapped_column(String(255))
    actual_sha256: Mapped[str | None] = mapped_column(String(64))
    processing_lease_until: Mapped[datetime | None]
    processing_attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    validation_attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    validation_summary: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    completion_parts: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    classification: Mapped[int] = mapped_column(default=0, nullable=False)
    owner_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    retention_until: Mapped[datetime | None]
    expires_at: Mapped[datetime | None]


class SeedRunModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "seed_runs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "namespace", "pack_version"),
        {"schema": "integration"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    namespace: Mapped[str] = mapped_column(String(200), nullable=False)
    pack_version: Mapped[str] = mapped_column(String(100), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    row_counts: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    applied_at: Mapped[datetime] = mapped_column(nullable=False)
    removed_at: Mapped[datetime | None]
