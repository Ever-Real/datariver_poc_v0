from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response, status

from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.dto import (
    KnowledgeStudioBindingRecord,
    KnowledgeStudioDraftRecord,
    KnowledgeStudioIngestionJobRecord,
    KnowledgeStudioReleaseRecord,
    KnowledgeStudioSourceDataset,
    KnowledgeStudioTBoxElementRecord,
    KnowledgeStudioTBoxProposalRecord,
    KnowledgeStudioTBoxRecord,
    KnowledgeStudioValidationEvidence,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.catalog import CatalogService
from datariver.application.services.knowledge_studio import KnowledgeStudioService
from datariver.application.services.knowledge_studio_catalog import (
    CatalogKnowledgeStudioSourceReader,
)
from datariver.application.services.knowledge_studio_preview import (
    KnowledgeStudioPreviewService,
)
from datariver.domain.authz import BuiltinPolicyEngine, Classification
from datariver.domain.common import ConflictError, ValidationError, canonical_json_hash
from datariver.domain.knowledge_studio import (
    TBoxElementInput,
    TBoxElementKind,
    TBoxMergeStrategy,
    TBoxOperationInput,
    TBoxOperationKind,
    TBoxProposalMode,
)
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.catalog import SqlCatalogIndexReader
from datariver.infrastructure.db.classification_access import (
    SqlClassificationAccessSnapshotReader,
)
from datariver.infrastructure.db.knowledge_studio import SqlKnowledgeStudioStore
from datariver.infrastructure.knowledge.runtime import (
    build_knowledge_runtime_adapters,
    resolve_knowledge_runtime_bindings,
)
from datariver.interfaces.http.dependencies import ContextDep, SessionDep, get_container
from datariver.interfaces.http.schemas import (
    KnowledgeStudioABoxResponse,
    KnowledgeStudioAdvanceRequest,
    KnowledgeStudioBasicInformationRequest,
    KnowledgeStudioBindingMutationResponse,
    KnowledgeStudioBindingRequest,
    KnowledgeStudioBindingResponse,
    KnowledgeStudioDomainOptionResponse,
    KnowledgeStudioDomainOptionsResponse,
    KnowledgeStudioDraftResponse,
    KnowledgeStudioIngestionJobListResponse,
    KnowledgeStudioIngestionJobResponse,
    KnowledgeStudioMappingRuleResponse,
    KnowledgeStudioPreflightResponse,
    KnowledgeStudioPreviewEdgeResponse,
    KnowledgeStudioPreviewGraphResponse,
    KnowledgeStudioPreviewNodeResponse,
    KnowledgeStudioPreviewRequest,
    KnowledgeStudioPreviewResponse,
    KnowledgeStudioPublishRequest,
    KnowledgeStudioPublishResponse,
    KnowledgeStudioReleaseResponse,
    KnowledgeStudioSourceDatasetResponse,
    KnowledgeStudioSourceDetailResponse,
    KnowledgeStudioSourcePageResponse,
    KnowledgeStudioTBoxBlockCreateRequest,
    KnowledgeStudioTBoxBlockResponse,
    KnowledgeStudioTBoxBlockUpdateRequest,
    KnowledgeStudioTBoxElementRequest,
    KnowledgeStudioTBoxElementResponse,
    KnowledgeStudioTBoxOperationsRequest,
    KnowledgeStudioTBoxProposalApplyRequest,
    KnowledgeStudioTBoxProposalConflictResponse,
    KnowledgeStudioTBoxProposalRequest,
    KnowledgeStudioTBoxProposalResponse,
    KnowledgeStudioTBoxResponse,
    KnowledgeStudioValidationEvidenceResponse,
    PageMeta,
)

router = APIRouter(prefix="/knowledge/studio", tags=["knowledge-studio"])
domains_router = APIRouter(prefix="/knowledge", tags=["knowledge-studio"])
ETAG_RESPONSE = {
    "description": "Knowledge Studio Draft",
    "headers": {"ETag": {"schema": {"type": "string"}}},
}

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=8, max_length=200),
]
IfMatch = Annotated[
    str,
    Header(alias="If-Match", min_length=3, max_length=22),
]


def _service_components(
    request: Request,
    session: SessionDep,
) -> tuple[
    SqlKnowledgeStudioStore,
    AuthorizationService,
    CatalogKnowledgeStudioSourceReader,
]:
    container = get_container(request)
    authorization = AuthorizationService(
        decision_writer=SqlDecisionWriter(container.database.session_factory)
    )
    index = SqlCatalogIndexReader(session)
    catalog = CatalogService(
        index=index,
        discovery=index,
        watermark=index,
        datahub=container.datahub,
        cache=container.cache,
        authorization=authorization,
        detail_cache_ttl_seconds=container.settings.cache_default_ttl_seconds,
        stale_detail_ttl_seconds=container.settings.datahub_stale_ttl_seconds,
        search_cache_ttl_seconds=container.settings.catalog_search_cache_ttl_seconds,
        minimum_query_length=container.settings.catalog_search_minimum_query_length,
        policy_version=BuiltinPolicyEngine.policy_version,
        classification_access=ClassificationAccessResolver(
            SqlClassificationAccessSnapshotReader(session)
        ),
        telemetry=container.metrics,
        candidate_targets=index,
    )
    return (
        SqlKnowledgeStudioStore(session),
        authorization,
        CatalogKnowledgeStudioSourceReader(catalog),
    )


def _service(request: Request, session: SessionDep) -> KnowledgeStudioService:
    store, authorization, sources = _service_components(request, session)
    return KnowledgeStudioService(
        store=store,
        authorization=authorization,
        sources=sources,
    )


def _runtime_service(request: Request, session: SessionDep) -> KnowledgeStudioService:
    store, authorization, sources = _service_components(request, session)
    runtime = build_knowledge_runtime_adapters(get_container(request).settings)
    return KnowledgeStudioService(
        store=store,
        authorization=authorization,
        sources=sources,
        schema_assistant=runtime.schema_assistant,
        schema_binding=runtime.bindings.schema_assistant,
        embedding_binding=runtime.bindings.embedding,
    )


def _ingestion_service(request: Request, session: SessionDep) -> KnowledgeStudioService:
    store, authorization, sources = _service_components(request, session)
    try:
        embedding_binding = resolve_knowledge_runtime_bindings(
            get_container(request).settings
        ).embedding
    except ConflictError:
        embedding_binding = None
    return KnowledgeStudioService(
        store=store,
        authorization=authorization,
        sources=sources,
        embedding_binding=embedding_binding,
    )


def _preview_service(
    request: Request,
    session: SessionDep,
) -> KnowledgeStudioPreviewService:
    container = get_container(request)
    store, authorization, sources = _service_components(request, session)
    return KnowledgeStudioPreviewService(
        store=store,
        authorization=authorization,
        sources=sources,
        samples=container.knowledge_studio_samples,
    )


def _expected_version(if_match: str) -> int:
    if len(if_match) < 3 or if_match[0] != '"' or if_match[-1] != '"':
        raise ValidationError('If-Match must be a quoted positive integer such as "3".')
    value = if_match[1:-1]
    if not value or any(character < "0" or character > "9" for character in value):
        raise ValidationError('If-Match must be a quoted positive integer such as "3".')
    version = int(value)
    if version < 1 or str(version) != value:
        raise ValidationError('If-Match must be a quoted positive integer such as "3".')
    return version


def _draft_response(record: KnowledgeStudioDraftRecord) -> KnowledgeStudioDraftResponse:
    return KnowledgeStudioDraftResponse(
        id=record.draft_id,
        author_id=record.author_id,
        kind=record.kind,
        state=record.state,
        current_step=record.current_step,
        name=record.name,
        endpoint_alias=record.endpoint_alias,
        domain_id=record.domain_id,
        domain_source_version=record.domain_source_version,
        classification=record.classification.name,
        last_autosaved_at=record.last_autosaved_at,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
        submitted_preflight_check_id=record.submitted_preflight_check_id,
        reviewed_by=record.reviewed_by,
        reviewed_at=record.reviewed_at,
        review_reason=record.review_reason,
        published_by=record.published_by,
        published_at=record.published_at,
        materialized_graph_id=record.materialized_graph_id,
        materialized_ontology_version_id=record.materialized_ontology_version_id,
        published_studio_release_id=record.published_studio_release_id,
    )


def _studio_release_response(
    record: KnowledgeStudioReleaseRecord,
) -> KnowledgeStudioReleaseResponse:
    return KnowledgeStudioReleaseResponse(
        id=record.studio_release_id,
        graph_id=record.graph_id,
        ontology_version_id=record.ontology_version_id,
        release_no=record.release_no,
        state=record.state,
        contract_version=record.contract_version,
        contract_hash=record.contract_hash,
        tbox_hash=record.tbox_hash,
        abox_hash=record.abox_hash,
        supersedes_studio_release_id=record.supersedes_studio_release_id,
        reviewed_by=record.reviewed_by,
        published_by=record.published_by,
        published_at=record.published_at,
        archived_studio_release_id=record.archived_studio_release_id,
    )


def _set_draft_headers(response: Response, record: KnowledgeStudioDraftRecord) -> None:
    response.headers["ETag"] = f'"{record.version}"'
    response.headers["Cache-Control"] = "no-store"


def _set_version_headers(response: Response, version: int) -> None:
    response.headers["ETag"] = f'"{version}"'
    response.headers["Cache-Control"] = "no-store"


def _source_response(
    source: KnowledgeStudioSourceDataset,
) -> KnowledgeStudioSourceDatasetResponse:
    return KnowledgeStudioSourceDatasetResponse(
        id=source.asset_id,
        name=source.name,
        asset_type=source.asset_type,
        platform=source.platform,
        database_name=source.database_name,
        schema_name=source.schema_name,
        classification=source.classification.name,
        source_version=source.source_version,
        projection_source_version=source.projection_source_version,
        field_paths=list(source.field_paths),
        fields_truncated=source.fields_truncated,
    )


def _binding_response(
    binding: KnowledgeStudioBindingRecord,
) -> KnowledgeStudioBindingResponse:
    return KnowledgeStudioBindingResponse(
        id=binding.binding_id,
        target_stable_element_id=binding.target_stable_element_id,
        source_reference_id=binding.source_reference_id,
        source_asset_id=binding.source_asset_id,
        source_name=binding.source_name,
        source_version=binding.source_version,
        projection_source_version=binding.projection_source_version,
        source_classification=binding.source_classification.name,
        readiness=binding.readiness,
        tbox_version=binding.tbox_version,
        version=binding.version,
        rules=[
            KnowledgeStudioMappingRuleResponse(
                id=rule.rule_id,
                ordinal=rule.ordinal,
                method=rule.method,
                source_field_path=rule.source_field_path,
                target_stable_element_id=rule.target_stable_element_id,
                transform_id=rule.transform_id,
                transform_version=rule.transform_version,
                source_unit=rule.source_unit,
                canonical_unit=rule.canonical_unit,
            )
            for rule in binding.rules
        ],
        created_at=binding.created_at,
        updated_at=binding.updated_at,
    )


def _tbox_element_response(
    item: KnowledgeStudioTBoxElementRecord,
) -> KnowledgeStudioTBoxElementResponse:
    return KnowledgeStudioTBoxElementResponse(
        stable_element_id=item.stable_element_id,
        kind=item.kind,
        canonical_name=item.canonical_name,
        display_name=item.display_name,
        parent_stable_element_id=item.parent_stable_element_id,
        source_stable_element_id=item.source_stable_element_id,
        target_stable_element_id=item.target_stable_element_id,
        data_type=item.data_type,
        nullable=item.nullable,
        ordinal=item.ordinal,
        version=item.version,
        block_id=item.block_id,
        definition=item.definition,
        aliases=list(item.aliases),
        unit=item.unit,
        vector_index_enabled=item.vector_index_enabled,
        layout_x=item.layout_x,
        layout_y=item.layout_y,
    )


def _tbox_response(record: KnowledgeStudioTBoxRecord) -> KnowledgeStudioTBoxResponse:
    return KnowledgeStudioTBoxResponse(
        draft=_draft_response(record.draft),
        blocks=[
            KnowledgeStudioTBoxBlockResponse(
                id=block.block_id,
                kind=block.kind,
                title=block.title,
                weight=block.weight,
                ordinal=block.ordinal,
                collapsed=block.collapsed,
                version=block.version,
                source_reference=block.source_reference,
                elements=[_tbox_element_response(item) for item in block.elements],
                created_at=block.created_at,
                updated_at=block.updated_at,
            )
            for block in record.blocks
        ],
    )


def _tbox_element_input(
    value: KnowledgeStudioTBoxElementRequest,
) -> TBoxElementInput:
    return TBoxElementInput(
        stable_element_id=value.stable_element_id,
        kind=TBoxElementKind(value.kind),
        canonical_name=value.canonical_name,
        display_name=value.display_name,
        parent_stable_element_id=value.parent_stable_element_id,
        source_stable_element_id=value.source_stable_element_id,
        target_stable_element_id=value.target_stable_element_id,
        data_type=value.data_type,
        nullable=value.nullable,
        definition=value.definition,
        aliases=tuple(value.aliases),
        unit=value.unit,
        vector_index_enabled=value.vector_index_enabled,
        layout_x=value.layout_x,
        layout_y=value.layout_y,
    )


def _proposal_response(
    record: KnowledgeStudioTBoxProposalRecord,
) -> KnowledgeStudioTBoxProposalResponse:
    return KnowledgeStudioTBoxProposalResponse(
        id=record.proposal_id,
        draft_id=record.draft_id,
        target_block_id=record.target_block_id,
        state=record.state,
        mode=record.mode,
        merge_strategy=record.merge_strategy,
        base_draft_version=record.base_draft_version,
        prompt=record.prompt,
        elements=[_tbox_element_response(item) for item in record.elements],
        conflicts=[
            KnowledgeStudioTBoxProposalConflictResponse(
                conflict_id=item.conflict_id,
                kind=item.kind,
                stable_element_id=item.stable_element_id,
                field=item.field,
                original_value=item.original_value,
                proposed_value=item.proposed_value,
            )
            for item in record.conflicts
        ],
        model_binding=record.model_binding,
        error_code=record.error_code,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
        applied_at=record.applied_at,
        rejected_at=record.rejected_at,
    )


def _ingestion_response(
    record: KnowledgeStudioIngestionJobRecord,
) -> KnowledgeStudioIngestionJobResponse:
    return KnowledgeStudioIngestionJobResponse(
        id=record.job_id,
        draft_id=record.draft_id,
        requested_by=record.requested_by,
        state=record.state,
        progress_percent=record.progress_percent,
        current_stage=record.current_stage,
        vector_target_count=record.vector_target_count,
        result=record.result,
        error_code=record.error_code,
        error_message=record.error_message,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
    )


def _evidence_response(
    item: KnowledgeStudioValidationEvidence,
) -> KnowledgeStudioValidationEvidenceResponse:
    return KnowledgeStudioValidationEvidenceResponse(
        severity=item.severity,
        code=item.code,
        location=item.location,
        message=item.message,
    )


@domains_router.get(
    "/domains",
    response_model=KnowledgeStudioDomainOptionsResponse,
    operation_id="list_knowledge_domains",
)
@router.get(
    "/domains",
    response_model=KnowledgeStudioDomainOptionsResponse,
    operation_id="list_knowledge_studio_domains_compatibility",
)
async def list_knowledge_studio_domains(
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    classification: Annotated[
        Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"],
        Query(),
    ] = "INTERNAL",
    q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> KnowledgeStudioDomainOptionsResponse:
    response.headers["Cache-Control"] = "no-store"
    values = await _service(request, session).list_domains(
        workspace_id=context.workspace_id,
        subject=context.subject,
        classification=Classification[classification],
        query=q,
        limit=limit,
        environment=context.environment,
        request_id=context.request_id,
    )
    return KnowledgeStudioDomainOptionsResponse(
        items=[
            KnowledgeStudioDomainOptionResponse(
                id=value.domain_id,
                display_name=value.display_name,
                source_version=value.source_version,
            )
            for value in values
        ]
    )


@router.post(
    "/drafts",
    response_model=KnowledgeStudioDraftResponse,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_201_CREATED: ETAG_RESPONSE},
)
async def create_knowledge_studio_draft(
    payload: KnowledgeStudioBasicInformationRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
) -> KnowledgeStudioDraftResponse:
    request_hash = canonical_json_hash(payload.model_dump(mode="json"))
    record = await _service(request, session).create_draft(
        workspace_id=context.workspace_id,
        subject=context.subject,
        name=payload.name,
        endpoint_alias=payload.endpoint_alias,
        domain_id=payload.domain_id,
        domain_source_version=payload.domain_source_version,
        classification=Classification[payload.classification],
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, record)
    return _draft_response(record)


@router.post(
    "/drafts/from-asset/{asset_id}",
    response_model=KnowledgeStudioDraftResponse,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_201_CREATED: ETAG_RESPONSE},
)
async def create_knowledge_studio_edit_draft(
    asset_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
) -> KnowledgeStudioDraftResponse:
    request_hash = canonical_json_hash(
        {
            "contract": "KNOWLEDGE_STUDIO_EDIT_DRAFT_V1",
            "asset_id": str(asset_id),
        }
    )
    record = await _service(request, session).create_edit_draft(
        workspace_id=context.workspace_id,
        subject=context.subject,
        graph_id=asset_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, record)
    return _draft_response(record)


@router.get(
    "/drafts/resumable",
    response_model=KnowledgeStudioDraftResponse,
    responses={status.HTTP_200_OK: ETAG_RESPONSE},
)
async def get_resumable_knowledge_studio_draft(
    endpoint_alias: Annotated[str, Query(min_length=3, max_length=100)],
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> KnowledgeStudioDraftResponse:
    record = await _service(request, session).get_resumable_draft(
        workspace_id=context.workspace_id,
        subject=context.subject,
        endpoint_alias=endpoint_alias,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, record)
    return _draft_response(record)


@router.get(
    "/drafts/{draft_id}",
    response_model=KnowledgeStudioDraftResponse,
    responses={status.HTTP_200_OK: ETAG_RESPONSE},
)
async def get_knowledge_studio_draft(
    draft_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> KnowledgeStudioDraftResponse:
    record = await _service(request, session).get_draft(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, record)
    return _draft_response(record)


@router.get(
    "/drafts/{draft_id}/tbox",
    response_model=KnowledgeStudioTBoxResponse,
    responses={status.HTTP_200_OK: ETAG_RESPONSE},
)
async def get_knowledge_studio_tbox(
    draft_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> KnowledgeStudioTBoxResponse:
    record = await _service(request, session).get_tbox(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, record.draft)
    return _tbox_response(record)


@router.post(
    "/drafts/{draft_id}/tbox/blocks",
    response_model=KnowledgeStudioTBoxResponse,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_201_CREATED: ETAG_RESPONSE},
)
async def create_knowledge_studio_tbox_block(
    draft_id: UUID,
    payload: KnowledgeStudioTBoxBlockCreateRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgeStudioTBoxResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "payload": payload.model_dump(mode="json"),
            "expected_version": expected_version,
        }
    )
    record = await _service(request, session).create_tbox_block(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        kind=payload.kind,
        title=payload.title,
        weight=payload.weight,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, record.draft)
    return _tbox_response(record)


@router.post(
    "/drafts/{draft_id}/tbox/proposals",
    response_model=KnowledgeStudioTBoxProposalResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_knowledge_studio_tbox_proposal(
    draft_id: UUID,
    payload: KnowledgeStudioTBoxProposalRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    if_match: IfMatch,
) -> KnowledgeStudioTBoxProposalResponse:
    expected_version = _expected_version(if_match)
    record = await _runtime_service(request, session).create_tbox_proposal(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        target_block_id=payload.target_block_id,
        mode=TBoxProposalMode(payload.mode),
        prompt=payload.prompt,
        expected_version=expected_version,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["Cache-Control"] = "no-store"
    return _proposal_response(record)


@router.get(
    "/drafts/{draft_id}/tbox/proposals/{proposal_id}",
    response_model=KnowledgeStudioTBoxProposalResponse,
)
async def get_knowledge_studio_tbox_proposal(
    draft_id: UUID,
    proposal_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> KnowledgeStudioTBoxProposalResponse:
    record = await _service(request, session).get_tbox_proposal(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        proposal_id=proposal_id,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["Cache-Control"] = "no-store"
    return _proposal_response(record)


@router.post(
    "/drafts/{draft_id}/tbox/proposals/{proposal_id}/apply",
    response_model=KnowledgeStudioTBoxResponse,
    responses={status.HTTP_200_OK: ETAG_RESPONSE},
)
async def apply_knowledge_studio_tbox_proposal(
    draft_id: UUID,
    proposal_id: UUID,
    payload: KnowledgeStudioTBoxProposalApplyRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgeStudioTBoxResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "proposal_id": str(proposal_id),
            "payload": payload.model_dump(mode="json"),
            "expected_version": expected_version,
        }
    )
    record = await _service(request, session).apply_tbox_proposal(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        proposal_id=proposal_id,
        merge_strategy=TBoxMergeStrategy(payload.merge_strategy),
        resolutions=tuple(
            {
                key: value
                for key, value in item.model_dump(mode="json", exclude_none=True).items()
                if isinstance(value, str)
            }
            for item in payload.resolutions
        ),
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, record.draft)
    return _tbox_response(record)


@router.patch(
    "/drafts/{draft_id}/tbox/blocks/{block_id}",
    response_model=KnowledgeStudioTBoxResponse,
    responses={status.HTTP_200_OK: ETAG_RESPONSE},
)
async def update_knowledge_studio_tbox_block(
    draft_id: UUID,
    block_id: UUID,
    payload: KnowledgeStudioTBoxBlockUpdateRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgeStudioTBoxResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "block_id": str(block_id),
            "payload": payload.model_dump(mode="json"),
            "expected_version": expected_version,
        }
    )
    record = await _service(request, session).update_tbox_block(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        block_id=block_id,
        title=payload.title,
        weight=payload.weight,
        collapsed=payload.collapsed,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, record.draft)
    return _tbox_response(record)


@router.post(
    "/drafts/{draft_id}/tbox/blocks/{block_id}/operations",
    response_model=KnowledgeStudioTBoxResponse,
    responses={status.HTTP_200_OK: ETAG_RESPONSE},
)
async def apply_knowledge_studio_tbox_operations(
    draft_id: UUID,
    block_id: UUID,
    payload: KnowledgeStudioTBoxOperationsRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgeStudioTBoxResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "block_id": str(block_id),
            "payload": payload.model_dump(mode="json"),
            "expected_version": expected_version,
        }
    )
    operations = tuple(
        TBoxOperationInput(
            operation=TBoxOperationKind(item.operation),
            stable_element_id=item.stable_element_id,
            element=_tbox_element_input(item.element) if item.element is not None else None,
            layout_x=item.layout_x,
            layout_y=item.layout_y,
        )
        for item in payload.operations
    )
    record = await _service(request, session).apply_tbox_operations(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        block_id=block_id,
        operations=operations,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, record.draft)
    return _tbox_response(record)


@router.patch(
    "/drafts/{draft_id}",
    response_model=KnowledgeStudioDraftResponse,
    responses={
        status.HTTP_200_OK: ETAG_RESPONSE,
        status.HTTP_412_PRECONDITION_FAILED: {
            "description": "The If-Match Draft version is stale."
        },
    },
)
async def autosave_knowledge_studio_draft(
    draft_id: UUID,
    payload: KnowledgeStudioBasicInformationRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgeStudioDraftResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "payload": payload.model_dump(mode="json"),
            "expected_version": expected_version,
        }
    )
    record = await _service(request, session).autosave_draft(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        name=payload.name,
        endpoint_alias=payload.endpoint_alias,
        domain_id=payload.domain_id,
        domain_source_version=payload.domain_source_version,
        classification=Classification[payload.classification],
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, record)
    return _draft_response(record)


@router.post(
    "/drafts/{draft_id}/advance",
    response_model=KnowledgeStudioDraftResponse,
    responses={
        status.HTTP_200_OK: ETAG_RESPONSE,
        status.HTTP_412_PRECONDITION_FAILED: {
            "description": "The If-Match Draft version is stale."
        },
    },
)
async def advance_knowledge_studio_draft(
    draft_id: UUID,
    payload: KnowledgeStudioAdvanceRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgeStudioDraftResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "target_step": payload.target_step,
            "expected_version": expected_version,
        }
    )
    service = _service(request, session)
    if payload.target_step == "TBOX":
        record = await service.advance_to_tbox(
            workspace_id=context.workspace_id,
            subject=context.subject,
            draft_id=draft_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            environment=context.environment,
            request_id=context.request_id,
        )
    else:
        record = await service.advance_to_abox(
            workspace_id=context.workspace_id,
            subject=context.subject,
            draft_id=draft_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            environment=context.environment,
            request_id=context.request_id,
        )
    _set_draft_headers(response, record)
    return _draft_response(record)


@router.post(
    "/drafts/{draft_id}/submit-review",
    response_model=KnowledgeStudioDraftResponse,
    responses={
        status.HTTP_200_OK: ETAG_RESPONSE,
        status.HTTP_412_PRECONDITION_FAILED: {
            "description": "The If-Match Draft version is stale."
        },
    },
)
async def submit_knowledge_studio_review(
    draft_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgeStudioDraftResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "draft_id": str(draft_id),
            "expected_version": expected_version,
        }
    )
    record = await _service(request, session).submit_review(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, record)
    return _draft_response(record)


@router.post(
    "/drafts/{draft_id}/discard",
    response_model=KnowledgeStudioDraftResponse,
    responses={
        status.HTTP_200_OK: ETAG_RESPONSE,
        status.HTTP_412_PRECONDITION_FAILED: {
            "description": "The If-Match Draft version is stale."
        },
    },
)
async def discard_knowledge_studio_draft(
    draft_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgeStudioDraftResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "draft_id": str(draft_id),
            "expected_version": expected_version,
        }
    )
    record = await _service(request, session).discard_draft(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, record)
    return _draft_response(record)


@router.post(
    "/drafts/{draft_id}/publish",
    response_model=KnowledgeStudioPublishResponse,
    responses={
        status.HTTP_200_OK: ETAG_RESPONSE,
        status.HTTP_412_PRECONDITION_FAILED: {
            "description": "The If-Match Draft version is stale."
        },
    },
)
async def publish_knowledge_studio_draft(
    draft_id: UUID,
    payload: KnowledgeStudioPublishRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgeStudioPublishResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "draft_id": str(draft_id),
            "expected_version": expected_version,
            "payload": payload.model_dump(mode="json"),
        }
    )
    draft, studio_release = await _service(request, session).publish_draft(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        review_reason=payload.review_reason,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, draft)
    return KnowledgeStudioPublishResponse(
        draft=_draft_response(draft),
        release=_studio_release_response(studio_release),
    )


@router.get(
    "/drafts/{draft_id}/abox",
    response_model=KnowledgeStudioABoxResponse,
    responses={status.HTTP_200_OK: ETAG_RESPONSE},
)
async def get_knowledge_studio_abox(
    draft_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> KnowledgeStudioABoxResponse:
    record = await _service(request, session).get_abox(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, record.draft)
    return KnowledgeStudioABoxResponse(
        draft=_draft_response(record.draft),
        tbox_elements=[_tbox_element_response(item) for item in record.tbox_elements],
        bindings=[_binding_response(item) for item in record.bindings],
    )


@router.post(
    "/drafts/{draft_id}/abox/ingestions",
    response_model=KnowledgeStudioIngestionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_knowledge_studio_ingestion_job(
    draft_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgeStudioIngestionJobResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "contract": "KNOWLEDGE_STUDIO_INGESTION_REQUEST_V1",
            "draft_id": str(draft_id),
            "expected_version": expected_version,
        }
    )
    record = await _ingestion_service(request, session).create_ingestion_job(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["Cache-Control"] = "no-store"
    return _ingestion_response(record)


@router.get(
    "/drafts/{draft_id}/abox/ingestions",
    response_model=KnowledgeStudioIngestionJobListResponse,
)
async def list_knowledge_studio_ingestion_jobs(
    draft_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> KnowledgeStudioIngestionJobListResponse:
    records = await _service(request, session).list_ingestion_jobs(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        limit=limit,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["Cache-Control"] = "no-store"
    return KnowledgeStudioIngestionJobListResponse(
        items=[_ingestion_response(record) for record in records]
    )


@router.get(
    "/drafts/{draft_id}/abox/ingestions/{job_id}",
    response_model=KnowledgeStudioIngestionJobResponse,
)
async def get_knowledge_studio_ingestion_job(
    draft_id: UUID,
    job_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> KnowledgeStudioIngestionJobResponse:
    record = await _service(request, session).get_ingestion_job(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        job_id=job_id,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["Cache-Control"] = "no-store"
    return _ingestion_response(record)


@router.get(
    "/drafts/{draft_id}/abox/sources",
    response_model=KnowledgeStudioSourcePageResponse,
)
async def list_knowledge_studio_abox_sources(
    draft_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    q: Annotated[str, Query(max_length=200)] = "",
    cursor: Annotated[str | None, Query(max_length=2_000)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> KnowledgeStudioSourcePageResponse:
    response.headers["Cache-Control"] = "no-store"
    page = await _service(request, session).search_abox_sources(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        query=q,
        cursor=cursor,
        limit=limit,
        environment=context.environment,
        request_id=context.request_id,
    )
    return KnowledgeStudioSourcePageResponse(
        items=[_source_response(item) for item in page.items],
        page=PageMeta(next_cursor=page.next_cursor, limit=limit),
    )


@router.get(
    "/drafts/{draft_id}/abox/sources/{asset_id}",
    response_model=KnowledgeStudioSourceDetailResponse,
)
async def get_knowledge_studio_abox_source(
    draft_id: UUID,
    asset_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> KnowledgeStudioSourceDetailResponse:
    response.headers["Cache-Control"] = "no-store"
    source = await _service(request, session).get_abox_source(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        asset_id=asset_id,
        environment=context.environment,
        request_id=context.request_id,
    )
    return KnowledgeStudioSourceDetailResponse(
        dataset=_source_response(source.dataset),
        observed_at=source.observed_at,
        stale_at=source.stale_at,
    )


@router.patch(
    "/drafts/{draft_id}/abox/bindings/{target_stable_element_id}",
    response_model=KnowledgeStudioBindingMutationResponse,
    responses={
        status.HTTP_200_OK: ETAG_RESPONSE,
        status.HTTP_412_PRECONDITION_FAILED: {
            "description": "The If-Match Draft version is stale."
        },
    },
)
async def patch_knowledge_studio_abox_binding(
    draft_id: UUID,
    target_stable_element_id: str,
    payload: KnowledgeStudioBindingRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgeStudioBindingMutationResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "target_stable_element_id": target_stable_element_id,
            "payload": payload.model_dump(mode="json"),
            "expected_version": expected_version,
        }
    )
    draft, binding = await _service(request, session).save_abox_binding(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        target_stable_element_id=target_stable_element_id,
        source_asset_id=payload.source_asset_id,
        source_version=payload.source_version,
        projection_source_version=payload.projection_source_version,
        rules=tuple(
            (
                rule.method,
                rule.source_field_path,
                rule.target_stable_element_id,
            )
            for rule in payload.rules
        ),
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_draft_headers(response, draft)
    return KnowledgeStudioBindingMutationResponse(
        draft=_draft_response(draft),
        binding=_binding_response(binding),
    )


@router.post(
    "/drafts/{draft_id}/abox/previews",
    response_model=KnowledgeStudioPreviewResponse,
    responses={
        status.HTTP_200_OK: ETAG_RESPONSE,
        status.HTTP_412_PRECONDITION_FAILED: {
            "description": "The If-Match Draft version is stale."
        },
    },
)
async def preview_knowledge_studio_abox_binding(
    draft_id: UUID,
    payload: KnowledgeStudioPreviewRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    if_match: IfMatch,
) -> KnowledgeStudioPreviewResponse:
    record = await _preview_service(request, session).preview_binding(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        target_stable_element_id=payload.target_stable_element_id,
        sample_limit=payload.sample_limit,
        expected_version=_expected_version(if_match),
        environment=context.environment,
        request_id=context.request_id,
    )
    _set_version_headers(response, record.draft_version)
    return KnowledgeStudioPreviewResponse(
        status=record.status,
        draft_version=record.draft_version,
        binding_version=record.binding_version,
        target_stable_element_id=record.target_stable_element_id,
        dry_run=True,
        sample_size=record.sample_size,
        graph=KnowledgeStudioPreviewGraphResponse(
            nodes=[
                KnowledgeStudioPreviewNodeResponse(
                    id=item.node_id,
                    stable_element_id=item.stable_element_id,
                    type=item.type_name,
                    identity=item.identity,
                    properties=dict(item.properties),
                )
                for item in record.graph.nodes
            ],
            edges=[
                KnowledgeStudioPreviewEdgeResponse(
                    id=item.edge_id,
                    stable_element_id=item.stable_element_id,
                    type=item.type_name,
                    source_node_id=item.source_node_id,
                    target_node_id=item.target_node_id,
                    properties=dict(item.properties),
                )
                for item in record.graph.edges
            ],
        ),
        evidence=[_evidence_response(item) for item in record.evidence],
    )


@router.post(
    "/drafts/{draft_id}/abox/preflight",
    response_model=KnowledgeStudioPreflightResponse,
    responses={
        status.HTTP_200_OK: ETAG_RESPONSE,
        status.HTTP_412_PRECONDITION_FAILED: {
            "description": "The If-Match Draft version is stale."
        },
    },
)
async def preflight_knowledge_studio_abox(
    draft_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: IdempotencyKey,
    if_match: IfMatch,
) -> KnowledgeStudioPreflightResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "draft_id": str(draft_id),
            "expected_version": expected_version,
        }
    )
    record = await _preview_service(request, session).preflight(
        workspace_id=context.workspace_id,
        subject=context.subject,
        draft_id=draft_id,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    if record.receipt_id is None or record.contract_hash is None:
        raise ValidationError("The durable pre-flight receipt is unavailable.")
    _set_version_headers(response, record.draft_version)
    return KnowledgeStudioPreflightResponse(
        status=record.status,
        valid=record.valid,
        draft_version=record.draft_version,
        checked_at=record.checked_at,
        receipt_id=record.receipt_id,
        contract_hash=record.contract_hash,
        evidence=[_evidence_response(item) for item in record.evidence],
    )
