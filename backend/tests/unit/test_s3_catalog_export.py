from __future__ import annotations

import hashlib
import io
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest

from datariver.domain.common import ConflictError, ValidationError
from datariver.infrastructure.object_store.s3 import S3ObjectStore


class FakeS3Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.uploaded_parts: dict[int, bytes] = {}
        self.object_content = b""
        self.object_content_type = "text/csv; charset=utf-8"
        self.object_etag = '"completed-etag"'
        self.object_metadata: dict[str, str] = {}

    def create_multipart_upload(self, **kwargs: object) -> dict[str, str]:
        self.calls.append(("create_multipart_upload", kwargs))
        self.object_content_type = str(kwargs["ContentType"])
        self.object_metadata = cast(dict[str, str], kwargs["Metadata"])
        return {"UploadId": "export-upload-1"}

    def put_object(self, **kwargs: object) -> dict[str, str]:
        self.calls.append(("put_object", kwargs))
        self.object_content = cast(bytes, kwargs["Body"])
        self.object_content_type = str(kwargs["ContentType"])
        self.object_metadata = cast(dict[str, str], kwargs["Metadata"])
        return {"ETag": self.object_etag}

    def upload_part(self, **kwargs: object) -> dict[str, str]:
        self.calls.append(("upload_part", kwargs))
        part_number = int(cast(int, kwargs["PartNumber"]))
        self.uploaded_parts[part_number] = cast(bytes, kwargs["Body"])
        return {"ETag": f'"part-{part_number}-etag"'}

    def complete_multipart_upload(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("complete_multipart_upload", kwargs))
        document = cast(dict[str, list[dict[str, object]]], kwargs["MultipartUpload"])
        self.object_content = b"".join(
            self.uploaded_parts[cast(int, part["PartNumber"])] for part in document["Parts"]
        )
        return {}

    def abort_multipart_upload(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("abort_multipart_upload", kwargs))
        return {}

    def head_object(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("head_object", kwargs))
        return {
            "ContentLength": len(self.object_content),
            "ContentType": self.object_content_type,
            "ETag": self.object_etag,
            "ChecksumSHA256": "provider-sha256",
            "Metadata": self.object_metadata,
        }

    def get_object(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("get_object", kwargs))
        return {"Body": io.BytesIO(self.object_content)}

    def delete_object(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("delete_object", kwargs))
        return {}


class FakePresignClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def generate_presigned_url(
        self,
        client_method: str,
        *,
        Params: dict[str, object],
        ExpiresIn: int,
        HttpMethod: str,
    ) -> str:
        self.calls.append(
            (
                client_method,
                {
                    "Params": Params,
                    "ExpiresIn": ExpiresIn,
                    "HttpMethod": HttpMethod,
                },
            )
        )
        return "https://objects.example.invalid/presigned"


def object_store(
    client: FakeS3Client, presign_client: FakePresignClient | None = None
) -> S3ObjectStore:
    store = object.__new__(S3ObjectStore)
    store._client = cast(Any, client)
    store._presign_client = cast(Any, presign_client or FakePresignClient())
    return store


async def chunks(*values: bytes) -> AsyncIterator[bytes]:
    for value in values:
        yield value


@pytest.mark.asyncio
async def test_write_export_streams_bounded_parts_and_returns_integrity_receipt() -> None:
    client = FakeS3Client()
    store = object_store(client)
    first = b"a" * (5 * 1024 * 1024)
    second = b"b" * (4 * 1024 * 1024)
    third = b"c" * 3
    payload = first + second + third
    metadata = {
        "export-id": "01900000-0000-7000-8000-000000000001",
        "request-hash": "request-hash",
        "csv-safety-version": "csv-safe-v1",
    }

    artifact = await store.write_export(
        bucket="catalog-exports",
        object_key="workspace/export.csv",
        chunks=chunks(first, second, third),
        metadata=metadata,
        maximum_bytes=len(payload),
    )

    assert [len(client.uploaded_parts[index]) for index in sorted(client.uploaded_parts)] == [
        8 * 1024 * 1024,
        1024 * 1024 + 3,
    ]
    assert client.object_content == payload
    create_call = next(
        arguments for name, arguments in client.calls if name == "create_multipart_upload"
    )
    assert create_call == {
        "Bucket": "catalog-exports",
        "Key": "workspace/export.csv",
        "ContentType": "text/csv; charset=utf-8",
        "Metadata": metadata,
    }
    complete_call = next(
        arguments for name, arguments in client.calls if name == "complete_multipart_upload"
    )
    assert complete_call["MultipartUpload"] == {
        "Parts": [
            {"PartNumber": 1, "ETag": "part-1-etag"},
            {"PartNumber": 2, "ETag": "part-2-etag"},
        ]
    }
    assert artifact.size_bytes == len(payload)
    assert artifact.content_sha256 == hashlib.sha256(payload).hexdigest()
    assert artifact.provider_checksum == "etag:completed-etag"


@pytest.mark.asyncio
async def test_write_immutable_receipt_uses_create_only_put_and_verifies_head() -> None:
    client = FakeS3Client()
    store = object_store(client)
    payload = b"record_kind,description\nTABLE,controlled\n"

    artifact = await store.write_immutable_receipt(
        bucket="datariver-infoschema",
        object_key="UPLOAD_METADATA_MANUAL_260718_000042.csv",
        content=payload,
        metadata={"content-kind": "manual-metadata-csv-v1"},
        maximum_bytes=5 * 1024 * 1024,
    )

    digest = hashlib.sha256(payload).hexdigest()
    assert client.calls[0] == (
        "put_object",
        {
            "Bucket": "datariver-infoschema",
            "Key": "UPLOAD_METADATA_MANUAL_260718_000042.csv",
            "Body": payload,
            "ContentLength": len(payload),
            "ContentType": "text/csv; charset=utf-8",
            "IfNoneMatch": "*",
            "Metadata": {
                "content-kind": "manual-metadata-csv-v1",
                "content-sha256": digest,
            },
        },
    )
    assert [name for name, _ in client.calls] == ["put_object", "head_object", "get_object"]
    assert artifact.size_bytes == len(payload)
    assert artifact.content_sha256 == digest
    assert artifact.provider_checksum == "etag:completed-etag"


@pytest.mark.asyncio
async def test_write_immutable_receipt_rejects_existing_key_without_delete() -> None:
    from botocore.exceptions import ClientError

    class ExistingKeyClient(FakeS3Client):
        def put_object(self, **kwargs: object) -> dict[str, str]:
            self.calls.append(("put_object", kwargs))
            raise ClientError(
                cast(
                    Any,
                    {
                        "Error": {"Code": "PreconditionFailed", "Message": "exists"},
                        "ResponseMetadata": {"HTTPStatusCode": 412},
                    },
                ),
                "PutObject",
            )

    client = ExistingKeyClient()
    store = object_store(client)

    with pytest.raises(ConflictError) as captured:
        await store.write_immutable_receipt(
            bucket="datariver-infoschema",
            object_key="existing.csv",
            content=b"private",
            metadata={},
            maximum_bytes=1024,
        )

    assert captured.value.details == {"code": "OBJECT_KEY_ALREADY_EXISTS"}
    assert [name for name, _ in client.calls] == ["put_object"]


@pytest.mark.asyncio
async def test_write_export_byte_limit_aborts_upload_and_deletes_partial_object() -> None:
    client = FakeS3Client()
    store = object_store(client)

    with pytest.raises(ValidationError) as error:
        await store.write_export(
            bucket="catalog-exports",
            object_key="workspace/export.csv",
            chunks=chunks(b"abc", b"def"),
            metadata={"export-id": "export-1"},
            maximum_bytes=5,
        )

    assert error.value.details == {"code": "EXPORT_BYTE_LIMIT"}
    assert not client.uploaded_parts
    assert [name for name, _ in client.calls] == [
        "create_multipart_upload",
        "abort_multipart_upload",
        "delete_object",
    ]
    assert client.calls[1][1] == {
        "Bucket": "catalog-exports",
        "Key": "workspace/export.csv",
        "UploadId": "export-upload-1",
    }
    assert client.calls[2][1] == {
        "Bucket": "catalog-exports",
        "Key": "workspace/export.csv",
    }


@pytest.mark.asyncio
async def test_delete_export_removes_only_the_requested_object() -> None:
    client = FakeS3Client()
    store = object_store(client)

    await store.delete_export(bucket="catalog-exports", object_key="workspace/export.csv")

    assert client.calls == [
        (
            "delete_object",
            {"Bucket": "catalog-exports", "Key": "workspace/export.csv"},
        )
    ]


@pytest.mark.asyncio
async def test_head_and_presign_download_preserve_integrity_metadata_and_safe_filename() -> None:
    client = FakeS3Client()
    client.object_content = b"header\r\n"
    client.object_metadata = {
        "export-id": "export-1",
        "request-hash": "request-hash",
    }
    presign_client = FakePresignClient()
    store = object_store(client, presign_client)

    metadata = await store.head_object(bucket="catalog-exports", object_key="workspace/export.csv")
    url = await store.presign_download(
        bucket="catalog-exports",
        object_key="workspace/export.csv",
        download_name='report"\r\nforged.csv',
        expires_seconds=60,
    )

    assert metadata.size_bytes == len(client.object_content)
    assert metadata.content_type == "text/csv; charset=utf-8"
    assert metadata.etag == "completed-etag"
    assert metadata.checksum_sha256 == "provider-sha256"
    assert metadata.user_metadata == client.object_metadata
    assert url == "https://objects.example.invalid/presigned"
    assert presign_client.calls == [
        (
            "get_object",
            {
                "Params": {
                    "Bucket": "catalog-exports",
                    "Key": "workspace/export.csv",
                    "ResponseContentDisposition": ('attachment; filename="reportforged.csv"'),
                },
                "ExpiresIn": 60,
                "HttpMethod": "GET",
            },
        )
    ]
