from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from datariver.application.dto import IdempotencyRecord
from datariver.application.ports import (
    IdempotencyStore,
    MembershipAccessRepository,
    OutboxWriter,
)
from datariver.domain.authz import (
    Action,
    Classification,
    Decision,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import (
    ConflictError,
    DomainEvent,
    ForbiddenError,
    NotFoundError,
)
from datariver.domain.inference_provider import (
    InferenceProviderProfileState,
    InferenceProviderProfileVersion,
)

_FORBIDDEN_AUDIT_KEY_FRAGMENTS = (
    "url",
    "endpoint",
    "credential",
    "secret",
    "api_key",
    "server_route_key",
)


@dataclass(frozen=True, slots=True)
class InferenceProviderProfilePage:
    items: tuple[InferenceProviderProfileVersion, ...]
    next_cursor: str | None


class InferenceProviderProfileRepository(Protocol):
    async def get(
        self, *, workspace_id: UUID, profile_version_id: UUID
    ) -> InferenceProviderProfileVersion | None: ...

    async def list(
        self,
        *,
        workspace_id: UUID,
        profile_key: str | None = None,
        state: InferenceProviderProfileState | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> InferenceProviderProfilePage: ...

    async def approve(self, profile: InferenceProviderProfileVersion) -> None: ...

    async def reject(self, profile: InferenceProviderProfileVersion) -> None: ...

    async def revoke(self, profile: InferenceProviderProfileVersion) -> None: ...


class InferenceAdminAuthorization(Protocol):
    async def authorize(
        self,
        *,
        subject: SubjectAttributes,
        resource: ResourceAttributes,
        action: Action,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> Decision: ...


class InferenceAdminUnitOfWork(Protocol):
    profiles: InferenceProviderProfileRepository
    memberships: MembershipAccessRepository
    outbox: OutboxWriter
    idempotency: IdempotencyStore

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def lock_workspace(self, *, workspace_id: UUID) -> None: ...

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None: ...


class InferenceAdminService:
    """Admin-only lifecycle for operator-registry proposals; no proposal API is exposed."""

    def __init__(
        self,
        uow_factory: Callable[[], InferenceAdminUnitOfWork],
        authorization: InferenceAdminAuthorization,
    ) -> None:
        self._uow_factory = uow_factory
        self._authorization = authorization

    async def list_profiles(
        self,
        *,
        workspace_id: UUID,
        profile_key: str | None,
        state: InferenceProviderProfileState | None,
        limit: int,
        cursor: str | None,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> InferenceProviderProfilePage:
        await self._authorize(
            workspace_id=workspace_id,
            resource_id=workspace_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await self._assert_current_human_admin(
                uow=uow, workspace_id=workspace_id, subject_ids={subject.subject_id}
            )
            return await uow.profiles.list(
                workspace_id=workspace_id,
                profile_key=profile_key,
                state=state,
                limit=limit,
                cursor=cursor,
            )

    async def get_profile(
        self,
        *,
        workspace_id: UUID,
        profile_version_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> InferenceProviderProfileVersion:
        await self._authorize(
            workspace_id=workspace_id,
            resource_id=profile_version_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await self._assert_current_human_admin(
                uow=uow, workspace_id=workspace_id, subject_ids={subject.subject_id}
            )
            profile = await uow.profiles.get(
                workspace_id=workspace_id, profile_version_id=profile_version_id
            )
            if profile is None:
                raise NotFoundError("The inference provider profile does not exist.")
            return profile

    async def approve_profile(
        self,
        *,
        workspace_id: UUID,
        profile_version_id: UUID,
        reason: str,
        expected_version: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> InferenceProviderProfileVersion:
        return await self._decide_profile(
            approve=True,
            workspace_id=workspace_id,
            profile_version_id=profile_version_id,
            reason=reason,
            expected_version=expected_version,
            subject=subject,
            environment=environment,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def reject_profile(
        self,
        *,
        workspace_id: UUID,
        profile_version_id: UUID,
        reason: str,
        expected_version: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> InferenceProviderProfileVersion:
        return await self._decide_profile(
            approve=False,
            workspace_id=workspace_id,
            profile_version_id=profile_version_id,
            reason=reason,
            expected_version=expected_version,
            subject=subject,
            environment=environment,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def revoke_profile(
        self,
        *,
        workspace_id: UUID,
        profile_version_id: UUID,
        reason: str,
        expected_version: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> InferenceProviderProfileVersion:
        decision = await self._authorize(
            workspace_id=workspace_id,
            resource_id=profile_version_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        operation = f"inference.provider_profile.revoke:{profile_version_id}"
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await uow.lock_workspace(workspace_id=workspace_id)
            profile = await uow.profiles.get(
                workspace_id=workspace_id, profile_version_id=profile_version_id
            )
            if profile is None:
                raise NotFoundError("The inference provider profile does not exist.")
            await self._assert_current_human_admin(
                uow=uow, workspace_id=workspace_id, subject_ids={subject.subject_id}
            )
            existing = await uow.idempotency.get_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
            )
            if existing is not None:
                _verify_idempotent_replay(
                    record=existing,
                    request_hash=request_hash,
                    actor_id=subject.subject_id,
                    profile=profile,
                )
                return profile
            profile.revoke(
                actor_id=subject.subject_id,
                reason=reason,
                policy_decision_id=decision.decision_id,
                expected_version=expected_version,
                now=environment.requested_at,
            )
            await uow.profiles.revoke(profile)
            await self._persist_change(
                uow=uow,
                profile=profile,
                subject=subject,
                operation=operation,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
        profile.events.clear()
        return profile

    async def _decide_profile(
        self,
        *,
        approve: bool,
        workspace_id: UUID,
        profile_version_id: UUID,
        reason: str,
        expected_version: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> InferenceProviderProfileVersion:
        decision = await self._authorize(
            workspace_id=workspace_id,
            resource_id=profile_version_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        action = "approve" if approve else "reject"
        operation = f"inference.provider_profile.{action}:{profile_version_id}"
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=subject.subject_id)
            await uow.lock_workspace(workspace_id=workspace_id)
            profile = await uow.profiles.get(
                workspace_id=workspace_id, profile_version_id=profile_version_id
            )
            if profile is None:
                raise NotFoundError("The inference provider profile does not exist.")
            await self._assert_current_human_admin(
                uow=uow,
                workspace_id=workspace_id,
                subject_ids={subject.subject_id, profile.maker_id},
            )
            existing = await uow.idempotency.get_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
            )
            if existing is not None:
                _verify_idempotent_replay(
                    record=existing,
                    request_hash=request_hash,
                    actor_id=subject.subject_id,
                    profile=profile,
                )
                return profile
            if approve:
                profile.approve(
                    checker_id=subject.subject_id,
                    reason=reason,
                    policy_decision_id=decision.decision_id,
                    expected_version=expected_version,
                    now=environment.requested_at,
                )
                await uow.profiles.approve(profile)
            else:
                profile.reject(
                    checker_id=subject.subject_id,
                    reason=reason,
                    policy_decision_id=decision.decision_id,
                    expected_version=expected_version,
                    now=environment.requested_at,
                )
                await uow.profiles.reject(profile)
            await self._persist_change(
                uow=uow,
                profile=profile,
                subject=subject,
                operation=operation,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
        profile.events.clear()
        return profile

    async def _persist_change(
        self,
        *,
        uow: InferenceAdminUnitOfWork,
        profile: InferenceProviderProfileVersion,
        subject: SubjectAttributes,
        operation: str,
        idempotency_key: str,
        request_hash: str,
    ) -> None:
        events = tuple(profile.events)
        _assert_safe_audit_events(events)
        await uow.outbox.add_events(events)
        await uow.idempotency.save_result(
            workspace_id=profile.workspace_id,
            key=idempotency_key,
            operation=operation,
            request_hash=request_hash,
            result={
                "actor_id": str(subject.subject_id),
                "profile_version_id": str(profile.provider_profile_version_id),
                "payload_hash": profile.payload_hash,
                "state": profile.state.value,
                "version": profile.version,
            },
        )
        await uow.commit()

    async def _authorize(
        self,
        *,
        workspace_id: UUID,
        resource_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> Decision:
        _require_human_subject(subject)
        return await self._authorization.authorize(
            subject=subject,
            resource=_resource(workspace_id=workspace_id, resource_id=resource_id),
            action=Action.ADMIN_MANAGE,
            environment=environment,
            request_id=request_id,
        )

    @staticmethod
    async def _assert_current_human_admin(
        *,
        uow: InferenceAdminUnitOfWork,
        workspace_id: UUID,
        subject_ids: set[UUID],
    ) -> None:
        await uow.memberships.assert_eligible_human_administrators(
            workspace_id=workspace_id,
            subject_ids=frozenset(subject_ids),
        )


def _resource(*, workspace_id: UUID, resource_id: UUID) -> ResourceAttributes:
    return ResourceAttributes(
        resource_id=resource_id,
        workspace_id=workspace_id,
        resource_type="inference_provider_profile",
        owner_department_id=None,
        system_id=None,
        domain_id=None,
        classification=Classification.RESTRICTED,
        lifecycle="ACTIVE",
    )


def _require_human_subject(subject: SubjectAttributes) -> None:
    if subject.job_function == "SERVICE_ACCOUNT" or "service-accounts" in subject.groups:
        raise ForbiddenError("A service account cannot administer inference providers.")


def _verify_idempotent_replay(
    *,
    record: IdempotencyRecord,
    request_hash: str,
    actor_id: UUID,
    profile: InferenceProviderProfileVersion,
) -> None:
    if record.request_hash != request_hash:
        raise ConflictError("The idempotency key was used with a different request.")
    if record.result.get("actor_id") != str(actor_id):
        raise ConflictError("The idempotency key belongs to another subject.")
    if (
        record.result.get("profile_version_id") != str(profile.provider_profile_version_id)
        or record.result.get("payload_hash") != profile.payload_hash
        or record.result.get("state") != profile.state.value
        or record.result.get("version") != profile.version
    ):
        raise ConflictError("The idempotent provider profile result is no longer current.")


def _assert_safe_audit_events(events: Sequence[DomainEvent]) -> None:
    for event in events:
        for key in event.payload:
            lowered = key.lower()
            if any(fragment in lowered for fragment in _FORBIDDEN_AUDIT_KEY_FRAGMENTS):
                raise ConflictError("The provider audit event contains forbidden connection data.")
