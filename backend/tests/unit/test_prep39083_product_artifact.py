from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "prep39083_product_artifact", ROOT / "scripts" / "prep39083_product_artifact.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

PRODUCT = "1" * 40


def inspection(**overrides: Any) -> list[dict[str, Any]]:
    document: dict[str, Any] = {
        "Os": "linux",
        "Architecture": "amd64",
        "Descriptor": {
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "digest": f"sha256:{'2' * 64}",
        },
        "Config": {
            "User": "node",
            "WorkingDir": "/app",
            "Entrypoint": None,
            "Cmd": ["node", "poc-server.mjs"],
            "Labels": {"org.opencontainers.image.revision": PRODUCT},
        },
    }
    for key, value in overrides.items():
        if key.startswith("Config_"):
            document["Config"][key.removeprefix("Config_")] = value
        else:
            document[key] = value
    return [document]


def test_build_command_is_pinned_to_the_canonical_product_dockerfile() -> None:
    command = MODULE.canonical_build_command(PRODUCT)
    dockerfile = command[command.index("--file") + 1]
    assert dockerfile.endswith("deploy/poc/Dockerfile.example")
    assert not dockerfile.endswith("frontend/Dockerfile")
    assert ["--platform", "linux/amd64"] == command[
        command.index("--platform") : command.index("--platform") + 2
    ]
    assert f"POC_SOURCE_COMMIT={PRODUCT}" in command


def test_runtime_module_closure_is_recursive_explicit_and_complete() -> None:
    closure = MODULE.verify_runtime_module_closure()
    assert set(MODULE.RUNTIME_MODULE_ENTRYPOINTS) <= set(closure)
    assert "poc-k9-semantic-input.mjs" in closure
    copied = MODULE.runtime_modules_copied_by_dockerfile()
    assert set(closure) <= copied
    assert not any(name.endswith(".test.mjs") for name in closure)


def test_runtime_module_closure_rejects_missing_or_broad_copy(
    tmp_path: Path,
) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "entry.mjs").write_text("import './dependency.mjs'\n", encoding="utf-8")
    (frontend / "dependency.mjs").write_text("export const ready = true\n", encoding="utf-8")
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("COPY frontend/entry.mjs ./entry.mjs\n", encoding="utf-8")

    with pytest.raises(MODULE.ProductArtifactError, match=r"dependency\.mjs"):
        MODULE.verify_runtime_module_closure(
            dockerfile,
            frontend,
            ("entry.mjs",),
        )

    dockerfile.write_text("COPY frontend/*.mjs ./*.mjs\n", encoding="utf-8")
    with pytest.raises(MODULE.ProductArtifactError, match="explicit"):
        MODULE.runtime_modules_copied_by_dockerfile(dockerfile)


def test_exact_oci_probe_sequence_imports_runtime_modules_from_image_workdir() -> None:
    image = f"datariver-poc:{PRODUCT}"
    commands = MODULE.runtime_probe_commands(image)
    assert commands[0][-1] == "/usr/bin/true"
    assert commands[1][-2:] == ["node", "--version"]
    assert [command[-1] for command in commands[2:]] == [
        "await import('./poc-provider-preflight.mjs')",
        "await import('./poc-k9-semantic-projector.mjs')",
        "await import('./poc-k9-semantic-input.mjs')",
    ]
    assert all(
        command[command.index("--entrypoint") + 1] == "" and command[-5] == image
        for command in commands[2:]
    )


def test_accepts_the_node_product_runtime_contract() -> None:
    observed = MODULE.validate_runtime_inspection(inspection(), PRODUCT)
    assert observed["Config"]["Cmd"] == ["node", "poc-server.mjs"]


@pytest.mark.parametrize(
    "document",
    [
        inspection(Config_User="nginx"),
        inspection(Config_Cmd=["nginx", "-g", "daemon off;"]),
        inspection(Config_Labels={"org.opencontainers.image.revision": "3" * 40}),
        inspection(Architecture="arm64"),
        inspection(
            Descriptor={"mediaType": "application/vnd.oci.image.manifest.v1+json", "digest": "bad"}
        ),
    ],
)
def test_rejects_frontend_only_or_mismatched_runtime_contract(
    document: list[dict[str, Any]],
) -> None:
    with pytest.raises(MODULE.ProductArtifactError):
        MODULE.validate_runtime_inspection(document, PRODUCT)
