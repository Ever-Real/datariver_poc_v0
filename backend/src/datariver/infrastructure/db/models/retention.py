from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
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
            "id",
            "payload_hash",
            "policy_number",
            name="uq_retention_policy_versions_workspace_id_hash_number",
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
        CheckConstraint(
            "(contract_version = 'SINGLE_DEADLINE_V1' "
            "AND effective_from IS NULL AND effective_until IS NULL "
            "AND execution_authorization_hours IS NULL) OR "
            "(contract_version IN ('POLICY_BOOK_V2', 'POLICY_BOOK_V3') "
            "AND effective_from IS NOT NULL "
            "AND (effective_until IS NULL OR effective_until > effective_from) "
            "AND execution_authorization_hours BETWEEN 1 AND 168)",
            name="contract_shape",
        ),
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
    contract_version: Mapped[str] = mapped_column(
        String(32), server_default=text("'SINGLE_DEADLINE_V1'"), nullable=False
    )
    effective_from: Mapped[datetime | None]
    effective_until: Mapped[datetime | None]
    execution_authorization_hours: Mapped[int | None] = mapped_column(Integer)
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


class RetentionPolicyClassRuleModel(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "policy_class_rules"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "id", name="uq_retention_policy_class_rules_workspace_id_id"
        ),
        UniqueConstraint(
            "workspace_id",
            "policy_id",
            "data_class",
            name="uq_retention_policy_class_rules_workspace_policy_class",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "policy_id", "policy_hash", "policy_number"],
            [
                "retention.policy_versions.workspace_id",
                "retention.policy_versions.id",
                "retention.policy_versions.payload_hash",
                "retention.policy_versions.policy_number",
            ],
            name="fk_retention_policy_class_rules_policy",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "data_class IN ('COMPLETED_OPERATIONS', 'CHAT_CONTENT', "
            "'AUDIT_EVIDENCE', 'OBJECT_DATA', 'QUALITY_RULE', "
            "'QUALITY_RESULT', 'QUALITY_AUDIT')",
            name="data_class",
        ),
        CheckConstraint("unit IN ('DAYS', 'MONTHS', 'YEARS')", name="unit"),
        CheckConstraint(
            "archive_disposition IN ('NO_ARCHIVE', 'EVIDENCE_ONLY', 'CONTENT_WORM')",
            name="archive_disposition",
        ),
        CheckConstraint(
            "minimum_value >= 0 AND maximum_value >= 1 "
            "AND minimum_value <= maximum_value "
            "AND ((unit = 'DAYS' AND maximum_value <= 36500) "
            "OR (unit = 'MONTHS' AND maximum_value <= 1200) "
            "OR (unit = 'YEARS' AND maximum_value <= 100))",
            name="bounds",
        ),
        CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="payload_hash_sha256"),
        Index(
            "ix_retention_policy_class_rules_workspace_policy",
            "workspace_id",
            "policy_id",
            "data_class",
        ),
        {"schema": "retention"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform.workspaces.id"), nullable=False
    )
    policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    data_class: Mapped[str] = mapped_column(String(32), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    minimum_value: Mapped[int] = mapped_column(Integer, nullable=False)
    maximum_value: Mapped[int] = mapped_column(Integer, nullable=False)
    archive_disposition: Mapped[str] = mapped_column(String(24), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)


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
            "'AUDIT_EVIDENCE', 'OBJECT_DATA', 'QUALITY_RULE', "
            "'QUALITY_RESULT', 'QUALITY_AUDIT')",
            name="data_class",
        ),
        CheckConstraint("scope IN ('WORKSPACE', 'SUBJECT', 'RESOURCE')", name="scope"),
        CheckConstraint(
            "(scope = 'WORKSPACE' AND scope_id IS NULL AND resource_type IS NULL) OR "
            "(scope = 'SUBJECT' AND scope_id IS NOT NULL AND resource_type IS NULL) OR "
            "(scope = 'RESOURCE' AND scope_id IS NOT NULL AND resource_type IN "
            "('LEGACY_UNTYPED', 'CHAT_SESSION', 'UPLOAD_OBJECT', "
            "'QUALITY_RULE_SET', 'QUALITY_VALIDATION_RUN'))",
            name="scope_shape",
        ),
        CheckConstraint(
            "scope <> 'RESOURCE' OR "
            "(resource_type = 'LEGACY_UNTYPED' "
            "AND data_class IN ('COMPLETED_OPERATIONS', 'CHAT_CONTENT', "
            "'AUDIT_EVIDENCE', 'OBJECT_DATA')) OR "
            "(resource_type = 'CHAT_SESSION' AND data_class = 'CHAT_CONTENT') OR "
            "(resource_type = 'UPLOAD_OBJECT' AND data_class = 'OBJECT_DATA') OR "
            "(resource_type = 'QUALITY_RULE_SET' "
            "AND data_class IN ('QUALITY_RULE', 'QUALITY_AUDIT')) OR "
            "(resource_type = 'QUALITY_VALIDATION_RUN' "
            "AND data_class IN ('QUALITY_RESULT', 'QUALITY_AUDIT'))",
            name="resource_semantics",
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
            "resource_type",
            "scope_id",
            postgresql_where=text("state <> 'RELEASED'"),
        ),
        Index("ix_legal_holds_workspace_state", "workspace_id", "state", "updated_at"),
        Index(
            "ix_legal_holds_workspace_created_id",
            "workspace_id",
            text("created_at DESC"),
            "id",
        ),
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
    resource_type: Mapped[str | None] = mapped_column(String(40))
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


class LegalHoldGenerationModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "legal_hold_generations"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "data_class",
            name="uq_legal_hold_generations_workspace_class",
        ),
        CheckConstraint(
            "data_class IN ('COMPLETED_OPERATIONS', 'CHAT_CONTENT', "
            "'AUDIT_EVIDENCE', 'OBJECT_DATA', 'QUALITY_RULE', "
            "'QUALITY_RESULT', 'QUALITY_AUDIT')",
            name="data_class",
        ),
        CheckConstraint("generation > 0", name="generation_positive"),
        CheckConstraint("resolution_hash ~ '^[0-9a-f]{64}$'", name="resolution_hash_sha256"),
        CheckConstraint("version > 0", name="version_positive"),
        {"schema": "retention"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("platform.workspaces.id"),
        nullable=False,
    )
    data_class: Mapped[str] = mapped_column(String(32), nullable=False)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    resolution_hash: Mapped[str] = mapped_column(String(64), nullable=False)


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
            "id",
            "version",
            "payload_hash",
            name="uq_erasure_requests_workspace_id_version_hash",
        ),
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
        Index(
            "ix_erasure_requests_workspace_created_id",
            "workspace_id",
            text("created_at DESC"),
            "id",
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


class ArchiveCapabilityAttestationModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "archive_capability_attestations"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "id", name="uq_archive_capability_attestations_workspace_id_id"
        ),
        UniqueConstraint(
            "workspace_id",
            "id",
            "configuration_fingerprint",
            "encryption_profile_fingerprint",
            "runtime_principal_fingerprint",
            name="uq_archive_capability_attestations_workspace_id_fingerprint",
        ),
        UniqueConstraint(
            "workspace_id",
            "configuration_fingerprint",
            "observed_at",
            name="uq_archive_capability_attestations_observation",
        ),
        CheckConstraint(
            "configuration_fingerprint ~ '^[0-9a-f]{64}$'",
            name="configuration_fingerprint_sha256",
        ),
        CheckConstraint(
            "encryption_profile_fingerprint ~ '^[0-9a-f]{64}$'",
            name="encryption_profile_fingerprint_sha256",
        ),
        CheckConstraint(
            "runtime_principal_fingerprint ~ '^[0-9a-f]{64}$'",
            name="runtime_principal_fingerprint_sha256",
        ),
        CheckConstraint("challenge_hash ~ '^[0-9a-f]{64}$'", name="challenge_hash_sha256"),
        CheckConstraint(
            "length(probe_contract_version) BETWEEN 1 AND 100",
            name="probe_contract_version",
        ),
        CheckConstraint(
            "object_bucket ~ '^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$'",
            name="object_bucket",
        ),
        CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="payload_hash_sha256"),
        CheckConstraint(
            "expires_at > observed_at AND expires_at <= observed_at + INTERVAL '24 hours'",
            name="observation_window",
        ),
        CheckConstraint("state IN ('VERIFIED', 'FAILED')", name="state"),
        CheckConstraint(
            "(state = 'VERIFIED' AND failure_code IS NULL "
            "AND versioning_enabled AND object_lock_enabled "
            "AND compliance_retention_supported AND checksum_sha256_supported "
            "AND full_readback_verified AND retention_shorten_denied "
            "AND retained_version_delete_denied) OR "
            "(state = 'FAILED' AND failure_code IS NOT NULL "
            "AND length(btrim(failure_code)) BETWEEN 1 AND 100)",
            name="state_shape",
        ),
        Index(
            "ix_archive_capability_attestations_workspace_observed",
            "workspace_id",
            "configuration_fingerprint",
            "observed_at",
        ),
        {"schema": "retention"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform.workspaces.id"), nullable=False
    )
    configuration_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    encryption_profile_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime_principal_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    probe_contract_version: Mapped[str] = mapped_column(String(100), nullable=False)
    challenge_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    object_bucket: Mapped[str] = mapped_column(String(63), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    versioning_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    object_lock_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    compliance_retention_supported: Mapped[bool] = mapped_column(Boolean, nullable=False)
    checksum_sha256_supported: Mapped[bool] = mapped_column(Boolean, nullable=False)
    full_readback_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    retention_shorten_denied: Mapped[bool] = mapped_column(Boolean, nullable=False)
    retained_version_delete_denied: Mapped[bool] = mapped_column(Boolean, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(100))
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class ImmutableArchiveReceiptModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "immutable_archive_receipts"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "id", name="uq_immutable_archive_receipts_workspace_id_id"
        ),
        UniqueConstraint(
            "workspace_id",
            "id",
            "manifest_hash",
            name="uq_immutable_archive_receipts_workspace_id_manifest",
        ),
        UniqueConstraint(
            "workspace_id",
            "source",
            "source_start",
            "source_end",
            "manifest_hash",
            name="uq_immutable_archive_receipts_source_manifest",
        ),
        UniqueConstraint(
            "object_bucket",
            "object_key",
            "object_version_id",
            name="uq_immutable_archive_receipts_object_version",
        ),
        ForeignKeyConstraint(
            [
                "workspace_id",
                "capability_attestation_id",
                "capability_fingerprint",
                "encryption_profile_fingerprint",
                "worker_principal_fingerprint",
            ],
            [
                "retention.archive_capability_attestations.workspace_id",
                "retention.archive_capability_attestations.id",
                "retention.archive_capability_attestations.configuration_fingerprint",
                "retention.archive_capability_attestations.encryption_profile_fingerprint",
                "retention.archive_capability_attestations.runtime_principal_fingerprint",
            ],
            name="fk_immutable_archive_receipts_capability_attestation",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "retention_policy_id", "retention_policy_hash"],
            [
                "retention.policy_versions.workspace_id",
                "retention.policy_versions.id",
                "retention.policy_versions.payload_hash",
            ],
            name="fk_immutable_archive_receipts_retention_policy",
        ),
        CheckConstraint(
            "source IN ('OUTBOX_EVENTS', 'INBOX_MESSAGES', 'POLICY_DECISIONS', 'ASSISTANT_RUNS', "
            "'ERASURE_EXECUTION_EVIDENCE')",
            name="source",
        ),
        CheckConstraint(
            "source_partition ~ '^[a-z][a-z0-9_]{1,49}_[0-9]{4}_[0-9]{2}$'",
            name="source_partition",
        ),
        CheckConstraint("row_count > 0", name="row_count_positive"),
        CheckConstraint("byte_count > 0", name="byte_count_positive"),
        CheckConstraint("source_end > source_start", name="source_range"),
        CheckConstraint("manifest_hash ~ '^[0-9a-f]{64}$'", name="manifest_hash_sha256"),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256"),
        CheckConstraint("length(provider_checksum) BETWEEN 1 AND 512", name="provider_checksum"),
        CheckConstraint("provider_checksum_algorithm = 'SHA256'", name="checksum_algorithm"),
        CheckConstraint(
            "provider_checksum_encoding IN ('HEX', 'BASE64')", name="checksum_encoding"
        ),
        CheckConstraint("provider_checksum_type = 'FULL_OBJECT'", name="checksum_type"),
        CheckConstraint(
            "provider_checksum_normalized_sha256 ~ '^[0-9a-f]{64}$'",
            name="provider_checksum_normalized_sha256",
        ),
        CheckConstraint("readback_sha256 ~ '^[0-9a-f]{64}$'", name="readback_sha256"),
        CheckConstraint("readback_byte_count > 0", name="readback_byte_count_positive"),
        CheckConstraint(
            "content_sha256 = readback_sha256 "
            "AND content_sha256 = provider_checksum_normalized_sha256 "
            "AND byte_count = readback_byte_count",
            name="content_readback_match",
        ),
        CheckConstraint(
            "object_bucket ~ '^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$'",
            name="object_bucket",
        ),
        CheckConstraint(
            "length(object_key) BETWEEN 1 AND 1024 AND object_key !~ '^/'",
            name="object_key",
        ),
        CheckConstraint(
            "length(object_version_id) BETWEEN 1 AND 1024 "
            "AND lower(btrim(object_version_id)) <> 'null'",
            name="object_version_id",
        ),
        CheckConstraint("retention_mode = 'COMPLIANCE'", name="retention_mode"),
        CheckConstraint(
            "retention_until = requested_retention_until "
            "AND retention_until = readback_retention_until "
            "AND retention_until > verified_at",
            name="retention_readback_match",
        ),
        CheckConstraint(
            "written_at <= content_verified_at "
            "AND written_at <= retention_verified_at "
            "AND content_verified_at <= verified_at "
            "AND retention_verified_at <= verified_at",
            name="verification_timeline",
        ),
        CheckConstraint(
            "retention_policy_hash ~ '^[0-9a-f]{64}$'",
            name="retention_policy_hash_sha256",
        ),
        CheckConstraint(
            "capability_fingerprint ~ '^[0-9a-f]{64}$'",
            name="capability_fingerprint_sha256",
        ),
        CheckConstraint(
            "encryption_profile_fingerprint ~ '^[0-9a-f]{64}$'",
            name="encryption_profile_fingerprint_sha256",
        ),
        CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="payload_hash_sha256"),
        CheckConstraint(
            "worker_principal_fingerprint ~ '^[0-9a-f]{64}$'",
            name="worker_principal_fingerprint_sha256",
        ),
        CheckConstraint(
            "length(correlation_id) BETWEEN 1 AND 100",
            name="correlation_id",
        ),
        CheckConstraint(
            "length(canonicalization_version) BETWEEN 1 AND 100 "
            "AND length(media_type) BETWEEN 1 AND 255 "
            "AND length(media_type_version) BETWEEN 1 AND 100 "
            "AND length(compression) BETWEEN 1 AND 50 "
            "AND length(compression_version) BETWEEN 1 AND 100",
            name="format_metadata",
        ),
        Index(
            "ix_immutable_archive_receipts_workspace_source",
            "workspace_id",
            "source",
            "source_partition",
        ),
        Index(
            "ix_immutable_archive_receipts_workspace_verified",
            "workspace_id",
            "verified_at",
        ),
        {"schema": "retention"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform.workspaces.id"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_partition: Mapped[str] = mapped_column(String(64), nullable=False)
    source_start: Mapped[datetime] = mapped_column(nullable=False)
    source_end: Mapped[datetime] = mapped_column(nullable=False)
    retention_policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    retention_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    byte_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_checksum: Mapped[str] = mapped_column(String(512), nullable=False)
    provider_checksum_algorithm: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_checksum_encoding: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_checksum_type: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_checksum_normalized_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    readback_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    readback_byte_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    object_bucket: Mapped[str] = mapped_column(String(63), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    object_version_id: Mapped[str] = mapped_column(String(1024), nullable=False)
    retention_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    retention_until: Mapped[datetime] = mapped_column(nullable=False)
    requested_retention_until: Mapped[datetime] = mapped_column(nullable=False)
    readback_retention_until: Mapped[datetime] = mapped_column(nullable=False)
    legal_hold: Mapped[bool] = mapped_column(Boolean, nullable=False)
    written_at: Mapped[datetime] = mapped_column(nullable=False)
    content_verified_at: Mapped[datetime] = mapped_column(nullable=False)
    retention_verified_at: Mapped[datetime] = mapped_column(nullable=False)
    verified_at: Mapped[datetime] = mapped_column(nullable=False)
    canonicalization_version: Mapped[str] = mapped_column(String(100), nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type_version: Mapped[str] = mapped_column(String(100), nullable=False)
    compression: Mapped[str] = mapped_column(String(50), nullable=False)
    compression_version: Mapped[str] = mapped_column(String(100), nullable=False)
    worker_principal_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False)
    capability_attestation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    capability_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    encryption_profile_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class RetentionExecutionJobModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "execution_jobs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_retention_execution_jobs_workspace_id_id"),
        UniqueConstraint(
            "workspace_id",
            "erasure_request_id",
            name="uq_retention_execution_jobs_erasure_request",
        ),
        UniqueConstraint(
            "workspace_id", "command_hash", name="uq_retention_execution_jobs_command_hash"
        ),
        ForeignKeyConstraint(
            [
                "workspace_id",
                "erasure_request_id",
                "erasure_request_version",
                "erasure_request_payload_hash",
            ],
            [
                "retention.erasure_requests.workspace_id",
                "retention.erasure_requests.id",
                "retention.erasure_requests.version",
                "retention.erasure_requests.payload_hash",
            ],
            name="fk_retention_execution_jobs_erasure_request",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "retention_policy_id", "retention_policy_hash", "policy_number"],
            [
                "retention.policy_versions.workspace_id",
                "retention.policy_versions.id",
                "retention.policy_versions.payload_hash",
                "retention.policy_versions.policy_number",
            ],
            name="fk_retention_execution_jobs_policy",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "archive_receipt_id", "archive_manifest_hash"],
            [
                "retention.immutable_archive_receipts.workspace_id",
                "retention.immutable_archive_receipts.id",
                "retention.immutable_archive_receipts.manifest_hash",
            ],
            name="fk_retention_execution_jobs_archive_receipt",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["executor_id"],
            ["iam.subjects.id"],
            name="fk_retention_execution_jobs_executor",
            ondelete="RESTRICT",
        ),
        CheckConstraint("kind = 'EXPLICIT_ERASURE_EVIDENCE'", name="kind"),
        CheckConstraint(
            "target_type = 'CHAT_SESSION' AND target_version > 0 "
            "AND target_owner_id IS NOT NULL AND classification BETWEEN 0 AND 3 "
            "AND target_snapshot_hash ~ '^[0-9a-f]{64}$'",
            name="target_shape",
        ),
        CheckConstraint(
            "state IN ('PLANNED', 'LEASED', 'RETRY_WAIT', 'BLOCKED', "
            "'ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED')",
            name="state",
        ),
        CheckConstraint("destructive_state = 'DISABLED_NOT_READY'", name="destructive_disabled"),
        CheckConstraint("archive_disposition = 'EVIDENCE_ONLY'", name="archive_disposition"),
        CheckConstraint(
            "command_hash ~ '^[0-9a-f]{64}$' "
            "AND erasure_request_payload_hash ~ '^[0-9a-f]{64}$' "
            "AND retention_policy_hash ~ '^[0-9a-f]{64}$' "
            "AND archive_configuration_hash ~ '^[0-9a-f]{64}$' "
            "AND (archive_manifest_hash IS NULL OR archive_manifest_hash ~ '^[0-9a-f]{64}$')",
            name="hashes_sha256",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= maximum_attempts "
            "AND maximum_attempts BETWEEN 1 AND 20 "
            "AND lease_epoch >= 0 AND version > 0",
            name="counters",
        ),
        CheckConstraint(
            "requester_id <> checker_id "
            "AND checker_id <> target_owner_id "
            "AND executor_id <> requester_id "
            "AND executor_id <> checker_id "
            "AND executor_id <> target_owner_id",
            name="separation_of_duties",
        ),
        CheckConstraint("archive_retain_until > created_at", name="archive_retention_deadline"),
        CheckConstraint(
            "(state = 'LEASED' AND lease_token_hash IS NOT NULL "
            "AND lease_owner_fingerprint IS NOT NULL AND lease_until IS NOT NULL) OR "
            "(state <> 'LEASED' AND lease_token_hash IS NULL "
            "AND lease_owner_fingerprint IS NULL AND lease_until IS NULL)",
            name="lease_shape",
        ),
        CheckConstraint(
            "lease_token_hash IS NULL OR lease_token_hash ~ '^[0-9a-f]{64}$'",
            name="lease_token_hash_sha256",
        ),
        CheckConstraint(
            "lease_owner_fingerprint IS NULL OR lease_owner_fingerprint ~ '^[0-9a-f]{64}$'",
            name="lease_owner_fingerprint_sha256",
        ),
        CheckConstraint(
            "(state = 'ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED' "
            "AND archive_receipt_id IS NOT NULL AND archive_manifest_hash IS NOT NULL) OR "
            "(state = 'BLOCKED' "
            "AND (last_failure_code = 'KILL_SWITCH_DISABLED_AFTER_WRITE' "
            "OR last_failure_code LIKE 'POST_WRITE_RECEIPT_%') "
            "AND archive_receipt_id IS NOT NULL AND archive_manifest_hash IS NOT NULL) OR "
            "(state <> 'ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED' "
            "AND COALESCE(last_failure_code, '') <> 'KILL_SWITCH_DISABLED_AFTER_WRITE' "
            "AND COALESCE(last_failure_code, '') NOT LIKE 'POST_WRITE_RECEIPT_%' "
            "AND archive_receipt_id IS NULL AND archive_manifest_hash IS NULL)",
            name="archive_receipt_shape",
        ),
        CheckConstraint(
            "last_failure_code IS NULL OR length(last_failure_code) BETWEEN 1 AND 100",
            name="failure_code",
        ),
        Index(
            "ix_retention_execution_jobs_claim",
            "workspace_id",
            "next_attempt_at",
            "created_at",
            "id",
            postgresql_where=text("state IN ('PLANNED', 'RETRY_WAIT')"),
        ),
        Index(
            "ix_retention_execution_jobs_expired_lease",
            "workspace_id",
            "lease_until",
            "id",
            postgresql_where=text("state = 'LEASED'"),
        ),
        {"schema": "retention"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform.workspaces.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    erasure_request_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    erasure_request_version: Mapped[int] = mapped_column(Integer, nullable=False)
    erasure_request_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    target_version: Mapped[int] = mapped_column(Integer, nullable=False)
    target_owner_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    classification: Mapped[int] = mapped_column(Integer, nullable=False)
    target_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    retention_policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    retention_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    requester_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    checker_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    executor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    execution_authorization_valid_until: Mapped[datetime] = mapped_column(nullable=False)
    archive_disposition: Mapped[str] = mapped_column(String(24), nullable=False)
    archive_configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    command_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    archive_retain_until: Mapped[datetime] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(String(48), nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    maximum_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_token_hash: Mapped[str | None] = mapped_column(String(64))
    lease_owner_fingerprint: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None]
    archive_receipt_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    archive_manifest_hash: Mapped[str | None] = mapped_column(String(64))
    last_failure_code: Mapped[str | None] = mapped_column(String(100))
    destructive_state: Mapped[str] = mapped_column(String(32), nullable=False)


class RetentionExecutionAttemptModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "execution_attempts"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "id", name="uq_retention_execution_attempts_workspace_id_id"
        ),
        UniqueConstraint(
            "workspace_id",
            "execution_job_id",
            "lease_epoch",
            name="uq_retention_execution_attempts_job_fence",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "execution_job_id"],
            ["retention.execution_jobs.workspace_id", "retention.execution_jobs.id"],
            name="fk_retention_execution_attempts_job",
            ondelete="RESTRICT",
        ),
        CheckConstraint("attempt_no > 0 AND lease_epoch > 0", name="positive_fence"),
        CheckConstraint("lease_token_hash ~ '^[0-9a-f]{64}$'", name="lease_token_hash"),
        CheckConstraint(
            "worker_principal_fingerprint ~ '^[0-9a-f]{64}$'",
            name="worker_principal_fingerprint_sha256",
        ),
        CheckConstraint(
            "state IN ('RUNNING', 'RETRY_WAIT', 'BLOCKED', "
            "'ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED', 'SUPERSEDED')",
            name="state",
        ),
        CheckConstraint("destructive_effect_count = 0", name="destructive_effect_zero"),
        CheckConstraint(
            "length(correlation_id) BETWEEN 1 AND 100 "
            "AND (failure_code IS NULL OR length(failure_code) BETWEEN 1 AND 100)",
            name="bounded_text",
        ),
        CheckConstraint(
            "evidence_hash ~ '^[0-9a-f]{64}$' "
            "AND (external_response_hash IS NULL "
            "OR external_response_hash ~ '^[0-9a-f]{64}$')",
            name="evidence_hashes",
        ),
        CheckConstraint("finished_at IS NULL OR finished_at >= started_at", name="timeline"),
        {"schema": "retention"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform.workspaces.id"), nullable=False
    )
    execution_job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    worker_principal_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(48), nullable=False)
    stage: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    external_response_hash: Mapped[str | None] = mapped_column(String(64))
    failure_code: Mapped[str | None] = mapped_column(String(100))
    destructive_effect_count: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    finished_at: Mapped[datetime | None]


class RetentionExecutionEventModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "execution_events"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "id", name="uq_retention_execution_events_workspace_id_id"
        ),
        UniqueConstraint(
            "workspace_id",
            "execution_job_id",
            "sequence",
            name="uq_retention_execution_events_job_sequence",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "execution_job_id"],
            ["retention.execution_jobs.workspace_id", "retention.execution_jobs.id"],
            name="fk_retention_execution_events_job",
            ondelete="RESTRICT",
        ),
        CheckConstraint("sequence > 0", name="sequence_positive"),
        CheckConstraint(
            "event_type IN ('PLANNED', 'LEASED', 'RETRY_WAIT', 'BLOCKED', "
            "'ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED')",
            name="event_type",
        ),
        CheckConstraint("evidence_hash ~ '^[0-9a-f]{64}$'", name="evidence_hash_sha256"),
        CheckConstraint(
            "reason_code IS NULL OR length(reason_code) BETWEEN 1 AND 100",
            name="reason_code",
        ),
        Index(
            "ix_retention_execution_events_workspace_job_time",
            "workspace_id",
            "execution_job_id",
            "occurred_at",
        ),
        {"schema": "retention"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform.workspaces.id"), nullable=False
    )
    execution_job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    attempt_no: Mapped[int | None] = mapped_column(Integer)
    reason_code: Mapped[str | None] = mapped_column(String(100))
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)
