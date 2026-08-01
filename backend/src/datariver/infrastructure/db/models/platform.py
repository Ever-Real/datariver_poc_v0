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
    text,
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


class MonitoringConfigurationModel(Base, TimestampMixin, VersionMixin):
    """Workspace-owned, non-secret Grafana tab presentation configuration."""

    __tablename__ = "monitoring_configurations"
    __table_args__ = (
        ForeignKeyConstraint(
            ("workspace_id", "updated_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_monitoring_configurations_updater",
        ),
        CheckConstraint("jsonb_typeof(dashboards) = 'array'", name="dashboards_array"),
        CheckConstraint("jsonb_array_length(dashboards) <= 8", name="dashboards_bounded"),
        CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="payload_hash_sha256"),
        CheckConstraint("version > 0", name="version_positive"),
        {"schema": "platform"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("platform.workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    )
    dashboards: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)


class SubjectModel(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "subjects"
    __table_args__ = (
        UniqueConstraint("issuer", "external_subject"),
        Index(
            "ix_subjects_display_name_lower_id",
            text("lower(display_name)"),
            "id",
        ),
        {"schema": "iam"},
    )

    issuer: Mapped[str] = mapped_column(String(500), nullable=False)
    external_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    last_login_at: Mapped[datetime | None] = mapped_column()
    last_login_ip: Mapped[str | None] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class WorkspaceMembershipModel(Base, TimestampMixin, VersionMixin):
    __tablename__ = "workspace_memberships"
    __table_args__ = ({"schema": "iam"},)

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
    # Human memberships expire and are renewed; service accounts use an operator-managed
    # lifecycle and therefore retain a NULL expiry rather than a fabricated far-future date.
    access_expires_at: Mapped[datetime | None]


class MembershipRenewalRequestModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    """A self-requested, independently approved six-month membership extension."""

    __tablename__ = "membership_renewal_requests"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        ForeignKeyConstraint(
            ("workspace_id", "target_subject_id"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_membership_renewals_target_membership",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "requester_id"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_membership_renewals_requester_membership",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "checker_id"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_membership_renewals_checker_membership",
        ),
        CheckConstraint("requester_id = target_subject_id", name="self_request"),
        CheckConstraint("state IN ('PENDING', 'APPROVED', 'REJECTED')", name="state"),
        CheckConstraint("requested_expires_at > current_expires_at", name="extension_positive"),
        CheckConstraint(
            "checker_id IS NULL OR checker_id <> target_subject_id",
            name="independent_checker",
        ),
        CheckConstraint(
            "(state = 'PENDING' AND checker_id IS NULL AND decision_reason IS NULL "
            "AND decision_policy_decision_id IS NULL AND decided_at IS NULL) OR "
            "(state IN ('APPROVED', 'REJECTED') AND checker_id IS NOT NULL "
            "AND decision_reason IS NOT NULL AND decision_policy_decision_id IS NOT NULL "
            "AND decided_at IS NOT NULL)",
            name="state_shape",
        ),
        Index(
            "ix_membership_renewals_workspace_state_created",
            "workspace_id",
            "state",
            "created_at",
        ),
        Index(
            "uq_membership_renewals_pending_subject",
            "workspace_id",
            "target_subject_id",
            unique=True,
            postgresql_where=text("state = 'PENDING'"),
        ),
        {"schema": "iam"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("platform.workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_subject_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    requester_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(4000), nullable=False)
    current_expires_at: Mapped[datetime] = mapped_column(nullable=False)
    requested_expires_at: Mapped[datetime] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    checker_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    decision_reason: Mapped[str | None] = mapped_column(String(4000))
    decision_policy_decision_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    decided_at: Mapped[datetime | None]


class AccessRoleModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    """Workspace-owned RBAC template materialized through governed membership updates."""

    __tablename__ = "access_roles"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "id", "role_kind"),
        UniqueConstraint("workspace_id", "role_key"),
        ForeignKeyConstraint(
            ("workspace_id", "updated_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_access_roles_updater",
        ),
        CheckConstraint("role_key ~ '^[a-z][a-z0-9-]{1,79}$'", name="role_key_shape"),
        CheckConstraint("clearance BETWEEN 0 AND 3", name="clearance_range"),
        CheckConstraint(
            "role_kind IN ('HUMAN_ROLE', 'CANONICAL_ADMIN')",
            name="role_kind_vocabulary",
        ),
        CheckConstraint(
            "management_source IN ('HUMAN_ADMIN', 'SERVER_CANONICAL')",
            name="management_source_vocabulary",
        ),
        CheckConstraint(
            "(role_kind = 'HUMAN_ROLE' AND management_source = 'HUMAN_ADMIN' "
            "AND capability_catalog_version IS NULL AND updated_by IS NOT NULL) OR "
            "(role_kind = 'CANONICAL_ADMIN' AND management_source = 'SERVER_CANONICAL' "
            "AND role_key = 'canonical-admin' AND capability_catalog_version IS NOT NULL "
            "AND updated_by IS NULL AND active IS TRUE AND clearance = 3)",
            name="management_shape",
        ),
        Index("ix_access_roles_workspace_active_name", "workspace_id", "active", "name"),
        Index(
            "uq_access_roles_workspace_canonical_admin",
            "workspace_id",
            unique=True,
            postgresql_where=text("role_kind = 'CANONICAL_ADMIN'"),
        ),
        {"schema": "iam"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("platform.workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    role_key: Mapped[str] = mapped_column(String(80), nullable=False)
    role_kind: Mapped[str] = mapped_column(
        String(32), default="HUMAN_ROLE", server_default="HUMAN_ROLE", nullable=False
    )
    management_source: Mapped[str] = mapped_column(
        String(32), default="HUMAN_ADMIN", server_default="HUMAN_ADMIN", nullable=False
    )
    capability_catalog_version: Mapped[str | None] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    clearance: Mapped[int] = mapped_column(Integer, nullable=False)
    groups: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    allowed_actions: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    denied_actions: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    allowed_system_ids: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    allowed_domain_ids: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))


class AccessRoleDataRuleModel(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """Immutable policy-book rule bound to one exact access-role version."""

    __tablename__ = "access_role_data_rules"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "role_id", "role_version", "classification"),
        ForeignKeyConstraint(
            ("workspace_id", "role_id"),
            ("iam.access_roles.workspace_id", "iam.access_roles.id"),
            ondelete="RESTRICT",
            name="fk_access_role_data_rules_role",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "created_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_access_role_data_rules_creator",
        ),
        CheckConstraint("role_version > 0", name="role_version_positive"),
        CheckConstraint("classification BETWEEN 0 AND 3", name="classification_range"),
        CheckConstraint(
            "access_level IN ('NO_ACCESS', 'PARTIAL_ACCESS', 'FULL_ACCESS')",
            name="access_level_vocabulary",
        ),
        CheckConstraint(
            "partial_treatment IS NULL OR partial_treatment IN ('MASK', 'REDACT', 'TOKENIZE')",
            name="partial_treatment_vocabulary",
        ),
        CheckConstraint(
            "(access_level = 'PARTIAL_ACCESS' AND partial_treatment IS NOT NULL) OR "
            "(access_level <> 'PARTIAL_ACCESS' AND partial_treatment IS NULL)",
            name="access_treatment_shape",
        ),
        CheckConstraint(
            "jsonb_typeof(allowed_residency_regions) = 'array' AND "
            "jsonb_typeof(allowed_processing_purposes) = 'array'",
            name="scope_arrays",
        ),
        CheckConstraint(
            "(access_level = 'NO_ACCESS' AND "
            "jsonb_array_length(allowed_residency_regions) = 0 AND "
            "jsonb_array_length(allowed_processing_purposes) = 0) OR "
            "(access_level <> 'NO_ACCESS' AND "
            "jsonb_array_length(allowed_residency_regions) > 0 AND "
            "jsonb_array_length(allowed_processing_purposes) > 0)",
            name="access_scope_shape",
        ),
        CheckConstraint(
            "jsonb_array_length(jsonb_path_query_array(allowed_residency_regions, "
            '\'$[*] ? (@.type() == "string" && '
            '@ like_regex "^[A-Z0-9][A-Z0-9._:-]{0,63}$")\')) = '
            "jsonb_array_length(allowed_residency_regions) AND "
            "allowed_processing_purposes <@ "
            '\'["METADATA_READ", "DATA_READ", "EXPORT", "ANALYTICS", '
            '"MODEL_TRAINING"]\'::jsonb',
            name="scope_item_vocabulary",
        ),
        CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="payload_hash_sha256"),
        Index(
            "ix_access_role_data_rules_workspace_role_version",
            "workspace_id",
            "role_id",
            "role_version",
        ),
        {
            "schema": "iam",
            "comment": "Missing classification rule resolves to ROLE_DATA_RULE_MISSING (deny)",
        },
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("platform.workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    role_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    role_version: Mapped[int] = mapped_column(Integer, nullable=False)
    classification: Mapped[int] = mapped_column(Integer, nullable=False)
    access_level: Mapped[str] = mapped_column(String(24), nullable=False)
    partial_treatment: Mapped[str | None] = mapped_column(String(24))
    allowed_residency_regions: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    allowed_processing_purposes: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)


class AccessRoleAssignmentModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    """Current normalized role assignment; membership ABAC remains runtime authority."""

    __tablename__ = "access_role_assignments"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "subject_id"),
        ForeignKeyConstraint(
            ("workspace_id", "subject_id"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_access_role_assignments_membership",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "role_id", "role_kind"),
            (
                "iam.access_roles.workspace_id",
                "iam.access_roles.id",
                "iam.access_roles.role_kind",
            ),
            ondelete="RESTRICT",
            name="fk_access_role_assignments_role",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "assigned_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_access_role_assignments_actor",
        ),
        CheckConstraint("role_version > 0", name="role_version_positive"),
        CheckConstraint("role_kind = 'HUMAN_ROLE'", name="human_role_only"),
        CheckConstraint("membership_version > 0", name="membership_version_positive"),
        CheckConstraint("access_payload_hash ~ '^[0-9a-f]{64}$'", name="payload_hash_sha256"),
        Index("ix_access_role_assignments_workspace_role", "workspace_id", "role_id", "active"),
        {"schema": "iam"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("platform.workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    subject_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    role_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    role_kind: Mapped[str] = mapped_column(
        String(32), default="HUMAN_ROLE", server_default="HUMAN_ROLE", nullable=False
    )
    role_version: Mapped[int] = mapped_column(Integer, nullable=False)
    membership_version: Mapped[int] = mapped_column(Integer, nullable=False)
    access_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    assigned_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class CanonicalAdminBindingModel(Base, TimestampMixin, VersionMixin):
    """Development-only protected capability evidence, never a Role assignment."""

    __tablename__ = "canonical_admin_bindings"
    __table_args__ = (
        ForeignKeyConstraint(
            ("workspace_id", "subject_id"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_canonical_admin_bindings_membership",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "canonical_role_id", "role_kind"),
            (
                "iam.access_roles.workspace_id",
                "iam.access_roles.id",
                "iam.access_roles.role_kind",
            ),
            ondelete="RESTRICT",
            name="fk_canonical_admin_bindings_role",
        ),
        CheckConstraint("role_kind = 'CANONICAL_ADMIN'", name="canonical_role_only"),
        CheckConstraint(
            "binding_source IN ('LOCAL_DEVELOPMENT_BOOTSTRAP', 'GOVERNED_ADMIN_ASSIGNMENT')",
            name="binding_source_vocabulary",
        ),
        CheckConstraint("state IN ('ACTIVE', 'REVOKED')", name="state_vocabulary"),
        CheckConstraint("canonical_role_version > 0", name="role_version_positive"),
        CheckConstraint("membership_version > 0", name="membership_version_positive"),
        CheckConstraint("capability_hash ~ '^[0-9a-f]{64}$'", name="capability_hash_sha256"),
        CheckConstraint("membership_access_hash ~ '^[0-9a-f]{64}$'", name="access_hash_sha256"),
        {"schema": "iam"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("platform.workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    )
    subject_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    canonical_role_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    role_kind: Mapped[str] = mapped_column(
        String(32), default="CANONICAL_ADMIN", server_default="CANONICAL_ADMIN", nullable=False
    )
    canonical_role_version: Mapped[int] = mapped_column(Integer, nullable=False)
    capability_catalog_version: Mapped[str] = mapped_column(String(100), nullable=False)
    capability_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    membership_version: Mapped[int] = mapped_column(Integer, nullable=False)
    membership_access_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False)
    binding_source: Mapped[str] = mapped_column(
        String(64), default="LOCAL_DEVELOPMENT_BOOTSTRAP", nullable=False
    )


class ProfileRoleAssignmentModel(Base, TimestampMixin, VersionMixin):
    """Current server-managed actions-only profile Role assignment."""

    __tablename__ = "profile_role_assignments"
    __table_args__ = (
        ForeignKeyConstraint(
            ("workspace_id", "subject_id"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_profile_role_assignments_membership",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "assigned_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_profile_role_assignments_actor",
        ),
        CheckConstraint(
            "tier IN ('VIEWER', 'ENGINEER_STEWARD', 'MANAGER')",
            name="tier_vocabulary",
        ),
        CheckConstraint("state IN ('ACTIVE', 'REVOKED')", name="state_vocabulary"),
        CheckConstraint("policy_version = 'PROFILE_ROLE_POLICY_V1'", name="policy_version"),
        CheckConstraint("membership_version > 0", name="membership_version_positive"),
        CheckConstraint(
            "materialized_actions_hash ~ '^[0-9a-f]{64}$'",
            name="actions_hash_sha256",
        ),
        CheckConstraint("char_length(trim(reason)) BETWEEN 1 AND 4000", name="reason_bounded"),
        CheckConstraint(
            "assurance IN ('PASSWORD_REAUTH', 'HARDWARE_WEBAUTHN')",
            name="assurance_vocabulary",
        ),
        Index("ix_profile_role_assignments_workspace_tier", "workspace_id", "tier", "state"),
        {"schema": "iam"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("platform.workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    )
    subject_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tier: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    materialized_actions_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    membership_version: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    assigned_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    assurance: Mapped[str] = mapped_column(String(32), nullable=False)


class ProfileRoleAssignmentEventModel(Base, UuidPrimaryKeyMixin):
    """Append-only profile Role and Canonical Admin transition evidence."""

    __tablename__ = "profile_role_assignment_events"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        ForeignKeyConstraint(
            ("workspace_id", "subject_id"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_profile_role_assignment_events_membership",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "actor_id"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_profile_role_assignment_events_actor",
        ),
        CheckConstraint(
            "event_type IN ('ASSIGNED', 'CHANGED', 'PROMOTED_TO_ADMIN', 'DEMOTED_FROM_ADMIN')",
            name="event_type_vocabulary",
        ),
        CheckConstraint(
            "previous_tier IS NULL OR previous_tier IN "
            "('VIEWER', 'ENGINEER_STEWARD', 'MANAGER', 'ADMIN')",
            name="previous_tier_vocabulary",
        ),
        CheckConstraint(
            "next_tier IN ('VIEWER', 'ENGINEER_STEWARD', 'MANAGER', 'ADMIN')",
            name="next_tier_vocabulary",
        ),
        CheckConstraint("policy_version = 'PROFILE_ROLE_POLICY_V1'", name="policy_version"),
        CheckConstraint("membership_version > 0", name="membership_version_positive"),
        CheckConstraint("assignment_version > 0", name="assignment_version_positive"),
        CheckConstraint("char_length(trim(reason)) BETWEEN 1 AND 4000", name="reason_bounded"),
        CheckConstraint(
            "assurance IN ('PASSWORD_REAUTH', 'HARDWARE_WEBAUTHN')",
            name="assurance_vocabulary",
        ),
        Index(
            "ix_profile_role_assignment_events_workspace_subject_occurred",
            "workspace_id",
            "subject_id",
            "occurred_at",
        ),
        {"schema": "iam"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("platform.workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    subject_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_tier: Mapped[str | None] = mapped_column(String(32))
    next_tier: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    membership_version: Mapped[int] = mapped_column(Integer, nullable=False)
    assignment_version: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    policy_decision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    assurance: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )


class AccessRoleAssignmentEventModel(Base, UuidPrimaryKeyMixin):
    """Append-only evidence for assignment, reassignment, and removal."""

    __tablename__ = "access_role_assignment_events"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        ForeignKeyConstraint(
            ("workspace_id", "subject_id"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_access_role_assignment_events_membership",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "actor_id"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_access_role_assignment_events_actor",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "previous_role_id"),
            ("iam.access_roles.workspace_id", "iam.access_roles.id"),
            ondelete="RESTRICT",
            name="fk_access_role_assignment_events_previous_role",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "role_id"),
            ("iam.access_roles.workspace_id", "iam.access_roles.id"),
            ondelete="RESTRICT",
            name="fk_access_role_assignment_events_role",
        ),
        CheckConstraint("event_type IN ('ASSIGNED', 'REASSIGNED', 'REMOVED')", name="event_type"),
        CheckConstraint(
            "(event_type = 'ASSIGNED' AND previous_role_id IS NULL "
            "AND previous_role_version IS NULL AND role_id IS NOT NULL "
            "AND role_version IS NOT NULL) OR "
            "(event_type = 'REASSIGNED' AND previous_role_id IS NOT NULL "
            "AND previous_role_version IS NOT NULL AND role_id IS NOT NULL "
            "AND role_version IS NOT NULL) OR "
            "(event_type = 'REMOVED' AND previous_role_id IS NOT NULL "
            "AND previous_role_version IS NOT NULL AND role_id IS NULL "
            "AND role_version IS NULL)",
            name="state_shape",
        ),
        CheckConstraint("membership_version > 0", name="membership_version_positive"),
        CheckConstraint(
            "(previous_role_version IS NULL OR previous_role_version > 0) AND "
            "(role_version IS NULL OR role_version > 0)",
            name="role_versions_positive",
        ),
        CheckConstraint("access_payload_hash ~ '^[0-9a-f]{64}$'", name="payload_hash_sha256"),
        Index(
            "ix_access_role_assignment_events_workspace_subject_occurred",
            "workspace_id",
            "subject_id",
            "occurred_at",
        ),
        {"schema": "iam"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("platform.workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    subject_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    previous_role_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    previous_role_version: Mapped[int | None] = mapped_column(Integer)
    role_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    role_version: Mapped[int | None] = mapped_column(Integer)
    membership_version: Mapped[int] = mapped_column(Integer, nullable=False)
    access_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )


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
        Index(
            "ix_system_assignees_workspace_system_id",
            "workspace_id",
            "system_id",
            "id",
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
    """Workspace-scoped external-service configuration with an explicit development boundary."""

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
            "service_key IN ('DATAHUB', 'DATAHUB_FRONTEND', 'AIRFLOW', 'REDIS_CACHE', "
            "'REDIS_DELIVERY', 'S3_STORAGE', "
            "'LLM_CHAT_MODEL', 'LLM_EMBEDDING', 'LLM_RERANKER', 'NEO4J', 'PROMETHEUS', "
            "'GRAFANA_DASHBOARD')",
            name="service_key_vocabulary",
        ),
        CheckConstraint("endpoint_url ~ '^(https?|redis|rediss)://'", name="endpoint_url_scheme"),
        CheckConstraint(
            "secret_reference IS NULL OR length(trim(secret_reference)) > 0",
            name="secret_reference_present",
        ),
        CheckConstraint(
            "activated_version IS NULL OR (activated_version > 0 AND activated_version <= version)",
            name="activated_version_range",
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
    endpoint_url: Mapped[str | None] = mapped_column(String(2048))
    auth_principal: Mapped[str | None] = mapped_column(String(255))
    secret_reference: Mapped[str | None] = mapped_column(String(512))
    configuration_yaml: Mapped[str] = mapped_column(Text, default="", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    activated_version: Mapped[int | None] = mapped_column(Integer)
    updated_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)


class ExternalServiceProfileVersionModel(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """Immutable configuration revision plus TEST and activation evidence."""

    __tablename__ = "external_service_profile_versions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "profile_id", "configuration_version"),
        ForeignKeyConstraint(
            ("workspace_id", "profile_id"),
            (
                "platform.external_service_profiles.workspace_id",
                "platform.external_service_profiles.id",
            ),
            ondelete="CASCADE",
            name="fk_external_service_profile_versions_profile",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "created_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_external_service_profile_versions_creator",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "tested_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_external_service_profile_versions_tester",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "activated_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_external_service_profile_versions_activator",
        ),
        CheckConstraint("configuration_version > 0", name="configuration_version_positive"),
        CheckConstraint("configuration_hash ~ '^[0-9a-f]{64}$'", name="configuration_hash_sha256"),
        CheckConstraint(
            "test_status IS NULL OR test_status IN "
            "('AVAILABLE', 'AUTHENTICATION_REQUIRED', 'UNAVAILABLE')",
            name="test_status_vocabulary",
        ),
        CheckConstraint(
            "test_scope IS NULL OR test_scope IN "
            "('HTTP_HEALTH', 'MODEL_DISCOVERY', 'MODEL_INFERENCE', "
            "'EMBEDDING_INFERENCE', 'RERANKING_INFERENCE', "
            "'AUTHENTICATED_QUERY', 'REDIS_PING', "
            "'REDIS_POLICY', 'S3_HEAD_BUCKET')",
            name="test_scope_vocabulary",
        ),
        CheckConstraint(
            "test_latency_ms IS NULL OR test_latency_ms >= 0", name="latency_non_negative"
        ),
        CheckConstraint(
            "(test_status IS NULL AND test_scope IS NULL AND test_latency_ms IS NULL "
            "AND tested_at IS NULL AND tested_by IS NULL) OR "
            "(test_status IS NOT NULL AND test_scope IS NOT NULL AND test_latency_ms IS NOT NULL "
            "AND tested_at IS NOT NULL AND tested_by IS NOT NULL)",
            name="test_evidence_shape",
        ),
        CheckConstraint(
            "(activated_at IS NULL AND activated_by IS NULL) OR "
            "(activated_at IS NOT NULL AND activated_by IS NOT NULL AND test_status = 'AVAILABLE')",
            name="activation_evidence_shape",
        ),
        Index(
            "ix_external_service_profile_versions_workspace_profile",
            "workspace_id",
            "profile_id",
            "configuration_version",
        ),
        {"schema": "platform"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("platform.workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    profile_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    configuration_version: Mapped[int] = mapped_column(Integer, nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_yaml: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint_url: Mapped[str | None] = mapped_column(String(2048))
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    test_status: Mapped[str | None] = mapped_column(String(32))
    test_scope: Mapped[str | None] = mapped_column(String(32))
    test_latency_ms: Mapped[int | None] = mapped_column(Integer)
    tested_at: Mapped[datetime | None]
    tested_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    activated_at: Mapped[datetime | None]
    activated_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))


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
