from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from uuid import UUID

from datariver.application.dto import (
    AdminAccessRequestPage,
    AdminReadContext,
    MembershipChangeRequestActivityPage,
    MembershipOwnedTablePage,
    MembershipRenewalPage,
    MembershipRenewalRecord,
    ProfileRolePolicyCatalog,
    ProfileRolePolicyItem,
    ProfileRoleServicePolicy,
    ProfileRoleTransitionResult,
    SystemAssigneeCandidatePage,
    SystemAssigneePage,
    SystemDirectoryEntry,
    SystemDirectoryPage,
    SystemSchemaScopeCandidatePage,
    SystemSchemaScopePage,
    WorkspaceMembershipAccessRecord,
    WorkspaceMembershipPage,
    WorkspaceMembershipSummary,
)
from datariver.application.ports import AdminAccessUnitOfWork
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.admin_access import (
    MAXIMUM_SYSTEM_CODE_CANDIDATES,
    AdminAccessDecision,
    AdminAccessRequest,
    AdminAccessRequestState,
    AdminFallbackStage,
    AdminOperation,
    MembershipAccessUpdate,
    SystemAssigneePatchCommand,
    SystemAssigneeUpdateCommand,
    SystemSchemaScopePatchCommand,
    canonical_system_code_base,
    system_code_collision_candidate,
)
from datariver.domain.authz import (
    Action,
    AuthenticationAssurance,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.capability_catalog import CAPABILITY_BY_ACTION, CAPABILITY_SERVICES
from datariver.domain.common import (
    ConflictError,
    DomainEvent,
    ForbiddenError,
    NotFoundError,
    ValidationError,
    canonical_json_hash,
)
from datariver.domain.membership_renewal import (
    MembershipRenewalDecision,
    MembershipRenewalRequest,
    MembershipRenewalState,
)
from datariver.domain.profile_roles import (
    PROFILE_ROLE_BY_TIER,
    PROFILE_ROLE_POLICIES,
    PROFILE_ROLE_POLICY_VERSION,
    ProfileRoleTier,
)


class AdminAccessService:
    def __init__(
        self,
        uow_factory: Callable[[], AdminAccessUnitOfWork],
        authorization: AuthorizationService,
        *,
        fallback_enabled: bool,
        fallback_ttl_seconds: int,
        development_admin_password_bypass_enabled: bool = False,
        development_system_configuration_enabled: bool = False,
        identity_administration_enabled: bool = False,
    ) -> None:
        self._uow_factory = uow_factory
        self._authorization = authorization
        self._fallback_enabled = fallback_enabled
        self._fallback_ttl = timedelta(seconds=fallback_ttl_seconds)
        self._development_admin_password_bypass_enabled = development_admin_password_bypass_enabled
        self._development_system_configuration_enabled = development_system_configuration_enabled
        self._identity_administration_enabled = identity_administration_enabled

    async def list_workspace_memberships(
        self,
        *,
        workspace_id: UUID,
        limit: int,
        query: str | None = None,
        active: bool | None = None,
        cursor: str | None = None,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> WorkspaceMembershipPage:
        _validate_admin_page_limit(limit)
        await self._authorize_read(
            workspace_id=workspace_id,
            resource_id=workspace_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await uow.memberships.assert_eligible_human_administrators(
                workspace_id=workspace_id, subject_ids=frozenset({subject.subject_id})
            )
            normalized_query = query.strip().casefold() if query and query.strip() else None
            return await uow.memberships.list(
                workspace_id=workspace_id,
                limit=limit,
                query=normalized_query,
                active=active,
                cursor=cursor,
            )

    async def list_systems(
        self,
        *,
        workspace_id: UUID,
        limit: int,
        query: str | None = None,
        active: bool | None = None,
        cursor: str | None = None,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> SystemDirectoryPage:
        _validate_admin_page_limit(limit)
        await self._authorize_read(
            workspace_id=workspace_id,
            resource_id=workspace_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await uow.memberships.assert_eligible_human_administrators(
                workspace_id=workspace_id, subject_ids=frozenset({subject.subject_id})
            )
            normalized_query = query.strip().lower() if query and query.strip() else None
            return await uow.systems.list(
                workspace_id=workspace_id,
                limit=limit,
                query=normalized_query,
                active=active,
                cursor=cursor,
            )

    async def create_system(
        self,
        *,
        workspace_id: UUID,
        name: str,
        description: str,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> SystemDirectoryEntry:
        decision = await self._authorization.authorize(
            subject=subject,
            resource=self._resource(workspace_id, workspace_id),
            action=Action.ADMIN_MANAGE,
            environment=environment,
            request_id=request_id,
        )
        operation = "admin.system.create"
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await uow.lock_workspace_access(workspace_id=workspace_id)
            await uow.memberships.assert_eligible_human_administrators(
                workspace_id=workspace_id, subject_ids=frozenset({subject.subject_id})
            )
            existing = await uow.idempotency.get_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
            )
            if existing is not None:
                _verify_idempotency(
                    existing.request_hash,
                    request_hash,
                    existing.result.get("actor_id"),
                    subject.subject_id,
                )
                return SystemDirectoryEntry(
                    system_id=UUID(str(existing.result["system_id"])),
                    code=str(existing.result["code"]),
                    name=str(existing.result["name"]),
                    description=str(existing.result["description"]),
                    active=True,
                    version=int(existing.result["version"]),
                )
            base_code = canonical_system_code_base(name)
            code: str | None = None
            for collision_index in range(MAXIMUM_SYSTEM_CODE_CANDIDATES):
                candidate = system_code_collision_candidate(base_code, collision_index)
                if not await uow.systems.code_exists(
                    workspace_id=workspace_id,
                    code=candidate,
                ):
                    code = candidate
                    break
            if code is None:
                raise ConflictError(
                    "No canonical System code is available for this name in the workspace."
                )
            result = await uow.systems.create(
                workspace_id=workspace_id,
                code=code,
                name=name.strip(),
                description=description.strip(),
            )
            await uow.outbox.add_events(
                [
                    DomainEvent.create(
                        event_type="platform.data_system.created.v1",
                        aggregate_type="data_system",
                        aggregate_id=result.system_id,
                        workspace_id=workspace_id,
                        payload={
                            "actor_id": str(subject.subject_id),
                            "assurance": subject.authentication_assurance.value,
                            "code": result.code,
                            "policy_decision_id": str(decision.decision_id),
                            "request_hash": request_hash,
                            "version": result.version,
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
                    "system_id": str(result.system_id),
                    "code": result.code,
                    "name": result.name,
                    "description": result.description,
                    "version": result.version,
                },
            )
            await uow.commit()
            return result

    async def list_system_assignees(
        self,
        *,
        workspace_id: UUID,
        system_id: UUID,
        limit: int,
        cursor: str | None,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> SystemAssigneePage:
        _validate_admin_page_limit(limit)
        await self._authorize_read(
            workspace_id=workspace_id,
            resource_id=system_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await uow.memberships.assert_eligible_human_administrators(
                workspace_id=workspace_id, subject_ids=frozenset({subject.subject_id})
            )
            return await uow.systems.list_assignees(
                workspace_id=workspace_id,
                system_id=system_id,
                limit=limit,
                cursor=cursor,
            )

    async def list_system_assignee_candidates(
        self,
        *,
        workspace_id: UUID,
        limit: int,
        query: str | None,
        cursor: str | None,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> SystemAssigneeCandidatePage:
        _validate_admin_page_limit(limit)
        await self._authorize_read(
            workspace_id=workspace_id,
            resource_id=workspace_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await uow.memberships.assert_eligible_human_administrators(
                workspace_id=workspace_id,
                subject_ids=frozenset({subject.subject_id}),
            )
            return await uow.systems.list_assignee_candidates(
                workspace_id=workspace_id,
                limit=limit,
                query=query.strip().casefold() if query and query.strip() else None,
                cursor=cursor,
            )

    async def list_system_schema_scopes(
        self,
        *,
        workspace_id: UUID,
        system_id: UUID,
        limit: int,
        cursor: str | None,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> SystemSchemaScopePage:
        _validate_admin_page_limit(limit)
        await self._authorize_read(
            workspace_id=workspace_id,
            resource_id=system_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await self._assert_verified_canonical_admin(
                uow=uow, workspace_id=workspace_id, subject_id=subject.subject_id
            )
            return await uow.systems.list_schema_scopes(
                workspace_id=workspace_id,
                system_id=system_id,
                limit=limit,
                cursor=cursor,
            )

    async def list_system_schema_scope_candidates(
        self,
        *,
        workspace_id: UUID,
        system_id: UUID,
        limit: int,
        query: str | None,
        cursor: str | None,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> SystemSchemaScopeCandidatePage:
        _validate_admin_page_limit(limit)
        await self._authorize_read(
            workspace_id=workspace_id,
            resource_id=system_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await self._assert_verified_canonical_admin(
                uow=uow, workspace_id=workspace_id, subject_id=subject.subject_id
            )
            return await uow.systems.list_schema_scope_candidates(
                workspace_id=workspace_id,
                system_id=system_id,
                subject=subject,
                limit=limit,
                query=query.strip().casefold() if query and query.strip() else None,
                cursor=cursor,
            )

    async def get_profile_role_policy(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
    ) -> ProfileRolePolicyCatalog:
        if (
            not subject.active
            or subject.workspace_id != workspace_id
            or subject.job_function == "SERVICE_ACCOUNT"
            or "service-accounts" in subject.groups
        ):
            raise ForbiddenError("An active workspace membership is required.")
        return ProfileRolePolicyCatalog(
            policy_version=PROFILE_ROLE_POLICY_VERSION,
            items=tuple(
                ProfileRolePolicyItem(
                    tier=policy.tier.value,
                    label=policy.label,
                    description=policy.description,
                    allowed_actions=tuple(
                        sorted(policy.allowed_actions, key=lambda item: item.value)
                    ),
                    services=tuple(
                        ProfileRoleServicePolicy(
                            service_key=service.service_key,
                            service_label=service.label,
                            action_labels=tuple(
                                CAPABILITY_BY_ACTION[action].label
                                for action in sorted(
                                    policy.allowed_actions,
                                    key=lambda action: action.value,
                                )
                                if CAPABILITY_BY_ACTION[action].service_key == service.service_key
                            ),
                        )
                        for service in CAPABILITY_SERVICES
                        if any(
                            CAPABILITY_BY_ACTION[action].service_key == service.service_key
                            for action in policy.allowed_actions
                        )
                    ),
                    assignable_to_system=policy.assignable_to_system,
                    lifecycle_note=policy.lifecycle_note,
                )
                for policy in PROFILE_ROLE_POLICIES
            ),
        )

    async def get_workspace_membership_access(
        self,
        *,
        workspace_id: UUID,
        target_subject_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> WorkspaceMembershipAccessRecord:
        await self._authorize_read(
            workspace_id=workspace_id,
            resource_id=target_subject_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await uow.memberships.assert_eligible_human_administrators(
                workspace_id=workspace_id, subject_ids=frozenset({subject.subject_id})
            )
            membership = await uow.memberships.get_access(
                workspace_id=workspace_id, subject_id=target_subject_id
            )
            if membership is None:
                raise NotFoundError("The target workspace membership does not exist.")
            return membership

    async def update_profile_role(
        self,
        *,
        workspace_id: UUID,
        target_subject_id: UUID,
        tier: str,
        expected_membership_version: int,
        expected_binding_version: int,
        reason: str,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> ProfileRoleTransitionResult:
        if subject.subject_id == target_subject_id:
            raise ValidationError("An administrator cannot change their own profile Role.")
        try:
            parsed_tier = ProfileRoleTier(tier)
        except ValueError as error:
            raise ValidationError("The profile Role tier is invalid.") from error
        normalized_reason = reason.strip()
        if not normalized_reason or len(normalized_reason) > 4_000:
            raise ValidationError("A bounded profile Role change reason is required.")
        decision = await self._authorization.authorize(
            subject=subject,
            resource=self._resource(workspace_id, target_subject_id),
            action=Action.ADMIN_MANAGE,
            environment=environment,
            request_id=request_id,
        )
        operation = f"admin.profile-role.update:{target_subject_id}"
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await uow.lock_workspace_access(workspace_id=workspace_id)
            await uow.memberships.assert_eligible_human_administrators(
                workspace_id=workspace_id,
                subject_ids=frozenset({subject.subject_id}),
            )
            existing = await uow.idempotency.get_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
            )
            if existing is not None:
                _verify_idempotency(
                    existing.request_hash,
                    request_hash,
                    existing.result.get("actor_id"),
                    subject.subject_id,
                )
                return ProfileRoleTransitionResult(
                    subject_id=target_subject_id,
                    tier=str(existing.result["tier"]),
                    membership_version=int(existing.result["membership_version"]),
                    assignment_version=int(existing.result["assignment_version"]),
                    binding_version=(
                        int(existing.result["binding_version"])
                        if existing.result.get("binding_version") is not None
                        else None
                    ),
                )
            actor_access = await uow.memberships.get_access(
                workspace_id=workspace_id,
                subject_id=subject.subject_id,
            )
            target_access = await uow.memberships.get_access(
                workspace_id=workspace_id,
                subject_id=target_subject_id,
            )
            if actor_access is None or target_access is None:
                raise NotFoundError("The profile Role target is unavailable.")
            if target_access.summary.membership_version != expected_membership_version:
                raise ConflictError("The target membership changed before the profile update.")
            target_binding = target_access.canonical_admin_binding
            protected_transition = parsed_tier is ProfileRoleTier.ADMIN or (
                target_binding is not None and target_binding.status != "REVOKED"
            )
            next_access_hash = _profile_role_access_payload_hash(
                access=target_access,
                tier=parsed_tier,
            )
            if protected_transition:
                if (
                    subject.authentication_assurance
                    is not AuthenticationAssurance.HARDWARE_WEBAUTHN
                    or not _authentication_is_fresh(subject=subject, environment=environment)
                ):
                    raise ForbiddenError(
                        "Canonical Admin profile transitions require fresh hardware WebAuthn."
                    )
                actor_binding = actor_access.canonical_admin_binding
                if actor_binding is None or actor_binding.status != "VERIFIED":
                    raise ForbiddenError("A current separate Canonical Admin binding is required.")
                actual_binding_version = (
                    target_binding.binding_version if target_binding is not None else 0
                )
                if actual_binding_version != expected_binding_version:
                    raise ConflictError("The target Canonical Admin binding changed.")
                if (
                    parsed_tier is not ProfileRoleTier.ADMIN
                    and await uow.memberships.count_verified_canonical_admins(
                        workspace_id=workspace_id
                    )
                    <= 1
                ):
                    raise ConflictError("The last verified Canonical Admin cannot be demoted.")
                result = await uow.memberships.transition_canonical_admin_profile(
                    workspace_id=workspace_id,
                    subject_id=target_subject_id,
                    tier=parsed_tier.value,
                    expected_membership_version=expected_membership_version,
                    expected_binding_version=expected_binding_version,
                    reason=normalized_reason,
                    assurance=subject.authentication_assurance.value,
                    access_payload_hash=next_access_hash,
                    policy_decision_id=decision.decision_id,
                )
            else:
                result = await uow.memberships.apply_profile_role(
                    workspace_id=workspace_id,
                    subject_id=target_subject_id,
                    tier=parsed_tier.value,
                    expected_membership_version=expected_membership_version,
                    reason=normalized_reason,
                    assurance=subject.authentication_assurance.value,
                    access_payload_hash=next_access_hash,
                    policy_decision_id=decision.decision_id,
                )
            await uow.outbox.add_events(
                [
                    DomainEvent.create(
                        event_type="iam.workspace_membership.profile_role_changed.v1",
                        aggregate_type="workspace_membership",
                        aggregate_id=target_subject_id,
                        workspace_id=workspace_id,
                        payload={
                            "actor_id": str(subject.subject_id),
                            "tier": result.tier,
                            "membership_version": result.membership_version,
                            "assignment_version": result.assignment_version,
                            "binding_version": result.binding_version,
                            "policy_decision_id": str(decision.decision_id),
                            "reason_hash": canonical_json_hash({"reason": normalized_reason}),
                            "assurance": subject.authentication_assurance.value,
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
                    "tier": result.tier,
                    "membership_version": result.membership_version,
                    "assignment_version": result.assignment_version,
                    "binding_version": result.binding_version,
                },
            )
            await uow.commit()
            return result

    async def list_membership_change_request_activity(
        self,
        *,
        workspace_id: UUID,
        target_subject_id: UUID,
        limit: int,
        cursor: str | None,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> MembershipChangeRequestActivityPage:
        _validate_admin_page_limit(limit)
        await self._authorize_read(
            workspace_id=workspace_id,
            resource_id=target_subject_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await uow.memberships.assert_eligible_human_administrators(
                workspace_id=workspace_id,
                subject_ids=frozenset({subject.subject_id}),
            )
            page = await uow.memberships.list_change_request_activity(
                workspace_id=workspace_id,
                subject_id=target_subject_id,
                limit=limit,
                cursor=cursor,
            )
        visible = []
        for item in page.items:
            try:
                await self._authorization.authorize(
                    subject=subject,
                    resource=ResourceAttributes(
                        resource_id=item.change_request_id,
                        workspace_id=workspace_id,
                        resource_type="change_request",
                        owner_department_id=None,
                        system_id=None,
                        domain_id=None,
                        classification=item.classification,
                        lifecycle="ACTIVE",
                        owner_subject_id=item.requester_id,
                    ),
                    action=Action.CHANGE_READ,
                    environment=environment,
                    request_id=request_id,
                )
            except ForbiddenError:
                continue
            visible.append(item)
        return MembershipChangeRequestActivityPage(
            items=tuple(visible),
            next_cursor=page.next_cursor,
        )

    async def list_membership_owned_tables(
        self,
        *,
        workspace_id: UUID,
        target_subject_id: UUID,
        limit: int,
        cursor: str | None,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> MembershipOwnedTablePage:
        _validate_admin_page_limit(limit)
        await self._authorize_read(
            workspace_id=workspace_id,
            resource_id=target_subject_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await uow.memberships.assert_eligible_human_administrators(
                workspace_id=workspace_id,
                subject_ids=frozenset({subject.subject_id}),
            )
            page = await uow.memberships.list_owned_tables(
                workspace_id=workspace_id,
                subject_id=target_subject_id,
                limit=limit,
                cursor=cursor,
            )
        visible = []
        for item in page.items:
            try:
                await self._authorization.authorize(
                    subject=subject,
                    resource=ResourceAttributes(
                        resource_id=item.asset_id,
                        workspace_id=workspace_id,
                        resource_type="TABLE",
                        owner_department_id=item.owner_department_id,
                        system_id=item.system_id,
                        domain_id=item.domain_id,
                        classification=item.classification,
                        lifecycle="ACTIVE",
                        owner_subject_id=target_subject_id,
                    ),
                    action=Action.CATALOG_READ,
                    environment=environment,
                    request_id=request_id,
                )
            except ForbiddenError:
                continue
            visible.append(item)
        return MembershipOwnedTablePage(
            items=tuple(visible),
            next_cursor=page.next_cursor,
        )

    async def get_own_workspace_membership(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
    ) -> WorkspaceMembershipSummary:
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            membership = await uow.memberships.get_access(
                workspace_id=workspace_id, subject_id=subject.subject_id
            )
            if membership is None:
                raise NotFoundError("The current workspace membership does not exist.")
            return membership.summary

    async def get_admin_read_context(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> AdminReadContext:
        await self._authorize_read(
            workspace_id=workspace_id,
            resource_id=workspace_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await uow.memberships.assert_eligible_human_administrators(
                workspace_id=workspace_id, subject_ids=frozenset({subject.subject_id})
            )
            membership = await uow.memberships.get_access(
                workspace_id=workspace_id, subject_id=subject.subject_id
            )
            if membership is None:
                raise NotFoundError("The administrator workspace membership does not exist.")
        operations = [
            AdminOperation.MEMBERSHIP_ACCESS_READ,
            AdminOperation.MEMBERSHIP_RENEWAL_READ,
            AdminOperation.CLASSIFICATION_POLICY_READ,
            AdminOperation.INFERENCE_PROVIDER_PROFILE_READ,
            AdminOperation.RESTRICTED_SEARCH_GRANT_READ,
            AdminOperation.MONITORING_CONFIGURATION_READ,
        ]
        if self._development_system_configuration_enabled:
            operations.append(AdminOperation.SYSTEM_CONFIGURATION_READ)
        if self._identity_administration_enabled:
            operations.append(AdminOperation.IDENTITY_USER_PROFILE_READ)
        if (
            Action.RETENTION_READ in subject.allowed_actions
            and Action.RETENTION_READ not in subject.denied_actions
        ):
            operations.extend(
                [
                    AdminOperation.RETENTION_POLICY_READ,
                    AdminOperation.LEGAL_HOLD_READ,
                    AdminOperation.ERASURE_READ,
                ]
            )
        direct_mutation_assurance = (
            subject.authentication_assurance is AuthenticationAssurance.HARDWARE_WEBAUTHN
            or (
                self._development_admin_password_bypass_enabled
                and subject.authentication_assurance
                in {
                    AuthenticationAssurance.PASSWORD,
                    AuthenticationAssurance.PASSWORD_REAUTH,
                }
            )
        )
        if direct_mutation_assurance and _authentication_is_fresh(
            subject=subject, environment=environment
        ):
            operations.extend(
                [
                    AdminOperation.MEMBERSHIP_ACCESS_UPDATE,
                    AdminOperation.MEMBERSHIP_RENEWAL_DECIDE,
                    AdminOperation.SYSTEM_ASSIGNMENT_UPDATE,
                    AdminOperation.CLASSIFICATION_POLICY_PROPOSE,
                    AdminOperation.CLASSIFICATION_POLICY_DECIDE,
                    AdminOperation.INFERENCE_PROVIDER_PROFILE_DECIDE,
                    AdminOperation.INFERENCE_PROVIDER_PROFILE_REVOKE,
                    AdminOperation.RESTRICTED_SEARCH_GRANT_PROPOSE,
                    AdminOperation.RESTRICTED_SEARCH_GRANT_DECIDE,
                    AdminOperation.RESTRICTED_SEARCH_GRANT_REVOKE,
                    AdminOperation.MONITORING_CONFIGURATION_UPDATE,
                ]
            )
            if self._identity_administration_enabled:
                operations.extend(
                    [
                        AdminOperation.IDENTITY_USER_PROVISION,
                        AdminOperation.IDENTITY_USER_PROFILE_UPDATE,
                        AdminOperation.IDENTITY_USER_PASSWORD_RESET,
                    ]
                )
            governed_operations = (
                (Action.RETENTION_MANAGE, AdminOperation.RETENTION_POLICY_MANAGE),
                (Action.LEGAL_HOLD_PLACE, AdminOperation.LEGAL_HOLD_PLACE),
                (Action.LEGAL_HOLD_RELEASE, AdminOperation.LEGAL_HOLD_RELEASE),
                (Action.ERASURE_REQUEST, AdminOperation.ERASURE_REQUEST),
                (Action.ERASURE_APPROVE, AdminOperation.ERASURE_APPROVE),
            )
            operations.extend(
                operation
                for action, operation in governed_operations
                if action in subject.allowed_actions and action not in subject.denied_actions
            )
        if self._fallback_enabled:
            operations.extend(
                [AdminOperation.FALLBACK_REQUEST_READ, AdminOperation.FALLBACK_REQUEST_DECIDE]
            )
            if subject.authentication_assurance is AuthenticationAssurance.PASSWORD_REAUTH:
                operations.extend(
                    [
                        AdminOperation.FALLBACK_REQUEST_CREATE,
                        AdminOperation.FALLBACK_REQUEST_CONSUME,
                    ]
                )
        return AdminReadContext(
            workspace_id=workspace_id,
            membership=membership.summary,
            authentication_assurance=subject.authentication_assurance,
            allowed_operations=tuple(operations),
            action_vocabulary=tuple(sorted(Action, key=lambda action: action.value)),
            fallback_enabled=self._fallback_enabled,
        )

    async def authorize_access_role_mutation(
        self,
        *,
        workspace_id: UUID,
        role_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> UUID:
        """Require a fresh high-risk decision and current human-admin membership."""

        decision = await self._authorization.authorize(
            subject=subject,
            resource=self._resource(workspace_id, role_id),
            action=Action.ADMIN_MANAGE,
            environment=environment,
            request_id=request_id,
        )
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await uow.memberships.assert_eligible_human_administrators(
                workspace_id=workspace_id,
                subject_ids=frozenset({subject.subject_id}),
            )
        return decision.decision_id

    async def request_membership_renewal(
        self,
        *,
        workspace_id: UUID,
        reason: str,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        idempotency_key: str,
        request_hash: str,
    ) -> MembershipRenewalRecord:
        operation = f"membership.renewal.request:{subject.subject_id}"
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await uow.lock_workspace_access(workspace_id=workspace_id)
            existing = await uow.idempotency.get_result(
                workspace_id=workspace_id, key=idempotency_key, operation=operation
            )
            if existing is not None:
                _verify_idempotency(
                    existing.request_hash,
                    request_hash,
                    existing.result.get("actor_id"),
                    subject.subject_id,
                )
                renewal_id = UUID(str(existing.result["renewal_request_id"]))
                record = await uow.renewals.get_record(
                    workspace_id=workspace_id,
                    renewal_request_id=renewal_id,
                )
                if record is not None and record.target_subject_id == subject.subject_id:
                    return record
                raise ConflictError("The idempotent membership renewal result is unavailable.")
            current_expires_at = await uow.memberships.get_expiration_for_update(
                workspace_id=workspace_id, subject_id=subject.subject_id
            )
            renewal = MembershipRenewalRequest.create(
                workspace_id=workspace_id,
                subject_id=subject.subject_id,
                reason=reason,
                current_expires_at=current_expires_at,
                requested_at=environment.requested_at,
            )
            await uow.renewals.add(renewal)
            await uow.outbox.add_events(renewal.events)
            await uow.idempotency.save_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                result={
                    "actor_id": str(subject.subject_id),
                    "renewal_request_id": str(renewal.renewal_request_id),
                },
            )
            await uow.commit()
        renewal.events.clear()
        record = await self._get_membership_renewal_record(
            workspace_id=workspace_id,
            renewal_request_id=renewal.renewal_request_id,
            actor_id=subject.subject_id,
        )
        if record is None:
            raise ConflictError("The created membership renewal result is unavailable.")
        return record

    async def list_membership_renewals(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID | None,
        state: MembershipRenewalState | None,
        limit: int,
        cursor: str | None = None,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        administrator: bool,
    ) -> MembershipRenewalPage:
        _validate_admin_page_limit(limit)
        target_subject_id = subject_id
        if administrator:
            await self._authorize_read(
                workspace_id=workspace_id,
                resource_id=workspace_id,
                subject=subject,
                environment=environment,
                request_id=request_id,
            )
        else:
            if subject_id not in {None, subject.subject_id}:
                raise ForbiddenError("A member can read only their own renewal requests.")
            target_subject_id = subject.subject_id
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            if administrator:
                await uow.memberships.assert_eligible_human_administrators(
                    workspace_id=workspace_id, subject_ids=frozenset({subject.subject_id})
                )
            return await uow.renewals.list_records(
                workspace_id=workspace_id,
                subject_id=target_subject_id,
                state=state.value if state is not None else None,
                limit=limit,
                cursor=cursor,
            )

    async def _get_membership_renewal_record(
        self,
        *,
        workspace_id: UUID,
        renewal_request_id: UUID,
        actor_id: UUID,
    ) -> MembershipRenewalRecord | None:
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=actor_id)
            return await uow.renewals.get_record(
                workspace_id=workspace_id,
                renewal_request_id=renewal_request_id,
            )

    async def decide_membership_renewal(
        self,
        *,
        workspace_id: UUID,
        renewal_request_id: UUID,
        decision_value: MembershipRenewalDecision,
        reason: str,
        expected_version: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> tuple[MembershipRenewalRecord, int | None]:
        decision = await self._authorization.authorize(
            subject=subject,
            resource=self._resource(workspace_id, renewal_request_id),
            action=Action.ADMIN_MANAGE,
            environment=environment,
            request_id=request_id,
        )
        operation = f"membership.renewal.decide:{renewal_request_id}"
        membership_version: int | None = None
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await uow.lock_workspace_access(workspace_id=workspace_id)
            await uow.memberships.assert_eligible_human_administrators(
                workspace_id=workspace_id, subject_ids=frozenset({subject.subject_id})
            )
            renewal = await uow.renewals.get_for_update(
                workspace_id=workspace_id, renewal_request_id=renewal_request_id
            )
            if renewal is None:
                raise NotFoundError("The membership renewal request does not exist.")
            existing = await uow.idempotency.get_result(
                workspace_id=workspace_id, key=idempotency_key, operation=operation
            )
            if existing is not None:
                _verify_idempotency(
                    existing.request_hash,
                    request_hash,
                    existing.result.get("actor_id"),
                    subject.subject_id,
                )
                record = await uow.renewals.get_record(
                    workspace_id=workspace_id,
                    renewal_request_id=renewal_request_id,
                )
                if record is not None:
                    stored_version = existing.result.get("membership_version")
                    return record, int(stored_version) if stored_version is not None else None
                raise ConflictError("The idempotent membership renewal result is unavailable.")
            current_expires_at = await uow.memberships.get_expiration_for_update(
                workspace_id=workspace_id, subject_id=renewal.target_subject_id
            )
            renewal.decide(
                decision=decision_value,
                checker_id=subject.subject_id,
                reason=reason,
                policy_decision_id=decision.decision_id,
                decided_at=environment.requested_at,
                expected_version=expected_version,
                observed_membership_expires_at=current_expires_at,
            )
            if decision_value is MembershipRenewalDecision.APPROVED:
                membership_version = await uow.memberships.extend_expiration(
                    workspace_id=workspace_id,
                    subject_id=renewal.target_subject_id,
                    expected=current_expires_at,
                    extended=renewal.requested_expires_at,
                )
            await uow.renewals.save(renewal)
            await uow.outbox.add_events(renewal.events)
            await uow.idempotency.save_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                result={
                    "actor_id": str(subject.subject_id),
                    "renewal_request_id": str(renewal_request_id),
                    "membership_version": membership_version,
                },
            )
            await uow.commit()
        renewal.events.clear()
        record = await self._get_membership_renewal_record(
            workspace_id=workspace_id,
            renewal_request_id=renewal_request_id,
            actor_id=subject.subject_id,
        )
        if record is None:
            raise ConflictError("The decided membership renewal result is unavailable.")
        return (
            record,
            membership_version,
        )

    async def update_membership_with_hardware_key(
        self,
        *,
        command: MembershipAccessUpdate,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
        role_id: UUID | None = None,
        role_version: int | None = None,
        role_transition: bool = False,
    ) -> int:
        if not role_transition and (role_id is not None or role_version is not None):
            raise ValidationError("Role evidence requires the dedicated Role assignment route.")
        if role_transition and role_id is None and role_version is not None:
            raise ValidationError("A Role removal cannot include a Role version.")
        if role_transition and role_id is not None and role_version is None:
            raise ValidationError("A Role assignment requires an exact Role version.")
        role_marker = _assert_role_marker_binding(command=command, role_id=role_id)
        if subject.subject_id == command.target_subject_id:
            raise ValidationError("An administrator cannot change their own access.")
        decision = await self._authorization.authorize(
            subject=subject,
            resource=self._resource(command.workspace_id, command.target_subject_id),
            action=Action.ADMIN_MANAGE,
            environment=environment,
            request_id=request_id,
        )
        operation = f"admin.membership.update:{command.target_subject_id}"
        async with self._uow_factory() as uow:
            await uow.set_security_context(
                workspace_id=command.workspace_id, subject_id=subject.subject_id
            )
            await uow.lock_workspace_access(workspace_id=command.workspace_id)
            await uow.memberships.assert_eligible_human_administrators(
                workspace_id=command.workspace_id,
                subject_ids=frozenset({subject.subject_id}),
            )
            existing = await uow.idempotency.get_result(
                workspace_id=command.workspace_id,
                key=idempotency_key,
                operation=operation,
            )
            if existing is not None:
                _verify_idempotency(
                    existing.request_hash,
                    request_hash,
                    existing.result.get("actor_id"),
                    subject.subject_id,
                )
                return int(existing.result["membership_version"])
            if role_transition:
                await uow.memberships.assert_current_version(command)
                if role_id is not None:
                    current_access = await uow.memberships.get_access(
                        workspace_id=command.workspace_id,
                        subject_id=command.target_subject_id,
                    )
                    if current_access is None:
                        raise NotFoundError("The target workspace membership does not exist.")
                    if (
                        current_access.profile_role is not None
                        and current_access.profile_role.status != "REVOKED"
                    ):
                        raise ConflictError(
                            "A custom Role cannot be assigned while a profile Role is active."
                        )
            else:
                await uow.memberships.assert_manual_access_update_allowed(
                    workspace_id=command.workspace_id,
                    subject_id=command.target_subject_id,
                )
                await uow.memberships.assert_current_version(command)
            membership_version = await uow.memberships.apply(command)
            if role_transition:
                await uow.memberships.record_role_assignment(
                    workspace_id=command.workspace_id,
                    subject_id=command.target_subject_id,
                    role_id=role_id,
                    role_version=role_version,
                    role_marker=role_marker,
                    membership_version=membership_version,
                    access_payload_hash=canonical_json_hash(command.access_document()),
                    actor_id=subject.subject_id,
                )
            await uow.outbox.add_events(
                [
                    DomainEvent.create(
                        event_type="iam.workspace_membership.access_updated.v1",
                        aggregate_type="workspace_membership",
                        aggregate_id=command.target_subject_id,
                        workspace_id=command.workspace_id,
                        payload={
                            "actor_id": str(subject.subject_id),
                            "payload_hash": command.payload_hash,
                            "membership_version": membership_version,
                            "policy_decision_id": str(decision.decision_id),
                            "assurance": subject.authentication_assurance.value,
                        },
                    )
                ]
            )
            await uow.idempotency.save_result(
                workspace_id=command.workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                result={
                    "actor_id": str(subject.subject_id),
                    "membership_version": membership_version,
                },
            )
            await uow.commit()
            return membership_version

    async def update_system_assignees_with_hardware_key(
        self,
        *,
        command: SystemAssigneeUpdateCommand,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> int:
        decision = await self._authorization.authorize(
            subject=subject,
            resource=self._resource(command.workspace_id, command.system_id),
            action=Action.ADMIN_MANAGE,
            environment=environment,
            request_id=request_id,
        )
        operation = f"admin.system.assignees.update:{command.system_id}"
        async with self._uow_factory() as uow:
            await uow.set_security_context(
                workspace_id=command.workspace_id, subject_id=subject.subject_id
            )
            await uow.lock_workspace_access(workspace_id=command.workspace_id)
            await uow.memberships.assert_eligible_human_administrators(
                workspace_id=command.workspace_id,
                subject_ids=frozenset({subject.subject_id}),
            )
            existing = await uow.idempotency.get_result(
                workspace_id=command.workspace_id,
                key=idempotency_key,
                operation=operation,
            )
            if existing is not None:
                _verify_idempotency(
                    existing.request_hash,
                    request_hash,
                    existing.result.get("actor_id"),
                    subject.subject_id,
                )
                return int(existing.result["system_version"])
            system_version = await uow.systems.replace_assignees(command)
            await uow.outbox.add_events(
                [
                    DomainEvent.create(
                        event_type="platform.data_system.assignees_updated.v1",
                        aggregate_type="data_system",
                        aggregate_id=command.system_id,
                        workspace_id=command.workspace_id,
                        payload={
                            "actor_id": str(subject.subject_id),
                            "payload_hash": command.payload_hash,
                            "system_version": system_version,
                            "policy_decision_id": str(decision.decision_id),
                            "assurance": subject.authentication_assurance.value,
                        },
                    )
                ]
            )
            await uow.idempotency.save_result(
                workspace_id=command.workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                result={
                    "actor_id": str(subject.subject_id),
                    "system_version": system_version,
                },
            )
            await uow.commit()
            return system_version

    async def patch_system_assignees_with_hardware_key(
        self,
        *,
        command: SystemAssigneePatchCommand,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> int:
        decision = await self._authorization.authorize(
            subject=subject,
            resource=self._resource(command.workspace_id, command.system_id),
            action=Action.ADMIN_MANAGE,
            environment=environment,
            request_id=request_id,
        )
        operation = f"admin.system.assignees.patch:{command.system_id}"
        async with self._uow_factory() as uow:
            await uow.set_security_context(
                workspace_id=command.workspace_id, subject_id=subject.subject_id
            )
            await uow.lock_workspace_access(workspace_id=command.workspace_id)
            await uow.memberships.assert_eligible_human_administrators(
                workspace_id=command.workspace_id,
                subject_ids=frozenset({subject.subject_id}),
            )
            existing = await uow.idempotency.get_result(
                workspace_id=command.workspace_id,
                key=idempotency_key,
                operation=operation,
            )
            if existing is not None:
                _verify_idempotency(
                    existing.request_hash,
                    request_hash,
                    existing.result.get("actor_id"),
                    subject.subject_id,
                )
                return int(existing.result["system_version"])
            system_version = await uow.systems.patch_assignees(command)
            await uow.outbox.add_events(
                [
                    DomainEvent.create(
                        event_type="platform.data_system.assignees_patched.v1",
                        aggregate_type="data_system",
                        aggregate_id=command.system_id,
                        workspace_id=command.workspace_id,
                        payload={
                            "actor_id": str(subject.subject_id),
                            "payload_hash": command.payload_hash,
                            "system_version": system_version,
                            "policy_decision_id": str(decision.decision_id),
                            "assurance": subject.authentication_assurance.value,
                        },
                    )
                ]
            )
            await uow.idempotency.save_result(
                workspace_id=command.workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                result={
                    "actor_id": str(subject.subject_id),
                    "system_version": system_version,
                },
            )
            await uow.commit()
            return system_version

    async def patch_system_schema_scopes(
        self,
        *,
        command: SystemSchemaScopePatchCommand,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> int:
        decision = await self._authorization.authorize(
            subject=subject,
            resource=self._resource(command.workspace_id, command.system_id),
            action=Action.ADMIN_MANAGE,
            environment=environment,
            request_id=request_id,
        )
        operation = f"admin.system.schema-scopes.patch:{command.system_id}"
        async with self._uow_factory() as uow:
            await uow.set_security_context(
                workspace_id=command.workspace_id, subject_id=subject.subject_id
            )
            await uow.lock_workspace_access(workspace_id=command.workspace_id)
            await self._assert_verified_canonical_admin(
                uow=uow,
                workspace_id=command.workspace_id,
                subject_id=subject.subject_id,
            )
            existing = await uow.idempotency.get_result(
                workspace_id=command.workspace_id,
                key=idempotency_key,
                operation=operation,
            )
            if existing is not None:
                _verify_idempotency(
                    existing.request_hash,
                    request_hash,
                    existing.result.get("actor_id"),
                    subject.subject_id,
                )
                return int(existing.result["system_version"])
            system_version = await uow.systems.patch_schema_scopes(command, subject=subject)
            await uow.outbox.add_events(
                [
                    DomainEvent.create(
                        event_type="platform.data_system.schema_scopes_patched.v1",
                        aggregate_type="data_system",
                        aggregate_id=command.system_id,
                        workspace_id=command.workspace_id,
                        payload={
                            "actor_id": str(subject.subject_id),
                            "assurance": subject.authentication_assurance.value,
                            "deactivated_count": len(command.deactivate_scope_ids),
                            "payload_hash": command.payload_hash,
                            "policy_decision_id": str(decision.decision_id),
                            "reason": command.reason.strip(),
                            "system_version": system_version,
                            "upserted_count": len(command.upsert_asset_ids),
                        },
                    )
                ]
            )
            await uow.idempotency.save_result(
                workspace_id=command.workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                result={
                    "actor_id": str(subject.subject_id),
                    "system_version": system_version,
                },
            )
            await uow.commit()
            return system_version

    async def create_fallback_request(
        self,
        *,
        command: MembershipAccessUpdate,
        reason: str,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> AdminAccessRequest:
        self._require_fallback_enabled()
        _assert_role_marker_binding(command=command, role_id=None)
        decision = await self._authorization.authorize_admin_fallback(
            subject=subject,
            resource=self._resource(command.workspace_id, command.target_subject_id),
            stage=AdminFallbackStage.REQUEST,
            environment=environment,
            request_id=request_id,
        )
        request = AdminAccessRequest.create(
            requester_id=subject.subject_id,
            reason=reason,
            policy_decision_id=decision.decision_id,
            command=command,
            now=environment.requested_at,
            expires_at=environment.requested_at + self._fallback_ttl,
        )
        operation = "admin.fallback.request"
        async with self._uow_factory() as uow:
            await uow.set_security_context(
                workspace_id=command.workspace_id, subject_id=subject.subject_id
            )
            await uow.lock_workspace_access(workspace_id=command.workspace_id)
            await uow.memberships.assert_eligible_human_administrators(
                workspace_id=command.workspace_id,
                subject_ids=frozenset({subject.subject_id}),
            )
            existing = await uow.idempotency.get_result(
                workspace_id=command.workspace_id,
                key=idempotency_key,
                operation=operation,
            )
            if existing is not None:
                _verify_idempotency(
                    existing.request_hash,
                    request_hash,
                    existing.result.get("actor_id"),
                    subject.subject_id,
                )
                stored = await uow.requests.get_for_update(
                    workspace_id=command.workspace_id,
                    access_request_id=UUID(str(existing.result["access_request_id"])),
                )
                if stored is None:
                    raise ConflictError("The idempotent fallback request is unavailable.")
                return stored
            await uow.memberships.assert_manual_access_update_allowed(
                workspace_id=command.workspace_id,
                subject_id=command.target_subject_id,
            )
            await uow.memberships.assert_current_version(command)
            await uow.requests.add(request)
            await uow.outbox.add_events(request.events)
            await uow.idempotency.save_result(
                workspace_id=command.workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                result={
                    "actor_id": str(subject.subject_id),
                    "access_request_id": str(request.access_request_id),
                },
            )
            await uow.commit()
        request.events.clear()
        return request

    async def list_fallback_requests(
        self,
        *,
        workspace_id: UUID,
        state: AdminAccessRequestState | None,
        limit: int,
        cursor: str | None = None,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> AdminAccessRequestPage:
        _validate_admin_page_limit(limit)
        self._require_fallback_enabled()
        await self._authorization.authorize_admin_fallback(
            subject=subject,
            resource=self._resource(workspace_id, workspace_id),
            stage=AdminFallbackStage.READ,
            environment=environment,
            request_id=request_id,
        )
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await uow.memberships.assert_eligible_human_administrators(
                workspace_id=workspace_id, subject_ids=frozenset({subject.subject_id})
            )
            return await uow.requests.list(
                workspace_id=workspace_id,
                state=state.value if state is not None else None,
                limit=limit,
                cursor=cursor,
            )

    async def decide_fallback_request(
        self,
        *,
        workspace_id: UUID,
        access_request_id: UUID,
        approval_decision: AdminAccessDecision,
        reason: str,
        expected_version: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> AdminAccessRequest:
        self._require_fallback_enabled()
        decision = await self._authorization.authorize_admin_fallback(
            subject=subject,
            resource=self._resource(workspace_id, access_request_id),
            stage=AdminFallbackStage.APPROVE,
            environment=environment,
            request_id=request_id,
        )
        operation = f"admin.fallback.decide:{access_request_id}"
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await uow.lock_workspace_access(workspace_id=workspace_id)
            request = await uow.requests.get_for_update(
                workspace_id=workspace_id, access_request_id=access_request_id
            )
            if request is None:
                raise NotFoundError("The administrator fallback request does not exist.")
            existing = await uow.idempotency.get_result(
                workspace_id=workspace_id, key=idempotency_key, operation=operation
            )
            if existing is not None:
                _verify_idempotency(
                    existing.request_hash,
                    request_hash,
                    existing.result.get("actor_id"),
                    subject.subject_id,
                )
                return request
            await uow.memberships.assert_eligible_human_administrators(
                workspace_id=workspace_id,
                subject_ids=frozenset({subject.subject_id, request.requester_id}),
            )
            await uow.memberships.assert_current_version(request.command)
            request.decide(
                decision=approval_decision,
                actor_id=subject.subject_id,
                reason=reason,
                policy_decision_id=decision.decision_id,
                expected_version=expected_version,
                now=environment.requested_at,
            )
            await uow.requests.save(request)
            await uow.outbox.add_events(request.events)
            await uow.idempotency.save_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                result={
                    "actor_id": str(subject.subject_id),
                    "access_request_id": str(access_request_id),
                    "state": request.state.value,
                    "version": request.version,
                },
            )
            await uow.commit()
        request.events.clear()
        return request

    async def consume_fallback_request(
        self,
        *,
        workspace_id: UUID,
        access_request_id: UUID,
        confirmed_payload_hash: str,
        expected_version: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> tuple[AdminAccessRequest, int]:
        self._require_fallback_enabled()
        decision = await self._authorization.authorize_admin_fallback(
            subject=subject,
            resource=self._resource(workspace_id, access_request_id),
            stage=AdminFallbackStage.CONSUME,
            environment=environment,
            request_id=request_id,
        )
        operation = f"admin.fallback.consume:{access_request_id}"
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await uow.lock_workspace_access(workspace_id=workspace_id)
            request = await uow.requests.get_for_update(
                workspace_id=workspace_id, access_request_id=access_request_id
            )
            if request is None:
                raise NotFoundError("The administrator fallback request does not exist.")
            existing = await uow.idempotency.get_result(
                workspace_id=workspace_id, key=idempotency_key, operation=operation
            )
            if existing is not None:
                _verify_idempotency(
                    existing.request_hash,
                    request_hash,
                    existing.result.get("actor_id"),
                    subject.subject_id,
                )
                return request, int(existing.result["membership_version"])
            if confirmed_payload_hash != request.payload_hash:
                raise ConflictError("The confirmed payload hash does not match the approval.")
            if request.checker_id is None:
                raise ConflictError("The fallback request has no independent checker.")
            _assert_role_marker_binding(command=request.command, role_id=None)
            await uow.memberships.assert_eligible_human_administrators(
                workspace_id=workspace_id,
                subject_ids=frozenset({subject.subject_id, request.checker_id}),
            )
            await uow.memberships.assert_manual_access_update_allowed(
                workspace_id=request.command.workspace_id,
                subject_id=request.command.target_subject_id,
            )
            membership_version = await uow.memberships.apply(request.command)
            request.consume(
                actor_id=subject.subject_id,
                policy_decision_id=decision.decision_id,
                expected_version=expected_version,
                now=environment.requested_at,
            )
            await uow.requests.save(request)
            await uow.outbox.add_events(
                [
                    *request.events,
                    DomainEvent.create(
                        event_type="iam.workspace_membership.access_updated.v1",
                        aggregate_type="workspace_membership",
                        aggregate_id=request.command.target_subject_id,
                        workspace_id=workspace_id,
                        payload={
                            "actor_id": str(subject.subject_id),
                            "access_request_id": str(access_request_id),
                            "payload_hash": request.payload_hash,
                            "membership_version": membership_version,
                            "policy_decision_id": str(decision.decision_id),
                            "assurance": "PASSWORD_REAUTH_MAKER_CHECKER",
                        },
                    ),
                ]
            )
            await uow.idempotency.save_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                result={
                    "actor_id": str(subject.subject_id),
                    "access_request_id": str(access_request_id),
                    "membership_version": membership_version,
                    "version": request.version,
                },
            )
            await uow.commit()
        request.events.clear()
        return request, membership_version

    def _require_fallback_enabled(self) -> None:
        if not self._fallback_enabled:
            raise ForbiddenError(
                "The administrator password fallback is disabled.",
                details={"remediation": {"kind": "FALLBACK_UNAVAILABLE"}},
            )

    @staticmethod
    async def _assert_verified_canonical_admin(
        *,
        uow: AdminAccessUnitOfWork,
        workspace_id: UUID,
        subject_id: UUID,
    ) -> None:
        await uow.memberships.assert_eligible_human_administrators(
            workspace_id=workspace_id,
            subject_ids=frozenset({subject_id}),
        )
        access = await uow.memberships.get_access(
            workspace_id=workspace_id,
            subject_id=subject_id,
        )
        if (
            access is None
            or access.canonical_admin_binding is None
            or access.canonical_admin_binding.status != "VERIFIED"
        ):
            raise ForbiddenError("A current Canonical Admin binding is required.")

    async def _authorize_read(
        self,
        *,
        workspace_id: UUID,
        resource_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> None:
        await self._authorization.authorize_admin_fallback(
            subject=subject,
            resource=self._resource(workspace_id, resource_id),
            stage=AdminFallbackStage.READ,
            environment=environment,
            request_id=request_id,
        )

    @staticmethod
    def _resource(workspace_id: UUID, resource_id: UUID) -> ResourceAttributes:
        return ResourceAttributes(
            resource_id=resource_id,
            workspace_id=workspace_id,
            resource_type="workspace_membership_access",
            owner_department_id=None,
            system_id=None,
            domain_id=None,
            classification=Classification.RESTRICTED,
            lifecycle="ACTIVE",
            owner_subject_id=resource_id,
        )


def _verify_idempotency(
    stored_hash: str,
    request_hash: str,
    stored_actor: object,
    actor_id: UUID,
) -> None:
    if stored_hash != request_hash:
        raise ConflictError("The idempotency key was used with a different request.")
    if stored_actor != str(actor_id):
        raise ConflictError("The idempotency key belongs to another subject.")


def _validate_admin_page_limit(limit: int) -> None:
    if limit < 1 or limit > 100:
        raise ValidationError("An administrator list page must contain between 1 and 100 items.")


def _profile_role_access_payload_hash(
    *,
    access: WorkspaceMembershipAccessRecord,
    tier: ProfileRoleTier,
) -> str:
    policy = PROFILE_ROLE_BY_TIER[tier]
    groups = {
        group
        for group in access.groups
        if group != "security-administrators" and not group.startswith("datariver-role-")
    }
    if tier is ProfileRoleTier.ADMIN:
        groups.add("security-administrators")
    clearance = (
        Classification.RESTRICTED
        if tier is ProfileRoleTier.ADMIN
        else max(access.summary.clearance, Classification.CONFIDENTIAL)
    )
    return canonical_json_hash(
        {
            "active": access.summary.membership_active,
            "clearance": clearance.name,
            "groups": sorted(groups),
            "allowed_actions": sorted(action.value for action in policy.allowed_actions),
            "denied_actions": sorted(action.value for action in access.denied_actions),
            "allowed_system_ids": [],
            "allowed_domain_ids": sorted(str(value) for value in access.allowed_domain_ids),
        }
    )


def _assert_role_marker_binding(
    *, command: MembershipAccessUpdate, role_id: UUID | None
) -> str | None:
    markers = tuple(group for group in command.groups if group.startswith("datariver-role-"))
    if role_id is None and markers:
        raise ValidationError(
            "Manual membership access cannot contain a reserved role marker; use Role assignment."
        )
    if role_id is not None and len(markers) != 1:
        raise ValidationError("A Role assignment requires exactly one server-managed role marker.")
    return markers[0] if markers else None


def _authentication_is_fresh(
    *, subject: SubjectAttributes, environment: EnvironmentAttributes
) -> bool:
    authenticated_at = subject.authentication_time
    if authenticated_at is None:
        return False
    if authenticated_at > environment.requested_at + environment.maximum_clock_skew:
        return False
    return environment.requested_at - authenticated_at <= environment.maximum_authentication_age
