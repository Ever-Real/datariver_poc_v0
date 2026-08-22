from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from uuid import UUID

from datariver.application.classification_access import ClassificationAccessSnapshot
from datariver.application.dto import DecisionAuditItem
from datariver.application.ports import DecisionSetWriter, DecisionWriter
from datariver.domain.admin_access import AdminFallbackStage
from datariver.domain.authz import (
    HIGH_RISK_ACTIONS,
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
from datariver.domain.common import Effect, ForbiddenError, uuid7

AUTHENTICATION_DENIAL_REASONS = frozenset(
    {
        "PHISHING_RESISTANT_AUTH_REQUIRED",
        "AUTHENTICATION_TIME_REQUIRED",
        "AUTHENTICATION_TIME_INVALID",
        "AUTHENTICATION_TOO_OLD",
    }
)
DEVELOPMENT_GOVERNANCE_PASSWORD_BYPASS_ACTIONS = frozenset(
    {
        Action.GOVERNANCE_DOCUMENT_PUBLISH,
        Action.GOVERNANCE_DOCUMENT_ARCHIVE,
        Action.GOVERNANCE_TEMPLATE_ACTIVATE,
        Action.GOVERNANCE_TEMPLATE_ARCHIVE,
    }
)
CHANGE_TARGET_ACTIONS = frozenset(
    {
        Action.CATALOG_READ,
        Action.CHANGE_CREATE,
        Action.CHANGE_READ,
        Action.CHANGE_EDIT,
        Action.CHANGE_REVIEW,
        Action.CHANGE_APPROVE,
    }
)


def _remediation_kind(
    *, action: Action, subject: SubjectAttributes, decision: Decision
) -> str | None:
    reasons = frozenset(decision.reason_codes)
    if not reasons or not reasons.issubset(AUTHENTICATION_DENIAL_REASONS):
        return None
    if (
        action is Action.ADMIN_MANAGE
        and subject.authentication_assurance is AuthenticationAssurance.PASSWORD_REAUTH
    ):
        return "FALLBACK_UNAVAILABLE"
    if subject.authentication_assurance is AuthenticationAssurance.HARDWARE_WEBAUTHN:
        return "REAUTH_REQUIRED"
    return "FIDO2_REQUIRED"


class AuthorizationService:
    def __init__(
        self,
        *,
        decision_writer: DecisionWriter,
        engine: BuiltinPolicyEngine | None = None,
        development_admin_password_bypass_enabled: bool = False,
        development_governance_password_bypass_enabled: bool = False,
        knowledge_studio_intranet_publication_assurance_mode: str = "HARDWARE_WEBAUTHN",
        knowledge_studio_intranet_publisher_checker_subject_id: UUID | None = None,
    ) -> None:
        self._decision_writer = decision_writer
        self._engine = engine or BuiltinPolicyEngine()
        self._development_admin_password_bypass_enabled = development_admin_password_bypass_enabled
        self._development_governance_password_bypass_enabled = (
            development_governance_password_bypass_enabled
        )
        self._knowledge_studio_intranet_publication_assurance_mode = (
            knowledge_studio_intranet_publication_assurance_mode
        )
        self._knowledge_studio_intranet_publisher_checker_subject_id = (
            knowledge_studio_intranet_publisher_checker_subject_id
        )

    def is_entitled(
        self,
        *,
        subject: SubjectAttributes,
        resource: ResourceAttributes,
        action: Action,
        environment: EnvironmentAttributes,
    ) -> bool:
        """Check durable action entitlement without treating step-up auth as missing RBAC.

        Capability and action-button discovery use this preview so a high-risk operation remains
        visible to an entitled human and can initiate its real reauthentication flow. The command
        path still calls ``authorize`` with the caller's actual assurance and writes the auditable
        decision used by database command fences.
        """

        preview_subject = subject
        if action in HIGH_RISK_ACTIONS:
            preview_subject = replace(
                subject,
                authentication_assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
                authentication_time=environment.requested_at,
            )
        return self._engine.decide(
            subject=preview_subject,
            resource=resource,
            action=action,
            environment=environment,
        ).allowed

    async def authorize(
        self,
        *,
        subject: SubjectAttributes,
        resource: ResourceAttributes,
        action: Action,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> Decision:
        decision = self._engine.decide(
            subject=subject,
            resource=resource,
            action=action,
            environment=environment,
        )
        if self._can_apply_development_admin_password_bypass(
            subject=subject,
            action=action,
            decision=decision,
            environment=environment,
        ):
            decision = Decision(
                decision_id=decision.decision_id,
                effect=Effect.ALLOW,
                reason_codes=("DEVELOPMENT_PASSWORD_BYPASS",),
                policy_versions=(
                    *decision.policy_versions,
                    (
                        "development-admin-password-bypass-v1"
                        if action is Action.ADMIN_MANAGE
                        else "development-governance-admin-password-bypass-v1"
                    ),
                ),
                authentication_assurance=subject.authentication_assurance,
                authentication_time=subject.authentication_time,
            )
        elif self._can_apply_knowledge_studio_intranet_publication_assurance(
            subject=subject,
            action=action,
            decision=decision,
            environment=environment,
        ):
            decision = Decision(
                decision_id=decision.decision_id,
                effect=Effect.ALLOW,
                reason_codes=("INTRANET_DISTINCT_PRINCIPAL",),
                policy_versions=(
                    *decision.policy_versions,
                    "intranet-studio-publication-assurance-v1",
                ),
                authentication_assurance=subject.authentication_assurance,
                authentication_time=subject.authentication_time,
            )
        await self._decision_writer.append_decision(
            decision=decision,
            subject_id=subject.subject_id,
            workspace_id=subject.workspace_id,
            resource_id=resource.resource_id,
            action=action.value,
            request_id=request_id,
        )
        if not decision.allowed:
            remediation_kind = _remediation_kind(action=action, subject=subject, decision=decision)
            if (
                self._development_password_bypass_applies(action)
                and decision.reason_codes
                and set(decision.reason_codes).issubset(AUTHENTICATION_DENIAL_REASONS)
                and subject.authentication_assurance is not AuthenticationAssurance.PASSWORD_REAUTH
            ):
                # The development exception still fails closed for an absent,
                # stale or non-password assurance. Tell the browser to obtain
                # the fresh PASSWORD_REAUTH token that the exception actually
                # requires instead of sending it to disabled WebAuthn.
                remediation_kind = "REAUTH_REQUIRED"
            details: dict[str, object] = {
                "decision_id": str(decision.decision_id),
                "reason_codes": decision.reason_codes,
            }
            if remediation_kind is not None:
                details["remediation"] = {"kind": remediation_kind}
            raise ForbiddenError(
                "The requested action is not permitted.",
                details=details,
            )
        return decision

    async def authorize_catalog_workspace_browse(
        self,
        *,
        subject: SubjectAttributes,
        resource: ResourceAttributes,
        classification_access: ClassificationAccessSnapshot,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> Decision:
        """Authorize the Catalog UI's non-RESTRICTED workspace discovery surface.

        This is an independent, audited policy. It never rewrites a generic
        BuiltinPolicyEngine denial and is intentionally unavailable to data-use,
        mutation, export, candidate, Chat, Quality, Change or Knowledge paths.
        """

        del environment
        reasons: list[str] = []
        allowed_resource_types = {"catalog_asset_browse", "catalog_lineage_browse"}
        if resource.resource_type not in allowed_resource_types:
            reasons.append("CATALOG_BROWSE_RESOURCE_TYPE_REQUIRED")
        if not subject.active:
            reasons.append("SUBJECT_INACTIVE")
        if not resource.active or resource.lifecycle != "ACTIVE":
            reasons.append("RESOURCE_INACTIVE")
        if resource.workspace_id != subject.workspace_id:
            reasons.append("WORKSPACE_MISMATCH")
        if "service-accounts" in subject.groups or subject.job_function == "SERVICE_ACCOUNT":
            reasons.append("HUMAN_ACTOR_REQUIRED")
        if Action.CATALOG_READ in subject.denied_actions:
            reasons.append("EXPLICIT_ACTION_DENY")
        elif Action.CATALOG_READ not in subject.allowed_actions:
            reasons.append("ACTION_NOT_GRANTED")
        if resource.classification is Classification.RESTRICTED:
            reasons.append("RESTRICTED_REQUIRES_SCOPED_AUTHORIZATION")
        elif resource.classification > subject.clearance:
            reasons.append("CLEARANCE_INSUFFICIENT")
        try:
            search_mode = classification_access.rule_for(resource.classification).search_mode
        except (StopIteration, ValueError):
            reasons.append("CLASSIFICATION_POLICY_INVALID")
        else:
            if search_mode is not SearchMode.ABAC:
                reasons.append("CLASSIFICATION_POLICY_DENY")
        classification_policy_version = (
            f"classification-access:{classification_access.posture.value}:"
            f"{classification_access.policy_version or 0}:"
            f"{classification_access.authorization_generation or 0}"
        )
        decision = Decision(
            decision_id=uuid7(),
            effect=Effect.DENY if reasons else Effect.ALLOW,
            reason_codes=tuple(reasons or ["CATALOG_WORKSPACE_DISCOVERY_ALLOW"]),
            policy_versions=("catalog-workspace-discovery-v1", classification_policy_version),
            authentication_assurance=subject.authentication_assurance,
            authentication_time=subject.authentication_time,
        )
        await self._decision_writer.append_decision(
            decision=decision,
            subject_id=subject.subject_id,
            workspace_id=subject.workspace_id,
            resource_id=resource.resource_id,
            action=Action.CATALOG_READ.value,
            request_id=request_id,
        )
        if not decision.allowed:
            raise ForbiddenError(
                "The requested Catalog workspace browse is not permitted.",
                details={
                    "decision_id": str(decision.decision_id),
                    "reason_codes": decision.reason_codes,
                },
            )
        return decision

    def _change_target_decision(
        self,
        *,
        subject: SubjectAttributes,
        resource: ResourceAttributes,
        action: Action,
        classification_access: ClassificationAccessSnapshot,
        environment: EnvironmentAttributes,
    ) -> Decision:
        """Evaluate the CR-only System-responsibility projection from first principles."""

        reasons: list[str] = []
        if resource.resource_type != "catalog_asset_change_target":
            reasons.append("CHANGE_TARGET_RESOURCE_TYPE_REQUIRED")
        if action not in CHANGE_TARGET_ACTIONS:
            reasons.append("CHANGE_TARGET_ACTION_REQUIRED")
        if subject.job_function == "SERVICE_ACCOUNT" or "service-accounts" in subject.groups:
            reasons.append("HUMAN_ACTOR_REQUIRED")
        if resource.lifecycle != "ACTIVE":
            reasons.append("RESOURCE_INACTIVE")
        if resource.system_id is None:
            reasons.append("SYSTEM_SCOPE_REQUIRED")
        elif resource.system_id not in subject.allowed_system_ids:
            reasons.append("SYSTEM_SCOPE_MISMATCH")

        try:
            search_mode = classification_access.rule_for(resource.classification).search_mode
        except (StopIteration, ValueError):
            reasons.append("CLASSIFICATION_POLICY_INVALID")
        else:
            if resource.classification is Classification.RESTRICTED:
                if search_mode is not SearchMode.EXPLICIT_GRANT_ONLY:
                    reasons.append("CLASSIFICATION_POLICY_DENY")
                if (
                    resource.domain_id is None
                    or resource.domain_id not in subject.allowed_domain_ids
                ):
                    reasons.append("DOMAIN_SCOPE_MISMATCH")
                if not (
                    resource.resource_id in classification_access.restricted_resource_ids
                    or (
                        resource.system_id is not None
                        and resource.system_id in classification_access.restricted_system_ids
                    )
                    or (
                        resource.domain_id is not None
                        and resource.domain_id in classification_access.restricted_domain_ids
                    )
                ):
                    reasons.append("RESTRICTED_EXPLICIT_GRANT_REQUIRED")
            elif search_mode is not SearchMode.ABAC:
                reasons.append("CLASSIFICATION_POLICY_DENY")

        # Domain is deliberately absent only from the non-RESTRICTED CR authorization
        # projection. The actual Domain remains on the resource and binding evidence.
        policy_resource = (
            resource
            if resource.classification is Classification.RESTRICTED
            else replace(resource, domain_id=None)
        )
        baseline = self._engine.decide(
            subject=subject,
            resource=policy_resource,
            action=action,
            environment=environment,
        )
        if baseline.reason_codes != ("POLICY_ALLOW",):
            reasons.extend(baseline.reason_codes)
        unique_reasons = tuple(dict.fromkeys(reasons))
        classification_policy_version = (
            f"classification-access:{classification_access.posture.value}:"
            f"{classification_access.policy_version or 0}:"
            f"{classification_access.authorization_generation or 0}"
        )
        return Decision(
            decision_id=baseline.decision_id,
            effect=Effect.DENY if unique_reasons else Effect.ALLOW,
            reason_codes=unique_reasons or ("CHANGE_TARGET_SYSTEM_SCOPE_ALLOW",),
            policy_versions=tuple(
                dict.fromkeys(
                    (
                        *baseline.policy_versions,
                        "change-target-system-responsibility-v1",
                        classification_policy_version,
                    )
                )
            ),
            authentication_assurance=baseline.authentication_assurance,
            authentication_time=baseline.authentication_time,
        )

    async def authorize_change_target(
        self,
        *,
        subject: SubjectAttributes,
        resource: ResourceAttributes,
        action: Action,
        classification_access: ClassificationAccessSnapshot,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> Decision:
        decision = self._change_target_decision(
            subject=subject,
            resource=resource,
            action=action,
            classification_access=classification_access,
            environment=environment,
        )
        await self._decision_writer.append_decision(
            decision=decision,
            subject_id=subject.subject_id,
            workspace_id=subject.workspace_id,
            resource_id=resource.resource_id,
            action=action.value,
            request_id=request_id,
        )
        if not decision.allowed:
            details: dict[str, object] = {
                "decision_id": str(decision.decision_id),
                "reason_codes": decision.reason_codes,
            }
            remediation_kind = _remediation_kind(
                action=action,
                subject=subject,
                decision=decision,
            )
            if remediation_kind is not None:
                details["remediation"] = {"kind": remediation_kind}
            raise ForbiddenError(
                "The requested change target is not permitted.",
                details=details,
            )
        return decision

    async def filter_authorized_change_targets(
        self,
        *,
        subject: SubjectAttributes,
        resources: Sequence[ResourceAttributes],
        action: Action,
        classification_access: ClassificationAccessSnapshot,
        environment: EnvironmentAttributes,
        request_id: str,
        parent_resource_id: UUID,
    ) -> tuple[ResourceAttributes, ...]:
        evaluated = tuple(
            (
                resource,
                self._change_target_decision(
                    subject=subject,
                    resource=resource,
                    action=action,
                    classification_access=classification_access,
                    environment=environment,
                ),
            )
            for resource in resources
        )
        if not evaluated:
            return ()
        items = tuple(
            DecisionAuditItem(resource_id=resource.resource_id, decision=decision)
            for resource, decision in evaluated
        )
        if isinstance(self._decision_writer, DecisionSetWriter):
            await self._decision_writer.append_decision_set(
                decision_id=uuid7(),
                items=items,
                subject_id=subject.subject_id,
                workspace_id=subject.workspace_id,
                parent_resource_id=parent_resource_id,
                action=action.value,
                request_id=request_id,
            )
        else:
            for item in items:
                await self._decision_writer.append_decision(
                    decision=item.decision,
                    subject_id=subject.subject_id,
                    workspace_id=subject.workspace_id,
                    resource_id=item.resource_id,
                    action=action.value,
                    request_id=request_id,
                )
        return tuple(resource for resource, decision in evaluated if decision.allowed)

    def _can_apply_development_admin_password_bypass(
        self,
        *,
        subject: SubjectAttributes,
        action: Action,
        decision: Decision,
        environment: EnvironmentAttributes,
    ) -> bool:
        return (
            self._development_password_bypass_applies(action)
            and not decision.allowed
            and bool(decision.reason_codes)
            and set(decision.reason_codes).issubset(AUTHENTICATION_DENIAL_REASONS)
            and subject.authentication_assurance
            in {
                AuthenticationAssurance.PASSWORD,
                AuthenticationAssurance.PASSWORD_REAUTH,
            }
            and subject.authentication_time is not None
            and subject.authentication_time
            <= environment.requested_at + environment.maximum_clock_skew
            and environment.requested_at - subject.authentication_time
            <= environment.maximum_authentication_age
        )

    def _development_password_bypass_applies(self, action: Action) -> bool:
        return (
            self._development_admin_password_bypass_enabled and action is Action.ADMIN_MANAGE
        ) or (
            self._development_governance_password_bypass_enabled
            and action in DEVELOPMENT_GOVERNANCE_PASSWORD_BYPASS_ACTIONS
        )

    def _can_apply_knowledge_studio_intranet_publication_assurance(
        self,
        *,
        subject: SubjectAttributes,
        action: Action,
        decision: Decision,
        environment: EnvironmentAttributes,
    ) -> bool:
        return (
            self._knowledge_studio_intranet_publication_assurance_mode
            == "INTRANET_DISTINCT_PRINCIPAL"
            and action is Action.KG_PUBLISH
            and subject.subject_id == self._knowledge_studio_intranet_publisher_checker_subject_id
            and not decision.allowed
            and bool(decision.reason_codes)
            and set(decision.reason_codes).issubset(
                {"PHISHING_RESISTANT_AUTH_REQUIRED", "HUMAN_ACTOR_REQUIRED"}
            )
            and subject.job_function == "SERVICE_ACCOUNT"
            and subject.groups == frozenset({"service-accounts", "k9-publisher-checkers"})
            and subject.allowed_actions
            == frozenset({Action.KG_PUBLISH, Action.KG_REVIEW, Action.KG_READ})
        )

    async def can_review_quarantined_catalog(
        self,
        *,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> bool:
        """Return the narrowly-scoped admin review decision without denying ordinary catalog reads.

        This is deliberately separate from generic catalog ABAC: it permits a human security
        administrator to inspect DataHub projections that are awaiting classification, while
        preserving normal lifecycle/classification filtering for every other subject and surface.
        """
        del environment
        reasons: list[str] = []
        if not subject.active:
            reasons.append("SUBJECT_INACTIVE")
        if "security-administrators" not in subject.groups:
            reasons.append("SECURITY_ADMINISTRATOR_REQUIRED")
        if "service-accounts" in subject.groups or subject.job_function == "SERVICE_ACCOUNT":
            reasons.append("HUMAN_ADMINISTRATOR_REQUIRED")
        for action in (Action.CATALOG_SEARCH, Action.CATALOG_READ, Action.ADMIN_MANAGE):
            if action in subject.denied_actions:
                reasons.append("EXPLICIT_ACTION_DENY")
            elif action not in subject.allowed_actions:
                reasons.append("ACTION_NOT_GRANTED")
        if subject.clearance < Classification.RESTRICTED:
            reasons.append("CLEARANCE_INSUFFICIENT")
        decision = Decision(
            decision_id=uuid7(),
            effect=Effect.DENY if reasons else Effect.ALLOW,
            reason_codes=tuple(reasons or ["POLICY_ALLOW"]),
            policy_versions=("builtin-admin-quarantine-review-v1",),
            authentication_assurance=subject.authentication_assurance,
            authentication_time=subject.authentication_time,
        )
        await self._decision_writer.append_decision(
            decision=decision,
            subject_id=subject.subject_id,
            workspace_id=subject.workspace_id,
            resource_id=subject.workspace_id,
            action=Action.CATALOG_QUARANTINE_READ.value,
            request_id=request_id,
        )
        return decision.allowed

    async def authorize_admin_fallback(
        self,
        *,
        subject: SubjectAttributes,
        resource: ResourceAttributes,
        stage: AdminFallbackStage,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> Decision:
        """Evaluate a password-reauth compensating control outside the generic ABAC path."""
        reasons: list[str] = []
        if not subject.active:
            reasons.append("SUBJECT_INACTIVE")
        if not resource.active:
            reasons.append("RESOURCE_INACTIVE")
        if subject.workspace_id != resource.workspace_id:
            reasons.append("WORKSPACE_MISMATCH")
        if Action.ADMIN_MANAGE in subject.denied_actions:
            reasons.append("EXPLICIT_ACTION_DENY")
        if Action.ADMIN_MANAGE not in subject.allowed_actions:
            reasons.append("ACTION_NOT_GRANTED")
        if resource.classification > subject.clearance:
            reasons.append("CLEARANCE_INSUFFICIENT")
        if "security-administrators" not in subject.groups:
            reasons.append("SECURITY_ADMINISTRATOR_REQUIRED")
        if "service-accounts" in subject.groups or subject.job_function == "SERVICE_ACCOUNT":
            reasons.append("HUMAN_ADMINISTRATOR_REQUIRED")
        allowed_assurance = {AuthenticationAssurance.PASSWORD_REAUTH}
        if stage is AdminFallbackStage.READ:
            # Read-only administration discovery never grants a mutation. It
            # must remain available after a normal OIDC login so the browser
            # can hydrate its server-derived menu without a reauth loop.
            allowed_assurance = set(AuthenticationAssurance)
        elif stage is AdminFallbackStage.APPROVE:
            allowed_assurance.add(AuthenticationAssurance.HARDWARE_WEBAUTHN)
        if subject.authentication_assurance not in allowed_assurance:
            reasons.append("PASSWORD_REAUTH_REQUIRED")
        if stage is not AdminFallbackStage.READ:
            if subject.authentication_time is None:
                reasons.append("AUTHENTICATION_TIME_REQUIRED")
            elif subject.authentication_time > (
                environment.requested_at + environment.maximum_clock_skew
            ):
                reasons.append("AUTHENTICATION_TIME_INVALID")
            elif (
                environment.requested_at - subject.authentication_time
                > environment.maximum_authentication_age
            ):
                reasons.append("AUTHENTICATION_TOO_OLD")
        decision = Decision(
            decision_id=uuid7(),
            effect=Effect.DENY if reasons else Effect.ALLOW,
            reason_codes=tuple(reasons or ["POLICY_ALLOW"]),
            policy_versions=("builtin-admin-fallback-v1",),
            authentication_assurance=subject.authentication_assurance,
            authentication_time=subject.authentication_time,
        )
        await self._decision_writer.append_decision(
            decision=decision,
            subject_id=subject.subject_id,
            workspace_id=subject.workspace_id,
            resource_id=resource.resource_id,
            action=stage.value,
            request_id=request_id,
        )
        if not decision.allowed:
            details: dict[str, object] = {
                "decision_id": str(decision.decision_id),
                "reason_codes": decision.reason_codes,
            }
            authentication_reasons = {
                "PASSWORD_REAUTH_REQUIRED",
                "AUTHENTICATION_TIME_REQUIRED",
                "AUTHENTICATION_TIME_INVALID",
                "AUTHENTICATION_TOO_OLD",
            }
            if set(reasons) and set(reasons).issubset(authentication_reasons):
                details["remediation"] = {"kind": "REAUTH_REQUIRED"}
            raise ForbiddenError(
                "The administrator fallback action is not permitted.", details=details
            )
        return decision

    async def filter_authorized(
        self,
        *,
        subject: SubjectAttributes,
        resources: Sequence[ResourceAttributes],
        action: Action,
        environment: EnvironmentAttributes,
        request_id: str,
        parent_resource_id: UUID,
    ) -> tuple[ResourceAttributes, ...]:
        """Evaluate a bounded resource set and persist one grouped audit event when supported."""
        evaluated = tuple(
            (
                resource,
                self._engine.decide(
                    subject=subject,
                    resource=resource,
                    action=action,
                    environment=environment,
                ),
            )
            for resource in resources
        )
        if not evaluated:
            return ()
        items = tuple(
            DecisionAuditItem(resource_id=resource.resource_id, decision=decision)
            for resource, decision in evaluated
        )
        if isinstance(self._decision_writer, DecisionSetWriter):
            await self._decision_writer.append_decision_set(
                decision_id=uuid7(),
                items=items,
                subject_id=subject.subject_id,
                workspace_id=subject.workspace_id,
                parent_resource_id=parent_resource_id,
                action=action.value,
                request_id=request_id,
            )
        else:
            for item in items:
                await self._decision_writer.append_decision(
                    decision=item.decision,
                    subject_id=subject.subject_id,
                    workspace_id=subject.workspace_id,
                    resource_id=item.resource_id,
                    action=action.value,
                    request_id=request_id,
                )
        return tuple(resource for resource, decision in evaluated if decision.allowed)


class NullDecisionWriter:
    """Test-only writer; production wiring must use durable audit persistence."""

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

    async def append_decision_set(
        self,
        *,
        decision_id: UUID,
        items: Sequence[DecisionAuditItem],
        subject_id: UUID,
        workspace_id: UUID,
        parent_resource_id: UUID,
        action: str,
        request_id: str,
    ) -> None:
        del (
            decision_id,
            items,
            subject_id,
            workspace_id,
            parent_resource_id,
            action,
            request_id,
        )
