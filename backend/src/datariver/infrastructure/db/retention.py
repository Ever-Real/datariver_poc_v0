from __future__ import annotations

from types import TracebackType
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.application.ports import (
    ErasureRequestRepository,
    ErasureTargetReader,
    LegalHoldRepository,
    RetentionPolicyRepository,
    RetentionUnitOfWork,
)
from datariver.domain.authz import Classification
from datariver.domain.common import (
    ConflictError,
    ValidationError,
    canonical_json_hash,
    utc_now,
    uuid7,
)
from datariver.domain.retention import (
    ErasureApproval,
    ErasureRequest,
    ErasureRequestState,
    ErasureTargetSnapshot,
    ErasureTargetType,
    GovernanceDecision,
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
from datariver.infrastructure.db.models.assistant import ChatSessionModel
from datariver.infrastructure.db.models.integration import ObjectManifestModel
from datariver.infrastructure.db.models.platform import WorkspaceMembershipModel
from datariver.infrastructure.db.models.retention import (
    ErasureRequestEventModel,
    ErasureRequestModel,
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

    async def has_active_for_erasure_target(
        self,
        *,
        workspace_id: UUID,
        target_type: ErasureTargetType,
        target_id: UUID,
        target_owner_id: UUID | None,
    ) -> bool:
        subject_scope_ids = {target_id}
        if target_owner_id is not None:
            subject_scope_ids.add(target_owner_id)
        scope_predicate = or_(
            LegalHoldModel.scope == LegalHoldScope.WORKSPACE.value,
            and_(
                LegalHoldModel.scope == LegalHoldScope.RESOURCE.value,
                LegalHoldModel.scope_id == target_id,
            ),
            and_(
                LegalHoldModel.scope == LegalHoldScope.SUBJECT.value,
                LegalHoldModel.scope_id.in_(subject_scope_ids),
            ),
        )
        statement = select(LegalHoldModel.id).where(
            LegalHoldModel.workspace_id == workspace_id,
            LegalHoldModel.state != LegalHoldState.RELEASED.value,
            scope_predicate,
        )
        target_data_class = {
            ErasureTargetType.CHAT_SESSION: RetentionDataClass.CHAT_CONTENT,
            ErasureTargetType.UPLOAD_OBJECT: RetentionDataClass.OBJECT_DATA,
        }.get(target_type)
        if target_data_class is not None:
            statement = statement.where(LegalHoldModel.data_class == target_data_class.value)
        return await self._session.scalar(statement.limit(1)) is not None

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


class SqlErasureRequestRepository(ErasureRequestRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, request: ErasureRequest) -> None:
        self._session.add(_erasure_request_model(request))
        self._session.add(_erasure_created_event_model(request))

    async def get(self, *, workspace_id: UUID, erasure_request_id: UUID) -> ErasureRequest | None:
        model = (
            await self._session.scalars(
                select(ErasureRequestModel).where(
                    ErasureRequestModel.workspace_id == workspace_id,
                    ErasureRequestModel.id == erasure_request_id,
                )
            )
        ).one_or_none()
        return await self._hydrate(model)

    async def get_for_update(
        self, *, workspace_id: UUID, erasure_request_id: UUID
    ) -> ErasureRequest | None:
        model = (
            await self._session.scalars(
                select(ErasureRequestModel)
                .where(
                    ErasureRequestModel.workspace_id == workspace_id,
                    ErasureRequestModel.id == erasure_request_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        return await self._hydrate(model)

    async def list(
        self, *, workspace_id: UUID, state: str | None, limit: int
    ) -> tuple[ErasureRequest, ...]:
        statement = (
            select(ErasureRequestModel)
            .where(ErasureRequestModel.workspace_id == workspace_id)
            .order_by(ErasureRequestModel.created_at.desc(), ErasureRequestModel.id)
            .limit(limit)
        )
        if state is not None:
            statement = statement.where(ErasureRequestModel.state == state)
        values: list[ErasureRequest] = []
        for model in await self._session.scalars(statement):
            request = await self._hydrate(model)
            if request is None:
                raise ConflictError("A stored erasure request disappeared during hydration.")
            values.append(request)
        return tuple(values)

    async def save(self, request: ErasureRequest) -> None:
        result = await self._session.execute(
            update(ErasureRequestModel)
            .where(
                ErasureRequestModel.workspace_id == request.workspace_id,
                ErasureRequestModel.id == request.erasure_request_id,
                ErasureRequestModel.version == request.version - 1,
            )
            .values(
                state=request.state.value,
                checker_id=request.checker_id,
                decision_reason=request.decision_reason,
                decision_policy_decision_id=request.decision_policy_decision_id,
                decided_at=request.decided_at,
                version=request.version,
                updated_at=utc_now(),
            )
        )
        if getattr(result, "rowcount", None) != 1:
            raise ConflictError("The erasure request was modified by another operation.")
        matching = tuple(
            approval
            for approval in request.approvals
            if approval.request_version == request.version
        )
        if len(matching) != 1:
            raise ConflictError("The erasure decision has no unique append-only approval event.")
        self._session.add(_erasure_approval_event_model(request, matching[0]))

    async def _hydrate(self, model: ErasureRequestModel | None) -> ErasureRequest | None:
        if model is None:
            return None
        events = tuple(
            await self._session.scalars(
                select(ErasureRequestEventModel)
                .where(
                    ErasureRequestEventModel.workspace_id == model.workspace_id,
                    ErasureRequestEventModel.erasure_request_id == model.id,
                )
                .order_by(ErasureRequestEventModel.request_version)
            )
        )
        return _hydrate_erasure_request(model, events)


class SqlErasureTargetReader(ErasureTargetReader):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_erasure_target_snapshot(
        self,
        *,
        workspace_id: UUID,
        target_type: ErasureTargetType,
        target_id: UUID,
    ) -> ErasureTargetSnapshot | None:
        if target_type is ErasureTargetType.SUBJECT_DATA:
            membership = (
                await self._session.scalars(
                    select(WorkspaceMembershipModel).where(
                        WorkspaceMembershipModel.workspace_id == workspace_id,
                        WorkspaceMembershipModel.subject_id == target_id,
                    )
                )
            ).one_or_none()
            if membership is None:
                return None
            return ErasureTargetSnapshot(
                target_type=target_type,
                target_id=target_id,
                version=membership.version,
                owner_id=target_id,
                classification=Classification.RESTRICTED,
            )

        if target_type is ErasureTargetType.CHAT_SESSION:
            session = (
                await self._session.scalars(
                    select(ChatSessionModel).where(
                        ChatSessionModel.workspace_id == workspace_id,
                        ChatSessionModel.id == target_id,
                    )
                )
            ).one_or_none()
            if session is None:
                return None
            return ErasureTargetSnapshot(
                target_type=target_type,
                target_id=target_id,
                version=session.version,
                owner_id=session.owner_id,
                classification=Classification.RESTRICTED,
            )

        manifest = (
            await self._session.scalars(
                select(ObjectManifestModel).where(
                    ObjectManifestModel.workspace_id == workspace_id,
                    ObjectManifestModel.id == target_id,
                )
            )
        ).one_or_none()
        if manifest is None:
            return None
        return ErasureTargetSnapshot(
            target_type=target_type,
            target_id=target_id,
            version=manifest.version,
            owner_id=manifest.owner_id,
            classification=_classification_or_restricted(manifest.classification),
        )


class SqlRetentionUnitOfWork(RetentionUnitOfWork):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self.policies: SqlRetentionPolicyRepository
        self.legal_holds: SqlLegalHoldRepository
        self.erasure_requests: SqlErasureRequestRepository
        self.erasure_targets: SqlErasureTargetReader
        self.outbox: SqlOutboxWriter
        self.idempotency: SqlIdempotencyStore
        self._committed = False

    async def __aenter__(self) -> SqlRetentionUnitOfWork:
        self._session = self._session_factory()
        self.policies = SqlRetentionPolicyRepository(self._session)
        self.legal_holds = SqlLegalHoldRepository(self._session)
        self.erasure_requests = SqlErasureRequestRepository(self._session)
        self.erasure_targets = SqlErasureTargetReader(self._session)
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


def _erasure_request_model(request: ErasureRequest) -> ErasureRequestModel:
    return ErasureRequestModel(
        id=request.erasure_request_id,
        workspace_id=request.workspace_id,
        target_type=request.target_type.value,
        target_id=request.target_id,
        target_version=request.target_version,
        target_owner_id=request.target_owner_id,
        classification=int(request.classification),
        retention_policy_id=request.retention_policy_id,
        retention_policy_hash=request.retention_policy_hash,
        requester_id=request.requester_id,
        request_reason=request.request_reason,
        request_policy_decision_id=request.request_policy_decision_id,
        payload_hash=request.payload_hash,
        expires_at=request.expires_at,
        state=request.state.value,
        checker_id=request.checker_id,
        decision_reason=request.decision_reason,
        decision_policy_decision_id=request.decision_policy_decision_id,
        decided_at=request.decided_at,
        version=request.version,
    )


def _erasure_created_event_model(request: ErasureRequest) -> ErasureRequestEventModel:
    return ErasureRequestEventModel(
        id=uuid7(),
        workspace_id=request.workspace_id,
        erasure_request_id=request.erasure_request_id,
        action="CREATED",
        actor_id=request.requester_id,
        reason=request.request_reason,
        policy_decision_id=request.request_policy_decision_id,
        occurred_at=utc_now(),
        request_version=1,
        payload_hash=request.payload_hash,
    )


def _erasure_approval_event_model(
    request: ErasureRequest, approval: ErasureApproval
) -> ErasureRequestEventModel:
    return ErasureRequestEventModel(
        id=approval.approval_id,
        workspace_id=request.workspace_id,
        erasure_request_id=request.erasure_request_id,
        action=approval.decision.value,
        actor_id=approval.actor_id,
        reason=approval.reason,
        policy_decision_id=approval.policy_decision_id,
        occurred_at=approval.occurred_at,
        request_version=approval.request_version,
        payload_hash=approval.payload_hash,
    )


def _hydrate_erasure_request(
    model: ErasureRequestModel, events: tuple[ErasureRequestEventModel, ...]
) -> ErasureRequest:
    try:
        target_type = ErasureTargetType(model.target_type)
        classification = Classification(model.classification)
        state = ErasureRequestState(model.state)
    except ValueError as error:
        raise ConflictError("The stored erasure request is invalid.") from error
    document = {
        "workspace_id": str(model.workspace_id),
        "target_type": target_type.value,
        "target_id": str(model.target_id),
        "target_version": model.target_version,
        "target_owner_id": str(model.target_owner_id) if model.target_owner_id else None,
        "classification": classification.name,
        "retention_policy_id": str(model.retention_policy_id),
        "retention_policy_hash": model.retention_policy_hash,
        "requester_id": str(model.requester_id),
        "request_reason": model.request_reason,
        "request_policy_decision_id": str(model.request_policy_decision_id),
        "expires_at": model.expires_at.isoformat(),
    }
    if canonical_json_hash(document) != model.payload_hash:
        raise ConflictError("The stored erasure request payload failed its integrity check.")
    if [event.request_version for event in events] != list(range(1, model.version + 1)):
        raise ConflictError("The stored erasure request event history is incomplete.")
    if not events or not _created_event_matches(model, events[0]):
        raise ConflictError("The stored erasure request creation event is invalid.")

    approvals = [_approval_from_event(model, event) for event in events[1:]]
    expected_action = {
        ErasureRequestState.PENDING: "CREATED",
        ErasureRequestState.APPROVED: GovernanceDecision.APPROVED.value,
        ErasureRequestState.REJECTED: GovernanceDecision.REJECTED.value,
    }[state]
    if events[-1].action != expected_action:
        raise ConflictError("The stored erasure request state and history do not match.")
    return ErasureRequest(
        erasure_request_id=model.id,
        workspace_id=model.workspace_id,
        target_type=target_type,
        target_id=model.target_id,
        target_version=model.target_version,
        target_owner_id=model.target_owner_id,
        classification=classification,
        retention_policy_id=model.retention_policy_id,
        retention_policy_hash=model.retention_policy_hash,
        requester_id=model.requester_id,
        request_reason=model.request_reason,
        request_policy_decision_id=model.request_policy_decision_id,
        payload_hash=model.payload_hash,
        expires_at=model.expires_at,
        state=state,
        checker_id=model.checker_id,
        decision_reason=model.decision_reason,
        decision_policy_decision_id=model.decision_policy_decision_id,
        decided_at=model.decided_at,
        version=model.version,
        approvals=approvals,
    )


def _created_event_matches(model: ErasureRequestModel, event: ErasureRequestEventModel) -> bool:
    return (
        event.action == "CREATED"
        and event.actor_id == model.requester_id
        and event.reason == model.request_reason
        and event.policy_decision_id == model.request_policy_decision_id
        and event.payload_hash == model.payload_hash
        and event.request_version == 1
    )


def _approval_from_event(
    model: ErasureRequestModel, event: ErasureRequestEventModel
) -> ErasureApproval:
    try:
        decision = GovernanceDecision(event.action)
    except ValueError as error:
        raise ConflictError("The stored erasure approval action is invalid.") from error
    if event.payload_hash != model.payload_hash:
        raise ConflictError("The stored erasure approval lost its target binding.")
    if (
        event.actor_id != model.checker_id
        or event.reason != model.decision_reason
        or event.policy_decision_id != model.decision_policy_decision_id
        or event.occurred_at != model.decided_at
    ):
        raise ConflictError("The stored erasure approval does not match its request.")
    return ErasureApproval(
        approval_id=event.id,
        decision=decision,
        actor_id=event.actor_id,
        reason=event.reason,
        policy_decision_id=event.policy_decision_id,
        payload_hash=event.payload_hash,
        request_version=event.request_version,
        occurred_at=event.occurred_at,
    )


def _classification_or_restricted(value: int | None) -> Classification:
    if value is None:
        return Classification.RESTRICTED
    try:
        return Classification(value)
    except ValueError:
        return Classification.RESTRICTED
