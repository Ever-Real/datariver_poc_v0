from __future__ import annotations

import json
import os
import urllib.request

from datariver_auth import datariver_api_base_url, service_token


def apply_manual_metadata_receipts(
    *, run_id: str, maximum_submissions: int = 50
) -> dict[str, object]:
    """Ask DataRiver to claim and apply bounded, hash-verified MANUAL CSV receipts.

    Airflow never receives provider or object-store credentials.  It authenticates to DataRiver with
    the deployment-owned service identity, and the API performs typed DataHub read/merge/read-back.
    """
    if not 1 <= maximum_submissions <= 100:
        raise ValueError("maximum_submissions must be between 1 and 100")
    workspace_id = os.environ["DATARIVER_WORKSPACE_ID"]
    api_base_url = datariver_api_base_url()
    states: dict[str, int] = {}
    processed = 0
    for _ordinal in range(maximum_submissions):
        request = urllib.request.Request(  # noqa: S310 - deployment-owned validated origin
            f"{api_base_url}/api/v1/registration/manual-submissions/apply",
            method="POST",
            data=b"{}",
            headers={
                "Authorization": f"Bearer {service_token()}",
                "X-Workspace-Id": workspace_id,
                "X-Purpose": "scheduled-manual-metadata-apply",
                "X-Run-Id": run_id[:200],
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            document = json.load(response)
        if document.get("processed") is not True:
            break
        processed += 1
        state = document.get("state")
        if not isinstance(state, str):
            raise RuntimeError("DataRiver returned an invalid manual metadata apply state.")
        states[state] = states.get(state, 0) + 1
    return {"processed": processed, "states": states}
