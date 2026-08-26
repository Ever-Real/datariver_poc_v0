from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import replace
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


def _operator_values(*, k9_configured: bool = True) -> dict[str, str]:
    contract = json.loads((ROOT / "deploy/prep39083/env-contract.json").read_text())
    values = {
        key: {
            "POC_PUBLIC_ORIGIN": "https://prep39083.example.test",
        }.get(key, f"configured-{key.lower()}")
        for key in contract["ownership"]["CORE_REQUIRED"]
    } | {"HTTP_PROXY": "", "HTTPS_PROXY": "", "NO_PROXY": "corp.internal"}
    values["POC_K9_STUDIO_DATABASE_URL"] = (
        "postgres://readonly@studio.example.test/studio" if k9_configured else ""
    )
    return values


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


def test_k9_studio_authority_is_feature_dependent_not_core_required(tmp_path: Path) -> None:
    operator = tmp_path / ".env.prep"
    _write_private_env(operator, _operator_values(k9_configured=False))
    deferred = deploy.reconcile_environment(
        _release(),
        operator_path=operator,
        optional_path=tmp_path / ".env.prep.optional",
        runtime_path=tmp_path / ".env.prep.runtime",
        random_token=lambda count: "x" * count,
    )
    assert deferred.k9_mode == "DEFERRED"
    assert deferred.effective["POC_K9_SCHEDULER_ENABLED"] == "false"

    _write_private_env(operator, _operator_values(k9_configured=True))
    configured = deploy.reconcile_environment(
        _release(),
        operator_path=operator,
        optional_path=tmp_path / ".env.prep.optional",
        runtime_path=tmp_path / ".env.prep.runtime",
        random_token=lambda count: pytest.fail("existing generated secrets must be reused"),
    )
    assert configured.k9_mode == "REQUIRED"
    assert configured.effective["POC_K9_SCHEDULER_ENABLED"] == "true"


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
    assert bundle.effective["POC_RUNTIME_HTTP_PROXY"] == ""
    assert bundle.effective["POC_RUNTIME_HTTPS_PROXY"] == ""
    assert bundle.effective["POC_RUNTIME_NO_PROXY"] == ""


def test_runtime_proxy_is_explicit_and_has_its_own_no_proxy_contract(tmp_path: Path) -> None:
    operator = tmp_path / ".env.prep"
    values = _operator_values() | {
        "HTTP_PROXY": "http://build-proxy.example.test:8080",
        "HTTPS_PROXY": "http://build-proxy.example.test:8080",
        "NO_PROXY": "build.internal",
        "POC_RUNTIME_HTTP_PROXY": "http://runtime-proxy.example.test:8080",
        "POC_RUNTIME_HTTPS_PROXY": "http://runtime-proxy.example.test:8080",
        "POC_RUNTIME_NO_PROXY": "datahub.internal",
    }
    _write_private_env(operator, values)
    bundle = deploy.reconcile_environment(
        _release(),
        operator_path=operator,
        optional_path=tmp_path / ".env.prep.optional",
        runtime_path=tmp_path / ".env.prep.runtime",
        random_token=lambda count: "x" * count,
    )
    assert bundle.effective["POC_RUNTIME_HTTP_PROXY"] == values["POC_RUNTIME_HTTP_PROXY"]
    assert set(bundle.effective["POC_RUNTIME_NO_PROXY"].split(",")) >= {
        "datahub.internal",
        "localhost",
        "127.0.0.1",
        "neo4j",
    }
    assert "pgvector" not in bundle.effective["POC_RUNTIME_NO_PROXY"].split(",")


def test_image_reference_is_resolved_without_shell_state() -> None:
    assert deploy.resolve_web_image({"services": {"web": {"image": "datariver-poc:" + "a" * 40}}})
    with pytest.raises(deploy.PrepError) as captured:
        deploy.resolve_web_image({"services": {"web": {"image": ""}}})
    assert captured.value.code == "PREP_WEB_IMAGE_REF_EMPTY"
    assert "IMAGE_REF" in captured.value.action


def test_postgres_contract_matches_or_returns_classified_credential_failure() -> None:
    valid = {
        "services": {
            "web": {
                "environment": {
                    "POC_POSTGRES_DB": "poc",
                    "POC_POSTGRES_USER": "poc",
                    "POC_POSTGRES_PASSWORD": "secret",
                }
            },
            "pgvector": {
                "environment": {
                    "POSTGRES_DB": "poc",
                    "POSTGRES_USER": "poc",
                    "POSTGRES_PASSWORD": "secret",
                }
            },
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


def _inventory(
    *,
    marker: bool = False,
    marker_valid: bool = False,
    runtime: bool = False,
    runtime_valid: bool = False,
    running: bool = False,
    volumes: tuple[str, ...] = (),
    network: bool = False,
    attempt: dict[str, object] | None = None,
    attempt_present: bool = False,
) -> object:
    containers = (deploy.TargetContainer("container", "web", running),) if running or marker else ()
    return deploy.TargetInventory(
        marker,
        marker_valid,
        runtime,
        runtime_valid,
        containers,
        tuple(deploy.TargetVolume(f"project_{name}", name) for name in volumes),
        ("project-services",) if network else (),
        attempt_present,
        attempt is not None,
        attempt,
    )


@pytest.mark.parametrize(
    ("inventory", "expected"),
    (
        (_inventory(), deploy.TargetState.FRESH_CLEAN),
        (
            _inventory(
                marker=True,
                marker_valid=True,
                runtime=True,
                runtime_valid=True,
                running=True,
                volumes=("pgvector-data", "neo4j-data", "neo4j-logs"),
            ),
            deploy.TargetState.EXISTING_ACCEPTED_RUNNING,
        ),
        (
            deploy.TargetInventory(
                True,
                True,
                True,
                True,
                (),
                (
                    deploy.TargetVolume("project_pg", "pgvector-data"),
                    deploy.TargetVolume("project_neo", "neo4j-data"),
                ),
                (),
            ),
            deploy.TargetState.EXISTING_ACCEPTED_STOPPED,
        ),
        (
            _inventory(runtime=True, runtime_valid=True, volumes=("pgvector-data",)),
            deploy.TargetState.FAILED_FIRST_INSTALL_REQUIRES_INSPECTION,
        ),
        (
            _inventory(
                runtime=True,
                runtime_valid=True,
                volumes=("pgvector-data", "neo4j-data", "neo4j-logs"),
            ),
            deploy.TargetState.LEGACY_SELF_BOOTSTRAPPED_PARTIAL_REQUIRES_INSPECTION,
        ),
        (
            _inventory(marker=True, marker_valid=False, runtime=True, runtime_valid=True),
            deploy.TargetState.EXISTING_STATE_AMBIGUOUS,
        ),
        (
            _inventory(marker=True, marker_valid=True, runtime=False, runtime_valid=False),
            deploy.TargetState.EXISTING_STATE_AMBIGUOUS,
        ),
    ),
)
def test_target_state_classifier(inventory: object, expected: object) -> None:
    assert deploy.classify_target_state(inventory) is expected


def test_owned_incomplete_receipt_is_resumable_but_malformed_receipt_is_ambiguous() -> None:
    receipt = {
        "contract": "DATARIVER_PREP39083_DEPLOY_ATTEMPT_V1",
        "product_sha": "a" * 40,
        "evidence_sha": "b" * 40,
        "handoff_commit": "c" * 40,
        "project": "datariver-prep39083",
        "platform": "linux/amd64",
        "port": 39083,
        "target_state_before": "FRESH_CLEAN",
        "runtime_env_fingerprint": "d" * 64,
        "volume_identities": [
            "datariver-prep39083_neo4j-data",
            "datariver-prep39083_neo4j-logs",
            "datariver-prep39083_pgvector-data",
        ],
        "k9_mode": "DEFERRED",
        "phase": "SMOKE_FAILED",
        "started_at": "2026-08-25T00:00:00+00:00",
        "updated_at": "2026-08-25T00:00:01+00:00",
    }
    inventory = deploy.TargetInventory(
        False,
        False,
        True,
        True,
        (),
        (
            deploy.TargetVolume("datariver-prep39083_pgvector-data", "pgvector-data"),
            deploy.TargetVolume("datariver-prep39083_neo4j-data", "neo4j-data"),
        ),
        ("datariver-prep39083-services",),
        True,
        True,
        receipt,
    )
    assert deploy.classify_target_state(inventory) is deploy.TargetState.EXISTING_OWNED_INCOMPLETE
    assert (
        deploy.classify_target_state(
            replace(inventory, attempt_receipt_valid=False),
        )
        is deploy.TargetState.EXISTING_STATE_AMBIGUOUS
    )


def test_attempt_receipt_is_atomic_secret_free_and_phase_progresses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt = tmp_path / "deploy-attempt.json"
    monkeypatch.setattr(deploy, "ATTEMPT_RECEIPT", attempt)
    bundle = deploy.EnvironmentBundle(
        {},
        {},
        {
            "POC_MCP_SERVICE_TOKEN": "mcp-secret-must-not-be-recorded",
            "POC_POSTGRES_PASSWORD": "postgres-secret-must-not-be-recorded",
            "NEO4J_PASSWORD": "neo4j-secret-must-not-be-recorded",
            "POC_SOURCE_COMMIT": "a" * 40,
        },
        {},
        (),
        deploy.TargetState.FRESH_CLEAN,
        "DEFERRED",
    )
    receipt = deploy.write_attempt_receipt(
        _release(),
        "c" * 40,
        bundle,
        ("project_pgvector-data", "project_neo4j-data", "project_neo4j-logs"),
        phase="PREPARED",
    )
    assert stat.S_IMODE(attempt.stat().st_mode) == 0o600
    payload = attempt.read_text(encoding="utf-8")
    assert "secret-must-not-be-recorded" not in payload
    assert receipt["runtime_env_fingerprint"] in payload
    advanced = deploy.advance_attempt_phase(receipt, "SMOKE_FAILED")
    assert advanced["phase"] == "SMOKE_FAILED"
    assert json.loads(attempt.read_text())["phase"] == "SMOKE_FAILED"


def test_accepted_state_never_generates_missing_runtime_secrets(tmp_path: Path) -> None:
    operator = tmp_path / ".env.prep"
    _write_private_env(operator, _operator_values())
    with pytest.raises(deploy.PrepError) as captured:
        deploy.reconcile_environment(
            _release(),
            operator_path=operator,
            optional_path=tmp_path / ".env.prep.optional",
            runtime_path=tmp_path / ".env.prep.runtime",
            target_state=deploy.TargetState.EXISTING_ACCEPTED_STOPPED,
            random_token=lambda _count: pytest.fail(
                "accepted state must never create a new secret",
            ),
        )
    assert captured.value.code == "PREP_EXISTING_STATE_REQUIRES_OPERATOR_RECOVERY"


def test_residual_inspection_uses_nonpersistent_placeholders(tmp_path: Path) -> None:
    operator = tmp_path / ".env.prep"
    runtime = tmp_path / ".env.prep.runtime"
    _write_private_env(operator, _operator_values(k9_configured=False))
    bundle = deploy.reconcile_environment(
        _release(),
        operator_path=operator,
        optional_path=tmp_path / ".env.prep.optional",
        runtime_path=runtime,
        target_state=deploy.TargetState.FAILED_FIRST_INSTALL_REQUIRES_INSPECTION,
        random_token=lambda _count: pytest.fail("inspection must not generate a secret"),
    )
    assert not runtime.exists()
    assert bundle.effective["POC_POSTGRES_PASSWORD"] == deploy.INSPECTION_PLACEHOLDER
    assert bundle.effective["NEO4J_PASSWORD"] == deploy.INSPECTION_PLACEHOLDER


def test_deployer_never_destroys_accepted_persistent_volumes() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    forbidden = (
        "docker compose down -v",
        "docker volume rm",
        '"down", "-v"',
        '"volume", "rm"',
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
    assert "ALTER ROLE" in source
    assert "inspect_postgres_durable_rows" in source
    assert "PREP_EXISTING_STATE_REQUIRES_OPERATOR_RECOVERY" in source
    assert source.index("run_provider_preflight(runner, prefix)") < source.index(
        'phase="PREPARED"',
    )
    assert 'advance_attempt_phase(attempt, "SMOKE_FAILED")' in source


@pytest.mark.parametrize(
    "classification",
    sorted(deploy.SUPPORTED_DATAHUB_INVENTORY_FAILURE_CODES),
)
def test_deploy_wrapper_preserves_bounded_inventory_smoke_classification(
    classification: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "runtime"
    smoke_failure = runtime_root / "smoke-failure.json"
    monkeypatch.setattr(deploy, "RUNTIME_ROOT", runtime_root)
    monkeypatch.setattr(deploy, "SMOKE_FAILURE", smoke_failure)

    class FailingSmokeRunner:
        def run(self, arguments: object, **_keywords: object) -> None:
            del arguments
            smoke_failure.write_text(
                json.dumps(
                    {
                        "contract": "DATARIVER_PREP39083_SMOKE_FAILURE_V1",
                        "classification": classification,
                    },
                ),
                encoding="utf-8",
            )
            completed = subprocess.CompletedProcess(["node"], 2, "", "")
            raise deploy.CommandFailure(["node"], completed)

    with pytest.raises(deploy.PrepError) as captured:
        deploy.run_smoke(
            FailingSmokeRunner(),
            _release(),
            "admin",
            "bounded-test-password",
            k9_mode="DEFERRED",
        )

    assert captured.value.step == "RUNTIME_SMOKE"
    assert captured.value.code == classification


def test_deploy_wrapper_rejects_untrusted_inventory_shaped_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "runtime"
    smoke_failure = runtime_root / "smoke-failure.json"
    monkeypatch.setattr(deploy, "RUNTIME_ROOT", runtime_root)
    monkeypatch.setattr(deploy, "SMOKE_FAILURE", smoke_failure)

    class FailingSmokeRunner:
        def run(self, arguments: object, **_keywords: object) -> None:
            del arguments
            smoke_failure.write_text(
                json.dumps({"classification": "PREP_DATAHUB_INVENTORY_UNTRUSTED_FAILED"}),
                encoding="utf-8",
            )
            completed = subprocess.CompletedProcess(["node"], 2, "", "")
            raise deploy.CommandFailure(["node"], completed)

    with pytest.raises(deploy.PrepError) as captured:
        deploy.run_smoke(
            FailingSmokeRunner(),
            _release(),
            "admin",
            "bounded-test-password",
            k9_mode="DEFERRED",
        )

    assert captured.value.code == "PREP_SMOKE_UNKNOWN_FAILED"


@pytest.mark.parametrize(
    "classification",
    sorted(deploy.SUPPORTED_GENERAL_PROVIDER_FAILURE_CODES),
)
def test_deploy_wrapper_preserves_bounded_general_provider_smoke_classification(
    classification: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "runtime"
    smoke_failure = runtime_root / "smoke-failure.json"
    monkeypatch.setattr(deploy, "RUNTIME_ROOT", runtime_root)
    monkeypatch.setattr(deploy, "SMOKE_FAILURE", smoke_failure)

    class FailingSmokeRunner:
        def run(self, arguments: object, **_keywords: object) -> None:
            del arguments
            smoke_failure.write_text(
                json.dumps({"classification": classification}),
                encoding="utf-8",
            )
            completed = subprocess.CompletedProcess(["node"], 2, "", "")
            raise deploy.CommandFailure(["node"], completed)

    with pytest.raises(deploy.PrepError) as captured:
        deploy.run_smoke(
            FailingSmokeRunner(),
            _release(),
            "admin",
            "bounded-test-password",
            k9_mode="DEFERRED",
        )

    assert captured.value.code == classification


def test_deploy_wrapper_rejects_untrusted_general_provider_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "runtime"
    smoke_failure = runtime_root / "smoke-failure.json"
    monkeypatch.setattr(deploy, "RUNTIME_ROOT", runtime_root)
    monkeypatch.setattr(deploy, "SMOKE_FAILURE", smoke_failure)

    class FailingSmokeRunner:
        def run(self, arguments: object, **_keywords: object) -> None:
            del arguments
            smoke_failure.write_text(
                json.dumps(
                    {"classification": "PREP_SMOKE_GENERAL_PROVIDER_UNTRUSTED_FAILED"},
                ),
                encoding="utf-8",
            )
            completed = subprocess.CompletedProcess(["node"], 2, "", "")
            raise deploy.CommandFailure(["node"], completed)

    with pytest.raises(deploy.PrepError) as captured:
        deploy.run_smoke(
            FailingSmokeRunner(),
            _release(),
            "admin",
            "bounded-test-password",
            k9_mode="DEFERRED",
        )

    assert captured.value.code == "PREP_SMOKE_UNKNOWN_FAILED"


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
        'test "$HTTP_PROXY" = "$http_proxy"\n'
        'test "$HTTPS_PROXY" = "$https_proxy"\n'
        'test "$NO_PROXY" = "$no_proxy"\n'
        'test "$1 $2 $3 $4" = "run --frozen python scripts/prep39083_deploy.py"\n',
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
    assert "COPY frontend/poc-llm-timeout.mjs ./poc-llm-timeout.mjs" in dockerfile
    assert "HTTP_PROXY: ${HTTP_PROXY:-}" in compose
    assert "HTTPS_PROXY: ${HTTPS_PROXY:-}" in compose
    assert "NO_PROXY: ${NO_PROXY:-}" in compose
    web_environment = compose.split("    environment:", 1)[1].split("    depends_on:", 1)[0]
    assert "HTTP_PROXY: ${HTTP_PROXY:-}" not in web_environment
    assert "HTTPS_PROXY: ${HTTPS_PROXY:-}" not in web_environment
    assert "POC_RUNTIME_HTTP_PROXY: ${POC_RUNTIME_HTTP_PROXY:-}" in web_environment
