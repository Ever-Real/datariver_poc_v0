#!/usr/bin/env python3
"""Governed Mac-only PKCE and transparent-gateway authorization parity probe."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from html.parser import HTMLParser
from typing import Any, Literal, NoReturn, Protocol, Self
from urllib.parse import parse_qs, urljoin, urlsplit
from uuid import UUID

import httpx

FIXTURE_CONTRACT = "SEC-GATEWAY-AUTH-PARITY-001-A-V1"
FIXTURE_CLIENT_ID = "datariver-gateway-auth-parity-v1"
ALLOW_USERNAME = "datariver-gateway-parity-allow"
DENY_USERNAME = "datariver-gateway-parity-deny"
PKCE_REDIRECT_URI = "http://127.0.0.1:38109/callback"
PKCE_REDIRECT_ORIGIN = "http://127.0.0.1:38109"
ACCESS_TOKEN_LIFESPAN_SECONDS = 30
OIDC_VERIFIER_LEEWAY_SECONDS = 30
GATEWAY_LOG_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
MAXIMUM_RESPONSE_BYTES = 256 * 1024
MAXIMUM_TOKEN_BYTES = 16 * 1024
PARITY_RESOURCES = (
    ("knowledge-registry", "/api/v1/knowledge/registry/assets"),
    ("change-request", "/api/v1/change-requests"),
)
PARITY_HOPS = ("direct", "gateway", "web")
LOCAL_WORKSPACE_ID = "00000000-0000-4000-8000-000000000100"
_SELECTED_RESPONSE_HEADERS = (
    "www-authenticate",
    "set-cookie",
    "access-control-allow-origin",
    "access-control-allow-methods",
    "access-control-allow-headers",
    "cache-control",
    "content-type",
    "x-request-id",
)
_PRODUCTION_WEB_STRING_FIELDS = (
    "clientId",
    "name",
    "protocol",
    "clientAuthenticatorType",
)
_PRODUCTION_WEB_BOOLEAN_FIELDS = (
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
_PRODUCTION_WEB_OPTIONAL_URL_FIELDS = ("rootUrl", "baseUrl", "adminUrl")
_PRODUCTION_WEB_LIST_FIELDS = (
    "redirectUris",
    "webOrigins",
    "defaultClientScopes",
    "optionalClientScopes",
)
_MAXIMUM_PRODUCTION_MAPPERS = 64


class GatewayAuthParityError(RuntimeError):
    """Fixed operator-safe failure with no credential or provider payload."""


class ProductionWebInvariantPredicate(str, Enum):
    """Closed, value-free classification for the fixed production Web client."""

    CLIENT_MATCH_COUNT = "CLIENT_MATCH_COUNT"
    CLIENT_SEARCH_SHAPE = "CLIENT_SEARCH_SHAPE"
    CLIENT_UUID = "CLIENT_UUID"
    CLIENT_DOCUMENT_IDENTITY = "CLIENT_DOCUMENT_IDENTITY"
    CLIENT_STRING_SHAPE = "CLIENT_STRING_SHAPE"
    CLIENT_BOOLEAN_SHAPE = "CLIENT_BOOLEAN_SHAPE"
    CLIENT_OPTIONAL_URL_SHAPE = "CLIENT_OPTIONAL_URL_SHAPE"
    CLIENT_LIST_SHAPE = "CLIENT_LIST_SHAPE"
    CLIENT_MAPPING_SHAPE = "CLIENT_MAPPING_SHAPE"
    MAPPER_INVENTORY_SHAPE = "MAPPER_INVENTORY_SHAPE"
    MAPPER_COUNT = "MAPPER_COUNT"
    MAPPER_UUID = "MAPPER_UUID"
    MAPPER_NAME = "MAPPER_NAME"
    MAPPER_PROTOCOL = "MAPPER_PROTOCOL"
    MAPPER_TYPE = "MAPPER_TYPE"
    MAPPER_CONSENT_SHAPE = "MAPPER_CONSENT_SHAPE"
    MAPPER_ID_DUPLICATE = "MAPPER_ID_DUPLICATE"
    MAPPER_NAME_DUPLICATE = "MAPPER_NAME_DUPLICATE"
    MAPPER_CONFIG_SHAPE = "MAPPER_CONFIG_SHAPE"
    ADMIN_BOUNDARY_UNAVAILABLE = "ADMIN_BOUNDARY_UNAVAILABLE"
    UNKNOWN = "UNKNOWN"
    PASS = "PASS"  # noqa: S105 - closed diagnostic predicate, not a credential.


@dataclass(frozen=True, slots=True)
class _ProductionWebInvariantEvidence:
    predicate: ProductionWebInvariantPredicate
    fingerprint: str | None
    client_match_count: int | None
    mapper_count: int | None

    def __post_init__(self) -> None:
        if (self.client_match_count is not None and not 0 <= self.client_match_count <= 2) or (
            self.mapper_count is not None and not 0 <= self.mapper_count <= 64
        ):
            raise ValueError("GATEWAY_PRODUCTION_INVARIANT_EVIDENCE_INVALID")
        fingerprint_valid = self.fingerprint is not None and (
            len(self.fingerprint) == 64
            and all(character in "0123456789abcdef" for character in self.fingerprint)
        )
        if (self.predicate is ProductionWebInvariantPredicate.PASS) != fingerprint_valid:
            raise ValueError("GATEWAY_PRODUCTION_INVARIANT_EVIDENCE_INVALID")


class _ProductionWebInvariantFailure(Exception):
    def __init__(
        self,
        predicate: ProductionWebInvariantPredicate,
        *,
        client_match_count: int | None = None,
        mapper_count: int | None = None,
    ) -> None:
        self.predicate = predicate
        self.client_match_count = client_match_count
        self.mapper_count = mapper_count
        super().__init__(predicate.value)


def format_production_web_invariant_evidence(
    evidence: _ProductionWebInvariantEvidence,
) -> str:
    """Render the sole bounded diagnostic line; no provider value is accepted."""

    fields = [
        f"predicate={evidence.predicate.value}",
        f"client_match_count_known={str(evidence.client_match_count is not None).lower()}",
    ]
    if evidence.client_match_count is not None:
        fields.append(f"client_match_count={evidence.client_match_count}")
    fields.append(f"mapper_count_known={str(evidence.mapper_count is not None).lower()}")
    if evidence.mapper_count is not None:
        fields.append(f"mapper_count={evidence.mapper_count}")
    fields.extend(("mutation_count=0", "retry_count=0"))
    return " ".join(fields)


_FIRST_FAILURE_CLASSIFICATIONS = frozenset(
    {
        "GATEWAY_AUTH_PARITY_CORS_FAILED",
        "GATEWAY_AUTH_PARITY_CLEANUP_REQUIRED",
        "GATEWAY_AUTH_PARITY_DEPENDENCY_UNAVAILABLE",
        "GATEWAY_AUTH_PARITY_EXPIRY_INVALID",
        "GATEWAY_AUTH_PARITY_FIXTURE_FAILED",
        "GATEWAY_AUTH_PARITY_FIXTURE_NOT_ABSENT",
        "GATEWAY_AUTH_PARITY_FIXTURE_STATE_INVALID",
        "GATEWAY_AUTH_PARITY_HEADER_FAILED",
        "GATEWAY_AUTH_PARITY_IDENTITY_INVALID",
        "GATEWAY_AUTH_PARITY_IDENTITY_OPERATION_FAILED",
        "GATEWAY_AUTH_PARITY_MATRIX_FAILED",
        "GATEWAY_AUTH_PARITY_MATRIX_INVALID",
        "GATEWAY_AUTH_PARITY_MEMBERSHIP_TOKEN_EXPIRED",
        "GATEWAY_AUTH_PARITY_PKCE_FAILED",
        "GATEWAY_AUTH_PARITY_PRODUCTION_INVARIANT_FAILED",
        "GATEWAY_AUTH_PARITY_RESPONSE_INVALID",
        "GATEWAY_AUTH_PARITY_STATE_INVALID",
        "GATEWAY_AUTH_PARITY_TARGET_INVALID",
        "GATEWAY_AUTH_PARITY_TOKEN_INVALID",
        "GATEWAY_CREDENTIAL_LOG_PROBE_FAILED",
    }
)


class GatewayCredentialLogEvidenceError(GatewayAuthParityError):
    """Fixed log-probe failure with an explicit evidence-known outcome."""

    def __init__(self, *, evidence_known: bool) -> None:
        self.evidence_known = evidence_known
        super().__init__("GATEWAY_CREDENTIAL_LOG_PROBE_FAILED")


class GatewayAuthParityExecutionError(GatewayAuthParityError):
    """Sanitized first-failure and independent cleanup outcome."""

    def __init__(
        self,
        *,
        first_failure: str,
        log_evidence_failed: bool,
        log_evidence_known: bool,
        cleanup_required: bool,
    ) -> None:
        if first_failure not in _FIRST_FAILURE_CLASSIFICATIONS | {
            "GATEWAY_AUTH_PARITY_INTERRUPTED",
            "GATEWAY_AUTH_PARITY_TOPOLOGY_FAILED",
        }:
            first_failure = "GATEWAY_AUTH_PARITY_TOPOLOGY_FAILED"
        self.first_failure = first_failure
        self.log_evidence_failed = log_evidence_failed
        self.log_evidence_known = log_evidence_known
        self.cleanup_required = cleanup_required
        super().__init__(
            "GATEWAY_AUTH_PARITY_EXECUTION_FAILED "
            f"first_failure={first_failure} "
            f"log_evidence_failed={str(log_evidence_failed).lower()} "
            f"log_evidence_known={str(log_evidence_known).lower()} "
            f"cleanup_required={str(cleanup_required).lower()}"
        )


def _first_failure_classification(error: BaseException) -> str:
    if isinstance(error, KeyboardInterrupt):
        return "GATEWAY_AUTH_PARITY_INTERRUPTED"
    if isinstance(error, GatewayAuthParityExecutionError):
        return error.first_failure
    if isinstance(error, GatewayAuthParityError) and str(error) in _FIRST_FAILURE_CLASSIFICATIONS:
        return str(error)
    return "GATEWAY_AUTH_PARITY_TOPOLOGY_FAILED"


@dataclass(frozen=True, slots=True)
class GatewayAuthParityToken:
    value: str
    expires_at: int


@dataclass(frozen=True, slots=True)
class GatewayAuthParityEvidence:
    resources: tuple[str, ...]
    hops: tuple[str, ...]
    statuses: tuple[int, ...]
    immediate_logout: str
    retry_count: int


@dataclass(frozen=True, slots=True)
class _ResponseEvidence:
    status: int
    headers: tuple[tuple[str, tuple[str, ...]], ...]
    body_hash: str


@dataclass(frozen=True, slots=True)
class _GatewayAuthParityCloseOutcome:
    log_evidence_failed: bool
    log_evidence_known: bool
    cleanup_required: bool


class GatewayAuthParityFixture(Protocol):
    def require_absent(self) -> None: ...

    def prepare(self, allow_subject: str, deny_subject: str) -> None: ...

    def enable(self, allow_subject: str, deny_subject: str) -> None: ...

    def revoke_allow_membership(self, allow_subject: str, deny_subject: str) -> None: ...

    def cleanup(self, allow_subject: str, deny_subject: str) -> None: ...

    def require_zero_residual(self) -> None: ...


class GatewayAuthParityIdentity(Protocol):
    def require_absent_and_capture_invariants(self) -> None: ...

    def create_disabled_fixture(self) -> tuple[str, str]: ...

    def enable_fixture(self) -> None: ...

    def authenticate_allow(self) -> GatewayAuthParityToken: ...

    def authenticate_deny(self) -> GatewayAuthParityToken: ...

    def cleanup_sessions_and_users(self) -> None: ...

    def cleanup_client(self) -> None: ...

    def require_invariants_and_zero_residual(self) -> None: ...

    def release_without_mutation(self) -> None: ...


class GatewayAuthParityTrafficPort(Protocol):
    def verify_status_matrix(self, scenario: str, token: str, expected_status: int) -> None: ...

    def verify_cors_and_headers(self, token: str) -> None: ...

    def wait_until_expired(self, expires_at: int) -> None: ...

    def require_not_expired(self, expires_at: int) -> None: ...

    def assert_logs_clean(self, sentinels: tuple[str, ...]) -> None: ...


def pkce_client_document() -> dict[str, Any]:
    """Return the one exact public-client document; it contains no credential."""

    return {
        "clientId": FIXTURE_CLIENT_ID,
        "name": "DataRiver Gateway Auth Parity",
        "description": FIXTURE_CONTRACT,
        "enabled": True,
        "protocol": "openid-connect",
        "publicClient": True,
        "clientAuthenticatorType": "client-secret",
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
        "notBefore": 0,
        "alwaysDisplayInConsole": False,
        "authenticationFlowBindingOverrides": {},
        "rootUrl": None,
        "baseUrl": None,
        "adminUrl": None,
        "redirectUris": [PKCE_REDIRECT_URI],
        "webOrigins": [PKCE_REDIRECT_ORIGIN],
        "defaultClientScopes": ["basic", "acr", "profile", "email", "roles"],
        "optionalClientScopes": [],
        "attributes": {
            "pkce.code.challenge.method": "S256",
            "access.token.lifespan": str(ACCESS_TOKEN_LIFESPAN_SECONDS),
        },
    }


def audience_mapper_document() -> dict[str, Any]:
    """Return the one optional-in-cleanup, required-in-use audience mapper."""

    return {
        "name": "datariver-api-audience",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-audience-mapper",
        "consentRequired": False,
        "config": {
            "included.client.audience": "datariver-api",
            "id.token.claim": "false",
            "access.token.claim": "true",
        },
    }


class _LoginFormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.action: str | None = None
        self.fields: dict[str, str] = {}
        self._inside = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form" and attributes.get("id") == "kc-form-login":
            self._inside = True
            self.action = attributes.get("action")
        elif tag == "input" and self._inside:
            name = attributes.get("name")
            if name:
                self.fields[name] = attributes.get("value") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self._inside:
            self._inside = False


def _safe_loopback_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_TARGET_INVALID")
    return value.rstrip("/")


def _same_origin(left: str, right: str) -> bool:
    first = urlsplit(left)
    second = urlsplit(right)
    return (
        first.username is None
        and first.password is None
        and second.username is None
        and second.password is None
        and (first.scheme, first.hostname, first.port)
        == (
            second.scheme,
            second.hostname,
            second.port,
        )
    )


def _exact_pkce_callback(value: str) -> bool:
    candidate = urlsplit(value)
    expected = urlsplit(PKCE_REDIRECT_URI)
    return (
        _same_origin(value, PKCE_REDIRECT_URI)
        and candidate.path == expected.path
        and candidate.fragment == ""
    )


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return verifier, challenge


def _jwt_expiry(token: str) -> int:
    if len(token.encode("utf-8")) > MAXIMUM_TOKEN_BYTES:
        raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_TOKEN_INVALID")
    parts = token.split(".")
    if len(parts) != 3:
        raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_TOKEN_INVALID")
    try:
        document = json.loads(
            base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)).decode("utf-8")
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_TOKEN_INVALID") from None
    expiry = document.get("exp") if isinstance(document, dict) else None
    issued = document.get("iat") if isinstance(document, dict) else None
    audience = document.get("aud") if isinstance(document, dict) else None
    if isinstance(audience, str):
        audience_values = {audience}
    elif isinstance(audience, list) and all(isinstance(value, str) for value in audience):
        audience_values = set(audience)
    else:
        audience_values = set()
    if (
        type(expiry) is not int
        or type(issued) is not int
        or "datariver-api" not in audience_values
        or expiry <= issued
        or expiry - issued > ACCESS_TOKEN_LIFESPAN_SECONDS + 2
    ):
        raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_TOKEN_INVALID")
    return expiry


def _genuine_expiry_reached(*, expires_at: int, observed_at: int) -> bool:
    return observed_at > expires_at + OIDC_VERIFIER_LEEWAY_SECONDS


def _production_failure(
    predicate: ProductionWebInvariantPredicate,
    *,
    client_match_count: int | None,
    mapper_count: int | None = None,
) -> NoReturn:
    raise _ProductionWebInvariantFailure(
        predicate,
        client_match_count=client_match_count,
        mapper_count=mapper_count,
    )


def _normalized_unique_strings(
    value: object,
    *,
    predicate: ProductionWebInvariantPredicate,
    client_match_count: int,
) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or len(value) > 64
        or not all(isinstance(item, str) and item for item in value)
        or len(set(value)) != len(value)
    ):
        _production_failure(predicate, client_match_count=client_match_count)
    return tuple(sorted(value))


def _normalized_string_mapping(
    value: object,
    *,
    predicate: ProductionWebInvariantPredicate,
    client_match_count: int,
    mapper_count: int | None = None,
) -> tuple[tuple[str, str], ...]:
    if (
        not isinstance(value, dict)
        or len(value) > 64
        or not all(
            isinstance(key, str) and key and isinstance(item, str) for key, item in value.items()
        )
    ):
        _production_failure(
            predicate,
            client_match_count=client_match_count,
            mapper_count=mapper_count,
        )
    return tuple(sorted(value.items()))


def _production_response_document(
    reader: Callable[[], httpx.Response],
    *,
    shape_predicate: ProductionWebInvariantPredicate,
    client_match_count: int | None,
    mapper_count: int | None = None,
) -> object:
    try:
        response = reader()
    except GatewayAuthParityError:
        _production_failure(
            ProductionWebInvariantPredicate.ADMIN_BOUNDARY_UNAVAILABLE,
            client_match_count=client_match_count,
            mapper_count=mapper_count,
        )
    try:
        return response.json()
    except ValueError:
        _production_failure(
            shape_predicate,
            client_match_count=client_match_count,
            mapper_count=mapper_count,
        )


def _normalize_production_web_contract(
    *,
    client_search: Callable[[], httpx.Response],
    client_document: Callable[[str], httpx.Response],
    mapper_inventory: Callable[[str], httpx.Response],
) -> _ProductionWebInvariantEvidence:
    """Apply the one ordered production-Web contract used by runtime and diagnosis."""

    search_document = _production_response_document(
        client_search,
        shape_predicate=ProductionWebInvariantPredicate.CLIENT_SEARCH_SHAPE,
        client_match_count=None,
    )
    if not isinstance(search_document, list) or len(search_document) > 2:
        _production_failure(
            ProductionWebInvariantPredicate.CLIENT_SEARCH_SHAPE,
            client_match_count=None,
        )
    matches = [
        item
        for item in search_document
        if isinstance(item, dict) and item.get("clientId") == "datariver-web"
    ]
    client_match_count = len(matches)
    if client_match_count != 1:
        _production_failure(
            ProductionWebInvariantPredicate.CLIENT_MATCH_COUNT,
            client_match_count=client_match_count,
        )
    try:
        client_uuid = str(UUID(matches[0].get("id")))
    except (TypeError, ValueError):
        _production_failure(
            ProductionWebInvariantPredicate.CLIENT_UUID,
            client_match_count=client_match_count,
        )

    selected = _production_response_document(
        lambda: client_document(client_uuid),
        shape_predicate=ProductionWebInvariantPredicate.CLIENT_DOCUMENT_IDENTITY,
        client_match_count=client_match_count,
    )
    if (
        not isinstance(selected, dict)
        or selected.get("id") != client_uuid
        or selected.get("clientId") != "datariver-web"
        or type(selected.get("notBefore")) is not int
    ):
        _production_failure(
            ProductionWebInvariantPredicate.CLIENT_DOCUMENT_IDENTITY,
            client_match_count=client_match_count,
        )
    if any(
        not isinstance(selected.get(field), str) or not selected[field]
        for field in _PRODUCTION_WEB_STRING_FIELDS
    ):
        _production_failure(
            ProductionWebInvariantPredicate.CLIENT_STRING_SHAPE,
            client_match_count=client_match_count,
        )
    if any(type(selected.get(field)) is not bool for field in _PRODUCTION_WEB_BOOLEAN_FIELDS):
        _production_failure(
            ProductionWebInvariantPredicate.CLIENT_BOOLEAN_SHAPE,
            client_match_count=client_match_count,
        )
    if any(
        selected.get(field) is not None and not isinstance(selected[field], str)
        for field in _PRODUCTION_WEB_OPTIONAL_URL_FIELDS
    ):
        _production_failure(
            ProductionWebInvariantPredicate.CLIENT_OPTIONAL_URL_SHAPE,
            client_match_count=client_match_count,
        )

    normalized_lists = {
        field: _normalized_unique_strings(
            selected.get(field),
            predicate=ProductionWebInvariantPredicate.CLIENT_LIST_SHAPE,
            client_match_count=client_match_count,
        )
        for field in _PRODUCTION_WEB_LIST_FIELDS
    }
    flow_overrides = _normalized_string_mapping(
        selected.get("authenticationFlowBindingOverrides"),
        predicate=ProductionWebInvariantPredicate.CLIENT_MAPPING_SHAPE,
        client_match_count=client_match_count,
    )
    attributes = _normalized_string_mapping(
        selected.get("attributes"),
        predicate=ProductionWebInvariantPredicate.CLIENT_MAPPING_SHAPE,
        client_match_count=client_match_count,
    )

    mapper_document = _production_response_document(
        lambda: mapper_inventory(client_uuid),
        shape_predicate=ProductionWebInvariantPredicate.MAPPER_INVENTORY_SHAPE,
        client_match_count=client_match_count,
    )
    if not isinstance(mapper_document, list) or not all(
        isinstance(item, dict) for item in mapper_document
    ):
        _production_failure(
            ProductionWebInvariantPredicate.MAPPER_INVENTORY_SHAPE,
            client_match_count=client_match_count,
        )
    if len(mapper_document) > _MAXIMUM_PRODUCTION_MAPPERS:
        _production_failure(
            ProductionWebInvariantPredicate.MAPPER_COUNT,
            client_match_count=client_match_count,
        )
    mapper_count = len(mapper_document)
    normalized_mappers: list[dict[str, object]] = []
    mapper_ids: set[str] = set()
    mapper_names: set[str] = set()
    for mapper in mapper_document:
        try:
            mapper_id = str(UUID(mapper.get("id")))
        except (TypeError, ValueError):
            _production_failure(
                ProductionWebInvariantPredicate.MAPPER_UUID,
                client_match_count=client_match_count,
                mapper_count=mapper_count,
            )
        name = mapper.get("name")
        protocol = mapper.get("protocol")
        protocol_mapper = mapper.get("protocolMapper")
        consent_required = mapper.get("consentRequired")
        if not isinstance(name, str) or not name:
            _production_failure(
                ProductionWebInvariantPredicate.MAPPER_NAME,
                client_match_count=client_match_count,
                mapper_count=mapper_count,
            )
        if not isinstance(protocol, str) or not protocol:
            _production_failure(
                ProductionWebInvariantPredicate.MAPPER_PROTOCOL,
                client_match_count=client_match_count,
                mapper_count=mapper_count,
            )
        if not isinstance(protocol_mapper, str) or not protocol_mapper:
            _production_failure(
                ProductionWebInvariantPredicate.MAPPER_TYPE,
                client_match_count=client_match_count,
                mapper_count=mapper_count,
            )
        if type(consent_required) is not bool:
            _production_failure(
                ProductionWebInvariantPredicate.MAPPER_CONSENT_SHAPE,
                client_match_count=client_match_count,
                mapper_count=mapper_count,
            )
        if mapper_id in mapper_ids:
            _production_failure(
                ProductionWebInvariantPredicate.MAPPER_ID_DUPLICATE,
                client_match_count=client_match_count,
                mapper_count=mapper_count,
            )
        if name in mapper_names:
            _production_failure(
                ProductionWebInvariantPredicate.MAPPER_NAME_DUPLICATE,
                client_match_count=client_match_count,
                mapper_count=mapper_count,
            )
        mapper_ids.add(mapper_id)
        mapper_names.add(name)
        normalized_mappers.append(
            {
                "id": mapper_id,
                "name": name,
                "protocol": protocol,
                "protocolMapper": protocol_mapper,
                "consentRequired": consent_required,
                "config": _normalized_string_mapping(
                    mapper.get("config"),
                    predicate=ProductionWebInvariantPredicate.MAPPER_CONFIG_SHAPE,
                    client_match_count=client_match_count,
                    mapper_count=mapper_count,
                ),
            }
        )
    bounded = {
        "id": client_uuid,
        **{field: selected[field] for field in _PRODUCTION_WEB_STRING_FIELDS},
        **{field: selected[field] for field in _PRODUCTION_WEB_BOOLEAN_FIELDS},
        "notBefore": selected["notBefore"],
        **{field: selected.get(field) for field in _PRODUCTION_WEB_OPTIONAL_URL_FIELDS},
        **normalized_lists,
        "authenticationFlowBindingOverrides": flow_overrides,
        "attributes": attributes,
        "protocolMappers": tuple(
            sorted(normalized_mappers, key=lambda document: str(document["id"]))
        ),
    }
    encoded = json.dumps(bounded, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _ProductionWebInvariantEvidence(
        predicate=ProductionWebInvariantPredicate.PASS,
        fingerprint=hashlib.sha256(encoded).hexdigest(),
        client_match_count=client_match_count,
        mapper_count=mapper_count,
    )


def _classify_production_web_contract(
    *,
    client_search: Callable[[], httpx.Response],
    client_document: Callable[[str], httpx.Response],
    mapper_inventory: Callable[[str], httpx.Response],
) -> _ProductionWebInvariantEvidence:
    try:
        return _normalize_production_web_contract(
            client_search=client_search,
            client_document=client_document,
            mapper_inventory=mapper_inventory,
        )
    except _ProductionWebInvariantFailure as error:
        return _ProductionWebInvariantEvidence(
            predicate=error.predicate,
            fingerprint=None,
            client_match_count=error.client_match_count,
            mapper_count=error.mapper_count,
        )
    except Exception:
        return _ProductionWebInvariantEvidence(
            predicate=ProductionWebInvariantPredicate.UNKNOWN,
            fingerprint=None,
            client_match_count=None,
            mapper_count=None,
        )


def _bounded_response(client: httpx.Client, request: httpx.Request) -> httpx.Response:
    response: httpx.Response | None = None
    try:
        response = client.send(request, stream=True)
        body = bytearray()
        for chunk in response.iter_bytes(chunk_size=64 * 1024):
            body.extend(chunk)
            if len(body) > MAXIMUM_RESPONSE_BYTES:
                raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_RESPONSE_INVALID")
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            content=bytes(body),
            request=request,
        )
    except httpx.HTTPError:
        raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_DEPENDENCY_UNAVAILABLE") from None
    finally:
        if response is not None:
            response.close()


class KeycloakGatewayAuthParityIdentity:
    """Exact local Keycloak fixture; no generic Admin API pass-through."""

    def __init__(
        self,
        *,
        base_url: str,
        admin_username: str,
        admin_password: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._base_url = _safe_loopback_url(base_url)
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
        )
        self._admin_username = admin_username
        self._admin_password = admin_password
        self._admin_token: str | None = None
        self._client_uuid: str | None = None
        self._allow_subject: str | None = None
        self._deny_subject: str | None = None
        self._allow_password: str | None = None
        self._deny_password: str | None = None
        self._production_fingerprint: str | None = None

    def _request(
        self,
        method: str,
        path: str,
        *,
        expected: frozenset[int],
        authenticated: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}))
        if authenticated:
            if self._admin_token is None:
                self._authenticate_admin()
            headers["Authorization"] = f"Bearer {self._admin_token}"
        request = self._client.build_request(method, path, headers=headers, **kwargs)
        response = _bounded_response(self._client, request)
        if response.status_code not in expected:
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_IDENTITY_OPERATION_FAILED")
        return response

    def _authenticate_admin(self) -> None:
        response = self._request(
            "POST",
            "/realms/master/protocol/openid-connect/token",
            expected=frozenset({200}),
            authenticated=False,
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": self._admin_username,
                "password": self._admin_password,
            },
        )
        try:
            document = response.json()
        except ValueError:
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_IDENTITY_OPERATION_FAILED") from None
        token = document.get("access_token") if isinstance(document, dict) else None
        if not isinstance(token, str) or not token or len(token) > MAXIMUM_TOKEN_BYTES:
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_IDENTITY_OPERATION_FAILED")
        self._admin_token = token

    def _find(self, kind: str, key: str, value: str) -> list[dict[str, Any]]:
        if kind not in {"clients", "users"} or key not in {"clientId", "username"}:
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_IDENTITY_OPERATION_FAILED")
        response = self._request(
            "GET",
            f"/admin/realms/datariver/{kind}",
            expected=frozenset({200}),
            params={key: value, **({"exact": "true"} if kind == "users" else {})},
        )
        try:
            document = response.json()
        except ValueError:
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_IDENTITY_OPERATION_FAILED") from None
        if not isinstance(document, list) or len(document) > 2:
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_IDENTITY_OPERATION_FAILED")
        return [item for item in document if isinstance(item, dict) and item.get(key) == value]

    def _production_contract_fingerprint(self) -> str:
        evidence = self.classify_production_web_invariant()
        if (
            evidence.predicate is not ProductionWebInvariantPredicate.PASS
            or evidence.fingerprint is None
        ):
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_PRODUCTION_INVARIANT_FAILED")
        return evidence.fingerprint

    def classify_production_web_invariant(self) -> _ProductionWebInvariantEvidence:
        """Read only the fixed production Web client through the shared normalizer."""

        return _classify_production_web_contract(
            client_search=lambda: self._request(
                "GET",
                "/admin/realms/datariver/clients",
                expected=frozenset({200}),
                params={"clientId": "datariver-web"},
            ),
            client_document=lambda client_uuid: self._request(
                "GET",
                f"/admin/realms/datariver/clients/{client_uuid}",
                expected=frozenset({200}),
            ),
            mapper_inventory=lambda client_uuid: self._request(
                "GET",
                f"/admin/realms/datariver/clients/{client_uuid}/protocol-mappers/models",
                expected=frozenset({200}),
            ),
        )

    def _get_admin_document(self, path: str) -> dict[str, Any]:
        response = self._request("GET", path, expected=frozenset({200}))
        try:
            document = response.json()
        except ValueError:
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_IDENTITY_OPERATION_FAILED") from None
        if not isinstance(document, dict):
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_IDENTITY_OPERATION_FAILED")
        return document

    def _get_admin_document_optional(self, path: str) -> dict[str, Any] | None:
        response = self._request("GET", path, expected=frozenset({200, 404}))
        if response.status_code == 404:
            return None
        try:
            document = response.json()
        except ValueError:
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_IDENTITY_OPERATION_FAILED") from None
        if not isinstance(document, dict):
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_IDENTITY_OPERATION_FAILED")
        return document

    def _get_admin_list(self, path: str) -> list[dict[str, Any]]:
        response = self._request("GET", path, expected=frozenset({200}))
        try:
            document = response.json()
        except ValueError:
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_IDENTITY_OPERATION_FAILED") from None
        if (
            not isinstance(document, list)
            or len(document) > 2
            or not all(isinstance(item, dict) for item in document)
        ):
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_IDENTITY_OPERATION_FAILED")
        return document

    def require_absent_and_capture_invariants(self) -> None:
        if self._find("clients", "clientId", FIXTURE_CLIENT_ID):
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_FIXTURE_NOT_ABSENT")
        if self._find("users", "username", ALLOW_USERNAME) or self._find(
            "users", "username", DENY_USERNAME
        ):
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_FIXTURE_NOT_ABSENT")
        self._production_fingerprint = self._production_contract_fingerprint()

    def _created_id(self, response: httpx.Response) -> str:
        location = response.headers.get("location", "")
        candidate = urlsplit(location).path.rstrip("/").rsplit("/", 1)[-1]
        try:
            return str(UUID(candidate))
        except ValueError:
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_IDENTITY_OPERATION_FAILED") from None

    def _create_disabled_user(self, username: str, password: str) -> str:
        response = self._request(
            "POST",
            "/admin/realms/datariver/users",
            expected=frozenset({201}),
            json={
                "username": username,
                "firstName": "DataRiver",
                "lastName": "Gateway Parity",
                "email": f"{username}@localhost.invalid",
                "emailVerified": True,
                "enabled": False,
                "requiredActions": [],
                "credentials": [{"type": "password", "value": password, "temporary": False}],
                "attributes": {"datariverFixture": [FIXTURE_CONTRACT]},
            },
        )
        return self._created_id(response)

    def _validated_client_uuid(
        self,
        *,
        allow_absent: bool,
        allow_partial_mapper: bool,
    ) -> str | None:
        matches = self._find("clients", "clientId", FIXTURE_CLIENT_ID)
        expected = pkce_client_document()
        if not matches:
            if (
                self._client_uuid is not None
                and self._get_admin_document_optional(
                    f"/admin/realms/datariver/clients/{self._client_uuid}"
                )
                is not None
            ):
                raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_FIXTURE_STATE_INVALID")
            if allow_absent:
                return None
        candidate = matches[0].get("id") if len(matches) == 1 else None
        try:
            candidate = str(UUID(candidate))
        except (TypeError, ValueError):
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_FIXTURE_STATE_INVALID") from None
        if self._client_uuid is not None and candidate != self._client_uuid:
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_FIXTURE_STATE_INVALID")
        selected = self._get_admin_document(f"/admin/realms/datariver/clients/{candidate}")
        for key in (
            "clientId",
            "name",
            "description",
            "enabled",
            "protocol",
            "publicClient",
            "clientAuthenticatorType",
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
            "notBefore",
            "alwaysDisplayInConsole",
            "authenticationFlowBindingOverrides",
            "rootUrl",
            "baseUrl",
            "adminUrl",
            "redirectUris",
            "webOrigins",
            "defaultClientScopes",
            "optionalClientScopes",
        ):
            if selected.get(key) != expected[key]:
                raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_FIXTURE_STATE_INVALID")
        attributes = selected.get("attributes")
        if not isinstance(attributes, dict) or attributes != expected["attributes"]:
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_FIXTURE_STATE_INVALID")
        mappers = self._get_admin_list(
            f"/admin/realms/datariver/clients/{candidate}/protocol-mappers/models"
        )
        allowed_mapper_counts = {0, 1} if allow_partial_mapper else {1}
        if len(mappers) not in allowed_mapper_counts:
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_FIXTURE_STATE_INVALID")
        if mappers:
            expected_mapper = audience_mapper_document()
            selected_mapper = mappers[0]
            if any(selected_mapper.get(key) != value for key, value in expected_mapper.items()):
                raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_FIXTURE_STATE_INVALID")
        return candidate

    def _validated_user_uuid(
        self,
        username: str,
        subject: str | None,
        *,
        enabled: bool | None,
        allow_absent: bool,
    ) -> str | None:
        matches = self._find("users", "username", username)
        if not matches:
            if (
                subject is not None
                and self._get_admin_document_optional(f"/admin/realms/datariver/users/{subject}")
                is not None
            ):
                raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_FIXTURE_STATE_INVALID")
            if allow_absent:
                return None
        candidate = matches[0].get("id") if len(matches) == 1 else None
        try:
            candidate = str(UUID(candidate))
        except (TypeError, ValueError):
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_FIXTURE_STATE_INVALID") from None
        if subject is not None and candidate != subject:
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_FIXTURE_STATE_INVALID")
        selected = self._get_admin_document(f"/admin/realms/datariver/users/{candidate}")
        attributes = selected.get("attributes")
        if (
            selected.get("id") != candidate
            or selected.get("username") != username
            or (enabled is not None and selected.get("enabled") is not enabled)
            or selected.get("firstName") != "DataRiver"
            or selected.get("lastName") != "Gateway Parity"
            or selected.get("email") != f"{username}@localhost.invalid"
            or selected.get("emailVerified") is not True
            or selected.get("requiredActions") != []
            or selected.get("serviceAccountClientId") is not None
            or selected.get("federationLink") is not None
            or selected.get("federatedIdentities") not in (None, [])
            or not isinstance(attributes, dict)
            or attributes != {"datariverFixture": [FIXTURE_CONTRACT]}
        ):
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_FIXTURE_STATE_INVALID")
        return candidate

    def create_disabled_fixture(self) -> tuple[str, str]:
        self._allow_password = secrets.token_urlsafe(48)
        self._deny_password = secrets.token_urlsafe(48)
        client = self._request(
            "POST",
            "/admin/realms/datariver/clients",
            expected=frozenset({201}),
            json=pkce_client_document(),
        )
        self._client_uuid = self._created_id(client)
        self._request(
            "POST",
            f"/admin/realms/datariver/clients/{self._client_uuid}/protocol-mappers/models",
            expected=frozenset({201}),
            json=audience_mapper_document(),
        )
        self._allow_subject = self._create_disabled_user(ALLOW_USERNAME, self._allow_password)
        self._deny_subject = self._create_disabled_user(DENY_USERNAME, self._deny_password)
        if (
            self._validated_client_uuid(
                allow_absent=False,
                allow_partial_mapper=False,
            )
            is None
        ):
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_FIXTURE_STATE_INVALID")
        for username, subject in (
            (ALLOW_USERNAME, self._allow_subject),
            (DENY_USERNAME, self._deny_subject),
        ):
            if (
                self._validated_user_uuid(
                    username,
                    subject,
                    enabled=False,
                    allow_absent=False,
                )
                is None
            ):
                raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_FIXTURE_STATE_INVALID")
        return self._allow_subject, self._deny_subject

    def enable_fixture(self) -> None:
        for subject in (self._allow_subject, self._deny_subject):
            if subject is None:
                raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_FIXTURE_STATE_INVALID")
            self._request(
                "PUT",
                f"/admin/realms/datariver/users/{subject}",
                expected=frozenset({204}),
                json={"enabled": True},
            )
        if (
            self._validated_client_uuid(
                allow_absent=False,
                allow_partial_mapper=False,
            )
            is None
        ):
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_FIXTURE_STATE_INVALID")
        for username, subject in (
            (ALLOW_USERNAME, self._allow_subject),
            (DENY_USERNAME, self._deny_subject),
        ):
            if (
                self._validated_user_uuid(
                    username,
                    subject,
                    enabled=True,
                    allow_absent=False,
                )
                is None
            ):
                raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_FIXTURE_STATE_INVALID")
        self._admin_token = None

    def _normalize_loopback_cookies(self, browser: httpx.Client) -> None:
        if urlsplit(self._base_url).scheme != "http":
            return
        for cookie in browser.cookies.jar:
            cookie.secure = False

    def _authenticate(self, username: str, password: str | None) -> GatewayAuthParityToken:
        if password is None:
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_FIXTURE_STATE_INVALID")
        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        with httpx.Client(
            base_url=self._base_url,
            timeout=self._client.timeout,
            follow_redirects=False,
            trust_env=False,
        ) as browser:
            request = browser.build_request(
                "GET",
                "/realms/datariver/protocol/openid-connect/auth",
                params={
                    "client_id": FIXTURE_CLIENT_ID,
                    "redirect_uri": PKCE_REDIRECT_URI,
                    "response_type": "code",
                    "response_mode": "query",
                    "scope": "openid",
                    "state": state,
                    "nonce": nonce,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                    "max_age": "0",
                    "prompt": "login",
                },
            )
            response = _bounded_response(browser, request)
            if response.status_code != 200:
                raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_PKCE_FAILED")
            self._normalize_loopback_cookies(browser)
            parser = _LoginFormParser()
            parser.feed(response.text)
            if parser.action is None:
                raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_PKCE_FAILED")
            action = urljoin(self._base_url, parser.action)
            if not _same_origin(self._base_url, action):
                raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_PKCE_FAILED")
            form = {**parser.fields, "username": username, "password": password, "credentialId": ""}
            self._normalize_loopback_cookies(browser)
            response = _bounded_response(browser, browser.build_request("POST", action, data=form))
            self._normalize_loopback_cookies(browser)
            query: dict[str, list[str]] | None = None
            for _ in range(5):
                if response.status_code not in {302, 303}:
                    break
                location = response.headers.get("location", "")
                if _exact_pkce_callback(location):
                    candidate = parse_qs(urlsplit(location).query)
                    if candidate.get("state") == [state] and len(candidate.get("code", ())) == 1:
                        query = candidate
                    break
                if not _same_origin(self._base_url, location):
                    break
                self._normalize_loopback_cookies(browser)
                response = _bounded_response(
                    browser,
                    browser.build_request("GET", location),
                )
                self._normalize_loopback_cookies(browser)
            if query is None:
                raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_PKCE_FAILED")
            self._normalize_loopback_cookies(browser)
            token_response = _bounded_response(
                browser,
                browser.build_request(
                    "POST",
                    "/realms/datariver/protocol/openid-connect/token",
                    data={
                        "client_id": FIXTURE_CLIENT_ID,
                        "grant_type": "authorization_code",
                        "code": query["code"][0],
                        "redirect_uri": PKCE_REDIRECT_URI,
                        "code_verifier": verifier,
                    },
                ),
            )
            if token_response.status_code != 200:
                raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_PKCE_FAILED")
            try:
                token = token_response.json().get("access_token")
            except (AttributeError, ValueError):
                raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_PKCE_FAILED") from None
            if not isinstance(token, str):
                raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_PKCE_FAILED")
            return GatewayAuthParityToken(token, _jwt_expiry(token))

    def authenticate_allow(self) -> GatewayAuthParityToken:
        return self._authenticate(ALLOW_USERNAME, self._allow_password)

    def authenticate_deny(self) -> GatewayAuthParityToken:
        return self._authenticate(DENY_USERNAME, self._deny_password)

    def cleanup_sessions_and_users(self) -> None:
        # Any earlier Admin API token may have aged during build/topology/expiry
        # evidence. Force one fresh token at the cleanup boundary; subsequent
        # user and client cleanup requests reuse only that bounded session.
        self._admin_token = None
        failures = False
        for username, recorded_subject in (
            (ALLOW_USERNAME, self._allow_subject),
            (DENY_USERNAME, self._deny_subject),
        ):
            try:
                subject = self._validated_user_uuid(
                    username,
                    recorded_subject,
                    enabled=None,
                    allow_absent=True,
                )
                if subject is None:
                    continue
                self._request(
                    "POST",
                    f"/admin/realms/datariver/users/{subject}/logout",
                    expected=frozenset({204, 404}),
                )
                self._request(
                    "DELETE",
                    f"/admin/realms/datariver/users/{subject}",
                    expected=frozenset({204, 404}),
                )
            except BaseException:
                failures = True
        self._allow_password = None
        self._deny_password = None
        if failures:
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_CLEANUP_REQUIRED")

    def cleanup_client(self) -> None:
        failures = False
        try:
            client_uuid = self._validated_client_uuid(
                allow_absent=True,
                allow_partial_mapper=True,
            )
            if client_uuid is not None:
                self._request(
                    "DELETE",
                    f"/admin/realms/datariver/clients/{client_uuid}",
                    expected=frozenset({204, 404}),
                )
        except BaseException:
            failures = True
        if failures:
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_CLEANUP_REQUIRED")

    def require_invariants_and_zero_residual(self) -> None:
        try:
            try:
                invalid = (
                    self._find("clients", "clientId", FIXTURE_CLIENT_ID)
                    or self._find("users", "username", ALLOW_USERNAME)
                    or self._find("users", "username", DENY_USERNAME)
                    or self._production_fingerprint is None
                    or self._production_contract_fingerprint() != self._production_fingerprint
                )
            except BaseException:
                raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_CLEANUP_REQUIRED") from None
            if invalid:
                raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_CLEANUP_REQUIRED")
        finally:
            self.release_without_mutation()

    def release_without_mutation(self) -> None:
        self._admin_password = ""
        self._admin_token = None
        self._allow_password = None
        self._deny_password = None
        self._client.close()


class GatewayAuthParityTraffic:
    def __init__(
        self,
        *,
        direct_url: str,
        gateway_url: str,
        web_url: str,
        origin: str,
        log_checker: Callable[[str, tuple[str, ...]], None],
        timeout_seconds: float = 10.0,
    ) -> None:
        self._bases = tuple(
            _safe_loopback_url(value) for value in (direct_url, gateway_url, web_url)
        )
        self._origin = _safe_loopback_url(origin)
        self._log_checker = log_checker
        self._timeout = timeout_seconds
        self._cookie_sentinel = "gateway-parity-cookie-" + secrets.token_urlsafe(18)
        self._body_sentinel = "gateway-parity-body-" + secrets.token_urlsafe(18)
        self._sentinels = {self._cookie_sentinel, self._body_sentinel}
        self._log_started_at: str | None = None

    def _request(
        self,
        base: str,
        path: str,
        *,
        method: str = "GET",
        token: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> _ResponseEvidence:
        selected = dict(headers or {})
        selected["X-Request-Id"] = "gateway-auth-parity-request"
        selected["Origin"] = self._origin
        if method != "OPTIONS":
            selected["X-Workspace-Id"] = LOCAL_WORKSPACE_ID
            selected["Cookie"] = f"datariver_gateway_parity={self._cookie_sentinel}"
        if token is not None:
            if self._log_started_at is None:
                self._log_started_at = datetime.now(UTC).strftime(GATEWAY_LOG_TIMESTAMP_FORMAT)
            selected["Authorization"] = f"Bearer {token}"
            self._sentinels.add(token)
        with httpx.Client(timeout=self._timeout, follow_redirects=False, trust_env=False) as client:
            response = _bounded_response(
                client,
                client.build_request(method, base + path, headers=selected),
            )
        header_evidence = tuple(
            (name, tuple(response.headers.get_list(name))) for name in _SELECTED_RESPONSE_HEADERS
        )
        return _ResponseEvidence(
            response.status_code,
            header_evidence,
            hashlib.sha256(response.content).hexdigest(),
        )

    def verify_status_matrix(self, scenario: str, token: str, expected_status: int) -> None:
        if scenario not in {
            "allow",
            "deny",
            "malformed",
            "expired",
            "membership-revoked",
        }:
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_MATRIX_INVALID")
        for _resource, path in PARITY_RESOURCES:
            evidence = tuple(self._request(base, path, token=token) for base in self._bases)
            if any(item.status != expected_status for item in evidence) or len(set(evidence)) != 1:
                raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_MATRIX_FAILED")

    def verify_cors_and_headers(self, token: str) -> None:
        for _resource, path in PARITY_RESOURCES:
            authenticated = tuple(self._request(base, path, token=token) for base in self._bases)
            if len(set(authenticated)) != 1:
                raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_HEADER_FAILED")
            preflight = tuple(
                self._request(
                    base,
                    path,
                    method="OPTIONS",
                    headers={
                        "Access-Control-Request-Method": "GET",
                        "Access-Control-Request-Headers": (
                            "authorization,x-workspace-id,x-request-id"
                        ),
                    },
                )
                for base in self._bases
            )
            if len(set(preflight)) != 1 or preflight[0].status not in {200, 204}:
                raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_CORS_FAILED")

    def wait_until_expired(self, expires_at: int) -> None:
        delay = expires_at + OIDC_VERIFIER_LEEWAY_SECONDS - int(time.time()) + 1
        if delay < 0 or delay > ACCESS_TOKEN_LIFESPAN_SECONDS + OIDC_VERIFIER_LEEWAY_SECONDS + 2:
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_EXPIRY_INVALID")
        time.sleep(delay)
        if not _genuine_expiry_reached(expires_at=expires_at, observed_at=int(time.time())):
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_EXPIRY_INVALID")

    def require_not_expired(self, expires_at: int) -> None:
        if expires_at <= int(time.time()):
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_MEMBERSHIP_TOKEN_EXPIRED")

    def assert_logs_clean(self, sentinels: tuple[str, ...]) -> None:
        if self._log_started_at is None:
            raise GatewayCredentialLogEvidenceError(evidence_known=False)
        combined = tuple(dict.fromkeys((*sentinels, *sorted(self._sentinels))))
        self._log_checker(self._log_started_at, combined)


class GatewayAuthParitySession:
    def __init__(
        self,
        *,
        identity: GatewayAuthParityIdentity,
        fixture: GatewayAuthParityFixture,
        traffic: GatewayAuthParityTrafficPort,
    ) -> None:
        self._identity = identity
        self._fixture = fixture
        self._traffic = traffic
        self._allow_subject: str | None = None
        self._deny_subject: str | None = None
        self._mutated = False
        self._closed = False
        self._prepared = False
        self._enabled = False
        self._close_outcome: _GatewayAuthParityCloseOutcome | None = None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _exception_type: type[BaseException] | None,
        error: BaseException | None,
        _traceback: object,
    ) -> Literal[False]:
        if error is None:
            self.close()
            return False
        outcome = self._close()
        raise GatewayAuthParityExecutionError(
            first_failure=_first_failure_classification(error),
            log_evidence_failed=outcome.log_evidence_failed,
            log_evidence_known=outcome.log_evidence_known,
            cleanup_required=outcome.cleanup_required,
        ) from None

    def prepare(self) -> None:
        if self._prepared or self._closed:
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_STATE_INVALID")
        self._identity.require_absent_and_capture_invariants()
        self._fixture.require_absent()
        self._mutated = True
        allow_subject, deny_subject = self._identity.create_disabled_fixture()
        self._allow_subject = str(UUID(allow_subject))
        self._deny_subject = str(UUID(deny_subject))
        if self._allow_subject == self._deny_subject:
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_IDENTITY_INVALID")
        self._fixture.prepare(self._allow_subject, self._deny_subject)
        self._prepared = True

    def enable(self) -> None:
        if not self._prepared or self._enabled or self._closed:
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_STATE_INVALID")
        assert self._allow_subject is not None
        assert self._deny_subject is not None
        self._identity.enable_fixture()
        self._fixture.enable(self._allow_subject, self._deny_subject)
        self._enabled = True

    def verify_after_topology(self) -> GatewayAuthParityEvidence:
        if not self._enabled or self._closed:
            raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_STATE_INVALID")
        assert self._allow_subject is not None
        assert self._deny_subject is not None
        allow = self._identity.authenticate_allow()
        self._traffic.verify_status_matrix("allow", allow.value, 200)
        self._traffic.verify_cors_and_headers(allow.value)
        deny = self._identity.authenticate_deny()
        self._traffic.verify_status_matrix("deny", deny.value, 403)
        malformed = "gateway-malformed-token-sentinel"
        self._traffic.verify_status_matrix("malformed", malformed, 401)
        self._traffic.wait_until_expired(allow.expires_at)
        self._traffic.verify_status_matrix("expired", allow.value, 401)
        current_allow = self._identity.authenticate_allow()
        self._traffic.require_not_expired(current_allow.expires_at)
        self._fixture.revoke_allow_membership(self._allow_subject, self._deny_subject)
        self._traffic.require_not_expired(current_allow.expires_at)
        self._traffic.verify_status_matrix("membership-revoked", current_allow.value, 403)
        return GatewayAuthParityEvidence(
            resources=tuple(sorted(resource for resource, _path in PARITY_RESOURCES)),
            hops=PARITY_HOPS,
            statuses=(200, 403, 401, 401, 403),
            immediate_logout="OPEN_UNSUPPORTED",
            retry_count=0,
        )

    def _close(self) -> _GatewayAuthParityCloseOutcome:
        if self._close_outcome is not None:
            return self._close_outcome
        self._closed = True
        if not self._mutated:
            cleanup_required = False
            try:
                self._identity.release_without_mutation()
            except BaseException:
                cleanup_required = True
            self._close_outcome = _GatewayAuthParityCloseOutcome(
                log_evidence_failed=False,
                log_evidence_known=False,
                cleanup_required=cleanup_required,
            )
            return self._close_outcome
        log_evidence_failed = False
        log_evidence_known = False
        try:
            self._traffic.assert_logs_clean(())
            log_evidence_known = True
        except GatewayCredentialLogEvidenceError as error:
            log_evidence_failed = True
            log_evidence_known = error.evidence_known
        except BaseException:
            log_evidence_failed = True
        cleanup_required = False
        try:
            self._identity.cleanup_sessions_and_users()
        except BaseException:
            cleanup_required = True
        if self._allow_subject is not None and self._deny_subject is not None:
            try:
                self._fixture.cleanup(self._allow_subject, self._deny_subject)
            except BaseException:
                cleanup_required = True
        else:
            cleanup_required = True
        try:
            self._identity.cleanup_client()
        except BaseException:
            cleanup_required = True
        try:
            self._identity.require_invariants_and_zero_residual()
        except BaseException:
            cleanup_required = True
        try:
            self._fixture.require_zero_residual()
        except BaseException:
            cleanup_required = True
        self._close_outcome = _GatewayAuthParityCloseOutcome(
            log_evidence_failed=log_evidence_failed,
            log_evidence_known=log_evidence_known,
            cleanup_required=cleanup_required,
        )
        return self._close_outcome

    def close(self) -> None:
        outcome = self._close()
        if not outcome.log_evidence_failed and not outcome.cleanup_required:
            return
        first_failure = (
            "GATEWAY_CREDENTIAL_LOG_PROBE_FAILED"
            if outcome.log_evidence_failed
            else "GATEWAY_AUTH_PARITY_CLEANUP_REQUIRED"
        )
        raise GatewayAuthParityExecutionError(
            first_failure=first_failure,
            log_evidence_failed=outcome.log_evidence_failed,
            log_evidence_known=outcome.log_evidence_known,
            cleanup_required=outcome.cleanup_required,
        ) from None


def run_with_topology(
    session_factory: Callable[[], GatewayAuthParitySession],
    topology_apply: Callable[[], None],
) -> GatewayAuthParityEvidence:
    """Hold one in-memory fixture across the canonical topology transaction."""

    with session_factory() as session:
        session.prepare()
        session.enable()
        topology_apply()
        return session.verify_after_topology()


def main() -> int:
    """Disallow an ad-hoc mutation path; the canonical locked workflow owns execution."""

    print("GATEWAY_AUTH_PARITY_CANONICAL_WORKFLOW_REQUIRED", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
