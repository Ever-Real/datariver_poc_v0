from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
MODULE_PATH = SCRIPTS / "development_cycle.py"


def _load_module() -> ModuleType:
    previous_platform_module = sys.modules.get("platform_workflow")
    sys.path.insert(0, str(SCRIPTS))
    try:
        specification = importlib.util.spec_from_file_location(
            "development_cycle_for_test",
            MODULE_PATH,
        )
        assert specification is not None
        assert specification.loader is not None
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS))
        if previous_platform_module is None:
            sys.modules.pop("platform_workflow", None)
        else:
            sys.modules["platform_workflow"] = previous_platform_module


cycle = _load_module()


@pytest.mark.parametrize(
    "remote_url",
    (
        "https://github.com/Ever-Real/datariver_v1.git",
        "git@github.com:Ever-Real/datariver_v1.git",
        "ssh://git@github.com/Ever-Real/datariver_v1.git",
    ),
)
def test_expected_ever_real_origin_is_accepted(remote_url: str) -> None:
    cycle.validate_origin_url(remote_url)


@pytest.mark.parametrize(
    "remote_url",
    (
        "https://github.com/JayJin/datariver_v1.git",
        "https://token@github.com/Ever-Real/datariver_v1.git",
        "http://github.com/Ever-Real/datariver_v1.git",
        "https://github.com/Ever-Real/another-repository.git",
    ),
)
def test_unapproved_origin_is_rejected(remote_url: str) -> None:
    with pytest.raises(cycle.DevelopmentCycleError):
        cycle.validate_origin_url(remote_url)


def test_preparation_bootstrap_preserves_selected_operator_modes(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.wsl-intranet-development"
    command = tuple(
        str(value)
        for value in cycle.preparation_bootstrap_command(
            env_file,
            {
                "DATAHUB_BASE_URL": "http://127.0.0.1:8080",
                "INTRANET_SOURCE_HOST_ENABLED": "true",
                "APP_PUBLIC_ORIGIN": "https://datariver.example.internal",
                "OIDC_PUBLIC_ORIGIN": "https://identity.example.internal",
                "AIRFLOW_SOURCE_API_BRIDGE_ENABLED": "true",
                "KNOWLEDGE_SOURCE_WORKER_ENABLED": "true",
            },
        )
    )

    assert command[-7:] == (
        "--intranet-source-host",
        "--web-public-origin",
        "https://datariver.example.internal",
        "--oidc-public-origin",
        "https://identity.example.internal",
        "--source-host-airflow-bridge",
        "--enable-knowledge-source-worker",
    )
    assert "DATAHUB_BASE_URL" not in command


def test_preparation_boolean_must_be_explicit() -> None:
    with pytest.raises(cycle.DevelopmentCycleError):
        cycle.env_bool({"NEO4J_PROJECTION_ENABLED": "yes"}, "NEO4J_PROJECTION_ENABLED")


def test_environment_schema_hash_never_depends_on_values() -> None:
    first = cycle.environment_schema_sha256({"PUBLIC_KEY": "one", "SECRET_REF": "secret-a"})
    second = cycle.environment_schema_sha256({"PUBLIC_KEY": "different", "SECRET_REF": "secret-b"})

    assert first == second
    assert first != cycle.environment_schema_sha256({"PUBLIC_KEY": "one"})


def test_selected_topology_contains_only_bounded_switches() -> None:
    topology = cycle.selected_topology(
        {
            "DATARIVER_OPERATOR_PROFILE": "wsl-intranet-development",
            "NEO4J_PROJECTION_ENABLED": "true",
            "DATAHUB_SECRET_REF": "file:/run/secrets/datahub_token",
        }
    )

    assert topology["operator_profile"] == "wsl-intranet-development"
    features = topology["features"]
    assert isinstance(features, dict)
    assert features["NEO4J_PROJECTION_ENABLED"] is True
    assert features["INTRANET_OPENAI_COMPATIBLE_CHAT_ENABLED"] is False
    assert "DATAHUB_SECRET_REF" not in str(topology)


class _FakePreflightRunner:
    def __init__(self, output: str) -> None:
        self.output_document = output
        self.reveal_failure_output: bool | None = None

    def output(self, _arguments: object, *, reveal_failure_output: bool = True) -> str:
        self.reveal_failure_output = reveal_failure_output
        return self.output_document


def test_preflight_capture_logs_only_allowlisted_capabilities(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = _FakePreflightRunner(
        """{
          "environment_file": "/home/operator/.env.wsl-intranet-development",
          "knowledge_source_analysis": "CONFIGURED",
          "local_inference_source_host": false,
          "neo4j_projection": "CONFIGURED",
          "neo4j_endpoint": {
            "expected_source_host_port": "17687",
            "host": "127.0.0.1",
            "port": 17687,
            "scheme": "bolt",
            "credential": "must-not-survive"
          },
          "runtime_activation": false,
          "future_secret": "must-not-survive"
        }"""
    )
    evidence = cycle.capture_source_host_preflight(runner, tmp_path / ".env")
    captured = capsys.readouterr()

    exposed = captured.out + captured.err + repr(evidence)
    for sensitive in (
        "environment_file",
        "/home/operator/.env.wsl-intranet-development",
        "credential",
        "must-not-survive",
        "future_secret",
    ):
        assert sensitive not in exposed
    assert runner.reveal_failure_output is False
    assert json.loads(captured.out.strip()) == evidence
    assert captured.err == ""


def test_invalid_preflight_capture_never_echoes_raw_content(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = _FakePreflightRunner(
        '{"credential":"secret-value","environment_file":"/private/operator.env"}'
    )

    with pytest.raises(cycle.DevelopmentCycleError) as captured_error:
        cycle.capture_source_host_preflight(runner, tmp_path / ".env")
    captured = capsys.readouterr()

    exposed = captured.out + captured.err + str(captured_error.value)
    assert "secret-value" not in exposed
    assert "/private/operator.env" not in exposed
    assert runner.reveal_failure_output is False
    assert captured.out == ""
    assert captured.err == ""


def test_preflight_subprocess_failure_suppresses_captured_raw_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_run(*_args: object, **_kwargs: object) -> None:
        raise cycle.subprocess.CalledProcessError(
            2,
            ["dev_host"],
            output='{"credential":"secret-value"}',
            stderr='{"environment_file":"/private/operator.env"}',
        )

    monkeypatch.setattr(cycle.subprocess, "run", fail_run)
    with pytest.raises(cycle.DevelopmentCycleError) as captured_error:
        cycle.capture_source_host_preflight(cycle.Runner(root=tmp_path), tmp_path / ".env")
    captured = capsys.readouterr()

    exposed = captured.out + captured.err + str(captured_error.value)
    assert "credential" not in exposed
    assert "secret-value" not in exposed
    assert "/private/operator.env" not in exposed


@pytest.mark.parametrize("output", ("0095 (head)\n0094 (head)", "0095", "other (head)"))
def test_alembic_head_must_be_sole_and_match_packaged_revision(output: str) -> None:
    with pytest.raises(cycle.DevelopmentCycleError):
        cycle.parse_sole_alembic_head(output, required_revision="0095")


def test_alembic_head_accepts_the_packaged_sole_revision() -> None:
    assert cycle.parse_sole_alembic_head("0095 (head)\n", required_revision="0095") == "0095"


def _readiness_evidence(commit: str = "a" * 40) -> dict[str, object]:
    return {
        "contract": cycle.READINESS_CONTRACT,
        "evidence_scope": "last-successful-preparation-readiness",
        "source": {
            "branch": "dev",
            "commit": commit,
            "origin_dev_commit": commit,
            "origin_repository": "github.com/Ever-Real/datariver_v1",
        },
        "platform": {},
        "locks": {},
        "toolchain": {},
        "environment": {},
        "topology": {},
        "database": {},
        "capabilities": {},
        "health": {"api": {"status": 200}},
    }


def test_readiness_manifest_is_private_and_timestamp_is_not_runtime_state(tmp_path: Path) -> None:
    manifest = tmp_path / "runtime" / "amd64-readiness.json"
    evidence = _readiness_evidence()

    cycle.write_readiness_manifest(evidence, manifest)

    assert stat.S_IMODE(manifest.stat().st_mode) == 0o600
    cycle.verify_readiness_manifest(evidence, manifest)
    with pytest.raises(cycle.DevelopmentCycleError):
        cycle.verify_readiness_manifest(_readiness_evidence("b" * 40), manifest)


def test_failed_atomic_replace_preserves_last_successful_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = tmp_path / "runtime" / "amd64-readiness.json"
    cycle.write_readiness_manifest(_readiness_evidence(), manifest)
    previous = manifest.read_bytes()

    def fail_replace(_source: str | os.PathLike[str], _target: str | os.PathLike[str]) -> None:
        raise OSError("simulated atomic replace failure")

    monkeypatch.setattr(cycle.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated atomic replace failure"):
        cycle.write_readiness_manifest(_readiness_evidence("b" * 40), manifest)

    assert manifest.read_bytes() == previous
    assert list(manifest.parent.glob(".amd64-readiness.json.*")) == []


def test_missing_readiness_manifest_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(cycle.DevelopmentCycleError, match="Run prep-update"):
        cycle.verify_readiness_manifest(_readiness_evidence(), tmp_path / "missing.json")
