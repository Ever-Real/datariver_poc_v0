from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response, status

from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.dto import (
    KnowledgeStudioBindingRecord,
    KnowledgeStudioDraftRecord,
    KnowledgeStudioSourceDataset,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.catalog import CatalogService
from datariver.application.services.knowledge_studio import KnowledgeStudioService
from datariver.application.services.knowledge_studio_catalog import (
    CatalogKnowledgeStudioSourceReader,
)
from datariver.domain.authz import BuiltinPolicyEngine, Classification
from datariver.domain.common import ValidationError, canonical_json_hash
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.catalog import SqlCatalogIndexReader
from datariver.infrastructure.db.classification_access import (
    SqlClassificationAccessSnapshotReader,
)
from datariver.infrastructure.db.knowledge_studio import SqlKnowledgeStudioStore
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
    KnowledgeStudioMappingRuleResponse,
    KnowledgeStudioSourceDatasetResponse,
    KnowledgeStudioSourceDetailResponse,
    KnowledgeStudioSourcePageResponse,
    KnowledgeStudioTBoxElementResponse,
    PageMeta,
)

router = APIRouter(prefix="/knowledge/studio", tags=["knowledge-studio"])
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


def _service(request: Request, session: SessionDep) -> KnowledgeStudioService:
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
    )
    return KnowledgeStudioService(
        store=SqlKnowledgeStudioStore(session),
        authorization=authorization,
        sources=CatalogKnowledgeStudioSourceReader(catalog),
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
    )


def _set_draft_headers(response: Response, record: KnowledgeStudioDraftRecord) -> None:
    response.headers["ETag"] = f'"{record.version}"'
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


@router.get("/domains", response_model=KnowledgeStudioDomainOptionsResponse)
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
        tbox_elements=[
            KnowledgeStudioTBoxElementResponse(
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
            )
            for item in record.tbox_elements
        ],
        bindings=[_binding_response(item) for item in record.bindings],
    )


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
