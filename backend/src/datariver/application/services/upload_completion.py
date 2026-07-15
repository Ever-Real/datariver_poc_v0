from __future__ import annotations

from datariver.application.dto import MultipartUpload, ObjectMetadata
from datariver.application.errors import ExternalDependencyError
from datariver.application.ports import ObjectStore, UploadCompletionStore
from datariver.domain.common import DomainError
from datariver.domain.registration import UploadManifest


class UploadCompletionWorker:
    """Completes one durable upload claim; PostgreSQL remains the source of truth."""

    def __init__(
        self,
        *,
        store: UploadCompletionStore,
        object_store: ObjectStore,
        lease_seconds: int = 120,
        maximum_attempts: int = 8,
    ) -> None:
        self._store = store
        self._object_store = object_store
        self._lease_seconds = lease_seconds
        self._maximum_attempts = maximum_attempts

    async def run_once(self) -> bool:
        manifest = await self._store.claim_next(
            lease_seconds=self._lease_seconds,
            maximum_attempts=self._maximum_attempts,
        )
        if manifest is None:
            return False

        try:
            metadata = await self._complete_or_reconcile(manifest)
            await self._store.mark_quarantined(manifest=manifest, metadata=metadata)
        except DomainError as error:
            await self._store.mark_failed(
                manifest=manifest,
                error_code=self._error_code(error),
                retryable=self._retryable(error),
                maximum_attempts=self._maximum_attempts,
            )
        return True

    async def _complete_or_reconcile(self, manifest: UploadManifest) -> ObjectMetadata:
        upload = MultipartUpload(
            upload_id=manifest.multipart_upload_id,
            bucket=manifest.bucket,
            object_key=manifest.object_key,
        )
        try:
            return await self._object_store.complete_multipart_upload(
                upload=upload,
                parts=manifest.completion_parts,
            )
        except ExternalDependencyError as error:
            if error.details.get("provider_code") not in {
                "NoSuchUpload",
                "NoSuchKey",
                "InvalidRequest",
            }:
                raise
            return await self._object_store.head_object(
                bucket=manifest.bucket,
                object_key=manifest.object_key,
            )

    @staticmethod
    def _retryable(error: DomainError) -> bool:
        return bool(error.details.get("retryable", False))

    @staticmethod
    def _error_code(error: DomainError) -> str:
        provider_code = error.details.get("provider_code")
        return str(provider_code or error.code)[:100]
