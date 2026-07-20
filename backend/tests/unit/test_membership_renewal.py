from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from datariver.domain.common import ConflictError, ValidationError
from datariver.domain.membership_renewal import (
    MembershipRenewalDecision,
    MembershipRenewalRequest,
    MembershipRenewalState,
    add_calendar_months,
)


def test_six_month_term_uses_calendar_months_at_month_end() -> None:
    assert add_calendar_months(datetime(2026, 8, 31, 9, tzinfo=UTC), 6) == datetime(
        2027, 2, 28, 9, tzinfo=UTC
    )


def test_renewal_opens_exactly_thirty_days_before_expiry() -> None:
    expires_at = datetime(2027, 1, 20, 9, tzinfo=UTC)
    with pytest.raises(ConflictError, match="opens 30 days"):
        MembershipRenewalRequest.create(
            workspace_id=uuid4(),
            subject_id=uuid4(),
            reason="Continue project access.",
            current_expires_at=expires_at,
            requested_at=expires_at - timedelta(days=30, seconds=1),
        )

    request = MembershipRenewalRequest.create(
        workspace_id=uuid4(),
        subject_id=uuid4(),
        reason="Continue project access.",
        current_expires_at=expires_at,
        requested_at=expires_at - timedelta(days=30),
    )

    assert request.state is MembershipRenewalState.PENDING
    assert request.requested_expires_at == datetime(2027, 7, 20, 9, tzinfo=UTC)
    assert request.events[0].event_type == "iam.workspace_membership.renewal_requested.v1"


def test_renewal_requires_independent_admin_and_unchanged_expiry() -> None:
    subject_id = uuid4()
    expires_at = datetime(2027, 1, 20, 9, tzinfo=UTC)
    request = MembershipRenewalRequest.create(
        workspace_id=uuid4(),
        subject_id=subject_id,
        reason="Continue project access.",
        current_expires_at=expires_at,
        requested_at=expires_at - timedelta(days=10),
    )
    with pytest.raises(ValidationError, match="own request"):
        request.decide(
            decision=MembershipRenewalDecision.APPROVED,
            checker_id=subject_id,
            reason="Self approval is prohibited.",
            policy_decision_id=uuid4(),
            decided_at=expires_at - timedelta(days=9),
            expected_version=1,
            observed_membership_expires_at=expires_at,
        )
    with pytest.raises(ConflictError, match="expiration changed"):
        request.decide(
            decision=MembershipRenewalDecision.APPROVED,
            checker_id=uuid4(),
            reason="Approve six more months.",
            policy_decision_id=uuid4(),
            decided_at=expires_at - timedelta(days=9),
            expected_version=1,
            observed_membership_expires_at=expires_at + timedelta(days=1),
        )

    checker_id = uuid4()
    request.decide(
        decision=MembershipRenewalDecision.APPROVED,
        checker_id=checker_id,
        reason="Approve six more months.",
        policy_decision_id=uuid4(),
        decided_at=expires_at - timedelta(days=9),
        expected_version=1,
        observed_membership_expires_at=expires_at,
    )

    assert request.state is MembershipRenewalState.APPROVED
    assert request.checker_id == checker_id
    assert request.version == 2
    assert request.events[-1].event_type == "iam.workspace_membership.renewal_approved.v1"
