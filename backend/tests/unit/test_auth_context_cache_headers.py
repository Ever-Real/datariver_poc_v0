from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import Request
from starlette.responses import Response

from datariver.infrastructure.security.oidc import VerifiedIdentity
from datariver.interfaces.http.dependencies import RequestContext
from datariver.interfaces.http.routes import admin, auth


@pytest.mark.asyncio
async def test_auth_profile_success_is_private_and_never_cacheable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Session:
        commit = AsyncMock()

    @asynccontextmanager
    async def session_factory() -> AsyncIterator[Session]:
        yield Session()

    reader = SimpleNamespace(
        get_default_workspace_id=AsyncMock(return_value=UUID(int=1)),
        record_authenticated_profile=AsyncMock(),
    )
    monkeypatch.setattr(auth, "SqlSubjectReader", lambda _session: reader)
    request = cast(
        Request,
        SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    container=SimpleNamespace(
                        database=SimpleNamespace(session_factory=session_factory),
                        settings=SimpleNamespace(
                            workspace_selection_enabled=True,
                            oidc_hardware_webauthn_enabled=True,
                            identity_password_change_action_enabled=True,
                        ),
                    ),
                )
            ),
            client=SimpleNamespace(host="127.0.0.1"),
        ),
    )
    identity = cast(
        VerifiedIdentity,
        SimpleNamespace(
            claims={"name": "Administrator", "realm_access": {"roles": ["administrator"]}},
            issuer="https://issuer.example.test",
            subject="external-subject",
            authentication_assurance=SimpleNamespace(value="PASSWORD"),
            authentication_time=datetime(2026, 7, 23, tzinfo=UTC),
        ),
    )
    response = Response()

    result = await auth.get_authenticated_profile(
        request=request,
        response=response,
        identity=identity,
    )

    assert result.subject == "external-subject"
    assert response.headers["Cache-Control"] == "private, no-store"


@pytest.mark.asyncio
async def test_admin_context_success_is_private_and_never_cacheable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = object()
    service = SimpleNamespace(get_admin_read_context=AsyncMock(return_value=value))
    monkeypatch.setattr(admin, "_service", lambda _request: service)
    monkeypatch.setattr(admin, "admin_read_context_response", lambda context: context)
    response = Response()
    context = cast(
        RequestContext,
        SimpleNamespace(
            workspace_id=UUID(int=1),
            subject=object(),
            environment=object(),
            request_id="request-one",
        ),
    )

    result = await admin.get_admin_context(
        request=cast(Request, object()),
        response=response,
        context=context,
    )

    assert result is value
    assert response.headers["Cache-Control"] == "private, no-store"
