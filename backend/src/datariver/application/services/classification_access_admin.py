from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from datariver.application.classification_access_admin import (
    ClassificationAccessAdminUnitOfWork,
    ClassificationPolicyPage,
    RestrictedSearchGrantPage,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    Classification,
    Decision,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.classification_access import (
    ClassificationAccessPolicy,
    ClassificationAccessPolicyState,
    ClassificationAccessRule,
    GrantDecision,
    PolicyDecision,
    RestrictedSearchGrant,
    RestrictedSearchGrantState,
    RestrictedSearchScope,
    SearchMode,
)
from datariver.domain.common import ConflictError, NotFoundError


class ClassificationAccessAdminService:
    def __init__(
        self,
        uow_factory: Callable[[], ClassificationAccessAdminUnitOfWork],
        authorization: AuthorizationService,
    ) -> None:
        self._uow_factory = uow_factory
        self._authorization = authorization

    async def propose_policy(
        self,
        *,
        workspace_id: UUID,
        required_jurisdiction: str,
        restricted_search_grant_maximum_days: int,
        rules: tuple[ClassificationAccessRule, ...],
        reason: str,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> ClassificationAccessPolicy:
        decision = await self._authorize(
            workspace_id, workspace_id, subject, environment, request_id
        )
        operation = "classification_access.policy.propose"
        async with self._uow_factory() as uow:
            await self._prepare(uow, workspace_id=workspace_id, subject=subject, lock=True)
            replay = await uow.idempotency.get_result(
                workspace_id=workspace_id, key=idempotency_key, operation=operation
            )
            if replay is not None:
                _verify_replay_request(replay.request_hash, request_hash, replay.result, subject)
                stored = await uow.policies.get(
                    workspace_id=workspace_id,
                    policy_id=UUID(str(replay.result["policy_id"])),
                )
                return _required_replay(stored, replay.result, "classification policy")
            policy = ClassificationAccessPolicy.propose(
                workspace_id=workspace_id,
                policy_number=await uow.policies.next_policy_number(workspace_id=workspace_id),
                required_jurisdiction=required_jurisdiction,
                restricted_search_grant_maximum_days=(restricted_search_grant_maximum_days),
                rules=rules,
                requester_id=subject.subject_id,
                reason=reason,
                policy_decision_id=decision.decision_id,
            )
            await uow.policies.add(policy)
            await uow.outbox.add_events(policy.events)
            await _save_replay(
                uow,
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                actor_id=subject.subject_id,
                aggregate_id=policy.policy_id,
                aggregate_key="policy_id",
                state=policy.state.value,
                version=policy.version,
            )
            await uow.commit()
        policy.events.clear()
        return policy

    async def list_policies(
        self,
        *,
        workspace_id: UUID,
        state: ClassificationAccessPolicyState | None,
        limit: int,
        cursor: str | None,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> ClassificationPolicyPage:
        await self._authorize(workspace_id, workspace_id, subject, environment, request_id)
        async with self._uow_factory() as uow:
            await self._prepare(uow, workspace_id=workspace_id, subject=subject, lock=False)
            return await uow.policies.list(
                workspace_id=workspace_id,
                state=state.value if state is not None else None,
                limit=limit,
                cursor=cursor,
            )

    async def get_policy(
        self,
        *,
        workspace_id: UUID,
        policy_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> ClassificationAccessPolicy:
        await self._authorize(workspace_id, policy_id, subject, environment, request_id)
        async with self._uow_factory() as uow:
            await self._prepare(uow, workspace_id=workspace_id, subject=subject, lock=False)
            policy = await uow.policies.get(workspace_id=workspace_id, policy_id=policy_id)
            if policy is None:
                raise NotFoundError("The classification policy does not exist.")
            return policy

    async def current_policy(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> ClassificationAccessPolicy | None:
        await self._authorize(workspace_id, workspace_id, subject, environment, request_id)
        async with self._uow_factory() as uow:
            await self._prepare(uow, workspace_id=workspace_id, subject=subject, lock=False)
            return await uow.policies.get_active(workspace_id=workspace_id)

    async def approve_policy(
        self,
        *,
        workspace_id: UUID,
        policy_id: UUID,
        reason: str,
        expected_version: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> ClassificationAccessPolicy:
        return await self._decide_policy(
            decision=PolicyDecision.APPROVED,
            workspace_id=workspace_id,
            policy_id=policy_id,
            reason=reason,
            expected_version=expected_version,
            subject=subject,
            environment=environment,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def reject_policy(
        self,
        *,
        workspace_id: UUID,
        policy_id: UUID,
        reason: str,
        expected_version: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> ClassificationAccessPolicy:
        return await self._decide_policy(
            decision=PolicyDecision.REJECTED,
            workspace_id=workspace_id,
            policy_id=policy_id,
            reason=reason,
            expected_version=expected_version,
            subject=subject,
            environment=environment,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def _decide_policy(
        self,
        *,
        decision: PolicyDecision,
        workspace_id: UUID,
        policy_id: UUID,
        reason: str,
        expected_version: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> ClassificationAccessPolicy:
        authorization = await self._authorize(
            workspace_id, policy_id, subject, environment, request_id
        )
        operation = f"classification_access.policy.{decision.value.lower()}:{policy_id}"
        async with self._uow_factory() as uow:
            await self._prepare(uow, workspace_id=workspace_id, subject=subject, lock=True)
            policy = await uow.policies.get_for_update(
                workspace_id=workspace_id, policy_id=policy_id
            )
            if policy is None:
                raise NotFoundError("The classification policy proposal does not exist.")
            replay = await uow.idempotency.get_result(
                workspace_id=workspace_id, key=idempotency_key, operation=operation
            )
            if replay is not None:
                _verify_replay_request(replay.request_hash, request_hash, replay.result, subject)
                return _required_replay(policy, replay.result, "classification policy")
            events = list(policy.events)
            if decision is PolicyDecision.APPROVED:
                await uow.policies.assert_provider_rules_eligible(
                    policy=policy, now=environment.requested_at
                )
                previous = await uow.policies.get_active_for_update(
                    workspace_id=workspace_id, excluding_policy_id=policy_id
                )
                if previous is not None:
                    previous.supersede(
                        actor_id=subject.subject_id,
                        reason=reason,
                        policy_decision_id=authorization.decision_id,
                        expected_version=previous.version,
                        now=environment.requested_at,
                    )
                    await uow.policies.save(previous)
                    events.extend(previous.events)
            policy.decide(
                decision=decision,
                actor_id=subject.subject_id,
                reason=reason,
                policy_decision_id=authorization.decision_id,
                expected_version=expected_version,
                now=environment.requested_at,
            )
            await uow.policies.save(policy)
            events.extend(policy.events)
            await uow.outbox.add_events(events)
            await _save_replay(
                uow,
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                actor_id=subject.subject_id,
                aggregate_id=policy.policy_id,
                aggregate_key="policy_id",
                state=policy.state.value,
                version=policy.version,
            )
            await uow.commit()
        policy.events.clear()
        return policy

    async def propose_grant(
        self,
        *,
        workspace_id: UUID,
        target_subject_id: UUID,
        scope: RestrictedSearchScope,
        scope_id: UUID,
        purpose: str,
        valid_from: datetime,
        expires_at: datetime,
        reason: str,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> RestrictedSearchGrant:
        decision = await self._authorize(
            workspace_id, target_subject_id, subject, environment, request_id
        )
        operation = "classification_access.grant.propose"
        async with self._uow_factory() as uow:
            await self._prepare(uow, workspace_id=workspace_id, subject=subject, lock=True)
            replay = await uow.idempotency.get_result(
                workspace_id=workspace_id, key=idempotency_key, operation=operation
            )
            if replay is not None:
                _verify_replay_request(replay.request_hash, request_hash, replay.result, subject)
                stored = await uow.grants.get(
                    workspace_id=workspace_id,
                    grant_id=UUID(str(replay.result["grant_id"])),
                )
                return _required_replay(stored, replay.result, "RESTRICTED Search grant")
            policy = await uow.policies.get_active_for_update(workspace_id=workspace_id)
            if policy is None or (
                policy.rule_for(Classification.RESTRICTED).search_mode
                is not SearchMode.EXPLICIT_GRANT_ONLY
            ):
                raise ConflictError("An active explicit-grant classification policy is required.")
            grant = RestrictedSearchGrant.propose(
                workspace_id=workspace_id,
                classification_policy_id=policy.policy_id,
                classification_policy_hash=policy.payload_hash,
                subject_id=target_subject_id,
                scope=scope,
                scope_id=scope_id,
                purpose=purpose,
                valid_from=valid_from,
                expires_at=expires_at,
                requester_id=subject.subject_id,
                reason=reason,
                policy_decision_id=decision.decision_id,
                now=environment.requested_at,
                maximum_lifetime=timedelta(days=policy.restricted_search_grant_maximum_days),
            )
            await uow.grants.add(grant)
            await uow.outbox.add_events(grant.events)
            await _save_replay(
                uow,
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                actor_id=subject.subject_id,
                aggregate_id=grant.grant_id,
                aggregate_key="grant_id",
                state=grant.state.value,
                version=grant.version,
            )
            await uow.commit()
        grant.events.clear()
        return grant

    async def list_grants(
        self,
        *,
        workspace_id: UUID,
        target_subject_id: UUID | None,
        state: RestrictedSearchGrantState | None,
        limit: int,
        cursor: str | None,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> RestrictedSearchGrantPage:
        await self._authorize(workspace_id, workspace_id, subject, environment, request_id)
        async with self._uow_factory() as uow:
            await self._prepare(uow, workspace_id=workspace_id, subject=subject, lock=False)
            return await uow.grants.list(
                workspace_id=workspace_id,
                subject_id=target_subject_id,
                state=state.value if state is not None else None,
                limit=limit,
                cursor=cursor,
            )

    async def get_grant(
        self,
        *,
        workspace_id: UUID,
        grant_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> RestrictedSearchGrant:
        await self._authorize(workspace_id, grant_id, subject, environment, request_id)
        async with self._uow_factory() as uow:
            await self._prepare(uow, workspace_id=workspace_id, subject=subject, lock=False)
            grant = await uow.grants.get(workspace_id=workspace_id, grant_id=grant_id)
            if grant is None:
                raise NotFoundError("The RESTRICTED Search grant does not exist.")
            return grant

    async def approve_grant(
        self,
        *,
        workspace_id: UUID,
        grant_id: UUID,
        reason: str,
        expected_version: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> RestrictedSearchGrant:
        return await self._decide_grant(
            decision=GrantDecision.APPROVED,
            workspace_id=workspace_id,
            grant_id=grant_id,
            reason=reason,
            expected_version=expected_version,
            subject=subject,
            environment=environment,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def reject_grant(
        self,
        *,
        workspace_id: UUID,
        grant_id: UUID,
        reason: str,
        expected_version: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> RestrictedSearchGrant:
        return await self._decide_grant(
            decision=GrantDecision.REJECTED,
            workspace_id=workspace_id,
            grant_id=grant_id,
            reason=reason,
            expected_version=expected_version,
            subject=subject,
            environment=environment,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def _decide_grant(
        self,
        *,
        decision: GrantDecision,
        workspace_id: UUID,
        grant_id: UUID,
        reason: str,
        expected_version: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> RestrictedSearchGrant:
        authorization = await self._authorize(
            workspace_id, grant_id, subject, environment, request_id
        )
        operation = f"classification_access.grant.{decision.value.lower()}:{grant_id}"
        async with self._uow_factory() as uow:
            await self._prepare(uow, workspace_id=workspace_id, subject=subject, lock=True)
            grant = await uow.grants.get_for_update(workspace_id=workspace_id, grant_id=grant_id)
            if grant is None:
                raise NotFoundError("The RESTRICTED Search grant does not exist.")
            replay = await uow.idempotency.get_result(
                workspace_id=workspace_id, key=idempotency_key, operation=operation
            )
            if replay is not None:
                _verify_replay_request(replay.request_hash, request_hash, replay.result, subject)
                return _required_replay(grant, replay.result, "RESTRICTED Search grant")
            if decision is GrantDecision.APPROVED:
                current = await uow.policies.get_active_for_update(workspace_id=workspace_id)
                if (
                    current is None
                    or current.policy_id != grant.classification_policy_id
                    or current.payload_hash != grant.classification_policy_hash
                ):
                    raise ConflictError("The grant no longer binds the active policy.")
            grant.decide(
                decision=decision,
                actor_id=subject.subject_id,
                reason=reason,
                policy_decision_id=authorization.decision_id,
                expected_version=expected_version,
                now=environment.requested_at,
            )
            await uow.grants.save(grant)
            await uow.outbox.add_events(grant.events)
            await _save_replay(
                uow,
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                actor_id=subject.subject_id,
                aggregate_id=grant.grant_id,
                aggregate_key="grant_id",
                state=grant.state.value,
                version=grant.version,
            )
            await uow.commit()
        grant.events.clear()
        return grant

    async def revoke_grant(
        self,
        *,
        workspace_id: UUID,
        grant_id: UUID,
        reason: str,
        expected_version: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> RestrictedSearchGrant:
        authorization = await self._authorize(
            workspace_id, grant_id, subject, environment, request_id
        )
        operation = f"classification_access.grant.revoke:{grant_id}"
        async with self._uow_factory() as uow:
            await self._prepare(uow, workspace_id=workspace_id, subject=subject, lock=True)
            grant = await uow.grants.get_for_update(workspace_id=workspace_id, grant_id=grant_id)
            if grant is None:
                raise NotFoundError("The RESTRICTED Search grant does not exist.")
            replay = await uow.idempotency.get_result(
                workspace_id=workspace_id, key=idempotency_key, operation=operation
            )
            if replay is not None:
                _verify_replay_request(replay.request_hash, request_hash, replay.result, subject)
                return _required_replay(grant, replay.result, "RESTRICTED Search grant")
            grant.revoke(
                actor_id=subject.subject_id,
                reason=reason,
                policy_decision_id=authorization.decision_id,
                expected_version=expected_version,
                now=environment.requested_at,
            )
            await uow.grants.save(grant)
            await uow.outbox.add_events(grant.events)
            await _save_replay(
                uow,
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                actor_id=subject.subject_id,
                aggregate_id=grant.grant_id,
                aggregate_key="grant_id",
                state=grant.state.value,
                version=grant.version,
            )
            await uow.commit()
        grant.events.clear()
        return grant

    async def _prepare(
        self,
        uow: ClassificationAccessAdminUnitOfWork,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        lock: bool,
    ) -> None:
        await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
        if lock:
            await uow.lock_workspace(workspace_id=workspace_id)
        await uow.memberships.assert_eligible_human_administrators(
            workspace_id=workspace_id, subject_ids=frozenset({subject.subject_id})
        )

    async def _authorize(
        self,
        workspace_id: UUID,
        resource_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> Decision:
        return await self._authorization.authorize(
            subject=subject,
            resource=ResourceAttributes(
                resource_id=resource_id,
                workspace_id=workspace_id,
                resource_type="classification_access_administration",
                owner_department_id=None,
                system_id=None,
                domain_id=None,
                classification=Classification.RESTRICTED,
                lifecycle="ACTIVE",
            ),
            action=Action.ADMIN_MANAGE,
            environment=environment,
            request_id=request_id,
        )


async def _save_replay(
    uow: ClassificationAccessAdminUnitOfWork,
    *,
    workspace_id: UUID,
    key: str,
    operation: str,
    request_hash: str,
    actor_id: UUID,
    aggregate_id: UUID,
    aggregate_key: str,
    state: str,
    version: int,
) -> None:
    await uow.idempotency.save_result(
        workspace_id=workspace_id,
        key=key,
        operation=operation,
        request_hash=request_hash,
        result={
            "actor_id": str(actor_id),
            aggregate_key: str(aggregate_id),
            "state": state,
            "version": version,
        },
    )


def _verify_replay_request(
    stored_hash: str,
    request_hash: str,
    result: dict[str, object],
    subject: SubjectAttributes,
) -> None:
    if stored_hash != request_hash:
        raise ConflictError("The idempotency key was used with a different request.")
    if result.get("actor_id") != str(subject.subject_id):
        raise ConflictError("The idempotency key belongs to another subject.")


def _required_replay[T: ClassificationAccessPolicy | RestrictedSearchGrant](
    aggregate: T | None, result: dict[str, object], name: str
) -> T:
    if aggregate is None:
        raise ConflictError(f"The idempotent {name} result is unavailable.")
    if result.get("state") != aggregate.state.value or result.get("version") != aggregate.version:
        raise ConflictError(
            "The original idempotent response is no longer current; refresh the resource."
        )
    return aggregate
