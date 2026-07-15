from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKeyConstraint, Index, String, Text, UniqueConstraint, Uuid
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
        {"schema": "assistant"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    scope: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)
    retention_until: Mapped[datetime | None]


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
        ForeignKeyConstraint(
            ("workspace_id", "run_id"),
            ("assistant.assistant_runs.workspace_id", "assistant.assistant_runs.id"),
            ondelete="CASCADE",
        ),
        {"schema": "assistant"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_locator: Mapped[str] = mapped_column(Text, nullable=False)
    source_version: Mapped[str] = mapped_column(String(255), nullable=False)
    excerpt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rank: Mapped[int] = mapped_column(nullable=False)
