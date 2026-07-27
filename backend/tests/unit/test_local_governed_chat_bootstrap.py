from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4

import pytest

from datariver.application.classification_access import (
    InferenceRuntimeBinding,
    InferenceStage,
)
from datariver.application.services.inference_admin import InferenceProviderProfilePage
from datariver.application.services.local_governed_chat_bootstrap import (
    LocalGovernedChatBootstrapConfig,
    LocalGovernedChatBootstrapService,
)
from datariver.domain.authz import Classification
from datariver.domain.classification_access import ClassificationAccessPolicy
from datariver.domain.common import ConflictError, DomainEvent, ValidationError
from datariver.domain.inference_provider import (
    InferenceProviderProfileState,
    InferenceProviderProfileVersion,
)
from datariver.domain.retention import (
    RetentionPolicyState,
    RetentionPolicyVersion,
    RetentionRules,
)


class MemoryProfiles:
    def __init__(self) -> None:
        self.values: list[InferenceProviderProfileVersion] = []

    async def list(
        self,
        *,
        workspace_id: UUID,
        profile_key: str | None = None,
        state: InferenceProviderProfileState | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> InferenceProviderProfilePage:
        del cursor
        values = tuple(
            value
            for value in self.values
            if value.workspace_id == workspace_id
            and (profile_key is None or value.profile.profile_key == profile_key)
            and (state is None or value.state is state)
        )[:limit]
        return InferenceProviderProfilePage(items=values, next_cursor=None)

    async def next_profile_version(self, *, workspace_id: UUID, profile_key: str) -> int:
        return (
            max(
                (
                    value.profile_version
                    for value in self.values
                    if value.workspace_id == workspace_id
                    and value.profile.profile_key == profile_key
                ),
                default=0,
            )
            + 1
        )

    async def add(self, profile: InferenceProviderProfileVersion) -> None:
        self.values.append(profile)

    async def approve(self, profile: InferenceProviderProfileVersion) -> None:
        assert profile in self.values


class MemoryClassificationPolicies:
    def __init__(self) -> None:
        self.values: list[ClassificationAccessPolicy] = []

    async def get_active(self, *, workspace_id: UUID) -> ClassificationAccessPolicy | None:
        return next(
            (
                value
                for value in self.values
                if value.workspace_id == workspace_id and value.state.value == "ACTIVE"
            ),
            None,
        )

    async def next_policy_number(self, *, workspace_id: UUID) -> int:
        return (
            max(
                (
                    value.policy_number
                    for value in self.values
                    if value.workspace_id == workspace_id
                ),
                default=0,
            )
            + 1
        )

    async def add(self, policy: ClassificationAccessPolicy) -> None:
        self.values.append(policy)

    async def save(self, policy: ClassificationAccessPolicy) -> None:
        assert policy in self.values

    async def assert_provider_rules_eligible(
        self, *, policy: ClassificationAccessPolicy, now: datetime
    ) -> None:
        del now
        assert all(
            rule.provider_profile_version_id is not None
            for rule in policy.rules
            if rule.chat_mode.value != "DENY"
        )


class MemoryRetentionPolicies:
    def __init__(self) -> None:
        self.values: list[RetentionPolicyVersion] = []

    async def get_active(self, *, workspace_id: UUID) -> RetentionPolicyVersion | None:
        return next(
            (
                value
                for value in self.values
                if value.workspace_id == workspace_id and value.state is RetentionPolicyState.ACTIVE
            ),
            None,
        )

    async def next_policy_number(self, *, workspace_id: UUID) -> int:
        return (
            max(
                (
                    value.policy_number
                    for value in self.values
                    if value.workspace_id == workspace_id
                ),
                default=0,
            )
            + 1
        )

    async def add(self, policy: RetentionPolicyVersion) -> None:
        self.values.append(policy)

    async def save(self, policy: RetentionPolicyVersion) -> None:
        assert policy in self.values


class MemoryMemberships:
    def __init__(self) -> None:
        self.assertions: list[tuple[UUID, frozenset[UUID]]] = []

    async def assert_eligible_human_administrators(
        self, *, workspace_id: UUID, subject_ids: frozenset[UUID]
    ) -> None:
        self.assertions.append((workspace_id, subject_ids))


class MemoryOutbox:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def add_events(self, events: Sequence[DomainEvent]) -> None:
        self.events.extend(events)


class MemoryBootstrapUnitOfWork:
    def __init__(self) -> None:
        self.profiles = MemoryProfiles()
        self.classification_policies = MemoryClassificationPolicies()
        self.retention_policies = MemoryRetentionPolicies()
        self.memberships = MemoryMemberships()
        self.outbox = MemoryOutbox()
        self.context: tuple[UUID, UUID] | None = None
        self.locked_workspace_id: UUID | None = None
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
        self.context = (workspace_id, subject_id)

    async def lock_workspace(self, *, workspace_id: UUID) -> None:
        self.locked_workspace_id = workspace_id

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


def _bindings() -> tuple[InferenceRuntimeBinding, ...]:
    return tuple(
        InferenceRuntimeBinding(
            stage=stage,
            provider_profile_version_id=None,
            server_route_key=f"local-{stage.value}-v1",
            provider_identity=f"local-{stage.value}",
            model_identity=f"operator-selected-{stage.value}",
            deployment_identity=f"sha256:{stage.value}",
        )
        for stage in InferenceStage
    )


def _config() -> LocalGovernedChatBootstrapConfig:
    return LocalGovernedChatBootstrapConfig(
        jurisdiction="kr-local",
        region="mac-development",
        attestation_evidence_reference="probe-evidence-2026-07-26",
        attestation_valid_days=30,
        restricted_search_grant_maximum_days=30,
        retention_rules=RetentionRules(
            completed_operation_days=30,
            chat_content_days=30,
            audit_online_months=12,
            immutable_archive_years=1,
        ),
    )


@pytest.mark.asyncio
async def test_bootstrap_creates_and_reuses_exact_governed_chat_contracts() -> None:
    workspace_id, maker_id, checker_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    uow = MemoryBootstrapUnitOfWork()
    service = LocalGovernedChatBootstrapService(lambda: uow)

    created = await service.bootstrap(
        workspace_id=workspace_id,
        maker_id=maker_id,
        checker_id=checker_id,
        bindings=_bindings(),
        config=_config(),
        now=now,
    )

    assert len(uow.profiles.values) == 3
    assert all(
        value.state is InferenceProviderProfileState.APPROVED
        and value.maker_id == maker_id
        and value.checker_id == checker_id
        and value.profile.maximum_classification is Classification.INTERNAL
        for value in uow.profiles.values
    )
    assert uow.classification_policies.values[0].state.value == "ACTIVE"
    assert uow.retention_policies.values[0].state is RetentionPolicyState.ACTIVE
    assert created.reused_profile_count == 0
    assert uow.memberships.assertions == [(workspace_id, frozenset({maker_id, checker_id}))]
    assert uow.context == (workspace_id, maker_id)
    assert uow.locked_workspace_id == workspace_id
    assert uow.commits == 1

    event_count = len(uow.outbox.events)
    reused = await service.bootstrap(
        workspace_id=workspace_id,
        maker_id=maker_id,
        checker_id=checker_id,
        bindings=_bindings(),
        config=_config(),
        now=now + timedelta(minutes=1),
    )

    assert reused.reused_profile_count == 3
    assert reused.reused_classification_policy is True
    assert reused.reused_retention_policy is True
    assert reused.composition_profile_version_id == created.composition_profile_version_id
    assert len(uow.profiles.values) == 3
    assert len(uow.outbox.events) == event_count
    assert uow.commits == 2


@pytest.mark.asyncio
async def test_bootstrap_supersedes_policy_and_profiles_for_confidential_chat() -> None:
    workspace_id, maker_id, checker_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    uow = MemoryBootstrapUnitOfWork()
    service = LocalGovernedChatBootstrapService(lambda: uow)

    initial = await service.bootstrap(
        workspace_id=workspace_id,
        maker_id=maker_id,
        checker_id=checker_id,
        bindings=_bindings(),
        config=_config(),
        now=now,
    )
    updated = await service.bootstrap(
        workspace_id=workspace_id,
        maker_id=maker_id,
        checker_id=checker_id,
        bindings=_bindings(),
        config=replace(
            _config(),
            maximum_classification=Classification.CONFIDENTIAL,
        ),
        now=now + timedelta(minutes=1),
    )

    assert updated.classification_policy_id != initial.classification_policy_id
    assert len(uow.profiles.values) == 6
    assert all(
        value.profile.maximum_classification is Classification.CONFIDENTIAL
        for value in uow.profiles.values[-3:]
    )
    assert uow.classification_policies.values[0].state.value == "SUPERSEDED"
    active = uow.classification_policies.values[1]
    assert active.state.value == "ACTIVE"
    confidential = next(
        rule for rule in active.rules if rule.classification is Classification.CONFIDENTIAL
    )
    assert confidential.chat_mode.value == "INTERNAL_APPROVED_ONLY"
    assert confidential.provider_profile_version_id is not None


@pytest.mark.asyncio
async def test_bootstrap_rejects_incomplete_runtime_stage_set() -> None:
    with pytest.raises(ConflictError, match="exactly one"):
        await LocalGovernedChatBootstrapService(lambda: MemoryBootstrapUnitOfWork()).bootstrap(
            workspace_id=uuid4(),
            maker_id=uuid4(),
            checker_id=uuid4(),
            bindings=_bindings()[:-1],
            config=_config(),
            now=datetime.now(UTC),
        )


def test_bootstrap_config_rejects_missing_attestation_evidence() -> None:
    with pytest.raises(ValidationError, match="attestation evidence"):
        LocalGovernedChatBootstrapConfig(
            jurisdiction="kr-local",
            region="mac-development",
            attestation_evidence_reference=" ",
            attestation_valid_days=30,
            restricted_search_grant_maximum_days=30,
            retention_rules=_config().retention_rules,
        )
