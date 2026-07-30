from __future__ import annotations

import importlib.util
import io
import json
import sys
import urllib.parse
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from urllib.request import Request

import pytest
import yaml  # type: ignore[import-untyped]


class _Response(io.BytesIO):
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _dags_root() -> Path:
    return Path(__file__).resolve().parents[3] / "infra/airflow/dags"


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_module(name: str) -> ModuleType:
    path = _dags_root() / f"{name}.py"
    specification = importlib.util.spec_from_file_location(f"test_{name}", path)
    if specification is None or specification.loader is None:
        raise AssertionError(f"Unable to load {path}.")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _load_dispatch_helper(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    auth = ModuleType("datariver_quality_auth")
    dynamic_auth = cast(Any, auth)
    dynamic_auth.quality_api_base_url = lambda: "https://quality-api.example.test"
    dynamic_auth.quality_service_token = lambda: "quality-service-token"
    dynamic_auth.quality_workspace_id = lambda: "00000000-0000-4000-8000-000000000001"
    monkeypatch.setitem(sys.modules, "datariver_quality_auth", auth)
    return _load_module("datariver_quality_dispatch")


def test_quality_auth_uses_only_the_dedicated_client_and_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret_file = tmp_path / "quality-dispatch-client-secret"
    secret_file.write_text("dedicated-quality-secret", encoding="utf-8")
    monkeypatch.setenv(
        "DATARIVER_QUALITY_DISPATCH_OIDC_CLIENT_ID",
        "datariver-quality-dispatch",
    )
    monkeypatch.setenv(
        "DATARIVER_QUALITY_DISPATCH_OIDC_CLIENT_SECRET_FILE",
        str(secret_file),
    )
    monkeypatch.setenv(
        "DATARIVER_QUALITY_DISPATCH_OIDC_TOKEN_URL",
        "https://identity.example.test/realms/datariver/protocol/openid-connect/token",
    )
    monkeypatch.setenv(
        "DATARIVER_QUALITY_DISPATCH_API_BASE_URL",
        "https://quality-api.example.test/",
    )
    monkeypatch.setenv(
        "DATARIVER_QUALITY_DISPATCH_WORKSPACE_ID",
        "00000000-0000-4000-8000-000000000001",
    )
    auth = _load_module("datariver_quality_auth")
    requests: list[Request] = []

    def urlopen(request: Request, *, timeout: int) -> _Response:
        assert timeout == 15
        requests.append(request)
        return _Response(
            json.dumps(
                {
                    "access_token": "dedicated-quality-token",
                    "expires_in": 300,
                }
            ).encode()
        )

    monkeypatch.setattr(auth.urllib.request, "urlopen", urlopen)

    assert auth.quality_service_token() == "dedicated-quality-token"
    assert auth.quality_service_token() == "dedicated-quality-token"
    assert auth.quality_api_base_url() == "https://quality-api.example.test"
    assert auth.quality_workspace_id() == "00000000-0000-4000-8000-000000000001"
    assert len(requests) == 1
    assert requests[0].full_url.endswith("/protocol/openid-connect/token")
    token_request = urllib.parse.parse_qs(cast(bytes, requests[0].data).decode())
    assert token_request == {
        "grant_type": ["client_credentials"],
        "client_id": ["datariver-quality-dispatch"],
        "client_secret": ["dedicated-quality-secret"],
    }


def test_quality_dispatch_posts_only_call_id_and_accepts_a_bounded_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = _load_dispatch_helper(monkeypatch)
    requests: list[Request] = []
    first_run_id = "00000000-0000-4000-8000-000000000011"
    second_run_id = "00000000-0000-4000-8000-000000000012"

    def urlopen(request: Request, *, timeout: int) -> _Response:
        assert timeout == 30
        requests.append(request)
        return _Response(
            json.dumps(
                {
                    "created_run_ids": [first_run_id, second_run_id],
                    "created_run_count": 2,
                    "skipped_window_count": 3,
                    "replayed": False,
                }
            ).encode()
        )

    monkeypatch.setattr(helper.urllib.request, "urlopen", urlopen)
    result = helper.dispatch_due_quality_runs(call_id="scheduled__2026-07-30T00:00:00+00:00")

    assert result == {
        "created_run_ids": [first_run_id, second_run_id],
        "created_run_count": 2,
        "skipped_window_count": 3,
        "replayed": False,
    }
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.full_url == ("https://quality-api.example.test/api/v1/quality/internal/dispatch")
    assert json.loads(cast(bytes, request.data)) == {
        "call_id": "scheduled__2026-07-30T00:00:00+00:00"
    }
    assert request.get_header("Authorization") == "Bearer quality-service-token"
    assert request.get_header("X-workspace-id") == "00000000-0000-4000-8000-000000000001"
    assert request.get_header("X-purpose") == "scheduled-quality-dispatch"


@pytest.mark.parametrize(
    "document",
    (
        {
            "created_run_ids": [],
            "created_run_count": 0,
            "skipped_window_count": 0,
            "replayed": False,
            "source": "forbidden-contract-drift",
        },
        {
            "created_run_ids": ["00000000-0000-4000-8000-000000000011"],
            "created_run_count": 0,
            "skipped_window_count": 0,
            "replayed": False,
        },
        {
            "created_run_ids": [
                "00000000-0000-4000-8000-000000000011",
                "00000000-0000-4000-8000-000000000011",
            ],
            "created_run_count": 2,
            "skipped_window_count": 0,
            "replayed": True,
        },
    ),
)
def test_quality_dispatch_rejects_response_drift(
    monkeypatch: pytest.MonkeyPatch,
    document: dict[str, object],
) -> None:
    helper = _load_dispatch_helper(monkeypatch)

    def urlopen(_request: Request, *, timeout: int) -> _Response:
        assert timeout == 30
        return _Response(json.dumps(document).encode())

    monkeypatch.setattr(helper.urllib.request, "urlopen", urlopen)
    with pytest.raises(RuntimeError):
        helper.dispatch_due_quality_runs(call_id="scheduled__2026-07-30")


def test_quality_dispatch_dag_is_paused_bounded_and_server_scheduled() -> None:
    root = _dags_root()
    dag = (root / "quality_dispatch.py").read_text(encoding="utf-8")
    helper = (root / "datariver_quality_dispatch.py").read_text(encoding="utf-8")
    auth = (root / "datariver_quality_auth.py").read_text(encoding="utf-8")

    assert 'dag_id="datariver_quality_dispatch"' in dag
    assert "schedule=_quality_dispatch_schedule()" in dag
    assert 'os.getenv("DATARIVER_QUALITY_DISPATCH_SCHEDULE")' in dag
    assert "is_paused_upon_creation=True" in dag
    assert "catchup=False" in dag
    assert "max_active_runs=1" in dag
    assert "execution_timeout=timedelta(minutes=5)" in dag
    assert "/api/v1/quality/internal/dispatch" in helper
    assert "from datariver_auth" not in auth
    assert "DATARIVER_OIDC_CLIENT_ID" not in auth
    assert "DATARIVER_OIDC_CLIENT_SECRET_FILE" not in auth
    for forbidden in (
        "DATAHUB_TOKEN",
        "DATAHUB_BASE_URL",
        "POSTGRES_PASSWORD",
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
        "great_expectations",
        "psycopg",
    ):
        assert forbidden not in f"{auth}\n{helper}\n{dag}"


def test_quality_dispatch_schedule_is_parser_only_and_secret_is_scheduler_only() -> None:
    document = yaml.safe_load(
        (_repository_root() / "compose.airflow.yaml").read_text(encoding="utf-8")
    )
    assert isinstance(document, dict)
    services = document["services"]
    assert isinstance(services, dict)

    dag_processor = services["airflow-dag-processor"]
    assert dag_processor["environment"]["DATARIVER_QUALITY_DISPATCH_SCHEDULE"] is None

    for service_name, service in services.items():
        if service_name != "airflow-dag-processor":
            assert "DATARIVER_QUALITY_DISPATCH_SCHEDULE" not in service.get("environment", {})

        quality_secret_count = sum(
            (
                secret == "quality_dispatch_client_secret"
                if isinstance(secret, str)
                else secret.get("source") == "quality_dispatch_client_secret"
            )
            for secret in service.get("secrets", ())
        )
        assert quality_secret_count == (1 if service_name == "airflow-scheduler" else 0)
