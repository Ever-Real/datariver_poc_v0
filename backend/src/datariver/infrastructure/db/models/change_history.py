from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
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

_FORBIDDEN_DOCUMENT_JSONPATH = (
    '$.** ? (@.type() == "object").keyvalue() ? '
    '(@.key == "raw" || @.key == "payload" || @.key == "aspect" || '
    '@.key == "schemaMetadata" || @.key == "previousAspectValue")'
)


class ChangeHistorySourceModel(
    Base,
    UuidPrimaryKeyMixin,
    TimestampMixin,
    VersionMixin,
):
    """Credential-free identity and verified capture boundary for one provider source."""

    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "source_identity_hash"),
        CheckConstraint("source_identity_hash ~ '^[0-9a-f]{64}$'", name="identity_sha256"),
        CheckConstraint("schema_contract_hash ~ '^[0-9a-f]{64}$'", name="schema_sha256"),
        CheckConstraint("source_generation > 0", name="generation_positive"),
        CheckConstraint("source_kind IN ('DATAHUB')", name="kind_vocabulary"),
        CheckConstraint(
            "capture_state IN ('DISABLED', 'READY', 'CAPTURING', 'DEGRADED_GAP', "
            "'TARGET_RECHECK_REQUIRED', 'FAILED')",
            name="capture_state_vocabulary",
        ),
        CheckConstraint(
            "char_length(provider_name) BETWEEN 1 AND 100 AND provider_name = btrim(provider_name)",
            name="provider_name_bounded",
        ),
        CheckConstraint(
            "char_length(provider_version) BETWEEN 1 AND 100 "
            "AND provider_version = btrim(provider_version)",
            name="provider_version_bounded",
        ),
        CheckConstraint(
            "first_mcl_offsets IS NULL OR "
            "(jsonb_typeof(first_mcl_offsets) = 'object' "
            "AND octet_length(first_mcl_offsets::text) <= 4096 "
            "AND NOT jsonb_path_exists(first_mcl_offsets, '$.* ? (@.type() != \"number\")') "
            "AND NOT jsonb_path_exists(first_mcl_offsets, '$.* ? (@ < 0)'))",
            name="first_mcl_offsets_bounded",
        ),
        CheckConstraint(
            "(ledger_guarantee_from IS NULL AND first_exact_capture_at IS NULL "
            "AND first_mcl_offsets IS NULL) OR "
            "(ledger_guarantee_from IS NOT NULL AND first_exact_capture_at IS NOT NULL "
            "AND first_mcl_offsets IS NOT NULL)",
            name="exact_boundary_shape",
        ),
        CheckConstraint("version > 0", name="version_positive"),
        ForeignKeyConstraint(
            ("workspace_id",),
            ("platform.workspaces.id",),
            ondelete="RESTRICT",
        ),
        Index("ix_change_history_sources_state", "workspace_id", "capture_state", "id"),
        {"schema": "change_history"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_identity_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_version: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_contract_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    capture_state: Mapped[str] = mapped_column(String(32), nullable=False)
    history_available_from: Mapped[datetime | None]
    ledger_guarantee_from: Mapped[datetime | None]
    first_exact_capture_at: Mapped[datetime | None]
    first_timeline_checkpoint: Mapped[datetime | None]
    first_mcl_offsets: Mapped[dict[str, Any] | None] = mapped_column(JSON_DOCUMENT)
    last_successful_capture_at: Mapped[datetime | None]


class ChangeHistoryLedgerEventModel(Base, UuidPrimaryKeyMixin):
    """Append-only normalized event; raw DataHub aspect documents are never stored."""

    __tablename__ = "ledger_events"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "event_identity"),
        UniqueConstraint(
            "workspace_id",
            "source_id",
            "source_event_identity",
            "deterministic_ordinal",
            name="uq_change_history_ledger_source_event_ordinal",
        ),
        CheckConstraint("event_identity ~ '^[0-9a-f]{64}$'", name="identity_sha256"),
        CheckConstraint("source_event_identity ~ '^[0-9a-f]{64}$'", name="source_sha256"),
        CheckConstraint(
            "normalized_change_transaction_id ~ '^[0-9a-f]{64}$'",
            name="transaction_sha256",
        ),
        CheckConstraint("entity_urn_hash ~ '^[0-9a-f]{64}$'", name="entity_urn_sha256"),
        CheckConstraint("deterministic_ordinal >= 0", name="ordinal_nonnegative"),
        CheckConstraint(
            "source_kind IN ('MCL', 'TIMELINE', 'RECONCILIATION')",
            name="source_kind_vocabulary",
        ),
        CheckConstraint(
            "(source_kind = 'MCL' AND topic_contract IS NOT NULL "
            "AND source_partition IS NOT NULL AND source_offset IS NOT NULL) OR "
            "(source_kind <> 'MCL' AND topic_contract IS NULL "
            "AND source_partition IS NULL AND source_offset IS NULL)",
            name="source_position_shape",
        ),
        CheckConstraint(
            "source_partition IS NULL OR source_partition >= 0",
            name="partition_nonnegative",
        ),
        CheckConstraint("source_offset IS NULL OR source_offset >= 0", name="offset_nonnegative"),
        CheckConstraint(
            "category IN ('TECHNICAL_SCHEMA', 'DOCUMENTATION', 'TAG', "
            "'GLOSSARY_TERM', 'OWNERSHIP')",
            name="category_vocabulary",
        ),
        CheckConstraint(
            "(category = 'TECHNICAL_SCHEMA' AND source_aspect = 'schemaMetadata') OR "
            "(category = 'DOCUMENTATION' AND source_aspect IN "
            "('datasetProperties', 'editableSchemaMetadata')) OR "
            "(category = 'TAG' AND source_aspect = 'globalTags') OR "
            "(category = 'GLOSSARY_TERM' AND source_aspect = 'glossaryTerms') OR "
            "(category = 'OWNERSHIP' AND source_aspect = 'ownership')",
            name="category_aspect_allowlist",
        ),
        CheckConstraint(
            "operation IN ('CREATE', 'UPDATE', 'UPSERT', 'DELETE', 'ADD', 'REMOVE')",
            name="operation_vocabulary",
        ),
        CheckConstraint(
            "precision IN ('EXACT_TIMELINE', 'EXACT_MCL', 'DRIFT_DETECTED', "
            "'BACKFILLED_BEST_EFFORT', 'INITIAL_BASELINE')",
            name="precision_vocabulary",
        ),
        CheckConstraint(
            "char_length(entity_urn) BETWEEN 1 AND 4096",
            name="entity_urn_bounded",
        ),
        CheckConstraint(
            "char_length(normalized_entity_key) BETWEEN 1 AND 1000 "
            "AND normalized_entity_key = btrim(normalized_entity_key)",
            name="entity_key_bounded",
        ),
        CheckConstraint(
            "before_data IS NULL OR (jsonb_typeof(before_data) = 'object' "
            "AND octet_length(before_data::text) <= 16384 "
            f"AND NOT jsonb_path_exists(before_data, '{_FORBIDDEN_DOCUMENT_JSONPATH}'))",
            name="before_data_bounded",
        ),
        CheckConstraint(
            "after_data IS NULL OR (jsonb_typeof(after_data) = 'object' "
            "AND octet_length(after_data::text) <= 16384 "
            f"AND NOT jsonb_path_exists(after_data, '{_FORBIDDEN_DOCUMENT_JSONPATH}'))",
            name="after_data_bounded",
        ),
        CheckConstraint(
            "before_hash IS NULL OR before_hash ~ '^[0-9a-f]{64}$'",
            name="before_hash_sha256",
        ),
        CheckConstraint(
            "after_hash IS NULL OR after_hash ~ '^[0-9a-f]{64}$'",
            name="after_hash_sha256",
        ),
        CheckConstraint(
            "jsonb_typeof(source_metadata) = 'object' "
            "AND octet_length(source_metadata::text) <= 4096 "
            "AND NOT (source_metadata ?| ARRAY["
            "'raw', 'payload', 'aspect', 'schemaMetadata', 'previousAspectValue']) "
            f"AND NOT jsonb_path_exists(source_metadata, '{_FORBIDDEN_DOCUMENT_JSONPATH}')",
            name="source_metadata_bounded",
        ),
        CheckConstraint(
            "actor_ref IS NULL OR char_length(actor_ref) BETWEEN 1 AND 1000",
            name="actor_bounded",
        ),
        ForeignKeyConstraint(
            ("workspace_id",),
            ("platform.workspaces.id",),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "source_id"),
            ("change_history.sources.workspace_id", "change_history.sources.id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "asset_id"),
            ("catalog.assets_projection.workspace_id", "catalog.assets_projection.id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "system_id"),
            ("platform.data_systems.workspace_id", "platform.data_systems.id"),
            ondelete="RESTRICT",
        ),
        Index(
            "ix_change_history_ledger_keyset",
            "workspace_id",
            text("source_occurred_at DESC"),
            text("id DESC"),
        ),
        Index(
            "ix_change_history_ledger_asset_history",
            "workspace_id",
            "asset_id",
            text("source_occurred_at DESC"),
            text("id DESC"),
        ),
        Index(
            "ix_change_history_ledger_filters",
            "workspace_id",
            "category",
            "precision",
            "system_id",
            text("source_occurred_at DESC"),
            text("id DESC"),
        ),
        Index(
            "ix_change_history_ledger_transaction",
            "workspace_id",
            "normalized_change_transaction_id",
            "id",
        ),
        {"schema": "change_history"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    event_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    source_event_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_change_transaction_id: Mapped[str] = mapped_column(String(64), nullable=False)
    deterministic_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    topic_contract: Mapped[str | None] = mapped_column(String(255))
    source_partition: Mapped[int | None] = mapped_column(Integer)
    source_offset: Mapped[int | None] = mapped_column(BigInteger)
    asset_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    entity_urn: Mapped[str] = mapped_column(Text, nullable=False)
    entity_urn_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    platform: Mapped[str | None] = mapped_column(String(100))
    database_name: Mapped[str | None] = mapped_column(String(255))
    schema_name: Mapped[str | None] = mapped_column(String(255))
    table_or_view_name: Mapped[str | None] = mapped_column(String(500))
    field_path: Mapped[str | None] = mapped_column(String(1000))
    normalized_entity_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    system_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    source_aspect: Mapped[str] = mapped_column(String(100), nullable=False)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    before_data: Mapped[dict[str, Any] | None] = mapped_column(JSON_DOCUMENT)
    after_data: Mapped[dict[str, Any] | None] = mapped_column(JSON_DOCUMENT)
    before_hash: Mapped[str | None] = mapped_column(String(64))
    after_hash: Mapped[str | None] = mapped_column(String(64))
    actor_ref: Mapped[str | None] = mapped_column(Text)
    source_occurred_at: Mapped[datetime | None]
    detected_at: Mapped[datetime]
    captured_at: Mapped[datetime]
    effective_week_start: Mapped[date | None] = mapped_column(Date())
    precision: Mapped[str] = mapped_column(String(32), nullable=False)
    tombstone: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)


class ChangeHistoryCheckpointModel(
    Base,
    UuidPrimaryKeyMixin,
    TimestampMixin,
    VersionMixin,
):
    """Partition materialization authority with an optimistic lease/fence."""

    __tablename__ = "checkpoints"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint(
            "workspace_id",
            "source_id",
            "topic_contract",
            "source_partition",
            name="uq_change_history_checkpoint_partition",
        ),
        CheckConstraint("source_partition >= 0", name="partition_nonnegative"),
        CheckConstraint("next_offset >= 0", name="next_offset_nonnegative"),
        CheckConstraint(
            "first_exact_offset IS NULL OR first_exact_offset >= 0",
            name="first_exact_offset_nonnegative",
        ),
        CheckConstraint(
            "first_mcl_offset IS NULL OR first_mcl_offset >= 0",
            name="first_mcl_offset_nonnegative",
        ),
        CheckConstraint(
            "first_mcl_offset IS NULL OR first_exact_offset = first_mcl_offset",
            name="first_offset_consistent",
        ),
        CheckConstraint(
            "last_contiguous_event_identity IS NULL OR "
            "last_contiguous_event_identity ~ '^[0-9a-f]{64}$'",
            name="last_event_sha256",
        ),
        CheckConstraint(
            "status IN ('READY', 'ACTIVE', 'DEGRADED_GAP', 'BLOCKED', 'FAILED')",
            name="status_vocabulary",
        ),
        CheckConstraint(
            "last_error_code IS NULL OR "
            "(char_length(last_error_code) BETWEEN 1 AND 100 "
            "AND last_error_code ~ '^[A-Z0-9_]+$')",
            name="error_code_bounded",
        ),
        CheckConstraint("fence_epoch >= 0", name="fence_epoch_nonnegative"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(
            "(lease_owner_fingerprint IS NULL AND lease_token_hash IS NULL "
            "AND lease_acquired_at IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_owner_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND lease_token_hash ~ '^[0-9a-f]{64}$' "
            "AND lease_acquired_at IS NOT NULL AND lease_expires_at > lease_acquired_at)",
            name="lease_shape",
        ),
        ForeignKeyConstraint(
            ("workspace_id",),
            ("platform.workspaces.id",),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "source_id"),
            ("change_history.sources.workspace_id", "change_history.sources.id"),
            ondelete="RESTRICT",
        ),
        Index(
            "ix_change_history_checkpoint_lease",
            "workspace_id",
            "status",
            "lease_expires_at",
            "id",
        ),
        {"schema": "change_history"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    topic_contract: Mapped[str] = mapped_column(String(255), nullable=False)
    source_partition: Mapped[int] = mapped_column(Integer, nullable=False)
    first_exact_offset: Mapped[int | None] = mapped_column(BigInteger)
    first_mcl_offset: Mapped[int | None] = mapped_column(BigInteger)
    next_offset: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_contiguous_event_identity: Mapped[str | None] = mapped_column(String(64))
    last_source_occurred_at: Mapped[datetime | None]
    last_captured_at: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    lease_owner_fingerprint: Mapped[str | None] = mapped_column(String(64))
    lease_token_hash: Mapped[str | None] = mapped_column(String(64))
    lease_acquired_at: Mapped[datetime | None]
    lease_expires_at: Mapped[datetime | None]
    fence_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)


class ChangeHistoryCrLinkEventModel(Base, UuidPrimaryKeyMixin):
    """Append-only CR candidate/primary command result without CR aggregate mutation."""

    __tablename__ = "cr_link_events"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "ledger_event_id", "link_version"),
        UniqueConstraint("workspace_id", "ledger_event_id", "event_hash"),
        CheckConstraint("link_version > 0", name="link_version_positive"),
        CheckConstraint("link_kind IN ('PRIMARY', 'CANDIDATE')", name="kind_vocabulary"),
        CheckConstraint(
            "action IN ('SET_PRIMARY', 'CLEAR_PRIMARY', 'ADD_CANDIDATE', 'REMOVE_CANDIDATE')",
            name="action_vocabulary",
        ),
        CheckConstraint(
            "(link_kind = 'PRIMARY' AND action IN ('SET_PRIMARY', 'CLEAR_PRIMARY')) OR "
            "(link_kind = 'CANDIDATE' AND action IN "
            "('ADD_CANDIDATE', 'REMOVE_CANDIDATE'))",
            name="kind_action_shape",
        ),
        CheckConstraint(
            "active_result = (action IN ('SET_PRIMARY', 'ADD_CANDIDATE'))",
            name="active_result_shape",
        ),
        CheckConstraint(
            "(resulting_primary_change_request_id IS NULL "
            "AND resulting_primary_round_id IS NULL) OR "
            "(resulting_primary_change_request_id IS NOT NULL "
            "AND resulting_primary_round_id IS NOT NULL)",
            name="resulting_primary_shape",
        ),
        CheckConstraint(
            "prior_link_hash IS NULL OR prior_link_hash ~ '^[0-9a-f]{64}$'",
            name="prior_hash_sha256",
        ),
        CheckConstraint("event_hash ~ '^[0-9a-f]{64}$'", name="event_hash_sha256"),
        CheckConstraint("policy_hash ~ '^[0-9a-f]{64}$'", name="policy_hash_sha256"),
        CheckConstraint("basis_hash ~ '^[0-9a-f]{64}$'", name="basis_hash_sha256"),
        CheckConstraint(
            "char_length(reason) BETWEEN 1 AND 2000 AND reason = btrim(reason)",
            name="reason_bounded",
        ),
        ForeignKeyConstraint(
            ("workspace_id",),
            ("platform.workspaces.id",),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "ledger_event_id"),
            ("change_history.ledger_events.workspace_id", "change_history.ledger_events.id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "change_request_id", "change_request_round_id"),
            (
                "governance.change_request_rounds.workspace_id",
                "governance.change_request_rounds.change_request_id",
                "governance.change_request_rounds.id",
            ),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            (
                "workspace_id",
                "resulting_primary_change_request_id",
                "resulting_primary_round_id",
            ),
            (
                "governance.change_request_rounds.workspace_id",
                "governance.change_request_rounds.change_request_id",
                "governance.change_request_rounds.id",
            ),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "actor_id"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
        ),
        Index(
            "ix_change_history_cr_links_current",
            "workspace_id",
            "ledger_event_id",
            text("link_version DESC"),
        ),
        Index(
            "ix_change_history_cr_links_request",
            "workspace_id",
            "change_request_id",
            "change_request_round_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
        {"schema": "change_history"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    ledger_event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    link_version: Mapped[int] = mapped_column(Integer, nullable=False)
    link_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    change_request_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    change_request_round_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    active_result: Mapped[bool] = mapped_column(Boolean, nullable=False)
    resulting_primary_change_request_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    resulting_primary_round_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    prior_link_hash: Mapped[str | None] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    basis_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
