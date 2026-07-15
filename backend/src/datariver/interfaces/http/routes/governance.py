from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

import orjson
from fastapi import APIRouter, Header, Query, Request

from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.governance import GovernanceService
from datariver.domain.authz import Classification
from datariver.domain.common import ValidationError, canonical_json_hash, uuid7
from datariver.domain.governance import ApprovalDecision, ChangeItem, ChangeState
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.governance import SqlGovernanceUnitOfWork
from datariver.interfaces.http.dependencies import ContextDep, get_container
from datariver.interfaces.http.presenters import change_request_response
from datariver.interfaces.http.schemas import (
    ApprovalRequest,
    ChangeRequestCreate,
    ChangeRequestListResponse,
    ChangeRequestResponse,
    TransitionRequest,
)

router = APIRouter(prefix="/change-requests", tags=["governance"])


def _service(request: Request) -> GovernanceService:
    container = get_container(request)
    authorization = AuthorizationService(
        decision_writer=SqlDecisionWriter(container.database.session_factory)
    )
    return GovernanceService(
        lambda: SqlGovernanceUnitOfWork(container.database.session_factory), authorization
    )


def _expected_version(if_match: str) -> int:
    value = if_match.strip().strip('"')
    if not value.isdigit() or int(value) < 1:
        raise ValidationError("If-Match must contain a quoted positive aggregate version.")
    return int(value)


@router.get("", response_model=ChangeRequestListResponse)
async def list_change_requests(
    request: Request,
    context: ContextDep,
    state: Annotated[str | None, Query(max_length=32)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ChangeRequestListResponse:
    try:
        parsed_state = ChangeState(state) if state else None
    except ValueError as error:
        raise ValidationError("The change-request state filter is invalid.") from error
    values = await _service(request).list_change_requests(
        workspace_id=context.workspace_id,
        state=parsed_state,
        limit=limit,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return ChangeRequestListResponse(items=[change_request_response(value) for value in values])


@router.get("/{change_request_id}", response_model=ChangeRequestResponse)
async def get_change_request(
    change_request_id: UUID,
    request: Request,
    context: ContextDep,
) -> ChangeRequestResponse:
    value = await _service(request).get_change_request(
        workspace_id=context.workspace_id,
        change_request_id=change_request_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return change_request_response(value)


@router.post("", status_code=201, response_model=ChangeRequestResponse)
async def create_change_request(
    payload: ChangeRequestCreate,
    request: Request,
    context: ContextDep,
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
    number = f"CR-{datetime.now(UTC):%Y}-{uuid7().hex[:12].upper()}"
    change_request = await _service(request).create_change_request(
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
    )
    return change_request_response(change_request)


@router.post("/{change_request_id}/approvals", response_model=ChangeRequestResponse)
async def add_approval(
    change_request_id: UUID,
    payload: ApprovalRequest,
    request: Request,
    context: ContextDep,
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
    change_request = await _service(request).add_approval(
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
    change_request = await _service(request).transition(
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
