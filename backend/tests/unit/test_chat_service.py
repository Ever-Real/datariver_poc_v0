from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Any, Self, cast
from uuid import UUID, uuid4

import pytest

from datariver.application.classification_access import (
    ClassificationAccessPosture,
    ClassificationAccessResolver,
    ClassificationAccessSnapshot,
    ClassificationRuleRecord,
    InferenceRuntimeBinding,
    InferenceStage,
    ProviderProfileRecord,
)
from datariver.application.dto import (
    CatalogAssetDetail,
    CatalogAssetIndex,
    CatalogPage,
    ChatCompositionAudit,
    ChatDraft,
    ChatEvidence,
    ChatEvidenceRanking,
    ChatExchange,
    ChatRetentionBinding,
    ChatRouteDecision,
    ChatVectorSearchResult,
    ChatWorkflowEvent,
    KnowledgeEvidenceCandidate,
    default_chat_route,
)
from datariver.application.evidence import build_evidence_chunk, evidence_chunk_is_valid
from datariver.application.ports import ChatStore, RetentionPolicyRepository
from datariver.application.services.authorization import AuthorizationService, NullDecisionWriter
from datariver.application.services.chat import (
    GENERAL_KNOWLEDGE_PREFIX,
    UNVERIFIABLE_ANSWER,
    ChatService,
)
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.chat import (
    MAXIMUM_CHAT_VECTOR_CANDIDATES,
    MAXIMUM_CHAT_VECTOR_TEXT_CHARACTERS,
    ChatAdapterState,
    ChatRetrievalMode,
    ChatWorkflowStage,
    ChatWorkflowStatus,
)
from datariver.domain.classification_access import ChatMode, SearchMode
from datariver.domain.common import ConflictError, ForbiddenError, RateLimitError, uuid7
from datariver.domain.retention import (
    GovernanceDecision,
    RetentionPolicyState,
    RetentionPolicyVersion,
    RetentionRules,
)


class FakeIndex:
    def __init__(
        self,
        item: CatalogAssetIndex,
        *,
        detail_item: CatalogAssetIndex | None = None,
    ) -> None:
        self.item = item
        self.detail_item = detail_item or item
        self.search_subject: SubjectAttributes | None = None

    async def search(
        self,
        *,
        subject: SubjectAttributes,
        access: object,
        query: str,
        filters: dict[str, Any],
        cursor: str | None,
        limit: int,
    ) -> CatalogPage:
        self.search_subject = subject
        del access, query, filters, cursor, limit
        return CatalogPage(items=(self.item,), next_cursor=None, observed_at=datetime.now(UTC))

    async def get_authorized_asset(
        self, *, subject: SubjectAttributes, access: object, asset_id: UUID
    ) -> CatalogAssetDetail | None:
        del subject, access
        if asset_id != self.item.asset_id:
            return None
        return CatalogAssetDetail(
            index=self.detail_item,
            ownership=(),
            glossary_terms=(),
            tags=self.detail_item.tags,
            schema_fields=(),
            quality={},
            raw_version=self.detail_item.source_version,
            observed_at=self.detail_item.observed_at,
        )

    async def get_authorized_assets_by_external_urns(
        self,
        *,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        external_urns: Sequence[str],
    ) -> Sequence[CatalogAssetIndex]:
        del subject, access
        return (self.item,) if self.item.external_urn in external_urns else ()


class RejectingBudgetGuard:
    def __init__(self) -> None:
        self.reservations = 0

    async def reserve(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        policy_scope: str,
        estimated_tokens: int,
        request_limit: int,
        token_limit: int,
        window_seconds: int,
    ) -> None:
        del (
            workspace_id,
            subject_id,
            policy_scope,
            estimated_tokens,
            request_limit,
            token_limit,
            window_seconds,
        )
        self.reservations += 1
        raise RateLimitError(
            "Chat budget exhausted.",
            details={"retry_after_seconds": 60},
        )


class FakeSessionOwnership:
    def __init__(self, owner_id: UUID | None = None) -> None:
        self.owner_id = owner_id
        self.calls = 0

    async def get_session_owner(
        self,
        *,
        workspace_id: UUID,
        session_id: UUID,
    ) -> UUID | None:
        del workspace_id, session_id
        self.calls += 1
        return self.owner_id


class PassthroughSubjectAccess:
    def __init__(self, refreshed: SubjectAttributes | None = None) -> None:
        self.refreshed = refreshed
        self.calls = 0

    async def refresh_subject(
        self,
        *,
        subject: SubjectAttributes,
        now: datetime,
    ) -> SubjectAttributes:
        del now
        self.calls += 1
        return self.refreshed or subject


def chat_service(**kwargs: Any) -> ChatService:
    return ChatService(
        session_ownership=FakeSessionOwnership(),
        subject_access=PassthroughSubjectAccess(),
        **kwargs,
    )


class FixedClassificationAccess:
    def __init__(self, *snapshots: ClassificationAccessSnapshot) -> None:
        self._snapshots = snapshots
        self.calls = 0

    async def resolve(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        now: datetime,
    ) -> ClassificationAccessSnapshot:
        del workspace_id, subject_id, now
        index = min(self.calls, len(self._snapshots) - 1)
        self.calls += 1
        return self._snapshots[index]


def inference_binding(
    stage: InferenceStage,
    profile_id: UUID,
) -> InferenceRuntimeBinding:
    return InferenceRuntimeBinding(
        stage=stage,
        provider_profile_version_id=profile_id,
        server_route_key=f"test-{stage.value}-route-v1",
        provider_identity=f"test-{stage.value}-provider",
        model_identity=f"test-{stage.value}-model",
        deployment_identity=f"test-{stage.value}-deployment",
    )


def mismatched_binding(
    binding: InferenceRuntimeBinding,
    *,
    field: str,
    value: str,
) -> InferenceRuntimeBinding:
    if field == "server_route_key":
        return replace(binding, server_route_key=value)
    if field == "provider_identity":
        return replace(binding, provider_identity=value)
    if field == "model_identity":
        return replace(binding, model_identity=value)
    if field == "deployment_identity":
        return replace(binding, deployment_identity=value)
    raise AssertionError(f"Unsupported binding field: {field}")


def governed_chat_access(
    *runtime_bindings: InferenceRuntimeBinding,
) -> ClassificationAccessSnapshot:
    by_stage = {binding.stage: binding for binding in runtime_bindings}
    composition = by_stage.get(InferenceStage.COMPOSITION) or inference_binding(
        InferenceStage.COMPOSITION,
        uuid4(),
    )
    by_stage[InferenceStage.COMPOSITION] = composition
    embedding = by_stage.get(InferenceStage.EMBEDDING)
    reranker = by_stage.get(InferenceStage.RERANKER)
    now = datetime.now(UTC)
    profiles = tuple(
        ProviderProfileRecord(
            provider_profile_version_id=cast(UUID, binding.provider_profile_version_id),
            state="APPROVED",
            kind="INTERNAL",
            server_route_key=binding.server_route_key,
            provider_identity=binding.provider_identity,
            model_identity=binding.model_identity,
            deployment_identity=binding.deployment_identity,
            jurisdiction="jurisdiction-a",
            maximum_classification=Classification.INTERNAL,
            residency_attestation_observed_at=now - timedelta(hours=1),
            residency_attestation_expires_at=now + timedelta(hours=8),
            zero_retention_attestation_observed_at=now - timedelta(hours=1),
            zero_retention_attestation_expires_at=now + timedelta(hours=8),
        )
        for binding in by_stage.values()
    )
    return ClassificationAccessSnapshot(
        posture=ClassificationAccessPosture.GOVERNED,
        policy_id=uuid4(),
        policy_hash="a" * 64,
        policy_version=2,
        required_jurisdiction="jurisdiction-a",
        authorization_generation=3,
        rules=(
            ClassificationRuleRecord(
                Classification.PUBLIC,
                SearchMode.ABAC,
                ChatMode.INTERNAL_APPROVED_ONLY,
                composition.provider_profile_version_id,
                (embedding.provider_profile_version_id if embedding is not None else None),
                (reranker.provider_profile_version_id if reranker is not None else None),
            ),
            ClassificationRuleRecord(
                Classification.INTERNAL,
                SearchMode.ABAC,
                ChatMode.INTERNAL_APPROVED_ONLY,
                composition.provider_profile_version_id,
                (embedding.provider_profile_version_id if embedding is not None else None),
                (reranker.provider_profile_version_id if reranker is not None else None),
            ),
            ClassificationRuleRecord(
                Classification.CONFIDENTIAL,
                SearchMode.DENY,
                ChatMode.DENY,
                None,
            ),
            ClassificationRuleRecord(
                Classification.RESTRICTED,
                SearchMode.DENY,
                ChatMode.DENY,
                None,
            ),
        ),
        restricted_resource_ids=frozenset(),
        restricted_system_ids=frozenset(),
        restricted_domain_ids=frozenset(),
        nearest_validity_boundary=None,
        provider_profiles=profiles,
    )


def test_chat_retrieval_translates_governed_chat_modes_into_sql_search_modes() -> None:
    profile_id = uuid4()
    access = ClassificationAccessSnapshot(
        posture=ClassificationAccessPosture.GOVERNED,
        policy_id=uuid4(),
        policy_hash="a" * 64,
        policy_version=2,
        required_jurisdiction="jurisdiction-a",
        authorization_generation=3,
        rules=(
            ClassificationRuleRecord(
                Classification.PUBLIC,
                SearchMode.ABAC,
                ChatMode.INTERNAL_APPROVED_ONLY,
                profile_id,
            ),
            ClassificationRuleRecord(
                Classification.INTERNAL,
                SearchMode.ABAC,
                ChatMode.DENY,
                None,
            ),
            ClassificationRuleRecord(
                Classification.CONFIDENTIAL,
                SearchMode.ABAC,
                ChatMode.INTERNAL_APPROVED_ONLY,
                profile_id,
            ),
            ClassificationRuleRecord(
                Classification.RESTRICTED,
                SearchMode.EXPLICIT_GRANT_ONLY,
                ChatMode.DENY,
                None,
            ),
        ),
        restricted_resource_ids=frozenset({uuid4()}),
        restricted_system_ids=frozenset(),
        restricted_domain_ids=frozenset(),
        nearest_validity_boundary=None,
    )
    transformed = ChatService._chat_retrieval_access(
        access,
        subject=replace(chat_subject(uuid4()), clearance=Classification.RESTRICTED),
    )

    assert transformed.rule_for(Classification.PUBLIC).search_mode is SearchMode.ABAC
    assert transformed.rule_for(Classification.INTERNAL).search_mode is SearchMode.DENY
    assert transformed.rule_for(Classification.CONFIDENTIAL).search_mode is SearchMode.ABAC
    assert transformed.rule_for(Classification.RESTRICTED).search_mode is SearchMode.DENY
    assert transformed.restricted_resource_ids == frozenset()


class FakeChatStore:
    def __init__(self) -> None:
        self.saved_evidence: tuple[ChatEvidence, ...] = ()
        self.saved_retention: ChatRetentionBinding | None = None
        self.saved_composition_audit: ChatCompositionAudit | None = None

    async def save_exchange(
        self,
        *,
        workspace_id: UUID,
        owner_id: UUID,
        session_id: UUID | None,
        question: str,
        answer: str,
        evidence: Sequence[ChatEvidence],
        policy_decision_id: UUID,
        retention: ChatRetentionBinding,
        route: ChatRouteDecision | None = None,
        workflow: Sequence[ChatWorkflowEvent] = (),
        evidence_ranking: Sequence[ChatEvidenceRanking] = (),
        composition_audit: ChatCompositionAudit | None = None,
    ) -> ChatExchange:
        del workspace_id, owner_id, question, policy_decision_id
        self.saved_evidence = tuple(evidence)
        self.saved_retention = retention
        self.saved_composition_audit = composition_audit
        return ChatExchange(
            session_id=session_id or uuid7(),
            request_message_id=uuid7(),
            response_message_id=uuid7(),
            answer=answer,
            evidence=self.saved_evidence,
            route=route or default_chat_route(),
            workflow=tuple(workflow),
            evidence_ranking=tuple(evidence_ranking),
        )


def active_retention_policy(
    workspace_id: UUID, *, chat_content_days: int = 90
) -> RetentionPolicyVersion:
    policy = RetentionPolicyVersion.propose(
        workspace_id=workspace_id,
        policy_number=1,
        rules=RetentionRules(
            completed_operation_days=30,
            chat_content_days=chat_content_days,
            audit_online_months=13,
            immutable_archive_years=7,
        ),
        requester_id=uuid4(),
        reason="Approved operating retention",
        policy_decision_id=uuid4(),
    )
    policy.decide(
        decision=GovernanceDecision.APPROVED,
        actor_id=uuid4(),
        reason="Independent retention approval",
        policy_decision_id=uuid4(),
        expected_version=1,
        now=datetime(2026, 7, 17, tzinfo=UTC),
    )
    assert policy.state is RetentionPolicyState.ACTIVE
    return policy


class FakeRetentionPolicies:
    def __init__(self, *, available: bool = True, chat_content_days: int = 90) -> None:
        self.available = available
        self.chat_content_days = chat_content_days

    async def get_active_for_update(
        self,
        *,
        workspace_id: UUID,
        excluding_policy_id: UUID | None = None,
    ) -> RetentionPolicyVersion | None:
        del excluding_policy_id
        if not self.available:
            return None
        return active_retention_policy(
            workspace_id,
            chat_content_days=self.chat_content_days,
        )


class FakeChatPersistenceUnitOfWork:
    def __init__(
        self,
        store: FakeChatStore,
        *,
        policy_available: bool = True,
        chat_content_days: int = 90,
    ) -> None:
        self.chats = cast(ChatStore, store)
        self.retention_policies = cast(
            RetentionPolicyRepository,
            FakeRetentionPolicies(
                available=policy_available,
                chat_content_days=chat_content_days,
            ),
        )
        self.committed = False
        self.rolled_back = False
        self.context: tuple[UUID, UUID] | None = None
        self.locked_workspace: UUID | None = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_value, traceback
        if exc_type is not None or not self.committed:
            self.rolled_back = True

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def lock_retention_workspace(self, *, workspace_id: UUID) -> None:
        self.locked_workspace = workspace_id

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None:
        self.context = (workspace_id, subject_id)

    async def transaction_time(self) -> datetime:
        return datetime(2026, 7, 17, 12, 0, tzinfo=UTC)


def chat_uow_factory(
    store: FakeChatStore,
    *,
    policy_available: bool = True,
    chat_content_days: int = 90,
) -> Callable[[], FakeChatPersistenceUnitOfWork]:
    return lambda: FakeChatPersistenceUnitOfWork(
        store,
        policy_available=policy_available,
        chat_content_days=chat_content_days,
    )


async def test_chat_persistence_uses_the_active_policy_duration() -> None:
    workspace_id = uuid4()
    store = FakeChatStore()
    service = chat_service(
        catalog_index=FakeIndex(asset(workspace_id)),
        uow_factory=chat_uow_factory(store, chat_content_days=37),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    )

    await service.query(
        workspace_id=workspace_id,
        subject=chat_subject(workspace_id),
        session_id=None,
        question="정책 결속을 확인해줘",
        maximum_evidence=1,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-retention-binding",
    )

    assert store.saved_retention is not None
    assert store.saved_retention.chat_content_days == 37
    assert store.saved_retention.policy_hash != ""


async def test_chat_budget_exhaustion_fails_before_retrieval_and_provider_calls() -> None:
    workspace_id = uuid4()
    index = FakeIndex(asset(workspace_id))
    guard = RejectingBudgetGuard()
    store = FakeChatStore()
    service = chat_service(
        catalog_index=index,
        uow_factory=chat_uow_factory(store),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
        budget_guard=guard,
        request_limit_per_minute=1,
        token_limit_per_minute=2_048,
    )

    with pytest.raises(RateLimitError, match="budget exhausted"):
        await service.query(
            workspace_id=workspace_id,
            subject=chat_subject(workspace_id),
            session_id=None,
            question="이 요청은 예약 단계에서 거부되어야 한다",
            maximum_evidence=1,
            environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
            request_id="request-budget-denied",
        )

    assert guard.reservations == 1
    assert index.search_subject is None
    assert store.saved_retention is None


async def test_chat_persistence_fails_closed_without_an_active_policy() -> None:
    workspace_id = uuid4()
    store = FakeChatStore()
    uow = FakeChatPersistenceUnitOfWork(store, policy_available=False)
    service = chat_service(
        catalog_index=FakeIndex(asset(workspace_id)),
        uow_factory=lambda: uow,
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    )

    with pytest.raises(ConflictError, match="active retention policy"):
        await service.query(
            workspace_id=workspace_id,
            subject=chat_subject(workspace_id),
            session_id=None,
            question="정책 없는 저장을 거부해줘",
            maximum_evidence=1,
            environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
            request_id="request-missing-retention",
        )

    assert store.saved_retention is None
    assert uow.committed is False
    assert uow.rolled_back is True


async def test_chat_development_ephemeral_exchange_never_persists_without_policy() -> None:
    workspace_id = uuid4()
    store = FakeChatStore()
    uow = FakeChatPersistenceUnitOfWork(store, policy_available=False)
    service = chat_service(
        catalog_index=FakeIndex(asset(workspace_id)),
        uow_factory=lambda: uow,
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
        allow_ephemeral_without_retention=True,
    )

    exchange = await service.query(
        workspace_id=workspace_id,
        subject=chat_subject(workspace_id),
        session_id=None,
        question="개발 검증용 근거를 알려줘",
        maximum_evidence=1,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-ephemeral-chat",
    )

    assert exchange.persistence == "EPHEMERAL_NO_STORE"
    assert exchange.evidence
    assert store.saved_retention is None
    assert uow.committed is False
    assert uow.rolled_back is True


class FakeKnowledgeEvidence:
    def __init__(
        self,
        workspace_id: UUID,
        *,
        tamper_hash: bool = False,
        drift_on_refresh: bool = False,
    ) -> None:
        self.workspace_id = workspace_id
        self.tamper_hash = tamper_hash
        self.drift_on_refresh = drift_on_refresh
        evidence = build_evidence_chunk(
            workspace_id=workspace_id,
            resource_id=uuid4(),
            classification=Classification.INTERNAL,
            system_id=None,
            domain_id=None,
            owner_department_id=None,
            name="EUV lithography",
            description="Critical equipment dependency",
            source_locator="knowledge://graphs/g/releases/r/nodes/n",
            source_version="f" * 64,
            effective_from=datetime.now(UTC),
            extraction_method="KNOWLEDGE_RELEASE_NODE_V1",
            source_type="KNOWLEDGE_NODE",
        )
        if self.tamper_hash:
            evidence = replace(evidence, content_hash="0" * 64)
        self.candidate = KnowledgeEvidenceCandidate(
            evidence=evidence,
            graph_id=uuid4(),
            classification=Classification.INTERNAL,
        )

    async def search_active_nodes(
        self,
        *,
        workspace_id: UUID,
        query: str,
        maximum_classification: int,
        limit: int,
    ) -> Sequence[KnowledgeEvidenceCandidate]:
        del query, maximum_classification, limit
        assert workspace_id == self.workspace_id
        return (self.candidate,)

    async def get_active_nodes_by_resource_ids(
        self,
        *,
        workspace_id: UUID,
        resource_ids: Sequence[UUID],
    ) -> Sequence[KnowledgeEvidenceCandidate]:
        assert workspace_id == self.workspace_id
        if self.drift_on_refresh:
            drifted = replace(
                self.candidate,
                evidence=build_evidence_chunk(
                    workspace_id=workspace_id,
                    resource_id=self.candidate.evidence.resource_id,
                    classification=self.candidate.classification,
                    system_id=None,
                    domain_id=None,
                    owner_department_id=None,
                    name=self.candidate.evidence.name,
                    description="A newer governed release changed this node.",
                    source_locator=self.candidate.evidence.source_locator,
                    source_version="e" * 64,
                    effective_from=datetime.now(UTC),
                    extraction_method="KNOWLEDGE_RELEASE_NODE_V1",
                    source_type="KNOWLEDGE_NODE",
                ),
            )
            return (drifted,)
        return (self.candidate,) if self.candidate.evidence.resource_id in resource_ids else ()


class FakeGovernanceEvidence:
    def __init__(self, workspace_id: UUID, *, drift_on_refresh: bool = False) -> None:
        self.workspace_id = workspace_id
        self.drift_on_refresh = drift_on_refresh
        self.item = build_evidence_chunk(
            workspace_id=workspace_id,
            resource_id=uuid4(),
            classification=Classification.INTERNAL,
            system_id=None,
            domain_id=None,
            owner_department_id=None,
            name="Data retention policy (v1)",
            description="Approved records are retained for seven years.",
            source_locator="governance://documents/d/versions/v#chunk=1",
            source_version=f"{uuid4()}:{'a' * 64}",
            effective_from=datetime.now(UTC),
            extraction_method="GOVERNANCE_DOCUMENT_PGVECTOR_V1",
            source_type="GOVERNANCE_DOCUMENT",
        )
        self.search_calls = 0
        self.current_calls = 0

    async def search(
        self,
        *,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        question: str,
        limit: int,
    ) -> tuple[ChatEvidence, ...]:
        del environment, request_id, question, limit
        assert subject.workspace_id == self.workspace_id
        self.search_calls += 1
        return (self.item,)

    async def get_current(
        self,
        *,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        resource_ids: Sequence[UUID],
    ) -> tuple[ChatEvidence, ...]:
        del environment, request_id
        assert subject.workspace_id == self.workspace_id
        self.current_calls += 1
        if self.item.resource_id not in resource_ids:
            return ()
        if self.drift_on_refresh:
            return (
                build_evidence_chunk(
                    workspace_id=self.workspace_id,
                    resource_id=self.item.resource_id,
                    classification=self.item.classification,
                    system_id=None,
                    domain_id=None,
                    owner_department_id=None,
                    name=self.item.name,
                    description="A newer approved policy superseded this content.",
                    source_locator=self.item.source_locator,
                    source_version=f"{uuid4()}:{'b' * 64}",
                    effective_from=datetime.now(UTC),
                    extraction_method="GOVERNANCE_DOCUMENT_PGVECTOR_V1",
                    source_type="GOVERNANCE_DOCUMENT",
                ),
            )
        return (self.item,)


class FixedComposer:
    def __init__(self, draft: ChatDraft) -> None:
        self.draft = draft

    async def compose(
        self,
        *,
        question: str,
        evidence: Sequence[ChatEvidence],
    ) -> ChatDraft:
        del question, evidence
        return self.draft


class SelectingComposer:
    def __init__(self, indexes: tuple[int, ...]) -> None:
        self.indexes = indexes
        self.calls = 0

    async def compose(
        self,
        *,
        question: str,
        evidence: Sequence[ChatEvidence],
    ) -> ChatDraft:
        del question
        self.calls += 1
        return ChatDraft(
            answer="authorized subset",
            cited_chunk_ids=tuple(evidence[index].chunk_id for index in self.indexes),
        )


class FixedGeneralComposer:
    def __init__(self, draft: ChatDraft) -> None:
        self.draft = draft
        self.calls = 0

    async def compose_general(self, *, question: str) -> ChatDraft:
        del question
        self.calls += 1
        return self.draft


class FailingReranker:
    async def rerank(
        self,
        *,
        question: str,
        evidence: Sequence[ChatEvidence],
    ) -> tuple[UUID, ...]:
        del question, evidence
        raise RuntimeError("provider unavailable")


class SelectingReranker:
    def __init__(self) -> None:
        self.calls = 0

    async def rerank(
        self,
        *,
        question: str,
        evidence: Sequence[ChatEvidence],
    ) -> tuple[UUID, ...]:
        del question
        self.calls += 1
        return tuple(item.chunk_id for item in evidence)


class CapturingVectorCatalog:
    def __init__(self, item: CatalogAssetIndex) -> None:
        self.item = item
        self.access: ClassificationAccessSnapshot | None = None
        self.calls = 0

    async def search(
        self,
        *,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        question: str,
        limit: int,
    ) -> ChatVectorSearchResult:
        del subject, question, limit
        self.calls += 1
        self.access = access
        return ChatVectorSearchResult(
            items=(self.item,),
            provider_invoked=True,
        )


class FailingBeforeProviderVectorCatalog:
    async def search(
        self,
        *,
        subject: SubjectAttributes,
        access: ClassificationAccessSnapshot,
        question: str,
        limit: int,
    ) -> ChatVectorSearchResult:
        del subject, access, question, limit
        raise RuntimeError("catalog candidate query failed before provider invocation")


def asset(workspace_id: UUID, *, description: str = "Fab yield observations") -> CatalogAssetIndex:
    return CatalogAssetIndex(
        asset_id=uuid4(),
        workspace_id=workspace_id,
        external_urn="urn:li:dataset:test",
        asset_type="DATASET",
        name="Wafer Yield",
        description=description,
        platform="postgres",
        domain_id=None,
        system_id=None,
        owner_department_id=None,
        classification=Classification.INTERNAL,
        lifecycle="ACTIVE",
        source_version="v1",
        observed_at=datetime.now(UTC),
    )


async def test_vector_provider_receives_only_exact_profile_bound_classifications() -> None:
    workspace_id = uuid4()
    profile_id = uuid4()
    binding = inference_binding(InferenceStage.EMBEDDING, profile_id)
    other_profile_id = uuid4()
    index = FakeIndex(asset(workspace_id))
    vector = CapturingVectorCatalog(index.item)
    governed = governed_chat_access(binding)
    access = replace(
        governed,
        rules=tuple(
            (
                replace(
                    rule,
                    search_mode=SearchMode.ABAC,
                    chat_mode=ChatMode.INTERNAL_APPROVED_ONLY,
                    embedding_provider_profile_version_id=other_profile_id,
                )
                if rule.classification is Classification.CONFIDENTIAL
                else rule
            )
            for rule in governed.rules
        ),
    )
    store = FakeChatStore()

    exchange = await chat_service(
        catalog_index=index,
        vector_catalog=vector,
        classification_access=cast(
            ClassificationAccessResolver,
            FixedClassificationAccess(access),
        ),
        inference_runtime_bindings=(binding,),
        uow_factory=chat_uow_factory(store),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    ).query(
        workspace_id=workspace_id,
        subject=replace(
            chat_subject(workspace_id),
            clearance=Classification.CONFIDENTIAL,
        ),
        session_id=None,
        question="승인된 고객 데이터를 찾아줘",
        maximum_evidence=2,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-vector-pruned",
        requested_mode=ChatRetrievalMode.VECTOR,
    )

    assert vector.access is not None
    assert vector.access.rule_for(Classification.CONFIDENTIAL).search_mode is SearchMode.DENY
    assert exchange.evidence
    assert store.saved_composition_audit is not None
    assert store.saved_composition_audit.external_service_used is True
    assert store.saved_composition_audit.external_stages == ("embedding",)
    assert store.saved_composition_audit.provider_profile_version_id is None
    assert store.saved_composition_audit.external_stage_provider_profile_version_ids == (
        ("embedding", profile_id),
    )


async def test_vector_pre_provider_failure_is_not_audited_as_external_use() -> None:
    workspace_id = uuid4()
    profile_id = uuid4()
    binding = inference_binding(InferenceStage.EMBEDDING, profile_id)
    store = FakeChatStore()

    exchange = await chat_service(
        catalog_index=FakeIndex(asset(workspace_id)),
        vector_catalog=FailingBeforeProviderVectorCatalog(),
        classification_access=cast(
            ClassificationAccessResolver,
            FixedClassificationAccess(governed_chat_access(binding)),
        ),
        inference_runtime_bindings=(binding,),
        uow_factory=chat_uow_factory(store),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    ).query(
        workspace_id=workspace_id,
        subject=chat_subject(workspace_id),
        session_id=None,
        question="의미가 비슷한 데이터를 찾아줘",
        maximum_evidence=2,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-vector-pre-provider-failure",
        requested_mode=ChatRetrievalMode.VECTOR,
    )

    assert exchange.route.adapter_state is ChatAdapterState.FAILED
    assert store.saved_composition_audit is not None
    assert store.saved_composition_audit.external_service_used is False
    assert store.saved_composition_audit.external_stages == ()
    assert store.saved_composition_audit.provider_profile_version_id is None


async def test_existing_session_owner_is_verified_before_authorization_or_providers() -> None:
    workspace_id = uuid4()
    session_id = uuid4()
    subject = chat_subject(workspace_id)
    index = FakeIndex(asset(workspace_id))
    vector = CapturingVectorCatalog(index.item)
    composer = SelectingComposer((0,))
    ownership = FakeSessionOwnership(uuid4())

    with pytest.raises(ForbiddenError):
        await ChatService(
            catalog_index=index,
            vector_catalog=vector,
            composer=composer,
            session_ownership=ownership,
            subject_access=PassthroughSubjectAccess(),
            uow_factory=chat_uow_factory(FakeChatStore()),
            authorization=AuthorizationService(
                decision_writer=NullDecisionWriter(),
            ),
        ).query(
            workspace_id=workspace_id,
            subject=subject,
            session_id=session_id,
            question="다른 사용자의 세션에서 계속해줘",
            maximum_evidence=2,
            environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
            request_id="request-owner-preflight",
            requested_mode=ChatRetrievalMode.VECTOR,
        )

    assert ownership.calls == 1
    assert index.search_subject is None
    assert vector.calls == 0
    assert composer.calls == 0


async def test_final_citation_validation_rejects_revoked_current_membership() -> None:
    workspace_id = uuid4()
    subject = chat_subject(workspace_id)
    subject_access = PassthroughSubjectAccess(replace(subject, active=False))
    store = FakeChatStore()
    composer = SelectingComposer((0,))

    exchange = await ChatService(
        catalog_index=FakeIndex(asset(workspace_id)),
        composer=composer,
        session_ownership=FakeSessionOwnership(),
        subject_access=subject_access,
        uow_factory=chat_uow_factory(store),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    ).query(
        workspace_id=workspace_id,
        subject=subject,
        session_id=None,
        question="현재 권한으로 설명해줘",
        maximum_evidence=2,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-membership-revoked",
        requested_mode=ChatRetrievalMode.GENERAL,
    )

    assert composer.calls == 1
    assert subject_access.calls == 1
    assert exchange.answer == UNVERIFIABLE_ANSWER
    assert exchange.evidence == ()
    assert store.saved_evidence == ()


async def test_final_citation_validation_rejects_canonical_catalog_drift() -> None:
    workspace_id = uuid4()
    initial = asset(workspace_id)
    current = replace(
        initial,
        classification=Classification.CONFIDENTIAL,
        source_version="v2",
        observed_at=initial.observed_at.replace(microsecond=0),
    )
    store = FakeChatStore()

    exchange = await chat_service(
        catalog_index=FakeIndex(initial, detail_item=current),
        composer=SelectingComposer((0,)),
        uow_factory=chat_uow_factory(store),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    ).query(
        workspace_id=workspace_id,
        subject=chat_subject(workspace_id),
        session_id=None,
        question="현재 카탈로그 근거를 설명해줘",
        maximum_evidence=2,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-catalog-drift",
        requested_mode=ChatRetrievalMode.GENERAL,
    )

    assert exchange.answer == UNVERIFIABLE_ANSWER
    assert exchange.evidence == ()
    assert store.saved_evidence == ()


async def test_final_citation_validation_rejects_active_release_drift() -> None:
    workspace_id = uuid4()
    store = FakeChatStore()
    knowledge = FakeKnowledgeEvidence(
        workspace_id,
        drift_on_refresh=True,
    )

    exchange = await chat_service(
        catalog_index=FakeIndex(asset(workspace_id)),
        knowledge_evidence=knowledge,
        composer=SelectingComposer((0,)),
        uow_factory=chat_uow_factory(store),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    ).query(
        workspace_id=workspace_id,
        subject=chat_subject(workspace_id, include_kg=True),
        session_id=None,
        question="현재 그래프 근거를 설명해줘",
        maximum_evidence=2,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-release-drift",
        requested_mode=ChatRetrievalMode.GRAPH,
    )

    assert exchange.answer == UNVERIFIABLE_ANSWER
    assert exchange.evidence == ()
    assert store.saved_evidence == ()


def test_vector_token_envelope_covers_the_maximum_embedding_payload() -> None:
    question = "𐀀" * 4_000
    input_texts = (
        question,
        *("𐀀" * MAXIMUM_CHAT_VECTOR_TEXT_CHARACTERS for _ in range(MAXIMUM_CHAT_VECTOR_CANDIDATES)),
    )
    serialized_embedding_bytes = len(
        json.dumps(
            {
                "model": "operator-selected-model",
                "input": input_texts,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    general = ChatService._estimated_token_envelope(
        question,
        maximum_evidence=10,
    )
    vector = ChatService._estimated_token_envelope(
        question,
        maximum_evidence=10,
        retrieval_mode=ChatRetrievalMode.VECTOR,
    )

    assert vector >= general + serialized_embedding_bytes
    assert vector < 1_000_000


async def test_chat_persists_only_evidence_that_passes_catalog_read_abac() -> None:
    workspace_id = uuid4()
    subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function=None,
        clearance=Classification.INTERNAL,
        allowed_actions=frozenset({Action.CHAT_QUERY, Action.CATALOG_READ}),
    )
    store = FakeChatStore()
    service = chat_service(
        catalog_index=FakeIndex(asset(workspace_id)),
        uow_factory=chat_uow_factory(store),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    )

    exchange = await service.query(
        workspace_id=workspace_id,
        subject=subject,
        session_id=None,
        question="Wafer yield를 알려줘",
        maximum_evidence=5,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-1",
    )

    assert len(exchange.evidence) == 1
    assert exchange.evidence[0].source_locator == "urn:li:dataset:test"
    assert exchange.evidence[0].workspace_id == workspace_id
    assert evidence_chunk_is_valid(exchange.evidence[0])


async def test_chat_omits_evidence_when_catalog_read_is_not_granted() -> None:
    workspace_id = uuid4()
    subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function=None,
        clearance=Classification.INTERNAL,
        allowed_actions=frozenset({Action.CHAT_QUERY}),
    )
    store = FakeChatStore()
    service = chat_service(
        catalog_index=FakeIndex(asset(workspace_id)),
        uow_factory=chat_uow_factory(store),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    )

    exchange = await service.query(
        workspace_id=workspace_id,
        subject=subject,
        session_id=None,
        question="Wafer yield를 알려줘",
        maximum_evidence=5,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-2",
    )

    assert exchange.evidence == ()
    assert exchange.answer == UNVERIFIABLE_ANSWER


async def test_chat_returns_explicit_general_knowledge_only_after_empty_authorized_retrieval() -> (
    None
):
    workspace_id = uuid4()
    subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function=None,
        clearance=Classification.INTERNAL,
        allowed_actions=frozenset({Action.CHAT_QUERY}),
    )
    store = FakeChatStore()
    general = FixedGeneralComposer(
        ChatDraft(answer="온톨로지는 개념과 관계를 구조화한 지식 모델입니다.", cited_chunk_ids=())
    )
    exchange = await chat_service(
        catalog_index=FakeIndex(asset(workspace_id)),
        general_composer=general,
        uow_factory=chat_uow_factory(store),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    ).query(
        workspace_id=workspace_id,
        subject=subject,
        session_id=None,
        question="온톨로지가 뭐야?",
        maximum_evidence=5,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-general-knowledge",
    )

    assert general.calls == 1
    assert exchange.answer == (
        f"{GENERAL_KNOWLEDGE_PREFIX}온톨로지는 개념과 관계를 구조화한 지식 모델입니다."
    )
    assert exchange.evidence == ()
    assert store.saved_evidence == ()
    assert any(
        item.detail_code == "GENERAL_KNOWLEDGE_DRAFT_COMPOSED"
        and item.status is ChatWorkflowStatus.COMPLETED
        for item in exchange.workflow
    )
    assert any(
        item.detail_code == "NO_INTERNAL_CITATIONS_GENERAL_ANSWER"
        and item.status is ChatWorkflowStatus.SKIPPED
        for item in exchange.workflow
    )


async def test_chat_rejects_general_draft_that_forges_internal_citations() -> None:
    workspace_id = uuid4()
    general = FixedGeneralComposer(ChatDraft(answer="forged", cited_chunk_ids=(uuid4(),)))
    exchange = await chat_service(
        catalog_index=FakeIndex(asset(workspace_id)),
        general_composer=general,
        uow_factory=chat_uow_factory(FakeChatStore()),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    ).query(
        workspace_id=workspace_id,
        subject=SubjectAttributes(
            subject_id=uuid4(),
            workspace_id=workspace_id,
            active=True,
            department_id=None,
            groups=frozenset(),
            job_function=None,
            clearance=Classification.INTERNAL,
            allowed_actions=frozenset({Action.CHAT_QUERY}),
        ),
        session_id=None,
        question="일반 지식을 알려줘",
        maximum_evidence=5,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-general-forged",
    )

    assert exchange.answer == UNVERIFIABLE_ANSWER
    assert exchange.evidence == ()
    assert any(
        item.detail_code == "INVALID_GENERAL_KNOWLEDGE_DRAFT"
        and item.status is ChatWorkflowStatus.REFUSED
        for item in exchange.workflow
    )


async def test_chat_graph_unavailable_returns_safe_general_knowledge_without_retrieval() -> None:
    workspace_id = uuid4()
    profile_id = uuid4()
    binding = inference_binding(InferenceStage.COMPOSITION, profile_id)
    index = FakeIndex(asset(workspace_id))
    store = FakeChatStore()
    general = FixedGeneralComposer(
        ChatDraft(answer="계보는 데이터 흐름과 의존 관계를 나타냅니다.", cited_chunk_ids=())
    )
    exchange = await chat_service(
        catalog_index=index,
        general_composer=general,
        composition_audit=ChatCompositionAudit(
            provider="local-test",
            model="configured-model",
            prompt_template_version="test-v1",
            external_service_used=True,
            provider_profile_version_id=profile_id,
        ),
        classification_access=cast(
            ClassificationAccessResolver,
            FixedClassificationAccess(governed_chat_access(binding)),
        ),
        inference_runtime_bindings=(binding,),
        uow_factory=chat_uow_factory(store),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    ).query(
        workspace_id=workspace_id,
        subject=chat_subject(workspace_id),
        session_id=None,
        question="이 테이블의 downstream 영향을 알려줘",
        maximum_evidence=5,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-graph-unavailable",
        requested_mode=ChatRetrievalMode.GRAPH,
    )

    assert index.search_subject is None
    assert general.calls == 1
    assert exchange.answer == (
        f"{GENERAL_KNOWLEDGE_PREFIX}계보는 데이터 흐름과 의존 관계를 나타냅니다."
    )
    assert exchange.evidence == ()
    assert exchange.route.selected_mode is ChatRetrievalMode.GRAPH
    assert exchange.route.adapter_state is ChatAdapterState.UNAVAILABLE
    routing = next(item for item in exchange.workflow if item.stage is ChatWorkflowStage.ROUTING)
    assert routing.status is ChatWorkflowStatus.UNAVAILABLE
    assert any(
        item.detail_code == "GRAPH_UNAVAILABLE_GENERAL_KNOWLEDGE_COMPOSED"
        and item.status is ChatWorkflowStatus.COMPLETED
        for item in exchange.workflow
    )
    assert store.saved_composition_audit is not None
    assert store.saved_composition_audit.external_stages == ("composition",)


async def test_chat_graph_fallback_refuses_unbound_external_general_composer() -> None:
    workspace_id = uuid4()
    policy_profile_id = uuid4()
    configured_profile_id = uuid4()
    policy_binding = inference_binding(InferenceStage.COMPOSITION, policy_profile_id)
    configured_binding = replace(
        policy_binding,
        provider_profile_version_id=configured_profile_id,
    )
    general = FixedGeneralComposer(ChatDraft(answer="안전한 일반 설명", cited_chunk_ids=()))
    exchange = await chat_service(
        catalog_index=FakeIndex(asset(workspace_id)),
        general_composer=general,
        composition_audit=ChatCompositionAudit(
            provider="local-test",
            model="configured-model",
            prompt_template_version="test-v1",
            external_service_used=True,
            provider_profile_version_id=configured_profile_id,
        ),
        classification_access=cast(
            ClassificationAccessResolver,
            FixedClassificationAccess(governed_chat_access(policy_binding)),
        ),
        inference_runtime_bindings=(configured_binding,),
        uow_factory=chat_uow_factory(FakeChatStore()),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    ).query(
        workspace_id=workspace_id,
        subject=chat_subject(workspace_id),
        session_id=None,
        question="이 테이블의 downstream 영향을 알려줘",
        maximum_evidence=5,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-graph-fallback-provider-mismatch",
        requested_mode=ChatRetrievalMode.GRAPH,
    )

    assert general.calls == 0
    assert exchange.answer == UNVERIFIABLE_ANSWER
    assert exchange.route.adapter_state is ChatAdapterState.UNAVAILABLE
    assert any(
        item.detail_code == "INFERENCE_PROVIDER_POLICY_BINDING_UNAVAILABLE"
        for item in exchange.workflow
    )


async def test_chat_reranker_failure_refuses_without_composer_or_strategy_fallback() -> None:
    workspace_id = uuid4()
    profile_id = uuid4()
    binding = inference_binding(InferenceStage.RERANKER, profile_id)
    store = FakeChatStore()
    exchange = await chat_service(
        catalog_index=FakeIndex(asset(workspace_id)),
        reranker=FailingReranker(),
        classification_access=cast(
            ClassificationAccessResolver,
            FixedClassificationAccess(governed_chat_access(binding)),
        ),
        inference_runtime_bindings=(binding,),
        uow_factory=chat_uow_factory(store),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    ).query(
        workspace_id=workspace_id,
        subject=chat_subject(workspace_id),
        session_id=None,
        question="주문 데이터를 알려줘",
        maximum_evidence=5,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-reranker-failure",
        requested_mode=ChatRetrievalMode.GENERAL,
    )

    assert exchange.answer == UNVERIFIABLE_ANSWER
    assert exchange.evidence == ()
    assert store.saved_evidence == ()
    assert exchange.route.adapter_state is ChatAdapterState.FAILED
    reranking = next(
        item for item in exchange.workflow if item.stage is ChatWorkflowStage.RERANKING
    )
    assert reranking.status is ChatWorkflowStatus.FAILED


async def test_chat_refuses_external_composer_when_provider_binding_mismatches() -> None:
    workspace_id = uuid4()
    policy_profile_id = uuid4()
    configured_profile_id = uuid4()
    policy_binding = inference_binding(InferenceStage.COMPOSITION, policy_profile_id)
    configured_binding = replace(
        policy_binding,
        provider_profile_version_id=configured_profile_id,
    )
    index = FakeIndex(asset(workspace_id))
    composer = SelectingComposer((0,))
    exchange = await chat_service(
        catalog_index=index,
        composer=composer,
        composition_audit=ChatCompositionAudit(
            provider="local-test",
            model="configured-model",
            prompt_template_version="test-v1",
            external_service_used=True,
            provider_profile_version_id=configured_profile_id,
        ),
        classification_access=cast(
            ClassificationAccessResolver,
            FixedClassificationAccess(governed_chat_access(policy_binding)),
        ),
        inference_runtime_bindings=(configured_binding,),
        uow_factory=chat_uow_factory(FakeChatStore()),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    ).query(
        workspace_id=workspace_id,
        subject=chat_subject(workspace_id),
        session_id=None,
        question="승인된 근거를 설명해줘",
        maximum_evidence=2,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-provider-mismatch",
        requested_mode=ChatRetrievalMode.GENERAL,
    )

    assert exchange.route.adapter_state is ChatAdapterState.UNAVAILABLE
    assert exchange.answer == UNVERIFIABLE_ANSWER
    assert exchange.evidence == ()
    assert index.search_subject is None
    assert composer.calls == 0
    assert any(
        item.detail_code == "INFERENCE_PROVIDER_POLICY_BINDING_UNAVAILABLE"
        for item in exchange.workflow
    )


async def test_chat_refuses_reranker_binding_mismatch_before_provider_call() -> None:
    workspace_id = uuid4()
    profile_id = uuid4()
    policy_binding = inference_binding(InferenceStage.RERANKER, profile_id)
    configured_binding = replace(
        policy_binding,
        deployment_identity="unapproved-reranker-deployment",
    )
    reranker = SelectingReranker()
    index = FakeIndex(asset(workspace_id))

    exchange = await chat_service(
        catalog_index=index,
        reranker=reranker,
        classification_access=cast(
            ClassificationAccessResolver,
            FixedClassificationAccess(governed_chat_access(policy_binding)),
        ),
        inference_runtime_bindings=(configured_binding,),
        uow_factory=chat_uow_factory(FakeChatStore()),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    ).query(
        workspace_id=workspace_id,
        subject=chat_subject(workspace_id),
        session_id=None,
        question="승인된 근거를 정렬해줘",
        maximum_evidence=2,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-reranker-binding-mismatch",
        requested_mode=ChatRetrievalMode.GENERAL,
    )

    assert exchange.route.adapter_state is ChatAdapterState.UNAVAILABLE
    assert exchange.answer == UNVERIFIABLE_ANSWER
    assert index.search_subject is None
    assert reranker.calls == 0


@pytest.mark.parametrize(
    ("field", "unapproved_value"),
    (
        ("server_route_key", "unapproved-runtime-route"),
        ("provider_identity", "unapproved-runtime-provider"),
        ("model_identity", "unapproved-runtime-model"),
        ("deployment_identity", "unapproved-runtime-deployment"),
    ),
)
async def test_chat_refuses_same_profile_uuid_when_runtime_identity_mismatches(
    field: str,
    unapproved_value: str,
) -> None:
    workspace_id = uuid4()
    profile_id = uuid4()
    policy_binding = inference_binding(InferenceStage.COMPOSITION, profile_id)
    configured_binding = mismatched_binding(
        policy_binding,
        field=field,
        value=unapproved_value,
    )
    composer = SelectingComposer((0,))

    exchange = await chat_service(
        catalog_index=FakeIndex(asset(workspace_id)),
        composer=composer,
        composition_audit=ChatCompositionAudit(
            provider=configured_binding.provider_identity,
            model=configured_binding.model_identity,
            prompt_template_version="test-v1",
            external_service_used=True,
            provider_profile_version_id=profile_id,
        ),
        classification_access=cast(
            ClassificationAccessResolver,
            FixedClassificationAccess(governed_chat_access(policy_binding)),
        ),
        inference_runtime_bindings=(configured_binding,),
        uow_factory=chat_uow_factory(FakeChatStore()),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    ).query(
        workspace_id=workspace_id,
        subject=chat_subject(workspace_id),
        session_id=None,
        question="승인된 근거를 설명해줘",
        maximum_evidence=2,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-provider-identity-mismatch",
        requested_mode=ChatRetrievalMode.GENERAL,
    )

    assert exchange.route.adapter_state is ChatAdapterState.UNAVAILABLE
    assert exchange.answer == UNVERIFIABLE_ANSWER
    assert composer.calls == 0


async def test_chat_reauthorizes_exact_provider_identity_after_external_call() -> None:
    workspace_id = uuid4()
    profile_id = uuid4()
    binding = inference_binding(InferenceStage.COMPOSITION, profile_id)
    initial_access = governed_chat_access(binding)
    drifted_access = replace(
        initial_access,
        provider_profiles=tuple(
            replace(profile, provider_identity="drifted-provider-identity")
            for profile in initial_access.provider_profiles
        ),
    )
    store = FakeChatStore()
    composer = SelectingComposer((0,))

    exchange = await chat_service(
        catalog_index=FakeIndex(asset(workspace_id)),
        composer=composer,
        composition_audit=ChatCompositionAudit(
            provider=binding.provider_identity,
            model=binding.model_identity,
            prompt_template_version="test-v1",
            external_service_used=True,
            provider_profile_version_id=profile_id,
        ),
        classification_access=cast(
            ClassificationAccessResolver,
            FixedClassificationAccess(initial_access, drifted_access),
        ),
        inference_runtime_bindings=(binding,),
        uow_factory=chat_uow_factory(store),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    ).query(
        workspace_id=workspace_id,
        subject=chat_subject(workspace_id),
        session_id=None,
        question="공급자 변경 중인 근거를 설명해줘",
        maximum_evidence=2,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-final-provider-identity-drift",
        requested_mode=ChatRetrievalMode.GENERAL,
    )

    assert composer.calls == 1
    assert exchange.answer == UNVERIFIABLE_ANSWER
    assert exchange.evidence == ()
    assert store.saved_evidence == ()


async def test_chat_reauthorizes_citations_after_provider_and_refuses_revocation() -> None:
    workspace_id = uuid4()
    profile_id = uuid4()
    binding = inference_binding(InferenceStage.COMPOSITION, profile_id)
    initial_access = governed_chat_access(binding)
    revoked_access = replace(
        initial_access,
        policy_hash="b" * 64,
        authorization_generation=4,
        rules=tuple(
            replace(rule, chat_mode=ChatMode.DENY, provider_profile_version_id=None)
            for rule in initial_access.rules
        ),
    )
    store = FakeChatStore()
    composer = SelectingComposer((0,))
    service = chat_service(
        catalog_index=FakeIndex(asset(workspace_id)),
        composer=composer,
        composition_audit=ChatCompositionAudit(
            provider="local-test",
            model="configured-model",
            prompt_template_version="test-v1",
            external_service_used=True,
            provider_profile_version_id=profile_id,
        ),
        classification_access=cast(
            ClassificationAccessResolver,
            FixedClassificationAccess(initial_access, revoked_access),
        ),
        inference_runtime_bindings=(binding,),
        uow_factory=chat_uow_factory(store),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    )

    exchange = await service.query(
        workspace_id=workspace_id,
        subject=chat_subject(workspace_id),
        session_id=None,
        question="정책 변경 중인 근거를 설명해줘",
        maximum_evidence=2,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-final-revocation",
        requested_mode=ChatRetrievalMode.GENERAL,
    )

    assert composer.calls == 1
    assert exchange.answer == UNVERIFIABLE_ANSWER
    assert exchange.evidence == ()
    assert store.saved_evidence == ()
    assert store.saved_composition_audit is not None
    assert store.saved_composition_audit.provider_profile_version_id == profile_id
    assert store.saved_composition_audit.classification_policy_id == initial_access.policy_id


def test_chat_token_envelope_is_conservative_at_request_bounds() -> None:
    question = "가" * 4_000

    estimate = ChatService._estimated_token_envelope(
        question,
        maximum_evidence=10,
    )

    assert estimate == len(question.encode("utf-8")) + (10 * 16_384) + 8_192 + 1_024
    assert estimate > 180_000


async def test_unavailable_graph_reason_is_not_hidden_by_provider_policy() -> None:
    workspace_id = uuid4()
    composer = SelectingComposer((0,))
    exchange = await chat_service(
        catalog_index=FakeIndex(asset(workspace_id)),
        composer=composer,
        composition_audit=ChatCompositionAudit(
            provider="local-test",
            model="configured-model",
            prompt_template_version="test-v1",
            external_service_used=True,
        ),
        uow_factory=chat_uow_factory(FakeChatStore()),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    ).query(
        workspace_id=workspace_id,
        subject=chat_subject(workspace_id),
        session_id=None,
        question="이 테이블의 downstream 영향을 알려줘",
        maximum_evidence=2,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-graph-reason",
        requested_mode=ChatRetrievalMode.GRAPH,
    )

    assert exchange.route.adapter_state is ChatAdapterState.UNAVAILABLE
    assert composer.calls == 0
    routing = next(item for item in exchange.workflow if item.stage is ChatWorkflowStage.ROUTING)
    assert routing.detail_code == "GRAPH_ADAPTER_UNAVAILABLE"


async def test_chat_excludes_protected_evidence_until_provider_policy_is_active() -> None:
    workspace_id = uuid4()
    protected_asset = replace(asset(workspace_id), classification=Classification.CONFIDENTIAL)
    index = FakeIndex(protected_asset)
    store = FakeChatStore()
    subject = replace(chat_subject(workspace_id), clearance=Classification.RESTRICTED)
    service = chat_service(
        catalog_index=index,
        uow_factory=chat_uow_factory(store),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    )

    exchange = await service.query(
        workspace_id=workspace_id,
        subject=subject,
        session_id=None,
        question="보호 데이터 설명",
        maximum_evidence=5,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-protected-floor",
        requested_mode=ChatRetrievalMode.GENERAL,
    )

    assert index.search_subject is not None
    assert index.search_subject.clearance is Classification.INTERNAL
    assert exchange.answer == UNVERIFIABLE_ANSWER
    assert exchange.evidence == ()
    assert store.saved_evidence == ()


async def test_chat_can_use_only_authorized_release_pinned_knowledge_evidence() -> None:
    workspace_id = uuid4()
    subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function=None,
        clearance=Classification.INTERNAL,
        allowed_actions=frozenset({Action.CHAT_QUERY, Action.CATALOG_READ, Action.KG_READ}),
    )
    service = chat_service(
        catalog_index=FakeIndex(asset(workspace_id)),
        knowledge_evidence=FakeKnowledgeEvidence(workspace_id),
        uow_factory=chat_uow_factory(FakeChatStore()),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    )

    exchange = await service.query(
        workspace_id=workspace_id,
        subject=subject,
        session_id=None,
        question="EUV 장비 의존성을 알려줘",
        maximum_evidence=2,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-3",
        requested_mode=ChatRetrievalMode.GRAPH,
    )

    assert len(exchange.evidence) == 1
    assert exchange.evidence[0].source_type == "KNOWLEDGE_NODE"
    assert exchange.evidence[0].source_version == "f" * 64


async def test_chat_vector_mode_uses_current_governance_document_evidence() -> None:
    workspace_id = uuid4()
    embedding_binding = inference_binding(InferenceStage.EMBEDDING, uuid4())
    governance = FakeGovernanceEvidence(workspace_id)
    store = FakeChatStore()
    service = chat_service(
        catalog_index=FakeIndex(asset(workspace_id)),
        governance_evidence=governance,
        classification_access=cast(
            ClassificationAccessResolver,
            FixedClassificationAccess(governed_chat_access(embedding_binding)),
        ),
        inference_runtime_bindings=(embedding_binding,),
        uow_factory=chat_uow_factory(store),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
        composer=SelectingComposer((0,)),
    )

    exchange = await service.query(
        workspace_id=workspace_id,
        subject=chat_subject(workspace_id, include_governance=True),
        session_id=None,
        question="승인된 보존 정책을 알려줘",
        maximum_evidence=2,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-governance-vector",
        requested_mode=ChatRetrievalMode.VECTOR,
    )

    assert exchange.answer == "authorized subset"
    assert tuple(item.source_type for item in exchange.evidence) == ("GOVERNANCE_DOCUMENT",)
    assert governance.search_calls == 1
    assert governance.current_calls == 1
    assert store.saved_evidence == exchange.evidence


async def test_chat_refuses_governance_citation_when_active_version_drifts() -> None:
    workspace_id = uuid4()
    embedding_binding = inference_binding(InferenceStage.EMBEDDING, uuid4())
    governance = FakeGovernanceEvidence(workspace_id, drift_on_refresh=True)
    store = FakeChatStore()
    service = chat_service(
        catalog_index=FakeIndex(asset(workspace_id)),
        governance_evidence=governance,
        classification_access=cast(
            ClassificationAccessResolver,
            FixedClassificationAccess(governed_chat_access(embedding_binding)),
        ),
        inference_runtime_bindings=(embedding_binding,),
        uow_factory=chat_uow_factory(store),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
        composer=SelectingComposer((0,)),
    )

    exchange = await service.query(
        workspace_id=workspace_id,
        subject=chat_subject(workspace_id, include_governance=True),
        session_id=None,
        question="변경 중인 보존 정책을 알려줘",
        maximum_evidence=2,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-governance-drift",
        requested_mode=ChatRetrievalMode.VECTOR,
    )

    assert exchange.answer == UNVERIFIABLE_ANSWER
    assert exchange.evidence == ()
    assert store.saved_evidence == ()
    assert governance.current_calls == 1


async def test_chat_rejects_forged_or_zero_citations_without_persisting_evidence() -> None:
    workspace_id = uuid4()
    subject = chat_subject(workspace_id)
    for draft in (
        ChatDraft(answer="forged", cited_chunk_ids=(uuid4(),)),
        ChatDraft(answer="unsupported prose", cited_chunk_ids=()),
    ):
        store = FakeChatStore()
        service = chat_service(
            catalog_index=FakeIndex(asset(workspace_id)),
            uow_factory=chat_uow_factory(store),
            authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
            composer=FixedComposer(draft),
        )
        exchange = await service.query(
            workspace_id=workspace_id,
            subject=subject,
            session_id=None,
            question="Wafer yield를 알려줘",
            maximum_evidence=5,
            environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
            request_id="request-forged",
        )
        assert exchange.answer == UNVERIFIABLE_ANSWER
        assert exchange.evidence == ()
        assert store.saved_evidence == ()


async def test_chat_rejects_tampered_chunk_hash() -> None:
    workspace_id = uuid4()
    store = FakeChatStore()
    service = chat_service(
        catalog_index=FakeIndex(asset(workspace_id)),
        knowledge_evidence=FakeKnowledgeEvidence(workspace_id, tamper_hash=True),
        uow_factory=chat_uow_factory(store),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
        composer=SelectingComposer((0,)),
    )
    exchange = await service.query(
        workspace_id=workspace_id,
        subject=chat_subject(workspace_id, include_kg=True),
        session_id=None,
        question="EUV 장비 의존성을 알려줘",
        maximum_evidence=2,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-tampered",
        requested_mode=ChatRetrievalMode.GRAPH,
    )
    assert exchange.answer == UNVERIFIABLE_ANSWER
    assert exchange.evidence == ()
    assert store.saved_evidence == ()


async def test_chat_persists_only_the_valid_cited_subset_in_citation_order() -> None:
    workspace_id = uuid4()
    service = chat_service(
        catalog_index=FakeIndex(asset(workspace_id)),
        knowledge_evidence=FakeKnowledgeEvidence(workspace_id),
        uow_factory=chat_uow_factory(FakeChatStore()),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
        composer=SelectingComposer((0,)),
    )
    exchange = await service.query(
        workspace_id=workspace_id,
        subject=chat_subject(workspace_id, include_kg=True),
        session_id=None,
        question="EUV 의존성을 알려줘",
        maximum_evidence=2,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-subset",
        requested_mode=ChatRetrievalMode.GRAPH,
    )
    assert exchange.answer == "authorized subset"
    assert tuple(item.source_type for item in exchange.evidence) == ("KNOWLEDGE_NODE",)


async def test_assistant_red_team_corpus_cannot_forge_citations_or_trigger_tools() -> None:
    corpus_path = Path(__file__).parents[1] / "fixtures" / "assistant_red_team.json"
    cases = json.loads(corpus_path.read_text(encoding="utf-8"))
    workspace_id = uuid4()
    for case in cases:
        store = FakeChatStore()
        service = chat_service(
            catalog_index=FakeIndex(asset(workspace_id, description=str(case["content"]))),
            uow_factory=chat_uow_factory(store),
            authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
            composer=FixedComposer(ChatDraft(answer="tool output", cited_chunk_ids=(uuid4(),))),
        )
        exchange = await service.query(
            workspace_id=workspace_id,
            subject=chat_subject(workspace_id),
            session_id=None,
            question="이 근거를 설명해줘",
            maximum_evidence=1,
            environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
            request_id=f"red-team-{case['id']}",
        )
        assert exchange.answer == UNVERIFIABLE_ANSWER
        assert exchange.evidence == ()
        assert store.saved_evidence == ()


def chat_subject(
    workspace_id: UUID,
    *,
    include_kg: bool = False,
    include_governance: bool = False,
) -> SubjectAttributes:
    actions = {Action.CHAT_QUERY, Action.CATALOG_READ}
    if include_kg:
        actions.add(Action.KG_READ)
    if include_governance:
        actions.add(Action.GOVERNANCE_KNOWLEDGE_READ)
    return SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function=None,
        clearance=Classification.INTERNAL,
        allowed_actions=frozenset(actions),
    )
