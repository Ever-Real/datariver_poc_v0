from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from datariver.application.dto import (
    CatalogAssetDetail,
    CatalogAssetIndex,
    CatalogPage,
    ChatEvidence,
    ChatExchange,
    KnowledgeEvidenceCandidate,
)
from datariver.application.services.authorization import AuthorizationService, NullDecisionWriter
from datariver.application.services.chat import ChatService
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
    def __init__(self, workspace_id: UUID) -> None:
        self.workspace_id = workspace_id

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
        return (
            KnowledgeEvidenceCandidate(
                evidence=ChatEvidence(
                    resource_id=uuid4(),
                    name="EUV lithography",
                    description="Critical equipment dependency",
                    source_locator="knowledge://graphs/g/releases/r/nodes/n",
                    source_version="f" * 64,
                    source_type="KNOWLEDGE_NODE",
                ),
                graph_id=uuid4(),
                classification=Classification.INTERNAL,
            ),
        )


def asset(workspace_id: UUID) -> CatalogAssetIndex:
    return CatalogAssetIndex(
        asset_id=uuid4(),
        workspace_id=workspace_id,
        external_urn="urn:li:dataset:test",
        asset_type="DATASET",
        name="Wafer Yield",
        description="Fab yield observations",
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
    assert "찾지 못했습니다" in exchange.answer


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
