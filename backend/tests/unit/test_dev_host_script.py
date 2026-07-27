from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _profile(tmp_path: Path, **overrides: str) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    effective_overrides = {
        "LOCAL_OLLAMA_CHAT_BASE_URL": "http://127.0.0.1:11434/v1",
        "LOCAL_OLLAMA_CHAT_MODEL": "test-chat-model",
        "LOCAL_OLLAMA_EMBEDDING_BASE_URL": "http://127.0.0.1:11434/v1",
        "LOCAL_OLLAMA_EMBEDDING_MODEL": "test-embedding-model",
        **overrides,
    }
    keys = set(effective_overrides)
    # Keep the fixture deterministic and independent from ignored developer
    # profiles. Explicit tests add a duplicate when exercising fail-closed
    # parsing.
    last_index: dict[str, int] = {}
    for index, line in enumerate(source):
        key, separator, _value = line.partition("=")
        if separator and key:
            last_index[key] = index
    retained = []
    for index, line in enumerate(source):
        key, separator, _value = line.partition("=")
        if key in keys:
            continue
        if separator and key and last_index[key] != index:
            continue
        retained.append(line)
    profile = tmp_path / "source-host.env"
    profile.write_text(
        "\n".join(
            (
                *retained,
                *(f"{key}={value}" for key, value in effective_overrides.items()),
                "",
            )
        ),
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
        "environment_file": str(profile),
        "knowledge_source_analysis": "CONFIGURED",
        "local_inference_source_host": True,
        "neo4j_endpoint": None,
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


def test_source_host_start_rejects_unsupported_node_before_processes(
    tmp_path: Path,
) -> None:
    profile = _profile(tmp_path / "profile", NEO4J_PROJECTION_ENABLED="false")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_node = fake_bin / "node"
    fake_node.write_text(
        "#!/usr/bin/env sh\nprintf '%s\\n' 'v18.20.8'\n",
        encoding="utf-8",
    )
    fake_node.chmod(0o755)

    result = subprocess.run(  # noqa: S603 - fixed repository script and temporary fake Node
        [
            "/bin/bash",
            str(ROOT / "scripts" / "dev_host.sh"),
            "start",
            "--env-file",
            str(profile),
        ],
        cwd=ROOT,
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "Unsupported Node.js runtime: v18.20.8" in result.stderr
    assert "requires Node.js >=22.19.0" in result.stderr


def test_source_host_node_floor_matches_frontend_engine() -> None:
    package = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text(encoding="utf-8"))
    launcher = (ROOT / "scripts/dev_host.sh").read_text(encoding="utf-8")

    assert package["engines"]["node"] == ">=22.19.0"
    linux_binding = lock["packages"]["node_modules/@rolldown/binding-linux-x64-gnu"]
    assert linux_binding["version"] == "1.1.5"
    assert linux_binding["cpu"] == ["x64"]
    assert linux_binding["os"] == ["linux"]
    assert linux_binding["optional"] is True
    assert "node_major < 22" in launcher
    assert "node_major == 22 && node_minor < 19" in launcher
    assert "requires Node.js >=22.19.0" in launcher
    assert "@rolldown/binding-linux-x64-gnu/rolldown-binding.linux-x64-gnu.node" in launcher
    assert "npm --prefix frontend ci --include=optional" in launcher


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
    assert graph_only["neo4j_endpoint"] == {
        "expected_source_host_port": 17687,
        "host": "127.0.0.1",
        "port": 17687,
        "scheme": "bolt",
    }


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


def test_source_host_preflight_accepts_single_quoted_dotenv_values(tmp_path: Path) -> None:
    profile = _profile(
        tmp_path,
        NEO4J_PROJECTION_ENABLED="'true'",
        NEO4J_URI="'bolt://127.0.0.1:17687'",
        NEO4J_ALLOWED_HOSTS="'127.0.0.1'",
    )

    document = _preflight(profile)

    assert document["neo4j_projection"] == "CONFIGURED"
    assert document["neo4j_endpoint"] == {
        "expected_source_host_port": 17687,
        "host": "127.0.0.1",
        "port": 17687,
        "scheme": "bolt",
    }


def test_source_host_preflight_translates_container_neo4j_to_selected_host_port(
    tmp_path: Path,
) -> None:
    document = _preflight(
        _profile(
            tmp_path,
            NEO4J_PROJECTION_ENABLED="true",
            NEO4J_URI="bolt://neo4j:7687",
            NEO4J_ALLOWED_HOSTS="neo4j",
            NEO4J_BOLT_PORT="27687",
        )
    )

    assert document["neo4j_endpoint"] == {
        "expected_source_host_port": 27687,
        "host": "127.0.0.1",
        "port": 27687,
        "scheme": "bolt",
    }


def test_source_host_preflight_reports_sanitized_endpoint_on_validation_failure(
    tmp_path: Path,
) -> None:
    profile = _profile(
        tmp_path,
        NEO4J_PROJECTION_ENABLED="true",
        NEO4J_URI="bolt://127.0.0.1:17687",
        NEO4J_ALLOWED_HOSTS="127.0.0.1",
        NEO4J_BOLT_PORT="27687",
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
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    diagnostic = json.loads(result.stderr)
    assert diagnostic["environment_file"] == str(profile)
    assert diagnostic["neo4j_endpoint"] == {
        "expected_source_host_port": "27687",
        "host": "127.0.0.1",
        "port": 17687,
        "scheme": "bolt",
    }
    assert diagnostic["status"] == "INVALID"
    assert "expected_source_host_port=27687" in diagnostic["validation_errors"][0]["message"]
    assert "neo4j_auth" not in result.stderr


def test_source_host_preflight_rejects_duplicate_environment_keys(tmp_path: Path) -> None:
    profile = _profile(tmp_path, NEO4J_PROJECTION_ENABLED="false")
    with profile.open("a", encoding="utf-8") as stream:
        stream.write("NEO4J_PROJECTION_ENABLED=true\n")

    result = subprocess.run(  # noqa: S603 - fixed repository script and arguments
        [
            "/bin/bash",
            str(ROOT / "scripts" / "dev_host.sh"),
            "preflight",
            "--env-file",
            str(profile),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "Duplicate environment key" in result.stderr
    assert "NEO4J_PROJECTION_ENABLED" in result.stderr


def test_source_host_preflight_rejects_bare_environment_entries(tmp_path: Path) -> None:
    profile = _profile(tmp_path, NEO4J_PROJECTION_ENABLED="false")
    with profile.open("a", encoding="utf-8") as stream:
        stream.write("NOT_AN_ASSIGNMENT\n")

    result = subprocess.run(  # noqa: S603 - fixed repository script and arguments
        [
            "/bin/bash",
            str(ROOT / "scripts" / "dev_host.sh"),
            "preflight",
            "--env-file",
            str(profile),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "Invalid environment entry without '='" in result.stderr


def test_source_host_preflight_does_not_inherit_missing_neo4j_values(
    tmp_path: Path,
) -> None:
    profile = _profile(
        tmp_path,
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
        env={
            **dict(os.environ),
            "NEO4J_PROJECTION_ENABLED": "true",
            "NEO4J_URI": "bolt://untrusted.example:7687",
        },
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout)["neo4j_projection"] == "NOT_CONFIGURED"


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


def test_source_host_exposes_idempotent_local_identity_bootstrap() -> None:
    source = (ROOT / "scripts/dev_host.sh").read_text(encoding="utf-8")

    assert "bootstrap-identity" in source
    assert (
        'BOOTSTRAP_DATABASE_URL="postgresql+asyncpg://datariver_bootstrap@127.0.0.1:'
        '$postgres_port/datariver"'
    ) in source
    assert 'BOOTSTRAP_DATABASE_SECRET_REF="$(secret_ref postgres_bootstrap_password)"' in source
    assert "-m datariver.bootstrap local-identity" in source
