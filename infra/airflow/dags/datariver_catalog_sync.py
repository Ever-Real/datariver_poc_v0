from __future__ import annotations

import json
import os
import urllib.request
from uuid import NAMESPACE_URL, uuid5

from datariver_auth import datariver_api_base_url, service_token


def _maximum_sync_pages() -> int:
    raw_value = os.getenv("DATARIVER_CATALOG_SYNC_MAX_PAGES", "10002")
    try:
        value = int(raw_value)
    except ValueError as error:
        raise RuntimeError("Catalog sync page safety limit must be an integer.") from error
    if not 1 <= value <= 100_002:
        raise RuntimeError("Catalog sync page safety limit is outside the governed range.")
    return value


def synchronize_catalog_projection(*, run_id: str) -> dict[str, object]:
    """Run one bounded, sequential DataHub-to-projection reconciliation."""
    workspace_id = os.environ["DATARIVER_WORKSPACE_ID"]
    api_base_url = datariver_api_base_url()
    sync_id = str(uuid5(NAMESPACE_URL, f"urn:datariver:catalog-sync:{run_id}"))
    headers = {
        "Authorization": f"Bearer {service_token()}",
        "X-Workspace-Id": workspace_id,
        "X-Purpose": "scheduled-datahub-projection-sync",
        "Accept": "application/json",
    }
    progress_request = urllib.request.Request(  # noqa: S310 - origin is validation-owned
        f"{api_base_url}/api/v1/catalog/sync/datahub/{sync_id}",
        method="GET",
        headers=headers,
    )
    with urllib.request.urlopen(progress_request, timeout=30) as response:  # noqa: S310
        progress = json.load(response)
    state = str(progress["state"])
    if state == "COMPLETED":
        return {
            "pages": 0,
            "upserted": 0,
            "tombstoned": 0,
            "observed_at": None,
            "tombstone_status": (
                "APPLIED"
                if bool(progress["snapshot_consistent"])
                else "SUPPRESSED_UNVERIFIED_SNAPSHOT"
            ),
            "resumed_from_offset": None,
            "already_completed": True,
        }
    if state == "ABANDONED":
        raise RuntimeError("The server-owned DataHub reconciliation was abandoned.")
    if state not in {"NOT_STARTED", "ACTIVE"}:
        raise RuntimeError("The server returned an invalid catalog sync state.")
    raw_offset = progress.get("next_offset")
    if isinstance(raw_offset, bool) or not isinstance(raw_offset, int) or raw_offset < 0:
        raise RuntimeError("The server returned an invalid catalog sync offset.")
    offset: int | None = raw_offset
    resumed_from_offset = offset
    total_upserted = 0
    tombstoned = 0
    pages = 0
    observed_at: object = None
    tombstone_status = "NOT_FINAL"
    maximum_pages = _maximum_sync_pages()

    while offset is not None:
        if pages >= maximum_pages:
            raise RuntimeError("DataHub scan exceeded the configured page safety limit.")
        payload = json.dumps({"sync_id": sync_id, "offset": offset, "limit": 100}).encode()
        request = urllib.request.Request(  # noqa: S310 - origin is validation-owned
            f"{api_base_url}/api/v1/catalog/sync/datahub",
            method="POST",
            data=payload,
            headers={
                **headers,
                "Idempotency-Key": f"catalog-sync-{run_id}-{offset}"[:200],
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            document = json.load(response)
        total_upserted += int(document["upserted"])
        tombstoned += int(document["tombstoned"])
        offset = document.get("next_offset")
        observed_at = document.get("observed_at")
        tombstone_status = str(document["tombstone_status"])
        pages += 1

    return {
        "pages": pages,
        "upserted": total_upserted,
        "tombstoned": tombstoned,
        "observed_at": observed_at,
        "tombstone_status": tombstone_status,
        "resumed_from_offset": resumed_from_offset,
        "already_completed": False,
    }
