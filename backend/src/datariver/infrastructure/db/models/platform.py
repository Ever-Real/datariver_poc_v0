from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
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


class WorkspaceModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("slug"), {"schema": "platform"})

    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)


class SubjectModel(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "subjects"
    __table_args__ = (
        UniqueConstraint("issuer", "external_subject"),
        {"schema": "iam"},
    )

    issuer: Mapped[str] = mapped_column(String(500), nullable=False)
    external_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class WorkspaceMembershipModel(Base, TimestampMixin, VersionMixin):
    __tablename__ = "workspace_memberships"
    __table_args__ = (
        UniqueConstraint("workspace_id", "subject_id"),
        {"schema": "iam"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("platform.workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    )
    subject_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("iam.subjects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    department_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    job_function: Mapped[str | None] = mapped_column(String(100))
    clearance: Mapped[int] = mapped_column(default=0, nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class DataSystemModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    """Canonical business-system master, scoped to exactly one workspace."""

    __tablename__ = "data_systems"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "code"),
        CheckConstraint("code ~ '^[A-Za-z][A-Za-z0-9_-]{1,99}$'", name="code_shape"),
        Index("ix_data_systems_workspace_active_name", "workspace_id", "active", "name"),
        {"schema": "platform"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("platform.workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class SystemSchemaScopeModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    """An explicit DataHub platform/database/schema to business-system mapping."""

    __tablename__ = "system_schema_scopes"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "platform", "database_name", "schema_name"),
        ForeignKeyConstraint(
            ("workspace_id", "system_id"),
            ("platform.data_systems.workspace_id", "platform.data_systems.id"),
            ondelete="CASCADE",
            name="fk_system_schema_scopes_system",
        ),
        CheckConstraint("length(trim(platform)) > 0", name="platform_present"),
        CheckConstraint("length(trim(database_name)) > 0", name="database_present"),
        CheckConstraint("length(trim(schema_name)) > 0", name="schema_present"),
        Index("ix_system_schema_scopes_workspace_system", "workspace_id", "system_id"),
        {"schema": "platform"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    system_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    platform: Mapped[str] = mapped_column(String(100), nullable=False)
    database_name: Mapped[str] = mapped_column(String(255), nullable=False)
    schema_name: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class SystemAssigneeModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    """A named human responsibility within a business-system master."""

    __tablename__ = "system_assignees"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "system_id", "subject_id", "responsibility"),
        ForeignKeyConstraint(
            ("workspace_id", "system_id"),
            ("platform.data_systems.workspace_id", "platform.data_systems.id"),
            ondelete="CASCADE",
            name="fk_system_assignees_system",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "subject_id"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_system_assignees_membership",
        ),
        CheckConstraint(
            "responsibility IN ('DEVELOPER', 'DATA_STEWARD')",
            name="responsibility_vocabulary",
        ),
        CheckConstraint("priority BETWEEN 1 AND 999", name="priority_range"),
        Index(
            "ix_system_assignees_workspace_system_priority",
            "workspace_id",
            "system_id",
            "priority",
        ),
        {"schema": "platform"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    system_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    subject_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    responsibility: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ExternalServiceProfileModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    """Redacted external-service connection intent; secret material is never persisted here."""

    __tablename__ = "external_service_profiles"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "service_key"),
        ForeignKeyConstraint(
            ("workspace_id", "updated_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_external_service_profiles_updater",
        ),
        CheckConstraint(
            "service_key IN ('DATAHUB', 'AIRFLOW', 'PROMETHEUS', 'NEO4J')",
            name="service_key_vocabulary",
        ),
        CheckConstraint("endpoint_url ~ '^https?://'", name="endpoint_url_scheme"),
        CheckConstraint(
            "secret_reference IS NULL OR length(trim(secret_reference)) > 0",
            name="secret_reference_present",
        ),
        Index("ix_external_service_profiles_workspace_active", "workspace_id", "active"),
        {"schema": "platform"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("platform.workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    service_key: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    endpoint_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    auth_principal: Mapped[str | None] = mapped_column(String(255))
    secret_reference: Mapped[str | None] = mapped_column(String(512))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)


class AdminAccessRequestModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "admin_access_requests"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        ForeignKeyConstraint(
            ["workspace_id", "target_subject_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_admin_access_requests_target_membership",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "requester_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_admin_access_requests_requester_membership",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "checker_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_admin_access_requests_checker_membership",
        ),
        CheckConstraint(
            "command_type = 'WORKSPACE_MEMBERSHIP_ACCESS_UPDATE_V1'",
            name="typed_command",
        ),
        CheckConstraint(
            "state IN ('PENDING', 'APPROVED', 'REJECTED', 'CONSUMED')",
            name="state",
        ),
        CheckConstraint(
            "payload_hash ~ '^[0-9a-f]{64}$'",
            name="payload_hash_sha256",
        ),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("expires_at > created_at", name="expiry_after_create"),
        CheckConstraint(
            "requester_id <> target_subject_id",
            name="no_self_benefit",
        ),
        CheckConstraint(
            "checker_id IS NULL OR "
            "(checker_id <> requester_id AND checker_id <> target_subject_id)",
            name="independent_checker",
        ),
        CheckConstraint(
            "consumed_by IS NULL OR consumed_by = requester_id",
            name="maker_consumes",
        ),
        CheckConstraint(
            "(state = 'PENDING' AND checker_id IS NULL AND consumed_by IS NULL "
            "AND consumed_at IS NULL AND consume_policy_decision_id IS NULL) OR "
            "(state IN ('APPROVED', 'REJECTED') AND checker_id IS NOT NULL "
            "AND consumed_by IS NULL AND consumed_at IS NULL "
            "AND consume_policy_decision_id IS NULL) OR "
            "(state = 'CONSUMED' AND checker_id IS NOT NULL "
            "AND consumed_by = requester_id AND consumed_at IS NOT NULL "
            "AND consume_policy_decision_id IS NOT NULL)",
            name="state_shape",
        ),
        Index("ix_admin_access_requests_workspace_state", "workspace_id", "state", "expires_at"),
        {"schema": "iam"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    requester_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    request_reason: Mapped[str] = mapped_column(String(4000), nullable=False)
    request_policy_decision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    target_subject_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    command_type: Mapped[str] = mapped_column(String(100), nullable=False)
    command_document: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    checker_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    consumed_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    consumed_at: Mapped[datetime | None]
    consume_policy_decision_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))


class AdminAccessApprovalModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "admin_access_approvals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "access_request_id"],
            ["iam.admin_access_requests.workspace_id", "iam.admin_access_requests.id"],
            ondelete="CASCADE",
            name="fk_admin_access_approvals_request",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "actor_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_admin_access_approvals_actor_membership",
        ),
        UniqueConstraint(
            "workspace_id",
            "access_request_id",
            "actor_id",
            name="uq_admin_access_approvals_request_actor",
        ),
        CheckConstraint(
            "decision IN ('APPROVED', 'REJECTED')",
            name="decision",
        ),
        CheckConstraint(
            "payload_hash ~ '^[0-9a-f]{64}$'",
            name="payload_hash_sha256",
        ),
        CheckConstraint("request_version > 0", name="version_positive"),
        Index("ix_admin_access_approvals_workspace_request", "workspace_id", "access_request_id"),
        {"schema": "iam"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    access_request_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(4000), nullable=False)
    policy_decision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_version: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)
