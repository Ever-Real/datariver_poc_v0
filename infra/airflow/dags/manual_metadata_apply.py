from __future__ import annotations

from datetime import UTC, datetime, timedelta

from airflow.sdk import dag, get_current_context, task
from datariver_manual_metadata import apply_manual_metadata_receipts


@dag(
    dag_id="datariver_manual_metadata_apply",
    description=(
        "Apply immutable MANUAL metadata CSV receipts through DataRiver's typed DataHub boundary."
    ),
    schedule="*/5 * * * *",
    start_date=datetime(2026, 7, 18, tzinfo=UTC),
    catchup=False,
    # External Airflow must not begin polling a newly migrated DataRiver deployment before the
    # operator verifies its OIDC identity, workspace and target API origin.
    is_paused_upon_creation=True,
    max_active_runs=1,
    tags=["datariver", "registration", "metadata", "datahub"],
)
def manual_metadata_apply() -> None:
    @task(retries=2, retry_delay=timedelta(seconds=60), execution_timeout=timedelta(minutes=15))
    def apply_receipts() -> dict[str, object]:
        return apply_manual_metadata_receipts(run_id=str(get_current_context()["run_id"]))

    apply_receipts()


manual_metadata_apply()
