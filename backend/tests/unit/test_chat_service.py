from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from datariver.application.dto import (
    CatalogAssetDetail,
    CatalogAssetIndex,
    CatalogPage,
    ChatDraft,
    ChatEvidence,
    ChatExchange,
    KnowledgeEvidenceCandidate,
)
from datariver.application.evidence import build_evidence_chunk, evidence_chunk_is_valid
from datariver.application.services.authorization import AuthorizationService, NullDecisionWriter
from datariver.application.services.chat import UNVERIFIABLE_ANSWER, ChatService
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import uuid7


class FakeIndex:
    def __init__(self, item: CatalogAssetIndex) -> None:
        self.item = item

    async def search(
        self,
        *,
        subject: SubjectAttributes,
        query: str,
        filters: dict[str, Any],
        cursor: str | None,
        limit: int,
    ) -> CatalogPage:
        del subject, query, filters, cursor, limit
        return CatalogPage(items=(self.item,), next_cursor=None, observed_at=datetime.now(UTC))

    async def get_authorized_asset(
        self, *, subject: SubjectAttributes, asset_id: UUID
    ) -> CatalogAssetDetail | None:
        del subject, asset_id
        return None


class FakeChatStore:
    def __init__(self) -> None:
        self.saved_evidence: tuple[ChatEvidence, ...] = ()

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
    ) -> ChatExchange:
        del workspace_id, owner_id, question, policy_decision_id
        self.saved_evidence = tuple(evidence)
        return ChatExchange(
            session_id=session_id or uuid7(),
            request_message_id=uuid7(),
            response_message_id=uuid7(),
            answer=answer,
            evidence=self.saved_evidence,
        )


class FakeKnowledgeEvidence:
    def __init__(self, workspace_id: UUID, *, tamper_hash: bool = False) -> None:
        self.workspace_id = workspace_id
        self.tamper_hash = tamper_hash

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
        return (
            KnowledgeEvidenceCandidate(
                evidence=evidence,
                graph_id=uuid4(),
                classification=Classification.INTERNAL,
            ),
        )


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

    async def compose(
        self,
        *,
        question: str,
        evidence: Sequence[ChatEvidence],
    ) -> ChatDraft:
        del question
        return ChatDraft(
            answer="authorized subset",
            cited_chunk_ids=tuple(evidence[index].chunk_id for index in self.indexes),
        )


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
    service = ChatService(
        catalog_index=FakeIndex(asset(workspace_id)),
        store=store,
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
    service = ChatService(
        catalog_index=FakeIndex(asset(workspace_id)),
        store=store,
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
    service = ChatService(
        catalog_index=FakeIndex(asset(workspace_id)),
        knowledge_evidence=FakeKnowledgeEvidence(workspace_id),
        store=FakeChatStore(),
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
    )

    assert len(exchange.evidence) == 2
    assert exchange.evidence[1].source_type == "KNOWLEDGE_NODE"
    assert exchange.evidence[1].source_version == "f" * 64


async def test_chat_rejects_forged_or_zero_citations_without_persisting_evidence() -> None:
    workspace_id = uuid4()
    subject = chat_subject(workspace_id)
    for draft in (
        ChatDraft(answer="forged", cited_chunk_ids=(uuid4(),)),
        ChatDraft(answer="unsupported prose", cited_chunk_ids=()),
    ):
        store = FakeChatStore()
        service = ChatService(
            catalog_index=FakeIndex(asset(workspace_id)),
            store=store,
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
    service = ChatService(
        catalog_index=FakeIndex(asset(workspace_id)),
        knowledge_evidence=FakeKnowledgeEvidence(workspace_id, tamper_hash=True),
        store=store,
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
        composer=SelectingComposer((1,)),
    )
    exchange = await service.query(
        workspace_id=workspace_id,
        subject=chat_subject(workspace_id, include_kg=True),
        session_id=None,
        question="EUV 장비 의존성을 알려줘",
        maximum_evidence=2,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-tampered",
    )
    assert exchange.answer == UNVERIFIABLE_ANSWER
    assert exchange.evidence == ()
    assert store.saved_evidence == ()


async def test_chat_persists_only_the_valid_cited_subset_in_citation_order() -> None:
    workspace_id = uuid4()
    service = ChatService(
        catalog_index=FakeIndex(asset(workspace_id)),
        knowledge_evidence=FakeKnowledgeEvidence(workspace_id),
        store=FakeChatStore(),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
        composer=SelectingComposer((1, 0)),
    )
    exchange = await service.query(
        workspace_id=workspace_id,
        subject=chat_subject(workspace_id, include_kg=True),
        session_id=None,
        question="EUV와 wafer yield를 알려줘",
        maximum_evidence=2,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-subset",
    )
    assert exchange.answer == "authorized subset"
    assert tuple(item.source_type for item in exchange.evidence) == (
        "KNOWLEDGE_NODE",
        "CATALOG_ASSET",
    )


async def test_assistant_red_team_corpus_cannot_forge_citations_or_trigger_tools() -> None:
    corpus_path = Path(__file__).parents[1] / "fixtures" / "assistant_red_team.json"
    cases = json.loads(corpus_path.read_text(encoding="utf-8"))
    workspace_id = uuid4()
    for case in cases:
        store = FakeChatStore()
        service = ChatService(
            catalog_index=FakeIndex(asset(workspace_id, description=str(case["content"]))),
            store=store,
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


def chat_subject(workspace_id: UUID, *, include_kg: bool = False) -> SubjectAttributes:
    actions = {Action.CHAT_QUERY, Action.CATALOG_READ}
    if include_kg:
        actions.add(Action.KG_READ)
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
