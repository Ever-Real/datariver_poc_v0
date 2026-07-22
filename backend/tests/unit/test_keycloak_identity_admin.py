from __future__ import annotations

import json
from urllib.parse import parse_qs
from uuid import UUID

import httpx
import pytest

from datariver.application.identity_admin import IdentityUserDraft
from datariver.domain.common import ConflictError
from datariver.infrastructure.identity.keycloak import KeycloakIdentityAdministration

WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000100")


def _draft() -> IdentityUserDraft:
    return IdentityUserDraft(
        username="hong.gildong",
        email="hong.gildong@example.internal",
        first_name="Gildong",
        last_name="Hong",
        temporary_password="approved-temporary-password",
        workspace_id=WORKSPACE_ID,
        provisioning_reference="a" * 64,
    )


@pytest.mark.asyncio
async def test_keycloak_adapter_creates_disabled_user_then_sets_temporary_password() -> None:
    calls: list[tuple[str, str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            json.loads(request.content)
            if request.content
            and request.headers.get("content-type", "").startswith("application/json")
            else None
        )
        calls.append((request.method, request.url.path, body))
        if request.url.path.endswith("/protocol/openid-connect/token"):
            assert parse_qs(request.content.decode()) == {
                "grant_type": ["client_credentials"],
                "client_id": ["datariver-identity-admin"],
                "client_secret": ["client-secret"],
            }
            return httpx.Response(200, request=request, json={"access_token": "service-token"})
        assert request.headers["Authorization"] == "Bearer service-token"
        if request.method == "GET":
            assert request.url.params["exact"] == "true"
            return httpx.Response(200, request=request, json=[])
        if request.method == "POST":
            assert body["enabled"] is False
            assert body["requiredActions"] == ["UPDATE_PASSWORD"]
            return httpx.Response(
                201,
                request=request,
                headers={"Location": "http://keycloak/admin/realms/datariver/users/user-123"},
            )
        assert request.url.path.endswith("/users/user-123/reset-password")
        assert body == {
            "type": "password",
            "value": "approved-temporary-password",
            "temporary": True,
        }
        return httpx.Response(204, request=request)

    adapter = KeycloakIdentityAdministration(
        base_url="http://keycloak:8080",
        realm="datariver",
        client_id="datariver-identity-admin",
        client_secret="client-secret",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )
    result = await adapter.ensure_disabled_user(_draft())
    await adapter.close()

    assert result.external_subject == "user-123"
    assert result.created is True
    assert sum(path.endswith("/token") for _, path, _ in calls) == 3


@pytest.mark.asyncio
async def test_enabled_managed_user_is_an_idempotent_retry_without_password_rotation() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/protocol/openid-connect/token"):
            return httpx.Response(200, request=request, json={"access_token": "service-token"})
        return httpx.Response(
            200,
            request=request,
            json=[
                {
                    "id": "user-123",
                    "username": "hong.gildong",
                    "email": "hong.gildong@example.internal",
                    "firstName": "Gildong",
                    "lastName": "Hong",
                    "enabled": True,
                    "attributes": {
                        "datariverWorkspace": [str(WORKSPACE_ID)],
                        "datariverProvisioningReference": ["a" * 64],
                    },
                }
            ],
        )

    adapter = KeycloakIdentityAdministration(
        base_url="http://keycloak:8080",
        realm="datariver",
        client_id="datariver-identity-admin",
        client_secret="client-secret",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )
    result = await adapter.ensure_disabled_user(_draft())
    await adapter.close()

    assert result.created is False
    assert not any(path.endswith("/reset-password") for path in paths)


@pytest.mark.asyncio
async def test_existing_unmanaged_username_is_rejected_without_password_change() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/protocol/openid-connect/token"):
            return httpx.Response(200, request=request, json={"access_token": "service-token"})
        return httpx.Response(
            200,
            request=request,
            json=[{"id": "outside", "username": "hong.gildong", "enabled": False}],
        )

    adapter = KeycloakIdentityAdministration(
        base_url="http://keycloak:8080",
        realm="datariver",
        client_id="datariver-identity-admin",
        client_secret="client-secret",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ConflictError, match="outside DataRiver"):
        await adapter.ensure_disabled_user(_draft())
    await adapter.close()
