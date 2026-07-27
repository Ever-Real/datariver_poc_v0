from __future__ import annotations

from datariver.domain.authz import Classification
from datariver.domain.knowledge import GraphEntityKind, GraphSnapshot
from datariver.local_graphrag_fixture import fixture_operations


def test_local_graphrag_fixture_is_deterministic_and_valid() -> None:
    first = fixture_operations()
    second = fixture_operations()

    assert first == second
    assert [operation.sequence for operation in first] == [1, 2, 3, 4, 5]
    assert [operation.entity_kind for operation in first] == [
        GraphEntityKind.NODE,
        GraphEntityKind.NODE,
        GraphEntityKind.NODE,
        GraphEntityKind.EDGE,
        GraphEntityKind.EDGE,
    ]

    snapshot = GraphSnapshot()
    for operation in first:
        operation.require_classification_ceiling(
            maximum_classification=int(Classification.INTERNAL)
        )
        snapshot = operation.apply(snapshot)

    assert len(snapshot.nodes) == 3
    assert len(snapshot.edges) == 2
    assert {node.properties["name"] for node in snapshot.nodes.values()} == {
        "Silicon Wafer",
        "Photolithography",
        "Semiconductor Device",
    }
    assert all(
        node.classification == int(Classification.INTERNAL) for node in snapshot.nodes.values()
    )
    assert all(
        edge.classification == int(Classification.INTERNAL) for edge in snapshot.edges.values()
    )
