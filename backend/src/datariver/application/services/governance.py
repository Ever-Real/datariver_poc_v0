from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from datariver.application.dto import (
    ChangeRequestSummaryPage,
    ChangeRequestSummaryRecord,
    RegistrationCandidateBindingCommand,
)
from datariver.application.ports import GovernanceUnitOfWork
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
    canonical_json_hash,
)
from datariver.domain.governance import (
    ApprovalAuthority,
    ApprovalAuthorityKind,
    ApprovalDecision,
    ChangeItem,
    ChangePriority,
    ChangeRequest,
    ChangeState,
    ChangeTestRunState,
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

    async def filter_authorized_summaries(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        summaries: Sequence[ChangeRequestSummaryRecord],
        action: Action,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[ChangeRequestSummaryRecord, ...]: ...

    async def authorize_approval_targets(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        change_request: ChangeRequest,
        action: Action,
        approval_system_ids: frozenset[UUID],
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> frozenset[UUID]: ...


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
            system_id=(
                item.routing_system_id or item.target_system_id if item is not None else None
            ),
            domain_id=item.target_domain_id if item is not None else None,
            classification=max(change_request.classification, target_classification),
            lifecycle=change_request.state.value,
            requester_id=change_request.requester_id,
        )

    @staticmethod
    async def _workflow_authorities(
        uow: GovernanceUnitOfWork,
        *,
        change_request: ChangeRequest,
        subject_id: UUID,
    ) -> tuple[ApprovalAuthority, ...]:
        return await uow.workflow_authorities.get_authorities(
            workspace_id=change_request.workspace_id,
            subject_id=subject_id,
            system_ids=change_request.required_system_ids(),
        )

    @classmethod
    async def _require_developer_for_target_system(
        cls,
        uow: GovernanceUnitOfWork,
        *,
        change_request: ChangeRequest,
        subject_id: UUID,
    ) -> tuple[ApprovalAuthority, ...]:
        authorities = await cls._workflow_authorities(
            uow, change_request=change_request, subject_id=subject_id
        )
        relevant = {
            ApprovalAuthority(ApprovalAuthorityKind.SYSTEM_DEVELOPER, system_id)
            for system_id in change_request.required_system_ids()
        }
        if not relevant & set(authorities):
            raise ForbiddenError(
                "Developer assignment is required for a target system in this stage."
            )
        return authorities

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

    @staticmethod
    def _relevant_approval_authorities(
        *,
        change_request: ChangeRequest,
        stage: str,
        authorities: Sequence[ApprovalAuthority],
    ) -> tuple[ApprovalAuthority, ...]:
        required_system_ids = change_request.required_system_ids()
        if stage in {"REVIEW", "TEST"}:
            allowed_kinds = frozenset({ApprovalAuthorityKind.SYSTEM_DEVELOPER})
        else:
            allowed_kinds = frozenset(
                {
                    ApprovalAuthorityKind.SYSTEM_DEVELOPER,
                    ApprovalAuthorityKind.SYSTEM_DATA_STEWARD,
                    ApprovalAuthorityKind.GLOBAL_ADMIN,
                }
            )
        return tuple(
            sorted(
                (
                    authority
                    for authority in authorities
                    if authority.kind in allowed_kinds
                    and (
                        authority.kind is ApprovalAuthorityKind.GLOBAL_ADMIN
                        or authority.system_id in required_system_ids
                    )
                ),
                key=lambda authority: (authority.kind.value, str(authority.system_id)),
            )
        )

    @staticmethod
    def _approval_response_view(
        change_request: ChangeRequest,
        *,
        visible_item_ids: frozenset[UUID],
    ) -> ChangeRequest:
        visible_items = [item for item in change_request.items if item.item_id in visible_item_ids]
        visible_system_ids = {
            item.routing_system_id or item.target_system_id for item in visible_items
        }
        visible_system_ids.discard(None)
        visible_approvals = []
        for approval in change_request.approvals:
            visible_authorities = tuple(
                authority
                for authority in approval.authorities
                if authority.kind is ApprovalAuthorityKind.GLOBAL_ADMIN
                or authority.system_id in visible_system_ids
            )
            if visible_authorities:
                visible_approvals.append(replace(approval, authorities=visible_authorities))
        return replace(
            change_request,
            items=visible_items,
            approvals=visible_approvals,
            test_runs=[
                test_run
                for test_run in change_request.test_runs
                if test_run.system_id in visible_system_ids
            ],
            events=[],
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

    async def authorize_attachment(
        self,
        *,
        workspace_id: UUID,
        change_request_id: UUID,
        kind: str,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> ChangeRequest:
        """Authorize an attachment against the current CR state and bound target."""

        if kind not in {"REQUEST", "TEST"}:
            raise ValidationError("The change-request attachment kind is invalid.")
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            change_request = await uow.change_requests.get_for_update(
                workspace_id=workspace_id,
                change_request_id=change_request_id,
            )
            if change_request is None:
                raise ChangeRequestNotFound("The change request does not exist.")
            if kind == "TEST":
                if change_request.state is not ChangeState.TESTING:
                    raise ValidationError(
                        "Test evidence can only be attached during the TESTING state."
                    )
                action = Action.CHANGE_REVIEW
                await self._require_developer_for_target_system(
                    uow,
                    change_request=change_request,
                    subject_id=subject.subject_id,
                )
            else:
                if change_request.state not in {
                    ChangeState.REGISTERED,
                    ChangeState.CHANGES_REQUESTED,
                }:
                    raise ValidationError(
                        "Request attachments can only be changed before review or after a "
                        "change request."
                    )
                action = Action.CHANGE_EDIT
            await self._authorization.authorize(
                subject=subject,
                resource=self._resource(change_request),
                action=action,
                environment=environment,
                request_id=request_id,
            )
            authorized = await self._authorize_current_targets(
                change_requests=(change_request,),
                workspace_id=workspace_id,
                subject=subject,
                action=action,
                environment=environment,
                request_id=request_id,
                strict_binding=True,
            )
            if not authorized:
                raise ForbiddenError("The change target is not available.")
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

    async def list_change_request_summaries(
        self,
        *,
        workspace_id: UUID,
        state: ChangeState | None,
        cursor: str | None,
        limit: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> ChangeRequestSummaryPage:
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
        context = canonical_json_hash(
            {
                "contract": "change-request-summary-cursor-v1",
                "state": state.value if state else None,
                "subject_id": str(subject.subject_id),
                "workspace_id": str(workspace_id),
            }
        )
        before_created_at, before_id = _unwrap_change_summary_cursor(
            cursor,
            expected_context=context,
        )
        async with self._uow_factory() as uow:
            await uow.set_security_context(
                workspace_id=workspace_id,
                subject_id=subject.subject_id,
            )
            raw = tuple(
                await uow.change_requests.list_summaries(
                    workspace_id=workspace_id,
                    maximum_classification=int(subject.clearance),
                    state=state.value if state else None,
                    before_created_at=before_created_at,
                    before_id=before_id,
                    limit=limit + 1,
                )
            )
            await uow.commit()
        window = raw[:limit]
        if self._target_authorizer is None:
            raise RuntimeError("Change-target authorization is unavailable.")
        visible = await self._target_authorizer.filter_authorized_summaries(
            workspace_id=workspace_id,
            subject=subject,
            summaries=window,
            action=Action.CHANGE_READ,
            environment=environment,
            request_id=request_id,
        )
        next_cursor = (
            _wrap_change_summary_cursor(
                created_at=window[-1].created_at,
                change_request_id=window[-1].change_request_id,
                context=context,
            )
            if len(raw) > limit and window
            else None
        )
        return ChangeRequestSummaryPage(items=visible, next_cursor=next_cursor)

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
        registration_candidate_binding: RegistrationCandidateBindingCommand | None = None,
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
            await uow.idempotency.acquire_key_lock(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation="change_request.create",
            )
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
                requester_department_id=subject.department_id,
                classification=classification,
                requested_due_date=requested_due_date,
                priority=priority,
                urgency=urgency,
            )
            await uow.change_requests.add(change_request)
            if registration_candidate_binding is not None:
                await uow.registration_content_bindings.verify_and_add(
                    command=registration_candidate_binding,
                    change_request_id=change_request.change_request_id,
                    change_item_id=change_request.items[0].item_id,
                    created_by=subject.subject_id,
                )
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

    async def find_idempotent_create(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> ChangeRequest | None:
        """Recover a committed create before any fallible provider preview is repeated."""

        async with self._uow_factory() as uow:
            await uow.set_security_context(
                workspace_id=workspace_id,
                subject_id=subject.subject_id,
            )
            await uow.idempotency.acquire_key_lock(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation="change_request.create",
            )
            existing = await uow.idempotency.get_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation="change_request.create",
            )
            if existing is None:
                return None
            if existing.request_hash != request_hash:
                raise ConflictError("The idempotency key was used with a different request.")
            if existing.result.get("requester_id") != str(subject.subject_id):
                raise ConflictError("The idempotency key belongs to another subject.")
            existing_request = await uow.change_requests.get_for_update(
                workspace_id=workspace_id,
                change_request_id=UUID(str(existing.result["change_request_id"])),
            )
            if existing_request is None:
                raise ConflictError("The idempotent result is no longer available.")
            await self._authorization.authorize(
                subject=subject,
                resource=ResourceAttributes(
                    resource_id=workspace_id,
                    workspace_id=workspace_id,
                    resource_type="change_request_collection",
                    owner_department_id=subject.department_id,
                    system_id=None,
                    domain_id=None,
                    classification=existing_request.classification,
                    lifecycle="ACTIVE",
                    requester_id=existing_request.requester_id,
                ),
                action=Action.CHANGE_CREATE,
                environment=environment,
                request_id=request_id,
            )
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
        if target in {
            ChangeState.APPLYING,
            ChangeState.APPLIED,
            ChangeState.APPLY_FAILED,
            ChangeState.COMPLETED,
        }:
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
            if (
                change_request.state is ChangeState.REGISTERED and target is ChangeState.IN_REVIEW
            ) or change_request.state in {ChangeState.IN_REVIEW, ChangeState.TESTING}:
                await self._require_developer_for_target_system(
                    uow,
                    change_request=change_request,
                    subject_id=subject.subject_id,
                )
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

    async def complete_intake(
        self,
        *,
        workspace_id: UUID,
        change_request_id: UUID,
        actor_id: UUID,
        reason: str,
        expected_version: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> ChangeRequest:
        """Complete a non-executable, human-verified intake after final review."""

        if actor_id != subject.subject_id:
            raise ForbiddenError("The completion actor must match the authenticated subject.")
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            operation = f"change_request.complete_intake:{change_request_id}"
            existing = await uow.idempotency.get_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
            )
            change_request = await uow.change_requests.get_for_update(
                workspace_id=workspace_id,
                change_request_id=change_request_id,
            )
            if change_request is None:
                raise ChangeRequestNotFound("The change request does not exist.")
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise ConflictError("The idempotency key was used with a different request.")
                if existing.result.get("actor_id") != str(subject.subject_id):
                    raise ConflictError("The idempotency key belongs to another subject.")
            decision = await self._authorization.authorize(
                subject=subject,
                resource=self._resource(change_request),
                action=Action.CHANGE_REVIEW,
                environment=environment,
                request_id=request_id,
            )
            if not await self._authorize_current_targets(
                change_requests=(change_request,),
                workspace_id=workspace_id,
                subject=subject,
                action=Action.CHANGE_REVIEW,
                environment=environment,
                request_id=request_id,
                strict_binding=True,
            ):
                raise ForbiddenError("The change target is not available.")
            await self._require_developer_for_target_system(
                uow,
                change_request=change_request,
                subject_id=subject.subject_id,
            )
            if existing is not None:
                return change_request
            change_request.complete_intake(
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
                    "change_request_id": str(change_request_id),
                    "actor_id": str(subject.subject_id),
                    "version": change_request.version,
                },
            )
            await uow.commit()
        change_request.events.clear()
        return change_request

    async def record_test_run(
        self,
        *,
        workspace_id: UUID,
        change_request_id: UUID,
        system_id: UUID,
        attachment_id: UUID,
        state: ChangeTestRunState,
        plan_hash: str,
        result_hash: str,
        bounded_summary: dict[str, object],
        expected_version: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> ChangeRequest:
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            operation = f"change_request.test_run:{change_request_id}"
            existing = await uow.idempotency.get_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
            )
            change_request = await uow.change_requests.get_for_update(
                workspace_id=workspace_id,
                change_request_id=change_request_id,
            )
            if change_request is None:
                raise ChangeRequestNotFound("The change request does not exist.")
            decision = await self._authorization.authorize(
                subject=subject,
                resource=self._resource(change_request),
                action=Action.CHANGE_REVIEW,
                environment=environment,
                request_id=request_id,
            )
            if not await self._authorize_current_targets(
                change_requests=(change_request,),
                workspace_id=workspace_id,
                subject=subject,
                action=Action.CHANGE_REVIEW,
                environment=environment,
                request_id=request_id,
                strict_binding=True,
            ):
                raise ForbiddenError("The change target is not available.")
            authorities = await self._require_developer_for_target_system(
                uow,
                change_request=change_request,
                subject_id=subject.subject_id,
            )
            required = ApprovalAuthority(ApprovalAuthorityKind.SYSTEM_DEVELOPER, system_id)
            if required not in authorities:
                raise ForbiddenError("Developer assignment is required for the test system.")
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise ConflictError("The idempotency key was used with a different request.")
                if existing.result.get("actor_id") != str(subject.subject_id):
                    raise ConflictError("The idempotency key belongs to another subject.")
                return change_request
            change_request.record_test_run(
                system_id=system_id,
                attachment_id=attachment_id,
                state=state,
                plan_hash=plan_hash,
                result_hash=result_hash,
                bounded_summary=bounded_summary,
                actor_id=subject.subject_id,
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
                    "change_request_id": str(change_request_id),
                    "actor_id": str(subject.subject_id),
                    "system_id": str(system_id),
                    "version": change_request.version,
                    "policy_decision_id": str(decision.decision_id),
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
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise ConflictError("The idempotency key was used with a different request.")
                if existing.result.get("actor_id") != str(subject.subject_id):
                    raise ConflictError("The idempotency key belongs to another subject.")
            action = Action.CHANGE_APPROVE if stage == "FINAL" else Action.CHANGE_REVIEW
            decision = await self._authorization.authorize(
                subject=subject,
                resource=self._resource(change_request),
                action=action,
                environment=environment,
                request_id=request_id,
            )
            current_authorities = await self._workflow_authorities(
                uow,
                change_request=change_request,
                subject_id=subject.subject_id,
            )
            authorities = self._relevant_approval_authorities(
                change_request=change_request,
                stage=stage,
                authorities=current_authorities,
            )
            approval_system_ids = frozenset(
                authority.system_id for authority in authorities if authority.system_id is not None
            )
            if self._target_authorizer is None:
                raise RuntimeError("Change-request approval requires a target authorizer.")
            visible_item_ids = await self._target_authorizer.authorize_approval_targets(
                workspace_id=workspace_id,
                subject=subject,
                change_request=change_request,
                action=action,
                approval_system_ids=approval_system_ids,
                environment=environment,
                request_id=request_id,
            )
            if existing is not None:
                return self._approval_response_view(
                    change_request,
                    visible_item_ids=visible_item_ids,
                )
            change_request.add_approval(
                stage=stage,
                decision=approval_decision,
                actor_id=subject.subject_id,
                reason=reason,
                policy_decision_id=decision.decision_id,
                expected_version=expected_version,
                authorities=authorities,
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
            response = self._approval_response_view(
                change_request,
                visible_item_ids=visible_item_ids,
            )
        change_request.events.clear()
        return response


def _wrap_change_summary_cursor(
    *,
    created_at: datetime,
    change_request_id: UUID,
    context: str,
) -> str:
    payload = json.dumps(
        {
            "v": 1,
            "context": context,
            "created_at": created_at.isoformat(),
            "change_request_id": str(change_request_id),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _unwrap_change_summary_cursor(
    cursor: str | None,
    *,
    expected_context: str,
) -> tuple[datetime | None, UUID | None]:
    if cursor is None:
        return None, None
    try:
        document = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        if (
            not isinstance(document, dict)
            or set(document) != {"v", "context", "created_at", "change_request_id"}
            or document.get("v") != 1
            or document.get("context") != expected_context
        ):
            raise ValueError
        created_at = datetime.fromisoformat(str(document["created_at"]))
        if created_at.tzinfo is None:
            raise ValueError
        return created_at, UUID(str(document["change_request_id"]))
    except (ValueError, TypeError, json.JSONDecodeError, binascii.Error) as error:
        raise ValidationError("The change-request cursor is stale or invalid.") from error
