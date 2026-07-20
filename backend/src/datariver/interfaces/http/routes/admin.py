from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response

from datariver.application.services.admin_access import AdminAccessService
from datariver.application.services.authorization import AuthorizationService
from datariver.config import Settings
from datariver.domain.admin_access import (
    AdminAccessDecision,
    AdminAccessRequestState,
    MembershipAccessUpdate,
    SystemAssigneeUpdate,
    SystemAssigneeUpdateCommand,
)
from datariver.domain.authz import Action, Classification
from datariver.domain.common import ValidationError, canonical_json_hash
from datariver.infrastructure.db.admin_access import SqlAdminAccessUnitOfWork
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.interfaces.http.dependencies import ContextDep, get_container
from datariver.interfaces.http.presenters import (
    admin_access_request_response,
    admin_read_context_response,
    workspace_membership_access_response,
    workspace_membership_summary_response,
)
from datariver.interfaces.http.schemas import (
    AdminAccessConsumeResponse,
    AdminAccessRequestListResponse,
    AdminAccessRequestResponse,
    AdminFallbackConsumeRequest,
    AdminFallbackCreateRequest,
    AdminFallbackDecisionRequest,
    AdminReadContextResponse,
    MembershipAccessDocumentRequest,
    MembershipAccessUpdateResponse,
    SystemAssigneeUpdateListRequest,
    SystemAssigneeUpdateResponse,
    SystemConfigurationEntryResponse,
    SystemConfigurationListResponse,
    SystemDirectoryEntryResponse,
    SystemDirectoryListResponse,
    WorkspaceMembershipAccessResponse,
    WorkspaceMembershipListResponse,
)

router = APIRouter(prefix="/admin", tags=["administration"])


def _system_configuration_entries(settings: Settings) -> list[SystemConfigurationEntryResponse]:
    """Expose only source/availability flags, never target URLs or secret references."""

    grafana_embed_state = (
        "AVAILABLE"
        if settings.grafana_embed_url() is not None
        else "NOT_CONFIGURED"
        if settings.ui_grafana_url is None
        else "DISABLED"
    )
    return [
        SystemConfigurationEntryResponse(
            system_id="DATAHUB_GMS",
            label="DataHub GMS",
            state="CONFIGURED",
            management_plane="DEPLOYMENT",
            secret_reference_configured=bool(settings.datahub_secret_ref),
            embedding_state="NOT_APPLICABLE",
        ),
        SystemConfigurationEntryResponse(
            system_id="DATAHUB_FRONTEND",
            label="DataHub Frontend",
            state="CONFIGURED" if settings.ui_datahub_url is not None else "NOT_CONFIGURED",
            management_plane="DEPLOYMENT",
            secret_reference_configured=False,
            embedding_state="NOT_APPLICABLE",
        ),
        SystemConfigurationEntryResponse(
            system_id="AIRFLOW",
            label="Airflow",
            state="CONFIGURED" if settings.ui_airflow_url is not None else "NOT_CONFIGURED",
            management_plane="DEPLOYMENT",
            secret_reference_configured=False,
            embedding_state="NOT_APPLICABLE",
        ),
        SystemConfigurationEntryResponse(
            system_id="S3_STORAGE",
            label="S3 Storage",
            state="CONFIGURED",
            management_plane="DEPLOYMENT",
            secret_reference_configured=bool(
                settings.s3_access_key_file and settings.s3_secret_key_file
            ),
            embedding_state="NOT_APPLICABLE",
        ),
        SystemConfigurationEntryResponse(
            system_id="LLM_CHAT_MODEL",
            label="LLM · Chat model",
            state="GOVERNED_PROFILE_REQUIRED",
            management_plane="GOVERNED_PROVIDER_PROFILE",
            secret_reference_configured=False,
            embedding_state="NOT_APPLICABLE",
        ),
        SystemConfigurationEntryResponse(
            system_id="LLM_EMBEDDING",
            label="LLM · Embedding",
            state="GOVERNED_PROFILE_REQUIRED",
            management_plane="GOVERNED_PROVIDER_PROFILE",
            secret_reference_configured=False,
            embedding_state="NOT_APPLICABLE",
        ),
        SystemConfigurationEntryResponse(
            system_id="LLM_RERANKER",
            label="LLM · Reranker",
            state="GOVERNED_PROFILE_REQUIRED",
            management_plane="GOVERNED_PROVIDER_PROFILE",
            secret_reference_configured=False,
            embedding_state="NOT_APPLICABLE",
        ),
        SystemConfigurationEntryResponse(
            system_id="NEO4J",
            label="Neo4j",
            state="NOT_CONFIGURED",
            management_plane="DEPLOYMENT",
            secret_reference_configured=False,
            embedding_state="NOT_APPLICABLE",
        ),
        SystemConfigurationEntryResponse(
            system_id="PROMETHEUS",
            label="Prometheus",
            state="CONFIGURED" if settings.ui_prometheus_url is not None else "NOT_CONFIGURED",
            management_plane="DEPLOYMENT",
            secret_reference_configured=False,
            embedding_state="NOT_APPLICABLE",
        ),
        SystemConfigurationEntryResponse(
            system_id="GRAFANA_DASHBOARD",
            label="Grafana Dashboard",
            state="CONFIGURED" if settings.ui_grafana_url is not None else "NOT_CONFIGURED",
            management_plane="DEPLOYMENT",
            secret_reference_configured=False,
            embedding_state=grafana_embed_state,
        ),
    ]


def _service(request: Request) -> AdminAccessService:
    container = get_container(request)
    authorization = AuthorizationService(
        decision_writer=SqlDecisionWriter(container.database.session_factory)
    )
    return AdminAccessService(
        lambda: SqlAdminAccessUnitOfWork(container.database.session_factory),
        authorization,
        fallback_enabled=container.settings.admin_password_fallback_enabled,
        fallback_ttl_seconds=container.settings.admin_password_fallback_ttl_seconds,
    )


def _expected_version(if_match: str) -> int:
    value = if_match.strip().strip('"')
    if not value.isdigit() or int(value) < 1:
        raise ValidationError("If-Match must contain a quoted positive version.")
    return int(value)


def _membership_command(
    *,
    workspace_id: UUID,
    target_subject_id: UUID,
    expected_membership_version: int,
    access: MembershipAccessDocumentRequest,
) -> MembershipAccessUpdate:
    try:
        return MembershipAccessUpdate(
            workspace_id=workspace_id,
            target_subject_id=target_subject_id,
            expected_membership_version=expected_membership_version,
            active=access.active,
            clearance=Classification[access.clearance],
            groups=frozenset(access.groups),
            allowed_actions=frozenset(Action(value) for value in access.allowed_actions),
            denied_actions=frozenset(Action(value) for value in access.denied_actions),
            allowed_system_ids=frozenset(access.allowed_system_ids),
            allowed_domain_ids=frozenset(access.allowed_domain_ids),
        )
    except (KeyError, ValueError) as error:
        raise ValidationError("The membership access document is invalid.") from error


def _system_assignee_command(
    *,
    workspace_id: UUID,
    system_id: UUID,
    expected_system_version: int,
    payload: SystemAssigneeUpdateListRequest,
) -> SystemAssigneeUpdateCommand:
    try:
        return SystemAssigneeUpdateCommand(
            workspace_id=workspace_id,
            system_id=system_id,
            expected_system_version=expected_system_version,
            assignees=tuple(
                SystemAssigneeUpdate(
                    subject_id=item.subject_id,
                    responsibility=item.responsibility,
                    priority=item.priority,
                )
                for item in payload.assignees
            ),
        )
    except (TypeError, ValueError) as error:
        raise ValidationError("The system-assignee document is invalid.") from error


@router.get("/me", response_model=AdminReadContextResponse)
async def get_admin_context(
    request: Request,
    context: ContextDep,
) -> AdminReadContextResponse:
    value = await _service(request).get_admin_read_context(
        workspace_id=context.workspace_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return admin_read_context_response(value)


@router.get("/workspace-memberships", response_model=WorkspaceMembershipListResponse)
async def list_workspace_memberships(
    request: Request,
    context: ContextDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> WorkspaceMembershipListResponse:
    values = await _service(request).list_workspace_memberships(
        workspace_id=context.workspace_id,
        limit=limit,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return WorkspaceMembershipListResponse(
        items=[workspace_membership_summary_response(value) for value in values]
    )


@router.get("/systems", response_model=SystemDirectoryListResponse)
async def list_systems(
    request: Request,
    context: ContextDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> SystemDirectoryListResponse:
    values = await _service(request).list_systems(
        workspace_id=context.workspace_id,
        limit=limit,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return SystemDirectoryListResponse(
        items=[
            SystemDirectoryEntryResponse(
                system_id=value.system_id,
                code=value.code,
                name=value.name,
                description=value.description,
                active=value.active,
                version=value.version,
                assignees=[
                    {
                        "subject_id": assignee.subject_id,
                        "display_name": assignee.display_name,
                        "responsibility": assignee.responsibility,
                        "priority": assignee.priority,
                        "active": assignee.active,
                    }
                    for assignee in value.assignees
                ],
            )
            for value in values
        ]
    )


@router.put(
    "/systems/{system_id}/assignees",
    response_model=SystemAssigneeUpdateResponse,
    responses={
        200: {
            "headers": {
                "ETag": {
                    "description": "Current system version after the assignment update.",
                    "schema": {"type": "string"},
                }
            }
        }
    },
)
async def update_system_assignees(
    system_id: UUID,
    payload: SystemAssigneeUpdateListRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> SystemAssigneeUpdateResponse:
    command = _system_assignee_command(
        workspace_id=context.workspace_id,
        system_id=system_id,
        expected_system_version=_expected_version(if_match),
        payload=payload,
    )
    request_hash = canonical_json_hash(
        {"operation": "admin.system.assignees.update", "command": command.command_document()}
    )
    system_version = await _service(request).update_system_assignees_with_hardware_key(
        command=command,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    response.headers["ETag"] = f'"{system_version}"'
    return SystemAssigneeUpdateResponse(
        system_id=system_id,
        system_version=system_version,
        payload_hash=command.payload_hash,
    )


@router.get("/system-configuration", response_model=SystemConfigurationListResponse)
async def list_system_configuration(
    request: Request,
    context: ContextDep,
) -> SystemConfigurationListResponse:
    # Reuse the same eligible-human-admin read gate as member/system inventory.
    # Configuration values, endpoints and secret references are intentionally
    # absent from the response; the operator plane owns them.
    await _service(request).get_admin_read_context(
        workspace_id=context.workspace_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return SystemConfigurationListResponse(
        items=_system_configuration_entries(get_container(request).settings)
    )


@router.get(
    "/workspace-memberships/{target_subject_id}/access",
    response_model=WorkspaceMembershipAccessResponse,
    responses={
        200: {
            "headers": {
                "ETag": {
                    "description": "Quoted current workspace membership version.",
                    "schema": {"type": "string"},
                }
            }
        }
    },
)
async def get_workspace_membership_access(
    target_subject_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
) -> WorkspaceMembershipAccessResponse:
    value = await _service(request).get_workspace_membership_access(
        workspace_id=context.workspace_id,
        target_subject_id=target_subject_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["ETag"] = f'"{value.summary.membership_version}"'
    return workspace_membership_access_response(value)


@router.put(
    "/workspace-memberships/{target_subject_id}/access",
    response_model=MembershipAccessUpdateResponse,
)
async def update_membership_access(
    target_subject_id: UUID,
    payload: MembershipAccessDocumentRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> MembershipAccessUpdateResponse:
    command = _membership_command(
        workspace_id=context.workspace_id,
        target_subject_id=target_subject_id,
        expected_membership_version=_expected_version(if_match),
        access=payload,
    )
    request_hash = canonical_json_hash(
        {"operation": "admin.membership.update", "command": command.command_document()}
    )
    membership_version = await _service(request).update_membership_with_hardware_key(
        command=command,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    response.headers["ETag"] = f'"{membership_version}"'
    return MembershipAccessUpdateResponse(
        target_subject_id=target_subject_id,
        membership_version=membership_version,
        payload_hash=command.payload_hash,
    )


@router.get(
    "/fallback/workspace-membership-access-requests",
    response_model=AdminAccessRequestListResponse,
)
async def list_fallback_requests(
    request: Request,
    context: ContextDep,
    state: Annotated[str | None, Query(max_length=20)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AdminAccessRequestListResponse:
    try:
        parsed_state = AdminAccessRequestState(state) if state is not None else None
    except ValueError as error:
        raise ValidationError("The administrator fallback state filter is invalid.") from error
    requests = await _service(request).list_fallback_requests(
        workspace_id=context.workspace_id,
        state=parsed_state,
        limit=limit,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return AdminAccessRequestListResponse(
        items=[admin_access_request_response(value) for value in requests]
    )


@router.post(
    "/fallback/workspace-membership-access-requests",
    status_code=201,
    response_model=AdminAccessRequestResponse,
)
async def create_fallback_request(
    payload: AdminFallbackCreateRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> AdminAccessRequestResponse:
    command = _membership_command(
        workspace_id=context.workspace_id,
        target_subject_id=payload.target_subject_id,
        expected_membership_version=_expected_version(if_match),
        access=payload.access,
    )
    request_hash = canonical_json_hash(
        {
            "operation": "admin.fallback.request",
            "command": command.command_document(),
            "reason": payload.reason,
        }
    )
    value = await _service(request).create_fallback_request(
        command=command,
        reason=payload.reason,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    response.headers["ETag"] = f'"{value.version}"'
    return admin_access_request_response(value)


@router.post(
    "/fallback/workspace-membership-access-requests/{access_request_id}/decisions",
    response_model=AdminAccessRequestResponse,
)
async def decide_fallback_request(
    access_request_id: UUID,
    payload: AdminFallbackDecisionRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> AdminAccessRequestResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "operation": "admin.fallback.decide",
            "access_request_id": str(access_request_id),
            "decision": payload.decision,
            "reason": payload.reason,
            "expected_version": expected_version,
        }
    )
    value = await _service(request).decide_fallback_request(
        workspace_id=context.workspace_id,
        access_request_id=access_request_id,
        approval_decision=AdminAccessDecision(payload.decision),
        reason=payload.reason,
        expected_version=expected_version,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    response.headers["ETag"] = f'"{value.version}"'
    return admin_access_request_response(value)


@router.post(
    "/fallback/workspace-membership-access-requests/{access_request_id}/consume",
    response_model=AdminAccessConsumeResponse,
)
async def consume_fallback_request(
    access_request_id: UUID,
    payload: AdminFallbackConsumeRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> AdminAccessConsumeResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "operation": "admin.fallback.consume",
            "access_request_id": str(access_request_id),
            "confirmed_payload_hash": payload.confirmed_payload_hash,
            "expected_version": expected_version,
        }
    )
    value, membership_version = await _service(request).consume_fallback_request(
        workspace_id=context.workspace_id,
        access_request_id=access_request_id,
        confirmed_payload_hash=payload.confirmed_payload_hash,
        expected_version=expected_version,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    response.headers["ETag"] = f'"{value.version}"'
    return AdminAccessConsumeResponse(
        request=admin_access_request_response(value), membership_version=membership_version
    )
