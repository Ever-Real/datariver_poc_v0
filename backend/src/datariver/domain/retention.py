from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from datariver.domain.authz import Classification
from datariver.domain.common import (
    ConflictError,
    DomainEvent,
    ValidationError,
    canonical_json_hash,
    uuid7,
)

_TEXT_LIMIT = 4000
_PARTITION_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,49}_[0-9]{4}_[0-9]{2}$")
_BUCKET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
AUTOMATION_DISABLED = "DISABLED_NOT_READY"
MAXIMUM_ERASURE_REVIEW_LIFETIME = timedelta(days=7)


class RetentionPolicyState(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class GovernanceDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RetentionDataClass(StrEnum):
    COMPLETED_OPERATIONS = "COMPLETED_OPERATIONS"
    CHAT_CONTENT = "CHAT_CONTENT"
    AUDIT_EVIDENCE = "AUDIT_EVIDENCE"
    OBJECT_DATA = "OBJECT_DATA"


class LegalHoldScope(StrEnum):
    WORKSPACE = "WORKSPACE"
    SUBJECT = "SUBJECT"
    RESOURCE = "RESOURCE"


class LegalHoldState(StrEnum):
    ACTIVE = "ACTIVE"
    RELEASE_REQUESTED = "RELEASE_REQUESTED"
    RELEASE_REJECTED = "RELEASE_REJECTED"
    RELEASED = "RELEASED"


class ErasureTargetType(StrEnum):
    SUBJECT_DATA = "SUBJECT_DATA"
    CHAT_SESSION = "CHAT_SESSION"
    UPLOAD_OBJECT = "UPLOAD_OBJECT"


class ErasureRequestState(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ArchiveSource(StrEnum):
    OUTBOX_EVENTS = "OUTBOX_EVENTS"
    INBOX_MESSAGES = "INBOX_MESSAGES"
    POLICY_DECISIONS = "POLICY_DECISIONS"
    CHAT_MESSAGES = "CHAT_MESSAGES"
    ASSISTANT_RUNS = "ASSISTANT_RUNS"


class ArchiveRetentionMode(StrEnum):
    COMPLIANCE = "COMPLIANCE"


@dataclass(frozen=True, slots=True)
class ArchiveCapability:
    configuration_fingerprint: str
    observed_at: datetime
    expires_at: datetime
    versioning_enabled: bool
    object_lock_enabled: bool
    compliance_retention_supported: bool
    checksum_sha256_supported: bool
    full_readback_verified: bool
    retention_shorten_denied: bool
    retained_version_delete_denied: bool

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", self.configuration_fingerprint):
            raise ValidationError("The archive capability fingerprint is invalid.")
        _require_aware_datetime(self.observed_at, "archive capability observation")
        _require_aware_datetime(self.expires_at, "archive capability expiry")
        if self.expires_at <= self.observed_at:
            raise ValidationError(
                "The archive capability attestation must expire after observation."
            )

    def assert_usable(self, *, now: datetime) -> None:
        _require_aware_datetime(now, "archive capability evaluation")
        if now >= self.expires_at:
            raise ConflictError("The archive capability attestation has expired.")
        checks = (
            self.versioning_enabled,
            self.object_lock_enabled,
            self.compliance_retention_supported,
            self.checksum_sha256_supported,
            self.full_readback_verified,
            self.retention_shorten_denied,
            self.retained_version_delete_denied,
        )
        if not all(checks):
            raise ConflictError("The immutable archive capability is not verified.")


@dataclass(frozen=True, slots=True)
class ArchiveWriteReceipt:
    object_bucket: str
    object_key: str
    object_version_id: str
    byte_count: int
    content_sha256: str
    provider_checksum: str
    retention_mode: ArchiveRetentionMode
    retention_until: datetime
    legal_hold: bool
    observed_at: datetime

    def __post_init__(self) -> None:
        _validate_archive_object_location(
            bucket=self.object_bucket,
            object_key=self.object_key,
            object_version_id=self.object_version_id,
        )
        _validate_archive_content(
            byte_count=self.byte_count,
            content_sha256=self.content_sha256,
            provider_checksum=self.provider_checksum,
        )
        _validate_compliance_retention(
            retention_mode=self.retention_mode,
            retention_until=self.retention_until,
            observed_at=self.observed_at,
        )


@dataclass(frozen=True, slots=True)
class ArchiveRetentionObservation:
    retention_mode: ArchiveRetentionMode
    retention_until: datetime
    legal_hold: bool
    observed_at: datetime

    def __post_init__(self) -> None:
        _validate_compliance_retention(
            retention_mode=self.retention_mode,
            retention_until=self.retention_until,
            observed_at=self.observed_at,
        )


@dataclass(frozen=True, slots=True)
class RetentionRules:
    completed_operation_days: int
    chat_content_days: int
    audit_online_months: int
    immutable_archive_years: int

    def __post_init__(self) -> None:
        bounds = (
            (self.completed_operation_days, 1, 3650),
            (self.chat_content_days, 1, 3650),
            (self.audit_online_months, 1, 120),
            (self.immutable_archive_years, 1, 100),
        )
        if any(not lower <= value <= upper for value, lower, upper in bounds):
            raise ValidationError("Retention rules are outside the supported bounds.")

    def document(self) -> dict[str, object]:
        return {
            "completed_operation_days": self.completed_operation_days,
            "chat_content_days": self.chat_content_days,
            "audit_online_months": self.audit_online_months,
            "immutable_archive_years": self.immutable_archive_years,
        }


@dataclass(slots=True)
class RetentionPolicyVersion:
    policy_id: UUID
    workspace_id: UUID
    policy_number: int
    rules: RetentionRules
    payload_hash: str
    requester_id: UUID
    request_reason: str
    request_policy_decision_id: UUID
    state: RetentionPolicyState = RetentionPolicyState.DRAFT
    checker_id: UUID | None = None
    decision_reason: str | None = None
    decision_policy_decision_id: UUID | None = None
    decided_at: datetime | None = None
    version: int = 1
    events: list[DomainEvent] = field(default_factory=list)

    @classmethod
    def propose(
        cls,
        *,
        workspace_id: UUID,
        policy_number: int,
        rules: RetentionRules,
        requester_id: UUID,
        reason: str,
        policy_decision_id: UUID,
    ) -> RetentionPolicyVersion:
        if policy_number < 1:
            raise ValidationError("The retention policy number must be positive.")
        cleaned_reason = _required_reason(reason, "A retention policy reason is required.")
        policy = cls(
            policy_id=uuid7(),
            workspace_id=workspace_id,
            policy_number=policy_number,
            rules=rules,
            payload_hash=canonical_json_hash(rules.document()),
            requester_id=requester_id,
            request_reason=cleaned_reason,
            request_policy_decision_id=policy_decision_id,
        )
        policy.events.append(
            _event(
                event_type="governance.retention_policy.proposed.v1",
                aggregate_type="retention_policy",
                aggregate_id=policy.policy_id,
                workspace_id=workspace_id,
                payload={
                    "policy_number": policy_number,
                    "payload_hash": policy.payload_hash,
                    "version": policy.version,
                },
            )
        )
        return policy

    def decide(
        self,
        *,
        decision: GovernanceDecision,
        actor_id: UUID,
        reason: str,
        policy_decision_id: UUID,
        expected_version: int,
        now: datetime,
    ) -> None:
        self._check_version(expected_version)
        if self.state is not RetentionPolicyState.DRAFT:
            raise ConflictError("The retention policy proposal has already been decided.")
        if actor_id == self.requester_id:
            raise ValidationError("The retention policy maker cannot be its checker.")
        if canonical_json_hash(self.rules.document()) != self.payload_hash:
            raise ConflictError("The retention policy payload failed its integrity check.")
        cleaned_reason = _required_reason(reason, "A policy decision reason is required.")
        self.state = (
            RetentionPolicyState.ACTIVE
            if decision is GovernanceDecision.APPROVED
            else RetentionPolicyState.REJECTED
        )
        self.checker_id = actor_id
        self.decision_reason = cleaned_reason
        self.decision_policy_decision_id = policy_decision_id
        self.decided_at = now
        self.version += 1
        self.events.append(
            _event(
                event_type=f"governance.retention_policy.{decision.value.lower()}.v1",
                aggregate_type="retention_policy",
                aggregate_id=self.policy_id,
                workspace_id=self.workspace_id,
                payload={
                    "policy_number": self.policy_number,
                    "payload_hash": self.payload_hash,
                    "checker_id": str(actor_id),
                    "version": self.version,
                },
            )
        )

    def supersede(self) -> None:
        if self.state is not RetentionPolicyState.ACTIVE:
            raise ConflictError("Only an active retention policy can be superseded.")
        self.state = RetentionPolicyState.SUPERSEDED
        self.version += 1

    def _check_version(self, expected_version: int) -> None:
        if expected_version != self.version:
            raise ConflictError(
                "The retention policy was modified by another operation.",
                details={"expected": expected_version, "actual": self.version},
            )


@dataclass(slots=True)
class LegalHold:
    hold_id: UUID
    workspace_id: UUID
    data_class: RetentionDataClass
    scope: LegalHoldScope
    scope_id: UUID | None
    reason: str
    created_by: UUID
    create_policy_decision_id: UUID
    state: LegalHoldState = LegalHoldState.ACTIVE
    release_requested_by: UUID | None = None
    release_request_reason: str | None = None
    release_request_policy_decision_id: UUID | None = None
    release_checker_id: UUID | None = None
    release_decision_reason: str | None = None
    release_decision_policy_decision_id: UUID | None = None
    released_at: datetime | None = None
    version: int = 1
    events: list[DomainEvent] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        *,
        workspace_id: UUID,
        data_class: RetentionDataClass,
        scope: LegalHoldScope,
        scope_id: UUID | None,
        reason: str,
        actor_id: UUID,
        policy_decision_id: UUID,
    ) -> LegalHold:
        _validate_hold_scope(scope, scope_id)
        hold = cls(
            hold_id=uuid7(),
            workspace_id=workspace_id,
            data_class=data_class,
            scope=scope,
            scope_id=scope_id,
            reason=_required_reason(reason, "A Legal Hold reason is required."),
            created_by=actor_id,
            create_policy_decision_id=policy_decision_id,
        )
        hold.events.append(hold._event("created", actor_id))
        return hold

    @property
    def active(self) -> bool:
        return self.state is not LegalHoldState.RELEASED

    def request_release(
        self,
        *,
        actor_id: UUID,
        reason: str,
        policy_decision_id: UUID,
        expected_version: int,
    ) -> None:
        self._check_version(expected_version)
        if self.state not in {LegalHoldState.ACTIVE, LegalHoldState.RELEASE_REJECTED}:
            raise ConflictError("The Legal Hold cannot enter release review.")
        cleaned_reason = _required_reason(reason, "A Legal Hold release reason is required.")
        self.state = LegalHoldState.RELEASE_REQUESTED
        self.release_requested_by = actor_id
        self.release_request_reason = cleaned_reason
        self.release_request_policy_decision_id = policy_decision_id
        self.release_checker_id = None
        self.release_decision_reason = None
        self.release_decision_policy_decision_id = None
        self.version += 1
        self.events.append(self._event("release_requested", actor_id))

    def decide_release(
        self,
        *,
        decision: GovernanceDecision,
        actor_id: UUID,
        reason: str,
        policy_decision_id: UUID,
        expected_version: int,
        now: datetime,
    ) -> None:
        self._check_version(expected_version)
        if self.state is not LegalHoldState.RELEASE_REQUESTED:
            raise ConflictError("The Legal Hold has no release request awaiting review.")
        if self.release_requested_by == actor_id:
            raise ValidationError("The Legal Hold release maker cannot be its checker.")
        if self.scope is LegalHoldScope.SUBJECT and self.scope_id == actor_id:
            raise ValidationError("A subject cannot release a Legal Hold on their own data.")
        cleaned_reason = _required_reason(
            reason, "A Legal Hold release decision reason is required."
        )
        self.state = (
            LegalHoldState.RELEASED
            if decision is GovernanceDecision.APPROVED
            else LegalHoldState.RELEASE_REJECTED
        )
        self.release_checker_id = actor_id
        self.release_decision_reason = cleaned_reason
        self.release_decision_policy_decision_id = policy_decision_id
        self.released_at = now if decision is GovernanceDecision.APPROVED else None
        self.version += 1
        self.events.append(self._event(f"release_{decision.value.lower()}", actor_id))

    def _check_version(self, expected_version: int) -> None:
        if expected_version != self.version:
            raise ConflictError(
                "The Legal Hold was modified by another operation.",
                details={"expected": expected_version, "actual": self.version},
            )

    def _event(self, action: str, actor_id: UUID) -> DomainEvent:
        return _event(
            event_type=f"governance.legal_hold.{action}.v1",
            aggregate_type="legal_hold",
            aggregate_id=self.hold_id,
            workspace_id=self.workspace_id,
            payload={
                "data_class": self.data_class.value,
                "scope": self.scope.value,
                "scope_id": str(self.scope_id) if self.scope_id else None,
                "actor_id": str(actor_id),
                "version": self.version,
            },
        )


@dataclass(slots=True)
class ErasureRequest:
    erasure_request_id: UUID
    workspace_id: UUID
    target_type: ErasureTargetType
    target_id: UUID
    target_version: int
    target_owner_id: UUID | None
    classification: Classification
    retention_policy_id: UUID
    requester_id: UUID
    request_reason: str
    request_policy_decision_id: UUID
    payload_hash: str
    expires_at: datetime
    state: ErasureRequestState = ErasureRequestState.PENDING
    checker_id: UUID | None = None
    decision_reason: str | None = None
    decision_policy_decision_id: UUID | None = None
    decided_at: datetime | None = None
    version: int = 1
    events: list[DomainEvent] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        *,
        workspace_id: UUID,
        target_type: ErasureTargetType,
        target_id: UUID,
        target_version: int,
        target_owner_id: UUID | None,
        classification: Classification,
        retention_policy_id: UUID,
        requester_id: UUID,
        reason: str,
        policy_decision_id: UUID,
        now: datetime,
        expires_at: datetime,
    ) -> ErasureRequest:
        _require_aware_datetime(now, "erasure request creation")
        _require_aware_datetime(expires_at, "erasure request expiry")
        if target_version < 1:
            raise ValidationError("The erasure target version must be positive.")
        if expires_at <= now or expires_at - now > MAXIMUM_ERASURE_REVIEW_LIFETIME:
            raise ValidationError("An erasure request must expire within seven days.")
        document = {
            "workspace_id": str(workspace_id),
            "target_type": target_type.value,
            "target_id": str(target_id),
            "target_version": target_version,
            "target_owner_id": str(target_owner_id) if target_owner_id else None,
            "classification": classification.name,
            "retention_policy_id": str(retention_policy_id),
            "requester_id": str(requester_id),
            "expires_at": expires_at.isoformat(),
        }
        request = cls(
            erasure_request_id=uuid7(),
            workspace_id=workspace_id,
            target_type=target_type,
            target_id=target_id,
            target_version=target_version,
            target_owner_id=target_owner_id,
            classification=classification,
            retention_policy_id=retention_policy_id,
            requester_id=requester_id,
            request_reason=_required_reason(reason, "An erasure request reason is required."),
            request_policy_decision_id=policy_decision_id,
            payload_hash=canonical_json_hash(document),
            expires_at=expires_at,
        )
        request.events.append(request._event("created", requester_id))
        return request

    @property
    def execution_state(self) -> str:
        return AUTOMATION_DISABLED

    def decide(
        self,
        *,
        decision: GovernanceDecision,
        actor_id: UUID,
        reason: str,
        policy_decision_id: UUID,
        expected_version: int,
        now: datetime,
        active_legal_hold: bool,
        current_target_version: int,
        active_retention_policy_id: UUID,
    ) -> None:
        _require_aware_datetime(now, "erasure decision")
        if expected_version != self.version:
            raise ConflictError(
                "The erasure request was modified by another operation.",
                details={"expected": expected_version, "actual": self.version},
            )
        if self.state is not ErasureRequestState.PENDING:
            raise ConflictError("The erasure request has already been decided.")
        if now >= self.expires_at:
            raise ConflictError("The erasure request has expired.")
        if actor_id == self.requester_id:
            raise ValidationError("The erasure request maker cannot be its checker.")
        if actor_id == self.target_owner_id or (
            self.target_type is ErasureTargetType.SUBJECT_DATA and actor_id == self.target_id
        ):
            raise ValidationError("A subject cannot approve erasure of their own data.")
        if current_target_version != self.target_version:
            raise ConflictError("The erasure target changed after the request was created.")
        if active_retention_policy_id != self.retention_policy_id:
            raise ConflictError(
                "The active retention policy changed after the request was created."
            )
        if decision is GovernanceDecision.APPROVED and active_legal_hold:
            raise ConflictError("An active Legal Hold blocks erasure approval.")
        cleaned_reason = _required_reason(reason, "An erasure decision reason is required.")
        self.state = (
            ErasureRequestState.APPROVED
            if decision is GovernanceDecision.APPROVED
            else ErasureRequestState.REJECTED
        )
        self.checker_id = actor_id
        self.decision_reason = cleaned_reason
        self.decision_policy_decision_id = policy_decision_id
        self.decided_at = now
        self.version += 1
        self.events.append(self._event(decision.value.lower(), actor_id))

    def _event(self, action: str, actor_id: UUID) -> DomainEvent:
        return _event(
            event_type=f"governance.erasure_request.{action}.v1",
            aggregate_type="erasure_request",
            aggregate_id=self.erasure_request_id,
            workspace_id=self.workspace_id,
            payload={
                "target_type": self.target_type.value,
                "target_id": str(self.target_id),
                "target_version": self.target_version,
                "classification": self.classification.name,
                "retention_policy_id": str(self.retention_policy_id),
                "payload_hash": self.payload_hash,
                "actor_id": str(actor_id),
                "execution_state": AUTOMATION_DISABLED,
                "version": self.version,
            },
        )


@dataclass(frozen=True, slots=True)
class ImmutableArchiveReceipt:
    receipt_id: UUID
    workspace_id: UUID
    source: ArchiveSource
    source_partition: str
    row_count: int
    byte_count: int
    content_sha256: str
    provider_checksum: str
    object_bucket: str
    object_key: str
    object_version_id: str
    retention_mode: ArchiveRetentionMode
    retention_until: datetime
    legal_hold: bool
    verified_at: datetime
    capability_fingerprint: str

    def __post_init__(self) -> None:
        if not _PARTITION_PATTERN.fullmatch(self.source_partition):
            raise ValidationError("The archive source partition name is invalid.")
        if self.row_count < 1:
            raise ValidationError("An immutable archive receipt must cover at least one row.")
        _validate_archive_object_location(
            bucket=self.object_bucket,
            object_key=self.object_key,
            object_version_id=self.object_version_id,
        )
        _validate_archive_content(
            byte_count=self.byte_count,
            content_sha256=self.content_sha256,
            provider_checksum=self.provider_checksum,
        )
        _validate_compliance_retention(
            retention_mode=self.retention_mode,
            retention_until=self.retention_until,
            observed_at=self.verified_at,
        )
        if not re.fullmatch(r"[0-9a-f]{64}", self.capability_fingerprint):
            raise ValidationError("The archive capability fingerprint is invalid.")


def _required_reason(reason: str, message: str) -> str:
    cleaned = reason.strip()
    if not cleaned or len(cleaned) > _TEXT_LIMIT:
        raise ValidationError(message)
    return cleaned


def _validate_hold_scope(scope: LegalHoldScope, scope_id: UUID | None) -> None:
    if (scope is LegalHoldScope.WORKSPACE and scope_id is not None) or (
        scope is not LegalHoldScope.WORKSPACE and scope_id is None
    ):
        raise ValidationError("The Legal Hold scope and identifier do not match.")


def _validate_archive_object_location(
    *, bucket: str, object_key: str, object_version_id: str
) -> None:
    if not _BUCKET_PATTERN.fullmatch(bucket):
        raise ValidationError("The immutable archive bucket name is invalid.")
    if not object_key or len(object_key) > 1024 or object_key.startswith("/"):
        raise ValidationError("The immutable archive object key is invalid.")
    if not object_version_id or len(object_version_id) > 1024:
        raise ValidationError("The immutable archive object version is required.")


def _validate_archive_content(
    *, byte_count: int, content_sha256: str, provider_checksum: str
) -> None:
    if byte_count < 1:
        raise ValidationError("An immutable archive object cannot be empty.")
    if not re.fullmatch(r"[0-9a-f]{64}", content_sha256):
        raise ValidationError("The immutable archive checksum is invalid.")
    if not provider_checksum or len(provider_checksum) > 512:
        raise ValidationError("The immutable archive provider checksum is required.")


def _validate_compliance_retention(
    *,
    retention_mode: ArchiveRetentionMode,
    retention_until: datetime,
    observed_at: datetime,
) -> None:
    if retention_mode is not ArchiveRetentionMode.COMPLIANCE:
        raise ValidationError("Immutable archives require COMPLIANCE retention mode.")
    _require_aware_datetime(retention_until, "archive retention")
    _require_aware_datetime(observed_at, "archive observation")
    if retention_until <= observed_at:
        raise ValidationError("The immutable archive retention must extend beyond verification.")


def _require_aware_datetime(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError(f"The {name} timestamp must include a timezone.")


def _event(
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: UUID,
    workspace_id: UUID,
    payload: dict[str, object],
) -> DomainEvent:
    return DomainEvent.create(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        workspace_id=workspace_id,
        payload=payload,
    )
