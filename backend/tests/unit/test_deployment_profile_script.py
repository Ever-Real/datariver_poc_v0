from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[3]


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "validate_deployment_profile", ROOT / "scripts" / "validate_deployment_profile.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _profile() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "profile_id": "target-profile",
        "environment": "target",
        "workspace_boundary": "LOGICAL_TENANT",
        "hosts": [
            {
                "role": "PRODUCTION",
                "cpu_model": "reviewed-cpu",
                "cpu_socket_count": 2,
                "physical_core_count": 32,
                "ram_gib": 256,
                "storage": {
                    "medium": "NVME",
                    "usable_gib": 4096,
                    "sustained_read_iops": 100000,
                    "sustained_write_iops": 50000,
                    "p99_read_latency_ms": 5.0,
                    "p99_write_latency_ms": 10.0,
                },
                "network": {"link_gbps": 10.0, "p99_rtt_ms": 2.0},
            }
        ],
        "workload": {
            "assets_per_workspace": 1000000,
            "total_assets": 5000000,
            "near_term_table_assets": 100000,
            "typical_daily_changes_per_workspace": 100,
            "burst_daily_changes_per_workspace": 50000,
            "concurrent_human_users": 50,
            "catalog_search_rps": 30.0,
            "chat_qps": 2.0,
            "chat_concurrent_streams": 60,
            "kg_nodes_per_large_workspace": 2000000,
            "kg_edges_per_large_workspace": 10000000,
            "soak_minutes": 60,
            "stress_multiplier": 3.0,
        },
        "slo": {
            "search": {
                "cached_p95_ms": 300,
                "uncached_p95_ms": 800,
                "uncached_p99_ms": 1500,
                "maximum_error_ratio": 0.01,
            },
            "chat": {
                "ttft_p95_ms": 3000,
                "average_tokens_per_second": 15.0,
                "benchmark_accuracy_ratio": 0.9,
            },
            "graph": {
                "maximum_hops": 3,
                "traversal_p95_ms": 1500,
                "source_to_projection_p99_seconds": 1800,
            },
            "ingestion": {
                "manual_proposal_p95_seconds": 10,
                "bulk_batch_p95_seconds": 300,
            },
            "freshness": {
                "projection_lag_p95_seconds": 300,
                "projection_lag_p99_seconds": 900,
                "permission_revocation_p99_seconds": 60,
                "emergency_edge_block_seconds": 15,
            },
            "service": {
                "monthly_availability_ratio": 0.995,
                "dashboard_render_p99_ms": 1500,
            },
        },
    }


def test_loads_a_complete_strict_profile(tmp_path: Path) -> None:
    module = _module()
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(_profile()), encoding="utf-8")

    profile = module.load_profile(path)

    assert profile.readiness_blockers() == ()
    assert module.safe_summary(profile)["ready_for_target_load"] is True


def test_reports_incomplete_reference_host_without_inventing_values(tmp_path: Path) -> None:
    module = _module()
    document = _profile()
    production = document["hosts"][0]
    production["storage"] = None
    production["network"] = None
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    profile = module.load_profile(path)

    assert profile.readiness_blockers() == (
        "hosts.PRODUCTION.storage",
        "hosts.PRODUCTION.network",
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("workspace_boundary", "PHYSICAL_SERVER"),
        ("unexpected", "not-allowed"),
    ],
)
def test_rejects_non_portable_or_unknown_root_fields(
    tmp_path: Path, field: str, value: object
) -> None:
    module = _module()
    document = _profile()
    document[field] = value
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValidationError):
        module.load_profile(path)


def test_rejects_inconsistent_capacity_targets(tmp_path: Path) -> None:
    module = _module()
    document = _profile()
    document["workload"]["total_assets"] = 10
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValidationError, match="total_assets"):
        module.load_profile(path)
