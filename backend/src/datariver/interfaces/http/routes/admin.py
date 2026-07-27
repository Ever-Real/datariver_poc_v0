from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

import yaml  # type: ignore[import-untyped]
from fastapi import APIRouter, Header, Query, Request, Response
from sqlalchemy import exists, func, or_, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from yaml.tokens import AliasToken, AnchorToken  # type: ignore[import-untyped]

from datariver.application.classification_access import InferenceRuntimeBinding
from datariver.application.dto import MembershipRenewalRecord
from datariver.application.identity_admin import IdentityUserDraft
from datariver.application.services.admin_access import AdminAccessService
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.identity_admin import IdentityAdminService
from datariver.config import Settings
from datariver.domain.admin_access import (
    AdminAccessDecision,
    AdminAccessRequestState,
    MembershipAccessUpdate,
    SystemAssigneeKey,
    SystemAssigneePatchCommand,
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
from datariver.domain.data_access import (
    DataAccessLevel,
    DataProcessingPurpose,
    PartialAccessTreatment,
    RoleDataAccessRule,
)
from datariver.domain.membership_renewal import (
    MembershipRenewalDecision,
    MembershipRenewalState,
)
from datariver.domain.system_configuration import (
    canonical_secret_references,
    require_canonical_secret_references,
)
from datariver.infrastructure.db.admin_access import (
    SqlAdminAccessUnitOfWork,
    SqlMembershipAccessRepository,
    decode_admin_list_cursor,
    encode_admin_list_cursor,
)
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.governance import SqlOutboxWriter
from datariver.infrastructure.db.models.platform import (
    AccessRoleAssignmentModel,
    AccessRoleDataRuleModel,
    AccessRoleModel,
    ExternalServiceProfileModel,
    ExternalServiceProfileVersionModel,
    WorkspaceMembershipModel,
)
from datariver.infrastructure.db.rls import set_security_context
from datariver.infrastructure.llm.runtime_binding import (
    resolve_composition_runtime_binding,
    resolve_embedding_runtime_binding,
    resolve_reranker_runtime_binding,
)
from datariver.infrastructure.secrets import SecretResolver
from datariver.infrastructure.system_configuration_probe import (
    probe_oidc_jwks,
    probe_system_configuration,
)
from datariver.infrastructure.system_configuration_runtime import (
    validate_runtime_system_configuration,
)
from datariver.interfaces.http.dependencies import ContextDep, get_container
from datariver.interfaces.http.presenters import (
    admin_access_request_response,
    admin_read_context_response,
    workspace_membership_access_response,
    workspace_membership_summary_response,
)
from datariver.interfaces.http.schemas import (
    AccessRoleDataRuleRequest,
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
    IdentityUserProvisionRequest,
    IdentityUserProvisionResponse,
    MembershipAccessDocumentRequest,
    MembershipAccessUpdateResponse,
    MembershipChangeRequestActivityListResponse,
    MembershipChangeRequestActivityResponse,
    MembershipOwnedTableListResponse,
    MembershipOwnedTableResponse,
    MembershipRenewalCreateRequest,
    MembershipRenewalDecisionRequest,
    MembershipRenewalListResponse,
    MembershipRenewalResponse,
    MembershipRoleAssignmentRequest,
    MembershipRoleAssignmentResponse,
    PageMeta,
    SystemAssigneeListResponse,
    SystemAssigneePatchRequest,
    SystemAssigneeUpdateListRequest,
    SystemAssigneeUpdateResponse,
    SystemConfigurationEntryResponse,
    SystemConfigurationListResponse,
    SystemConfigurationTestResponse,
    SystemConfigurationUpdateRequest,
    SystemConfigurationVersionListResponse,
    SystemConfigurationVersionResponse,
    SystemConnectionRequirementResponse,
    SystemCreateRequest,
    SystemDirectoryAssigneeResponse,
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


_BOOTSTRAP_SYSTEM_CONFIGURATION = (
    ("PLATFORM_RUNTIME", "PLATFORM_RUNTIME", "DataRiver Runtime"),
    ("POSTGRESQL", "POSTGRESQL", "PostgreSQL"),
    ("OIDC_IDENTITY", "OIDC_IDENTITY", "OIDC Identity"),
    ("RETENTION_ARCHIVE", "RETENTION_ARCHIVE", "Retention and archive"),
)
_CONNECTOR_SYSTEM_CONFIGURATION = (
    ("DATAHUB_GMS", "DATAHUB", "DataHub (Metadata)"),
    ("DATAHUB_FRONTEND", "DATAHUB_FRONTEND", "DataHub (Frontend)"),
    ("AIRFLOW", "AIRFLOW", "Airflow"),
    ("REDIS_CACHE", "REDIS_CACHE", "Redis Cache"),
    ("REDIS_DELIVERY", "REDIS_DELIVERY", "Redis Delivery"),
    ("S3_STORAGE", "S3_STORAGE", "S3-compatible Storage"),
    ("LLM_CHAT_MODEL", "LLM_CHAT_MODEL", "LLM · Chat model"),
    ("LLM_EMBEDDING", "LLM_EMBEDDING", "LLM · Embedding"),
    ("LLM_RERANKER", "LLM_RERANKER", "LLM · Reranker"),
    ("NEO4J", "NEO4J", "Neo4j"),
    ("PROMETHEUS", "PROMETHEUS", "Prometheus"),
    ("GRAFANA_DASHBOARD", "GRAFANA_DASHBOARD", "Grafana Dashboard"),
)
_SYSTEM_CONFIGURATION = _BOOTSTRAP_SYSTEM_CONFIGURATION + _CONNECTOR_SYSTEM_CONFIGURATION
_SYSTEM_ENVIRONMENT_KEYS: dict[str, tuple[str, ...]] = {
    "PLATFORM_RUNTIME": (
        "APP_ENV",
        "APP_NAME",
        "APP_LOG_LEVEL",
        "APP_PUBLIC_ORIGIN",
        "APP_CORS_ORIGINS",
        "APP_TRUSTED_HOSTS",
        "DEPLOYMENT_TIER",
        "DEPLOYMENT_EVIDENCE_REFERENCE",
        "SEED_PROFILE",
    ),
    "POSTGRESQL": (
        "POSTGRES_DB",
        "POSTGRES_USER",
        "DATABASE_URL",
        "DATABASE_SECRET_REF",
        "MIGRATION_DATABASE_URL",
        "MIGRATION_DATABASE_SECRET_REF",
        "RELAY_DATABASE_URL",
        "RELAY_DATABASE_SECRET_REF",
        "UPLOAD_DATABASE_URL",
        "UPLOAD_DATABASE_SECRET_REF",
        "GOVERNANCE_DATABASE_URL",
        "GOVERNANCE_DATABASE_SECRET_REF",
        "KNOWLEDGE_DATABASE_URL",
        "KNOWLEDGE_DATABASE_SECRET_REF",
        "EXPORT_DATABASE_URL",
        "EXPORT_DATABASE_SECRET_REF",
        "RETENTION_SCHEDULER_DATABASE_URL",
        "RETENTION_SCHEDULER_DATABASE_SECRET_REF",
        "ARCHIVE_DATABASE_URL",
        "ARCHIVE_DATABASE_SECRET_REF",
        "BOOTSTRAP_DATABASE_URL",
        "BOOTSTRAP_DATABASE_SECRET_REF",
        "DATABASE_POOL_SIZE",
        "DATABASE_POOL_MAX_OVERFLOW",
        "DATABASE_POOL_TIMEOUT_SECONDS",
        "DATABASE_READINESS_TIMEOUT_SECONDS",
        "WORKER_DATABASE_POOL_SIZE",
        "WORKER_DATABASE_POOL_MAX_OVERFLOW",
        "WORKER_DATABASE_POOL_TIMEOUT_SECONDS",
    ),
    "OIDC_IDENTITY": (
        "OIDC_ISSUER",
        "OIDC_AUDIENCE",
        "OIDC_JWKS_URL",
        "OIDC_ALLOWED_ALGORITHMS",
        "OIDC_PUBLIC_AUTHORITY",
        "OIDC_PUBLIC_ORIGIN",
        "OIDC_CLIENT_ID",
        "OIDC_HARDWARE_ACR_VALUES",
        "OIDC_STEP_UP_ACR",
        "OIDC_HARDWARE_AMR_VALUES",
        "OIDC_HARDWARE_WEBAUTHN_ENABLED",
        "OIDC_PASSWORD_REAUTH_ACR_VALUES",
        "OIDC_PASSWORD_REAUTH_REQUEST_ACR",
        "OIDC_PASSWORD_AMR_VALUES",
        "WORKSPACE_SELECTION_ENABLED",
        "IDENTITY_ADMIN_ENABLED",
        "IDENTITY_ADMIN_BASE_URL",
        "IDENTITY_ADMIN_REALM",
        "IDENTITY_ADMIN_CLIENT_ID",
        "IDENTITY_ADMIN_CLIENT_SECRET_REF",
        "IDENTITY_ADMIN_TIMEOUT_SECONDS",
        "IDENTITY_PASSWORD_CHANGE_ACTION_ENABLED",
        "HIGH_RISK_AUTH_MAX_AGE_SECONDS",
        "ADMIN_PASSWORD_FALLBACK_ENABLED",
        "ADMIN_PASSWORD_FALLBACK_TTL_SECONDS",
        "DEVELOPMENT_ADMIN_PASSWORD_BYPASS_ENABLED",
        "SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS",
    ),
    "RETENTION_ARCHIVE": (
        "EVENT_RETENTION_DAYS",
        "RETENTION_ARCHIVE_EXECUTION_ENABLED",
        "RETENTION_EXECUTION_CONTROL_FILE",
        "RETENTION_WORKSPACE_IDS",
        "RETENTION_CLAIM_BATCH_SIZE",
        "RETENTION_LEASE_SECONDS",
        "RETENTION_MAXIMUM_ATTEMPTS",
        "RETENTION_WORKER_DATABASE_POOL_SIZE",
        "RETENTION_WORKER_DATABASE_POOL_MAX_OVERFLOW",
        "RETENTION_METRICS_PORT",
        "RETENTION_WORKER_SUBJECT_ID",
    ),
    "DATAHUB_GMS": (
        "DATAHUB_BASE_URL",
        "DATAHUB_SECRET_REF",
        "DATAHUB_EXPECTED_VERSION",
        "DATAHUB_ALLOWED_VERSIONS",
        "DATAHUB_VERSION_ENFORCEMENT",
        "DATAHUB_VERSION_PROBE_TTL_SECONDS",
        "DATAHUB_TIMEOUT_SECONDS",
        "DATAHUB_MAX_CONCURRENCY",
        "DATAHUB_QUEUE_TIMEOUT_SECONDS",
        "DATAHUB_CIRCUIT_FAILURE_THRESHOLD",
        "DATAHUB_CIRCUIT_OPEN_SECONDS",
        "DATAHUB_STALE_TTL_SECONDS",
        "DATAHUB_CATALOG_PIT_VERIFIED",
        "DATAHUB_CATALOG_PIT_EVIDENCE_REFERENCE",
        "DATARIVER_CATALOG_SYNC_MAX_PAGES",
        "GOVERNANCE_APPLY_LEASE_SECONDS",
        "GOVERNANCE_APPLY_MAXIMUM_ATTEMPTS",
        "GOVERNANCE_WORKER_SUBJECT_ID",
        "SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS",
    ),
    "DATAHUB_FRONTEND": (
        "UI_DATAHUB_URL",
        "DATAHUB_EMBED_BASE_URL",
        "DATAHUB_EMBED_ENABLED",
        "SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS",
    ),
    "AIRFLOW": (
        "UI_AIRFLOW_URL",
        "AIRFLOW_WORKSPACE_ID",
        "SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS",
    ),
    "REDIS_CACHE": (
        "REDIS_CACHE_URL",
        "REDIS_CACHE_SECRET_REF",
        "CACHE_DEFAULT_TTL_SECONDS",
        "CACHE_MAX_VALUE_BYTES",
        "CATALOG_SEARCH_CACHE_TTL_SECONDS",
        "CATALOG_SEARCH_MINIMUM_QUERY_LENGTH",
        "SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS",
    ),
    "REDIS_DELIVERY": (
        "REDIS_DELIVERY_URL",
        "REDIS_DELIVERY_SECRET_REF",
        "OUTBOX_LEASE_SECONDS",
        "OUTBOX_MAXIMUM_ATTEMPTS",
        "WORKER_POLL_SECONDS",
        "SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS",
    ),
    "S3_STORAGE": (
        "S3_ENDPOINT_URL",
        "S3_PUBLIC_ENDPOINT_URL",
        "S3_PUBLIC_ORIGIN",
        "S3_REGION",
        "S3_BUCKET_QUARANTINE",
        "S3_BUCKET_ACCEPTED",
        "S3_BUCKET_EXPORTS",
        "S3_BUCKET_FILEFOLDER",
        "S3_BUCKET_INFOSCHEMA",
        "S3_ACCESS_KEY_FILE",
        "S3_SECRET_KEY_FILE",
        "S3_EXPORT_ACCESS_KEY_FILE",
        "S3_EXPORT_SECRET_KEY_FILE",
        "S3_KNOWLEDGE_ACCESS_KEY_FILE",
        "S3_KNOWLEDGE_SECRET_KEY_FILE",
        "S3_CORS_MANAGEMENT_MODE",
        "S3_ARCHIVE_ENDPOINT_URL",
        "S3_ARCHIVE_REGION",
        "S3_ARCHIVE_BUCKET",
        "S3_ARCHIVE_PREFIX",
        "S3_ARCHIVE_ACCESS_KEY_FILE",
        "S3_ARCHIVE_SECRET_KEY_FILE",
        "S3_ARCHIVE_ENCRYPTION_PROFILE_FINGERPRINT",
        "S3_ARCHIVE_WORKER_PRINCIPAL_FINGERPRINT",
        "PRESIGNED_URL_TTL_SECONDS",
        "CATALOG_EXPORT_WORKER_ENABLED",
        "CATALOG_EXPORT_ACCESS_TTL_SECONDS",
        "CATALOG_EXPORT_DOWNLOAD_TTL_SECONDS",
        "CATALOG_EXPORT_LEASE_SECONDS",
        "CATALOG_EXPORT_MAXIMUM_ATTEMPTS",
        "CATALOG_EXPORT_PAGE_SIZE",
        "CATALOG_EXPORT_MAXIMUM_ROWS",
        "CATALOG_EXPORT_MAXIMUM_BYTES",
        "UPLOAD_LEASE_SECONDS",
        "UPLOAD_MAXIMUM_ATTEMPTS",
        "UPLOAD_VALIDATION_LEASE_SECONDS",
        "UPLOAD_VALIDATION_MAXIMUM_ATTEMPTS",
        "BULK_PREPARATION_LEASE_SECONDS",
        "BULK_PREPARATION_MAXIMUM_ATTEMPTS",
        "EXPORT_WORKER_SUBJECT_ID",
        "RETENTION_WORKER_SUBJECT_ID",
        "WORKER_POLL_SECONDS",
        "SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS",
    ),
    "LLM_CHAT_MODEL": (
        "LOCAL_INFERENCE_SOURCE_HOST_ENABLED",
        "LOCAL_INFERENCE_ALLOWED_HOSTS",
        "LOCAL_OLLAMA_CHAT_ENABLED",
        "LOCAL_OLLAMA_CHAT_BASE_URL",
        "LOCAL_OLLAMA_CHAT_MODEL",
        "LOCAL_OLLAMA_CHAT_TIMEOUT_SECONDS",
        "LOCAL_OLLAMA_CHAT_CONTEXT_TOKENS",
        "INTRANET_OPENAI_COMPATIBLE_ALLOWED_HOSTS",
        "INTRANET_OPENAI_COMPATIBLE_CHAT_ENABLED",
        "INTRANET_OPENAI_COMPATIBLE_CHAT_BASE_URL",
        "INTRANET_OPENAI_COMPATIBLE_CHAT_MODEL",
        "INTRANET_OPENAI_COMPATIBLE_CHAT_API_KEY_SECRET_REF",
        "INTRANET_OPENAI_COMPATIBLE_CHAT_TIMEOUT_SECONDS",
        "INTRANET_OPENAI_COMPATIBLE_CHAT_CONTEXT_TOKENS",
        "CHAT_EPHEMERAL_ADMIN_WITHOUT_RETENTION_ENABLED",
        "CHAT_RATE_LIMIT_REQUESTS_PER_MINUTE",
        "CHAT_RATE_LIMIT_TOKENS_PER_MINUTE",
        "CHAT_COMPOSITION_PROVIDER_PROFILE_VERSION_ID",
        "SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS",
        "SYSTEM_CONFIGURATION_SECRET_ROOT",
    ),
    "LLM_EMBEDDING": (
        "LOCAL_INFERENCE_SOURCE_HOST_ENABLED",
        "LOCAL_INFERENCE_ALLOWED_HOSTS",
        "LOCAL_OLLAMA_EMBEDDING_ENABLED",
        "LOCAL_OLLAMA_EMBEDDING_BASE_URL",
        "LOCAL_OLLAMA_EMBEDDING_MODEL",
        "LOCAL_OLLAMA_EMBEDDING_TIMEOUT_SECONDS",
        "INTRANET_OPENAI_COMPATIBLE_ALLOWED_HOSTS",
        "INTRANET_OPENAI_COMPATIBLE_EMBEDDING_ENABLED",
        "INTRANET_OPENAI_COMPATIBLE_EMBEDDING_BASE_URL",
        "INTRANET_OPENAI_COMPATIBLE_EMBEDDING_MODEL",
        "INTRANET_OPENAI_COMPATIBLE_EMBEDDING_API_KEY_SECRET_REF",
        "INTRANET_OPENAI_COMPATIBLE_EMBEDDING_TIMEOUT_SECONDS",
        "CHAT_EMBEDDING_PROVIDER_PROFILE_VERSION_ID",
        "SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS",
        "SYSTEM_CONFIGURATION_SECRET_ROOT",
    ),
    "LLM_RERANKER": (
        "LOCAL_INFERENCE_SOURCE_HOST_ENABLED",
        "LOCAL_INFERENCE_ALLOWED_HOSTS",
        "LOCAL_LLAMA_CPP_RERANKER_ENABLED",
        "LOCAL_LLAMA_CPP_RERANKER_BASE_URL",
        "LOCAL_LLAMA_CPP_RERANKER_MODEL",
        "LOCAL_LLAMA_CPP_RERANKER_TIMEOUT_SECONDS",
        "LOCAL_LLAMA_CPP_RERANKER_TOP_N",
        "CHAT_RERANKER_PROVIDER_PROFILE_VERSION_ID",
        "SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS",
        "SYSTEM_CONFIGURATION_SECRET_ROOT",
    ),
    "NEO4J": (
        "NEO4J_IMAGE",
        "NEO4J_PROJECTION_ENABLED",
        "NEO4J_SOURCE_HOST_ENABLED",
        "NEO4J_URI",
        "NEO4J_ALLOWED_HOSTS",
        "NEO4J_DATABASE",
        "NEO4J_AUTH_SECRET_REF",
        "NEO4J_CONNECTION_TIMEOUT_SECONDS",
        "NEO4J_MAXIMUM_CONNECTION_POOL_SIZE",
        "NEO4J_HTTP_PORT",
        "NEO4J_BOLT_PORT",
        "UI_GRAPH_URL",
        "KNOWLEDGE_PIPELINE_ENABLED",
        "KNOWLEDGE_SOURCE_WORKER_ENABLED",
        "KNOWLEDGE_SOURCE_JOB_MAXIMUM_ATTEMPTS",
        "KNOWLEDGE_SOURCE_WORKER_LEASE_SECONDS",
        "KNOWLEDGE_SOURCE_WORKER_POLL_SECONDS",
        "KNOWLEDGE_SOURCE_MEMORY_SPOOL_BYTES",
        "KNOWLEDGE_SOURCE_SPOOL_DIRECTORY",
        "KNOWLEDGE_WORKER_SUBJECT_ID",
        "SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS",
        "SYSTEM_CONFIGURATION_SECRET_ROOT",
    ),
    "PROMETHEUS": (
        "UI_PROMETHEUS_URL",
        "SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS",
    ),
    "GRAFANA_DASHBOARD": (
        "UI_GRAFANA_URL",
        "GRAFANA_EMBED_BASE_URL",
        "GRAFANA_EMBED_ENABLED",
        "GRAFANA_EMBED_EVIDENCE_REFERENCE",
        "SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS",
    ),
}
_CONFIGURATION_BY_ID = {
    system_id: (service_key, label)
    for system_id, service_key, label in _CONNECTOR_SYSTEM_CONFIGURATION
}
_RUNTIME_RESTART_SCOPE = {
    "DATAHUB_GMS": "API_AND_WORKERS",
    "DATAHUB_FRONTEND": "API_ONLY",
    "AIRFLOW": "API_ONLY",
    "REDIS_CACHE": "API_ONLY",
    "REDIS_DELIVERY": "WORKERS_ONLY",
    "S3_STORAGE": "API_AND_WORKERS",
    "LLM_CHAT_MODEL": "API_ONLY",
    "LLM_EMBEDDING": "API_AND_WORKERS",
    "LLM_RERANKER": "API_ONLY",
    "NEO4J": "API_AND_WORKERS",
    "PROMETHEUS": "API_ONLY",
    "GRAFANA_DASHBOARD": "API_ONLY",
}
_SYSTEM_CONFIGURATION_TEMPLATES: dict[str, dict[str, Any]] = {
    "PLATFORM_RUNTIME": {"options": {}},
    "RETENTION_ARCHIVE": {"options": {}},
    "DATAHUB_GMS": {
        "base_url": "",
        "secret_references": dict(canonical_secret_references("DATAHUB_GMS")),
        "options": {
            "allowed_versions": [],
            "catalog_pit_evidence_reference": "",
            "catalog_pit_verified": False,
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
    "REDIS_CACHE": {
        "url": "redis://redis-cache.example.internal:6379/0",
        "secret_references": dict(canonical_secret_references("REDIS_CACHE")),
        "options": {"role": "CACHE", "required_policy": "allkeys-lfu"},
    },
    "REDIS_DELIVERY": {
        "url": "redis://redis-delivery.example.internal:6379/0",
        "secret_references": dict(canonical_secret_references("REDIS_DELIVERY")),
        "options": {"role": "DELIVERY", "required_policy": "noeviction+aof"},
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
        "secret_references": dict(canonical_secret_references("S3_STORAGE")),
    },
    "LLM_CHAT_MODEL": {
        "connection_mode": "LOCAL_OLLAMA",
        "base_url": "",
        "model": "",
        "secret_references": {},
        "options": {
            "api_style": "openai_compatible",
            "context_tokens": 8192,
            "timeout_seconds": 60.0,
        },
    },
    "LLM_EMBEDDING": {
        "connection_mode": "LOCAL_OLLAMA",
        "base_url": "",
        "model": "",
        "secret_references": {},
        "options": {"api_style": "openai_compatible", "timeout_seconds": 60.0},
    },
    "LLM_RERANKER": {
        "connection_mode": "LOCAL_LLAMA_CPP",
        "base_url": "",
        "model": "",
        "secret_references": {},
        "options": {"api_style": "rerank_v1", "timeout_seconds": 60.0, "top_n": 10},
    },
    "NEO4J": {
        "database": "neo4j",
        "secret_references": dict(canonical_secret_references("NEO4J")),
        "uri": "",
        "options": {"connection_timeout_seconds": 30.0, "maximum_connection_pool_size": 50},
    },
    "PROMETHEUS": {"base_url": "", "options": {}},
    "GRAFANA_DASHBOARD": {
        "options": {"dashboard_path": "", "embed_enabled": False},
        "url": "",
    },
}

_SYSTEM_METADATA: dict[str, dict[str, Any]] = {
    "PLATFORM_RUNTIME": {
        "category": "PLATFORM",
        "requirement": "BOOTSTRAP_REQUIRED",
        "description": "Application identity, public origin and deployment evidence options.",
        "fields": (),
    },
    "POSTGRESQL": {
        "category": "PLATFORM",
        "requirement": "BOOTSTRAP_REQUIRED",
        "description": "Canonical application database and System Settings bootstrap store.",
        "fields": (
            ("url", "Database URL", True, False, "postgresql+asyncpg://user@db:5432/datariver"),
            ("database", "Database name", True, False, "datariver"),
            ("username", "Role name", True, False, "datariver_app"),
            ("password", "Password secret reference", True, True, None),
        ),
    },
    "OIDC_IDENTITY": {
        "category": "PLATFORM",
        "requirement": "BOOTSTRAP_REQUIRED",
        "description": "Login and assurance provider; bundled Keycloak is one implementation.",
        "fields": (
            ("issuer", "Issuer URL", True, False, "https://id.example/realms/datariver"),
            ("jwks_url", "JWKS URL", True, False, "https://id.example/certs"),
            ("audience", "API audience", True, False, "datariver-api"),
        ),
    },
    "RETENTION_ARCHIVE": {
        "category": "STORAGE",
        "requirement": "FEATURE_CONNECTOR",
        "description": "Fail-closed retention scheduling and immutable archive execution controls.",
        "fields": (),
    },
    "DATAHUB_GMS": {
        "category": "CATALOG",
        "requirement": "CORE_CONNECTOR",
        "description": "Authoritative catalog provider for enrichment and governed apply.",
        "fields": (
            ("base_url", "Metadata endpoint", True, False, "https://datahub.example/api"),
            ("token", "Service token reference", True, True, None),
            ("expected_version", "Expected version", True, False, "v1.6.0"),
        ),
    },
    "DATAHUB_FRONTEND": {
        "category": "CATALOG",
        "requirement": "FEATURE_CONNECTOR",
        "description": "Optional DataHub link or separately reviewed embedded origin.",
        "fields": (("url", "Frontend URL", True, False, "https://datahub.example"),),
    },
    "AIRFLOW": {
        "category": "ORCHESTRATION",
        "requirement": "FEATURE_CONNECTOR",
        "description": "Optional scheduled and bulk workflow orchestrator.",
        "fields": (("base_url", "Airflow URL", True, False, "https://airflow.example"),),
    },
    "REDIS_CACHE": {
        "category": "PLATFORM",
        "requirement": "CORE_CONNECTOR",
        "description": "Evictable TTL cache; it must not share the delivery endpoint.",
        "fields": (
            ("url", "Redis URL", True, False, "rediss://redis-cache.example:6379/0"),
            ("password", "Password secret reference", True, True, None),
        ),
    },
    "REDIS_DELIVERY": {
        "category": "PLATFORM",
        "requirement": "CORE_CONNECTOR",
        "description": "No-eviction Redis Streams delivery; PostgreSQL remains canonical.",
        "fields": (
            ("url", "Redis URL", True, False, "rediss://redis-delivery.example:6379/0"),
            ("password", "Password secret reference", True, True, None),
        ),
    },
    "S3_STORAGE": {
        "category": "STORAGE",
        "requirement": "CORE_CONNECTOR",
        "description": "External MinIO/S3 endpoint for upload, validation and export objects.",
        "fields": (
            ("endpoint", "Private endpoint", True, False, "https://minio-api.example"),
            ("public_endpoint", "Browser endpoint", True, False, "https://objects.example"),
            ("region", "Region", True, False, "us-east-1"),
            ("buckets", "Bucket names", True, False, "quarantine/accepted/exports"),
            ("access_key", "Access key reference", True, True, None),
            ("secret_key", "Secret key reference", True, True, None),
        ),
    },
    "LLM_CHAT_MODEL": {
        "category": "AI",
        "requirement": "FEATURE_CONNECTOR",
        "description": "Optional approved OpenAI-compatible Chat model endpoint.",
        "fields": (
            ("connection_mode", "Connection Mode", True, False, "LOCAL_OLLAMA"),
            ("base_url", "Model endpoint", True, False, "https://llm.example/v1"),
            ("model", "Model Name", True, False, None),
            ("timeout_seconds", "Timeout (Seconds)", False, False, "60"),
            ("context_tokens", "Context Tokens", False, False, "8192"),
        ),
    },
    "LLM_EMBEDDING": {
        "category": "AI",
        "requirement": "FEATURE_CONNECTOR",
        "description": "Optional approved OpenAI-compatible embedding endpoint.",
        "fields": (
            ("connection_mode", "Connection Mode", True, False, "LOCAL_OLLAMA"),
            ("base_url", "Embedding endpoint", True, False, "https://llm.example/v1"),
            ("model", "Model Name", True, False, None),
            ("timeout_seconds", "Timeout (Seconds)", False, False, "60"),
        ),
    },
    "LLM_RERANKER": {
        "category": "AI",
        "requirement": "FEATURE_CONNECTOR",
        "description": (
            "Optional fixed /v1/rerank endpoint. Local development uses an Ollama-owned "
            "GGUF through llama-server; private deployments use the governed intranet contract."
        ),
        "fields": (
            ("connection_mode", "Connection Mode", True, False, "LOCAL_LLAMA_CPP"),
            ("base_url", "Reranker endpoint", True, False, "https://rerank.example/v1"),
            ("model", "Model Name", True, False, None),
            ("api_key", "Reranker API-key reference", True, True, None),
            ("top_n", "Top N", False, False, "10"),
        ),
    },
    "NEO4J": {
        "category": "CATALOG",
        "requirement": "FEATURE_CONNECTOR",
        "description": "Optional rebuildable graph query projection.",
        "fields": (
            ("uri", "Bolt/Neo4j URI", True, False, "neo4j://graph.example:7687"),
            ("database", "Database", True, False, "neo4j"),
            ("credential", "Credential reference", True, True, None),
        ),
    },
    "PROMETHEUS": {
        "category": "OBSERVABILITY",
        "requirement": "FEATURE_CONNECTOR",
        "description": "Optional metrics backend link.",
        "fields": (("base_url", "Prometheus URL", True, False, "https://metrics.example"),),
    },
    "GRAFANA_DASHBOARD": {
        "category": "OBSERVABILITY",
        "requirement": "FEATURE_CONNECTOR",
        "description": "Optional reviewed operations dashboard link or embed.",
        "fields": (("url", "Grafana URL", True, False, "https://grafana.example"),),
    },
}
_SENSITIVE_CONFIGURATION_KEY = re.compile(
    r"(?:^|[_-])(?:password|secret|token|credential|authorization|bearer|cookie|"
    r"api[_-]?key|private[_-]?key)(?:$|[_-])",
    re.IGNORECASE,
)
_MASKED_VALUE = "********"
_MAX_CONFIGURATION_BYTES = 65_536
_MAX_CONFIGURATION_DEPTH = 12
_MAX_CONFIGURATION_NODES = 512
_MAX_CONFIGURATION_SCALAR_BYTES = 32_768


def _yaml_document(value: str) -> dict[str, Any]:
    if len(value.encode("utf-8")) > _MAX_CONFIGURATION_BYTES:
        raise ValidationError("System configuration YAML exceeds the 64 KiB limit.")
    try:
        if any(isinstance(token, AliasToken | AnchorToken) for token in yaml.scan(value)):
            raise ValidationError("System configuration YAML aliases and anchors are forbidden.")
        document = yaml.safe_load(value)
    except yaml.YAMLError as error:
        raise ValidationError("System configuration must be valid YAML.") from error
    if not isinstance(document, dict):
        raise ValidationError("System configuration YAML must contain one mapping document.")
    pending: list[tuple[object, int]] = [(document, 1)]
    seen: set[int] = set()
    node_count = 0
    scalar_bytes = 0
    while pending:
        current, depth = pending.pop()
        node_count += 1
        if node_count > _MAX_CONFIGURATION_NODES:
            raise ValidationError("System configuration YAML exceeds the node limit.")
        if depth > _MAX_CONFIGURATION_DEPTH:
            raise ValidationError("System configuration YAML exceeds the nesting depth limit.")
        if isinstance(current, Mapping):
            identity = id(current)
            if identity in seen:
                raise ValidationError("System configuration YAML cannot contain recursive values.")
            seen.add(identity)
            for item_key, item_value in current.items():
                if not isinstance(item_key, str):
                    raise ValidationError("System configuration mapping keys must be strings.")
                scalar_bytes += len(item_key.encode("utf-8"))
                pending.append((item_value, depth + 1))
        elif isinstance(current, list):
            identity = id(current)
            if identity in seen:
                raise ValidationError("System configuration YAML cannot contain recursive values.")
            seen.add(identity)
            pending.extend((item, depth + 1) for item in current)
        elif isinstance(current, str):
            scalar_bytes += len(current.encode("utf-8"))
        elif current is not None and not isinstance(current, bool | int | float):
            raise ValidationError("System configuration YAML contains an unsupported value type.")
        if scalar_bytes > _MAX_CONFIGURATION_SCALAR_BYTES:
            raise ValidationError("System configuration YAML exceeds the scalar data limit.")
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


def _require_canonical_secret_contract(
    system_id: str,
    references: Mapping[str, str],
    *,
    connection_mode: object = None,
) -> None:
    try:
        require_canonical_secret_references(
            system_id,
            references,
            connection_mode=connection_mode,
        )
    except ValueError as error:
        raise ValidationError(str(error)) from error


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


def _configuration_endpoint(document: Mapping[str, Any], is_draft: bool = False) -> str | None:
    for key in ("url", "endpoint", "base_url"):
        value = document.get(key)
        if isinstance(value, str) and value.strip():
            normalized = value.strip()
            if is_draft and ("<" in normalized or ">" in normalized):
                return normalized
            parsed = urlsplit(normalized)
            if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
                if is_draft:
                    return normalized
                raise ValidationError("System configuration URL values must use HTTP or HTTPS.")
            if parsed.username is not None or parsed.password is not None:
                if is_draft:
                    return normalized
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


def _validate_option_value(key: str, value: object, template: object) -> None:
    if isinstance(template, bool):
        if not isinstance(value, bool):
            raise ValidationError(f"System configuration option {key} must be boolean.")
        return
    if isinstance(template, int):
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValidationError(f"System configuration option {key} must be an integer.")
        limits = {
            "circuit_failure_threshold": (1, 100),
            "circuit_open_seconds": (1, 3_600),
            "context_tokens": (256, 262_144),
            "maximum_concurrency": (1, 200),
            "maximum_connection_pool_size": (1, 200),
            "presigned_url_ttl_seconds": (60, 86_400),
            "queue_timeout_seconds": (1, 300),
            "stale_ttl_seconds": (1, 86_400),
            "timeout_seconds": (1, 300),
            "top_n": (1, 100),
            "version_probe_ttl_seconds": (1, 86_400),
            "connection_timeout_seconds": (1, 30),
        }
        lower, upper = limits.get(key, (0, 1_000_000))
        if value < lower or value > upper:
            raise ValidationError(
                f"System configuration option {key} must be between {lower} and {upper}."
            )
        return
    if isinstance(template, float):
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise ValidationError(f"System configuration option {key} must be numeric.")
        numeric_limits = {
            "connection_timeout_seconds": (1.0, 60.0),
            "timeout_seconds": (1.0, 300.0),
        }
        numeric_lower, numeric_upper = numeric_limits.get(key, (0.0, 1_000_000.0))
        if float(value) < numeric_lower or float(value) > numeric_upper:
            raise ValidationError(
                f"System configuration option {key} must be between "
                f"{numeric_lower:g} and {numeric_upper:g}."
            )
        return
    if isinstance(template, str):
        if not isinstance(value, str) or len(value) > 512:
            raise ValidationError(f"System configuration option {key} must be a short string.")
        fixed_values = {
            "api_style": template,
            "required_policy": template,
            "role": template,
        }
        if key in fixed_values and value != fixed_values[key]:
            raise ValidationError(f"System configuration option {key} is server-controlled.")
        if key == "version_enforcement" and value not in {"report", "enforce"}:
            raise ValidationError("System configuration version_enforcement is invalid.")
        return
    if isinstance(template, list):
        if (
            not isinstance(value, list)
            or len(value) > 20
            or any(not isinstance(item, str) or len(item) > 128 for item in value)
        ):
            raise ValidationError(
                f"System configuration option {key} must be a bounded string list."
            )
        return
    raise ValidationError(f"System configuration option {key} has no supported schema.")


def _validate_nested_configuration_schema(system_id: str, document: Mapping[str, Any]) -> None:
    template = _SYSTEM_CONFIGURATION_TEMPLATES[system_id]
    options = document.get("options")
    if not isinstance(options, Mapping):
        raise ValidationError("System configuration options must be one mapping.")
    option_template = template.get("options")
    if not isinstance(option_template, Mapping):
        raise ValidationError("The server-owned system configuration schema is invalid.")
    unknown_options = sorted(set(options) - set(option_template))
    if unknown_options:
        raise ValidationError(
            "System configuration contains unsupported option keys: "
            + ", ".join(str(value) for value in unknown_options)
        )
    for option_key, option_value in options.items():
        option_value_template = option_template[option_key]
        if (
            system_id == "LLM_CHAT_MODEL"
            and option_key == "api_style"
            and document.get("connection_mode") == "LOCAL_OLLAMA"
        ):
            option_value_template = "ollama_native_chat"
        _validate_option_value(
            str(option_key),
            option_value,
            option_value_template,
        )
    buckets = document.get("buckets")
    bucket_template = template.get("buckets")
    if buckets is not None:
        if not isinstance(buckets, Mapping) or not isinstance(bucket_template, Mapping):
            raise ValidationError("System configuration buckets must be one mapping.")
        unknown_buckets = sorted(set(buckets) - set(bucket_template))
        if unknown_buckets:
            raise ValidationError(
                "System configuration contains unsupported bucket keys: "
                + ", ".join(str(value) for value in unknown_buckets)
            )
        for bucket_key, bucket_value in buckets.items():
            if not isinstance(bucket_value, str) or len(bucket_value) > 255:
                raise ValidationError(
                    f"System configuration bucket {bucket_key} must be a short string."
                )


def _validate_system_configuration(
    system_id: str,
    document: Mapping[str, Any],
    is_draft: bool = False,
) -> str | None:
    allowed_top_level = set(_SYSTEM_CONFIGURATION_TEMPLATES[system_id]) | {"auth_principal"}
    unknown_keys = sorted(set(document) - allowed_top_level)
    if unknown_keys:
        raise ValidationError(
            "System configuration contains unsupported top-level keys: " + ", ".join(unknown_keys)
        )
    _secret_references(document.get("secret_references", {}))
    _validate_nested_configuration_schema(system_id, document)
    options = document["options"]
    assert isinstance(options, Mapping)
    if system_id == "NEO4J":
        uri = _require_non_empty_string(document, "uri")
        parsed = urlsplit(uri)
        if parsed.scheme not in {"bolt", "neo4j", "bolt+s", "neo4j+s"} or parsed.hostname is None:
            raise ValidationError(
                "Neo4j URI values must use bolt://, neo4j:// or their +s TLS variants."
            )
        if parsed.username is not None or parsed.password is not None:
            raise ValidationError("Credentials must not be embedded in the Neo4j URI.")
        _require_non_empty_string(document, "database")
        _require_canonical_secret_contract(
            system_id,
            _secret_references(document.get("secret_references", {})),
        )
        return None
    if system_id in {"REDIS_CACHE", "REDIS_DELIVERY"}:
        url = _require_non_empty_string(document, "url")
        parsed = urlsplit(url)
        if parsed.scheme not in {"redis", "rediss"} or parsed.hostname is None:
            raise ValidationError("Redis URL values must use redis:// or rediss://.")
        if parsed.username is not None or parsed.password is not None:
            raise ValidationError("Credentials must not be embedded in a Redis URL.")
        if parsed.query or parsed.fragment:
            raise ValidationError("A Redis URL must not contain a query or fragment.")
        secret_references = _secret_references(document.get("secret_references", {}))
        if set(secret_references) != {"password"}:
            raise ValidationError(
                "Redis configuration requires exactly one password secret reference."
            )
        _require_canonical_secret_contract(system_id, secret_references)
        return url
    endpoint = _configuration_endpoint(document, is_draft=is_draft)
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
        expected_api_style = (
            "ollama_native_chat"
            if system_id == "LLM_CHAT_MODEL" and connection_mode == "LOCAL_OLLAMA"
            else "openai_compatible"
        )
        if options.get("api_style") != expected_api_style:
            raise ValidationError(
                f"{system_id} with {connection_mode} requires api_style={expected_api_style}."
            )
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
        _require_canonical_secret_contract(
            system_id,
            secret_references,
            connection_mode=connection_mode,
        )
    if system_id == "LLM_RERANKER":
        connection_mode = document.get("connection_mode")
        if connection_mode not in {"LOCAL_LLAMA_CPP", "INTRANET_RERANK_V1"}:
            raise ValidationError("The reranker connection_mode is invalid.")
        parsed = urlsplit(endpoint)
        secret_references = _secret_references(document.get("secret_references", {}))
        if connection_mode == "LOCAL_LLAMA_CPP":
            if (
                parsed.scheme != "http"
                or parsed.hostname is None
                or parsed.port != 11435
                or parsed.path.rstrip("/") != "/v1"
                or parsed.query
                or parsed.fragment
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise ValidationError(
                    "The local llama.cpp reranker requires the fixed port-11435 /v1 endpoint."
                )
            if secret_references:
                raise ValidationError(
                    "The local llama.cpp reranker does not accept an API-key reference."
                )
        else:
            if parsed.scheme != "https" or parsed.path.rstrip("/") != "/v1":
                raise ValidationError(
                    "The private reranker requires an HTTPS endpoint ending in /v1."
                )
            if set(secret_references) != {"api_key"}:
                raise ValidationError(
                    "The private reranker requires exactly one api_key secret reference."
                )
        if options.get("api_style") != "rerank_v1":
            raise ValidationError("The reranker requires api_style=rerank_v1.")
        top_n = options.get("top_n")
        if not isinstance(top_n, int) or isinstance(top_n, bool) or not 1 <= top_n <= 100:
            raise ValidationError("The reranker top_n must be between 1 and 100.")
        _require_canonical_secret_contract(
            system_id,
            secret_references,
            connection_mode=connection_mode,
        )
    if system_id == "S3_STORAGE":
        _require_non_empty_string(document, "region")
        buckets = document.get("buckets")
        if not isinstance(buckets, Mapping):
            raise ValidationError("S3 configuration requires one buckets mapping.")
        for bucket_key in ("accepted", "exports", "quarantine"):
            _require_non_empty_string(buckets, bucket_key)
    if not system_id.startswith("LLM_"):
        _require_canonical_secret_contract(
            system_id,
            _secret_references(document.get("secret_references", {})),
        )
    return endpoint


def _role_marker(role_key: str) -> str:
    return f"datariver-role-{role_key}"


def _role_mutation_event(
    *,
    event_type: str,
    role: AccessRoleModel,
    actor_id: UUID,
    assurance: str,
    policy_decision_id: UUID,
    payload_hash: str | None = None,
) -> DomainEvent:
    payload: dict[str, object] = {
        "actor_id": str(actor_id),
        "policy_decision_id": str(policy_decision_id),
        "assurance": assurance,
        "role_key": role.role_key,
        "version": role.version,
    }
    if payload_hash is not None:
        payload["payload_hash"] = payload_hash
    return DomainEvent.create(
        event_type=event_type,
        aggregate_type="access_role",
        aggregate_id=role.id,
        workspace_id=role.workspace_id,
        payload=payload,
    )


def _effective_role_data_rules(
    payload: AccessRoleWriteRequest,
    *,
    current: tuple[AccessRoleDataRuleRequest, ...],
) -> tuple[AccessRoleDataRuleRequest, ...]:
    if "data_access_rules" not in payload.model_fields_set:
        return current
    return tuple(payload.data_access_rules)


def _role_document(
    payload: AccessRoleWriteRequest,
    *,
    data_access_rules: tuple[AccessRoleDataRuleRequest, ...],
) -> dict[str, object]:
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
        "data_access_rules": sorted(
            (_canonical_data_rule_document(rule) for rule in data_access_rules),
            key=lambda rule: str(rule["classification"]),
        ),
        "active": payload.active,
    }


def _stored_role_document(
    role: AccessRoleModel, rules: tuple[AccessRoleDataRuleModel, ...] = ()
) -> dict[str, object]:
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
        "data_access_rules": sorted(
            (_stored_data_rule_document(rule) for rule in rules),
            key=lambda rule: str(rule["classification"]),
        ),
        "active": role.active,
    }


async def _role_assigned_count(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    role_id: UUID,
    role_key: str,
) -> int:
    marker = _role_marker(role_key)
    assigned_subjects = (
        select(WorkspaceMembershipModel.subject_id)
        .where(
            WorkspaceMembershipModel.workspace_id == workspace_id,
            WorkspaceMembershipModel.attributes["groups"].contains([marker]),
            ~exists().where(
                AccessRoleAssignmentModel.workspace_id == workspace_id,
                AccessRoleAssignmentModel.subject_id == WorkspaceMembershipModel.subject_id,
                AccessRoleAssignmentModel.active.is_(True),
            ),
        )
        .union(
            select(AccessRoleAssignmentModel.subject_id).where(
                AccessRoleAssignmentModel.workspace_id == workspace_id,
                AccessRoleAssignmentModel.role_id == role_id,
                AccessRoleAssignmentModel.active.is_(True),
            )
        )
    )
    count = await session.scalar(select(func.count()).select_from(assigned_subjects.subquery()))
    return int(count or 0)


async def _role_assigned_counts(session: AsyncSession, *, workspace_id: UUID) -> dict[str, int]:
    rows = (
        await session.execute(
            text(
                """
                WITH assigned AS (
                    SELECT substring(marker.value FROM 16) AS role_key,
                        membership.subject_id
                    FROM iam.workspace_memberships AS membership
                    CROSS JOIN LATERAL jsonb_array_elements_text(
                        COALESCE(membership.attributes -> 'groups', '[]'::jsonb)
                    ) AS marker(value)
                    WHERE membership.workspace_id = :workspace_id
                      AND marker.value LIKE 'datariver-role-%'
                      AND NOT EXISTS (
                          SELECT 1
                          FROM iam.access_role_assignments AS current_assignment
                          WHERE current_assignment.workspace_id = membership.workspace_id
                            AND current_assignment.subject_id = membership.subject_id
                            AND current_assignment.active IS TRUE
                      )
                    UNION
                    SELECT role.role_key, assignment.subject_id
                    FROM iam.access_role_assignments AS assignment
                    JOIN iam.access_roles AS role
                      ON role.workspace_id = assignment.workspace_id
                     AND role.id = assignment.role_id
                    WHERE assignment.workspace_id = :workspace_id
                      AND assignment.active IS TRUE
                )
                SELECT role_key, count(*) AS assigned_count
                FROM assigned
                GROUP BY role_key
                """
            ),
            {"workspace_id": workspace_id},
        )
    ).all()
    return {str(role_key): int(count) for role_key, count in rows}


def _stored_data_rule_document(rule: AccessRoleDataRuleModel) -> dict[str, object]:
    return {
        "classification": Classification(rule.classification).name,
        "access_level": rule.access_level,
        "partial_treatment": rule.partial_treatment,
        "allowed_residency_regions": sorted(rule.allowed_residency_regions),
        "allowed_processing_purposes": sorted(rule.allowed_processing_purposes),
    }


def _canonical_data_rule_document(rule: AccessRoleDataRuleRequest) -> dict[str, object]:
    return RoleDataAccessRule(
        classification=Classification[rule.classification],
        access_level=DataAccessLevel(rule.access_level),
        partial_treatment=(
            PartialAccessTreatment(rule.partial_treatment)
            if rule.partial_treatment is not None
            else None
        ),
        allowed_residency_regions=tuple(rule.allowed_residency_regions),
        allowed_processing_purposes=frozenset(
            DataProcessingPurpose(value) for value in rule.allowed_processing_purposes
        ),
    ).payload_document()


def _data_rule_models(
    *,
    role: AccessRoleModel,
    rules: tuple[AccessRoleDataRuleRequest, ...],
    created_by: UUID,
) -> list[AccessRoleDataRuleModel]:
    models: list[AccessRoleDataRuleModel] = []
    for rule in rules:
        document = _canonical_data_rule_document(rule)
        models.append(
            AccessRoleDataRuleModel(
                workspace_id=role.workspace_id,
                role_id=role.id,
                role_version=role.version,
                classification=int(Classification[rule.classification]),
                access_level=rule.access_level,
                partial_treatment=rule.partial_treatment,
                allowed_residency_regions=sorted(rule.allowed_residency_regions),
                allowed_processing_purposes=sorted(rule.allowed_processing_purposes),
                payload_hash=canonical_json_hash(document),
                created_by=created_by,
            )
        )
    return models


def _role_response(
    role: AccessRoleModel,
    *,
    assigned_count: int,
    rules: tuple[AccessRoleDataRuleModel, ...] = (),
) -> AccessRoleResponse:
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
            data_access_rules=[
                AccessRoleDataRuleRequest.model_validate(_stored_data_rule_document(rule))
                for rule in sorted(rules, key=lambda value: value.classification)
            ],
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
) -> list[SystemConfigurationEntryResponse]:
    deployment_configured = {
        "PLATFORM_RUNTIME": True,
        "POSTGRESQL": True,
        "OIDC_IDENTITY": True,
        "RETENTION_ARCHIVE": True,
        "DATAHUB_GMS": True,
        "DATAHUB_FRONTEND": settings.ui_datahub_url is not None,
        "AIRFLOW": settings.ui_airflow_url is not None,
        "REDIS_CACHE": True,
        "REDIS_DELIVERY": True,
        "S3_STORAGE": True,
        "LLM_CHAT_MODEL": (
            settings.local_ollama_chat_enabled or settings.intranet_openai_compatible_chat_enabled
        ),
        "LLM_EMBEDDING": (
            settings.local_ollama_embedding_enabled
            or settings.intranet_openai_compatible_embedding_enabled
        ),
        "LLM_RERANKER": settings.local_llama_cpp_reranker_enabled,
        "NEO4J": settings.neo4j_projection_enabled,
        "PROMETHEUS": settings.ui_prometheus_url is not None,
        "GRAFANA_DASHBOARD": settings.ui_grafana_url is not None,
    }
    deployment_secret_configured: dict[str, bool] = {
        "POSTGRESQL": bool(settings.database_secret_ref),
        "OIDC_IDENTITY": False,
        "DATAHUB_GMS": bool(settings.datahub_secret_ref),
        "REDIS_CACHE": bool(settings.redis_cache_secret_ref),
        "REDIS_DELIVERY": bool(settings.redis_delivery_secret_ref),
        "S3_STORAGE": bool(settings.s3_access_key_file and settings.s3_secret_key_file),
        "NEO4J": bool(settings.neo4j_auth_secret_ref),
    }
    entries: list[SystemConfigurationEntryResponse] = []
    for system_id, _service_key, label in _SYSTEM_CONFIGURATION:
        restart_scope = _RUNTIME_RESTART_SCOPE.get(system_id, "NOT_IMPLEMENTED")
        runtime_supported = system_id in _RUNTIME_RESTART_SCOPE
        if system_id in {
            "PLATFORM_RUNTIME",
            "POSTGRESQL",
            "OIDC_IDENTITY",
            "RETENTION_ARCHIVE",
        }:
            state = "CONFIGURED"
            embedding_state = "NOT_APPLICABLE"
        else:
            static_configured = deployment_configured.get(system_id, False)
            if static_configured:
                state = "CONFIGURED"
            else:
                state = "NOT_CONFIGURED"
            if system_id == "GRAFANA_DASHBOARD":
                embedding_state = (
                    "AVAILABLE" if settings.grafana_embed_url() is not None else "NOT_CONFIGURED"
                )
            else:
                embedding_state = "NOT_APPLICABLE"
        management_plane = "DEPLOYMENT"
        environment_template = "\n".join(f"{key}=" for key in _SYSTEM_ENVIRONMENT_KEYS[system_id])
        effective_document = _deployment_display_document(settings, system_id)
        effective_configuration_yaml = (
            _render_yaml(_display_configuration(effective_document))
            if effective_document is not None
            else ""
        )
        metadata = _SYSTEM_METADATA[system_id]
        requirements = [
            SystemConnectionRequirementResponse(
                key=key,
                label=field_label,
                required=required,
                secret=secret,
                example=example,
            )
            for key, field_label, required, secret, example in metadata["fields"]
        ]
        entries.append(
            SystemConfigurationEntryResponse(
                system_id=system_id,
                label=label,
                category=metadata["category"],
                requirement=metadata["requirement"],
                description=metadata["description"],
                connection_requirements=requirements,
                state=state,
                management_plane=management_plane,
                secret_reference_configured=deployment_secret_configured.get(system_id, False),
                embedding_state=embedding_state,
                configuration_yaml="",
                template_yaml="",
                display_yaml=effective_configuration_yaml,
                environment_template=environment_template,
                effective_configuration_yaml=effective_configuration_yaml,
                version=0,
                configured_at=None,
                runtime_supported=runtime_supported,
                restart_scope=restart_scope,
                activation_state="DEPLOYMENT_MANAGED",
                tested_version=None,
                test_status=None,
                tested_at=None,
                activated_version=None,
                activated_at=None,
                applied_version=None,
                is_core=system_id
                in {
                    "POSTGRESQL",
                    "PLATFORM_RUNTIME",
                    "OIDC_IDENTITY",
                    "RETENTION_ARCHIVE",
                    "DATAHUB_GMS",
                    "DATAHUB_FRONTEND",
                    "REDIS_CACHE",
                    "REDIS_DELIVERY",
                },
            )
        )
    return entries


def _system_configuration_revision_keys(
    profiles: Sequence[ExternalServiceProfileModel],
) -> set[tuple[UUID, int]]:
    return {
        (profile.id, configuration_version)
        for profile in profiles
        for configuration_version in (profile.version, profile.activated_version)
        if configuration_version is not None
    }


def _require_system_configuration_runtime_activation(settings: Settings) -> None:
    if settings.app_env != "development":
        raise ForbiddenError(
            "Database-backed system configuration activation is available only in development."
        )
    if not settings.system_configuration_runtime_activation_enabled:
        raise ConflictError(
            "Runtime activation is disabled; deployment environment and secret files are the "
            "source of truth."
        )


def _service(request: Request) -> AdminAccessService:
    container = get_container(request)
    authorization = AuthorizationService(
        decision_writer=SqlDecisionWriter(container.database.session_factory),
        development_admin_password_bypass_enabled=(
            container.settings.development_admin_password_bypass_enabled
        ),
    )
    return AdminAccessService(
        lambda: SqlAdminAccessUnitOfWork(container.database.session_factory),
        authorization,
        fallback_enabled=container.settings.admin_password_fallback_enabled,
        fallback_ttl_seconds=container.settings.admin_password_fallback_ttl_seconds,
        development_admin_password_bypass_enabled=(
            container.settings.development_admin_password_bypass_enabled
        ),
        development_system_configuration_enabled=container.settings.app_env == "development",
        identity_administration_enabled=container.identity_admin is not None,
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


def _system_assignee_patch_command(
    *,
    workspace_id: UUID,
    system_id: UUID,
    expected_system_version: int,
    payload: SystemAssigneePatchRequest,
) -> SystemAssigneePatchCommand:
    try:
        return SystemAssigneePatchCommand(
            workspace_id=workspace_id,
            system_id=system_id,
            expected_system_version=expected_system_version,
            upserts=tuple(
                SystemAssigneeUpdate(
                    subject_id=item.subject_id,
                    responsibility=item.responsibility,
                    priority=item.priority,
                )
                for item in payload.upserts
            ),
            removals=tuple(
                SystemAssigneeKey(
                    subject_id=item.subject_id,
                    responsibility=item.responsibility,
                )
                for item in payload.removals
            ),
        )
    except (TypeError, ValueError) as error:
        raise ValidationError("The system-assignee patch document is invalid.") from error


@router.get("/me", response_model=AdminReadContextResponse)
async def get_admin_context(
    request: Request,
    response: Response,
    context: ContextDep,
) -> AdminReadContextResponse:
    value = await _service(request).get_admin_read_context(
        workspace_id=context.workspace_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return admin_read_context_response(value)


@router.get("/workspace-memberships", response_model=WorkspaceMembershipListResponse)
async def list_workspace_memberships(
    request: Request,
    context: ContextDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    status: Literal["ACTIVE", "INACTIVE"] | None = None,
    cursor: Annotated[str | None, Query(max_length=2000)] = None,
) -> WorkspaceMembershipListResponse:
    page = await _service(request).list_workspace_memberships(
        workspace_id=context.workspace_id,
        limit=limit,
        query=q,
        active=(status == "ACTIVE" if status is not None else None),
        cursor=cursor,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return WorkspaceMembershipListResponse(
        items=[workspace_membership_summary_response(value) for value in page.items],
        page=PageMeta(next_cursor=page.next_cursor, limit=limit),
    )


@router.get(
    "/workspace-memberships/{target_subject_id}/change-requests",
    response_model=MembershipChangeRequestActivityListResponse,
)
async def list_membership_change_request_activity(
    target_subject_id: UUID,
    request: Request,
    context: ContextDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
    cursor: Annotated[str | None, Query(max_length=2000)] = None,
) -> MembershipChangeRequestActivityListResponse:
    page = await _service(request).list_membership_change_request_activity(
        workspace_id=context.workspace_id,
        target_subject_id=target_subject_id,
        limit=limit,
        cursor=cursor,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return MembershipChangeRequestActivityListResponse(
        items=[
            MembershipChangeRequestActivityResponse(
                change_request_id=item.change_request_id,
                number=item.number,
                title=item.title,
                request_type=item.request_type,
                state=item.state,
                relationship=item.relationship,
                classification=item.classification.name,
                updated_at=item.updated_at,
            )
            for item in page.items
        ],
        page=PageMeta(next_cursor=page.next_cursor, limit=limit),
    )


@router.get(
    "/workspace-memberships/{target_subject_id}/owned-tables",
    response_model=MembershipOwnedTableListResponse,
)
async def list_membership_owned_tables(
    target_subject_id: UUID,
    request: Request,
    context: ContextDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
    cursor: Annotated[str | None, Query(max_length=2000)] = None,
) -> MembershipOwnedTableListResponse:
    page = await _service(request).list_membership_owned_tables(
        workspace_id=context.workspace_id,
        target_subject_id=target_subject_id,
        limit=limit,
        cursor=cursor,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return MembershipOwnedTableListResponse(
        items=[
            MembershipOwnedTableResponse(
                asset_id=item.asset_id,
                name=item.name,
                platform=item.platform,
                database_name=item.database_name,
                schema_name=item.schema_name,
                classification=item.classification.name,
                source_version=item.source_version,
                observed_at=item.observed_at,
            )
            for item in page.items
        ],
        page=PageMeta(next_cursor=page.next_cursor, limit=limit),
    )


@router.post(
    "/identity-users",
    response_model=IdentityUserProvisionResponse,
    status_code=201,
)
async def provision_identity_user(
    payload: IdentityUserProvisionRequest,
    request: Request,
    context: ContextDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> IdentityUserProvisionResponse:
    container = get_container(request)
    if container.identity_admin is None:
        raise ForbiddenError("Identity administration is not enabled for this deployment.")
    profile_document = {
        "workspace_id": str(context.workspace_id),
        "username": payload.username,
        "email": payload.email,
        "first_name": payload.first_name,
        "last_name": payload.last_name,
        "department_id": str(payload.department_id) if payload.department_id else None,
        "job_function": payload.job_function,
        "role_id": str(payload.role_id) if payload.role_id else None,
    }
    request_hash = canonical_json_hash(profile_document)
    provisioning_reference = canonical_json_hash(
        {
            "workspace_id": str(context.workspace_id),
            "idempotency_key": idempotency_key,
        }
    )
    result = await IdentityAdminService(
        uow_factory=lambda: SqlAdminAccessUnitOfWork(container.database.session_factory),
        authorization=AuthorizationService(
            decision_writer=SqlDecisionWriter(container.database.session_factory),
            development_admin_password_bypass_enabled=(
                container.settings.development_admin_password_bypass_enabled
            ),
        ),
        provider=container.identity_admin,
        issuer=container.settings.oidc_issuer,
    ).provision_user(
        draft=IdentityUserDraft(
            username=payload.username,
            email=payload.email,
            first_name=payload.first_name,
            last_name=payload.last_name,
            temporary_password=payload.temporary_password.get_secret_value(),
            workspace_id=context.workspace_id,
            provisioning_reference=provisioning_reference,
        ),
        department_id=payload.department_id,
        job_function=payload.job_function,
        role_id=payload.role_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    return IdentityUserProvisionResponse(
        subject_id=result.subject_id,
        username=result.username,
        display_name=result.display_name,
        email=result.email,
        workspace_id=result.workspace_id,
        role_id=result.role_id,
        access_expires_at=result.access_expires_at,
        temporary_password_required=result.temporary_password_required,
    )


@router.get("/access-roles", response_model=AccessRoleListResponse)
async def list_access_roles(
    request: Request,
    context: ContextDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    status: Literal["ACTIVE", "INACTIVE"] | None = None,
    cursor: Annotated[str | None, Query(max_length=2000)] = None,
) -> AccessRoleListResponse:
    admin_context = await _service(request).get_admin_read_context(
        workspace_id=context.workspace_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if "MEMBERSHIP_ACCESS_READ" not in admin_context.allowed_operations:
        raise ForbiddenError("Access-role definitions are not available for this administrator.")
    normalized_query = q.strip().lower() if q and q.strip() else None
    active = status == "ACTIVE" if status is not None else None
    filters = {"query": normalized_query, "active": active}
    container = get_container(request)
    async with container.database.session_factory() as session:
        async with session.begin():
            await set_security_context(
                session,
                workspace_id=context.workspace_id,
                subject_id=context.subject.subject_id,
            )
            statement = (
                select(AccessRoleModel)
                .where(AccessRoleModel.workspace_id == context.workspace_id)
                .order_by(AccessRoleModel.id.desc())
                .limit(limit + 1)
            )
            if normalized_query is not None:
                escaped_query = (
                    normalized_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                )
                pattern = f"%{escaped_query}%"
                statement = statement.where(
                    or_(
                        AccessRoleModel.name.ilike(pattern, escape="\\"),
                        AccessRoleModel.role_key.ilike(pattern, escape="\\"),
                    )
                )
            if active is not None:
                statement = statement.where(AccessRoleModel.active.is_(active))
            if cursor is not None:
                boundary_id = decode_admin_list_cursor(
                    cursor,
                    scope="ACCESS_ROLES",
                    workspace_id=context.workspace_id,
                    filters=filters,
                )
                statement = statement.where(AccessRoleModel.id < boundary_id)
            rows = (await session.scalars(statement)).all()
            has_more = len(rows) > limit
            roles = rows[:limit]
            role_ids = [role.id for role in roles]
            current_role_versions = [(role.id, role.version) for role in roles]
            stored_rules = (
                (
                    await session.scalars(
                        select(AccessRoleDataRuleModel).where(
                            AccessRoleDataRuleModel.workspace_id == context.workspace_id,
                            tuple_(
                                AccessRoleDataRuleModel.role_id,
                                AccessRoleDataRuleModel.role_version,
                            ).in_(current_role_versions),
                        )
                    )
                ).all()
                if role_ids
                else []
            )
            rules_by_role_version: dict[tuple[UUID, int], list[AccessRoleDataRuleModel]] = {}
            for rule in stored_rules:
                rules_by_role_version.setdefault((rule.role_id, rule.role_version), []).append(rule)
            assigned_counts = await _role_assigned_counts(
                session, workspace_id=context.workspace_id
            )
            items = [
                _role_response(
                    role,
                    assigned_count=assigned_counts.get(role.role_key, 0),
                    rules=tuple(rules_by_role_version.get((role.id, role.version), [])),
                )
                for role in roles
            ]
    return AccessRoleListResponse(
        items=items,
        page=PageMeta(
            next_cursor=(
                encode_admin_list_cursor(
                    scope="ACCESS_ROLES",
                    workspace_id=context.workspace_id,
                    filters=filters,
                    boundary_id=roles[-1].id,
                )
                if has_more
                else None
            ),
            limit=limit,
        ),
    )


@router.post("/access-roles", response_model=AccessRoleResponse, status_code=201)
async def create_access_role(
    payload: AccessRoleWriteRequest,
    request: Request,
    context: ContextDep,
) -> AccessRoleResponse:
    policy_decision_id = await _service(request).authorize_access_role_mutation(
        workspace_id=context.workspace_id,
        role_id=context.workspace_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if not payload.name.strip():
        raise ValidationError("Access-role name must not be blank.")
    requested_rules = _effective_role_data_rules(payload, current=())
    container = get_container(request)
    async with container.database.session_factory() as session:
        async with session.begin():
            await set_security_context(
                session,
                workspace_id=context.workspace_id,
                subject_id=context.subject.subject_id,
            )
            await SqlMembershipAccessRepository(session).assert_eligible_human_administrators(
                workspace_id=context.workspace_id,
                subject_ids=frozenset({context.subject.subject_id}),
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
            session.add_all(
                _data_rule_models(
                    role=role,
                    rules=requested_rules,
                    created_by=context.subject.subject_id,
                )
            )
            await SqlOutboxWriter(session).add_events(
                [
                    _role_mutation_event(
                        event_type="iam.access_role.created.v1",
                        role=role,
                        actor_id=context.subject.subject_id,
                        assurance=context.subject.authentication_assurance.value,
                        policy_decision_id=policy_decision_id,
                        payload_hash=canonical_json_hash(
                            _role_document(payload, data_access_rules=requested_rules)
                        ),
                    )
                ]
            )
            await session.flush()
            rules = tuple(
                (
                    await session.scalars(
                        select(AccessRoleDataRuleModel).where(
                            AccessRoleDataRuleModel.workspace_id == context.workspace_id,
                            AccessRoleDataRuleModel.role_id == role.id,
                            AccessRoleDataRuleModel.role_version == role.version,
                        )
                    )
                ).all()
            )
            result = _role_response(role, assigned_count=0, rules=rules)
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
    policy_decision_id = await _service(request).authorize_access_role_mutation(
        workspace_id=context.workspace_id,
        role_id=role_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
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
            await SqlMembershipAccessRepository(session).assert_eligible_human_administrators(
                workspace_id=context.workspace_id,
                subject_ids=frozenset({context.subject.subject_id}),
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
                role_id=role.id,
                role_key=role.role_key,
            )
            current_rules = tuple(
                (
                    await session.scalars(
                        select(AccessRoleDataRuleModel).where(
                            AccessRoleDataRuleModel.workspace_id == context.workspace_id,
                            AccessRoleDataRuleModel.role_id == role.id,
                            AccessRoleDataRuleModel.role_version == role.version,
                        )
                    )
                ).all()
            )
            current_rule_requests = tuple(
                AccessRoleDataRuleRequest.model_validate(_stored_data_rule_document(rule))
                for rule in sorted(current_rules, key=lambda value: value.classification)
            )
            effective_rules = _effective_role_data_rules(
                payload,
                current=current_rule_requests,
            )
            security_keys = {
                "clearance",
                "groups",
                "allowed_actions",
                "denied_actions",
                "allowed_system_ids",
                "allowed_domain_ids",
                "active",
                "data_access_rules",
            }
            current_document = _stored_role_document(role, current_rules)
            next_document = _role_document(payload, data_access_rules=effective_rules)
            if assigned_count and any(
                current_document[key] != next_document[key] for key in security_keys
            ):
                raise ConflictError(
                    "Reassign all users before changing an in-use role security definition."
                )
            _apply_role_payload(role, payload=payload, updated_by=context.subject.subject_id)
            role.version += 1
            await session.flush()
            next_rules = _data_rule_models(
                role=role,
                rules=effective_rules,
                created_by=context.subject.subject_id,
            )
            session.add_all(next_rules)
            await SqlOutboxWriter(session).add_events(
                [
                    _role_mutation_event(
                        event_type="iam.access_role.updated.v1",
                        role=role,
                        actor_id=context.subject.subject_id,
                        assurance=context.subject.authentication_assurance.value,
                        policy_decision_id=policy_decision_id,
                        payload_hash=canonical_json_hash(next_document),
                    )
                ]
            )
            result = _role_response(role, assigned_count=assigned_count, rules=tuple(next_rules))
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
    policy_decision_id = await _service(request).authorize_access_role_mutation(
        workspace_id=context.workspace_id,
        role_id=role_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    expected_version = _expected_version(if_match)
    container = get_container(request)
    async with container.database.session_factory() as session:
        async with session.begin():
            await set_security_context(
                session,
                workspace_id=context.workspace_id,
                subject_id=context.subject.subject_id,
            )
            await SqlMembershipAccessRepository(session).assert_eligible_human_administrators(
                workspace_id=context.workspace_id,
                subject_ids=frozenset({context.subject.subject_id}),
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
                role_id=role.id,
                role_key=role.role_key,
            )
            if assigned_count:
                raise ConflictError("Reassign all users before deactivating an access role.")
            role.active = False
            role.updated_by = context.subject.subject_id
            role.version += 1
            await session.flush()
            previous_rules = tuple(
                (
                    await session.scalars(
                        select(AccessRoleDataRuleModel).where(
                            AccessRoleDataRuleModel.workspace_id == context.workspace_id,
                            AccessRoleDataRuleModel.role_id == role.id,
                            AccessRoleDataRuleModel.role_version == role.version - 1,
                        )
                    )
                ).all()
            )
            copied_rules = [
                AccessRoleDataRuleModel(
                    workspace_id=rule.workspace_id,
                    role_id=rule.role_id,
                    role_version=role.version,
                    classification=rule.classification,
                    access_level=rule.access_level,
                    partial_treatment=rule.partial_treatment,
                    allowed_residency_regions=rule.allowed_residency_regions,
                    allowed_processing_purposes=rule.allowed_processing_purposes,
                    payload_hash=rule.payload_hash,
                    created_by=context.subject.subject_id,
                )
                for rule in previous_rules
            ]
            session.add_all(copied_rules)
            await SqlOutboxWriter(session).add_events(
                [
                    _role_mutation_event(
                        event_type="iam.access_role.deactivated.v1",
                        role=role,
                        actor_id=context.subject.subject_id,
                        assurance=context.subject.authentication_assurance.value,
                        policy_decision_id=policy_decision_id,
                    )
                ]
            )
            result = _role_response(role, assigned_count=0, rules=tuple(copied_rules))
    response.headers["ETag"] = f'"{result.version}"'
    return result


@router.get("/systems", response_model=SystemDirectoryListResponse)
async def list_systems(
    request: Request,
    context: ContextDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    status: Literal["ACTIVE", "INACTIVE"] | None = None,
    cursor: Annotated[str | None, Query(max_length=2000)] = None,
) -> SystemDirectoryListResponse:
    page = await _service(request).list_systems(
        workspace_id=context.workspace_id,
        limit=limit,
        query=q,
        active=(status == "ACTIVE" if status is not None else None),
        cursor=cursor,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return SystemDirectoryListResponse(
        items=[
            SystemDirectoryEntryResponse(
                system_id=entry.system_id,
                code=entry.code,
                name=entry.name,
                description=entry.description,
                active=entry.active,
                version=entry.version,
                assignees=[
                    SystemDirectoryAssigneeResponse(
                        subject_id=assignee.subject_id,
                        responsibility=assignee.responsibility,
                        priority=assignee.priority,
                        display_name=assignee.display_name,
                        active=assignee.active,
                    )
                    for assignee in entry.assignees
                ],
                assignee_count=entry.assignee_count,
            )
            for entry in page.items
        ],
        page=PageMeta(next_cursor=page.next_cursor, limit=limit),
    )


@router.post("/systems", response_model=SystemDirectoryEntryResponse)
async def create_system(
    request: Request,
    context: ContextDep,
    body: SystemCreateRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> SystemDirectoryEntryResponse:
    request_hash = canonical_json_hash(
        {
            "operation": "admin.system.create",
            "code": body.code.strip(),
            "name": body.name.strip(),
            "description": body.description.strip(),
        }
    )
    entry = await _service(request).create_system(
        workspace_id=context.workspace_id,
        code=body.code,
        name=body.name,
        description=body.description,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    return SystemDirectoryEntryResponse(
        system_id=entry.system_id,
        code=entry.code,
        name=entry.name,
        description=entry.description,
        active=entry.active,
        version=entry.version,
        assignees=[],
        assignee_count=0,
    )


@router.get(
    "/systems/{system_id}/assignees",
    response_model=SystemAssigneeListResponse,
)
async def list_system_assignees(
    system_id: UUID,
    request: Request,
    context: ContextDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=2000)] = None,
) -> SystemAssigneeListResponse:
    page = await _service(request).list_system_assignees(
        workspace_id=context.workspace_id,
        system_id=system_id,
        limit=limit,
        cursor=cursor,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return SystemAssigneeListResponse(
        system_version=page.system_version,
        items=[
            {
                "subject_id": assignee.subject_id,
                "display_name": assignee.display_name,
                "responsibility": assignee.responsibility,
                "priority": assignee.priority,
                "active": assignee.active,
            }
            for assignee in page.items
        ],
        page=PageMeta(next_cursor=page.next_cursor, limit=limit),
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


@router.patch(
    "/systems/{system_id}/assignees",
    response_model=SystemAssigneeUpdateResponse,
    responses={
        200: {
            "headers": {
                "ETag": {
                    "description": "Current system version after the assignment patch.",
                    "schema": {"type": "string"},
                }
            }
        }
    },
)
async def patch_system_assignees(
    system_id: UUID,
    payload: SystemAssigneePatchRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> SystemAssigneeUpdateResponse:
    command = _system_assignee_patch_command(
        workspace_id=context.workspace_id,
        system_id=system_id,
        expected_system_version=_expected_version(if_match),
        payload=payload,
    )
    request_hash = canonical_json_hash(
        {"operation": "admin.system.assignees.patch", "command": command.command_document()}
    )
    system_version = await _service(request).patch_system_assignees_with_hardware_key(
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
    response: Response,
    context: ContextDep,
) -> SystemConfigurationListResponse:
    response.headers["Cache-Control"] = "no-store, private"
    admin_context = await _service(request).get_admin_read_context(
        workspace_id=context.workspace_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if "SYSTEM_CONFIGURATION_READ" not in admin_context.allowed_operations:
        raise ForbiddenError("System configuration access is not available for this administrator.")
    container = get_container(request)
    return SystemConfigurationListResponse(items=_system_configuration_entries(container.settings))


async def list_system_configuration_versions(
    system_id: str,
    request: Request,
    context: ContextDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> SystemConfigurationVersionListResponse:
    """Return bounded non-secret SAVE/TEST/ACTIVATE history for one connector."""

    raise ForbiddenError(
        "Database-backed system configuration history is retired and deployment-managed."
    )
    container = get_container(request)
    if container.settings.app_env != "development":
        raise ForbiddenError(
            "Database-backed system configuration history is available only in development."
        )
    if system_id not in _CONFIGURATION_BY_ID:
        raise ValidationError(
            "The system configuration identifier is invalid or deployment-managed."
        )
    admin_context = await _service(request).get_admin_read_context(
        workspace_id=context.workspace_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if "SYSTEM_CONFIGURATION_READ" not in admin_context.allowed_operations:
        raise ForbiddenError("System configuration access is not available for this administrator.")
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
                    )
                )
            ).one_or_none()
            if profile is None:
                return SystemConfigurationVersionListResponse(
                    system_id=system_id,
                    current_version=0,
                    activated_version=None,
                    items=[],
                )
            revisions = (
                await session.scalars(
                    select(ExternalServiceProfileVersionModel)
                    .where(
                        ExternalServiceProfileVersionModel.workspace_id == context.workspace_id,
                        ExternalServiceProfileVersionModel.profile_id == profile.id,
                    )
                    .order_by(ExternalServiceProfileVersionModel.configuration_version.desc())
                    .limit(limit)
                )
            ).all()
            return SystemConfigurationVersionListResponse(
                system_id=system_id,
                current_version=profile.version,
                activated_version=profile.activated_version,
                items=[
                    SystemConfigurationVersionResponse(
                        configuration_version=revision.configuration_version,
                        configuration_hash=revision.configuration_hash,
                        created_by=revision.created_by,
                        created_at=revision.created_at,
                        test_status=revision.test_status,
                        test_scope=revision.test_scope,
                        test_latency_ms=revision.test_latency_ms,
                        tested_by=revision.tested_by,
                        tested_at=revision.tested_at,
                        activated_by=revision.activated_by,
                        activated_at=revision.activated_at,
                        current=revision.configuration_version == profile.version,
                        activated=revision.configuration_version == profile.activated_version,
                    )
                    for revision in revisions
                ],
            )


async def update_system_configuration(
    system_id: str,
    payload: SystemConfigurationUpdateRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
) -> SystemConfigurationEntryResponse:
    raise ForbiddenError(
        "Database-backed system configuration writes are retired and deployment-managed."
    )
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
    metadata = _SYSTEM_METADATA[system_id]
    return SystemConfigurationEntryResponse(
        system_id=system_id,
        label=label,
        category=metadata["category"],
        requirement=metadata["requirement"],
        description=metadata["description"],
        connection_requirements=[
            SystemConnectionRequirementResponse(
                key=key,
                label=field_label,
                required=required,
                secret=secret,
                example=example,
            )
            for key, field_label, required, secret, example in metadata["fields"]
        ],
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


async def test_draft_system_configuration(
    system_id: str,
    request: Request,
    response: Response,
    context: ContextDep,
    body: SystemConfigurationUpdateRequest,
) -> SystemConfigurationTestResponse:
    """Probe an unsaved development profile."""
    raise ForbiddenError(
        "Browser-authored system configuration probes are retired and deployment-managed."
    )
    container = get_container(request)
    if container.settings.app_env != "development":
        raise ForbiddenError("System configuration testing is available only in development.")
    if system_id not in _CONFIGURATION_BY_ID:
        raise ValidationError("The system configuration identifier is invalid.")
    admin_context = await _service(request).get_admin_read_context(
        workspace_id=context.workspace_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if "SYSTEM_CONFIGURATION_READ" not in admin_context.allowed_operations:
        raise ForbiddenError(
            "System configuration testing is not available for this administrator."
        )

    tested_document = _yaml_document(body.configuration_yaml)
    _validate_system_configuration(system_id, tested_document, is_draft=True)
    result = await probe_system_configuration(
        system_id=system_id,
        document=tested_document,
        secret_resolver=SecretResolver(
            virtual_secret_root=container.settings.system_configuration_secret_root
        ),
        allowed_hosts=container.settings.system_configuration_probe_allowed_hosts,
    )
    response.headers["Cache-Control"] = "no-store, private"
    return SystemConfigurationTestResponse(
        system_id=system_id,
        status=result.status,
        scope=result.scope,
        latency_ms=result.latency_ms,
        detail=result.detail,
        configuration_version=None,
        tested_at=utc_now(),
    )


async def test_system_configuration(
    system_id: str,
    request: Request,
    response: Response,
    context: ContextDep,
) -> SystemConfigurationTestResponse:
    """Probe only a saved development profile through one fixed connector route."""

    raise ForbiddenError(
        "Database-backed system configuration probes are retired and deployment-managed."
    )
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
    tested_document = _yaml_document(tested_yaml)
    _validate_system_configuration(system_id, tested_document)
    result = await probe_system_configuration(
        system_id=system_id,
        document=tested_document,
        secret_resolver=SecretResolver(
            virtual_secret_root=container.settings.system_configuration_secret_root
        ),
        allowed_hosts=container.settings.system_configuration_probe_allowed_hosts,
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


def _file_secret_reference(value: str) -> str:
    """Render one deployment-owned secret path as the portable probe contract."""

    return value if value.startswith("file:") else f"file:{value}"


def _deployment_display_document(
    settings: Settings,
    system_id: str,
) -> dict[str, Any] | None:
    """Return the effective typed Settings view without returning credential values."""

    if system_id == "POSTGRESQL":
        parsed = urlsplit(settings.database_url)
        return {
            "database": parsed.path.lstrip("/"),
            "host": parsed.hostname or "",
            "port": parsed.port,
            "role": parsed.username or "",
            "secret_reference": settings.database_secret_ref,
            "pool": {
                "max_overflow": settings.database_pool_max_overflow,
                "size": settings.database_pool_size,
                "timeout_seconds": settings.database_pool_timeout_seconds,
            },
        }
    if system_id == "OIDC_IDENTITY":
        return {
            "audience": settings.oidc_audience,
            "hardware_webauthn_enabled": settings.oidc_hardware_webauthn_enabled,
            "issuer": settings.oidc_issuer,
            "jwks_url": settings.oidc_jwks_url,
        }
    return _deployment_configuration_document(settings, system_id)


def _runtime_binding_document(
    binding: InferenceRuntimeBinding | None,
) -> dict[str, str | None] | None:
    if binding is None:
        return None
    return {
        "stage": binding.stage.value,
        "provider_profile_version_id": (
            str(binding.provider_profile_version_id)
            if binding.provider_profile_version_id is not None
            else None
        ),
        "server_route_key": binding.server_route_key,
        "provider_identity": binding.provider_identity,
        "model_identity": binding.model_identity,
        "deployment_identity": binding.deployment_identity,
    }


def _deployment_configuration_document(
    settings: Settings,
    system_id: str,
) -> dict[str, Any] | None:
    """Build a non-secret probe document exclusively from server-owned runtime settings."""

    if system_id == "DATAHUB_GMS":
        return {
            "base_url": settings.datahub_base_url,
            "secret_references": {"token": settings.datahub_secret_ref},
            "options": {
                "allowed_versions": list(settings.datahub_allowed_versions),
                "catalog_pit_evidence_reference": (
                    settings.datahub_catalog_pit_evidence_reference or ""
                ),
                "catalog_pit_verified": settings.datahub_catalog_pit_verified,
                "circuit_failure_threshold": settings.datahub_circuit_failure_threshold,
                "circuit_open_seconds": settings.datahub_circuit_open_seconds,
                "expected_version": settings.datahub_expected_version,
                "maximum_concurrency": settings.datahub_max_concurrency,
                "queue_timeout_seconds": settings.datahub_queue_timeout_seconds,
                "stale_ttl_seconds": settings.datahub_stale_ttl_seconds,
                "timeout_seconds": settings.datahub_timeout_seconds,
                "version_enforcement": settings.datahub_version_enforcement,
                "version_probe_ttl_seconds": settings.datahub_version_probe_ttl_seconds,
            },
        }
    if system_id == "DATAHUB_FRONTEND" and settings.ui_datahub_url is not None:
        return {
            "url": str(settings.ui_datahub_url),
            "options": {"embed_enabled": settings.datahub_embed_enabled},
        }
    if system_id == "AIRFLOW" and settings.ui_airflow_url is not None:
        return {
            "base_url": str(settings.ui_airflow_url),
            "secret_references": {},
            "options": {},
        }
    if system_id == "REDIS_CACHE":
        return {
            "url": settings.redis_cache_url,
            "secret_references": {"password": settings.redis_cache_secret_ref},
            "options": {"required_policy": "allkeys-lfu", "role": "CACHE"},
        }
    if system_id == "REDIS_DELIVERY":
        return {
            "url": settings.redis_delivery_url,
            "secret_references": {"password": settings.redis_delivery_secret_ref},
            "options": {"required_policy": "noeviction+aof", "role": "DELIVERY"},
        }
    if system_id == "S3_STORAGE":
        return {
            "endpoint": settings.s3_endpoint_url,
            "public_endpoint": settings.s3_public_endpoint_url,
            "region": settings.s3_region,
            "buckets": {
                "accepted": settings.s3_bucket_accepted,
                "exports": settings.s3_bucket_exports,
                "filefolder": settings.s3_bucket_filefolder or "",
                "infoschema": settings.s3_bucket_infoschema or "",
                "quarantine": settings.s3_bucket_quarantine,
            },
            "options": {"presigned_url_ttl_seconds": settings.presigned_url_ttl_seconds},
            "secret_references": {
                "access_key": _file_secret_reference(settings.s3_access_key_file),
                "secret_key": _file_secret_reference(settings.s3_secret_key_file),
            },
        }
    if system_id == "LLM_CHAT_MODEL":
        binding = resolve_composition_runtime_binding(settings)
        if settings.local_ollama_chat_enabled:
            return {
                "connection_mode": "LOCAL_OLLAMA",
                "base_url": str(settings.local_ollama_chat_base_url),
                "model": settings.local_ollama_chat_model,
                "secret_references": {},
                "options": {
                    "api_style": "ollama_native_chat",
                    "context_tokens": settings.local_ollama_chat_context_tokens,
                    "request_limit_per_minute": (settings.chat_rate_limit_requests_per_minute),
                    "token_limit_per_minute": settings.chat_rate_limit_tokens_per_minute,
                    "timeout_seconds": settings.local_ollama_chat_timeout_seconds,
                    "governance_binding": _runtime_binding_document(binding),
                },
            }
        if settings.intranet_openai_compatible_chat_enabled:
            return {
                "connection_mode": "INTRANET_OPENAI_COMPATIBLE",
                "base_url": str(settings.intranet_openai_compatible_chat_base_url),
                "model": settings.intranet_openai_compatible_chat_model,
                "secret_references": {
                    "api_key": settings.intranet_openai_compatible_chat_api_key_secret_ref
                },
                "options": {
                    "api_style": "openai_compatible",
                    "context_tokens": settings.intranet_openai_compatible_chat_context_tokens,
                    "request_limit_per_minute": (settings.chat_rate_limit_requests_per_minute),
                    "token_limit_per_minute": settings.chat_rate_limit_tokens_per_minute,
                    "timeout_seconds": settings.intranet_openai_compatible_chat_timeout_seconds,
                    "governance_binding": _runtime_binding_document(binding),
                },
            }
        return None
    if system_id == "LLM_EMBEDDING":
        binding = resolve_embedding_runtime_binding(settings)
        if settings.local_ollama_embedding_enabled:
            return {
                "connection_mode": "LOCAL_OLLAMA",
                "base_url": str(settings.local_ollama_embedding_base_url),
                "model": settings.local_ollama_embedding_model,
                "secret_references": {},
                "options": {
                    "api_style": "openai_compatible",
                    "timeout_seconds": settings.local_ollama_embedding_timeout_seconds,
                    "governance_binding": _runtime_binding_document(binding),
                },
            }
        if settings.intranet_openai_compatible_embedding_enabled:
            return {
                "connection_mode": "INTRANET_OPENAI_COMPATIBLE",
                "base_url": str(settings.intranet_openai_compatible_embedding_base_url),
                "model": settings.intranet_openai_compatible_embedding_model,
                "secret_references": {
                    "api_key": settings.intranet_openai_compatible_embedding_api_key_secret_ref
                },
                "options": {
                    "api_style": "openai_compatible",
                    "timeout_seconds": (
                        settings.intranet_openai_compatible_embedding_timeout_seconds
                    ),
                    "governance_binding": _runtime_binding_document(binding),
                },
            }
        return None
    if system_id == "LLM_RERANKER" and settings.local_llama_cpp_reranker_enabled:
        binding = resolve_reranker_runtime_binding(settings)
        return {
            "connection_mode": "LOCAL_LLAMA_CPP",
            "base_url": str(settings.local_llama_cpp_reranker_base_url),
            "model": settings.local_llama_cpp_reranker_model,
            "secret_references": {},
            "options": {
                "api_style": "rerank_v1",
                "timeout_seconds": settings.local_llama_cpp_reranker_timeout_seconds,
                "top_n": settings.local_llama_cpp_reranker_top_n,
                "governance_binding": _runtime_binding_document(binding),
            },
        }
    if system_id == "NEO4J" and settings.neo4j_projection_enabled:
        return {
            "database": settings.neo4j_database,
            "uri": settings.neo4j_uri,
            "secret_references": {"credential": settings.neo4j_auth_secret_ref},
            "options": {
                "connection_timeout_seconds": settings.neo4j_connection_timeout_seconds,
                "maximum_connection_pool_size": settings.neo4j_maximum_connection_pool_size,
            },
        }
    if system_id == "PROMETHEUS" and settings.ui_prometheus_url is not None:
        return {"base_url": str(settings.ui_prometheus_url), "options": {}}
    if system_id == "GRAFANA_DASHBOARD" and settings.ui_grafana_url is not None:
        return {
            "url": str(settings.ui_grafana_url),
            "options": {"dashboard_path": "", "embed_enabled": False},
        }
    return None


def _deployment_probe_document(
    settings: Settings,
    system_id: str,
) -> dict[str, Any] | None:
    """Project the live display document onto the fixed connection-probe schema."""

    document = _deployment_configuration_document(settings, system_id)
    if document is None:
        return None
    template = _SYSTEM_CONFIGURATION_TEMPLATES[system_id]
    probe_document = {key: value for key, value in document.items() if key in template}
    options = document.get("options")
    option_template = template.get("options")
    if isinstance(options, Mapping) and isinstance(option_template, Mapping):
        probe_document["options"] = {key: options[key] for key in option_template if key in options}
    return probe_document


def _deployment_probe_allowed_hosts(
    settings: Settings,
    system_id: str,
) -> tuple[str, ...]:
    hosts = set(settings.system_configuration_probe_allowed_hosts)
    if system_id.startswith("LLM_"):
        hosts.update(settings.effective_local_inference_allowed_hosts)
    return tuple(sorted(hosts))


@router.post(
    "/system-configuration/{system_id}/test-deployment",
    response_model=SystemConfigurationTestResponse,
)
async def test_deployment_system_configuration(
    system_id: str,
    request: Request,
    response: Response,
    context: ContextDep,
) -> SystemConfigurationTestResponse:
    """Probe one configured deployment-managed system using only live server settings."""
    import time as _time

    response.headers["Cache-Control"] = "no-store, private"
    container = get_container(request)
    if container.settings.app_env != "development":
        raise ForbiddenError("System configuration testing is available only in development.")
    if system_id not in {item[0] for item in _SYSTEM_CONFIGURATION}:
        raise ValidationError("The system configuration identifier is invalid.")
    admin_context = await _service(request).get_admin_read_context(
        workspace_id=context.workspace_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if "SYSTEM_CONFIGURATION_READ" not in admin_context.allowed_operations:
        raise ForbiddenError(
            "System configuration testing is not available for this administrator."
        )

    started = _time.monotonic()
    tested_at = utc_now()

    if system_id == "POSTGRESQL":
        try:
            async with container.database.session_factory() as session:
                await session.execute(text("SELECT 1"))
            elapsed_ms = int((_time.monotonic() - started) * 1000)
            return SystemConfigurationTestResponse(
                system_id=system_id,
                status="AVAILABLE",
                scope="AUTHENTICATED_QUERY",
                latency_ms=elapsed_ms,
                detail="PostgreSQL 데이터베이스에 성공적으로 연결되었습니다.",
                configuration_version=None,
                tested_at=tested_at,
            )
        except Exception:
            elapsed_ms = int((_time.monotonic() - started) * 1000)
            return SystemConfigurationTestResponse(
                system_id=system_id,
                status="UNAVAILABLE",
                scope="AUTHENTICATED_QUERY",
                latency_ms=elapsed_ms,
                detail="PostgreSQL 연결 또는 고정 SELECT 1 검증에 실패했습니다.",
                configuration_version=None,
                tested_at=tested_at,
            )

    if system_id == "OIDC_IDENTITY":
        try:
            result = await probe_oidc_jwks(
                jwks_url=container.settings.oidc_jwks_url,
                allowed_hosts=container.settings.system_configuration_probe_allowed_hosts,
            )
            status = result.status
            detail = result.detail
            latency_ms = result.latency_ms
        except Exception:
            status = "UNAVAILABLE"
            detail = "OIDC JWKS 신뢰 경로 또는 키 문서를 검증하지 못했습니다."
            latency_ms = int((_time.monotonic() - started) * 1000)
        return SystemConfigurationTestResponse(
            system_id=system_id,
            status=status,
            scope="HTTP_HEALTH",
            latency_ms=latency_ms,
            detail=detail,
            configuration_version=None,
            tested_at=tested_at,
        )

    document = _deployment_probe_document(container.settings, system_id)
    if document is None:
        return SystemConfigurationTestResponse(
            system_id=system_id,
            status="UNAVAILABLE",
            scope="HTTP_HEALTH",
            latency_ms=int((_time.monotonic() - started) * 1000),
            detail="이 배포에서 해당 시스템의 런타임 설정이 구성되지 않았습니다.",
            configuration_version=None,
            tested_at=tested_at,
        )
    try:
        _validate_system_configuration(system_id, document)
        result = await probe_system_configuration(
            system_id=system_id,
            document=document,
            secret_resolver=SecretResolver(
                virtual_secret_root=container.settings.system_configuration_secret_root
            ),
            allowed_hosts=_deployment_probe_allowed_hosts(container.settings, system_id),
        )
        status = result.status
        scope = result.scope
        latency_ms = result.latency_ms
        detail = result.detail
    except Exception:
        status = "UNAVAILABLE"
        scope = "HTTP_HEALTH"
        latency_ms = int((_time.monotonic() - started) * 1000)
        detail = "배포 설정의 고정 연결 검증에 실패했습니다. 서버 로그와 운영 설정을 확인하세요."
    return SystemConfigurationTestResponse(
        system_id=system_id,
        status=status,
        scope=scope,
        latency_ms=latency_ms,
        detail=detail,
        configuration_version=None,
        tested_at=tested_at,
    )


async def activate_system_configuration(
    system_id: str,
    request: Request,
    response: Response,
    context: ContextDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
) -> SystemConfigurationEntryResponse:
    """Select one TEST-passed revision for the next API/worker process startup."""

    raise ForbiddenError(
        "Database-backed system configuration activation is retired and deployment-managed."
    )
    container = get_container(request)
    _require_system_configuration_runtime_activation(container.settings)
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
            activation_document = _yaml_document(revision.configuration_yaml)
            _validate_system_configuration(system_id, activation_document)
            try:
                validate_runtime_system_configuration(
                    container.settings,
                    service_key=service_key,
                    document=activation_document,
                )
            except ValueError as error:
                raise ValidationError(
                    "The tested system configuration cannot satisfy the process startup contract."
                ) from error
            if canonical_json_hash(activation_document) != revision.configuration_hash:
                raise ConflictError("The activation revision failed its integrity check.")
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
            entry = _system_configuration_entries(container.settings)
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
    cursor: Annotated[str | None, Query(max_length=2000)] = None,
) -> MembershipRenewalListResponse:
    page = await _service(request).list_membership_renewals(
        workspace_id=context.workspace_id,
        subject_id=context.subject.subject_id,
        state=None,
        limit=limit,
        cursor=cursor,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        administrator=False,
    )
    return MembershipRenewalListResponse(
        items=[_membership_renewal_response(value) for value in page.items],
        page=PageMeta(next_cursor=page.next_cursor, limit=limit),
    )


@router.get("/membership-renewals", response_model=MembershipRenewalListResponse)
async def list_membership_renewals_for_admin(
    request: Request,
    context: ContextDep,
    state: Annotated[str | None, Query(max_length=20)] = "PENDING",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=2000)] = None,
) -> MembershipRenewalListResponse:
    try:
        parsed_state = MembershipRenewalState(state) if state is not None else None
    except ValueError as error:
        raise ValidationError("The membership renewal state filter is invalid.") from error
    page = await _service(request).list_membership_renewals(
        workspace_id=context.workspace_id,
        subject_id=None,
        state=parsed_state,
        limit=limit,
        cursor=cursor,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        administrator=True,
    )
    return MembershipRenewalListResponse(
        items=[_membership_renewal_response(value) for value in page.items],
        page=PageMeta(next_cursor=page.next_cursor, limit=limit),
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
    assigned_role_version: int | None = None
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
        assigned_role_version = role.version
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
        role_id=payload.role_id,
        role_version=assigned_role_version,
        role_transition=True,
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
    cursor: Annotated[str | None, Query(max_length=2000)] = None,
) -> AdminAccessRequestListResponse:
    try:
        parsed_state = AdminAccessRequestState(state) if state is not None else None
    except ValueError as error:
        raise ValidationError("The administrator fallback state filter is invalid.") from error
    page = await _service(request).list_fallback_requests(
        workspace_id=context.workspace_id,
        state=parsed_state,
        limit=limit,
        cursor=cursor,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return AdminAccessRequestListResponse(
        items=[admin_access_request_response(value) for value in page.items],
        page=PageMeta(next_cursor=page.next_cursor, limit=limit),
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
