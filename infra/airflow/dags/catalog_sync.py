from __future__ import annotations

from datetime import UTC, datetime, timedelta

from airflow.sdk import dag, get_current_context, task
from datariver_catalog_sync import synchronize_catalog_projection


@dag(
    dag_id="datariver_catalog_sync",
    description="Incrementally rebuild the authorized local projection from external DataHub.",
    schedule="0 */6 * * *",
    start_date=datetime(2026, 7, 1, tzinfo=UTC),
    catchup=False,
    is_paused_upon_creation=True,
    max_active_runs=1,
    tags=["datariver", "catalog", "datahub"],
)
def catalog_sync() -> None:
    @task(retries=2, retry_delay=timedelta(seconds=60), execution_timeout=timedelta(minutes=30))
    def synchronize() -> dict[str, object]:
        run_id = str(get_current_context()["run_id"])
        return synchronize_catalog_projection(run_id=run_id)

    synchronize()


catalog_sync()
