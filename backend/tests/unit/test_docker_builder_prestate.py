from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
try:
    import docker_builder_prestate as prestate
    import docker_capacity as capacity
    import reconcile_docker_builder_selection as operator
finally:
    sys.path.remove(str(SCRIPTS))


def _rows() -> list[dict[str, object]]:
    return [
        {
            "Current": True,
            "Driver": "docker-container",
            "Name": "managed-builder",
            "Nodes": [
                {
                    "Endpoint": "desktop-linux",
                    "Name": "managed-builder0",
                    "Status": "running",
                }
            ],
        },
        {
            "Current": False,
            "Driver": "docker",
            "Name": "desktop-linux",
            "Nodes": [
                {
                    "Endpoint": "desktop-linux",
                    "Name": "desktop-linux",
                    "Status": "running",
                }
            ],
        },
    ]


def _encoded(rows: list[dict[str, object]]) -> str:
    return "\n".join(json.dumps(row) for row in rows)


def _observation(rows: list[dict[str, object]]) -> prestate.BuilderPrestateSnapshot:
    views: list[prestate.BuilderPrestateRow] = []
    seen_names: set[object] = set()
    for row in rows:
        if row["Name"] in seen_names:
            continue
        seen_names.add(row["Name"])
        nodes = row["Nodes"]
        assert isinstance(nodes, list)
        node = nodes[0]
        assert isinstance(node, dict)
        name = row["Name"]
        node_name = node["Name"]
        views.append(
            prestate.BuilderPrestateRow(
                current=row["Current"] is True,
                driver=capacity.classify_driver(str(row["Driver"])),
                status=capacity.classify_status(str(node.get("Status", ""))),
                name_is_context=name == "desktop-linux",
                node_name_is_builder=node_name == name,
                node_name_is_context=node_name == "desktop-linux",
                endpoint_is_context=node["Endpoint"] == "desktop-linux",
                builder_error=capacity._error_shape(row, "Err"),
                node_error=capacity._error_shape(node, "Err"),
            )
        )
    return prestate.observe_builder_prestate(
        tuple(views),
        row_count=len(rows),
        context_target_count=sum(row["Name"] == "desktop-linux" for row in rows),
        version=prestate.BuildxVersionObservation(
            prestate.BuildxAuthorityPredicate.UPSTREAM_V0_35_0,
            prestate.BuildxDistributionPredicate.NOT_APPLICABLE,
        ),
    )


def _mutate(rows: list[dict[str, object]], case: str) -> None:
    prior_nodes = rows[0]["Nodes"]
    target_nodes = rows[1]["Nodes"]
    assert isinstance(prior_nodes, list) and isinstance(prior_nodes[0], dict)
    assert isinstance(target_nodes, list) and isinstance(target_nodes[0], dict)
    if case == "canonical":
        rows[0]["Current"], rows[1]["Current"] = False, True
    elif case == "duplicate":
        rows.append(json.loads(json.dumps(rows[1])))
    elif case == "current-count":
        rows[1]["Current"] = True
    elif case == "prior-driver":
        rows[0]["Driver"] = "remote"
    elif case == "prior-status":
        prior_nodes[0]["Status"] = "stopped"
    elif case == "target-missing":
        rows.pop()
    elif case == "target-driver":
        rows[1]["Driver"] = "remote"
    elif case == "target-status":
        target_nodes[0]["Status"] = "stopped"
    elif case == "target-node":
        target_nodes[0]["Name"] = "other"
    elif case == "target-endpoint":
        target_nodes[0]["Endpoint"] = "other"


@pytest.mark.parametrize(
    ("case", "predicate", "message"),
    (
        ("pass", "PASS", None),
        ("canonical", "CURRENT_ALREADY_CANONICAL", "DOCKER_BUILDER_SELECTION_PRESTATE_INVALID"),
        ("duplicate", "INVENTORY_DUPLICATE", "DOCKER_BUILDER_SELECTION_INVENTORY_DUPLICATE"),
        ("current-count", "CURRENT_COUNT", "DOCKER_BUILDER_SELECTION_PRESTATE_INVALID"),
        ("prior-driver", "PRIOR_DRIVER", "DOCKER_BUILDER_SELECTION_PRESTATE_INVALID"),
        ("prior-status", "PRIOR_STATUS", "DOCKER_BUILDER_SELECTION_PRESTATE_INVALID"),
        ("target-missing", "TARGET_MISSING", "DOCKER_BUILDER_SELECTION_TARGET_INVALID"),
        ("target-driver", "TARGET_DRIVER", "DOCKER_BUILDER_SELECTION_TARGET_INVALID"),
        ("target-status", "TARGET_STATUS", "DOCKER_BUILDER_SELECTION_TARGET_INVALID"),
        ("target-node", "TARGET_NODE_NAME", "DOCKER_BUILDER_SELECTION_TARGET_INVALID"),
        ("target-endpoint", "TARGET_ENDPOINT", "DOCKER_BUILDER_SELECTION_TARGET_INVALID"),
    ),
)
def test_phase_a_golden_plan_projection_matches_legacy_contract(
    case: str,
    predicate: str,
    message: str | None,
) -> None:
    rows = _rows()
    _mutate(rows, case)
    snapshot = _observation(rows)
    assert snapshot.first_defect.value == predicate
    assert capacity.builder_prestate_snapshot_is_consistent(snapshot)
    assert capacity.legacy_plan_error(snapshot.first_defect) == message
    if message is None:
        plan = capacity.require_docker_builder_selection_plan(
            _encoded(rows),
            {},
            current_context="desktop-linux",
        )
        assert plan.selection_argv == ("docker", "buildx", "use", "desktop-linux")
    else:
        with pytest.raises(capacity.DockerCapacityError) as captured:
            capacity.require_docker_builder_selection_plan(
                _encoded(rows),
                {},
                current_context="desktop-linux",
            )
        assert str(captured.value) == message


@pytest.mark.parametrize(
    ("line", "authority", "distribution"),
    (
        (
            "github.com/docker/buildx v0.35.0 " + "a" * 40 + "\n",
            "UPSTREAM_V0_35_0",
            "NOT_APPLICABLE",
        ),
        (
            "github.com/docker/buildx v0.34.0 " + "b" * 40 + "\n",
            "UPSTREAM_OTHER",
            "NOT_APPLICABLE",
        ),
        (
            "github.com/docker/buildx v0.35.0-desktop.1 " + "c" * 40 + "\n",
            "OTHER_DISTRIBUTION",
            "DOCUMENTED_DESKTOP_SUFFIX",
        ),
        (
            "buildx v0.11.2-desktop.1",
            "OTHER_DISTRIBUTION",
            "DOCUMENTED_DESKTOP_SUFFIX",
        ),
        (
            "buildx v0.11.2-desktop.1 " + "c" * 40 + "\n",
            "OTHER_DISTRIBUTION",
            "DOCUMENTED_DESKTOP_SUFFIX",
        ),
        (
            "github.com/docker/buildx development " + "d" * 40 + "\n",
            "OTHER_DISTRIBUTION",
            "UPSTREAM_MODULE_NONRELEASE",
        ),
        (
            "example.invalid/buildx v0.35.0 " + "e" * 40 + "\n",
            "OTHER_DISTRIBUTION",
            "OTHER_MODULE",
        ),
        ("malformed raw-version-sentinel", "OUTPUT_INVALID", "NOT_APPLICABLE"),
        ("x" * 257, "OUTPUT_INVALID", "NOT_APPLICABLE"),
    ),
)
def test_version_observation(line: str, authority: str, distribution: str) -> None:
    observed = prestate.observe_buildx_version(line)
    assert observed.authority.value == authority
    assert observed.distribution.value == distribution
    assert "github.com" not in repr(observed)
    assert "raw-version-sentinel" not in repr(observed)


def test_complete_snapshot_computes_later_matrix_before_prior_driver_defect() -> None:
    rows = _rows()
    rows[0]["Driver"] = ""
    rows[0]["Err"] = "raw-builder-error-sentinel"
    snapshot = _observation(rows)
    assert snapshot.first_defect is prestate.DockerBuilderSelectionPlanPredicate.PRIOR_DRIVER
    assert snapshot.prior_driver is prestate.PriorDriverPredicate.EMPTY
    assert snapshot.builder_error is prestate.BuilderErrorPredicate.PRESENT
    assert snapshot.prior_target_relation is prestate.PriorTargetRelationPredicate.DISTINCT
    assert snapshot.prior_status is prestate.PriorStatusPredicate.RUNNING
    assert snapshot.prior_node_error is prestate.BuilderErrorPredicate.ABSENT
    assert snapshot.target_contract is prestate.TargetContractPredicate.PASS
    assert "raw-builder-error-sentinel" not in repr(snapshot)


def test_duplicate_target_is_closed_without_exposing_count_or_identity() -> None:
    rows = _rows()
    _mutate(rows, "duplicate")
    snapshot = _observation(rows)
    assert snapshot.prior_target_relation is prestate.PriorTargetRelationPredicate.TARGET_MULTIPLE
    assert snapshot.target_contract is prestate.TargetContractPredicate.MULTIPLE


@pytest.mark.parametrize(
    ("case", "expected"),
    (
        ("pass", "PASS"),
        ("target-missing", "MISSING"),
        ("duplicate", "MULTIPLE"),
        ("target-driver", "DRIVER"),
        ("target-status", "STATUS"),
        ("target-node", "NODE_NAME"),
        ("target-endpoint", "ENDPOINT"),
    ),
)
def test_target_contract_is_complete_and_ordered(case: str, expected: str) -> None:
    rows = _rows()
    _mutate(rows, case)
    assert _observation(rows).target_contract.value == expected


@pytest.mark.parametrize("status", ("running", "stopped", "error", "", "future"))
def test_prior_status_is_closed_even_when_prior_driver_fails(status: str) -> None:
    rows = _rows()
    rows[0]["Driver"] = ""
    nodes = rows[0]["Nodes"]
    assert isinstance(nodes, list) and isinstance(nodes[0], dict)
    nodes[0]["Status"] = status
    closed = ("RUNNING", "STOPPED", "ERROR", "EMPTY")
    expected = (
        closed[("running", "stopped", "error", "").index(status)] if status != "future" else "OTHER"
    )
    assert _observation(rows).prior_status.value == expected


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("buildx_authority", prestate.BuildxAuthorityPredicate.UPSTREAM_OTHER),
        ("buildx_distribution", prestate.BuildxDistributionPredicate.OTHER_MODULE),
        ("builder_selection", prestate.BuilderSelectionPredicate.NODE_NOT_RUNNING),
        ("node_schema", prestate.NodeSchemaPredicate.NODE_NOT_MAPPING),
        ("prior_driver", prestate.PriorDriverPredicate.REMOTE),
        ("builder_error", prestate.BuilderErrorPredicate.PRESENT),
        ("prior_target_relation", prestate.PriorTargetRelationPredicate.SAME),
        ("prior_status", prestate.PriorStatusPredicate.STOPPED),
        ("prior_node_error", prestate.BuilderErrorPredicate.PRESENT),
        ("target_contract", prestate.TargetContractPredicate.STATUS),
        ("first_defect", prestate.DockerBuilderSelectionPlanPredicate.PLAN_DRIFT),
    ),
)
def test_whole_snapshot_comparison(field: str, replacement: object) -> None:
    snapshot = _observation(_rows())
    assert cast(Any, replace)(snapshot, **{field: replacement}) != snapshot


@pytest.mark.parametrize(
    "changes",
    (
        {"prior_driver": prestate.PriorDriverPredicate.UNKNOWN},
        {"builder_error": prestate.BuilderErrorPredicate.UNKNOWN},
        {"prior_status": prestate.PriorStatusPredicate.UNKNOWN},
        {"prior_node_error": prestate.BuilderErrorPredicate.UNKNOWN},
        {"builder_selection": prestate.BuilderSelectionPredicate.UNKNOWN},
        {"builder_selection": prestate.BuilderSelectionPredicate.NODE_SCHEMA},
        {"builder_selection": prestate.BuilderSelectionPredicate.ROW_SCHEMA},
        {"target_contract": prestate.TargetContractPredicate.UNKNOWN},
        {"prior_target_relation": prestate.PriorTargetRelationPredicate.SAME},
        {
            "builder_selection": prestate.BuilderSelectionPredicate.PASS,
            "prior_driver": prestate.PriorDriverPredicate.UNRECOGNIZED,
            "first_defect": prestate.DockerBuilderSelectionPlanPredicate.CURRENT_ALREADY_CANONICAL,
        },
    ),
)
def test_unreachable_snapshot_fails_fixed_before_format(changes: dict[str, object]) -> None:
    snapshot = cast(Any, replace)(_observation(_rows()), **changes)
    assert not capacity.builder_prestate_snapshot_is_consistent(snapshot)
    with pytest.raises(ValueError, match="DOCKER_BUILDER_SELECTION_PRESTATE_EVIDENCE_INVALID"):
        operator.BuilderSelectionPrestateDiagnosticEvidence(
            classification=operator.BuilderSelectionReconcileClassification.PASS,
            predicate=operator.BuilderSelectionReconcilePredicate.PASS,
            prestate_known=True,
            prestate_checkpoint=operator.BuilderSelectionPrestateCheckpoint.REPROOF,
            prestate_predicate=prestate.DockerBuilderSelectionPlanPredicate.PASS,
            observation_known=True,
            observation=snapshot,
        )


def test_v2_diagnostic_projection_is_one_nested_allowlisted_observation() -> None:
    rows = _rows()
    rows[0]["Driver"] = ""
    snapshot = replace(
        _observation(rows),
        buildx_authority=prestate.BuildxAuthorityPredicate.UPSTREAM_V0_35_0,
    )
    evidence = operator.BuilderSelectionPrestateDiagnosticEvidence(
        classification=operator.BuilderSelectionReconcileClassification.REJECTED,
        predicate=operator.BuilderSelectionReconcilePredicate.PRESTATE,
        prestate_known=True,
        prestate_checkpoint=operator.BuilderSelectionPrestateCheckpoint.CAPTURE,
        prestate_predicate=prestate.DockerBuilderSelectionPlanPredicate.PRIOR_DRIVER,
        observation_known=True,
        observation=snapshot,
    )
    payload = json.loads(operator.format_builder_selection_prestate_diagnostic(evidence))
    assert payload["schema"] == "BUILDER_PRESTATE_V2"
    assert payload["observation_known"] is True
    assert set(payload["observation"]) == set(
        "builder_error builder_selection buildx_authority buildx_distribution first_defect "
        "node_schema prior_driver prior_node_error prior_status prior_target_relation "
        "target_contract".split()
    )
