from __future__ import annotations

from datetime import UTC, datetime, timedelta

from airflow.sdk import dag, get_current_context, task
from datariver_bulk_registration import prepare_bulk_registration_receipts


@dag(
    dag_id="datariver_bulk_registration_prepare",
    description=(
        "Prepare immutable CSV/XLSX registration candidates through DataRiver's fenced boundary."
    ),
    schedule="*/5 * * * *",
    start_date=datetime(2026, 7, 21, tzinfo=UTC),
    catchup=False,
    is_paused_upon_creation=False,
    max_active_runs=1,
    tags=["datariver", "registration", "bulk", "xlsx"],
)
def bulk_registration_prepare() -> None:
    @task(retries=2, retry_delay=timedelta(seconds=60), execution_timeout=timedelta(minutes=45))
    def prepare_receipts() -> dict[str, object]:
        return prepare_bulk_registration_receipts(run_id=str(get_current_context()["run_id"]))

    prepare_receipts()


bulk_registration_prepare()
