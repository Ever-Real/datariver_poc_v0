from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = ROOT / "frontend" / "nginx.conf.template"
VERIFIER = ROOT / "scripts" / "verify_nginx_headers.py"

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; base-uri 'self'; object-src 'none'; "
        "frame-ancestors 'none'; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; "
        "connect-src 'self' ${S3_PUBLIC_ORIGIN} ${OIDC_PUBLIC_ORIGIN}; "
        "frame-src ${OIDC_PUBLIC_ORIGIN} ${DATAHUB_EMBED_BASE_URL} "
        "${GRAFANA_EMBED_BASE_URL}; form-action 'self' ${OIDC_PUBLIC_ORIGIN}"
    ),
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_nginx_headers", VERIFIER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _location(source: str, declaration: str) -> str:
    start = source.index(declaration)
    body_start = source.index(" {", start) + 2
    depth = 1
    cursor = body_start
    while depth:
        if source[cursor] == "{":
            depth += 1
        elif source[cursor] == "}":
            depth -= 1
        cursor += 1
    return source[body_start : cursor - 1]


def test_nginx_merges_security_headers_into_every_location_and_normalizes_api() -> None:
    source = TEMPLATE.read_text(encoding="utf-8")

    assert source.count("add_header_inherit merge;") == 1
    for name, value in SECURITY_HEADERS.items():
        assert source.count(f'add_header {name} "{value}" always;') == 1

    api = _location(source, "location /api/")
    hidden_headers = re.findall(
        r"proxy_hide_header\s+([^;]+);",
        api,
        flags=re.IGNORECASE,
    )
    assert len(hidden_headers) == len(SECURITY_HEADERS)
    assert {header.casefold() for header in hidden_headers} == {
        header.casefold() for header in SECURITY_HEADERS
    }

    assert 'add_header Cache-Control "no-store" always;' in _location(source, "location = /healthz")
    assert 'add_header Cache-Control "no-store" always;' in _location(
        source, "location = /runtime-config.js"
    )
    assert 'add_header Cache-Control "no-store" always;' in _location(source, "location / {")
    assert 'add_header Cache-Control "public, immutable";' in _location(source, "location /assets/")
    assert "client_max_body_size 12m;" in api
    assert "strict-transport-security" not in source.casefold()


def test_document_proposal_timeout_is_scoped_and_bounded() -> None:
    source = TEMPLATE.read_text(encoding="utf-8")
    proposal = _location(
        source,
        'location ~ "^/api/v1/knowledge/studio/drafts/[0-9a-fA-F-]{36}/tbox/document-proposals$"',
    )
    api = _location(source, "location /api/")
    entrypoint = (ROOT / "frontend" / "docker-entrypoint.sh").read_text(encoding="utf-8")
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    host_development = (ROOT / "compose.host-dev.yaml").read_text(encoding="utf-8")

    assert (
        "proxy_read_timeout ${KNOWLEDGE_STUDIO_DOCUMENT_PROXY_READ_TIMEOUT_SECONDS}s;" in proposal
    )
    assert "proxy_read_timeout ${API_PROXY_READ_TIMEOUT_SECONDS}s;" in api
    assert "KNOWLEDGE_STUDIO_DOCUMENT_PROXY_READ_TIMEOUT_SECONDS:-135" in entrypoint
    assert "integer between 1 and 900" in entrypoint
    assert (
        "KNOWLEDGE_STUDIO_DOCUMENT_PROXY_READ_TIMEOUT_SECONDS: "
        "${KNOWLEDGE_STUDIO_DOCUMENT_PROXY_READ_TIMEOUT_SECONDS:-135}" in compose
    )
    assert (
        "KNOWLEDGE_STUDIO_DOCUMENT_PROXY_READ_TIMEOUT_SECONDS: "
        "${HOST_DEV_KNOWLEDGE_STUDIO_DOCUMENT_PROXY_READ_TIMEOUT_SECONDS:-900}" in host_development
    )


def test_live_verifier_parses_headers_and_rejects_duplicates() -> None:
    module = _module()
    csp = "default-src 'self'; frame-ancestors 'none'"
    raw = "\n".join(
        (
            "  HTTP/1.1 503 Service Unavailable",
            f"  Content-Security-Policy: {csp}",
            "  Permissions-Policy: camera=(), microphone=(), geolocation=()",
            "  Referrer-Policy: no-referrer",
            "  X-Content-Type-Options: nosniff",
            "  X-Frame-Options: DENY",
            "  Cache-Control: private, no-store",
        )
    )
    response = module._parse_http_response(f"{raw}\r\n\r\n".encode() + b'{"state":"fixture"}')

    assert response.status == 503
    assert response.body == b'{"state":"fixture"}'
    module._assert_security_headers(response, csp)

    duplicate = module._parse_http_response(
        f"{raw}\n  X-Frame-Options: SAMEORIGIN\r\n\r\n".encode()
    )
    with pytest.raises(AssertionError, match="X-Frame-Options"):
        module._assert_security_headers(duplicate, csp)


def test_live_verifier_is_offline_native_platform_and_exact_cleanup_scoped() -> None:
    source = VERIFIER.read_text(encoding="utf-8")

    assert '"--pull=never"' in source
    assert '"--internal"' in source
    assert '"--read-only"' in source
    assert '"--cap-drop",' in source
    assert '"ALL",' in source
    assert '"no-new-privileges:true"' in source
    assert "daemon_platform != image_platform" in source
    assert '"sha256sum"' in source
    assert "web image does not embed the current Nginx source boundary" in source
    assert "docker system prune" not in source
    assert "docker image prune" not in source
