from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from datariver.domain.authz import Classification
from datariver.domain.classification_access import (
    ChatMode,
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
from datariver.domain.common import ConflictError, ValidationError


def _rules() -> tuple[ClassificationAccessRule, ...]:
    return (
        ClassificationAccessRule(
            classification=Classification.PUBLIC,
            search_mode=SearchMode.ABAC,
            chat_mode=ChatMode.APPROVED_PROVIDER_ONLY,
            provider_profile_version_id=uuid4(),
        ),
        ClassificationAccessRule(
            classification=Classification.INTERNAL,
            search_mode=SearchMode.ABAC,
            chat_mode=ChatMode.INTERNAL_APPROVED_ONLY,
            provider_profile_version_id=uuid4(),
        ),
        ClassificationAccessRule(
            classification=Classification.CONFIDENTIAL,
            search_mode=SearchMode.DENY,
            chat_mode=ChatMode.INTERNAL_APPROVED_ONLY,
            provider_profile_version_id=uuid4(),
        ),
        ClassificationAccessRule(
            classification=Classification.RESTRICTED,
            search_mode=SearchMode.EXPLICIT_GRANT_ONLY,
            chat_mode=ChatMode.DENY,
        ),
    )


def _policy() -> ClassificationAccessPolicy:
    return ClassificationAccessPolicy.propose(
        workspace_id=uuid4(),
        policy_number=4,
        rules=_rules(),
        requester_id=uuid4(),
        reason="Narrow classification access",
        policy_decision_id=uuid4(),
    )


def _grant(
    *,
    now: datetime,
    valid_from: datetime | None = None,
    expires_at: datetime | None = None,
) -> RestrictedSearchGrant:
    start = valid_from or now
    return RestrictedSearchGrant.propose(
        workspace_id=uuid4(),
        subject_id=uuid4(),
        scope=RestrictedSearchScope.RESOURCE,
        scope_id=uuid4(),
        purpose="Investigate a governed schema incident",
        valid_from=start,
        expires_at=expires_at or start + timedelta(days=5),
        requester_id=uuid4(),
        reason="Temporary investigation access",
        policy_decision_id=uuid4(),
        now=now,
    )


def _approve_policy(policy: ClassificationAccessPolicy, *, now: datetime) -> UUID:
    checker_id = uuid4()
    policy.decide(
        decision=PolicyDecision.APPROVED,
        actor_id=checker_id,
        reason="Independent approval",
        policy_decision_id=uuid4(),
        expected_version=1,
        now=now,
    )
    return checker_id


def _approve_grant(grant: RestrictedSearchGrant, *, now: datetime) -> UUID:
    checker_id = uuid4()
    while checker_id in {grant.requester_id, grant.subject_id}:
        checker_id = uuid4()
    grant.decide(
        decision=GrantDecision.APPROVED,
        actor_id=checker_id,
        reason="High-risk access approved",
        policy_decision_id=uuid4(),
        expected_version=1,
        now=now,
    )
    return checker_id


@pytest.mark.parametrize(
    ("classification", "search_mode", "chat_mode", "profile_id", "message"),
    [
        (
            Classification.RESTRICTED,
            SearchMode.ABAC,
            ChatMode.DENY,
            None,
            "RESTRICTED Search",
        ),
        (
            Classification.RESTRICTED,
            SearchMode.DENY,
            ChatMode.INTERNAL_APPROVED_ONLY,
            uuid4(),
            "RESTRICTED Chat",
        ),
        (
            Classification.CONFIDENTIAL,
            SearchMode.ABAC,
            ChatMode.APPROVED_PROVIDER_ONLY,
            uuid4(),
            "CONFIDENTIAL Chat",
        ),
        (
            Classification.INTERNAL,
            SearchMode.EXPLICIT_GRANT_ONLY,
            ChatMode.DENY,
            None,
            "only for RESTRICTED",
        ),
    ],
)
def test_rule_security_floor_rejects_widening_modes(
    classification: Classification,
    search_mode: SearchMode,
    chat_mode: ChatMode,
    profile_id: UUID | None,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        ClassificationAccessRule(
            classification=classification,
            search_mode=search_mode,
            chat_mode=chat_mode,
            provider_profile_version_id=profile_id,
        )


def test_chat_provider_binding_is_exact_and_mode_dependent() -> None:
    with pytest.raises(ValidationError, match="requires a provider-profile"):
        ClassificationAccessRule(
            classification=Classification.CONFIDENTIAL,
            search_mode=SearchMode.DENY,
            chat_mode=ChatMode.INTERNAL_APPROVED_ONLY,
        )
    with pytest.raises(ValidationError, match="denied Chat"):
        ClassificationAccessRule(
            classification=Classification.PUBLIC,
            search_mode=SearchMode.DENY,
            chat_mode=ChatMode.DENY,
            provider_profile_version_id=uuid4(),
        )


def test_policy_requires_exactly_one_typed_rule_per_classification() -> None:
    rules = _rules()
    with pytest.raises(ValidationError, match="exactly four"):
        ClassificationAccessPolicy.propose(
            workspace_id=uuid4(),
            policy_number=1,
            rules=rules[:-1],
            requester_id=uuid4(),
            reason="Incomplete",
            policy_decision_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="one rule per classification"):
        ClassificationAccessPolicy.propose(
            workspace_id=uuid4(),
            policy_number=1,
            rules=(rules[0], rules[1], rules[2], rules[2]),
            requester_id=uuid4(),
            reason="Duplicate",
            policy_decision_id=uuid4(),
        )


def test_policy_payload_is_canonical_and_uuid7_evented() -> None:
    rules = _rules()
    common = {
        "workspace_id": uuid4(),
        "policy_number": 3,
        "requester_id": uuid4(),
        "reason": "Canonical proposal",
        "policy_decision_id": uuid4(),
    }
    first = ClassificationAccessPolicy.propose(rules=rules, **common)
    second = ClassificationAccessPolicy.propose(rules=tuple(reversed(rules)), **common)
    assert first.payload_hash == second.payload_hash
    assert first.policy_id.version == 7
    assert first.state is ClassificationAccessPolicyState.PROPOSED
    assert first.version == 1
    assert first.events[0].event_type == "authz.classification_access_policy.proposed.v1"
    assert first.rule_for(Classification.RESTRICTED).chat_mode is ChatMode.DENY


def test_policy_decision_requires_independent_checker_version_and_intact_hash() -> None:
    now = datetime.now(UTC)
    maker_policy = _policy()
    with pytest.raises(ValidationError, match="maker"):
        maker_policy.decide(
            decision=PolicyDecision.APPROVED,
            actor_id=maker_policy.requester_id,
            reason="Self approval",
            policy_decision_id=uuid4(),
            expected_version=1,
            now=now,
        )

    stale = _policy()
    with pytest.raises(ConflictError, match="modified"):
        stale.decide(
            decision=PolicyDecision.APPROVED,
            actor_id=uuid4(),
            reason="Stale",
            policy_decision_id=uuid4(),
            expected_version=2,
            now=now,
        )

    tampered = _policy()
    public = tampered.rule_for(Classification.PUBLIC)
    tampered.rules = (
        ClassificationAccessRule(
            classification=Classification.PUBLIC,
            search_mode=SearchMode.DENY,
            chat_mode=public.chat_mode,
            provider_profile_version_id=public.provider_profile_version_id,
        ),
        *tampered.rules[1:],
    )
    with pytest.raises(ConflictError, match="integrity"):
        tampered.decide(
            decision=PolicyDecision.APPROVED,
            actor_id=uuid4(),
            reason="Tampered",
            policy_decision_id=uuid4(),
            expected_version=1,
            now=now,
        )


def test_policy_active_rejected_and_superseded_states_are_terminal() -> None:
    now = datetime.now(UTC)
    active = _policy()
    _approve_policy(active, now=now)
    assert active.state is ClassificationAccessPolicyState.ACTIVE
    assert active.version == 2
    active.supersede(
        actor_id=uuid4(),
        reason="New independently approved policy activated",
        policy_decision_id=uuid4(),
        expected_version=2,
        now=now + timedelta(seconds=1),
    )
    assert active.state is ClassificationAccessPolicyState.SUPERSEDED
    assert active.version == 3
    assert active.events[-1].event_type.endswith("superseded.v1")
    with pytest.raises(ConflictError, match="Only an active"):
        active.supersede(
            actor_id=uuid4(),
            reason="Again",
            policy_decision_id=uuid4(),
            expected_version=3,
            now=now + timedelta(seconds=2),
        )

    rejected = _policy()
    rejected.decide(
        decision=PolicyDecision.REJECTED,
        actor_id=uuid4(),
        reason="Unsafe profile selection",
        policy_decision_id=uuid4(),
        expected_version=1,
        now=now,
    )
    assert rejected.state is ClassificationAccessPolicyState.REJECTED
    with pytest.raises(ConflictError, match="Only an active"):
        rejected.supersede(
            actor_id=uuid4(),
            reason="Invalid",
            policy_decision_id=uuid4(),
            expected_version=2,
            now=now,
        )


def test_grant_scope_payload_and_lifetime_are_bounded() -> None:
    now = datetime.now(UTC)
    grant = _grant(now=now, expires_at=now + timedelta(days=90))
    assert grant.grant_id.version == 7
    assert grant.scope is RestrictedSearchScope.RESOURCE
    assert grant.state is RestrictedSearchGrantState.PENDING
    assert grant.events[0].payload["scope_id"] == str(grant.scope_id)

    with pytest.raises(ValidationError, match="90 days"):
        _grant(now=now, expires_at=now + timedelta(days=90, microseconds=1))
    with pytest.raises(ValidationError, match="backdated"):
        _grant(now=now, valid_from=now - timedelta(microseconds=1))
    with pytest.raises(ValidationError, match="include a timezone"):
        _grant(now=now.replace(tzinfo=None))


def test_grant_approval_requires_independent_checker_and_intact_payload() -> None:
    now = datetime.now(UTC)
    grant = _grant(now=now)
    for actor_id in (grant.requester_id, grant.subject_id):
        with pytest.raises(ValidationError):
            grant.decide(
                decision=GrantDecision.APPROVED,
                actor_id=actor_id,
                reason="Invalid self approval",
                policy_decision_id=uuid4(),
                expected_version=1,
                now=now,
            )

    grant.purpose = "Tampered purpose"
    with pytest.raises(ConflictError, match="integrity"):
        grant.decide(
            decision=GrantDecision.APPROVED,
            actor_id=uuid4(),
            reason="Approval",
            policy_decision_id=uuid4(),
            expected_version=1,
            now=now,
        )


def test_grant_active_at_uses_closed_open_validity_boundaries() -> None:
    now = datetime.now(UTC)
    start = now + timedelta(hours=1)
    expires = start + timedelta(days=1)
    grant = _grant(now=now, valid_from=start, expires_at=expires)
    _approve_grant(grant, now=now + timedelta(minutes=1))
    assert not grant.is_active_at(start - timedelta(microseconds=1))
    assert grant.is_active_at(start)
    assert grant.is_active_at(expires - timedelta(microseconds=1))
    assert not grant.is_active_at(expires)


def test_expired_grant_cannot_be_approved_but_can_be_rejected() -> None:
    now = datetime.now(UTC)
    expires = now + timedelta(seconds=1)
    expired = _grant(now=now, expires_at=expires)
    with pytest.raises(ConflictError, match="expired"):
        expired.decide(
            decision=GrantDecision.APPROVED,
            actor_id=uuid4(),
            reason="Too late",
            policy_decision_id=uuid4(),
            expected_version=1,
            now=expires,
        )

    rejected = _grant(now=now, expires_at=expires)
    rejected.decide(
        decision=GrantDecision.REJECTED,
        actor_id=uuid4(),
        reason="Expired request closed",
        policy_decision_id=uuid4(),
        expected_version=1,
        now=expires,
    )
    assert rejected.state is RestrictedSearchGrantState.REJECTED


def test_grant_revocation_is_immediate_and_may_use_the_original_checker() -> None:
    now = datetime.now(UTC)
    grant = _grant(now=now)
    checker_id = _approve_grant(grant, now=now)
    assert grant.is_active_at(now)
    grant.revoke(
        actor_id=checker_id,
        reason="Incident response revocation",
        policy_decision_id=uuid4(),
        expected_version=2,
        now=now + timedelta(microseconds=1),
    )
    assert grant.state is RestrictedSearchGrantState.REVOKED
    assert grant.revoked_by == checker_id
    assert not grant.is_active_at(now + timedelta(microseconds=1))
    assert grant.events[-1].event_type == "authz.restricted_search_grant.revoked.v1"
    with pytest.raises(ConflictError, match="modified"):
        grant.revoke(
            actor_id=uuid4(),
            reason="Stale revocation",
            policy_decision_id=uuid4(),
            expected_version=2,
            now=now + timedelta(seconds=1),
        )
