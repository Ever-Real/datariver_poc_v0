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
)
from sqlalchemy.orm import Mapped, mapped_column

from datariver.infrastructure.db.base import (
    Base,
    TimestampMixin,
    UuidPrimaryKeyMixin,
    VersionMixin,
)


class InferenceProviderProfileVersionModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "inference_provider_profile_versions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_inference_profile_versions_workspace_id"),
        UniqueConstraint(
            "workspace_id",
            "profile_key",
            "profile_version",
            name="uq_inference_profile_versions_key_version",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "maker_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_inference_profile_versions_maker_membership",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "checker_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_inference_profile_versions_checker_membership",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "revoked_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_inference_profile_versions_revoker_membership",
        ),
        CheckConstraint("profile_version > 0", name="profile_version_positive"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="payload_hash_sha256"),
        CheckConstraint("kind IN ('INTERNAL', 'EXTERNAL')", name="kind"),
        CheckConstraint("maximum_classification BETWEEN 0 AND 2", name="classification"),
        CheckConstraint(
            "kind <> 'EXTERNAL' OR maximum_classification <= 1",
            name="external_classification_floor",
        ),
        CheckConstraint("state IN ('PROPOSED', 'APPROVED', 'REJECTED', 'REVOKED')", name="state"),
        CheckConstraint(
            "residency_attestation_fingerprint ~ '^[0-9a-f]{64}$' AND "
            "zero_retention_attestation_fingerprint ~ '^[0-9a-f]{64}$'",
            name="attestation_hashes",
        ),
        CheckConstraint(
            "residency_attestation_expires_at > residency_attestation_observed_at AND "
            "zero_retention_attestation_expires_at > zero_retention_attestation_observed_at",
            name="attestation_windows",
        ),
        CheckConstraint("checker_id IS NULL OR checker_id <> maker_id", name="independent_checker"),
        CheckConstraint(
            "length(btrim(proposal_reason)) > 0 AND "
            "(decision_reason IS NULL OR length(btrim(decision_reason)) > 0) AND "
            "(revocation_reason IS NULL OR length(btrim(revocation_reason)) > 0)",
            name="reasons_nonempty",
        ),
        CheckConstraint(
            "profile_key !~ '://' AND server_route_key !~ '://' AND "
            "provider_identity !~ '://' AND model_identity !~ '://' AND "
            "deployment_identity !~ '://'",
            name="no_endpoint_values",
        ),
        CheckConstraint(
            "(state = 'PROPOSED' AND version = 1 AND checker_id IS NULL "
            "AND decision_reason IS NULL AND decision_policy_decision_id IS NULL "
            "AND decided_at IS NULL AND revoked_by IS NULL AND revocation_reason IS NULL "
            "AND revocation_policy_decision_id IS NULL AND revoked_at IS NULL) OR "
            "(state IN ('APPROVED', 'REJECTED') AND version = 2 AND checker_id IS NOT NULL "
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
            "ix_inference_profile_versions_workspace_state",
            "workspace_id",
            "state",
            "profile_key",
        ),
        {"schema": "integration"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform.workspaces.id"), nullable=False
    )
    profile_key: Mapped[str] = mapped_column(String(128), nullable=False)
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    server_route_key: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_identity: Mapped[str] = mapped_column(String(256), nullable=False)
    model_identity: Mapped[str] = mapped_column(String(256), nullable=False)
    deployment_identity: Mapped[str] = mapped_column(String(256), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(64), nullable=False)
    region: Mapped[str] = mapped_column(String(64), nullable=False)
    maximum_classification: Mapped[int] = mapped_column(Integer, nullable=False)
    residency_attestation_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    residency_attestation_observed_at: Mapped[datetime] = mapped_column(nullable=False)
    residency_attestation_expires_at: Mapped[datetime] = mapped_column(nullable=False)
    zero_retention_attestation_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    zero_retention_attestation_observed_at: Mapped[datetime] = mapped_column(nullable=False)
    zero_retention_attestation_expires_at: Mapped[datetime] = mapped_column(nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    maker_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    proposal_reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    proposal_policy_decision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    proposed_at: Mapped[datetime] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    checker_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    decision_reason: Mapped[str | None] = mapped_column(String(1000))
    decision_policy_decision_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    decided_at: Mapped[datetime | None]
    revoked_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    revocation_reason: Mapped[str | None] = mapped_column(String(1000))
    revocation_policy_decision_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    revoked_at: Mapped[datetime | None]


class InferenceProviderGenerationModel(Base):
    __tablename__ = "inference_provider_generations"
    __table_args__ = (
        CheckConstraint("generation >= 0", name="generation_nonnegative"),
        {"schema": "integration"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("platform.workspaces.id"),
        primary_key=True,
    )
    generation: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)
