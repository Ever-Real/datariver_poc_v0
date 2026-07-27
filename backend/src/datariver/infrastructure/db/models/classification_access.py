from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
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


class ClassificationAccessPolicyVersionModel(
    Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin
):
    __tablename__ = "classification_access_policy_versions"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "id", name="uq_classification_policy_versions_workspace_id"
        ),
        UniqueConstraint(
            "workspace_id",
            "id",
            "payload_hash",
            name="uq_classification_policy_versions_exact",
        ),
        UniqueConstraint(
            "workspace_id", "policy_number", name="uq_classification_policy_versions_number"
        ),
        ForeignKeyConstraint(
            ["workspace_id", "requester_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_classification_policy_versions_requester_membership",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "checker_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_classification_policy_versions_checker_membership",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "superseded_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_classification_policy_versions_superseder_membership",
        ),
        CheckConstraint("policy_number > 0", name="policy_number_positive"),
        CheckConstraint(
            "restricted_search_grant_maximum_days BETWEEN 1 AND 365",
            name="grant_maximum_days",
        ),
        CheckConstraint(
            "length(btrim(required_jurisdiction)) BETWEEN 1 AND 64", name="jurisdiction"
        ),
        CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="payload_hash_sha256"),
        CheckConstraint("state IN ('PROPOSED', 'ACTIVE', 'REJECTED', 'SUPERSEDED')", name="state"),
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
            "(state = 'PROPOSED' AND version = 1 AND checker_id IS NULL "
            "AND decision_reason IS NULL AND decision_policy_decision_id IS NULL "
            "AND decided_at IS NULL AND superseded_by IS NULL AND supersede_reason IS NULL "
            "AND supersede_policy_decision_id IS NULL AND superseded_at IS NULL) OR "
            "(state IN ('ACTIVE', 'REJECTED') AND version = 2 AND checker_id IS NOT NULL "
            "AND decision_reason IS NOT NULL AND decision_policy_decision_id IS NOT NULL "
            "AND decided_at IS NOT NULL AND superseded_by IS NULL AND supersede_reason IS NULL "
            "AND supersede_policy_decision_id IS NULL AND superseded_at IS NULL) OR "
            "(state = 'SUPERSEDED' AND version = 3 AND checker_id IS NOT NULL "
            "AND decision_reason IS NOT NULL AND decision_policy_decision_id IS NOT NULL "
            "AND decided_at IS NOT NULL AND superseded_by IS NOT NULL "
            "AND supersede_reason IS NOT NULL AND supersede_policy_decision_id IS NOT NULL "
            "AND superseded_at IS NOT NULL)",
            name="state_shape",
        ),
        Index(
            "uq_classification_policy_versions_workspace_active",
            "workspace_id",
            unique=True,
            postgresql_where=text("state = 'ACTIVE'"),
        ),
        Index(
            "ix_classification_policy_versions_workspace_number",
            "workspace_id",
            "policy_number",
        ),
        {"schema": "authz"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform.workspaces.id"), nullable=False
    )
    policy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    required_jurisdiction: Mapped[str] = mapped_column(String(64), nullable=False)
    restricted_search_grant_maximum_days: Mapped[int] = mapped_column(Integer, nullable=False)
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


class ClassificationAccessPolicyRuleModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "classification_access_policy_rules"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "policy_id", "policy_hash"],
            [
                "authz.classification_access_policy_versions.workspace_id",
                "authz.classification_access_policy_versions.id",
                "authz.classification_access_policy_versions.payload_hash",
            ],
            name="fk_classification_policy_rules_policy",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "provider_profile_version_id"],
            [
                "integration.inference_provider_profile_versions.workspace_id",
                "integration.inference_provider_profile_versions.id",
            ],
            name="fk_classification_policy_rules_provider_profile",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "embedding_provider_profile_version_id"],
            [
                "integration.inference_provider_profile_versions.workspace_id",
                "integration.inference_provider_profile_versions.id",
            ],
            name="fk_classification_policy_rules_embedding_profile",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "reranker_provider_profile_version_id"],
            [
                "integration.inference_provider_profile_versions.workspace_id",
                "integration.inference_provider_profile_versions.id",
            ],
            name="fk_classification_policy_rules_reranker_profile",
        ),
        UniqueConstraint(
            "workspace_id",
            "policy_id",
            "classification",
            name="uq_classification_policy_rules_classification",
        ),
        CheckConstraint("classification BETWEEN 0 AND 3", name="classification"),
        CheckConstraint(
            "search_mode IN ('ABAC', 'DENY', 'EXPLICIT_GRANT_ONLY')", name="search_mode"
        ),
        CheckConstraint(
            "chat_mode IN ('DENY', 'INTERNAL_APPROVED_ONLY', 'APPROVED_PROVIDER_ONLY')",
            name="chat_mode",
        ),
        CheckConstraint(
            "(chat_mode = 'DENY' AND provider_profile_version_id IS NULL "
            "AND embedding_provider_profile_version_id IS NULL "
            "AND reranker_provider_profile_version_id IS NULL) OR "
            "(chat_mode <> 'DENY' AND provider_profile_version_id IS NOT NULL)",
            name="provider_binding",
        ),
        CheckConstraint(
            "(classification = 3 AND search_mode IN ('DENY', 'EXPLICIT_GRANT_ONLY') "
            "AND chat_mode = 'DENY') OR "
            "(classification <> 3 AND search_mode <> 'EXPLICIT_GRANT_ONLY')",
            name="restricted_floor",
        ),
        CheckConstraint(
            "classification <> 2 OR chat_mode IN ('DENY', 'INTERNAL_APPROVED_ONLY')",
            name="confidential_chat_floor",
        ),
        Index("ix_classification_policy_rules_policy", "workspace_id", "policy_id"),
        {"schema": "authz"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform.workspaces.id"), nullable=False
    )
    policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    classification: Mapped[int] = mapped_column(Integer, nullable=False)
    search_mode: Mapped[str] = mapped_column(String(30), nullable=False)
    chat_mode: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_profile_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    embedding_provider_profile_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    reranker_provider_profile_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))


class RestrictedSearchGrantModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "restricted_search_grants"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_restricted_search_grants_workspace_id"),
        ForeignKeyConstraint(
            ["workspace_id", "classification_policy_id", "classification_policy_hash"],
            [
                "authz.classification_access_policy_versions.workspace_id",
                "authz.classification_access_policy_versions.id",
                "authz.classification_access_policy_versions.payload_hash",
            ],
            name="fk_restricted_search_grants_policy",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "subject_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_restricted_search_grants_subject_membership",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "requester_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_restricted_search_grants_requester_membership",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "checker_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_restricted_search_grants_checker_membership",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "revoked_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_restricted_search_grants_revoker_membership",
        ),
        CheckConstraint("scope IN ('RESOURCE', 'SYSTEM', 'DOMAIN')", name="scope"),
        CheckConstraint("expires_at > valid_from", name="validity_window"),
        CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="payload_hash_sha256"),
        CheckConstraint("classification_policy_hash ~ '^[0-9a-f]{64}$'", name="policy_hash_sha256"),
        CheckConstraint("state IN ('PENDING', 'ACTIVE', 'REJECTED', 'REVOKED')", name="state"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(
            "checker_id IS NULL OR checker_id <> requester_id", name="independent_checker"
        ),
        CheckConstraint(
            "checker_id IS NULL OR checker_id <> subject_id", name="subject_cannot_check"
        ),
        CheckConstraint(
            "length(btrim(purpose)) > 0 AND length(btrim(request_reason)) > 0 AND "
            "(decision_reason IS NULL OR length(btrim(decision_reason)) > 0) AND "
            "(revocation_reason IS NULL OR length(btrim(revocation_reason)) > 0)",
            name="reasons_nonempty",
        ),
        CheckConstraint(
            "(state = 'PENDING' AND version = 1 AND checker_id IS NULL "
            "AND decision_reason IS NULL AND decision_policy_decision_id IS NULL "
            "AND decided_at IS NULL AND revoked_by IS NULL AND revocation_reason IS NULL "
            "AND revocation_policy_decision_id IS NULL AND revoked_at IS NULL) OR "
            "(state IN ('ACTIVE', 'REJECTED') AND version = 2 AND checker_id IS NOT NULL "
            "AND decision_reason IS NOT NULL AND decision_policy_decision_id IS NOT NULL "
            "AND decided_at IS NOT NULL AND revoked_by IS NULL AND revocation_reason IS NULL "
            "AND revocation_policy_decision_id IS NULL AND revoked_at IS NULL) OR "
            "(state = 'REVOKED' AND version = 3 AND checker_id IS NOT NULL "
            "AND decision_reason IS NOT NULL AND decision_policy_decision_id IS NOT NULL "
            "AND decided_at IS NOT NULL AND revoked_by IS NOT NULL "
            "AND revocation_reason IS NOT NULL "
            "AND revocation_policy_decision_id IS NOT NULL AND revoked_at IS NOT NULL)",
            name="state_shape",
        ),
        Index(
            "ix_restricted_search_grants_subject_active",
            "workspace_id",
            "subject_id",
            "state",
            "expires_at",
        ),
        Index(
            "ix_restricted_search_grants_scope_active",
            "workspace_id",
            "scope",
            "scope_id",
            "state",
            "expires_at",
        ),
        Index(
            "ix_restricted_search_grants_workspace_created_id",
            "workspace_id",
            text("created_at DESC"),
            "id",
        ),
        {"schema": "authz"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform.workspaces.id"), nullable=False
    )
    classification_policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    classification_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    purpose: Mapped[str] = mapped_column(String(4000), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requester_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    request_reason: Mapped[str] = mapped_column(String(4000), nullable=False)
    request_policy_decision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    checker_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    decision_reason: Mapped[str | None] = mapped_column(String(4000))
    decision_policy_decision_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    decided_at: Mapped[datetime | None]
    revoked_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    revocation_reason: Mapped[str | None] = mapped_column(String(4000))
    revocation_policy_decision_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    revoked_at: Mapped[datetime | None]


class RestrictedSearchGrantEventModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "restricted_search_grant_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "grant_id"],
            ["authz.restricted_search_grants.workspace_id", "authz.restricted_search_grants.id"],
            name="fk_restricted_search_grant_events_grant",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "actor_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_restricted_search_grant_events_actor_membership",
        ),
        UniqueConstraint(
            "workspace_id", "grant_id", "grant_version", name="uq_grant_events_version"
        ),
        CheckConstraint("action IN ('PROPOSED', 'APPROVED', 'REJECTED', 'REVOKED')", name="action"),
        CheckConstraint("grant_version BETWEEN 1 AND 3", name="grant_version"),
        CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="payload_hash_sha256"),
        CheckConstraint("length(btrim(reason)) > 0", name="reason_nonempty"),
        Index("ix_restricted_search_grant_events_grant", "workspace_id", "grant_id", "occurred_at"),
        {"schema": "authz"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform.workspaces.id"), nullable=False
    )
    grant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(4000), nullable=False)
    policy_decision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)
    grant_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ClassificationAccessGenerationModel(Base):
    __tablename__ = "classification_access_generations"
    __table_args__ = (
        CheckConstraint("generation >= 0", name="generation_nonnegative"),
        {"schema": "authz"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("platform.workspaces.id"),
        primary_key=True,
    )
    generation: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)
