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


def _neo4j_bundle(tmp_path: Path, *, platform_name: str = "linux/amd64") -> Path:
    bundle = tmp_path / "neo4j-bundle"
    bundle.mkdir(parents=True)
    archive = bundle / "neo4j-2026.06.0-linux-amd64.tar.gz"
    archive.write_bytes(b"verified neo4j amd64 test archive")
    _write_checksum(archive)
    archive_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
    image_id = "sha256:" + "4" * 64
    repository_digest = workflow.approved_neo4j_source_image().partition("@")[2]
    (bundle / "neo4j-2026.06.0-linux-amd64.manifest.tsv").write_text(
        (
            "archive\timage\tsource_image\tplatform\timage_id\trepo_digest"
            "\tarchive_sha256\n"
            f"{archive.name}\tneo4j:2026.06.0"
            f"\tneo4j:2026.06.0@{repository_digest}\t{platform_name}\t{image_id}"
            f"\tneo4j@{repository_digest}\t{archive_sha256}\n"
        ),
        encoding="utf-8",
    )
    return bundle


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
    assert plan.local_image_reuse is False
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
    assert plan.local_image_reuse is False
    assert plan.release_platform_dir is None
    assert [path.name for path in plan.compose_files] == [
        "compose.yaml",
        "compose.identity.yaml",
        "compose.source-host.yaml",
    ]


class _ImageRunner:
    def __init__(
        self,
        *,
        database_id: str | None = None,
        platform_name: str = "linux/amd64",
    ) -> None:
        self.database_id = database_id or "sha256:" + "1" * 64
        self.platform_name = platform_name

    def output(self, arguments: list[str] | tuple[str, ...]) -> str:
        image = str(arguments[-1])
        if image == "postgres:17.10-bookworm":
            return f"{self.database_id}\t{self.platform_name}"
        if image == "datariver-keycloak:26.7.0":
            return f"sha256:{'2' * 64}\t{self.platform_name}"
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
        local_image_reuse=False,
        release_platform_dir=tmp_path / "release/amd64",
    )

    assert workflow.rendered_service_images(cast(Any, _ConfigRunner()), plan) == {
        "postgres": "registry/database:reviewed",
        "keycloak": "registry/identity:reviewed",
    }


def test_local_reuse_requires_existing_amd64_infrastructure_before_mutation() -> None:
    images = {
        "postgres": "postgres:17.10-bookworm",
        "keycloak": "datariver-keycloak:26.7.0",
    }

    workflow.verify_local_source_images(cast(Any, _ImageRunner()), images)

    with pytest.raises(
        platform.WorkflowError,
        match="requires the existing postgres image",
    ):
        workflow.verify_local_source_images(cast(Any, _MissingImageRunner()), images)
    with pytest.raises(platform.WorkflowError, match="must be linux/amd64"):
        workflow.verify_local_source_images(
            cast(Any, _ImageRunner(platform_name="linux/arm64")),
            images,
        )


def test_state_absent_plan_infers_registry_disabled_local_image_reuse(
    tmp_path: Path,
) -> None:
    (tmp_path / ".env.connected").write_text("APP_ENV=development\n", encoding="utf-8")

    plan = workflow.resolve_plan(
        root=tmp_path,
        state=None,
        env_file_override=Path(".env.connected"),
    )

    assert plan.profile == "local-image-source-development"
    assert plan.offline is False
    assert plan.local_image_reuse is True
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
            reuse_local_images=True,
        )
    with pytest.raises(platform.WorkflowError, match="applied workflow state is unavailable"):
        workflow.resolve_plan(
            root=tmp_path,
            state=None,
            env_file_override=None,
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


def test_neo4j_bundle_binds_archive_checksum_platform_and_image_identity(
    tmp_path: Path,
) -> None:
    bundle = workflow.load_neo4j_bundle(_neo4j_bundle(tmp_path))

    assert bundle.image == "neo4j:2026.06.0"
    assert bundle.platform == "linux/amd64"
    assert bundle.image_id == "sha256:" + "4" * 64
    assert bundle.source_image == workflow.approved_neo4j_source_image()
    assert bundle.repository_digest == (
        "neo4j@" + workflow.approved_neo4j_source_image().partition("@")[2]
    )
    assert bundle.archive_sha256 == hashlib.sha256(bundle.archive.read_bytes()).hexdigest()


def test_neo4j_bundle_rejects_wrong_platform_and_modified_archive(tmp_path: Path) -> None:
    wrong_platform = _neo4j_bundle(tmp_path / "wrong-platform", platform_name="linux/arm64")
    with pytest.raises(platform.WorkflowError, match="must target linux/amd64"):
        workflow.load_neo4j_bundle(wrong_platform)

    modified = _neo4j_bundle(tmp_path / "modified")
    next(modified.glob("*.tar.gz")).write_bytes(b"modified")
    with pytest.raises(platform.WorkflowError, match="Checksum mismatch"):
        workflow.load_neo4j_bundle(modified)

    digest_mismatch = _neo4j_bundle(tmp_path / "digest-mismatch")
    manifest = next(digest_mismatch.glob("*.manifest.tsv"))
    approved_digest = workflow.approved_neo4j_source_image().partition("@")[2]
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            f"neo4j@{approved_digest}",
            f"neo4j@sha256:{'6' * 64}",
        ),
        encoding="utf-8",
    )
    with pytest.raises(platform.WorkflowError, match="digest fields do not match"):
        workflow.load_neo4j_bundle(digest_mismatch)

    unapproved = _neo4j_bundle(tmp_path / "unapproved")
    manifest = next(unapproved.glob("*.manifest.tsv"))
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            approved_digest,
            "sha256:" + "7" * 64,
        ),
        encoding="utf-8",
    )
    with pytest.raises(platform.WorkflowError, match="approved Compose digest pin"):
        workflow.load_neo4j_bundle(unapproved)


def test_neo4j_bundle_directory_rejects_symbolic_links(tmp_path: Path) -> None:
    bundle = _neo4j_bundle(tmp_path)
    linked = tmp_path / "linked-bundle"
    linked.symlink_to(bundle, target_is_directory=True)

    with pytest.raises(platform.WorkflowError, match="must not be a symbolic link"):
        workflow.load_neo4j_bundle(linked)


class _Neo4jImageRunner:
    def __init__(self, *, observed: str | None = None) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.observed = observed or f"sha256:{'4' * 64}\tlinux/amd64"

    def run(self, arguments: list[str] | tuple[str, ...]) -> None:
        self.commands.append(tuple(str(value) for value in arguments))

    def output(self, arguments: list[str] | tuple[str, ...]) -> str:
        self.commands.append(tuple(str(value) for value in arguments))
        return self.observed


class _Neo4jStartRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.environments: list[dict[str, str]] = []

    def run(
        self,
        arguments: list[str] | tuple[str, ...],
        *,
        env: dict[str, str] | None = None,
    ) -> None:
        self.commands.append(tuple(str(value) for value in arguments))
        self.environments.append(dict(env or {}))


def test_neo4j_image_load_is_verified_against_the_bundle_manifest(tmp_path: Path) -> None:
    bundle = workflow.load_neo4j_bundle(_neo4j_bundle(tmp_path))
    runner = _Neo4jImageRunner()

    workflow.verify_and_load_neo4j_image(cast(Any, runner), bundle)

    assert runner.commands[0] == (
        "docker",
        "image",
        "load",
        "--input",
        str(bundle.archive),
    )
    assert runner.commands[1][-1] == bundle.image

    mismatched = _Neo4jImageRunner(observed=f"sha256:{'9' * 64}\tlinux/amd64")
    with pytest.raises(platform.WorkflowError, match="does not match"):
        workflow.verify_and_load_neo4j_image(cast(Any, mismatched), bundle)


def test_loaded_neo4j_reuse_requires_approved_tag_and_amd64(tmp_path: Path) -> None:
    environment = tmp_path / ".env.source"
    environment.write_text("NEO4J_IMAGE=neo4j:2026.06.0\n", encoding="utf-8")
    plan = workflow.SourceHostInfraPlan(
        profile="local-image-source-development",
        env_file=environment,
        compose_files=(tmp_path / "compose.yaml",),
        offline=False,
        local_image_reuse=True,
        release_platform_dir=None,
    )

    image = workflow.configured_loaded_neo4j_image(plan)
    assert image == "neo4j:2026.06.0"
    workflow.verify_loaded_neo4j_image(cast(Any, _Neo4jImageRunner()), image)
    with pytest.raises(platform.WorkflowError, match="loaded Neo4j image is unavailable"):
        workflow.verify_loaded_neo4j_image(cast(Any, _MissingImageRunner()), image)

    wrong_platform = _Neo4jImageRunner(observed=f"sha256:{'4' * 64}\tlinux/arm64")
    with pytest.raises(platform.WorkflowError, match="must be linux/amd64"):
        workflow.verify_loaded_neo4j_image(cast(Any, wrong_platform), image)

    environment.write_text("NEO4J_IMAGE=neo4j:unreviewed\n", encoding="utf-8")
    with pytest.raises(platform.WorkflowError, match="approved configured tag"):
        workflow.configured_loaded_neo4j_image(plan)


def test_neo4j_environment_is_persisted_only_after_authenticated_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = workflow.load_neo4j_bundle(_neo4j_bundle(tmp_path))
    environment = tmp_path / ".env.source"
    environment.write_text(
        (
            "APP_ENV=development\n"
            "NEO4J_BOLT_PORT=27687\n"
            "NEO4J_URI=bolt://neo4j:7687\n"
            "NEO4J_URI=bolt://stale.invalid:7687\n"
        ),
        encoding="utf-8",
    )
    secret_directory = tmp_path / "secrets"
    secret_directory.mkdir()
    (secret_directory / "neo4j_auth").write_text(
        f"neo4j/{'a' * 64}",
        encoding="utf-8",
    )
    plan = workflow.SourceHostInfraPlan(
        profile="wsl-preparation",
        env_file=environment,
        compose_files=(tmp_path / "compose.yaml",),
        offline=True,
        local_image_reuse=False,
        release_platform_dir=tmp_path / "release/amd64",
    )
    monkeypatch.setattr(workflow, "ROOT", tmp_path)

    configuration = workflow.resolve_neo4j_environment(plan, bundle.image)
    assert configuration == {
        "NEO4J_ALLOWED_HOSTS": "127.0.0.1",
        "NEO4J_AUTH_SECRET_REF": "file:/run/secrets/neo4j_auth",
        "NEO4J_IMAGE": "neo4j:2026.06.0",
        "NEO4J_PROJECTION_ENABLED": "true",
        "NEO4J_SOURCE_HOST_ENABLED": "true",
        "NEO4J_URI": "bolt://127.0.0.1:27687",
    }
    assert environment.read_text(encoding="utf-8").count("NEO4J_URI=") == 2

    runner = _Neo4jStartRunner()
    workflow.start_and_verify_neo4j(cast(Any, runner), plan, configuration)

    values = platform.read_env_values(environment)
    assert values["NEO4J_IMAGE"] == "neo4j:2026.06.0"
    assert values["NEO4J_PROJECTION_ENABLED"] == "true"
    assert values["NEO4J_SOURCE_HOST_ENABLED"] == "true"
    assert values["NEO4J_URI"] == "bolt://127.0.0.1:27687"
    assert values["NEO4J_ALLOWED_HOSTS"] == "127.0.0.1"
    assert environment.read_text(encoding="utf-8").count("NEO4J_URI=") == 1
    assert any(command[-6:-3] == ("exec", "-T", "neo4j") for command in runner.commands)
    assert all("datariver-local-connectors-neo4j-1" not in command for command in runner.commands)
    assert all(item["NEO4J_IMAGE"] == "neo4j:2026.06.0" for item in runner.environments)
