from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from types import TracebackType
from typing import Self, cast
from uuid import UUID, uuid4

import pytest

from datariver.application.dto import IdempotencyRecord
from datariver.application.ports import GovernanceUnitOfWork
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.governance import GovernanceService
from datariver.domain.authz import (
    Action,
    AuthenticationAssurance,
    Classification,
    Decision,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import DomainEvent
from datariver.domain.governance import ChangeItem, ChangeRequest


class MemoryTargetAuthorizer:
    def __init__(self) -> None:
        self.calls = 0

    async def authorize_targets(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        items: Sequence[ChangeItem],
        request_classification: Classification,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> None:
        del workspace_id, subject, items, request_classification, environment, request_id
        self.calls += 1


class MemoryDecisionWriter:
    def __init__(self) -> None:
        self.decisions: list[Decision] = []

    async def append_decision(
        self,
        *,
        decision: Decision,
        subject_id: UUID,
        workspace_id: UUID,
        resource_id: UUID,
        action: str,
        request_id: str,
    ) -> None:
        del subject_id, workspace_id, resource_id, action, request_id
        self.decisions.append(decision)


class MemoryChangeRequests:
    def __init__(self, values: dict[UUID, ChangeRequest]) -> None:
        self.values = values

    async def add(self, change_request: ChangeRequest) -> None:
        self.values[change_request.change_request_id] = change_request

    async def get_for_update(
        self, *, workspace_id: UUID, change_request_id: UUID
    ) -> ChangeRequest | None:
        value = self.values.get(change_request_id)
        return value if value and value.workspace_id == workspace_id else None

    async def save(self, change_request: ChangeRequest) -> None:
        self.values[change_request.change_request_id] = change_request


class MemoryOutbox:
    def __init__(self, values: list[DomainEvent]) -> None:
        self.values = values

    async def add_events(self, events: list[DomainEvent]) -> None:
        self.values.extend(events)


class MemoryIdempotency:
    def __init__(self, values: dict[tuple[UUID, str, str], IdempotencyRecord]) -> None:
        self.values = values

    async def get_result(
        self, *, workspace_id: UUID, key: str, operation: str
    ) -> IdempotencyRecord | None:
        return self.values.get((workspace_id, key, operation))

    async def save_result(
        self,
        *,
        workspace_id: UUID,
        key: str,
        operation: str,
        request_hash: str,
        result: dict[str, object],
    ) -> None:
        self.values[(workspace_id, key, operation)] = IdempotencyRecord(
            request_hash=request_hash, result=result
        )


class MemoryUnitOfWork:
    def __init__(self, state: dict[str, object]) -> None:
        self.change_requests = MemoryChangeRequests(state["requests"])  # type: ignore[arg-type]
        self.outbox = MemoryOutbox(state["outbox"])  # type: ignore[arg-type]
        self.idempotency = MemoryIdempotency(state["idempotency"])  # type: ignore[arg-type]
        self.committed = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.committed = False

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None:
        del workspace_id, subject_id


def subject(workspace_id: UUID) -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=uuid4(),
        groups=frozenset({"stewards"}),
        job_function="DATA_STEWARD",
        clearance=Classification.CONFIDENTIAL,
        allowed_actions=frozenset({Action.CHANGE_CREATE}),
        authentication_time=datetime.now(UTC),
        authentication_assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
    )


@pytest.mark.asyncio
async def test_create_is_idempotent_and_writes_one_outbox_event() -> None:
    workspace_id = uuid4()
    actor = subject(workspace_id)
    state: dict[str, object] = {"requests": {}, "outbox": [], "idempotency": {}}
    writer = MemoryDecisionWriter()
    uow_factory = cast(Callable[[], GovernanceUnitOfWork], lambda: MemoryUnitOfWork(state))
    target_authorizer = MemoryTargetAuthorizer()
    service = GovernanceService(
        uow_factory,
        AuthorizationService(decision_writer=writer),
        target_authorizer=target_authorizer,
    )
    arguments = {
        "workspace_id": workspace_id,
        "number": "CR-1",
        "request_type": "CATALOG_METADATA",
        "title": "Update",
        "description": "Description",
        "requester_id": actor.subject_id,
        "items": [
            ChangeItem(
                uuid4(),
                "DATAHUB_ASPECT",
                "urn:li:dataset:x",
                "UPSERT",
                {"name": "x"},
                "datasetProperties",
                "b" * 64,
            )
        ],
        "subject": actor,
        "classification": Classification.INTERNAL,
        "environment": EnvironmentAttributes(requested_at=datetime.now(UTC)),
        "request_id": "request-1",
        "idempotency_key": "idempotency-key-0001",
        "request_hash": "a" * 64,
    }

    first = await service.create_change_request(**arguments)  # type: ignore[arg-type]
    second = await service.create_change_request(**arguments)  # type: ignore[arg-type]

    assert first.change_request_id == second.change_request_id
    assert len(state["requests"]) == 1  # type: ignore[arg-type]
    assert len(state["outbox"]) == 1  # type: ignore[arg-type]
    assert len(writer.decisions) == 2
    assert target_authorizer.calls == 2
