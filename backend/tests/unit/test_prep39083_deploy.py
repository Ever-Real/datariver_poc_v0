from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import Any, cast

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
            "POC_PUBLIC_ORIGIN": "http://10.20.30.40:39083",
        }.get(key, f"configured-{key.lower()}")
        for key in contract["ownership"]["CORE_REQUIRED"]
    } | {"HTTP_PROXY": "", "HTTPS_PROXY": "", "NO_PROXY": "corp.internal"}
    del k9_configured
    return values


def _write_private_env(path: Path, values: dict[str, str]) -> bytes:
    payload = "".join(f"{key}={value}\n" for key, value in values.items()).encode()
    path.write_bytes(payload)
    path.chmod(0o600)
    return payload


def _release() -> object:
    return deploy.ReleaseIdentity("a" * 40, "b" * 40, "linux/amd64", 39083, "datariver-prep39083")


def _runtime_values(*, fixed_timeout: str = "120000") -> dict[str, str]:
    contract = json.loads((ROOT / "deploy/prep39083/env-contract.json").read_text())
    runtime = {str(key): str(value) for key, value in contract["ownership"]["FIXED"].items()}
    runtime.update(
        {
            "POC_POSTGRES_PASSWORD": "preserved-postgres-secret",
            "NEO4J_PASSWORD": "preserved-neo4j-secret",
            "POC_MCP_SERVICE_TOKEN": "preserved-mcp-secret",
            "POC_K9_SCHEDULER_ENABLED": "false",
            "POC_IMAGE_TAG": "a" * 40,
            "POC_SOURCE_COMMIT": "a" * 40,
            "PREP_RELEASE_PRODUCT_SHA": "a" * 40,
            "PREP_RELEASE_EVIDENCE_SHA": "b" * 40,
            "POC_LLM_TIMEOUT_MS": fixed_timeout,
        }
    )
    return runtime


class AttemptValidationRunner:
    def __init__(self, historical_contract: dict[str, object], *, ancestry: bool = True) -> None:
        self.historical_contract = historical_contract
        self.ancestry = ancestry

    def output(self, arguments: Sequence[str]) -> str:
        values = list(arguments)
        assert values[:2] == ["git", "show"]
        return json.dumps(self.historical_contract)

    def run(
        self,
        arguments: Sequence[str],
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        del check
        values = list(arguments)
        assert values[:3] == ["git", "merge-base", "--is-ancestor"]
        return subprocess.CompletedProcess(values, 0 if self.ancestry else 1, "", "")


def _attempt_inventory(receipt: dict[str, object]) -> Any:
    return deploy.TargetInventory(
        False,
        False,
        True,
        True,
        (),
        tuple(
            deploy.TargetVolume(name, name.removeprefix("datariver-prep39083_"))
            for name in deploy.canonical_volume_identities(_release())
        ),
        ("datariver-prep39083-services",),
        True,
        True,
        receipt,
    )


def _base_attempt_receipt(runtime: dict[str, str]) -> dict[str, object]:
    return {
        "contract": deploy.ATTEMPT_CONTRACT_V2,
        "product_sha": "1" * 40,
        "evidence_sha": "2" * 40,
        "handoff_commit": "3" * 40,
        "project": "datariver-prep39083",
        "platform": "linux/amd64",
        "port": 39083,
        "target_state_before": "FRESH_CLEAN",
        "ownership_fingerprint_contract": deploy.OWNERSHIP_FINGERPRINT_CONTRACT,
        "ownership_fingerprint": deploy.target_ownership_fingerprint(runtime),
        "volume_identities": list(deploy.canonical_volume_identities(_release())),
        "k9_mode": "DEFERRED",
        "phase": "SMOKE_FAILED",
        "started_at": "2026-08-25T00:00:00+00:00",
        "updated_at": "2026-08-25T00:00:01+00:00",
    }


def test_operator_environment_is_preserved_and_generated_secrets_are_stable(tmp_path: Path) -> None:
    operator = tmp_path / ".env.prep"
    runtime = tmp_path / ".env.prep.runtime"
    original = _write_private_env(
        operator,
        _operator_values() | {"POC_INTRANET_HTTP_ALLOWED_CIDRS": "100.64.0.0/10"},
    )
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
    assert first.effective["POC_INTRANET_HTTP_ALLOWED_CIDRS"] == "100.64.0.0/10"
    assert stat.S_IMODE(runtime.stat().st_mode) == 0o600
    assert first.effective["POC_IMAGE_TAG"] == "a" * 40
    assert first.effective["POC_SOURCE_COMMIT"] == "a" * 40


def test_accepted_target_adds_operator_intranet_cidr_without_state_or_secret_reset(
    tmp_path: Path,
) -> None:
    operator = tmp_path / ".env.prep"
    runtime = tmp_path / ".env.prep.runtime"
    _write_private_env(operator, _operator_values())
    first = deploy.reconcile_environment(
        _release(),
        operator_path=operator,
        optional_path=tmp_path / ".env.prep.optional",
        runtime_path=runtime,
        random_token=lambda count: "x" * count,
    )
    preserved = {
        key: first.runtime[key]
        for key in ("POC_POSTGRES_PASSWORD", "NEO4J_PASSWORD", "POC_MCP_SERVICE_TOKEN")
    }
    _write_private_env(
        operator,
        _operator_values() | {"POC_INTRANET_HTTP_ALLOWED_CIDRS": "100.64.0.0/10"},
    )
    upgraded = deploy.reconcile_environment(
        _release(),
        operator_path=operator,
        optional_path=tmp_path / ".env.prep.optional",
        runtime_path=runtime,
        target_state=deploy.TargetState.EXISTING_ACCEPTED_RUNNING,
        random_token=lambda _count: pytest.fail("accepted upgrade must not regenerate secrets"),
    )
    assert {key: upgraded.runtime[key] for key in preserved} == preserved
    assert upgraded.effective["POC_INTRANET_HTTP_ALLOWED_CIDRS"] == "100.64.0.0/10"


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


def test_mcl_discovery_requires_only_operator_kafka_connectivity(tmp_path: Path) -> None:
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
    assert bundle.effective["POC_CHANGE_HISTORY_SCHEDULER_ENABLED"] == "true"
    assert bundle.effective["POC_MCL_KAFKA_BROKERS"].startswith("configured-")
    assert not bundle.effective.get("POC_MCL_KAFKA_TOPIC")
    assert not bundle.effective.get("POC_MCL_SOURCE_IDENTITY_HASH")


def test_built_in_k9_is_required_without_an_external_studio_database(tmp_path: Path) -> None:
    operator = tmp_path / ".env.prep"
    _write_private_env(operator, _operator_values(k9_configured=False))
    deferred = deploy.reconcile_environment(
        _release(),
        operator_path=operator,
        optional_path=tmp_path / ".env.prep.optional",
        runtime_path=tmp_path / ".env.prep.runtime",
        random_token=lambda count: "x" * count,
    )
    assert deferred.k9_mode == "REQUIRED"
    assert deferred.effective["POC_K9_SCHEDULER_ENABLED"] == "true"

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


def _web_image_document(
    *,
    product_sha: str = "a" * 40,
    architecture: str = "amd64",
) -> dict[str, object]:
    image = f"datariver-poc:{'a' * 40}"
    return {
        "Id": "sha256:bounded-test-image",
        "Os": "linux",
        "Architecture": architecture,
        "RepoTags": [image],
        "Config": {
            "Env": ["POC_SERVER_PORT=8080"],
            "Labels": {"org.opencontainers.image.revision": product_sha},
        },
    }


class DoctorImageRunner:
    def __init__(
        self,
        inspections: Sequence[dict[str, object] | None],
        *,
        build_fails: bool = False,
    ) -> None:
        self.inspections = list(inspections)
        self.build_fails = build_fails
        self.calls: list[list[str]] = []

    def run(
        self,
        arguments: Sequence[str],
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        values = list(arguments)
        self.calls.append(values)
        if values[:3] == ["docker", "image", "inspect"]:
            inspection = self.inspections.pop(0)
            return subprocess.CompletedProcess(
                values,
                0 if inspection is not None else 1,
                json.dumps([inspection]) if inspection is not None else "",
                "",
            )
        assert values[-3:] == ["build", "--pull=false", "web"]
        completed = subprocess.CompletedProcess(values, 1 if self.build_fails else 0, "", "")
        if check and completed.returncode:
            raise deploy.CommandFailure(values, completed)
        return completed


def test_doctor_builds_exact_image_when_absent_and_reuses_valid_present_image() -> None:
    image = f"datariver-poc:{'a' * 40}"
    absent = DoctorImageRunner([None, _web_image_document()])
    assert (
        deploy.prepare_exact_web_image(
            absent,
            ["docker", "compose"],
            image,
            "a" * 40,
            doctor=True,
        )
        == "BUILT"
    )
    assert ["docker", "compose", "build", "--pull=false", "web"] in absent.calls

    present = DoctorImageRunner([_web_image_document()])
    assert (
        deploy.prepare_exact_web_image(
            present,
            ["docker", "compose"],
            image,
            "a" * 40,
            doctor=True,
        )
        == "REUSED"
    )
    assert not any("build" in call for call in present.calls)

    deploy_runner = DoctorImageRunner([_web_image_document()])
    assert (
        deploy.prepare_exact_web_image(
            deploy_runner,
            ["docker", "compose"],
            image,
            "a" * 40,
            doctor=False,
        )
        == "BUILT"
    )
    assert deploy_runner.calls[0][-3:] == ["build", "--pull=false", "web"]


@pytest.mark.parametrize(
    ("document", "code"),
    (
        (
            _web_image_document(product_sha="b" * 40),
            "PREP_DOCTOR_IMAGE_REVISION_MISMATCH",
        ),
        (
            _web_image_document(architecture="arm64"),
            "PREP_DOCTOR_IMAGE_PLATFORM_MISMATCH",
        ),
    ),
)
def test_doctor_rejects_wrong_revision_or_platform(
    document: dict[str, object],
    code: str,
) -> None:
    runner = DoctorImageRunner([document])
    with pytest.raises(deploy.PrepError) as captured:
        deploy.prepare_exact_web_image(
            runner,
            ["docker", "compose"],
            f"datariver-poc:{'a' * 40}",
            "a" * 40,
            doctor=True,
        )
    assert captured.value.code == code
    assert not any("build" in call for call in runner.calls)


def test_doctor_classifies_image_build_failure_and_post_build_absence() -> None:
    image = f"datariver-poc:{'a' * 40}"
    failed = DoctorImageRunner([None], build_fails=True)
    with pytest.raises(deploy.PrepError) as captured:
        deploy.prepare_exact_web_image(
            failed,
            ["docker", "compose"],
            image,
            "a" * 40,
            doctor=True,
        )
    assert captured.value.code == "PREP_DOCTOR_IMAGE_BUILD_FAILED"

    missing = DoctorImageRunner([None, None])
    with pytest.raises(deploy.PrepError) as captured:
        deploy.prepare_exact_web_image(
            missing,
            ["docker", "compose"],
            image,
            "a" * 40,
            doctor=True,
        )
    assert captured.value.code == "PREP_DOCTOR_IMAGE_MISSING"

    unexpected = DoctorImageRunner([])
    with pytest.raises(deploy.PrepError) as captured:
        deploy.prepare_exact_web_image(
            unexpected,
            ["docker", "compose"],
            "datariver-poc:latest",
            "a" * 40,
            doctor=True,
        )
    assert captured.value.code == "PREP_DOCTOR_IMAGE_IDENTITY_MISMATCH"
    assert unexpected.calls == []


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
    assert receipt["contract"] == deploy.ATTEMPT_CONTRACT_V2
    assert receipt["ownership_fingerprint"] in payload
    assert "runtime_env_fingerprint" not in receipt
    assert deploy._attempt_receipt(attempt) == receipt
    advanced = deploy.advance_attempt_phase(receipt, "SMOKE_FAILED")
    assert advanced["phase"] == "SMOKE_FAILED"
    assert json.loads(attempt.read_text())["phase"] == "SMOKE_FAILED"


def test_ownership_fingerprint_excludes_fixed_release_configuration() -> None:
    before = _runtime_values(fixed_timeout="15000")
    after = _runtime_values(fixed_timeout="120000")
    assert deploy.target_ownership_fingerprint(before) == deploy.target_ownership_fingerprint(after)
    after["POC_POSTGRES_PASSWORD"] = "changed-target-secret"
    assert deploy.target_ownership_fingerprint(before) != deploy.target_ownership_fingerprint(after)


def test_legacy_v1_receipt_migrates_after_runtime_already_has_descendant_fixed_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_contract = json.loads((ROOT / "deploy/prep39083/env-contract.json").read_text())
    historical_contract = json.loads(json.dumps(current_contract))
    historical_contract["contract"] = "DATARIVER_PREP39083_ENV_V4"
    historical_contract["ownership"]["FIXED"]["POC_LLM_TIMEOUT_MS"] = "15000"
    old_runtime = _runtime_values(fixed_timeout="15000")
    already_updated_runtime = _runtime_values(fixed_timeout="120000")
    receipt = _base_attempt_receipt(old_runtime)
    receipt.update(
        {
            "contract": deploy.ATTEMPT_CONTRACT_V1,
            "runtime_env_fingerprint": deploy.legacy_runtime_env_fingerprint_v1(old_runtime),
        }
    )
    receipt.pop("ownership_fingerprint_contract")
    receipt.pop("ownership_fingerprint")
    runner = AttemptValidationRunner(historical_contract)

    validated = deploy.validate_owned_attempt(
        runner,
        _release(),
        "4" * 40,
        _attempt_inventory(receipt),
        already_updated_runtime,
        "DEFERRED",
    )
    assert validated == receipt

    attempt_path = tmp_path / "deploy-attempt.json"
    monkeypatch.setattr(deploy, "ATTEMPT_RECEIPT", attempt_path)
    bundle = deploy.EnvironmentBundle(
        {},
        {},
        already_updated_runtime,
        already_updated_runtime,
        (),
        deploy.TargetState.EXISTING_OWNED_INCOMPLETE,
        "DEFERRED",
    )
    migrated = deploy.write_attempt_receipt(
        _release(),
        "4" * 40,
        bundle,
        deploy.canonical_volume_identities(_release()),
        phase="PREPARED",
        previous=validated,
    )
    assert migrated["contract"] == deploy.ATTEMPT_CONTRACT_V2
    assert migrated["migrated_from_contract"] == deploy.ATTEMPT_CONTRACT_V1
    assert migrated["resumed_from_product_sha"] == receipt["product_sha"]


@pytest.mark.parametrize(
    "drift",
    ("secret", "volume", "project", "platform", "port", "k9", "ancestry", "malformed"),
)
def test_owned_attempt_negative_drift_matrix_fails_closed(drift: str) -> None:
    runtime = _runtime_values()
    receipt = _base_attempt_receipt(runtime)
    inventory = _attempt_inventory(receipt)
    runner = AttemptValidationRunner(
        json.loads((ROOT / "deploy/prep39083/env-contract.json").read_text()),
        ancestry=drift != "ancestry",
    )
    expected_k9 = "DEFERRED"
    if drift == "secret":
        runtime["NEO4J_PASSWORD"] = "unauthorized-secret-change"
    elif drift == "volume":
        receipt["volume_identities"] = ["unrelated_volume"]
    elif drift == "project":
        receipt["project"] = "unrelated-project"
    elif drift == "platform":
        receipt["platform"] = "linux/arm64"
    elif drift == "port":
        receipt["port"] = 39084
    elif drift == "k9":
        expected_k9 = "REQUIRED"
    elif drift == "malformed":
        inventory = replace(inventory, attempt_receipt_valid=False)

    with pytest.raises(deploy.PrepError) as captured:
        deploy.validate_owned_attempt(
            runner,
            _release(),
            "4" * 40,
            inventory,
            runtime,
            expected_k9,
        )
    assert captured.value.code == "PREP_EXISTING_STATE_REQUIRES_OPERATOR_RECOVERY"


def test_incomplete_runtime_is_not_rewritten_before_ownership_validation(
    tmp_path: Path,
) -> None:
    operator = tmp_path / ".env.prep"
    runtime_path = tmp_path / ".env.prep.runtime"
    _write_private_env(operator, _operator_values(k9_configured=False))
    old_runtime = _runtime_values(fixed_timeout="15000")
    original = _write_private_env(runtime_path, old_runtime)
    bundle = deploy.reconcile_environment(
        _release(),
        operator_path=operator,
        optional_path=tmp_path / ".env.prep.optional",
        runtime_path=runtime_path,
        target_state=deploy.TargetState.EXISTING_OWNED_INCOMPLETE,
        persist_runtime=False,
        random_token=lambda _count: pytest.fail("owned target secrets must be reused"),
    )
    assert runtime_path.read_bytes() == original
    assert bundle.runtime["POC_LLM_TIMEOUT_MS"] == "120000"
    source = MODULE_PATH.read_text(encoding="utf-8")
    prepare = source[
        source.index("def prepare_deployment(") : source.index("def verify_source_identity(")
    ]
    assert prepare.index("validate_owned_attempt(") < prepare.index("reconcile_environment(")


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
    ("classification", "action_fragment"),
    (
        (
            "PREP_PREFLIGHT_WEB_INTRANET_ORIGIN_MALFORMED_FAILED",
            "POC_PUBLIC_ORIGIN",
        ),
        (
            "PREP_PREFLIGHT_WEB_INTRANET_ORIGIN_NOT_APPROVED_FAILED",
            "POC_INTRANET_HTTP_ALLOWED_CIDRS",
        ),
        (
            "PREP_PREFLIGHT_WEB_INTRANET_CIDR_CONFIG_FAILED",
            "POC_INTRANET_HTTP_ALLOWED_CIDRS",
        ),
    ),
)
def test_deploy_wrapper_preserves_typed_intranet_preflight_diagnostics(
    classification: str,
    action_fragment: str,
) -> None:
    class FailedPreflightRunner:
        def run(self, arguments: Sequence[str], **_keywords: object) -> None:
            completed = subprocess.CompletedProcess(
                list(arguments),
                2,
                "",
                json.dumps(
                    {
                        "classification": classification,
                        "stage": "WEB_INTRANET",
                    }
                ),
            )
            raise deploy.CommandFailure(list(arguments), completed)

    with pytest.raises(deploy.PrepError) as captured:
        deploy.run_provider_preflight(FailedPreflightRunner(), ["docker", "compose"])
    assert captured.value.code == classification
    assert action_fragment in captured.value.action


@pytest.mark.parametrize(
    ("classification", "stage"),
    (
        ("PREP_PREFLIGHT_DATAHUB_UNEXPECTED_FAILED", "DATAHUB"),
        ("PREP_PREFLIGHT_QUALITY_READ_UNEXPECTED_FAILED", "QUALITY_READ"),
        ("PREP_PREFLIGHT_CHAT_UNEXPECTED_FAILED", "CHAT"),
        ("PREP_PREFLIGHT_EMBEDDING_UNEXPECTED_FAILED", "EMBEDDING"),
        ("PREP_PREFLIGHT_RERANKER_UNEXPECTED_FAILED", "RERANKER"),
        ("PREP_PREFLIGHT_AIRFLOW_UNEXPECTED_FAILED", "AIRFLOW"),
        ("PREP_PREFLIGHT_MINIO_UNEXPECTED_FAILED", "MINIO"),
        ("PREP_MCL_DISCOVERY_KAFKA_ADMIN_FAILED", "MCL_DISCOVERY"),
    ),
)
def test_deploy_wrapper_preserves_sanitized_provider_stage_classification(
    classification: str,
    stage: str,
) -> None:
    class FailedPreflightRunner:
        def run(self, arguments: Sequence[str], **_keywords: object) -> None:
            completed = subprocess.CompletedProcess(
                list(arguments),
                2,
                "",
                json.dumps({"classification": classification, "stage": stage}),
            )
            raise deploy.CommandFailure(list(arguments), completed)

    with pytest.raises(deploy.PrepError) as captured:
        deploy.run_provider_preflight(FailedPreflightRunner(), ["docker", "compose"])

    assert captured.value.code == classification
    assert stage in captured.value.reason


def test_deploy_wrapper_uses_internal_not_unknown_for_malformed_failure_envelope() -> None:
    class FailedPreflightRunner:
        def run(self, arguments: Sequence[str], **_keywords: object) -> None:
            completed = subprocess.CompletedProcess(
                list(arguments), 2, "", json.dumps({"classification": "untrusted"})
            )
            raise deploy.CommandFailure(list(arguments), completed)

    with pytest.raises(deploy.PrepError) as captured:
        deploy.run_provider_preflight(FailedPreflightRunner(), ["docker", "compose"])

    assert captured.value.code == "PREP_PREFLIGHT_INTERNAL_UNEXPECTED_FAILED"


def _doctor_matrix(
    *,
    chat: dict[str, str] | None = None,
    datahub: dict[str, str] | None = None,
    quality: dict[str, str] | None = None,
) -> dict[str, object]:
    ready = {"status": "READY"}
    stages: dict[str, object] = {stage: dict(ready) for stage in deploy.DOCTOR_PREFLIGHT_STAGES}
    stages["AIRFLOW"] = {"status": "DEFERRED"}
    stages["MINIO"] = {"status": "DEFERRED"}
    if chat is not None:
        stages["CHAT"] = chat
    if datahub is not None:
        stages["DATAHUB"] = datahub
    if quality is not None:
        stages["QUALITY_READ"] = quality
    failed = any(
        isinstance(entry, dict) and entry.get("status") in {"FAILED", "BLOCKED_BY_DEPENDENCY"}
        for entry in stages.values()
    )
    return {
        "contract": "DATARIVER_PREP39083_PROVIDER_PREFLIGHT_MATRIX_V1",
        "status": "FAILED" if failed else "PASS",
        "stages": stages,
    }


class DoctorPreflightRunner:
    def __init__(
        self,
        matrix: dict[str, object] | None,
        *,
        container_returncode: int = 0,
        node_returncode: int = 0,
        module_returncode: int = 0,
        matrix_returncode: int | None = None,
        matrix_output: str | None = None,
    ) -> None:
        self.matrix = matrix
        self.container_returncode = container_returncode
        self.node_returncode = node_returncode
        self.module_returncode = module_returncode
        self.matrix_returncode = matrix_returncode
        self.matrix_output = matrix_output
        self.calls: list[list[str]] = []

    def run(
        self,
        arguments: Sequence[str],
        **keywords: object,
    ) -> subprocess.CompletedProcess[str]:
        values = list(arguments)
        self.calls.append(values)
        assert keywords == {"check": False}
        if values[-1] == "/usr/bin/true":
            return subprocess.CompletedProcess(values, self.container_returncode, "", "")
        if values[-2:] == ["node", "--version"]:
            return subprocess.CompletedProcess(values, self.node_returncode, "", "")
        if "--eval" in values:
            return subprocess.CompletedProcess(values, self.module_returncode, "", "")
        assert values[-1] == "--collect-all"
        output = self.matrix_output
        if output is None:
            output = "" if self.matrix is None else json.dumps(self.matrix)
        returncode = self.matrix_returncode
        if returncode is None:
            returncode = 2 if self.matrix and self.matrix.get("status") == "FAILED" else 0
        return subprocess.CompletedProcess(values, returncode, output, "")


def _collect_doctor(runner: DoctorPreflightRunner) -> dict[str, object]:
    return cast(
        dict[str, object],
        deploy.collect_provider_preflight(
            runner,
            f"datariver-poc:{'a' * 40}",
            Path("/private/doctor-effective.env"),
            {},
        ),
    )


def test_doctor_collect_all_parser_preserves_full_sanitized_matrix() -> None:
    matrix = _doctor_matrix(
        chat={
            "status": "FAILED",
            "classification": "PREP_PREFLIGHT_CHAT_AUTH_FAILED",
            "status_class": "4xx",
        },
        datahub={
            "status": "FAILED",
            "classification": "PREP_PREFLIGHT_DATAHUB_CONNECTIVITY_FAILED",
        },
        quality={"status": "BLOCKED_BY_DEPENDENCY", "dependency": "DATAHUB"},
    )

    result = _collect_doctor(DoctorPreflightRunner(matrix))
    assert result == matrix
    stages = cast(dict[str, object], result["stages"])
    assert stages["AIRFLOW"] == {"status": "DEFERRED"}
    assert stages["MINIO"] == {"status": "DEFERRED"}


def test_doctor_collect_all_parser_rejects_unbounded_stage_classification() -> None:
    matrix = _doctor_matrix(chat={"status": "FAILED", "classification": "untrusted"})

    with pytest.raises(deploy.PrepError) as captured:
        _collect_doctor(DoctorPreflightRunner(matrix))
    assert captured.value.code == "PREP_DOCTOR_PREFLIGHT_MATRIX_RESULT_INVALID"


def test_doctor_classifies_container_and_node_module_start_failures() -> None:
    matrix = _doctor_matrix()
    with pytest.raises(deploy.PrepError) as captured:
        _collect_doctor(DoctorPreflightRunner(matrix, container_returncode=125))
    assert captured.value.code == "PREP_DOCTOR_PREFLIGHT_CONTAINER_START_FAILED"

    for runner in (
        DoctorPreflightRunner(matrix, node_returncode=127),
        DoctorPreflightRunner(matrix, module_returncode=1),
    ):
        with pytest.raises(deploy.PrepError) as captured:
            _collect_doctor(runner)
        assert captured.value.code == "PREP_DOCTOR_PREFLIGHT_NODE_START_FAILED"


def test_doctor_uses_matrix_invalid_only_after_child_launches_successfully() -> None:
    runner = DoctorPreflightRunner(None, matrix_returncode=1, matrix_output="not-json")
    with pytest.raises(deploy.PrepError) as captured:
        _collect_doctor(runner)
    assert captured.value.code == "PREP_DOCTOR_PREFLIGHT_MATRIX_RESULT_INVALID"
    assert any("--eval" in call for call in runner.calls)
    assert runner.calls[-1][-1] == "--collect-all"


def test_doctor_image_and_collect_all_commands_do_not_touch_product_state() -> None:
    image_runner = DoctorImageRunner([None, _web_image_document()])
    deploy.prepare_exact_web_image(
        image_runner,
        ["docker", "compose"],
        f"datariver-poc:{'a' * 40}",
        "a" * 40,
        doctor=True,
    )
    preflight_runner = DoctorPreflightRunner(_doctor_matrix())
    _collect_doctor(preflight_runner)
    calls = [*image_runner.calls, *preflight_runner.calls]
    serialized = "\n".join(" ".join(call) for call in calls)
    for forbidden in (
        " up ",
        " exec ",
        "pgvector",
        "neo4j",
        "redis",
        "deploy-attempt.json",
        "accepted.json",
        "volume rm",
    ):
        assert forbidden not in f" {serialized} "
    for call in preflight_runner.calls:
        assert "--rm" in call
        assert call[:2] == ["docker", "run"]


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


@pytest.mark.parametrize(
    ("step", "code"),
    (
        ("TARGET_STATE", "PREP_TARGET_STATE_RECONCILIATION_FAILED"),
        ("STATE_SERVICES", "PREP_STATE_SERVICES_FAILED"),
        ("SCHEMA", "PREP_SCHEMA_INITIALIZATION_FAILED"),
        ("BOOTSTRAP", "PREP_BOOTSTRAP_RECONCILIATION_FAILED"),
        ("WEB_START", "PREP_WEB_START_FAILED"),
        ("AUTHENTICATED_SMOKE", "PREP_ACCEPTANCE_RECEIPT_WRITE_FAILED"),
    ),
)
def test_known_post_preflight_gates_replace_generic_deployment_failures(
    step: str,
    code: str,
) -> None:
    with pytest.raises(deploy.PrepError) as captured:
        with deploy.typed_deploy_gate(step, code, "sanitized reason"):
            raise OSError("private child detail")
    assert captured.value.step == step
    assert captured.value.code == code
    assert "private child detail" not in captured.value.reason


def test_known_post_preflight_gate_preserves_more_precise_product_classification() -> None:
    precise = deploy.PrepError(
        "K9_INITIAL_REFRESH",
        "PREP_SMOKE_K9_POLICY_PIN_DRIFT_FAILED",
        "sanitized",
        "retry",
    )
    with pytest.raises(deploy.PrepError) as captured:
        with deploy.typed_deploy_gate(
            "AUTHENTICATED_SMOKE",
            "PREP_AUTHENTICATED_SMOKE_FAILED",
            "fallback",
        ):
            raise precise
    assert captured.value is precise


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
