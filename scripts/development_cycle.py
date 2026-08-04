#!/usr/bin/env python3
"""Stable development and preparation-PC update entry points."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from platform_workflow import WorkflowError, read_env_values

ROOT = Path(__file__).resolve().parents[1]
DEV_BRANCH = "dev"
EXPECTED_GITHUB_HOST = "github.com"
EXPECTED_GITHUB_PATH = "Ever-Real/datariver_v1"
DEFAULT_PREPARATION_ENV = Path(".env.wsl-intranet-development")
READINESS_CONTRACT = "DATARIVER_PREPARATION_READINESS_V1"
LOCAL_TOPOLOGY_RECONCILIATION = "mac-development-graph-gateway-v1"
READINESS_MANIFEST = ROOT / "runtime" / "portability" / "amd64-readiness.json"
CANONICAL_ENV_SCHEMA = ROOT / ".env.example"
PYTHON_LOCK = ROOT / "uv.lock"
FRONTEND_LOCK = ROOT / "frontend" / "package-lock.json"
DATABASE_REVISION_MODULE = (
    ROOT / "backend" / "src" / "datariver" / "infrastructure" / "db" / "revision.py"
)
TOPOLOGY_BOOLEAN_KEYS = (
    "INTRANET_SOURCE_HOST_ENABLED",
    "AIRFLOW_SOURCE_API_BRIDGE_ENABLED",
    "KNOWLEDGE_SOURCE_WORKER_ENABLED",
    "KNOWLEDGE_STUDIO_PROPOSAL_WORKER_ENABLED",
    "KNOWLEDGE_STUDIO_INGESTION_WORKER_ENABLED",
    "NEO4J_PROJECTION_ENABLED",
    "LOCAL_INFERENCE_SOURCE_HOST_ENABLED",
    "LOCAL_OLLAMA_CHAT_ENABLED",
    "LOCAL_OLLAMA_EMBEDDING_ENABLED",
    "LOCAL_LLAMA_CPP_RERANKER_ENABLED",
    "INTRANET_OPENAI_COMPATIBLE_CHAT_ENABLED",
    "INTRANET_OPENAI_COMPATIBLE_EMBEDDING_ENABLED",
    "INTRANET_RERANKER_ENABLED",
)

RUFF_FORMAT_PATHS = (
    "backend/src",
    "backend/tests",
    "infra/airflow/dags",
    "scripts/cleanup_knowledge_studio_test_artifacts.py",
    "scripts/platform_workflow.py",
    "scripts/reconcile_manual_receipts.py",
    "scripts/render_wsl_intranet_nginx.py",
    "scripts/verify_nginx_headers.py",
    "scripts/workflow_source_host_infra.py",
    "scripts/development_cycle.py",
)
RUFF_CHECK_PATHS = (
    "backend/src",
    "backend/tests",
    "infra/airflow/dags",
    "scripts/configure_keycloak_assurance.py",
    "scripts/cleanup_knowledge_studio_test_artifacts.py",
    "scripts/development_cycle.py",
    "scripts/generate_initial_migration.py",
    "scripts/generate_semiconductor_seed.py",
    "scripts/local_reranker_service.py",
    "scripts/migrate_s3_objects.py",
    "scripts/platform_workflow.py",
    "scripts/probe_pgbouncer_rls.py",
    "scripts/probe_policy_revocation.py",
    "scripts/probe_s3_contract.py",
    "scripts/reconcile_manual_receipts.py",
    "scripts/render_wsl_intranet_nginx.py",
    "scripts/verify_datahub_contract.py",
    "scripts/verify_datahub_image_inventory.py",
    "scripts/verify_nginx_headers.py",
    "scripts/verify_static.py",
    "scripts/workflow_source_host_infra.py",
)
MYPY_PATHS = (
    "backend/src",
    "backend/tests",
    "scripts/cleanup_knowledge_studio_test_artifacts.py",
    "scripts/development_cycle.py",
    "scripts/local_reranker_service.py",
    "scripts/migrate_s3_objects.py",
    "scripts/platform_workflow.py",
    "scripts/probe_s3_contract.py",
    "scripts/reconcile_manual_receipts.py",
    "scripts/render_wsl_intranet_nginx.py",
    "scripts/verify_nginx_headers.py",
    "scripts/workflow_source_host_infra.py",
)


class DevelopmentCycleError(RuntimeError):
    """An operator-correctable development-cycle failure."""


class Runner:
    """Execute argument-vector commands without shell interpolation."""

    def __init__(self, *, root: Path = ROOT) -> None:
        self.root = root
        self.step = 0

    def note(self, message: str) -> None:
        self.step += 1
        print(f"[{self.step:02d}] {message}", flush=True)

    def run(
        self,
        arguments: Sequence[str | os.PathLike[str]],
        *,
        cwd: Path | None = None,
        capture_output: bool = False,
        reveal_failure_output: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        command = [os.fspath(argument) for argument in arguments]
        print(f"     $ {shlex.join(command)}", flush=True)
        try:
            return subprocess.run(  # noqa: S603 - no shell; every argv is repository-owned.
                command,
                cwd=cwd or self.root,
                check=True,
                capture_output=capture_output,
                text=True,
            )
        except subprocess.CalledProcessError as error:
            if capture_output and reveal_failure_output:
                if error.stdout:
                    print(error.stdout.rstrip(), file=sys.stderr)
                if error.stderr:
                    print(error.stderr.rstrip(), file=sys.stderr)
            raise DevelopmentCycleError(
                f"Command failed with exit code {error.returncode}: {shlex.join(command)}"
            ) from error

    def output(
        self,
        arguments: Sequence[str | os.PathLike[str]],
        *,
        cwd: Path | None = None,
        reveal_failure_output: bool = True,
    ) -> str:
        return self.run(
            arguments,
            cwd=cwd,
            capture_output=True,
            reveal_failure_output=reveal_failure_output,
        ).stdout.strip()


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the stable DataRiver dev publication or preparation-PC source update contract."
        )
    )
    parser.add_argument(
        "action",
        choices=("verify", "dev-publish", "prep-update", "prep-check"),
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_PREPARATION_ENV,
        help=("Preparation source-host environment (default: .env.wsl-intranet-development)."),
    )
    parser.add_argument(
        "--reconcile-local-topology",
        choices=(LOCAL_TOPOLOGY_RECONCILIATION,),
        help=("One reviewed Mac-development graph/gateway adoption, valid only with dev-publish."),
    )
    return parser.parse_args()


def validate_local_topology_reconciliation(action: str, value: str | None) -> str | None:
    if value is None:
        return None
    if action != "dev-publish" or value != LOCAL_TOPOLOGY_RECONCILIATION:
        raise DevelopmentCycleError(
            "Local topology reconciliation is valid only for the reviewed dev-publish action."
        )
    return value


def require_command(name: str) -> None:
    if shutil.which(name) is None:
        raise DevelopmentCycleError(f"Required command is unavailable: {name}")


def git_output(runner: Runner, *arguments: str) -> str:
    return runner.output(("git", *arguments))


def require_dev_checkout(runner: Runner) -> None:
    branch = git_output(runner, "branch", "--show-current")
    if branch != DEV_BRANCH:
        raise DevelopmentCycleError(
            f"This workflow runs only on {DEV_BRANCH!r}; current branch is {branch!r}."
        )
    status = git_output(runner, "status", "--porcelain", "--untracked-files=normal")
    if status:
        raise DevelopmentCycleError(
            "The worktree is not clean. Commit the coherent change on dev before publication."
        )


def validate_origin_url(remote_url: str) -> None:
    """Accept only the repository-owned Ever-Real GitHub destination."""

    normalized = remote_url.strip()
    host: str | None
    path: str
    if normalized.startswith("git@"):
        authority, separator, path = normalized.partition(":")
        host = authority.removeprefix("git@") if separator else None
    else:
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"https", "ssh"}:
            raise DevelopmentCycleError("origin must use HTTPS or SSH.")
        if parsed.username not in {None, "git"} or parsed.password is not None:
            raise DevelopmentCycleError("origin must not embed GitHub credentials.")
        host = parsed.hostname
        path = parsed.path.lstrip("/")
    repository_path = path.removesuffix(".git").rstrip("/")
    if host != EXPECTED_GITHUB_HOST or repository_path != EXPECTED_GITHUB_PATH:
        raise DevelopmentCycleError(
            "origin must resolve exactly to github.com/Ever-Real/datariver_v1."
        )


def require_expected_origin(runner: Runner) -> None:
    validate_origin_url(git_output(runner, "remote", "get-url", "--push", "origin"))


def current_commit(runner: Runner) -> str:
    commit = git_output(runner, "rev-parse", "--verify", "HEAD")
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise DevelopmentCycleError("Git did not return a full lowercase commit ID.")
    return commit


def verify_remote_dev(runner: Runner, expected_commit: str) -> None:
    output = git_output(runner, "ls-remote", "--heads", "origin", "refs/heads/dev")
    fields = output.split()
    if len(fields) != 2 or fields[1] != "refs/heads/dev":
        raise DevelopmentCycleError("origin/dev did not return one exact branch reference.")
    if fields[0] != expected_commit:
        raise DevelopmentCycleError(
            f"origin/dev is {fields[0]}, but the local verified commit is {expected_commit}."
        )


def verify_source(runner: Runner) -> None:
    python_bin = ROOT / ".venv" / "bin" / "python"
    ruff_bin = ROOT / ".venv" / "bin" / "ruff"
    mypy_bin = ROOT / ".venv" / "bin" / "mypy"
    pytest_bin = ROOT / ".venv" / "bin" / "pytest"
    for executable in (python_bin, ruff_bin, mypy_bin, pytest_bin):
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise DevelopmentCycleError(
                "The locked Python environment is incomplete. "
                "Run 'uv sync --frozen --all-extras' on the connected development PC."
            )
    if not (ROOT / "frontend" / "node_modules").is_dir():
        raise DevelopmentCycleError(
            "Frontend dependencies are absent. Run 'npm --prefix frontend ci' on the "
            "connected development PC."
        )

    runner.note("Ruff formatting and lint gates")
    runner.run((ruff_bin, "format", "--check", *RUFF_FORMAT_PATHS))
    runner.run((ruff_bin, "check", *RUFF_CHECK_PATHS))
    runner.note("Strict Python typing gate")
    runner.run((mypy_bin, *MYPY_PATHS))
    runner.note("Backend regression and static architecture gates")
    runner.run((pytest_bin, "backend/tests", "-q"))
    runner.run((python_bin, "scripts/verify_static.py"))
    runner.note("Frontend type, lint, regression and production-build gates")
    runner.run(("npm", "run", "typecheck"), cwd=ROOT / "frontend")
    runner.run(("npm", "run", "lint"), cwd=ROOT / "frontend")
    runner.run(("npm", "run", "test", "--", "--run"), cwd=ROOT / "frontend")
    runner.run(("npm", "run", "build"), cwd=ROOT / "frontend")


def require_platform(*, expected_system: str, expected_machines: set[str]) -> None:
    system = platform.system()
    machine = platform.machine().lower()
    if system != expected_system or machine not in expected_machines:
        allowed = ", ".join(sorted(expected_machines))
        raise DevelopmentCycleError(
            f"This action requires {expected_system} on {allowed}; observed {system} on {machine}."
        )


def _project_python() -> Path:
    python_bin = ROOT / ".venv" / "bin" / "python"
    if not python_bin.is_file() or not os.access(python_bin, os.X_OK):
        raise DevelopmentCycleError("The project Python interpreter is absent or not executable.")
    return python_bin


def level2_core_prestate_command() -> tuple[str | os.PathLike[str], ...]:
    """Return the exact private-supervisor argv; its required cwd is ``ROOT``."""

    return (
        _project_python(),
        ROOT / "scripts" / "workflow_update_restart.py",
        "--diagnostic-phase",
        "LEVEL2_CORE_PRESTATE",
    )


def dev_runtime_update_command(
    reconciliation: str | None,
) -> tuple[str | os.PathLike[str], ...]:
    command: list[str | os.PathLike[str]] = [
        _project_python(),
        ROOT / "scripts" / "workflow_update_restart.py",
        "--profile",
        "mac-development",
        "--refresh-bootstrap",
        "--assume-yes",
    ]
    if reconciliation is None:
        command.extend(("--publication-scope", "level2-core"))
    else:
        command.extend(("--reconcile-local-topology", reconciliation))
    return tuple(command)


def dev_publish(runner: Runner, *, reconciliation: str | None = None) -> None:
    require_platform(expected_system="Darwin", expected_machines={"arm64", "aarch64"})
    require_command("git")
    require_command("npm")
    require_dev_checkout(runner)
    require_expected_origin(runner)
    commit = current_commit(runner)
    runner.note("현재 dev commit 전체 소스 검증")
    verify_source(runner)
    runner.note("검증한 commit을 Mac 개발 runtime에 적용")
    runner.run(dev_runtime_update_command(reconciliation))
    runner.note("검증한 dev commit을 Ever-Real GitHub에 push")
    runner.run(("git", "push", "origin", "dev"))
    runner.note("GitHub origin/dev SHA 일치 확인")
    verify_remote_dev(runner, commit)
    print(f"DEV_PUBLISHED={commit}", flush=True)


def env_path(value: Path) -> Path:
    resolved = value.expanduser()
    return resolved.resolve() if resolved.is_absolute() else (ROOT / resolved).resolve()


def env_bool(values: Mapping[str, str], key: str, *, default: bool = False) -> bool:
    value = values.get(key)
    if value is None:
        return default
    if value not in {"true", "false"}:
        raise DevelopmentCycleError(f"{key} must be exactly true or false.")
    return value == "true"


def canonical_json_sha256(value: object) -> str:
    """Hash one non-secret canonical JSON value."""

    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise DevelopmentCycleError(f"Readiness input cannot be read: {path}") from error
    return digest.hexdigest()


def environment_schema_sha256(values: Mapping[str, str]) -> str:
    """Fingerprint only environment key names; never persist values or value hashes."""

    return canonical_json_sha256(sorted(values))


def selected_topology(values: Mapping[str, str]) -> dict[str, object]:
    """Return the bounded, non-secret topology switches used by the source host."""

    return {
        "operator_profile": require_env_value(values, "DATARIVER_OPERATOR_PROFILE"),
        "features": {key: env_bool(values, key) for key in TOPOLOGY_BOOLEAN_KEYS},
    }


def require_env_value(values: Mapping[str, str], key: str) -> str:
    value = values.get(key, "").strip()
    if not value:
        raise DevelopmentCycleError(f"{key} is missing from the preparation environment.")
    return value


def preparation_bootstrap_command(
    selected_env: Path,
    values: Mapping[str, str],
) -> tuple[str | os.PathLike[str], ...]:
    command: list[str | os.PathLike[str]] = [
        ROOT / "scripts" / "bootstrap.sh",
        "--env-file",
        selected_env,
        "--host-development",
        "--datahub-base-url",
        require_env_value(values, "DATAHUB_BASE_URL"),
    ]
    if env_bool(values, "INTRANET_SOURCE_HOST_ENABLED"):
        command.extend(
            (
                "--intranet-source-host",
                "--web-public-origin",
                require_env_value(values, "APP_PUBLIC_ORIGIN"),
                "--oidc-public-origin",
                require_env_value(values, "OIDC_PUBLIC_ORIGIN"),
            )
        )
    if env_bool(values, "AIRFLOW_SOURCE_API_BRIDGE_ENABLED"):
        command.append("--source-host-airflow-bridge")
    if env_bool(values, "KNOWLEDGE_SOURCE_WORKER_ENABLED"):
        command.append("--enable-knowledge-source-worker")
    if env_bool(values, "KNOWLEDGE_STUDIO_PROPOSAL_WORKER_ENABLED"):
        command.append("--enable-knowledge-studio-proposal-worker")
    return tuple(command)


def changed_paths(runner: Runner, older: str, newer: str) -> set[str]:
    if older == newer:
        return set()
    return set(git_output(runner, "diff", "--name-only", f"{older}..{newer}").splitlines())


def sync_changed_dependencies(runner: Runner, paths: set[str]) -> None:
    python_changed = bool({"pyproject.toml", "uv.lock"}.intersection(paths))
    python_missing = not (ROOT / ".venv" / "bin" / "python").is_file()
    if python_changed or python_missing:
        require_command("uv")
        runner.note("변경된 Python lock을 승인된 로컬 cache에서 동기화")
        runner.run(("uv", "sync", "--frozen", "--all-extras", "--offline"))

    frontend_changed = bool(
        {"frontend/package.json", "frontend/package-lock.json"}.intersection(paths)
    )
    frontend_missing = not (ROOT / "frontend" / "node_modules").is_dir()
    if frontend_changed or frontend_missing:
        require_command("npm")
        runner.note("변경된 Frontend lock을 승인된 로컬 cache에서 동기화")
        runner.run(
            (
                "npm",
                "--prefix",
                "frontend",
                "ci",
                "--offline",
                "--include=optional",
                "--no-audit",
                "--no-fund",
            )
        )


def source_host_arguments(
    action: str,
    selected_env: Path,
) -> tuple[str | os.PathLike[str], ...]:
    return (
        ROOT / "scripts" / "dev_host.sh",
        action,
        "--env-file",
        selected_env,
    )


def parse_source_host_preflight(output: str) -> dict[str, object]:
    """Retain only the existing non-secret capability fields from preflight."""

    try:
        document = json.loads(output)
    except json.JSONDecodeError as error:
        raise DevelopmentCycleError(
            "Source-host preflight did not return JSON evidence."
        ) from error
    if not isinstance(document, dict):
        raise DevelopmentCycleError("Source-host preflight evidence must be one JSON object.")

    knowledge = document.get("knowledge_source_analysis")
    graph = document.get("neo4j_projection")
    local_inference = document.get("local_inference_source_host")
    runtime_activation = document.get("runtime_activation")
    if knowledge not in {"CONFIGURED", "NOT_CONFIGURED"}:
        raise DevelopmentCycleError("Source-host knowledge capability evidence is invalid.")
    if graph not in {"CONFIGURED", "NOT_CONFIGURED"}:
        raise DevelopmentCycleError("Source-host graph capability evidence is invalid.")
    if not isinstance(local_inference, bool) or not isinstance(runtime_activation, bool):
        raise DevelopmentCycleError("Source-host boolean capability evidence is invalid.")

    raw_endpoint = document.get("neo4j_endpoint")
    endpoint: dict[str, object] | None
    if raw_endpoint is None:
        endpoint = None
    elif isinstance(raw_endpoint, dict):
        endpoint = {
            key: raw_endpoint.get(key)
            for key in ("scheme", "host", "port", "expected_source_host_port")
        }
        if not all(value is None or isinstance(value, (str, int)) for value in endpoint.values()):
            raise DevelopmentCycleError("Source-host graph endpoint evidence is invalid.")
    else:
        raise DevelopmentCycleError("Source-host graph endpoint evidence is invalid.")
    return {
        "knowledge_source_analysis": knowledge,
        "local_inference_source_host": local_inference,
        "neo4j_projection": graph,
        "neo4j_endpoint": endpoint,
        "runtime_activation": runtime_activation,
    }


def capture_source_host_preflight(runner: Runner, selected_env: Path) -> dict[str, object]:
    output = runner.output(
        source_host_arguments("preflight", selected_env), reveal_failure_output=False
    )
    capabilities = parse_source_host_preflight(output)
    safe_output = json.dumps(capabilities, sort_keys=True, separators=(",", ":"))
    print(f"     {safe_output}", flush=True)
    return capabilities


def prepare_source_host(runner: Runner, selected_env: Path) -> dict[str, object]:
    values = read_env_values(selected_env)
    runner.note("기존 operator 값과 secret을 보존하며 환경 schema 재적용")
    runner.run(preparation_bootstrap_command(selected_env, values))
    refreshed_values = read_env_values(selected_env)
    infrastructure_command: list[str | os.PathLike[str]] = [
        ROOT / "scripts" / "workflow_source_host_infra.py",
        "--env-file",
        selected_env,
    ]
    if env_bool(refreshed_values, "NEO4J_PROJECTION_ENABLED"):
        infrastructure_command.append("--reuse-loaded-neo4j")
    infrastructure_command.append("prepare")
    runner.note("loopback PostgreSQL, Keycloak 및 선택 Neo4j 준비")
    runner.run(tuple(infrastructure_command))
    runner.note("현재 Web origin과 Keycloak client 계약 동기화")
    runner.run(
        (
            ROOT / "scripts" / "configure_keycloak_host_dev.sh",
            "--env-file",
            selected_env,
        )
    )
    runner.note("현재 source migration 및 개발 identity 적용")
    runner.run(source_host_arguments("migrate", selected_env))
    runner.run(source_host_arguments("bootstrap-identity", selected_env))
    runner.note("최종 Settings preflight 후 source-host 시작")
    capabilities = capture_source_host_preflight(runner, selected_env)
    runner.run(source_host_arguments("start", selected_env))
    runner.run(source_host_arguments("status", selected_env))
    health = verify_source_host_health(runner, read_env_values(selected_env))
    return {"capabilities": capabilities, "health": health}


def probe_url(url: str, *, attempts: int = 20) -> dict[str, object]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    last_error: Exception | None = None
    for _attempt in range(attempts):
        try:
            with opener.open(url, timeout=5) as response:
                response.read(512)
            if 200 <= response.status < 400:
                print(f"     {url} -> HTTP {response.status}", flush=True)
                return {"url": url, "status": response.status}
            last_error = DevelopmentCycleError(f"Unexpected HTTP status {response.status}")
        except Exception as error:
            last_error = error
        time.sleep(1)
    raise DevelopmentCycleError(f"Health probe failed for {url}: {last_error}")


def verify_source_host_health(
    runner: Runner,
    values: Mapping[str, str],
) -> dict[str, dict[str, object]]:
    api_port = require_env_value(values, "API_PORT")
    web_port = require_env_value(values, "WEB_PORT")
    keycloak_port = require_env_value(values, "KEYCLOAK_PORT")
    if not all(
        value.isdigit() and 1 <= int(value) <= 65535
        for value in (api_port, web_port, keycloak_port)
    ):
        raise DevelopmentCycleError("API_PORT, WEB_PORT and KEYCLOAK_PORT must be valid ports.")
    runner.note("API, Web 및 loopback OIDC health 검증")
    return {
        "api": probe_url(f"http://127.0.0.1:{api_port}/api/v1/health/ready"),
        "web": probe_url(f"http://127.0.0.1:{web_port}/"),
        "oidc": probe_url(
            f"http://127.0.0.1:{keycloak_port}/realms/datariver/.well-known/openid-configuration"
        ),
    }


def required_database_revision() -> str:
    source = DATABASE_REVISION_MODULE.read_text(encoding="utf-8")
    match = re.search(
        r'^REQUIRED_DATABASE_REVISION = "([0-9a-f]+)"$',
        source,
        flags=re.MULTILINE,
    )
    if match is None:
        raise DevelopmentCycleError("The packaged database revision is not explicit.")
    return match.group(1)


def parse_sole_alembic_head(output: str, *, required_revision: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if len(lines) != 1:
        raise DevelopmentCycleError("Alembic must expose exactly one schema head.")
    match = re.fullmatch(r"([0-9a-f]+) \(head\)", lines[0])
    if match is None:
        raise DevelopmentCycleError("Alembic returned an invalid schema-head result.")
    revision = match.group(1)
    if revision != required_revision:
        raise DevelopmentCycleError(
            "The packaged database revision does not match the sole Alembic head."
        )
    return revision


def sole_alembic_head(runner: Runner) -> str:
    python_bin = ROOT / ".venv" / "bin" / "python"
    if not python_bin.is_file() or not os.access(python_bin, os.X_OK):
        raise DevelopmentCycleError("The locked Python runtime is unavailable for readiness.")
    output = runner.output(
        (python_bin, "-m", "alembic", "-c", ROOT / "backend" / "alembic.ini", "heads")
    )
    return parse_sole_alembic_head(output, required_revision=required_database_revision())


def toolchain_evidence(runner: Runner) -> dict[str, object]:
    python_bin = ROOT / ".venv" / "bin" / "python"
    for command in ("uv", "node", "npm", "docker"):
        require_command(command)
    versions = {
        "python": runner.output((python_bin, "--version")),
        "uv": runner.output(("uv", "--version")),
        "node": runner.output(("node", "--version")),
        "npm": runner.output(("npm", "--version")),
        "docker": runner.output(("docker", "version", "--format", "{{.Server.Version}}")),
        "docker_compose": runner.output(("docker", "compose", "version", "--short")),
    }
    return {"versions": versions, "sha256": canonical_json_sha256(versions)}


def build_readiness_evidence(
    runner: Runner,
    *,
    selected_env: Path,
    source_commit: str,
    origin_commit: str,
    runtime: Mapping[str, object],
) -> dict[str, object]:
    """Build evidence only after the caller has completed runtime checks."""

    docker_platform = runner.output(
        ("docker", "version", "--format", "{{.Server.Os}}/{{.Server.Arch}}")
    )
    if docker_platform != "linux/amd64":
        raise DevelopmentCycleError(
            f"Preparation Docker must be linux/amd64; observed {docker_platform!r}."
        )
    if source_commit != origin_commit:
        raise DevelopmentCycleError("The prepared source and origin/dev commits differ.")

    values = read_env_values(selected_env)
    canonical_values = read_env_values(CANONICAL_ENV_SCHEMA)
    locks: dict[str, object] = {
        "uv_lock_sha256": file_sha256(PYTHON_LOCK),
        "frontend_package_lock_sha256": file_sha256(FRONTEND_LOCK),
    }
    locks["sha256"] = canonical_json_sha256(locks)
    head = sole_alembic_head(runner)
    return {
        "contract": READINESS_CONTRACT,
        "evidence_scope": "last-successful-preparation-readiness",
        "source": {
            "branch": DEV_BRANCH,
            "commit": source_commit,
            "origin_dev_commit": origin_commit,
            "origin_repository": f"{EXPECTED_GITHUB_HOST}/{EXPECTED_GITHUB_PATH}",
        },
        "platform": {"host": "linux/amd64", "docker_server": docker_platform},
        "locks": locks,
        "toolchain": toolchain_evidence(runner),
        "environment": {
            "file_name": selected_env.name,
            "canonical_schema_sha256": environment_schema_sha256(canonical_values),
            "selected_schema_sha256": environment_schema_sha256(values),
        },
        "topology": selected_topology(values),
        "database": {
            "alembic_head": head,
            "alembic_current": head,
            "proof": "api-ready-required-revision",
        },
        "capabilities": runtime["capabilities"],
        "health": runtime["health"],
    }


def load_readiness_manifest(path: Path = READINESS_MANIFEST) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DevelopmentCycleError("The previous readiness manifest cannot be read.") from error
    if not isinstance(document, dict) or document.get("contract") != READINESS_CONTRACT:
        raise DevelopmentCycleError("The previous readiness manifest contract is invalid.")
    if document.get("evidence_scope") != "last-successful-preparation-readiness":
        raise DevelopmentCycleError("The previous readiness evidence scope is invalid.")
    if not isinstance(document.get("recorded_at"), str):
        raise DevelopmentCycleError("The previous readiness manifest timestamp is invalid.")
    for section in (
        "source",
        "platform",
        "locks",
        "toolchain",
        "environment",
        "topology",
        "database",
        "capabilities",
        "health",
    ):
        if not isinstance(document.get(section), dict):
            raise DevelopmentCycleError(f"The previous readiness {section} evidence is invalid.")
    source = document.get("source")
    if not isinstance(source, dict):
        raise DevelopmentCycleError("The previous readiness source binding is invalid.")
    commit = source.get("commit")
    if (
        not isinstance(commit, str)
        or source.get("origin_dev_commit") != commit
        or source.get("branch") != DEV_BRANCH
        or source.get("origin_repository") != f"{EXPECTED_GITHUB_HOST}/{EXPECTED_GITHUB_PATH}"
    ):
        raise DevelopmentCycleError("The previous readiness source binding is invalid.")
    return cast(dict[str, object], document)


def manifest_source_commit(manifest: Mapping[str, object]) -> str:
    source = manifest.get("source")
    if not isinstance(source, dict):
        raise DevelopmentCycleError("The readiness source binding is invalid.")
    commit = source.get("commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise DevelopmentCycleError("The readiness source commit is invalid.")
    return commit


def validate_previous_readiness(
    runner: Runner,
    current_source_commit: str,
    path: Path = READINESS_MANIFEST,
) -> None:
    manifest = load_readiness_manifest(path)
    if manifest is None:
        return
    previous_commit = manifest_source_commit(manifest)
    runner.run(("git", "merge-base", "--is-ancestor", previous_commit, current_source_commit))


def readiness_payload(manifest: Mapping[str, object]) -> dict[str, object]:
    return {key: value for key, value in manifest.items() if key != "recorded_at"}


def verify_readiness_manifest(
    evidence: Mapping[str, object],
    path: Path = READINESS_MANIFEST,
) -> None:
    manifest = load_readiness_manifest(path)
    if manifest is None:
        raise DevelopmentCycleError(
            "The readiness manifest is missing. Run prep-update successfully first."
        )
    if readiness_payload(manifest) != dict(evidence):
        raise DevelopmentCycleError(
            "The current source/runtime evidence differs from the last successful prep-update."
        )


def write_readiness_manifest(
    evidence: Mapping[str, object],
    path: Path = READINESS_MANIFEST,
) -> None:
    """Atomically replace only the last fully successful readiness evidence."""

    parent = path.parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent.chmod(0o700)
    document = dict(evidence)
    document["recorded_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    content = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def prep_update(runner: Runner, selected_env: Path) -> None:
    require_platform(expected_system="Linux", expected_machines={"amd64", "x86_64"})
    require_command("git")
    require_command("docker")
    require_dev_checkout(runner)
    require_expected_origin(runner)
    if not selected_env.is_file():
        raise DevelopmentCycleError(f"Canonical preparation environment is missing: {selected_env}")
    older = current_commit(runner)
    validate_previous_readiness(runner, older)
    runner.note("Ever-Real origin/dev fetch 및 fast-forward 적용")
    runner.run(("git", "fetch", "--prune", "origin", "dev"))
    remote_commit = git_output(runner, "rev-parse", "--verify", "origin/dev")
    runner.run(("git", "merge-base", "--is-ancestor", older, remote_commit))
    runner.run(("git", "merge", "--ff-only", "origin/dev"))
    newer = current_commit(runner)
    verify_remote_dev(runner, newer)
    sync_changed_dependencies(runner, changed_paths(runner, older, newer))
    runtime = prepare_source_host(runner, selected_env)
    runner.note("성공한 amd64 source/runtime readiness 증적 원자 기록")
    evidence = build_readiness_evidence(
        runner,
        selected_env=selected_env,
        source_commit=newer,
        origin_commit=newer,
        runtime=runtime,
    )
    write_readiness_manifest(evidence)
    print(f"PREPARATION_UPDATED={newer}", flush=True)


def prep_check(runner: Runner, selected_env: Path) -> None:
    require_platform(expected_system="Linux", expected_machines={"amd64", "x86_64"})
    require_dev_checkout(runner)
    require_expected_origin(runner)
    if not selected_env.is_file():
        raise DevelopmentCycleError(f"Canonical preparation environment is missing: {selected_env}")
    commit = current_commit(runner)
    origin_commit = git_output(runner, "rev-parse", "--verify", "origin/dev")
    runner.note("현재 source-host Settings와 process 상태 확인")
    capabilities = capture_source_host_preflight(runner, selected_env)
    runner.run(source_host_arguments("status", selected_env))
    health = verify_source_host_health(runner, read_env_values(selected_env))
    runner.note("현재 상태와 마지막 성공 readiness manifest 일치 확인")
    evidence = build_readiness_evidence(
        runner,
        selected_env=selected_env,
        source_commit=commit,
        origin_commit=origin_commit,
        runtime={"capabilities": capabilities, "health": health},
    )
    verify_readiness_manifest(evidence)


def main() -> int:
    arguments = parse_arguments()
    runner = Runner()
    try:
        reconciliation = validate_local_topology_reconciliation(
            arguments.action,
            arguments.reconcile_local_topology,
        )
        if arguments.action == "verify":
            verify_source(runner)
        elif arguments.action == "dev-publish":
            dev_publish(runner, reconciliation=reconciliation)
        elif arguments.action == "prep-update":
            prep_update(runner, env_path(arguments.env_file))
        else:
            prep_check(runner, env_path(arguments.env_file))
        return 0
    except (DevelopmentCycleError, OSError, ValueError, WorkflowError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
