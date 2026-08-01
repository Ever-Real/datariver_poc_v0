from __future__ import annotations

from dataclasses import replace

import pytest

from datariver.domain.authz import HIGH_RISK_ACTIONS, SERVICE_ONLY_ACTIONS, Action
from datariver.domain.capability_catalog import (
    CAPABILITY_BY_ACTION,
    CAPABILITY_CATALOG,
    CUSTOM_ROLE_ASSIGNABLE_ACTIONS,
    DEFAULT_HUMAN_ADMIN_ACTIONS,
    PROTECTED_ADMIN_CAPABILITIES,
    SELF_APPROVAL_CANDIDATE_ACTIONS,
    CapabilityActorKind,
    CapabilityAssignability,
    CapabilityAssurance,
    CapabilitySelfApprovalBinding,
    CapabilitySelfApprovalPolicy,
    validate_capability_catalog,
    validate_protected_capabilities,
)


def test_capability_catalog_is_exhaustive_and_preserves_the_actor_partition() -> None:
    assert len(CAPABILITY_CATALOG) == len(Action) == 69
    assert set(CAPABILITY_BY_ACTION) == set(Action)
    assert len(DEFAULT_HUMAN_ADMIN_ACTIONS) == 64
    assert DEFAULT_HUMAN_ADMIN_ACTIONS == set(Action) - set(SERVICE_ONLY_ACTIONS)
    assert {
        item.action
        for item in CAPABILITY_CATALOG
        if item.actor_kind is CapabilityActorKind.SERVICE_PRINCIPAL
    } == SERVICE_ONLY_ACTIONS
    assert all(item.label.strip() and item.description.strip() for item in CAPABILITY_CATALOG)


def test_capability_catalog_fails_closed_for_missing_or_duplicate_actions() -> None:
    with pytest.raises(RuntimeError, match="every Action exactly once"):
        validate_capability_catalog(CAPABILITY_CATALOG[:-1])
    with pytest.raises(RuntimeError, match="duplicate Action"):
        validate_capability_catalog((*CAPABILITY_CATALOG, CAPABILITY_CATALOG[0]))


def test_capability_catalog_fails_closed_for_assignment_partition_drift() -> None:
    human = CAPABILITY_BY_ACTION[Action.ADMIN_MANAGE]
    drifted = tuple(
        replace(item, assignability=CapabilityAssignability.SERVICE_PRINCIPAL_ONLY)
        if item.action is human.action
        else item
        for item in CAPABILITY_CATALOG
    )

    with pytest.raises(RuntimeError, match="assignability metadata"):
        validate_capability_catalog(drifted)


def test_capability_catalog_matches_high_risk_and_custom_role_boundaries() -> None:
    assert {
        item.action
        for item in CAPABILITY_CATALOG
        if item.assurance is CapabilityAssurance.FRESH_PHISHING_RESISTANT
    } == HIGH_RISK_ACTIONS
    assert CUSTOM_ROLE_ASSIGNABLE_ACTIONS == set(Action) - set(SERVICE_ONLY_ACTIONS)
    assert all(
        CAPABILITY_BY_ACTION[action].assignability is CapabilityAssignability.HUMAN_ROLE
        for action in CUSTOM_ROLE_ASSIGNABLE_ACTIONS
    )
    assert all(
        CAPABILITY_BY_ACTION[action].assurance is CapabilityAssurance.NOT_APPLICABLE
        for action in SERVICE_ONLY_ACTIONS
    )


def test_self_approval_metadata_is_pending_and_does_not_activate_a_policy() -> None:
    assert SELF_APPROVAL_CANDIDATE_ACTIONS
    assert Action.ADMIN_MANAGE not in SELF_APPROVAL_CANDIDATE_ACTIONS
    assert Action.ERASURE_APPROVE not in SELF_APPROVAL_CANDIDATE_ACTIONS
    for action in SELF_APPROVAL_CANDIDATE_ACTIONS:
        item = CAPABILITY_BY_ACTION[action]
        assert item.self_approval_policy is CapabilitySelfApprovalPolicy.CANONICAL_ADMIN_ONLY
        assert item.self_approval_binding is CapabilitySelfApprovalBinding.PENDING_PROTECTED_BINDING
    assert all(
        item.self_approval_binding is CapabilitySelfApprovalBinding.NOT_APPLICABLE
        for item in CAPABILITY_CATALOG
        if item.action not in SELF_APPROVAL_CANDIDATE_ACTIONS
    )


def test_canonical_admin_self_approval_is_separate_and_non_delegable() -> None:
    assert len(PROTECTED_ADMIN_CAPABILITIES) == 1
    protected = PROTECTED_ADMIN_CAPABILITIES[0]
    assert protected.capability_key == "admin.self_approve"
    assert protected.service_key == "admin"
    assert protected.actor_kind is CapabilityActorKind.HUMAN
    assert protected.assignability is CapabilityAssignability.CANONICAL_ADMIN_ONLY
    assert protected.default_admin is True
    assert protected.assurance is CapabilityAssurance.FRESH_PHISHING_RESISTANT
    assert protected.self_approval_policy is CapabilitySelfApprovalPolicy.CANONICAL_ADMIN_ONLY
    assert (
        protected.self_approval_binding is CapabilitySelfApprovalBinding.PENDING_PROTECTED_BINDING
    )
    assert protected.capability_key not in {action.value for action in Action}


def test_protected_capability_catalog_fails_closed_for_completeness_or_policy_drift() -> None:
    protected = PROTECTED_ADMIN_CAPABILITIES[0]
    with pytest.raises(RuntimeError, match="incomplete"):
        validate_protected_capabilities(())
    with pytest.raises(RuntimeError, match="duplicate key"):
        validate_protected_capabilities((protected, protected))
    with pytest.raises(RuntimeError, match="metadata"):
        validate_protected_capabilities(
            (replace(protected, assignability=CapabilityAssignability.HUMAN_ROLE),)
        )
