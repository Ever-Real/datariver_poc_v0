from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from datariver.application.dto import ChatEvidence
from datariver.application.evidence import evidence_chunk_is_valid
from datariver.domain.authz import Classification
from datariver.domain.common import ValidationError, uuid7
from datariver.domain.inference_provider import (
    InferenceProviderProfileState,
    ProviderKind,
)

INFERENCE_CONTRACT_VERSION = 1
MAXIMUM_INFERENCE_EVIDENCE = 10
MAXIMUM_INFERENCE_ANSWER_CHARACTERS = 16_000
UNVERIFIABLE_INFERENCE_ANSWER = "검증 불가"

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_ROUTE_KEY_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?")


class InferenceExecutionState(StrEnum):
    COMPLETED = "COMPLETED"
    REFUSED = "REFUSED"


class InferenceRefusalCode(StrEnum):
    INVALID_PROVIDER_OUTPUT = "INVALID_PROVIDER_OUTPUT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class InferencePolicySnapshot:
    workspace_id: UUID
    policy_id: UUID
    policy_version: int
    policy_hash: str
    authorization_generation: int
    required_jurisdiction: str
    evaluated_at: datetime
    schema_version: int = INFERENCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        if self.policy_version < 1 or self.authorization_generation < 0:
            raise ValidationError("The inference policy snapshot version is invalid.")
        _require_sha256(self.policy_hash, "inference policy hash")
        _require_jurisdiction(self.required_jurisdiction, "required jurisdiction")
        _require_aware(self.evaluated_at, "inference policy evaluation")


@dataclass(frozen=True, slots=True)
class InferenceAttestationSnapshot:
    fingerprint: str
    observed_at: datetime
    expires_at: datetime
    schema_version: int = INFERENCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        _require_sha256(self.fingerprint, "inference attestation fingerprint")
        _require_aware(self.observed_at, "inference attestation observation")
        _require_aware(self.expires_at, "inference attestation expiry")
        if self.expires_at <= self.observed_at:
            raise ValidationError("The inference attestation validity interval is invalid.")

    def is_current(self, *, at: datetime) -> bool:
        return _is_aware(at) and self.observed_at <= at < self.expires_at


@dataclass(frozen=True, slots=True)
class InferenceProviderSnapshot:
    workspace_id: UUID
    provider_profile_version_id: UUID
    profile_version: int
    payload_hash: str
    state: InferenceProviderProfileState
    kind: ProviderKind
    server_route_key: str
    jurisdiction: str
    maximum_classification: Classification
    residency_attestation: InferenceAttestationSnapshot
    zero_retention_attestation: InferenceAttestationSnapshot
    schema_version: int = INFERENCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        if self.profile_version < 1:
            raise ValidationError("The inference provider profile version is invalid.")
        _require_sha256(self.payload_hash, "inference provider profile hash")
        if not isinstance(self.state, InferenceProviderProfileState):
            raise ValidationError("The inference provider state is invalid.")
        if not isinstance(self.kind, ProviderKind):
            raise ValidationError("The inference provider kind is invalid.")
        if not _ROUTE_KEY_PATTERN.fullmatch(self.server_route_key):
            raise ValidationError("The server-side inference route key is invalid.")
        _require_jurisdiction(self.jurisdiction, "provider jurisdiction")
        if not isinstance(self.maximum_classification, Classification):
            raise ValidationError("The provider classification ceiling is invalid.")
        if self.maximum_classification is Classification.RESTRICTED:
            raise ValidationError("An inference provider cannot process RESTRICTED evidence.")
        if (
            self.kind is ProviderKind.EXTERNAL
            and self.maximum_classification > Classification.INTERNAL
        ):
            raise ValidationError("An external provider cannot process protected evidence.")


@dataclass(frozen=True, slots=True)
class AuthorizedEvidenceSnapshot:
    evidence: ChatEvidence
    schema_version: int = INFERENCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        if not evidence_chunk_is_valid(self.evidence):
            raise ValidationError("The authorized evidence chunk failed its integrity check.")
        if not 1 <= len(self.evidence.name) <= 500:
            raise ValidationError("The authorized evidence name is outside the contract bound.")
        if self.evidence.description is not None and len(self.evidence.description) > 4_000:
            raise ValidationError(
                "The authorized evidence description is outside the contract bound."
            )
        if not 1 <= len(self.evidence.source_locator) <= 2_048:
            raise ValidationError("The authorized evidence locator is outside the contract bound.")
        if not 1 <= len(self.evidence.source_version) <= 255:
            raise ValidationError("The authorized evidence version is outside the contract bound.")
        if not 1 <= len(self.evidence.extraction_method) <= 100:
            raise ValidationError(
                "The authorized evidence extraction method is outside the contract bound."
            )


@dataclass(frozen=True, slots=True)
class InferenceRoutingSnapshot:
    route_decision_id: UUID
    workspace_id: UUID
    effective_classification: Classification
    policy: InferencePolicySnapshot
    provider: InferenceProviderSnapshot
    routed_at: datetime
    schema_version: int = INFERENCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        _require_aware(self.routed_at, "inference routing decision")
        if self.effective_classification is Classification.RESTRICTED:
            raise ValidationError("RESTRICTED evidence cannot enter inference.")
        if not isinstance(self.effective_classification, Classification):
            raise ValidationError("The effective inference classification is invalid.")
        if (
            self.workspace_id != self.policy.workspace_id
            or self.workspace_id != self.provider.workspace_id
        ):
            raise ValidationError("The inference routing snapshot crosses a workspace boundary.")
        if self.policy.evaluated_at > self.routed_at:
            raise ValidationError("The inference policy snapshot is newer than its route.")
        if self.provider.state is not InferenceProviderProfileState.APPROVED:
            raise ValidationError("The inference provider profile is not approved.")
        if self.provider.jurisdiction != self.policy.required_jurisdiction:
            raise ValidationError("The inference route crosses the approved jurisdiction.")
        if self.effective_classification > self.provider.maximum_classification:
            raise ValidationError(
                "The inference route exceeds the provider classification ceiling."
            )
        if not self.provider.residency_attestation.is_current(at=self.routed_at):
            raise ValidationError("The provider residency attestation is not current.")
        if not self.provider.zero_retention_attestation.is_current(at=self.routed_at):
            raise ValidationError("The provider zero-retention attestation is not current.")


@dataclass(frozen=True, slots=True)
class AuthorizedInferencePackage:
    package_id: UUID
    workspace_id: UUID
    subject_id: UUID
    request_id: str
    question: str
    evidence: tuple[AuthorizedEvidenceSnapshot, ...]
    route: InferenceRoutingSnapshot
    schema_version: int = INFERENCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        if not 1 <= len(self.evidence) <= MAXIMUM_INFERENCE_EVIDENCE:
            raise ValidationError("The authorized inference evidence count is invalid.")
        if not 1 <= len(self.request_id) <= 128 or any(
            character in self.request_id for character in "\r\n\x00"
        ):
            raise ValidationError("The inference request ID is invalid.")
        if not 2 <= len(self.question.strip()) <= 4_000:
            raise ValidationError("The inference question length is invalid.")
        if self.workspace_id != self.route.workspace_id:
            raise ValidationError("The inference package route crosses a workspace boundary.")
        chunks = tuple(item.evidence for item in self.evidence)
        if any(item.workspace_id != self.workspace_id for item in chunks):
            raise ValidationError("The inference package evidence crosses a workspace boundary.")
        if len({item.chunk_id for item in chunks}) != len(chunks):
            raise ValidationError("The inference package contains duplicate evidence chunks.")
        if any(
            item.effective_from > self.route.routed_at
            or (item.effective_until is not None and item.effective_until <= self.route.routed_at)
            for item in chunks
        ):
            raise ValidationError("The inference package contains inactive evidence.")
        maximum = max(item.classification for item in chunks)
        if maximum is Classification.RESTRICTED:
            raise ValidationError("RESTRICTED evidence cannot enter inference.")
        if self.route.effective_classification is not maximum:
            raise ValidationError(
                "The inference route does not match the highest evidence classification."
            )

    @classmethod
    def create(
        cls,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        request_id: str,
        question: str,
        evidence: tuple[ChatEvidence, ...],
        policy: InferencePolicySnapshot,
        provider: InferenceProviderSnapshot,
        routed_at: datetime,
    ) -> AuthorizedInferencePackage:
        if not evidence:
            raise ValidationError("Inference requires authorized evidence.")
        effective_classification = max(item.classification for item in evidence)
        route = InferenceRoutingSnapshot(
            route_decision_id=uuid7(),
            workspace_id=workspace_id,
            effective_classification=effective_classification,
            policy=policy,
            provider=provider,
            routed_at=routed_at,
        )
        return cls(
            package_id=uuid7(),
            workspace_id=workspace_id,
            subject_id=subject_id,
            request_id=request_id,
            question=question.strip(),
            evidence=tuple(AuthorizedEvidenceSnapshot(item) for item in evidence),
            route=route,
        )


@dataclass(frozen=True, slots=True)
class ProviderInferenceDraft:
    answer: str
    cited_chunk_ids: tuple[UUID, ...]
    input_tokens: int
    output_tokens: int
    time_to_first_token_ms: int
    duration_ms: int
    schema_version: int = INFERENCE_CONTRACT_VERSION


@dataclass(frozen=True, slots=True)
class InferenceCitation:
    chunk_id: UUID
    rank: int
    source_locator: str
    source_version: str
    content_hash: str
    schema_version: int = INFERENCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        if self.rank < 1:
            raise ValidationError("The inference citation rank is invalid.")
        if (
            not self.source_locator.strip()
            or len(self.source_locator) > 2_048
            or not self.source_version.strip()
            or len(self.source_version) > 255
        ):
            raise ValidationError("The inference citation source is invalid.")
        _require_sha256(self.content_hash, "inference citation content hash")


@dataclass(frozen=True, slots=True)
class InferenceExecutionResult:
    route_decision_id: UUID
    provider_profile_version_id: UUID
    effective_classification: Classification
    state: InferenceExecutionState
    answer: str
    citations: tuple[InferenceCitation, ...]
    refusal_code: InferenceRefusalCode | None
    input_tokens: int | None
    output_tokens: int | None
    time_to_first_token_ms: int | None
    duration_ms: int | None
    schema_version: int = INFERENCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        if not isinstance(self.state, InferenceExecutionState):
            raise ValidationError("The inference execution state is invalid.")
        if (
            not isinstance(self.effective_classification, Classification)
            or self.effective_classification is Classification.RESTRICTED
        ):
            raise ValidationError("The inference result classification is invalid.")
        if not self.answer.strip() or len(self.answer) > MAXIMUM_INFERENCE_ANSWER_CHARACTERS:
            raise ValidationError("The inference result answer is outside the contract bound.")
        if len(self.citations) > MAXIMUM_INFERENCE_EVIDENCE:
            raise ValidationError("The inference result citation count is invalid.")
        ranks = tuple(item.rank for item in self.citations)
        chunk_ids = tuple(item.chunk_id for item in self.citations)
        if ranks != tuple(range(1, len(self.citations) + 1)) or len(chunk_ids) != len(
            set(chunk_ids)
        ):
            raise ValidationError("The inference result citations are inconsistent.")
        metrics = (
            self.input_tokens,
            self.output_tokens,
            self.time_to_first_token_ms,
            self.duration_ms,
        )
        if self.state is InferenceExecutionState.COMPLETED:
            if (
                not self.citations
                or self.refusal_code is not None
                or any(value is None for value in metrics)
            ):
                raise ValidationError("The completed inference result is incomplete.")
            return
        if (
            self.answer != UNVERIFIABLE_INFERENCE_ANSWER
            or self.citations
            or not isinstance(self.refusal_code, InferenceRefusalCode)
            or any(value is not None for value in metrics)
        ):
            raise ValidationError("The refused inference result is inconsistent.")


def finalize_inference_draft(
    *,
    package: AuthorizedInferencePackage,
    draft: ProviderInferenceDraft,
) -> InferenceExecutionResult:
    evidence_by_id = {item.evidence.chunk_id: item.evidence for item in package.evidence}
    cited_ids = draft.cited_chunk_ids
    invalid = (
        draft.schema_version != INFERENCE_CONTRACT_VERSION
        or not draft.answer.strip()
        or len(draft.answer) > MAXIMUM_INFERENCE_ANSWER_CHARACTERS
        or not cited_ids
        or len(cited_ids) > MAXIMUM_INFERENCE_EVIDENCE
        or len(cited_ids) != len(set(cited_ids))
        or any(chunk_id not in evidence_by_id for chunk_id in cited_ids)
        or not _bounded_metric(draft.input_tokens, maximum=10_000_000)
        or not _bounded_metric(draft.output_tokens, maximum=1_000_000)
        or not _bounded_metric(draft.time_to_first_token_ms, maximum=3_600_000)
        or not _bounded_metric(draft.duration_ms, maximum=86_400_000)
        or draft.time_to_first_token_ms > draft.duration_ms
    )
    if invalid:
        return refused_inference_result(
            package=package,
            code=InferenceRefusalCode.INVALID_PROVIDER_OUTPUT,
        )
    citations = tuple(
        InferenceCitation(
            chunk_id=chunk_id,
            rank=rank,
            source_locator=evidence_by_id[chunk_id].source_locator,
            source_version=evidence_by_id[chunk_id].source_version,
            content_hash=evidence_by_id[chunk_id].content_hash,
        )
        for rank, chunk_id in enumerate(cited_ids, start=1)
    )
    return InferenceExecutionResult(
        route_decision_id=package.route.route_decision_id,
        provider_profile_version_id=package.route.provider.provider_profile_version_id,
        effective_classification=package.route.effective_classification,
        state=InferenceExecutionState.COMPLETED,
        answer=draft.answer.strip(),
        citations=citations,
        refusal_code=None,
        input_tokens=draft.input_tokens,
        output_tokens=draft.output_tokens,
        time_to_first_token_ms=draft.time_to_first_token_ms,
        duration_ms=draft.duration_ms,
    )


def refused_inference_result(
    *,
    package: AuthorizedInferencePackage,
    code: InferenceRefusalCode,
) -> InferenceExecutionResult:
    return InferenceExecutionResult(
        route_decision_id=package.route.route_decision_id,
        provider_profile_version_id=package.route.provider.provider_profile_version_id,
        effective_classification=package.route.effective_classification,
        state=InferenceExecutionState.REFUSED,
        answer=UNVERIFIABLE_INFERENCE_ANSWER,
        citations=(),
        refusal_code=code,
        input_tokens=None,
        output_tokens=None,
        time_to_first_token_ms=None,
        duration_ms=None,
    )


def _bounded_metric(value: object, *, maximum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= maximum


def _require_schema_version(value: int) -> None:
    if value != INFERENCE_CONTRACT_VERSION:
        raise ValidationError("The assistant inference contract version is unsupported.")


def _require_sha256(value: str, name: str) -> None:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValidationError(f"The {name} is invalid.")


def _require_jurisdiction(value: str, name: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > 64
        or "://" in value
        or any(character in value for character in "\r\n\x00")
    ):
        raise ValidationError(f"The {name} is invalid.")


def _is_aware(value: object) -> bool:
    return (
        isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
    )


def _require_aware(value: datetime, name: str) -> None:
    if not _is_aware(value):
        raise ValidationError(f"The {name} timestamp must include a timezone.")
