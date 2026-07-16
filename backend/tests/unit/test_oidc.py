from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import jwt
import pytest

from datariver.application.errors import AuthenticationError
from datariver.domain.authz import AuthenticationAssurance
from datariver.infrastructure.security.oidc import OidcTokenVerifier

SECRET = "test-signing-key-with-at-least-32-bytes"
ISSUER = "https://identity.example/realms/datariver"
AUDIENCE = "datariver-api"


class StaticSigningKeyClient:
    def get_signing_key_from_jwt(self, _: str) -> SimpleNamespace:
        return SimpleNamespace(key=SECRET)


def verifier() -> OidcTokenVerifier:
    instance = OidcTokenVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        jwks_url=f"{ISSUER}/protocol/openid-connect/certs",
        allowed_algorithms=("HS256",),
        hardware_acr_values=("hardware",),
        hardware_amr_values=("webauthn", "hwk"),
        password_reauth_acr_values=("password-reauth",),
        password_amr_values=("pwd",),
    )
    instance._jwks_client = cast(Any, StaticSigningKeyClient())
    return instance


def token(*, acr: str, amr: list[str], auth_time: object = ...) -> str:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "iss": ISSUER,
        "sub": "user-one",
        "aud": AUDIENCE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "acr": acr,
        "amr": amr,
    }
    if auth_time is ...:
        claims["auth_time"] = int((now - timedelta(seconds=5)).timestamp())
    elif auth_time is not None:
        claims["auth_time"] = auth_time
    return jwt.encode(claims, SECRET, algorithm="HS256")


async def test_exact_acr_amr_and_auth_time_produce_hardware_assurance() -> None:
    identity = await verifier().verify(token(acr="hardware", amr=["pwd", "webauthn"]))

    assert identity.authentication_assurance is AuthenticationAssurance.HARDWARE_WEBAUTHN
    assert identity.authentication_time is not None
    assert identity.acr == "hardware"
    assert identity.amr == frozenset({"pwd", "webauthn"})


@pytest.mark.parametrize(
    ("acr", "amr", "expected"),
    [
        ("hardware", ["otp", "mfa"], AuthenticationAssurance.OTHER_MFA),
        ("untrusted", ["webauthn"], AuthenticationAssurance.OTHER_MFA),
        ("password-reauth", ["pwd"], AuthenticationAssurance.PASSWORD_REAUTH),
    ],
)
async def test_assurance_requires_an_exact_trusted_claim_combination(
    acr: str,
    amr: list[str],
    expected: AuthenticationAssurance,
) -> None:
    identity = await verifier().verify(token(acr=acr, amr=amr))

    assert identity.authentication_assurance is expected


async def test_recent_iat_never_replaces_missing_authentication_time() -> None:
    identity = await verifier().verify(token(acr="hardware", amr=["webauthn"], auth_time=None))

    assert identity.authentication_time is None
    assert identity.authentication_assurance is AuthenticationAssurance.OTHER_MFA


async def test_invalid_authentication_time_is_rejected() -> None:
    with pytest.raises(AuthenticationError, match="authentication time"):
        await verifier().verify(token(acr="hardware", amr=["webauthn"], auth_time="invalid"))
