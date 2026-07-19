from __future__ import annotations

import hashlib
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

import orjson
from fastapi import APIRouter, File, Form, Header, Query, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.change_numbers import change_request_number
from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.catalog import CatalogService
from datariver.application.services.change_targets import CatalogChangeTargetAuthorizer
from datariver.application.services.governance import GovernanceService
from datariver.domain.authz import BuiltinPolicyEngine, Classification
from datariver.domain.common import NotFoundError, ValidationError, canonical_json_hash, uuid7
from datariver.domain.governance import (
    CHANGE_INTAKE_ASPECT,
    DATAHUB_INTAKE_TARGET,
    MANUAL_DATASET_INTAKE_TARGET,
    ApprovalDecision,
    ChangeItem,
    ChangePriority,
    ChangeState,
    ChangeUrgency,
)
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.catalog import SqlCatalogIndexReader
from datariver.infrastructure.db.change_request_overview import SqlChangeRequestOverviewReader
from datariver.infrastructure.db.classification_access import (
    SqlClassificationAccessSnapshotReader,
)
from datariver.infrastructure.db.governance import SqlGovernanceUnitOfWork
from datariver.infrastructure.db.models.governance import (
    ChangeRequestAttachmentModel,
    ChangeRequestModel,
)
from datariver.interfaces.http.dependencies import ContextDep, SessionDep, get_container
from datariver.interfaces.http.presenters import (
    change_request_response,
    change_request_schema_overview_response,
)
from datariver.interfaces.http.schemas import (
    ApprovalRequest,
    ChangeRequestAttachmentListResponse,
    ChangeRequestAttachmentResponse,
    ChangeRequestCreate,
    ChangeRequestIntakeCreate,
    ChangeRequestListResponse,
    ChangeRequestResponse,
    IntakeCompletionRequest,
    TransitionRequest,
)

router = APIRouter(prefix="/change-requests", tags=["governance"])

_MAXIMUM_ATTACHMENT_BYTES = 10 * 1024 * 1024
_FILE_NAME_DISALLOWED = re.compile(r"[^A-Za-z0-9._-]+")


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
                index=SqlCatalogIndexReader(session),
                classification_access=ClassificationAccessResolver(
                    SqlClassificationAccessSnapshotReader(session)
                ),
                authorization=authorization,
            )
            if session is not None
            else None
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
    context: ContextDep,
    session: SessionDep,
    state: Annotated[str | None, Query(max_length=32)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ChangeRequestListResponse:
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
    )
    return ChangeRequestListResponse(
        items=[change_request_response(value) for value in values],
        overview=[change_request_schema_overview_response(value) for value in overview],
    )


@router.get("/{change_request_id}", response_model=ChangeRequestResponse)
async def get_change_request(
    change_request_id: UUID,
    request: Request,
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
    return change_request_response(value)


def _attachment_response(value: ChangeRequestAttachmentModel) -> ChangeRequestAttachmentResponse:
    return ChangeRequestAttachmentResponse(
        id=value.id,
        kind=value.kind,
        original_name=value.original_name,
        serial_number=value.serial_number,
        content_type=value.content_type,
        size_bytes=value.size_bytes,
        content_sha256=value.content_sha256,
        created_at=value.created_at,
    )


async def _upload_chunks(upload: UploadFile) -> AsyncIterator[bytes]:
    while chunk := await upload.read(1024 * 1024):
        yield chunk


def _safe_attachment_name(name: str | None) -> tuple[str, str, str]:
    candidate = Path(name or "attachment").name
    safe = _FILE_NAME_DISALLOWED.sub("_", candidate).strip("._")[:500]
    if not safe:
        raise ValidationError("The attachment filename is invalid.")
    suffix = Path(safe).suffix[:32]
    stem = Path(safe).stem[: max(1, 460 - len(suffix))]
    return safe, stem, suffix


@router.get("/{change_request_id}/attachments", response_model=ChangeRequestAttachmentListResponse)
async def list_change_request_attachments(
    change_request_id: UUID,
    request: Request,
    context: ContextDep,
    session: SessionDep,
) -> ChangeRequestAttachmentListResponse:
    await _service(request, session).get_change_request(
        workspace_id=context.workspace_id,
        change_request_id=change_request_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    rows = list(
        (
            await session.scalars(
                select(ChangeRequestAttachmentModel)
                .where(
                    ChangeRequestAttachmentModel.workspace_id == context.workspace_id,
                    ChangeRequestAttachmentModel.change_request_id == change_request_id,
                )
                .order_by(ChangeRequestAttachmentModel.created_at, ChangeRequestAttachmentModel.id)
            )
        ).all()
    )
    return ChangeRequestAttachmentListResponse(items=[_attachment_response(row) for row in rows])


@router.post("/{change_request_id}/attachments", response_model=ChangeRequestAttachmentResponse)
async def upload_change_request_attachment(
    change_request_id: UUID,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    kind: Annotated[str, Form(pattern="^(REQUEST|TEST)$")] = "REQUEST",
) -> ChangeRequestAttachmentResponse:
    container = get_container(request)
    bucket = container.settings.s3_bucket_filefolder
    if not bucket:
        raise ValidationError(
            "Change-request attachment storage is not configured.",
            details={"code": "FILEFOLDER_BUCKET_NOT_CONFIGURED"},
        )
    change_request = await _service(request, session).authorize_attachment(
        workspace_id=context.workspace_id,
        change_request_id=change_request_id,
        kind=kind,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    original_name, stem, suffix = _safe_attachment_name(file.filename)
    locked = (
        await session.scalars(
            select(ChangeRequestModel)
            .where(
                ChangeRequestModel.workspace_id == context.workspace_id,
                ChangeRequestModel.id == change_request_id,
            )
            .with_for_update()
        )
    ).one_or_none()
    if locked is None:
        raise NotFoundError("The change request does not exist.")
    serial = (
        int(
            await session.scalar(
                select(
                    func.coalesce(func.max(ChangeRequestAttachmentModel.serial_number), 0)
                ).where(
                    ChangeRequestAttachmentModel.workspace_id == context.workspace_id,
                    ChangeRequestAttachmentModel.change_request_id == change_request_id,
                    ChangeRequestAttachmentModel.kind == kind,
                    ChangeRequestAttachmentModel.original_name == original_name,
                )
            )
            or 0
        )
        + 1
    )
    object_key = f"{change_request.number}-{kind}-{stem}-{serial:02d}{suffix}"
    content_type = (file.content_type or "application/octet-stream")[:255]
    artifact = await container.object_store.write_export(
        bucket=bucket,
        object_key=object_key,
        chunks=_upload_chunks(file),
        metadata={
            "workspace-id": str(context.workspace_id),
            "change-request-id": str(change_request_id),
            "attachment-kind": kind,
        },
        maximum_bytes=_MAXIMUM_ATTACHMENT_BYTES,
        content_type=content_type,
    )
    try:
        row = ChangeRequestAttachmentModel(
            id=uuid7(),
            workspace_id=context.workspace_id,
            change_request_id=change_request_id,
            kind=kind,
            original_name=original_name,
            serial_number=serial,
            bucket=bucket,
            object_key=object_key,
            content_type=content_type,
            size_bytes=artifact.size_bytes,
            content_sha256=artifact.content_sha256,
            uploaded_by=context.subject.subject_id,
        )
        session.add(row)
        await session.commit()
    except Exception:
        await container.object_store.delete_export(bucket=bucket, object_key=object_key)
        raise
    return _attachment_response(row)


@router.get("/{change_request_id}/attachments/{attachment_id}/download")
async def download_change_request_attachment(
    change_request_id: UUID,
    attachment_id: UUID,
    request: Request,
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
                "tags": _unique_values(target.tags),
                "terms": _unique_values(target.terms),
                "columns": [
                    {
                        "field_path": column.field_path.strip(),
                        "data_type": column.data_type.strip(),
                        "description": column.description.strip(),
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
        number=change_request_number(payload.system_name),
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
