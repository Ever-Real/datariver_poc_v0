from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import jwt
from jwt import PyJWKClient

from datariver.application.errors import AuthenticationError


@dataclass(frozen=True, slots=True)
class VerifiedIdentity:
    issuer: str
    subject: str
    audience: tuple[str, ...]
    authentication_time: datetime
    strong_authentication: bool
    claims: dict[str, Any]


class OidcTokenVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_url: str,
        allowed_algorithms: tuple[str, ...],
    ) -> None:
        self._issuer = issuer.rstrip("/")
        self._audience = audience
        self._allowed_algorithms = allowed_algorithms
        self._jwks_client = PyJWKClient(jwks_url, cache_keys=True, lifespan=300)

    async def verify(self, token: str) -> VerifiedIdentity:
        try:
            signing_key = await asyncio.to_thread(self._jwks_client.get_signing_key_from_jwt, token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=list(self._allowed_algorithms),
                audience=self._audience,
                issuer=self._issuer,
                leeway=30,
                options={
                    "require": ["exp", "iat", "iss", "sub", "aud"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iat": True,
                    "verify_aud": True,
                    "verify_iss": True,
                },
            )
        except jwt.PyJWTError as error:
            raise AuthenticationError("The access token is invalid.") from error
        authentication_timestamp = claims.get("auth_time", claims["iat"])
        try:
            authentication_time = datetime.fromtimestamp(float(authentication_timestamp), tz=UTC)
        except (TypeError, ValueError, OSError) as error:
            raise AuthenticationError("The token authentication time is invalid.") from error
        audience_claim = claims["aud"]
        audience = (
            tuple(str(item) for item in audience_claim)
            if isinstance(audience_claim, list)
            else (str(audience_claim),)
        )
        amr_claim = claims.get("amr", [])
        amr = amr_claim if isinstance(amr_claim, list) else []
        acr = str(claims.get("acr", ""))
        strong_authentication = any(
            item in {"mfa", "otp", "hwk", "webauthn"} for item in amr
        ) or acr in {"2", "urn:mace:incommon:iap:silver", "phr", "phrh"}
        return VerifiedIdentity(
            issuer=str(claims["iss"]).rstrip("/"),
            subject=str(claims["sub"]),
            audience=audience,
            authentication_time=authentication_time,
            strong_authentication=strong_authentication,
            claims=dict(claims),
        )
