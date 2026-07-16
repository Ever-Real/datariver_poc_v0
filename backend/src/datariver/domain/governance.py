from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from datariver.domain.authz import Classification
from datariver.domain.common import (
    ConflictError,
    DomainEvent,
    ValidationError,
    canonical_json_hash,
    utc_now,
    uuid7,
)


class ChangeState(StrEnum):
    REGISTERED = "REGISTERED"
    IN_REVIEW = "IN_REVIEW"
    TESTING = "TESTING"
    FINAL_REVIEW = "FINAL_REVIEW"
    APPLY_QUEUED = "APPLY_QUEUED"
    APPLYING = "APPLYING"
    APPLIED = "APPLIED"
    APPLY_FAILED = "APPLY_FAILED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


ALLOWED_TRANSITIONS: dict[ChangeState, frozenset[ChangeState]] = {
    ChangeState.REGISTERED: frozenset(
        {ChangeState.IN_REVIEW, ChangeState.REJECTED, ChangeState.CANCELLED}
    ),
    ChangeState.IN_REVIEW: frozenset(
        {
            ChangeState.TESTING,
            ChangeState.FINAL_REVIEW,
            ChangeState.REJECTED,
            ChangeState.CANCELLED,
        }
    ),
    ChangeState.TESTING: frozenset(
        {
            ChangeState.IN_REVIEW,
            ChangeState.FINAL_REVIEW,
            ChangeState.REJECTED,
            ChangeState.CANCELLED,
        }
    ),
    ChangeState.FINAL_REVIEW: frozenset(
        {ChangeState.APPLY_QUEUED, ChangeState.REJECTED, ChangeState.CANCELLED}
    ),
    ChangeState.APPLY_QUEUED: frozenset(
        {ChangeState.APPLYING, ChangeState.APPLY_FAILED, ChangeState.CANCELLED}
    ),
    ChangeState.APPLYING: frozenset({ChangeState.APPLIED, ChangeState.APPLY_FAILED}),
    ChangeState.APPLY_FAILED: frozenset({ChangeState.APPLY_QUEUED, ChangeState.CANCELLED}),
    ChangeState.APPLIED: frozenset(),
    ChangeState.REJECTED: frozenset(),
    ChangeState.CANCELLED: frozenset(),
}


class ApprovalDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


ALLOWED_DATAHUB_ASPECTS = frozenset(
    {
        "datasetProperties",
        "domains",
        "globalTags",
        "glossaryTerms",
        "ownership",
        "schemaMetadata",
    }
)


@dataclass(frozen=True, slots=True)
class ChangeItem:
    item_id: UUID
    target_type: str
    target_ref: str
    operation: str
    after_document: dict[str, Any]
    aspect_name: str
    before_hash: str | None = None
    after_hash: str | None = None
    target_asset_id: UUID | None = None
    target_asset_type: str | None = None
    target_system_id: UUID | None = None
    target_domain_id: UUID | None = None
    target_owner_department_id: UUID | None = None
    target_classification: Classification | None = None
    target_lifecycle: str | None = None
    target_source_version: str | None = None
    target_observed_at: datetime | None = None
    target_binding_hash: str | None = None

    @property
    def has_complete_target_binding(self) -> bool:
        return all(
            value is not None
            for value in (
                self.target_asset_id,
                self.target_asset_type,
                self.target_classification,
                self.target_lifecycle,
                self.target_source_version,
                self.target_observed_at,
                self.target_binding_hash,
            )
        )

    def expected_target_binding_hash(self) -> str | None:
        if not self.has_complete_target_binding:
            return None
        assert self.target_asset_id is not None
        assert self.target_asset_type is not None
        assert self.target_classification is not None
        assert self.target_lifecycle is not None
        return change_target_binding_hash(
            target_ref=self.target_ref,
            asset_id=self.target_asset_id,
            asset_type=self.target_asset_type,
            system_id=self.target_system_id,
            domain_id=self.target_domain_id,
            owner_department_id=self.target_owner_department_id,
            classification=self.target_classification,
            lifecycle=self.target_lifecycle,
        )


def change_target_binding_hash(
    *,
    target_ref: str,
    asset_id: UUID,
    asset_type: str,
    system_id: UUID | None,
    domain_id: UUID | None,
    owner_department_id: UUID | None,
    classification: Classification,
    lifecycle: str,
) -> str:
    """Hash immutable target identity and authorization-relevant snapshot attributes."""

    return canonical_json_hash(
        {
            "target_ref": target_ref,
            "asset_id": str(asset_id),
            "asset_type": asset_type,
            "system_id": str(system_id) if system_id is not None else None,
            "domain_id": str(domain_id) if domain_id is not None else None,
            "owner_department_id": (
                str(owner_department_id) if owner_department_id is not None else None
            ),
            "classification": int(classification),
            "lifecycle": lifecycle,
        }
    )


@dataclass(frozen=True, slots=True)
class Approval:
    approval_id: UUID
    stage: str
    decision: ApprovalDecision
    actor_id: UUID
    reason: str
    policy_decision_id: UUID
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class Transition:
    transition_id: UUID
    from_state: ChangeState
    to_state: ChangeState
    actor_id: UUID
    reason: str
    policy_decision_id: UUID
    occurred_at: datetime


@dataclass(slots=True)
class ChangeRequest:
    change_request_id: UUID
    workspace_id: UUID
    number: str
    request_type: str
    title: str
    description: str
    requester_id: UUID
    classification: Classification = Classification.INTERNAL
    state: ChangeState = ChangeState.REGISTERED
    version: int = 1
    items: list[ChangeItem] = field(default_factory=list)
    approvals: list[Approval] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)
    events: list[DomainEvent] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        *,
        workspace_id: UUID,
        number: str,
        request_type: str,
        title: str,
        description: str,
        requester_id: UUID,
        items: list[ChangeItem],
        classification: Classification = Classification.INTERNAL,
    ) -> ChangeRequest:
        if not title.strip():
            raise ValidationError("Change request title is required.")
        if len(items) != 1:
            raise ValidationError(
                "Exactly one change item is supported until durable item checkpoints exist."
            )
        for item in items:
            if item.target_type != "DATAHUB_ASPECT":
                raise ValidationError("Only typed DataHub aspect changes are currently executable.")
            if item.operation != "UPSERT":
                raise ValidationError(
                    "Only idempotent DataHub UPSERT changes are currently executable."
                )
            if not item.target_ref.startswith("urn:li:"):
                raise ValidationError("A DataHub target must be a valid urn:li: identifier.")
            if not item.aspect_name.strip():
                raise ValidationError("A DataHub aspect name is required.")
            if item.aspect_name not in ALLOWED_DATAHUB_ASPECTS:
                raise ValidationError("The DataHub aspect is not in the governed allowlist.")
            if item.before_hash is None:
                raise ValidationError(
                    "A current DataHub aspect hash is required for optimistic concurrency."
                )
            if not item.has_complete_target_binding:
                raise ValidationError("A server-verified catalog target binding is required.")
            if item.target_asset_type != "DATASET" or item.target_lifecycle != "ACTIVE":
                raise ValidationError("The catalog target binding is not an active dataset.")
            if item.target_classification is None or classification < item.target_classification:
                raise ValidationError(
                    "The change-request classification cannot be lower than its target."
                )
            if not item.target_source_version or not item.target_source_version.strip():
                raise ValidationError("The catalog target source version is required.")
            if (
                item.target_observed_at is None
                or item.target_observed_at.tzinfo is None
                or item.target_observed_at.utcoffset() is None
            ):
                raise ValidationError("The catalog target observation time must be timezone-aware.")
            if item.expected_target_binding_hash() != item.target_binding_hash:
                raise ValidationError("The catalog target binding is invalid.")
        request = cls(
            change_request_id=uuid7(),
            workspace_id=workspace_id,
            number=number,
            request_type=request_type,
            title=title.strip(),
            description=description.strip(),
            requester_id=requester_id,
            classification=classification,
            items=list(items),
        )
        request.events.append(
            DomainEvent.create(
                event_type="governance.change_request.registered.v1",
                aggregate_type="change_request",
                aggregate_id=request.change_request_id,
                workspace_id=workspace_id,
                payload={"number": number, "request_type": request_type},
            )
        )
        return request

    def add_approval(
        self,
        *,
        stage: str,
        decision: ApprovalDecision,
        actor_id: UUID,
        reason: str,
        policy_decision_id: UUID,
        expected_version: int,
    ) -> None:
        self._check_version(expected_version)
        if stage not in {"REVIEW", "FINAL"}:
            raise ValidationError("Approval stage must be REVIEW or FINAL.")
        if stage == "FINAL" and self.state is not ChangeState.FINAL_REVIEW:
            raise ValidationError("Final approval is only allowed during final review.")
        if stage == "REVIEW" and self.state not in {
            ChangeState.IN_REVIEW,
            ChangeState.TESTING,
            ChangeState.FINAL_REVIEW,
        }:
            raise ValidationError("Review approval is not allowed in the current state.")
        if actor_id == self.requester_id and stage == "FINAL":
            raise ValidationError("The requester cannot provide final approval.")
        if any(a.stage == stage and a.actor_id == actor_id for a in self.approvals):
            raise ConflictError("The actor already decided this approval stage.")
        self.approvals.append(
            Approval(
                approval_id=uuid7(),
                stage=stage,
                decision=decision,
                actor_id=actor_id,
                reason=reason.strip(),
                policy_decision_id=policy_decision_id,
                occurred_at=utc_now(),
            )
        )
        self.version += 1
        self.events.append(
            DomainEvent.create(
                event_type="governance.change_request.approval_recorded.v1",
                aggregate_type="change_request",
                aggregate_id=self.change_request_id,
                workspace_id=self.workspace_id,
                payload={
                    "stage": stage,
                    "decision": decision.value,
                    "actor_id": str(actor_id),
                    "version": self.version,
                },
            )
        )

    def transition(
        self,
        *,
        target: ChangeState,
        actor_id: UUID,
        reason: str,
        policy_decision_id: UUID,
        expected_version: int,
    ) -> None:
        self._check_version(expected_version)
        if target is ChangeState.APPLIED:
            raise ValidationError("APPLIED requires verified reconciliation.")
        self._assert_transition_allowed(target)
        if target is ChangeState.APPLY_QUEUED:
            if any(
                approval.stage == "FINAL" and approval.decision is ApprovalDecision.REJECTED
                for approval in self.approvals
            ):
                raise ValidationError("A final rejection prevents application.")
            final_approvers = {
                approval.actor_id
                for approval in self.approvals
                if approval.stage == "FINAL" and approval.decision is ApprovalDecision.APPROVED
            }
            required = 2 if self.classification >= Classification.CONFIDENTIAL else 1
            if len(final_approvers) < required:
                raise ValidationError(
                    f"{required} distinct final approval(s) are required before application."
                )
            if self.requester_id in final_approvers:
                raise ValidationError("Requester final approval is invalid.")
        self._record_transition(target, actor_id, reason, policy_decision_id)

    def mark_applied(
        self,
        *,
        actor_id: UUID,
        policy_decision_id: UUID,
        expected_version: int,
        expected_hash: str,
        observed_hash: str,
        reconciled: bool,
    ) -> None:
        self._check_version(expected_version)
        self._assert_transition_allowed(ChangeState.APPLIED)
        if not reconciled or not expected_hash or expected_hash != observed_hash:
            raise ValidationError("Target state did not reconcile with the approved content hash.")
        self._record_transition(
            ChangeState.APPLIED,
            actor_id,
            "External state re-read and content hash reconciled.",
            policy_decision_id,
        )

    def _record_transition(
        self,
        target: ChangeState,
        actor_id: UUID,
        reason: str,
        policy_decision_id: UUID,
    ) -> None:
        previous = self.state
        self.state = target
        self.version += 1
        self.transitions.append(
            Transition(
                transition_id=uuid7(),
                from_state=previous,
                to_state=target,
                actor_id=actor_id,
                reason=reason.strip(),
                policy_decision_id=policy_decision_id,
                occurred_at=utc_now(),
            )
        )
        self.events.append(
            DomainEvent.create(
                event_type=f"governance.change_request.{target.value.lower()}.v1",
                aggregate_type="change_request",
                aggregate_id=self.change_request_id,
                workspace_id=self.workspace_id,
                payload={"from": previous.value, "to": target.value, "version": self.version},
            )
        )

    def _assert_transition_allowed(self, target: ChangeState) -> None:
        if target not in ALLOWED_TRANSITIONS[self.state]:
            raise ValidationError(
                f"Transition {self.state.value} -> {target.value} is not allowed.",
                details={"current_state": self.state.value, "target_state": target.value},
            )

    def _check_version(self, expected_version: int) -> None:
        if expected_version != self.version:
            raise ConflictError(
                "The change request was modified by another operation.",
                details={"expected": expected_version, "actual": self.version},
            )
