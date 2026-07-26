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
    AdminAccessRequestPage,
    IdempotencyRecord,
    MembershipChangeRequestActivity,
    MembershipChangeRequestActivityPage,
    MembershipOwnedTable,
    MembershipOwnedTablePage,
    MembershipRenewalPage,
    MembershipRenewalRecord,
    SystemAssigneePage,
    SystemDirectoryAssignee,
    SystemDirectoryEntry,
    SystemDirectoryPage,
    WorkspaceMembershipAccessRecord,
    WorkspaceMembershipPage,
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
    SystemAssigneeKey,
    SystemAssigneePatchCommand,
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
    canonical_json_hash,
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
        self,
        *,
        workspace_id: UUID,
        state: str | None,
        limit: int,
        cursor: str | None = None,
    ) -> AdminAccessRequestPage:
        values = tuple(
            value
            for value in self.values.values()
            if value.workspace_id == workspace_id and (state is None or value.state.value == state)
        )
        start = int(cursor) if cursor is not None else 0
        return AdminAccessRequestPage(
            items=values[start : start + limit],
            next_cursor=str(start + limit) if len(values) > start + limit else None,
        )

    async def save(self, request: AdminAccessRequest) -> None:
        self.values[request.access_request_id] = request


class MemoryMemberships:
    def __init__(self, state: dict[str, object]) -> None:
        self.state = state

    async def list(
        self,
        *,
        workspace_id: UUID,
        limit: int,
        query: str | None = None,
        active: bool | None = None,
        cursor: str | None = None,
    ) -> WorkspaceMembershipPage:
        assert workspace_id == self.state["workspace_id"]
        assert cursor is None
        self.state["membership_read_count"] = cast(int, self.state["membership_read_count"]) + 1
        records = cast(
            dict[UUID, WorkspaceMembershipAccessRecord], self.state["membership_records"]
        )
        values = tuple(
            record.summary
            for record in sorted(records.values(), key=lambda value: value.summary.display_name)
            if (
                (query is None or query in record.summary.display_name.casefold())
                and (active is None or record.summary.membership_active is active)
            )
        )
        return WorkspaceMembershipPage(
            items=values[:limit],
            next_cursor="next-page" if len(values) > limit else None,
        )

    async def get_access(
        self, *, workspace_id: UUID, subject_id: UUID
    ) -> WorkspaceMembershipAccessRecord | None:
        assert workspace_id == self.state["workspace_id"]
        self.state["membership_read_count"] = cast(int, self.state["membership_read_count"]) + 1
        records = cast(
            dict[UUID, WorkspaceMembershipAccessRecord], self.state["membership_records"]
        )
        return records.get(subject_id)

    async def list_change_request_activity(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        limit: int,
        cursor: str | None = None,
    ) -> MembershipChangeRequestActivityPage:
        assert workspace_id == self.state["workspace_id"]
        assert cursor is None
        assert subject_id in cast(
            dict[UUID, WorkspaceMembershipAccessRecord],
            self.state["membership_records"],
        )
        items = cast(list[MembershipChangeRequestActivity], self.state["member_cr_activity"])
        return MembershipChangeRequestActivityPage(items=tuple(items[:limit]), next_cursor=None)

    async def list_owned_tables(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        limit: int,
        cursor: str | None = None,
    ) -> MembershipOwnedTablePage:
        assert workspace_id == self.state["workspace_id"]
        assert cursor is None
        assert subject_id in cast(
            dict[UUID, WorkspaceMembershipAccessRecord],
            self.state["membership_records"],
        )
        items = cast(list[MembershipOwnedTable], self.state["member_owned_tables"])
        return MembershipOwnedTablePage(items=tuple(items[:limit]), next_cursor=None)

    async def apply(self, command: MembershipAccessUpdate) -> int:
        await self.assert_current_version(command)
        versions = cast(dict[UUID, int], self.state["membership_versions"])
        actual = versions[command.target_subject_id]
        if cast(int, self.state["remaining_admin_count"]) < 2:
            raise ConflictError("two administrators must remain")
        versions[command.target_subject_id] = actual + 1
        return actual + 1

    async def record_role_assignment(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        role_id: UUID | None,
        role_version: int | None,
        role_marker: str | None,
        membership_version: int,
        access_payload_hash: str,
        actor_id: UUID,
    ) -> None:
        if cast(bool, self.state["role_assignment_failure"]):
            raise ConflictError("role assignment evidence write failed")
        records = cast(list[dict[str, object]], self.state["role_assignment_records"])
        records.append(
            {
                "workspace_id": workspace_id,
                "subject_id": subject_id,
                "role_id": role_id,
                "role_version": role_version,
                "role_marker": role_marker,
                "membership_version": membership_version,
                "access_payload_hash": access_payload_hash,
                "actor_id": actor_id,
            }
        )

    async def assert_current_version(self, command: MembershipAccessUpdate) -> None:
        versions = cast(dict[UUID, int], self.state["membership_versions"])
        if versions.get(command.target_subject_id) != command.expected_membership_version:
            raise ConflictError("membership version mismatch")

    async def assert_manual_access_update_allowed(
        self, *, workspace_id: UUID, subject_id: UUID
    ) -> None:
        assert workspace_id == self.state["workspace_id"]
        blocked = cast(set[UUID], self.state["role_bound_subjects"])
        if subject_id in blocked:
            raise ConflictError(
                "Role-bound access must be changed through the dedicated Role assignment route."
            )

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


class MemoryRenewals:
    def __init__(self, state: dict[str, object]) -> None:
        self.state = state

    async def list_records(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID | None,
        state: str | None,
        limit: int,
        cursor: str | None = None,
    ) -> MembershipRenewalPage:
        assert workspace_id == self.state["workspace_id"]
        records = tuple(
            record
            for record in cast(list[MembershipRenewalRecord], self.state["renewals"])
            if (
                (subject_id is None or record.target_subject_id == subject_id)
                and (state is None or record.state == state)
            )
        )
        start = int(cursor) if cursor is not None else 0
        return MembershipRenewalPage(
            items=records[start : start + limit],
            next_cursor=str(start + limit) if len(records) > start + limit else None,
        )

    async def get_record(
        self, *, workspace_id: UUID, renewal_request_id: UUID
    ) -> MembershipRenewalRecord | None:
        assert workspace_id == self.state["workspace_id"]
        return next(
            (
                record
                for record in cast(list[MembershipRenewalRecord], self.state["renewals"])
                if record.renewal_request_id == renewal_request_id
            ),
            None,
        )


class MemorySystems:
    def __init__(self, state: dict[str, object]) -> None:
        self.state = state

    async def list(
        self,
        *,
        workspace_id: UUID,
        limit: int,
        query: str | None = None,
        active: bool | None = None,
        cursor: str | None = None,
    ) -> SystemDirectoryPage:
        assert workspace_id == self.state["workspace_id"]
        systems = tuple(
            system
            for system in cast(list[SystemDirectoryEntry], self.state["systems"])
            if (
                (query is None or query in system.name.lower() or query in system.code.lower())
                and (active is None or system.active is active)
            )
        )
        start = int(cursor) if cursor is not None else 0
        return SystemDirectoryPage(
            items=systems[start : start + limit],
            next_cursor=str(start + limit) if len(systems) > start + limit else None,
        )

    async def list_assignees(
        self,
        *,
        workspace_id: UUID,
        system_id: UUID,
        limit: int,
        cursor: str | None = None,
    ) -> SystemAssigneePage:
        assert workspace_id == self.state["workspace_id"]
        system = next(
            (
                value
                for value in cast(list[SystemDirectoryEntry], self.state["systems"])
                if value.system_id == system_id
            ),
            None,
        )
        if system is None:
            raise NotFoundError("data system missing")
        start = int(cursor) if cursor is not None else 0
        return SystemAssigneePage(
            items=system.assignees[start : start + limit],
            system_version=system.version,
            next_cursor=(str(start + limit) if len(system.assignees) > start + limit else None),
        )

    async def patch_assignees(self, command: SystemAssigneePatchCommand) -> int:
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
        if not {item.subject_id for item in command.upserts}.issubset(assignable):
            raise ValidationError("assigned member is inactive")
        assignments = {(item.subject_id, item.responsibility): item for item in system.assignees}
        removal_keys = {(item.subject_id, item.responsibility) for item in command.removals}
        missing = removal_keys - set(assignments)
        if missing:
            raise ConflictError("selected for removal no longer exists")
        effective = False
        for key in removal_keys:
            del assignments[key]
            effective = True
        for item in command.upserts:
            key = (item.subject_id, item.responsibility)
            current = assignments.get(key)
            if current is not None and current.priority == item.priority and current.active:
                continue
            assignments[key] = SystemDirectoryAssignee(
                subject_id=item.subject_id,
                display_name=f"User {item.subject_id}",
                responsibility=item.responsibility,
                priority=item.priority,
                active=True,
            )
            effective = True
        if not effective:
            raise ConflictError("no effective changes")
        for responsibility in ("DEVELOPER", "DATA_STEWARD"):
            priorities = [
                item.priority
                for item in assignments.values()
                if item.responsibility == responsibility
            ]
            if not priorities or min(priorities) != 1 or len(priorities) != len(set(priorities)):
                raise ValidationError("invalid responsibility lane")
        systems[index] = replace(
            system,
            version=system.version + 1,
            assignees=tuple(assignments.values()),
            assignee_count=len(assignments),
        )
        return systems[index].version

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

    async def create(
        self,
        *,
        workspace_id: UUID,
        code: str,
        name: str,
        description: str,
    ) -> SystemDirectoryEntry:
        assert workspace_id == self.state["workspace_id"]
        systems = cast(list[SystemDirectoryEntry], self.state["systems"])
        if any(item.code == code for item in systems):
            raise ConflictError("system code already exists")
        entry = SystemDirectoryEntry(
            system_id=uuid4(),
            code=code,
            name=name,
            description=description,
            active=True,
            version=1,
        )
        systems.append(entry)
        return entry


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
        self.renewals = MemoryRenewals(state)
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


def _system_patch_command(
    workspace_id: UUID,
    system_id: UUID,
    *,
    expected_version: int = 1,
    upserts: tuple[SystemAssigneeUpdate, ...] = (),
    removals: tuple[SystemAssigneeKey, ...] = (),
) -> SystemAssigneePatchCommand:
    return SystemAssigneePatchCommand(
        workspace_id=workspace_id,
        system_id=system_id,
        expected_system_version=expected_version,
        upserts=upserts,
        removals=removals,
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
        "renewals": [],
        "member_cr_activity": [],
        "member_owned_tables": [],
        "membership_read_count": 0,
        "systems": [],
        "assignable_subjects": {target_id, maker_id, checker_id},
        "eligible_administrators": {maker_id, checker_id},
        "remaining_admin_count": 2,
        "role_assignment_records": [],
        "role_assignment_failure": False,
        "role_bound_subjects": set(),
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


def _service(
    state: dict[str, object],
    *,
    enabled: bool = True,
    development_admin_password_bypass_enabled: bool = False,
) -> AdminAccessService:
    factory = cast(Callable[[], AdminAccessUnitOfWork], lambda: MemoryAdminAccessUnitOfWork(state))
    return AdminAccessService(
        factory,
        AuthorizationService(
            decision_writer=MemoryDecisionWriter(),
            development_admin_password_bypass_enabled=(development_admin_password_bypass_enabled),
        ),
        fallback_enabled=enabled,
        fallback_ttl_seconds=300,
        development_admin_password_bypass_enabled=(development_admin_password_bypass_enabled),
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

    assert len(items.items) == 1
    assert items.items[0].display_name == "Administrator"
    assert items.next_cursor == "next-page"
    assert access == target_record
    assert access.summary.membership_version == 1
    assert access.allowed_actions == frozenset({Action.ADMIN_MANAGE, Action.CATALOG_READ})


@pytest.mark.asyncio
async def test_member_activity_drilldowns_apply_item_level_authorization() -> None:
    workspace_id, target_id, administrator_id, other_admin_id = (uuid4() for _ in range(4))
    now = datetime.now(UTC)
    state = _state(workspace_id, target_id, administrator_id, other_admin_id)
    state["membership_records"] = {
        target_id: _membership_record(target_id, "Target User"),
        administrator_id: _membership_record(administrator_id, "Administrator"),
    }
    state["member_cr_activity"] = [
        MembershipChangeRequestActivity(
            change_request_id=uuid4(),
            number="CR-42",
            title="Metadata update",
            request_type="METADATA_CHANGE",
            state="IN_REVIEW",
            relationship="REQUESTER",
            classification=Classification.INTERNAL,
            requester_id=target_id,
            updated_at=now,
        )
    ]
    state["member_owned_tables"] = [
        MembershipOwnedTable(
            asset_id=uuid4(),
            name="customer_orders",
            platform="postgres",
            database_name="warehouse",
            schema_name="sales",
            classification=Classification.INTERNAL,
            system_id=None,
            domain_id=None,
            owner_department_id=None,
            source_version="v1",
            observed_at=now,
        )
    ]
    service = _service(state, enabled=False)
    allowed_subject = _administrator(
        workspace_id,
        administrator_id,
        assurance=AuthenticationAssurance.PASSWORD,
        now=now,
        allowed_actions=frozenset({Action.ADMIN_MANAGE, Action.CHANGE_READ, Action.CATALOG_READ}),
    )

    change_requests = await service.list_membership_change_request_activity(
        workspace_id=workspace_id,
        target_subject_id=target_id,
        limit=25,
        cursor=None,
        subject=allowed_subject,
        environment=EnvironmentAttributes(requested_at=now),
        request_id="member-cr-activity",
    )
    tables = await service.list_membership_owned_tables(
        workspace_id=workspace_id,
        target_subject_id=target_id,
        limit=25,
        cursor=None,
        subject=allowed_subject,
        environment=EnvironmentAttributes(requested_at=now),
        request_id="member-owned-tables",
    )
    denied_tables = await service.list_membership_owned_tables(
        workspace_id=workspace_id,
        target_subject_id=target_id,
        limit=25,
        cursor=None,
        subject=replace(
            allowed_subject,
            denied_actions=frozenset({Action.CATALOG_READ}),
        ),
        environment=EnvironmentAttributes(requested_at=now),
        request_id="member-owned-tables-denied",
    )

    assert [item.number for item in change_requests.items] == ["CR-42"]
    assert [item.name for item in tables.items] == ["customer_orders"]
    assert denied_tables.items == ()


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

    page = await _service(state, enabled=False).list_systems(
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

    assert [(item.system_id, item.code) for item in page.items] == [(system_id, "FAB")]
    assert page.next_cursor is None


@pytest.mark.asyncio
async def test_system_directory_read_forwards_normalized_filters_and_cursor_pages() -> None:
    workspace_id, target_id, administrator_id, other_admin_id = (uuid4() for _ in range(4))
    now = datetime.now(UTC)
    state = _state(workspace_id, target_id, administrator_id, other_admin_id)
    state["systems"] = [
        SystemDirectoryEntry(
            system_id=uuid4(),
            code=code,
            name=name,
            description="",
            active=active,
            version=1,
            assignees=(),
        )
        for code, name, active in (
            ("FAB-A", "Fabrication Alpha", True),
            ("FAB-B", "Fabrication Beta", True),
            ("OLD", "Legacy", False),
        )
    ]
    service = _service(state, enabled=False)
    subject = _administrator(
        workspace_id,
        administrator_id,
        assurance=AuthenticationAssurance.PASSWORD,
        now=now,
    )
    environment = EnvironmentAttributes(requested_at=now)

    first = await service.list_systems(
        workspace_id=workspace_id,
        limit=1,
        query="  FAB  ",
        active=True,
        subject=subject,
        environment=environment,
        request_id="system-directory-first",
    )
    second = await service.list_systems(
        workspace_id=workspace_id,
        limit=1,
        query="fab",
        active=True,
        cursor=first.next_cursor,
        subject=subject,
        environment=environment,
        request_id="system-directory-second",
    )

    assert [item.code for item in first.items] == ["FAB-A"]
    assert first.next_cursor == "1"
    assert [item.code for item in second.items] == ["FAB-B"]
    assert second.next_cursor is None


@pytest.mark.asyncio
async def test_system_creation_is_hardware_gated_idempotent_and_audited() -> None:
    workspace_id, target_id, administrator_id, other_admin_id = (uuid4() for _ in range(4))
    now = datetime.now(UTC)
    state = _state(workspace_id, target_id, administrator_id, other_admin_id)
    service = _service(state, enabled=False)
    subject = _administrator(
        workspace_id,
        administrator_id,
        assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
        now=now,
    )
    environment = EnvironmentAttributes(requested_at=now)
    request_hash = canonical_json_hash(
        {
            "operation": "admin.system.create",
            "code": "CRM",
            "name": "Customer Data",
            "description": "Customer source",
        }
    )

    created = await service.create_system(
        workspace_id=workspace_id,
        code="CRM",
        name="Customer Data",
        description="Customer source",
        subject=subject,
        environment=environment,
        request_id="system-create",
        idempotency_key="system-create-idempotency-0001",
        request_hash=request_hash,
    )
    replayed = await service.create_system(
        workspace_id=workspace_id,
        code="CRM",
        name="Customer Data",
        description="Customer source",
        subject=subject,
        environment=environment,
        request_id="system-create-replay",
        idempotency_key="system-create-idempotency-0001",
        request_hash=request_hash,
    )

    assert replayed == created
    assert len(cast(list[SystemDirectoryEntry], state["systems"])) == 1
    events = cast(list[DomainEvent], state["outbox"])
    assert len(events) == 1
    assert events[0].event_type == "platform.data_system.created.v1"
    assert events[0].payload["assurance"] == "HARDWARE_WEBAUTHN"

    with pytest.raises(ConflictError, match="different request"):
        await service.create_system(
            workspace_id=workspace_id,
            code="CRM",
            name="Changed",
            description="Customer source",
            subject=subject,
            environment=environment,
            request_id="system-create-conflict",
            idempotency_key="system-create-idempotency-0001",
            request_hash="f" * 64,
        )


@pytest.mark.asyncio
async def test_development_password_bypass_exposes_and_audits_direct_system_mutation() -> None:
    workspace_id, target_id, administrator_id, other_admin_id = (uuid4() for _ in range(4))
    now = datetime.now(UTC)
    state = _state(workspace_id, target_id, administrator_id, other_admin_id)
    cast(dict[UUID, WorkspaceMembershipAccessRecord], state["membership_records"])[
        administrator_id
    ] = _membership_record(administrator_id, "Administrator")
    service = _service(
        state,
        enabled=True,
        development_admin_password_bypass_enabled=True,
    )
    subject = _administrator(
        workspace_id,
        administrator_id,
        assurance=AuthenticationAssurance.PASSWORD,
        now=now,
    )
    environment = EnvironmentAttributes(requested_at=now)

    context = await service.get_admin_read_context(
        workspace_id=workspace_id,
        subject=subject,
        environment=environment,
        request_id="development-admin-context",
    )
    assert AdminOperation.SYSTEM_ASSIGNMENT_UPDATE in context.allowed_operations

    created = await service.create_system(
        workspace_id=workspace_id,
        code="DEV",
        name="Development System",
        description="Local E2E only",
        subject=subject,
        environment=environment,
        request_id="development-system-create",
        idempotency_key="development-system-create-0001",
        request_hash=canonical_json_hash(
            {
                "operation": "admin.system.create",
                "code": "DEV",
                "name": "Development System",
                "description": "Local E2E only",
            }
        ),
    )

    assert created.code == "DEV"
    events = cast(list[DomainEvent], state["outbox"])
    assert events[-1].payload["assurance"] == "PASSWORD"


@pytest.mark.asyncio
async def test_admin_list_services_reject_a_page_larger_than_one_hundred() -> None:
    workspace_id, target_id, administrator_id, other_admin_id = (uuid4() for _ in range(4))
    now = datetime.now(UTC)
    state = _state(workspace_id, target_id, administrator_id, other_admin_id)

    with pytest.raises(ValidationError, match="between 1 and 100"):
        await _service(state, enabled=False).list_systems(
            workspace_id=workspace_id,
            limit=101,
            subject=_administrator(
                workspace_id,
                administrator_id,
                assurance=AuthenticationAssurance.PASSWORD,
                now=now,
            ),
            environment=EnvironmentAttributes(requested_at=now),
            request_id="system-directory-oversized-page",
        )


@pytest.mark.asyncio
async def test_system_assignee_read_is_cursor_paged_and_capped_at_one_hundred() -> None:
    workspace_id, developer_id, administrator_id, steward_id = (uuid4() for _ in range(4))
    now = datetime.now(UTC)
    state = _state(workspace_id, developer_id, administrator_id, steward_id)
    system_id = uuid4()
    state["systems"] = [
        SystemDirectoryEntry(
            system_id=system_id,
            code="FAB",
            name="Fabrication",
            description="",
            active=True,
            version=3,
            assignees=(
                SystemDirectoryAssignee(
                    subject_id=developer_id,
                    display_name="Developer",
                    responsibility="DEVELOPER",
                    priority=1,
                    active=True,
                ),
                SystemDirectoryAssignee(
                    subject_id=steward_id,
                    display_name="Steward",
                    responsibility="DATA_STEWARD",
                    priority=1,
                    active=True,
                ),
            ),
            assignee_count=2,
        )
    ]
    service = _service(state, enabled=False)
    subject = _administrator(
        workspace_id,
        administrator_id,
        assurance=AuthenticationAssurance.PASSWORD,
        now=now,
    )
    environment = EnvironmentAttributes(requested_at=now)

    first = await service.list_system_assignees(
        workspace_id=workspace_id,
        system_id=system_id,
        limit=1,
        cursor=None,
        subject=subject,
        environment=environment,
        request_id="system-assignee-first",
    )
    second = await service.list_system_assignees(
        workspace_id=workspace_id,
        system_id=system_id,
        limit=1,
        cursor=first.next_cursor,
        subject=subject,
        environment=environment,
        request_id="system-assignee-second",
    )

    assert first.system_version == second.system_version == 3
    assert [item.responsibility for item in first.items] == ["DEVELOPER"]
    assert first.next_cursor == "1"
    assert [item.responsibility for item in second.items] == ["DATA_STEWARD"]
    assert second.next_cursor is None

    with pytest.raises(ValidationError, match="between 1 and 100"):
        await service.list_system_assignees(
            workspace_id=workspace_id,
            system_id=system_id,
            limit=101,
            cursor=None,
            subject=subject,
            environment=environment,
            request_id="system-assignee-oversized",
        )


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


@pytest.mark.asyncio
async def test_system_assignee_patch_requires_hardware_and_rejects_a_stale_version() -> None:
    workspace_id, developer_id, administrator_id, steward_id = (uuid4() for _ in range(4))
    now = datetime.now(UTC)
    state = _state(workspace_id, developer_id, administrator_id, steward_id)
    system_id = uuid4()
    state["systems"] = [
        SystemDirectoryEntry(
            system_id=system_id,
            code="FAB",
            name="Fabrication",
            description="",
            active=True,
            version=2,
            assignees=(
                SystemDirectoryAssignee(
                    subject_id=developer_id,
                    display_name="Developer",
                    responsibility="DEVELOPER",
                    priority=1,
                    active=True,
                ),
                SystemDirectoryAssignee(
                    subject_id=steward_id,
                    display_name="Steward",
                    responsibility="DATA_STEWARD",
                    priority=1,
                    active=True,
                ),
            ),
            assignee_count=2,
        )
    ]
    command = _system_patch_command(
        workspace_id,
        system_id,
        expected_version=1,
        upserts=(
            SystemAssigneeUpdate(
                subject_id=developer_id,
                responsibility="DEVELOPER",
                priority=2,
            ),
        ),
    )
    service = _service(state, enabled=False)
    environment = EnvironmentAttributes(requested_at=now)

    with pytest.raises(ForbiddenError) as denied:
        await service.patch_system_assignees_with_hardware_key(
            command=command,
            subject=_administrator(
                workspace_id,
                administrator_id,
                assurance=AuthenticationAssurance.PASSWORD,
                now=now,
            ),
            environment=environment,
            request_id="system-patch-password",
            idempotency_key="system-patch-password-0001",
            request_hash=command.payload_hash,
        )
    assert "PHISHING_RESISTANT_AUTH_REQUIRED" in denied.value.details["reason_codes"]

    with pytest.raises(ConflictError, match="system version mismatch"):
        await service.patch_system_assignees_with_hardware_key(
            command=command,
            subject=_administrator(
                workspace_id,
                administrator_id,
                assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
                now=now,
            ),
            environment=environment,
            request_id="system-patch-stale",
            idempotency_key="system-patch-stale-0001",
            request_hash=command.payload_hash,
        )

    assert cast(list[SystemDirectoryEntry], state["systems"])[0].version == 2
    assert cast(list[DomainEvent], state["outbox"]) == []
    assert cast(dict[tuple[UUID, str, str], IdempotencyRecord], state["idempotency"]) == {}


@pytest.mark.asyncio
async def test_system_assignee_patch_is_idempotent_and_writes_one_bounded_audit_event() -> None:
    workspace_id, developer_id, administrator_id, steward_id, second_developer_id = (
        uuid4() for _ in range(5)
    )
    now = datetime.now(UTC)
    state = _state(workspace_id, developer_id, administrator_id, steward_id)
    cast(set[UUID], state["assignable_subjects"]).add(second_developer_id)
    system_id = uuid4()
    state["systems"] = [
        SystemDirectoryEntry(
            system_id=system_id,
            code="FAB",
            name="Fabrication",
            description="",
            active=True,
            version=1,
            assignees=(
                SystemDirectoryAssignee(
                    subject_id=developer_id,
                    display_name="Developer",
                    responsibility="DEVELOPER",
                    priority=1,
                    active=True,
                ),
                SystemDirectoryAssignee(
                    subject_id=steward_id,
                    display_name="Steward",
                    responsibility="DATA_STEWARD",
                    priority=1,
                    active=True,
                ),
            ),
            assignee_count=2,
        )
    ]
    command = _system_patch_command(
        workspace_id,
        system_id,
        upserts=(
            SystemAssigneeUpdate(
                subject_id=second_developer_id,
                responsibility="DEVELOPER",
                priority=2,
            ),
        ),
    )
    service = _service(state, enabled=False)
    subject = _administrator(
        workspace_id,
        administrator_id,
        assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
        now=now,
    )
    environment = EnvironmentAttributes(requested_at=now)
    idempotency_key = "system-patch-idempotency-0001"

    version = await service.patch_system_assignees_with_hardware_key(
        command=command,
        subject=subject,
        environment=environment,
        request_id="system-patch",
        idempotency_key=idempotency_key,
        request_hash=command.payload_hash,
    )
    replayed = await service.patch_system_assignees_with_hardware_key(
        command=command,
        subject=subject,
        environment=environment,
        request_id="system-patch-replay",
        idempotency_key=idempotency_key,
        request_hash=command.payload_hash,
    )

    assert version == replayed == 2
    stored = cast(list[SystemDirectoryEntry], state["systems"])[0]
    assert stored.version == 2
    assert stored.assignee_count == 3
    assert [(item.responsibility, item.priority) for item in stored.assignees] == [
        ("DEVELOPER", 1),
        ("DATA_STEWARD", 1),
        ("DEVELOPER", 2),
    ]
    outbox = cast(list[DomainEvent], state["outbox"])
    assert len(outbox) == 1
    assert outbox[0].event_type == "platform.data_system.assignees_patched.v1"
    assert outbox[0].payload == {
        "actor_id": str(administrator_id),
        "payload_hash": command.payload_hash,
        "system_version": 2,
        "policy_decision_id": outbox[0].payload["policy_decision_id"],
        "assurance": "HARDWARE_WEBAUTHN",
    }
    assert len(str(outbox[0].payload["policy_decision_id"])) == 36

    with pytest.raises(ConflictError, match="different request"):
        await service.patch_system_assignees_with_hardware_key(
            command=command,
            subject=subject,
            environment=environment,
            request_id="system-patch-hash-conflict",
            idempotency_key=idempotency_key,
            request_hash="f" * 64,
        )
    with pytest.raises(ConflictError, match="belongs to another subject"):
        await service.patch_system_assignees_with_hardware_key(
            command=command,
            subject=_administrator(
                workspace_id,
                steward_id,
                assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
                now=now,
            ),
            environment=environment,
            request_id="system-patch-actor-conflict",
            idempotency_key=idempotency_key,
            request_hash=command.payload_hash,
        )
    assert len(cast(list[DomainEvent], state["outbox"])) == 1


@pytest.mark.asyncio
async def test_system_assignee_patch_noop_or_missing_removal_writes_no_evidence() -> None:
    workspace_id, developer_id, administrator_id, steward_id = (uuid4() for _ in range(4))
    now = datetime.now(UTC)
    state = _state(workspace_id, developer_id, administrator_id, steward_id)
    system_id = uuid4()
    current = SystemDirectoryEntry(
        system_id=system_id,
        code="FAB",
        name="Fabrication",
        description="",
        active=True,
        version=1,
        assignees=(
            SystemDirectoryAssignee(
                subject_id=developer_id,
                display_name="Developer",
                responsibility="DEVELOPER",
                priority=1,
                active=True,
            ),
            SystemDirectoryAssignee(
                subject_id=steward_id,
                display_name="Steward",
                responsibility="DATA_STEWARD",
                priority=1,
                active=True,
            ),
        ),
        assignee_count=2,
    )
    state["systems"] = [current]
    service = _service(state, enabled=False)
    subject = _administrator(
        workspace_id,
        administrator_id,
        assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
        now=now,
    )
    environment = EnvironmentAttributes(requested_at=now)
    noop = _system_patch_command(
        workspace_id,
        system_id,
        upserts=(
            SystemAssigneeUpdate(
                subject_id=developer_id,
                responsibility="DEVELOPER",
                priority=1,
            ),
        ),
    )
    missing = _system_patch_command(
        workspace_id,
        system_id,
        removals=(
            SystemAssigneeKey(
                subject_id=uuid4(),
                responsibility="DEVELOPER",
            ),
        ),
    )

    with pytest.raises(ConflictError, match="no effective changes"):
        await service.patch_system_assignees_with_hardware_key(
            command=noop,
            subject=subject,
            environment=environment,
            request_id="system-patch-noop",
            idempotency_key="system-patch-noop-0001",
            request_hash=noop.payload_hash,
        )
    with pytest.raises(ConflictError, match="selected for removal no longer exists"):
        await service.patch_system_assignees_with_hardware_key(
            command=missing,
            subject=subject,
            environment=environment,
            request_id="system-patch-missing",
            idempotency_key="system-patch-missing-0001",
            request_hash=missing.payload_hash,
        )

    assert cast(list[SystemDirectoryEntry], state["systems"]) == [current]
    assert cast(list[DomainEvent], state["outbox"]) == []
    assert cast(dict[tuple[UUID, str, str], IdempotencyRecord], state["idempotency"]) == {}


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
async def test_admin_read_context_does_not_advertise_mutations_for_stale_hardware_auth() -> None:
    workspace_id, target_id, administrator_id, other_admin_id = (uuid4() for _ in range(4))
    now = datetime.now(UTC)
    state = _state(workspace_id, target_id, administrator_id, other_admin_id)
    cast(dict[UUID, WorkspaceMembershipAccessRecord], state["membership_records"])[
        administrator_id
    ] = _membership_record(administrator_id, "Administrator")
    subject = replace(
        _administrator(
            workspace_id,
            administrator_id,
            assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
            now=now,
        ),
        authentication_time=now - timedelta(hours=1),
    )

    context = await _service(state).get_admin_read_context(
        workspace_id=workspace_id,
        subject=subject,
        environment=EnvironmentAttributes(requested_at=now),
        request_id="admin-me-stale-hardware",
    )

    assert AdminOperation.MEMBERSHIP_ACCESS_READ in context.allowed_operations
    assert AdminOperation.MEMBERSHIP_ACCESS_UPDATE not in context.allowed_operations


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
async def test_direct_role_assignment_records_exact_role_and_membership_versions() -> None:
    workspace_id, target_id, administrator_id, other_admin_id, role_id = (uuid4() for _ in range(5))
    now = datetime.now(UTC)
    state = _state(workspace_id, target_id, administrator_id, other_admin_id)
    command = replace(
        _command(workspace_id, target_id),
        groups=frozenset({"engineers", "datariver-role-data-steward"}),
    )

    membership_version = await _service(state).update_membership_with_hardware_key(
        command=command,
        subject=_administrator(
            workspace_id,
            administrator_id,
            assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
            now=now,
        ),
        environment=EnvironmentAttributes(requested_at=now),
        request_id="role-assignment",
        idempotency_key="role-assignment-0001",
        request_hash="a" * 64,
        role_id=role_id,
        role_version=7,
        role_transition=True,
    )
    replayed_version = await _service(state).update_membership_with_hardware_key(
        command=command,
        subject=_administrator(
            workspace_id,
            administrator_id,
            assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
            now=now,
        ),
        environment=EnvironmentAttributes(requested_at=now),
        request_id="role-assignment-replay",
        idempotency_key="role-assignment-0001",
        request_hash="a" * 64,
        role_id=role_id,
        role_version=7,
        role_transition=True,
    )

    assert membership_version == replayed_version == 2
    records = cast(list[dict[str, object]], state["role_assignment_records"])
    assert records == [
        {
            "workspace_id": workspace_id,
            "subject_id": target_id,
            "role_id": role_id,
            "role_version": 7,
            "role_marker": "datariver-role-data-steward",
            "membership_version": 2,
            "access_payload_hash": canonical_json_hash(command.access_document()),
            "actor_id": administrator_id,
        }
    ]
    assert len(cast(list[DomainEvent], state["outbox"])) == 1


@pytest.mark.asyncio
async def test_role_assignment_evidence_failure_rolls_back_membership_and_side_effects() -> None:
    workspace_id, target_id, administrator_id, other_admin_id, role_id = (uuid4() for _ in range(5))
    now = datetime.now(UTC)
    state = _state(workspace_id, target_id, administrator_id, other_admin_id)
    state["role_assignment_failure"] = True
    command = replace(
        _command(workspace_id, target_id),
        groups=frozenset({"engineers", "datariver-role-data-steward"}),
    )

    with pytest.raises(ConflictError, match="evidence write failed"):
        await _service(state).update_membership_with_hardware_key(
            command=command,
            subject=_administrator(
                workspace_id,
                administrator_id,
                assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
                now=now,
            ),
            environment=EnvironmentAttributes(requested_at=now),
            request_id="role-assignment-rollback",
            idempotency_key="role-assignment-rollback-0001",
            request_hash="e" * 64,
            role_id=role_id,
            role_version=7,
            role_transition=True,
        )

    assert cast(dict[UUID, int], state["membership_versions"])[target_id] == 1
    assert cast(list[dict[str, object]], state["role_assignment_records"]) == []
    assert cast(list[DomainEvent], state["outbox"]) == []
    assert cast(dict[tuple[UUID, str, str], IdempotencyRecord], state["idempotency"]) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "authentication_time",
    [None, datetime(2020, 1, 1, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC)],
)
async def test_access_role_mutation_rejects_missing_stale_or_future_hardware_authentication(
    authentication_time: datetime | None,
) -> None:
    workspace_id, administrator_id, other_admin_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    state = _state(workspace_id, uuid4(), administrator_id, other_admin_id)
    writer = MemoryDecisionWriter()
    service = AdminAccessService(
        cast(
            Callable[[], AdminAccessUnitOfWork],
            lambda: MemoryAdminAccessUnitOfWork(state),
        ),
        AuthorizationService(decision_writer=writer),
        fallback_enabled=True,
        fallback_ttl_seconds=300,
    )
    administrator = replace(
        _administrator(
            workspace_id,
            administrator_id,
            assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
            now=now,
        ),
        authentication_time=authentication_time,
    )

    with pytest.raises(ForbiddenError):
        await service.authorize_access_role_mutation(
            workspace_id=workspace_id,
            role_id=uuid4(),
            subject=administrator,
            environment=EnvironmentAttributes(requested_at=now),
            request_id="role-mutation-stale-auth",
        )

    assert writer.decisions[-1][0] == Action.ADMIN_MANAGE.value
    assert writer.decisions[-1][1].allowed is False


@pytest.mark.asyncio
async def test_access_role_mutation_accepts_fresh_hardware_and_audits_decision() -> None:
    workspace_id, administrator_id, other_admin_id, role_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    now = datetime.now(UTC)
    state = _state(workspace_id, uuid4(), administrator_id, other_admin_id)
    writer = MemoryDecisionWriter()
    service = AdminAccessService(
        cast(
            Callable[[], AdminAccessUnitOfWork],
            lambda: MemoryAdminAccessUnitOfWork(state),
        ),
        AuthorizationService(decision_writer=writer),
        fallback_enabled=True,
        fallback_ttl_seconds=300,
    )

    decision_id = await service.authorize_access_role_mutation(
        workspace_id=workspace_id,
        role_id=role_id,
        subject=_administrator(
            workspace_id,
            administrator_id,
            assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
            now=now,
        ),
        environment=EnvironmentAttributes(requested_at=now),
        request_id="role-mutation-fresh-auth",
    )

    action, decision = writer.decisions[-1]
    assert action == Action.ADMIN_MANAGE.value
    assert decision.allowed is True
    assert decision_id == decision.decision_id


@pytest.mark.asyncio
async def test_unbound_manual_membership_update_rejects_reserved_role_marker() -> None:
    workspace_id, target_id, administrator_id, other_admin_id = (uuid4() for _ in range(4))
    now = datetime.now(UTC)
    state = _state(workspace_id, target_id, administrator_id, other_admin_id)
    command = replace(
        _command(workspace_id, target_id),
        groups=frozenset({"datariver-role-reader"}),
    )

    with pytest.raises(ValidationError, match="reserved role marker"):
        await _service(state).update_membership_with_hardware_key(
            command=command,
            subject=_administrator(
                workspace_id,
                administrator_id,
                assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
                now=now,
            ),
            environment=EnvironmentAttributes(requested_at=now),
            request_id="manual-marker-rejection",
            idempotency_key="manual-marker-rejection-0001",
            request_hash="d" * 64,
        )

    assert cast(dict[UUID, int], state["membership_versions"])[target_id] == 1
    assert cast(list[dict[str, object]], state["role_assignment_records"]) == []


@pytest.mark.asyncio
async def test_manual_membership_update_rejects_role_bound_subject_without_side_effects() -> None:
    workspace_id, target_id, administrator_id, other_admin_id = (uuid4() for _ in range(4))
    now = datetime.now(UTC)
    state = _state(workspace_id, target_id, administrator_id, other_admin_id)
    cast(set[UUID], state["role_bound_subjects"]).add(target_id)

    with pytest.raises(ConflictError, match="dedicated Role assignment route"):
        await _service(state).update_membership_with_hardware_key(
            command=_command(workspace_id, target_id),
            subject=_administrator(
                workspace_id,
                administrator_id,
                assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
                now=now,
            ),
            environment=EnvironmentAttributes(requested_at=now),
            request_id="manual-role-bound-rejection",
            idempotency_key="manual-role-bound-rejection-0001",
            request_hash="8" * 64,
        )

    assert cast(dict[UUID, int], state["membership_versions"])[target_id] == 1
    assert cast(list[DomainEvent], state["outbox"]) == []
    assert cast(dict[tuple[UUID, str, str], IdempotencyRecord], state["idempotency"]) == {}


@pytest.mark.asyncio
async def test_manual_membership_update_does_not_emit_role_assignment_evidence() -> None:
    workspace_id, target_id, administrator_id, other_admin_id = (uuid4() for _ in range(4))
    now = datetime.now(UTC)
    state = _state(workspace_id, target_id, administrator_id, other_admin_id)

    version = await _service(state).update_membership_with_hardware_key(
        command=_command(workspace_id, target_id),
        subject=_administrator(
            workspace_id,
            administrator_id,
            assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
            now=now,
        ),
        environment=EnvironmentAttributes(requested_at=now),
        request_id="manual-unbound",
        idempotency_key="manual-unbound-update-0001",
        request_hash="9" * 64,
    )

    assert version == 2
    assert cast(list[dict[str, object]], state["role_assignment_records"]) == []


@pytest.mark.asyncio
async def test_fallback_creation_rejects_role_bound_subject_without_request() -> None:
    workspace_id, target_id, maker_id, checker_id = (uuid4() for _ in range(4))
    now = datetime.now(UTC)
    state = _state(workspace_id, target_id, maker_id, checker_id)
    cast(set[UUID], state["role_bound_subjects"]).add(target_id)

    with pytest.raises(ConflictError, match="dedicated Role assignment route"):
        await _service(state).create_fallback_request(
            command=_command(workspace_id, target_id),
            reason="Attempt a generic fallback change",
            subject=_administrator(
                workspace_id,
                maker_id,
                assurance=AuthenticationAssurance.PASSWORD_REAUTH,
                now=now,
            ),
            environment=EnvironmentAttributes(requested_at=now),
            request_id="fallback-role-bound-create",
            idempotency_key="fallback-role-bound-create-0001",
            request_hash="7" * 64,
        )

    assert cast(dict[UUID, AdminAccessRequest], state["requests"]) == {}
    assert cast(list[DomainEvent], state["outbox"]) == []


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
    assert cast(list[dict[str, object]], state["role_assignment_records"]) == []
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
async def test_fallback_consumption_rejects_role_assigned_after_approval() -> None:
    workspace_id, target_id, maker_id, checker_id = (uuid4() for _ in range(4))
    now = datetime.now(UTC)
    state = _state(workspace_id, target_id, maker_id, checker_id)
    service = _service(state)
    environment = EnvironmentAttributes(requested_at=now)
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
    request = await service.create_fallback_request(
        command=_command(workspace_id, target_id),
        reason="Correct access",
        subject=maker,
        environment=environment,
        request_id="fallback-role-race-create",
        idempotency_key="fallback-role-race-create-0001",
        request_hash="4" * 64,
    )
    approved = await service.decide_fallback_request(
        workspace_id=workspace_id,
        access_request_id=request.access_request_id,
        approval_decision=AdminAccessDecision.APPROVED,
        reason="Independent review",
        expected_version=1,
        subject=checker,
        environment=environment,
        request_id="fallback-role-race-approve",
        idempotency_key="fallback-role-race-approve-0001",
        request_hash="5" * 64,
    )
    cast(set[UUID], state["role_bound_subjects"]).add(target_id)

    with pytest.raises(ConflictError, match="dedicated Role assignment route"):
        await service.consume_fallback_request(
            workspace_id=workspace_id,
            access_request_id=approved.access_request_id,
            confirmed_payload_hash=approved.payload_hash,
            expected_version=2,
            subject=maker,
            environment=environment,
            request_id="fallback-role-race-consume",
            idempotency_key="fallback-role-race-consume-0001",
            request_hash="6" * 64,
        )

    assert cast(dict[UUID, int], state["membership_versions"])[target_id] == 1
    stored = cast(dict[UUID, AdminAccessRequest], state["requests"])[approved.access_request_id]
    assert stored.state is AdminAccessRequestState.APPROVED


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
