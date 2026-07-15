from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from typing import cast
from uuid import uuid4

from datariver.application.dto import MultipartUpload, ObjectMetadata
from datariver.application.errors import ExternalDependencyError
from datariver.application.ports import ObjectStore
from datariver.application.services.upload_completion import UploadCompletionWorker
from datariver.domain.authz import Classification
from datariver.domain.common import utc_now
from datariver.domain.registration import CompletedUploadPart, UploadManifest


def claimed_manifest() -> UploadManifest:
    upload = UploadManifest(
        upload_id=uuid4(),
        workspace_id=uuid4(),
        owner_id=uuid4(),
        bucket="quarantine",
        object_key="quarantine/object",
        display_name="catalog.csv",
        declared_size_bytes=10,
        declared_mime="text/csv",
        declared_sha256="a" * 64,
        classification=Classification.INTERNAL,
        multipart_upload_id="multipart-1",
        expires_at=utc_now() + timedelta(hours=1),
    )
    upload.queue_completion(
        parts=[CompletedUploadPart(part_number=1, etag="etag")], expected_version=1
    )
    upload.begin_completion(expected_version=2)
    return upload


class FakeStore:
    def __init__(self, upload: UploadManifest) -> None:
        self.upload = upload
        self.quarantined: ObjectMetadata | None = None
        self.failure: tuple[str, bool] | None = None

    async def claim_next(
        self, *, lease_seconds: int, maximum_attempts: int
    ) -> UploadManifest | None:
        del lease_seconds, maximum_attempts
        claimed, self.upload = self.upload, None  # type: ignore[assignment]
        return claimed

    async def mark_quarantined(self, *, manifest: UploadManifest, metadata: ObjectMetadata) -> None:
        del manifest
        self.quarantined = metadata

    async def mark_failed(
        self,
        *,
        manifest: UploadManifest,
        error_code: str,
        retryable: bool,
        maximum_attempts: int,
    ) -> None:
        del manifest, maximum_attempts
        self.failure = (error_code, retryable)


class FakeObjectStore:
    def __init__(self, complete_error: ExternalDependencyError | None = None) -> None:
        self.complete_error = complete_error
        self.head_calls = 0
        self.metadata = ObjectMetadata(
            bucket="quarantine",
            object_key="quarantine/object",
            size_bytes=10,
            content_type="text/csv",
            etag="etag",
            checksum_sha256=None,
            user_metadata={},
        )

    async def create_multipart_upload(
        self, *, bucket: str, object_key: str, content_type: str, metadata: dict[str, str]
    ) -> MultipartUpload:
        raise NotImplementedError

    async def presign_upload_part(
        self,
        *,
        upload: MultipartUpload,
        part_number: int,
        expires_seconds: int,
        checksum_sha256: str | None = None,
    ) -> str:
        raise NotImplementedError

    async def complete_multipart_upload(
        self, *, upload: MultipartUpload, parts: Sequence[CompletedUploadPart]
    ) -> ObjectMetadata:
        del upload, parts
        if self.complete_error is not None:
            raise self.complete_error
        return self.metadata

    async def abort_multipart_upload(self, *, upload: MultipartUpload) -> None:
        raise NotImplementedError

    async def head_object(self, *, bucket: str, object_key: str) -> ObjectMetadata:
        del bucket, object_key
        self.head_calls += 1
        return self.metadata

    async def presign_download(
        self,
        *,
        bucket: str,
        object_key: str,
        download_name: str,
        expires_seconds: int,
    ) -> str:
        raise NotImplementedError


async def test_completes_and_quarantines_claim() -> None:
    store = FakeStore(claimed_manifest())
    object_store = FakeObjectStore()
    worker = UploadCompletionWorker(store=store, object_store=cast(ObjectStore, object_store))

    assert await worker.run_once() is True
    assert store.quarantined == object_store.metadata
    assert store.failure is None


async def test_reconciles_object_after_crash_between_external_and_database_commit() -> None:
    error = ExternalDependencyError(
        "already completed",
        dependency="object_store",
        retryable=False,
        provider_code="NoSuchUpload",
    )
    store = FakeStore(claimed_manifest())
    object_store = FakeObjectStore(error)
    worker = UploadCompletionWorker(store=store, object_store=cast(ObjectStore, object_store))

    assert await worker.run_once() is True
    assert object_store.head_calls == 1
    assert store.quarantined == object_store.metadata
