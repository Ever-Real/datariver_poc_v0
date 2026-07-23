from __future__ import annotations

import io
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from botocore.exceptions import ClientError

from datariver.domain.common import ConflictError
from datariver.infrastructure.object_store.s3 import S3ObjectStore


class _CreateOnlyS3Client:
    def __init__(self, *, existing: bytes = b"") -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.object_content = existing
        self.object_content_type = "application/octet-stream"
        self.object_metadata: dict[str, str] = {}

    def put_object(self, **kwargs: object) -> dict[str, str]:
        self.calls.append(("put_object", kwargs))
        self.object_content = cast(bytes, kwargs["Body"])
        self.object_content_type = str(kwargs["ContentType"])
        self.object_metadata = cast(dict[str, str], kwargs["Metadata"])
        return {"ETag": '"attachment-etag"'}

    def head_object(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("head_object", kwargs))
        return {
            "ContentLength": len(self.object_content),
            "ContentType": self.object_content_type,
            "ETag": '"attachment-etag"',
            "Metadata": self.object_metadata,
        }

    def get_object(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("get_object", kwargs))
        return {"Body": io.BytesIO(self.object_content)}

    def delete_object(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("delete_object", kwargs))
        self.object_content = b""
        return {}


class _CollisionS3Client(_CreateOnlyS3Client):
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


def _store(client: _CreateOnlyS3Client) -> S3ObjectStore:
    store = object.__new__(S3ObjectStore)
    store._client = cast(Any, client)
    store._presign_client = cast(Any, client)
    return store


async def _chunks(*values: bytes) -> AsyncIterator[bytes]:
    for value in values:
        yield value


@pytest.mark.asyncio
async def test_attachment_write_is_conditional_create_and_fully_verified() -> None:
    client = _CreateOnlyS3Client()
    store = _store(client)

    artifact = await store.write_create_only(
        bucket="datariver-filefolder",
        object_key="attachments/workspace/request/attachment",
        chunks=_chunks(b"private ", b"evidence"),
        metadata={"attachment-id": "01900000-0000-7000-8000-000000000001"},
        maximum_bytes=10 * 1024 * 1024,
        content_type="text/plain",
    )

    put = client.calls[0][1]
    assert put["IfNoneMatch"] == "*"
    assert put["Body"] == b"private evidence"
    assert put["ContentLength"] == len(b"private evidence")
    assert [name for name, _ in client.calls] == ["put_object", "head_object", "get_object"]
    assert artifact.size_bytes == len(b"private evidence")


@pytest.mark.asyncio
async def test_attachment_create_collision_never_overwrites_or_deletes_existing_object() -> None:
    client = _CollisionS3Client(existing=b"existing durable evidence")
    store = _store(client)

    with pytest.raises(ConflictError) as captured:
        await store.write_create_only(
            bucket="datariver-filefolder",
            object_key="attachments/workspace/request/attachment",
            chunks=_chunks(b"replacement"),
            metadata={},
            maximum_bytes=10 * 1024 * 1024,
            content_type="text/plain",
        )

    assert captured.value.details == {"code": "OBJECT_KEY_ALREADY_EXISTS"}
    assert client.object_content == b"existing durable evidence"
    assert [name for name, _ in client.calls] == ["put_object"]
