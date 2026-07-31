from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from uuid import UUID

import pytest

from datariver.bootstrap import (
    LOCAL_DEMO_IDENTITIES,
    LOCAL_KNOWLEDGE_INGESTION_EXTERNAL_SUBJECT,
    LOCAL_KNOWLEDGE_INGESTION_SUBJECT_ID,
    _local_demo_identities,
    _local_human_membership_attributes,
    _local_service_identities,
)
from datariver.domain.authz import Action


def _copy_bootstrap_fixture(source_root: Path, target_root: Path) -> None:
    (target_root / "scripts").mkdir(parents=True)
    (target_root / "infra/keycloak").mkdir(parents=True)
    shutil.copy2(source_root / "scripts/bootstrap.sh", target_root / "scripts/bootstrap.sh")
    shutil.copy2(source_root / ".env.example", target_root / ".env.example")
    shutil.copy2(
        source_root / "infra/keycloak/datariver-realm.template.json",
        target_root / "infra/keycloak/datariver-realm.template.json",
    )


def test_bash_and_powershell_bootstrap_keep_host_secret_files_owner_only() -> None:
    root = Path(__file__).resolve().parents[3]
    shell = (root / "scripts/bootstrap.sh").read_text(encoding="utf-8")
    powershell = (root / "scripts/bootstrap.ps1").read_text(encoding="utf-8")
    writer = powershell[
        powershell.index("function Write-Secret") : powershell.index("function Get-OrCreateSecret")
    ]

    assert "umask 077" in shell
    assert "[IO.UnixFileMode]::UserRead" in writer
    assert "[IO.UnixFileMode]::UserWrite" in writer
    assert "[IO.UnixFileMode]::GroupRead" not in writer
    assert "[IO.UnixFileMode]::OtherRead" not in writer
    assert "intranet_llm_reranker_api_key" in powershell
    assert "SetAccessRuleProtection($true, $false)" in powershell
    assert 'SecurityIdentifier]::new("S-1-5-18")' in powershell
    assert "Set-OwnerOnlyWindowsAcl -Path $secretsDirectory -Directory" in powershell
    assert "Set-OwnerOnlyWindowsAcl -Path $temporaryPath" in writer
    assert "Set-OwnerOnlyWindowsAcl -Path $realmPath" in powershell


def test_local_demo_identities_match_keycloak_and_use_balanced_human_roles(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[3]
    realm = json.loads(
        (root / "infra/keycloak/datariver-realm.template.json").read_text(encoding="utf-8")
    )
    users_by_id = {user["id"]: user for user in realm["users"]}

    assert {demo.job_function for demo in LOCAL_DEMO_IDENTITIES} == {
        "DATA_ANALYST",
        "DATA_ENGINEER",
        "DATA_STEWARD",
    }
    assert len({demo.subject_id for demo in LOCAL_DEMO_IDENTITIES}) == 3
    assert len({demo.external_subject for demo in LOCAL_DEMO_IDENTITIES}) == 3
    for demo in LOCAL_DEMO_IDENTITIES:
        user = users_by_id[demo.external_subject]
        assert user["enabled"] is True
        assert user["email"] == demo.email
        assert user["requiredActions"] == ["UPDATE_PASSWORD"]
        assert user["credentials"] == [
            {
                "type": "password",
                "value": "__DEMO_PASSWORD__",
                "temporary": True,
            }
        ]
        assert demo.allowed_actions
    actions_by_username = {
        demo.username: frozenset(demo.allowed_actions) for demo in LOCAL_DEMO_IDENTITIES
    }
    assert Action.CHAT_QUERY in actions_by_username["minjae.oh"]
    assert Action.CHAT_QUERY not in actions_by_username["jihoon.choi"]
    assert Action.CHAT_QUERY in actions_by_username["sua.han"]
    assert {
        Action.ATTACHMENT_DOWNLOAD,
        Action.GOVERNANCE_DOCUMENT_READ,
        Action.GOVERNANCE_DOCUMENT_CREATE,
        Action.GOVERNANCE_DOCUMENT_EDIT,
        Action.GOVERNANCE_DOCUMENT_REVIEW,
        Action.GOVERNANCE_DOCUMENT_PUBLISH,
        Action.GOVERNANCE_TEMPLATE_READ,
        Action.GOVERNANCE_KNOWLEDGE_READ,
    }.issubset(actions_by_username["sua.han"])

    state_path = tmp_path / "local-demo-identities.json"
    provider_subjects = {
        "jihoon.choi": "00000000-0000-4000-8000-000000000205",
        "sua.han": "00000000-0000-4000-8000-000000000206",
        "minjae.oh": "00000000-0000-4000-8000-000000000207",
    }
    state_path.write_text(json.dumps(provider_subjects), encoding="utf-8")

    resolved = _local_demo_identities(state_path)

    assert {demo.username: demo.external_subject for demo in resolved} == provider_subjects
    state_path.write_text(
        json.dumps(dict.fromkeys(provider_subjects, provider_subjects["jihoon.choi"])),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="state file is invalid"):
        _local_demo_identities(state_path)


def test_local_knowledge_ingestion_service_has_one_exact_machine_envelope() -> None:
    services = {identity.subject_id: identity for identity in _local_service_identities()}
    ingestion = services[LOCAL_KNOWLEDGE_INGESTION_SUBJECT_ID]

    assert ingestion.external_subject == LOCAL_KNOWLEDGE_INGESTION_EXTERNAL_SUBJECT
    assert ingestion.groups == (
        "service-accounts",
        "knowledge-ingestion-workers",
    )
    assert ingestion.allowed_actions == (Action.KG_INGEST_EXECUTE,)
    assert ingestion.bootstrap_contract == "local-knowledge-studio-ingestion-service-v1"


def test_local_human_memberships_select_the_single_workspace_by_default() -> None:
    domain_id = UUID("3e43b772-b1f5-747c-52c0-bd1c154e595e")
    attributes = _local_human_membership_attributes(
        groups=("data-analysts",),
        allowed_actions=(Action.CATALOG_READ,),
        bootstrap="test-local-identity",
        allowed_domain_ids=(domain_id,),
    )

    assert attributes["default_workspace"] is True
    assert attributes["groups"] == ["data-analysts"]
    assert attributes["allowed_actions"] == [Action.CATALOG_READ.value]
    assert attributes["allowed_domain_ids"] == [str(domain_id)]


def test_bootstrap_migrates_demo_identity_state_out_of_keycloak_import(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[3]
    isolated_root = tmp_path / "repo"
    _copy_bootstrap_fixture(root, isolated_root)
    legacy_state = isolated_root / "runtime/keycloak/local-demo-identities.json"
    legacy_state.parent.mkdir(parents=True)
    legacy_document = json.dumps(
        {
            "jihoon.choi": "00000000-0000-4000-8000-000000000205",
            "sua.han": "00000000-0000-4000-8000-000000000206",
            "minjae.oh": "00000000-0000-4000-8000-000000000207",
        }
    )
    legacy_state.write_text(legacy_document, encoding="utf-8")
    approved_token = isolated_root / "approved-datahub-token"
    approved_token.write_text("test-only-datahub-token", encoding="utf-8")

    result = subprocess.run(  # noqa: S603 - copied repository script is trusted.
        [
            str(isolated_root / "scripts/bootstrap.sh"),
            "--datahub-token-file",
            str(approved_token),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    migrated_state = isolated_root / "runtime/identity/local-demo-identities.json"
    assert result.returncode == 0, result.stderr
    assert not legacy_state.exists()
    assert migrated_state.read_text(encoding="utf-8") == legacy_document
    assert migrated_state.stat().st_mode & 0o777 == 0o600


def test_bootstrap_backfills_required_non_secret_settings_in_legacy_env(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[3]
    isolated_root = tmp_path / "repo"
    _copy_bootstrap_fixture(root, isolated_root)
    env_path = isolated_root / ".env.wsl-intranet-development"
    required_names = {
        "OIDC_AUDIENCE",
        "DATAHUB_EXPECTED_VERSION",
        "S3_BUCKET_QUARANTINE",
        "S3_BUCKET_ACCEPTED",
    }
    legacy_lines = [
        line
        for line in (isolated_root / ".env.example").read_text(encoding="utf-8").splitlines()
        if line.split("=", 1)[0] not in required_names
    ]
    legacy_lines.append("OIDC_AUDIENCE=operator-selected-audience")
    env_path.write_text("\n".join(legacy_lines) + "\n", encoding="utf-8")
    approved_token = isolated_root / "approved-datahub-token"
    approved_token.write_text("test-only-datahub-token", encoding="utf-8")

    result = subprocess.run(  # noqa: S603 - copied repository script is trusted.
        [
            str(isolated_root / "scripts/bootstrap.sh"),
            "--env-file",
            env_path.name,
            "--datahub-token-file",
            str(approved_token),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    values = dict(
        line.split("=", 1)
        for line in env_path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )
    assert values["OIDC_AUDIENCE"] == "operator-selected-audience"
    assert values["DATAHUB_EXPECTED_VERSION"] == "v1.6.0"
    assert values["S3_BUCKET_QUARANTINE"] == "datariver-quarantine"
    assert values["S3_BUCKET_ACCEPTED"] == "datariver-accepted"
    assert "Added required environment setting from .env.example: OIDC_AUDIENCE" not in (
        result.stdout
    )
    assert "Added required environment setting from .env.example: DATAHUB_EXPECTED_VERSION" in (
        result.stdout
    )


def test_bootstrap_backfills_existing_env_before_external_token_preflight(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[3]
    isolated_root = tmp_path / "repo"
    _copy_bootstrap_fixture(root, isolated_root)
    env_path = isolated_root / ".env.wsl-intranet-development"
    required_names = {
        "OIDC_AUDIENCE",
        "DATAHUB_EXPECTED_VERSION",
        "S3_BUCKET_QUARANTINE",
        "S3_BUCKET_ACCEPTED",
    }
    env_path.write_text(
        "\n".join(
            line
            for line in (isolated_root / ".env.example").read_text(encoding="utf-8").splitlines()
            if line.split("=", 1)[0] not in required_names
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(  # noqa: S603 - copied repository script is trusted.
        [
            str(isolated_root / "scripts/bootstrap.sh"),
            "--env-file",
            env_path.name,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "DataHub token file is required" in result.stderr
    values = dict(
        line.split("=", 1)
        for line in env_path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )
    assert values["OIDC_AUDIENCE"] == "datariver-api"
    assert values["DATAHUB_EXPECTED_VERSION"] == "v1.6.0"
    assert values["S3_BUCKET_QUARANTINE"] == "datariver-quarantine"
    assert values["S3_BUCKET_ACCEPTED"] == "datariver-accepted"


def test_knowledge_source_worker_bootstrap_is_explicit_and_requires_inference_pair(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[3]
    shell = (root / "scripts/bootstrap.sh").read_text(encoding="utf-8")
    powershell = (root / "scripts/bootstrap.ps1").read_text(encoding="utf-8")

    assert "--enable-knowledge-source-worker" in shell
    assert "knowledge_inference_is_ready" in shell
    assert "[switch]$EnableKnowledgeSourceWorker" in powershell
    assert "Test-KnowledgeInferenceReady" in powershell
    for source in (shell, powershell):
        assert "LOCAL_OLLAMA_CHAT_ENABLED" in source
        assert "LOCAL_OLLAMA_EMBEDDING_ENABLED" in source
        assert "INTRANET_OPENAI_COMPATIBLE_CHAT_ENABLED" in source
        assert "INTRANET_OPENAI_COMPATIBLE_EMBEDDING_ENABLED" in source
        assert "KNOWLEDGE_SOURCE_WORKER_ENABLED" in source

    isolated_root = tmp_path / "repo"
    (isolated_root / "scripts").mkdir(parents=True)
    shutil.copy2(root / "scripts/bootstrap.sh", isolated_root / "scripts/bootstrap.sh")
    shutil.copy2(root / ".env.example", isolated_root / ".env.example")
    inference_token_file = tmp_path / "inference-datahub-token"
    inference_token_file.write_text("test-inference-token", encoding="utf-8")
    result = subprocess.run(  # noqa: S603 - copied repository script is trusted.
        [
            str(isolated_root / "scripts/bootstrap.sh"),
            "--enable-knowledge-source-worker",
            "--datahub-token-file",
            str(inference_token_file),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "requires one complete Chat+Embedding pair" in result.stderr
    assert not (isolated_root / "secrets").exists()

    wsl_env = (
        (isolated_root / ".env")
        .read_text(encoding="utf-8")
        .replace(
            "LOCAL_OLLAMA_CHAT_ENABLED=false",
            "\n".join(
                (
                    "LOCAL_OLLAMA_CHAT_ENABLED=true",
                    "LOCAL_OLLAMA_CHAT_BASE_URL=http://host.docker.internal:11434/v1",
                    "LOCAL_OLLAMA_CHAT_MODEL=chat-model",
                )
            ),
        )
        .replace(
            "LOCAL_OLLAMA_EMBEDDING_ENABLED=false",
            "\n".join(
                (
                    "LOCAL_OLLAMA_EMBEDDING_ENABLED=true",
                    "LOCAL_OLLAMA_EMBEDDING_BASE_URL=http://host.docker.internal:11434/v1",
                    "LOCAL_OLLAMA_EMBEDDING_MODEL=embedding-model",
                )
            ),
        )
    )
    (isolated_root / ".env").write_text(wsl_env, encoding="utf-8")
    wsl_result = subprocess.run(  # noqa: S603 - copied repository script is trusted.
        [
            str(isolated_root / "scripts/bootstrap.sh"),
            "--wsl-preparation",
            "--enable-knowledge-source-worker",
            "--datahub-token-file",
            str(inference_token_file),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert wsl_result.returncode == 2
    assert "requires one complete Chat+Embedding pair" in wsl_result.stderr
    assert not (isolated_root / "secrets").exists()

    configured_root = tmp_path / "configured-repo"
    (configured_root / "scripts").mkdir(parents=True)
    (configured_root / "infra/keycloak").mkdir(parents=True)
    shutil.copy2(root / "scripts/bootstrap.sh", configured_root / "scripts/bootstrap.sh")
    shutil.copy2(
        root / "infra/keycloak/datariver-realm.template.json",
        configured_root / "infra/keycloak/datariver-realm.template.json",
    )
    configured_env = (root / ".env.example").read_text(encoding="utf-8")
    configured_env = configured_env.replace(
        "LOCAL_OLLAMA_CHAT_ENABLED=false",
        "\n".join(
            (
                "LOCAL_OLLAMA_CHAT_ENABLED=true",
                "LOCAL_OLLAMA_CHAT_BASE_URL=http://host.docker.internal:11434/v1",
                "LOCAL_OLLAMA_CHAT_MODEL=chat-model",
            )
        ),
    ).replace(
        "LOCAL_OLLAMA_EMBEDDING_ENABLED=false",
        "\n".join(
            (
                "LOCAL_OLLAMA_EMBEDDING_ENABLED=true",
                "LOCAL_OLLAMA_EMBEDDING_BASE_URL=http://host.docker.internal:11434/v1",
                "LOCAL_OLLAMA_EMBEDDING_MODEL=embedding-model",
            )
        ),
    )
    (configured_root / ".env.example").write_text(configured_env, encoding="utf-8")
    (configured_root / "approved-datahub-token").write_text(
        "test-only-datahub-token",
        encoding="utf-8",
    )
    configured_result = subprocess.run(  # noqa: S603 - copied repository script is trusted.
        [
            str(configured_root / "scripts/bootstrap.sh"),
            "--enable-knowledge-source-worker",
            "--datahub-token-file",
            str(configured_root / "approved-datahub-token"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert configured_result.returncode == 0, configured_result.stderr
    output_env = (configured_root / ".env").read_text(encoding="utf-8")
    assert "KNOWLEDGE_SOURCE_WORKER_ENABLED=true" in output_env
    assert (
        "KNOWLEDGE_DATABASE_URL=postgresql+asyncpg://datariver_knowledge@postgres:5432/datariver"
    ) in output_env


def test_blank_wsl_bootstrap_fails_before_creating_any_state(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    isolated_root = tmp_path / "repo"
    _copy_bootstrap_fixture(root, isolated_root)

    result = subprocess.run(  # noqa: S603 - copied repository script is trusted.
        [
            str(isolated_root / "scripts/bootstrap.sh"),
            "--env-file",
            ".env.wsl-preparation",
            "--wsl-preparation",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "datahub token file" in result.stderr.lower()
    assert not (isolated_root / ".env.wsl-preparation").exists()
    assert not (isolated_root / "secrets").exists()
    assert not (isolated_root / "runtime").exists()


def test_portable_bootstrap_keeps_inference_disabled_and_uses_generic_ports(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[3]
    isolated_root = tmp_path / "repo"
    _copy_bootstrap_fixture(root, isolated_root)
    token = isolated_root / "approved-datahub-token"
    token.write_text("portable-test-token", encoding="utf-8")

    result = subprocess.run(  # noqa: S603 - copied repository script is trusted.
        [
            str(isolated_root / "scripts/bootstrap.sh"),
            "--env-file",
            ".env.portable-development",
            "--portable-development",
            "--datahub-token-file",
            str(token),
            "--datahub-base-url",
            "https://datahub.example.internal",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    values = (isolated_root / ".env.portable-development").read_text(encoding="utf-8")
    assert "APP_PUBLIC_ORIGIN=http://localhost:8080" in values
    assert "API_PORT=8000" in values
    assert "WEB_PORT=8080" in values
    assert "DATAHUB_BASE_URL=https://datahub.example.internal" in values
    assert "LOCAL_OLLAMA_CHAT_ENABLED=false" in values
    assert "LOCAL_OLLAMA_EMBEDDING_ENABLED=false" in values
    assert "LOCAL_LLAMA_CPP_RERANKER_ENABLED=false" in values
    assert "NEO4J_PROJECTION_ENABLED=false" in values
    assert "KNOWLEDGE_PIPELINE_ENABLED=false" in values
    assert "WORKSPACE_SELECTION_ENABLED=false" in values
    assert "SYSTEM_CONFIGURATION_RUNTIME_ACTIVATION_ENABLED=false" in values
    assert "SYSTEM_CONFIGURATION_RUNTIME_ACTIVATION_ENABLED=true" not in values
    assert "DATARIVER_OPERATOR_PROFILE=portable-development" in values


def test_linux_intranet_source_host_bootstrap_persists_distinct_https_origins(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[3]
    isolated_root = tmp_path / "repo"
    binary_directory = tmp_path / "bin"
    _copy_bootstrap_fixture(root, isolated_root)
    binary_directory.mkdir()
    fake_uname = binary_directory / "uname"
    fake_uname.write_text("#!/usr/bin/env sh\nprintf 'Linux\\n'\n", encoding="utf-8")
    fake_uname.chmod(0o755)
    token = isolated_root / "approved-datahub-token"
    token.write_text("intranet-source-host-test-token", encoding="utf-8")

    result = subprocess.run(  # noqa: S603 - copied repository script is trusted.
        [
            str(isolated_root / "scripts/bootstrap.sh"),
            "--env-file",
            ".env.wsl-intranet-development",
            "--host-development",
            "--intranet-source-host",
            "--web-public-origin",
            "https://datariver-prep.example.internal",
            "--oidc-public-origin",
            "https://identity-prep.example.internal",
            "--datahub-token-file",
            str(token),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{binary_directory}:{os.environ['PATH']}",
        },
    )

    assert result.returncode == 0, result.stderr
    values = (isolated_root / ".env.wsl-intranet-development").read_text(encoding="utf-8")
    assert "APP_ENV=development" in values
    assert "DATARIVER_OPERATOR_PROFILE=wsl-source-host" in values
    assert "INTRANET_SOURCE_HOST_ENABLED=true" in values
    assert "WORKSPACE_SELECTION_ENABLED=false" in values
    assert "APP_PUBLIC_ORIGIN=https://datariver-prep.example.internal" in values
    assert "OIDC_PUBLIC_ORIGIN=https://identity-prep.example.internal" in values
    assert (
        "OIDC_PUBLIC_AUTHORITY=https://identity-prep.example.internal/realms/datariver"
    ) in values
    assert "APP_CORS_ORIGINS=https://datariver-prep.example.internal" in values
    assert "REDIS_CACHE_URL=redis://127.0.0.1:6379/0" in values
    assert "REDIS_DELIVERY_URL=redis://127.0.0.1:6380/0" in values
    realm = json.loads(
        (isolated_root / "runtime/keycloak/datariver-realm.json").read_text(encoding="utf-8")
    )
    web_client = next(
        client for client in realm["clients"] if client.get("clientId") == "datariver-web"
    )
    assert web_client["redirectUris"] == ["https://datariver-prep.example.internal/*"]
    assert web_client["webOrigins"] == ["https://datariver-prep.example.internal"]


def test_mac_bootstrap_never_selects_or_creates_a_local_model(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    isolated_root = tmp_path / "repo"
    _copy_bootstrap_fixture(root, isolated_root)

    result = subprocess.run(  # noqa: S603 - copied repository script is trusted.
        [
            str(isolated_root / "scripts/bootstrap.sh"),
            "--env-file",
            ".env.mac-development",
            "--mac-development",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    values = (isolated_root / ".env.mac-development").read_text(encoding="utf-8")
    assert "LOCAL_OLLAMA_CHAT_ENABLED=false" in values
    assert "LOCAL_OLLAMA_EMBEDDING_ENABLED=false" in values
    assert "LOCAL_LLAMA_CPP_RERANKER_ENABLED=false" in values
    assert not any(
        line.startswith(
            (
                "LOCAL_OLLAMA_CHAT_MODEL=",
                "LOCAL_OLLAMA_EMBEDDING_MODEL=",
                "LOCAL_LLAMA_CPP_RERANKER_MODEL=",
            )
        )
        for line in values.splitlines()
    )
    source = (root / "scripts/bootstrap.sh").read_text(encoding="utf-8")
    assert "datariver-gemma4-dev" not in source
    assert "bge-m3:latest" not in source
    assert "qllama/bge-reranker" not in source


def test_bootstrap_rejects_conflicting_portable_and_host_specific_profiles(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[3]
    isolated_root = tmp_path / "repo"
    _copy_bootstrap_fixture(root, isolated_root)

    result = subprocess.run(  # noqa: S603 - copied repository script is trusted.
        [
            str(isolated_root / "scripts/bootstrap.sh"),
            "--portable-development",
            "--mac-development",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "mutually exclusive" in result.stderr
    assert not (isolated_root / ".env").exists()
    assert not (isolated_root / "secrets").exists()


def test_wsl_bootstrap_preserves_preinstalled_token_without_exposing_it(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[3]
    isolated_root = tmp_path / "repo"
    _copy_bootstrap_fixture(root, isolated_root)
    token = "approved-private-token-value"
    token_path = isolated_root / "secrets/datahub_token"
    token_path.parent.mkdir(mode=0o700)
    token_path.write_text(token, encoding="utf-8")
    token_path.chmod(0o600)

    result = subprocess.run(  # noqa: S603 - copied repository script is trusted.
        [
            str(isolated_root / "scripts/bootstrap.sh"),
            "--env-file",
            ".env.wsl-preparation",
            "--wsl-preparation",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert token_path.read_text(encoding="utf-8") == token
    assert token not in result.stdout
    assert token not in result.stderr
    environment_path = isolated_root / ".env.wsl-preparation"
    assert environment_path.is_file()
    environment = environment_path.read_text(encoding="utf-8")
    for expected in (
        "DATARIVER_OPERATOR_PROFILE=wsl-preparation",
        "AIRFLOW_SOURCE_API_BRIDGE_ENABLED=false",
        "SYSTEM_CONFIGURATION_RUNTIME_ACTIVATION_ENABLED=false",
        "NEO4J_IMAGE=neo4j:2026.06.0",
        "NEO4J_PROJECTION_ENABLED=false",
        "NEO4J_SOURCE_HOST_ENABLED=false",
        "NEO4J_URI=bolt://neo4j:7687",
        "NEO4J_ALLOWED_HOSTS=neo4j",
        "NEO4J_AUTH_SECRET_REF=file:/run/secrets/neo4j_auth",
        "KNOWLEDGE_SOURCE_WORKER_ENABLED=false",
        "WORKSPACE_SELECTION_ENABLED=false",
    ):
        assert expected in environment

    source_environment_path = isolated_root / ".env.wsl-intranet-development"
    shutil.copy2(environment_path, source_environment_path)
    source_environment_path.write_text(
        source_environment_path.read_text(encoding="utf-8").replace(
            "NEO4J_URI=bolt://neo4j:7687",
            "NEO4J_URI=bolt://neo4j:17687",
        ),
        encoding="utf-8",
    )
    source_result = subprocess.run(  # noqa: S603 - copied repository script is trusted.
        [
            str(isolated_root / "scripts/bootstrap.sh"),
            "--env-file",
            ".env.wsl-intranet-development",
            "--host-development",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert source_result.returncode == 0, source_result.stderr
    source_environment = source_environment_path.read_text(encoding="utf-8")
    for expected in (
        "NEO4J_SOURCE_HOST_ENABLED=true",
        "NEO4J_URI=bolt://127.0.0.1:17687",
        "NEO4J_ALLOWED_HOSTS=127.0.0.1",
    ):
        assert expected in source_environment
    active_keys = [
        line.partition("=")[0]
        for line in source_environment.splitlines()
        if line and not line.startswith("#") and "=" in line
    ]
    assert len(active_keys) == len(set(active_keys))


def test_bootstrap_accepts_a_token_file_path_but_rejects_a_token_value_argument(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[3]
    source_root = tmp_path / "source-repo"
    _copy_bootstrap_fixture(root, source_root)
    token = "approved-token-from-file"
    approved_token = tmp_path / "approved-datahub-token"
    approved_token.write_text(token, encoding="utf-8")
    approved_token.chmod(0o600)

    accepted = subprocess.run(  # noqa: S603 - copied repository script is trusted.
        [
            str(source_root / "scripts/bootstrap.sh"),
            "--env-file",
            ".env.wsl-preparation",
            "--wsl-preparation",
            "--datahub-token-file",
            str(approved_token),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert accepted.returncode == 0, accepted.stderr
    assert (source_root / "secrets/datahub_token").read_text(encoding="utf-8") == token
    assert token not in accepted.stdout
    assert token not in accepted.stderr

    rejected_root = tmp_path / "rejected-repo"
    _copy_bootstrap_fixture(root, rejected_root)
    rejected = subprocess.run(  # noqa: S603 - copied repository script is trusted.
        [str(rejected_root / "scripts/bootstrap.sh"), token],
        check=False,
        capture_output=True,
        text=True,
    )

    assert rejected.returncode == 2
    assert "unexpected argument" in rejected.stderr
    assert token not in rejected.stdout
    assert token not in rejected.stderr
    assert not (rejected_root / ".env").exists()
    assert not (rejected_root / "secrets").exists()


def test_bootstrap_preserves_an_explicitly_selected_installed_token(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[3]
    isolated_root = tmp_path / "repo"
    _copy_bootstrap_fixture(root, isolated_root)
    token_path = isolated_root / "secrets/datahub_token"
    token_path.parent.mkdir(mode=0o700)
    token_path.write_text("installed-token", encoding="utf-8")
    token_path.chmod(0o600)

    result = subprocess.run(  # noqa: S603 - copied repository script is trusted.
        [
            str(isolated_root / "scripts/bootstrap.sh"),
            "--env-file",
            ".env.wsl-preparation",
            "--wsl-preparation",
            "--datahub-token-file",
            str(token_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert token_path.read_text(encoding="utf-8") == "installed-token"
    assert (isolated_root / ".env.wsl-preparation").is_file()


def test_bootstrap_rejects_token_symlinks_before_mutation(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    isolated_root = tmp_path / "repo"
    _copy_bootstrap_fixture(root, isolated_root)
    external_token = tmp_path / "external-datahub-token"
    external_token.write_text("external-token", encoding="utf-8")
    external_token.chmod(0o600)
    token_path = isolated_root / "secrets/datahub_token"
    token_path.parent.mkdir(mode=0o700)
    token_path.symlink_to(external_token)

    result = subprocess.run(  # noqa: S603 - copied repository script is trusted.
        [
            str(isolated_root / "scripts/bootstrap.sh"),
            "--env-file",
            ".env.wsl-preparation",
            "--wsl-preparation",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "symbolic links" in result.stderr
    assert not (isolated_root / ".env.wsl-preparation").exists()
    assert not (isolated_root / "runtime").exists()
    assert external_token.stat().st_mode & 0o777 == 0o600
    assert external_token.read_text(encoding="utf-8") == "external-token"

    hidden_link_root = tmp_path / "hidden-link-repo"
    _copy_bootstrap_fixture(root, hidden_link_root)
    hidden_secrets = hidden_link_root / "secrets"
    hidden_secrets.mkdir(mode=0o700)
    (hidden_secrets / ".hidden-approved-link").symlink_to(external_token)
    hidden_result = subprocess.run(  # noqa: S603 - copied repository script is trusted.
        [
            str(hidden_link_root / "scripts/bootstrap.sh"),
            "--datahub-token-file",
            str(external_token),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert hidden_result.returncode == 2
    assert not (hidden_link_root / ".env").exists()
    assert not (hidden_link_root / "runtime").exists()

    source_root = tmp_path / "source-repo"
    _copy_bootstrap_fixture(root, source_root)
    approved_link = tmp_path / "approved-link"
    approved_link.symlink_to(external_token)
    source_result = subprocess.run(  # noqa: S603 - copied repository script is trusted.
        [
            str(source_root / "scripts/bootstrap.sh"),
            "--datahub-token-file",
            str(approved_link),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert source_result.returncode == 2
    assert not (source_root / ".env").exists()
    assert not (source_root / "secrets").exists()
    assert not (source_root / "runtime").exists()

    runtime_root = tmp_path / "runtime-repo"
    _copy_bootstrap_fixture(root, runtime_root)
    approved_token = tmp_path / "approved-runtime-token"
    approved_token.write_text("approved-token", encoding="utf-8")
    external_runtime = tmp_path / "external-runtime"
    external_runtime.mkdir()
    (runtime_root / "runtime").symlink_to(external_runtime, target_is_directory=True)
    runtime_result = subprocess.run(  # noqa: S603 - copied repository script is trusted.
        [
            str(runtime_root / "scripts/bootstrap.sh"),
            "--datahub-token-file",
            str(approved_token),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert runtime_result.returncode == 2
    assert "symbolic links" in runtime_result.stderr
    assert not (runtime_root / ".env").exists()
    assert not (runtime_root / "secrets").exists()
    assert list(external_runtime.iterdir()) == []


def test_compose_wrapper_creates_connector_network_before_compose_and_is_idempotent(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[3]
    isolated_root = tmp_path / "repo"
    bin_dir = tmp_path / "bin"
    state_file = tmp_path / "network-created"
    log_file = tmp_path / "docker.log"
    (isolated_root / "scripts").mkdir(parents=True)
    bin_dir.mkdir()
    shutil.copy2(root / "scripts/compose.sh", isolated_root / "scripts/compose.sh")
    shutil.copy2(
        root / "scripts/ensure_connector_network.sh",
        isolated_root / "scripts/ensure_connector_network.sh",
    )
    (isolated_root / ".env").write_text(
        "DATARIVER_CONNECTOR_NETWORK=datariver-test-connectors\n",
        encoding="utf-8",
    )
    fake_docker = bin_dir / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env sh
set -eu
printf '%s\\n' "$*" >> "$DOCKER_LOG"
if [ "$1" = network ] && [ "$2" = inspect ]; then
  [ -f "$DOCKER_NETWORK_STATE" ]
elif [ "$1" = network ] && [ "$2" = create ]; then
  : > "$DOCKER_NETWORK_STATE"
elif [ "$1" = compose ]; then
  exit 0
else
  exit 97
fi
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "DOCKER_LOG": str(log_file),
        "DOCKER_NETWORK_STATE": str(state_file),
    }
    command = [str(isolated_root / "scripts/compose.sh"), "up", "-d", "postgres"]

    first = subprocess.run(  # noqa: S603 - copied repository script is trusted.
        command,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    second = subprocess.run(  # noqa: S603 - copied repository script is trusted.
        command,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert log_file.read_text(encoding="utf-8").splitlines() == [
        "network inspect datariver-test-connectors",
        "network create --driver bridge datariver-test-connectors",
        f"compose --env-file {isolated_root / '.env'} up -d postgres",
        "network inspect datariver-test-connectors",
        f"compose --env-file {isolated_root / '.env'} up -d postgres",
    ]


def test_invalid_connector_network_fails_before_any_docker_command(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    isolated_root = tmp_path / "repo"
    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "docker.log"
    (isolated_root / "scripts").mkdir(parents=True)
    bin_dir.mkdir()
    shutil.copy2(root / "scripts/compose.sh", isolated_root / "scripts/compose.sh")
    shutil.copy2(
        root / "scripts/ensure_connector_network.sh",
        isolated_root / "scripts/ensure_connector_network.sh",
    )
    fake_docker = bin_dir / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env sh
printf '%s\\n' "$*" >> "$DOCKER_LOG"
exit 0
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    for network_name in ("", "invalid/network", "--help", ".", ".."):
        (isolated_root / ".env").write_text(
            f"DATARIVER_CONNECTOR_NETWORK={network_name}\n",
            encoding="utf-8",
        )
        for compose_arguments in (("config", "--quiet"), ("up", "-d", "postgres")):
            result = subprocess.run(  # noqa: S603 - copied repository script is trusted.
                [str(isolated_root / "scripts/compose.sh"), *compose_arguments],
                check=False,
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "PATH": f"{bin_dir}:{os.environ['PATH']}",
                    "DOCKER_LOG": str(log_file),
                },
            )

            assert result.returncode == 2
            assert "unsupported characters" in result.stderr
            assert not log_file.exists()


def test_valid_config_does_not_inspect_or_create_the_network(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    isolated_root = tmp_path / "repo"
    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "docker.log"
    (isolated_root / "scripts").mkdir(parents=True)
    bin_dir.mkdir()
    shutil.copy2(root / "scripts/compose.sh", isolated_root / "scripts/compose.sh")
    shutil.copy2(
        root / "scripts/ensure_connector_network.sh",
        isolated_root / "scripts/ensure_connector_network.sh",
    )
    (isolated_root / ".env").write_text(
        "DATARIVER_CONNECTOR_NETWORK=datariver-config-only\n",
        encoding="utf-8",
    )
    fake_docker = bin_dir / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env sh
printf '%s\\n' "$*" >> "$DOCKER_LOG"
exit 0
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    result = subprocess.run(  # noqa: S603 - copied repository script is trusted.
        [str(isolated_root / "scripts/compose.sh"), "config", "--quiet"],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "DOCKER_LOG": str(log_file),
        },
    )

    assert result.returncode == 0, result.stderr
    assert log_file.read_text(encoding="utf-8").splitlines() == [
        f"compose --env-file {isolated_root / '.env'} config --quiet"
    ]


def test_powershell_bootstrap_and_compose_wrapper_have_safe_parity() -> None:
    root = Path(__file__).resolve().parents[3]
    bootstrap = (root / "scripts/bootstrap.ps1").read_text(encoding="utf-8")
    compose_wrapper = (root / "scripts/compose.ps1").read_text(encoding="utf-8")

    assert "[string]$DataHubTokenFile" in bootstrap
    assert "[string]$DataHubToken," in bootstrap
    assert "DataHub token values are not accepted as process arguments" in bootstrap
    assert "Test-ReparsePoint" in bootstrap
    assert "$runtimeDirectory = Join-Path $root" in bootstrap
    assert "$runtimeDirectory," in bootstrap
    assert "Move-Item -Force -LiteralPath $temporaryPath" in bootstrap
    assert bootstrap.index("DataHub token values are not accepted") < bootstrap.index(
        "New-Item -ItemType Directory"
    )
    for fragment in (
        "DATARIVER_CONNECTOR_NETWORK",
        'network", "inspect',
        'network", "create',
        "[A-Za-z0-9_.-]",
        'StartsWith("-", [StringComparison]::Ordinal)',
        "compose",
        "--env-file",
    ):
        assert fragment in compose_wrapper


def test_local_connector_compose_uses_the_shared_external_network() -> None:
    root = Path(__file__).resolve().parents[3]
    compose = (root / "compose.local-connectors.yaml").read_text(encoding="utf-8")
    network = compose.split("\nnetworks:\n", maxsplit=1)[1].split("\nvolumes:\n", maxsplit=1)[0]

    assert "name: ${DATARIVER_CONNECTOR_NETWORK:-datariver-connectors}" in network
    assert "external: true" in network
    assert "internal: false" not in network


def test_operator_docs_use_file_based_tokens_and_network_owning_wrappers() -> None:
    root = Path(__file__).resolve().parents[3]
    documents = {
        path: path.read_text(encoding="utf-8")
        for path in (
            root / "README.md",
            root / "docs/08_DEPLOYMENT.md",
            root / "docs/13_OPERATIONS_RUNBOOK.md",
            root / "docs/26_MAC_TO_WSL_MIGRATION_RUNBOOK.md",
            root / "docs/23_CATALOG_DATAHUB_INGESTION_AND_EXPORT.md",
            root / "docs/10_SEMICONDUCTOR_SEED.md",
            root / "docs/17_SEMICONDUCTOR_SEED_WORKFLOW.md",
            root / "README(KOR).md",
        )
    }

    for path, content in documents.items():
        assert "-DataHubToken '" not in content, path
        assert not re.search(r"bootstrap\.sh\s+['\"]?<[^>]*token", content), path

    readme_platform = documents[root / "README.md"].split(
        "## Local quick start with bundled Keycloak",
        maxsplit=1,
    )[1]
    for path, content in (
        (root / "README.md", readme_platform),
        (root / "docs/08_DEPLOYMENT.md", documents[root / "docs/08_DEPLOYMENT.md"]),
        (
            root / "docs/13_OPERATIONS_RUNBOOK.md",
            documents[root / "docs/13_OPERATIONS_RUNBOOK.md"],
        ),
        (
            root / "docs/10_SEMICONDUCTOR_SEED.md",
            documents[root / "docs/10_SEMICONDUCTOR_SEED.md"],
        ),
        (
            root / "docs/17_SEMICONDUCTOR_SEED_WORKFLOW.md",
            documents[root / "docs/17_SEMICONDUCTOR_SEED_WORKFLOW.md"],
        ),
        (root / "README(KOR).md", documents[root / "README(KOR).md"]),
    ):
        unfolded = content.replace("\\\n", " ")
        assert not re.search(
            r"(?m)^\s*docker compose\b[^\n]*\b(?:up|run|create|start)\b",
            unfolded,
        ), path

    for path, content in documents.items():
        if "bootstrap.sh" in content or "bootstrap.ps1" in content:
            assert "--datahub-token-file" in content or "-DataHubTokenFile" in content, path
    assert (
        "scripts/compose.sh --env-file .env.wsl-preparation"
        in documents[root / "docs/26_MAC_TO_WSL_MIGRATION_RUNBOOK.md"]
    )
    for path in (root / "README.md", root / "docs/13_OPERATIONS_RUNBOOK.md"):
        content = documents[path]
        assert "DATARIVER_ENV_FILE=.env.mac-development" in content
        assert "DATARIVER_ENV_FILE=.env.wsl-preparation" in content
        assert 'scripts/compose.sh --env-file "$DATARIVER_ENV_FILE"' in content
    korean_readme = documents[root / "README(KOR).md"]
    assert "--datahub-token-file /approved-secure-transfer/datahub_token" in korean_readme
    assert "API `38101`" in korean_readme
    assert "Vite `38102`" in korean_readme
    assert "127.0.0.1:8000" not in korean_readme
    assert "localhost:5173" not in korean_readme
    assert "Alembic `0041`" not in korean_readme


def test_minio_knowledge_policy_renders_only_the_eligible_prefix() -> None:
    root = Path(__file__).resolve().parents[3]
    template = (root / "infra/minio/knowledge-read-policy.template.json").read_text(
        encoding="utf-8"
    )
    compose = (root / "compose.local-connectors.yaml").read_text(encoding="utf-8")

    rendered = json.loads(template.replace("__S3_BUCKET_ACCEPTED__", "accepted-a"))
    resources = {
        resource for statement in rendered["Statement"] for resource in statement["Resource"]
    }
    assert resources == {
        "arn:aws:s3:::accepted-a",
        "arn:aws:s3:::accepted-a/knowledge-eligible/*",
    }
    assert "datariver-accepted" not in template
    assert "S3_BUCKET_ACCEPTED: ${S3_BUCKET_ACCEPTED:?" in compose
    assert "MC_CONFIG_DIR: /tmp/mc" in compose
    assert "knowledge-read-policy.json" in compose
    assert "knowledge-read-policy.template.json" in compose
    assert "mc alias set local http://minio:9000" in compose
    assert "mc admin user add local" in compose
    assert 'mc alias set local http://minio:9000 "$$(' not in compose
    assert 'mc admin user add local "$$knowledge_user"' not in compose
    assert "unset root_user root_secret" in compose
    assert "unset knowledge_secret" in compose
    assert "S3_ACCESS_KEY" not in compose
    assert "S3_SECRET_KEY" not in compose


def test_knowledge_worker_image_prepares_owner_only_spool_mountpoint() -> None:
    root = Path(__file__).resolve().parents[3]
    dockerfile = (root / "backend/Dockerfile").read_text(encoding="utf-8")
    compose = (root / "compose.yaml").read_text(encoding="utf-8")

    assert (
        "install -d -o datariver -g datariver -m 0700 /var/spool/datariver-knowledge"
    ) in dockerfile
    assert "knowledge-spool:/var/spool/datariver-knowledge" in compose
