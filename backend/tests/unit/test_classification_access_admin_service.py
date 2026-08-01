from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from datariver.application.classification_access import (
    ClassificationAccessCandidate,
    ClassificationAccessPosture,
    ClassificationRuleRecord,
)
from datariver.application.classification_access_admin import (
    ClassificationAccessAdminUnitOfWork,
    ClassificationPolicyPage,
    RestrictedSearchGrantPage,
)
from datariver.application.dto import IdempotencyRecord
from datariver.application.services.authorization import AuthorizationService, NullDecisionWriter
from datariver.application.services.classification_access_admin import (
    ClassificationAccessAdminService,
)
from datariver.domain.authz import (
    Action,
    AuthenticationAssurance,
    Classification,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.classification_access import (
    ChatMode,
    ClassificationAccessPolicy,
    ClassificationAccessPolicyState,
    ClassificationAccessRule,
    PolicyDecision,
    RestrictedSearchGrant,
    RestrictedSearchGrantState,
    RestrictedSearchScope,
    SearchMode,
)
from datariver.domain.common import ConflictError, DomainEvent, ForbiddenError


class _Policies:
    def __init__(self) -> None:
        self.values: dict[UUID, ClassificationAccessPolicy] = {}
        self.saved: list[tuple[UUID, str]] = []
        self.provider_checks = 0
        self.provider_error = False

    async def add(self, policy: ClassificationAccessPolicy) -> None:
        self.values[policy.policy_id] = policy

    async def save(self, policy: ClassificationAccessPolicy) -> None:
        self.values[policy.policy_id] = policy
        self.saved.append((policy.policy_id, policy.state.value))

    async def get(
        self, *, workspace_id: UUID, policy_id: UUID
    ) -> ClassificationAccessPolicy | None:
        value = self.values.get(policy_id)
        return value if value is not None and value.workspace_id == workspace_id else None

    async def get_for_update(
        self, *, workspace_id: UUID, policy_id: UUID
    ) -> ClassificationAccessPolicy | None:
        return await self.get(workspace_id=workspace_id, policy_id=policy_id)

    async def get_active(self, *, workspace_id: UUID) -> ClassificationAccessPolicy | None:
        return next(
            (
                value
                for value in self.values.values()
                if value.workspace_id == workspace_id
                and value.state is ClassificationAccessPolicyState.ACTIVE
            ),
            None,
        )

    async def get_active_for_update(
        self, *, workspace_id: UUID, excluding_policy_id: UUID | None = None
    ) -> ClassificationAccessPolicy | None:
        value = await self.get_active(workspace_id=workspace_id)
        return value if value is not None and value.policy_id != excluding_policy_id else None

    async def list(
        self,
        *,
        workspace_id: UUID,
        state: str | None,
        limit: int,
        cursor: str | None,
    ) -> ClassificationPolicyPage:
        del cursor
        values = tuple(
            value
            for value in self.values.values()
            if value.workspace_id == workspace_id and (state is None or value.state.value == state)
        )
        return ClassificationPolicyPage(items=values[:limit], next_cursor=None)

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

    async def assert_provider_rules_eligible(
        self, *, policy: ClassificationAccessPolicy, now: datetime
    ) -> None:
        del policy, now
        self.provider_checks += 1
        if self.provider_error:
            raise ConflictError("provider ineligible")


class _Grants:
    def __init__(self) -> None:
        self.values: dict[UUID, RestrictedSearchGrant] = {}
        self.saved: list[tuple[UUID, str]] = []

    async def add(self, grant: RestrictedSearchGrant) -> None:
        self.values[grant.grant_id] = grant

    async def save(self, grant: RestrictedSearchGrant) -> None:
        self.values[grant.grant_id] = grant
        self.saved.append((grant.grant_id, grant.state.value))

    async def get(self, *, workspace_id: UUID, grant_id: UUID) -> RestrictedSearchGrant | None:
        value = self.values.get(grant_id)
        return value if value is not None and value.workspace_id == workspace_id else None

    async def get_for_update(
        self, *, workspace_id: UUID, grant_id: UUID
    ) -> RestrictedSearchGrant | None:
        return await self.get(workspace_id=workspace_id, grant_id=grant_id)

    async def list(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID | None,
        state: str | None,
        limit: int,
        cursor: str | None,
    ) -> RestrictedSearchGrantPage:
        del cursor
        values = tuple(
            value
            for value in self.values.values()
            if value.workspace_id == workspace_id
            and (subject_id is None or value.subject_id == subject_id)
            and (state is None or value.state.value == state)
        )
        return RestrictedSearchGrantPage(items=values[:limit], next_cursor=None)


class _Memberships:
    def __init__(self) -> None:
        self.checked: list[frozenset[UUID]] = []
        self.error: ForbiddenError | None = None

    async def assert_eligible_human_administrators(
        self, *, workspace_id: UUID, subject_ids: frozenset[UUID]
    ) -> None:
        del workspace_id
        if self.error is not None:
            raise self.error
        self.checked.append(subject_ids)


class _Snapshots:
    def __init__(self) -> None:
        self.candidate: ClassificationAccessCandidate | None = None
        self.reads = 0

    async def read_candidate(
        self, *, workspace_id: UUID, subject_id: UUID, now: datetime
    ) -> ClassificationAccessCandidate | None:
        del workspace_id, subject_id, now
        self.reads += 1
        return self.candidate


class _Idempotency:
    def __init__(self) -> None:
        self.records: dict[tuple[UUID, str, str], IdempotencyRecord] = {}

    async def get_result(
        self, *, workspace_id: UUID, key: str, operation: str
    ) -> IdempotencyRecord | None:
        return self.records.get((workspace_id, key, operation))

    async def save_result(
        self,
        *,
        workspace_id: UUID,
        key: str,
        operation: str,
        request_hash: str,
        result: dict[str, Any],
    ) -> None:
        self.records[(workspace_id, key, operation)] = IdempotencyRecord(
            request_hash=request_hash, result=result
        )


class _Outbox:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def add_events(self, events: list[DomainEvent]) -> None:
        self.events.extend(events)


class _Uow:
    def __init__(self) -> None:
        self.snapshots = _Snapshots()
        self.policies = _Policies()
        self.grants = _Grants()
        self.memberships = _Memberships()
        self.idempotency = _Idempotency()
        self.outbox = _Outbox()
        self.commits = 0
        self.locks = 0
        self.contexts: list[tuple[UUID, UUID]] = []

    async def __aenter__(self) -> _Uow:
        return self

    async def __aexit__(self, *args: object) -> None:
        del args

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None:
        self.contexts.append((workspace_id, subject_id))

    async def lock_workspace(self, *, workspace_id: UUID) -> None:
        del workspace_id
        self.locks += 1

    async def commit(self) -> None:
        self.commits += 1


def _subject(
    *,
    workspace_id: UUID,
    now: datetime,
    subject_id: UUID | None = None,
    assurance: AuthenticationAssurance = AuthenticationAssurance.HARDWARE_WEBAUTHN,
) -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=subject_id or uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset({"security-administrators"}),
        job_function="SECURITY_ADMINISTRATOR",
        clearance=Classification.RESTRICTED,
        allowed_actions=frozenset({Action.ADMIN_MANAGE}),
        authentication_time=now,
        authentication_assurance=assurance,
    )


def _rules() -> tuple[ClassificationAccessRule, ...]:
    return (
        ClassificationAccessRule(
            Classification.PUBLIC,
            SearchMode.ABAC,
            ChatMode.INTERNAL_APPROVED_ONLY,
            uuid4(),
        ),
        ClassificationAccessRule(
            Classification.INTERNAL,
            SearchMode.ABAC,
            ChatMode.INTERNAL_APPROVED_ONLY,
            uuid4(),
        ),
        ClassificationAccessRule(
            Classification.CONFIDENTIAL,
            SearchMode.DENY,
            ChatMode.INTERNAL_APPROVED_ONLY,
            uuid4(),
        ),
        ClassificationAccessRule(
            Classification.RESTRICTED,
            SearchMode.EXPLICIT_GRANT_ONLY,
            ChatMode.DENY,
        ),
    )


def _service(uow: _Uow) -> ClassificationAccessAdminService:
    return ClassificationAccessAdminService(
        lambda: cast(ClassificationAccessAdminUnitOfWork, uow),
        AuthorizationService(decision_writer=NullDecisionWriter()),
    )


async def _propose(
    service: ClassificationAccessAdminService,
    *,
    workspace_id: UUID,
    subject: SubjectAttributes,
    now: datetime,
) -> ClassificationAccessPolicy:
    return await service.propose_policy(
        workspace_id=workspace_id,
        required_jurisdiction="jurisdiction-test",
        restricted_search_grant_maximum_days=17,
        rules=_rules(),
        reason="Govern classification access",
        subject=subject,
        environment=EnvironmentAttributes(requested_at=now),
        request_id="request-propose",
        idempotency_key="key-propose",
        request_hash="a" * 64,
    )


@pytest.mark.asyncio
async def test_policy_proposal_and_activation_are_atomic_governed_commands() -> None:
    now = datetime.now(UTC)
    workspace_id = uuid4()
    uow = _Uow()
    service = _service(uow)
    maker = _subject(workspace_id=workspace_id, now=now)
    policy = await _propose(service, workspace_id=workspace_id, subject=maker, now=now)
    assert len(policy.rules) == 4
    assert uow.commits == 1
    assert uow.locks == 1
    assert uow.memberships.checked[-1] == frozenset({maker.subject_id})

    older = ClassificationAccessPolicy.propose(
        workspace_id=workspace_id,
        policy_number=1,
        required_jurisdiction="jurisdiction-old",
        restricted_search_grant_maximum_days=9,
        rules=_rules(),
        requester_id=uuid4(),
        reason="Older policy",
        policy_decision_id=uuid4(),
    )
    older.decide(
        decision=PolicyDecision.APPROVED,
        actor_id=uuid4(),
        reason="Older approval",
        policy_decision_id=uuid4(),
        expected_version=1,
        now=now,
    )
    uow.policies.values[older.policy_id] = older
    checker = _subject(workspace_id=workspace_id, now=now, subject_id=uuid4())
    approved = await service.approve_policy(
        workspace_id=workspace_id,
        policy_id=policy.policy_id,
        reason="Independent activation",
        expected_version=1,
        subject=checker,
        environment=EnvironmentAttributes(requested_at=now + timedelta(seconds=1)),
        request_id="request-approve",
        idempotency_key="key-approve",
        request_hash="b" * 64,
    )
    assert older.state is ClassificationAccessPolicyState.SUPERSEDED
    assert approved.state is ClassificationAccessPolicyState.ACTIVE
    assert uow.policies.saved[-2:] == [
        (older.policy_id, "SUPERSEDED"),
        (approved.policy_id, "ACTIVE"),
    ]
    assert uow.policies.provider_checks == 1
    assert uow.commits == 2


@pytest.mark.asyncio
async def test_provider_failure_and_nonhardware_actor_fail_before_commit() -> None:
    now = datetime.now(UTC)
    workspace_id = uuid4()
    uow = _Uow()
    service = _service(uow)
    maker = _subject(workspace_id=workspace_id, now=now)
    policy = await _propose(service, workspace_id=workspace_id, subject=maker, now=now)
    uow.policies.provider_error = True
    checker = _subject(workspace_id=workspace_id, now=now)
    with pytest.raises(ConflictError, match="provider"):
        await service.approve_policy(
            workspace_id=workspace_id,
            policy_id=policy.policy_id,
            reason="Unsafe activation",
            expected_version=1,
            subject=checker,
            environment=EnvironmentAttributes(requested_at=now),
            request_id="request-provider-deny",
            idempotency_key="key-provider-deny",
            request_hash="c" * 64,
        )
    assert uow.commits == 1

    password_actor = _subject(
        workspace_id=workspace_id,
        now=now,
        assurance=AuthenticationAssurance.PASSWORD,
    )
    before = len(uow.memberships.checked)
    with pytest.raises(ForbiddenError):
        await service.current_policy(
            workspace_id=workspace_id,
            subject=password_actor,
            environment=EnvironmentAttributes(requested_at=now),
            request_id="request-password",
        )
    assert len(uow.memberships.checked) == before


@pytest.mark.asyncio
async def test_policy_summary_allows_ordinary_admin_read_and_returns_only_effective_modes() -> None:
    now = datetime.now(UTC)
    workspace_id = uuid4()
    uow = _Uow()
    uow.snapshots.candidate = ClassificationAccessCandidate(
        policy_id=uuid4(),
        policy_hash="a" * 64,
        policy_version=2,
        required_jurisdiction="governed-zone",
        authorization_generation=3,
        rules=tuple(
                ClassificationRuleRecord(
                    classification=rule.classification,
                    search_mode=rule.search_mode,
                    chat_mode=ChatMode.DENY,
                    provider_profile_version_id=None,
            )
            for rule in _rules()
        ),
        grants=(),
        provider_profiles=(),
    )
    subject = _subject(
        workspace_id=workspace_id,
        now=now,
        assurance=AuthenticationAssurance.PASSWORD,
    )

    summary = await _service(uow).current_policy_summary(
        workspace_id=workspace_id,
        subject=subject,
        environment=EnvironmentAttributes(requested_at=now),
        request_id="request-summary",
    )

    assert summary.state is ClassificationAccessPosture.GOVERNED
    assert len(summary.rules) == 4
    assert {rule.classification for rule in summary.rules} == set(Classification)
    assert uow.contexts == [(workspace_id, subject.subject_id)]
    assert uow.memberships.checked == [frozenset({subject.subject_id})]
    assert uow.snapshots.reads == 1


@pytest.mark.asyncio
async def test_policy_summary_fails_before_read_after_deny_or_membership_revoke() -> None:
    now = datetime.now(UTC)
    workspace_id = uuid4()
    eligible = _subject(workspace_id=workspace_id, now=now)
    denied_subjects = (
        replace(eligible, groups=frozenset()),
        replace(eligible, allowed_actions=frozenset()),
        replace(eligible, denied_actions=frozenset({Action.ADMIN_MANAGE})),
        replace(eligible, clearance=Classification.CONFIDENTIAL),
        replace(
            eligible,
            groups=eligible.groups | frozenset({"service-accounts"}),
            job_function="SERVICE_ACCOUNT",
        ),
    )
    for denied in denied_subjects:
        denied_uow = _Uow()
        with pytest.raises(ForbiddenError):
            await _service(denied_uow).current_policy_summary(
                workspace_id=workspace_id,
                subject=denied,
                environment=EnvironmentAttributes(requested_at=now),
                request_id="request-summary-denied",
            )
        assert denied_uow.memberships.checked == []
        assert denied_uow.snapshots.reads == 0

    revoked_uow = _Uow()
    revoked_uow.memberships.error = ForbiddenError("Administrator membership was revoked.")
    revoked = _subject(workspace_id=workspace_id, now=now)
    with pytest.raises(ForbiddenError, match="revoked"):
        await _service(revoked_uow).current_policy_summary(
            workspace_id=workspace_id,
            subject=revoked,
            environment=EnvironmentAttributes(requested_at=now),
            request_id="request-summary-revoked",
        )
    assert revoked_uow.snapshots.reads == 0


@pytest.mark.asyncio
async def test_grant_binds_current_policy_approves_and_revokes_without_policy_fallback() -> None:
    now = datetime.now(UTC)
    workspace_id = uuid4()
    uow = _Uow()
    service = _service(uow)
    maker = _subject(workspace_id=workspace_id, now=now)
    policy = await _propose(service, workspace_id=workspace_id, subject=maker, now=now)
    policy.decide(
        decision=PolicyDecision.APPROVED,
        actor_id=uuid4(),
        reason="Activation",
        policy_decision_id=uuid4(),
        expected_version=1,
        now=now,
    )
    target_subject_id = uuid4()
    grant = await service.propose_grant(
        workspace_id=workspace_id,
        target_subject_id=target_subject_id,
        scope=RestrictedSearchScope.DOMAIN,
        scope_id=uuid4(),
        purpose="Incident investigation",
        valid_from=now,
        expires_at=now + timedelta(days=17),
        reason="Temporary exact scope",
        subject=maker,
        environment=EnvironmentAttributes(requested_at=now),
        request_id="request-grant",
        idempotency_key="key-grant",
        request_hash="d" * 64,
    )
    assert grant.classification_policy_id == policy.policy_id
    assert grant.classification_policy_hash == policy.payload_hash
    assert grant.state is RestrictedSearchGrantState.PENDING

    checker = _subject(workspace_id=workspace_id, now=now)
    grant = await service.approve_grant(
        workspace_id=workspace_id,
        grant_id=grant.grant_id,
        reason="Independent grant approval",
        expected_version=1,
        subject=checker,
        environment=EnvironmentAttributes(requested_at=now),
        request_id="request-grant-approve",
        idempotency_key="key-grant-approve",
        request_hash="e" * 64,
    )
    assert grant.state is RestrictedSearchGrantState.ACTIVE

    uow.policies.values.clear()
    grant = await service.revoke_grant(
        workspace_id=workspace_id,
        grant_id=grant.grant_id,
        reason="Immediate incident revocation",
        expected_version=2,
        subject=checker,
        environment=EnvironmentAttributes(requested_at=now + timedelta(seconds=1)),
        request_id="request-grant-revoke",
        idempotency_key="key-grant-revoke",
        request_hash="f" * 64,
    )
    assert grant.state is RestrictedSearchGrantState.REVOKED
    assert uow.commits == 4
