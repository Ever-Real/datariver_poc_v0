from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from datariver.application.errors import ExternalDependencyError
from datariver.application.identity_admin import (
    IdentityAdministration,
    IdentityUserDraft,
    ProvisionedIdentity,
)
from datariver.domain.common import ConflictError


class KeycloakIdentityAdministration(IdentityAdministration):
    """A least-privilege Keycloak user adapter with no generic admin pass-through."""

    def __init__(
        self,
        *,
        base_url: str,
        realm: str,
        client_id: str,
        client_secret: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._realm = realm
        self._client_id = client_id
        self._client_secret = client_secret
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
            follow_redirects=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def ensure_disabled_user(self, draft: IdentityUserDraft) -> ProvisionedIdentity:
        existing = await self._exact_user(draft.username)
        created = False
        if existing is None:
            response = await self._request(
                "POST",
                self._admin_path("users"),
                json={
                    "username": draft.username,
                    "email": draft.email,
                    "firstName": draft.first_name,
                    "lastName": draft.last_name,
                    "emailVerified": False,
                    "enabled": False,
                    "requiredActions": ["UPDATE_PASSWORD"],
                    "attributes": {
                        "datariverWorkspace": [str(draft.workspace_id)],
                        "datariverProvisioningReference": [draft.provisioning_reference],
                    },
                },
                expected={201},
            )
            created = True
            location = response.headers.get("location", "")
            external_subject = location.rstrip("/").rsplit("/", 1)[-1]
            if not external_subject:
                existing = await self._exact_user(draft.username)
                if existing is None:
                    raise self._dependency_error(
                        "The authentication system did not return the created user identity.",
                        retryable=True,
                    )
                external_subject = self._user_id(existing)
        else:
            self._assert_managed_retry(existing, draft)
            external_subject = self._user_id(existing)
            if existing.get("enabled") is True:
                return ProvisionedIdentity(
                    external_subject=external_subject,
                    username=draft.username,
                    created=False,
                )

        await self._request(
            "PUT",
            self._admin_path(f"users/{quote(external_subject, safe='')}/reset-password"),
            json={
                "type": "password",
                "value": draft.temporary_password,
                "temporary": True,
            },
            expected={204},
        )
        return ProvisionedIdentity(
            external_subject=external_subject,
            username=draft.username,
            created=created,
        )

    async def enable_user(self, *, external_subject: str) -> None:
        await self._request(
            "PUT",
            self._admin_path(f"users/{quote(external_subject, safe='')}"),
            json={"enabled": True},
            expected={204},
        )

    async def _exact_user(self, username: str) -> dict[str, Any] | None:
        response = await self._request(
            "GET",
            self._admin_path("users"),
            params={"username": username, "exact": "true", "max": "2"},
            expected={200},
        )
        value = response.json()
        if not isinstance(value, list):
            raise self._dependency_error(
                "The authentication system returned an invalid user list.", retryable=False
            )
        matches = [
            item for item in value if isinstance(item, dict) and item.get("username") == username
        ]
        if len(matches) > 1:
            raise ConflictError("The authentication system returned duplicate usernames.")
        return matches[0] if matches else None

    def _assert_managed_retry(self, user: dict[str, Any], draft: IdentityUserDraft) -> None:
        attributes = user.get("attributes")
        if not isinstance(attributes, dict):
            raise ConflictError(
                "The identity username already exists outside DataRiver provisioning."
            )
        if attributes.get("datariverWorkspace") != [str(draft.workspace_id)] or attributes.get(
            "datariverProvisioningReference"
        ) != [draft.provisioning_reference]:
            raise ConflictError("The identity username belongs to another provisioning request.")
        expected = {
            "email": draft.email,
            "firstName": draft.first_name,
            "lastName": draft.last_name,
        }
        if any(user.get(key) != value for key, value in expected.items()):
            raise ConflictError("The retried identity profile differs from the original request.")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        expected: set[int],
        **kwargs: Any,
    ) -> httpx.Response:
        token = await self._access_token()
        try:
            response = await self._client.request(
                method,
                path,
                headers={"Authorization": f"Bearer {token}"},
                **kwargs,
            )
        except httpx.HTTPError as error:
            raise self._dependency_error(
                "Identity administration is temporarily unavailable.", retryable=True
            ) from error
        if response.status_code not in expected:
            retryable = response.status_code >= 500 or response.status_code in {408, 429}
            if response.status_code == 409:
                raise ConflictError("The requested authentication identity already exists.")
            raise self._dependency_error(
                "The authentication system rejected the governed identity operation.",
                retryable=retryable,
                provider_code=str(response.status_code),
            )
        return response

    async def _access_token(self) -> str:
        try:
            response = await self._client.post(
                f"/realms/{quote(self._realm, safe='')}/protocol/openid-connect/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
        except httpx.HTTPError as error:
            raise self._dependency_error(
                "Identity-administration authentication is unavailable.", retryable=True
            ) from error
        if response.status_code != 200:
            raise self._dependency_error(
                "The authentication system rejected the administration credential.",
                retryable=response.status_code >= 500,
                provider_code=str(response.status_code),
            )
        value = response.json()
        token = value.get("access_token") if isinstance(value, dict) else None
        if not isinstance(token, str) or not token:
            raise self._dependency_error(
                "The authentication system returned an invalid service token.", retryable=False
            )
        return token

    def _admin_path(self, suffix: str) -> str:
        return f"/admin/realms/{quote(self._realm, safe='')}/{suffix}"

    @staticmethod
    def _user_id(value: dict[str, Any]) -> str:
        external_subject = value.get("id")
        if not isinstance(external_subject, str) or not external_subject:
            raise KeycloakIdentityAdministration._dependency_error(
                "The authentication system returned a user without an identity.", retryable=False
            )
        return external_subject

    @staticmethod
    def _dependency_error(
        message: str, *, retryable: bool, provider_code: str | None = None
    ) -> ExternalDependencyError:
        return ExternalDependencyError(
            message,
            dependency="keycloak_identity_admin",
            retryable=retryable,
            provider_code=provider_code,
        )
