from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from datariver.application.classification_access import static_classification_access_floor
from datariver.application.dto import DecisionAuditItem
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.admin_access import AdminFallbackStage
from datariver.domain.authz import (
    Action,
    AuthenticationAssurance,
    BuiltinPolicyEngine,
    Classification,
    Decision,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.classification_access import SearchMode
from datariver.domain.common import ForbiddenError


class BatchDecisionWriter:
    def __init__(self) -> None:
        self.single_calls = 0
        self.decisions: list[Decision] = []
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
        del subject_id, workspace_id, resource_id, action, request_id
        self.single_calls += 1
        self.decisions.append(decision)

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
        authentication_assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
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


def test_entitlement_preview_keeps_high_risk_action_visible_without_relaxing_command_auth() -> None:
    subject, resource, environment = make_context(action=Action.GOVERNANCE_DOCUMENT_PUBLISH)
    subject = replace(
        subject,
        authentication_assurance=AuthenticationAssurance.PASSWORD,
        authentication_time=None,
    )
    service = AuthorizationService(decision_writer=BatchDecisionWriter())

    assert service.is_entitled(
        subject=subject,
        resource=resource,
        action=Action.GOVERNANCE_DOCUMENT_PUBLISH,
        environment=environment,
    )
    assert (
        not BuiltinPolicyEngine()
        .decide(
            subject=subject,
            resource=resource,
            action=Action.GOVERNANCE_DOCUMENT_PUBLISH,
            environment=environment,
        )
        .allowed
    )


def test_entitlement_preview_does_not_override_business_denials() -> None:
    subject, resource, environment = make_context(action=Action.GOVERNANCE_DOCUMENT_PUBLISH)
    resource = replace(resource, requester_id=subject.subject_id)

    assert not AuthorizationService(decision_writer=BatchDecisionWriter()).is_entitled(
        subject=subject,
        resource=resource,
        action=Action.GOVERNANCE_DOCUMENT_PUBLISH,
        environment=environment,
    )


def test_public_resource_does_not_require_system_or_domain_scope() -> None:
    subject, resource, environment = make_context()
    resource = replace(
        resource,
        classification=Classification.PUBLIC,
        system_id=uuid4(),
        domain_id=uuid4(),
    )

    decision = BuiltinPolicyEngine().decide(
        subject=subject,
        resource=resource,
        action=Action.CATALOG_READ,
        environment=environment,
    )

    assert decision.allowed
    assert decision.reason_codes == ("POLICY_ALLOW",)


def test_non_public_resource_still_requires_system_and_domain_scope() -> None:
    subject, resource, environment = make_context()
    resource = replace(
        resource,
        classification=Classification.INTERNAL,
        system_id=uuid4(),
        domain_id=uuid4(),
    )

    decision = BuiltinPolicyEngine().decide(
        subject=subject,
        resource=resource,
        action=Action.CATALOG_READ,
        environment=environment,
    )

    assert not decision.allowed
    assert "SYSTEM_SCOPE_MISMATCH" in decision.reason_codes
    assert "DOMAIN_SCOPE_MISMATCH" in decision.reason_codes


@pytest.mark.asyncio
async def test_catalog_workspace_browse_independently_allows_nonrestricted_presentation() -> None:
    subject, resource, environment = make_context()
    resource = replace(
        resource,
        resource_type="catalog_asset_browse",
        system_id=uuid4(),
        domain_id=uuid4(),
    )
    writer = BatchDecisionWriter()

    decision = await AuthorizationService(
        decision_writer=writer
    ).authorize_catalog_workspace_browse(
        subject=subject,
        resource=resource,
        classification_access=static_classification_access_floor(),
        environment=environment,
        request_id="catalog-workspace-browse",
    )

    assert decision.allowed
    assert decision.reason_codes == ("CATALOG_WORKSPACE_DISCOVERY_ALLOW",)
    assert "catalog-workspace-discovery-v1" in decision.policy_versions
    assert writer.decisions == [decision]


@pytest.mark.parametrize(
    "case",
    [
        "cross_workspace",
        "inactive_subject",
        "inactive_resource",
        "service_identity",
        "explicit_deny",
        "missing_action",
        "clearance",
        "policy_deny",
        "restricted",
        "wrong_resource_type",
    ],
)
@pytest.mark.asyncio
async def test_catalog_workspace_browse_fails_closed(case: str) -> None:
    subject, resource, environment = make_context()
    resource = replace(resource, resource_type="catalog_lineage_browse")
    access = static_classification_access_floor()
    if case == "cross_workspace":
        resource = replace(resource, workspace_id=uuid4())
    elif case == "inactive_subject":
        subject = replace(subject, active=False)
    elif case == "inactive_resource":
        resource = replace(resource, active=False)
    elif case == "service_identity":
        subject = replace(subject, groups=frozenset({"service-accounts"}))
    elif case == "explicit_deny":
        subject = replace(subject, denied_actions=frozenset({Action.CATALOG_READ}))
    elif case == "missing_action":
        subject = replace(subject, allowed_actions=frozenset())
    elif case == "clearance":
        subject = replace(subject, clearance=Classification.PUBLIC)
    elif case == "policy_deny":
        access = replace(
            access,
            rules=tuple(
                replace(rule, search_mode=SearchMode.DENY)
                if rule.classification is resource.classification
                else rule
                for rule in access.rules
            ),
        )
    elif case == "restricted":
        resource = replace(resource, classification=Classification.RESTRICTED)
        subject = replace(subject, clearance=Classification.RESTRICTED)
    elif case == "wrong_resource_type":
        resource = replace(resource, resource_type="catalog_asset")
    writer = BatchDecisionWriter()

    with pytest.raises(ForbiddenError):
        await AuthorizationService(decision_writer=writer).authorize_catalog_workspace_browse(
            subject=subject,
            resource=resource,
            classification_access=access,
            environment=environment,
            request_id=f"catalog-workspace-browse-{case}",
        )

    assert writer.single_calls == 1
    assert writer.decisions[0].allowed is False


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


def test_high_risk_action_requires_recent_hardware_authentication() -> None:
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
        authentication_assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
    )

    decision = BuiltinPolicyEngine().decide(
        subject=subject,
        resource=resource,
        action=Action.KG_PUBLISH,
        environment=environment,
    )

    assert not decision.allowed
    assert "AUTHENTICATION_TOO_OLD" in decision.reason_codes


@pytest.mark.parametrize(
    "action",
    [
        Action.RETENTION_MANAGE,
        Action.LEGAL_HOLD_PLACE,
        Action.LEGAL_HOLD_RELEASE,
        Action.ERASURE_REQUEST,
        Action.ERASURE_APPROVE,
    ],
)
def test_retention_governance_mutations_require_hardware_authentication(action: Action) -> None:
    subject, resource, environment = make_context(action=action)
    subject = replace(
        subject,
        authentication_assurance=AuthenticationAssurance.PASSWORD_REAUTH,
        authentication_time=environment.requested_at - timedelta(seconds=10),
    )

    decision = BuiltinPolicyEngine().decide(
        subject=subject,
        resource=resource,
        action=action,
        environment=environment,
    )

    assert not decision.allowed
    assert "PHISHING_RESISTANT_AUTH_REQUIRED" in decision.reason_codes


@pytest.mark.parametrize(
    "action",
    [
        Action.RETENTION_MANAGE,
        Action.LEGAL_HOLD_PLACE,
        Action.LEGAL_HOLD_RELEASE,
        Action.ERASURE_REQUEST,
        Action.ERASURE_APPROVE,
    ],
)
def test_retention_governance_mutations_reject_service_accounts(action: Action) -> None:
    subject, resource, environment = make_context(action=action)
    subject = replace(
        subject,
        groups=frozenset({"security-administrators", "service-accounts"}),
        job_function="SERVICE_ACCOUNT",
    )

    decision = BuiltinPolicyEngine().decide(
        subject=subject,
        resource=resource,
        action=action,
        environment=environment,
    )

    assert not decision.allowed
    assert "HUMAN_ACTOR_REQUIRED" in decision.reason_codes


def test_password_and_otp_do_not_satisfy_hardware_authentication() -> None:
    subject, resource, environment = make_context(action=Action.ADMIN_MANAGE)

    for assurance in (
        AuthenticationAssurance.PASSWORD_REAUTH,
        AuthenticationAssurance.OTHER_MFA,
    ):
        candidate = SubjectAttributes(
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
            authentication_time=environment.requested_at - timedelta(seconds=10),
            authentication_assurance=assurance,
        )

        decision = BuiltinPolicyEngine().decide(
            subject=candidate,
            resource=resource,
            action=Action.ADMIN_MANAGE,
            environment=environment,
        )

        assert not decision.allowed
        assert "PHISHING_RESISTANT_AUTH_REQUIRED" in decision.reason_codes


def test_future_authentication_time_is_rejected() -> None:
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
        authentication_time=environment.requested_at + timedelta(minutes=1),
        authentication_assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
    )

    decision = BuiltinPolicyEngine().decide(
        subject=subject,
        resource=resource,
        action=Action.KG_PUBLISH,
        environment=environment,
    )

    assert not decision.allowed
    assert "AUTHENTICATION_TIME_INVALID" in decision.reason_codes


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


@pytest.mark.parametrize(
    ("action", "assurance", "authentication_age", "expected"),
    [
        (Action.KG_PUBLISH, AuthenticationAssurance.PASSWORD, 10, "FIDO2_REQUIRED"),
        (
            Action.KG_PUBLISH,
            AuthenticationAssurance.HARDWARE_WEBAUTHN,
            3600,
            "REAUTH_REQUIRED",
        ),
        (
            Action.ADMIN_MANAGE,
            AuthenticationAssurance.PASSWORD_REAUTH,
            10,
            "FALLBACK_UNAVAILABLE",
        ),
    ],
)
async def test_authentication_only_denials_have_bounded_remediation(
    action: Action,
    assurance: AuthenticationAssurance,
    authentication_age: int,
    expected: str,
) -> None:
    subject, resource, environment = make_context(action=action)
    subject = replace(
        subject,
        authentication_assurance=assurance,
        authentication_time=environment.requested_at - timedelta(seconds=authentication_age),
    )

    with pytest.raises(ForbiddenError) as captured:
        await AuthorizationService(decision_writer=BatchDecisionWriter()).authorize(
            subject=subject,
            resource=resource,
            action=action,
            environment=environment,
            request_id="request-remediation",
        )

    assert captured.value.details["remediation"] == {"kind": expected}


@pytest.mark.parametrize(
    ("stage", "assurance", "allowed"),
    [
        (AdminFallbackStage.REQUEST, AuthenticationAssurance.PASSWORD_REAUTH, True),
        (AdminFallbackStage.CONSUME, AuthenticationAssurance.PASSWORD_REAUTH, True),
        (AdminFallbackStage.READ, AuthenticationAssurance.PASSWORD_REAUTH, True),
        (AdminFallbackStage.APPROVE, AuthenticationAssurance.PASSWORD_REAUTH, True),
        (AdminFallbackStage.READ, AuthenticationAssurance.HARDWARE_WEBAUTHN, True),
        (AdminFallbackStage.APPROVE, AuthenticationAssurance.HARDWARE_WEBAUTHN, True),
        (AdminFallbackStage.REQUEST, AuthenticationAssurance.HARDWARE_WEBAUTHN, False),
        (AdminFallbackStage.CONSUME, AuthenticationAssurance.HARDWARE_WEBAUTHN, False),
        (AdminFallbackStage.REQUEST, AuthenticationAssurance.PASSWORD, False),
        (AdminFallbackStage.APPROVE, AuthenticationAssurance.OTHER_MFA, False),
    ],
)
async def test_admin_fallback_has_an_exact_assurance_matrix(
    stage: AdminFallbackStage,
    assurance: AuthenticationAssurance,
    allowed: bool,
) -> None:
    subject, resource, environment = make_context(action=Action.ADMIN_MANAGE)
    subject = replace(
        subject,
        groups=frozenset({"security-administrators"}),
        job_function="SECURITY_ADMINISTRATOR",
        clearance=Classification.RESTRICTED,
        authentication_assurance=assurance,
        authentication_time=environment.requested_at - timedelta(seconds=10),
    )
    resource = replace(resource, classification=Classification.RESTRICTED)
    service = AuthorizationService(decision_writer=BatchDecisionWriter())

    if allowed:
        decision = await service.authorize_admin_fallback(
            subject=subject,
            resource=resource,
            stage=stage,
            environment=environment,
            request_id="fallback-assurance",
        )
        assert decision.allowed
    else:
        with pytest.raises(ForbiddenError):
            await service.authorize_admin_fallback(
                subject=subject,
                resource=resource,
                stage=stage,
                environment=environment,
                request_id="fallback-assurance",
            )


@pytest.mark.parametrize(
    ("groups", "job_function"),
    [
        (frozenset({"stewards"}), "DATA_STEWARD"),
        (frozenset({"security-administrators", "service-accounts"}), "SERVICE_ACCOUNT"),
    ],
)
async def test_admin_fallback_requires_a_human_security_administrator(
    groups: frozenset[str], job_function: str
) -> None:
    subject, resource, environment = make_context(action=Action.ADMIN_MANAGE)
    subject = replace(
        subject,
        groups=groups,
        job_function=job_function,
        clearance=Classification.RESTRICTED,
        authentication_assurance=AuthenticationAssurance.PASSWORD_REAUTH,
        authentication_time=environment.requested_at - timedelta(seconds=10),
    )
    resource = replace(resource, classification=Classification.RESTRICTED)

    with pytest.raises(ForbiddenError):
        await AuthorizationService(decision_writer=BatchDecisionWriter()).authorize_admin_fallback(
            subject=subject,
            resource=resource,
            stage=AdminFallbackStage.REQUEST,
            environment=environment,
            request_id="fallback-human-only",
        )


async def test_non_authentication_denial_does_not_offer_misleading_remediation() -> None:
    subject, resource, environment = make_context(action=Action.CHANGE_APPROVE)
    resource = replace(resource, requester_id=subject.subject_id)

    with pytest.raises(ForbiddenError) as captured:
        await AuthorizationService(decision_writer=BatchDecisionWriter()).authorize(
            subject=subject,
            resource=resource,
            action=Action.CHANGE_APPROVE,
            environment=environment,
            request_id="request-self-approval",
        )

    assert "remediation" not in captured.value.details


@pytest.mark.parametrize(
    "assurance",
    [AuthenticationAssurance.PASSWORD, AuthenticationAssurance.PASSWORD_REAUTH],
)
async def test_development_admin_password_bypass_preserves_actual_assurance(
    assurance: AuthenticationAssurance,
) -> None:
    subject, resource, environment = make_context(action=Action.ADMIN_MANAGE)
    subject = replace(
        subject,
        authentication_assurance=assurance,
        authentication_time=environment.requested_at - timedelta(seconds=10),
    )
    writer = BatchDecisionWriter()

    decision = await AuthorizationService(
        decision_writer=writer,
        development_admin_password_bypass_enabled=True,
    ).authorize(
        subject=subject,
        resource=resource,
        action=Action.ADMIN_MANAGE,
        environment=environment,
        request_id="development-admin-password-bypass",
    )

    assert decision.allowed
    assert decision.authentication_assurance is assurance
    assert decision.reason_codes == ("DEVELOPMENT_PASSWORD_BYPASS",)
    assert "development-admin-password-bypass-v1" in decision.policy_versions


async def test_development_admin_password_bypass_requests_password_reauth_before_allowing() -> None:
    subject, resource, environment = make_context(action=Action.ADMIN_MANAGE)
    subject = replace(
        subject,
        authentication_assurance=AuthenticationAssurance.UNKNOWN,
        authentication_time=environment.requested_at
        - environment.maximum_authentication_age
        - timedelta(seconds=1),
    )

    with pytest.raises(ForbiddenError) as captured:
        await AuthorizationService(
            decision_writer=BatchDecisionWriter(),
            development_admin_password_bypass_enabled=True,
        ).authorize(
            subject=subject,
            resource=resource,
            action=Action.ADMIN_MANAGE,
            environment=environment,
            request_id="development-admin-password-reauth",
        )

    assert captured.value.details["remediation"] == {"kind": "REAUTH_REQUIRED"}
    assert set(captured.value.details["reason_codes"]) == {
        "PHISHING_RESISTANT_AUTH_REQUIRED",
        "AUTHENTICATION_TOO_OLD",
    }


async def test_development_governance_password_bypass_is_explicitly_scoped() -> None:
    subject, resource, environment = make_context(action=Action.GOVERNANCE_DOCUMENT_PUBLISH)
    subject = replace(
        subject,
        authentication_assurance=AuthenticationAssurance.PASSWORD_REAUTH,
        authentication_time=environment.requested_at - timedelta(seconds=10),
    )

    decision = await AuthorizationService(
        decision_writer=BatchDecisionWriter(),
        development_governance_password_bypass_enabled=True,
    ).authorize(
        subject=subject,
        resource=resource,
        action=Action.GOVERNANCE_DOCUMENT_PUBLISH,
        environment=environment,
        request_id="development-governance-password-bypass",
    )

    assert decision.allowed
    assert decision.authentication_assurance is AuthenticationAssurance.PASSWORD_REAUTH
    assert decision.reason_codes == ("DEVELOPMENT_PASSWORD_BYPASS",)
    assert "development-governance-admin-password-bypass-v1" in decision.policy_versions

    with pytest.raises(ForbiddenError):
        await AuthorizationService(
            decision_writer=BatchDecisionWriter(),
            development_governance_password_bypass_enabled=True,
        ).authorize(
            subject=replace(
                subject,
                allowed_actions=frozenset({Action.KG_PUBLISH}),
            ),
            resource=resource,
            action=Action.KG_PUBLISH,
            environment=environment,
            request_id="development-governance-password-bypass-out-of-scope",
        )


async def test_development_admin_password_bypass_never_overrides_other_denials() -> None:
    subject, resource, environment = make_context(action=Action.ADMIN_MANAGE)
    password_subject = replace(
        subject,
        authentication_assurance=AuthenticationAssurance.PASSWORD,
        authentication_time=environment.requested_at - timedelta(seconds=10),
    )
    candidates = (
        (
            replace(
                password_subject,
                authentication_assurance=AuthenticationAssurance.OTHER_MFA,
            ),
            resource,
        ),
        (replace(password_subject, authentication_time=None), resource),
        (
            replace(
                password_subject,
                authentication_time=environment.requested_at
                - environment.maximum_authentication_age
                - timedelta(seconds=1),
            ),
            resource,
        ),
        (replace(password_subject, active=False), resource),
        (
            replace(
                password_subject,
                denied_actions=frozenset({Action.ADMIN_MANAGE}),
            ),
            resource,
        ),
        (password_subject, replace(resource, workspace_id=uuid4())),
    )

    for candidate_subject, candidate_resource in candidates:
        with pytest.raises(ForbiddenError):
            await AuthorizationService(
                decision_writer=BatchDecisionWriter(),
                development_admin_password_bypass_enabled=True,
            ).authorize(
                subject=candidate_subject,
                resource=candidate_resource,
                action=Action.ADMIN_MANAGE,
                environment=environment,
                request_id="development-admin-password-bypass-deny",
            )
