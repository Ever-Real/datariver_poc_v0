from __future__ import annotations

from pathlib import Path


def _dags_root() -> Path:
    return Path(__file__).resolve().parents[3] / "infra/airflow/dags"


def test_registration_dags_are_explicitly_enabled_and_bounded() -> None:
    root = _dags_root()
    manual = (root / "manual_metadata_apply.py").read_text(encoding="utf-8")
    bulk = (root / "bulk_registration_prepare.py").read_text(encoding="utf-8")

    assert 'dag_id="datariver_manual_metadata_apply"' in manual
    assert 'dag_id="datariver_bulk_registration_prepare"' in bulk
    assert "is_paused_upon_creation=False" in manual
    assert "is_paused_upon_creation=False" in bulk
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

    assert 'states.get("FAILED", 0) > 0' in manual
    assert 'states.get("FAILED", 0) > 0' in bulk
    assert "raise RuntimeError" in manual
    assert "raise RuntimeError" in bulk
