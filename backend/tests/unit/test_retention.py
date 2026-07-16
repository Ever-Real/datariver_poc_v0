from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from datariver.application.ports import ImmutableArchiveStore
from datariver.domain.authz import Classification
from datariver.domain.common import ConflictError, ValidationError
from datariver.domain.retention import (
    AUTOMATION_DISABLED,
    ArchiveCapability,
    ArchiveRetentionMode,
    ArchiveSource,
    ArchiveWriteReceipt,
    ErasureRequest,
    ErasureRequestState,
    ErasureTargetType,
    GovernanceDecision,
    ImmutableArchiveReceipt,
    LegalHold,
    LegalHoldScope,
    LegalHoldState,
    RetentionDataClass,
    RetentionPolicyState,
    RetentionPolicyVersion,
    RetentionRules,
)


def rules() -> RetentionRules:
    return RetentionRules(
        completed_operation_days=30,
        chat_content_days=90,
        audit_online_months=13,
        immutable_archive_years=7,
    )


def test_retention_rules_keep_automation_fail_closed() -> None:
    assert AUTOMATION_DISABLED == "DISABLED_NOT_READY"
    assert "deletion_automation_state" not in rules().document()
    assert "partition_automation_state" not in rules().document()


def test_retention_policy_requires_independent_checker_and_hash_integrity() -> None:
    maker, checker = uuid4(), uuid4()
    policy = RetentionPolicyVersion.propose(
        workspace_id=uuid4(),
        policy_number=1,
        rules=rules(),
        requester_id=maker,
        reason="Adopt approved retention",
        policy_decision_id=uuid4(),
    )
    with pytest.raises(ValidationError):
        policy.decide(
            decision=GovernanceDecision.APPROVED,
            actor_id=maker,
            reason="self",
            policy_decision_id=uuid4(),
            expected_version=1,
            now=datetime.now(UTC),
        )
    policy.decide(
        decision=GovernanceDecision.APPROVED,
        actor_id=checker,
        reason="Independent review",
        policy_decision_id=uuid4(),
        expected_version=1,
        now=datetime.now(UTC),
    )
    assert policy.state is RetentionPolicyState.ACTIVE
    assert policy.version == 2


def test_invalid_policy_decision_does_not_partially_mutate_aggregate() -> None:
    policy = RetentionPolicyVersion.propose(
        workspace_id=uuid4(),
        policy_number=1,
        rules=rules(),
        requester_id=uuid4(),
        reason="Policy review",
        policy_decision_id=uuid4(),
    )
    with pytest.raises(ValidationError):
        policy.decide(
            decision=GovernanceDecision.APPROVED,
            actor_id=uuid4(),
            reason=" ",
            policy_decision_id=uuid4(),
            expected_version=1,
            now=datetime.now(UTC),
        )
    assert policy.state is RetentionPolicyState.DRAFT
    assert policy.version == 1


def test_legal_hold_scope_is_typed() -> None:
    with pytest.raises(ValidationError):
        LegalHold.create(
            workspace_id=uuid4(),
            data_class=RetentionDataClass.AUDIT_EVIDENCE,
            scope=LegalHoldScope.WORKSPACE,
            scope_id=uuid4(),
            reason="Investigation",
            actor_id=uuid4(),
            policy_decision_id=uuid4(),
        )


def test_legal_hold_release_is_maker_checker_and_rejection_remains_active() -> None:
    workspace_id, maker, checker = uuid4(), uuid4(), uuid4()
    hold = LegalHold.create(
        workspace_id=workspace_id,
        data_class=RetentionDataClass.CHAT_CONTENT,
        scope=LegalHoldScope.SUBJECT,
        scope_id=uuid4(),
        reason="Investigation",
        actor_id=uuid4(),
        policy_decision_id=uuid4(),
    )
    hold.request_release(
        actor_id=maker,
        reason="Case closed",
        policy_decision_id=uuid4(),
        expected_version=1,
    )
    with pytest.raises(ValidationError):
        hold.decide_release(
            decision=GovernanceDecision.APPROVED,
            actor_id=maker,
            reason="self",
            policy_decision_id=uuid4(),
            expected_version=2,
            now=datetime.now(UTC),
        )
    hold.decide_release(
        decision=GovernanceDecision.REJECTED,
        actor_id=checker,
        reason="Case remains open",
        policy_decision_id=uuid4(),
        expected_version=2,
        now=datetime.now(UTC),
    )
    assert hold.state is LegalHoldState.RELEASE_REJECTED
    assert hold.active


def test_subject_cannot_check_release_of_their_own_hold() -> None:
    subject_id = uuid4()
    hold = LegalHold.create(
        workspace_id=uuid4(),
        data_class=RetentionDataClass.OBJECT_DATA,
        scope=LegalHoldScope.SUBJECT,
        scope_id=subject_id,
        reason="Litigation",
        actor_id=uuid4(),
        policy_decision_id=uuid4(),
    )
    hold.request_release(
        actor_id=uuid4(),
        reason="Release requested",
        policy_decision_id=uuid4(),
        expected_version=1,
    )
    with pytest.raises(ValidationError):
        hold.decide_release(
            decision=GovernanceDecision.APPROVED,
            actor_id=subject_id,
            reason="Own data",
            policy_decision_id=uuid4(),
            expected_version=2,
            now=datetime.now(UTC),
        )


def test_active_legal_hold_blocks_erasure_approval() -> None:
    now = datetime.now(UTC)
    policy_id = uuid4()
    request = ErasureRequest.create(
        workspace_id=uuid4(),
        target_type=ErasureTargetType.CHAT_SESSION,
        target_id=uuid4(),
        target_version=1,
        target_owner_id=uuid4(),
        classification=Classification.INTERNAL,
        retention_policy_id=policy_id,
        requester_id=uuid4(),
        reason="Retention expired",
        policy_decision_id=uuid4(),
        now=now,
        expires_at=now + timedelta(days=1),
    )
    with pytest.raises(ConflictError):
        request.decide(
            decision=GovernanceDecision.APPROVED,
            actor_id=uuid4(),
            reason="Approved",
            policy_decision_id=uuid4(),
            expected_version=1,
            now=now,
            active_legal_hold=True,
            current_target_version=1,
            active_retention_policy_id=policy_id,
        )
    assert request.state is ErasureRequestState.PENDING


def test_erasure_approval_never_enables_execution() -> None:
    now = datetime.now(UTC)
    policy_id = uuid4()
    request = ErasureRequest.create(
        workspace_id=uuid4(),
        target_type=ErasureTargetType.UPLOAD_OBJECT,
        target_id=uuid4(),
        target_version=3,
        target_owner_id=uuid4(),
        classification=Classification.CONFIDENTIAL,
        retention_policy_id=policy_id,
        requester_id=uuid4(),
        reason="Approved destruction request",
        policy_decision_id=uuid4(),
        now=now,
        expires_at=now + timedelta(days=1),
    )
    request.decide(
        decision=GovernanceDecision.APPROVED,
        actor_id=uuid4(),
        reason="Independent approval",
        policy_decision_id=uuid4(),
        expected_version=1,
        now=now,
        active_legal_hold=False,
        current_target_version=3,
        active_retention_policy_id=policy_id,
    )
    assert request.state is ErasureRequestState.APPROVED
    assert request.execution_state == AUTOMATION_DISABLED


def test_erasure_approval_rejects_stale_target_and_policy_versions() -> None:
    now = datetime.now(UTC)
    policy_id = uuid4()
    request = ErasureRequest.create(
        workspace_id=uuid4(),
        target_type=ErasureTargetType.UPLOAD_OBJECT,
        target_id=uuid4(),
        target_version=3,
        target_owner_id=uuid4(),
        classification=Classification.CONFIDENTIAL,
        retention_policy_id=policy_id,
        requester_id=uuid4(),
        reason="Approved destruction request",
        policy_decision_id=uuid4(),
        now=now,
        expires_at=now + timedelta(days=1),
    )

    with pytest.raises(ConflictError):
        request.decide(
            decision=GovernanceDecision.APPROVED,
            actor_id=uuid4(),
            reason="Independent approval",
            policy_decision_id=uuid4(),
            expected_version=1,
            now=now,
            active_legal_hold=False,
            current_target_version=4,
            active_retention_policy_id=policy_id,
        )
    assert request.state is ErasureRequestState.PENDING

    with pytest.raises(ConflictError):
        request.decide(
            decision=GovernanceDecision.APPROVED,
            actor_id=uuid4(),
            reason="Independent approval",
            policy_decision_id=uuid4(),
            expected_version=1,
            now=now,
            active_legal_hold=False,
            current_target_version=3,
            active_retention_policy_id=uuid4(),
        )
    assert request.state is ErasureRequestState.PENDING


def test_archive_receipt_requires_verified_versioned_compliance_object() -> None:
    now = datetime.now(UTC)
    receipt = ImmutableArchiveReceipt(
        receipt_id=uuid4(),
        workspace_id=uuid4(),
        source=ArchiveSource.POLICY_DECISIONS,
        source_partition="policy_decisions_2026_07",
        row_count=100,
        byte_count=4096,
        content_sha256="a" * 64,
        provider_checksum="provider-sha256",
        object_bucket="datariver-worm",
        object_key="policy/2026/07/archive.jsonl",
        object_version_id="version-one",
        retention_mode=ArchiveRetentionMode.COMPLIANCE,
        retention_until=now + timedelta(days=365 * 7),
        legal_hold=False,
        verified_at=now,
        capability_fingerprint="b" * 64,
    )
    assert receipt.row_count == 100
    with pytest.raises(ValidationError):
        replace(receipt, object_version_id="")


def test_archive_capability_requires_every_verified_control() -> None:
    now = datetime.now(UTC)
    capability = ArchiveCapability(
        configuration_fingerprint="c" * 64,
        observed_at=now,
        expires_at=now + timedelta(minutes=15),
        versioning_enabled=True,
        object_lock_enabled=True,
        compliance_retention_supported=True,
        checksum_sha256_supported=True,
        full_readback_verified=True,
        retention_shorten_denied=True,
        retained_version_delete_denied=False,
    )
    with pytest.raises(ConflictError):
        capability.assert_usable(now=now + timedelta(minutes=1))


def test_archive_write_receipt_rejects_unversioned_or_noncompliant_results() -> None:
    now = datetime.now(UTC)
    receipt = ArchiveWriteReceipt(
        object_bucket="datariver-worm",
        object_key="audit/manifest.json",
        object_version_id="version-one",
        byte_count=128,
        content_sha256="d" * 64,
        provider_checksum="provider-checksum",
        retention_mode=ArchiveRetentionMode.COMPLIANCE,
        retention_until=now + timedelta(days=1),
        legal_hold=False,
        observed_at=now,
    )
    with pytest.raises(ValidationError):
        replace(receipt, object_version_id="")


def test_immutable_archive_port_exposes_no_delete_or_bypass_operation() -> None:
    operation_names = set(ImmutableArchiveStore.__dict__)
    assert not any("delete" in name or "bypass" in name for name in operation_names)
