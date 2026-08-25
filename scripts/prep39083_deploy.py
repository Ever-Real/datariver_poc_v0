#!/usr/bin/env python3
"""One-command PREP39083 source deployment above the immutable release tools."""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import platform
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, NoReturn

from prep39083_release import ReleaseError, source_contract

ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT = ROOT / "deploy" / "prep39083"
BASE_COMPOSE = ROOT / "deploy" / "poc" / "docker-compose.poc.yaml"
OPERATOR_ENV = DEPLOYMENT / ".env.prep"
OPTIONAL_ENV = DEPLOYMENT / ".env.prep.optional"
RUNTIME_ENV = DEPLOYMENT / ".env.prep.runtime"
ENV_CONTRACT = DEPLOYMENT / "env-contract.json"
RELEASE_IDENTITY = DEPLOYMENT / "release.json"
SMOKE_TOOL = ROOT / "scripts" / "smoke_prep39083.mjs"
RELEASE_TOOL = ROOT / "scripts" / "prep39083_release.py"
RUNTIME_ROOT = ROOT / "runtime" / "prep39083"
ACCEPTED_MARKER = RUNTIME_ROOT / "accepted.json"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
CHANGE_ME_PREFIX = "CHANGE_ME"
INSPECTION_PLACEHOLDER = "prep-inspection-only-not-persisted"


class PrepError(RuntimeError):
    """One sanitized, operator-correctable PREP deployment failure."""

    def __init__(self, step: str, code: str, reason: str, action: str) -> None:
        super().__init__(reason)
        self.step = step
        self.code = code
        self.reason = reason
        self.action = action


class CommandFailure(RuntimeError):
    """Private command failure; captured output is never emitted automatically."""

    def __init__(
        self,
        arguments: Sequence[str],
        completed: subprocess.CompletedProcess[str],
    ) -> None:
        super().__init__(f"command failed with exit code {completed.returncode}")
        self.arguments = tuple(arguments)
        self.returncode = completed.returncode
        self.stdout = completed.stdout
        self.stderr = completed.stderr


class Runner:
    def __init__(self, *, environment: Mapping[str, str] | None = None) -> None:
        self.environment = dict(environment or os.environ)
        self.step = 0

    def note(self, message: str) -> None:
        self.step += 1
        print(f"[{self.step:02d}] {message}", flush=True)

    def run(
        self,
        arguments: Sequence[str | os.PathLike[str]],
        *,
        check: bool = True,
        cwd: Path = ROOT,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [os.fspath(value) for value in arguments]
        completed = subprocess.run(  # noqa: S603 - argv only, no shell interpolation.
            command,
            cwd=cwd,
            env=self.environment,
            check=False,
            capture_output=True,
            text=True,
            input=input_text,
        )
        if check and completed.returncode != 0:
            raise CommandFailure(command, completed)
        return completed

    def output(self, arguments: Sequence[str | os.PathLike[str]]) -> str:
        return self.run(arguments).stdout.strip()


@dataclass(frozen=True)
class ReleaseIdentity:
    product_sha: str
    evidence_sha: str
    platform: str
    port: int
    project: str


class TargetState(str, Enum):
    FRESH_CLEAN = "FRESH_CLEAN"
    EXISTING_ACCEPTED_RUNNING = "EXISTING_ACCEPTED_RUNNING"
    EXISTING_ACCEPTED_STOPPED = "EXISTING_ACCEPTED_STOPPED"
    FAILED_FIRST_INSTALL_REQUIRES_INSPECTION = "FAILED_FIRST_INSTALL_REQUIRES_INSPECTION"
    FAILED_FIRST_INSTALL_RECOVERABLE = "FAILED_FIRST_INSTALL_RECOVERABLE"
    EXISTING_STATE_AMBIGUOUS = "EXISTING_STATE_AMBIGUOUS"


@dataclass(frozen=True)
class TargetContainer:
    identifier: str
    service: str
    running: bool


@dataclass(frozen=True)
class TargetVolume:
    name: str
    logical_name: str


@dataclass(frozen=True)
class TargetInventory:
    accepted_marker_present: bool
    accepted_marker_valid: bool
    runtime_env_present: bool
    runtime_env_valid: bool
    containers: tuple[TargetContainer, ...]
    volumes: tuple[TargetVolume, ...]
    networks: tuple[str, ...]

    @property
    def running(self) -> bool:
        return any(container.running for container in self.containers)

    @property
    def volume_names(self) -> set[str]:
        return {volume.logical_name for volume in self.volumes}


@dataclass(frozen=True)
class EnvironmentBundle:
    operator: Mapping[str, str]
    optional: Mapping[str, str]
    runtime: Mapping[str, str]
    effective: Mapping[str, str]
    warnings: tuple[str, ...]
    target_state: TargetState
    k9_mode: str


@dataclass(frozen=True)
class DeploymentPreparation:
    runner: Runner
    source: Mapping[str, str]
    inventory: TargetInventory
    before_39080: tuple[str, ...]


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PrepError(
            "RELEASE_ENVIRONMENT",
            "PREP_TRACKED_CONTRACT_INVALID",
            f"The tracked {label} cannot be read.",
            "Restore the exact origin/dev tracked deployment files and retry.",
        ) from error
    if not isinstance(value, dict):
        raise PrepError(
            "RELEASE_ENVIRONMENT",
            "PREP_TRACKED_CONTRACT_INVALID",
            f"The tracked {label} is not an object.",
            "Restore the exact origin/dev tracked deployment files and retry.",
        )
    return value


def load_release_identity(path: Path = RELEASE_IDENTITY) -> ReleaseIdentity:
    value = _read_json(path, "release identity")
    product_sha = value.get("product_sha")
    evidence_sha = value.get("evidence_sha")
    if not isinstance(product_sha, str) or not SHA_PATTERN.fullmatch(product_sha):
        raise PrepError(
            "RELEASE_IDENTITY",
            "PREP_PRODUCT_IDENTITY_INVALID",
            "The tracked Product identity is invalid.",
            "Pull the accepted origin/dev handoff and retry.",
        )
    if not isinstance(evidence_sha, str) or not SHA_PATTERN.fullmatch(evidence_sha):
        raise PrepError(
            "RELEASE_IDENTITY",
            "PREP_EVIDENCE_IDENTITY_INVALID",
            "The tracked Evidence identity is invalid.",
            "Pull the accepted origin/dev handoff and retry.",
        )
    if value.get("handoff_commit_policy") != "CURRENT_COMMITTED_HEAD":
        raise PrepError(
            "RELEASE_IDENTITY",
            "PREP_HANDOFF_POLICY_INVALID",
            "The tracked handoff policy is invalid.",
            "Restore deploy/prep39083/release.json from origin/dev.",
        )
    if value.get("platform") != "linux/amd64" or value.get("project") != "datariver-prep39083":
        raise PrepError(
            "RELEASE_IDENTITY",
            "PREP_PLATFORM_IDENTITY_INVALID",
            "The tracked PREP platform or project identity is invalid.",
            "Restore deploy/prep39083/release.json from origin/dev.",
        )
    port = value.get("port")
    if port != 39083:
        raise PrepError(
            "RELEASE_IDENTITY",
            "PREP_PORT_IDENTITY_INVALID",
            "The tracked PREP port is not 39083.",
            "Restore deploy/prep39083/release.json from origin/dev.",
        )
    return ReleaseIdentity(product_sha, evidence_sha, "linux/amd64", port, value["project"])


def _private_regular_file(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise PrepError(
            "ENVIRONMENT",
            "PREP_OPERATOR_ENV_MISSING",
            f"{label} is absent.",
            "Copy .env.prep.example to .env.prep, chmod 0600, and set required keys.",
        ) from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise PrepError(
            "ENVIRONMENT",
            "PREP_ENV_FILE_UNSAFE",
            f"{label} must be one regular non-symlink file.",
            "Replace it with a target-owned regular file.",
        )
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise PrepError(
            "ENVIRONMENT",
            "PREP_ENV_FILE_PERMISSIONS",
            f"{label} must use mode 0600 or stricter.",
            f"Run: chmod 0600 {path.relative_to(ROOT)}",
        )


def read_env_file(path: Path, *, private: bool, label: str) -> dict[str, str]:
    if private:
        _private_regular_file(path, label)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise PrepError(
            "ENVIRONMENT",
            "PREP_ENV_FILE_UNREADABLE",
            f"{label} cannot be read.",
            "Correct its ownership and permissions, then retry.",
        ) from error
    values: dict[str, str] = {}
    for raw_line in lines:
        if not raw_line or raw_line.lstrip().startswith("#") or "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        if not ENV_KEY.fullmatch(key):
            raise PrepError(
                "ENVIRONMENT",
                "PREP_ENV_KEY_INVALID",
                f"{label} contains an invalid key name.",
                "Use KEY=value entries with portable environment key names.",
            )
        if key in values:
            raise PrepError(
                "ENVIRONMENT",
                "PREP_ENV_KEY_DUPLICATED",
                f"{label} contains duplicate key {key}.",
                f"Keep exactly one {key}= entry.",
            )
        values[key] = value.rstrip("\r")
    return values


def _atomic_private_env(path: Path, values: Mapping[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    for key, value in values.items():
        if not ENV_KEY.fullmatch(key) or "\n" in value or "\r" in value:
            raise ValueError("invalid generated environment entry")
    payload = "# Generated by ./scripts/prep39083; do not edit or commit.\n" + "".join(
        f"{key}={value}\n" for key, value in sorted(values.items())
    )
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def _token(byte_count: int) -> str:
    return secrets.token_urlsafe(byte_count)


def merge_no_proxy(operator_value: str, required: Sequence[str], external: str = "") -> str:
    values: list[str] = []
    seen: set[str] = set()
    for raw in (*operator_value.split(","), *external.split(","), *required):
        value = raw.strip()
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            values.append(value)
    return ",".join(values)


def _optional_keys() -> set[str]:
    return set(read_env_file(
        DEPLOYMENT / ".env.prep.optional.example",
        private=False,
        label="optional environment template",
    ))


def _accepted_marker_valid(path: Path) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(
        isinstance(value, dict)
        and value.get("contract") == "DATARIVER_PREP39083_ACCEPTED_V1"
        and all(
            isinstance(value.get(key), str) and SHA_PATTERN.fullmatch(value[key])
            for key in ("product_sha", "evidence_sha", "handoff_commit")
        )
    )


def _runtime_env_valid(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        values = read_env_file(path, private=True, label=".env.prep.runtime")
    except PrepError:
        return False
    return all(values.get(key, "").strip() for key in (
        "POC_POSTGRES_PASSWORD",
        "NEO4J_PASSWORD",
        "POC_MCP_SERVICE_TOKEN",
    ))


def inspect_target_inventory(
    runner: Runner,
    release: ReleaseIdentity,
    *,
    runtime_path: Path = RUNTIME_ENV,
    accepted_marker_path: Path = ACCEPTED_MARKER,
) -> TargetInventory:
    containers: list[TargetContainer] = []
    for line in runner.output([
        "docker", "ps", "--all",
        "--filter", f"label=com.docker.compose.project={release.project}",
        "--format", '{{.ID}}\t{{.State}}\t{{.Label "com.docker.compose.service"}}',
    ]).splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0] and parts[2]:
            containers.append(TargetContainer(parts[0], parts[2], parts[1] == "running"))
    volumes: list[TargetVolume] = []
    for line in runner.output([
        "docker", "volume", "ls",
        "--filter", f"label=com.docker.compose.project={release.project}",
        "--format", '{{.Name}}\t{{.Label "com.docker.compose.volume"}}',
    ]).splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and parts[0] and parts[1]:
            volumes.append(TargetVolume(parts[0], parts[1]))
    networks = tuple(sorted(filter(None, runner.output([
        "docker", "network", "ls",
        "--filter", f"label=com.docker.compose.project={release.project}",
        "--format", "{{.Name}}",
    ]).splitlines())))
    return TargetInventory(
        accepted_marker_path.exists(),
        _accepted_marker_valid(accepted_marker_path),
        runtime_path.exists(),
        _runtime_env_valid(runtime_path),
        tuple(sorted(containers, key=lambda item: (item.service, item.identifier))),
        tuple(sorted(volumes, key=lambda item: (item.logical_name, item.name))),
        networks,
    )


def classify_target_state(inventory: TargetInventory) -> TargetState:
    required_accepted_volumes = {"pgvector-data", "neo4j-data"}
    allowed_services = {"web", "pgvector", "neo4j", "redis"}
    allowed_volumes = {"pgvector-data", "neo4j-data", "neo4j-logs"}
    logical_volumes = [volume.logical_name for volume in inventory.volumes]
    if (
        {container.service for container in inventory.containers} - allowed_services
        or set(logical_volumes) - allowed_volumes
        or len(logical_volumes) != len(set(logical_volumes))
        or len(inventory.networks) > 1
    ):
        return TargetState.EXISTING_STATE_AMBIGUOUS
    if inventory.accepted_marker_present:
        if (
            inventory.accepted_marker_valid
            and inventory.runtime_env_valid
            and required_accepted_volumes <= inventory.volume_names
        ):
            return (
                TargetState.EXISTING_ACCEPTED_RUNNING
                if inventory.running
                else TargetState.EXISTING_ACCEPTED_STOPPED
            )
        return TargetState.EXISTING_STATE_AMBIGUOUS
    if not any((
        inventory.runtime_env_present,
        inventory.containers,
        inventory.volumes,
        inventory.networks,
    )):
        return TargetState.FRESH_CLEAN
    return TargetState.FAILED_FIRST_INSTALL_REQUIRES_INSPECTION


def _environment_ownership(contract: Mapping[str, Any]) -> tuple[
    tuple[str, ...], dict[str, Any], tuple[str, ...], dict[str, Any], dict[str, Any]
]:
    ownership = contract.get("ownership")
    if not isinstance(ownership, dict):
        raise PrepError(
            "ENVIRONMENT",
            "PREP_ENV_CONTRACT_INVALID",
            "The tracked environment ownership contract is invalid.",
            "Restore deploy/prep39083/env-contract.json from origin/dev.",
        )
    core = ownership.get("CORE_REQUIRED")
    features = ownership.get("FEATURE_REQUIRED")
    optional = ownership.get("OPTIONAL")
    generated = ownership.get("GENERATED")
    fixed = ownership.get("FIXED")
    if (
        not isinstance(core, list)
        or not isinstance(features, dict)
        or not isinstance(optional, list)
        or not isinstance(generated, dict)
        or not isinstance(fixed, dict)
    ):
        raise PrepError(
            "ENVIRONMENT",
            "PREP_ENV_CONTRACT_INVALID",
            "The tracked environment ownership categories are invalid.",
            "Restore deploy/prep39083/env-contract.json from origin/dev.",
        )
    return tuple(map(str, core)), features, tuple(map(str, optional)), generated, fixed


def _feature_keys(features: Mapping[str, Any]) -> set[str]:
    keys: set[str] = set()
    for value in features.values():
        if not isinstance(value, dict) or not isinstance(value.get("keys"), list):
            raise PrepError(
                "ENVIRONMENT",
                "PREP_ENV_CONTRACT_INVALID",
                "One feature-dependent environment contract is invalid.",
                "Restore deploy/prep39083/env-contract.json from origin/dev.",
            )
        keys.update(map(str, value["keys"]))
    return keys


def reconcile_environment(
    release: ReleaseIdentity,
    *,
    operator_path: Path = OPERATOR_ENV,
    optional_path: Path = OPTIONAL_ENV,
    runtime_path: Path = RUNTIME_ENV,
    random_token: Callable[[int], str] = _token,
    target_state: TargetState = TargetState.FRESH_CLEAN,
) -> EnvironmentBundle:
    contract = _read_json(ENV_CONTRACT, "environment contract")
    if contract.get("contract") != "DATARIVER_PREP39083_ENV_V3":
        raise PrepError(
            "ENVIRONMENT",
            "PREP_ENV_CONTRACT_INVALID",
            "The tracked environment contract version is invalid.",
            "Restore deploy/prep39083/env-contract.json from origin/dev.",
        )
    if target_state is TargetState.EXISTING_STATE_AMBIGUOUS:
        raise PrepError(
            "TARGET_STATE",
            "PREP_EXISTING_STATE_REQUIRES_OPERATOR_RECOVERY",
            "Existing PREP state cannot be proven fresh, accepted, or disposable.",
            "Preserve all volumes and runtime files; inspect doctor output before "
            "approved recovery.",
        )
    operator = read_env_file(operator_path, private=True, label=".env.prep")
    optional = (
        read_env_file(optional_path, private=True, label=".env.prep.optional")
        if optional_path.exists()
        else {}
    )
    required, features, operator_optional, generated_specification, fixed = (
        _environment_ownership(contract)
    )
    missing = sorted(
        key for key in required
        if not operator.get(key, "").strip()
        or operator.get(key, "").strip().startswith(CHANGE_ME_PREFIX)
    )
    if missing:
        raise PrepError(
            "ENVIRONMENT",
            "PREP_REQUIRED_EXTERNAL_CONFIG_MISSING",
            f"Required operator keys are missing: {', '.join(missing)}.",
            "Set only those keys in deploy/prep39083/.env.prep and rerun deploy.",
        )
    feature_keys = _feature_keys(features)
    allowed_operator = set(required) | set(operator_optional) | feature_keys
    optional_keys = _optional_keys()
    unexpected_optional = sorted(set(optional) - optional_keys)
    if unexpected_optional:
        raise PrepError(
            "ENVIRONMENT",
            "PREP_OPTIONAL_ENV_KEY_UNKNOWN",
            f"Optional profile contains unknown keys: {', '.join(unexpected_optional)}.",
            "Move only documented optional keys into .env.prep.optional.",
        )
    overlap = sorted(set(operator) & set(optional))
    if overlap:
        raise PrepError(
            "ENVIRONMENT",
            "PREP_ENV_OWNERSHIP_CONFLICT",
            f"Keys occur in both operator and optional environments: {', '.join(overlap)}.",
            "Keep every key in exactly one target-owned file.",
        )

    runtime = (
        read_env_file(runtime_path, private=True, label=".env.prep.runtime")
        if runtime_path.exists()
        else {}
    )
    warnings: list[str] = []
    allow_generation = target_state in {
        TargetState.FRESH_CLEAN,
        TargetState.FAILED_FIRST_INSTALL_RECOVERABLE,
    }
    for key, raw_byte_count in generated_specification.items():
        byte_count = int(raw_byte_count)
        legacy = operator.get(key, "")
        if not runtime.get(key):
            if legacy and not legacy.startswith(CHANGE_ME_PREFIX):
                runtime[key] = legacy
            elif allow_generation:
                runtime[key] = random_token(byte_count)
            elif target_state is TargetState.FAILED_FIRST_INSTALL_REQUIRES_INSPECTION:
                runtime[key] = INSPECTION_PLACEHOLDER
            else:
                raise PrepError(
                    "TARGET_STATE",
                    "PREP_EXISTING_STATE_REQUIRES_OPERATOR_RECOVERY",
                    f"Accepted PREP state has no recoverable target-local value for {key}.",
                    "Restore the ignored runtime environment or its matching legacy value; "
                    "do not reset persistent volumes.",
                )
        elif legacy and not legacy.startswith(CHANGE_ME_PREFIX) and legacy != runtime[key]:
            raise PrepError(
                "ENVIRONMENT",
                "PREP_GENERATED_VALUE_DRIFT",
                f"Legacy operator key {key} conflicts with its preserved runtime value.",
                f"Remove legacy {key} from .env.prep or restore the matching accepted value.",
            )
        if legacy:
            warnings.append(f"legacy generated key remains in .env.prep: {key}")

    studio_database_url = operator.get("POC_K9_STUDIO_DATABASE_URL", "").strip()
    k9_configured = bool(
        studio_database_url and not studio_database_url.startswith(CHANGE_ME_PREFIX)
    )
    for key, value in fixed.items():
        runtime[str(key)] = str(value)
    runtime["POC_K9_SCHEDULER_ENABLED"] = "true" if k9_configured else "false"
    runtime["POC_IMAGE_TAG"] = release.product_sha
    runtime["POC_SOURCE_COMMIT"] = release.product_sha
    runtime["PREP_RELEASE_PRODUCT_SHA"] = release.product_sha
    runtime["PREP_RELEASE_EVIDENCE_SHA"] = release.evidence_sha
    if target_state is not TargetState.FAILED_FIRST_INSTALL_REQUIRES_INSPECTION:
        _atomic_private_env(runtime_path, runtime)

    known_legacy = set(generated_specification) | set(fixed) | optional_keys | feature_keys | {
        "POC_K9_SCHEDULER_ENABLED",
        "POC_IMAGE_TAG",
        "POC_SOURCE_COMMIT",
        "PREP_RELEASE_PRODUCT_SHA",
        "PREP_RELEASE_EVIDENCE_SHA",
    }
    unknown = sorted(set(operator) - allowed_operator - known_legacy)
    warnings.extend(f"deprecated or unknown operator key ignored: {key}" for key in unknown)
    migrated_optional = sorted(set(operator) & optional_keys)
    warnings.extend(
        f"optional key should move to .env.prep.optional: {key}"
        for key in migrated_optional
    )

    effective = {key: operator[key] for key in allowed_operator if key in operator}
    effective.update({key: value for key, value in operator.items() if key in optional_keys})
    effective.update(optional)
    effective.update(runtime)
    no_proxy = merge_no_proxy(
        effective.get("NO_PROXY", ""),
        tuple(str(value) for value in contract.get("required_no_proxy", ())),
        effective.get("EXTERNAL_SERVICE_NO_PROXY", ""),
    )
    effective["NO_PROXY"] = no_proxy
    effective["no_proxy"] = no_proxy
    effective["http_proxy"] = effective.get("HTTP_PROXY", "")
    effective["https_proxy"] = effective.get("HTTPS_PROXY", "")
    return EnvironmentBundle(
        operator,
        optional,
        runtime,
        effective,
        tuple(warnings),
        target_state,
        "REQUIRED" if k9_configured else "DEFERRED",
    )


@contextmanager
def private_effective_environment(values: Mapping[str, str]) -> Iterator[Path]:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix="effective-", suffix=".env", dir=RUNTIME_ROOT)
    path = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            for key, value in sorted(values.items()):
                if not ENV_KEY.fullmatch(key) or "\n" in value or "\r" in value:
                    raise ValueError("invalid effective environment entry")
                stream.write(f"{key}={value}\n")
        yield path
    finally:
        if path.exists():
            path.unlink()


def child_environment(values: Mapping[str, str]) -> dict[str, str]:
    environment = dict(os.environ)
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy"):
        environment[key] = values.get(key, "")
    return environment


def compose_prefix(release: ReleaseIdentity, env_file: Path) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-name",
        release.project,
        "--env-file",
        os.fspath(env_file),
        "--file",
        os.fspath(BASE_COMPOSE),
    ]


def resolve_web_image(config: Mapping[str, Any]) -> str:
    services = config.get("services")
    web = services.get("web") if isinstance(services, dict) else None
    image = web.get("image") if isinstance(web, dict) else None
    if not isinstance(image, str) or not image.strip():
        raise PrepError(
            "IMAGE_IDENTITY",
            "PREP_WEB_IMAGE_REF_EMPTY",
            "Compose did not resolve one non-empty web image reference.",
            "Restore release.json and canonical Compose; no IMAGE_REF shell variable is used.",
        )
    return image.strip()


def _service_environment(config: Mapping[str, Any], service: str) -> Mapping[str, str]:
    services = config.get("services")
    item = services.get(service) if isinstance(services, dict) else None
    environment = item.get("environment") if isinstance(item, dict) else None
    if not isinstance(environment, dict):
        raise PrepError(
            "COMPOSE_CONFIG",
            "PREP_COMPOSE_ENVIRONMENT_INVALID",
            f"Compose service {service} has no resolved environment object.",
            "Restore the canonical Compose configuration and retry.",
        )
    return {str(key): str(value) for key, value in environment.items()}


def validate_postgres_contract(config: Mapping[str, Any]) -> None:
    web = _service_environment(config, "web")
    database = _service_environment(config, "pgvector")
    pairs = (
        ("POC_POSTGRES_DB", "POSTGRES_DB"),
        ("POC_POSTGRES_USER", "POSTGRES_USER"),
        ("POC_POSTGRES_PASSWORD", "POSTGRES_PASSWORD"),
    )
    if any(not web.get(left) or web.get(left) != database.get(right) for left, right in pairs):
        raise PrepError(
            "LOCAL_DATABASE_AUTH",
            "PREP_LOCAL_DB_CREDENTIAL_MISMATCH",
            "Compose web and pgvector database credentials do not share one exact contract.",
            "Restore the preserved .env.prep.runtime values; never reset an accepted volume.",
        )


def classify_bootstrap_failure(error: CommandFailure) -> PrepError:
    private_output = f"{error.stdout}\n{error.stderr}"
    if "PREP_LOCAL_DB_CREDENTIAL_MISMATCH" in private_output or "28P01" in private_output:
        return PrepError(
            "LOCAL_DATABASE_AUTH",
            "PREP_LOCAL_DB_CREDENTIAL_MISMATCH",
            "The Compose application credential cannot authenticate to the existing "
            "PostgreSQL volume.",
            "Restore the original target-local database secret. Do not delete an accepted volume.",
        )
    return PrepError(
        "TARGET_BOOTSTRAP",
        "PREP_BOOTSTRAP_FAILED",
        "The Compose-scoped idempotent bootstrap did not complete.",
        "Run ./scripts/prep39083 doctor, then logs after correcting the reported gate.",
    )


def require_prep_platform(runner: Runner) -> None:
    if platform.system() != "Linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise PrepError(
            "PLATFORM_PREFLIGHT",
            "PREP_AMD64_REQUIRED",
            "PREP deployment requires native Linux/WSL amd64.",
            "Run this command on the approved PREP WSL/Linux amd64 host.",
        )
    for command in ("git", "docker", "node", "uv"):
        if shutil.which(command, path=runner.environment.get("PATH")) is None:
            raise PrepError(
                "PLATFORM_PREFLIGHT",
                "PREP_COMMAND_REQUIRED",
                f"Required command is unavailable: {command}.",
                f"Install the approved {command} tool and retry.",
            )
    architecture = runner.output(["docker", "info", "--format", "{{.Architecture}}"])
    if architecture not in {"amd64", "x86_64"}:
        raise PrepError(
            "PLATFORM_PREFLIGHT",
            "PREP_DOCKER_AMD64_REQUIRED",
            f"Docker reports unsupported architecture {architecture!r}.",
            "Select a native Linux amd64 Docker engine.",
        )
    runner.run(["docker", "compose", "version"])


def prepare_deployment(
    release: ReleaseIdentity,
) -> tuple[EnvironmentBundle, DeploymentPreparation]:
    operator = read_env_file(OPERATOR_ENV, private=True, label=".env.prep")
    runner = Runner(environment=child_environment(operator))
    runner.note("Verify native PREP platform and exact Product/Evidence source")
    require_prep_platform(runner)
    source = verify_source_identity(release)
    before_39080 = snapshot_39080(runner)
    inventory = inspect_target_inventory(runner, release)
    state = classify_target_state(inventory)
    runner.note(f"Classify PREP target state: {state.value}")
    if state is TargetState.EXISTING_STATE_AMBIGUOUS:
        _ambiguous_state("Existing PREP receipts, runtime secrets and persistent volumes disagree.")
    if state is TargetState.FAILED_FIRST_INSTALL_REQUIRES_INSPECTION:
        inspection_bundle = reconcile_environment(release, target_state=state)
        state = prove_failed_install_recoverable(
            runner,
            release,
            inspection_bundle,
            inventory,
        )
        runner.note(f"Prove residual target state: {state.value}")
    bundle = reconcile_environment(release, target_state=state)
    runner.environment = child_environment(bundle.effective)
    return bundle, DeploymentPreparation(runner, source, inventory, before_39080)


def verify_source_identity(release: ReleaseIdentity) -> dict[str, str]:
    try:
        return source_contract(release.product_sha, release.evidence_sha, clean=True)
    except ReleaseError as error:
        raise PrepError(
            "SOURCE_IDENTITY",
            "PREP_SOURCE_CONTRACT_FAILED",
            "Product/Evidence ancestry, cleanliness, or runtime-input stability failed.",
            "Run git switch dev and fast-forward origin/dev, then retry from a clean checkout.",
        ) from error


def compose_config(runner: Runner, prefix: Sequence[str]) -> dict[str, Any]:
    try:
        value = json.loads(runner.output([*prefix, "config", "--format", "json"]))
    except (CommandFailure, json.JSONDecodeError) as error:
        raise PrepError(
            "COMPOSE_CONFIG",
            "PREP_COMPOSE_CONFIG_INVALID",
            "The effective PREP Compose configuration is invalid.",
            "Correct only the named environment gate and rerun deploy.",
        ) from error
    if not isinstance(value, dict):
        raise PrepError(
            "COMPOSE_CONFIG",
            "PREP_COMPOSE_CONFIG_INVALID",
            "Compose did not return one configuration object.",
            "Restore the canonical Compose file and retry.",
        )
    validate_postgres_contract(value)
    return value


def inspect_web_image(runner: Runner, image: str, product_sha: str) -> None:
    try:
        inspected = json.loads(runner.output(["docker", "image", "inspect", image]))[0]
    except (CommandFailure, json.JSONDecodeError, IndexError) as error:
        raise PrepError(
            "IMAGE_IDENTITY",
            "PREP_WEB_IMAGE_MISSING",
            "The exact built web image cannot be inspected.",
            "Rerun ./scripts/prep39083 deploy; the image reference is resolved automatically.",
        ) from error
    labels = inspected.get("Config", {}).get("Labels") or {}
    if inspected.get("Os") != "linux" or inspected.get("Architecture") != "amd64":
        raise PrepError(
            "IMAGE_IDENTITY",
            "PREP_WEB_IMAGE_PLATFORM_MISMATCH",
            "The built web image is not linux/amd64.",
            "Use the approved native amd64 PREP Docker engine.",
        )
    if labels.get("org.opencontainers.image.revision") != product_sha:
        raise PrepError(
            "IMAGE_IDENTITY",
            "PREP_WEB_IMAGE_REVISION_MISMATCH",
            "The built web OCI revision does not equal the tracked Product SHA.",
            "Remove only the incorrect unaccepted image tag and rerun deploy.",
        )
    config = inspected.get("Config", {})
    serialized = json.dumps({"Env": config.get("Env"), "Labels": labels}, sort_keys=True)
    if re.search(r"https?://[^\s\"']+@", serialized):
        raise PrepError(
            "IMAGE_IDENTITY",
            "PREP_PROXY_SECRET_PERSISTED",
            "The final image configuration appears to contain a credential-bearing proxy URL.",
            "Stop promotion and correct the Docker build proxy boundary.",
        )


def snapshot_39080(runner: Runner) -> tuple[str, ...]:
    output = runner.output([
        "docker", "ps", "--filter", "publish=39080", "--format", "{{.ID}} {{.Names}}",
    ])
    return tuple(sorted(line for line in output.splitlines() if line))


def _ambiguous_state(reason: str) -> NoReturn:
    raise PrepError(
        "TARGET_STATE",
        "PREP_EXISTING_STATE_REQUIRES_OPERATOR_RECOVERY",
        reason,
        "Preserve all containers, volumes and target-owned environment files; "
        "review ./scripts/prep39083 doctor before approved recovery.",
    )


def _postgres_local_command(prefix: Sequence[str], database: str, username: str) -> list[str]:
    return [
        *prefix,
        "exec",
        "-T",
        "--user",
        "postgres",
        "pgvector",
        "psql",
        "--no-psqlrc",
        "--set",
        "ON_ERROR_STOP=1",
        "--username",
        username,
        "--dbname",
        database,
        "--tuples-only",
        "--no-align",
    ]


def inspect_postgres_durable_rows(
    runner: Runner,
    prefix: Sequence[str],
    *,
    database: str,
    username: str,
) -> dict[str, int]:
    command = _postgres_local_command(prefix, database, username)
    try:
        tables_output = runner.output([
            *command,
            "--command",
            "SELECT tablename FROM pg_catalog.pg_tables "
            "WHERE schemaname = 'public' ORDER BY tablename;",
        ])
        counts: dict[str, int] = {}
        for table in filter(None, tables_output.splitlines()):
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", table):
                _ambiguous_state("The residual PostgreSQL schema contains an unclassifiable table.")
            raw_count = runner.output([
                *command,
                "--command",
                f'SELECT CASE WHEN EXISTS (SELECT 1 FROM public."{table}" LIMIT 1) '  # noqa: S608 -- identifier is strictly allowlisted above.
                "THEN 1 ELSE 0 END;",
            ])
            if not raw_count.isdigit():
                _ambiguous_state("The residual PostgreSQL row-count proof was incomplete.")
            counts[table] = int(raw_count)
        return counts
    except CommandFailure as error:
        raise PrepError(
            "TARGET_STATE",
            "PREP_EXISTING_STATE_REQUIRES_OPERATOR_RECOVERY",
            "The residual PostgreSQL volume could not be inspected through its local socket.",
            "Preserve the volume and use an approved database recovery procedure.",
        ) from error


def inspect_neo4j_durable_nodes(password: str, port: str) -> int:
    if not password or password == INSPECTION_PLACEHOLDER:
        _ambiguous_state(
            "A residual Neo4j volume exists but its preserved target-local credential is absent.",
        )
    authorization = base64.b64encode(f"neo4j:{password}".encode()).decode("ascii")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/db/neo4j/tx/commit",
        data=json.dumps({
            "statements": [{"statement": "MATCH (n) RETURN count(n) AS count"}],
        }).encode(),
        headers={"Authorization": f"Basic {authorization}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=30) as response:
            payload = json.loads(response.read())
        errors = payload.get("errors") if isinstance(payload, dict) else None
        results = payload.get("results") if isinstance(payload, dict) else None
        rows = results[0].get("data") if isinstance(results, list) and results else None
        count = rows[0].get("row", [None])[0] if isinstance(rows, list) and rows else None
        if errors or not isinstance(count, int) or count < 0:
            raise ValueError("invalid Neo4j proof")
        return count
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as error:
        raise PrepError(
            "TARGET_STATE",
            "PREP_EXISTING_STATE_REQUIRES_OPERATOR_RECOVERY",
            "The residual Neo4j volume could not be proven empty with its preserved credential.",
            "Preserve the volume and restore its matching target-local runtime environment.",
        ) from error


def prove_failed_install_recoverable(
    runner: Runner,
    release: ReleaseIdentity,
    bundle: EnvironmentBundle,
    inventory: TargetInventory,
) -> TargetState:
    allowed_services = {"web", "pgvector", "neo4j", "redis"}
    allowed_volumes = {"pgvector-data", "neo4j-data", "neo4j-logs"}
    if inventory.accepted_marker_present:
        _ambiguous_state("An accepted receipt exists; failed-install recovery is not permitted.")
    if {item.service for item in inventory.containers} - allowed_services:
        _ambiguous_state("The PREP Compose project contains an unknown residual service.")
    if inventory.volume_names - allowed_volumes:
        _ambiguous_state("The PREP Compose project contains an unknown persistent volume.")
    with private_effective_environment(bundle.effective) as env_file:
        prefix = compose_prefix(release, env_file)
        if any(item.service == "web" and item.running for item in inventory.containers):
            runner.run([*prefix, "stop", "web"])
        if "pgvector-data" in inventory.volume_names:
            runner.run([*prefix, "up", "-d", "--wait", "pgvector"])
            counts = inspect_postgres_durable_rows(
                runner,
                prefix,
                database=bundle.effective["POC_POSTGRES_DB"],
                username=bundle.effective["POC_POSTGRES_USER"],
            )
            if any(count > 0 for count in counts.values()):
                _ambiguous_state(
                    "The unaccepted PostgreSQL volume contains durable Product state.",
                )
        if "neo4j-data" in inventory.volume_names:
            runner.run([*prefix, "up", "-d", "--wait", "neo4j"])
            count = inspect_neo4j_durable_nodes(
                bundle.effective["NEO4J_PASSWORD"],
                bundle.effective["POC_NEO4J_HTTP_PORT"],
            )
            if count > 0:
                _ambiguous_state("The unaccepted Neo4j volume contains durable graph state.")
    return TargetState.FAILED_FIRST_INSTALL_RECOVERABLE


def reconcile_recoverable_postgres_credential(
    runner: Runner,
    prefix: Sequence[str],
    bundle: EnvironmentBundle,
) -> None:
    username = bundle.effective["POC_POSTGRES_USER"]
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", username):
        _ambiguous_state("The configured PostgreSQL role cannot be safely reconciled.")
    password = bundle.effective["POC_POSTGRES_PASSWORD"]
    if "\n" in password or "\r" in password or "\x00" in password:
        _ambiguous_state("The generated PostgreSQL credential is outside its safe contract.")
    statement = f'ALTER ROLE "{username}" WITH PASSWORD \'{password.replace("\'", "\'\'")}\';\n'
    try:
        runner.run(
            [
                *_postgres_local_command(
                    prefix,
                    bundle.effective["POC_POSTGRES_DB"],
                    username,
                ),
                "--file",
                "-",
            ],
            input_text=statement,
        )
    except CommandFailure as error:
        raise PrepError(
            "LOCAL_DATABASE_AUTH",
            "PREP_LOCAL_DB_CREDENTIAL_MISMATCH",
            "Disposable first-install PostgreSQL state could not be reconciled.",
            "Preserve the volume and inspect the approved local database recovery path.",
        ) from error


def _parse_json_line(output: str) -> dict[str, Any]:
    for line in reversed(output.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("no JSON object in command output")


def inspect_bootstrap(runner: Runner, prefix: Sequence[str]) -> dict[str, Any]:
    try:
        completed = runner.run([
            *prefix,
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "web",
            "node",
            "poc-prep-bootstrap.mjs",
            "inspect",
        ])
        return _parse_json_line(completed.stdout)
    except CommandFailure as error:
        raise classify_bootstrap_failure(error) from error
    except ValueError as error:
        raise PrepError(
            "TARGET_BOOTSTRAP",
            "PREP_BOOTSTRAP_RESULT_INVALID",
            "The bootstrap inspection did not return its structured result.",
            "Inspect ./scripts/prep39083 logs without changing database credentials.",
        ) from error


@contextmanager
def private_password_file(password: str) -> Iterator[Path]:
    if len(password.encode("utf-8")) < 12 or "\n" in password or "\r" in password:
        raise PrepError(
            "ADMIN_BOOTSTRAP",
            "PREP_ADMIN_PASSWORD_INVALID",
            "The administrator password is outside the 12-character bounded contract.",
            "Enter a stronger password without line breaks.",
        )
    descriptor, name = tempfile.mkstemp(prefix="datariver-prep39083-admin-")
    path = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(f"{password}\n")
        yield path
    finally:
        if path.exists():
            path.unlink()


def _choose_existing_administrator(inspected: Mapping[str, Any]) -> str:
    administrators = inspected.get("administrators")
    if not isinstance(administrators, list) or not administrators:
        raise ValueError("administrator selection requires at least one candidate")
    usernames: list[str] = []
    for item in administrators:
        if isinstance(item, dict):
            username = item.get("username")
            if isinstance(username, str):
                usernames.append(username)
    usernames.sort()
    if not usernames:
        raise ValueError("administrator inspection contains no valid username")
    if len(usernames) == 1:
        return usernames[0]
    selected = input(f"PREP administrator username [{usernames[0]}]: ").strip() or usernames[0]
    if selected not in usernames:
        raise PrepError(
            "ADMIN_SMOKE",
            "PREP_ADMIN_SELECTION_INVALID",
            "The selected username is not an enabled PREP administrator.",
            "Select one of the non-secret usernames shown by ./scripts/prep39083 status.",
        )
    return selected


def reconcile_bootstrap(
    runner: Runner,
    prefix: Sequence[str],
    inspected: Mapping[str, Any],
) -> tuple[str, str]:
    administrators = inspected.get("administrators")
    if not isinstance(administrators, list):
        raise PrepError(
            "ADMIN_BOOTSTRAP",
            "PREP_BOOTSTRAP_RESULT_INVALID",
            "Bootstrap inspection omitted administrator state.",
            "Restore the exact Product image and retry.",
        )
    created = len(administrators) == 0
    if created:
        selected = input("No PREP admin found. Username [admin]: ").strip() or "admin"
        username = normalize_operator_username(selected)
        password = getpass.getpass("Password: ")
        confirmation = getpass.getpass("Confirm password: ")
        if password != confirmation:
            raise PrepError(
                "ADMIN_BOOTSTRAP",
                "PREP_ADMIN_PASSWORD_MISMATCH",
                "Administrator password confirmation did not match.",
                "Rerun deploy and enter the same hidden password twice.",
            )
    else:
        username = _choose_existing_administrator(inspected)
        password = getpass.getpass(f"Password for {username} (smoke only): ")
    with private_password_file(password) as password_path:
        command: list[str] = [
            *prefix,
            "run",
            "--rm",
            "--no-deps",
            "-T",
        ]
        if created:
            command.extend([
                "--volume",
                f"{password_path}:/run/prep-admin.password:ro",
            ])
        command.extend(["web", "node", "poc-prep-bootstrap.mjs", "reconcile"])
        if created:
            command.extend([
                "--admin-username",
                username,
                "--admin-password-file",
                "/run/prep-admin.password",
            ])
        try:
            result = _parse_json_line(runner.run(command).stdout)
        except CommandFailure as error:
            raise classify_bootstrap_failure(error) from error
        except ValueError as error:
            raise PrepError(
                "TARGET_BOOTSTRAP",
                "PREP_BOOTSTRAP_RESULT_INVALID",
                "Identity reconciliation did not return its structured result.",
                "Run ./scripts/prep39083 doctor and retry.",
            ) from error
        services = result.get("services")
        if not isinstance(services, list) or any(
            item.get("status") != "PRESENT" for item in services
        ):
            raise PrepError(
                "TARGET_BOOTSTRAP",
                "PREP_BOOTSTRAP_INCOMPLETE",
                "Requested target-local service identity reconciliation is incomplete.",
                "Do not start web; correct the reported identity drift first.",
            )
        # Keep only the in-memory password and one private temporary file until smoke completes.
        smoke_copy = password
    return username, smoke_copy


def normalize_operator_username(value: str) -> str:
    normalized = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._@+-]{0,63}", normalized):
        raise PrepError(
            "ADMIN_BOOTSTRAP",
            "PREP_ADMIN_USERNAME_INVALID",
            "The administrator username is outside its normalized contract.",
            "Use 1-64 lowercase letters, digits, dot, underscore, at-sign, plus or hyphen.",
        )
    return normalized


def run_smoke(
    runner: Runner,
    release: ReleaseIdentity,
    username: str,
    password: str,
    *,
    k9_mode: str,
) -> None:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    output = RUNTIME_ROOT / "smoke.json"
    if output.exists():
        output.unlink()
    with private_password_file(password) as password_path:
        try:
            runner.run([
                "node",
                SMOKE_TOOL,
                "--origin",
                f"http://127.0.0.1:{release.port}",
                "--username",
                username,
                "--password-file",
                password_path,
                "--k9-mode",
                k9_mode.lower(),
                "--readiness-timeout-ms",
                "1200000",
                "--output",
                output,
            ])
        except CommandFailure as error:
            private_output = f"{error.stdout}\n{error.stderr}"
            code = (
                "PREP_ADMIN_SMOKE_AUTH_FAILED"
                if "/auth/login returned HTTP 401" in private_output
                else "PREP_RUNTIME_SMOKE_FAILED"
            )
            action = (
                "Rerun deploy with the correct existing administrator password."
                if code == "PREP_ADMIN_SMOKE_AUTH_FAILED"
                else "Inspect ./scripts/prep39083 logs; do not widen authorization or reset state."
            )
            raise PrepError(
                "RUNTIME_SMOKE",
                code,
                "Authenticated PREP smoke did not complete.",
                action,
            ) from error


def write_accepted_marker(
    release: ReleaseIdentity,
    handoff: str,
    *,
    target_state: TargetState,
    k9_mode: str,
) -> None:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    payload = {
        "contract": "DATARIVER_PREP39083_ACCEPTED_V1",
        "product_sha": release.product_sha,
        "evidence_sha": release.evidence_sha,
        "handoff_commit": handoff,
        "initial_target_state": target_state.value,
        "k9_mode": k9_mode,
        "accepted_at": datetime.now(UTC).isoformat(),
    }
    temporary = ACCEPTED_MARKER.with_suffix(".tmp")
    temporary.write_text(f"{json.dumps(payload, indent=2, sort_keys=True)}\n", encoding="utf-8")
    os.replace(temporary, ACCEPTED_MARKER)


def deploy(
    release: ReleaseIdentity,
    bundle: EnvironmentBundle,
    preparation: DeploymentPreparation,
) -> None:
    runner = preparation.runner
    source = preparation.source
    before_39080 = preparation.before_39080
    for warning in bundle.warnings:
        print(f"WARNING: {warning}", flush=True)
    with private_effective_environment(bundle.effective) as env_file:
        prefix = compose_prefix(release, env_file)
        runner.note("Validate private environment ownership and Compose contract")
        config = compose_config(runner, prefix)
        image = resolve_web_image(config)
        runner.note("Build exact linux/amd64 Product image with bounded proxy configuration")
        runner.run([*prefix, "build", "--pull=false", "web"])
        inspect_web_image(runner, image, release.product_sha)
        if (
            bundle.target_state is TargetState.FAILED_FIRST_INSTALL_RECOVERABLE
            and "pgvector-data" in preparation.inventory.volume_names
        ):
            runner.note(
                "Reconcile proven-disposable PostgreSQL role credential without volume reset",
            )
            reconcile_recoverable_postgres_credential(runner, prefix, bundle)
        runner.note("Start isolated PostgreSQL, Neo4j and Redis and wait for health")
        runner.run([*prefix, "up", "-d", "--wait", "pgvector", "neo4j", "redis"])
        runner.note("Apply idempotent state initialization and inspect target-local identities")
        inspected = inspect_bootstrap(runner, prefix)
        username, password = reconcile_bootstrap(runner, prefix, inspected)
        runner.note("Start exact Product web service and verify internal and host health")
        runner.run([*prefix, "up", "-d", "--no-build", "--wait", "web"])
        web_id = runner.output([*prefix, "ps", "-q", "web"])
        if not web_id or runner.output([
            "docker", "inspect", "--format", "{{.State.Health.Status}}", web_id,
        ]) != "healthy":
            raise PrepError(
                "WEB_HEALTH",
                "PREP_INTERNAL_WEB_UNHEALTHY",
                "Docker internal web health is not healthy.",
                "Run ./scripts/prep39083 logs; do not reset persistent volumes.",
            )
        try:
            runner.run([
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                "--noproxy",
                "*",
                f"http://127.0.0.1:{release.port}/healthz",
            ])
        except CommandFailure as error:
            raise PrepError(
                "WEB_HEALTH",
                "PREP_HOST_39083_UNREACHABLE",
                "Docker is healthy but host port 39083 is not reachable without the proxy.",
                "Check WSL port binding and host firewall; the application container is healthy.",
            ) from error
        runner.note("Run authenticated provider, managed-graph and GENERAL smoke")
        run_smoke(runner, release, username, password, k9_mode=bundle.k9_mode)
        after_39080 = snapshot_39080(runner)
        if after_39080 != before_39080:
            raise PrepError(
                "ISOLATION",
                "PREP_39080_CHANGED",
                "The existing 39080 container set changed during deployment.",
                "Stop and investigate; do not promote this PREP result.",
            )
        write_accepted_marker(
            release,
            source["handoff_commit"],
            target_state=bundle.target_state,
            k9_mode=bundle.k9_mode,
        )
    print("\nPREP39083 DEPLOYMENT READY")
    print("\nRelease")
    print(f"- Product: {release.product_sha}")
    print(f"- Evidence: {release.evidence_sha}")
    print(f"- Handoff: {source['handoff_commit']}")
    print("- Platform: linux/amd64")
    print("\nRuntime")
    print(f"- Initial state: {bundle.target_state.value}")
    print("- Web: healthy")
    print(f"- Port: {release.port}")
    print("- PostgreSQL: healthy")
    print("- Neo4j: healthy")
    print("- Redis: healthy")
    print("- 39080: untouched")
    print("\nProviders")
    print("- DataHub: ready")
    print("- Chat: ready")
    if bundle.k9_mode == "REQUIRED":
        print("- Embedding/Reranker: configured; managed semantic index READY")
        print("- K9 Managed Refresh: DAILY / READY")
    else:
        print("- Embedding/Reranker: configured")
        print("- K9 Managed Refresh: DEFERRED — Studio DB not configured")
    optional_provider_ready = bool(
        bundle.effective.get("AIRFLOW_URL", "").strip()
        and bundle.effective.get("MINIO_URL", "").strip()
    )
    print(f"- Airflow/MinIO: {'configured' if optional_provider_ready else 'not configured'}")
    print("- MCL: disabled unless explicitly enabled in .env.prep.optional")
    print("\nAuthentication")
    print(f"- Admin: existing/created and smoke verified ({username})")
    print(f"\nNext\n- Browser: http://127.0.0.1:{release.port}")


def doctor(release: ReleaseIdentity, bundle: EnvironmentBundle) -> None:
    runner = Runner(environment=child_environment(bundle.effective))
    require_prep_platform(runner)
    source = verify_source_identity(release)
    with private_effective_environment(bundle.effective) as env_file:
        config = compose_config(runner, compose_prefix(release, env_file))
        image = resolve_web_image(config)
    print("PREP39083 DOCTOR PASS")
    print(f"- Product: {release.product_sha}")
    print(f"- Evidence: {release.evidence_sha}")
    print(f"- Handoff: {source['handoff_commit']}")
    print(f"- Image: {image}")
    print(f"- Environment warnings: {len(bundle.warnings)}")


def status(release: ReleaseIdentity, bundle: EnvironmentBundle) -> None:
    runner = Runner(environment=child_environment(bundle.effective))
    with private_effective_environment(bundle.effective) as env_file:
        prefix = compose_prefix(release, env_file)
        result = runner.run([*prefix, "ps"], check=False)
    print(result.stdout.rstrip() or "PREP39083 has no current containers.")


def logs(release: ReleaseIdentity, bundle: EnvironmentBundle) -> None:
    runner = Runner(environment=child_environment(bundle.effective))
    with private_effective_environment(bundle.effective) as env_file:
        prefix = compose_prefix(release, env_file)
        completed = runner.run([*prefix, "logs", "--tail", "200"], check=False)
    # Explicit troubleshooting action: application logs are emitted, environment values are not.
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    if completed.returncode != 0:
        raise PrepError(
            "LOGS",
            "PREP_LOGS_FAILED",
            "Compose logs could not be read.",
            "Verify Docker access and the datariver-prep39083 project name.",
        )


def smoke(release: ReleaseIdentity, bundle: EnvironmentBundle) -> None:
    runner = Runner(environment=child_environment(bundle.effective))
    with private_effective_environment(bundle.effective) as env_file:
        inspected = inspect_bootstrap(runner, compose_prefix(release, env_file))
    username = _choose_existing_administrator(inspected)
    password = getpass.getpass(f"Password for {username} (smoke only): ")
    run_smoke(runner, release, username, password, k9_mode=bundle.k9_mode)
    print("PREP39083 SMOKE PASS")


def export(release: ReleaseIdentity, bundle: EnvironmentBundle) -> None:
    runner = Runner(environment=child_environment(bundle.effective))
    output_dir = RUNTIME_ROOT / f"release-{release.product_sha}"
    with private_effective_environment(bundle.effective) as env_file:
        try:
            completed = runner.run([
                sys.executable,
                RELEASE_TOOL,
                "export",
                "--product-sha",
                release.product_sha,
                "--evidence-sha",
                release.evidence_sha,
                "--env-file",
                env_file,
                "--project-name",
                release.project,
                "--output-dir",
                output_dir,
            ])
        except CommandFailure as error:
            raise PrepError(
                "EXPORT",
                "PREP_EXPORT_FAILED",
                "Exact tested-image export did not pass its immutable release boundary.",
                "Keep PREP running and correct the source/image identity gate before retrying.",
            ) from error
    print(completed.stdout.rstrip())


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("deploy", "doctor", "status", "logs", "smoke", "export"))
    return parser.parse_args()


def prepare_operational_bundle(
    release: ReleaseIdentity,
    action: str,
) -> EnvironmentBundle:
    operator = read_env_file(OPERATOR_ENV, private=True, label=".env.prep")
    runner = Runner(environment=child_environment(operator))
    inventory = inspect_target_inventory(runner, release)
    state = classify_target_state(inventory)
    if state is TargetState.EXISTING_STATE_AMBIGUOUS:
        _ambiguous_state("Existing PREP receipts, runtime secrets and persistent volumes disagree.")
    if action in {"smoke", "export"} and state not in {
        TargetState.EXISTING_ACCEPTED_RUNNING,
        TargetState.EXISTING_ACCEPTED_STOPPED,
    }:
        _ambiguous_state(f"The {action} action requires one accepted PREP deployment.")
    read_only_state = (
        TargetState.FAILED_FIRST_INSTALL_REQUIRES_INSPECTION
        if state is TargetState.FRESH_CLEAN
        else state
    )
    return reconcile_environment(release, target_state=read_only_state)


def fail(error: PrepError) -> NoReturn:
    print("FAILED", file=sys.stderr)
    print(f"Step: {error.step}", file=sys.stderr)
    print(f"Code: {error.code}", file=sys.stderr)
    print(f"Reason: {error.reason}", file=sys.stderr)
    print(f"Action: {error.action}", file=sys.stderr)
    raise SystemExit(2)


def main() -> None:
    arguments = parse_arguments()
    try:
        release = load_release_identity()
        if arguments.action == "deploy":
            bundle, preparation = prepare_deployment(release)
            deploy(release, bundle, preparation)
            return
        bundle = prepare_operational_bundle(release, arguments.action)
        actions = {
            "doctor": doctor,
            "status": status,
            "logs": logs,
            "smoke": smoke,
            "export": export,
        }
        actions[arguments.action](release, bundle)
    except PrepError as error:
        fail(error)
    except CommandFailure:
        fail(PrepError(
            "COMMAND_EXECUTION",
            "PREP_COMMAND_FAILED",
            "A bounded deployment command failed without completing its gate.",
            "Run ./scripts/prep39083 doctor, then logs; secrets and raw command "
            "output were suppressed.",
        ))
    except (EOFError, KeyboardInterrupt):
        fail(PrepError(
            "OPERATOR_INPUT",
            "PREP_OPERATOR_INPUT_CANCELLED",
            "Interactive operator input was cancelled.",
            "Rerun ./scripts/prep39083 deploy when the administrator input is available.",
        ))
    except (OSError, ValueError):
        fail(PrepError(
            "UNEXPECTED",
            "PREP_DEPLOYMENT_FAILED",
            "The one-command deployment could not complete its bounded contract.",
            "Run ./scripts/prep39083 doctor; no persistent state was intentionally deleted.",
        ))


if __name__ == "__main__":
    main()
