from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import timedelta
from types import TracebackType
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.application.dto import IdempotencyRecord
from datariver.application.ports import (
    ChangeRequestRepository,
    GovernanceUnitOfWork,
    ManualMetadataSubmissionRepository,
    OutboxWriter,
)
from datariver.domain.authz import Classification
from datariver.domain.common import DomainEvent, utc_now
from datariver.domain.governance import (
    Approval,
    ApprovalDecision,
    ChangeItem,
    ChangePriority,
    ChangeRequest,
    ChangeState,
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
    ManualMetadataSubmissionModel,
    StateTransitionModel,
)
from datariver.infrastructure.db.models.integration import IdempotencyKeyModel, OutboxEventModel
from datariver.infrastructure.db.rls import set_security_context


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
        self._tracked[change_request_id] = model
        return ChangeRequest(
            change_request_id=model.id,
            workspace_id=model.workspace_id,
            number=model.number,
            request_type=model.request_type,
            title=model.title,
            description=model.description,
            requester_id=model.requester_id,
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
                )
                for transition in transitions
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
        self._session.add_all(
            [
                ApprovalModel(
                    id=item.approval_id,
                    workspace_id=change_request.workspace_id,
                    change_request_id=change_request.change_request_id,
                    stage=item.stage,
                    decision=item.decision.value,
                    actor_id=item.actor_id,
                    reason=item.reason,
                    policy_decision_id=item.policy_decision_id,
                    occurred_at=item.occurred_at,
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
        self.manual_metadata_submissions: SqlManualMetadataSubmissionRepository
        self.outbox: SqlOutboxWriter
        self.idempotency: SqlIdempotencyStore
        self._committed = False

    async def __aenter__(self) -> SqlGovernanceUnitOfWork:
        if self._session is None:
            self._session = self._session_factory()
        self.change_requests = SqlChangeRequestRepository(self._session)
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
