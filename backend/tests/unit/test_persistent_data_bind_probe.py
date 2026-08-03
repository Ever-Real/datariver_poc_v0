from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "scripts" / "probe_persistent_data_bind.py"
SCRIPTS = ROOT / "scripts"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("probe_persistent_data_bind", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    sys.path.insert(0, os.fspath(SCRIPTS))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(os.fspath(SCRIPTS))
    return module


probe = _load_module()


def _layout(tmp_path: Path) -> Any:
    os.chmod(tmp_path, 0o700)
    return probe.prepare_layout(tmp_path / "datariver-data")


def _bundle(layout: Any) -> Any:
    return probe.create_probe_secrets(layout)


def test_checked_in_image_references_remain_exactly_pinned() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    connectors = (ROOT / "compose.local-connectors.yaml").read_text(encoding="utf-8")

    assert probe.POSTGRES_IMAGE_REFERENCE in compose
    assert probe.MINIO_IMAGE_REFERENCE in connectors
    assert probe.POSTGRES_IMAGE_REFERENCE.endswith(probe.POSTGRES_IMAGE_ID)
    assert probe.MINIO_IMAGE_REFERENCE.endswith(probe.MINIO_IMAGE_ID)


def test_postgres_create_argv_has_only_the_approved_capabilities_and_limits(
    tmp_path: Path,
) -> None:
    layout = _layout(tmp_path)

    arguments = probe.postgres_create_arguments(layout)

    assert arguments[:4] == ("docker", "create", "--name", probe.POSTGRES_PROBE_CONTAINER)
    assert arguments.count("--cap-drop") == 1
    assert arguments[arguments.index("--cap-drop") + 1] == "ALL"
    capabilities = tuple(
        arguments[index + 1] for index, value in enumerate(arguments) if value == "--cap-add"
    )
    assert capabilities == probe.POSTGRES_CAPABILITIES
    assert "--privileged" not in arguments
    assert ("--network", "none") == (
        arguments[arguments.index("--network")],
        arguments[arguments.index("--network") + 1],
    )
    assert ("--memory", "1g") == (
        arguments[arguments.index("--memory")],
        arguments[arguments.index("--memory") + 1],
    )
    assert arguments[arguments.index("--pids-limit") + 1] == "128"
    assert arguments[arguments.index("--stop-timeout") + 1] == "60"
    assert arguments[arguments.index("--log-driver") + 1] == "none"
    assert "docker.sock" not in "\n".join(arguments)
    assert not {"sh", "bash", "-c"}.intersection(arguments)


def test_minio_create_argv_drops_all_capabilities_and_uses_file_only_server_secrets(
    tmp_path: Path,
) -> None:
    layout = _layout(tmp_path)

    arguments = probe.minio_create_arguments(layout)

    assert arguments.count("--cap-drop") == 1
    assert arguments[arguments.index("--cap-drop") + 1] == "ALL"
    assert "--cap-add" not in arguments
    assert "--privileged" not in arguments
    assert arguments[arguments.index("--memory") + 1] == "512m"
    assert arguments[arguments.index("--cpus") + 1] == "0.5"
    assert arguments[arguments.index("--pids-limit") + 1] == "64"
    assert arguments[arguments.index("--stop-timeout") + 1] == "30"
    assert "MINIO_ROOT_USER_FILE=/run/secrets/minio_access_key" in arguments
    assert "MINIO_ROOT_PASSWORD_FILE=/run/secrets/minio_secret_key" in arguments
    assert "MC_CONFIG_DIR=/tmp/mc" in arguments
    assert "docker.sock" not in "\n".join(arguments)
    assert not {"sh", "bash", "-c"}.intersection(arguments)


def test_mc_alias_uses_exact_non_tty_stdin_credential_contract() -> None:
    assert probe.mc_alias_arguments() == (
        "docker",
        "exec",
        "-i",
        probe.MINIO_PROBE_CONTAINER,
        "mc",
        "alias",
        "set",
        "probe",
        "http://127.0.0.1:9000",
        "--api",
        "S3v4",
        "--path",
        "on",
    )


def test_postgres_readiness_argv_has_one_exact_socket_host() -> None:
    arguments = probe._postgres_readiness_arguments()

    assert arguments.count("-h") == 1
    assert arguments[arguments.index("-h") + 1] == "/var/run/postgresql"


class _AbsenceExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def output(self, arguments: Any, **_kwargs: Any) -> bytes:
        self.calls.append(tuple(arguments))
        return b""


def test_probe_absence_query_uses_one_exact_name_filter_per_container() -> None:
    executor = _AbsenceExecutor()

    probe.require_probe_containers_absent(executor)

    assert len(executor.calls) == 2
    for name, arguments in zip(
        (probe.POSTGRES_PROBE_CONTAINER, probe.MINIO_PROBE_CONTAINER),
        executor.calls,
        strict=True,
    ):
        assert arguments.count("--filter") == 1
        assert arguments[arguments.index("--filter") + 1] == f"name=^/{name}$"


def test_probe_secrets_use_csprng_lengths_and_private_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = _layout(tmp_path)
    urlsafe_calls: list[int] = []
    hex_calls: list[int] = []

    def token_urlsafe(length: int) -> str:
        urlsafe_calls.append(length)
        return "P" * 48 if length == 36 else "S" * 43

    def token_hex(length: int) -> str:
        hex_calls.append(length)
        return "A" * 20

    monkeypatch.setattr(probe.secrets, "token_urlsafe", token_urlsafe)
    monkeypatch.setattr(probe.secrets, "token_hex", token_hex)

    bundle = probe.create_probe_secrets(layout)

    assert urlsafe_calls == [36, 32]
    assert hex_calls == [10]
    assert tuple(map(len, bundle.values)) == (48, 20, 43)
    for path, value in (
        (layout.postgres_password_file, bundle.postgres_password),
        (layout.minio_access_file, bundle.minio_access),
        (layout.minio_secret_file, bundle.minio_secret),
    ):
        metadata = path.lstat()
        assert stat.S_ISREG(metadata.st_mode)
        assert not path.is_symlink()
        assert stat.S_IMODE(metadata.st_mode) == 0o600
        assert path.read_bytes() == value + b"\n"


def test_secret_bundle_rejects_replacement_between_open_fd_and_post_fsync_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout = _layout(tmp_path)
    original_fsync = probe._fsync_directory

    def replace_after_fsync(path: Path) -> None:
        original_fsync(path)
        if path == layout.secrets_dir:
            layout.minio_access_file.unlink()
            layout.minio_access_file.write_bytes(b"R" * 20 + b"\n")
            layout.minio_access_file.chmod(0o600)

    monkeypatch.setattr(probe, "_fsync_directory", replace_after_fsync)

    with pytest.raises(probe.ProbeError, match=r"^PROBE_SECRET_FILE_CHANGED$"):
        probe.create_probe_secrets(layout)

    assert all(path.exists() for path in probe._secret_paths(layout))


def test_private_executor_closes_binary_stdin_and_applies_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = probe.PrivateExecutor()
    secret = b"A" * 20
    executor.set_forbidden((secret,))
    observed: dict[str, Any] = {}

    def fake_run(arguments: tuple[str, ...], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        observed["arguments"] = arguments
        observed.update(kwargs)
        return subprocess.CompletedProcess(arguments, 0, b"ok", b"")

    monkeypatch.setattr(probe.subprocess, "run", fake_run)

    output = executor.output(
        ("docker", "exec", "-i", "probe", "mc", "alias", "set"),
        classification="FIXED_FAILURE",
        timeout_seconds=20,
        input_bytes=secret + b"\n" + b"B" * 40 + b"\n",
    )

    assert output == b"ok"
    assert observed["input"] == secret + b"\n" + b"B" * 40 + b"\n"
    assert observed["timeout"] == 20
    assert observed["capture_output"] is True
    assert "text" not in observed


def test_private_executor_never_exposes_a_secret_echo(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    executor = probe.PrivateExecutor()
    secret = b"future_secret_" + b"X" * 24
    executor.set_forbidden((secret,))

    def fake_run(arguments: tuple[str, ...], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(arguments, 0, b"", secret)

    monkeypatch.setattr(probe.subprocess, "run", fake_run)

    with pytest.raises(probe.ProbeError, match=r"^PROBE_SECRET_ECHO_DETECTED$") as raised:
        executor.output(("docker", "version"), classification="FIXED_FAILURE")

    captured = capsys.readouterr()
    assert secret.decode("ascii") not in captured.out + captured.err + str(raised.value)


def test_pg_dump_capture_is_binary_bounded_fsynced_and_hashed(
    tmp_path: Path,
) -> None:
    executor = probe.PrivateExecutor()
    destination = tmp_path / "dump.partial"
    payload = b"PGDMP\x00\xffbinary"

    size, digest = executor.stream_stdout(
        (sys.executable, "-c", f"import sys;sys.stdout.buffer.write({payload!r})"),
        destination=destination,
        classification="POSTGRES_PROBE_DUMP_FAILED",
        timeout_seconds=60,
    )

    assert destination.read_bytes() == payload
    assert size == len(payload)
    assert digest == probe.hashlib.sha256(payload).hexdigest()
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_pg_dump_capture_never_writes_past_the_in_flight_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = probe.PrivateExecutor()
    destination = tmp_path / "overflow.partial"
    monkeypatch.setattr(probe, "MAXIMUM_PROBE_DUMP_BYTES", 8)

    with pytest.raises(probe.ProbeError, match=r"^POSTGRES_PROBE_DUMP_LIMIT_EXCEEDED$"):
        executor.stream_stdout(
            (
                sys.executable,
                "-c",
                "import sys;sys.stderr.write('private-stderr');sys.stdout.write('123456789')",
            ),
            destination=destination,
            classification="POSTGRES_PROBE_DUMP_FAILED",
            timeout_seconds=60,
        )

    assert destination.stat().st_size <= 8


def test_pg_dump_capture_accepts_the_exact_boundary(tmp_path: Path, monkeypatch: Any) -> None:
    destination = tmp_path / "boundary.partial"
    monkeypatch.setattr(probe, "MAXIMUM_PROBE_DUMP_BYTES", 8)

    size, _digest = probe.PrivateExecutor().stream_stdout(
        (sys.executable, "-c", "import sys;sys.stdout.write('12345678')"),
        destination=destination,
        classification="POSTGRES_PROBE_DUMP_FAILED",
        timeout_seconds=5,
    )

    assert size == 8
    assert destination.read_bytes() == b"12345678"


def test_pg_dump_overflow_terminates_and_reaps_the_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "child.partial"
    pid_file = tmp_path / "child.pid"
    monkeypatch.setattr(probe, "MAXIMUM_PROBE_DUMP_BYTES", 8)
    child = (
        "import os,pathlib,sys,time;"
        f"pathlib.Path({os.fspath(pid_file)!r}).write_text(str(os.getpid()));"
        "sys.stdout.write('123456789');sys.stdout.flush();time.sleep(60)"
    )

    with pytest.raises(probe.ProbeError, match=r"^POSTGRES_PROBE_DUMP_LIMIT_EXCEEDED$"):
        probe.PrivateExecutor().stream_stdout(
            (sys.executable, "-c", child),
            destination=destination,
            classification="POSTGRES_PROBE_DUMP_FAILED",
            timeout_seconds=5,
        )

    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text(encoding="utf-8")), 0)


def test_pg_dump_digest_is_streamed_without_reopening_the_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "streamed.partial"
    payload = b"PGDMP-streamed-sha"

    def forbidden_reopen(_path: Path) -> str:
        raise AssertionError("stream digest must not reopen the path")

    monkeypatch.setattr(probe, "_sha256_file", forbidden_reopen, raising=False)

    size, digest = probe.PrivateExecutor().stream_stdout(
        (sys.executable, "-c", f"import sys;sys.stdout.buffer.write({payload!r})"),
        destination=destination,
        classification="POSTGRES_PROBE_DUMP_FAILED",
        timeout_seconds=5,
    )

    assert size == len(payload)
    assert digest == probe.hashlib.sha256(payload).hexdigest()


def test_pg_dump_capture_rejects_destination_path_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "replaced.partial"
    original_read = probe.os.read
    replaced = False

    def replacing_read(descriptor: int, size: int) -> bytes:
        nonlocal replaced
        chunk = cast(bytes, original_read(descriptor, size))
        if chunk and not replaced:
            destination.unlink()
            destination.write_bytes(b"replacement")
            destination.chmod(0o600)
            replaced = True
        return chunk

    monkeypatch.setattr(probe.os, "read", replacing_read)

    with pytest.raises(probe.ProbeError, match=r"^POSTGRES_PROBE_DUMP_PATH_CHANGED$"):
        probe.PrivateExecutor().stream_stdout(
            (sys.executable, "-c", "import sys;sys.stdout.write('original')"),
            destination=destination,
            classification="POSTGRES_PROBE_DUMP_FAILED",
            timeout_seconds=5,
        )

    assert destination.read_bytes() == b"replacement"


def test_prepare_and_success_cleanup_remove_a_task_created_parent(tmp_path: Path) -> None:
    os.chmod(tmp_path, 0o700)
    parent = tmp_path / "datariver-data"
    layout = probe.prepare_layout(parent)
    (layout.postgres_data / "probe.bin").write_bytes(b"value")

    probe.cleanup_success(layout)

    assert not parent.exists()


def test_success_cleanup_retains_a_preexisting_parent(tmp_path: Path) -> None:
    os.chmod(tmp_path, 0o700)
    parent = tmp_path / "datariver-data"
    parent.mkdir(mode=0o700)
    os.chmod(parent, 0o700)
    layout = probe.prepare_layout(parent)

    probe.cleanup_success(layout)

    assert parent.is_dir()
    assert list(parent.iterdir()) == []


def test_prepare_rejects_a_symlinked_parent(tmp_path: Path) -> None:
    os.chmod(tmp_path, 0o700)
    physical = tmp_path / "physical"
    physical.mkdir(mode=0o700)
    linked = tmp_path / "datariver-data"
    linked.symlink_to(physical, target_is_directory=True)

    with pytest.raises(probe.ProbeError, match=r"^PROBE_PARENT_INVALID$"):
        probe.prepare_layout(linked)


def test_probe_evidence_never_claims_apfs_noowners_as_ownership_enforcement() -> None:
    evidence = probe.ProbeEvidence(
        filesystem_noowners=True,
        postgres_uid=999,
        postgres_gid=999,
        postgres_mode=0o700,
        minio_uid=0,
        minio_gid=0,
        minio_mode=0o700,
        postgres_dump_bytes=4096,
        postgres_dump_sha256="a" * 64,
        minio_object_sha256="b" * 64,
    )

    summary = evidence.summary()

    assert "filesystem_noowners=true" in summary
    assert "ownership_enforcement_claimed=false" in summary


class _OneOutputExecutor:
    def __init__(self, document: dict[str, Any]) -> None:
        self.document = document

    def output(self, _arguments: Any, **_kwargs: Any) -> bytes:
        return json.dumps([self.document], separators=(",", ":")).encode("utf-8")


def _container_document(
    layout: Any,
    name: str,
    *,
    spec: Any | None = None,
) -> dict[str, Any]:
    spec = spec or probe._container_specs(layout)[name]
    environment = dict(spec.image_environment)
    environment.update(spec.required_environment)
    return {
        "Id": "a" * 64,
        "Image": spec.image_id,
        "RestartCount": 0,
        "Config": {"Env": [f"{key}={value}" for key, value in sorted(environment.items())]},
        "HostConfig": {
            "Privileged": False,
            "ReadonlyRootfs": True,
            "NetworkMode": "none",
            "Memory": spec.memory_bytes,
            "NanoCpus": spec.nano_cpus,
            "PidsLimit": spec.pids_limit,
            "StopTimeout": spec.stop_timeout,
            "RestartPolicy": {"Name": "no"},
            "SecurityOpt": ["no-new-privileges:true"],
            "CapDrop": ["ALL"],
            "CapAdd": list(spec.cap_add),
            "LogConfig": {"Type": "none"},
            "PidMode": "",
            "IpcMode": "private",
            "UTSMode": "",
            "UsernsMode": "",
            "Devices": [],
            "DeviceRequests": [],
            "Binds": None,
            "Tmpfs": spec.tmpfs,
        },
        "State": {
            "Running": True,
            "Restarting": False,
            "Pid": 42,
            "OOMKilled": False,
        },
        "Mounts": [
            {
                "Type": "bind",
                "Source": os.fspath(source.resolve()),
                "Destination": destination,
                "RW": writable,
            }
            for destination, (source, writable) in spec.binds.items()
        ],
    }


def test_image_environment_baseline_is_duplicate_free_and_precedes_container_creation() -> None:
    document = {
        "Id": probe.MINIO_IMAGE_ID,
        "Os": "linux",
        "Architecture": probe._expected_architecture(),
        "Config": {
            "Entrypoint": ["/usr/bin/docker-entrypoint.sh"],
            "Env": ["PATH=/usr/bin", "PATH=/unreviewed"],
        },
    }

    with pytest.raises(probe.ProbeError, match=r"^PROBE_IMAGE_ENVIRONMENT_INVALID$"):
        probe.require_image(
            _OneOutputExecutor(document),
            image_id=probe.MINIO_IMAGE_ID,
            entrypoint=("/usr/bin/docker-entrypoint.sh",),
        )


@pytest.mark.parametrize(
    "entry",
    (
        "POSTGRES_PASSWORD=unexpected",
        "MINIO_ROOT_PASSWORD=unexpected",
        "MINIO_SERVER_URL=http://unexpected",
        "MC_HOST_probe=unexpected",
    ),
)
def test_image_environment_rejects_unreviewed_governed_keys_before_mutation(entry: str) -> None:
    is_postgres = entry.startswith("POSTGRES_")
    image_id = probe.POSTGRES_IMAGE_ID if is_postgres else probe.MINIO_IMAGE_ID
    entrypoint = ("docker-entrypoint.sh",) if is_postgres else ("/usr/bin/docker-entrypoint.sh",)
    prefixes = ("POSTGRES_",) if is_postgres else ("MINIO_", "MC_")
    reviewed = (
        probe.POSTGRES_REQUIRED_ENVIRONMENT if is_postgres else probe.MINIO_REQUIRED_ENVIRONMENT
    )
    document = {
        "Id": image_id,
        "Os": "linux",
        "Architecture": probe._expected_architecture(),
        "Config": {"Entrypoint": list(entrypoint), "Env": ["PATH=/usr/bin", entry]},
    }

    with pytest.raises(probe.ProbeError, match=r"^PROBE_IMAGE_ENVIRONMENT_INVALID$"):
        probe.require_image(
            _OneOutputExecutor(document),
            image_id=image_id,
            entrypoint=entrypoint,
            governed_environment_prefixes=prefixes,
            reviewed_environment_keys=frozenset(key for key, _value in reviewed),
        )


def test_probe_container_allows_only_an_equal_immutable_image_environment(
    tmp_path: Path,
) -> None:
    layout = _layout(tmp_path)
    _bundle(layout)
    name = probe.MINIO_PROBE_CONTAINER
    spec = probe._container_specs(
        layout,
        minio_image_environment=(("PATH", "/usr/bin"), ("UNRELATED", "baseline")),
    )[name]
    document = _container_document(layout, name, spec=spec)

    assert (
        probe.require_probe_container_contract(
            _OneOutputExecutor(document),
            spec=spec,
            secret_values=(b"Z" * 24,),
            require_running=True,
        )
        == "a" * 64
    )
    document["Config"]["Env"].append("OTHER=added")
    with pytest.raises(probe.ProbeError, match=r"^PROBE_CONTAINER_ENVIRONMENT_DRIFT$"):
        probe.require_probe_container_contract(
            _OneOutputExecutor(document),
            spec=spec,
            secret_values=(b"Z" * 24,),
            require_running=True,
        )


def test_probe_container_contract_accepts_only_the_exact_security_and_bind_set(
    tmp_path: Path,
) -> None:
    layout = _layout(tmp_path)
    _bundle(layout)
    name = probe.POSTGRES_PROBE_CONTAINER
    document = _container_document(layout, name)
    executor = _OneOutputExecutor(document)

    identifier = probe.require_probe_container_contract(
        executor,
        spec=probe._container_specs(layout)[name],
        secret_values=(b"Z" * 24,),
        require_running=True,
    )

    assert identifier == "a" * 64


def test_probe_container_contract_rejects_postgres_capability_expansion(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    _bundle(layout)
    name = probe.POSTGRES_PROBE_CONTAINER
    document = _container_document(layout, name)
    document["HostConfig"]["CapAdd"].append("NET_ADMIN")

    with pytest.raises(probe.ProbeError, match=r"^PROBE_CONTAINER_SECURITY_DRIFT$"):
        probe.require_probe_container_contract(
            _OneOutputExecutor(document),
            spec=probe._container_specs(layout)[name],
            secret_values=(b"Z" * 24,),
            require_running=True,
        )


def test_probe_container_contract_rejects_a_nonzero_restart_count(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    _bundle(layout)
    name = probe.POSTGRES_PROBE_CONTAINER
    document = _container_document(layout, name)
    document["RestartCount"] = 1

    with pytest.raises(probe.ProbeError, match=r"^PROBE_CONTAINER_STATE_INVALID$"):
        probe.require_probe_container_contract(
            _OneOutputExecutor(document),
            spec=probe._container_specs(layout)[name],
            secret_values=(b"Z" * 24,),
            require_running=True,
        )


def test_probe_container_contract_rejects_an_anonymous_volume(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    _bundle(layout)
    name = probe.MINIO_PROBE_CONTAINER
    document = _container_document(layout, name)
    document["Mounts"].append(
        {"Type": "volume", "Name": "anonymous", "Destination": "/fallback", "RW": True}
    )

    with pytest.raises(probe.ProbeError, match=r"^PROBE_CONTAINER_MOUNT_DRIFT$"):
        probe.require_probe_container_contract(
            _OneOutputExecutor(document),
            spec=probe._container_specs(layout)[name],
            secret_values=(b"Z" * 24,),
            require_running=True,
        )


def test_probe_container_contract_rejects_secret_material_in_inspect(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    _bundle(layout)
    name = probe.MINIO_PROBE_CONTAINER
    secret = b"future_secret_" + b"X" * 24
    document = _container_document(layout, name)
    document["Config"]["Env"].append("SECRET=" + secret.decode("ascii"))

    with pytest.raises(probe.ProbeError, match=r"^PROBE_SECRET_EXPOSURE_DETECTED$"):
        probe.require_probe_container_contract(
            _OneOutputExecutor(document),
            spec=probe._container_specs(layout)[name],
            secret_values=(secret,),
            require_running=True,
        )


@pytest.mark.parametrize(
    "extra_environment",
    (
        "MINIO_ROOT_PASSWORD=unexpected",
        "MINIO_SERVER_URL=http://unexpected",
        "MC_HOST_probe=unexpected",
    ),
)
def test_probe_container_contract_rejects_unreviewed_governed_environment(
    tmp_path: Path,
    extra_environment: str,
) -> None:
    layout = _layout(tmp_path)
    _bundle(layout)
    name = probe.MINIO_PROBE_CONTAINER
    document = _container_document(layout, name)
    document["Config"]["Env"].append(extra_environment)

    with pytest.raises(probe.ProbeError, match=r"^PROBE_CONTAINER_ENVIRONMENT_DRIFT$"):
        probe.require_probe_container_contract(
            _OneOutputExecutor(document),
            spec=probe._container_specs(layout)[name],
            secret_values=(b"Z" * 24,),
            require_running=True,
        )


def test_probe_container_contract_rejects_duplicate_environment_keys(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    _bundle(layout)
    name = probe.POSTGRES_PROBE_CONTAINER
    document = _container_document(layout, name)
    document["Config"]["Env"].append("POSTGRES_USER=conflict")

    with pytest.raises(probe.ProbeError, match=r"^PROBE_CONTAINER_ENVIRONMENT_DRIFT$"):
        probe.require_probe_container_contract(
            _OneOutputExecutor(document),
            spec=probe._container_specs(layout)[name],
            secret_values=(b"Z" * 24,),
            require_running=True,
        )


class _StoppedExecutor:
    def __init__(self, *, fail_stop: bool, secret_paths: tuple[Path, ...]) -> None:
        self.fail_stop = fail_stop
        self.secret_paths = secret_paths
        self.calls: list[tuple[str, ...]] = []

    def output(self, arguments: Any, **_kwargs: Any) -> bytes:
        command = tuple(arguments)
        self.calls.append(command)
        if command[1:2] == ("inspect",):
            assert all(path.exists() for path in self.secret_paths)
            running = self.fail_stop
            return json.dumps(
                [
                    {
                        "State": {
                            "Running": running,
                            "Restarting": False,
                            "Pid": 42 if running else 0,
                        }
                    }
                ]
            ).encode("utf-8")
        if command[1:2] == ("stop",) and self.fail_stop:
            raise probe.ProbeError("PROBE_FAILURE_STOP_FAILED")
        return b""


def test_failure_cleanup_unlinks_secrets_only_after_both_containers_are_stopped(
    tmp_path: Path,
) -> None:
    layout = _layout(tmp_path)
    bundle = _bundle(layout)
    secret_paths = (
        layout.postgres_password_file,
        layout.minio_access_file,
        layout.minio_secret_file,
    )
    executor = _StoppedExecutor(fail_stop=False, secret_paths=secret_paths)

    evidence = probe.cleanup_failure(
        executor,
        layout=layout,
        created_containers={probe.POSTGRES_PROBE_CONTAINER, probe.MINIO_PROBE_CONTAINER},
        secret_file_identities=bundle.file_identities,
    )

    assert evidence == probe.FailureCleanupEvidence(True, 3, 0)
    assert all(not path.exists() for path in secret_paths)
    assert sum(call[1:2] == ("inspect",) for call in executor.calls) == 4


def test_failure_cleanup_retains_all_secrets_when_any_stop_fails(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    bundle = _bundle(layout)
    secret_paths = (
        layout.postgres_password_file,
        layout.minio_access_file,
        layout.minio_secret_file,
    )
    executor = _StoppedExecutor(fail_stop=True, secret_paths=secret_paths)

    evidence = probe.cleanup_failure(
        executor,
        layout=layout,
        created_containers={probe.POSTGRES_PROBE_CONTAINER, probe.MINIO_PROBE_CONTAINER},
        secret_file_identities=bundle.file_identities,
    )

    assert evidence.both_containers_stopped is False
    assert evidence.secret_files_removed == 0
    assert evidence.secret_files_retained == 3
    assert evidence.classification == "PROBE_SECRET_CLEANUP_REQUIRED"
    assert all(path.exists() for path in secret_paths)


@pytest.mark.parametrize("replacement", ("regular", "symlink", "hardlink"))
def test_failure_cleanup_never_unlinks_replaced_or_linked_secret_files(
    tmp_path: Path,
    replacement: str,
) -> None:
    layout = _layout(tmp_path)
    bundle = _bundle(layout)
    target = layout.minio_access_file
    target.unlink()
    if replacement == "regular":
        target.write_bytes(b"replacement\n")
        target.chmod(0o600)
    elif replacement == "symlink":
        target.symlink_to(layout.minio_secret_file)
    else:
        os.link(layout.minio_secret_file, target)
    secret_paths = (
        layout.postgres_password_file,
        layout.minio_access_file,
        layout.minio_secret_file,
    )
    executor = _StoppedExecutor(fail_stop=False, secret_paths=secret_paths)

    evidence = probe.cleanup_failure(
        executor,
        layout=layout,
        created_containers={probe.POSTGRES_PROBE_CONTAINER, probe.MINIO_PROBE_CONTAINER},
        secret_file_identities=bundle.file_identities,
    )

    assert evidence.secret_files_removed == 0
    assert evidence.secret_files_retained == 3
    assert evidence.classification == "PROBE_SECRET_CLEANUP_REQUIRED"
    assert all(path.exists() or path.is_symlink() for path in secret_paths)


def test_unknown_cleanup_evidence_omits_all_unobserved_numeric_claims() -> None:
    evidence = probe.FailureCleanupEvidence(
        both_containers_stopped=None,
        secret_files_removed=None,
        secret_files_retained=None,
    )

    summary = evidence.summary()

    assert evidence.classification == "PROBE_SECRET_CLEANUP_REQUIRED"
    assert "both_containers_stopped_known=false" in summary
    assert "secret_files_removed_known=false" in summary
    assert "secret_files_retained_known=false" in summary
    assert "secret_files_removed=" not in summary
    assert "secret_files_retained=" not in summary


class _StopInspectFailureExecutor(_StoppedExecutor):
    def __init__(self, *, secret_paths: tuple[Path, ...]) -> None:
        super().__init__(fail_stop=False, secret_paths=secret_paths)
        self.inspect_attempts = 0

    def output(self, arguments: Any, **kwargs: Any) -> bytes:
        command = tuple(arguments)
        if command[1:2] == ("inspect",):
            self.calls.append(command)
            self.inspect_attempts += 1
            if self.inspect_attempts in {1, 2}:
                raise OSError("raw-stop-inspect-sentinel")
        return super().output(arguments, **kwargs)


def test_failure_cleanup_continues_after_stop_inspect_exception_without_false_counts(
    tmp_path: Path,
) -> None:
    layout = _layout(tmp_path)
    bundle = _bundle(layout)
    secret_paths = probe._secret_paths(layout)
    executor = _StopInspectFailureExecutor(secret_paths=secret_paths)

    evidence = probe.cleanup_failure(
        executor,
        layout=layout,
        created_containers={probe.POSTGRES_PROBE_CONTAINER, probe.MINIO_PROBE_CONTAINER},
        secret_file_identities=bundle.file_identities,
    )

    assert executor.inspect_attempts >= 2
    assert evidence.both_containers_stopped is None
    assert evidence.secret_files_removed == 0
    assert evidence.secret_files_retained == 3
    assert evidence.classification == "PROBE_SECRET_CLEANUP_REQUIRED"
    assert all(path.exists() for path in secret_paths)


class _CleanupSequenceExecutor:
    def __init__(
        self,
        inspections: dict[str, list[bytes | BaseException]],
        *,
        stop_errors: dict[str, BaseException] | None = None,
    ) -> None:
        self.inspections = inspections
        self.stop_errors = stop_errors or {}
        self.calls: list[tuple[str, ...]] = []

    def output(self, arguments: Any, **_kwargs: Any) -> bytes:
        command = tuple(arguments)
        self.calls.append(command)
        if command[1:2] == ("inspect",):
            outcome = self.inspections[command[2]].pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome
        if command[1:2] == ("stop",):
            name = command[-1]
            if name in self.stop_errors:
                raise self.stop_errors[name]
            return str(name).encode()
        raise AssertionError("unexpected cleanup command")


def _stopped_state_document(*, stopped: bool) -> bytes:
    return json.dumps(
        [
            {
                "State": {
                    "Running": not stopped,
                    "Restarting": False,
                    "Pid": 0 if stopped else 42,
                }
            }
        ]
    ).encode()


@pytest.mark.parametrize(
    ("initial_error", "stop_error", "final_stopped", "expected_stopped", "expected_removed"),
    (
        (OSError("raw-inspect-sentinel"), None, True, True, 3),
        (None, OSError("raw-stop-sentinel"), True, True, 3),
        (
            OSError("raw-inspect-sentinel"),
            OSError("raw-stop-sentinel"),
            False,
            None,
            0,
        ),
    ),
)
def test_failure_cleanup_always_final_inspects_after_ambiguous_initial_or_stop(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    initial_error: BaseException | None,
    stop_error: BaseException | None,
    final_stopped: bool,
    expected_stopped: bool | None,
    expected_removed: int,
) -> None:
    layout = _layout(tmp_path)
    bundle = _bundle(layout)
    postgres_initial = (
        initial_error if initial_error is not None else _stopped_state_document(stopped=False)
    )
    postgres_final: bytes | BaseException = (
        _stopped_state_document(stopped=True)
        if final_stopped
        else OSError("raw-final-inspect-sentinel")
    )
    executor = _CleanupSequenceExecutor(
        {
            probe.POSTGRES_PROBE_CONTAINER: [postgres_initial, postgres_final],
            probe.MINIO_PROBE_CONTAINER: [
                _stopped_state_document(stopped=True),
                _stopped_state_document(stopped=True),
            ],
        },
        stop_errors=({} if stop_error is None else {probe.POSTGRES_PROBE_CONTAINER: stop_error}),
    )

    evidence = probe.cleanup_failure(
        executor,
        layout=layout,
        created_containers={probe.POSTGRES_PROBE_CONTAINER, probe.MINIO_PROBE_CONTAINER},
        secret_file_identities=bundle.file_identities,
    )

    postgres_inspects = [
        call
        for call in executor.calls
        if call[:2] == ("docker", "inspect") and call[2] == probe.POSTGRES_PROBE_CONTAINER
    ]
    minio_inspects = [
        call
        for call in executor.calls
        if call[:2] == ("docker", "inspect") and call[2] == probe.MINIO_PROBE_CONTAINER
    ]
    postgres_stops = [
        call
        for call in executor.calls
        if call[:2] == ("docker", "stop") and call[-1] == probe.POSTGRES_PROBE_CONTAINER
    ]
    assert len(postgres_inspects) == 2
    assert len(minio_inspects) == 2
    assert len(postgres_stops) == 1
    assert evidence.both_containers_stopped is expected_stopped
    assert evidence.secret_files_removed == expected_removed
    assert evidence.secret_files_retained == (0 if expected_removed else 3)
    assert evidence.classification == (
        "PROBE_FAILURE_EVIDENCE_RETAINED" if expected_removed else "PROBE_SECRET_CLEANUP_REQUIRED"
    )
    captured = capsys.readouterr()
    assert "raw-inspect-sentinel" not in captured.out + captured.err
    assert "raw-stop-sentinel" not in captured.out + captured.err
    assert "raw-final-inspect-sentinel" not in captured.out + captured.err


def test_minio_versioning_and_object_version_json_are_structured_and_exact() -> None:
    state = json.dumps(
        {
            "status": "success",
            "url": "probe/datariver-bind-probe",
            "versioning": {"status": "Enabled", "MFADelete": "Disabled"},
        }
    ).encode("utf-8")
    listing = b"\n".join(
        (
            json.dumps(
                {
                    "status": "success",
                    "type": "file",
                    "key": "persistence.bin",
                    "versionId": "private-version-a",
                    "isDeleteMarker": False,
                }
            ).encode("utf-8"),
            json.dumps(
                {
                    "status": "success",
                    "type": "file",
                    "key": "persistence.bin",
                    "versionId": "private-version-b",
                    "isDeleteMarker": False,
                }
            ).encode("utf-8"),
        )
    )

    probe._require_minio_versioning_state(
        state,
        expected_url="probe/datariver-bind-probe",
    )
    version_ids = probe._parse_minio_object_versions(
        listing,
        expected_key="persistence.bin",
        expected_count=2,
    )

    assert set(version_ids) == {"private-version-a", "private-version-b"}


@pytest.mark.parametrize(
    "documents",
    (
        (
            {"status": "success", "type": "file", "key": "wrong", "versionId": "a"},
            {"status": "success", "type": "file", "key": "wrong", "versionId": "b"},
        ),
        (
            {
                "status": "success",
                "type": "file",
                "key": "persistence.bin",
                "versionId": "same",
            },
            {
                "status": "success",
                "type": "file",
                "key": "persistence.bin",
                "versionId": "same",
            },
        ),
        (
            {
                "status": "success",
                "type": "file",
                "key": "persistence.bin",
                "versionId": "a",
                "isDeleteMarker": True,
            },
            {
                "status": "success",
                "type": "file",
                "key": "persistence.bin",
                "versionId": "b",
            },
        ),
    ),
)
def test_minio_version_listing_rejects_wrong_duplicate_or_delete_entries(
    documents: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    payload = b"\n".join(json.dumps(document).encode("utf-8") for document in documents)

    with pytest.raises(probe.ProbeError, match=r"^MINIO_PROBE_VERSION_EVIDENCE_INVALID$"):
        probe._parse_minio_object_versions(
            payload,
            expected_key="persistence.bin",
            expected_count=2,
        )


class _RecorderLock:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def __enter__(self) -> _RecorderLock:
        self.events.append("lock.enter")
        return self

    def __exit__(self, *_arguments: Any) -> None:
        self.events.append("lock.exit")

    def require_held(self) -> None:
        self.events.append("lock.held")


class _ProbeProtocolExecutor:
    def __init__(
        self,
        events: list[str],
        *,
        injected: tuple[str, BaseException] | None = None,
        ambiguous_created_name: str | None = None,
    ) -> None:
        self.events = events
        self.injected = injected
        self.ambiguous_created_name = ambiguous_created_name
        self.calls: list[tuple[str, ...]] = []
        self.layout: Any | None = None
        self.running = {
            probe.POSTGRES_PROBE_CONTAINER: False,
            probe.MINIO_PROBE_CONTAINER: False,
        }
        self.minio_values: list[bytes] = []

    def set_forbidden(self, _values: Any) -> None:
        self.events.append("secrets.registered")

    def _inject(self, classification: str) -> None:
        if self.injected is not None and self.injected[0] == classification:
            error = self.injected[1]
            self.injected = None
            if self.ambiguous_created_name is not None:
                self.running[self.ambiguous_created_name] = True
            raise error

    def output(
        self,
        arguments: Any,
        *,
        classification: str,
        input_bytes: bytes | None = None,
        **_kwargs: Any,
    ) -> bytes:
        command = tuple(arguments)
        self.calls.append(command)
        self.events.append(classification)
        self._inject(classification)
        if command[:3] == ("docker", "image", "inspect"):
            image_id = command[3]
            entrypoint = (
                ["docker-entrypoint.sh"]
                if image_id == probe.POSTGRES_IMAGE_ID
                else ["/usr/bin/docker-entrypoint.sh"]
            )
            return json.dumps(
                [
                    {
                        "Id": image_id,
                        "Os": "linux",
                        "Architecture": probe._expected_architecture(),
                        "Config": {"Entrypoint": entrypoint, "Env": ["PATH=/usr/bin"]},
                    }
                ]
            ).encode()
        if command[:3] == ("docker", "volume", "inspect"):
            return json.dumps([{"Name": command[3], "Driver": "local"}]).encode()
        if command[:3] == ("docker", "volume", "ls"):
            return b"production-postgres\nproduction-minio\n"
        if command[:3] == ("docker", "container", "ls"):
            return b""
        if command[0] == "mount":
            return b"/dev/test on /Volumes/SSD_Mac (apfs, local, noowners)\n"
        if command[:2] == ("docker", "inspect"):
            name = command[2]
            if name == probe.POSTGRES_PRODUCTION_CONTAINER:
                return self._production_document(
                    "c" * 64,
                    probe.POSTGRES_IMAGE_ID,
                    probe.POSTGRES_PRODUCTION_VOLUME,
                    "/var/lib/postgresql/data",
                )
            if name == probe.MINIO_PRODUCTION_CONTAINER:
                return self._production_document(
                    "d" * 64,
                    probe.MINIO_IMAGE_ID,
                    probe.MINIO_PRODUCTION_VOLUME,
                    "/data",
                )
            assert self.layout is not None
            spec = probe._container_specs(
                self.layout,
                postgres_image_environment=(("PATH", "/usr/bin"),),
                minio_image_environment=(("PATH", "/usr/bin"),),
            )[name]
            document = _container_document(self.layout, name, spec=spec)
            running = self.running[name]
            document["Id"] = "a" * 64 if name == probe.POSTGRES_PROBE_CONTAINER else "b" * 64
            document["State"].update({"Running": running, "Pid": 42 if running else 0})
            return json.dumps([document]).encode()
        if command[:2] == ("docker", "create"):
            name = command[command.index("--name") + 1]
            return ("a" * 64 if name == probe.POSTGRES_PROBE_CONTAINER else "b" * 64).encode()
        if command[:2] == ("docker", "start"):
            self.running[command[2]] = True
            return str(command[2]).encode()
        if command[:2] == ("docker", "stop"):
            self.running[command[-1]] = False
            return str(command[-1]).encode()
        if command[:3] == ("docker", "container", "rm"):
            return str(command[3]).encode()
        if command[:2] == ("docker", "exec"):
            if "mc" in command and "pipe" in command:
                assert input_bytes is not None
                self.minio_values.append(input_bytes)
                return b""
            if "mc" in command and "version" in command and "info" in command:
                return json.dumps(
                    {
                        "status": "success",
                        "url": "probe/datariver-bind-probe",
                        "versioning": {"status": "Enabled", "MFADelete": "Disabled"},
                    }
                ).encode()
            if "mc" in command and "ls" in command:
                return self._version_listing()
            if "mc" in command and "cat" in command:
                version_id = command[command.index("--version-id") + 1]
                return self.minio_values[int(version_id.removeprefix("version-")) - 1]
            if "stat" in command:
                return b"999:999:700" if probe.POSTGRES_PROBE_CONTAINER in command else b"0:0:700"
            if "SELECT value" in " ".join(command):
                return b"persistent-value-v1\n"
            return b""
        raise AssertionError(f"unhandled fixed command key: {command[:3]!r}")

    def succeeds(self, arguments: Any, **_kwargs: Any) -> bool:
        self.calls.append(tuple(arguments))
        return True

    def stream_stdout(
        self,
        arguments: Any,
        *,
        destination: Path,
        classification: str,
        **_kwargs: Any,
    ) -> tuple[int, str]:
        self.calls.append(tuple(arguments))
        self.events.append(classification)
        self._inject(classification)
        payload = b"PGDMP-governed"
        destination.write_bytes(payload)
        destination.chmod(0o600)
        return len(payload), probe.hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _production_document(
        identifier: str,
        image: str,
        volume: str,
        destination: str,
    ) -> bytes:
        return json.dumps(
            [
                {
                    "Id": identifier,
                    "Image": image,
                    "State": {"Running": True},
                    "Mounts": [
                        {
                            "Type": "volume",
                            "Name": volume,
                            "Destination": destination,
                            "RW": True,
                        }
                    ],
                }
            ]
        ).encode()

    def _version_listing(self) -> bytes:
        return b"\n".join(
            json.dumps(
                {
                    "status": "success",
                    "type": "file",
                    "key": probe._MINIO_OBJECT,
                    "versionId": f"version-{index}",
                    "isDeleteMarker": False,
                }
            ).encode()
            for index in range(1, len(self.minio_values) + 1)
        )


def _run_recorded_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    injected: tuple[str, BaseException] | None = None,
    holder: dict[str, Any] | None = None,
    ambiguous_created_name: str | None = None,
) -> tuple[_ProbeProtocolExecutor, list[str], Any]:
    events: list[str] = []
    executor = _ProbeProtocolExecutor(
        events,
        injected=injected,
        ambiguous_created_name=ambiguous_created_name,
    )
    if holder is not None:
        holder["executor"] = executor
        holder["events"] = events
    original_prepare = probe.prepare_layout

    def prepare(parent: Path) -> Any:
        events.append("host.prepare")
        layout = original_prepare(parent)
        executor.layout = layout
        return layout

    monkeypatch.setattr(probe, "prepare_layout", prepare)
    monkeypatch.setattr(
        probe,
        "exclusive_docker_workflow_lock",
        lambda _root: _RecorderLock(events),
    )
    os.chmod(tmp_path, 0o700)
    result = probe.execute_probe(executor, data_parent=tmp_path / "datariver-data")
    return executor, events, result


def test_execute_probe_records_exact_governed_order_and_success_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_failure_cleanup(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("failure cleanup must not run on the PASS path")

    monkeypatch.setattr(probe, "cleanup_failure", unexpected_failure_cleanup)
    executor, events, result = _run_recorded_probe(tmp_path, monkeypatch)

    assert result.postgres_dump_bytes == len(b"PGDMP-governed")
    assert events[:2] == ["lock.enter", "lock.held"]
    assert events.index("host.prepare") > events.index("PROBE_IMAGE_INSPECT_FAILED")
    mutations = [
        call
        for call in executor.calls
        if call[:2]
        in {
            ("docker", "create"),
            ("docker", "start"),
            ("docker", "stop"),
        }
        or call[:3] == ("docker", "container", "rm")
    ]
    assert [(call[1], call[-1] if call[1] != "create" else call[3]) for call in mutations] == [
        ("create", probe.POSTGRES_PROBE_CONTAINER),
        ("start", probe.POSTGRES_PROBE_CONTAINER),
        ("stop", probe.POSTGRES_PROBE_CONTAINER),
        ("start", probe.POSTGRES_PROBE_CONTAINER),
        ("stop", probe.POSTGRES_PROBE_CONTAINER),
        ("create", probe.MINIO_PROBE_CONTAINER),
        ("start", probe.MINIO_PROBE_CONTAINER),
        ("stop", probe.MINIO_PROBE_CONTAINER),
        ("start", probe.MINIO_PROBE_CONTAINER),
        ("stop", probe.MINIO_PROBE_CONTAINER),
        ("container", probe.POSTGRES_PROBE_CONTAINER),
        ("container", probe.MINIO_PROBE_CONTAINER),
    ]
    assert events.count("PRODUCTION_CONTAINER_INSPECT_FAILED") == 6
    assert events.count("PRODUCTION_VOLUME_INSPECT_FAILED") == 6
    assert events.count("DOCKER_VOLUME_LIST_FAILED") == 3
    assert events[-1] == "lock.exit"
    assert not (tmp_path / "datariver-data").exists()


@pytest.mark.parametrize(
    "classification",
    (
        "PRODUCTION_CONTAINER_INSPECT_FAILED",
        "DOCKER_VOLUME_LIST_FAILED",
        "PROBE_CONTAINER_ABSENCE_CHECK_FAILED",
        "PROBE_IMAGE_INSPECT_FAILED",
    ),
)
def test_execute_probe_pre_mutation_gates_fail_before_any_create_or_host_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    classification: str,
) -> None:
    holder: dict[str, Any] = {}
    with pytest.raises(probe.ProbeError, match=f"^{classification}$"):
        _run_recorded_probe(
            tmp_path,
            monkeypatch,
            injected=(classification, probe.ProbeError(classification)),
            holder=holder,
        )

    assert not (tmp_path / "datariver-data").exists()
    executor = holder["executor"]
    assert not any(
        call[:2] in {("docker", "create"), ("docker", "start"), ("docker", "stop")}
        or call[:3] == ("docker", "container", "rm")
        for call in executor.calls
    )
    assert holder["events"][-1] == "lock.exit"


def test_execute_probe_tracks_ambiguous_daemon_creation_before_client_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    holder: dict[str, Any] = {}
    cleanup_calls = 0
    original_cleanup = probe.cleanup_failure

    def cleanup(*args: Any, **kwargs: Any) -> Any:
        nonlocal cleanup_calls
        cleanup_calls += 1
        return original_cleanup(*args, **kwargs)

    monkeypatch.setattr(probe, "cleanup_failure", cleanup)
    with pytest.raises(probe.ProbeError, match=r"^PROBE_INTERNAL_FAILURE$"):
        _run_recorded_probe(
            tmp_path,
            monkeypatch,
            injected=(
                "POSTGRES_PROBE_CREATE_FAILED",
                OSError("raw-create-timeout-sentinel"),
            ),
            holder=holder,
            ambiguous_created_name=probe.POSTGRES_PROBE_CONTAINER,
        )

    executor = holder["executor"]
    postgres_inspects = [
        call
        for call in executor.calls
        if call[:2] == ("docker", "inspect") and call[2] == probe.POSTGRES_PROBE_CONTAINER
    ]
    postgres_stops = [
        call
        for call in executor.calls
        if call[:2] == ("docker", "stop") and call[-1] == probe.POSTGRES_PROBE_CONTAINER
    ]
    captured = capsys.readouterr().err
    assert cleanup_calls == 1
    assert len(postgres_inspects) == 2
    assert len(postgres_stops) == 1
    assert not any(call[:3] == ("docker", "container", "rm") for call in executor.calls)
    assert "secret_files_removed=0" in captured
    assert "secret_files_retained=3" in captured
    assert "production_identity_unchanged=true" in captured
    assert "production_volumes_unchanged=true" in captured
    assert "raw-create-timeout-sentinel" not in captured


@pytest.mark.parametrize(
    ("error", "expected"),
    (
        (probe.ProbeError("MINIO_PROBE_SECOND_WRITE_FAILED"), "MINIO_PROBE_SECOND_WRITE_FAILED"),
        (OSError("raw-provider-sentinel"), "PROBE_INTERNAL_FAILURE"),
        (RuntimeError("raw-programming-sentinel"), "PROBE_INTERNAL_FAILURE"),
        (KeyboardInterrupt("raw-interrupt-sentinel"), None),
    ),
)
def test_execute_probe_mutation_failures_use_one_cleanup_and_recheck_production(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: BaseException,
    expected: str | None,
) -> None:
    holder: dict[str, Any] = {}
    cleanup_calls = 0
    production_rechecks = 0
    volume_checks = 0
    original_cleanup = probe.cleanup_failure
    original_production_recheck = probe.require_production_unchanged
    original_volume_names = probe._volume_names

    def cleanup(*args: Any, **kwargs: Any) -> Any:
        nonlocal cleanup_calls
        cleanup_calls += 1
        return original_cleanup(*args, **kwargs)

    def production_recheck(*args: Any, **kwargs: Any) -> Any:
        nonlocal production_rechecks
        production_rechecks += 1
        return original_production_recheck(*args, **kwargs)

    def volume_names(*args: Any, **kwargs: Any) -> Any:
        nonlocal volume_checks
        volume_checks += 1
        return original_volume_names(*args, **kwargs)

    monkeypatch.setattr(probe, "cleanup_failure", cleanup)
    monkeypatch.setattr(probe, "require_production_unchanged", production_recheck)
    monkeypatch.setattr(probe, "_volume_names", volume_names)
    if isinstance(error, probe.ProbeError):
        injection = (str(error), error)
    else:
        injection = ("MINIO_PROBE_SECOND_WRITE_FAILED", error)

    if expected is None:
        with pytest.raises(KeyboardInterrupt):
            _run_recorded_probe(tmp_path, monkeypatch, injected=injection, holder=holder)
    else:
        with pytest.raises(probe.ProbeError, match=f"^{expected}$"):
            _run_recorded_probe(tmp_path, monkeypatch, injected=injection, holder=holder)

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "raw-provider-sentinel" not in combined
    assert "raw-programming-sentinel" not in combined
    assert "raw-interrupt-sentinel" not in combined
    assert combined.count("PROBE_FAILURE_EVIDENCE_RETAINED") == 1
    assert "production_identity_unchanged=true" in combined
    assert "production_volumes_unchanged=true" in combined
    assert cleanup_calls == 1
    assert production_rechecks == 1
    assert volume_checks == 2
    executor = holder["executor"]
    stop_calls = [call for call in executor.calls if call[:2] == ("docker", "stop")]
    remove_calls = [call for call in executor.calls if call[:3] == ("docker", "container", "rm")]
    assert (
        stop_calls.count(
            (
                "docker",
                "stop",
                "--time",
                str(probe.MINIO_STOP_TIMEOUT_SECONDS),
                probe.MINIO_PROBE_CONTAINER,
            )
        )
        == 1
    )
    assert remove_calls == []
    assert executor.layout is not None
    assert executor.layout.leaf.is_dir()
    assert all(not path.exists() for path in probe._secret_paths(executor.layout))


@pytest.mark.parametrize(
    (
        "classification",
        "expected_creates",
        "expected_stops",
        "expected_removes",
        "expected_removed",
        "expected_retained",
    ),
    (
        ("POSTGRES_PROBE_START_FAILED", 1, 0, 0, 0, 3),
        ("MINIO_PROBE_START_FAILED", 2, 2, 0, 3, 0),
        ("MINIO_PROBE_SECOND_WRITE_FAILED", 2, 3, 0, 3, 0),
        ("PROBE_CONTAINER_REMOVE_FAILED", 2, 4, 1, 3, 0),
    ),
)
def test_execute_probe_recorder_covers_each_mutation_failure_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    classification: str,
    expected_creates: int,
    expected_stops: int,
    expected_removes: int,
    expected_removed: int,
    expected_retained: int,
) -> None:
    holder: dict[str, Any] = {}
    cleanup_calls = 0
    original_cleanup = probe.cleanup_failure

    def cleanup(*args: Any, **kwargs: Any) -> Any:
        nonlocal cleanup_calls
        cleanup_calls += 1
        return original_cleanup(*args, **kwargs)

    monkeypatch.setattr(probe, "cleanup_failure", cleanup)
    with pytest.raises(probe.ProbeError, match=f"^{classification}$"):
        _run_recorded_probe(
            tmp_path,
            monkeypatch,
            injected=(classification, probe.ProbeError(classification)),
            holder=holder,
        )

    executor = holder["executor"]
    create_calls = [call for call in executor.calls if call[:2] == ("docker", "create")]
    stop_calls = [call for call in executor.calls if call[:2] == ("docker", "stop")]
    remove_calls = [call for call in executor.calls if call[:3] == ("docker", "container", "rm")]
    captured = capsys.readouterr().err
    assert cleanup_calls == 1
    assert len(create_calls) == expected_creates
    assert len(stop_calls) == expected_stops
    assert len(remove_calls) == expected_removes
    assert f"secret_files_removed={expected_removed}" in captured
    assert f"secret_files_retained={expected_retained}" in captured
    assert "production_identity_unchanged=true" in captured
    assert "production_volumes_unchanged=true" in captured
    assert executor.layout is not None
    assert executor.layout.leaf.is_dir()


def test_execute_probe_host_pass_cleanup_failure_excludes_failure_cleanup_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    holder: dict[str, Any] = {}
    cleanup_failure_calls = 0
    original_failure_cleanup = probe.cleanup_failure

    def fail_pass_cleanup(_layout: Any) -> None:
        raise OSError("raw-pass-cleanup-sentinel")

    def failure_cleanup(*args: Any, **kwargs: Any) -> Any:
        nonlocal cleanup_failure_calls
        cleanup_failure_calls += 1
        return original_failure_cleanup(*args, **kwargs)

    monkeypatch.setattr(probe, "cleanup_success", fail_pass_cleanup)
    monkeypatch.setattr(probe, "cleanup_failure", failure_cleanup)
    with pytest.raises(probe.ProbeError, match=r"^PROBE_INTERNAL_FAILURE$"):
        _run_recorded_probe(tmp_path, monkeypatch, holder=holder)

    executor = holder["executor"]
    remove_calls = [call for call in executor.calls if call[:3] == ("docker", "container", "rm")]
    captured = capsys.readouterr().err
    assert cleanup_failure_calls == 1
    assert len(remove_calls) == 2
    assert "PROBE_SECRET_CLEANUP_REQUIRED" in captured
    assert "raw-pass-cleanup-sentinel" not in captured
    assert "production_identity_unchanged=true" in captured
    assert "production_volumes_unchanged=true" in captured
    assert executor.layout is not None
    assert executor.layout.leaf.is_dir()


def test_execute_probe_cleanup_exception_after_partial_unlink_reports_unknown_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    holder: dict[str, Any] = {}

    def partial_cleanup(
        _executor: Any,
        *,
        layout: Any,
        **_kwargs: Any,
    ) -> Any:
        assert layout is not None
        layout.postgres_password_file.unlink()
        raise OSError("raw-cleanup-sentinel")

    monkeypatch.setattr(probe, "cleanup_failure", partial_cleanup)
    with pytest.raises(probe.ProbeError, match=r"^MINIO_PROBE_SECOND_WRITE_FAILED$"):
        _run_recorded_probe(
            tmp_path,
            monkeypatch,
            injected=(
                "MINIO_PROBE_SECOND_WRITE_FAILED",
                probe.ProbeError("MINIO_PROBE_SECOND_WRITE_FAILED"),
            ),
            holder=holder,
        )

    captured = capsys.readouterr().err
    assert "PROBE_SECRET_CLEANUP_REQUIRED" in captured
    assert "both_containers_stopped_known=false" in captured
    assert "secret_files_removed_known=false" in captured
    assert "secret_files_retained_known=false" in captured
    assert "secret_files_removed=" not in captured
    assert "secret_files_retained=" not in captured
    assert "raw-cleanup-sentinel" not in captured
    assert "production_identity_unchanged=true" in captured
    assert "production_volumes_unchanged=true" in captured


def test_main_maps_a_cleaned_operator_interrupt_to_a_fixed_safe_exit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        probe,
        "_parse_args",
        lambda: type("Arguments", (), {"confirm": probe.CONFIRMATION})(),
    )

    def interrupted(_executor: Any) -> Any:
        raise KeyboardInterrupt("raw-interrupt-sentinel")

    monkeypatch.setattr(probe, "execute_probe", interrupted)

    assert probe.main() == 130
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "ERROR: PROBE_OPERATOR_INTERRUPT\n"
    assert "raw-interrupt-sentinel" not in captured.err


def test_production_container_or_volume_identity_change_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = probe.ProductionIdentity("a" * 64, "b" * 64, "c" * 64, "d" * 64)
    changed = probe.ProductionIdentity("e" * 64, "b" * 64, "c" * 64, "d" * 64)
    monkeypatch.setattr(probe, "capture_production_identity", lambda _executor: changed)

    with pytest.raises(probe.ProbeError, match=r"^PRODUCTION_IDENTITY_CHANGED$"):
        probe.require_production_unchanged(object(), baseline)


def test_confirmation_token_is_fixed_and_runtime_probe_is_not_a_daily_interface() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")

    assert probe.CONFIRMATION == "SEC-DURABLE-BIND-PROBE-001-A"
    assert "--confirm" in source
    assert "dev-publish" not in source
    assert "prep-update" not in source
