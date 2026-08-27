from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

try:
    from airflow.sdk import dag, get_current_context, task
except ImportError:  # Airflow 2.10.x exposes these through the legacy public modules.
    from airflow.decorators import dag, task
    from airflow.operators.python import get_current_context

from datariver_quality_dispatch import dispatch_due_quality_runs


def _quality_dispatch_schedule() -> str | None:
    value = os.getenv("DATARIVER_QUALITY_DISPATCH_SCHEDULE")
    if value is None:
        return None
    if (
        not value
        or value != value.strip()
        or len(value) > 100
        or any(ord(character) < 32 or ord(character) > 126 for character in value)
    ):
        raise RuntimeError("DATARIVER_QUALITY_DISPATCH_SCHEDULE is invalid.")
    return value


@dag(
    dag_id="datariver_quality_dispatch",
    description="Trigger bounded server-owned Quality due-window dispatch.",
    schedule=_quality_dispatch_schedule(),
    start_date=datetime(2026, 7, 30, tzinfo=UTC),
    catchup=False,
    is_paused_upon_creation=True,
    max_active_runs=1,
    tags=["datariver", "quality", "dispatch"],
)
def quality_dispatch() -> None:
    @task(retries=2, retry_delay=timedelta(seconds=60), execution_timeout=timedelta(minutes=5))
    def dispatch() -> dict[str, object]:
        return dispatch_due_quality_runs(call_id=str(get_current_context()["run_id"]))

    dispatch()


quality_dispatch()
