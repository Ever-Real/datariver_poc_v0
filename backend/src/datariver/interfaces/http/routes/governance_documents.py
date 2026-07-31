from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import (
    APIRouter,
    File,
    Form,
    Header,
    Query,
    Request,
    Response,
    UploadFile,
)
from pydantic import ValidationError as PydanticValidationError
from starlette.datastructures import UploadFile as StarletteUploadFile

from datariver.application.governance_document_formats import (
    PreparedGovernanceDocumentContent,
    prepare_governance_document_html,
    prepare_governance_document_upload,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.governance_documents import GovernanceDocumentService
from datariver.domain.authz import Classification
from datariver.domain.common import PreconditionRequiredError, ValidationError
from datariver.domain.governance_documents import (
    MAXIMUM_ATTACHMENT_BYTES,
    MAXIMUM_ATTACHMENTS_PER_VERSION,
    MAXIMUM_SANITIZED_HTML_BYTES,
    GovernanceDocumentCategory,
    GovernanceDocumentKind,
    GovernanceDocumentReviewDecision,
)
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.governance_documents import (
    SqlGovernanceDocumentRepository,
)
from datariver.infrastructure.knowledge.runtime import build_knowledge_runtime_adapters
from datariver.interfaces.http.dependencies import ContextDep, SessionDep, get_container
from datariver.interfaces.http.governance_document_presenters import (
    governance_document_attachment_response,
    governance_document_detail_response,
    governance_document_summary_response,
    governance_knowledge_evidence_response,
)
from datariver.interfaces.http.governance_document_schemas import (
    GovernanceDocumentArchiveRequest,
    GovernanceDocumentAttachmentDownloadResponse,
    GovernanceDocumentAttachmentResponse,
    GovernanceDocumentBlueprintListResponse,
    GovernanceDocumentBlueprintResponse,
    GovernanceDocumentCapabilityAxisResponse,
    GovernanceDocumentCapabilityResponse,
    GovernanceDocumentCommandResponse,
    GovernanceDocumentCreateRequest,
    GovernanceDocumentDetailResponse,
    GovernanceDocumentLimitsResponse,
    GovernanceDocumentListResponse,
    GovernanceDocumentReviewRequest,
    GovernanceDocumentVersionCreateRequest,
    GovernanceKnowledgeEvidenceListResponse,
    GovernanceRagSearchRequest,
)
from datariver.interfaces.http.schemas import PageMeta

router = APIRouter(prefix="/governance/documents", tags=["governance-documents"])
rag_router = APIRouter(prefix="/governance/search", tags=["governance-documents"])

_MAXIMUM_IDEMPOTENCY_KEY_CHARACTERS = 200


def _service(
    request: Request,
    session: SessionDep,
    *,
    knowledge_search: bool = False,
) -> GovernanceDocumentService:
    container = get_container(request)
    attachment_store = container.governance_document_attachments
    knowledge_runtime = (
        build_knowledge_runtime_adapters(container.settings) if knowledge_search else None
    )
    return GovernanceDocumentService(
        repository=SqlGovernanceDocumentRepository(session),
        authorization=AuthorizationService(
            decision_writer=SqlDecisionWriter(container.database.session_factory),
            development_governance_password_bypass_enabled=(
                container.settings.development_admin_password_bypass_enabled
            ),
        ),
        attachment_store=attachment_store,
        artifact_storage_ready=(
            container.settings.governance_document_worker_enabled and attachment_store is not None
        ),
        knowledge_projection_ready=(
            container.settings.governance_document_worker_enabled
            and container.knowledge_neo4j is not None
        ),
        knowledge_embedding=(
            knowledge_runtime.embedding if knowledge_runtime is not None else None
        ),
        knowledge_embedding_binding=(
            knowledge_runtime.bindings.embedding if knowledge_runtime is not None else None
        ),
        attachment_download_ttl_seconds=container.settings.presigned_url_ttl_seconds,
    )


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization, X-Workspace-Id"


def _etag(response: Response, version: int) -> None:
    response.headers["ETag"] = f'"{version}"'


def _expected_version(if_match: str | None) -> int:
    if if_match is None:
        raise PreconditionRequiredError(
            "If-Match is required for this Governance Document command."
        )
    match = re.fullmatch(r'"([1-9][0-9]*)"', if_match.strip())
    if match is None:
        raise ValidationError("If-Match must contain a quoted positive version.")
    return int(match.group(1))


def _idempotency_key(value: str) -> str:
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > _MAXIMUM_IDEMPOTENCY_KEY_CHARACTERS
        or any(ord(character) < 33 or ord(character) > 126 for character in normalized)
    ):
        raise ValidationError("The Governance Document idempotency key is invalid.")
    return normalized


async def _bounded_upload(upload: StarletteUploadFile) -> bytes:
    try:
        value = await upload.read(MAXIMUM_ATTACHMENT_BYTES + 1)
    finally:
        await upload.close()
    if not 1 <= len(value) <= MAXIMUM_ATTACHMENT_BYTES:
        raise ValidationError("The Governance Document upload exceeds its bounded size.")
    return value


@router.get("/capability", response_model=GovernanceDocumentCapabilityResponse)
async def get_governance_document_capability(
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> GovernanceDocumentCapabilityResponse:
    _private(response)
    value = await _service(request, session).capability(
        subject=context.subject,
        environment=context.environment,
    )
    return GovernanceDocumentCapabilityResponse(
        observed_at=value.observed_at,
        valid_until=value.valid_until,
        cache_scope=value.cache_scope,
        axes=[
            GovernanceDocumentCapabilityAxisResponse(
                id=axis.id,
                state=axis.state,
                reason_code=axis.reason_code,
            )
            for axis in value.axes
        ],
        limits=GovernanceDocumentLimitsResponse(
            max_html_bytes=MAXIMUM_SANITIZED_HTML_BYTES,
            max_attachment_bytes=MAXIMUM_ATTACHMENT_BYTES,
            max_attachments_per_version=MAXIMUM_ATTACHMENTS_PER_VERSION,
        ),
    )


@router.post("/imports", response_model=GovernanceDocumentCommandResponse, status_code=201)
async def import_governance_document(
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    kind: Annotated[GovernanceDocumentKind, Form()],
    category: Annotated[GovernanceDocumentCategory, Form()],
    title: Annotated[str, Form(min_length=1, max_length=500)],
    summary: Annotated[str, Form(max_length=2_000)],
    classification: Annotated[int, Form(ge=0, le=3)],
    applicability_scope: Annotated[str, Form(max_length=4_000)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> GovernanceDocumentCommandResponse:
    _private(response)
    filename = file.filename
    content_type = file.content_type
    content = await _bounded_upload(file)
    prepared = prepare_governance_document_upload(
        filename=filename,
        content_type=content_type,
        content=content,
    )
    value = await _service(request, session).create_document(
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=_idempotency_key(idempotency_key),
        kind=kind,
        category=category,
        title=title,
        summary=summary,
        classification=Classification(classification),
        applicability_scope=applicability_scope,
        content=prepared,
        source_template_version_id=None,
    )
    _etag(response, value.document.version)
    return GovernanceDocumentCommandResponse(item=governance_document_detail_response(value))


@router.get(
    "/template-blueprints",
    response_model=GovernanceDocumentBlueprintListResponse,
)
async def list_governance_document_template_blueprints(
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> GovernanceDocumentBlueprintListResponse:
    _private(response)
    values = await _service(request, session).template_blueprints(
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return GovernanceDocumentBlueprintListResponse(
        items=[
            GovernanceDocumentBlueprintResponse(
                blueprint_id=value.blueprint_id,
                blueprint_version=value.blueprint_version,
                category=value.category.value,
                title=value.title,
                summary=value.summary,
                applicability_scope=value.applicability_scope,
                sanitized_html=value.sanitized_html,
                content_sha256=value.content_sha256,
                sanitizer_policy_version=value.sanitizer_policy_version,
                sanitizer_policy_sha256=value.sanitizer_policy_sha256,
            )
            for value in values
        ]
    )


@router.get(
    "/knowledge/evidence",
    response_model=GovernanceKnowledgeEvidenceListResponse,
)
async def search_governance_knowledge_evidence(
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    q: Annotated[str, Query(min_length=2, max_length=500)],
    limit: Annotated[int, Query(ge=1, le=20)] = 8,
) -> GovernanceKnowledgeEvidenceListResponse:
    _private(response)
    values, read_context = await _service(
        request,
        session,
        knowledge_search=True,
    ).search_knowledge(
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        query=q,
        limit=limit,
    )
    return GovernanceKnowledgeEvidenceListResponse(
        items=[governance_knowledge_evidence_response(value) for value in values],
        cache_scope=read_context.cache_scope,
        observed_at=read_context.observed_at,
        authorization_valid_until=read_context.authorization_valid_until,
    )


@rag_router.post("/rag", response_model=GovernanceKnowledgeEvidenceListResponse)
async def search_governance_rag(
    body: GovernanceRagSearchRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> GovernanceKnowledgeEvidenceListResponse:
    _private(response)
    values, read_context = await _service(
        request,
        session,
        knowledge_search=True,
    ).search_knowledge(
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        query=body.query,
        limit=body.limit,
    )
    return GovernanceKnowledgeEvidenceListResponse(
        items=[governance_knowledge_evidence_response(value) for value in values],
        cache_scope=read_context.cache_scope,
        observed_at=read_context.observed_at,
        authorization_valid_until=read_context.authorization_valid_until,
    )


@router.get("", response_model=GovernanceDocumentListResponse)
async def list_governance_documents(
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=2_000)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    kind: Annotated[GovernanceDocumentKind | None, Query()] = None,
    category: Annotated[GovernanceDocumentCategory | None, Query()] = None,
    include_archived: bool = False,
) -> GovernanceDocumentListResponse:
    _private(response)
    page, read_context = await _service(request, session).list_documents(
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        kind=kind,
        category=category,
        include_archived=include_archived,
        query=q,
        limit=limit,
        cursor=cursor,
    )
    return GovernanceDocumentListResponse(
        items=[governance_document_summary_response(value) for value in page.items],
        page=PageMeta(next_cursor=page.next_cursor, limit=limit),
        cache_scope=read_context.cache_scope,
        observed_at=read_context.observed_at,
        authorization_valid_until=read_context.authorization_valid_until,
    )


@router.post("", response_model=GovernanceDocumentCommandResponse, status_code=201)
async def create_governance_document(
    body: GovernanceDocumentCreateRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> GovernanceDocumentCommandResponse:
    _private(response)
    service = _service(request, session)
    prepared: PreparedGovernanceDocumentContent
    if body.sanitized_html is not None:
        prepared = prepare_governance_document_html(body.sanitized_html)
    else:
        assert body.source_template_version_id is not None
        prepared = await service.published_template_content(
            version_id=body.source_template_version_id,
            subject=context.subject,
            environment=context.environment,
            request_id=context.request_id,
        )
    value = await service.create_document(
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=_idempotency_key(idempotency_key),
        kind=GovernanceDocumentKind(body.kind),
        category=GovernanceDocumentCategory(body.category),
        title=body.title,
        summary=body.summary,
        classification=Classification(body.classification),
        applicability_scope=body.applicability_scope,
        content=prepared,
        source_template_version_id=body.source_template_version_id,
    )
    _etag(response, value.document.version)
    return GovernanceDocumentCommandResponse(item=governance_document_detail_response(value))


@router.get("/{document_id}", response_model=GovernanceDocumentDetailResponse)
async def get_governance_document(
    document_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> GovernanceDocumentDetailResponse:
    _private(response)
    value, read_context = await _service(request, session).get_document(
        document_id=document_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    _etag(response, value.document.version)
    return GovernanceDocumentDetailResponse(
        item=governance_document_detail_response(value),
        cache_scope=read_context.cache_scope,
        observed_at=read_context.observed_at,
        authorization_valid_until=read_context.authorization_valid_until,
    )


@router.post(
    "/{document_id}/versions",
    response_model=GovernanceDocumentCommandResponse,
    status_code=201,
)
async def create_governance_document_version(
    document_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")] = "",
) -> GovernanceDocumentCommandResponse:
    _private(response)
    body, content = await _version_input(request)
    value = await _service(request, session).create_version(
        document_id=document_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        expected_version=_expected_version(if_match),
        idempotency_key=_idempotency_key(idempotency_key),
        title=body.title,
        summary=body.summary,
        applicability_scope=body.applicability_scope,
        content=content,
        source_template_version_id=body.source_template_version_id,
    )
    _etag(response, value.document.version)
    return GovernanceDocumentCommandResponse(item=governance_document_detail_response(value))


@router.post(
    "/{document_id}/versions/{version_id}/submissions",
    response_model=GovernanceDocumentCommandResponse,
)
async def submit_governance_document_version(
    document_id: UUID,
    version_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")] = "",
) -> GovernanceDocumentCommandResponse:
    _private(response)
    value = await _service(request, session).submit_version(
        document_id=document_id,
        document_version_id=version_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        expected_version=_expected_version(if_match),
        idempotency_key=_idempotency_key(idempotency_key),
    )
    _etag(response, value.document.version)
    return GovernanceDocumentCommandResponse(item=governance_document_detail_response(value))


@router.post(
    "/{document_id}/versions/{version_id}/reviews",
    response_model=GovernanceDocumentCommandResponse,
)
async def review_governance_document_version(
    document_id: UUID,
    version_id: UUID,
    body: GovernanceDocumentReviewRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")] = "",
) -> GovernanceDocumentCommandResponse:
    _private(response)
    value = await _service(request, session).review_version(
        document_id=document_id,
        document_version_id=version_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        expected_version=_expected_version(if_match),
        idempotency_key=_idempotency_key(idempotency_key),
        decision=GovernanceDocumentReviewDecision(body.decision),
        reason=body.reason,
    )
    _etag(response, value.document.version)
    return GovernanceDocumentCommandResponse(item=governance_document_detail_response(value))


@router.post(
    "/{document_id}/versions/{version_id}/attachments",
    response_model=GovernanceDocumentAttachmentResponse,
    status_code=201,
)
async def add_governance_document_attachment(
    document_id: UUID,
    version_id: UUID,
    file: Annotated[UploadFile, File()],
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")] = "",
) -> GovernanceDocumentAttachmentResponse:
    _private(response)
    filename = file.filename or ""
    content_type = file.content_type or "application/octet-stream"
    value = await _service(request, session).add_attachment(
        document_id=document_id,
        document_version_id=version_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        expected_version=_expected_version(if_match),
        idempotency_key=_idempotency_key(idempotency_key),
        original_name=filename,
        content_type=content_type,
        content=await _bounded_upload(file),
    )
    return governance_document_attachment_response(value)


@router.get(
    "/{document_id}/attachments/{attachment_id}/download",
    response_model=GovernanceDocumentAttachmentDownloadResponse,
)
async def download_governance_document_attachment(
    document_id: UUID,
    attachment_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> GovernanceDocumentAttachmentDownloadResponse:
    _private(response)
    value = await _service(request, session).download_attachment(
        document_id=document_id,
        attachment_id=attachment_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return GovernanceDocumentAttachmentDownloadResponse(
        attachment=governance_document_attachment_response(value.attachment),
        url=value.url,
        expires_at=datetime.fromtimestamp(value.expires_at_epoch_seconds, tz=UTC),
    )


@router.post(
    "/{document_id}/archive",
    response_model=GovernanceDocumentCommandResponse,
)
async def archive_governance_document(
    document_id: UUID,
    body: GovernanceDocumentArchiveRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")] = "",
) -> GovernanceDocumentCommandResponse:
    _private(response)
    value = await _service(request, session).archive_document(
        document_id=document_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        expected_version=_expected_version(if_match),
        idempotency_key=_idempotency_key(idempotency_key),
        reason=body.reason,
    )
    _etag(response, value.document.version)
    return GovernanceDocumentCommandResponse(item=governance_document_detail_response(value))


async def _version_input(
    request: Request,
) -> tuple[GovernanceDocumentVersionCreateRequest, PreparedGovernanceDocumentContent]:
    content_type = request.headers.get("content-type", "").casefold()
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if not isinstance(upload, StarletteUploadFile):
            raise ValidationError("The Governance Document version file is required.")
        title = _form_text(form.get("title"), "title", required=True)
        summary = _form_text(form.get("summary"), "summary", required=False)
        applicability_scope = _form_text(
            form.get("applicability_scope"),
            "applicability_scope",
            required=False,
        )
        template_id = _optional_uuid(form.get("source_template_version_id"))
        filename = upload.filename
        upload_content_type = upload.content_type
        content = await _bounded_upload(upload)
        prepared = prepare_governance_document_upload(
            filename=filename,
            content_type=upload_content_type,
            content=content,
        )
        return (
            GovernanceDocumentVersionCreateRequest(
                title=title,
                summary=summary or None,
                applicability_scope=applicability_scope,
                sanitized_html=prepared.sanitized_html,
                source_template_version_id=template_id,
            ),
            prepared,
        )
    try:
        payload = GovernanceDocumentVersionCreateRequest.model_validate(await request.json())
    except (PydanticValidationError, ValueError, TypeError) as error:
        raise ValidationError("The Governance Document version body is invalid.") from error
    return payload, prepare_governance_document_html(payload.sanitized_html)


def _form_text(value: Any, label: str, *, required: bool) -> str:
    if value is None:
        if required:
            raise ValidationError(f"The Governance Document {label} form field is required.")
        return ""
    if not isinstance(value, str):
        raise ValidationError(f"The Governance Document {label} form field is invalid.")
    return value


def _optional_uuid(value: Any) -> UUID | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValidationError("The Governance Document template version id is invalid.")
    try:
        return UUID(value)
    except ValueError:
        raise ValidationError("The Governance Document template version id is invalid.") from None
