from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

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

STEP_UP_FLOW_ALIAS = "datariver-browser-step-up-v1"
AUTH_FLOW_ALIAS = "datariver-authentication-v1"
LOA1_FLOW_ALIAS = "datariver-loa1-v1"
LOA2_FLOW_ALIAS = "datariver-loa2-v1"
LOA1_CONDITION_CONFIG_ALIAS = "datariver-loa1-condition-v1"
LOA2_CONDITION_CONFIG_ALIAS = "datariver-loa2-condition-v1"
PWD_REFERENCE_CONFIG_ALIAS = "datariver-password-reference-v1"  # noqa: S105
WEBAUTHN_REFERENCE_CONFIG_ALIAS = "datariver-webauthn-reference-v1"

WEBAUTHN_REALM_POLICY = {
    "webAuthnPolicyAuthenticatorAttachment": "cross-platform",
    "webAuthnPolicyResidentKey": "discouraged",
    "webAuthnPolicyUserVerificationRequirement": "required",
    "webAuthnPolicyAvoidSameAuthenticatorRegister": True,
}

AUTH_TIME_MAPPER_CONFIG = {
    "user.session.note": "AUTH_TIME",
    "id.token.claim": "true",
    "introspection.token.claim": "true",
    "access.token.claim": "true",
    "claim.name": "auth_time",
    "jsonType.label": "long",
}


def _safe_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme == "https" and parsed.hostname:
        return value.rstrip("/")
    if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        return value.rstrip("/")
    raise ValueError("Keycloak Admin API requires HTTPS, except for a loopback development URL.")


class _LoginFormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.action: str | None = None
        self.fields: dict[str, str] = {}
        self._in_login_form = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form" and attributes.get("id") == "kc-form-login":
            self._in_login_form = True
            self.action = attributes.get("action")
        elif self._in_login_form and tag == "input":
            name = attributes.get("name")
            if name:
                self.fields[name] = attributes.get("value") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self._in_login_form:
            self._in_login_form = False


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _same_origin(left: str, right: str) -> bool:
    left_url = urlsplit(left)
    right_url = urlsplit(right)
    return (left_url.scheme, left_url.hostname, left_url.port) == (
        right_url.scheme,
        right_url.hostname,
        right_url.port,
    )


def _jwt_payload(token: object) -> dict[str, Any]:
    if not isinstance(token, str):
        raise RuntimeError("Keycloak returned no access token to the browser-flow probe.")
    parts = token.split(".")
    if len(parts) != 3:
        raise RuntimeError("Keycloak returned a malformed access token.")
    encoded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(encoded).decode("utf-8"))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("Keycloak returned an unreadable access token.") from error
    if not isinstance(payload, dict):
        raise RuntimeError("Keycloak returned an invalid access-token payload.")
    return payload


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

    def create_probe_user(self, *, username: str, password: str) -> str:
        response = self._request(
            "POST",
            f"/admin/realms/{self._realm}/users",
            json={
                "username": username,
                "firstName": "DataRiver",
                "lastName": "Assurance Probe",
                "email": f"{username}@localhost.invalid",
                "enabled": True,
                "emailVerified": True,
                "credentials": [{"type": "password", "value": password, "temporary": False}],
            },
        )
        location = response.headers.get("Location")
        user_id = urlsplit(location).path.rsplit("/", 1)[-1] if location else ""
        if not user_id:
            raise RuntimeError("Keycloak did not return the probe-user identifier.")
        return user_id

    def delete_probe_user(self, user_id: str) -> None:
        self._request("DELETE", f"/admin/realms/{self._realm}/users/{user_id}")

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

    def _flows(self) -> list[dict[str, Any]]:
        flows = self._request("GET", f"/admin/realms/{self._realm}/authentication/flows").json()
        if not isinstance(flows, list) or not all(isinstance(item, dict) for item in flows):
            raise RuntimeError("The Keycloak authentication-flow contract is invalid.")
        return flows

    def _basic_client_scope(self) -> dict[str, Any]:
        scopes = self._request("GET", f"/admin/realms/{self._realm}/client-scopes").json()
        if not isinstance(scopes, list):
            raise RuntimeError("The Keycloak client-scope contract is invalid.")
        matches = [
            scope for scope in scopes if isinstance(scope, dict) and scope.get("name") == "basic"
        ]
        scope = self._exact(matches, kind="basic client scope")
        mappers = scope.get("protocolMappers")
        if not isinstance(mappers, list):
            raise RuntimeError("The Keycloak basic client scope has no protocol mappers.")
        auth_time_mappers = [
            mapper
            for mapper in mappers
            if isinstance(mapper, dict)
            and mapper.get("protocolMapper") == "oidc-usersessionmodel-note-mapper"
            and mapper.get("name") == "auth_time"
        ]
        mapper = self._exact(auth_time_mappers, kind="auth_time protocol mapper")
        if mapper.get("config") != AUTH_TIME_MAPPER_CONFIG:
            raise RuntimeError("The Keycloak auth_time protocol mapper has drifted.")
        return scope

    def _default_client_scopes(self, internal_client_id: str) -> list[dict[str, Any]]:
        scopes = self._request(
            "GET",
            f"/admin/realms/{self._realm}/clients/{internal_client_id}/default-client-scopes",
        ).json()
        if not isinstance(scopes, list) or not all(isinstance(scope, dict) for scope in scopes):
            raise RuntimeError("The Keycloak default-client-scope contract is invalid.")
        return scopes

    def _webauthn_registration_action(self) -> dict[str, Any]:
        actions = self._request(
            "GET", f"/admin/realms/{self._realm}/authentication/required-actions"
        ).json()
        if not isinstance(actions, list):
            raise RuntimeError("The Keycloak required-action contract is invalid.")
        matches = [
            action
            for action in actions
            if isinstance(action, dict) and action.get("alias") == "webauthn-register"
        ]
        return self._exact(matches, kind="WebAuthn registration required action")

    def _flow(self, alias: str) -> dict[str, Any] | None:
        matches = [flow for flow in self._flows() if flow.get("alias") == alias]
        if len(matches) > 1:
            raise RuntimeError(f"Keycloak has duplicate authentication flow {alias}.")
        return matches[0] if matches else None

    def _executions(self, flow_alias: str) -> list[dict[str, Any]]:
        executions = self._request(
            "GET",
            f"/admin/realms/{self._realm}/authentication/flows/{flow_alias}/executions",
        ).json()
        if not isinstance(executions, list) or not all(
            isinstance(item, dict) for item in executions
        ):
            raise RuntimeError("The Keycloak authentication-execution contract is invalid.")
        return executions

    @staticmethod
    def _one_execution(
        executions: list[dict[str, Any]],
        *,
        provider_id: str | None = None,
        display_name: str | None = None,
    ) -> dict[str, Any]:
        matches = [
            item
            for item in executions
            if (provider_id is None or item.get("providerId") == provider_id)
            and (display_name is None or item.get("displayName") == display_name)
        ]
        if len(matches) != 1:
            label = provider_id or display_name or "unknown"
            raise RuntimeError(f"Expected exactly one Keycloak execution {label}.")
        return matches[0]

    def _add_execution(self, *, flow_alias: str, provider_id: str) -> dict[str, Any]:
        self._request(
            "POST",
            f"/admin/realms/{self._realm}/authentication/flows/{flow_alias}/executions/execution",
            json={"provider": provider_id},
        )
        return self._one_execution(self._executions(flow_alias), provider_id=provider_id)

    def _add_subflow(self, *, parent_alias: str, alias: str) -> dict[str, Any]:
        self._request(
            "POST",
            f"/admin/realms/{self._realm}/authentication/flows/{parent_alias}/executions/flow",
            json={
                "alias": alias,
                "description": "DataRiver managed authentication assurance flow.",
                "type": "basic-flow",
            },
        )
        return self._one_execution(self._executions(parent_alias), display_name=alias)

    def _set_requirement(
        self, *, flow_alias: str, execution: dict[str, Any], requirement: str
    ) -> dict[str, Any]:
        updated = dict(execution)
        updated["requirement"] = requirement
        self._request(
            "PUT",
            f"/admin/realms/{self._realm}/authentication/flows/{flow_alias}/executions",
            json=updated,
        )
        execution_id = execution.get("id")
        matches = [item for item in self._executions(flow_alias) if item.get("id") == execution_id]
        return self._exact(matches, kind="updated execution")

    def _configure_execution(
        self, *, execution: dict[str, Any], alias: str, config: dict[str, str]
    ) -> None:
        execution_id = execution.get("id")
        if not isinstance(execution_id, str) or not execution_id:
            raise RuntimeError("The Keycloak execution has no stable identifier.")
        self._request(
            "POST",
            f"/admin/realms/{self._realm}/authentication/executions/{execution_id}/config",
            json={"alias": alias, "config": config},
        )

    def _execution_config(self, execution: dict[str, Any]) -> dict[str, Any]:
        config_id = execution.get("authenticationConfig")
        if not isinstance(config_id, str) or not config_id:
            raise RuntimeError("The Keycloak execution has no authenticator configuration.")
        config = self._request(
            "GET",
            f"/admin/realms/{self._realm}/authentication/config/{config_id}",
        ).json()
        if not isinstance(config, dict):
            raise RuntimeError("The Keycloak authenticator configuration is invalid.")
        return config

    @staticmethod
    def _verify_config(config: dict[str, Any], *, alias: str, expected: dict[str, str]) -> None:
        if config.get("alias") != alias or config.get("config") != expected:
            raise RuntimeError(f"Keycloak authenticator configuration {alias} has drifted.")

    def _create_step_up_flow(self) -> None:
        self._request(
            "POST",
            f"/admin/realms/{self._realm}/authentication/flows",
            json={
                "alias": STEP_UP_FLOW_ALIAS,
                "description": "DataRiver password login with hardware WebAuthn step-up.",
                "providerId": "basic-flow",
                "topLevel": True,
                "builtIn": False,
            },
        )
        cookie = self._add_execution(flow_alias=STEP_UP_FLOW_ALIAS, provider_id="auth-cookie")
        self._set_requirement(
            flow_alias=STEP_UP_FLOW_ALIAS,
            execution=cookie,
            requirement="ALTERNATIVE",
        )
        auth_flow = self._add_subflow(parent_alias=STEP_UP_FLOW_ALIAS, alias=AUTH_FLOW_ALIAS)
        self._set_requirement(
            flow_alias=STEP_UP_FLOW_ALIAS,
            execution=auth_flow,
            requirement="ALTERNATIVE",
        )

        loa1_flow = self._add_subflow(parent_alias=AUTH_FLOW_ALIAS, alias=LOA1_FLOW_ALIAS)
        self._set_requirement(
            flow_alias=AUTH_FLOW_ALIAS,
            execution=loa1_flow,
            requirement="CONDITIONAL",
        )
        loa1_condition = self._add_execution(
            flow_alias=LOA1_FLOW_ALIAS,
            provider_id="conditional-level-of-authentication",
        )
        loa1_condition = self._set_requirement(
            flow_alias=LOA1_FLOW_ALIAS,
            execution=loa1_condition,
            requirement="REQUIRED",
        )
        self._configure_execution(
            execution=loa1_condition,
            alias=LOA1_CONDITION_CONFIG_ALIAS,
            config={"loa-condition-level": "1", "loa-max-age": "36000"},
        )
        password = self._add_execution(
            flow_alias=LOA1_FLOW_ALIAS, provider_id="auth-username-password-form"
        )
        password = self._set_requirement(
            flow_alias=LOA1_FLOW_ALIAS,
            execution=password,
            requirement="REQUIRED",
        )
        self._configure_execution(
            execution=password,
            alias=PWD_REFERENCE_CONFIG_ALIAS,
            config={"default.reference.value": "pwd", "default.reference.maxAge": "0"},
        )

        loa2_flow = self._add_subflow(parent_alias=AUTH_FLOW_ALIAS, alias=LOA2_FLOW_ALIAS)
        self._set_requirement(
            flow_alias=AUTH_FLOW_ALIAS,
            execution=loa2_flow,
            requirement="CONDITIONAL",
        )
        loa2_condition = self._add_execution(
            flow_alias=LOA2_FLOW_ALIAS,
            provider_id="conditional-level-of-authentication",
        )
        loa2_condition = self._set_requirement(
            flow_alias=LOA2_FLOW_ALIAS,
            execution=loa2_condition,
            requirement="REQUIRED",
        )
        self._configure_execution(
            execution=loa2_condition,
            alias=LOA2_CONDITION_CONFIG_ALIAS,
            config={"loa-condition-level": "2", "loa-max-age": "0"},
        )
        webauthn = self._add_execution(
            flow_alias=LOA2_FLOW_ALIAS, provider_id="webauthn-authenticator"
        )
        webauthn = self._set_requirement(
            flow_alias=LOA2_FLOW_ALIAS,
            execution=webauthn,
            requirement="REQUIRED",
        )
        self._configure_execution(
            execution=webauthn,
            alias=WEBAUTHN_REFERENCE_CONFIG_ALIAS,
            config={
                "default.reference.value": "webauthn",
                "default.reference.maxAge": "0",
            },
        )

    def _verify_step_up_flow(self) -> None:
        flow = self._flow(STEP_UP_FLOW_ALIAS)
        if flow is None or flow.get("builtIn") is not False or flow.get("topLevel") is not True:
            raise RuntimeError("The managed Keycloak step-up flow is missing or invalid.")
        top = self._executions(STEP_UP_FLOW_ALIAS)
        cookie = self._one_execution(top, provider_id="auth-cookie")
        auth_flow = self._one_execution(top, display_name=AUTH_FLOW_ALIAS)
        if (
            cookie.get("requirement") != "ALTERNATIVE"
            or auth_flow.get("requirement") != "ALTERNATIVE"
        ):
            raise RuntimeError("The Keycloak step-up top-level requirements have drifted.")

        auth = self._executions(AUTH_FLOW_ALIAS)
        loa1_flow = self._one_execution(auth, display_name=LOA1_FLOW_ALIAS)
        loa2_flow = self._one_execution(auth, display_name=LOA2_FLOW_ALIAS)
        if (
            loa1_flow.get("requirement") != "CONDITIONAL"
            or loa2_flow.get("requirement") != "CONDITIONAL"
        ):
            raise RuntimeError("The Keycloak LoA flow requirements have drifted.")

        loa1 = self._executions(LOA1_FLOW_ALIAS)
        loa1_condition = self._one_execution(
            loa1, provider_id="conditional-level-of-authentication"
        )
        password = self._one_execution(loa1, provider_id="auth-username-password-form")
        loa2 = self._executions(LOA2_FLOW_ALIAS)
        loa2_condition = self._one_execution(
            loa2, provider_id="conditional-level-of-authentication"
        )
        webauthn = self._one_execution(loa2, provider_id="webauthn-authenticator")
        if any(
            item.get("requirement") != "REQUIRED"
            for item in (loa1_condition, password, loa2_condition, webauthn)
        ):
            raise RuntimeError("A Keycloak LoA execution is not required.")
        self._verify_config(
            self._execution_config(loa1_condition),
            alias=LOA1_CONDITION_CONFIG_ALIAS,
            expected={"loa-condition-level": "1", "loa-max-age": "36000"},
        )
        self._verify_config(
            self._execution_config(password),
            alias=PWD_REFERENCE_CONFIG_ALIAS,
            expected={"default.reference.value": "pwd", "default.reference.maxAge": "0"},
        )
        self._verify_config(
            self._execution_config(loa2_condition),
            alias=LOA2_CONDITION_CONFIG_ALIAS,
            expected={"loa-condition-level": "2", "loa-max-age": "0"},
        )
        self._verify_config(
            self._execution_config(webauthn),
            alias=WEBAUTHN_REFERENCE_CONFIG_ALIAS,
            expected={
                "default.reference.value": "webauthn",
                "default.reference.maxAge": "0",
            },
        )

    def configure_step_up(self, *, client_id: str) -> tuple[str, ...]:
        changes: list[str] = []
        registration_action = self._webauthn_registration_action()
        if (
            registration_action.get("enabled") is not True
            or registration_action.get("defaultAction") is not False
        ):
            registration_action["enabled"] = True
            registration_action["defaultAction"] = False
            self._request(
                "PUT",
                f"/admin/realms/{self._realm}/authentication/required-actions/webauthn-register",
                json=registration_action,
            )
            changes.append("enabled-explicit-webauthn-registration")
        if self._flow(STEP_UP_FLOW_ALIAS) is None:
            self._create_step_up_flow()
            changes.append("created-step-up-flow")
        self._verify_step_up_flow()

        realm_path = f"/admin/realms/{self._realm}"
        realm = self._request("GET", realm_path).json()
        if not isinstance(realm, dict):
            raise RuntimeError("The Keycloak realm representation is invalid.")
        realm_changed = False
        for key, expected in WEBAUTHN_REALM_POLICY.items():
            if realm.get(key) != expected:
                realm[key] = expected
                realm_changed = True
        if realm.get("browserFlow") != STEP_UP_FLOW_ALIAS:
            realm["browserFlow"] = STEP_UP_FLOW_ALIAS
            realm_changed = True
        if realm_changed:
            self._request("PUT", realm_path, json=realm)
            changes.append("bound-step-up-flow")

        client = self.client(client_id)
        internal_client_id = client.get("id")
        if not isinstance(internal_client_id, str) or not internal_client_id:
            raise RuntimeError("The Keycloak client has no stable identifier.")
        attributes = client.get("attributes", {})
        if not isinstance(attributes, dict):
            raise RuntimeError("The Keycloak client attributes are invalid.")
        if attributes.get("default.acr.values") != "1":
            client["attributes"] = {**attributes, "default.acr.values": "1"}
            self._request(
                "PUT",
                f"/admin/realms/{self._realm}/clients/{internal_client_id}",
                json=client,
            )
            changes.append("set-default-acr")
        basic_scope = self._basic_client_scope()
        basic_scope_id = basic_scope.get("id")
        if not isinstance(basic_scope_id, str) or not basic_scope_id:
            raise RuntimeError("The Keycloak basic client scope has no stable identifier.")
        default_scopes = self._default_client_scopes(internal_client_id)
        if not any(scope.get("id") == basic_scope_id for scope in default_scopes):
            self._request(
                "PUT",
                f"/admin/realms/{self._realm}/clients/{internal_client_id}"
                f"/default-client-scopes/{basic_scope_id}",
            )
            changes.append("attached-auth-time-scope")
        return tuple(changes)

    def verify_step_up(self, *, client_id: str) -> None:
        self._verify_step_up_flow()
        registration_action = self._webauthn_registration_action()
        if (
            registration_action.get("enabled") is not True
            or registration_action.get("defaultAction") is not False
        ):
            raise RuntimeError(
                "WebAuthn registration must be enabled but never a default required action."
            )
        realm = self._request("GET", f"/admin/realms/{self._realm}").json()
        if not isinstance(realm, dict) or realm.get("browserFlow") != STEP_UP_FLOW_ALIAS:
            raise RuntimeError("The Keycloak step-up flow is not bound as the browser flow.")
        if any(realm.get(key) != expected for key, expected in WEBAUTHN_REALM_POLICY.items()):
            raise RuntimeError("The Keycloak WebAuthn policy has drifted.")
        client = self.client(client_id)
        attributes = client.get("attributes", {})
        if not isinstance(attributes, dict) or attributes.get("default.acr.values") != "1":
            raise RuntimeError("The Keycloak web client does not default to LoA 1.")
        internal_client_id = client.get("id")
        if not isinstance(internal_client_id, str) or not internal_client_id:
            raise RuntimeError("The Keycloak client has no stable identifier.")
        basic_scope = self._basic_client_scope()
        if not any(
            scope.get("id") == basic_scope.get("id")
            for scope in self._default_client_scopes(internal_client_id)
        ):
            raise RuntimeError("The Keycloak web client does not emit auth_time.")

    def probe_browser_step_up(
        self,
        *,
        base_url: str,
        client_id: str,
        redirect_uri: str,
        timeout_seconds: float,
    ) -> dict[str, str]:
        safe_base_url = _safe_base_url(base_url)
        parsed_redirect = urlsplit(redirect_uri)
        if parsed_redirect.scheme not in {"http", "https"} or not parsed_redirect.hostname:
            raise ValueError("The probe redirect URI must be an absolute HTTP(S) URL.")
        username = f"datariver-assurance-probe-{secrets.token_hex(8)}"
        password = secrets.token_urlsafe(48)
        user_id = self.create_probe_user(username=username, password=password)
        try:
            loa1 = self._probe_browser_login(
                base_url=safe_base_url,
                client_id=client_id,
                redirect_uri=redirect_uri,
                username=username,
                password=password,
                requested_acr="1",
                timeout_seconds=timeout_seconds,
            )
            loa2 = self._probe_browser_login(
                base_url=safe_base_url,
                client_id=client_id,
                redirect_uri=redirect_uri,
                username=username,
                password=password,
                requested_acr="2",
                timeout_seconds=timeout_seconds,
            )
            return {"loa1": loa1, "loa2": loa2, "cleanup": "probe-user-removed"}
        finally:
            self.delete_probe_user(user_id)

    def _probe_browser_login(
        self,
        *,
        base_url: str,
        client_id: str,
        redirect_uri: str,
        username: str,
        password: str,
        requested_acr: str,
        timeout_seconds: float,
    ) -> str:
        verifier, challenge = _pkce_pair()
        expected_state = secrets.token_urlsafe(24)
        with httpx.Client(
            base_url=base_url,
            timeout=timeout_seconds,
            follow_redirects=False,
        ) as browser:
            response = browser.get(
                f"/realms/{self._realm}/protocol/openid-connect/auth",
                params={
                    "client_id": client_id,
                    "redirect_uri": redirect_uri,
                    "response_type": "code",
                    "response_mode": "query",
                    "scope": "openid",
                    "state": expected_state,
                    "nonce": secrets.token_urlsafe(24),
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                    "acr_values": requested_acr,
                    "max_age": "0",
                    "prompt": "login",
                },
            )
            response.raise_for_status()
            parser = _LoginFormParser()
            parser.feed(response.text)
            if not parser.action:
                raise RuntimeError("Keycloak did not render the expected password login form.")
            action = urljoin(base_url, parser.action)
            if not _same_origin(base_url, action):
                raise RuntimeError("Keycloak returned a cross-origin login form action.")
            if urlsplit(base_url).scheme == "http":
                # Browsers treat loopback as a secure context, while httpx correctly follows the
                # generic Secure-cookie rule. The probe's only permitted HTTP target is loopback.
                for cookie in browser.cookies.jar:
                    cookie.secure = False
            form = {
                **parser.fields,
                "username": username,
                "password": password,
                "credentialId": "",
            }
            response = browser.post(action, data=form)
            for _ in range(5):
                if not response.is_redirect:
                    break
                location = response.headers.get("Location", "")
                if _same_origin(location, redirect_uri):
                    query = parse_qs(urlsplit(location).query)
                    if (
                        requested_acr == "1"
                        and query.get("state") == [expected_state]
                        and query.get("code")
                    ):
                        token_response = browser.post(
                            f"/realms/{self._realm}/protocol/openid-connect/token",
                            data={
                                "client_id": client_id,
                                "grant_type": "authorization_code",
                                "code": query["code"][0],
                                "redirect_uri": redirect_uri,
                                "code_verifier": verifier,
                            },
                        )
                        token_response.raise_for_status()
                        claims = _jwt_payload(token_response.json().get("access_token"))
                        amr = claims.get("amr")
                        auth_time = claims.get("auth_time")
                        missing_claims: list[str] = []
                        if claims.get("acr") != "1":
                            missing_claims.append("acr=1")
                        if not isinstance(amr, list) or "pwd" not in amr:
                            missing_claims.append("amr=pwd")
                        if not isinstance(auth_time, int):
                            missing_claims.append("auth_time")
                        if missing_claims:
                            raise RuntimeError(
                                "Keycloak LoA 1 token lacks: " + ", ".join(missing_claims)
                            )
                        return "verified-pwd-token-issued"
                    raise RuntimeError("Keycloak returned an unexpected client redirect.")
                if not _same_origin(base_url, location):
                    raise RuntimeError("Keycloak returned a cross-origin authentication redirect.")
                response = browser.get(location)
                if urlsplit(base_url).scheme == "http":
                    for cookie in browser.cookies.jar:
                        cookie.secure = False
            if response.is_redirect:
                raise RuntimeError("Keycloak authentication exceeded the redirect limit.")
            response.raise_for_status()
            if requested_acr == "2" and "webauthn" in response.text.lower():
                return "webauthn-required"
            raise RuntimeError("Keycloak did not enforce the requested assurance level.")

    def configure_foundation(
        self,
        *,
        username: str,
        client_id: str,
        revoke_user_sessions: bool = False,
        configure_step_up: bool = False,
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
        if configure_step_up:
            changes.extend(self.configure_step_up(client_id=client_id))
        return tuple(changes)

    def verify_foundation(
        self, *, username: str, client_id: str, verify_step_up: bool = False
    ) -> None:
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
        if verify_step_up:
            self.verify_step_up(client_id=client_id)


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
        "--configure-step-up",
        action="store_true",
        help="Create, verify and bind the managed password plus hardware-WebAuthn LoA flow.",
    )
    parser.add_argument(
        "--revoke-user-sessions",
        action="store_true",
        help="Log the managed user out after applying the foundation.",
    )
    parser.add_argument(
        "--probe-browser-flow",
        action="store_true",
        help=(
            "Create a temporary user, prove LoA 1 login and LoA 2 WebAuthn enforcement, "
            "then remove it."
        ),
    )
    parser.add_argument("--probe-redirect-uri", default="http://localhost:5173/")
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
                    configure_step_up=args.configure_step_up,
                )
                if args.apply
                else ()
            )
            admin.verify_foundation(
                username=args.username,
                client_id=args.client_id,
                verify_step_up=args.configure_step_up,
            )
            probe = (
                admin.probe_browser_step_up(
                    base_url=args.base_url,
                    client_id=args.client_id,
                    redirect_uri=args.probe_redirect_uri,
                    timeout_seconds=args.timeout_seconds,
                )
                if args.probe_browser_flow
                else None
            )
        finally:
            admin.close()
    except (OSError, ValueError, RuntimeError, httpx.HTTPError) as error:
        print(f"Keycloak assurance foundation failed: {error}", file=sys.stderr)
        return 1
    result: dict[str, object] = {"status": "verified", "changes": changes}
    if probe is not None:
        result["probe"] = probe
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
