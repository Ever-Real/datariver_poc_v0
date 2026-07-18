from __future__ import annotations

import hashlib
from typing import Annotated

import orjson
from fastapi import APIRouter, Header, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.manual_metadata import ManualMetadataSubmissionService
from datariver.domain.manual_metadata import ManualColumnMetadata, ManualMetadataSubmission
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.catalog import SqlCatalogIndexReader
from datariver.infrastructure.db.classification_access import (
    SqlClassificationAccessSnapshotReader,
)
from datariver.infrastructure.db.governance import SqlGovernanceUnitOfWork
from datariver.interfaces.http.dependencies import ContextDep, SessionDep, get_container
from datariver.interfaces.http.schemas import (
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
