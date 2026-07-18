from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from airflow.sdk import dag, get_current_context, task
from datariver_catalog_sync import synchronize_catalog_projection


@dag(
    dag_id="datariver_semiconductor_seed_ingestion",
    description=(
        "Explicitly rebuild the local semiconductor test schema and emit its DataHub lineage. "
        "Oracle records are marked MOCK; PostgreSQL is the only database written by this DAG."
    ),
    schedule=None,
    start_date=datetime(2026, 7, 18, tzinfo=UTC),
    catchup=False,
    is_paused_upon_creation=True,
    max_active_runs=1,
    tags=["datariver", "seed", "semiconductor", "datahub", "local-only"],
)
def semiconductor_seed_ingestion() -> None:
    @task(retries=1, retry_delay=timedelta(minutes=2), execution_timeout=timedelta(hours=3))
    def build_and_ingest() -> dict[str, object]:
        context = get_current_context()
        params = context.get("params", {})
        rows_per_table = _rows_per_table(params)
        entity_scope = _entity_scope(params)
        run_id = str(context["run_id"])
        safe_run_id = hashlib.sha256(run_id.encode()).hexdigest()[:20]
        output_dir = Path("/opt/airflow/logs/semiconductor-seed") / safe_run_id
        command = [
            sys.executable,
            "/opt/datariver/scripts/generate_semiconductor_seed.py",
            "--apply",
            "--confirm-reset",
            "--ingest-datahub",
            "--entity-scope",
            entity_scope,
            "--rows-per-table",
            str(rows_per_table),
            "--output-dir",
            str(output_dir),
        ]
        subprocess.run(command, check=True, env=os.environ.copy())  # noqa: S603
        catalog_projection = synchronize_catalog_projection(run_id=run_id)
        return {
            "run_id": run_id,
            "rows_per_table": rows_per_table,
            "entity_scope": entity_scope,
            "manifest": str(output_dir / "manifest.json"),
            "catalog_projection": catalog_projection,
        }

    build_and_ingest()


def _rows_per_table(params: Any) -> int:
    value = params.get("rows_per_table", 20) if isinstance(params, dict) else 20
    if isinstance(value, bool):
        raise ValueError("rows_per_table must be an integer between 10 and 50.")
    try:
        rows = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("rows_per_table must be an integer between 10 and 50.") from error
    if not 10 <= rows <= 50:
        raise ValueError("rows_per_table must be between 10 and 50.")
    return rows


def _entity_scope(params: Any) -> str:
    value = params.get("entity_scope", "dual") if isinstance(params, dict) else "dual"
    if value not in {"postgres", "dual"}:
        raise ValueError("entity_scope must be 'postgres' or 'dual'.")
    return str(value)


semiconductor_seed_ingestion()
