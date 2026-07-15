from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from datariver.infrastructure.db import models as _models  # noqa: F401
from datariver.infrastructure.db.base import Base
from datariver.seed.semiconductor import build_pack

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = (
    ROOT / "compose.yaml",
    ROOT / "compose.identity.yaml",
    ROOT / "compose.airflow.yaml",
    ROOT / "compose.gateway.yaml",
)
REQUIRED_DOCKERIGNORE_ENTRIES = {
    ".env",
    ".env.*",
    "secrets",
    "runtime",
    ".venv",
    "frontend/node_modules",
}
EXPECTED_SERVICE_SECRETS = {
    "migrate": {"postgres_password"},
    "storage-init": {"s3_access_key", "s3_secret_key"},
    "semiconductor-seed": {"postgres_password"},
    "local-bootstrap": {"postgres_bootstrap_password"},
    "api": {
        "postgres_app_password",
        "valkey_cache_password",
        "datahub_token",
        "s3_access_key",
        "s3_secret_key",
    },
    "outbox-relay": {"postgres_relay_password", "valkey_queue_password"},
    "upload-worker": {
        "postgres_upload_password",
        "valkey_queue_password",
        "s3_access_key",
        "s3_secret_key",
    },
    "upload-validation-worker": {
        "postgres_upload_password",
        "valkey_queue_password",
        "s3_access_key",
        "s3_secret_key",
    },
    "governance-apply-worker": {
        "postgres_governance_password",
        "valkey_queue_password",
        "datahub_token",
    },
}


def _yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{path.relative_to(ROOT)} must contain a YAML mapping")
    return value


def verify_compose() -> None:
    documents = {path: _yaml(path) for path in COMPOSE_FILES}
    base_services = set(documents[COMPOSE_FILES[0]].get("services", {}))
    base_secrets = set(documents[COMPOSE_FILES[0]].get("secrets", {}))
    for path, document in documents.items():
        services = document.get("services", {})
        if not isinstance(services, dict):
            raise AssertionError(f"{path.name}: services must be a mapping")
        available = base_services | set(services)
        for name, raw_service in services.items():
            if not isinstance(raw_service, dict):
                raise AssertionError(f"{path.name}:{name} must be a mapping")
            image = raw_service.get("image")
            if isinstance(image, str):
                tag = image.rsplit("/", 1)[-1]
                if tag.endswith(":latest") or (":" not in tag and "@sha256:" not in image):
                    raise AssertionError(f"{path.name}:{name} image is not version-pinned: {image}")
            dependencies = raw_service.get("depends_on", {})
            dependency_names = set(dependencies)
            missing = dependency_names - available
            if missing:
                raise AssertionError(f"{path.name}:{name} has missing dependencies: {missing}")
            secret_entries = raw_service.get("secrets", [])
            names = {
                entry if isinstance(entry, str) else str(entry.get("source"))
                for entry in secret_entries
            }
            missing_secrets = names - base_secrets
            if missing_secrets:
                raise AssertionError(
                    f"{path.name}:{name} references undeclared secrets: {missing_secrets}"
                )
            if path == COMPOSE_FILES[0] and name in EXPECTED_SERVICE_SECRETS:
                expected = EXPECTED_SERVICE_SECRETS[name]
                if names != expected:
                    raise AssertionError(
                        f"{path.name}:{name} violates least-privilege secret set: "
                        f"expected={sorted(expected)}, actual={sorted(names)}"
                    )


def verify_build_context() -> None:
    path = ROOT / ".dockerignore"
    entries = {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    missing = REQUIRED_DOCKERIGNORE_ENTRIES - entries
    if missing:
        raise AssertionError(f".dockerignore does not exclude sensitive paths: {missing}")


def verify_runtime_hardening() -> None:
    documents = {path.name: _yaml(path) for path in COMPOSE_FILES}
    expected_read_only = {
        "compose.yaml": {
            "api",
            "outbox-relay",
            "upload-worker",
            "upload-validation-worker",
            "governance-apply-worker",
            "web",
        },
        "compose.identity.yaml": {"keycloak"},
        "compose.gateway.yaml": {"apisix"},
    }
    expected_no_new_privileges = {
        "compose.yaml": expected_read_only["compose.yaml"],
        "compose.identity.yaml": {"keycloak"},
        "compose.gateway.yaml": {"apisix"},
        "compose.airflow.yaml": {
            "airflow-init",
            "airflow-api-server",
            "airflow-scheduler",
            "airflow-dag-processor",
            "airflow-triggerer",
        },
    }
    for filename, names in expected_read_only.items():
        services = documents[filename]["services"]
        missing = {name for name in names if services[name].get("read_only") is not True}
        if missing:
            raise AssertionError(f"{filename} services are not read-only: {sorted(missing)}")
    for filename, names in expected_no_new_privileges.items():
        services = documents[filename]["services"]
        missing = {
            name
            for name in names
            if "no-new-privileges:true" not in services[name].get("security_opt", [])
        }
        if missing:
            raise AssertionError(
                f"{filename} services permit privilege escalation: {sorted(missing)}"
            )

    gateway = documents["compose.gateway.yaml"]["services"]["apisix"]
    if gateway.get("healthcheck", {}).get("test") != [
        "CMD",
        "/usr/local/bin/datariver-apisix-healthcheck",
    ]:
        raise AssertionError("APISIX must use the real HTTP health check")
    gateway_tmpfs = gateway.get("tmpfs", [])
    if not any(str(entry).startswith("/usr/local/apisix/conf:") for entry in gateway_tmpfs):
        raise AssertionError("APISIX generated configuration must use bounded tmpfs")

    keycloak_dockerfile = (ROOT / "infra" / "keycloak" / "Dockerfile").read_text(encoding="utf-8")
    if "USER 1000" not in keycloak_dockerfile:
        raise AssertionError("Keycloak runtime user must be explicitly non-root")

    nginx_template = (ROOT / "frontend" / "nginx.conf.template").read_text(encoding="utf-8")
    if "resolver 127.0.0.11" not in nginx_template or "proxy_pass $api_backend;" not in (
        nginx_template
    ):
        raise AssertionError("web proxy must re-resolve a replaced API container")
    if "proxy_pass http://api:8000" in nginx_template:
        raise AssertionError("web proxy contains a startup-only API resolution")


def verify_ci_supply_chain() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    required = {
        "pip-audit==2.10.0",
        "npm audit --audit-level=high",
        "aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25",
        "version: v0.70.0",
        "format: cyclonedx",
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
    }
    missing = {value for value in required if value not in workflow}
    if missing:
        raise AssertionError(f"CI supply-chain gates are incomplete: {missing}")


def verify_database_roles() -> None:
    generator = (ROOT / "scripts" / "generate_initial_migration.py").read_text(encoding="utf-8")
    role_init = (ROOT / "infra" / "postgres" / "init" / "010_roles.sh").read_text(encoding="utf-8")
    combined = generator + role_init + (ROOT / "compose.yaml").read_text(encoding="utf-8")
    if "datariver_worker" in combined or "postgres_worker_password" in combined:
        raise AssertionError("legacy all-powerful worker identity is still configured")
    required_roles = {
        "datariver_app",
        "datariver_relay",
        "datariver_upload",
        "datariver_governance",
        "datariver_bootstrap",
    }
    missing = {role for role in required_roles if role not in combined}
    if missing:
        raise AssertionError(f"least-privilege database roles are missing: {missing}")
    if "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES" in generator:
        raise AssertionError("runtime database roles cannot receive global table DML")


def verify_architecture_imports() -> None:
    source = ROOT / "backend" / "src" / "datariver"
    forbidden = {
        "domain": ("datariver.application", "datariver.infrastructure", "datariver.interfaces"),
        "application": ("datariver.infrastructure", "datariver.interfaces"),
    }
    for layer, prefixes in forbidden.items():
        for path in (source / layer).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for prefix in prefixes:
                if re.search(rf"(?:from|import)\s+{re.escape(prefix)}", text):
                    raise AssertionError(
                        f"inward dependency violation: {path.relative_to(ROOT)} imports {prefix}"
                    )


def verify_tenant_referential_integrity() -> None:
    """Every relationship between tenant tables must carry the workspace boundary."""
    for table in Base.metadata.tables.values():
        if "workspace_id" not in table.c:
            continue
        for constraint in table.foreign_key_constraints:
            referred = constraint.referred_table
            if "workspace_id" not in referred.c:
                continue
            mappings = {
                (element.parent.name, element.column.name) for element in constraint.elements
            }
            if ("workspace_id", "workspace_id") not in mappings:
                raise AssertionError(
                    "tenant relationship omits workspace boundary: "
                    f"{table.fullname} -> {referred.fullname}"
                )


def verify_seed() -> None:
    directory = ROOT / "seed" / "semiconductor"
    manifest = _yaml(directory / "manifest.yaml")
    expected = json.loads((directory / "expected" / "counts.json").read_text(encoding="utf-8"))
    if manifest.get("expected") != expected:
        raise AssertionError("seed manifest and expected/counts.json differ")
    pack = build_pack()
    actual = {
        "catalog_assets": len(pack.catalog_assets),
        "graph_nodes": len(pack.snapshot.nodes),
        "graph_edges": len(pack.snapshot.edges),
    }
    if actual != expected:
        raise AssertionError(f"seed builder counts differ: expected={expected}, actual={actual}")
    if pack.logical_hash != build_pack().logical_hash:
        raise AssertionError("seed logical hash is not deterministic")
    analytical_expected = json.loads(
        (directory / "expected" / "analytical_fixtures.json").read_text(encoding="utf-8")
    )
    observations = [
        node for node in pack.snapshot.nodes.values() if node.entity_type == "MetricObservation"
    ]
    materials = [node for node in pack.snapshot.nodes.values() if node.entity_type == "Material"]
    equipment = [
        node for node in pack.snapshot.nodes.values() if node.entity_type == "EquipmentFamily"
    ]
    analytical_actual = {
        "period_count": len({node.properties["period"] for node in observations}),
        "facility_observation_count": sum(
            node.properties["metric_family"] == "CAPACITY" for node in observations
        ),
        "product_demand_observation_count": sum(
            node.properties["metric_family"] == "DEMAND" for node in observations
        ),
        "single_source_material_count": sum(
            node.properties["synthetic_qualified_source_count"] == 1 for node in materials
        ),
        "maximum_equipment_lead_time_days": max(
            node.properties["synthetic_lead_time_days"] for node in equipment
        ),
        "observation_edge_count": sum(
            edge.edge_type == "OBSERVES" for edge in pack.snapshot.edges.values()
        ),
    }
    if analytical_actual != analytical_expected:
        raise AssertionError(
            "seed analytical fixtures differ: "
            f"expected={analytical_expected}, actual={analytical_actual}"
        )


def verify_document_links() -> None:
    pattern = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
    for path in (ROOT / "docs").rglob("*.md"):
        for target in pattern.findall(path.read_text(encoding="utf-8")):
            target = target.strip().strip("<>").split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            resolved = (path.parent / target).resolve()
            if not resolved.is_relative_to(ROOT.resolve()) or not resolved.exists():
                raise AssertionError(f"broken local link in {path.relative_to(ROOT)}: {target}")


def main() -> None:
    verify_compose()
    verify_build_context()
    verify_runtime_hardening()
    verify_ci_supply_chain()
    verify_database_roles()
    verify_architecture_imports()
    verify_tenant_referential_integrity()
    verify_seed()
    verify_document_links()
    print(
        "static verification passed: compose, build context, runtime hardening, CI supply chain, "
        "database roles, architecture, tenant foreign keys, seed, documentation"
    )


if __name__ == "__main__":
    main()
