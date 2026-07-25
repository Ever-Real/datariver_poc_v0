from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "scripts" / "platform_workflow.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("platform_workflow", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


workflow = _load_module()


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
        "knowledge-source-worker",
        "outbox-relay",
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
    )

    workflow.write_applied_state(state_path, state)

    assert workflow.load_applied_state(state_path) == state
    assert json.loads(state_path.read_text(encoding="utf-8"))["applied_commit"] == "b" * 40
    assert json.loads(state_path.read_text(encoding="utf-8"))["runtime_commit"] == "a" * 40


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
        "scripts/platform_workflow.py",
        "scripts/workflow_fresh_setup.py",
        "scripts/workflow_update_restart.py",
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
