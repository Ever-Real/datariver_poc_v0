from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import conv

from datariver.infrastructure.db.base import (
    JSON_DOCUMENT,
    Base,
    TimestampMixin,
    UuidPrimaryKeyMixin,
    VersionMixin,
)


class ChangeRequestModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "change_requests"
    __table_args__ = (
        UniqueConstraint("workspace_id", "number"),
        UniqueConstraint("workspace_id", "id"),
        CheckConstraint(
            "priority IS NULL OR priority IN ('LOW', 'NORMAL', 'HIGH', 'CRITICAL')",
            name="priority_vocabulary",
        ),
        CheckConstraint(
            "urgency IS NULL OR urgency IN ('NORMAL', 'URGENT', 'EMERGENCY')",
            name="urgency_vocabulary",
        ),
        Index("ix_change_requests_workspace_state", "workspace_id", "state", "created_at"),
        Index(
            "ix_change_requests_workspace_created_id",
            "workspace_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_change_requests_workspace_state_created_id",
            "workspace_id",
            "state",
            "created_at",
            "id",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "id", "current_round_id"),
            (
                "governance.change_request_rounds.workspace_id",
                "governance.change_request_rounds.change_request_id",
                "governance.change_request_rounds.id",
            ),
            name="fk_change_requests_current_round",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        {"schema": "governance"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    number: Mapped[str] = mapped_column(String(100), nullable=False)
    request_type: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    requester_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    requester_department_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    current_round_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    current_round_number: Mapped[int] = mapped_column(default=1, nullable=False)
    classification: Mapped[int] = mapped_column(default=0, nullable=False)
    requested_due_date: Mapped[date | None]
    priority: Mapped[str | None] = mapped_column(String(16))
    urgency: Mapped[str | None] = mapped_column(String(16))


class ChangeRequestRoundModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "change_request_rounds"
    __table_args__ = (
        UniqueConstraint("workspace_id", "change_request_id", "round_number"),
        UniqueConstraint("workspace_id", "change_request_id", "id"),
        CheckConstraint("round_number > 0", name="round_number_positive"),
        CheckConstraint("evidence_hash ~ '^[0-9a-f]{64}$'", name="evidence_hash_valid"),
        ForeignKeyConstraint(
            ("workspace_id", "change_request_id"),
            ("governance.change_requests.workspace_id", "governance.change_requests.id"),
            ondelete="CASCADE",
            name="fk_change_request_rounds_request",
        ),
        Index("ix_change_request_rounds_request", "workspace_id", "change_request_id"),
        {"schema": "governance"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    change_request_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    round_number: Mapped[int] = mapped_column(nullable=False)
    submitted_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ChangeItemModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "change_request_items"
    __table_args__ = (
        Index("ix_change_items_request", "change_request_id"),
        Index(
            "ix_change_items_target",
            "workspace_id",
            "target_asset_id",
            "aspect_name",
        ),
        UniqueConstraint("change_request_id", "ordinal"),
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint(
            "workspace_id",
            "change_request_id",
            "id",
            name="uq_change_request_item_request_identity",
        ),
        CheckConstraint(
            "(target_asset_id IS NULL AND target_asset_type IS NULL "
            "AND target_system_id IS NULL AND target_domain_id IS NULL "
            "AND target_owner_department_id IS NULL "
            "AND target_classification IS NULL AND target_lifecycle IS NULL "
            "AND target_source_version IS NULL AND target_observed_at IS NULL "
            "AND target_binding_hash IS NULL) OR "
            "(target_asset_id IS NOT NULL AND target_asset_type IS NOT NULL "
            "AND target_classification IS NOT NULL AND target_lifecycle IS NOT NULL "
            "AND target_source_version IS NOT NULL AND target_observed_at IS NOT NULL "
            "AND target_binding_hash IS NOT NULL)",
            name="target_binding_shape",
        ),
        CheckConstraint(
            "target_classification IS NULL OR target_classification BETWEEN 0 AND 3",
            name="target_classification_range",
        ),
        CheckConstraint(
            "target_binding_hash IS NULL OR target_binding_hash ~ '^[0-9a-f]{64}$'",
            name="target_binding_hash_sha256",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "change_request_id"),
            ("governance.change_requests.workspace_id", "governance.change_requests.id"),
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "routing_system_id"),
            ("platform.data_systems.workspace_id", "platform.data_systems.id"),
            ondelete="RESTRICT",
            name="fk_change_items_routing_system",
        ),
        {"schema": "governance"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    change_request_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    target_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_ref: Mapped[str] = mapped_column(Text, nullable=False)
    aspect_name: Mapped[str] = mapped_column(String(255), nullable=False)
    ordinal: Mapped[int] = mapped_column(nullable=False)
    operation: Mapped[str] = mapped_column(String(50), nullable=False)
    before_hash: Mapped[str | None] = mapped_column(String(64))
    after_document: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    after_hash: Mapped[str | None] = mapped_column(String(64))
    target_asset_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    target_asset_type: Mapped[str | None] = mapped_column(String(100))
    target_system_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    target_domain_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    target_owner_department_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    target_classification: Mapped[int | None]
    target_lifecycle: Mapped[str | None] = mapped_column(String(50))
    target_source_version: Mapped[str | None] = mapped_column(String(255))
    target_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    target_binding_hash: Mapped[str | None] = mapped_column(String(64))
    routing_system_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))


class ChangeRequestAttachmentModel(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """Private CR request/test evidence; bytes remain only in the configured object store."""

    __tablename__ = "change_request_attachments"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint(
            "bucket",
            "object_key",
            name="uq_change_request_attachment_object",
        ),
        UniqueConstraint(
            "workspace_id",
            "change_request_id",
            "round_id",
            "id",
            name="uq_change_request_attachment_round_identity",
        ),
        UniqueConstraint(
            "workspace_id",
            "change_request_id",
            "kind",
            "original_name",
            "serial_number",
            name="uq_change_request_attachment_serial",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "change_request_id"),
            ("governance.change_requests.workspace_id", "governance.change_requests.id"),
            ondelete="CASCADE",
            name="fk_change_request_attachments_request",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "change_request_id", "round_id"),
            (
                "governance.change_request_rounds.workspace_id",
                "governance.change_request_rounds.change_request_id",
                "governance.change_request_rounds.id",
            ),
            ondelete="RESTRICT",
            name="fk_change_request_attachments_round",
        ),
        CheckConstraint("kind IN ('REQUEST', 'TEST')", name="kind_vocabulary"),
        CheckConstraint("serial_number BETWEEN 1 AND 999999", name="serial_number_range"),
        CheckConstraint("size_bytes BETWEEN 1 AND 10485760", name="size_bytes_range"),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256_valid"),
        Index("ix_change_request_attachments_request", "workspace_id", "change_request_id"),
        {"schema": "governance"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    change_request_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    round_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    original_name: Mapped[str] = mapped_column(String(500), nullable=False)
    serial_number: Mapped[int] = mapped_column(nullable=False)
    bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)


class ChangeRequestAttachmentUploadIntentModel(
    Base,
    UuidPrimaryKeyMixin,
    TimestampMixin,
    VersionMixin,
):
    """Durable authorization and reconciliation state for one create-only object upload."""

    __tablename__ = "change_request_attachment_upload_intents"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint(
            "bucket",
            "object_key",
            name="uq_change_request_attachment_upload_intent_object",
        ),
        UniqueConstraint(
            "workspace_id",
            "change_request_id",
            "kind",
            "original_name",
            "serial_number",
            name="uq_change_request_attachment_upload_intent_serial",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "change_request_id"),
            ("governance.change_requests.workspace_id", "governance.change_requests.id"),
            ondelete="CASCADE",
            name="fk_change_request_attachment_upload_intents_request",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "change_request_id", "round_id"),
            (
                "governance.change_request_rounds.workspace_id",
                "governance.change_request_rounds.change_request_id",
                "governance.change_request_rounds.id",
            ),
            ondelete="RESTRICT",
            name="fk_change_request_attachment_upload_intents_round",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "uploaded_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_change_request_attachment_upload_intents_uploader",
        ),
        CheckConstraint(
            "kind IN ('REQUEST', 'TEST')",
            name=conv("ck_cr_attachment_intent_kind"),
        ),
        CheckConstraint(
            "state IN ('STARTED', 'STORED', 'FINALIZED', 'FAILED')",
            name=conv("ck_cr_attachment_intent_state"),
        ),
        CheckConstraint(
            "serial_number BETWEEN 1 AND 999999",
            name=conv("ck_cr_attachment_intent_serial"),
        ),
        CheckConstraint(
            "expected_size_bytes BETWEEN 1 AND 10485760",
            name=conv("ck_cr_attachment_intent_expected_size"),
        ),
        CheckConstraint(
            "expected_content_sha256 ~ '^[0-9a-f]{64}$'",
            name=conv("ck_cr_attachment_intent_expected_sha"),
        ),
        CheckConstraint(
            "size_bytes IS NULL OR size_bytes BETWEEN 1 AND 10485760",
            name=conv("ck_cr_attachment_intent_size"),
        ),
        CheckConstraint(
            "content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$'",
            name=conv("ck_cr_attachment_intent_sha"),
        ),
        CheckConstraint(
            "(state = 'STARTED' AND size_bytes IS NULL AND content_sha256 IS NULL "
            "AND provider_checksum IS NULL AND stored_at IS NULL AND finalized_at IS NULL "
            "AND failed_at IS NULL AND failure_code IS NULL) OR "
            "(state = 'STORED' AND size_bytes = expected_size_bytes "
            "AND content_sha256 = expected_content_sha256 AND stored_at IS NOT NULL "
            "AND finalized_at IS NULL AND failed_at IS NULL AND failure_code IS NULL) OR "
            "(state = 'FINALIZED' AND size_bytes = expected_size_bytes "
            "AND content_sha256 = expected_content_sha256 AND stored_at IS NOT NULL "
            "AND finalized_at IS NOT NULL AND failed_at IS NULL AND failure_code IS NULL) OR "
            "(state = 'FAILED' AND size_bytes IS NULL AND content_sha256 IS NULL "
            "AND provider_checksum IS NULL AND stored_at IS NULL AND finalized_at IS NULL "
            "AND failed_at IS NOT NULL AND failure_code IS NOT NULL)",
            name=conv("ck_cr_attachment_intent_shape"),
        ),
        Index(
            "ix_change_request_attachment_upload_intents_reconcile",
            "state",
            "updated_at",
            "id",
        ),
        Index(
            "ix_change_request_attachment_upload_intents_request",
            "workspace_id",
            "change_request_id",
        ),
        {"schema": "governance"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    change_request_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    round_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    original_name: Mapped[str] = mapped_column(String(500), nullable=False)
    serial_number: Mapped[int] = mapped_column(nullable=False)
    bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    expected_size_bytes: Mapped[int] = mapped_column(nullable=False)
    expected_content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    size_bytes: Mapped[int | None]
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    provider_checksum: Mapped[str | None] = mapped_column(String(255))
    uploaded_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    stored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(100))


class RegistrationContentBindingModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "registration_content_bindings"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "candidate_id"),
        UniqueConstraint("workspace_id", "change_request_id"),
        UniqueConstraint("workspace_id", "change_item_id"),
        CheckConstraint(
            "candidate_hash ~ '^[0-9a-f]{64}$'",
            name="candidate_hash_valid",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "candidate_id", "candidate_hash"),
            (
                "integration.upload_registration_candidates.workspace_id",
                "integration.upload_registration_candidates.id",
                "integration.upload_registration_candidates.candidate_hash",
            ),
            name="fk_reg_content_bindings_candidate_content",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "change_request_id"),
            ("governance.change_requests.workspace_id", "governance.change_requests.id"),
            name="fk_reg_content_bindings_workspace_request",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "change_request_id", "change_item_id"),
            (
                "governance.change_request_items.workspace_id",
                "governance.change_request_items.change_request_id",
                "governance.change_request_items.id",
            ),
            name="fk_reg_content_bindings_request_item",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "created_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            name="fk_reg_content_bindings_workspace_creator",
            ondelete="RESTRICT",
        ),
        {"schema": "governance"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    candidate_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    candidate_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    change_request_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    change_item_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ManualMetadataSubmissionModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    """Immutable manual-registration intent plus its private CSV receipt."""

    __tablename__ = "manual_metadata_submissions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "serial_number"),
        UniqueConstraint("bucket", "object_key"),
        Index(
            "ix_manual_metadata_submissions_workspace_state",
            "workspace_id",
            "state",
            "created_at",
        ),
        CheckConstraint("serial_number > 0", name="serial_number_positive"),
        CheckConstraint("csv_sha256 ~ '^[0-9a-f]{64}$'", name="csv_sha256_valid"),
        CheckConstraint(
            "provider_source_version ~ '^[0-9a-f]{64}$'",
            name="provider_source_version_valid",
        ),
        CheckConstraint("csv_size_bytes > 0", name="csv_size_bytes_positive"),
        CheckConstraint("row_count > 0", name="row_count_positive"),
        CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
        CheckConstraint("attempts <= 20", name="attempts_maximum"),
        CheckConstraint("lease_epoch = attempts", name="lease_epoch_matches_attempts"),
        CheckConstraint(
            "lease_token_hash IS NULL OR lease_token_hash ~ '^[0-9a-f]{64}$'",
            name="lease_token_hash_valid",
        ),
        CheckConstraint(
            "state IN ('QUEUED', 'APPLYING', 'APPLIED', 'FAILED')",
            name="state_vocabulary",
        ),
        CheckConstraint(
            "(state = 'QUEUED' AND next_attempt_at IS NOT NULL) "
            "OR (state <> 'QUEUED' AND next_attempt_at IS NULL)",
            name="retry_schedule_shape",
        ),
        CheckConstraint(
            "(state = 'APPLYING' AND lease_token_hash IS NOT NULL "
            "AND lease_owner_id IS NOT NULL AND lease_started_at IS NOT NULL "
            "AND lease_expires_at IS NOT NULL AND lease_expires_at > lease_started_at) "
            "OR (state <> 'APPLYING' AND lease_token_hash IS NULL "
            "AND lease_owner_id IS NULL AND lease_started_at IS NULL "
            "AND lease_expires_at IS NULL)",
            name="lease_shape",
        ),
        CheckConstraint(
            "(state = 'APPLIED' AND applied_at IS NOT NULL) "
            "OR (state <> 'APPLIED' AND applied_at IS NULL)",
            name="applied_at_shape",
        ),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_object"),
        ForeignKeyConstraint(
            ("workspace_id", "asset_id"),
            ("catalog.assets_projection.workspace_id", "catalog.assets_projection.id"),
            name="fk_manual_metadata_submissions_asset",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "requester_id"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            name="fk_manual_metadata_submissions_requester",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "lease_owner_id"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            name="fk_manual_metadata_submissions_lease_owner",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_manual_metadata_submissions_claim",
            "workspace_id",
            "next_attempt_at",
            "created_at",
            "id",
            postgresql_where=text("state = 'QUEUED'"),
        ),
        Index(
            "ix_manual_metadata_submissions_requester",
            "workspace_id",
            "requester_id",
            "created_at",
            "id",
        ),
        Index(
            "uq_manual_metadata_submissions_active_asset",
            "workspace_id",
            "asset_id",
            unique=True,
            postgresql_where=text("state = 'APPLYING'"),
        ),
        {"schema": "governance"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    requester_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    external_urn: Mapped[str] = mapped_column(Text, nullable=False)
    source_version: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_source_version: Mapped[str] = mapped_column(String(64), nullable=False)
    serial_number: Mapped[int] = mapped_column(nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    csv_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    csv_size_bytes: Mapped[int] = mapped_column(nullable=False)
    row_count: Mapped[int] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_epoch: Mapped[int] = mapped_column(default=0, nullable=False)
    lease_token_hash: Mapped[str | None] = mapped_column(String(64))
    lease_owner_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    lease_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ManualMetadataApplyAttemptModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "manual_metadata_apply_attempts"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "submission_id", "id"),
        UniqueConstraint("workspace_id", "submission_id", "attempt_no"),
        UniqueConstraint("workspace_id", "submission_id", "lease_epoch"),
        CheckConstraint("attempt_no > 0 AND lease_epoch > 0", name="attempt_fence_positive"),
        CheckConstraint(
            "lease_token_hash ~ '^[0-9a-f]{64}$'",
            name="lease_token_hash_valid",
        ),
        CheckConstraint(
            "state IN ('RUNNING', 'APPLIED', 'RETRY_WAIT', 'FAILED', 'SUPERSEDED')",
            name="state_vocabulary",
        ),
        CheckConstraint(
            "(state = 'RUNNING' AND finished_at IS NULL "
            "AND report_root_hash IS NULL AND failure_code IS NULL) "
            "OR (state <> 'RUNNING' AND finished_at IS NOT NULL "
            "AND finished_at >= started_at "
            "AND report_root_hash ~ '^[0-9a-f]{64}$' "
            "AND ((state = 'APPLIED' AND failure_code IS NULL) "
            "OR (state <> 'APPLIED' AND failure_code IS NOT NULL)))",
            name="terminal_shape",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "submission_id"),
            (
                "governance.manual_metadata_submissions.workspace_id",
                "governance.manual_metadata_submissions.id",
            ),
            name="fk_manual_apply_attempts_submission",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "worker_subject_id"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            name="fk_manual_apply_attempts_worker",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_manual_apply_attempts_submission",
            "workspace_id",
            "submission_id",
            "attempt_no",
        ),
        {"schema": "governance"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    submission_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    attempt_no: Mapped[int] = mapped_column(nullable=False)
    lease_epoch: Mapped[int] = mapped_column(nullable=False)
    lease_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    worker_subject_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(100))
    report_root_hash: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ManualMetadataAspectReportModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "manual_metadata_aspect_reports"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "attempt_id", "aspect_name"),
        CheckConstraint(
            "(aspect_name = 'datasetProperties' AND aspect_ordinal = 1) OR "
            "(aspect_name = 'domains' AND aspect_ordinal = 2) OR "
            "(aspect_name = 'globalTags' AND aspect_ordinal = 3) OR "
            "(aspect_name = 'glossaryTerms' AND aspect_ordinal = 4) OR "
            "(aspect_name = 'schemaMetadata' AND aspect_ordinal = 5)",
            name="aspect_ordinal_contract",
        ),
        CheckConstraint(
            "outcome IN ('ALREADY_MATCHED', 'APPLIED_VERIFIED', "
            "'FAILED_BEFORE_WRITE', 'WRITE_REJECTED', "
            "'READBACK_FAILED', 'READBACK_MISMATCH')",
            name="outcome_vocabulary",
        ),
        CheckConstraint(
            "(before_hash IS NULL OR before_hash ~ '^[0-9a-f]{64}$') "
            "AND (expected_hash IS NULL OR expected_hash ~ '^[0-9a-f]{64}$') "
            "AND (observed_hash IS NULL OR observed_hash ~ '^[0-9a-f]{64}$') "
            "AND (failure_code IS NULL OR char_length(failure_code) BETWEEN 1 AND 100)",
            name="content_hashes_valid",
        ),
        CheckConstraint(
            "(outcome = 'ALREADY_MATCHED' AND write_attempted = false "
            "AND before_hash = expected_hash "
            "AND expected_hash = observed_hash AND failure_code IS NULL "
            "AND provider_operation_id_hash IS NULL "
            "AND provider_version IS NULL AND provider_response_hash IS NULL) OR "
            "(outcome = 'APPLIED_VERIFIED' AND write_attempted = true "
            "AND expected_hash = observed_hash AND failure_code IS NULL "
            "AND provider_operation_id_hash ~ '^[0-9a-f]{64}$' "
            "AND char_length(provider_version) BETWEEN 1 AND 255 "
            "AND provider_response_hash ~ '^[0-9a-f]{64}$') OR "
            "(outcome = 'FAILED_BEFORE_WRITE' AND write_attempted = false "
            "AND before_hash IS NULL AND expected_hash IS NULL AND observed_hash IS NULL "
            "AND failure_code IS NOT NULL AND provider_operation_id_hash IS NULL "
            "AND provider_version IS NULL AND provider_response_hash IS NULL) OR "
            "(outcome = 'WRITE_REJECTED' AND write_attempted = true "
            "AND before_hash IS NOT NULL AND expected_hash IS NOT NULL "
            "AND observed_hash IS NULL AND failure_code IS NOT NULL "
            "AND provider_operation_id_hash IS NULL AND provider_version IS NULL "
            "AND provider_response_hash IS NULL) OR "
            "(outcome = 'READBACK_FAILED' AND write_attempted = true "
            "AND before_hash IS NOT NULL AND expected_hash IS NOT NULL "
            "AND observed_hash IS NULL AND failure_code IS NOT NULL "
            "AND provider_operation_id_hash ~ '^[0-9a-f]{64}$' "
            "AND char_length(provider_version) BETWEEN 1 AND 255 "
            "AND provider_response_hash ~ '^[0-9a-f]{64}$') OR "
            "(outcome = 'READBACK_MISMATCH' AND write_attempted = true "
            "AND before_hash IS NOT NULL AND expected_hash IS NOT NULL "
            "AND observed_hash IS NOT NULL AND expected_hash <> observed_hash "
            "AND failure_code IS NOT NULL "
            "AND provider_operation_id_hash ~ '^[0-9a-f]{64}$' "
            "AND char_length(provider_version) BETWEEN 1 AND 255 "
            "AND provider_response_hash ~ '^[0-9a-f]{64}$')",
            name="verified_outcome_shape",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "submission_id"),
            (
                "governance.manual_metadata_submissions.workspace_id",
                "governance.manual_metadata_submissions.id",
            ),
            name="fk_manual_aspect_reports_submission",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "submission_id", "attempt_id"),
            (
                "governance.manual_metadata_apply_attempts.workspace_id",
                "governance.manual_metadata_apply_attempts.submission_id",
                "governance.manual_metadata_apply_attempts.id",
            ),
            name="fk_manual_aspect_reports_attempt",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_manual_aspect_reports_attempt",
            "workspace_id",
            "attempt_id",
            "aspect_ordinal",
        ),
        {"schema": "governance"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    submission_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    attempt_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    aspect_name: Mapped[str] = mapped_column(String(64), nullable=False)
    aspect_ordinal: Mapped[int] = mapped_column(nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    before_hash: Mapped[str | None] = mapped_column(String(64))
    expected_hash: Mapped[str | None] = mapped_column(String(64))
    observed_hash: Mapped[str | None] = mapped_column(String(64))
    write_attempted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(100))
    provider_operation_id_hash: Mapped[str | None] = mapped_column(String(64))
    provider_version: Mapped[str | None] = mapped_column(String(255))
    provider_response_hash: Mapped[str | None] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ApprovalModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "approvals"
    __table_args__ = (
        UniqueConstraint("change_request_id", "round_id", "stage", "actor_id"),
        ForeignKeyConstraint(
            ("workspace_id", "change_request_id"),
            ("governance.change_requests.workspace_id", "governance.change_requests.id"),
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "change_request_id", "round_id"),
            (
                "governance.change_request_rounds.workspace_id",
                "governance.change_request_rounds.change_request_id",
                "governance.change_request_rounds.id",
            ),
            ondelete="RESTRICT",
            name="fk_approvals_round",
        ),
        CheckConstraint("jsonb_typeof(authority_snapshot) = 'array'", name="authority_array"),
        {"schema": "governance"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    change_request_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    round_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    stage: Mapped[str] = mapped_column(String(50), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    policy_decision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)
    authority_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )


class StateTransitionModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "state_transitions"
    __table_args__ = (
        Index("ix_state_transitions_request_time", "change_request_id", "occurred_at"),
        ForeignKeyConstraint(
            ("workspace_id", "change_request_id"),
            ("governance.change_requests.workspace_id", "governance.change_requests.id"),
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "change_request_id", "round_id"),
            (
                "governance.change_request_rounds.workspace_id",
                "governance.change_request_rounds.change_request_id",
                "governance.change_request_rounds.id",
            ),
            ondelete="RESTRICT",
            name="fk_state_transitions_round",
        ),
        {"schema": "governance"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    change_request_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    round_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    from_state: Mapped[str] = mapped_column(String(32), nullable=False)
    to_state: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    policy_decision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)


class ChangeTestRunModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "change_test_runs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "change_request_id", "round_id", "id"),
        CheckConstraint("state IN ('PASSED', 'FAILED')", name="state_vocabulary"),
        CheckConstraint("plan_hash ~ '^[0-9a-f]{64}$'", name="plan_hash_valid"),
        CheckConstraint("result_hash ~ '^[0-9a-f]{64}$'", name="result_hash_valid"),
        CheckConstraint("jsonb_typeof(bounded_summary) = 'object'", name="summary_object"),
        ForeignKeyConstraint(
            ("workspace_id", "change_request_id", "round_id"),
            (
                "governance.change_request_rounds.workspace_id",
                "governance.change_request_rounds.change_request_id",
                "governance.change_request_rounds.id",
            ),
            ondelete="RESTRICT",
            name="fk_change_test_runs_round",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "system_id"),
            ("platform.data_systems.workspace_id", "platform.data_systems.id"),
            ondelete="RESTRICT",
            name="fk_change_test_runs_system",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "change_request_id", "round_id", "attachment_id"),
            (
                "governance.change_request_attachments.workspace_id",
                "governance.change_request_attachments.change_request_id",
                "governance.change_request_attachments.round_id",
                "governance.change_request_attachments.id",
            ),
            ondelete="RESTRICT",
            name="fk_change_test_runs_attachment",
        ),
        Index(
            "ix_change_test_runs_round_system",
            "workspace_id",
            "change_request_id",
            "round_id",
            "system_id",
        ),
        {"schema": "governance"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    change_request_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    round_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    system_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    attachment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    bounded_summary: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    recorded_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
