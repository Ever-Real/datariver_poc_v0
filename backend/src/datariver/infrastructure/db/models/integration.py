from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
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
        UniqueConstraint("workspace_id", "id"),
        Index("ix_object_manifests_workspace_state", "workspace_id", "state"),
        CheckConstraint(
            "content_profile IN ('FORMAT_ONLY_V1', 'DATASET_DESCRIPTION_CSV_V1')",
            name="content_profile_allowlist",
        ),
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
    content_profile: Mapped[str] = mapped_column(
        String(100),
        default="FORMAT_ONLY_V1",
        server_default="FORMAT_ONLY_V1",
        nullable=False,
    )
    classification: Mapped[int] = mapped_column(default=0, nullable=False)
    owner_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    retention_until: Mapped[datetime | None]
    expires_at: Mapped[datetime | None]


class UploadPreparationJobModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "upload_preparation_jobs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint(
            "workspace_id",
            "id",
            "upload_id",
            "source_manifest_version",
            "source_sha256",
            "content_profile",
            "configuration_hash",
            name="uq_upload_preparation_job_source_evidence",
        ),
        UniqueConstraint(
            "workspace_id",
            "upload_id",
            "source_manifest_version",
            "content_profile",
            "configuration_hash",
            name="uq_upload_preparation_job_source_configuration",
        ),
        Index(
            "ix_upload_preparation_jobs_claim",
            "state",
            "lease_until",
            "created_at",
        ),
        CheckConstraint(
            "content_profile = 'DATASET_DESCRIPTION_CSV_V1'",
            name="typed_profile_allowlist",
        ),
        CheckConstraint(
            "state IN ('QUEUED', 'PREPARING', 'READY', 'FAILED', 'CANCELLED', 'STALE')",
            name="state_allowlist",
        ),
        CheckConstraint(
            "source_manifest_version > 0",
            name="source_manifest_version_positive",
        ),
        CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$'", name="source_sha256_valid"),
        CheckConstraint(
            "configuration_hash ~ '^[0-9a-f]{64}$'",
            name="configuration_hash_valid",
        ),
        CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
        CheckConstraint("rows_processed >= 0", name="rows_processed_nonnegative"),
        CheckConstraint(
            "total_rows IS NULL OR total_rows >= rows_processed",
            name="total_rows_bounds",
        ),
        CheckConstraint(
            "(state = 'PREPARING' AND lease_token IS NOT NULL AND lease_until IS NOT NULL) "
            "OR (state <> 'PREPARING' AND lease_token IS NULL AND lease_until IS NULL)",
            name="lease_shape",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "upload_id"),
            ("integration.object_manifests.workspace_id", "integration.object_manifests.id"),
            name="fk_upload_prep_jobs_workspace_upload",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "requested_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            name="fk_upload_prep_jobs_workspace_requester",
            ondelete="RESTRICT",
        ),
        {"schema": "integration"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    upload_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    requested_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    content_profile: Mapped[str] = mapped_column(String(100), nullable=False)
    source_manifest_version: Mapped[int] = mapped_column(nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    lease_token: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    rows_processed: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_rows: Mapped[int | None] = mapped_column(BigInteger)
    last_error_code: Mapped[str | None] = mapped_column(String(100))


class UploadPreparationReceiptModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "upload_preparation_receipts"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "preparation_job_id"),
        CheckConstraint("manifest_version > 0", name="manifest_version_positive"),
        CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$'", name="source_sha256_valid"),
        CheckConstraint("accepted_sha256 ~ '^[0-9a-f]{64}$'", name="accepted_sha256_valid"),
        CheckConstraint(
            "accepted_sha256 = source_sha256",
            name="accepted_source_sha256_equal",
        ),
        CheckConstraint(
            "object_locator_hash ~ '^[0-9a-f]{64}$'",
            name="object_locator_hash_valid",
        ),
        CheckConstraint(
            "configuration_hash ~ '^[0-9a-f]{64}$'",
            name="configuration_hash_valid",
        ),
        CheckConstraint(
            "candidate_root_hash ~ '^[0-9a-f]{64}$'",
            name="candidate_root_hash_valid",
        ),
        CheckConstraint("receipt_hash ~ '^[0-9a-f]{64}$'", name="receipt_hash_valid"),
        CheckConstraint(
            "item_count >= 0 AND rejected_count >= 0",
            name="row_counts_nonnegative",
        ),
        CheckConstraint(
            "content_profile = 'DATASET_DESCRIPTION_CSV_V1'",
            name="typed_profile_allowlist",
        ),
        ForeignKeyConstraint(
            (
                "workspace_id",
                "preparation_job_id",
                "upload_id",
                "manifest_version",
                "source_sha256",
                "content_profile",
                "configuration_hash",
            ),
            (
                "integration.upload_preparation_jobs.workspace_id",
                "integration.upload_preparation_jobs.id",
                "integration.upload_preparation_jobs.upload_id",
                "integration.upload_preparation_jobs.source_manifest_version",
                "integration.upload_preparation_jobs.source_sha256",
                "integration.upload_preparation_jobs.content_profile",
                "integration.upload_preparation_jobs.configuration_hash",
            ),
            name="fk_upload_prep_receipts_source_evidence",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "upload_id"),
            ("integration.object_manifests.workspace_id", "integration.object_manifests.id"),
            name="fk_upload_prep_receipts_workspace_upload",
            ondelete="RESTRICT",
        ),
        {"schema": "integration"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    preparation_job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    upload_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    manifest_version: Mapped[int] = mapped_column(nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    object_locator_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_etag: Mapped[str | None] = mapped_column(String(512))
    accepted_version_id: Mapped[str | None] = mapped_column(String(1024))
    content_profile: Mapped[str] = mapped_column(String(100), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(100), nullable=False)
    scanner_version: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    item_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rejected_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    candidate_root_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UploadRegistrationCandidateModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "upload_registration_candidates"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint(
            "workspace_id",
            "id",
            "candidate_hash",
            name="uq_upload_registration_candidate_content",
        ),
        UniqueConstraint("workspace_id", "receipt_id", "ordinal"),
        UniqueConstraint("workspace_id", "receipt_id", "target_asset_id"),
        CheckConstraint("ordinal > 0", name="ordinal_positive"),
        CheckConstraint(
            "candidate_kind = 'DATASET_DESCRIPTION_UPDATE'",
            name="candidate_kind_allowlist",
        ),
        CheckConstraint(
            "char_length(proposed_description) <= 10000",
            name="description_length",
        ),
        CheckConstraint("candidate_hash ~ '^[0-9a-f]{64}$'", name="candidate_hash_valid"),
        ForeignKeyConstraint(
            ("workspace_id", "receipt_id"),
            (
                "integration.upload_preparation_receipts.workspace_id",
                "integration.upload_preparation_receipts.id",
            ),
            name="fk_upload_reg_candidates_workspace_receipt",
            ondelete="RESTRICT",
        ),
        {"schema": "integration"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    receipt_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_asset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    candidate_kind: Mapped[str] = mapped_column(String(100), nullable=False)
    proposed_description: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


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
