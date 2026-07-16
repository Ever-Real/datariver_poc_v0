from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

AMR_MAPPER = {
    "name": "authentication-method-reference",
    "protocol": "openid-connect",
    "protocolMapper": "oidc-amr-mapper",
    "consentRequired": False,
    "config": {
        "id.token.claim": "true",
        "access.token.claim": "true",
        "lightweight.claim": "false",
    },
}


def _safe_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme == "https" and parsed.hostname:
        return value.rstrip("/")
    if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        return value.rstrip("/")
    raise ValueError("Keycloak Admin API requires HTTPS, except for a loopback development URL.")


class KeycloakAdmin:
    def __init__(self, *, client: httpx.Client, realm: str) -> None:
        self._client = client
        self._realm = realm

    @classmethod
    def login(
        cls,
        *,
        base_url: str,
        admin_realm: str,
        realm: str,
        admin_username: str,
        admin_password_file: Path,
        timeout_seconds: float,
    ) -> KeycloakAdmin:
        password = admin_password_file.read_text(encoding="utf-8").strip()
        if not password:
            raise ValueError("The Keycloak admin password file is empty.")
        client = httpx.Client(
            base_url=_safe_base_url(base_url),
            timeout=timeout_seconds,
            follow_redirects=False,
        )
        response = client.post(
            f"/realms/{admin_realm}/protocol/openid-connect/token",
            data={
                "client_id": "admin-cli",
                "grant_type": "password",
                "username": admin_username,
                "password": password,
            },
        )
        try:
            response.raise_for_status()
            token = response.json()["access_token"]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            client.close()
            raise RuntimeError("Keycloak admin authentication failed.") from error
        if not isinstance(token, str) or not token:
            client.close()
            raise RuntimeError("Keycloak admin authentication returned no access token.")
        client.headers["Authorization"] = f"Bearer {token}"
        return cls(client=client, realm=realm)

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = self._client.request(method, path, **kwargs)
        try:
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise RuntimeError(
                f"Keycloak Admin API operation failed with status {response.status_code}."
            ) from error
        return response

    @staticmethod
    def _exact(items: object, *, kind: str) -> dict[str, Any]:
        if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
            raise RuntimeError(f"Expected exactly one Keycloak {kind}.")
        return items[0]

    def user(self, username: str) -> dict[str, Any]:
        response = self._request(
            "GET",
            f"/admin/realms/{self._realm}/users",
            params={"username": username, "exact": "true"},
        )
        return self._exact(response.json(), kind="user")

    def client(self, client_id: str) -> dict[str, Any]:
        response = self._request(
            "GET",
            f"/admin/realms/{self._realm}/clients",
            params={"clientId": client_id},
        )
        return self._exact(response.json(), kind="client")

    def configure_foundation(
        self, *, username: str, client_id: str, revoke_user_sessions: bool = False
    ) -> tuple[str, ...]:
        changes: list[str] = []
        user = self.user(username)
        user_id = user.get("id")
        if not isinstance(user_id, str) or not user_id:
            raise RuntimeError("The Keycloak user has no stable identifier.")
        actions = user.get("requiredActions", [])
        if not isinstance(actions, list) or not all(isinstance(item, str) for item in actions):
            raise RuntimeError("The Keycloak user required-action contract is invalid.")
        filtered_actions = [item for item in actions if item != "CONFIGURE_TOTP"]
        if filtered_actions != actions:
            user["requiredActions"] = filtered_actions
            self._request(
                "PUT",
                f"/admin/realms/{self._realm}/users/{user_id}",
                json=user,
            )
            changes.append("removed-mobile-totp")

        client = self.client(client_id)
        internal_client_id = client.get("id")
        if not isinstance(internal_client_id, str) or not internal_client_id:
            raise RuntimeError("The Keycloak client has no stable identifier.")
        mapper_path = (
            f"/admin/realms/{self._realm}/clients/{internal_client_id}/protocol-mappers/models"
        )
        mappers = self._request("GET", mapper_path).json()
        if not isinstance(mappers, list):
            raise RuntimeError("The Keycloak protocol-mapper contract is invalid.")
        if not any(
            isinstance(mapper, dict) and mapper.get("protocolMapper") == "oidc-amr-mapper"
            for mapper in mappers
        ):
            self._request("POST", mapper_path, json=AMR_MAPPER)
            changes.append("added-amr-mapper")
        if revoke_user_sessions:
            self._request(
                "POST",
                f"/admin/realms/{self._realm}/users/{user_id}/logout",
            )
            changes.append("revoked-user-sessions")
        return tuple(changes)

    def verify_foundation(self, *, username: str, client_id: str) -> None:
        actions = self.user(username).get("requiredActions", [])
        if not isinstance(actions, list) or "CONFIGURE_TOTP" in actions:
            raise RuntimeError("Mobile TOTP remains a required action.")
        client = self.client(client_id)
        internal_client_id = client.get("id")
        if not isinstance(internal_client_id, str) or not internal_client_id:
            raise RuntimeError("The Keycloak client has no stable identifier.")
        mappers = self._request(
            "GET",
            f"/admin/realms/{self._realm}/clients/{internal_client_id}/protocol-mappers/models",
        ).json()
        if not isinstance(mappers, list) or not any(
            isinstance(mapper, dict) and mapper.get("protocolMapper") == "oidc-amr-mapper"
            for mapper in mappers
        ):
            raise RuntimeError("The Keycloak web client has no AMR mapper.")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply or verify the fail-closed Keycloak assurance foundation."
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--admin-realm", default="master")
    parser.add_argument("--realm", default="datariver")
    parser.add_argument("--admin-username", required=True)
    parser.add_argument("--admin-password-file", type=Path, required=True)
    parser.add_argument("--username", required=True, help="Managed human administrator username")
    parser.add_argument("--client-id", default="datariver-web")
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--revoke-user-sessions",
        action="store_true",
        help="Log the managed user out after applying the foundation.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        admin = KeycloakAdmin.login(
            base_url=args.base_url,
            admin_realm=args.admin_realm,
            realm=args.realm,
            admin_username=args.admin_username,
            admin_password_file=args.admin_password_file,
            timeout_seconds=args.timeout_seconds,
        )
        try:
            changes = (
                admin.configure_foundation(
                    username=args.username,
                    client_id=args.client_id,
                    revoke_user_sessions=args.revoke_user_sessions,
                )
                if args.apply
                else ()
            )
            admin.verify_foundation(username=args.username, client_id=args.client_id)
        finally:
            admin.close()
    except (OSError, ValueError, RuntimeError, httpx.HTTPError) as error:
        print(f"Keycloak assurance foundation failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "verified", "changes": changes}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
