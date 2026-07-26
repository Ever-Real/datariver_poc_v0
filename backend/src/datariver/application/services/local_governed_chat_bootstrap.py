from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from datariver.application.classification_access import (
    InferenceRuntimeBinding,
    InferenceStage,
)
from datariver.application.services.inference_admin import InferenceProviderProfilePage
from datariver.domain.authz import Classification
from datariver.domain.classification_access import (
    ChatMode,
    ClassificationAccessPolicy,
    ClassificationAccessRule,
    PolicyDecision,
    SearchMode,
)
from datariver.domain.common import (
    ConflictError,
    DomainEvent,
    ValidationError,
    canonical_json_hash,
    uuid7,
)
from datariver.domain.inference_provider import (
    InferenceProviderProfile,
    InferenceProviderProfileState,
    InferenceProviderProfileVersion,
    ProviderAttestation,
    ProviderKind,
)
from datariver.domain.retention import (
    GovernanceDecision,
    RetentionPolicyState,
    RetentionPolicyVersion,
    RetentionRules,
)


@dataclass(frozen=True, slots=True)
class LocalGovernedChatBootstrapConfig:
    jurisdiction: str
    region: str
    attestation_evidence_reference: str
    attestation_valid_days: int
    restricted_search_grant_maximum_days: int
    retention_rules: RetentionRules

    def __post_init__(self) -> None:
        if not self.jurisdiction.strip() or not self.region.strip():
            raise ValidationError("Local governance jurisdiction and region are required.")
        if not self.attestation_evidence_reference.strip():
            raise ValidationError("Local governance attestation evidence is required.")
        if not 1 <= self.attestation_valid_days <= 365:
            raise ValidationError("Local governance attestation validity must be 1-365 days.")
        if not 1 <= self.restricted_search_grant_maximum_days <= 365:
            raise ValidationError("The RESTRICTED Search grant maximum must be 1-365 days.")


@dataclass(frozen=True, slots=True)
class LocalGovernedChatBootstrapResult:
    composition_profile_version_id: UUID
    embedding_profile_version_id: UUID
    reranker_profile_version_id: UUID
    classification_policy_id: UUID
    retention_policy_id: UUID
    reused_profile_count: int
    reused_classification_policy: bool
    reused_retention_policy: bool


class LocalInferenceProfileRepository(Protocol):
    async def list(
        self,
        *,
        workspace_id: UUID,
        profile_key: str | None = None,
        state: InferenceProviderProfileState | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> InferenceProviderProfilePage: ...

    async def next_profile_version(self, *, workspace_id: UUID, profile_key: str) -> int: ...

    async def add(self, profile: InferenceProviderProfileVersion) -> None: ...

    async def approve(self, profile: InferenceProviderProfileVersion) -> None: ...


class LocalClassificationPolicyRepository(Protocol):
    async def get_active(self, *, workspace_id: UUID) -> ClassificationAccessPolicy | None: ...

    async def next_policy_number(self, *, workspace_id: UUID) -> int: ...

    async def add(self, policy: ClassificationAccessPolicy) -> None: ...

    async def save(self, policy: ClassificationAccessPolicy) -> None: ...

    async def assert_provider_rules_eligible(
        self, *, policy: ClassificationAccessPolicy, now: datetime
    ) -> None: ...


class LocalRetentionPolicyRepository(Protocol):
    async def get_active(self, *, workspace_id: UUID) -> RetentionPolicyVersion | None: ...

    async def next_policy_number(self, *, workspace_id: UUID) -> int: ...

    async def add(self, policy: RetentionPolicyVersion) -> None: ...

    async def save(self, policy: RetentionPolicyVersion) -> None: ...


class LocalHumanAdministratorRepository(Protocol):
    async def assert_eligible_human_administrators(
        self, *, workspace_id: UUID, subject_ids: frozenset[UUID]
    ) -> None: ...


class LocalBootstrapOutbox(Protocol):
    async def add_events(self, events: Sequence[DomainEvent]) -> None: ...


class LocalGovernedChatBootstrapUnitOfWork(Protocol):
    @property
    def profiles(self) -> LocalInferenceProfileRepository: ...

    @property
    def classification_policies(self) -> LocalClassificationPolicyRepository: ...

    @property
    def retention_policies(self) -> LocalRetentionPolicyRepository: ...

    @property
    def memberships(self) -> LocalHumanAdministratorRepository: ...

    @property
    def outbox(self) -> LocalBootstrapOutbox: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None: ...

    async def lock_workspace(self, *, workspace_id: UUID) -> None: ...

    async def flush(self) -> None: ...

    async def commit(self) -> None: ...


class LocalGovernedChatBootstrapService:
    """Idempotent, development-only maker/checker bootstrap over governed aggregates."""

    def __init__(
        self,
        uow_factory: Callable[[], LocalGovernedChatBootstrapUnitOfWork],
    ) -> None:
        self._uow_factory = uow_factory

    async def bootstrap(
        self,
        *,
        workspace_id: UUID,
        maker_id: UUID,
        checker_id: UUID,
        bindings: tuple[InferenceRuntimeBinding, ...],
        config: LocalGovernedChatBootstrapConfig,
        now: datetime,
    ) -> LocalGovernedChatBootstrapResult:
        if maker_id == checker_id:
            raise ValidationError("Local governance maker and checker must be different.")
        by_stage = _validated_bindings(bindings)
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=maker_id)
            await uow.lock_workspace(workspace_id=workspace_id)
            await uow.memberships.assert_eligible_human_administrators(
                workspace_id=workspace_id,
                subject_ids=frozenset({maker_id, checker_id}),
            )

            profile_ids: dict[InferenceStage, UUID] = {}
            reused_profile_count = 0
            for stage in InferenceStage:
                profile, reused = await self._ensure_profile(
                    uow=uow,
                    workspace_id=workspace_id,
                    maker_id=maker_id,
                    checker_id=checker_id,
                    binding=by_stage[stage],
                    config=config,
                    now=now,
                )
                profile_ids[stage] = profile.provider_profile_version_id
                reused_profile_count += int(reused)

            desired_rules = _classification_rules(profile_ids)
            classification_policy, reused_classification = await self._ensure_classification_policy(
                uow=uow,
                workspace_id=workspace_id,
                maker_id=maker_id,
                checker_id=checker_id,
                config=config,
                rules=desired_rules,
                now=now,
            )
            retention_policy, reused_retention = await self._ensure_retention_policy(
                uow=uow,
                workspace_id=workspace_id,
                maker_id=maker_id,
                checker_id=checker_id,
                rules=config.retention_rules,
                now=now,
            )
            await uow.commit()

        return LocalGovernedChatBootstrapResult(
            composition_profile_version_id=profile_ids[InferenceStage.COMPOSITION],
            embedding_profile_version_id=profile_ids[InferenceStage.EMBEDDING],
            reranker_profile_version_id=profile_ids[InferenceStage.RERANKER],
            classification_policy_id=classification_policy.policy_id,
            retention_policy_id=retention_policy.policy_id,
            reused_profile_count=reused_profile_count,
            reused_classification_policy=reused_classification,
            reused_retention_policy=reused_retention,
        )

    async def _ensure_profile(
        self,
        *,
        uow: LocalGovernedChatBootstrapUnitOfWork,
        workspace_id: UUID,
        maker_id: UUID,
        checker_id: UUID,
        binding: InferenceRuntimeBinding,
        config: LocalGovernedChatBootstrapConfig,
        now: datetime,
    ) -> tuple[InferenceProviderProfileVersion, bool]:
        profile_key = f"local-governed-chat-{binding.stage.value}"
        page = await uow.profiles.list(
            workspace_id=workspace_id,
            profile_key=profile_key,
            state=InferenceProviderProfileState.APPROVED,
            limit=100,
            cursor=None,
        )
        for candidate in page.items:
            if _profile_matches(
                candidate,
                binding=binding,
                config=config,
                now=now,
            ):
                return candidate, True

        attestation_expiry = now + timedelta(days=config.attestation_valid_days)
        base_evidence = {
            "contract": "DATARIVER_LOCAL_GOVERNED_CHAT_ATTESTATION_V1",
            "evidence_reference": config.attestation_evidence_reference,
            "stage": binding.stage.value,
            "server_route_key": binding.server_route_key,
            "provider_identity": binding.provider_identity,
            "model_identity": binding.model_identity,
            "deployment_identity": binding.deployment_identity,
        }
        profile = InferenceProviderProfile(
            profile_key=profile_key,
            server_route_key=binding.server_route_key,
            kind=ProviderKind.INTERNAL,
            provider_identity=binding.provider_identity,
            model_identity=binding.model_identity,
            deployment_identity=binding.deployment_identity,
            jurisdiction=config.jurisdiction,
            region=config.region,
            maximum_classification=Classification.INTERNAL,
            residency_attestation=ProviderAttestation(
                fingerprint=canonical_json_hash({**base_evidence, "claim": "residency"}),
                observed_at=now,
                expires_at=attestation_expiry,
            ),
            zero_retention_attestation=ProviderAttestation(
                fingerprint=canonical_json_hash({**base_evidence, "claim": "zero-retention"}),
                observed_at=now,
                expires_at=attestation_expiry,
            ),
        )
        proposal = InferenceProviderProfileVersion.propose(
            workspace_id=workspace_id,
            profile_version=await uow.profiles.next_profile_version(
                workspace_id=workspace_id, profile_key=profile_key
            ),
            profile=profile,
            maker_id=maker_id,
            reason="Approved local-development runtime binding bootstrap.",
            policy_decision_id=uuid7(),
            now=now,
        )
        await uow.profiles.add(proposal)
        await uow.flush()
        proposal.approve(
            checker_id=checker_id,
            reason="Independent local-development runtime binding check.",
            policy_decision_id=uuid7(),
            expected_version=proposal.version,
            now=now,
        )
        await uow.profiles.approve(proposal)
        await uow.outbox.add_events(proposal.events)
        await uow.flush()
        return proposal, False

    async def _ensure_classification_policy(
        self,
        *,
        uow: LocalGovernedChatBootstrapUnitOfWork,
        workspace_id: UUID,
        maker_id: UUID,
        checker_id: UUID,
        config: LocalGovernedChatBootstrapConfig,
        rules: tuple[ClassificationAccessRule, ...],
        now: datetime,
    ) -> tuple[ClassificationAccessPolicy, bool]:
        active = await uow.classification_policies.get_active(workspace_id=workspace_id)
        if active is not None:
            if (
                active.required_jurisdiction == config.jurisdiction
                and active.restricted_search_grant_maximum_days
                == config.restricted_search_grant_maximum_days
                and active.rules == rules
            ):
                return active, True
            raise ConflictError(
                "An active classification policy exists with a different governed contract."
            )
        policy = ClassificationAccessPolicy.propose(
            workspace_id=workspace_id,
            policy_number=await uow.classification_policies.next_policy_number(
                workspace_id=workspace_id
            ),
            required_jurisdiction=config.jurisdiction,
            restricted_search_grant_maximum_days=(config.restricted_search_grant_maximum_days),
            rules=rules,
            requester_id=maker_id,
            reason="Enable bounded local-development governed Chat.",
            policy_decision_id=uuid7(),
        )
        await uow.classification_policies.add(policy)
        await uow.flush()
        await uow.classification_policies.assert_provider_rules_eligible(policy=policy, now=now)
        policy.decide(
            decision=PolicyDecision.APPROVED,
            actor_id=checker_id,
            reason="Independent local-development classification policy check.",
            policy_decision_id=uuid7(),
            expected_version=policy.version,
            now=now,
        )
        await uow.classification_policies.save(policy)
        await uow.outbox.add_events(policy.events)
        await uow.flush()
        return policy, False

    async def _ensure_retention_policy(
        self,
        *,
        uow: LocalGovernedChatBootstrapUnitOfWork,
        workspace_id: UUID,
        maker_id: UUID,
        checker_id: UUID,
        rules: RetentionRules,
        now: datetime,
    ) -> tuple[RetentionPolicyVersion, bool]:
        active = await uow.retention_policies.get_active(workspace_id=workspace_id)
        if active is not None:
            if active.rules == rules and active.state is RetentionPolicyState.ACTIVE:
                return active, True
            raise ConflictError(
                "An active retention policy exists with a different governed contract."
            )
        policy = RetentionPolicyVersion.propose(
            workspace_id=workspace_id,
            policy_number=await uow.retention_policies.next_policy_number(
                workspace_id=workspace_id
            ),
            rules=rules,
            requester_id=maker_id,
            reason="Local-development persisted Chat E2E retention contract.",
            policy_decision_id=uuid7(),
        )
        await uow.retention_policies.add(policy)
        await uow.flush()
        policy.decide(
            decision=GovernanceDecision.APPROVED,
            actor_id=checker_id,
            reason="Independent local-development retention policy check.",
            policy_decision_id=uuid7(),
            expected_version=policy.version,
            now=now,
        )
        await uow.retention_policies.save(policy)
        await uow.outbox.add_events(policy.events)
        await uow.flush()
        return policy, False


def _validated_bindings(
    bindings: tuple[InferenceRuntimeBinding, ...],
) -> dict[InferenceStage, InferenceRuntimeBinding]:
    by_stage = {binding.stage: binding for binding in bindings}
    if len(bindings) != len(InferenceStage) or set(by_stage) != set(InferenceStage):
        raise ConflictError(
            "Local governed Chat requires exactly one composition, embedding and reranker binding."
        )
    return by_stage


def _classification_rules(
    profile_ids: dict[InferenceStage, UUID],
) -> tuple[ClassificationAccessRule, ...]:
    enabled = {
        "provider_profile_version_id": profile_ids[InferenceStage.COMPOSITION],
        "embedding_provider_profile_version_id": profile_ids[InferenceStage.EMBEDDING],
        "reranker_provider_profile_version_id": profile_ids[InferenceStage.RERANKER],
    }
    return (
        ClassificationAccessRule(
            classification=Classification.PUBLIC,
            search_mode=SearchMode.ABAC,
            chat_mode=ChatMode.INTERNAL_APPROVED_ONLY,
            **enabled,
        ),
        ClassificationAccessRule(
            classification=Classification.INTERNAL,
            search_mode=SearchMode.ABAC,
            chat_mode=ChatMode.INTERNAL_APPROVED_ONLY,
            **enabled,
        ),
        ClassificationAccessRule(
            classification=Classification.CONFIDENTIAL,
            search_mode=SearchMode.ABAC,
            chat_mode=ChatMode.DENY,
        ),
        ClassificationAccessRule(
            classification=Classification.RESTRICTED,
            search_mode=SearchMode.EXPLICIT_GRANT_ONLY,
            chat_mode=ChatMode.DENY,
        ),
    )


def _profile_matches(
    candidate: object,
    *,
    binding: InferenceRuntimeBinding,
    config: LocalGovernedChatBootstrapConfig,
    now: datetime,
) -> bool:
    if not isinstance(candidate, InferenceProviderProfileVersion):
        return False
    profile = candidate.profile
    base_evidence = {
        "contract": "DATARIVER_LOCAL_GOVERNED_CHAT_ATTESTATION_V1",
        "evidence_reference": config.attestation_evidence_reference,
        "stage": binding.stage.value,
        "server_route_key": binding.server_route_key,
        "provider_identity": binding.provider_identity,
        "model_identity": binding.model_identity,
        "deployment_identity": binding.deployment_identity,
    }
    return (
        candidate.state is InferenceProviderProfileState.APPROVED
        and profile.server_route_key == binding.server_route_key
        and profile.kind is ProviderKind.INTERNAL
        and profile.provider_identity == binding.provider_identity
        and profile.model_identity == binding.model_identity
        and profile.deployment_identity == binding.deployment_identity
        and profile.jurisdiction == config.jurisdiction
        and profile.region == config.region
        and profile.maximum_classification is Classification.INTERNAL
        and profile.residency_attestation.fingerprint
        == canonical_json_hash({**base_evidence, "claim": "residency"})
        and profile.zero_retention_attestation.fingerprint
        == canonical_json_hash({**base_evidence, "claim": "zero-retention"})
        and profile.attestations_current(now=now)
    )
