from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "prep39083_product_artifact", ROOT / "scripts" / "prep39083_product_artifact.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

PRODUCT = "1" * 40


def inspection(**overrides):
    document = {
        "Os": "linux",
        "Architecture": "amd64",
        "Descriptor": {
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "digest": f"sha256:{'2' * 64}",
        },
        "Config": {
            "User": "node",
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


def test_build_command_is_pinned_to_the_canonical_product_dockerfile():
    command = MODULE.canonical_build_command(PRODUCT)
    dockerfile = command[command.index("--file") + 1]
    assert dockerfile.endswith("deploy/poc/Dockerfile.example")
    assert not dockerfile.endswith("frontend/Dockerfile")
    assert ["--platform", "linux/amd64"] == command[
        command.index("--platform") : command.index("--platform") + 2
    ]
    assert f"POC_SOURCE_COMMIT={PRODUCT}" in command


def test_accepts_the_node_product_runtime_contract():
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
def test_rejects_frontend_only_or_mismatched_runtime_contract(document):
    with pytest.raises(MODULE.ProductArtifactError):
        MODULE.validate_runtime_inspection(document, PRODUCT)
