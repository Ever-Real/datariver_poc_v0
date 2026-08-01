#!/usr/bin/env python3
"""Apply one Git update and restart only affected DataRiver services."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from pathlib import Path

from platform_workflow import (
    AIRFLOW_SERVICES,
    ROOT,
    WORKFLOW_PROFILE_NAMES,
    AppliedState,
    ChangePlan,
    Runner,
    WorkflowError,
    changed_environment_keys,
    classify_changes,
    classify_environment_changes,
    compose_arguments,
    current_commit,
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

_POSTGRES_SECRET_MOUNT_ENV_KEYS = frozenset(
    {
        "KNOWLEDGE_PROPOSAL_DATABASE_SECRET_REF",
    }
)


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
    return parser.parse_args()


def _resolve_repo_path(value: str | Path) -> Path:
    candidate = Path(value).expanduser()
    return candidate.resolve() if candidate.is_absolute() else (ROOT / candidate).resolve()


def _compose_files(state: AppliedState, *, release_override: Path | None) -> tuple[Path, ...]:
    files = (ROOT / "compose.yaml", ROOT / "compose.identity.yaml")
    if state.deployment_mode == "build":
        return files
    release_dir = release_override or (
        Path(state.release_dir) if state.release_dir is not None else None
    )
    if release_dir is None:
        raise WorkflowError("The offline state has no release directory.")
    layout = release_layout(release_dir, architecture="amd64")
    return (*files, layout.offline_compose)


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
    output = runner.output(
        compose_arguments(
            env_file=env_file,
            compose_files=files,
            trailing=("ps", "--services", "--filter", "status=running"),
        )
    )
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
    runner = Runner()
    try:
        for command in ("docker", "git"):
            require_command(command)
        state_file = state_path(ROOT, args.profile)
        state = load_applied_state(state_file)
        if state.profile != args.profile:
            raise WorkflowError("The requested profile does not match its applied state.")
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
        enabled_optional_services = _enabled_optional_runtime_services(environment_values)
        restart_services = select_restart_services(
            plan.services,
            running_services=(*running, *enabled_optional_services),
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

        _reconcile_local_reranker(runner, env_file=env_file, profile=state.profile)

        offline = state.deployment_mode == "offline"
        if not offline and restart_services:
            build_services = list(restart_services)
            if plan.requires_migration and "migrate" not in build_services:
                build_services.append("migrate")
            runner.note("선택한 build 프로필에서 영향받은 이미지만 빌드합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=files,
                trailing=("build", *build_services),
            )
        if reapply_local_identity:
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

        if restart_services:
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
                    *restart_services,
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

        if plan.restart_airflow and state.local_airflow:
            airflow_files = (*files, ROOT / "compose.airflow.yaml")
            if offline_layout is not None:
                airflow_override = release_optional_compose(
                    offline_layout,
                    "offline-airflow.compose.yaml",
                    required=True,
                )
                assert airflow_override is not None
                airflow_files = (*airflow_files, airflow_override)
            if not offline:
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
            runner.run((ROOT / "scripts" / "start_datahub_mac_dev.sh", "start"))

        if plan.restart_graph and state.local_graph:
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

        if plan.restart_gateway and state.local_gateway:
            gateway_files = (*files, ROOT / "compose.gateway.yaml")
            if not offline:
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
                plan.restart_graph and state.local_graph,
                plan.restart_gateway and state.local_gateway,
                connector_changed,
            )
        )
        if restart_services or plan.requires_migration or auxiliary_changed:
            runner.note("DataRiver liveness/readiness/Web health를 검증합니다.")
            _health_check(runner, env_file=env_file)
            runner.note("DataHub GMS token/version 계약을 API 컨테이너에서 검증합니다.")
            _probe_datahub(runner, env_file=env_file, files=files)

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

        write_applied_state(
            state_file,
            replace(
                state,
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
    except (WorkflowError, KeyError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
