from __future__ import annotations

from collections.abc import Callable
from typing import cast

from fastapi.testclient import TestClient

from datariver.config import Settings
from datariver.domain.authz import Action
from datariver.domain.common import ForbiddenError
from datariver.infrastructure.db.session import DatabaseReadiness
from datariver.infrastructure.observability.metrics import HttpMetrics
from datariver.interfaces.http.container import AppContainer
from datariver.interfaces.http.factory import create_app


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
        "/api/v1/catalog/assets",
        "/api/v1/uploads",
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
        "/api/v1/admin/workspace-memberships",
        "/api/v1/admin/me",
        "/api/v1/admin/fallback/workspace-membership-access-requests",
        "/api/v1/admin/fallback/workspace-membership-access-requests/{access_request_id}/decisions",
        "/api/v1/admin/fallback/workspace-membership-access-requests/{access_request_id}/consume",
    }.issubset(document["paths"])


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
        "PASSWORD_REAUTH",
        "HARDWARE_WEBAUTHN",
    }
    assert set(context_schema["properties"]["allowed_operations"]["items"]["enum"]) == {
        "MEMBERSHIP_ACCESS_READ",
        "MEMBERSHIP_ACCESS_UPDATE",
        "FALLBACK_REQUEST_READ",
        "FALLBACK_REQUEST_CREATE",
        "FALLBACK_REQUEST_DECIDE",
        "FALLBACK_REQUEST_CONSUME",
    }
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
