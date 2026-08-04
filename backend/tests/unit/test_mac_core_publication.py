from __future__ import annotations

import importlib.util
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "mac_core_publication",
    ROOT / "scripts" / "mac_core_publication.py",
)
assert SPEC is not None
assert SPEC.loader is not None
MODULE: Any = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

CoreServiceCondition = MODULE.CoreServiceCondition
CoreServiceKey = MODULE.CoreServiceKey
CoreServiceObservation = MODULE.CoreServiceObservation
Level2CorePredicate = MODULE.Level2CorePredicate
Level2CoreClassification = MODULE.Level2CoreClassification
Level2CoreDiagnosticPredicate = MODULE.Level2CoreDiagnosticPredicate
Level2CoreEvidence = MODULE.Level2CoreEvidence
Level2CoreProjection = MODULE.Level2CoreProjection
PublicationCategory = MODULE.PublicationCategory
classify_publication_paths = MODULE.classify_publication_paths
evaluate_level2_core_snapshot = MODULE.evaluate_level2_core_snapshot
selected_core_service_specs = MODULE.selected_core_service_specs


def test_publication_classifier_separates_level2_optional_and_unknown() -> None:
    plan = classify_publication_paths(
        (
            "backend/src/datariver/application/ports.py",
            "backend/src/datariver/infrastructure/cache/redis.py",
            "backend/src/datariver/infrastructure/knowledge/neo4j.py",
            "compose.gateway.yaml",
            "backend/src/datariver/infrastructure/datahub/http.py",
            "infra/airflow/dags/catalog_sync.py",
            "backend/src/datariver/infrastructure/object_store/s3.py",
            "backend/src/datariver/infrastructure/llm/ollama.py",
            "docs/README.md",
            "scripts/unreviewed_operator.py",
        )
    )

    assert plan.categories == (
        PublicationCategory.LEVEL1,
        PublicationCategory.LEVEL2_REDIS,
        PublicationCategory.LEVEL2_GRAPH,
        PublicationCategory.LEVEL2_GATEWAY,
        PublicationCategory.OPTIONAL_DATAHUB,
        PublicationCategory.OPTIONAL_AIRFLOW,
        PublicationCategory.OPTIONAL_STORAGE,
        PublicationCategory.OPTIONAL_LOCAL_LLM_OBSERVABILITY,
        PublicationCategory.OPERATOR_ONLY,
        PublicationCategory.UNKNOWN,
    )
    assert not plan.accepted
    assert "backend/src/datariver/infrastructure/datahub/http.py" in plan.core_paths
    assert "backend/src/datariver/infrastructure/object_store/s3.py" in plan.core_paths
    assert "backend/src/datariver/infrastructure/llm/ollama.py" in plan.core_paths


def test_level2_paths_never_enter_optional_integration_categories() -> None:
    plan = classify_publication_paths(
        (
            "compose.local-connectors.yaml",
            "compose.graph.yaml",
            "infra/apisix/config.yaml",
        )
    )

    assert plan.accepted
    assert PublicationCategory.LEVEL2_REDIS in plan.categories
    assert PublicationCategory.LEVEL2_GRAPH in plan.categories
    assert PublicationCategory.LEVEL2_GATEWAY in plan.categories
    assert PublicationCategory.OPTIONAL_STORAGE in plan.categories


def test_known_local_provider_wrappers_are_optional_only() -> None:
    plan = classify_publication_paths(
        (
            "scripts/start_datahub_mac_dev.sh",
            "scripts/verify_datahub_contract.py",
            "scripts/verify_datahub_image_inventory.py",
            "scripts/local_reranker_service.py",
        )
    )

    assert plan.accepted
    assert plan.core_paths == ()
    assert plan.categories == (
        PublicationCategory.OPTIONAL_DATAHUB,
        PublicationCategory.OPTIONAL_LOCAL_LLM_OBSERVABILITY,
    )


def test_all_tracked_local_provider_wrappers_and_iac_are_optional_only() -> None:
    patterns = (
        "infra/datahub/**",
        "infra/airflow/**",
        "infra/minio/**",
        "infra/observability/**",
        "infra/postgres/init-airflow.sh",
        "infra/contracts/datahub-v1.6.0-images.json",
        "scripts/start_datahub_mac_dev.sh",
        "scripts/verify_datahub_contract.py",
        "scripts/verify_datahub_image_inventory.py",
        "scripts/local_reranker_service.py",
    )
    completed = subprocess.run(  # noqa: S603 - fixed Git source inventory only.
        ("git", "ls-files", "--", *patterns),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    paths = tuple(line for line in completed.stdout.splitlines() if line)

    assert paths
    for path in paths:
        plan = classify_publication_paths((path,))
        assert plan.accepted
        assert plan.core_paths == ()
        assert len(plan.categories) == 1
        assert plan.categories[0].value.startswith("OPTIONAL_")


def test_selected_service_specs_are_fixed_level1_level2_only() -> None:
    specs = selected_core_service_specs(
        {
            "GOVERNANCE_DOCUMENT_WORKER_ENABLED": "true",
            "KNOWLEDGE_SOURCE_WORKER_ENABLED": "false",
        }
    )
    keys = tuple(spec.key for spec in specs)

    assert CoreServiceKey.LEVEL1_GOVERNANCE_DOCUMENT_WORKER in keys
    assert CoreServiceKey.LEVEL1_KNOWLEDGE_SOURCE_WORKER not in keys
    assert keys[-4:] == (
        CoreServiceKey.LEVEL2_REDIS_CACHE,
        CoreServiceKey.LEVEL2_REDIS_DELIVERY,
        CoreServiceKey.LEVEL2_GRAPH,
        CoreServiceKey.LEVEL2_GATEWAY,
    )
    serialized = repr(specs).lower()
    for optional_label in ("datahub", "airflow", "minio", "llama", "observability"):
        assert optional_label not in serialized


def _ready_observations() -> tuple[Any, ...]:
    specs = selected_core_service_specs({})
    return tuple(
        CoreServiceObservation(
            key=spec.key,
            private_id=f"{index + 1:064x}",
            condition=(
                CoreServiceCondition.RUNNING_HEALTHY
                if spec.health_required
                else CoreServiceCondition.RUNNING_NO_HEALTH
            ),
        )
        for index, spec in enumerate(specs)
    )


def test_snapshot_projection_requires_adoption_but_keeps_value_free_checkpoint() -> None:
    snapshot = evaluate_level2_core_snapshot(
        observations=_ready_observations(),
        expected_specs=selected_core_service_specs({}),
        local_redis=False,
        local_graph=False,
        local_gateway=False,
    )

    assert snapshot.predicate is Level2CorePredicate.LEVEL2_ADOPTION_REQUIRED
    assert snapshot.level1_pass
    assert snapshot.redis_cache is CoreServiceCondition.RUNNING_HEALTHY
    assert snapshot.redis_delivery is CoreServiceCondition.RUNNING_HEALTHY
    assert snapshot.graph is CoreServiceCondition.RUNNING_HEALTHY
    assert snapshot.gateway is CoreServiceCondition.RUNNING_HEALTHY
    assert "private_id" not in repr(snapshot)


def test_snapshot_projection_blocks_level2_defect_after_adoption() -> None:
    observations = list(_ready_observations())
    graph_index = next(
        index
        for index, value in enumerate(observations)
        if value.key is CoreServiceKey.LEVEL2_GRAPH
    )
    observations[graph_index] = CoreServiceObservation(
        key=CoreServiceKey.LEVEL2_GRAPH,
        private_id="f" * 64,
        condition=CoreServiceCondition.EXITED,
    )

    snapshot = evaluate_level2_core_snapshot(
        observations=tuple(observations),
        expected_specs=selected_core_service_specs({}),
        local_redis=True,
        local_graph=True,
        local_gateway=True,
    )

    assert snapshot.predicate is Level2CorePredicate.LEVEL2_CONTRACT
    assert snapshot.graph is CoreServiceCondition.EXITED


def test_projection_and_evidence_reject_contradictory_public_states() -> None:
    ready = evaluate_level2_core_snapshot(
        observations=_ready_observations(),
        expected_specs=selected_core_service_specs({}),
        local_redis=True,
        local_graph=True,
        local_gateway=True,
    )
    with pytest.raises(ValueError, match="LEVEL2_CORE_PROJECTION_INVALID"):
        replace(ready, predicate=Level2CorePredicate.LEVEL2_ADOPTION_REQUIRED)
    with pytest.raises(ValueError, match="LEVEL2_CORE_EVIDENCE_INVALID"):
        Level2CoreEvidence(
            classification=Level2CoreClassification.PASS,
            predicate=Level2CoreDiagnosticPredicate.PASS,
        )
    with pytest.raises(ValueError, match="LEVEL2_CORE_EVIDENCE_INVALID"):
        Level2CoreEvidence(
            classification=Level2CoreClassification.REJECTED,
            predicate=Level2CoreDiagnosticPredicate.LEVEL1_CONTRACT,
            observation=ready,
        )
    with pytest.raises(ValueError, match="LEVEL2_CORE_EVIDENCE_INVALID"):
        Level2CoreEvidence(
            classification=Level2CoreClassification.PASS,
            predicate=Level2CoreDiagnosticPredicate.PASS,
            observation=ready,
            docker_query_count=45,
        )


@pytest.mark.parametrize(
    ("classification", "predicate"),
    (
        ("REJECTED", "DOCKER_QUERY_UNAVAILABLE"),
        ("REJECTED", "QUERY_EVIDENCE_INVALID"),
        ("OPERATOR_REVIEW_REQUIRED", "UNKNOWN"),
    ),
)
def test_query_failure_output_is_top_level_only(
    classification: str,
    predicate: str,
) -> None:
    evidence = Level2CoreEvidence(
        classification=Level2CoreClassification(classification),
        predicate=Level2CoreDiagnosticPredicate(predicate),
        docker_query_count=2,
    )

    line = MODULE.format_level2_core_evidence(evidence)
    document = MODULE.json.loads(line)

    assert document["classification"] == classification
    assert document["predicate"] == predicate
    assert document["schema"] == "DATARIVER_LEVEL2_CORE_PRESTATE_V1"
    assert set(document) == {
        "action_count",
        "classification",
        "docker_query_count",
        "mutation_count",
        "observation_known",
        "phase",
        "predicate",
        "retry_count",
        "schema",
    }
    assert "query_evidence" not in document
    assert all(
        forbidden not in line
        for forbidden in (
            "postgres",
            "container-private-id",
            "argv-sentinel",
            "signal-sentinel",
            "/private/runtime",
        )
    )


def test_second_snapshot_query_failure_can_retain_first_observation_honestly() -> None:
    ready = evaluate_level2_core_snapshot(
        observations=_ready_observations(),
        expected_specs=selected_core_service_specs({}),
        local_redis=True,
        local_graph=True,
        local_gateway=True,
    )
    evidence = Level2CoreEvidence(
        classification=Level2CoreClassification.REJECTED,
        predicate=Level2CoreDiagnosticPredicate.DOCKER_QUERY_UNAVAILABLE,
        observation=ready,
        docker_query_count=27,
    )

    assert evidence.observation is ready
    assert len(MODULE.format_level2_core_evidence(evidence).encode("utf-8")) <= 1_024
