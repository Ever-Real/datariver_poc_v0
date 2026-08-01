from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self, cast
from uuid import UUID, uuid4

import pytest

from datariver.application.dto import IdempotencyRecord
from datariver.application.identity_admin import (
    IdentityAdministration,
    IdentityProfileTarget,
    IdentityUserDraft,
    IdentityUserProfile,
    IdentityUserProfileDraft,
    ProvisionedIdentity,
)
from datariver.application.ports import AdminAccessUnitOfWork
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.identity_admin import IdentityAdminService
from datariver.domain.authz import (
    Action,
    AuthenticationAssurance,
    Classification,
    Decision,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import DomainEvent, ValidationError

NOW = datetime(2035, 1, 1, 12, tzinfo=UTC)


class _DecisionWriter:
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


class _Provider:
    def __init__(self) -> None:
        self.ensured: list[IdentityUserDraft] = []
        self.updated: list[tuple[str, IdentityUserProfileDraft]] = []
        self.resets: list[tuple[str, str]] = []

    async def ensure_disabled_user(self, draft: IdentityUserDraft) -> ProvisionedIdentity:
        self.ensured.append(draft)
        return ProvisionedIdentity(
            external_subject="provider-created-user",
            username=draft.username,
            created=True,
        )

    async def enable_user(self, *, external_subject: str) -> None:
        del external_subject

    async def update_user_profile(
        self,
        *,
        external_subject: str,
        draft: IdentityUserProfileDraft,
    ) -> IdentityUserProfile:
        self.updated.append((external_subject, draft))
        return IdentityUserProfile(
            external_subject=external_subject,
            username="managed.user",
            email=draft.email,
            first_name=draft.first_name,
            last_name=draft.last_name,
            enabled=True,
            email_verified=False,
            required_actions=(),
        )

    async def reset_temporary_password(
        self,
        *,
        external_subject: str,
        temporary_password: str,
    ) -> None:
        self.resets.append((external_subject, temporary_password))


class _Memberships:
    def __init__(self, target: IdentityProfileTarget) -> None:
        self.target = target
        self.updates: list[dict[str, object]] = []
        self.assignable_role_error: ValidationError | None = None

    async def assert_eligible_human_administrators(
        self, *, workspace_id: UUID, subject_ids: frozenset[UUID]
    ) -> None:
        assert workspace_id == self.target.workspace_id
        assert len(subject_ids) == 1

    async def assert_assignable_human_role(self, *, workspace_id: UUID, role_id: UUID) -> None:
        assert workspace_id == self.target.workspace_id
        del role_id
        if self.assignable_role_error is not None:
            raise self.assignable_role_error

    async def get_identity_profile_target(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        for_update: bool = False,
    ) -> IdentityProfileTarget | None:
        assert workspace_id == self.target.workspace_id
        assert subject_id == self.target.subject_id
        assert for_update is True
        return self.target

    async def update_identity_profile(
        self,
        *,
        target: IdentityProfileTarget,
        expected_membership_version: int,
        display_name: str,
        email: str,
        department_id: UUID | None,
        job_function: str | None,
    ) -> int:
        self.updates.append(
            {
                "target": target,
                "expected_membership_version": expected_membership_version,
                "display_name": display_name,
                "email": email,
                "department_id": department_id,
                "job_function": job_function,
            }
        )
        return expected_membership_version + 1


class _Outbox:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def add_events(self, events: Sequence[DomainEvent]) -> None:
        self.events.extend(events)


class _Idempotency:
    def __init__(self) -> None:
        self.record: IdempotencyRecord | None = None

    async def get_result(
        self, *, workspace_id: UUID, key: str, operation: str
    ) -> IdempotencyRecord | None:
        del workspace_id, key, operation
        return self.record

    async def save_result(
        self,
        *,
        workspace_id: UUID,
        key: str,
        operation: str,
        request_hash: str,
        result: dict[str, object],
    ) -> None:
        del workspace_id, key, operation
        self.record = IdempotencyRecord(request_hash=request_hash, result=result)


class _Uow:
    def __init__(self, target: IdentityProfileTarget) -> None:
        self.memberships = _Memberships(target)
        self.outbox = _Outbox()
        self.idempotency = _Idempotency()
        self.commits = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None:
        del workspace_id, subject_id

    async def lock_workspace_access(self, *, workspace_id: UUID) -> None:
        del workspace_id

    async def commit(self) -> None:
        self.commits += 1


def _subject(workspace_id: UUID) -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset({"security-administrators"}),
        job_function="SECURITY_ADMINISTRATOR",
        clearance=Classification.RESTRICTED,
        allowed_actions=frozenset({Action.ADMIN_MANAGE}),
        authentication_time=NOW,
        authentication_assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
    )


def _target(*, service_account: bool = False) -> IdentityProfileTarget:
    return IdentityProfileTarget(
        subject_id=uuid4(),
        workspace_id=uuid4(),
        issuer="https://identity.example/realms/datariver",
        external_subject="provider-user-123",
        display_name="Managed User",
        email="managed@example.test",
        department_id=None,
        job_function="SERVICE_ACCOUNT" if service_account else "ENGINEER",
        membership_version=3,
        subject_active=True,
        membership_active=True,
        service_account=service_account,
        access_expires_at=NOW + timedelta(days=30),
    )


def _service(target: IdentityProfileTarget) -> tuple[IdentityAdminService, _Uow, _Provider]:
    uow = _Uow(target)
    provider = _Provider()
    service = IdentityAdminService(
        uow_factory=lambda: cast(AdminAccessUnitOfWork, uow),
        authorization=AuthorizationService(decision_writer=_DecisionWriter()),
        provider=cast(IdentityAdministration, provider),
        issuer=target.issuer,
    )
    return service, uow, provider


@pytest.mark.asyncio
async def test_user_provisioning_rejects_any_explicit_role_before_provider_mutation() -> None:
    target = _target()
    service, uow, provider = _service(target)
    uow.memberships.assignable_role_error = ValidationError(
        "Canonical Admin cannot be assigned through a generic Role path."
    )

    with pytest.raises(
        ValidationError,
        match="New human identities always receive the Viewer profile Role",
    ):
        await service.provision_user(
            draft=IdentityUserDraft(
                username="new.user",
                email="new.user@example.test",
                first_name="New",
                last_name="User",
                temporary_password="temporary-only",
                workspace_id=target.workspace_id,
                provisioning_reference="test-reference",
            ),
            department_id=None,
            job_function="DATA_ENGINEER",
            role_id=uuid4(),
            subject=_subject(target.workspace_id),
            environment=EnvironmentAttributes(requested_at=NOW, network_zone="INTERNAL"),
            request_id="request-provision-canonical",
            idempotency_key="provision-canonical-role",
            request_hash="d" * 64,
        )

    assert provider.ensured == []
    assert uow.commits == 0


@pytest.mark.asyncio
async def test_profile_update_reconciles_provider_and_projection_without_secrets() -> None:
    target = _target()
    service, uow, provider = _service(target)
    actor = _subject(target.workspace_id)
    department_id = uuid4()

    result = await service.update_user_profile(
        workspace_id=target.workspace_id,
        target_subject_id=target.subject_id,
        expected_membership_version=3,
        draft=IdentityUserProfileDraft(
            email="updated@example.test",
            first_name="Updated",
            last_name="User",
        ),
        department_id=department_id,
        job_function="DATA_ENGINEER",
        subject=actor,
        environment=EnvironmentAttributes(requested_at=NOW, network_zone="INTERNAL"),
        request_id="request-one",
        idempotency_key="identity-profile-key",
        request_hash="a" * 64,
    )

    assert result.membership_version == 4
    assert provider.updated[0][0] == target.external_subject
    assert uow.memberships.updates[0]["department_id"] == department_id
    assert uow.commits == 1
    event_document = str(uow.outbox.events[0].payload)
    assert "IDENTITY_PROVIDER_PROFILE" in event_document
    assert "updated@example.test" not in event_document

    uow.memberships.target = replace(target, membership_version=4)
    replay = await service.update_user_profile(
        workspace_id=target.workspace_id,
        target_subject_id=target.subject_id,
        expected_membership_version=3,
        draft=IdentityUserProfileDraft(
            email="updated@example.test",
            first_name="Updated",
            last_name="User",
        ),
        department_id=department_id,
        job_function="DATA_ENGINEER",
        subject=actor,
        environment=EnvironmentAttributes(requested_at=NOW, network_zone="INTERNAL"),
        request_id="request-replay",
        idempotency_key="identity-profile-key",
        request_hash="a" * 64,
    )

    assert replay == result
    assert len(provider.updated) == 1


@pytest.mark.asyncio
async def test_temporary_password_reset_is_versioned_and_never_persists_the_secret() -> None:
    target = _target()
    service, uow, provider = _service(target)
    actor = _subject(target.workspace_id)
    secret = "Temporary-Only-42!"

    result = await service.reset_temporary_password(
        workspace_id=target.workspace_id,
        target_subject_id=target.subject_id,
        expected_membership_version=3,
        temporary_password=secret,
        subject=actor,
        environment=EnvironmentAttributes(requested_at=NOW, network_zone="INTERNAL"),
        request_id="request-two",
        idempotency_key="identity-password-key",
        request_hash="b" * 64,
    )

    assert result.sessions_revoked is True
    assert provider.resets == [(target.external_subject, secret)]
    assert uow.idempotency.record is not None
    assert secret not in str(uow.idempotency.record.result)
    assert secret not in str(uow.outbox.events[0].payload)
    assert uow.commits == 1


@pytest.mark.asyncio
async def test_service_account_profile_target_is_rejected_before_provider_mutation() -> None:
    target = _target(service_account=True)
    service, _, provider = _service(target)

    with pytest.raises(ValidationError, match="active human identity"):
        await service.reset_temporary_password(
            workspace_id=target.workspace_id,
            target_subject_id=target.subject_id,
            expected_membership_version=3,
            temporary_password="Temporary-Only-42!",
            subject=_subject(target.workspace_id),
            environment=EnvironmentAttributes(requested_at=NOW, network_zone="INTERNAL"),
            request_id="request-three",
            idempotency_key="identity-password-key",
            request_hash="c" * 64,
        )

    assert provider.resets == []
