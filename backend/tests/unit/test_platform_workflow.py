from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Self, cast

import pytest

from datariver.config import Settings

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
    assert audit.intent_mismatch == ("graph.neo4j",)


def test_exact_mac_topology_reconciliation_changes_only_graph_and_gateway() -> None:
    state = _topology_state(
        profile="mac-development",
        local_airflow=True,
        local_datahub=True,
        local_redis=True,
        local_storage=True,
        environment_key_hashes={"UNCHANGED": "a" * 64},
    )
    audit = workflow.LocalTopologyAudit(
        expected_missing=("worker.governance-document",),
        unexpected_running=("gateway.apisix", "graph.neo4j"),
        selected_unhealthy=(),
        intent_mismatch=("graph.neo4j",),
    )

    plan = workflow.build_topology_reconciliation_plan(
        "mac-development-graph-gateway-v1",
        state=state,
        environment_values={
            "GOVERNANCE_DOCUMENT_WORKER_ENABLED": "true",
            "NEO4J_PROJECTION_ENABLED": "true",
            "NEO4J_URI": "bolt://neo4j:7687",
        },
        audit=audit,
    )

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
        ({"local_graph": True}, {}, {}),
        ({"local_gateway": True}, {}, {}),
        ({}, {"NEO4J_PROJECTION_ENABLED": "false"}, {}),
        ({}, {"GOVERNANCE_DOCUMENT_WORKER_ENABLED": "false"}, {}),
        ({}, {}, {"expected_missing": ()}),
        ({}, {}, {"unexpected_unknown_count": 1}),
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
    assert events[6][-1] == "apisix"
    assert events[7][-1] == "web"
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


def test_topology_reconciliation_failure_stops_before_later_mutations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update = _load_update_module()
    calls: list[tuple[str, ...]] = []

    def compose(_runner: object, **kwargs: object) -> None:
        trailing = cast(tuple[str, ...], kwargs["trailing"])
        calls.append(trailing)
        if trailing == ("build", "apisix"):
            raise workflow.WorkflowError("fixed-gateway-build-failure")

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

    with pytest.raises(workflow.WorkflowError, match="fixed-gateway-build-failure"):
        update._apply_topology_reconciliation(
            SimpleNamespace(note=lambda _message: None),
            env_file=tmp_path / ".env",
            files=(ROOT / "compose.yaml", ROOT / "compose.gateway.yaml"),
            plan=_topology_reconciliation_plan(),
            selected_builder="builder",
            capacity_lock=object(),
            secret_guard=SecretGuard(),
        )

    assert calls[0][-1] == "governance-document-worker"
    assert calls[1] == ("build", "apisix")
    assert all(call[-1] not in {"web", "airflow-triggerer"} for call in calls)


def _write_topology_secret_fixture(root: Path) -> Path:
    secret_dir = root / "secrets"
    secret_dir.mkdir(mode=0o700)
    secret_dir.chmod(0o700)
    for name in workflow.TOPOLOGY_RECONCILIATION_SECRET_NAMES:
        target = secret_dir / name
        target.write_text("fixture\n", encoding="utf-8")
        target.chmod(0o444)
    return secret_dir


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
    assert set(request) == {
        "allow_external_subject",
        "contract",
        "deny_external_subject",
        "operation",
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
