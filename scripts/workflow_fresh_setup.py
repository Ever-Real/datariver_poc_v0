#!/usr/bin/env python3
"""Serial, fail-fast DataRiver setup for Mac development and WSL preparation."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from platform_workflow import (
    AIRFLOW_SERVICES,
    DEFAULT_RUNTIME_SERVICES,
    ROOT,
    WORKFLOW_PROFILE_NAMES,
    AppliedState,
    Runner,
    WorkflowError,
    compose_arguments,
    copy_secret,
    current_commit,
    endpoint_host,
    environment_key_hashes,
    install_secret,
    merge_no_proxy,
    normalize_secret_permissions,
    prompt_choice,
    prompt_confirm,
    prompt_secret,
    prompt_text,
    read_env_values,
    release_layout,
    release_optional_compose,
    require_clean_worktree,
    require_command,
    require_regular_file,
    require_release_compatible_checkout,
    state_path,
    update_env_values,
    validate_endpoint,
    validate_username_password_secret,
    workflow_profile,
    write_applied_state,
)

CATALOG_SYNC_PROGRAM = """\
import json
from datetime import UTC, datetime
from datariver_catalog_sync import synchronize_catalog_projection

run_id = "operator__fresh_" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
result = synchronize_catalog_projection(run_id=run_id)
print(json.dumps(result, ensure_ascii=False, indent=2))
"""

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

HEALTH_PROGRAM = """\
import sys
import urllib.request

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for url in sys.argv[1:]:
    with opener.open(url, timeout=10) as response:
        body = response.read(512).decode("utf-8", errors="replace").strip()
    print(f"{url} -> HTTP {response.status} {body}")
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create and validate a new DataRiver portable/Mac development or WSL preparation "
            "environment. Provider credentials are accepted only from files or hidden "
            "interactive input."
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
        help="Required immutable linux/amd64 release directory for WSL.",
    )
    parser.add_argument("--redis-image-archive", type=Path)
    parser.add_argument(
        "--datahub-mode",
        choices=("local", "external"),
        help="Local DataHub is supported only by the Mac development profile.",
    )
    parser.add_argument("--datahub-base-url")
    parser.add_argument("--datahub-token-file", type=Path)
    parser.add_argument("--redis-mode", choices=("local", "external"))
    parser.add_argument("--storage-mode", choices=("local", "external", "skip"))
    parser.add_argument("--airflow-mode", choices=("local", "external", "skip"))
    parser.add_argument("--airflow-ui-url")
    parser.add_argument(
        "--graph-mode",
        choices=("local", "external", "skip"),
        default="skip",
    )
    parser.add_argument("--neo4j-uri")
    parser.add_argument("--neo4j-auth-file", type=Path)
    parser.add_argument("--neo4j-ui-url")
    parser.add_argument(
        "--with-graph",
        action="store_true",
        help="Backward-compatible alias for --graph-mode local.",
    )
    parser.add_argument("--with-gateway", action="store_true")
    parser.add_argument("--skip-catalog-sync", action="store_true")
    parser.add_argument(
        "--assume-yes",
        action="store_true",
        help="Skip the final non-secret configuration confirmation.",
    )
    return parser.parse_args()


def _select_mode(
    supplied: str | None,
    *,
    label: str,
    choices: tuple[str, ...],
    default: str,
) -> str:
    return supplied or prompt_choice(label, choices, default=default)


def _normalize_architecture(value: str) -> str:
    aliases = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "amd64", "amd64": "amd64"}
    try:
        return aliases[value]
    except KeyError as error:
        raise WorkflowError(f"Unsupported Docker architecture: {value}") from error


def _verify_platform(runner: Runner, *, profile: str) -> str:
    raw = runner.output(("docker", "info", "--format", "{{.OSType}}/{{.Architecture}}"))
    try:
        operating_system, architecture = raw.split("/", 1)
    except ValueError as error:
        raise WorkflowError("Docker returned an invalid OS/architecture value.") from error
    normalized = _normalize_architecture(architecture)
    supported = workflow_profile(profile).target_architectures
    if operating_system != "linux" or normalized not in supported:
        expected = ", ".join(f"linux/{value}" for value in supported)
        raise WorkflowError(f"{profile} requires one of {expected}, but the daemon is {raw}.")
    return normalized


def _load_gzip_image(runner: Runner, archive: Path) -> None:
    require_regular_file(archive, label="Redis image archive")
    checksum = archive.with_name(archive.name + ".sha256")
    require_regular_file(checksum, label="Redis image checksum")
    checksum_tool = "sha256sum" if sys.platform != "darwin" else "shasum"
    arguments = (
        (checksum_tool, "-c", checksum.name)
        if checksum_tool == "sha256sum"
        else (checksum_tool, "-a", "256", "-c", checksum.name)
    )
    runner.run(arguments, cwd=archive.parent)
    runner.note("Redis 이미지 아카이브를 Docker에 로드합니다.")
    print(f"     $ gzip -dc {archive} | docker image load", flush=True)
    decompressor = subprocess.Popen(  # noqa: S603 - fixed executable and argv.
        ("gzip", "-dc", archive),
        stdout=subprocess.PIPE,
    )
    assert decompressor.stdout is not None
    loader = subprocess.run(
        ("docker", "image", "load"),
        stdin=decompressor.stdout,
        check=False,
    )
    decompressor.stdout.close()
    decompressor_status = decompressor.wait()
    if decompressor_status != 0 or loader.returncode != 0:
        raise WorkflowError("The Redis image archive could not be loaded.")


def _install_datahub_token(args: argparse.Namespace, *, mode: str) -> None:
    destination = ROOT / "secrets" / "datahub_token"
    if mode == "local" and args.profile == "mac-development":
        return
    if args.datahub_token_file is not None:
        copy_secret(args.datahub_token_file.expanduser(), destination)
        return
    if destination.is_file() and destination.stat().st_size > 0:
        if prompt_confirm("기존 secrets/datahub_token을 재사용할까요?", default=True):
            return
    install_secret(destination, prompt_secret("DataHub service token"))


def _configure_external_redis(env_file: Path) -> None:
    values = read_env_values(env_file)
    cache_url = validate_endpoint(
        prompt_text("Redis cache URL", default=values.get("REDIS_CACHE_URL")),
        allowed_schemes=("redis", "rediss"),
    )
    delivery_url = validate_endpoint(
        prompt_text("Redis delivery URL", default=values.get("REDIS_DELIVERY_URL")),
        allowed_schemes=("redis", "rediss"),
    )
    if cache_url == delivery_url:
        raise WorkflowError("Redis cache and delivery must use distinct URLs or databases.")
    install_secret(ROOT / "secrets" / "redis_cache_password", prompt_secret("Redis cache password"))
    install_secret(
        ROOT / "secrets" / "redis_delivery_password",
        prompt_secret("Redis delivery password"),
    )
    update_env_values(
        env_file,
        {
            "REDIS_CACHE_URL": cache_url,
            "REDIS_DELIVERY_URL": delivery_url,
            "REDIS_CACHE_SECRET_REF": "file:/run/secrets/redis_cache_password",
            "REDIS_DELIVERY_SECRET_REF": "file:/run/secrets/redis_delivery_password",
        },
    )


def _configure_external_storage(env_file: Path) -> tuple[str, str]:
    values = read_env_values(env_file)
    endpoint = validate_endpoint(
        prompt_text("MinIO/S3 API URL", default=values.get("S3_ENDPOINT_URL")),
        allowed_schemes=("http", "https"),
    )
    public_endpoint = validate_endpoint(
        prompt_text("브라우저 접근 MinIO/S3 API URL", default=endpoint),
        allowed_schemes=("http", "https"),
    )
    install_secret(ROOT / "secrets" / "s3_access_key", prompt_secret("MinIO/S3 access key"))
    install_secret(
        ROOT / "secrets" / "s3_secret_key",
        prompt_secret("MinIO/S3 secret key", confirm=True),
    )
    update_env_values(
        env_file,
        {
            "S3_ENDPOINT_URL": endpoint,
            "S3_PUBLIC_ENDPOINT_URL": public_endpoint,
            "S3_PUBLIC_ORIGIN": public_endpoint,
            "S3_CORS_MANAGEMENT_MODE": "external",
        },
    )
    return endpoint, public_endpoint


def _configure_local_storage(env_file: Path, *, profile: str) -> tuple[str, str]:
    public_port = "9000"
    endpoint = workflow_profile(profile).local_storage_endpoint
    public_endpoint = f"http://localhost:{public_port}"
    update_env_values(
        env_file,
        {
            "S3_ENDPOINT_URL": endpoint,
            "S3_PUBLIC_ENDPOINT_URL": public_endpoint,
            "S3_PUBLIC_ORIGIN": public_endpoint,
            "S3_CORS_MANAGEMENT_MODE": "external",
        },
    )
    return endpoint, public_endpoint


def _configure_external_graph(args: argparse.Namespace, env_file: Path) -> str:
    values = read_env_values(env_file)
    supplied_uri = args.neo4j_uri or prompt_text(
        "외부 Neo4j Bolt URI",
        default=values.get("NEO4J_URI"),
    )
    uri = validate_endpoint(
        supplied_uri,
        allowed_schemes=("bolt+s", "neo4j+s"),
    )
    if urlsplit(uri).port != 7687:
        raise WorkflowError("External Neo4j must expose the reviewed Bolt port 7687.")
    destination = ROOT / "secrets" / "neo4j_auth"
    if args.neo4j_auth_file is not None:
        source = require_regular_file(
            args.neo4j_auth_file.expanduser(),
            label="Neo4j credential source",
        )
        install_secret(
            destination,
            validate_username_password_secret(source.read_text(encoding="utf-8")),
        )
    else:
        username = prompt_text("Neo4j username")
        if "/" in username:
            raise WorkflowError("Neo4j username must not contain '/'.")
        install_secret(
            destination,
            validate_username_password_secret(f"{username}/{prompt_secret('Neo4j password')}"),
        )
    updates = {
        "NEO4J_PROJECTION_ENABLED": "true",
        "NEO4J_URI": uri,
        "NEO4J_ALLOWED_HOSTS": endpoint_host(uri),
        "NEO4J_AUTH_SECRET_REF": "file:/run/secrets/neo4j_auth",
    }
    if args.neo4j_ui_url is not None:
        updates["UI_GRAPH_URL"] = validate_endpoint(
            args.neo4j_ui_url,
            allowed_schemes=("http", "https"),
        )
    update_env_values(env_file, updates)
    return uri


def _bootstrap(
    runner: Runner,
    *,
    profile: str,
    env_file: Path,
    datahub_base_url: str,
) -> None:
    runner.run(
        (
            ROOT / "scripts" / "bootstrap.sh",
            "--env-file",
            env_file,
            f"--{profile}",
            "--datahub-base-url",
            datahub_base_url,
        )
    )


def _runtime_compose_files(*, offline_compose: Path | None) -> tuple[Path, ...]:
    files = (ROOT / "compose.yaml", ROOT / "compose.identity.yaml")
    return files if offline_compose is None else (*files, offline_compose)


def _offline_flags(offline: bool) -> tuple[str, ...]:
    return ("--no-build", "--pull", "never") if offline else ("--no-build",)


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


def main() -> int:
    args = parse_args()
    runner = Runner()
    try:
        for command in ("docker", "git", "openssl"):
            require_command(command)
        require_clean_worktree(runner)
        commit = current_commit(runner)
        profile = workflow_profile(args.profile)
        architecture = _verify_platform(runner, profile=args.profile)
        datahub_mode = _select_mode(
            args.datahub_mode,
            label="DataHub 배치",
            choices=("local", "external"),
            default=profile.default_datahub_mode,
        )
        if datahub_mode == "local" and not profile.local_datahub_supported:
            raise WorkflowError(f"Local DataHub quickstart is not supported by {profile.name}.")
        redis_mode = _select_mode(
            args.redis_mode,
            label="Redis 배치",
            choices=("local", "external"),
            default=profile.default_redis_mode,
        )
        storage_mode = _select_mode(
            args.storage_mode,
            label="MinIO/S3 배치",
            choices=("local", "external", "skip"),
            default=profile.default_storage_mode,
        )
        airflow_mode = _select_mode(
            args.airflow_mode,
            label="Airflow 배치",
            choices=("local", "external", "skip"),
            default=profile.default_airflow_mode,
        )
        if args.with_graph and args.graph_mode not in {"skip", "local"}:
            raise WorkflowError("--with-graph conflicts with a non-local --graph-mode.")
        graph_mode = "local" if args.with_graph else args.graph_mode

        env_file = (
            args.env_file.expanduser().resolve() if args.env_file else ROOT / f".env.{args.profile}"
        )
        offline = profile.deployment_mode == "offline"
        layout = None
        if offline:
            require_command("sha256sum")
            if args.release_dir is None:
                raise WorkflowError(f"--release-dir is required for {profile.name}.")
            layout = release_layout(args.release_dir, architecture=architecture)
            release_optional_compose(
                layout,
                "offline-airflow.compose.yaml",
                required=airflow_mode == "local",
            )
            release_optional_compose(
                layout,
                "offline-graph.compose.yaml",
                required=graph_mode == "local",
            )
            release_optional_compose(
                layout,
                "offline-local-connectors.compose.yaml",
                required=storage_mode == "local",
            )
            require_release_compatible_checkout(
                runner,
                release_commit=layout.source_commit,
                checkout_commit=commit,
            )
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

        if redis_mode == "local" and offline:
            if args.redis_image_archive is not None:
                require_command("gzip")
                _load_gzip_image(runner, args.redis_image_archive.expanduser().resolve())
            runner.run(
                (
                    "docker",
                    "image",
                    "inspect",
                    "--platform",
                    "linux/amd64",
                    "redis:8.2.6-bookworm",
                )
            )

        if datahub_mode == "local":
            datahub_base_url = "http://host.docker.internal:8080"
        else:
            supplied = args.datahub_base_url or prompt_text("DataHub GMS origin")
            datahub_base_url = validate_endpoint(
                supplied,
                allowed_schemes=("http", "https"),
            )
        _install_datahub_token(args, mode=datahub_mode)

        runner.note("Bootstrap으로 환경·시크릿·Keycloak realm을 생성합니다.")
        _bootstrap(
            runner,
            profile=args.profile,
            env_file=env_file,
            datahub_base_url=datahub_base_url,
        )

        if redis_mode == "external":
            _configure_external_redis(env_file)
        if storage_mode == "external":
            storage_endpoint, public_storage_endpoint = _configure_external_storage(env_file)
        elif storage_mode == "local":
            storage_endpoint, public_storage_endpoint = _configure_local_storage(
                env_file,
                profile=args.profile,
            )
        else:
            storage_endpoint = ""
            public_storage_endpoint = ""

        values = read_env_values(env_file)
        no_proxy_hosts = [endpoint_host(datahub_base_url)]
        if storage_endpoint:
            no_proxy_hosts.append(endpoint_host(storage_endpoint))
        no_proxy = merge_no_proxy(
            values.get("NO_PROXY", ""),
            ("127.0.0.1", "localhost", *no_proxy_hosts),
        )
        updates = {"NO_PROXY": no_proxy}
        if airflow_mode == "external":
            airflow_ui = args.airflow_ui_url or prompt_text(
                "외부 Airflow UI origin (비워둘 수 없음)"
            )
            updates["UI_AIRFLOW_URL"] = validate_endpoint(
                airflow_ui,
                allowed_schemes=("http", "https"),
            )
        update_env_values(env_file, updates)

        if graph_mode == "local":
            update_env_values(
                env_file,
                {
                    "NEO4J_PROJECTION_ENABLED": "true",
                    "NEO4J_URI": "bolt://neo4j:7687",
                    "NEO4J_ALLOWED_HOSTS": "neo4j",
                    "NEO4J_AUTH_SECRET_REF": "file:/run/secrets/neo4j_auth",
                },
            )
            graph_endpoint = "bolt://neo4j:7687"
        elif graph_mode == "external":
            graph_endpoint = _configure_external_graph(args, env_file)
        else:
            graph_endpoint = ""

        runner.note("새 provider secret의 Compose bind-mount 권한을 정규화합니다.")
        normalize_secret_permissions(ROOT / "secrets")

        if not args.assume_yes:
            print(
                json.dumps(
                    {
                        "profile": args.profile,
                        "source_commit": commit,
                        "env_file": os.fspath(env_file),
                        "release_dir": os.fspath(layout.root) if layout else None,
                        "datahub": datahub_base_url,
                        "redis": redis_mode,
                        "storage": storage_mode,
                        "storage_public": public_storage_endpoint or None,
                        "airflow": airflow_mode,
                        "gateway": args.with_gateway,
                        "graph": graph_mode,
                        "graph_endpoint": graph_endpoint or None,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            if not prompt_confirm("위 비민감 설정으로 계속할까요?", default=True):
                raise WorkflowError("Operator cancelled before container mutation.")

        if datahub_mode == "local":
            runner.note("Mac 개발용 DataHub v1.6.0을 시작합니다.")
            runner.run((ROOT / "scripts" / "start_datahub_mac_dev.sh", "start"))

        _reconcile_local_reranker(runner, env_file=env_file, profile=args.profile)

        runtime_files = _runtime_compose_files(
            offline_compose=layout.offline_compose if layout else None
        )
        if not offline:
            build_services = (
                "migrate",
                "storage-init",
                "local-bootstrap",
                "keycloak",
                *DEFAULT_RUNTIME_SERVICES,
            )
            runner.note("선택한 build 프로필에서 현재 소스의 DataRiver 이미지를 빌드합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=runtime_files,
                trailing=("build", *build_services),
            )

        runner.note("Compose 구성을 시작 전에 검증합니다.")
        _compose(
            runner,
            env_file=env_file,
            files=runtime_files,
            trailing=("config", "--quiet"),
        )

        if redis_mode == "local":
            connector_files: tuple[Path, ...] = (ROOT / "compose.local-connectors.yaml",)
            if layout is not None:
                connector_override = release_optional_compose(
                    layout,
                    "offline-local-connectors.compose.yaml",
                )
                if connector_override is not None:
                    connector_files = (*connector_files, connector_override)
            connector_env = os.environ.copy()
            if offline:
                connector_env["REDIS_IMAGE"] = "redis:8.2.6-bookworm"
            runner.note("로컬 Redis cache/delivery를 시작합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=connector_files,
                trailing=(
                    "up",
                    "-d",
                    "--wait",
                    *_offline_flags(offline),
                    "redis-cache",
                    "redis-delivery",
                ),
                env=connector_env,
            )

        if storage_mode == "local":
            connector_files = (ROOT / "compose.local-connectors.yaml",)
            if layout is not None:
                connector_override = release_optional_compose(
                    layout,
                    "offline-local-connectors.compose.yaml",
                    required=True,
                )
                assert connector_override is not None
                connector_files = (*connector_files, connector_override)
            runner.note("로컬 MinIO reference를 시작합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=connector_files,
                profiles=("object-storage",),
                trailing=(
                    "up",
                    "-d",
                    "--wait",
                    *_offline_flags(offline),
                    "minio",
                ),
            )

        runner.note("PostgreSQL과 Keycloak을 시작합니다.")
        _compose(
            runner,
            env_file=env_file,
            files=runtime_files,
            trailing=(
                "up",
                "-d",
                "--wait",
                *_offline_flags(offline),
                "postgres",
                "keycloak",
            ),
        )

        runner.note("Alembic migration을 적용합니다.")
        _compose(
            runner,
            env_file=env_file,
            files=runtime_files,
            trailing=(
                "run",
                "--rm",
                *(("--pull", "never") if offline else ()),
                "migrate",
            ),
        )
        runner.note("PostgreSQL 역할 계약을 재적용합니다.")
        _reconcile_postgres(runner, env_file=env_file)

        values = read_env_values(env_file)
        web_origin = values["APP_PUBLIC_ORIGIN"]
        runner.note("Keycloak redirect와 service client를 현재 origin에 맞춥니다.")
        keycloak_env = os.environ.copy()
        keycloak_env["DATARIVER_WEB_ORIGIN"] = web_origin
        runner.run((ROOT / "scripts" / "configure_keycloak_host_dev.sh",), env=keycloak_env)

        runner.note("로컬 Workspace와 service identity를 생성합니다.")
        _compose(
            runner,
            env_file=env_file,
            files=runtime_files,
            profiles=("tools",),
            trailing=(
                "run",
                "--rm",
                *(("--pull", "never") if offline else ()),
                "local-bootstrap",
            ),
        )

        if storage_mode != "skip":
            runner.note("MinIO/S3 bucket 계약과 자격증명을 확인합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=runtime_files,
                profiles=("object-storage-tools",),
                trailing=(
                    "run",
                    "--rm",
                    *(("--pull", "never") if offline else ()),
                    "storage-init",
                ),
            )

        runner.note("DataRiver API, Web과 기본 worker를 시작합니다.")
        _compose(
            runner,
            env_file=env_file,
            files=runtime_files,
            trailing=(
                "up",
                "-d",
                "--wait",
                *_offline_flags(offline),
                *DEFAULT_RUNTIME_SERVICES,
            ),
        )

        if airflow_mode == "local":
            airflow_files = (*runtime_files, ROOT / "compose.airflow.yaml")
            if layout is not None:
                airflow_override = release_optional_compose(
                    layout,
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
            runner.note("로컬 Airflow 서비스를 시작합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=airflow_files,
                trailing=(
                    "up",
                    "-d",
                    "--wait",
                    *_offline_flags(offline),
                    *AIRFLOW_SERVICES,
                ),
            )

        if graph_mode == "local":
            graph_files = (*runtime_files, ROOT / "compose.graph.yaml")
            if layout is not None:
                graph_override = release_optional_compose(
                    layout,
                    "offline-graph.compose.yaml",
                    required=True,
                )
                assert graph_override is not None
                graph_files = (*graph_files, graph_override)
            runner.note("선택한 Neo4j projection sandbox를 시작합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=graph_files,
                trailing=("up", "-d", "--wait", *_offline_flags(offline), "neo4j", "api"),
            )

        if args.with_gateway:
            gateway_files = (*runtime_files, ROOT / "compose.gateway.yaml")
            if not offline:
                runner.note("선택한 APISIX gateway 이미지를 빌드합니다.")
                _compose(
                    runner,
                    env_file=env_file,
                    files=gateway_files,
                    trailing=("build", "apisix"),
                )
            runner.note("선택한 APISIX gateway를 시작합니다.")
            _compose(
                runner,
                env_file=env_file,
                files=gateway_files,
                trailing=("up", "-d", "--wait", *_offline_flags(offline), "apisix"),
            )

        runner.note("DataRiver liveness/readiness/Web health를 검증합니다.")
        _health_check(runner, env_file=env_file)
        runner.note("DataHub GMS token/version 계약을 API 컨테이너에서 검증합니다.")
        _probe_datahub(runner, env_file=env_file, files=runtime_files)

        if not args.skip_catalog_sync:
            runner.note("최초 DataHub catalog projection을 동기화합니다.")
            _sync_catalog(runner, env_file=env_file)

        write_applied_state(
            state_path(ROOT, args.profile),
            AppliedState(
                profile=args.profile,
                applied_commit=commit,
                runtime_commit=layout.source_commit if layout else commit,
                env_file=(
                    os.fspath(env_file.relative_to(ROOT))
                    if env_file.is_relative_to(ROOT)
                    else os.fspath(env_file)
                ),
                deployment_mode="offline" if offline else "build",
                release_dir=os.fspath(layout.root) if layout else None,
                local_airflow=airflow_mode == "local",
                local_datahub=datahub_mode == "local",
                local_redis=redis_mode == "local",
                local_storage=storage_mode == "local",
                local_gateway=args.with_gateway,
                local_graph=graph_mode == "local",
                environment_key_hashes=environment_key_hashes(read_env_values(env_file)),
            ),
        )
        runner.note("신규 설치가 완료되었고 적용 커밋 상태를 기록했습니다.")
        return 0
    except (WorkflowError, KeyError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
