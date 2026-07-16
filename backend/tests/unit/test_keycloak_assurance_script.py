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


def test_step_up_flow_is_created_verified_and_idempotent() -> None:
    module = _module()
    state: dict[str, Any] = {
        "flows": [],
        "executions": {},
        "configs": {},
        "realm": {
            "realm": "datariver",
            "browserFlow": "browser",
            "webAuthnPolicyAuthenticatorAttachment": "not specified",
            "webAuthnPolicyResidentKey": "not specified",
            "webAuthnPolicyUserVerificationRequirement": "not specified",
            "webAuthnPolicyAvoidSameAuthenticatorRegister": False,
        },
        "client": {
            "id": "client-one",
            "clientId": "web",
            "attributes": {"pkce.code.challenge.method": "S256"},
        },
        "client_scopes": [
            {
                "id": "scope-basic",
                "name": "basic",
                "protocolMappers": [
                    {
                        "name": "auth_time",
                        "protocolMapper": "oidc-usersessionmodel-note-mapper",
                        "config": module.AUTH_TIME_MAPPER_CONFIG,
                    }
                ],
            }
        ],
        "default_scopes": [],
        "required_actions": [
            {
                "alias": "webauthn-register",
                "enabled": True,
                "defaultAction": False,
            }
        ],
        "next_id": 0,
    }
    provider_names = {
        "auth-cookie": "Cookie",
        "conditional-level-of-authentication": "Condition - Level of Authentication",
        "auth-username-password-form": "Username Password Form",
        "webauthn-authenticator": "WebAuthn Authenticator",
    }

    def next_id(prefix: str) -> str:
        state["next_id"] += 1
        return f"{prefix}-{state['next_id']}"

    def body(request: httpx.Request) -> dict[str, Any]:
        document = json.loads(request.read())
        assert isinstance(document, dict)
        return document

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        if path.endswith("/authentication/required-actions") and method == "GET":
            return httpx.Response(200, json=state["required_actions"])
        if path.endswith("/authentication/flows"):
            if method == "GET":
                return httpx.Response(200, json=state["flows"])
            flow_document = body(request)
            flow_document["id"] = next_id("flow")
            state["flows"].append(flow_document)
            state["executions"][flow_document["alias"]] = []
            return httpx.Response(201)
        if "/authentication/flows/" in path and path.endswith("/executions/flow"):
            parent = path.split("/authentication/flows/", 1)[1].rsplit("/executions/flow", 1)[0]
            document = body(request)
            alias = document["alias"]
            state["flows"].append(
                {
                    "id": next_id("flow"),
                    "alias": alias,
                    "topLevel": False,
                    "builtIn": False,
                }
            )
            state["executions"][alias] = []
            execution = {
                "id": next_id("execution"),
                "providerId": "basic-flow",
                "displayName": alias,
                "authenticationFlow": True,
                "requirement": "DISABLED",
            }
            state["executions"][parent].append(execution)
            return httpx.Response(201)
        if "/authentication/flows/" in path and path.endswith("/executions/execution"):
            flow_alias = path.split("/authentication/flows/", 1)[1].rsplit(
                "/executions/execution", 1
            )[0]
            provider = body(request)["provider"]
            state["executions"][flow_alias].append(
                {
                    "id": next_id("execution"),
                    "providerId": provider,
                    "displayName": provider_names[provider],
                    "authenticationFlow": False,
                    "requirement": "DISABLED",
                }
            )
            return httpx.Response(201)
        if "/authentication/flows/" in path and path.endswith("/executions"):
            flow_alias = path.split("/authentication/flows/", 1)[1].rsplit("/executions", 1)[0]
            if method == "GET":
                return httpx.Response(200, json=state["executions"][flow_alias])
            document = body(request)
            for index, execution in enumerate(state["executions"][flow_alias]):
                if execution["id"] == document["id"]:
                    state["executions"][flow_alias][index] = document
                    return httpx.Response(204)
            return httpx.Response(404)
        if "/authentication/executions/" in path and path.endswith("/config"):
            execution_id = path.split("/authentication/executions/", 1)[1].rsplit("/config", 1)[0]
            document = body(request)
            config_id = next_id("config")
            state["configs"][config_id] = {
                "id": config_id,
                "alias": document["alias"],
                "config": document["config"],
            }
            for executions in state["executions"].values():
                for execution in executions:
                    if execution["id"] == execution_id:
                        execution["authenticationConfig"] = config_id
                        return httpx.Response(201)
            return httpx.Response(404)
        if "/authentication/config/" in path and method == "GET":
            config_id = path.rsplit("/", 1)[1]
            return httpx.Response(200, json=state["configs"][config_id])
        if path.endswith("/admin/realms/datariver"):
            if method == "GET":
                return httpx.Response(200, json=state["realm"])
            state["realm"] = body(request)
            return httpx.Response(204)
        if path.endswith("/clients") and method == "GET":
            return httpx.Response(200, json=[state["client"]])
        if path.endswith("/clients/client-one") and method == "PUT":
            state["client"] = body(request)
            return httpx.Response(204)
        if path.endswith("/clients/client-one/default-client-scopes") and method == "GET":
            return httpx.Response(200, json=state["default_scopes"])
        if path.endswith("/clients/client-one/default-client-scopes/scope-basic"):
            state["default_scopes"] = [state["client_scopes"][0]]
            return httpx.Response(204)
        if path.endswith("/admin/realms/datariver/client-scopes") and method == "GET":
            return httpx.Response(200, json=state["client_scopes"])
        return httpx.Response(404)

    client = httpx.Client(
        base_url="https://identity.example",
        transport=httpx.MockTransport(handler),
    )
    admin = module.KeycloakAdmin(client=client, realm="datariver")

    changes = admin.configure_step_up(client_id="web")
    admin.verify_step_up(client_id="web")

    assert changes == (
        "created-step-up-flow",
        "bound-step-up-flow",
        "set-default-acr",
        "attached-auth-time-scope",
    )
    assert admin.configure_step_up(client_id="web") == ()
    assert state["realm"]["browserFlow"] == module.STEP_UP_FLOW_ALIAS
    assert state["realm"]["webAuthnPolicyAuthenticatorAttachment"] == "cross-platform"
    assert state["client"]["attributes"]["default.acr.values"] == "1"
    client.close()


def test_step_up_flow_drift_is_rejected_before_binding() -> None:
    module = _module()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/authentication/required-actions"):
            return httpx.Response(
                200,
                json=[
                    {
                        "alias": "webauthn-register",
                        "enabled": True,
                        "defaultAction": False,
                    }
                ],
            )
        if request.url.path.endswith("/authentication/flows"):
            return httpx.Response(
                200,
                json=[
                    {
                        "alias": module.STEP_UP_FLOW_ALIAS,
                        "topLevel": True,
                        "builtIn": False,
                    }
                ],
            )
        if request.url.path.endswith(
            f"/authentication/flows/{module.STEP_UP_FLOW_ALIAS}/executions"
        ):
            return httpx.Response(200, json=[])
        return httpx.Response(500)

    client = httpx.Client(
        base_url="https://identity.example",
        transport=httpx.MockTransport(handler),
    )
    admin = module.KeycloakAdmin(client=client, realm="datariver")

    with pytest.raises(RuntimeError, match="Expected exactly one Keycloak execution"):
        admin.configure_step_up(client_id="web")
    client.close()
