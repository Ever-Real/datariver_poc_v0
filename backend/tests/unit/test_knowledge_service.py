from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from datariver.application.dto import (
    KnowledgeChangeSetRecord,
    KnowledgeGraphRecord,
    KnowledgeReleaseRecord,
)
from datariver.application.ports import KnowledgeStore
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.knowledge import KnowledgeService
from datariver.domain.authz import (
    Action,
    AuthenticationAssurance,
    Classification,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ForbiddenError


class _Authorization:
    def __init__(self) -> None:
        self.calls = 0

    async def authorize(self, **kwargs: object) -> None:
        del kwargs
        self.calls += 1


class _PublicationStore:
    def __init__(self, *, graph_id: UUID) -> None:
        self.graph_id = graph_id
        self.calls: list[dict[str, object]] = []

    async def publish_approved_changeset(
        self,
        **kwargs: object,
    ) -> tuple[KnowledgeChangeSetRecord, KnowledgeReleaseRecord]:
        self.calls.append(dict(kwargs))
        now = datetime.now(UTC)
        changeset_id = kwargs["changeset_id"]
        release_id = uuid4()
        assert isinstance(changeset_id, UUID)
        return (
            KnowledgeChangeSetRecord(
                changeset_id=changeset_id,
                graph_id=self.graph_id,
                base_release_id=None,
                ontology_version_id=uuid4(),
                title="approved",
                state="PUBLISHED",
                author_id=uuid4(),
                reviewed_by=uuid4(),
                review_reason="approved",
                published_release_id=release_id,
                version=4,
                created_at=now,
                updated_at=now,
            ),
            KnowledgeReleaseRecord(
                release_id=release_id,
                graph_id=self.graph_id,
                release_no=1,
                ontology_version_id=uuid4(),
                content_hash="a" * 64,
                node_count=1,
                edge_count=0,
                published_at=now,
            ),
        )


class _CreateGraphStore:
    def __init__(self, *, workspace_id: UUID) -> None:
        self.workspace_id = workspace_id
        self.calls: list[dict[str, object]] = []

    async def create_graph(self, **kwargs: object) -> KnowledgeGraphRecord:
        self.calls.append(dict(kwargs))
        return KnowledgeGraphRecord(
            graph_id=uuid4(),
            workspace_id=self.workspace_id,
            slug="semiconductor",
            name="Semiconductor",
            graph_type="DOMAIN",
            status="DRAFT",
            classification=Classification.INTERNAL,
            active_release_id=None,
            version=1,
        )


def _subject(*, workspace_id: UUID) -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset({"security-administrators"}),
        job_function=None,
        clearance=Classification.RESTRICTED,
        allowed_actions=frozenset({Action.KG_PUBLISH, Action.CHAT_QUERY}),
        authentication_time=datetime.now(UTC),
        authentication_assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
    )


@pytest.mark.asyncio
async def test_service_publishes_an_approved_changeset_through_one_atomic_store_command() -> None:
    workspace_id = uuid4()
    graph_id = uuid4()
    changeset_id = uuid4()
    graph = KnowledgeGraphRecord(
        graph_id=graph_id,
        workspace_id=workspace_id,
        slug="semiconductor",
        name="Semiconductor",
        graph_type="DOMAIN",
        status="DRAFT",
        classification=Classification.INTERNAL,
        active_release_id=None,
        version=1,
    )
    store = _PublicationStore(graph_id=graph_id)
    authorization = _Authorization()
    service = KnowledgeService(
        store=cast(KnowledgeStore, store),
        authorization=cast(AuthorizationService, authorization),
    )

    changeset, release = await service.publish_changeset(
        workspace_id=workspace_id,
        graph=graph,
        changeset_id=changeset_id,
        subject=_subject(workspace_id=workspace_id),
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="knowledge-publication",
        idempotency_key="knowledge-publication-key",
        request_hash="b" * 64,
    )

    assert authorization.calls == 1
    assert len(store.calls) == 1
    assert store.calls[0]["changeset_id"] == changeset_id
    assert changeset.published_release_id == release.release_id


@pytest.mark.asyncio
async def test_create_graph_binds_the_idempotent_command_to_the_authenticated_subject() -> None:
    workspace_id = uuid4()
    subject = _subject(workspace_id=workspace_id)
    store = _CreateGraphStore(workspace_id=workspace_id)
    service = KnowledgeService(
        store=cast(KnowledgeStore, store),
        authorization=cast(AuthorizationService, _Authorization()),
    )

    await service.create_graph(
        workspace_id=workspace_id,
        subject=subject,
        slug="semiconductor",
        name="Semiconductor",
        graph_type="DOMAIN",
        classification=Classification.INTERNAL,
        entity_types=frozenset({"Dataset"}),
        edge_types=frozenset(),
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="knowledge-create",
        idempotency_key="knowledge-create-idempotency",
        request_hash="c" * 64,
    )

    assert store.calls[0]["actor_id"] == subject.subject_id


@pytest.mark.asyncio
async def test_graphrag_denies_confidential_graph_before_authorization_or_store_read() -> None:
    workspace_id = uuid4()
    graph = KnowledgeGraphRecord(
        graph_id=uuid4(),
        workspace_id=workspace_id,
        slug="confidential",
        name="Confidential",
        graph_type="DOMAIN",
        status="PUBLISHED",
        classification=Classification.CONFIDENTIAL,
        active_release_id=uuid4(),
        version=2,
    )
    authorization = _Authorization()
    service = KnowledgeService(
        store=cast(KnowledgeStore, cast(Any, object())),
        authorization=cast(AuthorizationService, authorization),
    )

    with pytest.raises(ForbiddenError, match="policy floor"):
        await service.get_release_for_graphrag(
            workspace_id=workspace_id,
            graph=graph,
            release_id=uuid4(),
            subject=_subject(workspace_id=workspace_id),
            environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
            request_id="restricted-graphrag",
            maximum_nodes=100,
        )

    assert authorization.calls == 0
