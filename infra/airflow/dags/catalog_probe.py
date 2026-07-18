from __future__ import annotations

import json
import os
import urllib.request
from datetime import UTC, datetime

from airflow.sdk import dag, task
from datariver_auth import datariver_api_base_url, service_token


@dag(
    dag_id="datariver_catalog_probe",
    description="Verify the governed DataHub wrapper with a service-account token.",
    schedule="0 2 * * *",
    start_date=datetime(2026, 7, 1, tzinfo=UTC),
    catchup=False,
    is_paused_upon_creation=True,
    tags=["datariver", "catalog", "governance"],
)
def catalog_probe() -> None:
    @task(retries=2, retry_delay=60)
    def probe() -> dict[str, object]:
        workspace_id = os.environ["DATARIVER_WORKSPACE_ID"]
        token = service_token()
        request = urllib.request.Request(  # noqa: S310 - origin is validation-owned
            f"{datariver_api_base_url()}/api/v1/catalog/assets?limit=1",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Workspace-Id": workspace_id,
                "X-Purpose": "scheduled-catalog-reconciliation-probe",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
            document = json.load(response)
        return {
            "asset_count": len(document.get("items", [])),
            "observed_at": document.get("meta", {}).get("observed_at"),
        }

    probe()


catalog_probe()
