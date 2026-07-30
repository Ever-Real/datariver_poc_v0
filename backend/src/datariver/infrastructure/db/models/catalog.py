from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from datariver.infrastructure.db.base import (
    JSON_DOCUMENT,
    Base,
    TimestampMixin,
    UuidPrimaryKeyMixin,
    VersionMixin,
)


class AssetProjectionModel(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "assets_projection"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_assets_projection_workspace_id"),
        UniqueConstraint("workspace_id", "urn_hash"),
        CheckConstraint("jsonb_typeof(tags) = 'array'", name="tags_array"),
        CheckConstraint("jsonb_typeof(glossary_terms) = 'array'", name="glossary_terms_array"),
        CheckConstraint("jsonb_typeof(column_names) = 'array'", name="column_names_array"),
        CheckConstraint(
            "description IS NULL OR char_length(description) <= 10000",
            name="description_bounded",
        ),
        CheckConstraint("jsonb_array_length(tags) <= 100", name="tags_bounded"),
        CheckConstraint(
            """NOT jsonb_path_exists(tags, '$[*] ? (@.type() != "string")')""",
            name="tags_string_items",
        ),
        CheckConstraint(
            "jsonb_array_length(glossary_terms) <= 100",
            name="glossary_terms_bounded",
        ),
        CheckConstraint(
            """NOT jsonb_path_exists(glossary_terms, '$[*] ? (@.type() != "string")')""",
            name="glossary_terms_string_items",
        ),
        CheckConstraint("jsonb_array_length(column_names) <= 1000", name="column_names_bounded"),
        CheckConstraint(
            """NOT jsonb_path_exists(column_names, '$[*] ? (@.type() != "string")')""",
            name="column_names_string_items",
        ),
        CheckConstraint(
            "char_length(external_urn) BETWEEN 1 AND 4096",
            name="external_urn_bounded",
        ),
        Index(
            "ix_assets_projection_scope",
            "workspace_id",
            "classification",
            "system_id",
            "domain_id",
        ),
        Index(
            "ix_assets_projection_active_scope_order",
            "workspace_id",
            "classification",
            "name",
            "id",
            postgresql_where=text("deleted_at IS NULL AND lifecycle = 'ACTIVE'"),
        ),
        Index(
            "ix_assets_projection_search_fts_active",
            "search_vector",
            postgresql_using="gin",
            postgresql_where=text("deleted_at IS NULL AND lifecycle = 'ACTIVE'"),
        ),
        Index(
            "ix_assets_projection_name_trgm_active",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
            postgresql_where=text("deleted_at IS NULL AND lifecycle = 'ACTIVE'"),
        ),
        Index(
            "ix_assets_projection_tree_active",
            "workspace_id",
            "platform",
            "database_name",
            "schema_name",
            "name",
            "id",
            postgresql_where=text("deleted_at IS NULL AND lifecycle = 'ACTIVE'"),
        ),
        {"schema": "catalog"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    external_urn: Mapped[str] = mapped_column(Text, nullable=False)
    urn_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    description_truncated: Mapped[bool] = mapped_column(
        default=False,
        server_default=text("false"),
        nullable=False,
    )
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('simple'::regconfig, "
            "coalesce(name, '') || ' ' || coalesce(description, ''))",
            persisted=True,
        ),
        nullable=False,
    )
    platform: Mapped[str | None] = mapped_column(String(100))
    database_name: Mapped[str | None] = mapped_column(String(255))
    schema_name: Mapped[str | None] = mapped_column(String(255))
    owner_ref: Mapped[str | None] = mapped_column(String(1_000))
    domain_ref: Mapped[str | None] = mapped_column(String(1_000))
    tags: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    tags_truncated: Mapped[bool] = mapped_column(
        default=False,
        server_default=text("false"),
        nullable=False,
    )
    glossary_terms: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    glossary_terms_truncated: Mapped[bool] = mapped_column(
        default=False,
        server_default=text("false"),
        nullable=False,
    )
    column_names: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    column_names_truncated: Mapped[bool] = mapped_column(
        default=False,
        server_default=text("false"),
        nullable=False,
    )
    source_created_at: Mapped[datetime | None]
    domain_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    system_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    owner_department_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    classification: Mapped[int] = mapped_column(default=0, nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(50), default="ACTIVE", nullable=False)
    source_version: Mapped[str] = mapped_column(String(255), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(nullable=False)
    deleted_at: Mapped[datetime | None]
    last_seen_sync_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    projection_source: Mapped[str] = mapped_column(String(32), default="DATAHUB", nullable=False)


Index(
    "ix_assets_projection_name_lower_prefix_active",
    func.lower(AssetProjectionModel.name).label("name_lower"),
    postgresql_ops={"name_lower": "text_pattern_ops"},
    postgresql_where=text("deleted_at IS NULL AND lifecycle = 'ACTIVE'"),
)


class AssetProfileSnapshotModel(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "asset_profile_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_asset_profile_snapshots_workspace_id",
        ),
        UniqueConstraint(
            "workspace_id",
            "asset_id",
            "snapshot_identity_hash",
            name="uq_asset_profile_snapshots_identity",
        ),
        UniqueConstraint(
            "workspace_id",
            "id",
            "classification",
            "target_scope_hash",
            "profile_retention_policy_id",
            "profile_retention_policy_number",
            "profile_retention_policy_hash",
            "profile_retain_until",
            "profile_hold_generation",
            "profile_hold_hash",
            name="uq_asset_profile_snapshots_child_binding",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "asset_id"),
            ("catalog.assets_projection.workspace_id", "catalog.assets_projection.id"),
            name="fk_asset_profile_snapshots_asset",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            (
                "workspace_id",
                "profile_retention_policy_id",
                "profile_retention_policy_hash",
                "profile_retention_policy_number",
            ),
            (
                "retention.policy_versions.workspace_id",
                "retention.policy_versions.id",
                "retention.policy_versions.payload_hash",
                "retention.policy_versions.policy_number",
            ),
            name="fk_asset_profile_snapshots_policy",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "profile_kind IN ('FULL', 'SAMPLE', 'PARTITION', 'QUERY', 'UNKNOWN')",
            name="profile_kind",
        ),
        CheckConstraint(
            "completeness IN ('COMPLETE', 'PARTIAL')",
            name="completeness",
        ),
        CheckConstraint(
            "classification BETWEEN 0 AND 3",
            name="classification",
        ),
        CheckConstraint(
            "row_count IS NULL OR row_count >= 0",
            name="row_count_nonnegative",
        ),
        CheckConstraint(
            "column_count IS NULL OR column_count >= 0",
            name="column_count_nonnegative",
        ),
        CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0",
            name="size_bytes_nonnegative",
        ),
        CheckConstraint(
            "(profile_kind IN ('PARTITION', 'QUERY') "
            "AND provenance_key_id IS NOT NULL "
            "AND provenance_fingerprint ~ '^[0-9a-f]{64}$') OR "
            "(profile_kind NOT IN ('PARTITION', 'QUERY') "
            "AND provenance_key_id IS NULL AND provenance_fingerprint IS NULL)",
            name="provenance_shape",
        ),
        CheckConstraint(
            "snapshot_identity_hash ~ '^[0-9a-f]{64}$' "
            "AND target_scope_hash ~ '^[0-9a-f]{64}$' "
            "AND provider_contract_hash ~ '^[0-9a-f]{64}$' "
            "AND provider_query_hash ~ '^[0-9a-f]{64}$' "
            "AND provider_config_hash ~ '^[0-9a-f]{64}$' "
            "AND source_watermark_hash ~ '^[0-9a-f]{64}$' "
            "AND normalized_payload_hash ~ '^[0-9a-f]{64}$' "
            "AND profile_retention_policy_hash ~ '^[0-9a-f]{64}$' "
            "AND profile_hold_hash ~ '^[0-9a-f]{64}$'",
            name="hashes_sha256",
        ),
        CheckConstraint(
            "profile_retention_kind = 'QUALITY_PROFILE'",
            name="retention_kind",
        ),
        CheckConstraint(
            "profile_retention_policy_number > 0 "
            "AND profile_hold_generation > 0 "
            "AND profile_retain_until > profile_retention_basis_at",
            name="retention_binding",
        ),
        CheckConstraint(
            "first_observed_at <= last_observed_at AND stale_at > profiled_at",
            name="time_order",
        ),
        Index(
            "ix_asset_profile_snapshots_latest",
            "workspace_id",
            "asset_id",
            text("profiled_at DESC"),
            text("last_observed_at DESC"),
            "id",
        ),
        Index(
            "ix_asset_profile_snapshots_retention",
            "workspace_id",
            "profile_retain_until",
            "id",
        ),
        {"schema": "catalog"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("platform.workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    )
    asset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    asset_source_version: Mapped[str] = mapped_column(String(255), nullable=False)
    snapshot_identity_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    completeness: Mapped[str] = mapped_column(String(16), nullable=False)
    profiled_at: Mapped[datetime] = mapped_column(nullable=False)
    first_observed_at: Mapped[datetime] = mapped_column(nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(nullable=False)
    stale_at: Mapped[datetime] = mapped_column(nullable=False)
    row_count: Mapped[int | None] = mapped_column(BigInteger)
    column_count: Mapped[int | None] = mapped_column(BigInteger)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    provenance_key_id: Mapped[str | None] = mapped_column(String(128))
    provenance_fingerprint: Mapped[str | None] = mapped_column(String(64))
    provider_version: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_contract_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_query_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_watermark_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    classification: Mapped[int] = mapped_column(Integer, nullable=False)
    system_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    domain_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    target_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_retention_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_retention_policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    profile_retention_policy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_retention_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_retention_basis_at: Mapped[datetime] = mapped_column(nullable=False)
    profile_retain_until: Mapped[datetime] = mapped_column(nullable=False)
    profile_hold_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    profile_hold_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ColumnProfileMetricModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "column_profile_metrics"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "snapshot_id",
            "field_path",
            name="uq_column_profile_metrics_field",
        ),
        ForeignKeyConstraint(
            (
                "workspace_id",
                "snapshot_id",
                "classification",
                "target_scope_hash",
                "profile_retention_policy_id",
                "profile_retention_policy_number",
                "profile_retention_policy_hash",
                "profile_retain_until",
                "profile_hold_generation",
                "profile_hold_hash",
            ),
            (
                "catalog.asset_profile_snapshots.workspace_id",
                "catalog.asset_profile_snapshots.id",
                "catalog.asset_profile_snapshots.classification",
                "catalog.asset_profile_snapshots.target_scope_hash",
                "catalog.asset_profile_snapshots.profile_retention_policy_id",
                "catalog.asset_profile_snapshots.profile_retention_policy_number",
                "catalog.asset_profile_snapshots.profile_retention_policy_hash",
                "catalog.asset_profile_snapshots.profile_retain_until",
                "catalog.asset_profile_snapshots.profile_hold_generation",
                "catalog.asset_profile_snapshots.profile_hold_hash",
            ),
            name="fk_column_profile_metrics_snapshot_binding",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "char_length(field_path) BETWEEN 1 AND 4096 AND field_path = btrim(field_path)",
            name="field_path",
        ),
        CheckConstraint(
            "(null_count_available AND null_count IS NOT NULL AND null_count >= 0) OR "
            "(NOT null_count_available AND null_count IS NULL)",
            name="null_count_shape",
        ),
        CheckConstraint(
            "(null_proportion_available AND null_proportion IS NOT NULL "
            "AND null_proportion BETWEEN 0 AND 1) OR "
            "(NOT null_proportion_available AND null_proportion IS NULL)",
            name="null_proportion_shape",
        ),
        CheckConstraint(
            "(unique_count_available AND unique_count IS NOT NULL AND unique_count >= 0) OR "
            "(NOT unique_count_available AND unique_count IS NULL)",
            name="unique_count_shape",
        ),
        CheckConstraint(
            "(unique_proportion_available AND unique_proportion IS NOT NULL "
            "AND unique_proportion BETWEEN 0 AND 1) OR "
            "(NOT unique_proportion_available AND unique_proportion IS NULL)",
            name="unique_proportion_shape",
        ),
        CheckConstraint(
            "classification BETWEEN 0 AND 3",
            name="classification",
        ),
        CheckConstraint(
            "target_scope_hash ~ '^[0-9a-f]{64}$' "
            "AND profile_retention_policy_hash ~ '^[0-9a-f]{64}$' "
            "AND profile_hold_hash ~ '^[0-9a-f]{64}$'",
            name="hashes_sha256",
        ),
        CheckConstraint(
            "profile_retention_policy_number > 0 AND profile_hold_generation > 0",
            name="retention_binding",
        ),
        Index(
            "ix_column_profile_metrics_snapshot",
            "workspace_id",
            "snapshot_id",
            "field_path",
        ),
        {"schema": "catalog"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("platform.workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    )
    snapshot_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    field_path: Mapped[str] = mapped_column(String(4096), nullable=False)
    null_count_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    null_count: Mapped[int | None] = mapped_column(BigInteger)
    null_proportion_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    null_proportion: Mapped[float | None] = mapped_column(Numeric(20, 18))
    unique_count_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    unique_count: Mapped[int | None] = mapped_column(BigInteger)
    unique_proportion_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    unique_proportion: Mapped[float | None] = mapped_column(Numeric(20, 18))
    classification: Mapped[int] = mapped_column(Integer, nullable=False)
    target_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_retention_policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    profile_retention_policy_number: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_retention_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_retain_until: Mapped[datetime] = mapped_column(nullable=False)
    profile_hold_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    profile_hold_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


class CatalogVocabularyEntryModel(Base, UuidPrimaryKeyMixin):
    """Workspace-owned resolver from local typed identity to a server-only provider reference."""

    __tablename__ = "vocabulary_entries"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "id", "kind"),
        UniqueConstraint(
            "workspace_id",
            "kind",
            "provider_ref",
            name="uq_vocabulary_entries_workspace_kind_provider_ref",
        ),
        CheckConstraint("kind IN ('DOMAIN', 'TAG', 'TERM')", name="kind_vocabulary"),
        CheckConstraint(
            "lifecycle IN ('ACTIVE', 'INACTIVE')",
            name="lifecycle_vocabulary",
        ),
        CheckConstraint(
            "char_length(display_name) BETWEEN 1 AND 500 AND display_name = btrim(display_name)",
            name="display_name_valid",
        ),
        CheckConstraint(
            "char_length(source_version) BETWEEN 1 AND 255 "
            "AND source_version = btrim(source_version)",
            name="source_version_valid",
        ),
        CheckConstraint(
            "(kind = 'DOMAIN' AND provider_ref LIKE 'urn:li:domain:%') OR "
            "(kind = 'TAG' AND provider_ref LIKE 'urn:li:tag:%') OR "
            "(kind = 'TERM' AND provider_ref LIKE 'urn:li:glossaryTerm:%')",
            name="provider_ref_kind",
        ),
        CheckConstraint("observed_at <= updated_at", name="observation_time_order"),
        CheckConstraint("version >= 1", name="version_positive"),
        ForeignKeyConstraint(
            ("workspace_id", "created_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
        ),
        Index(
            "ix_vocabulary_entries_workspace_kind_lifecycle_name",
            "workspace_id",
            "kind",
            "lifecycle",
            "display_name",
            "id",
        ),
        {"schema": "catalog"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("platform.workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_ref: Mapped[str] = mapped_column(String(1_000), nullable=False)
    display_name: Mapped[str] = mapped_column(String(500), nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(16), nullable=False)
    source_version: Mapped[str] = mapped_column(String(255), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(nullable=False)
    last_seen_sync_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    created_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


class CatalogVocabularySyncRunModel(Base):
    """Durable per-kind reconciliation cursor and verified snapshot evidence."""

    __tablename__ = "vocabulary_sync_runs"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('DOMAIN', 'TAG', 'TERM')",
            name="kind_vocabulary",
        ),
        CheckConstraint(
            "state IN ('ACTIVE', 'COMPLETED', 'ABANDONED')",
            name="state_vocabulary",
        ),
        CheckConstraint("next_offset >= 0", name="next_offset_nonnegative"),
        CheckConstraint(
            "expected_total IS NULL OR expected_total >= 0",
            name="expected_total_nonnegative",
        ),
        CheckConstraint("seen_count >= 0", name="seen_count_nonnegative"),
        CheckConstraint(
            "next_cursor IS NULL OR char_length(next_cursor) BETWEEN 1 AND 4096",
            name="next_cursor_bounded",
        ),
        CheckConstraint(
            "(NOT snapshot_consistent AND snapshot_evidence_reference IS NULL "
            "AND snapshot_contract_hash IS NULL AND snapshot_provider_version IS NULL) OR "
            "(snapshot_consistent "
            "AND snapshot_evidence_reference IS NOT NULL "
            "AND snapshot_contract_hash IS NOT NULL "
            "AND snapshot_provider_version IS NOT NULL "
            "AND char_length(snapshot_evidence_reference) BETWEEN 1 AND 500 "
            "AND snapshot_contract_hash ~ '^[0-9a-f]{64}$' "
            "AND char_length(snapshot_provider_version) BETWEEN 1 AND 128)",
            name="snapshot_evidence_bounded",
        ),
        Index(
            "uq_vocabulary_sync_runs_active_workspace_kind",
            "workspace_id",
            "kind",
            unique=True,
            postgresql_where=text("state = 'ACTIVE'"),
        ),
        Index(
            "ix_vocabulary_sync_runs_workspace_kind_started",
            "workspace_id",
            "kind",
            "started_at",
        ),
        {"schema": "catalog"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("platform.workspaces.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    sync_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    next_offset: Mapped[int] = mapped_column(nullable=False)
    next_cursor: Mapped[str | None] = mapped_column(Text)
    expected_total: Mapped[int | None] = mapped_column(BigInteger)
    seen_count: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    snapshot_consistent: Mapped[bool] = mapped_column(
        default=False,
        server_default=text("false"),
        nullable=False,
    )
    snapshot_evidence_reference: Mapped[str | None] = mapped_column(String(500))
    snapshot_contract_hash: Mapped[str | None] = mapped_column(String(64))
    snapshot_provider_version: Mapped[str | None] = mapped_column(String(128))
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(nullable=False)
    completed_at: Mapped[datetime | None]


class CatalogSyncRunModel(Base):
    __tablename__ = "sync_runs"
    __table_args__ = (
        Index("ix_catalog_sync_runs_workspace_state", "workspace_id", "state", "started_at"),
        CheckConstraint("next_offset >= 0", name="next_offset_nonnegative"),
        CheckConstraint(
            "expected_total IS NULL OR expected_total >= 0",
            name="expected_total_nonnegative",
        ),
        CheckConstraint("seen_count >= 0", name="seen_count_nonnegative"),
        CheckConstraint(
            "next_cursor IS NULL OR char_length(next_cursor) BETWEEN 1 AND 4096",
            name="next_cursor_bounded",
        ),
        CheckConstraint(
            "(NOT snapshot_consistent AND snapshot_evidence_reference IS NULL "
            "AND snapshot_contract_hash IS NULL AND snapshot_provider_version IS NULL) OR "
            "(snapshot_consistent "
            "AND snapshot_evidence_reference IS NOT NULL "
            "AND snapshot_contract_hash IS NOT NULL "
            "AND snapshot_provider_version IS NOT NULL "
            "AND char_length(snapshot_evidence_reference) BETWEEN 1 AND 500 "
            "AND snapshot_contract_hash ~ '^[0-9a-f]{64}$' "
            "AND char_length(snapshot_provider_version) BETWEEN 1 AND 128)",
            name="snapshot_evidence_bounded",
        ),
        {"schema": "catalog"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    sync_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    next_offset: Mapped[int] = mapped_column(nullable=False)
    next_cursor: Mapped[str | None] = mapped_column(Text)
    expected_total: Mapped[int | None] = mapped_column(BigInteger)
    seen_count: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    snapshot_consistent: Mapped[bool] = mapped_column(
        default=False,
        server_default=text("false"),
        nullable=False,
    )
    snapshot_evidence_reference: Mapped[str | None] = mapped_column(String(500))
    snapshot_contract_hash: Mapped[str | None] = mapped_column(String(64))
    snapshot_provider_version: Mapped[str | None] = mapped_column(String(128))
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(nullable=False)
    completed_at: Mapped[datetime | None]


class CatalogProjectionWatermarkModel(Base):
    __tablename__ = "projection_watermarks"
    __table_args__ = (
        CheckConstraint(
            "projection_version >= 0",
            name="projection_version_nonnegative",
        ),
        {"schema": "catalog"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("platform.workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    )
    projection_version: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        server_default=text("0"),
        nullable=False,
    )


class CatalogExportModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "export_requests"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "job_id"),
        UniqueConstraint("object_bucket", "object_key"),
        ForeignKeyConstraint(
            ("workspace_id", "requested_by"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "job_id"),
            ("integration.jobs.workspace_id", "integration.jobs.id"),
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_catalog_export_requests_workspace_job",
        ),
        CheckConstraint("request_hash ~ '^[0-9a-f]{64}$'", name="request_hash_sha256"),
        CheckConstraint(
            "permission_scope_hash ~ '^[0-9a-f]{64}$'",
            name="permission_scope_hash_sha256",
        ),
        CheckConstraint(
            "classification_access_hash ~ '^[0-9a-f]{64}$'",
            name="classification_access_hash_sha256",
        ),
        CheckConstraint(
            "classification_ceiling BETWEEN 0 AND 2",
            name="classification_ceiling_nonrestricted",
        ),
        CheckConstraint(
            "source_projection_version >= 0",
            name="source_projection_version_nonnegative",
        ),
        CheckConstraint("row_count IS NULL OR row_count >= 0", name="row_count_nonnegative"),
        CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="size_bytes_nonnegative"),
        CheckConstraint(
            "content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$'",
            name="content_sha256_valid",
        ),
        CheckConstraint(
            "(object_bucket IS NULL AND object_key IS NULL AND row_count IS NULL "
            "AND size_bytes IS NULL AND content_sha256 IS NULL AND completed_at IS NULL) "
            "OR (object_bucket IS NOT NULL AND object_key IS NOT NULL AND row_count IS NOT NULL "
            "AND size_bytes IS NOT NULL AND content_sha256 IS NOT NULL "
            "AND completed_at IS NOT NULL)",
            name="artifact_shape",
        ),
        CheckConstraint(
            "(classification_policy_id IS NULL AND classification_policy_hash IS NULL "
            "AND classification_policy_version IS NULL AND authorization_generation IS NULL) "
            "OR (classification_policy_id IS NOT NULL AND classification_policy_hash IS NOT NULL "
            "AND classification_policy_version IS NOT NULL "
            "AND authorization_generation IS NOT NULL)",
            name="classification_policy_binding_shape",
        ),
        Index("ix_catalog_exports_owner_time", "workspace_id", "requested_by", "created_at"),
        {"schema": "catalog"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    requested_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    request_document: Mapped[dict[str, object]] = mapped_column(JSON_DOCUMENT, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    permission_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    classification_access_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    builtin_policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    classification_policy_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    classification_policy_hash: Mapped[str | None] = mapped_column(String(64))
    classification_policy_version: Mapped[int | None]
    authorization_generation: Mapped[int | None] = mapped_column(BigInteger)
    source_projection_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    classification_ceiling: Mapped[int] = mapped_column(nullable=False)
    csv_safety_version: Mapped[str] = mapped_column(String(32), nullable=False)
    object_bucket: Mapped[str | None] = mapped_column(String(255))
    object_key: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime: Mapped[str] = mapped_column(String(100), nullable=False)
    row_count: Mapped[int | None] = mapped_column(BigInteger)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    provider_checksum: Mapped[str | None] = mapped_column(String(255))
    completed_at: Mapped[datetime | None]
    access_until: Mapped[datetime] = mapped_column(nullable=False)
