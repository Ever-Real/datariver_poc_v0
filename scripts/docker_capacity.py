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
from enum import StrEnum
from fcntl import LOCK_EX, LOCK_NB, LOCK_UN, flock
from pathlib import Path, PurePosixPath
from typing import NoReturn, Protocol

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
_OFFICIAL_BUILDX_DRIVER_KINDS = (
    "docker",
    "docker-container",
    "kubernetes",
    "remote",
)
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


class DockerCapacityMode(StrEnum):
    """Fixed mutation policy for one canonical capacity evaluation."""

    ACTION_ENABLED = "ACTION_ENABLED"
    MEASURE_ONLY = "MEASURE_ONLY"


class BuilderSelectionPredicate(StrEnum):
    """Closed, value-free outcome of the canonical builder selection contract."""

    EXTERNAL_BUILDKIT_HOST = "EXTERNAL_BUILDKIT_HOST"
    LIST_JSON = "LIST_JSON"
    ROW_SCHEMA = "ROW_SCHEMA"
    NODE_COUNT = "NODE_COUNT"
    NODE_SCHEMA = "NODE_SCHEMA"
    DUPLICATE_CONFLICT = "DUPLICATE_CONFLICT"
    CURRENT_MISSING = "CURRENT_MISSING"
    CURRENT_AMBIGUOUS = "CURRENT_AMBIGUOUS"
    OVERRIDE_INVALID = "OVERRIDE_INVALID"
    OVERRIDE_NOT_CURRENT = "OVERRIDE_NOT_CURRENT"
    DRIVER_NOT_DOCKER = "DRIVER_NOT_DOCKER"
    NODE_NOT_RUNNING = "NODE_NOT_RUNNING"
    BUILDER_CONTEXT_MISMATCH = "BUILDER_CONTEXT_MISMATCH"
    NODE_NAME_MISMATCH = "NODE_NAME_MISMATCH"
    ENDPOINT_CONTEXT_MISMATCH = "ENDPOINT_CONTEXT_MISMATCH"
    PASS = "PASS"  # noqa: S105 - fixed diagnostic predicate, not a secret.
    UNKNOWN = "UNKNOWN"


@dataclass(slots=True)
class BuilderSelectionRecorder:
    """Retain one structurally observed builder-selection outcome."""

    predicate: BuilderSelectionPredicate = BuilderSelectionPredicate.UNKNOWN

    @property
    def known(self) -> bool:
        return self.predicate is not BuilderSelectionPredicate.UNKNOWN

    def record(self, predicate: BuilderSelectionPredicate) -> None:
        if (
            not isinstance(predicate, BuilderSelectionPredicate)
            or predicate is BuilderSelectionPredicate.UNKNOWN
            or self.known
        ):
            raise DockerCapacityError("BUILDER_SELECTION_EVIDENCE_INVALID")
        self.predicate = predicate


class NodeSchemaPredicate(StrEnum):
    """Closed, value-free outcome of the Buildx node structural contract."""

    NODE_NOT_MAPPING = "NODE_NOT_MAPPING"
    NAME_MISSING = "NAME_MISSING"
    NAME_NULL = "NAME_NULL"
    NAME_NOT_STRING = "NAME_NOT_STRING"
    ENDPOINT_MISSING = "ENDPOINT_MISSING"
    ENDPOINT_NULL = "ENDPOINT_NULL"
    ENDPOINT_NOT_STRING = "ENDPOINT_NOT_STRING"
    STATUS_NULL = "STATUS_NULL"
    STATUS_NOT_STRING = "STATUS_NOT_STRING"
    PASS = "PASS"  # noqa: S105 - fixed diagnostic predicate, not a secret.
    UNKNOWN = "UNKNOWN"


class DockerBuilderSelectionPlanPredicate(StrEnum):
    """Closed, value-free plan construction outcome."""

    CURRENT_SELECTION_CONTRACT = "CURRENT_SELECTION_CONTRACT"
    CURRENT_ALREADY_CANONICAL = "CURRENT_ALREADY_CANONICAL"
    INVENTORY_DUPLICATE = "INVENTORY_DUPLICATE"
    CURRENT_COUNT = "CURRENT_COUNT"
    PRIOR_DRIVER = "PRIOR_DRIVER"
    PRIOR_STATUS = "PRIOR_STATUS"
    TARGET_MISSING = "TARGET_MISSING"
    TARGET_DRIVER = "TARGET_DRIVER"
    TARGET_STATUS = "TARGET_STATUS"
    TARGET_NODE_NAME = "TARGET_NODE_NAME"
    TARGET_ENDPOINT = "TARGET_ENDPOINT"
    TARGET_CURRENT = "TARGET_CURRENT"
    PLAN_DRIFT = "PLAN_DRIFT"
    PASS = "PASS"  # noqa: S105 - fixed diagnostic predicate, not a secret.
    UNKNOWN = "UNKNOWN"


@dataclass(slots=True)
class DockerBuilderSelectionPlanRecorder:
    """Retain one structurally observed plan outcome without provider values."""

    predicate: DockerBuilderSelectionPlanPredicate = DockerBuilderSelectionPlanPredicate.UNKNOWN

    @property
    def known(self) -> bool:
        return self.predicate is not DockerBuilderSelectionPlanPredicate.UNKNOWN

    def record(self, predicate: DockerBuilderSelectionPlanPredicate) -> None:
        if (
            not isinstance(predicate, DockerBuilderSelectionPlanPredicate)
            or predicate is DockerBuilderSelectionPlanPredicate.UNKNOWN
            or self.known
        ):
            raise DockerCapacityError("DOCKER_BUILDER_SELECTION_PLAN_EVIDENCE_INVALID")
        self.predicate = predicate

    def replace_pass_with_drift(self) -> None:
        if self.predicate is not DockerBuilderSelectionPlanPredicate.PASS:
            raise DockerCapacityError("DOCKER_BUILDER_SELECTION_PLAN_EVIDENCE_INVALID")
        self.predicate = DockerBuilderSelectionPlanPredicate.PLAN_DRIFT


class PriorDriverPredicate(StrEnum):
    """Closed, value-free classification of the plan's current prior driver."""

    KUBERNETES = "KUBERNETES"
    REMOTE = "REMOTE"
    UNRECOGNIZED = "UNRECOGNIZED"
    PASS = "PASS"  # noqa: S105 - fixed diagnostic predicate, not a secret.
    UNKNOWN = "UNKNOWN"


@dataclass(slots=True)
class PriorDriverRecorder:
    """Retain one exact prior-driver outcome without exposing its raw value."""

    predicate: PriorDriverPredicate = PriorDriverPredicate.UNKNOWN

    @property
    def known(self) -> bool:
        return self.predicate is not PriorDriverPredicate.UNKNOWN

    def record(self, predicate: PriorDriverPredicate) -> None:
        if (
            not isinstance(predicate, PriorDriverPredicate)
            or predicate is PriorDriverPredicate.UNKNOWN
            or self.known
        ):
            raise DockerCapacityError("PRIOR_DRIVER_EVIDENCE_INVALID")
        self.predicate = predicate


@dataclass(slots=True)
class NodeSchemaRecorder:
    """Retain one structurally observed Buildx node-schema outcome."""

    predicate: NodeSchemaPredicate = NodeSchemaPredicate.UNKNOWN

    @property
    def known(self) -> bool:
        return self.predicate is not NodeSchemaPredicate.UNKNOWN

    def record(self, predicate: NodeSchemaPredicate) -> None:
        if (
            not isinstance(predicate, NodeSchemaPredicate)
            or predicate is NodeSchemaPredicate.UNKNOWN
            or self.known
        ):
            raise DockerCapacityError("NODE_SCHEMA_EVIDENCE_INVALID")
        self.predicate = predicate


@dataclass(frozen=True)
class DockerBuilderIdentity:
    """One validated Buildx row kept private by governed operator code."""

    name: str
    current: bool
    driver: str
    node_name: str
    endpoint: str
    status: str

    @property
    def stable_identity(self) -> tuple[str, str, str, str, str]:
        """Return every identity field except the mutable current-selection flag."""

        return (self.name, self.driver, self.node_name, self.endpoint, self.status)


@dataclass(frozen=True)
class DockerBuilderInventory:
    """A complete validated Buildx inventory whose values must never be rendered."""

    current_context: str
    builders: tuple[DockerBuilderIdentity, ...]
    row_count: int

    @property
    def stable_identity(self) -> tuple[tuple[str, str, str, str, str], ...]:
        return tuple(sorted(builder.stable_identity for builder in self.builders))

    @property
    def selection_identity(self) -> tuple[tuple[str, bool], ...]:
        return tuple(sorted((builder.name, builder.current) for builder in self.builders))


@dataclass(frozen=True)
class DockerBuilderSelectionPlan:
    """One exact existing-builder selection transition held only in memory."""

    inventory: DockerBuilderInventory
    prior_builder: str
    target_builder: str

    @property
    def selection_argv(self) -> tuple[str, ...]:
        return ("docker", "buildx", "use", self.target_builder)

    @property
    def rollback_argv(self) -> tuple[str, ...]:
        return ("docker", "buildx", "use", self.prior_builder)


class BuildCapacityPreflightPredicate(StrEnum):
    """Closed, value-free first-failure phases for the read-only diagnostic."""

    HOST_ENVIRONMENT_PREFLIGHT = "HOST_ENVIRONMENT_PREFLIGHT"
    SOURCE_PROVENANCE = "SOURCE_PROVENANCE"
    COMPOSE_ARGUMENTS = "COMPOSE_ARGUMENTS"
    LOCK_CONTRACT = "LOCK_CONTRACT"
    CLEAN_CHECKOUT = "CLEAN_CHECKOUT"
    DOCKERIGNORE_CONTRACT = "DOCKERIGNORE_CONTRACT"
    COMPOSE_CONFIG = "COMPOSE_CONFIG"
    BUILD_TARGET_CONTRACT = "BUILD_TARGET_CONTRACT"
    TRACKED_CONTEXT = "TRACKED_CONTEXT"
    DOCKER_CONTEXT = "DOCKER_CONTEXT"
    BUILDER_LIST_PROBE = "BUILDER_LIST_PROBE"
    BUILDER_SELECTION = "BUILDER_SELECTION"
    DOCKER_PLATFORM = "DOCKER_PLATFORM"
    IMAGE_EVIDENCE = "IMAGE_EVIDENCE"
    CACHE_EVIDENCE = "CACHE_EVIDENCE"
    FILESYSTEM_EVIDENCE = "FILESYSTEM_EVIDENCE"
    CAPACITY_POLICY = "CAPACITY_POLICY"
    CAPACITY_CACHE_POLICY_SUPPORT = "CAPACITY_CACHE_POLICY_SUPPORT"
    CAPACITY_CACHE_ACTIVE_BUILD = "CAPACITY_CACHE_ACTIVE_BUILD"
    CACHE_ACTION_REQUIRED = "CACHE_ACTION_REQUIRED"
    INITIAL_BUILDER_IDLE_PROBE = "INITIAL_BUILDER_IDLE_PROBE"
    INITIAL_BUILDER_ACTIVE = "INITIAL_BUILDER_ACTIVE"
    PASS = "PASS"  # noqa: S105 - fixed diagnostic predicate, not a secret.
    UNKNOWN = "UNKNOWN"


@dataclass(slots=True)
class DockerCapacityPhaseRecorder:
    """Retain only the current closed capacity phase, never provider details."""

    predicate: BuildCapacityPreflightPredicate = BuildCapacityPreflightPredicate.UNKNOWN

    def mark(self, predicate: BuildCapacityPreflightPredicate) -> None:
        if not isinstance(predicate, BuildCapacityPreflightPredicate):
            raise DockerCapacityError("DOCKER_BUILD_CAPACITY_PHASE_INVALID")
        self.predicate = predicate


class DockerCapacityPhaseError(DockerCapacityError):
    """Preserve an existing sanitized error plus its structural phase."""

    def __init__(self, message: str, predicate: BuildCapacityPreflightPredicate) -> None:
        super().__init__(message)
        self.predicate = predicate


class DockerCapacityMeasureOnlyStop(DockerCapacityPhaseError):
    """Stop a read-only evaluation immediately before its cache action."""

    def __init__(self) -> None:
        super().__init__(
            "DOCKER_BUILD_CACHE_ACTION_REQUIRED",
            BuildCapacityPreflightPredicate.CACHE_ACTION_REQUIRED,
        )


@contextmanager
def _capacity_phase(
    recorder: DockerCapacityPhaseRecorder | None,
    predicate: BuildCapacityPreflightPredicate,
) -> Iterator[None]:
    if recorder is not None:
        recorder.mark(predicate)
    try:
        yield
    except DockerCapacityPhaseError:
        raise
    except DockerCapacityError as error:
        if recorder is not None:
            raise DockerCapacityPhaseError(str(error), predicate) from None
        raise


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
class BuildCacheUsage:
    """Bounded Buildx disk-usage partitions without cache identities."""

    record_count: int
    logical_bytes: int
    reclaimable_record_count: int
    reclaimable_logical_bytes: int
    private_record_count: int
    private_bytes: int
    reclaimable_private_record_count: int
    reclaimable_private_bytes: int
    shared_record_count: int
    shared_bytes: int
    reclaimable_shared_record_count: int
    reclaimable_shared_bytes: int

    def __post_init__(self) -> None:
        values = (
            self.record_count,
            self.logical_bytes,
            self.reclaimable_record_count,
            self.reclaimable_logical_bytes,
            self.private_record_count,
            self.private_bytes,
            self.reclaimable_private_record_count,
            self.reclaimable_private_bytes,
            self.shared_record_count,
            self.shared_bytes,
            self.reclaimable_shared_record_count,
            self.reclaimable_shared_bytes,
        )
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values
        ):
            raise DockerCapacityError("Docker build-cache partition evidence is invalid.")
        if (
            self.record_count != self.private_record_count + self.shared_record_count
            or self.logical_bytes != self.private_bytes + self.shared_bytes
            or self.reclaimable_record_count
            != self.reclaimable_private_record_count + self.reclaimable_shared_record_count
            or self.reclaimable_logical_bytes
            != self.reclaimable_private_bytes + self.reclaimable_shared_bytes
            or self.reclaimable_private_record_count > self.private_record_count
            or self.reclaimable_shared_record_count > self.shared_record_count
            or self.reclaimable_private_bytes > self.private_bytes
            or self.reclaimable_shared_bytes > self.shared_bytes
        ):
            raise DockerCapacityError("Docker build-cache partition evidence is invalid.")


def _cache_usage_fields(usage: BuildCacheUsage, *, suffix: str) -> tuple[str, ...]:
    if suffix not in {"before", "after"}:
        raise DockerCapacityError("Docker build-cache evidence suffix is invalid.")
    return (
        f"logical_cache_records_{suffix}={usage.record_count}",
        f"logical_cache_bytes_{suffix}={usage.logical_bytes}",
        f"reclaimable_logical_cache_records_{suffix}={usage.reclaimable_record_count}",
        f"reclaimable_logical_cache_bytes_{suffix}={usage.reclaimable_logical_bytes}",
        f"private_cache_records_{suffix}={usage.private_record_count}",
        f"private_cache_bytes_{suffix}={usage.private_bytes}",
        f"reclaimable_private_cache_records_{suffix}={usage.reclaimable_private_record_count}",
        f"reclaimable_private_cache_bytes_{suffix}={usage.reclaimable_private_bytes}",
        f"shared_cache_records_{suffix}={usage.shared_record_count}",
        f"shared_cache_bytes_{suffix}={usage.shared_bytes}",
        f"reclaimable_shared_cache_records_{suffix}={usage.reclaimable_shared_record_count}",
        f"reclaimable_shared_cache_bytes_{suffix}={usage.reclaimable_shared_bytes}",
    )


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
    cache_before: BuildCacheUsage
    cache_after: BuildCacheUsage
    cache_action: str

    def summary(self) -> str:
        fields = (
            "DOCKER_BUILD_CAPACITY_OK",
            f"builder={self.builder}",
            f"selected_services={self.selected_services}",
            f"selected_image_tags={self.selected_image_tags}",
            f"unique_builds={self.unique_builds}",
            f"context_bytes={self.context_bytes}",
            f"image_bytes={self.image_bytes}",
            f"build_peak_bytes={self.build_peak_bytes}",
            f"reserve_bytes={self.reserve_bytes}",
            f"required_free_bytes={self.required_free_bytes}",
            f"filesystem_total_bytes={self.filesystem_total_bytes}",
            f"free_bytes_before={self.free_bytes_before}",
            f"free_bytes_after={self.free_bytes_after}",
            f"cache_budget_bytes={self.cache_budget_bytes}",
            f"cache_reserved_bytes={self.cache_reserved_bytes}",
            *_cache_usage_fields(self.cache_before, suffix="before"),
            *_cache_usage_fields(self.cache_after, suffix="after"),
            f"cache_action={self.cache_action}",
        )
        return " ".join(fields)


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
    phase_recorder: DockerCapacityPhaseRecorder | None = None,
) -> dict[Path, int]:
    with _capacity_phase(
        phase_recorder,
        BuildCapacityPreflightPredicate.CLEAN_CHECKOUT,
    ):
        clean = _safe_output(
            executor,
            ("git", "-C", root, "status", "--porcelain", "--untracked-files=normal"),
            classification=GIT_CLEAN_CHECKOUT_PROBE,
            timeout_seconds=10,
        )
        if clean:
            raise DockerCapacityError("BUILD_CAPACITY_REQUIRES_CLEAN_CHECKOUT")

    sizes: dict[Path, int] = {}
    with _capacity_phase(
        phase_recorder,
        BuildCapacityPreflightPredicate.TRACKED_CONTEXT,
    ):
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
                    raise DockerCapacityError(
                        "Tracked build context entry cannot be read."
                    ) from error
                if stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                    total += metadata.st_size
            if total <= 0:
                raise DockerCapacityError("Tracked build context has no byte evidence.")
            sizes[context] = total
    return sizes


def _builder_selection_failure(
    recorder: BuilderSelectionRecorder | None,
    predicate: BuilderSelectionPredicate,
    message: str,
    *,
    cause: BaseException | None = None,
) -> NoReturn:
    if recorder is not None:
        recorder.record(predicate)
    if cause is None:
        raise DockerCapacityError(message)
    raise DockerCapacityError(message) from cause


def _node_schema_failure(
    builder_selection_recorder: BuilderSelectionRecorder | None,
    node_schema_recorder: NodeSchemaRecorder | None,
    predicate: NodeSchemaPredicate,
) -> NoReturn:
    if node_schema_recorder is not None:
        node_schema_recorder.record(predicate)
    _builder_selection_failure(
        builder_selection_recorder,
        BuilderSelectionPredicate.NODE_SCHEMA,
        "Docker builder node evidence is invalid.",
    )


def parse_docker_builder_inventory(
    raw: str,
    environ: Mapping[str, str],
    *,
    current_context: str,
    builder_selection_recorder: BuilderSelectionRecorder | None = None,
    node_schema_recorder: NodeSchemaRecorder | None = None,
) -> DockerBuilderInventory:
    """Parse the canonical bounded Buildx listing without exposing provider values."""

    if environ.get("BUILDKIT_HOST", "").strip():
        _builder_selection_failure(
            builder_selection_recorder,
            BuilderSelectionPredicate.EXTERNAL_BUILDKIT_HOST,
            "EXTERNAL_BUILDKIT_HOST_UNSUPPORTED",
        )
    parsed_builders: list[tuple[str, tuple[bool, str, str, str, str]]] = []
    try:
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    except json.JSONDecodeError as error:
        _builder_selection_failure(
            builder_selection_recorder,
            BuilderSelectionPredicate.LIST_JSON,
            "Docker builder evidence is invalid.",
            cause=error,
        )
    for row in rows:
        if not isinstance(row, dict):
            _builder_selection_failure(
                builder_selection_recorder,
                BuilderSelectionPredicate.ROW_SCHEMA,
                "Docker builder evidence is invalid.",
            )
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
            _builder_selection_failure(
                builder_selection_recorder,
                BuilderSelectionPredicate.ROW_SCHEMA,
                "Docker builder evidence is invalid.",
            )
        if len(nodes) != 1:
            _builder_selection_failure(
                builder_selection_recorder,
                BuilderSelectionPredicate.NODE_COUNT,
                "DOCKER_BUILDER_MUST_HAVE_EXACTLY_ONE_NODE",
            )
        node_names: list[str] = []
        endpoints: list[str] = []
        status_values: list[str] = []
        for node in nodes:
            if not isinstance(node, dict):
                _node_schema_failure(
                    builder_selection_recorder,
                    node_schema_recorder,
                    NodeSchemaPredicate.NODE_NOT_MAPPING,
                )
            if "Name" not in node:
                _node_schema_failure(
                    builder_selection_recorder,
                    node_schema_recorder,
                    NodeSchemaPredicate.NAME_MISSING,
                )
            node_name = node["Name"]
            if node_name is None:
                _node_schema_failure(
                    builder_selection_recorder,
                    node_schema_recorder,
                    NodeSchemaPredicate.NAME_NULL,
                )
            if not isinstance(node_name, str):
                _node_schema_failure(
                    builder_selection_recorder,
                    node_schema_recorder,
                    NodeSchemaPredicate.NAME_NOT_STRING,
                )
            if "Endpoint" not in node:
                _node_schema_failure(
                    builder_selection_recorder,
                    node_schema_recorder,
                    NodeSchemaPredicate.ENDPOINT_MISSING,
                )
            endpoint = node["Endpoint"]
            if endpoint is None:
                _node_schema_failure(
                    builder_selection_recorder,
                    node_schema_recorder,
                    NodeSchemaPredicate.ENDPOINT_NULL,
                )
            if not isinstance(endpoint, str):
                _node_schema_failure(
                    builder_selection_recorder,
                    node_schema_recorder,
                    NodeSchemaPredicate.ENDPOINT_NOT_STRING,
                )
            status = node.get("Status", "")
            if status is None:
                _node_schema_failure(
                    builder_selection_recorder,
                    node_schema_recorder,
                    NodeSchemaPredicate.STATUS_NULL,
                )
            if not isinstance(status, str):
                _node_schema_failure(
                    builder_selection_recorder,
                    node_schema_recorder,
                    NodeSchemaPredicate.STATUS_NOT_STRING,
                )
            node_names.append(node_name)
            endpoints.append(endpoint)
            status_values.append(status)
        evidence = (current, driver, node_names[0], endpoints[0], status_values[0])
        parsed_builders.append((name, evidence))

    if node_schema_recorder is not None:
        node_schema_recorder.record(NodeSchemaPredicate.PASS)
    builders: dict[str, DockerBuilderIdentity] = {}
    for name, evidence in parsed_builders:
        identity = DockerBuilderIdentity(
            name=name,
            current=evidence[0],
            driver=evidence[1],
            node_name=evidence[2],
            endpoint=evidence[3],
            status=evidence[4],
        )
        if name in builders and builders[name] != identity:
            _builder_selection_failure(
                builder_selection_recorder,
                BuilderSelectionPredicate.DUPLICATE_CONFLICT,
                "Docker builder duplicate evidence conflicts.",
            )
        builders[name] = identity
    return DockerBuilderInventory(
        current_context=current_context,
        builders=tuple(builders.values()),
        row_count=len(parsed_builders),
    )


def _selected_builder(
    raw: str,
    environ: Mapping[str, str],
    *,
    current_context: str,
    builder_selection_recorder: BuilderSelectionRecorder | None = None,
    node_schema_recorder: NodeSchemaRecorder | None = None,
) -> str:
    inventory = parse_docker_builder_inventory(
        raw,
        environ,
        current_context=current_context,
        builder_selection_recorder=builder_selection_recorder,
        node_schema_recorder=node_schema_recorder,
    )
    builders = {builder.name: builder for builder in inventory.builders}

    current_names = sorted(name for name, evidence in builders.items() if evidence.current)
    if not current_names:
        _builder_selection_failure(
            builder_selection_recorder,
            BuilderSelectionPredicate.CURRENT_MISSING,
            "DOCKER_BUILDER_AMBIGUOUS",
        )
    if len(current_names) > 1:
        _builder_selection_failure(
            builder_selection_recorder,
            BuilderSelectionPredicate.CURRENT_AMBIGUOUS,
            "DOCKER_BUILDER_AMBIGUOUS",
        )
    selected = current_names[0]
    override = environ.get("BUILDX_BUILDER", "").strip()
    if override:
        if _BUILDER_NAME.fullmatch(override) is None or override not in builders:
            _builder_selection_failure(
                builder_selection_recorder,
                BuilderSelectionPredicate.OVERRIDE_INVALID,
                "DOCKER_BUILDER_OVERRIDE_INVALID",
            )
        if override != selected:
            _builder_selection_failure(
                builder_selection_recorder,
                BuilderSelectionPredicate.OVERRIDE_NOT_CURRENT,
                "DOCKER_BUILDER_OVERRIDE_NOT_CURRENT",
            )
    selected_builder = builders[selected]
    current = selected_builder.current
    driver = selected_builder.driver
    node_name = selected_builder.node_name
    endpoint = selected_builder.endpoint
    status = selected_builder.status
    if not current:
        _builder_selection_failure(
            builder_selection_recorder,
            BuilderSelectionPredicate.CURRENT_MISSING,
            "DOCKER_BUILDER_NOT_CURRENT",
        )
    if driver != "docker":
        _builder_selection_failure(
            builder_selection_recorder,
            BuilderSelectionPredicate.DRIVER_NOT_DOCKER,
            "DOCKER_BUILDER_NOT_LOCAL_RUNNING_DOCKER_DRIVER",
        )
    if status != "running":
        _builder_selection_failure(
            builder_selection_recorder,
            BuilderSelectionPredicate.NODE_NOT_RUNNING,
            "DOCKER_BUILDER_NOT_LOCAL_RUNNING_DOCKER_DRIVER",
        )
    if selected != current_context:
        _builder_selection_failure(
            builder_selection_recorder,
            BuilderSelectionPredicate.BUILDER_CONTEXT_MISMATCH,
            "DOCKER_BUILDER_NOT_LOCAL_RUNNING_DOCKER_DRIVER",
        )
    if node_name != selected:
        _builder_selection_failure(
            builder_selection_recorder,
            BuilderSelectionPredicate.NODE_NAME_MISMATCH,
            "DOCKER_BUILDER_NOT_LOCAL_RUNNING_DOCKER_DRIVER",
        )
    if endpoint != current_context:
        _builder_selection_failure(
            builder_selection_recorder,
            BuilderSelectionPredicate.ENDPOINT_CONTEXT_MISMATCH,
            "DOCKER_BUILDER_NOT_LOCAL_RUNNING_DOCKER_DRIVER",
        )
    if builder_selection_recorder is not None:
        builder_selection_recorder.record(BuilderSelectionPredicate.PASS)
    return selected


def require_docker_builder_selection_plan(
    raw: str,
    environ: Mapping[str, str],
    *,
    current_context: str,
    plan_recorder: DockerBuilderSelectionPlanRecorder | None = None,
    builder_selection_recorder: BuilderSelectionRecorder | None = None,
    node_schema_recorder: NodeSchemaRecorder | None = None,
    prior_driver_recorder: PriorDriverRecorder | None = None,
) -> DockerBuilderSelectionPlan:
    """Resolve one exact docker-container to context-docker selection transition."""

    def fail(
        predicate: DockerBuilderSelectionPlanPredicate,
        message: str,
    ) -> NoReturn:
        if plan_recorder is not None:
            plan_recorder.record(predicate)
        raise DockerCapacityError(message)

    if environ.get("BUILDKIT_HOST", "").strip() or environ.get("BUILDX_BUILDER", "").strip():
        fail(
            DockerBuilderSelectionPlanPredicate.CURRENT_SELECTION_CONTRACT,
            "DOCKER_BUILDER_SELECTION_ENVIRONMENT_OVERRIDE",
        )
    builder_selection = builder_selection_recorder or BuilderSelectionRecorder()
    node_schema = node_schema_recorder or NodeSchemaRecorder()
    prior_driver = prior_driver_recorder or PriorDriverRecorder()
    try:
        _selected_builder(
            raw,
            environ,
            current_context=current_context,
            builder_selection_recorder=builder_selection,
            node_schema_recorder=node_schema,
        )
    except DockerCapacityError:
        pass
    else:
        fail(
            DockerBuilderSelectionPlanPredicate.CURRENT_ALREADY_CANONICAL,
            "DOCKER_BUILDER_SELECTION_PRESTATE_INVALID",
        )

    try:
        inventory = parse_docker_builder_inventory(
            raw,
            environ,
            current_context=current_context,
        )
    except DockerCapacityError:
        fail(
            DockerBuilderSelectionPlanPredicate.CURRENT_SELECTION_CONTRACT,
            "DOCKER_BUILDER_SELECTION_PRESTATE_INVALID",
        )
    if inventory.row_count != len(inventory.builders):
        fail(
            DockerBuilderSelectionPlanPredicate.INVENTORY_DUPLICATE,
            "DOCKER_BUILDER_SELECTION_INVENTORY_DUPLICATE",
        )
    current_builders = tuple(builder for builder in inventory.builders if builder.current)
    if len(current_builders) != 1:
        fail(
            DockerBuilderSelectionPlanPredicate.CURRENT_COUNT,
            "DOCKER_BUILDER_SELECTION_PRESTATE_INVALID",
        )
    prior = current_builders[0]
    expected_driver_transition = (
        builder_selection.predicate is BuilderSelectionPredicate.DRIVER_NOT_DOCKER
        and node_schema.predicate is NodeSchemaPredicate.PASS
    )
    expected_stopped_prior = (
        builder_selection.predicate is BuilderSelectionPredicate.NODE_NOT_RUNNING
        and node_schema.predicate is NodeSchemaPredicate.PASS
        and prior.driver == "docker-container"
    )
    if not (expected_driver_transition or expected_stopped_prior):
        fail(
            DockerBuilderSelectionPlanPredicate.CURRENT_SELECTION_CONTRACT,
            "DOCKER_BUILDER_SELECTION_PRESTATE_INVALID",
        )
    if prior.driver == "docker-container":
        prior_driver.record(PriorDriverPredicate.PASS)
    elif prior.driver == "kubernetes":
        prior_driver.record(PriorDriverPredicate.KUBERNETES)
    elif prior.driver == "remote":
        prior_driver.record(PriorDriverPredicate.REMOTE)
    else:
        prior_driver.record(PriorDriverPredicate.UNRECOGNIZED)
    if prior_driver.predicate is not PriorDriverPredicate.PASS:
        fail(
            DockerBuilderSelectionPlanPredicate.PRIOR_DRIVER,
            "DOCKER_BUILDER_SELECTION_PRESTATE_INVALID",
        )
    if prior.status != "running":
        fail(
            DockerBuilderSelectionPlanPredicate.PRIOR_STATUS,
            "DOCKER_BUILDER_SELECTION_PRESTATE_INVALID",
        )
    targets = tuple(builder for builder in inventory.builders if builder.name == current_context)
    if len(targets) != 1:
        fail(
            DockerBuilderSelectionPlanPredicate.TARGET_MISSING,
            "DOCKER_BUILDER_SELECTION_TARGET_INVALID",
        )
    target = targets[0]
    if target.driver != "docker":
        fail(
            DockerBuilderSelectionPlanPredicate.TARGET_DRIVER,
            "DOCKER_BUILDER_SELECTION_TARGET_INVALID",
        )
    if target.status != "running":
        fail(
            DockerBuilderSelectionPlanPredicate.TARGET_STATUS,
            "DOCKER_BUILDER_SELECTION_TARGET_INVALID",
        )
    if target.node_name != current_context:
        fail(
            DockerBuilderSelectionPlanPredicate.TARGET_NODE_NAME,
            "DOCKER_BUILDER_SELECTION_TARGET_INVALID",
        )
    if target.endpoint != current_context:
        fail(
            DockerBuilderSelectionPlanPredicate.TARGET_ENDPOINT,
            "DOCKER_BUILDER_SELECTION_TARGET_INVALID",
        )
    if target.current:
        fail(
            DockerBuilderSelectionPlanPredicate.TARGET_CURRENT,
            "DOCKER_BUILDER_SELECTION_TARGET_INVALID",
        )
    plan = DockerBuilderSelectionPlan(
        inventory=inventory,
        prior_builder=prior.name,
        target_builder=target.name,
    )
    if plan_recorder is not None:
        plan_recorder.record(DockerBuilderSelectionPlanPredicate.PASS)
    return plan


def docker_builder_selection_residual_count(
    expected: DockerBuilderInventory,
    observed: DockerBuilderInventory,
    *,
    selected_builder: str,
) -> int:
    """Count bounded inventory differences from one exact approved selection state."""

    if _BUILDER_NAME.fullmatch(selected_builder) is None:
        raise DockerCapacityError("DOCKER_BUILDER_SELECTION_POSTSTATE_INVALID")
    expected_rows = {
        (*builder.stable_identity, builder.name == selected_builder)
        for builder in expected.builders
    }
    observed_rows = {(*builder.stable_identity, builder.current) for builder in observed.builders}
    return len(expected_rows.symmetric_difference(observed_rows))


def require_docker_builder_selection_poststate(
    plan: DockerBuilderSelectionPlan,
    raw: str,
    environ: Mapping[str, str],
    *,
    selected_builder: str,
) -> DockerBuilderInventory:
    """Require the complete inventory to differ only by exact Current flags."""

    if selected_builder not in {plan.prior_builder, plan.target_builder}:
        raise DockerCapacityError("DOCKER_BUILDER_SELECTION_POSTSTATE_INVALID")
    inventory = parse_docker_builder_inventory(
        raw,
        environ,
        current_context=plan.inventory.current_context,
    )
    if (
        inventory.row_count != len(inventory.builders)
        or inventory.stable_identity != plan.inventory.stable_identity
        or docker_builder_selection_residual_count(
            plan.inventory,
            inventory,
            selected_builder=selected_builder,
        )
        != 0
    ):
        raise DockerCapacityError("DOCKER_BUILDER_SELECTION_POSTSTATE_INVALID")
    if selected_builder == plan.target_builder:
        recorder = BuilderSelectionRecorder()
        node_recorder = NodeSchemaRecorder()
        selected = _selected_builder(
            raw,
            environ,
            current_context=plan.inventory.current_context,
            builder_selection_recorder=recorder,
            node_schema_recorder=node_recorder,
        )
        if not (
            selected == plan.target_builder
            and recorder.predicate is BuilderSelectionPredicate.PASS
            and node_recorder.predicate is NodeSchemaPredicate.PASS
        ):
            raise DockerCapacityError("DOCKER_BUILDER_SELECTION_POSTSTATE_INVALID")
    return inventory


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


def _cache_bytes(raw: str) -> BuildCacheUsage:
    records: dict[str, tuple[int, bool, bool]] = {}
    try:
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    except json.JSONDecodeError as error:
        raise DockerCapacityError("Docker build-cache evidence is invalid.") from error
    for row in rows:
        if not isinstance(row, dict):
            raise DockerCapacityError("Docker build-cache evidence is invalid.")
        identifier = row.get("ID")
        reclaimable = row.get("Reclaimable")
        shared = row.get("Shared")
        if (
            not isinstance(identifier, str)
            or not identifier
            or not isinstance(reclaimable, bool)
            or not isinstance(shared, bool)
        ):
            raise DockerCapacityError("Docker build-cache evidence is invalid.")
        evidence = (_parse_size(row.get("Size")), reclaimable, shared)
        if identifier in records and records[identifier] != evidence:
            raise DockerCapacityError("Docker build-cache duplicate evidence conflicts.")
        records[identifier] = evidence
    logical_bytes = sum(size for size, _reclaimable, _shared in records.values())
    reclaimable_logical_bytes = sum(
        size for size, reclaimable, _shared in records.values() if reclaimable
    )
    private = tuple(evidence for evidence in records.values() if not evidence[2])
    shared_records = tuple(evidence for evidence in records.values() if evidence[2])
    usage = BuildCacheUsage(
        record_count=len(records),
        logical_bytes=logical_bytes,
        reclaimable_record_count=sum(
            1 for _size, reclaimable, _shared in records.values() if reclaimable
        ),
        reclaimable_logical_bytes=reclaimable_logical_bytes,
        private_record_count=len(private),
        private_bytes=sum(size for size, _reclaimable, _shared in private),
        reclaimable_private_record_count=sum(
            1 for _size, reclaimable, _shared in private if reclaimable
        ),
        reclaimable_private_bytes=sum(
            size for size, reclaimable, _shared in private if reclaimable
        ),
        shared_record_count=len(shared_records),
        shared_bytes=sum(size for size, _reclaimable, _shared in shared_records),
        reclaimable_shared_record_count=sum(
            1 for _size, reclaimable, _shared in shared_records if reclaimable
        ),
        reclaimable_shared_bytes=sum(
            size for size, reclaimable, _shared in shared_records if reclaimable
        ),
    )
    return usage


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
) -> BuildCacheUsage:
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


def require_local_unix_docker_context(
    executor: CapacityExecutor,
    environ: Mapping[str, str],
) -> str:
    """Expose the canonical local-context proof to fixed governed operators."""

    return _require_local_unix_docker_context(executor, environ)


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


def docker_builder_is_idle(
    *,
    builder: str,
    lock: DockerWorkflowLock,
    executor: CapacityExecutor | None = None,
) -> bool:
    """Return one validated active-build state without exposing history rows."""

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
    return not statuses


def require_no_active_builds(
    *,
    builder: str,
    lock: DockerWorkflowLock,
    executor: CapacityExecutor | None = None,
    phase_recorder: DockerCapacityPhaseRecorder | None = None,
    probe_predicate: BuildCapacityPreflightPredicate = (
        BuildCapacityPreflightPredicate.CAPACITY_CACHE_ACTIVE_BUILD
    ),
    active_predicate: BuildCapacityPreflightPredicate = (
        BuildCapacityPreflightPredicate.CAPACITY_CACHE_ACTIVE_BUILD
    ),
) -> None:
    """Fail closed unless the selected builder has no running build records."""

    with _capacity_phase(phase_recorder, probe_predicate):
        idle = docker_builder_is_idle(
            builder=builder,
            lock=lock,
            executor=executor,
        )
    if not idle:
        with _capacity_phase(phase_recorder, active_predicate):
            raise DockerCapacityError("DOCKER_ACTIVE_BUILD_PRESENT")


def _cli_megabytes(value: int) -> str:
    return f"{max(1, (value + 999_999) // 1_000_000)}mb"


def _post_action_error(
    *,
    classification: str,
    builder: str,
    action_succeeded: bool,
    cache_before: BuildCacheUsage,
    free_bytes_before: int,
    filesystem_total_bytes_before: int,
    cache_after: BuildCacheUsage | None,
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
    before_values = (free_bytes_before, filesystem_total_bytes_before)
    if any(value < 0 for value in before_values) or filesystem_total_bytes_before <= 0:
        return DockerCapacityError("DOCKER_BUILD_CACHE_POST_ACTION_EVIDENCE_INVALID")
    fields = [
        f"classification={classification}",
        f"builder={builder}",
        f"action_succeeded={'true' if action_succeeded else 'false'}",
        f"filesystem_total_before={filesystem_total_bytes_before}",
        *_cache_usage_fields(cache_before, suffix="before"),
        f"free_before={free_bytes_before}",
        "action_attempts=1",
        "retry_count=0",
        f"cache_probe_ok={'true' if cache_after is not None else 'false'}",
        f"filesystem_probe_ok={'true' if filesystem_after is not None else 'false'}",
    ]
    if cache_after is not None:
        logical_delta = cache_after.logical_bytes - cache_before.logical_bytes
        private_delta = cache_after.private_bytes - cache_before.private_bytes
        shared_delta = cache_after.shared_bytes - cache_before.shared_bytes
        fields.extend(
            (
                *_cache_usage_fields(cache_after, suffix="after"),
                f"logical_cache_delta_signed={logical_delta}",
                f"private_cache_delta_signed={private_delta}",
                f"shared_cache_delta_signed={shared_delta}",
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
    mode: DockerCapacityMode = DockerCapacityMode.ACTION_ENABLED,
    phase_recorder: DockerCapacityPhaseRecorder | None = None,
    builder_selection_recorder: BuilderSelectionRecorder | None = None,
    node_schema_recorder: NodeSchemaRecorder | None = None,
) -> DockerCapacityEvidence:
    """Prove selected builds fit before any Docker runtime mutation."""

    if not isinstance(mode, DockerCapacityMode):
        raise DockerCapacityError("DOCKER_BUILD_CAPACITY_MODE_INVALID")
    with _capacity_phase(
        phase_recorder,
        BuildCapacityPreflightPredicate.COMPOSE_ARGUMENTS,
    ):
        selected = tuple(dict.fromkeys(selected_build_services))
        if not selected:
            raise DockerCapacityError("No selected build services were supplied.")
    with _capacity_phase(
        phase_recorder,
        BuildCapacityPreflightPredicate.LOCK_CONTRACT,
    ):
        lock.require_held()
    resolved_root = root.resolve()
    with _capacity_phase(
        phase_recorder,
        BuildCapacityPreflightPredicate.DOCKERIGNORE_CONTRACT,
    ):
        _require_dockerignore_contract(resolved_root)
    command_executor = executor or SubprocessCapacityExecutor()
    with _capacity_phase(
        phase_recorder,
        BuildCapacityPreflightPredicate.COMPOSE_CONFIG,
    ):
        raw_config = _safe_output(
            command_executor,
            compose_config_command,
            classification=COMPOSE_BUILD_CONFIG_PROBE,
            timeout_seconds=30,
        )
    with _capacity_phase(
        phase_recorder,
        BuildCapacityPreflightPredicate.BUILD_TARGET_CONTRACT,
    ):
        targets = _resolve_build_targets(
            raw_config,
            root=resolved_root,
            selected_services=selected,
        )
    context_sizes = _tracked_context_bytes(
        command_executor,
        root=resolved_root,
        contexts=tuple(target.context for target in targets.values()),
        phase_recorder=phase_recorder,
    )
    total_context_bytes = sum(context_sizes[target.context] for target in targets.values())

    with _capacity_phase(
        phase_recorder,
        BuildCapacityPreflightPredicate.DOCKER_CONTEXT,
    ):
        current_context = _require_local_unix_docker_context(command_executor, environ)
    with _capacity_phase(
        phase_recorder,
        BuildCapacityPreflightPredicate.BUILDER_LIST_PROBE,
    ):
        raw_builder_list = _safe_output(
            command_executor,
            ("docker", "buildx", "ls", "--format", "{{json .}}"),
            classification=DOCKER_BUILDER_LIST_PROBE,
            timeout_seconds=20,
        )
    with _capacity_phase(
        phase_recorder,
        BuildCapacityPreflightPredicate.BUILDER_SELECTION,
    ):
        builder = _selected_builder(
            raw_builder_list,
            environ,
            current_context=current_context,
            builder_selection_recorder=builder_selection_recorder,
            node_schema_recorder=node_schema_recorder,
        )
    with _capacity_phase(
        phase_recorder,
        BuildCapacityPreflightPredicate.DOCKER_PLATFORM,
    ):
        platform = _docker_platform(command_executor)
    with _capacity_phase(
        phase_recorder,
        BuildCapacityPreflightPredicate.IMAGE_EVIDENCE,
    ):
        total_image_bytes, image_sizes = _image_bytes(
            command_executor,
            targets,
            expected_platform=platform,
        )
    with _capacity_phase(
        phase_recorder,
        BuildCapacityPreflightPredicate.CACHE_EVIDENCE,
    ):
        cache_before = _probe_cache(command_executor, builder)
    with _capacity_phase(
        phase_recorder,
        BuildCapacityPreflightPredicate.FILESYSTEM_EVIDENCE,
    ):
        filesystem_total, free_before = _probe_filesystem(
            command_executor,
            docker_filesystem_probe_command,
        )

    with _capacity_phase(
        phase_recorder,
        BuildCapacityPreflightPredicate.CAPACITY_POLICY,
    ):
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
    free_after = free_before

    if cache_before.private_bytes > cache_budget:
        with _capacity_phase(
            phase_recorder,
            BuildCapacityPreflightPredicate.CAPACITY_POLICY,
        ):
            required_cache_recovery = cache_before.private_bytes - cache_budget
            if cache_before.reclaimable_private_bytes < required_cache_recovery:
                raise DockerCapacityError("BUILDKIT_CACHE_RECLAIMABLE_INSUFFICIENT")
            recoverable_while_retaining_floor = min(
                cache_before.reclaimable_private_bytes,
                max(0, cache_before.private_bytes - cache_reserved),
            )
            if free_before + recoverable_while_retaining_floor < required:
                raise DockerCapacityError("DOCKER_CAPACITY_INSUFFICIENT_FOR_CACHE_ACTION")
        with _capacity_phase(
            phase_recorder,
            BuildCapacityPreflightPredicate.CAPACITY_CACHE_POLICY_SUPPORT,
        ):
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
            phase_recorder=phase_recorder,
            probe_predicate=BuildCapacityPreflightPredicate.CAPACITY_CACHE_ACTIVE_BUILD,
            active_predicate=BuildCapacityPreflightPredicate.CAPACITY_CACHE_ACTIVE_BUILD,
        )
        if mode is DockerCapacityMode.MEASURE_ONLY:
            if phase_recorder is not None:
                phase_recorder.mark(BuildCapacityPreflightPredicate.CACHE_ACTION_REQUIRED)
            raise DockerCapacityMeasureOnlyStop()
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

        cache_measurement_after: BuildCacheUsage | None = None
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
                cache_before=cache_before,
                free_bytes_before=free_before,
                filesystem_total_bytes_before=filesystem_total,
                cache_after=cache_measurement_after,
                filesystem_after=filesystem_measurement_after,
            )
        cache_after = cache_measurement_after
        filesystem_total_after, free_after = filesystem_measurement_after
        if not action_succeeded:
            raise _post_action_error(
                classification=DOCKER_BUILD_CACHE_ACTION_FAILED_POST_MEASUREMENT_OK,
                builder=builder,
                action_succeeded=False,
                cache_before=cache_before,
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
                cache_before=cache_before,
                free_bytes_before=free_before,
                filesystem_total_bytes_before=filesystem_total,
                cache_after=cache_measurement_after,
                filesystem_after=filesystem_measurement_after,
            )
        if cache_after.private_bytes > cache_budget:
            raise _post_action_error(
                classification="BUILDKIT_CACHE_BUDGET_NOT_RESTORED",
                builder=builder,
                action_succeeded=True,
                cache_before=cache_before,
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
                cache_before=cache_before,
                free_bytes_before=free_before,
                filesystem_total_bytes_before=filesystem_total,
                cache_after=cache_measurement_after,
                filesystem_after=filesystem_measurement_after,
            )
        cache_action = "bounded-prune-all"

    with _capacity_phase(
        phase_recorder,
        BuildCapacityPreflightPredicate.CAPACITY_POLICY,
    ):
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
        cache_before=cache_before,
        cache_after=cache_after,
        cache_action=cache_action,
    )
