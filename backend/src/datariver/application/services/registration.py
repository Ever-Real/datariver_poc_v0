from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from uuid import UUID

from datariver.application.dto import MultipartUpload
from datariver.application.ports import ObjectStore, UploadUnitOfWork
from datariver.application.services.authorization import AuthorizationService
from datariver.application.typed_upload_profiles import (
    TypedUploadProfileDefinition,
    typed_profile_definition,
    validate_upload_profile,
)
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import (
    ConflictError,
    DomainError,
    NotFoundError,
    canonical_json_hash,
    utc_now,
    uuid7,
)
from datariver.domain.registration import (
    CompletedUploadPart,
    UploadContentProfile,
    UploadManifest,
    UploadPreparation,
    UploadPreparationState,
    UploadState,
)


class UploadNotFound(NotFoundError):
    code = "upload_not_found"


class UploadPreparationNotFound(NotFoundError):
    code = "upload_preparation_not_found"


class UploadAuthorizationPolicy(StrEnum):
    REGISTRATION = "REGISTRATION"
    KNOWLEDGE_STUDIO = "KNOWLEDGE_STUDIO"


@dataclass(frozen=True, slots=True)
class UploadAuthorizationActions:
    initiate: Action
    presign_part: Action
    read_manifest: Action
    queue_completion: Action


_UPLOAD_AUTHORIZATION_ACTIONS = {
    UploadAuthorizationPolicy.REGISTRATION: UploadAuthorizationActions(
        initiate=Action.REGISTRATION_CREATE,
        presign_part=Action.REGISTRATION_CREATE,
        read_manifest=Action.REGISTRATION_READ,
        queue_completion=Action.REGISTRATION_CREATE,
    ),
    UploadAuthorizationPolicy.KNOWLEDGE_STUDIO: UploadAuthorizationActions(
        initiate=Action.KG_EDIT,
        presign_part=Action.KG_EDIT,
        read_manifest=Action.KG_EDIT,
        queue_completion=Action.KG_EDIT,
    ),
}


def upload_authorization_actions(
    policy: UploadAuthorizationPolicy,
) -> UploadAuthorizationActions:
    """Resolve a server-owned action set; callers cannot inject arbitrary actions."""

    return _UPLOAD_AUTHORIZATION_ACTIONS[policy]


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
        content_profile: UploadContentProfile,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
        authorization_policy: UploadAuthorizationPolicy = UploadAuthorizationPolicy.REGISTRATION,
    ) -> UploadManifest:
        actions = upload_authorization_actions(authorization_policy)
        validate_upload_profile(
            content_profile=content_profile,
            display_name=display_name,
            content_type=declared_mime,
            size_bytes=declared_size_bytes,
        )
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
            action=actions.initiate,
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
                        "content-profile": content_profile.value,
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
                    content_profile=content_profile,
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
        authorization_policy: UploadAuthorizationPolicy = UploadAuthorizationPolicy.REGISTRATION,
    ) -> tuple[str, int]:
        actions = upload_authorization_actions(authorization_policy)
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
                action=actions.presign_part,
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
        authorization_policy: UploadAuthorizationPolicy = UploadAuthorizationPolicy.REGISTRATION,
    ) -> UploadManifest:
        actions = upload_authorization_actions(authorization_policy)
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            manifest = await uow.uploads.get(
                workspace_id=workspace_id,
                upload_id=upload_id,
            )
            if manifest is None:
                raise UploadNotFound("The upload does not exist.")
            await self._authorize_manifest(
                manifest=manifest,
                subject=subject,
                action=actions.read_manifest,
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
        authorization_policy: UploadAuthorizationPolicy = UploadAuthorizationPolicy.REGISTRATION,
    ) -> UploadManifest:
        actions = upload_authorization_actions(authorization_policy)
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
                action=actions.queue_completion,
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

    async def create_preparation(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        subject: SubjectAttributes,
        expected_manifest_version: int,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
    ) -> UploadPreparation:
        async with self._uow_factory() as uow:
            await uow.set_security_context(
                workspace_id=workspace_id,
                subject_id=subject.subject_id,
            )
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
            await self._authorize_manifest(
                manifest=manifest,
                subject=subject,
                action=Action.REGISTRATION_VALIDATE,
                environment=environment,
                request_id=request_id,
            )
            if manifest.version != expected_manifest_version:
                raise ConflictError(
                    "The upload was modified by another operation.",
                    details={
                        "expected": expected_manifest_version,
                        "actual": manifest.version,
                    },
                )
            definition = typed_profile_definition(manifest.content_profile)
            self._verify_preparation_source(manifest=manifest, definition=definition)
            operation = f"upload.preparation.create:{upload_id}"
            request_hash = canonical_json_hash(
                {
                    "configuration_hash": definition.configuration_hash,
                    "content_profile": manifest.content_profile.value,
                    "expected_manifest_version": expected_manifest_version,
                    "source_sha256": manifest.declared_sha256,
                    "upload_id": str(upload_id),
                    "workspace_id": str(workspace_id),
                }
            )
            idempotent = await uow.idempotency.get_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
            )
            if idempotent is not None:
                if idempotent.request_hash != request_hash:
                    raise ConflictError("The idempotency key was used with a different request.")
                if idempotent.result.get("owner_id") != str(subject.subject_id):
                    raise ConflictError("The idempotency key belongs to another subject.")
                preparation = await uow.preparations.get(
                    workspace_id=workspace_id,
                    upload_id=upload_id,
                    preparation_id=UUID(str(idempotent.result["preparation_id"])),
                )
                if preparation is None:
                    raise ConflictError("The idempotent preparation result is unavailable.")
                return preparation

            preparation = await uow.preparations.find_source_configuration(
                workspace_id=workspace_id,
                upload_id=upload_id,
                source_manifest_version=manifest.version,
                content_profile=manifest.content_profile.value,
                configuration_hash=definition.configuration_hash,
            )
            created = preparation is None
            if preparation is None:
                preparation = UploadPreparation.queue(
                    workspace_id=workspace_id,
                    upload_id=upload_id,
                    requested_by=subject.subject_id,
                    content_profile=manifest.content_profile,
                    source_manifest_version=manifest.version,
                    source_sha256=manifest.declared_sha256,
                    configuration_hash=definition.configuration_hash,
                )
                await uow.preparations.add(preparation)
                await uow.outbox.add_events(preparation.events)
            await uow.idempotency.save_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                result={
                    "preparation_id": str(preparation.preparation_id),
                    "owner_id": str(subject.subject_id),
                },
            )
            await uow.commit()
        if created:
            preparation.events.clear()
        return preparation

    async def get_preparation(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        preparation_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> UploadPreparation:
        async with self._uow_factory() as uow:
            await uow.set_security_context(
                workspace_id=workspace_id,
                subject_id=subject.subject_id,
            )
            manifest = await uow.uploads.get(
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
            preparation = await uow.preparations.get(
                workspace_id=workspace_id,
                upload_id=upload_id,
                preparation_id=preparation_id,
            )
            if preparation is None:
                raise UploadPreparationNotFound("The upload preparation does not exist.")
            return preparation

    async def list_preparations(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        state: UploadPreparationState | None,
        limit: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[UploadPreparation, ...]:
        async with self._uow_factory() as uow:
            await uow.set_security_context(
                workspace_id=workspace_id,
                subject_id=subject.subject_id,
            )
            manifest = await uow.uploads.get(
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
            preparations = await uow.preparations.list(
                workspace_id=workspace_id,
                upload_id=upload_id,
                state=state.value if state is not None else None,
                limit=limit,
            )
            return tuple(preparations)

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

    @staticmethod
    def _verify_preparation_source(
        *,
        manifest: UploadManifest,
        definition: TypedUploadProfileDefinition,
    ) -> None:
        if manifest.state is not UploadState.ACCEPTED:
            raise ConflictError("Only an accepted upload can create a typed preparation.")
        if (
            manifest.declared_mime != definition.content_type
            or not manifest.display_name.lower().endswith(definition.filename_suffix)
        ):
            raise ConflictError("The accepted upload does not match its typed content profile.")
        summary = manifest.validation_summary
        expected_evidence: tuple[tuple[str, object], ...] = (
            ("validator_version", definition.acceptance_validator_version),
            ("sha256", manifest.declared_sha256),
            ("size_bytes", manifest.declared_size_bytes),
            ("content_type", manifest.declared_mime),
        )
        if any(summary.get(key) != expected for key, expected in expected_evidence):
            raise ConflictError("The accepted upload validation evidence is incomplete or stale.")
        if (
            manifest.actual_size_bytes != manifest.declared_size_bytes
            or manifest.actual_mime != manifest.declared_mime
            or manifest.actual_sha256 != manifest.declared_sha256
        ):
            raise ConflictError("The accepted upload metadata does not match its declaration.")
