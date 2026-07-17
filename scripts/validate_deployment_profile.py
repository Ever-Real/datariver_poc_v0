from __future__ import annotations

import argparse
import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

MAX_PROFILE_BYTES = 256 * 1024

PositiveInt = Annotated[int, Field(gt=0)]
PositiveFloat = Annotated[float, Field(gt=0)]
Ratio = Annotated[float, Field(gt=0, le=1)]


class StrictProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class HostRole(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    STAGING = "STAGING"
    PRODUCTION = "PRODUCTION"


class StorageProfile(StrictProfileModel):
    medium: Literal["NVME", "SSD", "HDD", "SAN", "OBJECT_BACKED"]
    usable_gib: PositiveInt
    sustained_read_iops: PositiveInt
    sustained_write_iops: PositiveInt
    p99_read_latency_ms: PositiveFloat
    p99_write_latency_ms: PositiveFloat


class NetworkProfile(StrictProfileModel):
    link_gbps: PositiveFloat
    p99_rtt_ms: PositiveFloat


class HostProfile(StrictProfileModel):
    role: HostRole
    cpu_model: Annotated[str, Field(min_length=1, max_length=200)]
    cpu_socket_count: PositiveInt | None
    physical_core_count: PositiveInt | None
    ram_gib: PositiveInt | None
    storage: StorageProfile | None
    network: NetworkProfile | None


class WorkloadProfile(StrictProfileModel):
    assets_per_workspace: PositiveInt
    total_assets: PositiveInt
    near_term_table_assets: PositiveInt
    typical_daily_changes_per_workspace: PositiveInt
    burst_daily_changes_per_workspace: PositiveInt
    concurrent_human_users: PositiveInt
    catalog_search_rps: PositiveFloat
    chat_qps: PositiveFloat
    chat_concurrent_streams: PositiveInt
    kg_nodes_per_large_workspace: PositiveInt
    kg_edges_per_large_workspace: PositiveInt
    soak_minutes: Annotated[int, Field(ge=60)]
    stress_multiplier: Annotated[float, Field(ge=1, le=10)]

    @model_validator(mode="after")
    def validate_relationships(self) -> WorkloadProfile:
        if self.total_assets < self.assets_per_workspace:
            raise ValueError("total_assets must be at least assets_per_workspace")
        if self.near_term_table_assets > self.assets_per_workspace:
            raise ValueError("near_term_table_assets cannot exceed assets_per_workspace")
        if self.typical_daily_changes_per_workspace > self.burst_daily_changes_per_workspace:
            raise ValueError("typical daily changes cannot exceed the burst target")
        if self.kg_edges_per_large_workspace < self.kg_nodes_per_large_workspace:
            raise ValueError("the large-graph edge target cannot be below the node target")
        return self


class SearchSlo(StrictProfileModel):
    cached_p95_ms: PositiveInt
    uncached_p95_ms: PositiveInt
    uncached_p99_ms: PositiveInt
    maximum_error_ratio: Ratio

    @model_validator(mode="after")
    def validate_percentiles(self) -> SearchSlo:
        if self.uncached_p99_ms < self.uncached_p95_ms:
            raise ValueError("uncached p99 cannot be lower than uncached p95")
        return self


class ChatSlo(StrictProfileModel):
    ttft_p95_ms: PositiveInt
    average_tokens_per_second: PositiveFloat
    benchmark_accuracy_ratio: Ratio


class GraphSlo(StrictProfileModel):
    maximum_hops: Annotated[int, Field(ge=1, le=3)]
    traversal_p95_ms: PositiveInt
    source_to_projection_p99_seconds: PositiveInt


class IngestionSlo(StrictProfileModel):
    manual_proposal_p95_seconds: PositiveInt
    bulk_batch_p95_seconds: PositiveInt


class FreshnessSlo(StrictProfileModel):
    projection_lag_p95_seconds: PositiveInt
    projection_lag_p99_seconds: PositiveInt
    permission_revocation_p99_seconds: PositiveInt
    emergency_edge_block_seconds: PositiveInt

    @model_validator(mode="after")
    def validate_percentiles(self) -> FreshnessSlo:
        if self.projection_lag_p99_seconds < self.projection_lag_p95_seconds:
            raise ValueError("projection lag p99 cannot be lower than p95")
        return self


class ServiceSlo(StrictProfileModel):
    monthly_availability_ratio: Ratio
    dashboard_render_p99_ms: PositiveInt


class SloProfile(StrictProfileModel):
    search: SearchSlo
    chat: ChatSlo
    graph: GraphSlo
    ingestion: IngestionSlo
    freshness: FreshnessSlo
    service: ServiceSlo


class DeploymentValidationProfile(StrictProfileModel):
    schema_version: Literal[1]
    profile_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,63}$")]
    environment: Annotated[str, Field(min_length=1, max_length=64)]
    workspace_boundary: Literal["LOGICAL_TENANT"]
    hosts: Annotated[list[HostProfile], Field(min_length=1, max_length=10)]
    workload: WorkloadProfile
    slo: SloProfile

    @model_validator(mode="after")
    def validate_hosts(self) -> DeploymentValidationProfile:
        roles = [host.role for host in self.hosts]
        if len(roles) != len(set(roles)):
            raise ValueError("host roles must be unique within a validation profile")
        if HostRole.PRODUCTION not in roles:
            raise ValueError("a production reference host is required")
        return self

    def readiness_blockers(self) -> tuple[str, ...]:
        production = next(host for host in self.hosts if host.role is HostRole.PRODUCTION)
        required: dict[str, Any] = {
            "hosts.PRODUCTION.cpu_socket_count": production.cpu_socket_count,
            "hosts.PRODUCTION.physical_core_count": production.physical_core_count,
            "hosts.PRODUCTION.ram_gib": production.ram_gib,
            "hosts.PRODUCTION.storage": production.storage,
            "hosts.PRODUCTION.network": production.network,
        }
        return tuple(name for name, value in required.items() if value is None)


def load_profile(path: Path) -> DeploymentValidationProfile:
    if not path.is_file():
        raise ValueError(f"deployment profile is not a regular file: {path}")
    size = path.stat().st_size
    if size <= 0 or size > MAX_PROFILE_BYTES:
        raise ValueError(f"deployment profile size must be between 1 and {MAX_PROFILE_BYTES} bytes")
    try:
        document = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError("deployment profile must be valid UTF-8 JSON") from error
    return DeploymentValidationProfile.model_validate_json(document)


def safe_summary(profile: DeploymentValidationProfile) -> dict[str, Any]:
    blockers = profile.readiness_blockers()
    return {
        "schema_version": profile.schema_version,
        "profile_id": profile.profile_id,
        "environment": profile.environment,
        "workspace_boundary": profile.workspace_boundary,
        "ready_for_target_load": not blockers,
        "readiness_blockers": list(blockers),
        "targets": {
            "assets_per_workspace": profile.workload.assets_per_workspace,
            "total_assets": profile.workload.total_assets,
            "catalog_search_rps": profile.workload.catalog_search_rps,
            "chat_qps": profile.workload.chat_qps,
            "chat_concurrent_streams": profile.workload.chat_concurrent_streams,
            "soak_minutes": profile.workload.soak_minutes,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate an ignored, deployment-supplied workload and SLO profile."
    )
    parser.add_argument("profile", type=Path)
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="return a non-zero status while reference-host sizing inputs are incomplete",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        profile = load_profile(args.profile)
    except (ValidationError, ValueError) as error:
        print(json.dumps({"valid": False, "error": str(error)}, ensure_ascii=False))
        return 2
    summary = safe_summary(profile)
    print(json.dumps({"valid": True, **summary}, ensure_ascii=False, sort_keys=True))
    if args.require_ready and profile.readiness_blockers():
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
