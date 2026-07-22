from __future__ import annotations

from collections.abc import Callable
from typing import cast

import pytest
from fastapi.testclient import TestClient

from datariver.config import Settings
from datariver.domain.authz import Action
from datariver.domain.common import ForbiddenError, ValidationError
from datariver.infrastructure.db.session import DatabaseReadiness
from datariver.infrastructure.observability.metrics import HttpMetrics
from datariver.interfaces.http.container import AppContainer
from datariver.interfaces.http.factory import create_app
from datariver.interfaces.http.routes.admin import (
    _display_configuration,
    _system_configuration_entries,
    _validate_configuration_submission,
    _validate_system_configuration,
)
from datariver.interfaces.http.routes.registration import _expected_version


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
        "/api/v1/uploads/{upload_id}/preparations",
        "/api/v1/uploads/{upload_id}/preparations/{preparation_id}",
        "/api/v1/uploads/{upload_id}/preparations/{preparation_id}/candidates",
        "/api/v1/uploads/{upload_id}/registration-proposals",
        "/api/v1/change-requests",
        "/api/v1/operations/summary",
        "/api/v1/operations/metrics",
        "/api/v1/knowledge/graphs",
        "/api/v1/chat/query",
        "/api/v1/catalog/sync/datahub",
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
        "/api/v1/admin/workspace-memberships/{target_subject_id}/role",
        "/api/v1/admin/workspace-memberships",
        "/api/v1/admin/access-roles",
        "/api/v1/admin/access-roles/{role_id}",
        "/api/v1/admin/systems",
        "/api/v1/admin/systems/{system_id}/assignees",
        "/api/v1/admin/system-configuration",
        "/api/v1/admin/system-configuration/{system_id}",
        "/api/v1/admin/system-configuration/{system_id}/versions",
        "/api/v1/admin/system-configuration/{system_id}/test",
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
        "POSTGRESQL",
        "OIDC_IDENTITY",
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
    assert any(field.secret for field in by_id["S3_STORAGE"].connection_requirements)
    assert by_id["LLM_CHAT_MODEL"].state == "GOVERNED_PROFILE_REQUIRED"
    assert by_id["GRAFANA_DASHBOARD"].embedding_state == "AVAILABLE"
    assert all(entry.template_yaml == "" for entry in entries)
    assert all(entry.display_yaml == "" for entry in entries)
    assert all("url" not in entry.model_dump() for entry in entries)
    assert all("secret_reference" not in entry.model_dump() for entry in entries)

    development = Settings(**(configured.model_dump() | {"app_env": "development"}))
    development_entries = _system_configuration_entries(development)
    connector_entries = [
        entry for entry in development_entries if entry.requirement != "BOOTSTRAP_REQUIRED"
    ]
    assert all(entry.template_yaml for entry in connector_entries)
    assert any("file:/run/secrets/" in entry.template_yaml for entry in development_entries)
    assert all("auth_token" not in entry.template_yaml.lower() for entry in development_entries)
    assert all("api_token" not in entry.template_yaml.lower() for entry in development_entries)


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
            document | {"secret_references": {}},
        )


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


def test_upload_preparation_openapi_is_typed_and_server_managed() -> None:
    factory = cast(Callable[[Settings], AppContainer], lambda _: LiveOnlyContainer())
    document = create_app(settings(), container_factory=factory).openapi()

    initiate = document["components"]["schemas"]["UploadInitiateRequest"]
    profile = initiate["properties"]["content_profile"]
    assert profile["default"] == "FORMAT_ONLY_V1"
    assert profile["enum"] == [
        "FORMAT_ONLY_V1",
        "DATASET_DESCRIPTION_CSV_V1",
        "DATASET_DESCRIPTION_XLSX_V1",
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
        "evidence_version",
        "candidate_kind",
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
    limit = next(
        parameter for parameter in membership_list["parameters"] if parameter["name"] == "limit"
    )
    assert limit["schema"]["default"] == 50
    assert limit["schema"]["minimum"] == 1
    assert limit["schema"]["maximum"] == 100

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
    assert set(context_schema["properties"]["allowed_operations"]["items"]["enum"]) == {
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
