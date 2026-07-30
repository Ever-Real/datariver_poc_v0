from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from datariver.domain.common import ConflictError, ValidationError, canonical_json_hash, uuid7

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_FIELD_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,254}$")
_NAME_LIMIT = 255
_FAILURE_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,99}$")


class RuleSetState(StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class RuleSetVersionState(StrEnum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class RuleReviewDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class RuleCommand(StrEnum):
    ACTIVATE = "ACTIVATE"
    REVOKE = "REVOKE"
    ARCHIVE = "ARCHIVE"
    SUPERSEDE = "SUPERSEDE"


class RuleKind(StrEnum):
    NOT_NULL = "NOT_NULL"
    RANGE = "RANGE"
    REGEX = "REGEX"


class RuleSeverity(StrEnum):
    BLOCKING = "BLOCKING"
    ADVISORY = "ADVISORY"


class RangeValueType(StrEnum):
    DECIMAL = "DECIMAL"
    DATE = "DATE"
    TIMESTAMP = "TIMESTAMP"


class ScheduleMode(StrEnum):
    MANUAL_ONLY = "MANUAL_ONLY"
    SCHEDULED = "SCHEDULED"


class ScheduleState(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class RunTrigger(StrEnum):
    MANUAL = "MANUAL"
    SCHEDULED = "SCHEDULED"
    RETRY = "RETRY"


class ValidationRunState(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    RETRY_WAIT = "RETRY_WAIT"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    STALE = "STALE"
    CANCELLED = "CANCELLED"

    @property
    def terminal(self) -> bool:
        return self in {
            self.SUCCEEDED,
            self.FAILED,
            self.STALE,
            self.CANCELLED,
        }


class ValidationAttemptState(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    RETRYABLE_FAILED = "RETRYABLE_FAILED"
    FAILED = "FAILED"
    STALE = "STALE"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class QualityOutcome(StrEnum):
    PASS = "PASS"  # noqa: S105 - outcome label, never credential material
    WARN = "WARN"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class ExpectationOutcome(StrEnum):
    PASS = "PASS"  # noqa: S105 - outcome label, never credential material
    ADVISORY_FAIL = "ADVISORY_FAIL"
    BLOCKING_FAIL = "BLOCKING_FAIL"


class RetentionKind(StrEnum):
    QUALITY_RULE = "QUALITY_RULE"
    QUALITY_RESULT = "QUALITY_RESULT"
    QUALITY_AUDIT = "QUALITY_AUDIT"


@dataclass(frozen=True, slots=True)
class LegalHoldBinding:
    generation: int
    resolution_hash: str

    def __post_init__(self) -> None:
        if self.generation < 1:
            raise ValidationError("The Legal Hold generation must be positive.")
        _require_sha256(self.resolution_hash, "Legal Hold resolution hash")

    def document(self) -> dict[str, object]:
        return {
            "generation": self.generation,
            "resolution_hash": self.resolution_hash,
        }


@dataclass(frozen=True, slots=True)
class RetentionBinding:
    kind: RetentionKind
    policy_id: UUID
    policy_number: int
    policy_hash: str
    basis_at: datetime
    retain_until: datetime
    hold: LegalHoldBinding

    def __post_init__(self) -> None:
        if self.policy_number < 1:
            raise ValidationError("The retention policy number must be positive.")
        _require_sha256(self.policy_hash, "retention policy hash")
        _require_aware(self.basis_at, "retention basis")
        _require_aware(self.retain_until, "retention deadline")
        if self.retain_until <= self.basis_at:
            raise ValidationError("The retention deadline must follow its basis.")

    def document(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "policy_id": str(self.policy_id),
            "policy_number": self.policy_number,
            "policy_hash": self.policy_hash,
            "basis_at": self.basis_at.isoformat(),
            "retain_until": self.retain_until.isoformat(),
            "hold": self.hold.document(),
        }


@dataclass(frozen=True, slots=True)
class TargetBinding:
    workspace_id: UUID
    asset_id: UUID
    system_id: UUID | None
    domain_id: UUID | None
    classification: int
    lifecycle: str
    source_version: str
    schema_hash: str
    source_connection_profile_id: str
    source_connection_profile_version: int
    source_connection_profile_hash: str
    workload_profile_id: str
    workload_profile_version: int
    workload_profile_hash: str

    def __post_init__(self) -> None:
        if self.classification not in {0, 1, 2, 3}:
            raise ValidationError("The target classification is invalid.")
        for value, label, limit in (
            (self.lifecycle, "lifecycle", 50),
            (self.source_version, "source version", 255),
            (self.source_connection_profile_id, "source connection profile ID", 255),
            (self.workload_profile_id, "workload profile ID", 255),
        ):
            if not value or len(value) > limit:
                raise ValidationError(f"The target {label} is invalid.")
        if self.source_connection_profile_version < 1 or self.workload_profile_version < 1:
            raise ValidationError("The target profile version must be positive.")
        for value, label in (
            (self.schema_hash, "schema hash"),
            (self.source_connection_profile_hash, "source connection profile hash"),
            (self.workload_profile_hash, "workload profile hash"),
        ):
            _require_sha256(value, label)

    def document(self) -> dict[str, object]:
        return {
            "contract": "QUALITY_TARGET_BINDING_V1",
            "workspace_id": str(self.workspace_id),
            "asset_id": str(self.asset_id),
            "system_id": str(self.system_id) if self.system_id else None,
            "domain_id": str(self.domain_id) if self.domain_id else None,
            "classification": self.classification,
            "lifecycle": self.lifecycle,
            "source_version": self.source_version,
            "schema_hash": self.schema_hash,
            "source_connection": {
                "profile_id": self.source_connection_profile_id,
                "version": self.source_connection_profile_version,
                "hash": self.source_connection_profile_hash,
            },
            "workload": {
                "profile_id": self.workload_profile_id,
                "version": self.workload_profile_version,
                "hash": self.workload_profile_hash,
            },
        }

    @property
    def binding_hash(self) -> str:
        return canonical_json_hash(self.document())


@dataclass(frozen=True, slots=True)
class CompilerBinding:
    contract_version: str
    gx_version: str
    compiler_hash: str

    def __post_init__(self) -> None:
        if not self.contract_version or len(self.contract_version) > 100:
            raise ValidationError("The compiler contract version is invalid.")
        if self.gx_version != "1.19.1":
            raise ValidationError("The Quality compiler requires GX 1.19.1.")
        _require_sha256(self.compiler_hash, "compiler hash")


@dataclass(frozen=True, slots=True)
class ScorePolicyBinding:
    policy_id: str
    policy_version: int
    policy_hash: str

    def __post_init__(self) -> None:
        if not self.policy_id or len(self.policy_id) > 255 or self.policy_version < 1:
            raise ValidationError("The score-policy binding is invalid.")
        _require_sha256(self.policy_hash, "score-policy hash")


@dataclass(frozen=True, slots=True)
class ScheduleProfileBinding:
    mode: ScheduleMode
    profile_id: str | None = None
    profile_version: int | None = None
    profile_hash: str | None = None

    def __post_init__(self) -> None:
        supplied = (
            self.profile_id is not None,
            self.profile_version is not None,
            self.profile_hash is not None,
        )
        if self.mode is ScheduleMode.MANUAL_ONLY:
            if any(supplied):
                raise ValidationError("A manual-only version cannot carry a schedule profile.")
            return
        if not all(supplied):
            raise ValidationError("A scheduled version requires an exact schedule profile.")
        if not self.profile_id or len(self.profile_id) > 255:
            raise ValidationError("The schedule profile ID is invalid.")
        if self.profile_version is None or self.profile_version < 1:
            raise ValidationError("The schedule profile version is invalid.")
        assert self.profile_hash is not None
        _require_sha256(self.profile_hash, "schedule profile hash")


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    rule_id: UUID
    ordinal: int
    field_identifier: str
    kind: RuleKind
    severity: RuleSeverity
    parameters: dict[str, object]
    definition_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.ordinal < 1:
            raise ValidationError("The rule ordinal must be positive.")
        if not _FIELD_IDENTIFIER_PATTERN.fullmatch(self.field_identifier):
            raise ValidationError("The server-owned field identifier is invalid.")
        normalized = _normalize_rule_parameters(kind=self.kind, parameters=self.parameters)
        object.__setattr__(self, "parameters", normalized)
        object.__setattr__(
            self,
            "definition_hash",
            canonical_json_hash(
                {
                    "contract": "QUALITY_RULE_DEFINITION_V1",
                    "ordinal": self.ordinal,
                    "field_identifier": self.field_identifier,
                    "kind": self.kind.value,
                    "severity": self.severity.value,
                    "parameters": normalized,
                }
            ),
        )

    @classmethod
    def create(
        cls,
        *,
        ordinal: int,
        field_identifier: str,
        kind: RuleKind,
        severity: RuleSeverity,
        parameters: dict[str, object],
    ) -> RuleDefinition:
        return cls(
            rule_id=uuid7(),
            ordinal=ordinal,
            field_identifier=field_identifier,
            kind=kind,
            severity=severity,
            parameters=parameters,
        )


@dataclass(frozen=True, slots=True)
class RuleReview:
    review_id: UUID
    decision: RuleReviewDecision
    actor_id: UUID
    reason: str
    policy_decision_id: UUID
    assurance_hash: str
    target_hash: str
    occurred_at: datetime
    retention: RetentionBinding

    def __post_init__(self) -> None:
        _require_text(self.reason, "review reason", 4000)
        _require_sha256(self.assurance_hash, "review assurance hash")
        _require_sha256(self.target_hash, "review target hash")
        _require_aware(self.occurred_at, "review time")
        if self.retention.kind is not RetentionKind.QUALITY_AUDIT:
            raise ValidationError("A review requires a QUALITY_AUDIT retention binding.")


@dataclass(slots=True)
class QualityRuleSetVersion:
    version_id: UUID
    workspace_id: UUID
    rule_set_id: UUID
    version_number: int
    author_id: UUID
    target: TargetBinding
    compiler: CompilerBinding
    score_policy: ScorePolicyBinding
    schedule_profile: ScheduleProfileBinding
    retention: RetentionBinding
    rules: tuple[RuleDefinition, ...]
    state: RuleSetVersionState = RuleSetVersionState.PROPOSED
    review: RuleReview | None = None

    def __post_init__(self) -> None:
        if self.version_number < 1:
            raise ValidationError("The Rule Set version number must be positive.")
        if self.target.workspace_id != self.workspace_id:
            raise ValidationError("The target and Rule Set workspaces differ.")
        if self.retention.kind is not RetentionKind.QUALITY_RULE:
            raise ValidationError("A Rule Set Version requires QUALITY_RULE retention.")
        ordinals = tuple(rule.ordinal for rule in self.rules)
        if ordinals != tuple(range(1, len(self.rules) + 1)):
            raise ValidationError("Rule ordinals must be unique and contiguous from one.")

    def decide(
        self,
        *,
        decision: RuleReviewDecision,
        actor_id: UUID,
        reason: str,
        policy_decision_id: UUID,
        assurance_hash: str,
        target_hash: str,
        occurred_at: datetime,
        audit_retention: RetentionBinding,
    ) -> None:
        if self.state is not RuleSetVersionState.PROPOSED or self.review is not None:
            raise ConflictError("The Rule Set Version is not awaiting review.")
        if actor_id == self.author_id:
            raise ValidationError("The Rule Set Version author cannot review it.")
        if target_hash != self.target.binding_hash:
            raise ConflictError("The reviewed target binding is stale.")
        self.review = RuleReview(
            review_id=uuid7(),
            decision=decision,
            actor_id=actor_id,
            reason=reason,
            policy_decision_id=policy_decision_id,
            assurance_hash=assurance_hash,
            target_hash=target_hash,
            occurred_at=occurred_at,
            retention=audit_retention,
        )
        self.state = (
            RuleSetVersionState.APPROVED
            if decision is RuleReviewDecision.APPROVE
            else RuleSetVersionState.REJECTED
        )

    def activate(self, *, actor_id: UUID) -> None:
        if self.state is not RuleSetVersionState.APPROVED:
            raise ConflictError("Only an approved Rule Set Version can be activated.")
        if not self.rules:
            raise ValidationError("An active Rule Set Version requires at least one rule.")
        if actor_id == self.author_id:
            raise ValidationError("The Rule Set Version author cannot activate it.")
        self.state = RuleSetVersionState.ACTIVE

    def supersede(self) -> None:
        if self.state is not RuleSetVersionState.ACTIVE:
            raise ConflictError("Only an active Rule Set Version can be superseded.")
        self.state = RuleSetVersionState.SUPERSEDED

    def revoke(self) -> None:
        if self.state is not RuleSetVersionState.ACTIVE:
            raise ConflictError("Only an active Rule Set Version can be revoked.")
        self.state = RuleSetVersionState.REVOKED


@dataclass(slots=True)
class QualityRuleSet:
    rule_set_id: UUID
    workspace_id: UUID
    asset_id: UUID
    name: str
    created_by: UUID
    retention: RetentionBinding
    state: RuleSetState = RuleSetState.ACTIVE
    version: int = 1

    def __post_init__(self) -> None:
        _require_text(self.name, "Rule Set name", _NAME_LIMIT)
        if self.retention.kind is not RetentionKind.QUALITY_RULE:
            raise ValidationError("A Rule Set requires QUALITY_RULE retention.")
        if self.version < 1:
            raise ValidationError("The Rule Set version must be positive.")

    @classmethod
    def create(
        cls,
        *,
        workspace_id: UUID,
        asset_id: UUID,
        name: str,
        created_by: UUID,
        retention: RetentionBinding,
    ) -> QualityRuleSet:
        return cls(
            rule_set_id=uuid7(),
            workspace_id=workspace_id,
            asset_id=asset_id,
            name=name.strip(),
            created_by=created_by,
            retention=retention,
        )

    def archive(
        self,
        *,
        actor_id: UUID,
        actor_is_security_administrator: bool,
        has_active_version: bool,
        expected_version: int,
    ) -> None:
        if expected_version != self.version:
            raise ConflictError(
                "The Rule Set was modified by another operation.",
                details={"expected": expected_version, "actual": self.version},
            )
        if self.state is RuleSetState.ARCHIVED:
            raise ConflictError("The Rule Set is already archived.")
        if actor_id != self.created_by and not actor_is_security_administrator:
            raise ValidationError("Only the creator or a security administrator may archive.")
        if has_active_version:
            raise ConflictError("The active Rule Set Version must be revoked before archive.")
        self.state = RuleSetState.ARCHIVED
        self.version += 1


_RUN_TRANSITIONS: dict[ValidationRunState, frozenset[ValidationRunState]] = {
    ValidationRunState.QUEUED: frozenset(
        {ValidationRunState.RUNNING, ValidationRunState.CANCELLED}
    ),
    ValidationRunState.RUNNING: frozenset(
        {
            ValidationRunState.RETRY_WAIT,
            ValidationRunState.CANCEL_REQUESTED,
            ValidationRunState.SUCCEEDED,
            ValidationRunState.FAILED,
            ValidationRunState.STALE,
            ValidationRunState.CANCELLED,
        }
    ),
    ValidationRunState.RETRY_WAIT: frozenset(
        {ValidationRunState.RUNNING, ValidationRunState.CANCELLED}
    ),
    ValidationRunState.CANCEL_REQUESTED: frozenset(
        {
            ValidationRunState.CANCELLED,
            ValidationRunState.FAILED,
            ValidationRunState.STALE,
        }
    ),
    ValidationRunState.SUCCEEDED: frozenset(),
    ValidationRunState.FAILED: frozenset(),
    ValidationRunState.STALE: frozenset(),
    ValidationRunState.CANCELLED: frozenset(),
}


def require_validation_run_transition(
    *, current: ValidationRunState, target: ValidationRunState
) -> None:
    if target not in _RUN_TRANSITIONS[current]:
        raise ValidationError(
            f"Quality run transition {current.value} -> {target.value} is invalid."
        )


def require_attempt_transition(
    *, current: ValidationAttemptState, target: ValidationAttemptState
) -> None:
    if current is not ValidationAttemptState.RUNNING or target is ValidationAttemptState.RUNNING:
        raise ValidationError(
            f"Quality attempt transition {current.value} -> {target.value} is invalid."
        )


def require_run_attempt_shape(
    *,
    run_state: ValidationRunState,
    current_attempt_state: ValidationAttemptState | None,
    quality_outcome: QualityOutcome,
) -> None:
    allowed_attempts: dict[ValidationRunState, frozenset[ValidationAttemptState | None]] = {
        ValidationRunState.QUEUED: frozenset({None}),
        ValidationRunState.RUNNING: frozenset({ValidationAttemptState.RUNNING}),
        ValidationRunState.RETRY_WAIT: frozenset({ValidationAttemptState.RETRYABLE_FAILED}),
        ValidationRunState.CANCEL_REQUESTED: frozenset({ValidationAttemptState.RUNNING}),
        ValidationRunState.SUCCEEDED: frozenset({ValidationAttemptState.SUCCEEDED}),
        ValidationRunState.FAILED: frozenset({ValidationAttemptState.FAILED}),
        ValidationRunState.STALE: frozenset({ValidationAttemptState.STALE}),
        ValidationRunState.CANCELLED: frozenset(
            {
                None,
                ValidationAttemptState.CANCELLED,
                ValidationAttemptState.RETRYABLE_FAILED,
            }
        ),
    }
    if current_attempt_state not in allowed_attempts[run_state]:
        raise ValidationError("The Quality run and current attempt states do not match.")
    if run_state is ValidationRunState.SUCCEEDED:
        if quality_outcome is QualityOutcome.UNKNOWN:
            raise ValidationError("A successful Quality run requires a quality outcome.")
    elif quality_outcome is not QualityOutcome.UNKNOWN:
        raise ValidationError("Only a successful Quality run may have a quality outcome.")


def aggregate_quality_outcome(
    results: tuple[tuple[RuleSeverity, bool], ...],
) -> QualityOutcome:
    if not results:
        return QualityOutcome.UNKNOWN
    if any(not passed and severity is RuleSeverity.BLOCKING for severity, passed in results):
        return QualityOutcome.FAIL
    if any(not passed for _, passed in results):
        return QualityOutcome.WARN
    return QualityOutcome.PASS


class TypedExpectationCompiler(Protocol):
    """Port implemented only by the isolated Quality worker adapter."""

    def compile(self, rule: RuleDefinition) -> dict[str, object]: ...


def _normalize_rule_parameters(
    *, kind: RuleKind, parameters: dict[str, object]
) -> dict[str, object]:
    prohibited = {
        "expectation_type",
        "expectation_name",
        "kwargs",
        "suite",
        "checkpoint",
        "datasource",
        "batch_request",
        "sql",
        "query",
        "graphql",
        "python",
        "module",
        "plugin",
        "row_condition",
        "condition_parser",
        "url",
        "urn",
        "external_urn",
    }
    if prohibited.intersection(key.lower() for key in parameters):
        raise ValidationError("The typed Quality rule contains a prohibited field.")
    if kind is RuleKind.NOT_NULL:
        if parameters:
            raise ValidationError("NOT_NULL does not accept parameters.")
        return {}
    if kind is RuleKind.REGEX:
        raise ValidationError("REGEX is disabled until a bounded safe engine is approved.")
    if set(parameters) != {
        "value_type",
        "min_value",
        "max_value",
        "inclusive_min",
        "inclusive_max",
    }:
        raise ValidationError("RANGE requires the exact typed parameter document.")
    try:
        value_type = RangeValueType(str(parameters["value_type"]))
    except ValueError as error:
        raise ValidationError("The RANGE value type is invalid.") from error
    if not isinstance(parameters["inclusive_min"], bool) or not isinstance(
        parameters["inclusive_max"], bool
    ):
        raise ValidationError("RANGE inclusivity values must be booleans.")
    minimum = _normalize_range_value(value_type, parameters["min_value"])
    maximum = _normalize_range_value(value_type, parameters["max_value"])
    if _compare_range_values(value_type, minimum, maximum) > 0:
        raise ValidationError("The RANGE minimum cannot exceed its maximum.")
    return {
        "value_type": value_type.value,
        "min_value": minimum,
        "max_value": maximum,
        "inclusive_min": parameters["inclusive_min"],
        "inclusive_max": parameters["inclusive_max"],
    }


def _normalize_range_value(value_type: RangeValueType, value: object) -> str:
    if isinstance(value, bool):
        raise ValidationError("A boolean is not a valid RANGE boundary.")
    if value_type is RangeValueType.DECIMAL:
        if not isinstance(value, (str, int, Decimal)):
            raise ValidationError("A decimal RANGE boundary must be a decimal string.")
        try:
            normalized = Decimal(str(value))
        except InvalidOperation as error:
            raise ValidationError("A decimal RANGE boundary is invalid.") from error
        if not normalized.is_finite():
            raise ValidationError("A decimal RANGE boundary must be finite.")
        rendered = format(normalized.normalize(), "f")
        return "0" if rendered in {"-0", ""} else rendered
    if value_type is RangeValueType.DATE:
        if isinstance(value, datetime) or not isinstance(value, (str, date)):
            raise ValidationError("A date RANGE boundary must be an ISO date.")
        try:
            parsed = value if isinstance(value, date) else date.fromisoformat(value)
        except ValueError as error:
            raise ValidationError("A date RANGE boundary is invalid.") from error
        return parsed.isoformat()
    if not isinstance(value, (str, datetime)):
        raise ValidationError("A timestamp RANGE boundary must be an ISO timestamp.")
    try:
        parsed_time = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    except ValueError as error:
        raise ValidationError("A timestamp RANGE boundary is invalid.") from error
    _require_aware(parsed_time, "RANGE timestamp boundary")
    return parsed_time.isoformat()


def _compare_range_values(value_type: RangeValueType, left: str, right: str) -> int:
    if value_type is RangeValueType.DECIMAL:
        left_decimal = Decimal(left)
        right_decimal = Decimal(right)
        return (left_decimal > right_decimal) - (left_decimal < right_decimal)
    if value_type is RangeValueType.DATE:
        left_date = date.fromisoformat(left)
        right_date = date.fromisoformat(right)
        return (left_date > right_date) - (left_date < right_date)
    left_time = datetime.fromisoformat(left)
    right_time = datetime.fromisoformat(right)
    return (left_time > right_time) - (left_time < right_time)


def _require_sha256(value: str, label: str) -> None:
    if not _SHA256_PATTERN.fullmatch(value):
        raise ValidationError(f"The {label} is invalid.")


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError(f"The {label} must be timezone-aware.")


def _require_text(value: str, label: str, limit: int) -> None:
    if not value.strip() or len(value) > limit:
        raise ValidationError(f"The {label} is invalid.")


def require_finite_ratio(value: float, label: str) -> None:
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValidationError(f"The {label} must be a finite ratio.")


def require_sanitized_failure_code(value: str | None) -> None:
    if value is not None and not _FAILURE_CODE_PATTERN.fullmatch(value):
        raise ValidationError("The Quality failure code is invalid.")
