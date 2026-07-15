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
