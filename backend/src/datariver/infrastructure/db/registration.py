from __future__ import annotations

from datetime import timedelta
from types import TracebackType
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.application.dto import ObjectMetadata
from datariver.application.ports import (
    UploadCompletionStore,
    UploadRepository,
    UploadUnitOfWork,
    UploadValidationStore,
)
from datariver.domain.authz import Classification
from datariver.domain.common import utc_now
from datariver.domain.registration import CompletedUploadPart, UploadManifest, UploadState
from datariver.infrastructure.db.governance import SqlIdempotencyStore, SqlOutboxWriter
from datariver.infrastructure.db.models.integration import ObjectManifestModel
from datariver.infrastructure.db.rls import set_security_context


class SqlUploadRepository(UploadRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tracked: dict[UUID, ObjectManifestModel] = {}

    async def add(self, manifest: UploadManifest) -> None:
        model = ObjectManifestModel(
            id=manifest.upload_id,
            workspace_id=manifest.workspace_id,
            bucket=manifest.bucket,
            object_key=manifest.object_key,
            display_name=manifest.display_name,
            multipart_upload_id=manifest.multipart_upload_id,
            size_bytes=manifest.declared_size_bytes,
            mime=manifest.declared_mime,
            sha256=manifest.declared_sha256,
            actual_size_bytes=manifest.actual_size_bytes,
            actual_mime=manifest.actual_mime,
            actual_sha256=manifest.actual_sha256,
            processing_lease_until=None,
            processing_attempts=manifest.processing_attempts,
            validation_attempts=manifest.validation_attempts,
            last_error_code=None,
            validation_summary=manifest.validation_summary,
            completion_parts=[],
            state=manifest.state.value,
            classification=int(manifest.classification),
            owner_id=manifest.owner_id,
            retention_until=None,
            expires_at=manifest.expires_at,
            version=manifest.version,
        )
        self._session.add(model)
        self._tracked[manifest.upload_id] = model

    async def get_for_update(self, *, workspace_id: UUID, upload_id: UUID) -> UploadManifest | None:
        model = (
            await self._session.scalars(
                select(ObjectManifestModel)
                .where(
                    ObjectManifestModel.id == upload_id,
                    ObjectManifestModel.workspace_id == workspace_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        if model is None or model.expires_at is None:
            return None
        self._tracked[upload_id] = model
        return _to_domain(model)

    async def save(self, manifest: UploadManifest) -> None:
        model = self._tracked[manifest.upload_id]
        _apply_manifest(model, manifest)

    async def list(
        self,
        *,
        workspace_id: UUID,
        owner_id: UUID | None,
        maximum_classification: int,
        state: str | None,
        limit: int,
    ) -> list[UploadManifest]:
        statement = select(ObjectManifestModel.id).where(
            ObjectManifestModel.workspace_id == workspace_id,
            ObjectManifestModel.classification <= maximum_classification,
        )
        if owner_id is not None:
            statement = statement.where(ObjectManifestModel.owner_id == owner_id)
        if state is not None:
            statement = statement.where(ObjectManifestModel.state == state)
        ids = list(
            (
                await self._session.scalars(
                    statement.order_by(ObjectManifestModel.created_at.desc()).limit(limit)
                )
            ).all()
        )
        values: list[UploadManifest] = []
        for upload_id in ids:
            value = await self.get_for_update(workspace_id=workspace_id, upload_id=upload_id)
            if value is not None:
                values.append(value)
        return values


def _to_domain(model: ObjectManifestModel) -> UploadManifest:
    if model.expires_at is None:
        raise ValueError("An upload manifest must have an expiry timestamp.")
    return UploadManifest(
        upload_id=model.id,
        workspace_id=model.workspace_id,
        owner_id=model.owner_id,
        bucket=model.bucket,
        object_key=model.object_key,
        display_name=model.display_name,
        declared_size_bytes=model.size_bytes,
        declared_mime=model.mime,
        declared_sha256=model.sha256,
        classification=Classification(model.classification),
        multipart_upload_id=model.multipart_upload_id or "",
        expires_at=model.expires_at,
        state=UploadState(model.state),
        version=model.version,
        completion_parts=[
            CompletedUploadPart(
                part_number=int(part["part_number"]),
                etag=str(part["etag"]),
                checksum_sha256=(
                    str(part["checksum_sha256"])
                    if part.get("checksum_sha256") is not None
                    else None
                ),
            )
            for part in model.completion_parts
        ],
        actual_size_bytes=model.actual_size_bytes,
        actual_mime=model.actual_mime,
        actual_sha256=model.actual_sha256,
        processing_attempts=model.processing_attempts,
        validation_attempts=model.validation_attempts,
        validation_summary=model.validation_summary,
        last_error_code=model.last_error_code,
    )


def _apply_manifest(model: ObjectManifestModel, manifest: UploadManifest) -> None:
    model.state = manifest.state.value
    model.version = manifest.version
    model.actual_size_bytes = manifest.actual_size_bytes
    model.actual_mime = manifest.actual_mime
    model.actual_sha256 = manifest.actual_sha256
    model.processing_attempts = manifest.processing_attempts
    model.validation_attempts = manifest.validation_attempts
    model.validation_summary = manifest.validation_summary
    model.bucket = manifest.bucket
    model.object_key = manifest.object_key
    model.completion_parts = [
        {
            "part_number": part.part_number,
            "etag": part.etag,
            "checksum_sha256": part.checksum_sha256,
        }
        for part in manifest.completion_parts
    ]


class SqlUploadCompletionStore(UploadCompletionStore):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def claim_next(
        self, *, lease_seconds: int, maximum_attempts: int
    ) -> UploadManifest | None:
        now = utc_now()
        async with self._session_factory() as session, session.begin():
            model = (
                await session.scalars(
                    select(ObjectManifestModel)
                    .where(
                        ObjectManifestModel.expires_at > now,
                        ObjectManifestModel.processing_attempts < maximum_attempts,
                        or_(
                            ObjectManifestModel.state == UploadState.COMPLETION_QUEUED.value,
                            and_(
                                ObjectManifestModel.state == UploadState.COMPLETING.value,
                                ObjectManifestModel.processing_lease_until < now,
                            ),
                        ),
                    )
                    .order_by(ObjectManifestModel.created_at)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
            ).one_or_none()
            if model is None:
                return None
            manifest = _to_domain(model)
            manifest.begin_completion(expected_version=manifest.version)
            _apply_manifest(model, manifest)
            model.processing_lease_until = now + timedelta(seconds=lease_seconds)
            model.last_error_code = None
        return manifest

    async def mark_quarantined(self, *, manifest: UploadManifest, metadata: ObjectMetadata) -> None:
        async with self._session_factory() as session, session.begin():
            model = await self._locked(session, manifest)
            if model is None or model.version != manifest.version:
                return
            current = _to_domain(model)
            current.mark_quarantined(
                actual_size_bytes=metadata.size_bytes,
                actual_mime=metadata.content_type,
                checksum_sha256=metadata.checksum_sha256,
                expected_version=current.version,
            )
            _apply_manifest(model, current)
            model.processing_lease_until = None
            model.last_error_code = None
            await SqlOutboxWriter(session).add_events(current.events)

    async def mark_failed(
        self,
        *,
        manifest: UploadManifest,
        error_code: str,
        retryable: bool,
        maximum_attempts: int,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            model = await self._locked(session, manifest)
            if model is None or model.version != manifest.version:
                return
            current = _to_domain(model)
            may_retry = retryable and current.processing_attempts < maximum_attempts
            current.mark_completion_failed(
                retryable=may_retry,
                expected_version=current.version,
            )
            _apply_manifest(model, current)
            model.processing_lease_until = None
            model.last_error_code = error_code
            await SqlOutboxWriter(session).add_events(current.events)

    @staticmethod
    async def _locked(
        session: AsyncSession, manifest: UploadManifest
    ) -> ObjectManifestModel | None:
        return (
            await session.scalars(
                select(ObjectManifestModel)
                .where(
                    ObjectManifestModel.id == manifest.upload_id,
                    ObjectManifestModel.workspace_id == manifest.workspace_id,
                )
                .with_for_update()
            )
        ).one_or_none()


class SqlUploadValidationStore(UploadValidationStore):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def claim_next(
        self, *, lease_seconds: int, maximum_attempts: int
    ) -> UploadManifest | None:
        now = utc_now()
        async with self._session_factory() as session, session.begin():
            model = (
                await session.scalars(
                    select(ObjectManifestModel)
                    .where(
                        ObjectManifestModel.expires_at > now,
                        ObjectManifestModel.validation_attempts < maximum_attempts,
                        or_(
                            ObjectManifestModel.state == UploadState.QUARANTINED.value,
                            and_(
                                ObjectManifestModel.state == UploadState.VALIDATING.value,
                                ObjectManifestModel.processing_lease_until < now,
                            ),
                        ),
                    )
                    .order_by(ObjectManifestModel.created_at)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
            ).one_or_none()
            if model is None:
                return None
            manifest = _to_domain(model)
            manifest.begin_validation(expected_version=manifest.version)
            _apply_manifest(model, manifest)
            model.processing_lease_until = now + timedelta(seconds=lease_seconds)
            model.last_error_code = None
        return manifest

    async def mark_accepted(
        self,
        *,
        manifest: UploadManifest,
        accepted_bucket: str,
        accepted_object_key: str,
        validation_summary: dict[str, object],
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            model = await SqlUploadCompletionStore._locked(session, manifest)
            if model is None or model.version != manifest.version:
                return False
            current = _to_domain(model)
            current.mark_accepted(
                accepted_bucket=accepted_bucket,
                accepted_object_key=accepted_object_key,
                validation_summary=validation_summary,
                expected_version=current.version,
            )
            _apply_manifest(model, current)
            model.processing_lease_until = None
            model.last_error_code = None
            await SqlOutboxWriter(session).add_events(current.events)
        return True

    async def mark_failed(
        self,
        *,
        manifest: UploadManifest,
        error_code: str,
        retryable: bool,
        maximum_attempts: int,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            model = await SqlUploadCompletionStore._locked(session, manifest)
            if model is None or model.version != manifest.version:
                return
            current = _to_domain(model)
            may_retry = retryable and current.validation_attempts < maximum_attempts
            current.mark_validation_failed(
                retryable=may_retry,
                expected_version=current.version,
            )
            _apply_manifest(model, current)
            model.processing_lease_until = None
            model.last_error_code = error_code
            await SqlOutboxWriter(session).add_events(current.events)


class SqlUploadUnitOfWork(UploadUnitOfWork):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self.uploads: SqlUploadRepository
        self.outbox: SqlOutboxWriter
        self.idempotency: SqlIdempotencyStore
        self._committed = False

    async def __aenter__(self) -> SqlUploadUnitOfWork:
        self._session = self._session_factory()
        self.uploads = SqlUploadRepository(self._session)
        self.outbox = SqlOutboxWriter(self._session)
        self.idempotency = SqlIdempotencyStore(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_value, traceback
        if self._session is None:
            return
        if exc_type is not None or not self._committed:
            await self._session.rollback()
        await self._session.close()

    async def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await self._session.commit()
        self._committed = True

    async def rollback(self) -> None:
        if self._session is not None:
            await self._session.rollback()

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await set_security_context(self._session, workspace_id=workspace_id, subject_id=subject_id)
