from datariver.domain.retention import (
    AUTOMATION_DISABLED,
    ErasureRequest,
    LegalHold,
    RetentionPolicyVersion,
)
from datariver.interfaces.http.retention_schemas import (
    ErasureApprovalResponse,
    ErasureRequestResponse,
    LegalHoldActionResponse,
    LegalHoldResponse,
    RetentionClassRuleRequest,
    RetentionPolicyContractRequest,
    RetentionPolicyResponse,
    RetentionRulesRequest,
)


def retention_policy_response(policy: RetentionPolicyVersion) -> RetentionPolicyResponse:
    return RetentionPolicyResponse(
        policy_id=policy.policy_id,
        policy_number=policy.policy_number,
        rules=RetentionRulesRequest(**policy.rules.document()),
        contract_version=policy.contract_version,
        contract=(
            RetentionPolicyContractRequest(
                effective_from=policy.contract.effective_from,
                effective_until=policy.contract.effective_until,
                execution_authorization_hours=policy.contract.execution_authorization_hours,
                class_rules=tuple(
                    RetentionClassRuleRequest(**rule.document())
                    for rule in policy.contract.class_rules
                ),
            )
            if policy.contract is not None
            else None
        ),
        payload_hash=policy.payload_hash,
        requester_id=policy.requester_id,
        request_reason=policy.request_reason,
        request_policy_decision_id=policy.request_policy_decision_id,
        state=policy.state,
        checker_id=policy.checker_id,
        decision_reason=policy.decision_reason,
        decision_policy_decision_id=policy.decision_policy_decision_id,
        decided_at=policy.decided_at,
        superseded_by=policy.superseded_by,
        supersede_reason=policy.supersede_reason,
        supersede_policy_decision_id=policy.supersede_policy_decision_id,
        superseded_at=policy.superseded_at,
        version=policy.version,
        partition_automation_state=AUTOMATION_DISABLED,
        deletion_automation_state=AUTOMATION_DISABLED,
    )


def legal_hold_response(hold: LegalHold) -> LegalHoldResponse:
    return LegalHoldResponse(
        hold_id=hold.hold_id,
        data_class=hold.data_class,
        scope=hold.scope,
        scope_id=hold.scope_id,
        reason=hold.reason,
        payload_hash=hold.payload_hash,
        created_by=hold.created_by,
        create_policy_decision_id=hold.create_policy_decision_id,
        state=hold.state,
        release_requested_by=hold.release_requested_by,
        release_request_reason=hold.release_request_reason,
        release_request_policy_decision_id=hold.release_request_policy_decision_id,
        release_checker_id=hold.release_checker_id,
        release_decision_reason=hold.release_decision_reason,
        release_decision_policy_decision_id=hold.release_decision_policy_decision_id,
        released_at=hold.released_at,
        version=hold.version,
        actions=[
            LegalHoldActionResponse(
                action_id=action.action_id,
                action=action.action,
                actor_id=action.actor_id,
                reason=action.reason,
                policy_decision_id=action.policy_decision_id,
                occurred_at=action.occurred_at,
                hold_version=action.hold_version,
                payload_hash=action.payload_hash,
            )
            for action in hold.actions
        ],
        deletion_effect="BLOCKED_BY_LEGAL_HOLD" if hold.active else AUTOMATION_DISABLED,
    )


def erasure_request_response(request: ErasureRequest) -> ErasureRequestResponse:
    return ErasureRequestResponse(
        erasure_request_id=request.erasure_request_id,
        target_type=request.target_type,
        target_id=request.target_id,
        target_version=request.target_version,
        target_owner_id=request.target_owner_id,
        classification=request.classification,
        retention_policy_id=request.retention_policy_id,
        retention_policy_hash=request.retention_policy_hash,
        requester_id=request.requester_id,
        request_reason=request.request_reason,
        request_policy_decision_id=request.request_policy_decision_id,
        payload_hash=request.payload_hash,
        expires_at=request.expires_at,
        state=request.state,
        checker_id=request.checker_id,
        decision_reason=request.decision_reason,
        decision_policy_decision_id=request.decision_policy_decision_id,
        decided_at=request.decided_at,
        version=request.version,
        approvals=[
            ErasureApprovalResponse(
                approval_id=approval.approval_id,
                decision=approval.decision,
                actor_id=approval.actor_id,
                reason=approval.reason,
                policy_decision_id=approval.policy_decision_id,
                payload_hash=approval.payload_hash,
                request_version=approval.request_version,
                occurred_at=approval.occurred_at,
            )
            for approval in request.approvals
        ],
        execution_state=request.execution_state,
    )
