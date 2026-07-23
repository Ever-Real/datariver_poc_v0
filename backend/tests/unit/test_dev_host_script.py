from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_source_host_preflight_validates_local_ollama_and_neo4j_settings() -> None:
    result = subprocess.run(  # noqa: S603 - fixed repository script and arguments
        [
            "/bin/bash",
            str(ROOT / "scripts" / "dev_host.sh"),
            "preflight",
            "--env-file",
            ".env.mac-development",
            "--enable-local-ollama",
            "--enable-neo4j",
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
        "neo4j_projection": "CONFIGURED",
        "runtime_activation": True,
    }


def _preflight(*flags: str) -> dict[str, object]:
    result = subprocess.run(  # noqa: S603 - fixed repository script and arguments
        [
            "/bin/bash",
            str(ROOT / "scripts" / "dev_host.sh"),
            "preflight",
            "--env-file",
            ".env.mac-development",
            *flags,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(result.stdout)
    assert isinstance(value, dict)
    return value


def test_source_host_preflight_capabilities_are_independently_selectable() -> None:
    model_only = _preflight("--enable-local-ollama")
    graph_only = _preflight("--enable-neo4j")

    assert model_only["knowledge_source_analysis"] == "CONFIGURED"
    assert model_only["neo4j_projection"] == "NOT_CONFIGURED"
    assert graph_only["knowledge_source_analysis"] == "NOT_CONFIGURED"
    assert graph_only["neo4j_projection"] == "CONFIGURED"
