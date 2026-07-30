from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from datariver.domain.common import ConflictError, ValidationError
from datariver.domain.quality import (
    CompilerBinding,
    LegalHoldBinding,
    QualityOutcome,
    QualityRuleSet,
    QualityRuleSetVersion,
    RangeValueType,
    RetentionBinding,
    RetentionKind,
    RuleDefinition,
    RuleKind,
    RuleReviewDecision,
    RuleSetVersionState,
    RuleSeverity,
    ScheduleMode,
    ScheduleProfileBinding,
    ScorePolicyBinding,
    TargetBinding,
    ValidationAttemptState,
    ValidationRunState,
    aggregate_quality_outcome,
    require_attempt_transition,
    require_run_attempt_shape,
    require_validation_run_transition,
)

NOW = datetime(2026, 7, 30, 9, tzinfo=UTC)
HASH = "a" * 64


def _retention(kind: RetentionKind) -> RetentionBinding:
    return RetentionBinding(
        kind=kind,
        policy_id=uuid4(),
        policy_number=3,
        policy_hash=HASH,
        basis_at=NOW,
        retain_until=NOW + timedelta(days=30),
        hold=LegalHoldBinding(generation=4, resolution_hash="b" * 64),
    )


def _target() -> TargetBinding:
    return TargetBinding(
        workspace_id=uuid4(),
        asset_id=uuid4(),
        system_id=uuid4(),
        domain_id=uuid4(),
        classification=2,
        lifecycle="ACTIVE",
        source_version="source-v7",
        schema_hash=HASH,
        source_connection_profile_id="postgres-main",
        source_connection_profile_version=2,
        source_connection_profile_hash="b" * 64,
        workload_profile_id="full-table-approved",
        workload_profile_version=1,
        workload_profile_hash="c" * 64,
    )


def _rule(
    *,
    ordinal: int = 1,
    kind: RuleKind = RuleKind.NOT_NULL,
    parameters: dict[str, object] | None = None,
) -> RuleDefinition:
    return RuleDefinition.create(
        ordinal=ordinal,
        field_identifier=f"field:{ordinal}",
        kind=kind,
        severity=RuleSeverity.BLOCKING,
        parameters=parameters or {},
    )


def _version(
    *,
    author_id: UUID | None = None,
    rules: tuple[RuleDefinition, ...] | None = None,
) -> QualityRuleSetVersion:
    target = _target()
    return QualityRuleSetVersion(
        version_id=uuid4(),
        workspace_id=target.workspace_id,
        rule_set_id=uuid4(),
        version_number=1,
        author_id=author_id or uuid4(),
        target=target,
        compiler=CompilerBinding(
            contract_version="TYPED_GX_COMPILER_V1",
            gx_version="1.19.1",
            compiler_hash="d" * 64,
        ),
        score_policy=ScorePolicyBinding(
            policy_id="score-v1", policy_version=1, policy_hash="e" * 64
        ),
        schedule_profile=ScheduleProfileBinding(mode=ScheduleMode.MANUAL_ONLY),
        retention=_retention(RetentionKind.QUALITY_RULE),
        rules=rules if rules is not None else (_rule(),),
    )


def test_typed_rule_contract_is_deterministic_and_rejects_raw_gx_inputs() -> None:
    assert _rule(kind=RuleKind.NOT_NULL, parameters={}).parameters == {}
    with pytest.raises(ValidationError, match="does not accept parameters"):
        _rule(kind=RuleKind.NOT_NULL, parameters={"unexpected": True})

    first = _rule(
        kind=RuleKind.RANGE,
        parameters={
            "value_type": RangeValueType.DECIMAL.value,
            "min_value": Decimal("1.00"),
            "max_value": "9.500",
            "inclusive_min": True,
            "inclusive_max": False,
        },
    )
    second = _rule(
        kind=RuleKind.RANGE,
        parameters={
            "value_type": "DECIMAL",
            "min_value": "1",
            "max_value": Decimal("9.5"),
            "inclusive_min": True,
            "inclusive_max": False,
        },
    )
    assert first.parameters == second.parameters
    assert first.definition_hash == second.definition_hash

    invalid_parameters: tuple[dict[str, object], ...] = (
        {"expectation_type": "expect_column_values_to_not_be_null"},
        {"sql": "select 1"},
        {"kwargs": {}},
        {"row_condition": "x > 1"},
    )
    for parameters in invalid_parameters:
        with pytest.raises(ValidationError):
            _rule(parameters=parameters)
    with pytest.raises(ValidationError, match="REGEX is disabled"):
        _rule(kind=RuleKind.REGEX, parameters={"pattern": "^x$"})


def test_a_field_can_have_multiple_ordered_typed_rules() -> None:
    not_null = RuleDefinition.create(
        ordinal=1,
        field_identifier="field:shared",
        kind=RuleKind.NOT_NULL,
        severity=RuleSeverity.BLOCKING,
        parameters={},
    )
    bounded = RuleDefinition.create(
        ordinal=2,
        field_identifier="field:shared",
        kind=RuleKind.RANGE,
        severity=RuleSeverity.ADVISORY,
        parameters={
            "value_type": "DECIMAL",
            "min_value": "0",
            "max_value": "100",
            "inclusive_min": True,
            "inclusive_max": True,
        },
    )
    assert _version(rules=(not_null, bounded)).rules == (not_null, bounded)


@pytest.mark.parametrize(
    ("value_type", "minimum", "maximum"),
    (
        ("DATE", date(2026, 1, 1), "2026-12-31"),
        ("TIMESTAMP", NOW, (NOW + timedelta(hours=1)).isoformat()),
    ),
)
def test_range_accepts_only_same_typed_ordered_boundaries(
    value_type: str, minimum: object, maximum: object
) -> None:
    rule = _rule(
        kind=RuleKind.RANGE,
        parameters={
            "value_type": value_type,
            "min_value": minimum,
            "max_value": maximum,
            "inclusive_min": True,
            "inclusive_max": True,
        },
    )
    assert rule.parameters["value_type"] == value_type

    with pytest.raises(ValidationError):
        _rule(
            kind=RuleKind.RANGE,
            parameters={
                "value_type": value_type,
                "min_value": maximum,
                "max_value": minimum,
                "inclusive_min": True,
                "inclusive_max": True,
            },
        )


def test_rule_version_maker_checker_and_terminal_lifecycle() -> None:
    author = uuid4()
    reviewer = uuid4()
    version = _version(author_id=author)
    with pytest.raises(ValidationError, match="cannot review"):
        version.decide(
            decision=RuleReviewDecision.APPROVE,
            actor_id=author,
            reason="self",
            policy_decision_id=uuid4(),
            assurance_hash=HASH,
            target_hash=version.target.binding_hash,
            occurred_at=NOW,
            audit_retention=_retention(RetentionKind.QUALITY_AUDIT),
        )
    version.decide(
        decision=RuleReviewDecision.APPROVE,
        actor_id=reviewer,
        reason="independent review",
        policy_decision_id=uuid4(),
        assurance_hash=HASH,
        target_hash=version.target.binding_hash,
        occurred_at=NOW,
        audit_retention=_retention(RetentionKind.QUALITY_AUDIT),
    )
    assert version.state is RuleSetVersionState.APPROVED
    with pytest.raises(ValidationError, match="cannot activate"):
        version.activate(actor_id=author)
    version.activate(actor_id=reviewer)
    version.revoke()
    assert version.state.value == RuleSetVersionState.REVOKED.value
    with pytest.raises(ConflictError):
        version.activate(actor_id=reviewer)


def test_activation_requires_nonempty_rules_and_archive_requires_revoke() -> None:
    author = uuid4()
    reviewer = uuid4()
    version = _version(author_id=author, rules=())
    version.decide(
        decision=RuleReviewDecision.APPROVE,
        actor_id=reviewer,
        reason="review",
        policy_decision_id=uuid4(),
        assurance_hash=HASH,
        target_hash=version.target.binding_hash,
        occurred_at=NOW,
        audit_retention=_retention(RetentionKind.QUALITY_AUDIT),
    )
    with pytest.raises(ValidationError, match="at least one rule"):
        version.activate(actor_id=reviewer)

    rule_set = QualityRuleSet.create(
        workspace_id=version.workspace_id,
        asset_id=version.target.asset_id,
        name="Core quality",
        created_by=author,
        retention=_retention(RetentionKind.QUALITY_RULE),
    )
    with pytest.raises(ConflictError, match="must be revoked"):
        rule_set.archive(
            actor_id=author,
            actor_is_security_administrator=False,
            has_active_version=True,
            expected_version=1,
        )
    rule_set.archive(
        actor_id=author,
        actor_is_security_administrator=False,
        has_active_version=False,
        expected_version=1,
    )
    assert rule_set.state.value == "ARCHIVED"


def test_run_attempt_shape_matrix_is_exhaustive() -> None:
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
    for run_state in ValidationRunState:
        for attempt_state in (None, *ValidationAttemptState):
            for outcome in QualityOutcome:
                expected = attempt_state in allowed_attempts[run_state] and (
                    (run_state is ValidationRunState.SUCCEEDED)
                    == (outcome is not QualityOutcome.UNKNOWN)
                )
                if expected:
                    require_run_attempt_shape(
                        run_state=run_state,
                        current_attempt_state=attempt_state,
                        quality_outcome=outcome,
                    )
                else:
                    with pytest.raises(ValidationError):
                        require_run_attempt_shape(
                            run_state=run_state,
                            current_attempt_state=attempt_state,
                            quality_outcome=outcome,
                        )


def test_run_and_attempt_transition_matrices_are_exhaustive() -> None:
    allowed_run_targets = {
        ValidationRunState.QUEUED: {
            ValidationRunState.RUNNING,
            ValidationRunState.CANCELLED,
        },
        ValidationRunState.RUNNING: {
            ValidationRunState.RETRY_WAIT,
            ValidationRunState.CANCEL_REQUESTED,
            ValidationRunState.SUCCEEDED,
            ValidationRunState.FAILED,
            ValidationRunState.STALE,
            ValidationRunState.CANCELLED,
        },
        ValidationRunState.RETRY_WAIT: {
            ValidationRunState.RUNNING,
            ValidationRunState.CANCELLED,
        },
        ValidationRunState.CANCEL_REQUESTED: {
            ValidationRunState.CANCELLED,
            ValidationRunState.FAILED,
            ValidationRunState.STALE,
        },
        ValidationRunState.SUCCEEDED: set(),
        ValidationRunState.FAILED: set(),
        ValidationRunState.STALE: set(),
        ValidationRunState.CANCELLED: set(),
    }
    for current in ValidationRunState:
        for target in ValidationRunState:
            if target in allowed_run_targets[current]:
                require_validation_run_transition(current=current, target=target)
            else:
                with pytest.raises(ValidationError):
                    require_validation_run_transition(current=current, target=target)
    for attempt_current in ValidationAttemptState:
        for attempt_target in ValidationAttemptState:
            if (
                attempt_current is ValidationAttemptState.RUNNING
                and attempt_target is not attempt_current
            ):
                require_attempt_transition(
                    current=attempt_current,
                    target=attempt_target,
                )
            else:
                with pytest.raises(ValidationError):
                    require_attempt_transition(
                        current=attempt_current,
                        target=attempt_target,
                    )


def test_score_outcome_covers_empty_pass_warn_and_fail() -> None:
    assert aggregate_quality_outcome(()) is QualityOutcome.UNKNOWN
    assert aggregate_quality_outcome(((RuleSeverity.BLOCKING, True),)) is QualityOutcome.PASS
    assert (
        aggregate_quality_outcome(
            (
                (RuleSeverity.BLOCKING, True),
                (RuleSeverity.ADVISORY, False),
            )
        )
        is QualityOutcome.WARN
    )
    assert aggregate_quality_outcome(((RuleSeverity.BLOCKING, False),)) is QualityOutcome.FAIL
