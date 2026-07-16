from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from datariver.application.dto import DecisionAuditItem
from datariver.application.ports import DecisionSetWriter, DecisionWriter
from datariver.domain.authz import (
    Action,
    AuthenticationAssurance,
    BuiltinPolicyEngine,
    Decision,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ForbiddenError, uuid7

AUTHENTICATION_DENIAL_REASONS = frozenset(
    {
        "PHISHING_RESISTANT_AUTH_REQUIRED",
        "AUTHENTICATION_TIME_REQUIRED",
        "AUTHENTICATION_TIME_INVALID",
        "AUTHENTICATION_TOO_OLD",
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
        self, *, decision_writer: DecisionWriter, engine: BuiltinPolicyEngine | None = None
    ) -> None:
        self._decision_writer = decision_writer
        self._engine = engine or BuiltinPolicyEngine()

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
