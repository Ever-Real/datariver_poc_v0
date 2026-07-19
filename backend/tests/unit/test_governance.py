from datetime import UTC, datetime
from uuid import uuid4

import pytest

from datariver.domain.authz import Classification
from datariver.domain.common import ConflictError, ValidationError
from datariver.domain.governance import (
    CHANGE_INTAKE_ASPECT,
    MANUAL_DATASET_INTAKE_TARGET,
    ApprovalDecision,
    ChangeItem,
    ChangeRequest,
    ChangeState,
    change_target_binding_hash,
)


def make_request() -> ChangeRequest:
    asset_id = uuid4()
    target_ref = "urn:li:dataset:test"
    return ChangeRequest.create(
        workspace_id=uuid4(),
        number="CR-2026-000001",
        request_type="CATALOG_METADATA",
        title="Update ownership",
        description="Set the governed owner.",
        requester_id=uuid4(),
        items=[
            ChangeItem(
                item_id=uuid4(),
                target_type="DATAHUB_ASPECT",
                target_ref=target_ref,
                operation="UPSERT",
                after_document={"owners": ["urn:li:corpuser:steward"]},
                aspect_name="ownership",
                before_hash="b" * 64,
                target_asset_id=asset_id,
                target_asset_type="DATASET",
                target_classification=Classification.INTERNAL,
                target_lifecycle="ACTIVE",
                target_source_version="1",
                target_observed_at=datetime.now(UTC),
                target_binding_hash=change_target_binding_hash(
                    target_ref=target_ref,
                    asset_id=asset_id,
                    asset_type="DATASET",
                    system_id=None,
                    domain_id=None,
                    owner_department_id=None,
                    classification=Classification.INTERNAL,
                    lifecycle="ACTIVE",
                ),
            )
        ],
    )


def move_to_final_review(request: ChangeRequest) -> None:
    actor = uuid4()
    decision = uuid4()
    request.transition(
        target=ChangeState.IN_REVIEW,
        actor_id=actor,
        reason="Review started",
        policy_decision_id=decision,
        expected_version=request.version,
    )
    request.transition(
        target=ChangeState.FINAL_REVIEW,
        actor_id=actor,
        reason="Tests attached",
        policy_decision_id=decision,
        expected_version=request.version,
    )


def test_undeclared_transition_is_rejected() -> None:
    request = make_request()

    with pytest.raises(ValidationError):
        request.transition(
            target=ChangeState.APPLYING,
            actor_id=uuid4(),
            reason="Skip review",
            policy_decision_id=uuid4(),
            expected_version=request.version,
        )


def test_changes_requested_requires_an_explicit_resubmission_before_review_restarts() -> None:
    request = make_request()
    actor = uuid4()
    request.transition(
        target=ChangeState.IN_REVIEW,
        actor_id=actor,
        reason="Review started",
        policy_decision_id=uuid4(),
        expected_version=request.version,
    )
    request.transition(
        target=ChangeState.CHANGES_REQUESTED,
        actor_id=actor,
        reason="Please supply test evidence.",
        policy_decision_id=uuid4(),
        expected_version=request.version,
    )
    with pytest.raises(ValidationError):
        request.transition(
            target=ChangeState.IN_REVIEW,
            actor_id=actor,
            reason="Cannot skip resubmission.",
            policy_decision_id=uuid4(),
            expected_version=request.version,
        )
    with pytest.raises(ValidationError, match="Only the requester"):
        request.transition(
            target=ChangeState.REGISTERED,
            actor_id=actor,
            reason="A reviewer cannot resubmit on behalf of the requester.",
            policy_decision_id=uuid4(),
            expected_version=request.version,
        )
    request.transition(
        target=ChangeState.REGISTERED,
        actor_id=request.requester_id,
        reason="Supplemented and resubmitted.",
        policy_decision_id=uuid4(),
        expected_version=request.version,
    )
    assert request.state is ChangeState.REGISTERED


def test_change_creation_requires_source_hash() -> None:
    with pytest.raises(ValidationError, match="current DataHub aspect hash"):
        ChangeRequest.create(
            workspace_id=uuid4(),
            number="CR-2026-000002",
            request_type="CATALOG_METADATA",
            title="Unsafe update",
            description="Missing optimistic concurrency guard.",
            requester_id=uuid4(),
            items=[
                ChangeItem(
                    item_id=uuid4(),
                    target_type="DATAHUB_ASPECT",
                    target_ref="urn:li:dataset:test",
                    operation="UPSERT",
                    after_document={"name": "unsafe"},
                    aspect_name="datasetProperties",
                )
            ],
        )


def test_change_creation_rejects_unmanaged_aspect() -> None:
    with pytest.raises(ValidationError, match="governed allowlist"):
        ChangeRequest.create(
            workspace_id=uuid4(),
            number="CR-2026-000003",
            request_type="CATALOG_METADATA",
            title="Unsafe update",
            description="Attempt to write an unmanaged provider aspect.",
            requester_id=uuid4(),
            items=[
                ChangeItem(
                    item_id=uuid4(),
                    target_type="DATAHUB_ASPECT",
                    target_ref="urn:li:dataset:test",
                    operation="UPSERT",
                    after_document={"value": "unsafe"},
                    aspect_name="corpSecretAspect",
                    before_hash="b" * 64,
                )
            ],
        )


def test_change_creation_rejects_multiple_items_until_checkpoints_exist() -> None:
    first = make_request().items[0]

    with pytest.raises(ValidationError, match="Exactly one change item"):
        ChangeRequest.create(
            workspace_id=uuid4(),
            number="CR-2026-000004",
            request_type="CATALOG_METADATA",
            title="Unsafe batch",
            description="Would permit a partial provider effect.",
            requester_id=uuid4(),
            items=[first, first],
        )


def test_multi_target_manual_intake_completes_only_after_independent_final_approval() -> None:
    requester = uuid4()
    items = [
        ChangeItem(
            item_id=uuid4(),
            target_type=MANUAL_DATASET_INTAKE_TARGET,
            target_ref=f"urn:datariver:proposed-dataset:{uuid4()}",
            operation="CREATE",
            aspect_name=CHANGE_INTAKE_ASPECT,
            after_document={"contract": "change-intake-v1", "table_name": table_name},
        )
        for table_name in ("wafer_forecast", "yield_forecast")
    ]
    request = ChangeRequest.create(
        workspace_id=uuid4(),
        number="CR-PLANNING-260719-ABCD",
        request_type="CHANGE_INTAKE",
        title="Forecast tables",
        description="Register proposed tables for review.",
        requester_id=requester,
        items=items,
    )
    move_to_final_review(request)
    final_approver = uuid4()
    request.add_approval(
        stage="FINAL",
        decision=ApprovalDecision.APPROVED,
        actor_id=final_approver,
        reason="Manual change and TEST evidence reviewed.",
        policy_decision_id=uuid4(),
        expected_version=request.version,
    )

    request.complete_intake(
        actor_id=uuid4(),
        reason="Developer completed the approved manual change.",
        policy_decision_id=uuid4(),
        expected_version=request.version,
    )

    assert request.state is ChangeState.COMPLETED


def test_stale_version_is_rejected() -> None:
    request = make_request()

    with pytest.raises(ConflictError):
        request.transition(
            target=ChangeState.IN_REVIEW,
            actor_id=uuid4(),
            reason="Review",
            policy_decision_id=uuid4(),
            expected_version=99,
        )


def test_requester_cannot_final_approve() -> None:
    request = make_request()
    move_to_final_review(request)

    with pytest.raises(ValidationError):
        request.add_approval(
            stage="FINAL",
            decision=ApprovalDecision.APPROVED,
            actor_id=request.requester_id,
            reason="Self approval",
            policy_decision_id=uuid4(),
            expected_version=request.version,
        )


def test_application_requires_final_approval() -> None:
    request = make_request()
    move_to_final_review(request)

    with pytest.raises(ValidationError):
        request.transition(
            target=ChangeState.APPLY_QUEUED,
            actor_id=uuid4(),
            reason="Apply",
            policy_decision_id=uuid4(),
            expected_version=request.version,
        )


def test_final_rejection_prevents_application_even_after_an_approval() -> None:
    request = make_request()
    move_to_final_review(request)
    request.add_approval(
        stage="FINAL",
        decision=ApprovalDecision.APPROVED,
        actor_id=uuid4(),
        reason="Approved",
        policy_decision_id=uuid4(),
        expected_version=request.version,
    )
    request.add_approval(
        stage="FINAL",
        decision=ApprovalDecision.REJECTED,
        actor_id=uuid4(),
        reason="Rejected",
        policy_decision_id=uuid4(),
        expected_version=request.version,
    )

    with pytest.raises(ValidationError, match="final rejection"):
        request.transition(
            target=ChangeState.APPLY_QUEUED,
            actor_id=uuid4(),
            reason="Apply",
            policy_decision_id=uuid4(),
            expected_version=request.version,
        )


def test_applied_requires_reconciled_equal_hash() -> None:
    request = make_request()
    move_to_final_review(request)
    approver = uuid4()
    request.add_approval(
        stage="FINAL",
        decision=ApprovalDecision.APPROVED,
        actor_id=approver,
        reason="Approved",
        policy_decision_id=uuid4(),
        expected_version=request.version,
    )
    request.transition(
        target=ChangeState.APPLY_QUEUED,
        actor_id=approver,
        reason="Queue",
        policy_decision_id=uuid4(),
        expected_version=request.version,
    )
    request.transition(
        target=ChangeState.APPLYING,
        actor_id=uuid4(),
        reason="Worker started",
        policy_decision_id=uuid4(),
        expected_version=request.version,
    )

    with pytest.raises(ValidationError):
        request.mark_applied(
            actor_id=uuid4(),
            policy_decision_id=uuid4(),
            expected_version=request.version,
            expected_hash="approved",
            observed_hash="different",
            reconciled=True,
        )

    request.mark_applied(
        actor_id=uuid4(),
        policy_decision_id=uuid4(),
        expected_version=request.version,
        expected_hash="approved",
        observed_hash="approved",
        reconciled=True,
    )

    assert request.state is ChangeState.APPLIED


def test_confidential_application_requires_two_distinct_final_approvers() -> None:
    request = make_request()
    request.classification = Classification.CONFIDENTIAL
    move_to_final_review(request)
    first = uuid4()
    request.add_approval(
        stage="FINAL",
        decision=ApprovalDecision.APPROVED,
        actor_id=first,
        reason="First approval",
        policy_decision_id=uuid4(),
        expected_version=request.version,
    )
    with pytest.raises(ValidationError):
        request.transition(
            target=ChangeState.APPLY_QUEUED,
            actor_id=first,
            reason="Too early",
            policy_decision_id=uuid4(),
            expected_version=request.version,
        )
    second = uuid4()
    request.add_approval(
        stage="FINAL",
        decision=ApprovalDecision.APPROVED,
        actor_id=second,
        reason="Second approval",
        policy_decision_id=uuid4(),
        expected_version=request.version,
    )
    request.transition(
        target=ChangeState.APPLY_QUEUED,
        actor_id=second,
        reason="Approved",
        policy_decision_id=uuid4(),
        expected_version=request.version,
    )
    assert request.state is ChangeState.APPLY_QUEUED
