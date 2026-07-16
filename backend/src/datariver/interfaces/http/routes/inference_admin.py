from __future__ import annotations

import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response

from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.inference_admin import InferenceAdminService
from datariver.domain.common import ValidationError, canonical_json_hash
from datariver.domain.inference_provider import InferenceProviderProfileState
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.inference_uow import SqlInferenceAdminUnitOfWork
from datariver.interfaces.http.classification_access_presenters import (
    inference_provider_profile_response,
)
from datariver.interfaces.http.classification_access_schemas import (
    GovernanceDecisionRequest,
    InferenceProviderProfileListResponse,
    InferenceProviderProfileResponse,
    RevocationRequest,
)
from datariver.interfaces.http.dependencies import ContextDep, get_container

router = APIRouter(prefix="/admin/inference/provider-profiles", tags=["inference-governance"])


def _service(request: Request) -> InferenceAdminService:
    container = get_container(request)
    return InferenceAdminService(
        lambda: SqlInferenceAdminUnitOfWork(container.database.session_factory),
        AuthorizationService(decision_writer=SqlDecisionWriter(container.database.session_factory)),
    )


def _expected_version(if_match: str) -> int:
    match = re.fullmatch(r'"([1-9][0-9]*)"', if_match.strip())
    if match is None:
        raise ValidationError("If-Match must contain a quoted positive version.")
    return int(match.group(1))


@router.get("", response_model=InferenceProviderProfileListResponse)
async def list_provider_profiles(
    request: Request,
    context: ContextDep,
    profile_key: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    state: InferenceProviderProfileState | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> InferenceProviderProfileListResponse:
    values = await _service(request).list_profiles(
        workspace_id=context.workspace_id,
        profile_key=profile_key,
        state=state,
        limit=limit,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return InferenceProviderProfileListResponse(
        items=[inference_provider_profile_response(value) for value in values]
    )


@router.get("/{profile_version_id}", response_model=InferenceProviderProfileResponse)
async def get_provider_profile(
    profile_version_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
) -> InferenceProviderProfileResponse:
    value = await _service(request).get_profile(
        workspace_id=context.workspace_id,
        profile_version_id=profile_version_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["ETag"] = f'"{value.version}"'
    return inference_provider_profile_response(value)


@router.post(
    "/{profile_version_id}/decisions",
    response_model=InferenceProviderProfileResponse,
)
async def decide_provider_profile(
    profile_version_id: UUID,
    payload: GovernanceDecisionRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> InferenceProviderProfileResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "operation": "inference.provider_profile.decide",
            "profile_version_id": str(profile_version_id),
            "decision": payload.decision,
            "reason": payload.reason,
            "expected_version": expected_version,
        }
    )
    method = (
        _service(request).approve_profile
        if payload.decision == "APPROVED"
        else _service(request).reject_profile
    )
    value = await method(
        workspace_id=context.workspace_id,
        profile_version_id=profile_version_id,
        reason=payload.reason,
        expected_version=expected_version,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    response.headers["ETag"] = f'"{value.version}"'
    return inference_provider_profile_response(value)


@router.post(
    "/{profile_version_id}/revocations",
    response_model=InferenceProviderProfileResponse,
)
async def revoke_provider_profile(
    profile_version_id: UUID,
    payload: RevocationRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> InferenceProviderProfileResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "operation": "inference.provider_profile.revoke",
            "profile_version_id": str(profile_version_id),
            "reason": payload.reason,
            "expected_version": expected_version,
        }
    )
    value = await _service(request).revoke_profile(
        workspace_id=context.workspace_id,
        profile_version_id=profile_version_id,
        reason=payload.reason,
        expected_version=expected_version,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    response.headers["ETag"] = f'"{value.version}"'
    return inference_provider_profile_response(value)
