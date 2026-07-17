from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
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
from datariver.domain.common import DomainEvent, ForbiddenError
from datariver.domain.governance import (
    ChangeItem,
    ChangeRequest,
    change_target_binding_hash,
)


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
    ) -> tuple[ChangeItem, ...]:
        del subject, environment, request_id
        self.calls += 1
        asset_id = uuid4()
        return tuple(
            replace(
                item,
                target_asset_id=asset_id,
                target_asset_type="DATASET",
                target_classification=request_classification,
                target_lifecycle="ACTIVE",
                target_source_version="1",
                target_observed_at=datetime.now(UTC),
                target_binding_hash=change_target_binding_hash(
                    target_ref=item.target_ref,
                    asset_id=asset_id,
                    asset_type="DATASET",
                    system_id=None,
                    domain_id=None,
                    owner_department_id=None,
                    classification=request_classification,
                    lifecycle="ACTIVE",
                ),
            )
            for item in items
        )

    async def filter_authorized_change_requests(
        self, *, change_requests: Sequence[ChangeRequest], **_: object
    ) -> tuple[ChangeRequest, ...]:
        return tuple(change_requests)


class MemoryDecisionWriter:
    def __init__(self) -> None:
        self.decisions: list[Decision] = []
        self.actions: list[str] = []

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
        del subject_id, workspace_id, resource_id, request_id
        self.decisions.append(decision)
        self.actions.append(action)


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
        "require_raw_operator_gate": False,
    }

    first = await service.create_change_request(**arguments)  # type: ignore[arg-type]
    second = await service.create_change_request(**arguments)  # type: ignore[arg-type]

    assert first.change_request_id == second.change_request_id
    assert len(state["requests"]) == 1  # type: ignore[arg-type]
    assert len(state["outbox"]) == 1  # type: ignore[arg-type]
    assert len(writer.decisions) == 2
    assert target_authorizer.calls == 2


@pytest.mark.asyncio
async def test_raw_creation_requires_explicit_hardware_human_operator_before_target_access() -> (
    None
):
    workspace_id = uuid4()
    base_actor = subject(workspace_id)
    traces: list[tuple[dict[str, object], MemoryDecisionWriter, MemoryTargetAuthorizer]] = []

    async def attempt(
        *, actor: SubjectAttributes, suffix: str
    ) -> tuple[
        ChangeRequest | None,
        dict[str, object],
        MemoryDecisionWriter,
        MemoryTargetAuthorizer,
    ]:
        state: dict[str, object] = {"requests": {}, "outbox": [], "idempotency": {}}
        writer = MemoryDecisionWriter()
        target_authorizer = MemoryTargetAuthorizer()
        traces.append((state, writer, target_authorizer))
        service = GovernanceService(
            cast(Callable[[], GovernanceUnitOfWork], lambda: MemoryUnitOfWork(state)),
            AuthorizationService(decision_writer=writer),
            target_authorizer=target_authorizer,
        )
        result = await service.create_change_request(
            workspace_id=workspace_id,
            number=f"CR-RAW-{suffix}",
            request_type="CATALOG_METADATA",
            title="Raw update",
            description="Operator controlled raw provider update",
            requester_id=actor.subject_id,
            items=[
                ChangeItem(
                    uuid4(),
                    "DATAHUB_ASPECT",
                    "urn:li:dataset:raw",
                    "UPSERT",
                    {"name": "raw"},
                    "datasetProperties",
                    "b" * 64,
                )
            ],
            subject=actor,
            classification=Classification.INTERNAL,
            environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
            request_id=f"request-raw-{suffix}",
            idempotency_key=f"idempotency-raw-{suffix}-0001",
            request_hash="c" * 64,
        )
        return result, state, writer, target_authorizer

    with pytest.raises(ForbiddenError):
        await attempt(actor=base_actor, suffix="missing-action")
    denied_state, denied_writer, denied_target_authorizer = traces[-1]
    assert denied_writer.actions == [Action.CHANGE_RAW_CREATE.value]
    assert denied_target_authorizer.calls == 0
    assert denied_state["requests"] == {}

    allowed_actor = replace(
        base_actor,
        allowed_actions=frozenset({Action.CHANGE_CREATE, Action.CHANGE_RAW_CREATE}),
    )
    result, state, writer, target_authorizer = await attempt(
        actor=allowed_actor, suffix="hardware-human"
    )
    assert result is not None
    assert len(state["requests"]) == 1  # type: ignore[arg-type]
    assert writer.actions == [Action.CHANGE_RAW_CREATE.value, Action.CHANGE_CREATE.value]
    assert target_authorizer.calls == 1

    service_actor = replace(
        allowed_actor,
        subject_id=uuid4(),
        groups=frozenset({"stewards", "service-accounts"}),
        job_function="SERVICE_ACCOUNT",
    )
    with pytest.raises(ForbiddenError):
        await attempt(actor=service_actor, suffix="service-account")
    service_state, service_writer, service_target_authorizer = traces[-1]
    assert service_writer.actions == [Action.CHANGE_RAW_CREATE.value]
    assert service_writer.decisions[0].reason_codes == ("HUMAN_ACTOR_REQUIRED",)
    assert service_target_authorizer.calls == 0
    assert service_state["requests"] == {}
