from __future__ import annotations

from collections.abc import Iterable

from fastapi import APIRouter

from datariver.interfaces.http.dependencies import AuthenticatedIdentityDep
from datariver.interfaces.http.schemas import AuthMeResponse

router = APIRouter(prefix="/auth", tags=["authentication"])


def _roles(value: object) -> list[str]:
    if not isinstance(value, dict):
        return []
    candidates = value.get("roles")
    if not isinstance(candidates, Iterable) or isinstance(candidates, (str, bytes)):
        return []
    return sorted({item.strip() for item in candidates if isinstance(item, str) and item.strip()})


@router.get("/me", response_model=AuthMeResponse)
async def get_authenticated_profile(identity: AuthenticatedIdentityDep) -> AuthMeResponse:
    """Hydrate browser memory from a freshly verified OIDC access token."""
    claims = identity.claims
    name = claims.get("name") or claims.get("preferred_username") or identity.subject
    email = claims.get("email")
    return AuthMeResponse(
        subject=identity.subject,
        display_name=str(name),
        email=str(email) if isinstance(email, str) else None,
        roles=_roles(claims.get("realm_access")),
        authentication_assurance=identity.authentication_assurance.value,
        authentication_time=identity.authentication_time,
    )
