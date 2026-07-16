from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from datariver.domain.admin_access import (
    AdminAccessDecision,
    AdminAccessRequest,
    AdminAccessRequestState,
    MembershipAccessUpdate,
)
from datariver.domain.authz import Action, Classification
from datariver.domain.common import ConflictError, ValidationError


def command(
    *, workspace_id: UUID | None = None, target_subject_id: UUID | None = None
) -> MembershipAccessUpdate:
    return MembershipAccessUpdate(
        workspace_id=workspace_id or uuid4(),
        target_subject_id=target_subject_id or uuid4(),
        expected_membership_version=3,
        active=True,
        clearance=Classification.CONFIDENTIAL,
        groups=frozenset({"data-stewards"}),
        allowed_actions=frozenset({Action.CATALOG_READ}),
        denied_actions=frozenset({Action.CHAT_QUERY}),
        allowed_system_ids=frozenset({uuid4()}),
    )


def test_command_hash_is_canonical_and_round_trips() -> None:
    value = command()
    restored = MembershipAccessUpdate.from_command_document(value.command_document())

    assert restored == value
    assert restored.payload_hash == value.payload_hash


def test_request_rejects_self_benefit_and_long_lifetime() -> None:
    now = datetime.now(UTC)
    actor = uuid4()
    with pytest.raises(ValidationError, match="own access"):
        AdminAccessRequest.create(
            requester_id=actor,
            reason="access maintenance",
            policy_decision_id=uuid4(),
            command=command(target_subject_id=actor),
            now=now,
            expires_at=now + timedelta(minutes=5),
        )
    with pytest.raises(ValidationError, match="five minutes"):
        AdminAccessRequest.create(
            requester_id=uuid4(),
            reason="access maintenance",
            policy_decision_id=uuid4(),
            command=command(),
            now=now,
            expires_at=now + timedelta(minutes=5, seconds=1),
        )


def test_maker_checker_approval_and_one_time_consumption() -> None:
    now = datetime.now(UTC)
    maker = uuid4()
    checker = uuid4()
    value = AdminAccessRequest.create(
        requester_id=maker,
        reason="access maintenance",
        policy_decision_id=uuid4(),
        command=command(),
        now=now,
        expires_at=now + timedelta(minutes=5),
    )

    with pytest.raises(ValidationError, match="maker"):
        value.decide(
            decision=AdminAccessDecision.APPROVED,
            actor_id=maker,
            reason="self",
            policy_decision_id=uuid4(),
            expected_version=1,
            now=now,
        )
    with pytest.raises(ValidationError, match="target subject"):
        value.decide(
            decision=AdminAccessDecision.APPROVED,
            actor_id=value.command.target_subject_id,
            reason="self benefit",
            policy_decision_id=uuid4(),
            expected_version=1,
            now=now,
        )
    value.decide(
        decision=AdminAccessDecision.APPROVED,
        actor_id=checker,
        reason="independent review",
        policy_decision_id=uuid4(),
        expected_version=1,
        now=now,
    )
    value.consume(actor_id=maker, policy_decision_id=uuid4(), expected_version=2, now=now)
    assert value.state is AdminAccessRequestState.CONSUMED
    assert value.consumed_by == maker
    with pytest.raises(ConflictError, match="Only an approved"):
        value.consume(actor_id=maker, policy_decision_id=uuid4(), expected_version=3, now=now)


def test_expiry_version_and_payload_binding_fail_closed() -> None:
    now = datetime.now(UTC)
    value = AdminAccessRequest.create(
        requester_id=uuid4(),
        reason="access maintenance",
        policy_decision_id=uuid4(),
        command=command(),
        now=now,
        expires_at=now + timedelta(minutes=1),
    )
    with pytest.raises(ConflictError, match="modified"):
        value.decide(
            decision=AdminAccessDecision.APPROVED,
            actor_id=uuid4(),
            reason="reviewed",
            policy_decision_id=uuid4(),
            expected_version=2,
            now=now,
        )
    with pytest.raises(ConflictError, match="expired"):
        value.decide(
            decision=AdminAccessDecision.APPROVED,
            actor_id=uuid4(),
            reason="reviewed",
            policy_decision_id=uuid4(),
            expected_version=1,
            now=now + timedelta(minutes=1),
        )
    value.payload_hash = "0" * 64
    with pytest.raises(ConflictError, match="payload"):
        value.decide(
            decision=AdminAccessDecision.APPROVED,
            actor_id=uuid4(),
            reason="reviewed",
            policy_decision_id=uuid4(),
            expected_version=1,
            now=now,
        )
