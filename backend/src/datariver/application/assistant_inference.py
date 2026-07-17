from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TypeGuard
from uuid import UUID

from datariver.application.dto import ChatEvidence
from datariver.application.evidence import evidence_chunk_is_valid
from datariver.domain.authz import Classification
from datariver.domain.common import ValidationError, canonical_json_hash, uuid7
from datariver.domain.inference_provider import (
    InferenceProviderProfileState,
    ProviderKind,
)

INFERENCE_CONTRACT_VERSION = 2
MAXIMUM_INFERENCE_EVIDENCE = 10
MAXIMUM_INFERENCE_ANSWER_CHARACTERS = 16_000
UNVERIFIABLE_INFERENCE_ANSWER = "보안 규정 및 근거 데이터 부족으로 답변할 수 없습니다"

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_ROUTE_KEY_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?")
_RUNTIME_IDENTITY_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._:/-]{0,254}[A-Za-z0-9])?")
_TIMEZONE_IDENTITY_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._+:/-]{0,62}[A-Za-z0-9])?")
_CANONICAL_URN_PATTERN = re.compile(
    r"urn:[a-z0-9][a-z0-9-]{0,31}:[A-Za-z0-9][A-Za-z0-9._~!$&'()*+,;=:@%/?#-]*"
)


class InferenceExecutionState(StrEnum):
    COMPLETED = "COMPLETED"
    REFUSED = "REFUSED"


class InferenceRefusalCode(StrEnum):
    INVALID_PROVIDER_OUTPUT = "INVALID_PROVIDER_OUTPUT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    GROUNDING_UNAVAILABLE = "GROUNDING_UNAVAILABLE"
    INSUFFICIENT_GROUNDING = "INSUFFICIENT_GROUNDING"


class InferenceBudgetMode(StrEnum):
    MONITOR_ONLY = "MONITOR_ONLY"
    HARD_LIMIT = "HARD_LIMIT"


class InferenceBudgetState(StrEnum):
    OBSERVED = "OBSERVED"
    RESERVED = "RESERVED"
    EXCEEDED = "EXCEEDED"


class InferenceRouteReason(StrEnum):
    PRIMARY = "PRIMARY"
    BUDGET_LIMIT_FALLBACK = "BUDGET_LIMIT_FALLBACK"


class InferenceGroundingMetric(StrEnum):
    COSINE_SIMILARITY = "COSINE_SIMILARITY"


class InferenceUsageState(StrEnum):
    UNAVAILABLE = "UNAVAILABLE"
    OBSERVED = "OBSERVED"


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
class InferenceGroundingPolicySnapshot:
    workspace_id: UUID
    policy_id: UUID
    policy_version: int
    policy_hash: str
    metric: InferenceGroundingMetric
    minimum_score_millionths: int
    evaluator_version: str
    evaluated_at: datetime
    schema_version: int = INFERENCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        if self.policy_version < 1:
            raise ValidationError("The grounding policy version is invalid.")
        _require_sha256(self.policy_hash, "grounding policy hash")
        if not isinstance(self.metric, InferenceGroundingMetric):
            raise ValidationError("The grounding policy metric is invalid.")
        if (
            not isinstance(self.minimum_score_millionths, int)
            or isinstance(self.minimum_score_millionths, bool)
            or not 1 <= self.minimum_score_millionths <= 1_000_000
        ):
            raise ValidationError("The grounding policy threshold is invalid.")
        _require_runtime_identity(self.evaluator_version, "grounding evaluator version")
        _require_aware(self.evaluated_at, "grounding policy evaluation")


@dataclass(frozen=True, slots=True)
class InferenceBudgetSnapshot:
    """Immutable result of a durable monthly usage reservation or observation."""

    budget_decision_id: UUID
    workspace_id: UUID
    subject_id: UUID
    policy_version: int
    policy_hash: str
    period_start: datetime
    period_end: datetime
    period_timezone: str
    mode: InferenceBudgetMode
    state: InferenceBudgetState
    estimated_tokens: int
    workspace_consumed_tokens: int
    subject_consumed_tokens: int
    workspace_limit_tokens: int | None
    subject_limit_tokens: int | None
    reservation_id: UUID | None
    decided_at: datetime
    schema_version: int = INFERENCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        if self.policy_version < 1:
            raise ValidationError("The inference budget policy version is invalid.")
        _require_sha256(self.policy_hash, "inference budget policy hash")
        for value in (
            self.estimated_tokens,
            self.workspace_consumed_tokens,
            self.subject_consumed_tokens,
        ):
            if not _bounded_metric(value, maximum=10**15):
                raise ValidationError("The inference budget token value is invalid.")
        if self.estimated_tokens < 1:
            raise ValidationError("The inference budget estimate must be positive.")
        _require_aware(self.period_start, "inference budget period start")
        _require_aware(self.period_end, "inference budget period end")
        _require_aware(self.decided_at, "inference budget decision")
        _require_timezone_identity(self.period_timezone)
        if (
            self.period_start.tzinfo is None
            or self.period_end.tzinfo is None
            or str(self.period_start.tzinfo) != self.period_timezone
            or str(self.period_end.tzinfo) != self.period_timezone
        ):
            raise ValidationError("The inference budget period timezone is not bound to its dates.")
        local_start = self.period_start
        local_end = self.period_end
        if (
            local_start.day != 1
            or any(
                (local_start.hour, local_start.minute, local_start.second, local_start.microsecond)
            )
            or local_end.day != 1
            or any((local_end.hour, local_end.minute, local_end.second, local_end.microsecond))
            or (local_end.year, local_end.month)
            != (
                (local_start.year + 1, 1)
                if local_start.month == 12
                else (local_start.year, local_start.month + 1)
            )
        ):
            raise ValidationError("The inference budget period must be one calendar month.")
        if not self.period_start <= self.decided_at < self.period_end:
            raise ValidationError("The inference budget decision is outside its accounting period.")
        if not isinstance(self.mode, InferenceBudgetMode) or not isinstance(
            self.state, InferenceBudgetState
        ):
            raise ValidationError("The inference budget mode or state is invalid.")
        if self.mode is InferenceBudgetMode.MONITOR_ONLY:
            if (
                self.state is not InferenceBudgetState.OBSERVED
                or self.workspace_limit_tokens is not None
                or self.subject_limit_tokens is not None
                or self.reservation_id is not None
            ):
                raise ValidationError("A monitor-only budget cannot authorize or deny inference.")
            return
        limits = (self.workspace_limit_tokens, self.subject_limit_tokens)
        if any(
            not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 10**15
            for value in limits
        ):
            raise ValidationError(
                "A hard token budget requires positive workspace and user limits."
            )
        assert self.workspace_limit_tokens is not None
        assert self.subject_limit_tokens is not None
        workspace_fits = (
            self.workspace_consumed_tokens + self.estimated_tokens <= self.workspace_limit_tokens
        )
        subject_fits = (
            self.subject_consumed_tokens + self.estimated_tokens <= self.subject_limit_tokens
        )
        if self.state is InferenceBudgetState.RESERVED:
            if self.reservation_id is None or not workspace_fits or not subject_fits:
                raise ValidationError("The inference token reservation exceeds its hard limit.")
            return
        if self.state is InferenceBudgetState.EXCEEDED:
            if self.reservation_id is not None or (workspace_fits and subject_fits):
                raise ValidationError("The inference budget denial does not exceed a hard limit.")
            return
        raise ValidationError("A hard token budget must be reserved or exceeded.")


@dataclass(frozen=True, slots=True)
class InferenceProviderSnapshot:
    workspace_id: UUID
    provider_profile_version_id: UUID
    profile_version: int
    payload_hash: str
    state: InferenceProviderProfileState
    kind: ProviderKind
    server_route_key: str
    provider_identity: str
    model_identity: str
    deployment_identity: str
    jurisdiction: str
    region: str
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
        _require_runtime_identity(self.provider_identity, "provider identity")
        _require_runtime_identity(self.model_identity, "model identity")
        _require_runtime_identity(self.deployment_identity, "deployment identity")
        _require_jurisdiction(self.jurisdiction, "provider jurisdiction")
        _require_runtime_identity(self.region, "provider region", maximum=64)
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
        _require_canonical_urn(self.evidence.source_locator, "authorized evidence source")
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
    grounding_policy: InferenceGroundingPolicySnapshot
    requested_provider: InferenceProviderSnapshot
    provider: InferenceProviderSnapshot
    requested_budget: InferenceBudgetSnapshot
    execution_budget: InferenceBudgetSnapshot
    selection_reason: InferenceRouteReason
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
            or self.workspace_id != self.grounding_policy.workspace_id
            or self.workspace_id != self.requested_provider.workspace_id
            or self.workspace_id != self.provider.workspace_id
            or self.workspace_id != self.requested_budget.workspace_id
            or self.workspace_id != self.execution_budget.workspace_id
        ):
            raise ValidationError("The inference routing snapshot crosses a workspace boundary.")
        if any(
            evaluated_at > self.routed_at
            for evaluated_at in (
                self.policy.evaluated_at,
                self.grounding_policy.evaluated_at,
                self.requested_budget.decided_at,
                self.execution_budget.decided_at,
            )
        ):
            raise ValidationError("The inference policy snapshot is newer than its route.")
        for budget in (self.requested_budget, self.execution_budget):
            if not budget.period_start <= self.routed_at < budget.period_end:
                raise ValidationError(
                    "The inference route is outside its budget accounting period."
                )
        _assert_provider_eligible(
            provider=self.requested_provider,
            effective_classification=self.effective_classification,
            required_jurisdiction=self.policy.required_jurisdiction,
            routed_at=self.routed_at,
        )
        _assert_provider_eligible(
            provider=self.provider,
            effective_classification=self.effective_classification,
            required_jurisdiction=self.policy.required_jurisdiction,
            routed_at=self.routed_at,
        )
        if not isinstance(self.selection_reason, InferenceRouteReason):
            raise ValidationError("The inference route selection reason is invalid.")
        if self.selection_reason is InferenceRouteReason.PRIMARY:
            if (
                self.provider != self.requested_provider
                or self.requested_budget != self.execution_budget
            ):
                raise ValidationError("A primary inference route changed its approved provider.")
            if self.provider.kind is ProviderKind.INTERNAL:
                if (
                    self.execution_budget.mode is not InferenceBudgetMode.MONITOR_ONLY
                    or self.execution_budget.state is not InferenceBudgetState.OBSERVED
                ):
                    raise ValidationError(
                        "Internal inference must use monitor-only token accounting."
                    )
                return
            if (
                self.execution_budget.mode is not InferenceBudgetMode.HARD_LIMIT
                or self.execution_budget.state is not InferenceBudgetState.RESERVED
            ):
                raise ValidationError("External inference requires a durable token reservation.")
            return
        if (
            self.selection_reason is not InferenceRouteReason.BUDGET_LIMIT_FALLBACK
            or self.requested_provider.kind is not ProviderKind.EXTERNAL
            or self.provider.kind is not ProviderKind.INTERNAL
            or self.requested_provider.provider_profile_version_id
            == self.provider.provider_profile_version_id
            or self.requested_budget.mode is not InferenceBudgetMode.HARD_LIMIT
            or self.requested_budget.state is not InferenceBudgetState.EXCEEDED
            or self.execution_budget.mode is not InferenceBudgetMode.MONITOR_ONLY
            or self.execution_budget.state is not InferenceBudgetState.OBSERVED
        ):
            raise ValidationError(
                "The inference budget fallback does not satisfy the approved route predicates."
            )


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
        if any(
            budget.workspace_id != self.workspace_id or budget.subject_id != self.subject_id
            for budget in (self.route.requested_budget, self.route.execution_budget)
        ):
            raise ValidationError("The inference budget decision crosses a subject boundary.")
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
        grounding_policy: InferenceGroundingPolicySnapshot,
        primary_provider: InferenceProviderSnapshot,
        budget: InferenceBudgetSnapshot,
        routed_at: datetime,
        internal_budget_fallback: InferenceProviderSnapshot | None = None,
        internal_fallback_budget: InferenceBudgetSnapshot | None = None,
    ) -> AuthorizedInferencePackage:
        if not evidence:
            raise ValidationError("Inference requires authorized evidence.")
        effective_classification = max(item.classification for item in evidence)
        provider = primary_provider
        execution_budget = budget
        selection_reason = InferenceRouteReason.PRIMARY
        if primary_provider.kind is ProviderKind.EXTERNAL:
            if (
                budget.mode is InferenceBudgetMode.HARD_LIMIT
                and budget.state is InferenceBudgetState.EXCEEDED
            ):
                if internal_budget_fallback is None or internal_fallback_budget is None:
                    raise ValidationError(
                        "External token-budget exhaustion requires an internal route "
                        "and accounting."
                    )
                provider = internal_budget_fallback
                execution_budget = internal_fallback_budget
                selection_reason = InferenceRouteReason.BUDGET_LIMIT_FALLBACK
            elif internal_budget_fallback is not None or internal_fallback_budget is not None:
                raise ValidationError("A reserved external route cannot declare a budget fallback.")
        elif internal_budget_fallback is not None or internal_fallback_budget is not None:
            raise ValidationError("An internal primary route cannot declare a budget fallback.")
        route = InferenceRoutingSnapshot(
            route_decision_id=uuid7(),
            workspace_id=workspace_id,
            effective_classification=effective_classification,
            policy=policy,
            grounding_policy=grounding_policy,
            requested_provider=primary_provider,
            provider=provider,
            requested_budget=budget,
            execution_budget=execution_budget,
            selection_reason=selection_reason,
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
class InferenceGroundingAssessment:
    """Server-side verifier output; this is never accepted from the model provider."""

    package_id: UUID
    route_decision_id: UUID
    policy_id: UUID
    policy_version: int
    policy_hash: str
    answer_hash: str
    cited_chunk_ids: tuple[UUID, ...]
    canonical_source_urns: tuple[str, ...]
    evidence_bundle_hash: str
    metric: InferenceGroundingMetric
    score_millionths: int
    evaluator_version: str
    evaluated_at: datetime
    schema_version: int = INFERENCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        if self.policy_version < 1:
            raise ValidationError("The grounding assessment policy version is invalid.")
        _require_sha256(self.policy_hash, "grounding assessment policy hash")
        _require_sha256(self.answer_hash, "grounding answer hash")
        _require_sha256(self.evidence_bundle_hash, "grounding evidence bundle hash")
        if (
            not self.cited_chunk_ids
            or len(self.cited_chunk_ids) > MAXIMUM_INFERENCE_EVIDENCE
            or len(self.cited_chunk_ids) != len(set(self.cited_chunk_ids))
            or len(self.canonical_source_urns) != len(self.cited_chunk_ids)
        ):
            raise ValidationError("The grounding evidence set is invalid.")
        for source_urn in self.canonical_source_urns:
            _require_canonical_urn(source_urn, "grounding source")
        if not isinstance(self.metric, InferenceGroundingMetric):
            raise ValidationError("The grounding metric is invalid.")
        if not _bounded_metric(self.score_millionths, maximum=1_000_000):
            raise ValidationError("The grounding score is outside the supported range.")
        _require_runtime_identity(self.evaluator_version, "grounding evaluator version")
        _require_aware(self.evaluated_at, "grounding evaluation")


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
        _require_canonical_urn(self.source_locator, "inference citation source")
        if not self.source_version.strip() or len(self.source_version) > 255:
            raise ValidationError("The inference citation source is invalid.")
        _require_sha256(self.content_hash, "inference citation content hash")


@dataclass(frozen=True, slots=True)
class InferenceExecutionResult:
    route_decision_id: UUID
    requested_budget_decision_id: UUID
    execution_budget_decision_id: UUID
    provider_profile_version_id: UUID
    route_reason: InferenceRouteReason
    effective_classification: Classification
    state: InferenceExecutionState
    answer: str
    citations: tuple[InferenceCitation, ...]
    refusal_code: InferenceRefusalCode | None
    usage_state: InferenceUsageState
    input_tokens: int | None
    output_tokens: int | None
    time_to_first_token_ms: int | None
    duration_ms: int | None
    schema_version: int = INFERENCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        if not isinstance(self.state, InferenceExecutionState):
            raise ValidationError("The inference execution state is invalid.")
        if not isinstance(self.route_reason, InferenceRouteReason):
            raise ValidationError("The inference result route reason is invalid.")
        if not isinstance(self.usage_state, InferenceUsageState):
            raise ValidationError("The inference result usage state is invalid.")
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
        metrics_valid = _metrics_are_valid(*metrics)
        if self.state is InferenceExecutionState.COMPLETED:
            if (
                not self.citations
                or self.refusal_code is not None
                or self.usage_state is not InferenceUsageState.OBSERVED
                or not metrics_valid
            ):
                raise ValidationError("The completed inference result is incomplete.")
            return
        if (
            self.answer != UNVERIFIABLE_INFERENCE_ANSWER
            or self.citations
            or not isinstance(self.refusal_code, InferenceRefusalCode)
            or (self.usage_state is InferenceUsageState.OBSERVED and not metrics_valid)
            or (
                self.usage_state is InferenceUsageState.UNAVAILABLE
                and any(value is not None for value in metrics)
            )
        ):
            raise ValidationError("The refused inference result is inconsistent.")

    @property
    def generation_tokens_per_second(self) -> float | None:
        if (
            self.output_tokens is None
            or self.time_to_first_token_ms is None
            or self.duration_ms is None
        ):
            return None
        generation_ms = max(1, self.duration_ms - self.time_to_first_token_ms)
        return self.output_tokens * 1_000 / generation_ms


def finalize_inference_draft(
    *,
    package: AuthorizedInferencePackage,
    draft: object,
    grounding: object,
) -> InferenceExecutionResult:
    try:
        draft_is_valid = provider_draft_is_valid(draft, package=package)
    except Exception:
        draft_is_valid = False
    if not draft_is_valid:
        return refused_inference_result(
            package=package,
            code=InferenceRefusalCode.INVALID_PROVIDER_OUTPUT,
        )
    assert isinstance(draft, ProviderInferenceDraft)
    try:
        draft_within_budget = provider_draft_within_budget(package=package, draft=draft)
    except Exception:
        draft_within_budget = False
    if not draft_within_budget:
        return refused_inference_result(
            package=package,
            code=InferenceRefusalCode.INVALID_PROVIDER_OUTPUT,
            draft=draft,
        )
    if not isinstance(grounding, InferenceGroundingAssessment):
        return refused_inference_result(
            package=package,
            code=InferenceRefusalCode.INVALID_PROVIDER_OUTPUT,
            draft=draft,
        )
    evidence_by_id = {item.evidence.chunk_id: item.evidence for item in package.evidence}
    cited_ids = draft.cited_chunk_ids
    expected_urns = tuple(evidence_by_id[chunk_id].source_locator for chunk_id in cited_ids)
    grounding_policy = package.route.grounding_policy
    grounding_invalid = (
        grounding.schema_version != INFERENCE_CONTRACT_VERSION
        or grounding.package_id != package.package_id
        or grounding.route_decision_id != package.route.route_decision_id
        or grounding.policy_id != grounding_policy.policy_id
        or grounding.policy_version != grounding_policy.policy_version
        or grounding.policy_hash != grounding_policy.policy_hash
        or grounding.answer_hash != grounding_answer_hash(draft.answer)
        or grounding.cited_chunk_ids != cited_ids
        or grounding.canonical_source_urns != expected_urns
        or grounding.evidence_bundle_hash
        != grounding_evidence_bundle_hash(package=package, cited_chunk_ids=cited_ids)
        or grounding.metric is not grounding_policy.metric
        or grounding.evaluator_version != grounding_policy.evaluator_version
        or grounding.evaluated_at < package.route.routed_at
    )
    if grounding_invalid:
        return refused_inference_result(
            package=package,
            code=InferenceRefusalCode.INVALID_PROVIDER_OUTPUT,
            draft=draft,
        )
    if grounding.score_millionths < grounding_policy.minimum_score_millionths:
        return refused_inference_result(
            package=package,
            code=InferenceRefusalCode.INSUFFICIENT_GROUNDING,
            draft=draft,
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
        requested_budget_decision_id=package.route.requested_budget.budget_decision_id,
        execution_budget_decision_id=package.route.execution_budget.budget_decision_id,
        provider_profile_version_id=package.route.provider.provider_profile_version_id,
        route_reason=package.route.selection_reason,
        effective_classification=package.route.effective_classification,
        state=InferenceExecutionState.COMPLETED,
        answer=draft.answer.strip(),
        citations=citations,
        refusal_code=None,
        usage_state=InferenceUsageState.OBSERVED,
        input_tokens=draft.input_tokens,
        output_tokens=draft.output_tokens,
        time_to_first_token_ms=draft.time_to_first_token_ms,
        duration_ms=draft.duration_ms,
    )


def refused_inference_result(
    *,
    package: AuthorizedInferencePackage,
    code: InferenceRefusalCode,
    draft: ProviderInferenceDraft | None = None,
) -> InferenceExecutionResult:
    usage_observed = draft is not None and provider_draft_metrics_are_valid(draft)
    return InferenceExecutionResult(
        route_decision_id=package.route.route_decision_id,
        requested_budget_decision_id=package.route.requested_budget.budget_decision_id,
        execution_budget_decision_id=package.route.execution_budget.budget_decision_id,
        provider_profile_version_id=package.route.provider.provider_profile_version_id,
        route_reason=package.route.selection_reason,
        effective_classification=package.route.effective_classification,
        state=InferenceExecutionState.REFUSED,
        answer=UNVERIFIABLE_INFERENCE_ANSWER,
        citations=(),
        refusal_code=code,
        usage_state=(
            InferenceUsageState.OBSERVED if usage_observed else InferenceUsageState.UNAVAILABLE
        ),
        input_tokens=draft.input_tokens if usage_observed and draft is not None else None,
        output_tokens=draft.output_tokens if usage_observed and draft is not None else None,
        time_to_first_token_ms=(
            draft.time_to_first_token_ms if usage_observed and draft is not None else None
        ),
        duration_ms=draft.duration_ms if usage_observed and draft is not None else None,
    )


def grounding_answer_hash(answer: str) -> str:
    return hashlib.sha256(answer.strip().encode("utf-8")).hexdigest()


def grounding_evidence_bundle_hash(
    *,
    package: AuthorizedInferencePackage,
    cited_chunk_ids: tuple[UUID, ...],
) -> str:
    evidence_by_id = {item.evidence.chunk_id: item.evidence for item in package.evidence}
    if (
        not cited_chunk_ids
        or len(cited_chunk_ids) != len(set(cited_chunk_ids))
        or any(chunk_id not in evidence_by_id for chunk_id in cited_chunk_ids)
    ):
        raise ValidationError("The grounding evidence bundle is not authorized.")
    return canonical_json_hash(
        {
            "package_id": str(package.package_id),
            "route_decision_id": str(package.route.route_decision_id),
            "evidence": [
                {
                    "chunk_id": str(chunk_id),
                    "source_urn": evidence_by_id[chunk_id].source_locator,
                    "source_version": evidence_by_id[chunk_id].source_version,
                    "content_hash": evidence_by_id[chunk_id].content_hash,
                }
                for chunk_id in cited_chunk_ids
            ],
        }
    )


def provider_draft_is_valid(
    draft: object,
    *,
    package: AuthorizedInferencePackage,
) -> TypeGuard[ProviderInferenceDraft]:
    if not isinstance(draft, ProviderInferenceDraft):
        return False
    evidence_ids = {item.evidence.chunk_id for item in package.evidence}
    cited_ids = draft.cited_chunk_ids
    return (
        draft.schema_version == INFERENCE_CONTRACT_VERSION
        and isinstance(draft.answer, str)
        and bool(draft.answer.strip())
        and len(draft.answer) <= MAXIMUM_INFERENCE_ANSWER_CHARACTERS
        and isinstance(cited_ids, tuple)
        and bool(cited_ids)
        and len(cited_ids) <= MAXIMUM_INFERENCE_EVIDENCE
        and all(isinstance(chunk_id, UUID) and chunk_id in evidence_ids for chunk_id in cited_ids)
        and len(cited_ids) == len(set(cited_ids))
        and provider_draft_metrics_are_valid(draft)
    )


def provider_draft_metrics_are_valid(draft: ProviderInferenceDraft) -> bool:
    return _metrics_are_valid(
        draft.input_tokens,
        draft.output_tokens,
        draft.time_to_first_token_ms,
        draft.duration_ms,
    )


def provider_draft_within_budget(
    *,
    package: AuthorizedInferencePackage,
    draft: ProviderInferenceDraft,
) -> bool:
    return not (
        package.route.provider.kind is ProviderKind.EXTERNAL
        and draft.input_tokens + draft.output_tokens
        > package.route.execution_budget.estimated_tokens
    )


def _metrics_are_valid(
    input_tokens: object,
    output_tokens: object,
    time_to_first_token_ms: object,
    duration_ms: object,
) -> bool:
    return (
        _bounded_metric(input_tokens, maximum=10_000_000)
        and _bounded_metric(output_tokens, maximum=1_000_000)
        and _bounded_metric(time_to_first_token_ms, maximum=3_600_000)
        and _bounded_metric(duration_ms, maximum=86_400_000)
        and isinstance(time_to_first_token_ms, int)
        and isinstance(duration_ms, int)
        and time_to_first_token_ms <= duration_ms
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


def _require_runtime_identity(value: str, name: str, *, maximum: int = 256) -> None:
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or "://" in value
        or _RUNTIME_IDENTITY_PATTERN.fullmatch(value) is None
    ):
        raise ValidationError(f"The {name} is invalid.")


def _require_timezone_identity(value: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) > 64
        or _TIMEZONE_IDENTITY_PATTERN.fullmatch(value) is None
    ):
        raise ValidationError("The inference budget period timezone is invalid.")


def _require_canonical_urn(value: str, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) > 2_048
        or _CANONICAL_URN_PATTERN.fullmatch(value) is None
        or any(
            character == "%"
            and (
                index + 2 >= len(value)
                or not all(item in "0123456789ABCDEF" for item in value[index + 1 : index + 3])
            )
            for index, character in enumerate(value)
        )
    ):
        raise ValidationError(f"The {name} must be a canonical URN.")


def _assert_provider_eligible(
    *,
    provider: InferenceProviderSnapshot,
    effective_classification: Classification,
    required_jurisdiction: str,
    routed_at: datetime,
) -> None:
    if provider.state is not InferenceProviderProfileState.APPROVED:
        raise ValidationError("The inference provider profile is not approved.")
    if provider.jurisdiction != required_jurisdiction:
        raise ValidationError("The inference route crosses the approved jurisdiction.")
    if effective_classification > provider.maximum_classification:
        raise ValidationError("The inference route exceeds the provider classification ceiling.")
    if not provider.residency_attestation.is_current(at=routed_at):
        raise ValidationError("The provider residency attestation is not current.")
    if not provider.zero_retention_attestation.is_current(at=routed_at):
        raise ValidationError("The provider zero-retention attestation is not current.")


def _is_aware(value: object) -> bool:
    return (
        isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
    )


def _require_aware(value: datetime, name: str) -> None:
    if not _is_aware(value):
        raise ValidationError(f"The {name} timestamp must include a timezone.")
