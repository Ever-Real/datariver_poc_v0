from __future__ import annotations

import importlib.util
import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[3]
SUPPORT_PATH = ROOT / "backend/tests/integration/test_prep39083_unified_deploy_docker.py"
_ENABLED = os.getenv("DATARIVER_PREP39083_K9_MCL_RECOVERY_INTEGRATION") == "1"


def _load_support() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "prep39083_k9_mcl_recovery_support",
        SUPPORT_PATH,
    )
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


support = _load_support()
deploy = support.deploy


def _dataset() -> dict[str, Any]:
    dataset_urn = "urn:li:dataset:(urn:li:dataPlatform:postgres,fixture.schema.asset,PROD)"
    classification_tag = {
        "urn": "urn:li:tag:fixture_classification",
        "name": "fixture_classification",
        "properties": {
            "name": "CLASSIFICATION:INTERNAL",
            "description": "",
        },
    }
    return {
        "urn": dataset_urn,
        "type": "DATASET",
        "name": "asset",
        "subTypes": {"typeNames": ["Table"]},
        "platform": {"urn": "urn:li:dataPlatform:postgres", "name": "postgres"},
        "properties": {
            "name": "asset",
            "qualifiedName": "fixture.schema.asset",
            "description": "",
            "customProperties": [],
        },
        "editableProperties": {"description": None},
        "browsePathV2": {"path": []},
        "domain": None,
        "ownership": {"owners": []},
        "globalTags": {"tags": [{"tag": classification_tag}]},
        "glossaryTerms": {
            "terms": [
                {
                    "term": {
                        "urn": "urn:li:glossaryTerm:fixture_term",
                        "name": "Fixture term",
                        "properties": {"name": "Fixture term", "description": ""},
                    }
                }
            ]
        },
        "schemaMetadata": {
            "name": "asset",
            "fields": [
                {
                    "fieldPath": "id",
                    "type": {"type": {"com.linkedin.schema.NumberType": {}}},
                    "nativeDataType": "bigint",
                    "description": "",
                    "nullable": False,
                    "isPartOfKey": True,
                    "isPartitioningKey": False,
                    "globalTags": {"tags": []},
                    "glossaryTerms": {"terms": []},
                }
            ],
        },
        "editableSchemaMetadata": {"editableSchemaFieldInfo": []},
        "fineGrainedLineages": [],
        "structuredProperties": {"properties": []},
        "latestFullTableProfile": [],
    }


def _glossary_term(*, assigned: bool = False) -> dict[str, Any]:
    return {
        "urn": "urn:li:glossaryTerm:fixture_term",
        "type": "GLOSSARY_TERM",
        "exists": True,
        "status": {"removed": False},
        "hierarchicalName": "fixture_term",
        "properties": {"name": "Fixture term", "description": ""},
        "glossaryTermInfo": {
            "name": "Fixture term",
            "description": "",
            "termSource": None,
            "sourceRef": None,
            "sourceUrl": None,
            "customProperties": [],
        },
        "domain": None,
        "structuredProperties": {"properties": []},
        "parentNodes": {"nodes": []},
        "tableAssignments": {"total": 1 if assigned else 0},
        "columnAssignments": {"total": 0},
        "outgoingRelationships": {"total": 0, "relationships": []},
    }


@contextmanager
def _provider_fixture() -> Iterator[tuple[str, dict[str, int]]]:
    observations = {
        "inventory": 0,
        "glossary": 0,
        "lineage": 0,
        "embedding": 0,
        "general": 0,
        "direct_term": 0,
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_arguments: object) -> None:
            return

        def _json(self, status: int, value: object) -> None:
            body = json.dumps(value, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            assert 0 <= length <= 1_048_576
            value = json.loads(self.rfile.read(length) or b"{}")
            assert isinstance(value, dict)
            return value

        def do_GET(self) -> None:
            if self.path == "/config":
                self._json(
                    200,
                    {"versions": {"acryldata/datahub": {"version": "1.6.0", "commit": "fixture"}}},
                )
                return
            if self.path.endswith("/models") or self.path == "/":
                self._json(200, {"data": []})
                return
            self._json(404, {"code": "NOT_FOUND"})

        def do_POST(self) -> None:
            body = self._body()
            if self.path == "/api/graphql":
                query = str(body.get("query", ""))
                if "DataRiverPocCatalogEmbeddingInventory" in query:
                    observations["inventory"] += 1
                    self._json(
                        200,
                        {
                            "data": {
                                "scrollAcrossEntities": {
                                    "nextScrollId": None,
                                    "count": 1,
                                    "total": 1,
                                    "searchResults": [{"entity": _dataset()}],
                                }
                            }
                        },
                    )
                    return
                if "DataRiverPocLineage" in query:
                    observations["lineage"] += 1
                    self._json(
                        200,
                        {
                            "data": {
                                "dataset": {
                                    "lineage": {
                                        "total": 0,
                                        "relationships": [],
                                    }
                                }
                            }
                        },
                    )
                    return
                if "DataRiverPocGlossaryTermByUrn" in query:
                    observations["direct_term"] += 1
                    self._json(200, {"data": {"entity": _glossary_term(assigned=True)}})
                    return
                if "DataRiverPocGlossary" in query:
                    observations["glossary"] += 1
                    self._json(
                        200,
                        {
                            "data": {
                                "scrollAcrossEntities": {
                                    "nextScrollId": None,
                                    "count": 0,
                                    "total": 0,
                                    "searchResults": [],
                                }
                            }
                        },
                    )
                    return
                if "DataRiverPocEntityRelationships" in query:
                    urn = body.get("variables", {}).get("urn")
                    self._json(
                        200,
                        {
                            "data": {
                                "entity": {
                                    "urn": urn,
                                    "type": "GLOSSARY_TERM",
                                    "relationships": {
                                        "start": 0,
                                        "count": 0,
                                        "total": 0,
                                        "relationships": [],
                                    },
                                }
                            }
                        },
                    )
                    return
                self._json(400, {"errors": [{"message": "fixture query is not allowlisted"}]})
                return
            if self.path.endswith("/embeddings"):
                observations["embedding"] += 1
                inputs = body.get("input")
                values = inputs if isinstance(inputs, list) else [inputs]
                self._json(
                    200,
                    {
                        "data": [
                            {"index": index, "embedding": [1.0, 0.0, 0.5]}
                            for index, _value in enumerate(values)
                        ]
                    },
                )
                return
            if self.path.endswith("/rerank") or self.path.endswith("/rerankings"):
                self._json(200, {"results": []})
                return
            if self.path.endswith("/chat/completions"):
                messages = body.get("messages") if isinstance(body.get("messages"), list) else []
                system_prompt = str(messages[0].get("content", "")) if messages else ""
                if "Plan one untrusted Data Catalog question" in system_prompt:
                    content = json.dumps(
                        {
                            "mode": "GENERAL",
                            "confidence": 0.99,
                            "intent": "GENERAL_CONVERSATION",
                            "entity_resolution_required": False,
                            "graph_traversal_required": False,
                            "semantic_retrieval_required": False,
                            "fallback_mode": None,
                            "primary_concepts": [],
                            "secondary_concepts": [],
                            "relation_intent": None,
                            "entity_type_hints": [],
                            "selected_graph_asset": None,
                            "retrieval_method": "NONE",
                        },
                        separators=(",", ":"),
                    )
                else:
                    observations["general"] += 1
                    content = "Bounded fixture answer."
                self._json(200, {"choices": [{"message": {"content": content}}]})
                return
            self._json(404, {"code": "NOT_FOUND"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://host.docker.internal:{server.server_port}", observations
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _seed_pending_mcl(runner: Any, prefix: list[str]) -> dict[str, Any]:
    script = """
import { createPocStateStore } from './poc-state-store.mjs'
const sourceIdentityHash = 'a'.repeat(64)
const store = createPocStateStore()
const before = await store.initializeChangeHistoryCaptureBoundaries({
  sourceIdentityHash,
  schemaContractHash: 'b'.repeat(64),
  providerName: 'DataHub',
  providerVersion: '1.6.0-fixture',
  topicContract: 'MetadataChangeLog_Versioned_v1',
  partitions: [{ partition: 0, boundary: 7 }],
})
const repeated = await store.initializeChangeHistoryCaptureBoundaries({
  sourceIdentityHash,
  schemaContractHash: 'b'.repeat(64),
  providerName: 'DataHub',
  providerVersion: '1.6.0-fixture',
  topicContract: 'MetadataChangeLog_Versioned_v1',
  partitions: [{ partition: 0, boundary: 7 }],
})
await store.writeChangeHistoryRuntimeStatus({
  state: 'READY',
  observedAt: new Date().toISOString(),
})
const after = await store.readChangeHistoryCheckpoint({
  sourceIdentityHash,
  topicContract: 'MetadataChangeLog_Versioned_v1',
  partition: 0,
})
process.stdout.write(JSON.stringify({
  before: before[0].nextOffset,
  repeated: repeated[0].nextOffset,
  after,
}) + '\\n')
await store.close()
"""
    output = runner.output(
        [
            *prefix,
            "exec",
            "-T",
            "web",
            "node",
            "--input-type=module",
            "-e",
            script,
        ]
    )
    return cast(dict[str, Any], json.loads(output.splitlines()[-1]))


def _k9_profile(runner: Any, prefix: list[str]) -> dict[str, Any]:
    script = """
import { createPocStateStore } from './poc-state-store.mjs'
const store = createPocStateStore()
const rows = await store.listK9ManagedGraphAssets()
const summary = rows.map((row) => ({
  intent: row.managed_intent,
  result: row.latest_result,
  active: Boolean(row.active_release_pointer),
  profile: row.active_manifest?.source_snapshot?.metadata_source_profile ?? null,
}))
process.stdout.write(JSON.stringify(summary) + '\\n')
await store.close()
"""
    output = runner.output(
        [
            *prefix,
            "exec",
            "-T",
            "web",
            "node",
            "--input-type=module",
            "-e",
            script,
        ]
    )
    values = json.loads(output.splitlines()[-1])
    assert len(values) == 2
    assert all(item["result"] in {"RUN", "NO_OP"} and item["active"] for item in values)
    profiles = [item["profile"] for item in values if item["profile"]]
    assert profiles
    return cast(dict[str, Any], profiles[0])


def _cleanup_exact_project(
    runner: Any,
    release: Any,
    bundle: Any,
    volume_names: tuple[str, ...],
) -> dict[str, int]:
    runner.environment = deploy.child_environment(bundle.effective)
    with deploy.private_effective_environment(bundle.effective) as env_file:
        prefix = deploy.compose_prefix(release, env_file)
        runner.run([*prefix, "down", "--remove-orphans"], check=False)
    for volume_name in volume_names:
        runner.run(["docker", "volume", "rm", volume_name], check=False)
    residue = {}
    for kind, command in {
        "containers": [
            "docker",
            "ps",
            "-a",
            "--filter",
            f"label=com.docker.compose.project={release.project}",
            "--quiet",
        ],
        "volumes": [
            "docker",
            "volume",
            "ls",
            "--filter",
            f"label=com.docker.compose.project={release.project}",
            "--quiet",
        ],
        "networks": [
            "docker",
            "network",
            "ls",
            "--filter",
            f"label=com.docker.compose.project={release.project}",
            "--quiet",
        ],
    }.items():
        output = runner.run(command, check=False).stdout.strip().splitlines()
        residue[kind] = len([item for item in output if item.strip()])
    return residue


@pytest.mark.skipif(
    not _ENABLED,
    reason="explicit PREP39083 K9/MCL recovery Docker integration is required",
)
def test_actual_prep_style_k9_failure_resumes_to_integrated_acceptance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    support._pollute_parent_environment(monkeypatch)
    parent_product = os.environ.get("DATARIVER_PREP39083_K9_FAILED_PRODUCT", "").strip()
    assert len(parent_product) == 40 and all(
        value in "0123456789abcdef" for value in parent_product
    )
    project = f"datariver-prep39083-k9-mcl-{uuid4().hex[:10]}"
    port = int(support._free_port())
    runner = deploy.Runner(environment=deploy.child_environment({}))
    product = runner.output(["git", "rev-parse", "HEAD"])
    assert (
        runner.run(
            ["git", "merge-base", "--is-ancestor", parent_product, product],
            check=False,
        ).returncode
        == 0
    )
    artifact_paths = {
        parent_product: tmp_path / f"{parent_product}.tar",
        product: tmp_path / f"{product}.tar",
    }
    artifacts = {
        parent_product: support._archive_existing_product(
            runner, parent_product, artifact_paths[parent_product]
        ),
        product: support._build_product_artifact(runner, product, artifact_paths[product]),
    }
    release_a = deploy.ReleaseIdentity(
        parent_product,
        "a" * 40,
        "linux/amd64",
        port,
        project,
        artifacts[parent_product],
    )
    release_b = deploy.ReleaseIdentity(
        product,
        "b" * 40,
        "linux/amd64",
        port,
        project,
        artifacts[product],
    )
    monkeypatch.setattr(
        deploy,
        "promoted_web_artifact_path",
        lambda artifact: artifact_paths[artifact.product_sha],
    )
    operator = tmp_path / ".env.prep"
    optional = tmp_path / ".env.prep.optional"
    runtime = tmp_path / ".env.prep.runtime"
    accepted = tmp_path / "accepted.json"
    attempt = tmp_path / "deploy-attempt.json"
    smoke_failure = tmp_path / "smoke-failure.json"
    runtime_root = tmp_path / "runtime"
    monkeypatch.setattr(deploy, "ACCEPTED_MARKER", accepted)
    monkeypatch.setattr(deploy, "ATTEMPT_RECEIPT", attempt)
    monkeypatch.setattr(deploy, "SMOKE_FAILURE", smoke_failure)
    monkeypatch.setattr(deploy, "RUNTIME_ROOT", runtime_root)

    with _provider_fixture() as (provider_origin, provider_observations):
        values = support._portable_operator_values(f"http://127.0.0.1:{port}")
        values.update(
            {
                "DATAHUB_GMS_URL": provider_origin,
                "DATAHUB_UI_URL": provider_origin,
                "LLM_CHAT_URL": provider_origin,
                "LLM_EMBEDDING_URL": provider_origin,
                "LLM_RERANKER_URL": provider_origin,
            }
        )
        support._private_env(operator, values)
        bundle = deploy.reconcile_environment(
            release_a,
            operator_path=operator,
            optional_path=optional,
            runtime_path=runtime,
            random_token=lambda count: "r" * count,
        )
        effective = dict(bundle.effective)
        effective.update(
            {
                "POC_PLATFORM": "linux/amd64",
                "POC_SHARED_NETWORK": f"{project}-services",
                "POC_POSTGRES_HOST_PORT": support._free_port(),
                "POC_NEO4J_HTTP_PORT": support._free_port(),
                "POC_REDIS_PORT": support._free_port(),
                "POC_PORT": str(port),
                "POC_PUBLIC_ORIGIN": f"http://127.0.0.1:{port}",
            }
        )
        bundle = replace(bundle, effective=effective)
        runner.environment = deploy.child_environment(bundle.effective)
        source_a = {"handoff_commit": parent_product}
        source_b = {"handoff_commit": product}
        before_39080 = deploy.snapshot_39080(runner)
        inventory = deploy.inspect_target_inventory(
            runner,
            release_a,
            runtime_path=runtime,
            accepted_marker_path=accepted,
            attempt_receipt_path=attempt,
        )
        preparation = deploy.DeploymentPreparation(runner, source_a, inventory, before_39080)
        monkeypatch.setattr(deploy, "verify_source_identity", lambda _release: source_a)
        monkeypatch.setattr(deploy, "require_prep_platform", lambda _runner: None)
        monkeypatch.setattr(
            deploy,
            "run_provider_preflight",
            lambda _runner, _image, _env_file, _effective: {
                "status": "PASS",
                "k9_studio": "DEFERRED",
                "gx_quality_execution": "DEFERRED",
                "airflow": "DEFERRED",
                "minio": "DEFERRED",
            },
        )
        monkeypatch.setattr("builtins.input", lambda _prompt="": "admin")
        passwords = iter(
            (
                "correct horse battery staple",
                "correct horse battery staple",
                "correct horse battery staple",
            )
        )
        monkeypatch.setattr(deploy.getpass, "getpass", lambda _prompt="": next(passwords))
        cleanup_bundle = bundle
        volume_names: tuple[str, ...] = ()
        residue: dict[str, int] | None = None
        original_smoke = deploy.run_smoke
        try:
            with deploy.private_effective_environment(bundle.effective) as env_file:
                volume_names = deploy.compose_volume_identities(
                    deploy.compose_config(runner, deploy.compose_prefix(release_a, env_file))
                )
            with pytest.raises(deploy.PrepError) as first_failure:
                deploy.deploy(release_a, bundle, preparation)
            assert first_failure.value.code == "PREP_SMOKE_K9_DATAHUB_SOURCE_FAILED"
            assert deploy._attempt_receipt(attempt)["phase"] == "SMOKE_FAILED"
            failure = json.loads(smoke_failure.read_text())
            assert failure["stage"] == "K9_INITIAL_REFRESH"
            assert failure["diagnostic"] == {
                "terminal": True,
                "product_error_code": "K9_DATAHUB_SOURCE_FAILED",
                "failure_stage": "METADATA_COLLECTION",
                "failure_detail_code": "ASSIGNMENT_TERM_OUTSIDE_SNAPSHOT",
            }

            retry_inventory = deploy.inspect_target_inventory(
                runner,
                release_b,
                runtime_path=runtime,
                accepted_marker_path=accepted,
                attempt_receipt_path=attempt,
            )
            assert (
                deploy.classify_target_state(retry_inventory)
                is deploy.TargetState.EXISTING_OWNED_INCOMPLETE
            )
            previous_attempt = deploy.validate_owned_attempt(
                runner,
                release_b,
                product,
                retry_inventory,
                deploy.read_env_file(runtime, private=True, label=".env.prep.runtime"),
                bundle.k9_mode,
            )
            preserved_runtime = deploy.read_env_file(
                runtime, private=True, label=".env.prep.runtime"
            )
            preserved_secrets = {
                key: preserved_runtime[key] for key in deploy.TARGET_OWNERSHIP_SECRET_KEYS
            }
            retry_bundle = deploy.reconcile_environment(
                release_b,
                operator_path=operator,
                optional_path=optional,
                runtime_path=runtime,
                target_state=deploy.TargetState.EXISTING_OWNED_INCOMPLETE,
                random_token=lambda _count: pytest.fail(
                    "descendant resume must reuse generated secrets"
                ),
            )
            retry_effective = dict(retry_bundle.effective)
            for key in (
                "POC_PLATFORM",
                "POC_SHARED_NETWORK",
                "POC_POSTGRES_HOST_PORT",
                "POC_NEO4J_HTTP_PORT",
                "POC_REDIS_PORT",
                "POC_PORT",
                "POC_PUBLIC_ORIGIN",
            ):
                retry_effective[key] = effective[key]
            retry_bundle = replace(retry_bundle, effective=retry_effective)
            cleanup_bundle = retry_bundle
            runner.environment = deploy.child_environment(retry_bundle.effective)
            retry_preparation = deploy.DeploymentPreparation(
                runner,
                source_b,
                retry_inventory,
                before_39080,
                previous_attempt,
            )
            mcl_checkpoint: dict[str, Any] = {}

            def integrated_smoke(
                smoke_runner: Any,
                smoke_release: Any,
                username: str,
                password: str,
                *,
                request_origin: str,
                k9_mode: str,
            ) -> None:
                nonlocal mcl_checkpoint
                with deploy.private_effective_environment(retry_bundle.effective) as env_file:
                    prefix = deploy.compose_prefix(release_b, env_file)
                    mcl_checkpoint = _seed_pending_mcl(runner, prefix)
                original_smoke(
                    smoke_runner,
                    smoke_release,
                    username,
                    password,
                    request_origin=request_origin,
                    k9_mode=k9_mode,
                )

            monkeypatch.setattr(deploy, "run_smoke", integrated_smoke)
            deploy.deploy(release_b, retry_bundle, retry_preparation)
            report = json.loads((runtime_root / "smoke.json").read_text())
            assert report == {
                **report,
                "health": "PASS",
                "login": "PASS",
                "datahub": "PASS",
                "managed_assets": "PASS",
                "default_lineage": "PASS",
                "metadata_master": "PASS",
                "semantic_index": "PASS",
                "mcl_change_history": "PASS",
                "llm_general": "PASS",
            }
            assert accepted.is_file()
            final_receipt = deploy._attempt_receipt(attempt)
            assert final_receipt["phase"] == "ACCEPTED"
            assert final_receipt["resumed_from_product_sha"] == parent_product
            assert mcl_checkpoint == {"before": 7, "repeated": 7, "after": 7}
            final_runtime = deploy.read_env_file(runtime, private=True, label=".env.prep.runtime")
            assert {
                key: final_runtime[key] for key in deploy.TARGET_OWNERSHIP_SECRET_KEYS
            } == preserved_secrets
            with deploy.private_effective_environment(retry_bundle.effective) as env_file:
                prefix = deploy.compose_prefix(release_b, env_file)
                inspected = deploy.inspect_bootstrap(runner, prefix)
                profile = _k9_profile(runner, prefix)
            assert inspected["administrator_record_count"] == 1
            assert inspected["user_record_count"] == 3
            assert [item["name"] for item in inspected["services"]] == ["K9", "MCP"]
            assert profile["inventory"] == {
                "total_dataset_count": 1,
                "table_count": 1,
                "view_count": 0,
                "materialized_view_count": 0,
                "total_column_count": 1,
                "table_tag_observation_count": 1,
                "column_tag_observation_count": 0,
                "table_glossary_term_observation_count": 1,
                "column_glossary_term_observation_count": 0,
                "non_empty": True,
            }
            assert profile["glossary_scroll"] == {
                "provider_reported_total": 0,
                "pages_fetched": 1,
                "entities_fetched": 0,
                "unique_term_count": 0,
                "unique_node_count": 0,
                "duplicate_term_observation_count": 0,
                "duplicate_node_observation_count": 0,
                "cursor_progression_status": "COMPLETE",
                "completion_status": True,
            }
            assert profile["relationships"] == {
                "glossary_entities_inspected": 1,
                "provider_relationship_total": 0,
                "relationship_pages_fetched": 1,
                "relationships_fetched": 0,
                "duplicate_relationship_observations": 0,
                "response_entity_identity_mismatch_count": 0,
                "completeness_mismatch_count": 0,
            }
            assert profile["assignments"] == {
                "declared_table_assignment_total": 1,
                "observed_table_assignment_total": 1,
                "declared_column_assignment_total": 0,
                "observed_column_assignment_total": 0,
                "term_outside_snapshot_count": 1,
                "duplicate_assignment_observation_count": 0,
                "missing_term_reference_count": 1,
                "direct_term_resolution_attempt_count": 1,
                "direct_term_resolution_recovered_count": 1,
                "direct_term_resolution_dangling_count": 0,
                "table_missing_term_count": 1,
                "column_missing_term_count": 0,
                "source_consistency_conflict_count": 0,
            }
            assert profile["identity_resolution"] == {
                "exact_duplicate_observation_count": 0,
                "compatible_sparse_rich_observation_count": 1,
                "contradiction_observation_count": 0,
                "failure": None,
            }
            assert provider_observations["inventory"] >= 2
            assert provider_observations["glossary"] >= 2
            assert provider_observations["direct_term"] >= 1
            assert provider_observations["lineage"] >= 4
            assert provider_observations["embedding"] >= 1
            assert provider_observations["general"] >= 1
        finally:
            if volume_names:
                residue = _cleanup_exact_project(runner, release_b, cleanup_bundle, volume_names)
        assert residue == {"containers": 0, "volumes": 0, "networks": 0}
