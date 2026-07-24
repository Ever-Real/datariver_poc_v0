from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
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


class ApiProductModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "api_products"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug"),
        UniqueConstraint("workspace_id", "graph_id", "id"),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id"),
            ("knowledge.graphs.workspace_id", "knowledge.graphs.id"),
        ),
        ForeignKeyConstraint(
            ("workspace_id", "id", "current_version_id"),
            (
                "sharing.api_product_versions.workspace_id",
                "sharing.api_product_versions.product_id",
                "sharing.api_product_versions.id",
            ),
            use_alter=True,
        ),
        Index("ix_api_products_workspace_state", "workspace_id", "state", "updated_at"),
        {"schema": "sharing"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    graph_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    classification: Mapped[int] = mapped_column(nullable=False)
    owner_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    current_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))


class ApiProductVersionModel(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "api_product_versions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "product_id", "id"),
        UniqueConstraint("workspace_id", "product_id", "version_no"),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id", "product_id"),
            (
                "sharing.api_products.workspace_id",
                "sharing.api_products.graph_id",
                "sharing.api_products.id",
            ),
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "graph_id", "release_id"),
            (
                "knowledge.releases.workspace_id",
                "knowledge.releases.graph_id",
                "knowledge.releases.id",
            ),
        ),
        Index("ix_api_product_versions_product_state", "product_id", "state", "version_no"),
        {"schema": "sharing"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    product_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    graph_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    release_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version_no: Mapped[int] = mapped_column(nullable=False)
    surface: Mapped[str] = mapped_column(String(32), nullable=False)
    contract_document: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    maximum_hops: Mapped[int] = mapped_column(nullable=False)
    maximum_nodes: Mapped[int] = mapped_column(nullable=False)
    timeout_ms: Mapped[int] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    published_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    published_at: Mapped[datetime | None]


class ConsumerGrantModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "consumer_grants"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        ForeignKeyConstraint(
            ("workspace_id", "product_id", "product_version_id"),
            (
                "sharing.api_product_versions.workspace_id",
                "sharing.api_product_versions.product_id",
                "sharing.api_product_versions.id",
            ),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "consumer_subject_id"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_consumer_grants_consumer_membership",
        ),
        CheckConstraint(
            "(contract_version = 'LEGACY_CLIENT_V1' "
            "AND consumer_subject_id IS NULL AND consumer_issuer IS NULL) OR "
            "(contract_version = 'SUBJECT_CLIENT_V2' "
            "AND consumer_subject_id IS NOT NULL AND consumer_issuer IS NOT NULL "
            "AND length(consumer_issuer) BETWEEN 1 AND 500)",
            name="contract_shape",
        ),
        Index(
            "uq_consumer_grants_legacy_client",
            "workspace_id",
            "product_version_id",
            "consumer_client_id",
            unique=True,
            postgresql_where=text("contract_version = 'LEGACY_CLIENT_V1'"),
        ),
        Index(
            "uq_consumer_grants_v2_subject_client",
            "workspace_id",
            "product_version_id",
            "consumer_subject_id",
            "consumer_client_id",
            unique=True,
            postgresql_where=text("contract_version = 'SUBJECT_CLIENT_V2'"),
        ),
        Index("ix_consumer_grants_client_state", "workspace_id", "consumer_client_id", "state"),
        {"schema": "sharing"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    product_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    product_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    contract_version: Mapped[str] = mapped_column(String(32), nullable=False)
    consumer_subject_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    consumer_issuer: Mapped[str | None] = mapped_column(String(500))
    consumer_client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, nullable=False)
    maximum_classification: Mapped[int] = mapped_column(nullable=False)
    requests_per_minute: Mapped[int] = mapped_column(nullable=False)
    monthly_quota: Mapped[int] = mapped_column(nullable=False)
    valid_from: Mapped[datetime] = mapped_column(nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    revoked_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    revoked_at: Mapped[datetime | None]


class ApiInvocationModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "api_invocations"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "grant_id", "invocation_key"),
        ForeignKeyConstraint(
            ("workspace_id", "grant_id"),
            ("sharing.consumer_grants.workspace_id", "sharing.consumer_grants.id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "actor_id"),
            ("iam.workspace_memberships.workspace_id", "iam.workspace_memberships.subject_id"),
            ondelete="RESTRICT",
            name="fk_api_invocations_actor_membership",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "product_id", "product_version_id"),
            (
                "sharing.api_product_versions.workspace_id",
                "sharing.api_product_versions.product_id",
                "sharing.api_product_versions.id",
            ),
            ondelete="RESTRICT",
            name="fk_api_invocations_product_version",
        ),
        CheckConstraint(
            "units = 1",
            name="single_unit",
        ),
        CheckConstraint(
            "(evidence_kind = 'LEGACY_USAGE_V1' "
            "AND actor_id IS NULL AND consumer_issuer IS NULL "
            "AND consumer_client_id IS NULL AND product_id IS NULL "
            "AND product_version_id IS NULL AND graph_id IS NULL AND release_id IS NULL "
            "AND release_content_hash IS NULL AND surface IS NULL "
            "AND effective_classification IS NULL AND security_scope_hash IS NULL "
            "AND request_hash IS NULL AND result_type IS NULL AND result_hash IS NULL "
            "AND result_size_bytes IS NULL AND retention_data_class IS NULL "
            "AND retention_policy_id IS NULL AND retention_policy_hash IS NULL "
            "AND retention_until IS NULL AND audit_retention_policy_id IS NULL "
            "AND audit_retention_policy_hash IS NULL AND audit_retention_until IS NULL "
            "AND completed_at IS NULL) OR "
            "(evidence_kind = 'ATOMIC_RESULT_V2' "
            "AND actor_id IS NOT NULL AND consumer_issuer IS NOT NULL "
            "AND consumer_client_id IS NOT NULL AND product_id IS NOT NULL "
            "AND product_version_id IS NOT NULL AND graph_id IS NOT NULL "
            "AND release_id IS NOT NULL AND release_content_hash IS NOT NULL "
            "AND surface IS NOT NULL AND effective_classification BETWEEN 0 AND 3 "
            "AND security_scope_hash IS NOT NULL AND request_hash IS NOT NULL "
            "AND result_type IS NOT NULL AND result_hash IS NOT NULL "
            "AND result_size_bytes BETWEEN 2 AND 1048576 "
            "AND retention_data_class IS NOT NULL AND retention_policy_id IS NOT NULL "
            "AND retention_policy_hash IS NOT NULL AND retention_until IS NOT NULL "
            "AND audit_retention_policy_id IS NOT NULL "
            "AND audit_retention_policy_hash IS NOT NULL "
            "AND audit_retention_until IS NOT NULL "
            "AND completed_at IS NOT NULL AND completed_at >= occurred_at "
            "AND retention_until > completed_at "
            "AND audit_retention_until > completed_at)",
            name="evidence_shape",
        ),
        CheckConstraint(
            "evidence_kind = 'LEGACY_USAGE_V1' OR "
            "(invocation_key ~ '^[0-9a-f]{64}$' "
            "AND release_content_hash ~ '^[0-9a-f]{64}$' "
            "AND security_scope_hash ~ '^[0-9a-f]{64}$' "
            "AND request_hash ~ '^[0-9a-f]{64}$' "
            "AND result_hash ~ '^[0-9a-f]{64}$' "
            "AND retention_policy_hash ~ '^[0-9a-f]{64}$' "
            "AND audit_retention_policy_hash ~ '^[0-9a-f]{64}$')",
            name="v2_hashes",
        ),
        CheckConstraint(
            "evidence_kind = 'LEGACY_USAGE_V1' OR "
            "((surface = 'SNAPSHOT' AND result_type = 'SNAPSHOT_V1' "
            "AND requested_scope = 'snapshot.read' "
            "AND retention_data_class = 'OBJECT_DATA') OR "
            "(surface = 'NEIGHBORS' AND result_type = 'NEIGHBORS_V1' "
            "AND requested_scope = 'neighbors.query' "
            "AND retention_data_class = 'OBJECT_DATA') OR "
            "(surface = 'CHAT' AND result_type = 'CHAT_LOCAL_V1' "
            "AND requested_scope = 'chat.query' "
            "AND retention_data_class = 'CHAT_CONTENT'))",
            name="surface_result",
        ),
        Index("ix_api_invocations_grant_time", "grant_id", "occurred_at"),
        {"schema": "sharing"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    grant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    invocation_key: Mapped[str] = mapped_column(String(200), nullable=False)
    evidence_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    consumer_issuer: Mapped[str | None] = mapped_column(String(500))
    consumer_client_id: Mapped[str | None] = mapped_column(String(255))
    product_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    product_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    graph_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    release_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    release_content_hash: Mapped[str | None] = mapped_column(String(64))
    surface: Mapped[str | None] = mapped_column(String(32))
    requested_scope: Mapped[str] = mapped_column(String(100), nullable=False)
    request_id: Mapped[str] = mapped_column(String(100), nullable=False)
    effective_classification: Mapped[int | None] = mapped_column(Integer)
    security_scope_hash: Mapped[str | None] = mapped_column(String(64))
    request_hash: Mapped[str | None] = mapped_column(String(64))
    result_type: Mapped[str | None] = mapped_column(String(32))
    result_hash: Mapped[str | None] = mapped_column(String(64))
    result_size_bytes: Mapped[int | None] = mapped_column(Integer)
    retention_data_class: Mapped[str | None] = mapped_column(String(32))
    retention_policy_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    retention_policy_hash: Mapped[str | None] = mapped_column(String(64))
    retention_until: Mapped[datetime | None]
    audit_retention_policy_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    audit_retention_policy_hash: Mapped[str | None] = mapped_column(String(64))
    audit_retention_until: Mapped[datetime | None]
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)
    completed_at: Mapped[datetime | None]
    units: Mapped[int] = mapped_column(default=1, nullable=False)


class ApiInvocationResultModel(Base):
    __tablename__ = "api_invocation_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ("workspace_id", "invocation_id"),
            ("sharing.api_invocations.workspace_id", "sharing.api_invocations.id"),
            ondelete="RESTRICT",
            name="fk_api_invocation_results_invocation",
        ),
        CheckConstraint(
            "jsonb_typeof(result_document::jsonb) = 'object'",
            name="document_object",
        ),
        CheckConstraint(
            "result_size_bytes BETWEEN 2 AND 1048576 "
            "AND octet_length(convert_to(result_document, 'UTF8')) = result_size_bytes",
            name="size_bound",
        ),
        CheckConstraint(
            "result_hash ~ '^[0-9a-f]{64}$' "
            "AND encode(sha256(convert_to(result_document, 'UTF8')), 'hex') = result_hash",
            name="result_hash",
        ),
        CheckConstraint("classification BETWEEN 0 AND 3", name="classification"),
        CheckConstraint(
            "retention_data_class IN ('OBJECT_DATA', 'CHAT_CONTENT')",
            name="retention_data_class",
        ),
        CheckConstraint("retention_policy_hash ~ '^[0-9a-f]{64}$'", name="policy_hash"),
        CheckConstraint("retention_until > created_at", name="retention_window"),
        Index(
            "ix_api_invocation_results_retention",
            "workspace_id",
            "retention_until",
            "invocation_id",
        ),
        {"schema": "sharing"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    invocation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    consumer_client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    result_type: Mapped[str] = mapped_column(String(32), nullable=False)
    result_document: Mapped[str] = mapped_column(Text, nullable=False)
    result_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    classification: Mapped[int] = mapped_column(Integer, nullable=False)
    retention_data_class: Mapped[str] = mapped_column(String(32), nullable=False)
    retention_policy_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    retention_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    retention_until: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)


class ApiInvocationMonthlyUsageModel(Base):
    __tablename__ = "api_invocation_monthly_usage"
    __table_args__ = (
        ForeignKeyConstraint(
            ("workspace_id", "grant_id"),
            ("sharing.consumer_grants.workspace_id", "sharing.consumer_grants.id"),
            ondelete="RESTRICT",
        ),
        CheckConstraint("units > 0", name="positive_units"),
        CheckConstraint(
            "month_start = date_trunc('month', month_start AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'",
            name="utc_month_start",
        ),
        Index(
            "ix_api_invocation_monthly_usage_grant_month",
            "grant_id",
            "month_start",
        ),
        {"schema": "sharing"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    grant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    month_start: Mapped[datetime] = mapped_column(primary_key=True)
    units: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)
