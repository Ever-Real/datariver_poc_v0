from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import IntEnum, StrEnum
from uuid import UUID

from datariver.domain.common import Effect, uuid7


class Classification(IntEnum):
    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    RESTRICTED = 3


class Action(StrEnum):
    CATALOG_SEARCH = "catalog.search"
    CATALOG_READ = "catalog.read"
    CATALOG_LINEAGE_READ = "catalog.lineage.read"
    CATALOG_SYNC = "catalog.sync"
    CATALOG_EXPORT = "catalog.export"
    REGISTRATION_CREATE = "registration.create"
    REGISTRATION_READ = "registration.read"
    REGISTRATION_VALIDATE = "registration.validate"
    CHANGE_CREATE = "change.create"
    CHANGE_READ = "change.read"
    CHANGE_EDIT = "change.edit"
    CHANGE_REVIEW = "change.review"
    CHANGE_APPROVE = "change.approve"
    CHANGE_RETRY = "change.retry"
    KG_CREATE = "kg.create"
    KG_READ = "kg.read"
    KG_EDIT = "kg.edit"
    KG_REVIEW = "kg.review"
    KG_PUBLISH = "kg.publish"
    KG_EXPORT = "kg.export"
    CHAT_QUERY = "chat.query"
    ATTACHMENT_DOWNLOAD = "attachment.download"
    SHARING_PUBLISH = "sharing.publish"
    SHARING_MANAGE = "sharing.manage"
    SHARING_INVOKE = "sharing.invoke"
    OPERATIONS_READ = "operations.read"
    OPERATIONS_RETRY = "operations.retry"
    AUDIT_READ = "audit.read"
    ADMIN_MANAGE = "admin.manage"
    RETENTION_READ = "retention.read"
    RETENTION_MANAGE = "retention.manage"
    LEGAL_HOLD_PLACE = "legal_hold.place"
    LEGAL_HOLD_RELEASE = "legal_hold.release"
    ERASURE_REQUEST = "erasure.request"
    ERASURE_APPROVE = "erasure.approve"
    ARCHIVE_READ = "archive.read"


class AuthenticationAssurance(StrEnum):
    UNKNOWN = "UNKNOWN"
    PASSWORD = "PASSWORD"  # noqa: S105 - assurance label, never credential material
    PASSWORD_REAUTH = "PASSWORD_REAUTH"  # noqa: S105 - assurance label
    OTHER_MFA = "OTHER_MFA"
    HARDWARE_WEBAUTHN = "HARDWARE_WEBAUTHN"


HIGH_RISK_ACTIONS = frozenset(
    {
        Action.CHANGE_APPROVE,
        Action.KG_PUBLISH,
        Action.SHARING_PUBLISH,
        Action.ADMIN_MANAGE,
        Action.RETENTION_MANAGE,
        Action.LEGAL_HOLD_PLACE,
        Action.LEGAL_HOLD_RELEASE,
        Action.ERASURE_REQUEST,
        Action.ERASURE_APPROVE,
    }
)

HUMAN_GOVERNANCE_ACTIONS = frozenset(
    {
        Action.RETENTION_MANAGE,
        Action.LEGAL_HOLD_PLACE,
        Action.LEGAL_HOLD_RELEASE,
        Action.ERASURE_REQUEST,
        Action.ERASURE_APPROVE,
    }
)


@dataclass(frozen=True, slots=True)
class SubjectAttributes:
    subject_id: UUID
    workspace_id: UUID
    active: bool
    department_id: UUID | None
    groups: frozenset[str]
    job_function: str | None
    clearance: Classification
    allowed_system_ids: frozenset[UUID] = field(default_factory=frozenset)
    allowed_domain_ids: frozenset[UUID] = field(default_factory=frozenset)
    allowed_actions: frozenset[Action] = field(default_factory=frozenset)
    denied_actions: frozenset[Action] = field(default_factory=frozenset)
    authentication_time: datetime | None = None
    authentication_assurance: AuthenticationAssurance = AuthenticationAssurance.UNKNOWN


@dataclass(frozen=True, slots=True)
class ResourceAttributes:
    resource_id: UUID
    workspace_id: UUID
    resource_type: str
    owner_department_id: UUID | None
    system_id: UUID | None
    domain_id: UUID | None
    classification: Classification
    lifecycle: str
    requester_id: UUID | None = None
    owner_subject_id: UUID | None = None
    active: bool = True


@dataclass(frozen=True, slots=True)
class EnvironmentAttributes:
    requested_at: datetime
    purpose: str | None = None
    network_zone: str = "unknown"
    client_type: str = "api"
    maximum_authentication_age: timedelta = timedelta(minutes=15)
    maximum_clock_skew: timedelta = timedelta(seconds=30)


@dataclass(frozen=True, slots=True)
class Decision:
    decision_id: UUID
    effect: Effect
    reason_codes: tuple[str, ...]
    policy_versions: tuple[str, ...]
    authentication_assurance: AuthenticationAssurance = AuthenticationAssurance.UNKNOWN
    authentication_time: datetime | None = None

    @property
    def allowed(self) -> bool:
        return self.effect is Effect.ALLOW


class BuiltinPolicyEngine:
    """Deterministic baseline ABAC. An OPA adapter may add denies, never bypass these guards."""

    policy_version = "builtin-abac-v2"

    def decide(
        self,
        *,
        subject: SubjectAttributes,
        resource: ResourceAttributes,
        action: Action,
        environment: EnvironmentAttributes,
    ) -> Decision:
        reasons: list[str] = []

        if not subject.active:
            reasons.append("SUBJECT_INACTIVE")
        if not resource.active:
            reasons.append("RESOURCE_INACTIVE")
        if subject.workspace_id != resource.workspace_id:
            reasons.append("WORKSPACE_MISMATCH")
        if action in subject.denied_actions:
            reasons.append("EXPLICIT_ACTION_DENY")
        if action not in subject.allowed_actions:
            reasons.append("ACTION_NOT_GRANTED")
        if resource.classification > subject.clearance:
            reasons.append("CLEARANCE_INSUFFICIENT")
        if action is Action.CATALOG_EXPORT and resource.classification is Classification.RESTRICTED:
            reasons.append("RESTRICTED_EXPORT_DENIED")
        if resource.system_id is not None and resource.system_id not in subject.allowed_system_ids:
            reasons.append("SYSTEM_SCOPE_MISMATCH")
        if resource.domain_id is not None and resource.domain_id not in subject.allowed_domain_ids:
            reasons.append("DOMAIN_SCOPE_MISMATCH")
        if action is Action.CHANGE_APPROVE and resource.requester_id == subject.subject_id:
            reasons.append("SELF_APPROVAL_FORBIDDEN")
        if (
            resource.owner_subject_id is not None
            and resource.owner_subject_id != subject.subject_id
            and "security-administrators" not in subject.groups
        ):
            reasons.append("OWNER_SCOPE_MISMATCH")
        if action in HIGH_RISK_ACTIONS:
            if subject.authentication_assurance is not AuthenticationAssurance.HARDWARE_WEBAUTHN:
                reasons.append("PHISHING_RESISTANT_AUTH_REQUIRED")
            if subject.authentication_time is None:
                reasons.append("AUTHENTICATION_TIME_REQUIRED")
            elif subject.authentication_time > (
                environment.requested_at + environment.maximum_clock_skew
            ):
                reasons.append("AUTHENTICATION_TIME_INVALID")
            elif (
                environment.requested_at - subject.authentication_time
                > environment.maximum_authentication_age
            ):
                reasons.append("AUTHENTICATION_TOO_OLD")
        if action in HUMAN_GOVERNANCE_ACTIONS and (
            subject.job_function == "SERVICE_ACCOUNT" or "service-accounts" in subject.groups
        ):
            reasons.append("HUMAN_ACTOR_REQUIRED")

        effect = Effect.DENY if reasons else Effect.ALLOW
        return Decision(
            decision_id=uuid7(),
            effect=effect,
            reason_codes=tuple(reasons or ["POLICY_ALLOW"]),
            policy_versions=(self.policy_version,),
            authentication_assurance=subject.authentication_assurance,
            authentication_time=subject.authentication_time,
        )
