from __future__ import annotations

from datariver.application.dto import (
    AdminReadContext,
    CatalogAssetDetail,
    CatalogAssetIndex,
    ChangeRequestSchemaOverview,
    WorkspaceMembershipAccessRecord,
    WorkspaceMembershipSummary,
)
from datariver.domain.admin_access import AdminAccessRequest
from datariver.domain.common import canonical_json_hash
from datariver.domain.governance import ChangeRequest
from datariver.interfaces.http.schemas import (
    AdminAccessApprovalResponse,
    AdminAccessRequestResponse,
    AdminReadContextResponse,
    ApprovalAuthorityResponse,
    ApprovalResponse,
    CatalogAssetResponse,
    CatalogAssetSummary,
    ChangeItemResponse,
    ChangeRequestAssigneeResponse,
    ChangeRequestResponse,
    ChangeRequestRoundResponse,
    ChangeRequestSchemaOverviewResponse,
    ChangeTestRunResponse,
    MembershipAccessCommandResponse,
    MembershipAccessDocumentRequest,
    MembershipAccessDocumentResponse,
    MembershipRoleAssignmentEvidenceResponse,
    TransitionResponse,
    WorkspaceMembershipAccessResponse,
    WorkspaceMembershipSummaryResponse,
)


def admin_access_request_response(request: AdminAccessRequest) -> AdminAccessRequestResponse:
    access = request.command.access_document()
    return AdminAccessRequestResponse(
        id=request.access_request_id,
        workspace_id=request.workspace_id,
        requester_id=request.requester_id,
        request_reason=request.request_reason,
        request_policy_decision_id=request.request_policy_decision_id,
        command=MembershipAccessCommandResponse(
            command_type="WORKSPACE_MEMBERSHIP_ACCESS_UPDATE_V1",
            workspace_id=request.workspace_id,
            target_subject_id=request.command.target_subject_id,
            expected_membership_version=request.command.expected_membership_version,
            access=MembershipAccessDocumentRequest.model_validate(access),
        ),
        payload_hash=request.payload_hash,
        state=request.state.value,
        version=request.version,
        expires_at=request.expires_at,
        checker_id=request.checker_id,
        consumed_by=request.consumed_by,
        consumed_at=request.consumed_at,
        consume_policy_decision_id=request.consume_policy_decision_id,
        approvals=[
            AdminAccessApprovalResponse(
                id=approval.approval_id,
                decision=approval.decision.value,
                actor_id=approval.actor_id,
                reason=approval.reason,
                policy_decision_id=approval.policy_decision_id,
                payload_hash=approval.payload_hash,
                request_version=approval.request_version,
                occurred_at=approval.occurred_at,
            )
            for approval in request.approvals
        ],
    )


def workspace_membership_summary_response(
    membership: WorkspaceMembershipSummary,
) -> WorkspaceMembershipSummaryResponse:
    return WorkspaceMembershipSummaryResponse(
        subject_id=membership.subject_id,
        display_name=membership.display_name,
        email=membership.email,
        last_login_at=membership.last_login_at,
        last_login_ip=membership.last_login_ip,
        owned_table_count=membership.owned_table_count,
        change_request_count=membership.change_request_count,
        joined_at=membership.joined_at,
        access_expires_at=membership.access_expires_at,
        renewal_eligible_at=membership.renewal_eligible_at,
        access_expired=membership.access_expired,
        renewal_request_eligible=membership.renewal_request_eligible,
        pending_renewal_request_id=membership.pending_renewal_request_id,
        subject_active=membership.subject_active,
        membership_active=membership.membership_active,
        department_id=membership.department_id,
        job_function=membership.job_function,
        clearance=membership.clearance.name,
        membership_version=membership.membership_version,
    )


def workspace_membership_access_response(
    membership: WorkspaceMembershipAccessRecord,
) -> WorkspaceMembershipAccessResponse:
    summary = membership.summary
    access_document = {
        "active": summary.membership_active,
        "clearance": summary.clearance.name,
        "groups": sorted(membership.groups),
        "allowed_actions": sorted(action.value for action in membership.allowed_actions),
        "denied_actions": sorted(action.value for action in membership.denied_actions),
        "allowed_system_ids": sorted(str(value) for value in membership.allowed_system_ids),
        "allowed_domain_ids": sorted(str(value) for value in membership.allowed_domain_ids),
    }
    assignment = membership.role_assignment
    legacy_markers = sorted(
        group for group in membership.groups if group.startswith("datariver-role-")
    )
    if assignment is None:
        assignment_response = MembershipRoleAssignmentEvidenceResponse(
            status="LEGACY_UNVERIFIED" if legacy_markers else "MANUAL",
            legacy_markers=legacy_markers,
        )
    else:
        evidence_matches = (
            assignment.subject_id == summary.subject_id
            and assignment.membership_version == summary.membership_version
            and assignment.access_payload_hash == canonical_json_hash(access_document)
        )
        assignment_response = MembershipRoleAssignmentEvidenceResponse(
            status="VERIFIED" if evidence_matches else "EVIDENCE_MISMATCH",
            role_id=assignment.role_id,
            role_version=assignment.role_version,
            assignment_version=assignment.assignment_version,
            membership_version=assignment.membership_version,
            access_payload_hash=assignment.access_payload_hash,
            assigned_by=assignment.assigned_by,
            updated_at=assignment.updated_at,
            legacy_markers=legacy_markers,
        )
    return WorkspaceMembershipAccessResponse(
        subject_id=summary.subject_id,
        display_name=summary.display_name,
        subject_active=summary.subject_active,
        department_id=summary.department_id,
        job_function=summary.job_function,
        membership_version=summary.membership_version,
        access=MembershipAccessDocumentResponse(
            active=summary.membership_active,
            clearance=summary.clearance.name,
            groups=sorted(membership.groups),
            allowed_actions=sorted(membership.allowed_actions, key=lambda action: action.value),
            denied_actions=sorted(membership.denied_actions, key=lambda action: action.value),
            allowed_system_ids=sorted(membership.allowed_system_ids, key=str),
            allowed_domain_ids=sorted(membership.allowed_domain_ids, key=str),
        ),
        role_assignment=assignment_response,
    )


def admin_read_context_response(context: AdminReadContext) -> AdminReadContextResponse:
    return AdminReadContextResponse(
        subject_id=context.membership.subject_id,
        workspace_id=context.workspace_id,
        display_name=context.membership.display_name,
        authentication_assurance=context.authentication_assurance.value,
        fallback_enabled=context.fallback_enabled,
        allowed_operations=[operation.value for operation in context.allowed_operations],
        action_vocabulary=list(context.action_vocabulary),
    )


def catalog_summary(asset: CatalogAssetIndex) -> CatalogAssetSummary:
    return CatalogAssetSummary(
        id=asset.asset_id,
        external_urn=asset.external_urn,
        asset_type=asset.asset_type,
        name=asset.name,
        description=asset.description,
        platform=asset.platform,
        database_name=asset.database_name,
        schema_name=asset.schema_name,
        owner=asset.owner,
        domain=asset.domain,
        tags=list(asset.tags),
        terms=list(asset.glossary_terms),
        created_at=asset.created_at,
        classification=asset.classification.name,
        lifecycle=asset.lifecycle,
        observed_at=asset.observed_at,
        matches=[
            {
                "field": fragment.field,
                "text": fragment.text,
                "matched_terms": list(fragment.matched_terms),
            }
            for fragment in asset.matches
        ],
    )


def catalog_detail(
    asset: CatalogAssetDetail,
    *,
    field_offset: int = 0,
    field_limit: int = 100,
) -> CatalogAssetResponse:
    summary = catalog_summary(asset.index)
    field_end = field_offset + field_limit
    fields_available = len(asset.schema_fields)
    fields_total = (
        asset.schema_fields_total if asset.schema_fields_total is not None else fields_available
    )
    return CatalogAssetResponse(
        **summary.model_dump(),
        ownership=list(asset.ownership),
        glossary_terms=list(asset.glossary_terms),
        schema_fields=list(asset.schema_fields[field_offset:field_end]),
        schema_fields_total=fields_total,
        schema_fields_available=fields_available,
        schema_fields_truncated=asset.schema_fields_truncated,
        schema_fields_total_exact=asset.schema_fields_total_exact,
        schema_fields_offset=field_offset,
        schema_fields_limit=field_limit,
        schema_fields_has_more=field_end < fields_available,
        quality=asset.quality,
        projection_source_version=asset.index.source_version,
        source_version=asset.raw_version,
        stale_at=asset.stale_at,
    )


def change_request_response(change_request: ChangeRequest) -> ChangeRequestResponse:
    return ChangeRequestResponse(
        id=change_request.change_request_id,
        number=change_request.number,
        request_type=change_request.request_type,
        title=change_request.title,
        description=change_request.description,
        state=change_request.state.value,
        requester_id=change_request.requester_id,
        requester_department_id=change_request.requester_department_id,
        current_round_id=change_request.current_round_id,
        current_round_number=change_request.current_round_number,
        created_at=change_request.created_at,
        requested_due_date=change_request.requested_due_date,
        priority=change_request.priority.value if change_request.priority is not None else None,
        urgency=change_request.urgency.value if change_request.urgency is not None else None,
        classification=change_request.classification.name,
        version=change_request.version,
        items=[
            ChangeItemResponse(
                id=item.item_id,
                target_type=item.target_type,
                target_ref=item.target_ref,
                aspect_name=item.aspect_name,
                operation=item.operation,
                before_hash=item.before_hash,
                after_hash=item.after_hash,
                after_document=item.after_document,
                target_asset_id=item.target_asset_id,
                target_asset_type=item.target_asset_type,
                target_system_id=item.target_system_id,
                target_domain_id=item.target_domain_id,
                target_owner_department_id=item.target_owner_department_id,
                target_classification=(
                    item.target_classification.name
                    if item.target_classification is not None
                    else None
                ),
                target_lifecycle=item.target_lifecycle,
                target_source_version=item.target_source_version,
                target_observed_at=item.target_observed_at,
                target_binding_hash=item.target_binding_hash,
                routing_system_id=item.routing_system_id,
            )
            for item in change_request.items
        ],
        approvals=[
            ApprovalResponse(
                id=approval.approval_id,
                stage=approval.stage,
                decision=approval.decision.value,
                actor_id=approval.actor_id,
                reason=approval.reason,
                occurred_at=approval.occurred_at,
                round_id=approval.round_id,
                authorities=[
                    ApprovalAuthorityResponse(
                        kind=authority.kind.value,
                        system_id=authority.system_id,
                    )
                    for authority in approval.authorities
                ],
            )
            for approval in change_request.approvals
        ],
        transitions=[
            TransitionResponse(
                id=transition.transition_id,
                from_state=transition.from_state.value,
                to_state=transition.to_state.value,
                actor_id=transition.actor_id,
                reason=transition.reason,
                occurred_at=transition.occurred_at,
                round_id=transition.round_id,
            )
            for transition in change_request.transitions
        ],
        rounds=[
            ChangeRequestRoundResponse(
                id=round_value.round_id,
                round_number=round_value.round_number,
                submitted_by=round_value.submitted_by,
                submitted_at=round_value.submitted_at,
                closed_at=round_value.closed_at,
                evidence_hash=round_value.evidence_hash,
            )
            for round_value in change_request.rounds
        ],
        test_runs=[
            ChangeTestRunResponse(
                id=test_run.test_run_id,
                round_id=test_run.round_id,
                system_id=test_run.system_id,
                attachment_id=test_run.attachment_id,
                state=test_run.state.value,
                plan_hash=test_run.plan_hash,
                result_hash=test_run.result_hash,
                bounded_summary=test_run.bounded_summary,
                recorded_by=test_run.recorded_by,
                occurred_at=test_run.occurred_at,
            )
            for test_run in change_request.test_runs
        ],
    )


def change_request_schema_overview_response(
    overview: ChangeRequestSchemaOverview,
) -> ChangeRequestSchemaOverviewResponse:
    return ChangeRequestSchemaOverviewResponse(
        platform=overview.platform,
        database_name=overview.database_name,
        schema_name=overview.schema_name,
        system_id=overview.system_id,
        system_code=overview.system_code,
        system_name=overview.system_name,
        assignees=[
            ChangeRequestAssigneeResponse(
                subject_id=assignee.subject_id,
                display_name=assignee.display_name,
                responsibility=assignee.responsibility,
                priority=assignee.priority,
            )
            for assignee in overview.assignees
        ],
        pending_count=overview.pending_count,
        total_count=overview.total_count,
        received_count=overview.received_count,
        recheck_count=overview.recheck_count,
        testing_count=overview.testing_count,
        final_review_count=overview.final_review_count,
        completed_count=overview.completed_count,
    )
