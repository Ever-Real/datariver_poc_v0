from __future__ import annotations

from uuid import UUID

from datariver.application.dto import (
    KnowledgeChangeSetRecord,
    KnowledgeGraphRecord,
    KnowledgeReleaseRecord,
)
from datariver.application.ports import KnowledgeStore
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.knowledge import ChangeSetState, GraphChangeOperation, GraphSnapshot


class KnowledgeService:
    def __init__(self, *, store: KnowledgeStore, authorization: AuthorizationService) -> None:
        self._store = store
        self._authorization = authorization

    async def create_graph(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        slug: str,
        name: str,
        graph_type: str,
        classification: Classification,
        entity_types: frozenset[str],
        edge_types: frozenset[str],
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeGraphRecord:
        await self._authorization.authorize(
            subject=subject,
            resource=self._resource(
                graph_id=workspace_id,
                workspace_id=workspace_id,
                classification=classification,
                lifecycle="DRAFT",
            ),
            action=Action.KG_CREATE,
            environment=environment,
            request_id=request_id,
        )
        return await self._store.create_graph(
            workspace_id=workspace_id,
            slug=slug,
            name=name,
            graph_type=graph_type,
            classification=int(classification),
            entity_types=entity_types,
            edge_types=edge_types,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def list_graphs(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[KnowledgeGraphRecord, ...]:
        await self._authorization.authorize(
            subject=subject,
            resource=self._resource(
                graph_id=workspace_id,
                workspace_id=workspace_id,
                classification=Classification.PUBLIC,
                lifecycle="ACTIVE",
            ),
            action=Action.KG_READ,
            environment=environment,
            request_id=request_id,
        )
        return await self._store.list_graphs(
            workspace_id=workspace_id,
            clearance=int(subject.clearance),
        )

    async def publish_release(
        self,
        *,
        workspace_id: UUID,
        graph: KnowledgeGraphRecord,
        snapshot: GraphSnapshot,
        expected_base_hash: str | None,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeReleaseRecord:
        await self._authorization.authorize(
            subject=subject,
            resource=self._resource(
                graph_id=graph.graph_id,
                workspace_id=workspace_id,
                classification=graph.classification,
                lifecycle=graph.status,
            ),
            action=Action.KG_PUBLISH,
            environment=environment,
            request_id=request_id,
        )
        return await self._store.publish_release(
            workspace_id=workspace_id,
            graph_id=graph.graph_id,
            snapshot=snapshot,
            expected_base_hash=expected_base_hash,
            published_by=subject.subject_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def create_changeset(
        self,
        *,
        workspace_id: UUID,
        graph: KnowledgeGraphRecord,
        title: str,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeChangeSetRecord:
        await self._authorize_graph(
            graph=graph,
            workspace_id=workspace_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
            action=Action.KG_EDIT,
        )
        return await self._store.create_changeset(
            workspace_id=workspace_id,
            graph_id=graph.graph_id,
            title=title,
            author_id=subject.subject_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def list_changesets(
        self,
        *,
        workspace_id: UUID,
        graph: KnowledgeGraphRecord,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[KnowledgeChangeSetRecord, ...]:
        await self._authorize_graph(
            graph=graph,
            workspace_id=workspace_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
            action=Action.KG_READ,
        )
        return await self._store.list_changesets(workspace_id=workspace_id, graph_id=graph.graph_id)

    async def append_change_operation(
        self,
        *,
        workspace_id: UUID,
        graph: KnowledgeGraphRecord,
        changeset_id: UUID,
        operation: GraphChangeOperation,
        expected_version: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeChangeSetRecord:
        await self._authorize_graph(
            graph=graph,
            workspace_id=workspace_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
            action=Action.KG_EDIT,
        )
        return await self._store.append_change_operation(
            workspace_id=workspace_id,
            graph_id=graph.graph_id,
            changeset_id=changeset_id,
            actor_id=subject.subject_id,
            expected_version=expected_version,
            operation=operation,
        )

    async def submit_changeset(
        self,
        *,
        workspace_id: UUID,
        graph: KnowledgeGraphRecord,
        changeset_id: UUID,
        expected_version: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeChangeSetRecord:
        await self._authorize_graph(
            graph=graph,
            workspace_id=workspace_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
            action=Action.KG_EDIT,
        )
        return await self._store.submit_changeset(
            workspace_id=workspace_id,
            graph_id=graph.graph_id,
            changeset_id=changeset_id,
            actor_id=subject.subject_id,
            expected_version=expected_version,
        )

    async def review_changeset(
        self,
        *,
        workspace_id: UUID,
        graph: KnowledgeGraphRecord,
        changeset_id: UUID,
        decision: ChangeSetState,
        reason: str,
        expected_version: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeChangeSetRecord:
        await self._authorize_graph(
            graph=graph,
            workspace_id=workspace_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
            action=Action.KG_REVIEW,
        )
        return await self._store.review_changeset(
            workspace_id=workspace_id,
            graph_id=graph.graph_id,
            changeset_id=changeset_id,
            actor_id=subject.subject_id,
            decision=decision,
            reason=reason,
            expected_version=expected_version,
        )

    async def publish_changeset(
        self,
        *,
        workspace_id: UUID,
        graph: KnowledgeGraphRecord,
        changeset_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> tuple[KnowledgeChangeSetRecord, KnowledgeReleaseRecord]:
        await self._authorize_graph(
            graph=graph,
            workspace_id=workspace_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
            action=Action.KG_PUBLISH,
        )
        changeset, snapshot, base_hash = await self._store.prepare_changeset_publication(
            workspace_id=workspace_id,
            graph_id=graph.graph_id,
            changeset_id=changeset_id,
        )
        release = await self._store.publish_release(
            workspace_id=workspace_id,
            graph_id=graph.graph_id,
            snapshot=snapshot,
            expected_base_hash=base_hash,
            published_by=subject.subject_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        published = await self._store.mark_changeset_published(
            workspace_id=workspace_id,
            graph_id=graph.graph_id,
            changeset_id=changeset_id,
            release_id=release.release_id,
            expected_version=changeset.version,
        )
        return published, release

    async def list_releases(
        self,
        *,
        workspace_id: UUID,
        graph: KnowledgeGraphRecord,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[KnowledgeReleaseRecord, ...]:
        await self._authorize_graph(
            graph=graph,
            workspace_id=workspace_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
            action=Action.KG_READ,
        )
        return await self._store.list_releases(workspace_id=workspace_id, graph_id=graph.graph_id)

    async def activate_release(
        self,
        *,
        workspace_id: UUID,
        graph: KnowledgeGraphRecord,
        release_id: UUID,
        expected_graph_version: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeGraphRecord:
        await self._authorize_graph(
            graph=graph,
            workspace_id=workspace_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
            action=Action.KG_PUBLISH,
        )
        return await self._store.activate_release(
            workspace_id=workspace_id,
            graph_id=graph.graph_id,
            release_id=release_id,
            expected_graph_version=expected_graph_version,
        )

    async def get_graph(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> KnowledgeGraphRecord | None:
        graph = await self._store.get_graph(
            workspace_id=workspace_id,
            graph_id=graph_id,
            clearance=int(subject.clearance),
        )
        if graph is None:
            return None
        await self._authorization.authorize(
            subject=subject,
            resource=self._resource(
                graph_id=graph.graph_id,
                workspace_id=workspace_id,
                classification=graph.classification,
                lifecycle=graph.status,
            ),
            action=Action.KG_READ,
            environment=environment,
            request_id=request_id,
        )
        return graph

    async def get_release_snapshot(
        self,
        *,
        workspace_id: UUID,
        graph: KnowledgeGraphRecord,
        release_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        maximum_nodes: int,
    ) -> tuple[KnowledgeReleaseRecord, GraphSnapshot] | None:
        await self._authorization.authorize(
            subject=subject,
            resource=self._resource(
                graph_id=graph.graph_id,
                workspace_id=workspace_id,
                classification=graph.classification,
                lifecycle=graph.status,
            ),
            action=Action.KG_READ,
            environment=environment,
            request_id=request_id,
        )
        return await self._store.get_release_snapshot(
            workspace_id=workspace_id,
            graph_id=graph.graph_id,
            release_id=release_id,
            clearance=int(subject.clearance),
            maximum_nodes=maximum_nodes,
        )

    async def get_release_for_action(
        self,
        *,
        workspace_id: UUID,
        graph: KnowledgeGraphRecord,
        release_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        action: Action,
        maximum_nodes: int,
    ) -> tuple[KnowledgeReleaseRecord, GraphSnapshot] | None:
        if action not in {Action.KG_EXPORT, Action.SHARING_INVOKE}:
            raise ValueError("Unsupported knowledge release action.")
        await self._authorization.authorize(
            subject=subject,
            resource=self._resource(
                graph_id=graph.graph_id,
                workspace_id=workspace_id,
                classification=graph.classification,
                lifecycle=graph.status,
            ),
            action=action,
            environment=environment,
            request_id=request_id,
        )
        return await self._store.get_release_snapshot(
            workspace_id=workspace_id,
            graph_id=graph.graph_id,
            release_id=release_id,
            clearance=int(subject.clearance),
            maximum_nodes=maximum_nodes,
        )

    async def _authorize_graph(
        self,
        *,
        graph: KnowledgeGraphRecord,
        workspace_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        action: Action,
    ) -> None:
        await self._authorization.authorize(
            subject=subject,
            resource=self._resource(
                graph_id=graph.graph_id,
                workspace_id=workspace_id,
                classification=graph.classification,
                lifecycle=graph.status,
            ),
            action=action,
            environment=environment,
            request_id=request_id,
        )

    @staticmethod
    def _resource(
        *,
        graph_id: UUID,
        workspace_id: UUID,
        classification: Classification,
        lifecycle: str,
    ) -> ResourceAttributes:
        return ResourceAttributes(
            resource_id=graph_id,
            workspace_id=workspace_id,
            resource_type="knowledge_graph",
            owner_department_id=None,
            system_id=None,
            domain_id=None,
            classification=classification,
            lifecycle=lifecycle,
        )
