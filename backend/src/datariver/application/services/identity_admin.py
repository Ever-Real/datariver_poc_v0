from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from datariver.application.identity_admin import (
    IdentityAdministration,
    IdentityProfileTarget,
    IdentityUserDraft,
    IdentityUserProfile,
    IdentityUserProfileDraft,
    ProvisionedWorkspaceUser,
    TemporaryPasswordReset,
    UpdatedWorkspaceIdentityProfile,
    WorkspaceIdentityProfile,
)
from datariver.application.ports import AdminAccessUnitOfWork
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.admin_access import AdminFallbackStage
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import (
    ConflictError,
    DomainEvent,
    NotFoundError,
    ValidationError,
    uuid7,
)
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

    async def get_user_profile(
        self,
        *,
        workspace_id: UUID,
        target_subject_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> WorkspaceIdentityProfile:
        await self._authorization.authorize_admin_fallback(
            subject=subject,
            resource=self._resource(workspace_id, target_subject_id),
            stage=AdminFallbackStage.READ,
            environment=environment,
            request_id=request_id,
        )
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await uow.memberships.assert_eligible_human_administrators(
                workspace_id=workspace_id,
                subject_ids=frozenset({subject.subject_id}),
            )
            target = await uow.memberships.get_identity_profile_target(
                workspace_id=workspace_id,
                subject_id=target_subject_id,
            )
            self._assert_identity_target(target, environment=environment)
        assert target is not None
        provider_profile = await self._provider.get_user_profile(
            external_subject=target.external_subject
        )
        return self._workspace_profile(target=target, provider_profile=provider_profile)

    async def update_user_profile(
        self,
        *,
        workspace_id: UUID,
        target_subject_id: UUID,
        expected_membership_version: int,
        draft: IdentityUserProfileDraft,
        department_id: UUID | None,
        job_function: str | None,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> UpdatedWorkspaceIdentityProfile:
        decision = await self._authorization.authorize(
            subject=subject,
            resource=self._resource(workspace_id, target_subject_id),
            action=Action.ADMIN_MANAGE,
            environment=environment,
            request_id=request_id,
        )
        operation = f"admin.identity.profile.update:{target_subject_id}"
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await uow.lock_workspace_access(workspace_id=workspace_id)
            await uow.memberships.assert_eligible_human_administrators(
                workspace_id=workspace_id,
                subject_ids=frozenset({subject.subject_id}),
            )
            target = await uow.memberships.get_identity_profile_target(
                workspace_id=workspace_id,
                subject_id=target_subject_id,
                for_update=True,
            )
            self._assert_identity_target(
                target,
                environment=environment,
            )
            existing = await uow.idempotency.get_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
            )
            if existing is not None:
                self._verify_idempotency(
                    request_hash=request_hash,
                    stored_hash=existing.request_hash,
                    actor_id=subject.subject_id,
                    stored_actor=existing.result.get("actor_id"),
                )
                return self._updated_profile_from_result(existing.result)
            self._assert_identity_target(
                target,
                environment=environment,
                expected_membership_version=expected_membership_version,
            )
            assert target is not None
            provider_profile = await self._provider.update_user_profile(
                external_subject=target.external_subject,
                draft=draft,
            )
            next_version = await uow.memberships.update_identity_profile(
                target=target,
                expected_membership_version=expected_membership_version,
                display_name=draft.display_name,
                email=provider_profile.email,
                department_id=department_id,
                job_function=job_function,
            )
            result = UpdatedWorkspaceIdentityProfile(
                subject_id=target.subject_id,
                username=provider_profile.username,
                display_name=draft.display_name,
                email=provider_profile.email,
                department_id=department_id,
                job_function=job_function,
                membership_version=next_version,
            )
            await uow.outbox.add_events(
                [
                    DomainEvent.create(
                        event_type="iam.workspace_identity.profile_updated.v1",
                        aggregate_type="workspace_membership",
                        aggregate_id=target.subject_id,
                        workspace_id=workspace_id,
                        payload={
                            "actor_id": str(subject.subject_id),
                            "updated_scopes": [
                                "IDENTITY_PROVIDER_PROFILE",
                                "WORKSPACE_MEMBERSHIP_PROFILE",
                            ],
                            "membership_version": next_version,
                            "policy_decision_id": str(decision.decision_id),
                            "provider": "KEYCLOAK",
                        },
                    )
                ]
            )
            await uow.idempotency.save_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                result={
                    "actor_id": str(subject.subject_id),
                    "subject_id": str(result.subject_id),
                    "username": result.username,
                    "display_name": result.display_name,
                    "email": result.email,
                    "department_id": (str(result.department_id) if result.department_id else None),
                    "job_function": result.job_function,
                    "membership_version": result.membership_version,
                },
            )
            await uow.commit()
            return result

    async def reset_temporary_password(
        self,
        *,
        workspace_id: UUID,
        target_subject_id: UUID,
        expected_membership_version: int,
        temporary_password: str,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> TemporaryPasswordReset:
        decision = await self._authorization.authorize(
            subject=subject,
            resource=self._resource(workspace_id, target_subject_id),
            action=Action.ADMIN_MANAGE,
            environment=environment,
            request_id=request_id,
        )
        operation = f"admin.identity.password.reset:{target_subject_id}"
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await uow.lock_workspace_access(workspace_id=workspace_id)
            await uow.memberships.assert_eligible_human_administrators(
                workspace_id=workspace_id,
                subject_ids=frozenset({subject.subject_id}),
            )
            target = await uow.memberships.get_identity_profile_target(
                workspace_id=workspace_id,
                subject_id=target_subject_id,
                for_update=True,
            )
            self._assert_identity_target(
                target,
                environment=environment,
            )
            existing = await uow.idempotency.get_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
            )
            if existing is not None:
                self._verify_idempotency(
                    request_hash=request_hash,
                    stored_hash=existing.request_hash,
                    actor_id=subject.subject_id,
                    stored_actor=existing.result.get("actor_id"),
                )
                return TemporaryPasswordReset(subject_id=target_subject_id)
            self._assert_identity_target(
                target,
                environment=environment,
                expected_membership_version=expected_membership_version,
            )
            assert target is not None
            await self._provider.reset_temporary_password(
                external_subject=target.external_subject,
                temporary_password=temporary_password,
            )
            result = TemporaryPasswordReset(subject_id=target.subject_id)
            await uow.outbox.add_events(
                [
                    DomainEvent.create(
                        event_type="iam.workspace_identity.temporary_password_reset.v1",
                        aggregate_type="workspace_membership",
                        aggregate_id=target.subject_id,
                        workspace_id=workspace_id,
                        payload={
                            "actor_id": str(subject.subject_id),
                            "policy_decision_id": str(decision.decision_id),
                            "provider": "KEYCLOAK",
                            "sessions_revoked": True,
                            "temporary_password_required": True,
                        },
                    )
                ]
            )
            await uow.idempotency.save_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                result={
                    "actor_id": str(subject.subject_id),
                    "subject_id": str(target.subject_id),
                    "sessions_revoked": True,
                    "temporary_password_required": True,
                },
            )
            await uow.commit()
            return result

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
        if role_id is not None:
            async with self._uow_factory() as preflight:
                await preflight.set_security_context(
                    workspace_id=draft.workspace_id,
                    subject_id=subject.subject_id,
                )
                await preflight.memberships.assert_eligible_human_administrators(
                    workspace_id=draft.workspace_id,
                    subject_ids=frozenset({subject.subject_id}),
                )
                await preflight.memberships.assert_assignable_human_role(
                    workspace_id=draft.workspace_id,
                    role_id=role_id,
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

    def _assert_identity_target(
        self,
        target: IdentityProfileTarget | None,
        *,
        environment: EnvironmentAttributes,
        expected_membership_version: int | None = None,
    ) -> None:
        if target is None or target.issuer != self._issuer:
            raise NotFoundError("The target managed identity does not exist.")
        if (
            not target.subject_active
            or not target.membership_active
            or target.service_account
            or (
                target.access_expires_at is not None
                and target.access_expires_at <= environment.requested_at
            )
        ):
            raise ValidationError("Only an active human identity can be administered.")
        if (
            expected_membership_version is not None
            and target.membership_version != expected_membership_version
        ):
            raise ConflictError("The target workspace identity changed during the operation.")

    @staticmethod
    def _resource(workspace_id: UUID, target_subject_id: UUID) -> ResourceAttributes:
        return ResourceAttributes(
            resource_id=target_subject_id,
            workspace_id=workspace_id,
            resource_type="identity_administration",
            owner_department_id=None,
            system_id=None,
            domain_id=None,
            classification=Classification.RESTRICTED,
            lifecycle="ACTIVE",
            owner_subject_id=target_subject_id,
        )

    @staticmethod
    def _workspace_profile(
        *,
        target: IdentityProfileTarget,
        provider_profile: IdentityUserProfile,
    ) -> WorkspaceIdentityProfile:
        if provider_profile.external_subject != target.external_subject:
            raise ConflictError("The identity provider returned a different subject.")
        return WorkspaceIdentityProfile(
            subject_id=target.subject_id,
            username=provider_profile.username,
            display_name=provider_profile.display_name or target.display_name,
            email=provider_profile.email,
            first_name=provider_profile.first_name,
            last_name=provider_profile.last_name,
            department_id=target.department_id,
            job_function=target.job_function,
            membership_version=target.membership_version,
            provider_enabled=provider_profile.enabled,
            email_verified=provider_profile.email_verified,
            required_actions=provider_profile.required_actions,
        )

    @staticmethod
    def _verify_idempotency(
        *,
        request_hash: str,
        stored_hash: str,
        actor_id: UUID,
        stored_actor: object,
    ) -> None:
        if request_hash != stored_hash:
            raise ConflictError("The idempotency key was used with a different request.")
        if stored_actor != str(actor_id):
            raise ConflictError("The idempotency key belongs to another administrator.")

    @staticmethod
    def _updated_profile_from_result(
        result: dict[str, object],
    ) -> UpdatedWorkspaceIdentityProfile:
        return UpdatedWorkspaceIdentityProfile(
            subject_id=UUID(str(result["subject_id"])),
            username=str(result["username"]),
            display_name=str(result["display_name"]),
            email=str(result["email"]),
            department_id=(
                UUID(str(result["department_id"]))
                if result.get("department_id") is not None
                else None
            ),
            job_function=(
                str(result["job_function"]) if result.get("job_function") is not None else None
            ),
            membership_version=int(str(result["membership_version"])),
        )
