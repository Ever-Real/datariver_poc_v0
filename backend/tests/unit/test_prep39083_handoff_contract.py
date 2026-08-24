from __future__ import annotations

import importlib.util
import io
import os
import tarfile
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "scripts" / "prep39083_release.py"
DEPLOYMENT = ROOT / "deploy" / "prep39083"


def _load_module() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "prep39083_release_for_test",
        MODULE_PATH,
    )
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


release = _load_module()


def test_prep_and_ops_templates_are_isolated_amd64_and_provider_external() -> None:
    prep = (DEPLOYMENT / ".env.prep.example").read_text(encoding="utf-8")
    ops = (DEPLOYMENT / ".env.ops.example").read_text(encoding="utf-8")

    assert "COMPOSE_PROJECT_NAME=datariver-prep39083" in prep
    assert "POC_PORT=39083" in prep
    assert "POC_PLATFORM=linux/amd64" in prep
    assert "POC_SHARED_NETWORK=datariver-prep39083-services" in prep
    assert "POC_POSTGRES_HOST_PORT=25432" in prep
    assert "POC_REDIS_PORT=26379" in prep
    assert "POC_NEO4J_HTTP_PORT=27475" in prep
    assert "COMPOSE_PROJECT_NAME=datariver-ops39083" in ops
    assert "POC_SHARED_NETWORK=datariver-ops39083-services" in ops
    for document in (prep, ops):
        assert "POC_PORT=39080" not in document
        assert "host.docker.internal" not in document
        assert "/Users/" not in document
        assert "LOCAL_LLAMA_CPP" not in document
        assert "POC_DATAHUB_ALLOW_NO_TOKEN=false" in document
        assert "POC_K9_SCHEDULER_ENABLED=true" in document
        assert "POC_K9_REFRESH_MODE=DAILY" in document
        assert "DATAHUB_GMS_URL=" in document
        assert "AIRFLOW_URL=" in document
        assert "MINIO_URL=" in document
        assert "LLM_CHAT_URL=" in document
        assert "LLM_EMBEDDING_URL=" in document
        assert "LLM_RERANKER_URL=" in document


def test_ops_override_removes_build_and_forbids_pull() -> None:
    override = (DEPLOYMENT / "docker-compose.ops.yaml").read_text(encoding="utf-8")

    assert "build: !reset null" in override
    assert override.count("pull_policy: never") == 4
    assert "image:" not in override
    assert "volumes:" not in override


def test_exporter_is_exact_running_image_capture_not_build_or_load() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")

    assert '"save",' in source
    assert '"org.opencontainers.image.revision"' in source
    assert '"linux/amd64"' in source
    assert '"runtime_input_diff": "NONE"' in source
    assert "docker image load" not in source
    assert "docker build" not in source
    assert "docker pull" not in source
    assert "docker compose up" not in source
    assert "docker compose down" not in source
    assert "docker volume rm" not in source
    assert "deploy/poc/.env" not in source


def test_release_archive_path_validation_rejects_escape(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe.tar"
    with tarfile.open(archive_path, "w") as archive:
        info = tarfile.TarInfo("../escape")
        payload = b"unsafe"
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))

    with tarfile.open(archive_path, "r") as archive:
        with pytest.raises(release.ReleaseError, match="unsafe path"):
            release.safe_archive_members(archive)


def test_release_archive_path_validation_rejects_duplicate(tmp_path: Path) -> None:
    archive_path = tmp_path / "duplicate.tar"
    with tarfile.open(archive_path, "w") as archive:
        for payload in (b"first", b"second"):
            info = tarfile.TarInfo("same-name")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))

    with tarfile.open(archive_path, "r") as archive:
        with pytest.raises(release.ReleaseError, match="unsafe path"):
            release.safe_archive_members(archive)


def test_private_environment_rejects_symlink_and_open_permissions(tmp_path: Path) -> None:
    environment = tmp_path / ".env.prep"
    environment.write_text("POC_PORT=39083\n", encoding="utf-8")
    environment.chmod(0o644)
    with pytest.raises(release.ReleaseError, match="0600"):
        release.require_private_env(environment)
    environment.chmod(0o600)
    assert release.require_private_env(environment) == environment.resolve()

    link = tmp_path / "linked.env"
    link.symlink_to(environment)
    with pytest.raises(release.ReleaseError, match="non-symlink"):
        release.require_private_env(link)


def test_operator_docs_preserve_ports_state_and_no_build_ops() -> None:
    prep = (ROOT / "docs" / "64_PREP39083_HANDOFF.md").read_text(encoding="utf-8")
    ops = (ROOT / "docs" / "65_PREP_TO_OPS_PROMOTION.md").read_text(encoding="utf-8")
    cycle = (ROOT / "docs" / "66_RELEASE_CYCLE.md").read_text(encoding="utf-8")

    assert "cmp /tmp/datariver-39080-before.txt /tmp/datariver-39080-after.txt" in prep
    assert "--project-name datariver-prep39083" in prep
    assert "up -d --no-build --wait" in prep
    assert "docker compose down -v" in prep
    assert "Never use `docker compose down -v`" in ops
    assert "docker load --input images.tar" in ops
    assert "up -d --no-build --wait" in ops
    assert "pull_policy: never" in ops
    assert "DEV never claims PREP or OPS runtime acceptance" in cycle
    assert "only one materializer" in cycle


def test_smoke_uses_opaque_login_and_checks_managed_graphs() -> None:
    smoke = (ROOT / "scripts" / "smoke_prep39083.mjs").read_text(encoding="utf-8")

    assert "/auth/login" in smoke
    assert "/auth/logout" in smoke
    assert "/poc-api/datahub/catalog?limit=1" in smoke
    assert "/poc-api/knowledge/managed-assets" in smoke
    assert "LINEAGE" in smoke
    assert "METADATA_MASTER" in smoke
    assert "semantic_index_status" in smoke
    assert "selected_mode !== 'GENERAL'" in smoke
    assert "writeFile(output" in smoke
    assert "password }" in smoke
    assert "console.log(password" not in smoke


def test_runtime_input_boundary_excludes_handoff_only_artifacts() -> None:
    assert release.RUNTIME_INPUTS == (
        "frontend",
        "deploy/poc/Dockerfile.example",
        "deploy/poc/docker-compose.poc.yaml",
        "deploy/poc/postgres-init",
    )
    for path in (release.BASE_COMPOSE, release.OPS_COMPOSE, release.PREP_ENV_EXAMPLE):
        assert Path(path).is_file()
    assert release.POSTGRES_INIT.is_dir()
    assert any(release.POSTGRES_INIT.glob("*.sql"))


def test_tracked_examples_are_explicit_gitignore_exceptions() -> None:
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "!deploy/prep39083/.env.prep.example" in ignore
    assert "!deploy/prep39083/.env.ops.example" in ignore
    assert os.fspath(DEPLOYMENT / ".env.prep") not in ignore
