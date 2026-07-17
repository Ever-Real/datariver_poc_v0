from __future__ import annotations

import math
import re
from dataclasses import dataclass

from datariver.domain.common import ValidationError

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_IDENTITY_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._:/-]{0,254}[A-Za-z0-9])?")


@dataclass(frozen=True, slots=True)
class AssistantBenchmarkManifest:
    dataset_id: str
    dataset_revision: str
    dataset_hash: str
    evaluator_version: str
    scoring_policy_version: str
    scoring_policy_hash: str

    def __post_init__(self) -> None:
        for value in (
            self.dataset_id,
            self.dataset_revision,
            self.evaluator_version,
            self.scoring_policy_version,
        ):
            if not isinstance(value, str) or _IDENTITY_PATTERN.fullmatch(value) is None:
                raise ValidationError("The assistant benchmark manifest identity is invalid.")
        for value in (self.dataset_hash, self.scoring_policy_hash):
            if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
                raise ValidationError("The assistant benchmark manifest hash is invalid.")


@dataclass(frozen=True, slots=True)
class AssistantSloTarget:
    ttft_p95_ms: int
    minimum_average_tokens_per_second: float
    minimum_benchmark_accuracy_ratio: float

    def __post_init__(self) -> None:
        if not _positive_int(self.ttft_p95_ms):
            raise ValidationError("The assistant TTFT target must be positive.")
        if not _positive_number(self.minimum_average_tokens_per_second):
            raise ValidationError("The assistant token-rate target must be positive.")
        if not _ratio(self.minimum_benchmark_accuracy_ratio):
            raise ValidationError("The assistant accuracy target must be within zero and one.")


@dataclass(frozen=True, slots=True)
class AssistantBenchmarkObservation:
    request_id: str
    case_id: str
    dataset_hash: str
    evaluator_version: str
    scoring_policy_hash: str
    time_to_first_token_ms: int
    output_tokens: int
    generation_duration_ms: int
    benchmark_correct: bool

    def __post_init__(self) -> None:
        if (
            not self.request_id.strip()
            or len(self.request_id) > 128
            or any(character in self.request_id for character in "\r\n\x00")
        ):
            raise ValidationError("The assistant benchmark request ID is invalid.")
        if (
            not self.case_id.strip()
            or len(self.case_id) > 128
            or any(character in self.case_id for character in "\r\n\x00")
        ):
            raise ValidationError("The assistant benchmark case ID is invalid.")
        if (
            _SHA256_PATTERN.fullmatch(self.dataset_hash) is None
            or _SHA256_PATTERN.fullmatch(self.scoring_policy_hash) is None
            or _IDENTITY_PATTERN.fullmatch(self.evaluator_version) is None
        ):
            raise ValidationError("The assistant benchmark observation binding is invalid.")
        if not _non_negative_int(self.time_to_first_token_ms):
            raise ValidationError("The assistant benchmark TTFT is invalid.")
        if not _non_negative_int(self.output_tokens):
            raise ValidationError("The assistant benchmark output token count is invalid.")
        if not _positive_int(self.generation_duration_ms):
            raise ValidationError("The assistant benchmark generation duration is invalid.")
        if not isinstance(self.benchmark_correct, bool):
            raise ValidationError("The assistant benchmark correctness value is invalid.")

    @property
    def tokens_per_second(self) -> float:
        return self.output_tokens * 1_000 / self.generation_duration_ms


@dataclass(frozen=True, slots=True)
class AssistantSloReport:
    manifest: AssistantBenchmarkManifest
    sample_size: int
    ttft_p95_ms: int
    average_tokens_per_second: float
    benchmark_accuracy_ratio: float
    ttft_target_met: bool
    token_rate_target_met: bool
    accuracy_target_met: bool

    @property
    def all_targets_met(self) -> bool:
        return self.ttft_target_met and self.token_rate_target_met and self.accuracy_target_met


def evaluate_assistant_slo(
    *,
    manifest: AssistantBenchmarkManifest,
    observations: tuple[AssistantBenchmarkObservation, ...],
    target: AssistantSloTarget,
) -> AssistantSloReport:
    """Evaluate a pinned benchmark run without claiming production telemetry evidence."""

    if not observations:
        raise ValidationError("The assistant SLO evaluation requires benchmark observations.")
    request_ids = tuple(item.request_id for item in observations)
    case_ids = tuple(item.case_id for item in observations)
    if len(request_ids) != len(set(request_ids)) or len(case_ids) != len(set(case_ids)):
        raise ValidationError(
            "The assistant SLO evaluation contains duplicate request or case IDs."
        )
    if any(
        item.dataset_hash != manifest.dataset_hash
        or item.evaluator_version != manifest.evaluator_version
        or item.scoring_policy_hash != manifest.scoring_policy_hash
        for item in observations
    ):
        raise ValidationError(
            "The assistant SLO observation does not match its benchmark manifest."
        )
    ordered_ttft = sorted(item.time_to_first_token_ms for item in observations)
    p95_index = max(0, math.ceil(len(ordered_ttft) * 0.95) - 1)
    ttft_p95_ms = ordered_ttft[p95_index]
    average_tokens_per_second = sum(item.tokens_per_second for item in observations) / len(
        observations
    )
    benchmark_accuracy_ratio = sum(item.benchmark_correct for item in observations) / len(
        observations
    )
    return AssistantSloReport(
        manifest=manifest,
        sample_size=len(observations),
        ttft_p95_ms=ttft_p95_ms,
        average_tokens_per_second=average_tokens_per_second,
        benchmark_accuracy_ratio=benchmark_accuracy_ratio,
        ttft_target_met=ttft_p95_ms <= target.ttft_p95_ms,
        token_rate_target_met=(
            average_tokens_per_second >= target.minimum_average_tokens_per_second
        ),
        accuracy_target_met=(benchmark_accuracy_ratio >= target.minimum_benchmark_accuracy_ratio),
    )


def _non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _positive_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _ratio(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0 < value <= 1
    )
