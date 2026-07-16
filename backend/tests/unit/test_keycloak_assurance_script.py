from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest


def _module() -> ModuleType:
    path = Path(__file__).resolve().parents[3] / "scripts" / "configure_keycloak_assurance.py"
    spec = importlib.util.spec_from_file_location("configure_keycloak_assurance", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rejects_non_loopback_plain_http() -> None:
    module = _module()

    with pytest.raises(ValueError, match="requires HTTPS"):
        module._safe_base_url("http://identity.example")


def test_foundation_removes_totp_and_adds_amr_mapper() -> None:
    module = _module()
    state: dict[str, Any] = {
        "actions": ["UPDATE_PASSWORD", "CONFIGURE_TOTP"],
        "has_mapper": False,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/users"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "user-one",
                        "username": "admin",
                        "requiredActions": state["actions"],
                    }
                ],
            )
        if path.endswith("/users/user-one") and request.method == "PUT":
            state["actions"] = json.loads(request.read())["requiredActions"]
            return httpx.Response(204)
        if path.endswith("/users/user-one/logout") and request.method == "POST":
            state["sessions_revoked"] = True
            return httpx.Response(204)
        if path.endswith("/clients"):
            return httpx.Response(200, json=[{"id": "client-one", "clientId": "web"}])
        if path.endswith("/protocol-mappers/models") and request.method == "GET":
            return httpx.Response(
                200,
                json=([{"protocolMapper": "oidc-amr-mapper"}] if state["has_mapper"] else []),
            )
        if path.endswith("/protocol-mappers/models") and request.method == "POST":
            state["has_mapper"] = True
            return httpx.Response(201)
        return httpx.Response(404)

    client = httpx.Client(
        base_url="https://identity.example",
        transport=httpx.MockTransport(handler),
    )
    admin = module.KeycloakAdmin(client=client, realm="datariver")

    changes = admin.configure_foundation(
        username="admin", client_id="web", revoke_user_sessions=True
    )
    admin.verify_foundation(username="admin", client_id="web")

    assert changes == (
        "removed-mobile-totp",
        "added-amr-mapper",
        "revoked-user-sessions",
    )
    assert state == {
        "actions": ["UPDATE_PASSWORD"],
        "has_mapper": True,
        "sessions_revoked": True,
    }
    client.close()
