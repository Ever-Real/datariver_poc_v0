from __future__ import annotations

import base64
import binascii
import hashlib
import re
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

import orjson
from fastapi import APIRouter, File, Form, Header, Query, Request, Response, UploadFile
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.change_numbers import change_request_number
from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.catalog import CatalogService
from datariver.application.services.change_targets import CatalogChangeTargetAuthorizer
from datariver.application.services.governance import GovernanceService
from datariver.application.services.governance_attachments import (
    AttachmentUploadIntent,
    FinalizedAttachment,
    GovernanceAttachmentUploadService,
)
from datariver.domain.authz import Action, BuiltinPolicyEngine, Classification, SubjectAttributes
from datariver.domain.catalog import DATASET_ASSET_TYPES, is_dataset_asset_type
from datariver.domain.common import (
    ConflictError,
    NotFoundError,
    ValidationError,
    canonical_json_hash,
    utc_now,
    uuid7,
)
from datariver.domain.governance import (
    CHANGE_INTAKE_ASPECT,
    DATAHUB_INTAKE_TARGET,
    MANUAL_DATASET_INTAKE_TARGET,
    ApprovalDecision,
    ChangeItem,
    ChangePriority,
    ChangeState,
    ChangeTestRunState,
    ChangeUrgency,
)
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.catalog import (
    SqlCatalogChangeTargetReader,
    SqlCatalogIndexReader,
)
from datariver.infrastructure.db.change_request_overview import SqlChangeRequestOverviewReader
from datariver.infrastructure.db.classification_access import (
    SqlClassificationAccessSnapshotReader,
)
from datariver.infrastructure.db.governance import SqlGovernanceUnitOfWork
from datariver.infrastructure.db.governance_apply_report import (
    SqlGovernanceApplyReportReader,
)
from datariver.infrastructure.db.governance_attachments import (
    SqlGovernanceAttachmentUploadIntentStore,
)
from datariver.infrastructure.db.models.governance import (
    ChangeRequestAttachmentModel,
    ChangeRequestModel,
)
from datariver.infrastructure.db.models.platform import DataSystemModel
from datariver.infrastructure.db.rls import set_security_context
from datariver.interfaces.http.dependencies import ContextDep, SessionDep, get_container
from datariver.interfaces.http.presenters import (
    catalog_detail,
    catalog_summary,
    change_request_response,
    change_request_schema_overview_response,
    public_change_item_identity,
)
from datariver.interfaces.http.schemas import (
    ApprovalRequest,
    CatalogAssetResponse,
    CatalogPolicyMeta,
    CatalogSearchResponse,
    ChangeRequestAttachmentListResponse,
    ChangeRequestAttachmentPageResponse,
    ChangeRequestAttachmentResponse,
    ChangeRequestAttachmentUploadListResponse,
    ChangeRequestAttachmentUploadResponse,
    ChangeRequestCreate,
    ChangeRequestIntakeCreate,
    ChangeRequestListResponse,
    ChangeRequestResponse,
    ChangeRequestSummaryItemResponse,
    ChangeRequestSummaryListResponse,
    ChangeRequestSummaryResponse,
    ChangeRequestSystemListResponse,
    ChangeRequestSystemResponse,
    ChangeTestRunRequest,
    GovernanceApplyAttemptResponse,
    GovernanceApplyItemResponse,
    GovernanceApplyReportResponse,
    IntakeCompletionRequest,
    PageMeta,
    TransitionRequest,
)

router = APIRouter(prefix="/change-requests", tags=["governance"])

_MAXIMUM_ATTACHMENT_BYTES = 10 * 1024 * 1024
_MAXIMUM_LEGACY_ATTACHMENTS = 200
_FILE_NAME_DISALLOWED = re.compile(r"[^A-Za-z0-9._-]+")


def _change_request_system_scope(subject: SubjectAttributes) -> frozenset[UUID] | None:
    can_create_change_request = (
        subject.active
        and subject.job_function != "SERVICE_ACCOUNT"
        and "service-accounts" not in subject.groups
        and Action.CHANGE_CREATE in subject.allowed_actions
        and Action.CHANGE_CREATE not in subject.denied_actions
    )
    if not can_create_change_request:
        return frozenset()
    global_administrator = (
        "security-administrators" in subject.groups
        and Action.ADMIN_MANAGE in subject.allowed_actions
        and Action.ADMIN_MANAGE not in subject.denied_actions
        and subject.clearance >= Classification.RESTRICTED
    )
    return None if global_administrator else subject.allowed_system_ids


async def _change_request_target_system_is_available(
    *,
    context: ContextDep,
    session: SessionDep,
    system_id: UUID,
) -> bool:
    system_scope = _change_request_system_scope(context.subject)
    if system_scope is not None and system_id not in system_scope:
        return False
    return (
        await session.scalar(
            select(DataSystemModel.id).where(
                DataSystemModel.workspace_id == context.workspace_id,
                DataSystemModel.id == system_id,
                DataSystemModel.active.is_(True),
            )
        )
        is not None
    )


def _empty_change_request_target_search(
    context: ContextDep, *, limit: int
) -> CatalogSearchResponse:
    return CatalogSearchResponse(
        items=[],
        page=PageMeta(next_cursor=None, limit=limit),
        total=0,
        total_exact=True,
        meta=CatalogPolicyMeta(
            observed_at=context.environment.requested_at,
            projection_version=0,
            policy_version=BuiltinPolicyEngine.policy_version,
        ),
    )


def _attachment_cursor(
    *,
    change_request_id: UUID,
    created_at: datetime,
    attachment_id: UUID,
) -> str:
    payload = orjson.dumps(
        {
            "attachment_id": str(attachment_id),
            "change_request_id": str(change_request_id),
            "created_at": created_at.isoformat(),
            "v": 1,
        },
        option=orjson.OPT_SORT_KEYS,
    )
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _parse_attachment_cursor(
    cursor: str | None,
    *,
    change_request_id: UUID,
) -> tuple[datetime | None, UUID | None]:
    if cursor is None:
        return None, None
    try:
        document = orjson.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        if (
            not isinstance(document, dict)
            or set(document)
            != {
                "attachment_id",
                "change_request_id",
                "created_at",
                "v",
            }
            or document.get("v") != 1
            or document.get("change_request_id") != str(change_request_id)
        ):
            raise ValueError
        created_at = datetime.fromisoformat(str(document["created_at"]))
        if created_at.tzinfo is None:
            raise ValueError
        return created_at, UUID(str(document["attachment_id"]))
    except (ValueError, TypeError, binascii.Error, orjson.JSONDecodeError) as error:
        raise ValidationError("The attachment cursor is stale or invalid.") from error


def _service(request: Request, session: AsyncSession | None = None) -> GovernanceService:
    container = get_container(request)
    authorization = AuthorizationService(
        decision_writer=SqlDecisionWriter(container.database.session_factory)
    )
    return GovernanceService(
        lambda: SqlGovernanceUnitOfWork(
            container.database.session_factory,
            session=session,
        ),
        authorization,
        target_authorizer=(
            CatalogChangeTargetAuthorizer(
                index=SqlCatalogChangeTargetReader(session),
                classification_access=ClassificationAccessResolver(
                    SqlClassificationAccessSnapshotReader(session)
                ),
                authorization=authorization,
            )
            if session is not None
            else None
        ),
    )


def _attachment_service(
    request: Request,
    session: AsyncSession,
) -> GovernanceAttachmentUploadService:
    container = get_container(request)
    authorization = AuthorizationService(
        decision_writer=SqlDecisionWriter(container.database.session_factory)
    )
    return GovernanceAttachmentUploadService(
        lambda: SqlGovernanceUnitOfWork(
            container.database.session_factory,
            session=session,
        ),
        authorization,
        store=SqlGovernanceAttachmentUploadIntentStore(session),
        target_authorizer=CatalogChangeTargetAuthorizer(
            index=SqlCatalogChangeTargetReader(session),
            classification_access=ClassificationAccessResolver(
                SqlClassificationAccessSnapshotReader(session)
            ),
            authorization=authorization,
        ),
    )


def _catalog_service(request: Request, session: SessionDep) -> CatalogService:
    container = get_container(request)
    index = SqlCatalogIndexReader(session)
    return CatalogService(
        index=index,
        discovery=index,
        watermark=index,
        datahub=container.datahub,
        cache=container.cache,
        authorization=AuthorizationService(
            decision_writer=SqlDecisionWriter(container.database.session_factory)
        ),
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


def _change_target_catalog_service(
    request: Request,
    session: SessionDep,
) -> tuple[CatalogService, SqlCatalogChangeTargetReader]:
    container = get_container(request)
    index = SqlCatalogChangeTargetReader(session)
    return (
        CatalogService(
            index=index,
            discovery=index,
            watermark=index,
            datahub=container.datahub,
            cache=container.cache,
            authorization=AuthorizationService(
                decision_writer=SqlDecisionWriter(container.database.session_factory)
            ),
            detail_cache_ttl_seconds=container.settings.cache_default_ttl_seconds,
            stale_detail_ttl_seconds=container.settings.datahub_stale_ttl_seconds,
            # System-schema mappings have their own version fence rather than the Catalog
            # projection watermark. CR target search therefore revalidates routing on every read.
            search_cache_ttl_seconds=0,
            minimum_query_length=container.settings.catalog_search_minimum_query_length,
            policy_version=BuiltinPolicyEngine.policy_version,
            classification_access=ClassificationAccessResolver(
                SqlClassificationAccessSnapshotReader(session)
            ),
            telemetry=container.metrics,
        ),
        index,
    )


def _metadata_tokens(value: object, key: str) -> list[str]:
    if not isinstance(value, list):
        return []
    values: list[str] = []
    for item in value:
        candidate = item.get(key) if isinstance(item, dict) else None
        if isinstance(candidate, str):
            values.append(candidate)
        elif isinstance(candidate, dict):
            display = candidate.get("name") or candidate.get("urn")
            if isinstance(display, str):
                values.append(display)
    return values


def _unique_values(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))[:100]


def _expected_version(if_match: str) -> int:
    value = if_match.strip().strip('"')
    if not value.isdigit() or int(value) < 1:
        raise ValidationError("If-Match must contain a quoted positive aggregate version.")
    return int(value)


@router.get("", response_model=ChangeRequestListResponse)
async def list_change_requests(
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    state: Annotated[str | None, Query(max_length=32)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ChangeRequestListResponse:
    """Preserve the published v1 full-record list contract for existing clients."""
    try:
        parsed_state = ChangeState(state) if state else None
    except ValueError as error:
        raise ValidationError("The change-request state filter is invalid.") from error
    values = await _service(request, session).list_change_requests(
        workspace_id=context.workspace_id,
        state=parsed_state,
        limit=limit,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    await set_security_context(
        session,
        workspace_id=context.workspace_id,
        subject_id=context.subject.subject_id,
    )
    access = await ClassificationAccessResolver(
        SqlClassificationAccessSnapshotReader(session)
    ).resolve(
        workspace_id=context.workspace_id,
        subject_id=context.subject.subject_id,
        now=context.environment.requested_at,
    )
    overview = await SqlChangeRequestOverviewReader(session).list_schema_overview(
        subject=context.subject,
        access=access,
        change_requests=values,
        limit=100,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return ChangeRequestListResponse(
        items=[change_request_response(value) for value in values],
        overview=[change_request_schema_overview_response(value) for value in overview],
    )


@router.get("/summaries", response_model=ChangeRequestSummaryListResponse)
async def list_change_request_summaries(
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    state: Annotated[str | None, Query(max_length=32)] = None,
    cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
) -> ChangeRequestSummaryListResponse:
    try:
        parsed_state = ChangeState(state) if state else None
    except ValueError as error:
        raise ValidationError("The change-request state filter is invalid.") from error
    page = await _service(request, session).list_change_request_summaries(
        workspace_id=context.workspace_id,
        state=parsed_state,
        cursor=cursor,
        limit=limit,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    # The shared governance UoW commits after authorization, which clears PostgreSQL
    # SET LOCAL values. Re-establish the request scope before route-level RLS reads.
    await set_security_context(
        session,
        workspace_id=context.workspace_id,
        subject_id=context.subject.subject_id,
    )
    access = await ClassificationAccessResolver(
        SqlClassificationAccessSnapshotReader(session)
    ).resolve(
        workspace_id=context.workspace_id,
        subject_id=context.subject.subject_id,
        now=context.environment.requested_at,
    )
    overview_reader = SqlChangeRequestOverviewReader(session)
    overview = await overview_reader.list_schema_overview(
        subject=context.subject,
        access=access,
        change_requests=page.items,
        limit=101,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return ChangeRequestSummaryListResponse(
        items=[
            ChangeRequestSummaryResponse(
                id=value.change_request_id,
                number=value.number,
                request_type=value.request_type,
                title=value.title,
                state=value.state.value,
                requester_id=value.requester_id,
                requester_department_id=value.requester_department_id,
                current_round_number=value.current_round_number,
                created_at=value.created_at,
                requested_due_date=value.requested_due_date,
                priority=value.priority,
                urgency=value.urgency,
                classification=value.classification.name,
                version=value.version,
                item_count=len(value.targets),
                first_item=ChangeRequestSummaryItemResponse(
                    target_ref=public_change_item_identity(
                        request_type=value.request_type,
                        target_ref=value.targets[0].target_ref,
                        aspect_name=value.targets[0].aspect_name,
                        target_asset_id=value.targets[0].target_asset_id,
                    )[0],
                    aspect_name=public_change_item_identity(
                        request_type=value.request_type,
                        target_ref=value.targets[0].target_ref,
                        aspect_name=value.targets[0].aspect_name,
                        target_asset_id=value.targets[0].target_asset_id,
                    )[1],
                    operation=value.targets[0].operation,
                ),
            )
            for value in page.items
        ],
        overview=[change_request_schema_overview_response(value) for value in overview],
        overview_truncated=overview_reader.truncated,
        page=PageMeta(next_cursor=page.next_cursor, limit=limit),
    )


@router.get("/systems", response_model=ChangeRequestSystemListResponse)
async def list_change_request_systems(
    context: ContextDep,
    session: SessionDep,
) -> ChangeRequestSystemListResponse:
    system_scope = _change_request_system_scope(context.subject)
    if system_scope is not None and not system_scope:
        return ChangeRequestSystemListResponse(items=[])
    statement = select(DataSystemModel).where(
        DataSystemModel.workspace_id == context.workspace_id,
        DataSystemModel.active.is_(True),
    )
    if system_scope is not None:
        statement = statement.where(DataSystemModel.id.in_(system_scope))
    values = (
        await session.scalars(statement.order_by(DataSystemModel.name, DataSystemModel.id))
    ).all()
    return ChangeRequestSystemListResponse(
        items=[
            ChangeRequestSystemResponse(id=value.id, code=value.code, name=value.name)
            for value in values
        ]
    )


@router.get("/targets", response_model=CatalogSearchResponse)
async def search_change_request_targets(
    request: Request,
    context: ContextDep,
    session: SessionDep,
    system_id: Annotated[UUID, Query()],
    q: Annotated[str, Query(max_length=500)] = "",
    cursor: Annotated[str | None, Query(max_length=2000)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> CatalogSearchResponse:
    if not await _change_request_target_system_is_available(
        context=context,
        session=session,
        system_id=system_id,
    ):
        return _empty_change_request_target_search(context, limit=limit)
    target_catalog, _ = _change_target_catalog_service(request, session)
    page = await target_catalog.search(
        subject=context.subject,
        query=q,
        filters={
            "asset_types": tuple(sorted(DATASET_ASSET_TYPES)),
            "routing_system_id": system_id,
        },
        cursor=cursor,
        limit=limit,
        environment=context.environment,
        request_id=context.request_id,
    )
    return CatalogSearchResponse(
        items=[catalog_summary(item) for item in page.items],
        page=PageMeta(next_cursor=page.next_cursor, limit=limit),
        total=page.total,
        total_exact=page.total_exact,
        meta=CatalogPolicyMeta(
            observed_at=page.observed_at,
            stale_at=page.stale_at,
            projection_version=page.projection_version,
            policy_version=page.policy_version,
            classification_policy_version=page.classification_policy_version,
            authorization_generation=page.authorization_generation,
        ),
    )


@router.get("/targets/{asset_id}", response_model=CatalogAssetResponse)
async def get_change_request_target(
    asset_id: UUID,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    system_id: Annotated[UUID, Query()],
) -> CatalogAssetResponse:
    if not await _change_request_target_system_is_available(
        context=context,
        session=session,
        system_id=system_id,
    ):
        raise NotFoundError("The selected change target does not exist.")
    target_catalog, target_reader = _change_target_catalog_service(request, session)
    asset = await target_catalog.get_asset(
        subject=context.subject,
        asset_id=asset_id,
        environment=context.environment,
        request_id=context.request_id,
    )
    if asset is not None:
        asset = await target_reader.route_authorized_detail(
            detail=asset,
            system_id=system_id,
        )
    if asset is None or not is_dataset_asset_type(asset.index.asset_type):
        raise NotFoundError("The selected change target does not exist.")
    return catalog_detail(asset)


@router.get("/{change_request_id}", response_model=ChangeRequestResponse)
async def get_change_request(
    change_request_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> ChangeRequestResponse:
    value = await _service(request, session).get_change_request(
        workspace_id=context.workspace_id,
        change_request_id=change_request_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return change_request_response(value)


@router.get(
    "/{change_request_id}/apply-report",
    response_model=GovernanceApplyReportResponse,
)
async def get_change_request_apply_report(
    change_request_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> GovernanceApplyReportResponse:
    change_request = await _service(request, session).get_change_request(
        workspace_id=context.workspace_id,
        change_request_id=change_request_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    await set_security_context(
        session,
        workspace_id=context.workspace_id,
        subject_id=context.subject.subject_id,
    )
    report = await SqlGovernanceApplyReportReader(session).get(
        workspace_id=context.workspace_id,
        change_request=change_request,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return GovernanceApplyReportResponse(
        change_request_id=report.change_request_id,
        job_id=report.job_id,
        state=report.state,
        attempt_count=report.attempt_count,
        last_error_code=report.last_error_code,
        expected_hash=report.expected_hash,
        observed_hash=report.observed_hash,
        reconciled=report.reconciled,
        created_at=report.created_at,
        updated_at=report.updated_at,
        items=[
            GovernanceApplyItemResponse(
                item_id=item.item_id,
                expected_hash=item.expected_hash,
                observed_hash=item.observed_hash,
                source_version=item.source_version,
                provider_version=item.provider_version,
            )
            for item in report.items
        ],
        attempts=[
            GovernanceApplyAttemptResponse(
                id=attempt.attempt_id,
                attempt_no=attempt.attempt_no,
                state=attempt.state,
                failure_code=attempt.failure_code,
                external_response_hash=attempt.external_response_hash,
                started_at=attempt.started_at,
                finished_at=attempt.finished_at,
            )
            for attempt in report.attempts
        ],
    )


def _attachment_response(
    value: ChangeRequestAttachmentModel | FinalizedAttachment,
) -> ChangeRequestAttachmentResponse:
    return ChangeRequestAttachmentResponse(
        id=value.id,
        kind=value.kind,
        round_id=value.round_id,
        original_name=value.original_name,
        serial_number=value.serial_number,
        content_type=value.content_type,
        size_bytes=value.size_bytes,
        content_sha256=value.content_sha256,
        created_at=value.created_at,
    )


def _attachment_upload_response(
    *,
    intent: AttachmentUploadIntent,
) -> ChangeRequestAttachmentUploadResponse:
    base_path = (
        f"/change-requests/{intent.change_request_id}/attachment-uploads/{intent.attachment_id}"
    )
    return ChangeRequestAttachmentUploadResponse(
        id=intent.attachment_id,
        change_request_id=intent.change_request_id,
        round_id=intent.round_id,
        kind=intent.kind,
        original_name=intent.original_name,
        state=intent.state,
        expected_size_bytes=intent.expected_size_bytes,
        expected_content_sha256=intent.expected_content_sha256,
        provider_checksum=intent.provider_checksum,
        failure_code=intent.failure_code,
        status_url=base_path,
        finalize_url=f"{base_path}/finalize",
    )


async def _upload_chunks(upload: UploadFile) -> AsyncIterator[bytes]:
    while chunk := await upload.read(1024 * 1024):
        yield chunk


async def _bounded_attachment_content(upload: UploadFile) -> bytes:
    content = bytearray()
    async for chunk in _upload_chunks(upload):
        if len(content) + len(chunk) > _MAXIMUM_ATTACHMENT_BYTES:
            raise ValidationError(
                "The attachment exceeds the configured byte limit.",
                details={"code": "OBJECT_BYTE_LIMIT"},
            )
        content.extend(chunk)
    if not content:
        raise ValidationError(
            "The attachment cannot be empty.",
            details={"code": "OBJECT_EMPTY"},
        )
    return bytes(content)


async def _content_chunks(content: bytes) -> AsyncIterator[bytes]:
    for offset in range(0, len(content), 1024 * 1024):
        yield content[offset : offset + 1024 * 1024]


def _safe_attachment_name(name: str | None) -> tuple[str, str, str]:
    candidate = Path(name or "attachment").name
    safe = _FILE_NAME_DISALLOWED.sub("_", candidate).strip("._")[:500]
    if not safe:
        raise ValidationError("The attachment filename is invalid.")
    suffix = Path(safe).suffix[:32]
    stem = Path(safe).stem[: max(1, 460 - len(suffix))]
    return safe, stem, suffix


def _attachment_object_key(
    *,
    workspace_id: UUID,
    change_request_id: UUID,
    attachment_id: UUID,
) -> str:
    return (
        f"governance/change-request-attachments/{workspace_id}/{change_request_id}/{attachment_id}"
    )


@router.get("/{change_request_id}/attachments", response_model=ChangeRequestAttachmentListResponse)
async def list_change_request_attachments(
    change_request_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> ChangeRequestAttachmentListResponse:
    """Preserve the published v1 full-list response within its explicit safe bound."""
    await _service(request, session).get_change_request(
        workspace_id=context.workspace_id,
        change_request_id=change_request_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    await set_security_context(
        session,
        workspace_id=context.workspace_id,
        subject_id=context.subject.subject_id,
    )
    rows = list(
        (
            await session.scalars(
                select(ChangeRequestAttachmentModel)
                .where(
                    ChangeRequestAttachmentModel.workspace_id == context.workspace_id,
                    ChangeRequestAttachmentModel.change_request_id == change_request_id,
                )
                .order_by(
                    ChangeRequestAttachmentModel.created_at,
                    ChangeRequestAttachmentModel.id,
                )
                .limit(_MAXIMUM_LEGACY_ATTACHMENTS + 1)
            )
        ).all()
    )
    if len(rows) > _MAXIMUM_LEGACY_ATTACHMENTS:
        raise ValidationError(
            "The attachment collection exceeds the legacy safe list limit.",
            details={
                "code": "ATTACHMENT_LEGACY_LIST_LIMIT_EXCEEDED",
                "maximum": _MAXIMUM_LEGACY_ATTACHMENTS,
                "page_path": f"/change-requests/{change_request_id}/attachments/page",
            },
        )
    response.headers["Cache-Control"] = "private, no-store"
    return ChangeRequestAttachmentListResponse(
        items=[_attachment_response(row) for row in rows],
    )


@router.get(
    "/{change_request_id}/attachments/page",
    response_model=ChangeRequestAttachmentPageResponse,
)
async def list_change_request_attachment_page(
    change_request_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
) -> ChangeRequestAttachmentPageResponse:
    await _service(request, session).get_change_request(
        workspace_id=context.workspace_id,
        change_request_id=change_request_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    await set_security_context(
        session,
        workspace_id=context.workspace_id,
        subject_id=context.subject.subject_id,
    )
    after_created_at, after_id = _parse_attachment_cursor(
        cursor,
        change_request_id=change_request_id,
    )
    statement = select(ChangeRequestAttachmentModel).where(
        ChangeRequestAttachmentModel.workspace_id == context.workspace_id,
        ChangeRequestAttachmentModel.change_request_id == change_request_id,
    )
    if after_created_at is not None and after_id is not None:
        statement = statement.where(
            or_(
                ChangeRequestAttachmentModel.created_at > after_created_at,
                and_(
                    ChangeRequestAttachmentModel.created_at == after_created_at,
                    ChangeRequestAttachmentModel.id > after_id,
                ),
            )
        )
    rows = list(
        (
            await session.scalars(
                statement.order_by(
                    ChangeRequestAttachmentModel.created_at,
                    ChangeRequestAttachmentModel.id,
                ).limit(limit + 1)
            )
        ).all()
    )
    visible = rows[:limit]
    next_cursor = (
        _attachment_cursor(
            change_request_id=change_request_id,
            created_at=visible[-1].created_at,
            attachment_id=visible[-1].id,
        )
        if len(rows) > limit and visible
        else None
    )
    response.headers["Cache-Control"] = "private, no-store"
    return ChangeRequestAttachmentPageResponse(
        items=[_attachment_response(row) for row in visible],
        page=PageMeta(next_cursor=next_cursor, limit=limit),
    )


@router.post(
    "/{change_request_id}/attachments",
    response_model=ChangeRequestAttachmentUploadResponse,
    status_code=202,
)
async def upload_change_request_attachment(
    change_request_id: UUID,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    kind: Annotated[str, Form(pattern="^(REQUEST|TEST)$")] = "REQUEST",
    upload_id: Annotated[UUID | None, Form()] = None,
) -> ChangeRequestAttachmentUploadResponse:
    container = get_container(request)
    bucket = container.settings.s3_bucket_filefolder
    if not bucket:
        raise ValidationError(
            "Change-request attachment storage is not configured.",
            details={"code": "FILEFOLDER_BUCKET_NOT_CONFIGURED"},
        )
    original_name, _, _ = _safe_attachment_name(file.filename)
    content = await _bounded_attachment_content(file)
    attachment_id = upload_id or uuid7()
    object_key = _attachment_object_key(
        workspace_id=context.workspace_id,
        change_request_id=change_request_id,
        attachment_id=attachment_id,
    )
    content_type = (file.content_type or "application/octet-stream")[:255]
    service = _attachment_service(request, session)
    intent = await service.start(
        attachment_id=attachment_id,
        workspace_id=context.workspace_id,
        change_request_id=change_request_id,
        kind=kind,
        original_name=original_name,
        bucket=bucket,
        object_key=object_key,
        content_type=content_type,
        expected_size_bytes=len(content),
        expected_content_sha256=hashlib.sha256(content).hexdigest(),
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    try:
        await container.object_store.write_create_only(
            bucket=bucket,
            object_key=object_key,
            chunks=_content_chunks(content),
            metadata={
                "workspace-id": str(context.workspace_id),
                "change-request-id": str(change_request_id),
                "attachment-id": str(attachment_id),
                "attachment-kind": kind,
                "content-sha256": intent.expected_content_sha256,
            },
            maximum_bytes=_MAXIMUM_ATTACHMENT_BYTES,
            content_type=content_type,
        )
    except ConflictError as error:
        if error.details.get("code") == "OBJECT_KEY_ALREADY_EXISTS":
            await service.record_known_create_rejection(
                workspace_id=context.workspace_id,
                attachment_id=attachment_id,
                subject_id=context.subject.subject_id,
                failure_code="OBJECT_KEY_ALREADY_EXISTS",
                occurred_at=utc_now(),
            )
        raise
    return _attachment_upload_response(intent=intent)


@router.get(
    "/{change_request_id}/attachment-uploads",
    response_model=ChangeRequestAttachmentUploadListResponse,
)
async def list_change_request_attachment_uploads(
    change_request_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    round_id: Annotated[UUID, Query()],
    limit: Annotated[int, Query(ge=1, le=10)] = 10,
) -> ChangeRequestAttachmentUploadListResponse:
    intents = await _attachment_service(request, session).list_reconcilable(
        workspace_id=context.workspace_id,
        subject_id=context.subject.subject_id,
        change_request_id=change_request_id,
        round_id=round_id,
        states=frozenset({"STORED"}),
        before_or_at=utc_now(),
        limit=limit,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return ChangeRequestAttachmentUploadListResponse(
        items=[_attachment_upload_response(intent=intent) for intent in intents]
    )


@router.get(
    "/{change_request_id}/attachment-uploads/{attachment_id}",
    response_model=ChangeRequestAttachmentUploadResponse,
)
async def get_change_request_attachment_upload(
    change_request_id: UUID,
    attachment_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> ChangeRequestAttachmentUploadResponse:
    intent = await _attachment_service(request, session).get_upload_intent(
        workspace_id=context.workspace_id,
        attachment_id=attachment_id,
        subject_id=context.subject.subject_id,
    )
    if intent.change_request_id != change_request_id:
        raise NotFoundError("The attachment upload intent does not exist.")
    response.headers["Cache-Control"] = "private, no-store"
    return _attachment_upload_response(intent=intent)


@router.post(
    "/{change_request_id}/attachment-uploads/{attachment_id}/finalize",
    response_model=ChangeRequestAttachmentResponse,
)
async def finalize_change_request_attachment_upload(
    change_request_id: UUID,
    attachment_id: UUID,
    request: Request,
    context: ContextDep,
    session: SessionDep,
) -> ChangeRequestAttachmentResponse:
    finalized = await _attachment_service(request, session).finalize(
        workspace_id=context.workspace_id,
        change_request_id=change_request_id,
        attachment_id=attachment_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        occurred_at=utc_now(),
    )
    if finalized.id != attachment_id:
        raise ConflictError("The finalized attachment identity does not match its upload.")
    return _attachment_response(finalized)


@router.get("/{change_request_id}/attachments/{attachment_id}/download")
async def download_change_request_attachment(
    change_request_id: UUID,
    attachment_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> dict[str, str]:
    container = get_container(request)
    await _service(request, session).get_change_request(
        workspace_id=context.workspace_id,
        change_request_id=change_request_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    await set_security_context(
        session,
        workspace_id=context.workspace_id,
        subject_id=context.subject.subject_id,
    )
    row = (
        await session.scalars(
            select(ChangeRequestAttachmentModel).where(
                ChangeRequestAttachmentModel.workspace_id == context.workspace_id,
                ChangeRequestAttachmentModel.change_request_id == change_request_id,
                ChangeRequestAttachmentModel.id == attachment_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError("The attachment does not exist.")
    response.headers["Cache-Control"] = "private, no-store"
    return {
        "url": await container.object_store.presign_download(
            bucket=row.bucket,
            object_key=row.object_key,
            download_name=row.original_name,
            expires_seconds=container.settings.presigned_url_ttl_seconds,
        )
    }


@router.post("", status_code=201, response_model=ChangeRequestResponse)
async def create_change_request(
    payload: ChangeRequestCreate,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> ChangeRequestResponse:
    items: list[ChangeItem] = []
    for item in payload.items:
        computed_hash = canonical_json_hash(item.after_document)
        if item.after_hash is not None and item.after_hash != computed_hash:
            raise ValidationError("A change item after_hash does not match its document.")
        items.append(
            ChangeItem(
                item_id=uuid7(),
                target_type=item.target_type,
                target_ref=item.target_ref,
                operation=item.operation,
                after_document=item.after_document,
                aspect_name=item.aspect_name,
                before_hash=item.before_hash,
                after_hash=computed_hash,
            )
        )
    request_hash = hashlib.sha256(
        orjson.dumps(payload.model_dump(mode="json"), option=orjson.OPT_SORT_KEYS)
    ).hexdigest()
    number = change_request_number(None)
    change_request = await _service(request, session).create_change_request(
        workspace_id=context.workspace_id,
        number=number,
        request_type=payload.request_type,
        title=payload.title,
        description=payload.description,
        requester_id=context.subject.subject_id,
        items=items,
        subject=context.subject,
        classification=Classification[payload.classification],
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        require_raw_operator_gate=True,
        requested_due_date=payload.requested_due_date,
        priority=ChangePriority(payload.priority) if payload.priority is not None else None,
        urgency=ChangeUrgency(payload.urgency) if payload.urgency is not None else None,
    )
    return change_request_response(change_request)


@router.post("/intake", status_code=201, response_model=ChangeRequestResponse)
async def create_change_request_intake(
    payload: ChangeRequestIntakeCreate,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> ChangeRequestResponse:
    """Create the v0.3-shaped CR form as an auditable, non-provider-write intake.

    Existing table identity and current fields are resolved again on the server;
    manual tables receive only a server-minted proposal URN.  This keeps the
    complete legacy form useful without allowing the browser to fabricate a
    DataHub target or to submit provider credentials/documents.
    """

    system = (
        await session.scalars(
            select(DataSystemModel).where(
                DataSystemModel.workspace_id == context.workspace_id,
                DataSystemModel.id == payload.system_id,
                DataSystemModel.active.is_(True),
            )
        )
    ).one_or_none()
    if system is None:
        raise ValidationError("The selected canonical data system is not active.")
    catalog = _catalog_service(request, session)
    items: list[ChangeItem] = []
    for target in payload.targets:
        if target.kind == "MANUAL":
            manual_after_document = {
                "contract": "change-intake-v1",
                "kind": "MANUAL",
                "database_name": target.database_name.strip(),
                "schema_name": target.schema_name.strip(),
                "table_name": target.table_name.strip(),
                "owner": target.owner.strip(),
                "description": target.description.strip(),
                "requested_change": target.requested_change.strip(),
                "tags": _unique_values(target.tags),
                "terms": _unique_values(target.terms),
                "columns": [
                    {
                        "field_path": column.field_path.strip(),
                        "data_type": column.data_type.strip(),
                        "description": column.description.strip(),
                        "requested_change": column.requested_change.strip(),
                        "tags": _unique_values(column.tags),
                        "terms": _unique_values(column.terms),
                    }
                    for column in target.columns
                ],
            }
            item_id = uuid7()
            items.append(
                ChangeItem(
                    item_id=item_id,
                    target_type=MANUAL_DATASET_INTAKE_TARGET,
                    target_ref=f"urn:datariver:proposed-dataset:{item_id}",
                    operation="CREATE",
                    aspect_name=CHANGE_INTAKE_ASPECT,
                    after_document=manual_after_document,
                    after_hash=canonical_json_hash(manual_after_document),
                    routing_system_id=system.id,
                )
            )
            continue

        detail = await catalog.get_asset(
            subject=context.subject,
            asset_id=target.asset_id,
            environment=context.environment,
            request_id=context.request_id,
        )
        if detail is None:
            raise NotFoundError("The selected catalog asset does not exist.")
        source_fields = {
            str(field.get("fieldPath")): field
            for field in detail.schema_fields
            if isinstance(field, dict) and isinstance(field.get("fieldPath"), str)
        }
        requested_columns: list[dict[str, object]] = []
        seen_fields: set[str] = set()
        for column in target.columns:
            field_path = column.field_path.strip()
            if field_path in seen_fields or field_path not in source_fields:
                raise ValidationError("A requested existing-table column is not available.")
            seen_fields.add(field_path)
            source = source_fields[field_path]
            source_tags = _metadata_tokens(
                (source.get("globalTags") or source.get("tags") or {}).get("tags", [])
                if isinstance(source.get("globalTags") or source.get("tags"), dict)
                else [],
                "tag",
            )
            source_terms = _metadata_tokens(
                (source.get("glossaryTerms") or source.get("terms") or {}).get("terms", [])
                if isinstance(source.get("glossaryTerms") or source.get("terms"), dict)
                else [],
                "term",
            )
            requested_columns.append(
                {
                    "field_path": field_path,
                    "source": {
                        "data_type": str(source.get("type") or source.get("nativeDataType") or ""),
                        "description": str(source.get("description") or ""),
                        "tags": _unique_values(source_tags),
                        "terms": _unique_values(source_terms),
                    },
                    "requested": {
                        "data_type": column.data_type.strip(),
                        "description": column.description.strip(),
                        "requested_change": column.requested_change.strip(),
                        "tags": _unique_values(column.tags),
                        "terms": _unique_values(column.terms),
                    },
                }
            )
        source_document: dict[str, Any] = {
            "asset_id": str(detail.index.asset_id),
            "external_urn": detail.index.external_urn,
            "platform": detail.index.platform,
            "database_name": detail.index.database_name,
            "schema_name": detail.index.schema_name,
            "table_name": detail.index.name,
            "owner": detail.index.owner,
            "description": detail.index.description or "",
            "tags": _unique_values(list(detail.tags)),
            "terms": _unique_values(_metadata_tokens(list(detail.glossary_terms), "term")),
            "source_version": detail.raw_version,
        }
        after_document: dict[str, Any] = {
            "contract": "change-intake-v1",
            "kind": "EXISTING",
            "source": source_document,
            "requested": {
                "description": target.description.strip(),
                "requested_change": target.requested_change.strip(),
                "tags": _unique_values(target.tags),
                "terms": _unique_values(target.terms),
                "columns": requested_columns,
            },
        }
        items.append(
            ChangeItem(
                item_id=uuid7(),
                target_type=DATAHUB_INTAKE_TARGET,
                target_ref=detail.index.external_urn,
                operation="REVIEW",
                aspect_name=CHANGE_INTAKE_ASPECT,
                before_hash=canonical_json_hash(source_document),
                after_document=after_document,
                after_hash=canonical_json_hash(after_document),
            )
        )

    request_hash = hashlib.sha256(
        orjson.dumps(payload.model_dump(mode="json"), option=orjson.OPT_SORT_KEYS)
    ).hexdigest()
    change_request = await _service(request, session).create_change_request(
        workspace_id=context.workspace_id,
        number=change_request_number(system.code),
        request_type="CHANGE_INTAKE",
        title=payload.title,
        description="\n\n".join(
            value
            for value in (payload.request_reason.strip(), payload.request_content.strip())
            if value
        ),
        requester_id=context.subject.subject_id,
        items=items,
        subject=context.subject,
        classification=Classification[payload.security_level],
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        require_raw_operator_gate=False,
        requested_due_date=payload.requested_due_date,
        priority=ChangePriority(payload.priority),
        urgency=ChangeUrgency(payload.urgency),
    )
    return change_request_response(change_request)


@router.post("/{change_request_id}/complete-intake", response_model=ChangeRequestResponse)
async def complete_change_request_intake(
    change_request_id: UUID,
    payload: IntakeCompletionRequest,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> ChangeRequestResponse:
    expected_version = _expected_version(if_match)
    request_hash = hashlib.sha256(
        orjson.dumps(
            {"reason": payload.reason, "expected_version": expected_version},
            option=orjson.OPT_SORT_KEYS,
        )
    ).hexdigest()
    change_request = await _service(request, session).complete_intake(
        workspace_id=context.workspace_id,
        change_request_id=change_request_id,
        actor_id=context.subject.subject_id,
        reason=payload.reason,
        expected_version=expected_version,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    return change_request_response(change_request)


@router.post("/{change_request_id}/approvals", response_model=ChangeRequestResponse)
async def add_approval(
    change_request_id: UUID,
    payload: ApprovalRequest,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> ChangeRequestResponse:
    expected_version = _expected_version(if_match)
    decision = ApprovalDecision(payload.decision)
    request_hash = hashlib.sha256(
        orjson.dumps(
            {
                "change_request_id": str(change_request_id),
                "stage": payload.stage,
                "decision": decision.value,
                "reason": payload.reason,
                "expected_version": expected_version,
            },
            option=orjson.OPT_SORT_KEYS,
        )
    ).hexdigest()
    change_request = await _service(request, session).add_approval(
        workspace_id=context.workspace_id,
        change_request_id=change_request_id,
        stage=payload.stage,
        approval_decision=decision,
        reason=payload.reason,
        expected_version=expected_version,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    return change_request_response(change_request)


@router.post("/{change_request_id}/test-runs", response_model=ChangeRequestResponse)
async def record_change_request_test_run(
    change_request_id: UUID,
    payload: ChangeTestRunRequest,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> ChangeRequestResponse:
    expected_version = _expected_version(if_match)
    state = ChangeTestRunState(payload.state)
    attachment = (
        await session.scalars(
            select(ChangeRequestAttachmentModel)
            .join(
                ChangeRequestModel,
                (ChangeRequestModel.workspace_id == ChangeRequestAttachmentModel.workspace_id)
                & (ChangeRequestModel.id == ChangeRequestAttachmentModel.change_request_id),
            )
            .where(
                ChangeRequestAttachmentModel.workspace_id == context.workspace_id,
                ChangeRequestAttachmentModel.change_request_id == change_request_id,
                ChangeRequestAttachmentModel.id == payload.attachment_id,
                ChangeRequestAttachmentModel.kind == "TEST",
                ChangeRequestAttachmentModel.round_id == ChangeRequestModel.current_round_id,
            )
        )
    ).one_or_none()
    if attachment is None:
        raise ValidationError("A TEST attachment from the current round is required.")
    plan_hash = canonical_json_hash(
        {
            "contract": "CR_TEST_ATTACHMENT_V1",
            "change_request_id": str(change_request_id),
            "round_id": str(attachment.round_id),
            "system_id": str(payload.system_id),
            "attachment_id": str(attachment.id),
        }
    )
    result_hash = attachment.content_sha256
    bounded_summary: dict[str, Any] = {
        "contract": "CR_TEST_ATTACHMENT_V1",
        "attachment_id": str(attachment.id),
        "attachment_name": attachment.original_name,
        "operator_summary": payload.bounded_summary,
    }
    request_hash = hashlib.sha256(
        orjson.dumps(
            {
                "change_request_id": str(change_request_id),
                "system_id": str(payload.system_id),
                "attachment_id": str(payload.attachment_id),
                "state": state.value,
                "plan_hash": plan_hash,
                "result_hash": result_hash,
                "bounded_summary": bounded_summary,
                "expected_version": expected_version,
            },
            option=orjson.OPT_SORT_KEYS,
        )
    ).hexdigest()
    change_request = await _service(request, session).record_test_run(
        workspace_id=context.workspace_id,
        change_request_id=change_request_id,
        system_id=payload.system_id,
        attachment_id=attachment.id,
        state=state,
        plan_hash=plan_hash,
        result_hash=result_hash,
        bounded_summary=bounded_summary,
        expected_version=expected_version,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    return change_request_response(change_request)


@router.post("/{change_request_id}/transitions", response_model=ChangeRequestResponse)
async def transition_change_request(
    change_request_id: UUID,
    payload: TransitionRequest,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> ChangeRequestResponse:
    try:
        target = ChangeState(payload.target_state)
    except ValueError as error:
        raise ValidationError("The target change-request state is invalid.") from error
    expected_version = _expected_version(if_match)
    request_hash = hashlib.sha256(
        orjson.dumps(
            {
                "change_request_id": str(change_request_id),
                "target_state": target.value,
                "reason": payload.reason,
                "expected_version": expected_version,
            },
            option=orjson.OPT_SORT_KEYS,
        )
    ).hexdigest()
    change_request = await _service(request, session).transition(
        workspace_id=context.workspace_id,
        change_request_id=change_request_id,
        target=target,
        actor_id=context.subject.subject_id,
        reason=payload.reason,
        expected_version=expected_version,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    return change_request_response(change_request)
