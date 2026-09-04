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
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_DOCKERFILE = ROOT / "deploy" / "poc" / "Dockerfile.example"
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
EXPECTED_FILES = (
    "/app/poc-server.mjs",
    "/app/poc-prep-bootstrap.mjs",
    "/app/poc-provider-preflight.mjs",
    "/app/poc-k9-semantic-projector.mjs",
    "/app/poc-k9-semantic-input.mjs",
    "/app/poc-k9-managed-graphs.mjs",
    "/app/poc-mcl-capture.mjs",
    "/app/dist-poc/poc.html",
)
RUNTIME_MODULE_ENTRYPOINTS = (
    "poc-server.mjs",
    "poc-prep-bootstrap.mjs",
    "poc-provider-preflight.mjs",
)
OCI_IMPORT_PROBES = (
    "poc-provider-preflight.mjs",
    "poc-k9-semantic-projector.mjs",
    "poc-k9-semantic-input.mjs",
)
RELATIVE_MJS_LITERAL = re.compile(r"""["'](\./[A-Za-z0-9_./-]+\.mjs)["']""")
EXACT_RUNTIME_COPY = re.compile(r"COPY frontend/([A-Za-z0-9_./-]+\.mjs) \./([A-Za-z0-9_./-]+\.mjs)")


class ProductArtifactError(RuntimeError):
    """The local build is not eligible for promotion."""


def run(command: Sequence[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - argv-only canonical release commands.
        list(command),
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def output(command: Sequence[str]) -> str:
    return run(command, capture=True).stdout.strip()


def canonical_build_command(product_sha: str) -> list[str]:
    return [
        "docker",
        "buildx",
        "build",
        "--platform",
        "linux/amd64",
        "--pull=false",
        "--load",
        "--build-arg",
        f"POC_SOURCE_COMMIT={product_sha}",
        "--file",
        os.fspath(CANONICAL_DOCKERFILE),
        "--tag",
        f"datariver-poc:{product_sha}",
        os.fspath(ROOT),
    ]


def runtime_modules_copied_by_dockerfile(dockerfile: Path = CANONICAL_DOCKERFILE) -> set[str]:
    copied: set[str] = set()
    for raw_line in dockerfile.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("COPY frontend/") or ".mjs" not in line:
            continue
        match = EXACT_RUNTIME_COPY.fullmatch(line)
        if match is None or match.group(1) != match.group(2):
            raise ProductArtifactError(
                "Runtime modules require explicit source-equal final-image COPY entries"
            )
        copied.add(match.group(1))
    return copied


def resolve_runtime_module_closure(
    frontend: Path = ROOT / "frontend",
    entrypoints: Sequence[str] = RUNTIME_MODULE_ENTRYPOINTS,
) -> tuple[str, ...]:
    frontend = frontend.resolve()
    pending = list(entrypoints)
    resolved: set[str] = set()
    while pending:
        relative = pending.pop()
        if relative in resolved:
            continue
        candidate = (frontend / relative).resolve()
        try:
            canonical_relative = candidate.relative_to(frontend).as_posix()
        except ValueError as error:
            raise ProductArtifactError(
                "Runtime module dependency escapes frontend source"
            ) from error
        if canonical_relative != relative or candidate.suffix != ".mjs" or not candidate.is_file():
            raise ProductArtifactError(f"Runtime module source is missing: {relative}")
        resolved.add(relative)
        for specifier in RELATIVE_MJS_LITERAL.findall(candidate.read_text(encoding="utf-8")):
            dependency = (candidate.parent / specifier).resolve()
            try:
                dependency_relative = dependency.relative_to(frontend).as_posix()
            except ValueError as error:
                raise ProductArtifactError(
                    "Runtime module dependency escapes frontend source"
                ) from error
            if dependency_relative not in resolved:
                pending.append(dependency_relative)
    return tuple(sorted(resolved))


def verify_runtime_module_closure(
    dockerfile: Path = CANONICAL_DOCKERFILE,
    frontend: Path = ROOT / "frontend",
    entrypoints: Sequence[str] = RUNTIME_MODULE_ENTRYPOINTS,
) -> tuple[str, ...]:
    closure = resolve_runtime_module_closure(frontend, entrypoints)
    copied = runtime_modules_copied_by_dockerfile(dockerfile)
    missing = sorted(set(closure) - copied)
    if missing:
        raise ProductArtifactError("Final image omits runtime module closure: " + ",".join(missing))
    return closure


def runtime_probe_commands(image: str) -> tuple[list[str], ...]:
    hardened = [
        "docker",
        "run",
        "--rm",
        "--platform",
        "linux/amd64",
        "--read-only",
        "--user",
        "1000:1000",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--entrypoint",
        "",
        image,
    ]
    imports = tuple(
        [
            *hardened,
            "node",
            "--input-type=module",
            "--eval",
            f"await import('./{module}')",
        ]
        for module in OCI_IMPORT_PROBES
    )
    return (
        [*hardened, "/usr/bin/true"],
        [*hardened, "node", "--version"],
        *imports,
    )


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
        or config.get("WorkingDir") != "/app"
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
    verify_runtime_module_closure()


def verify_runtime(image: str, product_sha: str) -> Mapping[str, Any]:
    inspected = json.loads(
        output(
            [
                "docker",
                "image",
                "inspect",
                "--platform",
                "linux/amd64",
                image,
            ]
        )
    )
    image_document = validate_runtime_inspection(inspected, product_sha)
    for command in runtime_probe_commands(image):
        run(command, capture=True)
    expression = (
        "const fs=require('node:fs');const missing="
        f"{json.dumps(EXPECTED_FILES)}.filter((p)=>!fs.existsSync(p));"
        "if(missing.length){console.error(missing.join('\\n'));process.exit(1)}"
    )
    run(
        [
            "docker",
            "run",
            "--rm",
            "--platform",
            "linux/amd64",
            "--read-only",
            "--user",
            "1000:1000",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--entrypoint",
            "node",
            image,
            "-e",
            expression,
        ],
        capture=True,
    )
    return image_document


def build_and_export(product_sha: str, output_dir: Path) -> Mapping[str, Any]:
    require_clean_product(product_sha)
    run(canonical_build_command(product_sha))
    image = f"datariver-poc:{product_sha}"
    inspected = verify_runtime(image, product_sha)
    run(
        [
            sys.executable,
            os.fspath(ROOT / "scripts" / "prep39083_release.py"),
            "web-artifact-export",
            "--product-sha",
            product_sha,
            "--output-dir",
            os.fspath(output_dir),
        ]
    )
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
