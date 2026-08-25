#!/usr/bin/env python3
"""Verify and export the exact PREP39083-tested POC image set for OPS.

This tool never builds, starts, stops, pulls, loads, or removes an image. PREP
operators build and accept the candidate with Compose first; ``export`` then
captures the immutable images used by those running containers. ``verify`` is
artifact-only and performs no Docker mutation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
BASE_COMPOSE = ROOT / "deploy" / "poc" / "docker-compose.poc.yaml"
OPS_COMPOSE = ROOT / "deploy" / "prep39083" / "docker-compose.ops.yaml"
OPS_ENV_EXAMPLE = ROOT / "deploy" / "prep39083" / ".env.ops.example"
PREP_ENV_EXAMPLE = ROOT / "deploy" / "prep39083" / ".env.prep.example"
PREP_OPTIONAL_ENV_EXAMPLE = (
    ROOT / "deploy" / "prep39083" / ".env.prep.optional.example"
)
ENV_CONTRACT = ROOT / "deploy" / "prep39083" / "env-contract.json"
POSTGRES_INIT = ROOT / "deploy" / "poc" / "postgres-init"
PREP_GUIDE = ROOT / "docs" / "64_PREP39083_HANDOFF.md"
OPS_GUIDE = ROOT / "docs" / "65_PREP_TO_OPS_PROMOTION.md"
RELEASE_GUIDE = ROOT / "docs" / "66_RELEASE_CYCLE.md"
RELEASE_TOOL = Path(__file__).resolve()
DEPLOY_TOOL = ROOT / "scripts" / "prep39083_deploy.py"
PREP_ENTRYPOINT = ROOT / "scripts" / "prep39083"
SMOKE_TOOL = ROOT / "scripts" / "smoke_prep39083.mjs"
RUNTIME_INPUTS = (
    "frontend",
    "deploy/poc/Dockerfile.example",
    "deploy/poc/docker-compose.poc.yaml",
    "deploy/poc/postgres-init",
    "deploy/prep39083/.env.prep.example",
    "deploy/prep39083/.env.prep.optional.example",
    "deploy/prep39083/.env.ops.example",
    "deploy/prep39083/docker-compose.ops.yaml",
    "deploy/prep39083/env-contract.json",
    "scripts/prep39083",
    "scripts/prep39083_deploy.py",
    "scripts/prep39083_release.py",
    "scripts/smoke_prep39083.mjs",
)
SERVICES = ("web", "neo4j", "pgvector", "redis")
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
CONTRACT = "DATARIVER_PREP39083_OPS_RELEASE_V2"


class ReleaseError(RuntimeError):
    """A fail-closed operator-correctable release error."""


def run(arguments: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(  # noqa: S603 - argv only; no shell interpolation.
        arguments,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if check and completed.returncode != 0:
        raise ReleaseError(f"command failed ({completed.returncode}): {' '.join(arguments[:4])}")
    return completed


def output(arguments: list[str]) -> str:
    return run(arguments).stdout.strip()


def require_sha(value: str, name: str) -> str:
    if not SHA_PATTERN.fullmatch(value):
        raise ReleaseError(f"{name} must be one exact 40-character lowercase Git SHA")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_paths(paths: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def sha256_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def git_commit_exists(commit: str, name: str) -> None:
    completed = run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], check=False)
    if completed.returncode != 0:
        raise ReleaseError(f"{name} is not an available Git commit")


def source_contract(product_sha: str, evidence_sha: str, *, clean: bool) -> dict[str, str]:
    product_sha = require_sha(product_sha, "Product SHA")
    evidence_sha = require_sha(evidence_sha, "Evidence SHA")
    repository = output(["git", "rev-parse", "--show-toplevel"])
    if Path(repository).resolve() != ROOT:
        raise ReleaseError("unexpected repository root")
    head = output(["git", "rev-parse", "HEAD"])
    git_commit_exists(product_sha, "Product SHA")
    git_commit_exists(evidence_sha, "Evidence SHA")
    for older, newer, label in (
        (product_sha, evidence_sha, "Product→Evidence"),
        (evidence_sha, head, "Evidence→HEAD"),
    ):
        relation = run(["git", "merge-base", "--is-ancestor", older, newer], check=False)
        if relation.returncode != 0:
            raise ReleaseError(f"{label} ancestry is not linear")
    drift = run(
        ["git", "diff", "--quiet", product_sha, "HEAD", "--", *RUNTIME_INPUTS],
        check=False,
    )
    if drift.returncode != 0:
        raise ReleaseError("runtime build inputs changed after the accepted Product checkpoint")
    if clean and output(["git", "status", "--porcelain", "--untracked-files=all"]):
        raise ReleaseError("release operations require a clean committed worktree")
    return {
        "product_sha": product_sha,
        "evidence_sha": evidence_sha,
        "handoff_commit": head,
        "runtime_input_diff": "NONE",
    }


def require_private_env(path: Path) -> Path:
    candidate = path.expanduser().absolute()
    metadata = candidate.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ReleaseError("the selected environment must be a regular non-symlink file")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ReleaseError("the selected environment file must have mode 0600 or stricter")
    return candidate.resolve()


def compose_prefix(project: str, env_file: Path) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-name",
        project,
        "--env-file",
        os.fspath(env_file),
        "--file",
        os.fspath(BASE_COMPOSE),
    ]


def inspect_running_images(project: str, env_file: Path, product_sha: str) -> list[dict[str, str]]:
    docker_architecture = output(["docker", "info", "--format", "{{.Architecture}}"])
    if platform.system() != "Linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise ReleaseError("PREP export requires a native Linux/WSL amd64 host")
    if docker_architecture != "x86_64" and docker_architecture != "amd64":
        raise ReleaseError(f"Docker server architecture is {docker_architecture}, expected amd64")
    prefix = compose_prefix(project, env_file)
    images: list[dict[str, str]] = []
    for service in SERVICES:
        identifiers = output([*prefix, "ps", "-q", service]).splitlines()
        if len(identifiers) != 1:
            raise ReleaseError(f"{project}/{service} must resolve to exactly one container")
        container = json.loads(output(["docker", "inspect", identifiers[0]]))[0]
        state = container.get("State", {})
        if not state.get("Running"):
            raise ReleaseError(f"{project}/{service} is not running")
        health = state.get("Health", {}).get("Status")
        if health and health != "healthy":
            raise ReleaseError(f"{project}/{service} health is {health}")
        image_ref = container.get("Config", {}).get("Image")
        running_id = container.get("Image")
        if not isinstance(image_ref, str) or not isinstance(running_id, str):
            raise ReleaseError(f"{project}/{service} image identity is unavailable")
        image = json.loads(output(["docker", "image", "inspect", image_ref]))[0]
        if image.get("Id") != running_id:
            raise ReleaseError(f"{service} image tag no longer names the running immutable image")
        if image.get("Os") != "linux" or image.get("Architecture") != "amd64":
            raise ReleaseError(f"{service} is not a linux/amd64 image")
        labels = image.get("Config", {}).get("Labels") or {}
        revision = labels.get("org.opencontainers.image.revision")
        if service == "web" and revision != product_sha:
            raise ReleaseError("running web OCI revision does not equal the accepted Product SHA")
        images.append(
            {
                "service": service,
                "reference": image_ref,
                "image_id": running_id,
                "platform": "linux/amd64",
                "source_revision": revision or "UPSTREAM_VENDOR_IMAGE",
                "created": str(image.get("Created") or "UNKNOWN"),
            }
        )
    return images


def safe_archive_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = archive.getmembers()
    names: set[str] = set()
    for member in members:
        path = PurePosixPath(member.name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or member.name in names
            or not (member.isfile() or member.isdir())
        ):
            raise ReleaseError("release archive contains an unsafe path or link")
        names.add(member.name)
    return members


def export_release(arguments: argparse.Namespace) -> None:
    source = source_contract(arguments.product_sha, arguments.evidence_sha, clean=True)
    env_file = require_private_env(arguments.env_file)
    output_dir = arguments.output_dir.expanduser().resolve()
    if output_dir.exists():
        raise ReleaseError(f"output directory already exists: {output_dir}")
    images = inspect_running_images(arguments.project_name, env_file, source["product_sha"])
    with tempfile.TemporaryDirectory(prefix="datariver-prep39083-export-") as temporary:
        stage = Path(temporary)
        tracked = (
            BASE_COMPOSE,
            OPS_COMPOSE,
            OPS_ENV_EXAMPLE,
            ENV_CONTRACT,
            PREP_OPTIONAL_ENV_EXAMPLE,
            PREP_GUIDE,
            OPS_GUIDE,
            RELEASE_GUIDE,
            PREP_ENTRYPOINT,
            DEPLOY_TOOL,
            RELEASE_TOOL,
            SMOKE_TOOL,
        )
        for path in tracked:
            shutil.copy2(path, stage / path.name)
        shutil.copytree(POSTGRES_INIT, stage / POSTGRES_INIT.name)
        image_archive = stage / "images.tar"
        run(
            [
                "docker",
                "image",
                "save",
                "--output",
                os.fspath(image_archive),
                *[item["reference"] for item in images],
            ]
        )
        manifest = {
            "contract": CONTRACT,
            "product_sha": source["product_sha"],
            "evidence_sha": source["evidence_sha"],
            "git_commit": source["handoff_commit"],
            "runtime_input_diff": source["runtime_input_diff"],
            "image_tag": images[0]["reference"],
            "image_id": images[0]["image_id"],
            "architecture": "linux/amd64",
            "build_timestamp": images[0]["created"],
            "export_timestamp": datetime.now(UTC).isoformat(),
            "compose_revision": sha256_paths((BASE_COMPOSE, OPS_COMPOSE)),
            "config_schema_version": "PREP39083_ENV_V2",
            "config_schema_sha256": sha256_paths(
                (
                    PREP_ENV_EXAMPLE,
                    PREP_OPTIONAL_ENV_EXAMPLE,
                    OPS_ENV_EXAMPLE,
                    ENV_CONTRACT,
                )
            ),
            "postgres_init_sha256": sha256_tree(POSTGRES_INIT),
            "image_archive": "images.tar",
            "image_archive_sha256": sha256_file(image_archive),
            "images": images,
            "external_services_not_bundled": [
                "DataHub",
                "Airflow",
                "MinIO",
                "OpenAI-compatible Chat/Embedding/Reranker",
            ],
        }
        manifest_path = stage / "release-manifest.json"
        manifest_path.write_text(
            f"{json.dumps(manifest, indent=2, sort_keys=True)}\n", encoding="utf-8"
        )
        output_dir.mkdir(parents=True, mode=0o755)
        bundle_name = f"datariver-prep39083-{source['product_sha'][:12]}-amd64.tar.gz"
        bundle = output_dir / bundle_name
        with tarfile.open(bundle, "w:gz") as archive:
            for path in sorted(stage.iterdir(), key=lambda item: item.name):
                archive.add(path, arcname=path.name, recursive=path.is_dir())
        checksum = sha256_file(bundle)
        checksum_path = output_dir / f"{bundle.name}.sha256"
        checksum_path.write_text(f"{checksum}  {bundle.name}\n", encoding="ascii")
    print(
        json.dumps(
            {
                "result": "PREP_TESTED_IMAGES_EXPORTED",
                "bundle": os.fspath(bundle),
                "bundle_sha256": checksum,
                "product_sha": source["product_sha"],
                "evidence_sha": source["evidence_sha"],
                "image_count": len(images),
            },
            sort_keys=True,
        )
    )


def verify_release(arguments: argparse.Namespace) -> None:
    bundle = arguments.bundle.expanduser().resolve()
    checksum_file = arguments.checksum_file.expanduser().resolve()
    fields = checksum_file.read_text(encoding="ascii").strip().split()
    if len(fields) != 2 or fields[1] != bundle.name or fields[0] != sha256_file(bundle):
        raise ReleaseError("release bundle SHA-256 verification failed")
    with tempfile.TemporaryDirectory(prefix="datariver-prep39083-verify-") as temporary:
        target = Path(temporary)
        with tarfile.open(bundle, "r:gz") as archive:
            members = safe_archive_members(archive)
            archive.extractall(target, members=members)  # noqa: S202 - members are rejected above.
        required = {
            "images.tar",
            "release-manifest.json",
            BASE_COMPOSE.name,
            OPS_COMPOSE.name,
            OPS_ENV_EXAMPLE.name,
            ENV_CONTRACT.name,
            PREP_OPTIONAL_ENV_EXAMPLE.name,
            PREP_GUIDE.name,
            OPS_GUIDE.name,
            RELEASE_GUIDE.name,
            PREP_ENTRYPOINT.name,
            DEPLOY_TOOL.name,
            RELEASE_TOOL.name,
            SMOKE_TOOL.name,
            POSTGRES_INIT.name,
        }
        observed = {item.name for item in target.iterdir()}
        if observed != required:
            raise ReleaseError("release bundle inventory is incomplete or unexpected")
        manifest = json.loads((target / "release-manifest.json").read_text(encoding="utf-8"))
        if manifest.get("contract") != CONTRACT or manifest.get("architecture") != "linux/amd64":
            raise ReleaseError("release manifest contract/platform is invalid")
        if manifest.get("image_archive_sha256") != sha256_file(target / "images.tar"):
            raise ReleaseError("images.tar checksum does not match the release manifest")
        if manifest.get("postgres_init_sha256") != sha256_tree(target / POSTGRES_INIT.name):
            raise ReleaseError("PostgreSQL initialization checksum does not match the manifest")
        if not SHA_PATTERN.fullmatch(str(manifest.get("product_sha", ""))):
            raise ReleaseError("release manifest Product SHA is invalid")
        if not SHA_PATTERN.fullmatch(str(manifest.get("evidence_sha", ""))):
            raise ReleaseError("release manifest Evidence SHA is invalid")
        if len(manifest.get("images", [])) != len(SERVICES):
            raise ReleaseError("release manifest does not bind every Compose image")
    print(
        json.dumps(
            {
                "result": "ARTIFACT_ONLY_VERIFICATION_PASS",
                "bundle": os.fspath(bundle),
                "bundle_sha256": fields[0],
                "product_sha": manifest["product_sha"],
                "evidence_sha": manifest["evidence_sha"],
            },
            sort_keys=True,
        )
    )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    source = subparsers.add_parser(
        "source-check", help="verify Product/Evidence ancestry and runtime-input stability"
    )
    source.add_argument("--product-sha", required=True)
    source.add_argument("--evidence-sha", required=True)
    source.add_argument("--allow-dirty", action="store_true")
    export = subparsers.add_parser(
        "export", help="export exact running PREP-tested images without building"
    )
    export.add_argument("--product-sha", required=True)
    export.add_argument("--evidence-sha", required=True)
    export.add_argument("--env-file", type=Path, required=True)
    export.add_argument("--output-dir", type=Path, required=True)
    export.add_argument("--project-name", default="datariver-prep39083")
    verify = subparsers.add_parser("verify", help="verify a release bundle without loading images")
    verify.add_argument("--bundle", type=Path, required=True)
    verify.add_argument("--checksum-file", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    if arguments.action == "source-check":
        print(
            json.dumps(
                {
                    "result": "SOURCE_CONTRACT_PASS",
                    **source_contract(
                        arguments.product_sha,
                        arguments.evidence_sha,
                        clean=not arguments.allow_dirty,
                    ),
                },
                sort_keys=True,
            )
        )
    elif arguments.action == "export":
        export_release(arguments)
    else:
        verify_release(arguments)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, json.JSONDecodeError, ReleaseError) as error:
        print(f"PREP39083_RELEASE_ERROR: {error}", file=sys.stderr)
        raise SystemExit(2) from error
