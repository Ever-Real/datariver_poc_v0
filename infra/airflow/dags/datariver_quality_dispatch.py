from __future__ import annotations

import json
import urllib.request
from uuid import UUID

from datariver_quality_auth import (
    quality_api_base_url,
    quality_service_token,
    quality_workspace_id,
)

_DISPATCH_RESPONSE_LIMIT_BYTES = 65_536
_MAXIMUM_CREATED_RUNS = 100
_MAXIMUM_SKIPPED_WINDOWS = 2_147_483_647
_RESPONSE_KEYS = frozenset(
    {
        "created_run_ids",
        "created_run_count",
        "skipped_window_count",
        "replayed",
    }
)


def _validated_call_id(value: str) -> str:
    if (
        not value
        or value != value.strip()
        or len(value) > 200
        or any(ord(character) < 33 or ord(character) > 126 for character in value)
    ):
        raise ValueError("The Quality dispatch call ID is invalid.")
    return value


def _bounded_integer(value: object, *, label: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise RuntimeError(f"The Quality dispatch {label} is invalid.")
    return value


def _normalized_response(document: object) -> dict[str, object]:
    if not isinstance(document, dict) or set(document) != _RESPONSE_KEYS:
        raise RuntimeError("DataRiver returned an invalid Quality dispatch response.")
    raw_run_ids = document["created_run_ids"]
    if not isinstance(raw_run_ids, list) or len(raw_run_ids) > _MAXIMUM_CREATED_RUNS:
        raise RuntimeError("DataRiver returned invalid Quality dispatch Run IDs.")
    run_ids: list[str] = []
    for raw_run_id in raw_run_ids:
        if not isinstance(raw_run_id, str):
            raise RuntimeError("DataRiver returned invalid Quality dispatch Run IDs.")
        try:
            run_id = UUID(raw_run_id)
        except ValueError as error:
            raise RuntimeError("DataRiver returned invalid Quality dispatch Run IDs.") from error
        if str(run_id) != raw_run_id.lower():
            raise RuntimeError("DataRiver returned non-canonical Quality dispatch Run IDs.")
        run_ids.append(str(run_id))
    if len(run_ids) != len(set(run_ids)):
        raise RuntimeError("DataRiver returned duplicate Quality dispatch Run IDs.")
    created_run_count = _bounded_integer(
        document["created_run_count"],
        label="created Run count",
        maximum=_MAXIMUM_CREATED_RUNS,
    )
    if created_run_count != len(run_ids):
        raise RuntimeError("The Quality dispatch Run count does not match its IDs.")
    skipped_window_count = _bounded_integer(
        document["skipped_window_count"],
        label="skipped-window count",
        maximum=_MAXIMUM_SKIPPED_WINDOWS,
    )
    replayed = document["replayed"]
    if not isinstance(replayed, bool):
        raise RuntimeError("The Quality dispatch replay marker is invalid.")
    return {
        "created_run_ids": run_ids,
        "created_run_count": created_run_count,
        "skipped_window_count": skipped_window_count,
        "replayed": replayed,
    }


def dispatch_due_quality_runs(*, call_id: str) -> dict[str, object]:
    """Ask DataRiver to dispatch one bounded, server-evaluated due-window call."""
    normalized_call_id = _validated_call_id(call_id)
    request = urllib.request.Request(  # noqa: S310 - deployment-owned validated origin
        f"{quality_api_base_url()}/api/v1/quality/internal/dispatch",
        method="POST",
        data=json.dumps(
            {"call_id": normalized_call_id},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {quality_service_token()}",
            "X-Workspace-Id": quality_workspace_id(),
            "X-Purpose": "scheduled-quality-dispatch",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        raw_document = response.read(_DISPATCH_RESPONSE_LIMIT_BYTES + 1)
    if len(raw_document) > _DISPATCH_RESPONSE_LIMIT_BYTES:
        raise RuntimeError("The Quality dispatch response is too large.")
    try:
        document: object = json.loads(raw_document)
    except (TypeError, ValueError) as error:
        raise RuntimeError("The Quality dispatch response is invalid.") from error
    return _normalized_response(document)
