from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from datariver.domain.authz import Action, Classification
from datariver.domain.common import ConflictError
from datariver.infrastructure.db.admin_access import _membership_access_record
from datariver.infrastructure.db.models.platform import SubjectModel, WorkspaceMembershipModel


def _stored_membership() -> tuple[SubjectModel, WorkspaceMembershipModel]:
    subject_id, workspace_id, department_id, system_id, domain_id = (uuid4() for _ in range(5))
    subject = SubjectModel(
        id=subject_id,
        issuer="https://identity.example.internal/realms/company",
        external_subject="external-subject",
        display_name="Security Administrator",
        active=True,
    )
    membership = WorkspaceMembershipModel(
        workspace_id=workspace_id,
        subject_id=subject_id,
        department_id=department_id,
        job_function="SECURITY_ADMINISTRATOR",
        clearance=int(Classification.RESTRICTED),
        attributes={
            "groups": ["security-administrators"],
            "allowed_actions": [Action.ADMIN_MANAGE.value, Action.CATALOG_READ.value],
            "denied_actions": [Action.CHAT_QUERY.value],
            "allowed_system_ids": [str(system_id)],
            "allowed_domain_ids": [str(domain_id)],
            "managed_by": "WORKSPACE_MEMBERSHIP_ACCESS_UPDATE_V1",
        },
        active=True,
        access_expires_at=datetime(2027, 1, 1, tzinfo=UTC),
        version=7,
    )
    return subject, membership


def test_membership_repository_mapping_returns_the_exact_typed_access_document() -> None:
    subject, membership = _stored_membership()

    record = _membership_access_record(subject, membership)

    assert record.summary.subject_id == subject.id
    assert record.summary.display_name == "Security Administrator"
    assert record.summary.department_id == membership.department_id
    assert record.summary.job_function == "SECURITY_ADMINISTRATOR"
    assert record.summary.clearance is Classification.RESTRICTED
    assert record.summary.membership_version == 7
    assert record.groups == frozenset({"security-administrators"})
    assert record.allowed_actions == frozenset({Action.ADMIN_MANAGE, Action.CATALOG_READ})
    assert record.denied_actions == frozenset({Action.CHAT_QUERY})
    assert {str(value) for value in record.allowed_system_ids} == set(
        membership.attributes["allowed_system_ids"]
    )


def test_membership_repository_mapping_fails_closed_on_unknown_action() -> None:
    subject, membership = _stored_membership()
    membership.attributes["allowed_actions"] = ["provider.arbitrary-action"]

    with pytest.raises(ConflictError, match="stored workspace membership access is invalid"):
        _membership_access_record(subject, membership)
