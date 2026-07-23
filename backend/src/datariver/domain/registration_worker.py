from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RegistrationWorkerCallIdentity:
    """Opaque identity for one orchestrator task call.

    The interface hashes the run/call tuple before constructing this value, so the raw
    orchestrator run id never crosses into durable persistence.
    """

    operation: str
    key_hash: str
    request_hash: str
    worker_subject_id: UUID


@dataclass(frozen=True, slots=True)
class RegistrationWorkerCallReplay:
    result: dict[str, Any]
