from __future__ import annotations

from dataclasses import replace

import pytest

from datariver.application.assistant_slo import (
    AssistantBenchmarkManifest,
    AssistantBenchmarkObservation,
    AssistantSloTarget,
    evaluate_assistant_slo,
)
from datariver.domain.common import ValidationError


def _observation(
    index: int,
    *,
    ttft_ms: int = 400,
    output_tokens: int = 20,
    generation_duration_ms: int = 1_000,
    correct: bool = True,
) -> AssistantBenchmarkObservation:
    return AssistantBenchmarkObservation(
        request_id=f"benchmark-{index}",
        case_id=f"case-{index}",
        dataset_hash="a" * 64,
        evaluator_version="evaluator-v1",
        scoring_policy_hash="b" * 64,
        time_to_first_token_ms=ttft_ms,
        output_tokens=output_tokens,
        generation_duration_ms=generation_duration_ms,
        benchmark_correct=correct,
    )


def _manifest() -> AssistantBenchmarkManifest:
    return AssistantBenchmarkManifest(
        dataset_id="assistant-benchmark",
        dataset_revision="dataset-v1",
        dataset_hash="a" * 64,
        evaluator_version="evaluator-v1",
        scoring_policy_version="scoring-v1",
        scoring_policy_hash="b" * 64,
    )


def test_evaluates_nearest_rank_p95_token_rate_and_accuracy() -> None:
    observations = tuple(
        _observation(
            index,
            ttft_ms=500 if index == 19 else 400,
            correct=index > 3,
        )
        for index in range(20)
    )

    report = evaluate_assistant_slo(
        manifest=_manifest(),
        observations=observations,
        target=AssistantSloTarget(
            ttft_p95_ms=450,
            minimum_average_tokens_per_second=20,
            minimum_benchmark_accuracy_ratio=0.8,
        ),
    )

    assert report.sample_size == 20
    assert report.manifest == _manifest()
    assert report.ttft_p95_ms == 400
    assert report.average_tokens_per_second == pytest.approx(20)
    assert report.benchmark_accuracy_ratio == pytest.approx(0.8)
    assert report.all_targets_met is True


def test_reports_each_failed_gate_without_hiding_partial_success() -> None:
    report = evaluate_assistant_slo(
        manifest=_manifest(),
        observations=(
            _observation(1, ttft_ms=900, output_tokens=5, correct=False),
            _observation(2, ttft_ms=1_000, output_tokens=5, correct=True),
        ),
        target=AssistantSloTarget(
            ttft_p95_ms=800,
            minimum_average_tokens_per_second=10,
            minimum_benchmark_accuracy_ratio=0.5,
        ),
    )

    assert report.ttft_target_met is False
    assert report.token_rate_target_met is False
    assert report.accuracy_target_met is True
    assert report.all_targets_met is False


def test_rejects_empty_or_duplicate_benchmark_runs() -> None:
    target = AssistantSloTarget(
        ttft_p95_ms=500,
        minimum_average_tokens_per_second=10,
        minimum_benchmark_accuracy_ratio=0.5,
    )

    with pytest.raises(ValidationError, match="requires"):
        evaluate_assistant_slo(manifest=_manifest(), observations=(), target=target)
    duplicate = _observation(1)
    with pytest.raises(ValidationError, match="duplicate"):
        evaluate_assistant_slo(
            manifest=_manifest(),
            observations=(duplicate, duplicate),
            target=target,
        )


def test_rejects_an_observation_from_another_dataset_or_evaluator() -> None:
    observation = _observation(1)
    target = AssistantSloTarget(
        ttft_p95_ms=500,
        minimum_average_tokens_per_second=10,
        minimum_benchmark_accuracy_ratio=0.5,
    )

    with pytest.raises(ValidationError, match="manifest"):
        evaluate_assistant_slo(
            manifest=_manifest(),
            observations=(replace(observation, dataset_hash="c" * 64),),
            target=target,
        )
