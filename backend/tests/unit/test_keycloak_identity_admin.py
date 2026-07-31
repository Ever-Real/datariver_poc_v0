from __future__ import annotations

import json
from urllib.parse import parse_qs
from uuid import UUID

import httpx
import pytest

from datariver.application.errors import ExternalDependencyError
from datariver.application.identity_admin import IdentityUserDraft, IdentityUserProfileDraft
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
            assert isinstance(body, dict)
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


@pytest.mark.asyncio
async def test_created_user_location_cannot_supply_an_unbounded_external_subject() -> None:
    exact_lookups = 0
    reset_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal exact_lookups
        if request.url.path.endswith("/protocol/openid-connect/token"):
            return httpx.Response(200, request=request, json={"access_token": "service-token"})
        if request.method == "GET":
            exact_lookups += 1
            return httpx.Response(200, request=request, json=[])
        if request.method == "POST":
            return httpx.Response(
                201,
                request=request,
                headers={"Location": ("http://keycloak/admin/realms/datariver/users/" + "x" * 256)},
            )
        reset_paths.append(request.url.path)
        return httpx.Response(204, request=request)

    adapter = KeycloakIdentityAdministration(
        base_url="http://keycloak:8080",
        realm="datariver",
        client_id="datariver-identity-admin",
        client_secret="client-secret",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ExternalDependencyError, match="created user identity"):
        await adapter.ensure_disabled_user(_draft())
    await adapter.close()

    assert exact_lookups == 2
    assert reset_paths == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("token_response", "expected_retryable"),
    [
        (httpx.Response(200, content=b"{" + b"x" * 262_145 + b"}"), False),
        (httpx.Response(200, content=b"{invalid-json"), False),
        (httpx.Response(429), True),
    ],
)
async def test_keycloak_token_response_is_bounded_typed_and_retryable(
    token_response: httpx.Response,
    expected_retryable: bool,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            token_response.status_code,
            request=request,
            content=token_response.content,
        )

    adapter = KeycloakIdentityAdministration(
        base_url="http://keycloak:8080",
        realm="datariver",
        client_id="datariver-identity-admin",
        client_secret="client-secret",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ExternalDependencyError) as captured:
        await adapter.ensure_disabled_user(_draft())
    await adapter.close()

    assert captured.value.details["retryable"] is expected_retryable


@pytest.mark.asyncio
async def test_keycloak_adapter_reads_one_typed_profile_by_exact_subject() -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path.endswith("/protocol/openid-connect/token"):
            return httpx.Response(200, request=request, json={"access_token": "service-token"})
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "user-123",
                "username": "hong.gildong",
                "email": "hong.gildong@example.internal",
                "firstName": "Gildong",
                "lastName": "Hong",
                "enabled": True,
                "requiredActions": ["UPDATE_PASSWORD", "UPDATE_PASSWORD"],
            },
        )

    adapter = KeycloakIdentityAdministration(
        base_url="http://keycloak:8080",
        realm="datariver",
        client_id="datariver-identity-admin",
        client_secret="client-secret",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )
    result = await adapter.get_user_profile(external_subject="user-123")
    await adapter.close()

    assert result.username == "hong.gildong"
    assert result.required_actions == ("UPDATE_PASSWORD",)
    assert requested_paths[-1] == "/admin/realms/datariver/users/user-123"


@pytest.mark.asyncio
async def test_keycloak_adapter_updates_only_bounded_profile_fields() -> None:
    updates: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/protocol/openid-connect/token"):
            return httpx.Response(200, request=request, json={"access_token": "service-token"})
        if request.method == "GET":
            return httpx.Response(
                200,
                request=request,
                json={
                    "id": "user-123",
                    "username": "hong.gildong",
                    "email": "old@example.internal",
                    "firstName": "Old",
                    "lastName": "Name",
                    "enabled": True,
                    "requiredActions": [],
                },
            )
        updates.append(json.loads(request.content))
        return httpx.Response(204, request=request)

    adapter = KeycloakIdentityAdministration(
        base_url="http://keycloak:8080",
        realm="datariver",
        client_id="datariver-identity-admin",
        client_secret="client-secret",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )
    result = await adapter.update_user_profile(
        external_subject="user-123",
        draft=IdentityUserProfileDraft(
            email="new@example.internal",
            first_name="New",
            last_name="Name",
        ),
    )
    await adapter.close()

    assert result.display_name == "New Name"
    assert updates == [
        {
            "email": "new@example.internal",
            "emailVerified": False,
            "firstName": "New",
            "lastName": "Name",
        }
    ]


@pytest.mark.asyncio
async def test_keycloak_temporary_password_reset_revokes_sessions_without_readback() -> None:
    operations: list[tuple[str, str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/protocol/openid-connect/token"):
            return httpx.Response(200, request=request, json={"access_token": "service-token"})
        if request.method == "GET":
            operations.append((request.method, request.url.path, None))
            return httpx.Response(
                200,
                request=request,
                json={
                    "id": "user-123",
                    "username": "hong.gildong",
                    "email": "hong.gildong@example.internal",
                    "firstName": "Gildong",
                    "lastName": "Hong",
                    "enabled": True,
                    "emailVerified": True,
                    "requiredActions": [],
                },
            )
        body = json.loads(request.content) if request.content else None
        operations.append((request.method, request.url.path, body))
        return httpx.Response(204, request=request)

    adapter = KeycloakIdentityAdministration(
        base_url="http://keycloak:8080",
        realm="datariver",
        client_id="datariver-identity-admin",
        client_secret="client-secret",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )
    await adapter.reset_temporary_password(
        external_subject="user-123",
        temporary_password="temporary-password-42!",
    )
    await adapter.close()

    assert operations == [
        ("GET", "/admin/realms/datariver/users/user-123", None),
        (
            "PUT",
            "/admin/realms/datariver/users/user-123/reset-password",
            {
                "type": "password",
                "value": "temporary-password-42!",
                "temporary": True,
            },
        ),
        ("POST", "/admin/realms/datariver/users/user-123/logout", None),
    ]


@pytest.mark.asyncio
async def test_disabled_keycloak_identity_rejects_credential_mutation() -> None:
    mutation_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/protocol/openid-connect/token"):
            return httpx.Response(200, request=request, json={"access_token": "service-token"})
        if request.method != "GET":
            mutation_paths.append(request.url.path)
            return httpx.Response(204, request=request)
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "user-123",
                "username": "hong.gildong",
                "email": "hong.gildong@example.internal",
                "firstName": "Gildong",
                "lastName": "Hong",
                "enabled": False,
                "emailVerified": True,
                "requiredActions": [],
            },
        )

    adapter = KeycloakIdentityAdministration(
        base_url="http://keycloak:8080",
        realm="datariver",
        client_id="datariver-identity-admin",
        client_secret="client-secret",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ConflictError, match="disabled"):
        await adapter.reset_temporary_password(
            external_subject="user-123",
            temporary_password="temporary-password-42!",
        )
    await adapter.close()

    assert mutation_paths == []
