from __future__ import annotations

import hashlib
from typing import Annotated

import orjson
from fastapi import APIRouter, Header, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.bulk_registration import BulkRegistrationPreparationService
from datariver.application.services.manual_metadata import ManualMetadataSubmissionService
from datariver.application.services.manual_metadata_apply import ManualMetadataApplyService
from datariver.domain.authz import Action, Classification, ResourceAttributes
from datariver.domain.manual_metadata import ManualColumnMetadata, ManualMetadataSubmission
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.bulk_registration import SqlBulkPreparationExecutionStore
from datariver.infrastructure.db.catalog import SqlCatalogIndexReader
from datariver.infrastructure.db.classification_access import (
    SqlClassificationAccessSnapshotReader,
)
from datariver.infrastructure.db.governance import SqlGovernanceUnitOfWork
from datariver.interfaces.http.dependencies import ContextDep, SessionDep, get_container
from datariver.interfaces.http.schemas import (
    BulkPreparationExecuteResponse,
    ManualMetadataApplyResponse,
    ManualMetadataSubmissionRequest,
    ManualMetadataSubmissionResponse,
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


def _response(submission: ManualMetadataSubmission) -> ManualMetadataSubmissionResponse:
    return ManualMetadataSubmissionResponse(
        id=submission.submission_id,
        state=submission.state.value,
        serial_number=submission.serial_number,
        row_count=submission.row_count,
        source_version=submission.source_version,
        created_at=submission.created_at,
        version=submission.version,
    )


@router.post(
    "/manual-submissions",
    response_model=ManualMetadataSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_manual_metadata(
    payload: ManualMetadataSubmissionRequest,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> ManualMetadataSubmissionResponse:
    request_hash = hashlib.sha256(
        orjson.dumps(
            {
                "operation": "registration.manual-metadata.submit.v1",
                "asset_id": str(payload.asset_id),
                "source_version": payload.source_version,
                "description": payload.description,
                "domain": payload.domain,
                "tags": payload.tags,
                "terms": payload.terms,
                "columns": [item.model_dump(mode="json") for item in payload.columns],
            },
            option=orjson.OPT_SORT_KEYS,
        )
    ).hexdigest()
    submission = await _service(request, session).submit(
        asset_id=payload.asset_id,
        source_version=payload.source_version,
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
            for item in payload.columns
        ),
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    return _response(submission)


@router.post(
    "/manual-submissions/apply",
    response_model=ManualMetadataApplyResponse,
)
async def apply_one_manual_metadata_submission(
    request: Request,
    context: ContextDep,
) -> ManualMetadataApplyResponse:
    """Airflow-only bounded apply entry point; ordinary registration users lack `catalog.sync`."""
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
    result = await _apply_service(request).run_once(
        workspace_id=context.workspace_id,
        worker_subject_id=context.subject.subject_id,
    )
    return ManualMetadataApplyResponse(
        processed=result.processed,
        submission_id=result.submission_id,
        serial_number=result.serial_number,
        state=result.state,
    )


@router.post(
    "/bulk-preparations/execute",
    response_model=BulkPreparationExecuteResponse,
)
async def execute_one_bulk_preparation(
    request: Request,
    context: ContextDep,
) -> BulkPreparationExecuteResponse:
    """Airflow-only preparation boundary; no provider or object-store secret leaves DataRiver."""
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
    result = await _bulk_preparation_service(request).run_once(
        workspace_id=context.workspace_id,
        worker_subject_id=context.subject.subject_id,
    )
    return BulkPreparationExecuteResponse(
        processed=result.processed,
        preparation_id=result.preparation_id,
        state=result.state,
        item_count=result.item_count,
    )
