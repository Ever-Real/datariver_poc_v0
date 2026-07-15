from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID

from datariver.domain.common import ConflictError, ValidationError, uuid7


class GraphType(StrEnum):
    CATALOG_MIRROR = "CATALOG_MIRROR"
    CURATED_KNOWLEDGE = "CURATED_KNOWLEDGE"
    ANALYTIC_PRODUCT = "ANALYTIC_PRODUCT"


class ChangeSetState(StrEnum):
    DRAFT = "DRAFT"
    REVIEW = "REVIEW"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"


class ChangeOperationType(StrEnum):
    UPSERT = "UPSERT"
    DELETE = "DELETE"


class GraphEntityKind(StrEnum):
    NODE = "NODE"
    EDGE = "EDGE"


@dataclass(frozen=True, slots=True)
class Provenance:
    source_ref: str
    source_locator: str
    source_version: str
    method: str
    confidence: float

    def validate(self) -> None:
        if not self.source_ref or not self.source_locator or not self.source_version:
            raise ValidationError("Every graph assertion requires source provenance.")
        if not 0 <= self.confidence <= 1:
            raise ValidationError("Provenance confidence must be between 0 and 1.")


@dataclass(frozen=True, slots=True)
class GraphNode:
    entity_id: UUID
    entity_type: str
    properties: dict[str, Any]
    classification: int
    provenance: tuple[Provenance, ...]


@dataclass(frozen=True, slots=True)
class GraphEdge:
    edge_id: UUID
    source_entity_id: UUID
    target_entity_id: UUID
    edge_type: str
    properties: dict[str, Any]
    classification: int
    provenance: tuple[Provenance, ...]


@dataclass(frozen=True, slots=True)
class Ontology:
    version_id: UUID
    entity_types: frozenset[str]
    edge_types: frozenset[str]


@dataclass(frozen=True, slots=True)
class GraphChangeOperation:
    sequence: int
    operation: ChangeOperationType
    entity_kind: GraphEntityKind
    stable_entity_id: UUID
    document: dict[str, Any]
    provenance: tuple[Provenance, ...]
    confidence: float

    def validate(self) -> None:
        if self.sequence < 1:
            raise ValidationError("Change operation sequence must be positive.")
        if not 0 <= self.confidence <= 1:
            raise ValidationError("Change operation confidence must be between 0 and 1.")
        if not self.provenance:
            raise ValidationError("Every graph edit requires provenance.")
        for item in self.provenance:
            item.validate()
        if self.operation is ChangeOperationType.DELETE:
            if self.document:
                raise ValidationError("DELETE operations cannot contain an entity document.")
            return
        required = (
            {"entity_type", "properties", "classification"}
            if self.entity_kind is GraphEntityKind.NODE
            else {"source_id", "target_id", "edge_type", "properties", "classification"}
        )
        if set(self.document) != required:
            raise ValidationError(
                "The typed graph edit document has invalid fields.",
                details={"required_fields": sorted(required)},
            )
        if not isinstance(self.document["properties"], dict):
            raise ValidationError("Graph edit properties must be an object.")
        classification = self.document["classification"]
        if not isinstance(classification, int) or isinstance(classification, bool):
            raise ValidationError("Graph edit classification must be an integer.")
        if not 0 <= classification <= 3:
            raise ValidationError("Graph edit classification must be between 0 and 3.")

    def apply(self, snapshot: GraphSnapshot) -> GraphSnapshot:
        self.validate()
        nodes = dict(snapshot.nodes)
        edges = dict(snapshot.edges)
        if self.operation is ChangeOperationType.DELETE:
            target = nodes if self.entity_kind is GraphEntityKind.NODE else edges
            if self.stable_entity_id not in target:
                raise ValidationError("The graph edit delete target does not exist.")
            del target[self.stable_entity_id]
            return GraphSnapshot(nodes=nodes, edges=edges)
        if self.entity_kind is GraphEntityKind.NODE:
            nodes[self.stable_entity_id] = GraphNode(
                entity_id=self.stable_entity_id,
                entity_type=str(self.document["entity_type"]),
                properties=dict(self.document["properties"]),
                classification=int(self.document["classification"]),
                provenance=self.provenance,
            )
        else:
            try:
                source_id = UUID(str(self.document["source_id"]))
                target_id = UUID(str(self.document["target_id"]))
            except (TypeError, ValueError) as error:
                raise ValidationError("Graph edge endpoints must be UUIDs.") from error
            edges[self.stable_entity_id] = GraphEdge(
                edge_id=self.stable_entity_id,
                source_entity_id=source_id,
                target_entity_id=target_id,
                edge_type=str(self.document["edge_type"]),
                properties=dict(self.document["properties"]),
                classification=int(self.document["classification"]),
                provenance=self.provenance,
            )
        return GraphSnapshot(nodes=nodes, edges=edges)


def apply_change_operations(
    snapshot: GraphSnapshot, operations: tuple[GraphChangeOperation, ...]
) -> GraphSnapshot:
    sequences = [item.sequence for item in operations]
    if len(sequences) != len(set(sequences)):
        raise ValidationError("Change operation sequences must be unique.")
    result = snapshot
    for operation in sorted(operations, key=lambda item: item.sequence):
        result = operation.apply(result)
    return result


@dataclass(slots=True)
class GraphChangeSet:
    changeset_id: UUID
    graph_id: UUID
    author_id: UUID
    state: ChangeSetState
    version: int

    @classmethod
    def create(cls, *, graph_id: UUID, author_id: UUID) -> GraphChangeSet:
        return cls(
            changeset_id=uuid7(),
            graph_id=graph_id,
            author_id=author_id,
            state=ChangeSetState.DRAFT,
            version=1,
        )

    def add_operation(
        self,
        *,
        actor_id: UUID,
        expected_version: int,
        operation: GraphChangeOperation,
    ) -> None:
        self._assert_version(expected_version)
        if actor_id != self.author_id:
            raise ValidationError("Only the changeset author can edit it.")
        if self.state is not ChangeSetState.DRAFT:
            raise ValidationError("Only a draft changeset can be edited.")
        operation.validate()
        self.version += 1

    def submit(
        self,
        *,
        actor_id: UUID,
        expected_version: int,
        snapshot: GraphSnapshot,
        ontology: Ontology,
    ) -> None:
        self._assert_version(expected_version)
        if actor_id != self.author_id:
            raise ValidationError("Only the changeset author can submit it for review.")
        if self.state is not ChangeSetState.DRAFT:
            raise ValidationError("Only a draft changeset can be submitted.")
        violations = snapshot.validate(ontology)
        if violations:
            raise ValidationError(
                "The changeset cannot enter review.", details={"violations": violations}
            )
        self.state = ChangeSetState.REVIEW
        self.version += 1

    def review(
        self,
        *,
        actor_id: UUID,
        decision: ChangeSetState,
        expected_version: int,
    ) -> None:
        self._assert_version(expected_version)
        if actor_id == self.author_id:
            raise ValidationError("A changeset author cannot review their own changes.")
        if self.state is not ChangeSetState.REVIEW:
            raise ValidationError("Only a changeset in review can receive a decision.")
        if decision not in {ChangeSetState.APPROVED, ChangeSetState.REJECTED}:
            raise ValidationError("The changeset review decision is invalid.")
        self.state = decision
        self.version += 1

    def mark_published(self, *, expected_version: int) -> None:
        self._assert_version(expected_version)
        if self.state is not ChangeSetState.APPROVED:
            raise ValidationError("Only an approved changeset can be published.")
        self.state = ChangeSetState.PUBLISHED
        self.version += 1

    def _assert_version(self, expected_version: int) -> None:
        if self.version != expected_version:
            raise ConflictError("The changeset version is stale.")


@dataclass(slots=True)
class GraphSnapshot:
    nodes: dict[UUID, GraphNode] = field(default_factory=dict)
    edges: dict[UUID, GraphEdge] = field(default_factory=dict)

    def validate(self, ontology: Ontology) -> list[str]:
        errors: list[str] = []
        for node in self.nodes.values():
            if not 0 <= node.classification <= 3:
                errors.append(f"NODE_CLASSIFICATION_INVALID:{node.entity_id}")
            if node.entity_type not in ontology.entity_types:
                errors.append(f"NODE_TYPE_NOT_ALLOWED:{node.entity_id}:{node.entity_type}")
            if not node.provenance:
                errors.append(f"NODE_PROVENANCE_REQUIRED:{node.entity_id}")
            for provenance in node.provenance:
                try:
                    provenance.validate()
                except ValidationError as error:
                    errors.append(f"NODE_PROVENANCE_INVALID:{node.entity_id}:{error.message}")
        for edge in self.edges.values():
            if not 0 <= edge.classification <= 3:
                errors.append(f"EDGE_CLASSIFICATION_INVALID:{edge.edge_id}")
            if edge.edge_type not in ontology.edge_types:
                errors.append(f"EDGE_TYPE_NOT_ALLOWED:{edge.edge_id}:{edge.edge_type}")
            if edge.source_entity_id not in self.nodes or edge.target_entity_id not in self.nodes:
                errors.append(f"EDGE_ENDPOINT_MISSING:{edge.edge_id}")
            if not edge.provenance:
                errors.append(f"EDGE_PROVENANCE_REQUIRED:{edge.edge_id}")
            for provenance in edge.provenance:
                try:
                    provenance.validate()
                except ValidationError as error:
                    errors.append(f"EDGE_PROVENANCE_INVALID:{edge.edge_id}:{error.message}")
        return sorted(errors)

    def content_hash(self) -> str:
        document = {
            "nodes": [
                {
                    "id": str(node.entity_id),
                    "type": node.entity_type,
                    "properties": node.properties,
                    "classification": node.classification,
                    "provenance": [
                        {
                            "source_ref": item.source_ref,
                            "source_locator": item.source_locator,
                            "source_version": item.source_version,
                            "method": item.method,
                            "confidence": item.confidence,
                        }
                        for item in node.provenance
                    ],
                }
                for node in sorted(self.nodes.values(), key=lambda item: item.entity_id.int)
            ],
            "edges": [
                {
                    "id": str(edge.edge_id),
                    "source": str(edge.source_entity_id),
                    "target": str(edge.target_entity_id),
                    "type": edge.edge_type,
                    "properties": edge.properties,
                    "classification": edge.classification,
                    "provenance": [
                        {
                            "source_ref": item.source_ref,
                            "source_locator": item.source_locator,
                            "source_version": item.source_version,
                            "method": item.method,
                            "confidence": item.confidence,
                        }
                        for item in edge.provenance
                    ],
                }
                for edge in sorted(self.edges.values(), key=lambda item: item.edge_id.int)
            ],
        }
        canonical = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def bounded_neighbors(
        self,
        *,
        node_id: UUID,
        direction: str,
        edge_types: frozenset[str],
        maximum_hops: int,
        maximum_nodes: int,
    ) -> tuple[GraphSnapshot, bool]:
        if node_id not in self.nodes:
            raise ValidationError("The analysis start node is unavailable.")
        if direction not in {"IN", "OUT", "BOTH"} or not 1 <= maximum_hops <= 3:
            raise ValidationError("The bounded-neighbor analysis parameters are invalid.")
        selected = {node_id}
        frontier = {node_id}
        truncated = False
        for _ in range(maximum_hops):
            candidates: set[UUID] = set()
            for edge in self.edges.values():
                if edge_types and edge.edge_type not in edge_types:
                    continue
                if direction in {"OUT", "BOTH"} and edge.source_entity_id in frontier:
                    candidates.add(edge.target_entity_id)
                if direction in {"IN", "BOTH"} and edge.target_entity_id in frontier:
                    candidates.add(edge.source_entity_id)
            unseen = sorted(candidates - selected, key=lambda value: value.int)
            remaining = maximum_nodes - len(selected)
            if len(unseen) > remaining:
                unseen = unseen[: max(remaining, 0)]
                truncated = True
            frontier = set(unseen)
            selected.update(frontier)
            if not frontier or len(selected) >= maximum_nodes:
                break
        edges = {
            edge_id: edge
            for edge_id, edge in self.edges.items()
            if edge.source_entity_id in selected
            and edge.target_entity_id in selected
            and (not edge_types or edge.edge_type in edge_types)
        }
        return (
            GraphSnapshot(
                nodes={entity_id: self.nodes[entity_id] for entity_id in selected},
                edges=edges,
            ),
            truncated,
        )


@dataclass(frozen=True, slots=True)
class GraphRelease:
    release_id: UUID
    graph_id: UUID
    release_no: int
    ontology_version_id: UUID
    content_hash: str
    node_count: int
    edge_count: int

    @classmethod
    def publish(
        cls,
        *,
        graph_id: UUID,
        release_no: int,
        ontology: Ontology,
        snapshot: GraphSnapshot,
        expected_base_hash: str | None,
        actual_base_hash: str | None,
    ) -> GraphRelease:
        if expected_base_hash != actual_base_hash:
            raise ConflictError("The graph base release changed before publication.")
        errors = snapshot.validate(ontology)
        if errors:
            raise ValidationError(
                "The graph snapshot cannot be published.", details={"violations": errors}
            )
        return cls(
            release_id=uuid7(),
            graph_id=graph_id,
            release_no=release_no,
            ontology_version_id=ontology.version_id,
            content_hash=snapshot.content_hash(),
            node_count=len(snapshot.nodes),
            edge_count=len(snapshot.edges),
        )
