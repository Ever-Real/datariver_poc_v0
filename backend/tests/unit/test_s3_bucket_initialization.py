from __future__ import annotations

from typing import Any

import pytest

from datariver.infrastructure.object_store.s3 import S3ObjectStore


class _S3Client:
    def __init__(self) -> None:
        self.headed: list[str] = []
        self.cors_requests: list[dict[str, Any]] = []

    def head_bucket(self, *, Bucket: str) -> None:
        self.headed.append(Bucket)

    def put_bucket_cors(self, **request: Any) -> None:
        self.cors_requests.append(request)


def _store(client: _S3Client) -> S3ObjectStore:
    store = object.__new__(S3ObjectStore)
    store._client = client  # type: ignore[assignment]
    return store


@pytest.mark.asyncio
async def test_bucket_cors_is_applied_by_default() -> None:
    client = _S3Client()

    await _store(client).ensure_bucket(
        bucket="quarantine",
        allowed_origins=("https://catalog.example",),
    )

    assert client.headed == ["quarantine"]
    assert client.cors_requests[0]["CORSConfiguration"]["CORSRules"][0]["AllowedOrigins"] == [
        "https://catalog.example"
    ]


@pytest.mark.asyncio
async def test_external_cors_mode_still_checks_private_bucket() -> None:
    client = _S3Client()

    await _store(client).ensure_bucket(
        bucket="quarantine",
        allowed_origins=("https://catalog.example",),
        manage_cors=False,
    )

    assert client.headed == ["quarantine"]
    assert client.cors_requests == []
