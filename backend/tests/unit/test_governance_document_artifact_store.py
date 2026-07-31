from __future__ import annotations

import base64
import hashlib
import inspect
from datetime import UTC, datetime
from io import BytesIO
from typing import Any
from uuid import UUID, uuid4

import pytest
from botocore.exceptions import ClientError

from datariver.application.governance_document_artifacts import (
    GovernanceDocumentArtifactCollisionError,
    GovernanceDocumentArtifactExternalError,
    GovernanceDocumentArtifactStore,
    GovernanceDocumentArtifactWrite,
    governance_document_artifact_keys,
)
from datariver.infrastructure.object_store.governance_documents import (
    S3GovernanceDocumentArtifactStore,
)


class _Body:
    def __init__(self, content: bytes) -> None:
        self._content = BytesIO(content)

    def read(self, size: int) -> bytes:
        return self._content.read(size)

    def close(self) -> None:
        self._content.close()


class _VersionedS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict[str, Any]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_stage: str | None = None
        self.corrupt_readback = False

    def put_object(self, **kwargs: Any) -> dict[str, str]:
        self.calls.append(("put_object", dict(kwargs)))
        key = str(kwargs["Key"])
        if self.fail_stage and key.endswith(self.fail_stage):
            raise ClientError(
                {"Error": {"Code": "RequestTimeout", "Message": "unknown outcome"}},
                "PutObject",
            )
        if any(existing_key == key for existing_key, _version in self.objects):
            raise ClientError(
                {
                    "Error": {"Code": "PreconditionFailed", "Message": "exists"},
                },
                "PutObject",
            )
        content = bytes(kwargs["Body"])
        version_id = f"version-{len(self.objects) + 1}"
        checksum = base64.b64encode(hashlib.sha256(content).digest()).decode("ascii")
        self.objects[(key, version_id)] = {
            "content": content,
            "content_type": kwargs["ContentType"],
            "etag": f"etag-{version_id}",
            "checksum": checksum,
            "metadata": dict(kwargs["Metadata"]),
        }
        return {"VersionId": version_id, "ChecksumSHA256": checksum}

    def head_object(self, **kwargs: Any) -> dict[str, object]:
        self.calls.append(("head_object", dict(kwargs)))
        key = str(kwargs["Key"])
        requested_version = kwargs.get("VersionId")
        matches = [
            (version, value)
            for (existing_key, version), value in self.objects.items()
            if existing_key == key and (requested_version is None or version == requested_version)
        ]
        if not matches:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "missing"}},
                "HeadObject",
            )
        version, value = matches[-1]
        return {
            "VersionId": version,
            "ContentLength": len(value["content"]),
            "ContentType": value["content_type"],
            "ETag": f'"{value["etag"]}"',
            "ChecksumSHA256": value["checksum"],
            "Metadata": value["metadata"],
        }

    def get_object(self, **kwargs: Any) -> dict[str, object]:
        self.calls.append(("get_object", dict(kwargs)))
        key = (str(kwargs["Key"]), str(kwargs["VersionId"]))
        value = self.objects[key]
        content = b"corrupt" if self.corrupt_readback else value["content"]
        return {
            "VersionId": key[1],
            "ChecksumSHA256": value["checksum"],
            "Body": _Body(content),
        }


def _write() -> GovernanceDocumentArtifactWrite:
    return GovernanceDocumentArtifactWrite(
        workspace_id=uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        document_title="데이터 분류/접근 정책",
        registered_at=datetime(2026, 7, 31, tzinfo=UTC),
        version_number=3,
        version_tag="v3.0",
        sanitizer_policy_version="html-policy:1",
        sanitizer_policy_sha256="a" * 64,
        classification="INTERNAL",
        content_html=b"<h1>Policy</h1>",
        manifest_json=b'{"contract":"governance-document-manifest-v1"}',
    )


def _store(client: _VersionedS3Client) -> S3GovernanceDocumentArtifactStore:
    return S3GovernanceDocumentArtifactStore(
        endpoint_url="https://minio.internal.example",
        region="us-east-1",
        bucket="datariver-filefolder",
        access_key="governance-writer",
        secret_key="secret",
        client=client,
    )


def test_key_builder_uses_uuid_isolation_and_a_normalized_governance_filename() -> None:
    write = _write()
    keys = governance_document_artifact_keys(
        workspace_id=write.workspace_id,
        document_id=write.document_id,
        version_id=write.version_id,
        document_title=write.document_title,
        registered_at=write.registered_at,
        version_number=write.version_number,
    )

    expected_prefix = (
        f"governance/documents/v1/{write.workspace_id}/{write.document_id}/{write.version_id}"
    )
    assert keys.content_key == (
        f"{expected_prefix}/doc_governance_데이터_분류_접근_정책_20260731_003.html"
    )
    assert keys.manifest_key == (
        f"{expected_prefix}/doc_governance_데이터_분류_접근_정책_20260731_003.manifest.json"
    )
    with pytest.raises(ValueError):
        governance_document_artifact_keys(
            workspace_id=UUID(int=0),
            document_id=write.document_id,
            version_id=write.version_id,
            document_title=write.document_title,
            registered_at=write.registered_at,
            version_number=write.version_number,
        )


@pytest.mark.asyncio
async def test_content_is_created_before_manifest_and_both_are_exactly_read_back() -> None:
    client = _VersionedS3Client()
    write = _write()

    receipt = await _store(client).ensure_version_artifacts(write)

    put_calls = [values for name, values in client.calls if name == "put_object"]
    assert str(put_calls[0]["Key"]).endswith("_003.html")
    assert str(put_calls[1]["Key"]).endswith("_003.manifest.json")
    assert all(call["IfNoneMatch"] == "*" for call in put_calls)
    assert all(call["ChecksumAlgorithm"] == "SHA256" for call in put_calls)
    assert receipt.content.provider_version_id == "version-1"
    assert receipt.manifest.provider_version_id == "version-2"
    assert receipt.content.content_sha256 == write.content_sha256
    assert receipt.manifest.content_sha256 == write.manifest_sha256
    exact_reads = [
        values
        for name, values in client.calls
        if name in {"head_object", "get_object"} and "VersionId" in values
    ]
    assert len(exact_reads) == 4
    assert all(values["ChecksumMode"] == "ENABLED" for values in exact_reads)


@pytest.mark.asyncio
async def test_exact_collision_is_idempotently_adopted_without_overwrite() -> None:
    client = _VersionedS3Client()
    store = _store(client)
    write = _write()
    first = await store.ensure_version_artifacts(write)

    second = await store.ensure_version_artifacts(write)

    assert second == first
    assert len(client.objects) == 2
    assert not any(name in {"delete_object", "copy_object"} for name, _values in client.calls)


@pytest.mark.asyncio
async def test_different_existing_content_is_a_structured_collision() -> None:
    client = _VersionedS3Client()
    store = _store(client)
    write = _write()
    await store.ensure_version_artifacts(write)
    different = GovernanceDocumentArtifactWrite(
        workspace_id=write.workspace_id,
        document_id=write.document_id,
        version_id=write.version_id,
        document_title=write.document_title,
        registered_at=write.registered_at,
        version_number=write.version_number,
        version_tag=write.version_tag,
        sanitizer_policy_version=write.sanitizer_policy_version,
        sanitizer_policy_sha256=write.sanitizer_policy_sha256,
        classification=write.classification,
        content_html=b"<h1>Different</h1>",
        manifest_json=write.manifest_json,
    )

    with pytest.raises(GovernanceDocumentArtifactCollisionError) as captured:
        await store.ensure_version_artifacts(different)

    assert captured.value.details["artifact_stage"] == "CONTENT"
    assert captured.value.details["content_committed"] is False
    assert captured.value.details["provider_code"] == (
        "GOVERNANCE_DOCUMENT_EXISTING_OBJECT_MISMATCH"
    )


@pytest.mark.asyncio
async def test_manifest_write_failure_preserves_content_and_marks_ambiguous_stage() -> None:
    client = _VersionedS3Client()
    client.fail_stage = "manifest.json"
    write = _write()

    with pytest.raises(GovernanceDocumentArtifactExternalError) as captured:
        await _store(client).ensure_version_artifacts(write)

    assert captured.value.details["artifact_stage"] == "MANIFEST"
    assert captured.value.details["content_committed"] is True
    assert captured.value.details["ambiguous_commit"] is True
    assert any(key.endswith("_003.html") for key, _version in client.objects)
    assert not any(key.endswith("_003.manifest.json") for key, _version in client.objects)


@pytest.mark.asyncio
async def test_committed_readback_mismatch_is_ambiguous_and_never_deleted() -> None:
    client = _VersionedS3Client()
    client.corrupt_readback = True

    with pytest.raises(GovernanceDocumentArtifactExternalError) as captured:
        await _store(client).ensure_version_artifacts(_write())

    assert captured.value.details["artifact_stage"] == "CONTENT"
    assert captured.value.details["ambiguous_commit"] is True
    assert captured.value.details["provider_code"] == (
        "GOVERNANCE_DOCUMENT_ARTIFACT_READBACK_MISMATCH"
    )
    assert not any(name == "delete_object" for name, _values in client.calls)


def test_dedicated_port_and_adapter_expose_no_destructive_or_raw_provider_methods() -> None:
    prohibited = {
        "delete_object",
        "copy_object",
        "presign_download",
        "presign_upload",
        "list_objects",
        "list_object_versions",
    }
    protocol_methods = set(vars(GovernanceDocumentArtifactStore))
    adapter_methods = {
        name
        for name, _member in inspect.getmembers(
            S3GovernanceDocumentArtifactStore,
            predicate=inspect.isfunction,
        )
        if not name.startswith("_")
    }

    assert prohibited.isdisjoint(protocol_methods)
    assert prohibited.isdisjoint(adapter_methods)
    assert adapter_methods == {"ensure_version_artifacts"}
