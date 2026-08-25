from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
MODULE_PATH = SCRIPTS / "prep39083_deploy.py"


def _load_module() -> ModuleType:
    sys.path.insert(0, os.fspath(SCRIPTS))
    try:
        specification = importlib.util.spec_from_file_location(
            "prep39083_deploy_for_test",
            MODULE_PATH,
        )
        assert specification is not None
        assert specification.loader is not None
        module = importlib.util.module_from_spec(specification)
        sys.modules[specification.name] = module
        specification.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(os.fspath(SCRIPTS))


deploy = _load_module()


def _operator_values() -> dict[str, str]:
    contract = json.loads((ROOT / "deploy/prep39083/env-contract.json").read_text())
    return {
        key: {
            "POC_PUBLIC_ORIGIN": "https://prep39083.example.test",
            "POC_K9_STUDIO_DATABASE_URL": "postgres://readonly@studio.example.test/studio",
        }.get(key, f"configured-{key.lower()}")
        for key in contract["operator_required"]
    } | {"HTTP_PROXY": "", "HTTPS_PROXY": "", "NO_PROXY": "corp.internal"}


def _write_private_env(path: Path, values: dict[str, str]) -> bytes:
    payload = "".join(f"{key}={value}\n" for key, value in values.items()).encode()
    path.write_bytes(payload)
    path.chmod(0o600)
    return payload


def _release() -> object:
    return deploy.ReleaseIdentity("a" * 40, "b" * 40, "linux/amd64", 39083, "datariver-prep39083")


def test_operator_environment_is_preserved_and_generated_secrets_are_stable(tmp_path: Path) -> None:
    operator = tmp_path / ".env.prep"
    runtime = tmp_path / ".env.prep.runtime"
    original = _write_private_env(operator, _operator_values())
    generated = iter(("postgres-secret", "neo4j-secret", "mcp-secret"))

    first = deploy.reconcile_environment(
        _release(),
        operator_path=operator,
        optional_path=tmp_path / ".env.prep.optional",
        runtime_path=runtime,
        random_token=lambda _count: next(generated),
    )
    second = deploy.reconcile_environment(
        _release(),
        operator_path=operator,
        optional_path=tmp_path / ".env.prep.optional",
        runtime_path=runtime,
        random_token=lambda _count: pytest.fail("stable runtime secret must be reused"),
    )

    assert operator.read_bytes() == original
    assert first.runtime["POC_POSTGRES_PASSWORD"] == "postgres-secret"
    assert first.runtime["NEO4J_PASSWORD"] == "neo4j-secret"
    assert first.runtime["POC_MCP_SERVICE_TOKEN"] == "mcp-secret"
    assert second.runtime == first.runtime
    assert stat.S_IMODE(runtime.stat().st_mode) == 0o600
    assert first.effective["POC_IMAGE_TAG"] == "a" * 40
    assert first.effective["POC_SOURCE_COMMIT"] == "a" * 40


def test_legacy_generated_secret_is_migrated_without_overwriting_operator_file(
    tmp_path: Path,
) -> None:
    operator = tmp_path / ".env.prep"
    values = _operator_values() | {"POC_POSTGRES_PASSWORD": "preserved-volume-password"}
    original = _write_private_env(operator, values)
    runtime = tmp_path / ".env.prep.runtime"
    generated = iter(("neo4j-secret", "mcp-secret"))

    bundle = deploy.reconcile_environment(
        _release(),
        operator_path=operator,
        optional_path=tmp_path / ".env.prep.optional",
        runtime_path=runtime,
        random_token=lambda _count: next(generated),
    )

    assert operator.read_bytes() == original
    assert bundle.runtime["POC_POSTGRES_PASSWORD"] == "preserved-volume-password"
    assert any("POC_POSTGRES_PASSWORD" in warning for warning in bundle.warnings)


def test_required_external_keys_fail_with_names_only(tmp_path: Path) -> None:
    operator = tmp_path / ".env.prep"
    _write_private_env(operator, _operator_values() | {"DATAHUB_GMS_TOKEN": "CHANGE_ME_TOKEN"})

    with pytest.raises(deploy.PrepError) as captured:
        deploy.reconcile_environment(
            _release(),
            operator_path=operator,
            optional_path=tmp_path / ".env.prep.optional",
            runtime_path=tmp_path / ".env.prep.runtime",
        )

    assert captured.value.code == "PREP_REQUIRED_EXTERNAL_CONFIG_MISSING"
    assert "DATAHUB_GMS_TOKEN" in captured.value.reason
    assert "CHANGE_ME_TOKEN" not in captured.value.reason


def test_optional_mcl_profile_is_not_required(tmp_path: Path) -> None:
    operator = tmp_path / ".env.prep"
    _write_private_env(operator, _operator_values())
    bundle = deploy.reconcile_environment(
        _release(),
        operator_path=operator,
        optional_path=tmp_path / ".env.prep.optional",
        runtime_path=tmp_path / ".env.prep.runtime",
        random_token=lambda count: "x" * count,
    )
    assert bundle.optional == {}
    assert bundle.effective["POC_CHANGE_HISTORY_SCHEDULER_ENABLED"] == "false"
    assert "POC_MCL_KAFKA_BROKERS" not in bundle.effective


def test_proxy_is_injected_once_with_lowercase_and_required_no_proxy(tmp_path: Path) -> None:
    operator = tmp_path / ".env.prep"
    values = _operator_values() | {
        "HTTP_PROXY": "http://proxy.example.test:8080",
        "HTTPS_PROXY": "http://secure-proxy.example.test:8443",
        "NO_PROXY": "corp.internal,localhost",
    }
    _write_private_env(operator, values)
    bundle = deploy.reconcile_environment(
        _release(),
        operator_path=operator,
        optional_path=tmp_path / ".env.prep.optional",
        runtime_path=tmp_path / ".env.prep.runtime",
        random_token=lambda count: "x" * count,
    )
    assert bundle.effective["http_proxy"] == values["HTTP_PROXY"]
    assert bundle.effective["https_proxy"] == values["HTTPS_PROXY"]
    no_proxy = bundle.effective["NO_PROXY"].split(",")
    assert no_proxy.count("localhost") == 1
    assert {"127.0.0.1", "pgvector", "redis", "neo4j", "web"} <= set(no_proxy)
    child = deploy.child_environment(bundle.effective)
    assert child["HTTPS_PROXY"] == child["https_proxy"]
    assert child["NO_PROXY"] == child["no_proxy"]


def test_image_reference_is_resolved_without_shell_state() -> None:
    assert deploy.resolve_web_image({"services": {"web": {"image": "datariver-poc:" + "a" * 40}}})
    with pytest.raises(deploy.PrepError) as captured:
        deploy.resolve_web_image({"services": {"web": {"image": ""}}})
    assert captured.value.code == "PREP_WEB_IMAGE_REF_EMPTY"
    assert "IMAGE_REF" in captured.value.action


def test_postgres_contract_matches_or_returns_classified_credential_failure() -> None:
    valid = {
        "services": {
            "web": {"environment": {
                "POC_POSTGRES_DB": "poc",
                "POC_POSTGRES_USER": "poc",
                "POC_POSTGRES_PASSWORD": "secret",
            }},
            "pgvector": {"environment": {
                "POSTGRES_DB": "poc",
                "POSTGRES_USER": "poc",
                "POSTGRES_PASSWORD": "secret",
            }},
        },
    }
    deploy.validate_postgres_contract(valid)
    invalid = json.loads(json.dumps(valid))
    invalid["services"]["web"]["environment"]["POC_POSTGRES_PASSWORD"] = "drift"
    with pytest.raises(deploy.PrepError) as captured:
        deploy.validate_postgres_contract(invalid)
    assert captured.value.code == "PREP_LOCAL_DB_CREDENTIAL_MISMATCH"

    completed = subprocess.CompletedProcess(
        ["docker", "compose", "run"],
        2,
        stdout="",
        stderr='{"code":"PREP_LOCAL_DB_CREDENTIAL_MISMATCH","sqlstate":"28P01"}',
    )
    classified = deploy.classify_bootstrap_failure(
        deploy.CommandFailure(completed.args, completed),
    )
    assert classified.code == "PREP_LOCAL_DB_CREDENTIAL_MISMATCH"
    assert "28P01" not in classified.reason


def test_deployer_never_destroys_accepted_persistent_volumes() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    forbidden = (
        "docker compose down -v",
        "docker volume rm",
        '"down", "-v"',
        '"volume", "rm"',
        "ALTER ROLE",
    )
    assert not any(value in source for value in forbidden)
    assert "PREP_LOCAL_DB_CREDENTIAL_MISMATCH" in source
    assert "accepted.json" in source
    assert '"run",\n            "--rm",\n            "--no-deps"' in source
    assert '"up", "-d", "--wait", "pgvector", "neo4j", "redis"' in source
    assert '"up", "-d", "--no-build", "--wait", "web"' in source
    assert source.index('"pgvector", "neo4j", "redis"') < source.index(
        '"--no-build", "--wait", "web"',
    )
    assert "snapshot_39080" in source


def test_uncaught_child_failure_is_sanitized_at_the_cli_boundary() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "except CommandFailure:" in source
    assert "secrets and raw command " in source
    assert "output were suppressed" in source
    assert "except (EOFError, KeyboardInterrupt):" in source


def test_wrapper_uses_uv_and_never_sources_operator_environment() -> None:
    source = (ROOT / "scripts/prep39083").read_text(encoding="utf-8")
    assert "uv run --frozen python scripts/prep39083_deploy.py" in source
    assert "source " not in source
    assert "HTTP_PROXY" in source and "http_proxy" in source


def test_wrapper_injects_proxy_into_uv_without_operator_duplication(tmp_path: Path) -> None:
    root = tmp_path / "checkout"
    (root / "scripts").mkdir(parents=True)
    (root / "deploy/prep39083").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts/prep39083", root / "scripts/prep39083")
    operator = root / "deploy/prep39083/.env.prep"
    operator.write_text(
        "HTTP_PROXY=http://proxy.example.test:8080\n"
        "HTTPS_PROXY=http://secure-proxy.example.test:8443\n"
        "NO_PROXY=corp.internal\n",
        encoding="utf-8",
    )
    operator.chmod(0o600)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        "#!/bin/sh\n"
        "test \"$HTTP_PROXY\" = \"$http_proxy\"\n"
        "test \"$HTTPS_PROXY\" = \"$https_proxy\"\n"
        "test \"$NO_PROXY\" = \"$no_proxy\"\n"
        "test \"$1 $2 $3 $4\" = \"run --frozen python scripts/prep39083_deploy.py\"\n",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)

    completed = subprocess.run(  # noqa: S603 - fixed private temporary executable.
        [root / "scripts/prep39083", "doctor"],
        cwd=root,
        env={"PATH": f"{fake_bin}:/usr/bin:/bin"},
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert completed.stdout == completed.stderr == ""


def test_docker_proxy_is_step_local_and_not_an_image_environment() -> None:
    dockerfile = (ROOT / "deploy/poc/Dockerfile.example").read_text(encoding="utf-8")
    compose = (ROOT / "deploy/poc/docker-compose.poc.yaml").read_text(encoding="utf-8")
    assert "ARG HTTP_PROXY" not in dockerfile
    assert "ARG HTTPS_PROXY" not in dockerfile
    assert "NPM_CONFIG_USERCONFIG=/tmp/datariver-npmrc" in dockerfile
    assert "npm config set strict-ssl false" in dockerfile
    assert "npm config set strict-ssl true" in dockerfile
    assert 'rm -f "${NPM_CONFIG_USERCONFIG}"' in dockerfile
    assert "HTTP_PROXY: ${HTTP_PROXY:-}" in compose
    assert "HTTPS_PROXY: ${HTTPS_PROXY:-}" in compose
    assert "NO_PROXY: ${NO_PROXY:-}" in compose
