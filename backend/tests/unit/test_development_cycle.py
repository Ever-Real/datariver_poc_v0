from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
MODULE_PATH = SCRIPTS / "development_cycle.py"


def _load_module() -> ModuleType:
    previous_platform_module = sys.modules.get("platform_workflow")
    sys.path.insert(0, str(SCRIPTS))
    try:
        specification = importlib.util.spec_from_file_location(
            "development_cycle_for_test",
            MODULE_PATH,
        )
        assert specification is not None
        assert specification.loader is not None
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS))
        if previous_platform_module is None:
            sys.modules.pop("platform_workflow", None)
        else:
            sys.modules["platform_workflow"] = previous_platform_module


cycle = _load_module()


@pytest.mark.parametrize(
    "remote_url",
    (
        "https://github.com/Ever-Real/datariver_v1.git",
        "git@github.com:Ever-Real/datariver_v1.git",
        "ssh://git@github.com/Ever-Real/datariver_v1.git",
    ),
)
def test_expected_ever_real_origin_is_accepted(remote_url: str) -> None:
    cycle.validate_origin_url(remote_url)


@pytest.mark.parametrize(
    "remote_url",
    (
        "https://github.com/JayJin/datariver_v1.git",
        "https://token@github.com/Ever-Real/datariver_v1.git",
        "http://github.com/Ever-Real/datariver_v1.git",
        "https://github.com/Ever-Real/another-repository.git",
    ),
)
def test_unapproved_origin_is_rejected(remote_url: str) -> None:
    with pytest.raises(cycle.DevelopmentCycleError):
        cycle.validate_origin_url(remote_url)


def test_preparation_bootstrap_preserves_selected_operator_modes(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.wsl-intranet-development"
    command = tuple(
        str(value)
        for value in cycle.preparation_bootstrap_command(
            env_file,
            {
                "DATAHUB_BASE_URL": "http://127.0.0.1:8080",
                "INTRANET_SOURCE_HOST_ENABLED": "true",
                "APP_PUBLIC_ORIGIN": "https://datariver.example.internal",
                "OIDC_PUBLIC_ORIGIN": "https://identity.example.internal",
                "AIRFLOW_SOURCE_API_BRIDGE_ENABLED": "true",
                "KNOWLEDGE_SOURCE_WORKER_ENABLED": "true",
            },
        )
    )

    assert command[-7:] == (
        "--intranet-source-host",
        "--web-public-origin",
        "https://datariver.example.internal",
        "--oidc-public-origin",
        "https://identity.example.internal",
        "--source-host-airflow-bridge",
        "--enable-knowledge-source-worker",
    )
    assert "DATAHUB_BASE_URL" not in command


def test_preparation_boolean_must_be_explicit() -> None:
    with pytest.raises(cycle.DevelopmentCycleError):
        cycle.env_bool({"NEO4J_PROJECTION_ENABLED": "yes"}, "NEO4J_PROJECTION_ENABLED")
