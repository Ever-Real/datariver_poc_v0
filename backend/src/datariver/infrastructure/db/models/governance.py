from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
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
        {"schema": "governance"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    number: Mapped[str] = mapped_column(String(100), nullable=False)
    request_type: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    requester_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    classification: Mapped[int] = mapped_column(default=0, nullable=False)
    requested_due_date: Mapped[date | None]
    priority: Mapped[str | None] = mapped_column(String(16))
    urgency: Mapped[str | None] = mapped_column(String(16))


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


class RegistrationContentBindingModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "registration_content_bindings"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "candidate_id"),
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


class ApprovalModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "approvals"
    __table_args__ = (
        UniqueConstraint("change_request_id", "stage", "actor_id"),
        ForeignKeyConstraint(
            ("workspace_id", "change_request_id"),
            ("governance.change_requests.workspace_id", "governance.change_requests.id"),
            ondelete="CASCADE",
        ),
        {"schema": "governance"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    change_request_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    stage: Mapped[str] = mapped_column(String(50), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    policy_decision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)


class StateTransitionModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "state_transitions"
    __table_args__ = (
        Index("ix_state_transitions_request_time", "change_request_id", "occurred_at"),
        ForeignKeyConstraint(
            ("workspace_id", "change_request_id"),
            ("governance.change_requests.workspace_id", "governance.change_requests.id"),
            ondelete="CASCADE",
        ),
        {"schema": "governance"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    change_request_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    from_state: Mapped[str] = mapped_column(String(32), nullable=False)
    to_state: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    policy_decision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)
