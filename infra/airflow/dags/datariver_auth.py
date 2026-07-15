from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from urllib.parse import urlsplit

_token: str | None = None
_refresh_at = 0.0


def service_token() -> str:
    """Return a short-lived client-credentials token, refreshing before expiry."""
    global _refresh_at, _token
    now = time.monotonic()
    if _token is not None and now < _refresh_at:
        return _token
    secret_path = os.environ["DATARIVER_OIDC_CLIENT_SECRET_FILE"]
    with open(secret_path, encoding="utf-8") as secret_file:
        client_secret = secret_file.read().strip()
    payload = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": os.environ["DATARIVER_OIDC_CLIENT_ID"],
            "client_secret": client_secret,
        }
    ).encode()
    token_url = os.environ["DATARIVER_OIDC_TOKEN_URL"]
    if urlsplit(token_url).scheme not in {"http", "https"}:
        raise RuntimeError("The OIDC token endpoint must use HTTP or HTTPS.")
    request = urllib.request.Request(  # noqa: S310
        token_url,
        method="POST",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
        document = json.load(response)
    token = document.get("access_token")
    expires_in = document.get("expires_in", 300)
    if not isinstance(token, str) or not token:
        raise RuntimeError("The OIDC token endpoint returned no access token.")
    if not isinstance(expires_in, (int, float)) or expires_in < 30:
        raise RuntimeError("The OIDC access-token lifetime is invalid.")
    _token = token
    _refresh_at = now + max(1.0, float(expires_in) - 30.0)
    return token
