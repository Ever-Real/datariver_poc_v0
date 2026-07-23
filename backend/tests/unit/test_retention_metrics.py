from uuid import uuid4

import pytest

from datariver.infrastructure.observability.metrics import RetentionWorkerMetrics


def test_retention_metrics_expose_only_bounded_worker_and_outcome_labels() -> None:
    metrics = RetentionWorkerMetrics(worker="scheduler")
    sensitive_id = str(uuid4())

    metrics.kill_switch_observed(enabled=False)
    metrics.cycle_finished(outcome="planned", duration_seconds=0.25, command_count=2)
    metrics.cycle_finished(outcome="blocked", duration_seconds=0.1, command_count=1)
    rendered = metrics.render().decode("utf-8")

    assert 'worker="scheduler"' in rendered
    assert 'outcome="planned"' in rendered
    assert 'outcome="blocked"' in rendered
    assert "datariver_retention_commands_total" in rendered
    assert "datariver_retention_kill_switch_enabled" in rendered
    assert sensitive_id not in rendered
    assert "workspace" not in rendered
    assert "subject" not in rendered
    assert "object_key" not in rendered


@pytest.mark.parametrize(
    ("worker", "outcome"),
    (("workspace-123", "planned"), ("scheduler", "target-123")),
)
def test_retention_metrics_reject_unbounded_label_values(worker: str, outcome: str) -> None:
    if worker not in {"scheduler", "archive"}:
        with pytest.raises(ValueError, match="worker"):
            RetentionWorkerMetrics(worker=worker)
        return

    metrics = RetentionWorkerMetrics(worker=worker)
    with pytest.raises(ValueError, match="outcome"):
        metrics.cycle_finished(outcome=outcome, duration_seconds=0.1, command_count=0)
