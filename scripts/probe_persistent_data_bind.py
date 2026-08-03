#!/usr/bin/env python3
"""Governed, isolated PostgreSQL/MinIO host-bind feasibility probe.

This is a one-time operator probe, not a daily deployment interface.  It never
uses production credentials or production data mounts.  Running it mutates the
fixed external probe directory and two isolated Docker containers, so the
reviewed confirmation token is mandatory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import secrets
import selectors
import stat
import subprocess
import sys
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from docker_capacity import exclusive_docker_workflow_lock

ROOT = Path(__file__).resolve().parents[1]
DATA_PARENT = Path("/Volumes/SSD_Mac/datariver-data")
PROBE_LEAF_NAME = ".c2-bind-probe-v1"
CONFIRMATION = "SEC-DURABLE-BIND-PROBE-001-A"

POSTGRES_PRODUCTION_CONTAINER = "datariver-next-postgres-1"
MINIO_PRODUCTION_CONTAINER = "datariver-local-connectors-minio-1"
POSTGRES_PRODUCTION_VOLUME = "datariver-next_postgres-data"
MINIO_PRODUCTION_VOLUME = "datariver-local-connectors_minio-data"
POSTGRES_PROBE_CONTAINER = "datariver-c2-probe-postgres-v1"
MINIO_PROBE_CONTAINER = "datariver-c2-probe-minio-v1"

POSTGRES_IMAGE_REFERENCE = (
    "pgvector/pgvector:0.8.2-pg17-bookworm@"
    "sha256:feb68f4f15446397d8cac7f4fe48fe4586de83160d1fc48b46283312d1a33966"
)
POSTGRES_IMAGE_ID = "sha256:feb68f4f15446397d8cac7f4fe48fe4586de83160d1fc48b46283312d1a33966"
MINIO_IMAGE_REFERENCE = (
    "quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z@"
    "sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e"
)
MINIO_IMAGE_ID = "sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e"

POSTGRES_CAPABILITIES = ("CHOWN", "DAC_OVERRIDE", "FOWNER", "SETGID", "SETUID")
POSTGRES_MEMORY_BYTES = 1_073_741_824
POSTGRES_NANO_CPUS = 1_500_000_000
POSTGRES_PIDS_LIMIT = 128
POSTGRES_STOP_TIMEOUT_SECONDS = 60
MINIO_MEMORY_BYTES = 536_870_912
MINIO_NANO_CPUS = 500_000_000
MINIO_PIDS_LIMIT = 64
MINIO_STOP_TIMEOUT_SECONDS = 30
COMMAND_TIMEOUT_SECONDS = 20
READINESS_ATTEMPTS = 30
READINESS_INTERVAL_SECONDS = 1.0
MINIMUM_HOST_FREE_BYTES = 2 * 1024 * 1024 * 1024
MAXIMUM_PROBE_DUMP_BYTES = 16 * 1024 * 1024
CONTAINER_TMPFS_PATH = "/tmp"  # noqa: S108 - isolated bounded container tmpfs.
CONTAINER_TMPFS_OPTION = "/tmp:rw,noexec,nosuid,size=33554432,mode=1777"  # noqa: S108 - isolated bounded container tmpfs.

_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_CONTAINER_ID = re.compile(r"^[0-9a-f]{64}$")
_SAFE_SECRET = re.compile(rb"^[A-Za-z0-9_-]+$")
_VERSION_ID = re.compile(r"^[!-~]{1,1024}$")
_POSTGRES_DB = "datariver_bind_probe"
_MINIO_ALIAS = "probe"
_MINIO_BUCKET = "datariver-bind-probe"
_MINIO_OBJECT = "persistence.bin"
POSTGRES_REQUIRED_ENVIRONMENT = (
    ("POSTGRES_DB", _POSTGRES_DB),
    ("POSTGRES_USER", "postgres"),
    ("POSTGRES_PASSWORD_FILE", "/run/secrets/postgres_password"),
    ("POSTGRES_INITDB_ARGS", "--auth-local=peer --auth-host=scram-sha-256"),
)
MINIO_REQUIRED_ENVIRONMENT = (
    ("MINIO_ROOT_USER_FILE", "/run/secrets/minio_access_key"),
    ("MINIO_ROOT_PASSWORD_FILE", "/run/secrets/minio_secret_key"),
    ("MC_CONFIG_DIR", "/tmp/mc"),  # noqa: S108 - bounded probe tmpfs.
)
POSTGRES_IMAGE_ENVIRONMENT_KEY_ALLOWLIST = frozenset(
    {"GOSU_VERSION", "LANG", "PATH", "PGDATA", "PG_MAJOR", "PG_VERSION"}
)
POSTGRES_REVIEWED_IMAGE_ENVIRONMENT_KEYS: frozenset[str] = frozenset()
MINIO_IMAGE_ENVIRONMENT_KEY_ALLOWLIST = frozenset(
    {
        "MC_CONFIG_DIR",
        "MINIO_ACCESS_KEY_FILE",
        "MINIO_CONFIG_ENV_FILE",
        "MINIO_KMS_SECRET_KEY_FILE",
        "MINIO_ROOT_PASSWORD_FILE",
        "MINIO_ROOT_USER_FILE",
        "MINIO_SECRET_KEY_FILE",
        "MINIO_UPDATE_MINISIGN_PUBKEY",
        "PATH",
    }
)
MINIO_REVIEWED_IMAGE_ENVIRONMENT_KEYS = frozenset(
    key for key in MINIO_IMAGE_ENVIRONMENT_KEY_ALLOWLIST if key != "PATH"
)


class ProbeError(RuntimeError):
    """A fixed, sanitized persistent-data probe failure."""


def fail(classification: str) -> NoReturn:
    raise ProbeError(classification)


@dataclass(frozen=True)
class PathIdentity:
    device: int
    inode: int
    mode: int


@dataclass(frozen=True)
class RegularFileIdentity:
    device: int
    inode: int
    mode: int
    links: int


@dataclass(frozen=True)
class ProbeLayout:
    parent: Path
    leaf: Path
    postgres_data: Path
    minio_data: Path
    evidence: Path
    secrets_dir: Path
    postgres_password_file: Path
    minio_access_file: Path
    minio_secret_file: Path
    parent_created: bool
    parent_identity: PathIdentity
    leaf_identity: PathIdentity


@dataclass(frozen=True)
class SecretBundle:
    postgres_password: bytes
    minio_access: bytes
    minio_secret: bytes
    file_identities: tuple[RegularFileIdentity, RegularFileIdentity, RegularFileIdentity]

    @property
    def values(self) -> tuple[bytes, ...]:
        return (self.postgres_password, self.minio_access, self.minio_secret)


@dataclass(frozen=True)
class ProductionIdentity:
    postgres_container_id: str
    minio_container_id: str
    postgres_volume_fingerprint: str
    minio_volume_fingerprint: str


@dataclass(frozen=True)
class ImageEvidence:
    environment: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ProbeEvidence:
    filesystem_noowners: bool
    postgres_uid: int
    postgres_gid: int
    postgres_mode: int
    minio_uid: int
    minio_gid: int
    minio_mode: int
    postgres_dump_bytes: int
    postgres_dump_sha256: str
    minio_object_sha256: str

    def summary(self) -> str:
        return (
            "DURABLE_BIND_PROBE_OK "
            f"filesystem_noowners={str(self.filesystem_noowners).lower()} "
            "ownership_enforcement_claimed=false "
            f"postgres_uid={self.postgres_uid} postgres_gid={self.postgres_gid} "
            f"postgres_mode={self.postgres_mode:o} minio_uid={self.minio_uid} "
            f"minio_gid={self.minio_gid} minio_mode={self.minio_mode:o} "
            f"postgres_dump_bytes={self.postgres_dump_bytes} "
            f"postgres_dump_sha256={self.postgres_dump_sha256} "
            f"minio_object_sha256={self.minio_object_sha256}"
        )


@dataclass(frozen=True)
class FailureCleanupEvidence:
    both_containers_stopped: bool | None
    secret_files_removed: int | None
    secret_files_retained: int | None

    @property
    def classification(self) -> str:
        if (
            self.both_containers_stopped is not True
            or self.secret_files_removed is None
            or self.secret_files_retained is None
            or self.secret_files_retained
        ):
            return "PROBE_SECRET_CLEANUP_REQUIRED"
        return "PROBE_FAILURE_EVIDENCE_RETAINED"

    def summary(self) -> str:
        parts = [self.classification]
        for name, value in (
            ("both_containers_stopped", self.both_containers_stopped),
            ("secret_files_removed", self.secret_files_removed),
            ("secret_files_retained", self.secret_files_retained),
        ):
            known = value is not None
            parts.append(f"{name}_known={str(known).lower()}")
            if value is not None:
                rendered = str(value).lower() if isinstance(value, bool) else str(value)
                parts.append(f"{name}={rendered}")
        return " ".join(parts)


class PrivateExecutor:
    """Run fixed argv without displaying commands or provider payloads."""

    def __init__(self) -> None:
        self._forbidden: tuple[bytes, ...] = ()

    def set_forbidden(self, values: Iterable[bytes]) -> None:
        material = tuple(value for value in values if value)
        if any(len(value) < 20 for value in material):
            fail("PROBE_SECRET_CONTRACT_INVALID")
        self._forbidden = material

    def _validate_arguments(self, arguments: Sequence[str]) -> tuple[str, ...]:
        command = tuple(arguments)
        if not command or any(not item or "\x00" in item or "\n" in item for item in command):
            fail("PROBE_COMMAND_INVALID")
        encoded = b"\x00".join(item.encode("utf-8") for item in command)
        if any(secret in encoded for secret in self._forbidden):
            fail("PROBE_SECRET_EXPOSURE_DETECTED")
        return command

    def output(
        self,
        arguments: Sequence[str],
        *,
        classification: str,
        timeout_seconds: int = COMMAND_TIMEOUT_SECONDS,
        input_bytes: bytes | None = None,
    ) -> bytes:
        command = self._validate_arguments(arguments)
        try:
            result = subprocess.run(  # noqa: S603 - every argv is repository-owned.
                command,
                check=True,
                capture_output=True,
                input=input_bytes,
                timeout=timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ProbeError(classification) from error
        private_payload = result.stdout + result.stderr
        if any(secret in private_payload for secret in self._forbidden):
            fail("PROBE_SECRET_ECHO_DETECTED")
        return result.stdout

    def succeeds(
        self,
        arguments: Sequence[str],
        *,
        timeout_seconds: int,
    ) -> bool:
        command = self._validate_arguments(arguments)
        try:
            result = subprocess.run(  # noqa: S603 - every argv is repository-owned.
                command,
                check=False,
                capture_output=True,
                timeout=timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        private_payload = result.stdout + result.stderr
        if any(secret in private_payload for secret in self._forbidden):
            fail("PROBE_SECRET_ECHO_DETECTED")
        return result.returncode == 0

    def stream_stdout(
        self,
        arguments: Sequence[str],
        *,
        destination: Path,
        classification: str,
        timeout_seconds: int,
    ) -> tuple[int, str]:
        command = self._validate_arguments(arguments)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor: int | None = None
        process: subprocess.Popen[bytes] | None = None
        selector: selectors.BaseSelector | None = None
        completed = False
        captured_size = 0
        captured_digest = ""
        try:
            descriptor = os.open(destination, flags, 0o600)
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                descriptor = None
                opened = _regular_file_identity_from_metadata(
                    os.fstat(stream.fileno()),
                    classification="POSTGRES_PROBE_DUMP_INVALID",
                )
                digest = hashlib.sha256()
                process = subprocess.Popen(  # noqa: S603 - every argv is repository-owned.
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                if process.stdout is None:
                    fail(classification)
                selector = selectors.DefaultSelector()
                selector.register(process.stdout, selectors.EVENT_READ)
                deadline = time.monotonic() + timeout_seconds
                written = 0
                while True:
                    remaining_time = deadline - time.monotonic()
                    if remaining_time <= 0:
                        fail(classification)
                    events = selector.select(remaining_time)
                    if not events:
                        fail(classification)
                    chunk = os.read(
                        process.stdout.fileno(),
                        min(1024 * 1024, MAXIMUM_PROBE_DUMP_BYTES - written + 1),
                    )
                    if not chunk:
                        break
                    allowed = MAXIMUM_PROBE_DUMP_BYTES - written
                    if len(chunk) > allowed:
                        if allowed:
                            stream.write(chunk[:allowed])
                            digest.update(chunk[:allowed])
                            written += allowed
                        stream.flush()
                        os.fsync(stream.fileno())
                        fail("POSTGRES_PROBE_DUMP_LIMIT_EXCEEDED")
                    stream.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
                stream.flush()
                os.fsync(stream.fileno())
                metadata = os.fstat(stream.fileno())
                current_path = _regular_file_identity(
                    destination,
                    classification="POSTGRES_PROBE_DUMP_PATH_CHANGED",
                )
                if current_path.device != metadata.st_dev or current_path.inode != metadata.st_ino:
                    fail("POSTGRES_PROBE_DUMP_PATH_CHANGED")
                captured = _regular_file_identity_from_metadata(
                    metadata,
                    classification="POSTGRES_PROBE_DUMP_INVALID",
                )
                if (
                    captured != opened
                    or metadata.st_size != written
                    or written <= 0
                    or written > MAXIMUM_PROBE_DUMP_BYTES
                ):
                    fail("POSTGRES_PROBE_DUMP_INVALID")
                if current_path != opened:
                    fail("POSTGRES_PROBE_DUMP_PATH_CHANGED")
                captured_size = written
                captured_digest = digest.hexdigest()
            try:
                return_code = process.wait(timeout=5)
                completed = True
            except subprocess.TimeoutExpired:
                fail(classification)
            if return_code != 0:
                raise ProbeError(classification)
            return captured_size, captured_digest
        except ProbeError:
            raise
        except (OSError, subprocess.SubprocessError) as error:
            raise ProbeError(classification) from error
        finally:
            if selector is not None:
                selector.close()
            if process is not None and not completed and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            if process is not None and process.stdout is not None:
                process.stdout.close()
            if descriptor is not None:
                os.close(descriptor)


def _json_document(payload: bytes, *, classification: str) -> dict[str, Any]:
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProbeError(classification) from error
    if not isinstance(document, list) or len(document) != 1 or not isinstance(document[0], dict):
        fail(classification)
    return document[0]


def _path_identity(path: Path, *, classification: str) -> PathIdentity:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ProbeError(classification) from error
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        fail(classification)
    return PathIdentity(
        device=metadata.st_dev,
        inode=metadata.st_ino,
        mode=stat.S_IMODE(metadata.st_mode),
    )


def _require_same_path(path: Path, identity: PathIdentity, *, classification: str) -> None:
    current = _path_identity(path, classification=classification)
    if current.device != identity.device or current.inode != identity.inode:
        fail(classification)


def _mkdir_private(path: Path) -> None:
    try:
        path.mkdir(mode=0o700)
        os.chmod(path, 0o700)
    except OSError as error:
        raise ProbeError("PROBE_HOST_PATH_CREATE_FAILED") from error


def prepare_layout(parent: Path) -> ProbeLayout:
    """Create the absent-only private probe tree after validating its parent mount."""

    mount_root = parent.parent
    mount_identity = _path_identity(mount_root, classification="PROBE_HOST_ROOT_INVALID")
    if mount_identity.mode & 0o022:
        fail("PROBE_HOST_ROOT_INVALID")
    try:
        free_bytes = os.statvfs(mount_root).f_bavail * os.statvfs(mount_root).f_frsize
    except OSError as error:
        raise ProbeError("PROBE_HOST_CAPACITY_FAILED") from error
    if free_bytes < MINIMUM_HOST_FREE_BYTES:
        fail("PROBE_HOST_CAPACITY_INSUFFICIENT")

    parent_created = False
    if parent.exists() or parent.is_symlink():
        parent_identity = _path_identity(parent, classification="PROBE_PARENT_INVALID")
        if parent_identity.mode != 0o700 or parent.stat().st_uid != os.getuid():
            fail("PROBE_PARENT_INVALID")
    else:
        _mkdir_private(parent)
        parent_created = True
        parent_identity = _path_identity(parent, classification="PROBE_PARENT_INVALID")

    leaf = parent / PROBE_LEAF_NAME
    if leaf.exists() or leaf.is_symlink():
        fail("PROBE_LEAF_ALREADY_EXISTS")
    _mkdir_private(leaf)
    leaf_identity = _path_identity(leaf, classification="PROBE_LEAF_INVALID")

    postgres_data = leaf / "postgres" / "data"
    minio_data = leaf / "minio" / "data"
    evidence = leaf / "evidence"
    secrets_dir = leaf / "secrets"
    for directory in (
        postgres_data.parent,
        postgres_data,
        minio_data.parent,
        minio_data,
        evidence,
        secrets_dir,
    ):
        _mkdir_private(directory)

    return ProbeLayout(
        parent=parent,
        leaf=leaf,
        postgres_data=postgres_data,
        minio_data=minio_data,
        evidence=evidence,
        secrets_dir=secrets_dir,
        postgres_password_file=secrets_dir / "postgres_password",
        minio_access_file=secrets_dir / "minio_access_key",
        minio_secret_file=secrets_dir / "minio_secret_key",
        parent_created=parent_created,
        parent_identity=parent_identity,
        leaf_identity=leaf_identity,
    )


def _write_secret(path: Path, value: bytes) -> RegularFileIdentity:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = None
            stream.write(value + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
            identity = _regular_file_identity_from_metadata(
                os.fstat(stream.fileno()),
                classification="PROBE_SECRET_FILE_INVALID",
            )
        return identity
    except ProbeError:
        raise
    except OSError as error:
        raise ProbeError("PROBE_SECRET_FILE_CREATE_FAILED") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _regular_file_identity_from_metadata(
    metadata: os.stat_result,
    *,
    classification: str,
) -> RegularFileIdentity:
    mode = stat.S_IMODE(metadata.st_mode)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or mode != 0o600
        or metadata.st_nlink != 1
    ):
        fail(classification)
    return RegularFileIdentity(
        device=metadata.st_dev,
        inode=metadata.st_ino,
        mode=mode,
        links=metadata.st_nlink,
    )


def _regular_file_identity(path: Path, *, classification: str) -> RegularFileIdentity:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ProbeError(classification) from error
    return _regular_file_identity_from_metadata(metadata, classification=classification)


def _secret_paths(layout: ProbeLayout) -> tuple[Path, Path, Path]:
    return (
        layout.postgres_password_file,
        layout.minio_access_file,
        layout.minio_secret_file,
    )


def create_probe_secrets(layout: ProbeLayout) -> SecretBundle:
    postgres_password = secrets.token_urlsafe(36).encode("ascii")
    minio_access = secrets.token_hex(10).encode("ascii")
    minio_secret = secrets.token_urlsafe(32).encode("ascii")
    values = (postgres_password, minio_access, minio_secret)
    if (
        len(postgres_password) < 48
        or len(minio_access) != 20
        or len(minio_secret) < 40
        or any(_SAFE_SECRET.fullmatch(value) is None for value in values)
        or len(set(values)) != 3
    ):
        fail("PROBE_SECRET_CONTRACT_INVALID")
    paths = _secret_paths(layout)
    identities = (
        _write_secret(paths[0], values[0]),
        _write_secret(paths[1], values[1]),
        _write_secret(paths[2], values[2]),
    )
    _fsync_directory(layout.secrets_dir)
    current_identities = tuple(
        _regular_file_identity(path, classification="PROBE_SECRET_FILE_CHANGED") for path in paths
    )
    if current_identities != identities:
        fail("PROBE_SECRET_FILE_CHANGED")
    return SecretBundle(
        postgres_password=postgres_password,
        minio_access=minio_access,
        minio_secret=minio_secret,
        file_identities=identities,
    )


def _mount(source: Path, destination: str, *, readonly: bool) -> str:
    mode = "readonly" if readonly else "rw"
    return f"type=bind,src={source},dst={destination},{mode}"


def postgres_create_arguments(layout: ProbeLayout) -> tuple[str, ...]:
    arguments = [
        "docker",
        "create",
        "--name",
        POSTGRES_PROBE_CONTAINER,
        "--pull",
        "never",
        "--network",
        "none",
        "--read-only",
        "--security-opt",
        "no-new-privileges=true",
        "--cap-drop",
        "ALL",
    ]
    for capability in POSTGRES_CAPABILITIES:
        arguments.extend(("--cap-add", capability))
    arguments.extend(
        (
            "--memory",
            "1g",
            "--cpus",
            "1.5",
            "--pids-limit",
            str(POSTGRES_PIDS_LIMIT),
            "--stop-timeout",
            str(POSTGRES_STOP_TIMEOUT_SECONDS),
            "--log-driver",
            "none",
            "--restart",
            "no",
            "--mount",
            _mount(layout.postgres_data, "/var/lib/postgresql/data", readonly=False),
            "--mount",
            _mount(
                layout.postgres_password_file,
                "/run/secrets/postgres_password",
                readonly=True,
            ),
            "--tmpfs",
            "/var/run/postgresql:rw,noexec,nosuid,size=16777216,mode=0775,uid=999,gid=999",
            "--tmpfs",
            CONTAINER_TMPFS_OPTION,
            "--env",
            f"POSTGRES_DB={_POSTGRES_DB}",
            "--env",
            "POSTGRES_USER=postgres",
            "--env",
            "POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password",
            "--env",
            "POSTGRES_INITDB_ARGS=--auth-local=peer --auth-host=scram-sha-256",
            POSTGRES_IMAGE_ID,
        )
    )
    return tuple(arguments)


def minio_create_arguments(layout: ProbeLayout) -> tuple[str, ...]:
    return (
        "docker",
        "create",
        "--name",
        MINIO_PROBE_CONTAINER,
        "--pull",
        "never",
        "--network",
        "none",
        "--read-only",
        "--security-opt",
        "no-new-privileges=true",
        "--cap-drop",
        "ALL",
        "--memory",
        "512m",
        "--cpus",
        "0.5",
        "--pids-limit",
        str(MINIO_PIDS_LIMIT),
        "--stop-timeout",
        str(MINIO_STOP_TIMEOUT_SECONDS),
        "--log-driver",
        "none",
        "--restart",
        "no",
        "--mount",
        _mount(layout.minio_data, "/data", readonly=False),
        "--mount",
        _mount(layout.minio_access_file, "/run/secrets/minio_access_key", readonly=True),
        "--mount",
        _mount(layout.minio_secret_file, "/run/secrets/minio_secret_key", readonly=True),
        "--tmpfs",
        CONTAINER_TMPFS_OPTION,
        "--env",
        "MINIO_ROOT_USER_FILE=/run/secrets/minio_access_key",
        "--env",
        "MINIO_ROOT_PASSWORD_FILE=/run/secrets/minio_secret_key",
        "--env",
        "MC_CONFIG_DIR=/tmp/mc",
        MINIO_IMAGE_ID,
        "server",
        "/data",
        "--address",
        "127.0.0.1:9000",
        "--console-address",
        "127.0.0.1:9001",
    )


def mc_alias_arguments() -> tuple[str, ...]:
    return (
        "docker",
        "exec",
        "-i",
        MINIO_PROBE_CONTAINER,
        "mc",
        "alias",
        "set",
        _MINIO_ALIAS,
        "http://127.0.0.1:9000",
        "--api",
        "S3v4",
        "--path",
        "on",
    )


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        os.fsync(descriptor)
    except OSError as error:
        raise ProbeError("PROBE_DIRECTORY_FSYNC_FAILED") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def probe_host_atomicity(layout: ProbeLayout) -> str:
    partial = layout.evidence / ".atomic.partial"
    final = layout.evidence / "atomic.ok"
    payload = b"datariver-persistent-bind-atomic-v1\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(partial, flags, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = None
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(partial, final)
        _fsync_directory(layout.evidence)
        if final.read_bytes() != payload:
            fail("PROBE_ATOMIC_READBACK_FAILED")
        return hashlib.sha256(payload).hexdigest()
    except ProbeError:
        raise
    except OSError as error:
        raise ProbeError("PROBE_ATOMIC_OPERATION_FAILED") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _expected_architecture() -> str:
    machine = platform.machine().casefold()
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    if machine in {"x86_64", "amd64"}:
        return "amd64"
    fail("PROBE_HOST_ARCHITECTURE_UNSUPPORTED")


def _parse_environment(
    values: Any,
    *,
    classification: str,
) -> dict[str, str]:
    if values is None:
        values = []
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        fail(classification)
    environment: dict[str, str] = {}
    for entry in values:
        key, separator, value = entry.partition("=")
        if separator != "=" or not key or "\x00" in key or "\n" in key or key in environment:
            fail(classification)
        environment[key] = value
    return environment


def require_image(
    executor: PrivateExecutor,
    *,
    image_id: str,
    entrypoint: tuple[str, ...],
    expected_environment_keys: frozenset[str],
    governed_environment_prefixes: tuple[str, ...] = (),
    reviewed_environment_keys: frozenset[str] = frozenset(),
) -> ImageEvidence:
    if _IMAGE_ID.fullmatch(image_id) is None:
        fail("PROBE_IMAGE_ID_INVALID")
    document = _json_document(
        executor.output(
            ("docker", "image", "inspect", image_id),
            classification="PROBE_IMAGE_INSPECT_FAILED",
        ),
        classification="PROBE_IMAGE_EVIDENCE_INVALID",
    )
    config = document.get("Config")
    if (
        document.get("Id") != image_id
        or document.get("Os") != "linux"
        or document.get("Architecture") != _expected_architecture()
        or not isinstance(config, dict)
        or tuple(config.get("Entrypoint") or ()) != entrypoint
    ):
        fail("PROBE_IMAGE_EVIDENCE_INVALID")
    environment = _parse_environment(
        config.get("Env"),
        classification="PROBE_IMAGE_ENVIRONMENT_INVALID",
    )
    if frozenset(environment) != expected_environment_keys or any(
        key.startswith(governed_environment_prefixes) and key not in reviewed_environment_keys
        for key in environment
    ):
        fail("PROBE_IMAGE_ENVIRONMENT_INVALID")
    return ImageEvidence(environment=tuple(sorted(environment.items())))


def _volume_fingerprint(executor: PrivateExecutor, volume: str) -> str:
    document = _json_document(
        executor.output(
            ("docker", "volume", "inspect", volume),
            classification="PRODUCTION_VOLUME_INSPECT_FAILED",
        ),
        classification="PRODUCTION_VOLUME_EVIDENCE_INVALID",
    )
    if document.get("Name") != volume or document.get("Driver") != "local":
        fail("PRODUCTION_VOLUME_EVIDENCE_INVALID")
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _production_container_id(
    executor: PrivateExecutor,
    *,
    container: str,
    image_id: str,
    volume: str,
    destination: str,
) -> str:
    document = _json_document(
        executor.output(
            ("docker", "inspect", container),
            classification="PRODUCTION_CONTAINER_INSPECT_FAILED",
        ),
        classification="PRODUCTION_CONTAINER_EVIDENCE_INVALID",
    )
    identifier = document.get("Id")
    state = document.get("State")
    mounts = document.get("Mounts")
    if (
        not isinstance(identifier, str)
        or _CONTAINER_ID.fullmatch(identifier) is None
        or document.get("Image") != image_id
        or not isinstance(state, dict)
        or state.get("Running") is not True
        or not isinstance(mounts, list)
    ):
        fail("PRODUCTION_CONTAINER_EVIDENCE_INVALID")
    matching = [
        mount
        for mount in mounts
        if isinstance(mount, dict)
        and mount.get("Type") == "volume"
        and mount.get("Name") == volume
        and mount.get("Destination") == destination
        and mount.get("RW") is True
    ]
    if len(matching) != 1:
        fail("PRODUCTION_CONTAINER_EVIDENCE_INVALID")
    return identifier


def capture_production_identity(executor: PrivateExecutor) -> ProductionIdentity:
    return ProductionIdentity(
        postgres_container_id=_production_container_id(
            executor,
            container=POSTGRES_PRODUCTION_CONTAINER,
            image_id=POSTGRES_IMAGE_ID,
            volume=POSTGRES_PRODUCTION_VOLUME,
            destination="/var/lib/postgresql/data",
        ),
        minio_container_id=_production_container_id(
            executor,
            container=MINIO_PRODUCTION_CONTAINER,
            image_id=MINIO_IMAGE_ID,
            volume=MINIO_PRODUCTION_VOLUME,
            destination="/data",
        ),
        postgres_volume_fingerprint=_volume_fingerprint(executor, POSTGRES_PRODUCTION_VOLUME),
        minio_volume_fingerprint=_volume_fingerprint(executor, MINIO_PRODUCTION_VOLUME),
    )


def require_production_unchanged(
    executor: PrivateExecutor,
    baseline: ProductionIdentity,
) -> None:
    if capture_production_identity(executor) != baseline:
        fail("PRODUCTION_IDENTITY_CHANGED")


def _volume_names(executor: PrivateExecutor) -> frozenset[str]:
    payload = executor.output(
        ("docker", "volume", "ls", "--format", "{{.Name}}"),
        classification="DOCKER_VOLUME_LIST_FAILED",
    )
    try:
        names = payload.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ProbeError("DOCKER_VOLUME_LIST_INVALID") from error
    if any(not name or len(name) > 255 or "\x00" in name for name in names):
        fail("DOCKER_VOLUME_LIST_INVALID")
    return frozenset(names)


def require_probe_containers_absent(executor: PrivateExecutor) -> None:
    for name in (POSTGRES_PROBE_CONTAINER, MINIO_PROBE_CONTAINER):
        payload = executor.output(
            (
                "docker",
                "container",
                "ls",
                "--all",
                "--filter",
                f"name=^/{name}$",
                "--format",
                "{{.ID}}",
            ),
            classification="PROBE_CONTAINER_ABSENCE_CHECK_FAILED",
        )
        if payload.strip():
            fail("PROBE_CONTAINER_ALREADY_EXISTS")


@dataclass(frozen=True)
class ProbeContainerSpec:
    name: str
    image_id: str
    memory_bytes: int
    nano_cpus: int
    pids_limit: int
    stop_timeout: int
    cap_add: tuple[str, ...]
    tmpfs: dict[str, str]
    binds: dict[str, tuple[Path, bool]]
    image_environment: tuple[tuple[str, str], ...]
    required_environment: tuple[tuple[str, str], ...]
    reviewed_override_keys: frozenset[str]


def _container_specs(
    layout: ProbeLayout,
    *,
    postgres_image_environment: tuple[tuple[str, str], ...] = (),
    minio_image_environment: tuple[tuple[str, str], ...] = (),
) -> dict[str, ProbeContainerSpec]:
    return {
        POSTGRES_PROBE_CONTAINER: ProbeContainerSpec(
            name=POSTGRES_PROBE_CONTAINER,
            image_id=POSTGRES_IMAGE_ID,
            memory_bytes=POSTGRES_MEMORY_BYTES,
            nano_cpus=POSTGRES_NANO_CPUS,
            pids_limit=POSTGRES_PIDS_LIMIT,
            stop_timeout=POSTGRES_STOP_TIMEOUT_SECONDS,
            cap_add=POSTGRES_CAPABILITIES,
            tmpfs={
                "/var/run/postgresql": "rw,noexec,nosuid,size=16777216,mode=0775,uid=999,gid=999",
                CONTAINER_TMPFS_PATH: "rw,noexec,nosuid,size=33554432,mode=1777",
            },
            binds={
                "/var/lib/postgresql/data": (layout.postgres_data, True),
                "/run/secrets/postgres_password": (layout.postgres_password_file, False),
            },
            image_environment=postgres_image_environment,
            required_environment=POSTGRES_REQUIRED_ENVIRONMENT,
            reviewed_override_keys=frozenset(key for key, _value in POSTGRES_REQUIRED_ENVIRONMENT),
        ),
        MINIO_PROBE_CONTAINER: ProbeContainerSpec(
            name=MINIO_PROBE_CONTAINER,
            image_id=MINIO_IMAGE_ID,
            memory_bytes=MINIO_MEMORY_BYTES,
            nano_cpus=MINIO_NANO_CPUS,
            pids_limit=MINIO_PIDS_LIMIT,
            stop_timeout=MINIO_STOP_TIMEOUT_SECONDS,
            cap_add=(),
            tmpfs={CONTAINER_TMPFS_PATH: "rw,noexec,nosuid,size=33554432,mode=1777"},
            binds={
                "/data": (layout.minio_data, True),
                "/run/secrets/minio_access_key": (layout.minio_access_file, False),
                "/run/secrets/minio_secret_key": (layout.minio_secret_file, False),
            },
            image_environment=minio_image_environment,
            required_environment=MINIO_REQUIRED_ENVIRONMENT,
            reviewed_override_keys=frozenset(key for key, _value in MINIO_REQUIRED_ENVIRONMENT),
        ),
    }


def require_probe_container_contract(
    executor: PrivateExecutor,
    *,
    spec: ProbeContainerSpec,
    secret_values: tuple[bytes, ...],
    require_running: bool,
) -> str:
    raw = executor.output(
        ("docker", "inspect", spec.name),
        classification="PROBE_CONTAINER_INSPECT_FAILED",
    )
    if any(secret in raw for secret in secret_values):
        fail("PROBE_SECRET_EXPOSURE_DETECTED")
    document = _json_document(raw, classification="PROBE_CONTAINER_EVIDENCE_INVALID")
    identifier = document.get("Id")
    host = document.get("HostConfig")
    config = document.get("Config")
    state = document.get("State")
    mounts = document.get("Mounts")
    if (
        not isinstance(identifier, str)
        or _CONTAINER_ID.fullmatch(identifier) is None
        or document.get("Image") != spec.image_id
        or not isinstance(host, dict)
        or not isinstance(config, dict)
        or not isinstance(state, dict)
        or not isinstance(mounts, list)
    ):
        fail("PROBE_CONTAINER_EVIDENCE_INVALID")

    security = host.get("SecurityOpt")
    cap_drop = host.get("CapDrop")
    cap_add = host.get("CapAdd")
    log_config = host.get("LogConfig")
    if (
        host.get("Privileged") is not False
        or host.get("ReadonlyRootfs") is not True
        or host.get("NetworkMode") != "none"
        or host.get("Memory") != spec.memory_bytes
        or host.get("NanoCpus") != spec.nano_cpus
        or host.get("PidsLimit") != spec.pids_limit
        or host.get("StopTimeout") != spec.stop_timeout
        or host.get("RestartPolicy", {}).get("Name") != "no"
        or security != ["no-new-privileges:true"]
        or cap_drop != ["ALL"]
        or tuple(sorted(cap_add or ())) != tuple(sorted(spec.cap_add))
        or not isinstance(log_config, dict)
        or log_config.get("Type") != "none"
        or any(host.get(key, "") == "host" for key in ("PidMode", "IpcMode", "UTSMode"))
        or host.get("UsernsMode", "") == "host"
        or host.get("Devices") not in (None, [])
        or host.get("DeviceRequests") not in (None, [])
        or host.get("Binds") not in (None, [])
        or host.get("Tmpfs") != spec.tmpfs
    ):
        fail("PROBE_CONTAINER_SECURITY_DRIFT")

    environment = _parse_environment(
        config.get("Env"),
        classification="PROBE_CONTAINER_ENVIRONMENT_DRIFT",
    )
    expected_environment = dict(spec.image_environment)
    required_environment = dict(spec.required_environment)
    if (
        len(expected_environment) != len(spec.image_environment)
        or len(required_environment) != len(spec.required_environment)
        or frozenset(required_environment) != spec.reviewed_override_keys
        or not frozenset(expected_environment)
        .intersection(required_environment)
        .issubset(spec.reviewed_override_keys)
    ):
        fail("PROBE_CONTAINER_ENVIRONMENT_DRIFT")
    expected_environment.update(required_environment)
    if environment != expected_environment:
        fail("PROBE_CONTAINER_ENVIRONMENT_DRIFT")

    observed_binds: dict[str, tuple[Path, bool]] = {}
    for mount in mounts:
        if not isinstance(mount, dict) or mount.get("Type") != "bind":
            fail("PROBE_CONTAINER_MOUNT_DRIFT")
        source = mount.get("Source")
        destination = mount.get("Destination")
        writable = mount.get("RW")
        if (
            not isinstance(source, str)
            or not isinstance(destination, str)
            or not isinstance(writable, bool)
        ):
            fail("PROBE_CONTAINER_MOUNT_DRIFT")
        observed_binds[destination] = (Path(source), writable)
    if set(observed_binds) != set(spec.binds):
        fail("PROBE_CONTAINER_MOUNT_DRIFT")
    for destination, (expected_source, expected_writable) in spec.binds.items():
        source, writable = observed_binds[destination]
        try:
            if source.resolve(strict=True) != expected_source.resolve(strict=True):
                fail("PROBE_CONTAINER_MOUNT_DRIFT")
        except OSError as error:
            raise ProbeError("PROBE_CONTAINER_MOUNT_DRIFT") from error
        if writable is not expected_writable:
            fail("PROBE_CONTAINER_MOUNT_DRIFT")

    if require_running:
        restart_count = document.get("RestartCount")
        if (
            state.get("Running") is not True
            or state.get("Restarting") is not False
            or not isinstance(state.get("Pid"), int)
            or state.get("Pid", 0) <= 0
            or state.get("OOMKilled") is not False
            or type(restart_count) is not int
            or restart_count != 0
        ):
            fail("PROBE_CONTAINER_STATE_INVALID")
    return identifier


def _wait_ready(
    executor: PrivateExecutor,
    arguments: tuple[str, ...],
    *,
    classification: str,
) -> None:
    for attempt in range(READINESS_ATTEMPTS):
        if executor.succeeds(arguments, timeout_seconds=5):
            return
        if attempt + 1 < READINESS_ATTEMPTS:
            time.sleep(READINESS_INTERVAL_SECONDS)
    fail(classification)


def _postgres_readiness_arguments() -> tuple[str, ...]:
    return (
        "docker",
        "exec",
        "--user",
        "999:999",
        POSTGRES_PROBE_CONTAINER,
        "pg_isready",
        "-h",
        "/var/run/postgresql",
        "-U",
        "postgres",
        "-d",
        _POSTGRES_DB,
    )


def _parse_uid_mode(payload: bytes, *, classification: str) -> tuple[int, int, int]:
    try:
        fields = payload.decode("ascii").strip().split(":")
        if len(fields) != 3:
            fail(classification)
        uid, gid, mode = int(fields[0]), int(fields[1]), int(fields[2], 8)
    except (UnicodeDecodeError, ValueError) as error:
        raise ProbeError(classification) from error
    if uid < 0 or gid < 0 or mode & 0o077:
        fail(classification)
    return uid, gid, mode


def _start_postgres(
    executor: PrivateExecutor,
    *,
    layout: ProbeLayout,
    secrets_bundle: SecretBundle,
    created_containers: set[str],
    spec: ProbeContainerSpec,
) -> tuple[str, tuple[int, int, int], int, str]:
    created_containers.add(POSTGRES_PROBE_CONTAINER)
    created = (
        executor.output(
            postgres_create_arguments(layout),
            classification="POSTGRES_PROBE_CREATE_FAILED",
        )
        .decode("ascii", errors="ignore")
        .strip()
    )
    if _CONTAINER_ID.fullmatch(created) is None:
        fail("POSTGRES_PROBE_CREATE_EVIDENCE_INVALID")
    executor.output(
        ("docker", "start", POSTGRES_PROBE_CONTAINER),
        classification="POSTGRES_PROBE_START_FAILED",
    )
    identifier = require_probe_container_contract(
        executor,
        spec=spec,
        secret_values=secrets_bundle.values,
        require_running=True,
    )
    if identifier != created:
        fail("POSTGRES_PROBE_CONTAINER_ID_CHANGED")
    _wait_ready(
        executor,
        _postgres_readiness_arguments(),
        classification="POSTGRES_PROBE_READINESS_FAILED",
    )
    sql = (
        "CREATE TABLE probe_persistence (id integer PRIMARY KEY, value text NOT NULL);"
        "INSERT INTO probe_persistence VALUES (1, 'persistent-value-v1');"
        "CHECKPOINT;"
    )
    executor.output(
        (
            "docker",
            "exec",
            "--user",
            "999:999",
            POSTGRES_PROBE_CONTAINER,
            "psql",
            "-h",
            "/var/run/postgresql",
            "-U",
            "postgres",
            "-d",
            _POSTGRES_DB,
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            sql,
        ),
        classification="POSTGRES_PROBE_WRITE_FAILED",
    )
    dump_partial = layout.evidence / "postgres.dump.partial"
    dump_final = layout.evidence / "postgres.dump"
    dump_bytes, dump_sha256 = executor.stream_stdout(
        (
            "docker",
            "exec",
            "--user",
            "999:999",
            POSTGRES_PROBE_CONTAINER,
            "pg_dump",
            "-h",
            "/var/run/postgresql",
            "-U",
            "postgres",
            "-d",
            _POSTGRES_DB,
            "--format=custom",
        ),
        destination=dump_partial,
        classification="POSTGRES_PROBE_DUMP_FAILED",
        timeout_seconds=POSTGRES_STOP_TIMEOUT_SECONDS,
    )
    try:
        os.replace(dump_partial, dump_final)
        _fsync_directory(layout.evidence)
    except OSError as error:
        raise ProbeError("POSTGRES_PROBE_DUMP_PUBLISH_FAILED") from error
    ownership = _parse_uid_mode(
        executor.output(
            (
                "docker",
                "exec",
                POSTGRES_PROBE_CONTAINER,
                "stat",
                "-c",
                "%u:%g:%a",
                "/var/lib/postgresql/data",
            ),
            classification="POSTGRES_PROBE_MODE_FAILED",
        ),
        classification="POSTGRES_PROBE_MODE_INVALID",
    )
    return identifier, ownership, dump_bytes, dump_sha256


def _verify_postgres_after_restart(
    executor: PrivateExecutor,
    *,
    identifier: str,
    layout: ProbeLayout,
    secret_values: tuple[bytes, ...],
    ownership: tuple[int, int, int],
    spec: ProbeContainerSpec,
) -> None:
    executor.output(
        ("docker", "stop", "--time", str(POSTGRES_STOP_TIMEOUT_SECONDS), POSTGRES_PROBE_CONTAINER),
        classification="POSTGRES_PROBE_STOP_FAILED",
        timeout_seconds=POSTGRES_STOP_TIMEOUT_SECONDS + 5,
    )
    require_probe_stopped(executor, POSTGRES_PROBE_CONTAINER)
    executor.output(
        ("docker", "start", POSTGRES_PROBE_CONTAINER),
        classification="POSTGRES_PROBE_RESTART_FAILED",
    )
    current = require_probe_container_contract(
        executor,
        spec=spec,
        secret_values=secret_values,
        require_running=True,
    )
    if current != identifier:
        fail("POSTGRES_PROBE_CONTAINER_ID_CHANGED")
    _wait_ready(
        executor,
        _postgres_readiness_arguments(),
        classification="POSTGRES_PROBE_RESTART_READINESS_FAILED",
    )
    value = executor.output(
        (
            "docker",
            "exec",
            "--user",
            "999:999",
            POSTGRES_PROBE_CONTAINER,
            "psql",
            "-h",
            "/var/run/postgresql",
            "-U",
            "postgres",
            "-d",
            _POSTGRES_DB,
            "-At",
            "-c",
            "SELECT value FROM probe_persistence WHERE id=1;",
        ),
        classification="POSTGRES_PROBE_RESTART_READ_FAILED",
    )
    if value.strip() != b"persistent-value-v1":
        fail("POSTGRES_PROBE_RESTART_READBACK_MISMATCH")
    current_ownership = _parse_uid_mode(
        executor.output(
            (
                "docker",
                "exec",
                POSTGRES_PROBE_CONTAINER,
                "stat",
                "-c",
                "%u:%g:%a",
                "/var/lib/postgresql/data",
            ),
            classification="POSTGRES_PROBE_MODE_FAILED",
        ),
        classification="POSTGRES_PROBE_MODE_INVALID",
    )
    if current_ownership != ownership:
        fail("POSTGRES_PROBE_MODE_CHANGED")
    executor.output(
        ("docker", "stop", "--time", str(POSTGRES_STOP_TIMEOUT_SECONDS), POSTGRES_PROBE_CONTAINER),
        classification="POSTGRES_PROBE_FINAL_STOP_FAILED",
        timeout_seconds=POSTGRES_STOP_TIMEOUT_SECONDS + 5,
    )
    require_probe_stopped(executor, POSTGRES_PROBE_CONTAINER)


def _set_minio_alias(executor: PrivateExecutor, bundle: SecretBundle) -> None:
    executor.output(
        mc_alias_arguments(),
        classification="MINIO_PROBE_ALIAS_FAILED",
        timeout_seconds=COMMAND_TIMEOUT_SECONDS,
        input_bytes=bundle.minio_access + b"\n" + bundle.minio_secret + b"\n",
    )


def _require_minio_versioning_state(payload: bytes, *, expected_url: str) -> None:
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProbeError("MINIO_PROBE_VERSION_EVIDENCE_INVALID") from error
    if not isinstance(document, dict):
        fail("MINIO_PROBE_VERSION_EVIDENCE_INVALID")
    versioning = document.get("versioning")
    if (
        document.get("status") != "success"
        or document.get("url") != expected_url
        or not isinstance(versioning, dict)
        or versioning.get("status") != "Enabled"
        or versioning.get("MFADelete") not in (None, "Disabled")
    ):
        fail("MINIO_PROBE_VERSION_EVIDENCE_INVALID")


def _parse_minio_object_versions(
    payload: bytes,
    *,
    expected_key: str,
    expected_count: int,
) -> tuple[str, ...]:
    try:
        lines = payload.decode("utf-8").splitlines()
        documents = [json.loads(line) for line in lines]
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProbeError("MINIO_PROBE_VERSION_EVIDENCE_INVALID") from error
    if len(documents) != expected_count or not all(
        isinstance(document, dict) for document in documents
    ):
        fail("MINIO_PROBE_VERSION_EVIDENCE_INVALID")
    version_ids: list[str] = []
    for document in documents:
        version_id = document.get("versionId")
        if (
            document.get("status") != "success"
            or document.get("type") != "file"
            or document.get("key") != expected_key
            or document.get("isDeleteMarker") is not False
            or not isinstance(version_id, str)
            or _VERSION_ID.fullmatch(version_id) is None
        ):
            fail("MINIO_PROBE_VERSION_EVIDENCE_INVALID")
        version_ids.append(version_id)
    if len(set(version_ids)) != expected_count:
        fail("MINIO_PROBE_VERSION_EVIDENCE_INVALID")
    return tuple(version_ids)


def _verify_minio_object_versions(
    executor: PrivateExecutor,
    *,
    object_target: str,
    expected_payloads: tuple[bytes, ...],
    expected_version_ids: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    listing = executor.output(
        (
            "docker",
            "exec",
            MINIO_PROBE_CONTAINER,
            "mc",
            "ls",
            "--versions",
            "--json",
            object_target,
        ),
        classification="MINIO_PROBE_VERSION_LIST_FAILED",
    )
    version_ids = _parse_minio_object_versions(
        listing,
        expected_key=_MINIO_OBJECT,
        expected_count=len(expected_payloads),
    )
    if expected_version_ids is not None and set(version_ids) != set(expected_version_ids):
        fail("MINIO_PROBE_VERSION_EVIDENCE_INVALID")
    expected_hashes = {hashlib.sha256(payload).hexdigest() for payload in expected_payloads}
    observed_hashes = {
        hashlib.sha256(
            executor.output(
                (
                    "docker",
                    "exec",
                    MINIO_PROBE_CONTAINER,
                    "mc",
                    "cat",
                    "--version-id",
                    version_id,
                    object_target,
                ),
                classification="MINIO_PROBE_VERSION_READ_FAILED",
            )
        ).hexdigest()
        for version_id in version_ids
    }
    if observed_hashes != expected_hashes:
        fail("MINIO_PROBE_VERSION_HASH_MISMATCH")
    return version_ids


def _start_minio(
    executor: PrivateExecutor,
    *,
    layout: ProbeLayout,
    bundle: SecretBundle,
    created_containers: set[str],
    spec: ProbeContainerSpec,
) -> tuple[str, tuple[int, int, int], str, tuple[str, ...]]:
    created_containers.add(MINIO_PROBE_CONTAINER)
    created = (
        executor.output(
            minio_create_arguments(layout),
            classification="MINIO_PROBE_CREATE_FAILED",
        )
        .decode("ascii", errors="ignore")
        .strip()
    )
    if _CONTAINER_ID.fullmatch(created) is None:
        fail("MINIO_PROBE_CREATE_EVIDENCE_INVALID")
    executor.output(
        ("docker", "start", MINIO_PROBE_CONTAINER),
        classification="MINIO_PROBE_START_FAILED",
    )
    identifier = require_probe_container_contract(
        executor,
        spec=spec,
        secret_values=bundle.values,
        require_running=True,
    )
    if identifier != created:
        fail("MINIO_PROBE_CONTAINER_ID_CHANGED")
    _set_minio_alias(executor, bundle)
    _wait_ready(
        executor,
        ("docker", "exec", MINIO_PROBE_CONTAINER, "mc", "ready", _MINIO_ALIAS),
        classification="MINIO_PROBE_READINESS_FAILED",
    )
    target = f"{_MINIO_ALIAS}/{_MINIO_BUCKET}"
    executor.output(
        ("docker", "exec", MINIO_PROBE_CONTAINER, "mc", "mb", target),
        classification="MINIO_PROBE_BUCKET_CREATE_FAILED",
    )
    executor.output(
        ("docker", "exec", MINIO_PROBE_CONTAINER, "mc", "version", "enable", target),
        classification="MINIO_PROBE_VERSION_ENABLE_FAILED",
    )
    version = executor.output(
        (
            "docker",
            "exec",
            MINIO_PROBE_CONTAINER,
            "mc",
            "version",
            "info",
            "--json",
            target,
        ),
        classification="MINIO_PROBE_VERSION_INFO_FAILED",
    )
    _require_minio_versioning_state(version, expected_url=target)
    object_target = f"{target}/{_MINIO_OBJECT}"
    first_value = b"datariver-bind-probe-object-v1\n"
    executor.output(
        ("docker", "exec", "-i", MINIO_PROBE_CONTAINER, "mc", "pipe", object_target),
        classification="MINIO_PROBE_FIRST_WRITE_FAILED",
        input_bytes=first_value,
    )
    _verify_minio_object_versions(
        executor,
        object_target=object_target,
        expected_payloads=(first_value,),
    )
    value = b"datariver-bind-probe-object-v2\n"
    executor.output(
        ("docker", "exec", "-i", MINIO_PROBE_CONTAINER, "mc", "pipe", object_target),
        classification="MINIO_PROBE_SECOND_WRITE_FAILED",
        input_bytes=value,
    )
    version_ids = _verify_minio_object_versions(
        executor,
        object_target=object_target,
        expected_payloads=(first_value, value),
    )
    ownership = _parse_uid_mode(
        executor.output(
            (
                "docker",
                "exec",
                MINIO_PROBE_CONTAINER,
                "stat",
                "-c",
                "%u:%g:%a",
                "/data",
            ),
            classification="MINIO_PROBE_MODE_FAILED",
        ),
        classification="MINIO_PROBE_MODE_INVALID",
    )
    return identifier, ownership, hashlib.sha256(value).hexdigest(), version_ids


def _verify_minio_after_restart(
    executor: PrivateExecutor,
    *,
    identifier: str,
    layout: ProbeLayout,
    bundle: SecretBundle,
    ownership: tuple[int, int, int],
    object_sha256: str,
    version_ids: tuple[str, ...],
    spec: ProbeContainerSpec,
) -> None:
    executor.output(
        ("docker", "stop", "--time", str(MINIO_STOP_TIMEOUT_SECONDS), MINIO_PROBE_CONTAINER),
        classification="MINIO_PROBE_STOP_FAILED",
        timeout_seconds=MINIO_STOP_TIMEOUT_SECONDS + 5,
    )
    require_probe_stopped(executor, MINIO_PROBE_CONTAINER)
    executor.output(
        ("docker", "start", MINIO_PROBE_CONTAINER),
        classification="MINIO_PROBE_RESTART_FAILED",
    )
    current = require_probe_container_contract(
        executor,
        spec=spec,
        secret_values=bundle.values,
        require_running=True,
    )
    if current != identifier:
        fail("MINIO_PROBE_CONTAINER_ID_CHANGED")
    _set_minio_alias(executor, bundle)
    _wait_ready(
        executor,
        ("docker", "exec", MINIO_PROBE_CONTAINER, "mc", "ready", _MINIO_ALIAS),
        classification="MINIO_PROBE_RESTART_READINESS_FAILED",
    )
    target = f"{_MINIO_ALIAS}/{_MINIO_BUCKET}"
    version = executor.output(
        (
            "docker",
            "exec",
            MINIO_PROBE_CONTAINER,
            "mc",
            "version",
            "info",
            "--json",
            target,
        ),
        classification="MINIO_PROBE_RESTART_VERSION_FAILED",
    )
    _require_minio_versioning_state(version, expected_url=target)
    latest_value = b"datariver-bind-probe-object-v2\n"
    if hashlib.sha256(latest_value).hexdigest() != object_sha256:
        fail("MINIO_PROBE_RESTART_HASH_MISMATCH")
    _verify_minio_object_versions(
        executor,
        object_target=f"{target}/{_MINIO_OBJECT}",
        expected_payloads=(b"datariver-bind-probe-object-v1\n", latest_value),
        expected_version_ids=version_ids,
    )
    current_ownership = _parse_uid_mode(
        executor.output(
            (
                "docker",
                "exec",
                MINIO_PROBE_CONTAINER,
                "stat",
                "-c",
                "%u:%g:%a",
                "/data",
            ),
            classification="MINIO_PROBE_MODE_FAILED",
        ),
        classification="MINIO_PROBE_MODE_INVALID",
    )
    if current_ownership != ownership:
        fail("MINIO_PROBE_MODE_CHANGED")
    executor.output(
        ("docker", "stop", "--time", str(MINIO_STOP_TIMEOUT_SECONDS), MINIO_PROBE_CONTAINER),
        classification="MINIO_PROBE_FINAL_STOP_FAILED",
        timeout_seconds=MINIO_STOP_TIMEOUT_SECONDS + 5,
    )
    require_probe_stopped(executor, MINIO_PROBE_CONTAINER)


def require_probe_stopped(executor: PrivateExecutor, name: str) -> None:
    document = _json_document(
        executor.output(
            ("docker", "inspect", name),
            classification="PROBE_STOPPED_STATE_CHECK_FAILED",
        ),
        classification="PROBE_STOPPED_STATE_INVALID",
    )
    state = document.get("State")
    if (
        not isinstance(state, dict)
        or state.get("Running") is not False
        or state.get("Restarting") is not False
        or state.get("Pid") != 0
    ):
        fail("PROBE_STOPPED_STATE_INVALID")


def _remove_secret_file(path: Path, expected_identity: RegularFileIdentity) -> None:
    try:
        parent = path.parent
        parent_identity = _path_identity(parent, classification="PROBE_SECRET_PARENT_INVALID")
        current = _regular_file_identity(path, classification="PROBE_SECRET_FILE_INVALID")
        if current != expected_identity:
            fail("PROBE_SECRET_FILE_CHANGED")
        path.unlink()
        _require_same_path(parent, parent_identity, classification="PROBE_SECRET_PARENT_CHANGED")
        _fsync_directory(parent)
    except ProbeError:
        raise
    except OSError as error:
        raise ProbeError("PROBE_SECRET_UNLINK_FAILED") from error


def _secret_presence_count(paths: tuple[Path, ...]) -> int | None:
    present = 0
    for path in paths:
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            return None
        present += 1
    return present


def _failure_probe_is_stopped(executor: PrivateExecutor, name: str) -> bool:
    document = _json_document(
        executor.output(
            ("docker", "inspect", name),
            classification="PROBE_FAILURE_STATE_CHECK_FAILED",
        ),
        classification="PROBE_FAILURE_STATE_INVALID",
    )
    state = document.get("State")
    if not isinstance(state, dict):
        fail("PROBE_FAILURE_STATE_INVALID")
    running = state.get("Running")
    restarting = state.get("Restarting")
    process_identifier = state.get("Pid")
    if (
        not isinstance(running, bool)
        or not isinstance(restarting, bool)
        or not isinstance(process_identifier, int)
        or isinstance(process_identifier, bool)
        or process_identifier < 0
    ):
        fail("PROBE_FAILURE_STATE_INVALID")
    return running is False and restarting is False and process_identifier == 0


def cleanup_failure(
    executor: PrivateExecutor,
    *,
    layout: ProbeLayout | None,
    created_containers: set[str],
    secret_file_identities: tuple[
        RegularFileIdentity,
        RegularFileIdentity,
        RegularFileIdentity,
    ]
    | None,
) -> FailureCleanupEvidence:
    """Stop created probes once; unlink secrets only after both are proven stopped."""

    stopped_states: list[bool | None] = []
    timeouts = {
        POSTGRES_PROBE_CONTAINER: POSTGRES_STOP_TIMEOUT_SECONDS,
        MINIO_PROBE_CONTAINER: MINIO_STOP_TIMEOUT_SECONDS,
    }
    for name in (POSTGRES_PROBE_CONTAINER, MINIO_PROBE_CONTAINER):
        if name not in created_containers:
            stopped_states.append(False)
            continue
        try:
            initially_stopped: bool | None = _failure_probe_is_stopped(executor, name)
        except BaseException:
            initially_stopped = None
        if initially_stopped is not True:
            try:
                executor.output(
                    ("docker", "stop", "--time", str(timeouts[name]), name),
                    classification="PROBE_FAILURE_STOP_FAILED",
                    timeout_seconds=timeouts[name] + 5,
                )
            except BaseException:  # noqa: S110 - final inspect supplies bounded evidence.
                pass
        try:
            stopped_states.append(_failure_probe_is_stopped(executor, name))
        except BaseException:
            stopped_states.append(None)
    both_stopped: bool | None
    if any(state is None for state in stopped_states):
        both_stopped = None
    else:
        both_stopped = all(state is True for state in stopped_states)
    secret_paths = () if layout is None else _secret_paths(layout)
    retained = _secret_presence_count(secret_paths)
    if retained is None:
        return FailureCleanupEvidence(both_stopped, None, None)
    if both_stopped is not True or layout is None or secret_file_identities is None:
        return FailureCleanupEvidence(both_stopped, 0, retained)
    try:
        current_identities = tuple(
            _regular_file_identity(path, classification="PROBE_SECRET_FILE_INVALID")
            for path in secret_paths
        )
        if current_identities != secret_file_identities:
            fail("PROBE_SECRET_FILE_CHANGED")
    except ProbeError:
        return FailureCleanupEvidence(True, 0, retained)
    removed = 0
    try:
        for path, expected_identity in zip(
            secret_paths,
            secret_file_identities,
            strict=True,
        ):
            _remove_secret_file(path, expected_identity)
            removed += 1
    except BaseException:
        return FailureCleanupEvidence(True, None, None)
    return FailureCleanupEvidence(True, removed, 0)


def _cleanup_manifest(root: Path) -> tuple[tuple[Path, PathIdentity, bool], ...]:
    root_resolved = root.resolve(strict=True)
    entries: list[tuple[Path, PathIdentity, bool]] = []
    for current_root, directories, files in os.walk(root, topdown=True, followlinks=False):
        current = Path(current_root)
        for name in (*directories, *files):
            path = current / name
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not (
                stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)
            ):
                fail("PROBE_CLEANUP_MANIFEST_INVALID")
            if path.resolve(strict=True).is_relative_to(root_resolved) is False:
                fail("PROBE_CLEANUP_MANIFEST_INVALID")
            if stat.S_ISREG(metadata.st_mode) and metadata.st_nlink != 1:
                fail("PROBE_CLEANUP_MANIFEST_INVALID")
            entries.append(
                (
                    path,
                    PathIdentity(metadata.st_dev, metadata.st_ino, stat.S_IMODE(metadata.st_mode)),
                    stat.S_ISDIR(metadata.st_mode),
                )
            )
    return tuple(entries)


def cleanup_success(layout: ProbeLayout) -> None:
    _require_same_path(layout.leaf, layout.leaf_identity, classification="PROBE_LEAF_CHANGED")
    manifest = _cleanup_manifest(layout.leaf)
    for path, identity, is_directory in sorted(
        manifest,
        key=lambda item: (len(item[0].parts), item[1].inode),
        reverse=True,
    ):
        metadata = path.lstat()
        if metadata.st_dev != identity.device or metadata.st_ino != identity.inode:
            fail("PROBE_CLEANUP_TARGET_CHANGED")
        try:
            if is_directory:
                path.rmdir()
            else:
                path.unlink()
        except OSError as error:
            raise ProbeError("PROBE_CLEANUP_FAILED") from error
    try:
        layout.leaf.rmdir()
        _fsync_directory(layout.parent)
    except OSError as error:
        raise ProbeError("PROBE_CLEANUP_FAILED") from error
    if layout.parent_created:
        _require_same_path(
            layout.parent,
            layout.parent_identity,
            classification="PROBE_PARENT_CHANGED",
        )
        try:
            if any(layout.parent.iterdir()):
                fail("PROBE_PARENT_NOT_EMPTY")
            layout.parent.rmdir()
            _fsync_directory(layout.parent.parent)
        except ProbeError:
            raise
        except OSError as error:
            raise ProbeError("PROBE_PARENT_CLEANUP_FAILED") from error


def _filesystem_noowners(executor: PrivateExecutor) -> bool:
    payload = executor.output(("mount",), classification="PROBE_FILESYSTEM_INSPECT_FAILED")
    marker = b" on /Volumes/SSD_Mac ("
    matches = [line for line in payload.splitlines() if marker in line]
    if len(matches) != 1:
        fail("PROBE_FILESYSTEM_EVIDENCE_INVALID")
    return b"noowners" in matches[0].lower()


def execute_probe(
    executor: PrivateExecutor,
    *,
    data_parent: Path = DATA_PARENT,
) -> ProbeEvidence:
    layout: ProbeLayout | None = None
    bundle: SecretBundle | None = None
    created_containers: set[str] = set()
    with exclusive_docker_workflow_lock(ROOT) as lock:
        lock.require_held()
        baseline = capture_production_identity(executor)
        volume_names = _volume_names(executor)
        require_probe_containers_absent(executor)
        postgres_image = require_image(
            executor,
            image_id=POSTGRES_IMAGE_ID,
            entrypoint=("docker-entrypoint.sh",),
            expected_environment_keys=POSTGRES_IMAGE_ENVIRONMENT_KEY_ALLOWLIST,
            governed_environment_prefixes=("POSTGRES_",),
            reviewed_environment_keys=POSTGRES_REVIEWED_IMAGE_ENVIRONMENT_KEYS,
        )
        minio_image = require_image(
            executor,
            image_id=MINIO_IMAGE_ID,
            entrypoint=("/usr/bin/docker-entrypoint.sh",),
            expected_environment_keys=MINIO_IMAGE_ENVIRONMENT_KEY_ALLOWLIST,
            governed_environment_prefixes=("MINIO_", "MC_"),
            reviewed_environment_keys=MINIO_REVIEWED_IMAGE_ENVIRONMENT_KEYS,
        )
        filesystem_noowners = _filesystem_noowners(executor)
        try:
            layout = prepare_layout(data_parent)
            specs = _container_specs(
                layout,
                postgres_image_environment=postgres_image.environment,
                minio_image_environment=minio_image.environment,
            )
            probe_host_atomicity(layout)
            bundle = create_probe_secrets(layout)
            executor.set_forbidden(bundle.values)

            postgres_id, postgres_mode, dump_bytes, dump_sha256 = _start_postgres(
                executor,
                layout=layout,
                secrets_bundle=bundle,
                created_containers=created_containers,
                spec=specs[POSTGRES_PROBE_CONTAINER],
            )
            _verify_postgres_after_restart(
                executor,
                identifier=postgres_id,
                layout=layout,
                secret_values=bundle.values,
                ownership=postgres_mode,
                spec=specs[POSTGRES_PROBE_CONTAINER],
            )

            minio_id, minio_mode, object_sha256, version_ids = _start_minio(
                executor,
                layout=layout,
                bundle=bundle,
                created_containers=created_containers,
                spec=specs[MINIO_PROBE_CONTAINER],
            )
            _verify_minio_after_restart(
                executor,
                identifier=minio_id,
                layout=layout,
                bundle=bundle,
                ownership=minio_mode,
                object_sha256=object_sha256,
                version_ids=version_ids,
                spec=specs[MINIO_PROBE_CONTAINER],
            )

            require_production_unchanged(executor, baseline)
            if _volume_names(executor) != volume_names:
                fail("DOCKER_VOLUME_SET_CHANGED")
            for name in (POSTGRES_PROBE_CONTAINER, MINIO_PROBE_CONTAINER):
                require_probe_stopped(executor, name)
                executor.output(
                    ("docker", "container", "rm", name),
                    classification="PROBE_CONTAINER_REMOVE_FAILED",
                )
            created_containers.clear()
            cleanup_success(layout)
            require_production_unchanged(executor, baseline)
            if _volume_names(executor) != volume_names:
                fail("DOCKER_VOLUME_SET_CHANGED")
            return ProbeEvidence(
                filesystem_noowners=filesystem_noowners,
                postgres_uid=postgres_mode[0],
                postgres_gid=postgres_mode[1],
                postgres_mode=postgres_mode[2],
                minio_uid=minio_mode[0],
                minio_gid=minio_mode[1],
                minio_mode=minio_mode[2],
                postgres_dump_bytes=dump_bytes,
                postgres_dump_sha256=dump_sha256,
                minio_object_sha256=object_sha256,
            )
        except BaseException as error:
            try:
                cleanup = cleanup_failure(
                    executor,
                    layout=layout,
                    created_containers=created_containers,
                    secret_file_identities=(None if bundle is None else bundle.file_identities),
                )
            except BaseException:
                cleanup = FailureCleanupEvidence(
                    both_containers_stopped=None,
                    secret_files_removed=None,
                    secret_files_retained=None,
                )
            try:
                require_production_unchanged(executor, baseline)
                production_unchanged = True
            except BaseException:
                production_unchanged = False
            try:
                volumes_unchanged = _volume_names(executor) == volume_names
            except BaseException:
                volumes_unchanged = False
            print(
                f"{cleanup.summary()} "
                f"production_identity_unchanged={str(production_unchanged).lower()} "
                f"production_volumes_unchanged={str(volumes_unchanged).lower()}",
                file=sys.stderr,
                flush=True,
            )
            if isinstance(error, KeyboardInterrupt):
                raise
            if isinstance(error, ProbeError):
                raise error
            raise ProbeError("PROBE_INTERNAL_FAILURE") from None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm",
        required=True,
        help="Exact reviewed Security decision token; no other value is accepted.",
    )
    return parser.parse_args()


def main() -> int:
    try:
        args = _parse_args()
        if args.confirm != CONFIRMATION:
            fail("PROBE_OPERATOR_CONFIRMATION_REQUIRED")
        evidence = execute_probe(PrivateExecutor())
        print(evidence.summary(), flush=True)
        return 0
    except ProbeError as error:
        print(f"ERROR: {error}", file=sys.stderr, flush=True)
        return 2
    except KeyboardInterrupt:
        print("ERROR: PROBE_OPERATOR_INTERRUPT", file=sys.stderr, flush=True)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
