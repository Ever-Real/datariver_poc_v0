from __future__ import annotations

from types import TracebackType
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.application.ports import (
    LegalHoldRepository,
    RetentionPolicyRepository,
    RetentionUnitOfWork,
)
from datariver.domain.common import ConflictError, ValidationError, canonical_json_hash, utc_now
from datariver.domain.retention import (
    LegalHold,
    LegalHoldAction,
    LegalHoldActionType,
    LegalHoldScope,
    LegalHoldState,
    RetentionDataClass,
    RetentionPolicyState,
    RetentionPolicyVersion,
    RetentionRules,
)
from datariver.infrastructure.db.governance import SqlIdempotencyStore, SqlOutboxWriter
from datariver.infrastructure.db.models.retention import (
    LegalHoldEventModel,
    LegalHoldModel,
    RetentionPolicyVersionModel,
)
from datariver.infrastructure.db.rls import set_security_context


class SqlRetentionPolicyRepository(RetentionPolicyRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, policy: RetentionPolicyVersion) -> None:
        self._session.add(_policy_model(policy))

    async def get(self, *, workspace_id: UUID, policy_id: UUID) -> RetentionPolicyVersion | None:
        model = (
            await self._session.scalars(
                select(RetentionPolicyVersionModel).where(
                    RetentionPolicyVersionModel.workspace_id == workspace_id,
                    RetentionPolicyVersionModel.id == policy_id,
                )
            )
        ).one_or_none()
        return _hydrate_policy(model)

    async def get_for_update(
        self, *, workspace_id: UUID, policy_id: UUID
    ) -> RetentionPolicyVersion | None:
        model = (
            await self._session.scalars(
                select(RetentionPolicyVersionModel)
                .where(
                    RetentionPolicyVersionModel.workspace_id == workspace_id,
                    RetentionPolicyVersionModel.id == policy_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        return _hydrate_policy(model)

    async def get_active(self, *, workspace_id: UUID) -> RetentionPolicyVersion | None:
        model = (
            await self._session.scalars(
                select(RetentionPolicyVersionModel).where(
                    RetentionPolicyVersionModel.workspace_id == workspace_id,
                    RetentionPolicyVersionModel.state == RetentionPolicyState.ACTIVE.value,
                )
            )
        ).one_or_none()
        return _hydrate_policy(model)

    async def get_active_for_update(
        self, *, workspace_id: UUID, excluding_policy_id: UUID | None = None
    ) -> RetentionPolicyVersion | None:
        statement = (
            select(RetentionPolicyVersionModel)
            .where(
                RetentionPolicyVersionModel.workspace_id == workspace_id,
                RetentionPolicyVersionModel.state == RetentionPolicyState.ACTIVE.value,
            )
            .with_for_update()
        )
        if excluding_policy_id is not None:
            statement = statement.where(RetentionPolicyVersionModel.id != excluding_policy_id)
        model = (await self._session.scalars(statement)).one_or_none()
        return _hydrate_policy(model)

    async def list(
        self, *, workspace_id: UUID, state: str | None, limit: int
    ) -> tuple[RetentionPolicyVersion, ...]:
        statement = (
            select(RetentionPolicyVersionModel)
            .where(RetentionPolicyVersionModel.workspace_id == workspace_id)
            .order_by(RetentionPolicyVersionModel.policy_number.desc())
            .limit(limit)
        )
        if state is not None:
            statement = statement.where(RetentionPolicyVersionModel.state == state)
        return tuple(_required_policy(model) for model in await self._session.scalars(statement))

    async def next_policy_number(self, *, workspace_id: UUID) -> int:
        maximum = await self._session.scalar(
            select(func.max(RetentionPolicyVersionModel.policy_number)).where(
                RetentionPolicyVersionModel.workspace_id == workspace_id
            )
        )
        return int(maximum or 0) + 1

    async def save(self, policy: RetentionPolicyVersion) -> None:
        result = await self._session.execute(
            update(RetentionPolicyVersionModel)
            .where(
                RetentionPolicyVersionModel.workspace_id == policy.workspace_id,
                RetentionPolicyVersionModel.id == policy.policy_id,
                RetentionPolicyVersionModel.version == policy.version - 1,
            )
            .values(
                state=policy.state.value,
                checker_id=policy.checker_id,
                decision_reason=policy.decision_reason,
                decision_policy_decision_id=policy.decision_policy_decision_id,
                decided_at=policy.decided_at,
                superseded_by=policy.superseded_by,
                supersede_reason=policy.supersede_reason,
                supersede_policy_decision_id=policy.supersede_policy_decision_id,
                superseded_at=policy.superseded_at,
                version=policy.version,
                updated_at=utc_now(),
            )
        )
        if getattr(result, "rowcount", None) != 1:
            raise ConflictError("The retention policy was modified by another operation.")


class SqlLegalHoldRepository(LegalHoldRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, hold: LegalHold) -> None:
        self._session.add(_hold_model(hold))
        self._session.add_all(_hold_event_model(hold, action) for action in hold.actions)

    async def get(self, *, workspace_id: UUID, hold_id: UUID) -> LegalHold | None:
        model = (
            await self._session.scalars(
                select(LegalHoldModel).where(
                    LegalHoldModel.workspace_id == workspace_id,
                    LegalHoldModel.id == hold_id,
                )
            )
        ).one_or_none()
        return await self._hydrate(model)

    async def get_for_update(self, *, workspace_id: UUID, hold_id: UUID) -> LegalHold | None:
        model = (
            await self._session.scalars(
                select(LegalHoldModel)
                .where(
                    LegalHoldModel.workspace_id == workspace_id,
                    LegalHoldModel.id == hold_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        return await self._hydrate(model)

    async def list(
        self, *, workspace_id: UUID, state: str | None, limit: int
    ) -> tuple[LegalHold, ...]:
        statement = (
            select(LegalHoldModel)
            .where(LegalHoldModel.workspace_id == workspace_id)
            .order_by(LegalHoldModel.updated_at.desc(), LegalHoldModel.id)
            .limit(limit)
        )
        if state is not None:
            statement = statement.where(LegalHoldModel.state == state)
        models = tuple(await self._session.scalars(statement))
        values: list[LegalHold] = []
        for model in models:
            hold = await self._hydrate(model)
            if hold is None:
                raise ConflictError("A stored Legal Hold disappeared during hydration.")
            values.append(hold)
        return tuple(values)

    async def save(self, hold: LegalHold) -> None:
        result = await self._session.execute(
            update(LegalHoldModel)
            .where(
                LegalHoldModel.workspace_id == hold.workspace_id,
                LegalHoldModel.id == hold.hold_id,
                LegalHoldModel.version == hold.version - 1,
            )
            .values(
                state=hold.state.value,
                release_requested_by=hold.release_requested_by,
                release_request_reason=hold.release_request_reason,
                release_request_policy_decision_id=hold.release_request_policy_decision_id,
                release_checker_id=hold.release_checker_id,
                release_decision_reason=hold.release_decision_reason,
                release_decision_policy_decision_id=hold.release_decision_policy_decision_id,
                released_at=hold.released_at,
                version=hold.version,
                updated_at=utc_now(),
            )
        )
        if getattr(result, "rowcount", None) != 1:
            raise ConflictError("The Legal Hold was modified by another operation.")
        matching = tuple(action for action in hold.actions if action.hold_version == hold.version)
        if len(matching) != 1:
            raise ConflictError("The Legal Hold mutation has no unique append-only action.")
        self._session.add(_hold_event_model(hold, matching[0]))

    async def _hydrate(self, model: LegalHoldModel | None) -> LegalHold | None:
        if model is None:
            return None
        events = tuple(
            await self._session.scalars(
                select(LegalHoldEventModel)
                .where(
                    LegalHoldEventModel.workspace_id == model.workspace_id,
                    LegalHoldEventModel.hold_id == model.id,
                )
                .order_by(LegalHoldEventModel.hold_version)
            )
        )
        return _hydrate_hold(model, events)


class SqlRetentionUnitOfWork(RetentionUnitOfWork):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self.policies: SqlRetentionPolicyRepository
        self.legal_holds: SqlLegalHoldRepository
        self.outbox: SqlOutboxWriter
        self.idempotency: SqlIdempotencyStore
        self._committed = False

    async def __aenter__(self) -> SqlRetentionUnitOfWork:
        self._session = self._session_factory()
        self.policies = SqlRetentionPolicyRepository(self._session)
        self.legal_holds = SqlLegalHoldRepository(self._session)
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

    async def lock_workspace(self, *, workspace_id: UUID) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"datariver:retention:workspace:{workspace_id}"},
        )

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await set_security_context(self._session, workspace_id=workspace_id, subject_id=subject_id)


def _policy_model(policy: RetentionPolicyVersion) -> RetentionPolicyVersionModel:
    return RetentionPolicyVersionModel(
        id=policy.policy_id,
        workspace_id=policy.workspace_id,
        policy_number=policy.policy_number,
        completed_operation_days=policy.rules.completed_operation_days,
        chat_content_days=policy.rules.chat_content_days,
        audit_online_months=policy.rules.audit_online_months,
        immutable_archive_years=policy.rules.immutable_archive_years,
        payload_hash=policy.payload_hash,
        requester_id=policy.requester_id,
        request_reason=policy.request_reason,
        request_policy_decision_id=policy.request_policy_decision_id,
        state=policy.state.value,
        checker_id=policy.checker_id,
        decision_reason=policy.decision_reason,
        decision_policy_decision_id=policy.decision_policy_decision_id,
        decided_at=policy.decided_at,
        superseded_by=policy.superseded_by,
        supersede_reason=policy.supersede_reason,
        supersede_policy_decision_id=policy.supersede_policy_decision_id,
        superseded_at=policy.superseded_at,
        version=policy.version,
    )


def _hydrate_policy(model: RetentionPolicyVersionModel | None) -> RetentionPolicyVersion | None:
    if model is None:
        return None
    return _required_policy(model)


def _required_policy(model: RetentionPolicyVersionModel) -> RetentionPolicyVersion:
    try:
        rules = RetentionRules(
            completed_operation_days=model.completed_operation_days,
            chat_content_days=model.chat_content_days,
            audit_online_months=model.audit_online_months,
            immutable_archive_years=model.immutable_archive_years,
        )
        state = RetentionPolicyState(model.state)
    except (ValueError, ValidationError) as error:
        raise ConflictError("The stored retention policy is invalid.") from error
    if canonical_json_hash(rules.document()) != model.payload_hash:
        raise ConflictError("The stored retention policy payload failed its integrity check.")
    return RetentionPolicyVersion(
        policy_id=model.id,
        workspace_id=model.workspace_id,
        policy_number=model.policy_number,
        rules=rules,
        payload_hash=model.payload_hash,
        requester_id=model.requester_id,
        request_reason=model.request_reason,
        request_policy_decision_id=model.request_policy_decision_id,
        state=state,
        checker_id=model.checker_id,
        decision_reason=model.decision_reason,
        decision_policy_decision_id=model.decision_policy_decision_id,
        decided_at=model.decided_at,
        superseded_by=model.superseded_by,
        supersede_reason=model.supersede_reason,
        supersede_policy_decision_id=model.supersede_policy_decision_id,
        superseded_at=model.superseded_at,
        version=model.version,
    )


def _hold_model(hold: LegalHold) -> LegalHoldModel:
    return LegalHoldModel(
        id=hold.hold_id,
        workspace_id=hold.workspace_id,
        data_class=hold.data_class.value,
        scope=hold.scope.value,
        scope_id=hold.scope_id,
        reason=hold.reason,
        payload_hash=hold.payload_hash,
        created_by=hold.created_by,
        create_policy_decision_id=hold.create_policy_decision_id,
        state=hold.state.value,
        release_requested_by=hold.release_requested_by,
        release_request_reason=hold.release_request_reason,
        release_request_policy_decision_id=hold.release_request_policy_decision_id,
        release_checker_id=hold.release_checker_id,
        release_decision_reason=hold.release_decision_reason,
        release_decision_policy_decision_id=hold.release_decision_policy_decision_id,
        released_at=hold.released_at,
        version=hold.version,
    )


def _hold_event_model(hold: LegalHold, action: LegalHoldAction) -> LegalHoldEventModel:
    return LegalHoldEventModel(
        id=action.action_id,
        workspace_id=hold.workspace_id,
        hold_id=hold.hold_id,
        action=action.action.value,
        actor_id=action.actor_id,
        reason=action.reason,
        policy_decision_id=action.policy_decision_id,
        occurred_at=action.occurred_at,
        hold_version=action.hold_version,
        payload_hash=action.payload_hash,
    )


def _hydrate_hold(model: LegalHoldModel, events: tuple[LegalHoldEventModel, ...]) -> LegalHold:
    try:
        data_class = RetentionDataClass(model.data_class)
        scope = LegalHoldScope(model.scope)
        state = LegalHoldState(model.state)
        actions = [_hydrate_action(model, event) for event in events]
    except (ValueError, ValidationError) as error:
        raise ConflictError("The stored Legal Hold is invalid.") from error
    placement_document = {
        "workspace_id": str(model.workspace_id),
        "data_class": data_class.value,
        "scope": scope.value,
        "scope_id": str(model.scope_id) if model.scope_id else None,
        "reason": model.reason,
    }
    if canonical_json_hash(placement_document) != model.payload_hash:
        raise ConflictError("The stored Legal Hold payload failed its integrity check.")
    expected_versions = list(range(1, model.version + 1))
    if [action.hold_version for action in actions] != expected_versions:
        raise ConflictError("The stored Legal Hold action history is incomplete.")
    expected_last_action = {
        LegalHoldState.ACTIVE: LegalHoldActionType.PLACED,
        LegalHoldState.RELEASE_REQUESTED: LegalHoldActionType.RELEASE_REQUESTED,
        LegalHoldState.RELEASE_REJECTED: LegalHoldActionType.RELEASE_REJECTED,
        LegalHoldState.RELEASED: LegalHoldActionType.RELEASE_APPROVED,
    }[state]
    if not actions or actions[-1].action is not expected_last_action:
        raise ConflictError("The stored Legal Hold state and history do not match.")
    return LegalHold(
        hold_id=model.id,
        workspace_id=model.workspace_id,
        data_class=data_class,
        scope=scope,
        scope_id=model.scope_id,
        reason=model.reason,
        payload_hash=model.payload_hash,
        created_by=model.created_by,
        create_policy_decision_id=model.create_policy_decision_id,
        state=state,
        release_requested_by=model.release_requested_by,
        release_request_reason=model.release_request_reason,
        release_request_policy_decision_id=model.release_request_policy_decision_id,
        release_checker_id=model.release_checker_id,
        release_decision_reason=model.release_decision_reason,
        release_decision_policy_decision_id=model.release_decision_policy_decision_id,
        released_at=model.released_at,
        version=model.version,
        actions=actions,
    )


def _hydrate_action(model: LegalHoldModel, event: LegalHoldEventModel) -> LegalHoldAction:
    action = LegalHoldActionType(event.action)
    payload_hash = canonical_json_hash(
        {
            "hold_id": str(model.id),
            "action": action.value,
            "actor_id": str(event.actor_id),
            "reason": event.reason,
            "policy_decision_id": str(event.policy_decision_id),
            "hold_version": event.hold_version,
            "placement_payload_hash": model.payload_hash,
        }
    )
    if payload_hash != event.payload_hash:
        raise ConflictError("The stored Legal Hold action failed its integrity check.")
    return LegalHoldAction(
        action_id=event.id,
        action=action,
        actor_id=event.actor_id,
        reason=event.reason,
        policy_decision_id=event.policy_decision_id,
        occurred_at=event.occurred_at,
        hold_version=event.hold_version,
        payload_hash=event.payload_hash,
    )
