import os
import subprocess
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[3]
POC_COMPOSE = ROOT / "deploy" / "poc" / "docker-compose.poc.yaml"
AIRFLOW_COMPOSE = ROOT / "deploy" / "poc" / "docker-compose.airflow.yaml"
PREP_ENV_CONTRACT = ROOT / "deploy" / "prep39083" / "env-contract.json"
OPS_ENV_EXAMPLE = ROOT / "deploy" / "prep39083" / ".env.ops.example"
RUN_POC = ROOT / "scripts" / "run_poc.sh"


def _document(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_poc_web_publish_is_loopback_while_container_listener_remains_reachable() -> None:
    compose = _document(POC_COMPOSE)
    services = compose["services"]
    web = services["web"]

    assert web["ports"] == ["${POC_BIND_HOST:-127.0.0.1}:${POC_PORT:-39080}:8080"]
    assert web["environment"]["POC_SERVER_HOST"] == "0.0.0.0"  # noqa: S104
    assert web["networks"] == ["poc-services"]

    assert services["neo4j"]["ports"] == [
        "${POC_STATE_BIND_HOST:-127.0.0.1}:${POC_NEO4J_HTTP_PORT:-17475}:7474"
    ]
    assert services["pgvector"]["ports"] == [
        "${POC_STATE_BIND_HOST:-127.0.0.1}:${POC_POSTGRES_HOST_PORT:-15432}:5432"
    ]
    assert services["redis"]["ports"] == [
        "${POC_STATE_BIND_HOST:-127.0.0.1}:${POC_REDIS_PORT:-16379}:6379"
    ]


def test_prep_and_ops_publish_only_web_to_the_intranet() -> None:
    compose = _document(POC_COMPOSE)
    assert set(compose["services"]) == {"web", "pgvector", "neo4j", "redis"}

    contract = _document(PREP_ENV_CONTRACT)
    fixed = contract["ownership"]["FIXED"]
    assert fixed["POC_BIND_HOST"] == "0.0.0.0"  # noqa: S104 - required intranet bind.
    assert fixed["POC_PORT"] == "39083"
    assert fixed["POC_STATE_BIND_HOST"] == "127.0.0.1"

    ops = dict(
        line.split("=", maxsplit=1)
        for line in OPS_ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    assert ops["POC_BIND_HOST"] == "0.0.0.0"  # noqa: S104 - required intranet bind.
    assert ops["POC_PORT"] == "39083"
    assert ops["POC_STATE_BIND_HOST"] == "127.0.0.1"


def test_compose_injects_datahub_no_token_flag_with_closed_default() -> None:
    """Compose must inject POC_DATAHUB_ALLOW_NO_TOKEN with an explicit false default.
    This ensures the flag is env-file-controlled, not silently inherited from the shell,
    and that the fail-closed default is enforced even when the operator forgets to set it."""
    compose = _document(POC_COMPOSE)
    env = compose["services"]["web"]["environment"]
    # The value must be the Compose variable reference with an explicit false default.
    assert env["POC_DATAHUB_ALLOW_NO_TOKEN"] == "${POC_DATAHUB_ALLOW_NO_TOKEN:-false}"


def test_optional_airflow_uses_loopback_publish_and_shared_web_network() -> None:
    compose = _document(AIRFLOW_COMPOSE)
    airflow = compose["services"]["airflow"]
    environment = airflow["environment"]

    assert airflow["ports"] == ["${AIRFLOW_BIND_HOST:-127.0.0.1}:${AIRFLOW_PORT:-18888}:8080"]
    assert airflow["networks"] == ["poc-services"]
    assert environment["DATARIVER_API_BASE_URL"] == ("${AIRFLOW_DATARIVER_URL:-http://web:8080}")
    assert "web" in environment["NO_PROXY"].split(",")
    assert "web" in environment["no_proxy"].split(",")
    assert compose["networks"]["poc-services"] == {
        "external": True,
        "name": "${POC_SHARED_NETWORK:-datariver-poc-services}",
    }


def _fake_docker(tmp_path: Path) -> tuple[Path, Path]:
    capture = tmp_path / "docker-commands.txt"
    executable = tmp_path / "docker"
    executable.write_text(
        '#!/usr/bin/env bash\nprintf \'%s|%s\\n\' "${POC_PORT-unset}" "$*" >> "${CAPTURE_PATH}"\n',
        encoding="utf-8",
    )
    executable.chmod(0o700)
    return executable, capture


def test_run_poc_selected_env_file_owns_compose_keys(tmp_path: Path) -> None:
    _executable, capture = _fake_docker(tmp_path)
    env_file = tmp_path / "poc.env"
    env_file.write_text("POC_PORT=39123\n", encoding="utf-8")
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "CAPTURE_PATH": os.fspath(capture),
        "POC_ENV_FILE": os.fspath(env_file),
        "POC_PORT": "39999",
    }

    result = subprocess.run(  # noqa: S603 - fixed repository script under test.
        (RUN_POC, "status"),
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    invocation = capture.read_text(encoding="utf-8").strip()
    assert invocation.startswith("unset|compose --env-file ")
    assert invocation.endswith(" ps")


def test_run_poc_web_restart_is_bounded_to_web(tmp_path: Path) -> None:
    _executable, capture = _fake_docker(tmp_path)
    env_file = tmp_path / "poc.env"
    env_file.write_text("POC_PORT=39123\n", encoding="utf-8")
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "CAPTURE_PATH": os.fspath(capture),
        "POC_ENV_FILE": os.fspath(env_file),
    }

    result = subprocess.run(  # noqa: S603 - fixed repository script under test.
        (RUN_POC, "web-restart"),
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    commands = capture.read_text(encoding="utf-8").splitlines()
    assert len(commands) == 3
    assert commands[0].endswith(" build web")
    assert commands[1].endswith(" up -d --no-deps --force-recreate web")
    assert commands[2].endswith(" ps web")
    assert all(
        service not in "\n".join(commands)
        for service in ("pgvector", "neo4j", "redis", "airflow", "datahub")
    )
