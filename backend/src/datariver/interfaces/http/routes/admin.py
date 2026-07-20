from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Annotated, Any
from uuid import UUID

import yaml  # type: ignore[import-untyped]
from fastapi import APIRouter, Header, Query, Request, Response
from sqlalchemy import select

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
from datariver.domain.common import (
    ConflictError,
    ForbiddenError,
    ValidationError,
    canonical_json_hash,
)
from datariver.infrastructure.db.admin_access import SqlAdminAccessUnitOfWork
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.models.platform import ExternalServiceProfileModel
from datariver.infrastructure.db.rls import set_security_context
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
    SystemConfigurationUpdateRequest,
    SystemDirectoryEntryResponse,
    SystemDirectoryListResponse,
    WorkspaceMembershipAccessResponse,
    WorkspaceMembershipListResponse,
)

router = APIRouter(prefix="/admin", tags=["administration"])


_SYSTEM_CONFIGURATION = (
    ("DATAHUB_GMS", "DATAHUB", "DataHub GMS"),
    ("DATAHUB_FRONTEND", "DATAHUB_FRONTEND", "DataHub Frontend"),
    ("AIRFLOW", "AIRFLOW", "Airflow"),
    ("S3_STORAGE", "S3_STORAGE", "S3 Storage"),
    ("LLM_CHAT_MODEL", "LLM_CHAT_MODEL", "LLM · Chat model"),
    ("LLM_EMBEDDING", "LLM_EMBEDDING", "LLM · Embedding"),
    ("LLM_RERANKER", "LLM_RERANKER", "LLM · Reranker"),
    ("NEO4J", "NEO4J", "Neo4j"),
    ("PROMETHEUS", "PROMETHEUS", "Prometheus"),
    ("GRAFANA_DASHBOARD", "GRAFANA_DASHBOARD", "Grafana Dashboard"),
)
_CONFIGURATION_BY_ID = {
    system_id: (service_key, label)
    for system_id, service_key, label in _SYSTEM_CONFIGURATION
}
_SENSITIVE_CONFIGURATION_KEY = re.compile(
    r"(?:password|secret|token|api[_-]?key|private[_-]?key)", re.IGNORECASE
)
_MASKED_VALUE = "********"


def _yaml_document(value: str) -> dict[str, Any]:
    try:
        document = yaml.safe_load(value)
    except yaml.YAMLError as error:
        raise ValidationError("System configuration must be valid YAML.") from error
    if not isinstance(document, dict):
        raise ValidationError("System configuration YAML must contain one mapping document.")
    return dict(document)


def _mask_configuration(value: object, *, key: str = "") -> object:
    if _SENSITIVE_CONFIGURATION_KEY.search(key):
        return _MASKED_VALUE
    if isinstance(value, Mapping):
        return {
            str(item_key): _mask_configuration(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_mask_configuration(item, key=key) for item in value]
    return value


def _merge_masked_configuration(incoming: object, current: object, *, key: str = "") -> object:
    if _SENSITIVE_CONFIGURATION_KEY.search(key) and incoming == _MASKED_VALUE:
        return current
    if isinstance(incoming, Mapping):
        previous = current if isinstance(current, Mapping) else {}
        return {
            str(item_key): _merge_masked_configuration(
                item_value, previous.get(item_key), key=str(item_key)
            )
            for item_key, item_value in incoming.items()
        }
    if isinstance(incoming, list):
        previous_items = current if isinstance(current, list) else []
        return [
            _merge_masked_configuration(
                item,
                previous_items[index] if index < len(previous_items) else None,
                key=key,
            )
            for index, item in enumerate(incoming)
        ]
    return incoming


def _render_yaml(document: object) -> str:
    return str(
        yaml.safe_dump(
            document,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=True,
        )
    )


def _configuration_endpoint(document: Mapping[str, Any]) -> str | None:
    for key in ("url", "endpoint", "base_url"):
        value = document.get(key)
        if isinstance(value, str) and value.strip():
            if not value.strip().startswith(("http://", "https://")):
                raise ValidationError("System configuration URL values must use HTTP or HTTPS.")
            return value.strip()
    return None


def _system_configuration_entries(
    settings: Settings, profiles: Mapping[str, ExternalServiceProfileModel] = {}
) -> list[SystemConfigurationEntryResponse]:
    development = settings.app_env == "development"
    entries: list[SystemConfigurationEntryResponse] = []
    for system_id, service_key, label in _SYSTEM_CONFIGURATION:
        profile = profiles.get(service_key)
        configured = profile is not None and profile.active
        if development:
            state = "CONFIGURED" if configured else "NOT_CONFIGURED"
            if system_id == "GRAFANA_DASHBOARD":
                embedding_state = "AVAILABLE" if configured else "NOT_CONFIGURED"
            else:
                embedding_state = "NOT_APPLICABLE"
            management_plane = "DEVELOPMENT_DATABASE"
        else:
            static_configured = {
                "DATAHUB_GMS": True,
                "DATAHUB_FRONTEND": settings.ui_datahub_url is not None,
                "AIRFLOW": settings.ui_airflow_url is not None,
                "S3_STORAGE": True,
                "PROMETHEUS": settings.ui_prometheus_url is not None,
                "GRAFANA_DASHBOARD": settings.ui_grafana_url is not None,
            }.get(system_id, False)
            if static_configured:
                state = "CONFIGURED"
            elif system_id.startswith("LLM_"):
                state = "GOVERNED_PROFILE_REQUIRED"
            else:
                state = "NOT_CONFIGURED"
            if system_id == "GRAFANA_DASHBOARD":
                embedding_state = (
                    "AVAILABLE"
                    if settings.grafana_embed_url() is not None
                    else "NOT_CONFIGURED"
                )
            else:
                embedding_state = "NOT_APPLICABLE"
            management_plane = (
                "GOVERNED_PROVIDER_PROFILE" if system_id.startswith("LLM_") else "DEPLOYMENT"
            )
        configuration_yaml = ""
        if development and profile and profile.configuration_yaml:
            configuration_yaml = _render_yaml(
                _mask_configuration(_yaml_document(profile.configuration_yaml))
            )
        secret_reference_configured = (
            bool(profile and profile.secret_reference)
            if development
            else system_id == "DATAHUB_GMS" and bool(settings.datahub_secret_ref)
        )
        entries.append(SystemConfigurationEntryResponse(
            system_id=system_id,
            label=label,
            state=state,
            management_plane=management_plane,
            secret_reference_configured=secret_reference_configured,
            embedding_state=embedding_state,
            configuration_yaml=configuration_yaml,
            version=profile.version if profile else 0,
            configured_at=profile.updated_at if profile else None,
        ))
    return entries


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
        development_system_configuration_enabled=container.settings.app_env == "development",
    )


def _expected_version(if_match: str) -> int:
    value = if_match.strip().strip('"')
    if not value.isdigit() or int(value) < 1:
        raise ValidationError("If-Match must contain a quoted positive version.")
    return int(value)


def _expected_configuration_version(if_match: str) -> int:
    value = if_match.strip().strip('"')
    if not value.isdigit():
        raise ValidationError("If-Match must contain a non-negative configuration version.")
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
    admin_context = await _service(request).get_admin_read_context(
        workspace_id=context.workspace_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if "SYSTEM_CONFIGURATION_READ" not in admin_context.allowed_operations:
        raise ForbiddenError("System configuration access is not available for this administrator.")
    container = get_container(request)
    profiles: dict[str, ExternalServiceProfileModel] = {}
    if container.settings.app_env == "development":
        async with container.database.session_factory() as session:
            async with session.begin():
                await set_security_context(
                    session,
                    workspace_id=context.workspace_id,
                    subject_id=context.subject.subject_id,
                )
                profiles = {
                    profile.service_key: profile
                    for profile in (
                        await session.scalars(
                            select(ExternalServiceProfileModel).where(
                                ExternalServiceProfileModel.workspace_id == context.workspace_id
                            )
                        )
                    ).all()
                }
    return SystemConfigurationListResponse(
        items=_system_configuration_entries(container.settings, profiles)
    )


@router.put(
    "/system-configuration/{system_id}",
    response_model=SystemConfigurationEntryResponse,
    responses={
        200: {
            "headers": {
                "ETag": {
                    "description": "Quoted configuration version after the update.",
                    "schema": {"type": "string"},
                }
            }
        }
    },
)
async def update_system_configuration(
    system_id: str,
    payload: SystemConfigurationUpdateRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
) -> SystemConfigurationEntryResponse:
    container = get_container(request)
    if container.settings.app_env != "development":
        raise ForbiddenError(
            "Database-backed system configuration is available only in development."
        )
    expected_version = _expected_configuration_version(if_match)
    if system_id not in _CONFIGURATION_BY_ID:
        raise ValidationError("The system configuration identifier is invalid.")
    admin_context = await _service(request).get_admin_read_context(
        workspace_id=context.workspace_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if "SYSTEM_CONFIGURATION_UPDATE" not in admin_context.allowed_operations:
        raise ForbiddenError("System configuration update is not available for this administrator.")
    service_key, label = _CONFIGURATION_BY_ID[system_id]
    submitted = _yaml_document(payload.configuration_yaml)
    profile: ExternalServiceProfileModel | None
    async with container.database.session_factory() as session:
        async with session.begin():
            await set_security_context(
                session, workspace_id=context.workspace_id, subject_id=context.subject.subject_id
            )
            profile = (
                await session.scalars(
                    select(ExternalServiceProfileModel)
                    .where(
                        ExternalServiceProfileModel.workspace_id == context.workspace_id,
                        ExternalServiceProfileModel.service_key == service_key,
                    )
                    .with_for_update()
                )
            ).one_or_none()
            current = (
                _yaml_document(profile.configuration_yaml)
                if profile and profile.configuration_yaml
                else {}
            )
            merged = _merge_masked_configuration(submitted, current)
            if not isinstance(merged, Mapping):
                raise ValidationError(
                    "System configuration YAML must contain one mapping document."
                )
            endpoint = _configuration_endpoint(merged)
            if profile is None:
                if expected_version != 0:
                    raise ConflictError("The system configuration was created by another request.")
                profile = ExternalServiceProfileModel(
                    workspace_id=context.workspace_id,
                    service_key=service_key,
                    display_name=label,
                    endpoint_url=endpoint,
                    auth_principal=None,
                    secret_reference=None,
                    configuration_yaml=_render_yaml(merged),
                    active=True,
                    updated_by=context.subject.subject_id,
                )
                session.add(profile)
            else:
                if profile.version != expected_version:
                    raise ConflictError("The system configuration was modified by another request.")
                profile.endpoint_url = endpoint
                profile.configuration_yaml = _render_yaml(merged)
                profile.active = True
                profile.updated_by = context.subject.subject_id
                profile.version += 1
            await session.flush()
            assert profile is not None
            saved_version = profile.version
            saved_at = profile.updated_at
            saved_yaml = _render_yaml(_mask_configuration(merged))
    response.headers["ETag"] = f'"{saved_version}"'
    return SystemConfigurationEntryResponse(
        system_id=system_id,
        label=label,
        state="CONFIGURED",
        management_plane="DEVELOPMENT_DATABASE",
        secret_reference_configured=False,
        embedding_state="AVAILABLE" if system_id == "GRAFANA_DASHBOARD" else "NOT_APPLICABLE",
        configuration_yaml=saved_yaml,
        version=saved_version,
        configured_at=saved_at,
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
