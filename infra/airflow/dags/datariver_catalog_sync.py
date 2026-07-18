from __future__ import annotations

import json
import os
import urllib.request
from uuid import NAMESPACE_URL, uuid5

from datariver_auth import datariver_api_base_url, service_token


def synchronize_catalog_projection(*, run_id: str) -> dict[str, object]:
    """Run one bounded, sequential DataHub-to-projection reconciliation."""
    workspace_id = os.environ["DATARIVER_WORKSPACE_ID"]
    api_base_url = datariver_api_base_url()
    sync_id = str(uuid5(NAMESPACE_URL, f"urn:datariver:catalog-sync:{run_id}"))
    offset: int | None = 0
    total_upserted = 0
    tombstoned = 0
    pages = 0
    observed_at: object = None

    while offset is not None:
        if pages >= 1000:
            raise RuntimeError("DataHub scan exceeded the configured page safety limit.")
        payload = json.dumps({"sync_id": sync_id, "offset": offset, "limit": 100}).encode()
        request = urllib.request.Request(  # noqa: S310 - origin is validation-owned
            f"{api_base_url}/api/v1/catalog/sync/datahub",
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
