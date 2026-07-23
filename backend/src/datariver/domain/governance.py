from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from datariver.domain.authz import Classification
from datariver.domain.catalog import is_dataset_asset_type
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
    COMPLETED = "COMPLETED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


ALLOWED_TRANSITIONS: dict[ChangeState, frozenset[ChangeState]] = {
    ChangeState.REGISTERED: frozenset(
        {ChangeState.IN_REVIEW, ChangeState.REJECTED, ChangeState.CANCELLED}
    ),
    ChangeState.IN_REVIEW: frozenset(
        {
            ChangeState.TESTING,
            ChangeState.CHANGES_REQUESTED,
            ChangeState.REJECTED,
            ChangeState.CANCELLED,
        }
    ),
    ChangeState.TESTING: frozenset(
        {
            ChangeState.IN_REVIEW,
            ChangeState.FINAL_REVIEW,
            ChangeState.CHANGES_REQUESTED,
            ChangeState.REJECTED,
            ChangeState.CANCELLED,
        }
    ),
    ChangeState.FINAL_REVIEW: frozenset(
        {
            ChangeState.APPLY_QUEUED,
            ChangeState.COMPLETED,
            ChangeState.CHANGES_REQUESTED,
            ChangeState.REJECTED,
            ChangeState.CANCELLED,
        }
    ),
    ChangeState.APPLY_QUEUED: frozenset(
        {ChangeState.APPLYING, ChangeState.APPLY_FAILED, ChangeState.CANCELLED}
    ),
    ChangeState.APPLYING: frozenset({ChangeState.APPLIED, ChangeState.APPLY_FAILED}),
    ChangeState.APPLY_FAILED: frozenset({ChangeState.APPLY_QUEUED, ChangeState.CANCELLED}),
    ChangeState.COMPLETED: frozenset(),
    ChangeState.CHANGES_REQUESTED: frozenset({ChangeState.REGISTERED, ChangeState.CANCELLED}),
    ChangeState.APPLIED: frozenset(),
    ChangeState.REJECTED: frozenset(),
    ChangeState.CANCELLED: frozenset(),
}


class ApprovalDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ApprovalAuthorityKind(StrEnum):
    SYSTEM_DEVELOPER = "SYSTEM_DEVELOPER"
    SYSTEM_DATA_STEWARD = "SYSTEM_DATA_STEWARD"
    GLOBAL_ADMIN = "GLOBAL_ADMIN"


class ChangeTestRunState(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class ChangePriority(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ChangeUrgency(StrEnum):
    NORMAL = "NORMAL"
    URGENT = "URGENT"
    EMERGENCY = "EMERGENCY"


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

CHANGE_INTAKE_ASPECT = "changeIntake"
DATAHUB_INTAKE_TARGET = "DATAHUB_INTAKE"
MANUAL_DATASET_INTAKE_TARGET = "MANUAL_DATASET_INTAKE"

MAX_CHANGE_ITEMS = 200
MAX_CHANGE_APPROVALS = 600
MAX_CHANGE_TRANSITIONS = 200
MAX_CHANGE_ROUNDS = 50
MAX_CHANGE_TEST_RUNS = 200


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
    item_contract_hash: str | None = None
    routing_system_id: UUID | None = None

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
    round_id: UUID
    authorities: tuple[ApprovalAuthority, ...] = ()


@dataclass(frozen=True, slots=True)
class ApprovalAuthority:
    kind: ApprovalAuthorityKind
    system_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.kind is ApprovalAuthorityKind.GLOBAL_ADMIN and self.system_id is not None:
            raise ValidationError("Global administrator approval cannot carry a system scope.")
        if self.kind is not ApprovalAuthorityKind.GLOBAL_ADMIN and self.system_id is None:
            raise ValidationError("System approval authority requires a system scope.")


@dataclass(frozen=True, slots=True)
class Transition:
    transition_id: UUID
    from_state: ChangeState
    to_state: ChangeState
    actor_id: UUID
    reason: str
    policy_decision_id: UUID
    occurred_at: datetime
    round_id: UUID


@dataclass(slots=True)
class ChangeRequestRound:
    round_id: UUID
    round_number: int
    submitted_by: UUID
    submitted_at: datetime
    evidence_hash: str
    closed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ChangeTestRun:
    test_run_id: UUID
    round_id: UUID
    system_id: UUID
    attachment_id: UUID
    state: ChangeTestRunState
    plan_hash: str
    result_hash: str
    bounded_summary: dict[str, Any]
    recorded_by: UUID
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
    requester_department_id: UUID | None
    current_round_id: UUID
    current_round_number: int
    created_at: datetime = field(default_factory=utc_now)
    requested_due_date: date | None = None
    priority: ChangePriority | None = None
    urgency: ChangeUrgency | None = None
    classification: Classification = Classification.INTERNAL
    state: ChangeState = ChangeState.REGISTERED
    version: int = 1
    items: list[ChangeItem] = field(default_factory=list)
    approvals: list[Approval] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)
    rounds: list[ChangeRequestRound] = field(default_factory=list)
    test_runs: list[ChangeTestRun] = field(default_factory=list)
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
        requester_department_id: UUID | None = None,
        classification: Classification = Classification.INTERNAL,
        requested_due_date: date | None = None,
        priority: ChangePriority | None = None,
        urgency: ChangeUrgency | None = None,
    ) -> ChangeRequest:
        if not title.strip():
            raise ValidationError("Change request title is required.")
        if not 1 <= len(items) <= MAX_CHANGE_ITEMS:
            raise ValidationError("A change request must contain between one and 200 change items.")
        if len(items) != 1 and any(item.target_type == "DATAHUB_ASPECT" for item in items):
            raise ValidationError(
                "Exactly one change item is supported for executable DataHub changes until "
                "durable item checkpoints exist."
            )
        for item in items:
            if item.target_type == MANUAL_DATASET_INTAKE_TARGET:
                if (
                    item.operation != "CREATE"
                    or item.aspect_name != CHANGE_INTAKE_ASPECT
                    or not item.target_ref.startswith("urn:datariver:proposed-dataset:")
                    or item.before_hash is not None
                    or item.has_complete_target_binding
                ):
                    raise ValidationError("The manual dataset intake item is invalid.")
                continue
            if item.target_type not in {"DATAHUB_ASPECT", DATAHUB_INTAKE_TARGET}:
                raise ValidationError("The change item target type is not governed.")
            if item.target_type == "DATAHUB_ASPECT":
                if item.operation != "UPSERT" or item.aspect_name not in ALLOWED_DATAHUB_ASPECTS:
                    raise ValidationError(
                        "The DataHub aspect change is outside the governed allowlist."
                    )
            elif item.operation != "REVIEW" or item.aspect_name != CHANGE_INTAKE_ASPECT:
                raise ValidationError("The DataHub intake item is invalid.")
            if not item.target_ref.startswith("urn:li:dataset:"):
                raise ValidationError("A DataHub target must be a dataset URN.")
            if item.before_hash is None:
                if item.target_type == "DATAHUB_ASPECT":
                    raise ValidationError(
                        "A current DataHub aspect hash is required for optimistic concurrency."
                    )
                raise ValidationError(
                    "A current target hash is required for a DataHub-backed item."
                )
            if not item.has_complete_target_binding:
                raise ValidationError("A server-verified catalog target binding is required.")
            if (
                not is_dataset_asset_type(item.target_asset_type)
                or item.target_lifecycle != "ACTIVE"
            ):
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
        change_request_id = uuid7()
        current_round_id = uuid7()
        created_at = utc_now()
        request = cls(
            change_request_id=change_request_id,
            workspace_id=workspace_id,
            number=number,
            request_type=request_type,
            title=title.strip(),
            description=description.strip(),
            requester_id=requester_id,
            requester_department_id=requester_department_id,
            current_round_id=current_round_id,
            current_round_number=1,
            created_at=created_at,
            requested_due_date=requested_due_date,
            priority=priority,
            urgency=urgency,
            classification=classification,
            items=list(items),
            rounds=[
                ChangeRequestRound(
                    round_id=current_round_id,
                    round_number=1,
                    submitted_by=requester_id,
                    submitted_at=created_at,
                    evidence_hash=canonical_json_hash(
                        {
                            "change_request_id": str(change_request_id),
                            "round_number": 1,
                            "title": title.strip(),
                            "description": description.strip(),
                            "item_ids": [str(item.item_id) for item in items],
                        }
                    ),
                )
            ],
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
        authorities: tuple[ApprovalAuthority, ...],
    ) -> None:
        self._check_version(expected_version)
        if len(self.approvals) >= MAX_CHANGE_APPROVALS:
            raise ConflictError(
                "The change-request approval history reached its governed capacity.",
                details={"code": "CHANGE_REQUEST_APPROVAL_CAPACITY"},
            )
        if stage not in {"REVIEW", "TEST", "FINAL"}:
            raise ValidationError("Approval stage must be REVIEW, TEST or FINAL.")
        if stage == "FINAL" and self.state is not ChangeState.FINAL_REVIEW:
            raise ValidationError("Final approval is only allowed during final review.")
        if stage == "REVIEW" and self.state is not ChangeState.IN_REVIEW:
            raise ValidationError("Review approval is not allowed in the current state.")
        if stage == "TEST" and self.state is not ChangeState.TESTING:
            raise ValidationError("Test approval is not allowed in the current state.")
        if actor_id == self.requester_id and stage == "FINAL":
            raise ValidationError("The requester cannot provide final approval.")
        required_system_ids = self.required_system_ids()
        authority_set = set(authorities)
        if stage in {"REVIEW", "TEST"}:
            relevant_developer_authorities = {
                ApprovalAuthority(ApprovalAuthorityKind.SYSTEM_DEVELOPER, system_id)
                for system_id in required_system_ids
            }
            if not authority_set & relevant_developer_authorities:
                raise ValidationError(
                    "Review and test decisions require Developer assignment for a target system."
                )
        else:
            relevant = (
                {
                    ApprovalAuthority(ApprovalAuthorityKind.SYSTEM_DEVELOPER, system_id)
                    for system_id in required_system_ids
                }
                | {
                    ApprovalAuthority(ApprovalAuthorityKind.SYSTEM_DATA_STEWARD, system_id)
                    for system_id in required_system_ids
                }
                | {ApprovalAuthority(ApprovalAuthorityKind.GLOBAL_ADMIN)}
            )
            if not authority_set & relevant:
                raise ValidationError("The actor has no final-approval authority for this request.")
        if any(
            a.round_id == self.current_round_id and a.stage == stage and a.actor_id == actor_id
            for a in self.approvals
        ):
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
                round_id=self.current_round_id,
                authorities=tuple(
                    sorted(authority_set, key=lambda item: (item.kind.value, str(item.system_id)))
                ),
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
                    "authorities": [
                        {
                            "kind": authority.kind.value,
                            "system_id": (
                                str(authority.system_id)
                                if authority.system_id is not None
                                else None
                            ),
                        }
                        for authority in authorities
                    ],
                    "version": self.version,
                },
            )
        )
        if stage == "FINAL" and decision is ApprovalDecision.REJECTED:
            self._record_transition(
                ChangeState.REJECTED,
                actor_id,
                reason,
                policy_decision_id,
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
        if target in {ChangeState.APPLIED, ChangeState.COMPLETED}:
            raise ValidationError("Terminal completion requires its controlled service path.")
        if self.state is ChangeState.FINAL_REVIEW and target is ChangeState.REJECTED:
            raise ValidationError("Final rejection requires a typed FINAL approval decision.")
        self._assert_transition_allowed(target)
        if (
            self.state is ChangeState.CHANGES_REQUESTED
            and target is ChangeState.REGISTERED
            and actor_id != self.requester_id
        ):
            raise ValidationError("Only the requester can resubmit a change request.")
        if target is ChangeState.APPLY_QUEUED:
            if any(
                approval.stage == "FINAL" and approval.decision is ApprovalDecision.REJECTED
                for approval in self.approvals
                if approval.round_id == self.current_round_id
            ):
                raise ValidationError("A final rejection prevents application.")
            self._assert_complete_final_authority()
        if target is ChangeState.TESTING:
            self._assert_complete_system_developer_approval("REVIEW")
        if target is ChangeState.FINAL_REVIEW:
            self._assert_complete_system_developer_approval("TEST")
            self._assert_complete_test_evidence()
        resubmitting = (
            self.state is ChangeState.CHANGES_REQUESTED and target is ChangeState.REGISTERED
        )
        if resubmitting and len(self.rounds) >= MAX_CHANGE_ROUNDS:
            raise ConflictError(
                "The change-request revision history reached its governed capacity.",
                details={"code": "CHANGE_REQUEST_ROUND_CAPACITY"},
            )
        self._record_transition(target, actor_id, reason, policy_decision_id)
        if resubmitting:
            now = utc_now()
            current_round = self._current_round()
            if current_round.closed_at is None:
                current_round.closed_at = now
            self.current_round_number += 1
            self.current_round_id = uuid7()
            self.rounds.append(
                ChangeRequestRound(
                    round_id=self.current_round_id,
                    round_number=self.current_round_number,
                    submitted_by=actor_id,
                    submitted_at=now,
                    evidence_hash=canonical_json_hash(
                        {
                            "change_request_id": str(self.change_request_id),
                            "round_number": self.current_round_number,
                            "prior_version": self.version,
                            "item_ids": [str(item.item_id) for item in self.items],
                        }
                    ),
                )
            )

    def record_test_run(
        self,
        *,
        system_id: UUID,
        attachment_id: UUID,
        state: ChangeTestRunState,
        plan_hash: str,
        result_hash: str,
        bounded_summary: dict[str, Any],
        actor_id: UUID,
        expected_version: int,
    ) -> None:
        self._check_version(expected_version)
        if len(self.test_runs) >= MAX_CHANGE_TEST_RUNS:
            raise ConflictError(
                "The change-request test history reached its governed capacity.",
                details={"code": "CHANGE_REQUEST_TEST_CAPACITY"},
            )
        if self.state is not ChangeState.TESTING:
            raise ValidationError("Test evidence is only accepted during TESTING.")
        if system_id not in self.required_system_ids():
            raise ValidationError("Test evidence must be scoped to a routed target system.")
        for name, value in (("plan_hash", plan_hash), ("result_hash", result_hash)):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValidationError(f"{name} must be a lowercase SHA-256 value.")
        if not isinstance(bounded_summary, dict) or len(str(bounded_summary)) > 8_000:
            raise ValidationError("Test evidence summary is invalid or too large.")
        self.test_runs.append(
            ChangeTestRun(
                test_run_id=uuid7(),
                round_id=self.current_round_id,
                system_id=system_id,
                attachment_id=attachment_id,
                state=state,
                plan_hash=plan_hash,
                result_hash=result_hash,
                bounded_summary=dict(bounded_summary),
                recorded_by=actor_id,
                occurred_at=utc_now(),
            )
        )
        self.version += 1
        self.events.append(
            DomainEvent.create(
                event_type="governance.change_request.test_evidence_recorded.v1",
                aggregate_type="change_request",
                aggregate_id=self.change_request_id,
                workspace_id=self.workspace_id,
                payload={
                    "round_id": str(self.current_round_id),
                    "system_id": str(system_id),
                    "attachment_id": str(attachment_id),
                    "state": state.value,
                    "plan_hash": plan_hash,
                    "result_hash": result_hash,
                    "version": self.version,
                },
            )
        )

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

    def complete_intake(
        self,
        *,
        actor_id: UUID,
        reason: str,
        policy_decision_id: UUID,
        expected_version: int,
    ) -> None:
        """Record a human-verified completion for a non-executable CR intake.

        Intake records deliberately do not claim a DataHub provider mutation.  Their
        completion is the accountable developer/steward workflow result after the
        requested change and TEST evidence have been reviewed.
        """

        self._check_version(expected_version)
        if self.state is not ChangeState.FINAL_REVIEW:
            raise ValidationError("Intake completion is only allowed during final review.")
        if any(item.target_type == "DATAHUB_ASPECT" for item in self.items):
            raise ValidationError("Executable DataHub changes require provider reconciliation.")
        self._assert_complete_final_authority()
        self._record_transition(ChangeState.COMPLETED, actor_id, reason, policy_decision_id)

    def required_system_ids(self) -> frozenset[UUID]:
        values = {item.routing_system_id or item.target_system_id for item in self.items}
        if None in values or not values:
            raise ValidationError(
                "Every change target requires a canonical system before workflow review."
            )
        return frozenset(value for value in values if value is not None)

    def _assert_complete_final_authority(self) -> None:
        if any(
            approval.stage == "FINAL" and approval.decision is ApprovalDecision.REJECTED
            for approval in self.approvals
            if approval.round_id == self.current_round_id
        ):
            raise ValidationError("A final rejection prevents completion.")
        requirements = {
            ApprovalAuthority(kind, system_id)
            for system_id in self.required_system_ids()
            for kind in (
                ApprovalAuthorityKind.SYSTEM_DEVELOPER,
                ApprovalAuthorityKind.SYSTEM_DATA_STEWARD,
            )
        }
        requirements.add(ApprovalAuthority(ApprovalAuthorityKind.GLOBAL_ADMIN))
        approved = [
            approval
            for approval in self.approvals
            if approval.round_id == self.current_round_id
            and approval.stage == "FINAL"
            and approval.decision is ApprovalDecision.APPROVED
            and approval.actor_id != self.requester_id
        ]

        def has_separated_role_assignment(
            remaining: frozenset[ApprovalAuthority],
            actor_roles: tuple[tuple[UUID, ApprovalAuthorityKind], ...],
        ) -> bool:
            if not remaining:
                return True
            requirement = min(
                remaining,
                key=lambda item: (item.kind.value, str(item.system_id)),
            )
            assigned_roles = dict(actor_roles)
            return any(
                (
                    approval.actor_id not in assigned_roles
                    or assigned_roles[approval.actor_id] is requirement.kind
                )
                and requirement in approval.authorities
                and has_separated_role_assignment(
                    remaining - {requirement},
                    tuple(
                        sorted(
                            {
                                **assigned_roles,
                                approval.actor_id: requirement.kind,
                            }.items(),
                            key=lambda item: str(item[0]),
                        )
                    ),
                )
                for approval in approved
            )

        if not has_separated_role_assignment(frozenset(requirements), ()):
            raise ValidationError(
                "Final approval requires role-separated Developer and Data Steward evidence for "
                "every target system plus one separate global administrator."
            )

    def _assert_complete_system_developer_approval(self, stage: str) -> None:
        if any(
            approval.stage == stage and approval.decision is ApprovalDecision.REJECTED
            for approval in self.approvals
            if approval.round_id == self.current_round_id
        ):
            raise ValidationError(f"A {stage.lower()} rejection prevents the next stage.")
        approved_authorities = {
            authority
            for approval in self.approvals
            if approval.round_id == self.current_round_id
            and approval.stage == stage
            and approval.decision is ApprovalDecision.APPROVED
            for authority in approval.authorities
        }
        required = {
            ApprovalAuthority(ApprovalAuthorityKind.SYSTEM_DEVELOPER, system_id)
            for system_id in self.required_system_ids()
        }
        if not required.issubset(approved_authorities):
            raise ValidationError(
                f"{stage.title()} approval requires Developer evidence for every target system."
            )

    def _record_transition(
        self,
        target: ChangeState,
        actor_id: UUID,
        reason: str,
        policy_decision_id: UUID,
    ) -> None:
        if len(self.transitions) >= MAX_CHANGE_TRANSITIONS:
            raise ConflictError(
                "The change-request transition history reached its governed capacity.",
                details={"code": "CHANGE_REQUEST_TRANSITION_CAPACITY"},
            )
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
                round_id=self.current_round_id,
            )
        )
        self.events.append(
            DomainEvent.create(
                event_type=f"governance.change_request.{target.value.lower()}.v1",
                aggregate_type="change_request",
                aggregate_id=self.change_request_id,
                workspace_id=self.workspace_id,
                payload={
                    "from": previous.value,
                    "to": target.value,
                    "round_id": str(self.current_round_id),
                    "version": self.version,
                },
            )
        )

    def _assert_complete_test_evidence(self) -> None:
        passed_system_ids = {
            test_run.system_id
            for test_run in self.test_runs
            if test_run.round_id == self.current_round_id
            and test_run.state is ChangeTestRunState.PASSED
        }
        if not self.required_system_ids().issubset(passed_system_ids):
            raise ValidationError(
                "A passed typed test result is required for every target system in this round."
            )

    def _current_round(self) -> ChangeRequestRound:
        for round_value in self.rounds:
            if round_value.round_id == self.current_round_id:
                return round_value
        raise ValidationError("The current change-request round is unavailable.")

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
