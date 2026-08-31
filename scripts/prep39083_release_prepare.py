#!/usr/bin/env python3
"""Prepare one exact PREP39083 release without touching a development worktree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from prep39083_release import RUNTIME_INPUTS
from prep39083_transport import TRANSPORT_CONTRACT

ROOT = Path(__file__).resolve().parents[1]
RELEASE_REF = "prep39083-release"
ARTIFACT_BRANCH_PREFIX = "prep39083-artifact-"
CHUNK_SIZE = 48 * 1024 * 1024
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class PrepareError(RuntimeError):
    def __init__(self, step: str, code: str, reason: str, action: str) -> None:
        super().__init__(reason)
        self.step = step
        self.code = code
        self.reason = reason
        self.action = action


@dataclass(frozen=True)
class PreparedRelease:
    product_sha: str
    evidence_sha: str
    artifact_handoff_sha: str
    release_snapshot_sha: str
    artifact_branch: str
    artifact_commit: str
    archive_sha256: str


def run(
    arguments: Sequence[str | os.PathLike[str]],
    *,
    cwd: Path,
    check: bool = True,
    input_text: str | None = None,
    visible: bool = False,
) -> subprocess.CompletedProcess[str]:
    command = [os.fspath(item) for item in arguments]
    completed = subprocess.run(  # noqa: S603 - argv only; no shell interpolation.
        command,
        cwd=cwd,
        check=False,
        capture_output=not visible,
        text=True,
        input=input_text,
    )
    if check and completed.returncode != 0:
        raise PrepareError(
            "COMMAND",
            "PREP_RELEASE_COMMAND_FAILED",
            f"Release command failed at {command[0]} {command[1] if len(command) > 1 else ''}.",
            "Preserve the Product and inspect the bounded command output; "
            "do not publish a release.",
        )
    return completed


def output(arguments: Sequence[str | os.PathLike[str]], *, cwd: Path) -> str:
    return run(arguments, cwd=cwd).stdout.strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def remote_ref(remote_url: str, ref: str, *, cwd: Path) -> str | None:
    lines = output(["git", "ls-remote", "--heads", remote_url, ref], cwd=cwd).splitlines()
    if not lines:
        return None
    if len(lines) != 1:
        raise PrepareError(
            "SOURCE_SELECTION",
            "PREP_RELEASE_REMOTE_REF_AMBIGUOUS",
            f"Remote ref {ref} did not resolve exactly once.",
            "Inspect repository refs without changing them.",
        )
    sha, observed = lines[0].split("\t", 1)
    if observed != f"refs/heads/{ref}" or not SHA_PATTERN.fullmatch(sha):
        raise PrepareError(
            "SOURCE_SELECTION",
            "PREP_RELEASE_REMOTE_REF_INVALID",
            f"Remote ref {ref} has an invalid identity.",
            "Correct the remote ref before preparing another release.",
        )
    return sha


def validate_product(product_sha: str, *, repository: Path, origin_dev: str) -> None:
    if not SHA_PATTERN.fullmatch(product_sha):
        raise PrepareError(
            "PRODUCT_SELECTION",
            "PREP_RELEASE_PRODUCT_SHA_INVALID",
            "Product SHA must be one exact lowercase 40-character commit.",
            "Choose a committed Product SHA from development history.",
        )
    exists = run(
        ["git", "cat-file", "-e", f"{product_sha}^{{commit}}"],
        cwd=repository,
        check=False,
    )
    ancestry = run(
        ["git", "merge-base", "--is-ancestor", product_sha, origin_dev],
        cwd=repository,
        check=False,
    )
    if exists.returncode != 0 or ancestry.returncode != 0:
        raise PrepareError(
            "PRODUCT_SELECTION",
            "PREP_RELEASE_PRODUCT_NOT_ON_DEV",
            "The selected Product is not a committed ancestor of current origin/dev.",
            "Push the verified Product to dev or select an existing dev ancestor.",
        )
    parent = run(["git", "rev-parse", f"{product_sha}^"], cwd=repository, check=False)
    if parent.returncode == 0:
        changed = set(
            output(
                ["git", "diff", "--name-only", parent.stdout.strip(), product_sha, "--"],
                cwd=repository,
            ).splitlines()
        )
        runtime_change = any(
            path == item or path.startswith(f"{item}/")
            for path in changed
            for item in RUNTIME_INPUTS
        )
        if not runtime_change:
            raise PrepareError(
                "PRODUCT_SELECTION",
                "PREP_RELEASE_METADATA_COMMIT_SELECTED",
                "The selected commit changes no Product runtime input and appears release-only.",
                "Select the committed Product source checkpoint, not Evidence or Handoff metadata.",
            )


def create_release_base(
    checkout: Path,
    *,
    product_sha: str,
    previous_release: str | None,
) -> str:
    if previous_release is None:
        run(["git", "switch", "-c", RELEASE_REF, product_sha], cwd=checkout)
        return product_sha
    tree = output(["git", "rev-parse", f"{product_sha}^{{tree}}"], cwd=checkout)
    bridge = run(
        [
            "git",
            "commit-tree",
            tree,
            "-p",
            previous_release,
            "-p",
            product_sha,
        ],
        cwd=checkout,
        input_text=f"chore(release): integrate Product {product_sha}\n",
    ).stdout.strip()
    if not SHA_PATTERN.fullmatch(bridge):
        raise PrepareError(
            "RELEASE_LINEAGE",
            "PREP_RELEASE_BRIDGE_INVALID",
            "The dedicated release lineage bridge was not created.",
            "Preserve both refs and inspect Git identity configuration.",
        )
    run(["git", "switch", "-c", RELEASE_REF, bridge], cwd=checkout)
    return bridge


def run_product_gates(build_checkout: Path, product_sha: str, output_dir: Path) -> dict[str, Any]:
    run(["git", "switch", "-c", "dev", product_sha], cwd=build_checkout)
    if output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=build_checkout):
        raise PrepareError(
            "CLEAN_CHECKOUT",
            "PREP_RELEASE_CHECKOUT_DIRTY",
            "The disposable Product checkout is not clean.",
            "Discard only the disposable checkout and retry.",
        )
    run(
        ["uv", "run", "--frozen", "python", "scripts/verify_static.py"],
        cwd=build_checkout,
        visible=True,
    )
    run(["npm", "ci", "--ignore-scripts"], cwd=build_checkout / "frontend", visible=True)
    run(["npm", "run", "build:poc"], cwd=build_checkout / "frontend", visible=True)
    run(["npm", "run", "test:poc-server"], cwd=build_checkout / "frontend", visible=True)
    run(
        [
            "uv",
            "run",
            "--frozen",
            "--extra",
            "dev",
            "pytest",
            "-q",
            "backend/tests/unit/test_prep39083_handoff_contract.py",
            "backend/tests/unit/test_prep39083_artifact.py",
            "backend/tests/unit/test_prep39083_product_artifact.py",
            "backend/tests/unit/test_prep39083_deploy.py",
            "backend/tests/unit/test_prep39083_transport.py",
            "backend/tests/unit/test_prep39083_release_prepare.py",
        ],
        cwd=build_checkout,
        visible=True,
    )
    run(
        [
            "uv",
            "run",
            "--frozen",
            "python",
            "scripts/prep39083_product_artifact.py",
            "--product-sha",
            product_sha,
            "--output-dir",
            output_dir,
        ],
        cwd=build_checkout,
        visible=True,
    )
    manifest_path = output_dir / "artifact-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PrepareError(
            "ARTIFACT_BUILD",
            "PREP_RELEASE_ARTIFACT_MANIFEST_INVALID",
            "Canonical artifact export did not produce a valid manifest.",
            "Do not publish the candidate; inspect the canonical build result.",
        ) from error
    if not isinstance(manifest, dict) or manifest.get("product_sha") != product_sha:
        raise PrepareError(
            "ARTIFACT_BUILD",
            "PREP_RELEASE_ARTIFACT_IDENTITY_INVALID",
            "Canonical artifact identity does not match the selected Product.",
            "Do not publish or reuse the generated archive.",
        )
    return manifest


def commit_all(checkout: Path, message: str) -> str:
    run(["git", "add", "--all"], cwd=checkout)
    run(["git", "commit", "-m", message], cwd=checkout)
    sha = output(["git", "rev-parse", "HEAD"], cwd=checkout)
    if not SHA_PATTERN.fullmatch(sha):
        raise PrepareError(
            "RELEASE_METADATA",
            "PREP_RELEASE_COMMIT_INVALID",
            "Release metadata commit identity is invalid.",
            "Do not publish the candidate.",
        )
    return sha


def write_evidence(
    checkout: Path,
    *,
    product_sha: str,
    artifact_manifest: dict[str, Any],
) -> Path:
    path = (
        checkout
        / "docs/evidence"
        / f"prep39083-automated-release-{product_sha[:12]}"
        / "README.md"
    )
    path.parent.mkdir(parents=True, exist_ok=False)
    archive = str(artifact_manifest["archive"])
    archive_path = ROOT / "dist" / f"prep39083-web-{product_sha}" / archive
    payload = f"""# PREP39083 automated release evidence

Recorded: {datetime.now(UTC).isoformat()}  
Product: `{product_sha}`

- Disposable clean `dev` checkout: PASS
- Static/source integrity gate: PASS
- Full applicable POC Node regression: PASS
- PREP release/transport contract tests: PASS
- Exact linux/amd64 Node runtime artifact preflight: PASS
- Archive: `{archive}`
- Archive size: `{archive_path.stat().st_size}` bytes
- Archive SHA-256: `{artifact_manifest['archive_sha256']}`
- Manifest digest: `{artifact_manifest['manifest_digest']}`
- Config digest: `{artifact_manifest['config_digest']}`
- OCI revision: `{artifact_manifest['oci_revision']}`
- Runtime input after Product: NONE
- Actual PREP deploy: NOT EXECUTED
- Reset/resecret: NONE
- User metadata mutation: NONE
"""
    path.write_text(payload, encoding="utf-8")
    return path


def update_release_json(
    checkout: Path,
    *,
    product_sha: str,
    evidence_sha: str,
    artifact_manifest: dict[str, Any],
) -> None:
    path = checkout / "deploy/prep39083/release.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document.update(
        {
            "product_sha": product_sha,
            "evidence_sha": evidence_sha,
            "handoff_commit_policy": "CURRENT_COMMITTED_HEAD",
            "web_artifact": artifact_manifest["release_json_web_artifact"],
        }
    )
    path.write_text(f"{json.dumps(document, indent=2)}\n", encoding="utf-8")


def split_archive(archive: Path, destination: Path) -> tuple[str, ...]:
    destination.mkdir(parents=True, exist_ok=False)
    names: list[str] = []
    with archive.open("rb") as source:
        index = 0
        while True:
            payload = source.read(CHUNK_SIZE)
            if not payload:
                break
            name = f"{archive.name}.part-{index:03d}"
            (destination / name).write_bytes(payload)
            names.append(name)
            index += 1
    return tuple(names)


def prepare_artifact_branch(
    *,
    remote_url: str,
    product_sha: str,
    handoff_sha: str,
    archive: Path,
    archive_sha256: str,
    workspace: Path,
) -> tuple[str, str, str, tuple[str, ...]]:
    branch = f"{ARTIFACT_BRANCH_PREFIX}{product_sha[:12]}"
    if remote_ref(remote_url, branch, cwd=ROOT) is not None:
        raise PrepareError(
            "ARTIFACT_TRANSPORT",
            "PREP_RELEASE_ARTIFACT_BRANCH_EXISTS",
            "The immutable Product artifact branch already exists.",
            "Use the existing completed release or select a new Product; never overwrite it.",
        )
    repository = workspace / "transport"
    repository.mkdir()
    run(["git", "init"], cwd=repository)
    run(["git", "remote", "add", "origin", remote_url], cwd=repository)
    run(["git", "switch", "--orphan", branch], cwd=repository)
    tree_path = f"prep39083/{product_sha}"
    target = repository / tree_path
    chunks = split_archive(archive, target)
    (target / f"{archive.name}.sha256").write_text(
        f"{archive_sha256}  {archive.name}\n",
        encoding="ascii",
    )
    branch_manifest = {
        "contract": "DATARIVER_PREP39083_GIT_ARTIFACT_TRANSPORT_V1",
        "purpose": "TRANSPORT_ONLY_NOT_PRODUCT_SOURCE",
        "product_sha": product_sha,
        "handoff_sha": handoff_sha,
        "original_filename": archive.name,
        "original_size": archive.stat().st_size,
        "original_sha256": archive_sha256,
        "chunk_size": CHUNK_SIZE,
        "chunk_count": len(chunks),
        "chunks": list(chunks),
    }
    (target / "transfer-manifest.json").write_text(
        f"{json.dumps(branch_manifest, indent=2)}\n",
        encoding="utf-8",
    )
    reconstructed = workspace / archive.name
    with reconstructed.open("wb") as destination:
        for name in chunks:
            with (target / name).open("rb") as source:
                shutil.copyfileobj(source, destination, length=1024 * 1024)
    if (
        reconstructed.stat().st_size != archive.stat().st_size
        or sha256_file(reconstructed) != archive_sha256
    ):
        raise PrepareError(
            "ARTIFACT_TRANSPORT",
            "PREP_RELEASE_LOCAL_RECONSTRUCTION_FAILED",
            "Local artifact chunk reconstruction differs from the exact archive.",
            "Do not push the artifact branch.",
        )
    run(["git", "add", "prep39083"], cwd=repository)
    run(
        ["git", "commit", "-m", f"chore(artifact): transport {product_sha[:12]} PREP image"],
        cwd=repository,
    )
    commit = output(["git", "rev-parse", "HEAD"], cwd=repository)
    run(["git", "push", "origin", f"HEAD:refs/heads/{branch}"], cwd=repository, visible=True)
    if remote_ref(remote_url, branch, cwd=ROOT) != commit:
        raise PrepareError(
            "ARTIFACT_TRANSPORT",
            "PREP_RELEASE_ARTIFACT_PUSH_UNVERIFIED",
            "The pushed artifact branch identity could not be verified.",
            "Do not advance the dedicated release ref.",
        )
    return branch, commit, tree_path, chunks


def simulate_remote_extraction(
    *,
    remote_url: str,
    artifact_branch: str,
    artifact_commit: str,
    tree_path: str,
    archive: Path,
    archive_sha256: str,
    chunks: tuple[str, ...],
    workspace: Path,
) -> None:
    checkout = workspace / "remote-extraction"
    run(["git", "clone", "--no-checkout", remote_url, checkout], cwd=ROOT)
    run(["git", "fetch", "--no-tags", "origin", artifact_branch], cwd=checkout)
    if output(["git", "rev-parse", "FETCH_HEAD"], cwd=checkout) != artifact_commit:
        raise PrepareError(
            "ARTIFACT_TRANSPORT",
            "PREP_RELEASE_REMOTE_COMMIT_MISMATCH",
            "Fresh-clone artifact fetch did not resolve the pinned commit.",
            "Do not advance the dedicated release ref.",
        )
    branch_archive = workspace / "remote-artifact-branch.tar"
    run(
        [
            "git",
            "archive",
            "--format=tar",
            f"--output={branch_archive}",
            artifact_commit,
            tree_path,
        ],
        cwd=checkout,
    )
    extraction = workspace / "remote-tree"
    with tarfile.open(branch_archive, "r:") as bundle:
        members = bundle.getmembers()
        if any(
            member.issym() or member.islnk() or ".." in Path(member.name).parts
            for member in members
        ):
            raise PrepareError(
                "ARTIFACT_TRANSPORT",
                "PREP_RELEASE_REMOTE_ARCHIVE_UNSAFE",
                "Fresh-clone artifact tree contains an unsafe member.",
                "Do not advance the dedicated release ref.",
            )
        bundle.extractall(extraction, members=members, filter="data")
    source = extraction / tree_path
    reconstructed = workspace / f"remote-{archive.name}"
    with reconstructed.open("wb") as destination:
        for name in chunks:
            with (source / name).open("rb") as chunk:
                shutil.copyfileobj(chunk, destination, length=1024 * 1024)
    if (
        reconstructed.stat().st_size != archive.stat().st_size
        or sha256_file(reconstructed) != archive_sha256
    ):
        raise PrepareError(
            "ARTIFACT_TRANSPORT",
            "PREP_RELEASE_REMOTE_RECONSTRUCTION_FAILED",
            "Fresh-clone artifact reconstruction differs from the exact archive.",
            "Do not advance the dedicated release ref.",
        )


def write_transport_json(
    checkout: Path,
    *,
    product_sha: str,
    evidence_sha: str,
    handoff_sha: str,
    artifact_branch: str,
    artifact_commit: str,
    tree_path: str,
    archive: Path,
    archive_sha256: str,
    chunks: tuple[str, ...],
) -> None:
    document = {
        "contract": TRANSPORT_CONTRACT,
        "product_sha": product_sha,
        "evidence_sha": evidence_sha,
        "handoff_sha": handoff_sha,
        "artifact_branch": artifact_branch,
        "artifact_commit": artifact_commit,
        "tree_path": tree_path,
        "archive_filename": archive.name,
        "archive_size": archive.stat().st_size,
        "archive_sha256": archive_sha256,
        "checksum_filename": f"{archive.name}.sha256",
        "chunk_size": CHUNK_SIZE,
        "chunk_count": len(chunks),
        "ordered_chunks": list(chunks),
    }
    path = checkout / "deploy/prep39083/transport.json"
    path.write_text(f"{json.dumps(document, indent=2)}\n", encoding="utf-8")


def prepare(product_sha: str) -> PreparedRelease:
    remote_url = output(["git", "remote", "get-url", "origin"], cwd=ROOT)
    run(["git", "fetch", "origin", "dev"], cwd=ROOT)
    origin_dev = output(["git", "rev-parse", "origin/dev"], cwd=ROOT)
    validate_product(product_sha, repository=ROOT, origin_dev=origin_dev)
    previous_release = remote_ref(remote_url, RELEASE_REF, cwd=ROOT)
    artifact_branch = f"{ARTIFACT_BRANCH_PREFIX}{product_sha[:12]}"
    if remote_ref(remote_url, artifact_branch, cwd=ROOT) is not None:
        raise PrepareError(
            "PRODUCT_SELECTION",
            "PREP_RELEASE_PRODUCT_ALREADY_PREPARED",
            "This Product already has an immutable artifact transport branch.",
            "Use its dedicated release snapshot or choose a new Product.",
        )
    output_dir = ROOT / "dist" / f"prep39083-web-{product_sha}"
    if output_dir.exists():
        raise PrepareError(
            "ARTIFACT_BUILD",
            "PREP_RELEASE_OUTPUT_EXISTS",
            "The canonical output directory already exists.",
            "Verify and preserve the existing release; do not overwrite it.",
        )
    with tempfile.TemporaryDirectory(prefix="datariver-prep39083-prepare-") as name:
        workspace = Path(name)
        build_checkout = workspace / "build"
        release_checkout = workspace / "release"
        run(["git", "clone", "--no-checkout", remote_url, build_checkout], cwd=ROOT)
        run(["git", "clone", "--no-checkout", remote_url, release_checkout], cwd=ROOT)
        create_release_base(
            release_checkout,
            product_sha=product_sha,
            previous_release=previous_release,
        )
        artifact_manifest = run_product_gates(build_checkout, product_sha, output_dir)
        write_evidence(
            release_checkout,
            product_sha=product_sha,
            artifact_manifest=artifact_manifest,
        )
        evidence_sha = commit_all(
            release_checkout,
            "docs(evidence): record automated PREP release",
        )
        update_release_json(
            release_checkout,
            product_sha=product_sha,
            evidence_sha=evidence_sha,
            artifact_manifest=artifact_manifest,
        )
        artifact_handoff = commit_all(
            release_checkout,
            "chore(release): pin automated PREP artifact",
        )
        run(
            [
                "uv",
                "run",
                "--frozen",
                "python",
                "scripts/prep39083_release.py",
                "source-check",
                "--product-sha",
                product_sha,
                "--evidence-sha",
                evidence_sha,
            ],
            cwd=release_checkout,
            visible=True,
        )
        archive = output_dir / str(artifact_manifest["archive"])
        archive_sha256 = str(artifact_manifest["archive_sha256"])
        branch, artifact_commit, tree_path, chunks = prepare_artifact_branch(
            remote_url=remote_url,
            product_sha=product_sha,
            handoff_sha=artifact_handoff,
            archive=archive,
            archive_sha256=archive_sha256,
            workspace=workspace,
        )
        simulate_remote_extraction(
            remote_url=remote_url,
            artifact_branch=branch,
            artifact_commit=artifact_commit,
            tree_path=tree_path,
            archive=archive,
            archive_sha256=archive_sha256,
            chunks=chunks,
            workspace=workspace,
        )
        write_transport_json(
            release_checkout,
            product_sha=product_sha,
            evidence_sha=evidence_sha,
            handoff_sha=artifact_handoff,
            artifact_branch=branch,
            artifact_commit=artifact_commit,
            tree_path=tree_path,
            archive=archive,
            archive_sha256=archive_sha256,
            chunks=chunks,
        )
        release_snapshot = commit_all(
            release_checkout,
            "chore(release): pin PREP Git transport",
        )
        run(
            [
                "uv",
                "run",
                "--frozen",
                "python",
                "scripts/prep39083_release.py",
                "source-check",
                "--product-sha",
                product_sha,
                "--evidence-sha",
                evidence_sha,
            ],
            cwd=release_checkout,
            visible=True,
        )
        if remote_ref(remote_url, RELEASE_REF, cwd=ROOT) != previous_release:
            raise PrepareError(
                "RELEASE_PUBLICATION",
                "PREP_RELEASE_REF_CONCURRENT_UPDATE",
                "The dedicated PREP release ref advanced during preparation.",
                "Keep both candidates and rerun from the new ref; do not overwrite it.",
            )
        run(
            ["git", "push", "origin", f"{release_snapshot}:refs/heads/{RELEASE_REF}"],
            cwd=release_checkout,
            visible=True,
        )
        if remote_ref(remote_url, RELEASE_REF, cwd=ROOT) != release_snapshot:
            raise PrepareError(
                "RELEASE_PUBLICATION",
                "PREP_RELEASE_REF_PUSH_UNVERIFIED",
                "The dedicated PREP release ref did not reach the exact snapshot.",
                "Do not deploy; inspect the remote ref without rewriting it.",
            )
        return PreparedRelease(
            product_sha,
            evidence_sha,
            artifact_handoff,
            release_snapshot,
            branch,
            artifact_commit,
            archive_sha256,
        )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--product-sha", required=True)
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    try:
        result = prepare(arguments.product_sha)
    except PrepareError as error:
        print("FAILED", file=sys.stderr)
        print(f"Step: {error.step}", file=sys.stderr)
        print(f"Code: {error.code}", file=sys.stderr)
        print(f"Reason: {error.reason}", file=sys.stderr)
        print(f"Action: {error.action}", file=sys.stderr)
        raise SystemExit(2) from error
    print("PREP39083 RELEASE READY")
    print(f"Product: {result.product_sha}")
    print(f"Evidence: {result.evidence_sha}")
    print(f"Handoff: {result.release_snapshot_sha}")
    print(f"Artifact branch: {result.artifact_branch}")
    print(f"Artifact commit: {result.artifact_commit}")
    print(f"Archive SHA-256: {result.archive_sha256}")
    print(f"PREP source ref: origin/{RELEASE_REF}")


if __name__ == "__main__":
    main()
