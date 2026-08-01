from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from datariver.domain.authz import SERVICE_ONLY_ACTIONS
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


class AllowingRoleReadService:
    async def get_admin_read_context(self, **_: object) -> SimpleNamespace:
        return SimpleNamespace(allowed_operations=("MEMBERSHIP_ACCESS_READ",))


class DenyingRoleReadService:
    async def get_admin_read_context(self, **_: object) -> SimpleNamespace:
        return SimpleNamespace(allowed_operations=())


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


def test_access_role_capability_catalog_is_bounded_and_server_canonical(
    monkeypatch: MonkeyPatch,
) -> None:
    app = FastAPI()
    app.include_router(admin_routes.router)
    app.dependency_overrides[get_request_context] = lambda: SimpleNamespace(
        workspace_id=uuid4(),
        subject=object(),
        environment=object(),
        request_id="role-capability-catalog",
    )
    monkeypatch.setattr(admin_routes, "_service", lambda _: AllowingRoleReadService())

    with TestClient(app) as client:
        response = client.get("/admin/access-roles/capabilities")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    document = response.json()
    assert document["contract_version"] == "ACCESS_ROLE_CAPABILITY_CATALOG_V1"
    assert document["action_count"] == 69
    assert document["human_action_count"] == 64
    assert document["service_action_count"] == 5
    actions = [action for service in document["services"] for action in service["actions"]]
    assert len(actions) == 69
    assert len({action["action"] for action in actions}) == 69
    assert next(action for action in actions if action["action"] == "change.approve") == {
        "action": "change.approve",
        "label": "변경 요청 최종 승인",
        "description": "변경 요청의 최종 승인 결정을 기록합니다.",
        "actor_kind": "HUMAN",
        "assignability": "HUMAN_ROLE",
        "default_admin": True,
        "assurance": "FRESH_PHISHING_RESISTANT",
        "reason_policy": "REQUIRED",
        "self_approval_policy": "CANONICAL_ADMIN_ONLY",
        "self_approval_binding": "PENDING_PROTECTED_BINDING",
        "risk": "HIGH",
    }
    admin_manage = next(action for action in actions if action["action"] == "admin.manage")
    erasure_approve = next(action for action in actions if action["action"] == "erasure.approve")
    assert admin_manage["assignability"] == "HUMAN_ROLE"
    assert admin_manage["self_approval_policy"] == "NOT_APPLICABLE"
    assert erasure_approve["self_approval_policy"] == "NOT_APPLICABLE"


def test_access_role_capability_catalog_requires_membership_read_operation(
    monkeypatch: MonkeyPatch,
) -> None:
    app = FastAPI()
    app.include_router(admin_routes.router)
    app.dependency_overrides[get_request_context] = lambda: SimpleNamespace(
        workspace_id=uuid4(),
        subject=object(),
        environment=object(),
        request_id="role-capability-denied",
    )

    @app.exception_handler(ForbiddenError)
    async def forbidden_handler(_: Request, error: ForbiddenError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": error.message})

    monkeypatch.setattr(admin_routes, "_service", lambda _: DenyingRoleReadService())

    with TestClient(app) as client:
        response = client.get("/admin/access-roles/capabilities")

    assert response.status_code == 403


def test_service_only_role_actions_stop_before_authorization_or_repository_access(
    monkeypatch: MonkeyPatch,
) -> None:
    workspace_id = uuid4()
    service = DenyingRoleMutationService()
    app = FastAPI()
    app.include_router(admin_routes.router)
    app.dependency_overrides[get_request_context] = lambda: SimpleNamespace(
        workspace_id=workspace_id,
        subject=object(),
        environment=object(),
        request_id="role-action-boundary",
    )
    monkeypatch.setattr(admin_routes, "_service", lambda _: service)
    forbidden_payloads = [
        {
            "role_key": "service-role",
            "name": "Service role",
            "clearance": "RESTRICTED",
            "allowed_actions": [action],
        }
        for action in sorted(action.value for action in SERVICE_ONLY_ACTIONS)
    ]

    with TestClient(app) as client:
        responses = [
            client.post("/admin/access-roles", json=payload) for payload in forbidden_payloads
        ]

    assert [response.status_code for response in responses] == [422] * len(SERVICE_ONLY_ACTIONS)
    assert service.role_ids == []
