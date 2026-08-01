from __future__ import annotations

import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response

from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.classification_access_admin import (
    ClassificationAccessAdminService,
)
from datariver.domain.authz import Classification
from datariver.domain.classification_access import (
    ClassificationAccessPolicyState,
    ClassificationAccessRule,
    RestrictedSearchGrantState,
)
from datariver.domain.common import ValidationError, canonical_json_hash
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.classification_access import (
    SqlClassificationAccessAdminUnitOfWork,
)
from datariver.interfaces.http.classification_access_presenters import (
    classification_policy_response,
    classification_policy_summary_response,
    restricted_search_grant_response,
)
from datariver.interfaces.http.classification_access_schemas import (
    ClassificationPolicyListResponse,
    ClassificationPolicyProposalRequest,
    ClassificationPolicyResponse,
    ClassificationPolicySummaryResponse,
    GovernanceDecisionRequest,
    RestrictedSearchGrantListResponse,
    RestrictedSearchGrantProposalRequest,
    RestrictedSearchGrantResponse,
    RevocationRequest,
)
from datariver.interfaces.http.dependencies import ContextDep, get_container
from datariver.interfaces.http.schemas import PageMeta

router = APIRouter(
    prefix="/admin/classification-access",
    tags=["classification-access-governance"],
)


def _service(request: Request) -> ClassificationAccessAdminService:
    container = get_container(request)
    return ClassificationAccessAdminService(
        lambda: SqlClassificationAccessAdminUnitOfWork(container.database.session_factory),
        AuthorizationService(
            decision_writer=SqlDecisionWriter(container.database.session_factory),
            development_admin_password_bypass_enabled=(
                container.settings.development_admin_password_bypass_enabled
            ),
        ),
    )


def _expected_version(if_match: str) -> int:
    match = re.fullmatch(r'"([1-9][0-9]*)"', if_match.strip())
    if match is None:
        raise ValidationError("If-Match must contain a quoted positive version.")
    return int(match.group(1))


@router.get("/policies", response_model=ClassificationPolicyListResponse)
async def list_classification_policies(
    request: Request,
    context: ContextDep,
    state: ClassificationAccessPolicyState | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=2000)] = None,
) -> ClassificationPolicyListResponse:
    page = await _service(request).list_policies(
        workspace_id=context.workspace_id,
        state=state,
        limit=limit,
        cursor=cursor,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return ClassificationPolicyListResponse(
        items=[classification_policy_response(value) for value in page.items],
        page=PageMeta(next_cursor=page.next_cursor, limit=limit),
    )


@router.get("/policies/current", response_model=ClassificationPolicyResponse | None)
async def get_current_classification_policy(
    request: Request,
    response: Response,
    context: ContextDep,
) -> ClassificationPolicyResponse | None:
    value = await _service(request).current_policy(
        workspace_id=context.workspace_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if value is None:
        return None
    response.headers["ETag"] = f'"{value.version}"'
    return classification_policy_response(value)


@router.get(
    "/policies/current/summary",
    response_model=ClassificationPolicySummaryResponse,
)
async def get_current_classification_policy_summary(
    request: Request,
    response: Response,
    context: ContextDep,
) -> ClassificationPolicySummaryResponse:
    response.headers["Cache-Control"] = "private, no-store"
    value = await _service(request).current_policy_summary(
        workspace_id=context.workspace_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return classification_policy_summary_response(value)


@router.get("/policies/{policy_id}", response_model=ClassificationPolicyResponse)
async def get_classification_policy(
    policy_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
) -> ClassificationPolicyResponse:
    value = await _service(request).get_policy(
        workspace_id=context.workspace_id,
        policy_id=policy_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["ETag"] = f'"{value.version}"'
    return classification_policy_response(value)


@router.post("/policies", status_code=201, response_model=ClassificationPolicyResponse)
async def propose_classification_policy(
    payload: ClassificationPolicyProposalRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> ClassificationPolicyResponse:
    rules = tuple(
        ClassificationAccessRule(
            classification=Classification[rule.classification],
            search_mode=rule.search_mode,
            chat_mode=rule.chat_mode,
            provider_profile_version_id=rule.provider_profile_version_id,
            embedding_provider_profile_version_id=(rule.embedding_provider_profile_version_id),
            reranker_provider_profile_version_id=rule.reranker_provider_profile_version_id,
        )
        for rule in payload.rules
    )
    request_hash = canonical_json_hash(
        {
            "operation": "classification_access.policy.propose",
            "required_jurisdiction": payload.required_jurisdiction,
            "restricted_search_grant_maximum_days": (payload.restricted_search_grant_maximum_days),
            "rules": [rule.document() for rule in rules],
            "reason": payload.reason,
        }
    )
    value = await _service(request).propose_policy(
        workspace_id=context.workspace_id,
        required_jurisdiction=payload.required_jurisdiction,
        restricted_search_grant_maximum_days=(payload.restricted_search_grant_maximum_days),
        rules=rules,
        reason=payload.reason,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    response.headers["ETag"] = f'"{value.version}"'
    return classification_policy_response(value)


@router.post(
    "/policies/{policy_id}/decisions",
    response_model=ClassificationPolicyResponse,
)
async def decide_classification_policy(
    policy_id: UUID,
    payload: GovernanceDecisionRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> ClassificationPolicyResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "operation": "classification_access.policy.decide",
            "policy_id": str(policy_id),
            "decision": payload.decision,
            "reason": payload.reason,
            "expected_version": expected_version,
        }
    )
    service = _service(request)
    method = service.approve_policy if payload.decision == "APPROVED" else service.reject_policy
    value = await method(
        workspace_id=context.workspace_id,
        policy_id=policy_id,
        reason=payload.reason,
        expected_version=expected_version,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    response.headers["ETag"] = f'"{value.version}"'
    return classification_policy_response(value)


@router.get(
    "/restricted-search-grants",
    response_model=RestrictedSearchGrantListResponse,
)
async def list_restricted_search_grants(
    request: Request,
    context: ContextDep,
    state: RestrictedSearchGrantState | None = None,
    subject_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=2000)] = None,
) -> RestrictedSearchGrantListResponse:
    page = await _service(request).list_grants(
        workspace_id=context.workspace_id,
        target_subject_id=subject_id,
        state=state,
        limit=limit,
        cursor=cursor,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return RestrictedSearchGrantListResponse(
        items=[restricted_search_grant_response(value) for value in page.items],
        page=PageMeta(next_cursor=page.next_cursor, limit=limit),
    )


@router.get(
    "/restricted-search-grants/{grant_id}",
    response_model=RestrictedSearchGrantResponse,
)
async def get_restricted_search_grant(
    grant_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
) -> RestrictedSearchGrantResponse:
    value = await _service(request).get_grant(
        workspace_id=context.workspace_id,
        grant_id=grant_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["ETag"] = f'"{value.version}"'
    return restricted_search_grant_response(value)


@router.post(
    "/restricted-search-grants",
    status_code=201,
    response_model=RestrictedSearchGrantResponse,
)
async def propose_restricted_search_grant(
    payload: RestrictedSearchGrantProposalRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> RestrictedSearchGrantResponse:
    request_hash = canonical_json_hash(
        {
            "operation": "classification_access.grant.propose",
            "subject_id": str(payload.subject_id),
            "scope": payload.scope.value,
            "scope_id": str(payload.scope_id),
            "purpose": payload.purpose,
            "valid_from": payload.valid_from.isoformat(),
            "expires_at": payload.expires_at.isoformat(),
            "reason": payload.reason,
        }
    )
    value = await _service(request).propose_grant(
        workspace_id=context.workspace_id,
        target_subject_id=payload.subject_id,
        scope=payload.scope,
        scope_id=payload.scope_id,
        purpose=payload.purpose,
        valid_from=payload.valid_from,
        expires_at=payload.expires_at,
        reason=payload.reason,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    response.headers["ETag"] = f'"{value.version}"'
    return restricted_search_grant_response(value)


@router.post(
    "/restricted-search-grants/{grant_id}/decisions",
    response_model=RestrictedSearchGrantResponse,
)
async def decide_restricted_search_grant(
    grant_id: UUID,
    payload: GovernanceDecisionRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> RestrictedSearchGrantResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "operation": "classification_access.grant.decide",
            "grant_id": str(grant_id),
            "decision": payload.decision,
            "reason": payload.reason,
            "expected_version": expected_version,
        }
    )
    service = _service(request)
    method = service.approve_grant if payload.decision == "APPROVED" else service.reject_grant
    value = await method(
        workspace_id=context.workspace_id,
        grant_id=grant_id,
        reason=payload.reason,
        expected_version=expected_version,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    response.headers["ETag"] = f'"{value.version}"'
    return restricted_search_grant_response(value)


@router.post(
    "/restricted-search-grants/{grant_id}/revocations",
    response_model=RestrictedSearchGrantResponse,
)
async def revoke_restricted_search_grant(
    grant_id: UUID,
    payload: RevocationRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> RestrictedSearchGrantResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "operation": "classification_access.grant.revoke",
            "grant_id": str(grant_id),
            "reason": payload.reason,
            "expected_version": expected_version,
        }
    )
    value = await _service(request).revoke_grant(
        workspace_id=context.workspace_id,
        grant_id=grant_id,
        reason=payload.reason,
        expected_version=expected_version,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    response.headers["ETag"] = f'"{value.version}"'
    return restricted_search_grant_response(value)
