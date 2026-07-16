from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import timedelta
from uuid import UUID

from datariver.application.ports import RetentionUnitOfWork
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    Classification,
    Decision,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ConflictError, NotFoundError
from datariver.domain.retention import (
    ErasureRequest,
    ErasureRequestState,
    ErasureTargetSnapshot,
    ErasureTargetType,
    GovernanceDecision,
    LegalHold,
    LegalHoldScope,
    LegalHoldState,
    RetentionDataClass,
    RetentionPolicyState,
    RetentionPolicyVersion,
    RetentionRules,
)


class RetentionGovernanceService:
    def __init__(
        self,
        uow_factory: Callable[[], RetentionUnitOfWork],
        authorization: AuthorizationService,
    ) -> None:
        self._uow_factory = uow_factory
        self._authorization = authorization

    async def propose_policy(
        self,
        *,
        workspace_id: UUID,
        rules: RetentionRules,
        reason: str,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> RetentionPolicyVersion:
        decision = await self._authorize(
            workspace_id=workspace_id,
            resource_id=workspace_id,
            action=Action.RETENTION_MANAGE,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        operation = "retention.policy.propose"
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await uow.lock_workspace(workspace_id=workspace_id)
            existing = await uow.idempotency.get_result(
                workspace_id=workspace_id, key=idempotency_key, operation=operation
            )
            if existing is not None:
                _verify_idempotency(
                    existing.request_hash,
                    request_hash,
                    existing.result.get("actor_id"),
                    subject.subject_id,
                )
                stored = await uow.policies.get(
                    workspace_id=workspace_id,
                    policy_id=UUID(str(existing.result["policy_id"])),
                )
                if stored is None:
                    raise ConflictError("The idempotent retention policy result is unavailable.")
                _verify_replay_snapshot(
                    stored_state=existing.result.get("state"),
                    stored_version=existing.result.get("version"),
                    current_state=stored.state.value,
                    current_version=stored.version,
                )
                return stored
            policy = RetentionPolicyVersion.propose(
                workspace_id=workspace_id,
                policy_number=await uow.policies.next_policy_number(workspace_id=workspace_id),
                rules=rules,
                requester_id=subject.subject_id,
                reason=reason,
                policy_decision_id=decision.decision_id,
            )
            await uow.policies.add(policy)
            await uow.outbox.add_events(policy.events)
            await uow.idempotency.save_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                result={
                    "actor_id": str(subject.subject_id),
                    "policy_id": str(policy.policy_id),
                    "state": policy.state.value,
                    "version": policy.version,
                },
            )
            await uow.commit()
        policy.events.clear()
        return policy

    async def decide_policy(
        self,
        *,
        workspace_id: UUID,
        policy_id: UUID,
        governance_decision: GovernanceDecision,
        reason: str,
        expected_version: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> RetentionPolicyVersion:
        decision = await self._authorize(
            workspace_id=workspace_id,
            resource_id=policy_id,
            action=Action.RETENTION_MANAGE,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        operation = f"retention.policy.decide:{policy_id}"
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await uow.lock_workspace(workspace_id=workspace_id)
            policy = await uow.policies.get_for_update(
                workspace_id=workspace_id, policy_id=policy_id
            )
            if policy is None:
                raise NotFoundError("The retention policy proposal does not exist.")
            existing = await uow.idempotency.get_result(
                workspace_id=workspace_id, key=idempotency_key, operation=operation
            )
            if existing is not None:
                _verify_idempotency(
                    existing.request_hash,
                    request_hash,
                    existing.result.get("actor_id"),
                    subject.subject_id,
                )
                _verify_replay_snapshot(
                    stored_state=existing.result.get("state"),
                    stored_version=existing.result.get("version"),
                    current_state=policy.state.value,
                    current_version=policy.version,
                )
                return policy
            policy.decide(
                decision=governance_decision,
                actor_id=subject.subject_id,
                reason=reason,
                policy_decision_id=decision.decision_id,
                expected_version=expected_version,
                now=environment.requested_at,
            )
            events = list(policy.events)
            if governance_decision is GovernanceDecision.APPROVED:
                previous = await uow.policies.get_active_for_update(
                    workspace_id=workspace_id, excluding_policy_id=policy_id
                )
                if previous is not None:
                    previous.supersede(
                        actor_id=subject.subject_id,
                        reason=reason,
                        policy_decision_id=decision.decision_id,
                        now=environment.requested_at,
                    )
                    await uow.policies.save(previous)
                    events.extend(previous.events)
            await uow.policies.save(policy)
            await uow.outbox.add_events(events)
            await uow.idempotency.save_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                result={
                    "actor_id": str(subject.subject_id),
                    "policy_id": str(policy_id),
                    "state": policy.state.value,
                    "version": policy.version,
                },
            )
            await uow.commit()
        policy.events.clear()
        return policy

    async def list_policies(
        self,
        *,
        workspace_id: UUID,
        state: RetentionPolicyState | None,
        limit: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> Sequence[RetentionPolicyVersion]:
        await self._authorize(
            workspace_id=workspace_id,
            resource_id=workspace_id,
            action=Action.RETENTION_READ,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            return await uow.policies.list(
                workspace_id=workspace_id,
                state=state.value if state is not None else None,
                limit=limit,
            )

    async def get_active_policy(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> RetentionPolicyVersion | None:
        await self._authorize(
            workspace_id=workspace_id,
            resource_id=workspace_id,
            action=Action.RETENTION_READ,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            return await uow.policies.get_active(workspace_id=workspace_id)

    async def place_legal_hold(
        self,
        *,
        workspace_id: UUID,
        data_class: RetentionDataClass,
        scope: LegalHoldScope,
        scope_id: UUID | None,
        reason: str,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> LegalHold:
        decision = await self._authorize(
            workspace_id=workspace_id,
            resource_id=scope_id or workspace_id,
            action=Action.LEGAL_HOLD_PLACE,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        operation = "retention.legal_hold.place"
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await uow.lock_workspace(workspace_id=workspace_id)
            existing = await uow.idempotency.get_result(
                workspace_id=workspace_id, key=idempotency_key, operation=operation
            )
            if existing is not None:
                _verify_idempotency(
                    existing.request_hash,
                    request_hash,
                    existing.result.get("actor_id"),
                    subject.subject_id,
                )
                stored = await uow.legal_holds.get(
                    workspace_id=workspace_id,
                    hold_id=UUID(str(existing.result["hold_id"])),
                )
                if stored is None:
                    raise ConflictError("The idempotent Legal Hold result is unavailable.")
                _verify_replay_snapshot(
                    stored_state=existing.result.get("state"),
                    stored_version=existing.result.get("version"),
                    current_state=stored.state.value,
                    current_version=stored.version,
                )
                return stored
            hold = LegalHold.create(
                workspace_id=workspace_id,
                data_class=data_class,
                scope=scope,
                scope_id=scope_id,
                reason=reason,
                actor_id=subject.subject_id,
                policy_decision_id=decision.decision_id,
                now=environment.requested_at,
            )
            await uow.legal_holds.add(hold)
            await uow.outbox.add_events(hold.events)
            await uow.idempotency.save_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                result={
                    "actor_id": str(subject.subject_id),
                    "hold_id": str(hold.hold_id),
                    "state": hold.state.value,
                    "version": hold.version,
                },
            )
            await uow.commit()
        hold.events.clear()
        return hold

    async def list_legal_holds(
        self,
        *,
        workspace_id: UUID,
        state: LegalHoldState | None,
        limit: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> Sequence[LegalHold]:
        await self._authorize(
            workspace_id=workspace_id,
            resource_id=workspace_id,
            action=Action.RETENTION_READ,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            return await uow.legal_holds.list(
                workspace_id=workspace_id,
                state=state.value if state is not None else None,
                limit=limit,
            )

    async def request_legal_hold_release(
        self,
        *,
        workspace_id: UUID,
        hold_id: UUID,
        reason: str,
        expected_version: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> LegalHold:
        decision = await self._authorize(
            workspace_id=workspace_id,
            resource_id=hold_id,
            action=Action.LEGAL_HOLD_RELEASE,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        return await self._change_hold(
            workspace_id=workspace_id,
            hold_id=hold_id,
            operation=f"retention.legal_hold.release_request:{hold_id}",
            subject=subject,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            apply=lambda hold: hold.request_release(
                actor_id=subject.subject_id,
                reason=reason,
                policy_decision_id=decision.decision_id,
                expected_version=expected_version,
                now=environment.requested_at,
            ),
        )

    async def decide_legal_hold_release(
        self,
        *,
        workspace_id: UUID,
        hold_id: UUID,
        governance_decision: GovernanceDecision,
        reason: str,
        expected_version: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> LegalHold:
        decision = await self._authorize(
            workspace_id=workspace_id,
            resource_id=hold_id,
            action=Action.LEGAL_HOLD_RELEASE,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        return await self._change_hold(
            workspace_id=workspace_id,
            hold_id=hold_id,
            operation=f"retention.legal_hold.release_decision:{hold_id}",
            subject=subject,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            apply=lambda hold: hold.decide_release(
                decision=governance_decision,
                actor_id=subject.subject_id,
                reason=reason,
                policy_decision_id=decision.decision_id,
                expected_version=expected_version,
                now=environment.requested_at,
            ),
        )

    async def request_erasure(
        self,
        *,
        workspace_id: UUID,
        target_type: ErasureTargetType,
        target_id: UUID,
        reason: str,
        review_ttl_seconds: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> ErasureRequest:
        operation = f"retention.erasure.request:{target_type.value}:{target_id}"
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await uow.lock_workspace(workspace_id=workspace_id)
            target = await uow.erasure_targets.get_erasure_target_snapshot(
                workspace_id=workspace_id,
                target_type=target_type,
                target_id=target_id,
            )
            if target is None:
                raise NotFoundError("The erasure target does not exist.")
            decision = await self._authorize_erasure(
                workspace_id=workspace_id,
                target=target,
                action=Action.ERASURE_REQUEST,
                subject=subject,
                environment=environment,
                request_id=request_id,
            )
            existing = await uow.idempotency.get_result(
                workspace_id=workspace_id, key=idempotency_key, operation=operation
            )
            if existing is not None:
                _verify_idempotency(
                    existing.request_hash,
                    request_hash,
                    existing.result.get("actor_id"),
                    subject.subject_id,
                )
                stored = await uow.erasure_requests.get(
                    workspace_id=workspace_id,
                    erasure_request_id=UUID(str(existing.result["erasure_request_id"])),
                )
                if stored is None:
                    raise ConflictError("The idempotent erasure request result is unavailable.")
                _verify_replay_snapshot(
                    stored_state=existing.result.get("state"),
                    stored_version=existing.result.get("version"),
                    current_state=stored.state.value,
                    current_version=stored.version,
                )
                return stored
            policy = await uow.policies.get_active(workspace_id=workspace_id)
            if policy is None:
                raise ConflictError("An active retention policy is required for erasure review.")
            erasure_request = ErasureRequest.create(
                workspace_id=workspace_id,
                target_type=target.target_type,
                target_id=target.target_id,
                target_version=target.version,
                target_owner_id=target.owner_id,
                classification=target.classification,
                retention_policy_id=policy.policy_id,
                retention_policy_hash=policy.payload_hash,
                requester_id=subject.subject_id,
                reason=reason,
                policy_decision_id=decision.decision_id,
                now=environment.requested_at,
                expires_at=environment.requested_at + timedelta(seconds=review_ttl_seconds),
            )
            await uow.erasure_requests.add(erasure_request)
            await uow.outbox.add_events(erasure_request.events)
            await uow.idempotency.save_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                result={
                    "actor_id": str(subject.subject_id),
                    "erasure_request_id": str(erasure_request.erasure_request_id),
                    "state": erasure_request.state.value,
                    "version": erasure_request.version,
                },
            )
            await uow.commit()
        erasure_request.events.clear()
        return erasure_request

    async def list_erasure_requests(
        self,
        *,
        workspace_id: UUID,
        state: ErasureRequestState | None,
        limit: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> Sequence[ErasureRequest]:
        await self._authorize(
            workspace_id=workspace_id,
            resource_id=workspace_id,
            action=Action.RETENTION_READ,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            return await uow.erasure_requests.list(
                workspace_id=workspace_id,
                state=state.value if state is not None else None,
                limit=limit,
            )

    async def get_erasure_request(
        self,
        *,
        workspace_id: UUID,
        erasure_request_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> ErasureRequest:
        await self._authorize(
            workspace_id=workspace_id,
            resource_id=erasure_request_id,
            action=Action.RETENTION_READ,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            value = await uow.erasure_requests.get(
                workspace_id=workspace_id,
                erasure_request_id=erasure_request_id,
            )
            if value is None:
                raise NotFoundError("The erasure request does not exist.")
            return value

    async def decide_erasure(
        self,
        *,
        workspace_id: UUID,
        erasure_request_id: UUID,
        governance_decision: GovernanceDecision,
        reason: str,
        expected_version: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> ErasureRequest:
        operation = f"retention.erasure.decide:{erasure_request_id}"
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await uow.lock_workspace(workspace_id=workspace_id)
            erasure_request = await uow.erasure_requests.get_for_update(
                workspace_id=workspace_id,
                erasure_request_id=erasure_request_id,
            )
            if erasure_request is None:
                raise NotFoundError("The erasure request does not exist.")
            target = await uow.erasure_targets.get_erasure_target_snapshot(
                workspace_id=workspace_id,
                target_type=erasure_request.target_type,
                target_id=erasure_request.target_id,
            )
            if target is None and governance_decision is GovernanceDecision.APPROVED:
                raise ConflictError("The erasure target no longer exists.")
            authorization_target = target or ErasureTargetSnapshot(
                target_type=erasure_request.target_type,
                target_id=erasure_request.target_id,
                version=erasure_request.target_version,
                owner_id=erasure_request.target_owner_id,
                classification=erasure_request.classification,
            )
            decision = await self._authorize_erasure(
                workspace_id=workspace_id,
                target=authorization_target,
                action=Action.ERASURE_APPROVE,
                subject=subject,
                environment=environment,
                request_id=request_id,
                requester_id=erasure_request.requester_id,
            )
            existing = await uow.idempotency.get_result(
                workspace_id=workspace_id, key=idempotency_key, operation=operation
            )
            if existing is not None:
                _verify_idempotency(
                    existing.request_hash,
                    request_hash,
                    existing.result.get("actor_id"),
                    subject.subject_id,
                )
                _verify_replay_snapshot(
                    stored_state=existing.result.get("state"),
                    stored_version=existing.result.get("version"),
                    current_state=erasure_request.state.value,
                    current_version=erasure_request.version,
                )
                return erasure_request
            policy = await uow.policies.get_active(workspace_id=workspace_id)
            if policy is None and governance_decision is GovernanceDecision.APPROVED:
                raise ConflictError("An active retention policy is required for erasure approval.")
            active_legal_hold = False
            if target is not None and governance_decision is GovernanceDecision.APPROVED:
                active_legal_hold = await uow.legal_holds.has_active_for_erasure_target(
                    workspace_id=workspace_id,
                    target_type=target.target_type,
                    target_id=target.target_id,
                    target_owner_id=target.owner_id,
                )
            erasure_request.decide(
                decision=governance_decision,
                actor_id=subject.subject_id,
                reason=reason,
                policy_decision_id=decision.decision_id,
                expected_version=expected_version,
                now=environment.requested_at,
                active_legal_hold=active_legal_hold,
                current_target_version=authorization_target.version,
                current_target_owner_id=authorization_target.owner_id,
                current_classification=authorization_target.classification,
                active_retention_policy_id=(
                    policy.policy_id if policy is not None else erasure_request.retention_policy_id
                ),
                active_retention_policy_hash=(
                    policy.payload_hash
                    if policy is not None
                    else erasure_request.retention_policy_hash
                ),
            )
            await uow.erasure_requests.save(erasure_request)
            await uow.outbox.add_events(erasure_request.events)
            await uow.idempotency.save_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                result={
                    "actor_id": str(subject.subject_id),
                    "erasure_request_id": str(erasure_request_id),
                    "state": erasure_request.state.value,
                    "version": erasure_request.version,
                },
            )
            await uow.commit()
        erasure_request.events.clear()
        return erasure_request

    async def _change_hold(
        self,
        *,
        workspace_id: UUID,
        hold_id: UUID,
        operation: str,
        subject: SubjectAttributes,
        idempotency_key: str,
        request_hash: str,
        apply: Callable[[LegalHold], None],
    ) -> LegalHold:
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await uow.lock_workspace(workspace_id=workspace_id)
            hold = await uow.legal_holds.get_for_update(workspace_id=workspace_id, hold_id=hold_id)
            if hold is None:
                raise NotFoundError("The Legal Hold does not exist.")
            existing = await uow.idempotency.get_result(
                workspace_id=workspace_id, key=idempotency_key, operation=operation
            )
            if existing is not None:
                _verify_idempotency(
                    existing.request_hash,
                    request_hash,
                    existing.result.get("actor_id"),
                    subject.subject_id,
                )
                _verify_replay_snapshot(
                    stored_state=existing.result.get("state"),
                    stored_version=existing.result.get("version"),
                    current_state=hold.state.value,
                    current_version=hold.version,
                )
                return hold
            apply(hold)
            await uow.legal_holds.save(hold)
            await uow.outbox.add_events(hold.events)
            await uow.idempotency.save_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                result={
                    "actor_id": str(subject.subject_id),
                    "hold_id": str(hold_id),
                    "state": hold.state.value,
                    "version": hold.version,
                },
            )
            await uow.commit()
        hold.events.clear()
        return hold

    async def _authorize(
        self,
        *,
        workspace_id: UUID,
        resource_id: UUID,
        action: Action,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> Decision:
        return await self._authorization.authorize(
            subject=subject,
            resource=ResourceAttributes(
                resource_id=resource_id,
                workspace_id=workspace_id,
                resource_type="retention_governance",
                owner_department_id=None,
                system_id=None,
                domain_id=None,
                classification=Classification.RESTRICTED,
                lifecycle="ACTIVE",
            ),
            action=action,
            environment=environment,
            request_id=request_id,
        )

    async def _authorize_erasure(
        self,
        *,
        workspace_id: UUID,
        target: ErasureTargetSnapshot,
        action: Action,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        requester_id: UUID | None = None,
    ) -> Decision:
        return await self._authorization.authorize(
            subject=subject,
            resource=ResourceAttributes(
                resource_id=target.target_id,
                workspace_id=workspace_id,
                resource_type=f"erasure_target:{target.target_type.value}",
                owner_department_id=None,
                system_id=None,
                domain_id=None,
                classification=target.classification,
                lifecycle="ACTIVE",
                requester_id=requester_id,
                owner_subject_id=target.owner_id,
            ),
            action=action,
            environment=environment,
            request_id=request_id,
        )


def _verify_idempotency(
    stored_hash: str,
    request_hash: str,
    stored_actor: object,
    actor_id: UUID,
) -> None:
    if stored_hash != request_hash:
        raise ConflictError("The idempotency key was used with a different request.")
    if stored_actor != str(actor_id):
        raise ConflictError("The idempotency key belongs to another subject.")


def _verify_replay_snapshot(
    *,
    stored_state: object,
    stored_version: object,
    current_state: str,
    current_version: int,
) -> None:
    if stored_state != current_state or stored_version != current_version:
        raise ConflictError(
            "The original idempotent response snapshot is no longer current; refresh the resource."
        )
