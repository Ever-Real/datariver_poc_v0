from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

import orjson
from fastapi import APIRouter, Header, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.change_targets import CatalogChangeTargetAuthorizer
from datariver.application.services.governance import GovernanceService
from datariver.application.services.registration import RegistrationService
from datariver.domain.authz import Classification
from datariver.domain.common import ConflictError, ValidationError, canonical_json_hash, uuid7
from datariver.domain.governance import ChangeItem
from datariver.domain.registration import (
    CompletedUploadPart,
    UploadContentProfile,
    UploadManifest,
    UploadPreparation,
    UploadPreparationState,
    UploadState,
)
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.catalog import SqlCatalogIndexReader
from datariver.infrastructure.db.classification_access import (
    SqlClassificationAccessSnapshotReader,
)
from datariver.infrastructure.db.governance import SqlGovernanceUnitOfWork
from datariver.infrastructure.db.registration import SqlUploadUnitOfWork
from datariver.interfaces.http.dependencies import ContextDep, SessionDep, get_container
from datariver.interfaces.http.presenters import change_request_response
from datariver.interfaces.http.schemas import (
    ChangeRequestResponse,
    UploadCompleteRequest,
    UploadInitiateRequest,
    UploadListResponse,
    UploadPartRequest,
    UploadPartResponse,
    UploadPreparationListResponse,
    UploadPreparationResponse,
    UploadRegistrationProposal,
    UploadResponse,
)

router = APIRouter(prefix="/uploads", tags=["registration"])


def _service(request: Request) -> RegistrationService:
    container = get_container(request)
    return RegistrationService(
        uow_factory=lambda: SqlUploadUnitOfWork(container.database.session_factory),
        authorization=AuthorizationService(
            decision_writer=SqlDecisionWriter(container.database.session_factory)
        ),
        object_store=container.object_store,
        quarantine_bucket=container.settings.s3_bucket_quarantine,
        presign_ttl_seconds=container.settings.presigned_url_ttl_seconds,
    )


def _governance_service(request: Request, session: AsyncSession) -> GovernanceService:
    container = get_container(request)
    authorization = AuthorizationService(
        decision_writer=SqlDecisionWriter(container.database.session_factory)
    )
    return GovernanceService(
        lambda: SqlGovernanceUnitOfWork(container.database.session_factory),
        authorization,
        target_authorizer=CatalogChangeTargetAuthorizer(
            index=SqlCatalogIndexReader(session),
            classification_access=ClassificationAccessResolver(
                SqlClassificationAccessSnapshotReader(session)
            ),
            authorization=authorization,
        ),
    )


def _response(manifest: UploadManifest) -> UploadResponse:
    return UploadResponse(
        id=manifest.upload_id,
        display_name=manifest.display_name,
        state=manifest.state.value,
        size_bytes=manifest.declared_size_bytes,
        content_type=manifest.declared_mime,
        sha256=manifest.declared_sha256,
        classification=manifest.classification.name,
        content_profile=manifest.content_profile.value,
        expires_at=manifest.expires_at,
        version=manifest.version,
        validation_summary=manifest.validation_summary,
        last_error_code=manifest.last_error_code,
    )


def _preparation_response(preparation: UploadPreparation) -> UploadPreparationResponse:
    return UploadPreparationResponse(
        id=preparation.preparation_id,
        upload_id=preparation.upload_id,
        content_profile=preparation.content_profile.value,
        source_manifest_version=preparation.source_manifest_version,
        source_sha256=preparation.source_sha256,
        configuration_hash=preparation.configuration_hash,
        state=preparation.state.value,
        attempts=preparation.attempts,
        rows_processed=preparation.rows_processed,
        total_rows=preparation.total_rows,
        last_error_code=preparation.last_error_code,
        created_at=preparation.created_at,
        updated_at=preparation.updated_at,
        version=preparation.version,
    )


def _set_preparation_response_headers(
    response: Response,
    *,
    upload_id: UUID,
    preparation: UploadPreparation,
) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["ETag"] = f'"{preparation.version}"'
    response.headers["Location"] = (
        f"/api/v1/uploads/{upload_id}/preparations/{preparation.preparation_id}"
    )


def _expected_version(if_match: str) -> int:
    match = re.fullmatch(r'"([1-9][0-9]*)"', if_match.strip())
    if match is None:
        raise ValidationError("If-Match must contain a quoted positive aggregate version.")
    return int(match.group(1))


@router.get("", response_model=UploadListResponse)
async def list_uploads(
    request: Request,
    context: ContextDep,
    state: Annotated[str | None, Query(max_length=32)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> UploadListResponse:
    try:
        parsed_state = UploadState(state) if state else None
    except ValueError as error:
        raise ValidationError("The upload state filter is invalid.") from error
    values = await _service(request).list_manifests(
        workspace_id=context.workspace_id,
        state=parsed_state,
        limit=limit,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return UploadListResponse(items=[_response(value) for value in values])


@router.get("/{upload_id}", response_model=UploadResponse)
async def get_upload(
    upload_id: UUID,
    request: Request,
    context: ContextDep,
) -> UploadResponse:
    manifest = await _service(request).get_manifest(
        workspace_id=context.workspace_id,
        upload_id=upload_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return _response(manifest)


@router.post("", status_code=201, response_model=UploadResponse)
async def initiate_upload(
    payload: UploadInitiateRequest,
    request: Request,
    context: ContextDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> UploadResponse:
    request_hash = hashlib.sha256(
        orjson.dumps(payload.model_dump(mode="json"), option=orjson.OPT_SORT_KEYS)
    ).hexdigest()
    manifest = await _service(request).initiate(
        workspace_id=context.workspace_id,
        subject=context.subject,
        display_name=payload.display_name,
        declared_size_bytes=payload.size_bytes,
        declared_mime=payload.content_type,
        declared_sha256=payload.sha256,
        classification=Classification[payload.classification],
        content_profile=UploadContentProfile(payload.content_profile),
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    return _response(manifest)


@router.post(
    "/{upload_id}/preparations",
    status_code=202,
    response_model=UploadPreparationResponse,
)
async def create_upload_preparation(
    upload_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    if_match: Annotated[str, Header(alias="If-Match", min_length=3, max_length=100)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> UploadPreparationResponse:
    preparation = await _service(request).create_preparation(
        workspace_id=context.workspace_id,
        upload_id=upload_id,
        subject=context.subject,
        expected_manifest_version=_expected_version(if_match),
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
    )
    _set_preparation_response_headers(
        response,
        upload_id=upload_id,
        preparation=preparation,
    )
    return _preparation_response(preparation)


@router.get(
    "/{upload_id}/preparations",
    response_model=UploadPreparationListResponse,
)
async def list_upload_preparations(
    upload_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    state: Annotated[str | None, Query(max_length=32)] = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 20,
) -> UploadPreparationListResponse:
    try:
        parsed_state = UploadPreparationState(state) if state else None
    except ValueError as error:
        raise ValidationError("The upload preparation state filter is invalid.") from error
    values = await _service(request).list_preparations(
        workspace_id=context.workspace_id,
        upload_id=upload_id,
        state=parsed_state,
        limit=limit,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return UploadPreparationListResponse(items=[_preparation_response(value) for value in values])


@router.get(
    "/{upload_id}/preparations/{preparation_id}",
    response_model=UploadPreparationResponse,
)
async def get_upload_preparation(
    upload_id: UUID,
    preparation_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
) -> UploadPreparationResponse:
    preparation = await _service(request).get_preparation(
        workspace_id=context.workspace_id,
        upload_id=upload_id,
        preparation_id=preparation_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_preparation_response_headers(
        response,
        upload_id=upload_id,
        preparation=preparation,
    )
    return _preparation_response(preparation)


@router.post("/{upload_id}/parts", response_model=UploadPartResponse)
async def presign_part(
    upload_id: UUID,
    payload: UploadPartRequest,
    request: Request,
    context: ContextDep,
) -> UploadPartResponse:
    url, lifetime = await _service(request).presign_part(
        workspace_id=context.workspace_id,
        upload_id=upload_id,
        subject=context.subject,
        part_number=payload.part_number,
        checksum_sha256=payload.checksum_sha256,
        environment=context.environment,
        request_id=context.request_id,
    )
    return UploadPartResponse(part_number=payload.part_number, url=url, expires_in_seconds=lifetime)


@router.post("/{upload_id}/complete", status_code=202, response_model=UploadResponse)
async def complete_upload(
    upload_id: UUID,
    payload: UploadCompleteRequest,
    request: Request,
    context: ContextDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> UploadResponse:
    expected_version = _expected_version(if_match)
    request_hash = hashlib.sha256(
        orjson.dumps(
            {
                "upload_id": str(upload_id),
                "expected_version": expected_version,
                "parts": [part.model_dump(mode="json") for part in payload.parts],
            },
            option=orjson.OPT_SORT_KEYS,
        )
    ).hexdigest()
    manifest = await _service(request).queue_completion(
        workspace_id=context.workspace_id,
        upload_id=upload_id,
        subject=context.subject,
        parts=[
            CompletedUploadPart(
                part_number=part.part_number,
                etag=part.etag,
                checksum_sha256=part.checksum_sha256,
            )
            for part in payload.parts
        ],
        expected_version=expected_version,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    return _response(manifest)


@router.post(
    "/{upload_id}/registration-proposals",
    status_code=201,
    response_model=ChangeRequestResponse,
)
async def create_registration_proposal(
    upload_id: UUID,
    payload: UploadRegistrationProposal,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> ChangeRequestResponse:
    manifest = await _service(request).get_manifest(
        workspace_id=context.workspace_id,
        upload_id=upload_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if manifest.state is not UploadState.ACCEPTED:
        raise ConflictError("Only an accepted and validated upload can create a proposal.")
    after_hash = canonical_json_hash(payload.after_document)
    item = ChangeItem(
        item_id=uuid7(),
        target_type="DATAHUB_ASPECT",
        target_ref=payload.target_ref,
        operation="UPSERT",
        after_document=payload.after_document,
        aspect_name=payload.aspect_name,
        before_hash=payload.before_hash,
        after_hash=after_hash,
    )
    evidence = (
        f"Accepted upload {manifest.upload_id}; SHA-256 {manifest.declared_sha256}; "
        f"validation={orjson.dumps(manifest.validation_summary).decode('utf-8')}"
    )
    request_document = {
        "upload_id": str(upload_id),
        "upload_version": manifest.version,
        "target_ref": payload.target_ref,
        "aspect_name": payload.aspect_name,
        "before_hash": payload.before_hash,
        "after_hash": after_hash,
        "title": payload.title,
        "description": payload.description,
    }
    request_hash = hashlib.sha256(
        orjson.dumps(request_document, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()
    value = await _governance_service(request, session).create_change_request(
        workspace_id=context.workspace_id,
        number=f"CR-{datetime.now(UTC):%Y}-{uuid7().hex[:12].upper()}",
        request_type="DATA_REGISTRATION",
        title=payload.title,
        description=f"{payload.description}\n\n{evidence}".strip(),
        requester_id=context.subject.subject_id,
        items=[item],
        subject=context.subject,
        classification=manifest.classification,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        require_raw_operator_gate=True,
    )
    return change_request_response(value)
