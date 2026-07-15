from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from datariver.infrastructure.db.base import (
    JSON_DOCUMENT,
    Base,
    TimestampMixin,
    UuidPrimaryKeyMixin,
    VersionMixin,
)


class ResourceModel(Base, UuidPrimaryKeyMixin, TimestampMixin, VersionMixin):
    __tablename__ = "resources"
    __table_args__ = (
        UniqueConstraint("workspace_id", "resource_type", "resource_key"),
        Index("ix_resources_scope", "workspace_id", "classification", "system_id", "domain_id"),
        {"schema": "authz"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_key: Mapped[str] = mapped_column(String(500), nullable=False)
    owner_department_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    system_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    domain_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    classification: Mapped[int] = mapped_column(default=0, nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(50), default="ACTIVE", nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class PolicyDecisionModel(Base, UuidPrimaryKeyMixin):
    __tablename__ = "policy_decisions"
    __table_args__ = (
        Index("ix_policy_decisions_workspace_time", "workspace_id", "decided_at"),
        {"schema": "authz"},
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    subject_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    effect: Mapped[str] = mapped_column(String(10), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, nullable=False)
    policy_versions: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, nullable=False)
    evaluation_context: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    request_id: Mapped[str] = mapped_column(String(100), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(nullable=False)
