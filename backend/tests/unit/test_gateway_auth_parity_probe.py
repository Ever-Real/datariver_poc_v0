from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "scripts" / "probe_gateway_auth_parity.py"
CLASSIFIER_MODULE_PATH = ROOT / "scripts" / "classify_gateway_production_invariant.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("probe_gateway_auth_parity", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    scripts_path = str(ROOT / "scripts")
    sys.path.insert(0, scripts_path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(scripts_path)
    return module


probe = _load_module()


def _load_classifier_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "classify_gateway_production_invariant",
        CLASSIFIER_MODULE_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    scripts_path = str(ROOT / "scripts")
    sys.path.insert(0, scripts_path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(scripts_path)
    return module


@dataclass(frozen=True)
class Token:
    value: str
    expires_at: int


class RecordingFixture:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def require_absent(self) -> None:
        self.events.append("db-absent")

    def prepare(self, allow_subject: str, deny_subject: str) -> None:
        assert allow_subject != deny_subject
        self.events.append("db-prepare")

    def enable(self, allow_subject: str, deny_subject: str) -> None:
        assert allow_subject != deny_subject
        self.events.append("db-enable")

    def revoke_allow_membership(self, allow_subject: str, deny_subject: str) -> None:
        assert allow_subject != deny_subject
        self.events.append("db-revoke")

    def cleanup(self, allow_subject: str, deny_subject: str) -> None:
        assert allow_subject != deny_subject
        self.events.append("db-cleanup")

    def require_zero_residual(self) -> None:
        self.events.append("db-zero")


class RecordingIdentity:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self._created = False
        self._allow_issuance_count = 0

    def require_absent_and_capture_invariants(self) -> None:
        self.events.append("identity-absent")

    def create_disabled_fixture(self) -> tuple[str, str]:
        self.events.append("identity-create-disabled")
        self._created = True
        return (
            "10000000-0000-4000-8000-000000000001",
            "10000000-0000-4000-8000-000000000002",
        )

    def enable_fixture(self) -> None:
        assert self._created
        self.events.append("identity-enable")

    def authenticate_allow(self) -> Token:
        self.events.append("pkce-allow")
        self._allow_issuance_count += 1
        return Token(
            "allow-token-secret-sentinel",
            110 if self._allow_issuance_count == 1 else 140,
        )

    def authenticate_deny(self) -> Token:
        self.events.append("pkce-deny")
        return Token("deny-token-secret-sentinel", 110)

    def cleanup_sessions_and_users(self) -> None:
        self.events.append("identity-sessions-users-cleanup")

    def cleanup_client(self) -> None:
        self.events.append("identity-client-cleanup")

    def require_invariants_and_zero_residual(self) -> None:
        self.events.append("identity-zero")

    def release_without_mutation(self) -> None:
        self.events.append("identity-release")


class RecordingTraffic:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.now = 100
        self.sentinels: set[str] = set()

    def verify_status_matrix(self, scenario: str, token: str, expected_status: int) -> None:
        assert token
        self.sentinels.add(token)
        self.events.append(f"traffic-{scenario}-{expected_status}")

    def verify_cors_and_headers(self, token: str) -> None:
        assert token
        self.events.append("traffic-headers-cors")

    def wait_until_expired(self, expires_at: int) -> None:
        assert expires_at > self.now
        self.now = expires_at + 1
        self.events.append("genuine-expiry-wait")

    def require_not_expired(self, expires_at: int) -> None:
        assert expires_at > self.now
        self.events.append("token-still-valid")

    def assert_logs_clean(self, sentinels: tuple[str, ...]) -> None:
        assert all(isinstance(sentinel, str) for sentinel in sentinels)
        self.events.append("logs-clean")


def _session(events: list[str]) -> Any:
    return probe.GatewayAuthParitySession(
        identity=RecordingIdentity(events),
        fixture=RecordingFixture(events),
        traffic=RecordingTraffic(events),
    )


def test_pkce_client_contract_disables_direct_grants_service_accounts_and_implicit_flow() -> None:
    document = probe.pkce_client_document()

    assert document["publicClient"] is True
    assert document["clientAuthenticatorType"] == "client-secret"
    assert document["standardFlowEnabled"] is True
    assert document["directAccessGrantsEnabled"] is False
    assert document["serviceAccountsEnabled"] is False
    assert document["implicitFlowEnabled"] is False
    assert document["bearerOnly"] is False
    assert document["surrogateAuthRequired"] is False
    assert document["authorizationServicesEnabled"] is False
    assert document["fullScopeAllowed"] is False
    assert document["authenticationFlowBindingOverrides"] == {}
    assert document["attributes"]["pkce.code.challenge.method"] == "S256"
    assert document["attributes"]["access.token.lifespan"] == str(
        probe.ACCESS_TOKEN_LIFESPAN_SECONDS
    )
    assert document["redirectUris"] == [probe.PKCE_REDIRECT_URI]
    assert document["webOrigins"] == [probe.PKCE_REDIRECT_ORIGIN]
    assert all("secret" not in key.casefold() for key in document)


def test_keycloak_fixture_create_order_is_client_mapper_then_two_disabled_humans(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    identity = probe.KeycloakGatewayAuthParityIdentity(
        base_url="http://127.0.0.1:8081",
        admin_username="datariver-bootstrap",
        admin_password="admin-secret-sentinel",
    )
    client_id = "10000000-0000-4000-8000-000000000070"
    user_ids = {
        probe.ALLOW_USERNAME: "10000000-0000-4000-8000-000000000071",
        probe.DENY_USERNAME: "10000000-0000-4000-8000-000000000072",
    }
    requests: list[tuple[str, str, object]] = []

    def request(method: str, path: str, **kwargs: object) -> httpx.Response:
        document = kwargs.get("json")
        requests.append((method, path, document))
        location = ""
        if path.endswith("/clients"):
            location = f"http://127.0.0.1/admin/realms/datariver/clients/{client_id}"
        elif path.endswith("/users"):
            assert isinstance(document, dict)
            location = (
                "http://127.0.0.1/admin/realms/datariver/users/"
                + user_ids[cast(str, document["username"])]
            )
        return httpx.Response(
            201,
            headers={"Location": location},
            request=httpx.Request(method, "http://127.0.0.1" + path),
        )

    monkeypatch.setattr(identity, "_request", request)
    monkeypatch.setattr(identity, "_validated_client_uuid", lambda **_kwargs: client_id)
    monkeypatch.setattr(
        identity,
        "_validated_user_uuid",
        lambda _username, subject, **_kwargs: subject,
    )

    assert identity.create_disabled_fixture() == tuple(user_ids.values())

    assert [path.rsplit("/", 1)[-1] for _method, path, _document in requests] == [
        "clients",
        "models",
        "users",
        "users",
    ]
    user_documents = [
        cast(dict[str, object], document)
        for _, path, document in requests
        if path.endswith("/users")
    ]
    assert all(document["enabled"] is False for document in user_documents)
    passwords: list[str] = [
        cast(
            str,
            cast(list[dict[str, object]], document["credentials"])[0]["value"],
        )
        for document in user_documents
    ]
    assert all(len(password) >= 48 for password in passwords)
    assert len(set(passwords)) == 2
    operator = capsys.readouterr()
    exposed = operator.out + operator.err
    assert all(password not in exposed for password in passwords)
    identity.release_without_mutation()


def test_genuine_expiry_requires_the_exact_backend_verifier_leeway_boundary() -> None:
    assert probe.OIDC_VERIFIER_LEEWAY_SECONDS == 30
    assert probe._genuine_expiry_reached(expires_at=100, observed_at=130) is False
    assert probe._genuine_expiry_reached(expires_at=100, observed_at=131) is True


def test_expiry_wait_is_bounded_to_token_ttl_plus_verifier_leeway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = {"now": 100}
    sleeps: list[int] = []
    traffic = probe.GatewayAuthParityTraffic(
        direct_url="http://127.0.0.1:8000",
        gateway_url="http://127.0.0.1:9080",
        web_url="http://127.0.0.1:8080",
        origin="http://127.0.0.1:8080",
        log_checker=lambda _started_at, _sentinels: None,
    )
    monkeypatch.setattr(probe.time, "time", lambda: observed["now"])

    def sleep(delay: int) -> None:
        sleeps.append(delay)
        observed["now"] += delay

    monkeypatch.setattr(probe.time, "sleep", sleep)

    traffic.wait_until_expired(110)

    assert sleeps == [41]
    assert observed["now"] == 141


def _jwt_for_test(
    *,
    issued_at: int,
    expires_at: int,
    audience: object = ("datariver-api",),
) -> str:
    def encode(document: dict[str, object]) -> str:
        raw = json.dumps(document, separators=(",", ":")).encode("utf-8")
        return cast(
            str,
            probe.base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii"),
        )

    return (
        f"{encode({'alg': 'none'})}."
        f"{encode({'iat': issued_at, 'exp': expires_at, 'aud': audience})}.signature"
    )


def test_pkce_token_requires_the_fixed_api_audience() -> None:
    with pytest.raises(
        probe.GatewayAuthParityError,
        match="GATEWAY_AUTH_PARITY_TOKEN_INVALID",
    ):
        probe._jwt_expiry(_jwt_for_test(issued_at=100, expires_at=130, audience=("account",)))


def test_loopback_secure_cookie_is_sent_on_login_post_without_value_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original_client = cast(type[httpx.Client], probe.httpx.Client)
    login_cookie_present: list[bool] = []
    expected_state = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal expected_state
        if request.method == "GET" and request.url.path.endswith("/auth"):
            expected_state = request.url.params["state"]
            return httpx.Response(
                200,
                headers={"Set-Cookie": "KC_RESTART=cookie-secret-sentinel; Secure; Path=/"},
                text='<form id="kc-form-login" action="http://127.0.0.1:8081/login"></form>',
            )
        if request.method == "POST" and request.url.path == "/login":
            login_cookie_present.append("KC_RESTART=" in request.headers.get("cookie", ""))
            return httpx.Response(
                302,
                headers={
                    "Location": (
                        "http://127.0.0.1:38109/callback?state="
                        f"{expected_state}&code=code-secret-sentinel"
                    )
                },
            )
        if request.method == "POST" and request.url.path.endswith("/token"):
            now = int(probe.time.time())
            return httpx.Response(
                200,
                json={
                    "access_token": _jwt_for_test(
                        issued_at=now,
                        expires_at=now + probe.ACCESS_TOKEN_LIFESPAN_SECONDS,
                    )
                },
            )
        raise AssertionError("unexpected fixed PKCE request")

    def client(**kwargs: Any) -> httpx.Client:
        return original_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(probe.httpx, "Client", client)
    identity = probe.KeycloakGatewayAuthParityIdentity(
        base_url="http://127.0.0.1:8081",
        admin_username="datariver-bootstrap",
        admin_password="admin-secret-sentinel",
    )
    cast(Any, identity)._allow_password = "password-secret-sentinel"

    token = identity.authenticate_allow()

    assert token.value
    assert login_cookie_present == [True]
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "cookie-secret-sentinel" not in combined
    assert "password-secret-sentinel" not in combined
    cast(Any, identity)._client.close()


@pytest.mark.parametrize(
    "failure",
    (
        "cross-origin-form",
        "callback-path",
        "callback-credentials",
        "state",
        "duplicate-code",
    ),
)
def test_pkce_rejects_unreviewed_redirect_state_or_code_without_raw_output(
    failure: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original_client = cast(type[httpx.Client], probe.httpx.Client)
    expected_state = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal expected_state
        if request.method == "GET" and request.url.path.endswith("/auth"):
            expected_state = request.url.params["state"]
            action = (
                "https://unreviewed.example.invalid/login"
                if failure == "cross-origin-form"
                else "http://127.0.0.1:8081/login"
            )
            return httpx.Response(200, text=f'<form id="kc-form-login" action="{action}"></form>')
        if request.method == "POST" and request.url.path == "/login":
            state = "state-provider-secret-sentinel" if failure == "state" else expected_state
            code = (
                "code=first-provider-secret-sentinel&code=second-provider-secret-sentinel"
                if failure == "duplicate-code"
                else "code=code-provider-secret-sentinel"
            )
            callback = probe.PKCE_REDIRECT_URI
            if failure == "callback-path":
                callback = "http://127.0.0.1:38109/unreviewed-callback"
            elif failure == "callback-credentials":
                callback = "http://user:pass@127.0.0.1:38109/callback"
            return httpx.Response(
                302,
                headers={"Location": f"{callback}?state={state}&{code}"},
            )
        raise AssertionError("unexpected PKCE request after fixed negative boundary")

    def client(**kwargs: Any) -> httpx.Client:
        return original_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(probe.httpx, "Client", client)
    identity = probe.KeycloakGatewayAuthParityIdentity(
        base_url="http://127.0.0.1:8081",
        admin_username="datariver-bootstrap",
        admin_password="admin-secret-sentinel",
    )
    cast(Any, identity)._allow_password = "password-secret-sentinel"

    with pytest.raises(
        probe.GatewayAuthParityError,
        match="GATEWAY_AUTH_PARITY_PKCE_FAILED",
    ) as captured:
        identity.authenticate_allow()

    operator = capsys.readouterr()
    exposed = operator.out + operator.err + str(captured.value)
    for forbidden in ("provider-secret", "password-secret", "unreviewed.example"):
        assert forbidden not in exposed
    cast(Any, identity)._client.close()


@pytest.mark.parametrize(
    "token",
    (
        _jwt_for_test(issued_at=100, expires_at=133),
        _jwt_for_test(issued_at=100, expires_at=100),
        _jwt_for_test(issued_at=True, expires_at=130),
    ),
)
def test_pkce_token_rejects_unbounded_or_nonpositive_lifetime(token: str) -> None:
    with pytest.raises(
        probe.GatewayAuthParityError,
        match="GATEWAY_AUTH_PARITY_TOKEN_INVALID",
    ):
        probe._jwt_expiry(token)


def test_cleanup_rediscovers_only_exact_task_resources_after_ambiguous_create_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = probe.KeycloakGatewayAuthParityIdentity(
        base_url="http://127.0.0.1:8081",
        admin_username="datariver-bootstrap",
        admin_password="admin-secret-sentinel",
    )
    client_id = "10000000-0000-4000-8000-000000000010"
    allow_id = "10000000-0000-4000-8000-000000000011"
    deny_id = "10000000-0000-4000-8000-000000000012"
    client_document = {**probe.pkce_client_document(), "id": client_id}
    mapper_document = {**probe.audience_mapper_document(), "id": "mapper-private-id"}
    user_documents = {
        probe.ALLOW_USERNAME: {
            "id": allow_id,
            "username": probe.ALLOW_USERNAME,
            "enabled": True,
            "firstName": "DataRiver",
            "lastName": "Gateway Parity",
            "email": f"{probe.ALLOW_USERNAME}@localhost.invalid",
            "emailVerified": True,
            "requiredActions": [],
            "attributes": {"datariverFixture": [probe.FIXTURE_CONTRACT]},
        },
        probe.DENY_USERNAME: {
            "id": deny_id,
            "username": probe.DENY_USERNAME,
            "enabled": True,
            "firstName": "DataRiver",
            "lastName": "Gateway Parity",
            "email": f"{probe.DENY_USERNAME}@localhost.invalid",
            "emailVerified": True,
            "requiredActions": [],
            "attributes": {"datariverFixture": [probe.FIXTURE_CONTRACT]},
        },
    }
    requested: list[tuple[str, str]] = []

    def find(kind: str, _key: str, value: str) -> list[dict[str, object]]:
        if kind == "clients":
            return [{"clientId": probe.FIXTURE_CLIENT_ID, "id": client_id}]
        document = user_documents[value]
        return [{"username": value, "id": document["id"]}]

    def document(path: str) -> dict[str, object]:
        if "/clients/" in path:
            return client_document
        for value in user_documents.values():
            if path.endswith(cast(str, value["id"])):
                return value
        raise AssertionError("unexpected fixed fixture document")

    def request(method: str, path: str, **_kwargs: object) -> httpx.Response:
        requested.append((method, path))
        return httpx.Response(204, request=httpx.Request(method, "http://127.0.0.1" + path))

    monkeypatch.setattr(identity, "_find", find)
    monkeypatch.setattr(identity, "_get_admin_document", document)
    monkeypatch.setattr(identity, "_get_admin_list", lambda _path: [mapper_document])
    monkeypatch.setattr(identity, "_request", request)

    identity.cleanup_sessions_and_users()
    identity.cleanup_client()

    assert requested == [
        ("POST", f"/admin/realms/datariver/users/{allow_id}/logout"),
        ("DELETE", f"/admin/realms/datariver/users/{allow_id}"),
        ("POST", f"/admin/realms/datariver/users/{deny_id}/logout"),
        ("DELETE", f"/admin/realms/datariver/users/{deny_id}"),
        ("DELETE", f"/admin/realms/datariver/clients/{client_id}"),
    ]
    cast(Any, identity)._client.close()


def test_cleanup_accepts_exact_client_before_optional_audience_mapper_was_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = probe.KeycloakGatewayAuthParityIdentity(
        base_url="http://127.0.0.1:8081",
        admin_username="datariver-bootstrap",
        admin_password="admin-secret-sentinel",
    )
    client_id = "10000000-0000-4000-8000-000000000030"
    requested: list[str] = []
    monkeypatch.setattr(
        identity,
        "_find",
        lambda _kind, _key, _value: [{"clientId": probe.FIXTURE_CLIENT_ID, "id": client_id}],
    )
    monkeypatch.setattr(
        identity,
        "_get_admin_document",
        lambda _path: {**probe.pkce_client_document(), "id": client_id},
    )
    monkeypatch.setattr(identity, "_get_admin_list", lambda _path: [])
    monkeypatch.setattr(
        identity,
        "_request",
        lambda _method, path, **_kwargs: requested.append(path),
    )

    identity.cleanup_client()

    assert requested == [f"/admin/realms/datariver/clients/{client_id}"]
    cast(Any, identity)._client.close()


@pytest.mark.parametrize(
    "drift",
    (
        "name",
        "default-scopes",
        "direct-grants",
        "service-accounts",
        "client-authenticator",
        "bearer-only",
        "implicit-flow",
        "authorization-services",
        "full-scope",
        "flow-binding",
        "optional-scopes",
        "extra-attribute",
        "mapper",
        "multiple-mappers",
        "uuid",
        "ambiguous",
    ),
)
def test_cleanup_rejects_client_auth_surface_mapper_scope_or_identity_drift(
    drift: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = probe.KeycloakGatewayAuthParityIdentity(
        base_url="http://127.0.0.1:8081",
        admin_username="datariver-bootstrap",
        admin_password="admin-secret-sentinel",
    )
    client_id = "10000000-0000-4000-8000-000000000040"
    client_document = {**probe.pkce_client_document(), "id": client_id}
    mapper_document = {**probe.audience_mapper_document(), "id": "mapper-private-id"}
    if drift == "name":
        client_document["name"] = "not-the-task-client"
    elif drift == "default-scopes":
        client_document["defaultClientScopes"] = ["roles", "offline_access"]
    elif drift == "direct-grants":
        client_document["directAccessGrantsEnabled"] = True
    elif drift == "service-accounts":
        client_document["serviceAccountsEnabled"] = True
    elif drift == "client-authenticator":
        client_document["clientAuthenticatorType"] = "client-secret-jwt"
    elif drift == "bearer-only":
        client_document["bearerOnly"] = True
    elif drift == "implicit-flow":
        client_document["implicitFlowEnabled"] = True
    elif drift == "authorization-services":
        client_document["authorizationServicesEnabled"] = True
    elif drift == "full-scope":
        client_document["fullScopeAllowed"] = True
    elif drift == "flow-binding":
        client_document["authenticationFlowBindingOverrides"] = {"browser": "unreviewed-flow"}
    elif drift == "optional-scopes":
        client_document["optionalClientScopes"] = ["offline_access"]
    elif drift == "extra-attribute":
        cast(dict[str, str], client_document["attributes"])[
            "oauth2.device.authorization.grant.enabled"
        ] = "true"
    elif drift == "mapper":
        mapper_document["protocolMapper"] = "oidc-hardcoded-claim-mapper"
    elif drift == "uuid":
        cast(Any, identity)._client_uuid = "10000000-0000-4000-8000-000000000041"

    matches = [{"clientId": probe.FIXTURE_CLIENT_ID, "id": client_id}]
    if drift == "ambiguous":
        matches = [*matches, {"clientId": probe.FIXTURE_CLIENT_ID, "id": client_id}]
    requested: list[str] = []
    monkeypatch.setattr(identity, "_find", lambda _kind, _key, _value: matches)
    monkeypatch.setattr(identity, "_get_admin_document", lambda _path: client_document)
    mapper_documents = [mapper_document]
    if drift == "multiple-mappers":
        mapper_documents.append(dict(mapper_document))
    monkeypatch.setattr(identity, "_get_admin_list", lambda _path: mapper_documents)
    monkeypatch.setattr(
        identity,
        "_request",
        lambda _method, path, **_kwargs: requested.append(path),
    )

    with pytest.raises(
        probe.GatewayAuthParityError,
        match="GATEWAY_AUTH_PARITY_CLEANUP_REQUIRED",
    ):
        identity.cleanup_client()

    assert requested == []
    cast(Any, identity)._client.close()


def test_cleanup_refreshes_the_admin_token_only_at_the_cleanup_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = probe.KeycloakGatewayAuthParityIdentity(
        base_url="http://127.0.0.1:8081",
        admin_username="datariver-bootstrap",
        admin_password="admin-secret-sentinel",
    )
    cast(Any, identity)._admin_token = "stale-admin-token-secret-sentinel"
    observed_tokens: list[str | None] = []

    def find(_kind: str, _key: str, _value: str) -> list[dict[str, object]]:
        observed_tokens.append(cast(Any, identity)._admin_token)
        return []

    monkeypatch.setattr(identity, "_find", find)

    identity.cleanup_sessions_and_users()

    assert observed_tokens == [None, None]
    cast(Any, identity)._client.close()


@pytest.mark.parametrize(
    "drift",
    ("marker", "email", "uuid", "service-account", "federation"),
)
def test_cleanup_rejects_user_identity_or_auth_surface_drift_without_deleting(
    drift: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = probe.KeycloakGatewayAuthParityIdentity(
        base_url="http://127.0.0.1:8081",
        admin_username="datariver-bootstrap",
        admin_password="admin-secret-sentinel",
    )
    user_id = "10000000-0000-4000-8000-000000000050"
    document: dict[str, object] = {
        "id": user_id,
        "username": probe.ALLOW_USERNAME,
        "enabled": True,
        "firstName": "DataRiver",
        "lastName": "Gateway Parity",
        "email": f"{probe.ALLOW_USERNAME}@localhost.invalid",
        "emailVerified": True,
        "requiredActions": [],
        "attributes": {"datariverFixture": [probe.FIXTURE_CONTRACT]},
    }
    if drift == "marker":
        document["attributes"] = {"datariverFixture": ["unreviewed-fixture"]}
    elif drift == "email":
        document["email"] = "real-user@example.invalid"
    elif drift == "service-account":
        document["serviceAccountClientId"] = "real-client"
    elif drift == "federation":
        document["federationLink"] = "provider-private-id"
    recorded = "10000000-0000-4000-8000-000000000051" if drift == "uuid" else user_id
    cast(Any, identity)._allow_subject = recorded
    requested: list[str] = []
    monkeypatch.setattr(
        identity,
        "_find",
        lambda kind, _key, value: (
            [{"username": value, "id": user_id}]
            if kind == "users" and value == probe.ALLOW_USERNAME
            else []
        ),
    )
    monkeypatch.setattr(identity, "_get_admin_document", lambda _path: document)
    monkeypatch.setattr(
        identity,
        "_request",
        lambda _method, path, **_kwargs: requested.append(path),
    )

    with pytest.raises(
        probe.GatewayAuthParityError,
        match="GATEWAY_AUTH_PARITY_CLEANUP_REQUIRED",
    ):
        identity.cleanup_sessions_and_users()

    assert requested == []
    cast(Any, identity)._client.close()


@pytest.mark.parametrize("kind", ("client", "user"))
def test_cleanup_rejects_recorded_uuid_that_was_renamed_instead_of_treating_it_absent(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = probe.KeycloakGatewayAuthParityIdentity(
        base_url="http://127.0.0.1:8081",
        admin_username="datariver-bootstrap",
        admin_password="admin-secret-sentinel",
    )
    recorded_id = "10000000-0000-4000-8000-000000000060"
    cast(Any, identity)._client_uuid = recorded_id if kind == "client" else None
    cast(Any, identity)._allow_subject = recorded_id if kind == "user" else None
    monkeypatch.setattr(identity, "_find", lambda _kind, _key, _value: [])
    monkeypatch.setattr(
        identity,
        "_get_admin_document_optional",
        lambda _path: {"id": recorded_id, "clientId": "renamed-private-fixture"},
    )
    requested: list[str] = []
    monkeypatch.setattr(
        identity,
        "_request",
        lambda _method, path, **_kwargs: requested.append(path),
    )

    with pytest.raises(
        probe.GatewayAuthParityError,
        match="GATEWAY_AUTH_PARITY_CLEANUP_REQUIRED",
    ):
        if kind == "client":
            identity.cleanup_client()
        else:
            identity.cleanup_sessions_and_users()

    assert requested == []
    cast(Any, identity)._client.close()


def _production_web_contract() -> tuple[dict[str, object], list[dict[str, object]]]:
    client_uuid = "10000000-0000-4000-8000-000000000080"
    return (
        {
            "id": client_uuid,
            "clientId": "datariver-web",
            "name": "DataRiver Web",
            "protocol": "openid-connect",
            "clientAuthenticatorType": "client-secret",
            "enabled": True,
            "publicClient": True,
            "bearerOnly": False,
            "surrogateAuthRequired": False,
            "consentRequired": False,
            "standardFlowEnabled": True,
            "directAccessGrantsEnabled": False,
            "implicitFlowEnabled": False,
            "serviceAccountsEnabled": False,
            "authorizationServicesEnabled": False,
            "fullScopeAllowed": False,
            "frontchannelLogout": False,
            "alwaysDisplayInConsole": False,
            "notBefore": 0,
            "rootUrl": None,
            "baseUrl": None,
            "adminUrl": None,
            "redirectUris": ["http://127.0.0.1:8080/callback"],
            "webOrigins": ["http://127.0.0.1:8080"],
            "defaultClientScopes": ["acr", "basic", "email", "profile", "roles"],
            "optionalClientScopes": [],
            "authenticationFlowBindingOverrides": {},
            "attributes": {
                "pkce.code.challenge.method": "S256",
                "post.logout.redirect.uris": "+",
            },
        },
        [
            {
                "id": "10000000-0000-4000-8000-000000000081",
                "name": "datariver-api-audience",
                "protocol": "openid-connect",
                "protocolMapper": "oidc-audience-mapper",
                "consentRequired": False,
                "config": {
                    "included.client.audience": "datariver-api",
                    "access.token.claim": "true",
                },
            }
        ],
    )


def _install_production_web_contract(
    identity: object,
    monkeypatch: pytest.MonkeyPatch,
    client: dict[str, object],
    mappers: list[dict[str, object]],
    *,
    search: object | None = None,
) -> None:
    search_document = (
        [{"id": client["id"], "clientId": "datariver-web"}] if search is None else search
    )
    monkeypatch.setattr(identity, "_find", lambda _kind, _key, _value: [])
    monkeypatch.setattr(
        identity,
        "classify_production_web_invariant",
        lambda: probe._classify_production_web_contract(
            client_search=lambda: _production_response(search_document),
            client_document=lambda _uuid: _production_response(client),
            mapper_inventory=lambda _uuid: _production_response(mappers),
        ),
    )


def test_production_web_fingerprint_reads_exact_client_and_mapper_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = probe.KeycloakGatewayAuthParityIdentity(
        base_url="http://127.0.0.1:8081",
        admin_username="datariver-bootstrap",
        admin_password="admin-secret-sentinel",
    )
    web_document, mapper_documents = _production_web_contract()
    client_uuid = cast(str, web_document["id"])
    requested: list[tuple[str, str]] = []

    def request(method: str, path: str, **_kwargs: object) -> httpx.Response:
        requested.append((method, path))
        if path == "/admin/realms/datariver/clients":
            document: object = [{"id": client_uuid, "clientId": "datariver-web"}]
        elif path.endswith("/protocol-mappers/models"):
            document = mapper_documents
        else:
            document = web_document
        return httpx.Response(200, json=document)

    monkeypatch.setattr(identity, "_request", request)

    fingerprint = cast(Any, identity)._production_contract_fingerprint()

    assert fingerprint == "ffc69db96bb50a2712ca81c5d38ba56d59ba9d17781fa368039c9a849c94b6d5"
    assert requested == [
        ("GET", "/admin/realms/datariver/clients"),
        ("GET", f"/admin/realms/datariver/clients/{client_uuid}"),
        (
            "GET",
            f"/admin/realms/datariver/clients/{client_uuid}/protocol-mappers/models",
        ),
    ]
    identity.release_without_mutation()


@pytest.mark.parametrize(
    "drift",
    (
        "missing-protocol",
        "uuid",
        "auth-flag",
        "redirect-extra",
        "scope-extra",
        "scope-duplicate",
        "attribute-extra",
        "mapper-missing",
        "mapper-extra",
        "mapper-drift",
        "mapper-duplicate",
    ),
)
def test_cleanup_detects_full_production_web_auth_surface_drift_without_raw_output(
    drift: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    identity = probe.KeycloakGatewayAuthParityIdentity(
        base_url="http://127.0.0.1:8081",
        admin_username="datariver-bootstrap",
        admin_password="admin-secret-sentinel",
    )
    web_document, mapper_documents = _production_web_contract()
    _install_production_web_contract(identity, monkeypatch, web_document, mapper_documents)
    identity.require_absent_and_capture_invariants()
    if drift == "missing-protocol":
        del web_document["protocol"]
    elif drift == "uuid":
        web_document["id"] = "10000000-0000-4000-8000-000000000099"
    elif drift == "auth-flag":
        web_document["fullScopeAllowed"] = True
    elif drift == "redirect-extra":
        cast(list[str], web_document["redirectUris"]).append(
            "http://provider-path-secret.invalid/callback"
        )
    elif drift == "scope-extra":
        cast(list[str], web_document["optionalClientScopes"]).append("offline_access")
    elif drift == "scope-duplicate":
        cast(list[str], web_document["defaultClientScopes"]).append("roles")
    elif drift == "attribute-extra":
        cast(dict[str, str], web_document["attributes"])["provider-secret-key"] = "private"
    elif drift == "mapper-missing":
        mapper_documents.clear()
    elif drift == "mapper-extra":
        extra = dict(mapper_documents[0])
        extra["id"] = "10000000-0000-4000-8000-000000000082"
        extra["name"] = "provider-private-extra"
        mapper_documents.append(extra)
    elif drift == "mapper-drift":
        cast(dict[str, str], mapper_documents[0]["config"])["access.token.claim"] = "false"
    else:
        mapper_documents.append(dict(mapper_documents[0]))

    with pytest.raises(
        probe.GatewayAuthParityError,
        match="GATEWAY_AUTH_PARITY_CLEANUP_REQUIRED",
    ) as captured:
        identity.require_invariants_and_zero_residual()

    operator = capsys.readouterr()
    exposed = operator.out + operator.err + str(captured.value)
    for forbidden in ("provider-path-secret", "provider-secret-key", "provider-private-extra"):
        assert forbidden not in exposed
    assert cast(Any, identity)._admin_password == ""
    assert cast(Any, identity)._admin_token is None


@pytest.mark.parametrize(
    "invalid",
    (
        "missing",
        "duplicate-client",
        "duplicate-scope",
        "duplicate-mapper",
        "mapper-uuid",
        "mapper-overflow",
    ),
)
def test_production_web_invariant_rejects_incomplete_or_duplicate_baseline_before_fixture(
    invalid: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = probe.KeycloakGatewayAuthParityIdentity(
        base_url="http://127.0.0.1:8081",
        admin_username="datariver-bootstrap",
        admin_password="admin-secret-sentinel",
    )
    web_document, mapper_documents = _production_web_contract()
    if invalid == "missing":
        del web_document["protocol"]
    elif invalid == "duplicate-client":
        _install_production_web_contract(
            identity,
            monkeypatch,
            web_document,
            mapper_documents,
            search=[
                {"id": web_document["id"], "clientId": "datariver-web"},
                {
                    "id": "10000000-0000-4000-8000-000000000099",
                    "clientId": "datariver-web",
                },
            ],
        )
    elif invalid == "duplicate-scope":
        cast(list[str], web_document["defaultClientScopes"]).append("roles")
    elif invalid == "duplicate-mapper":
        mapper_documents.append(dict(mapper_documents[0]))
    elif invalid == "mapper-uuid":
        mapper_documents[0]["id"] = "not-a-uuid"
    else:
        mapper_documents.extend(
            {
                **mapper_documents[0],
                "id": f"10000000-0000-4000-8000-{index:012d}",
                "name": f"bounded-mapper-{index}",
            }
            for index in range(2, probe._MAXIMUM_PRODUCTION_MAPPERS + 2)
        )
    if invalid != "duplicate-client":
        _install_production_web_contract(identity, monkeypatch, web_document, mapper_documents)

    with pytest.raises(
        probe.GatewayAuthParityError,
        match="GATEWAY_AUTH_PARITY_PRODUCTION_INVARIANT_FAILED",
    ):
        identity.require_absent_and_capture_invariants()

    identity.release_without_mutation()


def _production_invariant_case(
    case: str,
) -> tuple[
    object,
    dict[str, object],
    object,
    type[BaseException] | None,
]:
    client, mapper_documents = _production_web_contract()
    mapper_inventory: object = mapper_documents
    search: object = [{"id": client["id"], "clientId": "datariver-web"}]
    raised: type[BaseException] | None = None
    if case == "CLIENT_SEARCH_SHAPE":
        search = {"provider-raw-secret": "sentinel"}
    elif case == "CLIENT_MATCH_COUNT":
        search = []
    elif case == "CLIENT_UUID":
        search = [{"id": "provider-uuid-secret", "clientId": "datariver-web"}]
    elif case == "CLIENT_DOCUMENT_IDENTITY":
        client["id"] = "10000000-0000-4000-8000-000000000099"
    elif case == "CLIENT_STRING_SHAPE":
        client["name"] = ""
    elif case == "CLIENT_BOOLEAN_SHAPE":
        client["enabled"] = "provider-boolean-secret"
    elif case == "CLIENT_OPTIONAL_URL_SHAPE":
        client["rootUrl"] = 9
    elif case == "CLIENT_LIST_SHAPE":
        client["redirectUris"] = ["provider-list-secret", "provider-list-secret"]
    elif case == "CLIENT_MAPPING_SHAPE":
        client["attributes"] = {"provider-mapping-secret": 9}
    elif case == "MAPPER_INVENTORY_SHAPE":
        mapper_inventory = {"provider-mapper-secret": "sentinel"}
    elif case == "MAPPER_COUNT":
        mapper_inventory = [
            {
                **mapper_documents[0],
                "id": f"10000000-0000-4000-8000-{index:012d}",
                "name": f"bounded-mapper-{index}",
            }
            for index in range(probe._MAXIMUM_PRODUCTION_MAPPERS + 1)
        ]
    elif case == "MAPPER_UUID":
        mapper_documents[0]["id"] = "provider-mapper-uuid-secret"
    elif case == "MAPPER_NAME":
        mapper_documents[0]["name"] = ""
    elif case == "MAPPER_PROTOCOL":
        mapper_documents[0]["protocol"] = ""
    elif case == "MAPPER_TYPE":
        mapper_documents[0]["protocolMapper"] = ""
    elif case == "MAPPER_CONSENT_SHAPE":
        mapper_documents[0]["consentRequired"] = "provider-consent-secret"
    elif case == "MAPPER_ID_DUPLICATE":
        duplicate = dict(mapper_documents[0])
        duplicate["name"] = "bounded-second-mapper"
        mapper_documents.append(duplicate)
    elif case == "MAPPER_NAME_DUPLICATE":
        duplicate = dict(mapper_documents[0])
        duplicate["id"] = "10000000-0000-4000-8000-000000000082"
        mapper_documents.append(duplicate)
    elif case == "MAPPER_CONFIG_SHAPE":
        mapper_documents[0]["config"] = {"provider-config-secret": 9}
    elif case == "ADMIN_BOUNDARY_UNAVAILABLE":
        raised = probe.GatewayAuthParityError
    elif case == "UNKNOWN":
        raised = RuntimeError
    elif case != "PASS":
        raise AssertionError(f"unhandled production invariant case: {case}")
    return search, client, mapper_inventory, raised


def _production_response(value: object) -> httpx.Response:
    return httpx.Response(200, json=value)


@pytest.mark.parametrize(
    "expected",
    (
        "CLIENT_MATCH_COUNT",
        "CLIENT_SEARCH_SHAPE",
        "CLIENT_UUID",
        "CLIENT_DOCUMENT_IDENTITY",
        "CLIENT_STRING_SHAPE",
        "CLIENT_BOOLEAN_SHAPE",
        "CLIENT_OPTIONAL_URL_SHAPE",
        "CLIENT_LIST_SHAPE",
        "CLIENT_MAPPING_SHAPE",
        "MAPPER_INVENTORY_SHAPE",
        "MAPPER_COUNT",
        "MAPPER_UUID",
        "MAPPER_NAME",
        "MAPPER_PROTOCOL",
        "MAPPER_TYPE",
        "MAPPER_CONSENT_SHAPE",
        "MAPPER_ID_DUPLICATE",
        "MAPPER_NAME_DUPLICATE",
        "MAPPER_CONFIG_SHAPE",
        "ADMIN_BOUNDARY_UNAVAILABLE",
        "UNKNOWN",
        "PASS",
    ),
)
def test_production_web_normalizer_returns_every_closed_predicate_without_raw_values(
    expected: str,
) -> None:
    search, client, mapper_inventory, raised = _production_invariant_case(expected)

    def client_search() -> httpx.Response:
        if raised is not None:
            raise raised("provider-search-secret")
        return _production_response(search)

    evidence = probe._classify_production_web_contract(
        client_search=client_search,
        client_document=lambda _uuid: _production_response(client),
        mapper_inventory=lambda _uuid: _production_response(mapper_inventory),
    )
    rendered = probe.format_production_web_invariant_evidence(evidence)

    assert evidence.predicate.value == expected
    assert rendered.count("\n") == 0
    assert f"predicate={expected}" in rendered
    assert "mutation_count=0 retry_count=0" in rendered
    assert "provider-" not in rendered
    assert "10000000-" not in rendered
    assert "http://" not in rendered
    assert "fingerprint" not in rendered


def test_production_web_closed_predicate_table_covers_the_exact_enum() -> None:
    assert tuple(item.value for item in probe.ProductionWebInvariantPredicate) == (
        "CLIENT_MATCH_COUNT",
        "CLIENT_SEARCH_SHAPE",
        "CLIENT_UUID",
        "CLIENT_DOCUMENT_IDENTITY",
        "CLIENT_STRING_SHAPE",
        "CLIENT_BOOLEAN_SHAPE",
        "CLIENT_OPTIONAL_URL_SHAPE",
        "CLIENT_LIST_SHAPE",
        "CLIENT_MAPPING_SHAPE",
        "MAPPER_INVENTORY_SHAPE",
        "MAPPER_COUNT",
        "MAPPER_UUID",
        "MAPPER_NAME",
        "MAPPER_PROTOCOL",
        "MAPPER_TYPE",
        "MAPPER_CONSENT_SHAPE",
        "MAPPER_ID_DUPLICATE",
        "MAPPER_NAME_DUPLICATE",
        "MAPPER_CONFIG_SHAPE",
        "ADMIN_BOUNDARY_UNAVAILABLE",
        "UNKNOWN",
        "PASS",
    )


def test_production_web_boolean_field_and_status_enums_are_exact_and_ordered() -> None:
    assert tuple(item.value for item in probe.ProductionWebBooleanField) == (
        "enabled",
        "publicClient",
        "bearerOnly",
        "surrogateAuthRequired",
        "consentRequired",
        "standardFlowEnabled",
        "directAccessGrantsEnabled",
        "implicitFlowEnabled",
        "serviceAccountsEnabled",
        "authorizationServicesEnabled",
        "fullScopeAllowed",
        "frontchannelLogout",
        "alwaysDisplayInConsole",
    )
    assert probe._PRODUCTION_WEB_BOOLEAN_FIELDS == tuple(
        item.value for item in probe.ProductionWebBooleanField
    )
    assert tuple(item.value for item in probe.ProductionWebBooleanFieldStatus) == (
        "PRESENT_BOOL",
        "MISSING",
        "NON_BOOL",
    )


@pytest.mark.parametrize("field", tuple(probe.ProductionWebBooleanField))
def test_production_web_boolean_subpredicate_reports_each_missing_field_without_mapper_read(
    field: object,
) -> None:
    client, mappers = _production_web_contract()
    field_enum = cast(Any, field)
    client.pop(field_enum.value)
    mapper_reads: list[str] = []

    def mapper_inventory(_uuid: str) -> httpx.Response:
        mapper_reads.append("mapper")
        return _production_response(mappers)

    evidence = probe._classify_production_web_contract(
        client_search=lambda: _production_response(
            [{"id": client["id"], "clientId": "datariver-web"}]
        ),
        client_document=lambda _uuid: _production_response(client),
        mapper_inventory=mapper_inventory,
    )
    rendered = probe.format_production_web_invariant_evidence(evidence)

    assert evidence.predicate is probe.ProductionWebInvariantPredicate.CLIENT_BOOLEAN_SHAPE
    assert evidence.boolean_shape_known
    assert evidence.boolean_missing_fields == (field_enum,)
    assert evidence.boolean_non_bool_fields == ()
    assert "boolean_shape_known=true" in rendered
    assert "boolean_missing_count=1" in rendered
    assert f"boolean_missing_fields=[{field_enum.name}]" in rendered
    assert "boolean_non_bool_count=0 boolean_non_bool_fields=[]" in rendered
    assert mapper_reads == []


_NON_BOOLEAN_VALUES: tuple[object, ...] = (
    None,
    "provider-boolean-string-secret",
    1,
    ["provider-boolean-list-secret"],
    {"provider-boolean-map-secret": True},
)


@pytest.mark.parametrize(
    ("field", "invalid"),
    tuple(
        (field, _NON_BOOLEAN_VALUES[index % len(_NON_BOOLEAN_VALUES)])
        for index, field in enumerate(probe.ProductionWebBooleanField)
    ),
)
def test_production_web_boolean_subpredicate_reports_each_non_bool_exact_type_without_raw_value(
    field: object,
    invalid: object,
) -> None:
    client, mappers = _production_web_contract()
    field_enum = cast(Any, field)
    client[field_enum.value] = invalid

    evidence = probe._classify_production_web_contract(
        client_search=lambda: _production_response(
            [{"id": client["id"], "clientId": "datariver-web"}]
        ),
        client_document=lambda _uuid: _production_response(client),
        mapper_inventory=lambda _uuid: _production_response(mappers),
    )
    rendered = probe.format_production_web_invariant_evidence(evidence)

    assert evidence.predicate is probe.ProductionWebInvariantPredicate.CLIENT_BOOLEAN_SHAPE
    assert evidence.boolean_shape_known
    assert evidence.boolean_missing_fields == ()
    assert evidence.boolean_non_bool_fields == (field_enum,)
    assert "boolean_missing_count=0 boolean_missing_fields=[]" in rendered
    assert "boolean_non_bool_count=1" in rendered
    assert f"boolean_non_bool_fields=[{field_enum.name}]" in rendered
    for forbidden in (
        "provider-boolean-string",
        "provider-boolean-list",
        "provider-boolean-map",
    ):
        assert forbidden not in rendered


def test_boolean_subpredicate_scans_all_fields_in_fixed_order_without_duplicates() -> None:
    client, mappers = _production_web_contract()
    client.pop("alwaysDisplayInConsole")
    client.pop("bearerOnly")
    client["frontchannelLogout"] = "provider-frontchannel-secret"
    client["enabled"] = None
    client["provider-extra-boolean-key"] = "provider-extra-secret"

    evidence = probe._classify_production_web_contract(
        client_search=lambda: _production_response(
            [{"id": client["id"], "clientId": "datariver-web"}]
        ),
        client_document=lambda _uuid: _production_response(client),
        mapper_inventory=lambda _uuid: _production_response(mappers),
    )
    rendered = probe.format_production_web_invariant_evidence(evidence)

    assert evidence.boolean_missing_fields == (
        probe.ProductionWebBooleanField.BEARER_ONLY,
        probe.ProductionWebBooleanField.ALWAYS_DISPLAY_IN_CONSOLE,
    )
    assert evidence.boolean_non_bool_fields == (
        probe.ProductionWebBooleanField.ENABLED,
        probe.ProductionWebBooleanField.FRONTCHANNEL_LOGOUT,
    )
    assert rendered == (
        "predicate=CLIENT_BOOLEAN_SHAPE client_match_count_known=true client_match_count=1 "
        "mapper_count_known=false boolean_shape_known=true boolean_missing_count=2 "
        "boolean_missing_fields=[BEARER_ONLY,ALWAYS_DISPLAY_IN_CONSOLE] "
        "boolean_non_bool_count=2 "
        "boolean_non_bool_fields=[ENABLED,FRONTCHANNEL_LOGOUT] "
        "mutation_count=0 retry_count=0"
    )
    assert "provider-" not in rendered


def test_production_web_boolean_subpredicate_all_valid_is_known_with_empty_defect_sets() -> None:
    client, mappers = _production_web_contract()

    evidence = probe._classify_production_web_contract(
        client_search=lambda: _production_response(
            [{"id": client["id"], "clientId": "datariver-web"}]
        ),
        client_document=lambda _uuid: _production_response(client),
        mapper_inventory=lambda _uuid: _production_response(mappers),
    )
    rendered = probe.format_production_web_invariant_evidence(evidence)

    assert evidence.predicate is probe.ProductionWebInvariantPredicate.PASS
    assert evidence.boolean_shape_known
    assert evidence.boolean_missing_fields == ()
    assert evidence.boolean_non_bool_fields == ()
    assert "boolean_shape_known=true" in rendered
    assert "boolean_missing_count=0 boolean_missing_fields=[]" in rendered
    assert "boolean_non_bool_count=0 boolean_non_bool_fields=[]" in rendered


def test_production_web_boolean_subpredicate_unknown_omits_sets_and_counts() -> None:
    evidence = probe._classify_production_web_contract(
        client_search=lambda: (_ for _ in ()).throw(RuntimeError("provider-unknown-secret")),
        client_document=lambda _uuid: _production_response({}),
        mapper_inventory=lambda _uuid: _production_response([]),
    )
    rendered = probe.format_production_web_invariant_evidence(evidence)

    assert evidence.predicate is probe.ProductionWebInvariantPredicate.UNKNOWN
    assert not evidence.boolean_shape_known
    assert evidence.boolean_missing_fields is None
    assert evidence.boolean_non_bool_fields is None
    assert "boolean_shape_known=false" in rendered
    assert "boolean_missing_count=" not in rendered
    assert "boolean_missing_fields=" not in rendered
    assert "boolean_non_bool_count=" not in rendered
    assert "boolean_non_bool_fields=" not in rendered
    assert "provider-unknown-secret" not in rendered


@pytest.mark.parametrize(
    ("predicate", "fingerprint", "missing", "non_bool"),
    (
        (
            probe.ProductionWebInvariantPredicate.CLIENT_BOOLEAN_SHAPE,
            None,
            (),
            (),
        ),
        (
            probe.ProductionWebInvariantPredicate.CLIENT_BOOLEAN_SHAPE,
            None,
            (
                probe.ProductionWebBooleanField.PUBLIC_CLIENT,
                probe.ProductionWebBooleanField.ENABLED,
            ),
            (),
        ),
        (
            probe.ProductionWebInvariantPredicate.CLIENT_BOOLEAN_SHAPE,
            None,
            (
                probe.ProductionWebBooleanField.ENABLED,
                probe.ProductionWebBooleanField.ENABLED,
            ),
            (),
        ),
        (
            probe.ProductionWebInvariantPredicate.CLIENT_BOOLEAN_SHAPE,
            None,
            (probe.ProductionWebBooleanField.ENABLED,),
            (probe.ProductionWebBooleanField.ENABLED,),
        ),
        (
            probe.ProductionWebInvariantPredicate.PASS,
            "a" * 64,
            (probe.ProductionWebBooleanField.ENABLED,),
            (),
        ),
        (
            probe.ProductionWebInvariantPredicate.UNKNOWN,
            None,
            (),
            (),
        ),
    ),
)
def test_production_web_boolean_subpredicate_evidence_rejects_unknown_or_invalid_sets(
    predicate: Any,
    fingerprint: str | None,
    missing: tuple[Any, ...],
    non_bool: tuple[Any, ...],
) -> None:
    with pytest.raises(ValueError, match="GATEWAY_PRODUCTION_INVARIANT_EVIDENCE_INVALID"):
        probe._ProductionWebInvariantEvidence(
            predicate=predicate,
            fingerprint=fingerprint,
            client_match_count=1,
            mapper_count=None,
            boolean_missing_fields=missing,
            boolean_non_bool_fields=non_bool,
        )


@pytest.mark.parametrize(
    "predicate",
    tuple(
        item
        for item in (
            "CLIENT_MATCH_COUNT",
            "CLIENT_SEARCH_SHAPE",
            "CLIENT_UUID",
            "CLIENT_DOCUMENT_IDENTITY",
            "CLIENT_STRING_SHAPE",
            "CLIENT_BOOLEAN_SHAPE",
            "CLIENT_OPTIONAL_URL_SHAPE",
            "CLIENT_LIST_SHAPE",
            "CLIENT_MAPPING_SHAPE",
            "MAPPER_INVENTORY_SHAPE",
            "MAPPER_COUNT",
            "MAPPER_UUID",
            "MAPPER_NAME",
            "MAPPER_PROTOCOL",
            "MAPPER_TYPE",
            "MAPPER_CONSENT_SHAPE",
            "MAPPER_ID_DUPLICATE",
            "MAPPER_NAME_DUPLICATE",
            "MAPPER_CONFIG_SHAPE",
            "ADMIN_BOUNDARY_UNAVAILABLE",
            "UNKNOWN",
        )
    ),
)
def test_normal_runtime_maps_every_internal_production_predicate_to_generic_failure(
    predicate: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = probe.KeycloakGatewayAuthParityIdentity(
        base_url="http://127.0.0.1:8081",
        admin_username="datariver-bootstrap",
        admin_password="admin-secret-sentinel",
    )
    evidence = probe._ProductionWebInvariantEvidence(
        predicate=probe.ProductionWebInvariantPredicate(predicate),
        fingerprint=None,
        client_match_count=None,
        mapper_count=None,
        boolean_missing_fields=(probe.ProductionWebBooleanField.BEARER_ONLY,)
        if predicate == "CLIENT_BOOLEAN_SHAPE"
        else None,
        boolean_non_bool_fields=() if predicate == "CLIENT_BOOLEAN_SHAPE" else None,
    )
    monkeypatch.setattr(identity, "classify_production_web_invariant", lambda: evidence)

    with pytest.raises(
        probe.GatewayAuthParityError,
        match=r"^GATEWAY_AUTH_PARITY_PRODUCTION_INVARIANT_FAILED$",
    ):
        cast(Any, identity)._production_contract_fingerprint()

    identity.release_without_mutation()


def test_production_web_admin_reads_are_token_then_search_document_mapper_and_short_circuit() -> (
    None
):
    web_document, mapper_documents = _production_web_contract()
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.path.endswith("/protocol/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "admin-token-secret-sentinel"})
        if request.url.path == "/admin/realms/datariver/clients":
            return httpx.Response(
                200,
                json=[{"id": web_document["id"], "clientId": "datariver-web"}],
            )
        if request.url.path.endswith("/protocol-mappers/models"):
            return httpx.Response(200, json=mapper_documents)
        return httpx.Response(200, json=web_document)

    identity = probe.KeycloakGatewayAuthParityIdentity(
        base_url="http://127.0.0.1:8081",
        admin_username="datariver-bootstrap",
        admin_password="admin-secret-sentinel",
    )
    cast(Any, identity)._client.close()
    cast(Any, identity)._client = httpx.Client(
        base_url="http://127.0.0.1:8081",
        transport=httpx.MockTransport(handler),
        trust_env=False,
    )

    evidence = identity.classify_production_web_invariant()

    assert evidence.predicate is probe.ProductionWebInvariantPredicate.PASS
    assert requests == [
        ("POST", "/realms/master/protocol/openid-connect/token"),
        ("GET", "/admin/realms/datariver/clients"),
        ("GET", f"/admin/realms/datariver/clients/{web_document['id']}"),
        (
            "GET",
            f"/admin/realms/datariver/clients/{web_document['id']}/protocol-mappers/models",
        ),
    ]
    identity.release_without_mutation()


def test_production_web_boolean_subpredicate_uses_one_full_document_and_no_mapper_read() -> None:
    web_document, _mapper_documents = _production_web_contract()
    web_document.pop("bearerOnly")
    web_document["frontchannelLogout"] = "provider-non-bool-secret"
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.path.endswith("/protocol/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "admin-token-secret-sentinel"})
        if request.url.path == "/admin/realms/datariver/clients":
            return httpx.Response(
                200,
                json=[{"id": web_document["id"], "clientId": "datariver-web"}],
            )
        if request.url.path.endswith("/protocol-mappers/models"):
            raise AssertionError("boolean-shape failure must not read mappers")
        return httpx.Response(200, json=web_document)

    identity = probe.KeycloakGatewayAuthParityIdentity(
        base_url="http://127.0.0.1:8081",
        admin_username="datariver-bootstrap",
        admin_password="admin-secret-sentinel",
    )
    cast(Any, identity)._client.close()
    cast(Any, identity)._client = httpx.Client(
        base_url="http://127.0.0.1:8081",
        transport=httpx.MockTransport(handler),
        trust_env=False,
    )

    evidence = identity.classify_production_web_invariant()
    rendered = probe.format_production_web_invariant_evidence(evidence)

    assert evidence.predicate is probe.ProductionWebInvariantPredicate.CLIENT_BOOLEAN_SHAPE
    assert evidence.boolean_missing_fields == (probe.ProductionWebBooleanField.BEARER_ONLY,)
    assert evidence.boolean_non_bool_fields == (
        probe.ProductionWebBooleanField.FRONTCHANNEL_LOGOUT,
    )
    assert requests == [
        ("POST", "/realms/master/protocol/openid-connect/token"),
        ("GET", "/admin/realms/datariver/clients"),
        ("GET", f"/admin/realms/datariver/clients/{web_document['id']}"),
    ]
    assert "provider-" not in rendered
    assert "admin-token" not in rendered
    identity.release_without_mutation()


def test_production_web_first_predicate_short_circuits_later_admin_reads() -> None:
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.path.endswith("/protocol/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "admin-token-secret-sentinel"})
        return httpx.Response(200, json=[])

    identity = probe.KeycloakGatewayAuthParityIdentity(
        base_url="http://127.0.0.1:8081",
        admin_username="datariver-bootstrap",
        admin_password="admin-secret-sentinel",
    )
    cast(Any, identity)._client.close()
    cast(Any, identity)._client = httpx.Client(
        base_url="http://127.0.0.1:8081",
        transport=httpx.MockTransport(handler),
        trust_env=False,
    )

    evidence = identity.classify_production_web_invariant()

    assert evidence.predicate is probe.ProductionWebInvariantPredicate.CLIENT_MATCH_COUNT
    assert evidence.client_match_count == 0
    assert evidence.mapper_count is None
    assert requests == [
        ("POST", "/realms/master/protocol/openid-connect/token"),
        ("GET", "/admin/realms/datariver/clients"),
    ]
    identity.release_without_mutation()


@pytest.mark.parametrize("match_count", (0, 2))
def test_production_web_client_match_count_is_bounded_when_known(match_count: int) -> None:
    client, mappers = _production_web_contract()
    search = [
        {
            "id": f"10000000-0000-4000-8000-{index:012d}",
            "clientId": "datariver-web",
        }
        for index in range(match_count)
    ]

    evidence = probe._classify_production_web_contract(
        client_search=lambda: _production_response(search),
        client_document=lambda _uuid: _production_response(client),
        mapper_inventory=lambda _uuid: _production_response(mappers),
    )

    assert evidence.predicate is probe.ProductionWebInvariantPredicate.CLIENT_MATCH_COUNT
    assert evidence.client_match_count == match_count
    assert f"client_match_count={match_count}" in (
        probe.format_production_web_invariant_evidence(evidence)
    )


@pytest.mark.parametrize(
    ("stage", "expected"),
    (
        ("search-overflow", "CLIENT_SEARCH_SHAPE"),
        ("client-nondict", "CLIENT_DOCUMENT_IDENTITY"),
        ("mapper-nonlist", "MAPPER_INVENTORY_SHAPE"),
    ),
)
def test_production_web_provider_container_shapes_fail_at_the_first_exact_stage(
    stage: str,
    expected: str,
) -> None:
    client, mappers = _production_web_contract()
    search: object = [{"id": client["id"], "clientId": "datariver-web"}]
    client_document: object = client
    mapper_inventory: object = mappers
    if stage == "search-overflow":
        search = [
            {"id": client["id"], "clientId": "datariver-web"},
            {"id": client["id"], "clientId": "ignored-one"},
            {"id": client["id"], "clientId": "ignored-two"},
        ]
    elif stage == "client-nondict":
        client_document = ["provider-client-secret"]
    else:
        mapper_inventory = {"provider-mapper-secret": "sentinel"}

    evidence = probe._classify_production_web_contract(
        client_search=lambda: _production_response(search),
        client_document=lambda _uuid: _production_response(client_document),
        mapper_inventory=lambda _uuid: _production_response(mapper_inventory),
    )

    assert evidence.predicate.value == expected
    assert "provider-" not in probe.format_production_web_invariant_evidence(evidence)


@pytest.mark.parametrize(
    ("failure", "expected"),
    (
        ("timeout", "ADMIN_BOUNDARY_UNAVAILABLE"),
        ("overflow", "ADMIN_BOUNDARY_UNAVAILABLE"),
        ("search-non-json", "CLIENT_SEARCH_SHAPE"),
    ),
)
def test_production_web_admin_boundary_and_response_failures_are_fixed_and_nonleaking(
    failure: str,
    expected: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "timeout":
            raise httpx.ReadTimeout("provider-timeout-secret", request=request)
        if failure == "overflow":
            return httpx.Response(
                200,
                content=b"provider-overflow-secret" * probe.MAXIMUM_RESPONSE_BYTES,
            )
        if request.url.path.endswith("/protocol/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "admin-token-secret-sentinel"})
        return httpx.Response(200, content=b"provider-non-json-secret")

    identity = probe.KeycloakGatewayAuthParityIdentity(
        base_url="http://127.0.0.1:8081",
        admin_username="datariver-bootstrap",
        admin_password="admin-secret-sentinel",
    )
    cast(Any, identity)._client.close()
    cast(Any, identity)._client = httpx.Client(
        base_url="http://127.0.0.1:8081",
        transport=httpx.MockTransport(handler),
        trust_env=False,
    )

    evidence = identity.classify_production_web_invariant()
    rendered = probe.format_production_web_invariant_evidence(evidence)

    assert evidence.predicate.value == expected
    combined = capsys.readouterr().out + capsys.readouterr().err + rendered
    for forbidden in ("provider-timeout", "provider-overflow", "provider-non-json", "admin-token"):
        assert forbidden not in combined
    identity.release_without_mutation()


def test_production_web_diagnostic_omits_unavailable_counts_instead_of_estimating() -> None:
    client, mappers = _production_web_contract()
    evidence = probe._classify_production_web_contract(
        client_search=lambda: _production_response(
            [{"id": client["id"], "clientId": "datariver-web"}]
        ),
        client_document=lambda _uuid: _production_response(client),
        mapper_inventory=lambda _uuid: _production_response(
            [
                {
                    **mappers[0],
                    "id": f"10000000-0000-4000-8000-{index:012d}",
                    "name": f"bounded-mapper-{index}",
                }
                for index in range(probe._MAXIMUM_PRODUCTION_MAPPERS + 1)
            ]
        ),
    )

    rendered = probe.format_production_web_invariant_evidence(evidence)

    assert evidence.predicate is probe.ProductionWebInvariantPredicate.MAPPER_COUNT
    assert "client_match_count_known=true client_match_count=1" in rendered
    assert "mapper_count_known=false" in rendered
    assert "mapper_count=" not in rendered


@pytest.mark.parametrize(("client_count", "mapper_count"), ((3, None), (None, 65)))
def test_production_web_evidence_rejects_unbounded_counts(
    client_count: int | None,
    mapper_count: int | None,
) -> None:
    with pytest.raises(ValueError, match="GATEWAY_PRODUCTION_INVARIANT_EVIDENCE_INVALID"):
        probe._ProductionWebInvariantEvidence(
            predicate=probe.ProductionWebInvariantPredicate.UNKNOWN,
            fingerprint=None,
            client_match_count=client_count,
            mapper_count=mapper_count,
        )


class _RecordingContext:
    def __init__(self, events: list[str], label: str, value: object) -> None:
        self.events = events
        self.label = label
        self.value = value

    def __enter__(self) -> object:
        self.events.append(f"{self.label}-enter")
        return self.value

    def __exit__(self, *_args: object) -> None:
        self.events.append(f"{self.label}-exit")


def _install_classifier_runtime(
    classifier: ModuleType,
    probe_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    events: list[str],
    *,
    failure: BaseException | None = None,
) -> None:
    guard = SimpleNamespace(
        file_descriptors={name: index for index, name in enumerate(classifier.SECRET_NAMES)},
        file_identities={name: (index,) for index, name in enumerate(classifier.SECRET_NAMES)},
        revalidate=lambda: events.append("guard-revalidate"),
    )
    monkeypatch.setattr(
        classifier,
        "exclusive_docker_workflow_lock",
        lambda _root: _RecordingContext(events, "lock", object()),
    )

    def applied_state(_path: Path) -> SimpleNamespace:
        events.append("state")
        return SimpleNamespace(
            profile="mac-development",
            deployment_mode="build",
            env_file=".env.mac-development",
            environment_key_hashes={"SAFE": "digest"},
            local_gateway=False,
            local_graph=False,
        )

    def environment_values(_path: Path) -> dict[str, str]:
        events.append("env")
        return {"SAFE": "opaque", "KEYCLOAK_PORT": "8081"}

    def admin_password(_guard: object) -> str:
        events.append("password-read")
        return "admin-secret-sentinel"

    monkeypatch.setattr(
        classifier,
        "load_applied_state",
        applied_state,
    )
    monkeypatch.setattr(
        classifier,
        "read_env_values",
        environment_values,
    )
    monkeypatch.setattr(
        classifier,
        "environment_key_hashes",
        lambda _values: {"SAFE": "digest"},
    )
    monkeypatch.setattr(
        classifier,
        "require_topology_reconciliation_secrets",
        lambda _root: _RecordingContext(events, "guard", guard),
    )
    monkeypatch.setattr(
        classifier,
        "_read_gateway_admin_password",
        admin_password,
    )

    class Identity:
        def __init__(self, **kwargs: object) -> None:
            assert kwargs["base_url"] == "http://127.0.0.1:8081"
            assert kwargs["admin_username"] == "datariver-bootstrap"
            assert kwargs["admin_password"] == "admin-secret-sentinel"
            events.append("identity")

        def classify_production_web_invariant(self) -> object:
            events.append("diagnostic")
            if failure is not None:
                raise failure
            return probe_module._ProductionWebInvariantEvidence(
                predicate=probe_module.ProductionWebInvariantPredicate.PASS,
                fingerprint="a" * 64,
                client_match_count=1,
                mapper_count=1,
                boolean_missing_fields=(),
                boolean_non_bool_fields=(),
            )

        def release_without_mutation(self) -> None:
            events.append("release")

    monkeypatch.setattr(classifier, "KeycloakGatewayAuthParityIdentity", Identity)


@pytest.mark.parametrize(
    "drift",
    (
        "profile",
        "deployment",
        "gateway-selected",
        "graph-selected",
        "environment-path",
        "environment-hash",
        "keycloak-port",
    ),
)
def test_classifier_mac_state_and_environment_drift_is_fixed_before_secret_or_admin_read(
    drift: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    classifier = _load_classifier_module()
    state = SimpleNamespace(
        profile="portable-development" if drift == "profile" else "mac-development",
        deployment_mode="offline" if drift == "deployment" else "build",
        env_file="provider-path-secret" if drift == "environment-path" else ".env.mac-development",
        environment_key_hashes={"SAFE": "wrong" if drift == "environment-hash" else "digest"},
        local_gateway=drift == "gateway-selected",
        local_graph=drift == "graph-selected",
    )
    monkeypatch.setattr(classifier, "load_applied_state", lambda _path: state)
    monkeypatch.setattr(
        classifier,
        "read_env_values",
        lambda _path: {
            "SAFE": "opaque-provider-value",
            "KEYCLOAK_PORT": "provider-port-secret" if drift == "keycloak-port" else "8081",
        },
    )
    monkeypatch.setattr(classifier, "environment_key_hashes", lambda _values: {"SAFE": "digest"})

    with pytest.raises(
        RuntimeError,
        match=r"^GATEWAY_PRODUCTION_INVARIANT_CONTEXT_INVALID$",
    ) as captured:
        classifier._mac_environment()

    combined = capsys.readouterr().out + capsys.readouterr().err + str(captured.value)
    for forbidden in ("provider-path", "provider-port", "opaque-provider"):
        assert forbidden not in combined


def test_classifier_holds_lock_state_env_exact8_guard_and_releases_before_one_line_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    classifier = _load_classifier_module()
    events: list[str] = []
    _install_classifier_runtime(classifier, probe, monkeypatch, events)
    monkeypatch.setattr(sys, "argv", [str(CLASSIFIER_MODULE_PATH)])

    assert classifier.main() == 0

    assert events == [
        "lock-enter",
        "state",
        "env",
        "guard-enter",
        "guard-revalidate",
        "password-read",
        "guard-revalidate",
        "identity",
        "diagnostic",
        "release",
        "guard-revalidate",
        "guard-exit",
        "lock-exit",
    ]
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out == (
        "predicate=PASS client_match_count_known=true client_match_count=1 "
        "mapper_count_known=true mapper_count=1 boolean_shape_known=true "
        "boolean_missing_count=0 boolean_missing_fields=[] boolean_non_bool_count=0 "
        "boolean_non_bool_fields=[] mutation_count=0 retry_count=0\n"
    )
    assert "a" * 64 not in output.out
    assert "admin-secret-sentinel" not in output.out


def test_classifier_rejects_exact8_guard_key_drift_before_admin_boundary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    classifier = _load_classifier_module()
    events: list[str] = []
    _install_classifier_runtime(classifier, probe, monkeypatch, events)
    guard = SimpleNamespace(
        file_descriptors={name: index for index, name in enumerate(classifier.SECRET_NAMES[:-1])},
        file_identities={name: (index,) for index, name in enumerate(classifier.SECRET_NAMES[:-1])},
        revalidate=lambda: events.append("drift-guard-revalidate"),
    )
    monkeypatch.setattr(
        classifier,
        "require_topology_reconciliation_secrets",
        lambda _root: _RecordingContext(events, "drift-guard", guard),
    )
    monkeypatch.setattr(sys, "argv", [str(CLASSIFIER_MODULE_PATH)])

    assert classifier.main() == 2

    assert "password-read" not in events
    assert "identity" not in events
    assert events[-2:] == ["drift-guard-exit", "lock-exit"]
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out.startswith("predicate=UNKNOWN ")


@pytest.mark.parametrize("failure", (RuntimeError("raw-runtime-sentinel"), KeyboardInterrupt()))
def test_classifier_baseexception_closes_every_resource_and_emits_only_fixed_unknown(
    failure: BaseException,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    classifier = _load_classifier_module()
    events: list[str] = []
    _install_classifier_runtime(classifier, probe, monkeypatch, events, failure=failure)
    monkeypatch.setattr(sys, "argv", [str(CLASSIFIER_MODULE_PATH)])

    assert classifier.main() == 2

    assert events.count("diagnostic") == 1
    assert events.count("release") == 1
    assert events[-2:] == ["guard-exit", "lock-exit"]
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out == (
        "predicate=UNKNOWN client_match_count_known=false mapper_count_known=false "
        "boolean_shape_known=false mutation_count=0 retry_count=0\n"
    )
    assert "raw-runtime-sentinel" not in output.out


def test_classifier_rejects_all_arguments_before_lock_or_admin_boundary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    classifier = _load_classifier_module()
    entered: list[str] = []
    monkeypatch.setattr(
        classifier,
        "exclusive_docker_workflow_lock",
        lambda _root: entered.append("lock"),
    )
    monkeypatch.setattr(sys, "argv", [str(CLASSIFIER_MODULE_PATH), "provider-url-secret"])

    assert classifier.main() == 2

    assert entered == []
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out == (
        "predicate=UNKNOWN client_match_count_known=false mapper_count_known=false "
        "boolean_shape_known=false mutation_count=0 retry_count=0\n"
    )
    assert "provider-url-secret" not in output.out


def test_cleanup_retains_multiple_or_nonexact_task_resources_without_deleting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = probe.KeycloakGatewayAuthParityIdentity(
        base_url="http://127.0.0.1:8081",
        admin_username="datariver-bootstrap",
        admin_password="admin-secret-sentinel",
    )
    requested: list[str] = []

    monkeypatch.setattr(
        identity,
        "_find",
        lambda kind, _key, value: (
            [{"username": value, "id": "10000000-0000-4000-8000-000000000021"}] * 2
            if kind == "users" and value == probe.ALLOW_USERNAME
            else []
        ),
    )
    monkeypatch.setattr(
        identity,
        "_request",
        lambda _method, path, **_kwargs: requested.append(path),
    )

    with pytest.raises(
        probe.GatewayAuthParityError,
        match="GATEWAY_AUTH_PARITY_CLEANUP_REQUIRED",
    ):
        identity.cleanup_sessions_and_users()

    assert requested == []
    cast(Any, identity)._client.close()


def test_fixture_prepare_enable_topology_then_exact_matrix_and_cleanup_order() -> None:
    events: list[str] = []

    with _session(events) as session:
        session.prepare()
        session.enable()
        events.append("topology-apply")
        evidence = session.verify_after_topology()

    assert events == [
        "identity-absent",
        "db-absent",
        "identity-create-disabled",
        "db-prepare",
        "identity-enable",
        "db-enable",
        "topology-apply",
        "pkce-allow",
        "traffic-allow-200",
        "traffic-headers-cors",
        "pkce-deny",
        "traffic-deny-403",
        "traffic-malformed-401",
        "genuine-expiry-wait",
        "traffic-expired-401",
        "pkce-allow",
        "token-still-valid",
        "db-revoke",
        "token-still-valid",
        "traffic-membership-revoked-403",
        "logs-clean",
        "identity-sessions-users-cleanup",
        "db-cleanup",
        "identity-client-cleanup",
        "identity-zero",
        "db-zero",
    ]
    assert evidence == probe.GatewayAuthParityEvidence(
        resources=("change-request", "knowledge-registry"),
        hops=("direct", "gateway", "web"),
        statuses=(200, 403, 401, 401, 403),
        immediate_logout="OPEN_UNSUPPORTED",
        retry_count=0,
    )


def test_pre_mutation_absence_failure_releases_private_identity_state_without_cleanup() -> None:
    events: list[str] = []
    session = _session(events)

    def fail_absence() -> None:
        events.append("identity-absent")
        raise probe.GatewayAuthParityError("GATEWAY_AUTH_PARITY_FIXTURE_NOT_ABSENT")

    cast(Any, session)._identity.require_absent_and_capture_invariants = fail_absence

    with pytest.raises(probe.GatewayAuthParityExecutionError) as captured:
        with session:
            session.prepare()

    assert captured.value.first_failure == "GATEWAY_AUTH_PARITY_FIXTURE_NOT_ABSENT"
    assert events == ["identity-absent", "identity-release"]


@pytest.mark.parametrize(
    ("raised", "classification"),
    (
        (
            probe.GatewayAuthParityError("GATEWAY_AUTH_PARITY_MATRIX_FAILED"),
            "GATEWAY_AUTH_PARITY_MATRIX_FAILED",
        ),
        (
            probe.GatewayAuthParityError("GATEWAY_AUTH_PARITY_FIXTURE_FAILED"),
            "GATEWAY_AUTH_PARITY_FIXTURE_FAILED",
        ),
        (RuntimeError("raw-provider-secret-sentinel"), "GATEWAY_AUTH_PARITY_TOPOLOGY_FAILED"),
        (KeyboardInterrupt(), "GATEWAY_AUTH_PARITY_INTERRUPTED"),
    ),
)
def test_any_baseexception_preserves_sanitized_first_failure_and_cleans_exactly_once(
    raised: BaseException,
    classification: str,
) -> None:
    events: list[str] = []
    session = _session(events)

    with pytest.raises(probe.GatewayAuthParityExecutionError) as captured:
        with session:
            session.prepare()
            raise raised

    session.close()
    assert captured.value.first_failure == classification
    assert captured.value.log_evidence_failed is False
    assert captured.value.log_evidence_known is True
    assert captured.value.cleanup_required is False
    assert "raw-provider-secret-sentinel" not in str(captured.value)
    assert events.count("identity-sessions-users-cleanup") == 1
    assert events.count("identity-client-cleanup") == 1
    assert events.count("db-cleanup") == 1
    assert events[-5:] == [
        "identity-sessions-users-cleanup",
        "db-cleanup",
        "identity-client-cleanup",
        "identity-zero",
        "db-zero",
    ]


@pytest.mark.parametrize(
    "raised_kind",
    ("matrix", "interrupt"),
)
@pytest.mark.parametrize(
    "cleanup_failure_kind",
    ("runtime", "interrupt"),
)
def test_first_failure_and_cleanup_failure_are_reported_independently_without_raw_payload(
    raised_kind: str,
    cleanup_failure_kind: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[str] = []
    session = _session(events)
    raised: BaseException = (
        KeyboardInterrupt()
        if raised_kind == "interrupt"
        else probe.GatewayAuthParityError("GATEWAY_AUTH_PARITY_MATRIX_FAILED")
    )
    cleanup_failure: BaseException = (
        KeyboardInterrupt()
        if cleanup_failure_kind == "interrupt"
        else RuntimeError("cleanup-token-path-secret-sentinel")
    )
    cast(Any, session)._identity.cleanup_sessions_and_users = lambda: (_ for _ in ()).throw(
        cleanup_failure
    )

    with pytest.raises(probe.GatewayAuthParityExecutionError) as captured:
        with session:
            session.prepare()
            raise raised

    assert captured.value.first_failure in {
        "GATEWAY_AUTH_PARITY_MATRIX_FAILED",
        "GATEWAY_AUTH_PARITY_INTERRUPTED",
    }
    assert captured.value.cleanup_required is True
    assert captured.value.log_evidence_failed is False
    assert captured.value.log_evidence_known is True
    assert captured.value.__cause__ is None
    assert captured.value.__suppress_context__ is True
    assert events.count("db-cleanup") == 1
    assert events.count("identity-client-cleanup") == 1
    assert events.count("identity-zero") == 1
    assert events.count("db-zero") == 1
    combined = capsys.readouterr().out + capsys.readouterr().err + str(captured.value)
    assert "cleanup-token" not in combined
    assert "path-secret" not in combined


def test_cleanup_failure_is_sanitized_and_continues_all_exact_cleanup_steps(
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[str] = []
    session = _session(events)
    session.prepare()
    cast(Any, session)._identity.cleanup_sessions_and_users = lambda: (_ for _ in ()).throw(
        RuntimeError("raw-admin-response token-secret path-secret")
    )

    with pytest.raises(
        probe.GatewayAuthParityError,
        match="GATEWAY_AUTH_PARITY_CLEANUP_REQUIRED",
    ) as captured:
        session.close()

    assert "db-cleanup" in events
    assert "db-zero" in events
    combined = capsys.readouterr().out + capsys.readouterr().err + str(captured.value)
    assert "raw-admin-response" not in combined
    assert "token-secret" not in combined
    assert "path-secret" not in combined


def test_failed_parity_still_checks_logs_and_preserves_the_first_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[str] = []
    session = _session(events)
    cast(Any, session)._traffic.assert_logs_clean = lambda _sentinels: (_ for _ in ()).throw(
        RuntimeError("raw-log-token-cookie-secret-sentinel")
    )

    with pytest.raises(probe.GatewayAuthParityExecutionError) as captured:
        with session:
            session.prepare()
            raise probe.GatewayAuthParityError("GATEWAY_AUTH_PARITY_MATRIX_FAILED")

    assert captured.value.first_failure == "GATEWAY_AUTH_PARITY_MATRIX_FAILED"
    assert captured.value.log_evidence_failed is True
    assert captured.value.log_evidence_known is False
    assert captured.value.cleanup_required is False
    assert events.count("identity-sessions-users-cleanup") == 1
    assert events.count("db-zero") == 1
    operator = capsys.readouterr()
    exposed = operator.out + operator.err + str(captured.value)
    for forbidden in ("raw-log", "token-cookie", "secret-sentinel"):
        assert forbidden not in exposed


def test_successful_parity_with_known_log_defect_reports_log_outcome_not_cleanup(
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[str] = []
    session = _session(events)
    cast(Any, session)._traffic.assert_logs_clean = lambda _sentinels: (_ for _ in ()).throw(
        probe.GatewayCredentialLogEvidenceError(evidence_known=True)
    )

    with pytest.raises(probe.GatewayAuthParityExecutionError) as captured:
        with session:
            session.prepare()

    assert captured.value.first_failure == "GATEWAY_CREDENTIAL_LOG_PROBE_FAILED"
    assert captured.value.log_evidence_failed is True
    assert captured.value.log_evidence_known is True
    assert captured.value.cleanup_required is False
    assert events.count("identity-sessions-users-cleanup") == 1
    assert events.count("db-zero") == 1
    assert "secret" not in (capsys.readouterr().out + capsys.readouterr().err)


def test_successful_parity_with_unknown_log_probe_failure_is_not_cleanup(
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[str] = []
    session = _session(events)
    cast(Any, session)._traffic.assert_logs_clean = lambda _sentinels: (_ for _ in ()).throw(
        RuntimeError("raw-provider-log-token-secret-sentinel")
    )

    with pytest.raises(probe.GatewayAuthParityExecutionError) as captured:
        with session:
            session.prepare()

    assert captured.value.first_failure == "GATEWAY_CREDENTIAL_LOG_PROBE_FAILED"
    assert captured.value.log_evidence_failed is True
    assert captured.value.log_evidence_known is False
    assert captured.value.cleanup_required is False
    assert events.count("identity-sessions-users-cleanup") == 1
    assert events.count("db-cleanup") == 1
    exposed = capsys.readouterr().out + capsys.readouterr().err + str(captured.value)
    for forbidden in ("raw-provider", "log-token", "secret-sentinel"):
        assert forbidden not in exposed


@pytest.mark.parametrize("cleanup_failure", ("runtime", "interrupt"))
def test_log_evidence_and_cleanup_failures_remain_independent(
    cleanup_failure: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[str] = []
    session = _session(events)
    cast(Any, session)._traffic.assert_logs_clean = lambda _sentinels: (_ for _ in ()).throw(
        probe.GatewayCredentialLogEvidenceError(evidence_known=True)
    )
    failure: BaseException = (
        KeyboardInterrupt()
        if cleanup_failure == "interrupt"
        else RuntimeError("raw-cleanup-provider-token-secret-sentinel")
    )
    cast(Any, session)._identity.cleanup_sessions_and_users = lambda: (_ for _ in ()).throw(failure)

    with pytest.raises(probe.GatewayAuthParityExecutionError) as captured:
        with session:
            session.prepare()

    assert captured.value.first_failure == "GATEWAY_CREDENTIAL_LOG_PROBE_FAILED"
    assert captured.value.log_evidence_failed is True
    assert captured.value.log_evidence_known is True
    assert captured.value.cleanup_required is True
    assert events.count("db-cleanup") == 1
    assert events.count("identity-client-cleanup") == 1
    assert events.count("identity-zero") == 1
    assert events.count("db-zero") == 1
    exposed = capsys.readouterr().out + capsys.readouterr().err + str(captured.value)
    for forbidden in ("raw-cleanup", "provider-token", "secret-sentinel"):
        assert forbidden not in exposed


@pytest.mark.parametrize("first_failure", ("matrix", "interrupt"))
@pytest.mark.parametrize("log_failure", ("runtime", "interrupt"))
def test_first_defect_and_unknown_log_probe_failure_are_reported_independently(
    first_failure: str,
    log_failure: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[str] = []
    session = _session(events)
    observed_log_failure: BaseException = (
        KeyboardInterrupt()
        if log_failure == "interrupt"
        else RuntimeError("raw-log-provider-token-secret-sentinel")
    )
    cast(Any, session)._traffic.assert_logs_clean = lambda _sentinels: (_ for _ in ()).throw(
        observed_log_failure
    )
    original: BaseException = (
        KeyboardInterrupt()
        if first_failure == "interrupt"
        else probe.GatewayAuthParityError("GATEWAY_AUTH_PARITY_MATRIX_FAILED")
    )

    with pytest.raises(probe.GatewayAuthParityExecutionError) as captured:
        with session:
            session.prepare()
            raise original

    assert captured.value.first_failure == (
        "GATEWAY_AUTH_PARITY_INTERRUPTED"
        if first_failure == "interrupt"
        else "GATEWAY_AUTH_PARITY_MATRIX_FAILED"
    )
    assert captured.value.log_evidence_failed is True
    assert captured.value.log_evidence_known is False
    assert captured.value.cleanup_required is False
    assert events.count("identity-sessions-users-cleanup") == 1
    assert events.count("db-cleanup") == 1
    exposed = capsys.readouterr().out + capsys.readouterr().err + str(captured.value)
    for forbidden in ("raw-log", "provider-token", "secret-sentinel"):
        assert forbidden not in exposed


def test_live_status_matrix_invokes_both_resources_and_all_hops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []
    original_client = cast(type[httpx.Client], probe.httpx.Client)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={
                "Access-Control-Allow-Origin": "http://127.0.0.1:8080",
                "Cache-Control": "no-store",
            },
            content=b'{"items":[]}',
        )

    def client(
        *,
        timeout: float,
        follow_redirects: bool,
        trust_env: bool,
    ) -> httpx.Client:
        return original_client(
            transport=httpx.MockTransport(handler),
            timeout=timeout,
            follow_redirects=follow_redirects,
            trust_env=trust_env,
        )

    monkeypatch.setattr(probe.httpx, "Client", client)
    traffic = probe.GatewayAuthParityTraffic(
        direct_url="http://127.0.0.1:8000",
        gateway_url="http://127.0.0.1:9080",
        web_url="http://127.0.0.1:8080",
        origin="http://127.0.0.1:8080",
        log_checker=lambda _started_at, _sentinels: None,
    )

    traffic.verify_status_matrix("allow", "token-secret-sentinel", 200)

    assert probe.PARITY_RESOURCES == (
        ("knowledge-registry", "/api/v1/knowledge/registry/assets"),
        ("change-request", "/api/v1/change-requests"),
    )
    assert probe.PARITY_HOPS == ("direct", "gateway", "web")
    assert len(requests) == 6
    assert {request.url.port for request in requests} == {8000, 9080, 8080}
    assert {request.url.path for request in requests} == {
        "/api/v1/knowledge/registry/assets",
        "/api/v1/change-requests",
    }
    assert all(
        request.headers["authorization"] == "Bearer token-secret-sentinel" for request in requests
    )
    assert all(
        request.headers["cookie"].startswith("datariver_gateway_parity=gateway-parity-cookie-")
        for request in requests
    )


def test_log_interval_starts_once_immediately_before_first_credential_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    log_checks: list[tuple[str, tuple[str, ...]]] = []
    original_client = cast(type[httpx.Client], probe.httpx.Client)

    class FixedDatetime:
        @classmethod
        def now(cls, tz: object) -> datetime:
            assert tz is UTC
            events.append("timestamp")
            return datetime(2026, 8, 3, tzinfo=UTC)

    def handler(request: httpx.Request) -> httpx.Response:
        events.append("request")
        return httpx.Response(200, content=b'{"items":[]}')

    def client(
        *,
        timeout: float,
        follow_redirects: bool,
        trust_env: bool,
    ) -> httpx.Client:
        return original_client(
            transport=httpx.MockTransport(handler),
            timeout=timeout,
            follow_redirects=follow_redirects,
            trust_env=trust_env,
        )

    monkeypatch.setattr(probe, "datetime", FixedDatetime)
    monkeypatch.setattr(probe.httpx, "Client", client)
    traffic = probe.GatewayAuthParityTraffic(
        direct_url="http://127.0.0.1:8000",
        gateway_url="http://127.0.0.1:9080",
        web_url="http://127.0.0.1:8080",
        origin="http://127.0.0.1:8080",
        log_checker=lambda started_at, sentinels: log_checks.append((started_at, sentinels)),
    )

    traffic.verify_status_matrix("allow", "dynamic-token-secret-sentinel", 200)
    traffic.assert_logs_clean(())

    assert events[0] == "timestamp"
    assert events.count("timestamp") == 1
    assert log_checks[0][0] == "2026-08-03T00:00:00.000000Z"
    assert "dynamic-token-secret-sentinel" in log_checks[0][1]


@pytest.mark.parametrize("drift", ("status", "header", "body"))
def test_live_status_matrix_rejects_any_three_hop_semantic_drift(
    drift: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_client = cast(type[httpx.Client], probe.httpx.Client)

    def handler(request: httpx.Request) -> httpx.Response:
        selected = request.url.port == 9080
        return httpx.Response(
            403 if selected and drift == "status" else 200,
            headers={"Cache-Control": "private" if selected and drift == "header" else "no-store"},
            content=(b'{"items":["drift"]}' if selected and drift == "body" else b'{"items":[]}'),
        )

    def client(
        *,
        timeout: float,
        follow_redirects: bool,
        trust_env: bool,
    ) -> httpx.Client:
        return original_client(
            transport=httpx.MockTransport(handler),
            timeout=timeout,
            follow_redirects=follow_redirects,
            trust_env=trust_env,
        )

    monkeypatch.setattr(probe.httpx, "Client", client)
    traffic = probe.GatewayAuthParityTraffic(
        direct_url="http://127.0.0.1:8000",
        gateway_url="http://127.0.0.1:9080",
        web_url="http://127.0.0.1:8080",
        origin="http://127.0.0.1:8080",
        log_checker=lambda _started_at, _sentinels: None,
    )

    with pytest.raises(
        probe.GatewayAuthParityError,
        match="GATEWAY_AUTH_PARITY_MATRIX_FAILED",
    ):
        traffic.verify_status_matrix("allow", "token-secret-sentinel", 200)


def test_cors_preflight_uses_browser_headers_without_fixture_cookie_or_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []
    original_client = cast(type[httpx.Client], probe.httpx.Client)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        status = 204 if request.method == "OPTIONS" else 200
        return httpx.Response(
            status,
            headers={
                "Access-Control-Allow-Origin": "http://127.0.0.1:8080",
                "Access-Control-Allow-Methods": "GET",
                "Access-Control-Allow-Headers": "authorization,x-workspace-id,x-request-id",
                "Cache-Control": "no-store",
            },
            content=b"" if status == 204 else b'{"items":[]}',
        )

    def client(
        *,
        timeout: float,
        follow_redirects: bool,
        trust_env: bool,
    ) -> httpx.Client:
        return original_client(
            transport=httpx.MockTransport(handler),
            timeout=timeout,
            follow_redirects=follow_redirects,
            trust_env=trust_env,
        )

    monkeypatch.setattr(probe.httpx, "Client", client)
    traffic = probe.GatewayAuthParityTraffic(
        direct_url="http://127.0.0.1:8000",
        gateway_url="http://127.0.0.1:9080",
        web_url="http://127.0.0.1:8080",
        origin="http://127.0.0.1:8080",
        log_checker=lambda _started_at, _sentinels: None,
    )

    traffic.verify_cors_and_headers("token-secret-sentinel")

    preflight = [request for request in requests if request.method == "OPTIONS"]
    assert len(preflight) == 6
    assert all("authorization" not in request.headers for request in preflight)
    assert all("cookie" not in request.headers for request in preflight)
    assert all("x-workspace-id" not in request.headers for request in preflight)
    assert all(request.headers["origin"] == "http://127.0.0.1:8080" for request in preflight)


def test_cors_preflight_rejects_gateway_header_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_client = cast(type[httpx.Client], probe.httpx.Client)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method != "OPTIONS":
            return httpx.Response(200, headers={"Cache-Control": "no-store"}, content=b"{}")
        allowed_headers = (
            "authorization"
            if request.url.port == 9080
            else "authorization,x-workspace-id,x-request-id"
        )
        return httpx.Response(
            204,
            headers={
                "Access-Control-Allow-Origin": "http://127.0.0.1:8080",
                "Access-Control-Allow-Methods": "GET",
                "Access-Control-Allow-Headers": allowed_headers,
                "Cache-Control": "no-store",
            },
        )

    def client(
        *,
        timeout: float,
        follow_redirects: bool,
        trust_env: bool,
    ) -> httpx.Client:
        return original_client(
            transport=httpx.MockTransport(handler),
            timeout=timeout,
            follow_redirects=follow_redirects,
            trust_env=trust_env,
        )

    monkeypatch.setattr(probe.httpx, "Client", client)
    traffic = probe.GatewayAuthParityTraffic(
        direct_url="http://127.0.0.1:8000",
        gateway_url="http://127.0.0.1:9080",
        web_url="http://127.0.0.1:8080",
        origin="http://127.0.0.1:8080",
        log_checker=lambda _started_at, _sentinels: None,
    )

    with pytest.raises(
        probe.GatewayAuthParityError,
        match="GATEWAY_AUTH_PARITY_CORS_FAILED",
    ):
        traffic.verify_cors_and_headers("token-secret-sentinel")


def test_live_http_timeout_is_fixed_and_never_exposes_request_credentials(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original_client = cast(type[httpx.Client], probe.httpx.Client)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(
            "raw-timeout-token-secret-sentinel",
            request=request,
        )

    def client(
        *,
        timeout: float,
        follow_redirects: bool,
        trust_env: bool,
    ) -> httpx.Client:
        return original_client(
            transport=httpx.MockTransport(handler),
            timeout=timeout,
            follow_redirects=follow_redirects,
            trust_env=trust_env,
        )

    monkeypatch.setattr(probe.httpx, "Client", client)
    traffic = probe.GatewayAuthParityTraffic(
        direct_url="http://127.0.0.1:8000",
        gateway_url="http://127.0.0.1:9080",
        web_url="http://127.0.0.1:8080",
        origin="http://127.0.0.1:8080",
        log_checker=lambda _started_at, _sentinels: None,
    )

    with pytest.raises(
        probe.GatewayAuthParityError,
        match="GATEWAY_AUTH_PARITY_DEPENDENCY_UNAVAILABLE",
    ) as captured:
        traffic.verify_status_matrix("allow", "request-token-secret-sentinel", 200)

    combined = capsys.readouterr().out + capsys.readouterr().err + str(captured.value)
    assert "raw-timeout" not in combined
    assert "request-token" not in combined


@contextmanager
def _record_context(events: list[str], label: str) -> Iterator[None]:
    events.append(f"{label}-enter")
    try:
        yield
    finally:
        events.append(f"{label}-exit")


def test_workflow_contract_holds_one_session_across_topology_callback() -> None:
    events: list[str] = []

    def factory() -> Any:
        events.append("factory")
        return _session(events)

    with _record_context(events, "lock"):
        result = probe.run_with_topology(factory, lambda: events.append("topology"))

    assert result.immediate_logout == "OPEN_UNSUPPORTED"
    assert events.index("db-enable") < events.index("topology") < events.index("pkce-allow")
    assert events[0] == "lock-enter"
    assert events[-1] == "lock-exit"
