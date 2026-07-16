from __future__ import annotations

import ipaddress
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated, cast
from uuid import UUID

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.errors import AuthenticationError
from datariver.domain.authz import EnvironmentAttributes, SubjectAttributes
from datariver.domain.common import utc_now
from datariver.infrastructure.db.authz import SqlSubjectReader, with_authentication_context
from datariver.infrastructure.db.rls import set_security_context
from datariver.infrastructure.security.oidc import VerifiedIdentity
from datariver.interfaces.http.container import AppContainer

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class RequestContext:
    request_id: str
    workspace_id: UUID
    identity: VerifiedIdentity
    subject: SubjectAttributes
    environment: EnvironmentAttributes


def get_container(request: Request) -> AppContainer:
    return cast(AppContainer, request.app.state.container)


def _network_zone(request: Request) -> str:
    host = request.client.host if request.client else "unknown"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return "unknown"
    if address.is_loopback:
        return "loopback"
    if address.is_private:
        return "private"
    return "public"


async def get_request_context(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    workspace_id: Annotated[UUID, Header(alias="X-Workspace-Id")],
    purpose: Annotated[str | None, Header(alias="X-Purpose")] = None,
) -> RequestContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("A bearer access token is required.")
    container = get_container(request)
    identity = await container.oidc.verify(credentials.credentials)
    async with container.database.session_factory() as session:
        await set_security_context(session, workspace_id=workspace_id, subject_id=None)
        subject = await SqlSubjectReader(session).get_subject(
            issuer=identity.issuer,
            external_subject=identity.subject,
            workspace_id=workspace_id,
        )
    subject = with_authentication_context(
        subject,
        authentication_time=identity.authentication_time,
        authentication_assurance=identity.authentication_assurance,
    )
    return RequestContext(
        request_id=request.state.request_id,
        workspace_id=workspace_id,
        identity=identity,
        subject=subject,
        environment=EnvironmentAttributes(
            requested_at=utc_now(),
            purpose=purpose,
            network_zone=_network_zone(request),
            client_type="browser" if "text/html" in request.headers.get("accept", "") else "api",
            maximum_authentication_age=timedelta(
                seconds=container.settings.high_risk_auth_max_age_seconds
            ),
        ),
    )


async def get_session(
    request: Request,
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> AsyncIterator[AsyncSession]:
    container = get_container(request)
    async with container.database.session_factory() as session:
        await set_security_context(
            session,
            workspace_id=context.workspace_id,
            subject_id=context.subject.subject_id,
        )
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
ContextDep = Annotated[RequestContext, Depends(get_request_context)]
