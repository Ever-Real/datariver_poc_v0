from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "scripts" / "prep39083_release.py"
DEPLOYMENT = ROOT / "deploy" / "prep39083"


def _load_module() -> ModuleType:
    sys.path.insert(0, os.fspath(MODULE_PATH.parent))
    try:
        specification = importlib.util.spec_from_file_location(
            "prep39083_release_for_test",
            MODULE_PATH,
        )
        assert specification is not None
        assert specification.loader is not None
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(os.fspath(MODULE_PATH.parent))


release = _load_module()
artifact_contract = sys.modules["prep39083_artifact"]


def _git(
    repository: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed Git executable and isolated test repository.
        ["/usr/bin/git", *arguments],
        cwd=repository,
        check=check,
        capture_output=True,
        text=True,
    )


def test_prep_and_ops_templates_are_isolated_amd64_and_provider_external() -> None:
    prep = (DEPLOYMENT / ".env.prep.example").read_text(encoding="utf-8")
    optional = (DEPLOYMENT / ".env.prep.optional.example").read_text(encoding="utf-8")
    ops = (DEPLOYMENT / ".env.ops.example").read_text(encoding="utf-8")
    contract = (DEPLOYMENT / "env-contract.json").read_text(encoding="utf-8")

    assert "POC_PUBLIC_ORIGIN=" in prep
    assert "POC_INTRANET_HTTP_ALLOWED_CIDRS=" in prep
    assert "HTTP_PROXY=" in prep
    assert "HTTPS_PROXY=" in prep
    assert "NO_PROXY=" in prep
    assert "POC_RUNTIME_HTTP_PROXY=" in prep
    assert "POC_RUNTIME_HTTPS_PROXY=" in prep
    assert "POC_RUNTIME_NO_PROXY=" in prep
    assert "RUNTIME_CA_CERT_FILE=" in prep
    assert "POC_POSTGRES_PASSWORD=" not in prep
    assert "NEO4J_PASSWORD=" not in prep
    assert "POC_MCP_SERVICE_TOKEN=" not in prep
    assert "POC_MCL_KAFKA_BROKERS=" in prep
    assert "AIRFLOW_URL=" not in prep
    assert "MINIO_URL=" not in prep
    assert "AIRFLOW_URL=" in optional
    assert "MINIO_URL=" in optional
    assert "POC_CHANGE_HISTORY_SCHEDULER_ENABLED" not in optional
    assert '"COMPOSE_PROJECT_NAME": "datariver-prep39083"' in contract
    assert '"POC_PORT": "39083"' in contract
    assert '"POC_PLATFORM": "linux/amd64"' in contract
    assert '"POC_SHARED_NETWORK": "datariver-prep39083-services"' in contract
    assert "COMPOSE_PROJECT_NAME=datariver-ops39083" in ops
    assert "POC_INTRANET_HTTP_ALLOWED_CIDRS=" in ops
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
    assert "POC_K9_STUDIO_DATABASE_URL" not in prep
    assert "Topic, cluster identity" in prep
    assert '"CORE_REQUIRED"' in contract
    assert '"FEATURE_REQUIRED"' in contract
    assert '"GENERATED"' in contract
    assert '"FIXED"' in contract
    contract_value = json.loads(contract)
    assert "POC_INTRANET_HTTP_ALLOWED_CIDRS" in contract_value["ownership"]["OPTIONAL"]
    assert "PREP_GLOSSARY_TERM_URN" in contract_value["ownership"]["OPTIONAL"]
    assert "PREP_GLOSSARY_TERM_URN=" in prep
    assert contract_value["ownership"]["FIXED"]["POC_BIND_HOST"] == "0.0.0.0"  # noqa: S104
    assert contract_value["ownership"]["FIXED"]["POC_STATE_BIND_HOST"] == "127.0.0.1"
    assert contract_value["ownership"]["FIXED"]["POC_K9_SCHEDULER_ENABLED"] == "true"
    assert contract_value["ownership"]["FIXED"]["POC_LLM_TIMEOUT_MS"] == "120000"


def test_compose_exposes_only_web_and_host_health_remains_loopback() -> None:
    compose = (ROOT / "deploy" / "poc" / "docker-compose.poc.yaml").read_text(
        encoding="utf-8",
    )
    deployer = (ROOT / "scripts" / "prep39083_deploy.py").read_text(encoding="utf-8")

    assert "${POC_BIND_HOST:-127.0.0.1}:${POC_PORT:-39080}:8080" in compose
    assert compose.count("${POC_STATE_BIND_HOST:-127.0.0.1}:") == 3
    assert "${POC_STATE_BIND_HOST:-127.0.0.1}:${POC_NEO4J_HTTP_PORT" in compose
    assert "${POC_STATE_BIND_HOST:-127.0.0.1}:${POC_POSTGRES_HOST_PORT" in compose
    assert "${POC_STATE_BIND_HOST:-127.0.0.1}:${POC_REDIS_PORT" in compose
    assert 'f"http://127.0.0.1:{release.port}/healthz"' in deployer
    assert '"--noproxy",\n                    "*"' in deployer


def test_ops_override_removes_build_and_forbids_pull() -> None:
    override = (DEPLOYMENT / "docker-compose.ops.yaml").read_text(encoding="utf-8")
    prep_override = (DEPLOYMENT / "docker-compose.artifact.yaml").read_text(encoding="utf-8")

    assert "build: !reset null" in override
    assert override.count("pull_policy: never") == 4
    assert "image:" not in override
    assert "volumes:" not in override
    assert "build: !reset null" in prep_override
    assert "pull_policy: never" in prep_override
    assert "image: datariver-poc:${POC_IMAGE_TAG" in prep_override


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
    assert '"config_schema_version": "PREP39083_ENV_V5"' in source


def test_web_artifact_export_saves_verified_image_once_without_build_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product_sha = "a" * 40
    manifest_digest = f"sha256:{'d' * 64}"
    image = f"datariver-poc:{product_sha}"
    output_dir = tmp_path / "export"
    calls: list[list[str]] = []

    def fake_run(arguments: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        del check
        calls.append(arguments)
        if arguments[:3] == ["docker", "image", "inspect"]:
            document = {
                "Os": "linux",
                "Architecture": "amd64",
                "Descriptor": {
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "digest": manifest_digest,
                    "platform": {"architecture": "amd64", "os": "linux"},
                },
                "Config": {"Labels": {"org.opencontainers.image.revision": product_sha}},
            }
            return subprocess.CompletedProcess(arguments, 0, json.dumps([document]), "")
        assert arguments[:3] == ["docker", "image", "save"]
        archive = Path(arguments[arguments.index("--output") + 1])
        archive.write_bytes(b"exact-image-archive")
        return subprocess.CompletedProcess(arguments, 0, "", "")

    observed = artifact_contract.WebArtifactIdentity(
        product_sha=product_sha,
        artifact_id=f"datariver-poc-{product_sha}-linux-amd64",
        image_reference=image,
        archive_sha256="c" * 64,
        manifest_digest=manifest_digest,
        config_digest=f"sha256:{'e' * 64}",
        platform="linux/amd64",
        oci_revision=product_sha,
    )
    monkeypatch.setattr(release, "exact_product_source", lambda value: value)
    monkeypatch.setattr(release, "run", fake_run)
    monkeypatch.setattr(release, "inspect_web_archive", lambda _path: observed)

    release.export_web_artifact(SimpleNamespace(product_sha=product_sha, output_dir=output_dir))

    manifest = json.loads((output_dir / "artifact-manifest.json").read_text())
    assert manifest["release_json_web_artifact"] == observed.release_mapping()
    assert calls[0] == [
        "docker",
        "image",
        "inspect",
        "--platform",
        "linux/amd64",
        image,
    ]
    assert calls[1][:5] == ["docker", "image", "save", "--platform", "linux/amd64"]
    assert not any("build" in call or "pull" in call or "load" in call for call in calls)


def test_web_artifact_export_fails_closed_when_verified_image_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def absent(arguments: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        del check
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 1, "", "missing")

    monkeypatch.setattr(release, "exact_product_source", lambda value: value)
    monkeypatch.setattr(release, "run", absent)
    with pytest.raises(release.ReleaseError, match="do not rebuild implicitly"):
        release.export_web_artifact(
            SimpleNamespace(product_sha="a" * 40, output_dir=tmp_path / "missing")
        )
    assert len(calls) == 1


def test_product_image_contains_the_runtime_mcl_modules() -> None:
    dockerfile = (ROOT / "deploy" / "poc" / "Dockerfile.example").read_text(encoding="utf-8")
    assert "COPY frontend/poc-mcl-discovery.mjs ./poc-mcl-discovery.mjs" in dockerfile
    assert "COPY frontend/poc-mcl-runtime-failure.mjs ./poc-mcl-runtime-failure.mjs" in dockerfile


def test_product_image_contains_the_airflow_control_runtime_module() -> None:
    dockerfile = (ROOT / "deploy" / "poc" / "Dockerfile.example").read_text(encoding="utf-8")
    assert "COPY frontend/poc-airflow-control.mjs ./poc-airflow-control.mjs" in dockerfile


def test_product_image_contains_the_site_branding_runtime_module() -> None:
    dockerfile = (ROOT / "deploy" / "poc" / "Dockerfile.example").read_text(encoding="utf-8")
    assert "COPY frontend/poc-site-branding.mjs ./poc-site-branding.mjs" in dockerfile


def test_product_image_contains_the_postgres_owned_schema_integrity_module() -> None:
    dockerfile = (ROOT / "deploy" / "poc" / "Dockerfile.example").read_text(encoding="utf-8")
    assert (
        "COPY frontend/poc-postgres-schema-integrity.mjs "
        "./poc-postgres-schema-integrity.mjs"
    ) in dockerfile


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
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "./scripts/prep39083 deploy" in prep
    assert "git pull --ff-only origin main" in prep
    assert "git switch --track -c main origin/main" in prep
    assert "PRODUCT_SHA" in prep and "Operators do not" in prep
    assert "docker compose run --no-deps" in prep
    assert "raw `docker run`" in prep
    assert "docker compose down -v" in prep
    assert "./scripts/prep39083 export" in ops
    assert "Never use `docker compose down -v`" in ops
    assert "docker load --input images.tar" in ops
    assert "up -d --no-build --wait" in ops
    assert "pull_policy: never" in ops
    assert "stage archive at release.json path" in cycle
    assert "web-artifact-export" in cycle
    assert "never builds or pulls an image" in cycle
    assert "archive checksum" in prep
    assert "there is no build or pull fallback" in prep
    assert "DEV never claims PREP or OPS runtime acceptance" in cycle
    assert "Only one materializer" in cycle
    assert "./scripts/prep39083 deploy" in cycle
    assert "ownership fingerprint covers only the generated" in prep
    assert "POC_INTRANET_HTTP_ALLOWED_CIDRS" in prep
    assert "Windows Firewall" in prep and "netsh" in prep
    assert "before reconciling or writing" in prep
    assert "legacy V1 receipt" in prep
    assert "ownership-only V2" in cycle
    assert "git merge-base --is-ancestor origin/main" in cycle
    assert '"$CANDIDATE":refs/heads/main' in cycle
    assert "Development and feature pull requests normally target `dev`" in agents
    assert "PREP39083 updates its release contract only from `origin/main`" in agents
    assert "checksum-pinned OCI/Docker archive" in agents
    assert 'branches: [dev, main, "codex/**"]' in workflow


def test_main_promotion_is_fast_forward_only_and_dev_advancement_is_isolated(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "branch-policy"
    repository.mkdir()
    _git(repository, "init", "--initial-branch=dev")
    _git(repository, "config", "user.name", "DataRiver Test")
    _git(repository, "config", "user.email", "datariver-test@example.invalid")
    policy = repository / "policy.txt"
    policy.write_text("verified handoff\n", encoding="utf-8")
    _git(repository, "add", "policy.txt")
    _git(repository, "commit", "-m", "verified handoff")
    handoff = _git(repository, "rev-parse", "HEAD").stdout.strip()
    _git(repository, "branch", "main", handoff)

    policy.write_text("verified handoff\ndev-only advancement\n", encoding="utf-8")
    _git(repository, "commit", "-am", "dev only")
    dev_head = _git(repository, "rev-parse", "dev").stdout.strip()
    assert dev_head != handoff
    assert _git(repository, "rev-parse", "main").stdout.strip() == handoff
    assert _git(repository, "merge-base", "--is-ancestor", "main", "dev").returncode == 0

    _git(repository, "switch", "--orphan", "unrelated")
    (repository / "unrelated.txt").write_text("unrelated root\n", encoding="utf-8")
    _git(repository, "add", "unrelated.txt")
    _git(repository, "commit", "-m", "unrelated root")
    rejected = _git(
        repository,
        "merge-base",
        "--is-ancestor",
        "main",
        "unrelated",
        check=False,
    )
    assert rejected.returncode != 0
    assert _git(repository, "rev-parse", "main").stdout.strip() == handoff


def test_smoke_uses_opaque_login_and_checks_managed_graphs() -> None:
    smoke = (ROOT / "scripts" / "smoke_prep39083.mjs").read_text(encoding="utf-8")
    compose = (ROOT / "deploy" / "poc" / "docker-compose.poc.yaml").read_text(
        encoding="utf-8",
    )
    poc_example = (ROOT / "deploy" / "poc" / ".env.example").read_text(encoding="utf-8")
    ops_example = (DEPLOYMENT / ".env.ops.example").read_text(encoding="utf-8")

    assert "/auth/login" in smoke
    assert "/auth/logout" in smoke
    assert "/poc-api/datahub/catalog?limit=1" in smoke
    assert "/poc-api/knowledge/managed-assets" in smoke
    assert "LINEAGE" in smoke
    assert "METADATA_MASTER" in smoke
    assert "semantic_index_status" in smoke
    assert "selected_mode !== 'GENERAL'" in smoke
    assert "atomicJson(output" in smoke
    assert "password }" in smoke
    assert "console.log(password" not in smoke
    assert "--k9-mode" in smoke
    assert "--request-origin" in smoke
    assert "requestOrigin" in smoke
    assert "PREP_SMOKE_ADMIN_ORIGIN_FAILED" in smoke
    assert "PREP_SMOKE_K9_SOURCE_DRIFT_RETRY_EXHAUSTED" in smoke
    assert "k9Mode === 'REQUIRED'" in smoke
    assert "'DEFERRED'" in smoke
    assert "PREP_SMOKE_GENERAL_PROVIDER_FAILED" in smoke
    assert "PREP_SMOKE_GENERAL_PROVIDER_TIMEOUT_FAILED" in smoke
    assert "--failure-output" in smoke
    assert "POC_LLM_TIMEOUT_MS: ${POC_LLM_TIMEOUT_MS:-120000}" in compose
    assert "POC_LLM_TIMEOUT_MS=120000" in poc_example
    assert "POC_LLM_TIMEOUT_MS=120000" in ops_example


def test_runtime_input_boundary_excludes_handoff_only_artifacts() -> None:
    assert "frontend" in release.RUNTIME_INPUTS
    assert "deploy/poc/Dockerfile.example" in release.RUNTIME_INPUTS
    assert "deploy/poc/docker-compose.poc.yaml" in release.RUNTIME_INPUTS
    assert "deploy/poc/postgres-init" in release.RUNTIME_INPUTS
    assert "scripts/prep39083" in release.RUNTIME_INPUTS
    assert "scripts/prep39083_deploy.py" in release.RUNTIME_INPUTS
    assert "scripts/prep39083_artifact.py" in release.RUNTIME_INPUTS
    assert "deploy/prep39083/docker-compose.artifact.yaml" in release.RUNTIME_INPUTS
    assert "deploy/prep39083/env-contract.json" in release.RUNTIME_INPUTS
    assert "deploy/prep39083/release.json" not in release.RUNTIME_INPUTS
    for path in (
        release.BASE_COMPOSE,
        release.OPS_COMPOSE,
        release.PREP_ARTIFACT_COMPOSE,
        release.PREP_ENV_EXAMPLE,
        release.PREP_OPTIONAL_ENV_EXAMPLE,
        release.ENV_CONTRACT,
        release.PREP_ENTRYPOINT,
        release.DEPLOY_TOOL,
        release.ARTIFACT_TOOL,
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
