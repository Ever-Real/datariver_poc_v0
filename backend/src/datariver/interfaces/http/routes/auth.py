from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from fastapi import APIRouter, Request

from datariver.infrastructure.db.authz import SqlSubjectReader
from datariver.interfaces.http.dependencies import AuthenticatedIdentityDep, get_container
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
async def get_authenticated_profile(
    request: Request, identity: AuthenticatedIdentityDep
) -> AuthMeResponse:
    """Hydrate browser memory from a freshly verified OIDC access token."""
    claims = identity.claims
    name = claims.get("name") or claims.get("preferred_username") or identity.subject
    email = claims.get("email")
    container = get_container(request)
    async with container.database.session_factory() as session:
        reader = SqlSubjectReader(session)
        default_workspace_id = await reader.get_default_workspace_id(
            issuer=identity.issuer,
            external_subject=identity.subject,
        )
        source_ip = request.client.host if request.client else None
        await reader.record_authenticated_profile(
            issuer=identity.issuer,
            external_subject=identity.subject,
            email=str(email) if isinstance(email, str) else None,
            source_ip=source_ip[:64] if source_ip else None,
            observed_at=datetime.now(UTC),
        )
        await session.commit()
    return AuthMeResponse(
        subject=identity.subject,
        display_name=str(name),
        email=str(email) if isinstance(email, str) else None,
        roles=_roles(claims.get("realm_access")),
        authentication_assurance=identity.authentication_assurance.value,
        authentication_time=identity.authentication_time,
        default_workspace_id=default_workspace_id,
    )
