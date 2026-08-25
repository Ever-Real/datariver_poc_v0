#!/usr/bin/env python3
"""One-command PREP39083 source deployment above the immutable release tools."""

from __future__ import annotations

import argparse
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
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
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
    ) -> subprocess.CompletedProcess[str]:
        command = [os.fspath(value) for value in arguments]
        completed = subprocess.run(  # noqa: S603 - argv only, no shell interpolation.
            command,
            cwd=cwd,
            env=self.environment,
            check=False,
            capture_output=True,
            text=True,
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


@dataclass(frozen=True)
class EnvironmentBundle:
    operator: Mapping[str, str]
    optional: Mapping[str, str]
    runtime: Mapping[str, str]
    effective: Mapping[str, str]
    warnings: tuple[str, ...]


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


def reconcile_environment(
    release: ReleaseIdentity,
    *,
    operator_path: Path = OPERATOR_ENV,
    optional_path: Path = OPTIONAL_ENV,
    runtime_path: Path = RUNTIME_ENV,
    random_token: Callable[[int], str] = _token,
) -> EnvironmentBundle:
    contract = _read_json(ENV_CONTRACT, "environment contract")
    if contract.get("contract") != "DATARIVER_PREP39083_ENV_V2":
        raise PrepError(
            "ENVIRONMENT",
            "PREP_ENV_CONTRACT_INVALID",
            "The tracked environment contract version is invalid.",
            "Restore deploy/prep39083/env-contract.json from origin/dev.",
        )
    operator = read_env_file(operator_path, private=True, label=".env.prep")
    optional = (
        read_env_file(optional_path, private=True, label=".env.prep.optional")
        if optional_path.exists()
        else {}
    )
    required = tuple(contract.get("operator_required", ()))
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
    allowed_operator = set(required) | set(contract.get("operator_optional", ()))
    generated_specification = contract.get("generated_secrets", {})
    fixed = contract.get("fixed", {})
    if not isinstance(generated_specification, dict) or not isinstance(fixed, dict):
        raise PrepError(
            "ENVIRONMENT",
            "PREP_ENV_CONTRACT_INVALID",
            "Generated and fixed environment ownership must be objects.",
            "Restore deploy/prep39083/env-contract.json from origin/dev.",
        )
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
    for key, raw_byte_count in generated_specification.items():
        byte_count = int(raw_byte_count)
        legacy = operator.get(key, "")
        if not runtime.get(key):
            runtime[key] = (
                legacy
                if legacy and not legacy.startswith(CHANGE_ME_PREFIX)
                else random_token(byte_count)
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

    for key, value in fixed.items():
        runtime[str(key)] = str(value)
    runtime["POC_IMAGE_TAG"] = release.product_sha
    runtime["POC_SOURCE_COMMIT"] = release.product_sha
    runtime["PREP_RELEASE_PRODUCT_SHA"] = release.product_sha
    runtime["PREP_RELEASE_EVIDENCE_SHA"] = release.evidence_sha
    _atomic_private_env(runtime_path, runtime)

    known_legacy = set(generated_specification) | set(fixed) | optional_keys | {
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
    return EnvironmentBundle(operator, optional, runtime, effective, tuple(warnings))


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
                "K9/MCP target-local identity reconciliation is incomplete.",
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


def write_accepted_marker(release: ReleaseIdentity, handoff: str) -> None:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    payload = {
        "contract": "DATARIVER_PREP39083_ACCEPTED_V1",
        "product_sha": release.product_sha,
        "evidence_sha": release.evidence_sha,
        "handoff_commit": handoff,
        "accepted_at": datetime.now(UTC).isoformat(),
    }
    temporary = ACCEPTED_MARKER.with_suffix(".tmp")
    temporary.write_text(f"{json.dumps(payload, indent=2, sort_keys=True)}\n", encoding="utf-8")
    os.replace(temporary, ACCEPTED_MARKER)


def deploy(release: ReleaseIdentity, bundle: EnvironmentBundle) -> None:
    runner = Runner(environment=child_environment(bundle.effective))
    runner.note("Verify native PREP platform and exact Product/Evidence source")
    require_prep_platform(runner)
    source = verify_source_identity(release)
    before_39080 = snapshot_39080(runner)
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
        run_smoke(runner, release, username, password)
        after_39080 = snapshot_39080(runner)
        if after_39080 != before_39080:
            raise PrepError(
                "ISOLATION",
                "PREP_39080_CHANGED",
                "The existing 39080 container set changed during deployment.",
                "Stop and investigate; do not promote this PREP result.",
            )
        write_accepted_marker(release, source["handoff_commit"])
    print("\nPREP39083 DEPLOYMENT READY")
    print("\nRelease")
    print(f"- Product: {release.product_sha}")
    print(f"- Evidence: {release.evidence_sha}")
    print(f"- Handoff: {source['handoff_commit']}")
    print("- Platform: linux/amd64")
    print("\nRuntime")
    print("- Web: healthy")
    print(f"- Port: {release.port}")
    print("- PostgreSQL: healthy")
    print("- Neo4j: healthy")
    print("- Redis: healthy")
    print("- 39080: untouched")
    print("\nProviders")
    print("- DataHub: ready")
    print("- Chat: ready")
    print("- Embedding/Reranker: configured; managed semantic index READY")
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
    run_smoke(runner, release, username, password)
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
        bundle = reconcile_environment(release)
        actions = {
            "deploy": deploy,
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
