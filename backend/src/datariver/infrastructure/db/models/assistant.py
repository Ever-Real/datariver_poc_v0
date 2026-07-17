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


class ChatSessionModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        Index("ix_chat_sessions_owner", "workspace_id", "owner_id", "updated_at"),
        UniqueConstraint("workspace_id", "id"),
        ForeignKeyConstraint(
            ("workspace_id", "retention_policy_id", "retention_policy_hash"),
            (
                "retention.policy_versions.workspace_id",
                "retention.policy_versions.id",
                "retention.policy_versions.payload_hash",
            ),
            name="fk_chat_sessions_retention_policy_binding",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "retention_binding_version IN ('LEGACY_UNBOUND_V1', 'ACTIVE_POLICY_V1')",
            name="retention_binding_version_allowlist",
        ),
        CheckConstraint(
            "(retention_binding_version = 'LEGACY_UNBOUND_V1' "
            "AND retention_policy_id IS NULL AND retention_policy_hash IS NULL "
            "AND retention_basis_at IS NULL) OR "
            "(retention_binding_version = 'ACTIVE_POLICY_V1' "
            "AND retention_policy_id IS NOT NULL AND retention_policy_hash IS NOT NULL "
            "AND retention_basis_at IS NOT NULL AND retention_until IS NOT NULL)",
            name="retention_binding_shape",
        ),
        CheckConstraint(
            "retention_policy_hash IS NULL OR retention_policy_hash ~ '^[0-9a-f]{64}$'",
            name="retention_policy_hash_sha256",
        ),
        CheckConstraint(
            "retention_until IS NULL OR retention_basis_at IS NULL "
            "OR retention_until > retention_basis_at",
            name="retention_window",
        ),
        {"schema": "assistant"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    scope: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)
    retention_until: Mapped[datetime | None]
    retention_policy_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    retention_policy_hash: Mapped[str | None] = mapped_column(String(64))
    retention_basis_at: Mapped[datetime | None]
    retention_binding_version: Mapped[str] = mapped_column(
        String(32), server_default=text("'ACTIVE_POLICY_V1'"), nullable=False
    )


class ChatMessageModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_session_time", "session_id", "created_at"),
        UniqueConstraint("workspace_id", "session_id", "id"),
        ForeignKeyConstraint(
            ("workspace_id", "session_id"),
            ("assistant.chat_sessions.workspace_id", "assistant.chat_sessions.id"),
            ondelete="CASCADE",
        ),
        {"schema": "assistant"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    actor: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    content_ref: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(nullable=False)


class AssistantRunModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "assistant_runs"
    __table_args__ = (
        Index("ix_assistant_runs_session", "session_id", "started_at"),
        UniqueConstraint("workspace_id", "id"),
        ForeignKeyConstraint(
            ("workspace_id", "session_id"),
            ("assistant.chat_sessions.workspace_id", "assistant.chat_sessions.id"),
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("workspace_id", "session_id", "request_message_id"),
            (
                "assistant.chat_messages.workspace_id",
                "assistant.chat_messages.session_id",
                "assistant.chat_messages.id",
            ),
        ),
        {"schema": "assistant"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    request_message_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_template_version: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_decision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    finished_at: Mapped[datetime | None]


class EvidenceCitationModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "evidence_citations"
    __table_args__ = (
        Index("ix_evidence_citations_run_rank", "run_id", "rank"),
        UniqueConstraint("workspace_id", "run_id", "chunk_id"),
        UniqueConstraint("workspace_id", "run_id", "rank"),
        CheckConstraint(
            "classification >= 0 AND classification <= 3",
            name="classification_range",
        ),
        CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="effective_window",
        ),
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="content_hash_sha256",
        ),
        CheckConstraint("rank > 0", name="rank_positive"),
        ForeignKeyConstraint(
            ("workspace_id", "run_id"),
            ("assistant.assistant_runs.workspace_id", "assistant.assistant_runs.id"),
            ondelete="CASCADE",
        ),
        {"schema": "assistant"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    chunk_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    classification: Mapped[int] = mapped_column(Integer, nullable=False)
    system_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    domain_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    owner_department_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_locator: Mapped[str] = mapped_column(Text, nullable=False)
    source_version: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(nullable=False)
    effective_until: Mapped[datetime | None]
    extraction_method: Mapped[str] = mapped_column(String(100), nullable=False)
    rank: Mapped[int] = mapped_column(nullable=False)
