from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


def utc_now() -> datetime:
    return datetime.now(UTC)


def uuid7() -> UUID:
    """Return a time-sortable UUIDv7 without a third-party runtime dependency."""
    timestamp_ms = time.time_ns() // 1_000_000
    value = (timestamp_ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76
    value |= secrets.randbits(12) << 64
    value |= 0b10 << 62
    value |= secrets.randbits(62)
    return UUID(int=value)


def canonical_json_hash(value: Any) -> str:
    """Hash JSON by content so adapters and workers can reconcile deterministically."""
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class DomainError(Exception):
    code = "domain_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ValidationError(DomainError):
    code = "validation_error"


class ConflictError(DomainError):
    code = "conflict"


class ForbiddenError(DomainError):
    code = "forbidden"


class NotFoundError(DomainError):
    code = "not_found"


class RateLimitError(DomainError):
    code = "rate_limit_exceeded"


class Effect(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"


@dataclass(frozen=True, slots=True)
class DomainEvent:
    event_id: UUID
    event_type: str
    aggregate_type: str
    aggregate_id: UUID
    workspace_id: UUID
    payload: dict[str, Any]
    occurred_at: datetime

    @classmethod
    def create(
        cls,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: UUID,
        workspace_id: UUID,
        payload: dict[str, Any],
    ) -> DomainEvent:
        return cls(
            event_id=uuid7(),
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            workspace_id=workspace_id,
            payload=payload,
            occurred_at=utc_now(),
        )
