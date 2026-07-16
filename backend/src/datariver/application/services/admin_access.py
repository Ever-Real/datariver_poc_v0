from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import timedelta
from uuid import UUID

from datariver.application.dto import (
    AdminReadContext,
    WorkspaceMembershipAccessRecord,
    WorkspaceMembershipSummary,
)
from datariver.application.ports import AdminAccessUnitOfWork
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.admin_access import (
    AdminAccessDecision,
    AdminAccessRequest,
    AdminAccessRequestState,
    AdminFallbackStage,
    AdminOperation,
    MembershipAccessUpdate,
)
from datariver.domain.authz import (
    Action,
    AuthenticationAssurance,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import (
    ConflictError,
    DomainEvent,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)


class AdminAccessService:
    def __init__(
        self,
        uow_factory: Callable[[], AdminAccessUnitOfWork],
        authorization: AuthorizationService,
        *,
        fallback_enabled: bool,
        fallback_ttl_seconds: int,
    ) -> None:
        self._uow_factory = uow_factory
        self._authorization = authorization
        self._fallback_enabled = fallback_enabled
        self._fallback_ttl = timedelta(seconds=fallback_ttl_seconds)

    async def list_workspace_memberships(
        self,
        *,
        workspace_id: UUID,
        limit: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> Sequence[WorkspaceMembershipSummary]:
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
            return await uow.memberships.list(workspace_id=workspace_id, limit=limit)

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
            AdminOperation.CLASSIFICATION_POLICY_READ,
            AdminOperation.INFERENCE_PROVIDER_PROFILE_READ,
            AdminOperation.RESTRICTED_SEARCH_GRANT_READ,
        ]
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
        if subject.authentication_assurance is AuthenticationAssurance.HARDWARE_WEBAUTHN:
            operations.extend(
                [
                    AdminOperation.MEMBERSHIP_ACCESS_UPDATE,
                    AdminOperation.CLASSIFICATION_POLICY_PROPOSE,
                    AdminOperation.CLASSIFICATION_POLICY_DECIDE,
                    AdminOperation.INFERENCE_PROVIDER_PROFILE_DECIDE,
                    AdminOperation.INFERENCE_PROVIDER_PROFILE_REVOKE,
                    AdminOperation.RESTRICTED_SEARCH_GRANT_PROPOSE,
                    AdminOperation.RESTRICTED_SEARCH_GRANT_DECIDE,
                    AdminOperation.RESTRICTED_SEARCH_GRANT_REVOKE,
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

    async def update_membership_with_hardware_key(
        self,
        *,
        command: MembershipAccessUpdate,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> int:
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
            await uow.memberships.assert_current_version(command)
            membership_version = await uow.memberships.apply(command)
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
                            "assurance": "HARDWARE_WEBAUTHN",
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
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> Sequence[AdminAccessRequest]:
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
            await uow.memberships.assert_eligible_human_administrators(
                workspace_id=workspace_id,
                subject_ids=frozenset({subject.subject_id, request.checker_id}),
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
