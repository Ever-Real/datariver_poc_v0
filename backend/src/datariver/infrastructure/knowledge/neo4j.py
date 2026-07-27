from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncManagedTransaction

from datariver.application.knowledge_pipeline_ports import (
    ScopedGraphEvidenceRetriever,
    VerifiedKnowledgeProjectionWriter,
)
from datariver.domain.common import ValidationError
from datariver.domain.knowledge import GraphEdge, GraphNode, GraphSnapshot, Provenance
from datariver.domain.knowledge_pipeline import (
    MAX_GRAPHRAG_EVIDENCE_ITEMS,
    MAX_GRAPHRAG_QUERY_NODES,
    GraphRagEvidence,
    ProjectionReceipt,
)


@dataclass(frozen=True, slots=True)
class CypherStatement:
    query: str
    parameters: Mapping[str, object]


class Neo4jQueryExecutor(Protocol):
    async def write_transaction(
        self, *, statements: Sequence[CypherStatement]
    ) -> tuple[Mapping[str, object], ...]: ...

    async def read(self, *, statement: CypherStatement) -> tuple[Mapping[str, object], ...]: ...


class BoltNeo4jQueryExecutor(Neo4jQueryExecutor):
    """Owned Bolt driver executing only server-defined parameterized statements."""

    def __init__(
        self,
        *,
        uri: str,
        username: str,
        password: str,
        database: str,
        connection_timeout_seconds: float,
        maximum_connection_pool_size: int,
    ) -> None:
        self._database = database
        self._driver: AsyncDriver = AsyncGraphDatabase.driver(
            uri,
            auth=(username, password),
            connection_timeout=connection_timeout_seconds,
            max_connection_pool_size=maximum_connection_pool_size,
        )

    async def close(self) -> None:
        await self._driver.close()

    @staticmethod
    async def _run_statements(
        transaction: AsyncManagedTransaction,
        statements: Sequence[CypherStatement],
    ) -> tuple[Mapping[str, object], ...]:
        returned: list[Mapping[str, object]] = []
        for statement in statements:
            result = await transaction.run(statement.query, dict(statement.parameters))
            returned.extend(await result.data())
        return tuple(returned)

    async def write_transaction(
        self, *, statements: Sequence[CypherStatement]
    ) -> tuple[Mapping[str, object], ...]:
        if not statements:
            raise ValueError("A Neo4j write transaction requires at least one statement.")
        async with self._driver.session(database=self._database) as session:
            return await session.execute_write(self._run_statements, tuple(statements))

    async def read(self, *, statement: CypherStatement) -> tuple[Mapping[str, object], ...]:
        async with self._driver.session(database=self._database) as session:
            return await session.execute_read(self._run_statements, (statement,))


class SemanticSeedSelector(Protocol):
    async def select_seed_ids(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        release_id: UUID,
        question: str,
        maximum_classification: int,
        limit: int,
    ) -> tuple[UUID, ...]: ...


_DELETE_RELEASE = """
MATCH (node:KnowledgeEntity {
  workspace_id: $workspace_id, graph_id: $graph_id, release_id: $release_id
})
DETACH DELETE node
"""

_DELETE_META = """
MATCH (deployment:KnowledgeProjection {
  workspace_id: $workspace_id, graph_id: $graph_id, release_id: $release_id
})
DELETE deployment
"""

_UPSERT_NODES = """
UNWIND $rows AS row
CREATE (node:KnowledgeEntity {
  workspace_id: $workspace_id,
  graph_id: $graph_id,
  release_id: $release_id,
  entity_id: row.entity_id,
  entity_type: row.entity_type,
  properties_json: row.properties_json,
  classification: row.classification,
  source_locator: row.source_locator,
  source_version: row.source_version,
  page_number: row.page_number,
  evidence_excerpt: row.evidence_excerpt,
  evidence_sha256: row.evidence_sha256,
  source_page_sha256: row.source_page_sha256,
  provenance_json: row.provenance_json
})
"""

_UPSERT_EDGES = """
UNWIND $rows AS row
MATCH (source:KnowledgeEntity {
  workspace_id: $workspace_id, graph_id: $graph_id,
  release_id: $release_id, entity_id: row.source_id
})
MATCH (target:KnowledgeEntity {
  workspace_id: $workspace_id, graph_id: $graph_id,
  release_id: $release_id, entity_id: row.target_id
})
CREATE (source)-[:KNOWLEDGE_RELATION {
  edge_id: row.edge_id,
  edge_type: row.edge_type,
  properties_json: row.properties_json,
  classification: row.classification,
  source_locator: row.source_locator,
  source_version: row.source_version,
  page_number: row.page_number,
  evidence_excerpt: row.evidence_excerpt,
  evidence_sha256: row.evidence_sha256,
  source_page_sha256: row.source_page_sha256,
  provenance_json: row.provenance_json
}]->(target)
"""

_CREATE_META = """
CREATE (:KnowledgeProjection {
  deployment_id: $deployment_id,
  workspace_id: $workspace_id,
  graph_id: $graph_id,
  release_id: $release_id,
  release_hash: $release_hash,
  node_count: $node_count,
  edge_count: $edge_count,
  state: 'VERIFYING'
})
"""

_MARK_VERIFIED = """
MATCH (deployment:KnowledgeProjection {
  deployment_id: $deployment_id,
  workspace_id: $workspace_id,
  graph_id: $graph_id,
  release_id: $release_id,
  release_hash: $release_hash,
  node_count: $node_count,
  edge_count: $edge_count,
  state: 'VERIFYING'
})
SET deployment.state = 'SHADOW_VERIFIED'
RETURN deployment.state AS state
"""

_VERIFY_RELEASE = """
MATCH (deployment:KnowledgeProjection {
  deployment_id: $deployment_id,
  workspace_id: $workspace_id,
  graph_id: $graph_id,
  release_id: $release_id
})
OPTIONAL MATCH (node:KnowledgeEntity {
  workspace_id: $workspace_id, graph_id: $graph_id, release_id: $release_id
})
WITH deployment, count(DISTINCT node) AS nodes
OPTIONAL MATCH (:KnowledgeEntity {
  workspace_id: $workspace_id, graph_id: $graph_id, release_id: $release_id
})-[edge:KNOWLEDGE_RELATION]->(:KnowledgeEntity {
  workspace_id: $workspace_id, graph_id: $graph_id, release_id: $release_id
})
RETURN deployment.release_hash AS release_hash, nodes, count(DISTINCT edge) AS edges,
       deployment.state AS state
"""

_READ_PROJECTED_NODES = """
MATCH (node:KnowledgeEntity {
  workspace_id: $workspace_id, graph_id: $graph_id, release_id: $release_id
})
RETURN node.entity_id AS entity_id, node.entity_type AS entity_type,
       node.properties_json AS properties_json, node.classification AS classification,
       node.provenance_json AS provenance_json
ORDER BY entity_id
"""

_READ_PROJECTED_EDGES = """
MATCH (source:KnowledgeEntity {
  workspace_id: $workspace_id, graph_id: $graph_id, release_id: $release_id
})-[edge:KNOWLEDGE_RELATION]->(target:KnowledgeEntity {
  workspace_id: $workspace_id, graph_id: $graph_id, release_id: $release_id
})
RETURN edge.edge_id AS edge_id, source.entity_id AS source_id,
       target.entity_id AS target_id, edge.edge_type AS edge_type,
       edge.properties_json AS properties_json, edge.classification AS classification,
       edge.provenance_json AS provenance_json
ORDER BY edge_id
"""

_READ_NODES = """
UNWIND $entity_ids AS entity_id
MATCH (node:KnowledgeEntity {
  workspace_id: $workspace_id, graph_id: $graph_id,
  release_id: $release_id, entity_id: entity_id
})
WHERE node.classification <= $maximum_classification
RETURN node.entity_id AS entity_id, node.entity_type AS entity_type,
       node.properties_json AS properties_json, node.classification AS classification,
       node.source_locator AS source_locator, node.source_version AS source_version,
       node.page_number AS page_number, node.evidence_excerpt AS evidence_excerpt,
       node.evidence_sha256 AS evidence_sha256,
       node.source_page_sha256 AS source_page_sha256
"""

_READ_EDGES = """
MATCH (source:KnowledgeEntity {
  workspace_id: $workspace_id, graph_id: $graph_id, release_id: $release_id
})-[edge:KNOWLEDGE_RELATION]->(target:KnowledgeEntity {
  workspace_id: $workspace_id, graph_id: $graph_id, release_id: $release_id
})
WHERE source.entity_id IN $entity_ids AND target.entity_id IN $entity_ids
  AND source.classification <= $maximum_classification
  AND target.classification <= $maximum_classification
  AND edge.classification <= $maximum_classification
  AND (size($edge_types) = 0 OR edge.edge_type IN $edge_types)
RETURN edge.edge_id AS edge_id, source.entity_id AS source_id,
       target.entity_id AS target_id, edge.edge_type AS edge_type,
       edge.properties_json AS properties_json, edge.classification AS classification,
       edge.source_locator AS source_locator, edge.source_version AS source_version,
       edge.page_number AS page_number, edge.evidence_excerpt AS evidence_excerpt,
       edge.evidence_sha256 AS evidence_sha256,
       edge.source_page_sha256 AS source_page_sha256
ORDER BY edge_id
LIMIT $limit
"""

_READ_NEIGHBORS_BOTH = """
UNWIND $entity_ids AS entity_id
MATCH (source:KnowledgeEntity {
  workspace_id: $workspace_id, graph_id: $graph_id,
  release_id: $release_id, entity_id: entity_id
})-[edge:KNOWLEDGE_RELATION]-(target:KnowledgeEntity {
  workspace_id: $workspace_id, graph_id: $graph_id, release_id: $release_id
})
WHERE source.classification <= $maximum_classification
  AND target.classification <= $maximum_classification
  AND edge.classification <= $maximum_classification
  AND (size($edge_types) = 0 OR edge.edge_type IN $edge_types)
RETURN DISTINCT target.entity_id AS entity_id
ORDER BY entity_id
LIMIT $limit
"""

_READ_NEIGHBORS_OUT = _READ_NEIGHBORS_BOTH.replace(
    ")-[edge:KNOWLEDGE_RELATION]-(target:", ")-[edge:KNOWLEDGE_RELATION]->(target:"
)
_READ_NEIGHBORS_IN = _READ_NEIGHBORS_BOTH.replace(
    ")-[edge:KNOWLEDGE_RELATION]-(target:", ")<-[edge:KNOWLEDGE_RELATION]-(target:"
)
_NEIGHBOR_QUERIES = {
    "BOTH": _READ_NEIGHBORS_BOTH,
    "OUT": _READ_NEIGHBORS_OUT,
    "IN": _READ_NEIGHBORS_IN,
}


def _common_scope(*, workspace_id: UUID, graph_id: UUID, release_id: UUID) -> dict[str, object]:
    return {
        "workspace_id": str(workspace_id),
        "graph_id": str(graph_id),
        "release_id": str(release_id),
    }


def _provenance_values(values: Sequence[Provenance]) -> dict[str, object]:
    if not values:
        raise ValidationError("Projection entities require provenance.")
    for value in values:
        value.validate()
    first = next((value for value in values if value.evidence_excerpt is not None), values[0])
    source_locator = str(first.source_locator)
    source_version = str(first.source_version)
    marker = "#page="
    page = None
    if marker in source_locator:
        try:
            page = int(source_locator.rsplit(marker, maxsplit=1)[1])
        except ValueError:
            page = None
    return {
        "source_locator": source_locator,
        "source_version": source_version,
        "page_number": page,
        "evidence_excerpt": first.evidence_excerpt,
        "evidence_sha256": first.evidence_sha256,
        "source_page_sha256": first.source_page_sha256,
        "provenance_json": json.dumps(
            [value.to_document() for value in values],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    }


def _json_object(value: object, *, field: str) -> dict[str, object]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError) as error:
        raise ValidationError(f"Neo4j returned invalid {field} JSON.") from error
    if not isinstance(parsed, dict):
        raise ValidationError(f"Neo4j returned non-object {field} JSON.")
    return parsed


def _provenance_from_json(value: object) -> tuple[Provenance, ...]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError) as error:
        raise ValidationError("Neo4j returned invalid provenance JSON.") from error
    if not isinstance(parsed, list) or not parsed:
        raise ValidationError("Neo4j projection entities require provenance JSON.")
    values: list[Provenance] = []
    for document in parsed:
        if not isinstance(document, dict):
            raise ValidationError("Neo4j returned a non-object provenance item.")
        try:
            provenance = Provenance.from_document(document)
        except (KeyError, TypeError, ValueError) as error:
            raise ValidationError("Neo4j returned incomplete provenance JSON.") from error
        provenance.validate()
        values.append(provenance)
    return tuple(values)


def _projected_snapshot(
    *,
    node_rows: Sequence[Mapping[str, object]],
    edge_rows: Sequence[Mapping[str, object]],
) -> GraphSnapshot:
    nodes: dict[UUID, GraphNode] = {}
    edges: dict[UUID, GraphEdge] = {}
    try:
        for row in node_rows:
            entity_id = UUID(str(row["entity_id"]))
            if entity_id in nodes:
                raise ValidationError("Neo4j returned duplicate projected node identifiers.")
            nodes[entity_id] = GraphNode(
                entity_id=entity_id,
                entity_type=str(row["entity_type"]),
                properties=_json_object(row["properties_json"], field="node properties"),
                classification=int(str(row["classification"])),
                provenance=_provenance_from_json(row["provenance_json"]),
            )
        for row in edge_rows:
            edge_id = UUID(str(row["edge_id"]))
            if edge_id in edges:
                raise ValidationError("Neo4j returned duplicate projected edge identifiers.")
            edges[edge_id] = GraphEdge(
                edge_id=edge_id,
                source_entity_id=UUID(str(row["source_id"])),
                target_entity_id=UUID(str(row["target_id"])),
                edge_type=str(row["edge_type"]),
                properties=_json_object(row["properties_json"], field="edge properties"),
                classification=int(str(row["classification"])),
                provenance=_provenance_from_json(row["provenance_json"]),
            )
    except (KeyError, TypeError, ValueError) as error:
        raise ValidationError("Neo4j returned an invalid projected graph row.") from error
    if any(
        edge.source_entity_id not in nodes or edge.target_entity_id not in nodes
        for edge in edges.values()
    ):
        raise ValidationError("Neo4j returned a projected edge with a missing endpoint.")
    return GraphSnapshot(nodes=nodes, edges=edges)


def _optional_string(value: object) -> str | None:
    return None if value is None else str(value)


def _page_number(value: object) -> int | None:
    return None if value is None else int(str(value))


class Neo4jKnowledgeProjectionAdapter(VerifiedKnowledgeProjectionWriter):
    def __init__(self, *, executor: Neo4jQueryExecutor) -> None:
        self._executor = executor

    async def replace_shadow_release(
        self,
        *,
        deployment_id: UUID,
        workspace_id: UUID,
        graph_id: UUID,
        release_id: UUID,
        release_hash: str,
        snapshot: GraphSnapshot,
    ) -> ProjectionReceipt:
        scope = _common_scope(
            workspace_id=workspace_id,
            graph_id=graph_id,
            release_id=release_id,
        )
        nodes: list[dict[str, object]] = []
        for node in snapshot.nodes.values():
            nodes.append(
                {
                    "entity_id": str(node.entity_id),
                    "entity_type": node.entity_type,
                    "properties_json": json.dumps(
                        node.properties,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "classification": node.classification,
                    **_provenance_values(node.provenance),
                }
            )
        edges: list[dict[str, object]] = []
        for edge in snapshot.edges.values():
            edges.append(
                {
                    "edge_id": str(edge.edge_id),
                    "source_id": str(edge.source_entity_id),
                    "target_id": str(edge.target_entity_id),
                    "edge_type": edge.edge_type,
                    "properties_json": json.dumps(
                        edge.properties,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "classification": edge.classification,
                    **_provenance_values(edge.provenance),
                }
            )
        await self._executor.write_transaction(
            statements=(
                CypherStatement(_DELETE_RELEASE, scope),
                CypherStatement(_DELETE_META, scope),
                CypherStatement(_UPSERT_NODES, {**scope, "rows": nodes}),
                CypherStatement(_UPSERT_EDGES, {**scope, "rows": edges}),
                CypherStatement(
                    _CREATE_META,
                    {
                        **scope,
                        "deployment_id": str(deployment_id),
                        "release_hash": release_hash,
                        "node_count": len(nodes),
                        "edge_count": len(edges),
                    },
                ),
            )
        )
        rows = await self._executor.read(
            statement=CypherStatement(
                _VERIFY_RELEASE,
                {**scope, "deployment_id": str(deployment_id)},
            )
        )
        if len(rows) != 1:
            raise ValidationError("Neo4j did not return one projection verification row.")
        row = rows[0]
        metadata = (
            str(row.get("release_hash", "")),
            int(str(row.get("nodes", -1))),
            int(str(row.get("edges", -1))),
            row.get("state"),
        )
        expected_metadata = (release_hash, len(nodes), len(edges), "VERIFYING")
        if metadata != expected_metadata:
            raise ValidationError("Neo4j projection metadata verification failed.")
        projected = _projected_snapshot(
            node_rows=await self._executor.read(
                statement=CypherStatement(_READ_PROJECTED_NODES, scope)
            ),
            edge_rows=await self._executor.read(
                statement=CypherStatement(_READ_PROJECTED_EDGES, scope)
            ),
        )
        actual_hash = projected.content_hash()
        if (
            actual_hash != release_hash
            or len(projected.nodes) != len(nodes)
            or len(projected.edges) != len(edges)
        ):
            raise ValidationError(
                "Neo4j projected content does not match the canonical PostgreSQL release."
            )
        marked = await self._executor.write_transaction(
            statements=(
                CypherStatement(
                    _MARK_VERIFIED,
                    {
                        **scope,
                        "deployment_id": str(deployment_id),
                        "release_hash": actual_hash,
                        "node_count": len(projected.nodes),
                        "edge_count": len(projected.edges),
                    },
                ),
            )
        )
        if len(marked) != 1 or marked[0].get("state") != "SHADOW_VERIFIED":
            raise ValidationError("Neo4j projection could not be marked as verified.")
        verified_rows = await self._executor.read(
            statement=CypherStatement(
                _VERIFY_RELEASE,
                {**scope, "deployment_id": str(deployment_id)},
            )
        )
        if len(verified_rows) != 1:
            raise ValidationError("Neo4j did not return the verified projection metadata.")
        verified = verified_rows[0]
        if (
            str(verified.get("release_hash", "")),
            int(str(verified.get("nodes", -1))),
            int(str(verified.get("edges", -1))),
            verified.get("state"),
        ) != (actual_hash, len(projected.nodes), len(projected.edges), "SHADOW_VERIFIED"):
            raise ValidationError("Neo4j verified projection metadata changed unexpectedly.")
        return ProjectionReceipt(
            deployment_id=deployment_id,
            workspace_id=workspace_id,
            graph_id=graph_id,
            release_id=release_id,
            release_hash=actual_hash,
            node_count=len(projected.nodes),
            edge_count=len(projected.edges),
            verified=True,
        )


class Neo4jScopedEvidenceRetriever(ScopedGraphEvidenceRetriever):
    def __init__(
        self,
        *,
        executor: Neo4jQueryExecutor,
        semantic_selector: SemanticSeedSelector,
    ) -> None:
        self._executor = executor
        self._semantic_selector = semantic_selector

    async def retrieve(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        release_id: UUID,
        question: str,
        start_node_id: UUID | None,
        direction: str,
        edge_types: frozenset[str],
        maximum_classification: int,
        maximum_hops: int,
        maximum_nodes: int,
    ) -> tuple[GraphRagEvidence, ...]:
        effective_maximum_nodes = min(maximum_nodes, MAX_GRAPHRAG_QUERY_NODES)
        selected = list(
            await self._semantic_selector.select_seed_ids(
                workspace_id=workspace_id,
                graph_id=graph_id,
                release_id=release_id,
                question=question,
                maximum_classification=maximum_classification,
                limit=effective_maximum_nodes,
            )
        )
        if start_node_id is not None and start_node_id not in selected:
            selected.insert(0, start_node_id)
        selected = selected[:effective_maximum_nodes]
        seen = set(selected)
        frontier = list(selected)
        scope = _common_scope(
            workspace_id=workspace_id,
            graph_id=graph_id,
            release_id=release_id,
        )
        for _ in range(maximum_hops):
            if not frontier or len(seen) >= effective_maximum_nodes:
                break
            rows = await self._executor.read(
                statement=CypherStatement(
                    _NEIGHBOR_QUERIES[direction],
                    {
                        **scope,
                        "entity_ids": [str(value) for value in frontier],
                        "maximum_classification": maximum_classification,
                        "edge_types": sorted(edge_types),
                        "limit": effective_maximum_nodes - len(seen),
                    },
                )
            )
            candidates = [UUID(str(row["entity_id"])) for row in rows]
            frontier = [entity_id for entity_id in candidates if entity_id not in seen]
            seen.update(frontier)
        if not seen:
            return ()
        node_rows = await self._executor.read(
            statement=CypherStatement(
                _READ_NODES,
                {
                    **scope,
                    "entity_ids": [
                        str(value) for value in sorted(seen, key=lambda value: value.int)
                    ],
                    "maximum_classification": maximum_classification,
                },
            )
        )
        evidence: list[GraphRagEvidence] = []
        for row in node_rows:
            entity_id = UUID(str(row["entity_id"]))
            evidence.append(
                GraphRagEvidence(
                    evidence_id=f"kg:{release_id}:{entity_id}",
                    entity_id=entity_id,
                    entity_type=str(row["entity_type"]),
                    properties=_json_object(row["properties_json"], field="node properties"),
                    source_locator=str(row["source_locator"]),
                    source_version=str(row["source_version"]),
                    page_number=_page_number(row.get("page_number")),
                    classification=int(str(row["classification"])),
                    evidence_excerpt=_optional_string(row.get("evidence_excerpt")),
                    evidence_sha256=_optional_string(row.get("evidence_sha256")),
                    source_page_sha256=_optional_string(row.get("source_page_sha256")),
                )
            )
        edge_limit = max(0, MAX_GRAPHRAG_EVIDENCE_ITEMS - len(evidence))
        edge_rows = (
            await self._executor.read(
                statement=CypherStatement(
                    _READ_EDGES,
                    {
                        **scope,
                        "entity_ids": [
                            str(value) for value in sorted(seen, key=lambda value: value.int)
                        ],
                        "maximum_classification": maximum_classification,
                        "edge_types": sorted(edge_types),
                        "limit": edge_limit,
                    },
                )
            )
            if edge_limit
            else ()
        )
        for row in edge_rows:
            edge_id = UUID(str(row["edge_id"]))
            edge_type = str(row["edge_type"])
            evidence.append(
                GraphRagEvidence(
                    evidence_id=f"kg:{release_id}:edge:{edge_id}",
                    entity_id=edge_id,
                    entity_type=edge_type,
                    properties=_json_object(row["properties_json"], field="edge properties"),
                    source_locator=str(row["source_locator"]),
                    source_version=str(row["source_version"]),
                    page_number=_page_number(row.get("page_number")),
                    classification=int(str(row["classification"])),
                    entity_kind="EDGE",
                    source_entity_id=UUID(str(row["source_id"])),
                    target_entity_id=UUID(str(row["target_id"])),
                    edge_type=edge_type,
                    evidence_excerpt=_optional_string(row.get("evidence_excerpt")),
                    evidence_sha256=_optional_string(row.get("evidence_sha256")),
                    source_page_sha256=_optional_string(row.get("source_page_sha256")),
                )
            )
        return tuple(evidence)
