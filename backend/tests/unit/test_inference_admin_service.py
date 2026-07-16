from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self, cast
from uuid import UUID, uuid4

import pytest

from datariver.application.dto import IdempotencyRecord
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.inference_admin import (
    InferenceAdminService,
    InferenceAdminUnitOfWork,
)
from datariver.domain.authz import (
    Action,
    AuthenticationAssurance,
    Classification,
    Decision,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ConflictError, DomainEvent, ForbiddenError, ValidationError
from datariver.domain.inference_provider import (
    InferenceProviderProfile,
    InferenceProviderProfileState,
    InferenceProviderProfileVersion,
    ProviderAttestation,
    ProviderKind,
)

NOW = datetime(2035, 1, 1, 12, tzinfo=UTC)


class _DecisionWriter:
    def __init__(self) -> None:
        self.values: list[tuple[Decision, UUID, UUID, UUID, str, str]] = []

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
        self.values.append((decision, subject_id, workspace_id, resource_id, action, request_id))


class _Profiles:
    def __init__(self, profile: InferenceProviderProfileVersion) -> None:
        self.profile = profile
        self.writes: list[str] = []

    async def get(
        self, *, workspace_id: UUID, profile_version_id: UUID
    ) -> InferenceProviderProfileVersion | None:
        if (
            workspace_id != self.profile.workspace_id
            or profile_version_id != self.profile.provider_profile_version_id
        ):
            return None
        return self.profile

    async def list(
        self,
        *,
        workspace_id: UUID,
        profile_key: str | None = None,
        state: InferenceProviderProfileState | None = None,
        limit: int = 100,
    ) -> tuple[InferenceProviderProfileVersion, ...]:
        del limit
        if workspace_id != self.profile.workspace_id:
            return ()
        if profile_key is not None and profile_key != self.profile.profile.profile_key:
            return ()
        if state is not None and state is not self.profile.state:
            return ()
        return (self.profile,)

    async def approve(self, profile: InferenceProviderProfileVersion) -> None:
        assert profile is self.profile
        self.writes.append("approve")

    async def reject(self, profile: InferenceProviderProfileVersion) -> None:
        assert profile is self.profile
        self.writes.append("reject")

    async def revoke(self, profile: InferenceProviderProfileVersion) -> None:
        assert profile is self.profile
        self.writes.append("revoke")


class _Memberships:
    def __init__(self) -> None:
        self.checks: list[frozenset[UUID]] = []

    async def assert_eligible_human_administrators(
        self, *, workspace_id: UUID, subject_ids: frozenset[UUID]
    ) -> None:
        del workspace_id
        self.checks.append(subject_ids)


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
    def __init__(self, profile: InferenceProviderProfileVersion) -> None:
        self.profiles = _Profiles(profile)
        self.memberships = _Memberships()
        self.outbox = _Outbox()
        self.idempotency = _Idempotency()
        self.contexts: list[tuple[UUID, UUID]] = []
        self.locks: list[UUID] = []
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
        self.contexts.append((workspace_id, subject_id))

    async def lock_workspace(self, *, workspace_id: UUID) -> None:
        self.locks.append(workspace_id)

    async def commit(self) -> None:
        self.commits += 1


def _attestation(marker: str) -> ProviderAttestation:
    return ProviderAttestation(
        fingerprint=marker * 64,
        observed_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=1),
    )


def _proposal(
    *, workspace_id: UUID | None = None, maker_id: UUID | None = None
) -> InferenceProviderProfileVersion:
    return InferenceProviderProfileVersion.propose(
        workspace_id=workspace_id or uuid4(),
        profile_version=1,
        profile=InferenceProviderProfile(
            profile_key="profile-a",
            server_route_key="route-a",
            kind=ProviderKind.INTERNAL,
            provider_identity="provider-a",
            model_identity="model-a",
            deployment_identity="deployment-a",
            jurisdiction="JURISDICTION-A",
            region="region-a",
            maximum_classification=Classification.CONFIDENTIAL,
            residency_attestation=_attestation("a"),
            zero_retention_attestation=_attestation("b"),
        ),
        maker_id=maker_id or uuid4(),
        reason="Operator registry proposal",
        policy_decision_id=uuid4(),
        now=NOW,
    )


def _subject(
    workspace_id: UUID,
    *,
    subject_id: UUID | None = None,
    assurance: AuthenticationAssurance = AuthenticationAssurance.HARDWARE_WEBAUTHN,
    service_account: bool = False,
) -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=subject_id or uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset(
            {"security-administrators", "service-accounts"}
            if service_account
            else {"security-administrators"}
        ),
        job_function="SERVICE_ACCOUNT" if service_account else "SECURITY_ADMINISTRATOR",
        clearance=Classification.RESTRICTED,
        allowed_actions=frozenset({Action.ADMIN_MANAGE}),
        authentication_time=NOW,
        authentication_assurance=assurance,
    )


def _service(
    profile: InferenceProviderProfileVersion,
) -> tuple[InferenceAdminService, _Uow, _DecisionWriter]:
    uow = _Uow(profile)
    writer = _DecisionWriter()
    authorization = AuthorizationService(decision_writer=writer)
    return (
        InferenceAdminService(lambda: cast(InferenceAdminUnitOfWork, uow), authorization),
        uow,
        writer,
    )


def _environment() -> EnvironmentAttributes:
    return EnvironmentAttributes(requested_at=NOW)


@pytest.mark.asyncio
async def test_list_and_get_require_hardware_admin_and_revalidate_db_membership() -> None:
    profile = _proposal()
    service, uow, writer = _service(profile)
    subject = _subject(profile.workspace_id)

    values = await service.list_profiles(
        workspace_id=profile.workspace_id,
        profile_key=None,
        state=None,
        limit=20,
        subject=subject,
        environment=_environment(),
        request_id="list-profiles",
    )
    value = await service.get_profile(
        workspace_id=profile.workspace_id,
        profile_version_id=profile.provider_profile_version_id,
        subject=subject,
        environment=_environment(),
        request_id="get-profile",
    )

    assert values == (profile,)
    assert value is profile
    assert uow.memberships.checks == [
        frozenset({subject.subject_id}),
        frozenset({subject.subject_id}),
    ]
    assert all(entry[4] == Action.ADMIN_MANAGE.value for entry in writer.values)
    assert all(
        entry[0].authentication_assurance is AuthenticationAssurance.HARDWARE_WEBAUTHN
        for entry in writer.values
    )


@pytest.mark.asyncio
async def test_approval_enforces_maker_checker_and_persists_minimal_audit() -> None:
    profile = _proposal()
    service, uow, writer = _service(profile)
    checker = _subject(profile.workspace_id)

    result = await service.approve_profile(
        workspace_id=profile.workspace_id,
        profile_version_id=profile.provider_profile_version_id,
        reason="Independent approval",
        expected_version=1,
        subject=checker,
        environment=_environment(),
        request_id="approve-profile",
        idempotency_key="approval-key",
        request_hash="a" * 64,
    )

    assert result.state is InferenceProviderProfileState.APPROVED
    assert uow.profiles.writes == ["approve"]
    assert uow.memberships.checks[-1] == frozenset({checker.subject_id, profile.maker_id})
    assert uow.locks == [profile.workspace_id]
    assert uow.commits == 1
    assert len(uow.outbox.events) == 2
    event_document = repr([event.payload for event in uow.outbox.events]).lower()
    for forbidden in ("endpoint", "secret", "credential", "server_route_key", "route-a"):
        assert forbidden not in event_document
    assert writer.values[-1][4] == Action.ADMIN_MANAGE.value


@pytest.mark.asyncio
async def test_maker_cannot_approve_own_profile() -> None:
    maker_id = uuid4()
    profile = _proposal(maker_id=maker_id)
    service, uow, _ = _service(profile)
    maker = _subject(profile.workspace_id, subject_id=maker_id)

    with pytest.raises(ValidationError, match="maker"):
        await service.approve_profile(
            workspace_id=profile.workspace_id,
            profile_version_id=profile.provider_profile_version_id,
            reason="Self approval",
            expected_version=1,
            subject=maker,
            environment=_environment(),
            request_id="self-approve",
            idempotency_key="self-approve",
            request_hash="b" * 64,
        )

    assert uow.profiles.writes == []
    assert uow.commits == 0


@pytest.mark.asyncio
async def test_independent_rejection_is_persisted() -> None:
    profile = _proposal()
    service, uow, _ = _service(profile)
    checker = _subject(profile.workspace_id)

    result = await service.reject_profile(
        workspace_id=profile.workspace_id,
        profile_version_id=profile.provider_profile_version_id,
        reason="Assurance evidence rejected",
        expected_version=1,
        subject=checker,
        environment=_environment(),
        request_id="reject-profile",
        idempotency_key="reject-key",
        request_hash="c" * 64,
    )

    assert result.state is InferenceProviderProfileState.REJECTED
    assert uow.profiles.writes == ["reject"]
    assert uow.commits == 1


@pytest.mark.asyncio
async def test_revocation_is_immediate_and_does_not_require_a_new_checker() -> None:
    revoker_id = uuid4()
    profile = _proposal(maker_id=revoker_id)
    profile.approve(
        checker_id=uuid4(),
        reason="Initial approval",
        policy_decision_id=uuid4(),
        expected_version=1,
        now=NOW,
    )
    profile.events.clear()
    service, uow, _ = _service(profile)
    revoker = _subject(profile.workspace_id, subject_id=revoker_id)

    result = await service.revoke_profile(
        workspace_id=profile.workspace_id,
        profile_version_id=profile.provider_profile_version_id,
        reason="Provider assurance withdrawn",
        expected_version=2,
        subject=revoker,
        environment=_environment(),
        request_id="revoke-profile",
        idempotency_key="revoke-key",
        request_hash="d" * 64,
    )

    assert result.state is InferenceProviderProfileState.REVOKED
    assert result.revoked_by == revoker_id
    assert uow.memberships.checks == [frozenset({revoker_id})]
    assert uow.profiles.writes == ["revoke"]
    assert uow.commits == 1


@pytest.mark.asyncio
async def test_idempotent_approval_replay_does_not_write_twice() -> None:
    profile = _proposal()
    service, uow, _ = _service(profile)
    checker = _subject(profile.workspace_id)

    async def invoke() -> InferenceProviderProfileVersion:
        return await service.approve_profile(
            workspace_id=profile.workspace_id,
            profile_version_id=profile.provider_profile_version_id,
            reason="Independent approval",
            expected_version=1,
            subject=checker,
            environment=_environment(),
            request_id="approve-profile",
            idempotency_key="approval-key",
            request_hash="e" * 64,
        )

    await invoke()
    await invoke()

    assert uow.profiles.writes == ["approve"]
    assert uow.commits == 1


@pytest.mark.asyncio
async def test_service_account_and_nonhardware_admin_are_denied_before_db_access() -> None:
    profile = _proposal()
    service, uow, writer = _service(profile)

    with pytest.raises(ForbiddenError, match="service account"):
        await service.get_profile(
            workspace_id=profile.workspace_id,
            profile_version_id=profile.provider_profile_version_id,
            subject=_subject(profile.workspace_id, service_account=True),
            environment=_environment(),
            request_id="service-account-read",
        )
    assert writer.values == []

    with pytest.raises(ForbiddenError):
        await service.get_profile(
            workspace_id=profile.workspace_id,
            profile_version_id=profile.provider_profile_version_id,
            subject=_subject(
                profile.workspace_id, assurance=AuthenticationAssurance.PASSWORD_REAUTH
            ),
            environment=_environment(),
            request_id="password-read",
        )
    assert uow.contexts == []
    assert writer.values[-1][0].allowed is False


def test_browser_facing_service_exposes_no_proposal_creation() -> None:
    service, _, _ = _service(_proposal())
    assert not hasattr(service, "propose_profile")
    assert not hasattr(service, "create_profile")


@pytest.mark.asyncio
async def test_idempotency_replay_rejects_different_request_hash() -> None:
    profile = _proposal()
    profile.approve(
        checker_id=uuid4(),
        reason="Independent approval",
        policy_decision_id=uuid4(),
        expected_version=1,
        now=NOW,
    )
    service, uow, _ = _service(profile)
    checker = _subject(profile.workspace_id, subject_id=profile.checker_id)
    uow.idempotency.record = IdempotencyRecord(
        request_hash="a" * 64,
        result={
            "actor_id": str(checker.subject_id),
            "profile_version_id": str(profile.provider_profile_version_id),
            "payload_hash": profile.payload_hash,
            "state": profile.state.value,
            "version": profile.version,
        },
    )

    with pytest.raises(ConflictError, match="different request"):
        await service.approve_profile(
            workspace_id=profile.workspace_id,
            profile_version_id=profile.provider_profile_version_id,
            reason="Independent approval",
            expected_version=1,
            subject=checker,
            environment=_environment(),
            request_id="approve-profile",
            idempotency_key="approval-key",
            request_hash="b" * 64,
        )
