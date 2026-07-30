from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

_TOKEN_RESPONSE_LIMIT_BYTES = 65_536
_SECRET_LIMIT_BYTES = 16_384
_token: str | None = None
_refresh_at = 0.0


def _required_environment(name: str, *, maximum_length: int) -> str:
    value = os.environ[name]
    if (
        not value
        or value != value.strip()
        or len(value) > maximum_length
        or any(ord(character) < 33 or ord(character) > 126 for character in value)
    ):
        raise RuntimeError(f"{name} is invalid.")
    return value


def _quality_client_secret() -> str:
    raw_path = _required_environment(
        "DATARIVER_QUALITY_DISPATCH_OIDC_CLIENT_SECRET_FILE",
        maximum_length=512,
    )
    path = Path(raw_path)
    try:
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise RuntimeError("The Quality dispatch OIDC secret file is invalid.")
        if not 0 < path.stat().st_size <= _SECRET_LIMIT_BYTES:
            raise RuntimeError("The Quality dispatch OIDC secret file size is invalid.")
        value = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError("The Quality dispatch OIDC secret file cannot be read.") from error
    if not value or len(value.encode("utf-8")) > _SECRET_LIMIT_BYTES:
        raise RuntimeError("The Quality dispatch OIDC client secret is invalid.")
    return value


def _quality_token_url() -> str:
    value = _required_environment(
        "DATARIVER_QUALITY_DISPATCH_OIDC_TOKEN_URL",
        maximum_length=2_048,
    )
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path.startswith("/")
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError(
            "DATARIVER_QUALITY_DISPATCH_OIDC_TOKEN_URL must be one credential-free HTTP(S) URL."
        )
    return value


def quality_service_token() -> str:
    """Return a cached token from the dedicated Quality dispatch client-credentials grant."""
    global _refresh_at, _token

    now = time.monotonic()
    if _token is not None and now < _refresh_at:
        return _token
    payload = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": _required_environment(
                "DATARIVER_QUALITY_DISPATCH_OIDC_CLIENT_ID",
                maximum_length=255,
            ),
            "client_secret": _quality_client_secret(),
        }
    ).encode()
    request = urllib.request.Request(  # noqa: S310 - deployment-owned validated endpoint
        _quality_token_url(),
        method="POST",
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
        raw_document = response.read(_TOKEN_RESPONSE_LIMIT_BYTES + 1)
    if len(raw_document) > _TOKEN_RESPONSE_LIMIT_BYTES:
        raise RuntimeError("The Quality dispatch OIDC token response is too large.")
    try:
        document: object = json.loads(raw_document)
    except (TypeError, ValueError) as error:
        raise RuntimeError("The Quality dispatch OIDC token response is invalid.") from error
    if not isinstance(document, dict):
        raise RuntimeError("The Quality dispatch OIDC token response is invalid.")
    token = document.get("access_token")
    expires_in = document.get("expires_in")
    if not isinstance(token, str) or not token or len(token.encode("utf-8")) > _SECRET_LIMIT_BYTES:
        raise RuntimeError("The Quality dispatch OIDC token response contains no valid token.")
    if (
        isinstance(expires_in, bool)
        or not isinstance(expires_in, (int, float))
        or not 30 <= expires_in <= 86_400
    ):
        raise RuntimeError("The Quality dispatch OIDC token lifetime is invalid.")
    _token = token
    _refresh_at = now + max(1.0, float(expires_in) - 30.0)
    return token


def quality_api_base_url() -> str:
    """Return the deployment-owned DataRiver API origin for Quality dispatch."""
    value = _required_environment(
        "DATARIVER_QUALITY_DISPATCH_API_BASE_URL",
        maximum_length=2_048,
    )
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError(
            "DATARIVER_QUALITY_DISPATCH_API_BASE_URL must be one credential-free HTTP(S) origin."
        )
    return f"{parsed.scheme}://{parsed.netloc}"


def quality_workspace_id() -> str:
    """Return one canonical deployment-owned Workspace UUID."""
    value = _required_environment(
        "DATARIVER_QUALITY_DISPATCH_WORKSPACE_ID",
        maximum_length=36,
    )
    try:
        workspace_id = UUID(value)
    except ValueError as error:
        raise RuntimeError("DATARIVER_QUALITY_DISPATCH_WORKSPACE_ID must be a UUID.") from error
    if str(workspace_id) != value.lower():
        raise RuntimeError("DATARIVER_QUALITY_DISPATCH_WORKSPACE_ID must be canonical.")
    return str(workspace_id)
