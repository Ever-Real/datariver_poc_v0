from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import (
    text as sa_text,
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
        CheckConstraint(
            "lease_token_hash IS NULL OR lease_token_hash ~ '^[0-9a-f]{64}$'",
            name="lease_token_hash_valid",
        ),
        CheckConstraint(
            "attempt_cycle > 0 AND cycle_attempts >= 0 AND attempts >= cycle_attempts",
            name="attempt_counters_valid",
        ),
        CheckConstraint(
            "job_type <> 'DATAHUB_CHANGE_APPLY' OR "
            "((state = 'RUNNING' AND lease_token_hash IS NOT NULL "
            "AND lease_owner_id IS NOT NULL AND lease_until IS NOT NULL) "
            "OR (state <> 'RUNNING' AND lease_token_hash IS NULL "
            "AND lease_owner_id IS NULL))",
            name="governance_apply_lease_shape",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "lease_owner_id"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            name="fk_jobs_workspace_lease_owner",
            ondelete="RESTRICT",
        ),
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
    attempt_cycle: Mapped[int] = mapped_column(default=1, server_default="1", nullable=False)
    cycle_attempts: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    lease_token_hash: Mapped[str | None] = mapped_column(String(64))
    lease_owner_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
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
        Index(
            "ux_outbox_source_analysis_transition",
            "workspace_id",
            "aggregate_id",
            "event_type",
            sa_text("(payload ->> 'version')"),
            unique=True,
            postgresql_where=sa_text("aggregate_type = 'knowledge_source_analysis_job'"),
        ),
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


class RegistrationWorkerCallReceiptModel(Base):
    __tablename__ = "registration_worker_call_receipts"
    __table_args__ = (
        CheckConstraint(
            "operation IN ("
            "'registration.manual-metadata.apply-run.v1', "
            "'registration.bulk-preparation.execute-run.v1'"
            ")",
            name="operation_allowlist",
        ),
        CheckConstraint(
            "state IN ('RUNNING', 'COMPLETED')",
            name="state_allowlist",
        ),
        CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$' AND key_hash ~ '^[0-9a-f]{64}$'",
            name="identity_hashes_valid",
        ),
        CheckConstraint(
            "claim_token_hash IS NULL OR claim_token_hash ~ '^[0-9a-f]{64}$'",
            name="claim_token_hash_valid",
        ),
        CheckConstraint(
            "(state = 'RUNNING' AND processed IS NULL AND result IS NULL "
            "AND work_kind IN ('MANUAL', 'BULK') AND work_id IS NOT NULL "
            "AND claim_attempt IS NOT NULL AND claim_attempt > 0 "
            "AND claim_token_hash IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (state = 'COMPLETED' AND processed IS NOT NULL AND result IS NOT NULL "
            "AND claim_token_hash IS NULL AND lease_expires_at IS NULL)",
            name="state_shape",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "worker_subject_id"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            name="fk_registration_worker_call_receipts_subject",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_registration_worker_call_receipts_running_lease",
            "lease_expires_at",
            postgresql_where=sa_text("state = 'RUNNING'"),
        ),
        {"schema": "integration"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    operation: Mapped[str] = mapped_column(String(100), primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    worker_subject_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    work_kind: Mapped[str | None] = mapped_column(String(16))
    work_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    claim_attempt: Mapped[int | None]
    claim_token_hash: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed: Mapped[bool | None] = mapped_column(Boolean)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON_DOCUMENT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ObjectManifestModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "object_manifests"
    __table_args__ = (
        UniqueConstraint("bucket", "object_key"),
        UniqueConstraint("workspace_id", "id"),
        Index("ix_object_manifests_workspace_state", "workspace_id", "state"),
        CheckConstraint(
            "content_profile IN ('FORMAT_ONLY_V1', "
            "'CATALOG_METADATA_ROWS_CSV_V1', 'CATALOG_METADATA_ROWS_XLSX_V1')",
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
            "next_attempt_at",
            "lease_until",
            "created_at",
        ),
        CheckConstraint(
            "content_profile IN ('CATALOG_METADATA_ROWS_CSV_V1', 'CATALOG_METADATA_ROWS_XLSX_V1')",
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
        CheckConstraint(
            "(state = 'QUEUED' AND next_attempt_at IS NOT NULL) "
            "OR (state <> 'QUEUED' AND next_attempt_at IS NULL)",
            name="retry_schedule_shape",
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
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
        UniqueConstraint(
            "workspace_id",
            "id",
            "content_profile",
            name="uq_upload_preparation_receipts_profile_identity",
        ),
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
            "content_profile IN ('CATALOG_METADATA_ROWS_CSV_V1', 'CATALOG_METADATA_ROWS_XLSX_V1')",
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
        CheckConstraint(
            "evidence_version IN ('LEGACY_V1', 'DATASET_DESCRIPTION_CANDIDATE_V2')",
            name="evidence_version_allowlist",
        ),
        CheckConstraint(
            "(evidence_version = 'LEGACY_V1' AND submitted_platform IS NULL "
            "AND submitted_database_name IS NULL AND submitted_schema_name IS NULL "
            "AND submitted_table_name IS NULL AND submitted_identity_hash IS NULL) OR "
            "(evidence_version = 'DATASET_DESCRIPTION_CANDIDATE_V2' "
            "AND submitted_platform IS NOT NULL AND submitted_database_name IS NOT NULL "
            "AND submitted_schema_name IS NOT NULL AND submitted_table_name IS NOT NULL "
            "AND submitted_identity_hash ~ '^[0-9a-f]{64}$')",
            name="submitted_identity_evidence_shape",
        ),
        CheckConstraint(
            "submitted_platform IS NULL OR "
            "(char_length(submitted_platform) BETWEEN 1 AND 100 "
            "AND submitted_platform = btrim(submitted_platform))",
            name="submitted_platform_valid",
        ),
        CheckConstraint(
            "submitted_database_name IS NULL OR "
            "(char_length(submitted_database_name) BETWEEN 1 AND 255 "
            "AND submitted_database_name = btrim(submitted_database_name))",
            name="submitted_database_name_valid",
        ),
        CheckConstraint(
            "submitted_schema_name IS NULL OR "
            "(char_length(submitted_schema_name) BETWEEN 1 AND 255 "
            "AND submitted_schema_name = btrim(submitted_schema_name))",
            name="submitted_schema_name_valid",
        ),
        CheckConstraint(
            "submitted_table_name IS NULL OR "
            "(char_length(submitted_table_name) BETWEEN 1 AND 500 "
            "AND submitted_table_name = btrim(submitted_table_name))",
            name="submitted_table_name_valid",
        ),
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
    evidence_version: Mapped[str] = mapped_column(
        String(100),
        default="DATASET_DESCRIPTION_CANDIDATE_V2",
        server_default="DATASET_DESCRIPTION_CANDIDATE_V2",
        nullable=False,
    )
    submitted_platform: Mapped[str | None] = mapped_column(String(100))
    submitted_database_name: Mapped[str | None] = mapped_column(String(255))
    submitted_schema_name: Mapped[str | None] = mapped_column(String(255))
    submitted_table_name: Mapped[str | None] = mapped_column(String(500))
    submitted_identity_hash: Mapped[str | None] = mapped_column(String(64))
    candidate_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CatalogMetadataRowModel(Base, UuidPrimaryKeyMixin):
    """Immutable source-row evidence for the typed catalog-metadata profiles."""

    __tablename__ = "catalog_metadata_rows"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "receipt_id", "ordinal"),
        UniqueConstraint(
            "workspace_id",
            "receipt_id",
            "semantic_target_hash",
            name="uq_catalog_metadata_rows_semantic_target",
        ),
        UniqueConstraint(
            "workspace_id",
            "receipt_id",
            "id",
            "content_profile",
            "row_hash",
            name="uq_catalog_metadata_rows_content",
        ),
        CheckConstraint("ordinal BETWEEN 1 AND 10000", name="ordinal_range"),
        CheckConstraint(
            "content_profile IN ('CATALOG_METADATA_ROWS_CSV_V1', 'CATALOG_METADATA_ROWS_XLSX_V1')",
            name="content_profile_allowlist",
        ),
        CheckConstraint(
            "evidence_version = 'CATALOG_METADATA_CANDIDATE_V3'",
            name="evidence_version_contract",
        ),
        CheckConstraint(
            "record_kind IN ('TABLE_DESCRIPTION', 'COLUMN_DESCRIPTION', "
            "'DATASET_DOMAIN', 'DATASET_TERM', 'DATASET_TAG')",
            name="record_kind_allowlist",
        ),
        CheckConstraint(
            "operation IN ('SET', 'CLEAR', 'ADD')",
            name="operation_allowlist",
        ),
        CheckConstraint(
            "(record_kind = 'TABLE_DESCRIPTION' AND aspect_name = 'datasetProperties') OR "
            "(record_kind = 'COLUMN_DESCRIPTION' AND aspect_name = 'schemaMetadata') OR "
            "(record_kind = 'DATASET_DOMAIN' AND aspect_name = 'domains') OR "
            "(record_kind = 'DATASET_TERM' AND aspect_name = 'glossaryTerms') OR "
            "(record_kind = 'DATASET_TAG' AND aspect_name = 'globalTags')",
            name="record_kind_aspect_contract",
        ),
        CheckConstraint(
            "char_length(submitted_platform) BETWEEN 1 AND 100 "
            "AND submitted_platform = btrim(submitted_platform)",
            name="submitted_platform_valid",
        ),
        CheckConstraint(
            "char_length(submitted_database_name) BETWEEN 1 AND 255 "
            "AND submitted_database_name = btrim(submitted_database_name)",
            name="submitted_database_name_valid",
        ),
        CheckConstraint(
            "char_length(submitted_schema_name) BETWEEN 1 AND 255 "
            "AND submitted_schema_name = btrim(submitted_schema_name)",
            name="submitted_schema_name_valid",
        ),
        CheckConstraint(
            "char_length(submitted_table_name) BETWEEN 1 AND 500 "
            "AND submitted_table_name = btrim(submitted_table_name)",
            name="submitted_table_name_valid",
        ),
        CheckConstraint(
            "field_path IS NULL OR "
            "(char_length(field_path) BETWEEN 1 AND 2000 "
            "AND field_path = btrim(field_path))",
            name="field_path_valid",
        ),
        CheckConstraint(
            "value_text IS NULL OR char_length(value_text) BETWEEN 1 AND 10000",
            name="value_text_valid",
        ),
        CheckConstraint(
            "controlled_kind IS NULL OR controlled_kind IN ('DOMAIN', 'TAG', 'TERM')",
            name="controlled_kind_vocabulary",
        ),
        CheckConstraint(
            "submitted_identity_hash ~ '^[0-9a-f]{64}$' "
            "AND semantic_target_hash ~ '^[0-9a-f]{64}$' "
            "AND row_hash ~ '^[0-9a-f]{64}$'",
            name="evidence_hashes_valid",
        ),
        CheckConstraint(
            "("
            "record_kind = 'TABLE_DESCRIPTION' "
            "AND field_path IS NULL AND controlled_ref_id IS NULL "
            "AND controlled_kind IS NULL "
            "AND ((operation = 'SET' AND value_text IS NOT NULL) "
            "OR (operation = 'CLEAR' AND value_text IS NULL))"
            ") OR ("
            "record_kind = 'COLUMN_DESCRIPTION' "
            "AND field_path IS NOT NULL AND controlled_ref_id IS NULL "
            "AND controlled_kind IS NULL "
            "AND ((operation = 'SET' AND value_text IS NOT NULL) "
            "OR (operation = 'CLEAR' AND value_text IS NULL))"
            ") OR ("
            "record_kind = 'DATASET_DOMAIN' "
            "AND field_path IS NULL AND value_text IS NULL "
            "AND ((operation = 'SET' AND controlled_ref_id IS NOT NULL "
            "AND controlled_kind = 'DOMAIN') "
            "OR (operation = 'CLEAR' AND controlled_ref_id IS NULL "
            "AND controlled_kind IS NULL))"
            ") OR ("
            "record_kind = 'DATASET_TERM' AND operation = 'ADD' "
            "AND field_path IS NULL AND value_text IS NULL "
            "AND controlled_ref_id IS NOT NULL AND controlled_kind = 'TERM'"
            ") OR ("
            "record_kind = 'DATASET_TAG' AND operation = 'ADD' "
            "AND field_path IS NULL AND value_text IS NULL "
            "AND controlled_ref_id IS NOT NULL AND controlled_kind = 'TAG'"
            ")",
            name="typed_detail_xor",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "receipt_id", "content_profile"),
            (
                "integration.upload_preparation_receipts.workspace_id",
                "integration.upload_preparation_receipts.id",
                "integration.upload_preparation_receipts.content_profile",
            ),
            name="fk_catalog_metadata_rows_receipt_profile",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "controlled_ref_id", "controlled_kind"),
            (
                "catalog.vocabulary_entries.workspace_id",
                "catalog.vocabulary_entries.id",
                "catalog.vocabulary_entries.kind",
            ),
            name="fk_catalog_metadata_rows_vocabulary",
            ondelete="RESTRICT",
        ),
        {"schema": "integration"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    receipt_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_profile: Mapped[str] = mapped_column(String(100), nullable=False)
    evidence_version: Mapped[str] = mapped_column(String(100), nullable=False)
    record_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    aspect_name: Mapped[str] = mapped_column(String(64), nullable=False)
    target_asset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    submitted_platform: Mapped[str] = mapped_column(String(100), nullable=False)
    submitted_database_name: Mapped[str] = mapped_column(String(255), nullable=False)
    submitted_schema_name: Mapped[str] = mapped_column(String(255), nullable=False)
    submitted_table_name: Mapped[str] = mapped_column(String(500), nullable=False)
    field_path: Mapped[str | None] = mapped_column(String(2_000))
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    value_text: Mapped[str | None] = mapped_column(Text)
    controlled_ref_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    controlled_kind: Mapped[str | None] = mapped_column(String(16))
    submitted_identity_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    semantic_target_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CatalogMetadataCandidateModel(Base, UuidPrimaryKeyMixin):
    """Immutable candidate grouping all rows for one dataset and fixed Aspect."""

    __tablename__ = "catalog_metadata_candidates"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "receipt_id", "candidate_ordinal"),
        UniqueConstraint(
            "workspace_id",
            "receipt_id",
            "target_asset_id",
            "aspect_name",
            name="uq_catalog_metadata_candidates_target_aspect",
        ),
        UniqueConstraint(
            "workspace_id",
            "receipt_id",
            "id",
            "content_profile",
            "candidate_hash",
            name="uq_catalog_metadata_candidates_membership_content",
        ),
        UniqueConstraint(
            "workspace_id",
            "id",
            "content_profile",
            "candidate_kind",
            "aspect_name",
            "candidate_hash",
            name="uq_catalog_metadata_candidates_binding_content",
        ),
        CheckConstraint(
            "candidate_ordinal BETWEEN 1 AND 10000",
            name="candidate_ordinal_range",
        ),
        CheckConstraint(
            "content_profile IN ('CATALOG_METADATA_ROWS_CSV_V1', 'CATALOG_METADATA_ROWS_XLSX_V1')",
            name="content_profile_allowlist",
        ),
        CheckConstraint(
            "evidence_version = 'CATALOG_METADATA_CANDIDATE_V3'",
            name="evidence_version_contract",
        ),
        CheckConstraint(
            "(record_kind = 'TABLE_DESCRIPTION' "
            "AND candidate_kind = 'TABLE_DESCRIPTION_UPDATE' "
            "AND aspect_name = 'datasetProperties') OR "
            "(record_kind = 'COLUMN_DESCRIPTION' "
            "AND candidate_kind = 'COLUMN_DESCRIPTION_UPDATE' "
            "AND aspect_name = 'schemaMetadata') OR "
            "(record_kind = 'DATASET_DOMAIN' "
            "AND candidate_kind = 'DATASET_DOMAIN_UPDATE' "
            "AND aspect_name = 'domains') OR "
            "(record_kind = 'DATASET_TERM' "
            "AND candidate_kind = 'DATASET_TERM_ADD' "
            "AND aspect_name = 'glossaryTerms') OR "
            "(record_kind = 'DATASET_TAG' "
            "AND candidate_kind = 'DATASET_TAG_ADD' "
            "AND aspect_name = 'globalTags')",
            name="record_candidate_aspect_contract",
        ),
        CheckConstraint(
            "row_count BETWEEN 1 AND 10000 "
            "AND first_row_ordinal BETWEEN 1 AND 10000 "
            "AND last_row_ordinal BETWEEN first_row_ordinal AND 10000",
            name="ordered_row_span",
        ),
        CheckConstraint(
            "submitted_identity_hash ~ '^[0-9a-f]{64}$' "
            "AND row_root_hash ~ '^[0-9a-f]{64}$' "
            "AND candidate_hash ~ '^[0-9a-f]{64}$'",
            name="evidence_hashes_valid",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "receipt_id", "content_profile"),
            (
                "integration.upload_preparation_receipts.workspace_id",
                "integration.upload_preparation_receipts.id",
                "integration.upload_preparation_receipts.content_profile",
            ),
            name="fk_catalog_metadata_candidates_receipt_profile",
            ondelete="RESTRICT",
        ),
        {"schema": "integration"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    receipt_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    candidate_ordinal: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_profile: Mapped[str] = mapped_column(String(100), nullable=False)
    record_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_kind: Mapped[str] = mapped_column(String(100), nullable=False)
    evidence_version: Mapped[str] = mapped_column(String(100), nullable=False)
    target_asset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    aspect_name: Mapped[str] = mapped_column(String(64), nullable=False)
    submitted_identity_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    first_row_ordinal: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_row_ordinal: Mapped[int] = mapped_column(BigInteger, nullable=False)
    row_root_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CatalogMetadataCandidateRowModel(Base):
    """Immutable ordered membership between a grouped candidate and source rows."""

    __tablename__ = "catalog_metadata_candidate_rows"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "receipt_id",
            "candidate_id",
            "member_ordinal",
            name="uq_catalog_metadata_candidate_rows_member",
        ),
        UniqueConstraint(
            "workspace_id",
            "receipt_id",
            "candidate_id",
            "source_ordinal",
            name="uq_catalog_metadata_candidate_rows_source_ordinal",
        ),
        UniqueConstraint(
            "workspace_id",
            "receipt_id",
            "row_id",
            name="uq_catalog_metadata_candidate_rows_row",
        ),
        CheckConstraint(
            "member_ordinal BETWEEN 1 AND 10000 AND source_ordinal BETWEEN 1 AND 10000",
            name="ordinal_range",
        ),
        CheckConstraint(
            "content_profile IN ('CATALOG_METADATA_ROWS_CSV_V1', 'CATALOG_METADATA_ROWS_XLSX_V1')",
            name="content_profile_allowlist",
        ),
        CheckConstraint(
            "candidate_hash ~ '^[0-9a-f]{64}$' AND row_hash ~ '^[0-9a-f]{64}$'",
            name="content_hashes_valid",
        ),
        ForeignKeyConstraint(
            (
                "workspace_id",
                "receipt_id",
                "candidate_id",
                "content_profile",
                "candidate_hash",
            ),
            (
                "integration.catalog_metadata_candidates.workspace_id",
                "integration.catalog_metadata_candidates.receipt_id",
                "integration.catalog_metadata_candidates.id",
                "integration.catalog_metadata_candidates.content_profile",
                "integration.catalog_metadata_candidates.candidate_hash",
            ),
            name="fk_catalog_metadata_candidate_rows_candidate",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            (
                "workspace_id",
                "receipt_id",
                "row_id",
                "content_profile",
                "row_hash",
            ),
            (
                "integration.catalog_metadata_rows.workspace_id",
                "integration.catalog_metadata_rows.receipt_id",
                "integration.catalog_metadata_rows.id",
                "integration.catalog_metadata_rows.content_profile",
                "integration.catalog_metadata_rows.row_hash",
            ),
            name="fk_catalog_metadata_candidate_rows_row",
            ondelete="RESTRICT",
        ),
        {
            "schema": "integration",
        },
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    receipt_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    candidate_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    row_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    content_profile: Mapped[str] = mapped_column(String(100), nullable=False)
    candidate_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    member_ordinal: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_ordinal: Mapped[int] = mapped_column(BigInteger, nullable=False)
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
