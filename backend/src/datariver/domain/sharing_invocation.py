from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from datariver.domain.common import ConflictError, ValidationError, canonical_json_hash

MAX_CANONICAL_RESULT_BYTES = 1_048_576
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class InvocationRequestBinding:
    workspace_id: UUID
    subject_id: UUID
    consumer_issuer: str
    consumer_client_id: str
    security_scopes: frozenset[str]
    grant_id: UUID
    product_id: UUID
    product_version_id: UUID
    graph_id: UUID
    release_id: UUID
    release_content_hash: str
    contract_hash: str
    effective_classification: int
    surface: str
    operation: str
    result_type: str
    requested_scope: str
    payload_document: dict[str, Any]
    request_id: str
    invocation_key: str

    def __post_init__(self) -> None:
        for name, value in (
            ("release content hash", self.release_content_hash),
            ("contract hash", self.contract_hash),
        ):
            if not _SHA256_PATTERN.fullmatch(value):
                raise ValidationError(f"The {name} must be a lowercase SHA-256 value.")
        if not 0 <= self.effective_classification <= 3:
            raise ValidationError("The effective invocation classification is invalid.")
        if not self.consumer_issuer.strip() or len(self.consumer_issuer) > 500:
            raise ValidationError("The invocation consumer issuer is invalid.")
        if not self.consumer_client_id.strip() or len(self.consumer_client_id) > 255:
            raise ValidationError("The invocation consumer client is invalid.")


@dataclass(frozen=True, slots=True)
class LegacyInvocation:
    invocation_id: UUID


@dataclass(frozen=True, slots=True)
class CompletedInvocation:
    invocation_id: UUID
    request_hash: str
    result_document: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CanonicalInvocationResult:
    document: dict[str, Any]
    encoded: bytes
    size_bytes: int
    content_hash: str


def canonical_invocation_request_hash(binding: InvocationRequestBinding) -> str:
    payload = _normalized_payload(binding.surface, binding.payload_document)
    return canonical_json_hash(
        {
            "contract_version": "ATOMIC_RESULT_V2",
            "workspace_id": str(binding.workspace_id),
            "subject_id": str(binding.subject_id),
            "consumer_issuer": binding.consumer_issuer,
            "consumer_client_id": binding.consumer_client_id,
            "security_scopes": sorted(binding.security_scopes),
            "grant_id": str(binding.grant_id),
            "product_id": str(binding.product_id),
            "product_version_id": str(binding.product_version_id),
            "graph_id": str(binding.graph_id),
            "release_id": str(binding.release_id),
            "release_content_hash": binding.release_content_hash,
            "contract_hash": binding.contract_hash,
            "effective_classification": binding.effective_classification,
            "surface": binding.surface,
            "operation": binding.operation,
            "result_type": binding.result_type,
            "requested_scope": binding.requested_scope,
            "payload": payload,
        }
    )


def validate_canonical_result(document: object) -> CanonicalInvocationResult:
    if not isinstance(document, dict):
        raise ValidationError("An API-product result must be a JSON object.")
    try:
        encoded = json.dumps(
            document,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValidationError("The API-product result is not canonical JSON.") from error
    if len(encoded) > MAX_CANONICAL_RESULT_BYTES:
        raise ValidationError("The API-product result exceeds the 1 MiB contract.")
    return CanonicalInvocationResult(
        document=document,
        encoded=encoded,
        size_bytes=len(encoded),
        content_hash=hashlib.sha256(encoded).hexdigest(),
    )


async def execute_or_replay_invocation(
    *,
    existing: LegacyInvocation | CompletedInvocation | None,
    request_hash: str,
    executor: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    if isinstance(existing, LegacyInvocation):
        raise ConflictError(
            "The legacy invocation has no replayable result; use a new idempotency key."
        )
    if isinstance(existing, CompletedInvocation):
        if existing.request_hash != request_hash:
            raise ConflictError("The invocation key was used with a different request.")
        return validate_canonical_result(existing.result_document).document
    return validate_canonical_result(await executor()).document


def _normalized_payload(surface: str, payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    if surface == "NEIGHBORS" and "edge_types" in normalized:
        edge_types = normalized["edge_types"]
        if not isinstance(edge_types, (list, tuple, set, frozenset)):
            raise ValidationError("Neighbor edge types must be a collection.")
        normalized["edge_types"] = sorted(str(value) for value in edge_types)
    return normalized
