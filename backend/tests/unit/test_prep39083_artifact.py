from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import sys
import tarfile
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
MODULE_PATH = SCRIPTS / "prep39083_artifact.py"


def _load_module() -> ModuleType:
    sys.path.insert(0, os.fspath(SCRIPTS))
    try:
        specification = importlib.util.spec_from_file_location(
            "prep39083_artifact_for_test",
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


artifact = _load_module()


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _write_member(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    member = tarfile.TarInfo(name)
    member.size = len(payload)
    archive.addfile(member, io.BytesIO(payload))


def write_web_archive(
    path: Path,
    *,
    revision: str = "a" * 40,
    architecture: str = "amd64",
) -> None:
    config = _json_bytes(
        {
            "architecture": architecture,
            "config": {"Labels": {"org.opencontainers.image.revision": revision}},
            "os": "linux",
        }
    )
    config_digest = _digest(config)
    config_path = f"blobs/sha256/{config_digest.removeprefix('sha256:')}"
    layer = b"bounded-layer"
    layer_digest = _digest(layer)
    layer_path = f"blobs/sha256/{layer_digest.removeprefix('sha256:')}"
    image_manifest = _json_bytes(
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
    manifest_digest = _digest(image_manifest)
    manifest_path = f"blobs/sha256/{manifest_digest.removeprefix('sha256:')}"
    index = _json_bytes(
        {
            "manifests": [
                {
                    "annotations": {"org.opencontainers.image.ref.name": revision},
                    "digest": manifest_digest,
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "platform": {"architecture": architecture, "os": "linux"},
                    "size": len(image_manifest),
                }
            ],
            "schemaVersion": 2,
        }
    )
    docker_manifest = _json_bytes(
        [
            {
                "Config": config_path,
                "Layers": [layer_path],
                "RepoTags": [f"datariver-poc:{revision}"],
            }
        ]
    )
    with tarfile.open(path, "w") as archive:
        for name, payload in (
            ("manifest.json", docker_manifest),
            ("index.json", index),
            ("oci-layout", _json_bytes({"imageLayoutVersion": "1.0.0"})),
            (config_path, config),
            (manifest_path, image_manifest),
            (layer_path, layer),
        ):
            _write_member(archive, name, payload)


def test_inspect_web_archive_binds_archive_manifest_config_platform_and_revision(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "image.tar"
    write_web_archive(archive)

    observed = artifact.inspect_web_archive(archive)

    assert observed.product_sha == "a" * 40
    assert observed.image_reference == f"datariver-poc:{'a' * 40}"
    assert observed.platform == "linux/amd64"
    assert observed.oci_revision == "a" * 40
    assert observed.archive_sha256 == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert observed.manifest_digest.startswith("sha256:")
    assert observed.config_digest.startswith("sha256:")
    assert (
        artifact.identity_from_release_mapping(observed.release_mapping(), product_sha="a" * 40)
        == observed
    )


@pytest.mark.parametrize(
    ("revision", "architecture"),
    (("short", "amd64"), ("a" * 40, "arm64")),
)
def test_inspect_web_archive_rejects_revision_or_platform_mismatch(
    tmp_path: Path,
    revision: str,
    architecture: str,
) -> None:
    archive = tmp_path / "image.tar"
    write_web_archive(archive, revision=revision, architecture=architecture)

    with pytest.raises(artifact.ArtifactError):
        artifact.inspect_web_archive(archive)


def test_release_mapping_rejects_checksum_manifest_and_path_drift(tmp_path: Path) -> None:
    archive = tmp_path / "image.tar"
    write_web_archive(archive)
    observed = artifact.inspect_web_archive(archive)

    for key, value in (
        ("archive_sha256", "0" * 64),
        ("manifest_digest", f"sha256:{'1' * 64}"),
        ("path", "runtime/prep39083/artifacts/other.tar"),
    ):
        mapping = observed.release_mapping()
        mapping[key] = value
        if key in {"archive_sha256", "manifest_digest"}:
            parsed = artifact.identity_from_release_mapping(mapping, product_sha="a" * 40)
            with pytest.raises(artifact.ArtifactError):
                artifact.require_expected_identity(observed, parsed)
        else:
            with pytest.raises(artifact.ArtifactError):
                artifact.identity_from_release_mapping(mapping, product_sha="a" * 40)


def test_inspect_web_archive_rejects_unsafe_or_missing_inventory(tmp_path: Path) -> None:
    archive = tmp_path / "image.tar"
    with tarfile.open(archive, "w") as bundle:
        _write_member(bundle, "../manifest.json", b"[]")

    with pytest.raises(artifact.ArtifactError):
        artifact.inspect_web_archive(archive)

    with pytest.raises(artifact.ArtifactError):
        artifact.inspect_web_archive(tmp_path / "missing.tar")
