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
DATAHUB_CONTRACT = ROOT / "infra" / "contracts" / "datahub-v1.6.0-images.json"
DATAHUB_RELEASE = "v1.6.0"
DATAHUB_COMPONENTS = {"actions", "frontend", "gms", "upgrade"}
IMMUTABLE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


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


def verify_datahub_release_contract() -> None:
    contract = json.loads(DATAHUB_CONTRACT.read_text(encoding="utf-8"))
    if contract.get("schema_version") != 1 or contract.get("release") != DATAHUB_RELEASE:
        raise AssertionError("DataHub contract must identify the approved stable v1.6.0 release")
    components = contract.get("components")
    if not isinstance(components, dict) or set(components) != DATAHUB_COMPONENTS:
        raise AssertionError("DataHub contract component set is incomplete")
    forbidden = (":head", ":latest", "rc", "snapshot")
    for name, component in components.items():
        if not isinstance(component, dict):
            raise AssertionError(f"DataHub component {name} must be a mapping")
        image = component.get("image")
        digest = component.get("oci_index_digest")
        if not isinstance(image, str) or f":{DATAHUB_RELEASE}" not in image:
            raise AssertionError(f"DataHub component {name} does not use the approved release tag")
        if any(marker in image.lower() for marker in forbidden):
            raise AssertionError(f"DataHub component {name} uses a mutable or prerelease tag")
        if not isinstance(digest, str) or IMMUTABLE_DIGEST.fullmatch(digest) is None:
            raise AssertionError(f"DataHub component {name} has no immutable OCI index digest")


def verify_identity_assurance_contract() -> None:
    realm = json.loads(
        (ROOT / "infra" / "keycloak" / "datariver-realm.template.json").read_text(encoding="utf-8")
    )
    clients = realm.get("clients")
    users = realm.get("users")
    if not isinstance(clients, list) or not isinstance(users, list):
        raise AssertionError("Keycloak realm must contain clients and users")
    web_client = next(
        (client for client in clients if client.get("clientId") == "datariver-web"), None
    )
    if not isinstance(web_client, dict):
        raise AssertionError("Keycloak realm has no datariver-web client")
    mapper_ids = {
        mapper.get("protocolMapper")
        for mapper in web_client.get("protocolMappers", [])
        if isinstance(mapper, dict)
    }
    if "oidc-amr-mapper" not in mapper_ids:
        raise AssertionError("Keycloak web client must emit authentication method references")
    if web_client.get("attributes", {}).get("default.acr.values") != "1":
        raise AssertionError("Keycloak web client must default ordinary login to LoA 1")
    if "basic" not in web_client.get("defaultClientScopes", []):
        raise AssertionError("Keycloak web client must include the built-in auth_time mapper scope")
    for user in users:
        if isinstance(user, dict) and "CONFIGURE_TOTP" in user.get("requiredActions", []):
            raise AssertionError("Mobile TOTP cannot be a required DataRiver user action")

    step_up_alias = "datariver-browser-step-up-v1"
    if realm.get("browserFlow") != step_up_alias:
        raise AssertionError("Keycloak must bind the managed browser step-up flow")
    expected_policy = {
        "webAuthnPolicyAuthenticatorAttachment": "cross-platform",
        "webAuthnPolicyResidentKey": "discouraged",
        "webAuthnPolicyUserVerificationRequirement": "required",
        "webAuthnPolicyAvoidSameAuthenticatorRegister": True,
    }
    if any(realm.get(key) != value for key, value in expected_policy.items()):
        raise AssertionError("Keycloak WebAuthn policy must require a cross-platform verified key")

    flows = {
        flow.get("alias"): flow
        for flow in realm.get("authenticationFlows", [])
        if isinstance(flow, dict)
    }
    required_flows = {
        step_up_alias,
        "datariver-authentication-v1",
        "datariver-loa1-v1",
        "datariver-loa2-v1",
    }
    if not required_flows.issubset(flows):
        raise AssertionError("Keycloak managed LoA flows are incomplete")

    loa2_executions = flows["datariver-loa2-v1"].get("authenticationExecutions", [])
    webauthn = next(
        (
            execution
            for execution in loa2_executions
            if execution.get("authenticator") == "webauthn-authenticator"
        ),
        None,
    )
    if not isinstance(webauthn, dict) or webauthn.get("requirement") != "REQUIRED":
        raise AssertionError("Keycloak LoA 2 must require WebAuthn")

    configs = {
        config.get("alias"): config.get("config")
        for config in realm.get("authenticatorConfig", [])
        if isinstance(config, dict)
    }
    if configs.get("datariver-loa2-condition-v1") != {
        "loa-condition-level": "2",
        "loa-max-age": "0",
    }:
        raise AssertionError("Keycloak LoA 2 condition must require fresh authentication")
    if configs.get("datariver-webauthn-reference-v1") != {
        "default.reference.value": "webauthn",
        "default.reference.maxAge": "0",
    }:
        raise AssertionError("Keycloak WebAuthn execution must emit an AMR reference")


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


def verify_readiness_contract() -> None:
    base = _yaml(ROOT / "compose.yaml")
    api_healthcheck = json.dumps(base["services"]["api"]["healthcheck"]["test"])
    if "/health/ready" not in api_healthcheck or "/health/live" in api_healthcheck:
        raise AssertionError("API upstream health must use schema-aware readiness")
    apisix = (ROOT / "infra" / "apisix" / "apisix.yaml").read_text(encoding="utf-8")
    if apisix.count("http_path: /api/v1/health/ready") != 2:
        raise AssertionError("both APISIX upstreams must use readiness")
    if "http_path: /api/v1/health/live" in apisix:
        raise AssertionError("APISIX cannot route using process-only liveness")
    gateway_health = (ROOT / "infra" / "apisix" / "healthcheck.sh").read_text(encoding="utf-8")
    if "/health/ready" not in gateway_health or "/health/live" in gateway_health:
        raise AssertionError("APISIX healthcheck must verify proxied readiness")


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
    assistant_grant = (
        "GRANT SELECT, INSERT ON assistant.chat_sessions, assistant.chat_messages,\n"
        "            assistant.assistant_runs, assistant.evidence_citations TO datariver_app;"
    )
    if assistant_grant not in generator:
        raise AssertionError(
            "assistant evidence citations must remain append-only for the app role"
        )
    if re.search(r"GRANT[^;]*(?:UPDATE|DELETE)[^;]*assistant\.evidence_citations", generator):
        raise AssertionError("the app role cannot mutate or delete assistant evidence citations")


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
    verify_datahub_release_contract()
    verify_identity_assurance_contract()
    verify_runtime_hardening()
    verify_readiness_contract()
    verify_ci_supply_chain()
    verify_database_roles()
    verify_architecture_imports()
    verify_tenant_referential_integrity()
    verify_seed()
    verify_document_links()
    print(
        "static verification passed: compose, build context, DataHub release contract, "
        "identity assurance contract, "
        "runtime hardening/readiness, "
        "CI supply chain, "
        "database roles, architecture, tenant foreign keys, seed, documentation"
    )


if __name__ == "__main__":
    main()
