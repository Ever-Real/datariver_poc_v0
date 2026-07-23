from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from datariver.application.dto import (
    MembershipRoleAssignmentEvidence,
    WorkspaceMembershipAccessRecord,
    WorkspaceMembershipSummary,
)
from datariver.domain.authz import Action, Classification
from datariver.domain.common import canonical_json_hash
from datariver.interfaces.http.presenters import workspace_membership_access_response


def _record(
    *,
    groups: frozenset[str] = frozenset({"catalog-users"}),
    assignment: MembershipRoleAssignmentEvidence | None = None,
) -> WorkspaceMembershipAccessRecord:
    workspace_id, subject_id = uuid4(), uuid4()
    del workspace_id
    return WorkspaceMembershipAccessRecord(
        summary=WorkspaceMembershipSummary(
            subject_id=subject_id,
            display_name="Catalog Reader",
            subject_active=True,
            membership_active=True,
            department_id=None,
            job_function="ANALYST",
            clearance=Classification.INTERNAL,
            membership_version=7,
        ),
        groups=groups,
        allowed_actions=frozenset({Action.CATALOG_READ}),
        denied_actions=frozenset(),
        allowed_system_ids=frozenset(),
        allowed_domain_ids=frozenset(),
        role_assignment=assignment,
    )


def test_membership_response_verifies_exact_normalized_role_assignment() -> None:
    workspace_id, role_id, actor_id = (uuid4() for _ in range(3))
    record = _record()
    access_hash = canonical_json_hash(
        {
            "active": True,
            "clearance": "INTERNAL",
            "groups": ["catalog-users"],
            "allowed_actions": ["catalog.read"],
            "denied_actions": [],
            "allowed_system_ids": [],
            "allowed_domain_ids": [],
        }
    )
    record = WorkspaceMembershipAccessRecord(
        summary=record.summary,
        groups=record.groups,
        allowed_actions=record.allowed_actions,
        denied_actions=record.denied_actions,
        allowed_system_ids=record.allowed_system_ids,
        allowed_domain_ids=record.allowed_domain_ids,
        role_assignment=MembershipRoleAssignmentEvidence(
            workspace_id=workspace_id,
            subject_id=record.summary.subject_id,
            role_id=role_id,
            role_version=3,
            membership_version=7,
            access_payload_hash=access_hash,
            assigned_by=actor_id,
            assignment_version=2,
            updated_at=datetime(2026, 7, 23, tzinfo=UTC),
        ),
    )

    response = workspace_membership_access_response(record)

    assert response.role_assignment.status == "VERIFIED"
    assert response.role_assignment.role_id == role_id
    assert response.role_assignment.role_version == 3
    assert response.role_assignment.assignment_version == 2
    assert response.role_assignment.access_payload_hash == access_hash


def test_membership_response_never_promotes_legacy_marker_to_role_authority() -> None:
    response = workspace_membership_access_response(
        _record(groups=frozenset({"catalog-users", "datariver-role-catalog-reader"}))
    )

    assert response.role_assignment.status == "LEGACY_UNVERIFIED"
    assert response.role_assignment.role_id is None
    assert response.role_assignment.legacy_markers == ["datariver-role-catalog-reader"]


def test_membership_response_flags_assignment_evidence_drift() -> None:
    workspace_id, subject_id, role_id, actor_id = (uuid4() for _ in range(4))
    response = workspace_membership_access_response(
        _record(
            assignment=MembershipRoleAssignmentEvidence(
                workspace_id=workspace_id,
                subject_id=subject_id,
                role_id=role_id,
                role_version=1,
                membership_version=6,
                access_payload_hash="f" * 64,
                assigned_by=actor_id,
                assignment_version=1,
                updated_at=datetime(2026, 7, 23, tzinfo=UTC),
            )
        )
    )

    assert response.role_assignment.status == "EVIDENCE_MISMATCH"
