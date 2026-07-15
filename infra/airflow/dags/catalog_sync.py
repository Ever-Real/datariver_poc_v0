from __future__ import annotations

import json
import os
import urllib.request
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from airflow.sdk import dag, get_current_context, task
from datariver_auth import service_token


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
        workspace_id = os.environ["DATARIVER_WORKSPACE_ID"]
        run_id = str(get_current_context()["run_id"])
        sync_id = str(uuid5(NAMESPACE_URL, f"urn:datariver:catalog-sync:{run_id}"))
        offset: int | None = 0
        total_upserted = 0
        pages = 0
        observed_at = None
        tombstoned = 0
        while offset is not None:
            if pages >= 1000:
                raise RuntimeError("DataHub scan exceeded the configured page safety limit.")
            payload = json.dumps({"sync_id": sync_id, "offset": offset, "limit": 100}).encode()
            request = urllib.request.Request(
                "http://api:8000/api/v1/catalog/sync/datahub",
                method="POST",
                data=payload,
                headers={
                    "Authorization": f"Bearer {service_token()}",
                    "X-Workspace-Id": workspace_id,
                    "X-Purpose": "scheduled-datahub-projection-sync",
                    "Idempotency-Key": f"catalog-sync-{run_id}-{offset}"[:200],
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                document = json.load(response)
            total_upserted += int(document["upserted"])
            tombstoned += int(document["tombstoned"])
            offset = document.get("next_offset")
            observed_at = document.get("observed_at")
            pages += 1
        return {
            "pages": pages,
            "upserted": total_upserted,
            "tombstoned": tombstoned,
            "observed_at": observed_at,
        }

    synchronize()


catalog_sync()
