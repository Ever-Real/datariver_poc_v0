#!/usr/bin/env python3
"""One-command PREP39083 source deployment above the immutable release tools."""

from __future__ import annotations

import argparse
import base64
import fcntl
import getpass
import hashlib
import hmac
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
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, NoReturn, TextIO

from prep39083_artifact import (
    ArtifactError,
    WebArtifactIdentity,
    identity_from_release_mapping,
    inspect_web_archive,
    require_expected_identity,
    sha256_file,
)
from prep39083_release import ReleaseError, source_contract
from prep39083_transport import (
    GitTransportIdentity,
    TransportError,
    read_transport_identity,
    retrieve_git_artifact,
)

ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT = ROOT / "deploy" / "prep39083"
BASE_COMPOSE = ROOT / "deploy" / "poc" / "docker-compose.poc.yaml"
PREP_ARTIFACT_COMPOSE = DEPLOYMENT / "docker-compose.artifact.yaml"
OPERATOR_ENV = DEPLOYMENT / ".env.prep"
OPTIONAL_ENV = DEPLOYMENT / ".env.prep.optional"
RUNTIME_ENV = DEPLOYMENT / ".env.prep.runtime"
ENV_CONTRACT = DEPLOYMENT / "env-contract.json"
RELEASE_IDENTITY = DEPLOYMENT / "release.json"
TRANSPORT_IDENTITY = DEPLOYMENT / "transport.json"
SMOKE_TOOL = ROOT / "scripts" / "smoke_prep39083.mjs"
RELEASE_TOOL = ROOT / "scripts" / "prep39083_release.py"
RUNTIME_ROOT = ROOT / "runtime" / "prep39083"
ACCEPTED_MARKER = RUNTIME_ROOT / "accepted.json"
ATTEMPT_RECEIPT = RUNTIME_ROOT / "deploy-attempt.json"
SMOKE_FAILURE = RUNTIME_ROOT / "smoke-failure.json"
SMOKE_REPORT = RUNTIME_ROOT / "smoke.json"
K9_PROGRESS = RUNTIME_ROOT / "k9-progress.json"
DEPLOY_LOCK = RUNTIME_ROOT / "deploy.lock"
LAST_COMMAND = RUNTIME_ROOT / "last-command.json"
COMMAND_LOGS = RUNTIME_ROOT / "logs"
PREP_RELEASE_BRANCH = "prep39083-release"
ACCEPTED_CONTRACT_V1 = "DATARIVER_PREP39083_ACCEPTED_V1"
ACCEPTED_CONTRACT_V2 = "DATARIVER_PREP39083_ACCEPTED_V2"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
CHANGE_ME_PREFIX = "CHANGE_ME"
INSPECTION_PLACEHOLDER = "prep-inspection-only-not-persisted"
SUPPORTED_DATAHUB_INVENTORY_FAILURE_CODES = frozenset(
    {
        "PREP_DATAHUB_INVENTORY_QUERY_FAILED",
        "PREP_DATAHUB_INVENTORY_PAGE_FAILED",
        "PREP_DATAHUB_INVENTORY_GRAPHQL_FAILED",
        "PREP_DATAHUB_INVENTORY_CONTRACT_FAILED",
        "PREP_DATAHUB_INVENTORY_NORMALIZATION_FAILED",
        "PREP_DATAHUB_INVENTORY_PROMOTION_FAILED",
    },
)
SUPPORTED_GENERAL_PROVIDER_FAILURE_CODES = frozenset(
    {
        "PREP_SMOKE_GENERAL_PROVIDER_FAILED",
        "PREP_SMOKE_GENERAL_PROVIDER_AUTH_FAILED",
        "PREP_SMOKE_GENERAL_PROVIDER_CONNECTIVITY_FAILED",
        "PREP_SMOKE_GENERAL_PROVIDER_CONTRACT_FAILED",
        "PREP_SMOKE_GENERAL_PROVIDER_HTTP_FAILED",
        "PREP_SMOKE_GENERAL_PROVIDER_TIMEOUT_FAILED",
    },
)
SUPPORTED_GLOSSARY_SMOKE_FAILURE_CODES = frozenset(
    {
        "PREP_SMOKE_GLOSSARY_TERM_INPUT_FAILED",
        "PREP_SMOKE_GLOSSARY_TERM_DISCOVERY_FAILED",
        "PREP_SMOKE_GLOSSARY_TERM_LOOKUP_FAILED",
        "PREP_SMOKE_GLOSSARY_TERM_NOT_FOUND_FAILED",
        "PREP_SMOKE_GLOSSARY_TERM_CONTRACT_FAILED",
    },
)
HOST_SUBPROCESS_ENVIRONMENT_KEYS = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "TMPDIR",
        "TMP",
        "TEMP",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
        "DOCKER_CONFIG",
        "XDG_RUNTIME_DIR",
    }
)
SUPPORTED_K9_SMOKE_FAILURE_CODES = frozenset(
    {
        "PREP_SMOKE_K9_NOT_READY",
        "PREP_SMOKE_K9_DATAHUB_SOURCE_FAILED",
        "PREP_SMOKE_K9_POLICY_PIN_DRIFT_FAILED",
        "PREP_SMOKE_K9_NEO4J_PROJECTION_FAILED",
        "PREP_SMOKE_K9_PROMOTION_FAILED",
        "PREP_SMOKE_K9_REFRESH_FAILED",
        "PREP_SMOKE_K9_SOURCE_DRIFT_RETRY_EXHAUSTED",
        "PREP_SMOKE_SEMANTIC_INDEX_NOT_READY",
    }
)
SUPPORTED_MCL_SMOKE_FAILURE_CODES = frozenset(
    {
        "PREP_SMOKE_MCL_SOURCE_FAILED",
        "PREP_SMOKE_MCL_RUNTIME_DISCOVERY_FAILED",
        "PREP_SMOKE_MCL_HISTORY_GAP_BLOCKED",
        "PREP_SMOKE_MCL_RUNTIME_CAPTURE_FAILED",
    }
)
SUPPORTED_POSTGRES_SCHEMA_FAILURE_CODES = frozenset(
    {
        "POC_POSTGRES_SCHEMA_INSPECTION_INVALID",
        "POC_POSTGRES_SCHEMA_INTEGRITY_CONFIG_INVALID",
        "POC_POSTGRES_SCHEMA_INTEGRITY_FAILED",
        "POC_POSTGRES_SCHEMA_MIGRATION_INCOMPLETE",
        "POC_POSTGRES_SCHEMA_NEWER_UNSUPPORTED",
        "POC_POSTGRES_SCHEMA_RECEIPT_MISMATCH",
    }
)


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
        self.environment = dict(os.environ if environment is None else environment)
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
        visible: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        command = [os.fspath(value) for value in arguments]
        completed = subprocess.run(  # noqa: S603 - argv only, no shell interpolation.
            command,
            cwd=cwd,
            env=self.environment,
            check=False,
            capture_output=not visible,
            text=True,
            input=input_text,
        )
        if check and completed.returncode != 0:
            raise CommandFailure(command, completed)
        return completed

    def output(
        self,
        arguments: Sequence[str | os.PathLike[str]],
        *,
        cwd: Path = ROOT,
    ) -> str:
        return self.run(arguments, cwd=cwd).stdout.strip()


class _Tee:
    def __init__(self, terminal: TextIO, log: TextIO) -> None:
        self.terminal = terminal
        self.log = log

    def write(self, value: str) -> int:
        written = self.terminal.write(value)
        self.log.write(value)
        return written

    def flush(self) -> None:
        self.terminal.flush()
        self.log.flush()


@dataclass(frozen=True)
class ReleaseIdentity:
    product_sha: str
    evidence_sha: str
    platform: str
    port: int
    project: str
    web_artifact: WebArtifactIdentity | None = None
    git_transport: GitTransportIdentity | None = None


class TargetState(str, Enum):
    FRESH_CLEAN = "FRESH_CLEAN"
    EXISTING_ACCEPTED_RUNNING = "EXISTING_ACCEPTED_RUNNING"
    EXISTING_ACCEPTED_STOPPED = "EXISTING_ACCEPTED_STOPPED"
    EXISTING_OWNED_INCOMPLETE = "EXISTING_OWNED_INCOMPLETE"
    LEGACY_SELF_BOOTSTRAPPED_PARTIAL_REQUIRES_INSPECTION = (
        "LEGACY_SELF_BOOTSTRAPPED_PARTIAL_REQUIRES_INSPECTION"
    )
    LEGACY_SELF_BOOTSTRAPPED_PARTIAL = "LEGACY_SELF_BOOTSTRAPPED_PARTIAL"
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
    attempt_receipt_present: bool = False
    attempt_receipt_valid: bool = False
    attempt_receipt: Mapping[str, Any] | None = None
    accepted_marker: Mapping[str, Any] | None = None

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
    previous_attempt: Mapping[str, Any] | None = None


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
    if value.get("contract") != "DATARIVER_PREP39083_RELEASE_V3":
        raise PrepError(
            "RELEASE_IDENTITY",
            "PREP_RELEASE_CONTRACT_INVALID",
            "The tracked release contract is not the build-once artifact contract.",
            "Restore deploy/prep39083/release.json from the exact approved Handoff.",
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
    try:
        web_artifact = identity_from_release_mapping(
            value.get("web_artifact"),
            product_sha=product_sha,
        )
    except ArtifactError as error:
        raise PrepError(
            "RELEASE_IDENTITY",
            "PREP_WEB_ARTIFACT_IDENTITY_INVALID",
            "The tracked promoted web artifact identity is invalid.",
            "Restore release.json from the exact approved Handoff; do not rebuild on PREP.",
        ) from error
    git_transport = None
    if TRANSPORT_IDENTITY.is_file():
        try:
            git_transport = read_transport_identity(
                TRANSPORT_IDENTITY,
                product_sha=product_sha,
                evidence_sha=evidence_sha,
                artifact=web_artifact,
            )
        except TransportError as error:
            raise PrepError(
                "RELEASE_IDENTITY",
                "PREP_GIT_TRANSPORT_IDENTITY_INVALID",
                "The tracked Git artifact transport identity is invalid.",
                "Restore the exact dedicated PREP release snapshot and retry.",
            ) from error
    return ReleaseIdentity(
        product_sha,
        evidence_sha,
        "linux/amd64",
        port,
        value["project"],
        web_artifact,
        git_transport,
    )


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
    return set(
        read_env_file(
            DEPLOYMENT / ".env.prep.optional.example",
            private=False,
            label="optional environment template",
        )
    )


def _accepted_marker(path: Path) -> Mapping[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("contract") not in {
        ACCEPTED_CONTRACT_V1,
        ACCEPTED_CONTRACT_V2,
    }:
        return None
    if not all(
        isinstance(value.get(key), str) and SHA_PATTERN.fullmatch(value[key])
        for key in ("product_sha", "evidence_sha", "handoff_commit")
    ):
        return None
    if value.get("contract") == ACCEPTED_CONTRACT_V1:
        return value
    valid_v2 = (
        isinstance(value.get("project"), str)
        and bool(re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", value["project"]))
        and value.get("platform") == "linux/amd64"
        and isinstance(value.get("port"), int)
        and 1 <= value["port"] <= 65535
        and value.get("k9_mode") in {"REQUIRED", "DEFERRED"}
        and value.get("ownership_fingerprint_contract") == OWNERSHIP_FINGERPRINT_CONTRACT
        and isinstance(value.get("ownership_fingerprint"), str)
        and bool(re.fullmatch(r"[0-9a-f]{64}", value["ownership_fingerprint"]))
        and isinstance(value.get("volume_identities"), list)
        and len(value["volume_identities"]) == len(set(value["volume_identities"]))
        and all(isinstance(item, str) and item for item in value["volume_identities"])
    )
    return value if valid_v2 else None


def _accepted_marker_valid(path: Path) -> bool:
    return _accepted_marker(path) is not None


ATTEMPT_PHASES = frozenset(
    {
        "PREPARED",
        "STATE_SERVICES_READY",
        "SCHEMA_READY",
        "BOOTSTRAP_READY",
        "WEB_READY",
        "SMOKE_RUNNING",
        "SMOKE_FAILED",
        "ACCEPTED",
    }
)
ATTEMPT_CONTRACT_V1 = "DATARIVER_PREP39083_DEPLOY_ATTEMPT_V1"
ATTEMPT_CONTRACT_V2 = "DATARIVER_PREP39083_DEPLOY_ATTEMPT_V2"
OWNERSHIP_FINGERPRINT_CONTRACT = "DATARIVER_PREP39083_TARGET_OWNERSHIP_V2"
TARGET_OWNERSHIP_SECRET_KEYS = (
    "NEO4J_PASSWORD",
    "POC_MCP_SERVICE_TOKEN",
    "POC_POSTGRES_PASSWORD",
)
PREP_VOLUME_LOGICAL_NAMES = ("neo4j-data", "neo4j-logs", "pgvector-data")


def _attempt_receipt(path: Path) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    contract = value.get("contract")
    fingerprint_valid = (
        isinstance(value.get("runtime_env_fingerprint"), str)
        and bool(re.fullmatch(r"[0-9a-f]{64}", value["runtime_env_fingerprint"]))
        if contract == ATTEMPT_CONTRACT_V1
        else (
            contract == ATTEMPT_CONTRACT_V2
            and value.get("ownership_fingerprint_contract") == OWNERSHIP_FINGERPRINT_CONTRACT
            and isinstance(value.get("ownership_fingerprint"), str)
            and bool(re.fullmatch(r"[0-9a-f]{64}", value["ownership_fingerprint"]))
        )
    )
    valid = (
        contract in {ATTEMPT_CONTRACT_V1, ATTEMPT_CONTRACT_V2}
        and all(
            isinstance(value.get(key), str) and SHA_PATTERN.fullmatch(value[key])
            for key in ("product_sha", "evidence_sha", "handoff_commit")
        )
        and isinstance(value.get("project"), str)
        and bool(re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", value["project"]))
        and value.get("platform") == "linux/amd64"
        and isinstance(value.get("port"), int)
        and 1 <= value["port"] <= 65535
        and value.get("phase") in ATTEMPT_PHASES
        and value.get("k9_mode") in {"REQUIRED", "DEFERRED"}
        and fingerprint_valid
        and isinstance(value.get("volume_identities"), list)
        and all(isinstance(item, str) and item for item in value["volume_identities"])
    )
    return value if valid else None


def _runtime_env_valid(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        values = read_env_file(path, private=True, label=".env.prep.runtime")
    except PrepError:
        return False
    return all(
        values.get(key, "").strip()
        for key in (
            "POC_POSTGRES_PASSWORD",
            "NEO4J_PASSWORD",
            "POC_MCP_SERVICE_TOKEN",
        )
    )


def inspect_target_inventory(
    runner: Runner,
    release: ReleaseIdentity,
    *,
    runtime_path: Path = RUNTIME_ENV,
    accepted_marker_path: Path = ACCEPTED_MARKER,
    attempt_receipt_path: Path = ATTEMPT_RECEIPT,
) -> TargetInventory:
    containers: list[TargetContainer] = []
    for line in runner.output(
        [
            "docker",
            "ps",
            "--all",
            "--filter",
            f"label=com.docker.compose.project={release.project}",
            "--format",
            '{{.ID}}\t{{.State}}\t{{.Label "com.docker.compose.service"}}',
        ]
    ).splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0] and parts[2]:
            containers.append(TargetContainer(parts[0], parts[2], parts[1] == "running"))
    volumes: list[TargetVolume] = []
    for line in runner.output(
        [
            "docker",
            "volume",
            "ls",
            "--filter",
            f"label=com.docker.compose.project={release.project}",
            "--format",
            '{{.Name}}\t{{.Label "com.docker.compose.volume"}}',
        ]
    ).splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and parts[0] and parts[1]:
            volumes.append(TargetVolume(parts[0], parts[1]))
    networks = tuple(
        sorted(
            filter(
                None,
                runner.output(
                    [
                        "docker",
                        "network",
                        "ls",
                        "--filter",
                        f"label=com.docker.compose.project={release.project}",
                        "--format",
                        "{{.Name}}",
                    ]
                ).splitlines(),
            )
        )
    )
    accepted = _accepted_marker(accepted_marker_path)
    attempt = _attempt_receipt(attempt_receipt_path)
    return TargetInventory(
        accepted_marker_path.exists(),
        accepted is not None,
        runtime_path.exists(),
        _runtime_env_valid(runtime_path),
        tuple(sorted(containers, key=lambda item: (item.service, item.identifier))),
        tuple(sorted(volumes, key=lambda item: (item.logical_name, item.name))),
        networks,
        attempt_receipt_path.exists(),
        attempt is not None,
        attempt,
        accepted,
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
        if not (
            inventory.accepted_marker_valid
            and inventory.runtime_env_valid
            and required_accepted_volumes <= inventory.volume_names
            and inventory.attempt_receipt_present
            and inventory.attempt_receipt_valid
            and isinstance(inventory.attempt_receipt, Mapping)
        ):
            return TargetState.EXISTING_STATE_AMBIGUOUS
        if inventory.attempt_receipt.get("phase") == "ACCEPTED":
            return (
                TargetState.EXISTING_ACCEPTED_RUNNING
                if inventory.running
                else TargetState.EXISTING_ACCEPTED_STOPPED
            )
        return TargetState.EXISTING_OWNED_INCOMPLETE
    if inventory.attempt_receipt_present:
        attempt = inventory.attempt_receipt
        if (
            inventory.attempt_receipt_valid
            and inventory.runtime_env_valid
            and isinstance(attempt, Mapping)
            and attempt.get("phase") != "ACCEPTED"
            and {volume.name for volume in inventory.volumes}
            <= set(attempt.get("volume_identities", ()))
        ):
            return TargetState.EXISTING_OWNED_INCOMPLETE
        return TargetState.EXISTING_STATE_AMBIGUOUS
    if not any(
        (
            inventory.runtime_env_present,
            inventory.containers,
            inventory.volumes,
            inventory.networks,
        )
    ):
        return TargetState.FRESH_CLEAN
    if inventory.runtime_env_valid and required_accepted_volumes <= inventory.volume_names:
        return TargetState.LEGACY_SELF_BOOTSTRAPPED_PARTIAL_REQUIRES_INSPECTION
    return TargetState.FAILED_FIRST_INSTALL_REQUIRES_INSPECTION


def _environment_ownership(
    contract: Mapping[str, Any],
) -> tuple[tuple[str, ...], dict[str, Any], tuple[str, ...], dict[str, Any], dict[str, Any]]:
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


def k9_mode_from_operator(operator: Mapping[str, str]) -> str:
    del operator
    return "REQUIRED"


def reconcile_environment(
    release: ReleaseIdentity,
    *,
    operator_path: Path = OPERATOR_ENV,
    optional_path: Path = OPTIONAL_ENV,
    runtime_path: Path = RUNTIME_ENV,
    random_token: Callable[[int], str] = _token,
    target_state: TargetState = TargetState.FRESH_CLEAN,
    persist_runtime: bool = True,
) -> EnvironmentBundle:
    contract = _read_json(ENV_CONTRACT, "environment contract")
    if contract.get("contract") != "DATARIVER_PREP39083_ENV_V5":
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
    required, features, operator_optional, generated_specification, fixed = _environment_ownership(
        contract
    )
    missing = sorted(
        key
        for key in required
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

    k9_mode = k9_mode_from_operator(operator)
    k9_configured = True
    for key, value in fixed.items():
        runtime[str(key)] = str(value)
    runtime["POC_K9_SCHEDULER_ENABLED"] = "true" if k9_configured else "false"
    runtime["POC_IMAGE_TAG"] = release.product_sha
    runtime["POC_SOURCE_COMMIT"] = release.product_sha
    runtime["PREP_RELEASE_PRODUCT_SHA"] = release.product_sha
    runtime["PREP_RELEASE_EVIDENCE_SHA"] = release.evidence_sha
    if persist_runtime and target_state is not TargetState.FAILED_FIRST_INSTALL_REQUIRES_INSPECTION:
        _atomic_private_env(runtime_path, runtime)

    known_legacy = (
        set(generated_specification)
        | set(fixed)
        | optional_keys
        | feature_keys
        | {
            "POC_K9_SCHEDULER_ENABLED",
            "POC_IMAGE_TAG",
            "POC_SOURCE_COMMIT",
            "PREP_RELEASE_PRODUCT_SHA",
            "PREP_RELEASE_EVIDENCE_SHA",
        }
    )
    unknown = sorted(set(operator) - allowed_operator - known_legacy)
    warnings.extend(f"deprecated or unknown operator key ignored: {key}" for key in unknown)
    migrated_optional = sorted(set(operator) & optional_keys)
    warnings.extend(
        f"optional key should move to .env.prep.optional: {key}" for key in migrated_optional
    )

    effective = {key: operator[key] for key in allowed_operator if key in operator}
    effective.update({key: value for key, value in operator.items() if key in optional_keys})
    effective.update(optional)
    effective.update(runtime)
    for key in operator_optional:
        effective.setdefault(key, "")
    effective["POC_MCL_KAFKA_SSL"] = effective.get("POC_MCL_KAFKA_SSL", "").strip() or "false"
    no_proxy = merge_no_proxy(
        effective.get("NO_PROXY", ""),
        tuple(str(value) for value in contract.get("required_no_proxy", ())),
        effective.get("EXTERNAL_SERVICE_NO_PROXY", ""),
    )
    effective["NO_PROXY"] = no_proxy
    effective["no_proxy"] = no_proxy
    effective["http_proxy"] = effective.get("HTTP_PROXY", "")
    effective["https_proxy"] = effective.get("HTTPS_PROXY", "")
    runtime_proxy_configured = bool(
        effective.get("POC_RUNTIME_HTTP_PROXY", "").strip()
        or effective.get("POC_RUNTIME_HTTPS_PROXY", "").strip()
    )
    effective["POC_RUNTIME_NO_PROXY"] = (
        merge_no_proxy(
            effective.get("POC_RUNTIME_NO_PROXY", ""),
            tuple(str(value) for value in contract.get("required_runtime_no_proxy", ())),
        )
        if runtime_proxy_configured
        else ""
    )
    ca_source = effective.get("RUNTIME_CA_CERT_FILE", "").strip()
    if ca_source:
        ca_path = Path(ca_source)
        if not ca_path.is_absolute():
            raise PrepError(
                "ENVIRONMENT",
                "PREP_RUNTIME_CA_PATH_INVALID",
                "RUNTIME_CA_CERT_FILE must be one absolute target-local path.",
                "Set one existing absolute CA bundle path or leave the key blank.",
            )
        try:
            metadata = ca_path.lstat()
        except OSError as error:
            raise PrepError(
                "ENVIRONMENT",
                "PREP_RUNTIME_CA_FILE_MISSING",
                "The configured runtime CA bundle cannot be read.",
                "Correct RUNTIME_CA_CERT_FILE without committing the target CA.",
            ) from error
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size < 1
            or metadata.st_size > 1024 * 1024
        ):
            raise PrepError(
                "ENVIRONMENT",
                "PREP_RUNTIME_CA_FILE_UNSAFE",
                "The runtime CA bundle must be one bounded regular non-symlink file.",
                "Use an approved target-local CA bundle up to 1 MiB.",
            )
        effective["POC_RUNTIME_CA_BIND_SOURCE"] = os.fspath(ca_path)
        effective["POC_RUNTIME_CA_CONTAINER_FILE"] = "/run/datariver/runtime-ca.pem"
    else:
        effective["POC_RUNTIME_CA_BIND_SOURCE"] = "/dev/null"
        effective["POC_RUNTIME_CA_CONTAINER_FILE"] = ""
    return EnvironmentBundle(
        operator,
        optional,
        runtime,
        effective,
        tuple(warnings),
        target_state,
        k9_mode,
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


def child_environment(
    values: Mapping[str, str],
    *,
    parent: Mapping[str, str] | None = None,
) -> dict[str, str]:
    inherited = os.environ if parent is None else parent
    environment = {
        key: inherited[key] for key in HOST_SUBPROCESS_ENVIRONMENT_KEYS if key in inherited
    }
    environment.update({str(key): str(value) for key, value in values.items()})
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
        "--file",
        os.fspath(PREP_ARTIFACT_COMPOSE),
    ]


def web_start_command(prefix: Sequence[str], target_state: TargetState) -> list[str]:
    command = [*prefix, "up", "-d", "--no-build", "--wait"]
    if target_state is TargetState.EXISTING_OWNED_INCOMPLETE:
        command.extend(["--force-recreate", "--no-deps"])
    return [*command, "web"]


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


def _compose_service(config: Mapping[str, Any], service: str) -> Mapping[str, Any]:
    services = config.get("services")
    item = services.get(service) if isinstance(services, dict) else None
    if not isinstance(item, dict):
        raise PrepError(
            "COMPOSE_CONFIG",
            "PREP_COMPOSE_RELEASE_CONTRACT_MISMATCH",
            f"Compose omitted the canonical {service} service contract.",
            "Restore the tracked Compose and release environment contracts.",
        )
    return item


def _compose_port_binding(
    config: Mapping[str, Any],
    service: str,
    target: int,
) -> Mapping[str, Any]:
    ports = _compose_service(config, service).get("ports")
    matches = (
        [item for item in ports if isinstance(item, dict) and item.get("target") == target]
        if isinstance(ports, list)
        else []
    )
    if len(matches) != 1:
        raise PrepError(
            "COMPOSE_CONFIG",
            "PREP_COMPOSE_RELEASE_CONTRACT_MISMATCH",
            f"Compose {service} has no unique canonical host-port binding.",
            "Restore the tracked Compose and release environment contracts.",
        )
    return matches[0]


def validate_compose_release_contract(
    config: Mapping[str, Any],
    release: ReleaseIdentity,
    effective: Mapping[str, str],
) -> None:
    expected_image = f"datariver-poc:{release.product_sha}"
    web = _compose_service(config, "web")
    build = web.get("build")
    if (
        config.get("name") != release.project
        or resolve_web_image(config) != expected_image
        or web.get("platform") != release.platform
        or build is not None
        or web.get("pull_policy") != "never"
    ):
        raise PrepError(
            "COMPOSE_CONFIG",
            "PREP_COMPOSE_RELEASE_CONTRACT_MISMATCH",
            "Compose project, Product image, platform, or no-build identity differs "
            "from release.json.",
            "Use the tracked environment files; parent-shell Product values are not supported.",
        )

    expected_ports = (
        ("web", 8080, effective.get("POC_BIND_HOST", ""), str(release.port)),
        (
            "pgvector",
            5432,
            effective.get("POC_STATE_BIND_HOST", ""),
            effective.get("POC_POSTGRES_HOST_PORT", ""),
        ),
        (
            "neo4j",
            7474,
            effective.get("POC_STATE_BIND_HOST", ""),
            effective.get("POC_NEO4J_HTTP_PORT", ""),
        ),
        (
            "redis",
            6379,
            effective.get("POC_STATE_BIND_HOST", ""),
            effective.get("POC_REDIS_PORT", ""),
        ),
    )
    for service, target, host, published in expected_ports:
        binding = _compose_port_binding(config, service, target)
        if binding.get("host_ip") != host or str(binding.get("published", "")) != published:
            raise PrepError(
                "COMPOSE_CONFIG",
                "PREP_COMPOSE_RELEASE_CONTRACT_MISMATCH",
                f"Compose {service} host binding differs from the tracked PREP contract.",
                "Restore the tracked fixed port and bind-host values; do not use shell overrides.",
            )

    web_environment = _service_environment(config, "web")
    mismatched_keys = sorted(
        key
        for key, expected in effective.items()
        if key in web_environment and web_environment[key] != expected
    )
    if mismatched_keys:
        raise PrepError(
            "COMPOSE_CONFIG",
            "PREP_COMPOSE_ENVIRONMENT_DRIFT",
            "Compose Product/provider environment differs from the canonical effective contract.",
            "Remove no files; rerun from tracked source because shell overrides are ignored.",
        )


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
    schema_code = next(
        (code for code in SUPPORTED_POSTGRES_SCHEMA_FAILURE_CODES if code in private_output),
        None,
    )
    if schema_code:
        return PrepError(
            "POSTGRES_SCHEMA_INTEGRITY",
            schema_code,
            "The Product-owned PostgreSQL schema is partial, malformed or unsupported.",
            "Preserve the database and deployment receipts; do not reset or apply manual DDL.",
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
        if inventory.accepted_marker_present:
            _accepted_state_failure(
                "PREP_ACCEPTED_STATE_OWNERSHIP_UNPROVEN",
                "The accepted marker is not paired with one complete owned target state.",
            )
        _ambiguous_state("Existing PREP receipts, runtime secrets and persistent volumes disagree.")
    previous_attempt: Mapping[str, Any] | None = None
    if state in {
        TargetState.EXISTING_ACCEPTED_RUNNING,
        TargetState.EXISTING_ACCEPTED_STOPPED,
        TargetState.EXISTING_OWNED_INCOMPLETE,
    }:
        preserved_runtime = read_env_file(
            RUNTIME_ENV,
            private=True,
            label=".env.prep.runtime",
        )
        if state in {
            TargetState.EXISTING_ACCEPTED_RUNNING,
            TargetState.EXISTING_ACCEPTED_STOPPED,
        }:
            previous_attempt = validate_accepted_state(
                runner,
                release,
                source["handoff_commit"],
                inventory,
                preserved_runtime,
                k9_mode_from_operator(operator),
            )
            runner.note("Prove accepted target ownership and compatible source ancestry")
        else:
            previous_attempt = validate_owned_attempt(
                runner,
                release,
                source["handoff_commit"],
                inventory,
                preserved_runtime,
                k9_mode_from_operator(operator),
            )
            if inventory.accepted_marker_present:
                validate_prior_accepted_marker(
                    runner,
                    release,
                    inventory,
                    preserved_runtime,
                )
            runner.note(
                "Prove incomplete target ownership and source ancestry before reconciliation"
            )
    bundle = reconcile_environment(release, target_state=state)
    runner.environment = child_environment(bundle.effective)
    return bundle, DeploymentPreparation(
        runner,
        source,
        inventory,
        before_39080,
        previous_attempt,
    )


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


def ensure_git_transport_artifact(release: ReleaseIdentity) -> str:
    transport = release.git_transport
    artifact = release.web_artifact
    if transport is None:
        return "LEGACY_MANUAL_ARTIFACT_CONTRACT"
    if artifact is None:
        raise PrepError(
            "ARTIFACT_RETRIEVAL",
            "PREP_GIT_TRANSPORT_RELEASE_INVALID",
            "The Git transport has no exact Product artifact identity.",
            "Restore the exact dedicated PREP release snapshot and retry.",
        )
    try:
        return retrieve_git_artifact(
            transport,
            root=ROOT,
            artifact=artifact,
        )
    except TransportError as error:
        raise PrepError(
            "ARTIFACT_RETRIEVAL",
            "PREP_GIT_TRANSPORT_FAILED",
            "The pinned Git artifact could not be reconstructed and verified.",
            "Run ./scripts/prep39083 status; preserve the existing archive and PREP state.",
        ) from error


def sync_release_source(*, root: Path | None = None) -> str:
    repository = ROOT if root is None else root
    runner = Runner(environment=child_environment({}))
    if runner.output(["git", "rev-parse", "--show-toplevel"], cwd=repository) != os.fspath(
        repository
    ):
        raise PrepError(
            "SOURCE_SYNC",
            "PREP_RELEASE_REPOSITORY_INVALID",
            "The PREP command is not running from its canonical repository.",
            "Run the tracked ./scripts/prep39083 command from the PREP repository.",
        )
    if runner.output(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=repository,
    ):
        raise PrepError(
            "SOURCE_SYNC",
            "PREP_RELEASE_SOURCE_DIRTY",
            "Tracked PREP source files have local changes.",
            "Preserve and review those changes; do not overwrite them with release sync.",
        )
    try:
        runner.run(
            [
                "git",
                "fetch",
                "--no-tags",
                "origin",
                f"refs/heads/{PREP_RELEASE_BRANCH}:"
                f"refs/remotes/origin/{PREP_RELEASE_BRANCH}",
            ],
            cwd=repository,
        )
        target = runner.output(
            ["git", "rev-parse", f"origin/{PREP_RELEASE_BRANCH}"],
            cwd=repository,
        )
        current_branch = runner.output(["git", "branch", "--show-current"], cwd=repository)
        local = runner.run(
            ["git", "show-ref", "--verify", f"refs/heads/{PREP_RELEASE_BRANCH}"],
            check=False,
            cwd=repository,
        )
        if current_branch != PREP_RELEASE_BRANCH:
            if local.returncode == 0:
                runner.run(["git", "switch", PREP_RELEASE_BRANCH], cwd=repository)
            else:
                runner.run(
                    [
                        "git",
                        "switch",
                        "-c",
                        PREP_RELEASE_BRANCH,
                        f"origin/{PREP_RELEASE_BRANCH}",
                    ],
                    cwd=repository,
                )
        current = runner.output(["git", "rev-parse", "HEAD"], cwd=repository)
        if current != target:
            if (
                runner.run(
                    ["git", "merge-base", "--is-ancestor", current, target],
                    check=False,
                    cwd=repository,
                ).returncode
                != 0
            ):
                raise PrepError(
                    "SOURCE_SYNC",
                    "PREP_RELEASE_SOURCE_DIVERGED",
                    "The local PREP release branch is not an ancestor of the dedicated remote ref.",
                    "Preserve the checkout and inspect its source history; do not reset it.",
                )
            runner.run(["git", "merge", "--ff-only", target], cwd=repository)
        if runner.output(["git", "rev-parse", "HEAD"], cwd=repository) != target:
            raise PrepError(
                "SOURCE_SYNC",
                "PREP_RELEASE_SOURCE_SYNC_INCOMPLETE",
                "PREP source did not reach the exact dedicated release snapshot.",
                "Run ./scripts/prep39083 status and inspect Git connectivity.",
            )
        return target
    except CommandFailure as error:
        raise PrepError(
            "SOURCE_SYNC",
            "PREP_RELEASE_SOURCE_SYNC_FAILED",
            "The dedicated PREP release ref could not be fast-forwarded.",
            "Preserve local source and verify the existing Git authentication path.",
        ) from error


@contextmanager
def deployment_lock(action: str) -> Iterator[None]:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(DEPLOY_LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise PrepError(
                "DEPLOY_LOCK",
                "PREP_DEPLOY_ALREADY_ACTIVE",
                "Another stateful PREP operation owns the target-local lock.",
                "Run ./scripts/prep39083 status; do not start a duplicate deploy.",
            ) from error
        payload = json.dumps(
            {
                "contract": "DATARIVER_PREP39083_OPERATION_LOCK_V1",
                "action": action,
                "pid": os.getpid(),
                "started_at": datetime.now(UTC).isoformat(),
            },
            sort_keys=True,
        ).encode("utf-8")
        os.ftruncate(descriptor, 0)
        os.write(descriptor, payload)
        os.fsync(descriptor)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def deploy_lock_active(path: Path = DEPLOY_LOCK) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return False
    finally:
        os.close(descriptor)


def write_last_command(
    action: str,
    result: str,
    *,
    error: PrepError | None = None,
) -> None:
    payload: dict[str, object] = {
        "contract": "DATARIVER_PREP39083_LAST_COMMAND_V1",
        "action": action,
        "result": result,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    if error is not None:
        payload.update(
            {
                "step": error.step,
                "code": error.code,
                "reason": error.reason,
                "next_action": error.action,
            }
        )
    _atomic_json(LAST_COMMAND, payload)


@contextmanager
def command_log(action: str) -> Iterator[Path]:
    COMMAND_LOGS.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = COMMAND_LOGS / f"{timestamp}-{action}-{os.getpid()}.log"
    with path.open("x", encoding="utf-8") as stream:
        with redirect_stdout(_Tee(sys.stdout, stream)), redirect_stderr(_Tee(sys.stderr, stream)):
            yield path


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


def compose_volume_identities(config: Mapping[str, Any]) -> tuple[str, ...]:
    volumes = config.get("volumes")
    if not isinstance(volumes, dict):
        raise PrepError(
            "COMPOSE_CONFIG",
            "PREP_COMPOSE_VOLUME_IDENTITY_INVALID",
            "Compose omitted the canonical persistent volume identities.",
            "Restore the tracked Compose contract and retry.",
        )
    names = tuple(
        sorted(
            str(value.get("name"))
            for value in volumes.values()
            if isinstance(value, dict) and value.get("name")
        )
    )
    if len(names) != 3 or len(set(names)) != 3:
        raise PrepError(
            "COMPOSE_CONFIG",
            "PREP_COMPOSE_VOLUME_IDENTITY_INVALID",
            "Compose persistent volume identities are incomplete or duplicated.",
            "Restore the tracked pgvector/Neo4j volume contract and retry.",
        )
    return names


def legacy_runtime_env_fingerprint_v1(runtime: Mapping[str, str]) -> str:
    """Reproduce the retired V1 whole-runtime fingerprint for bounded migration only."""
    key = runtime.get("POC_MCP_SERVICE_TOKEN", "")
    if not key:
        raise PrepError(
            "TARGET_STATE",
            "PREP_RUNTIME_FINGERPRINT_UNAVAILABLE",
            "The target-local runtime ownership fingerprint cannot be derived.",
            "Restore the preserved .env.prep.runtime file and retry.",
        )
    excluded = {
        "POC_IMAGE_TAG",
        "POC_SOURCE_COMMIT",
        "PREP_RELEASE_PRODUCT_SHA",
        "PREP_RELEASE_EVIDENCE_SHA",
    }
    payload = json.dumps(
        {key_name: runtime[key_name] for key_name in sorted(runtime) if key_name not in excluded},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hmac.new(key.encode(), payload, hashlib.sha256).hexdigest()


def target_ownership_fingerprint(runtime: Mapping[str, str]) -> str:
    values = {key: runtime.get(key, "") for key in TARGET_OWNERSHIP_SECRET_KEYS}
    if any(not value or value == INSPECTION_PLACEHOLDER for value in values.values()):
        raise PrepError(
            "TARGET_STATE",
            "PREP_RUNTIME_FINGERPRINT_UNAVAILABLE",
            "The target-local ownership fingerprint cannot be derived.",
            "Restore the preserved .env.prep.runtime file and retry.",
        )
    payload = json.dumps(
        {"contract": OWNERSHIP_FINGERPRINT_CONTRACT, "generated": values},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hmac.new(values["POC_MCP_SERVICE_TOKEN"].encode(), payload, hashlib.sha256).hexdigest()


def canonical_volume_identities(release: ReleaseIdentity) -> tuple[str, ...]:
    return tuple(sorted(f"{release.project}_{name}" for name in PREP_VOLUME_LOGICAL_NAMES))


def _historical_env_contract(runner: Runner, handoff: str) -> dict[str, Any]:
    try:
        raw = runner.output(
            ["git", "show", f"{handoff}:deploy/prep39083/env-contract.json"],
        )
        contract = json.loads(raw)
    except (CommandFailure, json.JSONDecodeError):
        _ambiguous_state("The legacy attempt environment contract cannot be reconstructed.")
    if not isinstance(contract, dict) or contract.get("contract") not in {
        "DATARIVER_PREP39083_ENV_V3",
        "DATARIVER_PREP39083_ENV_V4",
        "DATARIVER_PREP39083_ENV_V5",
    }:
        _ambiguous_state(
            "The legacy attempt environment contract is outside the supported migration boundary."
        )
    _environment_ownership(contract)
    return contract


def _legacy_runtime_for_receipt(
    preserved_runtime: Mapping[str, str],
    historical_contract: Mapping[str, Any],
) -> dict[str, str]:
    current_contract = _read_json(ENV_CONTRACT, "environment contract")
    _, _, _, current_generated, current_fixed = _environment_ownership(current_contract)
    _, _, _, historical_generated, historical_fixed = _environment_ownership(
        historical_contract,
    )
    legacy = dict(preserved_runtime)
    for key in set(current_fixed) - set(historical_fixed):
        legacy.pop(str(key), None)
    for key in set(current_generated) - set(historical_generated):
        legacy.pop(str(key), None)
    for key, value in historical_fixed.items():
        legacy[str(key)] = str(value)
    return legacy


def _atomic_json(path: Path, payload: Mapping[str, Any], *, private: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600 if private else 0o644)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(f"{json.dumps(dict(payload), indent=2, sort_keys=True)}\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o600 if private else 0o644)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_attempt_receipt(
    release: ReleaseIdentity,
    handoff: str,
    bundle: EnvironmentBundle,
    volume_identities: Sequence[str],
    *,
    phase: str,
    previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if phase not in ATTEMPT_PHASES:
        raise ValueError("invalid deployment attempt phase")
    now = datetime.now(UTC).isoformat()
    payload: dict[str, Any] = {
        "contract": ATTEMPT_CONTRACT_V2,
        "product_sha": release.product_sha,
        "evidence_sha": release.evidence_sha,
        "handoff_commit": handoff,
        "project": release.project,
        "platform": release.platform,
        "port": release.port,
        "target_state_before": bundle.target_state.value,
        "ownership_fingerprint_contract": OWNERSHIP_FINGERPRINT_CONTRACT,
        "ownership_fingerprint": target_ownership_fingerprint(bundle.runtime),
        "volume_identities": sorted(set(volume_identities)),
        "k9_mode": bundle.k9_mode,
        "phase": phase,
        "started_at": previous.get("started_at", now) if previous else now,
        "updated_at": now,
    }
    if previous and previous.get("product_sha") != release.product_sha:
        payload["resumed_from_product_sha"] = previous.get("product_sha")
    if previous and previous.get("contract") != ATTEMPT_CONTRACT_V2:
        payload["migrated_from_contract"] = previous.get("contract")
    _atomic_json(ATTEMPT_RECEIPT, payload)
    return payload


def advance_attempt_phase(receipt: Mapping[str, Any], phase: str) -> dict[str, Any]:
    if phase not in ATTEMPT_PHASES:
        raise ValueError("invalid deployment attempt phase")
    payload = dict(receipt)
    payload["phase"] = phase
    payload["updated_at"] = datetime.now(UTC).isoformat()
    _atomic_json(ATTEMPT_RECEIPT, payload)
    return payload


def _accepted_state_failure(code: str, reason: str) -> NoReturn:
    raise PrepError(
        "TARGET_STATE",
        code,
        reason,
        "Preserve all containers, volumes, receipts and target-owned environment files; "
        "do not reset or treat this target as fresh.",
    )


def _attempt_fingerprint_matches(
    runner: Runner,
    receipt: Mapping[str, Any],
    preserved_runtime: Mapping[str, str],
) -> bool:
    if receipt.get("contract") == ATTEMPT_CONTRACT_V1:
        historical_contract = _historical_env_contract(
            runner,
            str(receipt["handoff_commit"]),
        )
        legacy_runtime = _legacy_runtime_for_receipt(
            preserved_runtime,
            historical_contract,
        )
        legacy_runtime["POC_K9_SCHEDULER_ENABLED"] = (
            "true" if receipt.get("k9_mode") == "REQUIRED" else "false"
        )
        return receipt.get("runtime_env_fingerprint") == legacy_runtime_env_fingerprint_v1(
            legacy_runtime
        )
    return receipt.get("ownership_fingerprint") == target_ownership_fingerprint(preserved_runtime)


def _git_is_ancestor(runner: Runner, ancestor: str, descendant: str) -> bool:
    return (
        runner.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            check=False,
        ).returncode
        == 0
    )


def validate_accepted_state(
    runner: Runner,
    release: ReleaseIdentity,
    handoff: str,
    inventory: TargetInventory,
    preserved_runtime: Mapping[str, str],
    expected_k9_mode: str,
) -> Mapping[str, Any]:
    marker = inventory.accepted_marker
    receipt = inventory.attempt_receipt
    if not inventory.accepted_marker_valid or not isinstance(marker, Mapping):
        _accepted_state_failure(
            "PREP_ACCEPTED_STATE_OWNERSHIP_UNPROVEN",
            "The accepted marker is absent, malformed or outside the supported marker contract.",
        )
    if (
        not inventory.attempt_receipt_valid
        or not isinstance(receipt, Mapping)
        or receipt.get("phase") != "ACCEPTED"
    ):
        _accepted_state_failure(
            "PREP_ACCEPTED_STATE_OWNERSHIP_UNPROVEN",
            "The accepted marker is not paired with one canonical ACCEPTED deployment receipt.",
        )
    expected_volumes = set(canonical_volume_identities(release))
    observed_volumes = {volume.name for volume in inventory.volumes}
    common_keys = ("product_sha", "evidence_sha", "handoff_commit")
    if (
        any(marker.get(key) != receipt.get(key) for key in common_keys)
        or receipt.get("project") != release.project
        or receipt.get("platform") != release.platform
        or receipt.get("port") != release.port
        or receipt.get("k9_mode") != expected_k9_mode
        or set(receipt.get("volume_identities", ())) != expected_volumes
        or observed_volumes != expected_volumes
    ):
        _accepted_state_failure(
            "PREP_ACCEPTED_STATE_OWNERSHIP_UNPROVEN",
            "The accepted marker, receipt and canonical target identity do not agree.",
        )
    if not _attempt_fingerprint_matches(runner, receipt, preserved_runtime):
        _accepted_state_failure(
            "PREP_ACCEPTED_STATE_FINGERPRINT_MISMATCH",
            "The accepted receipt no longer matches the preserved target-owned runtime secrets.",
        )
    if marker.get("contract") == ACCEPTED_CONTRACT_V2:
        if (
            marker.get("project") != release.project
            or marker.get("platform") != release.platform
            or marker.get("port") != release.port
            or marker.get("k9_mode") != expected_k9_mode
            or set(marker.get("volume_identities", ())) != expected_volumes
        ):
            _accepted_state_failure(
                "PREP_ACCEPTED_STATE_OWNERSHIP_UNPROVEN",
                "The accepted V2 marker no longer matches the canonical target identity.",
            )
        if marker.get("ownership_fingerprint") != target_ownership_fingerprint(preserved_runtime):
            _accepted_state_failure(
                "PREP_ACCEPTED_STATE_FINGERPRINT_MISMATCH",
                "The accepted V2 marker no longer matches the preserved target ownership.",
            )
    ancestry_pairs = (
        (str(receipt["product_sha"]), str(receipt["evidence_sha"])),
        (str(receipt["evidence_sha"]), str(receipt["handoff_commit"])),
        (str(receipt["product_sha"]), release.product_sha),
        (str(receipt["handoff_commit"]), handoff),
    )
    if any(
        not _git_is_ancestor(runner, ancestor, descendant)
        for ancestor, descendant in ancestry_pairs
    ):
        _accepted_state_failure(
            "PREP_ACCEPTED_STATE_LINEAGE_MISMATCH",
            "The accepted Product/Evidence/Handoff lineage is not compatible with this release.",
        )
    return receipt


def validate_prior_accepted_marker(
    runner: Runner,
    release: ReleaseIdentity,
    inventory: TargetInventory,
    preserved_runtime: Mapping[str, str],
) -> None:
    marker = inventory.accepted_marker
    receipt = inventory.attempt_receipt
    if not inventory.accepted_marker_valid or not isinstance(marker, Mapping):
        _accepted_state_failure(
            "PREP_ACCEPTED_STATE_OWNERSHIP_UNPROVEN",
            "The interrupted accepted-state update has no supported prior accepted marker.",
        )
    if not inventory.attempt_receipt_valid or not isinstance(receipt, Mapping):
        _accepted_state_failure(
            "PREP_ACCEPTED_STATE_OWNERSHIP_UNPROVEN",
            "The interrupted accepted-state update has no canonical owned attempt receipt.",
        )
    if receipt.get("target_state_before") not in {
        TargetState.EXISTING_ACCEPTED_RUNNING.value,
        TargetState.EXISTING_ACCEPTED_STOPPED.value,
        TargetState.EXISTING_OWNED_INCOMPLETE.value,
    }:
        _accepted_state_failure(
            "PREP_ACCEPTED_STATE_OWNERSHIP_UNPROVEN",
            "The accepted marker contradicts the recorded origin of the incomplete attempt.",
        )
    expected_volumes = set(canonical_volume_identities(release))
    if {volume.name for volume in inventory.volumes} != expected_volumes:
        _accepted_state_failure(
            "PREP_ACCEPTED_STATE_OWNERSHIP_UNPROVEN",
            "The interrupted accepted-state update no longer owns the canonical volumes.",
        )
    if marker.get("contract") == ACCEPTED_CONTRACT_V2:
        if (
            set(marker.get("volume_identities", ())) != expected_volumes
            or marker.get("project") != release.project
            or marker.get("platform") != release.platform
            or marker.get("port") != release.port
            or marker.get("ownership_fingerprint")
            != target_ownership_fingerprint(preserved_runtime)
        ):
            _accepted_state_failure(
                "PREP_ACCEPTED_STATE_FINGERPRINT_MISMATCH",
                "The prior accepted marker no longer matches target ownership.",
            )
    ancestry_pairs = (
        (str(marker["product_sha"]), str(marker["evidence_sha"])),
        (str(marker["evidence_sha"]), str(marker["handoff_commit"])),
        (str(marker["product_sha"]), str(receipt["product_sha"])),
        (str(marker["handoff_commit"]), str(receipt["handoff_commit"])),
    )
    if any(
        not _git_is_ancestor(runner, ancestor, descendant)
        for ancestor, descendant in ancestry_pairs
    ):
        _accepted_state_failure(
            "PREP_ACCEPTED_STATE_LINEAGE_MISMATCH",
            "The prior accepted marker is outside the interrupted update lineage.",
        )


def validate_owned_attempt(
    runner: Runner,
    release: ReleaseIdentity,
    handoff: str,
    inventory: TargetInventory,
    preserved_runtime: Mapping[str, str],
    expected_k9_mode: str,
) -> Mapping[str, Any]:
    receipt = inventory.attempt_receipt
    if not inventory.attempt_receipt_valid or not isinstance(receipt, dict):
        _ambiguous_state("The incomplete deployment receipt is absent or malformed.")
    expected_volumes = canonical_volume_identities(release)
    if (
        receipt.get("project") != release.project
        or receipt.get("platform") != release.platform
        or receipt.get("port") != release.port
        or receipt.get("k9_mode") != expected_k9_mode
        or sorted(receipt.get("volume_identities", ())) != sorted(expected_volumes)
        or {volume.name for volume in inventory.volumes} != set(expected_volumes)
    ):
        _ambiguous_state("The incomplete deployment receipt no longer matches target ownership.")
    if not _attempt_fingerprint_matches(runner, receipt, preserved_runtime):
        _ambiguous_state("The incomplete deployment receipt no longer matches target ownership.")
    for ancestor, descendant in (
        (str(receipt["product_sha"]), release.product_sha),
        (str(receipt["handoff_commit"]), handoff),
    ):
        if not _git_is_ancestor(runner, ancestor, descendant):
            _ambiguous_state(
                "The incomplete deployment receipt is outside current source ancestry."
            )
    return receipt


def _image_code(doctor: bool, suffix: str) -> str:
    return f"PREP_DOCTOR_IMAGE_{suffix}" if doctor else f"PREP_WEB_IMAGE_{suffix}"


def promoted_web_artifact_path(artifact: WebArtifactIdentity) -> Path:
    return ROOT / artifact.relative_path


def _read_web_image(
    runner: Runner,
    image: str,
    *,
    doctor: bool,
) -> Mapping[str, Any] | None:
    completed = runner.run(
        ["docker", "image", "inspect", "--platform", "linux/amd64", image],
        check=False,
    )
    if completed.returncode != 0:
        return None
    try:
        document = json.loads(completed.stdout)
        inspected = document[0]
    except (json.JSONDecodeError, IndexError, KeyError, TypeError) as error:
        raise PrepError(
            "IMAGE_IDENTITY",
            _image_code(doctor, "MISSING"),
            "Docker returned no bounded exact-image inspection contract.",
            "Preserve PREP state and rerun doctor from the exact tracked source.",
        ) from error
    if not isinstance(inspected, dict):
        raise PrepError(
            "IMAGE_IDENTITY",
            _image_code(doctor, "MISSING"),
            "Docker returned no bounded exact-image inspection contract.",
            "Preserve PREP state and rerun doctor from the exact tracked source.",
        )
    return inspected


def inspect_web_image(
    inspected: Mapping[str, Any],
    image: str,
    artifact: WebArtifactIdentity,
    *,
    doctor: bool,
) -> None:
    repo_tags = inspected.get("RepoTags")
    if not isinstance(repo_tags, list) or image not in repo_tags:
        raise PrepError(
            "IMAGE_IDENTITY",
            _image_code(doctor, "IDENTITY_MISMATCH"),
            "Docker inspection did not bind the exact requested Product image tag.",
            "Restore the exact tracked Compose image identity before retrying.",
        )
    config = inspected.get("Config")
    if not isinstance(config, dict):
        raise PrepError(
            "IMAGE_IDENTITY",
            _image_code(doctor, "MISSING"),
            "Docker returned no bounded exact-image configuration contract.",
            "Preserve PREP state and rerun the same command from tracked source.",
        )
    labels = config.get("Labels") or {}
    if not isinstance(labels, dict):
        raise PrepError(
            "IMAGE_IDENTITY",
            _image_code(doctor, "MISSING"),
            "Docker returned no bounded exact-image label contract.",
            "Preserve PREP state and rerun the same command from tracked source.",
        )
    if inspected.get("Os") != "linux" or inspected.get("Architecture") != "amd64":
        raise PrepError(
            "IMAGE_IDENTITY",
            _image_code(doctor, "PLATFORM_MISMATCH"),
            "The promoted web image is not linux/amd64.",
            "Restore the exact approved artifact; PREP does not rebuild images.",
        )
    if labels.get("org.opencontainers.image.revision") != artifact.product_sha:
        raise PrepError(
            "IMAGE_IDENTITY",
            _image_code(doctor, "REVISION_MISMATCH"),
            "The promoted web OCI revision does not equal the tracked Product SHA.",
            "Restore the exact approved artifact; PREP does not rebuild images.",
        )
    descriptor = inspected.get("Descriptor")
    descriptor_platform = descriptor.get("platform") if isinstance(descriptor, dict) else None
    if (
        not isinstance(descriptor, dict)
        or descriptor.get("mediaType") != "application/vnd.oci.image.manifest.v1+json"
        or descriptor.get("digest") != artifact.manifest_digest
        or (
            descriptor_platform is not None
            and descriptor_platform != {"architecture": "amd64", "os": "linux"}
        )
    ):
        raise PrepError(
            "IMAGE_IDENTITY",
            _image_code(doctor, "MANIFEST_MISMATCH"),
            "The loaded web image manifest does not equal the promoted immutable identity.",
            "Restore the exact approved artifact and rerun the same command without rebuilding.",
        )
    serialized = json.dumps({"Env": config.get("Env"), "Labels": labels}, sort_keys=True)
    if re.search(r"https?://[^\s\"']+@", serialized):
        raise PrepError(
            "IMAGE_IDENTITY",
            "PREP_PROXY_SECRET_PERSISTED",
            "The final image configuration appears to contain a credential-bearing proxy URL.",
            "Stop promotion and correct the Docker build proxy boundary.",
        )


def prepare_exact_web_image(
    runner: Runner,
    prefix: Sequence[str],
    image: str,
    release: ReleaseIdentity,
    *,
    doctor: bool,
) -> str:
    del prefix  # Compose build is intentionally unavailable on this release path.
    artifact = release.web_artifact
    if artifact is None:
        raise PrepError(
            "IMAGE_ARTIFACT",
            _image_code(doctor, "ARTIFACT_IDENTITY_INVALID"),
            "release.json does not bind one promoted web artifact.",
            "Restore release.json from the exact approved Handoff; do not rebuild on PREP.",
        )
    expected_image = f"datariver-poc:{release.product_sha}"
    if image != expected_image or image != artifact.image_reference:
        raise PrepError(
            "IMAGE_IDENTITY",
            _image_code(doctor, "IDENTITY_MISMATCH"),
            "Compose did not resolve the exact Product-tagged web image identity.",
            "Restore release.json and the canonical Compose image contract.",
        )

    archive = promoted_web_artifact_path(artifact)
    if not archive.exists():
        raise PrepError(
            "IMAGE_ARTIFACT",
            _image_code(doctor, "ARTIFACT_MISSING"),
            "The checksum-pinned promoted web image archive is missing.",
            "Stage the approved archive at its release.json path; do not rebuild on PREP.",
        )
    try:
        observed_checksum = sha256_file(archive)
    except OSError as error:
        raise PrepError(
            "IMAGE_ARTIFACT",
            _image_code(doctor, "ARTIFACT_UNREADABLE"),
            "The checksum-pinned promoted web image archive cannot be read.",
            "Restore the approved archive and rerun the same command without rebuilding.",
        ) from error
    if observed_checksum != artifact.archive_sha256:
        raise PrepError(
            "IMAGE_ARTIFACT",
            _image_code(doctor, "ARTIFACT_CHECKSUM_MISMATCH"),
            "The promoted web image archive checksum differs from release.json.",
            "Replace it with the approved archive; do not load or rebuild this candidate.",
        )
    try:
        observed_artifact = inspect_web_archive(archive)
        require_expected_identity(observed_artifact, artifact)
    except ArtifactError as error:
        raise PrepError(
            "IMAGE_ARTIFACT",
            _image_code(doctor, "ARTIFACT_CONTRACT_MISMATCH"),
            "The promoted web image archive identity differs from release.json.",
            "Restore the approved archive; do not load or rebuild this candidate.",
        ) from error

    inspected = _read_web_image(runner, image, doctor=doctor)
    if inspected is not None:
        inspect_web_image(inspected, image, artifact, doctor=doctor)
        return "REUSED_EXACT_ARTIFACT"

    try:
        runner.run(["docker", "image", "load", "--input", os.fspath(archive)])
    except CommandFailure as error:
        raise PrepError(
            "IMAGE_ARTIFACT",
            _image_code(doctor, "ARTIFACT_LOAD_FAILED"),
            "Docker could not load the checksum-verified promoted web image archive.",
            "Preserve PREP state, correct the local Docker load failure, and retry.",
        ) from error
    inspected = _read_web_image(runner, image, doctor=doctor)
    if inspected is None:
        raise PrepError(
            "IMAGE_IDENTITY",
            _image_code(doctor, "MISSING"),
            "The exact Product image is absent after its approved archive was loaded.",
            "Preserve PREP state and inspect the bounded Docker load result before retrying.",
        )
    inspect_web_image(inspected, image, artifact, doctor=doctor)
    return "LOADED_EXACT_ARTIFACT"


def snapshot_39080(runner: Runner) -> tuple[str, ...]:
    output = runner.output(
        [
            "docker",
            "ps",
            "--filter",
            "publish=39080",
            "--format",
            "{{.ID}} {{.Names}}",
        ]
    )
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
        tables_output = runner.output(
            [
                *command,
                "--command",
                "SELECT tablename FROM pg_catalog.pg_tables "
                "WHERE schemaname = 'public' ORDER BY tablename;",
            ]
        )
        counts: dict[str, int] = {}
        for table in filter(None, tables_output.splitlines()):
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", table):
                _ambiguous_state("The residual PostgreSQL schema contains an unclassifiable table.")
            raw_count = runner.output(
                [
                    *command,
                    "--command",
                    f'SELECT CASE WHEN EXISTS (SELECT 1 FROM public."{table}" LIMIT 1) '  # noqa: S608 -- identifier is strictly allowlisted above.
                    "THEN 1 ELSE 0 END;",
                ]
            )
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


def _neo4j_local_query(
    password: str,
    port: str,
    statements: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    if not password or password == INSPECTION_PLACEHOLDER:
        _ambiguous_state(
            "A residual Neo4j volume exists but its preserved target-local credential is absent.",
        )
    authorization = base64.b64encode(f"neo4j:{password}".encode()).decode("ascii")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/db/neo4j/tx/commit",
        data=json.dumps({"statements": list(statements)}).encode(),
        headers={"Authorization": f"Basic {authorization}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=30) as response:
            payload = json.loads(response.read())
        errors = payload.get("errors") if isinstance(payload, dict) else None
        results = payload.get("results") if isinstance(payload, dict) else None
        if errors or not isinstance(results, list) or len(results) != len(statements):
            raise ValueError("invalid Neo4j proof")
        return results
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as error:
        raise PrepError(
            "TARGET_STATE",
            "PREP_EXISTING_STATE_REQUIRES_OPERATOR_RECOVERY",
            "The residual Neo4j volume could not be inspected with its preserved credential.",
            "Preserve the volume and restore its matching target-local runtime environment.",
        ) from error


def inspect_neo4j_durable_nodes(password: str, port: str) -> int:
    results = _neo4j_local_query(
        password,
        port,
        ({"statement": "MATCH (n) RETURN count(n) AS count"},),
    )
    rows = results[0].get("data")
    count = rows[0].get("row", [None])[0] if isinstance(rows, list) and rows else None
    if not isinstance(count, int) or count < 0:
        _ambiguous_state("The residual Neo4j node-count proof was incomplete.")
    return count


def verify_neo4j_owned_projection(
    password: str,
    port: str,
    namespaces: Sequence[str],
) -> None:
    results = _neo4j_local_query(
        password,
        port,
        (
            {
                "statement": (
                    "MATCH (n) RETURN count(n) AS total, "
                    "count(CASE WHEN n:K9Node AND n.namespace IN $namespaces THEN 1 END) AS owned"
                ),
                "parameters": {"namespaces": list(namespaces)},
            },
            {
                "statement": (
                    "MATCH (a)-[r]->(b) RETURN count(r) AS total, "
                    "count(CASE WHEN a:K9Node AND b:K9Node AND a.namespace = b.namespace "
                    "AND a.namespace IN $namespaces THEN 1 END) AS owned"
                ),
                "parameters": {"namespaces": list(namespaces)},
            },
        ),
    )
    counts: list[tuple[int, int]] = []
    for result in results:
        rows = result.get("data")
        row = rows[0].get("row") if isinstance(rows, list) and rows else None
        if (
            not isinstance(row, list)
            or len(row) != 2
            or not all(isinstance(value, int) and value >= 0 for value in row)
        ):
            _ambiguous_state("The residual Neo4j ownership proof was incomplete.")
        counts.append((row[0], row[1]))
    if any(total != owned for total, owned in counts):
        _ambiguous_state(
            "The residual Neo4j volume contains data outside canonical managed K9 namespaces.",
        )


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
    statement = f"ALTER ROLE \"{username}\" WITH PASSWORD '{password.replace("'", "''")}';\n"
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
        completed = runner.run(
            [
                *prefix,
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "web",
                "node",
                "poc-prep-bootstrap.mjs",
                "inspect",
            ]
        )
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


def inspect_owned_partial_bootstrap(
    runner: Runner,
    prefix: Sequence[str],
    bundle: EnvironmentBundle,
) -> dict[str, Any]:
    try:
        completed = runner.run(
            [
                *prefix,
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "web",
                "node",
                "poc-prep-bootstrap.mjs",
                "inspect-owned-partial",
            ]
        )
        result = _parse_json_line(completed.stdout)
    except CommandFailure as error:
        try:
            failure = _parse_json_line(f"{error.stdout}\n{error.stderr}")
        except ValueError:
            raise classify_bootstrap_failure(error) from error
        code = str(failure.get("code", ""))
        if code.startswith("PREP_LEGACY_PARTIAL_") or code.startswith("PREP_SERVICE_"):
            _ambiguous_state(
                "The legacy partial deployment differs from its canonical bootstrap footprint.",
            )
        raise classify_bootstrap_failure(error) from error
    except ValueError as error:
        raise PrepError(
            "TARGET_STATE",
            "PREP_LEGACY_PARTIAL_RESULT_INVALID",
            "The legacy partial inspection returned no structured ownership result.",
            "Preserve all PREP state and inspect the bounded doctor output.",
        ) from error
    if result.get("status") != "OWNED_PARTIAL":
        _ambiguous_state("The legacy partial deployment did not prove canonical ownership.")
    footprint = result.get("footprint")
    namespaces = footprint.get("neo4j_namespaces") if isinstance(footprint, dict) else None
    if not isinstance(namespaces, list) or not all(isinstance(item, str) for item in namespaces):
        _ambiguous_state("The legacy partial deployment omitted its managed graph namespaces.")
    verify_neo4j_owned_projection(
        bundle.effective["NEO4J_PASSWORD"],
        bundle.effective["POC_NEO4J_HTTP_PORT"],
        namespaces,
    )
    return result


def run_provider_preflight(
    runner: Runner,
    image: str,
    env_file: Path,
    effective: Mapping[str, str],
) -> dict[str, Any]:
    completed = execute_provider_preflight_child(
        runner,
        image,
        env_file,
        effective,
        collect_all=False,
    )
    try:
        result = _parse_json_line(f"{completed.stdout}\n{completed.stderr}")
    except ValueError as error:
        if completed.returncode == 0:
            raise PrepError(
                "PROVIDER_PREFLIGHT",
                "PREP_PREFLIGHT_RESULT_INVALID",
                "Provider preflight returned no structured result.",
                "Restore the exact Product image and rerun deploy.",
            ) from error
        result = {}
    if completed.returncode != 0:
        failure = result
        code = str(failure.get("classification", "PREP_PREFLIGHT_INTERNAL_UNEXPECTED_FAILED"))
        if not (
            re.fullmatch(r"PREP_PREFLIGHT_[A-Z0-9_]+_FAILED", code)
            or re.fullmatch(r"PREP_MCL_DISCOVERY_[A-Z0-9_]+_FAILED", code)
        ):
            code = "PREP_PREFLIGHT_INTERNAL_UNEXPECTED_FAILED"
        stage = str(failure.get("stage", "PROVIDER"))
        if not re.fullmatch(r"[A-Z0-9_]{1,32}", stage):
            stage = "PROVIDER"
        action = {
            "PREP_PREFLIGHT_WEB_INTRANET_CIDR_CONFIG_FAILED": (
                "Correct only POC_INTRANET_HTTP_ALLOWED_CIDRS in .env.prep, then rerun "
                "the same deploy command."
            ),
            "PREP_PREFLIGHT_WEB_INTRANET_ORIGIN_NOT_APPROVED_FAILED": (
                "Approve the exact company intranet range in "
                "POC_INTRANET_HTTP_ALLOWED_CIDRS, then rerun the same deploy command."
            ),
            "PREP_PREFLIGHT_WEB_INTRANET_ORIGIN_MALFORMED_FAILED": (
                "Correct POC_PUBLIC_ORIGIN to one exact credential-free literal-IP origin, "
                "then rerun the same deploy command."
            ),
        }.get(code)
        if action is None:
            action = (
                "Preserve PREP state and inspect the sanitized stage classification before "
                "rerunning the same deploy command."
                if "_UNEXPECTED_" in code
                else "Correct only the named provider configuration, then rerun the same "
                "deploy command."
            )
        raise PrepError(
            "PROVIDER_PREFLIGHT",
            code,
            f"Read-only {stage} provider preflight failed before persistent Product mutation.",
            action,
        )
    if (
        result.get("contract") != "DATARIVER_PREP39083_PROVIDER_PREFLIGHT_V2"
        or result.get("status") != "PASS"
    ):
        raise PrepError(
            "PROVIDER_PREFLIGHT",
            "PREP_PREFLIGHT_RESULT_INVALID",
            "Provider preflight did not report PASS.",
            "Correct the named provider configuration and rerun deploy.",
        )
    return result


DOCTOR_PREFLIGHT_STAGES = (
    "WEB_INTRANET",
    "DATAHUB",
    "QUALITY_READ",
    "CHAT",
    "EMBEDDING",
    "RERANKER",
    "MCL_DISCOVERY",
    "AIRFLOW",
    "MINIO",
)


def provider_preflight_container_prefix(
    image: str,
    env_file: Path,
    effective: Mapping[str, str],
) -> list[str]:
    command = [
        "docker",
        "run",
        "--rm",
        "--platform",
        "linux/amd64",
        "--env-file",
        os.fspath(env_file),
        "--read-only",
        "--user",
        "1000:1000",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
    ]
    ca_source = effective.get("POC_RUNTIME_CA_BIND_SOURCE", "")
    ca_target = effective.get("POC_RUNTIME_CA_CONTAINER_FILE", "")
    if ca_source and ca_source != "/dev/null" and ca_target:
        command.extend(
            [
                "--mount",
                f"type=bind,source={ca_source},target={ca_target},readonly",
            ]
        )
    command.extend(["--env", f"POC_RUNTIME_CA_CERT_FILE={ca_target}", image])
    return command


def execute_provider_preflight_child(
    runner: Runner,
    image: str,
    env_file: Path,
    effective: Mapping[str, str],
    *,
    collect_all: bool,
) -> subprocess.CompletedProcess[str]:
    child_prefix = provider_preflight_container_prefix(image, env_file, effective)
    mode = "doctor" if collect_all else "deploy"
    container_code = (
        "PREP_DOCTOR_PREFLIGHT_CONTAINER_START_FAILED"
        if collect_all
        else "PREP_PREFLIGHT_CONTAINER_START_FAILED"
    )
    node_code = (
        "PREP_DOCTOR_PREFLIGHT_NODE_START_FAILED"
        if collect_all
        else "PREP_PREFLIGHT_NODE_START_FAILED"
    )
    container_probe = runner.run([*child_prefix, "/usr/bin/true"], check=False)
    if container_probe.returncode != 0:
        raise PrepError(
            "PROVIDER_PREFLIGHT",
            container_code,
            f"Docker could not create the ephemeral {mode} Product container.",
            f"Inspect only Docker image and container policy, then rerun {mode}.",
        )
    node_probe = runner.run([*child_prefix, "node", "--version"], check=False)
    if node_probe.returncode != 0:
        raise PrepError(
            "PROVIDER_PREFLIGHT",
            node_code,
            f"The pinned Node runtime could not start in the ephemeral {mode} container.",
            f"Restore the exact Product image and rerun {mode}.",
        )
    module_probe = runner.run(
        [
            *child_prefix,
            "node",
            "--input-type=module",
            "--eval",
            "await import('./poc-provider-preflight.mjs')",
        ],
        check=False,
    )
    if module_probe.returncode != 0:
        raise PrepError(
            "PROVIDER_PREFLIGHT",
            node_code,
            "The pinned Node runtime or provider-preflight module could not start in the "
            f"ephemeral {mode} container.",
            f"Restore the exact Product image and rerun {mode}.",
        )
    arguments = [*child_prefix, "node", "poc-provider-preflight.mjs"]
    if collect_all:
        arguments.append("--collect-all")
    return runner.run(arguments, check=False)


def collect_provider_preflight(
    runner: Runner,
    image: str,
    env_file: Path,
    effective: Mapping[str, str],
) -> dict[str, Any]:
    completed = execute_provider_preflight_child(
        runner,
        image,
        env_file,
        effective,
        collect_all=True,
    )
    try:
        result = _parse_json_line(f"{completed.stdout}\n{completed.stderr}")
    except ValueError as error:
        raise PrepError(
            "PROVIDER_PREFLIGHT",
            "PREP_DOCTOR_PREFLIGHT_MATRIX_RESULT_INVALID",
            "Collect-all provider doctor returned no structured matrix.",
            "Restore the exact Product image and rerun doctor.",
        ) from error
    stages = result.get("stages")
    if (
        result.get("contract") != "DATARIVER_PREP39083_PROVIDER_PREFLIGHT_MATRIX_V1"
        or result.get("status") not in {"PASS", "FAILED"}
        or not isinstance(stages, dict)
        or set(stages) != set(DOCTOR_PREFLIGHT_STAGES)
    ):
        raise PrepError(
            "PROVIDER_PREFLIGHT",
            "PREP_DOCTOR_PREFLIGHT_MATRIX_RESULT_INVALID",
            "Collect-all provider doctor returned an invalid matrix contract.",
            "Restore the exact Product image and rerun doctor.",
        )
    for stage in DOCTOR_PREFLIGHT_STAGES:
        entry = stages[stage]
        if not isinstance(entry, dict) or entry.get("status") not in {
            "READY",
            "DEFERRED",
            "FAILED",
            "BLOCKED_BY_DEPENDENCY",
        }:
            raise PrepError(
                "PROVIDER_PREFLIGHT",
                "PREP_DOCTOR_PREFLIGHT_MATRIX_RESULT_INVALID",
                "Collect-all provider doctor returned an invalid stage result.",
                "Restore the exact Product image and rerun doctor.",
            )
        classification = entry.get("classification")
        if entry["status"] == "FAILED" and not (
            isinstance(classification, str)
            and (
                re.fullmatch(r"PREP_PREFLIGHT_[A-Z0-9_]+_FAILED", classification)
                or re.fullmatch(r"PREP_MCL_DISCOVERY_[A-Z0-9_]+_FAILED", classification)
            )
        ):
            raise PrepError(
                "PROVIDER_PREFLIGHT",
                "PREP_DOCTOR_PREFLIGHT_MATRIX_RESULT_INVALID",
                "Collect-all provider doctor returned an unbounded failure code.",
                "Restore the exact Product image and rerun doctor.",
            )
    expected_returncode = 0 if result["status"] == "PASS" else 2
    if completed.returncode != expected_returncode:
        raise PrepError(
            "PROVIDER_PREFLIGHT",
            "PREP_DOCTOR_PREFLIGHT_MATRIX_RESULT_INVALID",
            "Collect-all provider doctor process status conflicts with its matrix.",
            "Restore the exact Product image and rerun doctor.",
        )
    return result


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
            command.extend(
                [
                    "--user",
                    "0:0",
                    "--volume",
                    f"{password_path}:/run/prep-admin.password:ro",
                ]
            )
        command.extend(["web", "node", "poc-prep-bootstrap.mjs", "reconcile"])
        if created:
            command.extend(
                [
                    "--admin-username",
                    username,
                    "--admin-password-file",
                    "/run/prep-admin.password",
                ]
            )
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
    request_origin: str,
    k9_mode: str,
    glossary_term_urn: str = "",
) -> None:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    output = RUNTIME_ROOT / "smoke.json"
    if output.exists():
        output.unlink()
    if SMOKE_FAILURE.exists():
        SMOKE_FAILURE.unlink()
    if K9_PROGRESS.exists():
        K9_PROGRESS.unlink()
    with private_password_file(password) as password_path:
        try:
            command: list[str | os.PathLike[str]] = [
                "node",
                SMOKE_TOOL,
                "--origin",
                f"http://127.0.0.1:{release.port}",
                "--request-origin",
                request_origin,
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
                "--failure-output",
                SMOKE_FAILURE,
                "--progress-output",
                K9_PROGRESS,
            ]
            if glossary_term_urn.strip():
                command.extend(["--glossary-term-urn", glossary_term_urn.strip()])
            runner.run(command, visible=True)
        except CommandFailure as error:
            try:
                failure = _read_json(SMOKE_FAILURE, "sanitized smoke failure")
            except PrepError:
                failure = {}
            code = str(failure.get("classification", "PREP_SMOKE_UNKNOWN_FAILED"))
            if (
                code not in SUPPORTED_DATAHUB_INVENTORY_FAILURE_CODES
                and code not in SUPPORTED_GLOSSARY_SMOKE_FAILURE_CODES
                and code not in SUPPORTED_K9_SMOKE_FAILURE_CODES
                and code not in SUPPORTED_MCL_SMOKE_FAILURE_CODES
                and not re.fullmatch(r"PREP_SMOKE_[A-Z0-9_]+_FAILED", code)
            ):
                code = "PREP_SMOKE_UNKNOWN_FAILED"
            if (
                code.startswith("PREP_SMOKE_GENERAL_PROVIDER_")
                and code not in SUPPORTED_GENERAL_PROVIDER_FAILURE_CODES
            ):
                code = "PREP_SMOKE_UNKNOWN_FAILED"
            if (
                code.startswith("PREP_SMOKE_GLOSSARY_TERM_")
                and code not in SUPPORTED_GLOSSARY_SMOKE_FAILURE_CODES
            ):
                code = "PREP_SMOKE_UNKNOWN_FAILED"
            if code == "PREP_SMOKE_ADMIN_AUTH_FAILED":
                action = "Rerun deploy with the correct existing administrator password."
            elif code == "PREP_SMOKE_ADMIN_ORIGIN_FAILED":
                action = (
                    "Preserve PREP state and verify the smoke request uses the exact canonical "
                    "POC_PUBLIC_ORIGIN before rerunning the same deploy command."
                )
            else:
                action = (
                    "Correct the classified provider/readiness gate and rerun the same deploy "
                    "command; do not reset persistent state."
                )
            smoke_step = (
                "DATAHUB_GLOSSARY_TERM"
                if code in SUPPORTED_GLOSSARY_SMOKE_FAILURE_CODES
                else "K9_INITIAL_REFRESH"
                if "_K9_" in code or code == "PREP_SMOKE_SEMANTIC_INDEX_NOT_READY"
                else "MCL_INITIAL_CAPTURE"
                if "_MCL_" in code
                else "AUTHENTICATED_SMOKE"
            )
            raise PrepError(
                smoke_step,
                code,
                "Authenticated PREP smoke did not complete at its classified stage.",
                action,
            ) from error


def write_accepted_marker(
    release: ReleaseIdentity,
    handoff: str,
    *,
    attempt: Mapping[str, Any],
    target_state: TargetState,
    k9_mode: str,
) -> None:
    payload = {
        "contract": ACCEPTED_CONTRACT_V2,
        "product_sha": release.product_sha,
        "evidence_sha": release.evidence_sha,
        "handoff_commit": handoff,
        "project": release.project,
        "platform": release.platform,
        "port": release.port,
        "initial_target_state": target_state.value,
        "k9_mode": k9_mode,
        "ownership_fingerprint_contract": OWNERSHIP_FINGERPRINT_CONTRACT,
        "ownership_fingerprint": attempt.get("ownership_fingerprint"),
        "volume_identities": sorted(set(attempt.get("volume_identities", ()))),
        "accepted_at": datetime.now(UTC).isoformat(),
    }
    if (
        payload["ownership_fingerprint_contract"] != attempt.get("ownership_fingerprint_contract")
        or not isinstance(payload["ownership_fingerprint"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", payload["ownership_fingerprint"])
        or set(payload["volume_identities"]) != set(canonical_volume_identities(release))
    ):
        _accepted_state_failure(
            "PREP_ACCEPTED_STATE_OWNERSHIP_UNPROVEN",
            "The accepted marker cannot be bound to the completed owned attempt.",
        )
    _atomic_json(ACCEPTED_MARKER, payload)


@contextmanager
def typed_deploy_gate(
    step: str,
    code: str,
    reason: str,
    action: str = "Preserve PREP state, inspect doctor/logs, and rerun the same deploy command.",
) -> Iterator[None]:
    try:
        yield
    except PrepError:
        raise
    except (CommandFailure, OSError, ValueError) as error:
        raise PrepError(step, code, reason, action) from error


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

    runner.note("Validate private environment ownership and Compose contract")
    with private_effective_environment(bundle.effective) as env_file:
        prefix = compose_prefix(release, env_file)
        config = compose_config(runner, prefix)
        validate_compose_release_contract(config, release, bundle.effective)
        image = resolve_web_image(config)
        volume_identities = compose_volume_identities(config)
        runner.note("Verify and load the checksum-pinned linux/amd64 Product artifact")
        prepare_exact_web_image(
            runner,
            prefix,
            image,
            release,
            doctor=False,
        )
        runner.note("Run read-only external provider preflight before persistent mutation")
        preflight = run_provider_preflight(
            runner,
            image,
            env_file,
            bundle.effective,
        )
        print(
            "Provider preflight: DataHub/Chat/Embedding/Reranker/K9/MCL/GX read PASS; "
            f"GX execution {preflight.get('gx_quality_execution', 'UNKNOWN')}",
            flush=True,
        )

        previous_attempt = preparation.previous_attempt
        with typed_deploy_gate(
            "TARGET_STATE",
            "PREP_TARGET_STATE_RECONCILIATION_FAILED",
            "The proven PREP target state could not be reconciled without mutation ambiguity.",
        ):
            if bundle.target_state is TargetState.EXISTING_OWNED_INCOMPLETE:
                if not isinstance(previous_attempt, Mapping):
                    _ambiguous_state(
                        "The incomplete deployment was not ownership-validated "
                        "before reconciliation."
                    )
                if sorted(previous_attempt.get("volume_identities", ())) != sorted(
                    volume_identities,
                ):
                    _ambiguous_state(
                        "The current Compose volume contract differs from the proven "
                        "target ownership."
                    )
                runner.note("Retain proven owned incomplete receipt for idempotent resume")
            elif bundle.target_state is (
                TargetState.LEGACY_SELF_BOOTSTRAPPED_PARTIAL_REQUIRES_INSPECTION
            ):
                runner.note(
                    "Inspect legacy self-bootstrap state through canonical identity contracts"
                )
                runner.run([*prefix, "up", "-d", "--wait", "pgvector", "neo4j", "redis"])
                inspect_owned_partial_bootstrap(runner, prefix, bundle)
                bundle = replace(
                    bundle,
                    target_state=TargetState.LEGACY_SELF_BOOTSTRAPPED_PARTIAL,
                )
                runner.note("Classify legacy state: LEGACY_SELF_BOOTSTRAPPED_PARTIAL")
            elif bundle.target_state is TargetState.FAILED_FIRST_INSTALL_REQUIRES_INSPECTION:
                state = prove_failed_install_recoverable(
                    runner,
                    release,
                    bundle,
                    preparation.inventory,
                )
                runner.note(f"Prove residual target state: {state.value}")
                bundle = reconcile_environment(release, target_state=state)
                runner.environment = child_environment(bundle.effective)

    # A proven residual recovery generates/persists its runtime secrets only after inspection,
    # so render the final Compose environment again before the attempt becomes mutation owner.
    with private_effective_environment(bundle.effective) as env_file:
        prefix = compose_prefix(release, env_file)
        config = compose_config(runner, prefix)
        validate_compose_release_contract(config, release, bundle.effective)
        final_volumes = compose_volume_identities(config)
        if final_volumes != volume_identities:
            _ambiguous_state(
                "The final Compose persistent volume identity changed after preflight."
            )
        with typed_deploy_gate(
            "TARGET_STATE",
            "PREP_ATTEMPT_RECEIPT_WRITE_FAILED",
            "The owned deployment attempt could not be recorded atomically.",
        ):
            attempt = write_attempt_receipt(
                release,
                source["handoff_commit"],
                bundle,
                final_volumes,
                phase="PREPARED",
                previous=previous_attempt,
            )
        if (
            bundle.target_state is TargetState.FAILED_FIRST_INSTALL_RECOVERABLE
            and "pgvector-data" in preparation.inventory.volume_names
        ):
            runner.note(
                "Reconcile proven-disposable PostgreSQL role credential without volume reset",
            )
            reconcile_recoverable_postgres_credential(runner, prefix, bundle)
        runner.note("Start isolated PostgreSQL, Neo4j and Redis and wait for health")
        with typed_deploy_gate(
            "STATE_SERVICES",
            "PREP_STATE_SERVICES_FAILED",
            "PostgreSQL, Neo4j or Redis did not reach the bounded healthy state.",
        ):
            runner.run([*prefix, "up", "-d", "--wait", "pgvector", "neo4j", "redis"])
            attempt = advance_attempt_phase(attempt, "STATE_SERVICES_READY")
        runner.note("Apply idempotent state initialization and inspect target-local identities")
        with typed_deploy_gate(
            "SCHEMA",
            "PREP_SCHEMA_INITIALIZATION_FAILED",
            "Idempotent PostgreSQL schema initialization or inspection failed.",
        ):
            inspected = inspect_bootstrap(runner, prefix)
            attempt = advance_attempt_phase(attempt, "SCHEMA_READY")
        with typed_deploy_gate(
            "BOOTSTRAP",
            "PREP_BOOTSTRAP_RECONCILIATION_FAILED",
            "Target-local administrator or service identity reconciliation failed.",
        ):
            username, password = reconcile_bootstrap(runner, prefix, inspected)
            attempt = advance_attempt_phase(attempt, "BOOTSTRAP_READY")
        runner.note("Start exact Product web service and verify internal and host health")
        with typed_deploy_gate(
            "WEB_START",
            "PREP_WEB_START_FAILED",
            "The exact Product web service could not start under the Compose contract.",
        ):
            # A proven incomplete same-Product attempt may leave a healthy Web
            # container running. Recreate only that stateless service so startup
            # resumes persisted V2 projector receipts; state services and volumes
            # remain untouched. Accepted reruns continue to reuse the healthy Web.
            runner.run(web_start_command(prefix, bundle.target_state))
            web_id = runner.output([*prefix, "ps", "-q", "web"])
        if (
            not web_id
            or runner.output(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{.State.Health.Status}}",
                    web_id,
                ]
            )
            != "healthy"
        ):
            raise PrepError(
                "WEB_HEALTH",
                "PREP_INTERNAL_WEB_UNHEALTHY",
                "Docker internal web health is not healthy.",
                "Run ./scripts/prep39083 logs; do not reset persistent volumes.",
            )
        try:
            runner.run(
                [
                    "curl",
                    "--fail",
                    "--silent",
                    "--show-error",
                    "--noproxy",
                    "*",
                    f"http://127.0.0.1:{release.port}/healthz",
                ]
            )
        except CommandFailure as error:
            raise PrepError(
                "WEB_HEALTH",
                "PREP_HOST_39083_UNREACHABLE",
                "Docker is healthy but host port 39083 is not reachable without the proxy.",
                "Check WSL port binding and host firewall; the application container is healthy.",
            ) from error
        attempt = advance_attempt_phase(attempt, "WEB_READY")
        runner.note("Run authenticated provider, managed-graph and GENERAL smoke")
        attempt = advance_attempt_phase(attempt, "SMOKE_RUNNING")
        try:
            with typed_deploy_gate(
                "AUTHENTICATED_SMOKE",
                "PREP_AUTHENTICATED_SMOKE_FAILED",
                "Authenticated PREP smoke failed outside a more precise Product classification.",
            ):
                run_smoke(
                    runner,
                    release,
                    username,
                    password,
                    request_origin=bundle.effective["POC_PUBLIC_ORIGIN"],
                    k9_mode=bundle.k9_mode,
                    glossary_term_urn=bundle.effective.get("PREP_GLOSSARY_TERM_URN", ""),
                )
        except PrepError:
            advance_attempt_phase(attempt, "SMOKE_FAILED")
            raise
        after_39080 = snapshot_39080(runner)
        if after_39080 != before_39080:
            raise PrepError(
                "ISOLATION",
                "PREP_39080_CHANGED",
                "The existing 39080 container set changed during deployment.",
                "Stop and investigate; do not promote this PREP result.",
            )
        with typed_deploy_gate(
            "ACCEPTED_RECEIPT",
            "PREP_ACCEPTANCE_RECEIPT_WRITE_FAILED",
            "Authenticated gates passed but accepted deployment evidence was not "
            "recorded atomically.",
        ):
            write_accepted_marker(
                release,
                source["handoff_commit"],
                attempt=attempt,
                target_state=bundle.target_state,
                k9_mode=bundle.k9_mode,
            )
            advance_attempt_phase(attempt, "ACCEPTED")
    print("\nPREP39083 DEPLOYMENT READY")
    print("\nRelease")
    print(f"- Product: {release.product_sha}")
    print(f"- Evidence: {release.evidence_sha}")
    print(f"- Handoff: {source['handoff_commit']}")
    print("- Platform: linux/amd64")
    print("\nRuntime")
    print(f"- Initial state: {bundle.target_state.value}")
    print("- Web Intranet: READY")
    print(f"- Port: {release.port}")
    print("- PostgreSQL: healthy")
    print("- Neo4j: healthy")
    print("- Redis: healthy")
    print("- 39080: untouched")
    print("\nProviders")
    print("- DataHub: ready")
    print("- Chat: ready")
    print("- Embedding/Reranker: READY; managed semantic index READY")
    print("- K9 Built-in Graphs: DAILY / READY")
    print("- MCL Change History: READY")
    print("- GX Quality Read: READY")
    print(f"- GX Quality Execution: {preflight.get('gx_quality_execution', 'DEFERRED')}")
    print(f"- Airflow: {preflight.get('airflow', 'DEFERRED')}")
    print(f"- MinIO: {preflight.get('minio', 'DEFERRED')}")
    print("\nAuthentication")
    print(f"- Admin: existing/created and smoke verified ({username})")
    print(f"\nNext\n- Browser: {bundle.effective['POC_PUBLIC_ORIGIN']}")


def doctor(release: ReleaseIdentity, bundle: EnvironmentBundle) -> None:
    runner = Runner(environment=child_environment(bundle.effective))
    require_prep_platform(runner)
    source = verify_source_identity(release)
    with private_effective_environment(bundle.effective) as env_file:
        config = compose_config(runner, compose_prefix(release, env_file))
        validate_compose_release_contract(config, release, bundle.effective)
        prefix = compose_prefix(release, env_file)
        image = resolve_web_image(config)
        runner.note("Verify and load the exact read-only doctor Product artifact")
        image_preparation = prepare_exact_web_image(
            runner,
            prefix,
            image,
            release,
            doctor=True,
        )
        runner.note("Run collect-all provider diagnostics in an ephemeral Product container")
        preflight = collect_provider_preflight(
            runner,
            image,
            env_file,
            bundle.effective,
        )
    print(f"PREP39083 DOCTOR {preflight['status']}")
    print(f"- Product: {release.product_sha}")
    print(f"- Evidence: {release.evidence_sha}")
    print(f"- Handoff: {source['handoff_commit']}")
    print(f"- Image: {image}")
    print(f"- Image preparation: {image_preparation}")
    print(f"- Environment warnings: {len(bundle.warnings)}")
    stages = preflight["stages"]
    for stage in DOCTOR_PREFLIGHT_STAGES:
        entry = stages[stage]
        suffix = ""
        if entry["status"] == "FAILED":
            suffix = f" / {entry['classification']}"
        elif entry["status"] == "BLOCKED_BY_DEPENDENCY":
            suffix = f" / {entry.get('dependency', 'DEPENDENCY')}"
        print(f"- {stage}: {entry['status']}{suffix}")
    quality_execution = "READY" if stages["AIRFLOW"]["status"] == "READY" else "DEFERRED"
    print(f"- QUALITY_EXECUTION: {quality_execution}")
    if preflight["status"] != "PASS":
        failed = next(
            (
                entry.get("classification")
                for entry in stages.values()
                if entry["status"] == "FAILED"
            ),
            "PREP_DOCTOR_PREFLIGHT_DEPENDENCY_BLOCKED",
        )
        raise PrepError(
            "PROVIDER_PREFLIGHT",
            failed,
            "Collect-all doctor found one or more unavailable required provider stages.",
            "Correct only the typed failed stage, then rerun the same doctor command.",
        )


def _optional_json(path: Path) -> Mapping[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def status(release: ReleaseIdentity) -> None:
    active = deploy_lock_active()
    attempt = _optional_json(ATTEMPT_RECEIPT)
    accepted = _optional_json(ACCEPTED_MARKER)
    last = _optional_json(LAST_COMMAND)
    smoke_failure = _optional_json(SMOKE_FAILURE)
    smoke_report = _optional_json(SMOKE_REPORT)
    k9_progress = _optional_json(K9_PROGRESS)
    phase = str(attempt.get("phase", "NONE")) if attempt else "NONE"
    accepted_product = str(accepted.get("product_sha", "NONE")) if accepted else "NONE"
    target_state = str(attempt.get("target_state_before", "UNKNOWN")) if attempt else "UNKNOWN"
    last_result = str(last.get("result", phase)) if last else phase
    failed_step = str(last.get("step", "NONE")) if last_result == "FAILED" and last else "NONE"
    code = str(last.get("code", "NONE")) if last_result == "FAILED" and last else "NONE"
    if active:
        next_action = "Wait for the active command; run ./scripts/prep39083 status again."
    elif last_result == "FAILED" and last:
        next_action = str(last.get("next_action", "Run ./scripts/prep39083 doctor."))
    elif phase == "ACCEPTED" and accepted_product == release.product_sha:
        next_action = "No action required; rerun deploy only for an explicit acceptance check."
    elif phase in ATTEMPT_PHASES and phase not in {"ACCEPTED", "NONE"}:
        next_action = "Run ./scripts/prep39083 deploy to resume the owned attempt."
    else:
        next_action = "Run ./scripts/prep39083 deploy."

    runner = Runner(environment=child_environment({}))
    web = "UNKNOWN"
    containers = runner.run(
        [
            "docker",
            "ps",
            "--all",
            "--filter",
            f"label=com.docker.compose.project={release.project}",
            "--format",
            '{{.Label "com.docker.compose.service"}}|{{.State}}|{{.Status}}',
        ],
        check=False,
    )
    if containers.returncode == 0:
        web_lines = [line for line in containers.stdout.splitlines() if line.startswith("web|")]
        if len(web_lines) == 1:
            web = (
                "HEALTHY"
                if "(healthy)" in web_lines[0]
                else web_lines[0].split("|", 2)[1].upper()
            )
        elif not web_lines:
            web = "ABSENT"
    ready = phase == "ACCEPTED" and accepted_product == release.product_sha
    failed_stage = str(smoke_failure.get("stage", "")) if smoke_failure else ""
    smoke_diagnostic = smoke_failure.get("diagnostic", {}) if smoke_failure else {}
    if not isinstance(smoke_diagnostic, dict):
        smoke_diagnostic = {}
    readiness = smoke_report.get("readiness", {}) if smoke_report else {}
    if not isinstance(readiness, dict):
        readiness = {}
    lifecycle = smoke_report.get("k9_lifecycle", {}) if smoke_report else {}
    if (
        not isinstance(lifecycle, dict)
        or lifecycle.get("contract") != "DATARIVER_K9_LIFECYCLE_STATUS_V2"
    ):
        lifecycle = {}

    def lane_state(name: str) -> str | None:
        value = readiness.get(name)
        if not isinstance(value, dict):
            return None
        status_value = value.get("status")
        return (
            str(status_value)
            if status_value in {"PASS", "FAILED", "PENDING", "DEFERRED"}
            else None
        )

    k9_lane = lane_state("K9")
    mcl_lane = lane_state("MCL")
    general_lane = lane_state("GENERAL")
    k9 = (
        "READY" if k9_lane == "PASS"
        else k9_lane if k9_lane in {"FAILED", "PENDING", "DEFERRED"}
        else "READY" if ready
        else "FAILED" if failed_stage.startswith("K9")
        else "UNKNOWN"
    )
    if active and isinstance(k9_progress, dict) and k9_progress.get("k9") == "RUNNING":
        k9 = "RUNNING"
    lifecycle_projectors = lifecycle.get("projectors", {})
    if not isinstance(lifecycle_projectors, dict):
        lifecycle_projectors = {}
    semantic_projector = lifecycle_projectors.get("SEMANTIC", {})
    semantic_status = (
        semantic_projector.get("status")
        if isinstance(semantic_projector, dict)
        else None
    )
    semantic = (
        semantic_status
        if semantic_status in {"NOT_STARTED", "PENDING", "RUNNING", "READY", "FAILED"}
        else "READY" if ready else "UNKNOWN"
    )
    if k9 == "RUNNING" and isinstance(k9_progress, dict) \
            and k9_progress.get("stage") == "SEMANTIC_PROJECTOR":
        semantic = "RUNNING"
    mcl = (
        "READY" if mcl_lane == "PASS"
        else mcl_lane if mcl_lane in {"FAILED", "PENDING", "DEFERRED"}
        else "READY" if ready
        else "FAILED" if failed_stage.startswith("MCL")
        else "UNKNOWN"
    )
    general = (
        "READY" if general_lane == "PASS"
        else general_lane if general_lane in {"FAILED", "PENDING", "DEFERRED"}
        else "READY" if ready
        else "FAILED" if failed_stage in {"GENERAL", "GENERAL_PROVIDER", "GENERAL_ROUTE"}
        else "UNKNOWN"
    )
    handoff = Runner().output(["git", "rev-parse", "HEAD"])
    print(f"Product: {release.product_sha}")
    print(f"Handoff: {handoff}")
    print(f"Target state: {target_state}")
    print(f"Deploy active: {'YES' if active else 'NO'}")
    print(f"Deploy phase: {phase}")
    print(f"Last result: {last_result}")
    print(f"Last failed step: {failed_step}")
    print(f"Code: {code}")
    print(f"Accepted Product: {accepted_product}")
    print(f"Web: {web}")
    lifecycle_source = lifecycle.get("source", {}) if lifecycle else {}
    if isinstance(lifecycle_source, dict):
        source_status = lifecycle_source.get("status", "UNKNOWN")
        desired_snapshot = lifecycle_source.get("desired_snapshot_id")
        active_snapshot = lifecycle_source.get("active_snapshot_id")
        print(f"Source: {source_status}")
        print(
            f"Source snapshot: desired={desired_snapshot or 'NONE'}; "
            f"active={active_snapshot or 'NONE'}"
        )
        for projector_name, label in (
            ("LINEAGE", "Lineage"), ("METADATA", "Metadata"), ("SEMANTIC", "Semantic projector")
        ):
            projector_value = lifecycle_projectors.get(projector_name, {})
            if not isinstance(projector_value, dict):
                projector_value = {}
            print(
                f"{label}: {projector_value.get('status', 'UNKNOWN')}; "
                f"desired={projector_value.get('desired_snapshot_id') or 'NONE'}; "
                f"active={projector_value.get('active_snapshot_id') or 'NONE'}"
            )
        aggregate = lifecycle.get("aggregate", {})
        aggregate_status = (
            aggregate.get("status", "UNKNOWN")
            if isinstance(aggregate, dict)
            else "UNKNOWN"
        )
        print(f"K9 aggregate: {aggregate_status}")
    print(f"K9: {k9}")
    source_warning = smoke_report.get("k9_source_warning") if smoke_report else None
    if ready and isinstance(source_warning, dict) and (
        source_warning.get("code") == "DANGLING_GLOSSARY_ASSIGNMENTS"
    ):
        def warning_count(key: str) -> int:
            value = source_warning.get(key, 0)
            valid = isinstance(value, int) and not isinstance(value, bool) and value >= 0
            return value if valid else 0

        print("K9 source warning: DANGLING_GLOSSARY_ASSIGNMENTS")
        print(f"Dangling Terms: {warning_count('dangling_unique_terms')}")
        print(f"Dangling References: {warning_count('dangling_assignment_references')}")
        print(f"Absent: {warning_count('absent')}")
        print(f"Does not exist: {warning_count('does_not_exist')}")
        print(f"Removed: {warning_count('removed')}")
    assignment_scope = smoke_report.get("k9_assignment_scope") if smoke_report else None
    if ready and isinstance(assignment_scope, dict):
        scope_relation = assignment_scope.get("provider_scope_relation")
        if scope_relation in {"GLOBAL_GREATER", "GLOBAL_SMALLER", "MIXED"}:
            print(f"K9 assignment scope: {scope_relation} (advisory)")
            print(
                "K9 scoped references: "
                f"table={assignment_scope.get('k9_scoped_table_reference_total', 0)}; "
                f"column={assignment_scope.get('k9_scoped_column_reference_total', 0)}"
            )
            print(
                "Provider incoming totals: "
                f"table={assignment_scope.get('provider_incoming_table_total', 0)}; "
                f"column={assignment_scope.get('provider_incoming_column_total', 0)}"
            )
    if k9 == "RUNNING" and isinstance(k9_progress, dict):
        print(f"K9 stage: {k9_progress.get('stage', 'UNKNOWN')}")
        print(f"K9 detail: {k9_progress.get('detail', 'UNKNOWN')}")
        print(f"Progress: {k9_progress.get('completed', 0)}/{k9_progress.get('total', 0)}")
        print(f"Batch: {k9_progress.get('batch_number', 0)}/{k9_progress.get('batch_total', 0)}")
    if k9 == "FAILED":
        print(f"K9 stage: {smoke_diagnostic.get('failure_stage', failed_stage or 'UNKNOWN')}")
        print(f"K9 detail: {smoke_diagnostic.get('failure_detail_code', code)}")
        provider_class = smoke_diagnostic.get("provider_failure_class")
        if provider_class:
            print(f"Provider class: {provider_class}")
        batch_number = smoke_diagnostic.get("batch_number")
        batch_count = smoke_diagnostic.get("batch_count")
        if isinstance(batch_number, int) and isinstance(batch_count, int):
            print(f"Batch: {batch_number}/{batch_count}")
        requested = smoke_diagnostic.get("batch_requested_count")
        received = smoke_diagnostic.get("batch_response_count")
        elapsed = smoke_diagnostic.get("batch_elapsed_ms")
        if isinstance(requested, int):
            print(f"Requested: {requested}")
        if isinstance(received, int):
            print(f"Received: {received}")
        if isinstance(elapsed, int):
            print(f"Elapsed: {elapsed} ms")
        profile = smoke_diagnostic.get("metadata_profile")
        if isinstance(profile, dict):
            assignments = profile.get("assignments", {})
            if isinstance(assignments, dict) and (
                smoke_diagnostic.get("failure_detail_code") == "GLOSSARY_ASSIGNMENT_COUNT_MISMATCH"
            ):
                print(
                    "Assignment accounting: "
                    f"raw={assignments.get('raw_table_refs', 0)}/"
                    f"{assignments.get('raw_column_refs', 0)}; "
                    f"projectable={assignments.get('projectable_table_refs', 0)}/"
                    f"{assignments.get('projectable_column_refs', 0)}; "
                    f"dangling={assignments.get('dangling_table_refs', 0)}/"
                    f"{assignments.get('dangling_column_refs', 0)}; "
                    f"unique={assignments.get('unique_projected_table_edges', 0)}/"
                    f"{assignments.get('unique_projected_column_edges', 0)}; "
                    f"duplicate={assignments.get('duplicate_table_refs', 0)}/"
                    f"{assignments.get('duplicate_column_refs', 0)}"
                )
            direct = profile.get("direct_resolution", {})
            if isinstance(direct, dict):
                print(
                    "Diagnostic profile: "
                    f"glossary={profile.get('glossary_entities_fetched', 0)}/"
                    f"{profile.get('glossary_reported_total', 0)}; "
                    f"direct={direct.get('completed_resolution_count', 0)}/"
                    f"{direct.get('total', 0)}"
                )
                dangling_terms = direct.get("dangling_unique_terms", 0)
                dangling_references = direct.get("dangling_assignment_references", 0)
                if isinstance(dangling_terms, int) and dangling_terms > 0:
                    print(f"Dangling Terms: {dangling_terms}")
                    print(
                        "Dangling References: "
                        f"{dangling_references if isinstance(dangling_references, int) else 0}"
                    )
                    print(f"Absent: {direct.get('dangling_absent_count', 0)}")
                    print(f"Does not exist: {direct.get('dangling_does_not_exist_count', 0)}")
                    print(f"Removed: {direct.get('dangling_removed_count', 0)}")
                    print(f"Incompatible type: {direct.get('dangling_incompatible_type_count', 0)}")
    print(f"Semantic: {semantic}")
    print(f"MCL: {mcl}")
    print(f"GENERAL: {general}")
    print(f"Exact next action: {next_action}")


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
    run_smoke(
        runner,
        release,
        username,
        password,
        request_origin=bundle.effective["POC_PUBLIC_ORIGIN"],
        k9_mode=bundle.k9_mode,
        glossary_term_urn=bundle.effective.get("PREP_GLOSSARY_TERM_URN", ""),
    )
    print("PREP39083 SMOKE PASS")


def export(release: ReleaseIdentity, bundle: EnvironmentBundle) -> None:
    runner = Runner(environment=child_environment(bundle.effective))
    output_dir = RUNTIME_ROOT / f"release-{release.product_sha}"
    with private_effective_environment(bundle.effective) as env_file:
        try:
            completed = runner.run(
                [
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
                ]
            )
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
    parser.add_argument(
        "action",
        choices=("sync", "deploy", "doctor", "status", "logs", "smoke", "export"),
    )
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
        if inventory.accepted_marker_present:
            _accepted_state_failure(
                "PREP_ACCEPTED_STATE_OWNERSHIP_UNPROVEN",
                "The accepted marker is not paired with one complete owned target state.",
            )
        _ambiguous_state("Existing PREP receipts, runtime secrets and persistent volumes disagree.")
    if state in {
        TargetState.EXISTING_ACCEPTED_RUNNING,
        TargetState.EXISTING_ACCEPTED_STOPPED,
    }:
        source = verify_source_identity(release)
        preserved_runtime = read_env_file(
            RUNTIME_ENV,
            private=True,
            label=".env.prep.runtime",
        )
        validate_accepted_state(
            runner,
            release,
            source["handoff_commit"],
            inventory,
            preserved_runtime,
            k9_mode_from_operator(operator),
        )
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
    return reconcile_environment(
        release,
        target_state=read_only_state,
        persist_runtime=False,
    )


def fail(error: PrepError) -> NoReturn:
    print("FAILED", file=sys.stderr)
    print(f"Step: {error.step}", file=sys.stderr)
    print(f"Code: {error.code}", file=sys.stderr)
    print(f"Reason: {error.reason}", file=sys.stderr)
    print(f"Action: {error.action}", file=sys.stderr)
    raise SystemExit(2)


def execute(arguments: argparse.Namespace) -> None:
    try:
        if arguments.action == "sync":
            with deployment_lock("sync"):
                snapshot = sync_release_source()
                print("PREP39083 SOURCE SYNC PASS")
                print(f"Handoff: {snapshot}")
                write_last_command("sync", "PASS")
            return
        release = load_release_identity()
        if arguments.action == "status":
            status(release)
            return
        if arguments.action == "deploy":
            with deployment_lock("deploy"):
                retrieval = ensure_git_transport_artifact(release)
                print(f"Artifact retrieval: {retrieval}", flush=True)
                bundle, preparation = prepare_deployment(release)
                deploy(release, bundle, preparation)
                write_last_command("deploy", "ACCEPTED")
            return
        if arguments.action == "doctor":
            with deployment_lock("doctor"):
                retrieval = ensure_git_transport_artifact(release)
                print(f"Artifact retrieval: {retrieval}", flush=True)
                bundle = prepare_operational_bundle(release, arguments.action)
                doctor(release, bundle)
                write_last_command("doctor", "PASS")
            return
        bundle = prepare_operational_bundle(release, arguments.action)
        actions = {
            "logs": logs,
            "smoke": smoke,
            "export": export,
        }
        actions[arguments.action](release, bundle)
        write_last_command(arguments.action, "PASS")
    except PrepError as error:
        try:
            write_last_command(arguments.action, "FAILED", error=error)
        except OSError:
            pass
        fail(error)
    except CommandFailure:
        error = PrepError(
            "COMMAND_EXECUTION",
            "PREP_COMMAND_FAILED",
            "A bounded deployment command failed without completing its gate.",
            "Run ./scripts/prep39083 doctor, then logs; secrets and raw command "
            "output were suppressed.",
        )
        try:
            write_last_command(arguments.action, "FAILED", error=error)
        except OSError:
            pass
        fail(error)
    except (EOFError, KeyboardInterrupt):
        error = PrepError(
            "OPERATOR_INPUT",
            "PREP_OPERATOR_INPUT_CANCELLED",
            "Interactive operator input was cancelled.",
            "Rerun ./scripts/prep39083 deploy when the administrator input is available.",
        )
        try:
            write_last_command(arguments.action, "FAILED", error=error)
        except OSError:
            pass
        fail(error)
    except (OSError, ValueError):
        error = PrepError(
            "UNEXPECTED",
            "PREP_DEPLOYMENT_FAILED",
            "The one-command deployment could not complete its bounded contract.",
            "Run ./scripts/prep39083 doctor; no persistent state was intentionally deleted.",
        )
        try:
            write_last_command(arguments.action, "FAILED", error=error)
        except OSError:
            pass
        fail(error)


def main() -> None:
    arguments = parse_arguments()
    with command_log(arguments.action):
        execute(arguments)


if __name__ == "__main__":
    main()
