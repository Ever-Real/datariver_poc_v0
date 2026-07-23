from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest


def _dags_root() -> Path:
    return Path(__file__).resolve().parents[3] / "infra/airflow/dags"


def test_registration_dags_are_paused_by_default_and_bounded() -> None:
    root = _dags_root()
    manual = (root / "manual_metadata_apply.py").read_text(encoding="utf-8")
    bulk = (root / "bulk_registration_prepare.py").read_text(encoding="utf-8")

    assert 'dag_id="datariver_manual_metadata_apply"' in manual
    assert 'dag_id="datariver_bulk_registration_prepare"' in bulk
    assert "is_paused_upon_creation=True" in manual
    assert "is_paused_upon_creation=True" in bulk
    assert "max_active_runs=1" in manual
    assert "max_active_runs=1" in bulk


def test_bulk_airflow_helper_calls_only_the_oidc_protected_datariver_api() -> None:
    helper = (_dags_root() / "datariver_bulk_registration.py").read_text(encoding="utf-8")

    assert "/api/v1/registration/bulk-preparations/execute" in helper
    assert "service_token()" in helper
    assert 'os.environ["DATARIVER_WORKSPACE_ID"]' in helper
    for forbidden in (
        "DATAHUB_TOKEN",
        "DATAHUB_BASE_URL",
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
        "POSTGRES_PASSWORD",
        "boto3",
        "psycopg",
    ):
        assert forbidden not in helper


def test_registration_airflow_helpers_fail_the_run_on_terminal_job_failure() -> None:
    root = _dags_root()
    manual = (root / "datariver_manual_metadata.py").read_text(encoding="utf-8")
    bulk = (root / "datariver_bulk_registration.py").read_text(encoding="utf-8")
    manual_dag = (root / "manual_metadata_apply.py").read_text(encoding="utf-8")
    bulk_dag = (root / "bulk_registration_prepare.py").read_text(encoding="utf-8")

    assert 'states.get("FAILED", 0) > 0' in manual
    assert 'states.get("FAILED", 0) > 0' in bulk
    assert "raise TerminalManualMetadataFailure" in manual
    assert "raise TerminalBulkRegistrationFailure" in bulk
    assert "except TerminalManualMetadataFailure" in manual_dag
    assert "except TerminalBulkRegistrationFailure" in bulk_dag
    assert "raise AirflowFailException" in manual_dag
    assert "raise AirflowFailException" in bulk_dag
    assert '"X-Run-Call": str(ordinal)' in manual
    assert '"X-Run-Call": str(ordinal)' in bulk
    assert "_ALLOWED_STATES" in manual


class _Response(io.BytesIO):
    status = 200

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _load_helper(monkeypatch: pytest.MonkeyPatch, name: str) -> ModuleType:
    auth = ModuleType("datariver_auth")
    dynamic_auth = cast(Any, auth)
    dynamic_auth.datariver_api_base_url = lambda: "https://datariver.test"
    dynamic_auth.service_token = lambda: "test-token"
    monkeypatch.setitem(sys.modules, "datariver_auth", auth)
    path = _dags_root() / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"test_{name}", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("helper_name", "function_name", "exception_name", "failed_document"),
    [
        (
            "datariver_manual_metadata",
            "apply_manual_metadata_receipts",
            "TerminalManualMetadataFailure",
            {"processed": True, "state": "FAILED"},
        ),
        (
            "datariver_bulk_registration",
            "prepare_bulk_registration_receipts",
            "TerminalBulkRegistrationFailure",
            {"processed": True, "state": "FAILED", "item_count": 1},
        ),
    ],
)
def test_registration_helpers_preserve_terminal_failure_as_a_typed_exception(
    monkeypatch: pytest.MonkeyPatch,
    helper_name: str,
    function_name: str,
    exception_name: str,
    failed_document: dict[str, Any],
) -> None:
    monkeypatch.setenv("DATARIVER_WORKSPACE_ID", "00000000-0000-0000-0000-000000000001")
    helper = _load_helper(monkeypatch, helper_name)
    responses = iter(
        (
            failed_document,
            {"processed": False},
            {"processed": False},
        )
    )

    def urlopen(_request: object, *, timeout: int) -> _Response:
        assert timeout in {60, 300}
        return _Response(json.dumps(next(responses)).encode())

    monkeypatch.setattr(helper.urllib.request, "urlopen", urlopen)
    function = getattr(helper, function_name)
    terminal_error = getattr(helper, exception_name)
    with pytest.raises(terminal_error):
        function(run_id="registration-terminal-test")

    assert function(run_id="registration-empty-retry")["processed"] == 0


def test_registration_helpers_enforce_worker_and_http_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manual = _load_helper(monkeypatch, "datariver_manual_metadata")
    bulk = _load_helper(monkeypatch, "datariver_bulk_registration")

    with pytest.raises(ValueError, match="between 1 and 10"):
        manual.apply_manual_metadata_receipts(run_id="test", maximum_submissions=11)
    with pytest.raises(ValueError, match="between 1 and 8"):
        bulk.prepare_bulk_registration_receipts(run_id="test", maximum_preparations=9)
