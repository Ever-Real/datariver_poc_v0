from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
MODULE_PATH = SCRIPTS / "prep39083_transport.py"


def _load_module() -> ModuleType:
    sys.path.insert(0, os.fspath(SCRIPTS))
    try:
        specification = importlib.util.spec_from_file_location(
            "prep39083_transport_for_test",
            MODULE_PATH,
        )
        assert specification is not None
        assert specification.loader is not None
        module = importlib.util.module_from_spec(specification)
        sys.modules[specification.name] = module
        specification.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(os.fspath(SCRIPTS))


transport = _load_module()


def _git(cwd: Path, *arguments: str, input_text: str | None = None) -> str:
    completed = subprocess.run(  # noqa: S603 - test-owned fixed Git argv.
        ["git", *arguments],  # noqa: S607 - Git is the tested operator dependency.
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        input=input_text,
    )
    return completed.stdout.strip()


def _member(bundle: tarfile.TarFile, name: str, payload: bytes) -> None:
    item = tarfile.TarInfo(name)
    item.size = len(payload)
    bundle.addfile(item, io.BytesIO(payload))


def _oci_archive(path: Path, revision: str) -> None:
    def encoded(value: object) -> bytes:
        return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()

    config = encoded(
        {
            "architecture": "amd64",
            "config": {"Labels": {"org.opencontainers.image.revision": revision}},
            "os": "linux",
        }
    )
    config_digest = f"sha256:{hashlib.sha256(config).hexdigest()}"
    layer = b"bounded-layer"
    layer_digest = f"sha256:{hashlib.sha256(layer).hexdigest()}"
    manifest = encoded(
        {
            "config": {
                "digest": config_digest,
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "size": len(config),
            },
            "layers": [
                {
                    "digest": layer_digest,
                    "mediaType": "application/vnd.oci.image.layer.v1.tar",
                    "size": len(layer),
                }
            ],
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "schemaVersion": 2,
        }
    )
    manifest_digest = f"sha256:{hashlib.sha256(manifest).hexdigest()}"
    config_path = f"blobs/sha256/{config_digest.removeprefix('sha256:')}"
    layer_path = f"blobs/sha256/{layer_digest.removeprefix('sha256:')}"
    manifest_path = f"blobs/sha256/{manifest_digest.removeprefix('sha256:')}"
    index = encoded(
        {
            "manifests": [
                {
                    "annotations": {"org.opencontainers.image.ref.name": revision},
                    "digest": manifest_digest,
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "platform": {"architecture": "amd64", "os": "linux"},
                    "size": len(manifest),
                }
            ],
            "schemaVersion": 2,
        }
    )
    docker_manifest = encoded(
        [
            {
                "Config": config_path,
                "Layers": [layer_path],
                "RepoTags": [f"datariver-poc:{revision}"],
            }
        ]
    )
    with tarfile.open(path, "w") as bundle:
        for name, payload in (
            ("manifest.json", docker_manifest),
            ("index.json", index),
            ("oci-layout", encoded({"imageLayoutVersion": "1.0.0"})),
            (config_path, config),
            (manifest_path, manifest),
            (layer_path, layer),
        ):
            _member(bundle, name, payload)


def _fixture(tmp_path: Path, *, omit_last_chunk: bool = False) -> tuple[Path, Any, Any]:
    remote = tmp_path / "remote.git"
    subprocess.run(  # noqa: S603 - test-owned fixed Git argv.
        ["git", "init", "--bare", remote],  # noqa: S607 - Git is required by contract.
        check=True,
        capture_output=True,
    )
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init")
    _git(source, "config", "user.email", "test@example.invalid")
    _git(source, "config", "user.name", "test")
    (source / "frontend").mkdir()
    (source / "frontend/product.txt").write_text("product", encoding="utf-8")
    (source / ".gitignore").write_text("runtime/prep39083/artifacts/\n", encoding="utf-8")
    _git(source, "add", ".")
    _git(source, "commit", "-m", "product")
    product = _git(source, "rev-parse", "HEAD")
    _git(source, "remote", "add", "origin", os.fspath(remote))
    _git(source, "push", "origin", "HEAD:dev")

    archive = tmp_path / f"datariver-poc-{product}-linux-amd64.tar"
    _oci_archive(archive, product)
    artifact = transport.inspect_web_archive(archive)
    artifact_repo = tmp_path / "artifact"
    artifact_repo.mkdir()
    _git(artifact_repo, "init")
    _git(artifact_repo, "config", "user.email", "test@example.invalid")
    _git(artifact_repo, "config", "user.name", "test")
    branch = f"prep39083-artifact-{product[:12]}"
    _git(artifact_repo, "switch", "--orphan", branch)
    tree_path = f"prep39083/{product}"
    tree = artifact_repo / tree_path
    tree.mkdir(parents=True)
    payload = archive.read_bytes()
    chunk_size = max(1, len(payload) // 2)
    chunks = tuple(
        f"{archive.name}.part-{index:03d}"
        for index in range((len(payload) + chunk_size - 1) // chunk_size)
    )
    for index, name in enumerate(chunks):
        (tree / name).write_bytes(payload[index * chunk_size : (index + 1) * chunk_size])
    if omit_last_chunk:
        (tree / chunks[-1]).unlink()
    checksum = hashlib.sha256(payload).hexdigest()
    (tree / f"{archive.name}.sha256").write_text(
        f"{checksum}  {archive.name}\n",
        encoding="ascii",
    )
    branch_manifest = {
        "contract": "DATARIVER_PREP39083_GIT_ARTIFACT_TRANSPORT_V1",
        "purpose": "TRANSPORT_ONLY_NOT_PRODUCT_SOURCE",
        "product_sha": product,
        "handoff_sha": product,
        "original_filename": archive.name,
        "original_size": len(payload),
        "original_sha256": checksum,
        "chunk_size": chunk_size,
        "chunk_count": len(chunks),
        "chunks": list(chunks),
    }
    (tree / "transfer-manifest.json").write_text(json.dumps(branch_manifest), encoding="utf-8")
    _git(artifact_repo, "add", ".")
    _git(artifact_repo, "commit", "-m", "artifact")
    artifact_commit = _git(artifact_repo, "rev-parse", "HEAD")
    _git(artifact_repo, "remote", "add", "origin", os.fspath(remote))
    _git(artifact_repo, "push", "origin", f"HEAD:{branch}")

    document = {
        "contract": transport.TRANSPORT_CONTRACT,
        "product_sha": product,
        "evidence_sha": product,
        "handoff_sha": product,
        "artifact_branch": branch,
        "artifact_commit": artifact_commit,
        "tree_path": tree_path,
        "archive_filename": archive.name,
        "archive_size": len(payload),
        "archive_sha256": checksum,
        "checksum_filename": f"{archive.name}.sha256",
        "chunk_size": chunk_size,
        "chunk_count": len(chunks),
        "ordered_chunks": list(chunks),
    }
    identity = transport.load_transport_identity(
        document,
        product_sha=product,
        evidence_sha=product,
        artifact=artifact,
    )
    return source, artifact, identity


def test_git_transport_reconstructs_exact_oci_without_merging_source(tmp_path: Path) -> None:
    source, artifact, identity = _fixture(tmp_path)

    result = transport.retrieve_git_artifact(identity, root=source, artifact=artifact)

    target = source / artifact.relative_path
    assert result == "RETRIEVED_EXACT_GIT_ARTIFACT"
    assert target.stat().st_size == identity.archive_size
    assert transport.sha256_file(target) == identity.archive_sha256
    assert _git(source, "status", "--porcelain", "--untracked-files=all") == ""
    assert transport.retrieve_git_artifact(identity, root=source, artifact=artifact) == (
        "REUSED_EXACT_GIT_ARTIFACT"
    )


def test_git_transport_rejects_missing_chunk_and_wrong_commit(tmp_path: Path) -> None:
    source, artifact, identity = _fixture(tmp_path, omit_last_chunk=True)
    with pytest.raises(transport.TransportError):
        transport.retrieve_git_artifact(identity, root=source, artifact=artifact)

    source_two, artifact_two, identity_two = _fixture(tmp_path / "other")
    wrong = transport.GitTransportIdentity(
        **{**identity_two.__dict__, "artifact_commit": identity_two.product_sha}
    )
    with pytest.raises(transport.TransportError):
        transport.retrieve_git_artifact(wrong, root=source_two, artifact=artifact_two)


def test_transport_identity_rejects_wrong_order_and_sha(tmp_path: Path) -> None:
    _source, artifact, identity = _fixture(tmp_path)
    document = {
        **identity.__dict__,
        "contract": transport.TRANSPORT_CONTRACT,
        "chunk_count": identity.chunk_count,
        "ordered_chunks": list(reversed(identity.ordered_chunks)),
    }
    document.pop("ordered_chunks", None)
    document["ordered_chunks"] = list(reversed(identity.ordered_chunks))
    with pytest.raises(transport.TransportError):
        transport.load_transport_identity(
            document,
            product_sha=identity.product_sha,
            evidence_sha=identity.evidence_sha,
            artifact=artifact,
        )

    document["ordered_chunks"] = list(identity.ordered_chunks)
    document["archive_sha256"] = "0" * 64
    with pytest.raises(transport.TransportError):
        transport.load_transport_identity(
            document,
            product_sha=identity.product_sha,
            evidence_sha=identity.evidence_sha,
            artifact=artifact,
        )
