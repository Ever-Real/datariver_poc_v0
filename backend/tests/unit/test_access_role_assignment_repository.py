from __future__ import annotations

from dataclasses import replace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.domain.admin_access import MembershipAccessUpdate
from datariver.domain.authz import Action, Classification
from datariver.domain.common import ConflictError, canonical_json_hash
from datariver.infrastructure.db.admin_access import SqlMembershipAccessRepository
from datariver.infrastructure.db.models.platform import (
    AccessRoleAssignmentEventModel,
    AccessRoleAssignmentModel,
    AccessRoleModel,
)


class ScalarResult:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def one_or_none(self) -> object | None:
        return self._value


class AssignmentSession:
    def __init__(self) -> None:
        self.current: AccessRoleAssignmentModel | None = None
        self.selected_role: AccessRoleModel | None = None
        self.events: list[AccessRoleAssignmentEventModel] = []

    async def scalars(self, statement: Any) -> ScalarResult:
        entity = statement.column_descriptions[0].get("entity")
        if entity is AccessRoleAssignmentModel:
            return ScalarResult(self.current)
        if entity is AccessRoleModel:
            return ScalarResult(self.selected_role)
        raise AssertionError(f"Unexpected scalar entity: {entity}")

    def add(self, value: object) -> None:
        if isinstance(value, AccessRoleAssignmentModel):
            if value.version is None:
                value.version = 1
            self.current = value
            return
        if isinstance(value, AccessRoleAssignmentEventModel):
            self.events.append(value)
            return
        raise AssertionError(f"Unexpected model: {type(value)}")

    async def flush(self) -> None:
        return None


def _role(workspace_id: UUID, *, version: int) -> AccessRoleModel:
    return AccessRoleModel(
        id=uuid4(),
        workspace_id=workspace_id,
        role_key=f"role-{version}",
        name=f"Role {version}",
        description="",
        clearance=2,
        groups=[],
        allowed_actions=[],
        denied_actions=[],
        allowed_system_ids=[],
        allowed_domain_ids=[],
        active=True,
        updated_by=uuid4(),
        version=version,
    )


@pytest.mark.asyncio
async def test_assignment_repository_records_assigned_reassigned_removed_transition() -> None:
    workspace_id, subject_id, actor_id = uuid4(), uuid4(), uuid4()
    session = AssignmentSession()
    repository = SqlMembershipAccessRepository(cast(AsyncSession, session))
    first = _role(workspace_id, version=3)
    second = _role(workspace_id, version=5)

    session.selected_role = first
    await repository.record_role_assignment(
        workspace_id=workspace_id,
        subject_id=subject_id,
        role_id=first.id,
        role_version=first.version,
        role_marker=f"datariver-role-{first.role_key}",
        membership_version=2,
        access_payload_hash="a" * 64,
        actor_id=actor_id,
    )
    session.selected_role = second
    await repository.record_role_assignment(
        workspace_id=workspace_id,
        subject_id=subject_id,
        role_id=second.id,
        role_version=second.version,
        role_marker=f"datariver-role-{second.role_key}",
        membership_version=3,
        access_payload_hash="b" * 64,
        actor_id=actor_id,
    )
    await repository.record_role_assignment(
        workspace_id=workspace_id,
        subject_id=subject_id,
        role_id=None,
        role_version=None,
        role_marker=None,
        membership_version=4,
        access_payload_hash="c" * 64,
        actor_id=actor_id,
    )

    assert session.current is not None
    assert session.current.active is False
    assert session.current.role_id == second.id
    assert session.current.role_version == second.version
    assert session.current.membership_version == 4
    assert [event.event_type for event in session.events] == [
        "ASSIGNED",
        "REASSIGNED",
        "REMOVED",
    ]
    assert session.events[1].previous_role_id == first.id
    assert session.events[1].previous_role_version == first.version
    assert session.events[2].previous_role_id == second.id
    assert session.events[2].role_id is None


@pytest.mark.asyncio
async def test_assignment_repository_rejects_role_version_race_before_writing_evidence() -> None:
    workspace_id, subject_id, actor_id = uuid4(), uuid4(), uuid4()
    session = AssignmentSession()
    repository = SqlMembershipAccessRepository(cast(AsyncSession, session))

    with pytest.raises(ConflictError, match="changed before assignment"):
        await repository.record_role_assignment(
            workspace_id=workspace_id,
            subject_id=subject_id,
            role_id=uuid4(),
            role_version=7,
            role_marker="datariver-role-role-7",
            membership_version=2,
            access_payload_hash="a" * 64,
            actor_id=actor_id,
        )

    assert session.current is None
    assert session.events == []


@pytest.mark.asyncio
async def test_assignment_repository_rejects_marker_that_does_not_match_locked_role() -> None:
    workspace_id, subject_id, actor_id = uuid4(), uuid4(), uuid4()
    session = AssignmentSession()
    repository = SqlMembershipAccessRepository(cast(AsyncSession, session))
    role = _role(workspace_id, version=7)
    session.selected_role = role

    with pytest.raises(ConflictError, match="marker does not match"):
        await repository.record_role_assignment(
            workspace_id=workspace_id,
            subject_id=subject_id,
            role_id=role.id,
            role_version=role.version,
            role_marker="datariver-role-a-different-role",
            membership_version=2,
            access_payload_hash="a" * 64,
            actor_id=actor_id,
        )

    assert session.current is None
    assert session.events == []


@pytest.mark.asyncio
async def test_assignment_repository_rejects_exact_same_role_reaffirmation() -> None:
    workspace_id, subject_id, actor_id = uuid4(), uuid4(), uuid4()
    session = AssignmentSession()
    repository = SqlMembershipAccessRepository(cast(AsyncSession, session))
    role = _role(workspace_id, version=7)
    original_command = MembershipAccessUpdate(
        workspace_id=workspace_id,
        target_subject_id=subject_id,
        expected_membership_version=2,
        active=True,
        clearance=Classification.CONFIDENTIAL,
        groups=frozenset({"engineers", f"datariver-role-{role.role_key}"}),
        allowed_actions=frozenset({Action.CATALOG_READ}),
        denied_actions=frozenset(),
    )
    reaffirmation_command = replace(original_command, expected_membership_version=3)
    access_payload_hash = canonical_json_hash(original_command.access_document())

    assert original_command.payload_hash != reaffirmation_command.payload_hash
    assert access_payload_hash == canonical_json_hash(reaffirmation_command.access_document())

    session.selected_role = role
    session.current = AccessRoleAssignmentModel(
        workspace_id=workspace_id,
        subject_id=subject_id,
        role_id=role.id,
        role_version=role.version,
        membership_version=2,
        access_payload_hash=access_payload_hash,
        assigned_by=actor_id,
        active=True,
        version=1,
    )

    with pytest.raises(ConflictError, match="already has this exact access role"):
        await repository.record_role_assignment(
            workspace_id=workspace_id,
            subject_id=subject_id,
            role_id=role.id,
            role_version=role.version,
            role_marker=f"datariver-role-{role.role_key}",
            membership_version=3,
            access_payload_hash=canonical_json_hash(reaffirmation_command.access_document()),
            actor_id=actor_id,
        )

    assert session.current.membership_version == 2
    assert session.current.version == 1
    assert session.events == []
