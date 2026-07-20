from __future__ import annotations

from types import TracebackType
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.application.dto import (
    SystemDirectoryAssignee,
    SystemDirectoryEntry,
    WorkspaceMembershipAccessRecord,
    WorkspaceMembershipSummary,
)
from datariver.application.ports import (
    AdminAccessRequestRepository,
    AdminAccessUnitOfWork,
    MembershipAccessRepository,
    SystemDirectoryRepository,
)
from datariver.domain.admin_access import (
    MEMBERSHIP_ACCESS_COMMAND,
    AdminAccessApproval,
    AdminAccessDecision,
    AdminAccessRequest,
    AdminAccessRequestState,
    MembershipAccessUpdate,
    SystemAssigneeUpdateCommand,
)
from datariver.domain.authz import Action, Classification
from datariver.domain.common import ConflictError, ForbiddenError, NotFoundError, ValidationError
from datariver.infrastructure.db.governance import SqlIdempotencyStore, SqlOutboxWriter
from datariver.infrastructure.db.models.catalog import AssetProjectionModel
from datariver.infrastructure.db.models.governance import ChangeRequestModel
from datariver.infrastructure.db.models.platform import (
    AdminAccessApprovalModel,
    AdminAccessRequestModel,
    DataSystemModel,
    SubjectModel,
    SystemAssigneeModel,
    WorkspaceMembershipModel,
)
from datariver.infrastructure.db.rls import set_security_context


class SqlAdminAccessRequestRepository(AdminAccessRequestRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, request: AdminAccessRequest) -> None:
        self._session.add(_request_model(request))

    async def get_for_update(
        self, *, workspace_id: UUID, access_request_id: UUID
    ) -> AdminAccessRequest | None:
        model = (
            await self._session.scalars(
                select(AdminAccessRequestModel)
                .where(
                    AdminAccessRequestModel.workspace_id == workspace_id,
                    AdminAccessRequestModel.id == access_request_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        return await self._hydrate(model)

    async def get(
        self, *, workspace_id: UUID, access_request_id: UUID
    ) -> AdminAccessRequest | None:
        model = (
            await self._session.scalars(
                select(AdminAccessRequestModel).where(
                    AdminAccessRequestModel.workspace_id == workspace_id,
                    AdminAccessRequestModel.id == access_request_id,
                )
            )
        ).one_or_none()
        return await self._hydrate(model)

    async def list(
        self, *, workspace_id: UUID, state: str | None, limit: int
    ) -> tuple[AdminAccessRequest, ...]:
        statement = (
            select(AdminAccessRequestModel)
            .where(AdminAccessRequestModel.workspace_id == workspace_id)
            .order_by(AdminAccessRequestModel.created_at.desc())
            .limit(limit)
        )
        if state is not None:
            statement = statement.where(AdminAccessRequestModel.state == state)
        models = (await self._session.scalars(statement)).all()
        values: list[AdminAccessRequest] = []
        for model in models:
            hydrated = await self._hydrate(model)
            if hydrated is not None:
                values.append(hydrated)
        return tuple(values)

    async def save(self, request: AdminAccessRequest) -> None:
        model = await self._session.get(AdminAccessRequestModel, request.access_request_id)
        if model is None or model.workspace_id != request.workspace_id:
            raise NotFoundError("The administrator fallback request does not exist.")
        model.state = request.state.value
        model.version = request.version
        model.checker_id = request.checker_id
        model.consumed_by = request.consumed_by
        model.consumed_at = request.consumed_at
        model.consume_policy_decision_id = request.consume_policy_decision_id
        stored_ids = set(
            (
                await self._session.scalars(
                    select(AdminAccessApprovalModel.id).where(
                        AdminAccessApprovalModel.workspace_id == request.workspace_id,
                        AdminAccessApprovalModel.access_request_id == request.access_request_id,
                    )
                )
            ).all()
        )
        self._session.add_all(
            [
                AdminAccessApprovalModel(
                    id=approval.approval_id,
                    workspace_id=request.workspace_id,
                    access_request_id=request.access_request_id,
                    actor_id=approval.actor_id,
                    decision=approval.decision.value,
                    reason=approval.reason,
                    policy_decision_id=approval.policy_decision_id,
                    payload_hash=approval.payload_hash,
                    request_version=approval.request_version,
                    occurred_at=approval.occurred_at,
                )
                for approval in request.approvals
                if approval.approval_id not in stored_ids
            ]
        )

    async def _hydrate(self, model: AdminAccessRequestModel | None) -> AdminAccessRequest | None:
        if model is None:
            return None
        command = MembershipAccessUpdate.from_command_document(model.command_document)
        if (
            command.payload_hash != model.payload_hash
            or model.command_type != MEMBERSHIP_ACCESS_COMMAND
        ):
            raise ConflictError(
                "The stored administrator fallback command failed integrity checks."
            )
        approval_models = (
            await self._session.scalars(
                select(AdminAccessApprovalModel)
                .where(
                    AdminAccessApprovalModel.workspace_id == model.workspace_id,
                    AdminAccessApprovalModel.access_request_id == model.id,
                )
                .order_by(AdminAccessApprovalModel.occurred_at)
            )
        ).all()
        if command.workspace_id != model.workspace_id or command.target_subject_id != (
            model.target_subject_id
        ):
            raise ConflictError(
                "The stored administrator fallback command does not match its envelope."
            )
        if any(approval.payload_hash != model.payload_hash for approval in approval_models):
            raise ConflictError(
                "The stored administrator fallback approval failed integrity checks."
            )
        if model.state == AdminAccessRequestState.PENDING.value:
            valid_state_shape = (
                not approval_models and model.checker_id is None and model.version == 1
            )
        else:
            expected_decision = (
                AdminAccessDecision.REJECTED.value
                if model.state == AdminAccessRequestState.REJECTED.value
                else AdminAccessDecision.APPROVED.value
            )
            expected_version = 3 if model.state == AdminAccessRequestState.CONSUMED.value else 2
            valid_state_shape = (
                len(approval_models) == 1
                and model.checker_id == approval_models[0].actor_id
                and approval_models[0].request_version == 2
                and approval_models[0].decision == expected_decision
                and model.version == expected_version
            )
        if not valid_state_shape:
            raise ConflictError(
                "The stored administrator fallback approval state failed integrity checks."
            )
        return AdminAccessRequest(
            access_request_id=model.id,
            workspace_id=model.workspace_id,
            requester_id=model.requester_id,
            request_reason=model.request_reason,
            request_policy_decision_id=model.request_policy_decision_id,
            command=command,
            payload_hash=model.payload_hash,
            expires_at=model.expires_at,
            state=AdminAccessRequestState(model.state),
            version=model.version,
            approvals=[
                AdminAccessApproval(
                    approval_id=approval.id,
                    decision=AdminAccessDecision(approval.decision),
                    actor_id=approval.actor_id,
                    reason=approval.reason,
                    policy_decision_id=approval.policy_decision_id,
                    payload_hash=approval.payload_hash,
                    request_version=approval.request_version,
                    occurred_at=approval.occurred_at,
                )
                for approval in approval_models
            ],
            checker_id=model.checker_id,
            consumed_by=model.consumed_by,
            consumed_at=model.consumed_at,
            consume_policy_decision_id=model.consume_policy_decision_id,
        )


class SqlMembershipAccessRepository(MembershipAccessRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(
        self, *, workspace_id: UUID, limit: int
    ) -> tuple[WorkspaceMembershipSummary, ...]:
        rows = (
            await self._session.execute(
                select(SubjectModel, WorkspaceMembershipModel)
                .join(
                    WorkspaceMembershipModel,
                    WorkspaceMembershipModel.subject_id == SubjectModel.id,
                )
                .where(WorkspaceMembershipModel.workspace_id == workspace_id)
                .order_by(func.lower(SubjectModel.display_name), SubjectModel.id)
                .limit(limit)
            )
        ).all()
        if not rows:
            return ()
        subject_ids = [subject.id for subject, _ in rows]
        change_request_counts: dict[UUID, int] = {}
        for subject_id, count in (
            await self._session.execute(
                select(ChangeRequestModel.requester_id, func.count())
                .where(
                    ChangeRequestModel.workspace_id == workspace_id,
                    ChangeRequestModel.requester_id.in_(subject_ids),
                )
                .group_by(ChangeRequestModel.requester_id)
            )
        ).all():
            change_request_counts[subject_id] = int(count)
        owner_subjects = {
            f"urn:li:corpuser:{subject.external_subject}": subject.id for subject, _ in rows
        }
        owned_table_counts = {subject_id: 0 for subject_id in subject_ids}
        if owner_subjects:
            for owner_ref, count in (
                await self._session.execute(
                    select(AssetProjectionModel.owner_ref, func.count())
                    .where(
                        AssetProjectionModel.workspace_id == workspace_id,
                        AssetProjectionModel.owner_ref.in_(owner_subjects),
                        AssetProjectionModel.asset_type == "TABLE",
                    )
                    .group_by(AssetProjectionModel.owner_ref)
                )
            ).all():
                if owner_ref in owner_subjects:
                    owned_table_counts[owner_subjects[owner_ref]] = int(count)
        return tuple(
            _membership_summary(
                subject,
                membership,
                owned_table_count=owned_table_counts[subject.id],
                change_request_count=int(change_request_counts.get(subject.id, 0)),
            )
            for subject, membership in rows
        )

    async def get_access(
        self, *, workspace_id: UUID, subject_id: UUID
    ) -> WorkspaceMembershipAccessRecord | None:
        row = (
            await self._session.execute(
                select(SubjectModel, WorkspaceMembershipModel)
                .join(
                    WorkspaceMembershipModel,
                    WorkspaceMembershipModel.subject_id == SubjectModel.id,
                )
                .where(
                    WorkspaceMembershipModel.workspace_id == workspace_id,
                    WorkspaceMembershipModel.subject_id == subject_id,
                )
            )
        ).one_or_none()
        if row is None:
            return None
        subject, membership = row
        return _membership_access_record(subject, membership)

    async def apply(self, command: MembershipAccessUpdate) -> int:
        membership = await self._membership_for_update(command)
        membership.active = command.active
        membership.clearance = int(command.clearance)
        membership.attributes = {
            "groups": sorted(command.groups),
            "allowed_actions": sorted(action.value for action in command.allowed_actions),
            "denied_actions": sorted(action.value for action in command.denied_actions),
            "allowed_system_ids": sorted(str(value) for value in command.allowed_system_ids),
            "allowed_domain_ids": sorted(str(value) for value in command.allowed_domain_ids),
            "managed_by": MEMBERSHIP_ACCESS_COMMAND,
        }
        membership.version += 1
        await self._session.flush()
        administrator_count = await self._session.scalar(
            select(func.count())
            .select_from(WorkspaceMembershipModel)
            .join(SubjectModel, SubjectModel.id == WorkspaceMembershipModel.subject_id)
            .where(
                WorkspaceMembershipModel.workspace_id == command.workspace_id,
                SubjectModel.active.is_(True),
                WorkspaceMembershipModel.active.is_(True),
                or_(
                    WorkspaceMembershipModel.job_function.is_(None),
                    WorkspaceMembershipModel.job_function != "SERVICE_ACCOUNT",
                ),
                WorkspaceMembershipModel.clearance >= int(Classification.RESTRICTED),
                func.jsonb_path_exists(
                    WorkspaceMembershipModel.attributes,
                    '$.groups[*] ? (@ == "security-administrators")',
                ),
                ~func.jsonb_path_exists(
                    WorkspaceMembershipModel.attributes,
                    '$.groups[*] ? (@ == "service-accounts")',
                ),
                func.jsonb_path_exists(
                    WorkspaceMembershipModel.attributes,
                    '$.allowed_actions[*] ? (@ == "admin.manage")',
                ),
                ~func.jsonb_path_exists(
                    WorkspaceMembershipModel.attributes,
                    '$.denied_actions[*] ? (@ == "admin.manage")',
                ),
            )
        )
        if int(administrator_count or 0) < 2:
            raise ConflictError(
                "At least two active security administrators must remain in the workspace."
            )
        return membership.version

    async def assert_current_version(self, command: MembershipAccessUpdate) -> None:
        await self._membership_for_update(command)

    async def _membership_for_update(
        self, command: MembershipAccessUpdate
    ) -> WorkspaceMembershipModel:
        membership = (
            await self._session.scalars(
                select(WorkspaceMembershipModel)
                .where(
                    WorkspaceMembershipModel.workspace_id == command.workspace_id,
                    WorkspaceMembershipModel.subject_id == command.target_subject_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        if membership is None:
            raise NotFoundError("The target workspace membership does not exist.")
        if membership.version != command.expected_membership_version:
            raise ConflictError(
                "The target membership was modified by another operation.",
                details={
                    "expected": command.expected_membership_version,
                    "actual": membership.version,
                },
            )
        return membership

    async def assert_eligible_human_administrators(
        self, *, workspace_id: UUID, subject_ids: frozenset[UUID]
    ) -> None:
        if not subject_ids:
            raise ForbiddenError("At least one administrator identity is required.")
        rows = (
            await self._session.execute(
                select(SubjectModel, WorkspaceMembershipModel)
                .join(
                    WorkspaceMembershipModel,
                    WorkspaceMembershipModel.subject_id == SubjectModel.id,
                )
                .where(
                    WorkspaceMembershipModel.workspace_id == workspace_id,
                    WorkspaceMembershipModel.subject_id.in_(subject_ids),
                )
                .order_by(WorkspaceMembershipModel.subject_id)
                .with_for_update(of=WorkspaceMembershipModel)
            )
        ).all()
        if len(rows) != len(subject_ids):
            raise ForbiddenError("An administrator membership is no longer available.")
        for subject, membership in rows:
            attributes = membership.attributes
            groups = _string_set(attributes, "groups")
            allowed = _string_set(attributes, "allowed_actions")
            denied = _string_set(attributes, "denied_actions")
            if (
                groups is None
                or allowed is None
                or denied is None
                or not subject.active
                or not membership.active
                or membership.job_function == "SERVICE_ACCOUNT"
                or "service-accounts" in groups
                or "security-administrators" not in groups
                or Action.ADMIN_MANAGE.value not in allowed
                or Action.ADMIN_MANAGE.value in denied
                or membership.clearance < int(Classification.RESTRICTED)
            ):
                raise ForbiddenError("An administrator is no longer eligible for this workflow.")


class SqlSystemDirectoryRepository(SystemDirectoryRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self, *, workspace_id: UUID, limit: int) -> tuple[SystemDirectoryEntry, ...]:
        systems = (
            await self._session.scalars(
                select(DataSystemModel)
                .where(DataSystemModel.workspace_id == workspace_id)
                .order_by(func.lower(DataSystemModel.name), DataSystemModel.id)
                .limit(limit)
            )
        ).all()
        if not systems:
            return ()
        rows = (
            await self._session.execute(
                select(SystemAssigneeModel, SubjectModel, WorkspaceMembershipModel)
                .join(SubjectModel, SubjectModel.id == SystemAssigneeModel.subject_id)
                .join(
                    WorkspaceMembershipModel,
                    and_(
                        WorkspaceMembershipModel.workspace_id == SystemAssigneeModel.workspace_id,
                        WorkspaceMembershipModel.subject_id == SystemAssigneeModel.subject_id,
                    ),
                )
                .where(
                    SystemAssigneeModel.workspace_id == workspace_id,
                    SystemAssigneeModel.system_id.in_([system.id for system in systems]),
                )
                .order_by(
                    SystemAssigneeModel.system_id,
                    SystemAssigneeModel.responsibility,
                    SystemAssigneeModel.priority,
                    func.lower(SubjectModel.display_name),
                )
            )
        ).all()
        assignees: dict[UUID, list[SystemDirectoryAssignee]] = {system.id: [] for system in systems}
        for assignment, subject, membership in rows:
            assignees.setdefault(assignment.system_id, []).append(
                SystemDirectoryAssignee(
                    subject_id=subject.id,
                    display_name=subject.display_name,
                    responsibility=assignment.responsibility,
                    priority=assignment.priority,
                    active=assignment.active and subject.active and membership.active,
                )
            )
        return tuple(
            SystemDirectoryEntry(
                system_id=system.id,
                code=system.code,
                name=system.name,
                description=system.description,
                active=system.active,
                version=system.version,
                assignees=tuple(assignees.get(system.id, ())),
            )
            for system in systems
        )

    async def replace_assignees(self, command: SystemAssigneeUpdateCommand) -> int:
        system = (
            await self._session.scalars(
                select(DataSystemModel)
                .where(
                    DataSystemModel.workspace_id == command.workspace_id,
                    DataSystemModel.id == command.system_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        if system is None:
            raise NotFoundError("The data system does not exist.")
        if system.version != command.expected_system_version:
            raise ConflictError("The data system was modified by another operation.")
        subject_ids = frozenset(item.subject_id for item in command.assignees)
        active_subject_ids = set(
            (
                await self._session.scalars(
                    select(WorkspaceMembershipModel.subject_id)
                    .join(SubjectModel, SubjectModel.id == WorkspaceMembershipModel.subject_id)
                    .where(
                        WorkspaceMembershipModel.workspace_id == command.workspace_id,
                        WorkspaceMembershipModel.subject_id.in_(subject_ids),
                        WorkspaceMembershipModel.active.is_(True),
                        SubjectModel.active.is_(True),
                        or_(
                            WorkspaceMembershipModel.job_function.is_(None),
                            WorkspaceMembershipModel.job_function != "SERVICE_ACCOUNT",
                        ),
                    )
                )
            ).all()
        )
        if active_subject_ids != subject_ids:
            raise ValidationError("Every system assignee must be an active human workspace member.")
        await self._session.execute(
            delete(SystemAssigneeModel).where(
                SystemAssigneeModel.workspace_id == command.workspace_id,
                SystemAssigneeModel.system_id == command.system_id,
            )
        )
        self._session.add_all(
            [
                SystemAssigneeModel(
                    workspace_id=command.workspace_id,
                    system_id=command.system_id,
                    subject_id=item.subject_id,
                    responsibility=item.responsibility,
                    priority=item.priority,
                    active=True,
                )
                for item in command.assignees
            ]
        )
        system.version += 1
        await self._session.flush()
        return system.version


class SqlAdminAccessUnitOfWork(AdminAccessUnitOfWork):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self.requests: SqlAdminAccessRequestRepository
        self.memberships: SqlMembershipAccessRepository
        self.systems: SqlSystemDirectoryRepository
        self.outbox: SqlOutboxWriter
        self.idempotency: SqlIdempotencyStore
        self._committed = False

    async def __aenter__(self) -> SqlAdminAccessUnitOfWork:
        self._session = self._session_factory()
        self.requests = SqlAdminAccessRequestRepository(self._session)
        self.memberships = SqlMembershipAccessRepository(self._session)
        self.systems = SqlSystemDirectoryRepository(self._session)
        self.outbox = SqlOutboxWriter(self._session)
        self.idempotency = SqlIdempotencyStore(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_value, traceback
        if self._session is None:
            return
        if exc_type is not None or not self._committed:
            await self._session.rollback()
        await self._session.close()

    async def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await self._session.commit()
        self._committed = True

    async def lock_workspace_access(self, *, workspace_id: UUID) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"datariver:iam:workspace-access:{workspace_id}"},
        )

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await set_security_context(self._session, workspace_id=workspace_id, subject_id=subject_id)


def _request_model(request: AdminAccessRequest) -> AdminAccessRequestModel:
    return AdminAccessRequestModel(
        id=request.access_request_id,
        workspace_id=request.workspace_id,
        requester_id=request.requester_id,
        request_reason=request.request_reason,
        request_policy_decision_id=request.request_policy_decision_id,
        target_subject_id=request.command.target_subject_id,
        command_type=MEMBERSHIP_ACCESS_COMMAND,
        command_document=request.command.command_document(),
        payload_hash=request.payload_hash,
        state=request.state.value,
        expires_at=request.expires_at,
        checker_id=request.checker_id,
        consumed_by=request.consumed_by,
        consumed_at=request.consumed_at,
        consume_policy_decision_id=request.consume_policy_decision_id,
        version=request.version,
    )


def _string_set(document: object, key: str) -> set[str] | None:
    if not isinstance(document, dict):
        return None
    value = document.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return None
    return set(value)


def _membership_summary(
    subject: SubjectModel,
    membership: WorkspaceMembershipModel,
    *,
    owned_table_count: int = 0,
    change_request_count: int = 0,
) -> WorkspaceMembershipSummary:
    try:
        clearance = Classification(membership.clearance)
    except ValueError as error:
        raise ConflictError("The stored workspace membership access is invalid.") from error
    if membership.version < 1:
        raise ConflictError("The stored workspace membership version is invalid.")
    return WorkspaceMembershipSummary(
        subject_id=subject.id,
        display_name=subject.display_name,
        email=subject.email,
        last_login_at=subject.last_login_at,
        last_login_ip=subject.last_login_ip,
        owned_table_count=owned_table_count,
        change_request_count=change_request_count,
        subject_active=subject.active,
        membership_active=membership.active,
        department_id=membership.department_id,
        job_function=membership.job_function,
        clearance=clearance,
        membership_version=membership.version,
    )


def _membership_access_record(
    subject: SubjectModel, membership: WorkspaceMembershipModel
) -> WorkspaceMembershipAccessRecord:
    attributes = membership.attributes
    groups = _string_set(attributes, "groups")
    allowed = _string_set(attributes, "allowed_actions")
    denied = _string_set(attributes, "denied_actions")
    system_ids = _string_set(attributes, "allowed_system_ids")
    domain_ids = _string_set(attributes, "allowed_domain_ids")
    if (
        groups is None
        or allowed is None
        or denied is None
        or system_ids is None
        or domain_ids is None
    ):
        raise ConflictError("The stored workspace membership access is invalid.")
    try:
        command = MembershipAccessUpdate(
            workspace_id=membership.workspace_id,
            target_subject_id=membership.subject_id,
            expected_membership_version=membership.version,
            active=membership.active,
            clearance=Classification(membership.clearance),
            groups=frozenset(groups),
            allowed_actions=frozenset(Action(value) for value in allowed),
            denied_actions=frozenset(Action(value) for value in denied),
            allowed_system_ids=frozenset(UUID(value) for value in system_ids),
            allowed_domain_ids=frozenset(UUID(value) for value in domain_ids),
        )
    except (TypeError, ValueError, ValidationError) as error:
        raise ConflictError("The stored workspace membership access is invalid.") from error
    return WorkspaceMembershipAccessRecord(
        summary=_membership_summary(subject, membership),
        groups=command.groups,
        allowed_actions=command.allowed_actions,
        denied_actions=command.denied_actions,
        allowed_system_ids=command.allowed_system_ids,
        allowed_domain_ids=command.allowed_domain_ids,
    )
