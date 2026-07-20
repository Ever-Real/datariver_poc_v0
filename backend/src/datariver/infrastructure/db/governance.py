from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime, timedelta
from types import TracebackType
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.application.dto import IdempotencyRecord
from datariver.application.ports import (
    ChangeRequestRepository,
    ChangeWorkflowAuthorityReader,
    GovernanceUnitOfWork,
    ManualMetadataSubmissionRepository,
    OutboxWriter,
)
from datariver.domain.authz import Classification
from datariver.domain.common import ConflictError, DomainEvent, utc_now
from datariver.domain.governance import (
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
)
from datariver.domain.manual_metadata import (
    ManualColumnMetadata,
    ManualMetadataSubmission,
    ManualMetadataSubmissionState,
)
from datariver.infrastructure.db.models.governance import (
    ApprovalModel,
    ChangeItemModel,
    ChangeRequestModel,
    ChangeRequestRoundModel,
    ChangeTestRunModel,
    ManualMetadataSubmissionModel,
    StateTransitionModel,
)
from datariver.infrastructure.db.models.integration import IdempotencyKeyModel, OutboxEventModel
from datariver.infrastructure.db.models.platform import (
    DataSystemModel,
    SubjectModel,
    SystemAssigneeModel,
    WorkspaceMembershipModel,
)
from datariver.infrastructure.db.rls import set_security_context


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
        items = list(
            (
                await self._session.scalars(
                    select(ChangeItemModel)
                    .where(ChangeItemModel.change_request_id == change_request_id)
                    .order_by(ChangeItemModel.ordinal)
                )
            ).all()
        )
        approvals = list(
            (
                await self._session.scalars(
                    select(ApprovalModel).where(
                        ApprovalModel.change_request_id == change_request_id
                    )
                )
            ).all()
        )
        transitions = list(
            (
                await self._session.scalars(
                    select(StateTransitionModel).where(
                        StateTransitionModel.change_request_id == change_request_id
                    )
                )
            ).all()
        )
        rounds = list(
            (
                await self._session.scalars(
                    select(ChangeRequestRoundModel)
                    .where(ChangeRequestRoundModel.change_request_id == change_request_id)
                    .order_by(ChangeRequestRoundModel.round_number)
                )
            ).all()
        )
        test_runs = list(
            (
                await self._session.scalars(
                    select(ChangeTestRunModel)
                    .where(ChangeTestRunModel.change_request_id == change_request_id)
                    .order_by(ChangeTestRunModel.occurred_at, ChangeTestRunModel.id)
                )
            ).all()
        )
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
        now: datetime,
        lease_seconds: int,
        maximum_attempts: int,
    ) -> ManualMetadataSubmission | None:
        model = (
            await self._session.scalars(
                select(ManualMetadataSubmissionModel)
                .where(
                    ManualMetadataSubmissionModel.workspace_id == workspace_id,
                    ManualMetadataSubmissionModel.attempts < maximum_attempts,
                    or_(
                        ManualMetadataSubmissionModel.state
                        == ManualMetadataSubmissionState.QUEUED.value,
                        and_(
                            ManualMetadataSubmissionModel.state
                            == ManualMetadataSubmissionState.APPLYING.value,
                            ManualMetadataSubmissionModel.lease_expires_at.is_not(None),
                            ManualMetadataSubmissionModel.lease_expires_at <= now,
                        ),
                    ),
                )
                .order_by(
                    ManualMetadataSubmissionModel.created_at, ManualMetadataSubmissionModel.id
                )
                .with_for_update(skip_locked=True)
            )
        ).first()
        if model is None:
            return None
        submission = _submission_from_model(model)
        submission.claim_for_apply(now=now, lease_seconds=lease_seconds)
        await self.save(submission)
        return submission

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
        model.lease_expires_at = submission.lease_expires_at
        model.updated_at = submission.updated_at
        model.version = submission.version


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
        lease_expires_at=model.lease_expires_at,
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
        self.workflow_authorities: SqlChangeWorkflowAuthorityReader
        self.manual_metadata_submissions: SqlManualMetadataSubmissionRepository
        self.outbox: SqlOutboxWriter
        self.idempotency: SqlIdempotencyStore
        self._committed = False

    async def __aenter__(self) -> SqlGovernanceUnitOfWork:
        if self._session is None:
            self._session = self._session_factory()
        self.change_requests = SqlChangeRequestRepository(self._session)
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

    async def rollback(self) -> None:
        if self._session is None:
            return
        await self._session.rollback()

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await set_security_context(self._session, workspace_id=workspace_id, subject_id=subject_id)
