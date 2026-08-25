from __future__ import annotations

import importlib.util
import json
import os
import socket
import stat
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
MODULE_PATH = SCRIPTS / "prep39083_deploy.py"
_ENABLED = os.getenv("DATARIVER_PREP39083_DOCKER_INTEGRATION") == "1"
_FULL_ENABLED = os.getenv("DATARIVER_PREP39083_FULL_DOCKER_INTEGRATION") == "1"


def _load_module() -> ModuleType:
    sys.path.insert(0, os.fspath(SCRIPTS))
    try:
        specification = importlib.util.spec_from_file_location(
            "prep39083_deploy_for_docker_integration",
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


def _private_env(path: Path, values: dict[str, str]) -> None:
    path.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
    path.chmod(0o600)


def _operator_values() -> dict[str, str]:
    contract = json.loads((ROOT / "deploy/prep39083/env-contract.json").read_text())
    return {
        key: {
            "POC_PUBLIC_ORIGIN": "https://prep39083.integration.invalid",
        }.get(key, f"configured-{key.lower()}")
        for key in contract["ownership"]["CORE_REQUIRED"]
    } | {
        "HTTP_PROXY": "",
        "HTTPS_PROXY": "",
        "NO_PROXY": "",
        "POC_K9_STUDIO_DATABASE_URL": "",
        "NEO4J_PASSWORD": "o" * 32,
    }


def _portable_operator_values(origin: str) -> dict[str, str]:
    values = _operator_values()
    values.update(
        {
            "POC_PUBLIC_ORIGIN": origin,
            "DATAHUB_GMS_URL": "http://127.0.0.1:9",
            "DATAHUB_GMS_TOKEN": "isolated-datahub-token",
            "DATAHUB_UI_URL": "http://127.0.0.1:9",
            "LLM_CHAT_URL": "http://127.0.0.1:9",
            "LLM_CHAT_MODEL": "isolated-chat",
            "LLM_CHAT_TOKEN": "isolated-chat-token",
            "LLM_EMBEDDING_URL": "http://127.0.0.1:9",
            "LLM_EMBEDDING_MODEL": "isolated-embedding",
            "LLM_EMBEDDING_TOKEN": "isolated-embedding-token",
            "LLM_RERANKER_URL": "http://127.0.0.1:9",
            "LLM_RERANKER_MODEL": "isolated-reranker",
            "LLM_RERANKER_TOKEN": "isolated-reranker-token",
        }
    )
    return values


def _free_port() -> str:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return str(listener.getsockname()[1])


def _effective(bundle: Any, project: str) -> Any:
    values = dict(bundle.effective)
    values.update(
        {
            "POC_PLATFORM": "linux/amd64",
            "POC_SHARED_NETWORK": f"{project}-services",
            "POC_POSTGRES_HOST_PORT": _free_port(),
            "POC_NEO4J_HTTP_PORT": _free_port(),
            "POC_REDIS_PORT": _free_port(),
            "POC_PORT": _free_port(),
        }
    )
    return replace(bundle, effective=values)


def _marker(path: Path, release: Any) -> None:
    path.write_text(
        json.dumps(
            {
                "contract": "DATARIVER_PREP39083_ACCEPTED_V1",
                "product_sha": release.product_sha,
                "evidence_sha": release.evidence_sha,
                "handoff_commit": "c" * 40,
                "accepted_at": "2026-08-25T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.skipif(
    not _ENABLED,
    reason="explicit isolated PREP39083 Docker integration is required",
)
def test_unified_state_machine_and_non_destructive_failed_install_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = f"datariver-prep39083-it-{uuid4().hex[:10]}"
    assert project.startswith("datariver-prep39083-it-")
    release = deploy.ReleaseIdentity("a" * 40, "b" * 40, "linux/amd64", 39083, project)
    operator = tmp_path / ".env.prep"
    optional = tmp_path / ".env.prep.optional"
    runtime = tmp_path / ".env.prep.runtime"
    marker = tmp_path / "accepted.json"
    attempt_path = tmp_path / "deploy-attempt.json"
    monkeypatch.setattr(deploy, "ATTEMPT_RECEIPT", attempt_path)
    _private_env(operator, _operator_values())
    runner = deploy.Runner()

    fresh = deploy.inspect_target_inventory(
        runner,
        release,
        runtime_path=runtime,
        accepted_marker_path=marker,
    )
    assert deploy.classify_target_state(fresh) is deploy.TargetState.FRESH_CLEAN

    old_bundle = deploy.reconcile_environment(
        release,
        operator_path=operator,
        optional_path=optional,
        runtime_path=runtime,
        random_token=lambda count: "o" * count,
    )
    old_bundle = _effective(old_bundle, project)
    cleanup_bundle = old_bundle
    try:
        with deploy.private_effective_environment(old_bundle.effective) as env_file:
            old_prefix = deploy.compose_prefix(release, env_file)
            runner.run([*old_prefix, "up", "-d", "--wait", "pgvector", "neo4j"])
            runner.run([*old_prefix, "rm", "--stop", "--force", "pgvector", "neo4j"])
        runtime.unlink()

        residual = deploy.inspect_target_inventory(
            runner,
            release,
            runtime_path=runtime,
            accepted_marker_path=marker,
        )
        assert deploy.classify_target_state(residual) is (
            deploy.TargetState.FAILED_FIRST_INSTALL_REQUIRES_INSPECTION
        )
        inspection = deploy.reconcile_environment(
            release,
            operator_path=operator,
            optional_path=optional,
            runtime_path=runtime,
            target_state=deploy.TargetState.FAILED_FIRST_INSTALL_REQUIRES_INSPECTION,
            random_token=lambda _count: pytest.fail("inspection must not generate secrets"),
        )
        inspection = _effective(inspection, project)
        assert (
            deploy.prove_failed_install_recoverable(
                runner,
                release,
                inspection,
                residual,
            )
            is deploy.TargetState.FAILED_FIRST_INSTALL_RECOVERABLE
        )

        recovered = deploy.reconcile_environment(
            release,
            operator_path=operator,
            optional_path=optional,
            runtime_path=runtime,
            target_state=deploy.TargetState.FAILED_FIRST_INSTALL_RECOVERABLE,
            random_token=lambda count: "n" * count,
        )
        recovered = _effective(recovered, project)
        cleanup_bundle = recovered
        assert stat.S_IMODE(runtime.stat().st_mode) == 0o600
        with deploy.private_effective_environment(recovered.effective) as env_file:
            recovered_prefix = deploy.compose_prefix(release, env_file)
            deploy.reconcile_recoverable_postgres_credential(runner, recovered_prefix, recovered)
            runner.run([*recovered_prefix, "up", "-d", "--wait", "--force-recreate", "pgvector"])
            runner.run(
                [
                    *deploy._postgres_local_command(
                        recovered_prefix,
                        recovered.effective["POC_POSTGRES_DB"],
                        recovered.effective["POC_POSTGRES_USER"],
                    ),
                    "--command",
                    "INSERT INTO poc_state(scope, value) "
                    "VALUES ('integration-durable', '{}'::jsonb);",
                ]
            )

            config = deploy.compose_config(runner, recovered_prefix)
            receipt = deploy.write_attempt_receipt(
                release,
                "c" * 40,
                recovered,
                deploy.compose_volume_identities(config),
                phase="PREPARED",
            )
            deploy.advance_attempt_phase(receipt, "SMOKE_FAILED")

        owned_incomplete = deploy.inspect_target_inventory(
            runner,
            release,
            runtime_path=runtime,
            accepted_marker_path=marker,
            attempt_receipt_path=attempt_path,
        )
        assert deploy.classify_target_state(owned_incomplete) is (
            deploy.TargetState.EXISTING_OWNED_INCOMPLETE
        )
        with deploy.private_effective_environment(recovered.effective) as env_file:
            retry_prefix = deploy.compose_prefix(release, env_file)
            assert (
                deploy.inspect_postgres_durable_rows(
                    runner,
                    retry_prefix,
                    database=recovered.effective["POC_POSTGRES_DB"],
                    username=recovered.effective["POC_POSTGRES_USER"],
                )["poc_state"]
                == 1
            )

        _marker(marker, release)
        deploy.advance_attempt_phase(deploy._attempt_receipt(attempt_path), "ACCEPTED")
        accepted_running = deploy.inspect_target_inventory(
            runner,
            release,
            runtime_path=runtime,
            accepted_marker_path=marker,
            attempt_receipt_path=attempt_path,
        )
        assert deploy.classify_target_state(accepted_running) is (
            deploy.TargetState.EXISTING_ACCEPTED_RUNNING
        )
        running_update_release = deploy.ReleaseIdentity(
            "d" * 40,
            "e" * 40,
            "linux/amd64",
            39083,
            project,
        )
        assert (
            deploy.classify_target_state(
                deploy.inspect_target_inventory(
                    runner,
                    running_update_release,
                    runtime_path=runtime,
                    accepted_marker_path=marker,
                    attempt_receipt_path=attempt_path,
                )
            )
            is deploy.TargetState.EXISTING_ACCEPTED_RUNNING
        )
        with deploy.private_effective_environment(recovered.effective) as env_file:
            prefix = deploy.compose_prefix(release, env_file)
            runner.run([*prefix, "stop", "pgvector", "neo4j"])
        accepted_stopped = deploy.inspect_target_inventory(
            runner,
            release,
            runtime_path=runtime,
            accepted_marker_path=marker,
            attempt_receipt_path=attempt_path,
        )
        assert deploy.classify_target_state(accepted_stopped) is (
            deploy.TargetState.EXISTING_ACCEPTED_STOPPED
        )
        assert deploy.classify_target_state(accepted_stopped) is (
            deploy.TargetState.EXISTING_ACCEPTED_STOPPED
        )  # exact same release rerun
        stopped_update = deploy.inspect_target_inventory(
            runner,
            running_update_release,
            runtime_path=runtime,
            accepted_marker_path=marker,
            attempt_receipt_path=attempt_path,
        )
        assert deploy.classify_target_state(stopped_update) is (
            deploy.TargetState.EXISTING_ACCEPTED_STOPPED
        )

        marker.unlink()
        attempt_path.unlink()
        ambiguous = deploy.inspect_target_inventory(
            runner,
            release,
            runtime_path=runtime,
            accepted_marker_path=marker,
        )
        inspection_with_secret = deploy.reconcile_environment(
            release,
            operator_path=operator,
            optional_path=optional,
            runtime_path=runtime,
            target_state=deploy.TargetState.FAILED_FIRST_INSTALL_REQUIRES_INSPECTION,
            random_token=lambda _count: pytest.fail("preserved secret must be reused"),
        )
        inspection_with_secret = _effective(inspection_with_secret, project)
        with pytest.raises(deploy.PrepError) as captured:
            deploy.prove_failed_install_recoverable(
                runner,
                release,
                inspection_with_secret,
                ambiguous,
            )
        assert captured.value.code == "PREP_EXISTING_STATE_REQUIRES_OPERATOR_RECOVERY"
    finally:
        with deploy.private_effective_environment(cleanup_bundle.effective) as env_file:
            cleanup_prefix = deploy.compose_prefix(release, env_file)
            runner.run([*cleanup_prefix, "down", "--volumes", "--remove-orphans"], check=False)


@pytest.mark.skipif(
    not _FULL_ENABLED,
    reason="explicit full PREP39083 failed-smoke Docker integration is required",
)
def test_failed_smoke_resumes_with_same_deploy_command_without_duplicate_bootstrap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = f"datariver-prep39083-retry-{uuid4().hex[:10]}"
    port = int(_free_port())
    runner = deploy.Runner()
    product = runner.output(["git", "rev-parse", "HEAD"])
    release = deploy.ReleaseIdentity(product, "b" * 40, "linux/amd64", port, project)
    operator = tmp_path / ".env.prep"
    optional = tmp_path / ".env.prep.optional"
    runtime = tmp_path / ".env.prep.runtime"
    accepted = tmp_path / "accepted.json"
    attempt = tmp_path / "deploy-attempt.json"
    smoke_failure = tmp_path / "smoke-failure.json"
    runtime_root = tmp_path / "runtime"
    monkeypatch.setattr(deploy, "ACCEPTED_MARKER", accepted)
    monkeypatch.setattr(deploy, "ATTEMPT_RECEIPT", attempt)
    monkeypatch.setattr(deploy, "SMOKE_FAILURE", smoke_failure)
    monkeypatch.setattr(deploy, "RUNTIME_ROOT", runtime_root)
    _private_env(operator, _portable_operator_values(f"http://127.0.0.1:{port}"))
    bundle = deploy.reconcile_environment(
        release,
        operator_path=operator,
        optional_path=optional,
        runtime_path=runtime,
        random_token=lambda count: "r" * count,
    )
    effective = dict(bundle.effective)
    effective.update(
        {
            "POC_PLATFORM": "linux/amd64",
            "POC_SHARED_NETWORK": f"{project}-services",
            "POC_POSTGRES_HOST_PORT": _free_port(),
            "POC_NEO4J_HTTP_PORT": _free_port(),
            "POC_REDIS_PORT": _free_port(),
            "POC_PORT": str(port),
            "POC_PUBLIC_ORIGIN": f"http://127.0.0.1:{port}",
        }
    )
    bundle = replace(bundle, effective=effective)
    source = {"handoff_commit": product}
    before_39080 = deploy.snapshot_39080(runner)
    inventory = deploy.inspect_target_inventory(
        runner,
        release,
        runtime_path=runtime,
        accepted_marker_path=accepted,
        attempt_receipt_path=attempt,
    )
    preparation = deploy.DeploymentPreparation(runner, source, inventory, before_39080)
    monkeypatch.setattr(
        deploy,
        "run_provider_preflight",
        lambda _runner, _prefix: {
            "status": "PASS",
            "k9_studio": "DEFERRED",
        },
    )
    smoke_attempts = 0

    def controlled_smoke(*_arguments: object, **_keywords: object) -> None:
        nonlocal smoke_attempts
        smoke_attempts += 1
        if smoke_attempts == 1:
            raise deploy.PrepError(
                "RUNTIME_SMOKE",
                "PREP_SMOKE_GENERAL_PROVIDER_FAILED",
                "Intentional isolated smoke failure.",
                "Retry the same command.",
            )

    monkeypatch.setattr(deploy, "run_smoke", controlled_smoke)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "admin")
    passwords = iter(
        (
            "correct horse battery staple",
            "correct horse battery staple",
            "correct horse battery staple",
        )
    )
    monkeypatch.setattr(deploy.getpass, "getpass", lambda _prompt="": next(passwords))
    cleanup_bundle = bundle
    try:
        with pytest.raises(deploy.PrepError) as first_failure:
            deploy.deploy(release, bundle, preparation)
        assert first_failure.value.code == "PREP_SMOKE_GENERAL_PROVIDER_FAILED"
        assert not accepted.exists()
        assert deploy._attempt_receipt(attempt)["phase"] == "SMOKE_FAILED"

        retry_inventory = deploy.inspect_target_inventory(
            runner,
            release,
            runtime_path=runtime,
            accepted_marker_path=accepted,
            attempt_receipt_path=attempt,
        )
        assert deploy.classify_target_state(retry_inventory) is (
            deploy.TargetState.EXISTING_OWNED_INCOMPLETE
        )
        retry_bundle = deploy.reconcile_environment(
            release,
            operator_path=operator,
            optional_path=optional,
            runtime_path=runtime,
            target_state=deploy.TargetState.EXISTING_OWNED_INCOMPLETE,
            random_token=lambda _count: pytest.fail("retry must reuse generated secrets"),
        )
        retry_bundle = replace(retry_bundle, effective=effective)
        cleanup_bundle = retry_bundle
        retry_preparation = deploy.DeploymentPreparation(
            runner,
            source,
            retry_inventory,
            before_39080,
        )
        deploy.deploy(release, retry_bundle, retry_preparation)
        assert accepted.is_file()
        assert deploy._attempt_receipt(attempt)["phase"] == "ACCEPTED"
        assert smoke_attempts == 2
        with deploy.private_effective_environment(retry_bundle.effective) as env_file:
            inspected = deploy.inspect_bootstrap(
                runner,
                deploy.compose_prefix(release, env_file),
            )
        assert inspected["administrator_record_count"] == 1
        assert inspected["user_record_count"] == 2
        assert [item["name"] for item in inspected["services"]] == ["MCP"]
    finally:
        with deploy.private_effective_environment(cleanup_bundle.effective) as env_file:
            prefix = deploy.compose_prefix(release, env_file)
            runner.run([*prefix, "down", "--volumes", "--remove-orphans"], check=False)
