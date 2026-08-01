from datariver.domain.authz import SERVICE_ONLY_ACTIONS, Action
from datariver.seed.__main__ import (
    ADMINISTRATOR_ACTIONS,
    REVIEWER_ACTIONS,
    REVIEWER_SUBJECT_ID,
    SUBJECT_ID,
    graph_classification,
    seed_operation_ledger,
)
from datariver.seed.semiconductor import build_pack


def test_semiconductor_pack_is_deep_and_deterministic() -> None:
    first = build_pack()
    second = build_pack()

    assert len(first.catalog_assets) == 12
    assert len(first.snapshot.nodes) == 257
    assert len(first.snapshot.edges) == 279
    assert first.snapshot.content_hash() == second.snapshot.content_hash()
    assert first.logical_hash == second.logical_hash


def test_every_seed_assertion_has_synthetic_marker_and_provenance() -> None:
    pack = build_pack()

    assert all(node.properties["is_synthetic"] is True for node in pack.snapshot.nodes.values())
    assert all(node.provenance for node in pack.snapshot.nodes.values())
    assert all(edge.properties["is_synthetic"] is True for edge in pack.snapshot.edges.values())
    assert all(edge.provenance for edge in pack.snapshot.edges.values())


def test_seed_graph_envelope_is_the_maximum_assertion_classification() -> None:
    pack = build_pack()

    assertion_classifications = {
        *(node.classification for node in pack.snapshot.nodes.values()),
        *(edge.classification for edge in pack.snapshot.edges.values()),
    }

    assert assertion_classifications == {0, 1, 2}
    assert graph_classification(pack) == 2


def test_seed_publication_has_separate_authorized_publisher_and_reviewer_roles() -> None:
    assert SUBJECT_ID != REVIEWER_SUBJECT_ID
    assert Action.KG_PUBLISH.value in ADMINISTRATOR_ACTIONS
    assert Action.KG_REVIEW.value in REVIEWER_ACTIONS
    assert Action.KG_PUBLISH.value not in REVIEWER_ACTIONS


def test_seed_administrator_uses_the_default_human_capability_catalog() -> None:
    assert len(ADMINISTRATOR_ACTIONS) == 64
    assert Action.CHANGE_RAW_CREATE.value in ADMINISTRATOR_ACTIONS
    assert not {action.value for action in SERVICE_ONLY_ACTIONS} & set(ADMINISTRATOR_ACTIONS)


def test_seed_operation_ledger_exactly_covers_every_assertion() -> None:
    pack = build_pack()
    ledger = seed_operation_ledger(pack)

    assert len(ledger) == len(pack.snapshot.nodes) + len(pack.snapshot.edges) == 536
    assert [entry["sequence"] for entry in ledger] == list(range(1, 537))
    assert len({entry["id"] for entry in ledger}) == 536
    assert ledger == seed_operation_ledger(build_pack())


def test_semiconductor_pack_contains_quantitative_analysis_fixtures() -> None:
    pack = build_pack()
    facility_observations = [
        node
        for node in pack.snapshot.nodes.values()
        if node.entity_type == "MetricObservation"
        and node.properties["metric_family"] == "CAPACITY"
    ]
    demand_observations = [
        node
        for node in pack.snapshot.nodes.values()
        if node.entity_type == "MetricObservation" and node.properties["metric_family"] == "DEMAND"
    ]
    materials = [node for node in pack.snapshot.nodes.values() if node.entity_type == "Material"]
    equipment = [
        node for node in pack.snapshot.nodes.values() if node.entity_type == "EquipmentFamily"
    ]
    observation_edges = [
        edge for edge in pack.snapshot.edges.values() if edge.edge_type == "OBSERVES"
    ]

    assert len({node.properties["period"] for node in facility_observations}) == 12
    assert len(facility_observations) == 72
    assert len(demand_observations) == 96
    assert sum(node.properties["synthetic_qualified_source_count"] == 1 for node in materials) == 3
    assert max(node.properties["synthetic_lead_time_days"] for node in equipment) == 435
    assert len(observation_edges) == 168
