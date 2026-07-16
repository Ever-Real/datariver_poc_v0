from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
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


class RetentionPolicyVersionModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "policy_versions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_retention_policy_versions_workspace_id_id"),
        UniqueConstraint(
            "workspace_id",
            "id",
            "payload_hash",
            name="uq_retention_policy_versions_workspace_id_hash",
        ),
        UniqueConstraint(
            "workspace_id",
            "policy_number",
            name="uq_retention_policy_versions_workspace_number",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "requester_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_retention_policy_versions_requester_membership",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "checker_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_retention_policy_versions_checker_membership",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "superseded_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_retention_policy_versions_superseder_membership",
        ),
        CheckConstraint("policy_number > 0", name="policy_number_positive"),
        CheckConstraint(
            "completed_operation_days BETWEEN 1 AND 3650 AND "
            "chat_content_days BETWEEN 1 AND 3650 AND "
            "audit_online_months BETWEEN 1 AND 120 AND "
            "immutable_archive_years BETWEEN 1 AND 100",
            name="rules_supported_bounds",
        ),
        CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="payload_hash_sha256"),
        CheckConstraint("state IN ('DRAFT', 'ACTIVE', 'REJECTED', 'SUPERSEDED')", name="state"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(
            "checker_id IS NULL OR checker_id <> requester_id", name="independent_checker"
        ),
        CheckConstraint(
            "length(btrim(request_reason)) > 0 AND "
            "(decision_reason IS NULL OR length(btrim(decision_reason)) > 0) AND "
            "(supersede_reason IS NULL OR length(btrim(supersede_reason)) > 0)",
            name="reasons_nonempty",
        ),
        CheckConstraint(
            "(state = 'DRAFT' AND checker_id IS NULL AND decision_reason IS NULL "
            "AND decision_policy_decision_id IS NULL AND decided_at IS NULL "
            "AND superseded_by IS NULL AND supersede_reason IS NULL "
            "AND supersede_policy_decision_id IS NULL AND superseded_at IS NULL) OR "
            "(state IN ('ACTIVE', 'REJECTED') AND checker_id IS NOT NULL "
            "AND decision_reason IS NOT NULL AND decision_policy_decision_id IS NOT NULL "
            "AND decided_at IS NOT NULL AND superseded_by IS NULL "
            "AND supersede_reason IS NULL AND supersede_policy_decision_id IS NULL "
            "AND superseded_at IS NULL) OR "
            "(state = 'SUPERSEDED' AND checker_id IS NOT NULL "
            "AND decision_reason IS NOT NULL AND decision_policy_decision_id IS NOT NULL "
            "AND decided_at IS NOT NULL AND superseded_by IS NOT NULL "
            "AND supersede_reason IS NOT NULL AND supersede_policy_decision_id IS NOT NULL "
            "AND superseded_at IS NOT NULL)",
            name="state_shape",
        ),
        Index(
            "uq_retention_policy_versions_workspace_active",
            "workspace_id",
            unique=True,
            postgresql_where=text("state = 'ACTIVE'"),
        ),
        Index("ix_retention_policy_versions_workspace_number", "workspace_id", "policy_number"),
        {"schema": "retention"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("platform.workspaces.id"),
        nullable=False,
    )
    policy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_operation_days: Mapped[int] = mapped_column(Integer, nullable=False)
    chat_content_days: Mapped[int] = mapped_column(Integer, nullable=False)
    audit_online_months: Mapped[int] = mapped_column(Integer, nullable=False)
    immutable_archive_years: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requester_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    request_reason: Mapped[str] = mapped_column(String(4000), nullable=False)
    request_policy_decision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    checker_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    decision_reason: Mapped[str | None] = mapped_column(String(4000))
    decision_policy_decision_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    decided_at: Mapped[datetime | None]
    superseded_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    supersede_reason: Mapped[str | None] = mapped_column(String(4000))
    supersede_policy_decision_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    superseded_at: Mapped[datetime | None]


class LegalHoldModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "legal_holds"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_legal_holds_workspace_id_id"),
        ForeignKeyConstraint(
            ["workspace_id", "created_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_legal_holds_creator_membership",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "release_requested_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_legal_holds_release_requester_membership",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "release_checker_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_legal_holds_release_checker_membership",
        ),
        CheckConstraint(
            "data_class IN ('COMPLETED_OPERATIONS', 'CHAT_CONTENT', "
            "'AUDIT_EVIDENCE', 'OBJECT_DATA')",
            name="data_class",
        ),
        CheckConstraint("scope IN ('WORKSPACE', 'SUBJECT', 'RESOURCE')", name="scope"),
        CheckConstraint(
            "(scope = 'WORKSPACE' AND scope_id IS NULL) OR "
            "(scope IN ('SUBJECT', 'RESOURCE') AND scope_id IS NOT NULL)",
            name="scope_shape",
        ),
        CheckConstraint(
            "state IN ('ACTIVE', 'RELEASE_REQUESTED', 'RELEASE_REJECTED', 'RELEASED')",
            name="state",
        ),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("length(btrim(reason)) > 0", name="reason_nonempty"),
        CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="payload_hash_sha256"),
        CheckConstraint(
            "release_checker_id IS NULL OR release_checker_id <> release_requested_by",
            name="independent_release_checker",
        ),
        CheckConstraint(
            "scope <> 'SUBJECT' OR release_checker_id IS NULL OR release_checker_id <> scope_id",
            name="subject_cannot_release_own_hold",
        ),
        CheckConstraint(
            "(state = 'ACTIVE' AND release_requested_by IS NULL "
            "AND release_request_reason IS NULL "
            "AND release_request_policy_decision_id IS NULL "
            "AND release_checker_id IS NULL AND release_decision_reason IS NULL "
            "AND release_decision_policy_decision_id IS NULL AND released_at IS NULL) OR "
            "(state = 'RELEASE_REQUESTED' AND release_requested_by IS NOT NULL "
            "AND release_request_reason IS NOT NULL "
            "AND release_request_policy_decision_id IS NOT NULL "
            "AND release_checker_id IS NULL AND release_decision_reason IS NULL "
            "AND release_decision_policy_decision_id IS NULL AND released_at IS NULL) OR "
            "(state = 'RELEASE_REJECTED' AND release_requested_by IS NOT NULL "
            "AND release_request_reason IS NOT NULL "
            "AND release_request_policy_decision_id IS NOT NULL "
            "AND release_checker_id IS NOT NULL AND release_decision_reason IS NOT NULL "
            "AND release_decision_policy_decision_id IS NOT NULL AND released_at IS NULL) OR "
            "(state = 'RELEASED' AND release_requested_by IS NOT NULL "
            "AND release_request_reason IS NOT NULL "
            "AND release_request_policy_decision_id IS NOT NULL "
            "AND release_checker_id IS NOT NULL AND release_decision_reason IS NOT NULL "
            "AND release_decision_policy_decision_id IS NOT NULL AND released_at IS NOT NULL)",
            name="state_shape",
        ),
        Index(
            "ix_legal_holds_workspace_blocking_scope",
            "workspace_id",
            "data_class",
            "scope",
            "scope_id",
            postgresql_where=text("state <> 'RELEASED'"),
        ),
        Index("ix_legal_holds_workspace_state", "workspace_id", "state", "updated_at"),
        {"schema": "retention"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("platform.workspaces.id"),
        nullable=False,
    )
    data_class: Mapped[str] = mapped_column(String(32), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    reason: Mapped[str] = mapped_column(String(4000), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    create_policy_decision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    release_requested_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    release_request_reason: Mapped[str | None] = mapped_column(String(4000))
    release_request_policy_decision_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    release_checker_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    release_decision_reason: Mapped[str | None] = mapped_column(String(4000))
    release_decision_policy_decision_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    released_at: Mapped[datetime | None]


class LegalHoldEventModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "legal_hold_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "hold_id"],
            ["retention.legal_holds.workspace_id", "retention.legal_holds.id"],
            name="fk_legal_hold_events_hold",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "actor_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_legal_hold_events_actor_membership",
        ),
        UniqueConstraint(
            "workspace_id",
            "hold_id",
            "hold_version",
            name="uq_legal_hold_events_hold_version",
        ),
        CheckConstraint(
            "action IN ('PLACED', 'RELEASE_REQUESTED', 'RELEASE_APPROVED', 'RELEASE_REJECTED')",
            name="action",
        ),
        CheckConstraint(
            "(action = 'PLACED' AND hold_version = 1) OR (action <> 'PLACED' AND hold_version > 1)",
            name="action_version_shape",
        ),
        CheckConstraint("length(btrim(reason)) > 0", name="reason_nonempty"),
        CheckConstraint("hold_version > 0", name="hold_version_positive"),
        CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="payload_hash_sha256"),
        Index(
            "ix_legal_hold_events_workspace_hold_time",
            "workspace_id",
            "hold_id",
            "occurred_at",
        ),
        {"schema": "retention"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("platform.workspaces.id"),
        nullable=False,
    )
    hold_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(4000), nullable=False)
    policy_decision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)
    hold_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ErasureRequestModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "erasure_requests"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_erasure_requests_workspace_id_id"),
        UniqueConstraint(
            "workspace_id",
            "requester_id",
            "payload_hash",
            name="uq_erasure_requests_idempotent_payload",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "retention_policy_id", "retention_policy_hash"],
            [
                "retention.policy_versions.workspace_id",
                "retention.policy_versions.id",
                "retention.policy_versions.payload_hash",
            ],
            name="fk_erasure_requests_retention_policy",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "requester_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_erasure_requests_requester_membership",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "checker_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_erasure_requests_checker_membership",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "target_owner_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_erasure_requests_target_owner_membership",
        ),
        CheckConstraint(
            "target_type IN ('SUBJECT_DATA', 'CHAT_SESSION', 'UPLOAD_OBJECT')",
            name="target_type",
        ),
        CheckConstraint("target_version > 0", name="target_version_positive"),
        CheckConstraint("classification BETWEEN 0 AND 3", name="classification_range"),
        CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="payload_hash_sha256"),
        CheckConstraint(
            "retention_policy_hash ~ '^[0-9a-f]{64}$'",
            name="retention_policy_hash_sha256",
        ),
        CheckConstraint("state IN ('PENDING', 'APPROVED', 'REJECTED')", name="state"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(
            "length(btrim(request_reason)) > 0 AND "
            "(decision_reason IS NULL OR length(btrim(decision_reason)) > 0)",
            name="reasons_nonempty",
        ),
        CheckConstraint(
            "expires_at > created_at AND expires_at <= created_at + INTERVAL '7 days' "
            "AND (decided_at IS NULL OR decided_at >= created_at) "
            "AND (state <> 'APPROVED' OR decided_at < expires_at)",
            name="review_window",
        ),
        CheckConstraint(
            "checker_id IS NULL OR checker_id <> requester_id", name="independent_checker"
        ),
        CheckConstraint(
            "checker_id IS NULL OR target_owner_id IS NULL OR checker_id <> target_owner_id",
            name="target_owner_cannot_check",
        ),
        CheckConstraint(
            "target_type <> 'SUBJECT_DATA' OR checker_id IS NULL OR checker_id <> target_id",
            name="subject_cannot_check_own_erasure",
        ),
        CheckConstraint(
            "(state = 'PENDING' AND version = 1 AND checker_id IS NULL "
            "AND decision_reason IS NULL AND decision_policy_decision_id IS NULL "
            "AND decided_at IS NULL) OR "
            "(state IN ('APPROVED', 'REJECTED') AND version = 2 "
            "AND checker_id IS NOT NULL AND decision_reason IS NOT NULL "
            "AND decision_policy_decision_id IS NOT NULL AND decided_at IS NOT NULL)",
            name="state_shape",
        ),
        Index(
            "ix_erasure_requests_workspace_state_expiry",
            "workspace_id",
            "state",
            "expires_at",
        ),
        Index(
            "ix_erasure_requests_workspace_target",
            "workspace_id",
            "target_type",
            "target_id",
            "created_at",
        ),
        {"schema": "retention"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform.workspaces.id"), nullable=False
    )
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    target_version: Mapped[int] = mapped_column(Integer, nullable=False)
    target_owner_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    classification: Mapped[int] = mapped_column(Integer, nullable=False)
    retention_policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    retention_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requester_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    request_reason: Mapped[str] = mapped_column(String(4000), nullable=False)
    request_policy_decision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    checker_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    decision_reason: Mapped[str | None] = mapped_column(String(4000))
    decision_policy_decision_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    decided_at: Mapped[datetime | None]


class ErasureRequestEventModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "erasure_request_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "erasure_request_id"],
            ["retention.erasure_requests.workspace_id", "retention.erasure_requests.id"],
            name="fk_erasure_request_events_request",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "actor_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_erasure_request_events_actor_membership",
        ),
        UniqueConstraint(
            "workspace_id",
            "erasure_request_id",
            "request_version",
            name="uq_erasure_request_events_request_version",
        ),
        CheckConstraint("action IN ('CREATED', 'APPROVED', 'REJECTED')", name="action"),
        CheckConstraint(
            "(action = 'CREATED' AND request_version = 1) OR "
            "(action IN ('APPROVED', 'REJECTED') AND request_version = 2)",
            name="action_version_shape",
        ),
        CheckConstraint("length(btrim(reason)) > 0", name="reason_nonempty"),
        CheckConstraint("request_version > 0", name="request_version_positive"),
        CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="payload_hash_sha256"),
        Index(
            "ix_erasure_request_events_workspace_request_time",
            "workspace_id",
            "erasure_request_id",
            "occurred_at",
        ),
        {"schema": "retention"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform.workspaces.id"), nullable=False
    )
    erasure_request_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(4000), nullable=False)
    policy_decision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)
    request_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
