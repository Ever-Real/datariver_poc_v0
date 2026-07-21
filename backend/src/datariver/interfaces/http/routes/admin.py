from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Annotated, Any
from urllib.parse import urlsplit
from uuid import UUID

import yaml  # type: ignore[import-untyped]
from fastapi import APIRouter, Header, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.dto import MembershipRenewalRecord
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
    DomainEvent,
    ForbiddenError,
    ValidationError,
    canonical_json_hash,
    utc_now,
)
from datariver.domain.membership_renewal import (
    MembershipRenewalDecision,
    MembershipRenewalState,
)
from datariver.infrastructure.db.admin_access import SqlAdminAccessUnitOfWork
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.governance import SqlOutboxWriter
from datariver.infrastructure.db.models.platform import (
    AccessRoleModel,
    ExternalServiceProfileModel,
    ExternalServiceProfileVersionModel,
    WorkspaceMembershipModel,
)
from datariver.infrastructure.db.rls import set_security_context
from datariver.infrastructure.secrets import SecretResolver
from datariver.infrastructure.system_configuration_probe import probe_system_configuration
from datariver.interfaces.http.dependencies import ContextDep, get_container
from datariver.interfaces.http.presenters import (
    admin_access_request_response,
    admin_read_context_response,
    workspace_membership_access_response,
    workspace_membership_summary_response,
)
from datariver.interfaces.http.schemas import (
    AccessRoleListResponse,
    AccessRoleResponse,
    AccessRoleWriteRequest,
    AdminAccessConsumeResponse,
    AdminAccessRequestListResponse,
    AdminAccessRequestResponse,
    AdminFallbackConsumeRequest,
    AdminFallbackCreateRequest,
    AdminFallbackDecisionRequest,
    AdminReadContextResponse,
    MembershipAccessDocumentRequest,
    MembershipAccessUpdateResponse,
    MembershipRenewalCreateRequest,
    MembershipRenewalDecisionRequest,
    MembershipRenewalListResponse,
    MembershipRenewalResponse,
    MembershipRoleAssignmentRequest,
    MembershipRoleAssignmentResponse,
    SystemAssigneeUpdateListRequest,
    SystemAssigneeUpdateResponse,
    SystemConfigurationEntryResponse,
    SystemConfigurationListResponse,
    SystemConfigurationTestResponse,
    SystemConfigurationUpdateRequest,
    SystemDirectoryEntryResponse,
    SystemDirectoryListResponse,
    WorkspaceMembershipAccessResponse,
    WorkspaceMembershipListResponse,
    WorkspaceMembershipSummaryResponse,
)

router = APIRouter(prefix="/admin", tags=["administration"])


def _membership_renewal_response(
    value: MembershipRenewalRecord, *, membership_version: int | None = None
) -> MembershipRenewalResponse:
    return MembershipRenewalResponse(
        id=value.renewal_request_id,
        workspace_id=value.workspace_id,
        target_subject_id=value.target_subject_id,
        requester_id=value.requester_id,
        requester_display_name=value.requester_display_name,
        reason=value.reason,
        current_expires_at=value.current_expires_at,
        requested_expires_at=value.requested_expires_at,
        state=value.state,
        version=value.version,
        created_at=value.created_at,
        checker_id=value.checker_id,
        checker_display_name=value.checker_display_name,
        decision_reason=value.decision_reason,
        decided_at=value.decided_at,
        membership_version=membership_version,
    )


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
    system_id: (service_key, label) for system_id, service_key, label in _SYSTEM_CONFIGURATION
}
_RUNTIME_RESTART_SCOPE = {
    "DATAHUB_GMS": "API_AND_WORKERS",
    "DATAHUB_FRONTEND": "API_ONLY",
    "AIRFLOW": "API_ONLY",
    "S3_STORAGE": "API_AND_WORKERS",
    "LLM_CHAT_MODEL": "API_ONLY",
    "LLM_EMBEDDING": "API_AND_WORKERS",
    "NEO4J": "API_AND_WORKERS",
    "PROMETHEUS": "API_ONLY",
    "GRAFANA_DASHBOARD": "API_ONLY",
}
_SYSTEM_CONFIGURATION_TEMPLATES: dict[str, dict[str, Any]] = {
    "DATAHUB_GMS": {
        "base_url": "",
        "secret_references": {"token": "file:/run/secrets/datahub_token"},
        "options": {
            "allowed_versions": [],
            "circuit_failure_threshold": 5,
            "circuit_open_seconds": 30,
            "expected_version": "v1.6.0",
            "maximum_concurrency": 20,
            "queue_timeout_seconds": 2,
            "timeout_seconds": 10,
            "stale_ttl_seconds": 900,
            "version_enforcement": "report",
            "version_probe_ttl_seconds": 300,
        },
    },
    "DATAHUB_FRONTEND": {
        "url": "",
        "options": {"embed_enabled": False},
    },
    "AIRFLOW": {
        "base_url": "",
        "secret_references": {},
        "options": {},
    },
    "S3_STORAGE": {
        "endpoint": "",
        "public_endpoint": "",
        "region": "",
        "buckets": {
            "accepted": "",
            "exports": "",
            "filefolder": "",
            "infoschema": "",
            "quarantine": "",
        },
        "options": {"presigned_url_ttl_seconds": 900},
        "secret_references": {
            "access_key": "file:/run/secrets/s3_access_key",
            "secret_key": "file:/run/secrets/s3_secret_key",
        },
    },
    "LLM_CHAT_MODEL": {
        "connection_mode": "LOCAL_OLLAMA",
        "base_url": "",
        "model": "",
        "secret_references": {},
        "options": {
            "api_style": "openai_compatible",
            "context_tokens": 8192,
            "timeout_seconds": 60,
        },
    },
    "LLM_EMBEDDING": {
        "connection_mode": "LOCAL_OLLAMA",
        "base_url": "",
        "model": "",
        "secret_references": {},
        "options": {"api_style": "openai_compatible", "timeout_seconds": 60},
    },
    "LLM_RERANKER": {
        "base_url": "",
        "model": "",
        "secret_references": {},
        "options": {"api_style": "openai_compatible", "timeout_seconds": 60, "top_n": 10},
    },
    "NEO4J": {
        "database": "neo4j",
        "secret_references": {"credential": "file:/run/secrets/neo4j_auth"},
        "uri": "",
        "options": {"connection_timeout_seconds": 30, "maximum_connection_pool_size": 50},
    },
    "PROMETHEUS": {"base_url": "", "options": {}},
    "GRAFANA_DASHBOARD": {
        "options": {"dashboard_path": "", "embed_enabled": False},
        "url": "",
    },
}
_SENSITIVE_CONFIGURATION_KEY = re.compile(
    r"(?:^|[_-])(?:password|secret|token|api[_-]?key|private[_-]?key)(?:$|[_-])",
    re.IGNORECASE,
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
    if key == "secret_references" and isinstance(value, Mapping):
        return {str(item_key): str(item_value) for item_key, item_value in value.items()}
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


def _display_configuration(value: object, *, key: str = "") -> object:
    """Remove sensitive fields entirely from the administrator summary."""
    if key == "secret_references" and isinstance(value, Mapping):
        return {str(item_key): str(item_value) for item_key, item_value in value.items()}
    if isinstance(value, Mapping):
        return {
            str(item_key): _display_configuration(item_value, key=str(item_key))
            for item_key, item_value in value.items()
            if str(item_key) == "secret_references"
            or not _SENSITIVE_CONFIGURATION_KEY.search(str(item_key))
        }
    if isinstance(value, list):
        return [_display_configuration(item, key=key) for item in value]
    return value


def _secret_references(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValidationError("secret_references must be one mapping.")
    if len(value) > 20:
        raise ValidationError("A system configuration can contain at most 20 secret references.")
    references: dict[str, str] = {}
    for raw_name, raw_reference in value.items():
        name = str(raw_name)
        if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name) is None:
            raise ValidationError("A secret reference name is invalid.")
        if (
            not isinstance(raw_reference, str)
            or re.fullmatch(r"file:/run/secrets/[A-Za-z0-9][A-Za-z0-9._-]{0,127}", raw_reference)
            is None
        ):
            raise ValidationError(
                "Secret references must use file:/run/secrets/<name>; secret values are forbidden."
            )
        references[name] = raw_reference
    return references


def _validate_configuration_submission(
    incoming: object,
    current: object,
    *,
    key: str = "",
) -> None:
    """Reject browser-supplied secrets while allowing an existing masked value to survive."""
    if key == "secret_references":
        _secret_references(incoming)
        return
    if _SENSITIVE_CONFIGURATION_KEY.search(key):
        if incoming != _MASKED_VALUE or current is None:
            raise ValidationError(
                "Sensitive system configuration values must use an operator-managed secret."
            )
        return
    if isinstance(incoming, Mapping):
        previous = current if isinstance(current, Mapping) else {}
        for item_key, item_value in incoming.items():
            _validate_configuration_submission(
                item_value,
                previous.get(item_key),
                key=str(item_key),
            )
        return
    if isinstance(incoming, list):
        previous_items = current if isinstance(current, list) else []
        for index, item in enumerate(incoming):
            _validate_configuration_submission(
                item,
                previous_items[index] if index < len(previous_items) else None,
                key=key,
            )


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
            normalized = value.strip()
            parsed = urlsplit(normalized)
            if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
                raise ValidationError("System configuration URL values must use HTTP or HTTPS.")
            if parsed.username is not None or parsed.password is not None:
                raise ValidationError("Credentials must not be embedded in a system URL.")
            if parsed.query or parsed.fragment:
                raise ValidationError("A system base URL must not contain a query or fragment.")
            return normalized
    return None


def _require_non_empty_string(document: Mapping[str, Any], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"System configuration requires a non-empty {key} value.")
    return value.strip()


def _validate_system_configuration(system_id: str, document: Mapping[str, Any]) -> str | None:
    allowed_top_level = set(_SYSTEM_CONFIGURATION_TEMPLATES[system_id]) | {"auth_principal"}
    unknown_keys = sorted(set(document) - allowed_top_level)
    if unknown_keys:
        raise ValidationError(
            "System configuration contains unsupported top-level keys: " + ", ".join(unknown_keys)
        )
    _secret_references(document.get("secret_references", {}))
    options = document.get("options")
    if not isinstance(options, Mapping):
        raise ValidationError("System configuration options must be one mapping.")
    if system_id == "NEO4J":
        uri = _require_non_empty_string(document, "uri")
        parsed = urlsplit(uri)
        if parsed.scheme not in {"bolt", "neo4j"} or parsed.hostname is None:
            raise ValidationError("Neo4j URI values must use bolt:// or neo4j://.")
        if parsed.username is not None or parsed.password is not None:
            raise ValidationError("Credentials must not be embedded in the Neo4j URI.")
        _require_non_empty_string(document, "database")
        return None
    endpoint = _configuration_endpoint(document)
    if endpoint is None:
        raise ValidationError("System configuration requires one non-empty HTTP endpoint.")
    if system_id.startswith("LLM_"):
        model = _require_non_empty_string(document, "model")
        if len(model) > 128 or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", model) is None:
            raise ValidationError("The LLM model identity is invalid.")
    if system_id in {"LLM_CHAT_MODEL", "LLM_EMBEDDING"}:
        connection_mode = document.get("connection_mode", "LOCAL_OLLAMA")
        if connection_mode not in {"LOCAL_OLLAMA", "INTRANET_OPENAI_COMPATIBLE"}:
            raise ValidationError("The LLM connection mode is invalid.")
        secret_references = _secret_references(document.get("secret_references", {}))
        if connection_mode == "LOCAL_OLLAMA" and secret_references:
            raise ValidationError("Local Ollama does not accept an API-key secret reference.")
        if connection_mode == "INTRANET_OPENAI_COMPATIBLE":
            parsed = urlsplit(endpoint)
            if parsed.scheme != "https" or parsed.path.rstrip("/") != "/v1":
                raise ValidationError(
                    "Intranet OpenAI-compatible LLM configuration requires an HTTPS /v1 endpoint."
                )
            if set(secret_references) != {"api_key"}:
                raise ValidationError(
                    "Intranet OpenAI-compatible LLM configuration requires exactly one "
                    "api_key secret reference."
                )
            options_api_style = options.get("api_style")
            if options_api_style != "openai_compatible":
                raise ValidationError(
                    "Intranet OpenAI-compatible LLM configuration requires "
                    "api_style=openai_compatible."
                )
    if system_id == "S3_STORAGE":
        _require_non_empty_string(document, "region")
        buckets = document.get("buckets")
        if not isinstance(buckets, Mapping):
            raise ValidationError("S3 configuration requires one buckets mapping.")
        for bucket_key in ("accepted", "exports", "quarantine"):
            _require_non_empty_string(buckets, bucket_key)
    return endpoint


def _role_marker(role_key: str) -> str:
    return f"datariver-role-{role_key}"


def _role_document(payload: AccessRoleWriteRequest) -> dict[str, object]:
    return {
        "role_key": payload.role_key,
        "name": payload.name.strip(),
        "description": payload.description.strip(),
        "clearance": payload.clearance,
        "groups": sorted(payload.groups),
        "allowed_actions": sorted(action.value for action in payload.allowed_actions),
        "denied_actions": sorted(action.value for action in payload.denied_actions),
        "allowed_system_ids": sorted(str(value) for value in payload.allowed_system_ids),
        "allowed_domain_ids": sorted(str(value) for value in payload.allowed_domain_ids),
        "active": payload.active,
    }


def _stored_role_document(role: AccessRoleModel) -> dict[str, object]:
    return {
        "role_key": role.role_key,
        "name": role.name,
        "description": role.description,
        "clearance": Classification(role.clearance).name,
        "groups": sorted(role.groups),
        "allowed_actions": sorted(role.allowed_actions),
        "denied_actions": sorted(role.denied_actions),
        "allowed_system_ids": sorted(role.allowed_system_ids),
        "allowed_domain_ids": sorted(role.allowed_domain_ids),
        "active": role.active,
    }


async def _role_assigned_count(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    role_key: str,
) -> int:
    marker = _role_marker(role_key)
    count = await session.scalar(
        select(func.count())
        .select_from(WorkspaceMembershipModel)
        .where(
            WorkspaceMembershipModel.workspace_id == workspace_id,
            WorkspaceMembershipModel.attributes["groups"].contains([marker]),
        )
    )
    return int(count or 0)


def _role_response(role: AccessRoleModel, *, assigned_count: int) -> AccessRoleResponse:
    try:
        return AccessRoleResponse(
            id=role.id,
            role_key=role.role_key,
            name=role.name,
            description=role.description,
            clearance=Classification(role.clearance).name,
            groups=role.groups,
            allowed_actions=[Action(value) for value in role.allowed_actions],
            denied_actions=[Action(value) for value in role.denied_actions],
            allowed_system_ids=[UUID(value) for value in role.allowed_system_ids],
            allowed_domain_ids=[UUID(value) for value in role.allowed_domain_ids],
            active=role.active,
            assigned_count=assigned_count,
            version=role.version,
            created_at=role.created_at,
            updated_at=role.updated_at,
        )
    except (TypeError, ValueError) as error:
        raise ConflictError("The stored access role definition is invalid.") from error


def _apply_role_payload(
    role: AccessRoleModel,
    *,
    payload: AccessRoleWriteRequest,
    updated_by: UUID,
) -> None:
    role.name = payload.name.strip()
    role.description = payload.description.strip()
    role.clearance = int(Classification[payload.clearance])
    role.groups = sorted(payload.groups)
    role.allowed_actions = sorted(action.value for action in payload.allowed_actions)
    role.denied_actions = sorted(action.value for action in payload.denied_actions)
    role.allowed_system_ids = sorted(str(value) for value in payload.allowed_system_ids)
    role.allowed_domain_ids = sorted(str(value) for value in payload.allowed_domain_ids)
    role.active = payload.active
    role.updated_by = updated_by


def _system_configuration_entries(
    settings: Settings,
    profiles: Mapping[str, ExternalServiceProfileModel] = {},
    versions: Mapping[tuple[UUID, int], ExternalServiceProfileVersionModel] = {},
) -> list[SystemConfigurationEntryResponse]:
    development = settings.app_env == "development"
    entries: list[SystemConfigurationEntryResponse] = []
    for system_id, service_key, label in _SYSTEM_CONFIGURATION:
        profile = profiles.get(service_key)
        current_revision = versions.get((profile.id, profile.version)) if profile else None
        activated_revision = (
            versions.get((profile.id, profile.activated_version))
            if profile and profile.activated_version is not None
            else None
        )
        restart_scope = _RUNTIME_RESTART_SCOPE.get(system_id, "NOT_IMPLEMENTED")
        runtime_supported = system_id in _RUNTIME_RESTART_SCOPE
        applied_version = settings.system_configuration_runtime_versions.get(service_key)
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
                    "AVAILABLE" if settings.grafana_embed_url() is not None else "NOT_CONFIGURED"
                )
            else:
                embedding_state = "NOT_APPLICABLE"
            management_plane = (
                "GOVERNED_PROVIDER_PROFILE" if system_id.startswith("LLM_") else "DEPLOYMENT"
            )
        configuration_yaml = ""
        display_yaml = ""
        template_yaml = (
            _render_yaml(_SYSTEM_CONFIGURATION_TEMPLATES[system_id]) if development else ""
        )
        if development and profile and profile.configuration_yaml:
            document = _yaml_document(profile.configuration_yaml)
            configuration_yaml = _render_yaml(_mask_configuration(document))
            display_yaml = _render_yaml(_display_configuration(document))
        secret_reference_configured = (
            bool(profile and profile.secret_reference)
            if development
            else system_id == "DATAHUB_GMS" and bool(settings.datahub_secret_ref)
        )
        if profile is None:
            activation_state = "NOT_CONFIGURED"
        elif not runtime_supported:
            activation_state = "RUNTIME_NOT_IMPLEMENTED"
        elif current_revision is None or current_revision.test_status is None:
            activation_state = "SAVED_UNTESTED"
        elif current_revision.test_status != "AVAILABLE":
            activation_state = "TEST_NOT_AVAILABLE"
        elif profile.activated_version != profile.version:
            activation_state = "TESTED"
        elif applied_version == profile.activated_version:
            activation_state = "APPLIED_TO_API_PROCESS"
        else:
            activation_state = "ACTIVATED_RESTART_REQUIRED"
        entries.append(
            SystemConfigurationEntryResponse(
                system_id=system_id,
                label=label,
                state=state,
                management_plane=management_plane,
                secret_reference_configured=secret_reference_configured,
                embedding_state=embedding_state,
                configuration_yaml=configuration_yaml,
                template_yaml=template_yaml,
                display_yaml=display_yaml,
                version=profile.version if profile else 0,
                configured_at=profile.updated_at if profile else None,
                runtime_supported=runtime_supported,
                restart_scope=restart_scope,
                activation_state=activation_state,
                tested_version=(
                    current_revision.configuration_version
                    if current_revision and current_revision.test_status is not None
                    else None
                ),
                test_status=current_revision.test_status if current_revision else None,
                tested_at=current_revision.tested_at if current_revision else None,
                activated_version=profile.activated_version if profile else None,
                activated_at=activated_revision.activated_at if activated_revision else None,
                applied_version=applied_version,
            )
        )
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


@router.get("/access-roles", response_model=AccessRoleListResponse)
async def list_access_roles(
    request: Request,
    context: ContextDep,
) -> AccessRoleListResponse:
    admin_context = await _service(request).get_admin_read_context(
        workspace_id=context.workspace_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if "MEMBERSHIP_ACCESS_READ" not in admin_context.allowed_operations:
        raise ForbiddenError("Access-role definitions are not available for this administrator.")
    container = get_container(request)
    async with container.database.session_factory() as session:
        async with session.begin():
            await set_security_context(
                session,
                workspace_id=context.workspace_id,
                subject_id=context.subject.subject_id,
            )
            roles = (
                await session.scalars(
                    select(AccessRoleModel)
                    .where(AccessRoleModel.workspace_id == context.workspace_id)
                    .order_by(
                        AccessRoleModel.active.desc(),
                        AccessRoleModel.name,
                        AccessRoleModel.id,
                    )
                    .limit(100)
                )
            ).all()
            items = [
                _role_response(
                    role,
                    assigned_count=await _role_assigned_count(
                        session,
                        workspace_id=context.workspace_id,
                        role_key=role.role_key,
                    ),
                )
                for role in roles
            ]
    return AccessRoleListResponse(items=items)


@router.post("/access-roles", response_model=AccessRoleResponse, status_code=201)
async def create_access_role(
    payload: AccessRoleWriteRequest,
    request: Request,
    context: ContextDep,
) -> AccessRoleResponse:
    admin_context = await _service(request).get_admin_read_context(
        workspace_id=context.workspace_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if "MEMBERSHIP_ACCESS_UPDATE" not in admin_context.allowed_operations:
        raise ForbiddenError("Access-role creation requires current hardware assurance.")
    if not payload.name.strip():
        raise ValidationError("Access-role name must not be blank.")
    container = get_container(request)
    async with container.database.session_factory() as session:
        async with session.begin():
            await set_security_context(
                session,
                workspace_id=context.workspace_id,
                subject_id=context.subject.subject_id,
            )
            count = await session.scalar(
                select(func.count())
                .select_from(AccessRoleModel)
                .where(AccessRoleModel.workspace_id == context.workspace_id)
            )
            if int(count or 0) >= 100:
                raise ValidationError("A workspace can contain at most 100 access roles.")
            existing = (
                await session.scalars(
                    select(AccessRoleModel).where(
                        AccessRoleModel.workspace_id == context.workspace_id,
                        AccessRoleModel.role_key == payload.role_key,
                    )
                )
            ).one_or_none()
            if existing is not None:
                raise ConflictError("The access-role key already exists in this workspace.")
            role = AccessRoleModel(
                workspace_id=context.workspace_id,
                role_key=payload.role_key,
                name=payload.name.strip(),
                description=payload.description.strip(),
                clearance=int(Classification[payload.clearance]),
                groups=sorted(payload.groups),
                allowed_actions=sorted(action.value for action in payload.allowed_actions),
                denied_actions=sorted(action.value for action in payload.denied_actions),
                allowed_system_ids=sorted(str(value) for value in payload.allowed_system_ids),
                allowed_domain_ids=sorted(str(value) for value in payload.allowed_domain_ids),
                active=payload.active,
                updated_by=context.subject.subject_id,
            )
            session.add(role)
            await session.flush()
            await SqlOutboxWriter(session).add_events(
                [
                    DomainEvent.create(
                        event_type="iam.access_role.created.v1",
                        aggregate_type="access_role",
                        aggregate_id=role.id,
                        workspace_id=context.workspace_id,
                        payload={
                            "actor_id": str(context.subject.subject_id),
                            "payload_hash": canonical_json_hash(_role_document(payload)),
                            "role_key": role.role_key,
                            "version": role.version,
                        },
                    )
                ]
            )
            result = _role_response(role, assigned_count=0)
    return result


@router.put("/access-roles/{role_id}", response_model=AccessRoleResponse)
async def update_access_role(
    role_id: UUID,
    payload: AccessRoleWriteRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
) -> AccessRoleResponse:
    admin_context = await _service(request).get_admin_read_context(
        workspace_id=context.workspace_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if "MEMBERSHIP_ACCESS_UPDATE" not in admin_context.allowed_operations:
        raise ForbiddenError("Access-role updates require current hardware assurance.")
    if not payload.name.strip():
        raise ValidationError("Access-role name must not be blank.")
    expected_version = _expected_version(if_match)
    container = get_container(request)
    async with container.database.session_factory() as session:
        async with session.begin():
            await set_security_context(
                session,
                workspace_id=context.workspace_id,
                subject_id=context.subject.subject_id,
            )
            role = (
                await session.scalars(
                    select(AccessRoleModel)
                    .where(
                        AccessRoleModel.workspace_id == context.workspace_id,
                        AccessRoleModel.id == role_id,
                    )
                    .with_for_update()
                )
            ).one_or_none()
            if role is None:
                raise ValidationError("The access role does not exist in this workspace.")
            if role.version != expected_version:
                raise ConflictError("The access role was modified by another request.")
            if role.role_key != payload.role_key:
                raise ValidationError("The access-role key is immutable.")
            assigned_count = await _role_assigned_count(
                session,
                workspace_id=context.workspace_id,
                role_key=role.role_key,
            )
            security_keys = {
                "clearance",
                "groups",
                "allowed_actions",
                "denied_actions",
                "allowed_system_ids",
                "allowed_domain_ids",
                "active",
            }
            current_document = _stored_role_document(role)
            next_document = _role_document(payload)
            if assigned_count and any(
                current_document[key] != next_document[key] for key in security_keys
            ):
                raise ConflictError(
                    "Reassign all users before changing an in-use role security definition."
                )
            _apply_role_payload(role, payload=payload, updated_by=context.subject.subject_id)
            role.version += 1
            await session.flush()
            await SqlOutboxWriter(session).add_events(
                [
                    DomainEvent.create(
                        event_type="iam.access_role.updated.v1",
                        aggregate_type="access_role",
                        aggregate_id=role.id,
                        workspace_id=context.workspace_id,
                        payload={
                            "actor_id": str(context.subject.subject_id),
                            "payload_hash": canonical_json_hash(next_document),
                            "role_key": role.role_key,
                            "version": role.version,
                        },
                    )
                ]
            )
            result = _role_response(role, assigned_count=assigned_count)
    response.headers["ETag"] = f'"{result.version}"'
    return result


@router.delete("/access-roles/{role_id}", response_model=AccessRoleResponse)
async def deactivate_access_role(
    role_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
) -> AccessRoleResponse:
    admin_context = await _service(request).get_admin_read_context(
        workspace_id=context.workspace_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if "MEMBERSHIP_ACCESS_UPDATE" not in admin_context.allowed_operations:
        raise ForbiddenError("Access-role deactivation requires current hardware assurance.")
    expected_version = _expected_version(if_match)
    container = get_container(request)
    async with container.database.session_factory() as session:
        async with session.begin():
            await set_security_context(
                session,
                workspace_id=context.workspace_id,
                subject_id=context.subject.subject_id,
            )
            role = (
                await session.scalars(
                    select(AccessRoleModel)
                    .where(
                        AccessRoleModel.workspace_id == context.workspace_id,
                        AccessRoleModel.id == role_id,
                    )
                    .with_for_update()
                )
            ).one_or_none()
            if role is None:
                raise ValidationError("The access role does not exist in this workspace.")
            if role.version != expected_version:
                raise ConflictError("The access role was modified by another request.")
            assigned_count = await _role_assigned_count(
                session,
                workspace_id=context.workspace_id,
                role_key=role.role_key,
            )
            if assigned_count:
                raise ConflictError("Reassign all users before deactivating an access role.")
            role.active = False
            role.updated_by = context.subject.subject_id
            role.version += 1
            await session.flush()
            await SqlOutboxWriter(session).add_events(
                [
                    DomainEvent.create(
                        event_type="iam.access_role.deactivated.v1",
                        aggregate_type="access_role",
                        aggregate_id=role.id,
                        workspace_id=context.workspace_id,
                        payload={
                            "actor_id": str(context.subject.subject_id),
                            "role_key": role.role_key,
                            "version": role.version,
                        },
                    )
                ]
            )
            result = _role_response(role, assigned_count=0)
    response.headers["ETag"] = f'"{result.version}"'
    return result


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
    versions: dict[tuple[UUID, int], ExternalServiceProfileVersionModel] = {}
    if container.settings.app_env == "development":
        async with container.database.session_factory() as session:
            async with session.begin():
                await set_security_context(
                    session,
                    workspace_id=context.workspace_id,
                    subject_id=context.subject.subject_id,
                )
                profile_items = (
                    await session.scalars(
                        select(ExternalServiceProfileModel).where(
                            ExternalServiceProfileModel.workspace_id == context.workspace_id
                        )
                    )
                ).all()
                profiles = {profile.service_key: profile for profile in profile_items}
                revision_items = (
                    await session.scalars(
                        select(ExternalServiceProfileVersionModel).where(
                            ExternalServiceProfileVersionModel.workspace_id == context.workspace_id
                        )
                    )
                ).all()
                versions = {
                    (revision.profile_id, revision.configuration_version): revision
                    for revision in revision_items
                }
    return SystemConfigurationListResponse(
        items=_system_configuration_entries(container.settings, profiles, versions)
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
    revision: ExternalServiceProfileVersionModel
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
            _validate_configuration_submission(submitted, current)
            merged = _merge_masked_configuration(submitted, current)
            if not isinstance(merged, Mapping):
                raise ValidationError(
                    "System configuration YAML must contain one mapping document."
                )
            endpoint = _validate_system_configuration(system_id, merged)
            rendered_configuration = _render_yaml(merged)
            secret_references = _secret_references(merged.get("secret_references", {}))
            auth_principal = merged.get("auth_principal")
            if auth_principal is not None and (
                not isinstance(auth_principal, str) or not auth_principal.strip()
            ):
                raise ValidationError("auth_principal must be a non-empty string when supplied.")
            if profile is None:
                if expected_version != 0:
                    raise ConflictError("The system configuration was created by another request.")
                profile = ExternalServiceProfileModel(
                    workspace_id=context.workspace_id,
                    service_key=service_key,
                    display_name=label,
                    endpoint_url=endpoint,
                    auth_principal=auth_principal.strip()
                    if isinstance(auth_principal, str)
                    else None,
                    secret_reference=(
                        "configuration_yaml:secret_references" if secret_references else None
                    ),
                    configuration_yaml=rendered_configuration,
                    active=True,
                    activated_version=None,
                    updated_by=context.subject.subject_id,
                )
                session.add(profile)
            else:
                if profile.version != expected_version:
                    raise ConflictError("The system configuration was modified by another request.")
                profile.endpoint_url = endpoint
                profile.auth_principal = (
                    auth_principal.strip() if isinstance(auth_principal, str) else None
                )
                profile.secret_reference = (
                    "configuration_yaml:secret_references" if secret_references else None
                )
                profile.configuration_yaml = rendered_configuration
                profile.active = True
                profile.updated_by = context.subject.subject_id
                profile.version += 1
            await session.flush()
            assert profile is not None
            revision = ExternalServiceProfileVersionModel(
                workspace_id=context.workspace_id,
                profile_id=profile.id,
                configuration_version=profile.version,
                configuration_hash=canonical_json_hash(merged),
                configuration_yaml=rendered_configuration,
                endpoint_url=endpoint,
                created_by=context.subject.subject_id,
            )
            session.add(revision)
            await SqlOutboxWriter(session).add_events(
                [
                    DomainEvent.create(
                        event_type="platform.system_configuration.saved.v1",
                        aggregate_type="external_service_profile",
                        aggregate_id=profile.id,
                        workspace_id=context.workspace_id,
                        payload={
                            "actor_id": str(context.subject.subject_id),
                            "configuration_hash": revision.configuration_hash,
                            "configuration_version": profile.version,
                            "service_key": service_key,
                        },
                    )
                ]
            )
            saved_version = profile.version
            saved_at = profile.updated_at
            saved_yaml = _render_yaml(_mask_configuration(merged))
    response.headers["ETag"] = f'"{saved_version}"'
    return SystemConfigurationEntryResponse(
        system_id=system_id,
        label=label,
        state="CONFIGURED",
        management_plane="DEVELOPMENT_DATABASE",
        secret_reference_configured=bool(secret_references),
        embedding_state="AVAILABLE" if system_id == "GRAFANA_DASHBOARD" else "NOT_APPLICABLE",
        configuration_yaml=saved_yaml,
        template_yaml=_render_yaml(_SYSTEM_CONFIGURATION_TEMPLATES[system_id]),
        display_yaml=_render_yaml(_display_configuration(merged)),
        version=saved_version,
        configured_at=saved_at,
        runtime_supported=system_id in _RUNTIME_RESTART_SCOPE,
        restart_scope=_RUNTIME_RESTART_SCOPE.get(system_id, "NOT_IMPLEMENTED"),
        activation_state=(
            "SAVED_UNTESTED" if system_id in _RUNTIME_RESTART_SCOPE else "RUNTIME_NOT_IMPLEMENTED"
        ),
    )


@router.post(
    "/system-configuration/{system_id}/test",
    response_model=SystemConfigurationTestResponse,
)
async def test_system_configuration(
    system_id: str,
    request: Request,
    response: Response,
    context: ContextDep,
) -> SystemConfigurationTestResponse:
    """Probe only a saved development profile through one fixed connector route."""

    container = get_container(request)
    if container.settings.app_env != "development":
        raise ForbiddenError(
            "Database-backed system configuration testing is available only in development."
        )
    if system_id not in _CONFIGURATION_BY_ID:
        raise ValidationError("The system configuration identifier is invalid.")
    admin_context = await _service(request).get_admin_read_context(
        workspace_id=context.workspace_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if "SYSTEM_CONFIGURATION_UPDATE" not in admin_context.allowed_operations:
        raise ForbiddenError(
            "System configuration testing is not available for this administrator."
        )
    service_key, _ = _CONFIGURATION_BY_ID[system_id]
    async with container.database.session_factory() as session:
        async with session.begin():
            await set_security_context(
                session,
                workspace_id=context.workspace_id,
                subject_id=context.subject.subject_id,
            )
            profile = (
                await session.scalars(
                    select(ExternalServiceProfileModel).where(
                        ExternalServiceProfileModel.workspace_id == context.workspace_id,
                        ExternalServiceProfileModel.service_key == service_key,
                        ExternalServiceProfileModel.active.is_(True),
                    )
                )
            ).one_or_none()
    if profile is None or not profile.configuration_yaml:
        raise ValidationError("Save this system configuration before testing it.")
    tested_version = profile.version
    tested_yaml = profile.configuration_yaml
    result = await probe_system_configuration(
        system_id=system_id,
        document=_yaml_document(tested_yaml),
        secret_resolver=SecretResolver(
            virtual_secret_root=container.settings.system_configuration_secret_root
        ),
    )
    tested_at = utc_now()
    async with container.database.session_factory() as session:
        async with session.begin():
            await set_security_context(
                session,
                workspace_id=context.workspace_id,
                subject_id=context.subject.subject_id,
            )
            locked_profile = (
                await session.scalars(
                    select(ExternalServiceProfileModel)
                    .where(
                        ExternalServiceProfileModel.workspace_id == context.workspace_id,
                        ExternalServiceProfileModel.service_key == service_key,
                    )
                    .with_for_update()
                )
            ).one_or_none()
            if locked_profile is None or locked_profile.version != tested_version:
                raise ConflictError(
                    "The system configuration changed while its connection test was running."
                )
            revision = (
                await session.scalars(
                    select(ExternalServiceProfileVersionModel)
                    .where(
                        ExternalServiceProfileVersionModel.workspace_id == context.workspace_id,
                        ExternalServiceProfileVersionModel.profile_id == locked_profile.id,
                        ExternalServiceProfileVersionModel.configuration_version == tested_version,
                    )
                    .with_for_update()
                )
            ).one_or_none()
            if revision is None or revision.configuration_yaml != tested_yaml:
                raise ConflictError("The tested configuration revision does not exist.")
            revision.configuration_hash = canonical_json_hash(_yaml_document(tested_yaml))
            revision.test_status = result.status
            revision.test_scope = result.scope
            revision.test_latency_ms = result.latency_ms
            revision.tested_at = tested_at
            revision.tested_by = context.subject.subject_id
            await SqlOutboxWriter(session).add_events(
                [
                    DomainEvent.create(
                        event_type="platform.system_configuration.tested.v1",
                        aggregate_type="external_service_profile",
                        aggregate_id=locked_profile.id,
                        workspace_id=context.workspace_id,
                        payload={
                            "actor_id": str(context.subject.subject_id),
                            "configuration_version": tested_version,
                            "scope": result.scope,
                            "service_key": service_key,
                            "status": result.status,
                        },
                    )
                ]
            )
    response.headers["Cache-Control"] = "no-store, private"
    return SystemConfigurationTestResponse(
        system_id=system_id,
        status=result.status,
        scope=result.scope,
        latency_ms=result.latency_ms,
        detail=result.detail,
        configuration_version=tested_version,
        tested_at=tested_at,
    )


@router.post(
    "/system-configuration/{system_id}/activate",
    response_model=SystemConfigurationEntryResponse,
)
async def activate_system_configuration(
    system_id: str,
    request: Request,
    response: Response,
    context: ContextDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
) -> SystemConfigurationEntryResponse:
    """Select one TEST-passed revision for the next API/worker process startup."""

    container = get_container(request)
    if container.settings.app_env != "development":
        raise ForbiddenError(
            "Database-backed system configuration activation is available only in development."
        )
    if system_id not in _CONFIGURATION_BY_ID:
        raise ValidationError("The system configuration identifier is invalid.")
    if system_id not in _RUNTIME_RESTART_SCOPE:
        raise ConflictError("No runtime consumer is implemented for this system configuration.")
    expected_version = _expected_configuration_version(if_match)
    admin_context = await _service(request).get_admin_read_context(
        workspace_id=context.workspace_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if "SYSTEM_CONFIGURATION_ACTIVATE" not in admin_context.allowed_operations:
        raise ForbiddenError(
            "System configuration activation requires recent hardware WebAuthn assurance."
        )
    service_key, _ = _CONFIGURATION_BY_ID[system_id]
    async with container.database.session_factory() as session:
        async with session.begin():
            await set_security_context(
                session,
                workspace_id=context.workspace_id,
                subject_id=context.subject.subject_id,
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
            if profile is None or profile.version != expected_version:
                raise ConflictError("The system configuration version is stale.")
            revision = (
                await session.scalars(
                    select(ExternalServiceProfileVersionModel)
                    .where(
                        ExternalServiceProfileVersionModel.workspace_id == context.workspace_id,
                        ExternalServiceProfileVersionModel.profile_id == profile.id,
                        ExternalServiceProfileVersionModel.configuration_version == profile.version,
                    )
                    .with_for_update()
                )
            ).one_or_none()
            if revision is None or revision.test_status != "AVAILABLE":
                raise ConflictError("Only the current TEST-passed configuration can be activated.")
            if profile.activated_version != profile.version:
                activated_at = utc_now()
                profile.activated_version = profile.version
                revision.activated_at = activated_at
                revision.activated_by = context.subject.subject_id
                await SqlOutboxWriter(session).add_events(
                    [
                        DomainEvent.create(
                            event_type="platform.system_configuration.activated.v1",
                            aggregate_type="external_service_profile",
                            aggregate_id=profile.id,
                            workspace_id=context.workspace_id,
                            payload={
                                "actor_id": str(context.subject.subject_id),
                                "configuration_hash": revision.configuration_hash,
                                "configuration_version": profile.version,
                                "restart_scope": _RUNTIME_RESTART_SCOPE[system_id],
                                "service_key": service_key,
                            },
                        )
                    ]
                )
            await session.flush()
            entry = _system_configuration_entries(
                container.settings,
                {service_key: profile},
                {(profile.id, revision.configuration_version): revision},
            )
            result = next(item for item in entry if item.system_id == system_id)
    response.headers["ETag"] = f'"{profile.version}"'
    return result


@router.post(
    "/membership-renewals/me",
    status_code=201,
    response_model=MembershipRenewalResponse,
)
async def request_own_membership_renewal(
    payload: MembershipRenewalCreateRequest,
    request: Request,
    context: ContextDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> MembershipRenewalResponse:
    request_hash = canonical_json_hash(
        {
            "operation": "membership.renewal.request",
            "subject_id": str(context.subject.subject_id),
            "reason": payload.reason.strip(),
        }
    )
    value = await _service(request).request_membership_renewal(
        workspace_id=context.workspace_id,
        reason=payload.reason,
        subject=context.subject,
        environment=context.environment,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    return _membership_renewal_response(value)


@router.get(
    "/workspace-memberships/me/summary",
    response_model=WorkspaceMembershipSummaryResponse,
)
async def get_own_workspace_membership_summary(
    request: Request,
    context: ContextDep,
) -> WorkspaceMembershipSummaryResponse:
    value = await _service(request).get_own_workspace_membership(
        workspace_id=context.workspace_id,
        subject=context.subject,
    )
    return workspace_membership_summary_response(value)


@router.get("/membership-renewals/me", response_model=MembershipRenewalListResponse)
async def list_own_membership_renewals(
    request: Request,
    context: ContextDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> MembershipRenewalListResponse:
    values = await _service(request).list_membership_renewals(
        workspace_id=context.workspace_id,
        subject_id=context.subject.subject_id,
        state=None,
        limit=limit,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        administrator=False,
    )
    return MembershipRenewalListResponse(
        items=[_membership_renewal_response(value) for value in values]
    )


@router.get("/membership-renewals", response_model=MembershipRenewalListResponse)
async def list_membership_renewals_for_admin(
    request: Request,
    context: ContextDep,
    state: Annotated[str | None, Query(max_length=20)] = "PENDING",
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> MembershipRenewalListResponse:
    try:
        parsed_state = MembershipRenewalState(state) if state is not None else None
    except ValueError as error:
        raise ValidationError("The membership renewal state filter is invalid.") from error
    values = await _service(request).list_membership_renewals(
        workspace_id=context.workspace_id,
        subject_id=None,
        state=parsed_state,
        limit=limit,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        administrator=True,
    )
    return MembershipRenewalListResponse(
        items=[_membership_renewal_response(value) for value in values]
    )


@router.post(
    "/membership-renewals/{renewal_request_id}/decisions",
    response_model=MembershipRenewalResponse,
)
async def decide_membership_renewal(
    renewal_request_id: UUID,
    payload: MembershipRenewalDecisionRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> MembershipRenewalResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "operation": "membership.renewal.decide",
            "renewal_request_id": str(renewal_request_id),
            "decision": payload.decision,
            "reason": payload.reason.strip(),
            "expected_version": expected_version,
        }
    )
    value, membership_version = await _service(request).decide_membership_renewal(
        workspace_id=context.workspace_id,
        renewal_request_id=renewal_request_id,
        decision_value=MembershipRenewalDecision(payload.decision),
        reason=payload.reason,
        expected_version=expected_version,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    response.headers["ETag"] = f'"{value.version}"'
    return _membership_renewal_response(value, membership_version=membership_version)


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
    "/workspace-memberships/{target_subject_id}/role",
    response_model=MembershipRoleAssignmentResponse,
)
async def assign_membership_role(
    target_subject_id: UUID,
    payload: MembershipRoleAssignmentRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> MembershipRoleAssignmentResponse:
    expected_version = _expected_version(if_match)
    current = await _service(request).get_workspace_membership_access(
        workspace_id=context.workspace_id,
        target_subject_id=target_subject_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if current.summary.membership_version != expected_version:
        raise ConflictError("The workspace membership was modified by another request.")
    if payload.role_id is None:
        command = MembershipAccessUpdate(
            workspace_id=context.workspace_id,
            target_subject_id=target_subject_id,
            expected_membership_version=expected_version,
            active=current.summary.membership_active,
            clearance=Classification.PUBLIC,
            groups=frozenset(),
            allowed_actions=frozenset(),
            denied_actions=frozenset(),
            allowed_system_ids=frozenset(),
            allowed_domain_ids=frozenset(),
        )
    else:
        container = get_container(request)
        async with container.database.session_factory() as session:
            async with session.begin():
                await set_security_context(
                    session,
                    workspace_id=context.workspace_id,
                    subject_id=context.subject.subject_id,
                )
                role = (
                    await session.scalars(
                        select(AccessRoleModel).where(
                            AccessRoleModel.workspace_id == context.workspace_id,
                            AccessRoleModel.id == payload.role_id,
                            AccessRoleModel.active.is_(True),
                        )
                    )
                ).one_or_none()
        if role is None:
            raise ValidationError("The active access role does not exist in this workspace.")
        try:
            command = MembershipAccessUpdate(
                workspace_id=context.workspace_id,
                target_subject_id=target_subject_id,
                expected_membership_version=expected_version,
                active=current.summary.membership_active,
                clearance=Classification(role.clearance),
                groups=frozenset([*role.groups, _role_marker(role.role_key)]),
                allowed_actions=frozenset(Action(value) for value in role.allowed_actions),
                denied_actions=frozenset(Action(value) for value in role.denied_actions),
                allowed_system_ids=frozenset(UUID(value) for value in role.allowed_system_ids),
                allowed_domain_ids=frozenset(UUID(value) for value in role.allowed_domain_ids),
            )
        except (TypeError, ValueError) as error:
            raise ConflictError("The stored access role definition is invalid.") from error
    request_hash = canonical_json_hash(
        {
            "operation": "admin.membership.role.assign",
            "role_id": str(payload.role_id) if payload.role_id is not None else None,
            "command": command.command_document(),
        }
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
    return MembershipRoleAssignmentResponse(
        subject_id=target_subject_id,
        role_id=payload.role_id,
        membership_version=membership_version,
        payload_hash=command.payload_hash,
    )


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
