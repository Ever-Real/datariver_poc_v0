from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Self, cast

import pytest

from datariver.config import Settings
from datariver.gateway_auth_parity_fixture import (
    FixtureDiagnosticEnvelope,
    FixtureDiagnosticOperation,
    FixtureDiagnosticPredicate,
    fixture_diagnostic_failure_classification,
    format_fixture_diagnostic_line,
)

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "scripts" / "platform_workflow.py"
FRESH_SETUP_MODULE_PATH = ROOT / "scripts" / "workflow_fresh_setup.py"
UPDATE_MODULE_PATH = ROOT / "scripts" / "workflow_update_restart.py"
CAPACITY_MODULE_PATH = ROOT / "scripts" / "docker_capacity.py"
GATEWAY_PARITY_MODULE_PATH = ROOT / "scripts" / "probe_gateway_auth_parity.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("platform_workflow", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


workflow = _load_module()


def _load_fresh_setup_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "workflow_fresh_setup_for_profile_test",
        FRESH_SETUP_MODULE_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    previous_platform_module = sys.modules.get("platform_workflow")
    sys.modules["platform_workflow"] = workflow
    try:
        spec.loader.exec_module(module)
    finally:
        if previous_platform_module is None:
            sys.modules.pop("platform_workflow", None)
        else:
            sys.modules["platform_workflow"] = previous_platform_module
    return module


def _load_update_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "workflow_update_restart_for_environment_test",
        UPDATE_MODULE_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    previous_update_module = sys.modules.get(spec.name)
    previous_platform_module = sys.modules.get("platform_workflow")
    previous_capacity_module = sys.modules.get("docker_capacity")
    previous_gateway_parity_module = sys.modules.get("probe_gateway_auth_parity")
    capacity_spec = importlib.util.spec_from_file_location(
        "docker_capacity",
        CAPACITY_MODULE_PATH,
    )
    assert capacity_spec is not None
    assert capacity_spec.loader is not None
    capacity_module = importlib.util.module_from_spec(capacity_spec)
    gateway_parity_spec = importlib.util.spec_from_file_location(
        "probe_gateway_auth_parity",
        GATEWAY_PARITY_MODULE_PATH,
    )
    assert gateway_parity_spec is not None
    assert gateway_parity_spec.loader is not None
    gateway_parity_module = importlib.util.module_from_spec(gateway_parity_spec)
    sys.modules["platform_workflow"] = workflow
    sys.modules["docker_capacity"] = capacity_module
    sys.modules["probe_gateway_auth_parity"] = gateway_parity_module
    sys.modules[spec.name] = module
    try:
        capacity_spec.loader.exec_module(capacity_module)
        gateway_parity_spec.loader.exec_module(gateway_parity_module)
        spec.loader.exec_module(module)
    finally:
        if previous_platform_module is None:
            sys.modules.pop("platform_workflow", None)
        else:
            sys.modules["platform_workflow"] = previous_platform_module
        if previous_capacity_module is None:
            sys.modules.pop("docker_capacity", None)
        else:
            sys.modules["docker_capacity"] = previous_capacity_module
        if previous_gateway_parity_module is None:
            sys.modules.pop("probe_gateway_auth_parity", None)
        else:
            sys.modules["probe_gateway_auth_parity"] = previous_gateway_parity_module
        if previous_update_module is None:
            sys.modules.pop(spec.name, None)
        else:
            sys.modules[spec.name] = previous_update_module

    @contextmanager
    def test_lock(_root: Path) -> Iterator[Any]:
        yield SimpleNamespace()

    dynamic_module = cast(Any, module)
    dynamic_module.exclusive_docker_workflow_lock = test_lock
    dynamic_module._preflight_build_capacity = lambda *_args, **_kwargs: "test-builder"
    dynamic_module._require_idle_builder = lambda *_args, **_kwargs: None
    dynamic_module.enforce_local_topology = lambda *_args, **_kwargs: None
    return module


def test_portable_profile_is_buildable_on_arm64_and_amd64_without_local_datahub() -> None:
    profile = workflow.workflow_profile("portable-development")

    assert profile.deployment_mode == "build"
    assert profile.target_architectures == ("arm64", "amd64")
    assert profile.default_datahub_mode == "external"
    assert profile.local_datahub_supported is False
    assert "portable-development" in workflow.WORKFLOW_PROFILE_NAMES


def test_local_identity_bootstrap_reapplies_only_for_its_mac_source_contract() -> None:
    changed = ("backend/src/datariver/bootstrap.py",)

    assert workflow.requires_local_identity_bootstrap(
        changed,
        profile="mac-development",
    )
    assert not workflow.requires_local_identity_bootstrap(
        changed,
        profile="portable-development",
    )
    assert not workflow.requires_local_identity_bootstrap(
        ("backend/src/datariver/config.py",),
        profile="mac-development",
    )


def test_compatibility_profiles_keep_the_reviewed_topology_contract() -> None:
    mac = workflow.workflow_profile("mac-development")
    wsl = workflow.workflow_profile("wsl-preparation")

    assert (
        mac.deployment_mode,
        mac.target_architectures,
        mac.default_datahub_mode,
        mac.default_redis_mode,
        mac.default_storage_mode,
        mac.default_airflow_mode,
        mac.local_storage_endpoint,
        mac.local_datahub_supported,
        mac.local_reranker_supported,
    ) == (
        "build",
        ("arm64",),
        "local",
        "local",
        "local",
        "local",
        "http://host.docker.internal:9000",
        True,
        True,
    )
    assert (
        wsl.deployment_mode,
        wsl.target_architectures,
        wsl.default_datahub_mode,
        wsl.default_redis_mode,
        wsl.default_storage_mode,
        wsl.default_airflow_mode,
        wsl.local_storage_endpoint,
        wsl.local_datahub_supported,
        wsl.local_reranker_supported,
    ) == (
        "offline",
        ("amd64",),
        "external",
        "local",
        "external",
        "external",
        "http://minio:9000",
        False,
        False,
    )


@pytest.mark.parametrize(
    ("profile", "docker_platform", "expected"),
    (
        ("portable-development", "linux/aarch64", "arm64"),
        ("portable-development", "linux/x86_64", "amd64"),
        ("mac-development", "linux/aarch64", "arm64"),
        ("wsl-preparation", "linux/x86_64", "amd64"),
    ),
)
def test_platform_verification_accepts_each_profile_architecture(
    profile: str,
    docker_platform: str,
    expected: str,
) -> None:
    fresh_setup = _load_fresh_setup_module()

    class FakeRunner:
        def output(self, _arguments: tuple[str, ...]) -> str:
            return docker_platform

    assert fresh_setup._verify_platform(FakeRunner(), profile=profile) == expected


@pytest.mark.parametrize(
    ("profile", "docker_platform"),
    (
        ("portable-development", "windows/amd64"),
        ("portable-development", "linux/s390x"),
        ("mac-development", "linux/x86_64"),
        ("wsl-preparation", "linux/aarch64"),
    ),
)
def test_platform_verification_rejects_wrong_os_or_architecture(
    profile: str,
    docker_platform: str,
) -> None:
    fresh_setup = _load_fresh_setup_module()

    class FakeRunner:
        def output(self, _arguments: tuple[str, ...]) -> str:
            return docker_platform

    with pytest.raises(workflow.WorkflowError):
        fresh_setup._verify_platform(FakeRunner(), profile=profile)


@pytest.mark.parametrize(
    "overrides",
    (
        {"deployment_mode": "mutable"},
        {"target_architectures": ()},
        {"target_architectures": ("s390x",)},
        {"default_datahub_mode": "embedded"},
        {"default_redis_mode": "shared"},
        {"default_storage_mode": "unknown"},
        {"default_airflow_mode": "unknown"},
        {"local_storage_endpoint": "http://localhost:9000"},
        {"local_datahub_supported": True},
    ),
)
def test_profile_validator_rejects_invalid_topology(overrides: dict[str, object]) -> None:
    values: dict[str, object] = {
        "name": "invalid-profile",
        "deployment_mode": "build",
        "target_architectures": ("amd64",),
        "default_datahub_mode": "external",
        "default_redis_mode": "local",
        "default_storage_mode": "local",
        "default_airflow_mode": "skip",
        "local_storage_endpoint": "http://minio:9000",
        "local_datahub_supported": False,
        "local_reranker_supported": False,
    }
    values.update(overrides)
    profile = workflow.WorkflowProfile(**values)

    with pytest.raises(workflow.WorkflowError):
        profile.validate()


def test_unknown_profile_lookup_and_state_path_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(workflow.WorkflowError):
        workflow.workflow_profile("unknown")
    with pytest.raises(workflow.WorkflowError):
        workflow.state_path(tmp_path, "unknown")


def test_compose_wrapper_uses_one_selected_file_for_interpolation_and_container_env(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        "#!/bin/sh\n"
        "printf 'selected=%s\\n' \"$DATARIVER_ENV_FILE\"\n"
        "printf 'argv='\n"
        "printf '%s|' \"$@\"\n",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = os.pathsep.join((os.fspath(fake_bin), environment["PATH"]))

    for filename in (".env.portable-development", ".env.other-development"):
        selected = tmp_path / filename
        selected.write_text(
            f"DATARIVER_CONNECTOR_NETWORK=network-{filename.removeprefix('.env.')}\n",
            encoding="utf-8",
        )
        result = subprocess.run(  # noqa: S603 - repository script and bounded fake PATH.
            (ROOT / "scripts" / "compose.sh", "--env-file", selected, "config"),
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

        assert result.returncode == 0, result.stderr
        assert f"selected={selected}" in result.stdout
        assert f"argv=compose|--env-file|{selected}|config|" in result.stdout


def test_applied_state_rejects_profile_deployment_mode_mismatch() -> None:
    state = workflow.AppliedState(
        profile="portable-development",
        applied_commit="b" * 40,
        runtime_commit="b" * 40,
        env_file=".env.portable-development",
        deployment_mode="offline",
        release_dir="/not-valid-for-portable",
        local_airflow=False,
        local_datahub=False,
        local_redis=True,
        local_storage=True,
        local_gateway=False,
        local_graph=False,
    )

    with pytest.raises(workflow.WorkflowError, match="does not match"):
        state.validate()


def test_applied_state_rejects_portable_local_datahub() -> None:
    state = workflow.AppliedState(
        profile="portable-development",
        applied_commit="b" * 40,
        runtime_commit="b" * 40,
        env_file=".env.portable-development",
        deployment_mode="build",
        release_dir=None,
        local_airflow=False,
        local_datahub=True,
        local_redis=True,
        local_storage=True,
        local_gateway=False,
        local_graph=False,
    )

    with pytest.raises(workflow.WorkflowError, match="local DataHub"):
        state.validate()


def test_portable_state_round_trip_preserves_exact_env_path(tmp_path: Path) -> None:
    path = workflow.state_path(tmp_path, "portable-development")
    state = workflow.AppliedState(
        profile="portable-development",
        applied_commit="b" * 40,
        runtime_commit="b" * 40,
        env_file=".env.portable-development",
        deployment_mode="build",
        release_dir=None,
        local_airflow=False,
        local_datahub=False,
        local_redis=True,
        local_storage=True,
        local_gateway=False,
        local_graph=False,
    )

    workflow.write_applied_state(path, state)

    assert workflow.load_applied_state(path) == state
    assert json.loads(path.read_text(encoding="utf-8"))["env_file"] == (".env.portable-development")


@pytest.mark.parametrize(
    "value",
    (
        "http://10.20.30.40:8080",
        "https://datahub-gms.example.internal",
        "redis://redis-cache.internal:6379/0",
        "rediss://redis-cache.internal:6380/0",
        "bolt+s://neo4j.internal:7687",
    ),
)
def test_validate_endpoint_accepts_explicit_origins_and_redis_urls(value: str) -> None:
    allowed: tuple[str, ...]
    if value.startswith("redis"):
        allowed = ("redis", "rediss")
    elif value.startswith("bolt"):
        allowed = ("bolt", "bolt+s", "neo4j", "neo4j+s")
    else:
        allowed = ("http", "https")

    assert workflow.validate_endpoint(value, allowed_schemes=allowed) == value


@pytest.mark.parametrize(
    "value",
    (
        "http://<datahub-gms-host>:8080",
        "https://user:password@example.internal",
        "https://example.internal/api",
        "https://example.internal?token=secret",
        "bolt+s://neo4j.internal:7687/database",
        "localhost:8080",
        "/home/user/workspace/datariver_v1",
    ),
)
def test_validate_endpoint_rejects_placeholders_credentials_paths_and_files(value: str) -> None:
    with pytest.raises(workflow.WorkflowError):
        workflow.validate_endpoint(value, allowed_schemes=("http", "https"))


def test_update_env_values_replaces_duplicates_without_exposing_other_values(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env.wsl-preparation"
    env_file.write_text(
        "DATAHUB_BASE_URL=https://old.invalid\n"
        "DATAHUB_SECRET_REF=file:/run/secrets/datahub_token\n"
        "SENSITIVE_VALUE=do-not-touch\n"
        "DATAHUB_BASE_URL=https://duplicate.invalid\n",
        encoding="utf-8",
    )

    workflow.update_env_values(
        env_file,
        {
            "DATAHUB_BASE_URL": "http://10.20.30.40:8080",
            "NO_PROXY": "127.0.0.1,localhost,10.20.30.40",
        },
    )

    content = env_file.read_text(encoding="utf-8")
    assert content.count("DATAHUB_BASE_URL=") == 1
    assert "DATAHUB_BASE_URL=http://10.20.30.40:8080" in content
    assert "NO_PROXY=127.0.0.1,localhost,10.20.30.40" in content
    assert "SENSITIVE_VALUE=do-not-touch" in content


def test_environment_fingerprints_detect_keys_without_persisting_values() -> None:
    previous = workflow.environment_key_hashes(
        {
            "DATAHUB_BASE_URL": "https://old.example",
            "DATAHUB_SECRET_REF": "file:/run/secrets/datahub_token",
        }
    )
    current = workflow.environment_key_hashes(
        {
            "DATAHUB_BASE_URL": "https://new.example",
            "DATAHUB_SECRET_REF": "file:/run/secrets/datahub_token",
        }
    )

    assert workflow.changed_environment_keys(previous, current) == ("DATAHUB_BASE_URL",)
    assert all(len(value) == 64 for value in current.values())
    assert "new.example" not in json.dumps(current)
    assert "datahub_token" not in json.dumps(current)


def test_environment_change_classification_restarts_only_known_consumers() -> None:
    llm = workflow.classify_environment_changes(("LOCAL_OLLAMA_CHAT_MODEL",))
    assert set(llm.services) == {"api", "knowledge-tbox-proposal-worker"}
    assert llm.requires_migration is False

    embedding = workflow.classify_environment_changes(("LOCAL_OLLAMA_EMBEDDING_MODEL",))
    assert set(embedding.services) == {"api", "knowledge-source-worker"}

    reranker = workflow.classify_environment_changes(("LOCAL_LLAMA_CPP_RERANKER_MODEL",))
    assert reranker.services == ("api",)

    local_hosts = workflow.classify_environment_changes(("LOCAL_INFERENCE_ALLOWED_HOSTS",))
    assert set(local_hosts.services) == {
        "api",
        "knowledge-source-worker",
        "knowledge-tbox-proposal-worker",
    }

    public_intranet_hosts = workflow.classify_environment_changes(
        ("INTRANET_OPENAI_COMPATIBLE_APPROVED_PUBLIC_HOSTS",)
    )
    assert set(public_intranet_hosts.services) == {
        "api",
        "knowledge-source-worker",
        "knowledge-tbox-proposal-worker",
    }

    plaintext_probe_ips = workflow.classify_environment_changes(
        ("SYSTEM_CONFIGURATION_PROBE_PLAINTEXT_ALLOWED_IPS",)
    )
    assert plaintext_probe_ips.services == ("api",)

    identity = workflow.classify_environment_changes(("OIDC_ISSUER",))
    assert identity.services == ("api",)
    assert identity.configure_keycloak is False

    browser_identity = workflow.classify_environment_changes(("OIDC_CLIENT_ID",))
    assert browser_identity.services == ("web",)

    identity_origin = workflow.classify_environment_changes(("OIDC_PUBLIC_ORIGIN",))
    assert set(identity_origin.services) == {"web", "keycloak"}
    assert identity_origin.configure_keycloak is True

    identity_admin = workflow.classify_environment_changes(("IDENTITY_ADMIN_ENABLED",))
    assert identity_admin.services == ("api",)

    storage = workflow.classify_environment_changes(("S3_ENDPOINT_URL",))
    assert set(storage.services) == set(workflow.BACKEND_RUNTIME_SERVICES)
    assert storage.restart_local_connectors is False

    browser_storage = workflow.classify_environment_changes(("S3_PUBLIC_ORIGIN",))
    assert browser_storage.services == ("web",)

    app_origin = workflow.classify_environment_changes(("APP_PUBLIC_ORIGIN",))
    assert app_origin.local_connector_services == ("minio",)

    knowledge_proposal_worker = workflow.classify_environment_changes(
        ("KNOWLEDGE_STUDIO_PROPOSAL_WORKER_LEASE_SECONDS",)
    )
    assert set(knowledge_proposal_worker.services) == {
        "api",
        "knowledge-tbox-proposal-worker",
    }

    connector_network = workflow.classify_environment_changes(("DATARIVER_CONNECTOR_NETWORK",))
    assert set(connector_network.local_connector_services) == set(workflow.LOCAL_CONNECTOR_SERVICES)
    assert connector_network.restart_airflow is True
    assert connector_network.restart_graph is True

    gateway = workflow.classify_environment_changes(("APISIX_PORT", "DATARIVER_API_UPSTREAM"))
    assert gateway.restart_gateway is True


def test_every_documented_environment_key_has_an_explicit_consumer_plan() -> None:
    documented: set[str] = set()
    for raw_line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = raw_line.removeprefix("# ").strip()
        key, separator, _value = line.partition("=")
        if separator and key and key.replace("_", "").isalnum() and key.upper() == key:
            documented.add(key)

    unclassified: list[str] = []
    for key in sorted(documented):
        try:
            workflow.classify_environment_changes((key,), reject_unknown=True)
        except workflow.WorkflowError:
            unclassified.append(key)

    assert unclassified == []


def test_every_live_settings_field_has_a_documented_explicit_consumer_plan() -> None:
    retired = {
        "SYSTEM_CONFIGURATION_RUNTIME_ACTIVATION_ENABLED",
        "SYSTEM_CONFIGURATION_RUNTIME_WORKSPACE_ID",
        "SYSTEM_CONFIGURATION_RUNTIME_VERSIONS",
        "SYSTEM_CONFIGURATION_RUNTIME_HASHES",
    }
    live_settings = {name.upper() for name in Settings.model_fields} - retired
    documented: set[str] = set()
    for raw_line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = raw_line.removeprefix("# ").strip()
        key, separator, _value = line.partition("=")
        if separator and key and key.replace("_", "").isalnum() and key.upper() == key:
            documented.add(key)

    assert live_settings - documented == set()
    for key in sorted(live_settings):
        workflow.classify_environment_changes((key,), reject_unknown=True)


def test_worker_specific_environment_keys_do_not_restart_unrelated_processes() -> None:
    assert workflow.classify_environment_changes(("GOVERNANCE_APPLY_LEASE_SECONDS",)).services == (
        "api",
        "governance-apply-worker",
    )
    assert workflow.classify_environment_changes(("OUTBOX_MAXIMUM_ATTEMPTS",)).services == (
        "outbox-relay",
    )
    assert workflow.classify_environment_changes(("UPLOAD_LEASE_SECONDS",)).services == (
        "upload-worker",
    )
    assert workflow.classify_environment_changes(("UPLOAD_VALIDATION_LEASE_SECONDS",)).services == (
        "upload-validation-worker",
    )
    assert workflow.classify_environment_changes(("CACHE_DEFAULT_TTL_SECONDS",)).services == (
        "api",
    )
    assert workflow.classify_environment_changes(("CATALOG_EXPORT_WORKER_ENABLED",)).services == (
        "api",
        "catalog-export-worker",
    )
    assert workflow.classify_environment_changes(("EVENT_RETENTION_DAYS",)).services == ()


def test_environment_plan_merges_with_source_plan_without_inferred_migration() -> None:
    result = workflow.merge_change_plans(
        workflow.classify_changes(("frontend/src/App.tsx",)),
        workflow.classify_environment_changes(("LOCAL_OLLAMA_CHAT_MODEL",)),
    )

    assert set(result.services) == {"api", "knowledge-tbox-proposal-worker", "web"}
    assert result.requires_migration is False


def test_update_starts_an_explicitly_enabled_proposal_worker() -> None:
    update = _load_update_module()

    assert update._enabled_optional_runtime_services(
        {"KNOWLEDGE_STUDIO_PROPOSAL_WORKER_ENABLED": "true"}
    ) == ("knowledge-tbox-proposal-worker",)
    assert (
        update._enabled_optional_runtime_services(
            {"KNOWLEDGE_STUDIO_PROPOSAL_WORKER_ENABLED": "false"}
        )
        == ()
    )


def _topology_state(**overrides: object) -> Any:
    values: dict[str, object] = {
        "profile": "portable-development",
        "applied_commit": "a" * 40,
        "runtime_commit": "a" * 40,
        "env_file": ".env.portable-development",
        "deployment_mode": "build",
        "release_dir": None,
        "local_airflow": False,
        "local_datahub": False,
        "local_redis": False,
        "local_storage": False,
        "local_gateway": False,
        "local_graph": False,
        "environment_key_hashes": {},
    }
    values.update(overrides)
    return workflow.AppliedState(**values)


def _core_topology_observations() -> list[Any]:
    return [
        workflow.LocalServiceObservation(
            project="datariver-next",
            service=service,
            state="running",
            health="healthy" if service in {"postgres", "keycloak", "api", "web"} else "none",
        )
        for service in (
            "postgres",
            "keycloak",
            "api",
            "web",
            "outbox-relay",
            "upload-worker",
            "upload-validation-worker",
            "governance-apply-worker",
        )
    ]


def _topology_reconciliation_observations(
    *,
    web_running: bool,
    apisix_health: str = "healthy",
    neo4j_health: str = "healthy",
) -> tuple[Any, ...]:
    observations = [
        item for item in _core_topology_observations() if web_running or item.service != "web"
    ]
    observations.extend(
        workflow.LocalServiceObservation(
            project="datariver-next",
            service=service,
            state="running",
            health="none",
        )
        for service in workflow.AIRFLOW_SERVICES
    )
    observations.extend(
        (
            workflow.LocalServiceObservation(
                project="datariver-next",
                service="apisix",
                state="running",
                health=apisix_health,
            ),
            workflow.LocalServiceObservation(
                project="datariver-next",
                service="neo4j",
                state="running",
                health=neo4j_health,
            ),
        )
    )
    return tuple(observations)


def test_local_topology_clean_fast_path_has_no_findings() -> None:
    audit = workflow.build_local_topology_audit(
        state=_topology_state(),
        environment_values={"NEO4J_PROJECTION_ENABLED": "false"},
        observations=_core_topology_observations(),
    )

    assert audit.has_findings is False
    assert json.loads(audit.summary()) == {
        "expected_missing": [],
        "intent_mismatch": [],
        "selected_unhealthy": [],
        "unexpected_unhealthy": [],
        "unexpected_running": [],
        "unexpected_unknown_count": 0,
    }


def test_local_topology_keeps_runtime_and_intent_drift_separate() -> None:
    observations = _core_topology_observations()
    observations.extend(
        (
            workflow.LocalServiceObservation(
                project="datariver-next",
                service="neo4j",
                state="running",
                health="healthy",
            ),
            workflow.LocalServiceObservation(
                project="datariver-next",
                service="apisix",
                state="running",
                health="healthy",
            ),
        )
    )

    audit = workflow.build_local_topology_audit(
        state=_topology_state(),
        environment_values={
            "NEO4J_PROJECTION_ENABLED": "true",
            "NEO4J_URI": "bolt://neo4j:7687",
        },
        observations=observations,
    )

    assert audit.expected_missing == ()
    assert audit.unexpected_running == ("gateway.apisix", "graph.neo4j")
    assert audit.selected_unhealthy == ()
    assert audit.unexpected_unhealthy == ()
    assert audit.intent_mismatch == ("graph.neo4j",)


@pytest.mark.parametrize(
    ("service", "health", "logical_key"),
    (
        ("apisix", "starting", "gateway.apisix"),
        ("apisix", "unhealthy", "gateway.apisix"),
        ("neo4j", "starting", "graph.neo4j"),
        ("neo4j", "unhealthy", "graph.neo4j"),
    ),
)
def test_topology_reconciliation_rejects_unexpected_target_unhealthy_before_mutation(
    service: str,
    health: str,
    logical_key: str,
) -> None:
    state = _topology_state(profile="mac-development", local_airflow=True)
    environment = {
        "GOVERNANCE_DOCUMENT_WORKER_ENABLED": "true",
        "NEO4J_PROJECTION_ENABLED": "true",
        "NEO4J_URI": "bolt://neo4j:7687",
    }
    audit = workflow.build_local_topology_audit(
        state=state,
        environment_values=environment,
        observations=_topology_reconciliation_observations(
            web_running=False,
            apisix_health=health if service == "apisix" else "healthy",
            neo4j_health=health if service == "neo4j" else "healthy",
        ),
    )

    assert audit.unexpected_unhealthy == ((logical_key, health),)
    assert json.loads(audit.summary())["unexpected_unhealthy"] == [
        {"service": logical_key, "status": health}
    ]
    with pytest.raises(
        workflow.WorkflowError,
        match="TOPOLOGY_RECONCILIATION_PRECONDITION_FAILED",
    ):
        workflow.build_topology_reconciliation_plan(
            "mac-development-graph-gateway-v1",
            state=state,
            environment_values=environment,
            audit=audit,
        )


def test_local_topology_rejects_invalid_health_without_raw_evidence() -> None:
    sentinel = "future-health-secret-path"
    observations = _core_topology_observations()
    observations.append(
        workflow.LocalServiceObservation(
            project="datariver-next",
            service="apisix",
            state="running",
            health=sentinel,
        )
    )

    with pytest.raises(workflow.WorkflowError, match="LOCAL_TOPOLOGY_EVIDENCE_INVALID") as raised:
        workflow.build_local_topology_audit(
            state=_topology_state(),
            environment_values={"NEO4J_PROJECTION_ENABLED": "false"},
            observations=observations,
        )

    assert sentinel not in str(raised.value)


@pytest.mark.parametrize(
    "unexpected_unhealthy",
    (
        (("gateway.apisix", "healthy"),),
        (("future-secret-service", "unhealthy"),),
        (("graph.neo4j", "starting"), ("gateway.apisix", "unhealthy")),
        (("gateway.apisix", "unhealthy"), ("gateway.apisix", "unhealthy")),
    ),
)
def test_local_topology_audit_rejects_invalid_unexpected_health_evidence(
    unexpected_unhealthy: tuple[tuple[str, str], ...],
) -> None:
    with pytest.raises(workflow.WorkflowError, match="LOCAL_TOPOLOGY_EVIDENCE_INVALID") as raised:
        workflow.LocalTopologyAudit(
            expected_missing=(),
            unexpected_running=(),
            selected_unhealthy=(),
            unexpected_unhealthy=unexpected_unhealthy,
            intent_mismatch=(),
        )

    assert "future-secret-service" not in str(raised.value)


@pytest.mark.parametrize(
    ("service", "duplicate_key"),
    (
        ("apisix", "duplicate.gateway.apisix"),
        ("neo4j", "duplicate.graph.neo4j"),
    ),
)
def test_unexpected_target_duplicate_running_is_bounded_and_rejected(
    service: str,
    duplicate_key: str,
) -> None:
    state = _topology_state(profile="mac-development", local_airflow=True)
    environment = {
        "GOVERNANCE_DOCUMENT_WORKER_ENABLED": "true",
        "NEO4J_PROJECTION_ENABLED": "true",
        "NEO4J_URI": "bolt://neo4j:7687",
    }
    observations = (
        *_topology_reconciliation_observations(web_running=False),
        workflow.LocalServiceObservation(
            project="datariver-next",
            service=service,
            state="running",
            health="healthy",
        ),
    )

    audit = workflow.build_local_topology_audit(
        state=state,
        environment_values=environment,
        observations=observations,
    )

    assert duplicate_key in audit.unexpected_running
    assert audit.unexpected_unhealthy == ()
    with pytest.raises(
        workflow.WorkflowError,
        match="TOPOLOGY_RECONCILIATION_PRECONDITION_FAILED",
    ):
        workflow.build_topology_reconciliation_plan(
            "mac-development-graph-gateway-v1",
            state=state,
            environment_values=environment,
            audit=audit,
        )


@pytest.mark.parametrize("service", ("apisix", "neo4j"))
def test_unexpected_target_running_and_stopped_is_not_duplicate(service: str) -> None:
    state = _topology_state(profile="mac-development", local_airflow=True)
    environment = {
        "GOVERNANCE_DOCUMENT_WORKER_ENABLED": "true",
        "NEO4J_PROJECTION_ENABLED": "true",
        "NEO4J_URI": "bolt://neo4j:7687",
    }
    observations = (
        *_topology_reconciliation_observations(web_running=False),
        workflow.LocalServiceObservation(
            project="datariver-next",
            service=service,
            state="exited",
            health="none",
        ),
    )

    audit = workflow.build_local_topology_audit(
        state=state,
        environment_values=environment,
        observations=observations,
    )
    plan = workflow.build_topology_reconciliation_plan(
        "mac-development-graph-gateway-v1",
        state=state,
        environment_values=environment,
        audit=audit,
    )

    assert all(not finding.startswith("duplicate.") for finding in audit.unexpected_running)
    assert plan.checkpoint == "web-missing-recovery"


@pytest.mark.parametrize(
    ("service", "health", "duplicate_key", "logical_key"),
    (
        ("apisix", "starting", "duplicate.gateway.apisix", "gateway.apisix"),
        ("apisix", "unhealthy", "duplicate.gateway.apisix", "gateway.apisix"),
        ("neo4j", "starting", "duplicate.graph.neo4j", "graph.neo4j"),
        ("neo4j", "unhealthy", "duplicate.graph.neo4j", "graph.neo4j"),
    ),
)
def test_unexpected_target_duplicate_retains_unhealthy_evidence(
    service: str,
    health: str,
    duplicate_key: str,
    logical_key: str,
) -> None:
    state = _topology_state(profile="mac-development", local_airflow=True)
    environment = {
        "GOVERNANCE_DOCUMENT_WORKER_ENABLED": "true",
        "NEO4J_PROJECTION_ENABLED": "true",
        "NEO4J_URI": "bolt://neo4j:7687",
    }
    observations = (
        *_topology_reconciliation_observations(web_running=False),
        workflow.LocalServiceObservation(
            project="datariver-next",
            service=service,
            state="running",
            health=health,
        ),
    )

    audit = workflow.build_local_topology_audit(
        state=state,
        environment_values=environment,
        observations=observations,
    )

    assert duplicate_key in audit.unexpected_running
    assert audit.unexpected_unhealthy == ((logical_key, health),)
    with pytest.raises(
        workflow.WorkflowError,
        match="TOPOLOGY_RECONCILIATION_PRECONDITION_FAILED",
    ):
        workflow.build_topology_reconciliation_plan(
            "mac-development-graph-gateway-v1",
            state=state,
            environment_values=environment,
            audit=audit,
        )


def test_exact_mac_topology_reconciliation_changes_only_graph_and_gateway() -> None:
    state = _topology_state(
        profile="mac-development",
        local_airflow=True,
        local_datahub=True,
        environment_key_hashes={"UNCHANGED": "a" * 64},
    )
    environment = {
        "GOVERNANCE_DOCUMENT_WORKER_ENABLED": "true",
        "NEO4J_PROJECTION_ENABLED": "true",
        "NEO4J_URI": "bolt://neo4j:7687",
    }
    audit = workflow.build_local_topology_audit(
        state=state,
        environment_values=environment,
        observations=_topology_reconciliation_observations(web_running=True),
    )

    plan = workflow.build_topology_reconciliation_plan(
        "mac-development-graph-gateway-v1",
        state=state,
        environment_values=environment,
        audit=audit,
    )

    assert plan.checkpoint == "initial"
    assert audit.unexpected_unhealthy == ()
    assert plan.missing_worker_service == "governance-document-worker"
    assert plan.target_state == workflow.replace(
        state,
        local_graph=True,
        local_gateway=True,
    )


def test_exact_mac_topology_reconciliation_accepts_only_web_missing_recovery() -> None:
    state = _topology_state(
        profile="mac-development",
        local_airflow=True,
        local_datahub=True,
        environment_key_hashes={"UNCHANGED": "a" * 64},
    )
    environment = {
        "GOVERNANCE_DOCUMENT_WORKER_ENABLED": "true",
        "NEO4J_PROJECTION_ENABLED": "true",
        "NEO4J_URI": "bolt://neo4j:7687",
    }
    audit = workflow.build_local_topology_audit(
        state=state,
        environment_values=environment,
        observations=_topology_reconciliation_observations(web_running=False),
    )

    plan = workflow.build_topology_reconciliation_plan(
        "mac-development-graph-gateway-v1",
        state=state,
        environment_values=environment,
        audit=audit,
    )

    assert plan.checkpoint == "web-missing-recovery"
    assert audit.unexpected_unhealthy == ()
    assert plan.missing_worker_service == "governance-document-worker"
    assert plan.target_state == workflow.replace(
        state,
        local_graph=True,
        local_gateway=True,
    )


@pytest.mark.parametrize(
    ("state_overrides", "environment", "audit_overrides"),
    (
        ({"profile": "portable-development"}, {}, {}),
        ({"deployment_mode": "offline", "release_dir": "/release"}, {}, {}),
        ({"local_airflow": False}, {}, {}),
        ({"local_graph": True}, {}, {}),
        ({"local_gateway": True}, {}, {}),
        ({}, {"NEO4J_PROJECTION_ENABLED": "false"}, {}),
        ({}, {"NEO4J_URI": "bolt://external-graph:7687"}, {}),
        ({}, {"GOVERNANCE_DOCUMENT_WORKER_ENABLED": "false"}, {}),
        ({}, {}, {"expected_missing": ()}),
        ({}, {}, {"expected_missing": ("core.web",)}),
        ({}, {}, {"expected_missing": ("core.api", "worker.governance-document")}),
        (
            {},
            {},
            {
                "expected_missing": (
                    "core.web",
                    "worker.governance-document",
                    "worker.upload",
                )
            },
        ),
        ({}, {}, {"unexpected_running": ("graph.neo4j",)}),
        (
            {},
            {},
            {
                "unexpected_running": (
                    "duplicate.gateway.apisix",
                    "gateway.apisix",
                    "graph.neo4j",
                )
            },
        ),
        ({}, {}, {"intent_mismatch": ()}),
        ({}, {}, {"unexpected_unknown_count": 1}),
        ({}, {}, {"selected_unhealthy": (("core.web", "starting"),)}),
        ({}, {}, {"selected_unhealthy": (("core.api", "unhealthy"),)}),
    ),
)
def test_topology_reconciliation_rejects_any_nonexact_prestate_or_finding(
    state_overrides: dict[str, object],
    environment: dict[str, str],
    audit_overrides: dict[str, object],
) -> None:
    state_values: dict[str, object] = {
        "profile": "mac-development",
        "local_airflow": True,
        "local_datahub": True,
        "local_redis": True,
        "local_storage": True,
    }
    state_values.update(state_overrides)
    state = _topology_state(**state_values)
    audit_values: dict[str, object] = {
        "expected_missing": ("worker.governance-document",),
        "unexpected_running": ("gateway.apisix", "graph.neo4j"),
        "selected_unhealthy": (),
        "unexpected_unhealthy": (),
        "intent_mismatch": ("graph.neo4j",),
        "unexpected_unknown_count": 0,
    }
    audit_values.update(audit_overrides)
    values = {
        "GOVERNANCE_DOCUMENT_WORKER_ENABLED": "true",
        "NEO4J_PROJECTION_ENABLED": "true",
        "NEO4J_URI": "bolt://neo4j:7687",
        **environment,
    }

    with pytest.raises(workflow.WorkflowError, match="TOPOLOGY_RECONCILIATION_PRECONDITION"):
        workflow.build_topology_reconciliation_plan(
            "mac-development-graph-gateway-v1",
            state=state,
            environment_values=values,
            audit=workflow.LocalTopologyAudit(**audit_values),
        )


@pytest.mark.parametrize(
    "checkpoint_order",
    (("initial", "recovery"), ("recovery", "initial")),
)
def test_locked_topology_checkpoint_transition_stops_before_mutation(
    checkpoint_order: tuple[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    update = _load_update_module()
    env_file = tmp_path / ".env.mac-development"
    environment = {
        "GOVERNANCE_DOCUMENT_WORKER_ENABLED": "true",
        "NEO4J_PROJECTION_ENABLED": "true",
        "NEO4J_URI": "bolt://neo4j:7687",
    }
    env_file.write_text(
        "\n".join(f"{key}={value}" for key, value in environment.items()) + "\n",
        encoding="utf-8",
    )
    state = _topology_state(
        profile="mac-development",
        env_file=os.fspath(env_file),
        local_airflow=True,
        local_datahub=True,
        local_redis=True,
        local_storage=True,
        environment_key_hashes=workflow.environment_key_hashes(environment),
    )
    initial = workflow.build_topology_reconciliation_plan(
        "mac-development-graph-gateway-v1",
        state=state,
        environment_values=environment,
        audit=workflow.LocalTopologyAudit(
            expected_missing=("worker.governance-document",),
            unexpected_running=("gateway.apisix", "graph.neo4j"),
            selected_unhealthy=(),
            unexpected_unhealthy=(),
            intent_mismatch=("graph.neo4j",),
        ),
    )
    recovery = workflow.build_topology_reconciliation_plan(
        "mac-development-graph-gateway-v1",
        state=state,
        environment_values=environment,
        audit=workflow.LocalTopologyAudit(
            expected_missing=("core.web", "worker.governance-document"),
            unexpected_running=("gateway.apisix", "graph.neo4j"),
            selected_unhealthy=(),
            unexpected_unhealthy=(),
            intent_mismatch=("graph.neo4j",),
        ),
    )
    plans_by_checkpoint = {"initial": initial, "recovery": recovery}
    plans = iter(plans_by_checkpoint[name] for name in checkpoint_order)
    events: list[str] = []

    class FakeRunner:
        def note(self, _message: str) -> None:
            return None

    @contextmanager
    def held_lock(_root: Path) -> Iterator[object]:
        events.append("lock-enter")
        try:
            yield object()
        finally:
            events.append("lock-exit")

    @contextmanager
    def held_secrets(_root: Path) -> Iterator[object]:
        events.append("secret-enter")
        try:
            yield object()
        finally:
            events.append("secret-exit")

    def compose(_runner: object, **kwargs: object) -> None:
        trailing = cast(tuple[str, ...], kwargs["trailing"])
        events.append("config" if trailing == ("config", "--quiet") else "docker-mutation")

    def prepared(*_args: object, **_kwargs: object) -> Any:
        events.append("audit")
        return next(plans)

    monkeypatch.setattr(
        update,
        "parse_args",
        lambda: SimpleNamespace(
            profile="mac-development",
            env_file=env_file,
            release_dir=None,
            git_pull=False,
            reload_release=False,
            refresh_bootstrap=False,
            skip_catalog_sync=True,
            assume_yes=True,
            reconcile_local_topology="mac-development-graph-gateway-v1",
        ),
    )
    monkeypatch.setattr(update, "Runner", FakeRunner)
    monkeypatch.setattr(update, "require_command", lambda _command: None)
    monkeypatch.setattr(update, "require_clean_worktree", lambda _runner: None)
    monkeypatch.setattr(update, "state_path", lambda _root, _profile: tmp_path / "state.json")
    monkeypatch.setattr(update, "load_applied_state", lambda _path: state)
    monkeypatch.setattr(update, "current_commit", lambda _runner: state.applied_commit)
    monkeypatch.setattr(update, "_git_paths", lambda *_args: ())
    monkeypatch.setattr(update, "_running_services", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(update, "_compose", compose)
    monkeypatch.setattr(update, "_prepare_topology_reconciliation", prepared)
    monkeypatch.setattr(update, "exclusive_docker_workflow_lock", held_lock)
    monkeypatch.setattr(update, "require_topology_reconciliation_secrets", held_secrets)
    for name in (
        "_bootstrap",
        "_preflight_build_capacity",
        "_reconcile_local_reranker",
        "_reconcile_topology_with_gateway_parity",
        "write_applied_state",
    ):
        monkeypatch.setattr(
            update,
            name,
            lambda *_args, _name=name, **_kwargs: events.append(_name),
        )

    assert update.main() == 2
    assert events == [
        "lock-enter",
        "config",
        "audit",
        "secret-enter",
        "audit",
        "secret-exit",
        "lock-exit",
    ]
    assert capsys.readouterr().err.splitlines() == [
        "ERROR: TOPOLOGY_RECONCILIATION_PRECONDITION_FAILED"
    ]


def test_gateway_routing_overlay_has_narrow_change_classification() -> None:
    plan = workflow.classify_changes(("compose.gateway-routing.yaml",))

    assert plan.services == ("web",)
    assert plan.restart_gateway is True
    assert plan.requires_migration is False
    assert plan.configure_keycloak is False
    assert plan.restart_airflow is False
    assert plan.restart_graph is False


def test_selected_gateway_state_renders_only_reviewed_routing_overlays() -> None:
    update = _load_update_module()
    state = _topology_state(
        profile="mac-development",
        local_gateway=True,
        local_graph=True,
    )

    files = update._compose_files(state, release_override=None)

    assert files == (
        ROOT / "compose.yaml",
        ROOT / "compose.identity.yaml",
        ROOT / "compose.gateway.yaml",
        ROOT / "compose.gateway-routing.yaml",
    )

    assert update._airflow_compose_files(files, local_gateway=True) == (
        *files,
        ROOT / "compose.airflow.yaml",
        ROOT / "compose.airflow.host-dev.yaml",
    )
    assert update._airflow_compose_files(files[:2], local_gateway=False) == (
        *files[:2],
        ROOT / "compose.airflow.yaml",
    )


def _topology_reconciliation_plan() -> Any:
    state = _topology_state(
        profile="mac-development",
        local_airflow=True,
        local_datahub=True,
        local_redis=True,
        local_storage=True,
    )
    return workflow.TopologyReconciliationPlan(
        name="mac-development-graph-gateway-v1",
        checkpoint="initial",
        target_state=workflow.replace(state, local_gateway=True, local_graph=True),
        missing_worker_service="governance-document-worker",
    )


def test_topology_reconciliation_mutation_order_is_worker_gateway_web_airflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    events: list[tuple[str, ...]] = []

    def compose(_runner: object, **kwargs: object) -> None:
        trailing = cast(tuple[str, ...], kwargs["trailing"])
        events.append(trailing)

    monkeypatch.setattr(update, "_compose", compose)
    monkeypatch.setattr(
        update,
        "_verify_governance_document_worker_database",
        lambda *_args, **_kwargs: events.append(("database-gates",)),
    )
    monkeypatch.setattr(
        update,
        "_require_idle_builder",
        lambda *_args, **_kwargs: events.append(("builder-idle",)),
    )

    class SecretGuard:
        def revalidate(self) -> None:
            events.append(("secret-guard",))

    update._apply_topology_reconciliation(
        SimpleNamespace(note=lambda _message: None),
        env_file=tmp_path / ".env",
        files=(ROOT / "compose.yaml", ROOT / "compose.gateway.yaml"),
        plan=_topology_reconciliation_plan(),
        selected_builder="builder",
        capacity_lock=object(),
        secret_guard=SecretGuard(),
    )

    assert events[0] == ("secret-guard",)
    assert events[1][-1] == "governance-document-worker"
    assert events[2] == ("secret-guard",)
    assert events[3] == ("database-gates",)
    assert events[4] == ("builder-idle",)
    assert events[5] == ("build", "apisix")
    assert "--wait" in events[6]
    assert events[6][-1] == "apisix"
    assert "--wait" in events[7]
    assert "--force-recreate" in events[7]
    assert events[7][-1] == "web"
    assert sum(event[-1:] == ("web",) for event in events) == 1
    assert events[8][-4:] == workflow.AIRFLOW_SERVICES


def test_governance_document_role_and_backlog_are_separate_sanitized_queries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    commands: list[tuple[str, ...]] = []
    outputs = iter(("datariver_governance_document", "12"))
    notes: list[str] = []

    def private_output(**kwargs: object) -> str:
        commands.append(cast(tuple[str, ...], kwargs["trailing"]))
        return next(outputs)

    monkeypatch.setattr(update, "_private_compose_output", private_output)
    update._verify_governance_document_worker_database(
        SimpleNamespace(note=notes.append),
        env_file=tmp_path / ".env",
        files=(ROOT / "compose.yaml",),
    )

    assert len(commands) == 2
    assert "SELECT current_user;" in commands[0][-1]
    assert "count(*)" not in commands[0][-1]
    assert "SELECT count(*)" in commands[1][-1]
    assert "current_user" not in commands[1][-1]
    assert notes == ["Governance document worker database role/backlog verified count=12"]


@pytest.mark.parametrize(
    "failed_step",
    ("worker", "apisix", "web", "airflow"),
)
def test_topology_reconciliation_failure_stops_before_later_mutations(
    failed_step: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    calls: list[tuple[str, ...]] = []

    def compose(_runner: object, **kwargs: object) -> None:
        trailing = cast(tuple[str, ...], kwargs["trailing"])
        calls.append(trailing)
        current_step = (
            "worker"
            if trailing[-1] == "governance-document-worker"
            else "apisix"
            if trailing[-1] == "apisix"
            else "web"
            if trailing[-1] == "web"
            else "airflow"
            if trailing[-4:] == workflow.AIRFLOW_SERVICES
            else "other"
        )
        if current_step == failed_step:
            raise workflow.WorkflowError(f"fixed-{failed_step}-failure")

    monkeypatch.setattr(update, "_compose", compose)
    monkeypatch.setattr(
        update,
        "_verify_governance_document_worker_database",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(update, "_require_idle_builder", lambda *_args, **_kwargs: None)

    class SecretGuard:
        def revalidate(self) -> None:
            return None

    with pytest.raises(workflow.WorkflowError, match=f"fixed-{failed_step}-failure"):
        update._apply_topology_reconciliation(
            SimpleNamespace(note=lambda _message: None),
            env_file=tmp_path / ".env",
            files=(ROOT / "compose.yaml", ROOT / "compose.gateway.yaml"),
            plan=_topology_reconciliation_plan(),
            selected_builder="builder",
            capacity_lock=object(),
            secret_guard=SecretGuard(),
        )

    observed_steps = [
        "worker"
        if call[-1] == "governance-document-worker"
        else "apisix"
        if call[-1] == "apisix"
        else "web"
        if call[-1] == "web"
        else "airflow"
        if call[-4:] == workflow.AIRFLOW_SERVICES
        else "other"
        for call in calls
    ]
    expected_prefixes = {
        "worker": ["worker"],
        "apisix": ["worker", "apisix"],
        "web": ["worker", "apisix", "apisix", "web"],
        "airflow": ["worker", "apisix", "apisix", "web", "airflow"],
    }
    assert observed_steps == expected_prefixes[failed_step]


def test_reconciliation_target_audit_requires_web_worker_gateway_and_graph() -> None:
    state = _topology_state(local_gateway=True, local_graph=True)
    services = (
        *_core_topology_observations(),
        workflow.LocalServiceObservation(
            project="datariver-next",
            service="governance-document-worker",
            state="running",
            health="healthy",
        ),
        workflow.LocalServiceObservation(
            project="datariver-next",
            service="apisix",
            state="running",
            health="healthy",
        ),
        workflow.LocalServiceObservation(
            project="datariver-next",
            service="neo4j",
            state="running",
            health="healthy",
        ),
    )
    environment = {
        "GOVERNANCE_DOCUMENT_WORKER_ENABLED": "true",
        "NEO4J_PROJECTION_ENABLED": "true",
        "NEO4J_URI": "bolt://neo4j:7687",
    }

    clean = workflow.build_local_topology_audit(
        state=state,
        environment_values=environment,
        observations=services,
    )
    assert clean.has_findings is False

    required = {
        "web": "core.web",
        "governance-document-worker": "worker.governance-document",
        "apisix": "gateway.apisix",
        "neo4j": "graph.neo4j",
    }
    for service, logical_key in required.items():
        audit = workflow.build_local_topology_audit(
            state=state,
            environment_values=environment,
            observations=tuple(item for item in services if item.service != service),
        )
        assert audit.expected_missing == (logical_key,)


def _write_topology_secret_fixture(root: Path) -> Path:
    secret_dir = root / "secrets"
    secret_dir.mkdir(mode=0o700)
    secret_dir.chmod(0o700)
    for name in workflow.TOPOLOGY_RECONCILIATION_SECRET_NAMES:
        target = secret_dir / name
        target.write_text("fixture\n", encoding="utf-8")
        target.chmod(0o444)
    return secret_dir


def _assert_topology_secret_guard_descriptors_closed(
    guard: Any,
) -> None:
    descriptors = (
        guard.root_descriptor,
        guard.secret_descriptor,
        *guard.file_descriptors.values(),
    )
    assert guard.closed is True
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_topology_secret_guard_selects_exact_gateway_admin_credential() -> None:
    assert workflow.TOPOLOGY_RECONCILIATION_SECRET_NAMES == (
        "postgres_governance_document_password",
        "redis_delivery_password",
        "s3_governance_document_access_key",
        "s3_governance_document_secret_key",
        "intranet_llm_chat_api_key",
        "intranet_llm_embedding_api_key",
        "neo4j_auth",
        "keycloak_admin_password",
    )


def test_gateway_admin_reader_uses_retained_selected_secret_descriptor(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    update = _load_update_module()
    secret_dir = _write_topology_secret_fixture(tmp_path)
    target = secret_dir / "keycloak_admin_password"
    sentinel = "gateway-admin-secret-must-not-leak"
    target.chmod(0o600)
    target.write_text(sentinel + "\n", encoding="utf-8")
    target.chmod(0o444)

    with workflow.require_topology_reconciliation_secrets(tmp_path) as guard:
        assert set(guard.file_descriptors) == set(workflow.TOPOLOGY_RECONCILIATION_SECRET_NAMES)
        assert set(guard.file_identities) == set(workflow.TOPOLOGY_RECONCILIATION_SECRET_NAMES)
        assert update._read_gateway_admin_password(guard) == sentinel

    captured = capsys.readouterr()
    assert sentinel not in captured.out
    assert sentinel not in captured.err
    _assert_topology_secret_guard_descriptors_closed(guard)


def test_gateway_admin_secret_replacement_is_detected_by_retained_guard(
    tmp_path: Path,
) -> None:
    secret_dir = _write_topology_secret_fixture(tmp_path)
    target = secret_dir / "keycloak_admin_password"

    with workflow.require_topology_reconciliation_secrets(tmp_path) as guard:
        replacement = tmp_path / "gateway-admin-replacement"
        replacement.write_text("replacement\n", encoding="utf-8")
        replacement.chmod(0o444)
        target.rename(tmp_path / "gateway-admin-original")
        replacement.rename(target)
        with pytest.raises(workflow.WorkflowError, match="TOPOLOGY_SECRET_PREFLIGHT_FAILED"):
            guard.revalidate()


@pytest.mark.parametrize(
    "failure",
    (
        "missing",
        "symlink",
        "nonregular",
        "mode",
        "owner",
        "hardlink",
        "empty",
        "device",
        "fd-replacement",
    ),
)
def test_gateway_admin_secret_metadata_failure_is_fixed_and_nonleaking(
    tmp_path: Path,
    failure: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret_dir = _write_topology_secret_fixture(tmp_path)
    target = secret_dir / "keycloak_admin_password"
    sentinel = "gateway-admin-metadata-secret-must-not-leak"
    target.chmod(0o600)
    target.write_text(sentinel + "\n", encoding="utf-8")
    target.chmod(0o444)
    if failure == "missing":
        target.unlink()
    elif failure == "symlink":
        target.unlink()
        target.symlink_to(secret_dir / workflow.TOPOLOGY_RECONCILIATION_SECRET_NAMES[0])
    elif failure == "nonregular":
        target.unlink()
        target.mkdir()
    elif failure == "mode":
        target.chmod(0o400)
    elif failure == "hardlink":
        os.link(target, tmp_path / "gateway-admin-hardlink")
    elif failure == "empty":
        target.chmod(0o600)
        target.write_bytes(b"")
        target.chmod(0o444)
    elif failure in {"owner", "device"}:
        identity = target.stat()
        original_fstat = workflow.os.fstat

        def drifted_fstat(descriptor: int) -> os.stat_result:
            evidence = cast(os.stat_result, original_fstat(descriptor))
            if evidence.st_ino != identity.st_ino:
                return evidence
            fields = list(evidence)
            fields[4 if failure == "owner" else 2] += 1
            return os.stat_result(fields)

        monkeypatch.setattr(workflow.os, "fstat", drifted_fstat)
    else:
        alternate = tmp_path / "gateway-admin-alternate"
        alternate.write_text("alternate\n", encoding="utf-8")
        alternate.chmod(0o444)
        original_open = workflow.os.open

        def replaced_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
            if path == "keycloak_admin_password":
                return cast(int, original_open(alternate, flags))
            return cast(int, original_open(path, flags, *args, **kwargs))

        monkeypatch.setattr(workflow.os, "open", replaced_open)

    with pytest.raises(workflow.WorkflowError, match="TOPOLOGY_SECRET_PREFLIGHT_FAILED") as error:
        with workflow.require_topology_reconciliation_secrets(tmp_path):
            pass

    captured = capsys.readouterr()
    exposed = captured.out + captured.err + str(error.value)
    assert sentinel not in exposed


@pytest.mark.parametrize(
    "payload",
    (
        b"",
        b"x" * 4_097,
        b"gateway-admin-secret\x00suffix",
        b"gateway-admin-secret-\xff",
        b"gateway-admin-secret\nembedded",
        b"gateway-admin-secret\rembedded",
    ),
)
def test_gateway_admin_reader_rejects_invalid_shape_without_payload_leak(
    tmp_path: Path,
    payload: bytes,
    capsys: pytest.CaptureFixture[str],
) -> None:
    update = _load_update_module()
    target = tmp_path / "synthetic-admin-secret"
    target.write_bytes(payload)
    descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
    guard = SimpleNamespace(
        file_descriptors={"keycloak_admin_password": descriptor},
        revalidate=lambda: None,
    )
    try:
        with pytest.raises(
            update.GatewayAuthParityError,
            match="GATEWAY_AUTH_PARITY_ADMIN_CREDENTIAL_INVALID",
        ) as error:
            update._read_gateway_admin_password(guard)
    finally:
        os.close(descriptor)

    captured = capsys.readouterr()
    exposed = captured.out + captured.err + str(error.value)
    assert "gateway-admin-secret" not in exposed


def test_gateway_admin_reader_postcheck_detects_path_replacement_during_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    update = _load_update_module()
    secret_dir = _write_topology_secret_fixture(tmp_path)
    target = secret_dir / "keycloak_admin_password"
    sentinel = "gateway-admin-read-secret-must-not-leak"
    target.chmod(0o600)
    target.write_text(sentinel + "\n", encoding="utf-8")
    target.chmod(0o444)
    original_pread = update.os.pread

    with workflow.require_topology_reconciliation_secrets(tmp_path) as guard:

        def replaced_pread(descriptor: int, size: int, offset: int) -> bytes:
            replacement = tmp_path / "gateway-admin-during-read"
            replacement.write_text("replacement\n", encoding="utf-8")
            replacement.chmod(0o444)
            target.rename(tmp_path / "gateway-admin-before-read")
            replacement.rename(target)
            return cast(bytes, original_pread(descriptor, size, offset))

        monkeypatch.setattr(update.os, "pread", replaced_pread)
        with pytest.raises(workflow.WorkflowError, match="TOPOLOGY_SECRET_PREFLIGHT_FAILED"):
            update._read_gateway_admin_password(guard)

    captured = capsys.readouterr()
    assert sentinel not in captured.out
    assert sentinel not in captured.err


def test_topology_secret_guard_closes_all_descriptors_after_base_exception(
    tmp_path: Path,
) -> None:
    _write_topology_secret_fixture(tmp_path)
    guard = workflow.require_topology_reconciliation_secrets(tmp_path)

    with pytest.raises(KeyboardInterrupt):
        with guard:
            raise KeyboardInterrupt

    _assert_topology_secret_guard_descriptors_closed(guard)


def test_topology_secret_preflight_accepts_selected_subset_of_canonical_metadata(
    tmp_path: Path,
) -> None:
    secret_dir = _write_topology_secret_fixture(tmp_path)
    unrelated = secret_dir / "unrelated-canonical-secret"
    unrelated.write_text("unrelated\n", encoding="utf-8")
    unrelated.chmod(0o444)

    guard = workflow.require_topology_reconciliation_secrets(tmp_path)
    with guard:
        assert guard.closed is False
        guard.revalidate()
    assert guard.closed is True


def test_topology_secret_preflight_rejects_a_symlinked_root(tmp_path: Path) -> None:
    actual_root = tmp_path / "actual"
    actual_root.mkdir()
    _write_topology_secret_fixture(actual_root)
    linked_root = tmp_path / "linked"
    linked_root.symlink_to(actual_root, target_is_directory=True)

    with pytest.raises(workflow.WorkflowError, match="TOPOLOGY_SECRET_PREFLIGHT_FAILED"):
        with workflow.require_topology_reconciliation_secrets(linked_root):
            pass


def test_topology_secret_guard_detects_selected_file_replacement_after_preflight(
    tmp_path: Path,
) -> None:
    secret_dir = _write_topology_secret_fixture(tmp_path)
    target = secret_dir / workflow.TOPOLOGY_RECONCILIATION_SECRET_NAMES[0]

    with workflow.require_topology_reconciliation_secrets(tmp_path) as guard:
        replacement = tmp_path / "replacement"
        replacement.write_text("replacement\n", encoding="utf-8")
        replacement.chmod(0o444)
        target.rename(tmp_path / "original")
        replacement.rename(target)
        with pytest.raises(workflow.WorkflowError, match="TOPOLOGY_SECRET_PREFLIGHT_FAILED"):
            guard.revalidate()


def test_worker_create_is_bracketed_by_retained_secret_guard_on_ambiguous_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    events: list[str] = []

    class SecretGuard:
        def revalidate(self) -> None:
            events.append("guard")
            if events == ["guard", "create", "guard"]:
                raise workflow.WorkflowError("TOPOLOGY_SECRET_PREFLIGHT_FAILED")

    def compose(_runner: object, **kwargs: object) -> None:
        trailing = cast(tuple[str, ...], kwargs["trailing"])
        if trailing[-1] == "governance-document-worker":
            events.append("create")
            raise workflow.WorkflowError("ambiguous-create-failure")
        events.append("later-mutation")

    monkeypatch.setattr(update, "_compose", compose)

    with pytest.raises(workflow.WorkflowError, match="TOPOLOGY_SECRET_PREFLIGHT_FAILED"):
        update._apply_topology_reconciliation(
            SimpleNamespace(note=lambda _message: None),
            env_file=tmp_path / ".env",
            files=(ROOT / "compose.yaml",),
            plan=_topology_reconciliation_plan(),
            selected_builder=None,
            capacity_lock=object(),
            secret_guard=SecretGuard(),
        )

    assert events == ["guard", "create", "guard"]


def test_gateway_transparency_is_only_a_routing_negative_not_positive_auth_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    calls: list[tuple[str, ...]] = []
    notes: list[str] = []

    class ProbeRunner:
        def run(
            self,
            command: tuple[object, ...],
            **kwargs: object,
        ) -> None:
            calls.append(tuple(os.fspath(cast(str | os.PathLike[str], item)) for item in command))
            program = cast(str, kwargs["input_text"])
            assert "gateway-invalid-token-sentinel" in program
            assert "gateway-cookie-sentinel" in program
            assert "gateway-code-sentinel" in program
            assert "gateway-secret-sentinel" in program
            assert "gateway-body-secret-sentinel" in program
            assert "response.read" not in program
            assert 'paths = ("/api/v1/knowledge/registry/assets", "/api/v1/change-requests")' in (
                program
            )

        def note(self, message: str) -> None:
            notes.append(message)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "API_PORT=8000\nAPISIX_PORT=9080\nWEB_PORT=8080\nAPP_PUBLIC_ORIGIN=http://localhost:8080\n",
        encoding="utf-8",
    )
    log_checks: list[tuple[Path, ...]] = []
    monkeypatch.setattr(
        update,
        "_verify_gateway_logs_do_not_persist_probe_credentials",
        lambda **kwargs: log_checks.append(cast(tuple[Path, ...], kwargs["files"])),
    )

    update._verify_gateway_transparency(
        ProbeRunner(),
        env_file=env_file,
        files=(ROOT / "compose.yaml", ROOT / "compose.gateway-routing.yaml"),
    )

    assert len(calls) == 1
    assert calls[0][-4:] == (
        "http://127.0.0.1:8000",
        "http://127.0.0.1:9080",
        "http://127.0.0.1:8080",
        "http://localhost:8080",
    )
    assert log_checks == [(ROOT / "compose.yaml", ROOT / "compose.gateway-routing.yaml")]
    assert notes == []


def test_gateway_fixture_compose_boundary_uses_fixed_private_stdin_and_exact_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    update = _load_update_module()
    env_file = tmp_path / ".env"
    env_file.write_text("APP_ENV=development\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = tuple(command)
        captured["input"] = kwargs["input"]
        return subprocess.CompletedProcess(
            command,
            0,
            '{"membership_count":2,"privilege_residual_count":0,'
            '"state":"prepared","subject_count":2}',
            "",
        )

    monkeypatch.setattr(update.subprocess, "run", run)
    controller = update._ComposeGatewayAuthParityFixture(
        env_file=env_file,
        files=(ROOT / "compose.yaml", ROOT / "compose.identity.yaml"),
    )
    controller.prepare(
        "10000000-0000-4000-8000-000000000001",
        "10000000-0000-4000-8000-000000000002",
    )

    command = cast(tuple[str, ...], captured["command"])
    request = json.loads(cast(str, captured["input"]))
    assert command[-7:] == (
        "--no-build",
        "-T",
        "local-bootstrap",
        "/app/.venv/bin/python",
        "-m",
        "datariver.gateway_auth_parity_fixture",
        "prepare",
    )
    assert "--name" not in command
    assert "--label" not in command
    assert set(request) == {
        "allow_external_subject",
        "contract",
        "deny_external_subject",
        "operation",
        "source_sha256",
    }
    assert request["operation"] == "prepare"
    assert capsys.readouterr().out == ""


def test_gateway_fixture_compose_failure_never_exposes_private_input_or_provider_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    update = _load_update_module()
    env_file = tmp_path / ".env"
    env_file.write_text("APP_ENV=development\n", encoding="utf-8")
    monkeypatch.setattr(
        update.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            subprocess.CalledProcessError(
                2,
                ["docker", "compose"],
                output="provider-id-secret-sentinel",
                stderr="token-path-secret-sentinel",
            )
        ),
    )
    controller = update._ComposeGatewayAuthParityFixture(
        env_file=env_file,
        files=(ROOT / "compose.yaml",),
    )

    with pytest.raises(
        update.GatewayAuthParityError,
        match="GATEWAY_AUTH_PARITY_FIXTURE_FAILED",
    ) as captured:
        controller.prepare(
            "10000000-0000-4000-8000-000000000001",
            "10000000-0000-4000-8000-000000000002",
        )

    operator = capsys.readouterr().out + capsys.readouterr().err + str(captured.value)
    assert "provider-id" not in operator
    assert "token-path" not in operator


def test_gateway_fixture_compose_timeout_is_fixed_not_retried_and_never_exposes_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    update = _load_update_module()
    env_file = tmp_path / ".env"
    env_file.write_text("APP_ENV=development\n", encoding="utf-8")
    calls = 0

    def timeout(*_args: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise subprocess.TimeoutExpired(
            ["docker", "compose", "provider-path-secret-sentinel"],
            30,
            output="token-secret-sentinel",
            stderr="stderr-secret-sentinel",
        )

    monkeypatch.setattr(update.subprocess, "run", timeout)
    controller = update._ComposeGatewayAuthParityFixture(
        env_file=env_file,
        files=(ROOT / "compose.yaml",),
    )

    with pytest.raises(
        update.GatewayAuthParityError,
        match="GATEWAY_AUTH_PARITY_FIXTURE_FAILED",
    ) as captured:
        controller.prepare(
            "10000000-0000-4000-8000-000000000001",
            "10000000-0000-4000-8000-000000000002",
        )

    assert calls == 1
    operator = capsys.readouterr().out + capsys.readouterr().err + str(captured.value)
    for forbidden in ("provider-path", "token-secret", "stderr-secret"):
        assert forbidden not in operator


@pytest.mark.parametrize(
    "predicate",
    tuple(
        predicate
        for predicate in FixtureDiagnosticPredicate
        if predicate is not FixtureDiagnosticPredicate.PASS
    ),
)
def test_gateway_fixture_require_absent_propagates_each_fixed_child_predicate(
    predicate: FixtureDiagnosticPredicate,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    line = format_fixture_diagnostic_line(
        FixtureDiagnosticEnvelope(
            FixtureDiagnosticOperation.REQUIRE_ABSENT,
            predicate,
        )
    )
    monkeypatch.setattr(
        update,
        "_bounded_fixture_diagnostic_process",
        lambda command, _input_text: subprocess.CompletedProcess(command, 2, "", line),
    )
    monkeypatch.setattr(
        update,
        "_fixture_container_snapshot",
        lambda: update._FixtureContainerState.ABSENT,
    )
    controller = update._ComposeGatewayAuthParityFixture(
        env_file=tmp_path / ".env",
        files=(ROOT / "compose.yaml",),
    )

    with pytest.raises(
        update.GatewayAuthParityError,
        match=fixture_diagnostic_failure_classification(predicate),
    ):
        controller.require_absent()


@pytest.mark.parametrize(
    ("stdout", "stderr", "returncode", "predicate"),
    (
        ("", "", 2, FixtureDiagnosticPredicate.PROCESS_NONZERO),
        ("x" * 258, "", 0, FixtureDiagnosticPredicate.OUTPUT_SIZE),
        ("not-json", "", 0, FixtureDiagnosticPredicate.OUTPUT_JSON),
        ("{}\n{}", "", 0, FixtureDiagnosticPredicate.OUTPUT_LINE),
        (
            format_fixture_diagnostic_line(
                FixtureDiagnosticEnvelope(
                    FixtureDiagnosticOperation.REQUIRE_ABSENT,
                    FixtureDiagnosticPredicate.PASS,
                )
            ),
            "conflicting-secret-sentinel",
            0,
            FixtureDiagnosticPredicate.OUTPUT_TUPLE,
        ),
    ),
)
def test_gateway_fixture_require_absent_classifies_parent_process_and_output_defects(
    stdout: str,
    stderr: str,
    returncode: int,
    predicate: FixtureDiagnosticPredicate,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    update = _load_update_module()
    monkeypatch.setattr(
        update,
        "_bounded_fixture_diagnostic_process",
        lambda command, _input_text: subprocess.CompletedProcess(
            command,
            returncode,
            stdout,
            stderr,
        ),
    )
    monkeypatch.setattr(
        update,
        "_fixture_container_snapshot",
        lambda: update._FixtureContainerState.ABSENT,
    )
    controller = update._ComposeGatewayAuthParityFixture(
        env_file=tmp_path / ".env",
        files=(ROOT / "compose.yaml",),
    )

    evidence = controller.diagnose_require_absent()

    assert evidence.predicate is predicate
    operator = capsys.readouterr().out + capsys.readouterr().err
    assert "secret-sentinel" not in operator


@pytest.mark.parametrize(
    "predicate",
    (
        FixtureDiagnosticPredicate.PROCESS_SPAWN,
        FixtureDiagnosticPredicate.PROCESS_TIMEOUT,
        FixtureDiagnosticPredicate.UNKNOWN,
    ),
)
def test_gateway_fixture_require_absent_process_failures_are_fixed_and_not_retried(
    predicate: FixtureDiagnosticPredicate,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    update = _load_update_module()
    calls = 0

    def fail(*_args: object, **_kwargs: object) -> FixtureDiagnosticPredicate:
        nonlocal calls
        calls += 1
        return predicate

    monkeypatch.setattr(update, "_bounded_fixture_diagnostic_process", fail)
    monkeypatch.setattr(
        update,
        "_fixture_container_snapshot",
        lambda: update._FixtureContainerState.ABSENT,
    )
    controller = update._ComposeGatewayAuthParityFixture(
        env_file=tmp_path / ".env",
        files=(ROOT / "compose.yaml",),
    )

    evidence = controller.diagnose_require_absent()

    assert evidence.predicate is predicate
    assert calls == 1
    operator = capsys.readouterr().out + capsys.readouterr().err
    assert "secret" not in operator.casefold()


def test_no_argument_fixture_diagnostic_holds_lock_and_stops_after_require_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    update = _load_update_module()
    env_file = tmp_path / ".env.mac-development"
    env_file.write_text("APP_ENV=development\n", encoding="utf-8")
    environment = {"APP_ENV": "development"}
    state = _topology_state(
        profile="mac-development",
        env_file=os.fspath(env_file),
        environment_key_hashes=update.environment_key_hashes(environment),
    )
    events: list[str] = []

    @contextmanager
    def lock(_root: Path) -> Iterator[object]:
        events.append("lock-enter")
        try:
            yield object()
        finally:
            events.append("lock-exit")

    class Fixture:
        def __init__(self, **kwargs: object) -> None:
            assert kwargs["source_sha256"] == "a" * 64
            self.execution = cast(Any, kwargs["execution_state"])
            events.append("fixture-init")

        def diagnose_require_absent(self) -> FixtureDiagnosticEnvelope:
            events.append("require-absent")
            self.execution.container_attempted = True
            self.execution.container_cleanup_known = True
            self.execution.container_cleanup_required = False
            self.execution.container_residual_known = True
            self.execution.container_residual_count = 0
            return FixtureDiagnosticEnvelope(
                FixtureDiagnosticOperation.REQUIRE_ABSENT,
                FixtureDiagnosticPredicate.PASS,
            )

    def source_digest() -> str:
        events.append("source")
        return "a" * 64

    def source_is_clean() -> bool:
        events.append("clean")
        return True

    def capacity(*_args: object, **_kwargs: object) -> str:
        events.append("capacity")
        return "builder"

    def build(**_kwargs: object) -> object:
        events.append("build")
        return update._FixtureBuildOutcome(True, True, True)

    monkeypatch.setattr(update, "exclusive_docker_workflow_lock", lock)
    monkeypatch.setattr(update, "load_applied_state", lambda _path: state)
    monkeypatch.setattr(update, "read_env_values", lambda _path: environment)
    monkeypatch.setattr(
        update,
        "current_fixture_source_sha256",
        source_digest,
    )
    monkeypatch.setattr(
        update,
        "_fixture_diagnostic_source_is_clean",
        source_is_clean,
    )
    monkeypatch.setattr(
        update,
        "_preflight_build_capacity",
        capacity,
    )
    monkeypatch.setattr(
        update,
        "_require_idle_builder",
        lambda *_args, **_kwargs: events.append("idle"),
    )
    monkeypatch.setattr(
        update,
        "_build_current_fixture_image",
        build,
    )
    monkeypatch.setattr(update, "_ComposeGatewayAuthParityFixture", Fixture)
    for forbidden in (
        "_gateway_auth_parity_session",
        "_apply_topology_reconciliation",
        "write_applied_state",
    ):
        monkeypatch.setattr(
            update,
            forbidden,
            lambda *_args, name=forbidden, **_kwargs: events.append(name),
        )
    monkeypatch.setattr(sys, "argv", [os.fspath(UPDATE_MODULE_PATH)])

    assert update.main() == 0

    assert events == [
        "lock-enter",
        "clean",
        "source",
        "capacity",
        "idle",
        "build",
        "idle",
        "clean",
        "source",
        "fixture-init",
        "require-absent",
        "lock-exit",
    ]
    output = json.loads(capsys.readouterr().out)
    assert output["classification"] == "PASS"
    assert output["predicate"] == "PASS"
    assert output["cache_action_count"] == 0
    assert output["cache_action_succeeded"] is False
    assert output["build_attempted"] is True
    assert output["build_succeeded"] is True
    assert output["container_attempted"] is True
    assert output["container_residual_count"] == 0
    assert output["business_mutation_count"] == 0
    assert output["retry_count"] == 0


def test_host_environment_preflight_is_locked_ordered_and_stops_before_later_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    env_file = tmp_path / ".env.mac-development"
    environment = {"APP_ENV": "development"}
    expected_hashes = cast(dict[str, str], update.environment_key_hashes(environment))
    state = _topology_state(
        profile="mac-development",
        env_file=os.fspath(env_file),
        environment_key_hashes=expected_hashes,
    )
    events: list[str] = []

    @contextmanager
    def lock(_root: Path) -> Iterator[object]:
        events.append("lock-enter")
        try:
            yield object()
        finally:
            events.append("lock-exit")

    def load(_path: Path) -> object:
        events.append("state")
        return state

    def resolve(_value: str | Path) -> Path:
        events.append("env-path")
        return env_file

    def regular(_path: Path, *, label: str) -> None:
        assert label == "Environment file"
        events.append("env-file")

    def read(_path: Path) -> dict[str, str]:
        events.append("env-read")
        return environment

    def hashes(_values: dict[str, str]) -> dict[str, str]:
        events.append("env-fingerprint")
        return expected_hashes

    def compose(_state: object, *, release_override: Path | None) -> tuple[Path, ...]:
        assert release_override is None
        events.append("compose-selection")
        return (ROOT / "compose.yaml", ROOT / "compose.identity.yaml")

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("later diagnostic path must not run")

    monkeypatch.setattr(update, "exclusive_docker_workflow_lock", lock)
    monkeypatch.setattr(update, "load_applied_state", load)
    monkeypatch.setattr(update, "_resolve_repo_path", resolve)
    monkeypatch.setattr(update, "require_regular_file", regular)
    monkeypatch.setattr(update, "read_env_values", read)
    monkeypatch.setattr(update, "environment_key_hashes", hashes)
    monkeypatch.setattr(update, "_compose_files", compose)
    for name in (
        "_fixture_diagnostic_source_is_clean",
        "current_fixture_source_sha256",
        "_preflight_build_capacity",
        "_require_idle_builder",
        "_build_current_fixture_image",
        "_ComposeGatewayAuthParityFixture",
        "_gateway_auth_parity_session",
        "_apply_topology_reconciliation",
        "write_applied_state",
    ):
        monkeypatch.setattr(update, name, forbidden)

    evidence = update._host_environment_preflight_diagnostic()

    assert evidence.classification is update.HostEnvironmentPreflightClassification.PASS
    assert evidence.phase is update.HostEnvironmentPreflightPhase.HOST_ENVIRONMENT_PREFLIGHT
    assert evidence.predicate is update.HostEnvironmentPreflightPredicate.PASS
    assert evidence.mutation_count == 0
    assert evidence.retry_count == 0
    assert events == [
        "lock-enter",
        "state",
        "env-path",
        "env-file",
        "env-read",
        "env-fingerprint",
        "compose-selection",
        "lock-exit",
    ]


def test_host_environment_preflight_vocabulary_and_evidence_are_exact() -> None:
    update = _load_update_module()

    assert tuple(item.value for item in update.HostEnvironmentPreflightPredicate) == (
        "APPLIED_STATE_CONTRACT",
        "PROFILE_SELECTION",
        "DEPLOYMENT_MODE_SELECTION",
        "GATEWAY_SELECTION",
        "GRAPH_SELECTION",
        "ENV_PATH_CONTRACT",
        "ENV_FILE_CONTRACT",
        "ENV_READ",
        "ENV_FINGERPRINT",
        "COMPOSE_SELECTION",
        "PASS",
        "UNKNOWN",
    )
    with pytest.raises(update.WorkflowError, match="HOST_ENVIRONMENT_PREFLIGHT_EVIDENCE_INVALID"):
        update.HostEnvironmentPreflightEvidence(
            classification=update.HostEnvironmentPreflightClassification.PASS,
            phase=update.HostEnvironmentPreflightPhase.HOST_ENVIRONMENT_PREFLIGHT,
            predicate=update.HostEnvironmentPreflightPredicate.ENV_READ,
        )
    with pytest.raises(update.WorkflowError, match="HOST_ENVIRONMENT_PREFLIGHT_EVIDENCE_INVALID"):
        update.HostEnvironmentPreflightEvidence(
            classification=update.HostEnvironmentPreflightClassification.REJECTED,
            phase=update.HostEnvironmentPreflightPhase.HOST_ENVIRONMENT_PREFLIGHT,
            predicate=update.HostEnvironmentPreflightPredicate.ENV_READ,
            mutation_count=1,
        )


@pytest.mark.parametrize(
    ("case", "expected"),
    (
        ("state", "APPLIED_STATE_CONTRACT"),
        ("profile", "PROFILE_SELECTION"),
        ("deployment", "DEPLOYMENT_MODE_SELECTION"),
        ("gateway", "GATEWAY_SELECTION"),
        ("graph", "GRAPH_SELECTION"),
        ("env-path", "ENV_PATH_CONTRACT"),
        ("env-file", "ENV_FILE_CONTRACT"),
        ("env-read", "ENV_READ"),
        ("env-fingerprint", "ENV_FINGERPRINT"),
        ("compose", "COMPOSE_SELECTION"),
    ),
)
def test_host_environment_preflight_classifies_each_boundary_without_raw(
    case: str,
    expected: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    env_file = tmp_path / ".env.mac-development"
    environment = {"APP_ENV": "development"}
    overrides: dict[str, object] = {
        "profile": "mac-development",
        "env_file": os.fspath(env_file),
        "environment_key_hashes": update.environment_key_hashes(environment),
    }
    if case == "profile":
        overrides["profile"] = "portable-development"
    elif case == "deployment":
        overrides["deployment_mode"] = "offline"
    elif case == "gateway":
        overrides["local_gateway"] = True
    elif case == "graph":
        overrides["local_graph"] = True
    elif case == "env-fingerprint":
        overrides["environment_key_hashes"] = {"APP_ENV": "b" * 64}
    state = _topology_state(**overrides)

    @contextmanager
    def lock(_root: Path) -> Iterator[object]:
        yield object()

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("raw-path-env-secret-sentinel")

    monkeypatch.setattr(update, "exclusive_docker_workflow_lock", lock)
    monkeypatch.setattr(update, "load_applied_state", lambda _path: state)
    monkeypatch.setattr(update, "_resolve_repo_path", lambda _value: env_file)
    monkeypatch.setattr(update, "require_regular_file", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(update, "read_env_values", lambda _path: environment)
    monkeypatch.setattr(
        update,
        "_compose_files",
        lambda _state, *, release_override: (ROOT / "compose.yaml",),
    )
    failure_target = {
        "state": "load_applied_state",
        "env-path": "_resolve_repo_path",
        "env-file": "require_regular_file",
        "env-read": "read_env_values",
        "compose": "_compose_files",
    }.get(case)
    if failure_target is not None:
        monkeypatch.setattr(update, failure_target, fail)

    evidence = update._host_environment_preflight_diagnostic()
    line = update.format_host_environment_preflight_line(evidence)

    assert evidence.classification is update.HostEnvironmentPreflightClassification.REJECTED
    assert evidence.predicate.value == expected
    assert evidence.mutation_count == 0
    assert evidence.retry_count == 0
    assert "raw-path-env-secret-sentinel" not in line
    assert os.fspath(env_file) not in line


def test_host_environment_preflight_rejects_noncanonical_compose_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    env_file = tmp_path / ".env.mac-development"
    environment = {"APP_ENV": "development"}
    state = _topology_state(
        profile="mac-development",
        env_file=os.fspath(env_file),
        environment_key_hashes=update.environment_key_hashes(environment),
    )

    @contextmanager
    def lock(_root: Path) -> Iterator[object]:
        yield object()

    monkeypatch.setattr(update, "exclusive_docker_workflow_lock", lock)
    monkeypatch.setattr(update, "load_applied_state", lambda _path: state)
    monkeypatch.setattr(update, "_resolve_repo_path", lambda _value: env_file)
    monkeypatch.setattr(update, "require_regular_file", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(update, "read_env_values", lambda _path: environment)
    monkeypatch.setattr(update, "_compose_files", lambda *_args, **_kwargs: ())

    evidence = update._host_environment_preflight_diagnostic()

    assert evidence.classification is update.HostEnvironmentPreflightClassification.REJECTED
    assert evidence.predicate is update.HostEnvironmentPreflightPredicate.COMPOSE_SELECTION


@pytest.mark.parametrize(
    "step",
    ("state", "env-path", "env-file", "env-read", "env-fingerprint", "compose"),
)
@pytest.mark.parametrize("failure", (KeyboardInterrupt, SystemExit, BaseException))
def test_host_environment_preflight_interrupt_at_step_is_fixed_and_nonleaking(
    step: str,
    failure: type[BaseException],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    env_file = tmp_path / ".env.mac-development"
    environment = {"APP_ENV": "development"}
    expected_hashes = cast(dict[str, str], update.environment_key_hashes(environment))
    state = _topology_state(
        profile="mac-development",
        env_file=os.fspath(env_file),
        environment_key_hashes=expected_hashes,
    )
    events: list[str] = []

    @contextmanager
    def lock(_root: Path) -> Iterator[object]:
        events.append("lock-enter")
        try:
            yield object()
        finally:
            events.append("lock-exit")

    def interrupt_if_selected(name: str) -> None:
        events.append(name)
        if step == name:
            raise failure("raw-environment-value-sentinel")

    def load(_path: Path) -> object:
        interrupt_if_selected("state")
        return state

    def resolve(_value: str | Path) -> Path:
        interrupt_if_selected("env-path")
        return env_file

    def regular(_path: Path, *, label: str) -> None:
        assert label == "Environment file"
        interrupt_if_selected("env-file")

    def read(_path: Path) -> dict[str, str]:
        interrupt_if_selected("env-read")
        return environment

    def fingerprint(_values: dict[str, str]) -> dict[str, str]:
        interrupt_if_selected("env-fingerprint")
        return expected_hashes

    def compose(_state: object, *, release_override: Path | None) -> tuple[Path, ...]:
        assert release_override is None
        interrupt_if_selected("compose")
        return (ROOT / "compose.yaml", ROOT / "compose.identity.yaml")

    monkeypatch.setattr(update, "exclusive_docker_workflow_lock", lock)
    monkeypatch.setattr(update, "load_applied_state", load)
    monkeypatch.setattr(update, "_resolve_repo_path", resolve)
    monkeypatch.setattr(update, "require_regular_file", regular)
    monkeypatch.setattr(update, "read_env_values", read)
    monkeypatch.setattr(update, "environment_key_hashes", fingerprint)
    monkeypatch.setattr(update, "_compose_files", compose)

    evidence = update._host_environment_preflight_diagnostic()
    line = update.format_host_environment_preflight_line(evidence)

    assert evidence.classification is (
        update.HostEnvironmentPreflightClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.predicate is update.HostEnvironmentPreflightPredicate.UNKNOWN
    order = ("state", "env-path", "env-file", "env-read", "env-fingerprint", "compose")
    assert events == ["lock-enter", *order[: order.index(step) + 1], "lock-exit"]
    assert "raw-environment-value-sentinel" not in line


def test_fixture_diagnostic_preflight_interrupt_is_unknown_before_later_actions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    env_file = tmp_path / ".env.mac-development"
    state = _topology_state(
        profile="mac-development",
        env_file=os.fspath(env_file),
    )
    later_actions: list[str] = []

    @contextmanager
    def lock(_root: Path) -> Iterator[object]:
        yield object()

    def interrupt(_path: Path) -> dict[str, str]:
        raise KeyboardInterrupt("raw-fixture-preflight-secret-sentinel")

    def forbidden(*_args: object, **_kwargs: object) -> None:
        later_actions.append("forbidden")

    monkeypatch.setattr(update, "exclusive_docker_workflow_lock", lock)
    monkeypatch.setattr(update, "load_applied_state", lambda _path: state)
    monkeypatch.setattr(update, "_resolve_repo_path", lambda _value: env_file)
    monkeypatch.setattr(update, "require_regular_file", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(update, "read_env_values", interrupt)
    for name in (
        "_fixture_diagnostic_source_is_clean",
        "current_fixture_source_sha256",
        "_preflight_build_capacity",
        "_require_idle_builder",
        "_build_current_fixture_image",
        "_ComposeGatewayAuthParityFixture",
    ):
        monkeypatch.setattr(update, name, forbidden)

    evidence = update._fixture_require_absent_diagnostic()
    line = update.format_fixture_diagnostic_execution_line(evidence)

    assert evidence.predicate is FixtureDiagnosticPredicate.UNKNOWN
    assert evidence.build_attempted is False
    assert evidence.container_attempted is False
    assert evidence.business_mutation_count == 0
    assert evidence.retry_count == 0
    assert later_actions == []
    assert "raw-fixture-preflight-secret-sentinel" not in line


@pytest.mark.parametrize("failure", (RuntimeError, KeyboardInterrupt))
def test_host_environment_preflight_lock_failure_is_review_required_and_nonleaking(
    failure: type[BaseException],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()

    @contextmanager
    def lock(_root: Path) -> Iterator[object]:
        try:
            raise failure("raw-lock-secret-sentinel")
        finally:
            pass
        yield object()

    monkeypatch.setattr(update, "exclusive_docker_workflow_lock", lock)

    evidence = update._host_environment_preflight_diagnostic()
    line = update.format_host_environment_preflight_line(evidence)

    assert evidence.classification is (
        update.HostEnvironmentPreflightClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.predicate is update.HostEnvironmentPreflightPredicate.UNKNOWN
    assert evidence.mutation_count == 0
    assert evidence.retry_count == 0
    assert "raw-lock-secret-sentinel" not in line


def test_host_environment_preflight_lock_exit_failure_downgrades_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    env_file = tmp_path / ".env.mac-development"
    environment = {"APP_ENV": "development"}
    state = _topology_state(
        profile="mac-development",
        env_file=os.fspath(env_file),
        environment_key_hashes=update.environment_key_hashes(environment),
    )

    @contextmanager
    def lock(_root: Path) -> Iterator[object]:
        yield object()
        raise RuntimeError("raw-lock-exit-sentinel")

    monkeypatch.setattr(update, "exclusive_docker_workflow_lock", lock)
    monkeypatch.setattr(update, "load_applied_state", lambda _path: state)
    monkeypatch.setattr(update, "_resolve_repo_path", lambda _value: env_file)
    monkeypatch.setattr(update, "require_regular_file", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(update, "read_env_values", lambda _path: environment)

    evidence = update._host_environment_preflight_diagnostic()
    line = update.format_host_environment_preflight_line(evidence)

    assert evidence.classification is (
        update.HostEnvironmentPreflightClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.predicate is update.HostEnvironmentPreflightPredicate.UNKNOWN
    assert "raw-lock-exit-sentinel" not in line


def test_host_environment_preflight_main_accepts_only_exact_phase_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    update = _load_update_module()
    accepted = update.HostEnvironmentPreflightEvidence(
        classification=update.HostEnvironmentPreflightClassification.PASS,
        phase=update.HostEnvironmentPreflightPhase.HOST_ENVIRONMENT_PREFLIGHT,
        predicate=update.HostEnvironmentPreflightPredicate.PASS,
    )
    calls: list[str] = []

    def diagnose() -> object:
        calls.append("diagnose")
        return accepted

    monkeypatch.setattr(update, "_host_environment_preflight_diagnostic", diagnose)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            os.fspath(UPDATE_MODULE_PATH),
            "--diagnostic-phase",
            "HOST_ENVIRONMENT_PREFLIGHT",
        ],
    )

    assert update.main() == 0
    assert calls == ["diagnose"]
    assert json.loads(capsys.readouterr().out) == {
        "classification": "PASS",
        "mutation_count": 0,
        "phase": "HOST_ENVIRONMENT_PREFLIGHT",
        "predicate": "PASS",
        "retry_count": 0,
    }

    monkeypatch.setattr(
        sys,
        "argv",
        [
            os.fspath(UPDATE_MODULE_PATH),
            "--diagnostic-phase",
            "HOST_ENVIRONMENT_PREFLIGHT",
            os.fspath(tmp_path / "raw-secret-extra"),
        ],
    )
    assert update.main() == 2
    assert calls == ["diagnose"]
    rejected = json.loads(capsys.readouterr().out)
    assert rejected == {
        "classification": "REJECTED",
        "mutation_count": 0,
        "phase": "HOST_ENVIRONMENT_PREFLIGHT",
        "predicate": "UNKNOWN",
        "retry_count": 0,
    }
    assert "raw-secret-extra" not in json.dumps(rejected)


def _passed_host_preflight(
    update: Any,
    *,
    env_file: Path,
) -> Any:
    environment = {"APP_ENV": "development"}
    state = _topology_state(
        profile="mac-development",
        env_file=os.fspath(env_file),
        environment_key_hashes=update.environment_key_hashes(environment),
    )
    return update._HostEnvironmentPreflightResult(
        update.HostEnvironmentPreflightEvidence(
            classification=update.HostEnvironmentPreflightClassification.PASS,
            phase=update.HostEnvironmentPreflightPhase.HOST_ENVIRONMENT_PREFLIGHT,
            predicate=update.HostEnvironmentPreflightPredicate.PASS,
        ),
        state=state,
        env_file=env_file,
        files=(ROOT / "compose.yaml", ROOT / "compose.identity.yaml"),
    )


def _stub_clean_capacity_source(
    update: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update,
        "_fixture_diagnostic_source_state",
        lambda: update._FixtureSourceCleanState.CLEAN,
    )
    monkeypatch.setattr(update, "current_fixture_source_sha256", lambda: "a" * 64)

    def require_same(expected_sha256: str) -> None:
        assert expected_sha256 == "a" * 64

    monkeypatch.setattr(update, "require_current_fixture_source", require_same)


def test_build_capacity_preflight_is_locked_ordered_read_only_and_value_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    env_file = tmp_path / ".env.mac-development"
    preflight = _passed_host_preflight(update, env_file=env_file)
    events: list[str] = []
    lock_token = object()
    executor_token = object()

    @contextmanager
    def lock(_root: Path) -> Iterator[object]:
        events.append("lock-enter")
        try:
            yield lock_token
        finally:
            events.append("lock-exit")

    def capacity(*_args: object, **kwargs: object) -> str:
        events.append("capacity")
        assert kwargs["lock"] is lock_token
        assert kwargs["executor"] is executor_token
        assert kwargs["mode"] is update.DockerCapacityMode.MEASURE_ONLY
        recorder = cast(Any, kwargs["phase_recorder"])
        recorder.mark(update.BuildCapacityPreflightPredicate.CAPACITY_POLICY)
        selection = cast(Any, kwargs["builder_selection_recorder"])
        node_schema = cast(Any, kwargs["node_schema_recorder"])
        node_schema.record(update.NodeSchemaPredicate.PASS)
        selection.record(update.BuilderSelectionPredicate.PASS)
        return "desktop-linux"

    def idle(_builder: object, _lock: object, **kwargs: object) -> None:
        events.append("initial-idle")
        assert kwargs["executor"] is executor_token
        recorder = cast(Any, kwargs["phase_recorder"])
        recorder.mark(update.BuildCapacityPreflightPredicate.INITIAL_BUILDER_IDLE_PROBE)

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("A read-only capacity diagnostic reached a later mutation boundary.")

    def host_preflight() -> object:
        events.append("host-preflight")
        return preflight

    def clean_source() -> object:
        events.append("clean-source")
        return update._FixtureSourceCleanState.CLEAN

    def source_proof() -> str:
        events.append("source-proof")
        return "a" * 64

    def require_same(expected_sha256: str) -> None:
        events.append("source-hash-check")
        assert expected_sha256 == "a" * 64

    monkeypatch.setattr(update, "exclusive_docker_workflow_lock", lock)
    monkeypatch.setattr(update, "_host_environment_preflight_under_lock", host_preflight)
    monkeypatch.setattr(update, "_fixture_diagnostic_source_state", clean_source)
    monkeypatch.setattr(update, "current_fixture_source_sha256", source_proof)
    monkeypatch.setattr(update, "require_current_fixture_source", require_same)
    monkeypatch.setattr(update, "_BuildCapacityPreflightExecutor", lambda: executor_token)
    monkeypatch.setattr(update, "_preflight_build_capacity", capacity)
    monkeypatch.setattr(update, "_require_idle_builder", idle)
    for name in (
        "_build_current_fixture_image",
        "_ComposeGatewayAuthParityFixture",
        "_gateway_auth_parity_session",
        "_apply_topology_reconciliation",
        "write_applied_state",
    ):
        monkeypatch.setattr(update, name, forbidden)

    evidence = update._build_capacity_preflight_diagnostic()
    line = update.format_build_capacity_preflight_line(evidence)

    assert evidence.classification is update.BuildCapacityPreflightClassification.PASS
    assert evidence.phase is update.BuildCapacityPreflightPhase.BUILD_CAPACITY_PREFLIGHT
    assert evidence.predicate is update.BuildCapacityPreflightPredicate.PASS
    assert json.loads(line) == {
        "build_count": 0,
        "builder_selection_known": True,
        "builder_selection_predicate": "PASS",
        "cache_action_count": 0,
        "classification": "PASS",
        "container_count": 0,
        "mutation_count": 0,
        "node_schema_known": True,
        "node_schema_predicate": "PASS",
        "phase": "BUILD_CAPACITY_PREFLIGHT",
        "predicate": "PASS",
        "retry_count": 0,
    }
    assert events == [
        "lock-enter",
        "host-preflight",
        "clean-source",
        "source-proof",
        "capacity",
        "clean-source",
        "source-hash-check",
        "initial-idle",
        "clean-source",
        "source-hash-check",
        "lock-exit",
    ]


@pytest.mark.parametrize(
    "predicate",
    (
        "COMPOSE_CONFIG",
        "BUILDER_SELECTION",
        "CACHE_EVIDENCE",
        "CAPACITY_POLICY",
        "INITIAL_BUILDER_IDLE_PROBE",
        "INITIAL_BUILDER_ACTIVE",
    ),
)
def test_build_capacity_preflight_preserves_structured_first_failure(
    predicate: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    preflight = _passed_host_preflight(update, env_file=tmp_path / ".env.mac-development")
    closed = update.BuildCapacityPreflightPredicate(predicate)

    @contextmanager
    def lock(_root: Path) -> Iterator[object]:
        yield object()

    def capacity(*_args: object, **kwargs: object) -> str:
        selection = cast(Any, kwargs["builder_selection_recorder"])
        node_schema = cast(Any, kwargs["node_schema_recorder"])
        if predicate.startswith("INITIAL_"):
            node_schema.record(update.NodeSchemaPredicate.PASS)
            selection.record(update.BuilderSelectionPredicate.PASS)
            return "desktop-linux"
        if predicate == "BUILDER_SELECTION":
            selection.record(update.BuilderSelectionPredicate.ROW_SCHEMA)
        elif predicate not in {"COMPOSE_CONFIG"}:
            node_schema.record(update.NodeSchemaPredicate.PASS)
            selection.record(update.BuilderSelectionPredicate.PASS)
        raise update.DockerCapacityPhaseError("fixed-safe-error", closed)

    def idle(*_args: object, **_kwargs: object) -> None:
        raise update.DockerCapacityPhaseError("fixed-safe-error", closed)

    monkeypatch.setattr(update, "exclusive_docker_workflow_lock", lock)
    monkeypatch.setattr(update, "_host_environment_preflight_under_lock", lambda: preflight)
    _stub_clean_capacity_source(update, monkeypatch)
    monkeypatch.setattr(update, "_preflight_build_capacity", capacity)
    monkeypatch.setattr(update, "_require_idle_builder", idle)

    evidence = update._build_capacity_preflight_diagnostic()
    line = update.format_build_capacity_preflight_line(evidence)

    assert evidence.classification is update.BuildCapacityPreflightClassification.REJECTED
    assert evidence.predicate is closed
    assert "fixed-safe-error" not in line


@pytest.mark.parametrize(
    ("case", "expected"),
    (
        ("host", "HOST_ENVIRONMENT_PREFLIGHT"),
        ("clean", "CLEAN_CHECKOUT"),
        ("source", "SOURCE_PROVENANCE"),
        ("compose-arguments", "COMPOSE_ARGUMENTS"),
    ),
)
def test_build_capacity_preflight_classifies_host_source_and_argument_boundaries(
    case: str,
    expected: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    preflight = _passed_host_preflight(update, env_file=tmp_path / ".env.mac-development")

    @contextmanager
    def lock(_root: Path) -> Iterator[object]:
        yield object()

    if case == "host":
        preflight = update._HostEnvironmentPreflightResult(
            update.HostEnvironmentPreflightEvidence(
                classification=update.HostEnvironmentPreflightClassification.REJECTED,
                phase=update.HostEnvironmentPreflightPhase.HOST_ENVIRONMENT_PREFLIGHT,
                predicate=update.HostEnvironmentPreflightPredicate.ENV_READ,
            )
        )
    monkeypatch.setattr(update, "exclusive_docker_workflow_lock", lock)
    monkeypatch.setattr(update, "_host_environment_preflight_under_lock", lambda: preflight)
    _stub_clean_capacity_source(update, monkeypatch)
    if case == "clean":
        monkeypatch.setattr(
            update,
            "_fixture_diagnostic_source_state",
            lambda: update._FixtureSourceCleanState.DIRTY,
        )

    def source() -> str:
        if case == "source":
            raise RuntimeError("raw-source-proof-sentinel")
        return "a" * 64

    monkeypatch.setattr(update, "current_fixture_source_sha256", source)
    if case == "compose-arguments":

        def compose_arguments_failure(*_args: object, **kwargs: object) -> str:
            recorder = cast(Any, kwargs["phase_recorder"])
            recorder.mark(update.BuildCapacityPreflightPredicate.COMPOSE_ARGUMENTS)
            raise RuntimeError("raw-compose-argument-sentinel")

        monkeypatch.setattr(update, "_preflight_build_capacity", compose_arguments_failure)

    evidence = update._build_capacity_preflight_diagnostic()
    line = update.format_build_capacity_preflight_line(evidence)

    assert evidence.classification is update.BuildCapacityPreflightClassification.REJECTED
    assert evidence.predicate.value == expected
    assert "raw-source-proof-sentinel" not in line
    assert "raw-compose-argument-sentinel" not in line


def test_build_capacity_preflight_evidence_rejects_nonzero_actions() -> None:
    update = _load_update_module()

    for field in ("mutation_count", "cache_action_count", "build_count", "container_count"):
        with pytest.raises(update.WorkflowError, match="BUILD_CAPACITY_PREFLIGHT_EVIDENCE_INVALID"):
            update.BuildCapacityPreflightEvidence(
                classification=update.BuildCapacityPreflightClassification.REJECTED,
                phase=update.BuildCapacityPreflightPhase.BUILD_CAPACITY_PREFLIGHT,
                predicate=update.BuildCapacityPreflightPredicate.CAPACITY_POLICY,
                builder_selection_known=True,
                builder_selection_predicate=update.BuilderSelectionPredicate.PASS,
                node_schema_known=True,
                node_schema_predicate=update.NodeSchemaPredicate.PASS,
                **{field: 1},
            )


def test_build_capacity_preflight_builder_selection_output_is_closed_and_optional() -> None:
    update = _load_update_module()
    failure = update.BuildCapacityPreflightEvidence(
        classification=update.BuildCapacityPreflightClassification.REJECTED,
        phase=update.BuildCapacityPreflightPhase.BUILD_CAPACITY_PREFLIGHT,
        predicate=update.BuildCapacityPreflightPredicate.BUILDER_SELECTION,
        builder_selection_known=True,
        builder_selection_predicate=(update.BuilderSelectionPredicate.DRIVER_NOT_DOCKER),
        node_schema_known=True,
        node_schema_predicate=update.NodeSchemaPredicate.PASS,
    )
    later = update.BuildCapacityPreflightEvidence(
        classification=update.BuildCapacityPreflightClassification.REJECTED,
        phase=update.BuildCapacityPreflightPhase.BUILD_CAPACITY_PREFLIGHT,
        predicate=update.BuildCapacityPreflightPredicate.DOCKER_PLATFORM,
        builder_selection_known=True,
        builder_selection_predicate=update.BuilderSelectionPredicate.PASS,
        node_schema_known=True,
        node_schema_predicate=update.NodeSchemaPredicate.PASS,
    )
    before = update.BuildCapacityPreflightEvidence(
        classification=update.BuildCapacityPreflightClassification.REJECTED,
        phase=update.BuildCapacityPreflightPhase.BUILD_CAPACITY_PREFLIGHT,
        predicate=update.BuildCapacityPreflightPredicate.COMPOSE_CONFIG,
    )

    failure_line = json.loads(update.format_build_capacity_preflight_line(failure))
    later_line = json.loads(update.format_build_capacity_preflight_line(later))
    before_line = json.loads(update.format_build_capacity_preflight_line(before))

    assert failure_line["builder_selection_known"] is True
    assert failure_line["builder_selection_predicate"] == "DRIVER_NOT_DOCKER"
    assert failure_line["node_schema_known"] is True
    assert failure_line["node_schema_predicate"] == "PASS"
    assert later_line["builder_selection_known"] is True
    assert later_line["builder_selection_predicate"] == "PASS"
    assert later_line["node_schema_known"] is True
    assert later_line["node_schema_predicate"] == "PASS"
    assert before_line["builder_selection_known"] is False
    assert "builder_selection_predicate" not in before_line
    assert before_line["node_schema_known"] is False
    assert "node_schema_predicate" not in before_line
    assert "null" not in update.format_build_capacity_preflight_line(before)


def test_build_capacity_preflight_node_schema_output_is_closed_and_optional() -> None:
    update = _load_update_module()
    assert tuple(predicate.value for predicate in update.NodeSchemaPredicate) == (
        "NODE_NOT_MAPPING",
        "NAME_MISSING",
        "NAME_NULL",
        "NAME_NOT_STRING",
        "ENDPOINT_MISSING",
        "ENDPOINT_NULL",
        "ENDPOINT_NOT_STRING",
        "STATUS_NULL",
        "STATUS_NOT_STRING",
        "PASS",
        "UNKNOWN",
    )
    failure = update.BuildCapacityPreflightEvidence(
        classification=update.BuildCapacityPreflightClassification.REJECTED,
        phase=update.BuildCapacityPreflightPhase.BUILD_CAPACITY_PREFLIGHT,
        predicate=update.BuildCapacityPreflightPredicate.BUILDER_SELECTION,
        builder_selection_known=True,
        builder_selection_predicate=update.BuilderSelectionPredicate.NODE_SCHEMA,
        node_schema_known=True,
        node_schema_predicate=update.NodeSchemaPredicate.NAME_MISSING,
    )
    before = update.BuildCapacityPreflightEvidence(
        classification=update.BuildCapacityPreflightClassification.REJECTED,
        phase=update.BuildCapacityPreflightPhase.BUILD_CAPACITY_PREFLIGHT,
        predicate=update.BuildCapacityPreflightPredicate.BUILDER_SELECTION,
        builder_selection_known=True,
        builder_selection_predicate=update.BuilderSelectionPredicate.ROW_SCHEMA,
    )

    failure_line = json.loads(update.format_build_capacity_preflight_line(failure))
    before_line = json.loads(update.format_build_capacity_preflight_line(before))

    assert failure_line["builder_selection_predicate"] == "NODE_SCHEMA"
    assert failure_line["node_schema_known"] is True
    assert failure_line["node_schema_predicate"] == "NAME_MISSING"
    assert before_line["node_schema_known"] is False
    assert "node_schema_predicate" not in before_line
    assert "null" not in update.format_build_capacity_preflight_line(before)


@pytest.mark.parametrize(
    ("builder", "node_known", "node"),
    (
        ("NODE_SCHEMA", False, None),
        ("NODE_SCHEMA", True, "PASS"),
        ("NODE_SCHEMA", True, "UNKNOWN"),
        ("DRIVER_NOT_DOCKER", True, "NAME_MISSING"),
        ("DRIVER_NOT_DOCKER", False, None),
        ("ROW_SCHEMA", True, "PASS"),
        ("PASS", False, None),
    ),
)
def test_build_capacity_preflight_rejects_contradictory_node_schema_evidence(
    builder: str,
    node_known: bool,
    node: str | None,
) -> None:
    update = _load_update_module()
    closed_node = None if node is None else update.NodeSchemaPredicate(node)

    with pytest.raises(
        update.WorkflowError,
        match="BUILD_CAPACITY_PREFLIGHT_EVIDENCE_INVALID",
    ):
        update.BuildCapacityPreflightEvidence(
            classification=update.BuildCapacityPreflightClassification.REJECTED,
            phase=update.BuildCapacityPreflightPhase.BUILD_CAPACITY_PREFLIGHT,
            predicate=(
                update.BuildCapacityPreflightPredicate.DOCKER_PLATFORM
                if builder == "PASS"
                else update.BuildCapacityPreflightPredicate.BUILDER_SELECTION
            ),
            builder_selection_known=True,
            builder_selection_predicate=update.BuilderSelectionPredicate(builder),
            node_schema_known=node_known,
            node_schema_predicate=closed_node,
        )


def test_build_capacity_preflight_rejects_raw_or_extra_node_schema_fields() -> None:
    update = _load_update_module()
    base = {
        "classification": update.BuildCapacityPreflightClassification.REJECTED,
        "phase": update.BuildCapacityPreflightPhase.BUILD_CAPACITY_PREFLIGHT,
        "predicate": update.BuildCapacityPreflightPredicate.COMPOSE_CONFIG,
    }

    for fields in (
        {"node_schema_known": cast(Any, 1)},
        {
            "node_schema_known": True,
            "node_schema_predicate": cast(Any, "PASS"),
        },
    ):
        with pytest.raises(
            update.WorkflowError,
            match="BUILD_CAPACITY_PREFLIGHT_EVIDENCE_INVALID",
        ):
            update.BuildCapacityPreflightEvidence(**base, **fields)
    with pytest.raises(TypeError):
        update.BuildCapacityPreflightEvidence(
            **base,
            raw_node_name=cast(Any, "raw-node-schema-sentinel"),
        )


@pytest.mark.parametrize(
    ("top", "known", "selection"),
    (
        ("BUILDER_SELECTION", False, None),
        ("BUILDER_SELECTION", True, "PASS"),
        ("BUILDER_SELECTION", True, "UNKNOWN"),
        ("DOCKER_PLATFORM", True, "DRIVER_NOT_DOCKER"),
        ("COMPOSE_CONFIG", True, "PASS"),
        ("DOCKER_PLATFORM", False, "PASS"),
        ("DOCKER_PLATFORM", True, None),
    ),
)
def test_build_capacity_preflight_rejects_contradictory_builder_selection_evidence(
    top: str,
    known: bool,
    selection: str | None,
) -> None:
    update = _load_update_module()
    closed_selection = None if selection is None else update.BuilderSelectionPredicate(selection)

    with pytest.raises(
        update.WorkflowError,
        match="BUILD_CAPACITY_PREFLIGHT_EVIDENCE_INVALID",
    ):
        update.BuildCapacityPreflightEvidence(
            classification=update.BuildCapacityPreflightClassification.REJECTED,
            phase=update.BuildCapacityPreflightPhase.BUILD_CAPACITY_PREFLIGHT,
            predicate=update.BuildCapacityPreflightPredicate(top),
            builder_selection_known=known,
            builder_selection_predicate=closed_selection,
        )


def test_build_capacity_preflight_rejects_nonboolean_raw_or_extra_builder_fields() -> None:
    update = _load_update_module()
    base = {
        "classification": update.BuildCapacityPreflightClassification.REJECTED,
        "phase": update.BuildCapacityPreflightPhase.BUILD_CAPACITY_PREFLIGHT,
        "predicate": update.BuildCapacityPreflightPredicate.COMPOSE_CONFIG,
    }

    for fields in (
        {"builder_selection_known": cast(Any, 1)},
        {
            "builder_selection_known": True,
            "builder_selection_predicate": cast(Any, "PASS"),
        },
    ):
        with pytest.raises(
            update.WorkflowError,
            match="BUILD_CAPACITY_PREFLIGHT_EVIDENCE_INVALID",
        ):
            update.BuildCapacityPreflightEvidence(**base, **fields)
    with pytest.raises(TypeError):
        update.BuildCapacityPreflightEvidence(
            **base,
            raw_builder_name=cast(Any, "raw-builder-sentinel"),
        )


def test_build_capacity_review_required_forbids_every_other_nonunknown_top_predicate() -> None:
    update = _load_update_module()

    with pytest.raises(
        update.WorkflowError,
        match="BUILD_CAPACITY_PREFLIGHT_EVIDENCE_INVALID",
    ):
        update.BuildCapacityPreflightEvidence(
            classification=(update.BuildCapacityPreflightClassification.OPERATOR_REVIEW_REQUIRED),
            phase=update.BuildCapacityPreflightPhase.BUILD_CAPACITY_PREFLIGHT,
            predicate=update.BuildCapacityPreflightPredicate.DOCKER_PLATFORM,
            builder_selection_known=True,
            builder_selection_predicate=update.BuilderSelectionPredicate.PASS,
            node_schema_known=True,
            node_schema_predicate=update.NodeSchemaPredicate.PASS,
        )


@pytest.mark.parametrize(
    (
        "case",
        "expected_top",
        "expected_known",
        "expected_selection",
        "expected_node_known",
        "expected_node",
    ),
    (
        ("before-interrupt", "UNKNOWN", False, None, False, None),
        ("node-pass-interrupt", "UNKNOWN", False, None, True, "PASS"),
        ("selection-failure", "BUILDER_SELECTION", True, "DRIVER_NOT_DOCKER", True, "PASS"),
        ("later-failure", "DOCKER_PLATFORM", True, "PASS", True, "PASS"),
        ("lock-exit", "UNKNOWN", True, "PASS", True, "PASS"),
    ),
)
def test_build_capacity_preflight_retains_monotonic_builder_selection_outcome(
    case: str,
    expected_top: str,
    expected_known: bool,
    expected_selection: str | None,
    expected_node_known: bool,
    expected_node: str | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    preflight = _passed_host_preflight(update, env_file=tmp_path / ".env.mac-development")

    @contextmanager
    def lock(_root: Path) -> Iterator[object]:
        yield object()
        if case == "lock-exit":
            raise RuntimeError("raw-lock-exit-sentinel")

    def capacity(*_args: object, **kwargs: object) -> str:
        if case == "before-interrupt":
            raise KeyboardInterrupt("raw-selection-interrupt-sentinel")
        recorder = cast(Any, kwargs["builder_selection_recorder"])
        node_schema = cast(Any, kwargs["node_schema_recorder"])
        node_schema.record(update.NodeSchemaPredicate.PASS)
        if case == "node-pass-interrupt":
            raise KeyboardInterrupt("raw-node-schema-pass-interrupt-sentinel")
        if case == "selection-failure":
            recorder.record(update.BuilderSelectionPredicate.DRIVER_NOT_DOCKER)
            raise update.DockerCapacityPhaseError(
                "fixed-safe-error",
                update.BuildCapacityPreflightPredicate.BUILDER_SELECTION,
            )
        recorder.record(update.BuilderSelectionPredicate.PASS)
        if case == "later-failure":
            raise update.DockerCapacityPhaseError(
                "fixed-safe-error",
                update.BuildCapacityPreflightPredicate.DOCKER_PLATFORM,
            )
        return "desktop-linux"

    monkeypatch.setattr(update, "exclusive_docker_workflow_lock", lock)
    monkeypatch.setattr(update, "_host_environment_preflight_under_lock", lambda: preflight)
    _stub_clean_capacity_source(update, monkeypatch)
    monkeypatch.setattr(update, "_preflight_build_capacity", capacity)
    monkeypatch.setattr(update, "_require_idle_builder", lambda *_args, **_kwargs: None)

    evidence = update._build_capacity_preflight_diagnostic()
    rendered = update.format_build_capacity_preflight_line(evidence)

    assert evidence.predicate.value == expected_top
    assert evidence.builder_selection_known is expected_known
    assert (
        None
        if evidence.builder_selection_predicate is None
        else evidence.builder_selection_predicate.value
    ) == expected_selection
    assert evidence.node_schema_known is expected_node_known
    assert (
        None if evidence.node_schema_predicate is None else evidence.node_schema_predicate.value
    ) == expected_node
    assert "raw-selection-interrupt-sentinel" not in rendered
    assert "raw-node-schema-pass-interrupt-sentinel" not in rendered
    assert "raw-lock-exit-sentinel" not in rendered


@pytest.mark.parametrize("failure", (RuntimeError, KeyboardInterrupt, BaseException))
def test_builder_selection_failure_survives_later_lock_exit_failure(
    failure: type[BaseException],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    preflight = _passed_host_preflight(update, env_file=tmp_path / ".env.mac-development")

    @contextmanager
    def lock(_root: Path) -> Iterator[object]:
        yield object()
        raise failure("raw-lock-exit-after-selection-sentinel")

    def capacity(*_args: object, **kwargs: object) -> str:
        selection = cast(Any, kwargs["builder_selection_recorder"])
        node_schema = cast(Any, kwargs["node_schema_recorder"])
        node_schema.record(update.NodeSchemaPredicate.PASS)
        selection.record(update.BuilderSelectionPredicate.DRIVER_NOT_DOCKER)
        raise update.DockerCapacityPhaseError(
            "fixed-selection-failure",
            update.BuildCapacityPreflightPredicate.BUILDER_SELECTION,
        )

    monkeypatch.setattr(update, "exclusive_docker_workflow_lock", lock)
    monkeypatch.setattr(update, "_host_environment_preflight_under_lock", lambda: preflight)
    _stub_clean_capacity_source(update, monkeypatch)
    monkeypatch.setattr(update, "_preflight_build_capacity", capacity)

    evidence = update._build_capacity_preflight_diagnostic()
    rendered = update.format_build_capacity_preflight_line(evidence)

    assert evidence.classification is (
        update.BuildCapacityPreflightClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.predicate is update.BuildCapacityPreflightPredicate.BUILDER_SELECTION
    assert evidence.builder_selection_known is True
    assert evidence.builder_selection_predicate is (
        update.BuilderSelectionPredicate.DRIVER_NOT_DOCKER
    )
    assert evidence.node_schema_known is True
    assert evidence.node_schema_predicate is update.NodeSchemaPredicate.PASS
    assert evidence.mutation_count == 0
    assert evidence.cache_action_count == 0
    assert evidence.build_count == 0
    assert evidence.container_count == 0
    assert evidence.retry_count == 0
    assert rendered.count("\n") == 0
    assert "raw-lock-exit-after-selection-sentinel" not in rendered
    assert "fixed-selection-failure" not in rendered


@pytest.mark.parametrize("failure", (RuntimeError, KeyboardInterrupt, BaseException))
def test_node_schema_failure_survives_later_lock_exit_failure(
    failure: type[BaseException],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    preflight = _passed_host_preflight(update, env_file=tmp_path / ".env.mac-development")

    @contextmanager
    def lock(_root: Path) -> Iterator[object]:
        yield object()
        raise failure("raw-lock-exit-after-node-schema-sentinel")

    def capacity(*_args: object, **kwargs: object) -> str:
        selection = cast(Any, kwargs["builder_selection_recorder"])
        node_schema = cast(Any, kwargs["node_schema_recorder"])
        node_schema.record(update.NodeSchemaPredicate.ENDPOINT_NULL)
        selection.record(update.BuilderSelectionPredicate.NODE_SCHEMA)
        raise update.DockerCapacityPhaseError(
            "fixed-node-schema-failure",
            update.BuildCapacityPreflightPredicate.BUILDER_SELECTION,
        )

    monkeypatch.setattr(update, "exclusive_docker_workflow_lock", lock)
    monkeypatch.setattr(update, "_host_environment_preflight_under_lock", lambda: preflight)
    _stub_clean_capacity_source(update, monkeypatch)
    monkeypatch.setattr(update, "_preflight_build_capacity", capacity)

    evidence = update._build_capacity_preflight_diagnostic()
    rendered = update.format_build_capacity_preflight_line(evidence)

    assert evidence.classification is (
        update.BuildCapacityPreflightClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.predicate is update.BuildCapacityPreflightPredicate.BUILDER_SELECTION
    assert evidence.builder_selection_predicate is update.BuilderSelectionPredicate.NODE_SCHEMA
    assert evidence.node_schema_known is True
    assert evidence.node_schema_predicate is update.NodeSchemaPredicate.ENDPOINT_NULL
    assert evidence.mutation_count == 0
    assert evidence.cache_action_count == 0
    assert evidence.build_count == 0
    assert evidence.container_count == 0
    assert evidence.retry_count == 0
    assert rendered.count("\n") == 0
    assert "raw-lock-exit-after-node-schema-sentinel" not in rendered
    assert "fixed-node-schema-failure" not in rendered


def test_build_capacity_measure_only_action_required_never_runs_prune_or_later_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    preflight = _passed_host_preflight(update, env_file=tmp_path / ".env.mac-development")
    later: list[str] = []

    @contextmanager
    def lock(_root: Path) -> Iterator[object]:
        yield object()

    def action_required(*_args: object, **kwargs: object) -> str:
        selection = cast(Any, kwargs["builder_selection_recorder"])
        node_schema = cast(Any, kwargs["node_schema_recorder"])
        node_schema.record(update.NodeSchemaPredicate.PASS)
        selection.record(update.BuilderSelectionPredicate.PASS)
        raise update.DockerCapacityMeasureOnlyStop()

    monkeypatch.setattr(update, "exclusive_docker_workflow_lock", lock)
    monkeypatch.setattr(update, "_host_environment_preflight_under_lock", lambda: preflight)
    _stub_clean_capacity_source(update, monkeypatch)
    monkeypatch.setattr(update, "_preflight_build_capacity", action_required)
    monkeypatch.setattr(
        update,
        "_require_idle_builder",
        lambda *_args, **_kwargs: later.append("idle"),
    )
    monkeypatch.setattr(
        update,
        "_build_current_fixture_image",
        lambda **_kwargs: later.append("build"),
    )

    evidence = update._build_capacity_preflight_diagnostic()

    assert evidence.classification is update.BuildCapacityPreflightClassification.REJECTED
    assert evidence.predicate is update.BuildCapacityPreflightPredicate.CACHE_ACTION_REQUIRED
    assert evidence.cache_action_count == 0
    assert evidence.build_count == 0
    assert evidence.container_count == 0
    assert later == []


def test_build_capacity_executor_forwards_only_exact_help_before_action_required(
    tmp_path: Path,
) -> None:
    update = _load_update_module()
    dockerfile = tmp_path / "backend" / "Dockerfile"
    source = tmp_path / "backend" / "app.py"
    dockerfile.parent.mkdir(parents=True)
    dockerfile.write_text("FROM scratch\n", encoding="utf-8")
    source.write_text("x" * 1_000, encoding="utf-8")
    (tmp_path / ".dockerignore").write_text(
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
    builder = {
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
    outputs = {
        "COMPOSE_BUILD_CONFIG_PROBE_FAILED": json.dumps(
            {
                "name": "datariver-next",
                "services": {
                    "local-bootstrap": {
                        "build": {
                            "context": os.fspath(tmp_path),
                            "dockerfile": "backend/Dockerfile",
                        }
                    }
                },
            }
        ),
        "GIT_CLEAN_CHECKOUT_PROBE_FAILED": "",
        "GIT_BUILD_CONTEXT_PROBE_FAILED": "backend/Dockerfile\0backend/app.py\0",
        "DOCKER_CONTEXT_PROBE_FAILED": (
            json.dumps("desktop-linux") + "|" + json.dumps("unix:///private/docker.sock")
        ),
        "DOCKER_BUILDER_LIST_PROBE_FAILED": "\n".join((json.dumps(builder), json.dumps(builder))),
        "DOCKER_PLATFORM_PROBE_FAILED": "linux/arm64\n",
        "DOCKER_IMAGE_SIZE_PROBE_FAILED": ("sha256:" + ("a" * 64) + "\t10000000\tlinux\tarm64\n"),
        "DOCKER_BUILD_CACHE_PROBE_FAILED": json.dumps(
            {
                "ID": "cache-1",
                "Reclaimable": True,
                "Shared": False,
                "Size": "140MB",
            }
        ),
        "DOCKER_BACKING_FILESYSTEM_PROBE_FAILED": (
            "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
            "overlay 1000000 400000 600000 40% /\n"
        ),
        "DOCKER_BUILD_CACHE_HELP_PROBE_FAILED": (
            "--all --builder --force --max-used-space --min-free-space --reserved-space"
        ),
        "DOCKER_ACTIVE_BUILD_PROBE_FAILED": "",
    }

    class Delegate:
        def __init__(self) -> None:
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
            return outputs[classification]

    delegate = Delegate()
    executor = update._BuildCapacityPreflightExecutor(delegate)
    recorder = update.DockerCapacityPhaseRecorder()
    lock = SimpleNamespace(require_held=lambda: None)
    with pytest.raises(update.DockerCapacityMeasureOnlyStop):
        update.governed_compose_build_capacity(
            root=tmp_path,
            compose_config_command=("compose", "config", "--format", "json"),
            docker_filesystem_probe_command=("compose", "exec", "postgres", "df"),
            selected_build_services=("local-bootstrap",),
            environ={},
            lock=lock,
            executor=executor,
            mode=update.DockerCapacityMode.MEASURE_ONLY,
            phase_recorder=recorder,
        )

    prune_calls = [
        arguments
        for _classification, arguments in delegate.calls
        if arguments[:3] == ("docker", "buildx", "prune")
    ]
    assert prune_calls == [("docker", "buildx", "prune", "--help")]
    assert recorder.predicate is update.BuildCapacityPreflightPredicate.CACHE_ACTION_REQUIRED


@pytest.mark.parametrize(
    "arguments",
    (
        ("docker", "buildx", "prune"),
        ("docker", "buildx", "prune", "--help", "--force"),
        ("docker", "buildx", "prune", "--force"),
        ("docker", "buildx", "prune", "--builder", "desktop-linux"),
    ),
)
def test_build_capacity_executor_rejects_every_nonhelp_prune_tuple(
    arguments: tuple[str, ...],
) -> None:
    update = _load_update_module()
    delegated: list[tuple[str, ...]] = []

    class Delegate:
        def output(
            self,
            command: tuple[str, ...],
            *,
            classification: str,
            timeout_seconds: int,
        ) -> str:
            del classification, timeout_seconds
            delegated.append(command)
            return "unexpected"

    executor = update._BuildCapacityPreflightExecutor(Delegate())

    with pytest.raises(
        update.DockerCapacityError,
        match="BUILD_CAPACITY_PREFLIGHT_MUTATION_FORBIDDEN",
    ):
        executor.output(arguments, classification="FIXED", timeout_seconds=1)
    assert delegated == []


@pytest.mark.parametrize(
    ("checkpoint", "post_state", "hash_drift"),
    (
        ("capacity", "DIRTY", False),
        ("capacity", "INVALID", False),
        ("capacity", "UNKNOWN", False),
        ("action-required", "DIRTY", False),
        ("idle", "CLEAN", True),
    ),
)
def test_build_capacity_source_drift_is_review_required_before_trusted_result(
    checkpoint: str,
    post_state: str,
    hash_drift: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    preflight = _passed_host_preflight(update, env_file=tmp_path / ".env.mac-development")
    events: list[str] = []
    clean_states = iter(("CLEAN", post_state, "CLEAN"))
    hash_checks = 0

    @contextmanager
    def lock(_root: Path) -> Iterator[object]:
        yield object()

    def source_state() -> object:
        value = next(clean_states)
        events.append(f"source-{value}")
        return update._FixtureSourceCleanState(value)

    def require_same(_expected: str) -> None:
        nonlocal hash_checks
        hash_checks += 1
        events.append("source-hash-check")
        if hash_drift and hash_checks == 2:
            raise RuntimeError("raw-source-drift-sentinel")

    def capacity(*_args: object, **_kwargs: object) -> str:
        events.append("capacity")
        if checkpoint == "action-required":
            raise update.DockerCapacityMeasureOnlyStop()
        return "desktop-linux"

    def idle(*_args: object, **_kwargs: object) -> None:
        events.append("idle")

    monkeypatch.setattr(update, "exclusive_docker_workflow_lock", lock)
    monkeypatch.setattr(update, "_host_environment_preflight_under_lock", lambda: preflight)
    monkeypatch.setattr(update, "_fixture_diagnostic_source_state", source_state)
    monkeypatch.setattr(update, "current_fixture_source_sha256", lambda: "a" * 64)
    monkeypatch.setattr(update, "require_current_fixture_source", require_same)
    monkeypatch.setattr(update, "_preflight_build_capacity", capacity)
    monkeypatch.setattr(update, "_require_idle_builder", idle)

    evidence = update._build_capacity_preflight_diagnostic()
    rendered = update.format_build_capacity_preflight_line(evidence)

    assert evidence.classification is (
        update.BuildCapacityPreflightClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.predicate is update.BuildCapacityPreflightPredicate.UNKNOWN
    assert evidence.mutation_count == 0
    assert evidence.retry_count == 0
    assert "raw-source-drift-sentinel" not in rendered
    if checkpoint != "idle":
        assert "idle" not in events


@pytest.mark.parametrize("failure", (KeyboardInterrupt, SystemExit, BaseException))
def test_build_capacity_nested_git_interrupt_is_unknown_before_capacity(
    failure: type[BaseException],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    preflight = _passed_host_preflight(update, env_file=tmp_path / ".env.mac-development")
    later: list[str] = []

    @contextmanager
    def lock(_root: Path) -> Iterator[object]:
        yield object()

    def interrupted(*_args: object, **_kwargs: object) -> Any:
        raise failure("raw-git-source-interrupt")

    monkeypatch.setattr(update, "exclusive_docker_workflow_lock", lock)
    monkeypatch.setattr(update, "_host_environment_preflight_under_lock", lambda: preflight)
    monkeypatch.setattr(update.subprocess, "Popen", interrupted)
    monkeypatch.setattr(
        update,
        "_preflight_build_capacity",
        lambda *_args, **_kwargs: later.append("capacity"),
    )

    evidence = update._build_capacity_preflight_diagnostic()
    rendered = update.format_build_capacity_preflight_line(evidence)

    assert evidence.classification is (
        update.BuildCapacityPreflightClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.predicate is update.BuildCapacityPreflightPredicate.UNKNOWN
    assert later == []
    assert "raw-git-source-interrupt" not in rendered


@pytest.mark.parametrize("step", ("host", "source", "capacity", "idle"))
@pytest.mark.parametrize("failure", (KeyboardInterrupt, SystemExit, BaseException))
def test_build_capacity_preflight_interrupt_is_unknown_and_stops_later_calls(
    step: str,
    failure: type[BaseException],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    preflight = _passed_host_preflight(update, env_file=tmp_path / ".env.mac-development")
    later: list[str] = []

    @contextmanager
    def lock(_root: Path) -> Iterator[object]:
        yield object()

    def stop_if(name: str) -> None:
        if step == name:
            raise failure("raw-capacity-interrupt-sentinel")

    def host() -> object:
        stop_if("host")
        return preflight

    def source_clean() -> object:
        stop_if("source")
        return update._FixtureSourceCleanState.CLEAN

    def capacity(*_args: object, **_kwargs: object) -> str:
        stop_if("capacity")
        return "desktop-linux"

    def idle(*_args: object, **_kwargs: object) -> None:
        stop_if("idle")

    monkeypatch.setattr(update, "exclusive_docker_workflow_lock", lock)
    monkeypatch.setattr(update, "_host_environment_preflight_under_lock", host)
    monkeypatch.setattr(update, "_fixture_diagnostic_source_state", source_clean)
    monkeypatch.setattr(update, "current_fixture_source_sha256", lambda: "a" * 64)

    def require_same(expected_sha256: str) -> None:
        assert expected_sha256 == "a" * 64

    monkeypatch.setattr(update, "require_current_fixture_source", require_same)
    monkeypatch.setattr(update, "_preflight_build_capacity", capacity)
    monkeypatch.setattr(update, "_require_idle_builder", idle)
    monkeypatch.setattr(
        update,
        "_build_current_fixture_image",
        lambda **_kwargs: later.append("build"),
    )

    evidence = update._build_capacity_preflight_diagnostic()
    line = update.format_build_capacity_preflight_line(evidence)

    assert evidence.classification is (
        update.BuildCapacityPreflightClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.predicate is update.BuildCapacityPreflightPredicate.UNKNOWN
    assert evidence.mutation_count == 0
    assert evidence.retry_count == 0
    assert later == []
    assert "raw-capacity-interrupt-sentinel" not in line


def test_build_capacity_preflight_main_accepts_only_exact_phase_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    update = _load_update_module()
    accepted = update.BuildCapacityPreflightEvidence(
        classification=update.BuildCapacityPreflightClassification.PASS,
        phase=update.BuildCapacityPreflightPhase.BUILD_CAPACITY_PREFLIGHT,
        predicate=update.BuildCapacityPreflightPredicate.PASS,
        builder_selection_known=True,
        builder_selection_predicate=update.BuilderSelectionPredicate.PASS,
        node_schema_known=True,
        node_schema_predicate=update.NodeSchemaPredicate.PASS,
    )
    calls: list[str] = []

    def diagnose() -> object:
        calls.append("diagnose")
        return accepted

    monkeypatch.setattr(
        update,
        "_build_capacity_preflight_diagnostic",
        diagnose,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            os.fspath(UPDATE_MODULE_PATH),
            "--diagnostic-phase",
            "BUILD_CAPACITY_PREFLIGHT",
        ],
    )

    assert update.main() == 0
    assert calls == ["diagnose"]
    assert json.loads(capsys.readouterr().out)["predicate"] == "PASS"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            os.fspath(UPDATE_MODULE_PATH),
            "--diagnostic-phase",
            "BUILD_CAPACITY_PREFLIGHT",
            os.fspath(tmp_path / "raw-secret-extra"),
        ],
    )
    assert update.main() == 2
    assert calls == ["diagnose"]
    rejected = json.loads(capsys.readouterr().out)
    assert rejected["phase"] == "BUILD_CAPACITY_PREFLIGHT"
    assert rejected["predicate"] == "UNKNOWN"
    assert "raw-secret-extra" not in json.dumps(rejected)


@pytest.mark.parametrize(
    ("phase", "expected_phase"),
    (
        ("BUILD_CAPACITY_PREFLIGHT", "BUILD_CAPACITY_PREFLIGHT"),
        ("HOST_ENVIRONMENT_PREFLIGHT", "HOST_ENVIRONMENT_PREFLIGHT"),
    ),
)
def test_diagnostic_phase_equals_form_is_fixed_before_argparse_and_lock(
    phase: str,
    expected_phase: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    update = _load_update_module()
    locks: list[str] = []
    monkeypatch.setattr(
        update,
        "exclusive_docker_workflow_lock",
        lambda *_args, **_kwargs: locks.append("lock"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            os.fspath(UPDATE_MODULE_PATH),
            f"--diagnostic-phase={phase}",
            os.fspath(tmp_path / "raw-equals-secret"),
        ],
    )

    assert update.main() == 2
    output = capsys.readouterr()
    assert output.err == ""
    evidence = json.loads(output.out)
    assert evidence["classification"] == "REJECTED"
    assert evidence["phase"] == expected_phase
    assert evidence["predicate"] == "UNKNOWN"
    assert "raw-equals-secret" not in json.dumps(evidence)
    assert locks == []


@pytest.mark.parametrize(
    ("arguments", "expected_phase"),
    (
        (("--diagnostic-phase=BUILD_CAPACITY_PREFLIGHT/raw-sentinel",), "BUILD_CAPACITY_PREFLIGHT"),
        (
            ("--diagnostic-phase=HOST_ENVIRONMENT_PREFLIGHT/raw-sentinel",),
            "HOST_ENVIRONMENT_PREFLIGHT",
        ),
        (("--diagnostic-phase=UNREVIEWED/raw-sentinel",), "INVALID_DIAGNOSTIC"),
        (
            (
                "--diagnostic-phase=BUILD_CAPACITY_PREFLIGHT",
                "--diagnostic-phase=HOST_ENVIRONMENT_PREFLIGHT",
            ),
            "INVALID_DIAGNOSTIC",
        ),
    ),
)
def test_diagnostic_phase_every_equals_prefix_is_fixed_without_raw_or_calls(
    arguments: tuple[str, ...],
    expected_phase: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    update = _load_update_module()
    calls: list[str] = []

    def forbidden(name: str) -> Any:
        calls.append(name)
        pytest.fail(f"The malformed diagnostic reached {name}.")

    monkeypatch.setattr(
        update,
        "exclusive_docker_workflow_lock",
        lambda *_args, **_kwargs: forbidden("lock"),
    )
    monkeypatch.setattr(
        update,
        "_build_capacity_preflight_diagnostic",
        lambda: forbidden("capacity-diagnostic"),
    )
    monkeypatch.setattr(
        update,
        "_host_environment_preflight_diagnostic",
        lambda: forbidden("host-diagnostic"),
    )
    monkeypatch.setattr(update, "parse_args", lambda: forbidden("argparse"))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            os.fspath(UPDATE_MODULE_PATH),
            *arguments,
            os.fspath(tmp_path / "raw-extra-secret"),
        ],
    )

    assert update.main() == 2
    output = capsys.readouterr()
    assert output.err == ""
    evidence = json.loads(output.out)
    assert evidence["classification"] == "REJECTED"
    assert evidence["phase"] == expected_phase
    assert evidence["predicate"] == "UNKNOWN"
    assert evidence["mutation_count"] == 0
    assert evidence["retry_count"] == 0
    assert "raw" not in json.dumps(evidence)
    assert calls == []


@pytest.mark.parametrize("outcome_known", (True, False))
def test_fixture_diagnostic_provenance_failure_stops_before_ephemeral_query(
    outcome_known: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    environment = {"APP_ENV": "development"}
    state = _topology_state(
        profile="mac-development",
        env_file=os.fspath(tmp_path / ".env.mac-development"),
        environment_key_hashes=update.environment_key_hashes(environment),
    )
    (tmp_path / ".env.mac-development").write_text("APP_ENV=development\n", encoding="utf-8")
    events: list[str] = []

    @contextmanager
    def lock(_root: Path) -> Iterator[object]:
        yield object()

    monkeypatch.setattr(update, "exclusive_docker_workflow_lock", lock)
    monkeypatch.setattr(update, "load_applied_state", lambda _path: state)
    monkeypatch.setattr(update, "read_env_values", lambda _path: environment)
    monkeypatch.setattr(update, "current_fixture_source_sha256", lambda: "a" * 64)
    monkeypatch.setattr(update, "_fixture_diagnostic_source_is_clean", lambda: True)
    monkeypatch.setattr(update, "_preflight_build_capacity", lambda *_args, **_kwargs: "builder")
    monkeypatch.setattr(update, "_require_idle_builder", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        update,
        "_build_current_fixture_image",
        lambda **_kwargs: update._FixtureBuildOutcome(
            attempted=True,
            succeeded=False,
            outcome_known=outcome_known,
        ),
    )
    fixture_type = update._ComposeGatewayAuthParityFixture
    original_init = fixture_type.__init__

    def record_init(self: Any, **kwargs: object) -> None:
        events.append("query")
        original_init(self, **kwargs)

    monkeypatch.setattr(fixture_type, "__init__", record_init)

    evidence = update._fixture_require_absent_diagnostic()

    assert evidence.predicate is FixtureDiagnosticPredicate.IMAGE_PROVENANCE
    assert events == []


def test_fixture_diagnostic_dirty_source_stops_before_capacity_build_and_query(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    env_file = tmp_path / ".env.mac-development"
    env_file.write_text("APP_ENV=development\n", encoding="utf-8")
    environment = {"APP_ENV": "development"}
    state = _topology_state(
        profile="mac-development",
        env_file=os.fspath(env_file),
        environment_key_hashes=update.environment_key_hashes(environment),
    )
    events: list[str] = []

    @contextmanager
    def lock(_root: Path) -> Iterator[object]:
        yield object()

    monkeypatch.setattr(update, "exclusive_docker_workflow_lock", lock)
    monkeypatch.setattr(update, "load_applied_state", lambda _path: state)
    monkeypatch.setattr(update, "read_env_values", lambda _path: environment)
    monkeypatch.setattr(update, "_fixture_diagnostic_source_is_clean", lambda: False)
    monkeypatch.setattr(
        update,
        "_preflight_build_capacity",
        lambda *_args, **_kwargs: events.append("capacity"),
    )
    monkeypatch.setattr(
        update,
        "_build_current_fixture_image",
        lambda **_kwargs: events.append("build"),
    )
    fixture_type = update._ComposeGatewayAuthParityFixture
    original_init = fixture_type.__init__

    def record_init(self: Any, **kwargs: object) -> None:
        events.append("query")
        original_init(self, **kwargs)

    monkeypatch.setattr(fixture_type, "__init__", record_init)

    evidence = update._fixture_require_absent_diagnostic()

    assert evidence.predicate is FixtureDiagnosticPredicate.IMAGE_PROVENANCE
    assert events == []


def test_fixture_diagnostic_build_is_exact_local_bootstrap_action_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    commands: list[tuple[str, ...]] = []

    def build(command: tuple[str, ...]) -> object:
        commands.append(command)
        return update._FixtureBuildOutcome(True, True, True)

    monkeypatch.setattr(update, "_bounded_suppressed_fixture_build", build)

    outcome = update._build_current_fixture_image(
        env_file=tmp_path / ".env.mac-development",
        files=(ROOT / "compose.yaml",),
    )
    assert outcome == update._FixtureBuildOutcome(True, True, True)
    assert len(commands) == 1
    assert commands[0][-2:] == ("build", "local-bootstrap")
    profile_index = commands[0].index("--profile")
    assert commands[0][profile_index + 1] == "tools"
    assert "--no-build" not in commands[0]


@pytest.mark.parametrize(
    ("result", "expected_state", "expected_clean"),
    (
        (subprocess.CompletedProcess(("git",), 0, "", ""), "CLEAN", True),
        (subprocess.CompletedProcess(("git",), 0, " M fixed.py", ""), "DIRTY", False),
        (subprocess.CompletedProcess(("git",), 2, "", ""), "INVALID", False),
        (FixtureDiagnosticPredicate.OUTPUT_SIZE, "INVALID", False),
        (FixtureDiagnosticPredicate.UNKNOWN, "UNKNOWN", False),
    ),
)
def test_fixture_diagnostic_clean_source_proof_is_fail_closed(
    result: subprocess.CompletedProcess[str] | FixtureDiagnosticPredicate,
    expected_state: str,
    expected_clean: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    calls: list[tuple[tuple[str, ...], str]] = []

    def run(command: tuple[str, ...], input_text: str) -> object:
        calls.append((command, input_text))
        return result

    monkeypatch.setattr(update, "_bounded_fixture_diagnostic_process", run)

    assert update._fixture_diagnostic_source_state().value == expected_state
    assert update._fixture_diagnostic_source_is_clean() is expected_clean
    assert calls == [
        (("git", "status", "--porcelain", "--untracked-files=normal"), "{}"),
        (("git", "status", "--porcelain", "--untracked-files=normal"), "{}"),
    ]


def test_fixture_diagnostic_dual_stream_capture_is_capped_while_child_runs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    update = _load_update_module()

    outcome = update._bounded_fixture_diagnostic_process(
        (
            sys.executable,
            "-c",
            (
                "import os,time;"
                f"os.write(1,b'raw-secret-sentinel'+b'x'*{update.MAXIMUM_FIXTURE_DIAGNOSTIC_BYTES});"
                "time.sleep(5)"
            ),
        ),
        "{}",
    )

    assert outcome is FixtureDiagnosticPredicate.OUTPUT_SIZE
    exposed = capsys.readouterr().out + capsys.readouterr().err
    assert "raw-secret-sentinel" not in exposed


def test_fixture_diagnostic_dual_stream_conflict_and_nonzero_remain_fixed() -> None:
    update = _load_update_module()
    controller = update._ComposeGatewayAuthParityFixture(
        env_file=ROOT / ".env.mac-development",
        files=(ROOT / "compose.yaml",),
    )
    conflict = update._bounded_fixture_diagnostic_process(
        (sys.executable, "-c", "import sys;print('{}');print('{}',file=sys.stderr)"),
        "{}",
    )
    nonzero = update._bounded_fixture_diagnostic_process(
        (sys.executable, "-c", "import sys;sys.exit(7)"),
        "{}",
    )

    assert not isinstance(conflict, FixtureDiagnosticPredicate)
    assert controller._parse_require_absent_result(conflict).predicate is (
        FixtureDiagnosticPredicate.OUTPUT_TUPLE
    )
    assert not isinstance(nonzero, FixtureDiagnosticPredicate)
    assert controller._parse_require_absent_result(nonzero).predicate is (
        FixtureDiagnosticPredicate.PROCESS_NONZERO
    )


def test_fixture_diagnostic_timeout_terminates_and_reaps_child_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    original_popen = subprocess.Popen
    processes: list[subprocess.Popen[bytes]] = []

    def popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        process: subprocess.Popen[bytes] = cast(Any, original_popen)(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(update.subprocess, "Popen", popen)
    monkeypatch.setattr(update, "_FIXTURE_DIAGNOSTIC_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(update, "_FIXTURE_DIAGNOSTIC_REAP_SECONDS", 1)

    outcome = update._bounded_fixture_diagnostic_process(
        (sys.executable, "-c", "import time;time.sleep(5)"),
        "{}",
    )

    assert outcome is FixtureDiagnosticPredicate.PROCESS_TIMEOUT
    assert len(processes) == 1
    assert processes[0].poll() is not None


def test_fixture_diagnostic_timeout_kills_child_that_ignores_terminate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    original_popen = subprocess.Popen
    processes: list[subprocess.Popen[bytes]] = []

    def popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        process: subprocess.Popen[bytes] = cast(Any, original_popen)(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(update.subprocess, "Popen", popen)
    monkeypatch.setattr(update, "_FIXTURE_DIAGNOSTIC_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(update, "_FIXTURE_DIAGNOSTIC_REAP_SECONDS", 0.05)

    outcome = update._bounded_fixture_diagnostic_process(
        (
            sys.executable,
            "-c",
            "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(5)",
        ),
        "{}",
    )

    assert outcome is FixtureDiagnosticPredicate.PROCESS_TIMEOUT
    assert len(processes) == 1
    assert processes[0].poll() is not None


def test_fixture_diagnostic_spawn_and_reap_failures_are_fixed_and_nonleaking(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    update = _load_update_module()
    original_popen = subprocess.Popen

    def spawn_failure(*_args: object, **_kwargs: object) -> object:
        raise OSError("raw-provider-secret-sentinel")

    monkeypatch.setattr(update.subprocess, "Popen", spawn_failure)
    assert update._bounded_fixture_diagnostic_process(("fixed",), "{}") is (
        FixtureDiagnosticPredicate.PROCESS_SPAWN
    )

    monkeypatch.setattr(update.subprocess, "Popen", original_popen)
    inner = original_popen(
        (sys.executable, "-c", "import time;time.sleep(5)"),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    class UnreapableProcess:
        stdin = inner.stdin
        stdout = inner.stdout
        stderr = inner.stderr

        def poll(self) -> None:
            return None

        def wait(self, *, timeout: float) -> int:
            raise subprocess.TimeoutExpired(("fixed",), timeout)

        def terminate(self) -> None:
            inner.terminate()

        def kill(self) -> None:
            inner.kill()

    monkeypatch.setattr(update.subprocess, "Popen", lambda *_args, **_kwargs: UnreapableProcess())
    monkeypatch.setattr(update, "_FIXTURE_DIAGNOSTIC_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(update, "_FIXTURE_DIAGNOSTIC_REAP_SECONDS", 0.01)
    try:
        outcome = update._bounded_fixture_diagnostic_process(("fixed",), "{}")
    finally:
        inner.kill()
        inner.wait(timeout=1)

    assert outcome is FixtureDiagnosticPredicate.UNKNOWN
    assert "raw-provider" not in (capsys.readouterr().out + capsys.readouterr().err)


def test_fixture_diagnostic_capacity_recorder_preserves_ambiguous_action() -> None:
    update = _load_update_module()
    calls: list[tuple[str, ...]] = []

    class Executor:
        def output(
            self,
            arguments: tuple[str, ...],
            *,
            classification: str,
            timeout_seconds: int,
        ) -> str:
            del classification, timeout_seconds
            calls.append(arguments)
            if arguments[:3] == ("docker", "buildx", "prune"):
                raise KeyboardInterrupt("raw-provider-secret-sentinel")
            return "fixed"

    recorder = update._FixtureDiagnosticCapacityExecutor(Executor())

    with pytest.raises(KeyboardInterrupt):
        recorder.output(
            ("docker", "buildx", "prune", "--force"),
            classification="fixed",
            timeout_seconds=1,
        )

    assert calls == [("docker", "buildx", "prune", "--force")]
    assert recorder.action_count_known is True
    assert recorder.action_count == 1
    assert recorder.action_succeeded is False
    assert recorder.action_outcome_known is False


def test_fixture_diagnostic_capacity_failure_retains_cache_action_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    env_file = tmp_path / ".env.mac-development"
    env_file.write_text("APP_ENV=development\n", encoding="utf-8")
    environment = {"APP_ENV": "development"}
    state = _topology_state(
        profile="mac-development",
        env_file=os.fspath(env_file),
        environment_key_hashes=update.environment_key_hashes(environment),
    )
    recorder = SimpleNamespace(
        action_count_known=True,
        action_count=0,
        action_succeeded=False,
        action_outcome_known=True,
    )
    later_actions: list[str] = []

    @contextmanager
    def lock(_root: Path) -> Iterator[object]:
        yield object()

    def capacity(*_args: object, **kwargs: object) -> str:
        assert kwargs["executor"] is recorder
        recorder.action_count = 1
        recorder.action_outcome_known = False
        raise KeyboardInterrupt("raw-provider-secret-sentinel")

    monkeypatch.setattr(update, "exclusive_docker_workflow_lock", lock)
    monkeypatch.setattr(update, "load_applied_state", lambda _path: state)
    monkeypatch.setattr(update, "read_env_values", lambda _path: environment)
    monkeypatch.setattr(update, "_fixture_diagnostic_source_is_clean", lambda: True)
    monkeypatch.setattr(update, "current_fixture_source_sha256", lambda: "a" * 64)
    monkeypatch.setattr(update, "_FixtureDiagnosticCapacityExecutor", lambda: recorder)
    monkeypatch.setattr(update, "_preflight_build_capacity", capacity)
    monkeypatch.setattr(
        update,
        "_build_current_fixture_image",
        lambda **_kwargs: later_actions.append("build"),
    )
    monkeypatch.setattr(
        update,
        "_ComposeGatewayAuthParityFixture",
        lambda **_kwargs: later_actions.append("container"),
    )

    evidence = update._fixture_require_absent_diagnostic()

    assert evidence.classification is (
        update.FixtureDiagnosticExecutionClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.predicate is FixtureDiagnosticPredicate.ENVIRONMENT_DEPENDENCY
    assert evidence.cache_action_count_known is True
    assert evidence.cache_action_count == 1
    assert evidence.cache_action_outcome_known is False
    assert evidence.build_attempted is False
    assert evidence.container_attempted is False
    assert evidence.retry_count == 0
    assert later_actions == []


def test_fixture_diagnostic_outer_evidence_is_bounded_honest_and_value_free() -> None:
    update = _load_update_module()
    execution = update._FixtureDiagnosticExecutionState(
        cache_action_count_known=True,
        cache_action_count=1,
        cache_action_succeeded=False,
        cache_action_outcome_known=False,
        build_attempted=True,
        build_succeeded=False,
        build_outcome_known=False,
        builder_idle_known=False,
        container_attempted=True,
        container_cleanup_known=False,
        container_cleanup_required=True,
        container_residual_known=False,
        container_residual_count=None,
    )
    evidence = execution.to_evidence(FixtureDiagnosticPredicate.PROCESS_TIMEOUT)
    line = update.format_fixture_diagnostic_execution_line(evidence)
    document = json.loads(line)

    assert evidence.classification is (
        update.FixtureDiagnosticExecutionClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert document == {
        "build_attempted": True,
        "build_outcome_known": False,
        "build_succeeded": False,
        "builder_idle": False,
        "builder_idle_known": False,
        "business_mutation_count": 0,
        "cache_action_count": 1,
        "cache_action_count_known": True,
        "cache_action_outcome_known": False,
        "cache_action_succeeded": False,
        "classification": "OPERATOR_REVIEW_REQUIRED",
        "container_attempted": True,
        "container_cleanup_known": False,
        "container_cleanup_required": True,
        "container_remove_attempts": 0,
        "container_residual_count": None,
        "container_residual_known": False,
        "container_stop_attempts": 0,
        "data_mutation_count": 0,
        "identity_mutation_count": 0,
        "operation": "REQUIRE_ABSENT",
        "predicate": "PROCESS_TIMEOUT",
        "push_count": 0,
        "retry_count": 0,
        "state_mutation_count": 0,
        "topology_mutation_count": 0,
    }
    assert "provider-secret-sentinel" not in line
    assert len(line.encode("utf-8")) <= update.MAXIMUM_FIXTURE_EXECUTION_EVIDENCE_BYTES

    with pytest.raises(update.WorkflowError):
        replace(evidence, retry_count=1)
    with pytest.raises(update.WorkflowError):
        replace(evidence, cache_action_count_known=1)


def test_fixture_diagnostic_build_failure_always_attempts_post_idle_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    env_file = tmp_path / ".env.mac-development"
    env_file.write_text("APP_ENV=development\n", encoding="utf-8")
    environment = {"APP_ENV": "development"}
    state = _topology_state(
        profile="mac-development",
        env_file=os.fspath(env_file),
        environment_key_hashes=update.environment_key_hashes(environment),
    )
    idle_calls: list[str] = []

    @contextmanager
    def lock(_root: Path) -> Iterator[object]:
        yield object()

    def idle(*_args: object, **_kwargs: object) -> None:
        idle_calls.append("idle")
        if len(idle_calls) == 2:
            raise RuntimeError("raw-provider-secret-sentinel")

    monkeypatch.setattr(update, "exclusive_docker_workflow_lock", lock)
    monkeypatch.setattr(update, "load_applied_state", lambda _path: state)
    monkeypatch.setattr(update, "read_env_values", lambda _path: environment)
    monkeypatch.setattr(update, "_fixture_diagnostic_source_is_clean", lambda: True)
    monkeypatch.setattr(update, "current_fixture_source_sha256", lambda: "a" * 64)
    monkeypatch.setattr(update, "_preflight_build_capacity", lambda *_args, **_kwargs: "builder")
    monkeypatch.setattr(update, "_require_idle_builder", idle)
    monkeypatch.setattr(
        update,
        "_build_current_fixture_image",
        lambda **_kwargs: update._FixtureBuildOutcome(
            attempted=True,
            succeeded=False,
            outcome_known=False,
        ),
    )

    evidence = update._fixture_require_absent_diagnostic()

    assert idle_calls == ["idle", "idle"]
    assert (
        evidence.classification
        is update.FixtureDiagnosticExecutionClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.build_attempted is True
    assert evidence.build_succeeded is False
    assert evidence.build_outcome_known is False
    assert evidence.builder_idle_known is False
    assert evidence.retry_count == 0


@pytest.mark.parametrize(
    ("mode", "expected_events", "expected_succeeded", "expected_known"),
    (
        ("nonzero", ("wait",), False, True),
        ("terminate", ("wait", "terminate", "wait"), False, False),
        (
            "kill",
            ("wait", "terminate", "wait", "kill", "wait"),
            False,
            False,
        ),
        (
            "unreaped",
            ("wait", "terminate", "wait", "kill", "wait"),
            False,
            False,
        ),
    ),
)
def test_fixture_diagnostic_build_process_outcome_and_reap_are_bounded(
    mode: str,
    expected_events: tuple[str, ...],
    expected_succeeded: bool,
    expected_known: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    events: list[str] = []

    class Process:
        def __init__(self) -> None:
            self.wait_calls = 0

        def wait(self, *, timeout: float) -> int:
            events.append("wait")
            self.wait_calls += 1
            if mode == "nonzero":
                return 7
            if mode == "terminate" and self.wait_calls == 2:
                return 0
            if mode == "kill" and self.wait_calls == 3:
                return 0
            raise subprocess.TimeoutExpired(("fixed",), timeout)

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            events.append("terminate")

        def kill(self) -> None:
            events.append("kill")

    monkeypatch.setattr(update.subprocess, "Popen", lambda *_args, **_kwargs: Process())

    outcome = update._bounded_suppressed_fixture_build(
        ("docker", "compose", "build", "local-bootstrap")
    )

    assert tuple(events) == expected_events
    assert outcome.attempted is True
    assert outcome.succeeded is expected_succeeded
    assert outcome.outcome_known is expected_known


@pytest.mark.parametrize(
    ("status", "contract", "operation", "expected"),
    (
        ("running", "SEC-GATEWAY-AUTH-PARITY-001-A-V1", "REQUIRE_ABSENT", "OWNED_RUNNING"),
        ("exited", "SEC-GATEWAY-AUTH-PARITY-001-A-V1", "REQUIRE_ABSENT", "OWNED_STOPPED"),
        ("running", "foreign-contract", "REQUIRE_ABSENT", "FOREIGN"),
        ("running", "SEC-GATEWAY-AUTH-PARITY-001-A-V1", "OTHER", "FOREIGN"),
        ("unknown", "SEC-GATEWAY-AUTH-PARITY-001-A-V1", "REQUIRE_ABSENT", "UNKNOWN"),
    ),
)
def test_fixture_diagnostic_container_snapshot_requires_exact_name_and_labels(
    status: str,
    contract: str,
    operation: str,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    update = _load_update_module()
    commands: list[tuple[str, ...]] = []
    results = iter(
        (
            subprocess.CompletedProcess(
                ("docker",),
                0,
                f"{update._FIXTURE_DIAGNOSTIC_CONTAINER_NAME}\n",
                "",
            ),
            subprocess.CompletedProcess(
                ("docker",),
                0,
                f"{json.dumps(status)}|{json.dumps(contract)}|{json.dumps(operation)}\n",
                "",
            ),
        )
    )

    def execute(command: tuple[str, ...], _input: str) -> object:
        commands.append(command)
        return next(results)

    monkeypatch.setattr(update, "_bounded_fixture_diagnostic_process", execute)

    snapshot = update._fixture_container_snapshot()

    assert snapshot is update._FixtureContainerState[expected]
    assert commands[0] == (
        "docker",
        "container",
        "ls",
        "--all",
        "--filter",
        f"name=^/{update._FIXTURE_DIAGNOSTIC_CONTAINER_NAME}$",
        "--format",
        "{{.Names}}",
    )
    assert commands[1][-1] == update._FIXTURE_DIAGNOSTIC_CONTAINER_NAME
    assert "raw-container-id-sentinel" not in (capsys.readouterr().out + capsys.readouterr().err)


@pytest.mark.parametrize(
    "prestate",
    (
        "OWNED_RUNNING",
        "OWNED_STOPPED",
        "FOREIGN",
        "UNKNOWN",
    ),
)
def test_fixture_diagnostic_preexisting_exact_name_stops_before_child(
    prestate: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    execution = update._FixtureDiagnosticExecutionState()
    child_calls: list[str] = []
    monkeypatch.setattr(
        update,
        "_fixture_container_snapshot",
        lambda: update._FixtureContainerState[prestate],
    )
    monkeypatch.setattr(
        update,
        "_bounded_fixture_diagnostic_process",
        lambda *_args, **_kwargs: child_calls.append("child"),
    )
    controller = update._ComposeGatewayAuthParityFixture(
        env_file=tmp_path / ".env",
        files=(ROOT / "compose.yaml",),
        source_sha256="a" * 64,
        execution_state=execution,
    )

    evidence = controller.diagnose_require_absent()

    assert evidence.predicate is FixtureDiagnosticPredicate.UNKNOWN
    assert child_calls == []
    assert execution.container_attempted is False
    assert execution.container_cleanup_required is True


def test_fixture_diagnostic_ambiguous_create_cleans_only_exact_owned_container(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    execution = update._FixtureDiagnosticExecutionState()
    snapshots = iter(
        (
            update._FixtureContainerState.ABSENT,
            update._FixtureContainerState.OWNED_RUNNING,
            update._FixtureContainerState.OWNED_STOPPED,
            update._FixtureContainerState.ABSENT,
        )
    )
    controls: list[str] = []
    commands: list[tuple[str, ...]] = []

    def run_child(
        command: tuple[str, ...],
        _input: str,
    ) -> FixtureDiagnosticPredicate:
        commands.append(command)
        return FixtureDiagnosticPredicate.PROCESS_TIMEOUT

    def stop() -> Any:
        controls.append("stop")
        return update._DockerActionOutcome(True, True)

    def remove() -> Any:
        controls.append("remove")
        return update._DockerActionOutcome(True, True)

    monkeypatch.setattr(update, "_fixture_container_snapshot", lambda: next(snapshots))
    monkeypatch.setattr(update, "_bounded_fixture_diagnostic_process", run_child)
    monkeypatch.setattr(update, "_stop_fixture_container", stop)
    monkeypatch.setattr(update, "_remove_fixture_container", remove)
    controller = update._ComposeGatewayAuthParityFixture(
        env_file=tmp_path / ".env",
        files=(ROOT / "compose.yaml",),
        source_sha256="a" * 64,
        execution_state=execution,
    )

    evidence = controller.diagnose_require_absent()

    assert evidence.predicate is FixtureDiagnosticPredicate.PROCESS_TIMEOUT
    assert len(commands) == 1
    assert ("--name", update._FIXTURE_DIAGNOSTIC_CONTAINER_NAME) == (
        commands[0][commands[0].index("--name")],
        commands[0][commands[0].index("--name") + 1],
    )
    assert (
        "--label",
        update._FIXTURE_DIAGNOSTIC_CONTAINER_CONTRACT_LABEL,
    ) == (
        commands[0][commands[0].index("--label")],
        commands[0][commands[0].index("--label") + 1],
    )
    second_label = commands[0].index("--label", commands[0].index("--label") + 1)
    assert commands[0][second_label : second_label + 2] == (
        "--label",
        update._FIXTURE_DIAGNOSTIC_CONTAINER_OPERATION_LABEL,
    )
    assert controls == ["stop", "remove"]
    assert execution.container_attempted is True
    assert execution.container_stop_attempts == 1
    assert execution.container_remove_attempts == 1
    assert execution.container_cleanup_known is True
    assert execution.container_cleanup_required is False
    assert execution.container_residual_known is True
    assert execution.container_residual_count == 0


@pytest.mark.parametrize("failure_type", (RuntimeError, KeyboardInterrupt))
def test_fixture_diagnostic_create_baseexception_still_proves_zero_residual(
    failure_type: type[BaseException],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    update = _load_update_module()
    execution = update._FixtureDiagnosticExecutionState()
    snapshots = iter(
        (
            update._FixtureContainerState.ABSENT,
            update._FixtureContainerState.ABSENT,
        )
    )

    def fail(*_args: object, **_kwargs: object) -> object:
        raise failure_type("raw-provider-secret-sentinel")

    monkeypatch.setattr(update, "_fixture_container_snapshot", lambda: next(snapshots))
    monkeypatch.setattr(update, "_bounded_fixture_diagnostic_process", fail)
    controller = update._ComposeGatewayAuthParityFixture(
        env_file=tmp_path / ".env",
        files=(ROOT / "compose.yaml",),
        source_sha256="a" * 64,
        execution_state=execution,
    )

    evidence = controller.diagnose_require_absent()

    assert evidence.predicate is FixtureDiagnosticPredicate.UNKNOWN
    assert execution.container_attempted is True
    assert execution.container_stop_attempts == 0
    assert execution.container_remove_attempts == 0
    assert execution.container_cleanup_known is True
    assert execution.container_cleanup_required is False
    assert execution.container_residual_known is True
    assert execution.container_residual_count == 0
    assert "raw-provider-secret-sentinel" not in (capsys.readouterr().out + capsys.readouterr().err)


def test_fixture_diagnostic_cleanup_failure_retains_exact_residual_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    execution = update._FixtureDiagnosticExecutionState()
    snapshots = iter(
        (
            update._FixtureContainerState.ABSENT,
            update._FixtureContainerState.OWNED_STOPPED,
            update._FixtureContainerState.OWNED_STOPPED,
        )
    )
    monkeypatch.setattr(update, "_fixture_container_snapshot", lambda: next(snapshots))
    monkeypatch.setattr(
        update,
        "_bounded_fixture_diagnostic_process",
        lambda *_args, **_kwargs: FixtureDiagnosticPredicate.PROCESS_TIMEOUT,
    )
    monkeypatch.setattr(
        update,
        "_remove_fixture_container",
        lambda: update._DockerActionOutcome(False, False),
    )
    controller = update._ComposeGatewayAuthParityFixture(
        env_file=tmp_path / ".env",
        files=(ROOT / "compose.yaml",),
        source_sha256="a" * 64,
        execution_state=execution,
    )

    controller.diagnose_require_absent()

    assert execution.container_attempted is True
    assert execution.container_remove_attempts == 1
    assert execution.container_cleanup_known is True
    assert execution.container_cleanup_required is True
    assert execution.container_residual_known is True
    assert execution.container_residual_count == 1


@pytest.mark.parametrize(
    ("cleanup_states", "failed_action"),
    (
        (("ABSENT", "UNKNOWN"), None),
        (("ABSENT", "OWNED_STOPPED", "OWNED_STOPPED"), "remove"),
        (("ABSENT", "OWNED_RUNNING", "OWNED_RUNNING"), "stop"),
    ),
)
def test_fixture_diagnostic_child_pass_requires_proven_container_cleanup(
    cleanup_states: tuple[str, ...],
    failed_action: str | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    execution = update._FixtureDiagnosticExecutionState()
    snapshots = iter(tuple(update._FixtureContainerState[state] for state in cleanup_states))
    child_line = format_fixture_diagnostic_line(
        FixtureDiagnosticEnvelope(
            FixtureDiagnosticOperation.REQUIRE_ABSENT,
            FixtureDiagnosticPredicate.PASS,
        )
    )
    monkeypatch.setattr(update, "_fixture_container_snapshot", lambda: next(snapshots))
    monkeypatch.setattr(
        update,
        "_bounded_fixture_diagnostic_process",
        lambda command, _input: subprocess.CompletedProcess(command, 0, child_line, ""),
    )
    monkeypatch.setattr(
        update,
        "_stop_fixture_container",
        lambda: update._DockerActionOutcome(failed_action != "stop", True),
    )
    monkeypatch.setattr(
        update,
        "_remove_fixture_container",
        lambda: update._DockerActionOutcome(failed_action != "remove", True),
    )
    controller = update._ComposeGatewayAuthParityFixture(
        env_file=tmp_path / ".env",
        files=(ROOT / "compose.yaml",),
        source_sha256="a" * 64,
        execution_state=execution,
    )

    evidence = controller.diagnose_require_absent()
    outer = execution.to_evidence(evidence.predicate)

    assert evidence.predicate is FixtureDiagnosticPredicate.UNKNOWN
    assert outer.classification is (
        update.FixtureDiagnosticExecutionClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert execution.container_cleanup_required is True


def test_fixture_diagnostic_child_pass_cleanup_baseexception_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    update = _load_update_module()
    execution = update._FixtureDiagnosticExecutionState()
    snapshot_calls = 0
    child_line = format_fixture_diagnostic_line(
        FixtureDiagnosticEnvelope(
            FixtureDiagnosticOperation.REQUIRE_ABSENT,
            FixtureDiagnosticPredicate.PASS,
        )
    )

    def snapshot() -> Any:
        nonlocal snapshot_calls
        snapshot_calls += 1
        if snapshot_calls == 1:
            return update._FixtureContainerState.ABSENT
        raise KeyboardInterrupt("raw-cleanup-secret-sentinel")

    monkeypatch.setattr(update, "_fixture_container_snapshot", snapshot)
    monkeypatch.setattr(
        update,
        "_bounded_fixture_diagnostic_process",
        lambda command, _input: subprocess.CompletedProcess(command, 0, child_line, ""),
    )
    controller = update._ComposeGatewayAuthParityFixture(
        env_file=tmp_path / ".env",
        files=(ROOT / "compose.yaml",),
        source_sha256="a" * 64,
        execution_state=execution,
    )

    evidence = controller.diagnose_require_absent()

    assert evidence.predicate is FixtureDiagnosticPredicate.UNKNOWN
    assert execution.container_cleanup_known is False
    assert execution.container_cleanup_required is True
    assert execution.container_residual_known is False
    assert "raw-cleanup-secret-sentinel" not in (capsys.readouterr().out + capsys.readouterr().err)


def test_fixture_diagnostic_nonpass_first_defect_survives_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    execution = update._FixtureDiagnosticExecutionState()
    snapshots = iter(
        (
            update._FixtureContainerState.ABSENT,
            update._FixtureContainerState.UNKNOWN,
        )
    )
    child_line = format_fixture_diagnostic_line(
        FixtureDiagnosticEnvelope(
            FixtureDiagnosticOperation.REQUIRE_ABSENT,
            FixtureDiagnosticPredicate.REPOSITORY_NOT_ABSENT,
        )
    )
    monkeypatch.setattr(update, "_fixture_container_snapshot", lambda: next(snapshots))
    monkeypatch.setattr(
        update,
        "_bounded_fixture_diagnostic_process",
        lambda command, _input: subprocess.CompletedProcess(command, 2, "", child_line),
    )
    controller = update._ComposeGatewayAuthParityFixture(
        env_file=tmp_path / ".env",
        files=(ROOT / "compose.yaml",),
        source_sha256="a" * 64,
        execution_state=execution,
    )

    evidence = controller.diagnose_require_absent()
    outer = execution.to_evidence(evidence.predicate)

    assert evidence.predicate is FixtureDiagnosticPredicate.REPOSITORY_NOT_ABSENT
    assert outer.classification is (
        update.FixtureDiagnosticExecutionClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert outer.container_cleanup_required is True


@pytest.mark.parametrize(
    "poststate",
    ("FOREIGN", "UNKNOWN"),
)
def test_fixture_diagnostic_ambiguous_create_never_touches_unowned_or_unknown_container(
    poststate: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    execution = update._FixtureDiagnosticExecutionState()
    snapshots = iter(
        (
            update._FixtureContainerState.ABSENT,
            update._FixtureContainerState[poststate],
        )
    )
    controls: list[str] = []
    monkeypatch.setattr(update, "_fixture_container_snapshot", lambda: next(snapshots))
    monkeypatch.setattr(
        update,
        "_bounded_fixture_diagnostic_process",
        lambda *_args, **_kwargs: FixtureDiagnosticPredicate.PROCESS_TIMEOUT,
    )
    monkeypatch.setattr(
        update,
        "_stop_fixture_container",
        lambda: controls.append("stop"),
    )
    monkeypatch.setattr(
        update,
        "_remove_fixture_container",
        lambda: controls.append("remove"),
    )
    controller = update._ComposeGatewayAuthParityFixture(
        env_file=tmp_path / ".env",
        files=(ROOT / "compose.yaml",),
        source_sha256="a" * 64,
        execution_state=execution,
    )

    evidence = controller.diagnose_require_absent()

    assert evidence.predicate is FixtureDiagnosticPredicate.PROCESS_TIMEOUT
    assert controls == []
    assert execution.container_attempted is True
    assert execution.container_cleanup_required is True
    if poststate == "FOREIGN":
        assert execution.container_cleanup_known is True
        assert execution.container_residual_known is True
        assert execution.container_residual_count == 1
    else:
        assert execution.container_cleanup_known is False
        assert execution.container_residual_known is False
        assert execution.container_residual_count is None


def test_fixture_diagnostic_lock_exit_failure_preserves_all_attempted_actions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    update = _load_update_module()
    env_file = tmp_path / ".env.mac-development"
    env_file.write_text("APP_ENV=development\n", encoding="utf-8")
    environment = {"APP_ENV": "development"}
    state = _topology_state(
        profile="mac-development",
        env_file=os.fspath(env_file),
        environment_key_hashes=update.environment_key_hashes(environment),
    )

    @contextmanager
    def lock(_root: Path) -> Iterator[object]:
        try:
            yield object()
        finally:
            raise KeyboardInterrupt("raw-lock-secret-sentinel")

    class Fixture:
        def __init__(self, **kwargs: object) -> None:
            self.execution = cast(Any, kwargs["execution_state"])

        def diagnose_require_absent(self) -> FixtureDiagnosticEnvelope:
            self.execution.container_attempted = True
            self.execution.container_cleanup_known = True
            self.execution.container_cleanup_required = False
            self.execution.container_residual_known = True
            self.execution.container_residual_count = 0
            return FixtureDiagnosticEnvelope(
                FixtureDiagnosticOperation.REQUIRE_ABSENT,
                FixtureDiagnosticPredicate.PASS,
            )

    monkeypatch.setattr(update, "exclusive_docker_workflow_lock", lock)
    monkeypatch.setattr(update, "load_applied_state", lambda _path: state)
    monkeypatch.setattr(update, "read_env_values", lambda _path: environment)
    monkeypatch.setattr(update, "_fixture_diagnostic_source_is_clean", lambda: True)
    monkeypatch.setattr(update, "current_fixture_source_sha256", lambda: "a" * 64)
    monkeypatch.setattr(update, "_preflight_build_capacity", lambda *_args, **_kwargs: "builder")
    monkeypatch.setattr(update, "_require_idle_builder", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        update,
        "_build_current_fixture_image",
        lambda **_kwargs: update._FixtureBuildOutcome(True, True, True),
    )
    monkeypatch.setattr(update, "_ComposeGatewayAuthParityFixture", Fixture)

    evidence = update._fixture_require_absent_diagnostic()

    assert evidence.classification is (
        update.FixtureDiagnosticExecutionClassification.OPERATOR_REVIEW_REQUIRED
    )
    assert evidence.predicate is FixtureDiagnosticPredicate.UNKNOWN
    assert evidence.build_attempted is True
    assert evidence.build_succeeded is True
    assert evidence.builder_idle_known is True
    assert evidence.container_attempted is True
    assert evidence.container_cleanup_known is True
    assert evidence.container_residual_count == 0
    assert evidence.retry_count == 0
    assert "raw-lock-secret-sentinel" not in (capsys.readouterr().out + capsys.readouterr().err)


def test_gateway_parity_session_validates_all_targets_before_reading_admin_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_PUBLIC_ORIGIN=https://unreviewed.example.invalid\n",
        encoding="utf-8",
    )
    secret_reads: list[str] = []

    def read_gateway_admin_password(_guard: object) -> str:
        secret_reads.append("read")
        return "admin-secret-sentinel"

    monkeypatch.setattr(
        update,
        "_read_gateway_admin_password",
        read_gateway_admin_password,
    )

    with pytest.raises(
        update.GatewayAuthParityError,
        match="GATEWAY_AUTH_PARITY_TARGET_INVALID",
    ):
        update._gateway_auth_parity_session(
            env_file=env_file,
            files=(ROOT / "compose.yaml",),
            secret_guard=SimpleNamespace(revalidate=lambda: None),
        )

    assert secret_reads == []


def test_topology_apply_is_bracketed_by_one_gateway_parity_session_and_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    events: list[str] = []

    class Session:
        def __enter__(self) -> Self:
            events.append("session-enter")
            return self

        def __exit__(self, *_args: object) -> None:
            self.close()
            events.append("session-exit")

        def prepare(self) -> None:
            events.append("fixture-prepare")

        def enable(self) -> None:
            events.append("fixture-enable")

        def verify_after_topology(self) -> object:
            events.append("live-parity")
            return SimpleNamespace(immediate_logout="OPEN_UNSUPPORTED", retry_count=0)

        def close(self) -> None:
            if "fixture-clean" not in events:
                events.append("fixture-clean")

    monkeypatch.setattr(
        update,
        "_apply_topology_reconciliation",
        lambda *_args, **_kwargs: events.append("topology-apply"),
    )

    evidence = update._reconcile_topology_with_gateway_parity(
        session=Session(),
        runner=SimpleNamespace(note=lambda message: events.append(f"note:{message}")),
        env_file=tmp_path / ".env",
        files=(ROOT / "compose.yaml",),
        plan=_topology_reconciliation_plan(),
        selected_builder="builder",
        capacity_lock=object(),
        secret_guard=SimpleNamespace(revalidate=lambda: None),
    )

    assert evidence.immediate_logout == "OPEN_UNSUPPORTED"
    assert events[:5] == [
        "session-enter",
        "fixture-prepare",
        "fixture-enable",
        "topology-apply",
        "live-parity",
    ]
    assert events.count("fixture-clean") == 1
    assert events.index("fixture-clean") < events.index("session-exit")


def test_unreviewed_gateway_reconciliation_stops_under_lock_before_runtime_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    update = _load_update_module()
    env_file = tmp_path / ".env.mac-development"
    env_file.write_text("NEO4J_PROJECTION_ENABLED=true\n", encoding="utf-8")
    state = _topology_state(
        profile="mac-development",
        env_file=os.fspath(env_file),
        local_airflow=True,
        local_datahub=True,
        local_redis=True,
        local_storage=True,
    )
    events: list[str] = []

    class FakeRunner:
        def note(self, _message: str) -> None:
            return None

    class Lock:
        def __enter__(self) -> object:
            events.append("lock-enter")
            return object()

        def __exit__(self, *_args: object) -> None:
            events.append("lock-exit")

    monkeypatch.setattr(
        update,
        "parse_args",
        lambda: SimpleNamespace(
            profile="mac-development",
            env_file=None,
            release_dir=None,
            git_pull=False,
            reload_release=False,
            refresh_bootstrap=True,
            skip_catalog_sync=True,
            assume_yes=True,
            reconcile_local_topology="unreviewed-topology",
        ),
    )
    monkeypatch.setattr(update, "Runner", FakeRunner)
    monkeypatch.setattr(update, "require_command", lambda _command: None)
    monkeypatch.setattr(update, "state_path", lambda _root, _profile: tmp_path / "state.json")
    monkeypatch.setattr(update, "load_applied_state", lambda _path: state)
    monkeypatch.setattr(update, "require_clean_worktree", lambda _runner: None)
    monkeypatch.setattr(update, "current_commit", lambda _runner: "a" * 40)
    monkeypatch.setattr(update, "_git_paths", lambda *_args: ())
    monkeypatch.setattr(update, "exclusive_docker_workflow_lock", lambda _root: Lock())

    for name in (
        "_bootstrap",
        "_preflight_build_capacity",
        "_reconcile_local_reranker",
        "_compose",
        "_apply_topology_reconciliation",
        "write_applied_state",
    ):
        monkeypatch.setattr(
            update,
            name,
            lambda *_args, _name=name, **_kwargs: events.append(_name),
        )

    assert update.main() == 2

    assert events == ["lock-enter", "lock-exit"]
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "ERROR: GATEWAY_AUTH_PARITY_EVIDENCE_UNAVAILABLE"


def test_worker_create_stops_before_mutation_when_retained_secret_guard_drifted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    compose_calls: list[tuple[str, ...]] = []

    class SecretGuard:
        def revalidate(self) -> None:
            raise workflow.WorkflowError("TOPOLOGY_SECRET_PREFLIGHT_FAILED")

    monkeypatch.setattr(
        update,
        "_compose",
        lambda _runner, **kwargs: compose_calls.append(cast(tuple[str, ...], kwargs["trailing"])),
    )

    with pytest.raises(workflow.WorkflowError, match="TOPOLOGY_SECRET_PREFLIGHT_FAILED"):
        update._apply_topology_reconciliation(
            SimpleNamespace(note=lambda _message: None),
            env_file=tmp_path / ".env",
            files=(ROOT / "compose.yaml",),
            plan=_topology_reconciliation_plan(),
            selected_builder=None,
            capacity_lock=object(),
            secret_guard=SecretGuard(),
        )

    assert compose_calls == []


def test_gateway_log_probe_rejects_credential_persistence_without_raw_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    update = _load_update_module()
    sentinel = b"gateway-invalid-token-sentinel"

    monkeypatch.setattr(
        update,
        "_bounded_gateway_log_output",
        lambda _command: sentinel,
    )

    with pytest.raises(
        update.GatewayCredentialLogEvidenceError,
        match="GATEWAY_CREDENTIAL_LOG_PROBE_FAILED",
    ) as error:
        update._verify_gateway_logs_do_not_persist_probe_credentials(
            env_file=tmp_path / ".env",
            files=(ROOT / "compose.yaml",),
            started_at="2026-08-03T00:00:00.000000Z",
        )

    assert error.value.evidence_known is True
    captured = capsys.readouterr()
    exposed = captured.out + captured.err + str(error.value)
    assert sentinel.decode() not in exposed


def test_gateway_log_probe_uses_complete_exact_interval_and_all_three_services(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    commands: list[tuple[str, ...]] = []
    sentinel = "api-only-dynamic-token-secret-sentinel"

    def output(command: tuple[str, ...]) -> bytes:
        commands.append(command)
        return (("safe-line\n" * 250) + sentinel).encode()

    monkeypatch.setattr(update, "_bounded_gateway_log_output", output)
    with pytest.raises(
        update.GatewayCredentialLogEvidenceError,
        match="GATEWAY_CREDENTIAL_LOG_PROBE_FAILED",
    ):
        update._verify_gateway_logs_do_not_persist_probe_credentials(
            env_file=tmp_path / ".env",
            files=(ROOT / "compose.yaml",),
            started_at="2026-08-03T00:00:00.000000Z",
            sentinels=(sentinel,),
        )

    assert len(commands) == 1
    command = commands[0]
    since = command.index("--since")
    assert command[since + 1] == "2026-08-03T00:00:00.000000Z"
    assert command[-3:] == ("api", "apisix", "web")
    assert "--tail" not in command
    assert "2m" not in command


def test_gateway_log_capture_accepts_exact_cap_and_rejects_overflow_without_raw_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    update = _load_update_module()
    exact = update._bounded_gateway_log_output(
        (
            sys.executable,
            "-c",
            f"import os;os.write(1,b'x'*{update._GATEWAY_LOG_MAXIMUM_BYTES})",
        )
    )
    assert len(exact) == update._GATEWAY_LOG_MAXIMUM_BYTES

    with pytest.raises(
        update.GatewayCredentialLogEvidenceError,
        match="GATEWAY_CREDENTIAL_LOG_PROBE_FAILED",
    ) as captured:
        update._bounded_gateway_log_output(
            (
                sys.executable,
                "-c",
                (
                    "import os;os.write(1,b'provider-secret-sentinel'"
                    f"+b'x'*{update._GATEWAY_LOG_MAXIMUM_BYTES})"
                ),
            )
        )

    exposed = capsys.readouterr().out + capsys.readouterr().err + str(captured.value)
    assert "provider-secret-sentinel" not in exposed


def test_gateway_log_capture_timeout_terminates_and_reaps_child_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    original_popen = subprocess.Popen
    processes: list[subprocess.Popen[bytes]] = []

    def popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        process: subprocess.Popen[bytes] = cast(Any, original_popen)(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(update.subprocess, "Popen", popen)
    monkeypatch.setattr(update, "_GATEWAY_LOG_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(update, "_GATEWAY_LOG_REAP_SECONDS", 1)

    with pytest.raises(
        update.GatewayCredentialLogEvidenceError,
        match="GATEWAY_CREDENTIAL_LOG_PROBE_FAILED",
    ):
        update._bounded_gateway_log_output((sys.executable, "-c", "import time;time.sleep(5)"))

    assert len(processes) == 1
    assert processes[0].poll() is not None


def test_gateway_log_capture_nonzero_child_is_fixed_and_never_exposes_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    update = _load_update_module()

    with pytest.raises(
        update.GatewayCredentialLogEvidenceError,
        match="GATEWAY_CREDENTIAL_LOG_PROBE_FAILED",
    ) as captured:
        update._bounded_gateway_log_output(
            (
                sys.executable,
                "-c",
                "import sys;sys.stderr.write('provider-token-secret-sentinel');sys.exit(7)",
            )
        )

    exposed = capsys.readouterr().out + capsys.readouterr().err + str(captured.value)
    assert "provider-token-secret-sentinel" not in exposed


@pytest.mark.parametrize(
    "failure",
    (
        "mode",
        "empty",
        "hardlink",
        "symlink",
        "missing",
        "nonregular",
        "owner",
        "directory-mode",
        "ancestor-mode",
        "fd-replacement",
        "device-drift",
    ),
)
def test_topology_secret_preflight_fails_closed_without_reading_values(
    tmp_path: Path,
    failure: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret_dir = _write_topology_secret_fixture(tmp_path)
    target = secret_dir / workflow.TOPOLOGY_RECONCILIATION_SECRET_NAMES[0]
    sentinel = "secret-value-must-not-leak"
    if failure == "mode":
        target.chmod(0o400)
    elif failure == "empty":
        target.chmod(0o600)
        target.write_text("", encoding="utf-8")
        target.chmod(0o444)
    elif failure == "hardlink":
        os.link(target, tmp_path / "hardlink-fixture")
    elif failure == "symlink":
        target.unlink()
        target.symlink_to(secret_dir / workflow.TOPOLOGY_RECONCILIATION_SECRET_NAMES[1])
    elif failure == "missing":
        target.unlink()
    elif failure == "nonregular":
        target.unlink()
        target.mkdir()
    elif failure == "owner":
        actual_uid = os.getuid()
        monkeypatch.setattr(workflow.os, "getuid", lambda: actual_uid + 1)
    elif failure == "directory-mode":
        secret_dir.chmod(0o755)
    elif failure == "ancestor-mode":
        tmp_path.chmod(0o777)
    elif failure == "fd-replacement":
        alternate = tmp_path / "alternate-secret"
        alternate.write_text("alternate\n", encoding="utf-8")
        alternate.chmod(0o444)
        original_open = workflow.os.open

        def replaced_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
            if path == workflow.TOPOLOGY_RECONCILIATION_SECRET_NAMES[0]:
                return cast(int, original_open(alternate, flags))
            return cast(int, original_open(path, flags, *args, **kwargs))

        monkeypatch.setattr(workflow.os, "open", replaced_open)
    else:
        target_identity = target.stat()
        original_fstat = workflow.os.fstat

        def drifted_fstat(descriptor: int) -> os.stat_result:
            evidence = cast(os.stat_result, original_fstat(descriptor))
            if evidence.st_ino != target_identity.st_ino:
                return evidence
            fields = list(evidence)
            fields[2] += 1
            return os.stat_result(fields)

        monkeypatch.setattr(workflow.os, "fstat", drifted_fstat)

    with pytest.raises(workflow.WorkflowError, match="TOPOLOGY_SECRET_PREFLIGHT_FAILED") as error:
        with workflow.require_topology_reconciliation_secrets(tmp_path):
            pass

    captured = capsys.readouterr()
    exposed = captured.out + captured.err + str(error.value)
    assert sentinel not in exposed


def test_local_topology_reports_missing_and_selected_unhealthy_separately() -> None:
    observations = [item for item in _core_topology_observations() if item.service != "api"]
    for service in workflow.AIRFLOW_SERVICES:
        observations.append(
            workflow.LocalServiceObservation(
                project="datariver-next",
                service=service,
                state="running",
                health="starting" if service == "airflow-scheduler" else "none",
            )
        )

    audit = workflow.build_local_topology_audit(
        state=_topology_state(local_airflow=True),
        environment_values={"NEO4J_PROJECTION_ENABLED": "false"},
        observations=observations,
    )

    assert audit.expected_missing == ("core.api",)
    assert audit.selected_unhealthy == (("airflow.scheduler", "starting"),)
    assert audit.unexpected_running == ()


def test_local_topology_unknown_service_is_counted_without_identifier_leak() -> None:
    sentinel = "future-secret-service-path"
    observations = workflow.parse_local_topology_output(
        "datariver-next",
        f"{sentinel}\trunning\tUp 2 hours\n",
    )
    audit = workflow.build_local_topology_audit(
        state=_topology_state(),
        environment_values={"NEO4J_PROJECTION_ENABLED": "false"},
        observations=(*_core_topology_observations(), *observations),
    )

    assert audit.unexpected_unknown_count == 1
    assert sentinel not in audit.summary()
    assert observations[0].service == "__unknown__"


def test_local_topology_reverse_intent_mismatch_does_not_adopt_env_silently() -> None:
    observations = _core_topology_observations()
    observations.append(
        workflow.LocalServiceObservation(
            project="datariver-next",
            service="neo4j",
            state="running",
            health="healthy",
        )
    )

    audit = workflow.build_local_topology_audit(
        state=_topology_state(local_graph=True),
        environment_values={
            "NEO4J_PROJECTION_ENABLED": "false",
            "NEO4J_URI": "bolt://neo4j:7687",
        },
        observations=observations,
    )

    assert audit.unexpected_running == ()
    assert audit.intent_mismatch == ("graph.neo4j",)


def _captured_workflow_failure(sentinel: str) -> Exception:
    cause = subprocess.CalledProcessError(
        1,
        ("compose-query",),
        output=sentinel,
        stderr=sentinel,
    )
    error = cast(Exception, workflow.WorkflowError("captured child command failure"))
    error.__cause__ = cause
    return error


class _ScriptedOutputRunner:
    def __init__(self, outcomes: list[str | Exception]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[str, ...]] = []
        self.topology_projects: list[str] = []
        self.notes: list[str] = []

    def output(self, arguments: Any) -> str:
        self.calls.append(tuple(os.fspath(argument) for argument in arguments))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def local_topology_output(self, *, project: str) -> str:
        self.topology_projects.append(project)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise workflow.WorkflowError("LOCAL_TOPOLOGY_QUERY_FAILED") from outcome
        return outcome

    def note(self, message: str) -> None:
        self.notes.append(message)


def test_local_topology_queries_only_exact_managed_projects() -> None:
    runner = _ScriptedOutputRunner(["", ""])

    assert workflow.capture_local_topology(runner) == ()
    assert runner.topology_projects == [
        "datariver-next",
        "datariver-local-connectors",
    ]
    assert runner.calls == []


def test_local_topology_query_failure_is_fixed_and_sanitized(
    capsys: pytest.CaptureFixture[str],
) -> None:
    sentinel = "credential=/private/runtime.env"
    runner = _ScriptedOutputRunner([_captured_workflow_failure(sentinel)])

    with pytest.raises(workflow.WorkflowError, match=r"^LOCAL_TOPOLOGY_QUERY_FAILED$") as raised:
        workflow.capture_local_topology(runner)

    captured = capsys.readouterr()
    observed = captured.out + captured.err + str(raised.value)
    assert sentinel not in observed


def test_local_topology_private_capture_never_prints_command_or_payload(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    sentinel = "container-id=0123456789 credential=/private/runtime.env"

    def fake_run(*args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args[0],
            0,
            f"{sentinel}\trunning\tUp 2 hours\n",
            "future_secret=never-print",
        )

    monkeypatch.setattr(workflow.subprocess, "run", fake_run)
    runner = workflow.Runner(root=tmp_path)

    observations = workflow.capture_local_topology(runner)

    assert len(observations) == 2
    assert all(item.service == "__unknown__" for item in observations)
    captured = capsys.readouterr()
    observed = captured.out + captured.err
    assert sentinel not in observed
    assert "future_secret" not in observed
    assert "com.docker.compose.project" not in observed
    assert "datariver-next" not in observed


def test_local_topology_private_capture_failure_is_fixed_and_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    sentinel = "container-id=0123456789 credential=/private/runtime.env"

    def fail_run(*args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(
            1,
            args[0],
            output=sentinel,
            stderr="future_secret=never-print",
        )

    monkeypatch.setattr(workflow.subprocess, "run", fail_run)
    runner = workflow.Runner(root=tmp_path)

    with pytest.raises(workflow.WorkflowError, match=r"^LOCAL_TOPOLOGY_QUERY_FAILED$") as raised:
        workflow.capture_local_topology(runner)

    captured = capsys.readouterr()
    observed = captured.out + captured.err + str(raised.value)
    assert sentinel not in observed
    assert "future_secret" not in observed
    assert "com.docker.compose.project" not in observed
    assert "datariver-next" not in observed


def test_local_topology_private_capture_timeout_is_fixed_sanitized_and_not_retried(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    sentinel = "container-id=0123456789 credential=/private/runtime.env"
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def timeout_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((args, kwargs))
        raise subprocess.TimeoutExpired(
            args[0],
            kwargs["timeout"],
            output=sentinel,
            stderr="future_secret=never-print",
        )

    monkeypatch.setattr(workflow.subprocess, "run", timeout_run)
    runner = workflow.Runner(root=tmp_path)

    with pytest.raises(workflow.WorkflowError, match=r"^LOCAL_TOPOLOGY_QUERY_FAILED$") as raised:
        workflow.capture_local_topology(runner)

    assert len(calls) == 1
    assert calls[0][1]["timeout"] == 20
    captured = capsys.readouterr()
    observed = captured.out + captured.err + str(raised.value)
    assert sentinel not in observed
    assert "future_secret" not in observed
    assert "com.docker.compose.project" not in observed
    assert "datariver-next" not in observed


def test_local_topology_malformed_evidence_never_echoes_raw_value() -> None:
    sentinel = "future_secret=/private/path"

    with pytest.raises(workflow.WorkflowError, match="LOCAL_TOPOLOGY_EVIDENCE_INVALID") as raised:
        workflow.parse_local_topology_output("datariver-next", sentinel)

    assert sentinel not in str(raised.value)


def test_running_services_preserves_first_success_behavior(tmp_path: Path) -> None:
    update = _load_update_module()
    runner = _ScriptedOutputRunner(["api\nweb\n"])

    result = update._running_services(
        runner,
        env_file=tmp_path / ".env.mac-development",
        files=(tmp_path / "compose.yaml",),
    )

    assert result == ("api", "web")
    assert len(runner.calls) == 1
    assert runner.calls[0][-4:] == ("ps", "--services", "--filter", "status=running")
    assert runner.notes == []


def test_running_services_recovers_once_after_a_successful_daemon_probe(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    update = _load_update_module()
    runner = _ScriptedOutputRunner(
        [
            _captured_workflow_failure("first-query-sensitive-sentinel"),
            "29.4.2",
            "api\nweb\n",
        ]
    )

    result = update._running_services(
        runner,
        env_file=tmp_path / ".env.mac-development",
        files=(tmp_path / "compose.yaml",),
    )

    assert result == ("api", "web")
    assert len(runner.calls) == 3
    assert runner.calls[0] == runner.calls[2]
    assert runner.calls[1] == (
        "docker",
        "version",
        "--format",
        "{{.Server.Version}}",
    )
    assert len(runner.notes) == 1
    captured = capsys.readouterr()
    observed = captured.out + captured.err + "\n".join(runner.notes)
    assert "first-query-sensitive-sentinel" not in observed
    assert "29.4.2" not in observed


def test_running_services_stops_safely_when_daemon_probe_fails(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    update = _load_update_module()
    sentinel = "credential=/private/operator.env"
    runner = _ScriptedOutputRunner(
        [
            _captured_workflow_failure(sentinel),
            _captured_workflow_failure(sentinel),
        ]
    )

    with pytest.raises(
        workflow.WorkflowError,
        match="DOCKER_DAEMON_UNAVAILABLE",
    ) as raised:
        update._running_services(
            runner,
            env_file=tmp_path / ".env.mac-development",
            files=(tmp_path / "compose.yaml",),
        )

    assert len(runner.calls) == 2
    assert runner.calls[0][-4:] == ("ps", "--services", "--filter", "status=running")
    assert runner.calls[1][:3] == ("docker", "version", "--format")
    assert runner.notes == []
    captured = capsys.readouterr()
    observed = captured.out + captured.err + str(raised.value)
    assert sentinel not in observed


def test_running_services_stops_after_one_sanitized_query_retry(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    update = _load_update_module()
    sentinel = "future_secret=never-log-this"
    runner = _ScriptedOutputRunner(
        [
            _captured_workflow_failure(sentinel),
            "29.4.2",
            _captured_workflow_failure(sentinel),
        ]
    )

    with pytest.raises(
        workflow.WorkflowError,
        match="COMPOSE_RUNNING_SERVICES_QUERY_FAILED",
    ) as raised:
        update._running_services(
            runner,
            env_file=tmp_path / ".env.mac-development",
            files=(tmp_path / "compose.yaml",),
        )

    assert len(runner.calls) == 3
    assert runner.calls[0] == runner.calls[2]
    assert runner.calls[1][:3] == ("docker", "version", "--format")
    assert len(runner.notes) == 1
    captured = capsys.readouterr()
    observed = captured.out + captured.err + str(raised.value) + "\n".join(runner.notes)
    assert sentinel not in observed
    assert "29.4.2" not in observed


def test_update_remounts_a_new_postgres_role_secret_before_reconciliation() -> None:
    update = _load_update_module()
    assert update._requires_postgres_secret_remount(("KNOWLEDGE_PROPOSAL_DATABASE_SECRET_REF",))

    source = UPDATE_MODULE_PATH.read_text(encoding="utf-8")
    migration_block = source.split("if plan.requires_migration:", maxsplit=1)[1].split(
        "if reapply_local_identity:", maxsplit=1
    )[0]
    remount = migration_block.index("새 PostgreSQL role secret mount")
    reconcile = migration_block.index("Migration 선행 PostgreSQL 역할 계약")
    assert remount < reconcile


def test_update_reconciles_runtime_roles_before_and_after_migration() -> None:
    source = UPDATE_MODULE_PATH.read_text(encoding="utf-8")
    migration_block = source.split("if plan.requires_migration:", maxsplit=1)[1].split(
        "if reapply_local_identity:", maxsplit=1
    )[0]

    before = migration_block.index("Migration 선행 PostgreSQL 역할 계약")
    migrate = migration_block.index('runner.note("Alembic migration을 적용합니다.")')
    after = migration_block.index("Migration 후 PostgreSQL 역할 grant")

    assert before < migrate < after
    assert migration_block.count("_reconcile_postgres(runner, env_file=env_file)") == 2


def test_update_recovers_a_stopped_keycloak_before_reconfiguration() -> None:
    source = UPDATE_MODULE_PATH.read_text(encoding="utf-8")
    recovery = source.index('if plan.configure_keycloak and "keycloak" not in running:')
    start = source.index('"up",', recovery)
    configure = source.index("if plan.configure_keycloak:", recovery)

    assert recovery < start < configure
    assert '"--wait",' in source[start:configure]
    assert '"keycloak",' in source[start:configure]


@pytest.mark.parametrize(
    "load_workflow",
    (_load_fresh_setup_module, _load_update_module),
)
def test_workflow_reconciles_local_reranker_lifecycle(
    load_workflow: Any,
    tmp_path: Path,
) -> None:
    module = load_workflow()
    calls: list[tuple[object, ...]] = []

    class FakeRunner:
        def note(self, _message: str) -> None:
            return None

        def run(self, arguments: tuple[object, ...]) -> None:
            calls.append(arguments)

    env_file = tmp_path / ".env.mac-development"
    env_file.write_text(
        "LOCAL_LLAMA_CPP_RERANKER_ENABLED=true\n"
        "LOCAL_LLAMA_CPP_RERANKER_MODEL=operator-selected/reranker:q4\n",
        encoding="utf-8",
    )

    module._reconcile_local_reranker(
        FakeRunner(),
        env_file=env_file,
        profile="mac-development",
    )

    assert calls[-1][-3:] == (
        "start",
        "--model",
        "operator-selected/reranker:q4",
    )

    env_file.write_text(
        "LOCAL_LLAMA_CPP_RERANKER_ENABLED=false\n",
        encoding="utf-8",
    )
    module._reconcile_local_reranker(
        FakeRunner(),
        env_file=env_file,
        profile="mac-development",
    )
    assert calls[-1][-1] == "stop"

    env_file.write_text(
        "LOCAL_LLAMA_CPP_RERANKER_ENABLED=true\n"
        "LOCAL_LLAMA_CPP_RERANKER_MODEL=operator-selected/reranker:q4\n",
        encoding="utf-8",
    )
    module._reconcile_local_reranker(
        FakeRunner(),
        env_file=env_file,
        profile="portable-development",
    )
    assert calls[-1][-1] == "stop"


def test_update_topology_drift_stops_before_lock_reranker_or_state_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    update = _load_update_module()
    env_file = tmp_path / ".env.portable-development"
    env_file.write_text("NEO4J_PROJECTION_ENABLED=false\n", encoding="utf-8")
    state = _topology_state(
        env_file=os.fspath(env_file),
        environment_key_hashes=workflow.environment_key_hashes(
            {"NEO4J_PROJECTION_ENABLED": "false"}
        ),
    )
    events: list[str] = []

    class FakeRunner:
        def note(self, _message: str) -> None:
            return None

    monkeypatch.setattr(
        update,
        "parse_args",
        lambda: SimpleNamespace(
            profile="portable-development",
            env_file=env_file,
            release_dir=None,
            git_pull=False,
            reload_release=False,
            refresh_bootstrap=False,
            skip_catalog_sync=True,
            assume_yes=True,
        ),
    )
    monkeypatch.setattr(update, "Runner", FakeRunner)
    monkeypatch.setattr(update, "require_command", lambda _command: None)
    monkeypatch.setattr(update, "require_clean_worktree", lambda _runner: None)
    monkeypatch.setattr(update, "state_path", lambda _root, _profile: tmp_path / "state.json")
    monkeypatch.setattr(update, "load_applied_state", lambda _path: state)
    monkeypatch.setattr(update, "current_commit", lambda _runner: "a" * 40)
    monkeypatch.setattr(update, "_git_paths", lambda _runner, _old, _new: ())
    monkeypatch.setattr(update, "_running_services", lambda *_args, **_kwargs: ("api", "web"))

    def compose(_runner: object, **kwargs: object) -> None:
        trailing = cast(tuple[str, ...], kwargs["trailing"])
        events.append("config" if trailing == ("config", "--quiet") else "docker-mutation")

    def drift(*_args: object, **_kwargs: object) -> None:
        events.append("topology-audit")
        raise workflow.WorkflowError("LOCAL_TOPOLOGY_DRIFT")

    @contextmanager
    def held_lock(_root: Path) -> Iterator[object]:
        events.append("lock")
        yield object()

    monkeypatch.setattr(update, "_compose", compose)
    monkeypatch.setattr(update, "enforce_local_topology", drift)
    monkeypatch.setattr(update, "exclusive_docker_workflow_lock", held_lock)
    monkeypatch.setattr(
        update,
        "_reconcile_local_reranker",
        lambda *_args, **_kwargs: events.append("reranker"),
    )
    monkeypatch.setattr(
        update,
        "write_applied_state",
        lambda *_args, **_kwargs: events.append("state-write"),
    )

    assert update.main() == 2
    assert events == ["config", "topology-audit"]
    assert capsys.readouterr().err.splitlines() == ["ERROR: LOCAL_TOPOLOGY_DRIFT"]


def test_update_topology_audit_precedes_confirmation_and_capacity_mutation() -> None:
    source = UPDATE_MODULE_PATH.read_text(encoding="utf-8")
    config = source.index('trailing=("config", "--quiet")')
    running = source.index("running = _running_services", config)
    audit = source.index("enforce_local_topology(", running)
    plan = source.index("_print_plan(", audit)
    confirm = source.index("if not args.assume_yes", plan)
    capacity = source.index("exclusive_docker_workflow_lock", confirm)
    reranker = source.index("_reconcile_local_reranker", capacity)

    assert config < running < audit < plan < confirm < capacity < reranker


def test_update_main_recreates_env_consumer_and_persists_state_only_after_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    env_file = tmp_path / ".env.portable-development"
    env_file.write_text(
        "LOCAL_OLLAMA_CHAT_ENABLED=true\nLOCAL_OLLAMA_CHAT_MODEL=new-installed-model\n",
        encoding="utf-8",
    )
    state = workflow.AppliedState(
        profile="portable-development",
        applied_commit="a" * 40,
        runtime_commit="a" * 40,
        env_file=os.fspath(env_file),
        deployment_mode="build",
        release_dir=None,
        local_airflow=False,
        local_datahub=False,
        local_redis=False,
        local_storage=False,
        local_gateway=False,
        local_graph=False,
        environment_key_hashes=workflow.environment_key_hashes(
            {
                "LOCAL_OLLAMA_CHAT_ENABLED": "true",
                "LOCAL_OLLAMA_CHAT_MODEL": "old-installed-model",
            }
        ),
    )
    compose_calls: list[tuple[str, ...]] = []
    written: list[Any] = []

    class FakeRunner:
        def note(self, _message: str) -> None:
            return None

    monkeypatch.setattr(
        update,
        "parse_args",
        lambda: SimpleNamespace(
            profile="portable-development",
            env_file=env_file,
            release_dir=None,
            git_pull=False,
            reload_release=False,
            refresh_bootstrap=False,
            skip_catalog_sync=True,
            assume_yes=True,
        ),
    )
    monkeypatch.setattr(update, "Runner", FakeRunner)
    monkeypatch.setattr(update, "require_command", lambda _command: None)
    monkeypatch.setattr(update, "require_clean_worktree", lambda _runner: None)
    monkeypatch.setattr(update, "state_path", lambda _root, _profile: tmp_path / "state.json")
    monkeypatch.setattr(update, "load_applied_state", lambda _path: state)
    monkeypatch.setattr(update, "current_commit", lambda _runner: "a" * 40)
    monkeypatch.setattr(update, "_git_paths", lambda _runner, _old, _new: ())
    monkeypatch.setattr(update, "_running_services", lambda *_args, **_kwargs: ("api", "web"))
    monkeypatch.setattr(
        update,
        "_compose",
        lambda _runner, **kwargs: compose_calls.append(tuple(kwargs["trailing"])),
    )
    monkeypatch.setattr(update, "_health_check", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(update, "_probe_datahub", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(update, "_reconcile_local_reranker", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        update,
        "write_applied_state",
        lambda _path, next_state: written.append(next_state),
    )

    assert update.main() == 0
    assert ("build", "api") in compose_calls
    recreate = next(call for call in compose_calls if call[:2] == ("up", "-d"))
    assert "--force-recreate" in recreate
    assert recreate[-1] == "api"
    assert written[-1].environment_key_hashes == workflow.environment_key_hashes(
        workflow.read_env_values(env_file)
    )

    written.clear()

    def fail_recreate(_runner: object, **kwargs: object) -> None:
        raw_trailing = kwargs["trailing"]
        assert isinstance(raw_trailing, tuple)
        trailing = raw_trailing
        compose_calls.append(trailing)
        if trailing[:2] == ("up", "-d"):
            raise workflow.WorkflowError("simulated recreate failure")

    monkeypatch.setattr(update, "_compose", fail_recreate)
    assert update.main() == 2
    assert written == []


def test_update_capacity_lock_spans_preflight_build_mutation_and_state_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    env_file = tmp_path / ".env.portable-development"
    env_file.write_text(
        "LOCAL_OLLAMA_CHAT_ENABLED=true\nLOCAL_OLLAMA_CHAT_MODEL=new-model\n",
        encoding="utf-8",
    )
    state = workflow.AppliedState(
        profile="portable-development",
        applied_commit="a" * 40,
        runtime_commit="a" * 40,
        env_file=os.fspath(env_file),
        deployment_mode="build",
        release_dir=None,
        local_airflow=False,
        local_datahub=False,
        local_redis=False,
        local_storage=False,
        local_gateway=False,
        local_graph=False,
        environment_key_hashes=workflow.environment_key_hashes(
            {
                "LOCAL_OLLAMA_CHAT_ENABLED": "true",
                "LOCAL_OLLAMA_CHAT_MODEL": "old-model",
            }
        ),
    )
    events: list[str] = []
    lock_token = object()

    class FakeRunner:
        def note(self, _message: str) -> None:
            return None

    @contextmanager
    def held_lock(_root: Path) -> Iterator[object]:
        events.append("lock-enter")
        try:
            yield lock_token
        finally:
            events.append("lock-exit")

    def preflight(*_args: object, **kwargs: object) -> str:
        assert kwargs["lock"] is lock_token
        selected = kwargs["selected_build_services"]
        assert isinstance(selected, tuple)
        assert "api" in selected
        events.append("preflight")
        return "desktop-linux"

    def idle(builder: object, lock: object) -> None:
        assert builder == "desktop-linux"
        assert lock is lock_token
        events.append("active-build-check")

    def compose(_runner: object, **kwargs: object) -> None:
        trailing = cast(tuple[str, ...], kwargs["trailing"])
        if trailing == ("config", "--quiet"):
            events.append("config")
        elif trailing[0] == "build":
            events.append("build")
        elif trailing[:2] == ("up", "-d"):
            events.append("recreate")

    monkeypatch.setattr(
        update,
        "parse_args",
        lambda: SimpleNamespace(
            profile="portable-development",
            env_file=env_file,
            release_dir=None,
            git_pull=False,
            reload_release=False,
            refresh_bootstrap=False,
            skip_catalog_sync=True,
            assume_yes=True,
        ),
    )
    monkeypatch.setattr(update, "Runner", FakeRunner)
    monkeypatch.setattr(update, "require_command", lambda _command: None)
    monkeypatch.setattr(update, "require_clean_worktree", lambda _runner: None)
    monkeypatch.setattr(update, "state_path", lambda _root, _profile: tmp_path / "state.json")
    monkeypatch.setattr(update, "load_applied_state", lambda _path: state)
    monkeypatch.setattr(update, "current_commit", lambda _runner: "a" * 40)
    monkeypatch.setattr(update, "_git_paths", lambda _runner, _old, _new: ())
    monkeypatch.setattr(update, "_running_services", lambda *_args, **_kwargs: ("api", "web"))
    monkeypatch.setattr(update, "_compose", compose)
    monkeypatch.setattr(update, "exclusive_docker_workflow_lock", held_lock)
    monkeypatch.setattr(update, "_preflight_build_capacity", preflight)
    monkeypatch.setattr(update, "_require_idle_builder", idle)
    monkeypatch.setattr(
        update,
        "_reconcile_local_reranker",
        lambda *_args, **_kwargs: events.append("reranker"),
    )
    monkeypatch.setattr(update, "_health_check", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(update, "_probe_datahub", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        update,
        "write_applied_state",
        lambda *_args, **_kwargs: events.append("state-write"),
    )

    assert update.main() == 0
    assert events.index("config") < events.index("lock-enter")
    assert events.index("lock-enter") < events.index("preflight")
    assert events.index("preflight") < events.index("reranker")
    assert events.index("reranker") < events.index("active-build-check")
    assert events.index("active-build-check") < events.index("build")
    assert events.index("build") < events.index("recreate")
    assert events.index("recreate") < events.index("state-write")
    assert events.index("state-write") < events.index("lock-exit")


def test_update_capacity_failure_releases_lock_before_any_docker_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    update = _load_update_module()
    env_file = tmp_path / ".env.portable-development"
    env_file.write_text("LOCAL_OLLAMA_CHAT_MODEL=new-model\n", encoding="utf-8")
    state = workflow.AppliedState(
        profile="portable-development",
        applied_commit="a" * 40,
        runtime_commit="a" * 40,
        env_file=os.fspath(env_file),
        deployment_mode="build",
        release_dir=None,
        local_airflow=False,
        local_datahub=False,
        local_redis=False,
        local_storage=False,
        local_gateway=False,
        local_graph=False,
        environment_key_hashes=workflow.environment_key_hashes(
            {"LOCAL_OLLAMA_CHAT_MODEL": "old-model"}
        ),
    )
    events: list[str] = []

    class FakeRunner:
        def note(self, _message: str) -> None:
            return None

    @contextmanager
    def held_lock(_root: Path) -> Iterator[object]:
        events.append("lock-enter")
        try:
            yield object()
        finally:
            events.append("lock-exit")

    def compose(_runner: object, **kwargs: object) -> None:
        trailing = cast(tuple[str, ...], kwargs["trailing"])
        events.append("config" if trailing == ("config", "--quiet") else "mutation")

    monkeypatch.setattr(
        update,
        "parse_args",
        lambda: SimpleNamespace(
            profile="portable-development",
            env_file=env_file,
            release_dir=None,
            git_pull=False,
            reload_release=False,
            refresh_bootstrap=False,
            skip_catalog_sync=True,
            assume_yes=True,
        ),
    )
    monkeypatch.setattr(update, "Runner", FakeRunner)
    monkeypatch.setattr(update, "require_command", lambda _command: None)
    monkeypatch.setattr(update, "require_clean_worktree", lambda _runner: None)
    monkeypatch.setattr(update, "state_path", lambda _root, _profile: tmp_path / "state.json")
    monkeypatch.setattr(update, "load_applied_state", lambda _path: state)
    monkeypatch.setattr(update, "current_commit", lambda _runner: "a" * 40)
    monkeypatch.setattr(update, "_git_paths", lambda _runner, _old, _new: ())
    monkeypatch.setattr(update, "_running_services", lambda *_args, **_kwargs: ("api", "web"))
    monkeypatch.setattr(update, "_compose", compose)
    monkeypatch.setattr(update, "exclusive_docker_workflow_lock", held_lock)
    safe_failure = (
        "classification=DOCKER_BUILD_CACHE_ACTION_FAILED_POST_MEASUREMENT_OK "
        "builder=desktop-linux action_succeeded=false filesystem_total_before=1024000000 "
        "cache_before=140000000 reclaimable_before=140000000 free_before=204800000 "
        "action_attempts=1 retry_count=0 cache_probe_ok=true filesystem_probe_ok=true "
        "cache_after=20000000 reclaimable_after=20000000 cache_delta_signed=-120000000 "
        "filesystem_total_after=1024000000 free_after=358400000 "
        "free_delta_signed=153600000"
    )
    monkeypatch.setattr(
        update,
        "_preflight_build_capacity",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(update.DockerCapacityError(safe_failure)),
    )
    monkeypatch.setattr(
        update,
        "_reconcile_local_reranker",
        lambda *_args, **_kwargs: events.append("reranker"),
    )
    monkeypatch.setattr(
        update,
        "write_applied_state",
        lambda *_args, **_kwargs: events.append("state-write"),
    )

    assert update.main() == 2
    assert events == ["config", "lock-enter", "lock-exit"]
    assert capsys.readouterr().err.splitlines() == [f"ERROR: {safe_failure}"]

    def contended_lock(_root: Path) -> object:
        events.append("lock-contended")
        raise update.DockerCapacityError("DOCKER_WORKFLOW_LOCK_UNAVAILABLE")

    events.clear()
    monkeypatch.setattr(update, "exclusive_docker_workflow_lock", contended_lock)
    monkeypatch.setattr(
        update,
        "_preflight_build_capacity",
        lambda *_args, **_kwargs: events.append("unexpected-preflight"),
    )

    assert update.main() == 2
    assert events == ["config", "lock-contended"]


def test_update_main_with_unchanged_environment_does_not_recreate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    env_file = tmp_path / ".env.portable-development"
    env_file.write_text("LOCAL_OLLAMA_CHAT_ENABLED=false\n", encoding="utf-8")
    hashes = workflow.environment_key_hashes(workflow.read_env_values(env_file))
    state = workflow.AppliedState(
        profile="portable-development",
        applied_commit="a" * 40,
        runtime_commit="a" * 40,
        env_file=os.fspath(env_file),
        deployment_mode="build",
        release_dir=None,
        local_airflow=False,
        local_datahub=False,
        local_redis=False,
        local_storage=False,
        local_gateway=False,
        local_graph=False,
        environment_key_hashes=hashes,
    )
    compose_calls: list[tuple[str, ...]] = []

    class FakeRunner:
        def note(self, _message: str) -> None:
            return None

    monkeypatch.setattr(
        update,
        "parse_args",
        lambda: SimpleNamespace(
            profile="portable-development",
            env_file=env_file,
            release_dir=None,
            git_pull=False,
            reload_release=False,
            refresh_bootstrap=False,
            skip_catalog_sync=True,
            assume_yes=True,
        ),
    )
    monkeypatch.setattr(update, "Runner", FakeRunner)
    monkeypatch.setattr(update, "require_command", lambda _command: None)
    monkeypatch.setattr(update, "require_clean_worktree", lambda _runner: None)
    monkeypatch.setattr(update, "state_path", lambda _root, _profile: tmp_path / "state.json")
    monkeypatch.setattr(update, "load_applied_state", lambda _path: state)
    monkeypatch.setattr(update, "current_commit", lambda _runner: "a" * 40)
    monkeypatch.setattr(update, "_git_paths", lambda _runner, _old, _new: ())
    monkeypatch.setattr(update, "_running_services", lambda *_args, **_kwargs: ("api", "web"))
    monkeypatch.setattr(
        update,
        "_compose",
        lambda _runner, **kwargs: compose_calls.append(tuple(kwargs["trailing"])),
    )
    monkeypatch.setattr(
        update,
        "write_applied_state",
        lambda _path, _next_state: None,
    )
    monkeypatch.setattr(update, "_reconcile_local_reranker", lambda *_args, **_kwargs: None)

    assert update.main() == 0
    assert compose_calls == [("config", "--quiet")]


def test_update_main_recreates_only_changed_local_connector(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    env_file = tmp_path / ".env.portable-development"
    env_file.write_text("MINIO_API_PORT=19000\n", encoding="utf-8")
    state = workflow.AppliedState(
        profile="portable-development",
        applied_commit="a" * 40,
        runtime_commit="a" * 40,
        env_file=os.fspath(env_file),
        deployment_mode="build",
        release_dir=None,
        local_airflow=False,
        local_datahub=False,
        local_redis=True,
        local_storage=True,
        local_gateway=False,
        local_graph=False,
        environment_key_hashes=workflow.environment_key_hashes({"MINIO_API_PORT": "9000"}),
    )
    compose_calls: list[tuple[str, ...]] = []

    class FakeRunner:
        def note(self, _message: str) -> None:
            return None

    monkeypatch.setattr(
        update,
        "parse_args",
        lambda: SimpleNamespace(
            profile="portable-development",
            env_file=env_file,
            release_dir=None,
            git_pull=False,
            reload_release=False,
            refresh_bootstrap=False,
            skip_catalog_sync=True,
            assume_yes=True,
        ),
    )
    monkeypatch.setattr(update, "Runner", FakeRunner)
    monkeypatch.setattr(update, "require_command", lambda _command: None)
    monkeypatch.setattr(update, "require_clean_worktree", lambda _runner: None)
    monkeypatch.setattr(update, "state_path", lambda _root, _profile: tmp_path / "state.json")
    monkeypatch.setattr(update, "load_applied_state", lambda _path: state)
    monkeypatch.setattr(update, "current_commit", lambda _runner: "a" * 40)
    monkeypatch.setattr(update, "_git_paths", lambda _runner, _old, _new: ())
    monkeypatch.setattr(update, "_running_services", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(
        update,
        "_compose",
        lambda _runner, **kwargs: compose_calls.append(tuple(kwargs["trailing"])),
    )
    monkeypatch.setattr(update, "_health_check", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(update, "_probe_datahub", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(update, "_reconcile_local_reranker", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(update, "write_applied_state", lambda *_args: None)

    assert update.main() == 0
    recreate = next(call for call in compose_calls if call[:2] == ("up", "-d"))
    assert "--force-recreate" in recreate
    assert recreate[-1] == "minio"
    assert "redis-cache" not in recreate
    assert "redis-delivery" not in recreate
    assert "api" not in recreate


def test_update_main_initializes_knowledge_storage_before_proposal_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    env_file = tmp_path / ".env.portable-development"
    env_file.write_text(
        "KNOWLEDGE_STUDIO_PROPOSAL_WORKER_ENABLED=true\n",
        encoding="utf-8",
    )
    state = workflow.AppliedState(
        profile="portable-development",
        applied_commit="a" * 40,
        runtime_commit="a" * 40,
        env_file=os.fspath(env_file),
        deployment_mode="build",
        release_dir=None,
        local_airflow=False,
        local_datahub=False,
        local_redis=False,
        local_storage=True,
        local_gateway=False,
        local_graph=False,
        environment_key_hashes=workflow.environment_key_hashes(
            {"KNOWLEDGE_STUDIO_PROPOSAL_WORKER_ENABLED": "false"}
        ),
    )
    compose_calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    written: list[Any] = []

    class FakeRunner:
        def note(self, _message: str) -> None:
            return None

    monkeypatch.setattr(
        update,
        "parse_args",
        lambda: SimpleNamespace(
            profile="portable-development",
            env_file=env_file,
            release_dir=None,
            git_pull=False,
            reload_release=False,
            refresh_bootstrap=False,
            skip_catalog_sync=True,
            assume_yes=True,
        ),
    )
    monkeypatch.setattr(update, "Runner", FakeRunner)
    monkeypatch.setattr(update, "require_command", lambda _command: None)
    monkeypatch.setattr(update, "require_clean_worktree", lambda _runner: None)
    monkeypatch.setattr(update, "state_path", lambda _root, _profile: tmp_path / "state.json")
    monkeypatch.setattr(update, "load_applied_state", lambda _path: state)
    monkeypatch.setattr(update, "current_commit", lambda _runner: "a" * 40)
    monkeypatch.setattr(update, "_git_paths", lambda _runner, _old, _new: ())
    monkeypatch.setattr(update, "_running_services", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(
        update,
        "_compose",
        lambda _runner, **kwargs: compose_calls.append(
            (tuple(kwargs.get("profiles", ())), tuple(kwargs["trailing"]))
        ),
    )
    monkeypatch.setattr(update, "_health_check", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(update, "_probe_datahub", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(update, "_reconcile_local_reranker", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        update,
        "write_applied_state",
        lambda _path, next_state: written.append(next_state),
    )

    assert update.main() == 0
    initializer_index = next(
        index
        for index, (_profiles, trailing) in enumerate(compose_calls)
        if trailing[-1:] == ("minio-knowledge-identity-init",)
    )
    worker_index = next(
        index
        for index, (_profiles, trailing) in enumerate(compose_calls)
        if trailing[:2] == ("up", "-d") and trailing[-1:] == ("knowledge-tbox-proposal-worker",)
    )
    initializer_profiles, initializer = compose_calls[initializer_index]
    assert initializer_profiles == ("object-storage",)
    assert initializer == ("run", "--rm", "minio-knowledge-identity-init")
    assert "--no-deps" not in initializer
    assert initializer_index < worker_index
    assert len(written) == 1

    compose_calls.clear()
    written.clear()

    def fail_initializer(_runner: object, **kwargs: object) -> None:
        raw_profiles = kwargs.get("profiles", ())
        raw_trailing = kwargs["trailing"]
        assert isinstance(raw_profiles, tuple)
        assert isinstance(raw_trailing, tuple)
        profiles = raw_profiles
        trailing = raw_trailing
        compose_calls.append((profiles, trailing))
        if trailing[-1:] == ("minio-knowledge-identity-init",):
            raise workflow.WorkflowError("simulated knowledge storage identity failure")

    monkeypatch.setattr(update, "_compose", fail_initializer)
    assert update.main() == 2
    assert not any(
        trailing[:2] == ("up", "-d") and trailing[-1:] == ("knowledge-tbox-proposal-worker",)
        for _profiles, trailing in compose_calls
    )
    assert written == []


@pytest.mark.parametrize(
    ("local_storage", "proposal_enabled"),
    ((False, True), (True, False)),
)
def test_update_main_skips_knowledge_storage_initializer_outside_local_enabled_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    local_storage: bool,
    proposal_enabled: bool,
) -> None:
    update = _load_update_module()
    env_file = tmp_path / ".env.portable-development"
    env_file.write_text(
        f"KNOWLEDGE_STUDIO_PROPOSAL_WORKER_ENABLED={'true' if proposal_enabled else 'false'}\n",
        encoding="utf-8",
    )
    state = workflow.AppliedState(
        profile="portable-development",
        applied_commit="a" * 40,
        runtime_commit="a" * 40,
        env_file=os.fspath(env_file),
        deployment_mode="build",
        release_dir=None,
        local_airflow=False,
        local_datahub=False,
        local_redis=False,
        local_storage=local_storage,
        local_gateway=False,
        local_graph=False,
        environment_key_hashes=workflow.environment_key_hashes(
            {"KNOWLEDGE_STUDIO_PROPOSAL_WORKER_ENABLED": "true"}
        ),
    )
    compose_calls: list[tuple[str, ...]] = []

    class FakeRunner:
        def note(self, _message: str) -> None:
            return None

    monkeypatch.setattr(
        update,
        "parse_args",
        lambda: SimpleNamespace(
            profile="portable-development",
            env_file=env_file,
            release_dir=None,
            git_pull=False,
            reload_release=False,
            refresh_bootstrap=False,
            skip_catalog_sync=True,
            assume_yes=True,
        ),
    )
    monkeypatch.setattr(update, "Runner", FakeRunner)
    monkeypatch.setattr(update, "require_command", lambda _command: None)
    monkeypatch.setattr(update, "require_clean_worktree", lambda _runner: None)
    monkeypatch.setattr(update, "state_path", lambda _root, _profile: tmp_path / "state.json")
    monkeypatch.setattr(update, "load_applied_state", lambda _path: state)
    monkeypatch.setattr(update, "current_commit", lambda _runner: "a" * 40)
    monkeypatch.setattr(update, "_git_paths", lambda _runner, _old, _new: ())
    monkeypatch.setattr(update, "_running_services", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(
        update,
        "_compose",
        lambda _runner, **kwargs: compose_calls.append(tuple(kwargs["trailing"])),
    )
    monkeypatch.setattr(update, "_health_check", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(update, "_probe_datahub", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(update, "_reconcile_local_reranker", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(update, "write_applied_state", lambda *_args: None)

    assert update.main() == 0
    assert not any(
        trailing[-1:] == ("minio-knowledge-identity-init",) for trailing in compose_calls
    )


def test_merge_no_proxy_adds_hosts_once_and_preserves_existing_order() -> None:
    assert (
        workflow.merge_no_proxy(
            "localhost,127.0.0.1,datahub.internal",
            ("datahub.internal", "minio.internal"),
        )
        == "localhost,127.0.0.1,datahub.internal,minio.internal"
    )


def test_classify_changes_limits_restarts_to_affected_services() -> None:
    frontend = workflow.classify_changes(("frontend/src/App.tsx",))
    assert frontend.services == ("web",)
    assert frontend.requires_migration is False

    backend = workflow.classify_changes(
        (
            "backend/src/datariver/config.py",
            "backend/alembic/versions/0056_example.py",
        )
    )
    assert backend.requires_migration is True
    assert set(backend.services) == {
        "api",
        "catalog-export-worker",
        "governance-apply-worker",
        "governance-document-worker",
        "knowledge-source-worker",
        "knowledge-tbox-proposal-worker",
        "outbox-relay",
        "quality-worker",
        "retention-archive-worker",
        "retention-scheduler",
        "upload-validation-worker",
        "upload-worker",
    }

    identity = workflow.classify_changes(("infra/keycloak/Dockerfile",))
    assert set(identity.services) == {"api", "keycloak"}
    assert identity.configure_keycloak is True


def test_classify_unknown_root_change_fails_safe_to_all_runtime_services() -> None:
    result = workflow.classify_changes(("pyproject.toml",))

    assert result.requires_migration is True
    assert set(result.services) == set(workflow.RUNTIME_SERVICES)


def test_release_layout_requires_checksum_relative_to_platform_directory(
    tmp_path: Path,
) -> None:
    release = tmp_path / "datariver-deadbeef0000"
    platform = release / "amd64"
    platform.mkdir(parents=True)
    (platform / "datariver-core-amd64.tar").write_bytes(b"archive")
    (platform / "datariver-core-amd64.tar.sha256").write_text(
        "not-a-real-hash  datariver-core-amd64.tar\n",
        encoding="utf-8",
    )
    (platform / "offline-core.compose.yaml").write_text("services: {}\n", encoding="utf-8")
    (release / "source-commit.txt").write_text("a" * 40 + "\n", encoding="utf-8")

    layout = workflow.release_layout(release, architecture="amd64")

    assert layout.checksum_cwd == platform
    assert layout.checksum_file.name == "datariver-core-amd64.tar.sha256"
    assert layout.core_archive == platform / "datariver-core-amd64.tar"


def test_optional_release_compose_is_explicit_and_can_be_required(tmp_path: Path) -> None:
    release = tmp_path / "datariver-deadbeef0000"
    platform = release / "amd64"
    platform.mkdir(parents=True)
    (platform / "datariver-core-amd64.tar").write_bytes(b"archive")
    (platform / "datariver-core-amd64.tar.sha256").write_text(
        "not-a-real-hash  datariver-core-amd64.tar\n",
        encoding="utf-8",
    )
    (platform / "offline-core.compose.yaml").write_text("services: {}\n", encoding="utf-8")
    (release / "source-commit.txt").write_text("a" * 40 + "\n", encoding="utf-8")
    layout = workflow.release_layout(release, architecture="amd64")

    assert (
        workflow.release_optional_compose(
            layout,
            "offline-airflow.compose.yaml",
        )
        is None
    )
    with pytest.raises(workflow.WorkflowError):
        workflow.release_optional_compose(
            layout,
            "offline-airflow.compose.yaml",
            required=True,
        )


def test_write_and_load_state_round_trip(tmp_path: Path) -> None:
    state_path = tmp_path / "runtime" / "operator-workflow" / "wsl-preparation.json"
    state = workflow.AppliedState(
        profile="wsl-preparation",
        applied_commit="b" * 40,
        runtime_commit="a" * 40,
        env_file=".env.wsl-preparation",
        deployment_mode="offline",
        release_dir="/transfer/datariver-deadbeef0000",
        local_airflow=False,
        local_datahub=False,
        local_redis=True,
        local_storage=False,
        local_gateway=False,
        local_graph=False,
        environment_key_hashes={"DATAHUB_BASE_URL": "d" * 64},
    )

    workflow.write_applied_state(state_path, state)

    assert workflow.load_applied_state(state_path) == state
    assert json.loads(state_path.read_text(encoding="utf-8"))["applied_commit"] == "b" * 40
    assert json.loads(state_path.read_text(encoding="utf-8"))["runtime_commit"] == "a" * 40
    assert json.loads(state_path.read_text(encoding="utf-8"))["environment_key_hashes"] == {
        "DATAHUB_BASE_URL": "d" * 64
    }


def test_load_state_accepts_legacy_state_without_environment_fingerprints(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "legacy-state.json"
    state_path.write_text(
        json.dumps(
            {
                "profile": "portable-development",
                "applied_commit": "c" * 40,
                "runtime_commit": "c" * 40,
                "env_file": ".env.portable-development",
                "deployment_mode": "build",
                "release_dir": None,
                "local_airflow": False,
                "local_datahub": False,
                "local_redis": True,
                "local_storage": True,
                "local_gateway": False,
                "local_graph": False,
            }
        ),
        encoding="utf-8",
    )

    state = workflow.load_applied_state(state_path)

    assert state.environment_key_hashes == {}


def test_load_state_rejects_non_mapping_environment_fingerprints(tmp_path: Path) -> None:
    state_path = tmp_path / "invalid-state.json"
    state_path.write_text(
        json.dumps(
            {
                "profile": "portable-development",
                "applied_commit": "c" * 40,
                "runtime_commit": "c" * 40,
                "env_file": ".env.portable-development",
                "deployment_mode": "build",
                "release_dir": None,
                "local_airflow": False,
                "local_datahub": False,
                "local_redis": True,
                "local_storage": True,
                "local_gateway": False,
                "local_graph": False,
                "environment_key_hashes": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(workflow.WorkflowError, match="fingerprints"):
        workflow.load_applied_state(state_path)


def test_load_state_rejects_non_string_environment_fingerprint(tmp_path: Path) -> None:
    state_path = tmp_path / "invalid-state.json"
    state_path.write_text(
        json.dumps(
            {
                "profile": "portable-development",
                "applied_commit": "c" * 40,
                "runtime_commit": "c" * 40,
                "env_file": ".env.portable-development",
                "deployment_mode": "build",
                "release_dir": None,
                "local_airflow": False,
                "local_datahub": False,
                "local_redis": True,
                "local_storage": True,
                "local_gateway": False,
                "local_graph": False,
                "environment_key_hashes": {"DATAHUB_BASE_URL": 42},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(workflow.WorkflowError, match="fingerprints"):
        workflow.load_applied_state(state_path)


def test_load_state_rejects_unknown_fields(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "profile": "wsl-preparation",
                "applied_commit": "c" * 40,
                "runtime_commit": "b" * 40,
                "env_file": ".env.wsl-preparation",
                "deployment_mode": "offline",
                "release_dir": "/release",
                "local_airflow": False,
                "local_datahub": False,
                "local_redis": True,
                "local_storage": False,
                "local_gateway": False,
                "local_graph": False,
                "unexpected": "field",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(workflow.WorkflowError):
        workflow.load_applied_state(state_path)


def test_release_compatibility_allows_operator_only_checkout_changes() -> None:
    paths = (
        "README.md",
        "docs/26_MAC_TO_WSL_MIGRATION_RUNBOOK.md",
        "backend/tests/unit/test_platform_workflow.py",
        "compose.connected-source-host.yaml",
        "scripts/docker_capacity.py",
        "scripts/platform_workflow.py",
        "scripts/dev_host.sh",
        "scripts/workflow_fresh_setup.py",
        "scripts/workflow_source_host_infra.py",
        "scripts/workflow_update_restart.py",
        "scripts/verify_static.py",
    )

    assert workflow.incompatible_release_paths(paths) == ()


def test_release_compatibility_rejects_runtime_and_compose_changes() -> None:
    paths = (
        "backend/src/datariver/config.py",
        "frontend/src/App.tsx",
        "compose.yaml",
        "scripts/workflow_update_restart.py",
    )

    assert workflow.incompatible_release_paths(paths) == (
        "backend/src/datariver/config.py",
        "frontend/src/App.tsx",
        "compose.yaml",
    )


def test_restart_selection_keeps_defaults_and_only_running_optional_workers() -> None:
    selected = workflow.select_restart_services(
        (
            "api",
            "web",
            "catalog-export-worker",
            "knowledge-source-worker",
        ),
        running_services=("api", "web", "knowledge-source-worker"),
    )

    assert selected == ("api", "web", "knowledge-source-worker")


def test_operator_workflow_changes_do_not_restart_runtime() -> None:
    result = workflow.classify_changes(
        (
            "scripts/platform_workflow.py",
            "scripts/workflow_fresh_setup.py",
            "scripts/workflow_update_restart.py",
            "scripts/verify_static.py",
        )
    )

    assert result.services == ()
    assert result.requires_migration is False


def test_docker_capacity_controller_is_operator_only() -> None:
    result = workflow.classify_changes(("scripts/docker_capacity.py",))

    assert result.services == ()
    assert result.requires_migration is False
    assert result.local_connector_services == ()
    assert result.restart_datahub is False
    assert result.restart_airflow is False
    assert result.restart_gateway is False
    assert result.restart_graph is False


def test_datahub_wrapper_change_only_restarts_local_datahub_when_selected() -> None:
    result = workflow.classify_changes(("scripts/start_datahub_mac_dev.sh",))

    assert result.services == ()
    assert result.restart_datahub is True
    assert result.requires_migration is False


def test_update_reuses_existing_datahub_images_without_registry_pull() -> None:
    source = UPDATE_MODULE_PATH.read_text(encoding="utf-8")
    datahub_block = source.split(
        "if plan.restart_datahub and state.local_datahub:",
        maxsplit=1,
    )[1].split("if plan.restart_graph", maxsplit=1)[0]

    assert '"start-offline"' in datahub_block
    assert '"start"' not in datahub_block


def test_offline_identity_build_keeps_existing_no_capacity_evidence_semantics() -> None:
    source = UPDATE_MODULE_PATH.read_text(encoding="utf-8")
    identity_block = source.split("if reapply_local_identity:", maxsplit=1)[1].split(
        "if plan.requires_migration:", maxsplit=1
    )[0]

    assert "if not offline:" in identity_block
    assert identity_block.index("if not offline:") < identity_block.index(
        "_require_idle_builder(selected_builder, capacity_lock)"
    )
    assert identity_block.index("_require_idle_builder") < identity_block.index(
        'trailing=("build", "local-bootstrap")'
    )


def test_normalize_secret_permissions_keeps_private_directory_and_readable_mounts(
    tmp_path: Path,
) -> None:
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    secret = secret_dir / "provider_token"
    secret.write_text("secret\n", encoding="utf-8")
    secret.chmod(0o600)

    workflow.normalize_secret_permissions(secret_dir)

    assert secret_dir.stat().st_mode & 0o777 == 0o700
    assert secret.stat().st_mode & 0o777 == 0o444


@pytest.mark.parametrize("value", ("neo4j/password", "reader/a/long/password"))
def test_username_password_secret_accepts_delimiter_after_username(value: str) -> None:
    assert workflow.validate_username_password_secret(value) == value


@pytest.mark.parametrize("value", ("", "neo4j", "/password", "neo4j/"))
def test_username_password_secret_rejects_missing_parts(value: str) -> None:
    with pytest.raises(workflow.WorkflowError):
        workflow.validate_username_password_secret(value)
