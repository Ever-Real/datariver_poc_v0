from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, cast

import pytest
import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[3]
APISIX_ROUTES = ROOT / "infra" / "apisix" / "apisix.yaml"
APISIX_CONFIG = ROOT / "infra" / "apisix" / "config.yaml"
WEB_TEMPLATE = ROOT / "frontend" / "nginx.conf.template"
WEB_OVERLAY = ROOT / "compose.gateway-routing.yaml"
CORE_COMPOSE = ROOT / "compose.yaml"
KEYCLOAK_SYNC = ROOT / "scripts" / "configure_keycloak_host_dev.sh"
AIRFLOW = ROOT / "compose.airflow.yaml"
AIRFLOW_OVERLAY = ROOT / "compose.airflow.host-dev.yaml"

ALLOWED_PLUGINS = {"request-id", "limit-count", "proxy-rewrite"}
AUTH_PLUGINS = {
    "jwt-auth",
    "openid-connect",
    "key-auth",
    "basic-auth",
    "hmac-auth",
    "authz-keycloak",
    "forward-auth",
    "consumer-restriction",
}


def _document(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


def _assert_transparent_plugin_contract(document: dict[str, Any]) -> None:
    assert "plugins" not in document
    routes = document["routes"]
    assert isinstance(routes, list)
    for route in routes:
        plugins = route["plugins"]
        assert set(plugins) == ALLOWED_PLUGINS
        assert set(plugins).isdisjoint(AUTH_PLUGINS)


def _forward_request_headers(route: dict[str, Any], headers: dict[str, str]) -> dict[str, str]:
    forwarded = dict(headers)
    configured = route["plugins"]["proxy-rewrite"]["headers"]["set"]
    assert configured == {"X-Forwarded-Proto": "$scheme"}
    forwarded["X-Forwarded-Proto"] = "http"
    return forwarded


def test_apisix_is_a_transparent_rate_limited_router_not_an_identity_provider() -> None:
    routes = _document(APISIX_ROUTES)["routes"]
    assert isinstance(routes, list)
    assert len(routes) == 2

    for route in routes:
        assert isinstance(route, dict)
        plugins = route["plugins"]
        assert isinstance(plugins, dict)
        assert set(plugins) == ALLOWED_PLUGINS
        assert set(plugins).isdisjoint(AUTH_PLUGINS)
        assert plugins["proxy-rewrite"] == {"headers": {"set": {"X-Forwarded-Proto": "$scheme"}}}
        assert plugins["limit-count"]["key"] == "remote_addr"
        assert plugins["limit-count"]["rejected_code"] == 429

    general = next(route for route in routes if route["id"] == "datariver-api-v1")
    assert set(general["methods"]) == {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}


def test_apisix_has_no_global_plugin_or_credential_log_surface() -> None:
    config = _document(APISIX_CONFIG)
    assert config["apisix"]["enable_admin"] is False
    assert config["apisix"]["enable_control"] is False
    assert config["deployment"] == {
        "role": "data_plane",
        "role_data_plane": {"config_provider": "yaml"},
    }
    assert "plugins" not in config
    assert config["nginx_config"]["http"]["client_max_body_size"] == "12m"

    rendered = APISIX_CONFIG.read_text(encoding="utf-8").casefold()
    for forbidden in (
        "$http_authorization",
        "$http_cookie",
        "$request_body",
        "authorization:",
        "cookie:",
    ):
        assert forbidden not in rendered


def test_web_proxy_preserves_identity_cors_and_retry_headers_without_direct_fallback() -> None:
    template = WEB_TEMPLATE.read_text(encoding="utf-8")
    overlay = _document(WEB_OVERLAY)
    web = overlay["services"]["web"]

    assert "set $api_backend http://${API_PROXY_UPSTREAM};" in template
    assert web["environment"] == {"API_PROXY_UPSTREAM": "apisix:9080"}
    assert web["depends_on"] == {"apisix": {"condition": "service_healthy"}}
    assert "api:8000" not in WEB_OVERLAY.read_text(encoding="utf-8")

    hidden = {
        line.strip().removeprefix("proxy_hide_header ").removesuffix(";").casefold()
        for line in template.splitlines()
        if "proxy_hide_header" in line
    }
    assert hidden == {
        "content-security-policy",
        "permissions-policy",
        "referrer-policy",
        "x-content-type-options",
        "x-frame-options",
    }
    for preserved in (
        "authorization",
        "cookie",
        "origin",
        "access-control-request-method",
        "access-control-request-headers",
        "www-authenticate",
        "set-cookie",
        "access-control-allow-origin",
        "access-control-allow-methods",
        "access-control-allow-headers",
        "idempotency-key",
        "if-match",
        "x-request-id",
    ):
        assert preserved not in hidden


def test_gateway_overlay_does_not_change_browser_oidc_or_public_origin_contract() -> None:
    overlay = WEB_OVERLAY.read_text(encoding="utf-8")
    for forbidden in (
        "BROWSER_OIDC_AUTHORITY",
        "BROWSER_OIDC_CLIENT_ID",
        "BROWSER_OIDC_REDIRECT_URI",
        "APP_PUBLIC_ORIGIN",
        "OIDC_PUBLIC_ORIGIN",
    ):
        assert forbidden not in overlay

    web_environment = _document(CORE_COMPOSE)["services"]["web"]["environment"]
    assert web_environment["BROWSER_OIDC_AUTHORITY"] == (
        "${OIDC_PUBLIC_AUTHORITY:-http://localhost:8081/realms/datariver}"
    )
    assert web_environment["BROWSER_OIDC_CLIENT_ID"] == "${OIDC_CLIENT_ID:-datariver-web}"
    assert web_environment["BROWSER_OIDC_REDIRECT_URI"] == (
        "${APP_PUBLIC_ORIGIN:-http://localhost:8080}"
    )
    keycloak_sync = KEYCLOAK_SYNC.read_text(encoding="utf-8")
    for fragment in (
        r"redirectUris=[\"$web_origin/*\"]",
        r"webOrigins=[\"$web_origin\"]",
        "post.logout.redirect.uris",
    ):
        assert fragment in keycloak_sync


def test_selected_airflow_uses_gateway_but_acquires_tokens_directly_from_keycloak() -> None:
    base = _document(AIRFLOW)
    overlay = _document(AIRFLOW_OVERLAY)
    common = base["x-airflow-common"]["environment"]

    assert common["DATARIVER_OIDC_TOKEN_URL"].startswith("http://keycloak:8080/")
    assert common["DATARIVER_API_BASE_URL"] == "${DATARIVER_API_BASE_URL:-http://api:8000}"
    for service in (
        "airflow-api-server",
        "airflow-scheduler",
        "airflow-dag-processor",
        "airflow-triggerer",
    ):
        assert overlay["services"][service]["environment"]["DATARIVER_API_BASE_URL"] == (
            "http://apisix:9080"
        )
    assert (
        overlay["services"]["airflow-scheduler"]["environment"][
            "DATARIVER_QUALITY_DISPATCH_API_BASE_URL"
        ]
        == "http://apisix:9080"
    )
    assert "OIDC_TOKEN_URL" not in AIRFLOW_OVERLAY.read_text(encoding="utf-8")


@pytest.mark.parametrize("plugin", tuple(sorted(AUTH_PLUGINS | {"cors"})))
def test_every_auth_or_global_plugin_injection_is_rejected(plugin: str) -> None:
    route_document = _document(APISIX_ROUTES)
    injected_route = copy.deepcopy(route_document)
    injected_route["routes"][0]["plugins"][plugin] = {}
    with pytest.raises(AssertionError):
        _assert_transparent_plugin_contract(injected_route)

    injected_global = copy.deepcopy(route_document)
    injected_global["plugins"] = [plugin]
    with pytest.raises(AssertionError):
        _assert_transparent_plugin_contract(injected_global)


def test_request_and_response_identity_headers_are_transparent() -> None:
    route = next(
        item for item in _document(APISIX_ROUTES)["routes"] if item["id"] == "datariver-api-v1"
    )
    request_headers = {
        "Authorization": "Bearer synthetic-token-sentinel",
        "Cookie": "session=synthetic-cookie-sentinel",
        "Origin": "https://datariver.example.test",
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization,x-request-id",
        "X-Request-Id": "synthetic-request-id",
    }
    response_headers = {
        "WWW-Authenticate": "Bearer",
        "Set-Cookie": "session=synthetic-response-cookie",
        "Access-Control-Allow-Origin": "https://datariver.example.test",
        "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
        "Access-Control-Allow-Headers": "Authorization,X-Request-Id",
        "Cache-Control": "private, no-store",
    }

    forwarded = _forward_request_headers(route, request_headers)

    for name, value in request_headers.items():
        assert forwarded[name] == value
    assert forwarded["X-Forwarded-Proto"] == "http"
    assert dict(response_headers) == response_headers
    combined_source = APISIX_ROUTES.read_text(encoding="utf-8") + APISIX_CONFIG.read_text(
        encoding="utf-8"
    )
    for sentinel in (
        "synthetic-token-sentinel",
        "synthetic-cookie-sentinel",
        "synthetic-response-cookie",
    ):
        assert sentinel not in combined_source


def test_static_status_echo_is_not_accepted_as_gateway_auth_parity_evidence() -> None:
    source = (ROOT / "scripts" / "workflow_update_restart.py").read_text(encoding="utf-8")
    test_source = Path(__file__).read_text(encoding="utf-8")
    static_status_echo_helper = "_forward_api_" + "status_below_rate_limit"

    assert "GATEWAY_AUTH_PARITY_EVIDENCE_UNAVAILABLE" in source
    assert static_status_echo_helper not in test_source
