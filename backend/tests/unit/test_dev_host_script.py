from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _profile(tmp_path: Path, **overrides: str) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = (ROOT / ".env.mac-development").read_text(encoding="utf-8").splitlines()
    keys = set(overrides)
    retained = [
        line
        for line in source
        if not line or line.startswith("#") or line.partition("=")[0] not in keys
    ]
    profile = tmp_path / "source-host.env"
    profile.write_text(
        "\n".join((*retained, *(f"{key}={value}" for key, value in overrides.items()), "")),
        encoding="utf-8",
    )
    return profile


def test_source_host_preflight_validates_env_owned_capabilities(tmp_path: Path) -> None:
    profile = _profile(
        tmp_path,
        LOCAL_OLLAMA_CHAT_ENABLED="true",
        LOCAL_OLLAMA_EMBEDDING_ENABLED="true",
        NEO4J_PROJECTION_ENABLED="false",
    )
    result = subprocess.run(  # noqa: S603 - fixed repository script and arguments
        [
            "/bin/bash",
            str(ROOT / "scripts" / "dev_host.sh"),
            "preflight",
            "--env-file",
            str(profile),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    document = json.loads(result.stdout)

    assert document == {
        "knowledge_source_analysis": "CONFIGURED",
        "local_inference_source_host": True,
        "neo4j_projection": "NOT_CONFIGURED",
        "runtime_activation": False,
    }


def _preflight(profile: Path) -> dict[str, object]:
    result = subprocess.run(  # noqa: S603 - fixed repository script and arguments
        [
            "/bin/bash",
            str(ROOT / "scripts" / "dev_host.sh"),
            "preflight",
            "--env-file",
            str(profile),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(result.stdout)
    assert isinstance(value, dict)
    return value


def test_source_host_preflight_capabilities_are_independently_selectable(
    tmp_path: Path,
) -> None:
    model_only = _preflight(
        _profile(
            tmp_path / "model",
            LOCAL_OLLAMA_CHAT_ENABLED="true",
            LOCAL_OLLAMA_EMBEDDING_ENABLED="true",
            INTRANET_OPENAI_COMPATIBLE_CHAT_ENABLED="false",
            INTRANET_OPENAI_COMPATIBLE_EMBEDDING_ENABLED="false",
            NEO4J_PROJECTION_ENABLED="false",
        )
    )
    graph_only = _preflight(
        _profile(
            tmp_path / "graph",
            LOCAL_OLLAMA_CHAT_ENABLED="false",
            LOCAL_OLLAMA_EMBEDDING_ENABLED="false",
            INTRANET_OPENAI_COMPATIBLE_CHAT_ENABLED="false",
            INTRANET_OPENAI_COMPATIBLE_EMBEDDING_ENABLED="false",
            NEO4J_PROJECTION_ENABLED="true",
            NEO4J_URI="bolt://127.0.0.1:17687",
            NEO4J_AUTH_SECRET_REF="file:/run/secrets/neo4j_auth",
        )
    )

    assert model_only["knowledge_source_analysis"] == "CONFIGURED"
    assert model_only["neo4j_projection"] == "NOT_CONFIGURED"
    assert graph_only["knowledge_source_analysis"] == "NOT_CONFIGURED"
    assert graph_only["neo4j_projection"] == "CONFIGURED"


def test_source_host_preflight_accepts_windows_crlf_and_injects_neo4j_secret(
    tmp_path: Path,
) -> None:
    profile = _profile(
        tmp_path,
        LOCAL_OLLAMA_CHAT_ENABLED="false",
        LOCAL_OLLAMA_EMBEDDING_ENABLED="false",
        NEO4J_PROJECTION_ENABLED="true",
        NEO4J_URI="bolt://127.0.0.1:17687",
        NEO4J_ALLOWED_HOSTS="127.0.0.1",
    )
    profile.write_bytes(profile.read_text(encoding="utf-8").replace("\n", "\r\n").encode())

    document = _preflight(profile)

    assert document["neo4j_projection"] == "CONFIGURED"


def test_intranet_source_host_preflight_accepts_distinct_https_origins(
    tmp_path: Path,
) -> None:
    document = _preflight(
        _profile(
            tmp_path,
            APP_ENV="development",
            INTRANET_SOURCE_HOST_ENABLED="true",
            APP_PUBLIC_ORIGIN="https://datariver-prep.example.internal",
            APP_CORS_ORIGINS="https://datariver-prep.example.internal",
            OIDC_ISSUER="https://identity-prep.example.internal/realms/datariver",
            OIDC_PUBLIC_AUTHORITY=("https://identity-prep.example.internal/realms/datariver"),
            OIDC_PUBLIC_ORIGIN="https://identity-prep.example.internal",
        )
    )

    assert document["local_inference_source_host"] is True


def test_migrate_explains_unpublished_wsl_postgres_port(tmp_path: Path) -> None:
    profile = _profile(tmp_path, POSTGRES_PORT="45999")
    result = subprocess.run(  # noqa: S603 - fixed repository script and arguments
        [
            "/bin/bash",
            str(ROOT / "scripts" / "dev_host.sh"),
            "migrate",
            "--env-file",
            str(profile),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "PostgreSQL is not reachable at 127.0.0.1:45999" in result.stderr
    assert "shown only as 5432/tcp is not published" in result.stderr
    assert "workflow_source_host_infra.py" in result.stderr


def test_optional_source_processes_are_required_only_when_enabled() -> None:
    source = (ROOT / "scripts/dev_host.sh").read_text(encoding="utf-8")

    assert 'show_optional_status airflow-api-bridge "$enable_airflow_source_bridge"' in source
    assert (
        'show_optional_status knowledge-source-worker "$knowledge_source_worker_enabled"' in source
    )
    assert "required_processes+=(airflow-api-bridge)" in source
    assert "required_processes+=(knowledge-source-worker)" in source
    assert 'export NEO4J_AUTH_SECRET_REF="$(secret_ref neo4j_auth)"' in source
