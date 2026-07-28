from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response, status

from datariver.application.dto import KnowledgeStudioDraftRecord
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.knowledge_studio import KnowledgeStudioService
from datariver.domain.authz import Classification
from datariver.domain.common import ValidationError, canonical_json_hash
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.knowledge_studio import SqlKnowledgeStudioStore
from datariver.interfaces.http.dependencies import ContextDep, SessionDep, get_container
from datariver.interfaces.http.schemas import (
    KnowledgeStudioAdvanceRequest,
    KnowledgeStudioBasicInformationRequest,
    KnowledgeStudioDomainOptionResponse,
    KnowledgeStudioDomainOptionsResponse,
    KnowledgeStudioDraftResponse,
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
    return KnowledgeStudioService(
        store=SqlKnowledgeStudioStore(session),
        authorization=AuthorizationService(
            decision_writer=SqlDecisionWriter(container.database.session_factory)
        ),
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
    record = await _service(request, session).advance_to_tbox(
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
