"""Shared, testable contracts for DataRiver operator workflows."""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import NoReturn
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_RUNTIME_SERVICES = (
    "api",
    "web",
    "outbox-relay",
    "upload-worker",
    "upload-validation-worker",
    "governance-apply-worker",
)
BACKEND_RUNTIME_SERVICES = (
    "api",
    "outbox-relay",
    "upload-worker",
    "upload-validation-worker",
    "governance-apply-worker",
    "catalog-export-worker",
    "knowledge-source-worker",
    "retention-scheduler",
    "retention-archive-worker",
)
RUNTIME_SERVICES = (
    *DEFAULT_RUNTIME_SERVICES,
    "catalog-export-worker",
    "knowledge-source-worker",
    "retention-scheduler",
    "retention-archive-worker",
    "keycloak",
)
AIRFLOW_SERVICES = (
    "airflow-api-server",
    "airflow-scheduler",
    "airflow-dag-processor",
    "airflow-triggerer",
)
OPTIONAL_RELEASE_COMPOSE_FILES = {
    "offline-airflow.compose.yaml",
    "offline-graph.compose.yaml",
    "offline-local-connectors.compose.yaml",
}
LOCAL_CONNECTOR_SERVICES = ("redis-cache", "redis-delivery", "minio")

_ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class WorkflowError(RuntimeError):
    """An operator-correctable workflow failure."""


@dataclass(frozen=True)
class WorkflowProfile:
    """One explicit operator topology without inferring it from the host OS."""

    name: str
    deployment_mode: str
    target_architectures: tuple[str, ...]
    default_datahub_mode: str
    default_redis_mode: str
    default_storage_mode: str
    default_airflow_mode: str
    local_storage_endpoint: str
    local_datahub_supported: bool = False
    local_reranker_supported: bool = False

    def validate(self) -> None:
        if self.deployment_mode not in {"build", "offline"}:
            raise WorkflowError("The workflow profile deployment mode is invalid.")
        if not self.target_architectures or not set(self.target_architectures) <= {
            "arm64",
            "amd64",
        }:
            raise WorkflowError("The workflow profile target architecture is invalid.")
        if self.default_datahub_mode not in {"local", "external"}:
            raise WorkflowError("The workflow profile DataHub mode is invalid.")
        if self.default_redis_mode not in {"local", "external"}:
            raise WorkflowError("The workflow profile Redis mode is invalid.")
        if self.default_storage_mode not in {"local", "external", "skip"}:
            raise WorkflowError("The workflow profile storage mode is invalid.")
        if self.default_airflow_mode not in {"local", "external", "skip"}:
            raise WorkflowError("The workflow profile Airflow mode is invalid.")
        if self.local_storage_endpoint not in {
            "http://host.docker.internal:9000",
            "http://minio:9000",
        }:
            raise WorkflowError("The workflow profile local storage endpoint is invalid.")
        if self.local_datahub_supported != (self.default_datahub_mode == "local"):
            raise WorkflowError("The workflow profile local DataHub policy is inconsistent.")


WORKFLOW_PROFILES = {
    profile.name: profile
    for profile in (
        WorkflowProfile(
            name="portable-development",
            deployment_mode="build",
            target_architectures=("arm64", "amd64"),
            default_datahub_mode="external",
            default_redis_mode="local",
            default_storage_mode="local",
            default_airflow_mode="skip",
            local_storage_endpoint="http://minio:9000",
        ),
        WorkflowProfile(
            name="mac-development",
            deployment_mode="build",
            target_architectures=("arm64",),
            default_datahub_mode="local",
            default_redis_mode="local",
            default_storage_mode="local",
            default_airflow_mode="local",
            local_storage_endpoint="http://host.docker.internal:9000",
            local_datahub_supported=True,
            local_reranker_supported=True,
        ),
        WorkflowProfile(
            name="wsl-preparation",
            deployment_mode="offline",
            target_architectures=("amd64",),
            default_datahub_mode="external",
            default_redis_mode="local",
            default_storage_mode="external",
            default_airflow_mode="external",
            local_storage_endpoint="http://minio:9000",
        ),
    )
}
WORKFLOW_PROFILE_NAMES = tuple(WORKFLOW_PROFILES)
for _profile in WORKFLOW_PROFILES.values():
    _profile.validate()


def workflow_profile(name: str) -> WorkflowProfile:
    try:
        return WORKFLOW_PROFILES[name]
    except KeyError as error:
        raise WorkflowError("Unsupported workflow profile.") from error


@dataclass(frozen=True)
class ReleaseLayout:
    root: Path
    platform_dir: Path
    core_archive: Path
    checksum_file: Path
    checksum_cwd: Path
    offline_compose: Path
    source_commit_file: Path

    @property
    def source_commit(self) -> str:
        value = self.source_commit_file.read_text(encoding="utf-8").strip()
        if not _COMMIT.fullmatch(value):
            raise WorkflowError("The release source-commit marker is invalid.")
        return value


@dataclass(frozen=True)
class AppliedState:
    profile: str
    applied_commit: str
    runtime_commit: str
    env_file: str
    deployment_mode: str
    release_dir: str | None
    local_airflow: bool
    local_datahub: bool
    local_redis: bool
    local_storage: bool
    local_gateway: bool
    local_graph: bool
    environment_key_hashes: dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        profile = workflow_profile(self.profile)
        if not _COMMIT.fullmatch(self.applied_commit):
            raise WorkflowError("The applied-state commit is invalid.")
        if not _COMMIT.fullmatch(self.runtime_commit):
            raise WorkflowError("The applied-state runtime commit is invalid.")
        if self.deployment_mode not in {"build", "offline"}:
            raise WorkflowError("The applied-state deployment mode is invalid.")
        if self.deployment_mode != profile.deployment_mode:
            raise WorkflowError("The applied-state deployment mode does not match its profile.")
        if self.local_datahub and not profile.local_datahub_supported:
            raise WorkflowError(
                "The applied-state local DataHub mode is not allowed by its profile."
            )
        if not self.env_file or "\n" in self.env_file or "\r" in self.env_file:
            raise WorkflowError("The applied-state environment path is invalid.")
        if not isinstance(self.environment_key_hashes, dict) or any(
            not isinstance(key, str)
            or not isinstance(digest, str)
            or not _ENV_KEY.fullmatch(key)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            for key, digest in self.environment_key_hashes.items()
        ):
            raise WorkflowError("The applied-state environment fingerprints are invalid.")
        if self.deployment_mode == "offline" and not self.release_dir:
            raise WorkflowError("Offline applied state requires a release directory.")


@dataclass(frozen=True)
class ChangePlan:
    services: tuple[str, ...]
    requires_migration: bool
    configure_keycloak: bool
    restart_datahub: bool
    restart_airflow: bool
    restart_gateway: bool
    restart_graph: bool
    local_connector_services: tuple[str, ...]

    @property
    def restart_local_connectors(self) -> bool:
        return bool(self.local_connector_services)


class Runner:
    """Print and execute subprocesses without shell interpolation."""

    def __init__(self, *, root: Path = ROOT, dry_run: bool = False) -> None:
        self.root = root.resolve()
        self.dry_run = dry_run
        self.step = 0

    def note(self, message: str) -> None:
        self.step += 1
        print(f"[{self.step:02d}] {message}", flush=True)

    def run(
        self,
        arguments: Sequence[str | os.PathLike[str]],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        input_text: str | None = None,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        command = [os.fspath(argument) for argument in arguments]
        print(f"     $ {shlex.join(command)}", flush=True)
        if self.dry_run:
            return subprocess.CompletedProcess(command, 0, "", "")
        try:
            return subprocess.run(  # noqa: S603 - argv is never passed through a shell.
                command,
                cwd=cwd or self.root,
                env=env,
                input=input_text,
                check=True,
                text=True,
                capture_output=capture_output,
            )
        except subprocess.CalledProcessError as error:
            raise WorkflowError(
                f"Command failed with exit code {error.returncode}: {shlex.join(command)}"
            ) from error

    def output(
        self,
        arguments: Sequence[str | os.PathLike[str]],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        result = self.run(
            arguments,
            cwd=cwd,
            env=env,
            capture_output=True,
        )
        return result.stdout.strip()


def fail(message: str) -> NoReturn:
    raise WorkflowError(message)


def require_command(name: str) -> None:
    if shutil.which(name) is None:
        raise WorkflowError(f"Required command is unavailable: {name}")


def require_regular_file(path: Path, *, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise WorkflowError(f"{label} is not a regular file: {path}")
    return path.resolve()


def validate_endpoint(value: str, *, allowed_schemes: tuple[str, ...]) -> str:
    normalized = value.strip()
    if not normalized or any(character in normalized for character in "<>\r\n"):
        raise WorkflowError("The endpoint is blank or contains a placeholder.")
    parsed = urlsplit(normalized)
    if parsed.scheme not in allowed_schemes:
        raise WorkflowError(f"The endpoint scheme must be one of: {', '.join(allowed_schemes)}.")
    if (
        parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise WorkflowError("The endpoint must not contain credentials, query or fragment.")
    try:
        _ = parsed.port
    except ValueError as error:
        raise WorkflowError("The endpoint port is invalid.") from error
    if parsed.scheme in {"http", "https"} and parsed.path not in {"", "/"}:
        raise WorkflowError("An HTTP provider endpoint must be one origin without a path.")
    if parsed.scheme in {"bolt", "bolt+s", "neo4j", "neo4j+s"} and parsed.path not in {"", "/"}:
        raise WorkflowError("A Neo4j provider endpoint must not contain a database path.")
    if parsed.scheme in {"redis", "rediss"} and not re.fullmatch(r"/\d+", parsed.path):
        raise WorkflowError("A Redis endpoint must select one numeric database path.")
    return normalized.rstrip("/") if parsed.scheme in {"http", "https"} else normalized


def endpoint_host(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.hostname is None:
        raise WorkflowError("The endpoint has no host.")
    return parsed.hostname


def validate_username_password_secret(value: str) -> str:
    normalized = value.strip()
    username, separator, password = normalized.partition("/")
    if (
        not separator
        or not username
        or not password
        or any(character in normalized for character in "\r\n")
    ):
        raise WorkflowError("The credential must use the non-empty username/password format.")
    return normalized


def read_env_values(path: Path) -> dict[str, str]:
    require_regular_file(path, label="Environment file")
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line or raw_line.lstrip().startswith("#") or "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        if _ENV_KEY.fullmatch(key):
            values[key] = value.rstrip("\r")
    return values


def environment_key_hashes(values: dict[str, str]) -> dict[str, str]:
    """Fingerprint effective .env entries without persisting their values."""

    return {
        key: hashlib.sha256(f"{key}\0{value}".encode()).hexdigest()
        for key, value in sorted(values.items())
    }


def changed_environment_keys(
    previous: dict[str, str],
    current: dict[str, str],
) -> tuple[str, ...]:
    return tuple(
        sorted(key for key in set(previous) | set(current) if previous.get(key) != current.get(key))
    )


def update_env_values(path: Path, updates: dict[str, str]) -> None:
    require_regular_file(path, label="Environment file")
    for key, value in updates.items():
        if not _ENV_KEY.fullmatch(key):
            raise WorkflowError(f"Invalid environment key: {key}")
        if "\n" in value or "\r" in value:
            raise WorkflowError(f"Environment value contains a line break: {key}")
    original = path.read_text(encoding="utf-8").splitlines()
    emitted: set[str] = set()
    result: list[str] = []
    for line in original:
        key = line.split("=", 1)[0] if "=" in line else ""
        if key in updates:
            if key not in emitted:
                result.append(f"{key}={updates[key]}")
                emitted.add(key)
            continue
        result.append(line)
    for key, value in updates.items():
        if key not in emitted:
            result.append(f"{key}={value}")
    _atomic_write(path, "\n".join(result) + "\n", mode=stat.S_IMODE(path.stat().st_mode))


def merge_no_proxy(current: str, hosts: Sequence[str]) -> str:
    ordered = [entry.strip() for entry in current.split(",") if entry.strip()]
    for host in hosts:
        normalized = host.strip()
        if normalized and normalized not in ordered:
            ordered.append(normalized)
    return ",".join(ordered)


def prompt_text(label: str, *, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        value = input(f"{label}{suffix}: ").strip()
        if value:
            return value
        if default is not None:
            return default
        print("값을 입력해야 합니다.", flush=True)


def prompt_choice(label: str, choices: tuple[str, ...], *, default: str) -> str:
    rendered = "/".join(choices)
    while True:
        value = input(f"{label} ({rendered}) [{default}]: ").strip() or default
        if value in choices:
            return value
        print(f"다음 중 하나를 입력하세요: {rendered}", flush=True)


def prompt_confirm(label: str, *, default: bool = False) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        value = input(f"{label} [{suffix}]: ").strip().casefold()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("y 또는 n을 입력하세요.", flush=True)


def prompt_secret(label: str, *, confirm: bool = False) -> str:
    while True:
        value = getpass.getpass(f"{label}: ")
        if not value or "\n" in value or "\r" in value:
            print("비어 있지 않은 한 줄 값을 입력해야 합니다.", flush=True)
            continue
        if confirm and getpass.getpass(f"{label} 확인: ") != value:
            print("입력값이 일치하지 않습니다.", flush=True)
            continue
        return value


def install_secret(path: Path, value: str) -> None:
    if path.is_symlink():
        raise WorkflowError(f"Secret path must not be a symbolic link: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    _atomic_write(path, value.strip() + "\n", mode=0o600)


def copy_secret(source: Path, destination: Path) -> None:
    require_regular_file(source, label="Secret source")
    value = source.read_text(encoding="utf-8").strip()
    if not value:
        raise WorkflowError(f"Secret source is empty: {source}")
    install_secret(destination, value)


def normalize_secret_permissions(directory: Path) -> None:
    """Match Compose bind-secret permissions without exposing the parent directory."""

    if directory.is_symlink() or not directory.is_dir():
        raise WorkflowError(f"Secret directory is unavailable: {directory}")
    directory.chmod(0o700)
    for path in directory.iterdir():
        if path.is_symlink():
            raise WorkflowError(f"Secret path must not be a symbolic link: {path}")
        if path.is_file():
            path.chmod(0o444)


def release_layout(release_dir: Path, *, architecture: str) -> ReleaseLayout:
    root = release_dir.expanduser().resolve()
    if architecture not in {"amd64", "arm64"}:
        raise WorkflowError("Release architecture must be amd64 or arm64.")
    platform_dir = root / architecture
    core_archive = platform_dir / f"datariver-core-{architecture}.tar"
    checksum_file = platform_dir / f"datariver-core-{architecture}.tar.sha256"
    offline_compose = platform_dir / "offline-core.compose.yaml"
    source_commit_file = root / "source-commit.txt"
    for path, label in (
        (core_archive, "Core image archive"),
        (checksum_file, "Core image checksum"),
        (offline_compose, "Offline Compose override"),
        (source_commit_file, "Release source-commit marker"),
    ):
        require_regular_file(path, label=label)
    return ReleaseLayout(
        root=root,
        platform_dir=platform_dir,
        core_archive=core_archive,
        checksum_file=checksum_file,
        checksum_cwd=platform_dir,
        offline_compose=offline_compose,
        source_commit_file=source_commit_file,
    )


def release_optional_compose(
    layout: ReleaseLayout,
    filename: str,
    *,
    required: bool = False,
) -> Path | None:
    if filename not in OPTIONAL_RELEASE_COMPOSE_FILES:
        raise WorkflowError("Unsupported optional release Compose filename.")
    path = layout.platform_dir / filename
    if path.is_file() and not path.is_symlink():
        return path.resolve()
    if required:
        raise WorkflowError(
            f"The selected offline topology requires a release containing {filename}."
        )
    return None


def state_path(root: Path, profile: str) -> Path:
    workflow_profile(profile)
    return root / "runtime" / "operator-workflow" / f"{profile}.json"


def write_applied_state(path: Path, state: AppliedState) -> None:
    state.validate()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    _atomic_write(
        path,
        json.dumps(asdict(state), indent=2, sort_keys=True) + "\n",
        mode=0o600,
    )


def load_applied_state(path: Path) -> AppliedState:
    require_regular_file(path, label="Applied workflow state")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise WorkflowError("The applied workflow state is not valid JSON.") from error
    if not isinstance(payload, dict):
        raise WorkflowError("The applied workflow state must be an object.")
    expected = {field.name for field in fields(AppliedState)}
    optional_legacy_fields = {"environment_key_hashes"}
    if set(payload) - expected or expected - set(payload) - optional_legacy_fields:
        raise WorkflowError("The applied workflow state has missing or unknown fields.")
    payload.setdefault("environment_key_hashes", {})
    try:
        state = AppliedState(**payload)
    except TypeError as error:
        raise WorkflowError("The applied workflow state has invalid values.") from error
    state.validate()
    return state


def classify_changes(paths: Sequence[str]) -> ChangePlan:
    services: set[str] = set()
    requires_migration = False
    configure_keycloak = False
    restart_datahub = False
    restart_airflow = False
    restart_gateway = False
    restart_graph = False
    local_connector_services: set[str] = set()
    meaningful = False
    operator_only_scripts = {
        "scripts/platform_workflow.py",
        "scripts/workflow_fresh_setup.py",
        "scripts/workflow_source_host_infra.py",
        "scripts/workflow_update_restart.py",
        "scripts/verify_static.py",
    }

    for path in paths:
        normalized = path.strip().lstrip("./")
        if not normalized:
            continue
        if normalized in operator_only_scripts:
            continue
        if normalized.startswith(("docs/", "backend/tests/", "frontend/src/")):
            if normalized.startswith("frontend/src/"):
                meaningful = True
                services.add("web")
            continue
        if normalized.startswith("frontend/"):
            meaningful = True
            services.add("web")
            continue
        if normalized.startswith("backend/"):
            meaningful = True
            services.update(BACKEND_RUNTIME_SERVICES)
            requires_migration = requires_migration or normalized.startswith(
                ("backend/alembic/", "backend/src/datariver/infrastructure/db/")
            )
            continue
        if normalized.startswith("infra/keycloak/") or normalized == "compose.identity.yaml":
            meaningful = True
            services.update(("api", "keycloak"))
            configure_keycloak = True
            continue
        if normalized.startswith("infra/datahub/") or normalized == (
            "scripts/start_datahub_mac_dev.sh"
        ):
            meaningful = True
            restart_datahub = True
            continue
        if normalized.startswith("infra/postgres/"):
            meaningful = True
            services.update(BACKEND_RUNTIME_SERVICES)
            requires_migration = True
            continue
        if normalized.startswith("infra/airflow/") or normalized.startswith("compose.airflow"):
            meaningful = True
            restart_airflow = True
            continue
        if normalized.startswith("infra/apisix/") or normalized == "compose.gateway.yaml":
            meaningful = True
            restart_gateway = True
            continue
        if normalized.startswith("infra/neo4j/") or normalized == "compose.graph.yaml":
            meaningful = True
            restart_graph = True
            services.add("api")
            continue
        if normalized == "compose.local-connectors.yaml":
            meaningful = True
            local_connector_services.update(LOCAL_CONNECTOR_SERVICES)
            continue
        if normalized.startswith(("README", "AGENTS.md", ".github/")):
            continue
        meaningful = True
        services.update(RUNTIME_SERVICES)
        requires_migration = True
        configure_keycloak = True
        restart_datahub = True
        restart_airflow = True
        restart_gateway = True
        restart_graph = True
        local_connector_services.update(LOCAL_CONNECTOR_SERVICES)

    if not meaningful:
        services.clear()
    return ChangePlan(
        services=tuple(service for service in RUNTIME_SERVICES if service in services),
        requires_migration=requires_migration,
        configure_keycloak=configure_keycloak,
        restart_datahub=restart_datahub,
        restart_airflow=restart_airflow,
        restart_gateway=restart_gateway,
        restart_graph=restart_graph,
        local_connector_services=tuple(
            service for service in LOCAL_CONNECTOR_SERVICES if service in local_connector_services
        ),
    )


def requires_local_identity_bootstrap(
    paths: Sequence[str],
    *,
    profile: str,
) -> bool:
    """Reapply the Mac-only local identity projection when its source contract changes."""

    return profile == "mac-development" and any(
        path.strip().lstrip("./") == "backend/src/datariver/bootstrap.py" for path in paths
    )


def classify_environment_changes(
    keys: Sequence[str], *, reject_unknown: bool = False
) -> ChangePlan:
    """Map changed deployment settings to only their runtime consumers."""

    services: set[str] = set()
    configure_keycloak = False
    restart_airflow = False
    restart_gateway = False
    restart_graph = False
    local_connector_services: set[str] = set()
    for raw_key in keys:
        key = raw_key.strip()
        if not _ENV_KEY.fullmatch(key):
            raise WorkflowError("An environment change contains an invalid key.")
        if key in {
            "DATARIVER_ENV_FILE",
            "POSTGRES_DB",
            "POSTGRES_USER",
            "MIGRATION_DATABASE_URL",
            "MIGRATION_DATABASE_SECRET_REF",
            "BOOTSTRAP_DATABASE_URL",
            "BOOTSTRAP_DATABASE_SECRET_REF",
            "EVENT_RETENTION_DAYS",
            "SEED_PROFILE",
            "DATARIVER_CATALOG_SYNC_MAX_PAGES",
            "INTRANET_SOURCE_HOST_ENABLED",
        }:
            # These values are consumed by a one-shot operator command, an
            # immutable bootstrap boundary, or a future retention operation.
            # No long-running process reads them after startup.
            pass
        elif key in {
            "APP_ENV",
            "APP_NAME",
            "APP_LOG_LEVEL",
            "DEPLOYMENT_TIER",
            "DEPLOYMENT_EVIDENCE_REFERENCE",
        }:
            services.update(BACKEND_RUNTIME_SERVICES)
        elif key == "APP_PUBLIC_ORIGIN":
            services.update(("api", "web", "keycloak"))
            configure_keycloak = True
            local_connector_services.add("minio")
        elif key in {"APP_CORS_ORIGINS", "APP_TRUSTED_HOSTS"}:
            services.add("api")
        elif key in {
            "WORKSPACE_SELECTION_ENABLED",
            "HIGH_RISK_AUTH_MAX_AGE_SECONDS",
            "CHAT_EPHEMERAL_ADMIN_WITHOUT_RETENTION_ENABLED",
            "CHAT_RATE_LIMIT_REQUESTS_PER_MINUTE",
            "CHAT_RATE_LIMIT_TOKENS_PER_MINUTE",
            "CHAT_COMPOSITION_PROVIDER_PROFILE_VERSION_ID",
            "CHAT_EMBEDDING_PROVIDER_PROFILE_VERSION_ID",
            "CHAT_RERANKER_PROVIDER_PROFILE_VERSION_ID",
            "PRESIGNED_URL_TTL_SECONDS",
        }:
            services.add("api")
        elif key.startswith(("CACHE_", "CATALOG_SEARCH_")):
            services.add("api")
        elif key == "CATALOG_EXPORT_WORKER_ENABLED":
            services.update(("api", "catalog-export-worker"))
        elif key in {
            "CATALOG_EXPORT_ACCESS_TTL_SECONDS",
            "CATALOG_EXPORT_DOWNLOAD_TTL_SECONDS",
        }:
            services.add("api")
        elif key in {
            "CATALOG_EXPORT_LEASE_SECONDS",
            "CATALOG_EXPORT_MAXIMUM_ATTEMPTS",
            "CATALOG_EXPORT_MAXIMUM_BYTES",
            "CATALOG_EXPORT_MAXIMUM_ROWS",
            "CATALOG_EXPORT_PAGE_SIZE",
            "EXPORT_WORKER_SUBJECT_ID",
        }:
            services.add("catalog-export-worker")
        elif key.startswith("GOVERNANCE_APPLY_") or key == "GOVERNANCE_WORKER_SUBJECT_ID":
            services.update(("api", "governance-apply-worker"))
        elif key in {"OUTBOX_LEASE_SECONDS", "OUTBOX_MAXIMUM_ATTEMPTS"}:
            services.add("outbox-relay")
        elif key in {
            "UPLOAD_LEASE_SECONDS",
            "UPLOAD_MAXIMUM_ATTEMPTS",
        }:
            services.add("upload-worker")
        elif key == "WORKER_POLL_SECONDS":
            services.update(
                (
                    "outbox-relay",
                    "upload-worker",
                    "upload-validation-worker",
                    "governance-apply-worker",
                    "catalog-export-worker",
                    "retention-scheduler",
                    "retention-archive-worker",
                )
            )
        elif key == "KNOWLEDGE_WORKER_SUBJECT_ID":
            services.add("knowledge-source-worker")
        elif key == "RETENTION_WORKER_SUBJECT_ID":
            services.add("retention-scheduler")
        elif key.startswith("UPLOAD_VALIDATION_"):
            services.add("upload-validation-worker")
        elif key.startswith("BULK_PREPARATION_"):
            services.add("api")
        elif key in {
            "OIDC_PUBLIC_AUTHORITY",
            "OIDC_CLIENT_ID",
            "OIDC_STEP_UP_ACR",
            "OIDC_PASSWORD_REAUTH_REQUEST_ACR",
        }:
            services.add("web")
        elif key == "OIDC_PUBLIC_ORIGIN":
            services.update(("web", "keycloak"))
            configure_keycloak = True
        elif key.startswith(("OIDC_", "IDENTITY_", "ADMIN_PASSWORD_")) or key == (
            "DEVELOPMENT_ADMIN_PASSWORD_BYPASS_ENABLED"
        ):
            services.add("api")
        elif key.startswith(("UI_", "DATAHUB_EMBED_", "GRAFANA_EMBED_")):
            services.update(("api", "web"))
        elif key.startswith(
            (
                "LOCAL_OLLAMA_CHAT_",
                "LOCAL_LLAMA_CPP_RERANKER_",
                "INTRANET_OPENAI_COMPATIBLE_CHAT_",
            )
        ):
            services.add("api")
        elif key == "LOCAL_INFERENCE_SOURCE_HOST_ENABLED":
            services.update(("api", "knowledge-source-worker"))
        elif key.startswith(
            (
                "LOCAL_OLLAMA_EMBEDDING_",
                "INTRANET_OPENAI_COMPATIBLE_EMBEDDING_",
            )
        ):
            services.update(("api", "knowledge-source-worker"))
        elif key == "INTRANET_OPENAI_COMPATIBLE_ALLOWED_HOSTS":
            services.update(("api", "knowledge-source-worker"))
        elif key == "SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS":
            services.add("api")
        elif key == "SYSTEM_CONFIGURATION_SECRET_ROOT":
            services.update(BACKEND_RUNTIME_SERVICES)
        elif key.startswith(("NEO4J_", "KNOWLEDGE_")):
            services.update(("api", "knowledge-source-worker"))
            restart_graph = key in {
                "NEO4J_HTTP_PORT",
                "NEO4J_BOLT_PORT",
                "NEO4J_IMAGE",
            }
        elif key.startswith("DATAHUB_"):
            services.update(BACKEND_RUNTIME_SERVICES)
        elif key == "S3_PUBLIC_ORIGIN":
            services.add("web")
        elif key.startswith(("MINIO_",)):
            local_connector_services.add("minio")
        elif key.startswith("S3_ARCHIVE_"):
            services.update(("retention-scheduler", "retention-archive-worker"))
        elif key.startswith("S3_EXPORT_"):
            services.add("catalog-export-worker")
        elif key.startswith("S3_KNOWLEDGE_"):
            services.add("knowledge-source-worker")
        elif key.startswith("S3_"):
            services.update(BACKEND_RUNTIME_SERVICES)
        elif key in {"REDIS_CACHE_PORT", "REDIS_DELIVERY_PORT", "REDIS_IMAGE"}:
            local_connector_services.update(("redis-cache", "redis-delivery"))
        elif key.startswith("REDIS_"):
            services.update(BACKEND_RUNTIME_SERVICES)
        elif key.startswith("AIRFLOW_"):
            services.add("api")
            restart_airflow = True
        elif key == "DATARIVER_CONNECTOR_NETWORK":
            services.update(RUNTIME_SERVICES)
            local_connector_services.update(LOCAL_CONNECTOR_SERVICES)
            restart_airflow = True
            restart_graph = True
        elif key in {"APISIX_PORT", "DATARIVER_API_UPSTREAM"}:
            restart_gateway = True
        elif key == "DATARIVER_API_BASE_URL":
            restart_airflow = True
        elif key.startswith("RETENTION_SCHEDULER_DATABASE_"):
            services.add("retention-scheduler")
        elif key.startswith("ARCHIVE_DATABASE_"):
            services.add("retention-archive-worker")
        elif key.startswith("RETENTION_"):
            services.update(("retention-scheduler", "retention-archive-worker"))
        elif key.startswith(
            (
                "DATABASE_",
                "MIGRATION_DATABASE_",
                "RELAY_DATABASE_",
                "UPLOAD_DATABASE_",
                "GOVERNANCE_DATABASE_",
                "KNOWLEDGE_DATABASE_",
                "EXPORT_DATABASE_",
                "ARCHIVE_DATABASE_",
                "BOOTSTRAP_DATABASE_",
                "WORKER_DATABASE_",
            )
        ):
            services.update(BACKEND_RUNTIME_SERVICES)
        elif key in {"WEB_PORT"}:
            services.add("web")
        elif key in {"API_PORT"}:
            services.add("api")
        else:
            if reject_unknown:
                raise WorkflowError(
                    f"Environment key {key} has no explicit consumer classification."
                )
            # Unknown deployment settings fail safe by recreating all runtime
            # consumers, but never infer a database migration.
            services.update(RUNTIME_SERVICES)
    return ChangePlan(
        services=tuple(service for service in RUNTIME_SERVICES if service in services),
        requires_migration=False,
        configure_keycloak=configure_keycloak,
        restart_datahub=False,
        restart_airflow=restart_airflow,
        restart_gateway=restart_gateway,
        restart_graph=restart_graph,
        local_connector_services=tuple(
            service for service in LOCAL_CONNECTOR_SERVICES if service in local_connector_services
        ),
    )


def merge_change_plans(*plans: ChangePlan) -> ChangePlan:
    services = {service for plan in plans for service in plan.services}
    connector_services = {service for plan in plans for service in plan.local_connector_services}
    return ChangePlan(
        services=tuple(service for service in RUNTIME_SERVICES if service in services),
        requires_migration=any(plan.requires_migration for plan in plans),
        configure_keycloak=any(plan.configure_keycloak for plan in plans),
        restart_datahub=any(plan.restart_datahub for plan in plans),
        restart_airflow=any(plan.restart_airflow for plan in plans),
        restart_gateway=any(plan.restart_gateway for plan in plans),
        restart_graph=any(plan.restart_graph for plan in plans),
        local_connector_services=tuple(
            service for service in LOCAL_CONNECTOR_SERVICES if service in connector_services
        ),
    )


def current_commit(runner: Runner) -> str:
    value = runner.output(("git", "rev-parse", "--verify", "HEAD"))
    if not _COMMIT.fullmatch(value):
        raise WorkflowError("Git did not return one full commit ID.")
    return value


def require_clean_worktree(runner: Runner) -> None:
    status = runner.output(("git", "status", "--porcelain", "--untracked-files=normal"))
    if status:
        raise WorkflowError(
            "The source worktree is not clean. Commit or preserve local work before this workflow."
        )


def incompatible_release_paths(paths: Sequence[str]) -> tuple[str, ...]:
    """Return checkout paths that can change the immutable release runtime contract."""

    allowed_exact = {
        "README.md",
        "scripts/platform_workflow.py",
        "scripts/workflow_fresh_setup.py",
        "scripts/workflow_update_restart.py",
    }
    allowed_prefixes = ("docs/", "backend/tests/")
    incompatible: list[str] = []
    for path in paths:
        normalized = path.strip().lstrip("./")
        if not normalized:
            continue
        if normalized in allowed_exact or normalized.startswith(allowed_prefixes):
            continue
        incompatible.append(normalized)
    return tuple(incompatible)


def select_restart_services(
    affected_services: Sequence[str],
    *,
    running_services: Sequence[str],
) -> tuple[str, ...]:
    """Keep required runtime services, without accidentally enabling optional workers."""

    affected = set(affected_services)
    running = set(running_services)
    selected = {
        service for service in affected if service in DEFAULT_RUNTIME_SERVICES or service in running
    }
    return tuple(service for service in RUNTIME_SERVICES if service in selected)


def require_release_compatible_checkout(
    runner: Runner,
    *,
    release_commit: str,
    checkout_commit: str,
) -> tuple[str, ...]:
    """Permit newer operator docs/tools while refusing stale runtime images."""

    if not _COMMIT.fullmatch(release_commit) or not _COMMIT.fullmatch(checkout_commit):
        raise WorkflowError("Release compatibility requires full Git commit IDs.")
    if release_commit == checkout_commit:
        return ()
    try:
        runner.run(("git", "merge-base", "--is-ancestor", release_commit, checkout_commit))
    except WorkflowError as error:
        raise WorkflowError(
            "The immutable release commit is not an ancestor of the checked-out source."
        ) from error
    paths = tuple(
        line
        for line in runner.output(
            ("git", "diff", "--name-only", f"{release_commit}..{checkout_commit}")
        ).splitlines()
        if line
    )
    incompatible = incompatible_release_paths(paths)
    if incompatible:
        rendered = "\n  - ".join(incompatible)
        raise WorkflowError(
            "The checked-out runtime differs from the immutable image release. "
            "Build and transfer a release for the current runtime commit before restarting:\n"
            f"  - {rendered}"
        )
    return paths


def compose_arguments(
    *,
    env_file: Path,
    compose_files: Sequence[Path],
    trailing: Sequence[str],
    profiles: Sequence[str] = (),
) -> list[str]:
    arguments = [os.fspath(ROOT / "scripts" / "compose.sh"), "--env-file", os.fspath(env_file)]
    for profile in profiles:
        arguments.extend(("--profile", profile))
    for compose_file in compose_files:
        arguments.extend(("-f", os.fspath(compose_file)))
    arguments.extend(trailing)
    return arguments


def _atomic_write(path: Path, content: str, *, mode: int) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
