from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.application.catalog_export_csv import CSV_SAFETY_VERSION
from datariver.application.catalog_security import (
    catalog_classification_access_hash,
    catalog_permission_scope_hash,
)
from datariver.application.classification_access import (
    ClassificationAccessResolver,
)
from datariver.application.dto import (
    CatalogExportArtifact,
    CatalogExportClaim,
    CatalogExportRecord,
    CatalogExportRequest,
    CatalogPage,
)
from datariver.application.ports import CatalogExportStore, CatalogExportWorkerStore
from datariver.domain.authz import BuiltinPolicyEngine, Classification, SubjectAttributes
from datariver.domain.common import (
    ConflictError,
    DomainEvent,
    Effect,
    ForbiddenError,
    utc_now,
    uuid7,
)
from datariver.infrastructure.db.authz import subject_attributes_from_models
from datariver.infrastructure.db.catalog import SqlCatalogIndexReader
from datariver.infrastructure.db.classification_access import (
    SqlClassificationAccessSnapshotReader,
)
from datariver.infrastructure.db.governance import SqlIdempotencyStore, SqlOutboxWriter
from datariver.infrastructure.db.models.authz import PolicyDecisionModel
from datariver.infrastructure.db.models.catalog import (
    CatalogExportModel,
    CatalogProjectionWatermarkModel,
)
from datariver.infrastructure.db.models.integration import JobAttemptModel, JobModel
from datariver.infrastructure.db.models.platform import (
    SubjectModel,
    WorkspaceMembershipModel,
    WorkspaceModel,
)
from datariver.infrastructure.db.rls import set_security_context

JOB_TYPE = "CATALOG_EXPORT"


class SqlCatalogExportStore(CatalogExportStore):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        workspace_id: UUID,
        requested_by: UUID,
        request: CatalogExportRequest,
        request_hash: str,
        permission_scope_hash: str,
        classification_access_hash: str,
        builtin_policy_version: str,
        classification_policy_id: UUID | None,
        classification_policy_hash: str | None,
        classification_policy_version: int | None,
        authorization_generation: int | None,
        source_projection_version: int,
        classification_ceiling: int,
        csv_safety_version: str,
        access_until: datetime,
        idempotency_key: str,
    ) -> CatalogExportRecord:
        operation = f"catalog.export.create:{requested_by}"
        idempotency = SqlIdempotencyStore(self._session)
        existing = await idempotency.get_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ConflictError("The idempotency key was reused with a different export.")
            export_id = UUID(str(existing.result["export_id"]))
            record = await self.get_owned(
                workspace_id=workspace_id,
                export_id=export_id,
                requested_by=requested_by,
            )
            if record is None:
                raise ConflictError("The idempotent catalog export result is unavailable.")
            return record

        export_id = uuid7()
        job_id = uuid7()
        model = CatalogExportModel(
            id=export_id,
            workspace_id=workspace_id,
            job_id=job_id,
            requested_by=requested_by,
            request_document=request.document(),
            request_hash=request_hash,
            permission_scope_hash=permission_scope_hash,
            classification_access_hash=classification_access_hash,
            builtin_policy_version=builtin_policy_version,
            classification_policy_id=classification_policy_id,
            classification_policy_hash=classification_policy_hash,
            classification_policy_version=classification_policy_version,
            authorization_generation=authorization_generation,
            source_projection_version=source_projection_version,
            classification_ceiling=classification_ceiling,
            csv_safety_version=csv_safety_version,
            object_bucket=None,
            object_key=None,
            display_name=f"catalog-export-{export_id}.csv",
            mime="text/csv; charset=utf-8",
            row_count=None,
            size_bytes=None,
            content_sha256=None,
            provider_checksum=None,
            completed_at=None,
            access_until=access_until,
            version=1,
        )
        job = JobModel(
            id=job_id,
            workspace_id=workspace_id,
            job_type=JOB_TYPE,
            causation_id=export_id,
            state="QUEUED",
            requested_by=requested_by,
            progress={},
            result_ref=None,
            lease_until=None,
            attempts=0,
            last_error_code=None,
            version=1,
        )
        self._session.add_all((model, job))
        event = DomainEvent.create(
            event_type="catalog.export.requested.v1",
            aggregate_type="catalog_export",
            aggregate_id=export_id,
            workspace_id=workspace_id,
            payload={
                "export_id": str(export_id),
                "job_id": str(job_id),
                "request_hash": request_hash,
                "permission_scope_hash": permission_scope_hash,
                "classification_access_hash": classification_access_hash,
                "source_projection_version": source_projection_version,
            },
        )
        await SqlOutboxWriter(self._session).add_events((event,))
        await idempotency.save_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
            request_hash=request_hash,
            result={"export_id": str(export_id), "job_id": str(job_id)},
        )
        await self._session.flush()
        record = _to_record(model, job)
        await self._session.commit()
        return record

    async def get_owned(
        self, *, workspace_id: UUID, export_id: UUID, requested_by: UUID
    ) -> CatalogExportRecord | None:
        row = (
            await self._session.execute(
                select(CatalogExportModel, JobModel)
                .join(
                    JobModel,
                    and_(
                        JobModel.workspace_id == CatalogExportModel.workspace_id,
                        JobModel.id == CatalogExportModel.job_id,
                    ),
                )
                .where(
                    CatalogExportModel.workspace_id == workspace_id,
                    CatalogExportModel.id == export_id,
                    CatalogExportModel.requested_by == requested_by,
                )
            )
        ).one_or_none()
        return _to_record(*row) if row is not None else None


class SqlCatalogExportWorkerStore(CatalogExportWorkerStore):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def claim_next(
        self,
        *,
        worker_id: str,
        system_actor_id: UUID,
        lease_seconds: int,
        maximum_attempts: int,
    ) -> CatalogExportClaim | None:
        # The export role is deliberately NOBYPASSRLS. It may enumerate only workspace
        # identifiers, then every business-table transaction is pinned to one workspace.
        async with self._session_factory() as discovery_session:
            workspace_ids = tuple(
                (
                    await discovery_session.scalars(
                        select(WorkspaceModel.id).order_by(WorkspaceModel.id).limit(10_000)
                    )
                ).all()
            )
        for workspace_id in workspace_ids:
            claim = await self._claim_in_workspace(
                workspace_id=workspace_id,
                worker_id=worker_id,
                system_actor_id=system_actor_id,
                lease_seconds=lease_seconds,
                maximum_attempts=maximum_attempts,
            )
            if claim is not None:
                return claim
        return None

    async def _claim_in_workspace(
        self,
        *,
        workspace_id: UUID,
        worker_id: str,
        system_actor_id: UUID,
        lease_seconds: int,
        maximum_attempts: int,
    ) -> CatalogExportClaim | None:
        now = utc_now()
        async with self._session_factory() as session, session.begin():
            await set_security_context(
                session,
                workspace_id=workspace_id,
                subject_id=system_actor_id,
            )
            row = (
                await session.execute(
                    select(CatalogExportModel, JobModel)
                    .join(
                        JobModel,
                        and_(
                            JobModel.workspace_id == CatalogExportModel.workspace_id,
                            JobModel.id == CatalogExportModel.job_id,
                            JobModel.job_type == JOB_TYPE,
                        ),
                    )
                    .where(
                        CatalogExportModel.workspace_id == workspace_id,
                        JobModel.attempts < maximum_attempts,
                        or_(
                            JobModel.state == "QUEUED",
                            and_(
                                JobModel.state.in_(("RUNNING", "RETRY_WAIT")),
                                or_(JobModel.lease_until.is_(None), JobModel.lease_until <= now),
                            ),
                        ),
                    )
                    .order_by(CatalogExportModel.created_at)
                    .with_for_update(of=JobModel, skip_locked=True)
                    .limit(1)
                )
            ).one_or_none()
            if row is None:
                return None
            export, job = row
            subject = await _current_subject(session, export)
            access = await ClassificationAccessResolver(
                SqlClassificationAccessSnapshotReader(session)
            ).resolve(
                workspace_id=export.workspace_id,
                subject_id=export.requested_by,
                now=now,
            )
            snapshot_valid = await _snapshot_is_current(
                session=session,
                export=export,
                subject=subject,
                access_hash=catalog_classification_access_hash(access),
                now=now,
            )
            job.attempts += 1
            job.state = "RUNNING"
            job.lease_until = now + timedelta(seconds=lease_seconds)
            job.last_error_code = None
            job.updated_at = now
            job.version += 1
            attempt = JobAttemptModel(
                id=uuid7(),
                workspace_id=export.workspace_id,
                job_id=job.id,
                attempt_no=job.attempts,
                worker_id=worker_id,
                state="RUNNING",
                error_class=None,
                external_response_hash=None,
                started_at=now,
                finished_at=None,
            )
            session.add(attempt)
            _append_system_decision(
                session=session,
                export=export,
                system_actor_id=system_actor_id,
                action="system.catalog.export.claim",
                request_id=str(job.id),
                reason="SCOPED_EXPORT_WORKER_CLAIM",
            )
            await session.flush()
            return CatalogExportClaim(
                export=_to_record(export, job),
                attempt_id=attempt.id,
                attempt_no=attempt.attempt_no,
                subject=subject,
                access=access,
                snapshot_valid=snapshot_valid,
            )

    async def read_page(
        self,
        *,
        claim: CatalogExportClaim,
        cursor: str | None,
        limit: int,
    ) -> CatalogPage:
        async with self._session_factory() as session, session.begin():
            await set_security_context(
                session,
                workspace_id=claim.export.workspace_id,
                subject_id=claim.export.requested_by,
            )
            if not await self._snapshot_is_current(session=session, claim=claim):
                raise ConflictError("The catalog export snapshot changed during generation.")
            page = await SqlCatalogIndexReader(session).export_page(
                subject=claim.subject,
                access=claim.access,
                query=claim.export.request.query,
                filters=claim.export.request.filters,
                cursor=cursor,
                limit=limit,
            )
            if not await self._snapshot_is_current(session=session, claim=claim):
                raise ConflictError("The catalog export snapshot changed during generation.")
            return page

    async def snapshot_is_current(self, *, claim: CatalogExportClaim) -> bool:
        async with self._session_factory() as session, session.begin():
            await set_security_context(
                session,
                workspace_id=claim.export.workspace_id,
                subject_id=claim.export.requested_by,
            )
            return await self._snapshot_is_current(session=session, claim=claim)

    async def mark_completed(
        self,
        *,
        claim: CatalogExportClaim,
        system_actor_id: UUID,
        bucket: str,
        object_key: str,
        artifact: CatalogExportArtifact,
        row_count: int,
    ) -> None:
        now = utc_now()
        async with self._session_factory() as session, session.begin():
            await set_security_context(
                session,
                workspace_id=claim.export.workspace_id,
                subject_id=system_actor_id,
            )
            export, job, attempt = await _locked_claim_rows(session, claim)
            if export is None or job is None or attempt is None:
                raise ConflictError("The catalog export claim no longer exists.")
            if not _claim_can_complete(job=job, attempt=attempt, claim=claim, now=now):
                raise ConflictError("The catalog export claim lease was superseded.")
            if not await self._snapshot_is_current(session=session, claim=claim):
                raise ConflictError("The catalog export snapshot changed before completion.")
            export.object_bucket = bucket
            export.object_key = object_key
            export.row_count = row_count
            export.size_bytes = artifact.size_bytes
            export.content_sha256 = artifact.content_sha256
            export.provider_checksum = artifact.provider_checksum
            export.completed_at = now
            export.version += 1
            export.updated_at = now
            job.state = "COMPLETED"
            job.progress = {
                "row_count": row_count,
                "size_bytes": artifact.size_bytes,
                "content_sha256": artifact.content_sha256,
            }
            job.result_ref = f"catalog-export:{export.id}"
            job.lease_until = None
            job.last_error_code = None
            job.version += 1
            job.updated_at = now
            attempt.state = "COMPLETED"
            attempt.external_response_hash = artifact.content_sha256
            attempt.finished_at = now
            _append_system_decision(
                session=session,
                export=export,
                system_actor_id=system_actor_id,
                action="system.catalog.export.complete",
                request_id=str(job.id),
                reason="EXPORT_ARTIFACT_VERIFIED",
            )

    async def mark_failed(
        self,
        *,
        claim: CatalogExportClaim,
        system_actor_id: UUID,
        error_code: str,
        retryable: bool,
        maximum_attempts: int,
    ) -> None:
        now = utc_now()
        async with self._session_factory() as session, session.begin():
            await set_security_context(
                session,
                workspace_id=claim.export.workspace_id,
                subject_id=system_actor_id,
            )
            export, job, attempt = await _locked_claim_rows(session, claim)
            if export is None or job is None or attempt is None:
                return
            if not _claim_is_current(job=job, attempt=attempt, claim=claim):
                if attempt.state == "RUNNING":
                    attempt.state = "SUPERSEDED"
                    attempt.finished_at = now
                return
            attempt.state = "FAILED"
            attempt.error_class = error_code
            attempt.finished_at = now
            job.last_error_code = error_code
            job.version += 1
            job.updated_at = now
            if retryable and job.attempts < maximum_attempts:
                job.state = "RETRY_WAIT"
                job.lease_until = now + timedelta(seconds=min(2 ** min(job.attempts, 6), 60))
            else:
                job.state = "FAILED"
                job.lease_until = None
            _append_system_decision(
                session=session,
                export=export,
                system_actor_id=system_actor_id,
                action="system.catalog.export.fail",
                request_id=str(job.id),
                reason=error_code,
            )

    async def _snapshot_is_current(
        self, *, session: AsyncSession, claim: CatalogExportClaim
    ) -> bool:
        export = await session.get(CatalogExportModel, claim.export.export_id)
        if export is None:
            return False
        subject = await _current_subject(session, export)
        access = await ClassificationAccessResolver(
            SqlClassificationAccessSnapshotReader(session)
        ).resolve(
            workspace_id=export.workspace_id,
            subject_id=export.requested_by,
            now=utc_now(),
        )
        return await _snapshot_is_current(
            session=session,
            export=export,
            subject=subject,
            access_hash=catalog_classification_access_hash(access),
            now=utc_now(),
        )


async def _current_subject(session: AsyncSession, export: CatalogExportModel) -> SubjectAttributes:
    row = (
        await session.execute(
            select(SubjectModel, WorkspaceMembershipModel)
            .join(
                WorkspaceMembershipModel,
                and_(
                    WorkspaceMembershipModel.subject_id == SubjectModel.id,
                    WorkspaceMembershipModel.workspace_id == export.workspace_id,
                ),
            )
            .where(SubjectModel.id == export.requested_by)
        )
    ).one_or_none()
    if row is None:
        return SubjectAttributes(
            subject_id=export.requested_by,
            workspace_id=export.workspace_id,
            active=False,
            department_id=None,
            groups=frozenset(),
            job_function=None,
            clearance=Classification.PUBLIC,
        )
    try:
        return subject_attributes_from_models(subject=row[0], membership=row[1])
    except ForbiddenError:
        return SubjectAttributes(
            subject_id=export.requested_by,
            workspace_id=export.workspace_id,
            active=False,
            department_id=None,
            groups=frozenset(),
            job_function=None,
            clearance=Classification.PUBLIC,
        )


async def _snapshot_is_current(
    *,
    session: AsyncSession,
    export: CatalogExportModel,
    subject: SubjectAttributes,
    access_hash: str,
    now: datetime,
) -> bool:
    watermark = await session.scalar(
        select(CatalogProjectionWatermarkModel.projection_version).where(
            CatalogProjectionWatermarkModel.workspace_id == export.workspace_id
        )
    )
    return (
        export.access_until > now
        and subject.active
        and export.builtin_policy_version == BuiltinPolicyEngine.policy_version
        and export.csv_safety_version == CSV_SAFETY_VERSION
        and export.permission_scope_hash == catalog_permission_scope_hash(subject)
        and export.classification_access_hash == access_hash
        and export.source_projection_version == int(watermark or 0)
    )


async def _locked_claim_rows(
    session: AsyncSession, claim: CatalogExportClaim
) -> tuple[CatalogExportModel | None, JobModel | None, JobAttemptModel | None]:
    export = await session.get(CatalogExportModel, claim.export.export_id, with_for_update=True)
    job = await session.get(JobModel, claim.export.job_id, with_for_update=True)
    attempt = await session.get(JobAttemptModel, claim.attempt_id, with_for_update=True)
    return export, job, attempt


def _claim_is_current(
    *,
    job: JobModel,
    attempt: JobAttemptModel,
    claim: CatalogExportClaim,
) -> bool:
    return (
        job.id == claim.export.job_id
        and job.job_type == JOB_TYPE
        and job.state == "RUNNING"
        and job.attempts == claim.attempt_no
        and attempt.job_id == job.id
        and attempt.attempt_no == claim.attempt_no
        and attempt.state == "RUNNING"
    )


def _claim_can_complete(
    *,
    job: JobModel,
    attempt: JobAttemptModel,
    claim: CatalogExportClaim,
    now: datetime,
) -> bool:
    return (
        _claim_is_current(job=job, attempt=attempt, claim=claim)
        and job.lease_until is not None
        and job.lease_until > now
    )


def _append_system_decision(
    *,
    session: AsyncSession,
    export: CatalogExportModel,
    system_actor_id: UUID,
    action: str,
    request_id: str,
    reason: str,
) -> None:
    session.add(
        PolicyDecisionModel(
            id=uuid7(),
            workspace_id=export.workspace_id,
            subject_id=system_actor_id,
            resource_id=export.id,
            action=action,
            effect=Effect.ALLOW.value,
            reason_codes=[reason],
            policy_versions=[export.builtin_policy_version],
            evaluation_context={
                "kind": "catalog_export_worker",
                "workspace_id": str(export.workspace_id),
                "export_id": str(export.id),
                "request_hash": export.request_hash,
                "permission_scope_hash": export.permission_scope_hash,
                "classification_access_hash": export.classification_access_hash,
                "source_projection_version": export.source_projection_version,
            },
            request_id=request_id,
            decided_at=utc_now(),
        )
    )


def _to_record(model: CatalogExportModel, job: JobModel) -> CatalogExportRecord:
    request = _request_from_document(model.request_document)
    return CatalogExportRecord(
        export_id=model.id,
        workspace_id=model.workspace_id,
        job_id=model.job_id,
        requested_by=model.requested_by,
        request=request,
        request_hash=model.request_hash,
        permission_scope_hash=model.permission_scope_hash,
        classification_access_hash=model.classification_access_hash,
        builtin_policy_version=model.builtin_policy_version,
        classification_policy_id=model.classification_policy_id,
        classification_policy_hash=model.classification_policy_hash,
        classification_policy_version=model.classification_policy_version,
        authorization_generation=model.authorization_generation,
        source_projection_version=model.source_projection_version,
        classification_ceiling=Classification(model.classification_ceiling),
        csv_safety_version=model.csv_safety_version,
        display_name=model.display_name,
        mime=model.mime,
        job_state=job.state,
        last_error_code=job.last_error_code,
        row_count=model.row_count,
        size_bytes=model.size_bytes,
        content_sha256=model.content_sha256,
        provider_checksum=model.provider_checksum,
        object_bucket=model.object_bucket,
        object_key=model.object_key,
        created_at=model.created_at,
        completed_at=model.completed_at,
        access_until=model.access_until,
    )


def _request_from_document(document: dict[str, object]) -> CatalogExportRequest:
    try:
        filters_document = document["filters"]
        if not isinstance(filters_document, dict):
            raise TypeError
        filters = {
            str(key): str(value)
            for key, value in filters_document.items()
            if isinstance(key, str) and isinstance(value, str)
        }
        request = CatalogExportRequest(
            query=str(document["query"]),
            filters=filters,
            sort=str(document["sort"]),
            format=str(document["format"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ConflictError("The stored catalog export request is invalid.") from error
    if request.document() != document:
        raise ConflictError("The stored catalog export request failed canonical validation.")
    return request
