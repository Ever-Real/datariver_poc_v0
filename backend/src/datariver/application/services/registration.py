from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from uuid import UUID

from datariver.application.dto import MultipartUpload
from datariver.application.ports import ObjectStore, UploadUnitOfWork
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ConflictError, DomainError, NotFoundError, utc_now, uuid7
from datariver.domain.registration import CompletedUploadPart, UploadManifest, UploadState


class UploadNotFound(NotFoundError):
    code = "upload_not_found"


class RegistrationService:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], UploadUnitOfWork],
        authorization: AuthorizationService,
        object_store: ObjectStore,
        quarantine_bucket: str,
        presign_ttl_seconds: int,
    ) -> None:
        self._uow_factory = uow_factory
        self._authorization = authorization
        self._object_store = object_store
        self._quarantine_bucket = quarantine_bucket
        self._presign_ttl_seconds = presign_ttl_seconds

    async def initiate(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        display_name: str,
        declared_size_bytes: int,
        declared_mime: str,
        declared_sha256: str,
        classification: Classification,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> UploadManifest:
        upload_id = uuid7()
        await self._authorization.authorize(
            subject=subject,
            resource=self._resource(
                upload_id=upload_id,
                workspace_id=workspace_id,
                owner_id=subject.subject_id,
                classification=classification,
                lifecycle=UploadState.INITIATED.value,
            ),
            action=Action.REGISTRATION_CREATE,
            environment=environment,
            request_id=request_id,
        )
        object_key = f"quarantine/{workspace_id}/{upload_id}"
        multipart: MultipartUpload | None = None
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            existing = await uow.idempotency.get_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation="upload.initiate",
            )
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise ConflictError("The idempotency key was used with a different request.")
                if existing.result.get("owner_id") != str(subject.subject_id):
                    raise ConflictError("The idempotency key belongs to another subject.")
                manifest = await uow.uploads.get_for_update(
                    workspace_id=workspace_id, upload_id=UUID(existing.result["upload_id"])
                )
                if manifest is None:
                    raise ConflictError("The idempotent upload result is unavailable.")
                return manifest
            try:
                multipart = await self._object_store.create_multipart_upload(
                    bucket=self._quarantine_bucket,
                    object_key=object_key,
                    content_type=declared_mime,
                    metadata={
                        "workspace-id": str(workspace_id),
                        "upload-id": str(upload_id),
                        "declared-sha256": declared_sha256,
                    },
                )
                manifest = UploadManifest(
                    upload_id=upload_id,
                    workspace_id=workspace_id,
                    owner_id=subject.subject_id,
                    bucket=multipart.bucket,
                    object_key=multipart.object_key,
                    display_name=display_name,
                    declared_size_bytes=declared_size_bytes,
                    declared_mime=declared_mime,
                    declared_sha256=declared_sha256,
                    classification=classification,
                    multipart_upload_id=multipart.upload_id,
                    expires_at=utc_now() + timedelta(hours=24),
                )
                await uow.uploads.add(manifest)
                await uow.idempotency.save_result(
                    workspace_id=workspace_id,
                    key=idempotency_key,
                    operation="upload.initiate",
                    request_hash=request_hash,
                    result={"upload_id": str(upload_id), "owner_id": str(subject.subject_id)},
                )
                await uow.commit()
                return manifest
            except Exception:
                if multipart is not None:
                    try:
                        await self._object_store.abort_multipart_upload(upload=multipart)
                    except DomainError:
                        pass
                raise

    async def presign_part(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        subject: SubjectAttributes,
        part_number: int,
        checksum_sha256: str | None,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[str, int]:
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            manifest = await uow.uploads.get_for_update(
                workspace_id=workspace_id, upload_id=upload_id
            )
            if manifest is None or manifest.expired:
                raise UploadNotFound("The upload does not exist or has expired.")
            await self._authorize_manifest(
                manifest=manifest,
                subject=subject,
                action=Action.REGISTRATION_CREATE,
                environment=environment,
                request_id=request_id,
            )
            if manifest.state is not UploadState.INITIATED:
                raise ConflictError("The upload is no longer accepting parts.")
            url = await self._object_store.presign_upload_part(
                upload=self._multipart(manifest),
                part_number=part_number,
                expires_seconds=self._presign_ttl_seconds,
                checksum_sha256=checksum_sha256,
            )
            return url, self._presign_ttl_seconds

    async def get_manifest(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> UploadManifest:
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            manifest = await uow.uploads.get_for_update(
                workspace_id=workspace_id,
                upload_id=upload_id,
            )
            if manifest is None:
                raise UploadNotFound("The upload does not exist.")
            await self._authorize_manifest(
                manifest=manifest,
                subject=subject,
                action=Action.REGISTRATION_READ,
                environment=environment,
                request_id=request_id,
            )
            return manifest

    async def list_manifests(
        self,
        *,
        workspace_id: UUID,
        state: UploadState | None,
        limit: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[UploadManifest, ...]:
        await self._authorization.authorize(
            subject=subject,
            resource=ResourceAttributes(
                resource_id=workspace_id,
                workspace_id=workspace_id,
                resource_type="upload_collection",
                owner_department_id=None,
                system_id=None,
                domain_id=None,
                classification=Classification.PUBLIC,
                lifecycle="ACTIVE",
            ),
            action=Action.REGISTRATION_READ,
            environment=environment,
            request_id=request_id,
        )
        owner_id = None if "security-administrators" in subject.groups else subject.subject_id
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            values = await uow.uploads.list(
                workspace_id=workspace_id,
                owner_id=owner_id,
                maximum_classification=int(subject.clearance),
                state=state.value if state else None,
                limit=limit,
            )
            await uow.commit()
        return tuple(values)

    async def queue_completion(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        subject: SubjectAttributes,
        parts: list[CompletedUploadPart],
        expected_version: int,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> UploadManifest:
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            manifest = await uow.uploads.get_for_update(
                workspace_id=workspace_id, upload_id=upload_id
            )
            if manifest is None or manifest.expired:
                raise UploadNotFound("The upload does not exist or has expired.")
            await self._authorize_manifest(
                manifest=manifest,
                subject=subject,
                action=Action.REGISTRATION_CREATE,
                environment=environment,
                request_id=request_id,
            )
            operation = f"upload.complete:{upload_id}"
            existing = await uow.idempotency.get_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
            )
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise ConflictError("The idempotency key was used with a different request.")
                if existing.result.get("owner_id") != str(subject.subject_id):
                    raise ConflictError("The idempotency key belongs to another subject.")
                return manifest
            manifest.queue_completion(parts=parts, expected_version=expected_version)
            await uow.uploads.save(manifest)
            await uow.outbox.add_events(manifest.events)
            await uow.idempotency.save_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                result={
                    "upload_id": str(upload_id),
                    "owner_id": str(subject.subject_id),
                    "version": manifest.version,
                },
            )
            await uow.commit()
        manifest.events.clear()
        return manifest

    async def _authorize_manifest(
        self,
        *,
        manifest: UploadManifest,
        subject: SubjectAttributes,
        action: Action,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> None:
        await self._authorization.authorize(
            subject=subject,
            resource=self._resource(
                upload_id=manifest.upload_id,
                workspace_id=manifest.workspace_id,
                owner_id=manifest.owner_id,
                classification=manifest.classification,
                lifecycle=manifest.state.value,
            ),
            action=action,
            environment=environment,
            request_id=request_id,
        )

    @staticmethod
    def _resource(
        *,
        upload_id: UUID,
        workspace_id: UUID,
        owner_id: UUID,
        classification: Classification,
        lifecycle: str,
    ) -> ResourceAttributes:
        return ResourceAttributes(
            resource_id=upload_id,
            workspace_id=workspace_id,
            resource_type="upload_manifest",
            owner_department_id=None,
            system_id=None,
            domain_id=None,
            classification=classification,
            lifecycle=lifecycle,
            requester_id=owner_id,
            owner_subject_id=owner_id,
        )

    @staticmethod
    def _multipart(manifest: UploadManifest) -> MultipartUpload:
        return MultipartUpload(
            upload_id=manifest.multipart_upload_id,
            bucket=manifest.bucket,
            object_key=manifest.object_key,
        )
