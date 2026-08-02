from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest

from datariver.config import Settings

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "scripts" / "platform_workflow.py"
FRESH_SETUP_MODULE_PATH = ROOT / "scripts" / "workflow_fresh_setup.py"
UPDATE_MODULE_PATH = ROOT / "scripts" / "workflow_update_restart.py"


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
    sys.modules["platform_workflow"] = workflow
    try:
        spec.loader.exec_module(module)
    finally:
        if previous_platform_module is None:
            sys.modules.pop("platform_workflow", None)
        else:
            sys.modules["platform_workflow"] = previous_platform_module
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
        self.notes: list[str] = []

    def output(self, arguments: Any) -> str:
        self.calls.append(tuple(os.fspath(argument) for argument in arguments))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def note(self, message: str) -> None:
        self.notes.append(message)


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


def test_datahub_wrapper_change_only_restarts_local_datahub_when_selected() -> None:
    result = workflow.classify_changes(("scripts/start_datahub_mac_dev.sh",))

    assert result.services == ()
    assert result.restart_datahub is True
    assert result.requires_migration is False


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
