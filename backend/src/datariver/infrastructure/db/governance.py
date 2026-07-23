from __future__ import annotations

import hashlib
import secrets
from collections.abc import Sequence
from datetime import datetime, timedelta
from types import TracebackType
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select, text, true
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from datariver.application.dto import (
    ChangeRequestSummaryRecord,
    ChangeRequestSummaryTarget,
    IdempotencyRecord,
    ManualMetadataApplyAttemptEvidence,
    ManualMetadataAspectReportEvidence,
    RegistrationCandidateBindingCommand,
)
from datariver.application.ports import (
    ChangeRequestRepository,
    ChangeWorkflowAuthorityReader,
    GovernanceUnitOfWork,
    ManualMetadataSubmissionRepository,
    OutboxWriter,
    RegistrationContentBindingRepository,
)
from datariver.domain.authz import Classification
from datariver.domain.common import ConflictError, DomainEvent, canonical_json_hash, utc_now, uuid7
from datariver.domain.governance import (
    MAX_CHANGE_APPROVALS,
    MAX_CHANGE_ITEMS,
    MAX_CHANGE_ROUNDS,
    MAX_CHANGE_TEST_RUNS,
    MAX_CHANGE_TRANSITIONS,
    Approval,
    ApprovalAuthority,
    ApprovalAuthorityKind,
    ApprovalDecision,
    ChangeItem,
    ChangePriority,
    ChangeRequest,
    ChangeRequestRound,
    ChangeState,
    ChangeTestRun,
    ChangeTestRunState,
    ChangeUrgency,
    Transition,
    change_target_binding_hash,
)
from datariver.domain.manual_metadata import (
    ManualColumnMetadata,
    ManualMetadataApplyClaim,
    ManualMetadataAspectReport,
    ManualMetadataSubmission,
    ManualMetadataSubmissionState,
)
from datariver.domain.registration_worker import (
    RegistrationWorkerCallIdentity,
    RegistrationWorkerCallReplay,
)
from datariver.infrastructure.db.models.catalog import AssetProjectionModel
from datariver.infrastructure.db.models.governance import (
    ApprovalModel,
    ChangeItemModel,
    ChangeRequestModel,
    ChangeRequestRoundModel,
    ChangeTestRunModel,
    ManualMetadataApplyAttemptModel,
    ManualMetadataAspectReportModel,
    ManualMetadataSubmissionModel,
    RegistrationContentBindingModel,
    StateTransitionModel,
)
from datariver.infrastructure.db.models.integration import (
    IdempotencyKeyModel,
    ObjectManifestModel,
    OutboxEventModel,
    UploadPreparationJobModel,
    UploadPreparationReceiptModel,
    UploadRegistrationCandidateModel,
)
from datariver.infrastructure.db.models.platform import (
    DataSystemModel,
    SubjectModel,
    SystemAssigneeModel,
    WorkspaceMembershipModel,
)
from datariver.infrastructure.db.registration_worker_receipts import (
    SqlRegistrationWorkerCallReceipts,
)
from datariver.infrastructure.db.rls import set_security_context

_MAXIMUM_EXHAUSTED_MANUAL_RECOVERIES_PER_CLAIM = 100
_REGISTRATION_RECOVERY_LIMIT_STATE = "RECOVERY_LIMIT_REACHED"


def _approval_authorities(document: object) -> tuple[ApprovalAuthority, ...]:
    if not isinstance(document, list):
        raise ConflictError("The stored change approval authority evidence is invalid.")
    values: list[ApprovalAuthority] = []
    try:
        for item in document:
            if not isinstance(item, dict) or set(item) != {"kind", "system_id"}:
                raise ValueError
            system_value = item["system_id"]
            values.append(
                ApprovalAuthority(
                    kind=ApprovalAuthorityKind(str(item["kind"])),
                    system_id=UUID(str(system_value)) if system_value is not None else None,
                )
            )
    except (TypeError, ValueError) as error:
        raise ConflictError("The stored change approval authority evidence is invalid.") from error
    if len(values) != len(set(values)):
        raise ConflictError("The stored change approval authority evidence is duplicated.")
    return tuple(values)


class SqlChangeRequestRepository(ChangeRequestRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tracked: dict[UUID, ChangeRequestModel] = {}

    async def add(self, change_request: ChangeRequest) -> None:
        model = ChangeRequestModel(
            id=change_request.change_request_id,
            workspace_id=change_request.workspace_id,
            number=change_request.number,
            request_type=change_request.request_type,
            title=change_request.title,
            description=change_request.description,
            state=change_request.state.value,
            requester_id=change_request.requester_id,
            requester_department_id=change_request.requester_department_id,
            current_round_id=change_request.current_round_id,
            current_round_number=change_request.current_round_number,
            created_at=change_request.created_at,
            requested_due_date=change_request.requested_due_date,
            priority=(
                change_request.priority.value if change_request.priority is not None else None
            ),
            urgency=(change_request.urgency.value if change_request.urgency is not None else None),
            version=change_request.version,
            classification=int(change_request.classification),
        )
        self._session.add(model)
        # The aggregate has a deferred circular FK to its current round. Flush the parent
        # explicitly so SQLAlchemy cannot schedule child items before change_requests when
        # the round and items are attached as independent ORM models.
        await self._session.flush([model])
        self._session.add_all(
            [
                ChangeRequestRoundModel(
                    id=round_value.round_id,
                    workspace_id=change_request.workspace_id,
                    change_request_id=change_request.change_request_id,
                    round_number=round_value.round_number,
                    submitted_by=round_value.submitted_by,
                    submitted_at=round_value.submitted_at,
                    closed_at=round_value.closed_at,
                    evidence_hash=round_value.evidence_hash,
                )
                for round_value in change_request.rounds
            ]
        )
        self._session.add_all(
            [
                ChangeItemModel(
                    id=item.item_id,
                    workspace_id=change_request.workspace_id,
                    change_request_id=change_request.change_request_id,
                    target_type=item.target_type,
                    target_ref=item.target_ref,
                    aspect_name=item.aspect_name,
                    ordinal=ordinal,
                    operation=item.operation,
                    before_hash=item.before_hash,
                    after_document=item.after_document,
                    after_hash=item.after_hash,
                    target_asset_id=item.target_asset_id,
                    target_asset_type=item.target_asset_type,
                    target_system_id=item.target_system_id,
                    target_domain_id=item.target_domain_id,
                    target_owner_department_id=item.target_owner_department_id,
                    target_classification=(
                        int(item.target_classification)
                        if item.target_classification is not None
                        else None
                    ),
                    target_lifecycle=item.target_lifecycle,
                    target_source_version=item.target_source_version,
                    target_observed_at=item.target_observed_at,
                    target_binding_hash=item.target_binding_hash,
                    routing_system_id=item.routing_system_id,
                )
                for ordinal, item in enumerate(change_request.items)
            ]
        )
        self._tracked[change_request.change_request_id] = model

    async def get_for_update(
        self, *, workspace_id: UUID, change_request_id: UUID
    ) -> ChangeRequest | None:
        model = (
            await self._session.scalars(
                select(ChangeRequestModel)
                .where(
                    ChangeRequestModel.id == change_request_id,
                    ChangeRequestModel.workspace_id == workspace_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        if model is None:
            return None

        def require_bounded(values: Sequence[object], maximum: int, label: str) -> None:
            if len(values) > maximum:
                raise ConflictError(
                    "The change-request history exceeds the governed read capacity.",
                    details={"code": "CHANGE_REQUEST_HISTORY_BOUND", "section": label},
                )

        items = list(
            (
                await self._session.scalars(
                    select(ChangeItemModel)
                    .where(ChangeItemModel.change_request_id == change_request_id)
                    .order_by(ChangeItemModel.ordinal)
                    .limit(MAX_CHANGE_ITEMS + 1)
                )
            ).all()
        )
        require_bounded(items, MAX_CHANGE_ITEMS, "items")
        approvals = list(
            (
                await self._session.scalars(
                    select(ApprovalModel)
                    .where(ApprovalModel.change_request_id == change_request_id)
                    .limit(MAX_CHANGE_APPROVALS + 1)
                )
            ).all()
        )
        require_bounded(approvals, MAX_CHANGE_APPROVALS, "approvals")
        transitions = list(
            (
                await self._session.scalars(
                    select(StateTransitionModel)
                    .where(StateTransitionModel.change_request_id == change_request_id)
                    .limit(MAX_CHANGE_TRANSITIONS + 1)
                )
            ).all()
        )
        require_bounded(transitions, MAX_CHANGE_TRANSITIONS, "transitions")
        rounds = list(
            (
                await self._session.scalars(
                    select(ChangeRequestRoundModel)
                    .where(ChangeRequestRoundModel.change_request_id == change_request_id)
                    .order_by(ChangeRequestRoundModel.round_number)
                    .limit(MAX_CHANGE_ROUNDS + 1)
                )
            ).all()
        )
        require_bounded(rounds, MAX_CHANGE_ROUNDS, "rounds")
        test_runs = list(
            (
                await self._session.scalars(
                    select(ChangeTestRunModel)
                    .where(ChangeTestRunModel.change_request_id == change_request_id)
                    .order_by(ChangeTestRunModel.occurred_at, ChangeTestRunModel.id)
                    .limit(MAX_CHANGE_TEST_RUNS + 1)
                )
            ).all()
        )
        require_bounded(test_runs, MAX_CHANGE_TEST_RUNS, "test_runs")
        self._tracked[change_request_id] = model
        return ChangeRequest(
            change_request_id=model.id,
            workspace_id=model.workspace_id,
            number=model.number,
            request_type=model.request_type,
            title=model.title,
            description=model.description,
            requester_id=model.requester_id,
            requester_department_id=model.requester_department_id,
            current_round_id=model.current_round_id,
            current_round_number=model.current_round_number,
            created_at=model.created_at,
            requested_due_date=model.requested_due_date,
            priority=ChangePriority(model.priority) if model.priority is not None else None,
            urgency=ChangeUrgency(model.urgency) if model.urgency is not None else None,
            classification=Classification(model.classification),
            state=ChangeState(model.state),
            version=model.version,
            items=[
                ChangeItem(
                    item_id=item.id,
                    target_type=item.target_type,
                    target_ref=item.target_ref,
                    operation=item.operation,
                    after_document=item.after_document,
                    aspect_name=item.aspect_name,
                    before_hash=item.before_hash,
                    after_hash=item.after_hash,
                    target_asset_id=item.target_asset_id,
                    target_asset_type=item.target_asset_type,
                    target_system_id=item.target_system_id,
                    target_domain_id=item.target_domain_id,
                    target_owner_department_id=item.target_owner_department_id,
                    target_classification=(
                        Classification(item.target_classification)
                        if item.target_classification is not None
                        else None
                    ),
                    target_lifecycle=item.target_lifecycle,
                    target_source_version=item.target_source_version,
                    target_observed_at=item.target_observed_at,
                    target_binding_hash=item.target_binding_hash,
                    routing_system_id=item.routing_system_id,
                )
                for item in items
            ],
            approvals=[
                Approval(
                    approval_id=approval.id,
                    stage=approval.stage,
                    decision=ApprovalDecision(approval.decision),
                    actor_id=approval.actor_id,
                    reason=approval.reason,
                    policy_decision_id=approval.policy_decision_id,
                    occurred_at=approval.occurred_at,
                    round_id=approval.round_id,
                    authorities=_approval_authorities(approval.authority_snapshot),
                )
                for approval in approvals
            ],
            transitions=[
                Transition(
                    transition_id=transition.id,
                    from_state=ChangeState(transition.from_state),
                    to_state=ChangeState(transition.to_state),
                    actor_id=transition.actor_id,
                    reason=transition.reason,
                    policy_decision_id=transition.policy_decision_id,
                    occurred_at=transition.occurred_at,
                    round_id=transition.round_id,
                )
                for transition in transitions
            ],
            rounds=[
                ChangeRequestRound(
                    round_id=round_value.id,
                    round_number=round_value.round_number,
                    submitted_by=round_value.submitted_by,
                    submitted_at=round_value.submitted_at,
                    closed_at=round_value.closed_at,
                    evidence_hash=round_value.evidence_hash,
                )
                for round_value in rounds
            ],
            test_runs=[
                ChangeTestRun(
                    test_run_id=test_run.id,
                    round_id=test_run.round_id,
                    system_id=test_run.system_id,
                    attachment_id=test_run.attachment_id,
                    state=ChangeTestRunState(test_run.state),
                    plan_hash=test_run.plan_hash,
                    result_hash=test_run.result_hash,
                    bounded_summary=test_run.bounded_summary,
                    recorded_by=test_run.recorded_by,
                    occurred_at=test_run.occurred_at,
                )
                for test_run in test_runs
            ],
        )

    async def get(self, *, workspace_id: UUID, change_request_id: UUID) -> ChangeRequest | None:
        # The same hydration path is used so aggregate child ordering remains identical.
        # The UoW is short-lived and commits immediately after authorization.
        return await self.get_for_update(
            workspace_id=workspace_id, change_request_id=change_request_id
        )

    async def list(
        self,
        *,
        workspace_id: UUID,
        maximum_classification: int,
        state: str | None,
        limit: int,
    ) -> Sequence[ChangeRequest]:
        statement = select(ChangeRequestModel.id).where(
            ChangeRequestModel.workspace_id == workspace_id,
            ChangeRequestModel.classification <= maximum_classification,
        )
        if state is not None:
            statement = statement.where(ChangeRequestModel.state == state)
        ids = list(
            (
                await self._session.scalars(
                    statement.order_by(ChangeRequestModel.created_at.desc()).limit(limit)
                )
            ).all()
        )
        values: list[ChangeRequest] = []
        for change_request_id in ids:
            value = await self.get_for_update(
                workspace_id=workspace_id, change_request_id=change_request_id
            )
            if value is not None:
                values.append(value)
        return values

    async def list_summaries(
        self,
        *,
        workspace_id: UUID,
        maximum_classification: int,
        state: str | None,
        before_created_at: datetime | None,
        before_id: UUID | None,
        limit: int,
    ) -> Sequence[ChangeRequestSummaryRecord]:
        statement = select(
            ChangeRequestModel.id.label("change_request_id"),
            ChangeRequestModel.number,
            ChangeRequestModel.request_type,
            ChangeRequestModel.title,
            ChangeRequestModel.state,
            ChangeRequestModel.requester_id,
            ChangeRequestModel.requester_department_id,
            ChangeRequestModel.current_round_number,
            ChangeRequestModel.created_at,
            ChangeRequestModel.requested_due_date,
            ChangeRequestModel.priority,
            ChangeRequestModel.urgency,
            ChangeRequestModel.classification,
            ChangeRequestModel.version,
        ).where(
            ChangeRequestModel.workspace_id == workspace_id,
            ChangeRequestModel.classification <= maximum_classification,
        )
        if state is not None:
            statement = statement.where(ChangeRequestModel.state == state)
        if before_created_at is not None and before_id is not None:
            statement = statement.where(
                or_(
                    ChangeRequestModel.created_at < before_created_at,
                    and_(
                        ChangeRequestModel.created_at == before_created_at,
                        ChangeRequestModel.id < before_id,
                    ),
                )
            )
        roots = list(
            (
                await self._session.execute(
                    statement.order_by(
                        ChangeRequestModel.created_at.desc(),
                        ChangeRequestModel.id.desc(),
                    ).limit(limit)
                )
            ).mappings()
        )
        if not roots:
            return ()
        request_ids = tuple(UUID(str(row["change_request_id"])) for row in roots)
        item_rows = (
            await self._session.execute(
                select(
                    ChangeItemModel.change_request_id,
                    ChangeItemModel.id,
                    ChangeItemModel.target_type,
                    ChangeItemModel.target_ref,
                    ChangeItemModel.aspect_name,
                    ChangeItemModel.operation,
                    ChangeItemModel.target_asset_id,
                    ChangeItemModel.target_asset_type,
                    ChangeItemModel.target_system_id,
                    ChangeItemModel.target_domain_id,
                    ChangeItemModel.target_owner_department_id,
                    ChangeItemModel.target_classification,
                    ChangeItemModel.target_lifecycle,
                    ChangeItemModel.target_source_version,
                    ChangeItemModel.target_observed_at,
                    ChangeItemModel.target_binding_hash,
                    ChangeItemModel.routing_system_id,
                )
                .where(
                    ChangeItemModel.workspace_id == workspace_id,
                    ChangeItemModel.change_request_id.in_(request_ids),
                )
                .order_by(ChangeItemModel.change_request_id, ChangeItemModel.ordinal)
            )
        ).all()
        targets_by_request: dict[UUID, list[ChangeRequestSummaryTarget]] = {}
        for row in item_rows:
            targets_by_request.setdefault(row.change_request_id, []).append(
                ChangeRequestSummaryTarget(
                    item_id=row.id,
                    target_type=row.target_type,
                    target_ref=row.target_ref,
                    aspect_name=row.aspect_name,
                    operation=row.operation,
                    target_asset_id=row.target_asset_id,
                    target_asset_type=row.target_asset_type,
                    target_system_id=row.target_system_id,
                    target_domain_id=row.target_domain_id,
                    target_owner_department_id=row.target_owner_department_id,
                    target_classification=(
                        Classification(row.target_classification)
                        if row.target_classification is not None
                        else None
                    ),
                    target_lifecycle=row.target_lifecycle,
                    target_source_version=row.target_source_version,
                    target_observed_at=row.target_observed_at,
                    target_binding_hash=row.target_binding_hash,
                    routing_system_id=row.routing_system_id,
                )
            )
        return [
            ChangeRequestSummaryRecord(
                change_request_id=UUID(str(row["change_request_id"])),
                number=str(row["number"]),
                request_type=str(row["request_type"]),
                title=str(row["title"]),
                state=ChangeState(str(row["state"])),
                requester_id=UUID(str(row["requester_id"])),
                requester_department_id=(
                    UUID(str(row["requester_department_id"]))
                    if row["requester_department_id"] is not None
                    else None
                ),
                current_round_number=int(row["current_round_number"]),
                created_at=row["created_at"],
                requested_due_date=row["requested_due_date"],
                priority=str(row["priority"]) if row["priority"] is not None else None,
                urgency=str(row["urgency"]) if row["urgency"] is not None else None,
                classification=Classification(int(row["classification"])),
                version=int(row["version"]),
                targets=tuple(targets_by_request.get(UUID(str(row["change_request_id"])), ())),
            )
            for row in roots
        ]

    async def save(self, change_request: ChangeRequest) -> None:
        model = self._tracked[change_request.change_request_id]
        model.state = change_request.state.value
        model.version = change_request.version
        model.current_round_id = change_request.current_round_id
        model.current_round_number = change_request.current_round_number
        stored_round_ids = set(
            await self._session.scalars(
                select(ChangeRequestRoundModel.id).where(
                    ChangeRequestRoundModel.change_request_id == change_request.change_request_id
                )
            )
        )
        stored_approval_ids = set(
            await self._session.scalars(
                select(ApprovalModel.id).where(
                    ApprovalModel.change_request_id == change_request.change_request_id
                )
            )
        )
        stored_transition_ids = set(
            await self._session.scalars(
                select(StateTransitionModel.id).where(
                    StateTransitionModel.change_request_id == change_request.change_request_id
                )
            )
        )
        stored_test_run_ids = set(
            await self._session.scalars(
                select(ChangeTestRunModel.id).where(
                    ChangeTestRunModel.change_request_id == change_request.change_request_id
                )
            )
        )
        for round_value in change_request.rounds:
            if round_value.round_id in stored_round_ids:
                stored_round = await self._session.get(
                    ChangeRequestRoundModel, round_value.round_id
                )
                if stored_round is not None:
                    stored_round.closed_at = round_value.closed_at
                continue
            self._session.add(
                ChangeRequestRoundModel(
                    id=round_value.round_id,
                    workspace_id=change_request.workspace_id,
                    change_request_id=change_request.change_request_id,
                    round_number=round_value.round_number,
                    submitted_by=round_value.submitted_by,
                    submitted_at=round_value.submitted_at,
                    closed_at=round_value.closed_at,
                    evidence_hash=round_value.evidence_hash,
                )
            )
        self._session.add_all(
            [
                ApprovalModel(
                    id=item.approval_id,
                    workspace_id=change_request.workspace_id,
                    change_request_id=change_request.change_request_id,
                    round_id=item.round_id,
                    stage=item.stage,
                    decision=item.decision.value,
                    actor_id=item.actor_id,
                    reason=item.reason,
                    policy_decision_id=item.policy_decision_id,
                    occurred_at=item.occurred_at,
                    authority_snapshot=[
                        {
                            "kind": authority.kind.value,
                            "system_id": (
                                str(authority.system_id)
                                if authority.system_id is not None
                                else None
                            ),
                        }
                        for authority in item.authorities
                    ],
                )
                for item in change_request.approvals
                if item.approval_id not in stored_approval_ids
            ]
        )
        self._session.add_all(
            [
                StateTransitionModel(
                    id=item.transition_id,
                    workspace_id=change_request.workspace_id,
                    change_request_id=change_request.change_request_id,
                    round_id=item.round_id,
                    from_state=item.from_state.value,
                    to_state=item.to_state.value,
                    actor_id=item.actor_id,
                    reason=item.reason,
                    policy_decision_id=item.policy_decision_id,
                    occurred_at=item.occurred_at,
                )
                for item in change_request.transitions
                if item.transition_id not in stored_transition_ids
            ]
        )
        self._session.add_all(
            [
                ChangeTestRunModel(
                    id=item.test_run_id,
                    workspace_id=change_request.workspace_id,
                    change_request_id=change_request.change_request_id,
                    round_id=item.round_id,
                    system_id=item.system_id,
                    attachment_id=item.attachment_id,
                    state=item.state.value,
                    plan_hash=item.plan_hash,
                    result_hash=item.result_hash,
                    bounded_summary=item.bounded_summary,
                    recorded_by=item.recorded_by,
                    occurred_at=item.occurred_at,
                )
                for item in change_request.test_runs
                if item.test_run_id not in stored_test_run_ids
            ]
        )


class SqlChangeWorkflowAuthorityReader(ChangeWorkflowAuthorityReader):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_authorities(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        system_ids: frozenset[UUID],
    ) -> tuple[ApprovalAuthority, ...]:
        if not system_ids:
            return ()
        rows = (
            await self._session.scalars(
                select(SystemAssigneeModel)
                .join(
                    DataSystemModel,
                    and_(
                        DataSystemModel.workspace_id == SystemAssigneeModel.workspace_id,
                        DataSystemModel.id == SystemAssigneeModel.system_id,
                    ),
                )
                .join(
                    WorkspaceMembershipModel,
                    and_(
                        WorkspaceMembershipModel.workspace_id == SystemAssigneeModel.workspace_id,
                        WorkspaceMembershipModel.subject_id == SystemAssigneeModel.subject_id,
                    ),
                )
                .join(SubjectModel, SubjectModel.id == SystemAssigneeModel.subject_id)
                .where(
                    SystemAssigneeModel.workspace_id == workspace_id,
                    SystemAssigneeModel.subject_id == subject_id,
                    SystemAssigneeModel.system_id.in_(system_ids),
                    SystemAssigneeModel.active.is_(True),
                    DataSystemModel.active.is_(True),
                    SubjectModel.active.is_(True),
                    WorkspaceMembershipModel.active.is_(True),
                    or_(
                        WorkspaceMembershipModel.access_expires_at.is_(None),
                        WorkspaceMembershipModel.access_expires_at > func.now(),
                    ),
                )
            )
        ).all()
        authorities = {
            ApprovalAuthority(
                ApprovalAuthorityKind.SYSTEM_DEVELOPER
                if row.responsibility == "DEVELOPER"
                else ApprovalAuthorityKind.SYSTEM_DATA_STEWARD,
                row.system_id,
            )
            for row in rows
        }
        admin_row = (
            await self._session.execute(
                select(SubjectModel, WorkspaceMembershipModel)
                .join(
                    WorkspaceMembershipModel,
                    WorkspaceMembershipModel.subject_id == SubjectModel.id,
                )
                .where(
                    SubjectModel.id == subject_id,
                    SubjectModel.active.is_(True),
                    WorkspaceMembershipModel.workspace_id == workspace_id,
                    WorkspaceMembershipModel.active.is_(True),
                    or_(
                        WorkspaceMembershipModel.access_expires_at.is_(None),
                        WorkspaceMembershipModel.access_expires_at > func.now(),
                    ),
                )
            )
        ).one_or_none()
        if admin_row is not None:
            _, membership = admin_row
            attributes = membership.attributes
            groups = attributes.get("groups") if isinstance(attributes, dict) else None
            allowed = attributes.get("allowed_actions") if isinstance(attributes, dict) else None
            denied = attributes.get("denied_actions") if isinstance(attributes, dict) else None
            if (
                isinstance(groups, list)
                and isinstance(allowed, list)
                and isinstance(denied, list)
                and "security-administrators" in groups
                and "admin.manage" in allowed
                and "admin.manage" not in denied
                and membership.clearance >= int(Classification.RESTRICTED)
                and membership.job_function != "SERVICE_ACCOUNT"
            ):
                authorities.add(ApprovalAuthority(ApprovalAuthorityKind.GLOBAL_ADMIN))
        return tuple(sorted(authorities, key=lambda item: (item.kind.value, str(item.system_id))))


class SqlOutboxWriter(OutboxWriter):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_events(self, events: Sequence[DomainEvent]) -> None:
        self._session.add_all(
            [
                OutboxEventModel(
                    id=event.event_id,
                    workspace_id=event.workspace_id,
                    aggregate_type=event.aggregate_type,
                    aggregate_id=event.aggregate_id,
                    event_type=event.event_type,
                    schema_version=1,
                    payload=event.payload,
                    created_at=event.occurred_at,
                    attempts=0,
                )
                for event in events
            ]
        )


class SqlIdempotencyStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _key_hash(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()

    async def acquire_key_lock(self, *, workspace_id: UUID, key: str, operation: str) -> None:
        lock_identity = f"{workspace_id}:{operation}:{self._key_hash(key)}"
        await self._session.execute(
            select(
                func.pg_advisory_xact_lock(
                    func.hashtextextended(lock_identity, 0),
                )
            )
        )

    async def get_result(
        self, *, workspace_id: UUID, key: str, operation: str
    ) -> IdempotencyRecord | None:
        model = await self._session.get(
            IdempotencyKeyModel,
            {
                "workspace_id": workspace_id,
                "operation": operation,
                "key_hash": self._key_hash(key),
            },
        )
        if model is None or model.expires_at <= utc_now():
            return None
        return IdempotencyRecord(request_hash=model.request_hash, result=model.result)

    async def save_result(
        self,
        *,
        workspace_id: UUID,
        key: str,
        operation: str,
        request_hash: str,
        result: dict[str, object],
    ) -> None:
        now = utc_now()
        self._session.add(
            IdempotencyKeyModel(
                workspace_id=workspace_id,
                operation=operation,
                key_hash=self._key_hash(key),
                request_hash=request_hash,
                result=result,
                created_at=now,
                expires_at=now + timedelta(hours=24),
            )
        )


class SqlManualMetadataSubmissionRepository(ManualMetadataSubmissionRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def allocate_serial_number(self) -> int:
        value = await self._session.scalar(
            text("SELECT nextval('governance.manual_metadata_submission_serial_seq')")
        )
        if not isinstance(value, int) or value < 1:
            raise RuntimeError("Manual metadata submission serial allocation failed.")
        return value

    async def add(self, submission: ManualMetadataSubmission) -> None:
        self._session.add(
            ManualMetadataSubmissionModel(
                id=submission.submission_id,
                workspace_id=submission.workspace_id,
                asset_id=submission.asset_id,
                requester_id=submission.requester_id,
                external_urn=submission.external_urn,
                source_version=submission.source_version,
                provider_source_version=submission.provider_source_version,
                serial_number=submission.serial_number,
                payload=_submission_payload(submission),
                bucket=submission.bucket,
                object_key=submission.object_key,
                csv_sha256=submission.csv_sha256,
                csv_size_bytes=submission.csv_size_bytes,
                row_count=submission.row_count,
                state=submission.state.value,
                created_at=submission.created_at,
                updated_at=submission.updated_at,
                version=submission.version,
                applied_at=submission.applied_at,
                last_error_code=submission.last_error_code,
                attempts=submission.attempts,
                next_attempt_at=submission.next_attempt_at,
                lease_epoch=submission.lease_epoch,
                lease_token_hash=submission.lease_token_hash,
                lease_owner_id=submission.lease_owner_id,
                lease_started_at=submission.lease_started_at,
                lease_expires_at=submission.lease_expires_at,
            )
        )

    async def get(
        self, *, workspace_id: UUID, submission_id: UUID
    ) -> ManualMetadataSubmission | None:
        model = (
            await self._session.scalars(
                select(ManualMetadataSubmissionModel).where(
                    ManualMetadataSubmissionModel.workspace_id == workspace_id,
                    ManualMetadataSubmissionModel.id == submission_id,
                )
            )
        ).one_or_none()
        return _submission_from_model(model) if model is not None else None

    async def claim_next(
        self,
        *,
        workspace_id: UUID,
        worker_subject_id: UUID,
        now: datetime,
        lease_seconds: int,
        maximum_attempts: int,
        run_call: RegistrationWorkerCallIdentity | None = None,
    ) -> ManualMetadataApplyClaim | RegistrationWorkerCallReplay | None:
        del now
        now = await self._database_now()
        receipts = SqlRegistrationWorkerCallReceipts(self._session)
        call_receipt = (
            await receipts.lock(workspace_id=workspace_id, identity=run_call)
            if run_call is not None
            else None
        )
        if call_receipt is not None:
            if call_receipt.state == "COMPLETED":
                return receipts.replay(call_receipt)
            receipts.require_reclaimable(call_receipt, now=now)
            if (
                call_receipt.work_kind == "MANUAL"
                and call_receipt.work_id is not None
                and call_receipt.claim_attempt is not None
            ):
                superseded = await self._session.scalar(
                    select(ManualMetadataSubmissionModel)
                    .where(
                        ManualMetadataSubmissionModel.workspace_id == workspace_id,
                        ManualMetadataSubmissionModel.id == call_receipt.work_id,
                        ManualMetadataSubmissionModel.attempts > call_receipt.claim_attempt,
                        ManualMetadataSubmissionModel.lease_epoch > call_receipt.claim_attempt,
                        exists(
                            select(1).where(
                                ManualMetadataApplyAttemptModel.workspace_id
                                == ManualMetadataSubmissionModel.workspace_id,
                                ManualMetadataApplyAttemptModel.submission_id
                                == ManualMetadataSubmissionModel.id,
                                ManualMetadataApplyAttemptModel.attempt_no
                                > call_receipt.claim_attempt,
                                ManualMetadataApplyAttemptModel.lease_epoch
                                > call_receipt.claim_attempt,
                            )
                        ),
                    )
                    .with_for_update()
                )
                if superseded is not None:
                    result = {
                        "processed": True,
                        "submission_id": str(superseded.id),
                        "serial_number": superseded.serial_number,
                        "state": "SUPERSEDED",
                    }
                    await receipts.complete(
                        receipt=call_receipt,
                        result=result,
                        now=now,
                    )
                    return RegistrationWorkerCallReplay(result=result)
        preferred_submission_id = (
            call_receipt.work_id
            if call_receipt is not None and call_receipt.work_kind == "MANUAL"
            else None
        )
        earlier = aliased(ManualMetadataSubmissionModel)
        competing = aliased(ManualMetadataSubmissionModel)
        model: ManualMetadataSubmissionModel | None = None
        for _ in range(_MAXIMUM_EXHAUSTED_MANUAL_RECOVERIES_PER_CLAIM):
            model = (
                await self._session.scalars(
                    select(ManualMetadataSubmissionModel)
                    .where(
                        ManualMetadataSubmissionModel.workspace_id == workspace_id,
                        (
                            ManualMetadataSubmissionModel.id == preferred_submission_id
                            if preferred_submission_id is not None
                            else true()
                        ),
                        or_(
                            and_(
                                ManualMetadataSubmissionModel.state
                                == ManualMetadataSubmissionState.QUEUED.value,
                                ManualMetadataSubmissionModel.attempts < maximum_attempts,
                                ManualMetadataSubmissionModel.next_attempt_at.is_not(None),
                                ManualMetadataSubmissionModel.next_attempt_at <= now,
                            ),
                            and_(
                                ManualMetadataSubmissionModel.state
                                == ManualMetadataSubmissionState.APPLYING.value,
                                ManualMetadataSubmissionModel.lease_expires_at.is_not(None),
                                ManualMetadataSubmissionModel.lease_expires_at <= now,
                            ),
                        ),
                        ~exists(
                            select(1).where(
                                earlier.workspace_id == ManualMetadataSubmissionModel.workspace_id,
                                earlier.asset_id == ManualMetadataSubmissionModel.asset_id,
                                earlier.serial_number < ManualMetadataSubmissionModel.serial_number,
                                earlier.state.in_(
                                    (
                                        ManualMetadataSubmissionState.QUEUED.value,
                                        ManualMetadataSubmissionState.APPLYING.value,
                                    )
                                ),
                            )
                        ),
                        ~exists(
                            select(1).where(
                                competing.workspace_id
                                == ManualMetadataSubmissionModel.workspace_id,
                                competing.asset_id == ManualMetadataSubmissionModel.asset_id,
                                competing.id != ManualMetadataSubmissionModel.id,
                                competing.state == ManualMetadataSubmissionState.APPLYING.value,
                            )
                        ),
                    )
                    .order_by(
                        func.coalesce(
                            ManualMetadataSubmissionModel.next_attempt_at,
                            ManualMetadataSubmissionModel.lease_expires_at,
                        ),
                        ManualMetadataSubmissionModel.serial_number,
                        ManualMetadataSubmissionModel.id,
                    )
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).first()
            if model is None:
                if call_receipt is not None:
                    raise ConflictError(
                        "The previous worker claim is not yet safely reclaimable.",
                        details={"code": "WORKER_RUN_RECOVERY_PENDING", "retryable": True},
                    )
                if run_call is None:
                    return None
                return await receipts.complete_no_work(
                    workspace_id=workspace_id,
                    identity=run_call,
                    existing=None,
                    result={
                        "processed": False,
                        "submission_id": None,
                        "serial_number": None,
                        "state": None,
                    },
                    now=now,
                )
            if (
                model.state == ManualMetadataSubmissionState.APPLYING.value
                and model.attempts >= maximum_attempts
            ):
                await self._terminalize_exhausted_apply(model=model, now=now)
                # This unit of work disables autoflush. Persist the terminal
                # state before scanning again or the same expired row remains
                # eligible and can be reclaimed.
                await self._session.flush()
                if (
                    call_receipt is not None
                    and call_receipt.work_id == model.id
                    and run_call is not None
                ):
                    result = {
                        "processed": True,
                        "submission_id": str(model.id),
                        "serial_number": model.serial_number,
                        "state": ManualMetadataSubmissionState.FAILED.value,
                    }
                    await receipts.complete(receipt=call_receipt, result=result, now=now)
                    return RegistrationWorkerCallReplay(result=result)
                model = None
                continue
            break
        if model is None:
            if run_call is not None:
                if call_receipt is not None:
                    raise ConflictError(
                        "The previous worker claim still requires a terminal replay.",
                        details={
                            "code": "WORKER_RUN_TERMINAL_RETRY",
                            "retryable": True,
                        },
                    )
                return await receipts.complete_no_work(
                    workspace_id=workspace_id,
                    identity=run_call,
                    existing=None,
                    result={
                        "processed": False,
                        "submission_id": None,
                        "serial_number": None,
                        "state": _REGISTRATION_RECOVERY_LIMIT_STATE,
                    },
                    now=now,
                )
            return None
        await self._session.scalar(
            select(AssetProjectionModel.id)
            .where(
                AssetProjectionModel.workspace_id == workspace_id,
                AssetProjectionModel.id == model.asset_id,
            )
            .with_for_update()
        )
        submission = _submission_from_model(model)
        previous: ManualMetadataApplyAttemptModel | None = None
        previous_report_root: str | None = None
        if submission.state is ManualMetadataSubmissionState.APPLYING:
            previous = await self._session.scalar(
                select(ManualMetadataApplyAttemptModel)
                .where(
                    ManualMetadataApplyAttemptModel.workspace_id == workspace_id,
                    ManualMetadataApplyAttemptModel.submission_id == submission.submission_id,
                    ManualMetadataApplyAttemptModel.lease_epoch == submission.lease_epoch,
                    ManualMetadataApplyAttemptModel.state == "RUNNING",
                )
                .with_for_update()
            )
            if previous is not None:
                previous_report_root = await self._terminal_report_root(
                    attempt_id=previous.id,
                    failure_code="LEASE_EXPIRED",
                )
        lease_token = secrets.token_urlsafe(32)
        lease_token_hash = hashlib.sha256(lease_token.encode()).hexdigest()
        submission.claim_for_apply(
            now=now,
            lease_seconds=lease_seconds,
            lease_token_hash=lease_token_hash,
            lease_owner_id=worker_subject_id,
        )
        await self._session.scalar(
            select(func.set_config("app.manual_metadata_lease_token", lease_token, True))
        )
        await self.save(submission)
        # Persist the new parent claim before superseding the old attempt.
        # This makes durable newer-attempt evidence a prerequisite for the
        # tokenless recovery path and removes the old-lease TOCTOU window.
        await self._session.flush((model,))
        if previous is not None:
            assert previous_report_root is not None
            previous.state = "SUPERSEDED"
            previous.failure_code = "LEASE_EXPIRED"
            previous.report_root_hash = previous_report_root
            previous.finished_at = now
            await self._session.flush((previous,))
        attempt_id = uuid7()
        self._session.add(
            ManualMetadataApplyAttemptModel(
                id=attempt_id,
                workspace_id=submission.workspace_id,
                submission_id=submission.submission_id,
                attempt_no=submission.attempts,
                lease_epoch=submission.lease_epoch,
                lease_token_hash=lease_token_hash,
                worker_subject_id=worker_subject_id,
                state="RUNNING",
                failure_code=None,
                report_root_hash=None,
                started_at=now,
                finished_at=None,
            )
        )
        if run_call is not None:
            assert submission.lease_expires_at is not None
            await receipts.start(
                workspace_id=workspace_id,
                identity=run_call,
                existing=call_receipt,
                work_kind="MANUAL",
                work_id=submission.submission_id,
                claim_attempt=submission.lease_epoch,
                raw_claim_token=lease_token,
                lease_expires_at=submission.lease_expires_at,
                now=now,
            )
            await self._session.flush()
            await receipts.complete_superseded_for_newer_claim(
                workspace_id=workspace_id,
                worker_subject_id=worker_subject_id,
                work_kind="MANUAL",
                work_id=submission.submission_id,
                newer_claim_attempt=submission.lease_epoch,
                newer_key_hash=run_call.key_hash,
                result={
                    "processed": True,
                    "submission_id": str(submission.submission_id),
                    "serial_number": submission.serial_number,
                    "state": "SUPERSEDED",
                },
                now=now,
            )
        return ManualMetadataApplyClaim(
            submission=submission,
            attempt_id=attempt_id,
            attempt_no=submission.attempts,
            lease_epoch=submission.lease_epoch,
            lease_token=lease_token,
            worker_subject_id=worker_subject_id,
            run_call=run_call,
        )

    async def _terminalize_exhausted_apply(
        self,
        *,
        model: ManualMetadataSubmissionModel,
        now: datetime,
    ) -> None:
        submission = _submission_from_model(model)
        previous = await self._session.scalar(
            select(ManualMetadataApplyAttemptModel)
            .where(
                ManualMetadataApplyAttemptModel.workspace_id == submission.workspace_id,
                ManualMetadataApplyAttemptModel.submission_id == submission.submission_id,
                ManualMetadataApplyAttemptModel.lease_epoch == submission.lease_epoch,
                ManualMetadataApplyAttemptModel.state == "RUNNING",
            )
            .with_for_update()
        )
        if previous is not None:
            previous.state = "FAILED"
            previous.failure_code = "WORKER_LEASE_EXHAUSTED"
            previous.report_root_hash = await self._terminal_report_root(
                attempt_id=previous.id,
                failure_code="WORKER_LEASE_EXHAUSTED",
            )
            previous.finished_at = now
        submission.mark_apply_failed(
            now=now,
            error_code="WORKER_LEASE_EXHAUSTED",
            retryable=False,
        )
        await self.save(submission)
        await SqlOutboxWriter(self._session).add_events(
            (
                DomainEvent.create(
                    event_type="registration.manual_metadata.failed.v1",
                    aggregate_type="manual_metadata_submission",
                    aggregate_id=submission.submission_id,
                    workspace_id=submission.workspace_id,
                    payload={
                        "error_code": "WORKER_LEASE_EXHAUSTED",
                        "submission_id": str(submission.submission_id),
                    },
                ),
            )
        )

    async def save(self, submission: ManualMetadataSubmission) -> None:
        model = (
            await self._session.scalars(
                select(ManualMetadataSubmissionModel)
                .where(
                    ManualMetadataSubmissionModel.workspace_id == submission.workspace_id,
                    ManualMetadataSubmissionModel.id == submission.submission_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        if model is None:
            raise RuntimeError("Manual metadata submission persistence is unavailable.")
        model.state = submission.state.value
        model.applied_at = submission.applied_at
        model.last_error_code = submission.last_error_code
        model.attempts = submission.attempts
        model.next_attempt_at = submission.next_attempt_at
        model.lease_epoch = submission.lease_epoch
        model.lease_token_hash = submission.lease_token_hash
        model.lease_owner_id = submission.lease_owner_id
        model.lease_started_at = submission.lease_started_at
        model.lease_expires_at = submission.lease_expires_at
        model.updated_at = submission.updated_at
        model.version = submission.version

    async def record_aspect_report(
        self,
        *,
        claim: ManualMetadataApplyClaim,
        report: ManualMetadataAspectReport,
    ) -> bool:
        now = await self._database_now()
        current, attempt = await self._locked_current_claim(claim=claim, now=now)
        if current is None or attempt is None:
            return False
        existing = await self._session.scalar(
            select(ManualMetadataAspectReportModel).where(
                ManualMetadataAspectReportModel.workspace_id == current.workspace_id,
                ManualMetadataAspectReportModel.attempt_id == attempt.id,
                ManualMetadataAspectReportModel.aspect_name == report.aspect_name,
            )
        )
        if existing is not None:
            return _aspect_report_hash(existing) == report.content_hash()
        self._session.add(
            ManualMetadataAspectReportModel(
                id=uuid7(),
                workspace_id=current.workspace_id,
                submission_id=current.submission_id,
                attempt_id=attempt.id,
                aspect_name=report.aspect_name,
                aspect_ordinal=report.aspect_ordinal,
                outcome=report.outcome.value,
                before_hash=report.before_hash,
                expected_hash=report.expected_hash,
                observed_hash=report.observed_hash,
                write_attempted=report.write_attempted,
                failure_code=report.failure_code,
                provider_operation_id_hash=report.provider_operation_id_hash,
                provider_version=report.provider_version,
                provider_response_hash=report.provider_response_hash,
                observed_at=report.observed_at,
                created_at=now,
            )
        )
        return True

    async def renew_lease(
        self,
        *,
        claim: ManualMetadataApplyClaim,
        lease_seconds: int,
    ) -> bool:
        if lease_seconds < 1:
            raise ValueError("The manual metadata apply lease is invalid.")
        now = await self._database_now()
        current, attempt = await self._locked_current_claim(claim=claim, now=now)
        if current is None or attempt is None:
            return False
        model = await self._session.scalar(
            select(ManualMetadataSubmissionModel).where(
                ManualMetadataSubmissionModel.workspace_id == current.workspace_id,
                ManualMetadataSubmissionModel.id == current.submission_id,
            )
        )
        if model is None:
            return False
        model.lease_expires_at = now + timedelta(seconds=lease_seconds)
        model.updated_at = now
        if claim.run_call is not None:
            # The receipt trigger verifies the renewed expiry against the canonical claim.
            await self._session.flush()
            receipts = SqlRegistrationWorkerCallReceipts(self._session)
            call_receipt = await receipts.lock(
                workspace_id=current.workspace_id,
                identity=claim.run_call,
            )
            if call_receipt is None or call_receipt.state != "RUNNING":
                return False
            expected_hash = hashlib.sha256(claim.lease_token.encode()).hexdigest()
            if call_receipt.claim_token_hash != expected_hash:
                return False
            await self._session.scalar(
                select(
                    func.set_config(
                        "app.registration_worker_claim_token",
                        claim.lease_token,
                        True,
                    )
                )
            )
            call_receipt.lease_expires_at = model.lease_expires_at
            call_receipt.updated_at = now
        return True

    async def complete(
        self, *, claim: ManualMetadataApplyClaim, now: datetime
    ) -> ManualMetadataSubmission | None:
        del now
        now = await self._database_now()
        current, attempt = await self._locked_current_claim(claim=claim, now=now)
        if current is None or attempt is None:
            await self._complete_worker_call(
                claim=claim,
                result={
                    "processed": True,
                    "submission_id": str(claim.submission.submission_id),
                    "serial_number": claim.submission.serial_number,
                    "state": "SUPERSEDED",
                },
                now=now,
            )
            return None
        reports = list(
            (
                await self._session.scalars(
                    select(ManualMetadataAspectReportModel)
                    .where(
                        ManualMetadataAspectReportModel.workspace_id == current.workspace_id,
                        ManualMetadataAspectReportModel.attempt_id == attempt.id,
                    )
                    .order_by(ManualMetadataAspectReportModel.aspect_ordinal)
                    .with_for_update()
                )
            ).all()
        )
        if [report.aspect_ordinal for report in reports] != [1, 2, 3, 4, 5]:
            raise ConflictError("The manual metadata aspect report is incomplete.")
        if any(
            report.outcome not in {"ALREADY_MATCHED", "APPLIED_VERIFIED"}
            or report.expected_hash != report.observed_hash
            for report in reports
        ):
            raise ConflictError("The manual metadata aspect report is not fully verified.")
        current.mark_applied(now=now)
        await self.save(current)
        attempt.state = "APPLIED"
        attempt.failure_code = None
        attempt.report_root_hash = _aspect_report_root(reports)
        attempt.finished_at = now
        await self._complete_worker_call(
            claim=claim,
            result={
                "processed": True,
                "submission_id": str(current.submission_id),
                "serial_number": current.serial_number,
                "state": ManualMetadataSubmissionState.APPLIED.value,
            },
            now=now,
        )
        return current

    async def fail(
        self,
        *,
        claim: ManualMetadataApplyClaim,
        now: datetime,
        error_code: str,
        retryable: bool,
        maximum_attempts: int,
    ) -> str | None:
        del now
        now = await self._database_now()
        current, attempt = await self._locked_current_claim(claim=claim, now=now)
        if current is None or attempt is None:
            await self._complete_worker_call(
                claim=claim,
                result={
                    "processed": True,
                    "submission_id": str(claim.submission.submission_id),
                    "serial_number": claim.submission.serial_number,
                    "state": "SUPERSEDED",
                },
                now=now,
            )
            return None
        may_retry = retryable and current.attempts < maximum_attempts
        current.mark_apply_failed(
            now=now,
            error_code=error_code,
            retryable=may_retry,
        )
        await self.save(current)
        reports = list(
            (
                await self._session.scalars(
                    select(ManualMetadataAspectReportModel)
                    .where(
                        ManualMetadataAspectReportModel.workspace_id == current.workspace_id,
                        ManualMetadataAspectReportModel.attempt_id == attempt.id,
                    )
                    .order_by(ManualMetadataAspectReportModel.aspect_ordinal)
                )
            ).all()
        )
        attempt.state = "RETRY_WAIT" if may_retry else "FAILED"
        attempt.failure_code = error_code
        attempt.report_root_hash = _aspect_report_root(reports, failure_code=error_code)
        attempt.finished_at = now
        await self._complete_worker_call(
            claim=claim,
            result={
                "processed": True,
                "submission_id": str(current.submission_id),
                "serial_number": current.serial_number,
                "state": current.state.value,
            },
            now=now,
        )
        return current.state.value

    async def _complete_worker_call(
        self,
        *,
        claim: ManualMetadataApplyClaim,
        result: dict[str, object],
        now: datetime,
    ) -> None:
        if claim.run_call is None:
            return
        receipts = SqlRegistrationWorkerCallReceipts(self._session)
        receipt = await receipts.lock(
            workspace_id=claim.submission.workspace_id,
            identity=claim.run_call,
        )
        if receipt is None:
            raise ConflictError(
                "The durable worker run receipt is unavailable.",
                details={
                    "code": "WORKER_RUN_TERMINAL_RETRY",
                    "retryable": True,
                },
            )
        if receipt.state == "COMPLETED":
            if receipt.result == result:
                return
            raise ConflictError(
                "The worker run terminal result must be replayed.",
                details={
                    "code": "WORKER_RUN_TERMINAL_RETRY",
                    "retryable": True,
                },
            )
        expected_token_hash = hashlib.sha256(claim.lease_token.encode()).hexdigest()
        if receipt.state != "RUNNING" or receipt.claim_token_hash != expected_token_hash:
            raise ConflictError(
                "The worker run terminal claim is no longer current.",
                details={
                    "code": "WORKER_RUN_TERMINAL_RETRY",
                    "retryable": True,
                },
            )
        await receipts.complete(
            receipt=receipt,
            result=result,
            now=now,
            raw_claim_token=claim.lease_token,
        )

    async def list(
        self,
        *,
        workspace_id: UUID,
        requester_id: UUID | None,
        state: str | None,
        before_created_at: datetime | None,
        before_id: UUID | None,
        limit: int,
    ) -> Sequence[ManualMetadataSubmission]:
        statement = select(ManualMetadataSubmissionModel).where(
            ManualMetadataSubmissionModel.workspace_id == workspace_id
        )
        if requester_id is not None:
            statement = statement.where(ManualMetadataSubmissionModel.requester_id == requester_id)
        if state is not None:
            statement = statement.where(ManualMetadataSubmissionModel.state == state)
        if before_created_at is not None and before_id is not None:
            statement = statement.where(
                or_(
                    ManualMetadataSubmissionModel.created_at < before_created_at,
                    and_(
                        ManualMetadataSubmissionModel.created_at == before_created_at,
                        ManualMetadataSubmissionModel.id < before_id,
                    ),
                )
            )
        models = list(
            (
                await self._session.scalars(
                    statement.order_by(
                        ManualMetadataSubmissionModel.created_at.desc(),
                        ManualMetadataSubmissionModel.id.desc(),
                    ).limit(limit)
                )
            ).all()
        )
        return [_submission_from_model(model) for model in models]

    async def list_attempts(
        self,
        *,
        workspace_id: UUID,
        submission_id: UUID,
        limit: int,
    ) -> Sequence[ManualMetadataApplyAttemptEvidence]:
        attempts = list(
            (
                await self._session.scalars(
                    select(ManualMetadataApplyAttemptModel)
                    .where(
                        ManualMetadataApplyAttemptModel.workspace_id == workspace_id,
                        ManualMetadataApplyAttemptModel.submission_id == submission_id,
                    )
                    .order_by(ManualMetadataApplyAttemptModel.attempt_no.desc())
                    .limit(limit)
                )
            ).all()
        )
        if not attempts:
            return ()
        reports = list(
            (
                await self._session.scalars(
                    select(ManualMetadataAspectReportModel)
                    .where(
                        ManualMetadataAspectReportModel.workspace_id == workspace_id,
                        ManualMetadataAspectReportModel.attempt_id.in_(
                            tuple(attempt.id for attempt in attempts)
                        ),
                    )
                    .order_by(
                        ManualMetadataAspectReportModel.attempt_id,
                        ManualMetadataAspectReportModel.aspect_ordinal,
                    )
                )
            ).all()
        )
        by_attempt: dict[UUID, list[ManualMetadataAspectReportEvidence]] = {}
        for report in reports:
            by_attempt.setdefault(report.attempt_id, []).append(
                ManualMetadataAspectReportEvidence(
                    aspect_name=report.aspect_name,
                    aspect_ordinal=report.aspect_ordinal,
                    outcome=report.outcome,
                    before_hash=report.before_hash,
                    expected_hash=report.expected_hash,
                    observed_hash=report.observed_hash,
                    write_attempted=report.write_attempted,
                    failure_code=report.failure_code,
                    provider_version=report.provider_version,
                    provider_response_hash=report.provider_response_hash,
                    observed_at=report.observed_at,
                )
            )
        return [
            ManualMetadataApplyAttemptEvidence(
                attempt_id=attempt.id,
                attempt_no=attempt.attempt_no,
                lease_epoch=attempt.lease_epoch,
                state=attempt.state,
                failure_code=attempt.failure_code,
                report_root_hash=attempt.report_root_hash,
                started_at=attempt.started_at,
                finished_at=attempt.finished_at,
                aspects=tuple(by_attempt.get(attempt.id, ())),
            )
            for attempt in attempts
        ]

    async def _locked_current_claim(
        self,
        *,
        claim: ManualMetadataApplyClaim,
        now: datetime,
    ) -> tuple[ManualMetadataSubmission | None, ManualMetadataApplyAttemptModel | None]:
        model = await self._session.scalar(
            select(ManualMetadataSubmissionModel)
            .where(
                ManualMetadataSubmissionModel.workspace_id == claim.submission.workspace_id,
                ManualMetadataSubmissionModel.id == claim.submission.submission_id,
            )
            .with_for_update()
        )
        attempt = await self._session.scalar(
            select(ManualMetadataApplyAttemptModel)
            .where(
                ManualMetadataApplyAttemptModel.workspace_id == claim.submission.workspace_id,
                ManualMetadataApplyAttemptModel.id == claim.attempt_id,
                ManualMetadataApplyAttemptModel.submission_id == claim.submission.submission_id,
            )
            .with_for_update()
        )
        if model is None or attempt is None or attempt.state != "RUNNING":
            return None, attempt
        current = _submission_from_model(model)
        token_hash = hashlib.sha256(claim.lease_token.encode()).hexdigest()
        if not current.fence_matches(
            now=now,
            lease_epoch=claim.lease_epoch,
            lease_token_hash=token_hash,
            lease_owner_id=claim.worker_subject_id,
        ) or (
            attempt.attempt_no != claim.attempt_no
            or attempt.lease_epoch != claim.lease_epoch
            or attempt.lease_token_hash != token_hash
            or attempt.worker_subject_id != claim.worker_subject_id
        ):
            return None, attempt
        await self._session.scalar(
            select(func.set_config("app.manual_metadata_lease_token", claim.lease_token, True))
        )
        return current, attempt

    async def _terminal_report_root(self, *, attempt_id: UUID, failure_code: str) -> str:
        reports = list(
            (
                await self._session.scalars(
                    select(ManualMetadataAspectReportModel)
                    .where(ManualMetadataAspectReportModel.attempt_id == attempt_id)
                    .order_by(ManualMetadataAspectReportModel.aspect_ordinal)
                )
            ).all()
        )
        return _aspect_report_root(reports, failure_code=failure_code)

    async def _database_now(self) -> datetime:
        value = await self._session.scalar(select(func.clock_timestamp()))
        if not isinstance(value, datetime):
            raise RuntimeError("PostgreSQL clock_timestamp() did not return a timestamp.")
        return value


def _submission_payload(submission: ManualMetadataSubmission) -> dict[str, object]:
    return {
        "description": submission.description,
        "domain": submission.domain,
        "tags": list(submission.tags),
        "terms": list(submission.terms),
        "columns": [
            {
                "field_path": column.field_path,
                "description": column.description,
                "tags": list(column.tags),
                "terms": list(column.terms),
            }
            for column in submission.columns
        ],
    }


def _aspect_report_hash(model: ManualMetadataAspectReportModel) -> str:
    return canonical_json_hash(
        {
            "aspect_name": model.aspect_name,
            "aspect_ordinal": model.aspect_ordinal,
            "before_hash": model.before_hash,
            "expected_hash": model.expected_hash,
            "failure_code": model.failure_code,
            "observed_hash": model.observed_hash,
            "outcome": model.outcome,
            "provider_operation_id_hash": model.provider_operation_id_hash,
            "provider_response_hash": model.provider_response_hash,
            "provider_version": model.provider_version,
            "write_attempted": model.write_attempted,
        }
    )


def _aspect_report_root(
    reports: Sequence[ManualMetadataAspectReportModel],
    *,
    failure_code: str | None = None,
) -> str:
    return canonical_json_hash(
        {
            "contract": "manual-metadata-aspect-report-root-v1",
            "failure_code": failure_code,
            "reports": [_aspect_report_hash(report) for report in reports],
        }
    )


def _submission_from_model(model: ManualMetadataSubmissionModel) -> ManualMetadataSubmission:
    payload = model.payload
    raw_columns = payload.get("columns", [])
    columns = tuple(
        ManualColumnMetadata(
            field_path=str(value["field_path"]),
            description=str(value.get("description", "")),
            tags=tuple(str(item) for item in value.get("tags", [])),
            terms=tuple(str(item) for item in value.get("terms", [])),
        )
        for value in raw_columns
        if isinstance(value, dict) and isinstance(value.get("field_path"), str)
    )
    return ManualMetadataSubmission(
        submission_id=model.id,
        workspace_id=model.workspace_id,
        asset_id=model.asset_id,
        external_urn=model.external_urn,
        requester_id=model.requester_id,
        source_version=model.source_version,
        provider_source_version=model.provider_source_version,
        serial_number=model.serial_number,
        description=str(payload.get("description", "")),
        domain=str(payload["domain"]) if payload.get("domain") is not None else None,
        tags=tuple(str(item) for item in payload.get("tags", [])),
        terms=tuple(str(item) for item in payload.get("terms", [])),
        columns=columns,
        bucket=model.bucket,
        object_key=model.object_key,
        csv_sha256=model.csv_sha256,
        csv_size_bytes=model.csv_size_bytes,
        row_count=model.row_count,
        state=ManualMetadataSubmissionState(model.state),
        created_at=model.created_at,
        updated_at=model.updated_at,
        version=model.version,
        applied_at=model.applied_at,
        last_error_code=model.last_error_code,
        attempts=model.attempts,
        next_attempt_at=model.next_attempt_at,
        lease_epoch=model.lease_epoch,
        lease_token_hash=model.lease_token_hash,
        lease_owner_id=model.lease_owner_id,
        lease_started_at=model.lease_started_at,
        lease_expires_at=model.lease_expires_at,
    )


class SqlRegistrationContentBindingRepository(RegistrationContentBindingRepository):
    """Append provenance only after locking and reconciling the full typed BULK chain."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def verify_and_add(
        self,
        *,
        command: RegistrationCandidateBindingCommand,
        change_request_id: UUID,
        change_item_id: UUID,
        created_by: UUID,
    ) -> None:
        manifest = await self._session.scalar(
            select(ObjectManifestModel)
            .where(
                ObjectManifestModel.workspace_id == command.workspace_id,
                ObjectManifestModel.id == command.upload_id,
            )
            .with_for_update()
        )
        preparation = await self._session.scalar(
            select(UploadPreparationJobModel)
            .where(
                UploadPreparationJobModel.workspace_id == command.workspace_id,
                UploadPreparationJobModel.id == command.preparation_id,
                UploadPreparationJobModel.upload_id == command.upload_id,
            )
            .with_for_update()
        )
        receipt = await self._session.scalar(
            select(UploadPreparationReceiptModel)
            .where(
                UploadPreparationReceiptModel.workspace_id == command.workspace_id,
                UploadPreparationReceiptModel.id == command.receipt_id,
                UploadPreparationReceiptModel.preparation_job_id == command.preparation_id,
                UploadPreparationReceiptModel.upload_id == command.upload_id,
            )
            .with_for_update()
        )
        candidate = await self._session.scalar(
            select(UploadRegistrationCandidateModel)
            .where(
                UploadRegistrationCandidateModel.workspace_id == command.workspace_id,
                UploadRegistrationCandidateModel.id == command.candidate_id,
                UploadRegistrationCandidateModel.receipt_id == command.receipt_id,
            )
            .with_for_update()
        )
        target = await self._session.scalar(
            select(AssetProjectionModel)
            .where(
                AssetProjectionModel.workspace_id == command.workspace_id,
                AssetProjectionModel.id == command.target_asset_id,
            )
            .with_for_update(read=True)
        )
        existing = await self._session.scalar(
            select(RegistrationContentBindingModel)
            .where(
                RegistrationContentBindingModel.workspace_id == command.workspace_id,
                RegistrationContentBindingModel.candidate_id == command.candidate_id,
            )
            .with_for_update()
        )
        target_binding_hash = (
            change_target_binding_hash(
                target_ref=target.external_urn,
                asset_id=target.id,
                asset_type=target.asset_type,
                system_id=target.system_id,
                domain_id=target.domain_id,
                owner_department_id=target.owner_department_id,
                classification=Classification(target.classification),
                lifecycle=target.lifecycle,
            )
            if target is not None
            else None
        )
        if (
            manifest is None
            or preparation is None
            or receipt is None
            or candidate is None
            or target is None
            or existing is not None
            or manifest.state != "ACCEPTED"
            or manifest.version != preparation.source_manifest_version
            or manifest.actual_sha256 != preparation.source_sha256
            or manifest.content_profile != preparation.content_profile
            or preparation.state != "READY"
            or receipt.receipt_hash != command.receipt_hash
            or receipt.manifest_version != manifest.version
            or receipt.source_sha256 != preparation.source_sha256
            or receipt.configuration_hash != preparation.configuration_hash
            or candidate.candidate_hash != command.candidate_hash
            or candidate.evidence_version != "DATASET_DESCRIPTION_CANDIDATE_V2"
            or candidate.target_asset_id != command.target_asset_id
            or target.deleted_at is not None
            or target.lifecycle != "ACTIVE"
            or target.source_version != command.target_source_version
            or target_binding_hash != command.target_binding_hash
            or (
                target.platform,
                target.database_name,
                target.schema_name,
                target.name,
            )
            != (
                candidate.submitted_platform,
                candidate.submitted_database_name,
                candidate.submitted_schema_name,
                candidate.submitted_table_name,
            )
        ):
            raise ConflictError(
                "The typed BULK candidate is stale or already bound.",
                details={"code": "TYPED_BULK_CANDIDATE_STALE"},
            )
        created_at = await self._session.scalar(select(func.clock_timestamp()))
        if not isinstance(created_at, datetime):
            raise RuntimeError("PostgreSQL clock_timestamp() did not return a timestamp.")
        self._session.add(
            RegistrationContentBindingModel(
                id=uuid7(),
                workspace_id=command.workspace_id,
                candidate_id=command.candidate_id,
                candidate_hash=command.candidate_hash,
                change_request_id=change_request_id,
                change_item_id=change_item_id,
                created_by=created_by,
                created_at=created_at,
            )
        )


class SqlGovernanceUnitOfWork(GovernanceUnitOfWork):
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        session: AsyncSession | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = session
        self._owns_session = session is None
        self.change_requests: SqlChangeRequestRepository
        self.registration_content_bindings: SqlRegistrationContentBindingRepository
        self.workflow_authorities: SqlChangeWorkflowAuthorityReader
        self.manual_metadata_submissions: SqlManualMetadataSubmissionRepository
        self.outbox: SqlOutboxWriter
        self.idempotency: SqlIdempotencyStore
        self._committed = False

    async def __aenter__(self) -> SqlGovernanceUnitOfWork:
        if self._session is None:
            self._session = self._session_factory()
        self.change_requests = SqlChangeRequestRepository(self._session)
        self.registration_content_bindings = SqlRegistrationContentBindingRepository(self._session)
        self.workflow_authorities = SqlChangeWorkflowAuthorityReader(self._session)
        self.manual_metadata_submissions = SqlManualMetadataSubmissionRepository(self._session)
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
        if self._owns_session:
            await self._session.close()

    async def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await self._session.commit()
        self._committed = True

    async def flush(self) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await self._session.flush()

    async def rollback(self) -> None:
        if self._session is None:
            return
        await self._session.rollback()

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await set_security_context(self._session, workspace_id=workspace_id, subject_id=subject_id)
