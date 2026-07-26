from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.responses import Response

from datariver.config import Settings
from datariver.domain.authz import Action
from datariver.domain.common import ForbiddenError, RateLimitError, ValidationError
from datariver.infrastructure.db.session import DatabaseReadiness
from datariver.infrastructure.observability.metrics import HttpMetrics
from datariver.interfaces.http.container import AppContainer
from datariver.interfaces.http.dependencies import get_request_context
from datariver.interfaces.http.factory import create_app
from datariver.interfaces.http.routes import admin as admin_routes
from datariver.interfaces.http.routes.admin import (
    _SYSTEM_ENVIRONMENT_KEYS,
    _deployment_configuration_document,
    _display_configuration,
    _system_configuration_entries,
    _validate_configuration_submission,
    _validate_system_configuration,
    _yaml_document,
)
from datariver.interfaces.http.routes.registration import _expected_version

ROOT = Path(__file__).resolve().parents[3]


class LiveOnlyContainer:
    def __init__(self) -> None:
        self.metrics = HttpMetrics()

    async def close(self) -> None:
        return None


class NotReadyDatabase:
    async def readiness(self, **_: object) -> DatabaseReadiness:
        return DatabaseReadiness(ready=False, code="SCHEMA_REVISION_MISMATCH")


class NotReadyContainer(LiveOnlyContainer):
    def __init__(self, configured: Settings) -> None:
        super().__init__()
        self.settings = configured
        self.database = NotReadyDatabase()


def settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        database_url="postgresql+asyncpg://u@localhost/db",
        database_secret_ref="file:/run/secrets/postgres_password",
        migration_database_url="postgresql+asyncpg://owner@localhost/db",
        migration_database_secret_ref="file:/run/secrets/postgres_owner_password",
        relay_database_url="postgresql+asyncpg://relay@localhost/db",
        relay_database_secret_ref="file:/run/secrets/postgres_relay_password",
        upload_database_url="postgresql+asyncpg://upload@localhost/db",
        upload_database_secret_ref="file:/run/secrets/postgres_upload_password",
        governance_database_url="postgresql+asyncpg://governance@localhost/db",
        governance_database_secret_ref="file:/run/secrets/postgres_governance_password",
        bootstrap_database_url="postgresql+asyncpg://bootstrap@localhost/db",
        bootstrap_database_secret_ref="file:/run/secrets/postgres_bootstrap_password",
        oidc_issuer="http://idp/realms/test",
        oidc_audience="api",
        oidc_jwks_url="http://idp/jwks",
        datahub_base_url="http://datahub",
        datahub_secret_ref="file:/tmp/token",
        datahub_expected_version="v1.6.0",
        local_ollama_chat_enabled=False,
        local_ollama_embedding_enabled=False,
        neo4j_projection_enabled=False,
        knowledge_pipeline_enabled=False,
        system_configuration_runtime_activation_enabled=False,
        valkey_cache_url="redis://cache:6379/0",
        valkey_queue_url="redis://queue:6379/0",
        valkey_cache_secret_ref="file:/run/secrets/valkey_cache_password",
        valkey_queue_secret_ref="file:/run/secrets/valkey_queue_password",
        s3_endpoint_url="http://s3",
        s3_public_endpoint_url="http://localhost:8333",
        s3_bucket_quarantine="q",
        s3_bucket_accepted="a",
        s3_access_key_file="/run/secrets/test_s3_access_key",
        s3_secret_key_file="/run/secrets/test_s3_secret_key",
    )


def test_liveness_and_security_headers() -> None:
    factory = cast(Callable[[Settings], AppContainer], lambda _: LiveOnlyContainer())
    app = create_app(settings(), container_factory=factory)

    with TestClient(app) as client:
        response = client.get("/api/v1/health/live", headers={"X-Request-Id": "valid-request-id"})

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}
    assert response.headers["X-Request-Id"] == "valid-request-id"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_liveness_survives_while_schema_readiness_returns_bounded_503() -> None:
    configured = settings()
    container = NotReadyContainer(configured)
    factory = cast(Callable[[Settings], AppContainer], lambda _: container)
    app = create_app(configured, container_factory=factory)

    with TestClient(app) as client:
        live_response = client.get("/api/v1/health/live")
        ready_response = client.get("/api/v1/health/ready")

    assert live_response.status_code == 200
    assert ready_response.status_code == 503
    assert ready_response.json() == {
        "status": "not_ready",
        "code": "SCHEMA_REVISION_MISMATCH",
    }


def test_invalid_request_id_is_replaced() -> None:
    factory = cast(Callable[[Settings], AppContainer], lambda _: LiveOnlyContainer())
    app = create_app(settings(), container_factory=factory)

    with TestClient(app) as client:
        response = client.get("/api/v1/health/live", headers={"X-Request-Id": "invalid value"})

    assert response.status_code == 200
    assert response.headers["X-Request-Id"] != "invalid value"


def test_rate_limit_problem_is_stable_retryable_and_never_cacheable() -> None:
    factory = cast(Callable[[Settings], AppContainer], lambda _: LiveOnlyContainer())
    app = create_app(settings(), container_factory=factory)

    @app.get("/test/rate-limit")
    async def rate_limited() -> None:
        raise RateLimitError(
            "The API consumer per-minute quota has been exhausted.",
            details={"retry_after_seconds": 60},
        )

    with TestClient(app) as client:
        response = client.get(
            "/test/rate-limit",
            headers={"X-Request-Id": "phase6c-rate-limit"},
        )

    assert response.status_code == 429
    assert response.headers["Content-Type"].startswith("application/problem+json")
    assert response.headers["Retry-After"] == "60"
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["X-Request-Id"] == "phase6c-rate-limit"
    assert response.json() == {
        "type": "urn:datariver:problem:rate_limit_exceeded",
        "title": "Rate Limit Exceeded",
        "status": 429,
        "detail": "The API consumer per-minute quota has been exhausted.",
        "instance": "/test/rate-limit",
        "code": "rate_limit_exceeded",
        "request_id": "phase6c-rate-limit",
    }


def test_http_metrics_use_bounded_route_templates() -> None:
    container = LiveOnlyContainer()
    factory = cast(Callable[[Settings], AppContainer], lambda _: container)
    app = create_app(settings(), container_factory=factory)

    with TestClient(app) as client:
        response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    rendered = container.metrics.render().decode()
    assert 'route="/api/v1/health/live"' in rendered
    assert "testclient" not in rendered


def test_internal_compose_and_healthcheck_hosts_are_trusted() -> None:
    factory = cast(Callable[[Settings], AppContainer], lambda _: LiveOnlyContainer())
    app = create_app(settings(), container_factory=factory)

    with TestClient(app) as client:
        service_response = client.get("/api/v1/health/live", headers={"Host": "api:8000"})
        healthcheck_response = client.get("/api/v1/health/live", headers={"Host": "127.0.0.1:8000"})

    assert service_response.status_code == 200
    assert healthcheck_response.status_code == 200


def test_openapi_contains_all_required_product_modules() -> None:
    factory = cast(Callable[[Settings], AppContainer], lambda _: LiveOnlyContainer())
    document = create_app(settings(), container_factory=factory).openapi()

    assert {
        "/api/v1/auth/me",
        "/api/v1/catalog/assets",
        "/api/v1/catalog/facets",
        "/api/v1/catalog/suggestions",
        "/api/v1/catalog/exports",
        "/api/v1/catalog/exports/{export_id}",
        "/api/v1/catalog/exports/{export_id}/download",
        "/api/v1/catalog/export-capability",
        "/api/v1/catalog/assets/{asset_id}/description-previews",
        "/api/v1/catalog/assets/{asset_id}/description-change-requests",
        "/api/v1/catalog/assets/{asset_id}/controlled-metadata-previews",
        "/api/v1/catalog/assets/{asset_id}/controlled-metadata-change-requests",
        "/api/v1/uploads",
        "/api/v1/uploads/operator-capability",
        "/api/v1/uploads/metadata-vocabulary",
        "/api/v1/uploads/metadata-vocabulary/sync",
        "/api/v1/uploads/profiles/{content_profile}/template",
        "/api/v1/uploads/{upload_id}/preparations",
        "/api/v1/uploads/{upload_id}/preparations/{preparation_id}",
        "/api/v1/uploads/{upload_id}/preparations/{preparation_id}/candidates",
        "/api/v1/uploads/{upload_id}/preparations/{preparation_id}/candidates/{candidate_id}/preview",
        "/api/v1/uploads/{upload_id}/preparations/{preparation_id}/candidates/{candidate_id}/change-request",
        "/api/v1/uploads/{upload_id}/preparations/{preparation_id}/metadata-candidates",
        "/api/v1/uploads/{upload_id}/preparations/{preparation_id}/metadata-candidates/{candidate_id}/preview",
        "/api/v1/uploads/{upload_id}/preparations/{preparation_id}/metadata-candidates/{candidate_id}/change-request",
        "/api/v1/uploads/{upload_id}/registration-proposals",
        "/api/v1/change-requests",
        "/api/v1/change-requests/{change_request_id}/apply-report",
        "/api/v1/operations/summary",
        "/api/v1/operations/metrics",
        "/api/v1/knowledge/graphs",
        "/api/v1/chat/query",
        "/api/v1/catalog/sync/datahub",
        "/api/v1/catalog/sync/datahub/{sync_id}",
        "/api/v1/change-requests/{change_request_id}/approvals",
        "/api/v1/knowledge/graphs/{graph_id}/releases/{release_id}/export",
        "/api/v1/knowledge/graphs/{graph_id}/releases/{release_id}/analysis/neighbors",
        "/api/v1/knowledge/graphs/{graph_id}/changesets",
        "/api/v1/knowledge/graphs/{graph_id}/changesets/{changeset_id}/operations",
        "/api/v1/knowledge/graphs/{graph_id}/changesets/{changeset_id}/submit",
        "/api/v1/knowledge/graphs/{graph_id}/changesets/{changeset_id}/reviews",
        "/api/v1/knowledge/graphs/{graph_id}/changesets/{changeset_id}/publish",
        "/api/v1/knowledge/graphs/{graph_id}/releases",
        "/api/v1/knowledge/graphs/{graph_id}/releases/{release_id}/activate",
        "/api/v1/api-products",
        "/api/v1/api-products/{product_id}/versions",
        "/api/v1/api-products/{product_id}/versions/{version_id}/publish",
        "/api/v1/api-products/{product_id}/grants",
        "/api/v1/api-products/{product_id}/grants/{grant_id}/revoke",
        "/api/v1/api-products/{product_id}/authorize-invocation",
        "/api/v1/api-products/{product_id}/invoke/neighbors",
        "/api/v1/api-products/{product_id}/invoke/snapshot",
        "/api/v1/api-products/{product_id}/invoke/chat",
        "/api/v1/admin/workspace-memberships/{target_subject_id}/access",
        "/api/v1/admin/workspace-memberships/{target_subject_id}/change-requests",
        "/api/v1/admin/workspace-memberships/{target_subject_id}/owned-tables",
        "/api/v1/admin/workspace-memberships/{target_subject_id}/role",
        "/api/v1/admin/workspace-memberships",
        "/api/v1/admin/access-roles",
        "/api/v1/admin/access-roles/{role_id}",
        "/api/v1/admin/systems",
        "/api/v1/admin/systems/{system_id}/assignees",
        "/api/v1/admin/system-configuration",
        "/api/v1/admin/system-configuration/{system_id}/test-deployment",
        "/api/v1/admin/me",
        "/api/v1/admin/fallback/workspace-membership-access-requests",
        "/api/v1/admin/fallback/workspace-membership-access-requests/{access_request_id}/decisions",
        "/api/v1/admin/fallback/workspace-membership-access-requests/{access_request_id}/consume",
        "/api/v1/admin/classification-access/policies",
        "/api/v1/admin/classification-access/policies/current",
        "/api/v1/admin/classification-access/policies/{policy_id}/decisions",
        "/api/v1/admin/classification-access/restricted-search-grants",
        "/api/v1/admin/classification-access/restricted-search-grants/{grant_id}/decisions",
        "/api/v1/admin/classification-access/restricted-search-grants/{grant_id}/revocations",
        "/api/v1/admin/inference/provider-profiles",
        "/api/v1/admin/inference/provider-profiles/{profile_version_id}/decisions",
        "/api/v1/admin/inference/provider-profiles/{profile_version_id}/revocations",
    }.issubset(document["paths"])


def test_direct_knowledge_release_publication_is_explicitly_retired() -> None:
    factory = cast(Callable[[Settings], AppContainer], lambda _: LiveOnlyContainer())
    app = create_app(settings(), container_factory=factory)
    document = app.openapi()

    operation = document["paths"]["/api/v1/knowledge/graphs/{graph_id}/releases"]["post"]

    assert operation["deprecated"] is True
    assert "410" in operation["responses"]
    assert "requestBody" not in operation
    app.dependency_overrides[get_request_context] = lambda: object()
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/knowledge/graphs/{UUID(int=1)}/releases",
            json={"snapshot": "must-not-be-accepted"},
        )
    assert response.status_code == 410
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Content-Type"].startswith("application/problem+json")
    assert response.json()["type"].endswith("/direct-release-retired")


def test_system_configuration_inventory_is_server_owned_and_redacted() -> None:
    configured = Settings(
        **(
            settings().model_dump()
            | {
                "ui_grafana_url": "https://grafana.example.internal/d/overview",
                "grafana_embed_base_url": "https://grafana.example.internal",
                "grafana_embed_enabled": True,
                "grafana_embed_evidence_reference": "SEC-REVIEW-1234",
            }
        )
    )

    entries = _system_configuration_entries(configured)
    by_id = {entry.system_id: entry for entry in entries}

    assert list(by_id) == [
        "PLATFORM_RUNTIME",
        "POSTGRESQL",
        "OIDC_IDENTITY",
        "RETENTION_ARCHIVE",
        "DATAHUB_GMS",
        "DATAHUB_FRONTEND",
        "AIRFLOW",
        "REDIS_CACHE",
        "REDIS_DELIVERY",
        "S3_STORAGE",
        "LLM_CHAT_MODEL",
        "LLM_EMBEDDING",
        "LLM_RERANKER",
        "NEO4J",
        "PROMETHEUS",
        "GRAFANA_DASHBOARD",
    ]
    assert by_id["DATAHUB_GMS"].secret_reference_configured is True
    assert by_id["POSTGRESQL"].requirement == "BOOTSTRAP_REQUIRED"
    assert by_id["REDIS_CACHE"].requirement == "CORE_CONNECTOR"
    assert by_id["REDIS_DELIVERY"].restart_scope == "WORKERS_ONLY"
    assert by_id["LLM_RERANKER"].runtime_supported is True
    assert by_id["LLM_RERANKER"].restart_scope == "API_ONLY"
    assert any(field.secret for field in by_id["S3_STORAGE"].connection_requirements)
    assert by_id["LLM_CHAT_MODEL"].state == "NOT_CONFIGURED"
    assert by_id["GRAFANA_DASHBOARD"].embedding_state == "AVAILABLE"
    assert all(entry.activation_state == "DEPLOYMENT_MANAGED" for entry in entries)
    assert all(entry.template_yaml == "" for entry in entries)
    assert all(entry.environment_template for entry in entries)
    assert by_id["DATAHUB_GMS"].effective_configuration_yaml
    assert "DATAHUB_BASE_URL=" in by_id["DATAHUB_GMS"].environment_template
    assert "token:" in by_id["DATAHUB_GMS"].effective_configuration_yaml
    assert "********" not in by_id["DATAHUB_GMS"].effective_configuration_yaml
    assert all("url" not in entry.model_dump() for entry in entries)
    assert all("secret_reference" not in entry.model_dump() for entry in entries)

    development = Settings(**(configured.model_dump() | {"app_env": "development"}))
    development_entries = _system_configuration_entries(development)
    assert [entry.model_dump() for entry in development_entries] == [
        entry.model_dump() for entry in entries
    ]
    assert all(entry.activation_state == "DEPLOYMENT_MANAGED" for entry in development_entries)


def test_system_environment_templates_use_only_documented_env_example_keys() -> None:
    documented: set[str] = set()
    for raw_line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = raw_line.removeprefix("# ").strip()
        if "=" in line:
            documented.add(line.split("=", 1)[0])

    missing = {
        key for keys in _SYSTEM_ENVIRONMENT_KEYS.values() for key in keys if key not in documented
    }

    assert missing == set()
    retired = {
        "SYSTEM_CONFIGURATION_RUNTIME_ACTIVATION_ENABLED",
        "SYSTEM_CONFIGURATION_RUNTIME_WORKSPACE_ID",
        "SYSTEM_CONFIGURATION_RUNTIME_VERSIONS",
        "SYSTEM_CONFIGURATION_RUNTIME_HASHES",
    }
    live_settings = {name.upper() for name in Settings.model_fields} - retired
    assert live_settings - documented == set()
    connector_prefixes = (
        "DATABASE_",
        "MIGRATION_DATABASE_",
        "RELAY_DATABASE_",
        "UPLOAD_DATABASE_",
        "GOVERNANCE_DATABASE_",
        "KNOWLEDGE_DATABASE_",
        "EXPORT_DATABASE_",
        "RETENTION_SCHEDULER_DATABASE_",
        "ARCHIVE_DATABASE_",
        "BOOTSTRAP_DATABASE_",
        "WORKER_DATABASE_",
        "OIDC_",
        "IDENTITY_",
        "ADMIN_PASSWORD_",
        "DATAHUB_",
        "DATARIVER_CATALOG_",
        "REDIS_",
        "CACHE_",
        "CATALOG_SEARCH_",
        "CATALOG_EXPORT_",
        "OUTBOX_",
        "UPLOAD_",
        "GOVERNANCE_",
        "S3_",
        "LOCAL_OLLAMA_",
        "LOCAL_LLAMA_CPP_",
        "INTRANET_OPENAI_",
        "NEO4J_",
        "KNOWLEDGE_",
        "GRAFANA_",
        "SYSTEM_CONFIGURATION_PROBE_",
        "SYSTEM_CONFIGURATION_SECRET_",
    )
    connector_exact = {
        "AIRFLOW_WORKSPACE_ID",
        "CATALOG_EXPORT_WORKER_ENABLED",
        "CHAT_EPHEMERAL_ADMIN_WITHOUT_RETENTION_ENABLED",
        "EXPORT_WORKER_SUBJECT_ID",
        "HIGH_RISK_AUTH_MAX_AGE_SECONDS",
        "LOCAL_INFERENCE_SOURCE_HOST_ENABLED",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "PRESIGNED_URL_TTL_SECONDS",
        "RETENTION_WORKER_SUBJECT_ID",
        "UI_AIRFLOW_URL",
        "UI_DATAHUB_URL",
        "UI_GRAFANA_URL",
        "UI_GRAPH_URL",
        "UI_PROMETHEUS_URL",
        "WORKER_POLL_SECONDS",
        "WORKSPACE_SELECTION_ENABLED",
    }
    expected = {
        key for key in documented if key.startswith(connector_prefixes) or key in connector_exact
    }
    rendered = {key for keys in _SYSTEM_ENVIRONMENT_KEYS.values() for key in keys}

    assert live_settings - rendered == set()
    assert expected - rendered == set()
    reference = (ROOT / "docs" / "41_DEPLOYMENT_ENVIRONMENT_CONFIGURATION.md").read_text(
        encoding="utf-8"
    )
    assert {key for key in live_settings if key not in reference} == set()
    assert {key for key in rendered if key not in reference} == set()


def test_deployment_probe_documents_use_only_server_owned_runtime_settings() -> None:
    chat_profile_id = uuid4()
    reranker_profile_id = uuid4()
    configured = Settings(
        **(
            settings().model_dump()
            | {
                "app_env": "development",
                "local_ollama_chat_enabled": True,
                "local_ollama_chat_base_url": "http://host.docker.internal:11434/v1",
                "local_ollama_chat_model": "operator-selected-chat-model",
                "chat_composition_provider_profile_version_id": chat_profile_id,
                "local_llama_cpp_reranker_enabled": True,
                "local_llama_cpp_reranker_base_url": ("http://host.docker.internal:11435/v1"),
                "local_llama_cpp_reranker_model": ("qllama/bge-reranker-v2-m3:q4_k_m"),
                "chat_reranker_provider_profile_version_id": reranker_profile_id,
            }
        )
    )

    datahub = _deployment_configuration_document(configured, "DATAHUB_GMS")
    delivery = _deployment_configuration_document(configured, "REDIS_DELIVERY")
    chat = _deployment_configuration_document(configured, "LLM_CHAT_MODEL")
    reranker = _deployment_configuration_document(configured, "LLM_RERANKER")

    assert datahub is not None
    assert datahub["base_url"] == configured.datahub_base_url
    assert datahub["secret_references"] == {"token": configured.datahub_secret_ref}
    assert delivery is not None
    assert delivery["url"] == configured.redis_delivery_url
    assert delivery["secret_references"] == {"password": configured.redis_delivery_secret_ref}
    assert chat is not None
    assert chat["base_url"] == "http://host.docker.internal:11434/v1"
    assert chat["model"] == "operator-selected-chat-model"
    assert chat["options"]["api_style"] == "ollama_native_chat"
    assert chat["options"]["governance_binding"] == {
        "stage": "composition",
        "provider_profile_version_id": str(chat_profile_id),
        "server_route_key": "local-ollama-native-chat-v1",
        "provider_identity": "ollama-native-chat",
        "model_identity": "operator-selected-chat-model",
        "deployment_identity": chat["options"]["governance_binding"]["deployment_identity"],
    }
    assert str(chat["options"]["governance_binding"]["deployment_identity"]).startswith("sha256:")
    assert chat["secret_references"] == {}
    assert reranker is not None
    assert reranker["connection_mode"] == "LOCAL_LLAMA_CPP"
    assert reranker["base_url"] == "http://host.docker.internal:11435/v1"
    assert reranker["model"] == "qllama/bge-reranker-v2-m3:q4_k_m"
    assert reranker["options"]["governance_binding"]["provider_profile_version_id"] == str(
        reranker_profile_id
    )
    assert reranker["secret_references"] == {}


def test_system_configuration_display_removes_nested_secrets_and_submission_rejects_them() -> None:
    stored = {
        "base_url": "http://service.internal",
        "auth": {"username": "developer", "password": "stored-secret"},
        "headers": [{"api_token": "stored-token", "accept": "application/json"}],
        "options": {"context_tokens": 8192, "max_completion_tokens": 4096},
    }

    assert _display_configuration(stored) == {
        "base_url": "http://service.internal",
        "auth": {"username": "developer"},
        "headers": [{"accept": "application/json"}],
        "options": {"context_tokens": 8192, "max_completion_tokens": 4096},
    }
    with pytest.raises(ValidationError, match="operator-managed secret"):
        _validate_configuration_submission(
            {"auth": {"password": "new-secret"}},
            stored,
        )
    _validate_configuration_submission(
        {
            "auth": {"password": "********"},
            "headers": [{"api_token": "********"}],
        },
        stored,
    )
    with pytest.raises(ValidationError, match="operator-managed secret"):
        _validate_configuration_submission({"api_key": "********"}, {})
    _validate_configuration_submission(
        {"secret_references": {"token": "file:/run/secrets/datahub_token"}},
        {},
    )
    with pytest.raises(ValidationError, match="Secret references must use"):
        _validate_configuration_submission(
            {"secret_references": {"token": "literal-secret-value"}},
            {},
        )


def test_system_configuration_yaml_rejects_aliases_and_resource_exhaustion() -> None:
    with pytest.raises(ValidationError, match="aliases and anchors are forbidden"):
        _yaml_document("options: &loop\n  recursive: *loop\n")

    nested = "value: terminal"
    for index in range(20):
        nested = f"level_{index}:\n" + "\n".join(f"  {line}" for line in nested.splitlines())
    with pytest.raises(ValidationError, match="nesting depth limit"):
        _yaml_document(nested)

    nodes = "options:\n" + "\n".join(f"  item_{index}: {index}" for index in range(520))
    with pytest.raises(ValidationError, match="node limit"):
        _yaml_document(nodes)


@pytest.mark.parametrize("secret_key", ["credential", "authorization"])
def test_system_configuration_rejects_unknown_nested_secret_fields(secret_key: str) -> None:
    document = {
        "url": "https://grafana.example",
        "options": {
            "dashboard_path": "",
            "embed_enabled": False,
            secret_key: "plaintext-secret",
        },
    }

    with pytest.raises(ValidationError, match="unsupported option keys"):
        _validate_system_configuration("GRAFANA_DASHBOARD", document)


def test_redis_system_configuration_requires_separate_secret_reference() -> None:
    document = {
        "url": "rediss://redis-cache.example.internal:6379/0",
        "secret_references": {"password": "file:/run/secrets/redis_cache_password"},
        "options": {"role": "CACHE", "required_policy": "allkeys-lfu"},
    }

    assert _validate_system_configuration("REDIS_CACHE", document) == document["url"]
    with pytest.raises(ValidationError, match="must not be embedded"):
        _validate_system_configuration(
            "REDIS_CACHE",
            document | {"url": "redis://default:secret@redis-cache:6379/0"},
        )
    with pytest.raises(ValidationError, match="exactly one password"):
        _validate_system_configuration(
            "REDIS_DELIVERY",
            document
            | {
                "secret_references": {},
                "options": {"role": "DELIVERY", "required_policy": "noeviction+aof"},
            },
        )
    with pytest.raises(ValidationError, match="canonical operator-managed secret"):
        _validate_system_configuration(
            "REDIS_CACHE",
            document
            | {
                "secret_references": {
                    "password": "file:/run/secrets/keycloak_identity_admin_client_secret"
                }
            },
        )


def test_datahub_system_configuration_accepts_only_explicit_pit_evidence_contract() -> None:
    options: dict[str, object] = {
        "catalog_pit_verified": True,
        "catalog_pit_evidence_reference": "ops://datahub/pit/2026-07-23",
        "version_enforcement": "enforce",
    }
    document: dict[str, object] = {
        "base_url": "https://datahub.example",
        "secret_references": {"token": "file:/run/secrets/datahub_token"},
        "options": options,
    }

    assert _validate_system_configuration("DATAHUB_GMS", document) == document["base_url"]
    with pytest.raises(ValidationError, match="version_enforcement is invalid"):
        _validate_system_configuration(
            "DATAHUB_GMS",
            {
                **document,
                "options": {
                    **options,
                    "version_enforcement": "strict",
                },
            },
        )


@pytest.mark.parametrize(
    ("system_id", "document"),
    [
        (
            "DATAHUB_GMS",
            {
                "base_url": "https://datahub.example",
                "secret_references": {
                    "token": "file:/run/secrets/keycloak_identity_admin_client_secret"
                },
                "options": {},
            },
        ),
        (
            "S3_STORAGE",
            {
                "endpoint": "https://minio.example",
                "public_endpoint": "https://objects.example",
                "region": "ap-northeast-2",
                "buckets": {
                    "accepted": "accepted",
                    "exports": "exports",
                    "filefolder": "filefolder",
                    "infoschema": "infoschema",
                    "quarantine": "quarantine",
                },
                "secret_references": {
                    "access_key": "file:/run/secrets/datahub_token",
                    "secret_key": "file:/run/secrets/s3_secret_key",
                },
                "options": {},
            },
        ),
        (
            "LLM_CHAT_MODEL",
            {
                "connection_mode": "INTRANET_OPENAI_COMPATIBLE",
                "base_url": "https://10.42.0.15/v1",
                "model": "approved-chat",
                "secret_references": {"api_key": "file:/run/secrets/s3_secret_key"},
                "options": {"api_style": "openai_compatible"},
            },
        ),
        (
            "NEO4J",
            {
                "uri": "neo4j://graph.example:7687",
                "database": "neo4j",
                "secret_references": {"credential": "file:/run/secrets/postgres_app_password"},
                "options": {},
            },
        ),
    ],
)
def test_system_configuration_rejects_cross_connector_secret_binding(
    system_id: str,
    document: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="canonical operator-managed secret"):
        _validate_system_configuration(system_id, document)


def test_system_configuration_contract_rejects_credentials_and_incomplete_profiles() -> None:
    with pytest.raises(ValidationError, match="must not be embedded"):
        _validate_system_configuration(
            "DATAHUB_GMS",
            {"base_url": "http://admin:password@datahub:8080", "options": {}},
        )
    with pytest.raises(ValidationError, match="non-empty model"):
        _validate_system_configuration(
            "LLM_CHAT_MODEL",
            {"base_url": "http://host.docker.internal:11434/v1", "model": "", "options": {}},
        )
    with pytest.raises(ValidationError, match="HTTPS /v1"):
        _validate_system_configuration(
            "LLM_CHAT_MODEL",
            {
                "connection_mode": "INTRANET_OPENAI_COMPATIBLE",
                "base_url": "http://10.42.0.15/v1",
                "model": "gemma4:latest",
                "secret_references": {"api_key": "file:/run/secrets/intranet_llm_chat_api_key"},
                "options": {"api_style": "openai_compatible"},
            },
        )
    with pytest.raises(ValidationError, match="accepted"):
        _validate_system_configuration(
            "S3_STORAGE",
            {
                "endpoint": "http://object-store:9000",
                "public_endpoint": "http://localhost:8333",
                "region": "ap-northeast-2",
                "buckets": {"accepted": "", "exports": "exports", "quarantine": "q"},
                "options": {},
            },
        )


def test_reranker_configuration_is_one_fixed_non_openai_contract() -> None:
    valid: dict[str, Any] = {
        "connection_mode": "INTRANET_RERANK_V1",
        "base_url": "https://10.42.0.16/v1",
        "model": "bge-reranker-v2-m3",
        "secret_references": {"api_key": "file:/run/secrets/intranet_llm_reranker_api_key"},
        "options": {"api_style": "rerank_v1", "timeout_seconds": 60, "top_n": 10},
    }

    assert _validate_system_configuration("LLM_RERANKER", valid) == ("https://10.42.0.16/v1")

    with pytest.raises(ValidationError, match="server-controlled"):
        _validate_system_configuration(
            "LLM_RERANKER",
            {
                **valid,
                "options": {
                    **valid["options"],
                    "api_style": "openai_compatible",
                },
            },
        )
    with pytest.raises(ValidationError, match="connection_mode"):
        _validate_system_configuration(
            "LLM_RERANKER",
            {**valid, "connection_mode": "LOCAL_OLLAMA"},
        )
    with pytest.raises(ValidationError, match="canonical operator-managed secret"):
        _validate_system_configuration(
            "LLM_RERANKER",
            {
                **valid,
                "secret_references": {"api_key": "file:/run/secrets/intranet_llm_chat_api_key"},
            },
        )

    local = {
        **valid,
        "connection_mode": "LOCAL_LLAMA_CPP",
        "base_url": "http://host.docker.internal:11435/v1",
        "model": "qllama/bge-reranker-v2-m3:q4_k_m",
        "secret_references": {},
    }
    assert _validate_system_configuration("LLM_RERANKER", local) == (
        "http://host.docker.internal:11435/v1"
    )
    with pytest.raises(ValidationError, match="port-11435"):
        _validate_system_configuration(
            "LLM_RERANKER",
            {**local, "base_url": "http://host.docker.internal:11434/v1"},
        )


def test_database_backed_system_configuration_mutation_routes_are_not_published() -> None:
    startup_settings = settings()
    container = LiveOnlyContainer()
    container.settings = startup_settings  # type: ignore[attr-defined]
    factory = cast(Callable[[Settings], AppContainer], lambda _: cast(AppContainer, container))
    app = create_app(startup_settings, container_factory=factory)
    app.dependency_overrides[get_request_context] = lambda: object()

    document = app.openapi()
    paths = document["paths"]
    assert "/api/v1/admin/system-configuration/{system_id}" not in paths
    assert "/api/v1/admin/system-configuration/{system_id}/versions" not in paths
    assert "/api/v1/admin/system-configuration/{system_id}/test" not in paths
    assert "/api/v1/admin/system-configuration/{system_id}/test-draft" not in paths
    assert "/api/v1/admin/system-configuration/{system_id}/activate" not in paths
    with TestClient(app) as client:
        for method, path in (
            ("PUT", "/api/v1/admin/system-configuration/DATAHUB_GMS"),
            ("GET", "/api/v1/admin/system-configuration/DATAHUB_GMS/versions"),
            ("POST", "/api/v1/admin/system-configuration/DATAHUB_GMS/test"),
            ("POST", "/api/v1/admin/system-configuration/DATAHUB_GMS/test-draft"),
            ("POST", "/api/v1/admin/system-configuration/DATAHUB_GMS/activate"),
        ):
            assert client.request(method, path).status_code == 404


@pytest.mark.asyncio
async def test_deployment_system_configuration_routes_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = cast(Any, object())
    context = cast(
        Any,
        SimpleNamespace(
            workspace_id=UUID(int=1),
            subject=SimpleNamespace(subject_id=UUID(int=2)),
            environment=object(),
            request_id="request-system-configuration-negative",
        ),
    )
    denied_service = SimpleNamespace(
        get_admin_read_context=AsyncMock(return_value=SimpleNamespace(allowed_operations=()))
    )
    monkeypatch.setattr(admin_routes, "_service", lambda _request: denied_service)
    inventory_response = Response()
    with pytest.raises(ForbiddenError):
        await admin_routes.list_system_configuration(
            request=request,
            response=inventory_response,
            context=context,
        )
    assert inventory_response.headers["Cache-Control"] == "no-store, private"

    non_admin_service = SimpleNamespace(
        get_admin_read_context=AsyncMock(
            side_effect=ForbiddenError("Administrator membership is required.")
        )
    )
    monkeypatch.setattr(admin_routes, "_service", lambda _request: non_admin_service)
    with pytest.raises(ForbiddenError, match="Administrator membership"):
        await admin_routes.list_system_configuration(
            request=request,
            response=Response(),
            context=context,
        )

    production_container = SimpleNamespace(
        settings=settings().model_copy(update={"app_env": "production"})
    )
    monkeypatch.setattr(
        admin_routes,
        "get_container",
        lambda _request: production_container,
    )
    probe_response = Response()
    with pytest.raises(ForbiddenError, match="development"):
        await admin_routes.test_deployment_system_configuration(
            system_id="DATAHUB_GMS",
            request=request,
            response=probe_response,
            context=context,
        )
    assert probe_response.headers["Cache-Control"] == "no-store, private"

    development_container = SimpleNamespace(
        settings=settings().model_copy(update={"app_env": "development"})
    )
    monkeypatch.setattr(
        admin_routes,
        "get_container",
        lambda _request: development_container,
    )
    probe = AsyncMock()
    monkeypatch.setattr(admin_routes, "probe_system_configuration", probe)
    monkeypatch.setattr(admin_routes, "_service", lambda _request: denied_service)
    denied_probe_response = Response()
    with pytest.raises(ForbiddenError, match="not available"):
        await admin_routes.test_deployment_system_configuration(
            system_id="DATAHUB_GMS",
            request=request,
            response=denied_probe_response,
            context=context,
        )
    assert denied_probe_response.headers["Cache-Control"] == "no-store, private"
    probe.assert_not_awaited()

    monkeypatch.setattr(admin_routes, "_service", lambda _request: non_admin_service)
    non_admin_probe_response = Response()
    with pytest.raises(ForbiddenError, match="Administrator membership"):
        await admin_routes.test_deployment_system_configuration(
            system_id="DATAHUB_GMS",
            request=request,
            response=non_admin_probe_response,
            context=context,
        )
    assert non_admin_probe_response.headers["Cache-Control"] == "no-store, private"
    probe.assert_not_awaited()

    with pytest.raises(ValidationError, match="identifier"):
        await admin_routes.test_deployment_system_configuration(
            system_id="NOT_A_SYSTEM",
            request=request,
            response=Response(),
            context=context,
        )

    factory = cast(Callable[[Settings], AppContainer], lambda _: LiveOnlyContainer())
    operation = create_app(settings(), container_factory=factory).openapi()["paths"][
        "/api/v1/admin/system-configuration/{system_id}/test-deployment"
    ]["post"]
    assert "requestBody" not in operation


def test_upload_preparation_openapi_is_typed_and_server_managed() -> None:
    factory = cast(Callable[[Settings], AppContainer], lambda _: LiveOnlyContainer())
    document = create_app(settings(), container_factory=factory).openapi()

    initiate = document["components"]["schemas"]["UploadInitiateRequest"]
    profile = initiate["properties"]["content_profile"]
    assert profile["default"] == "FORMAT_ONLY_V1"
    assert profile["enum"] == [
        "FORMAT_ONLY_V1",
        "CATALOG_METADATA_ROWS_CSV_V1",
        "CATALOG_METADATA_ROWS_XLSX_V1",
    ]

    create = document["paths"]["/api/v1/uploads/{upload_id}/preparations"]["post"]
    assert "requestBody" not in create
    headers = {parameter["name"]: parameter for parameter in create["parameters"]}
    assert headers["If-Match"]["required"] is True
    assert headers["If-Match"]["schema"]["minLength"] == 3
    assert headers["Idempotency-Key"]["required"] is True
    assert headers["Idempotency-Key"]["schema"]["minLength"] == 16

    response = document["components"]["schemas"]["UploadPreparationResponse"]
    assert set(response["properties"]) == {
        "id",
        "upload_id",
        "content_profile",
        "source_manifest_version",
        "source_sha256",
        "configuration_hash",
        "state",
        "attempts",
        "rows_processed",
        "total_rows",
        "last_error_code",
        "created_at",
        "updated_at",
        "version",
    }
    assert {
        "bucket",
        "object_key",
        "lease_token",
        "lease_until",
        "requested_by",
        "parser_configuration",
        "rows",
    }.isdisjoint(response["properties"])


def test_typed_upload_template_is_an_authenticated_server_versioned_download() -> None:
    factory = cast(Callable[[Settings], AppContainer], lambda _: LiveOnlyContainer())
    document = create_app(settings(), container_factory=factory).openapi()

    operation = document["paths"]["/api/v1/uploads/profiles/{content_profile}/template"]["get"]
    assert "requestBody" not in operation
    profile = next(
        parameter for parameter in operation["parameters"] if parameter["name"] == "content_profile"
    )
    assert set(profile["schema"]["enum"]) == {
        "CATALOG_METADATA_ROWS_CSV_V1",
        "CATALOG_METADATA_ROWS_XLSX_V1",
    }
    content = operation["responses"]["200"]["content"]
    assert "application/json" not in content
    assert content == {
        "text/csv": {"schema": {"type": "string", "format": "binary"}},
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {
            "schema": {"type": "string", "format": "binary"}
        },
    }


def test_upload_candidate_openapi_is_bounded_read_only_and_non_disclosing() -> None:
    factory = cast(Callable[[Settings], AppContainer], lambda _: LiveOnlyContainer())
    document = create_app(settings(), container_factory=factory).openapi()

    operation = document["paths"][
        "/api/v1/uploads/{upload_id}/preparations/{preparation_id}/candidates"
    ]["get"]
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    assert parameters["limit"]["schema"] == {
        "type": "integer",
        "maximum": 50,
        "minimum": 1,
        "default": 20,
        "title": "Limit",
    }
    assert parameters["cursor"]["schema"]["anyOf"][0]["maxLength"] == 2048
    assert "requestBody" not in operation

    page = document["components"]["schemas"]["UploadRegistrationCandidateListResponse"]
    assert set(page["properties"]) == {"items", "page", "receipt", "meta"}
    candidate = document["components"]["schemas"]["UploadRegistrationCandidateResponse"]
    assert set(candidate["properties"]) == {
        "ordinal",
        "candidate_hash",
        "id",
        "proposed_description",
        "submitted_identity",
        "current_target",
        "created_at",
    }
    serialized = str({page["title"]: page, candidate["title"]: candidate}).lower()
    for forbidden in (
        "total",
        "bucket",
        "object_key",
        "etag",
        "requested_by",
        "raw",
        "provider",
        "after_document",
    ):
        assert forbidden not in serialized


def test_registration_operator_capability_is_read_only_and_server_owned() -> None:
    factory = cast(Callable[[Settings], AppContainer], lambda _: LiveOnlyContainer())
    document = create_app(settings(), container_factory=factory).openapi()

    operation = document["paths"]["/api/v1/uploads/operator-capability"]["get"]
    assert "requestBody" not in operation
    response = document["components"]["schemas"]["RegistrationOperatorCapabilityResponse"]
    assert set(response["properties"]) == {
        "eligible",
        "can_view_workspace_history",
        "reason_code",
        "allowed_roles",
    }
    serialized = str(response).lower()
    for forbidden in ("groups", "job_function", "subject_id", "token", "credential"):
        assert forbidden not in serialized


def test_typed_bulk_candidate_command_accepts_no_provider_or_storage_document() -> None:
    factory = cast(Callable[[Settings], AppContainer], lambda _: LiveOnlyContainer())
    document = create_app(settings(), container_factory=factory).openapi()
    base = "/api/v1/uploads/{upload_id}/preparations/{preparation_id}/candidates/{candidate_id}"
    preview = document["paths"][f"{base}/preview"]["get"]
    creation = document["paths"][f"{base}/change-request"]["post"]
    assert "requestBody" not in preview
    headers = {
        parameter["name"] for parameter in creation["parameters"] if parameter.get("in") == "header"
    }
    assert {"If-Match", "Idempotency-Key"} <= headers
    request_schema = document["components"]["schemas"]["TypedBulkChangeRequestCreate"]
    assert set(request_schema["properties"]) == {"title", "reason"}
    response_schema = document["components"]["schemas"]["TypedBulkCandidatePreviewResponse"]
    serialized = str(
        {
            "request": request_schema,
            "response": response_schema,
        }
    ).lower()
    for forbidden in (
        "after_document",
        "object_key",
        "bucket",
        "accepted_etag",
        "accepted_version_id",
        "credential",
        "token",
    ):
        assert forbidden not in serialized


def test_catalog_metadata_candidate_contract_is_bounded_and_non_disclosing() -> None:
    factory = cast(Callable[[Settings], AppContainer], lambda _: LiveOnlyContainer())
    document = create_app(settings(), container_factory=factory).openapi()
    base = "/api/v1/uploads/{upload_id}/preparations/{preparation_id}/metadata-candidates"

    listing = document["paths"][base]["get"]
    parameters = {parameter["name"]: parameter for parameter in listing["parameters"]}
    assert "requestBody" not in listing
    assert parameters["limit"]["schema"] == {
        "type": "integer",
        "maximum": 50,
        "minimum": 1,
        "default": 20,
        "title": "Limit",
    }
    assert parameters["cursor"]["schema"]["anyOf"][0]["maxLength"] == 2048

    preview = document["paths"][f"{base}/{{candidate_id}}/preview"]["get"]
    creation = document["paths"][f"{base}/{{candidate_id}}/change-request"]["post"]
    assert "requestBody" not in preview
    headers = {
        parameter["name"] for parameter in creation["parameters"] if parameter.get("in") == "header"
    }
    assert {"If-Match", "Idempotency-Key"} <= headers

    request_schema = document["components"]["schemas"]["TypedBulkChangeRequestCreate"]
    candidate_schema = document["components"]["schemas"]["CatalogMetadataCandidateResponse"]
    preview_schema = document["components"]["schemas"]["TypedCatalogMetadataPreviewResponse"]
    response_schema = document["components"]["schemas"]["TypedCatalogMetadataChangeRequestResponse"]
    assert set(request_schema["properties"]) == {"title", "reason"}
    assert set(response_schema["properties"]) == {"id", "number", "request_type", "state"}
    assert "aspect_name" not in candidate_schema["properties"]
    assert "aspect_name" not in preview_schema["properties"]
    assert candidate_schema["properties"]["field_path_sample"]["maxItems"] == 20
    assert preview_schema["properties"]["description_change_sample"]["maxItems"] == 20

    serialized = str(
        {
            "candidate": candidate_schema,
            "preview": preview_schema,
            "request": request_schema,
            "response": response_schema,
        }
    ).lower()
    for forbidden in (
        "after_document",
        "object_key",
        "bucket",
        "provider",
        "controlled_ref_id",
        "controlled_ref_urn",
        "credential",
        "token",
    ):
        assert forbidden not in serialized


def test_governance_apply_report_is_bounded_and_exposes_only_sanitized_evidence() -> None:
    factory = cast(Callable[[Settings], AppContainer], lambda _: LiveOnlyContainer())
    document = create_app(settings(), container_factory=factory).openapi()

    operation = document["paths"]["/api/v1/change-requests/{change_request_id}/apply-report"]["get"]
    assert "requestBody" not in operation
    report = document["components"]["schemas"]["GovernanceApplyReportResponse"]
    assert report["properties"]["items"]["maxItems"] == 200
    assert report["properties"]["attempts"]["maxItems"] == 20
    serialized = str(report).lower()
    for forbidden in (
        "after_document",
        "target_ref",
        "operation_id",
        "raw_response",
        "credential",
        "token",
    ):
        assert forbidden not in serialized


def test_registration_if_match_requires_a_canonical_quoted_positive_version() -> None:
    assert _expected_version('"7"') == 7
    for value in ("7", '"0"', '"01"', 'W/"7"', '"-1"'):
        with pytest.raises(ValidationError):
            _expected_version(value)


def test_catalog_description_openapi_is_typed_and_server_binds_the_target() -> None:
    factory = cast(Callable[[Settings], AppContainer], lambda _: LiveOnlyContainer())
    document = create_app(settings(), container_factory=factory).openapi()

    preview_request = document["components"]["schemas"]["CatalogDescriptionPreviewRequest"]
    assert set(preview_request["properties"]) == {"description"}
    change_request = document["components"]["schemas"]["CatalogDescriptionChangeRequest"]
    assert set(change_request["properties"]) == {
        "description",
        "title",
        "change_description",
        "requested_due_date",
        "priority",
        "urgency",
    }
    assert {"target_ref", "aspect_name", "classification", "after_document"}.isdisjoint(
        change_request["properties"]
    )

    preview_response = document["components"]["schemas"]["CatalogDescriptionPreviewResponse"]
    assert set(preview_response["properties"]) == {
        "asset_id",
        "target_ref",
        "aspect_name",
        "current_description",
        "proposed_description",
        "before_hash",
        "after_hash",
        "preview_etag",
        "source_version",
        "observed_at",
    }
    assert preview_response["properties"]["preview_etag"]["pattern"] == ('^"[0-9a-f]{64}"$')

    creation = document["paths"]["/api/v1/catalog/assets/{asset_id}/description-change-requests"][
        "post"
    ]
    headers = {parameter["name"]: parameter for parameter in creation["parameters"]}
    assert headers["If-Match"]["required"] is True
    assert headers["If-Match"]["schema"]["minLength"] == 66
    assert headers["If-Match"]["schema"]["maxLength"] == 66
    assert headers["Idempotency-Key"]["required"] is True


def test_catalog_export_openapi_is_server_managed_and_does_not_expose_storage_coordinates() -> None:
    factory = cast(Callable[[Settings], AppContainer], lambda _: LiveOnlyContainer())
    document = create_app(settings(), container_factory=factory).openapi()

    create = document["components"]["schemas"]["CatalogExportCreateRequest"]
    assert set(create["properties"]) == {
        "q",
        "asset_type",
        "platform",
        "database_name",
        "schema_name",
        "domain",
        "search_fields",
        "classification",
        "lifecycle",
        "sort",
        "format",
    }
    status = document["components"]["schemas"]["CatalogExportStatusResponse"]
    assert {"bucket", "object_key", "storage_key", "cursor"}.isdisjoint(status["properties"])
    download = document["components"]["schemas"]["CatalogExportDownloadResponse"]
    assert set(download["properties"]) == {"url", "expires_seconds"}

    capability = document["components"]["schemas"]["CatalogExportCapabilityResponse"]
    assert set(capability["properties"]) == {"enabled"}


def test_knowledge_source_job_openapi_is_durable_bounded_and_non_disclosing() -> None:
    factory = cast(Callable[[Settings], AppContainer], lambda _: LiveOnlyContainer())
    document = create_app(settings(), container_factory=factory).openapi()

    analyze = document["paths"]["/api/v1/knowledge/graphs/{graph_id}/sources/{upload_id}/analyze"][
        "post"
    ]
    analyze_headers = {parameter["name"]: parameter for parameter in analyze["parameters"]}
    assert set(analyze["responses"]) >= {"202", "422"}
    assert "201" not in analyze["responses"]
    assert analyze_headers["Idempotency-Key"]["required"] is True
    assert analyze_headers["Idempotency-Key"]["schema"]["minLength"] == 16

    collection = document["paths"]["/api/v1/knowledge/graphs/{graph_id}/source-analysis-jobs"][
        "get"
    ]
    query = {parameter["name"]: parameter for parameter in collection["parameters"]}
    assert query["limit"]["schema"]["minimum"] == 1
    assert query["limit"]["schema"]["maximum"] == 100
    assert query["cursor"]["schema"]["anyOf"][0]["maxLength"] == 2000

    cancel = document["paths"][
        "/api/v1/knowledge/graphs/{graph_id}/source-analysis-jobs/{job_id}/cancel"
    ]["post"]
    cancel_headers = {parameter["name"]: parameter for parameter in cancel["parameters"]}
    assert cancel_headers["If-Match"]["required"] is True
    assert cancel_headers["Idempotency-Key"]["required"] is True
    assert cancel_headers["Idempotency-Key"]["schema"]["minLength"] == 16

    job = document["components"]["schemas"]["KnowledgeSourceJobResponse"]
    assert {
        "bucket",
        "object_key",
        "endpoint",
        "credential",
        "lease_token",
        "lease_token_hash",
        "worker_fingerprint",
    }.isdisjoint(job["properties"])
    result = document["components"]["schemas"]["KnowledgeSourceJobResultResponse"]
    assert set(result["properties"]) == {
        "changeset_id",
        "page_count",
        "proposed_node_count",
        "proposed_edge_count",
        "evidence_hash",
        "embedding_model",
        "extraction_model",
    }


def test_change_write_contract_requires_source_hash_and_governed_aspect() -> None:
    factory = cast(Callable[[Settings], AppContainer], lambda _: LiveOnlyContainer())
    document = create_app(settings(), container_factory=factory).openapi()
    expected_aspects = {
        "datasetProperties",
        "domains",
        "globalTags",
        "glossaryTerms",
        "ownership",
        "schemaMetadata",
    }

    change_item = document["components"]["schemas"]["ChangeItemRequest"]
    change_request = document["components"]["schemas"]["ChangeRequestCreate"]
    assert change_request["properties"]["items"]["minItems"] == 1
    assert change_request["properties"]["items"]["maxItems"] == 1
    assert "before_hash" in change_item["required"]
    assert change_item["properties"]["target_ref"]["pattern"] == "^urn:li:dataset:"
    assert set(change_item["properties"]["aspect_name"]["enum"]) == expected_aspects
    assert change_item["properties"]["before_hash"]["pattern"] == "^[0-9a-f]{64}$"

    registration = document["components"]["schemas"]["UploadRegistrationProposal"]
    assert "before_hash" in registration["required"]
    assert set(registration["properties"]["aspect_name"]["enum"]) == expected_aspects


def test_openapi_keeps_inference_profile_proposals_out_of_the_browser_contract() -> None:
    factory = cast(Callable[[Settings], AppContainer], lambda _: LiveOnlyContainer())
    document = create_app(settings(), container_factory=factory).openapi()

    collection = document["paths"]["/api/v1/admin/inference/provider-profiles"]
    assert set(collection) == {"get"}
    serialized = str(document["components"]["schemas"]).lower()
    for forbidden in ("endpoint_url", "api_key", "credential", "secret_key"):
        assert forbidden not in serialized


def test_openapi_exposes_only_local_bounded_catalog_metadata_vocabulary_contract() -> None:
    factory = cast(Callable[[Settings], AppContainer], lambda _: LiveOnlyContainer())
    document = create_app(settings(), container_factory=factory).openapi()

    listing = document["paths"]["/api/v1/uploads/metadata-vocabulary"]["get"]
    assert "requestBody" not in listing
    parameters = {parameter["name"]: parameter for parameter in listing["parameters"]}
    assert parameters["limit"]["schema"]["minimum"] == 1
    assert parameters["limit"]["schema"]["maximum"] == 50
    assert parameters["cursor"]["schema"]["anyOf"][0]["maxLength"] == 2000
    assert parameters["q"]["schema"]["anyOf"][0]["maxLength"] == 200
    assert set(parameters["kind"]["schema"]["enum"]) == {"DOMAIN", "TAG", "TERM"}

    entry = document["components"]["schemas"]["CatalogMetadataVocabularyItemResponse"]
    assert set(entry["properties"]) == {
        "id",
        "kind",
        "display_name",
        "source_version",
    }
    serialized_entry = str(entry).lower()
    for forbidden in (
        "provider",
        "provider_ref",
        "urn",
        "credential",
        "secret",
        "endpoint",
    ):
        assert forbidden not in serialized_entry
    listing_schema = document["components"]["schemas"]["CatalogMetadataVocabularyListResponse"]
    assert listing_schema["properties"]["items"]["maxItems"] == 50

    mutation = document["paths"]["/api/v1/uploads/metadata-vocabulary/sync"]["post"]
    assert any(
        parameter["name"] == "Idempotency-Key" and parameter["required"] is True
        for parameter in mutation["parameters"]
    )
    request_schema = document["components"]["schemas"]["CatalogMetadataVocabularySyncRequest"]
    assert set(request_schema["properties"]) == {"sync_id", "kind", "offset", "limit"}


def test_classification_admin_requests_cannot_supply_policy_bindings_for_grants() -> None:
    factory = cast(Callable[[Settings], AppContainer], lambda _: LiveOnlyContainer())
    document = create_app(settings(), container_factory=factory).openapi()

    grant_request = document["components"]["schemas"]["RestrictedSearchGrantProposalRequest"]
    assert set(grant_request["properties"]) == {
        "subject_id",
        "scope",
        "scope_id",
        "purpose",
        "valid_from",
        "expires_at",
        "reason",
    }
    assert "classification_policy_id" not in grant_request["properties"]
    assert "classification_policy_hash" not in grant_request["properties"]


def test_openapi_exposes_bounded_typed_administrator_read_contracts() -> None:
    factory = cast(Callable[[Settings], AppContainer], lambda _: LiveOnlyContainer())
    document = create_app(settings(), container_factory=factory).openapi()

    membership_list = document["paths"]["/api/v1/admin/workspace-memberships"]["get"]
    membership_parameters = {
        parameter["name"]: parameter for parameter in membership_list["parameters"]
    }
    limit = membership_parameters["limit"]
    assert limit["schema"]["default"] == 50
    assert limit["schema"]["minimum"] == 1
    assert limit["schema"]["maximum"] == 100
    assert membership_parameters["q"]["schema"]["anyOf"][0]["maxLength"] == 200
    assert membership_parameters["cursor"]["schema"]["anyOf"][0]["maxLength"] == 2000
    assert set(membership_parameters["status"]["schema"]["anyOf"][0]["enum"]) == {
        "ACTIVE",
        "INACTIVE",
    }
    membership_page = document["components"]["schemas"]["WorkspaceMembershipListResponse"]
    assert set(membership_page["required"]) == {"items", "page"}

    execution = document["paths"][
        "/api/v1/admin/retention/erasure-requests/{erasure_request_id}/execution-evidence"
    ]["get"]
    assert "requestBody" not in execution
    execution_schema = document["components"]["schemas"]["RetentionExecutionJobResponse"]
    serialized_schema = str(execution_schema)
    for forbidden in (
        "object_bucket",
        "object_key",
        "object_version_id",
        "provider_checksum",
        "lease_token",
        "lease_owner",
        "principal_fingerprint",
        "archive_configuration",
    ):
        assert forbidden not in serialized_schema

    membership_detail = document["paths"][
        "/api/v1/admin/workspace-memberships/{target_subject_id}/access"
    ]["get"]
    assert membership_detail["responses"]["200"]["headers"]["ETag"]["schema"] == {"type": "string"}
    access_schema = document["components"]["schemas"]["MembershipAccessDocumentResponse"]
    assert set(access_schema["required"]) == {
        "active",
        "clearance",
        "groups",
        "allowed_actions",
        "denied_actions",
        "allowed_system_ids",
        "allowed_domain_ids",
    }

    context_schema = document["components"]["schemas"]["AdminReadContextResponse"]
    assert set(context_schema["properties"]["authentication_assurance"]["enum"]) == {
        "UNKNOWN",
        "PASSWORD",
        "OTHER_MFA",
        "PASSWORD_REAUTH",
        "HARDWARE_WEBAUTHN",
    }
    operation_schema = document["components"]["schemas"]["AdminOperation"]
    assert context_schema["properties"]["allowed_operations"]["items"] == {
        "$ref": "#/components/schemas/AdminOperation"
    }
    assert set(operation_schema["enum"]) == {
        "IDENTITY_USER_PROVISION",
        "MEMBERSHIP_ACCESS_READ",
        "MEMBERSHIP_ACCESS_UPDATE",
        "MEMBERSHIP_RENEWAL_READ",
        "MEMBERSHIP_RENEWAL_DECIDE",
        "SYSTEM_ASSIGNMENT_UPDATE",
        "SYSTEM_CONFIGURATION_READ",
        "SYSTEM_CONFIGURATION_UPDATE",
        "SYSTEM_CONFIGURATION_ACTIVATE",
        "FALLBACK_REQUEST_READ",
        "FALLBACK_REQUEST_CREATE",
        "FALLBACK_REQUEST_DECIDE",
        "FALLBACK_REQUEST_CONSUME",
        "CLASSIFICATION_POLICY_READ",
        "CLASSIFICATION_POLICY_PROPOSE",
        "CLASSIFICATION_POLICY_DECIDE",
        "INFERENCE_PROVIDER_PROFILE_READ",
        "INFERENCE_PROVIDER_PROFILE_DECIDE",
        "INFERENCE_PROVIDER_PROFILE_REVOKE",
        "RESTRICTED_SEARCH_GRANT_READ",
        "RESTRICTED_SEARCH_GRANT_PROPOSE",
        "RESTRICTED_SEARCH_GRANT_DECIDE",
        "RESTRICTED_SEARCH_GRANT_REVOKE",
        "RETENTION_POLICY_READ",
        "RETENTION_POLICY_MANAGE",
        "LEGAL_HOLD_READ",
        "LEGAL_HOLD_PLACE",
        "LEGAL_HOLD_RELEASE",
        "ERASURE_READ",
        "ERASURE_REQUEST",
        "ERASURE_APPROVE",
    }
    system_assignment = document["paths"]["/api/v1/admin/systems/{system_id}/assignees"]["put"]
    assignment_headers = {
        parameter["name"]: parameter for parameter in system_assignment["parameters"]
    }
    assert assignment_headers["If-Match"]["required"] is True
    assert assignment_headers["Idempotency-Key"]["required"] is True
    assert system_assignment["responses"]["200"]["headers"]["ETag"]["schema"] == {"type": "string"}
    system_assignee_path = document["paths"]["/api/v1/admin/systems/{system_id}/assignees"]
    assert set(system_assignee_path) == {"get", "put", "patch"}
    assignee_list = system_assignee_path["get"]
    assignee_list_parameters = {
        parameter["name"]: parameter for parameter in assignee_list["parameters"]
    }
    assert assignee_list_parameters["limit"]["schema"] == {
        "type": "integer",
        "maximum": 100,
        "minimum": 1,
        "default": 25,
        "title": "Limit",
    }
    assert assignee_list_parameters["cursor"]["schema"]["anyOf"][0]["maxLength"] == 2000
    assignee_list_schema = document["components"]["schemas"]["SystemAssigneeListResponse"]
    assert set(assignee_list_schema["required"]) == {"system_version", "items", "page"}
    assignee_item_schema = document["components"]["schemas"]["SystemDirectoryAssigneeResponse"]
    assert set(assignee_item_schema["required"]) == {
        "subject_id",
        "display_name",
        "responsibility",
        "priority",
        "active",
    }
    patch_assignment = system_assignee_path["patch"]
    patch_headers = {parameter["name"]: parameter for parameter in patch_assignment["parameters"]}
    assert patch_headers["If-Match"]["required"] is True
    assert patch_headers["Idempotency-Key"]["required"] is True
    assert patch_assignment["responses"]["200"]["headers"]["ETag"]["schema"] == {"type": "string"}
    patch_schema_reference = patch_assignment["requestBody"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    assert patch_schema_reference == "#/components/schemas/SystemAssigneePatchRequest"
    patch_schema = document["components"]["schemas"]["SystemAssigneePatchRequest"]
    assert patch_schema["properties"]["upserts"]["maxItems"] == 100
    assert patch_schema["properties"]["removals"]["maxItems"] == 100
    assert context_schema["properties"]["action_vocabulary"]["items"] == {
        "$ref": "#/components/schemas/Action"
    }
    assert set(document["components"]["schemas"]["Action"]["enum"]) == {
        action.value for action in Action
    }


def test_forbidden_problem_exposes_only_bounded_remediation() -> None:
    factory = cast(Callable[[Settings], AppContainer], lambda _: LiveOnlyContainer())
    app = create_app(settings(), container_factory=factory)

    @app.get("/test-remediation")
    async def remediation_error() -> None:
        raise ForbiddenError(
            "Step-up is required.",
            details={
                "decision_id": "internal-decision",
                "reason_codes": ("PHISHING_RESISTANT_AUTH_REQUIRED",),
                "remediation": {"kind": "FIDO2_REQUIRED", "internal": "not-public"},
            },
        )

    with TestClient(app) as client:
        response = client.get("/test-remediation")

    assert response.status_code == 403
    assert response.headers["Content-Type"].startswith("application/problem+json")
    assert response.json()["remediation"] == {"kind": "FIDO2_REQUIRED"}
    assert "reason_codes" not in response.json()
    assert "decision_id" not in response.json()
    assert "internal" not in response.text
