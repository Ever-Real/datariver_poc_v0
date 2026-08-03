#!/usr/bin/env python3
"""Apply one Git update and restart only affected DataRiver services."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path

from docker_capacity import (
    DockerCapacityError,
    DockerWorkflowLock,
    exclusive_docker_workflow_lock,
    governed_compose_build_capacity,
    require_no_active_builds,
)
from platform_workflow import (
    AIRFLOW_SERVICES,
    ROOT,
    WORKFLOW_PROFILE_NAMES,
    AppliedState,
    ChangePlan,
    Runner,
    TopologyReconciliationPlan,
    TopologyReconciliationSecretGuard,
    WorkflowError,
    build_local_topology_audit,
    build_topology_reconciliation_plan,
    capture_local_topology,
    changed_environment_keys,
    classify_changes,
    classify_environment_changes,
    compose_arguments,
    current_commit,
    enforce_local_topology,
    environment_key_hashes,
    load_applied_state,
    merge_change_plans,
    merge_no_proxy,
    prompt_confirm,
    read_env_values,
    release_layout,
    release_optional_compose,
    require_clean_worktree,
    require_command,
    require_regular_file,
    require_release_compatible_checkout,
    require_topology_reconciliation_secrets,
    requires_local_identity_bootstrap,
    select_restart_services,
    state_path,
    update_env_values,
    workflow_profile,
    write_applied_state,
)

DATAHUB_PROBE_PROGRAM = """\
import json
import os
import urllib.request
from pathlib import Path

base_url = os.environ["DATAHUB_BASE_URL"].rstrip("/")
token = Path("/run/secrets/datahub_token").read_text(encoding="utf-8").strip()
request = urllib.request.Request(
    base_url + "/config",
    headers={"Authorization": "Bearer " + token},
)
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with opener.open(request, timeout=15) as response:
    document = json.load(response)
version = (
    document.get("versions", {})
    .get("acryldata/datahub", {})
    .get("version", "unknown")
)
print(f"DataHub GMS HTTP 200, version={version}")
"""

CATALOG_SYNC_PROGRAM = """\
import json
from datetime import UTC, datetime
from datariver_catalog_sync import synchronize_catalog_projection

run_id = "operator__update_" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
result = synchronize_catalog_projection(run_id=run_id)
print(json.dumps(result, ensure_ascii=False, indent=2))
"""

HEALTH_PROGRAM = """\
import sys
import urllib.request

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for url in sys.argv[1:]:
    with opener.open(url, timeout=10) as response:
        body = response.read(512).decode("utf-8", errors="replace").strip()
    print(f"{url} -> HTTP {response.status} {body}")
"""

GATEWAY_TRANSPARENCY_PROGRAM = """\
import sys
import urllib.error
import urllib.request

direct, gateway, web, origin = sys.argv[1:]
selected_headers = (
    "WWW-Authenticate",
    "Set-Cookie",
    "Access-Control-Allow-Origin",
    "Access-Control-Allow-Methods",
    "Access-Control-Allow-Headers",
    "Cache-Control",
    "Content-Type",
    "X-Request-Id",
)

def fail():
    raise SystemExit("GATEWAY_TRANSPARENCY_FAILED")

def request(base, path, *, method="GET", headers=None, data=None):
    selected = dict(headers or {})
    selected["X-Request-Id"] = "gateway-transparency-probe"
    value = urllib.request.Request(base + path, method=method, headers=selected, data=data)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        response = opener.open(value, timeout=10)
    except urllib.error.HTTPError as error:
        response = error
    except (OSError, ValueError, urllib.error.URLError):
        fail()
    header_evidence = tuple(
        (name.casefold(), tuple(response.headers.get_all(name, [])))
        for name in selected_headers
    )
    return response.status, header_evidence

paths = ("/api/v1/knowledge/registry/assets", "/api/v1/change-requests")
for path in paths:
    for headers in (
        {},
        {
            "Authorization": "Bearer gateway-invalid-token-sentinel",
            "Cookie": "session=gateway-cookie-sentinel",
            "Origin": origin,
            "X-Gateway-Probe-Code": "gateway-code-sentinel",
            "X-Gateway-Probe-Secret": "gateway-secret-sentinel",
        },
    ):
        evidence = tuple(request(base, path, headers=headers) for base in (direct, gateway, web))
        if any(status != 401 for status, _ in evidence) or len(set(evidence)) != 1:
            fail()

body_evidence = tuple(
    request(
        base,
        paths[1],
        method="POST",
        headers={
            "Authorization": "Bearer gateway-invalid-token-sentinel",
            "Content-Type": "application/json",
        },
        data=b'{"probe":"gateway-body-secret-sentinel"}',
    )
    for base in (direct, gateway, web)
)
if any(status != 401 for status, _ in body_evidence) or len(set(body_evidence)) != 1:
    fail()

preflight_headers = {
    "Origin": origin,
    "Access-Control-Request-Method": "GET",
    "Access-Control-Request-Headers": "authorization,x-request-id",
}
preflight = tuple(
    request(base, paths[0], method="OPTIONS", headers=preflight_headers)
    for base in (direct, gateway, web)
)
if len(set(preflight)) != 1 or preflight[0][0] not in (200, 204):
    fail()
print("GATEWAY_TRANSPARENCY_OK")
"""

_POSTGRES_SECRET_MOUNT_ENV_KEYS = frozenset(
    {
        "KNOWLEDGE_PROPOSAL_DATABASE_SECRET_REF",
    }
)
_DOCKER_DAEMON_PROBE = (
    "docker",
    "version",
    "--format",
    "{{.Server.Version}}",
)
_DOCKER_DAEMON_UNAVAILABLE = "DOCKER_DAEMON_UNAVAILABLE"
_COMPOSE_RUNNING_SERVICES_QUERY_FAILED = "COMPOSE_RUNNING_SERVICES_QUERY_FAILED"
_TOPOLOGY_RECONCILIATION = "mac-development-graph-gateway-v1"
_GATEWAY_AUTH_PARITY_EVIDENCE_UNAVAILABLE = "GATEWAY_AUTH_PARITY_EVIDENCE_UNAVAILABLE"
_GOVERNANCE_DOCUMENT_ROLE_QUERY = """\
password="$(tr -d '\\r\\n' </run/secrets/postgres_governance_document_password)"
export PGPASSWORD="$password"
exec psql --no-psqlrc --tuples-only --no-align --set ON_ERROR_STOP=1 \
  --username datariver_governance_document --dbname "$POSTGRES_DB" \
  --command 'SELECT current_user;'
"""
_GOVERNANCE_DOCUMENT_BACKLOG_QUERY = """\
password="$(tr -d '\\r\\n' </run/secrets/postgres_governance_document_password)"
export PGPASSWORD="$password"
exec psql --no-psqlrc --tuples-only --no-align --set ON_ERROR_STOP=1 \
  --username datariver_governance_document --dbname "$POSTGRES_DB" \
  --command "SELECT count(*)
    FROM governance.document_versions
    WHERE state = 'PUBLISHED'
      AND knowledge_state IN ('PENDING','FAILED')
      AND next_attempt_at <= clock_timestamp()
      AND (lease_until IS NULL OR lease_until <= clock_timestamp());"
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Optionally pull one fast-forward Git update, validate its runtime artifact, "
            "run migrations when needed, and recreate only affected services."
        )
    )
    parser.add_argument(
        "--profile",
        choices=WORKFLOW_PROFILE_NAMES,
        required=True,
    )
    parser.add_argument("--env-file", type=Path)
    parser.add_argument(
        "--release-dir",
        type=Path,
        help="New or retained immutable amd64 release directory for WSL.",
    )
    parser.add_argument(
        "--git-pull",
        action="store_true",
        help="Run git pull --ff-only before calculating the update.",
    )
    parser.add_argument(
        "--reload-release",
        action="store_true",
        help="Re-verify and reload the offline Core archive even if its commit is unchanged.",
    )
    parser.add_argument(
        "--refresh-bootstrap",
        action="store_true",
        help="Reapply bootstrap before Compose validation; existing secrets are preserved.",
    )
    parser.add_argument("--skip-catalog-sync", action="store_true")
    parser.add_argument("--assume-yes", action="store_true")
    parser.add_argument(
        "--reconcile-local-topology",
        choices=(_TOPOLOGY_RECONCILIATION,),
        help="Apply the sole reviewed Mac-development graph/gateway adoption.",
    )
    return parser.parse_args()


def _resolve_repo_path(value: str | Path) -> Path:
    candidate = Path(value).expanduser()
    return candidate.resolve() if candidate.is_absolute() else (ROOT / candidate).resolve()


def _compose_files(state: AppliedState, *, release_override: Path | None) -> tuple[Path, ...]:
    files: tuple[Path, ...] = (ROOT / "compose.yaml", ROOT / "compose.identity.yaml")
    if state.local_gateway:
        files = (
            *files,
            ROOT / "compose.gateway.yaml",
            ROOT / "compose.gateway-routing.yaml",
        )
    if state.deployment_mode == "build":
        return files
    release_dir = release_override or (
        Path(state.release_dir) if state.release_dir is not None else None
    )
    if release_dir is None:
        raise WorkflowError("The offline state has no release directory.")
    layout = release_layout(release_dir, architecture="amd64")
    return (*files, layout.offline_compose)


def _airflow_compose_files(
    files: tuple[Path, ...],
    *,
    local_gateway: bool,
) -> tuple[Path, ...]:
    selected = (*files, ROOT / "compose.airflow.yaml")
    if local_gateway:
        selected = (*selected, ROOT / "compose.airflow.host-dev.yaml")
    return tuple(dict.fromkeys(selected))


def _private_compose_output(
    *,
    env_file: Path,
    files: tuple[Path, ...],
    trailing: tuple[str, ...],
    classification: str,
) -> str:
    command = [
        os.fspath(argument)
        for argument in compose_arguments(
            env_file=env_file,
            compose_files=files,
            trailing=trailing,
        )
    ]
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, never a shell on the host.
            command,
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
            timeout=20,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise WorkflowError(classification) from None
    output = result.stdout.strip()
    if len(output.encode("utf-8")) > 256 or "\n" in output or "\r" in output:
        raise WorkflowError(classification)
    return output


def _verify_governance_document_worker_database(
    runner: Runner,
    *,
    env_file: Path,
    files: tuple[Path, ...],
) -> None:
    role = _private_compose_output(
        env_file=env_file,
        files=files,
        trailing=(
            "exec",
            "-T",
            "postgres",
            "sh",
            "-ec",
            _GOVERNANCE_DOCUMENT_ROLE_QUERY,
        ),
        classification="GOVERNANCE_DOCUMENT_DATABASE_ROLE_INVALID",
    )
    if role != "datariver_governance_document":
        raise WorkflowError("GOVERNANCE_DOCUMENT_DATABASE_ROLE_INVALID")
    raw_backlog = _private_compose_output(
        env_file=env_file,
        files=files,
        trailing=(
            "exec",
            "-T",
            "postgres",
            "sh",
            "-ec",
            _GOVERNANCE_DOCUMENT_BACKLOG_QUERY,
        ),
        classification="GOVERNANCE_DOCUMENT_BACKLOG_INVALID",
    )
    if not raw_backlog.isascii() or not raw_backlog.isdecimal():
        raise WorkflowError("GOVERNANCE_DOCUMENT_BACKLOG_INVALID")
    backlog = int(raw_backlog)
    if backlog > 1_000_000_000:
        raise WorkflowError("GOVERNANCE_DOCUMENT_BACKLOG_INVALID")
    runner.note(f"Governance document worker database role/backlog verified count={backlog}")


def _verify_gateway_logs_do_not_persist_probe_credentials(
    *,
    env_file: Path,
    files: tuple[Path, ...],
) -> None:
    command = [
        os.fspath(argument)
        for argument in compose_arguments(
            env_file=env_file,
            compose_files=files,
            trailing=(
                "logs",
                "--no-color",
                "--since",
                "2m",
                "--tail",
                "200",
                "apisix",
                "web",
            ),
        )
    ]
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, never a shell on the host.
            command,
            cwd=ROOT,
            check=True,
            capture_output=True,
            timeout=20,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise WorkflowError("GATEWAY_CREDENTIAL_LOG_PROBE_FAILED") from None
    combined = result.stdout + result.stderr
    if len(combined) > 256 * 1024:
        raise WorkflowError("GATEWAY_CREDENTIAL_LOG_PROBE_FAILED")
    for sentinel in (
        b"gateway-invalid-token-sentinel",
        b"gateway-cookie-sentinel",
        b"gateway-code-sentinel",
        b"gateway-secret-sentinel",
        b"gateway-body-secret-sentinel",
    ):
        if sentinel in combined:
            raise WorkflowError("GATEWAY_CREDENTIAL_LOG_PROBE_FAILED")


def _verify_gateway_transparency(
    runner: Runner,
    *,
    env_file: Path,
    files: tuple[Path, ...],
) -> None:
    values = read_env_values(env_file)
    api_port = values.get("API_PORT", "8000")
    gateway_port = values.get("APISIX_PORT", "9080")
    web_port = values.get("WEB_PORT", "8080")
    origin = values.get("APP_PUBLIC_ORIGIN", f"http://127.0.0.1:{web_port}")
    runner.run(
        (
            sys.executable,
            "-",
            f"http://127.0.0.1:{api_port}",
            f"http://127.0.0.1:{gateway_port}",
            f"http://127.0.0.1:{web_port}",
            origin,
        ),
        input_text=GATEWAY_TRANSPARENCY_PROGRAM,
    )
    _verify_gateway_logs_do_not_persist_probe_credentials(
        env_file=env_file,
        files=files,
    )
    # The checked-in development identities cannot currently provide the full live
    # authorized/denied/expired/revoked matrix without provisioning credentials or
    # mutating policy/session state. A static status echo is not adoption evidence.
    raise WorkflowError(_GATEWAY_AUTH_PARITY_EVIDENCE_UNAVAILABLE)


def _require_gateway_auth_parity_evidence_available(reconciliation_name: str | None) -> None:
    """Stop the optional topology transaction before mutation until its live plan exists."""

    if reconciliation_name is not None:
        raise WorkflowError(_GATEWAY_AUTH_PARITY_EVIDENCE_UNAVAILABLE)


def _prepare_topology_reconciliation(
    runner: Runner,
    *,
    state: AppliedState,
    environment_values: dict[str, str],
    reconciliation: str,
) -> TopologyReconciliationPlan:
    audit = build_local_topology_audit(
        state=state,
        environment_values=environment_values,
        observations=capture_local_topology(runner),
    )
    runner.note(f"Local topology reconciliation preflight {audit.summary()}")
    return build_topology_reconciliation_plan(
        reconciliation,
        state=state,
        environment_values=environment_values,
        audit=audit,
    )


def _apply_topology_reconciliation(
    runner: Runner,
    *,
    env_file: Path,
    files: tuple[Path, ...],
    plan: TopologyReconciliationPlan,
    selected_builder: str | None,
    capacity_lock: DockerWorkflowLock | None,
    secret_guard: TopologyReconciliationSecretGuard,
) -> None:
    runner.note("누락된 governance document worker만 복구합니다.")
    secret_guard.revalidate()
    try:
        _compose(
            runner,
            env_file=env_file,
            files=files,
            profiles=("governance-documents",),
            trailing=(
                "up",
                "-d",
                "--wait",
                "--no-deps",
                "--no-build",
                plan.missing_worker_service,
            ),
        )
    finally:
        secret_guard.revalidate()
    _verify_governance_document_worker_database(
        runner,
        env_file=env_file,
        files=files,
    )

    _require_idle_builder(selected_builder, capacity_lock)
    gateway_files = tuple(dict.fromkeys((*files, ROOT / "compose.gateway.yaml")))
    runner.note("검증된 APISIX image만 빌드하고 기존 gateway를 재생성합니다.")
    _compose(
        runner,
        env_file=env_file,
        files=gateway_files,
        trailing=("build", "apisix"),
    )
    _compose(
        runner,
        env_file=env_file,
        files=gateway_files,
        trailing=(
            "up",
            "-d",
            "--wait",
            "--no-deps",
            "--force-recreate",
            "--no-build",
            "apisix",
        ),
    )

    runner.note("Web의 내부 API upstream을 APISIX로 고정해 재생성합니다.")
    _compose(
        runner,
        env_file=env_file,
        files=files,
        trailing=(
            "up",
            "-d",
            "--wait",
            "--no-deps",
            "--force-recreate",
            "--no-build",
            "web",
        ),
    )
    if plan.target_state.local_airflow:
        airflow_files = _airflow_compose_files(
            files,
            local_gateway=True,
        )
        runner.note("선택된 Airflow API 호출만 동일 Bearer로 APISIX를 경유시킵니다.")
        _compose(
            runner,
            env_file=env_file,
            files=airflow_files,
            trailing=(
                "up",
                "-d",
                "--wait",
                "--no-deps",
                "--force-recreate",
                "--no-build",
                *AIRFLOW_SERVICES,
            ),
        )


def _compose(
    runner: Runner,
    *,
    env_file: Path,
    files: tuple[Path, ...],
    trailing: tuple[str, ...],
    profiles: tuple[str, ...] = (),
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> None:
    runner.run(
        compose_arguments(
            env_file=env_file,
            compose_files=files,
            profiles=profiles,
            trailing=trailing,
        ),
        env=env,
        input_text=input_text,
    )


def _preflight_build_capacity(
    runner: Runner,
    *,
    env_file: Path,
    files: tuple[Path, ...],
    selected_build_services: tuple[str, ...],
    lock: DockerWorkflowLock,
) -> str:
    evidence = governed_compose_build_capacity(
        root=ROOT,
        compose_config_command=compose_arguments(
            env_file=env_file,
            compose_files=files,
            profiles=("*",),
            trailing=("config", "--format", "json"),
        ),
        docker_filesystem_probe_command=compose_arguments(
            env_file=env_file,
            compose_files=files,
            trailing=("exec", "-T", "postgres", "df", "-Pk", "/"),
        ),
        selected_build_services=selected_build_services,
        environ=os.environ,
        lock=lock,
    )
    runner.note(evidence.summary())
    return evidence.builder


def _require_idle_builder(
    builder: str | None,
    lock: DockerWorkflowLock | None,
) -> None:
    if builder is None or lock is None:
        raise DockerCapacityError("DOCKER_BUILD_CAPACITY_EVIDENCE_MISSING")
    require_no_active_builds(builder=builder, lock=lock)


def _git_paths(runner: Runner, older: str, newer: str) -> tuple[str, ...]:
    if older == newer:
        return ()
    try:
        runner.run(("git", "merge-base", "--is-ancestor", older, newer))
    except WorkflowError as error:
        raise WorkflowError(
            "The previously applied commit is not an ancestor of the current checkout. "
            "Use a reviewed rollback procedure instead of this forward-update workflow."
        ) from error
    return tuple(
        line
        for line in runner.output(("git", "diff", "--name-only", f"{older}..{newer}")).splitlines()
        if line
    )


def _running_services(
    runner: Runner,
    *,
    env_file: Path,
    files: tuple[Path, ...],
) -> tuple[str, ...]:
    arguments = compose_arguments(
        env_file=env_file,
        compose_files=files,
        trailing=("ps", "--services", "--filter", "status=running"),
    )
    try:
        output = runner.output(arguments)
    except WorkflowError:
        try:
            runner.output(_DOCKER_DAEMON_PROBE)
        except WorkflowError as error:
            raise WorkflowError(
                "The Compose running-service query stopped "
                f"(classification={_DOCKER_DAEMON_UNAVAILABLE})."
            ) from error
        runner.note("Docker daemon probe 통과 후 실행 서비스 조회를 1회 재시도합니다.")
        try:
            output = runner.output(arguments)
        except WorkflowError as error:
            raise WorkflowError(
                "The Compose running-service query stopped after one bounded retry "
                f"(classification={_COMPOSE_RUNNING_SERVICES_QUERY_FAILED})."
            ) from error
    return tuple(line.strip() for line in output.splitlines() if line.strip())


def _verify_and_load_release(runner: Runner, *, release_dir: Path) -> None:
    layout = release_layout(release_dir, architecture="amd64")
    runner.note("오프라인 release의 source/checksum/manifest/platform을 검증·로드합니다.")
    runner.run(
        (
            ROOT / "scripts" / "verify_offline_release.sh",
            layout.root,
            "--platform",
            "linux/amd64",
            "--load",
        )
    )


def _bootstrap(runner: Runner, *, state: AppliedState, env_file: Path) -> None:
    values = read_env_values(env_file)
    datahub_base_url = values.get("DATAHUB_BASE_URL")
    if not datahub_base_url:
        raise WorkflowError("DATAHUB_BASE_URL is missing from the selected environment file.")
    preserved = {
        key: value
        for key, value in values.items()
        if key.startswith(
            (
                "REDIS_",
                "S3_",
                "UI_",
                "INTRANET_OPENAI_",
                "LOCAL_OLLAMA_",
                "LOCAL_LLAMA_CPP_",
                "NEO4J_",
            )
        )
        or key in {"NO_PROXY", "OIDC_HARDWARE_WEBAUTHN_ENABLED"}
    }
    runner.run(
        (
            ROOT / "scripts" / "bootstrap.sh",
            "--env-file",
            env_file,
            f"--{state.profile}",
            "--datahub-base-url",
            datahub_base_url,
        )
    )
    update_env_values(env_file, preserved)


def _reconcile_postgres(runner: Runner, *, env_file: Path) -> None:
    _compose(
        runner,
        env_file=env_file,
        files=(ROOT / "compose.yaml",),
        trailing=(
            "exec",
            "-T",
            "postgres",
            "sh",
            "-ec",
            'export PGPASSWORD="$(tr -d "\\r\\n" </run/secrets/postgres_password)"; '
            "exec sh /docker-entrypoint-initdb.d/010_roles.sh",
        ),
    )


def _enabled_optional_runtime_services(values: dict[str, str]) -> tuple[str, ...]:
    services: list[str] = []
    if values.get("KNOWLEDGE_STUDIO_PROPOSAL_WORKER_ENABLED", "").lower() == "true":
        services.append("knowledge-tbox-proposal-worker")
    return tuple(services)


def _requires_postgres_secret_remount(environment_keys: tuple[str, ...]) -> bool:
    return bool(_POSTGRES_SECRET_MOUNT_ENV_KEYS.intersection(environment_keys))


def _health_check(runner: Runner, *, env_file: Path) -> None:
    values = read_env_values(env_file)
    api_port = values.get("API_PORT", "8000")
    web_port = values.get("WEB_PORT", "8080")
    runner.run(
        (
            sys.executable,
            "-",
            f"http://127.0.0.1:{api_port}/api/v1/health/live",
            f"http://127.0.0.1:{api_port}/api/v1/health/ready",
            f"http://127.0.0.1:{web_port}/healthz",
        ),
        input_text=HEALTH_PROGRAM,
    )


def _reconcile_local_reranker(runner: Runner, *, env_file: Path, profile: str) -> None:
    values = read_env_values(env_file)
    enabled = values.get("LOCAL_LLAMA_CPP_RERANKER_ENABLED", "").lower() == "true"
    manager = ROOT / "scripts" / "local_reranker_service.py"
    if not workflow_profile(profile).local_reranker_supported or not enabled:
        runner.note("비활성 로컬 llama.cpp reranker의 소유 프로세스를 정리합니다.")
        runner.run((sys.executable, manager, "stop"))
        return
    model = values.get("LOCAL_LLAMA_CPP_RERANKER_MODEL")
    if not model:
        raise WorkflowError("LOCAL_LLAMA_CPP_RERANKER_MODEL is required when enabled.")
    runner.note("Ollama GGUF 기반 로컬 llama.cpp reranker를 검증·시작합니다.")
    runner.run(
        (
            sys.executable,
            manager,
            "start",
            "--model",
            model,
        )
    )


def _probe_datahub(
    runner: Runner,
    *,
    env_file: Path,
    files: tuple[Path, ...],
) -> None:
    _compose(
        runner,
        env_file=env_file,
        files=files,
        trailing=("exec", "-T", "api", "/app/.venv/bin/python", "-"),
        input_text=DATAHUB_PROBE_PROGRAM,
    )


def _sync_catalog(runner: Runner, *, env_file: Path) -> None:
    values = read_env_values(env_file)
    api_port = values.get("API_PORT", "8000")
    keycloak_port = values.get("KEYCLOAK_PORT", "8081")
    environment = os.environ.copy()
    environment.update(
        {
            "DATARIVER_API_BASE_URL": f"http://127.0.0.1:{api_port}",
            "DATARIVER_WORKSPACE_ID": "00000000-0000-4000-8000-000000000100",
            "DATARIVER_OIDC_TOKEN_URL": (
                f"http://127.0.0.1:{keycloak_port}/realms/datariver/protocol/openid-connect/token"
            ),
            "DATARIVER_OIDC_CLIENT_ID": "datariver-airflow",
            "DATARIVER_OIDC_CLIENT_SECRET_FILE": os.fspath(
                ROOT / "secrets" / "airflow_client_secret"
            ),
            "DATARIVER_CATALOG_SYNC_MAX_PAGES": values.get(
                "DATARIVER_CATALOG_SYNC_MAX_PAGES", "10002"
            ),
            "NO_PROXY": merge_no_proxy(
                os.environ.get("NO_PROXY", ""),
                ("127.0.0.1", "localhost"),
            ),
            "PYTHONPATH": os.fspath(ROOT / "infra" / "airflow" / "dags"),
        }
    )
    environment["no_proxy"] = environment["NO_PROXY"]
    runner.run((sys.executable, "-"), env=environment, input_text=CATALOG_SYNC_PROGRAM)


def _reconcile_local_admin_catalog_access(
    runner: Runner,
    *,
    env_file: Path,
    files: tuple[Path, ...],
) -> None:
    _compose(
        runner,
        env_file=env_file,
        files=files,
        trailing=(
            "--profile",
            "tools",
            "run",
            "--rm",
            "--no-deps",
            "--build",
            "local-bootstrap",
            "/app/.venv/bin/python",
            "-m",
            "datariver.local_admin_catalog_access",
        ),
    )


def _print_plan(
    *,
    previous_commit: str,
    current_source_commit: str,
    runtime_commit: str,
    paths: tuple[str, ...],
    environment_keys: tuple[str, ...],
    plan: ChangePlan,
    restart_services: tuple[str, ...],
) -> None:
    print("Update plan", flush=True)
    print(f"  source:  {previous_commit[:12]} -> {current_source_commit[:12]}", flush=True)
    print(f"  runtime: {runtime_commit[:12]}", flush=True)
    print(f"  changed paths: {len(paths)}", flush=True)
    for path in paths:
        print(f"    - {path}", flush=True)
    print(f"  changed environment keys: {len(environment_keys)}", flush=True)
    for key in environment_keys:
        print(f"    - {key}", flush=True)
    print(
        "  restart services: " + (", ".join(restart_services) if restart_services else "none"),
        flush=True,
    )
    print(f"  migration: {'yes' if plan.requires_migration else 'no'}", flush=True)
    print(f"  DataHub: {'restart' if plan.restart_datahub else 'unchanged'}", flush=True)
    print(f"  Airflow: {'restart' if plan.restart_airflow else 'unchanged'}", flush=True)
    print(f"  APISIX: {'restart' if plan.restart_gateway else 'unchanged'}", flush=True)
    print(f"  Neo4j: {'restart' if plan.restart_graph else 'unchanged'}", flush=True)


def main() -> int:
    args = parse_args()
    reconciliation_name = getattr(args, "reconcile_local_topology", None)
    runner = Runner()
    mutation_stack = ExitStack()
    try:
        for command in ("docker", "git"):
            require_command(command)
        state_file = state_path(ROOT, args.profile)
        state = load_applied_state(state_file)
        if state.profile != args.profile:
            raise WorkflowError("The requested profile does not match its applied state.")
        capacity_lock: DockerWorkflowLock | None = None
        if reconciliation_name is not None:
            capacity_lock = mutation_stack.enter_context(exclusive_docker_workflow_lock(ROOT))
            _require_gateway_auth_parity_evidence_available(reconciliation_name)
        if args.git_pull:
            require_clean_worktree(runner)
            runner.note("현재 branch를 fast-forward 방식으로 pull합니다.")
            runner.run(("git", "pull", "--ff-only"))
        require_clean_worktree(runner)

        current_source_commit = current_commit(runner)
        env_file = (
            args.env_file.expanduser().resolve()
            if args.env_file is not None
            else _resolve_repo_path(state.env_file)
        )
        require_regular_file(env_file, label="Environment file")

        source_paths = _git_paths(runner, state.applied_commit, current_source_commit)
        runtime_commit = current_source_commit
        release_dir: Path | None = None
        offline_layout = None
        runtime_paths: tuple[str, ...] = ()
        if state.deployment_mode == "offline":
            require_command("sha256sum")
            selected_release = args.release_dir or (
                Path(state.release_dir) if state.release_dir is not None else None
            )
            if selected_release is None:
                raise WorkflowError("The offline update requires --release-dir.")
            release_dir = selected_release.expanduser().resolve()
            layout = release_layout(release_dir, architecture="amd64")
            offline_layout = layout
            release_optional_compose(
                layout,
                "offline-airflow.compose.yaml",
                required=state.local_airflow,
            )
            release_optional_compose(
                layout,
                "offline-graph.compose.yaml",
                required=state.local_graph,
            )
            release_optional_compose(
                layout,
                "offline-local-connectors.compose.yaml",
                required=state.local_storage,
            )
            require_release_compatible_checkout(
                runner,
                release_commit=layout.source_commit,
                checkout_commit=current_source_commit,
            )
            runtime_commit = layout.source_commit
            runtime_paths = _git_paths(runner, state.runtime_commit, runtime_commit)
            if args.reload_release or runtime_commit != state.runtime_commit:
                _verify_and_load_release(runner, release_dir=release_dir)
        elif args.release_dir is not None:
            raise WorkflowError("--release-dir is valid only for an offline applied state.")

        changed_paths = tuple(dict.fromkeys((*source_paths, *runtime_paths)))
        source_plan = classify_changes(changed_paths)
        reapply_local_identity = requires_local_identity_bootstrap(
            changed_paths,
            profile=state.profile,
        )
        files = _compose_files(state, release_override=release_dir)

        if args.refresh_bootstrap:
            runner.note("기존 secret을 보존하며 bootstrap 파생 설정을 재적용합니다.")
            _bootstrap(runner, state=state, env_file=env_file)

        environment_values = read_env_values(env_file)
        current_environment_hashes = environment_key_hashes(environment_values)
        environment_keys = changed_environment_keys(
            state.environment_key_hashes,
            current_environment_hashes,
        )
        immutable_bootstrap_keys = {"POSTGRES_DB", "POSTGRES_USER"}
        changed_immutable_keys = sorted(immutable_bootstrap_keys.intersection(environment_keys))
        if state.environment_key_hashes and changed_immutable_keys:
            raise WorkflowError(
                "Bootstrap-owned PostgreSQL identity cannot be changed by the update workflow: "
                + ", ".join(changed_immutable_keys)
                + ". Use a reviewed fresh setup or database migration procedure."
            )
        plan = merge_change_plans(
            source_plan,
            classify_environment_changes(environment_keys),
        )

        runner.note("Compose 구성을 서비스 변경 전에 검증합니다.")
        _compose(
            runner,
            env_file=env_file,
            files=files,
            trailing=("config", "--quiet"),
        )
        running = _running_services(runner, env_file=env_file, files=files)
        reconciliation_plan: TopologyReconciliationPlan | None = None
        if reconciliation_name is None:
            enforce_local_topology(
                runner,
                state=state,
                environment_values=environment_values,
            )
        else:
            reconciliation_plan = _prepare_topology_reconciliation(
                runner,
                state=state,
                environment_values=environment_values,
                reconciliation=reconciliation_name,
            )
        operating_state = (
            reconciliation_plan.target_state if reconciliation_plan is not None else state
        )
        files = _compose_files(operating_state, release_override=release_dir)
        enabled_optional_services = _enabled_optional_runtime_services(environment_values)
        restart_services = select_restart_services(
            plan.services,
            running_services=(*running, *enabled_optional_services),
        )
        immediate_restart_services = tuple(
            service
            for service in restart_services
            if reconciliation_plan is None or service != "web"
        )
        _print_plan(
            previous_commit=state.applied_commit,
            current_source_commit=current_source_commit,
            runtime_commit=runtime_commit,
            paths=changed_paths,
            environment_keys=environment_keys,
            plan=plan,
            restart_services=restart_services,
        )
        if not args.assume_yes and (changed_paths or environment_keys):
            if not prompt_confirm("위 변경만 적용할까요?", default=True):
                raise WorkflowError("Operator cancelled before service mutation.")

        offline = state.deployment_mode == "offline"
        core_build_services: list[str] = []
        selected_build_services: list[str] = []
        capacity_files = list(files)
        if not offline:
            if restart_services:
                core_build_services.extend(restart_services)
                core_build_services.extend(("migrate",) if plan.requires_migration else ())
                selected_build_services.extend(core_build_services)
            if reapply_local_identity:
                selected_build_services.append("local-bootstrap")
            if (
                plan.restart_airflow
                and operating_state.local_airflow
                and reconciliation_plan is None
            ):
                selected_build_services.extend(AIRFLOW_SERVICES)
                capacity_files.append(ROOT / "compose.airflow.yaml")
            if plan.restart_gateway and operating_state.local_gateway:
                selected_build_services.append("apisix")
                capacity_files.append(ROOT / "compose.gateway.yaml")
        core_build_services = list(dict.fromkeys(core_build_services))
        selected_build_services = list(dict.fromkeys(selected_build_services))

        topology_secret_guard: TopologyReconciliationSecretGuard | None = None
        selected_builder: str | None = None
        if not offline:
            if capacity_lock is None:
                capacity_lock = mutation_stack.enter_context(exclusive_docker_workflow_lock(ROOT))
            if reconciliation_plan is not None:
                runner.note(
                    "Topology mutation 전 canonical secret/config/runtime preflight를 반복합니다."
                )
                topology_secret_guard = mutation_stack.enter_context(
                    require_topology_reconciliation_secrets(ROOT)
                )
                locked_plan = _prepare_topology_reconciliation(
                    runner,
                    state=state,
                    environment_values=environment_values,
                    reconciliation=reconciliation_plan.name,
                )
                if locked_plan != reconciliation_plan:
                    raise WorkflowError("TOPOLOGY_RECONCILIATION_PRECONDITION_FAILED")
                _compose(
                    runner,
                    env_file=env_file,
                    files=files,
                    trailing=("config", "--quiet"),
                )
            if selected_build_services:
                runner.note("Docker 변경 전에 선택 build의 용량·cache 계약을 검증합니다.")
                selected_builder = _preflight_build_capacity(
                    runner,
                    env_file=env_file,
                    files=tuple(dict.fromkeys(capacity_files)),
                    selected_build_services=tuple(selected_build_services),
                    lock=capacity_lock,
                )

        _reconcile_local_reranker(runner, env_file=env_file, profile=state.profile)

        if not offline and restart_services:
            _require_idle_builder(selected_builder, capacity_lock)
            runner.note("선택한 build 프로필에서 영향받은 이미지만 빌드합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=files,
                trailing=("build", *core_build_services),
            )
        if reapply_local_identity:
            if not offline:
                _require_idle_builder(selected_builder, capacity_lock)
            runner.note("변경된 Mac 로컬 identity bootstrap 이미지를 빌드합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=files,
                profiles=("tools",),
                trailing=("build", "local-bootstrap"),
            )

        if plan.requires_migration:
            stop_services = tuple(service for service in restart_services if service in running)
            if stop_services:
                runner.note("Schema 변경 전에 영향받는 실행 서비스를 중지합니다.")
                _compose(
                    runner,
                    env_file=env_file,
                    files=files,
                    trailing=("stop", *stop_services),
                )
            if _requires_postgres_secret_remount(environment_keys):
                runner.note("새 PostgreSQL role secret mount를 migration 전에 재적용합니다.")
                _compose(
                    runner,
                    env_file=env_file,
                    files=(ROOT / "compose.yaml",),
                    trailing=(
                        "up",
                        "-d",
                        "--wait",
                        "--no-deps",
                        "--force-recreate",
                        *(("--pull", "never") if offline else ()),
                        "postgres",
                    ),
                )
            runner.note("Migration 선행 PostgreSQL 역할 계약을 재적용합니다.")
            _reconcile_postgres(runner, env_file=env_file)
            runner.note("Alembic migration을 적용합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=files,
                trailing=(
                    "run",
                    "--rm",
                    *(("--pull", "never") if offline else ()),
                    "migrate",
                ),
            )
            runner.note("Migration 후 PostgreSQL 역할 grant를 재적용합니다.")
            _reconcile_postgres(runner, env_file=env_file)

        if reapply_local_identity:
            runner.note("변경된 Mac 로컬 maker/checker identity를 재적용합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=files,
                profiles=("tools",),
                trailing=("run", "--rm", "local-bootstrap"),
            )

        if state.local_storage and (
            environment_values.get("KNOWLEDGE_STUDIO_PROPOSAL_WORKER_ENABLED", "").lower() == "true"
        ):
            knowledge_storage_files: tuple[Path, ...] = (ROOT / "compose.local-connectors.yaml",)
            if offline_layout is not None:
                storage_override = release_optional_compose(
                    offline_layout,
                    "offline-local-connectors.compose.yaml",
                    required=True,
                )
                assert storage_override is not None
                knowledge_storage_files = (*knowledge_storage_files, storage_override)
            runner.note("Knowledge Proposal worker의 전용 Object Storage identity를 검증합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=knowledge_storage_files,
                profiles=("object-storage",),
                trailing=(
                    "run",
                    "--rm",
                    *(("--pull", "never") if offline else ()),
                    "minio-knowledge-identity-init",
                ),
            )

        if immediate_restart_services:
            runner.note("영향받은 DataRiver 서비스만 재생성합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=files,
                trailing=(
                    "up",
                    "-d",
                    "--wait",
                    "--no-deps",
                    "--force-recreate",
                    *(("--no-build", "--pull", "never") if offline else ("--no-build",)),
                    *immediate_restart_services,
                ),
            )

        if plan.configure_keycloak and "keycloak" not in running:
            runner.note("중단된 update 재시도를 위해 Keycloak을 기동합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=files,
                trailing=(
                    "up",
                    "-d",
                    "--wait",
                    "--no-deps",
                    *(("--pull", "never") if offline else ()),
                    "keycloak",
                ),
            )

        if plan.configure_keycloak:
            values = read_env_values(env_file)
            keycloak_env = os.environ.copy()
            keycloak_env["DATARIVER_WEB_ORIGIN"] = values["APP_PUBLIC_ORIGIN"]
            runner.note("Keycloak redirect와 service client를 현재 origin에 재적용합니다.")
            runner.run(
                (ROOT / "scripts" / "configure_keycloak_host_dev.sh",),
                env=keycloak_env,
            )

        if plan.restart_local_connectors and (state.local_redis or state.local_storage):
            connector_files: tuple[Path, ...] = (ROOT / "compose.local-connectors.yaml",)
            if offline_layout is not None:
                connector_override = release_optional_compose(
                    offline_layout,
                    "offline-local-connectors.compose.yaml",
                    required=state.local_storage,
                )
                if connector_override is not None:
                    connector_files = (*connector_files, connector_override)
            connector_services: list[str] = []
            profiles: tuple[str, ...] = ()
            connector_env = os.environ.copy()
            if state.local_redis:
                connector_services.extend(
                    service
                    for service in ("redis-cache", "redis-delivery")
                    if service in plan.local_connector_services
                )
                if offline:
                    connector_env["REDIS_IMAGE"] = "redis:8.2.6-bookworm"
            if state.local_storage and "minio" in plan.local_connector_services:
                connector_services.append("minio")
                profiles = ("object-storage",)
            if connector_services:
                runner.note("변경된 로컬 connector만 재생성합니다.")
                _compose(
                    runner,
                    env_file=env_file,
                    files=connector_files,
                    profiles=profiles,
                    trailing=(
                        "up",
                        "-d",
                        "--wait",
                        "--no-deps",
                        "--force-recreate",
                        *(("--no-build", "--pull", "never") if offline else ("--no-build",)),
                        *connector_services,
                    ),
                    env=connector_env,
                )

        if plan.restart_airflow and state.local_airflow and reconciliation_plan is None:
            airflow_files = _airflow_compose_files(
                files,
                local_gateway=operating_state.local_gateway,
            )
            if offline_layout is not None:
                airflow_override = release_optional_compose(
                    offline_layout,
                    "offline-airflow.compose.yaml",
                    required=True,
                )
                assert airflow_override is not None
                airflow_files = (*airflow_files, airflow_override)
            if not offline:
                _require_idle_builder(selected_builder, capacity_lock)
                _compose(
                    runner,
                    env_file=env_file,
                    files=airflow_files,
                    trailing=("build", *AIRFLOW_SERVICES),
                )
            runner.note("Airflow metadata migration 전에 scheduler/API를 중지합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=airflow_files,
                trailing=("stop", *AIRFLOW_SERVICES),
            )
            runner.note("Airflow DB role/database 계약을 재적용합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=airflow_files,
                trailing=(
                    "run",
                    "--rm",
                    *(("--pull", "never") if offline else ()),
                    "airflow-db-init",
                ),
            )
            runner.note("Airflow metadata migration을 적용합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=airflow_files,
                trailing=(
                    "run",
                    "--rm",
                    *(("--pull", "never") if offline else ()),
                    "airflow-init",
                ),
            )
            runner.note("로컬 Airflow 서비스만 재생성합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=airflow_files,
                trailing=(
                    "up",
                    "-d",
                    "--wait",
                    "--no-deps",
                    "--force-recreate",
                    *(("--no-build", "--pull", "never") if offline else ("--no-build",)),
                    *AIRFLOW_SERVICES,
                ),
            )

        if plan.restart_datahub and state.local_datahub:
            runner.note("Mac 개발용 DataHub 구성을 재적용합니다.")
            runner.run((ROOT / "scripts" / "start_datahub_mac_dev.sh", "start-offline"))

        if plan.restart_graph and operating_state.local_graph:
            graph_files = (*files, ROOT / "compose.graph.yaml")
            if offline_layout is not None:
                graph_override = release_optional_compose(
                    offline_layout,
                    "offline-graph.compose.yaml",
                    required=True,
                )
                assert graph_override is not None
                graph_files = (*graph_files, graph_override)
            runner.note("로컬 Neo4j projection sandbox만 재생성합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=graph_files,
                trailing=(
                    "up",
                    "-d",
                    "--wait",
                    "--no-deps",
                    "--force-recreate",
                    *(("--no-build", "--pull", "never") if offline else ("--no-build",)),
                    "neo4j",
                ),
            )

        if reconciliation_plan is None and plan.restart_gateway and operating_state.local_gateway:
            gateway_files = tuple(dict.fromkeys((*files, ROOT / "compose.gateway.yaml")))
            if not offline:
                _require_idle_builder(selected_builder, capacity_lock)
                _compose(
                    runner,
                    env_file=env_file,
                    files=gateway_files,
                    trailing=("build", "apisix"),
                )
            runner.note("로컬 APISIX gateway만 재생성합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=gateway_files,
                trailing=(
                    "up",
                    "-d",
                    "--wait",
                    "--no-deps",
                    "--force-recreate",
                    *(("--no-build", "--pull", "never") if offline else ("--no-build",)),
                    "apisix",
                ),
            )

        if reconciliation_plan is not None:
            if topology_secret_guard is None:
                raise WorkflowError("TOPOLOGY_SECRET_PREFLIGHT_FAILED")
            _apply_topology_reconciliation(
                runner,
                env_file=env_file,
                files=files,
                plan=reconciliation_plan,
                selected_builder=selected_builder,
                capacity_lock=capacity_lock,
                secret_guard=topology_secret_guard,
            )

        connector_changed = (
            state.local_redis
            and any(
                service in plan.local_connector_services
                for service in ("redis-cache", "redis-delivery")
            )
        ) or (state.local_storage and "minio" in plan.local_connector_services)
        auxiliary_changed = any(
            (
                plan.restart_datahub and state.local_datahub,
                plan.restart_airflow and state.local_airflow,
                plan.restart_graph and operating_state.local_graph,
                plan.restart_gateway and operating_state.local_gateway,
                connector_changed,
            )
        )
        if restart_services or plan.requires_migration or auxiliary_changed:
            runner.note("DataRiver liveness/readiness/Web health를 검증합니다.")
            _health_check(runner, env_file=env_file)
            runner.note("DataHub GMS token/version 계약을 API 컨테이너에서 검증합니다.")
            _probe_datahub(runner, env_file=env_file, files=files)

        if reconciliation_plan is not None:
            runner.note("APISIX transparent auth/header/log 계약을 state write 전에 검증합니다.")
            _verify_gateway_transparency(
                runner,
                env_file=env_file,
                files=files,
            )

        backend_changed = any(
            path.startswith("backend/") or path in {"compose.yaml", "pyproject.toml"}
            for path in changed_paths
        ) or any(key.startswith("DATAHUB_") for key in environment_keys)
        catalog_synced = False
        if (backend_changed or (plan.restart_datahub and state.local_datahub)) and (
            not args.skip_catalog_sync
        ):
            runner.note("Backend 변경 후 DataHub catalog projection을 동기화합니다.")
            _sync_catalog(runner, env_file=env_file)
            catalog_synced = True
        if catalog_synced or reapply_local_identity:
            runner.note("활성 Catalog System/Domain 범위를 로컬 관리자에게 동기화합니다.")
            _reconcile_local_admin_catalog_access(
                runner,
                env_file=env_file,
                files=files,
            )

        if reconciliation_plan is not None:
            if topology_secret_guard is None:
                raise WorkflowError("TOPOLOGY_SECRET_PREFLIGHT_FAILED")
            topology_secret_guard.revalidate()
            runner.note("Graph/gateway target topology를 state write 전에 최종 검증합니다.")
            enforce_local_topology(
                runner,
                state=operating_state,
                environment_values=environment_values,
            )

        write_applied_state(
            state_file,
            replace(
                operating_state,
                applied_commit=current_source_commit,
                runtime_commit=runtime_commit,
                env_file=(
                    os.fspath(env_file.relative_to(ROOT))
                    if env_file.is_relative_to(ROOT)
                    else os.fspath(env_file)
                ),
                release_dir=os.fspath(release_dir) if release_dir else state.release_dir,
                environment_key_hashes=current_environment_hashes,
            ),
        )
        if not changed_paths and not environment_keys:
            runner.note("적용할 source/runtime/환경 변경이 없어 컨테이너를 재시작하지 않았습니다.")
        else:
            runner.note("업데이트 적용과 선택적 재시작을 완료했습니다.")
        return 0
    except (DockerCapacityError, WorkflowError, KeyError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    finally:
        mutation_stack.close()


if __name__ == "__main__":
    raise SystemExit(main())
