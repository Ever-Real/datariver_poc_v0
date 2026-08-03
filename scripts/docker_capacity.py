"""Fail-closed Docker build-capacity evidence for managed source workflows."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fcntl import LOCK_EX, LOCK_NB, LOCK_UN, flock
from pathlib import Path, PurePosixPath
from typing import Protocol

COMPOSE_BUILD_CONFIG_PROBE = "COMPOSE_BUILD_CONFIG_PROBE_FAILED"
DOCKER_BUILDER_LIST_PROBE = "DOCKER_BUILDER_LIST_PROBE_FAILED"
DOCKER_CONTEXT_PROBE = "DOCKER_CONTEXT_PROBE_FAILED"
DOCKER_PLATFORM_PROBE = "DOCKER_PLATFORM_PROBE_FAILED"
DOCKER_ACTIVE_BUILD_PROBE = "DOCKER_ACTIVE_BUILD_PROBE_FAILED"
DOCKER_BUILD_CACHE_PROBE = "DOCKER_BUILD_CACHE_PROBE_FAILED"
DOCKER_BUILD_CACHE_HELP_PROBE = "DOCKER_BUILD_CACHE_HELP_PROBE_FAILED"
DOCKER_BUILD_CACHE_ACTION = "DOCKER_BUILD_CACHE_ACTION_FAILED"
DOCKER_BUILD_CACHE_ACTION_FAILED_POST_MEASUREMENT_OK = (
    "DOCKER_BUILD_CACHE_ACTION_FAILED_POST_MEASUREMENT_OK"
)
DOCKER_BUILD_CACHE_ACTION_FAILED_POST_MEASUREMENT_FAILED = (
    "DOCKER_BUILD_CACHE_ACTION_FAILED_POST_MEASUREMENT_FAILED"
)
DOCKER_BUILD_CACHE_ACTION_SUCCEEDED_POST_MEASUREMENT_FAILED = (
    "DOCKER_BUILD_CACHE_ACTION_SUCCEEDED_POST_MEASUREMENT_FAILED"
)
DOCKER_BACKING_FILESYSTEM_PROBE = "DOCKER_BACKING_FILESYSTEM_PROBE_FAILED"
DOCKER_IMAGE_SIZE_PROBE = "DOCKER_IMAGE_SIZE_PROBE_FAILED"
GIT_CLEAN_CHECKOUT_PROBE = "GIT_CLEAN_CHECKOUT_PROBE_FAILED"
GIT_BUILD_CONTEXT_PROBE = "GIT_BUILD_CONTEXT_PROBE_FAILED"
DOCKER_WORKFLOW_LOCK_UNAVAILABLE = "DOCKER_WORKFLOW_LOCK_UNAVAILABLE"

_BUILDER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_COMPOSE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
_IMAGE_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@:-]{0,254}$")
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_SIZE = re.compile(r"^(\d+(?:\.\d+)?)(B|kB|MB|GB|TB|KiB|MiB|GiB|TiB)$")

_REQUIRED_DOCKERIGNORE_RULES = frozenset(
    {
        ".git",
        ".env",
        ".env.*",
        "secrets",
        "runtime",
        "docker_imgs",
        ".venv",
        ".venv-wsl",
        "frontend/node_modules",
        "frontend/dist",
    }
)


class DockerCapacityError(RuntimeError):
    """A sanitized, operator-correctable Docker capacity failure."""


class CapacityExecutor(Protocol):
    def output(
        self,
        arguments: tuple[str, ...],
        *,
        classification: str,
        timeout_seconds: int,
    ) -> str: ...


class SubprocessCapacityExecutor:
    """Run bounded argv-only probes without exposing captured provider output."""

    def output(
        self,
        arguments: tuple[str, ...],
        *,
        classification: str,
        timeout_seconds: int,
    ) -> str:
        del classification
        completed = subprocess.run(  # noqa: S603 - every argv is repository-owned.
            arguments,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return completed.stdout


class DockerWorkflowLock:
    """An exclusive process lock spanning capacity checks and Docker mutation."""

    def __init__(self, descriptor: int) -> None:
        self._descriptor = descriptor
        self._held = True

    def require_held(self) -> None:
        if not self._held:
            raise DockerCapacityError("DOCKER_WORKFLOW_LOCK_NOT_HELD")

    def release(self) -> None:
        if not self._held:
            return
        flock(self._descriptor, LOCK_UN)
        os.close(self._descriptor)
        self._held = False


def _require_private_lock_directory(root: Path) -> Path:
    runtime = root / "runtime"
    try:
        if runtime.exists():
            metadata = runtime.lstat()
            if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                raise DockerCapacityError("DOCKER_WORKFLOW_LOCK_PARENT_INVALID")
        else:
            runtime.mkdir(mode=0o700)
        lock_directory = runtime / "operator-locks"
        if lock_directory.exists():
            metadata = lock_directory.lstat()
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or stat.S_ISLNK(metadata.st_mode)
                or metadata.st_uid != os.getuid()
            ):
                raise DockerCapacityError("DOCKER_WORKFLOW_LOCK_DIRECTORY_INVALID")
        else:
            lock_directory.mkdir(mode=0o700)
        os.chmod(lock_directory, 0o700)
    except DockerCapacityError:
        raise
    except OSError:
        raise DockerCapacityError("DOCKER_WORKFLOW_LOCK_DIRECTORY_INVALID") from None
    return lock_directory


@contextmanager
def exclusive_docker_workflow_lock(root: Path) -> Iterator[DockerWorkflowLock]:
    """Acquire the ignored host-local lock without waiting or following symlinks."""

    resolved_root = root.resolve()
    lock_directory = _require_private_lock_directory(resolved_root)
    lock_path = lock_directory / "update-build.lock"
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    lock: DockerWorkflowLock | None = None
    try:
        descriptor = os.open(lock_path, flags, 0o600)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise DockerCapacityError("DOCKER_WORKFLOW_LOCK_FILE_INVALID")
        os.fchmod(descriptor, 0o600)
        try:
            flock(descriptor, LOCK_EX | LOCK_NB)
        except BlockingIOError:
            raise DockerCapacityError(DOCKER_WORKFLOW_LOCK_UNAVAILABLE) from None
        lock = DockerWorkflowLock(descriptor)
        descriptor = None
        yield lock
    except DockerCapacityError:
        raise
    except OSError:
        raise DockerCapacityError("DOCKER_WORKFLOW_LOCK_FILE_INVALID") from None
    finally:
        if lock is not None:
            lock.release()
        elif descriptor is not None:
            os.close(descriptor)


@dataclass(frozen=True)
class DockerCapacityEvidence:
    builder: str
    selected_services: int
    selected_image_tags: int
    unique_builds: int
    context_bytes: int
    image_bytes: int
    build_peak_bytes: int
    reserve_bytes: int
    required_free_bytes: int
    filesystem_total_bytes: int
    free_bytes_before: int
    free_bytes_after: int
    cache_budget_bytes: int
    cache_reserved_bytes: int
    cache_bytes_before: int
    reclaimable_cache_bytes_before: int
    cache_bytes_after: int
    reclaimable_cache_bytes_after: int
    cache_action: str

    def summary(self) -> str:
        return (
            "DOCKER_BUILD_CAPACITY_OK "
            f"builder={self.builder} "
            f"selected_services={self.selected_services} "
            f"selected_image_tags={self.selected_image_tags} "
            f"unique_builds={self.unique_builds} "
            f"context_bytes={self.context_bytes} "
            f"image_bytes={self.image_bytes} "
            f"build_peak_bytes={self.build_peak_bytes} "
            f"reserve_bytes={self.reserve_bytes} "
            f"required_free_bytes={self.required_free_bytes} "
            f"filesystem_total_bytes={self.filesystem_total_bytes} "
            f"free_bytes_before={self.free_bytes_before} "
            f"free_bytes_after={self.free_bytes_after} "
            f"cache_budget_bytes={self.cache_budget_bytes} "
            f"cache_reserved_bytes={self.cache_reserved_bytes} "
            f"cache_bytes_before={self.cache_bytes_before} "
            f"reclaimable_cache_bytes_before={self.reclaimable_cache_bytes_before} "
            f"cache_bytes_after={self.cache_bytes_after} "
            f"reclaimable_cache_bytes_after={self.reclaimable_cache_bytes_after} "
            f"cache_action={self.cache_action}"
        )


@dataclass(frozen=True)
class _BuildTarget:
    context: Path
    dockerfile: Path
    image_references: tuple[str, ...]


@dataclass
class _BuildTargetAccumulator:
    context: Path
    dockerfile: Path
    images: set[str]


def _safe_output(
    executor: CapacityExecutor,
    arguments: Sequence[str | os.PathLike[str]],
    *,
    classification: str,
    timeout_seconds: int,
) -> str:
    command = tuple(os.fspath(argument) for argument in arguments)
    try:
        return executor.output(
            command,
            classification=classification,
            timeout_seconds=timeout_seconds,
        )
    except Exception:
        raise DockerCapacityError(
            f"Docker build-capacity check stopped (classification={classification})."
        ) from None


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _require_dockerignore_contract(root: Path) -> None:
    dockerignore = root / ".dockerignore"
    if dockerignore.is_symlink() or not dockerignore.is_file():
        raise DockerCapacityError("Dockerignore contract is invalid.")
    try:
        rules = {
            line.strip()
            for line in dockerignore.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
    except OSError as error:
        raise DockerCapacityError("Dockerignore contract cannot be read.") from error
    if not _REQUIRED_DOCKERIGNORE_RULES.issubset(rules):
        raise DockerCapacityError("Dockerignore capacity exclusions are incomplete.")


def _canonical_hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _resolve_build_targets(
    raw_config: str,
    *,
    root: Path,
    selected_services: Sequence[str],
) -> dict[str, _BuildTarget]:
    try:
        document = json.loads(raw_config)
    except json.JSONDecodeError as error:
        raise DockerCapacityError("Resolved Compose build contract is invalid.") from error
    if not isinstance(document, dict):
        raise DockerCapacityError("Resolved Compose build contract is invalid.")
    project_name = document.get("name")
    services = document.get("services")
    if not isinstance(project_name, str) or _COMPOSE_NAME.fullmatch(project_name) is None:
        raise DockerCapacityError("Resolved Compose project identity is invalid.")
    if not isinstance(services, dict):
        raise DockerCapacityError("Resolved Compose services are invalid.")

    grouped: dict[str, _BuildTargetAccumulator] = {}
    for service_name in tuple(dict.fromkeys(selected_services)):
        if _COMPOSE_NAME.fullmatch(service_name) is None:
            raise DockerCapacityError("Selected Compose service identity is invalid.")
        service = services.get(service_name)
        if not isinstance(service, dict):
            raise DockerCapacityError("Selected Compose build service is unavailable.")
        build = service.get("build")
        if isinstance(build, str):
            build = {"context": build}
        if not isinstance(build, dict):
            raise DockerCapacityError("Selected Compose service has no build contract.")
        raw_context = build.get("context")
        if not isinstance(raw_context, str) or not raw_context.strip():
            raise DockerCapacityError("Selected build context is invalid.")
        context_candidate = Path(raw_context).expanduser()
        context_lexical = Path(
            os.path.abspath(
                context_candidate if context_candidate.is_absolute() else root / context_candidate
            )
        )
        context = context_lexical.resolve()
        if not _inside(context, root):
            raise DockerCapacityError("BUILD_CONTEXT_OUTSIDE_CHECKOUT")
        if context != context_lexical or not context.is_dir():
            raise DockerCapacityError("Selected build context is not a regular directory.")

        raw_dockerfile = build.get("dockerfile", "Dockerfile")
        if not isinstance(raw_dockerfile, str) or not raw_dockerfile.strip():
            raise DockerCapacityError("Selected Dockerfile path is invalid.")
        dockerfile_candidate = Path(raw_dockerfile)
        dockerfile_lexical = Path(
            os.path.abspath(
                dockerfile_candidate
                if dockerfile_candidate.is_absolute()
                else context / dockerfile_candidate
            )
        )
        dockerfile = dockerfile_lexical.resolve()
        if not _inside(dockerfile, root) or not _inside(dockerfile, context):
            raise DockerCapacityError("DOCKERFILE_OUTSIDE_BUILD_CONTEXT")
        if dockerfile != dockerfile_lexical or not dockerfile.is_file():
            raise DockerCapacityError("Selected Dockerfile is not a regular file.")

        raw_image = service.get("image")
        image = (
            raw_image
            if isinstance(raw_image, str) and raw_image
            else f"{project_name}-{service_name}"
        )
        if _IMAGE_REFERENCE.fullmatch(image) is None:
            raise DockerCapacityError("Selected build image reference is invalid.")
        fingerprint = _canonical_hash(
            {
                "context": os.fspath(context.relative_to(root)),
                "dockerfile": os.fspath(dockerfile.relative_to(root)),
                "target": build.get("target"),
                "args": build.get("args"),
            }
        )
        existing = grouped.setdefault(
            fingerprint,
            _BuildTargetAccumulator(
                context=context,
                dockerfile=dockerfile,
                images=set(),
            ),
        )
        existing.images.add(image)

    result: dict[str, _BuildTarget] = {}
    for fingerprint, fields in grouped.items():
        result[fingerprint] = _BuildTarget(
            context=fields.context,
            dockerfile=fields.dockerfile,
            image_references=tuple(sorted(fields.images)),
        )
    if not result:
        raise DockerCapacityError("No selected build evidence is available.")
    return result


def _tracked_context_bytes(
    executor: CapacityExecutor,
    *,
    root: Path,
    contexts: Sequence[Path],
) -> dict[Path, int]:
    clean = _safe_output(
        executor,
        ("git", "-C", root, "status", "--porcelain", "--untracked-files=normal"),
        classification=GIT_CLEAN_CHECKOUT_PROBE,
        timeout_seconds=10,
    )
    if clean:
        raise DockerCapacityError("BUILD_CAPACITY_REQUIRES_CLEAN_CHECKOUT")

    sizes: dict[Path, int] = {}
    for context in sorted(set(contexts)):
        relative_context = context.relative_to(root)
        output = _safe_output(
            executor,
            ("git", "-C", root, "ls-files", "-z", "--", relative_context or Path(".")),
            classification=GIT_BUILD_CONTEXT_PROBE,
            timeout_seconds=20,
        )
        total = 0
        files = [name for name in output.split("\0") if name]
        if not files:
            raise DockerCapacityError("Tracked build context is empty.")
        for name in files:
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts:
                raise DockerCapacityError("Tracked build context entry is invalid.")
            path = (root / Path(*pure.parts)).resolve(strict=False)
            if not _inside(path, root) or not _inside(path, context):
                raise DockerCapacityError("Tracked build context entry escaped its context.")
            try:
                metadata = path.lstat()
            except OSError as error:
                raise DockerCapacityError("Tracked build context entry cannot be read.") from error
            if stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                total += metadata.st_size
        if total <= 0:
            raise DockerCapacityError("Tracked build context has no byte evidence.")
        sizes[context] = total
    return sizes


def _selected_builder(
    raw: str,
    environ: Mapping[str, str],
    *,
    current_context: str,
) -> str:
    if environ.get("BUILDKIT_HOST", "").strip():
        raise DockerCapacityError("EXTERNAL_BUILDKIT_HOST_UNSUPPORTED")
    builders: dict[str, tuple[bool, str, str, str, str]] = {}
    try:
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    except json.JSONDecodeError as error:
        raise DockerCapacityError("Docker builder evidence is invalid.") from error
    for row in rows:
        if not isinstance(row, dict):
            raise DockerCapacityError("Docker builder evidence is invalid.")
        name = row.get("Name")
        current = row.get("Current")
        driver = row.get("Driver")
        nodes = row.get("Nodes")
        if (
            not isinstance(name, str)
            or _BUILDER_NAME.fullmatch(name) is None
            or not isinstance(current, bool)
            or not isinstance(driver, str)
            or not isinstance(nodes, list)
        ):
            raise DockerCapacityError("Docker builder evidence is invalid.")
        if len(nodes) != 1:
            raise DockerCapacityError("DOCKER_BUILDER_MUST_HAVE_EXACTLY_ONE_NODE")
        node_names: list[str] = []
        endpoints: list[str] = []
        status_values: list[str] = []
        for node in nodes:
            if not isinstance(node, dict):
                raise DockerCapacityError("Docker builder node evidence is invalid.")
            node_name = node.get("Name")
            endpoint = node.get("Endpoint")
            status = node.get("Status")
            if (
                not isinstance(node_name, str)
                or _BUILDER_NAME.fullmatch(node_name) is None
                or not isinstance(endpoint, str)
                or _BUILDER_NAME.fullmatch(endpoint) is None
                or not isinstance(status, str)
            ):
                raise DockerCapacityError("Docker builder node evidence is invalid.")
            node_names.append(node_name)
            endpoints.append(endpoint)
            status_values.append(status)
        evidence = (current, driver, node_names[0], endpoints[0], status_values[0])
        if name in builders and builders[name] != evidence:
            raise DockerCapacityError("Docker builder duplicate evidence conflicts.")
        builders[name] = evidence

    current_names = sorted(name for name, evidence in builders.items() if evidence[0])
    if len(current_names) != 1:
        raise DockerCapacityError("DOCKER_BUILDER_AMBIGUOUS")
    selected = current_names[0]
    override = environ.get("BUILDX_BUILDER", "").strip()
    if override:
        if _BUILDER_NAME.fullmatch(override) is None or override not in builders:
            raise DockerCapacityError("DOCKER_BUILDER_OVERRIDE_INVALID")
        if override != selected:
            raise DockerCapacityError("DOCKER_BUILDER_OVERRIDE_NOT_CURRENT")
    current, driver, node_name, endpoint, status = builders[selected]
    if not current:
        raise DockerCapacityError("DOCKER_BUILDER_NOT_CURRENT")
    if (
        driver != "docker"
        or status != "running"
        or selected != current_context
        or node_name != selected
        or endpoint != current_context
    ):
        raise DockerCapacityError("DOCKER_BUILDER_NOT_LOCAL_RUNNING_DOCKER_DRIVER")
    return selected


def _parse_size(value: object) -> int:
    if isinstance(value, int) and value >= 0:
        return value
    if not isinstance(value, str):
        raise DockerCapacityError("Docker size evidence is invalid.")
    match = _SIZE.fullmatch(value)
    if match is None:
        raise DockerCapacityError("Docker size evidence is invalid.")
    try:
        number = Decimal(match.group(1))
    except InvalidOperation as error:
        raise DockerCapacityError("Docker size evidence is invalid.") from error
    units = {
        "B": 1,
        "kB": 1_000,
        "MB": 1_000_000,
        "GB": 1_000_000_000,
        "TB": 1_000_000_000_000,
        "KiB": 1 << 10,
        "MiB": 1 << 20,
        "GiB": 1 << 30,
        "TiB": 1 << 40,
    }
    result = int(number * units[match.group(2)])
    if result < 0:
        raise DockerCapacityError("Docker size evidence is invalid.")
    return result


def _cache_bytes(raw: str) -> tuple[int, int]:
    records: dict[str, tuple[int, bool]] = {}
    try:
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    except json.JSONDecodeError as error:
        raise DockerCapacityError("Docker build-cache evidence is invalid.") from error
    for row in rows:
        if not isinstance(row, dict):
            raise DockerCapacityError("Docker build-cache evidence is invalid.")
        identifier = row.get("ID")
        reclaimable = row.get("Reclaimable")
        if not isinstance(identifier, str) or not identifier or not isinstance(reclaimable, bool):
            raise DockerCapacityError("Docker build-cache evidence is invalid.")
        evidence = (_parse_size(row.get("Size")), reclaimable)
        if identifier in records and records[identifier] != evidence:
            raise DockerCapacityError("Docker build-cache duplicate evidence conflicts.")
        records[identifier] = evidence
    total = sum(size for size, _reclaimable in records.values())
    reclaimable_total = sum(size for size, reclaimable in records.values() if reclaimable)
    return total, reclaimable_total


def _filesystem_bytes(raw: str) -> tuple[int, int]:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) < 2:
        raise DockerCapacityError("Docker backing-filesystem evidence is invalid.")
    fields = lines[-1].split()
    if len(fields) < 6 or fields[-1] != "/":
        raise DockerCapacityError("Docker backing-filesystem evidence is invalid.")
    try:
        total = int(fields[-5]) * 1024
        free = int(fields[-3]) * 1024
    except ValueError as error:
        raise DockerCapacityError("Docker backing-filesystem evidence is invalid.") from error
    if total <= 0 or free < 0 or free > total:
        raise DockerCapacityError("Docker backing-filesystem evidence is invalid.")
    return total, free


def _image_bytes(
    executor: CapacityExecutor,
    targets: Mapping[str, _BuildTarget],
    *,
    expected_platform: tuple[str, str],
) -> tuple[int, dict[str, int]]:
    by_fingerprint: dict[str, int] = {}
    for fingerprint, target in sorted(targets.items()):
        raw = _safe_output(
            executor,
            (
                "docker",
                "image",
                "inspect",
                "--format",
                "{{.Id}}\t{{.Size}}\t{{.Os}}\t{{.Architecture}}",
                *target.image_references,
            ),
            classification=DOCKER_IMAGE_SIZE_PROBE,
            timeout_seconds=20,
        )
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if len(lines) != len(target.image_references):
            raise DockerCapacityError("Selected build image evidence is incomplete.")
        sizes: list[int] = []
        for line in lines:
            fields = line.split("\t")
            if len(fields) != 4 or _IMAGE_ID.fullmatch(fields[0]) is None:
                raise DockerCapacityError("Selected build image evidence is invalid.")
            try:
                size = int(fields[1])
            except ValueError as error:
                raise DockerCapacityError("Selected build image evidence is invalid.") from error
            if size <= 0:
                raise DockerCapacityError("Selected build image evidence is invalid.")
            if (fields[2], fields[3]) != expected_platform:
                raise DockerCapacityError("Selected build image platform evidence conflicts.")
            sizes.append(size)
        by_fingerprint[fingerprint] = max(sizes)
    return sum(by_fingerprint.values()), by_fingerprint


def _probe_cache(
    executor: CapacityExecutor,
    builder: str,
) -> tuple[int, int]:
    raw = _safe_output(
        executor,
        (
            "docker",
            "buildx",
            "du",
            "--builder",
            builder,
            "--timeout",
            "20s",
            "--format",
            "{{json .}}",
        ),
        classification=DOCKER_BUILD_CACHE_PROBE,
        timeout_seconds=25,
    )
    return _cache_bytes(raw)


def _probe_filesystem(
    executor: CapacityExecutor,
    command: Sequence[str | os.PathLike[str]],
) -> tuple[int, int]:
    raw = _safe_output(
        executor,
        command,
        classification=DOCKER_BACKING_FILESYSTEM_PROBE,
        timeout_seconds=20,
    )
    return _filesystem_bytes(raw)


def _require_local_unix_docker_context(
    executor: CapacityExecutor,
    environ: Mapping[str, str],
) -> str:
    docker_host = environ.get("DOCKER_HOST", "").strip()
    docker_context = environ.get("DOCKER_CONTEXT", "").strip()
    if docker_host and docker_context:
        raise DockerCapacityError("DOCKER_CONTEXT_SELECTION_AMBIGUOUS")
    if docker_host and not docker_host.startswith("unix:///"):
        raise DockerCapacityError("DOCKER_CONTEXT_MUST_BE_LOCAL_UNIX")
    raw = _safe_output(
        executor,
        (
            "docker",
            "context",
            "inspect",
            "--format",
            "{{json .Name}}|{{json .Endpoints.docker.Host}}",
        ),
        classification=DOCKER_CONTEXT_PROBE,
        timeout_seconds=10,
    )
    fields = raw.strip().split("|")
    if len(fields) != 2:
        raise DockerCapacityError("DOCKER_CONTEXT_ENDPOINT_INVALID")
    try:
        context_name = json.loads(fields[0])
        endpoint = json.loads(fields[1])
    except json.JSONDecodeError:
        raise DockerCapacityError("DOCKER_CONTEXT_ENDPOINT_INVALID") from None
    if (
        not isinstance(context_name, str)
        or _BUILDER_NAME.fullmatch(context_name) is None
        or not isinstance(endpoint, str)
        or not endpoint.startswith("unix:///")
        or "\n" in endpoint
        or "\r" in endpoint
    ):
        raise DockerCapacityError("DOCKER_CONTEXT_MUST_BE_LOCAL_UNIX")
    if docker_context and docker_context != context_name:
        raise DockerCapacityError("DOCKER_CONTEXT_SELECTION_AMBIGUOUS")
    if docker_host and docker_host != endpoint:
        raise DockerCapacityError("DOCKER_CONTEXT_SELECTION_AMBIGUOUS")
    return context_name


def _docker_platform(executor: CapacityExecutor) -> tuple[str, str]:
    raw = _safe_output(
        executor,
        ("docker", "version", "--format", "{{.Server.Os}}/{{.Server.Arch}}"),
        classification=DOCKER_PLATFORM_PROBE,
        timeout_seconds=10,
    )
    fields = raw.strip().split("/")
    if len(fields) != 2 or fields[0] != "linux" or fields[1] not in {"amd64", "arm64"}:
        raise DockerCapacityError("DOCKER_PLATFORM_EVIDENCE_INVALID")
    return fields[0], fields[1]


def require_no_active_builds(
    *,
    builder: str,
    lock: DockerWorkflowLock,
    executor: CapacityExecutor | None = None,
) -> None:
    """Fail closed unless the selected builder has no running build records."""

    lock.require_held()
    if _BUILDER_NAME.fullmatch(builder) is None:
        raise DockerCapacityError("DOCKER_BUILDER_IDENTITY_INVALID")
    command_executor = executor or SubprocessCapacityExecutor()
    raw = _safe_output(
        command_executor,
        (
            "docker",
            "buildx",
            "history",
            "ls",
            "--builder",
            builder,
            "--filter",
            "status=running",
            "--format",
            "{{.Status}}",
        ),
        classification=DOCKER_ACTIVE_BUILD_PROBE,
        timeout_seconds=20,
    )
    statuses = tuple(line.strip().lower() for line in raw.splitlines() if line.strip())
    if any(status != "running" for status in statuses):
        raise DockerCapacityError("DOCKER_ACTIVE_BUILD_EVIDENCE_INVALID")
    if statuses:
        raise DockerCapacityError("DOCKER_ACTIVE_BUILD_PRESENT")


def _cli_megabytes(value: int) -> str:
    return f"{max(1, (value + 999_999) // 1_000_000)}mb"


def _post_action_error(
    *,
    classification: str,
    builder: str,
    action_succeeded: bool,
    cache_bytes_before: int,
    reclaimable_cache_bytes_before: int,
    free_bytes_before: int,
    filesystem_total_bytes_before: int,
    cache_after: tuple[int, int] | None,
    filesystem_after: tuple[int, int] | None,
) -> DockerCapacityError:
    allowed_classifications = {
        DOCKER_BUILD_CACHE_ACTION_FAILED_POST_MEASUREMENT_OK,
        DOCKER_BUILD_CACHE_ACTION_FAILED_POST_MEASUREMENT_FAILED,
        DOCKER_BUILD_CACHE_ACTION_SUCCEEDED_POST_MEASUREMENT_FAILED,
        "DOCKER_BACKING_FILESYSTEM_CHANGED_DURING_PREFLIGHT",
        "BUILDKIT_CACHE_BUDGET_NOT_RESTORED",
        "DOCKER_CAPACITY_INSUFFICIENT_AFTER_CACHE_ACTION",
    }
    if classification not in allowed_classifications:
        return DockerCapacityError("DOCKER_BUILD_CACHE_POST_ACTION_EVIDENCE_INVALID")
    if _BUILDER_NAME.fullmatch(builder) is None:
        return DockerCapacityError("DOCKER_BUILD_CACHE_POST_ACTION_EVIDENCE_INVALID")
    before_values = (
        cache_bytes_before,
        reclaimable_cache_bytes_before,
        free_bytes_before,
        filesystem_total_bytes_before,
    )
    if any(value < 0 for value in before_values) or filesystem_total_bytes_before <= 0:
        return DockerCapacityError("DOCKER_BUILD_CACHE_POST_ACTION_EVIDENCE_INVALID")
    fields = [
        f"classification={classification}",
        f"builder={builder}",
        f"action_succeeded={'true' if action_succeeded else 'false'}",
        f"filesystem_total_before={filesystem_total_bytes_before}",
        f"cache_before={cache_bytes_before}",
        f"reclaimable_before={reclaimable_cache_bytes_before}",
        f"free_before={free_bytes_before}",
        "action_attempts=1",
        "retry_count=0",
        f"cache_probe_ok={'true' if cache_after is not None else 'false'}",
        f"filesystem_probe_ok={'true' if filesystem_after is not None else 'false'}",
    ]
    if cache_after is not None:
        cache_bytes_after, reclaimable_cache_bytes_after = cache_after
        if cache_bytes_after < 0 or reclaimable_cache_bytes_after < 0:
            return DockerCapacityError("DOCKER_BUILD_CACHE_POST_ACTION_EVIDENCE_INVALID")
        fields.extend(
            (
                f"cache_after={cache_bytes_after}",
                f"reclaimable_after={reclaimable_cache_bytes_after}",
                f"cache_delta_signed={cache_bytes_after - cache_bytes_before}",
            )
        )
    if filesystem_after is not None:
        filesystem_total_bytes_after, free_bytes_after = filesystem_after
        if (
            filesystem_total_bytes_after <= 0
            or free_bytes_after < 0
            or free_bytes_after > filesystem_total_bytes_after
        ):
            return DockerCapacityError("DOCKER_BUILD_CACHE_POST_ACTION_EVIDENCE_INVALID")
        fields.extend(
            (
                f"filesystem_total_after={filesystem_total_bytes_after}",
                f"free_after={free_bytes_after}",
                f"free_delta_signed={free_bytes_after - free_bytes_before}",
            )
        )
    return DockerCapacityError(" ".join(fields))


def governed_compose_build_capacity(
    *,
    root: Path,
    compose_config_command: Sequence[str | os.PathLike[str]],
    docker_filesystem_probe_command: Sequence[str | os.PathLike[str]],
    selected_build_services: Sequence[str],
    environ: Mapping[str, str],
    lock: DockerWorkflowLock,
    executor: CapacityExecutor | None = None,
) -> DockerCapacityEvidence:
    """Prove selected builds fit before any Docker runtime mutation."""

    selected = tuple(dict.fromkeys(selected_build_services))
    if not selected:
        raise DockerCapacityError("No selected build services were supplied.")
    lock.require_held()
    resolved_root = root.resolve()
    _require_dockerignore_contract(resolved_root)
    command_executor = executor or SubprocessCapacityExecutor()
    raw_config = _safe_output(
        command_executor,
        compose_config_command,
        classification=COMPOSE_BUILD_CONFIG_PROBE,
        timeout_seconds=30,
    )
    targets = _resolve_build_targets(raw_config, root=resolved_root, selected_services=selected)
    context_sizes = _tracked_context_bytes(
        command_executor,
        root=resolved_root,
        contexts=tuple(target.context for target in targets.values()),
    )
    total_context_bytes = sum(context_sizes[target.context] for target in targets.values())

    current_context = _require_local_unix_docker_context(command_executor, environ)
    builder = _selected_builder(
        _safe_output(
            command_executor,
            ("docker", "buildx", "ls", "--format", "{{json .}}"),
            classification=DOCKER_BUILDER_LIST_PROBE,
            timeout_seconds=20,
        ),
        environ,
        current_context=current_context,
    )
    platform = _docker_platform(command_executor)
    total_image_bytes, image_sizes = _image_bytes(
        command_executor,
        targets,
        expected_platform=platform,
    )
    cache_before, reclaimable_before = _probe_cache(command_executor, builder)
    filesystem_total, free_before = _probe_filesystem(
        command_executor,
        docker_filesystem_probe_command,
    )

    build_peak = sum(
        (2 * image_sizes[fingerprint]) + context_sizes[target.context]
        for fingerprint, target in targets.items()
    )
    reserve = (filesystem_total + 9) // 10
    required = build_peak + reserve
    cache_budget = (filesystem_total + 7) // 8
    cache_reserved = cache_budget // 2
    if (
        build_peak <= 0
        or reserve <= 0
        or required <= 0
        or required > filesystem_total
        or cache_reserved <= 0
        or cache_reserved > cache_budget
        or cache_budget >= filesystem_total
    ):
        raise DockerCapacityError("DOCKER_BUILD_CAPACITY_POLICY_INFEASIBLE")
    cache_action = "none"
    cache_after = cache_before
    reclaimable_after = reclaimable_before
    free_after = free_before

    if cache_before > cache_budget:
        required_cache_recovery = cache_before - cache_budget
        if reclaimable_before < required_cache_recovery:
            raise DockerCapacityError("BUILDKIT_CACHE_RECLAIMABLE_INSUFFICIENT")
        recoverable_while_retaining_floor = min(
            reclaimable_before,
            max(0, cache_before - cache_reserved),
        )
        if free_before + recoverable_while_retaining_floor < required:
            raise DockerCapacityError("DOCKER_CAPACITY_INSUFFICIENT_FOR_CACHE_ACTION")
        help_output = _safe_output(
            command_executor,
            ("docker", "buildx", "prune", "--help"),
            classification=DOCKER_BUILD_CACHE_HELP_PROBE,
            timeout_seconds=10,
        )
        required_flags = {
            "--all",
            "--builder",
            "--force",
            "--max-used-space",
            "--min-free-space",
            "--reserved-space",
        }
        if any(flag not in help_output for flag in required_flags):
            raise DockerCapacityError("BUILDKIT_CACHE_POLICY_UNSUPPORTED")
        require_no_active_builds(
            builder=builder,
            lock=lock,
            executor=command_executor,
        )
        action_succeeded = True
        try:
            _safe_output(
                command_executor,
                (
                    "docker",
                    "buildx",
                    "prune",
                    "--builder",
                    builder,
                    "--all",
                    "--force",
                    "--reserved-space",
                    _cli_megabytes(cache_reserved),
                    "--max-used-space",
                    _cli_megabytes(cache_budget),
                    "--min-free-space",
                    _cli_megabytes(required),
                ),
                classification=DOCKER_BUILD_CACHE_ACTION,
                timeout_seconds=300,
            )
        except DockerCapacityError:
            action_succeeded = False

        cache_measurement_after: tuple[int, int] | None = None
        filesystem_measurement_after: tuple[int, int] | None = None
        try:
            cache_measurement_after = _probe_cache(command_executor, builder)
        except DockerCapacityError:
            pass
        try:
            filesystem_measurement_after = _probe_filesystem(
                command_executor,
                docker_filesystem_probe_command,
            )
        except DockerCapacityError:
            pass
        if cache_measurement_after is None or filesystem_measurement_after is None:
            classification = (
                DOCKER_BUILD_CACHE_ACTION_SUCCEEDED_POST_MEASUREMENT_FAILED
                if action_succeeded
                else DOCKER_BUILD_CACHE_ACTION_FAILED_POST_MEASUREMENT_FAILED
            )
            raise _post_action_error(
                classification=classification,
                builder=builder,
                action_succeeded=action_succeeded,
                cache_bytes_before=cache_before,
                reclaimable_cache_bytes_before=reclaimable_before,
                free_bytes_before=free_before,
                filesystem_total_bytes_before=filesystem_total,
                cache_after=cache_measurement_after,
                filesystem_after=filesystem_measurement_after,
            )
        cache_after, reclaimable_after = cache_measurement_after
        filesystem_total_after, free_after = filesystem_measurement_after
        if not action_succeeded:
            raise _post_action_error(
                classification=DOCKER_BUILD_CACHE_ACTION_FAILED_POST_MEASUREMENT_OK,
                builder=builder,
                action_succeeded=False,
                cache_bytes_before=cache_before,
                reclaimable_cache_bytes_before=reclaimable_before,
                free_bytes_before=free_before,
                filesystem_total_bytes_before=filesystem_total,
                cache_after=cache_measurement_after,
                filesystem_after=filesystem_measurement_after,
            )
        if filesystem_total_after != filesystem_total:
            raise _post_action_error(
                classification="DOCKER_BACKING_FILESYSTEM_CHANGED_DURING_PREFLIGHT",
                builder=builder,
                action_succeeded=True,
                cache_bytes_before=cache_before,
                reclaimable_cache_bytes_before=reclaimable_before,
                free_bytes_before=free_before,
                filesystem_total_bytes_before=filesystem_total,
                cache_after=cache_measurement_after,
                filesystem_after=filesystem_measurement_after,
            )
        if cache_after > cache_budget:
            raise _post_action_error(
                classification="BUILDKIT_CACHE_BUDGET_NOT_RESTORED",
                builder=builder,
                action_succeeded=True,
                cache_bytes_before=cache_before,
                reclaimable_cache_bytes_before=reclaimable_before,
                free_bytes_before=free_before,
                filesystem_total_bytes_before=filesystem_total,
                cache_after=cache_measurement_after,
                filesystem_after=filesystem_measurement_after,
            )
        if free_after < required:
            raise _post_action_error(
                classification="DOCKER_CAPACITY_INSUFFICIENT_AFTER_CACHE_ACTION",
                builder=builder,
                action_succeeded=True,
                cache_bytes_before=cache_before,
                reclaimable_cache_bytes_before=reclaimable_before,
                free_bytes_before=free_before,
                filesystem_total_bytes_before=filesystem_total,
                cache_after=cache_measurement_after,
                filesystem_after=filesystem_measurement_after,
            )
        cache_action = "bounded-prune-all"

    if free_after < required:
        raise DockerCapacityError("DOCKER_CAPACITY_INSUFFICIENT")
    return DockerCapacityEvidence(
        builder=builder,
        selected_services=len(selected),
        selected_image_tags=sum(len(target.image_references) for target in targets.values()),
        unique_builds=len(targets),
        context_bytes=total_context_bytes,
        image_bytes=total_image_bytes,
        build_peak_bytes=build_peak,
        reserve_bytes=reserve,
        required_free_bytes=required,
        filesystem_total_bytes=filesystem_total,
        free_bytes_before=free_before,
        free_bytes_after=free_after,
        cache_budget_bytes=cache_budget,
        cache_reserved_bytes=cache_reserved,
        cache_bytes_before=cache_before,
        reclaimable_cache_bytes_before=reclaimable_before,
        cache_bytes_after=cache_after,
        reclaimable_cache_bytes_after=reclaimable_after,
        cache_action=cache_action,
    )
