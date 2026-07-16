from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response

from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.retention import RetentionGovernanceService
from datariver.domain.common import ValidationError, canonical_json_hash
from datariver.domain.retention import (
    LegalHoldState,
    RetentionPolicyState,
    RetentionRules,
)
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.retention import SqlRetentionUnitOfWork
from datariver.interfaces.http.dependencies import ContextDep, get_container
from datariver.interfaces.http.retention_presenters import (
    legal_hold_response,
    retention_policy_response,
)
from datariver.interfaces.http.retention_schemas import (
    GovernanceDecisionRequest,
    LegalHoldListResponse,
    LegalHoldPlaceRequest,
    LegalHoldReleaseRequest,
    LegalHoldResponse,
    RetentionPolicyListResponse,
    RetentionPolicyProposalRequest,
    RetentionPolicyResponse,
)

router = APIRouter(prefix="/admin/retention", tags=["retention-governance"])


def _service(request: Request) -> RetentionGovernanceService:
    container = get_container(request)
    return RetentionGovernanceService(
        lambda: SqlRetentionUnitOfWork(container.database.session_factory),
        AuthorizationService(decision_writer=SqlDecisionWriter(container.database.session_factory)),
    )


def _expected_version(if_match: str) -> int:
    value = if_match.strip().strip('"')
    if not value.isdigit() or int(value) < 1:
        raise ValidationError("If-Match must contain a quoted positive version.")
    return int(value)


@router.get("/policies", response_model=RetentionPolicyListResponse)
async def list_retention_policies(
    request: Request,
    context: ContextDep,
    state: RetentionPolicyState | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> RetentionPolicyListResponse:
    values = await _service(request).list_policies(
        workspace_id=context.workspace_id,
        state=state,
        limit=limit,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return RetentionPolicyListResponse(items=[retention_policy_response(value) for value in values])


@router.get("/policies/current", response_model=RetentionPolicyResponse | None)
async def get_active_retention_policy(
    request: Request,
    response: Response,
    context: ContextDep,
) -> RetentionPolicyResponse | None:
    value = await _service(request).get_active_policy(
        workspace_id=context.workspace_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if value is None:
        return None
    response.headers["ETag"] = f'"{value.version}"'
    return retention_policy_response(value)


@router.post("/policies", status_code=201, response_model=RetentionPolicyResponse)
async def propose_retention_policy(
    payload: RetentionPolicyProposalRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> RetentionPolicyResponse:
    rules = RetentionRules(**payload.rules.model_dump())
    request_hash = canonical_json_hash(
        {
            "operation": "retention.policy.propose",
            "rules": rules.document(),
            "reason": payload.reason,
        }
    )
    value = await _service(request).propose_policy(
        workspace_id=context.workspace_id,
        rules=rules,
        reason=payload.reason,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    response.headers["ETag"] = f'"{value.version}"'
    return retention_policy_response(value)


@router.post(
    "/policies/{policy_id}/decisions",
    response_model=RetentionPolicyResponse,
)
async def decide_retention_policy(
    policy_id: UUID,
    payload: GovernanceDecisionRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> RetentionPolicyResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "operation": "retention.policy.decide",
            "policy_id": str(policy_id),
            "decision": payload.decision.value,
            "reason": payload.reason,
            "expected_version": expected_version,
        }
    )
    value = await _service(request).decide_policy(
        workspace_id=context.workspace_id,
        policy_id=policy_id,
        governance_decision=payload.decision,
        reason=payload.reason,
        expected_version=expected_version,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    response.headers["ETag"] = f'"{value.version}"'
    return retention_policy_response(value)


@router.get("/legal-holds", response_model=LegalHoldListResponse)
async def list_legal_holds(
    request: Request,
    context: ContextDep,
    state: LegalHoldState | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> LegalHoldListResponse:
    values = await _service(request).list_legal_holds(
        workspace_id=context.workspace_id,
        state=state,
        limit=limit,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return LegalHoldListResponse(items=[legal_hold_response(value) for value in values])


@router.post("/legal-holds", status_code=201, response_model=LegalHoldResponse)
async def place_legal_hold(
    payload: LegalHoldPlaceRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> LegalHoldResponse:
    request_hash = canonical_json_hash(
        {
            "operation": "retention.legal_hold.place",
            "data_class": payload.data_class.value,
            "scope": payload.scope.value,
            "scope_id": str(payload.scope_id) if payload.scope_id else None,
            "reason": payload.reason,
        }
    )
    value = await _service(request).place_legal_hold(
        workspace_id=context.workspace_id,
        data_class=payload.data_class,
        scope=payload.scope,
        scope_id=payload.scope_id,
        reason=payload.reason,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    response.headers["ETag"] = f'"{value.version}"'
    return legal_hold_response(value)


@router.post(
    "/legal-holds/{hold_id}/release-requests",
    response_model=LegalHoldResponse,
)
async def request_legal_hold_release(
    hold_id: UUID,
    payload: LegalHoldReleaseRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> LegalHoldResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "operation": "retention.legal_hold.release_request",
            "hold_id": str(hold_id),
            "reason": payload.reason,
            "expected_version": expected_version,
        }
    )
    value = await _service(request).request_legal_hold_release(
        workspace_id=context.workspace_id,
        hold_id=hold_id,
        reason=payload.reason,
        expected_version=expected_version,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    response.headers["ETag"] = f'"{value.version}"'
    return legal_hold_response(value)


@router.post(
    "/legal-holds/{hold_id}/release-decisions",
    response_model=LegalHoldResponse,
)
async def decide_legal_hold_release(
    hold_id: UUID,
    payload: GovernanceDecisionRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> LegalHoldResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "operation": "retention.legal_hold.release_decision",
            "hold_id": str(hold_id),
            "decision": payload.decision.value,
            "reason": payload.reason,
            "expected_version": expected_version,
        }
    )
    value = await _service(request).decide_legal_hold_release(
        workspace_id=context.workspace_id,
        hold_id=hold_id,
        governance_decision=payload.decision,
        reason=payload.reason,
        expected_version=expected_version,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    response.headers["ETag"] = f'"{value.version}"'
    return legal_hold_response(value)
