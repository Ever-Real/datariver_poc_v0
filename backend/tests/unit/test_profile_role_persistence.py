from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import CheckConstraint, Table

from datariver.application.dto import CanonicalAdminBindingEvidence
from datariver.domain.authz import Classification
from datariver.domain.capability_catalog import (
    CANONICAL_ADMIN_CAPABILITY_HASH,
    CANONICAL_ADMIN_ROLE_KEY,
    CAPABILITY_CATALOG_VERSION,
    DEFAULT_HUMAN_ADMIN_ACTIONS,
)
from datariver.domain.profile_roles import (
    PROFILE_ROLE_BY_TIER,
    PROFILE_ROLE_POLICY_VERSION,
    EffectiveProfileRoleStatus,
    ProfileRoleTier,
)
from datariver.infrastructure.db.admin_access import (
    _profile_role_assignment_evidence,
    membership_access_payload_hash,
)
from datariver.infrastructure.db.authz import _canonical_admin_binding_is_current
from datariver.infrastructure.db.models.platform import (
    AccessRoleModel,
    CanonicalAdminBindingModel,
    ProfileRoleAssignmentEventModel,
    ProfileRoleAssignmentModel,
    SubjectModel,
    WorkspaceMembershipModel,
)
from datariver.infrastructure.db.profile_role_sql import (
    CANONICAL_ADMIN_PROFILE_TRANSITION_FUNCTION_SQL,
    PROFILE_ROLE_ASSIGNMENT_FUNCTION_SQL,
    PROFILE_ROLE_SECURITY_SQL,
)


def test_profile_role_tables_separate_current_assignment_from_append_only_events() -> None:
    assignment = cast(Table, ProfileRoleAssignmentModel.__table__)
    events = cast(Table, ProfileRoleAssignmentEventModel.__table__)

    assert {"workspace_id", "subject_id"} == {
        column.name for column in assignment.primary_key.columns
    }
    assert {
        "tier",
        "policy_version",
        "materialized_actions_hash",
        "membership_version",
        "state",
        "assigned_by",
        "reason",
        "assurance",
        "version",
    } <= set(assignment.c.keys())
    assert {
        "previous_tier",
        "next_tier",
        "assignment_version",
        "policy_decision_id",
        "occurred_at",
    } <= set(events.c.keys())
    event_checks = {
        constraint.name
        for constraint in events.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ck_profile_role_assignment_events_event_type_vocabulary" in event_checks


def test_profile_role_sql_keeps_generic_role_and_profile_authority_exclusive() -> None:
    assignment_sql = PROFILE_ROLE_ASSIGNMENT_FUNCTION_SQL
    transition_sql = CANONICAL_ADMIN_PROFILE_TRANSITION_FUNCTION_SQL
    security_sql = "\n".join(PROFILE_ROLE_SECURITY_SQL)

    assert "UPDATE iam.access_role_assignments" in assignment_sql
    assert "active = FALSE" in assignment_sql
    assert "INSERT INTO iam.access_role_assignment_events" in assignment_sql
    assert "Canonical Admin demotion requires the protected transition" in assignment_sql
    assert "p_assurance <> 'HARDWARE_WEBAUTHN'" in transition_sql
    assert "The actor Canonical Admin binding is not current" in transition_sql
    assert "The last Canonical Admin cannot be demoted" in transition_sql
    assert "current_binding.state = 'REVOKED'" in transition_sql
    assert "p_expected_binding_version <> current_binding.version" in transition_sql
    assert "binding.canonical_role_version = actor_role.version" in transition_sql
    assert "binding.capability_hash =" in transition_sql
    assert "actor_role.allowed_actions =" in transition_sql
    assert "membership.attributes -> 'allowed_actions'" in transition_sql
    assert "JOIN iam.access_roles AS role" in transition_sql
    assert "binding.membership_version = membership.version" in transition_sql
    assert "p_policy_decision_id" in assignment_sql
    assert "p_policy_decision_id" in transition_sql
    assert "GRANT SELECT ON iam.profile_role_assignments" in security_sql
    assert "REVOKE INSERT, UPDATE, DELETE ON iam.profile_role_assignments" in security_sql
    assert "GRANT INSERT" not in security_sql


def test_canonical_admin_currentness_preserves_unrelated_non_authority_groups() -> None:
    now = datetime.now(UTC)
    workspace_id, subject_id, role_id, system_id, domain_id = (uuid4() for _ in range(5))
    actions = sorted(action.value for action in DEFAULT_HUMAN_ADMIN_ACTIONS)
    subject = SubjectModel(
        id=subject_id,
        issuer="https://identity.example/realms/datariver",
        external_subject="canonical-admin",
        display_name="Canonical Administrator",
        email="admin@example.test",
        active=True,
        created_at=now,
        updated_at=now,
    )
    membership = WorkspaceMembershipModel(
        workspace_id=workspace_id,
        subject_id=subject_id,
        department_id=None,
        job_function="SECURITY_ADMINISTRATOR",
        clearance=int(Classification.RESTRICTED),
        attributes={
            "groups": ["engineering", "security-administrators"],
            "allowed_actions": actions,
            "denied_actions": [],
            "allowed_system_ids": [str(system_id)],
            "allowed_domain_ids": [str(domain_id)],
        },
        active=True,
        access_expires_at=None,
        version=4,
        created_at=now,
        updated_at=now,
    )
    role = AccessRoleModel(
        id=role_id,
        workspace_id=workspace_id,
        role_key=CANONICAL_ADMIN_ROLE_KEY,
        role_kind="CANONICAL_ADMIN",
        management_source="SERVER_CANONICAL",
        capability_catalog_version=CAPABILITY_CATALOG_VERSION,
        name="Canonical Administrator",
        description="Server-owned Canonical Admin definition.",
        clearance=int(Classification.RESTRICTED),
        groups=["security-administrators"],
        allowed_actions=actions,
        denied_actions=[],
        allowed_system_ids=[],
        allowed_domain_ids=[],
        active=True,
        updated_by=None,
        version=2,
        created_at=now,
        updated_at=now,
    )
    binding = CanonicalAdminBindingModel(
        workspace_id=workspace_id,
        subject_id=subject_id,
        canonical_role_id=role_id,
        role_kind="CANONICAL_ADMIN",
        canonical_role_version=2,
        capability_catalog_version=CAPABILITY_CATALOG_VERSION,
        capability_hash=CANONICAL_ADMIN_CAPABILITY_HASH,
        membership_version=4,
        membership_access_hash=membership_access_payload_hash(membership),
        state="ACTIVE",
        binding_source="GOVERNED_ADMIN_ASSIGNMENT",
        version=3,
        created_at=now,
        updated_at=now,
    )

    assert _canonical_admin_binding_is_current(
        subject=subject,
        membership=membership,
        binding=binding,
        role=role,
        now=now,
    )
    transition_sql = CANONICAL_ADMIN_PROFILE_TRANSITION_FUNCTION_SQL
    assert transition_sql.count("? 'security-administrators'") >= 2
    assert transition_sql.count("? 'service-accounts'") >= 2
    assert transition_sql.count("membership_group.value LIKE 'datariver-role-%'") >= 2

    binding.membership_access_hash = "0" * 64
    assert not _canonical_admin_binding_is_current(
        subject=subject, membership=membership, binding=binding, role=role, now=now
    )
    binding.membership_access_hash = membership_access_payload_hash(membership)
    binding.membership_version -= 1
    assert not _canonical_admin_binding_is_current(
        subject=subject, membership=membership, binding=binding, role=role, now=now
    )
    binding.membership_version = membership.version

    role.allowed_domain_ids = [str(domain_id)]
    assert not _canonical_admin_binding_is_current(
        subject=subject, membership=membership, binding=binding, role=role, now=now
    )
    role.allowed_domain_ids = []
    membership.attributes["groups"] = [
        "engineering",
        "security-administrators",
        "service-accounts",
    ]
    binding.membership_access_hash = membership_access_payload_hash(membership)
    assert not _canonical_admin_binding_is_current(
        subject=subject, membership=membership, binding=binding, role=role, now=now
    )
    membership.attributes["groups"] = ["engineering", "security-administrators"]
    membership.attributes["allowed_actions"] = actions[:-1]
    binding.membership_access_hash = membership_access_payload_hash(membership)
    assert not _canonical_admin_binding_is_current(
        subject=subject, membership=membership, binding=binding, role=role, now=now
    )
    membership.attributes["allowed_actions"] = actions
    binding.capability_catalog_version = "STALE_CATALOG"
    binding.membership_access_hash = membership_access_payload_hash(membership)
    assert not _canonical_admin_binding_is_current(
        subject=subject, membership=membership, binding=binding, role=role, now=now
    )

    binding.capability_catalog_version = CAPABILITY_CATALOG_VERSION
    membership.attributes["allowed_system_ids"] = [str(system_id), str(uuid4())]
    membership.version += 1
    assert not _canonical_admin_binding_is_current(
        subject=subject, membership=membership, binding=binding, role=role, now=now
    )
    binding.membership_version = membership.version
    binding.membership_access_hash = membership_access_payload_hash(membership)
    assert _canonical_admin_binding_is_current(
        subject=subject, membership=membership, binding=binding, role=role, now=now
    )


@pytest.mark.parametrize(
    ("tier", "policy_version", "actions_hash", "assignment_version", "state", "expected"),
    [
        (
            "ENGINEER_STEWARD",
            PROFILE_ROLE_POLICY_VERSION,
            PROFILE_ROLE_BY_TIER[ProfileRoleTier.ENGINEER_STEWARD].materialized_actions_hash,
            3,
            "ACTIVE",
            EffectiveProfileRoleStatus.VERIFIED.value,
        ),
        (
            "UNKNOWN",
            PROFILE_ROLE_POLICY_VERSION,
            "0" * 64,
            3,
            "ACTIVE",
            EffectiveProfileRoleStatus.STALE.value,
        ),
        (
            "ENGINEER_STEWARD",
            "STALE_POLICY",
            PROFILE_ROLE_BY_TIER[ProfileRoleTier.ENGINEER_STEWARD].materialized_actions_hash,
            3,
            "ACTIVE",
            EffectiveProfileRoleStatus.STALE.value,
        ),
        (
            "ENGINEER_STEWARD",
            PROFILE_ROLE_POLICY_VERSION,
            "0" * 64,
            3,
            "ACTIVE",
            EffectiveProfileRoleStatus.STALE.value,
        ),
        (
            "ENGINEER_STEWARD",
            PROFILE_ROLE_POLICY_VERSION,
            PROFILE_ROLE_BY_TIER[ProfileRoleTier.ENGINEER_STEWARD].materialized_actions_hash,
            2,
            "ACTIVE",
            EffectiveProfileRoleStatus.STALE.value,
        ),
        (
            "ENGINEER_STEWARD",
            PROFILE_ROLE_POLICY_VERSION,
            PROFILE_ROLE_BY_TIER[ProfileRoleTier.ENGINEER_STEWARD].materialized_actions_hash,
            3,
            "REVOKED",
            EffectiveProfileRoleStatus.REVOKED.value,
        ),
    ],
)
def test_profile_role_evidence_fails_closed_when_assignment_is_not_current(
    tier: str,
    policy_version: str,
    actions_hash: str,
    assignment_version: int,
    state: str,
    expected: str,
) -> None:
    now = datetime.now(UTC)
    workspace_id, subject_id, actor_id = uuid4(), uuid4(), uuid4()
    policy = PROFILE_ROLE_BY_TIER[ProfileRoleTier.ENGINEER_STEWARD]
    subject = SubjectModel(
        id=subject_id,
        issuer="https://identity.example/realms/datariver",
        external_subject="subject",
        display_name="Target User",
        email="target@example.test",
        active=True,
        created_at=now,
        updated_at=now,
    )
    membership = WorkspaceMembershipModel(
        workspace_id=workspace_id,
        subject_id=subject_id,
        department_id=None,
        job_function="DATA_ENGINEER",
        clearance=int(Classification.CONFIDENTIAL),
        attributes={
            "groups": [],
            "allowed_actions": sorted(action.value for action in policy.allowed_actions),
            "denied_actions": [],
            "allowed_system_ids": [],
            "allowed_domain_ids": [],
        },
        active=True,
        access_expires_at=None,
        version=3,
        created_at=now,
        updated_at=now,
    )
    assignment = ProfileRoleAssignmentModel(
        workspace_id=workspace_id,
        subject_id=subject_id,
        tier=tier,
        policy_version=policy_version,
        materialized_actions_hash=actions_hash,
        membership_version=assignment_version,
        state=state,
        assigned_by=actor_id,
        reason="Approved profile transition.",
        assurance="PASSWORD_REAUTH",
        version=1,
        created_at=now,
        updated_at=now,
    )

    evidence = _profile_role_assignment_evidence(
        subject=subject,
        membership=membership,
        assignment=assignment,
        canonical_admin_binding=None,
    )

    assert evidence is not None
    assert evidence.status == expected


def test_revoked_canonical_binding_does_not_hide_current_non_admin_profile() -> None:
    now = datetime.now(UTC)
    workspace_id, subject_id, actor_id = uuid4(), uuid4(), uuid4()
    policy = PROFILE_ROLE_BY_TIER[ProfileRoleTier.MANAGER]
    subject = SubjectModel(
        id=subject_id,
        issuer="https://identity.example/realms/datariver",
        external_subject="former-admin",
        display_name="Former Admin",
        email="former-admin@example.test",
        active=True,
        created_at=now,
        updated_at=now,
    )
    membership = WorkspaceMembershipModel(
        workspace_id=workspace_id,
        subject_id=subject_id,
        department_id=None,
        job_function="MANAGER",
        clearance=int(Classification.RESTRICTED),
        attributes={
            "groups": [],
            "allowed_actions": sorted(action.value for action in policy.allowed_actions),
            "denied_actions": [],
            "allowed_system_ids": [],
            "allowed_domain_ids": [],
        },
        active=True,
        access_expires_at=None,
        version=4,
        created_at=now,
        updated_at=now,
    )
    assignment = ProfileRoleAssignmentModel(
        workspace_id=workspace_id,
        subject_id=subject_id,
        tier=ProfileRoleTier.MANAGER.value,
        policy_version=PROFILE_ROLE_POLICY_VERSION,
        materialized_actions_hash=policy.materialized_actions_hash,
        membership_version=4,
        state="ACTIVE",
        assigned_by=actor_id,
        reason="Demoted through the protected transition.",
        assurance="HARDWARE_WEBAUTHN",
        version=2,
        created_at=now,
        updated_at=now,
    )

    evidence = _profile_role_assignment_evidence(
        subject=subject,
        membership=membership,
        assignment=assignment,
        canonical_admin_binding=CanonicalAdminBindingEvidence(status="REVOKED"),
    )

    assert evidence is not None
    assert evidence.status == EffectiveProfileRoleStatus.VERIFIED.value
    assert evidence.tier == ProfileRoleTier.MANAGER.value
