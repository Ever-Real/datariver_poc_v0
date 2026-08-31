#!/usr/bin/env python3
"""Exact Git-transport retrieval for one PREP39083 Product archive."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from prep39083_artifact import (
    ArtifactError,
    WebArtifactIdentity,
    inspect_web_archive,
    require_expected_identity,
)

TRANSPORT_CONTRACT = "DATARIVER_PREP39083_GIT_ARTIFACT_TRANSPORT_V2"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
BRANCH_PATTERN = re.compile(r"^prep39083-artifact-[0-9a-f]{12}$")
CHUNK_PATTERN = re.compile(r"^datariver-poc-[0-9a-f]{40}-linux-amd64\.tar\.part-[0-9]{3}$")


class TransportError(RuntimeError):
    """One fail-closed artifact transport contract failure."""


@dataclass(frozen=True)
class GitTransportIdentity:
    product_sha: str
    evidence_sha: str
    handoff_sha: str
    artifact_branch: str
    artifact_commit: str
    tree_path: str
    archive_filename: str
    archive_size: int
    archive_sha256: str
    checksum_filename: str
    chunk_size: int
    ordered_chunks: tuple[str, ...]

    @property
    def chunk_count(self) -> int:
        return len(self.ordered_chunks)


def _require_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA_PATTERN.fullmatch(value):
        raise TransportError(f"{label} is not one exact Git SHA")
    return value


def _safe_tree_path(value: object) -> str:
    if not isinstance(value, str):
        raise TransportError("transport tree path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or len(path.parts) != 2:
        raise TransportError("transport tree path is unsafe")
    return value


def load_transport_identity(
    document: Mapping[str, Any],
    *,
    product_sha: str,
    evidence_sha: str,
    artifact: WebArtifactIdentity,
) -> GitTransportIdentity:
    if document.get("contract") != TRANSPORT_CONTRACT:
        raise TransportError("transport contract is unsupported")
    observed_product = _require_sha(document.get("product_sha"), "transport Product")
    observed_evidence = _require_sha(document.get("evidence_sha"), "transport Evidence")
    handoff_sha = _require_sha(document.get("handoff_sha"), "transport Handoff")
    artifact_commit = _require_sha(document.get("artifact_commit"), "artifact commit")
    branch = document.get("artifact_branch")
    if not isinstance(branch, str) or not BRANCH_PATTERN.fullmatch(branch):
        raise TransportError("artifact branch identity is invalid")
    tree_path = _safe_tree_path(document.get("tree_path"))
    archive_filename = document.get("archive_filename")
    checksum_filename = document.get("checksum_filename")
    archive_size = document.get("archive_size")
    archive_sha256 = document.get("archive_sha256")
    chunk_size = document.get("chunk_size")
    chunks = document.get("ordered_chunks")
    expected_archive = f"datariver-poc-{product_sha}-linux-amd64.tar"
    if (
        observed_product != product_sha
        or observed_evidence != evidence_sha
        or archive_filename != expected_archive
        or checksum_filename != f"{expected_archive}.sha256"
        or not isinstance(archive_size, int)
        or archive_size <= 0
        or not isinstance(archive_sha256, str)
        or not SHA256_PATTERN.fullmatch(archive_sha256)
        or archive_sha256 != artifact.archive_sha256
        or not isinstance(chunk_size, int)
        or chunk_size <= 0
        or chunk_size > 48 * 1024 * 1024
        or not isinstance(chunks, list)
        or not chunks
        or len(chunks) > 999
        or any(not isinstance(item, str) or not CHUNK_PATTERN.fullmatch(item) for item in chunks)
        or len(chunks) != len(set(chunks))
    ):
        raise TransportError("transport artifact identity is inconsistent")
    expected_chunks = tuple(
        f"{expected_archive}.part-{index:03d}" for index in range(len(chunks))
    )
    if tuple(chunks) != expected_chunks:
        raise TransportError("transport chunks are not in canonical deterministic order")
    if tree_path != f"prep39083/{product_sha}":
        raise TransportError("transport tree path does not match the Product")
    return GitTransportIdentity(
        product_sha=observed_product,
        evidence_sha=observed_evidence,
        handoff_sha=handoff_sha,
        artifact_branch=branch,
        artifact_commit=artifact_commit,
        tree_path=tree_path,
        archive_filename=archive_filename,
        archive_size=archive_size,
        archive_sha256=archive_sha256,
        checksum_filename=checksum_filename,
        chunk_size=chunk_size,
        ordered_chunks=expected_chunks,
    )


def read_transport_identity(
    path: Path,
    *,
    product_sha: str,
    evidence_sha: str,
    artifact: WebArtifactIdentity,
) -> GitTransportIdentity:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TransportError("tracked transport manifest is unreadable") from error
    if not isinstance(document, dict):
        raise TransportError("tracked transport manifest is not an object")
    return load_transport_identity(
        document,
        product_sha=product_sha,
        evidence_sha=evidence_sha,
        artifact=artifact,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run(
    arguments: Sequence[str | os.PathLike[str]],
    *,
    root: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    command = [os.fspath(item) for item in arguments]
    completed = subprocess.run(  # noqa: S603 - argv only; no shell interpolation.
        command,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if check and completed.returncode != 0:
        raise TransportError(f"Git transport command failed: {command[1]}")
    return completed


def _safe_extract(archive: Path, destination: Path, identity: GitTransportIdentity) -> Path:
    expected_files = {
        *identity.ordered_chunks,
        identity.checksum_filename,
        "transfer-manifest.json",
    }
    expected_prefix = PurePosixPath(identity.tree_path)
    with tarfile.open(archive, "r:") as bundle:
        members = bundle.getmembers()
        observed: set[str] = set()
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
                raise TransportError("artifact branch archive contains an unsafe member")
            if member.isfile():
                try:
                    relative = path.relative_to(expected_prefix)
                except ValueError as error:
                    raise TransportError(
                        "artifact branch archive escaped its pinned tree"
                    ) from error
                if len(relative.parts) != 1:
                    raise TransportError("artifact branch archive has an unexpected nested file")
                observed.add(relative.name)
            elif not member.isdir():
                raise TransportError("artifact branch archive has an unsupported member")
        if observed != expected_files:
            raise TransportError("artifact branch inventory is incomplete or unexpected")
        bundle.extractall(
            destination,
            members=members,
            filter="data",
        )
    return destination / identity.tree_path


def _validate_branch_manifest(path: Path, identity: GitTransportIdentity) -> None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TransportError("artifact branch manifest is unreadable") from error
    expected = {
        "contract": "DATARIVER_PREP39083_GIT_ARTIFACT_TRANSPORT_V1",
        "purpose": "TRANSPORT_ONLY_NOT_PRODUCT_SOURCE",
        "product_sha": identity.product_sha,
        "handoff_sha": identity.handoff_sha,
        "original_filename": identity.archive_filename,
        "original_size": identity.archive_size,
        "original_sha256": identity.archive_sha256,
        "chunk_size": identity.chunk_size,
        "chunk_count": identity.chunk_count,
        "chunks": list(identity.ordered_chunks),
    }
    if document != expected:
        raise TransportError("artifact branch manifest differs from the tracked transport identity")


def _validate_sidecar(path: Path, identity: GitTransportIdentity) -> None:
    try:
        fields = path.read_text(encoding="ascii").strip().split()
    except OSError as error:
        raise TransportError("artifact checksum sidecar is unreadable") from error
    if fields != [identity.archive_sha256, identity.archive_filename]:
        raise TransportError("artifact checksum sidecar differs from the tracked identity")


def retrieve_git_artifact(
    identity: GitTransportIdentity,
    *,
    root: Path,
    artifact: WebArtifactIdentity,
) -> str:
    target = root / artifact.relative_path
    if target.exists():
        try:
            if target.stat().st_size != identity.archive_size:
                raise TransportError("existing promoted archive size differs from release identity")
            require_expected_identity(inspect_web_archive(target), artifact)
        except (ArtifactError, OSError) as error:
            raise TransportError(
                "existing promoted archive differs from release identity"
            ) from error
        return "REUSED_EXACT_GIT_ARTIFACT"

    fetched = _run(
        ["git", "fetch", "--no-tags", "origin", identity.artifact_branch],
        root=root,
    )
    del fetched
    observed_commit = _run(["git", "rev-parse", "FETCH_HEAD"], root=root).stdout.strip()
    if observed_commit != identity.artifact_commit:
        raise TransportError("fetched artifact branch does not equal the pinned commit")
    relation = _run(
        ["git", "merge-base", "--is-ancestor", identity.handoff_sha, "HEAD"],
        root=root,
        check=False,
    )
    if relation.returncode != 0:
        raise TransportError("artifact Handoff is outside the checked-out release snapshot")

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".prep39083-transfer-", dir=target.parent) as name:
        temporary = Path(name)
        branch_archive = temporary / "artifact-branch.tar"
        _run(
            [
                "git",
                "archive",
                "--format=tar",
                f"--output={branch_archive}",
                identity.artifact_commit,
                identity.tree_path,
            ],
            root=root,
        )
        extracted = _safe_extract(branch_archive, temporary / "tree", identity)
        _validate_branch_manifest(extracted / "transfer-manifest.json", identity)
        _validate_sidecar(extracted / identity.checksum_filename, identity)
        reconstructed = temporary / identity.archive_filename
        with reconstructed.open("wb") as destination:
            for chunk in identity.ordered_chunks:
                with (extracted / chunk).open("rb") as source:
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
            destination.flush()
            os.fsync(destination.fileno())
        if (
            reconstructed.stat().st_size != identity.archive_size
            or sha256_file(reconstructed) != identity.archive_sha256
        ):
            raise TransportError("reconstructed Product archive size or SHA-256 is invalid")
        try:
            require_expected_identity(inspect_web_archive(reconstructed), artifact)
        except ArtifactError as error:
            raise TransportError("reconstructed Product OCI identity is invalid") from error
        os.replace(reconstructed, target)
        sidecar_target = target.with_name(identity.checksum_filename)
        temporary_sidecar = temporary / identity.checksum_filename
        shutil.copy2(extracted / identity.checksum_filename, temporary_sidecar)
        os.replace(temporary_sidecar, sidecar_target)
    return "RETRIEVED_EXACT_GIT_ARTIFACT"
