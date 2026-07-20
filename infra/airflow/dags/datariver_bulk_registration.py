from __future__ import annotations

import json
import os
import urllib.request

from datariver_auth import datariver_api_base_url, service_token

_ALLOWED_STATES = frozenset({"READY", "QUEUED", "FAILED", "SUPERSEDED"})


def prepare_bulk_registration_receipts(
    *, run_id: str, maximum_preparations: int = 20
) -> dict[str, object]:
    """Ask DataRiver to execute bounded, lease-fenced BULK preparations.

    Airflow receives only a short-lived DataRiver service token. Object-store, PostgreSQL and
    DataHub credentials remain inside DataRiver-owned API/worker boundaries.
    """

    if not 1 <= maximum_preparations <= 50:
        raise ValueError("maximum_preparations must be between 1 and 50")
    workspace_id = os.environ["DATARIVER_WORKSPACE_ID"]
    api_base_url = datariver_api_base_url()
    states: dict[str, int] = {}
    processed = 0
    item_count = 0
    for _ordinal in range(maximum_preparations):
        request = urllib.request.Request(  # noqa: S310 - deployment-owned validated origin
            f"{api_base_url}/api/v1/registration/bulk-preparations/execute",
            method="POST",
            data=b"{}",
            headers={
                "Authorization": f"Bearer {service_token()}",
                "X-Workspace-Id": workspace_id,
                "X-Purpose": "scheduled-bulk-registration-prepare",
                "X-Run-Id": run_id[:200],
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=900) as response:  # noqa: S310
            if response.status != 200:
                raise RuntimeError("DataRiver rejected the BULK preparation request.")
            document = json.load(response)
        if document.get("processed") is not True:
            break
        state = document.get("state")
        if not isinstance(state, str) or state not in _ALLOWED_STATES:
            raise RuntimeError("DataRiver returned an invalid BULK preparation state.")
        count = document.get("item_count")
        if count is not None and (not isinstance(count, int) or count < 1):
            raise RuntimeError("DataRiver returned an invalid BULK candidate count.")
        processed += 1
        item_count += count or 0
        states[state] = states.get(state, 0) + 1
    if states.get("FAILED", 0) > 0:
        raise RuntimeError("One or more BULK preparation jobs reached FAILED state.")
    return {"processed": processed, "item_count": item_count, "states": states}
