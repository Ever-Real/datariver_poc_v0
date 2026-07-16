from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import jwt
from jwt import PyJWKClient

from datariver.application.errors import AuthenticationError
from datariver.domain.authz import AuthenticationAssurance


@dataclass(frozen=True, slots=True)
class VerifiedIdentity:
    issuer: str
    subject: str
    audience: tuple[str, ...]
    authentication_time: datetime | None
    authentication_assurance: AuthenticationAssurance
    acr: str
    amr: frozenset[str]
    claims: dict[str, Any]


class OidcTokenVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_url: str,
        allowed_algorithms: tuple[str, ...],
        hardware_acr_values: tuple[str, ...] = ("2",),
        hardware_amr_values: tuple[str, ...] = ("webauthn", "hwk"),
        password_reauth_acr_values: tuple[str, ...] = ("1",),
        password_amr_values: tuple[str, ...] = ("pwd",),
    ) -> None:
        self._issuer = issuer.rstrip("/")
        self._audience = audience
        self._allowed_algorithms = allowed_algorithms
        self._hardware_acr_values = frozenset(hardware_acr_values)
        self._hardware_amr_values = frozenset(item.lower() for item in hardware_amr_values)
        self._password_reauth_acr_values = frozenset(password_reauth_acr_values)
        self._password_amr_values = frozenset(item.lower() for item in password_amr_values)
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
        authentication_time = None
        if "auth_time" in claims:
            try:
                authentication_time = datetime.fromtimestamp(float(claims["auth_time"]), tz=UTC)
            except (TypeError, ValueError, OSError) as error:
                raise AuthenticationError("The token authentication time is invalid.") from error
        audience_claim = claims["aud"]
        audience = (
            tuple(str(item) for item in audience_claim)
            if isinstance(audience_claim, list)
            else (str(audience_claim),)
        )
        amr_claim = claims.get("amr", [])
        amr = (
            frozenset(
                str(item).strip().lower()
                for item in amr_claim
                if isinstance(item, str) and item.strip()
            )
            if isinstance(amr_claim, list)
            else frozenset()
        )
        acr = str(claims.get("acr", ""))
        if (
            authentication_time is not None
            and acr in self._hardware_acr_values
            and bool(amr & self._hardware_amr_values)
        ):
            assurance = AuthenticationAssurance.HARDWARE_WEBAUTHN
        elif (
            authentication_time is not None
            and acr in self._password_reauth_acr_values
            and bool(amr & self._password_amr_values)
        ):
            assurance = AuthenticationAssurance.PASSWORD_REAUTH
        elif amr & self._password_amr_values:
            assurance = AuthenticationAssurance.PASSWORD
        elif amr:
            assurance = AuthenticationAssurance.OTHER_MFA
        else:
            assurance = AuthenticationAssurance.UNKNOWN
        return VerifiedIdentity(
            issuer=str(claims["iss"]).rstrip("/"),
            subject=str(claims["sub"]),
            audience=audience,
            authentication_time=authentication_time,
            authentication_assurance=assurance,
            acr=acr,
            amr=amr,
            claims=dict(claims),
        )
