import inspect
from collections.abc import Callable
from uuid import uuid4

import pytest

from datariver.domain.common import ConflictError, ValidationError
from datariver.domain.knowledge import (
    ChangeOperationType,
    ChangeSetState,
    GraphChangeOperation,
    GraphChangeSet,
    GraphEdge,
    GraphEntityKind,
    GraphNode,
    GraphRelease,
    GraphSnapshot,
    Ontology,
    Provenance,
    apply_change_operations,
)
from datariver.interfaces.http.routes.knowledge import (
    project_knowledge_release,
    query_knowledge_release,
)


def provenance() -> Provenance:
    return Provenance(
        source_ref="seed:semiconductor",
        source_locator="companies.csv#row=1",
        source_version="1.0.0",
        method="deterministic_import",
        confidence=1.0,
    )


@pytest.mark.parametrize(
    "operation,adapter_error",
    [
        (project_knowledge_release, "projection adapter is unavailable"),
        (query_knowledge_release, "query adapter is unavailable"),
    ],
)
def test_knowledge_routes_authorize_canonical_resources_before_revealing_adapter_state(
    operation: Callable[..., object],
    adapter_error: str,
) -> None:
    source = inspect.getsource(operation)

    assert source.index("service.get_graph(") < source.index(adapter_error)
    if operation is project_knowledge_release:
        assert source.index("service.authorize_projection(") < source.index(adapter_error)
    else:
        assert source.index("service.get_release_for_graphrag(") < source.index(adapter_error)


def test_graphrag_route_releases_request_transaction_before_external_inference() -> None:
    source = inspect.getsource(query_knowledge_release)

    transaction_release = source.index("await session.commit()")
    runtime_construction = source.index("runtime = _knowledge_adapters(request)")
    inference = source.index(").answer(")
    assert transaction_release < runtime_construction < inference
    assert "session_factory=container.database.session_factory" in source
    assert "subject_id=context.subject.subject_id" in source


def valid_graph() -> tuple[Ontology, GraphSnapshot]:
    source_id = uuid4()
    target_id = uuid4()
    ontology = Ontology(
        version_id=uuid4(),
        entity_types=frozenset({"Company", "Facility"}),
        edge_types=frozenset({"OWNS"}),
    )
    snapshot = GraphSnapshot(
        nodes={
            source_id: GraphNode(source_id, "Company", {"name": "A"}, 1, (provenance(),)),
            target_id: GraphNode(target_id, "Facility", {"name": "Fab"}, 1, (provenance(),)),
        },
        edges={
            (edge_id := uuid4()): GraphEdge(
                edge_id,
                source_id,
                target_id,
                "OWNS",
                {},
                1,
                (provenance(),),
            )
        },
    )
    return ontology, snapshot


def test_release_hash_is_deterministic() -> None:
    ontology, snapshot = valid_graph()

    first = GraphRelease.publish(
        graph_id=uuid4(),
        release_no=1,
        ontology=ontology,
        snapshot=snapshot,
        expected_base_hash=None,
        actual_base_hash=None,
    )
    second = GraphRelease.publish(
        graph_id=first.graph_id,
        release_no=1,
        ontology=ontology,
        snapshot=snapshot,
        expected_base_hash=None,
        actual_base_hash=None,
    )

    assert first.content_hash == second.content_hash
    assert first.node_count == 2
    assert first.edge_count == 1


def test_publish_rejects_missing_edge_endpoint() -> None:
    ontology, snapshot = valid_graph()
    edge = next(iter(snapshot.edges.values()))
    snapshot.nodes.pop(edge.target_entity_id)

    with pytest.raises(ValidationError) as error:
        GraphRelease.publish(
            graph_id=uuid4(),
            release_no=1,
            ontology=ontology,
            snapshot=snapshot,
            expected_base_hash=None,
            actual_base_hash=None,
        )

    assert "EDGE_ENDPOINT_MISSING" in str(error.value.details)


def test_publish_rejects_changed_base_release() -> None:
    ontology, snapshot = valid_graph()

    with pytest.raises(ConflictError):
        GraphRelease.publish(
            graph_id=uuid4(),
            release_no=2,
            ontology=ontology,
            snapshot=snapshot,
            expected_base_hash="old",
            actual_base_hash="new",
        )


def test_snapshot_rejects_content_above_graph_classification_envelope() -> None:
    ontology, snapshot = valid_graph()
    node = next(iter(snapshot.nodes.values()))
    snapshot.nodes[node.entity_id] = GraphNode(
        entity_id=node.entity_id,
        entity_type=node.entity_type,
        properties=node.properties,
        classification=3,
        provenance=node.provenance,
    )

    violations = snapshot.validate(ontology, maximum_classification=1)

    assert violations == [f"NODE_CLASSIFICATION_EXCEEDS_GRAPH:{node.entity_id}:3:1"]


def test_change_operation_rejects_classification_above_graph_before_persistence() -> None:
    operation = GraphChangeOperation(
        sequence=1,
        operation=ChangeOperationType.UPSERT,
        entity_kind=GraphEntityKind.NODE,
        stable_entity_id=uuid4(),
        document={
            "entity_type": "Company",
            "properties": {"name": "Restricted supplier"},
            "classification": 3,
        },
        provenance=(provenance(),),
        confidence=1.0,
    )

    with pytest.raises(ValidationError, match="exceeds the graph"):
        operation.require_classification_ceiling(maximum_classification=1)


def test_neighbor_analysis_is_typed_bounded_and_directional() -> None:
    _, snapshot = valid_graph()
    edge = next(iter(snapshot.edges.values()))

    outbound, truncated = snapshot.bounded_neighbors(
        node_id=edge.source_entity_id,
        direction="OUT",
        edge_types=frozenset({"OWNS"}),
        maximum_hops=1,
        maximum_nodes=10,
    )
    inbound, _ = snapshot.bounded_neighbors(
        node_id=edge.source_entity_id,
        direction="IN",
        edge_types=frozenset({"OWNS"}),
        maximum_hops=1,
        maximum_nodes=10,
    )

    assert len(outbound.nodes) == 2
    assert len(outbound.edges) == 1
    assert truncated is False
    assert len(inbound.nodes) == 1


def test_typed_change_operations_create_a_valid_versioned_snapshot() -> None:
    ontology, base = valid_graph()
    entity_id = uuid4()
    operation = GraphChangeOperation(
        sequence=1,
        operation=ChangeOperationType.UPSERT,
        entity_kind=GraphEntityKind.NODE,
        stable_entity_id=entity_id,
        document={
            "entity_type": "Company",
            "properties": {"name": "New supplier"},
            "classification": 1,
        },
        provenance=(provenance(),),
        confidence=0.9,
    )

    result = apply_change_operations(base, (operation,))

    assert result.nodes[entity_id].properties["name"] == "New supplier"
    assert result.validate(ontology) == []


def test_delete_requires_explicit_edge_cleanup() -> None:
    ontology, base = valid_graph()
    edge = next(iter(base.edges.values()))
    operation = GraphChangeOperation(
        sequence=1,
        operation=ChangeOperationType.DELETE,
        entity_kind=GraphEntityKind.NODE,
        stable_entity_id=edge.target_entity_id,
        document={},
        provenance=(provenance(),),
        confidence=1.0,
    )

    result = apply_change_operations(base, (operation,))

    assert any(value.startswith("EDGE_ENDPOINT_MISSING") for value in result.validate(ontology))


def test_changeset_requires_independent_review_before_publication() -> None:
    ontology, snapshot = valid_graph()
    author = uuid4()
    changeset = GraphChangeSet.create(graph_id=uuid4(), author_id=author)
    changeset.submit(
        actor_id=author,
        expected_version=changeset.version,
        snapshot=snapshot,
        ontology=ontology,
    )

    with pytest.raises(ValidationError, match="cannot review"):
        changeset.review(
            actor_id=author,
            decision=ChangeSetState.APPROVED,
            expected_version=changeset.version,
        )

    changeset.review(
        actor_id=uuid4(),
        decision=ChangeSetState.APPROVED,
        expected_version=changeset.version,
    )
    changeset.mark_published(expected_version=changeset.version)
    assert changeset.state is ChangeSetState.PUBLISHED
