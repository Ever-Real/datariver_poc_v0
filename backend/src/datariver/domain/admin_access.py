from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from datariver.domain.authz import Action, Classification
from datariver.domain.common import (
    ConflictError,
    DomainEvent,
    ValidationError,
    canonical_json_hash,
    uuid7,
)

MEMBERSHIP_ACCESS_COMMAND = "WORKSPACE_MEMBERSHIP_ACCESS_UPDATE_V1"
SYSTEM_ASSIGNMENT_UPDATE_COMMAND = "SYSTEM_ASSIGNMENT_UPDATE_V1"
MAXIMUM_FALLBACK_LIFETIME = timedelta(minutes=5)
_GROUP_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,99}$")
_COMMAND_KEYS = {
    "command_type",
    "workspace_id",
    "target_subject_id",
    "expected_membership_version",
    "access",
}
_ACCESS_KEYS = {
    "active",
    "clearance",
    "groups",
    "allowed_actions",
    "denied_actions",
    "allowed_system_ids",
    "allowed_domain_ids",
}


class AdminAccessRequestState(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CONSUMED = "CONSUMED"


class AdminFallbackStage(StrEnum):
    READ = "admin.fallback.read"
    REQUEST = "admin.fallback.request"
    APPROVE = "admin.fallback.approve"
    CONSUME = "admin.fallback.consume"


class AdminOperation(StrEnum):
    MEMBERSHIP_ACCESS_READ = "MEMBERSHIP_ACCESS_READ"
    MEMBERSHIP_ACCESS_UPDATE = "MEMBERSHIP_ACCESS_UPDATE"
    SYSTEM_ASSIGNMENT_UPDATE = "SYSTEM_ASSIGNMENT_UPDATE"
    FALLBACK_REQUEST_READ = "FALLBACK_REQUEST_READ"
    FALLBACK_REQUEST_CREATE = "FALLBACK_REQUEST_CREATE"
    FALLBACK_REQUEST_DECIDE = "FALLBACK_REQUEST_DECIDE"
    FALLBACK_REQUEST_CONSUME = "FALLBACK_REQUEST_CONSUME"
    CLASSIFICATION_POLICY_READ = "CLASSIFICATION_POLICY_READ"
    CLASSIFICATION_POLICY_PROPOSE = "CLASSIFICATION_POLICY_PROPOSE"
    CLASSIFICATION_POLICY_DECIDE = "CLASSIFICATION_POLICY_DECIDE"
    INFERENCE_PROVIDER_PROFILE_READ = "INFERENCE_PROVIDER_PROFILE_READ"
    INFERENCE_PROVIDER_PROFILE_DECIDE = "INFERENCE_PROVIDER_PROFILE_DECIDE"
    INFERENCE_PROVIDER_PROFILE_REVOKE = "INFERENCE_PROVIDER_PROFILE_REVOKE"
    RESTRICTED_SEARCH_GRANT_READ = "RESTRICTED_SEARCH_GRANT_READ"
    RESTRICTED_SEARCH_GRANT_PROPOSE = "RESTRICTED_SEARCH_GRANT_PROPOSE"
    RESTRICTED_SEARCH_GRANT_DECIDE = "RESTRICTED_SEARCH_GRANT_DECIDE"
    RESTRICTED_SEARCH_GRANT_REVOKE = "RESTRICTED_SEARCH_GRANT_REVOKE"
    RETENTION_POLICY_READ = "RETENTION_POLICY_READ"
    RETENTION_POLICY_MANAGE = "RETENTION_POLICY_MANAGE"
    LEGAL_HOLD_READ = "LEGAL_HOLD_READ"
    LEGAL_HOLD_PLACE = "LEGAL_HOLD_PLACE"
    LEGAL_HOLD_RELEASE = "LEGAL_HOLD_RELEASE"
    ERASURE_READ = "ERASURE_READ"
    ERASURE_REQUEST = "ERASURE_REQUEST"
    ERASURE_APPROVE = "ERASURE_APPROVE"


class AdminAccessDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class MembershipAccessUpdate:
    workspace_id: UUID
    target_subject_id: UUID
    expected_membership_version: int
    active: bool
    clearance: Classification
    groups: frozenset[str]
    allowed_actions: frozenset[Action]
    denied_actions: frozenset[Action]
    allowed_system_ids: frozenset[UUID] = frozenset()
    allowed_domain_ids: frozenset[UUID] = frozenset()

    def __post_init__(self) -> None:
        if self.expected_membership_version < 1:
            raise ValidationError("The expected membership version must be positive.")
        if len(self.groups) > 100 or any(
            not _GROUP_PATTERN.fullmatch(group) for group in self.groups
        ):
            raise ValidationError("Membership groups must use bounded lowercase identifiers.")
        if self.allowed_actions & self.denied_actions:
            raise ValidationError("An action cannot be both allowed and denied.")
        if len(self.allowed_actions) + len(self.denied_actions) > len(Action):
            raise ValidationError("The membership action set is invalid.")
        if len(self.allowed_system_ids) > 1000 or len(self.allowed_domain_ids) > 1000:
            raise ValidationError("Membership resource scopes exceed the supported bound.")

    def access_document(self) -> dict[str, object]:
        return {
            "active": self.active,
            "clearance": self.clearance.name,
            "groups": sorted(self.groups),
            "allowed_actions": sorted(action.value for action in self.allowed_actions),
            "denied_actions": sorted(action.value for action in self.denied_actions),
            "allowed_system_ids": sorted(str(value) for value in self.allowed_system_ids),
            "allowed_domain_ids": sorted(str(value) for value in self.allowed_domain_ids),
        }

    def command_document(self) -> dict[str, object]:
        return {
            "command_type": MEMBERSHIP_ACCESS_COMMAND,
            "workspace_id": str(self.workspace_id),
            "target_subject_id": str(self.target_subject_id),
            "expected_membership_version": self.expected_membership_version,
            "access": self.access_document(),
        }

    @property
    def payload_hash(self) -> str:
        return canonical_json_hash(self.command_document())

    @classmethod
    def from_command_document(cls, document: dict[str, object]) -> MembershipAccessUpdate:
        if (
            set(document) != _COMMAND_KEYS
            or document.get("command_type") != MEMBERSHIP_ACCESS_COMMAND
        ):
            raise ValidationError("The admin access command type is unsupported.")
        access = document.get("access")
        if not isinstance(access, dict) or set(access) != _ACCESS_KEYS:
            raise ValidationError("The admin access command document is invalid.")
        try:
            return cls(
                workspace_id=UUID(str(document["workspace_id"])),
                target_subject_id=UUID(str(document["target_subject_id"])),
                expected_membership_version=int(str(document["expected_membership_version"])),
                active=_required_bool(access, "active"),
                clearance=Classification[str(access["clearance"])],
                groups=frozenset(_required_strings(access, "groups")),
                allowed_actions=frozenset(
                    Action(value) for value in _required_strings(access, "allowed_actions")
                ),
                denied_actions=frozenset(
                    Action(value) for value in _required_strings(access, "denied_actions")
                ),
                allowed_system_ids=frozenset(
                    UUID(value) for value in _required_strings(access, "allowed_system_ids")
                ),
                allowed_domain_ids=frozenset(
                    UUID(value) for value in _required_strings(access, "allowed_domain_ids")
                ),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValidationError("The admin access command document is invalid.") from error


@dataclass(frozen=True, slots=True)
class SystemAssigneeUpdate:
    subject_id: UUID
    responsibility: str
    priority: int

    def __post_init__(self) -> None:
        if self.responsibility not in {"DEVELOPER", "DATA_STEWARD"}:
            raise ValidationError("The system-assignee responsibility is invalid.")
        if not 1 <= self.priority <= 999:
            raise ValidationError("The system-assignee priority must be between 1 and 999.")

    def document(self) -> dict[str, object]:
        return {
            "subject_id": str(self.subject_id),
            "responsibility": self.responsibility,
            "priority": self.priority,
        }


@dataclass(frozen=True, slots=True)
class SystemAssigneeUpdateCommand:
    workspace_id: UUID
    system_id: UUID
    expected_system_version: int
    assignees: tuple[SystemAssigneeUpdate, ...]

    def __post_init__(self) -> None:
        if self.expected_system_version < 1:
            raise ValidationError("The expected system version must be positive.")
        if not self.assignees or len(self.assignees) > 500:
            raise ValidationError("System assignees must contain between one and 500 entries.")
        keys = {(item.subject_id, item.responsibility) for item in self.assignees}
        if len(keys) != len(self.assignees):
            raise ValidationError("A system responsibility can be assigned to a subject only once.")
        for responsibility in ("DEVELOPER", "DATA_STEWARD"):
            priorities = [
                item.priority for item in self.assignees if item.responsibility == responsibility
            ]
            if not priorities:
                raise ValidationError(
                    "Every system must retain at least one Developer and one Data Steward."
                )
            if min(priorities) != 1 or len(priorities) != len(set(priorities)):
                raise ValidationError(
                    "System-assignee priorities must be unique and start with priority 1."
                )

    def command_document(self) -> dict[str, object]:
        return {
            "command_type": SYSTEM_ASSIGNMENT_UPDATE_COMMAND,
            "workspace_id": str(self.workspace_id),
            "system_id": str(self.system_id),
            "expected_system_version": self.expected_system_version,
            "assignees": [
                item.document()
                for item in sorted(
                    self.assignees,
                    key=lambda item: (item.responsibility, item.priority, str(item.subject_id)),
                )
            ],
        }

    @property
    def payload_hash(self) -> str:
        return canonical_json_hash(self.command_document())


@dataclass(frozen=True, slots=True)
class AdminAccessApproval:
    approval_id: UUID
    decision: AdminAccessDecision
    actor_id: UUID
    reason: str
    policy_decision_id: UUID
    payload_hash: str
    request_version: int
    occurred_at: datetime


@dataclass(slots=True)
class AdminAccessRequest:
    access_request_id: UUID
    workspace_id: UUID
    requester_id: UUID
    request_reason: str
    request_policy_decision_id: UUID
    command: MembershipAccessUpdate
    payload_hash: str
    expires_at: datetime
    state: AdminAccessRequestState = AdminAccessRequestState.PENDING
    version: int = 1
    approvals: list[AdminAccessApproval] = field(default_factory=list)
    checker_id: UUID | None = None
    consumed_by: UUID | None = None
    consumed_at: datetime | None = None
    consume_policy_decision_id: UUID | None = None
    events: list[DomainEvent] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        *,
        requester_id: UUID,
        reason: str,
        policy_decision_id: UUID,
        command: MembershipAccessUpdate,
        now: datetime,
        expires_at: datetime,
    ) -> AdminAccessRequest:
        if requester_id == command.target_subject_id:
            raise ValidationError("An administrator cannot request a change to their own access.")
        cleaned_reason = reason.strip()
        if not cleaned_reason:
            raise ValidationError("A fallback request reason is required.")
        if expires_at <= now or expires_at - now > MAXIMUM_FALLBACK_LIFETIME:
            raise ValidationError("A fallback request must expire within five minutes.")
        request = cls(
            access_request_id=uuid7(),
            workspace_id=command.workspace_id,
            requester_id=requester_id,
            request_reason=cleaned_reason,
            request_policy_decision_id=policy_decision_id,
            command=command,
            payload_hash=command.payload_hash,
            expires_at=expires_at,
        )
        request.events.append(
            DomainEvent.create(
                event_type="iam.admin_access_request.created.v1",
                aggregate_type="admin_access_request",
                aggregate_id=request.access_request_id,
                workspace_id=request.workspace_id,
                payload={
                    "command_type": MEMBERSHIP_ACCESS_COMMAND,
                    "target_subject_id": str(command.target_subject_id),
                    "payload_hash": request.payload_hash,
                    "version": request.version,
                },
            )
        )
        return request

    def decide(
        self,
        *,
        decision: AdminAccessDecision,
        actor_id: UUID,
        reason: str,
        policy_decision_id: UUID,
        expected_version: int,
        now: datetime,
    ) -> None:
        self._check_version(expected_version)
        if self.state is not AdminAccessRequestState.PENDING:
            raise ConflictError("The fallback request has already been decided.")
        self._check_not_expired(now)
        if actor_id == self.requester_id:
            raise ValidationError("The request maker cannot be its checker.")
        if actor_id == self.command.target_subject_id:
            raise ValidationError("The target subject cannot check their own access change.")
        cleaned_reason = reason.strip()
        if not cleaned_reason:
            raise ValidationError("An approval reason is required.")
        if self.command.payload_hash != self.payload_hash:
            raise ConflictError("The fallback request payload no longer matches its approval hash.")
        self.version += 1
        self.state = (
            AdminAccessRequestState.APPROVED
            if decision is AdminAccessDecision.APPROVED
            else AdminAccessRequestState.REJECTED
        )
        self.checker_id = actor_id
        self.approvals.append(
            AdminAccessApproval(
                approval_id=uuid7(),
                decision=decision,
                actor_id=actor_id,
                reason=cleaned_reason,
                policy_decision_id=policy_decision_id,
                payload_hash=self.payload_hash,
                request_version=self.version,
                occurred_at=now,
            )
        )
        self.events.append(
            DomainEvent.create(
                event_type=f"iam.admin_access_request.{decision.value.lower()}.v1",
                aggregate_type="admin_access_request",
                aggregate_id=self.access_request_id,
                workspace_id=self.workspace_id,
                payload={
                    "checker_id": str(actor_id),
                    "payload_hash": self.payload_hash,
                    "version": self.version,
                },
            )
        )

    def consume(
        self,
        *,
        actor_id: UUID,
        policy_decision_id: UUID,
        expected_version: int,
        now: datetime,
    ) -> None:
        self._check_version(expected_version)
        if self.state is not AdminAccessRequestState.APPROVED:
            raise ConflictError("Only an approved fallback request can be consumed.")
        self._check_not_expired(now)
        if actor_id != self.requester_id:
            raise ValidationError("Only the original request maker can consume the approval.")
        if self.checker_id is None or self.checker_id == actor_id:
            raise ValidationError("An independent checker approval is required.")
        if self.command.payload_hash != self.payload_hash:
            raise ConflictError("The approved payload hash does not match the command.")
        self.state = AdminAccessRequestState.CONSUMED
        self.consumed_by = actor_id
        self.consumed_at = now
        self.consume_policy_decision_id = policy_decision_id
        self.version += 1
        self.events.append(
            DomainEvent.create(
                event_type="iam.admin_access_request.consumed.v1",
                aggregate_type="admin_access_request",
                aggregate_id=self.access_request_id,
                workspace_id=self.workspace_id,
                payload={
                    "consumer_id": str(actor_id),
                    "target_subject_id": str(self.command.target_subject_id),
                    "payload_hash": self.payload_hash,
                    "version": self.version,
                },
            )
        )

    def _check_not_expired(self, now: datetime) -> None:
        if now >= self.expires_at:
            raise ConflictError("The fallback request has expired.")

    def _check_version(self, expected_version: int) -> None:
        if expected_version != self.version:
            raise ConflictError(
                "The fallback request was modified by another operation.",
                details={"expected": expected_version, "actual": self.version},
            )


def _required_strings(document: dict[object, object], key: str) -> tuple[str, ...]:
    value = document.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValidationError("The admin access command document is invalid.")
    return tuple(value)


def _required_bool(document: dict[object, object], key: str) -> bool:
    value = document.get(key)
    if not isinstance(value, bool):
        raise ValidationError("The admin access command document is invalid.")
    return value
