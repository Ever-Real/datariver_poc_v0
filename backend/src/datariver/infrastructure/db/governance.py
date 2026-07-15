from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import timedelta
from types import TracebackType
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.application.dto import IdempotencyRecord
from datariver.application.ports import (
    ChangeRequestRepository,
    GovernanceUnitOfWork,
    OutboxWriter,
)
from datariver.domain.authz import Classification
from datariver.domain.common import DomainEvent, utc_now
from datariver.domain.governance import (
    Approval,
    ApprovalDecision,
    ChangeItem,
    ChangeRequest,
    ChangeState,
    Transition,
)
from datariver.infrastructure.db.models.governance import (
    ApprovalModel,
    ChangeItemModel,
    ChangeRequestModel,
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


class SqlGovernanceUnitOfWork(GovernanceUnitOfWork):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self.change_requests: SqlChangeRequestRepository
        self.outbox: SqlOutboxWriter
        self.idempotency: SqlIdempotencyStore
        self._committed = False

    async def __aenter__(self) -> SqlGovernanceUnitOfWork:
        self._session = self._session_factory()
        self.change_requests = SqlChangeRequestRepository(self._session)
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

    async def rollback(self) -> None:
        if self._session is None:
            return
        await self._session.rollback()

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await set_security_context(self._session, workspace_id=workspace_id, subject_id=subject_id)
