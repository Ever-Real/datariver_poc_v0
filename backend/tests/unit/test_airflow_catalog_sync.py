from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from urllib.request import Request

import pytest


class _Response(io.BytesIO):
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _helper(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    auth = ModuleType("datariver_auth")
    auth.__dict__["datariver_api_base_url"] = lambda: "https://api.example.test"
    auth.__dict__["service_token"] = lambda: "service-token"
    monkeypatch.setitem(sys.modules, "datariver_auth", auth)
    path = (
        Path(__file__).resolve().parents[3]
        / "infra"
        / "airflow"
        / "dags"
        / "datariver_catalog_sync.py"
    )
    specification = importlib.util.spec_from_file_location(
        "test_datariver_catalog_sync",
        path,
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_airflow_catalog_sync_resumes_from_the_server_owned_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = _helper(monkeypatch)
    monkeypatch.setenv("DATARIVER_WORKSPACE_ID", "workspace-1")
    requests: list[Request] = []
    documents: list[dict[str, Any]] = [
        {
            "state": "ACTIVE",
            "next_offset": 731,
            "seen_count": 73_100,
            "expected_total": 73_125,
            "snapshot_consistent": False,
        },
        {
            "upserted": 25,
            "tombstoned": 0,
            "next_offset": None,
            "total": 73_125,
            "observed_at": "2026-07-23T00:00:00Z",
            "tombstone_status": "SUPPRESSED_UNVERIFIED_SNAPSHOT",
        },
    ]

    def urlopen(request: Request, *, timeout: int) -> _Response:
        assert timeout == 30
        requests.append(request)
        return _Response(json.dumps(documents.pop(0)).encode())

    monkeypatch.setattr(helper.urllib.request, "urlopen", urlopen)

    result = helper.synchronize_catalog_projection(run_id="scheduled__2026-07-23")

    assert len(requests) == 2
    assert requests[0].method == "GET"
    assert requests[1].method == "POST"
    assert json.loads(cast(bytes, requests[1].data)) == {
        "sync_id": str(
            helper.uuid5(
                helper.NAMESPACE_URL,
                "urn:datariver:catalog-sync:scheduled__2026-07-23",
            )
        ),
        "offset": 731,
        "limit": 100,
    }
    assert result["resumed_from_offset"] == 731
    assert result["pages"] == 1
    assert result["already_completed"] is False


def test_airflow_catalog_sync_does_not_replay_an_already_completed_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = _helper(monkeypatch)
    monkeypatch.setenv("DATARIVER_WORKSPACE_ID", "workspace-1")
    calls = 0

    def urlopen(request: Request, *, timeout: int) -> _Response:
        nonlocal calls
        calls += 1
        assert request.method == "GET"
        assert timeout == 30
        return _Response(
            json.dumps(
                {
                    "state": "COMPLETED",
                    "next_offset": None,
                    "seen_count": 50,
                    "expected_total": 50,
                    "snapshot_consistent": True,
                }
            ).encode()
        )

    monkeypatch.setattr(helper.urllib.request, "urlopen", urlopen)

    result = helper.synchronize_catalog_projection(run_id="manual__completed")

    assert calls == 1
    assert result["already_completed"] is True
    assert result["tombstone_status"] == "APPLIED"
