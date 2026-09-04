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
WILDCARD_BIND_HOST = "0.0.0.0"  # noqa: S104 - explicit polluted/canonical test value
POLLUTED_PARENT_ENVIRONMENT = {
    "POC_IMAGE_TAG": "0" * 40,
    "POC_SOURCE_COMMIT": "0" * 40,
    "PREP_RELEASE_PRODUCT_SHA": "0" * 40,
    "POC_BIND_HOST": "127.0.0.1",
    "POC_STATE_BIND_HOST": WILDCARD_BIND_HOST,
    "POC_PORT": "39999",
    "POC_PLATFORM": "linux/arm64",
    "DATAHUB_GMS_URL": "http://wrong.invalid",
    "DATAHUB_GMS_TOKEN": "wrong-token",
    "LLM_CHAT_URL": "http://wrong-chat.invalid",
    "LLM_EMBEDDING_URL": "http://wrong-embedding.invalid",
    "LLM_RERANKER_URL": "http://wrong-reranker.invalid",
    "POC_MCL_KAFKA_BROKERS": "wrong-broker:9092",
    "COMPOSE_PROJECT_NAME": "wrong-project",
    "COMPOSE_FILE": "/wrong/compose.yaml",
    "COMPOSE_ENV_FILES": "/wrong/environment",
    "DOCKER_DEFAULT_PLATFORM": "linux/arm64",
}


def _pollute_parent_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in POLLUTED_PARENT_ENVIRONMENT.items():
        monkeypatch.setenv(key, value)


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


def _build_product_artifact(
    runner: Any,
    product: str,
    target: Path,
) -> Any:
    image = f"datariver-poc:{product}"
    runner.run(
        [
            "docker",
            "buildx",
            "build",
            "--platform",
            "linux/amd64",
            "--pull=false",
            "--load",
            "--build-arg",
            f"POC_SOURCE_COMMIT={product}",
            "--file",
            os.fspath(ROOT / "deploy/poc/Dockerfile.example"),
            "--tag",
            image,
            os.fspath(ROOT),
        ]
    )
    runner.run(
        [
            "docker",
            "image",
            "save",
            "--platform",
            "linux/amd64",
            "--output",
            os.fspath(target),
            image,
        ]
    )
    return deploy.inspect_web_archive(target)


def _archive_existing_product(runner: Any, product: str, target: Path) -> Any:
    image = f"datariver-poc:{product}"
    inspected = json.loads(
        runner.output(["docker", "image", "inspect", "--platform", "linux/amd64", image])
    )[0]
    labels = inspected.get("Config", {}).get("Labels", {})
    assert labels.get("org.opencontainers.image.revision") == product
    runner.run(
        [
            "docker",
            "image",
            "save",
            "--platform",
            "linux/amd64",
            "--output",
            os.fspath(target),
            image,
        ]
    )
    return deploy.inspect_web_archive(target)


@pytest.mark.skipif(
    not _ENABLED,
    reason="explicit isolated PREP39083 Docker integration is required",
)
def test_foreign_checkout_web_adoption_identity_fence_and_failure_preservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = f"datariver-prep39083-owner-{uuid4().hex[:10]}"
    old_product = f"{uuid4().hex}{uuid4().hex[:8]}"
    target_product = f"{uuid4().hex}{uuid4().hex[:8]}"
    checkout_a = tmp_path / "checkout-a"
    checkout_b = tmp_path / "checkout-b"
    checkout_a.mkdir()
    checkout_b.mkdir()
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        "FROM python:3.12.12-slim-bookworm\n"
        "ARG PRODUCT\n"
        "LABEL org.opencontainers.image.revision=$PRODUCT\n"
        'CMD ["python", "-c", "import time; time.sleep(3600)"]\n',
        encoding="utf-8",
    )
    runner = deploy.Runner(environment=deploy.child_environment({}))
    for product in (old_product, target_product):
        runner.run(
            [
                "docker",
                "build",
                "--pull=false",
                "--build-arg",
                f"PRODUCT={product}",
                "--tag",
                f"datariver-poc:{product}",
                "--file",
                dockerfile,
                tmp_path,
            ]
        )
    compose = (
        "services:\n"
        "  web:\n"
        "    image: datariver-poc:${POC_IMAGE_TAG}\n"
        '    command: ["python", "-c", "import time; time.sleep(3600)"]\n'
        "    networks: [services]\n"
        "  state:\n"
        "    image: python:3.12.12-slim-bookworm\n"
        '    command: ["python", "-c", "import time; time.sleep(3600)"]\n'
        "    volumes:\n"
        "      - pgvector-data:/state/pg\n"
        "      - neo4j-data:/state/neo4j\n"
        "      - neo4j-logs:/state/logs\n"
        "    networks: [services]\n"
        "networks:\n"
        "  services:\n"
        f"    name: {project}-services\n"
        "volumes:\n"
        "  pgvector-data:\n"
        f"    name: {project}_pgvector-data\n"
        "  neo4j-data:\n"
        f"    name: {project}_neo4j-data\n"
        "  neo4j-logs:\n"
        f"    name: {project}_neo4j-logs\n"
    )
    for checkout in (checkout_a, checkout_b):
        (checkout / "base.yaml").write_text(compose, encoding="utf-8")
        (checkout / "artifact.yaml").write_text("services: {}\n", encoding="utf-8")
    env_a = checkout_a / "runtime.env"
    env_b = checkout_b / "runtime.env"
    _private_env(env_a, {"POC_IMAGE_TAG": old_product})
    _private_env(env_b, {"POC_IMAGE_TAG": target_product})
    prefix_a = [
        "docker",
        "compose",
        "--project-name",
        project,
        "--env-file",
        os.fspath(env_a),
        "--file",
        os.fspath(checkout_a / "base.yaml"),
        "--file",
        os.fspath(checkout_a / "artifact.yaml"),
    ]
    prefix_b = [
        "docker",
        "compose",
        "--project-name",
        project,
        "--env-file",
        os.fspath(env_b),
        "--file",
        os.fspath(checkout_b / "base.yaml"),
        "--file",
        os.fspath(checkout_b / "artifact.yaml"),
    ]
    release = deploy.ReleaseIdentity(target_product, "b" * 40, "linux/amd64", 39083, project)
    runtime = {
        "POC_IMAGE_TAG": target_product,
        "POC_SOURCE_COMMIT": target_product,
        "PREP_RELEASE_PRODUCT_SHA": target_product,
        "PREP_RELEASE_EVIDENCE_SHA": release.evidence_sha,
    }
    bundle = deploy.EnvironmentBundle(
        {}, {}, runtime, runtime, (), deploy.TargetState.EXISTING_OWNED_INCOMPLETE, "REQUIRED"
    )
    attempt_path = tmp_path / "deploy-attempt.json"
    secret_file = tmp_path / "generated.env"
    _private_env(secret_file, {"SECRET": "preserved"})
    secret_before = secret_file.read_bytes()
    monkeypatch.setattr(deploy, "ROOT", checkout_b)
    monkeypatch.setattr(deploy, "BASE_COMPOSE", checkout_b / "base.yaml")
    monkeypatch.setattr(deploy, "PREP_ARTIFACT_COMPOSE", checkout_b / "artifact.yaml")
    monkeypatch.setattr(deploy, "ATTEMPT_RECEIPT", attempt_path)
    monkeypatch.setattr(deploy, "_git_is_ancestor", lambda *_a, **_k: True)
    host_lock = None
    try:
        runner.run([*prefix_a, "up", "-d", "state", "web"])
        host_lock = deploy.host_project_deployment_lock(project, root=tmp_path / "host-locks")
        host_lock.__enter__()
        with pytest.raises(deploy.PrepError) as concurrent:
            with deploy.host_project_deployment_lock(project, root=tmp_path / "host-locks"):
                pass
        assert concurrent.value.code == "PREP_HOST_PROJECT_DEPLOY_ALREADY_ACTIVE"
        state_container_before = runner.output([*prefix_a, "ps", "-q", "state"])
        volume_names = deploy.canonical_volume_identities(release)
        volume_ids_before = {
            name: runner.output(["docker", "volume", "inspect", "--format", "{{.Name}}", name])
            for name in volume_names
        }
        old_identity = deploy.inspect_running_web_identity(runner, release)
        assert old_identity is not None
        assert old_identity.oci_revision == old_product
        assert old_identity.working_dir_same is False
        config = {
            "services": {"web": {"image": f"datariver-poc:{target_product}"}},
            "volumes": {
                "pgvector-data": {"name": f"{project}_pgvector-data"},
                "neo4j-data": {"name": f"{project}_neo4j-data"},
                "neo4j-logs": {"name": f"{project}_neo4j-logs"},
            },
            "networks": {"services": {"name": f"{project}-services"}},
        }
        inventory = deploy.TargetInventory(
            False,
            False,
            True,
            True,
            (deploy.TargetContainer(old_identity.container_id, "web", True),),
            tuple(
                deploy.TargetVolume(name, logical)
                for name, logical in zip(
                    volume_names, deploy.PREP_VOLUME_LOGICAL_NAMES, strict=True
                )
            ),
            (f"{project}-services",),
        )
        previous = {"product_sha": target_product, "resumed_from_product_sha": old_product}
        assert (
            deploy.prove_foreign_web_owner_adoptable(runner, release, inventory, config, previous)
            is True
        )
        runner.run([*prefix_b, "up", "-d", "--no-recreate", "state"])
        assert runner.output([*prefix_b, "ps", "-q", "state"]) == state_container_before
        runner.run(
            deploy.web_start_command(
                prefix_b,
                deploy.TargetState.EXISTING_OWNED_INCOMPLETE,
                force_recreate=True,
            )
        )
        applied = deploy.verify_applied_web_identity(runner, release, bundle, prefix_b, config)
        assert applied.oci_revision == target_product
        assert applied.working_dir_same is True
        assert applied.config_files_same is True
        receipt_runtime = {
            "POC_MCP_SERVICE_TOKEN": "mcp-secret",
            "POC_POSTGRES_PASSWORD": "pg-secret",
            "NEO4J_PASSWORD": "neo4j-secret",
        }
        receipt_bundle = replace(bundle, runtime=receipt_runtime)
        receipt = deploy.write_attempt_receipt(
            release,
            "c" * 40,
            receipt_bundle,
            volume_names,
            phase="PREPARED",
            foreign_owner_adopted=True,
        )
        receipt = deploy.advance_attempt_identity(receipt, "applied_product_sha", target_product)
        receipt = deploy.advance_attempt_identity(receipt, "smoke_product_sha", target_product)
        receipt = deploy.advance_attempt_identity(
            receipt, "post_failure_product_sha", target_product
        )
        receipt = deploy.advance_attempt_phase(receipt, "SMOKE_FAILED")
        assert receipt["target_product_sha"] == target_product
        assert receipt["applied_product_sha"] == target_product
        assert receipt["smoke_product_sha"] == target_product
        assert receipt["post_failure_product_sha"] == target_product
        assert receipt["foreign_owner_adopted"] is True
        assert receipt["rollback_attempted"] is False
        assert receipt["rollback_completed"] is False
        assert secret_file.read_bytes() == secret_before
        assert {
            name: runner.output(["docker", "volume", "inspect", "--format", "{{.Name}}", name])
            for name in volume_names
        } == volume_ids_before

        runner.run([*prefix_a, "up", "-d", "--no-deps", "--force-recreate", "web"])
        with pytest.raises(deploy.PrepError) as replaced_runtime:
            deploy.verify_web_runtime_stable(runner, release, applied)
        assert replaced_runtime.value.code == "PREP_FOREIGN_COMPOSE_REPLACEMENT_DETECTED"
    finally:
        if host_lock is not None:
            host_lock.__exit__(None, None, None)
        runner.run([*prefix_b, "down", "--volumes", "--remove-orphans"], check=False)
        runner.run(["docker", "image", "rm", f"datariver-poc:{old_product}"], check=False)
        runner.run(["docker", "image", "rm", f"datariver-poc:{target_product}"], check=False)


@pytest.mark.skipif(
    not _ENABLED,
    reason="explicit isolated PREP39083 Docker integration is required",
)
def test_doctor_bootstraps_only_exact_image_and_runs_matrix_without_product_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pollute_parent_environment(monkeypatch)
    project = f"datariver-prep39083-doctor-{uuid4().hex[:10]}"
    product = f"{uuid4().hex}{uuid4().hex[:8]}"
    runner = deploy.Runner(environment=deploy.child_environment({}))
    artifact_path = tmp_path / "exact-product.tar"
    artifact = _build_product_artifact(runner, product, artifact_path)
    release = deploy.ReleaseIdentity(
        product,
        "b" * 40,
        "linux/amd64",
        39083,
        project,
        artifact,
    )
    monkeypatch.setattr(deploy, "promoted_web_artifact_path", lambda _artifact: artifact_path)
    operator = tmp_path / ".env.prep"
    runtime = tmp_path / ".env.prep.runtime"
    attempt = tmp_path / "deploy-attempt.json"
    accepted = tmp_path / "accepted.json"
    _private_env(operator, _portable_operator_values("https://doctor.integration.invalid"))
    bundle = deploy.reconcile_environment(
        release,
        operator_path=operator,
        optional_path=tmp_path / ".env.prep.optional",
        runtime_path=runtime,
        target_state=deploy.TargetState.FAILED_FIRST_INSTALL_REQUIRES_INSPECTION,
        persist_runtime=False,
        random_token=lambda _count: pytest.fail("doctor must not generate runtime secrets"),
    )
    assert not runtime.exists()
    bundle = _effective(bundle, project)
    bundle = replace(bundle, effective={**bundle.effective, "POC_PORT": "39083"})
    runner.environment = deploy.child_environment(bundle.effective)
    assert runner.environment["POC_IMAGE_TAG"] == product
    assert runner.environment["POC_BIND_HOST"] == WILDCARD_BIND_HOST
    assert runner.environment["POC_STATE_BIND_HOST"] == "127.0.0.1"
    assert "COMPOSE_FILE" not in runner.environment
    assert "COMPOSE_ENV_FILES" not in runner.environment
    assert "DOCKER_DEFAULT_PLATFORM" not in runner.environment
    image = f"datariver-poc:{product}"
    try:
        runner.run(["docker", "image", "rm", image])
        with deploy.private_effective_environment(bundle.effective) as env_file:
            prefix = deploy.compose_prefix(release, env_file)
            config = deploy.compose_config(runner, prefix)
            deploy.validate_compose_release_contract(config, release, bundle.effective)
            assert deploy.resolve_web_image(config) == image
            assert runner.run(["docker", "image", "inspect", image], check=False).returncode != 0
            assert (
                deploy.prepare_exact_web_image(
                    runner,
                    prefix,
                    image,
                    release,
                    doctor=True,
                )
                == "LOADED_EXACT_ARTIFACT"
            )
            matrix = deploy.collect_provider_preflight(
                runner,
                image,
                env_file,
                bundle.effective,
            )
            assert matrix["contract"] == "DATARIVER_PREP39083_PROVIDER_PREFLIGHT_MATRIX_V1"
            assert set(matrix["stages"]) == set(deploy.DOCTOR_PREFLIGHT_STAGES)
            assert matrix["stages"]["WEB_INTRANET"] == {"status": "READY"}
            with pytest.raises(deploy.PrepError) as fail_fast:
                deploy.run_provider_preflight(
                    runner,
                    image,
                    env_file,
                    bundle.effective,
                )
            assert fail_fast.value.code == "PREP_PREFLIGHT_DATAHUB_CONNECTIVITY_FAILED"
            assert not attempt.exists() and not accepted.exists() and not runtime.exists()
            assert runner.run([*prefix, "ps", "-q"], check=False).stdout.strip() == ""
            assert (
                runner.run(
                    [
                        "docker",
                        "volume",
                        "ls",
                        "--filter",
                        f"label=com.docker.compose.project={project}",
                        "--quiet",
                    ],
                    check=False,
                ).stdout.strip()
                == ""
            )
    finally:
        with deploy.private_effective_environment(bundle.effective) as env_file:
            prefix = deploy.compose_prefix(release, env_file)
            runner.run([*prefix, "down", "--remove-orphans"], check=False)
        runner.run(["docker", "image", "rm", image], check=False)


@pytest.mark.skipif(
    not _ENABLED,
    reason="explicit isolated PREP39083 Docker integration is required",
)
def test_unified_state_machine_and_non_destructive_failed_install_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pollute_parent_environment(monkeypatch)
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
    runner = deploy.Runner(environment=deploy.child_environment({}))

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
    runner.environment = deploy.child_environment(old_bundle.effective)
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
        runner.environment = deploy.child_environment(inspection.effective)
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
        runner.environment = deploy.child_environment(recovered.effective)
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
            deploy.advance_attempt_phase(receipt, "STATE_SERVICES_READY")

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
        runner.environment = deploy.child_environment(inspection_with_secret.effective)
        with pytest.raises(deploy.PrepError) as captured:
            deploy.prove_failed_install_recoverable(
                runner,
                release,
                inspection_with_secret,
                ambiguous,
            )
        assert captured.value.code == "PREP_EXISTING_STATE_REQUIRES_OPERATOR_RECOVERY"
    finally:
        runner.environment = deploy.child_environment(cleanup_bundle.effective)
        with deploy.private_effective_environment(cleanup_bundle.effective) as env_file:
            cleanup_prefix = deploy.compose_prefix(release, env_file)
            runner.run([*cleanup_prefix, "down", "--volumes", "--remove-orphans"], check=False)


@pytest.mark.skipif(
    not _FULL_ENABLED,
    reason="explicit full PREP39083 failed-smoke Docker integration is required",
)
def test_current_v2_smoke_failed_resumes_across_descendant_without_duplicate_bootstrap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pollute_parent_environment(monkeypatch)
    project = f"datariver-prep39083-retry-{uuid4().hex[:10]}"
    port = int(_free_port())
    runner = deploy.Runner(environment=deploy.child_environment({}))
    product_b = runner.output(["git", "rev-parse", "HEAD"])
    product_a = runner.output(["git", "rev-parse", "HEAD^"])
    assert (
        runner.run(
            ["git", "merge-base", "--is-ancestor", product_a, product_b],
            check=False,
        ).returncode
        == 0
    )
    artifact_paths = {product: tmp_path / f"{product}.tar" for product in (product_a, product_b)}
    artifacts = {
        product: _build_product_artifact(runner, product, artifact_paths[product])
        for product in (product_a, product_b)
    }
    release_a = deploy.ReleaseIdentity(
        product_a, "a" * 40, "linux/amd64", port, project, artifacts[product_a]
    )
    release_b = deploy.ReleaseIdentity(
        product_b, "b" * 40, "linux/amd64", port, project, artifacts[product_b]
    )
    monkeypatch.setattr(
        deploy,
        "promoted_web_artifact_path",
        lambda artifact: artifact_paths[artifact.product_sha],
    )
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
        release_a,
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
    runner.environment = deploy.child_environment(bundle.effective)
    assert runner.environment["POC_IMAGE_TAG"] == product_a
    assert runner.environment["POC_BIND_HOST"] == WILDCARD_BIND_HOST
    assert runner.environment["POC_STATE_BIND_HOST"] == "127.0.0.1"
    assert runner.environment["POC_PORT"] == str(port)
    assert runner.environment["DATAHUB_GMS_URL"] == "http://127.0.0.1:9"
    assert runner.environment["LLM_CHAT_URL"] == "http://127.0.0.1:9"
    assert "COMPOSE_FILE" not in runner.environment
    assert "COMPOSE_ENV_FILES" not in runner.environment
    assert "DOCKER_DEFAULT_PLATFORM" not in runner.environment
    source_a = {"handoff_commit": product_a}
    source_b = {"handoff_commit": product_b}
    before_39080 = deploy.snapshot_39080(runner)
    inventory = deploy.inspect_target_inventory(
        runner,
        release_a,
        runtime_path=runtime,
        accepted_marker_path=accepted,
        attempt_receipt_path=attempt,
    )
    preparation = deploy.DeploymentPreparation(runner, source_a, inventory, before_39080)

    monkeypatch.setattr(deploy, "verify_source_identity", lambda _release: source_a)
    monkeypatch.setattr(deploy, "require_prep_platform", lambda _runner: None)
    with pytest.raises(deploy.PrepError):
        deploy.doctor(release_a, bundle)
    assert not accepted.exists() and not attempt.exists()
    assert not runtime_root.exists() or list(runtime_root.iterdir()) == []
    assert (
        runner.run(
            [
                "docker",
                "volume",
                "ls",
                "--filter",
                f"label=com.docker.compose.project={project}",
                "--quiet",
            ],
            check=False,
        ).stdout.strip()
        == ""
    )

    def failed_provider_preflight(*_arguments: object, **_keywords: object) -> dict[str, str]:
        raise deploy.PrepError(
            "PROVIDER_PREFLIGHT",
            "PREP_PREFLIGHT_DATAHUB_CONNECTIVITY_FAILED",
            "Intentional isolated provider failure.",
            "Correct the provider and retry.",
        )

    monkeypatch.setattr(deploy, "run_provider_preflight", failed_provider_preflight)
    with pytest.raises(deploy.PrepError) as provider_failure:
        deploy.deploy(release_a, bundle, preparation)
    assert provider_failure.value.code == "PREP_PREFLIGHT_DATAHUB_CONNECTIVITY_FAILED"
    assert not accepted.exists() and not attempt.exists()
    assert (
        runner.run(
            [
                "docker",
                "volume",
                "ls",
                "--filter",
                f"label=com.docker.compose.project={project}",
                "--quiet",
            ],
            check=False,
        ).stdout.strip()
        == ""
    )
    monkeypatch.setattr(
        deploy,
        "run_provider_preflight",
        lambda _runner, _image, _env_file, _effective: {
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
            deploy.deploy(release_a, bundle, preparation)
        assert first_failure.value.code == "PREP_SMOKE_GENERAL_PROVIDER_FAILED"
        assert not accepted.exists()
        assert deploy._attempt_receipt(attempt)["phase"] == "SMOKE_FAILED"

        retry_inventory = deploy.inspect_target_inventory(
            runner,
            release_b,
            runtime_path=runtime,
            accepted_marker_path=accepted,
            attempt_receipt_path=attempt,
        )
        assert deploy.classify_target_state(retry_inventory) is (
            deploy.TargetState.EXISTING_OWNED_INCOMPLETE
        )
        previous_attempt = deploy.validate_owned_attempt(
            runner,
            release_b,
            product_b,
            retry_inventory,
            deploy.read_env_file(runtime, private=True, label=".env.prep.runtime"),
            bundle.k9_mode,
        )
        preserved_runtime = deploy.read_env_file(
            runtime,
            private=True,
            label=".env.prep.runtime",
        )
        preserved_secrets = {
            key: preserved_runtime[key] for key in deploy.TARGET_OWNERSHIP_SECRET_KEYS
        }
        retry_bundle = deploy.reconcile_environment(
            release_b,
            operator_path=operator,
            optional_path=optional,
            runtime_path=runtime,
            target_state=deploy.TargetState.EXISTING_OWNED_INCOMPLETE,
            random_token=lambda _count: pytest.fail("retry must reuse generated secrets"),
        )
        retry_effective = dict(retry_bundle.effective)
        for key in (
            "POC_PLATFORM",
            "POC_SHARED_NETWORK",
            "POC_POSTGRES_HOST_PORT",
            "POC_NEO4J_HTTP_PORT",
            "POC_REDIS_PORT",
            "POC_PORT",
            "POC_PUBLIC_ORIGIN",
        ):
            retry_effective[key] = effective[key]
        retry_bundle = replace(retry_bundle, effective=retry_effective)
        runner.environment = deploy.child_environment(retry_bundle.effective)
        cleanup_bundle = retry_bundle
        retry_preparation = deploy.DeploymentPreparation(
            runner,
            source_b,
            retry_inventory,
            before_39080,
            previous_attempt,
        )
        deploy.deploy(release_b, retry_bundle, retry_preparation)
        assert accepted.is_file()
        final_receipt = deploy._attempt_receipt(attempt)
        assert final_receipt["phase"] == "ACCEPTED"
        assert final_receipt["resumed_from_product_sha"] == product_a
        final_runtime = deploy.read_env_file(
            runtime,
            private=True,
            label=".env.prep.runtime",
        )
        assert {
            key: final_runtime[key] for key in deploy.TARGET_OWNERSHIP_SECRET_KEYS
        } == preserved_secrets
        assert smoke_attempts == 2
        with deploy.private_effective_environment(retry_bundle.effective) as env_file:
            inspected = deploy.inspect_bootstrap(
                runner,
                deploy.compose_prefix(release_b, env_file),
            )
        assert inspected["administrator_record_count"] == 1
        assert inspected["user_record_count"] == 3
        assert [item["name"] for item in inspected["services"]] == ["K9", "MCP"]
    finally:
        runner.environment = deploy.child_environment(cleanup_bundle.effective)
        with deploy.private_effective_environment(cleanup_bundle.effective) as env_file:
            prefix = deploy.compose_prefix(release_b, env_file)
            runner.run([*prefix, "down", "--volumes", "--remove-orphans"], check=False)


@pytest.mark.skipif(
    not _FULL_ENABLED,
    reason="explicit full PREP39083 cross-release Docker integration is required",
)
def test_legacy_smoke_failed_resumes_across_descendant_fixed_contract_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = f"datariver-prep39083-cross-{uuid4().hex[:10]}"
    port = int(_free_port())
    runner = deploy.Runner()
    current_handoff = runner.output(["git", "rev-parse", "HEAD"])
    timeout_change = runner.output(
        [
            "git",
            "log",
            "-S",
            '"POC_LLM_TIMEOUT_MS": "120000"',
            "--format=%H",
            "-1",
            "--",
            "deploy/prep39083/env-contract.json",
        ]
    )
    previous_handoff = runner.output(["git", "rev-parse", f"{timeout_change}^"])
    historical_contract = json.loads(
        runner.output(
            [
                "git",
                "show",
                f"{previous_handoff}:deploy/prep39083/env-contract.json",
            ]
        )
    )
    assert historical_contract["ownership"]["FIXED"]["POC_LLM_TIMEOUT_MS"] == "15000"
    current_contract_path = ROOT / "deploy/prep39083/env-contract.json"
    current_contract = json.loads(current_contract_path.read_text())
    assert current_contract["ownership"]["FIXED"]["POC_LLM_TIMEOUT_MS"] == "120000"
    setup_contract = json.loads(json.dumps(current_contract))
    setup_contract["ownership"]["FIXED"]["POC_LLM_TIMEOUT_MS"] = "15000"
    setup_contract_path = tmp_path / "env-contract.setup.json"
    setup_contract_path.write_text(json.dumps(setup_contract), encoding="utf-8")

    artifact_paths = {
        product: tmp_path / f"{product}.tar" for product in (previous_handoff, current_handoff)
    }
    artifacts = {
        product: _build_product_artifact(runner, product, artifact_paths[product])
        for product in (previous_handoff, current_handoff)
    }
    release_a = deploy.ReleaseIdentity(
        previous_handoff,
        "a" * 40,
        "linux/amd64",
        port,
        project,
        artifacts[previous_handoff],
    )
    release_b = deploy.ReleaseIdentity(
        current_handoff,
        "b" * 40,
        "linux/amd64",
        port,
        project,
        artifacts[current_handoff],
    )
    monkeypatch.setattr(
        deploy,
        "promoted_web_artifact_path",
        lambda artifact: artifact_paths[artifact.product_sha],
    )
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
    monkeypatch.setattr(deploy, "ENV_CONTRACT", setup_contract_path)
    _private_env(operator, _portable_operator_values(f"http://127.0.0.1:{port}"))
    bundle_a = deploy.reconcile_environment(
        release_a,
        operator_path=operator,
        optional_path=optional,
        runtime_path=runtime,
        random_token=lambda count: "x" * count,
    )
    historical_runtime = dict(bundle_a.runtime)
    historical_runtime["POC_K9_SCHEDULER_ENABLED"] = "false"
    deploy._atomic_private_env(runtime, historical_runtime)
    bundle_a = replace(
        bundle_a,
        runtime=historical_runtime,
        effective={
            **bundle_a.effective,
            "POC_K9_SCHEDULER_ENABLED": "false",
        },
        k9_mode="DEFERRED",
    )
    bundle_a = _effective(bundle_a, project)
    effective_a = dict(bundle_a.effective)
    effective_a.update(
        {
            "POC_PORT": str(port),
            "POC_PUBLIC_ORIGIN": f"http://127.0.0.1:{port}",
        }
    )
    bundle_a = replace(bundle_a, effective=effective_a)
    source_a = {"handoff_commit": previous_handoff}
    before_39080 = deploy.snapshot_39080(runner)
    inventory_a = deploy.inspect_target_inventory(
        runner,
        release_a,
        runtime_path=runtime,
        accepted_marker_path=accepted,
        attempt_receipt_path=attempt,
    )
    preparation_a = deploy.DeploymentPreparation(
        runner,
        source_a,
        inventory_a,
        before_39080,
    )
    monkeypatch.setattr(
        deploy,
        "run_provider_preflight",
        lambda _runner, _image, _env_file, _effective: {
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
                "Intentional cross-release smoke failure.",
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
    cleanup_bundle = bundle_a
    try:
        with pytest.raises(deploy.PrepError):
            deploy.deploy(release_a, bundle_a, preparation_a)
        v2_receipt = deploy._attempt_receipt(attempt)
        assert v2_receipt is not None
        legacy_receipt = dict(v2_receipt)
        legacy_receipt["contract"] = deploy.ATTEMPT_CONTRACT_V1
        legacy_runtime = deploy._legacy_runtime_for_receipt(
            bundle_a.runtime,
            historical_contract,
        )
        legacy_runtime["POC_K9_SCHEDULER_ENABLED"] = "false"
        legacy_receipt["runtime_env_fingerprint"] = deploy.legacy_runtime_env_fingerprint_v1(
            legacy_runtime
        )
        legacy_receipt.pop("ownership_fingerprint_contract")
        legacy_receipt.pop("ownership_fingerprint")
        deploy._atomic_json(attempt, legacy_receipt)

        # Reproduce the actual observed PREP state: the prior release receipt remains,
        # while a failed descendant deploy already wrote its new tracked FIXED values.
        already_updated_runtime = deploy.read_env_file(
            runtime,
            private=True,
            label=".env.prep.runtime",
        )
        already_updated_runtime.update(
            {str(key): str(value) for key, value in current_contract["ownership"]["FIXED"].items()}
        )
        already_updated_runtime.update(
            {
                "POC_IMAGE_TAG": release_b.product_sha,
                "POC_SOURCE_COMMIT": release_b.product_sha,
                "PREP_RELEASE_PRODUCT_SHA": release_b.product_sha,
                "PREP_RELEASE_EVIDENCE_SHA": release_b.evidence_sha,
            }
        )
        deploy._atomic_private_env(runtime, already_updated_runtime)
        preserved_secrets = {
            key: already_updated_runtime[key] for key in deploy.TARGET_OWNERSHIP_SECRET_KEYS
        }

        monkeypatch.setattr(deploy, "ENV_CONTRACT", current_contract_path)
        inventory_b = deploy.inspect_target_inventory(
            runner,
            release_b,
            runtime_path=runtime,
            accepted_marker_path=accepted,
            attempt_receipt_path=attempt,
        )
        assert deploy.classify_target_state(inventory_b) is (
            deploy.TargetState.EXISTING_OWNED_INCOMPLETE
        )
        previous_attempt = deploy.validate_owned_attempt(
            runner,
            release_b,
            current_handoff,
            inventory_b,
            already_updated_runtime,
            "DEFERRED",
        )
        bundle_b = deploy.reconcile_environment(
            release_b,
            operator_path=operator,
            optional_path=optional,
            runtime_path=runtime,
            target_state=deploy.TargetState.EXISTING_OWNED_INCOMPLETE,
            random_token=lambda _count: pytest.fail("descendant resume must reuse secrets"),
        )
        effective_b = dict(bundle_b.effective)
        for key in (
            "POC_PLATFORM",
            "POC_SHARED_NETWORK",
            "POC_POSTGRES_HOST_PORT",
            "POC_NEO4J_HTTP_PORT",
            "POC_REDIS_PORT",
            "POC_PORT",
            "POC_PUBLIC_ORIGIN",
        ):
            effective_b[key] = bundle_a.effective[key]
        bundle_b = replace(bundle_b, effective=effective_b)
        cleanup_bundle = bundle_b
        preparation_b = deploy.DeploymentPreparation(
            runner,
            {"handoff_commit": current_handoff},
            inventory_b,
            before_39080,
            previous_attempt,
        )
        deploy.deploy(release_b, bundle_b, preparation_b)

        final_receipt = deploy._attempt_receipt(attempt)
        assert final_receipt is not None
        assert final_receipt["contract"] == deploy.ATTEMPT_CONTRACT_V2
        assert final_receipt["phase"] == "ACCEPTED"
        assert final_receipt["migrated_from_contract"] == deploy.ATTEMPT_CONTRACT_V1
        assert final_receipt["resumed_from_product_sha"] == release_a.product_sha
        final_runtime = deploy.read_env_file(
            runtime,
            private=True,
            label=".env.prep.runtime",
        )
        assert final_runtime["POC_LLM_TIMEOUT_MS"] == "120000"
        assert {
            key: final_runtime[key] for key in deploy.TARGET_OWNERSHIP_SECRET_KEYS
        } == preserved_secrets
        assert smoke_attempts == 2
        with deploy.private_effective_environment(bundle_b.effective) as env_file:
            inspected = deploy.inspect_bootstrap(
                runner,
                deploy.compose_prefix(release_b, env_file),
            )
        assert inspected["administrator_record_count"] == 1
        assert inspected["user_record_count"] == 3
        assert [item["name"] for item in inspected["services"]] == ["K9", "MCP"]
    finally:
        with deploy.private_effective_environment(cleanup_bundle.effective) as env_file:
            prefix = deploy.compose_prefix(release_b, env_file)
            runner.run([*prefix, "down", "--volumes", "--remove-orphans"], check=False)


@pytest.mark.skipif(
    not _FULL_ENABLED,
    reason="explicit full historical accepted-upgrade Docker integration is required",
)
def test_historical_deferred_accepted_release_upgrades_to_required_capabilities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pollute_parent_environment(monkeypatch)
    project = f"datariver-prep39083-accepted-{uuid4().hex[:10]}"
    port = int(_free_port())
    runner = deploy.Runner(environment=deploy.child_environment({}))
    current_handoff = runner.output(["git", "rev-parse", "HEAD"])
    historical_handoff = "749f568f4ea0dcddd3e837e76d83fe784985bb5b"
    assert (
        runner.run(
            ["git", "merge-base", "--is-ancestor", historical_handoff, current_handoff],
            check=False,
        ).returncode
        == 0
    )
    historical_source_contract = json.loads(
        runner.output(["git", "show", f"{historical_handoff}:deploy/prep39083/env-contract.json"])
    )
    current_contract_path = ROOT / "deploy/prep39083/env-contract.json"
    current_contract = json.loads(current_contract_path.read_text())
    assert historical_source_contract["contract"] == "DATARIVER_PREP39083_ENV_V4"
    assert historical_source_contract["ownership"]["FIXED"]["POC_BIND_HOST"] == "127.0.0.1"
    assert (
        historical_source_contract["ownership"]["FIXED"]["POC_CHANGE_HISTORY_SCHEDULER_ENABLED"]
        == "false"
    )
    assert historical_source_contract["ownership"]["FIXED"].get("POC_K9_SCHEDULER_ENABLED") is None
    assert current_contract["ownership"]["FIXED"]["POC_BIND_HOST"] == "0.0.0.0"  # noqa: S104
    assert current_contract["ownership"]["FIXED"]["POC_CHANGE_HISTORY_SCHEDULER_ENABLED"] == "true"
    assert current_contract["ownership"]["FIXED"]["POC_K9_SCHEDULER_ENABLED"] == "true"
    # Current reconciliation reads the current V5 schema; this contract uses that
    # schema with the exact historical topology values proven above.
    historical_contract = json.loads(json.dumps(current_contract))
    historical_contract["ownership"]["FIXED"].update(
        {
            "POC_BIND_HOST": "127.0.0.1",
            # The historical host publish was loopback-only. The current
            # canonical Compose always keeps the container listener internal.
            "POC_SERVER_HOST": WILDCARD_BIND_HOST,
            "POC_K9_SCHEDULER_ENABLED": "false",
            "POC_CHANGE_HISTORY_SCHEDULER_ENABLED": "false",
        }
    )
    historical_contract_path = tmp_path / "env-contract.historical-shape.json"
    historical_contract_path.write_text(json.dumps(historical_contract), encoding="utf-8")

    artifact_paths = {
        product: tmp_path / f"{product}.tar" for product in (historical_handoff, current_handoff)
    }
    artifacts = {
        product: _build_product_artifact(runner, product, artifact_paths[product])
        for product in (historical_handoff, current_handoff)
    }
    release_a = deploy.ReleaseIdentity(
        historical_handoff,
        "a" * 40,
        "linux/amd64",
        port,
        project,
        artifacts[historical_handoff],
    )
    release_b = deploy.ReleaseIdentity(
        current_handoff,
        "b" * 40,
        "linux/amd64",
        port,
        project,
        artifacts[current_handoff],
    )
    monkeypatch.setattr(
        deploy,
        "promoted_web_artifact_path",
        lambda artifact: artifact_paths[artifact.product_sha],
    )
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
    monkeypatch.setattr(deploy, "ENV_CONTRACT", historical_contract_path)
    values = _portable_operator_values(f"http://127.0.0.1:{port}")
    values["POC_MCL_KAFKA_BROKERS"] = "127.0.0.1:9"
    _private_env(operator, values)

    bundle_a = deploy.reconcile_environment(
        release_a,
        operator_path=operator,
        optional_path=optional,
        runtime_path=runtime,
        random_token=lambda count: "h" * count,
    )
    historical_runtime = dict(bundle_a.runtime)
    historical_runtime["POC_K9_SCHEDULER_ENABLED"] = "false"
    deploy._atomic_private_env(runtime, historical_runtime)
    bundle_a = replace(
        bundle_a,
        runtime=historical_runtime,
        effective={**bundle_a.effective, "POC_K9_SCHEDULER_ENABLED": "false"},
        k9_mode="DEFERRED",
    )
    bundle_a = _effective(bundle_a, project)
    effective_a = dict(bundle_a.effective)
    effective_a.update(
        {
            "POC_PORT": str(port),
            "POC_PUBLIC_ORIGIN": f"http://127.0.0.1:{port}",
        }
    )
    bundle_a = replace(bundle_a, effective=effective_a)
    runner.environment = deploy.child_environment(bundle_a.effective)
    before_39080 = deploy.snapshot_39080(runner)
    inventory_a = deploy.inspect_target_inventory(
        runner,
        release_a,
        runtime_path=runtime,
        accepted_marker_path=accepted,
        attempt_receipt_path=attempt,
    )
    monkeypatch.setattr(
        deploy,
        "run_provider_preflight",
        lambda _runner, _image, _env_file, _effective: {
            "status": "PASS",
            "gx_quality_execution": "DEFERRED",
            "airflow": "DEFERRED",
            "minio": "DEFERRED",
        },
    )
    monkeypatch.setattr(deploy, "run_smoke", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "admin")
    passwords = iter(
        (
            "correct horse battery staple",
            "correct horse battery staple",
            "correct horse battery staple",
        )
    )
    monkeypatch.setattr(deploy.getpass, "getpass", lambda _prompt="": next(passwords))
    cleanup_bundle = bundle_a
    try:
        deploy.deploy(
            release_a,
            bundle_a,
            deploy.DeploymentPreparation(
                runner,
                {"handoff_commit": historical_handoff},
                inventory_a,
                before_39080,
            ),
        )
        assert bundle_a.k9_mode == "DEFERRED"
        assert accepted.is_file() and attempt.is_file()
        accepted_a = accepted.read_bytes()
        attempt_a = deploy._attempt_receipt(attempt)
        assert attempt_a is not None and attempt_a["phase"] == "ACCEPTED"
        runtime_a = deploy.read_env_file(runtime, private=True, label=".env.prep.runtime")
        secrets_a = {key: runtime_a[key] for key in deploy.TARGET_OWNERSHIP_SECRET_KEYS}
        with deploy.private_effective_environment(bundle_a.effective) as env_file:
            prefix_a = deploy.compose_prefix(release_a, env_file)
            config_a = deploy.compose_config(runner, prefix_a)
            volumes_a = deploy.compose_volume_identities(config_a)
            runner.run(
                [
                    *deploy._postgres_local_command(
                        prefix_a,
                        bundle_a.effective["POC_POSTGRES_DB"],
                        bundle_a.effective["POC_POSTGRES_USER"],
                    ),
                    "--command",
                    "INSERT INTO poc_state(scope, value) VALUES "
                    "('historical-accepted-durable', '{\"preserved\":true}'::jsonb) "
                    "ON CONFLICT (scope) DO NOTHING;",
                ]
            )
            checkpoint_count = runner.output(
                [
                    *deploy._postgres_local_command(
                        prefix_a,
                        bundle_a.effective["POC_POSTGRES_DB"],
                        bundle_a.effective["POC_POSTGRES_USER"],
                    ),
                    "--tuples-only",
                    "--no-align",
                    "--command",
                    "SELECT count(*) FROM poc_change_history_checkpoints;",
                ]
            )
            assert checkpoint_count == "0"

        monkeypatch.setattr(deploy, "ENV_CONTRACT", current_contract_path)
        values["POC_PUBLIC_ORIGIN"] = f"http://100.64.17.9:{port}"
        values["POC_INTRANET_HTTP_ALLOWED_CIDRS"] = "100.64.0.0/10"
        _private_env(operator, values)
        inventory_b = deploy.inspect_target_inventory(
            runner,
            release_b,
            runtime_path=runtime,
            accepted_marker_path=accepted,
            attempt_receipt_path=attempt,
        )
        assert deploy.classify_target_state(inventory_b) in {
            deploy.TargetState.EXISTING_ACCEPTED_RUNNING,
            deploy.TargetState.EXISTING_ACCEPTED_STOPPED,
        }
        bundle_b = deploy.reconcile_environment(
            release_b,
            operator_path=operator,
            optional_path=optional,
            runtime_path=runtime,
            target_state=deploy.classify_target_state(inventory_b),
            random_token=lambda _count: pytest.fail("accepted upgrade must preserve secrets"),
        )
        effective_b = dict(bundle_b.effective)
        for key in (
            "POC_PLATFORM",
            "POC_SHARED_NETWORK",
            "POC_POSTGRES_HOST_PORT",
            "POC_NEO4J_HTTP_PORT",
            "POC_REDIS_PORT",
            "POC_PORT",
        ):
            effective_b[key] = bundle_a.effective[key]
        effective_b["POC_PUBLIC_ORIGIN"] = values["POC_PUBLIC_ORIGIN"]
        effective_b["POC_INTRANET_HTTP_ALLOWED_CIDRS"] = values["POC_INTRANET_HTTP_ALLOWED_CIDRS"]
        bundle_b = replace(bundle_b, effective=effective_b)
        runner.environment = deploy.child_environment(bundle_b.effective)
        cleanup_bundle = bundle_b
        assert bundle_b.k9_mode == "REQUIRED"
        deploy.deploy(
            release_b,
            bundle_b,
            deploy.DeploymentPreparation(
                runner,
                {"handoff_commit": current_handoff},
                inventory_b,
                before_39080,
            ),
        )
        runtime_b = deploy.read_env_file(runtime, private=True, label=".env.prep.runtime")
        assert {key: runtime_b[key] for key in deploy.TARGET_OWNERSHIP_SECRET_KEYS} == secrets_a
        with deploy.private_effective_environment(bundle_b.effective) as env_file:
            prefix_b = deploy.compose_prefix(release_b, env_file)
            config_b = deploy.compose_config(runner, prefix_b)
            assert deploy.compose_volume_identities(config_b) == volumes_a
            preserved = runner.output(
                [
                    *deploy._postgres_local_command(
                        prefix_b,
                        bundle_b.effective["POC_POSTGRES_DB"],
                        bundle_b.effective["POC_POSTGRES_USER"],
                    ),
                    "--tuples-only",
                    "--no-align",
                    "--command",
                    "SELECT count(*) FROM poc_state WHERE scope = 'historical-accepted-durable';",
                ]
            )
            policies = runner.output(
                [
                    *deploy._postgres_local_command(
                        prefix_b,
                        bundle_b.effective["POC_POSTGRES_DB"],
                        bundle_b.effective["POC_POSTGRES_USER"],
                    ),
                    "--tuples-only",
                    "--no-align",
                    "--command",
                    "SELECT count(*) FROM poc_k9_managed_graph_policies;",
                ]
            )
            assert preserved == "1"
            assert policies == "2"
            inspected = deploy.inspect_bootstrap(runner, prefix_b)
            assert [item["name"] for item in inspected["services"]] == ["K9", "MCP"]
        assert accepted.is_file() and attempt.is_file()
        assert accepted.read_bytes() != accepted_a
        assert deploy._attempt_receipt(attempt)["phase"] == "ACCEPTED"
        source = MODULE_PATH.read_text(encoding="utf-8")
        assert "down -v" not in source
        assert '"volume", "rm"' not in source
    finally:
        runner.environment = deploy.child_environment(cleanup_bundle.effective)
        with deploy.private_effective_environment(cleanup_bundle.effective) as env_file:
            prefix = deploy.compose_prefix(release_b, env_file)
            runner.run([*prefix, "down", "--volumes", "--remove-orphans"], check=False)
