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

from datariver.application.governance_document_attachments import (
    MAXIMUM_GOVERNANCE_DOCUMENT_ATTACHMENT_BYTES,
    GovernanceDocumentAttachmentCollisionError,
    GovernanceDocumentAttachmentExternalError,
    GovernanceDocumentAttachmentSource,
    GovernanceDocumentAttachmentStore,
    GovernanceDocumentAttachmentWrite,
    governance_document_attachment_key,
)
from datariver.domain.common import ValidationError
from datariver.domain.governance_documents import GovernanceDocumentAttachment
from datariver.infrastructure.object_store.governance_document_attachments import (
    S3GovernanceDocumentAttachmentStore,
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
        self.fail_write = False
        self.corrupt_readback = False

    def put_object(self, **kwargs: Any) -> dict[str, str]:
        self.calls.append(("put_object", dict(kwargs)))
        if self.fail_write:
            raise ClientError(
                {"Error": {"Code": "RequestTimeout", "Message": "unknown outcome"}},
                "PutObject",
            )
        key = str(kwargs["Key"])
        if any(existing_key == key for existing_key, _version in self.objects):
            raise ClientError(
                {"Error": {"Code": "PreconditionFailed", "Message": "exists"}},
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
        return {"VersionId": version_id}

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

    def generate_presigned_url(self, operation: str, **kwargs: Any) -> str:
        self.calls.append(
            (
                "generate_presigned_url",
                {"operation": operation, **kwargs},
            )
        )
        return "https://minio.example.test/signed-download"


def _write() -> GovernanceDocumentAttachmentWrite:
    return GovernanceDocumentAttachmentWrite(
        workspace_id=uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        attachment_id=uuid4(),
        document_title="데이터 분류/접근 정책",
        registered_at=datetime(2026, 7, 31, tzinfo=UTC),
        serial_number=1,
        original_name="승인 증빙.PDF",
        classification="INTERNAL",
        content=b"immutable attachment evidence",
    )


def _store(client: _VersionedS3Client) -> S3GovernanceDocumentAttachmentStore:
    return S3GovernanceDocumentAttachmentStore(
        endpoint_url="https://minio.internal.example",
        region="us-east-1",
        bucket="datariver-filefolder",
        access_key="governance-attachment-writer",
        secret_key="secret",
        public_endpoint_url="https://minio.example.test",
        client=client,
        presign_client=client,
    )


def test_attachment_key_uses_uuid_isolation_and_a_ref_governance_filename() -> None:
    write = _write()
    key = governance_document_attachment_key(
        workspace_id=write.workspace_id,
        document_id=write.document_id,
        version_id=write.version_id,
        attachment_id=write.attachment_id,
        storage_filename=write.storage_filename,
    )

    assert key == (
        f"governance/documents/v1/{write.workspace_id}/{write.document_id}/"
        f"{write.version_id}/attachments/{write.attachment_id}/"
        "ref_governance_데이터_분류_접근_정책_20260731_001.pdf"
    )
    with pytest.raises(ValueError):
        governance_document_attachment_key(
            workspace_id=UUID(int=0),
            document_id=write.document_id,
            version_id=write.version_id,
            attachment_id=write.attachment_id,
            storage_filename=write.storage_filename,
        )


def test_attachment_payload_is_bounded_to_25_mib() -> None:
    write = _write()

    with pytest.raises(ValidationError):
        GovernanceDocumentAttachmentWrite(
            workspace_id=write.workspace_id,
            document_id=write.document_id,
            version_id=write.version_id,
            attachment_id=write.attachment_id,
            document_title=write.document_title,
            registered_at=write.registered_at,
            serial_number=write.serial_number,
            original_name=write.original_name,
            classification=write.classification,
            content=b"x" * (MAXIMUM_GOVERNANCE_DOCUMENT_ATTACHMENT_BYTES + 1),
        )


@pytest.mark.asyncio
async def test_attachment_is_create_only_and_exact_version_fully_read_back() -> None:
    client = _VersionedS3Client()
    write = _write()

    receipt = await _store(client).ensure_attachment(write)

    put = next(values for name, values in client.calls if name == "put_object")
    assert put["IfNoneMatch"] == "*"
    assert put["ContentType"] == "application/octet-stream"
    assert put["ContentLength"] == len(write.content)
    assert put["ChecksumAlgorithm"] == "SHA256"
    assert "original-name" not in put["Metadata"]
    assert receipt.provider_version_id == "version-1"
    assert receipt.content_sha256 == write.content_sha256
    exact_reads = [
        values
        for name, values in client.calls
        if name in {"head_object", "get_object"} and "VersionId" in values
    ]
    assert len(exact_reads) == 2
    assert all(values["ChecksumMode"] == "ENABLED" for values in exact_reads)


@pytest.mark.asyncio
async def test_exact_retry_adopts_without_overwrite_or_delete() -> None:
    client = _VersionedS3Client()
    store = _store(client)
    write = _write()
    first = await store.ensure_attachment(write)

    second = await store.ensure_attachment(write)

    assert second == first
    assert len(client.objects) == 1
    assert not any(name == "delete_object" for name, _values in client.calls)


@pytest.mark.asyncio
async def test_different_existing_bytes_raise_structured_collision() -> None:
    client = _VersionedS3Client()
    store = _store(client)
    write = _write()
    await store.ensure_attachment(write)
    different = GovernanceDocumentAttachmentWrite(
        workspace_id=write.workspace_id,
        document_id=write.document_id,
        version_id=write.version_id,
        attachment_id=write.attachment_id,
        document_title=write.document_title,
        registered_at=write.registered_at,
        serial_number=write.serial_number,
        original_name=write.original_name,
        classification=write.classification,
        content=b"different evidence",
    )

    with pytest.raises(GovernanceDocumentAttachmentCollisionError) as captured:
        await store.ensure_attachment(different)

    assert captured.value.details["code"] == "GOVERNANCE_DOCUMENT_ATTACHMENT_COLLISION"
    assert captured.value.details["provider_code"] == (
        "GOVERNANCE_DOCUMENT_ATTACHMENT_EXISTING_OBJECT_MISMATCH"
    )


@pytest.mark.asyncio
async def test_ambiguous_write_and_readback_mismatch_never_delete() -> None:
    write_client = _VersionedS3Client()
    write_client.fail_write = True
    with pytest.raises(GovernanceDocumentAttachmentExternalError) as ambiguous:
        await _store(write_client).ensure_attachment(_write())
    assert ambiguous.value.details["ambiguous_commit"] is True
    assert ambiguous.value.details["provider_code"] == "RequestTimeout"

    read_client = _VersionedS3Client()
    read_client.corrupt_readback = True
    with pytest.raises(GovernanceDocumentAttachmentExternalError) as mismatch:
        await _store(read_client).ensure_attachment(_write())
    assert mismatch.value.details["provider_code"] == (
        "GOVERNANCE_DOCUMENT_ATTACHMENT_READBACK_MISMATCH"
    )
    assert not any(name == "delete_object" for name, _values in read_client.calls)


@pytest.mark.asyncio
async def test_download_is_signed_for_the_exact_immutable_object_version() -> None:
    client = _VersionedS3Client()
    write = _write()
    receipt = await _store(client).ensure_attachment(write)
    source = GovernanceDocumentAttachmentSource(
        attachment=GovernanceDocumentAttachment(
            attachment_id=write.attachment_id,
            workspace_id=write.workspace_id,
            document_id=write.document_id,
            document_version_id=write.version_id,
            serial_number=write.serial_number,
            storage_filename=write.storage_filename,
            original_name="정책 증빙.txt",
            content_type="text/plain",
            size_bytes=len(write.content),
            content_sha256=write.content_sha256,
            uploaded_by=uuid4(),
            created_at=datetime.now(UTC),
        ),
        bucket=receipt.bucket,
        object_key=receipt.object_key,
        provider_version_id=receipt.provider_version_id,
    )

    url = await _store(client).presign_download(source, expires_seconds=300)

    assert url == "https://minio.example.test/signed-download"
    call = next(values for name, values in client.calls if name == "generate_presigned_url")
    assert call["operation"] == "get_object"
    assert call["HttpMethod"] == "GET"
    assert call["ExpiresIn"] == 300
    assert call["Params"]["VersionId"] == "version-1"
    assert call["Params"]["Key"] == receipt.object_key
    assert "filename*=UTF-8''" in call["Params"]["ResponseContentDisposition"]


def test_attachment_port_and_adapter_expose_only_bounded_non_destructive_methods() -> None:
    prohibited = {
        "delete_object",
        "copy_object",
        "presign_upload",
        "list_objects",
        "list_object_versions",
    }
    protocol_methods = set(vars(GovernanceDocumentAttachmentStore))
    adapter_methods = {
        name
        for name, _member in inspect.getmembers(
            S3GovernanceDocumentAttachmentStore,
            predicate=inspect.isfunction,
        )
        if not name.startswith("_")
    }

    assert prohibited.isdisjoint(protocol_methods)
    assert prohibited.isdisjoint(adapter_methods)
    assert adapter_methods == {"ensure_attachment", "presign_download"}
