from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date
from typing import Protocol
from uuid import UUID

from datariver.application.ports import GovernanceUnitOfWork
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ConflictError, ForbiddenError, NotFoundError, ValidationError
from datariver.domain.governance import (
    ApprovalDecision,
    ChangeItem,
    ChangePriority,
    ChangeRequest,
    ChangeState,
    ChangeUrgency,
)


class ChangeTargetAuthorizer(Protocol):
    async def authorize_targets(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        items: Sequence[ChangeItem],
        request_classification: Classification,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[ChangeItem, ...]: ...

    async def filter_authorized_change_requests(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        change_requests: Sequence[ChangeRequest],
        action: Action,
        environment: EnvironmentAttributes,
        request_id: str,
        strict_binding: bool,
    ) -> tuple[ChangeRequest, ...]: ...


class ChangeRequestNotFound(NotFoundError):
    code = "change_request_not_found"


class GovernanceService:
    def __init__(
        self,
        uow_factory: Callable[[], GovernanceUnitOfWork],
        authorization: AuthorizationService,
        *,
        target_authorizer: ChangeTargetAuthorizer | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._authorization = authorization
        self._target_authorizer = target_authorizer

    @staticmethod
    def _resource(change_request: ChangeRequest) -> ResourceAttributes:
        item = change_request.items[0] if len(change_request.items) == 1 else None
        target_classification = (
            item.target_classification
            if item is not None and item.target_classification is not None
            else change_request.classification
        )
        return ResourceAttributes(
            resource_id=change_request.change_request_id,
            workspace_id=change_request.workspace_id,
            resource_type="change_request",
            owner_department_id=item.target_owner_department_id if item is not None else None,
            system_id=item.target_system_id if item is not None else None,
            domain_id=item.target_domain_id if item is not None else None,
            classification=max(change_request.classification, target_classification),
            lifecycle=change_request.state.value,
            requester_id=change_request.requester_id,
        )

    async def _authorize_current_targets(
        self,
        *,
        change_requests: Sequence[ChangeRequest],
        workspace_id: UUID,
        subject: SubjectAttributes,
        action: Action,
        environment: EnvironmentAttributes,
        request_id: str,
        strict_binding: bool,
    ) -> tuple[ChangeRequest, ...]:
        if self._target_authorizer is None:
            raise RuntimeError("Change-request access requires a target authorizer.")
        return await self._target_authorizer.filter_authorized_change_requests(
            workspace_id=workspace_id,
            subject=subject,
            change_requests=change_requests,
            action=action,
            environment=environment,
            request_id=request_id,
            strict_binding=strict_binding,
        )

    async def get_change_request(
        self,
        *,
        workspace_id: UUID,
        change_request_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> ChangeRequest:
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            change_request = await uow.change_requests.get(
                workspace_id=workspace_id, change_request_id=change_request_id
            )
            if change_request is None:
                raise ChangeRequestNotFound("The change request does not exist.")
            try:
                await self._authorization.authorize(
                    subject=subject,
                    resource=self._resource(change_request),
                    action=Action.CHANGE_READ,
                    environment=environment,
                    request_id=request_id,
                )
                authorized = await self._authorize_current_targets(
                    change_requests=(change_request,),
                    workspace_id=workspace_id,
                    subject=subject,
                    action=Action.CHANGE_READ,
                    environment=environment,
                    request_id=request_id,
                    strict_binding=False,
                )
                if not authorized:
                    raise ForbiddenError("The change target is not available.")
            except ForbiddenError as error:
                raise ChangeRequestNotFound("The change request does not exist.") from error
            await uow.commit()
            return change_request

    async def list_change_requests(
        self,
        *,
        workspace_id: UUID,
        state: ChangeState | None,
        limit: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[ChangeRequest, ...]:
        await self._authorization.authorize(
            subject=subject,
            resource=ResourceAttributes(
                resource_id=workspace_id,
                workspace_id=workspace_id,
                resource_type="change_request_collection",
                owner_department_id=None,
                system_id=None,
                domain_id=None,
                classification=Classification.PUBLIC,
                lifecycle="ACTIVE",
            ),
            action=Action.CHANGE_READ,
            environment=environment,
            request_id=request_id,
        )
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            values = await uow.change_requests.list(
                workspace_id=workspace_id,
                maximum_classification=int(subject.clearance),
                state=state.value if state else None,
                limit=limit,
            )
            await uow.commit()
        return await self._authorize_current_targets(
            change_requests=values,
            workspace_id=workspace_id,
            subject=subject,
            action=Action.CHANGE_READ,
            environment=environment,
            request_id=request_id,
            strict_binding=False,
        )

    async def create_change_request(
        self,
        *,
        workspace_id: UUID,
        number: str,
        request_type: str,
        title: str,
        description: str,
        requester_id: UUID,
        items: list[ChangeItem],
        subject: SubjectAttributes,
        classification: Classification,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
        require_raw_operator_gate: bool = True,
        requested_due_date: date | None = None,
        priority: ChangePriority | None = None,
        urgency: ChangeUrgency | None = None,
    ) -> ChangeRequest:
        if self._target_authorizer is None:
            raise RuntimeError("Change-request creation requires a target authorizer.")
        if require_raw_operator_gate:
            await self._authorization.authorize(
                subject=subject,
                resource=ResourceAttributes(
                    resource_id=workspace_id,
                    workspace_id=workspace_id,
                    resource_type="raw_provider_change_entrypoint",
                    owner_department_id=subject.department_id,
                    system_id=None,
                    domain_id=None,
                    classification=classification,
                    lifecycle="ACTIVE",
                    requester_id=requester_id,
                ),
                action=Action.CHANGE_RAW_CREATE,
                environment=environment,
                request_id=request_id,
            )
        bound_items = await self._target_authorizer.authorize_targets(
            workspace_id=workspace_id,
            subject=subject,
            items=items,
            request_classification=classification,
            environment=environment,
            request_id=request_id,
        )
        await self._authorization.authorize(
            subject=subject,
            resource=ResourceAttributes(
                resource_id=workspace_id,
                workspace_id=workspace_id,
                resource_type="change_request_collection",
                owner_department_id=subject.department_id,
                system_id=None,
                domain_id=None,
                classification=classification,
                lifecycle="ACTIVE",
                requester_id=requester_id,
            ),
            action=Action.CHANGE_CREATE,
            environment=environment,
            request_id=request_id,
        )
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            existing = await uow.idempotency.get_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation="change_request.create",
            )
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise ConflictError("The idempotency key was used with a different request.")
                if existing.result.get("requester_id") != str(subject.subject_id):
                    raise ConflictError("The idempotency key belongs to another subject.")
                existing_request = await uow.change_requests.get_for_update(
                    workspace_id=workspace_id,
                    change_request_id=UUID(existing.result["change_request_id"]),
                )
                if existing_request is None:
                    raise ConflictError("The idempotent result is no longer available.")
                if not await self._authorize_current_targets(
                    change_requests=(existing_request,),
                    workspace_id=workspace_id,
                    subject=subject,
                    action=Action.CHANGE_CREATE,
                    environment=environment,
                    request_id=request_id,
                    strict_binding=True,
                ):
                    raise ForbiddenError("The change target is not available.")
                return existing_request
            change_request = ChangeRequest.create(
                workspace_id=workspace_id,
                number=number,
                request_type=request_type,
                title=title,
                description=description,
                requester_id=requester_id,
                items=list(bound_items),
                classification=classification,
                requested_due_date=requested_due_date,
                priority=priority,
                urgency=urgency,
            )
            await uow.change_requests.add(change_request)
            await uow.outbox.add_events(change_request.events)
            await uow.idempotency.save_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation="change_request.create",
                request_hash=request_hash,
                result={
                    "change_request_id": str(change_request.change_request_id),
                    "requester_id": str(subject.subject_id),
                },
            )
            await uow.commit()
        change_request.events.clear()
        return change_request

    async def transition(
        self,
        *,
        workspace_id: UUID,
        change_request_id: UUID,
        target: ChangeState,
        actor_id: UUID,
        reason: str,
        expected_version: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> ChangeRequest:
        if target in {ChangeState.APPLYING, ChangeState.APPLIED, ChangeState.APPLY_FAILED}:
            raise ValidationError("The requested state is controlled by the application worker.")
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            operation = f"change_request.transition:{change_request_id}"
            existing = await uow.idempotency.get_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
            )
            change_request = await uow.change_requests.get_for_update(
                workspace_id=workspace_id, change_request_id=change_request_id
            )
            if change_request is None:
                raise ChangeRequestNotFound("The change request does not exist.")
            action = Action.CHANGE_REVIEW
            if (
                change_request.state is ChangeState.CHANGES_REQUESTED
                and target is ChangeState.REGISTERED
            ):
                action = Action.CHANGE_EDIT
            elif target is ChangeState.APPLY_QUEUED:
                action = (
                    Action.CHANGE_RETRY
                    if change_request.state is ChangeState.APPLY_FAILED
                    else Action.CHANGE_APPROVE
                )
            decision = await self._authorization.authorize(
                subject=subject,
                resource=self._resource(change_request),
                action=action,
                environment=environment,
                request_id=request_id,
            )
            if not await self._authorize_current_targets(
                change_requests=(change_request,),
                workspace_id=workspace_id,
                subject=subject,
                action=action,
                environment=environment,
                request_id=request_id,
                strict_binding=True,
            ):
                raise ForbiddenError("The change target is not available.")
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise ConflictError("The idempotency key was used with a different request.")
                if existing.result.get("actor_id") != str(subject.subject_id):
                    raise ConflictError("The idempotency key belongs to another subject.")
                return change_request
            change_request.transition(
                target=target,
                actor_id=actor_id,
                reason=reason,
                policy_decision_id=decision.decision_id,
                expected_version=expected_version,
            )
            await uow.change_requests.save(change_request)
            await uow.outbox.add_events(change_request.events)
            await uow.idempotency.save_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                result={
                    "change_request_id": str(change_request.change_request_id),
                    "actor_id": str(subject.subject_id),
                    "version": change_request.version,
                    "state": change_request.state.value,
                },
            )
            await uow.commit()
        change_request.events.clear()
        return change_request

    async def add_approval(
        self,
        *,
        workspace_id: UUID,
        change_request_id: UUID,
        stage: str,
        approval_decision: ApprovalDecision,
        reason: str,
        expected_version: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> ChangeRequest:
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            operation = f"change_request.approval:{change_request_id}"
            existing = await uow.idempotency.get_result(
                workspace_id=workspace_id, key=idempotency_key, operation=operation
            )
            change_request = await uow.change_requests.get_for_update(
                workspace_id=workspace_id, change_request_id=change_request_id
            )
            if change_request is None:
                raise ChangeRequestNotFound("The change request does not exist.")
            action = Action.CHANGE_APPROVE if stage == "FINAL" else Action.CHANGE_REVIEW
            decision = await self._authorization.authorize(
                subject=subject,
                resource=self._resource(change_request),
                action=action,
                environment=environment,
                request_id=request_id,
            )
            if not await self._authorize_current_targets(
                change_requests=(change_request,),
                workspace_id=workspace_id,
                subject=subject,
                action=action,
                environment=environment,
                request_id=request_id,
                strict_binding=True,
            ):
                raise ForbiddenError("The change target is not available.")
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise ConflictError("The idempotency key was used with a different request.")
                if existing.result.get("actor_id") != str(subject.subject_id):
                    raise ConflictError("The idempotency key belongs to another subject.")
                return change_request
            change_request.add_approval(
                stage=stage,
                decision=approval_decision,
                actor_id=subject.subject_id,
                reason=reason,
                policy_decision_id=decision.decision_id,
                expected_version=expected_version,
            )
            await uow.change_requests.save(change_request)
            await uow.outbox.add_events(change_request.events)
            await uow.idempotency.save_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                result={
                    "change_request_id": str(change_request.change_request_id),
                    "actor_id": str(subject.subject_id),
                    "version": change_request.version,
                },
            )
            await uow.commit()
        change_request.events.clear()
        return change_request
