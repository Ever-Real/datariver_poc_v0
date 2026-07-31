from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from datariver.application.errors import ExternalDependencyError
from datariver.application.identity_admin import (
    IdentityAdministration,
    IdentityUserDraft,
    IdentityUserProfile,
    IdentityUserProfileDraft,
    ProvisionedIdentity,
)
from datariver.domain.common import ConflictError


class KeycloakIdentityAdministration(IdentityAdministration):
    """A least-privilege Keycloak user adapter with no generic admin pass-through."""

    _MAXIMUM_RESPONSE_BYTES = 256 * 1024
    _MAXIMUM_TOKEN_LENGTH = 16 * 1024
    _MAXIMUM_EXTERNAL_SUBJECT_LENGTH = 255

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
        self._timeout_seconds = timeout_seconds
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(
                timeout_seconds,
                connect=min(timeout_seconds, 5.0),
                pool=min(timeout_seconds, 5.0),
            ),
            transport=transport,
            follow_redirects=False,
            trust_env=False,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
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
            external_subject = self._subject_from_location(location)
            if external_subject is None:
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

    async def get_user_profile(self, *, external_subject: str) -> IdentityUserProfile:
        response = await self._request(
            "GET",
            self._admin_path(f"users/{quote(external_subject, safe='')}"),
            expected={200},
        )
        try:
            value = response.json()
        except ValueError as error:
            raise self._dependency_error(
                "The authentication system returned an invalid user profile.",
                retryable=False,
            ) from error
        if not isinstance(value, dict) or self._user_id(value) != external_subject:
            raise self._dependency_error(
                "The authentication system returned an invalid user profile.",
                retryable=False,
            )
        return self._user_profile(value)

    async def update_user_profile(
        self,
        *,
        external_subject: str,
        draft: IdentityUserProfileDraft,
    ) -> IdentityUserProfile:
        current = await self.get_user_profile(external_subject=external_subject)
        if not current.enabled:
            raise ConflictError("The managed authentication identity is disabled.")
        await self._request(
            "PUT",
            self._admin_path(f"users/{quote(external_subject, safe='')}"),
            json={
                "email": draft.email,
                "emailVerified": (
                    current.email_verified if current.email == draft.email else False
                ),
                "firstName": draft.first_name,
                "lastName": draft.last_name,
            },
            expected={204},
        )
        return IdentityUserProfile(
            external_subject=external_subject,
            username=current.username,
            email=draft.email,
            first_name=draft.first_name,
            last_name=draft.last_name,
            enabled=current.enabled,
            email_verified=current.email_verified if current.email == draft.email else False,
            required_actions=current.required_actions,
        )

    async def reset_temporary_password(
        self,
        *,
        external_subject: str,
        temporary_password: str,
    ) -> None:
        current = await self.get_user_profile(external_subject=external_subject)
        if not current.enabled:
            raise ConflictError("The managed authentication identity is disabled.")
        encoded_subject = quote(external_subject, safe="")
        await self._request(
            "PUT",
            self._admin_path(f"users/{encoded_subject}/reset-password"),
            json={
                "type": "password",
                "value": temporary_password,
                "temporary": True,
            },
            expected={204},
        )
        await self._request(
            "POST",
            self._admin_path(f"users/{encoded_subject}/logout"),
            expected={204},
        )

    async def _exact_user(self, username: str) -> dict[str, Any] | None:
        response = await self._request(
            "GET",
            self._admin_path("users"),
            params={"username": username, "exact": "true", "max": "2"},
            expected={200},
        )
        try:
            value = response.json()
        except ValueError as error:
            raise self._dependency_error(
                "The authentication system returned an invalid user list.", retryable=False
            ) from error
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
            response = await self._send_bounded(
                method,
                path,
                headers={"Authorization": f"Bearer {token}"},
                **kwargs,
            )
        except (TimeoutError, httpx.HTTPError) as error:
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
            response = await self._send_bounded(
                "POST",
                f"/realms/{quote(self._realm, safe='')}/protocol/openid-connect/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
        except (TimeoutError, httpx.HTTPError) as error:
            raise self._dependency_error(
                "Identity-administration authentication is unavailable.", retryable=True
            ) from error
        if response.status_code != 200:
            raise self._dependency_error(
                "The authentication system rejected the administration credential.",
                retryable=response.status_code >= 500 or response.status_code in {408, 429},
                provider_code=str(response.status_code),
            )
        try:
            value = response.json()
        except ValueError as error:
            raise self._dependency_error(
                "The authentication system returned an invalid service token.", retryable=False
            ) from error
        token = value.get("access_token") if isinstance(value, dict) else None
        if not isinstance(token, str) or not token or len(token) > self._MAXIMUM_TOKEN_LENGTH:
            raise self._dependency_error(
                "The authentication system returned an invalid service token.", retryable=False
            )
        return token

    async def _send_bounded(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        request = self._client.build_request(method, path, **kwargs)
        response: httpx.Response | None = None
        try:
            async with asyncio.timeout(self._timeout_seconds):
                response = await self._client.send(request, stream=True)
                raw_length = response.headers.get("content-length")
                if raw_length is not None:
                    try:
                        content_length = int(raw_length)
                    except ValueError as error:
                        raise self._dependency_error(
                            "The authentication system returned an invalid response.",
                            retryable=False,
                        ) from error
                    if content_length > self._MAXIMUM_RESPONSE_BYTES:
                        raise self._dependency_error(
                            "The authentication system response exceeded its size limit.",
                            retryable=False,
                        )
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > self._MAXIMUM_RESPONSE_BYTES:
                        raise self._dependency_error(
                            "The authentication system response exceeded its size limit.",
                            retryable=False,
                        )
                return httpx.Response(
                    response.status_code,
                    headers=response.headers,
                    content=bytes(body),
                    request=request,
                )
        finally:
            if response is not None:
                await response.aclose()

    def _admin_path(self, suffix: str) -> str:
        return f"/admin/realms/{quote(self._realm, safe='')}/{suffix}"

    @staticmethod
    def _user_id(value: dict[str, Any]) -> str:
        external_subject = value.get("id")
        if (
            not isinstance(external_subject, str)
            or not external_subject
            or len(external_subject)
            > KeycloakIdentityAdministration._MAXIMUM_EXTERNAL_SUBJECT_LENGTH
        ):
            raise KeycloakIdentityAdministration._dependency_error(
                "The authentication system returned a user without an identity.", retryable=False
            )
        return external_subject

    @classmethod
    def _user_profile(cls, value: dict[str, Any]) -> IdentityUserProfile:
        external_subject = cls._user_id(value)
        username = value.get("username")
        email = value.get("email")
        first_name = value.get("firstName")
        last_name = value.get("lastName")
        enabled = value.get("enabled")
        email_verified = value.get("emailVerified", False)
        required_actions = value.get("requiredActions", [])
        if (
            not isinstance(username, str)
            or not username
            or not isinstance(email, str)
            or not email
            or not isinstance(first_name, str)
            or not isinstance(last_name, str)
            or not isinstance(enabled, bool)
            or not isinstance(email_verified, bool)
            or not isinstance(required_actions, list)
            or len(username) > 255
            or len(email) > 320
            or len(first_name) > 100
            or len(last_name) > 100
            or len(required_actions) > 32
            or any(
                not isinstance(item, str) or not item or len(item) > 100
                for item in required_actions
            )
        ):
            raise cls._dependency_error(
                "The authentication system returned an invalid user profile.",
                retryable=False,
            )
        return IdentityUserProfile(
            external_subject=external_subject,
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            enabled=enabled,
            email_verified=email_verified,
            required_actions=tuple(sorted(set(required_actions))),
        )

    def _subject_from_location(self, location: str) -> str | None:
        if not location:
            return None
        path = urlsplit(location).path.rstrip("/")
        expected_prefix = self._admin_path("users/")
        if not path.startswith(expected_prefix):
            return None
        external_subject = path.removeprefix(expected_prefix)
        if "/" in external_subject:
            return None
        if not external_subject or len(external_subject) > self._MAXIMUM_EXTERNAL_SUBJECT_LENGTH:
            return None
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
