from __future__ import annotations

import hashlib
import re
from typing import Annotated, Literal
from uuid import UUID

import orjson
from fastapi import APIRouter, Header, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.change_numbers import change_request_number
from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.dto import (
    CatalogMetadataCandidatePage,
    UploadRegistrationCandidatePage,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.catalog_metadata_candidates import (
    CatalogMetadataCandidateQueryService,
)
from datariver.application.services.catalog_metadata_vocabulary import (
    CatalogMetadataVocabularyService,
)
from datariver.application.services.change_targets import CatalogChangeTargetAuthorizer
from datariver.application.services.governance import GovernanceService
from datariver.application.services.registration import RegistrationService
from datariver.application.services.registration_candidates import RegistrationCandidateQueryService
from datariver.application.services.registration_worker import (
    require_registration_operator_identity,
)
from datariver.application.services.typed_bulk_registration import (
    TypedBulkRegistrationService,
)
from datariver.application.services.typed_catalog_metadata_registration import (
    TypedCatalogMetadataRegistrationService,
)
from datariver.application.typed_upload_profiles import typed_profile_definition
from datariver.application.typed_upload_template import encode_typed_upload_template
from datariver.domain.authz import BuiltinPolicyEngine, Classification
from datariver.domain.common import (
    ConflictError,
    ForbiddenError,
    ValidationError,
    canonical_json_hash,
    uuid7,
)
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
from datariver.infrastructure.db.catalog_metadata import (
    SqlCatalogMetadataVocabularyProjection,
    SqlCatalogMetadataVocabularyResolver,
)
from datariver.infrastructure.db.classification_access import (
    SqlClassificationAccessSnapshotReader,
)
from datariver.infrastructure.db.governance import SqlGovernanceUnitOfWork
from datariver.infrastructure.db.registration import (
    SqlCatalogMetadataCandidateReader,
    SqlUploadCandidateReader,
    SqlUploadPreparationRepository,
    SqlUploadRepository,
    SqlUploadUnitOfWork,
)
from datariver.interfaces.http.dependencies import ContextDep, SessionDep, get_container
from datariver.interfaces.http.presenters import change_request_response
from datariver.interfaces.http.schemas import (
    CatalogMetadataCandidateListResponse,
    CatalogMetadataCandidateReceiptResponse,
    CatalogMetadataCandidateResponse,
    CatalogMetadataDescriptionChangeResponse,
    CatalogMetadataVocabularyItemResponse,
    CatalogMetadataVocabularyListResponse,
    CatalogMetadataVocabularySyncRequest,
    CatalogMetadataVocabularySyncResponse,
    ChangeRequestResponse,
    PageMeta,
    RegistrationOperatorCapabilityResponse,
    TypedBulkCandidatePreviewResponse,
    TypedBulkChangeRequestCreate,
    TypedCatalogMetadataChangeRequestResponse,
    TypedCatalogMetadataPreviewResponse,
    UploadCandidateCurrentTargetResponse,
    UploadCandidatePolicyMetaResponse,
    UploadCandidateReceiptResponse,
    UploadCandidateSubmittedIdentityResponse,
    UploadCompleteRequest,
    UploadInitiateRequest,
    UploadListResponse,
    UploadPartRequest,
    UploadPartResponse,
    UploadPreparationListResponse,
    UploadPreparationResponse,
    UploadRegistrationCandidateListResponse,
    UploadRegistrationCandidateResponse,
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


def _candidate_service(
    request: Request,
    session: AsyncSession,
) -> RegistrationCandidateQueryService:
    container = get_container(request)
    catalog = SqlCatalogIndexReader(session)
    return RegistrationCandidateQueryService(
        uploads=SqlUploadRepository(session),
        preparations=SqlUploadPreparationRepository(session),
        candidates=SqlUploadCandidateReader(session),
        catalog=catalog,
        watermark=catalog,
        classification_access=ClassificationAccessResolver(
            SqlClassificationAccessSnapshotReader(session)
        ),
        authorization=AuthorizationService(
            decision_writer=SqlDecisionWriter(container.database.session_factory)
        ),
        policy_version=BuiltinPolicyEngine.policy_version,
    )


def _typed_bulk_service(
    request: Request,
    session: AsyncSession,
) -> TypedBulkRegistrationService:
    return TypedBulkRegistrationService(
        candidates=_candidate_service(request, session),
        datahub=get_container(request).datahub,
        governance=_governance_service(request, session),
    )


def _catalog_metadata_candidate_service(
    request: Request,
    session: AsyncSession,
) -> CatalogMetadataCandidateQueryService:
    container = get_container(request)
    catalog = SqlCatalogIndexReader(session)
    return CatalogMetadataCandidateQueryService(
        uploads=SqlUploadRepository(session),
        preparations=SqlUploadPreparationRepository(session),
        candidates=SqlCatalogMetadataCandidateReader(session),
        catalog=catalog,
        watermark=catalog,
        classification_access=ClassificationAccessResolver(
            SqlClassificationAccessSnapshotReader(session)
        ),
        authorization=AuthorizationService(
            decision_writer=SqlDecisionWriter(container.database.session_factory)
        ),
        policy_version=BuiltinPolicyEngine.policy_version,
    )


def _typed_catalog_metadata_service(
    request: Request,
    session: AsyncSession,
) -> TypedCatalogMetadataRegistrationService:
    return TypedCatalogMetadataRegistrationService(
        candidates=_catalog_metadata_candidate_service(request, session),
        vocabulary=SqlCatalogMetadataVocabularyResolver(session),
        datahub=get_container(request).datahub,
        governance=_governance_service(request, session),
    )


def _catalog_metadata_vocabulary_service(
    request: Request,
    session: AsyncSession,
) -> CatalogMetadataVocabularyService:
    container = get_container(request)
    return CatalogMetadataVocabularyService(
        datahub=container.datahub,
        projection=SqlCatalogMetadataVocabularyProjection(session),
        authorization=AuthorizationService(
            decision_writer=SqlDecisionWriter(container.database.session_factory)
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


def _candidate_list_response(
    page: UploadRegistrationCandidatePage,
    *,
    limit: int,
) -> UploadRegistrationCandidateListResponse:
    receipt = page.receipt
    items: list[UploadRegistrationCandidateResponse] = []
    for value in page.items:
        candidate = value.evidence
        target = value.current_target
        submitted_values = (
            candidate.submitted_platform,
            candidate.submitted_database_name,
            candidate.submitted_schema_name,
            candidate.submitted_table_name,
            candidate.submitted_identity_hash,
        )
        if any(item is None for item in submitted_values):
            raise ConflictError("The upload preparation evidence is unavailable.")
        platform, database_name, schema_name, table_name, identity_hash = submitted_values
        assert isinstance(platform, str)
        assert isinstance(database_name, str)
        assert isinstance(schema_name, str)
        assert isinstance(table_name, str)
        assert isinstance(identity_hash, str)
        if target.platform is None or target.database_name is None or target.schema_name is None:
            raise ConflictError("The candidate target is unavailable.")
        items.append(
            UploadRegistrationCandidateResponse(
                id=candidate.candidate_id,
                ordinal=candidate.ordinal,
                evidence_version="DATASET_DESCRIPTION_CANDIDATE_V2",
                candidate_kind="DATASET_DESCRIPTION_UPDATE",
                proposed_description=candidate.proposed_description,
                submitted_identity=UploadCandidateSubmittedIdentityResponse(
                    platform=platform,
                    database_name=database_name,
                    schema_name=schema_name,
                    table_name=table_name,
                    identity_hash=identity_hash,
                ),
                candidate_hash=candidate.candidate_hash,
                created_at=candidate.created_at,
                current_target=UploadCandidateCurrentTargetResponse(
                    id=target.asset_id,
                    asset_type="DATASET",
                    name=target.name,
                    platform=target.platform,
                    database_name=target.database_name,
                    schema_name=target.schema_name,
                    classification=target.classification.name,
                    lifecycle="ACTIVE",
                    source_version=target.source_version,
                    observed_at=target.observed_at,
                ),
            )
        )
    return UploadRegistrationCandidateListResponse(
        items=items,
        page=PageMeta(next_cursor=page.next_cursor, limit=limit),
        receipt=UploadCandidateReceiptResponse(
            id=receipt.receipt_id,
            preparation_id=receipt.preparation_id,
            manifest_version=receipt.manifest_version,
            source_sha256=receipt.source_sha256,
            content_profile=receipt.content_profile,
            parser_version=receipt.parser_version,
            scanner_version=receipt.scanner_version,
            schema_version=receipt.schema_version,
            configuration_hash=receipt.configuration_hash,
            candidate_root_hash=receipt.candidate_root_hash,
            receipt_hash=receipt.receipt_hash,
            observed_at=receipt.observed_at,
            created_at=receipt.created_at,
        ),
        meta=UploadCandidatePolicyMetaResponse(
            projection_version=page.projection_version,
            policy_version=page.policy_version,
            classification_policy_version=page.classification_policy_version,
            authorization_generation=page.authorization_generation,
        ),
    )


def _catalog_metadata_candidate_list_response(
    page: CatalogMetadataCandidatePage,
    *,
    limit: int,
) -> CatalogMetadataCandidateListResponse:
    receipt = page.receipt
    items: list[CatalogMetadataCandidateResponse] = []
    for value in page.items:
        candidate = value.evidence
        target = value.current_target
        if target.platform is None or target.database_name is None or target.schema_name is None:
            raise ConflictError("The catalog metadata candidate target is unavailable.")
        field_paths = tuple(row.field_path for row in candidate.rows if row.field_path is not None)
        controlled_count = sum(row.controlled_ref_id is not None for row in candidate.rows)
        items.append(
            CatalogMetadataCandidateResponse(
                id=candidate.candidate_id,
                ordinal=candidate.ordinal,
                evidence_version="CATALOG_METADATA_CANDIDATE_V3",
                record_kind=candidate.record_kind,
                candidate_kind=candidate.candidate_kind,
                operation_count=len(candidate.rows),
                field_path_sample=list(field_paths[:20]),
                controlled_reference_count=controlled_count,
                row_summary_truncated=len(field_paths) > 20,
                submitted_identity=UploadCandidateSubmittedIdentityResponse(
                    platform=candidate.submitted_platform,
                    database_name=candidate.submitted_database_name,
                    schema_name=candidate.submitted_schema_name,
                    table_name=candidate.submitted_table_name,
                    identity_hash=candidate.submitted_identity_hash,
                ),
                candidate_hash=candidate.candidate_hash,
                created_at=candidate.created_at,
                current_target=UploadCandidateCurrentTargetResponse(
                    id=target.asset_id,
                    asset_type="DATASET",
                    name=target.name,
                    platform=target.platform,
                    database_name=target.database_name,
                    schema_name=target.schema_name,
                    classification=target.classification.name,
                    lifecycle="ACTIVE",
                    source_version=target.source_version,
                    observed_at=target.observed_at,
                ),
            )
        )
    return CatalogMetadataCandidateListResponse(
        items=items,
        page=PageMeta(next_cursor=page.next_cursor, limit=limit),
        receipt=CatalogMetadataCandidateReceiptResponse(
            id=receipt.receipt_id,
            preparation_id=receipt.preparation_id,
            manifest_version=receipt.manifest_version,
            source_sha256=receipt.source_sha256,
            content_profile=receipt.content_profile,
            parser_version=receipt.parser_version,
            scanner_version=receipt.scanner_version,
            schema_version=receipt.schema_version,
            configuration_hash=receipt.configuration_hash,
            item_count=receipt.item_count,
            candidate_count=receipt.candidate_count,
            candidate_root_hash=receipt.candidate_root_hash,
            receipt_hash=receipt.receipt_hash,
            observed_at=receipt.observed_at,
            created_at=receipt.created_at,
        ),
        meta=UploadCandidatePolicyMetaResponse(
            projection_version=page.projection_version,
            policy_version=page.policy_version,
            classification_policy_version=page.classification_policy_version,
            authorization_generation=page.authorization_generation,
        ),
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


@router.get(
    "/operator-capability",
    response_model=RegistrationOperatorCapabilityResponse,
)
async def get_registration_operator_capability(
    response: Response,
    context: ContextDep,
) -> RegistrationOperatorCapabilityResponse:
    try:
        require_registration_operator_identity(context.subject)
    except ForbiddenError:
        eligible = False
        reason_code = "ACTIVE_HUMAN_ADMIN_OR_DATA_STEWARD_REQUIRED"
    else:
        eligible = True
        reason_code = "ELIGIBLE"
    response.headers["Cache-Control"] = "private, no-store"
    return RegistrationOperatorCapabilityResponse(
        eligible=eligible,
        can_view_workspace_history=(
            eligible and "security-administrators" in context.subject.groups
        ),
        reason_code=reason_code,
        allowed_roles=("ADMIN", "DATA_STEWARD"),
    )


@router.get(
    "/profiles/{content_profile}/template",
    response_class=Response,
    responses={
        200: {
            "content": {
                "text/csv": {
                    "schema": {"type": "string", "format": "binary"},
                },
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {
                    "schema": {"type": "string", "format": "binary"},
                },
            },
            "description": "Server-versioned typed upload template.",
        }
    },
)
async def download_typed_upload_template(
    content_profile: Literal[
        "CATALOG_METADATA_ROWS_CSV_V1",
        "CATALOG_METADATA_ROWS_XLSX_V1",
    ],
    context: ContextDep,
) -> Response:
    require_registration_operator_identity(context.subject)
    definition = typed_profile_definition(UploadContentProfile(content_profile))
    content, filename = encode_typed_upload_template(definition)
    return Response(
        content=content,
        media_type=definition.content_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'attachment; filename="{filename}"',
            "ETag": f'"{definition.configuration_hash}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("", response_model=UploadListResponse)
async def list_uploads(
    request: Request,
    response: Response,
    context: ContextDep,
    state: Annotated[str | None, Query(max_length=32)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> UploadListResponse:
    require_registration_operator_identity(context.subject)
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
    response.headers["Cache-Control"] = "private, no-store"
    return UploadListResponse(items=[_response(value) for value in values])


@router.get(
    "/metadata-vocabulary",
    response_model=CatalogMetadataVocabularyListResponse,
)
async def list_catalog_metadata_vocabulary(
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    kind: Literal["DOMAIN", "TAG", "TERM"],
    q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    cursor: Annotated[str | None, Query(min_length=1, max_length=2_000)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> CatalogMetadataVocabularyListResponse:
    page = await _catalog_metadata_vocabulary_service(request, session).list_active(
        workspace_id=context.workspace_id,
        kind=kind,
        query=q,
        cursor=cursor,
        limit=limit,
        subject=context.subject,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return CatalogMetadataVocabularyListResponse(
        items=[
            CatalogMetadataVocabularyItemResponse(
                id=item.vocabulary_id,
                kind=item.kind,
                display_name=item.display_name,
                source_version=item.source_version,
            )
            for item in page.items
        ],
        page=PageMeta(next_cursor=page.next_cursor, limit=limit),
    )


@router.post(
    "/metadata-vocabulary/sync",
    response_model=CatalogMetadataVocabularySyncResponse,
)
async def sync_catalog_metadata_vocabulary(
    payload: CatalogMetadataVocabularySyncRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=16, max_length=200),
    ],
) -> CatalogMetadataVocabularySyncResponse:
    request_hash = hashlib.sha256(
        orjson.dumps(
            {
                **payload.model_dump(mode="json"),
                "operation": "catalog-metadata-vocabulary-sync.v1",
                "workspace_id": str(context.workspace_id),
            },
            option=orjson.OPT_SORT_KEYS,
        )
    ).hexdigest()
    result = await _catalog_metadata_vocabulary_service(request, session).sync_page(
        workspace_id=context.workspace_id,
        sync_id=payload.sync_id,
        kind=payload.kind,
        offset=payload.offset,
        limit=payload.limit,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return CatalogMetadataVocabularySyncResponse(
        kind=payload.kind,
        upserted=result.upserted,
        inactivated=result.inactivated,
        next_offset=result.next_offset,
        total=result.total,
        observed_at=result.observed_at,
        inactivation_status=result.inactivation_status,
    )


@router.get("/{upload_id}", response_model=UploadResponse)
async def get_upload(
    upload_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
) -> UploadResponse:
    require_registration_operator_identity(context.subject)
    manifest = await _service(request).get_manifest(
        workspace_id=context.workspace_id,
        upload_id=upload_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return _response(manifest)


@router.post("", status_code=201, response_model=UploadResponse)
async def initiate_upload(
    payload: UploadInitiateRequest,
    request: Request,
    context: ContextDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> UploadResponse:
    require_registration_operator_identity(context.subject)
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
    require_registration_operator_identity(context.subject)
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
    require_registration_operator_identity(context.subject)
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
    require_registration_operator_identity(context.subject)
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


@router.get(
    "/{upload_id}/preparations/{preparation_id}/candidates",
    response_model=UploadRegistrationCandidateListResponse,
)
async def list_upload_registration_candidates(
    upload_id: UUID,
    preparation_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> UploadRegistrationCandidateListResponse:
    require_registration_operator_identity(context.subject)
    page = await _candidate_service(request, session).list_candidates(
        workspace_id=context.workspace_id,
        upload_id=upload_id,
        preparation_id=preparation_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        cursor=cursor,
        limit=limit,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return _candidate_list_response(page, limit=limit)


@router.get(
    "/{upload_id}/preparations/{preparation_id}/candidates/{candidate_id}/preview",
    response_model=TypedBulkCandidatePreviewResponse,
)
async def preview_upload_registration_candidate(
    upload_id: UUID,
    preparation_id: UUID,
    candidate_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> TypedBulkCandidatePreviewResponse:
    require_registration_operator_identity(context.subject)
    preview = await _typed_bulk_service(request, session).preview(
        workspace_id=context.workspace_id,
        upload_id=upload_id,
        preparation_id=preparation_id,
        candidate_id=candidate_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["ETag"] = preview.preview_etag
    response.headers["Cache-Control"] = "private, no-store"
    return TypedBulkCandidatePreviewResponse(
        candidate_id=preview.candidate_id,
        target_asset_id=preview.target_asset_id,
        target_ref=preview.target_ref,
        platform=preview.platform,
        database_name=preview.database_name,
        schema_name=preview.schema_name,
        table_name=preview.table_name,
        current_description=preview.current_description,
        proposed_description=preview.proposed_description,
        before_hash=preview.before_hash,
        after_hash=preview.after_hash,
        source_version=preview.source_version,
        observed_at=preview.observed_at,
        preview_etag=preview.preview_etag,
    )


@router.post(
    "/{upload_id}/preparations/{preparation_id}/candidates/{candidate_id}/change-request",
    response_model=ChangeRequestResponse,
    status_code=201,
)
async def create_upload_registration_candidate_change_request(
    upload_id: UUID,
    preparation_id: UUID,
    candidate_id: UUID,
    payload: TypedBulkChangeRequestCreate,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    if_match: Annotated[str, Header(alias="If-Match", min_length=66, max_length=66)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> ChangeRequestResponse:
    require_registration_operator_identity(context.subject)
    if re.fullmatch(r'"[0-9a-f]{64}"', if_match) is None:
        raise ValidationError("If-Match must contain the quoted typed preview ETag.")
    request_hash = hashlib.sha256(
        orjson.dumps(
            {
                "candidate_id": str(candidate_id),
                "expected_preview_etag": if_match,
                "operation": "typed-bulk-candidate-change-request.v1",
                "preparation_id": str(preparation_id),
                "reason": payload.reason,
                "title": payload.title,
                "upload_id": str(upload_id),
                "workspace_id": str(context.workspace_id),
            },
            option=orjson.OPT_SORT_KEYS,
        )
    ).hexdigest()
    change_request = await _typed_bulk_service(request, session).create_change_request(
        workspace_id=context.workspace_id,
        upload_id=upload_id,
        preparation_id=preparation_id,
        candidate_id=candidate_id,
        expected_preview_etag=if_match,
        title=payload.title,
        reason=payload.reason,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return change_request_response(change_request)


@router.get(
    "/{upload_id}/preparations/{preparation_id}/metadata-candidates",
    response_model=CatalogMetadataCandidateListResponse,
)
async def list_catalog_metadata_candidates(
    upload_id: UUID,
    preparation_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> CatalogMetadataCandidateListResponse:
    require_registration_operator_identity(context.subject)
    page = await _catalog_metadata_candidate_service(request, session).list_candidates(
        workspace_id=context.workspace_id,
        upload_id=upload_id,
        preparation_id=preparation_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        cursor=cursor,
        limit=limit,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return _catalog_metadata_candidate_list_response(page, limit=limit)


@router.get(
    "/{upload_id}/preparations/{preparation_id}/metadata-candidates/{candidate_id}/preview",
    response_model=TypedCatalogMetadataPreviewResponse,
)
async def preview_catalog_metadata_candidate(
    upload_id: UUID,
    preparation_id: UUID,
    candidate_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> TypedCatalogMetadataPreviewResponse:
    require_registration_operator_identity(context.subject)
    preview = await _typed_catalog_metadata_service(request, session).preview(
        workspace_id=context.workspace_id,
        upload_id=upload_id,
        preparation_id=preparation_id,
        candidate_id=candidate_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["ETag"] = preview.preview_etag
    response.headers["Cache-Control"] = "private, no-store"
    return TypedCatalogMetadataPreviewResponse(
        candidate_id=preview.candidate_id,
        target_asset_id=preview.target_asset_id,
        platform=preview.platform,
        database_name=preview.database_name,
        schema_name=preview.schema_name,
        table_name=preview.table_name,
        record_kind=preview.record_kind,
        candidate_kind=preview.candidate_kind,
        operation_count=preview.operation_count,
        description_change_count=preview.description_change_count,
        description_change_sample=[
            CatalogMetadataDescriptionChangeResponse(
                field_path=field_path,
                current_description=current,
                proposed_description=proposed,
            )
            for field_path, current, proposed in preview.description_change_sample
        ],
        description_changes_truncated=preview.description_changes_truncated,
        current_reference_count=preview.current_reference_count,
        proposed_reference_count=preview.proposed_reference_count,
        before_hash=preview.before_hash,
        after_hash=preview.after_hash,
        source_version=preview.source_version,
        observed_at=preview.observed_at,
        preview_etag=preview.preview_etag,
    )


@router.post(
    "/{upload_id}/preparations/{preparation_id}/metadata-candidates/{candidate_id}/change-request",
    response_model=TypedCatalogMetadataChangeRequestResponse,
    status_code=201,
)
async def create_catalog_metadata_candidate_change_request(
    upload_id: UUID,
    preparation_id: UUID,
    candidate_id: UUID,
    payload: TypedBulkChangeRequestCreate,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    if_match: Annotated[str, Header(alias="If-Match", min_length=66, max_length=66)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> TypedCatalogMetadataChangeRequestResponse:
    require_registration_operator_identity(context.subject)
    if re.fullmatch(r'"[0-9a-f]{64}"', if_match) is None:
        raise ValidationError("If-Match must contain the quoted typed preview ETag.")
    request_hash = hashlib.sha256(
        orjson.dumps(
            {
                "candidate_id": str(candidate_id),
                "expected_preview_etag": if_match,
                "operation": "typed-catalog-metadata-change-request.v1",
                "preparation_id": str(preparation_id),
                "reason": payload.reason,
                "title": payload.title,
                "upload_id": str(upload_id),
                "workspace_id": str(context.workspace_id),
            },
            option=orjson.OPT_SORT_KEYS,
        )
    ).hexdigest()
    change_request = await _typed_catalog_metadata_service(request, session).create_change_request(
        workspace_id=context.workspace_id,
        upload_id=upload_id,
        preparation_id=preparation_id,
        candidate_id=candidate_id,
        expected_preview_etag=if_match,
        title=payload.title,
        reason=payload.reason,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return TypedCatalogMetadataChangeRequestResponse(
        id=change_request.change_request_id,
        number=change_request.number,
        request_type="BULK_CATALOG_METADATA",
        state=change_request.state.value,
    )


@router.post("/{upload_id}/parts", response_model=UploadPartResponse)
async def presign_part(
    upload_id: UUID,
    payload: UploadPartRequest,
    request: Request,
    context: ContextDep,
) -> UploadPartResponse:
    require_registration_operator_identity(context.subject)
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
    require_registration_operator_identity(context.subject)
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
    require_registration_operator_identity(context.subject)
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
        number=change_request_number(None),
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
