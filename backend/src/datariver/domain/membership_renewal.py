from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from datariver.domain.common import ConflictError, DomainEvent, ValidationError, uuid7

RENEWAL_TERM_MONTHS = 6
RENEWAL_REQUEST_WINDOW = timedelta(days=30)


class MembershipRenewalState(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class MembershipRenewalDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


def add_calendar_months(value: datetime, months: int) -> datetime:
    """Add whole calendar months while retaining timezone and end-of-month safety."""
    if months < 1:
        raise ValidationError("Membership renewal months must be positive.")
    target_index = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(target_index, 12)
    month = month_index + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


@dataclass(slots=True)
class MembershipRenewalRequest:
    renewal_request_id: UUID
    workspace_id: UUID
    target_subject_id: UUID
    requester_id: UUID
    reason: str
    current_expires_at: datetime
    requested_expires_at: datetime
    state: MembershipRenewalState
    version: int
    created_at: datetime
    checker_id: UUID | None = None
    decision_reason: str | None = None
    decision_policy_decision_id: UUID | None = None
    decided_at: datetime | None = None
    events: list[DomainEvent] = field(default_factory=list, repr=False)

    @classmethod
    def create(
        cls,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        reason: str,
        current_expires_at: datetime,
        requested_at: datetime,
    ) -> MembershipRenewalRequest:
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValidationError("Membership renewal reason is required.")
        if len(normalized_reason) > 4000:
            raise ValidationError("Membership renewal reason is too long.")
        if requested_at.tzinfo is None or current_expires_at.tzinfo is None:
            raise ValidationError("Membership renewal timestamps must be timezone-aware.")
        if requested_at >= current_expires_at:
            raise ConflictError("An expired workspace membership cannot request renewal.")
        if requested_at < current_expires_at - RENEWAL_REQUEST_WINDOW:
            raise ConflictError("Membership renewal opens 30 days before the current expiration.")
        requested_expires_at = add_calendar_months(current_expires_at, RENEWAL_TERM_MONTHS)
        value = cls(
            renewal_request_id=uuid7(),
            workspace_id=workspace_id,
            target_subject_id=subject_id,
            requester_id=subject_id,
            reason=normalized_reason,
            current_expires_at=current_expires_at,
            requested_expires_at=requested_expires_at,
            state=MembershipRenewalState.PENDING,
            version=1,
            created_at=requested_at,
        )
        value.events.append(
            DomainEvent.create(
                event_type="iam.workspace_membership.renewal_requested.v1",
                aggregate_type="membership_renewal_request",
                aggregate_id=value.renewal_request_id,
                workspace_id=workspace_id,
                payload={
                    "target_subject_id": str(subject_id),
                    "current_expires_at": current_expires_at.isoformat(),
                    "requested_expires_at": requested_expires_at.isoformat(),
                },
            )
        )
        return value

    def decide(
        self,
        *,
        decision: MembershipRenewalDecision,
        checker_id: UUID,
        reason: str,
        policy_decision_id: UUID,
        decided_at: datetime,
        expected_version: int,
        observed_membership_expires_at: datetime,
    ) -> None:
        if self.version != expected_version:
            raise ConflictError("The membership renewal request version changed.")
        if self.state is not MembershipRenewalState.PENDING:
            raise ConflictError("The membership renewal request is already decided.")
        if checker_id in {self.requester_id, self.target_subject_id}:
            raise ValidationError(
                "A membership renewal requester cannot approve their own request."
            )
        if observed_membership_expires_at != self.current_expires_at:
            raise ConflictError("The workspace membership expiration changed after this request.")
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValidationError("Membership renewal decision reason is required.")
        if len(normalized_reason) > 4000:
            raise ValidationError("Membership renewal decision reason is too long.")
        self.state = MembershipRenewalState(decision.value)
        self.checker_id = checker_id
        self.decision_reason = normalized_reason
        self.decision_policy_decision_id = policy_decision_id
        self.decided_at = decided_at
        self.version += 1
        self.events.append(
            DomainEvent.create(
                event_type=f"iam.workspace_membership.renewal_{decision.value.lower()}.v1",
                aggregate_type="membership_renewal_request",
                aggregate_id=self.renewal_request_id,
                workspace_id=self.workspace_id,
                payload={
                    "checker_id": str(checker_id),
                    "target_subject_id": str(self.target_subject_id),
                    "requested_expires_at": self.requested_expires_at.isoformat(),
                    "version": self.version,
                },
            )
        )
