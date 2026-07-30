from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from datariver.domain.authz import Classification
from datariver.domain.common import ConflictError, ValidationError
from datariver.domain.retention import (
    AUTOMATION_DISABLED,
    LEGACY_RETENTION_DATA_CLASSES,
    ErasureRequest,
    ErasureTargetSnapshot,
    ErasureTargetType,
    GovernanceDecision,
    RetentionArchiveDisposition,
    RetentionClassRule,
    RetentionDataClass,
    RetentionExecutionCommand,
    RetentionExecutionState,
    RetentionPeriodUnit,
    RetentionPolicyContract,
    RetentionPolicyVersion,
    RetentionRules,
)


def _contract(*, now: datetime, minimum_chat_days: int = 7) -> RetentionPolicyContract:
    return RetentionPolicyContract(
        effective_from=now - timedelta(days=1),
        effective_until=now + timedelta(days=365),
        execution_authorization_hours=24,
        class_rules=(
            RetentionClassRule(
                data_class=RetentionDataClass.COMPLETED_OPERATIONS,
                unit=RetentionPeriodUnit.DAYS,
                minimum=30,
                maximum=90,
                archive_disposition=RetentionArchiveDisposition.EVIDENCE_ONLY,
            ),
            RetentionClassRule(
                data_class=RetentionDataClass.CHAT_CONTENT,
                unit=RetentionPeriodUnit.DAYS,
                minimum=minimum_chat_days,
                maximum=365,
                archive_disposition=RetentionArchiveDisposition.EVIDENCE_ONLY,
            ),
            RetentionClassRule(
                data_class=RetentionDataClass.AUDIT_EVIDENCE,
                unit=RetentionPeriodUnit.YEARS,
                minimum=3,
                maximum=7,
                archive_disposition=RetentionArchiveDisposition.CONTENT_WORM,
            ),
            RetentionClassRule(
                data_class=RetentionDataClass.OBJECT_DATA,
                unit=RetentionPeriodUnit.DAYS,
                minimum=14,
                maximum=730,
                archive_disposition=RetentionArchiveDisposition.EVIDENCE_ONLY,
            ),
        ),
    )


def _active_policy(*, workspace_id: UUID, now: datetime) -> RetentionPolicyVersion:
    policy = RetentionPolicyVersion.propose(
        workspace_id=workspace_id,
        policy_number=2,
        rules=RetentionRules(30, 365, 12, 7),
        contract=_contract(now=now),
        requester_id=uuid4(),
        reason="Policy Book V2 retention contract",
        policy_decision_id=uuid4(),
    )
    policy.decide(
        decision=GovernanceDecision.APPROVED,
        actor_id=uuid4(),
        reason="Independent approval",
        policy_decision_id=uuid4(),
        expected_version=1,
        now=now - timedelta(hours=2),
    )
    return policy


def _approved_request(
    *,
    workspace_id: UUID,
    policy: RetentionPolicyVersion,
    target: ErasureTargetSnapshot,
    now: datetime,
) -> ErasureRequest:
    request = ErasureRequest.create(
        workspace_id=workspace_id,
        target_type=target.target_type,
        target_id=target.target_id,
        target_version=target.version,
        target_owner_id=target.owner_id,
        classification=target.classification,
        retention_policy_id=policy.policy_id,
        retention_policy_hash=policy.payload_hash,
        requester_id=uuid4(),
        reason="Approved explicit erasure",
        policy_decision_id=uuid4(),
        now=now - timedelta(hours=3),
        expires_at=now + timedelta(days=1),
    )
    request.decide(
        decision=GovernanceDecision.APPROVED,
        actor_id=uuid4(),
        reason="Independent erasure approval",
        policy_decision_id=uuid4(),
        expected_version=1,
        now=now - timedelta(hours=1),
        active_legal_hold=False,
        current_target_version=target.version,
        current_target_owner_id=target.owner_id,
        current_classification=target.classification,
        active_retention_policy_id=policy.policy_id,
        active_retention_policy_hash=policy.payload_hash,
    )
    return request


def test_policy_book_v2_requires_exactly_one_bounded_rule_per_data_class() -> None:
    now = datetime.now(UTC)
    contract = _contract(now=now)
    assert set(rule.data_class for rule in contract.class_rules) == LEGACY_RETENTION_DATA_CLASSES
    assert contract.rule_for(RetentionDataClass.CHAT_CONTENT).minimum == 7

    with pytest.raises(ValidationError, match="exactly one"):
        RetentionPolicyContract(
            effective_from=now,
            effective_until=now + timedelta(days=1),
            execution_authorization_hours=24,
            class_rules=contract.class_rules[:-1],
        )


def test_policy_book_v3_requires_all_quality_classes_without_backfilling_v2() -> None:
    now = datetime.now(UTC)
    legacy = _contract(now=now)
    quality_rules = tuple(
        RetentionClassRule(
            data_class=data_class,
            unit=RetentionPeriodUnit.DAYS,
            minimum=30,
            maximum=365,
            archive_disposition=RetentionArchiveDisposition.EVIDENCE_ONLY,
        )
        for data_class in (
            RetentionDataClass.QUALITY_RULE,
            RetentionDataClass.QUALITY_RESULT,
            RetentionDataClass.QUALITY_AUDIT,
        )
    )
    quality = RetentionPolicyContract(
        effective_from=legacy.effective_from,
        effective_until=legacy.effective_until,
        execution_authorization_hours=legacy.execution_authorization_hours,
        class_rules=legacy.class_rules + quality_rules,
        contract_version="POLICY_BOOK_V3",
    )
    assert quality.contract_version == "POLICY_BOOK_V3"
    assert quality.rule_for(RetentionDataClass.QUALITY_RESULT).minimum == 30
    assert legacy.contract_version == "POLICY_BOOK_V2"
    with pytest.raises(ValidationError, match="every governed data class"):
        RetentionPolicyContract(
            effective_from=legacy.effective_from,
            effective_until=legacy.effective_until,
            execution_authorization_hours=legacy.execution_authorization_hours,
            class_rules=legacy.class_rules + quality_rules[:-1],
            contract_version="POLICY_BOOK_V3",
        )
    with pytest.raises(ValidationError, match="minimum"):
        RetentionClassRule(
            data_class=RetentionDataClass.CHAT_CONTENT,
            unit=RetentionPeriodUnit.DAYS,
            minimum=10,
            maximum=9,
            archive_disposition=RetentionArchiveDisposition.EVIDENCE_ONLY,
        )


def test_policy_v2_hashes_window_and_rules_without_reinterpreting_legacy() -> None:
    now = datetime.now(UTC)
    workspace_id = uuid4()
    legacy = RetentionPolicyVersion.propose(
        workspace_id=workspace_id,
        policy_number=1,
        rules=RetentionRules(30, 365, 12, 7),
        requester_id=uuid4(),
        reason="Legacy policy",
        policy_decision_id=uuid4(),
    )
    modern = RetentionPolicyVersion.propose(
        workspace_id=workspace_id,
        policy_number=2,
        rules=RetentionRules(30, 365, 12, 7),
        contract=_contract(now=now),
        requester_id=uuid4(),
        reason="Modern policy",
        policy_decision_id=uuid4(),
    )
    changed = RetentionPolicyVersion.propose(
        workspace_id=workspace_id,
        policy_number=3,
        rules=RetentionRules(30, 365, 12, 7),
        contract=_contract(now=now, minimum_chat_days=8),
        requester_id=uuid4(),
        reason="Changed modern policy",
        policy_decision_id=uuid4(),
    )

    assert legacy.contract is None
    assert legacy.contract_version == "SINGLE_DEADLINE_V1"
    assert modern.contract_version == "POLICY_BOOK_V2"
    assert modern.payload_hash != legacy.payload_hash
    assert changed.payload_hash != modern.payload_hash

    with pytest.raises(ValidationError, match="Chat scheduling deadline"):
        RetentionPolicyVersion.propose(
            workspace_id=workspace_id,
            policy_number=4,
            rules=RetentionRules(30, 366, 12, 7),
            contract=_contract(now=now),
            requester_id=uuid4(),
            reason="Out-of-bounds Chat schedule",
            policy_decision_id=uuid4(),
        )


def test_execution_command_consumes_exact_approval_but_never_enables_deletion() -> None:
    now = datetime.now(UTC)
    workspace_id = uuid4()
    owner_id = uuid4()
    target = ErasureTargetSnapshot(
        target_type=ErasureTargetType.CHAT_SESSION,
        target_id=uuid4(),
        version=4,
        owner_id=owner_id,
        classification=Classification.CONFIDENTIAL,
        retention_basis_at=now - timedelta(days=30),
        retention_until=now + timedelta(days=335),
    )
    policy = _active_policy(workspace_id=workspace_id, now=now)
    request = _approved_request(workspace_id=workspace_id, policy=policy, target=target, now=now)
    executor_id = uuid4()

    command = RetentionExecutionCommand.plan(
        request=request,
        policy=policy,
        target=target,
        executor_id=executor_id,
        active_legal_hold=False,
        maker_currently_eligible=True,
        checker_currently_eligible=True,
        now=now,
    )

    assert command.state is RetentionExecutionState.PLANNED
    assert request.decided_at is not None
    assert command.execution_authorization_valid_until == request.decided_at + timedelta(hours=24)
    assert command.destructive_state == AUTOMATION_DISABLED
    assert command.archive_disposition is RetentionArchiveDisposition.EVIDENCE_ONLY
    assert command.target_snapshot_hash


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("hold", "Legal Hold"),
        ("maker_revoked", "maker"),
        ("checker_revoked", "checker"),
        ("executor_is_checker", "executor"),
        ("stale_target", "target"),
        ("legacy_policy", "POLICY_BOOK_V2"),
    ],
)
def test_execution_planning_fails_closed_on_governance_drift(mutation: str, message: str) -> None:
    now = datetime.now(UTC)
    workspace_id = uuid4()
    target = ErasureTargetSnapshot(
        target_type=ErasureTargetType.CHAT_SESSION,
        target_id=uuid4(),
        version=2,
        owner_id=uuid4(),
        classification=Classification.INTERNAL,
        retention_basis_at=now - timedelta(days=30),
        retention_until=now + timedelta(days=335),
    )
    policy = _active_policy(workspace_id=workspace_id, now=now)
    request = _approved_request(workspace_id=workspace_id, policy=policy, target=target, now=now)
    if mutation == "executor_is_checker":
        assert request.checker_id is not None
        executor = request.checker_id
    else:
        executor = uuid4()
    current_target = target
    if mutation == "stale_target":
        current_target = ErasureTargetSnapshot(
            target_type=target.target_type,
            target_id=target.target_id,
            version=target.version + 1,
            owner_id=target.owner_id,
            classification=target.classification,
            retention_basis_at=target.retention_basis_at,
            retention_until=target.retention_until,
        )
    current_policy = policy
    if mutation == "legacy_policy":
        current_policy = RetentionPolicyVersion.propose(
            workspace_id=workspace_id,
            policy_number=3,
            rules=RetentionRules(30, 365, 12, 7),
            requester_id=uuid4(),
            reason="Legacy only",
            policy_decision_id=uuid4(),
        )
        current_policy.state = policy.state
        current_policy.payload_hash = request.retention_policy_hash
        current_policy.policy_id = request.retention_policy_id

    with pytest.raises((ConflictError, ValidationError), match=message):
        RetentionExecutionCommand.plan(
            request=request,
            policy=current_policy,
            target=current_target,
            executor_id=executor,
            active_legal_hold=mutation == "hold",
            maker_currently_eligible=mutation != "maker_revoked",
            checker_currently_eligible=mutation != "checker_revoked",
            now=now,
        )


def test_execution_planning_respects_minimum_retention_and_post_approval_ttl() -> None:
    now = datetime.now(UTC)
    workspace_id = uuid4()
    target = ErasureTargetSnapshot(
        target_type=ErasureTargetType.CHAT_SESSION,
        target_id=uuid4(),
        version=1,
        owner_id=uuid4(),
        classification=Classification.INTERNAL,
        retention_basis_at=now - timedelta(days=2),
        retention_until=now + timedelta(days=363),
    )
    policy = _active_policy(workspace_id=workspace_id, now=now)
    request = _approved_request(workspace_id=workspace_id, policy=policy, target=target, now=now)

    with pytest.raises(ConflictError, match="minimum retention"):
        RetentionExecutionCommand.plan(
            request=request,
            policy=policy,
            target=target,
            executor_id=uuid4(),
            active_legal_hold=False,
            maker_currently_eligible=True,
            checker_currently_eligible=True,
            now=now,
        )

    with pytest.raises(ConflictError, match="execution authorisation"):
        RetentionExecutionCommand.plan(
            request=request,
            policy=policy,
            target=ErasureTargetSnapshot(
                target_type=target.target_type,
                target_id=target.target_id,
                version=target.version,
                owner_id=target.owner_id,
                classification=target.classification,
                retention_basis_at=now - timedelta(days=30),
                retention_until=target.retention_until,
            ),
            executor_id=uuid4(),
            active_legal_hold=False,
            maker_currently_eligible=True,
            checker_currently_eligible=True,
            now=now + timedelta(hours=25),
        )


def test_execution_planning_rejects_future_dated_approval_evidence() -> None:
    now = datetime.now(UTC)
    workspace_id = uuid4()
    target = ErasureTargetSnapshot(
        target_type=ErasureTargetType.CHAT_SESSION,
        target_id=uuid4(),
        version=1,
        owner_id=uuid4(),
        classification=Classification.INTERNAL,
        retention_basis_at=now - timedelta(days=30),
        retention_until=now + timedelta(days=335),
    )
    policy = _active_policy(workspace_id=workspace_id, now=now)
    request = _approved_request(
        workspace_id=workspace_id,
        policy=policy,
        target=target,
        now=now + timedelta(hours=2),
    )

    with pytest.raises(ConflictError, match="timestamp is in the future"):
        RetentionExecutionCommand.plan(
            request=request,
            policy=policy,
            target=target,
            executor_id=uuid4(),
            active_legal_hold=False,
            maker_currently_eligible=True,
            checker_currently_eligible=True,
            now=now,
        )
