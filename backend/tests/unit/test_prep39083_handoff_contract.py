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
    optional = (DEPLOYMENT / ".env.prep.optional.example").read_text(encoding="utf-8")
    ops = (DEPLOYMENT / ".env.ops.example").read_text(encoding="utf-8")
    contract = (DEPLOYMENT / "env-contract.json").read_text(encoding="utf-8")

    assert "POC_PUBLIC_ORIGIN=" in prep
    assert "HTTP_PROXY=" in prep
    assert "HTTPS_PROXY=" in prep
    assert "NO_PROXY=" in prep
    assert "POC_POSTGRES_PASSWORD=" not in prep
    assert "NEO4J_PASSWORD=" not in prep
    assert "POC_MCP_SERVICE_TOKEN=" not in prep
    assert "POC_MCL_KAFKA_BROKERS=" not in prep
    assert "AIRFLOW_URL=" not in prep
    assert "MINIO_URL=" not in prep
    assert "AIRFLOW_URL=" in optional
    assert "MINIO_URL=" in optional
    assert "POC_CHANGE_HISTORY_SCHEDULER_ENABLED=false" in optional
    assert '"COMPOSE_PROJECT_NAME": "datariver-prep39083"' in contract
    assert '"POC_PORT": "39083"' in contract
    assert '"POC_PLATFORM": "linux/amd64"' in contract
    assert '"POC_SHARED_NETWORK": "datariver-prep39083-services"' in contract
    assert "COMPOSE_PROJECT_NAME=datariver-ops39083" in ops
    assert "POC_SHARED_NETWORK=datariver-ops39083-services" in ops
    for document in (prep, optional, ops, contract):
        assert "POC_PORT=39080" not in document
        assert "host.docker.internal" not in document
        assert "/Users/" not in document
        assert "LOCAL_LLAMA_CPP" not in document
    assert "DATAHUB_GMS_URL=" in prep
    assert "LLM_CHAT_URL=" in prep
    assert "LLM_EMBEDDING_URL=" in prep
    assert "LLM_RERANKER_URL=" in prep


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

    assert "./scripts/prep39083 deploy" in prep
    assert "git pull --ff-only origin dev" in prep
    assert "PRODUCT_SHA" in prep and "Operators do not" in prep
    assert "docker compose run --no-deps" in prep
    assert "raw `docker run`" in prep
    assert "docker compose down -v" in prep
    assert "./scripts/prep39083 export" in ops
    assert "Never use `docker compose down -v`" in ops
    assert "docker load --input images.tar" in ops
    assert "up -d --no-build --wait" in ops
    assert "pull_policy: never" in ops
    assert "DEV never claims PREP or OPS runtime acceptance" in cycle
    assert "Only one materializer" in cycle
    assert "./scripts/prep39083 deploy" in cycle


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
    assert "frontend" in release.RUNTIME_INPUTS
    assert "deploy/poc/Dockerfile.example" in release.RUNTIME_INPUTS
    assert "deploy/poc/docker-compose.poc.yaml" in release.RUNTIME_INPUTS
    assert "deploy/poc/postgres-init" in release.RUNTIME_INPUTS
    assert "scripts/prep39083" in release.RUNTIME_INPUTS
    assert "scripts/prep39083_deploy.py" in release.RUNTIME_INPUTS
    assert "deploy/prep39083/env-contract.json" in release.RUNTIME_INPUTS
    assert "deploy/prep39083/release.json" not in release.RUNTIME_INPUTS
    for path in (
        release.BASE_COMPOSE,
        release.OPS_COMPOSE,
        release.PREP_ENV_EXAMPLE,
        release.PREP_OPTIONAL_ENV_EXAMPLE,
        release.ENV_CONTRACT,
        release.PREP_ENTRYPOINT,
        release.DEPLOY_TOOL,
    ):
        assert Path(path).is_file()
    assert release.POSTGRES_INIT.is_dir()
    assert any(release.POSTGRES_INIT.glob("*.sql"))


def test_tracked_examples_are_explicit_gitignore_exceptions() -> None:
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "!deploy/prep39083/.env.prep.example" in ignore
    assert "!deploy/prep39083/.env.prep.optional.example" in ignore
    assert "!deploy/prep39083/.env.ops.example" in ignore
    assert os.fspath(DEPLOYMENT / ".env.prep") not in ignore
