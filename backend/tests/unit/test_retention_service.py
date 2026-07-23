from __future__ import annotations

from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self, cast
from uuid import UUID, uuid4

import pytest

from datariver.application.dto import IdempotencyRecord
from datariver.application.ports import RetentionUnitOfWork
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.retention import RetentionGovernanceService
from datariver.domain.authz import (
    Action,
    AuthenticationAssurance,
    Classification,
    Decision,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ConflictError, DomainEvent, ForbiddenError, ValidationError
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


class MemoryDecisionWriter:
    async def append_decision(
        self,
        *,
        decision: Decision,
        subject_id: UUID,
        workspace_id: UUID,
        resource_id: UUID,
        action: str,
        request_id: str,
    ) -> None:
        del decision, subject_id, workspace_id, resource_id, action, request_id


class MemoryPolicies:
    def __init__(self, values: dict[UUID, RetentionPolicyVersion]) -> None:
        self.values = values

    async def add(self, policy: RetentionPolicyVersion) -> None:
        self.values[policy.policy_id] = policy

    async def get(self, *, workspace_id: UUID, policy_id: UUID) -> RetentionPolicyVersion | None:
        value = self.values.get(policy_id)
        return value if value is not None and value.workspace_id == workspace_id else None

    async def get_for_update(
        self, *, workspace_id: UUID, policy_id: UUID
    ) -> RetentionPolicyVersion | None:
        return await self.get(workspace_id=workspace_id, policy_id=policy_id)

    async def get_active(self, *, workspace_id: UUID) -> RetentionPolicyVersion | None:
        return next(
            (
                value
                for value in self.values.values()
                if value.workspace_id == workspace_id and value.state is RetentionPolicyState.ACTIVE
            ),
            None,
        )

    async def get_active_for_update(
        self, *, workspace_id: UUID, excluding_policy_id: UUID | None = None
    ) -> RetentionPolicyVersion | None:
        return next(
            (
                value
                for value in self.values.values()
                if value.workspace_id == workspace_id
                and value.policy_id != excluding_policy_id
                and value.state is RetentionPolicyState.ACTIVE
            ),
            None,
        )

    async def list(
        self, *, workspace_id: UUID, state: str | None, limit: int
    ) -> Sequence[RetentionPolicyVersion]:
        return tuple(
            value
            for value in sorted(self.values.values(), key=lambda item: item.policy_number)
            if value.workspace_id == workspace_id and (state is None or value.state.value == state)
        )[:limit]

    async def next_policy_number(self, *, workspace_id: UUID) -> int:
        return (
            max(
                (
                    value.policy_number
                    for value in self.values.values()
                    if value.workspace_id == workspace_id
                ),
                default=0,
            )
            + 1
        )

    async def save(self, policy: RetentionPolicyVersion) -> None:
        self.values[policy.policy_id] = policy


class MemoryLegalHolds:
    def __init__(self, values: dict[UUID, LegalHold], state: dict[str, object]) -> None:
        self.values = values
        self.state = state

    async def add(self, hold: LegalHold) -> None:
        self.values[hold.hold_id] = hold

    async def get(self, *, workspace_id: UUID, hold_id: UUID) -> LegalHold | None:
        value = self.values.get(hold_id)
        return value if value is not None and value.workspace_id == workspace_id else None

    async def get_for_update(self, *, workspace_id: UUID, hold_id: UUID) -> LegalHold | None:
        return await self.get(workspace_id=workspace_id, hold_id=hold_id)

    async def list(
        self, *, workspace_id: UUID, state: str | None, limit: int
    ) -> Sequence[LegalHold]:
        return tuple(
            value
            for value in self.values.values()
            if value.workspace_id == workspace_id and (state is None or value.state.value == state)
        )[:limit]

    async def save(self, hold: LegalHold) -> None:
        self.values[hold.hold_id] = hold

    async def has_active_for_erasure_target(
        self,
        *,
        workspace_id: UUID,
        target_type: ErasureTargetType,
        target_id: UUID,
        target_owner_id: UUID | None,
    ) -> bool:
        del target_type, target_id, target_owner_id
        assert workspace_id == self.state["workspace_id"]
        return cast(bool, self.state["hold_blocks"])


class MemoryErasureRequests:
    def __init__(self, values: dict[UUID, ErasureRequest]) -> None:
        self.values = values

    async def add(self, request: ErasureRequest) -> None:
        self.values[request.erasure_request_id] = request

    async def get(self, *, workspace_id: UUID, erasure_request_id: UUID) -> ErasureRequest | None:
        value = self.values.get(erasure_request_id)
        return value if value is not None and value.workspace_id == workspace_id else None

    async def get_for_update(
        self, *, workspace_id: UUID, erasure_request_id: UUID
    ) -> ErasureRequest | None:
        return await self.get(workspace_id=workspace_id, erasure_request_id=erasure_request_id)

    async def list(
        self, *, workspace_id: UUID, state: str | None, limit: int
    ) -> Sequence[ErasureRequest]:
        return tuple(
            value
            for value in self.values.values()
            if value.workspace_id == workspace_id and (state is None or value.state.value == state)
        )[:limit]

    async def save(self, request: ErasureRequest) -> None:
        self.values[request.erasure_request_id] = request


class MemoryErasureTargets:
    def __init__(self, values: dict[tuple[ErasureTargetType, UUID], ErasureTargetSnapshot]) -> None:
        self.values = values

    async def get_erasure_target_snapshot(
        self,
        *,
        workspace_id: UUID,
        target_type: ErasureTargetType,
        target_id: UUID,
    ) -> ErasureTargetSnapshot | None:
        del workspace_id
        return self.values.get((target_type, target_id))


class MemoryOutbox:
    def __init__(self, values: list[DomainEvent]) -> None:
        self.values = values

    async def add_events(self, events: Sequence[DomainEvent]) -> None:
        self.values.extend(events)


class MemoryIdempotency:
    def __init__(self, values: dict[tuple[UUID, str, str], IdempotencyRecord]) -> None:
        self.values = values

    async def get_result(
        self, *, workspace_id: UUID, key: str, operation: str
    ) -> IdempotencyRecord | None:
        return self.values.get((workspace_id, key, operation))

    async def save_result(
        self,
        *,
        workspace_id: UUID,
        key: str,
        operation: str,
        request_hash: str,
        result: dict[str, object],
    ) -> None:
        self.values[(workspace_id, key, operation)] = IdempotencyRecord(
            request_hash=request_hash, result=result
        )


class MemoryRetentionUnitOfWork:
    def __init__(self, state: dict[str, object]) -> None:
        self.state = state
        self.policies = MemoryPolicies(cast(dict[UUID, RetentionPolicyVersion], state["policies"]))
        self.legal_holds = MemoryLegalHolds(cast(dict[UUID, LegalHold], state["holds"]), state)
        self.erasure_requests = MemoryErasureRequests(
            cast(dict[UUID, ErasureRequest], state["erasure_requests"])
        )
        self.erasure_targets = MemoryErasureTargets(
            cast(
                dict[tuple[ErasureTargetType, UUID], ErasureTargetSnapshot],
                state["erasure_targets"],
            )
        )
        self.outbox = MemoryOutbox(cast(list[DomainEvent], state["outbox"]))
        self.idempotency = MemoryIdempotency(
            cast(dict[tuple[UUID, str, str], IdempotencyRecord], state["idempotency"])
        )
        self._snapshot: dict[str, object] | None = None
        self._committed = False

    async def __aenter__(self) -> Self:
        self._snapshot = deepcopy(self.state)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_value, traceback
        if exc_type is not None or not self._committed:
            assert self._snapshot is not None
            self.state.clear()
            self.state.update(self._snapshot)

    async def commit(self) -> None:
        self._committed = True

    async def lock_workspace(self, *, workspace_id: UUID) -> None:
        assert workspace_id == self.state["workspace_id"]
        self.state["lock_count"] = cast(int, self.state["lock_count"]) + 1

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None:
        assert workspace_id == self.state["workspace_id"]
        assert isinstance(subject_id, UUID)


def _state(workspace_id: UUID) -> dict[str, object]:
    return {
        "workspace_id": workspace_id,
        "policies": {},
        "holds": {},
        "erasure_requests": {},
        "erasure_targets": {},
        "hold_blocks": False,
        "outbox": [],
        "idempotency": {},
        "lock_count": 0,
    }


def _service(state: dict[str, object]) -> RetentionGovernanceService:
    factory = cast(Callable[[], RetentionUnitOfWork], lambda: MemoryRetentionUnitOfWork(state))
    return RetentionGovernanceService(
        factory, AuthorizationService(decision_writer=MemoryDecisionWriter())
    )


def _subject(
    workspace_id: UUID,
    *,
    actions: frozenset[Action],
    assurance: AuthenticationAssurance = AuthenticationAssurance.HARDWARE_WEBAUTHN,
    now: datetime,
) -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset({"security-administrators"}),
        job_function="SECURITY_ADMINISTRATOR",
        clearance=Classification.RESTRICTED,
        allowed_actions=actions,
        authentication_time=now - timedelta(seconds=5),
        authentication_assurance=assurance,
    )


def _rules(days: int = 17) -> RetentionRules:
    return RetentionRules(
        completed_operation_days=days,
        chat_content_days=29,
        audit_online_months=8,
        immutable_archive_years=4,
    )


async def _propose(
    service: RetentionGovernanceService,
    *,
    workspace_id: UUID,
    subject: SubjectAttributes,
    now: datetime,
    suffix: str,
    days: int = 30,
) -> RetentionPolicyVersion:
    return await service.propose_policy(
        workspace_id=workspace_id,
        rules=_rules(days),
        reason="Approved operating retention",
        subject=subject,
        environment=EnvironmentAttributes(requested_at=now),
        request_id=f"propose-{suffix}",
        idempotency_key=f"retention-propose-{suffix}",
        request_hash=suffix * 64,
    )


async def _activate_policy(
    service: RetentionGovernanceService,
    *,
    workspace_id: UUID,
    now: datetime,
) -> RetentionPolicyVersion:
    maker = _subject(workspace_id, actions=frozenset({Action.RETENTION_MANAGE}), now=now)
    checker = _subject(workspace_id, actions=frozenset({Action.RETENTION_MANAGE}), now=now)
    policy = await _propose(service, workspace_id=workspace_id, subject=maker, now=now, suffix="p")
    return await service.decide_policy(
        workspace_id=workspace_id,
        policy_id=policy.policy_id,
        governance_decision=GovernanceDecision.APPROVED,
        reason="Independent policy approval",
        expected_version=1,
        subject=checker,
        environment=EnvironmentAttributes(requested_at=now),
        request_id="activate-erasure-policy",
        idempotency_key="retention-activate-erasure-policy",
        request_hash="q" * 64,
    )


@pytest.mark.asyncio
async def test_policy_maker_checker_supersedes_previous_active_version() -> None:
    workspace_id = uuid4()
    now = datetime.now(UTC)
    state = _state(workspace_id)
    service = _service(state)
    maker = _subject(workspace_id, actions=frozenset({Action.RETENTION_MANAGE}), now=now)
    checker = _subject(workspace_id, actions=frozenset({Action.RETENTION_MANAGE}), now=now)

    first = await _propose(service, workspace_id=workspace_id, subject=maker, now=now, suffix="a")
    first = await service.decide_policy(
        workspace_id=workspace_id,
        policy_id=first.policy_id,
        governance_decision=GovernanceDecision.APPROVED,
        reason="Independent review",
        expected_version=1,
        subject=checker,
        environment=EnvironmentAttributes(requested_at=now),
        request_id="approve-first",
        idempotency_key="retention-approve-first",
        request_hash="b" * 64,
    )
    second = await _propose(
        service, workspace_id=workspace_id, subject=maker, now=now, suffix="c", days=31
    )
    second = await service.decide_policy(
        workspace_id=workspace_id,
        policy_id=second.policy_id,
        governance_decision=GovernanceDecision.APPROVED,
        reason="Independent review",
        expected_version=1,
        subject=checker,
        environment=EnvironmentAttributes(requested_at=now),
        request_id="approve-second",
        idempotency_key="retention-approve-second",
        request_hash="d" * 64,
    )

    policies = cast(dict[UUID, RetentionPolicyVersion], state["policies"])
    assert policies[first.policy_id].state is RetentionPolicyState.SUPERSEDED
    assert policies[first.policy_id].superseded_by == checker.subject_id
    assert policies[first.policy_id].supersede_reason == "Independent review"
    assert second.state is RetentionPolicyState.ACTIVE
    assert second.policy_number == 2
    assert all("automation" not in key for key in second.rules.document())
    event_types = [event.event_type for event in cast(list[DomainEvent], state["outbox"])]
    assert event_types[-2:] == [
        "governance.retention_policy.approved.v1",
        "governance.retention_policy.superseded.v1",
    ]


@pytest.mark.asyncio
async def test_policy_self_approval_rolls_back_without_state_change() -> None:
    workspace_id = uuid4()
    now = datetime.now(UTC)
    state = _state(workspace_id)
    service = _service(state)
    maker = _subject(workspace_id, actions=frozenset({Action.RETENTION_MANAGE}), now=now)
    policy = await _propose(service, workspace_id=workspace_id, subject=maker, now=now, suffix="e")

    with pytest.raises(ValidationError):
        await service.decide_policy(
            workspace_id=workspace_id,
            policy_id=policy.policy_id,
            governance_decision=GovernanceDecision.APPROVED,
            reason="Self approval",
            expected_version=1,
            subject=maker,
            environment=EnvironmentAttributes(requested_at=now),
            request_id="self-approve",
            idempotency_key="retention-self-approve",
            request_hash="f" * 64,
        )

    stored = cast(dict[UUID, RetentionPolicyVersion], state["policies"])[policy.policy_id]
    assert stored.state is RetentionPolicyState.DRAFT
    assert stored.version == 1


@pytest.mark.asyncio
async def test_legal_hold_release_requires_independent_checker_and_keeps_history() -> None:
    workspace_id = uuid4()
    now = datetime.now(UTC)
    state = _state(workspace_id)
    service = _service(state)
    maker = _subject(
        workspace_id,
        actions=frozenset({Action.LEGAL_HOLD_PLACE, Action.LEGAL_HOLD_RELEASE}),
        now=now,
    )
    checker = _subject(workspace_id, actions=frozenset({Action.LEGAL_HOLD_RELEASE}), now=now)
    environment = EnvironmentAttributes(requested_at=now)
    hold = await service.place_legal_hold(
        workspace_id=workspace_id,
        data_class=RetentionDataClass.AUDIT_EVIDENCE,
        scope=LegalHoldScope.WORKSPACE,
        scope_id=None,
        reason="Regulatory investigation",
        subject=maker,
        environment=environment,
        request_id="hold-place",
        idempotency_key="retention-hold-place",
        request_hash="1" * 64,
    )
    hold = await service.request_legal_hold_release(
        workspace_id=workspace_id,
        hold_id=hold.hold_id,
        reason="Investigation closed",
        expected_version=1,
        subject=maker,
        environment=environment,
        request_id="hold-release-request",
        idempotency_key="retention-hold-release-request",
        request_hash="2" * 64,
    )

    with pytest.raises(ValidationError):
        await service.decide_legal_hold_release(
            workspace_id=workspace_id,
            hold_id=hold.hold_id,
            governance_decision=GovernanceDecision.APPROVED,
            reason="Self approval",
            expected_version=2,
            subject=maker,
            environment=environment,
            request_id="hold-self-approve",
            idempotency_key="retention-hold-self-approve",
            request_hash="3" * 64,
        )
    hold = await service.decide_legal_hold_release(
        workspace_id=workspace_id,
        hold_id=hold.hold_id,
        governance_decision=GovernanceDecision.APPROVED,
        reason="Independent release review",
        expected_version=2,
        subject=checker,
        environment=environment,
        request_id="hold-approve",
        idempotency_key="retention-hold-approve",
        request_hash="4" * 64,
    )

    assert hold.state is LegalHoldState.RELEASED
    assert len(hold.actions) == 3
    assert len({action.payload_hash for action in hold.actions}) == 3


@pytest.mark.asyncio
async def test_weak_authentication_fails_before_retention_state_is_written() -> None:
    workspace_id = uuid4()
    now = datetime.now(UTC)
    state = _state(workspace_id)
    subject = _subject(
        workspace_id,
        actions=frozenset({Action.RETENTION_MANAGE}),
        assurance=AuthenticationAssurance.PASSWORD_REAUTH,
        now=now,
    )

    with pytest.raises(ForbiddenError):
        await _propose(
            _service(state),
            workspace_id=workspace_id,
            subject=subject,
            now=now,
            suffix="9",
        )

    assert state["policies"] == {}
    assert state["outbox"] == []


@pytest.mark.asyncio
async def test_retention_idempotency_key_rejects_a_different_payload_hash() -> None:
    workspace_id = uuid4()
    now = datetime.now(UTC)
    state = _state(workspace_id)
    service = _service(state)
    maker = _subject(workspace_id, actions=frozenset({Action.RETENTION_MANAGE}), now=now)
    await _propose(service, workspace_id=workspace_id, subject=maker, now=now, suffix="8")

    with pytest.raises(ConflictError):
        await service.propose_policy(
            workspace_id=workspace_id,
            rules=_rules(31),
            reason="Changed command",
            subject=maker,
            environment=EnvironmentAttributes(requested_at=now),
            request_id="conflicting-replay",
            idempotency_key="retention-propose-8",
            request_hash="7" * 64,
        )

    assert len(cast(dict[UUID, RetentionPolicyVersion], state["policies"])) == 1


@pytest.mark.asyncio
async def test_idempotent_proposal_replay_never_returns_a_later_mutated_snapshot() -> None:
    workspace_id = uuid4()
    now = datetime.now(UTC)
    state = _state(workspace_id)
    service = _service(state)
    maker = _subject(workspace_id, actions=frozenset({Action.RETENTION_MANAGE}), now=now)
    checker = _subject(workspace_id, actions=frozenset({Action.RETENTION_MANAGE}), now=now)
    policy = await _propose(service, workspace_id=workspace_id, subject=maker, now=now, suffix="6")
    await service.decide_policy(
        workspace_id=workspace_id,
        policy_id=policy.policy_id,
        governance_decision=GovernanceDecision.APPROVED,
        reason="Independent review",
        expected_version=1,
        subject=checker,
        environment=EnvironmentAttributes(requested_at=now),
        request_id="approve-before-replay",
        idempotency_key="retention-approve-before-replay",
        request_hash="5" * 64,
    )

    with pytest.raises(ConflictError):
        await _propose(
            service,
            workspace_id=workspace_id,
            subject=maker,
            now=now,
            suffix="6",
        )


@pytest.mark.asyncio
async def test_erasure_request_binds_canonical_target_and_active_policy() -> None:
    workspace_id = uuid4()
    now = datetime.now(UTC)
    state = _state(workspace_id)
    service = _service(state)
    policy = await _activate_policy(service, workspace_id=workspace_id, now=now)
    target_id = uuid4()
    target = ErasureTargetSnapshot(
        target_type=ErasureTargetType.UPLOAD_OBJECT,
        target_id=target_id,
        version=7,
        owner_id=uuid4(),
        classification=Classification.CONFIDENTIAL,
    )
    cast(
        dict[tuple[ErasureTargetType, UUID], ErasureTargetSnapshot],
        state["erasure_targets"],
    )[(target.target_type, target.target_id)] = target
    maker = _subject(workspace_id, actions=frozenset({Action.ERASURE_REQUEST}), now=now)

    request = await service.request_erasure(
        workspace_id=workspace_id,
        target_type=target.target_type,
        target_id=target.target_id,
        reason="Approved destruction request",
        review_ttl_seconds=3600,
        subject=maker,
        environment=EnvironmentAttributes(requested_at=now),
        request_id="request-erasure",
        idempotency_key="retention-request-erasure",
        request_hash="r" * 64,
    )

    assert request.target_version == 7
    assert request.target_owner_id == target.owner_id
    assert request.classification is Classification.CONFIDENTIAL
    assert request.retention_policy_id == policy.policy_id
    assert request.retention_policy_hash == policy.payload_hash
    assert request.execution_state == "DISABLED_NOT_READY"
    assert request.state is ErasureRequestState.PENDING


@pytest.mark.asyncio
async def test_erasure_approval_is_blocked_by_hold_then_succeeds_for_checker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = uuid4()
    now = datetime.now(UTC)
    state = _state(workspace_id)
    service = _service(state)
    await _activate_policy(service, workspace_id=workspace_id, now=now)
    target_id = uuid4()
    target = ErasureTargetSnapshot(
        target_type=ErasureTargetType.CHAT_SESSION,
        target_id=target_id,
        version=2,
        owner_id=uuid4(),
        classification=Classification.RESTRICTED,
    )
    cast(
        dict[tuple[ErasureTargetType, UUID], ErasureTargetSnapshot],
        state["erasure_targets"],
    )[(target.target_type, target.target_id)] = target
    maker = _subject(workspace_id, actions=frozenset({Action.ERASURE_REQUEST}), now=now)
    checker = _subject(workspace_id, actions=frozenset({Action.ERASURE_APPROVE}), now=now)
    request = await service.request_erasure(
        workspace_id=workspace_id,
        target_type=target.target_type,
        target_id=target.target_id,
        reason="Delete expired chat",
        review_ttl_seconds=3600,
        subject=maker,
        environment=EnvironmentAttributes(requested_at=now),
        request_id="request-chat-erasure",
        idempotency_key="retention-request-chat-erasure",
        request_hash="s" * 64,
    )
    state["hold_blocks"] = True
    with pytest.raises(ConflictError):
        await service.decide_erasure(
            workspace_id=workspace_id,
            erasure_request_id=request.erasure_request_id,
            governance_decision=GovernanceDecision.APPROVED,
            reason="Independent approval",
            expected_version=1,
            subject=checker,
            environment=EnvironmentAttributes(requested_at=now),
            request_id="approve-held-erasure",
            idempotency_key="retention-approve-held-erasure",
            request_hash="t" * 64,
        )
    stored = cast(dict[UUID, ErasureRequest], state["erasure_requests"])[request.erasure_request_id]
    assert stored.state is ErasureRequestState.PENDING

    state["hold_blocks"] = False
    persisted_decision_time = now + timedelta(seconds=1)
    monkeypatch.setattr(
        "datariver.application.services.retention.utc_now", lambda: persisted_decision_time
    )
    approved = await service.decide_erasure(
        workspace_id=workspace_id,
        erasure_request_id=request.erasure_request_id,
        governance_decision=GovernanceDecision.APPROVED,
        reason="Independent approval",
        expected_version=1,
        subject=checker,
        environment=EnvironmentAttributes(requested_at=now),
        request_id="approve-erasure",
        idempotency_key="retention-approve-erasure",
        request_hash="u" * 64,
    )
    assert approved.state is ErasureRequestState.APPROVED
    assert approved.execution_state == "DISABLED_NOT_READY"
    assert approved.decided_at == persisted_decision_time
    assert approved.decided_at > now


@pytest.mark.asyncio
async def test_erasure_request_rejects_password_and_service_accounts() -> None:
    workspace_id = uuid4()
    now = datetime.now(UTC)
    state = _state(workspace_id)
    service = _service(state)
    await _activate_policy(service, workspace_id=workspace_id, now=now)
    target = ErasureTargetSnapshot(
        target_type=ErasureTargetType.SUBJECT_DATA,
        target_id=uuid4(),
        version=1,
        owner_id=uuid4(),
        classification=Classification.RESTRICTED,
    )
    cast(
        dict[tuple[ErasureTargetType, UUID], ErasureTargetSnapshot],
        state["erasure_targets"],
    )[(target.target_type, target.target_id)] = target
    weak = _subject(
        workspace_id,
        actions=frozenset({Action.ERASURE_REQUEST}),
        assurance=AuthenticationAssurance.PASSWORD_REAUTH,
        now=now,
    )
    service_account = replace(
        weak,
        subject_id=uuid4(),
        groups=frozenset({"security-administrators", "service-accounts"}),
        job_function="SERVICE_ACCOUNT",
        authentication_assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
    )

    for actor in (weak, service_account):
        with pytest.raises(ForbiddenError):
            await service.request_erasure(
                workspace_id=workspace_id,
                target_type=target.target_type,
                target_id=target.target_id,
                reason="Governed subject request",
                review_ttl_seconds=3600,
                subject=actor,
                environment=EnvironmentAttributes(requested_at=now),
                request_id=f"deny-erasure-{actor.subject_id}",
                idempotency_key=f"retention-deny-{actor.subject_id}",
                request_hash="v" * 64,
            )
