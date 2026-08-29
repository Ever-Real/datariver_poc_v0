from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Dialect
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.domain.admin_access import (
    SystemAssigneeKey,
    SystemAssigneePatchCommand,
    SystemAssigneeUpdate,
)
from datariver.domain.authz import Action, Classification
from datariver.domain.capability_catalog import (
    CANONICAL_ADMIN_CAPABILITY_HASH,
    CANONICAL_ADMIN_ROLE_KEY,
    CAPABILITY_CATALOG_VERSION,
    DEFAULT_HUMAN_ADMIN_ACTIONS,
    AccessRoleKind,
    AccessRoleManagementSource,
)
from datariver.domain.common import ConflictError, ValidationError
from datariver.infrastructure.db.admin_access import (
    SqlSystemDirectoryRepository,
    _canonical_admin_binding_evidence,
    _decode_membership_cursor,
    _encode_membership_cursor,
    _membership_access_record,
    decode_admin_list_cursor,
    encode_admin_list_cursor,
    membership_access_payload_hash,
)
from datariver.infrastructure.db.models.platform import (
    AccessRoleModel,
    CanonicalAdminBindingModel,
    DataSystemModel,
    SubjectModel,
    SystemAssigneeModel,
    WorkspaceMembershipModel,
)
from datariver.interfaces.http.presenters import workspace_membership_access_response

POSTGRES_DIALECT = cast(Callable[[], Dialect], postgresql.dialect)()


@pytest.mark.asyncio
async def test_system_code_collision_lookup_is_workspace_scoped_and_case_insensitive() -> None:
    workspace_id = uuid4()
    session = _SystemRepositorySession(scalar_results=[[True]])

    exists = await SqlSystemDirectoryRepository(cast(AsyncSession, session)).code_exists(
        workspace_id=workspace_id,
        code="CUSTOMER-DATA",
    )

    assert exists is True
    statement = _compiled_postgres(session.scalar_statements[0])
    assert "data_systems.workspace_id" in statement
    assert "lower(platform.data_systems.code)" in statement


def _stored_membership() -> tuple[SubjectModel, WorkspaceMembershipModel]:
    subject_id, workspace_id, department_id, system_id, domain_id = (uuid4() for _ in range(5))
    subject = SubjectModel(
        id=subject_id,
        issuer="https://identity.example.internal/realms/company",
        external_subject="external-subject",
        display_name="Security Administrator",
        active=True,
    )
    membership = WorkspaceMembershipModel(
        workspace_id=workspace_id,
        subject_id=subject_id,
        department_id=department_id,
        job_function="SECURITY_ADMINISTRATOR",
        clearance=int(Classification.RESTRICTED),
        attributes={
            "groups": ["security-administrators"],
            "allowed_actions": [Action.ADMIN_MANAGE.value, Action.CATALOG_READ.value],
            "denied_actions": [Action.CHAT_QUERY.value],
            "allowed_system_ids": [str(system_id)],
            "allowed_domain_ids": [str(domain_id)],
            "managed_by": "WORKSPACE_MEMBERSHIP_ACCESS_UPDATE_V1",
        },
        active=True,
        access_expires_at=datetime(2027, 1, 1, tzinfo=UTC),
        version=7,
    )
    return subject, membership


def test_membership_repository_mapping_returns_the_exact_typed_access_document() -> None:
    subject, membership = _stored_membership()

    record = _membership_access_record(subject, membership)

    assert record.summary.subject_id == subject.id
    assert record.summary.display_name == "Security Administrator"
    assert record.summary.department_id == membership.department_id
    assert record.summary.job_function == "SECURITY_ADMINISTRATOR"
    assert record.summary.clearance is Classification.RESTRICTED
    assert record.summary.membership_version == 7
    assert record.groups == frozenset({"security-administrators"})
    assert record.allowed_actions == frozenset({Action.ADMIN_MANAGE, Action.CATALOG_READ})
    assert record.denied_actions == frozenset({Action.CHAT_QUERY})
    assert {str(value) for value in record.allowed_system_ids} == set(
        membership.attributes["allowed_system_ids"]
    )


def test_membership_repository_mapping_fails_closed_on_unknown_action() -> None:
    subject, membership = _stored_membership()
    membership.attributes["allowed_actions"] = ["provider.arbitrary-action"]

    with pytest.raises(ConflictError, match="stored workspace membership access is invalid"):
        _membership_access_record(subject, membership)


def test_canonical_admin_binding_status_rechecks_exact_role_membership_and_scope_hash() -> None:
    workspace_id, subject_id, domain_id = uuid4(), uuid4(), uuid4()
    subject = SubjectModel(
        id=subject_id,
        issuer="https://identity.example.internal/realms/company",
        external_subject="canonical-admin",
        display_name="Canonical Administrator",
        active=True,
    )
    membership = WorkspaceMembershipModel(
        workspace_id=workspace_id,
        subject_id=subject_id,
        job_function="SECURITY_ADMINISTRATOR",
        clearance=int(Classification.RESTRICTED),
        attributes={
            "groups": ["security-administrators"],
            "allowed_actions": sorted(action.value for action in DEFAULT_HUMAN_ADMIN_ACTIONS),
            "denied_actions": [],
            "allowed_system_ids": [],
            "allowed_domain_ids": [str(domain_id)],
        },
        active=True,
        access_expires_at=None,
        version=5,
    )
    role = AccessRoleModel(
        id=uuid4(),
        workspace_id=workspace_id,
        role_key=CANONICAL_ADMIN_ROLE_KEY,
        role_kind=AccessRoleKind.CANONICAL_ADMIN.value,
        management_source=AccessRoleManagementSource.SERVER_CANONICAL.value,
        capability_catalog_version=CAPABILITY_CATALOG_VERSION,
        name="Canonical Admin",
        description="Server-owned Canonical Admin capability definition.",
        clearance=int(Classification.RESTRICTED),
        groups=["security-administrators"],
        allowed_actions=sorted(action.value for action in DEFAULT_HUMAN_ADMIN_ACTIONS),
        denied_actions=[],
        allowed_system_ids=[],
        allowed_domain_ids=[],
        active=True,
        updated_by=None,
        version=3,
    )
    binding = CanonicalAdminBindingModel(
        workspace_id=workspace_id,
        subject_id=subject_id,
        canonical_role_id=role.id,
        role_kind=AccessRoleKind.CANONICAL_ADMIN.value,
        canonical_role_version=role.version,
        capability_catalog_version=CAPABILITY_CATALOG_VERSION,
        capability_hash=CANONICAL_ADMIN_CAPABILITY_HASH,
        membership_version=membership.version,
        membership_access_hash=membership_access_payload_hash(membership),
        state="ACTIVE",
        binding_source="LOCAL_DEVELOPMENT_BOOTSTRAP",
        version=1,
        updated_at=datetime(2026, 8, 1, tzinfo=UTC),
    )

    evidence = _canonical_admin_binding_evidence(
        subject=subject,
        membership=membership,
        binding=binding,
        role=role,
    )
    assert evidence.status == "VERIFIED"
    response = workspace_membership_access_response(
        _membership_access_record(
            subject,
            membership,
            canonical_admin_binding=evidence,
        )
    )
    binding_document = response.canonical_admin_binding.model_dump()
    assert set(binding_document) == {
        "status",
        "role_version",
        "catalog_version",
        "membership_version",
        "binding_version",
        "updated_at",
    }
    assert not any("hash" in key or key.endswith("_id") for key in binding_document)

    membership.attributes["allowed_domain_ids"] = [str(uuid4())]
    assert (
        _canonical_admin_binding_evidence(
            subject=subject,
            membership=membership,
            binding=binding,
            role=role,
        ).status
        == "STALE"
    )
    binding.state = "REVOKED"
    assert (
        _canonical_admin_binding_evidence(
            subject=subject,
            membership=membership,
            binding=binding,
            role=role,
        ).status
        == "REVOKED"
    )


def test_membership_cursor_is_bound_to_workspace_query_and_status() -> None:
    workspace_id, subject_id = uuid4(), uuid4()
    cursor = _encode_membership_cursor(
        workspace_id=workspace_id,
        query="engineer",
        active=True,
        display_name="engineer a",
        subject_id=subject_id,
    )

    assert _decode_membership_cursor(
        cursor,
        workspace_id=workspace_id,
        query="engineer",
        active=True,
    ) == ("engineer a", subject_id)

    with pytest.raises(ValidationError, match="does not match"):
        _decode_membership_cursor(
            cursor,
            workspace_id=uuid4(),
            query="engineer",
            active=True,
        )
    with pytest.raises(ValidationError, match="does not match"):
        _decode_membership_cursor(
            cursor,
            workspace_id=workspace_id,
            query="steward",
            active=True,
        )


def test_admin_list_cursor_is_canonical_and_bound_to_scope_workspace_and_filters() -> None:
    workspace_id, boundary_id = uuid4(), uuid4()
    filters: dict[str, str | bool | None] = {"state": "PENDING", "active": True}
    cursor = encode_admin_list_cursor(
        scope="MEMBERSHIP_RENEWALS",
        workspace_id=workspace_id,
        filters=filters,
        boundary_id=boundary_id,
    )

    assert (
        decode_admin_list_cursor(
            cursor,
            scope="MEMBERSHIP_RENEWALS",
            workspace_id=workspace_id,
            filters=filters,
        )
        == boundary_id
    )

    with pytest.raises(ValidationError, match="does not match"):
        decode_admin_list_cursor(
            cursor,
            scope="ADMIN_FALLBACK_REQUESTS",
            workspace_id=workspace_id,
            filters=filters,
        )
    with pytest.raises(ValidationError, match="does not match"):
        decode_admin_list_cursor(
            cursor,
            scope="MEMBERSHIP_RENEWALS",
            workspace_id=uuid4(),
            filters=filters,
        )
    with pytest.raises(ValidationError, match="does not match"):
        decode_admin_list_cursor(
            cursor,
            scope="MEMBERSHIP_RENEWALS",
            workspace_id=workspace_id,
            filters={"state": "APPROVED", "active": True},
        )


@pytest.mark.parametrize("cursor", ["not-base64!", "e30", ""])
def test_admin_list_cursor_rejects_malformed_or_incomplete_documents(cursor: str) -> None:
    with pytest.raises(ValidationError, match="does not match"):
        decode_admin_list_cursor(
            cursor,
            scope="SYSTEM_DIRECTORY",
            workspace_id=uuid4(),
            filters={"query": None, "active": None},
        )


class _ScalarResult:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def one_or_none(self) -> Any | None:
        if len(self._values) > 1:
            raise AssertionError("one_or_none received multiple fake rows")
        return self._values[0] if self._values else None

    def all(self) -> list[Any]:
        return list(self._values)


class _ExecuteResult:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[object, ...]]:
        return list(self._rows)


class _SystemRepositorySession:
    def __init__(
        self,
        *,
        scalar_results: list[list[Any]],
        execute_results: list[list[tuple[object, ...]]] | None = None,
    ) -> None:
        self.scalar_results = scalar_results
        self.execute_results = execute_results or []
        self.scalar_statements: list[object] = []
        self.execute_statements: list[object] = []
        self.execute_count = 0
        self.added: list[object] = []
        self.flush_count = 0

    async def scalar(self, statement: object) -> Any | None:
        self.scalar_statements.append(statement)
        if not self.scalar_results:
            raise AssertionError("unexpected scalar query")
        values = self.scalar_results.pop(0)
        if len(values) > 1:
            raise AssertionError("scalar received multiple fake rows")
        return values[0] if values else None

    async def scalars(self, statement: object) -> _ScalarResult:
        self.scalar_statements.append(statement)
        if not self.scalar_results:
            raise AssertionError("unexpected scalar query")
        return _ScalarResult(self.scalar_results.pop(0))

    async def execute(self, statement: object) -> _ExecuteResult:
        self.execute_statements.append(statement)
        self.execute_count += 1
        if not self.execute_results:
            raise AssertionError("unexpected execute query")
        return _ExecuteResult(self.execute_results.pop(0))

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flush_count += 1


def _stored_system(
    *,
    workspace_id: UUID | None = None,
    system_id: UUID | None = None,
    version: int = 1,
) -> DataSystemModel:
    return DataSystemModel(
        id=system_id or uuid4(),
        workspace_id=workspace_id or uuid4(),
        code="FAB",
        name="Fabrication",
        description="",
        active=True,
        version=version,
    )


def _stored_assignee(
    *,
    workspace_id: UUID,
    system_id: UUID,
    subject_id: UUID,
    responsibility: str,
    priority: int,
) -> SystemAssigneeModel:
    return SystemAssigneeModel(
        id=uuid4(),
        workspace_id=workspace_id,
        system_id=system_id,
        subject_id=subject_id,
        responsibility=responsibility,
        priority=priority,
        active=True,
        version=1,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["workspace", "system", "version"])
async def test_system_assignee_cursor_is_bound_to_workspace_system_and_version(
    mismatch: str,
) -> None:
    cursor_workspace_id, cursor_system_id = uuid4(), uuid4()
    requested_workspace_id = uuid4() if mismatch == "workspace" else cursor_workspace_id
    requested_system_id = uuid4() if mismatch == "system" else cursor_system_id
    stored_version = 2 if mismatch == "version" else 1
    system = _stored_system(
        workspace_id=requested_workspace_id,
        system_id=requested_system_id,
        version=stored_version,
    )
    session = _SystemRepositorySession(scalar_results=[[system]])
    cursor = encode_admin_list_cursor(
        scope="SYSTEM_ASSIGNEES",
        workspace_id=cursor_workspace_id,
        filters={
            "system_id": str(cursor_system_id),
            "system_version": "1",
        },
        boundary_id=uuid4(),
    )

    with pytest.raises(ValidationError, match="stale or does not match"):
        await SqlSystemDirectoryRepository(cast(AsyncSession, session)).list_assignees(
            workspace_id=requested_workspace_id,
            system_id=requested_system_id,
            limit=25,
            cursor=cursor,
        )

    assert session.execute_count == 0


def _compiled_postgres(statement: object) -> str:
    return str(cast(Any, statement).compile(dialect=POSTGRES_DIALECT))


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [25, 100])
async def test_system_assignee_repository_returns_a_bounded_page_and_versioned_cursor(
    limit: int,
) -> None:
    workspace_id, system_id = uuid4(), uuid4()
    system = _stored_system(
        workspace_id=workspace_id,
        system_id=system_id,
        version=7,
    )
    rows: list[tuple[object, ...]] = []
    for priority in range(1, limit + 2):
        subject_id = uuid4()
        assignment = _stored_assignee(
            workspace_id=workspace_id,
            system_id=system_id,
            subject_id=subject_id,
            responsibility="DEVELOPER",
            priority=priority,
        )
        subject = SubjectModel(
            id=subject_id,
            issuer="https://identity.example.internal/realms/company",
            external_subject=f"subject-{priority}",
            display_name=f"Developer {priority}",
            active=True,
        )
        membership = WorkspaceMembershipModel(
            workspace_id=workspace_id,
            subject_id=subject_id,
            clearance=int(Classification.INTERNAL),
            attributes={},
            active=True,
            access_expires_at=None,
            version=1,
        )
        rows.append((assignment, subject, membership))
    session = _SystemRepositorySession(
        scalar_results=[[system]],
        execute_results=[rows],
    )

    page = await SqlSystemDirectoryRepository(cast(AsyncSession, session)).list_assignees(
        workspace_id=workspace_id,
        system_id=system_id,
        limit=limit,
    )

    assert len(page.items) == limit
    assert page.system_version == 7
    assert page.next_cursor is not None
    assert (
        decode_admin_list_cursor(
            page.next_cursor,
            scope="SYSTEM_ASSIGNEES",
            workspace_id=workspace_id,
            filters={
                "system_id": str(system_id),
                "system_version": "7",
            },
        )
        == cast(SystemAssigneeModel, rows[limit - 1][0]).id
    )
    assert session.execute_count == 1
    assert "FOR SHARE" in _compiled_postgres(session.scalar_statements[0])


@pytest.mark.asyncio
async def test_system_assignee_repository_rejects_a_missing_removal_without_version_change() -> (
    None
):
    workspace_id, system_id, subject_id = uuid4(), uuid4(), uuid4()
    system = _stored_system(workspace_id=workspace_id, system_id=system_id)
    session = _SystemRepositorySession(scalar_results=[[system], []])
    command = SystemAssigneePatchCommand(
        workspace_id=workspace_id,
        system_id=system_id,
        expected_system_version=1,
        upserts=(),
        removals=(SystemAssigneeKey(subject_id=subject_id, responsibility="DEVELOPER"),),
    )

    with pytest.raises(ConflictError, match="selected for removal no longer exists") as caught:
        await SqlSystemDirectoryRepository(cast(AsyncSession, session)).patch_assignees(command)

    assert caught.value.details == {
        "missing": [
            {
                "subject_id": str(subject_id),
                "responsibility": "DEVELOPER",
            }
        ]
    }
    assert system.version == 1
    assert session.execute_count == 0
    assert session.flush_count == 0


@pytest.mark.asyncio
async def test_system_assignee_repository_soft_deactivates_removal_and_counts_active_lanes() -> (
    None
):
    workspace_id, system_id, subject_id = uuid4(), uuid4(), uuid4()
    system = _stored_system(workspace_id=workspace_id, system_id=system_id)
    assignment = _stored_assignee(
        workspace_id=workspace_id,
        system_id=system_id,
        subject_id=subject_id,
        responsibility="DEVELOPER",
        priority=2,
    )
    session = _SystemRepositorySession(
        scalar_results=[[system], [assignment]],
        execute_results=[
            [
                ("DEVELOPER", 1, 1, 1),
                ("DATA_STEWARD", 1, 1, 1),
            ]
        ],
    )
    command = SystemAssigneePatchCommand(
        workspace_id=workspace_id,
        system_id=system_id,
        expected_system_version=1,
        upserts=(),
        removals=(SystemAssigneeKey(subject_id=subject_id, responsibility="DEVELOPER"),),
    )

    version = await SqlSystemDirectoryRepository(cast(AsyncSession, session)).patch_assignees(
        command
    )

    assert version == 2
    assert assignment.active is False
    assert assignment.version == 2
    assert session.execute_count == 1
    assert "system_assignees.active IS true" in _compiled_postgres(session.execute_statements[0])


@pytest.mark.asyncio
async def test_system_assignee_repository_reactivates_an_inactive_row() -> None:
    workspace_id, system_id, subject_id = uuid4(), uuid4(), uuid4()
    system = _stored_system(workspace_id=workspace_id, system_id=system_id)
    assignment = _stored_assignee(
        workspace_id=workspace_id,
        system_id=system_id,
        subject_id=subject_id,
        responsibility="DEVELOPER",
        priority=2,
    )
    assignment.active = False
    session = _SystemRepositorySession(
        scalar_results=[[system], [subject_id], [assignment]],
        execute_results=[
            [
                ("DEVELOPER", 1, 1, 1),
                ("DATA_STEWARD", 1, 1, 1),
            ]
        ],
    )
    command = SystemAssigneePatchCommand(
        workspace_id=workspace_id,
        system_id=system_id,
        expected_system_version=1,
        upserts=(
            SystemAssigneeUpdate(
                subject_id=subject_id,
                responsibility="DEVELOPER",
                priority=1,
            ),
        ),
        removals=(),
    )

    version = await SqlSystemDirectoryRepository(cast(AsyncSession, session)).patch_assignees(
        command
    )

    assert version == 2
    assert assignment.active is True
    assert assignment.priority == 1
    assert assignment.version == 2


@pytest.mark.asyncio
async def test_system_assignee_repository_rejects_an_identical_only_upsert() -> None:
    workspace_id, system_id, subject_id = uuid4(), uuid4(), uuid4()
    system = _stored_system(workspace_id=workspace_id, system_id=system_id)
    assignment = _stored_assignee(
        workspace_id=workspace_id,
        system_id=system_id,
        subject_id=subject_id,
        responsibility="DEVELOPER",
        priority=1,
    )
    session = _SystemRepositorySession(
        scalar_results=[[system], [subject_id], [assignment]],
    )
    command = SystemAssigneePatchCommand(
        workspace_id=workspace_id,
        system_id=system_id,
        expected_system_version=1,
        upserts=(
            SystemAssigneeUpdate(
                subject_id=subject_id,
                responsibility="DEVELOPER",
                priority=1,
            ),
        ),
        removals=(),
    )

    with pytest.raises(ConflictError, match="no effective changes"):
        await SqlSystemDirectoryRepository(cast(AsyncSession, session)).patch_assignees(command)

    assert system.version == 1
    assert assignment.version == 1
    assert session.execute_count == 0
    assert session.flush_count == 0


@pytest.mark.asyncio
async def test_system_assignee_repository_ignores_identical_rows_in_a_mixed_patch() -> None:
    workspace_id, system_id = uuid4(), uuid4()
    existing_subject_id, new_subject_id = uuid4(), uuid4()
    system = _stored_system(workspace_id=workspace_id, system_id=system_id)
    existing = _stored_assignee(
        workspace_id=workspace_id,
        system_id=system_id,
        subject_id=existing_subject_id,
        responsibility="DEVELOPER",
        priority=1,
    )
    session = _SystemRepositorySession(
        scalar_results=[
            [system],
            [existing_subject_id, new_subject_id],
            [existing],
        ],
        execute_results=[
            [
                ("DEVELOPER", 2, 1, 2),
                ("DATA_STEWARD", 1, 1, 1),
            ]
        ],
    )
    command = SystemAssigneePatchCommand(
        workspace_id=workspace_id,
        system_id=system_id,
        expected_system_version=1,
        upserts=(
            SystemAssigneeUpdate(
                subject_id=existing_subject_id,
                responsibility="DEVELOPER",
                priority=1,
            ),
            SystemAssigneeUpdate(
                subject_id=new_subject_id,
                responsibility="DEVELOPER",
                priority=2,
            ),
        ),
        removals=(),
    )

    version = await SqlSystemDirectoryRepository(cast(AsyncSession, session)).patch_assignees(
        command
    )

    assert version == 2
    assert existing.version == 1
    assert len(session.added) == 1
    added = cast(SystemAssigneeModel, session.added[0])
    assert (added.subject_id, added.priority) == (new_subject_id, 2)
    assert session.execute_count == 1
    assert session.flush_count == 2
