from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from datariver.domain.common import ForbiddenError
from datariver.interfaces.http.dependencies import get_request_context
from datariver.interfaces.http.routes import admin as admin_routes


class DenyingRoleMutationService:
    def __init__(self) -> None:
        self.role_ids: list[UUID] = []

    async def authorize_access_role_mutation(self, **values: object) -> UUID:
        role_id = values["role_id"]
        assert isinstance(role_id, UUID)
        self.role_ids.append(role_id)
        raise ForbiddenError("fresh hardware authentication required")


def test_access_role_write_routes_require_high_risk_authorization_before_database_access(
    monkeypatch: MonkeyPatch,
) -> None:
    workspace_id, role_id = uuid4(), uuid4()
    service = DenyingRoleMutationService()
    app = FastAPI()
    app.include_router(admin_routes.router)
    app.dependency_overrides[get_request_context] = lambda: SimpleNamespace(
        workspace_id=workspace_id,
        subject=object(),
        environment=object(),
        request_id="role-route-high-risk",
    )

    @app.exception_handler(ForbiddenError)
    async def forbidden_handler(_: Request, error: ForbiddenError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": error.message})

    monkeypatch.setattr(admin_routes, "_service", lambda _: service)
    payload = {
        "role_key": "catalog-reader",
        "name": "Catalog reader",
        "clearance": "INTERNAL",
        "allowed_actions": ["catalog.read"],
    }

    with TestClient(app) as client:
        create = client.post("/admin/access-roles", json=payload)
        update = client.put(
            f"/admin/access-roles/{role_id}",
            json=payload,
            headers={"If-Match": '"1"'},
        )
        deactivate = client.delete(f"/admin/access-roles/{role_id}", headers={"If-Match": '"1"'})

    assert [create.status_code, update.status_code, deactivate.status_code] == [403, 403, 403]
    assert service.role_ids == [workspace_id, role_id, role_id]
