from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Text, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.dto import KnowledgeEvidenceCandidate
from datariver.application.evidence import build_evidence_chunk
from datariver.application.ports import KnowledgeEvidenceReader
from datariver.domain.authz import Classification
from datariver.infrastructure.db.knowledge import governed_release_ids
from datariver.infrastructure.db.models.knowledge import (
    GraphModel,
    ReleaseModel,
    ReleaseNodeModel,
)


class SqlKnowledgeEvidenceReader(KnowledgeEvidenceReader):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search_active_nodes(
        self,
        *,
        workspace_id: UUID,
        query: str,
        maximum_classification: int,
        limit: int,
    ) -> tuple[KnowledgeEvidenceCandidate, ...]:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        rows = list(
            (
                await self._session.execute(
                    select(GraphModel, ReleaseModel, ReleaseNodeModel)
                    .join(ReleaseModel, ReleaseModel.id == GraphModel.active_release_id)
                    .join(ReleaseNodeModel, ReleaseNodeModel.release_id == ReleaseModel.id)
                    .where(
                        GraphModel.workspace_id == workspace_id,
                        GraphModel.classification <= maximum_classification,
                        ReleaseModel.id.in_(
                            governed_release_ids(
                                workspace_id=workspace_id,
                                graph_id=ReleaseModel.graph_id,
                            ).correlate(ReleaseModel)
                        ),
                        ReleaseNodeModel.classification <= maximum_classification,
                        or_(
                            ReleaseNodeModel.entity_type.ilike(pattern, escape="\\"),
                            cast(ReleaseNodeModel.properties, Text).ilike(pattern, escape="\\"),
                        ),
                    )
                    .order_by(GraphModel.name, ReleaseNodeModel.entity_id)
                    .limit(limit)
                )
            ).all()
        )
        return tuple(
            self._candidate(
                workspace_id=workspace_id,
                graph=graph,
                release=release,
                node=node,
            )
            for graph, release, node in rows
        )

    async def get_active_nodes_by_resource_ids(
        self,
        *,
        workspace_id: UUID,
        resource_ids: Sequence[UUID],
    ) -> tuple[KnowledgeEvidenceCandidate, ...]:
        unique_ids = tuple(dict.fromkeys(resource_ids))
        if not unique_ids:
            return ()
        rows = (
            await self._session.execute(
                select(GraphModel, ReleaseModel, ReleaseNodeModel)
                .join(ReleaseModel, ReleaseModel.id == GraphModel.active_release_id)
                .join(ReleaseNodeModel, ReleaseNodeModel.release_id == ReleaseModel.id)
                .where(
                    GraphModel.workspace_id == workspace_id,
                    ReleaseModel.id.in_(
                        governed_release_ids(
                            workspace_id=workspace_id,
                            graph_id=ReleaseModel.graph_id,
                        ).correlate(ReleaseModel)
                    ),
                    ReleaseNodeModel.entity_id.in_(unique_ids),
                )
                .order_by(ReleaseNodeModel.entity_id, GraphModel.id)
            )
        ).all()
        return tuple(
            self._candidate(
                workspace_id=workspace_id,
                graph=graph,
                release=release,
                node=node,
            )
            for graph, release, node in rows
        )

    @staticmethod
    def _candidate(
        *,
        workspace_id: UUID,
        graph: GraphModel,
        release: ReleaseModel,
        node: ReleaseNodeModel,
    ) -> KnowledgeEvidenceCandidate:
        classification = Classification(max(graph.classification, node.classification))
        name = str(
            node.properties.get("name")
            or node.properties.get("label")
            or node.properties.get("title")
            or f"{node.entity_type} {node.entity_id}"
        )[:500]
        description_value = node.properties.get("description") or node.properties.get("summary")
        return KnowledgeEvidenceCandidate(
            evidence=build_evidence_chunk(
                workspace_id=workspace_id,
                resource_id=node.entity_id,
                classification=classification,
                system_id=None,
                domain_id=None,
                owner_department_id=None,
                name=name,
                description=str(description_value)[:1000] if description_value else None,
                source_locator=(
                    f"urn:datariver:knowledge-node:{graph.id}:{release.id}:{node.entity_id}"
                ),
                source_version=release.content_hash,
                effective_from=release.published_at,
                extraction_method="KNOWLEDGE_RELEASE_NODE_V1",
                source_type="KNOWLEDGE_NODE",
            ),
            graph_id=graph.id,
            classification=classification,
        )
