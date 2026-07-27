#!/usr/bin/env python3
"""Stable development and preparation-PC update entry points."""

from __future__ import annotations

import argparse
import os
import platform
import shlex
import shutil
import subprocess
import sys
import time
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from urllib.parse import urlsplit

from platform_workflow import WorkflowError, read_env_values

ROOT = Path(__file__).resolve().parents[1]
DEV_BRANCH = "dev"
EXPECTED_GITHUB_HOST = "github.com"
EXPECTED_GITHUB_PATH = "Ever-Real/datariver_v1"
DEFAULT_PREPARATION_ENV = Path(".env.wsl-intranet-development")

RUFF_FORMAT_PATHS = (
    "backend/src",
    "backend/tests",
    "infra/airflow/dags",
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
            if capture_output:
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
    ) -> str:
        return self.run(arguments, cwd=cwd, capture_output=True).stdout.strip()


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
    return parser.parse_args()


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


def dev_publish(runner: Runner) -> None:
    require_platform(expected_system="Darwin", expected_machines={"arm64", "aarch64"})
    require_command("git")
    require_command("npm")
    require_dev_checkout(runner)
    require_expected_origin(runner)
    commit = current_commit(runner)
    runner.note("현재 dev commit 전체 소스 검증")
    verify_source(runner)
    runner.note("검증한 commit을 Mac 개발 runtime에 적용")
    runner.run(
        (
            ROOT / "scripts" / "workflow_update_restart.py",
            "--profile",
            "mac-development",
            "--refresh-bootstrap",
            "--assume-yes",
        )
    )
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


def prepare_source_host(runner: Runner, selected_env: Path) -> None:
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
    runner.run(source_host_arguments("preflight", selected_env))
    runner.run(source_host_arguments("start", selected_env))
    runner.run(source_host_arguments("status", selected_env))
    verify_source_host_health(runner, read_env_values(selected_env))


def probe_url(url: str, *, attempts: int = 20) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    last_error: Exception | None = None
    for _attempt in range(attempts):
        try:
            with opener.open(url, timeout=5) as response:
                response.read(512)
            if 200 <= response.status < 400:
                print(f"     {url} -> HTTP {response.status}", flush=True)
                return
            last_error = DevelopmentCycleError(f"Unexpected HTTP status {response.status}")
        except Exception as error:
            last_error = error
        time.sleep(1)
    raise DevelopmentCycleError(f"Health probe failed for {url}: {last_error}")


def verify_source_host_health(
    runner: Runner,
    values: Mapping[str, str],
) -> None:
    api_port = require_env_value(values, "API_PORT")
    web_port = require_env_value(values, "WEB_PORT")
    keycloak_port = require_env_value(values, "KEYCLOAK_PORT")
    if not all(
        value.isdigit() and 1 <= int(value) <= 65535
        for value in (api_port, web_port, keycloak_port)
    ):
        raise DevelopmentCycleError("API_PORT, WEB_PORT and KEYCLOAK_PORT must be valid ports.")
    runner.note("API, Web 및 loopback OIDC health 검증")
    probe_url(f"http://127.0.0.1:{api_port}/api/v1/health/ready")
    probe_url(f"http://127.0.0.1:{web_port}/")
    probe_url(f"http://127.0.0.1:{keycloak_port}/realms/datariver/.well-known/openid-configuration")


def prep_update(runner: Runner, selected_env: Path) -> None:
    require_platform(expected_system="Linux", expected_machines={"amd64", "x86_64"})
    require_command("git")
    require_command("docker")
    require_dev_checkout(runner)
    require_expected_origin(runner)
    if not selected_env.is_file():
        raise DevelopmentCycleError(f"Canonical preparation environment is missing: {selected_env}")
    older = current_commit(runner)
    runner.note("Ever-Real origin/dev fetch 및 fast-forward 적용")
    runner.run(("git", "fetch", "--prune", "origin", "dev"))
    remote_commit = git_output(runner, "rev-parse", "--verify", "origin/dev")
    runner.run(("git", "merge-base", "--is-ancestor", older, remote_commit))
    runner.run(("git", "merge", "--ff-only", "origin/dev"))
    newer = current_commit(runner)
    verify_remote_dev(runner, newer)
    sync_changed_dependencies(runner, changed_paths(runner, older, newer))
    prepare_source_host(runner, selected_env)
    print(f"PREPARATION_UPDATED={newer}", flush=True)


def prep_check(runner: Runner, selected_env: Path) -> None:
    require_platform(expected_system="Linux", expected_machines={"amd64", "x86_64"})
    require_dev_checkout(runner)
    require_expected_origin(runner)
    if not selected_env.is_file():
        raise DevelopmentCycleError(f"Canonical preparation environment is missing: {selected_env}")
    runner.note("현재 source-host Settings와 process 상태 확인")
    runner.run(source_host_arguments("preflight", selected_env))
    runner.run(source_host_arguments("status", selected_env))
    verify_source_host_health(runner, read_env_values(selected_env))


def main() -> int:
    arguments = parse_arguments()
    runner = Runner()
    try:
        if arguments.action == "verify":
            verify_source(runner)
        elif arguments.action == "dev-publish":
            dev_publish(runner)
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
