from __future__ import annotations

import hashlib
from typing import Annotated
from uuid import UUID

import orjson
from fastapi import APIRouter, Header, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.bulk_registration import BulkRegistrationPreparationService
from datariver.application.services.manual_metadata import ManualMetadataSubmissionService
from datariver.application.services.manual_metadata_apply import ManualMetadataApplyService
from datariver.application.services.manual_metadata_reports import ManualMetadataReportService
from datariver.application.services.registration_worker import (
    require_registration_operator_identity,
    require_registration_worker_identity,
)
from datariver.domain.authz import Action, Classification, ResourceAttributes
from datariver.domain.manual_metadata import ManualColumnMetadata, ManualMetadataSubmission
from datariver.domain.registration_worker import RegistrationWorkerCallIdentity
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.bulk_registration import SqlBulkPreparationExecutionStore
from datariver.infrastructure.db.catalog import SqlCatalogIndexReader
from datariver.infrastructure.db.classification_access import (
    SqlClassificationAccessSnapshotReader,
)
from datariver.infrastructure.db.governance import SqlGovernanceUnitOfWork
from datariver.infrastructure.db.manual_metadata_apply import SqlManualMetadataApplyEligibility
from datariver.infrastructure.db.provider_mutation import SqlProviderMutationLock
from datariver.interfaces.http.dependencies import ContextDep, SessionDep, get_container
from datariver.interfaces.http.schemas import (
    BulkPreparationExecuteResponse,
    ManualMetadataApplyAttemptResponse,
    ManualMetadataApplyResponse,
    ManualMetadataAspectReportResponse,
    ManualMetadataSubmissionListResponse,
    ManualMetadataSubmissionReportResponse,
    ManualMetadataSubmissionRequest,
    ManualMetadataSubmissionResponse,
    ManualMetadataSubmissionStatusResponse,
    PageMeta,
)

router = APIRouter(prefix="/registration", tags=["registration"])


def _service(request: Request, session: AsyncSession) -> ManualMetadataSubmissionService:
    container = get_container(request)
    return ManualMetadataSubmissionService(
        index=SqlCatalogIndexReader(session),
        classification_access=ClassificationAccessResolver(
            SqlClassificationAccessSnapshotReader(session)
        ),
        authorization=AuthorizationService(
            decision_writer=SqlDecisionWriter(container.database.session_factory)
        ),
        datahub=container.datahub,
        object_store=container.object_store,
        uow_factory=lambda: SqlGovernanceUnitOfWork(container.database.session_factory),
        infoschema_bucket=container.settings.s3_bucket_infoschema,
    )


def _apply_service(request: Request) -> ManualMetadataApplyService:
    container = get_container(request)
    return ManualMetadataApplyService(
        datahub=container.datahub,
        object_store=container.object_store,
        uow_factory=lambda: SqlGovernanceUnitOfWork(container.database.session_factory),
        eligibility=SqlManualMetadataApplyEligibility(container.database.session_factory),
        provider_mutation_lock=SqlProviderMutationLock(container.database.provider_lock_engine),
        lease_seconds=container.settings.governance_apply_lease_seconds,
        maximum_attempts=container.settings.governance_apply_maximum_attempts,
    )


def _bulk_preparation_service(request: Request) -> BulkRegistrationPreparationService:
    container = get_container(request)
    return BulkRegistrationPreparationService(
        store=SqlBulkPreparationExecutionStore(container.database.session_factory),
        object_store=container.object_store,
        lease_seconds=container.settings.bulk_preparation_lease_seconds,
        maximum_attempts=container.settings.bulk_preparation_maximum_attempts,
    )


def _report_service(request: Request) -> ManualMetadataReportService:
    container = get_container(request)
    return ManualMetadataReportService(
        authorization=AuthorizationService(
            decision_writer=SqlDecisionWriter(container.database.session_factory)
        ),
        uow_factory=lambda: SqlGovernanceUnitOfWork(container.database.session_factory),
    )


def _response(submission: ManualMetadataSubmission) -> ManualMetadataSubmissionResponse:
    return ManualMetadataSubmissionResponse(
        id=submission.submission_id,
        state=submission.state.value,
        serial_number=submission.serial_number,
        row_count=submission.row_count,
        source_version=submission.source_version,
        provider_source_version=submission.provider_source_version,
        created_at=submission.created_at,
        version=submission.version,
    )


def _status_response(
    submission: ManualMetadataSubmission,
) -> ManualMetadataSubmissionStatusResponse:
    return ManualMetadataSubmissionStatusResponse(
        **_response(submission).model_dump(),
        updated_at=submission.updated_at,
        applied_at=submission.applied_at,
        attempts=submission.attempts,
        next_attempt_at=submission.next_attempt_at,
        last_error_code=submission.last_error_code,
    )


def _manual_submission_request_hash(payload: ManualMetadataSubmissionRequest) -> str:
    if payload.columns is not None:
        # Preserve the exact pre-sparse-edit request identity so a successful legacy submission
        # remains replayable across a rolling deployment.
        document: dict[str, object] = {
            "operation": "registration.manual-metadata.submit.v1",
            "asset_id": str(payload.asset_id),
            "source_version": payload.source_version,
            "description": payload.description,
            "domain": payload.domain,
            "tags": payload.tags,
            "terms": payload.terms,
            "columns": [item.model_dump(mode="json") for item in payload.columns],
        }
    else:
        document = {
            "operation": "registration.manual-metadata.submit.v2",
            "asset_id": str(payload.asset_id),
            "source_version": payload.source_version,
            "provider_source_version": payload.provider_source_version,
            "description": payload.description,
            "domain": payload.domain,
            "tags": payload.tags,
            "terms": payload.terms,
            "column_edits": [
                item.model_dump(mode="json")
                for item in sorted(payload.column_edits or (), key=lambda item: item.field_path)
            ],
        }
    return hashlib.sha256(orjson.dumps(document, option=orjson.OPT_SORT_KEYS)).hexdigest()


@router.get(
    "/manual-submissions",
    response_model=ManualMetadataSubmissionListResponse,
)
async def list_manual_metadata_submissions(
    request: Request,
    response: Response,
    context: ContextDep,
    scope: Annotated[str, Query(pattern="^(mine|workspace)$")] = "mine",
    state: Annotated[str | None, Query(pattern="^(QUEUED|APPLYING|APPLIED|FAILED)$")] = None,
    cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> ManualMetadataSubmissionListResponse:
    require_registration_operator_identity(context.subject)
    page = await _report_service(request).list(
        workspace_id=context.workspace_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        scope=scope,
        state=state,
        cursor=cursor,
        limit=limit,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return ManualMetadataSubmissionListResponse(
        items=[_status_response(item) for item in page.items],
        page=PageMeta(next_cursor=page.next_cursor, limit=limit),
    )


@router.get(
    "/manual-submissions/{submission_id}",
    response_model=ManualMetadataSubmissionReportResponse,
)
async def get_manual_metadata_submission_report(
    submission_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
) -> ManualMetadataSubmissionReportResponse:
    require_registration_operator_identity(context.subject)
    report = await _report_service(request).get(
        workspace_id=context.workspace_id,
        submission_id=submission_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return ManualMetadataSubmissionReportResponse(
        submission=_status_response(report.submission),
        attempts=[
            ManualMetadataApplyAttemptResponse(
                id=attempt.attempt_id,
                attempt_no=attempt.attempt_no,
                lease_epoch=attempt.lease_epoch,
                state=attempt.state,
                failure_code=attempt.failure_code,
                report_root_hash=attempt.report_root_hash,
                started_at=attempt.started_at,
                finished_at=attempt.finished_at,
                aspects=[
                    ManualMetadataAspectReportResponse(
                        aspect_name=aspect.aspect_name,
                        aspect_ordinal=aspect.aspect_ordinal,
                        outcome=aspect.outcome,
                        before_hash=aspect.before_hash,
                        expected_hash=aspect.expected_hash,
                        observed_hash=aspect.observed_hash,
                        write_attempted=aspect.write_attempted,
                        failure_code=aspect.failure_code,
                        provider_version=aspect.provider_version,
                        provider_response_hash=aspect.provider_response_hash,
                        observed_at=aspect.observed_at,
                    )
                    for aspect in attempt.aspects
                ],
            )
            for attempt in report.attempts
        ],
    )


@router.post(
    "/manual-submissions",
    response_model=ManualMetadataSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_manual_metadata(
    payload: ManualMetadataSubmissionRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> ManualMetadataSubmissionResponse:
    require_registration_operator_identity(context.subject)
    request_hash = _manual_submission_request_hash(payload)
    submission = await _service(request, session).submit(
        asset_id=payload.asset_id,
        source_version=payload.source_version,
        provider_source_version=payload.provider_source_version,
        description=payload.description,
        domain=payload.domain,
        tags=tuple(payload.tags),
        terms=tuple(payload.terms),
        columns=tuple(
            ManualColumnMetadata(
                field_path=item.field_path,
                description=item.description,
                tags=tuple(item.tags),
                terms=tuple(item.terms),
            )
            for item in (
                payload.column_edits if payload.column_edits is not None else payload.columns or ()
            )
        ),
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return _response(submission)


@router.post(
    "/manual-submissions/apply",
    response_model=ManualMetadataApplyResponse,
)
async def apply_one_manual_metadata_submission(
    request: Request,
    response: Response,
    context: ContextDep,
    run_id: Annotated[str, Header(alias="X-Run-Id", min_length=1, max_length=200)],
    run_call: Annotated[int, Header(alias="X-Run-Call", ge=1, le=10)],
) -> ManualMetadataApplyResponse:
    """Airflow-only bounded apply entry point."""
    require_registration_worker_identity(context.subject)
    container = get_container(request)
    await AuthorizationService(
        decision_writer=SqlDecisionWriter(container.database.session_factory)
    ).authorize(
        subject=context.subject,
        resource=ResourceAttributes(
            resource_id=context.workspace_id,
            workspace_id=context.workspace_id,
            resource_type="manual_metadata_apply",
            owner_department_id=None,
            system_id=None,
            domain_id=None,
            classification=Classification.RESTRICTED,
            lifecycle="ACTIVE",
        ),
        action=Action.CATALOG_SYNC,
        environment=context.environment,
        request_id=context.request_id,
    )
    operation = "registration.manual-metadata.apply-run.v1"
    request_hash = hashlib.sha256(
        f"{context.workspace_id}:{run_id}:{run_call}:{operation}".encode()
    ).hexdigest()
    result = await _apply_service(request).run_once(
        workspace_id=context.workspace_id,
        worker_subject_id=context.subject.subject_id,
        request_id=f"{context.request_id}:{run_id}:{run_call}",
        run_call=RegistrationWorkerCallIdentity(
            operation=operation,
            key_hash=hashlib.sha256(f"{run_id}:{run_call}".encode()).hexdigest(),
            request_hash=request_hash,
            worker_subject_id=context.subject.subject_id,
        ),
    )
    value = ManualMetadataApplyResponse(
        processed=result.processed,
        submission_id=result.submission_id,
        serial_number=result.serial_number,
        state=result.state,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return value


@router.post(
    "/bulk-preparations/execute",
    response_model=BulkPreparationExecuteResponse,
)
async def execute_one_bulk_preparation(
    request: Request,
    response: Response,
    context: ContextDep,
    run_id: Annotated[str, Header(alias="X-Run-Id", min_length=1, max_length=200)],
    run_call: Annotated[int, Header(alias="X-Run-Call", ge=1, le=8)],
) -> BulkPreparationExecuteResponse:
    """Airflow-only preparation boundary; no provider or object-store secret leaves DataRiver."""
    require_registration_worker_identity(context.subject)
    container = get_container(request)
    await AuthorizationService(
        decision_writer=SqlDecisionWriter(container.database.session_factory)
    ).authorize(
        subject=context.subject,
        resource=ResourceAttributes(
            resource_id=context.workspace_id,
            workspace_id=context.workspace_id,
            resource_type="bulk_registration_preparation",
            owner_department_id=None,
            system_id=None,
            domain_id=None,
            classification=Classification.RESTRICTED,
            lifecycle="ACTIVE",
        ),
        action=Action.CATALOG_SYNC,
        environment=context.environment,
        request_id=context.request_id,
    )
    operation = "registration.bulk-preparation.execute-run.v1"
    request_hash = hashlib.sha256(
        f"{context.workspace_id}:{run_id}:{run_call}:{operation}".encode()
    ).hexdigest()
    result = await _bulk_preparation_service(request).run_once(
        workspace_id=context.workspace_id,
        worker_subject_id=context.subject.subject_id,
        run_call=RegistrationWorkerCallIdentity(
            operation=operation,
            key_hash=hashlib.sha256(f"{run_id}:{run_call}".encode()).hexdigest(),
            request_hash=request_hash,
            worker_subject_id=context.subject.subject_id,
        ),
    )
    value = BulkPreparationExecuteResponse(
        processed=result.processed,
        preparation_id=result.preparation_id,
        state=result.state,
        item_count=result.item_count,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return value
