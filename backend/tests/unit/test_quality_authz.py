from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from datariver.domain.authz import (
    SERVICE_ONLY_ACTIONS,
    Action,
    AuthenticationAssurance,
    BuiltinPolicyEngine,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)

NOW = datetime(2026, 7, 30, 9, tzinfo=UTC)


def _resource(*, author_id: UUID | None = None) -> ResourceAttributes:
    workspace_id = uuid4()
    return ResourceAttributes(
        resource_id=uuid4(),
        workspace_id=workspace_id,
        resource_type="quality_rule_set_version",
        owner_department_id=None,
        system_id=None,
        domain_id=None,
        classification=Classification.INTERNAL,
        lifecycle="ACTIVE",
        requester_id=author_id,
    )


def _subject(
    resource: ResourceAttributes,
    *,
    subject_id: UUID | None = None,
    action: Action,
    groups: frozenset[str] = frozenset(),
    job_function: str | None = "DATA_STEWARD",
    allowed_actions: frozenset[Action] | None = None,
) -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=subject_id or uuid4(),
        workspace_id=resource.workspace_id,
        active=True,
        department_id=None,
        groups=groups,
        job_function=job_function,
        clearance=Classification.RESTRICTED,
        allowed_actions=allowed_actions or frozenset({action}),
        authentication_time=NOW,
        authentication_assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
    )


@pytest.mark.parametrize(
    ("action", "purpose_group"),
    (
        (Action.QUALITY_DISPATCH, "quality-dispatchers"),
        (Action.QUALITY_EXECUTE, "quality-workers"),
        (Action.CATALOG_PROFILE_COLLECT, "catalog-profile-collectors"),
        (Action.KG_INGEST_EXECUTE, "knowledge-ingestion-workers"),
        (Action.KG_PROPOSAL_EXECUTE, "knowledge-proposal-workers"),
    ),
)
def test_service_actions_require_exact_purpose_identity(action: Action, purpose_group: str) -> None:
    resource = _resource()
    engine = BuiltinPolicyEngine()
    environment = EnvironmentAttributes(requested_at=NOW)
    human = _subject(resource, action=action)
    assert not engine.decide(
        subject=human, resource=resource, action=action, environment=environment
    ).allowed

    service = _subject(
        resource,
        action=action,
        groups=frozenset({"service-accounts", purpose_group}),
        job_function="SERVICE_ACCOUNT",
    )
    assert engine.decide(
        subject=service, resource=resource, action=action, environment=environment
    ).allowed
    overprivileged = _subject(
        resource,
        action=action,
        groups=frozenset({"service-accounts", purpose_group}),
        job_function="SERVICE_ACCOUNT",
        allowed_actions=frozenset({action, Action.QUALITY_READ}),
    )
    decision = engine.decide(
        subject=overprivileged,
        resource=resource,
        action=action,
        environment=environment,
    )
    assert "SERVICE_ACTION_SET_INVALID" in decision.reason_codes


def test_service_identity_cannot_perform_human_quality_governance() -> None:
    resource = _resource()
    service = _subject(
        resource,
        action=Action.QUALITY_RULE_PROPOSE,
        groups=frozenset({"service-accounts"}),
        job_function="SERVICE_ACCOUNT",
    )
    decision = BuiltinPolicyEngine().decide(
        subject=service,
        resource=resource,
        action=Action.QUALITY_RULE_PROPOSE,
        environment=EnvironmentAttributes(requested_at=NOW),
    )
    assert "HUMAN_ACTOR_REQUIRED" in decision.reason_codes


@pytest.mark.parametrize("action", (Action.QUALITY_RULE_REVIEW, Action.QUALITY_RULE_ACTIVATE))
def test_author_cannot_review_or_activate_own_version(action: Action) -> None:
    author = uuid4()
    resource = _resource(author_id=author)
    subject = _subject(resource, subject_id=author, action=action)
    decision = BuiltinPolicyEngine().decide(
        subject=subject,
        resource=resource,
        action=action,
        environment=EnvironmentAttributes(requested_at=NOW),
    )
    assert "SELF_APPROVAL_FORBIDDEN" in decision.reason_codes


def test_activate_and_revoke_require_hardware_webauthn() -> None:
    for action in (Action.QUALITY_RULE_ACTIVATE, Action.QUALITY_RULE_REVOKE):
        resource = _resource()
        subject = _subject(resource, action=action)
        weak = replace(
            subject,
            authentication_assurance=AuthenticationAssurance.OTHER_MFA,
        )
        decision = BuiltinPolicyEngine().decide(
            subject=weak,
            resource=resource,
            action=action,
            environment=EnvironmentAttributes(requested_at=NOW),
        )
        assert "PHISHING_RESISTANT_AUTH_REQUIRED" in decision.reason_codes


def test_service_actions_are_closed_and_not_accidentally_human_admin_actions() -> None:
    assert SERVICE_ONLY_ACTIONS == {
        Action.QUALITY_DISPATCH,
        Action.QUALITY_EXECUTE,
        Action.CATALOG_PROFILE_COLLECT,
        Action.KG_INGEST_EXECUTE,
        Action.KG_PROPOSAL_EXECUTE,
    }
