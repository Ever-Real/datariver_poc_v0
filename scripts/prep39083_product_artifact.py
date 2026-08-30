#!/usr/bin/env python3
"""Build and export one canonical PREP39083 Product artifact.

This is the only supported local build entry point for the promoted Product
image.  Target hosts continue to consume the checksum-pinned archive and never
invoke this command.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_DOCKERFILE = ROOT / "deploy" / "poc" / "Dockerfile.example"
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
EXPECTED_FILES = (
    "/app/poc-server.mjs",
    "/app/poc-provider-preflight.mjs",
    "/app/poc-k9-managed-graphs.mjs",
    "/app/poc-mcl-capture.mjs",
    "/app/dist-poc/poc.html",
)


class ProductArtifactError(RuntimeError):
    """The local build is not eligible for promotion."""


def run(command: Sequence[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command), cwd=ROOT, check=True, text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def output(command: Sequence[str]) -> str:
    return run(command, capture=True).stdout.strip()


def canonical_build_command(product_sha: str) -> list[str]:
    return [
        "docker", "buildx", "build",
        "--platform", "linux/amd64",
        "--pull=false",
        "--load",
        "--build-arg", f"POC_SOURCE_COMMIT={product_sha}",
        "--file", os.fspath(CANONICAL_DOCKERFILE),
        "--tag", f"datariver-poc:{product_sha}",
        os.fspath(ROOT),
    ]


def validate_runtime_inspection(document: object, product_sha: str) -> Mapping[str, Any]:
    if not isinstance(document, list) or len(document) != 1 or not isinstance(document[0], dict):
        raise ProductArtifactError("Docker returned no exact single-image inspection contract")
    image = document[0]
    config = image.get("Config")
    descriptor = image.get("Descriptor")
    if not isinstance(config, dict) or not isinstance(descriptor, dict):
        raise ProductArtifactError("Product image config or manifest descriptor is missing")
    labels = config.get("Labels") or {}
    if (
        image.get("Os") != "linux"
        or image.get("Architecture") != "amd64"
        or config.get("User") != "node"
        or config.get("Entrypoint") not in (None, [])
        or config.get("Cmd") != ["node", "poc-server.mjs"]
        or not isinstance(labels, dict)
        or labels.get("org.opencontainers.image.revision") != product_sha
        or descriptor.get("mediaType") != "application/vnd.oci.image.manifest.v1+json"
        or not isinstance(descriptor.get("digest"), str)
        or not DIGEST_PATTERN.fullmatch(descriptor["digest"])
    ):
        raise ProductArtifactError("Product runtime entrypoint/platform/revision contract mismatch")
    return image


def require_clean_product(product_sha: str) -> None:
    if not SHA_PATTERN.fullmatch(product_sha):
        raise ProductArtifactError("Product SHA must be one exact lowercase Git SHA")
    if output(["git", "rev-parse", "HEAD"]) != product_sha:
        raise ProductArtifactError("HEAD must equal the Product SHA before build")
    if output(["git", "branch", "--show-current"]) != "dev":
        raise ProductArtifactError("Product artifact build is allowed only from canonical dev")
    if output(["git", "status", "--porcelain", "--untracked-files=all"]):
        raise ProductArtifactError("Product artifact build requires a clean committed worktree")
    if not CANONICAL_DOCKERFILE.is_file():
        raise ProductArtifactError("Canonical Product Dockerfile is missing")


def verify_runtime(image: str, product_sha: str) -> Mapping[str, Any]:
    inspected = json.loads(output([
        "docker", "image", "inspect", "--platform", "linux/amd64", image,
    ]))
    image_document = validate_runtime_inspection(inspected, product_sha)
    hardening = [
        "docker", "run", "--rm", "--platform", "linux/amd64", "--read-only",
        "--user", "1000:1000", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges:true", "--entrypoint", "node", image,
    ]
    run([*hardening, "--version"], capture=True)
    expression = (
        "const fs=require('node:fs');const missing="
        f"{json.dumps(EXPECTED_FILES)}.filter((p)=>!fs.existsSync(p));"
        "if(missing.length){console.error(missing.join('\\n'));process.exit(1)}"
    )
    run([*hardening, "-e", expression], capture=True)
    return image_document


def build_and_export(product_sha: str, output_dir: Path) -> Mapping[str, Any]:
    require_clean_product(product_sha)
    run(canonical_build_command(product_sha))
    image = f"datariver-poc:{product_sha}"
    inspected = verify_runtime(image, product_sha)
    run([
        sys.executable, os.fspath(ROOT / "scripts" / "prep39083_release.py"),
        "web-artifact-export", "--product-sha", product_sha,
        "--output-dir", os.fspath(output_dir),
    ])
    return {
        "result": "CANONICAL_PRODUCT_ARTIFACT_EXPORTED",
        "product_sha": product_sha,
        "image": image,
        "platform": "linux/amd64",
        "manifest_digest": inspected["Descriptor"]["digest"],
        "output_dir": os.fspath(output_dir),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product-sha", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        result = build_and_export(arguments.product_sha, arguments.output_dir.resolve())
    except (ProductArtifactError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        print(f"PREP39083_PRODUCT_ARTIFACT_ERROR: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
