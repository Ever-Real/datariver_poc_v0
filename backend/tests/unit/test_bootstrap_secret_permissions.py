from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


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
    assert "Set-OwnerOnlyWindowsAcl -Path $path" in writer
    assert "Set-OwnerOnlyWindowsAcl -Path $realmPath" in powershell


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
    result = subprocess.run(  # noqa: S603 - copied repository script is trusted.
        [
            str(isolated_root / "scripts/bootstrap.sh"),
            "--enable-knowledge-source-worker",
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
    configured_result = subprocess.run(  # noqa: S603 - copied repository script is trusted.
        [
            str(configured_root / "scripts/bootstrap.sh"),
            "--enable-knowledge-source-worker",
            "test-only-datahub-token",
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
