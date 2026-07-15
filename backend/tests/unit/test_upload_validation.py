from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest

from datariver.application.dto import ObjectMetadata
from datariver.application.ports import ObjectStore
from datariver.application.services.upload_validation import UploadValidationWorker
from datariver.domain.authz import Classification
from datariver.domain.registration import UploadManifest, UploadState


class MemoryValidationStore:
    def __init__(self, manifest: UploadManifest) -> None:
        self.manifest: UploadManifest | None = manifest
        self.accepted: dict[str, object] | None = None
        self.failed: tuple[str, bool] | None = None

    async def claim_next(
        self, *, lease_seconds: int, maximum_attempts: int
    ) -> UploadManifest | None:
        del lease_seconds, maximum_attempts
        value, self.manifest = self.manifest, None
        return value

    async def mark_accepted(
        self,
        *,
        manifest: UploadManifest,
        accepted_bucket: str,
        accepted_object_key: str,
        validation_summary: dict[str, object],
    ) -> None:
        del manifest, accepted_bucket, accepted_object_key
        self.accepted = validation_summary

    async def mark_failed(
        self,
        *,
        manifest: UploadManifest,
        error_code: str,
        retryable: bool,
        maximum_attempts: int,
    ) -> None:
        del manifest, maximum_attempts
        self.failed = (error_code, retryable)


class MemoryObjectStore:
    def __init__(self, content: bytes, content_type: str) -> None:
        self.content = content
        self.content_type = content_type
        self.deleted = False

    async def iter_object_chunks(
        self, *, bucket: str, object_key: str, chunk_size: int = 1024 * 1024
    ) -> AsyncIterator[bytes]:
        del bucket, object_key, chunk_size
        midpoint = max(len(self.content) // 2, 1)
        yield self.content[:midpoint]
        if self.content[midpoint:]:
            yield self.content[midpoint:]

    async def copy_object(
        self,
        *,
        source_bucket: str,
        source_key: str,
        destination_bucket: str,
        destination_key: str,
    ) -> ObjectMetadata:
        del source_bucket, source_key
        return ObjectMetadata(
            destination_bucket,
            destination_key,
            len(self.content),
            self.content_type,
            "etag",
            hashlib.sha256(self.content).hexdigest(),
            {},
        )

    async def delete_object(self, *, bucket: str, object_key: str) -> None:
        del bucket, object_key
        self.deleted = True


def manifest(content: bytes, *, declared_hash: str | None = None) -> UploadManifest:
    return UploadManifest(
        upload_id=uuid4(),
        workspace_id=uuid4(),
        owner_id=uuid4(),
        bucket="quarantine",
        object_key="object",
        display_name="assets.csv",
        declared_size_bytes=len(content),
        declared_mime="text/csv",
        declared_sha256=declared_hash or hashlib.sha256(content).hexdigest(),
        classification=Classification.INTERNAL,
        multipart_upload_id="multipart",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        state=UploadState.VALIDATING,
    )


@pytest.mark.asyncio
async def test_streaming_csv_integrity_validation_promotes_then_cleans_quarantine() -> None:
    content = b"asset_id,name\n1,wafer\n2,die\n"
    upload = manifest(content)
    store = MemoryValidationStore(upload)
    objects = MemoryObjectStore(content, "text/csv")
    worker = UploadValidationWorker(
        store=store,
        object_store=cast(ObjectStore, objects),
        accepted_bucket="accepted",
    )

    assert await worker.run_once() is True
    assert store.failed is None
    assert store.accepted is not None
    assert store.accepted["column_count"] == 2
    assert objects.deleted is True


@pytest.mark.asyncio
async def test_checksum_mismatch_is_terminal_and_never_promoted() -> None:
    content = b"asset_id,name\n1,wafer\n"
    upload = manifest(content, declared_hash="0" * 64)
    store = MemoryValidationStore(upload)
    objects = MemoryObjectStore(content, "text/csv")
    worker = UploadValidationWorker(
        store=store,
        object_store=cast(ObjectStore, objects),
        accepted_bucket="accepted",
    )

    assert await worker.run_once() is True
    assert store.accepted is None
    assert store.failed == ("CHECKSUM_MISMATCH", False)
    assert objects.deleted is False
