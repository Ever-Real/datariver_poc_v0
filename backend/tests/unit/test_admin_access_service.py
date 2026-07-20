from __future__ import annotations

from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self, cast
from uuid import UUID, uuid4

import pytest

from datariver.application.dto import (
    IdempotencyRecord,
    SystemDirectoryAssignee,
    SystemDirectoryEntry,
    WorkspaceMembershipAccessRecord,
    WorkspaceMembershipSummary,
)
from datariver.application.ports import AdminAccessUnitOfWork
from datariver.application.services.admin_access import AdminAccessService
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.admin_access import (
    AdminAccessDecision,
    AdminAccessRequest,
    AdminAccessRequestState,
    AdminOperation,
    MembershipAccessUpdate,
    SystemAssigneeUpdate,
    SystemAssigneeUpdateCommand,
)
from datariver.domain.authz import (
    Action,
    AuthenticationAssurance,
    Classification,
    Decision,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import (
    ConflictError,
    DomainEvent,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)


class MemoryDecisionWriter:
    def __init__(self) -> None:
        self.decisions: list[tuple[str, Decision]] = []

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
        self.decisions.append((action, decision))


class MemoryRequests:
    def __init__(self, values: dict[UUID, AdminAccessRequest]) -> None:
        self.values = values

    async def add(self, request: AdminAccessRequest) -> None:
        self.values[request.access_request_id] = request

    async def get_for_update(
        self, *, workspace_id: UUID, access_request_id: UUID
    ) -> AdminAccessRequest | None:
        value = self.values.get(access_request_id)
        return value if value is not None and value.workspace_id == workspace_id else None

    async def get(
        self, *, workspace_id: UUID, access_request_id: UUID
    ) -> AdminAccessRequest | None:
        return await self.get_for_update(
            workspace_id=workspace_id, access_request_id=access_request_id
        )

    async def list(
        self, *, workspace_id: UUID, state: str | None, limit: int
    ) -> Sequence[AdminAccessRequest]:
        return tuple(
            value
            for value in self.values.values()
            if value.workspace_id == workspace_id and (state is None or value.state.value == state)
        )[:limit]

    async def save(self, request: AdminAccessRequest) -> None:
        self.values[request.access_request_id] = request


class MemoryMemberships:
    def __init__(self, state: dict[str, object]) -> None:
        self.state = state

    async def list(self, *, workspace_id: UUID, limit: int) -> Sequence[WorkspaceMembershipSummary]:
        assert workspace_id == self.state["workspace_id"]
        self.state["membership_read_count"] = cast(int, self.state["membership_read_count"]) + 1
        records = cast(
            dict[UUID, WorkspaceMembershipAccessRecord], self.state["membership_records"]
        )
        return tuple(
            record.summary
            for record in sorted(records.values(), key=lambda value: value.summary.display_name)
        )[:limit]

    async def get_access(
        self, *, workspace_id: UUID, subject_id: UUID
    ) -> WorkspaceMembershipAccessRecord | None:
        assert workspace_id == self.state["workspace_id"]
        self.state["membership_read_count"] = cast(int, self.state["membership_read_count"]) + 1
        records = cast(
            dict[UUID, WorkspaceMembershipAccessRecord], self.state["membership_records"]
        )
        return records.get(subject_id)

    async def apply(self, command: MembershipAccessUpdate) -> int:
        await self.assert_current_version(command)
        versions = cast(dict[UUID, int], self.state["membership_versions"])
        actual = versions[command.target_subject_id]
        if cast(int, self.state["remaining_admin_count"]) < 2:
            raise ConflictError("two administrators must remain")
        versions[command.target_subject_id] = actual + 1
        return actual + 1

    async def assert_current_version(self, command: MembershipAccessUpdate) -> None:
        versions = cast(dict[UUID, int], self.state["membership_versions"])
        if versions.get(command.target_subject_id) != command.expected_membership_version:
            raise ConflictError("membership version mismatch")

    async def assert_eligible_human_administrators(
        self, *, workspace_id: UUID, subject_ids: frozenset[UUID]
    ) -> None:
        assert workspace_id == self.state["workspace_id"]
        eligible = cast(set[UUID], self.state["eligible_administrators"])
        if not subject_ids.issubset(eligible):
            raise ForbiddenError("administrator eligibility changed")


class MemoryOutbox:
    def __init__(self, values: list[DomainEvent]) -> None:
        self.values = values

    async def add_events(self, events: Sequence[DomainEvent]) -> None:
        self.values.extend(events)


class MemorySystems:
    def __init__(self, state: dict[str, object]) -> None:
        self.state = state

    async def list(self, *, workspace_id: UUID, limit: int) -> Sequence[SystemDirectoryEntry]:
        assert workspace_id == self.state["workspace_id"]
        return tuple(cast(list[SystemDirectoryEntry], self.state["systems"]))[:limit]

    async def replace_assignees(self, command: SystemAssigneeUpdateCommand) -> int:
        systems = cast(list[SystemDirectoryEntry], self.state["systems"])
        index = next(
            (
                position
                for position, system in enumerate(systems)
                if system.system_id == command.system_id
            ),
            None,
        )
        if index is None:
            raise NotFoundError("data system missing")
        system = systems[index]
        if system.version != command.expected_system_version:
            raise ConflictError("system version mismatch")
        assignable = cast(set[UUID], self.state["assignable_subjects"])
        if not {item.subject_id for item in command.assignees}.issubset(assignable):
            raise ForbiddenError("assigned member is inactive")
        systems[index] = replace(
            system,
            version=system.version + 1,
            assignees=tuple(
                SystemDirectoryAssignee(
                    subject_id=item.subject_id,
                    display_name=f"User {item.subject_id}",
                    responsibility=item.responsibility,
                    priority=item.priority,
                    active=True,
                )
                for item in command.assignees
            ),
        )
        return systems[index].version


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


class MemoryAdminAccessUnitOfWork:
    def __init__(self, state: dict[str, object]) -> None:
        self.state = state
        self.requests = MemoryRequests(cast(dict[UUID, AdminAccessRequest], state["requests"]))
        self.memberships = MemoryMemberships(state)
        self.systems = MemorySystems(state)
        self.outbox = MemoryOutbox(cast(list[DomainEvent], state["outbox"]))
        self.idempotency = MemoryIdempotency(
            cast(dict[tuple[UUID, str, str], IdempotencyRecord], state["idempotency"])
        )
        self._snapshot: dict[str, object] | None = None
        self._committed = False

    async def __aenter__(self) -> Self:
        self._snapshot = deepcopy(self.state)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_value, traceback
        if exc_type is not None or not self._committed:
            assert self._snapshot is not None
            self.state.clear()
            self.state.update(self._snapshot)

    async def commit(self) -> None:
        self._committed = True

    async def lock_workspace_access(self, *, workspace_id: UUID) -> None:
        assert workspace_id == self.state["workspace_id"]
        self.state["lock_count"] = cast(int, self.state["lock_count"]) + 1

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None:
        assert workspace_id == self.state["workspace_id"]
        assert isinstance(subject_id, UUID)


def _administrator(
    workspace_id: UUID,
    subject_id: UUID,
    *,
    assurance: AuthenticationAssurance,
    now: datetime,
    allowed_actions: frozenset[Action] | None = None,
    denied_actions: frozenset[Action] = frozenset(),
) -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=subject_id,
        workspace_id=workspace_id,
        active=True,
        department_id=uuid4(),
        groups=frozenset({"security-administrators"}),
        job_function="SECURITY_ADMINISTRATOR",
        clearance=Classification.RESTRICTED,
        allowed_actions=allowed_actions or frozenset({Action.ADMIN_MANAGE}),
        denied_actions=denied_actions,
        authentication_time=now - timedelta(seconds=5),
        authentication_assurance=assurance,
    )


def _command(workspace_id: UUID, target_id: UUID) -> MembershipAccessUpdate:
    return MembershipAccessUpdate(
        workspace_id=workspace_id,
        target_subject_id=target_id,
        expected_membership_version=1,
        active=True,
        clearance=Classification.CONFIDENTIAL,
        groups=frozenset({"engineers"}),
        allowed_actions=frozenset({Action.CATALOG_READ, Action.CATALOG_SEARCH}),
        denied_actions=frozenset({Action.CHAT_QUERY}),
    )


def _system_command(
    workspace_id: UUID,
    system_id: UUID,
    developer_id: UUID,
    steward_id: UUID,
) -> SystemAssigneeUpdateCommand:
    return SystemAssigneeUpdateCommand(
        workspace_id=workspace_id,
        system_id=system_id,
        expected_system_version=1,
        assignees=(
            SystemAssigneeUpdate(
                subject_id=developer_id,
                responsibility="DEVELOPER",
                priority=1,
            ),
            SystemAssigneeUpdate(
                subject_id=steward_id,
                responsibility="DATA_STEWARD",
                priority=1,
            ),
        ),
    )


def _state(
    workspace_id: UUID, target_id: UUID, maker_id: UUID, checker_id: UUID
) -> dict[str, object]:
    return {
        "workspace_id": workspace_id,
        "requests": {},
        "outbox": [],
        "idempotency": {},
        "membership_versions": {target_id: 1},
        "membership_records": {},
        "membership_read_count": 0,
        "systems": [],
        "assignable_subjects": {target_id, maker_id, checker_id},
        "eligible_administrators": {maker_id, checker_id},
        "remaining_admin_count": 2,
        "lock_count": 0,
    }


def _membership_record(subject_id: UUID, display_name: str) -> WorkspaceMembershipAccessRecord:
    system_id, domain_id = uuid4(), uuid4()
    return WorkspaceMembershipAccessRecord(
        summary=WorkspaceMembershipSummary(
            subject_id=subject_id,
            display_name=display_name,
            subject_active=True,
            membership_active=True,
            department_id=uuid4(),
            job_function="SECURITY_ADMINISTRATOR",
            clearance=Classification.RESTRICTED,
            membership_version=1,
        ),
        groups=frozenset({"security-administrators"}),
        allowed_actions=frozenset({Action.ADMIN_MANAGE, Action.CATALOG_READ}),
        denied_actions=frozenset({Action.CHAT_QUERY}),
        allowed_system_ids=frozenset({system_id}),
        allowed_domain_ids=frozenset({domain_id}),
    )


def _service(state: dict[str, object], *, enabled: bool = True) -> AdminAccessService:
    factory = cast(Callable[[], AdminAccessUnitOfWork], lambda: MemoryAdminAccessUnitOfWork(state))
    return AdminAccessService(
        factory,
        AuthorizationService(decision_writer=MemoryDecisionWriter()),
        fallback_enabled=enabled,
        fallback_ttl_seconds=300,
    )


@pytest.mark.asyncio
async def test_quarantined_catalog_review_is_human_admin_only_and_audited() -> None:
    workspace_id, administrator_id = uuid4(), uuid4()
    now = datetime.now(UTC)
    decision_writer = MemoryDecisionWriter()
    authorization = AuthorizationService(decision_writer=decision_writer)
    administrator = _administrator(
        workspace_id,
        administrator_id,
        assurance=AuthenticationAssurance.PASSWORD,
        now=now,
        allowed_actions=frozenset(
            {Action.CATALOG_SEARCH, Action.CATALOG_READ, Action.ADMIN_MANAGE}
        ),
    )

    assert await authorization.can_review_quarantined_catalog(
        subject=administrator,
        environment=EnvironmentAttributes(requested_at=now),
        request_id="quarantine-review-allow",
    )
    action, decision = decision_writer.decisions[-1]
    assert action == Action.CATALOG_QUARANTINE_READ.value
    assert decision.allowed is True

    service_identity = replace(
        administrator,
        groups=frozenset({"security-administrators", "service-accounts"}),
        job_function="SERVICE_ACCOUNT",
    )
    assert not await authorization.can_review_quarantined_catalog(
        subject=service_identity,
        environment=EnvironmentAttributes(requested_at=now),
        request_id="quarantine-review-service-account",
    )
    assert "HUMAN_ADMINISTRATOR_REQUIRED" in decision_writer.decisions[-1][1].reason_codes

    explicitly_denied = replace(
        administrator,
        denied_actions=frozenset({Action.CATALOG_SEARCH}),
    )
    assert not await authorization.can_review_quarantined_catalog(
        subject=explicitly_denied,
        environment=EnvironmentAttributes(requested_at=now),
        request_id="quarantine-review-explicit-deny",
    )
    assert "EXPLICIT_ACTION_DENY" in decision_writer.decisions[-1][1].reason_codes


@pytest.mark.parametrize(
    "assurance",
    [
        AuthenticationAssurance.PASSWORD,
        AuthenticationAssurance.PASSWORD_REAUTH,
        AuthenticationAssurance.HARDWARE_WEBAUTHN,
    ],
)
@pytest.mark.asyncio
async def test_membership_reads_reuse_admin_read_assurance_when_fallback_is_disabled(
    assurance: AuthenticationAssurance,
) -> None:
    workspace_id, target_id, administrator_id, other_admin_id = (uuid4() for _ in range(4))
    now = datetime.now(UTC)
    state = _state(workspace_id, target_id, administrator_id, other_admin_id)
    administrator_record = _membership_record(administrator_id, "Administrator")
    target_record = _membership_record(target_id, "Target User")
    cast(dict[UUID, WorkspaceMembershipAccessRecord], state["membership_records"]).update(
        {administrator_id: administrator_record, target_id: target_record}
    )
    service = _service(state, enabled=False)
    subject = _administrator(workspace_id, administrator_id, assurance=assurance, now=now)
    environment = EnvironmentAttributes(requested_at=now)

    items = await service.list_workspace_memberships(
        workspace_id=workspace_id,
        limit=1,
        subject=subject,
        environment=environment,
        request_id="membership-list",
    )
    access = await service.get_workspace_membership_access(
        workspace_id=workspace_id,
        target_subject_id=target_id,
        subject=subject,
        environment=environment,
        request_id="membership-detail",
    )

    assert len(items) == 1
    assert items[0].display_name == "Administrator"
    assert access == target_record
    assert access.summary.membership_version == 1
    assert access.allowed_actions == frozenset({Action.ADMIN_MANAGE, Action.CATALOG_READ})


@pytest.mark.asyncio
async def test_system_directory_read_requires_an_eligible_workspace_administrator() -> None:
    workspace_id, target_id, administrator_id, other_admin_id = (uuid4() for _ in range(4))
    now = datetime.now(UTC)
    state = _state(workspace_id, target_id, administrator_id, other_admin_id)
    state["membership_records"] = {
        administrator_id: _membership_record(administrator_id, "Administrator")
    }
    system_id = uuid4()
    state["systems"] = [
        SystemDirectoryEntry(
            system_id=system_id,
            code="FAB",
            name="Fabrication",
            description="Fab data",
            active=True,
            version=1,
            assignees=(),
        )
    ]

    items = await _service(state, enabled=False).list_systems(
        workspace_id=workspace_id,
        limit=100,
        subject=_administrator(
            workspace_id,
            administrator_id,
            assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
            now=now,
        ),
        environment=EnvironmentAttributes(requested_at=now),
        request_id="system-directory",
    )

    assert [(item.system_id, item.code) for item in items] == [(system_id, "FAB")]


@pytest.mark.asyncio
async def test_system_assignment_requires_hardware_and_writes_versioned_audit_evidence() -> None:
    workspace_id, developer_id, administrator_id, steward_id = (uuid4() for _ in range(4))
    now = datetime.now(UTC)
    state = _state(workspace_id, developer_id, administrator_id, steward_id)
    system_id = uuid4()
    state["systems"] = [
        SystemDirectoryEntry(
            system_id=system_id,
            code="FAB",
            name="Fabrication",
            description="Fab data",
            active=True,
            version=1,
            assignees=(),
        )
    ]
    command = _system_command(workspace_id, system_id, developer_id, steward_id)
    service = _service(state, enabled=False)
    subject = _administrator(
        workspace_id,
        administrator_id,
        assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
        now=now,
    )
    environment = EnvironmentAttributes(requested_at=now)

    version = await service.update_system_assignees_with_hardware_key(
        command=command,
        subject=subject,
        environment=environment,
        request_id="system-assignment",
        idempotency_key="system-assignment-idempotency-key",
        request_hash=command.payload_hash,
    )
    repeated = await service.update_system_assignees_with_hardware_key(
        command=command,
        subject=subject,
        environment=environment,
        request_id="system-assignment-repeat",
        idempotency_key="system-assignment-idempotency-key",
        request_hash=command.payload_hash,
    )

    updated = cast(list[SystemDirectoryEntry], state["systems"])[0]
    assert (version, repeated, updated.version) == (2, 2, 2)
    assert [(item.responsibility, item.priority) for item in updated.assignees] == [
        ("DEVELOPER", 1),
        ("DATA_STEWARD", 1),
    ]
    outbox = cast(list[DomainEvent], state["outbox"])
    assert len(outbox) == 1
    assert outbox[0].event_type == "platform.data_system.assignees_updated.v1"
    assert outbox[0].payload["payload_hash"] == command.payload_hash


def test_system_assignment_requires_one_ranked_developer_and_steward() -> None:
    workspace_id, system_id, subject_id = uuid4(), uuid4(), uuid4()

    with pytest.raises(ValidationError, match="one Developer and one Data Steward"):
        SystemAssigneeUpdateCommand(
            workspace_id=workspace_id,
            system_id=system_id,
            expected_system_version=1,
            assignees=(
                SystemAssigneeUpdate(
                    subject_id=subject_id,
                    responsibility="DEVELOPER",
                    priority=1,
                ),
            ),
        )


@pytest.mark.asyncio
async def test_membership_detail_hides_unknown_or_other_workspace_subject() -> None:
    workspace_id, target_id, administrator_id, other_admin_id = (uuid4() for _ in range(4))
    now = datetime.now(UTC)
    state = _state(workspace_id, target_id, administrator_id, other_admin_id)
    cast(dict[UUID, WorkspaceMembershipAccessRecord], state["membership_records"])[
        administrator_id
    ] = _membership_record(administrator_id, "Administrator")

    with pytest.raises(NotFoundError, match="target workspace membership"):
        await _service(state, enabled=False).get_workspace_membership_access(
            workspace_id=workspace_id,
            target_subject_id=uuid4(),
            subject=_administrator(
                workspace_id,
                administrator_id,
                assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
                now=now,
            ),
            environment=EnvironmentAttributes(requested_at=now),
            request_id="membership-hidden",
        )


@pytest.mark.parametrize(
    ("enabled", "assurance", "expected_operations"),
    [
        (
            False,
            AuthenticationAssurance.PASSWORD,
            {
                AdminOperation.MEMBERSHIP_ACCESS_READ,
                AdminOperation.MEMBERSHIP_RENEWAL_READ,
                AdminOperation.CLASSIFICATION_POLICY_READ,
                AdminOperation.INFERENCE_PROVIDER_PROFILE_READ,
                AdminOperation.RESTRICTED_SEARCH_GRANT_READ,
            },
        ),
        (
            False,
            AuthenticationAssurance.PASSWORD_REAUTH,
            {
                AdminOperation.MEMBERSHIP_ACCESS_READ,
                AdminOperation.MEMBERSHIP_RENEWAL_READ,
                AdminOperation.CLASSIFICATION_POLICY_READ,
                AdminOperation.INFERENCE_PROVIDER_PROFILE_READ,
                AdminOperation.RESTRICTED_SEARCH_GRANT_READ,
            },
        ),
        (
            True,
            AuthenticationAssurance.PASSWORD_REAUTH,
            {
                AdminOperation.MEMBERSHIP_ACCESS_READ,
                AdminOperation.MEMBERSHIP_RENEWAL_READ,
                AdminOperation.CLASSIFICATION_POLICY_READ,
                AdminOperation.INFERENCE_PROVIDER_PROFILE_READ,
                AdminOperation.RESTRICTED_SEARCH_GRANT_READ,
                AdminOperation.FALLBACK_REQUEST_READ,
                AdminOperation.FALLBACK_REQUEST_CREATE,
                AdminOperation.FALLBACK_REQUEST_DECIDE,
                AdminOperation.FALLBACK_REQUEST_CONSUME,
            },
        ),
        (
            True,
            AuthenticationAssurance.HARDWARE_WEBAUTHN,
            {
                AdminOperation.MEMBERSHIP_ACCESS_READ,
                AdminOperation.MEMBERSHIP_ACCESS_UPDATE,
                AdminOperation.MEMBERSHIP_RENEWAL_READ,
                AdminOperation.MEMBERSHIP_RENEWAL_DECIDE,
                AdminOperation.SYSTEM_ASSIGNMENT_UPDATE,
                AdminOperation.CLASSIFICATION_POLICY_READ,
                AdminOperation.CLASSIFICATION_POLICY_PROPOSE,
                AdminOperation.CLASSIFICATION_POLICY_DECIDE,
                AdminOperation.INFERENCE_PROVIDER_PROFILE_READ,
                AdminOperation.INFERENCE_PROVIDER_PROFILE_DECIDE,
                AdminOperation.INFERENCE_PROVIDER_PROFILE_REVOKE,
                AdminOperation.RESTRICTED_SEARCH_GRANT_READ,
                AdminOperation.RESTRICTED_SEARCH_GRANT_PROPOSE,
                AdminOperation.RESTRICTED_SEARCH_GRANT_DECIDE,
                AdminOperation.RESTRICTED_SEARCH_GRANT_REVOKE,
                AdminOperation.FALLBACK_REQUEST_READ,
                AdminOperation.FALLBACK_REQUEST_DECIDE,
            },
        ),
    ],
)
@pytest.mark.asyncio
async def test_admin_read_context_exposes_only_current_assurance_operations(
    enabled: bool,
    assurance: AuthenticationAssurance,
    expected_operations: set[AdminOperation],
) -> None:
    workspace_id, target_id, administrator_id, other_admin_id = (uuid4() for _ in range(4))
    now = datetime.now(UTC)
    state = _state(workspace_id, target_id, administrator_id, other_admin_id)
    cast(dict[UUID, WorkspaceMembershipAccessRecord], state["membership_records"])[
        administrator_id
    ] = _membership_record(administrator_id, "Administrator")

    context = await _service(state, enabled=enabled).get_admin_read_context(
        workspace_id=workspace_id,
        subject=_administrator(workspace_id, administrator_id, assurance=assurance, now=now),
        environment=EnvironmentAttributes(requested_at=now),
        request_id="admin-me",
    )

    assert context.workspace_id == workspace_id
    assert context.membership.subject_id == administrator_id
    assert context.authentication_assurance is assurance
    assert set(context.allowed_operations) == expected_operations
    assert context.fallback_enabled is enabled
    assert context.action_vocabulary == tuple(sorted(Action, key=lambda action: action.value))


@pytest.mark.asyncio
async def test_admin_read_context_exposes_only_granted_governance_surfaces() -> None:
    workspace_id, target_id, administrator_id, other_admin_id = (uuid4() for _ in range(4))
    now = datetime.now(UTC)
    state = _state(workspace_id, target_id, administrator_id, other_admin_id)
    cast(dict[UUID, WorkspaceMembershipAccessRecord], state["membership_records"])[
        administrator_id
    ] = _membership_record(administrator_id, "Administrator")
    granted_actions = frozenset(
        {
            Action.ADMIN_MANAGE,
            Action.RETENTION_READ,
            Action.RETENTION_MANAGE,
            Action.LEGAL_HOLD_PLACE,
            Action.LEGAL_HOLD_RELEASE,
            Action.ERASURE_REQUEST,
            Action.ERASURE_APPROVE,
        }
    )

    context = await _service(state).get_admin_read_context(
        workspace_id=workspace_id,
        subject=_administrator(
            workspace_id,
            administrator_id,
            assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
            now=now,
            allowed_actions=granted_actions,
            denied_actions=frozenset({Action.LEGAL_HOLD_RELEASE}),
        ),
        environment=EnvironmentAttributes(requested_at=now),
        request_id="admin-governance-capabilities",
    )

    operations = set(context.allowed_operations)
    assert {
        AdminOperation.RETENTION_POLICY_READ,
        AdminOperation.RETENTION_POLICY_MANAGE,
        AdminOperation.LEGAL_HOLD_READ,
        AdminOperation.LEGAL_HOLD_PLACE,
        AdminOperation.ERASURE_READ,
        AdminOperation.ERASURE_REQUEST,
        AdminOperation.ERASURE_APPROVE,
    } <= operations
    assert AdminOperation.LEGAL_HOLD_RELEASE not in operations


@pytest.mark.asyncio
async def test_fallback_is_disabled_by_default_and_has_no_side_effects() -> None:
    workspace_id, target_id, maker_id, checker_id = (uuid4() for _ in range(4))
    now = datetime.now(UTC)
    state = _state(workspace_id, target_id, maker_id, checker_id)

    with pytest.raises(ForbiddenError) as captured:
        await _service(state, enabled=False).create_fallback_request(
            command=_command(workspace_id, target_id),
            reason="Emergency access correction",
            subject=_administrator(
                workspace_id,
                maker_id,
                assurance=AuthenticationAssurance.PASSWORD_REAUTH,
                now=now,
            ),
            environment=EnvironmentAttributes(requested_at=now),
            request_id="request-disabled",
            idempotency_key="fallback-disabled-0001",
            request_hash="a" * 64,
        )

    assert captured.value.details["remediation"] == {"kind": "FALLBACK_UNAVAILABLE"}
    assert state["requests"] == {}
    assert state["outbox"] == []


@pytest.mark.asyncio
async def test_fallback_full_flow_is_two_person_one_time_and_data_minimized() -> None:
    workspace_id, target_id, maker_id, checker_id = (uuid4() for _ in range(4))
    now = datetime.now(UTC)
    state = _state(workspace_id, target_id, maker_id, checker_id)
    service = _service(state)
    maker = _administrator(
        workspace_id,
        maker_id,
        assurance=AuthenticationAssurance.PASSWORD_REAUTH,
        now=now,
    )
    checker = _administrator(
        workspace_id,
        checker_id,
        assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
        now=now,
    )
    environment = EnvironmentAttributes(requested_at=now)

    request = await service.create_fallback_request(
        command=_command(workspace_id, target_id),
        reason="Correct a locked membership",
        subject=maker,
        environment=environment,
        request_id="fallback-create",
        idempotency_key="fallback-create-0001",
        request_hash="a" * 64,
    )
    request = await service.decide_fallback_request(
        workspace_id=workspace_id,
        access_request_id=request.access_request_id,
        approval_decision=AdminAccessDecision.APPROVED,
        reason="Verified against incident ticket",
        expected_version=1,
        subject=checker,
        environment=environment,
        request_id="fallback-approve",
        idempotency_key="fallback-approve-001",
        request_hash="b" * 64,
    )
    consumed, membership_version = await service.consume_fallback_request(
        workspace_id=workspace_id,
        access_request_id=request.access_request_id,
        confirmed_payload_hash=request.payload_hash,
        expected_version=2,
        subject=maker,
        environment=environment,
        request_id="fallback-consume",
        idempotency_key="fallback-consume-001",
        request_hash="c" * 64,
    )
    replayed, replayed_version = await service.consume_fallback_request(
        workspace_id=workspace_id,
        access_request_id=request.access_request_id,
        confirmed_payload_hash=request.payload_hash,
        expected_version=2,
        subject=maker,
        environment=environment,
        request_id="fallback-consume-replay",
        idempotency_key="fallback-consume-001",
        request_hash="c" * 64,
    )

    assert consumed.state is AdminAccessRequestState.CONSUMED
    assert consumed.checker_id == checker_id
    assert consumed.consumed_by == maker_id
    assert replayed.state is AdminAccessRequestState.CONSUMED
    assert membership_version == replayed_version == 2
    assert cast(dict[UUID, int], state["membership_versions"])[target_id] == 2
    events = cast(list[DomainEvent], state["outbox"])
    assert [event.event_type for event in events] == [
        "iam.admin_access_request.created.v1",
        "iam.admin_access_request.approved.v1",
        "iam.admin_access_request.consumed.v1",
        "iam.workspace_membership.access_updated.v1",
    ]
    serialized_payloads = repr([event.payload for event in events])
    assert "engineers" not in serialized_payloads
    assert "catalog.read" not in serialized_payloads
    assert "Correct a locked membership" not in serialized_payloads


@pytest.mark.asyncio
async def test_consume_rechecks_checker_eligibility_and_rolls_back() -> None:
    workspace_id, target_id, maker_id, checker_id = (uuid4() for _ in range(4))
    now = datetime.now(UTC)
    state = _state(workspace_id, target_id, maker_id, checker_id)
    service = _service(state)
    maker = _administrator(
        workspace_id,
        maker_id,
        assurance=AuthenticationAssurance.PASSWORD_REAUTH,
        now=now,
    )
    checker = _administrator(
        workspace_id,
        checker_id,
        assurance=AuthenticationAssurance.PASSWORD_REAUTH,
        now=now,
    )
    environment = EnvironmentAttributes(requested_at=now)
    request = await service.create_fallback_request(
        command=_command(workspace_id, target_id),
        reason="Correct access",
        subject=maker,
        environment=environment,
        request_id="create",
        idempotency_key="fallback-recheck-create",
        request_hash="d" * 64,
    )
    approved = await service.decide_fallback_request(
        workspace_id=workspace_id,
        access_request_id=request.access_request_id,
        approval_decision=AdminAccessDecision.APPROVED,
        reason="Independent review",
        expected_version=1,
        subject=checker,
        environment=environment,
        request_id="approve",
        idempotency_key="fallback-recheck-approve",
        request_hash="e" * 64,
    )
    cast(set[UUID], state["eligible_administrators"]).remove(checker_id)

    with pytest.raises(ForbiddenError):
        await service.consume_fallback_request(
            workspace_id=workspace_id,
            access_request_id=approved.access_request_id,
            confirmed_payload_hash=approved.payload_hash,
            expected_version=2,
            subject=maker,
            environment=environment,
            request_id="consume",
            idempotency_key="fallback-recheck-consume",
            request_hash="f" * 64,
        )

    assert cast(dict[UUID, int], state["membership_versions"])[target_id] == 1
    stored = cast(dict[UUID, AdminAccessRequest], state["requests"])[approved.access_request_id]
    assert stored.state is AdminAccessRequestState.APPROVED


@pytest.mark.parametrize("revocation", ["maker", "target_version"])
@pytest.mark.asyncio
async def test_approval_rechecks_maker_and_target_version(revocation: str) -> None:
    workspace_id, target_id, maker_id, checker_id = (uuid4() for _ in range(4))
    now = datetime.now(UTC)
    state = _state(workspace_id, target_id, maker_id, checker_id)
    service = _service(state)
    maker = _administrator(
        workspace_id,
        maker_id,
        assurance=AuthenticationAssurance.PASSWORD_REAUTH,
        now=now,
    )
    checker = _administrator(
        workspace_id,
        checker_id,
        assurance=AuthenticationAssurance.PASSWORD_REAUTH,
        now=now,
    )
    environment = EnvironmentAttributes(requested_at=now)
    request = await service.create_fallback_request(
        command=_command(workspace_id, target_id),
        reason="Correct access",
        subject=maker,
        environment=environment,
        request_id="create",
        idempotency_key=f"fallback-{revocation}-create",
        request_hash="1" * 64,
    )
    expected_error: type[ForbiddenError] | type[ConflictError]
    if revocation == "maker":
        cast(set[UUID], state["eligible_administrators"]).remove(maker_id)
        expected_error = ForbiddenError
    else:
        cast(dict[UUID, int], state["membership_versions"])[target_id] = 2
        expected_error = ConflictError

    with pytest.raises(expected_error):
        await service.decide_fallback_request(
            workspace_id=workspace_id,
            access_request_id=request.access_request_id,
            approval_decision=AdminAccessDecision.APPROVED,
            reason="Independent review",
            expected_version=1,
            subject=checker,
            environment=environment,
            request_id="approve",
            idempotency_key=f"fallback-{revocation}-approve",
            request_hash="2" * 64,
        )

    stored = cast(dict[UUID, AdminAccessRequest], state["requests"])[request.access_request_id]
    assert stored.state is AdminAccessRequestState.PENDING
