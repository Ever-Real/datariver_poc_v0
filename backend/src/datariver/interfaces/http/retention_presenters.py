from datariver.domain.retention import AUTOMATION_DISABLED, LegalHold, RetentionPolicyVersion
from datariver.interfaces.http.retention_schemas import (
    LegalHoldActionResponse,
    LegalHoldResponse,
    RetentionPolicyResponse,
    RetentionRulesRequest,
)


def retention_policy_response(policy: RetentionPolicyVersion) -> RetentionPolicyResponse:
    return RetentionPolicyResponse(
        policy_id=policy.policy_id,
        policy_number=policy.policy_number,
        rules=RetentionRulesRequest(**policy.rules.document()),
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
