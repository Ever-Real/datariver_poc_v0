from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from datariver.application.identity_admin import (
    IdentityAdministration,
    IdentityUserDraft,
    ProvisionedWorkspaceUser,
)
from datariver.application.ports import AdminAccessUnitOfWork
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ConflictError, DomainEvent, uuid7
from datariver.domain.membership_renewal import RENEWAL_TERM_MONTHS, add_calendar_months


class IdentityAdminService:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], AdminAccessUnitOfWork],
        authorization: AuthorizationService,
        provider: IdentityAdministration,
        issuer: str,
    ) -> None:
        self._uow_factory = uow_factory
        self._authorization = authorization
        self._provider = provider
        self._issuer = issuer

    async def provision_user(
        self,
        *,
        draft: IdentityUserDraft,
        department_id: UUID | None,
        job_function: str | None,
        role_id: UUID | None,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> ProvisionedWorkspaceUser:
        decision = await self._authorization.authorize(
            subject=subject,
            resource=ResourceAttributes(
                resource_id=draft.workspace_id,
                workspace_id=draft.workspace_id,
                resource_type="identity_provisioning",
                owner_department_id=None,
                system_id=None,
                domain_id=None,
                classification=Classification.RESTRICTED,
                lifecycle="ACTIVE",
                owner_subject_id=None,
            ),
            action=Action.ADMIN_MANAGE,
            environment=environment,
            request_id=request_id,
        )
        identity = await self._provider.ensure_disabled_user(draft)
        operation = "admin.identity.provision"
        async with self._uow_factory() as uow:
            await uow.set_security_context(
                workspace_id=draft.workspace_id, subject_id=subject.subject_id
            )
            await uow.lock_workspace_access(workspace_id=draft.workspace_id)
            await uow.memberships.assert_eligible_human_administrators(
                workspace_id=draft.workspace_id,
                subject_ids=frozenset({subject.subject_id}),
            )
            existing = await uow.idempotency.get_result(
                workspace_id=draft.workspace_id,
                key=idempotency_key,
                operation=operation,
            )
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise ConflictError(
                        "The idempotency key was used with a different user profile."
                    )
                if existing.result.get("actor_id") != str(subject.subject_id):
                    raise ConflictError("The idempotency key belongs to another administrator.")
                result = ProvisionedWorkspaceUser(
                    subject_id=UUID(str(existing.result["subject_id"])),
                    external_subject=str(existing.result["external_subject"]),
                    username=str(existing.result["username"]),
                    display_name=str(existing.result["display_name"]),
                    email=str(existing.result["email"]),
                    workspace_id=draft.workspace_id,
                    role_id=(
                        UUID(str(existing.result["role_id"]))
                        if existing.result.get("role_id") is not None
                        else None
                    ),
                    access_expires_at=datetime.fromisoformat(
                        str(existing.result["access_expires_at"])
                    ),
                )
            else:
                result = await uow.memberships.provision_identity_membership(
                    subject_id=uuid7(),
                    workspace_id=draft.workspace_id,
                    issuer=self._issuer,
                    external_subject=identity.external_subject,
                    username=identity.username,
                    display_name=draft.display_name,
                    email=draft.email,
                    department_id=department_id,
                    job_function=job_function,
                    role_id=role_id,
                    access_expires_at=add_calendar_months(
                        environment.requested_at, RENEWAL_TERM_MONTHS
                    ),
                )
                await uow.outbox.add_events(
                    [
                        DomainEvent.create(
                            event_type="iam.workspace_identity.provisioned.v1",
                            aggregate_type="workspace_membership",
                            aggregate_id=result.subject_id,
                            workspace_id=draft.workspace_id,
                            payload={
                                "actor_id": str(subject.subject_id),
                                "role_id": str(role_id) if role_id else None,
                                "policy_decision_id": str(decision.decision_id),
                                "provider": "KEYCLOAK",
                                "temporary_password_required": True,
                            },
                        )
                    ]
                )
                await uow.idempotency.save_result(
                    workspace_id=draft.workspace_id,
                    key=idempotency_key,
                    operation=operation,
                    request_hash=request_hash,
                    result={
                        "actor_id": str(subject.subject_id),
                        "subject_id": str(result.subject_id),
                        "external_subject": result.external_subject,
                        "username": result.username,
                        "display_name": result.display_name,
                        "email": result.email,
                        "role_id": str(result.role_id) if result.role_id else None,
                        "access_expires_at": result.access_expires_at.isoformat(),
                    },
                )
                await uow.commit()
        if result.external_subject != identity.external_subject:
            raise ConflictError("The identity provider result changed during a retry.")
        await self._provider.enable_user(external_subject=result.external_subject)
        return result
