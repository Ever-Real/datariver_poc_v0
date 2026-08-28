#!/usr/bin/env python3
"""Portable, fail-closed identity checks for one promoted PREP web image archive."""

from __future__ import annotations

import hashlib
import json
import re
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

WEB_ARTIFACT_CONTRACT = "DATARIVER_PREP39083_WEB_ARTIFACT_V1"
WEB_ARTIFACT_TRANSPORT = "APPROVED_DOCKER_ARCHIVE"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
MAX_ARCHIVE_BYTES = 4 * 1024 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 1024
MAX_JSON_BYTES = 1024 * 1024


class ArtifactError(RuntimeError):
    """One bounded promoted-artifact contract failure."""


@dataclass(frozen=True)
class WebArtifactIdentity:
    product_sha: str
    artifact_id: str
    image_reference: str
    archive_sha256: str
    manifest_digest: str
    config_digest: str
    platform: str
    oci_revision: str

    @property
    def filename(self) -> str:
        return f"{self.artifact_id}.tar"

    @property
    def relative_path(self) -> str:
        return f"runtime/prep39083/artifacts/{self.filename}"

    def release_mapping(self) -> dict[str, str]:
        return {
            "contract": WEB_ARTIFACT_CONTRACT,
            "transport": WEB_ARTIFACT_TRANSPORT,
            "artifact_id": self.artifact_id,
            "path": self.relative_path,
            "archive_sha256": self.archive_sha256,
            "image_reference": self.image_reference,
            "manifest_digest": self.manifest_digest,
            "config_digest": self.config_digest,
            "platform": self.platform,
            "oci_revision": self.oci_revision,
        }


def artifact_id(product_sha: str) -> str:
    if not SHA_PATTERN.fullmatch(product_sha):
        raise ArtifactError("Product SHA is invalid")
    return f"datariver-poc-{product_sha}-linux-amd64"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _digest_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _json_member(
    archive: tarfile.TarFile,
    members: dict[str, tarfile.TarInfo],
    name: str,
) -> tuple[dict[str, Any] | list[Any], bytes]:
    member = members.get(name)
    if member is None or not member.isfile() or member.size > MAX_JSON_BYTES:
        raise ArtifactError("promoted image archive JSON inventory is invalid")
    stream = archive.extractfile(member)
    if stream is None:
        raise ArtifactError("promoted image archive JSON inventory is unreadable")
    payload = stream.read(MAX_JSON_BYTES + 1)
    if len(payload) > MAX_JSON_BYTES:
        raise ArtifactError("promoted image archive JSON exceeds its bounded size")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ArtifactError("promoted image archive JSON is malformed") from error
    if not isinstance(value, (dict, list)):
        raise ArtifactError("promoted image archive JSON shape is invalid")
    return value, payload


def _safe_members(archive: tarfile.TarFile) -> dict[str, tarfile.TarInfo]:
    entries = archive.getmembers()
    if not entries or len(entries) > MAX_ARCHIVE_MEMBERS:
        raise ArtifactError("promoted image archive inventory is unbounded or empty")
    members: dict[str, tarfile.TarInfo] = {}
    for member in entries:
        path = PurePosixPath(member.name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or member.name in members
            or not (member.isfile() or member.isdir())
        ):
            raise ArtifactError("promoted image archive contains an unsafe member")
        members[member.name] = member
    return members


def inspect_web_archive(path: Path) -> WebArtifactIdentity:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise ArtifactError("promoted image archive is missing") from error
    if path.is_symlink() or not path.is_file():
        raise ArtifactError("promoted image archive must be one regular non-symlink file")
    if metadata.st_size <= 0 or metadata.st_size > MAX_ARCHIVE_BYTES:
        raise ArtifactError("promoted image archive size is outside its bounded contract")

    archive_sha256 = sha256_file(path)
    try:
        with tarfile.open(path, "r:*") as archive:
            members = _safe_members(archive)
            manifest_value, _manifest_payload = _json_member(archive, members, "manifest.json")
            index_value, _index_payload = _json_member(archive, members, "index.json")
            if not isinstance(manifest_value, list) or len(manifest_value) != 1:
                raise ArtifactError("promoted image archive must contain exactly one image")
            manifest_entry = manifest_value[0]
            if not isinstance(manifest_entry, dict):
                raise ArtifactError("promoted image archive manifest entry is invalid")
            repo_tags = manifest_entry.get("RepoTags")
            config_path = manifest_entry.get("Config")
            layers = manifest_entry.get("Layers")
            if (
                not isinstance(repo_tags, list)
                or len(repo_tags) != 1
                or not isinstance(repo_tags[0], str)
                or not isinstance(config_path, str)
                or not isinstance(layers, list)
                or not layers
                or len(layers) > 256
                or any(not isinstance(layer, str) for layer in layers)
                or len(set(layers)) != len(layers)
            ):
                raise ArtifactError("promoted image archive Docker manifest is invalid")

            if not isinstance(index_value, dict):
                raise ArtifactError("promoted image archive OCI index is invalid")
            descriptors = index_value.get("manifests")
            if not isinstance(descriptors, list) or len(descriptors) != 1:
                raise ArtifactError("promoted image archive OCI index is not single-platform")
            descriptor = descriptors[0]
            platform = descriptor.get("platform") if isinstance(descriptor, dict) else None
            manifest_digest = descriptor.get("digest") if isinstance(descriptor, dict) else None
            if (
                descriptor.get("mediaType") != "application/vnd.oci.image.manifest.v1+json"
                or not isinstance(manifest_digest, str)
                or not DIGEST_PATTERN.fullmatch(manifest_digest)
                or platform != {"architecture": "amd64", "os": "linux"}
            ):
                raise ArtifactError("promoted image archive OCI descriptor is invalid")

            manifest_blob_path = f"blobs/sha256/{manifest_digest.removeprefix('sha256:')}"
            child_manifest, child_payload = _json_member(archive, members, manifest_blob_path)
            if _digest_bytes(child_payload) != manifest_digest or not isinstance(
                child_manifest, dict
            ):
                raise ArtifactError("promoted image manifest digest does not match its content")
            child_config = child_manifest.get("config")
            config_digest = child_config.get("digest") if isinstance(child_config, dict) else None
            if (
                not isinstance(config_digest, str)
                or not DIGEST_PATTERN.fullmatch(config_digest)
                or config_path != f"blobs/sha256/{config_digest.removeprefix('sha256:')}"
            ):
                raise ArtifactError("promoted image config reference is invalid")

            config_value, config_payload = _json_member(archive, members, config_path)
            if _digest_bytes(config_payload) != config_digest or not isinstance(config_value, dict):
                raise ArtifactError("promoted image config digest does not match its content")
            labels = (
                config_value.get("config", {}).get("Labels", {})
                if isinstance(config_value.get("config"), dict)
                else {}
            )
            revision = labels.get("org.opencontainers.image.revision")
            if (
                config_value.get("os") != "linux"
                or config_value.get("architecture") != "amd64"
                or not isinstance(revision, str)
                or not SHA_PATTERN.fullmatch(revision)
            ):
                raise ArtifactError("promoted image platform or revision contract is invalid")

            expected_id = artifact_id(revision)
            expected_image = f"datariver-poc:{revision}"
            if repo_tags != [expected_image]:
                raise ArtifactError("promoted image reference does not match its revision")
            annotations = descriptor.get("annotations")
            if (
                not isinstance(annotations, dict)
                or annotations.get("org.opencontainers.image.ref.name") != revision
            ):
                raise ArtifactError("promoted image OCI tag annotation is invalid")
            for referenced in (config_path, *layers, manifest_blob_path):
                member = members.get(referenced)
                if member is None or not member.isfile():
                    raise ArtifactError("promoted image archive references a missing blob")
    except (tarfile.TarError, OSError) as error:
        raise ArtifactError("promoted image archive cannot be inspected") from error

    return WebArtifactIdentity(
        product_sha=revision,
        artifact_id=expected_id,
        image_reference=expected_image,
        archive_sha256=archive_sha256,
        manifest_digest=manifest_digest,
        config_digest=config_digest,
        platform="linux/amd64",
        oci_revision=revision,
    )


def require_expected_identity(
    observed: WebArtifactIdentity,
    expected: WebArtifactIdentity,
) -> None:
    if observed != expected:
        raise ArtifactError("promoted image archive identity differs from release.json")


def identity_from_release_mapping(
    value: object,
    *,
    product_sha: str,
) -> WebArtifactIdentity:
    if not isinstance(value, dict):
        raise ArtifactError("release web artifact is not an object")
    expected_id = artifact_id(product_sha)
    expected_image = f"datariver-poc:{product_sha}"
    fields = {
        key: value.get(key)
        for key in (
            "artifact_id",
            "image_reference",
            "archive_sha256",
            "manifest_digest",
            "config_digest",
            "platform",
            "oci_revision",
        )
    }
    if (
        value.get("contract") != WEB_ARTIFACT_CONTRACT
        or value.get("transport") != WEB_ARTIFACT_TRANSPORT
        or fields["artifact_id"] != expected_id
        or value.get("path") != f"runtime/prep39083/artifacts/{expected_id}.tar"
        or fields["image_reference"] != expected_image
        or fields["platform"] != "linux/amd64"
        or fields["oci_revision"] != product_sha
        or not isinstance(fields["archive_sha256"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", fields["archive_sha256"])
        or not isinstance(fields["manifest_digest"], str)
        or not DIGEST_PATTERN.fullmatch(fields["manifest_digest"])
        or not isinstance(fields["config_digest"], str)
        or not DIGEST_PATTERN.fullmatch(fields["config_digest"])
    ):
        raise ArtifactError("release web artifact identity is invalid or inconsistent")
    return WebArtifactIdentity(
        product_sha=product_sha,
        artifact_id=str(fields["artifact_id"]),
        image_reference=str(fields["image_reference"]),
        archive_sha256=str(fields["archive_sha256"]),
        manifest_digest=str(fields["manifest_digest"]),
        config_digest=str(fields["config_digest"]),
        platform=str(fields["platform"]),
        oci_revision=str(fields["oci_revision"]),
    )
