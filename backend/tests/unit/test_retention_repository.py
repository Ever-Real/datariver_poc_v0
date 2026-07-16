from datetime import UTC, datetime
from uuid import uuid4

import pytest

from datariver.domain.common import ConflictError
from datariver.domain.retention import (
    LegalHold,
    LegalHoldScope,
    RetentionDataClass,
    RetentionPolicyVersion,
    RetentionRules,
)
from datariver.infrastructure.db.retention import (
    _hold_event_model,
    _hold_model,
    _hydrate_hold,
    _policy_model,
    _required_policy,
)


def test_policy_hydration_rejects_a_tampered_rules_hash() -> None:
    policy = RetentionPolicyVersion.propose(
        workspace_id=uuid4(),
        policy_number=1,
        rules=RetentionRules(30, 90, 13, 7),
        requester_id=uuid4(),
        reason="Operating policy",
        policy_decision_id=uuid4(),
    )
    model = _policy_model(policy)
    model.completed_operation_days = 31

    with pytest.raises(ConflictError, match="integrity"):
        _required_policy(model)


def test_legal_hold_hydration_requires_complete_hash_bound_history() -> None:
    hold = LegalHold.create(
        workspace_id=uuid4(),
        data_class=RetentionDataClass.AUDIT_EVIDENCE,
        scope=LegalHoldScope.WORKSPACE,
        scope_id=None,
        reason="Investigation",
        actor_id=uuid4(),
        policy_decision_id=uuid4(),
        now=datetime.now(UTC),
    )
    model = _hold_model(hold)
    event = _hold_event_model(hold, hold.actions[0])

    hydrated = _hydrate_hold(model, (event,))
    assert hydrated.payload_hash == hold.payload_hash
    assert hydrated.actions == hold.actions

    event.payload_hash = "0" * 64
    with pytest.raises(ConflictError, match="action failed its integrity"):
        _hydrate_hold(model, (event,))


def test_legal_hold_hydration_rejects_missing_append_only_event() -> None:
    hold = LegalHold.create(
        workspace_id=uuid4(),
        data_class=RetentionDataClass.CHAT_CONTENT,
        scope=LegalHoldScope.SUBJECT,
        scope_id=uuid4(),
        reason="Investigation",
        actor_id=uuid4(),
        policy_decision_id=uuid4(),
        now=datetime.now(UTC),
    )
    model = _hold_model(hold)

    with pytest.raises(ConflictError, match="history is incomplete"):
        _hydrate_hold(model, ())
