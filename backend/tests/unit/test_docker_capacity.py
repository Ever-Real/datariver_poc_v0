from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "scripts" / "docker_capacity.py"


def _load_module() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "docker_capacity_for_test",
        MODULE_PATH,
    )
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


capacity = _load_module()


class FakeExecutor:
    def __init__(self, outputs: dict[str, list[str | BaseException]]) -> None:
        self.outputs = outputs
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def output(
        self,
        arguments: tuple[str, ...],
        *,
        classification: str,
        timeout_seconds: int,
    ) -> str:
        del timeout_seconds
        self.calls.append((classification, arguments))
        responses = self.outputs.get(classification)
        if not responses:
            raise AssertionError(f"Unexpected command classification: {classification}")
        response = responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _builder_lines() -> str:
    row = {
        "Current": True,
        "Driver": "docker",
        "Name": "desktop-linux",
        "Nodes": [
            {
                "Endpoint": "desktop-linux",
                "Name": "desktop-linux",
                "Status": "running",
            }
        ],
    }
    return "\n".join((json.dumps(row), json.dumps(row)))


def _cache_line(
    size: str,
    *,
    identifier: str = "cache-1",
    reclaimable: bool = True,
    shared: bool = False,
) -> str:
    return json.dumps(
        {
            "ID": identifier,
            "Reclaimable": reclaimable,
            "Shared": shared,
            "Size": size,
        }
    )


def _cache_help() -> str:
    return "--all --builder --force --max-used-space --min-free-space --reserved-space"


def _compose_config(root: Path) -> str:
    return json.dumps(
        {
            "name": "datariver-next",
            "services": {
                "api": {
                    "build": {
                        "context": str(root),
                        "dockerfile": "backend/Dockerfile",
                    },
                    "image": None,
                },
                "migrate": {
                    "build": {
                        "context": str(root),
                        "dockerfile": "backend/Dockerfile",
                    },
                    "image": None,
                },
            },
        }
    )


def _prepare_context(root: Path) -> int:
    dockerfile = root / "backend" / "Dockerfile"
    source = root / "backend" / "app.py"
    dockerfile.parent.mkdir(parents=True)
    dockerfile.write_bytes(b"FROM scratch\n")
    source.write_bytes(b"x" * 1_000)
    (root / ".dockerignore").write_text(
        "\n".join(
            (
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
            )
        )
        + "\n",
        encoding="utf-8",
    )
    return dockerfile.stat().st_size + source.stat().st_size


def _base_outputs(root: Path) -> dict[str, list[str | BaseException]]:
    return {
        capacity.COMPOSE_BUILD_CONFIG_PROBE: [_compose_config(root)],
        capacity.GIT_CLEAN_CHECKOUT_PROBE: [""],
        capacity.DOCKER_CONTEXT_PROBE: [
            json.dumps("desktop-linux") + "|" + json.dumps("unix:///private/docker.sock")
        ],
        capacity.DOCKER_BUILDER_LIST_PROBE: [_builder_lines()],
        capacity.DOCKER_PLATFORM_PROBE: ["linux/arm64\n"],
        capacity.DOCKER_ACTIVE_BUILD_PROBE: [""],
        capacity.DOCKER_BUILD_CACHE_PROBE: [_cache_line("10MB")],
        capacity.DOCKER_BACKING_FILESYSTEM_PROBE: [
            "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
            "overlay 1000000 400000 600000 40% /\n"
        ],
        capacity.GIT_BUILD_CONTEXT_PROBE: ["backend/Dockerfile\0backend/app.py\0"],
        capacity.DOCKER_IMAGE_SIZE_PROBE: [
            ("sha256:" + ("a" * 64) + "\t10000000\tlinux\tarm64\n") * 2
        ],
    }


def _run(
    root: Path,
    executor: FakeExecutor,
    *,
    environ: dict[str, str] | None = None,
    mode: Any = None,
    phase_recorder: Any = None,
) -> Any:
    with capacity.exclusive_docker_workflow_lock(root) as lock:
        kwargs: dict[str, Any] = {}
        if mode is not None:
            kwargs["mode"] = mode
        if phase_recorder is not None:
            kwargs["phase_recorder"] = phase_recorder
        return capacity.governed_compose_build_capacity(
            root=root,
            compose_config_command=("compose", "config", "--format", "json"),
            docker_filesystem_probe_command=("compose", "exec", "postgres", "df"),
            selected_build_services=("api", "migrate"),
            environ=environ or {},
            executor=executor,
            lock=lock,
            **kwargs,
        )


def _error_fields(error: Exception) -> dict[str, str]:
    rendered = str(error)
    assert "\n" not in rendered
    fields: dict[str, str] = {}
    for token in rendered.split():
        key, separator, value = token.partition("=")
        assert separator == "="
        assert key not in fields
        fields[key] = value
    return fields


def _assert_private_only_cache_fields(
    fields: dict[str, str],
    *,
    suffix: str,
    size: int,
) -> None:
    assert fields[f"logical_cache_records_{suffix}"] == "1"
    assert fields[f"logical_cache_bytes_{suffix}"] == str(size)
    assert fields[f"reclaimable_logical_cache_records_{suffix}"] == "1"
    assert fields[f"reclaimable_logical_cache_bytes_{suffix}"] == str(size)
    assert fields[f"private_cache_records_{suffix}"] == "1"
    assert fields[f"private_cache_bytes_{suffix}"] == str(size)
    assert fields[f"reclaimable_private_cache_records_{suffix}"] == "1"
    assert fields[f"reclaimable_private_cache_bytes_{suffix}"] == str(size)
    assert fields[f"shared_cache_records_{suffix}"] == "0"
    assert fields[f"shared_cache_bytes_{suffix}"] == "0"
    assert fields[f"reclaimable_shared_cache_records_{suffix}"] == "0"
    assert fields[f"reclaimable_shared_cache_bytes_{suffix}"] == "0"


def test_selected_services_are_deduplicated_by_build_fingerprint(tmp_path: Path) -> None:
    context_bytes = _prepare_context(tmp_path)
    executor = FakeExecutor(_base_outputs(tmp_path))

    evidence = _run(tmp_path, executor)

    assert evidence.builder == "desktop-linux"
    assert evidence.selected_services == 2
    assert evidence.selected_image_tags == 2
    assert evidence.unique_builds == 1
    assert evidence.context_bytes == context_bytes
    assert evidence.image_bytes == 10_000_000
    assert evidence.build_peak_bytes == 20_000_000 + context_bytes
    assert evidence.reserve_bytes == 102_400_000
    assert evidence.required_free_bytes == evidence.build_peak_bytes + evidence.reserve_bytes
    assert evidence.cache_budget_bytes == 128_000_000
    assert evidence.cache_action == "none"
    assert evidence.free_bytes_before == evidence.free_bytes_after
    assert not any(call[0] == capacity.DOCKER_BUILD_CACHE_ACTION for call in executor.calls)


def test_build_capacity_preflight_predicates_are_closed_and_ordered() -> None:
    assert tuple(member.value for member in capacity.BuildCapacityPreflightPredicate) == (
        "HOST_ENVIRONMENT_PREFLIGHT",
        "SOURCE_PROVENANCE",
        "COMPOSE_ARGUMENTS",
        "LOCK_CONTRACT",
        "CLEAN_CHECKOUT",
        "DOCKERIGNORE_CONTRACT",
        "COMPOSE_CONFIG",
        "BUILD_TARGET_CONTRACT",
        "TRACKED_CONTEXT",
        "DOCKER_CONTEXT",
        "BUILDER_LIST_PROBE",
        "BUILDER_SELECTION",
        "DOCKER_PLATFORM",
        "IMAGE_EVIDENCE",
        "CACHE_EVIDENCE",
        "FILESYSTEM_EVIDENCE",
        "CAPACITY_POLICY",
        "CAPACITY_CACHE_POLICY_SUPPORT",
        "CAPACITY_CACHE_ACTIVE_BUILD",
        "CACHE_ACTION_REQUIRED",
        "INITIAL_BUILDER_IDLE_PROBE",
        "INITIAL_BUILDER_ACTIVE",
        "PASS",
        "UNKNOWN",
    )


def test_measure_only_over_budget_reports_action_required_without_prune(
    tmp_path: Path,
) -> None:
    _prepare_context(tmp_path)
    outputs = _base_outputs(tmp_path)
    outputs[capacity.DOCKER_BUILD_CACHE_PROBE] = [_cache_line("140MB")]
    outputs[capacity.DOCKER_BUILD_CACHE_HELP_PROBE] = [_cache_help()]
    outputs[capacity.DOCKER_ACTIVE_BUILD_PROBE] = [""]
    executor = FakeExecutor(outputs)
    recorder = capacity.DockerCapacityPhaseRecorder()

    with pytest.raises(capacity.DockerCapacityMeasureOnlyStop) as captured:
        _run(
            tmp_path,
            executor,
            mode=capacity.DockerCapacityMode.MEASURE_ONLY,
            phase_recorder=recorder,
        )

    assert (
        captured.value.predicate is capacity.BuildCapacityPreflightPredicate.CACHE_ACTION_REQUIRED
    )
    assert recorder.predicate is capacity.BuildCapacityPreflightPredicate.CACHE_ACTION_REQUIRED
    assert not any(call[0] == capacity.DOCKER_BUILD_CACHE_ACTION for call in executor.calls)


@pytest.mark.parametrize(
    ("failed_classification", "expected_predicate"),
    (
        (capacity.COMPOSE_BUILD_CONFIG_PROBE, "COMPOSE_CONFIG"),
        (capacity.GIT_CLEAN_CHECKOUT_PROBE, "CLEAN_CHECKOUT"),
        (capacity.DOCKER_CONTEXT_PROBE, "DOCKER_CONTEXT"),
        (capacity.DOCKER_BUILDER_LIST_PROBE, "BUILDER_LIST_PROBE"),
        (capacity.DOCKER_PLATFORM_PROBE, "DOCKER_PLATFORM"),
        (capacity.DOCKER_IMAGE_SIZE_PROBE, "IMAGE_EVIDENCE"),
        (capacity.DOCKER_BUILD_CACHE_PROBE, "CACHE_EVIDENCE"),
        (capacity.DOCKER_BACKING_FILESYSTEM_PROBE, "FILESYSTEM_EVIDENCE"),
    ),
)
def test_capacity_probe_failures_carry_structural_phase_without_raw_payload(
    failed_classification: str,
    expected_predicate: str,
    tmp_path: Path,
) -> None:
    _prepare_context(tmp_path)
    outputs = _base_outputs(tmp_path)
    outputs[failed_classification] = [RuntimeError("raw-capacity-secret-sentinel")]
    recorder = capacity.DockerCapacityPhaseRecorder()

    with pytest.raises(capacity.DockerCapacityPhaseError) as captured:
        _run(tmp_path, FakeExecutor(outputs), phase_recorder=recorder)

    predicate = capacity.BuildCapacityPreflightPredicate(expected_predicate)
    assert captured.value.predicate is predicate
    assert recorder.predicate is predicate
    assert "raw-capacity-secret-sentinel" not in str(captured.value)


def test_measure_only_under_budget_preserves_normal_no_action_evidence(
    tmp_path: Path,
) -> None:
    _prepare_context(tmp_path)
    executor = FakeExecutor(_base_outputs(tmp_path))
    recorder = capacity.DockerCapacityPhaseRecorder()

    evidence = _run(
        tmp_path,
        executor,
        mode=capacity.DockerCapacityMode.MEASURE_ONLY,
        phase_recorder=recorder,
    )

    assert evidence.cache_action == "none"
    assert recorder.predicate is capacity.BuildCapacityPreflightPredicate.CAPACITY_POLICY
    assert not any(call[0] == capacity.DOCKER_BUILD_CACHE_ACTION for call in executor.calls)


@pytest.mark.parametrize(
    ("case", "expected"),
    (
        ("dockerignore", "DOCKERIGNORE_CONTRACT"),
        ("target", "BUILD_TARGET_CONTRACT"),
        ("tracked", "TRACKED_CONTEXT"),
        ("builder", "BUILDER_SELECTION"),
        ("policy", "CAPACITY_POLICY"),
    ),
)
def test_structural_phases_cover_local_contract_and_policy_failures(
    case: str,
    expected: str,
    tmp_path: Path,
) -> None:
    outputs = _base_outputs(tmp_path)
    if case != "dockerignore":
        _prepare_context(tmp_path)
    if case == "target":
        outputs[capacity.COMPOSE_BUILD_CONFIG_PROBE] = ["{}"]
    elif case == "tracked":
        outputs[capacity.GIT_BUILD_CONTEXT_PROBE] = [""]
    elif case == "builder":
        outputs[capacity.DOCKER_BUILDER_LIST_PROBE] = ["{}"]
    elif case == "policy":
        outputs[capacity.DOCKER_IMAGE_SIZE_PROBE] = [
            ("sha256:" + ("a" * 64) + "\t600000000\tlinux\tarm64\n") * 2
        ]
    recorder = capacity.DockerCapacityPhaseRecorder()

    with pytest.raises(capacity.DockerCapacityPhaseError) as captured:
        _run(tmp_path, FakeExecutor(outputs), phase_recorder=recorder)

    predicate = capacity.BuildCapacityPreflightPredicate(expected)
    assert captured.value.predicate is predicate
    assert recorder.predicate is predicate


@pytest.mark.parametrize(
    ("help_output", "active_output", "expected"),
    (
        (
            "--all --builder --force",
            "",
            "CAPACITY_CACHE_POLICY_SUPPORT",
        ),
        (
            _cache_help(),
            "running\n",
            "CAPACITY_CACHE_ACTIVE_BUILD",
        ),
    ),
)
def test_measure_only_cache_policy_and_active_build_fail_before_action(
    help_output: str,
    active_output: str,
    expected: str,
    tmp_path: Path,
) -> None:
    _prepare_context(tmp_path)
    outputs = _base_outputs(tmp_path)
    outputs[capacity.DOCKER_BUILD_CACHE_PROBE] = [_cache_line("140MB")]
    outputs[capacity.DOCKER_BUILD_CACHE_HELP_PROBE] = [help_output]
    outputs[capacity.DOCKER_ACTIVE_BUILD_PROBE] = [active_output]
    executor = FakeExecutor(outputs)
    recorder = capacity.DockerCapacityPhaseRecorder()

    with pytest.raises(capacity.DockerCapacityPhaseError) as captured:
        _run(
            tmp_path,
            executor,
            mode=capacity.DockerCapacityMode.MEASURE_ONLY,
            phase_recorder=recorder,
        )

    predicate = capacity.BuildCapacityPreflightPredicate(expected)
    assert captured.value.predicate is predicate
    assert recorder.predicate is predicate
    assert not any(call[0] == capacity.DOCKER_BUILD_CACHE_ACTION for call in executor.calls)


@pytest.mark.parametrize(
    ("active_output", "expected"),
    (
        (RuntimeError("raw-idle-probe-sentinel"), "INITIAL_BUILDER_IDLE_PROBE"),
        ("running\n", "INITIAL_BUILDER_ACTIVE"),
    ),
)
def test_initial_builder_idle_uses_distinct_structured_predicates(
    active_output: str | BaseException,
    expected: str,
    tmp_path: Path,
) -> None:
    with capacity.exclusive_docker_workflow_lock(tmp_path) as lock:
        recorder = capacity.DockerCapacityPhaseRecorder()
        executor = FakeExecutor({capacity.DOCKER_ACTIVE_BUILD_PROBE: [active_output]})
        with pytest.raises(capacity.DockerCapacityPhaseError) as captured:
            capacity.require_no_active_builds(
                builder="desktop-linux",
                lock=lock,
                executor=executor,
                phase_recorder=recorder,
                probe_predicate=(
                    capacity.BuildCapacityPreflightPredicate.INITIAL_BUILDER_IDLE_PROBE
                ),
                active_predicate=capacity.BuildCapacityPreflightPredicate.INITIAL_BUILDER_ACTIVE,
            )

    predicate = capacity.BuildCapacityPreflightPredicate(expected)
    assert captured.value.predicate is predicate
    assert recorder.predicate is predicate
    assert "raw-idle-probe-sentinel" not in str(captured.value)


@pytest.mark.parametrize(
    "failed_classification",
    (
        capacity.COMPOSE_BUILD_CONFIG_PROBE,
        capacity.GIT_CLEAN_CHECKOUT_PROBE,
        capacity.GIT_BUILD_CONTEXT_PROBE,
        capacity.DOCKER_CONTEXT_PROBE,
        capacity.DOCKER_BUILDER_LIST_PROBE,
        capacity.DOCKER_PLATFORM_PROBE,
        capacity.DOCKER_IMAGE_SIZE_PROBE,
        capacity.DOCKER_BUILD_CACHE_PROBE,
        capacity.DOCKER_BACKING_FILESYSTEM_PROBE,
    ),
)
def test_capacity_interrupts_are_not_falsely_classified_as_provider_failures(
    failed_classification: str,
    tmp_path: Path,
) -> None:
    _prepare_context(tmp_path)
    outputs = _base_outputs(tmp_path)
    outputs[failed_classification] = [KeyboardInterrupt("raw-capacity-interrupt-sentinel")]
    recorder = capacity.DockerCapacityPhaseRecorder()

    with pytest.raises(KeyboardInterrupt, match="raw-capacity-interrupt-sentinel"):
        _run(tmp_path, FakeExecutor(outputs), phase_recorder=recorder)


def test_insufficient_backing_filesystem_fails_without_cache_action(tmp_path: Path) -> None:
    _prepare_context(tmp_path)
    outputs = _base_outputs(tmp_path)
    outputs[capacity.DOCKER_BACKING_FILESYSTEM_PROBE] = [
        "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
        "overlay 1000000 999000 1000 99% /\n"
    ]
    executor = FakeExecutor(outputs)

    with pytest.raises(
        capacity.DockerCapacityError,
        match="DOCKER_CAPACITY_INSUFFICIENT",
    ):
        _run(tmp_path, executor)

    assert not any(call[0] == capacity.DOCKER_BUILD_CACHE_ACTION for call in executor.calls)


def test_backing_filesystem_probe_failure_is_sanitized(tmp_path: Path) -> None:
    _prepare_context(tmp_path)
    outputs = _base_outputs(tmp_path)
    outputs[capacity.DOCKER_BACKING_FILESYSTEM_PROBE] = [
        RuntimeError("credential=must-not-leak /private/operator.env")
    ]

    with pytest.raises(capacity.DockerCapacityError) as captured:
        _run(tmp_path, FakeExecutor(outputs))

    assert capacity.DOCKER_BACKING_FILESYSTEM_PROBE in str(captured.value)
    assert "must-not-leak" not in str(captured.value)
    assert "/private/operator.env" not in str(captured.value)


def test_cache_over_budget_runs_one_bounded_action_and_remeasures(tmp_path: Path) -> None:
    _prepare_context(tmp_path)
    outputs = _base_outputs(tmp_path)
    outputs[capacity.DOCKER_BUILD_CACHE_PROBE] = [
        _cache_line("140MB"),
        _cache_line("20MB"),
    ]
    outputs[capacity.DOCKER_BACKING_FILESYSTEM_PROBE] = [
        "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
        "overlay 1000000 800000 200000 80% /\n",
        "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
        "overlay 1000000 650000 350000 65% /\n",
    ]
    outputs[capacity.DOCKER_BUILD_CACHE_HELP_PROBE] = [_cache_help()]
    outputs[capacity.DOCKER_BUILD_CACHE_ACTION] = [""]
    executor = FakeExecutor(outputs)

    evidence = _run(tmp_path, executor)

    actions = [args for kind, args in executor.calls if kind == capacity.DOCKER_BUILD_CACHE_ACTION]
    assert len(actions) == 1
    assert "--all" in actions[0]
    assert "-a" not in actions[0]
    assert actions[0][:5] == (
        "docker",
        "buildx",
        "prune",
        "--builder",
        "desktop-linux",
    )
    assert actions[0] == (
        "docker",
        "buildx",
        "prune",
        "--builder",
        "desktop-linux",
        "--all",
        "--force",
        "--reserved-space",
        "64mb",
        "--max-used-space",
        "128mb",
        "--min-free-space",
        "123mb",
    )
    assert evidence.cache_action == "bounded-prune-all"
    assert evidence.cache_before.private_bytes == 140_000_000
    assert evidence.cache_after.private_bytes == 20_000_000
    assert evidence.free_bytes_before == 200_000 * 1024
    assert evidence.free_bytes_after == 350_000 * 1024
    assert (
        len([call for call in executor.calls if call[0] == capacity.DOCKER_ACTIVE_BUILD_PROBE]) == 1
    )
    action_index = next(
        index
        for index, call in enumerate(executor.calls)
        if call[0] == capacity.DOCKER_BUILD_CACHE_ACTION
    )
    assert executor.calls[action_index - 1][0] == capacity.DOCKER_ACTIVE_BUILD_PROBE


def test_shared_heavy_logical_cache_below_private_budget_skips_action(
    tmp_path: Path,
) -> None:
    _prepare_context(tmp_path)
    outputs = _base_outputs(tmp_path)
    outputs[capacity.DOCKER_BUILD_CACHE_PROBE] = [
        "\n".join(
            (
                _cache_line(
                    "140MB",
                    identifier="shared-record-must-not-leak",
                    shared=True,
                ),
                _cache_line("10MB", identifier="private-record-must-not-leak"),
            )
        )
    ]
    executor = FakeExecutor(outputs)

    evidence = _run(tmp_path, executor)

    assert evidence.cache_before.logical_bytes == 150_000_000
    assert evidence.cache_before.shared_bytes == 140_000_000
    assert evidence.cache_before.private_bytes == 10_000_000
    assert evidence.cache_before.reclaimable_logical_bytes == 150_000_000
    assert evidence.cache_before.reclaimable_shared_bytes == 140_000_000
    assert evidence.cache_before.reclaimable_private_bytes == 10_000_000
    assert evidence.cache_before.record_count == 2
    assert evidence.cache_before.shared_record_count == 1
    assert evidence.cache_before.private_record_count == 1
    assert evidence.cache_action == "none"
    summary = evidence.summary()
    assert "logical_cache_records_before=2" in summary
    assert "logical_cache_bytes_before=150000000" in summary
    assert "private_cache_bytes_before=10000000" in summary
    assert "shared_cache_bytes_before=140000000" in summary
    assert "reclaimable_private_cache_bytes_before=10000000" in summary
    assert "reclaimable_shared_cache_bytes_before=140000000" in summary
    assert "logical_cache_records_after=2" in summary
    assert "private_cache_bytes_after=10000000" in summary
    assert "shared_cache_bytes_after=140000000" in summary
    assert "shared-record-must-not-leak" not in summary
    assert "private-record-must-not-leak" not in summary
    assert not any(call[0] == capacity.DOCKER_BUILD_CACHE_ACTION for call in executor.calls)


def test_private_over_budget_action_ignores_shared_logical_post_total(tmp_path: Path) -> None:
    _prepare_context(tmp_path)
    outputs = _base_outputs(tmp_path)
    outputs[capacity.DOCKER_BUILD_CACHE_PROBE] = [
        "\n".join(
            (
                _cache_line("500MB", identifier="shared", shared=True),
                _cache_line("140MB", identifier="private"),
            )
        ),
        "\n".join(
            (
                _cache_line("500MB", identifier="shared", shared=True),
                _cache_line("20MB", identifier="private"),
            )
        ),
    ]
    outputs[capacity.DOCKER_BACKING_FILESYSTEM_PROBE] = [
        "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
        "overlay 1000000 800000 200000 80% /\n",
        "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
        "overlay 1000000 650000 350000 65% /\n",
    ]
    outputs[capacity.DOCKER_BUILD_CACHE_HELP_PROBE] = [_cache_help()]
    outputs[capacity.DOCKER_BUILD_CACHE_ACTION] = [""]
    executor = FakeExecutor(outputs)

    evidence = _run(tmp_path, executor)

    assert evidence.cache_action == "bounded-prune-all"
    assert evidence.cache_before.private_bytes == 140_000_000
    assert evidence.cache_after.private_bytes == 20_000_000
    assert evidence.cache_before.shared_bytes == 500_000_000
    assert evidence.cache_after.shared_bytes == 500_000_000
    assert evidence.cache_after.logical_bytes == 520_000_000
    assert evidence.cache_after.logical_bytes > evidence.cache_budget_bytes
    assert (
        len([call for call in executor.calls if call[0] == capacity.DOCKER_BUILD_CACHE_ACTION]) == 1
    )


def test_shared_cache_cannot_satisfy_private_recovery_requirement(tmp_path: Path) -> None:
    _prepare_context(tmp_path)
    outputs = _base_outputs(tmp_path)
    outputs[capacity.DOCKER_BUILD_CACHE_PROBE] = [
        "\n".join(
            (
                _cache_line("135MB", identifier="fixed", reclaimable=False),
                _cache_line("5MB", identifier="private-reclaimable"),
                _cache_line("500MB", identifier="shared", shared=True),
            )
        )
    ]
    executor = FakeExecutor(outputs)

    with pytest.raises(
        capacity.DockerCapacityError,
        match="BUILDKIT_CACHE_RECLAIMABLE_INSUFFICIENT",
    ):
        _run(tmp_path, executor)

    assert not any(call[0] == capacity.DOCKER_BUILD_CACHE_ACTION for call in executor.calls)


@pytest.mark.parametrize("shared", (None, "false", 0, 1))
def test_cache_shared_evidence_must_be_boolean(tmp_path: Path, shared: object) -> None:
    _prepare_context(tmp_path)
    outputs = _base_outputs(tmp_path)
    row = {
        "ID": "cache-1",
        "Reclaimable": True,
        "Size": "10MB",
    }
    if shared is not None:
        row["Shared"] = shared
    outputs[capacity.DOCKER_BUILD_CACHE_PROBE] = [json.dumps(row)]

    with pytest.raises(capacity.DockerCapacityError, match="build-cache evidence is invalid"):
        _run(tmp_path, FakeExecutor(outputs))


def test_duplicate_cache_shared_conflict_fails_closed(tmp_path: Path) -> None:
    _prepare_context(tmp_path)
    outputs = _base_outputs(tmp_path)
    outputs[capacity.DOCKER_BUILD_CACHE_PROBE] = [
        "\n".join(
            (
                _cache_line("10MB", shared=False),
                _cache_line("10MB", shared=True),
            )
        )
    ]

    with pytest.raises(
        capacity.DockerCapacityError,
        match="duplicate evidence conflicts",
    ):
        _run(tmp_path, FakeExecutor(outputs))


def test_identical_cache_duplicates_collapse_into_exact_partitions(tmp_path: Path) -> None:
    _prepare_context(tmp_path)
    outputs = _base_outputs(tmp_path)
    private = _cache_line("10MB", identifier="private")
    shared = _cache_line("20MB", identifier="shared", shared=True)
    outputs[capacity.DOCKER_BUILD_CACHE_PROBE] = ["\n".join((private, private, shared, shared))]

    evidence = _run(tmp_path, FakeExecutor(outputs))

    assert evidence.cache_before.record_count == 2
    assert evidence.cache_before.logical_bytes == 30_000_000
    assert evidence.cache_before.private_record_count == 1
    assert evidence.cache_before.private_bytes == 10_000_000
    assert evidence.cache_before.shared_record_count == 1
    assert evidence.cache_before.shared_bytes == 20_000_000
    assert evidence.cache_before.reclaimable_record_count == 2
    assert evidence.cache_before.reclaimable_logical_bytes == 30_000_000
    assert evidence.cache_before.reclaimable_private_record_count == 1
    assert evidence.cache_before.reclaimable_private_bytes == 10_000_000
    assert evidence.cache_before.reclaimable_shared_record_count == 1
    assert evidence.cache_before.reclaimable_shared_bytes == 20_000_000


def test_inconsistent_cache_partition_evidence_fails_closed() -> None:
    with pytest.raises(
        capacity.DockerCapacityError,
        match="partition evidence is invalid",
    ):
        capacity.BuildCacheUsage(
            record_count=2,
            logical_bytes=30,
            reclaimable_record_count=2,
            reclaimable_logical_bytes=30,
            private_record_count=1,
            private_bytes=10,
            reclaimable_private_record_count=1,
            reclaimable_private_bytes=10,
            shared_record_count=1,
            shared_bytes=19,
            reclaimable_shared_record_count=1,
            reclaimable_shared_bytes=20,
        )


def test_cache_action_failure_is_sanitized_and_not_retried(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare_context(tmp_path)
    outputs = _base_outputs(tmp_path)
    outputs[capacity.DOCKER_BUILD_CACHE_PROBE] = [
        _cache_line("140MB"),
        _cache_line("20MB"),
    ]
    outputs[capacity.DOCKER_BACKING_FILESYSTEM_PROBE] = [
        "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
        "overlay 1000000 800000 200000 80% /\n",
        "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
        "overlay 1000000 650000 350000 65% /\n",
    ]
    outputs[capacity.DOCKER_BUILD_CACHE_HELP_PROBE] = [_cache_help()]
    outputs[capacity.DOCKER_BUILD_CACHE_ACTION] = [
        RuntimeError("token=must-not-leak /private/operator.env")
    ]
    executor = FakeExecutor(outputs)

    with pytest.raises(capacity.DockerCapacityError) as captured:
        _run(tmp_path, executor)

    fields = _error_fields(captured.value)
    _assert_private_only_cache_fields(fields, suffix="before", size=140_000_000)
    _assert_private_only_cache_fields(fields, suffix="after", size=20_000_000)
    assert fields["logical_cache_delta_signed"] == "-120000000"
    assert fields["private_cache_delta_signed"] == "-120000000"
    assert fields["shared_cache_delta_signed"] == "0"
    assert fields["cache_probe_ok"] == "true"
    non_cache_fields = {key: value for key, value in fields.items() if "cache" not in key}
    assert non_cache_fields == {
        "classification": capacity.DOCKER_BUILD_CACHE_ACTION_FAILED_POST_MEASUREMENT_OK,
        "builder": "desktop-linux",
        "action_succeeded": "false",
        "filesystem_total_before": "1024000000",
        "free_before": "204800000",
        "action_attempts": "1",
        "retry_count": "0",
        "filesystem_probe_ok": "true",
        "filesystem_total_after": "1024000000",
        "free_after": "358400000",
        "free_delta_signed": "153600000",
    }
    console = capsys.readouterr()
    observed = " ".join((str(captured.value), console.out, console.err))
    assert "must-not-leak" not in observed
    assert "/private/operator.env" not in observed
    assert (
        len([call for call in executor.calls if call[0] == capacity.DOCKER_BUILD_CACHE_ACTION]) == 1
    )
    assert (
        len([call for call in executor.calls if call[0] == capacity.DOCKER_BUILD_CACHE_PROBE]) == 2
    )
    assert (
        len(
            [call for call in executor.calls if call[0] == capacity.DOCKER_BACKING_FILESYSTEM_PROBE]
        )
        == 2
    )


def test_failed_cache_action_and_failed_post_probe_report_composite_failure(
    tmp_path: Path,
) -> None:
    _prepare_context(tmp_path)
    sentinel = "post-probe-secret-must-not-leak"
    outputs = _base_outputs(tmp_path)
    outputs[capacity.DOCKER_BUILD_CACHE_PROBE] = [
        _cache_line("140MB"),
        RuntimeError(sentinel),
    ]
    outputs[capacity.DOCKER_BACKING_FILESYSTEM_PROBE] = [
        "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
        "overlay 1000000 800000 200000 80% /\n",
        "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
        "overlay 1000000 650000 350000 65% /\n",
    ]
    outputs[capacity.DOCKER_BUILD_CACHE_HELP_PROBE] = [_cache_help()]
    outputs[capacity.DOCKER_BUILD_CACHE_ACTION] = [RuntimeError(sentinel)]
    executor = FakeExecutor(outputs)

    with pytest.raises(capacity.DockerCapacityError) as captured:
        _run(tmp_path, executor)

    fields = _error_fields(captured.value)
    assert fields["classification"] == (
        capacity.DOCKER_BUILD_CACHE_ACTION_FAILED_POST_MEASUREMENT_FAILED
    )
    assert fields["builder"] == "desktop-linux"
    assert fields["action_succeeded"] == "false"
    assert fields["action_attempts"] == "1"
    assert fields["retry_count"] == "0"
    assert fields["cache_probe_ok"] == "false"
    assert fields["filesystem_probe_ok"] == "true"
    _assert_private_only_cache_fields(fields, suffix="before", size=140_000_000)
    assert not any(key.endswith("_after") and "cache" in key for key in fields)
    assert "logical_cache_delta_signed" not in fields
    assert "private_cache_delta_signed" not in fields
    assert "shared_cache_delta_signed" not in fields
    assert fields["filesystem_total_after"] == "1024000000"
    assert fields["free_after"] == "358400000"
    assert fields["free_delta_signed"] == "153600000"
    assert sentinel not in str(captured.value)
    assert (
        len([call for call in executor.calls if call[0] == capacity.DOCKER_BUILD_CACHE_ACTION]) == 1
    )
    assert (
        len([call for call in executor.calls if call[0] == capacity.DOCKER_BUILD_CACHE_PROBE]) == 2
    )
    assert (
        len(
            [call for call in executor.calls if call[0] == capacity.DOCKER_BACKING_FILESYSTEM_PROBE]
        )
        == 2
    )


def test_successful_cache_action_and_failed_post_probe_fail_closed(
    tmp_path: Path,
) -> None:
    _prepare_context(tmp_path)
    sentinel = "filesystem-post-probe-secret-must-not-leak"
    outputs = _base_outputs(tmp_path)
    outputs[capacity.DOCKER_BUILD_CACHE_PROBE] = [
        _cache_line("140MB"),
        _cache_line("20MB"),
    ]
    outputs[capacity.DOCKER_BACKING_FILESYSTEM_PROBE] = [
        "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
        "overlay 1000000 800000 200000 80% /\n",
        RuntimeError(sentinel),
    ]
    outputs[capacity.DOCKER_BUILD_CACHE_HELP_PROBE] = [_cache_help()]
    outputs[capacity.DOCKER_BUILD_CACHE_ACTION] = [""]
    executor = FakeExecutor(outputs)

    with pytest.raises(capacity.DockerCapacityError) as captured:
        _run(tmp_path, executor)

    fields = _error_fields(captured.value)
    assert fields["classification"] == (
        capacity.DOCKER_BUILD_CACHE_ACTION_SUCCEEDED_POST_MEASUREMENT_FAILED
    )
    assert fields["builder"] == "desktop-linux"
    assert fields["action_succeeded"] == "true"
    assert fields["action_attempts"] == "1"
    assert fields["retry_count"] == "0"
    assert fields["cache_probe_ok"] == "true"
    assert fields["filesystem_probe_ok"] == "false"
    _assert_private_only_cache_fields(fields, suffix="before", size=140_000_000)
    _assert_private_only_cache_fields(fields, suffix="after", size=20_000_000)
    assert fields["logical_cache_delta_signed"] == "-120000000"
    assert fields["private_cache_delta_signed"] == "-120000000"
    assert fields["shared_cache_delta_signed"] == "0"
    assert "filesystem_total_after" not in fields
    assert "free_after" not in fields
    assert "free_delta_signed" not in fields
    assert sentinel not in str(captured.value)
    assert (
        len([call for call in executor.calls if call[0] == capacity.DOCKER_BUILD_CACHE_ACTION]) == 1
    )
    assert (
        len([call for call in executor.calls if call[0] == capacity.DOCKER_BUILD_CACHE_PROBE]) == 2
    )
    assert (
        len(
            [call for call in executor.calls if call[0] == capacity.DOCKER_BACKING_FILESYSTEM_PROBE]
        )
        == 2
    )


@pytest.mark.parametrize(
    ("cache_after", "filesystem_after", "classification"),
    (
        (
            "20MB",
            "overlay 900000 550000 350000 62% /\n",
            "DOCKER_BACKING_FILESYSTEM_CHANGED_DURING_PREFLIGHT",
        ),
        (
            "140MB",
            "overlay 1000000 650000 350000 65% /\n",
            "BUILDKIT_CACHE_BUDGET_NOT_RESTORED",
        ),
        (
            "20MB",
            "overlay 1000000 900000 100000 90% /\n",
            "DOCKER_CAPACITY_INSUFFICIENT_AFTER_CACHE_ACTION",
        ),
    ),
)
def test_post_action_policy_failures_preserve_full_numeric_evidence(
    tmp_path: Path,
    cache_after: str,
    filesystem_after: str,
    classification: str,
) -> None:
    _prepare_context(tmp_path)
    outputs = _base_outputs(tmp_path)
    outputs[capacity.DOCKER_BUILD_CACHE_PROBE] = [
        _cache_line("140MB"),
        _cache_line(cache_after),
    ]
    outputs[capacity.DOCKER_BACKING_FILESYSTEM_PROBE] = [
        "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
        "overlay 1000000 800000 200000 80% /\n",
        "Filesystem 1024-blocks Used Available Capacity Mounted on\n" + filesystem_after,
    ]
    outputs[capacity.DOCKER_BUILD_CACHE_HELP_PROBE] = [_cache_help()]
    outputs[capacity.DOCKER_BUILD_CACHE_ACTION] = [""]
    executor = FakeExecutor(outputs)

    with pytest.raises(capacity.DockerCapacityError) as captured:
        _run(tmp_path, executor)

    fields = _error_fields(captured.value)
    assert fields["classification"] == classification
    assert fields["builder"] == "desktop-linux"
    assert fields["action_succeeded"] == "true"
    assert fields["action_attempts"] == "1"
    assert fields["retry_count"] == "0"
    assert fields["cache_probe_ok"] == "true"
    assert fields["filesystem_probe_ok"] == "true"
    parsed_after = capacity._parse_size(cache_after)
    _assert_private_only_cache_fields(fields, suffix="before", size=140_000_000)
    _assert_private_only_cache_fields(fields, suffix="after", size=parsed_after)
    assert fields["logical_cache_delta_signed"] == str(parsed_after - 140_000_000)
    assert fields["private_cache_delta_signed"] == str(parsed_after - 140_000_000)
    assert fields["shared_cache_delta_signed"] == "0"
    assert "filesystem_total_after" in fields
    assert "free_after" in fields
    assert "free_delta_signed" in fields
    assert (
        len([call for call in executor.calls if call[0] == capacity.DOCKER_BUILD_CACHE_ACTION]) == 1
    )


def test_cache_action_requires_enough_reclaimable_bytes_to_restore_budget(
    tmp_path: Path,
) -> None:
    _prepare_context(tmp_path)
    outputs = _base_outputs(tmp_path)
    outputs[capacity.DOCKER_BUILD_CACHE_PROBE] = [
        "\n".join(
            (
                _cache_line("135MB", identifier="fixed", reclaimable=False),
                _cache_line("5MB", identifier="reclaimable"),
            )
        )
    ]
    executor = FakeExecutor(outputs)

    with pytest.raises(
        capacity.DockerCapacityError,
        match="BUILDKIT_CACHE_RECLAIMABLE_INSUFFICIENT",
    ):
        _run(tmp_path, executor)

    assert not any(call[0] == capacity.DOCKER_BUILD_CACHE_ACTION for call in executor.calls)


def test_cache_action_preserves_floor_when_proving_required_free_space(
    tmp_path: Path,
) -> None:
    _prepare_context(tmp_path)
    outputs = _base_outputs(tmp_path)
    outputs[capacity.DOCKER_BUILD_CACHE_PROBE] = [_cache_line("140MB")]
    outputs[capacity.DOCKER_BACKING_FILESYSTEM_PROBE] = [
        "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
        "overlay 1000000 970000 30000 97% /\n"
    ]
    executor = FakeExecutor(outputs)

    with pytest.raises(
        capacity.DockerCapacityError,
        match="DOCKER_CAPACITY_INSUFFICIENT_FOR_CACHE_ACTION",
    ):
        _run(tmp_path, executor)

    assert not any(call[0] == capacity.DOCKER_BUILD_CACHE_ACTION for call in executor.calls)


def test_ambiguous_current_builder_fails_closed(tmp_path: Path) -> None:
    _prepare_context(tmp_path)
    outputs = _base_outputs(tmp_path)
    second = {
        "Current": True,
        "Driver": "docker-container",
        "Name": "another-builder",
        "Nodes": [
            {
                "Endpoint": "another-builder",
                "Name": "another-builder",
                "Status": "running",
            }
        ],
    }
    outputs[capacity.DOCKER_BUILDER_LIST_PROBE] = [_builder_lines() + "\n" + json.dumps(second)]

    with pytest.raises(capacity.DockerCapacityError, match="DOCKER_BUILDER_AMBIGUOUS"):
        _run(tmp_path, FakeExecutor(outputs))


def test_non_current_builder_override_is_rejected(tmp_path: Path) -> None:
    _prepare_context(tmp_path)
    outputs = _base_outputs(tmp_path)
    alternate = {
        "Current": False,
        "Driver": "docker",
        "Name": "alternate",
        "Nodes": [{"Endpoint": "alternate", "Name": "alternate", "Status": "running"}],
    }
    outputs[capacity.DOCKER_BUILDER_LIST_PROBE] = [_builder_lines() + "\n" + json.dumps(alternate)]

    with pytest.raises(
        capacity.DockerCapacityError,
        match="DOCKER_BUILDER_OVERRIDE_NOT_CURRENT",
    ):
        _run(tmp_path, FakeExecutor(outputs), environ={"BUILDX_BUILDER": "alternate"})


def test_multi_node_current_builder_is_rejected(tmp_path: Path) -> None:
    _prepare_context(tmp_path)
    outputs = _base_outputs(tmp_path)
    row = {
        "Current": True,
        "Driver": "docker",
        "Name": "desktop-linux",
        "Nodes": [
            {
                "Endpoint": "desktop-linux",
                "Name": "desktop-linux",
                "Status": "running",
            },
            {
                "Endpoint": "secondary",
                "Name": "secondary",
                "Status": "running",
            },
        ],
    }
    outputs[capacity.DOCKER_BUILDER_LIST_PROBE] = [json.dumps(row)]

    with pytest.raises(
        capacity.DockerCapacityError,
        match="DOCKER_BUILDER_MUST_HAVE_EXACTLY_ONE_NODE",
    ):
        _run(tmp_path, FakeExecutor(outputs))


def test_current_builder_must_match_current_local_context(tmp_path: Path) -> None:
    _prepare_context(tmp_path)
    outputs = _base_outputs(tmp_path)
    outputs[capacity.DOCKER_CONTEXT_PROBE] = [
        json.dumps("another-local") + "|" + json.dumps("unix:///private/docker.sock")
    ]

    with pytest.raises(
        capacity.DockerCapacityError,
        match="DOCKER_BUILDER_NOT_LOCAL_RUNNING_DOCKER_DRIVER",
    ):
        _run(tmp_path, FakeExecutor(outputs))


def test_compose_context_outside_checkout_is_rejected(tmp_path: Path) -> None:
    _prepare_context(tmp_path)
    outside = tmp_path.parent / "outside-build-context"
    outputs = _base_outputs(tmp_path)
    document = json.loads(_compose_config(tmp_path))
    document["services"]["api"]["build"]["context"] = str(outside)
    document["services"]["migrate"]["build"]["context"] = str(outside)
    outputs[capacity.COMPOSE_BUILD_CONFIG_PROBE] = [json.dumps(document)]

    with pytest.raises(capacity.DockerCapacityError, match="BUILD_CONTEXT_OUTSIDE_CHECKOUT"):
        _run(tmp_path, FakeExecutor(outputs))


def test_active_build_blocks_cache_action_without_mutation(tmp_path: Path) -> None:
    _prepare_context(tmp_path)
    outputs = _base_outputs(tmp_path)
    outputs[capacity.DOCKER_BUILD_CACHE_PROBE] = [_cache_line("140MB")]
    outputs[capacity.DOCKER_BUILD_CACHE_HELP_PROBE] = [_cache_help()]
    outputs[capacity.DOCKER_ACTIVE_BUILD_PROBE] = ["running\n"]
    executor = FakeExecutor(outputs)

    with pytest.raises(capacity.DockerCapacityError, match="DOCKER_ACTIVE_BUILD_PRESENT"):
        _run(tmp_path, executor)

    assert not any(call[0] == capacity.DOCKER_BUILD_CACHE_ACTION for call in executor.calls)


def test_lock_is_nonblocking_and_released_after_failure(tmp_path: Path) -> None:
    _prepare_context(tmp_path)

    with capacity.exclusive_docker_workflow_lock(tmp_path):
        lock_directory = tmp_path / "runtime" / "operator-locks"
        lock_file = lock_directory / "update-build.lock"
        assert lock_directory.stat().st_mode & 0o777 == 0o700
        assert lock_file.stat().st_mode & 0o777 == 0o600
        with pytest.raises(
            capacity.DockerCapacityError,
            match=capacity.DOCKER_WORKFLOW_LOCK_UNAVAILABLE,
        ):
            with capacity.exclusive_docker_workflow_lock(tmp_path):
                pytest.fail("A concurrent lock holder must not enter the mutation region.")

    with capacity.exclusive_docker_workflow_lock(tmp_path) as reacquired:
        reacquired.require_held()


def test_released_lock_cannot_authorize_a_capacity_action(tmp_path: Path) -> None:
    _prepare_context(tmp_path)
    with capacity.exclusive_docker_workflow_lock(tmp_path) as released:
        released.require_held()

    with pytest.raises(capacity.DockerCapacityError, match="LOCK_NOT_HELD"):
        capacity.governed_compose_build_capacity(
            root=tmp_path,
            compose_config_command=("compose", "config"),
            docker_filesystem_probe_command=("compose", "exec", "postgres", "df"),
            selected_build_services=("api",),
            environ={},
            executor=FakeExecutor({}),
            lock=released,
        )


def test_symlinked_context_is_rejected(tmp_path: Path) -> None:
    physical = tmp_path / "physical"
    _prepare_context(physical)
    linked = tmp_path / "linked"
    linked.symlink_to(physical, target_is_directory=True)
    outputs = _base_outputs(physical)
    document = json.loads(_compose_config(physical))
    document["services"]["api"]["build"]["context"] = str(linked)
    document["services"]["migrate"]["build"]["context"] = str(linked)
    outputs[capacity.COMPOSE_BUILD_CONFIG_PROBE] = [json.dumps(document)]

    with pytest.raises(capacity.DockerCapacityError, match="regular directory"):
        _run(physical, FakeExecutor(outputs))


def test_symlinked_dockerfile_is_rejected(tmp_path: Path) -> None:
    _prepare_context(tmp_path)
    real_file = tmp_path / "backend" / "Dockerfile.real"
    real_file.write_bytes(b"FROM scratch\n")
    (tmp_path / "backend" / "Dockerfile").unlink()
    (tmp_path / "backend" / "Dockerfile").symlink_to(real_file)

    with pytest.raises(capacity.DockerCapacityError, match="regular file"):
        _run(tmp_path, FakeExecutor(_base_outputs(tmp_path)))


def test_build_args_and_probe_failure_payload_never_escape(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare_context(tmp_path)
    sentinel = "build-credential-must-not-leak"
    secret_path = "/private/operator-secret.env"
    outputs = _base_outputs(tmp_path)
    document = json.loads(_compose_config(tmp_path))
    document["services"]["api"]["build"]["args"] = {"TOKEN": sentinel}
    document["services"]["migrate"]["build"]["args"] = {"TOKEN": sentinel}
    outputs[capacity.COMPOSE_BUILD_CONFIG_PROBE] = [json.dumps(document)]
    outputs[capacity.DOCKER_BACKING_FILESYSTEM_PROBE] = [RuntimeError(f"{sentinel} {secret_path}")]

    with pytest.raises(capacity.DockerCapacityError) as captured:
        _run(tmp_path, FakeExecutor(outputs))

    console = capsys.readouterr()
    observed = " ".join((str(captured.value), repr(captured.value), console.out, console.err))
    assert sentinel not in observed
    assert secret_path not in observed


def test_historical_images_for_one_fingerprint_use_conservative_maximum(
    tmp_path: Path,
) -> None:
    _prepare_context(tmp_path)
    outputs = _base_outputs(tmp_path)
    outputs[capacity.DOCKER_IMAGE_SIZE_PROBE] = [
        "sha256:"
        + ("a" * 64)
        + "\t10000000\tlinux\tarm64\nsha256:"
        + ("b" * 64)
        + "\t12000000\tlinux\tarm64\n"
    ]

    evidence = _run(tmp_path, FakeExecutor(outputs))

    assert evidence.image_bytes == 12_000_000
    assert evidence.build_peak_bytes == 24_000_000 + 1_013
    assert evidence.selected_image_tags == 2


@pytest.mark.parametrize(
    ("image_output", "classification"),
    (
        (
            "sha256:" + ("a" * 64) + "\t10000000\tlinux\tarm64\n",
            "incomplete",
        ),
        (
            ("sha256:" + ("a" * 64) + "\t0\tlinux\tarm64\n") * 2,
            "invalid",
        ),
        (
            ("not-an-image-id\t10000000\tlinux\tarm64\n") * 2,
            "invalid",
        ),
        (
            ("sha256:" + ("a" * 64) + "\t10000000\tlinux\tamd64\n") * 2,
            "platform evidence conflicts",
        ),
    ),
)
def test_missing_invalid_or_wrong_platform_image_evidence_fails_closed(
    tmp_path: Path,
    image_output: str,
    classification: str,
) -> None:
    _prepare_context(tmp_path)
    outputs = _base_outputs(tmp_path)
    outputs[capacity.DOCKER_IMAGE_SIZE_PROBE] = [image_output]

    with pytest.raises(capacity.DockerCapacityError, match=classification):
        _run(tmp_path, FakeExecutor(outputs))


def test_remote_docker_context_is_rejected_before_cache_or_filesystem_probe(
    tmp_path: Path,
) -> None:
    _prepare_context(tmp_path)
    outputs = _base_outputs(tmp_path)
    outputs[capacity.DOCKER_CONTEXT_PROBE] = [
        json.dumps("desktop-linux") + "|" + json.dumps("tcp://remote.example:2376")
    ]
    executor = FakeExecutor(outputs)

    with pytest.raises(capacity.DockerCapacityError, match="MUST_BE_LOCAL_UNIX"):
        _run(tmp_path, executor)

    assert not any(
        call[0]
        in {
            capacity.DOCKER_BUILDER_LIST_PROBE,
            capacity.DOCKER_IMAGE_SIZE_PROBE,
            capacity.DOCKER_BUILD_CACHE_PROBE,
            capacity.DOCKER_BACKING_FILESYSTEM_PROBE,
            capacity.DOCKER_BUILD_CACHE_ACTION,
        }
        for call in executor.calls
    )


def test_remote_docker_host_override_is_rejected_before_context_probe(
    tmp_path: Path,
) -> None:
    _prepare_context(tmp_path)
    executor = FakeExecutor(_base_outputs(tmp_path))

    with pytest.raises(capacity.DockerCapacityError, match="MUST_BE_LOCAL_UNIX"):
        _run(tmp_path, executor, environ={"DOCKER_HOST": "tcp://remote.example:2376"})

    assert not any(
        call[0]
        in {
            capacity.DOCKER_CONTEXT_PROBE,
            capacity.DOCKER_BUILDER_LIST_PROBE,
            capacity.DOCKER_IMAGE_SIZE_PROBE,
            capacity.DOCKER_BUILD_CACHE_PROBE,
            capacity.DOCKER_BACKING_FILESYSTEM_PROBE,
            capacity.DOCKER_BUILD_CACHE_ACTION,
        }
        for call in executor.calls
    )


def test_dirty_checkout_fails_before_any_docker_probe(tmp_path: Path) -> None:
    _prepare_context(tmp_path)
    outputs = _base_outputs(tmp_path)
    outputs[capacity.GIT_CLEAN_CHECKOUT_PROBE] = ["?? ignored-runtime-surprise\n"]
    executor = FakeExecutor(outputs)

    with pytest.raises(capacity.DockerCapacityError, match="REQUIRES_CLEAN_CHECKOUT"):
        _run(tmp_path, executor)

    docker_kinds = {
        capacity.DOCKER_CONTEXT_PROBE,
        capacity.DOCKER_BUILDER_LIST_PROBE,
        capacity.DOCKER_BUILD_CACHE_PROBE,
        capacity.DOCKER_BACKING_FILESYSTEM_PROBE,
        capacity.DOCKER_IMAGE_SIZE_PROBE,
        capacity.DOCKER_BUILD_CACHE_ACTION,
    }
    assert not any(call[0] in docker_kinds for call in executor.calls)


def test_active_build_probe_failure_is_sanitized(tmp_path: Path) -> None:
    _prepare_context(tmp_path)
    sentinel = "active-build-token-must-not-leak"
    outputs = _base_outputs(tmp_path)
    outputs[capacity.DOCKER_BUILD_CACHE_PROBE] = [_cache_line("140MB")]
    outputs[capacity.DOCKER_BUILD_CACHE_HELP_PROBE] = [_cache_help()]
    outputs[capacity.DOCKER_ACTIVE_BUILD_PROBE] = [RuntimeError(sentinel)]
    executor = FakeExecutor(outputs)

    with pytest.raises(capacity.DockerCapacityError) as captured:
        _run(tmp_path, executor)

    assert capacity.DOCKER_ACTIVE_BUILD_PROBE in str(captured.value)
    assert sentinel not in str(captured.value)
    assert not any(call[0] == capacity.DOCKER_BUILD_CACHE_ACTION for call in executor.calls)
