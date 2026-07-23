from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from datariver.application.dto import SystemAssigneePage, SystemDirectoryAssignee
from datariver.domain.admin_access import (
    SystemAssigneeKey,
    SystemAssigneePatchCommand,
    SystemAssigneeUpdate,
)
from datariver.domain.common import ValidationError
from datariver.interfaces.http.dependencies import get_request_context
from datariver.interfaces.http.routes import admin as admin_routes


def _upsert(
    *,
    subject_id: UUID | None = None,
    responsibility: str = "DEVELOPER",
    priority: int = 1,
) -> SystemAssigneeUpdate:
    return SystemAssigneeUpdate(
        subject_id=subject_id or uuid4(),
        responsibility=responsibility,
        priority=priority,
    )


def _removal(
    *,
    subject_id: UUID | None = None,
    responsibility: str = "DEVELOPER",
) -> SystemAssigneeKey:
    return SystemAssigneeKey(
        subject_id=subject_id or uuid4(),
        responsibility=responsibility,
    )


def _command(
    *,
    upserts: tuple[SystemAssigneeUpdate, ...] = (),
    removals: tuple[SystemAssigneeKey, ...] = (),
) -> SystemAssigneePatchCommand:
    return SystemAssigneePatchCommand(
        workspace_id=uuid4(),
        system_id=uuid4(),
        expected_system_version=1,
        upserts=upserts,
        removals=removals,
    )


def test_system_assignee_patch_rejects_an_empty_change_set() -> None:
    with pytest.raises(ValidationError, match="cannot be empty"):
        _command()


def test_system_assignee_patch_rejects_more_than_one_hundred_total_changes() -> None:
    with pytest.raises(ValidationError, match="limited to 100 changes"):
        _command(
            upserts=tuple(_upsert() for _ in range(51)),
            removals=tuple(_removal() for _ in range(50)),
        )


@pytest.mark.parametrize("duplicate_kind", ["upsert", "removal"])
def test_system_assignee_patch_rejects_duplicate_keys(duplicate_kind: str) -> None:
    subject_id = uuid4()
    upserts: tuple[SystemAssigneeUpdate, ...]
    removals: tuple[SystemAssigneeKey, ...]
    if duplicate_kind == "upsert":
        upserts = (
            _upsert(subject_id=subject_id, priority=1),
            _upsert(subject_id=subject_id, priority=2),
        )
        removals = ()
    else:
        upserts = ()
        removals = (
            _removal(subject_id=subject_id),
            _removal(subject_id=subject_id),
        )

    with pytest.raises(ValidationError, match="duplicate responsibility"):
        _command(upserts=upserts, removals=removals)


def test_system_assignee_patch_rejects_an_overlapping_upsert_and_removal() -> None:
    subject_id = uuid4()

    with pytest.raises(ValidationError, match="update and remove the same entry"):
        _command(
            upserts=(_upsert(subject_id=subject_id),),
            removals=(_removal(subject_id=subject_id),),
        )


def test_system_assignee_patch_hash_is_independent_of_input_order() -> None:
    first_subject, second_subject = uuid4(), uuid4()
    workspace_id, system_id = uuid4(), uuid4()
    first = SystemAssigneePatchCommand(
        workspace_id=workspace_id,
        system_id=system_id,
        expected_system_version=7,
        upserts=(
            _upsert(subject_id=second_subject, responsibility="DATA_STEWARD", priority=2),
            _upsert(subject_id=first_subject, priority=1),
        ),
        removals=(),
    )
    reordered = SystemAssigneePatchCommand(
        workspace_id=workspace_id,
        system_id=system_id,
        expected_system_version=7,
        upserts=tuple(reversed(first.upserts)),
        removals=(),
    )

    assert first.command_document() == reordered.command_document()
    assert first.payload_hash == reordered.payload_hash


class _SystemAssigneeRouteService:
    def __init__(self, *, subject_id: UUID) -> None:
        self.subject_id = subject_id
        self.list_calls: list[dict[str, object]] = []
        self.patch_calls: list[dict[str, object]] = []

    async def list_system_assignees(self, **values: object) -> SystemAssigneePage:
        self.list_calls.append(values)
        return SystemAssigneePage(
            items=(
                SystemDirectoryAssignee(
                    subject_id=self.subject_id,
                    display_name="Developer",
                    responsibility="DEVELOPER",
                    priority=1,
                    active=True,
                ),
            ),
            system_version=3,
            next_cursor="opaque-next",
        )

    async def patch_system_assignees_with_hardware_key(self, **values: object) -> int:
        self.patch_calls.append(values)
        return 4


def _route_app(
    monkeypatch: MonkeyPatch,
    *,
    workspace_id: UUID,
    service: _SystemAssigneeRouteService,
) -> FastAPI:
    app = FastAPI()
    app.include_router(admin_routes.router)
    app.dependency_overrides[get_request_context] = lambda: SimpleNamespace(
        workspace_id=workspace_id,
        subject=object(),
        environment=object(),
        request_id="system-assignee-route",
    )

    @app.exception_handler(ValidationError)
    async def validation_handler(_: Request, error: ValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": error.message})

    monkeypatch.setattr(admin_routes, "_service", lambda _: service)
    return app


def test_system_assignee_get_and_patch_routes_preserve_page_and_version_contract(
    monkeypatch: MonkeyPatch,
) -> None:
    workspace_id, system_id, subject_id = uuid4(), uuid4(), uuid4()
    service = _SystemAssigneeRouteService(subject_id=subject_id)
    app = _route_app(monkeypatch, workspace_id=workspace_id, service=service)
    patch_document = {
        "upserts": [
            {
                "subject_id": str(subject_id),
                "responsibility": "DEVELOPER",
                "priority": 2,
            }
        ],
        "removals": [],
    }

    with TestClient(app) as client:
        listed = client.get(f"/admin/systems/{system_id}/assignees?limit=25")
        patched = client.patch(
            f"/admin/systems/{system_id}/assignees",
            json=patch_document,
            headers={
                "If-Match": '"3"',
                "Idempotency-Key": "system-assignee-route-idempotency",
            },
        )

    assert listed.status_code == 200
    assert listed.json() == {
        "system_version": 3,
        "items": [
            {
                "subject_id": str(subject_id),
                "display_name": "Developer",
                "responsibility": "DEVELOPER",
                "priority": 1,
                "active": True,
            }
        ],
        "page": {"next_cursor": "opaque-next", "limit": 25},
    }
    assert len(service.list_calls) == 1
    assert service.list_calls[0]["workspace_id"] == workspace_id
    assert service.list_calls[0]["system_id"] == system_id
    assert service.list_calls[0]["limit"] == 25
    assert service.list_calls[0]["cursor"] is None
    assert service.list_calls[0]["request_id"] == "system-assignee-route"
    assert patched.status_code == 200
    assert patched.headers["ETag"] == '"4"'
    assert patched.json()["system_version"] == 4
    command = service.patch_calls[0]["command"]
    assert isinstance(command, SystemAssigneePatchCommand)
    assert patched.json()["payload_hash"] == command.payload_hash
    assert command.expected_system_version == 3
    assert command.upserts[0].priority == 2
    assert service.patch_calls[0]["idempotency_key"] == ("system-assignee-route-idempotency")
    assert isinstance(service.patch_calls[0]["request_hash"], str)
    assert len(service.patch_calls[0]["request_hash"]) == 64


@pytest.mark.parametrize("shape", ["empty", "overlap", "too_many"])
def test_system_assignee_patch_route_rejects_invalid_delta_documents(
    monkeypatch: MonkeyPatch,
    shape: str,
) -> None:
    workspace_id, system_id, subject_id = uuid4(), uuid4(), uuid4()
    service = _SystemAssigneeRouteService(subject_id=subject_id)
    app = _route_app(monkeypatch, workspace_id=workspace_id, service=service)
    if shape == "empty":
        document: dict[str, Any] = {"upserts": [], "removals": []}
    elif shape == "overlap":
        document = {
            "upserts": [
                {
                    "subject_id": str(subject_id),
                    "responsibility": "DEVELOPER",
                    "priority": 1,
                }
            ],
            "removals": [
                {
                    "subject_id": str(subject_id),
                    "responsibility": "DEVELOPER",
                }
            ],
        }
    else:
        document = {
            "upserts": [
                {
                    "subject_id": str(uuid4()),
                    "responsibility": "DEVELOPER",
                    "priority": 1,
                }
                for _ in range(51)
            ],
            "removals": [
                {
                    "subject_id": str(uuid4()),
                    "responsibility": "DATA_STEWARD",
                }
                for _ in range(50)
            ],
        }

    with TestClient(app) as client:
        response = client.patch(
            f"/admin/systems/{system_id}/assignees",
            json=document,
            headers={
                "If-Match": '"3"',
                "Idempotency-Key": "system-assignee-route-idempotency",
            },
        )

    assert response.status_code == 422
    assert service.patch_calls == []
