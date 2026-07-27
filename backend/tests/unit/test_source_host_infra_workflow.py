from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[3]
PLATFORM_MODULE_PATH = ROOT / "scripts" / "platform_workflow.py"
WORKFLOW_MODULE_PATH = ROOT / "scripts" / "workflow_source_host_infra.py"


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


platform = _load_module("platform_workflow", PLATFORM_MODULE_PATH)
workflow = _load_module("workflow_source_host_infra_for_test", WORKFLOW_MODULE_PATH)


def test_container_application_stop_set_excludes_identity_infrastructure() -> None:
    assert "keycloak" not in workflow.CONTAINER_APPLICATION_SERVICES
    assert set(workflow.CONTAINER_APPLICATION_SERVICES) == set(platform.RUNTIME_SERVICES) - {
        "keycloak"
    }


def _write_checksum(path: Path) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_name(f"{path.name}.sha256").write_text(
        f"{digest}  {path.name}\n",
        encoding="utf-8",
    )


def _release(tmp_path: Path) -> Path:
    release = tmp_path / "release"
    platform_directory = release / "amd64"
    platform_directory.mkdir(parents=True)
    archive = platform_directory / "datariver-core-amd64.tar"
    archive.write_bytes(b"verified test archive")
    _write_checksum(archive)
    offline_compose = platform_directory / "offline-core.compose.yaml"
    offline_compose.write_text(
        "services:\n  postgres:\n    image: postgres:17.10-bookworm\n",
        encoding="utf-8",
    )
    _write_checksum(offline_compose)
    postgres_id = "sha256:" + "1" * 64
    keycloak_id = "sha256:" + "2" * 64
    manifest = platform_directory / "datariver-core-amd64.manifest.tsv"
    manifest.write_text(
        (
            "image\timage_id\trepository_digests\tplatform\n"
            "postgres:17.10-bookworm@sha256:"
            f"{'3' * 64}\t{postgres_id}\t\tlinux/amd64\n"
            f"datariver-keycloak:26.7.0\t{keycloak_id}\t\tlinux/amd64\n"
        ),
        encoding="utf-8",
    )
    _write_checksum(manifest)
    (release / "source-commit.txt").write_text("a" * 40 + "\n", encoding="utf-8")
    return release


def _state(
    *,
    release_dir: Path | None,
    deployment_mode: str,
) -> Any:
    return platform.AppliedState(
        profile=("wsl-preparation" if deployment_mode == "offline" else "mac-development"),
        applied_commit="a" * 40,
        runtime_commit="a" * 40,
        env_file=".env.selected",
        deployment_mode=deployment_mode,
        release_dir=str(release_dir) if release_dir else None,
        local_airflow=False,
        local_datahub=False,
        local_redis=True,
        local_storage=False,
        local_gateway=False,
        local_graph=False,
    )


def test_offline_plan_hides_the_release_override_behind_applied_state(
    tmp_path: Path,
) -> None:
    (tmp_path / ".env.selected").write_text("APP_ENV=development\n", encoding="utf-8")
    release = _release(tmp_path)

    plan = workflow.resolve_plan(
        root=tmp_path,
        state=_state(release_dir=release, deployment_mode="offline"),
        env_file_override=None,
    )

    assert plan.offline is True
    assert plan.connected_build is False
    assert plan.env_file == (tmp_path / ".env.selected").resolve()
    assert [path.name for path in plan.compose_files] == [
        "compose.yaml",
        "compose.identity.yaml",
        "compose.source-host.yaml",
        "offline-core.compose.yaml",
    ]


def test_build_plan_uses_the_same_action_without_an_offline_override(
    tmp_path: Path,
) -> None:
    (tmp_path / ".env.selected").write_text("APP_ENV=development\n", encoding="utf-8")

    plan = workflow.resolve_plan(
        root=tmp_path,
        state=_state(release_dir=None, deployment_mode="build"),
        env_file_override=None,
    )

    assert plan.offline is False
    assert plan.connected_build is False
    assert plan.release_platform_dir is None
    assert [path.name for path in plan.compose_files] == [
        "compose.yaml",
        "compose.identity.yaml",
        "compose.source-host.yaml",
    ]


class _ImageRunner:
    def __init__(self, *, database_id: str | None = None) -> None:
        self.database_id = database_id or "sha256:" + "1" * 64

    def output(self, arguments: list[str] | tuple[str, ...]) -> str:
        image = str(arguments[-1])
        if image == "postgres:17.10-bookworm":
            return f"{self.database_id}\tlinux/amd64"
        if image == "datariver-keycloak:26.7.0":
            return f"sha256:{'2' * 64}\tlinux/amd64"
        raise AssertionError(f"Unexpected image: {image}")


class _ConfigRunner:
    def output(self, arguments: list[str] | tuple[str, ...]) -> str:
        assert tuple(str(value) for value in arguments[-3:]) == (
            "config",
            "--format",
            "json",
        )
        return (
            '{"services":{"postgres":{"image":"registry/database:reviewed"},'
            '"keycloak":{"image":"registry/identity:reviewed"}}}'
        )


class _MissingImageRunner:
    def output(self, arguments: list[str] | tuple[str, ...]) -> str:
        raise platform.WorkflowError(f"missing {arguments[-1]}")


def test_service_images_come_from_the_final_compose_model(tmp_path: Path) -> None:
    plan = workflow.SourceHostInfraPlan(
        profile="wsl-preparation",
        env_file=tmp_path / ".env",
        compose_files=(tmp_path / "compose.yaml",),
        offline=True,
        connected_build=False,
        release_platform_dir=tmp_path / "release/amd64",
    )

    assert workflow.rendered_service_images(cast(Any, _ConfigRunner()), plan) == {
        "postgres": "registry/database:reviewed",
        "keycloak": "registry/identity:reviewed",
    }


def test_connected_prepare_requires_existing_final_keycloak_before_mutation() -> None:
    images = {
        "postgres": "postgres:17.10-bookworm",
        "keycloak": "datariver-keycloak:26.7.0",
    }

    workflow.verify_connected_local_keycloak(cast(Any, _ImageRunner()), images)

    with pytest.raises(
        platform.WorkflowError,
        match="requires the existing final Keycloak image",
    ):
        workflow.verify_connected_local_keycloak(cast(Any, _MissingImageRunner()), images)


def test_connected_build_plan_requires_explicit_environment_and_no_state(
    tmp_path: Path,
) -> None:
    (tmp_path / ".env.connected").write_text("APP_ENV=development\n", encoding="utf-8")

    plan = workflow.resolve_plan(
        root=tmp_path,
        state=None,
        env_file_override=Path(".env.connected"),
        connected_build=True,
    )

    assert plan.profile == "connected-source-development"
    assert plan.offline is False
    assert plan.connected_build is True
    assert [path.name for path in plan.compose_files] == [
        "compose.yaml",
        "compose.identity.yaml",
        "compose.source-host.yaml",
        "compose.connected-source-host.yaml",
    ]
    with pytest.raises(platform.WorkflowError, match="requires an explicit --env-file"):
        workflow.resolve_plan(
            root=tmp_path,
            state=None,
            env_file_override=None,
            connected_build=True,
        )
    with pytest.raises(platform.WorkflowError, match="applied workflow state is unavailable"):
        workflow.resolve_plan(
            root=tmp_path,
            state=None,
            env_file_override=Path(".env.connected"),
        )


def test_offline_image_verification_binds_local_tags_to_release_ids(
    tmp_path: Path,
) -> None:
    release = _release(tmp_path)

    workflow.verify_offline_images(
        cast(Any, _ImageRunner()),
        release / "amd64",
        {
            "postgres": "postgres:17.10-bookworm",
            "keycloak": "datariver-keycloak:26.7.0",
        },
    )

    with pytest.raises(
        platform.WorkflowError,
        match="does not match the verified release manifest",
    ):
        workflow.verify_offline_images(
            cast(Any, _ImageRunner(database_id="sha256:" + "9" * 64)),
            release / "amd64",
            {
                "postgres": "postgres:17.10-bookworm",
                "keycloak": "datariver-keycloak:26.7.0",
            },
        )


def test_offline_verification_uses_resolved_compose_images_not_script_tags(
    tmp_path: Path,
) -> None:
    release = _release(tmp_path)

    with pytest.raises(
        platform.WorkflowError,
        match="omits the resolved postgres image",
    ):
        workflow.verify_offline_images(
            cast(Any, _ImageRunner()),
            release / "amd64",
            {
                "postgres": "postgres:unexpected",
                "keycloak": "datariver-keycloak:26.7.0",
            },
        )


def test_offline_verification_rejects_registry_only_digest_reference(
    tmp_path: Path,
) -> None:
    release = _release(tmp_path)

    with pytest.raises(
        platform.WorkflowError,
        match="retained a registry-only digest",
    ):
        workflow.verify_offline_images(
            cast(Any, _ImageRunner()),
            release / "amd64",
            {
                "postgres": f"postgres:17.10-bookworm@sha256:{'3' * 64}",
                "keycloak": "datariver-keycloak:26.7.0",
            },
        )


def test_checksum_verification_rejects_modified_offline_override(
    tmp_path: Path,
) -> None:
    release = _release(tmp_path)
    offline_compose = release / "amd64/offline-core.compose.yaml"
    offline_compose.write_text("services: {}\n", encoding="utf-8")

    with pytest.raises(platform.WorkflowError, match="Checksum mismatch"):
        workflow.verify_checksum(release / "amd64/offline-core.compose.yaml.sha256")
