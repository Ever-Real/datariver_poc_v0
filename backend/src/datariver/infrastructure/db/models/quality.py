from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
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

_HASH_CHECKS = (
    "target_binding_hash",
    "schema_hash",
    "source_connection_profile_hash",
    "workload_profile_hash",
    "compiler_hash",
    "score_policy_hash",
    "rule_retention_policy_hash",
    "rule_hold_hash",
)


def _sha256_checks(*columns: str) -> tuple[CheckConstraint, ...]:
    return tuple(
        CheckConstraint(f"{column} ~ '^[0-9a-f]{{64}}$'", name=f"{column}_sha256")
        for column in columns
    )


class QualityRuleSetModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "rule_sets"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_quality_rule_sets_workspace_id"),
        UniqueConstraint(
            "workspace_id",
            "id",
            "rule_retention_policy_id",
            "rule_retention_policy_number",
            "rule_retention_policy_hash",
            "rule_retain_until",
            "rule_hold_generation",
            "rule_hold_hash",
            name="uq_quality_rule_sets_rule_binding",
        ),
        UniqueConstraint("workspace_id", "asset_id", "name", name="uq_quality_rule_sets_name"),
        ForeignKeyConstraint(
            ["workspace_id", "asset_id"],
            ["catalog.assets_projection.workspace_id", "catalog.assets_projection.id"],
            name="fk_quality_rule_sets_asset",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "created_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_quality_rule_sets_creator",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "updated_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_quality_rule_sets_updater",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "workspace_id",
                "rule_retention_policy_id",
                "rule_retention_policy_hash",
                "rule_retention_policy_number",
            ],
            [
                "retention.policy_versions.workspace_id",
                "retention.policy_versions.id",
                "retention.policy_versions.payload_hash",
                "retention.policy_versions.policy_number",
            ],
            name="fk_quality_rule_sets_policy",
            ondelete="RESTRICT",
        ),
        CheckConstraint("state IN ('ACTIVE', 'ARCHIVED')", name="state"),
        CheckConstraint(
            "(state = 'ACTIVE' AND archived_at IS NULL) OR "
            "(state = 'ARCHIVED' AND archived_at IS NOT NULL)",
            name="state_shape",
        ),
        CheckConstraint("char_length(btrim(name)) BETWEEN 1 AND 255", name="name_bounded"),
        CheckConstraint("rule_retention_kind = 'QUALITY_RULE'", name="rule_retention_kind"),
        CheckConstraint("rule_retention_policy_number > 0", name="rule_policy_number"),
        CheckConstraint("rule_retain_until > rule_retention_basis_at", name="rule_deadline"),
        CheckConstraint("rule_hold_generation > 0", name="rule_hold_generation"),
        CheckConstraint("version > 0", name="version_positive"),
        *_sha256_checks("rule_retention_policy_hash", "rule_hold_hash"),
        Index("ix_quality_rule_sets_asset", "workspace_id", "asset_id", "state", "id"),
        Index(
            "ix_quality_rule_sets_list",
            "workspace_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
        {"schema": "quality"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform.workspaces.id"), nullable=False
    )
    asset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ACTIVE", server_default=text("'ACTIVE'")
    )
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    updated_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    archived_at: Mapped[datetime | None]
    rule_retention_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'QUALITY_RULE'")
    )
    rule_retention_policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    rule_retention_policy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_retention_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_retention_basis_at: Mapped[datetime] = mapped_column(nullable=False)
    rule_retain_until: Mapped[datetime] = mapped_column(nullable=False)
    rule_hold_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rule_hold_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class QualityRuleSetVersionModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "rule_set_versions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_quality_rule_versions_workspace_id"),
        UniqueConstraint(
            "workspace_id",
            "rule_set_id",
            "version_number",
            name="uq_quality_rule_versions_number",
        ),
        UniqueConstraint(
            "workspace_id",
            "id",
            "rule_retention_policy_id",
            "rule_retention_policy_number",
            "rule_retention_policy_hash",
            "rule_retain_until",
            "rule_hold_generation",
            "rule_hold_hash",
            name="uq_quality_rule_versions_rule_binding",
        ),
        UniqueConstraint(
            "workspace_id",
            "id",
            "rule_set_id",
            "asset_id",
            name="uq_quality_rule_versions_run_target",
        ),
        ForeignKeyConstraint(
            [
                "workspace_id",
                "rule_set_id",
                "rule_retention_policy_id",
                "rule_retention_policy_number",
                "rule_retention_policy_hash",
                "rule_retain_until",
                "rule_hold_generation",
                "rule_hold_hash",
            ],
            [
                "quality.rule_sets.workspace_id",
                "quality.rule_sets.id",
                "quality.rule_sets.rule_retention_policy_id",
                "quality.rule_sets.rule_retention_policy_number",
                "quality.rule_sets.rule_retention_policy_hash",
                "quality.rule_sets.rule_retain_until",
                "quality.rule_sets.rule_hold_generation",
                "quality.rule_sets.rule_hold_hash",
            ],
            name="fk_quality_rule_versions_rule_set",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "author_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_quality_rule_versions_author",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "reviewed_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_quality_rule_versions_reviewer",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "activated_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_quality_rule_versions_activator",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "revoked_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_quality_rule_versions_revoker",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "state IN ('PROPOSED', 'APPROVED', 'REJECTED', 'ACTIVE', 'SUPERSEDED', 'REVOKED')",
            name="state",
        ),
        CheckConstraint("version_number > 0", name="version_number_positive"),
        CheckConstraint("classification BETWEEN 0 AND 3", name="classification"),
        CheckConstraint("source_connection_profile_version > 0", name="connection_version"),
        CheckConstraint("workload_profile_version > 0", name="workload_version"),
        CheckConstraint("score_policy_version > 0", name="score_policy_version"),
        CheckConstraint("gx_version = '1.19.1'", name="gx_version"),
        CheckConstraint(
            "(schedule_mode = 'MANUAL_ONLY' AND schedule_profile_id IS NULL "
            "AND schedule_profile_version IS NULL AND schedule_profile_hash IS NULL) OR "
            "(schedule_mode = 'SCHEDULED' AND schedule_profile_id IS NOT NULL "
            "AND schedule_profile_version > 0 AND schedule_profile_hash IS NOT NULL)",
            name="schedule_binding",
        ),
        CheckConstraint(
            "reviewed_by IS NULL OR reviewed_by <> author_id", name="independent_reviewer"
        ),
        CheckConstraint(
            "activated_by IS NULL OR activated_by <> author_id", name="independent_activator"
        ),
        CheckConstraint(
            "(state = 'PROPOSED' AND reviewed_by IS NULL AND reviewed_at IS NULL "
            "AND activated_by IS NULL AND activated_at IS NULL "
            "AND revoked_by IS NULL AND revoked_at IS NULL) OR "
            "(state IN ('APPROVED', 'REJECTED') AND reviewed_by IS NOT NULL "
            "AND reviewed_at IS NOT NULL AND activated_by IS NULL AND activated_at IS NULL "
            "AND revoked_by IS NULL AND revoked_at IS NULL) OR "
            "(state IN ('ACTIVE', 'SUPERSEDED') AND reviewed_by IS NOT NULL "
            "AND reviewed_at IS NOT NULL AND activated_by IS NOT NULL "
            "AND activated_at IS NOT NULL AND revoked_by IS NULL AND revoked_at IS NULL) OR "
            "(state = 'REVOKED' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND activated_by IS NOT NULL AND activated_at IS NOT NULL "
            "AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL)",
            name="state_shape",
        ),
        CheckConstraint("rule_retention_kind = 'QUALITY_RULE'", name="rule_retention_kind"),
        CheckConstraint("rule_retention_policy_number > 0", name="rule_policy_number"),
        CheckConstraint("rule_retain_until > rule_retention_basis_at", name="rule_deadline"),
        CheckConstraint("rule_hold_generation > 0", name="rule_hold_generation"),
        CheckConstraint("version > 0", name="version_positive"),
        *_sha256_checks(*_HASH_CHECKS, "schedule_profile_hash"),
        Index(
            "uq_quality_rule_set_versions_active",
            "workspace_id",
            "rule_set_id",
            unique=True,
            postgresql_where=text("state = 'ACTIVE'"),
        ),
        Index(
            "ix_quality_rule_versions_history",
            "workspace_id",
            "rule_set_id",
            text("version_number DESC"),
            "id",
        ),
        {"schema": "quality"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform.workspaces.id"), nullable=False
    )
    rule_set_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    author_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PROPOSED", server_default=text("'PROPOSED'")
    )
    asset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    system_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    domain_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    classification: Mapped[int] = mapped_column(Integer, nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(50), nullable=False)
    source_version: Mapped[str] = mapped_column(String(255), nullable=False)
    target_binding_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_connection_profile_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_connection_profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_connection_profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    workload_profile_id: Mapped[str] = mapped_column(String(255), nullable=False)
    workload_profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    workload_profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    compiler_contract_version: Mapped[str] = mapped_column(String(100), nullable=False)
    gx_version: Mapped[str] = mapped_column(String(32), nullable=False)
    compiler_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    score_policy_id: Mapped[str] = mapped_column(String(255), nullable=False)
    score_policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    score_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schedule_mode: Mapped[str] = mapped_column(String(24), nullable=False)
    schedule_profile_id: Mapped[str | None] = mapped_column(String(255))
    schedule_profile_version: Mapped[int | None] = mapped_column(Integer)
    schedule_profile_hash: Mapped[str | None] = mapped_column(String(64))
    rule_retention_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'QUALITY_RULE'")
    )
    rule_retention_policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    rule_retention_policy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_retention_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_retention_basis_at: Mapped[datetime] = mapped_column(nullable=False)
    rule_retain_until: Mapped[datetime] = mapped_column(nullable=False)
    rule_hold_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rule_hold_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewed_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    reviewed_at: Mapped[datetime | None]
    activated_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    activated_at: Mapped[datetime | None]
    revoked_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    revoked_at: Mapped[datetime | None]


class QualityRuleDefinitionModel(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "rule_definitions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_quality_rule_defs_workspace_id"),
        UniqueConstraint(
            "workspace_id",
            "id",
            "rule_set_version_id",
            name="uq_quality_rule_defs_version_binding",
        ),
        UniqueConstraint(
            "workspace_id",
            "rule_set_version_id",
            "ordinal",
            name="uq_quality_rule_defs_ordinal",
        ),
        ForeignKeyConstraint(
            [
                "workspace_id",
                "rule_set_version_id",
                "rule_retention_policy_id",
                "rule_retention_policy_number",
                "rule_retention_policy_hash",
                "rule_retain_until",
                "rule_hold_generation",
                "rule_hold_hash",
            ],
            [
                "quality.rule_set_versions.workspace_id",
                "quality.rule_set_versions.id",
                "quality.rule_set_versions.rule_retention_policy_id",
                "quality.rule_set_versions.rule_retention_policy_number",
                "quality.rule_set_versions.rule_retention_policy_hash",
                "quality.rule_set_versions.rule_retain_until",
                "quality.rule_set_versions.rule_hold_generation",
                "quality.rule_set_versions.rule_hold_hash",
            ],
            name="fk_quality_rule_defs_version",
            ondelete="RESTRICT",
        ),
        CheckConstraint("ordinal > 0", name="ordinal_positive"),
        CheckConstraint("kind IN ('NOT_NULL', 'RANGE')", name="kind"),
        CheckConstraint("severity IN ('BLOCKING', 'ADVISORY')", name="severity"),
        CheckConstraint("char_length(field_identifier) BETWEEN 1 AND 255", name="field_bounded"),
        CheckConstraint("jsonb_typeof(parameters) = 'object'", name="parameters_object"),
        CheckConstraint(
            "(kind = 'NOT_NULL' AND parameters = '{}'::jsonb) OR "
            "(kind = 'RANGE' AND parameters ?& ARRAY["
            "'value_type','min_value','max_value','inclusive_min','inclusive_max'"
            "] AND parameters = jsonb_build_object("
            "'value_type', parameters -> 'value_type', "
            "'min_value', parameters -> 'min_value', "
            "'max_value', parameters -> 'max_value', "
            "'inclusive_min', parameters -> 'inclusive_min', "
            "'inclusive_max', parameters -> 'inclusive_max') "
            "AND parameters ->> 'value_type' IN ('DECIMAL','DATE','TIMESTAMP') "
            "AND jsonb_typeof(parameters -> 'min_value') = 'string' "
            "AND jsonb_typeof(parameters -> 'max_value') = 'string' "
            "AND jsonb_typeof(parameters -> 'inclusive_min') = 'boolean' "
            "AND jsonb_typeof(parameters -> 'inclusive_max') = 'boolean' "
            "AND char_length(parameters ->> 'min_value') BETWEEN 1 AND 100 "
            "AND char_length(parameters ->> 'max_value') BETWEEN 1 AND 100 "
            "AND CASE parameters ->> 'value_type' "
            "WHEN 'DECIMAL' THEN CASE "
            "WHEN parameters ->> 'min_value' ~ '^-?(0|[1-9][0-9]*)(\\.[0-9]+)?$' "
            "AND parameters ->> 'max_value' ~ '^-?(0|[1-9][0-9]*)(\\.[0-9]+)?$' "
            "THEN (parameters ->> 'min_value')::numeric "
            "<= (parameters ->> 'max_value')::numeric ELSE false END "
            "WHEN 'DATE' THEN CASE "
            "WHEN parameters ->> 'min_value' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' "
            "AND parameters ->> 'max_value' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' "
            "THEN (parameters ->> 'min_value')::date "
            "<= (parameters ->> 'max_value')::date ELSE false END "
            "WHEN 'TIMESTAMP' THEN CASE "
            "WHEN parameters ->> 'min_value' ~ "
            "'^[0-9]{4}-[0-9]{2}-[0-9]{2}T.+(Z|[+-][0-9]{2}:[0-9]{2})$' "
            "AND parameters ->> 'max_value' ~ "
            "'^[0-9]{4}-[0-9]{2}-[0-9]{2}T.+(Z|[+-][0-9]{2}:[0-9]{2})$' "
            "THEN (parameters ->> 'min_value')::timestamptz "
            "<= (parameters ->> 'max_value')::timestamptz ELSE false END "
            "ELSE false END)",
            name="typed_parameters",
        ),
        CheckConstraint("rule_retention_kind = 'QUALITY_RULE'", name="rule_retention_kind"),
        CheckConstraint("rule_hold_generation > 0", name="rule_hold_generation"),
        *_sha256_checks("definition_hash", "rule_retention_policy_hash", "rule_hold_hash"),
        {"schema": "quality"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform.workspaces.id"), nullable=False
    )
    rule_set_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    field_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    parameters: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_retention_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_retention_policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    rule_retention_policy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_retention_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_retain_until: Mapped[datetime] = mapped_column(nullable=False)
    rule_hold_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rule_hold_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class QualityRuleReviewModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "rule_reviews"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_quality_rule_reviews_workspace_id"),
        UniqueConstraint(
            "workspace_id",
            "rule_set_version_id",
            name="uq_quality_rule_reviews_version",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "rule_set_version_id"],
            ["quality.rule_set_versions.workspace_id", "quality.rule_set_versions.id"],
            name="fk_quality_rule_reviews_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "actor_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_quality_rule_reviews_actor",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "workspace_id",
                "audit_retention_policy_id",
                "audit_retention_policy_hash",
                "audit_retention_policy_number",
            ],
            [
                "retention.policy_versions.workspace_id",
                "retention.policy_versions.id",
                "retention.policy_versions.payload_hash",
                "retention.policy_versions.policy_number",
            ],
            name="fk_quality_rule_reviews_policy",
            ondelete="RESTRICT",
        ),
        CheckConstraint("decision IN ('APPROVE', 'REJECT')", name="decision"),
        CheckConstraint("char_length(btrim(reason)) BETWEEN 1 AND 4000", name="reason_bounded"),
        CheckConstraint("audit_retention_kind = 'QUALITY_AUDIT'", name="audit_kind"),
        CheckConstraint("audit_retain_until > audit_retention_basis_at", name="audit_deadline"),
        CheckConstraint("audit_hold_generation > 0", name="audit_hold_generation"),
        *_sha256_checks(
            "assurance_hash",
            "target_binding_hash",
            "audit_retention_policy_hash",
            "audit_hold_hash",
        ),
        Index(
            "ix_quality_rule_reviews_version_time",
            "workspace_id",
            "rule_set_version_id",
            "occurred_at",
            "id",
        ),
        {"schema": "quality"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform.workspaces.id"), nullable=False
    )
    rule_set_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(4000), nullable=False)
    policy_decision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    assurance_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    target_binding_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_retention_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    audit_retention_policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    audit_retention_policy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    audit_retention_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_retention_basis_at: Mapped[datetime] = mapped_column(nullable=False)
    audit_retain_until: Mapped[datetime] = mapped_column(nullable=False)
    audit_hold_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    audit_hold_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("transaction_timestamp()")
    )


class QualityRuleCommandEventModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "rule_command_events"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_quality_rule_commands_workspace_id"),
        UniqueConstraint(
            "workspace_id",
            "rule_set_id",
            "sequence",
            name="uq_quality_rule_commands_sequence",
        ),
        UniqueConstraint(
            "workspace_id",
            "rule_set_id",
            "idempotency_key_hash",
            name="uq_quality_rule_commands_idempotency",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "rule_set_id"],
            ["quality.rule_sets.workspace_id", "quality.rule_sets.id"],
            name="fk_quality_rule_commands_rule_set",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "rule_set_version_id"],
            ["quality.rule_set_versions.workspace_id", "quality.rule_set_versions.id"],
            name="fk_quality_rule_commands_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "actor_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_quality_rule_commands_actor",
            ondelete="RESTRICT",
        ),
        CheckConstraint("sequence > 0", name="sequence_positive"),
        CheckConstraint("command IN ('ACTIVATE','REVOKE','ARCHIVE','SUPERSEDE')", name="command"),
        CheckConstraint("actor_kind IN ('HUMAN','SERVICE')", name="actor_kind"),
        CheckConstraint(
            "(command IN ('ACTIVATE','REVOKE','SUPERSEDE') "
            "AND webauthn_evidence_hash IS NOT NULL "
            "AND authentication_time IS NOT NULL) OR "
            "(command NOT IN ('ACTIVATE','REVOKE','SUPERSEDE') "
            "AND webauthn_evidence_hash IS NULL AND authentication_time IS NULL)",
            name="webauthn_shape",
        ),
        CheckConstraint("audit_retention_kind = 'QUALITY_AUDIT'", name="audit_kind"),
        CheckConstraint("audit_hold_generation > 0", name="audit_hold_generation"),
        *_sha256_checks(
            "webauthn_evidence_hash",
            "authorization_hash",
            "target_binding_hash",
            "schedule_binding_hash",
            "retention_binding_hash",
            "request_hash",
            "idempotency_key_hash",
            "audit_retention_policy_hash",
            "audit_hold_hash",
        ),
        {"schema": "quality"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform.workspaces.id"), nullable=False
    )
    rule_set_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    rule_set_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    command: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    webauthn_evidence_hash: Mapped[str | None] = mapped_column(String(64))
    authentication_time: Mapped[datetime | None]
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    target_binding_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schedule_binding_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    retention_binding_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_retention_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    audit_retention_policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    audit_retention_policy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    audit_retention_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_retention_basis_at: Mapped[datetime] = mapped_column(nullable=False)
    audit_retain_until: Mapped[datetime] = mapped_column(nullable=False)
    audit_hold_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    audit_hold_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("transaction_timestamp()")
    )


class QualityRuleScheduleModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "rule_schedules"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_quality_rule_schedules_workspace_id"),
        UniqueConstraint(
            "workspace_id",
            "rule_set_version_id",
            name="uq_quality_rule_schedules_version",
        ),
        UniqueConstraint(
            "workspace_id",
            "id",
            "version",
            "rule_set_version_id",
            name="uq_quality_rule_schedules_run_binding",
        ),
        ForeignKeyConstraint(
            [
                "workspace_id",
                "rule_set_version_id",
                "rule_retention_policy_id",
                "rule_retention_policy_number",
                "rule_retention_policy_hash",
                "rule_retain_until",
                "rule_hold_generation",
                "rule_hold_hash",
            ],
            [
                "quality.rule_set_versions.workspace_id",
                "quality.rule_set_versions.id",
                "quality.rule_set_versions.rule_retention_policy_id",
                "quality.rule_set_versions.rule_retention_policy_number",
                "quality.rule_set_versions.rule_retention_policy_hash",
                "quality.rule_set_versions.rule_retain_until",
                "quality.rule_set_versions.rule_hold_generation",
                "quality.rule_set_versions.rule_hold_hash",
            ],
            name="fk_quality_rule_schedules_version",
            ondelete="RESTRICT",
        ),
        CheckConstraint("state IN ('ACTIVE','INACTIVE')", name="state"),
        CheckConstraint("schedule_profile_version > 0", name="profile_version"),
        CheckConstraint("jsonb_typeof(cadence) = 'object'", name="cadence_object"),
        CheckConstraint("late_grace_seconds BETWEEN 0 AND 86400", name="late_grace"),
        CheckConstraint(
            "missed_window_policy IN "
            "('SKIP_MISSED_V1','LATEST_ONLY_V1','CATCH_UP_OLDEST_FIRST_V1')",
            name="missed_window_policy",
        ),
        CheckConstraint("catch_up_cap BETWEEN 1 AND 100", name="catch_up_cap"),
        CheckConstraint("rule_retention_kind = 'QUALITY_RULE'", name="rule_kind"),
        CheckConstraint("rule_hold_generation > 0", name="rule_hold_generation"),
        CheckConstraint("version > 0", name="version_positive"),
        *_sha256_checks(
            "schedule_profile_hash",
            "cadence_hash",
            "tzdb_hash",
            "rule_retention_policy_hash",
            "rule_hold_hash",
        ),
        Index(
            "uq_quality_rule_schedules_active",
            "workspace_id",
            "rule_set_id",
            unique=True,
            postgresql_where=text("state = 'ACTIVE'"),
        ),
        Index(
            "ix_quality_rule_schedules_due",
            "workspace_id",
            "state",
            "next_due_at",
            "id",
            postgresql_where=text("state = 'ACTIVE'"),
        ),
        {"schema": "quality"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform.workspaces.id"), nullable=False
    )
    rule_set_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    rule_set_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    schedule_profile_id: Mapped[str] = mapped_column(String(255), nullable=False)
    schedule_profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    schedule_profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    cadence: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    cadence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    timezone_name: Mapped[str] = mapped_column(String(255), nullable=False)
    evaluator_contract_version: Mapped[str] = mapped_column(String(100), nullable=False)
    tzdb_version: Mapped[str] = mapped_column(String(100), nullable=False)
    tzdb_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    late_grace_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    missed_window_policy: Mapped[str] = mapped_column(String(40), nullable=False)
    catch_up_cap: Mapped[int] = mapped_column(Integer, nullable=False)
    next_due_at: Mapped[datetime | None]
    current_window_key: Mapped[str | None] = mapped_column(String(255))
    rule_retention_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_retention_policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    rule_retention_policy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_retention_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_retain_until: Mapped[datetime] = mapped_column(nullable=False)
    rule_hold_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rule_hold_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class QualityValidationRunModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "validation_runs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_quality_runs_workspace_id"),
        UniqueConstraint(
            "workspace_id",
            "schedule_id",
            "canonical_window_key",
            name="uq_quality_runs_schedule_window",
        ),
        UniqueConstraint(
            "workspace_id",
            "id",
            "result_retention_policy_id",
            "result_retention_policy_number",
            "result_retention_policy_hash",
            "result_retain_until",
            "result_hold_generation",
            "result_hold_hash",
            name="uq_quality_runs_result_binding",
        ),
        UniqueConstraint(
            "workspace_id",
            "id",
            "audit_retention_policy_id",
            "audit_retention_policy_number",
            "audit_retention_policy_hash",
            "audit_retain_until",
            "audit_hold_generation",
            "audit_hold_hash",
            name="uq_quality_runs_audit_binding",
        ),
        UniqueConstraint(
            "workspace_id",
            "id",
            "result_retention_policy_id",
            "result_retention_policy_number",
            "result_retention_policy_hash",
            "result_retain_until",
            "result_hold_generation",
            "result_hold_hash",
            "audit_retention_policy_id",
            "audit_retention_policy_number",
            "audit_retention_policy_hash",
            "audit_retain_until",
            "audit_hold_generation",
            "audit_hold_hash",
            name="uq_quality_runs_retention_binding",
        ),
        UniqueConstraint(
            "workspace_id",
            "id",
            "current_attempt_id",
            "state",
            "rule_set_version_id",
            "result_retention_policy_id",
            "result_retention_policy_number",
            "result_retention_policy_hash",
            "result_retain_until",
            "result_hold_generation",
            "result_hold_hash",
            name="uq_quality_runs_result_completion_binding",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "rule_set_version_id", "rule_set_id", "asset_id"],
            [
                "quality.rule_set_versions.workspace_id",
                "quality.rule_set_versions.id",
                "quality.rule_set_versions.rule_set_id",
                "quality.rule_set_versions.asset_id",
            ],
            name="fk_quality_runs_rule_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "schedule_id", "schedule_version", "rule_set_version_id"],
            [
                "quality.rule_schedules.workspace_id",
                "quality.rule_schedules.id",
                "quality.rule_schedules.version",
                "quality.rule_schedules.rule_set_version_id",
            ],
            name="fk_quality_runs_schedule",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "id", "current_attempt_id"],
            [
                "quality.validation_attempts.workspace_id",
                "quality.validation_attempts.run_id",
                "quality.validation_attempts.id",
            ],
            name="fk_quality_runs_current_attempt",
            ondelete="RESTRICT",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "retry_of_run_id"],
            ["quality.validation_runs.workspace_id", "quality.validation_runs.id"],
            name="fk_quality_runs_retry_parent",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "requested_by"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_quality_runs_requester",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "state IN ('QUEUED','RUNNING','RETRY_WAIT','CANCEL_REQUESTED',"
            "'SUCCEEDED','FAILED','STALE','CANCELLED')",
            name="state",
        ),
        CheckConstraint("trigger_kind IN ('MANUAL','SCHEDULED','RETRY')", name="trigger_kind"),
        CheckConstraint("quality_outcome IN ('PASS','WARN','FAIL','UNKNOWN')", name="outcome"),
        CheckConstraint(
            "(state = 'SUCCEEDED' AND quality_outcome IN ('PASS','WARN','FAIL') "
            "AND score BETWEEN 0 AND 100 AND completed_at IS NOT NULL) OR "
            "(state <> 'SUCCEEDED' AND quality_outcome = 'UNKNOWN' AND score IS NULL)",
            name="outcome_shape",
        ),
        CheckConstraint(
            "(trigger_kind = 'SCHEDULED' AND schedule_id IS NOT NULL "
            "AND schedule_version IS NOT NULL "
            "AND canonical_window_key IS NOT NULL AND due_at IS NOT NULL "
            "AND requested_by IS NULL) OR "
            "(trigger_kind <> 'SCHEDULED' AND schedule_id IS NULL AND schedule_version IS NULL "
            "AND canonical_window_key IS NULL AND due_at IS NULL)",
            name="trigger_shape",
        ),
        CheckConstraint("attempt_count >= 0 AND lease_epoch >= 0", name="counters"),
        CheckConstraint("maximum_attempts BETWEEN 1 AND 10", name="maximum_attempts"),
        CheckConstraint(
            "(state IN ('RUNNING','CANCEL_REQUESTED') AND current_attempt_id IS NOT NULL "
            "AND lease_token_hash IS NOT NULL AND lease_owner_fingerprint IS NOT NULL "
            "AND lease_until IS NOT NULL) OR "
            "(state NOT IN ('RUNNING','CANCEL_REQUESTED') AND lease_token_hash IS NULL "
            "AND lease_owner_fingerprint IS NULL AND lease_until IS NULL)",
            name="lease_shape",
        ),
        CheckConstraint("result_retention_kind = 'QUALITY_RESULT'", name="result_kind"),
        CheckConstraint("audit_retention_kind = 'QUALITY_AUDIT'", name="audit_kind"),
        CheckConstraint("result_hold_generation > 0", name="result_hold_generation"),
        CheckConstraint("audit_hold_generation > 0", name="audit_hold_generation"),
        CheckConstraint("version > 0", name="version_positive"),
        *_sha256_checks(
            "target_binding_hash",
            "schema_hash",
            "source_connection_profile_hash",
            "workload_profile_hash",
            "security_context_hash",
            "datahub_profile_context_hash",
            "score_policy_hash",
            "hard_timeout_contract_hash",
            "lease_token_hash",
            "result_retention_policy_hash",
            "result_hold_hash",
            "audit_retention_policy_hash",
            "audit_hold_hash",
        ),
        Index(
            "ix_quality_validation_runs_runnable",
            "workspace_id",
            "state",
            "next_attempt_at",
            "lease_until",
            "id",
            postgresql_where=text(
                "state IN ('QUEUED','RETRY_WAIT') OR "
                "(state IN ('RUNNING','CANCEL_REQUESTED') AND lease_until IS NOT NULL)"
            ),
        ),
        Index(
            "ix_quality_validation_runs_terminal_dashboard",
            "workspace_id",
            "rule_set_version_id",
            text("completed_at DESC"),
            text("id DESC"),
            postgresql_where=text("state IN ('SUCCEEDED','FAILED','STALE','CANCELLED')"),
        ),
        Index(
            "ix_quality_validation_runs_list",
            "workspace_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
        {"schema": "quality"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform.workspaces.id"), nullable=False
    )
    rule_set_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    rule_set_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    target_binding_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_connection_profile_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_connection_profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_connection_profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    workload_profile_id: Mapped[str] = mapped_column(String(255), nullable=False)
    workload_profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    workload_profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    security_context_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    datahub_profile_context_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    score_policy_id: Mapped[str] = mapped_column(String(255), nullable=False)
    score_policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    score_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    retry_of_run_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    trigger_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    schedule_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    schedule_version: Mapped[int | None] = mapped_column(Integer)
    canonical_window_key: Mapped[str | None] = mapped_column(String(255))
    due_at: Mapped[datetime | None]
    is_late: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    state: Mapped[str] = mapped_column(
        String(24), nullable=False, default="QUEUED", server_default=text("'QUEUED'")
    )
    quality_outcome: Mapped[str] = mapped_column(
        String(16), nullable=False, default="UNKNOWN", server_default=text("'UNKNOWN'")
    )
    score: Mapped[int | None] = mapped_column(Integer)
    passed_count: Mapped[int | None] = mapped_column(Integer)
    advisory_failed_count: Mapped[int | None] = mapped_column(Integer)
    blocking_failed_count: Mapped[int | None] = mapped_column(Integer)
    current_attempt_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    maximum_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(nullable=False)
    lease_epoch: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    lease_token_hash: Mapped[str | None] = mapped_column(String(64))
    lease_owner_fingerprint: Mapped[str | None] = mapped_column(String(255))
    lease_until: Mapped[datetime | None]
    heartbeat_at: Mapped[datetime | None]
    source_started_at: Mapped[datetime | None]
    source_access_deadline: Mapped[datetime | None]
    hard_timeout_contract_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    completed_at: Mapped[datetime | None]
    failure_code: Mapped[str | None] = mapped_column(String(100))
    result_retention_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    result_retention_policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    result_retention_policy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    result_retention_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_retention_basis_at: Mapped[datetime] = mapped_column(nullable=False)
    result_retain_until: Mapped[datetime] = mapped_column(nullable=False)
    result_hold_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    result_hold_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_retention_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    audit_retention_policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    audit_retention_policy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    audit_retention_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_retention_basis_at: Mapped[datetime] = mapped_column(nullable=False)
    audit_retain_until: Mapped[datetime] = mapped_column(nullable=False)
    audit_hold_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    audit_hold_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class QualityValidationAttemptModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "validation_attempts"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_quality_attempts_workspace_id"),
        UniqueConstraint(
            "workspace_id",
            "run_id",
            "id",
            name="uq_quality_attempts_current_binding",
        ),
        UniqueConstraint(
            "workspace_id",
            "id",
            "run_id",
            "lease_epoch",
            "lease_token_hash",
            "audit_retention_policy_id",
            "audit_retention_policy_number",
            "audit_retention_policy_hash",
            "audit_retain_until",
            "audit_hold_generation",
            "audit_hold_hash",
            name="uq_quality_attempts_execution_binding",
        ),
        UniqueConstraint("workspace_id", "run_id", "attempt_no", name="uq_quality_attempts_number"),
        UniqueConstraint("workspace_id", "run_id", "lease_epoch", name="uq_quality_attempts_epoch"),
        ForeignKeyConstraint(
            [
                "workspace_id",
                "run_id",
                "result_retention_policy_id",
                "result_retention_policy_number",
                "result_retention_policy_hash",
                "result_retain_until",
                "result_hold_generation",
                "result_hold_hash",
                "audit_retention_policy_id",
                "audit_retention_policy_number",
                "audit_retention_policy_hash",
                "audit_retain_until",
                "audit_hold_generation",
                "audit_hold_hash",
            ],
            [
                "quality.validation_runs.workspace_id",
                "quality.validation_runs.id",
                "quality.validation_runs.result_retention_policy_id",
                "quality.validation_runs.result_retention_policy_number",
                "quality.validation_runs.result_retention_policy_hash",
                "quality.validation_runs.result_retain_until",
                "quality.validation_runs.result_hold_generation",
                "quality.validation_runs.result_hold_hash",
                "quality.validation_runs.audit_retention_policy_id",
                "quality.validation_runs.audit_retention_policy_number",
                "quality.validation_runs.audit_retention_policy_hash",
                "quality.validation_runs.audit_retain_until",
                "quality.validation_runs.audit_hold_generation",
                "quality.validation_runs.audit_hold_hash",
            ],
            name="fk_quality_attempts_run",
            ondelete="RESTRICT",
        ),
        CheckConstraint("attempt_no > 0 AND lease_epoch > 0", name="attempt_epoch_positive"),
        CheckConstraint(
            "state IN ('RUNNING','SUCCEEDED','RETRYABLE_FAILED','FAILED',"
            "'STALE','CANCELLED','SUPERSEDED')",
            name="state",
        ),
        CheckConstraint(
            "(state = 'RUNNING' AND finished_at IS NULL) OR "
            "(state <> 'RUNNING' AND finished_at IS NOT NULL)",
            name="state_shape",
        ),
        *_sha256_checks(
            "lease_token_hash",
            "compiler_result_hash",
            "gx_result_hash",
            "normalized_result_hash",
            "result_retention_policy_hash",
            "result_hold_hash",
            "audit_retention_policy_hash",
            "audit_hold_hash",
        ),
        {"schema": "quality"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform.workspaces.id"), nullable=False
    )
    run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lease_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    worker_fingerprint: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(nullable=False)
    lease_until: Mapped[datetime] = mapped_column(nullable=False)
    source_started_at: Mapped[datetime | None]
    source_access_deadline: Mapped[datetime | None]
    compiler_result_hash: Mapped[str | None] = mapped_column(String(64))
    gx_result_hash: Mapped[str | None] = mapped_column(String(64))
    normalized_result_hash: Mapped[str | None] = mapped_column(String(64))
    failure_code: Mapped[str | None] = mapped_column(String(100))
    finished_at: Mapped[datetime | None]
    result_retention_policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    result_retention_policy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    result_retention_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_retain_until: Mapped[datetime] = mapped_column(nullable=False)
    result_hold_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    result_hold_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_retention_policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    audit_retention_policy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    audit_retention_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_retain_until: Mapped[datetime] = mapped_column(nullable=False)
    audit_hold_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    audit_hold_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class QualityExpectationResultModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "expectation_results"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_quality_results_workspace_id"),
        UniqueConstraint(
            "workspace_id",
            "run_id",
            "rule_definition_id",
            name="uq_quality_results_run_rule",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "rule_definition_id", "rule_set_version_id"],
            [
                "quality.rule_definitions.workspace_id",
                "quality.rule_definitions.id",
                "quality.rule_definitions.rule_set_version_id",
            ],
            name="fk_quality_results_rule",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "workspace_id",
                "run_id",
                "attempt_id",
                "run_state",
                "rule_set_version_id",
                "result_retention_policy_id",
                "result_retention_policy_number",
                "result_retention_policy_hash",
                "result_retain_until",
                "result_hold_generation",
                "result_hold_hash",
            ],
            [
                "quality.validation_runs.workspace_id",
                "quality.validation_runs.id",
                "quality.validation_runs.current_attempt_id",
                "quality.validation_runs.state",
                "quality.validation_runs.rule_set_version_id",
                "quality.validation_runs.result_retention_policy_id",
                "quality.validation_runs.result_retention_policy_number",
                "quality.validation_runs.result_retention_policy_hash",
                "quality.validation_runs.result_retain_until",
                "quality.validation_runs.result_hold_generation",
                "quality.validation_runs.result_hold_hash",
            ],
            name="fk_quality_results_run",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("run_state = 'SUCCEEDED'", name="run_state"),
        CheckConstraint("outcome IN ('PASS','ADVISORY_FAIL','BLOCKING_FAIL')", name="outcome"),
        CheckConstraint(
            "evaluated_count >= 0 AND missing_count >= 0 AND unexpected_count >= 0",
            name="counts_nonnegative",
        ),
        CheckConstraint(
            "missing_ratio BETWEEN 0 AND 1 AND unexpected_ratio BETWEEN 0 AND 1",
            name="ratios",
        ),
        CheckConstraint("duration_ms >= 0", name="duration_nonnegative"),
        *_sha256_checks("result_hash", "result_retention_policy_hash", "result_hold_hash"),
        Index(
            "ix_quality_expectation_results_issues",
            "workspace_id",
            text("occurred_at DESC"),
            text("id DESC"),
            postgresql_where=text("outcome IN ('ADVISORY_FAIL','BLOCKING_FAIL')"),
        ),
        {"schema": "quality"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform.workspaces.id"), nullable=False
    )
    run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    attempt_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    run_state: Mapped[str] = mapped_column(String(24), nullable=False)
    rule_set_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    rule_definition_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    evaluated_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    missing_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    unexpected_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    missing_ratio: Mapped[Decimal] = mapped_column(Numeric(18, 12), nullable=False)
    unexpected_ratio: Mapped[Decimal] = mapped_column(Numeric(18, 12), nullable=False)
    duration_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_retention_policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    result_retention_policy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    result_retention_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_retain_until: Mapped[datetime] = mapped_column(nullable=False)
    result_hold_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    result_hold_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("transaction_timestamp()")
    )


class QualityRunEventModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "run_events"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_quality_run_events_workspace_id"),
        UniqueConstraint(
            "workspace_id", "run_id", "sequence", name="uq_quality_run_events_sequence"
        ),
        ForeignKeyConstraint(
            [
                "workspace_id",
                "run_id",
                "audit_retention_policy_id",
                "audit_retention_policy_number",
                "audit_retention_policy_hash",
                "audit_retain_until",
                "audit_hold_generation",
                "audit_hold_hash",
            ],
            [
                "quality.validation_runs.workspace_id",
                "quality.validation_runs.id",
                "quality.validation_runs.audit_retention_policy_id",
                "quality.validation_runs.audit_retention_policy_number",
                "quality.validation_runs.audit_retention_policy_hash",
                "quality.validation_runs.audit_retain_until",
                "quality.validation_runs.audit_hold_generation",
                "quality.validation_runs.audit_hold_hash",
            ],
            name="fk_quality_run_events_run",
            ondelete="RESTRICT",
        ),
        CheckConstraint("sequence > 0", name="sequence_positive"),
        CheckConstraint("char_length(reason_code) BETWEEN 1 AND 100", name="reason_bounded"),
        *_sha256_checks("evidence_hash", "audit_retention_policy_hash", "audit_hold_hash"),
        {"schema": "quality"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform.workspaces.id"), nullable=False
    )
    run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_retention_policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    audit_retention_policy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    audit_retention_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_retain_until: Mapped[datetime] = mapped_column(nullable=False)
    audit_hold_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    audit_hold_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("transaction_timestamp()")
    )


class QualityDispatchCallReceiptModel(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "dispatch_call_receipts"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_quality_dispatch_workspace_id"),
        UniqueConstraint(
            "workspace_id",
            "service_subject_id",
            "call_id_hash",
            name="uq_quality_dispatch_call",
        ),
        UniqueConstraint(
            "workspace_id",
            "id",
            "audit_retention_policy_id",
            "audit_retention_policy_number",
            "audit_retention_policy_hash",
            "audit_retain_until",
            "audit_hold_generation",
            "audit_hold_hash",
            name="uq_quality_dispatch_audit_binding",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "service_subject_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_quality_dispatch_subject",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "created_run_count BETWEEN 0 AND 100 AND skipped_window_count >= 0",
            name="counts",
        ),
        CheckConstraint("max_due_schedules BETWEEN 1 AND 100", name="max_due"),
        CheckConstraint("max_created_runs BETWEEN 1 AND 100", name="max_created"),
        CheckConstraint("audit_retention_kind = 'QUALITY_AUDIT'", name="audit_kind"),
        *_sha256_checks(
            "call_id_hash",
            "request_hash",
            "result_hash",
            "idempotency_hash",
            "contract_hash",
            "created_run_list_hash",
            "skipped_range_hash",
            "audit_retention_policy_hash",
            "audit_hold_hash",
        ),
        {"schema": "quality"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform.workspaces.id"), nullable=False
    )
    service_subject_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    call_id_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    cutoff_at: Mapped[datetime] = mapped_column(nullable=False)
    evaluator_contract_version: Mapped[str] = mapped_column(String(100), nullable=False)
    tzdb_version: Mapped[str] = mapped_column(String(100), nullable=False)
    contract_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    max_due_schedules: Mapped[int] = mapped_column(Integer, nullable=False)
    max_created_runs: Mapped[int] = mapped_column(Integer, nullable=False)
    created_run_count: Mapped[int] = mapped_column(Integer, nullable=False)
    skipped_window_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_run_list_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    skipped_range_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_retention_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    audit_retention_policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    audit_retention_policy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    audit_retention_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_retention_basis_at: Mapped[datetime] = mapped_column(nullable=False)
    audit_retain_until: Mapped[datetime] = mapped_column(nullable=False)
    audit_hold_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    audit_hold_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class QualityDispatchRunLinkModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "dispatch_run_links"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "dispatch_receipt_id",
            "ordinal",
            name="uq_quality_dispatch_links_ordinal",
        ),
        UniqueConstraint("workspace_id", "run_id", name="uq_quality_dispatch_links_run"),
        ForeignKeyConstraint(
            [
                "workspace_id",
                "dispatch_receipt_id",
                "receipt_audit_policy_id",
                "receipt_audit_policy_number",
                "receipt_audit_policy_hash",
                "receipt_audit_retain_until",
                "receipt_audit_hold_generation",
                "receipt_audit_hold_hash",
            ],
            [
                "quality.dispatch_call_receipts.workspace_id",
                "quality.dispatch_call_receipts.id",
                "quality.dispatch_call_receipts.audit_retention_policy_id",
                "quality.dispatch_call_receipts.audit_retention_policy_number",
                "quality.dispatch_call_receipts.audit_retention_policy_hash",
                "quality.dispatch_call_receipts.audit_retain_until",
                "quality.dispatch_call_receipts.audit_hold_generation",
                "quality.dispatch_call_receipts.audit_hold_hash",
            ],
            name="fk_quality_dispatch_links_receipt",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "workspace_id",
                "run_id",
                "run_result_policy_id",
                "run_result_policy_number",
                "run_result_policy_hash",
                "run_result_retain_until",
                "run_result_hold_generation",
                "run_result_hold_hash",
                "run_audit_policy_id",
                "run_audit_policy_number",
                "run_audit_policy_hash",
                "run_audit_retain_until",
                "run_audit_hold_generation",
                "run_audit_hold_hash",
            ],
            [
                "quality.validation_runs.workspace_id",
                "quality.validation_runs.id",
                "quality.validation_runs.result_retention_policy_id",
                "quality.validation_runs.result_retention_policy_number",
                "quality.validation_runs.result_retention_policy_hash",
                "quality.validation_runs.result_retain_until",
                "quality.validation_runs.result_hold_generation",
                "quality.validation_runs.result_hold_hash",
                "quality.validation_runs.audit_retention_policy_id",
                "quality.validation_runs.audit_retention_policy_number",
                "quality.validation_runs.audit_retention_policy_hash",
                "quality.validation_runs.audit_retain_until",
                "quality.validation_runs.audit_hold_generation",
                "quality.validation_runs.audit_hold_hash",
            ],
            name="fk_quality_dispatch_links_run",
            ondelete="RESTRICT",
        ),
        CheckConstraint("ordinal > 0", name="ordinal_positive"),
        CheckConstraint(
            "receipt_audit_hold_generation > 0 "
            "AND run_result_hold_generation > 0 "
            "AND run_audit_hold_generation > 0",
            name="hold_generations_positive",
        ),
        *_sha256_checks(
            "receipt_audit_policy_hash",
            "receipt_audit_hold_hash",
            "run_result_policy_hash",
            "run_result_hold_hash",
            "run_audit_policy_hash",
            "run_audit_hold_hash",
        ),
        {"schema": "quality"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform.workspaces.id"), nullable=False
    )
    dispatch_receipt_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    receipt_audit_policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    receipt_audit_policy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    receipt_audit_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_audit_retain_until: Mapped[datetime] = mapped_column(nullable=False)
    receipt_audit_hold_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    receipt_audit_hold_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    run_result_policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    run_result_policy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    run_result_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    run_result_retain_until: Mapped[datetime] = mapped_column(nullable=False)
    run_result_hold_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    run_result_hold_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    run_audit_policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    run_audit_policy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    run_audit_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    run_audit_retain_until: Mapped[datetime] = mapped_column(nullable=False)
    run_audit_hold_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    run_audit_hold_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("transaction_timestamp()")
    )


class QualityExecutionCallReceiptModel(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "execution_call_receipts"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_quality_execution_workspace_id"),
        UniqueConstraint(
            "workspace_id",
            "service_subject_id",
            "run_id",
            "call_id_hash",
            name="uq_quality_execution_call",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "service_subject_id"],
            ["iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"],
            name="fk_quality_execution_subject",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "workspace_id",
                "run_id",
                "audit_retention_policy_id",
                "audit_retention_policy_number",
                "audit_retention_policy_hash",
                "audit_retain_until",
                "audit_hold_generation",
                "audit_hold_hash",
            ],
            [
                "quality.validation_runs.workspace_id",
                "quality.validation_runs.id",
                "quality.validation_runs.audit_retention_policy_id",
                "quality.validation_runs.audit_retention_policy_number",
                "quality.validation_runs.audit_retention_policy_hash",
                "quality.validation_runs.audit_retain_until",
                "quality.validation_runs.audit_hold_generation",
                "quality.validation_runs.audit_hold_hash",
            ],
            name="fk_quality_execution_run",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "workspace_id",
                "attempt_id",
                "run_id",
                "lease_epoch",
                "lease_token_hash",
                "audit_retention_policy_id",
                "audit_retention_policy_number",
                "audit_retention_policy_hash",
                "audit_retain_until",
                "audit_hold_generation",
                "audit_hold_hash",
            ],
            [
                "quality.validation_attempts.workspace_id",
                "quality.validation_attempts.id",
                "quality.validation_attempts.run_id",
                "quality.validation_attempts.lease_epoch",
                "quality.validation_attempts.lease_token_hash",
                "quality.validation_attempts.audit_retention_policy_id",
                "quality.validation_attempts.audit_retention_policy_number",
                "quality.validation_attempts.audit_retention_policy_hash",
                "quality.validation_attempts.audit_retain_until",
                "quality.validation_attempts.audit_hold_generation",
                "quality.validation_attempts.audit_hold_hash",
            ],
            name="fk_quality_execution_attempt",
            ondelete="RESTRICT",
        ),
        CheckConstraint("lease_epoch > 0", name="lease_epoch_positive"),
        *_sha256_checks(
            "call_id_hash",
            "request_hash",
            "result_hash",
            "idempotency_hash",
            "lease_token_hash",
            "audit_retention_policy_hash",
            "audit_hold_hash",
        ),
        {"schema": "quality"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("platform.workspaces.id"), nullable=False
    )
    service_subject_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    attempt_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    lease_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lease_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    call_id_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_retention_policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    audit_retention_policy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    audit_retention_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_retain_until: Mapped[datetime] = mapped_column(nullable=False)
    audit_hold_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    audit_hold_hash: Mapped[str] = mapped_column(String(64), nullable=False)
