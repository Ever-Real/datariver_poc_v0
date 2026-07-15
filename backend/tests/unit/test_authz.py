from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from datariver.application.dto import DecisionAuditItem
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    BuiltinPolicyEngine,
    Classification,
    Decision,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)


class BatchDecisionWriter:
    def __init__(self) -> None:
        self.single_calls = 0
        self.sets: list[tuple[DecisionAuditItem, ...]] = []

    async def append_decision(
        self,
        *,
        decision: Decision,
        subject_id: UUID,
        workspace_id: UUID,
        resource_id: UUID,
        action: str,
        request_id: str,
    ) -> None:
        del decision, subject_id, workspace_id, resource_id, action, request_id
        self.single_calls += 1

    async def append_decision_set(
        self,
        *,
        decision_id: UUID,
        items: tuple[DecisionAuditItem, ...],
        subject_id: UUID,
        workspace_id: UUID,
        parent_resource_id: UUID,
        action: str,
        request_id: str,
    ) -> None:
        del decision_id, subject_id, workspace_id, parent_resource_id, action, request_id
        self.sets.append(items)


def make_context(
    *, action: Action = Action.CATALOG_READ
) -> tuple[SubjectAttributes, ResourceAttributes, EnvironmentAttributes]:
    workspace_id = uuid4()
    subject_id = uuid4()
    system_id = uuid4()
    domain_id = uuid4()
    now = datetime.now(UTC)
    subject = SubjectAttributes(
        subject_id=subject_id,
        workspace_id=workspace_id,
        active=True,
        department_id=uuid4(),
        groups=frozenset({"stewards"}),
        job_function="DATA_STEWARD",
        clearance=Classification.CONFIDENTIAL,
        allowed_system_ids=frozenset({system_id}),
        allowed_domain_ids=frozenset({domain_id}),
        allowed_actions=frozenset({action}),
        authentication_time=now - timedelta(minutes=1),
        strong_authentication=True,
    )
    resource = ResourceAttributes(
        resource_id=uuid4(),
        workspace_id=workspace_id,
        resource_type="catalog_asset",
        owner_department_id=subject.department_id,
        system_id=system_id,
        domain_id=domain_id,
        classification=Classification.INTERNAL,
        lifecycle="ACTIVE",
    )
    environment = EnvironmentAttributes(requested_at=now)
    return subject, resource, environment


def test_allows_matching_attributes() -> None:
    subject, resource, environment = make_context()

    decision = BuiltinPolicyEngine().decide(
        subject=subject,
        resource=resource,
        action=Action.CATALOG_READ,
        environment=environment,
    )

    assert decision.allowed
    assert decision.reason_codes == ("POLICY_ALLOW",)


def test_denies_cross_workspace_even_when_action_is_granted() -> None:
    subject, resource, environment = make_context()
    resource = ResourceAttributes(
        resource_id=resource.resource_id,
        workspace_id=uuid4(),
        resource_type=resource.resource_type,
        owner_department_id=resource.owner_department_id,
        system_id=resource.system_id,
        domain_id=resource.domain_id,
        classification=resource.classification,
        lifecycle=resource.lifecycle,
    )

    decision = BuiltinPolicyEngine().decide(
        subject=subject,
        resource=resource,
        action=Action.CATALOG_READ,
        environment=environment,
    )

    assert not decision.allowed
    assert "WORKSPACE_MISMATCH" in decision.reason_codes


def test_denies_insufficient_clearance() -> None:
    subject, resource, environment = make_context()
    resource = ResourceAttributes(
        resource_id=resource.resource_id,
        workspace_id=resource.workspace_id,
        resource_type=resource.resource_type,
        owner_department_id=resource.owner_department_id,
        system_id=resource.system_id,
        domain_id=resource.domain_id,
        classification=Classification.RESTRICTED,
        lifecycle=resource.lifecycle,
    )

    decision = BuiltinPolicyEngine().decide(
        subject=subject,
        resource=resource,
        action=Action.CATALOG_READ,
        environment=environment,
    )

    assert not decision.allowed
    assert "CLEARANCE_INSUFFICIENT" in decision.reason_codes


def test_denies_requester_self_approval() -> None:
    subject, resource, environment = make_context(action=Action.CHANGE_APPROVE)
    resource = ResourceAttributes(
        resource_id=resource.resource_id,
        workspace_id=resource.workspace_id,
        resource_type="change_request",
        owner_department_id=resource.owner_department_id,
        system_id=resource.system_id,
        domain_id=resource.domain_id,
        classification=resource.classification,
        lifecycle="FINAL_REVIEW",
        requester_id=subject.subject_id,
    )

    decision = BuiltinPolicyEngine().decide(
        subject=subject,
        resource=resource,
        action=Action.CHANGE_APPROVE,
        environment=environment,
    )

    assert not decision.allowed
    assert "SELF_APPROVAL_FORBIDDEN" in decision.reason_codes


def test_high_risk_action_requires_recent_strong_authentication() -> None:
    subject, resource, environment = make_context(action=Action.KG_PUBLISH)
    subject = SubjectAttributes(
        subject_id=subject.subject_id,
        workspace_id=subject.workspace_id,
        active=subject.active,
        department_id=subject.department_id,
        groups=subject.groups,
        job_function=subject.job_function,
        clearance=subject.clearance,
        allowed_system_ids=subject.allowed_system_ids,
        allowed_domain_ids=subject.allowed_domain_ids,
        allowed_actions=subject.allowed_actions,
        authentication_time=environment.requested_at - timedelta(hours=1),
        strong_authentication=True,
    )

    decision = BuiltinPolicyEngine().decide(
        subject=subject,
        resource=resource,
        action=Action.KG_PUBLISH,
        environment=environment,
    )

    assert not decision.allowed
    assert "AUTHENTICATION_TOO_OLD" in decision.reason_codes


def test_denies_another_subject_owned_resource() -> None:
    subject, resource, environment = make_context()
    resource = ResourceAttributes(
        resource_id=resource.resource_id,
        workspace_id=resource.workspace_id,
        resource_type="upload_manifest",
        owner_department_id=resource.owner_department_id,
        system_id=resource.system_id,
        domain_id=resource.domain_id,
        classification=resource.classification,
        lifecycle=resource.lifecycle,
        owner_subject_id=uuid4(),
    )

    decision = BuiltinPolicyEngine().decide(
        subject=subject,
        resource=resource,
        action=Action.CATALOG_READ,
        environment=environment,
    )

    assert not decision.allowed
    assert "OWNER_SCOPE_MISMATCH" in decision.reason_codes


async def test_resource_set_is_evaluated_once_and_returns_only_allowed_items() -> None:
    subject, allowed, environment = make_context()
    denied = ResourceAttributes(
        resource_id=uuid4(),
        workspace_id=allowed.workspace_id,
        resource_type=allowed.resource_type,
        owner_department_id=allowed.owner_department_id,
        system_id=allowed.system_id,
        domain_id=allowed.domain_id,
        classification=Classification.RESTRICTED,
        lifecycle=allowed.lifecycle,
    )
    writer = BatchDecisionWriter()

    resources = await AuthorizationService(decision_writer=writer).filter_authorized(
        subject=subject,
        resources=(allowed, denied),
        action=Action.CATALOG_READ,
        environment=environment,
        request_id="request-one",
        parent_resource_id=subject.workspace_id,
    )

    assert resources == (allowed,)
    assert writer.single_calls == 0
    assert len(writer.sets) == 1
    assert len(writer.sets[0]) == 2
