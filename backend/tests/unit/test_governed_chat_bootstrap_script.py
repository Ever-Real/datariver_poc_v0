from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_MODULE_PATH = ROOT / "scripts" / "platform_workflow.py"
BOOTSTRAP_MODULE_PATH = ROOT / "scripts" / "bootstrap_local_governed_chat.py"


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


workflow = _load_module("platform_workflow", WORKFLOW_MODULE_PATH)
bootstrap = _load_module("governed_chat_bootstrap_script", BOOTSTRAP_MODULE_PATH)


def test_source_host_profile_runs_governance_bootstrap_through_selected_environment(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env.wsl-intranet-development"
    module_arguments = ("--jurisdiction", "kr-intranet")

    command = bootstrap._bootstrap_command(
        env_file=env_file,
        values={"DATARIVER_OPERATOR_PROFILE": "wsl-source-host"},
        module_arguments=module_arguments,
    )

    assert command == (
        str(ROOT / "scripts" / "dev_host.sh"),
        "bootstrap-governed-chat",
        "--env-file",
        str(env_file),
        "--",
        *module_arguments,
    )


def test_container_profile_keeps_compose_governance_bootstrap(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.mac-development"

    command = bootstrap._bootstrap_command(
        env_file=env_file,
        values={"DATARIVER_OPERATOR_PROFILE": "mac-development"},
        module_arguments=("--jurisdiction", "kr-local"),
    )

    assert tuple(command[-7:]) == (
        "-T",
        "api",
        "/app/.venv/bin/python",
        "-m",
        "datariver.local_governed_chat_bootstrap",
        "--jurisdiction",
        "kr-local",
    )
