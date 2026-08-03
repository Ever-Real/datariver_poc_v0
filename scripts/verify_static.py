from __future__ import annotations

import ast
import json
import re
import xml.etree.ElementTree as ET
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
    ROOT / "compose.source-host.yaml",
    ROOT / "compose.connected-source-host.yaml",
    ROOT / "compose.airflow.yaml",
    ROOT / "compose.gateway.yaml",
)
AUX_COMPOSE_FILE = ROOT / "aux-compose.yml"
REQUIRED_DOCKERIGNORE_ENTRIES = {
    ".env",
    ".env.*",
    "secrets",
    "runtime",
    "docker_imgs",
    ".venv",
    ".venv-wsl",
    "frontend/node_modules",
}
EXPECTED_SERVICE_SECRETS = {
    "migrate": {"postgres_password", "postgres_export_password"},
    "storage-init": {"s3_access_key", "s3_secret_key"},
    "semiconductor-seed": {"postgres_password"},
    "local-bootstrap": {"postgres_app_password", "postgres_bootstrap_password"},
    "api": {
        "postgres_app_password",
        "redis_cache_password",
        "redis_delivery_password",
        "datahub_token",
        "intranet_llm_chat_api_key",
        "intranet_llm_embedding_api_key",
        "intranet_llm_reranker_api_key",
        "neo4j_auth",
        "keycloak_identity_admin_client_secret",
        "s3_access_key",
        "s3_governance_document_access_key",
        "s3_governance_document_secret_key",
        "s3_secret_key",
    },
    "outbox-relay": {"postgres_relay_password", "redis_delivery_password"},
    "upload-worker": {
        "postgres_upload_password",
        "redis_delivery_password",
        "s3_access_key",
        "s3_secret_key",
    },
    "upload-validation-worker": {
        "postgres_upload_password",
        "redis_delivery_password",
        "s3_access_key",
        "s3_secret_key",
    },
    "governance-apply-worker": {
        "postgres_governance_password",
        "redis_delivery_password",
        "datahub_token",
    },
    "catalog-export-worker": {
        "postgres_export_password",
        "redis_delivery_password",
        "s3_export_access_key",
        "s3_export_secret_key",
    },
    "quality-worker": {
        "postgres_quality_password",
        "redis_delivery_password",
    },
    "governance-document-worker": {
        "postgres_governance_document_password",
        "redis_delivery_password",
        "s3_governance_document_access_key",
        "s3_governance_document_secret_key",
        "intranet_llm_chat_api_key",
        "intranet_llm_embedding_api_key",
        "neo4j_auth",
    },
    "knowledge-source-worker": {
        "postgres_knowledge_password",
        "redis_delivery_password",
        "s3_knowledge_access_key",
        "s3_knowledge_secret_key",
        "intranet_llm_chat_api_key",
        "intranet_llm_embedding_api_key",
    },
    "knowledge-tbox-proposal-worker": {
        "postgres_knowledge_proposal_password",
        "redis_delivery_password",
        "s3_knowledge_access_key",
        "s3_knowledge_secret_key",
        "intranet_llm_chat_api_key",
    },
    "knowledge-studio-ingestion-worker": {
        "postgres_knowledge_ingestion_password",
        "redis_delivery_password",
        "intranet_llm_embedding_api_key",
    },
}
DATAHUB_CONTRACT_DIRECTORY = ROOT / "infra" / "contracts"
DATAHUB_COMPONENTS = {"actions", "frontend", "gms", "upgrade"}
IMMUTABLE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
EXACT_STABLE_RELEASE = re.compile(r"v\d+\.\d+\.\d+\Z")
PRODUCTION_SOURCE_ROOTS = (
    ROOT / "backend" / "src",
    ROOT / "frontend" / "src",
    ROOT / "infra" / "airflow" / "dags",
)
SOURCE_SUFFIXES = {".js", ".jsx", ".py", ".ts", ".tsx"}


def _yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{path.relative_to(ROOT)} must contain a YAML mapping")
    return value


def verify_compose() -> None:
    compose_files = (*COMPOSE_FILES, AUX_COMPOSE_FILE)
    documents = {path: _yaml(path) for path in compose_files}
    base_services = set(documents[COMPOSE_FILES[0]].get("services", {}))
    base_secrets = set(documents[COMPOSE_FILES[0]].get("secrets", {}))
    forbidden_bundled_connectors = {"valkey-cache", "valkey-queue", "redis", "minio", "seaweedfs"}
    bundled = base_services & forbidden_bundled_connectors
    if bundled:
        raise AssertionError(
            f"compose.yaml must not own external Redis/S3 connector services: {sorted(bundled)}"
        )
    forbidden_volumes = {"valkey-queue-data", "redis-data", "minio-data", "seaweed-data"}
    declared_volumes = set(documents[COMPOSE_FILES[0]].get("volumes", {}))
    if declared_volumes & forbidden_volumes:
        raise AssertionError("compose.yaml must not own external Redis/S3 data volumes")
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

    source_host = documents[ROOT / "compose.source-host.yaml"]
    source_access = source_host.get("networks", {}).get("source-access", {})
    if source_access.get("internal") is not False:
        raise AssertionError(
            "compose.source-host.yaml:source-access must remain non-internal for "
            "loopback port publication"
        )
    source_host_services = source_host["services"]
    for name in ("postgres",):
        networks = set(source_host_services[name].get("networks", []))
        if networks != {"data", "source-access"}:
            raise AssertionError(
                f"compose.source-host.yaml:{name} must keep private data access and the "
                "dedicated source-access publication bridge"
            )
    connected_source_host = documents[ROOT / "compose.connected-source-host.yaml"]
    connected_postgres = connected_source_host["services"]["postgres"]
    if connected_postgres.get("pull_policy") != "never":
        raise AssertionError(
            "compose.connected-source-host.yaml:postgres must not access a registry"
        )
    connected_keycloak = connected_source_host["services"]["keycloak"]
    if connected_keycloak.get("pull_policy") != "never":
        raise AssertionError(
            "compose.connected-source-host.yaml:keycloak must use the existing final image"
        )
    base = documents[ROOT / "compose.yaml"]
    connectors = base.get("networks", {}).get("connectors", {})
    if connectors.get("external") is not True:
        raise AssertionError("compose.yaml:connectors must be a shared external network")
    if connectors.get("name") != "${DATARIVER_CONNECTOR_NETWORK:-datariver-connectors}":
        raise AssertionError("compose.yaml:connectors must have a stable deployment-owned name")
    for name in (
        "api",
        "storage-init",
        "outbox-relay",
        "upload-worker",
        "upload-validation-worker",
        "governance-apply-worker",
        "catalog-export-worker",
        "knowledge-source-worker",
    ):
        networks = set(base["services"][name].get("networks", []))
        if not networks:
            networks = set(base.get("x-backend", {}).get("networks", []))
        if "connectors" not in networks:
            raise AssertionError(f"compose.yaml:{name} must reach external connector endpoints")

    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    for setting in (
        "REDIS_CACHE_URL=",
        "REDIS_DELIVERY_URL=",
        "REDIS_CACHE_SECRET_REF=",
        "REDIS_DELIVERY_SECRET_REF=",
        "S3_ENDPOINT_URL=",
        "S3_PUBLIC_ENDPOINT_URL=",
    ):
        if setting not in env_example:
            raise AssertionError(f".env.example is missing external connector setting {setting}")


def verify_datahub_mac_capacity_contract() -> None:
    override_path = ROOT / "infra" / "datahub" / "datahub-v1.6.0-mac-dev.images.yaml"
    override_source = override_path.read_text(encoding="utf-8")
    override = yaml.safe_load(override_source.replace("!override", ""))
    if not isinstance(override, dict):
        raise AssertionError("DataHub Mac override must contain a YAML mapping")
    services = override.get("services", {})
    if not isinstance(services, dict):
        raise AssertionError("DataHub Mac override services must be a mapping")

    actions = services.get("datahub-actions", {})
    if not isinstance(actions, dict) or actions.get("environment", {}).get("UV_NO_CACHE") != "1":
        raise AssertionError("DataHub Actions must disable its persistent uv cache")

    gms = services.get("datahub-gms", {})
    logging = gms.get("logging", {}) if isinstance(gms, dict) else {}
    if logging != {
        "driver": "json-file",
        "options": {"max-size": "64m", "max-file": "4"},
    }:
        raise AssertionError("DataHub GMS must keep a bounded local json-file log")
    expected_logback_mount = (
        "${DATARIVER_REPOSITORY_ROOT:?required}/infra/datahub/gms-logback.xml:"
        "/etc/datariver/datahub/gms-logback.xml:ro"
    )
    if expected_logback_mount not in gms.get("volumes", []):
        raise AssertionError("DataHub GMS must mount the checked-in bounded logback policy")
    java_options = gms.get("environment", {}).get("JAVA_OPTS", "")
    if java_options != (
        "-Xms1g -Xmx1g -Dlogback.configurationFile=/etc/datariver/datahub/gms-logback.xml"
    ):
        raise AssertionError("DataHub GMS must activate the bounded logback policy")

    logback_path = ROOT / "infra" / "datahub" / "gms-logback.xml"
    if logback_path.is_symlink() or not logback_path.is_file():
        raise AssertionError("The checked-in DataHub GMS logback policy is not a regular file")
    if logback_path.stat().st_size > 16 * 1024:
        raise AssertionError("The checked-in DataHub GMS logback policy is unexpectedly large")
    # This parser reads one size-bounded, repository-controlled file, never deployment input.
    logback_root = ET.parse(logback_path).getroot()  # noqa: S314
    expected_policies = {
        "FILE": ("32MB", "128MB", "3"),
        "DEBUG_FILE": ("16MB", "64MB", "1"),
        "GRAPHQL_DEBUG_FILE": ("16MB", "64MB", "1"),
    }
    for appender_name, expected in expected_policies.items():
        appender = logback_root.find(f"./appender[@name='{appender_name}']")
        policy = appender.find("rollingPolicy") if appender is not None else None
        observed = (
            policy.findtext("maxFileSize") if policy is not None else None,
            policy.findtext("totalSizeCap") if policy is not None else None,
            policy.findtext("maxHistory") if policy is not None else None,
        )
        if observed != expected:
            raise AssertionError(
                f"DataHub GMS {appender_name} producer log retention is not bounded"
            )

    start_source = (ROOT / "scripts" / "start_datahub_mac_dev.sh").read_text(encoding="utf-8")
    for fragment in (
        'datahub_commit="059a36c0b035a6057de00114ccac0ea9003d6bc2"',
        'image_override="$root/infra/datahub/datahub-v1.6.0-mac-dev.images.yaml"',
        'export DATARIVER_REPOSITORY_ROOT="$root"',
        '-f "$image_override"',
    ):
        if fragment not in start_source:
            raise AssertionError("DataHub Mac startup must use the pinned checked-in override")


def verify_observability_contract() -> None:
    auxiliary = _yaml(AUX_COMPOSE_FILE)
    services = auxiliary.get("services", {})
    if not isinstance(services, dict):
        raise AssertionError("aux-compose.yml: services must be a mapping")
    expected_services = {
        "otel-collector",
        "prometheus",
        "grafana",
        "alertmanager",
        "tempo",
        "loki",
    }
    if set(services) != expected_services:
        raise AssertionError("aux-compose.yml must contain the approved observability services")
    grafana = services["grafana"]
    if grafana.get("secrets") != ["grafana_admin_password"]:
        raise AssertionError("Grafana must use a generated file-mounted admin secret")
    environment = grafana.get("environment", {})
    if environment.get("GF_SECURITY_ADMIN_PASSWORD__FILE") != (
        "/run/secrets/grafana_admin_password"
    ):
        raise AssertionError("Grafana admin password must be sourced from its Compose secret")
    for name, service in services.items():
        profiles = service.get("profiles", [])
        if profiles != ["observability"]:
            raise AssertionError(f"aux-compose.yml:{name} must remain opt-in")
        if "no-new-privileges:true" not in service.get("security_opt", []):
            raise AssertionError(f"aux-compose.yml:{name} must prevent privilege escalation")
    required_files = {
        ROOT / "infra" / "observability" / "otel-collector.yaml",
        ROOT / "infra" / "observability" / "otel-collector.enterprise.example.yaml",
        ROOT / "infra" / "observability" / "prometheus.yml",
        ROOT / "infra" / "observability" / "alertmanager.yml",
        ROOT / "infra" / "observability" / "tempo.yaml",
        ROOT / "infra" / "observability" / "loki.yaml",
        ROOT
        / "infra"
        / "observability"
        / "grafana"
        / "provisioning"
        / "datasources"
        / "datariver.yaml",
    }
    missing = {path.relative_to(ROOT).as_posix() for path in required_files if not path.is_file()}
    if missing:
        raise AssertionError(f"observability configuration is incomplete: {sorted(missing)}")


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


def verify_multiarch_release_contract() -> None:
    required_pins = {
        ROOT / "backend" / "Dockerfile": {
            "uv:0.9.17@sha256:5cb6b54d2bc3fe2eb9a8483db958a0b9eebf9edff68adedb369df8e7b98711a2",
            "python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c",
        },
        ROOT / "frontend" / "Dockerfile": {
            "node:22.19.0-bookworm-slim@sha256:4a4884e8a44826194dff92ba316264f392056cbe243dcc9fd3551e71cea02b90",
            "nginx:1.30.3-alpine3.23@sha256:0d3b80406a13a767339fbe2f41406d6c7da727ab89cf8fae399e81f780f814d1",
        },
        ROOT / "infra" / "keycloak" / "Dockerfile": {
            "keycloak:26.7.0@sha256:2eb3cd316835c990e69e26ade292ffa78f6fb0db7d5fc6377463c162e1979ac0",
        },
        ROOT / "compose.yaml": {
            "pgvector/pgvector:0.8.2-pg17-bookworm@sha256:feb68f4f15446397d8cac7f4fe48fe4586de83160d1fc48b46283312d1a33966",
        },
        ROOT / "compose.local-connectors.yaml": {
            "redis:8.2.6-bookworm@sha256:3055dc25265b0c19ec90a1756dad4e0faff6f79e2557a6ac3d1274e39ee906f6",
            "minio:RELEASE.2025-09-07T16-13-09Z@sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e",
            "cypher-shell -u neo4j",
        },
    }
    for path, fragments in required_pins.items():
        content = path.read_text(encoding="utf-8")
        missing = {fragment for fragment in fragments if fragment not in content}
        if missing:
            raise AssertionError(
                f"{path.relative_to(ROOT)} is missing multi-architecture image pins: {missing}"
            )

    exporter = (ROOT / "scripts" / "export_offline_images.sh").read_text(encoding="utf-8")
    for fragment in (
        "status --porcelain --untracked-files=normal",
        "arm64|aarch64",
        "amd64|x86_64",
        "datariver-source.bundle",
        "release-index.tsv",
        "offline-core.compose.yaml",
        "source-commit.txt.sha256",
        "--accept-local-connector-license-review",
        "platform_staging_dir=$(mktemp -d",
        'docker image pull --platform "$target_platform" "$image"',
        'pinned_id=$(docker image inspect --platform "$target_platform"',
        'docker image pull --platform "$target_platform" "$original"',
        'if [ "$tagged_id" != "$pinned_id" ]',
        'docker image save --platform "$target_platform"',
        'docker image inspect --platform "$target_platform"',
        "save_image=${image%@sha256:*}",
        "Saved archive omitted required image tag",
        "include_local_connectors",
        "datariver-next-knowledge-source-worker:latest",
        "catalog-export-worker knowledge-source-worker web keycloak",
        "compose.airflow.yaml infra/airflow/Dockerfile infra/postgres/init-airflow.sh",
        '"$output_dir"/*.bundle',
    ):
        if fragment not in exporter:
            raise AssertionError(f"offline exporter is missing release guard: {fragment}")
    if "RELEASE.2025-10-15T17-29-55Z" in exporter:
        raise AssertionError("offline exporter references a nonexistent MinIO container tag")
    if "FROM --platform=$TARGETPLATFORM ${BASE_IMAGE}" in exporter:
        raise AssertionError("offline exporter must not wrap external images and change identity")

    verifier = (ROOT / "scripts" / "verify_offline_release.sh").read_text(encoding="utf-8")
    for fragment in (
        'verify_checksums "$release_root"',
        'bundle verify "$bundle"',
        'bundle list-heads "$bundle"',
        "Claimed source commit is absent from the source bundle",
        "Source checkout does not match release commit",
        "Loaded image platform mismatch",
        "inspect_image=${image%@sha256:*}",
        "Source checkout is not clean",
        "Indexed artifact is missing",
        "offline-core.compose.yaml",
        "config --images",
        "--artifact-only and --load are mutually exclusive",
        "require_platform_artifact offline-local-connectors.compose.yaml",
        "include_observability=$(release_flag include_observability)",
        "verify_compose_inventory --profile object-storage",
        "Compose image is absent from the selected release manifests",
    ):
        if fragment not in verifier:
            raise AssertionError(f"offline verifier is missing fail-closed check: {fragment}")

    migration_runbook = (ROOT / "docs" / "26_MAC_TO_WSL_MIGRATION_RUNBOOK.md").read_text(
        encoding="utf-8"
    )
    for fragment in (
        "/transfer/datariver-RELEASE/datariver-source.bundle",
        "</run/secrets/postgres_password",
        "run --rm --pull never local-bootstrap",
        "SELECT count(*) FROM iam.subjects",
        "--source-access-key-file /transfer/migration/source-minio/access_key",
        "--target-access-key-file secrets/s3_access_key",
        "NEO4J_ALLOWED_HOSTS=neo4j",
    ):
        if fragment not in migration_runbook:
            raise AssertionError(f"WSL migration runbook omits fail-closed step: {fragment}")

    object_migrator = (ROOT / "scripts" / "migrate_s3_objects.py").read_text(encoding="utf-8")
    for fragment in (
        'raw["malformed_count"] != 0',
        'raw["conflict_count"] != 0',
        "Source object is missing",
        "does not match PostgreSQL manifest",
        "use_threads=False",
    ):
        if fragment not in object_migrator:
            raise AssertionError(f"S3 migrator is missing fail-closed guard: {fragment}")

    manifest_query = (ROOT / "scripts" / "export_s3_migration_manifest.sql").read_text(
        encoding="utf-8"
    )
    for fragment in (
        "WHERE state = 'ACCEPTED'",
        "governance.change_request_attachments",
        "governance.manual_metadata_submissions",
        "knowledge.source_snapshots",
        "catalog.export_requests",
        "conflict_count",
    ):
        if fragment not in manifest_query:
            raise AssertionError(f"S3 migration manifest omits required evidence: {fragment}")

    keycloak_host_dev = (ROOT / "scripts" / "configure_keycloak_host_dev.sh").read_text(
        encoding="utf-8"
    )
    for fragment in (
        'docker exec "$container"',
        'attributes.\\"pkce.code.challenge.method\\"',
        'attributes.\\"post.logout.redirect.uris\\"',
        'attributes.\\"default.acr.values\\"',
        "clientId=datariver-airflow",
        "/run/secrets/airflow_client_secret",
        "clientId=datariver-quality-dispatch",
        "/run/secrets/quality_dispatch_client_secret",
        "datariver-api-audience",
        "__DATARIVER_SERVICE_IDENTITIES__",
        "trap '\\''rm -f",
    ):
        if fragment not in keycloak_host_dev:
            raise AssertionError(f"Keycloak host-development sync omits guard: {fragment}")
    if "set-password" in keycloak_host_dev:
        raise AssertionError("Keycloak host-development sync must not rotate an existing user")
    for fragment in (
        'if [ -z "$user_id" ]; then',
        "demo_password=$(cat /run/secrets/keycloak_demo_password)",
        '-s "credentials=[',
        "unset demo_password",
        "__DATARIVER_DEMO_IDENTITIES__",
        "local-demo-identities.json",
    ):
        if fragment not in keycloak_host_dev:
            raise AssertionError(
                f"Keycloak host-development sync omits new-user credential guard: {fragment}"
            )
    local_bootstrap = _yaml(ROOT / "compose.yaml")["services"]["local-bootstrap"]
    if (
        "./runtime/identity/local-demo-identities.json:"
        "/run/datariver/local-demo-identities.json:ro" not in local_bootstrap.get("volumes", [])
    ):
        raise AssertionError("Local bootstrap must consume the Keycloak demo identity state")
    keycloak_imports = _yaml(ROOT / "compose.identity.yaml")["services"]["keycloak"].get(
        "volumes", []
    )
    if any("local-demo-identities.json" in mount for mount in keycloak_imports):
        raise AssertionError("Keycloak realm imports must not include runtime identity state")

    connector_network = (ROOT / "scripts" / "ensure_connector_network.sh").read_text(
        encoding="utf-8"
    )
    for fragment in (
        'docker network inspect "$network"',
        'docker network create --driver bridge "$network"',
        "*[!A-Za-z0-9_.-]*",
    ):
        if fragment not in connector_network:
            raise AssertionError(f"connector network bootstrap omits guard: {fragment}")

    s3_probe = (ROOT / "scripts" / "probe_s3_contract.py").read_text(encoding="utf-8")
    for fragment in (
        '"upload_part"',
        "public_client.generate_presigned_url",
        '"x-amz-checksum-sha256"',
        "create_multipart_upload",
        "complete_multipart_upload",
        "copy_object",
        "Anonymous object",
        '"access-control-allow-methods"',
        '"access-control-allow-headers"',
        "CORS preflight did not return the exact allowed origin",
        "client.delete_object",
    ):
        if fragment not in s3_probe:
            raise AssertionError(f"S3 contract probe omits evidence: {fragment}")


def verify_datahub_release_contract() -> None:
    contracts = tuple(sorted(DATAHUB_CONTRACT_DIRECTORY.glob("datahub-*-images.json")))
    if not contracts:
        raise AssertionError("At least one reviewed DataHub image contract is required")
    for contract_path in contracts:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        release = contract.get("release")
        if contract.get("schema_version") != 1 or not isinstance(release, str):
            raise AssertionError(f"{contract_path.name} must declare an exact stable release")
        if EXACT_STABLE_RELEASE.fullmatch(release) is None:
            raise AssertionError(
                f"{contract_path.name} uses a prerelease or partial DataHub version"
            )
        components = contract.get("components")
        if not isinstance(components, dict) or set(components) != DATAHUB_COMPONENTS:
            raise AssertionError(f"{contract_path.name} component set is incomplete")
        for name, component in components.items():
            if not isinstance(component, dict):
                raise AssertionError(f"DataHub component {name} must be a mapping")
            image = component.get("image")
            digest = component.get("oci_index_digest")
            if not isinstance(image, str) or f":{release}" not in image:
                raise AssertionError(
                    f"DataHub component {name} does not use its declared release tag"
                )
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
    quality_dispatch_client = next(
        (client for client in clients if client.get("clientId") == "datariver-quality-dispatch"),
        None,
    )
    if not isinstance(quality_dispatch_client, dict):
        raise AssertionError("Keycloak realm has no dedicated Quality dispatch client")
    if (
        quality_dispatch_client.get("publicClient") is not False
        or quality_dispatch_client.get("serviceAccountsEnabled") is not True
        or quality_dispatch_client.get("standardFlowEnabled") is not False
        or quality_dispatch_client.get("directAccessGrantsEnabled") is not False
    ):
        raise AssertionError("Quality dispatch client must be service-account-only")
    quality_audiences: set[object] = set()
    for mapper in quality_dispatch_client.get("protocolMappers", []):
        if not isinstance(mapper, dict):
            continue
        mapper_config = mapper.get("config")
        if isinstance(mapper_config, dict):
            quality_audiences.add(mapper_config.get("included.client.audience"))
    if quality_audiences != {"datariver-api"}:
        raise AssertionError("Quality dispatch client must emit only the DataRiver API audience")
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

    compose = _yaml(ROOT / "compose.yaml")
    web_environment = compose["services"]["web"].get("environment", {})
    if web_environment.get("BROWSER_OIDC_HIGH_ASSURANCE_ACR") != "${OIDC_STEP_UP_ACR:-2}":
        raise AssertionError("web runtime step-up ACR must be a deployment setting")
    if web_environment.get("BROWSER_OIDC_PASSWORD_REAUTH_ACR") != (
        "${OIDC_PASSWORD_REAUTH_REQUEST_ACR:-1}"
    ):
        raise AssertionError(
            "web runtime password reauthentication ACR must be a deployment setting"
        )
    dockerfile = (ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    if "ARG VITE_OIDC" in dockerfile:
        raise AssertionError("web OIDC configuration must not be embedded at image build time")
    entrypoint = (ROOT / "frontend" / "docker-entrypoint.sh").read_text(encoding="utf-8")
    if "BROWSER_OIDC_HIGH_ASSURANCE_ACR" not in entrypoint:
        raise AssertionError("web image must generate the runtime step-up ACR")
    if "BROWSER_OIDC_PASSWORD_REAUTH_ACR" not in entrypoint:
        raise AssertionError("web image must generate the runtime password reauthentication ACR")
    frontend_auth = (ROOT / "frontend" / "src" / "auth" / "redirectState.ts").read_text(
        encoding="utf-8"
    )
    if "webauthn-register:skip_if_exists" not in frontend_auth or "max_age: 0" not in frontend_auth:
        raise AssertionError("web must use explicit fresh WebAuthn enrollment and step-up")
    frontend_provider = (ROOT / "frontend" / "src" / "auth" / "AuthProvider.tsx").read_text(
        encoding="utf-8"
    )
    if (
        "oidcPasswordReauthAcr" not in frontend_provider
        or "beginPasswordReauth" not in frontend_provider
        or "PASSWORD_REAUTH" not in frontend_auth
    ):
        raise AssertionError("web password reauthentication must remain explicit and fail-closed")


def verify_runtime_hardening() -> None:
    documents = {path.name: _yaml(path) for path in (*COMPOSE_FILES, AUX_COMPOSE_FILE)}
    expected_read_only = {
        "compose.yaml": {
            "api",
            "outbox-relay",
            "upload-worker",
            "upload-validation-worker",
            "governance-apply-worker",
            "catalog-export-worker",
            "knowledge-source-worker",
            "web",
        },
        "compose.identity.yaml": {"keycloak"},
        "compose.airflow.yaml": {"airflow-db-init"},
        "compose.gateway.yaml": {"apisix"},
        "aux-compose.yml": {"otel-collector", "prometheus", "alertmanager"},
    }
    expected_no_new_privileges = {
        "compose.yaml": expected_read_only["compose.yaml"],
        "compose.identity.yaml": {"keycloak"},
        "compose.gateway.yaml": {"apisix"},
        "compose.airflow.yaml": {
            "airflow-db-init",
            "airflow-init",
            "airflow-api-server",
            "airflow-scheduler",
            "airflow-dag-processor",
            "airflow-triggerer",
        },
        "aux-compose.yml": {
            "otel-collector",
            "prometheus",
            "grafana",
            "alertmanager",
            "tempo",
            "loki",
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
    if "${DATAHUB_EMBED_BASE_URL}" not in nginx_template:
        raise AssertionError("web CSP must allow only the deployment-approved DataHub embed origin")
    if nginx_template.count("add_header_inherit merge;") != 1:
        raise AssertionError(
            "web Nginx must recursively merge server security headers into "
            "header-defining locations"
        )
    required_web_headers = {
        'add_header X-Content-Type-Options "nosniff" always;',
        'add_header Referrer-Policy "no-referrer" always;',
        'add_header X-Frame-Options "DENY" always;',
        'add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;',
        (
            "add_header Content-Security-Policy \"default-src 'self'; base-uri 'self'; "
            "object-src 'none'; frame-ancestors 'none'; img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self' "
            "${S3_PUBLIC_ORIGIN} ${OIDC_PUBLIC_ORIGIN}; frame-src ${OIDC_PUBLIC_ORIGIN} "
            "${DATAHUB_EMBED_BASE_URL} ${GRAFANA_EMBED_BASE_URL} http: https:; "
            "form-action 'self' ${OIDC_PUBLIC_ORIGIN}\" always;"
        ),
    }
    missing_web_headers = {
        header for header in required_web_headers if nginx_template.count(header) != 1
    }
    if missing_web_headers:
        raise AssertionError(
            "web Nginx security headers must have one canonical always rule: "
            f"{sorted(missing_web_headers)}"
        )
    api_location = re.search(
        r"^\s*location /api/ \{(?P<body>.*?)^\s{4}\}",
        nginx_template,
        flags=re.MULTILINE | re.DOTALL,
    )
    if api_location is None:
        raise AssertionError("web Nginx API location is missing")
    required_hidden_headers = {
        "Content-Security-Policy",
        "Permissions-Policy",
        "Referrer-Policy",
        "X-Content-Type-Options",
        "X-Frame-Options",
    }
    hidden_headers = re.findall(
        r"proxy_hide_header\s+([^;]+);",
        api_location.group("body"),
        flags=re.IGNORECASE,
    )
    expected_hidden_headers = {name.casefold() for name in required_hidden_headers}
    actual_hidden_headers = {name.casefold() for name in hidden_headers}
    if (
        len(hidden_headers) != len(required_hidden_headers)
        or actual_hidden_headers != expected_hidden_headers
    ):
        missing_hidden_headers = expected_hidden_headers - actual_hidden_headers
        unexpected_hidden_headers = actual_hidden_headers - expected_hidden_headers
        raise AssertionError(
            "web Nginx /api must hide exactly the canonical browser-security headers: "
            f"missing={sorted(missing_hidden_headers)}, "
            f"unexpected={sorted(unexpected_hidden_headers)}, count={len(hidden_headers)}"
        )
    if "strict-transport-security" in nginx_template.casefold():
        raise AssertionError(
            "the inner HTTP web container must not emit Strict-Transport-Security; "
            "HSTS belongs to the approved external TLS edge"
        )
    if nginx_template.count('add_header Cache-Control "no-store" always;') != 3:
        raise AssertionError("health, runtime config and SPA shell must remain no-store")
    if nginx_template.count('add_header Cache-Control "public, immutable";') != 1:
        raise AssertionError("only the hashed-asset location may add immutable cache policy")
    web_environment = documents["compose.yaml"]["services"]["web"].get("environment", {})
    if web_environment.get("DATAHUB_EMBED_BASE_URL") != "${DATAHUB_EMBED_BASE_URL:-}":
        raise AssertionError("web CSP must receive the same DataHub embed origin as the API")


def verify_host_development_ports() -> None:
    required_fragments = {
        ROOT / "scripts" / "dev_host.sh": {
            "datahub_base_url=$(env_file_value DATAHUB_BASE_URL http://127.0.0.1:8080)",
            "api_port=$(env_file_value API_PORT 38101)",
            "web_port=$(env_file_value WEB_PORT 38102)",
            "intranet_source_host_enabled=$(env_file_value INTRANET_SOURCE_HOST_ENABLED false)",
            "airflow_source_api_bridge_enabled=$(env_file_value "
            "AIRFLOW_SOURCE_API_BRIDGE_ENABLED false)",
            "line=${line%$'\\r'}",
            "stop_owned_vite_processes",
            "require_postgres_listener",
            "A container shown only as 5432/tcp is not published",
            "workflow_source_host_infra.py",
            "show_optional_status airflow-api-bridge",
            "required_processes+=(airflow-api-bridge)",
            'export NEO4J_AUTH_SECRET_REF="$(secret_ref neo4j_auth)"',
            'DATARIVER_ENV_FILE="$env_file_argument" "$root/scripts/reconcile-postgres-roles.sh"',
            "export NEO4J_SOURCE_HOST_ENABLED=true",
            'export NEO4J_URI="bolt://127.0.0.1:${NEO4J_BOLT_PORT:-17687}"',
            "Duplicate environment key",
            "DATARIVER_SELECTED_ENV_FILE",
            'vite_entry="$root/frontend/node_modules/vite/bin/vite.js"',
            "DataRiver source development requires Node.js >=22.19.0.",
            "@rolldown/binding-linux-x64-gnu/rolldown-binding.linux-x64-gnu.node",
            "npm --prefix frontend ci --include=optional",
            'start_process vite "$root/frontend" "$node" "$vite_entry"',
            '"$root/scripts/source_api_bridge.py"',
            'VITE_API_PROXY_TARGET="http://127.0.0.1:$api_port"',
            'VITE_ALLOWED_HOSTS="$web_public_host"',
            "--host 127.0.0.1",
        },
        ROOT / "scripts" / "bootstrap.sh": {
            "web_public_origin=http://localhost:38102",
            "set_env_value API_PORT 38101",
            "set_env_value WEB_PORT 38102",
            "DATARIVER_BOOTSTRAP_ENV_NAME",
            "set_env_value SYSTEM_CONFIGURATION_RUNTIME_ACTIVATION_ENABLED false",
            "--source-host-airflow-bridge",
            "set_env_value AIRFLOW_SOURCE_API_BRIDGE_PORT 38103",
            "--intranet-source-host",
            "set_env_value INTRANET_SOURCE_HOST_ENABLED",
            "set_env_value NEO4J_IMAGE neo4j:2026.06.0",
            "set_env_value NEO4J_SOURCE_HOST_ENABLED true",
            "set_env_value NEO4J_URI bolt://neo4j:7687",
            "set_env_value NEO4J_AUTH_SECRET_REF file:/run/secrets/neo4j_auth",
            "set_env_value KNOWLEDGE_SOURCE_WORKER_ENABLED false",
        },
        ROOT / "scripts" / "configure_keycloak_host_dev.sh": {
            "web_origin=${web_origin:-http://localhost:38102}",
            "INTRANET_SOURCE_HOST_ENABLED",
            "OIDC_PUBLIC_AUTHORITY must match OIDC_PUBLIC_ORIGIN",
        },
        ROOT / "scripts" / "start_gateway_host_dev.sh": {
            "api_port=${api_port:-38101}",
            '"$host_gateway:$api_port"',
        },
        ROOT / "frontend" / "vite.config.ts": {
            "value('API_PORT') || '38101'",
            "value('WEB_PORT') || '38102'",
            "VITE_ALLOWED_HOSTS",
        },
        ROOT / "scripts" / "render_wsl_intranet_nginx.py": {
            "INTRANET_SOURCE_HOST_ENABLED=true",
            "proxy_pass http://127.0.0.1:",
            "An unrestricted 0.0.0.0/0 or ::/0 client network is forbidden",
        },
        ROOT / "scripts" / "workflow_source_host_infra.py": {
            "compose.source-host.yaml",
            "offline-core.compose.yaml.sha256",
            "datariver-core-amd64.manifest.tsv.sha256",
            "Loaded image does not match the verified release manifest",
            "service_images = rendered_service_images",
            "retained a registry-only digest",
            "--reuse-local-images",
            "--connected-build",
            "compose.connected-source-host.yaml",
            "verify_local_source_images",
            "--neo4j-bundle-dir",
            "--reuse-loaded-neo4j",
            "approved_neo4j_source_image",
            "load_neo4j_bundle",
            "verify_and_load_neo4j_image",
            "configured_loaded_neo4j_image",
            "verify_loaded_neo4j_image",
            "resolve_neo4j_environment(plan, neo4j_bundle.image)",
            "start_and_verify_neo4j",
            '"exec",',
            '"-T",',
            '"RETURN 1"',
            '"--build",',
            '"--no-build", "--pull", "never"',
        },
        ROOT / "compose.connected-source-host.yaml": {
            "${SOURCE_HOST_POSTGRES_IMAGE:-pgvector/pgvector:0.8.2-pg17-bookworm}",
            "${SOURCE_HOST_KEYCLOAK_IMAGE:-datariver-keycloak:26.7.0}",
            "pull_policy: never",
        },
    }
    for path, fragments in required_fragments.items():
        content = path.read_text(encoding="utf-8")
        missing = fragments - {fragment for fragment in fragments if fragment in content}
        if missing:
            raise AssertionError(
                f"{path.relative_to(ROOT)} has drifted from the host-development port contract: "
                f"{sorted(missing)}"
            )

    gateway_host_dev = (ROOT / "compose.gateway.host-dev.yaml").read_text(encoding="utf-8")
    if "${DATARIVER_API_UPSTREAM:-host.docker.internal:38101}" not in gateway_host_dev:
        raise AssertionError("host-development APISIX must default to the source API on 38101")

    bootstrap = (ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")
    mac_block = bootstrap.rsplit('if [ "$mac_development" = true ]; then', 1)[1].split("\nfi\n", 1)[
        0
    ]
    for fragment in (
        "set_env_value WEB_PORT 38102",
        "set_env_value API_PORT 38101",
        "set_env_value POSTGRES_PORT 15432",
    ):
        if fragment not in mac_block:
            raise AssertionError(
                "Mac development must use the same 38101/38102 developer port contract"
            )

    wsl_block = bootstrap.rsplit('if [ "$wsl_preparation" = true ]; then', 1)[1].split("\nfi\n", 1)[
        0
    ]
    for fragment in (
        "set_env_value OIDC_ISSUER http://localhost:8081/realms/datariver",
        "set_env_value OIDC_JWKS_URL http://keycloak:8080/realms/datariver/protocol/openid-connect/certs",
        "set_env_value LOCAL_OLLAMA_CHAT_ENABLED false",
    ):
        if fragment not in wsl_block:
            raise AssertionError(
                "WSL preparation must separate the public token issuer from private JWKS access"
            )

    admin_routes = (
        ROOT / "backend" / "src" / "datariver" / "interfaces" / "http" / "routes" / "admin.py"
    ).read_text(encoding="utf-8")
    forbidden_routes = (
        '@router.get(\n    "/system-configuration/{system_id}/versions"',
        '@router.put(\n    "/system-configuration/{system_id}"',
        '@router.post(\n    "/system-configuration/{system_id}/test-draft"',
        '@router.post(\n    "/system-configuration/{system_id}/test"',
        '@router.post(\n    "/system-configuration/{system_id}/activate"',
    )
    if any(fragment in admin_routes for fragment in forbidden_routes):
        raise AssertionError("database-backed system configuration routes must remain retired")
    if (
        '@router.get("/system-configuration"' not in admin_routes
        or '"/system-configuration/{system_id}/test-deployment"' not in admin_routes
    ):
        raise AssertionError(
            "Admin system configuration must expose only inventory and deployment probes"
        )
    runtime_consumers = (
        ROOT / "backend" / "src" / "datariver" / "interfaces" / "http" / "factory.py",
        *(ROOT / "backend" / "src" / "datariver" / "workers").glob("*.py"),
    )
    if any(
        "resolve_activated_system_configuration" in path.read_text(encoding="utf-8")
        for path in runtime_consumers
    ):
        raise AssertionError("API and workers must load only deployment-owned Settings")

    core = _yaml(ROOT / "compose.yaml")
    if "127.0.0.1:${API_PORT:-8000}:8000" not in core["services"]["api"].get("ports", []):
        raise AssertionError(
            "host-development ports must not change the container API port contract"
        )


def verify_readiness_contract() -> None:
    base = _yaml(ROOT / "compose.yaml")
    api_healthcheck = json.dumps(base["services"]["api"]["healthcheck"]["test"])
    if "/health/ready" not in api_healthcheck or "/health/live" in api_healthcheck:
        raise AssertionError("API upstream health must use schema-aware readiness")
    apisix = (ROOT / "infra" / "apisix" / "apisix.yaml").read_text(encoding="utf-8")
    if apisix.count("http_path: /api/v1/health/ready") != 2:
        raise AssertionError("both APISIX upstreams must use readiness")
    if (
        apisix.count("discovery_type: dns") != 2
        or apisix.count('service_name: "__DATARIVER_API_UPSTREAM__"') != 2
    ):
        raise AssertionError("APISIX upstreams must re-resolve a replaced API container")
    apisix_config = (ROOT / "infra" / "apisix" / "config.yaml").read_text(encoding="utf-8")
    if '"127.0.0.11:53"' not in apisix_config:
        raise AssertionError("APISIX DNS discovery must use Docker's embedded resolver")
    if "http_path: /api/v1/health/live" in apisix:
        raise AssertionError("APISIX cannot route using process-only liveness")
    gateway_health = (ROOT / "infra" / "apisix" / "healthcheck.sh").read_text(encoding="utf-8")
    if "/health/ready" not in gateway_health or "/health/live" in gateway_health:
        raise AssertionError("APISIX healthcheck must verify proxied readiness")


def verify_browser_storage_boundary() -> None:
    frontend_source = ROOT / "frontend" / "src"
    source_files = tuple(frontend_source.rglob("*.ts")) + tuple(frontend_source.rglob("*.tsx"))
    webauthn_warning_file = frontend_source / "features" / "admin" / "AdminPage.tsx"
    allowed_warning_storage = (
        "const key = `webAuthnWarningShown_${context.subject_id}`",
        "window.localStorage.getItem(key)",
        "window.localStorage.setItem(key, 'true')",
    )
    local_storage_files = [
        path.relative_to(ROOT)
        for path in source_files
        if "localStorage" in path.read_text(encoding="utf-8")
        and not path.name.endswith((".test.ts", ".test.tsx"))
        and not (
            path == webauthn_warning_file
            and all(item in path.read_text(encoding="utf-8") for item in allowed_warning_storage)
            and path.read_text(encoding="utf-8").count("localStorage") == 2
        )
    ]
    if local_storage_files:
        raise AssertionError(
            "browser source must not persist security or tenant context in localStorage; "
            "only the non-sensitive, per-user WebAuthn warning acknowledgement is allowed: "
            f"{local_storage_files}"
        )
    recovery_file = frontend_source / "features" / "knowledge" / "studio" / "draftRecoveryQueue.ts"
    indexed_db_files = [
        path.relative_to(ROOT)
        for path in source_files
        if (
            "indexedDB" in path.read_text(encoding="utf-8")
            or "IDBFactory" in path.read_text(encoding="utf-8")
        )
        and not path.name.endswith((".test.ts", ".test.tsx"))
        and path != recovery_file
    ]
    if indexed_db_files:
        raise AssertionError(
            "IndexedDB is reserved for the typed Knowledge Studio recovery queue: "
            f"{indexed_db_files}"
        )
    recovery_source = recovery_file.read_text(encoding="utf-8")
    recovery_record = recovery_source.split("export interface DraftRecoveryRecord {", 1)[1].split(
        "}", 1
    )[0]
    forbidden_recovery_fields = {
        "accessToken",
        "refreshToken",
        "authorization",
        "bearer",
        "role",
        "clearance",
        "allowedActions",
        "workspaceId",
        "subjectId",
    }
    leaked_recovery_fields = {
        field for field in forbidden_recovery_fields if field in recovery_record
    }
    if leaked_recovery_fields:
        raise AssertionError(
            "Knowledge Studio recovery records cannot persist identity or authorization context: "
            f"{leaked_recovery_fields}"
        )
    required_recovery_contract = {
        "scopeHash: string",
        "payload: KnowledgeStudioBasicInformation",
        "expectedEtag?: string",
        "idempotencyKey: string",
    }
    missing = {item for item in required_recovery_contract if item not in recovery_record}
    if missing:
        raise AssertionError(f"Knowledge Studio recovery queue contract is incomplete: {missing}")
    auth_provider = (frontend_source / "auth" / "AuthProvider.tsx").read_text(encoding="utf-8")
    if "new InMemoryWebStorage()" not in auth_provider:
        raise AssertionError("OIDC user tokens must use in-memory storage")
    transaction_store = (
        "stateStore: new WebStorageStateStore({\n"
        "      store: window.sessionStorage,\n"
        "      prefix: 'datariver.oidc.transaction.',\n"
        "    })"
    )
    if transaction_store not in auth_provider:
        raise AssertionError(
            "OIDC may use session storage only for the tab-scoped PKCE transaction state"
        )
    if "userStore: new WebStorageStateStore({ store: window.sessionStorage" in auth_provider:
        raise AssertionError("OIDC user tokens must not use sessionStorage")


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
    canonical = (ROOT / "backend" / "alembic" / "versions" / "0001_initial_schema.py").read_text(
        encoding="utf-8"
    )
    combined = generator + role_init + (ROOT / "compose.yaml").read_text(encoding="utf-8")
    if "datariver_worker" in combined or "postgres_worker_password" in combined:
        raise AssertionError("legacy all-powerful worker identity is still configured")
    required_roles = {
        "datariver_app",
        "datariver_relay",
        "datariver_upload",
        "datariver_governance",
        "datariver_export",
        "datariver_retention_scheduler",
        "datariver_archive",
        "datariver_bootstrap",
        "datariver_knowledge",
        "datariver_knowledge_proposal",
        "datariver_knowledge_ingestion",
        "datariver_quality",
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
    required_admin_grants = {
        "GRANT UPDATE (active, clearance, attributes, version, updated_at)\n"
        "            ON iam.workspace_memberships TO datariver_app;",
        "GRANT SELECT, INSERT ON iam.admin_access_requests TO datariver_app;",
        "GRANT UPDATE (state, checker_id, consumed_by, consumed_at,\n"
        "            consume_policy_decision_id, version, updated_at)\n"
        "            ON iam.admin_access_requests TO datariver_app;",
        "GRANT SELECT, INSERT ON iam.admin_access_approvals TO datariver_app;",
    }
    missing_admin_grants = {grant for grant in required_admin_grants if grant not in generator}
    if missing_admin_grants:
        raise AssertionError("administrator workflow grants are not column-bounded")
    if re.search(r"GRANT[^;]*DELETE[^;]*iam\.admin_access_", generator):
        raise AssertionError("administrator workflow evidence cannot be deleted by the app role")
    if re.search(r"GRANT[^;]*UPDATE[^;]*iam\.admin_access_approvals", generator):
        raise AssertionError("administrator approvals must remain append-only")
    required_retention_grants = {
        "GRANT SELECT, INSERT ON retention.policy_versions,\n"
        "            retention.policy_class_rules TO datariver_app;",
        "GRANT SELECT, INSERT ON retention.legal_holds TO datariver_app;",
        "GRANT SELECT, INSERT ON retention.legal_hold_events TO datariver_app;",
        "GRANT SELECT ON retention.execution_jobs TO datariver_app;",
        "GRANT SELECT ON retention.execution_attempts,\n"
        "            retention.execution_events TO datariver_app;",
    }
    missing_retention_grants = {
        grant for grant in required_retention_grants if grant not in generator
    }
    if missing_retention_grants:
        raise AssertionError("retention governance grants are incomplete")
    if re.search(r"GRANT[^;]*DELETE[^;]*retention\.", generator):
        raise AssertionError("the application role cannot delete retention governance evidence")
    if re.search(r"GRANT[^;]*UPDATE[^;]*retention\.legal_hold_events", generator):
        raise AssertionError("Legal Hold history must remain append-only")
    for role in (
        "datariver_retention_scheduler",
        "datariver_archive",
        "datariver_knowledge",
        "datariver_knowledge_proposal",
        "datariver_knowledge_ingestion",
        "datariver_quality",
    ):
        if re.search(rf"ALTER ROLE {role}[^;]*NOBYPASSRLS;", combined) is None:
            raise AssertionError(f"{role} must remain subject to workspace RLS")
    required_ingestion_contract = {
        "datariver_knowledge_ingestion",
        "request_studio_ingestion_v1",
        "claim_studio_ingestion_v1",
        "complete_studio_ingestion_v1",
        "current_studio_ingestion_lease_matches_v1",
    }
    for source_name, source in (
        ("role reconciliation", role_init),
        ("canonical initial migration", canonical),
    ):
        missing_ingestion = required_ingestion_contract - {
            value for value in required_ingestion_contract if value in source
        }
        if missing_ingestion:
            raise AssertionError(
                f"{source_name} is missing the governed Studio ingestion contract: "
                f"{sorted(missing_ingestion)}"
            )
    compose = _yaml(ROOT / "compose.yaml")
    proposal_worker = compose["services"].get("knowledge-tbox-proposal-worker")
    if not isinstance(proposal_worker, dict):
        raise AssertionError("Knowledge Studio Proposal worker service is missing")
    if (
        proposal_worker.get("profiles") != ["knowledge-studio-proposal"]
        or proposal_worker.get("read_only") is not True
        or "no-new-privileges:true" not in proposal_worker.get("security_opt", [])
    ):
        raise AssertionError(
            "Knowledge Studio Proposal worker isolation/profile contract is incomplete"
        )
    expected_proposal_spool = (
        "/var/spool/datariver-knowledge-proposal:"
        "size=16m,noexec,nosuid,mode=0700,uid=10001,gid=10001"
    )
    if proposal_worker.get("tmpfs") != [expected_proposal_spool]:
        raise AssertionError(
            "Knowledge Studio Proposal worker must use its bounded owner-only tmpfs spool"
        )
    if proposal_worker.get("volumes"):
        raise AssertionError(
            "Knowledge Studio Proposal worker must not use a persistent spool volume"
        )
    if "knowledge-proposal-spool" in compose.get("volumes", {}):
        raise AssertionError("Knowledge Studio Proposal spool named volume must remain absent")
    if proposal_worker.get("healthcheck", {}).get("test") != [
        "CMD",
        "/app/.venv/bin/python",
        "-m",
        "datariver.workers.knowledge_tbox_proposal",
        "--healthcheck",
    ]:
        raise AssertionError(
            "Knowledge Studio Proposal worker must expose its dedicated DB/Redis health check"
        )
    ingestion_worker = compose["services"].get("knowledge-studio-ingestion-worker")
    if not isinstance(ingestion_worker, dict):
        raise AssertionError("Knowledge Studio ingestion worker service is missing")
    if (
        ingestion_worker.get("profiles") != ["knowledge-studio-ingestion"]
        or ingestion_worker.get("read_only") is not True
        or "no-new-privileges:true" not in ingestion_worker.get("security_opt", [])
    ):
        raise AssertionError(
            "Knowledge Studio ingestion worker isolation/profile contract is incomplete"
        )
    attachment_migration = (
        ROOT / "backend/alembic/versions/0050_change_request_attachment_upload_intents.py"
    ).read_text(encoding="utf-8")
    if re.search(
        r"GRANT\s+SELECT\s+ON\s+governance"
        r"\.change_request_attachment_upload_intents\s+TO\s+datariver_upload",
        attachment_migration,
    ):
        raise AssertionError(
            "the BYPASSRLS upload role cannot directly read attachment upload intents"
        )
    if "claim_attachment_upload_reconciliation" not in attachment_migration:
        raise AssertionError("attachment reconciliation requires a bounded claim function")
    if "retention.execution_events TO datariver_retention_scheduler;" not in generator:
        raise AssertionError("the retention scheduler cannot append execution evidence")
    if "retention.immutable_archive_receipts TO datariver_archive;" not in generator:
        raise AssertionError("the archive worker cannot read its immutable receipts")
    for required_reconciliation_grant in (
        "platform.workspaces, iam.subjects, iam.workspace_memberships",
        "retention.execution_events TO datariver_retention_scheduler",
        "retention.immutable_archive_receipts TO datariver_archive",
        "to_regclass('retention.execution_jobs') IS NOT NULL",
    ):
        if required_reconciliation_grant not in role_init:
            raise AssertionError(
                "existing-volume retention role reconciliation grants are incomplete"
            )
    for reconciliation_script in (
        ROOT / "scripts" / "reconcile-postgres-roles.sh",
        ROOT / "scripts" / "reconcile-postgres-roles.ps1",
    ):
        if not reconciliation_script.is_file():
            raise AssertionError("cross-platform PostgreSQL role reconciliation is incomplete")
        if 'PGPASSWORD="$(tr -d "\\r\\n" </run/secrets/postgres_password)"' not in (
            reconciliation_script.read_text(encoding="utf-8")
        ):
            raise AssertionError(
                "PostgreSQL role reconciliation must authenticate from the mounted owner secret"
            )
    relay_configuration_grant = (
        "GRANT SELECT ON platform.external_service_profiles,\n"
        "            platform.external_service_profile_versions TO datariver_relay;"
    )
    if relay_configuration_grant not in generator:
        raise AssertionError("relay cannot load its activated Redis delivery revision")
    archive_port = (
        (ROOT / "backend/src/datariver/application/ports.py")
        .read_text(encoding="utf-8")
        .split("class ImmutableArchiveStore", maxsplit=1)[1]
        .split("class UploadRepository", maxsplit=1)[0]
    )
    if re.search(r"(?:async\s+)?def\s+[^\n]*(?:delete|bypass)", archive_port, re.IGNORECASE):
        raise AssertionError("the immutable archive port cannot expose delete or bypass operations")
    retention_domain = (ROOT / "backend/src/datariver/domain/retention.py").read_text(
        encoding="utf-8"
    )
    if 'AUTOMATION_DISABLED = "DISABLED_NOT_READY"' not in retention_domain:
        raise AssertionError("retention automation must remain fail-closed")
    relay_block = generator.split("rolname = 'datariver_relay'", maxsplit=1)[1].split(
        "END IF;", maxsplit=1
    )[0]
    if "DELETE" in relay_block:
        raise AssertionError("the outbox relay role cannot delete retained event evidence")
    relay_worker = (ROOT / "backend/src/datariver/workers/outbox_relay.py").read_text(
        encoding="utf-8"
    )
    relay_store = (ROOT / "backend/src/datariver/infrastructure/db/outbox.py").read_text(
        encoding="utf-8"
    )
    if "prune_completed" in relay_worker + relay_store:
        raise AssertionError("event pruning must remain disabled until governed archival is ready")


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


def verify_phase7_source_integrity() -> None:
    """Keep production surfaces free of fake UI data, debug residue and credential literals."""

    forbidden_residue = re.compile(
        r"\b(?:TODO|FIXME|HACK|XXX)\b"
        r"|console\.(?:log|debug|trace)\s*\("
        r"|\bdebugger\s*;"
        r"|\bbreakpoint\s*\("
    )
    admin_identity_bypass = re.compile(
        r"(?:if|elif)\s+[^\n]*(?:user(?:name)?|subject|role)"
        r"[^\n]*(?:==|in)\s*[\"'](?:admin|administrator)[\"']",
        re.IGNORECASE,
    )
    frontend_mock_identifier = re.compile(
        r"\b(?:const|let|var)\s+[A-Za-z0-9_]*(?:mock|fixture|dummy|fake)"
        r"[A-Za-z0-9_]*\s*[:=]",
        re.IGNORECASE,
    )
    credential_fingerprints = (
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
        re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    )
    for source_root in PRODUCTION_SOURCE_ROOTS:
        for path in source_root.rglob("*"):
            if (
                not path.is_file()
                or path.suffix not in SOURCE_SUFFIXES
                or ".test." in path.name
                or "__pycache__" in path.parts
            ):
                continue
            source = path.read_text(encoding="utf-8")
            if forbidden_residue.search(source):
                raise AssertionError(
                    f"production source contains debug/dead-code residue: {path.relative_to(ROOT)}"
                )
            if path.suffix == ".py" and admin_identity_bypass.search(source):
                raise AssertionError(
                    f"production authorization compares an administrator name: "
                    f"{path.relative_to(ROOT)}"
                )
            if source_root.name == "src" and "frontend" in source_root.parts:
                if frontend_mock_identifier.search(source):
                    raise AssertionError(
                        f"frontend runtime declares mock/fixture data: {path.relative_to(ROOT)}"
                    )
            if any(pattern.search(source) for pattern in credential_fingerprints):
                raise AssertionError(
                    f"production source contains a credential fingerprint: {path.relative_to(ROOT)}"
                )

    example_environment = (ROOT / ".env.example").read_text(encoding="utf-8")
    for line in example_environment.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", maxsplit=1)
        if re.search(r"(?:_PASSWORD|_SECRET|_TOKEN|_API_KEY)\Z", key) and value:
            raise AssertionError(f".env.example must not provide plaintext {key}")

    phase_migrations = tuple(
        next((ROOT / "backend" / "alembic" / "versions").glob(f"{revision}_*.py"))
        for revision in ("0067", "0068", "0069")
    )
    protected_legacy_relation = re.compile(
        r"ALTER\s+TABLE\s+(?:catalog\.assets_projection|integration\."
        r"(?!outbox_events\b)|platform\.external_service_profile)",
        re.IGNORECASE,
    )
    destructive_legacy_ddl = re.compile(
        r"(?:DROP\s+(?:TABLE|CONSTRAINT)|ON\s+DELETE\s+CASCADE|\bCASCADE\b)",
        re.IGNORECASE,
    )
    for migration in phase_migrations:
        upgrade_source = migration.read_text(encoding="utf-8").split("def downgrade()", maxsplit=1)[
            0
        ]
        for match in protected_legacy_relation.finditer(upgrade_source):
            statement = upgrade_source[match.start() : match.start() + 500]
            if destructive_legacy_ddl.search(statement):
                raise AssertionError(
                    f"{migration.name} destructively alters a protected legacy relation"
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


def verify_amd64_source_readiness_contract() -> None:
    workflow_path = ROOT / "scripts" / "development_cycle.py"
    workflow = workflow_path.read_text(encoding="utf-8")
    required_fragments = {
        'choices=("verify", "dev-publish", "prep-update", "prep-check")',
        'DEFAULT_PREPARATION_ENV = Path(".env.wsl-intranet-development")',
        'READINESS_CONTRACT = "DATARIVER_PREPARATION_READINESS_V1"',
        'ROOT / "runtime" / "portability" / "amd64-readiness.json"',
        '("git", "merge-base", "--is-ancestor", previous_commit, current_source_commit)',
        '("git", "merge", "--ff-only", "origin/dev")',
        "verify_remote_dev(runner, newer)",
        '"{{.Server.Os}}/{{.Server.Arch}}"',
        '"proof": "api-ready-required-revision"',
        'safe_output = json.dumps(capabilities, sort_keys=True, separators=(",", ":"))',
        "reveal_failure_output=False",
        "os.replace(temporary, path)",
        "verify_readiness_manifest(evidence)",
    }
    missing = {fragment for fragment in required_fragments if fragment not in workflow}
    if missing:
        raise AssertionError(
            f"the stable amd64 source-readiness workflow has drifted: {sorted(missing)}"
        )
    forbidden_transfer_commands = ("docker save", "docker load", "docker push")
    if any(command in workflow for command in forbidden_transfer_commands):
        raise AssertionError(
            "the daily source workflow must not transfer Docker images or use a registry"
        )
    if 'print(f"     {output}")' in workflow:
        raise AssertionError("raw source-host preflight output must never reach operator logs")
    runtime_launcher = workflow.split("def dev_runtime_update_command(", maxsplit=1)[1].split(
        "def dev_publish(", maxsplit=1
    )[0]
    for fragment in (
        'python_bin = ROOT / ".venv" / "bin" / "python"',
        "not python_bin.is_file() or not os.access(python_bin, os.X_OK)",
        '"The project Python interpreter is absent or not executable."',
        'ROOT / "scripts" / "workflow_update_restart.py"',
        'command.extend(("--reconcile-local-topology", reconciliation))',
    ):
        if fragment not in runtime_launcher:
            raise AssertionError(f"the Mac runtime project-Python launcher is missing: {fragment}")
    if runtime_launcher.index("python_bin,") > runtime_launcher.index(
        'ROOT / "scripts" / "workflow_update_restart.py"'
    ):
        raise AssertionError("the project Python must precede the exact runtime workflow script")
    for forbidden in ("sys.executable", "os.environ", "shell=True"):
        if forbidden in runtime_launcher:
            raise AssertionError("the Mac runtime launcher cannot select an alternate interpreter")
    if workflow.index("runtime = prepare_source_host") > workflow.index(
        "write_readiness_manifest(evidence)"
    ):
        raise AssertionError("readiness evidence must be written only after runtime verification")

    prep_check_source = workflow[workflow.index("def prep_check(") : workflow.index("\ndef main()")]
    for fragment in (
        "capture_source_host_preflight(runner, selected_env)",
        'source_host_arguments("status", selected_env)',
        "verify_source_host_health(runner, read_env_values(selected_env))",
        "verify_readiness_manifest(evidence)",
    ):
        if fragment not in prep_check_source:
            raise AssertionError(f"prep-check lost its read-only readiness gate: {fragment}")
    for fragment in (
        "prepare_source_host(",
        "sync_changed_dependencies(",
        "write_readiness_manifest(",
        '"fetch"',
        '"merge"',
        '"migrate"',
        '"start"',
        '"bootstrap-identity"',
    ):
        if fragment in prep_check_source:
            raise AssertionError(f"prep-check must remain repeatable and read-only: {fragment}")

    test_source = (ROOT / "backend" / "tests" / "unit" / "test_development_cycle.py").read_text(
        encoding="utf-8"
    )
    for fragment in (
        "test_environment_schema_hash_never_depends_on_values",
        "test_preflight_capture_logs_only_allowlisted_capabilities",
        "test_invalid_preflight_capture_never_echoes_raw_content",
        "test_preflight_subprocess_failure_suppresses_captured_raw_output",
        "test_failed_atomic_replace_preserves_last_successful_manifest",
        "test_missing_readiness_manifest_fails_closed",
        "test_prep_check_is_repeatable_and_read_only_after_successful_update",
        "test_dev_runtime_update_command_requires_executable_project_python",
        "test_dev_runtime_update_operator_boundary_imports_with_project_python",
        "test_dev_publish_propagates_runtime_child_interrupt_without_push",
    ):
        if fragment not in test_source:
            raise AssertionError(f"the amd64 readiness direct test is missing: {fragment}")

    for document in (
        ROOT / "docs" / "adr" / "0111-source-built-amd64-portability-layer.md",
        ROOT / "docs" / "57_AMD64_SOURCE_BUILT_PORTABILITY_CONTRACT.md",
    ):
        content = document.read_text(encoding="utf-8")
        if "DATARIVER_PREPARATION_READINESS_V1" not in content:
            raise AssertionError(
                f"{document.relative_to(ROOT)} omits the readiness contract identity"
            )


def verify_governed_docker_build_capacity_contract() -> None:
    capacity_path = ROOT / "scripts" / "docker_capacity.py"
    capacity = capacity_path.read_text(encoding="utf-8")
    required_capacity_fragments = {
        'runtime / "operator-locks"',
        'lock_directory / "update-build.lock"',
        "LOCK_EX | LOCK_NB",
        '"docker",\n            "context",\n            "inspect"',
        '"docker", "version", "--format", "{{.Server.Os}}/{{.Server.Arch}}"',
        '"status=running"',
        '"docker",\n                    "buildx",\n                    "prune"',
        '"--all"',
        '"--reserved-space"',
        '"--max-used-space"',
        '"--min-free-space"',
        "reserve = (filesystem_total + 9) // 10",
        "cache_budget = (filesystem_total + 7) // 8",
        'shared = row.get("Shared")',
        "records: dict[str, tuple[int, bool, bool]]",
        'evidence = (_parse_size(row.get("Size")), reclaimable, shared)',
        "self.logical_bytes != self.private_bytes + self.shared_bytes",
        "self.reclaimable_logical_bytes",
        "!= self.reclaimable_private_bytes + self.reclaimable_shared_bytes",
        "cache_before.reclaimable_private_bytes < required_cache_recovery",
        "free_before + recoverable_while_retaining_floor < required",
        "if cache_before.private_bytes > cache_budget:",
        "if cache_after.private_bytes > cache_budget:",
        "DOCKER_BUILD_CACHE_ACTION_FAILED_POST_MEASUREMENT_OK",
        "DOCKER_BUILD_CACHE_ACTION_FAILED_POST_MEASUREMENT_FAILED",
        "DOCKER_BUILD_CACHE_ACTION_SUCCEEDED_POST_MEASUREMENT_FAILED",
        '"action_attempts=1"',
        '"retry_count=0"',
        'f"cache_probe_ok={',
        'f"filesystem_probe_ok={',
        'f"logical_cache_delta_signed={',
        'f"private_cache_delta_signed={',
        'f"shared_cache_delta_signed={',
        'f"free_delta_signed={',
        '"DOCKER_BUILDER_MUST_HAVE_EXACTLY_ONE_NODE"',
        '"DOCKER_BUILDER_OVERRIDE_NOT_CURRENT"',
        'raise DockerCapacityError("DOCKER_ACTIVE_BUILD_PRESENT")',
        'raise DockerCapacityError("BUILD_CAPACITY_REQUIRES_CLEAN_CHECKOUT")',
        'raise DockerCapacityError("DOCKER_CONTEXT_MUST_BE_LOCAL_UNIX")',
        "selected_image_tags=sum(",
    }
    missing = {fragment for fragment in required_capacity_fragments if fragment not in capacity}
    if missing:
        raise AssertionError(
            f"the governed Docker build-capacity contract has drifted: {sorted(missing)}"
        )
    capacity_syntax = ast.parse(capacity, filename=capacity_path.as_posix())

    active_build_functions = [
        node
        for node in capacity_syntax.body
        if isinstance(node, ast.FunctionDef) and node.name == "docker_builder_is_idle"
    ]
    if len(active_build_functions) != 1:
        raise AssertionError("the shared active-build probe must be defined exactly once")
    active_build_calls = [
        node
        for node in ast.walk(active_build_functions[0])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_safe_output"
        and len(node.args) == 2
        and isinstance(node.args[1], ast.Tuple)
    ]
    if len(active_build_calls) != 1:
        raise AssertionError("the shared active-build probe must issue one bounded history probe")

    def fixed_or_name(node: ast.expr) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return f"${node.id}"
        return None

    active_build_tuple = active_build_calls[0].args[1]
    if not isinstance(active_build_tuple, ast.Tuple):
        raise AssertionError("the shared active-build argv must be a literal tuple")
    active_build_argv = tuple(fixed_or_name(element) for element in active_build_tuple.elts)
    if active_build_argv != (
        "docker",
        "buildx",
        "history",
        "ls",
        "--builder",
        "$builder",
        "--filter",
        "status=running",
        "--format",
        "{{.Status}}",
    ):
        raise AssertionError("the exact selected-builder history argv has drifted")
    require_idle_functions = [
        node
        for node in capacity_syntax.body
        if isinstance(node, ast.FunctionDef) and node.name == "require_no_active_builds"
    ]
    if len(require_idle_functions) != 1:
        raise AssertionError("the canonical active-build guard must remain unique")
    shared_idle_calls = [
        node
        for node in ast.walk(require_idle_functions[0])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "docker_builder_is_idle"
    ]
    if len(shared_idle_calls) != 1:
        raise AssertionError("the canonical guard must reuse the shared active-build probe")

    def capacity_enum_members(class_name: str) -> tuple[tuple[str, object], ...]:
        matches = [
            node
            for node in capacity_syntax.body
            if isinstance(node, ast.ClassDef) and node.name == class_name
        ]
        if len(matches) != 1:
            raise AssertionError("the capacity diagnostic enum must be defined exactly once")
        return tuple(
            (statement.targets[0].id, ast.literal_eval(statement.value))
            for statement in matches[0].body
            if isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        )

    if capacity_enum_members("DockerCapacityMode") != (
        ("ACTION_ENABLED", "ACTION_ENABLED"),
        ("MEASURE_ONLY", "MEASURE_ONLY"),
    ):
        raise AssertionError("the default-preserving capacity mode has drifted")
    expected_builder_selection_predicates = tuple(
        (value, value)
        for value in (
            "EXTERNAL_BUILDKIT_HOST",
            "LIST_JSON",
            "ROW_SCHEMA",
            "NODE_COUNT",
            "NODE_SCHEMA",
            "DUPLICATE_CONFLICT",
            "CURRENT_MISSING",
            "CURRENT_AMBIGUOUS",
            "OVERRIDE_INVALID",
            "OVERRIDE_NOT_CURRENT",
            "DRIVER_NOT_DOCKER",
            "NODE_NOT_RUNNING",
            "BUILDER_CONTEXT_MISMATCH",
            "NODE_NAME_MISMATCH",
            "ENDPOINT_CONTEXT_MISMATCH",
            "PASS",
            "UNKNOWN",
        )
    )
    if capacity_enum_members("BuilderSelectionPredicate") != expected_builder_selection_predicates:
        raise AssertionError("the builder-selection predicate vocabulary has drifted")
    builder_selection_recorder = capacity.split("class BuilderSelectionRecorder:", maxsplit=1)[
        1
    ].split("class NodeSchemaPredicate", maxsplit=1)[0]
    for fragment in (
        "predicate: BuilderSelectionPredicate = BuilderSelectionPredicate.UNKNOWN",
        "return self.predicate is not BuilderSelectionPredicate.UNKNOWN",
        "not isinstance(predicate, BuilderSelectionPredicate)",
        "predicate is BuilderSelectionPredicate.UNKNOWN",
        "or self.known",
        'raise DockerCapacityError("BUILDER_SELECTION_EVIDENCE_INVALID")',
        "self.predicate = predicate",
    ):
        if fragment not in builder_selection_recorder:
            raise AssertionError(f"the builder-selection recorder is missing: {fragment}")
    expected_node_schema_predicates = tuple(
        (value, value)
        for value in (
            "NODE_NOT_MAPPING",
            "NAME_MISSING",
            "NAME_NULL",
            "NAME_NOT_STRING",
            "ENDPOINT_MISSING",
            "ENDPOINT_NULL",
            "ENDPOINT_NOT_STRING",
            "STATUS_NULL",
            "STATUS_NOT_STRING",
            "PASS",
            "UNKNOWN",
        )
    )
    if capacity_enum_members("NodeSchemaPredicate") != expected_node_schema_predicates:
        raise AssertionError("the node-schema predicate vocabulary has drifted")
    node_schema_recorder = capacity.split("class NodeSchemaRecorder:", maxsplit=1)[1].split(
        "class BuildCapacityPreflightPredicate",
        maxsplit=1,
    )[0]
    for fragment in (
        "predicate: NodeSchemaPredicate = NodeSchemaPredicate.UNKNOWN",
        "return self.predicate is not NodeSchemaPredicate.UNKNOWN",
        "not isinstance(predicate, NodeSchemaPredicate)",
        "predicate is NodeSchemaPredicate.UNKNOWN",
        "or self.known",
        'raise DockerCapacityError("NODE_SCHEMA_EVIDENCE_INVALID")',
        "self.predicate = predicate",
    ):
        if fragment not in node_schema_recorder:
            raise AssertionError(f"the node-schema recorder is missing: {fragment}")
    expected_capacity_predicates = tuple(
        (value, value)
        for value in (
            "HOST_ENVIRONMENT_PREFLIGHT",
            "SOURCE_PROVENANCE",
            "COMPOSE_ARGUMENTS",
            "LOCK_CONTRACT",
            "CLEAN_CHECKOUT",
            "DOCKERIGNORE_CONTRACT",
            "COMPOSE_CONFIG",
            "BUILD_TARGET_CONTRACT",
            "TRACKED_CONTEXT",
            "DOCKER_CONTEXT",
            "BUILDER_LIST_PROBE",
            "BUILDER_SELECTION",
            "DOCKER_PLATFORM",
            "IMAGE_EVIDENCE",
            "CACHE_EVIDENCE",
            "FILESYSTEM_EVIDENCE",
            "CAPACITY_POLICY",
            "CAPACITY_CACHE_POLICY_SUPPORT",
            "CAPACITY_CACHE_ACTIVE_BUILD",
            "CACHE_ACTION_REQUIRED",
            "INITIAL_BUILDER_IDLE_PROBE",
            "INITIAL_BUILDER_ACTIVE",
            "PASS",
            "UNKNOWN",
        )
    )
    if capacity_enum_members("BuildCapacityPreflightPredicate") != expected_capacity_predicates:
        raise AssertionError("the build-capacity predicate vocabulary has drifted")
    selected_builder_functions = [
        node
        for node in capacity_syntax.body
        if isinstance(node, ast.FunctionDef) and node.name == "_selected_builder"
    ]
    if len(selected_builder_functions) != 1:
        raise AssertionError("the canonical builder selector must remain unique")
    inventory_parser_functions = [
        node
        for node in capacity_syntax.body
        if isinstance(node, ast.FunctionDef) and node.name == "parse_docker_builder_inventory"
    ]
    if len(inventory_parser_functions) != 1:
        raise AssertionError("the shared immutable builder inventory parser must remain unique")
    builder_failure_pairs: list[tuple[str, object]] = []

    class BuilderFailureOrderVisitor(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> None:
            if (
                isinstance(node.func, ast.Name)
                and node.func.id == "_builder_selection_failure"
                and len(node.args) >= 3
                and isinstance(node.args[1], ast.Attribute)
                and isinstance(node.args[1].value, ast.Name)
                and node.args[1].value.id == "BuilderSelectionPredicate"
            ):
                builder_failure_pairs.append((node.args[1].attr, ast.literal_eval(node.args[2])))
            self.generic_visit(node)

    BuilderFailureOrderVisitor().visit(inventory_parser_functions[0])
    BuilderFailureOrderVisitor().visit(selected_builder_functions[0])
    expected_builder_failure_pairs = (
        ("EXTERNAL_BUILDKIT_HOST", "EXTERNAL_BUILDKIT_HOST_UNSUPPORTED"),
        ("LIST_JSON", "Docker builder evidence is invalid."),
        ("ROW_SCHEMA", "Docker builder evidence is invalid."),
        ("ROW_SCHEMA", "Docker builder evidence is invalid."),
        ("NODE_COUNT", "DOCKER_BUILDER_MUST_HAVE_EXACTLY_ONE_NODE"),
        ("DUPLICATE_CONFLICT", "Docker builder duplicate evidence conflicts."),
        ("CURRENT_MISSING", "DOCKER_BUILDER_AMBIGUOUS"),
        ("CURRENT_AMBIGUOUS", "DOCKER_BUILDER_AMBIGUOUS"),
        ("OVERRIDE_INVALID", "DOCKER_BUILDER_OVERRIDE_INVALID"),
        ("OVERRIDE_NOT_CURRENT", "DOCKER_BUILDER_OVERRIDE_NOT_CURRENT"),
        ("CURRENT_MISSING", "DOCKER_BUILDER_NOT_CURRENT"),
        ("DRIVER_NOT_DOCKER", "DOCKER_BUILDER_NOT_LOCAL_RUNNING_DOCKER_DRIVER"),
        ("NODE_NOT_RUNNING", "DOCKER_BUILDER_NOT_LOCAL_RUNNING_DOCKER_DRIVER"),
        ("BUILDER_CONTEXT_MISMATCH", "DOCKER_BUILDER_NOT_LOCAL_RUNNING_DOCKER_DRIVER"),
        ("NODE_NAME_MISMATCH", "DOCKER_BUILDER_NOT_LOCAL_RUNNING_DOCKER_DRIVER"),
        ("ENDPOINT_CONTEXT_MISMATCH", "DOCKER_BUILDER_NOT_LOCAL_RUNNING_DOCKER_DRIVER"),
    )
    if tuple(builder_failure_pairs) != expected_builder_failure_pairs:
        raise AssertionError("the exact builder-selection branches or legacy errors have drifted")
    selected_builder_source = ast.get_source_segment(capacity, selected_builder_functions[0])
    if selected_builder_source is None or not (
        "builder_selection_recorder: BuilderSelectionRecorder | None = None"
        in selected_builder_source
        and "builder_selection_recorder.record(BuilderSelectionPredicate.PASS)"
        in selected_builder_source
        and "parse_docker_builder_inventory(" in selected_builder_source
        and "str(error)" not in selected_builder_source
    ):
        raise AssertionError("builder selection is not structurally recorded without text parsing")
    inventory_parser_source = ast.get_source_segment(capacity, inventory_parser_functions[0])
    if inventory_parser_source is None:
        raise AssertionError("the immutable builder inventory parser source is unavailable")
    node_schema_failure = capacity.split("def _node_schema_failure(", maxsplit=1)[1].split(
        "def _selected_builder(",
        maxsplit=1,
    )[0]
    for fragment in (
        "node_schema_recorder.record(predicate)",
        "BuilderSelectionPredicate.NODE_SCHEMA",
        '"Docker builder node evidence is invalid."',
    ):
        if fragment not in node_schema_failure:
            raise AssertionError(f"the node-schema failure boundary is missing: {fragment}")
    node_schema_failures = tuple(
        node.args[2].attr
        for node in ast.walk(inventory_parser_functions[0])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_node_schema_failure"
        and len(node.args) == 3
        and isinstance(node.args[2], ast.Attribute)
        and isinstance(node.args[2].value, ast.Name)
        and node.args[2].value.id == "NodeSchemaPredicate"
    )
    if node_schema_failures != (
        "NODE_NOT_MAPPING",
        "NAME_MISSING",
        "NAME_NULL",
        "NAME_NOT_STRING",
        "ENDPOINT_MISSING",
        "ENDPOINT_NULL",
        "ENDPOINT_NOT_STRING",
        "STATUS_NULL",
        "STATUS_NOT_STRING",
    ):
        raise AssertionError("the exact node-schema branch order has drifted")
    status_assignments = [
        node
        for node in ast.walk(inventory_parser_functions[0])
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "status"
    ]
    if len(status_assignments) != 1 or ast.dump(
        status_assignments[0].value, include_attributes=False
    ) != ast.dump(
        ast.Call(
            func=ast.Attribute(
                value=ast.Name(id="node", ctx=ast.Load()),
                attr="get",
                ctx=ast.Load(),
            ),
            args=[ast.Constant(value="Status"), ast.Constant(value="")],
            keywords=[],
        ),
        include_attributes=False,
    ):
        raise AssertionError("missing Buildx node status must remain unavailable, not malformed")
    builder_name_fullmatch_calls = sorted(
        (
            call
            for function in (inventory_parser_functions[0], selected_builder_functions[0])
            for call in ast.walk(function)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "fullmatch"
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "_BUILDER_NAME"
            and len(call.args) == 1
            and isinstance(call.args[0], ast.Name)
        ),
        key=lambda call: (call.lineno, call.col_offset),
    )
    builder_name_fullmatch_targets = tuple(
        call.args[0].id
        for call in builder_name_fullmatch_calls
        if isinstance(call.args[0], ast.Name)
    )
    if builder_name_fullmatch_targets != ("name", "override"):
        raise AssertionError(
            "Buildx node and endpoint strings must not use the builder-name grammar"
        )
    provider_shape_order = tuple(
        inventory_parser_source.index(fragment)
        for fragment in (
            'if "Name" not in node:',
            "if node_name is None:",
            "if not isinstance(node_name, str):",
            'if "Endpoint" not in node:',
            "if endpoint is None:",
            "if not isinstance(endpoint, str):",
            'status = node.get("Status", "")',
            "if status is None:",
            "if not isinstance(status, str):",
            "node_schema_recorder.record(NodeSchemaPredicate.PASS)",
            "for name, evidence in parsed_builders:",
        )
    )
    if provider_shape_order != tuple(sorted(provider_shape_order)):
        raise AssertionError("Buildx node structural validation order has drifted")
    semantic_order = tuple(
        selected_builder_source.index(fragment)
        for fragment in (
            'if driver != "docker":',
            'if status != "running":',
            "if selected != current_context:",
            "if node_name != selected:",
            "if endpoint != current_context:",
        )
    )
    if semantic_order != tuple(sorted(semantic_order)):
        raise AssertionError("Buildx node semantic validation order has drifted")
    for forbidden in ("endpoint.strip", "status.strip", "urlparse"):
        if forbidden in inventory_parser_source or forbidden in selected_builder_source:
            raise AssertionError(f"Buildx node evidence cannot be normalized: {forbidden}")
    governed_capacity = capacity.split("def governed_compose_build_capacity(", maxsplit=1)[1]
    capacity_phase_order = tuple(
        governed_capacity.index(fragment)
        for fragment in (
            "BuildCapacityPreflightPredicate.LOCK_CONTRACT",
            "BuildCapacityPreflightPredicate.DOCKERIGNORE_CONTRACT",
            "BuildCapacityPreflightPredicate.COMPOSE_CONFIG",
            "BuildCapacityPreflightPredicate.BUILD_TARGET_CONTRACT",
            "phase_recorder=phase_recorder",
            "BuildCapacityPreflightPredicate.DOCKER_CONTEXT",
            "BuildCapacityPreflightPredicate.BUILDER_LIST_PROBE",
            "BuildCapacityPreflightPredicate.BUILDER_SELECTION",
            "BuildCapacityPreflightPredicate.DOCKER_PLATFORM",
            "BuildCapacityPreflightPredicate.IMAGE_EVIDENCE",
            "BuildCapacityPreflightPredicate.CACHE_EVIDENCE",
            "BuildCapacityPreflightPredicate.FILESYSTEM_EVIDENCE",
            "BuildCapacityPreflightPredicate.CAPACITY_POLICY",
        )
    )
    if capacity_phase_order != tuple(sorted(capacity_phase_order)):
        raise AssertionError("the canonical capacity phase order has drifted")
    measure_only = governed_capacity.split(
        "if mode is DockerCapacityMode.MEASURE_ONLY:", maxsplit=1
    )[1]
    if not (
        measure_only.index("BuildCapacityPreflightPredicate.CACHE_ACTION_REQUIRED")
        < measure_only.index("raise DockerCapacityMeasureOnlyStop()")
        < measure_only.index("action_succeeded = True")
        < measure_only.index('"prune",')
    ):
        raise AssertionError("measure-only capacity must stop before the prune argv")
    for fragment in (
        "mode: DockerCapacityMode = DockerCapacityMode.ACTION_ENABLED",
        "phase_recorder: DockerCapacityPhaseRecorder | None = None",
        "builder_selection_recorder: BuilderSelectionRecorder | None = None",
        "node_schema_recorder: NodeSchemaRecorder | None = None",
        "builder_selection_recorder=builder_selection_recorder",
        "node_schema_recorder=node_schema_recorder",
        "except DockerCapacityPhaseError:",
        "raise DockerCapacityPhaseError(str(error), predicate) from None",
    ):
        if fragment not in capacity:
            raise AssertionError(f"structured capacity phase evidence is missing: {fragment}")
    if "_BUILDER_NAME.fullmatch(node_name)" in inventory_parser_source:
        raise AssertionError("Buildx node names must reach the exact selected-name equality check")
    private_policy = capacity.split('cache_action = "none"', maxsplit=1)[1].split(
        "help_output = _safe_output", maxsplit=1
    )[0]
    for fragment in (
        "cache_before.private_bytes > cache_budget",
        "cache_before.private_bytes - cache_budget",
        "cache_before.reclaimable_private_bytes < required_cache_recovery",
        "cache_before.reclaimable_private_bytes",
        "cache_before.private_bytes - cache_reserved",
    ):
        if fragment not in private_policy:
            raise AssertionError(f"private BuildKit budget policy has drifted: {fragment}")
    if ".logical_bytes" in private_policy or ".shared_bytes" in private_policy:
        raise AssertionError("shared or logical BuildKit bytes cannot authorize cache deletion")
    for forbidden in (
        "docker system prune",
        "docker image prune",
        "docker container prune",
        "docker volume prune",
        "docker builder prune",
    ):
        if forbidden in capacity:
            raise AssertionError(f"the capacity gate contains a forbidden cleanup: {forbidden}")

    selection_plan = capacity.split("class DockerBuilderSelectionPlan:", maxsplit=1)[1].split(
        "class BuildCapacityPreflightPredicate",
        maxsplit=1,
    )[0]
    for fragment in (
        'return ("docker", "buildx", "use", self.target_builder)',
        'return ("docker", "buildx", "use", self.prior_builder)',
    ):
        if fragment not in selection_plan:
            raise AssertionError(f"the fixed builder-selection argv has drifted: {fragment}")
    for forbidden in ("--default", "--global", "create", "remove", "stop", "bootstrap"):
        if forbidden in selection_plan:
            raise AssertionError(f"the builder-selection plan widened its authority: {forbidden}")
    for fragment in (
        "class DockerBuilderIdentity:",
        "class DockerBuilderInventory:",
        "class DockerBuilderSelectionPlan:",
        "def parse_docker_builder_inventory(",
        "def require_docker_builder_selection_plan(",
        "def require_docker_builder_selection_poststate(",
        "def docker_builder_selection_residual_count(",
        'prior.driver != "docker-container"',
        'builder.driver == "docker"',
        "builder.name == current_context",
        "builder.node_name == current_context",
        "builder.endpoint == current_context",
        'environ.get("BUILDKIT_HOST", "").strip()',
        '"BUILDX_BUILDER", ""',
        "inventory.row_count != len(inventory.builders)",
        "inventory.stable_identity != plan.inventory.stable_identity",
    ):
        if fragment not in capacity:
            raise AssertionError(f"the immutable builder-selection contract is missing: {fragment}")

    selection_operator_path = ROOT / "scripts" / "reconcile_docker_builder_selection.py"
    if not selection_operator_path.is_file() or not selection_operator_path.stat().st_mode & 0o111:
        raise AssertionError("the fixed builder-selection operator must be executable")
    selection_operator = selection_operator_path.read_text(encoding="utf-8")
    selection_operator_syntax = ast.parse(
        selection_operator,
        filename=selection_operator_path.as_posix(),
    )

    def operator_enum_members(class_name: str) -> tuple[tuple[str, object], ...]:
        matches = [
            node
            for node in selection_operator_syntax.body
            if isinstance(node, ast.ClassDef) and node.name == class_name
        ]
        if len(matches) != 1:
            raise AssertionError("the builder-selection operator enum must remain unique")
        return tuple(
            (statement.targets[0].id, ast.literal_eval(statement.value))
            for statement in matches[0].body
            if isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        )

    expected_reconcile_predicates = tuple(
        (value, value)
        for value in (
            "ARGUMENTS",
            "PLATFORM",
            "SOURCE",
            "HOST_ENVIRONMENT",
            "ENVIRONMENT_OVERRIDE",
            "DOCKER_CONTEXT",
            "BUILDER_INVENTORY",
            "PRESTATE",
            "ACTIVE_BUILDS",
            "ACTION",
            "POSTSTATE",
            "ROLLBACK",
            "PASS",
            "UNKNOWN",
        )
    )
    if operator_enum_members("BuilderSelectionReconcilePredicate") != expected_reconcile_predicates:
        raise AssertionError("the builder-selection operator predicate vocabulary has drifted")
    for fragment in (
        "with exclusive_docker_workflow_lock(root) as lock:",
        'platform.system() != "Darwin"',
        'platform.machine().lower() not in {"arm64", "aarch64"}',
        '("git", "status", "--porcelain", "--untracked-files=normal")',
        '("git", "rev-parse", "--verify", "HEAD")',
        '("git", "branch", "--show-current")',
        'branch != "dev"',
        "state.applied_commit != state.runtime_commit",
        "fingerprints != state.environment_key_hashes",
        'environ.get("BUILDKIT_HOST", "").strip()',
        '"BUILDX_BUILDER", ""',
        "require_local_unix_docker_context(executor, environ)",
        "require_docker_builder_selection_plan(",
        "docker_builder_is_idle(",
        "runtime.action_attempted = True",
        "runtime.rollback_attempted = True",
        "prestate.plan.selection_argv",
        "prestate.plan.rollback_argv",
        "_capture_poststate(",
        "selection_mutation_count=runtime.mutation_count",
        "cache_action_count: int = 0",
        "build_count: int = 0",
        "container_action_count: int = 0",
        "retry_count: int = 0",
        "stderr=subprocess.STDOUT",
        "_MAXIMUM_PROCESS_OUTPUT_BYTES - len(output) + 1",
        "class _ProcessUnreaped(BaseException):",
        "process.terminate()",
        "process.kill()",
        "raise _ProcessUnreaped() from None",
        "def _reprove_prestate(",
        "exact_residual_count if exact_residual_count <= 128 else None",
        "rollback_interrupted = not isinstance(error, Exception)",
        "len(sys.argv) != 1",
    ):
        if fragment not in selection_operator:
            raise AssertionError(f"the governed builder-selection operator is missing: {fragment}")
    process_finalizer = selection_operator.split("def _finalize_bounded_process(", maxsplit=1)[
        1
    ].split("class _BoundedProcessExecutor:", maxsplit=1)[0]
    selector_close = process_finalizer.index("selector.close()")
    terminate = process_finalizer.index("process.terminate()")
    first_wait = process_finalizer.index("process.wait(timeout=_PROCESS_REAP_SECONDS)")
    kill = process_finalizer.index("process.kill()")
    second_wait = process_finalizer.rindex("process.wait(timeout=_PROCESS_REAP_SECONDS)")
    final_poll = process_finalizer.rindex("child_reaped = process.poll() is not None")
    stdout_close = process_finalizer.index("process_output.close()", final_poll)
    unreaped_guard = process_finalizer.rindex("if not child_reaped:")
    unreaped_raise = process_finalizer.index("raise _ProcessUnreaped() from None", unreaped_guard)
    close_failure_guard = process_finalizer.index("if cleanup_failed:", unreaped_raise)
    if not (
        selector_close
        < terminate
        < first_wait
        < kill
        < second_wait
        < final_poll
        < stdout_close
        < unreaped_guard
        < unreaped_raise
        < close_failure_guard
    ):
        raise AssertionError("the bounded builder-selection process reap contract has drifted")
    if process_finalizer.count("except BaseException:") != 9:
        raise AssertionError("every bounded process cleanup step must absorb BaseException")
    reproof = selection_operator.split("def _reprove_prestate(", maxsplit=1)[1].split(
        "def _capture_poststate(", maxsplit=1
    )[0]
    reproof_order = (
        "_source_identity(executor)",
        "_host_identity(root)",
        "docker_environment_identity = tuple(",
        "require_local_unix_docker_context(executor, environ)",
        "raw = _builder_listing(executor)",
        "plan = require_docker_builder_selection_plan(",
        "_require_idle(prestate.plan.prior_builder",
        "_require_idle(prestate.plan.target_builder",
    )
    reproof_positions = tuple(reproof.index(fragment) for fragment in reproof_order)
    if reproof_positions != tuple(sorted(reproof_positions)):
        raise AssertionError("the final builder-selection authority reproof order has drifted")
    action_marker = selection_operator.index("runtime.action_attempted = True")
    final_reproof = selection_operator.index("_reprove_prestate(", action_marker - 500)
    action_call = selection_operator.index("prestate.plan.selection_argv", action_marker)
    post_proof = selection_operator.index("post = _capture_poststate(", action_call)
    rollback_marker = selection_operator.index("runtime.rollback_attempted = True", post_proof)
    rollback_call = selection_operator.index("prestate.plan.rollback_argv", rollback_marker)
    rollback_proof = selection_operator.index("rollback_post = _capture_poststate(", rollback_call)
    if (
        not final_reproof
        < action_marker
        < action_call
        < post_proof
        < rollback_marker
        < rollback_call
        < rollback_proof
    ):
        raise AssertionError("the builder-selection attempt/proof/rollback order has drifted")
    operator_main = selection_operator.split("def main() -> int:", maxsplit=1)[1]
    if not operator_main.index("if len(sys.argv) != 1:") < operator_main.index(
        "evidence = _run_operator(runtime)"
    ):
        raise AssertionError("extra builder-selection arguments must stop before the lock")
    expected_output_keys = {
        "classification",
        "predicate",
        "action_attempted",
        "action_succeeded",
        "mutation_outcome_known",
        "poststate_known",
        "poststate_valid",
        "rollback_attempted",
        "rollback_succeeded",
        "rollback_outcome_known",
        "rollback_count",
        "selection_mutation_count",
        "residual_known",
        "residual_count",
        "cache_action_count",
        "build_count",
        "container_action_count",
        "retry_count",
    }
    format_functions = [
        node
        for node in selection_operator_syntax.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "format_builder_selection_reconcile_evidence"
    ]
    if len(format_functions) != 1:
        raise AssertionError("the builder-selection formatter must remain unique")
    output_keys = {
        key.value
        for node in ast.walk(format_functions[0])
        if isinstance(node, ast.Dict)
        for key in node.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    output_keys.update(
        node.slice.value
        for node in ast.walk(format_functions[0])
        if isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == "fields"
        and isinstance(node.ctx, ast.Store)
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
    )
    if output_keys != expected_output_keys:
        raise AssertionError("the builder-selection value-free output keys have drifted")
    for forbidden in (
        '"create"',
        '"remove"',
        '"stop"',
        '"bootstrap"',
        '"prune"',
        '"volume"',
        '"context", "use"',
        '"--default"',
        '"--global"',
        "write_applied_state",
        "development_cycle",
        "workflow_update_restart",
    ):
        if forbidden in selection_operator:
            raise AssertionError(
                f"the one-time builder-selection operator is too broad: {forbidden}"
            )

    selection_test = (
        ROOT / "backend" / "tests" / "unit" / "test_docker_builder_selection_reconcile.py"
    ).read_text(encoding="utf-8")
    for test_name in (
        "test_success_runs_one_exact_selection_and_proves_both_builders_idle",
        "test_response_loss_with_proven_target_is_accepted_without_retry",
        "test_interrupt_after_action_preserves_proven_mutation_but_requires_review",
        "test_failed_action_with_exact_prior_state_is_known_and_never_retried",
        "test_target_active_poststate_rolls_back_once_only_after_prior_idle_proof",
        "test_rollback_response_loss_is_accepted_only_after_exact_prior_reproof",
        "test_ambiguous_rollback_stops_without_a_third_selection_mutation",
        "test_inventory_drift_never_rolls_back_or_estimates_residual_state",
        "test_post_proof_baseexception_preserves_action_and_never_rolls_back",
        "test_prestate_active_builder_stops_before_selection_action",
        "test_lock_exit_failure_preserves_completed_action_and_post_proof",
        "test_builder_environment_override_stops_before_context_or_action",
        "test_extra_arguments_are_rejected_before_lock_without_raw_output",
        "test_bounded_process_output_overflow_terminates_and_reaps_without_raw_output",
        "test_bounded_process_timeout_kills_terminate_ignoring_child",
        "test_bounded_process_unreaped_failure_is_distinct_and_never_swallowed",
        "test_cleanup_defects_never_mask_an_unreaped_process",
        "test_reaped_process_close_only_defect_is_fixed_failure_not_unreaped",
        "test_bounded_process_spawn_nonzero_and_invalid_utf8_never_emit_raw",
        "test_unreaped_action_stops_without_post_proof_or_rollback",
        "test_unreaped_read_only_prestate_process_is_review_required_action_zero",
        "test_unreaped_rollback_stops_without_post_proof_or_third_action",
        "test_residual_evidence_is_exact_at_bound_and_unknown_above_it",
        "test_residual_over_bound_survives_lock_exit_fallback",
        "test_main_fallback_formats_normalized_overbound_residual_without_traceback",
        "test_final_prestate_reproof_rejects_every_drift_before_selection",
        "test_final_prestate_reproof_interrupt_is_unknown_and_action_zero",
        "test_final_reproof_and_active_checks_are_immediately_before_action",
        "test_rollback_interrupt_preserves_observed_state_but_requires_review",
    ):
        if test_name not in selection_test:
            raise AssertionError(f"the builder-selection operator test is missing: {test_name}")
    development_cycle = (ROOT / "scripts" / "development_cycle.py").read_text(encoding="utf-8")
    update_workflow = (ROOT / "scripts" / "workflow_update_restart.py").read_text(encoding="utf-8")
    if "reconcile_docker_builder_selection" in development_cycle or (
        "reconcile_docker_builder_selection" in update_workflow
    ):
        raise AssertionError("builder selection must not become part of normal dev-publish")

    workflow = (ROOT / "scripts" / "workflow_update_restart.py").read_text(encoding="utf-8")
    main_source = workflow.split("def main() -> int:", maxsplit=1)[1]
    lock_start = main_source.index("capacity_lock = mutation_stack.enter_context")
    preflight = main_source.index("selected_builder = _preflight_build_capacity")
    reranker = main_source.index("_reconcile_local_reranker")
    if not lock_start < preflight < reranker:
        raise AssertionError("capacity lock/preflight must precede local reranker mutation")
    if main_source.count("_require_idle_builder(selected_builder, capacity_lock)") != 5:
        raise AssertionError("every update-workflow Compose build must recheck active builds")
    parity_note = main_source.index(
        'runner.note("Gateway parity의 고정 local-bootstrap 모듈을 현재 source로 빌드합니다.")'
    )
    parity_idle = main_source.rfind(
        "_require_idle_builder(selected_builder, capacity_lock)",
        preflight,
        parity_note,
    )
    parity_build = main_source.index('trailing=("build", "local-bootstrap")', parity_note)
    if not preflight < parity_idle < parity_note < parity_build < reranker:
        raise AssertionError(
            "gateway parity local-bootstrap build must recheck the selected builder under lock"
        )
    for fragment in (
        "selected_build_services=tuple(selected_build_services)",
        'trailing=("build", *core_build_services)',
    ):
        if fragment not in main_source:
            raise AssertionError("capacity selection must not widen an individual Compose build")
    if 'trailing=("build", *selected_build_services)' in main_source:
        raise AssertionError("aggregate capacity selection cannot become a Compose build target")
    datahub_update = main_source.split(
        "if plan.restart_datahub and state.local_datahub:", maxsplit=1
    )[1].split("if plan.restart_graph", maxsplit=1)[0]
    if '"start-offline"' not in datahub_update or '"start"' in datahub_update:
        raise AssertionError("daily DataHub update must not pull unbudgeted image bytes")
    if "finally:\n        mutation_stack.close()" not in main_source:
        raise AssertionError("the Docker workflow lock must release on every exit")

    platform_workflow = (ROOT / "scripts" / "platform_workflow.py").read_text(encoding="utf-8")
    if '"scripts/docker_capacity.py"' not in platform_workflow:
        raise AssertionError("the capacity controller must remain an operator-only source path")

    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for rule in (
        ".git",
        ".env",
        ".env.*",
        "secrets",
        "runtime",
        "docker_imgs",
        ".venv",
        ".venv-wsl",
        "frontend/node_modules",
        "frontend/dist",
    ):
        if rule not in dockerignore:
            raise AssertionError(f"the Docker build-capacity exclusion is missing: {rule}")

    test_source = (ROOT / "backend" / "tests" / "unit" / "test_docker_capacity.py").read_text(
        encoding="utf-8"
    )
    workflow_test_source = (
        ROOT / "backend" / "tests" / "unit" / "test_platform_workflow.py"
    ).read_text(encoding="utf-8")
    for test_name in (
        "test_cache_over_budget_runs_one_bounded_action_and_remeasures",
        "test_active_build_blocks_cache_action_without_mutation",
        "test_lock_is_nonblocking_and_released_after_failure",
        "test_build_args_and_probe_failure_payload_never_escape",
        "test_remote_docker_context_is_rejected_before_cache_or_filesystem_probe",
        "test_historical_images_for_one_fingerprint_use_conservative_maximum",
        "test_missing_invalid_or_wrong_platform_image_evidence_fails_closed",
        "test_failed_cache_action_and_failed_post_probe_report_composite_failure",
        "test_successful_cache_action_and_failed_post_probe_fail_closed",
        "test_cache_action_requires_enough_reclaimable_bytes_to_restore_budget",
        "test_cache_action_preserves_floor_when_proving_required_free_space",
        "test_non_current_builder_override_is_rejected",
        "test_multi_node_current_builder_is_rejected",
        "test_current_builder_must_match_current_local_context",
        "test_post_action_policy_failures_preserve_full_numeric_evidence",
        "test_shared_heavy_logical_cache_below_private_budget_skips_action",
        "test_private_over_budget_action_ignores_shared_logical_post_total",
        "test_shared_cache_cannot_satisfy_private_recovery_requirement",
        "test_cache_shared_evidence_must_be_boolean",
        "test_duplicate_cache_shared_conflict_fails_closed",
        "test_identical_cache_duplicates_collapse_into_exact_partitions",
        "test_inconsistent_cache_partition_evidence_fails_closed",
        "test_build_capacity_preflight_predicates_are_closed_and_ordered",
        "test_measure_only_over_budget_reports_action_required_without_prune",
        "test_measure_only_under_budget_preserves_normal_no_action_evidence",
        "test_structural_phases_cover_local_contract_and_policy_failures",
        "test_measure_only_cache_policy_and_active_build_fail_before_action",
        "test_initial_builder_idle_uses_distinct_structured_predicates",
        "test_capacity_interrupts_are_not_falsely_classified_as_provider_failures",
        "test_builder_selection_recorder_classifies_every_existing_failure_branch",
        "test_builder_selection_recorder_records_pass_once_and_never_serializes_unknown",
        "test_governed_capacity_threads_exact_builder_selection_outcome",
        "test_builder_selection_interrupt_never_invents_a_known_outcome",
        "test_builder_selection_reports_the_first_simultaneous_final_defect",
        "test_provider_valid_node_shapes_reach_semantic_checks_before_later_probes",
        "test_node_schema_recorder_classifies_each_structural_failure",
        "test_structural_node_name_strings_reach_exact_name_mismatch",
        "test_complete_node_scan_records_pass_before_duplicate_selection_failure",
        "test_incomplete_multirow_node_scan_precedes_duplicate_conflict",
        "test_official_node_shape_records_schema_pass_and_selection_pass",
        "test_node_schema_interrupt_before_structural_outcome_remains_unknown",
        "test_selection_plan_preserves_complete_private_inventory_and_fixed_argv",
        "test_selection_plan_rejects_every_unreviewed_prestate",
        "test_selection_poststate_accepts_only_current_flag_delta",
        "test_builder_idle_state_is_shared_with_canonical_active_build_guard",
    ):
        if test_name not in test_source:
            raise AssertionError(f"the Docker capacity direct test is missing: {test_name}")
    for test_name in (
        "test_update_capacity_lock_spans_preflight_build_mutation_and_state_write",
        "test_update_capacity_failure_releases_lock_before_any_docker_mutation",
        "test_docker_capacity_controller_is_operator_only",
        "test_update_reuses_existing_datahub_images_without_registry_pull",
        "test_offline_identity_build_keeps_existing_no_capacity_evidence_semantics",
        "test_build_capacity_preflight_builder_selection_output_is_closed_and_optional",
        "test_build_capacity_preflight_rejects_contradictory_builder_selection_evidence",
        "test_build_capacity_preflight_retains_monotonic_builder_selection_outcome",
        "test_build_capacity_preflight_rejects_nonboolean_raw_or_extra_builder_fields",
        "test_builder_selection_failure_survives_later_lock_exit_failure",
        "test_build_capacity_review_required_forbids_every_other_nonunknown_top_predicate",
        "test_build_capacity_preflight_node_schema_output_is_closed_and_optional",
        "test_build_capacity_preflight_rejects_contradictory_node_schema_evidence",
        "test_build_capacity_preflight_rejects_raw_or_extra_node_schema_fields",
        "test_node_schema_failure_survives_later_lock_exit_failure",
    ):
        if test_name not in workflow_test_source:
            raise AssertionError(f"the update-workflow capacity test is missing: {test_name}")

    adr = (ROOT / "docs" / "adr" / "0112-governed-docker-build-capacity.md").read_text(
        encoding="utf-8"
    )
    for fragment in (
        "P = Σ(2 \u00d7 Iᵢ + Cᵢ)",
        "F = P + S",
        "B = ceil(T / 8)",
        "R = floor(B / 2)",
        "runtime/operator-locks/update-build.lock",
        "boolean `Shared` classification",
        "logical = private + shared",
        "Shared=false",
        "diagnosis-only",
        "closed, value-free structural recorder",
        "`builder_selection_known`",
        "optional closed `builder_selection_predicate`",
        "Unknown or pre-selection stops\nomit the subpredicate",
        "fixed first-defect order is driver",
        "sole review-required result\nwhose top-level predicate is not `UNKNOWN`",
        "https://raw.githubusercontent.com/docker/buildx/v0.35.0/commands/ls.go",
        "https://raw.githubusercontent.com/docker/buildx/v0.35.0/builder/builder.go",
        "https://raw.githubusercontent.com/docker/buildx/v0.35.0/builder/node.go",
        "https://docs.docker.com/reference/cli/docker/buildx/ls/",
        "does not claim that the current host binary is pinned to that tag",
        "An omitted or empty node status",
        "node name is not separately matched\nagainst that grammar",
        "closed node-schema subpredicate",
        "`PASS` is recorded only after the complete row/node structural scan",
        "`reconcile_docker_builder_selection.py`",
        "`docker buildx use <validated-current-context>`",
        "neither `--default` nor `--global`",
        "existing `docker-container` builder, its container and its cache are retained",
        "Total selection mutations are therefore at most two",
        "`SEC-DOCKER-BUILDER-SELECT-001`",
        "does not make `docker-container` acceptable",
    ):
        if fragment not in adr:
            raise AssertionError(f"ADR-0112 omits governed capacity term: {fragment}")


def verify_governed_local_topology_contract() -> None:
    platform_path = ROOT / "scripts" / "platform_workflow.py"
    platform = platform_path.read_text(encoding="utf-8")
    platform_tree = ast.parse(platform)
    expected_topology_secrets = (
        "postgres_governance_document_password",
        "redis_delivery_password",
        "s3_governance_document_access_key",
        "s3_governance_document_secret_key",
        "intranet_llm_chat_api_key",
        "intranet_llm_embedding_api_key",
        "neo4j_auth",
        "keycloak_admin_password",
    )
    assignments = (
        node
        for node in ast.walk(platform_tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "TOPOLOGY_RECONCILIATION_SECRET_NAMES"
            for target in node.targets
        )
    )
    secret_assignments = tuple(assignments)
    if len(secret_assignments) != 1:
        raise AssertionError("the topology secret allowlist assignment is ambiguous")
    if ast.literal_eval(secret_assignments[0].value) != expected_topology_secrets:
        raise AssertionError("the exact topology secret allowlist has drifted")
    if platform.count("len(TOPOLOGY_RECONCILIATION_SECRET_NAMES) != 8") != 2:
        raise AssertionError("both topology secret count guards must pin the exact eight names")
    audit_keyword_names = {
        "expected_missing",
        "unexpected_running",
        "selected_unhealthy",
        "unexpected_unhealthy",
        "intent_mismatch",
        "unexpected_unknown_count",
    }
    expected_audits = {
        "exact_initial_findings": {
            "expected_missing": ("worker.governance-document",),
            "unexpected_running": ("gateway.apisix", "graph.neo4j"),
            "selected_unhealthy": (),
            "unexpected_unhealthy": (),
            "intent_mismatch": ("graph.neo4j",),
            "unexpected_unknown_count": 0,
        },
        "exact_web_missing_recovery_findings": {
            "expected_missing": ("core.web", "worker.governance-document"),
            "unexpected_running": ("gateway.apisix", "graph.neo4j"),
            "selected_unhealthy": (),
            "unexpected_unhealthy": (),
            "intent_mismatch": ("graph.neo4j",),
            "unexpected_unknown_count": 0,
        },
    }
    for assignment_name, expected_values in expected_audits.items():
        audit_assignments = [
            node
            for node in ast.walk(platform_tree)
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == assignment_name
        ]
        if len(audit_assignments) != 1:
            raise AssertionError(
                f"the exact topology audit assignment is ambiguous: {assignment_name}"
            )
        audit_call = audit_assignments[0].value
        if not (
            isinstance(audit_call, ast.Call)
            and isinstance(audit_call.func, ast.Name)
            and audit_call.func.id == "LocalTopologyAudit"
            and not audit_call.args
            and all(keyword.arg is not None for keyword in audit_call.keywords)
        ):
            raise AssertionError(
                f"the exact topology audit must be a direct literal: {assignment_name}"
            )
        actual_keyword_names = {keyword.arg for keyword in audit_call.keywords}
        if actual_keyword_names != audit_keyword_names:
            raise AssertionError(f"the exact topology audit fields have drifted: {assignment_name}")
        try:
            actual_values = {
                keyword.arg: ast.literal_eval(keyword.value) for keyword in audit_call.keywords
            }
        except (TypeError, ValueError) as error:
            raise AssertionError(
                f"the exact topology audit contains a nonliteral: {assignment_name}"
            ) from error
        if actual_values != expected_values:
            raise AssertionError(f"the exact topology audit values have drifted: {assignment_name}")

    reconciliation_builders = [
        node
        for node in platform_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "build_topology_reconciliation_plan"
    ]
    if len(reconciliation_builders) != 1:
        raise AssertionError("the topology reconciliation builder is ambiguous")
    reconciliation_builder_node = reconciliation_builders[0]

    def audit_equality(node: ast.If, expected_name: str) -> bool:
        return (
            isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "audit"
            and len(node.test.ops) == 1
            and isinstance(node.test.ops[0], ast.Eq)
            and len(node.test.comparators) == 1
            and isinstance(node.test.comparators[0], ast.Name)
            and node.test.comparators[0].id == expected_name
        )

    def exact_checkpoint_assignment(statements: list[ast.stmt], value: str | None) -> bool:
        return (
            len(statements) == 1
            and isinstance(statements[0], ast.Assign)
            and len(statements[0].targets) == 1
            and isinstance(statements[0].targets[0], ast.Name)
            and statements[0].targets[0].id == "checkpoint"
            and isinstance(statements[0].value, ast.Constant)
            and statements[0].value.value == value
        )

    initial_checks = [
        node
        for node in reconciliation_builder_node.body
        if isinstance(node, ast.If) and audit_equality(node, "exact_initial_findings")
    ]
    if len(initial_checks) != 1:
        raise AssertionError("the initial topology checkpoint equality is ambiguous")
    initial_check = initial_checks[0]
    if not exact_checkpoint_assignment(initial_check.body, "initial") or not (
        len(initial_check.orelse) == 1
        and isinstance(initial_check.orelse[0], ast.If)
        and audit_equality(initial_check.orelse[0], "exact_web_missing_recovery_findings")
        and exact_checkpoint_assignment(initial_check.orelse[0].body, "web-missing-recovery")
        and exact_checkpoint_assignment(initial_check.orelse[0].orelse, None)
    ):
        raise AssertionError("the exact topology checkpoint mapping has drifted")
    for fragment in (
        "class LocalTopologyAudit:",
        "class TopologyReconciliationPlan:",
        'LOCAL_TOPOLOGY_RECONCILIATION = "mac-development-graph-gateway-v1"',
        'checkpoint: Literal["initial", "web-missing-recovery"]',
        "exact_initial_findings = LocalTopologyAudit(",
        'expected_missing=("worker.governance-document",)',
        "exact_web_missing_recovery_findings = LocalTopologyAudit(",
        'expected_missing=("core.web", "worker.governance-document")',
        'unexpected_running=("gateway.apisix", "graph.neo4j")',
        "unexpected_unhealthy=()",
        "or self.unexpected_unhealthy",
        "if audit == exact_initial_findings:",
        'checkpoint = "initial"',
        "elif audit == exact_web_missing_recovery_findings:",
        'checkpoint = "web-missing-recovery"',
        "checkpoint=checkpoint",
        "target_state=replace(state, local_gateway=True, local_graph=True)",
        "class TopologyReconciliationSecretGuard:",
        "TOPOLOGY_RECONCILIATION_SECRET_NAMES",
        '"keycloak_admin_password",',
        "len(TOPOLOGY_RECONCILIATION_SECRET_NAMES) != 8",
        "def revalidate(self) -> None:",
        "set(self.file_descriptors) != expected_names",
        "set(self.file_identities) != expected_names",
        "set(file_descriptors) != expected_names",
        "set(file_identities) != expected_names",
        "_secret_guard_identity(opened) != self.file_identities[name]",
        'traversed == Path("/Volumes/SSD_Mac") and mode == 0o775',
        "opened_secret_dir.st_dev != opened_root.st_dev",
        "os.O_RDONLY | os.O_NOFOLLOW",
        "stat.S_IMODE(opened.st_mode) != 0o444",
        '"expected_missing"',
        '"unexpected_running"',
        '"selected_unhealthy"',
        '"unexpected_unhealthy"',
        '"intent_mismatch"',
        '"unexpected_unknown_count"',
        'raise WorkflowError("LOCAL_TOPOLOGY_QUERY_FAILED")',
        'raise WorkflowError("LOCAL_TOPOLOGY_DRIFT")',
        "state.local_graph != _local_graph_intent(environment_values)",
        'else "__unknown__"',
        "def local_topology_output(",
    ):
        if fragment not in platform:
            raise AssertionError(f"the governed local-topology contract is missing: {fragment}")
    reconciliation_builder = platform.split("def build_topology_reconciliation_plan(", maxsplit=1)[
        1
    ].split("def _same_file_identity(", maxsplit=1)[0]
    for forbidden in ("issubset", "issuperset", "startswith", "audit in "):
        if forbidden in reconciliation_builder:
            raise AssertionError("topology recovery cannot use a generalized prestate predicate")
    topology_audit_builder = platform.split("def build_local_topology_audit(", maxsplit=1)[1].split(
        "def enforce_local_topology(", maxsplit=1
    )[0]
    unexpected_loop = topology_audit_builder.split(
        "for identity, items in grouped.items():", maxsplit=1
    )[1].split("intent_mismatch: set[str]", maxsplit=1)[0]
    unexpected_running = unexpected_loop.index(
        'running = [item for item in items if item.state == "running"]'
    )
    base_finding = unexpected_loop.index("unexpected_running.add(logical_key)", unexpected_running)
    duplicate_check = unexpected_loop.index("if len(running) > 1:", base_finding)
    duplicate_finding = unexpected_loop.index(
        'unexpected_running.add(f"duplicate.{logical_key}")', duplicate_check
    )
    health_finding = unexpected_loop.index("for observation in running:", duplicate_finding)
    if not unexpected_running < base_finding < duplicate_check < duplicate_finding < health_finding:
        raise AssertionError("unexpected managed target duplicate evidence ordering has drifted")
    if "set(os.listdir(secret_descriptor))" in platform:
        raise AssertionError("unrelated canonical secrets cannot influence topology selection")

    update_source = (ROOT / "scripts" / "workflow_update_restart.py").read_text(encoding="utf-8")
    admin_reader = update_source.split("def _read_gateway_admin_password(", maxsplit=1)[1].split(
        "def _gateway_auth_parity_session(", maxsplit=1
    )[0]
    first_revalidate = admin_reader.index("secret_guard.revalidate()")
    descriptor_lookup = admin_reader.index(
        'secret_guard.file_descriptors["keycloak_admin_password"]'
    )
    held_fd_read = admin_reader.index("raw = os.pread(descriptor, 4_097, 0)")
    fixed_shape = admin_reader.index('if not raw or len(raw) > 4_096 or b"\\x00" in raw:')
    decode = admin_reader.index('value = raw.decode("utf-8").strip()')
    last_revalidate = admin_reader.rindex("secret_guard.revalidate()")
    if admin_reader.count("secret_guard.revalidate()") != 2 or not (
        first_revalidate < descriptor_lookup < held_fd_read < fixed_shape < decode < last_revalidate
    ):
        raise AssertionError("the held gateway admin secret reader ordering has drifted")
    for forbidden in ("print(", "write_text(", "write_bytes(", "hashlib"):
        if forbidden in admin_reader:
            raise AssertionError("the gateway admin reader cannot expose or persist credentials")

    platform_test_source = (
        ROOT / "backend" / "tests" / "unit" / "test_platform_workflow.py"
    ).read_text(encoding="utf-8")
    for test_name in (
        "test_topology_secret_guard_selects_exact_gateway_admin_credential",
        "test_gateway_admin_reader_uses_retained_selected_secret_descriptor",
        "test_gateway_admin_secret_replacement_is_detected_by_retained_guard",
        "test_gateway_admin_secret_metadata_failure_is_fixed_and_nonleaking",
        "test_gateway_admin_reader_rejects_invalid_shape_without_payload_leak",
        "test_gateway_admin_reader_postcheck_detects_path_replacement_during_read",
        "test_topology_secret_guard_closes_all_descriptors_after_base_exception",
    ):
        if test_name not in platform_test_source:
            raise AssertionError(f"the topology secret-guard direct test is missing: {test_name}")

    private_query = platform.split("def local_topology_output(", maxsplit=1)[1].split(
        "def _topology_health_class", maxsplit=1
    )[0]
    for fragment in (
        '"docker",',
        '"container",',
        '"ls",',
        '"--all",',
        'f"label=com.docker.compose.project={project}"',
        'raise WorkflowError("LOCAL_TOPOLOGY_QUERY_FAILED")',
        "timeout=20,",
        "subprocess.TimeoutExpired",
    ):
        if fragment not in private_query:
            raise AssertionError("local-topology private query contract is incomplete")
    if "print(" in private_query or "self.run(" in private_query or "self.output(" in private_query:
        raise AssertionError("local-topology private query must not render argv or raw payload")

    capture = platform.split("def capture_local_topology(", maxsplit=1)[1].split(
        "def _enabled_optional_topology_services", maxsplit=1
    )[0]
    if "runner.local_topology_output(project=project)" not in capture:
        raise AssertionError("local-topology capture must use the fixed private query")
    for forbidden in ('"stop"', '"rm"', '"down"', '"restart"', '"inspect"'):
        if forbidden in capture:
            raise AssertionError(f"local-topology capture contains a mutation: {forbidden}")
    if "runner.output(" in capture or "runner.run(" in capture:
        raise AssertionError("local-topology capture must keep Docker argv and payload private")

    workflow = (ROOT / "scripts" / "workflow_update_restart.py").read_text(encoding="utf-8")
    main_source = workflow.split("def main() -> int:", maxsplit=1)[1]
    early_lock = main_source.index(
        "capacity_lock = mutation_stack.enter_context(exclusive_docker_workflow_lock(ROOT))"
    )
    evidence_gate = main_source.index(
        "_require_gateway_auth_parity_evidence_available(reconciliation_name)", early_lock
    )
    refresh_bootstrap = main_source.index("if args.refresh_bootstrap:", evidence_gate)
    config = main_source.index('trailing=("config", "--quiet")')
    running = main_source.index("running = _running_services", config)
    audit = main_source.index("enforce_local_topology(", running)
    plan = main_source.index("_print_plan(", audit)
    confirmation = main_source.index("if not args.assume_yes", plan)
    normal_lock_guard = main_source.index("if capacity_lock is None:", confirmation)
    lock = main_source.index("exclusive_docker_workflow_lock", normal_lock_guard)
    reranker = main_source.index("_reconcile_local_reranker", lock)
    if not (
        early_lock
        < evidence_gate
        < refresh_bootstrap
        < config
        < running
        < audit
        < plan
        < confirmation
        < normal_lock_guard
        < lock
        < reranker
    ):
        raise AssertionError("local-topology audit must precede every update mutation boundary")
    for fragment in (
        "mutation_stack.enter_context(\n                    "
        "require_topology_reconciliation_secrets(ROOT)",
        "topology_secret_guard.revalidate()",
    ):
        if fragment not in main_source:
            raise AssertionError("the retained topology secret guard has drifted")

    reconciliation = workflow.split("def _apply_topology_reconciliation(", maxsplit=1)[1].split(
        "def _compose(", maxsplit=1
    )[0]
    guard_before = reconciliation.index("secret_guard.revalidate()")
    worker = reconciliation.index("plan.missing_worker_service")
    guard_after = reconciliation.index("secret_guard.revalidate()", guard_before + 1)
    database = reconciliation.index("_verify_governance_document_worker_database", worker)
    gateway_build = reconciliation.index('trailing=("build", "apisix")', database)
    gateway_up = reconciliation.index('"apisix",', gateway_build)
    web = reconciliation.index('"web",', gateway_up)
    airflow = reconciliation.index("*AIRFLOW_SERVICES", web)
    if (
        not guard_before
        < worker
        < guard_after
        < database
        < gateway_build
        < gateway_up
        < web
        < airflow
    ):
        raise AssertionError("topology reconciliation mutation order has drifted")
    if any(fragment in reconciliation for fragment in ('"stop"', '"rm"', '"down"')):
        raise AssertionError("topology reconciliation cannot stop or delete selected services")

    test_source = (ROOT / "backend" / "tests" / "unit" / "test_platform_workflow.py").read_text(
        encoding="utf-8"
    )
    for test_name in (
        "test_local_topology_clean_fast_path_has_no_findings",
        "test_local_topology_keeps_runtime_and_intent_drift_separate",
        "test_topology_reconciliation_rejects_unexpected_target_unhealthy_before_mutation",
        "test_local_topology_rejects_invalid_health_without_raw_evidence",
        "test_local_topology_audit_rejects_invalid_unexpected_health_evidence",
        "test_unexpected_target_duplicate_running_is_bounded_and_rejected",
        "test_unexpected_target_running_and_stopped_is_not_duplicate",
        "test_unexpected_target_duplicate_retains_unhealthy_evidence",
        "test_local_topology_reports_missing_and_selected_unhealthy_separately",
        "test_local_topology_unknown_service_is_counted_without_identifier_leak",
        "test_local_topology_reverse_intent_mismatch_does_not_adopt_env_silently",
        "test_local_topology_queries_only_exact_managed_projects",
        "test_local_topology_query_failure_is_fixed_and_sanitized",
        "test_local_topology_private_capture_never_prints_command_or_payload",
        "test_local_topology_private_capture_failure_is_fixed_and_sanitized",
        "test_local_topology_private_capture_timeout_is_fixed_sanitized_and_not_retried",
        "test_update_topology_drift_stops_before_lock_reranker_or_state_mutation",
        "test_exact_mac_topology_reconciliation_changes_only_graph_and_gateway",
        "test_exact_mac_topology_reconciliation_accepts_only_web_missing_recovery",
        "test_topology_reconciliation_rejects_any_nonexact_prestate_or_finding",
        "test_locked_topology_checkpoint_transition_stops_before_mutation",
        "test_topology_secret_preflight_accepts_selected_subset_of_canonical_metadata",
        "test_topology_secret_preflight_rejects_a_symlinked_root",
        "test_topology_secret_guard_detects_selected_file_replacement_after_preflight",
        "test_topology_secret_preflight_fails_closed_without_reading_values",
        "test_topology_reconciliation_mutation_order_is_worker_gateway_web_airflow",
        "test_worker_create_is_bracketed_by_retained_secret_guard_on_ambiguous_failure",
        "test_worker_create_stops_before_mutation_when_retained_secret_guard_drifted",
        "test_governance_document_role_and_backlog_are_separate_sanitized_queries",
        "test_topology_reconciliation_failure_stops_before_later_mutations",
        "test_reconciliation_target_audit_requires_web_worker_gateway_and_graph",
        "test_gateway_transparency_is_only_a_routing_negative_not_positive_auth_evidence",
        "test_unreviewed_gateway_reconciliation_stops_under_lock_before_runtime_mutation",
        "test_gateway_log_probe_rejects_credential_persistence_without_raw_output",
    ):
        if test_name not in test_source:
            raise AssertionError(f"the local-topology direct test is missing: {test_name}")
    if "if locked_plan != reconciliation_plan:" not in workflow:
        raise AssertionError("the locked topology plan must retain exact checkpoint equality")
    development_test_source = (
        ROOT / "backend" / "tests" / "unit" / "test_development_cycle.py"
    ).read_text(encoding="utf-8")
    if "test_dev_publish_never_pushes_after_reconciliation_failure" not in development_test_source:
        raise AssertionError("dev-publish must retain reconciliation-failure push0 coverage")

    adr = (ROOT / "docs" / "adr" / "0113-governed-local-topology-drift.md").read_text(
        encoding="utf-8"
    )
    for fragment in (
        "LOCAL_TOPOLOGY_DRIFT",
        "expected-missing",
        "web-missing-recovery",
        "not a general resumability contract",
        "unexpected-running",
        "selected-unhealthy",
        "intent-mismatch",
        "no auto-stop",
        "mac-development-graph-gateway-v1",
        "governance-document-worker",
        "required subset",
        "SEC-GATEWAY-AUTH-PARITY-001-A-V1",
        "Keycloak remains the sole identity provider",
        "do not claim that",
        "remote_addr",
        "OPEN_TARGET_GATE",
    ):
        if fragment not in adr:
            raise AssertionError(f"ADR-0113 omits local-topology term: {fragment}")


def verify_transparent_gateway_contract() -> None:
    route_document = _yaml(ROOT / "infra" / "apisix" / "apisix.yaml")
    routes = route_document.get("routes")
    if not isinstance(routes, list) or len(routes) != 2:
        raise AssertionError("APISIX must expose only the two reviewed API routes")
    allowed_plugins = {"request-id", "limit-count", "proxy-rewrite"}
    auth_plugins = {
        "jwt-auth",
        "openid-connect",
        "key-auth",
        "basic-auth",
        "hmac-auth",
        "authz-keycloak",
        "forward-auth",
        "consumer-restriction",
        "cors",
    }
    for route in routes:
        plugins = route.get("plugins")
        if not isinstance(plugins, dict) or set(plugins) != allowed_plugins:
            raise AssertionError("APISIX route plugin allowlist has drifted")
        if auth_plugins.intersection(plugins):
            raise AssertionError("APISIX cannot authenticate or authorize DataRiver callers")
        if plugins.get("proxy-rewrite") != {"headers": {"set": {"X-Forwarded-Proto": "$scheme"}}}:
            raise AssertionError("APISIX cannot strip or synthesize caller credentials")
        limit = plugins.get("limit-count")
        if not isinstance(limit, dict) or (
            limit.get("key") != "remote_addr" or limit.get("rejected_code") != 429
        ):
            raise AssertionError("Mac gateway rate limiting must remain an availability decision")
    general = next((route for route in routes if route.get("id") == "datariver-api-v1"), None)
    if not isinstance(general, dict) or set(general.get("methods", [])) != {
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
    }:
        raise AssertionError("APISIX must preserve the complete API method contract")

    config = _yaml(ROOT / "infra" / "apisix" / "config.yaml")
    if "plugins" in config:
        raise AssertionError("APISIX global plugins are forbidden")
    if (
        config.get("apisix", {}).get("enable_admin") is not False
        or config.get("apisix", {}).get("enable_control") is not False
    ):
        raise AssertionError("APISIX must remain a YAML-only data plane")
    http = config.get("nginx_config", {}).get("http", {})
    if http.get("client_max_body_size") != "12m":
        raise AssertionError("APISIX and Web bounded multipart limits must agree")
    config_source = (
        (ROOT / "infra" / "apisix" / "config.yaml").read_text(encoding="utf-8").casefold()
    )
    for forbidden in ("$http_authorization", "$http_cookie", "$request_body"):
        if forbidden in config_source:
            raise AssertionError("APISIX logs must not include credentials or request bodies")

    routing = _yaml(ROOT / "compose.gateway-routing.yaml")["services"]["web"]
    if routing.get("environment") != {"API_PROXY_UPSTREAM": "apisix:9080"}:
        raise AssertionError("selected Web traffic must use the fixed APISIX upstream")
    if routing.get("depends_on") != {"apisix": {"condition": "service_healthy"}}:
        raise AssertionError("Web must fail unavailable without a healthy selected gateway")
    routing_source = (ROOT / "compose.gateway-routing.yaml").read_text(encoding="utf-8")
    for forbidden in (
        "api:8000",
        "BROWSER_OIDC_AUTHORITY",
        "BROWSER_OIDC_CLIENT_ID",
        "BROWSER_OIDC_REDIRECT_URI",
    ):
        if forbidden in routing_source:
            raise AssertionError("gateway routing cannot bypass API or rewrite browser identity")

    airflow = _yaml(ROOT / "compose.airflow.host-dev.yaml")["services"]
    for service in (
        "airflow-api-server",
        "airflow-scheduler",
        "airflow-dag-processor",
        "airflow-triggerer",
    ):
        if airflow[service]["environment"].get("DATARIVER_API_BASE_URL") != ("http://apisix:9080"):
            raise AssertionError("selected Airflow API traffic must use fixed APISIX routing")
    if (
        airflow["airflow-scheduler"]["environment"].get("DATARIVER_QUALITY_DISPATCH_API_BASE_URL")
        != "http://apisix:9080"
    ):
        raise AssertionError("selected Airflow quality dispatch must use fixed APISIX routing")

    tests = ROOT / "backend" / "tests" / "unit" / "test_apisix_transparent_gateway.py"
    test_source = tests.read_text(encoding="utf-8")
    for test_name in (
        "test_apisix_is_a_transparent_rate_limited_router_not_an_identity_provider",
        "test_apisix_has_no_global_plugin_or_credential_log_surface",
        "test_web_proxy_preserves_identity_cors_and_retry_headers_without_direct_fallback",
        "test_gateway_overlay_does_not_change_browser_oidc_or_public_origin_contract",
        "test_selected_airflow_uses_gateway_but_acquires_tokens_directly_from_keycloak",
        "test_every_auth_or_global_plugin_injection_is_rejected",
        "test_request_and_response_identity_headers_are_transparent",
        "test_static_status_echo_is_not_accepted_as_gateway_auth_parity_evidence",
    ):
        if test_name not in test_source:
            raise AssertionError(f"the transparent gateway direct test is missing: {test_name}")

    update = (ROOT / "scripts" / "workflow_update_restart.py").read_text(encoding="utf-8")
    probe = update.split("GATEWAY_TRANSPARENCY_PROGRAM =", maxsplit=1)[1].split(
        "_POSTGRES_SECRET_MOUNT_ENV_KEYS", maxsplit=1
    )[0]
    for fragment in (
        '"/api/v1/knowledge/registry/assets"',
        '"/api/v1/change-requests"',
        '"Authorization"',
        '"Cookie"',
        '"Origin"',
        '"Access-Control-Request-Method"',
        '"WWW-Authenticate"',
        '"Set-Cookie"',
        '"Access-Control-Allow-Origin"',
        "status != 401",
        'method="POST"',
        "gateway-body-secret-sentinel",
        'method="OPTIONS"',
        "GATEWAY_TRANSPARENCY_OK",
    ):
        if fragment not in probe:
            raise AssertionError(f"the transparent gateway runtime probe is missing: {fragment}")
    if "response.read" in probe or "print(response" in probe:
        raise AssertionError("transparent gateway evidence cannot retain response bodies")
    if "GATEWAY_AUTH_PARITY_EVIDENCE_UNAVAILABLE" not in update:
        raise AssertionError("unreviewed gateway reconciliation names must fail closed")
    update_main = update.split("def main() -> int:", maxsplit=1)[1]
    availability_gate = update_main.index(
        "_require_gateway_auth_parity_evidence_available(reconciliation_name)"
    )
    if availability_gate > update_main.index("if args.refresh_bootstrap:"):
        raise AssertionError("unavailable auth parity must stop before refresh-bootstrap")
    if "_forward_api_status_below_rate_limit" in test_source:
        raise AssertionError("static status echo cannot be gateway auth-parity evidence")

    main_source = update_main
    if "_airflow_compose_files(" not in main_source:
        raise AssertionError("selected Airflow restarts must retain transparent gateway routing")
    transparency = main_source.index("_verify_gateway_transparency(")
    target_audit = main_source.index("enforce_local_topology(", transparency)
    state_write = main_source.index("write_applied_state(", target_audit)
    if not transparency < target_audit < state_write:
        raise AssertionError("transparent gateway evidence must precede audit and state write")


def verify_gateway_auth_parity_fixture_contract() -> None:
    probe_path = ROOT / "scripts" / "probe_gateway_auth_parity.py"
    classifier_path = ROOT / "scripts" / "classify_gateway_production_invariant.py"
    convergence_path = ROOT / "scripts" / "converge_gateway_web_authorization_services.py"
    fixture_path = ROOT / "backend" / "src" / "datariver" / "gateway_auth_parity_fixture.py"
    probe_test_path = ROOT / "backend" / "tests" / "unit" / "test_gateway_auth_parity_probe.py"
    convergence_test_path = (
        ROOT / "backend" / "tests" / "unit" / "test_gateway_web_authorization_services.py"
    )
    fixture_test_path = ROOT / "backend" / "tests" / "unit" / "test_gateway_auth_parity_fixture.py"
    platform_test_path = ROOT / "backend" / "tests" / "unit" / "test_platform_workflow.py"
    workflow_path = ROOT / "scripts" / "workflow_update_restart.py"
    keycloak_dockerfile_path = ROOT / "infra" / "keycloak" / "Dockerfile"
    keycloak_realm_path = ROOT / "infra" / "keycloak" / "datariver-realm.template.json"
    keycloak_host_dev_path = ROOT / "scripts" / "configure_keycloak_host_dev.sh"
    for path in (
        probe_path,
        classifier_path,
        convergence_path,
        fixture_path,
        probe_test_path,
        convergence_test_path,
        fixture_test_path,
        platform_test_path,
        workflow_path,
    ):
        if not path.is_file():
            raise AssertionError("the governed gateway parity fixture path is missing")

    probe = probe_path.read_text(encoding="utf-8")
    classifier = classifier_path.read_text(encoding="utf-8")
    convergence = convergence_path.read_text(encoding="utf-8")
    fixture = fixture_path.read_text(encoding="utf-8")
    probe_tests = probe_test_path.read_text(encoding="utf-8")
    convergence_tests = convergence_test_path.read_text(encoding="utf-8")
    fixture_tests = fixture_test_path.read_text(encoding="utf-8")
    platform_tests = platform_test_path.read_text(encoding="utf-8")
    workflow = workflow_path.read_text(encoding="utf-8")
    keycloak_dockerfile = keycloak_dockerfile_path.read_text(encoding="utf-8")
    keycloak_realm = json.loads(keycloak_realm_path.read_text(encoding="utf-8"))
    keycloak_host_dev = keycloak_host_dev_path.read_text(encoding="utf-8")
    pinned_keycloak = (
        "quay.io/keycloak/keycloak:26.7.0@sha256:"
        "2eb3cd316835c990e69e26ade292ffa78f6fb0db7d5fc6377463c162e1979ac0"
    )
    if keycloak_dockerfile.count(pinned_keycloak) != 2:
        raise AssertionError("gateway invariant must stay pinned to exact Keycloak 26.7 image")
    web_clients = [
        client
        for client in keycloak_realm.get("clients", [])
        if isinstance(client, dict) and client.get("clientId") == "datariver-web"
    ]
    if len(web_clients) != 1 or web_clients[0].get("authorizationServicesEnabled") is not False:
        raise AssertionError("the exact Web client must disable Keycloak Authorization Services")
    web_update = keycloak_host_dev.split("clientId=datariver-web", maxsplit=1)[1].split(
        "update realms/datariver", maxsplit=1
    )[0]
    if (
        web_update.count("-s authorizationServicesEnabled=false") != 1
        or "authorizationServicesEnabled=true" in keycloak_host_dev
    ):
        raise AssertionError("the exact Web updater must explicitly disable Authorization Services")
    for fragment in (
        'FIXTURE_CONTRACT = "SEC-GATEWAY-AUTH-PARITY-001-A-V1"',
        'FIXTURE_CLIENT_ID = "datariver-gateway-auth-parity-v1"',
        "OIDC_VERIFIER_LEEWAY_SECONDS = 30",
        'GATEWAY_LOG_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"',
        '"publicClient": True',
        '"clientAuthenticatorType": "client-secret"',
        '"name": "DataRiver Gateway Auth Parity"',
        '"bearerOnly": False',
        '"surrogateAuthRequired": False',
        '"consentRequired": False',
        '"standardFlowEnabled": True',
        '"directAccessGrantsEnabled": False',
        '"implicitFlowEnabled": False',
        '"serviceAccountsEnabled": False',
        '"authorizationServicesEnabled": False',
        '"fullScopeAllowed": False',
        '"frontchannelLogout": False',
        '"authenticationFlowBindingOverrides": {}',
        '"optionalClientScopes": []',
        '"defaultClientScopes": ["basic", "acr", "profile", "email", "roles"]',
        '"pkce.code.challenge.method": "S256"',
        '("knowledge-registry", "/api/v1/knowledge/registry/assets")',
        '("change-request", "/api/v1/change-requests")',
        'PARITY_HOPS = ("direct", "gateway", "web")',
        'self._traffic.verify_status_matrix("allow", allow.value, 200)',
        'self._traffic.verify_status_matrix("deny", deny.value, 403)',
        'self._traffic.verify_status_matrix("malformed", malformed, 401)',
        'self._traffic.verify_status_matrix("expired", allow.value, 401)',
        "self._traffic.require_not_expired(current_allow.expires_at)",
        'self._traffic.verify_status_matrix("membership-revoked", current_allow.value, 403)',
        'immediate_logout="OPEN_UNSUPPORTED"',
        'print("GATEWAY_AUTH_PARITY_CANONICAL_WORKFLOW_REQUIRED", file=sys.stderr)',
        "self._validated_user_uuid(",
        "allow_partial_mapper=True",
        "def audience_mapper_document()",
        "def _exact_pkce_callback(value: str) -> bool:",
        "response.iter_bytes(chunk_size=64 * 1024)",
        "allowed_mapper_counts = {0, 1} if allow_partial_mapper else {1}",
        'attributes != expected["attributes"]',
        "class GatewayAuthParityExecutionError",
        "class GatewayCredentialLogEvidenceError",
        "log_evidence_failed=outcome.log_evidence_failed",
        "log_evidence_known=outcome.log_evidence_known",
        "cleanup_required=cleanup_required",
        "GATEWAY_AUTH_PARITY_INTERRUPTED",
        '"GATEWAY_AUTH_PARITY_FIXTURE_FAILED",',
        "raise GatewayAuthParityExecutionError(",
        "self._admin_token = None",
        "def release_without_mutation(self) -> None:",
        "if len(mapper_document) > _MAXIMUM_PRODUCTION_MAPPERS:",
        "flow_overrides = _normalized_string_mapping(",
        "attributes = _normalized_string_mapping(",
        '"authenticationFlowBindingOverrides": flow_overrides',
        '"protocolMappers": tuple(',
        "class ProductionWebInvariantPredicate(str, Enum):",
        "def _normalize_production_web_contract(",
        "def _classify_production_web_contract(",
        "def classify_production_web_invariant(self)",
        "format_production_web_invariant_evidence(",
    ):
        if fragment not in probe:
            raise AssertionError(f"the governed gateway parity probe is missing: {fragment}")
    oidc_verifier = (
        ROOT / "backend" / "src" / "datariver" / "infrastructure" / "security" / "oidc.py"
    ).read_text(encoding="utf-8")
    if "leeway=30" not in oidc_verifier:
        raise AssertionError("gateway parity expiry evidence must match the API verifier leeway")
    concrete_traffic = probe.split("class GatewayAuthParityTraffic:", maxsplit=1)[1]
    expiry = concrete_traffic.split("def wait_until_expired(", maxsplit=1)[1].split(
        "def require_not_expired(", maxsplit=1
    )[0]
    for fragment in (
        "expires_at + OIDC_VERIFIER_LEEWAY_SECONDS",
        "ACCESS_TOKEN_LIFESPAN_SECONDS + OIDC_VERIFIER_LEEWAY_SECONDS + 2",
        "_genuine_expiry_reached(",
    ):
        if fragment not in expiry:
            raise AssertionError("gateway parity genuine-expiry timing has drifted")
    authenticate = probe.split("def _authenticate(", maxsplit=1)[1].split(
        "def authenticate_allow(", maxsplit=1
    )[0]
    initial_get = authenticate.index("response = _bounded_response(browser, request)")
    first_cookie_normalization = authenticate.index(
        "self._normalize_loopback_cookies(browser)", initial_get
    )
    credential_post = authenticate.index('browser.build_request("POST", action, data=form)')
    if not initial_get < first_cookie_normalization < credential_post:
        raise AssertionError("loopback Secure cookies must be normalized before credential POST")
    if authenticate.count("self._normalize_loopback_cookies(browser)") < 5:
        raise AssertionError("every loopback PKCE same-origin transition must normalize cookies")
    traffic_request = concrete_traffic.split("def _request(", maxsplit=1)[1].split(
        "def verify_status_matrix(", maxsplit=1
    )[0]
    if not traffic_request.index("self._log_started_at = datetime.now(") < traffic_request.index(
        'selected["Authorization"] = f"Bearer {token}"'
    ):
        raise AssertionError("gateway log interval must start before the first credential request")
    revoke = probe.index("self._fixture.revoke_allow_membership(")
    first_valid = probe.rfind("self._traffic.require_not_expired(", 0, revoke)
    second_valid = probe.index("self._traffic.require_not_expired(", revoke)
    if not first_valid < revoke < second_valid:
        raise AssertionError(
            "membership parity must keep a valid token around the exact revocation"
        )
    close = probe.split("def _close(self) -> _GatewayAuthParityCloseOutcome:", maxsplit=1)[1].split(
        "def close(self) -> None:", maxsplit=1
    )[0]
    public_close = probe.split("def close(self) -> None:", maxsplit=1)[1].split(
        "def run_with_topology(", maxsplit=1
    )[0]
    cleanup_order = tuple(
        close.index(fragment)
        for fragment in (
            "self._traffic.assert_logs_clean(())",
            "cleanup_sessions_and_users()",
            "self._fixture.cleanup(",
            "cleanup_client()",
            "require_invariants_and_zero_residual()",
            "self._fixture.require_zero_residual()",
        )
    )
    if (
        cleanup_order != tuple(sorted(cleanup_order))
        or "except BaseException:" not in close
        or "log_evidence_failed = True" not in close
        or "cleanup_required = True" not in close
        or "GATEWAY_CREDENTIAL_LOG_PROBE_FAILED" not in public_close
    ):
        raise AssertionError("gateway parity cleanup order or BaseException boundary has drifted")

    for fragment in (
        'actions = ("change.read", "kg.read")',
        'job_function="GATEWAY_AUTH_PARITY_PROBE"',
        "active=False",
        "membership.active = False",
        "membership.version += 1",
        "rows = await self._exact_rows(identities, cleanup=True, allow_absent=True)",
        "with_for_update=True",
        "membership.version != expected_version",
        "privilege_residual_counts = await self._privilege_residual_counts(subject_ids)",
        "if not rows or any(privilege_residual_counts):",
        "external_subjects = tuple(identity.external_subject for identity in identities)",
        "residual_subject_ids = tuple(dict.fromkeys((*subject_ids, *residual_subject_rows)))",
        "privilege_residual_counts = await self._privilege_residual_counts(residual_subject_ids)",
        "except BaseException:",
        'print("GATEWAY_AUTH_PARITY_FIXTURE_FAILED", file=sys.stderr)',
    ):
        if fragment not in fixture:
            raise AssertionError(f"the least-scope gateway parity fixture is missing: {fragment}")
    fixture_syntax = ast.parse(fixture, filename=fixture_path.as_posix())

    def fixture_enum_members(class_name: str) -> tuple[tuple[str, object], ...]:
        matches = [
            node
            for node in fixture_syntax.body
            if isinstance(node, ast.ClassDef) and node.name == class_name
        ]
        if len(matches) != 1:
            raise AssertionError("the fixture diagnostic enum must be defined exactly once")
        return tuple(
            (statement.targets[0].id, ast.literal_eval(statement.value))
            for statement in matches[0].body
            if isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        )

    if fixture_enum_members("FixtureDiagnosticOperation") != (
        ("REQUIRE_ABSENT", "REQUIRE_ABSENT"),
    ):
        raise AssertionError("the fixture diagnostic operation must remain exact and read-only")
    expected_diagnostic_predicates = (
        ("PASS", "PASS"),
        ("FIXED_INPUT_PROTOCOL", "FIXED_INPUT_PROTOCOL"),
        ("ENVIRONMENT_DEPENDENCY", "ENVIRONMENT_DEPENDENCY"),
        ("REPOSITORY_NOT_ABSENT", "REPOSITORY_NOT_ABSENT"),
        ("REPOSITORY_QUERY_DEPENDENCY", "REPOSITORY_QUERY_DEPENDENCY"),
        ("IMAGE_PROVENANCE", "IMAGE_PROVENANCE"),
        ("PROCESS_SPAWN", "PROCESS_SPAWN"),
        ("PROCESS_TIMEOUT", "PROCESS_TIMEOUT"),
        ("PROCESS_NONZERO", "PROCESS_NONZERO"),
        ("OUTPUT_SIZE", "OUTPUT_SIZE"),
        ("OUTPUT_LINE", "OUTPUT_LINE"),
        ("OUTPUT_JSON", "OUTPUT_JSON"),
        ("OUTPUT_SHAPE", "OUTPUT_SHAPE"),
        ("OUTPUT_TUPLE", "OUTPUT_TUPLE"),
        ("UNKNOWN", "UNKNOWN"),
    )
    if fixture_enum_members("FixtureDiagnosticPredicate") != expected_diagnostic_predicates:
        raise AssertionError("the fixture diagnostic predicate vocabulary has drifted")
    workflow_syntax = ast.parse(workflow, filename=workflow_path.as_posix())

    def workflow_enum_members(class_name: str) -> tuple[tuple[str, object], ...]:
        matches = [
            node
            for node in workflow_syntax.body
            if isinstance(node, ast.ClassDef) and node.name == class_name
        ]
        if len(matches) != 1:
            raise AssertionError("the outer fixture diagnostic enum must be defined exactly once")
        return tuple(
            (statement.targets[0].id, ast.literal_eval(statement.value))
            for statement in matches[0].body
            if isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        )

    if workflow_enum_members("FixtureDiagnosticExecutionClassification") != (
        ("PASS", "PASS"),
        ("REJECTED", "REJECTED"),
        ("OPERATOR_REVIEW_REQUIRED", "OPERATOR_REVIEW_REQUIRED"),
    ):
        raise AssertionError("the outer fixture classification vocabulary has drifted")
    if workflow_enum_members("HostEnvironmentPreflightClassification") != (
        ("PASS", "PASS"),
        ("REJECTED", "REJECTED"),
        ("OPERATOR_REVIEW_REQUIRED", "OPERATOR_REVIEW_REQUIRED"),
    ):
        raise AssertionError("the host-environment classification vocabulary has drifted")
    if workflow_enum_members("BuildCapacityPreflightClassification") != (
        ("PASS", "PASS"),
        ("REJECTED", "REJECTED"),
        ("OPERATOR_REVIEW_REQUIRED", "OPERATOR_REVIEW_REQUIRED"),
    ):
        raise AssertionError("the build-capacity classification vocabulary has drifted")
    if workflow_enum_members("HostEnvironmentPreflightPhase") != (
        ("HOST_ENVIRONMENT_PREFLIGHT", "HOST_ENVIRONMENT_PREFLIGHT"),
    ):
        raise AssertionError("the host-environment diagnostic phase has drifted")
    if workflow_enum_members("BuildCapacityPreflightPhase") != (
        ("BUILD_CAPACITY_PREFLIGHT", "BUILD_CAPACITY_PREFLIGHT"),
    ):
        raise AssertionError("the build-capacity diagnostic phase has drifted")
    build_capacity_evidence = workflow.split("class BuildCapacityPreflightEvidence:", maxsplit=1)[
        1
    ].split("class _HostEnvironmentPreflightResult:", maxsplit=1)[0]
    for fragment in (
        "builder_selection_known: bool = False",
        "builder_selection_predicate: BuilderSelectionPredicate | None = None",
        "type(self.builder_selection_known) is not bool",
        "self.builder_selection_known",
        "!= (self.builder_selection_predicate is not None)",
        "self.builder_selection_predicate is BuilderSelectionPredicate.UNKNOWN",
        "self.predicate is BuildCapacityPreflightPredicate.BUILDER_SELECTION",
        "builder_selection_failure",
        "self.builder_selection_predicate is BuilderSelectionPredicate.PASS",
        "builder_selection_pass_required",
        "review_preserves_selection_failure",
        "and not review_preserves_selection_failure",
        "node_schema_known: bool = False",
        "node_schema_predicate: NodeSchemaPredicate | None = None",
        "type(self.node_schema_known) is not bool",
        "self.node_schema_known",
        "!= (self.node_schema_predicate is not None)",
        "self.node_schema_predicate is NodeSchemaPredicate.UNKNOWN",
        "self.builder_selection_predicate is BuilderSelectionPredicate.NODE_SCHEMA",
        "node_schema_failure",
        "self.node_schema_predicate is NodeSchemaPredicate.PASS",
        "node_schema_pass_required",
        "review_preserves_node_schema_pass",
    ):
        if fragment not in build_capacity_evidence:
            raise AssertionError(
                f"the builder-selection evidence consistency rule is missing: {fragment}"
            )
    if workflow_enum_members("HostEnvironmentPreflightPredicate") != (
        ("APPLIED_STATE_CONTRACT", "APPLIED_STATE_CONTRACT"),
        ("PROFILE_SELECTION", "PROFILE_SELECTION"),
        ("DEPLOYMENT_MODE_SELECTION", "DEPLOYMENT_MODE_SELECTION"),
        ("GATEWAY_SELECTION", "GATEWAY_SELECTION"),
        ("GRAPH_SELECTION", "GRAPH_SELECTION"),
        ("ENV_PATH_CONTRACT", "ENV_PATH_CONTRACT"),
        ("ENV_FILE_CONTRACT", "ENV_FILE_CONTRACT"),
        ("ENV_READ", "ENV_READ"),
        ("ENV_FINGERPRINT", "ENV_FINGERPRINT"),
        ("COMPOSE_SELECTION", "COMPOSE_SELECTION"),
        ("PASS", "PASS"),
        ("UNKNOWN", "UNKNOWN"),
    ):
        raise AssertionError("the host-environment predicate vocabulary has drifted")
    if workflow_enum_members("_FixtureContainerState") != (
        ("ABSENT", "ABSENT"),
        ("OWNED_RUNNING", "OWNED_RUNNING"),
        ("OWNED_STOPPED", "OWNED_STOPPED"),
        ("FOREIGN", "FOREIGN"),
        ("UNKNOWN", "UNKNOWN"),
    ):
        raise AssertionError("the exact fixture-container state vocabulary has drifted")
    if workflow_enum_members("_FixtureSourceCleanState") != (
        ("CLEAN", "CLEAN"),
        ("DIRTY", "DIRTY"),
        ("INVALID", "INVALID"),
        ("UNKNOWN", "UNKNOWN"),
    ):
        raise AssertionError("the fixture source-clean state vocabulary has drifted")
    for fragment in (
        "MAXIMUM_FIXTURE_DIAGNOSTIC_BYTES = 256",
        "object_pairs_hook=_capture_fixture_diagnostic_object",
        "if len(keys) != len(set(keys)):",
        'set(document) != {"operation", "predicate"}',
        'operation_value = document["operation"]',
        'predicate_value = document["predicate"]',
        "FixtureDiagnosticOperation(operation_value)",
        "FixtureDiagnosticPredicate(predicate_value)",
        'return f"GATEWAY_AUTH_PARITY_FIXTURE_REQUIRE_ABSENT_{predicate.value}"',
        "diagnostic_predicate=FixtureDiagnosticPredicate.FIXED_INPUT_PROTOCOL",
        "diagnostic_predicate=FixtureDiagnosticPredicate.ENVIRONMENT_DEPENDENCY",
        "diagnostic_predicate=FixtureDiagnosticPredicate.REPOSITORY_NOT_ABSENT",
        "diagnostic_predicate=FixtureDiagnosticPredicate.REPOSITORY_QUERY_DEPENDENCY",
        "diagnostic_predicate=FixtureDiagnosticPredicate.IMAGE_PROVENANCE",
        '"source_sha256",',
        "descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)",
        "opened = os.fstat(descriptor)",
        "chunk = os.read(",
        "return hashlib.sha256(content).hexdigest()",
        "hmac.compare_digest(current_fixture_source_sha256(), expected_sha256)",
        "if request.operation is FixtureOperation.REQUIRE_ABSENT:",
        "format_fixture_diagnostic_line(",
    ):
        if fragment not in fixture:
            raise AssertionError(f"the fixture diagnostic envelope is missing: {fragment}")
    fixture_main = fixture.split("def main() -> int:", maxsplit=1)[1]
    if not fixture_main.index(
        "require_current_fixture_source(request.source_sha256)"
    ) < fixture_main.index("execute_fixture_request(request)"):
        raise AssertionError("the baked fixture provenance must fail before any repository query")
    fixture_source_proof = fixture.split("def current_fixture_source_sha256() -> str:", maxsplit=1)[
        1
    ].split("def require_current_fixture_source(", maxsplit=1)[0]
    if "except BaseException:" in fixture_source_proof or "except Exception:" not in (
        fixture_source_proof
    ):
        raise AssertionError("the fixture source proof must not absorb process interrupts")
    sql_repository = fixture.split("class SqlGatewayAuthParityFixtureRepository:", maxsplit=1)[1]
    absence_source = sql_repository.split("async def require_absent(", maxsplit=1)[1].split(
        "async def prepare(", maxsplit=1
    )[0]
    if any(
        forbidden in absence_source for forbidden in ("delete(", ".execute(", ".add(", ".flush(")
    ):
        raise AssertionError("the require-absent diagnostic repository must remain SELECT-only")
    workflow_fixture = workflow.split("class _ComposeGatewayAuthParityFixture:", maxsplit=1)[
        1
    ].split("def _read_gateway_admin_password(", maxsplit=1)[0]
    for fragment in (
        "diagnostic_container_arguments = (",
        'if operation == "require-absent"',
        "*diagnostic_container_arguments,",
        "_bounded_fixture_diagnostic_process(tuple(command), request_document)",
        "parse_fixture_diagnostic_line(stdout)",
        "parse_fixture_diagnostic_line(stderr)",
        "if stdout and stderr:",
        "def diagnose_require_absent(self) -> FixtureDiagnosticEnvelope:",
        "fixture_diagnostic_failure_classification(evidence.predicate)",
    ):
        if fragment not in workflow_fixture:
            raise AssertionError(f"the fixture diagnostic parent is missing: {fragment}")
    if "print(result.stdout" in workflow_fixture or "print(result.stderr" in workflow_fixture:
        raise AssertionError("the fixture diagnostic must never forward child output")
    if workflow_fixture.count("*diagnostic_container_arguments,") != 1:
        raise AssertionError("the exact task container options must be diagnostic-only")
    require_absent_branch = workflow_fixture.split('if operation == "require-absent":', maxsplit=1)[
        1
    ].split("\n\n        try:\n            result = subprocess.run", maxsplit=1)[0]
    if any(
        forbidden in require_absent_branch
        for forbidden in ("capture_output=True", "subprocess.run(", ".communicate(")
    ):
        raise AssertionError("the require-absent process must use only bounded in-flight capture")
    bounded_capture = workflow.split("def _bounded_fixture_diagnostic_process(", maxsplit=1)[
        1
    ].split("def _bounded_suppressed_fixture_build(", maxsplit=1)[0]
    for fragment in (
        "subprocess.Popen(",
        "selectors.DefaultSelector()",
        "selector.register(process.stdout, selectors.EVENT_READ, stdout)",
        "selector.register(process.stderr, selectors.EVENT_READ, stderr)",
        "combined_size = len(stdout) + len(stderr)",
        "MAXIMUM_FIXTURE_DIAGNOSTIC_BYTES + 1 - combined_size",
        "if len(stdout) + len(stderr) > MAXIMUM_FIXTURE_DIAGNOSTIC_BYTES:",
        "process.terminate()",
        "process.kill()",
        "process.wait(timeout=_FIXTURE_DIAGNOSTIC_REAP_SECONDS)",
        "FixtureDiagnosticPredicate.PROCESS_SPAWN",
        "FixtureDiagnosticPredicate.PROCESS_TIMEOUT",
        "FixtureDiagnosticPredicate.OUTPUT_SIZE",
        "FixtureDiagnosticPredicate.UNKNOWN",
    ):
        if fragment not in bounded_capture:
            raise AssertionError(f"the bounded fixture capture is missing: {fragment}")
    if any(forbidden in bounded_capture for forbidden in ("capture_output=True", ".communicate(")):
        raise AssertionError("fixture diagnostic capture must remain hard-bounded in flight")
    if not (
        bounded_capture.index("process.terminate()")
        < bounded_capture.index("process.kill()")
        < bounded_capture.rindex("process.wait(timeout=_FIXTURE_DIAGNOSTIC_REAP_SECONDS)")
    ):
        raise AssertionError("fixture diagnostic terminate/kill/reap ordering has drifted")
    bounded_fixture_build = workflow.split("def _bounded_suppressed_fixture_build(", maxsplit=1)[
        1
    ].split("def _build_current_fixture_image(", maxsplit=1)[0]
    fixture_build = workflow.split("def _build_current_fixture_image(", maxsplit=1)[1].split(
        "class _FixtureDiagnosticRunner", maxsplit=1
    )[0]
    for fragment in (
        'profiles=("tools",)',
        'trailing=("build", "local-bootstrap")',
        "return _bounded_suppressed_fixture_build(command)",
    ):
        if fragment not in fixture_build:
            raise AssertionError(f"the exact local-bootstrap fixture build is missing: {fragment}")
    for fragment in (
        "except subprocess.TimeoutExpired:",
        "except BaseException:",
        "process.terminate()",
        "process.kill()",
        "process.wait(timeout=_FIXTURE_DIAGNOSTIC_REAP_SECONDS)",
        "outcome_known = process is None",
        "return _FixtureBuildOutcome(",
    ):
        if fragment not in bounded_fixture_build:
            raise AssertionError(f"the bounded fixture build evidence is missing: {fragment}")
    if any(
        forbidden in bounded_fixture_build for forbidden in ("capture_output=True", ".communicate(")
    ):
        raise AssertionError("the fixture build must suppress output without buffering it")
    fixture_container = workflow.split("def _fixture_container_snapshot(", maxsplit=1)[1].split(
        "class _FixtureDiagnosticRunner", maxsplit=1
    )[0]
    for fragment in (
        '_FIXTURE_DIAGNOSTIC_CONTAINER_NAME = "datariver-gateway-auth-parity-require-absent"',
        '"name=^/{_FIXTURE_DIAGNOSTIC_CONTAINER_NAME}$"',
        '"datariver.fixture.contract"',
        '"datariver.fixture.operation"',
        'if contract != FIXTURE_CONTRACT or operation != "REQUIRE_ABSENT":',
        '"docker",\n            "container",\n            "stop",',
        '"docker", "container", "rm", _FIXTURE_DIAGNOSTIC_CONTAINER_NAME',
        "if snapshot in {_FixtureContainerState.FOREIGN, _FixtureContainerState.UNKNOWN}:",
        "execution.container_stop_attempts += 1",
        "execution.container_remove_attempts += 1",
        "_record_fixture_container_residual(execution, _fixture_container_snapshot())",
    ):
        if fragment not in workflow and fragment not in fixture_container:
            raise AssertionError(f"the exact fixture-container lifecycle is missing: {fragment}")
    if any(
        forbidden in fixture_container
        for forbidden in ("--force", "container prune", "system prune", '"docker", "rm"')
    ):
        raise AssertionError("fixture cleanup must target only the exact reviewed one-off")
    execution_evidence = workflow.split("class FixtureDiagnosticExecutionEvidence:", maxsplit=1)[
        1
    ].split("class _FixtureDiagnosticCapacityExecutor:", maxsplit=1)[0]
    for fragment in (
        "cache_action_count_known: bool",
        "cache_action_count: int | None",
        "cache_action_succeeded: bool",
        "cache_action_outcome_known: bool",
        "build_attempted: bool",
        "build_succeeded: bool",
        "build_outcome_known: bool",
        "builder_idle_known: bool",
        "builder_idle: bool",
        "container_attempted: bool",
        "container_stop_attempts: int",
        "container_remove_attempts: int",
        "container_cleanup_known: bool",
        "container_cleanup_required: bool",
        "container_residual_known: bool",
        "container_residual_count: int | None",
        "def container_cleanup_proven(self) -> bool:",
        "self.container_attempted",
        "self.container_cleanup_known",
        "not self.container_cleanup_required",
        "self.container_residual_known",
        "self.container_residual_count == 0",
        "business_mutation_count: int = 0",
        "data_mutation_count: int = 0",
        "identity_mutation_count: int = 0",
        "topology_mutation_count: int = 0",
        "state_mutation_count: int = 0",
        "push_count: int = 0",
        "retry_count: int = 0",
        "value != 0",
        "FixtureDiagnosticExecutionClassification.OPERATOR_REVIEW_REQUIRED",
    ):
        if fragment not in execution_evidence:
            raise AssertionError(f"the outer fixture execution evidence is missing: {fragment}")
    execution_output = workflow.split("def format_fixture_diagnostic_execution_line(", maxsplit=1)[
        1
    ].split("class _FixtureDiagnosticCapacityExecutor:", maxsplit=1)[0]
    exact_execution_output_keys = (
        "build_attempted",
        "build_outcome_known",
        "build_succeeded",
        "builder_idle",
        "builder_idle_known",
        "business_mutation_count",
        "cache_action_count",
        "cache_action_count_known",
        "cache_action_outcome_known",
        "cache_action_succeeded",
        "classification",
        "container_attempted",
        "container_cleanup_known",
        "container_cleanup_required",
        "container_remove_attempts",
        "container_residual_count",
        "container_residual_known",
        "container_stop_attempts",
        "data_mutation_count",
        "identity_mutation_count",
        "operation",
        "predicate",
        "push_count",
        "retry_count",
        "state_mutation_count",
        "topology_mutation_count",
    )
    output_key_matches = tuple(
        sorted(
            set(
                re.findall(
                    r'^\s+"([a-z_]+)": evidence\.',
                    execution_output,
                    flags=re.MULTILINE,
                )
            )
        )
    )
    if output_key_matches != tuple(sorted(exact_execution_output_keys)):
        raise AssertionError("the outer fixture execution output allowlist has drifted")
    host_output = workflow.split("def format_host_environment_preflight_line(", maxsplit=1)[
        1
    ].split("def format_build_capacity_preflight_line(", maxsplit=1)[0]
    host_output_keys = tuple(
        re.findall(
            r'^\s{12}"([a-z_]+)": evidence\.',
            host_output,
            flags=re.MULTILINE,
        )
    )
    if host_output_keys != (
        "classification",
        "mutation_count",
        "phase",
        "predicate",
        "retry_count",
    ):
        raise AssertionError("the host-environment output allowlist has drifted")
    capacity_output = workflow.split("def format_build_capacity_preflight_line(", maxsplit=1)[
        1
    ].split("def _host_environment_preflight_failure(", maxsplit=1)[0]
    capacity_output_keys = tuple(
        re.findall(
            r'^\s{8}"([a-z_]+)": evidence\.',
            capacity_output,
            flags=re.MULTILINE,
        )
    )
    if capacity_output_keys != (
        "build_count",
        "builder_selection_known",
        "cache_action_count",
        "classification",
        "container_count",
        "mutation_count",
        "node_schema_known",
        "phase",
        "predicate",
        "retry_count",
    ):
        raise AssertionError("the build-capacity output allowlist has drifted")
    if not (
        "if evidence.builder_selection_known:" in capacity_output
        and 'fields["builder_selection_predicate"] = evidence.builder_selection_predicate.value'
        in capacity_output
        and capacity_output.count('"builder_selection_predicate"') == 1
        and '"builder_selection_predicate":' not in capacity_output
    ):
        raise AssertionError("the optional builder-selection output contract has drifted")
    if not (
        "if evidence.node_schema_known:" in capacity_output
        and 'fields["node_schema_predicate"] = evidence.node_schema_predicate.value'
        in capacity_output
        and capacity_output.count('"node_schema_predicate"') == 1
        and '"node_schema_predicate":' not in capacity_output
    ):
        raise AssertionError("the optional node-schema output contract has drifted")
    host_functions = [
        node
        for node in workflow_syntax.body
        if isinstance(node, ast.FunctionDef)
        and node.name
        in {
            "_host_environment_preflight_under_lock",
            "_host_environment_preflight_diagnostic",
        }
    ]
    if len(host_functions) != 2:
        raise AssertionError("the host-environment preflight functions must remain unique")
    host_preflight = workflow.split(
        "def _host_environment_preflight_under_lock() -> _HostEnvironmentPreflightResult:",
        maxsplit=1,
    )[1].split("def _host_environment_preflight_diagnostic()", maxsplit=1)[0]
    host_order = tuple(
        host_preflight.index(fragment)
        for fragment in (
            'load_applied_state(state_path(ROOT, "mac-development"))',
            'if state.profile != "mac-development":',
            'if state.deployment_mode != "build":',
            "if state.local_gateway:",
            "if state.local_graph:",
            "env_file = _resolve_repo_path(state.env_file)",
            'require_regular_file(env_file, label="Environment file")',
            "environment_values = read_env_values(env_file)",
            "environment_fingerprint = environment_key_hashes(environment_values)",
            "if environment_fingerprint != state.environment_key_hashes:",
            "files = _compose_files(state, release_override=None)",
            'if files != (ROOT / "compose.yaml", ROOT / "compose.identity.yaml"):',
            "predicate=HostEnvironmentPreflightPredicate.PASS",
        )
    )
    if host_order != tuple(sorted(host_order)):
        raise AssertionError("the host-environment canonical preflight order has drifted")
    if "except BaseException:" in host_preflight:
        raise AssertionError("step-local host-environment failures must not absorb interrupts")
    for forbidden in (
        "_fixture_diagnostic_source_is_clean",
        "current_fixture_source_sha256",
        "_preflight_build_capacity",
        "governed_compose_build_capacity",
        "_require_idle_builder",
        "require_no_active_builds",
        "_build_current_fixture_image",
        "_ComposeGatewayAuthParityFixture",
        "_bounded_fixture_diagnostic_process",
        "_gateway_auth_parity_session",
        "_read_gateway_admin_password",
        "KeycloakGatewayAuthParityIdentity",
        "_apply_topology_reconciliation",
        "write_applied_state",
        "subprocess.",
    ):
        if forbidden in host_preflight:
            raise AssertionError(
                f"the host-environment phase crossed a forbidden later boundary: {forbidden}"
            )
    host_operator = workflow.split(
        "def _host_environment_preflight_diagnostic() -> HostEnvironmentPreflightEvidence:",
        maxsplit=1,
    )[1].split("def _build_capacity_preflight_failure(", maxsplit=1)[0]
    if host_operator.count("except BaseException:") != 1 or not (
        host_operator.index("with exclusive_docker_workflow_lock(ROOT):")
        < host_operator.index("result = _host_environment_preflight_under_lock()")
        < host_operator.index("except BaseException:")
        < host_operator.index(
            "classification=HostEnvironmentPreflightClassification.OPERATOR_REVIEW_REQUIRED"
        )
        < host_operator.index("predicate=HostEnvironmentPreflightPredicate.UNKNOWN")
    ):
        raise AssertionError("the host-environment lock/finalization boundary has drifted")
    capacity_operator = workflow.split("def _build_capacity_preflight_under_lock(", maxsplit=1)[
        1
    ].split("def _fixture_require_absent_diagnostic()", maxsplit=1)[0]
    capacity_operator_order = tuple(
        capacity_operator.index(fragment)
        for fragment in (
            "preflight = _host_environment_preflight_under_lock()",
            "source_state = _fixture_diagnostic_source_state()",
            "source_sha256 = current_fixture_source_sha256()",
            "phase_recorder = DockerCapacityPhaseRecorder()",
            "command_executor = _BuildCapacityPreflightExecutor()",
            "selected_builder = _preflight_build_capacity(",
            "mode=DockerCapacityMode.MEASURE_ONLY",
            "if not _fixture_diagnostic_source_is_stable(source_sha256):",
            "_require_idle_builder(",
            "phase_recorder.mark(BuildCapacityPreflightPredicate.PASS)",
        )
    )
    if capacity_operator_order != tuple(sorted(capacity_operator_order)):
        raise AssertionError("the build-capacity diagnostic phase order has drifted")
    review_required = workflow.split("def _build_capacity_preflight_review_required(", maxsplit=1)[
        1
    ].split("def _fixture_diagnostic_source_is_stable(", maxsplit=1)[0]
    review_order = tuple(
        review_required.index(fragment)
        for fragment in (
            "preserve_selection_failure = builder_selection_recorder.known",
            "builder_selection_recorder.predicate is not BuilderSelectionPredicate.PASS",
            "classification=BuildCapacityPreflightClassification.OPERATOR_REVIEW_REQUIRED",
            "BuildCapacityPreflightPredicate.BUILDER_SELECTION",
            "if preserve_selection_failure",
            "else BuildCapacityPreflightPredicate.UNKNOWN",
        )
    )
    if review_order != tuple(sorted(review_order)):
        raise AssertionError("the simultaneous builder/outer failure evidence order has drifted")
    for fragment in (
        'selected_build_services=("local-bootstrap",)',
        "executor=command_executor",
        "phase_recorder=phase_recorder",
        "builder_selection_recorder=builder_selection_recorder",
        "node_schema_recorder=node_schema_recorder",
        "except DockerCapacityMeasureOnlyStop:",
        "except DockerCapacityPhaseError as error:",
        "node_schema_recorder = NodeSchemaRecorder()",
        "node_schema_known=node_schema_recorder.known",
        "node_schema_recorder.predicate if node_schema_recorder.known else None",
    ):
        if fragment not in capacity_operator:
            raise AssertionError(f"the build-capacity diagnostic guard is missing: {fragment}")
    if (
        "del source_sha256" in capacity_operator
        or capacity_operator.count("_fixture_diagnostic_source_is_stable(source_sha256)") != 3
    ):
        raise AssertionError("the build-capacity source identity is not retained and rechecked")
    action_required = capacity_operator.split("except DockerCapacityMeasureOnlyStop:", maxsplit=1)[
        1
    ].split("except DockerCapacityPhaseError as error:", maxsplit=1)[0]
    if not (
        action_required.index("_fixture_diagnostic_source_is_stable(source_sha256)")
        < action_required.index("BuildCapacityPreflightPredicate.CACHE_ACTION_REQUIRED")
    ):
        raise AssertionError("cache-action-required evidence precedes the source-stability proof")
    for forbidden in (
        "_build_current_fixture_image",
        "_ComposeGatewayAuthParityFixture",
        "_bounded_fixture_diagnostic_process",
        "_gateway_auth_parity_session",
        "_read_gateway_admin_password",
        "KeycloakGatewayAuthParityIdentity",
        "_apply_topology_reconciliation",
        "write_applied_state",
        "DockerCapacityError" + "(" + "str(",
    ):
        if forbidden in capacity_operator:
            raise AssertionError(
                f"the build-capacity phase crossed a forbidden boundary: {forbidden}"
            )
    preflight_executor = workflow.split("class _BuildCapacityPreflightExecutor:", maxsplit=1)[
        1
    ].split("def _bounded_fixture_diagnostic_process(", maxsplit=1)[0]
    exact_help = 'arguments == ("docker", "buildx", "prune", "--help")'
    prune_prefix = 'arguments[:3] == ("docker", "buildx", "prune")'
    if not (
        exact_help in preflight_executor
        and prune_prefix in preflight_executor
        and preflight_executor.index(exact_help) < preflight_executor.index(prune_prefix)
        and "BUILD_CAPACITY_PREFLIGHT_MUTATION_FORBIDDEN" in preflight_executor
    ):
        raise AssertionError("the build-capacity executor must allow help and refuse every prune")
    source_state = workflow.split("def _fixture_diagnostic_source_state(", maxsplit=1)[1].split(
        "def _fixed_diagnostic_stream(", maxsplit=1
    )[0]
    for fragment in (
        "result is FixtureDiagnosticPredicate.UNKNOWN",
        "return _FixtureSourceCleanState.UNKNOWN",
        "return _FixtureSourceCleanState.INVALID",
        "return _FixtureSourceCleanState.DIRTY",
        "return _FixtureSourceCleanState.CLEAN",
        "return _fixture_diagnostic_source_state() is _FixtureSourceCleanState.CLEAN",
    ):
        if fragment not in source_state:
            raise AssertionError(f"the structured source-clean proof is missing: {fragment}")
    capacity_recorder = workflow.split("class _FixtureDiagnosticCapacityExecutor:", maxsplit=1)[
        1
    ].split("def _bounded_fixture_diagnostic_process(", maxsplit=1)[0]
    for fragment in (
        'arguments[:3] == ("docker", "buildx", "prune")',
        "self.action_count = 1",
        "self.action_succeeded = False",
        "self.action_outcome_known = False",
        "self.action_succeeded = True",
        "self.action_outcome_known = True",
    ):
        if fragment not in capacity_recorder:
            raise AssertionError(f"the cache action recorder is missing: {fragment}")
    operator_diagnostic = workflow.split(
        "def _fixture_require_absent_diagnostic() -> FixtureDiagnosticExecutionEvidence:",
        maxsplit=1,
    )[1].split("def main() -> int:", maxsplit=1)[0]
    diagnostic_order = tuple(
        operator_diagnostic.index(fragment)
        for fragment in (
            "with exclusive_docker_workflow_lock(ROOT) as capacity_lock:",
            "preflight = _host_environment_preflight_under_lock()",
            "if not _fixture_diagnostic_source_is_clean():",
            "source_sha256 = current_fixture_source_sha256()",
            "selected_builder = _preflight_build_capacity(",
            "_require_idle_builder(selected_builder, capacity_lock)",
            "build_outcome = _build_current_fixture_image(",
            "_ComposeGatewayAuthParityFixture(",
            "fixture.diagnose_require_absent()",
        )
    )
    if diagnostic_order != tuple(sorted(diagnostic_order)):
        raise AssertionError("the fixture diagnostic lock/provenance/build/query order has drifted")
    if operator_diagnostic.count("_require_idle_builder(selected_builder, capacity_lock)") != 2:
        raise AssertionError(
            "the fixture diagnostic must prove builder idle before and after build"
        )
    if operator_diagnostic.count("_fixture_diagnostic_source_is_clean()") != 2:
        raise AssertionError(
            "the fixture diagnostic must prove clean source before and after build"
        )
    if operator_diagnostic.count("current_fixture_source_sha256()") != 2:
        raise AssertionError("the fixture source fingerprint must be stable around the exact build")
    post_build = operator_diagnostic.split("build_outcome = _FixtureBuildOutcome(", maxsplit=1)[
        1
    ].split("if (", maxsplit=1)[0]
    if not (
        post_build.index("try:")
        < post_build.index("_build_current_fixture_image(")
        < post_build.index("finally:")
        < post_build.index("_require_idle_builder(selected_builder, capacity_lock)")
    ):
        raise AssertionError("post-build idle proof must remain unconditional under the lock")
    require_absent_execution = workflow_fixture.split(
        'if operation == "require-absent":', maxsplit=1
    )[1].split("\n\n        try:\n            result = subprocess.run", maxsplit=1)[0]
    for fragment in (
        "prestate = _fixture_container_snapshot()",
        "if prestate is not _FixtureContainerState.ABSENT:",
        "self._execution_state.container_attempted = True",
        "_bounded_fixture_diagnostic_process(",
        "finally:",
        "_cleanup_fixture_container(self._execution_state)",
        "evidence.predicate is FixtureDiagnosticPredicate.PASS",
        "and not self._execution_state.container_cleanup_proven",
        "return self._diagnostic_envelope(FixtureDiagnosticPredicate.UNKNOWN)",
    ):
        if fragment not in require_absent_execution:
            raise AssertionError(f"the exact one-off execution guard is missing: {fragment}")
    if not (
        require_absent_execution.index("prestate = _fixture_container_snapshot()")
        < require_absent_execution.index("self._execution_state.container_attempted = True")
        < require_absent_execution.index("_bounded_fixture_diagnostic_process(")
        < require_absent_execution.index("finally:")
        < require_absent_execution.index("_cleanup_fixture_container(self._execution_state)")
        < require_absent_execution.index("evidence.predicate is FixtureDiagnosticPredicate.PASS")
        < require_absent_execution.index("and not self._execution_state.container_cleanup_proven")
        < require_absent_execution.rindex("return evidence")
    ):
        raise AssertionError("the one-off preabsence, attempt and cleanup order has drifted")
    parity_session_prepare = (
        probe.split("class GatewayAuthParitySession:", maxsplit=1)[1]
        .split("    def enable(self) -> None:", maxsplit=1)[0]
        .split("    def prepare(self) -> None:", maxsplit=1)[1]
    )
    if not (
        parity_session_prepare.index("self._fixture.require_absent()")
        < parity_session_prepare.index("self._mutated = True")
        < parity_session_prepare.index("self._identity.create_disabled_fixture()")
        < parity_session_prepare.index("self._fixture.prepare(")
    ):
        raise AssertionError("fixture cleanup proof must precede every parity mutation")
    for forbidden in (
        "_gateway_auth_parity_session(",
        "_apply_topology_reconciliation(",
        "write_applied_state(",
        ".prepare(",
        ".enable(",
        "git push",
    ):
        if forbidden in operator_diagnostic:
            raise AssertionError("the fixture diagnostic must stop before mutation")
    workflow_main = workflow.split("def main() -> int:", maxsplit=1)[1]
    if not (
        workflow_main.index("diagnostic_equals_arguments = tuple(")
        < workflow_main.index("argument.startswith(_DIAGNOSTIC_PHASE_EQUALS_PREFIX)")
        < workflow_main.index("if len(diagnostic_equals_arguments) > 1")
        < workflow_main.index("print(_fixed_invalid_diagnostic_line())")
        < workflow_main.index("if diagnostic_arguments == _BUILD_CAPACITY_PREFLIGHT_ARGUMENTS:")
        < workflow_main.index(
            "diagnostic_equals_argument.startswith(_BUILD_CAPACITY_PREFLIGHT_EQUALS_PREFIX)"
        )
        < workflow_main.index(
            "diagnostic_equals_argument.startswith(_HOST_ENVIRONMENT_PREFLIGHT_EQUALS_PREFIX)"
        )
        < workflow_main.index("if diagnostic_arguments == _HOST_ENVIRONMENT_PREFLIGHT_ARGUMENTS:")
        < workflow_main.index("if len(sys.argv) == 1:")
        < workflow_main.index("args = parse_args()")
    ):
        raise AssertionError("the fixed diagnostics must precede normal argument parsing")
    for forbidden in (
        '"--diagnostic-phase=BUILD_CAPACITY_PREFLIGHT" in diagnostic_arguments',
        '"--diagnostic-phase=HOST_ENVIRONMENT_PREFLIGHT" in diagnostic_arguments',
    ):
        if forbidden in workflow_main:
            raise AssertionError("diagnostic equals-form handling regressed to exact-only matching")
    invalid_diagnostic = workflow.split("def _fixed_invalid_diagnostic_line() -> str:", maxsplit=1)[
        1
    ].split("def _host_environment_preflight_failure(", maxsplit=1)[0]
    for fragment in (
        '"classification": "REJECTED"',
        '"phase": "INVALID_DIAGNOSTIC"',
        '"predicate": "UNKNOWN"',
        '"mutation_count": 0',
        '"retry_count": 0',
    ):
        if fragment not in invalid_diagnostic:
            raise AssertionError(f"the invalid-diagnostic evidence is missing: {fragment}")
    for fragment in (
        '_BUILD_CAPACITY_PREFLIGHT_ARGUMENTS = (\n    "--diagnostic-phase",\n'
        '    "BUILD_CAPACITY_PREFLIGHT",\n)',
        "capacity_evidence = _build_capacity_preflight_diagnostic()",
        "print(format_build_capacity_preflight_line(capacity_evidence))",
        '_HOST_ENVIRONMENT_PREFLIGHT_ARGUMENTS = (\n    "--diagnostic-phase",\n'
        '    "HOST_ENVIRONMENT_PREFLIGHT",\n)',
        "environment_evidence = _host_environment_preflight_diagnostic()",
        "print(format_host_environment_preflight_line(environment_evidence))",
    ):
        if fragment not in workflow:
            raise AssertionError(f"the fixed host-environment argv is missing: {fragment}")
    for test_name in (
        "test_host_environment_preflight_is_locked_ordered_and_stops_before_later_paths",
        "test_host_environment_preflight_classifies_each_boundary_without_raw",
        "test_host_environment_preflight_rejects_noncanonical_compose_selection",
        "test_host_environment_preflight_interrupt_at_step_is_fixed_and_nonleaking",
        "test_fixture_diagnostic_preflight_interrupt_is_unknown_before_later_actions",
        "test_host_environment_preflight_lock_exit_failure_downgrades_pass",
        "test_host_environment_preflight_main_accepts_only_exact_phase_argv",
        "test_build_capacity_preflight_is_locked_ordered_read_only_and_value_free",
        "test_build_capacity_preflight_preserves_structured_first_failure",
        "test_build_capacity_preflight_classifies_host_source_and_argument_boundaries",
        "test_build_capacity_measure_only_action_required_never_runs_prune_or_later_paths",
        "test_build_capacity_executor_forwards_only_exact_help_before_action_required",
        "test_build_capacity_executor_rejects_every_nonhelp_prune_tuple",
        "test_build_capacity_source_drift_is_review_required_before_trusted_result",
        "test_build_capacity_nested_git_interrupt_is_unknown_before_capacity",
        "test_build_capacity_preflight_interrupt_is_unknown_and_stops_later_calls",
        "test_build_capacity_preflight_main_accepts_only_exact_phase_argv",
        "test_diagnostic_phase_equals_form_is_fixed_before_argparse_and_lock",
        "test_diagnostic_phase_every_equals_prefix_is_fixed_without_raw_or_calls",
    ):
        if f"def {test_name}(" not in platform_tests:
            raise AssertionError(f"the host-environment negative is missing: {test_name}")
    for test_name, source in (
        (
            "test_require_absent_diagnostic_envelope_is_closed_bounded_and_value_free",
            fixture_tests,
        ),
        (
            "test_require_absent_diagnostic_parser_classifies_protocol_defects_without_raw",
            fixture_tests,
        ),
        ("test_sql_absence_query_failure_is_fixed_select_only_and_nonleaking", fixture_tests),
        ("test_require_absent_child_emits_one_fixed_line_and_never_raw_failure", fixture_tests),
        (
            "test_require_absent_child_rejects_invalid_private_request_as_fixed_input_protocol",
            fixture_tests,
        ),
        ("test_stale_fixture_source_provenance_stops_before_repository_query", fixture_tests),
        (
            "test_fixture_source_provenance_does_not_absorb_file_boundary_interrupts",
            fixture_tests,
        ),
        (
            "test_gateway_fixture_require_absent_propagates_each_fixed_child_predicate",
            platform_tests,
        ),
        (
            "test_gateway_fixture_require_absent_process_failures_are_fixed_and_not_retried",
            platform_tests,
        ),
        (
            "test_fixture_diagnostic_dual_stream_capture_is_capped_while_child_runs",
            platform_tests,
        ),
        (
            "test_fixture_diagnostic_timeout_kills_child_that_ignores_terminate",
            platform_tests,
        ),
        (
            "test_fixture_diagnostic_spawn_and_reap_failures_are_fixed_and_nonleaking",
            platform_tests,
        ),
        (
            "test_fixture_diagnostic_provenance_failure_stops_before_ephemeral_query",
            platform_tests,
        ),
        (
            "test_fixture_diagnostic_build_is_exact_local_bootstrap_action_once",
            platform_tests,
        ),
        (
            "test_fixture_diagnostic_capacity_failure_retains_cache_action_evidence",
            platform_tests,
        ),
        (
            "test_fixture_diagnostic_build_process_outcome_and_reap_are_bounded",
            platform_tests,
        ),
        (
            "test_fixture_diagnostic_container_snapshot_requires_exact_name_and_labels",
            platform_tests,
        ),
        (
            "test_fixture_diagnostic_ambiguous_create_cleans_only_exact_owned_container",
            platform_tests,
        ),
        (
            "test_fixture_diagnostic_ambiguous_create_never_touches_unowned_or_unknown_container",
            platform_tests,
        ),
        (
            "test_fixture_diagnostic_lock_exit_failure_preserves_all_attempted_actions",
            platform_tests,
        ),
        (
            "test_fixture_diagnostic_child_pass_requires_proven_container_cleanup",
            platform_tests,
        ),
        (
            "test_fixture_diagnostic_child_pass_cleanup_baseexception_fails_closed",
            platform_tests,
        ),
        (
            "test_fixture_diagnostic_nonpass_first_defect_survives_cleanup_failure",
            platform_tests,
        ),
        (
            "test_require_absent_cleanup_unknown_stops_before_identity_or_fixture_mutation",
            probe_tests,
        ),
        (
            "test_no_argument_fixture_diagnostic_holds_lock_and_stops_after_require_absent",
            platform_tests,
        ),
        (
            "test_require_absent_diagnostic_failure_is_preserved_before_fixture_mutation",
            probe_tests,
        ),
    ):
        if test_name not in source:
            raise AssertionError(f"the fixture diagnostic negative is missing: {test_name}")
    probe_diagnostic_syntax = ast.parse(probe, filename=probe_path.as_posix())
    probe_assignments = {
        statement.targets[0].id: statement.value
        for statement in probe_diagnostic_syntax.body
        if isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
    }
    fixture_failure_values = probe_assignments.get(
        "_FIXTURE_REQUIRE_ABSENT_FAILURE_CLASSIFICATIONS"
    )
    first_failure_values = probe_assignments.get("_FIRST_FAILURE_CLASSIFICATIONS")
    if (
        not isinstance(fixture_failure_values, ast.Call)
        or not isinstance(fixture_failure_values.func, ast.Name)
        or fixture_failure_values.func.id != "frozenset"
        or not isinstance(first_failure_values, ast.BinOp)
        or not isinstance(first_failure_values.op, ast.BitOr)
        or not isinstance(first_failure_values.right, ast.Name)
        or first_failure_values.right.id != "_FIXTURE_REQUIRE_ABSENT_FAILURE_CLASSIFICATIONS"
        or "fixture_diagnostic_failure_classification(predicate)" not in probe
    ):
        raise AssertionError("fixture diagnostic failures must remain allowlisted first defects")
    cleanup_source = sql_repository.split("async def cleanup(", maxsplit=1)[1].split(
        "async def require_zero_residual(", maxsplit=1
    )[0]
    exact_rows = cleanup_source.index(
        "rows = await self._exact_rows(identities, cleanup=True, allow_absent=True)"
    )
    alias_proof = cleanup_source.index("existing = await self._subjects(identities)")
    membership_proof = cleanup_source.index("membership_count = await self._session.scalar(")
    privilege_proof = cleanup_source.index(
        "privilege_residual_counts = await self._privilege_residual_counts(subject_ids)"
    )
    first_delete = cleanup_source.index("delete(WorkspaceMembershipModel)")
    if not exact_rows < alias_proof < membership_proof < privilege_proof < first_delete:
        raise AssertionError("gateway parity SQL cleanup must lock then re-prove before deletion")
    production_identity = probe.split("class KeycloakGatewayAuthParityIdentity:", maxsplit=1)[
        1
    ].split("class GatewayAuthParityTraffic:", maxsplit=1)[0]
    production_cleanup = production_identity.split(
        "def require_invariants_and_zero_residual(self) -> None:", maxsplit=1
    )[1].split("def release_without_mutation(self) -> None:", maxsplit=1)[0]
    for fragment in (
        "self._production_contract_fingerprint() != self._production_fingerprint",
        "except BaseException:",
        'raise GatewayAuthParityError("GATEWAY_AUTH_PARITY_CLEANUP_REQUIRED") from None',
    ):
        if fragment not in production_cleanup:
            raise AssertionError(
                "production Web cleanup invariant failure must remain fixed and nonleaking"
            )

    probe_syntax = ast.parse(probe, filename=probe_path.as_posix())
    predicate_classes = [
        node
        for node in probe_syntax.body
        if isinstance(node, ast.ClassDef) and node.name == "ProductionWebInvariantPredicate"
    ]
    if len(predicate_classes) != 1:
        raise AssertionError("production Web diagnostic predicate enum is missing or duplicated")
    predicate_members = tuple(
        (statement.targets[0].id, ast.literal_eval(statement.value))
        for statement in predicate_classes[0].body
        if isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
    )
    exact_predicates = (
        "CLIENT_MATCH_COUNT",
        "CLIENT_SEARCH_SHAPE",
        "CLIENT_UUID",
        "CLIENT_DOCUMENT_IDENTITY",
        "CLIENT_STRING_SHAPE",
        "CLIENT_BOOLEAN_SHAPE",
        "CLIENT_AUTHORIZATION_SERVICES_POLICY",
        "CLIENT_OPTIONAL_URL_SHAPE",
        "CLIENT_LIST_SHAPE",
        "CLIENT_MAPPING_SHAPE",
        "MAPPER_INVENTORY_SHAPE",
        "MAPPER_COUNT",
        "MAPPER_UUID",
        "MAPPER_NAME",
        "MAPPER_PROTOCOL",
        "MAPPER_TYPE",
        "MAPPER_CONSENT_SHAPE",
        "MAPPER_ID_DUPLICATE",
        "MAPPER_NAME_DUPLICATE",
        "MAPPER_CONFIG_SHAPE",
        "ADMIN_BOUNDARY_UNAVAILABLE",
        "UNKNOWN",
        "PASS",
    )
    if predicate_members != tuple((value, value) for value in exact_predicates):
        raise AssertionError("production Web diagnostic predicate enum has drifted")
    boolean_field_classes = [
        node
        for node in probe_syntax.body
        if isinstance(node, ast.ClassDef) and node.name == "ProductionWebBooleanField"
    ]
    boolean_status_classes = [
        node
        for node in probe_syntax.body
        if isinstance(node, ast.ClassDef) and node.name == "ProductionWebBooleanFieldStatus"
    ]
    if len(boolean_field_classes) != 1 or len(boolean_status_classes) != 1:
        raise AssertionError("production Web boolean field enums are missing or duplicated")
    boolean_field_members = tuple(
        (statement.targets[0].id, ast.literal_eval(statement.value))
        for statement in boolean_field_classes[0].body
        if isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
    )
    exact_boolean_fields = (
        ("ENABLED", "enabled"),
        ("PUBLIC_CLIENT", "publicClient"),
        ("BEARER_ONLY", "bearerOnly"),
        ("SURROGATE_AUTH_REQUIRED", "surrogateAuthRequired"),
        ("CONSENT_REQUIRED", "consentRequired"),
        ("STANDARD_FLOW_ENABLED", "standardFlowEnabled"),
        ("DIRECT_ACCESS_GRANTS_ENABLED", "directAccessGrantsEnabled"),
        ("IMPLICIT_FLOW_ENABLED", "implicitFlowEnabled"),
        ("SERVICE_ACCOUNTS_ENABLED", "serviceAccountsEnabled"),
        ("AUTHORIZATION_SERVICES_ENABLED", "authorizationServicesEnabled"),
        ("FULL_SCOPE_ALLOWED", "fullScopeAllowed"),
        ("FRONTCHANNEL_LOGOUT", "frontchannelLogout"),
        ("ALWAYS_DISPLAY_IN_CONSOLE", "alwaysDisplayInConsole"),
    )
    if boolean_field_members != exact_boolean_fields:
        raise AssertionError("production Web boolean field enum order has drifted")
    boolean_status_members = tuple(
        (statement.targets[0].id, ast.literal_eval(statement.value))
        for statement in boolean_status_classes[0].body
        if isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
    )
    if boolean_status_members != (
        ("PRESENT_BOOL", "PRESENT_BOOL"),
        ("MISSING", "MISSING"),
        ("NON_BOOL", "NON_BOOL"),
    ):
        raise AssertionError("production Web boolean status enum has drifted")
    boolean_field_assignments = [
        node
        for node in probe_syntax.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_PRODUCTION_WEB_BOOLEAN_FIELDS"
            for target in node.targets
        )
    ]
    if (
        len(boolean_field_assignments) != 1
        or ast.unparse(boolean_field_assignments[0].value)
        != "tuple((field.value for field in ProductionWebBooleanField))"
    ):
        raise AssertionError("production Web boolean tuple must derive from the exact enum")
    omission_allowlist_assignments = [
        node
        for node in probe_syntax.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "_KEYCLOAK_26_7_OMITTED_FALSE_BOOLEAN_FIELDS"
            for target in node.targets
        )
    ]
    if (
        len(omission_allowlist_assignments) != 1
        or ast.unparse(omission_allowlist_assignments[0].value)
        != "(ProductionWebBooleanField.AUTHORIZATION_SERVICES_ENABLED,)"
    ):
        raise AssertionError("Keycloak 26.7 may omit only the exact Authorization Services field")
    boolean_scanner = probe.split("def _production_web_boolean_field_statuses(", maxsplit=1)[
        1
    ].split("def _normalized_unique_strings(", maxsplit=1)[0]
    for fragment in (
        "for field in ProductionWebBooleanField:",
        "if field.value not in document:",
        "status = ProductionWebBooleanFieldStatus.MISSING",
        "elif type(document[field.value]) is bool:",
        "status = ProductionWebBooleanFieldStatus.PRESENT_BOOL",
        "status = ProductionWebBooleanFieldStatus.NON_BOOL",
        "return tuple(statuses)",
    ):
        if fragment not in boolean_scanner:
            raise AssertionError(f"production Web boolean full scan is missing: {fragment}")
    normalizer = probe.split("def _normalize_production_web_contract(", maxsplit=1)[1].split(
        "def _classify_production_web_contract(", maxsplit=1
    )[0]
    classifier_wrapper = probe.split("def _classify_production_web_contract(", maxsplit=1)[1].split(
        "def _bounded_response(", maxsplit=1
    )[0]
    production_fingerprint = production_identity.split(
        "def _production_contract_fingerprint(self) -> str:", maxsplit=1
    )[1].split("def classify_production_web_invariant(", maxsplit=1)[0]
    production_snapshot = production_identity.split(
        "def _production_contract_snapshot(self) -> _ProductionWebContractSnapshot:", maxsplit=1
    )[1].split("def _production_contract_fingerprint(", maxsplit=1)[0]
    production_diagnostic = production_identity.split(
        "def classify_production_web_invariant(", maxsplit=1
    )[1].split("def converge_web_authorization_services_disabled(", maxsplit=1)[0]
    if (
        "return _normalize_production_web_contract(" not in classifier_wrapper
        or "self.classify_production_web_invariant()" not in production_fingerprint
        or "evidence = _classify_production_web_contract(" not in production_snapshot
        or "return self._production_contract_snapshot().evidence" not in production_diagnostic
        or '"/admin/realms/datariver/clients"' not in production_snapshot
        or 'f"/admin/realms/datariver/clients/{client_uuid}/protocol-mappers/models"'
        not in production_snapshot
        or "ProductionWebInvariantPredicate.CLIENT_MATCH_COUNT" not in normalizer
        or normalizer.count("_production_web_boolean_field_statuses(normalized_selected)") != 1
        or "if boolean_missing_fields or boolean_non_bool_fields:" not in normalizer
        or "normalized_selected = dict(selected)" not in normalizer
        or "field not in _KEYCLOAK_26_7_OMITTED_FALSE_BOOLEAN_FIELDS" not in normalizer
        or "ProductionWebInvariantPredicate.CLIENT_AUTHORIZATION_SERVICES_POLICY" not in normalizer
        or "normalized_selected[authorization_services_field.value] = False" not in normalizer
        or "ProductionWebInvariantPredicate.MAPPER_CONFIG_SHAPE" not in normalizer
    ):
        raise AssertionError("production Web fingerprint and diagnostic must share one normalizer")
    boolean_scan = normalizer.index("_production_web_boolean_field_statuses(normalized_selected)")
    policy_guard = normalizer.index(
        "ProductionWebInvariantPredicate.CLIENT_AUTHORIZATION_SERVICES_POLICY"
    )
    mapper_read = normalizer.index("mapper_document = _production_response_document(")
    if not boolean_scan < policy_guard < mapper_read:
        raise AssertionError("Authorization Services policy must fail before mapper reads")
    for forbidden in (
        "normalized_selected.setdefault(",
        '.get("authorizationServicesEnabled", False)',
        ".get(authorization_services_field.value, False)",
    ):
        if forbidden in normalizer:
            raise AssertionError("provider boolean omission cannot use a wildcard default")
    for fragment in (
        "client_match_count_known=",
        "mapper_count_known=",
        "boolean_shape_known=",
        "boolean_missing_count=",
        "boolean_missing_fields=[",
        "boolean_non_bool_count=",
        "boolean_non_bool_fields=[",
        "mutation_count=0",
        "retry_count=0",
        "if evidence.client_match_count is not None:",
        "if evidence.mapper_count is not None:",
        "if evidence.boolean_shape_known:",
    ):
        if fragment not in probe:
            raise AssertionError(f"production Web sanitized evidence is missing: {fragment}")
    evidence_formatters = [
        node
        for node in probe_syntax.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "format_production_web_invariant_evidence"
    ]
    if len(evidence_formatters) != 1:
        raise AssertionError("production Web evidence formatter is missing or duplicated")
    formatted_prefixes = {
        node.values[0].value
        for node in ast.walk(evidence_formatters[0])
        if isinstance(node, ast.JoinedStr)
        and node.values
        and isinstance(node.values[0], ast.Constant)
        and isinstance(node.values[0].value, str)
    }
    if formatted_prefixes != {
        "predicate=",
        "client_match_count_known=",
        "client_match_count=",
        "mapper_count_known=",
        "mapper_count=",
        "boolean_shape_known=",
        "boolean_missing_count=",
        "boolean_missing_fields=[",
        "boolean_non_bool_count=",
        "boolean_non_bool_fields=[",
    }:
        raise AssertionError("production Web evidence dynamic output keys have drifted")
    for forbidden in (
        "fingerprint={",
        "client_uuid={",
        "redirectUris={",
        "webOrigins={",
        "protocolMappers={",
        "provider_field={",
        "provider_value={",
    ):
        if forbidden in probe:
            raise AssertionError("production Web diagnostic cannot format provider values")

    classifier_syntax = ast.parse(classifier, filename=classifier_path.as_posix())
    imported_modules = {
        node.module
        for node in classifier_syntax.body
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    if imported_modules != {
        "__future__",
        "docker_capacity",
        "pathlib",
        "platform_workflow",
        "probe_gateway_auth_parity",
        "workflow_update_restart",
    }:
        raise AssertionError("production Web classifier imports have drifted")
    classifier_calls = [node for node in ast.walk(classifier_syntax) if isinstance(node, ast.Call)]
    print_calls = [
        node
        for node in classifier_calls
        if isinstance(node.func, ast.Name) and node.func.id == "print"
    ]
    if len(print_calls) != 1:
        raise AssertionError("production Web classifier must have exactly one output call")
    forbidden_call_names = {
        "open",
        "write_applied_state",
        "capture_local_topology",
        "create_disabled_fixture",
        "cleanup_client",
        "cleanup_sessions_and_users",
    }
    forbidden_attributes = {"write", "write_text", "write_bytes", "unlink", "mkdir", "rmdir"}
    if any(
        (isinstance(call.func, ast.Name) and call.func.id in forbidden_call_names)
        or (isinstance(call.func, ast.Attribute) and call.func.attr in forbidden_attributes)
        for call in classifier_calls
    ):
        raise AssertionError("production Web classifier cannot persist or mutate state")
    for fragment in (
        'PROFILE = "mac-development"',
        'ENVIRONMENT_FILE = ".env.mac-development"',
        "SECRET_NAMES = TOPOLOGY_RECONCILIATION_SECRET_NAMES",
        "with exclusive_docker_workflow_lock(ROOT):",
        "_environment_file, keycloak_port = _mac_environment()",
        "with require_topology_reconciliation_secrets(ROOT) as guard:",
        "password = _read_gateway_admin_password(guard)",
        'base_url=f"http://127.0.0.1:{keycloak_port}"',
        'admin_username="datariver-bootstrap"',
        "return identity.classify_production_web_invariant()",
        "identity.release_without_mutation()",
        "print(format_production_web_invariant_evidence(evidence), flush=True)",
        "len(sys.argv) == 1",
        "boolean_missing_fields=None",
        "boolean_non_bool_fields=None",
    ):
        if fragment not in classifier:
            raise AssertionError(f"production Web classifier contract is missing: {fragment}")
    classifier_order = tuple(
        classifier.index(fragment)
        for fragment in (
            "with exclusive_docker_workflow_lock(ROOT):",
            "_environment_file, keycloak_port = _mac_environment()",
            "with require_topology_reconciliation_secrets(ROOT) as guard:",
            "password = _read_gateway_admin_password(guard)",
            "identity = KeycloakGatewayAuthParityIdentity(",
            "return identity.classify_production_web_invariant()",
            "identity.release_without_mutation()",
        )
    )
    if classifier_order != tuple(sorted(classifier_order)):
        raise AssertionError("production Web classifier lock/read/release order has drifted")
    admin_authentication = production_identity.split(
        "def _authenticate_admin(self) -> None:", maxsplit=1
    )[1].split("def _find(", maxsplit=1)[0]
    if (
        admin_authentication.count("self._request(") != 1
        or admin_authentication.count('"POST"') != 1
        or admin_authentication.count('"/realms/master/protocol/openid-connect/token"') != 1
        or production_snapshot.count("self._request(") != 3
        or production_snapshot.count('"GET"') != 3
    ):
        raise AssertionError("production Web diagnostic Admin request count has drifted")
    for forbidden in (
        "argparse",
        "subprocess",
        "create_disabled_fixture",
        "require_absent_and_capture_invariants",
        "authenticate_allow",
        "authenticate_deny",
        "cleanup_client",
        "cleanup_sessions_and_users",
        "write_applied_state",
        "capture_local_topology",
        "docker build",
        "docker compose",
        '"PUT"',
        '"DELETE"',
    ):
        if forbidden in classifier:
            raise AssertionError(
                f"production Web classifier mutation boundary drifted: {forbidden}"
            )

    if convergence_path.stat().st_mode & 0o111 == 0:
        raise AssertionError("the Web Authorization Services operator must remain executable")
    convergence_syntax = ast.parse(convergence, filename=convergence_path.as_posix())
    identity_classes = [
        node
        for node in probe_syntax.body
        if isinstance(node, ast.ClassDef) and node.name == "KeycloakGatewayAuthParityIdentity"
    ]
    if len(identity_classes) != 1:
        raise AssertionError("the fixed Keycloak identity class is missing or duplicated")
    convergence_status_classes = [
        node
        for node in probe_syntax.body
        if isinstance(node, ast.ClassDef) and node.name == "GatewayWebAuthorizationServicesStatus"
    ]
    convergence_classification_classes = [
        node
        for node in probe_syntax.body
        if isinstance(node, ast.ClassDef)
        and node.name == "GatewayWebAuthorizationServicesClassification"
    ]
    if len(convergence_status_classes) != 1 or len(convergence_classification_classes) != 1:
        raise AssertionError("the Web convergence evidence enums are missing or duplicated")

    def exact_enum_members(node: ast.ClassDef) -> tuple[tuple[str, object], ...]:
        return tuple(
            (statement.targets[0].id, ast.literal_eval(statement.value))
            for statement in node.body
            if isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        )

    if exact_enum_members(convergence_status_classes[0]) != (
        ("MISSING", "MISSING"),
        ("FALSE", "FALSE"),
        ("TRUE", "TRUE"),
        ("NON_BOOL", "NON_BOOL"),
        ("UNKNOWN", "UNKNOWN"),
    ) or exact_enum_members(convergence_classification_classes[0]) != (
        ("PASS", "PASS"),
        ("PRECONDITION_FAILED", "PRECONDITION_FAILED"),
        ("POSTCONDITION_FAILED", "POSTCONDITION_FAILED"),
        ("OPERATOR_REVIEW_REQUIRED", "OPERATOR_REVIEW_REQUIRED"),
        ("UNKNOWN", "UNKNOWN"),
    ):
        raise AssertionError("the Web convergence evidence enums have drifted")
    convergence_formatters = [
        node
        for node in probe_syntax.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "format_gateway_web_authorization_services_evidence"
    ]
    if len(convergence_formatters) != 1:
        raise AssertionError("the Web convergence evidence formatter is missing or duplicated")
    formatter_prefixes = {
        node.values[0].value
        for node in ast.walk(convergence_formatters[0])
        if isinstance(node, ast.JoinedStr)
        and node.values
        and isinstance(node.values[0], ast.Constant)
        and isinstance(node.values[0].value, str)
    }
    if formatter_prefixes != {
        "classification=",
        "predicate=",
        "pre_status=",
        "action_attempted=",
        "action_succeeded=",
        "mutation_outcome_known=",
        "post_status_known=",
        "post_status=",
        "fingerprint_equal_known=",
        "fingerprint_equal=",
        "admin_token_grant_attempts=",
        "admin_request_attempts=",
        "mutation_count=",
    } or "retry_count=0" not in {
        node.value
        for node in ast.walk(convergence_formatters[0])
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }:
        raise AssertionError("the Web convergence evidence output allowlist has drifted")
    convergence_methods = [
        node
        for node in identity_classes[0].body
        if isinstance(node, ast.FunctionDef)
        and node.name == "converge_web_authorization_services_disabled"
    ]
    if len(convergence_methods) != 1 or len(convergence_methods[0].args.args) != 1:
        raise AssertionError("the exact Web convergence method cannot accept operator input")
    update_calls = [
        node
        for node in ast.walk(convergence_methods[0])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "self"
        and node.func.attr == "_request"
    ]
    if len(update_calls) != 1:
        raise AssertionError("the exact Web convergence method must issue one Admin mutation")
    update_call = update_calls[0]
    update_keywords = {keyword.arg: keyword.value for keyword in update_call.keywords}
    expected_call = update_keywords.get("expected")
    update_body = update_keywords.get("json")
    if (
        len(update_call.args) != 2
        or ast.literal_eval(update_call.args[0]) != "PUT"
        or ast.unparse(update_call.args[1])
        != "f'/admin/realms/datariver/clients/{before.client_uuid}'"
        or not isinstance(expected_call, ast.Call)
        or ast.unparse(expected_call) != "frozenset({204})"
        or not isinstance(update_body, ast.Dict)
        or len(update_body.keys) != 1
        or ast.literal_eval(update_body.keys[0]) != "authorizationServicesEnabled"
        or ast.literal_eval(update_body.values[0]) is not False
        or set(update_keywords) != {"expected", "json"}
    ):
        raise AssertionError("the Web convergence PUT method/path/body/status has drifted")
    method_source = ast.get_source_segment(probe, convergence_methods[0]) or ""
    for fragment in (
        "before = self._production_contract_snapshot()",
        "before.evidence.predicate is not ProductionWebInvariantPredicate.PASS",
        "GatewayWebAuthorizationServicesStatus.MISSING",
        "GatewayWebAuthorizationServicesStatus.FALSE",
        "self._web_authorization_services_action_attempted = True",
        "self._web_authorization_services_action_succeeded = True",
        "except BaseException:",
        "after = self._production_contract_snapshot()",
        "after.client_uuid == before.client_uuid",
        "after.evidence.fingerprint == before.evidence.fingerprint",
        "action_succeeded=False",
        "mutation_outcome_known=not action_error",
        "mutation_count=1",
    ):
        if fragment not in method_source:
            raise AssertionError(f"the exact Web convergence guard is missing: {fragment}")
    action_marker = method_source.index("self._web_authorization_services_action_attempted = True")
    action_request = method_source.index("self._request(", action_marker)
    action_success = method_source.index("self._web_authorization_services_action_succeeded = True")
    post_proof = method_source.index("after = self._production_contract_snapshot()")
    if not action_marker < action_request < action_success < post_proof:
        raise AssertionError("the Web convergence monotonic action-state order has drifted")
    if method_source.count("after = self._production_contract_snapshot()") != 1:
        raise AssertionError("the Web convergence may perform only one post-action proof")

    convergence_imports = {
        node.module
        for node in convergence_syntax.body
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    if convergence_imports != {
        "__future__",
        "docker_capacity",
        "pathlib",
        "platform_workflow",
        "probe_gateway_auth_parity",
        "workflow_update_restart",
    }:
        raise AssertionError("the exact Web convergence operator imports have drifted")
    convergence_assignments: dict[str, list[ast.expr]] = {}
    for statement in convergence_syntax.body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target = statement.targets[0]
        if isinstance(target, ast.Name):
            convergence_assignments.setdefault(target.id, []).append(statement.value)
    for name, expected in (
        ("PROFILE", "mac-development"),
        ("ENVIRONMENT_FILE", ".env.mac-development"),
        ("KEYCLOAK_CONTAINER", "datariver-next-keycloak-1"),
        ("KEYCLOAK_IMAGE", "datariver-keycloak:26.7.0"),
        ("KEYCLOAK_BASE_IMAGE", pinned_keycloak),
    ):
        values = convergence_assignments.get(name, [])
        if len(values) != 1 or ast.literal_eval(values[0]) != expected:
            raise AssertionError(f"the exact Web convergence {name} literal has drifted")
    runtime_checks = [
        node
        for node in convergence_syntax.body
        if isinstance(node, ast.FunctionDef) and node.name == "_require_pinned_keycloak_runtime"
    ]
    if len(runtime_checks) != 1:
        raise AssertionError("the fixed Web convergence runtime check is missing or duplicated")
    inspect_arguments = tuple(
        ast.unparse(call.args[0])
        for call in ast.walk(runtime_checks[0])
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "_inspect_one"
        and len(call.args) == 1
        and not call.keywords
    )
    if (
        set(inspect_arguments)
        != {
            "('docker', '--context', 'default', 'container', 'inspect', KEYCLOAK_CONTAINER)",
            "('docker', '--context', 'default', 'image', 'inspect', KEYCLOAK_IMAGE)",
        }
        or len(inspect_arguments) != 2
    ):
        raise AssertionError("the exact Web convergence Docker inspect argv has drifted")
    runtime_check_source = ast.get_source_segment(convergence, runtime_checks[0]) or ""
    if "dockerfile.count(KEYCLOAK_BASE_IMAGE) != 2" not in runtime_check_source:
        raise AssertionError("the pinned Keycloak source-image check has drifted")
    for fragment in (
        "with exclusive_docker_workflow_lock(ROOT):",
        "_environment_file, keycloak_port = _mac_environment()",
        "_require_pinned_keycloak_runtime()",
        "with require_topology_reconciliation_secrets(ROOT) as guard:",
        "password = _read_gateway_admin_password(guard)",
        "runtime.identity.converge_web_authorization_services_disabled()",
        "runtime.identity.release_without_mutation()",
        "format_gateway_web_authorization_services_evidence(evidence)",
        "process.terminate()",
        "process.kill()",
        "_DOCKER_OUTPUT_MAXIMUM_BYTES - len(output) + 1",
        "len(sys.argv) == 1",
        "_FORBIDDEN_OVERRIDE_ENVIRONMENT",
    ):
        if fragment not in convergence:
            raise AssertionError(f"the exact Web convergence operator is missing: {fragment}")
    run_convergence_functions = [
        node
        for node in convergence_syntax.body
        if isinstance(node, ast.FunctionDef) and node.name == "_run_convergence"
    ]
    if len(run_convergence_functions) != 1:
        raise AssertionError("the fixed Web convergence runner is missing or duplicated")
    run_convergence_source = ast.get_source_segment(convergence, run_convergence_functions[0]) or ""
    if run_convergence_source.count("guard.revalidate()") != 3:
        raise AssertionError("the exact8 guard revalidation count has drifted")
    first_guard_revalidation = run_convergence_source.index("guard.revalidate()")
    password_read = run_convergence_source.index("password = _read_gateway_admin_password(guard)")
    second_guard_revalidation = run_convergence_source.index(
        "guard.revalidate()", first_guard_revalidation + 1
    )
    identity_construction = run_convergence_source.index(
        "runtime.identity = KeycloakGatewayAuthParityIdentity("
    )
    convergence_action = run_convergence_source.index(
        "runtime.identity.converge_web_authorization_services_disabled()"
    )
    identity_release = run_convergence_source.index("runtime.identity.release_without_mutation()")
    final_guard_revalidation = run_convergence_source.rindex("guard.revalidate()")
    convergence_order = (
        run_convergence_source.index("with exclusive_docker_workflow_lock(ROOT):"),
        run_convergence_source.index("_environment_file, keycloak_port = _mac_environment()"),
        run_convergence_source.index("_require_pinned_keycloak_runtime()"),
        run_convergence_source.index(
            "with require_topology_reconciliation_secrets(ROOT) as guard:"
        ),
        first_guard_revalidation,
        password_read,
        second_guard_revalidation,
        identity_construction,
        convergence_action,
        identity_release,
        final_guard_revalidation,
    )
    if convergence_order != tuple(sorted(convergence_order)):
        raise AssertionError("the exact Web convergence lock/read/action/release order has drifted")
    review_functions = [
        node
        for node in convergence_syntax.body
        if isinstance(node, ast.FunctionDef) and node.name == "_operator_review_evidence"
    ]
    main_functions = [
        node
        for node in convergence_syntax.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    ]
    if len(review_functions) != 1 or len(main_functions) != 1:
        raise AssertionError("the Web convergence fallback functions are missing or duplicated")
    review_source = ast.get_source_segment(convergence, review_functions[0]) or ""
    for fragment in (
        'getattr(identity, "web_authorization_services_action_attempted", False)',
        'getattr(identity, "web_authorization_services_action_succeeded", False)',
        "action_attempted = evidence.action_attempted or identity_attempted",
        "action_succeeded = evidence.action_succeeded or identity_succeeded",
    ):
        if fragment not in review_source:
            raise AssertionError(
                f"the Web convergence action-preserving fallback is missing: {fragment}"
            )
    review_evidence_calls = [
        node
        for node in ast.walk(review_functions[0])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "GatewayWebAuthorizationServicesConvergenceEvidence"
    ]
    if len(review_evidence_calls) != 1:
        raise AssertionError("the Web convergence review evidence constructor has drifted")
    review_keywords = {
        keyword.arg: ast.unparse(keyword.value) for keyword in review_evidence_calls[0].keywords
    }
    if (
        review_keywords.get("classification")
        != "GatewayWebAuthorizationServicesClassification.OPERATOR_REVIEW_REQUIRED"
        or review_keywords.get("predicate") != "ProductionWebInvariantPredicate.UNKNOWN"
        or review_keywords.get("action_attempted") != "True"
        or review_keywords.get("action_succeeded") != "action_succeeded"
        or review_keywords.get("mutation_outcome_known") != "action_succeeded"
        or review_keywords.get("mutation_count") != "1"
    ):
        raise AssertionError("the Web convergence review evidence can erase action state")
    main_call_names = tuple(
        call.func.id
        for call in ast.walk(main_functions[0])
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id
        in {
            "_ConvergenceRuntimeState",
            "_run_convergence",
            "_operator_review_evidence",
        }
    )
    if any(
        main_call_names.count(name) != 1
        for name in (
            "_ConvergenceRuntimeState",
            "_run_convergence",
            "_operator_review_evidence",
        )
    ):
        raise AssertionError("the Web convergence outer fallback can erase action evidence")
    release_finalizers: list[ast.Try] = []
    for candidate in ast.walk(run_convergence_functions[0]):
        if not isinstance(candidate, ast.Try):
            continue
        body_calls = [call for statement in candidate.body for call in ast.walk(statement)]
        final_calls = [call for statement in candidate.finalbody for call in ast.walk(statement)]
        releases_identity = any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "release_without_mutation"
            for call in body_calls
        )
        finally_revalidates = any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "revalidate"
            for call in final_calls
        )
        if releases_identity and finally_revalidates:
            release_finalizers.append(candidate)
    if len(release_finalizers) != 1:
        raise AssertionError(
            "identity release must unconditionally attempt the final exact8 guard proof"
        )
    if not any(
        isinstance(handler.type, ast.Name) and handler.type.id == "BaseException"
        for handler in release_finalizers[0].handlers
    ):
        raise AssertionError("identity release failure must remain bounded before guard proof")
    convergence_calls = [
        node for node in ast.walk(convergence_syntax) if isinstance(node, ast.Call)
    ]
    forbidden_convergence_calls = {
        "write_applied_state",
        "capture_local_topology",
        "create_disabled_fixture",
        "cleanup_client",
        "cleanup_sessions_and_users",
    }
    forbidden_convergence_attributes = {
        "mkdir",
        "rmdir",
        "unlink",
        "write",
        "write_bytes",
        "write_text",
    }
    if any(
        (isinstance(call.func, ast.Name) and call.func.id in forbidden_convergence_calls)
        or (
            isinstance(call.func, ast.Attribute)
            and call.func.attr in forbidden_convergence_attributes
        )
        for call in convergence_calls
    ):
        raise AssertionError("the exact Web convergence operator cannot mutate local state")
    for forbidden in (
        "configure_keycloak_host_dev",
        "kcadm",
        '"DELETE"',
        '"POST"',
        "create_disabled_fixture",
        "cleanup_client",
        "write_applied_state",
    ):
        if forbidden in convergence:
            raise AssertionError(f"the exact Web convergence operator is too broad: {forbidden}")
    for test_name in (
        "test_fixed_gateway_web_authorization_services_operator_is_checked_in",
        "test_operator_holds_lock_context_image_exact8_guard_and_releases_before_output",
        "test_operator_rejects_exact8_guard_key_drift_before_admin_or_action",
        "test_operator_rejects_args_and_target_environment_overrides_before_lock_or_admin",
        "test_operator_context_drift_fails_before_image_secret_or_admin",
        "test_operator_pins_fixed_keycloak_container_image_and_source_digest",
        "test_operator_rejects_keycloak_container_or_image_identity_drift",
        "test_operator_baseexception_releases_identity_guard_and_lock_with_raw0",
        "test_operator_release_failure_still_revalidates_guard_and_preserves_action",
        "test_operator_final_guard_revalidation_failure_preserves_action",
        "test_operator_context_exit_failure_after_action_preserves_evidence",
        "test_operator_outer_fallback_preserves_monotonic_action_state",
        "test_operator_source_forbids_broad_keycloak_mutation_and_full_updater",
    ):
        if f"def {test_name}(" not in convergence_tests:
            raise AssertionError(f"the exact Web convergence operator test is missing: {test_name}")
    for test_name in (
        "test_exact_web_authorization_services_convergence_uses_one_literal_put",
        "test_exact_web_authorization_services_convergence_rejects_bad_prestate_before_put",
        "test_web_authz_convergence_requires_full_pre_fingerprint_before_put",
        "test_web_authz_convergence_reports_ambiguous_put_and_reads_post_once",
        "test_web_authz_convergence_preserves_attempt_on_put_baseexception",
        "test_web_authz_convergence_preserves_attempt_when_post_proof_raises",
        "test_exact_web_authorization_services_convergence_rejects_postcondition_drift",
        "test_exact_web_authorization_services_convergence_reports_unavailable_post_proof",
    ):
        if f"def {test_name}(" not in probe_tests:
            raise AssertionError(
                f"the exact Web convergence transport test is missing: {test_name}"
            )
    for test_name in (
        "test_production_web_normalizer_returns_every_closed_predicate_without_raw_values",
        "test_normal_runtime_maps_every_internal_production_predicate_to_generic_failure",
        "test_production_web_admin_reads_are_token_then_search_document_mapper_and_short_circuit",
        "test_production_web_admin_boundary_and_response_failures_are_fixed_and_nonleaking",
        "test_production_web_provider_container_shapes_fail_at_the_first_exact_stage",
        "test_production_web_boolean_field_and_status_enums_are_exact_and_ordered",
        "test_production_web_boolean_subpredicate_reports_each_missing_field_without_mapper_read",
        "test_production_web_boolean_subpredicate_reports_each_non_bool_exact_type_without_raw_value",
        "test_missing_authorization_services_and_explicit_false_have_identical_fingerprints",
        "test_authorization_services_true_is_a_policy_failure_before_mapper_read",
        "test_missing_authorization_services_does_not_hide_another_boolean_defect",
        "test_boolean_subpredicate_scans_all_fields_in_fixed_order_without_duplicates",
        "test_production_web_boolean_subpredicate_all_valid_is_known_with_empty_defect_sets",
        "test_production_web_boolean_subpredicate_unknown_omits_sets_and_counts",
        "test_production_web_boolean_subpredicate_evidence_rejects_unknown_or_invalid_sets",
        "test_production_web_boolean_subpredicate_uses_one_full_document_and_no_mapper_read",
        "test_classifier_mac_state_and_environment_drift_is_fixed_before_secret_or_admin_read",
        "test_classifier_holds_lock_state_env_exact8_guard_and_releases_before_one_line_output",
        "test_classifier_rejects_exact8_guard_key_drift_before_admin_boundary",
        "test_classifier_baseexception_closes_every_resource_and_emits_only_fixed_unknown",
        "test_classifier_rejects_all_arguments_before_lock_or_admin_boundary",
    ):
        if f"def {test_name}(" not in probe_tests:
            raise AssertionError(f"production Web diagnostic negative is missing: {test_name}")
    for forbidden_delete in (
        "delete(CanonicalAdminBindingModel)",
        "delete(ProfileRoleAssignmentModel)",
        "delete(AccessRoleAssignmentModel)",
    ):
        if forbidden_delete in cleanup_source:
            raise AssertionError("gateway parity cleanup cannot normalize privilege drift")
    for forbidden in ('"directAccessGrantsEnabled": True', '"serviceAccountsEnabled": True'):
        if forbidden in probe:
            raise AssertionError("the gateway parity fixture cannot enable a credential shortcut")

    for fragment in (
        'selected_build_services.append("local-bootstrap")',
        'trailing=("build", "local-bootstrap")',
        "class _ComposeGatewayAuthParityFixture:",
        '"--no-build",',
        '"-T",',
        '"datariver.gateway_auth_parity_fixture",',
        "timeout=30,",
        "subprocess.TimeoutExpired",
        "_reconcile_topology_with_gateway_parity(",
        "def _bounded_gateway_log_output(",
    ):
        if fragment not in workflow:
            raise AssertionError(f"the canonical gateway parity workflow is missing: {fragment}")
    reconciliation_session = workflow.split(
        "def _reconcile_topology_with_gateway_parity(", maxsplit=1
    )[1].split("def _prepare_topology_reconciliation(", maxsplit=1)[0]
    if "session.close()" in reconciliation_session:
        raise AssertionError("the parity context must own exactly-once cleanup")
    bounded_logs = workflow.split("def _bounded_gateway_log_output(", maxsplit=1)[1].split(
        "def _verify_gateway_logs_do_not_persist_probe_credentials(", maxsplit=1
    )[0]
    for fragment in (
        "subprocess.Popen(",
        "selectors.DefaultSelector()",
        "_GATEWAY_LOG_MAXIMUM_BYTES - len(output) + 1",
        "process.terminate()",
        "process.kill()",
        "process.wait(timeout=_GATEWAY_LOG_REAP_SECONDS)",
    ):
        if fragment not in bounded_logs:
            raise AssertionError(f"gateway log bounded capture is missing: {fragment}")
    if "capture_output=True" in bounded_logs:
        raise AssertionError("gateway log capture cannot buffer unbounded subprocess output")
    log_verification = workflow.split(
        "def _verify_gateway_logs_do_not_persist_probe_credentials(", maxsplit=1
    )[1].split("def _verify_gateway_transparency(", maxsplit=1)[0]
    for fragment in ('"--since",', "started_at,", '"api",', '"apisix",', '"web",'):
        if fragment not in log_verification:
            raise AssertionError(f"gateway log complete interval is missing: {fragment}")
    if '"--tail"' in log_verification or '"2m"' in log_verification:
        raise AssertionError("gateway log evidence cannot use a relative or tail-truncated window")

    for test_name in (
        "test_fixture_contract_is_exact_human_least_scope_and_not_a_service_identity",
        "test_fixture_operations_are_fixed_and_membership_revocation_advances_version",
        "test_sql_membership_revocation_advances_only_the_allow_version",
        "test_fixture_request_rejects_missing_extra_colliding_or_provider_passthrough",
        "test_sql_cleanup_rejects_swapped_external_subjects_before_any_delete",
        "test_sql_cleanup_rejects_membership_envelope_drift_before_any_delete",
        "test_sql_cleanup_rejects_any_privilege_assignment_before_any_delete",
        "test_sql_absence_rejects_orphaned_privilege_residual_before_prepare",
        "test_sql_cleanup_deletes_only_exact_rows_after_zero_privilege_proof",
        "test_sql_cleanup_rechecks_concurrent_cross_workspace_membership_under_subject_locks",
        "test_zero_residual_rejects_external_subject_alias_under_another_id",
        "test_pkce_client_contract_disables_direct_grants_service_accounts_and_implicit_flow",
        "test_keycloak_fixture_create_order_is_client_mapper_then_two_disabled_humans",
        "test_genuine_expiry_requires_the_exact_backend_verifier_leeway_boundary",
        "test_expiry_wait_is_bounded_to_token_ttl_plus_verifier_leeway",
        "test_loopback_secure_cookie_is_sent_on_login_post_without_value_output",
        "test_pkce_rejects_unreviewed_redirect_state_or_code_without_raw_output",
        "test_pkce_token_rejects_unbounded_or_nonpositive_lifetime",
        "test_fixture_prepare_enable_topology_then_exact_matrix_and_cleanup_order",
        "test_pre_mutation_absence_failure_releases_private_identity_state_without_cleanup",
        "test_any_baseexception_preserves_sanitized_first_failure_and_cleans_exactly_once",
        "test_first_failure_and_cleanup_failure_are_reported_independently_without_raw_payload",
        "test_cleanup_failure_is_sanitized_and_continues_all_exact_cleanup_steps",
        "test_failed_parity_still_checks_logs_and_preserves_the_first_failure",
        "test_successful_parity_with_known_log_defect_reports_log_outcome_not_cleanup",
        "test_successful_parity_with_unknown_log_probe_failure_is_not_cleanup",
        "test_log_evidence_and_cleanup_failures_remain_independent",
        "test_first_defect_and_unknown_log_probe_failure_are_reported_independently",
        "test_cleanup_rediscovers_only_exact_task_resources_after_ambiguous_create_response",
        "test_cleanup_accepts_exact_client_before_optional_audience_mapper_was_created",
        "test_cleanup_rejects_client_auth_surface_mapper_scope_or_identity_drift",
        "test_cleanup_refreshes_the_admin_token_only_at_the_cleanup_boundary",
        "test_cleanup_rejects_user_identity_or_auth_surface_drift_without_deleting",
        "test_cleanup_rejects_recorded_uuid_that_was_renamed_instead_of_treating_it_absent",
        "test_production_web_fingerprint_reads_exact_client_and_mapper_inventory",
        "test_cleanup_detects_full_production_web_auth_surface_drift_without_raw_output",
        "test_production_web_invariant_rejects_incomplete_or_duplicate_baseline_before_fixture",
        "test_pkce_token_requires_the_fixed_api_audience",
        "test_cleanup_retains_multiple_or_nonexact_task_resources_without_deleting",
        "test_live_status_matrix_invokes_both_resources_and_all_hops",
        "test_log_interval_starts_once_immediately_before_first_credential_request",
        "test_live_status_matrix_rejects_any_three_hop_semantic_drift",
        "test_cors_preflight_uses_browser_headers_without_fixture_cookie_or_token",
        "test_cors_preflight_rejects_gateway_header_drift",
        "test_live_http_timeout_is_fixed_and_never_exposes_request_credentials",
        "test_gateway_fixture_compose_timeout_is_fixed_not_retried_and_never_exposes_input",
        "test_gateway_parity_session_validates_all_targets_before_reading_admin_secret",
        "test_gateway_log_probe_uses_complete_exact_interval_and_all_three_services",
        "test_gateway_log_capture_accepts_exact_cap_and_rejects_overflow_without_raw_output",
        "test_gateway_log_capture_timeout_terminates_and_reaps_child_once",
        "test_gateway_log_capture_nonzero_child_is_fixed_and_never_exposes_output",
    ):
        if not any(test_name in source for source in (probe_tests, fixture_tests, platform_tests)):
            raise AssertionError(f"the governed gateway parity direct test is missing: {test_name}")

    adr = (ROOT / "docs" / "adr" / "0113-governed-local-topology-drift.md").read_text(
        encoding="utf-8"
    )
    for fragment in (
        "public PKCE `S256` client",
        "Direct grants",
        "genuinely expired `401`",
        "`active=false`",
        "private process memory",
        "`OPEN_UNSUPPORTED`",
        "exactly-once best-effort cleanup",
        "retry count zero",
        "exact 30-second leeway",
        "before the credential POST",
        "swapped, aliased, drifted",
        "independent cleanup-required outcome",
        "log-evidence failed/known outcome",
        "complete interval for `api`, `apisix` and `web`",
        "all-Workspace Membership count",
        "complete bounded protocol-mapper inventory",
        "same\nprivate normalizer",
        "admin_token_grant=1",
        "mutation_count=0",
        "runtime remains a separate reviewed exact-one operation",
        "authorizationServicesEnabled=false",
        "never serializes `false`",
        "CLIENT_AUTHORIZATION_SERVICES_POLICY",
        "Keycloak remains the identity provider",
        "PostgreSQL RLS remain the authorization authorities",
        "converge_gateway_web_authorization_services.py",
        "sole\nnarrow existing-client convergence boundary",
        '`{"authorizationServicesEnabled": false}`',
        "An unavailable or non-204 action response is ambiguous",
        "A monotonic action-attempt marker is set before the request",
        "still attempts every independent final guard",
        "There is no automatic rollback",
        "multi-client/realm/identity envelope is not this narrow operator contract",
        "governed cache\naction count and known outcome",
        "final selected-builder\nidle proof",
        "Business, data, identity, topology, AppliedState and push mutation\ncounts remain zero",
        "selected-builder idle proof in an unconditional\nfinalization boundary",
        "one fixed task-owned name plus exact contract/operation labels",
        "foreign, ambiguous\nor retained exact-name observation is never touched",
        "Docker CLI termination is not treated as proof",
        "A child `PASS` is accepted by both the standalone diagnostic and canonical parity session",
        "A\nnon-PASS child predicate remains the first defect when cleanup also fails",
        "before any identity creation",
        "separate closed subpredicate distinguishes every\nreviewed selection branch",
        "`builder_selection_known` is always present",
        "no phase name is used to reconstruct it",
        "every other review-required\ntop-level result remains `UNKNOWN`",
        "`node_schema_known` is always present",
        "non-mapping node and missing, null or non-string name/endpoint",
        "simultaneous node-schema first defect and lock/context-exit defect",
        "Pre-scan interruption remains unknown",
    ):
        if fragment not in adr:
            raise AssertionError(f"ADR-0113 omits gateway parity term: {fragment}")


def verify_governed_persistent_data_bind_probe_contract() -> None:
    probe_path = ROOT / "scripts" / "probe_persistent_data_bind.py"
    test_path = ROOT / "backend" / "tests" / "unit" / "test_persistent_data_bind_probe.py"
    adr_path = ROOT / "docs" / "adr" / "0114-governed-persistent-data-bind-migration.md"
    probe = probe_path.read_text(encoding="utf-8")
    tests = test_path.read_text(encoding="utf-8")
    adr = adr_path.read_text(encoding="utf-8")

    syntax = ast.parse(probe, filename=probe_path.as_posix())

    def assigned_frozen_string_set(name: str) -> frozenset[str]:
        for statement in syntax.body:
            target: ast.expr | None = None
            value: ast.expr | None = None
            if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
                target = statement.targets[0]
                value = statement.value
            elif isinstance(statement, ast.AnnAssign):
                target = statement.target
                value = statement.value
            if not isinstance(target, ast.Name) or target.id != name:
                continue
            if (
                not isinstance(value, ast.Call)
                or not isinstance(value.func, ast.Name)
                or value.func.id != "frozenset"
                or len(value.args) != 1
                or value.keywords
            ):
                raise AssertionError(f"the persistent-data bind {name} is not a literal frozenset")
            evaluated = ast.literal_eval(value.args[0])
            if not isinstance(evaluated, set) or not all(
                isinstance(item, str) for item in evaluated
            ):
                raise AssertionError(f"the persistent-data bind {name} is not a string set")
            return frozenset(evaluated)
        raise AssertionError(f"the persistent-data bind {name} is missing")

    expected_image_environment_keys = {
        "POSTGRES_IMAGE_ENVIRONMENT_KEY_ALLOWLIST": frozenset(
            {"GOSU_VERSION", "LANG", "PATH", "PGDATA", "PG_MAJOR", "PG_VERSION"}
        ),
        "MINIO_IMAGE_ENVIRONMENT_KEY_ALLOWLIST": frozenset(
            {
                "MC_CONFIG_DIR",
                "MINIO_ACCESS_KEY_FILE",
                "MINIO_CONFIG_ENV_FILE",
                "MINIO_KMS_SECRET_KEY_FILE",
                "MINIO_ROOT_PASSWORD_FILE",
                "MINIO_ROOT_USER_FILE",
                "MINIO_SECRET_KEY_FILE",
                "MINIO_UPDATE_MINISIGN_PUBKEY",
                "PATH",
            }
        ),
    }
    for name, expected in expected_image_environment_keys.items():
        actual = assigned_frozen_string_set(name)
        if actual != expected or len(actual) != len(expected):
            raise AssertionError(f"the persistent-data bind {name} exact key set has drifted")

    for fragment in (
        'DATA_PARENT = Path("/Volumes/SSD_Mac/datariver-data")',
        'PROBE_LEAF_NAME = ".c2-bind-probe-v1"',
        '_LOCAL_APFS_DEVICE = re.compile(rb"^/dev/disk[0-9]+(?:s[0-9]+){0,2}$")',
        'CONFIRMATION = "SEC-DURABLE-BIND-PROBE-001-A"',
        'POSTGRES_IMAGE_ID = "sha256:'
        'feb68f4f15446397d8cac7f4fe48fe4586de83160d1fc48b46283312d1a33966"',
        'MINIO_IMAGE_ID = "sha256:'
        '14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e"',
        'POSTGRES_CAPABILITIES = ("CHOWN", "DAC_OVERRIDE", "FOWNER", "SETGID", "SETUID")',
        "with exclusive_docker_workflow_lock(ROOT) as lock:",
        '"PROBE_SECRET_CLEANUP_REQUIRED"',
        '"ownership_enforcement_claimed=false "',
        'f"mount_root_group_writable={str(self.mount_root_group_writable).lower()} "',
        "class MountRootGuard:",
        "class GuardedDirectory:",
        "class LayoutGuard:",
        "source: bytes = field(repr=False)",
        "options: frozenset[bytes] = field(repr=False)",
        "mount_root: Path = field(repr=False)",
        "mount: MountEvidence = field(repr=False)",
        'input_bytes=bundle.minio_access + b"\\n" + bundle.minio_secret + b"\\n"',
        "class RegularFileIdentity:",
        "os.fstat(stream.fileno())",
        "if current_identities != identities:",
        "if current_identities != secret_file_identities:",
        "if frozenset(environment) != expected_environment_keys or any(",
        "if environment != expected_environment:",
        'governed_environment_prefixes=("POSTGRES_",)',
        'governed_environment_prefixes=("MINIO_", "MC_")',
        "expected_environment_keys=POSTGRES_IMAGE_ENVIRONMENT_KEY_ALLOWLIST",
        "expected_environment_keys=MINIO_IMAGE_ENVIRONMENT_KEY_ALLOWLIST",
        "stderr=subprocess.DEVNULL",
        'fail("POSTGRES_PROBE_DUMP_LIMIT_EXCEEDED")',
        'fail("POSTGRES_PROBE_DUMP_PATH_CHANGED")',
        "digest.update(chunk)",
        'parts.append(f"{name}_known={str(known).lower()}")',
        "def _require_minio_versioning_state(",
        '"--versions",',
        '"--version-id",',
        "except BaseException as error:",
        'raise ProbeError("PROBE_INTERNAL_FAILURE") from None',
        'print("ERROR: PROBE_OPERATOR_INTERRUPT"',
        "os.O_EXCL",
        "os.O_NOFOLLOW",
        "os.fsync(",
        "os.replace(",
        "require_production_unchanged(executor, baseline)",
        "if _volume_names(executor) != volume_names:",
        "def _failure_probe_is_stopped(",
        "os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW",
        "metadata.identity.mode != 0o775",
        "or metadata.identity.mode & 0o002",
        "metadata.uid != os.getuid()",
        "metadata.gid != os.getgid()",
        "parent_metadata.identity.device == metadata.identity.device",
        "stat.S_ISBLK(linked.st_mode)",
        "linked.st_rdev != resolved.st_rdev",
        "mount_root != DATA_PARENT.parent",
        "mount_root.resolve(strict=True) != mount_root",
        "os.mkdir(name, 0o700, dir_fd=parent_descriptor)",
        "os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)",
        "os.fchmod(descriptor, 0o700)",
        "guard: LayoutGuard = field(repr=False)",
        "layout.guard.revalidate()",
    ):
        if fragment not in probe:
            raise AssertionError(f"the persistent-data bind probe is missing: {fragment}")

    postgres_argv = probe.split("def postgres_create_arguments(", maxsplit=1)[1].split(
        "def minio_create_arguments(", maxsplit=1
    )[0]
    minio_argv = probe.split("def minio_create_arguments(", maxsplit=1)[1].split(
        "def mc_alias_arguments(", maxsplit=1
    )[0]
    alias_argv = probe.split("def mc_alias_arguments(", maxsplit=1)[1].split(
        "def _fsync_directory(", maxsplit=1
    )[0]
    for required in (
        '"--pull",\n        "never"',
        '"--network",\n        "none"',
        '"--read-only"',
        '"no-new-privileges=true"',
        '"--cap-drop",\n        "ALL"',
        '"--log-driver",\n            "none"',
        '"--restart",\n            "no"',
    ):
        if required not in postgres_argv:
            raise AssertionError("PostgreSQL probe isolation argv has drifted")
    if postgres_argv.count('arguments.extend(("--cap-add", capability))') != 1:
        raise AssertionError(
            "PostgreSQL probe capabilities must come only from the exact allowlist"
        )
    for required in (
        '"--pull",\n        "never"',
        '"--network",\n        "none"',
        '"--read-only"',
        '"no-new-privileges=true"',
        '"--cap-drop",\n        "ALL"',
        '"MINIO_ROOT_USER_FILE=/run/secrets/minio_access_key"',
        '"MINIO_ROOT_PASSWORD_FILE=/run/secrets/minio_secret_key"',
        '"MC_CONFIG_DIR=/tmp/mc"',
    ):
        if required not in minio_argv:
            raise AssertionError("MinIO probe isolation or file-secret argv has drifted")
    if '"--cap-add"' in minio_argv:
        raise AssertionError("the MinIO probe must not add a Linux capability")
    for required in (
        '"docker",',
        '"exec",',
        '"-i",',
        '"alias",',
        '"set",',
        '"http://127.0.0.1:9000",',
    ):
        if required not in alias_argv:
            raise AssertionError("the fixed MinIO stdin alias contract has drifted")
    for forbidden in ("shell=True", '"--privileged"', '"docker.sock"'):
        if forbidden in probe:
            raise AssertionError(
                f"the bind probe contains a forbidden execution surface: {forbidden}"
            )
    if "_sha256_file(destination)" in probe:
        raise AssertionError("the bounded PostgreSQL dump must not reopen its destination")
    for forbidden_mount_fragment in (
        "source_sha",
        "source_hash",
        "hashlib.sha256(source",
    ):
        if forbidden_mount_fragment in probe:
            raise AssertionError("the APFS source token must not be fingerprinted or persisted")

    prepare = probe.split("def prepare_layout(", maxsplit=1)[1].split(
        "def _write_secret(", maxsplit=1
    )[0]
    for forbidden_prepare_fragment in (
        ".exists()",
        ".is_symlink()",
        ".mkdir(",
        "exist_ok",
    ):
        if forbidden_prepare_fragment in prepare:
            raise AssertionError("the probe layout must use only dir-fd absent creation")
    dir_fd_create = probe.split("def _open_private_directory_at(", maxsplit=1)[1].split(
        "def _create_private_child(", maxsplit=1
    )[0]
    dir_fd_fragments = (
        "os.mkdir(name, 0o700, dir_fd=parent_descriptor)",
        "descriptor = os.open(",
        "os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW",
        "os.fstat(descriptor)",
        "os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)",
        "if opened != linked:",
        "os.fchmod(descriptor, 0o700)",
        "os.fsync(descriptor)",
        "os.fsync(parent_descriptor)",
    )
    positions = [dir_fd_create.index(fragment) for fragment in dir_fd_fragments]
    if positions != sorted(positions):
        raise AssertionError("the probe dir-fd creation and durability order has drifted")
    if dir_fd_create.count("dir_fd=parent_descriptor") != 3:
        raise AssertionError("the probe dir-fd binding count has drifted")

    guarded_directory = probe.split("class GuardedDirectory:", maxsplit=1)[1].split(
        "class LayoutGuard:", maxsplit=1
    )[0]
    for fragment in (
        "os.fstat(self.descriptor)",
        "path_metadata = _directory_metadata(self.path, classification=classification)",
        "descriptor_metadata != self.metadata or path_metadata != self.metadata",
    ):
        if fragment not in guarded_directory:
            raise AssertionError("the retained child path-to-FD contract has drifted")

    layout_guard = probe.split("class LayoutGuard:", maxsplit=1)[1].split(
        "class RegularFileIdentity:", maxsplit=1
    )[0]
    for field_name in (
        "parent",
        "leaf",
        "postgres",
        "postgres_data",
        "minio",
        "minio_data",
        "evidence",
        "secrets",
    ):
        if layout_guard.count(f"{field_name}: GuardedDirectory") != 1:
            raise AssertionError("the retained layout directory set has drifted")
    for fragment in (
        "for directory in self.directories:",
        "directory.revalidate(classification=classification)",
        "for directory in reversed(self.directories):",
        "os.close(directory.descriptor)",
        "def verify_removed(self, *, parent_created: bool) -> None:",
        "descriptor_metadata != directory.metadata",
        "for directory in self.directories[1:]:",
        'self.parent.revalidate(classification="PROBE_CLEANUP_EVIDENCE_INVALID")',
    ):
        if fragment not in layout_guard:
            raise AssertionError("the retained layout identity/close contract has drifted")

    atomicity = probe.split("def probe_host_atomicity(", maxsplit=1)[1].split(
        "def _expected_architecture(", maxsplit=1
    )[0]
    for fragment in (
        "layout.guard.revalidate()",
        "directory_descriptor = layout.guard.evidence.descriptor",
        "dir_fd=directory_descriptor",
        "src_dir_fd=directory_descriptor",
        "dst_dir_fd=directory_descriptor",
        "os.fsync(directory_descriptor)",
    ):
        if fragment not in atomicity:
            raise AssertionError("the atomicity dir-fd contract has drifted")
    if atomicity.count("layout.guard.revalidate()") != 2:
        raise AssertionError("the atomicity child recheck count has drifted")

    secret_creation = probe.split("def create_probe_secrets(", maxsplit=1)[1].split(
        "def _mount(", maxsplit=1
    )[0]
    for fragment in (
        "layout.guard.revalidate()",
        "directory_descriptor = layout.guard.secrets.descriptor",
        "_write_secret(directory_descriptor, names[0], values[0])",
        "os.fsync(directory_descriptor)",
        "_regular_file_identity_at(",
    ):
        if fragment not in secret_creation:
            raise AssertionError("the synthetic-secret dir-fd contract has drifted")
    if secret_creation.count("layout.guard.revalidate()") != 2:
        raise AssertionError("the synthetic-secret child recheck count has drifted")

    postgres_start = probe.split("def _start_postgres(", maxsplit=1)[1].split(
        "def _verify_postgres_after_restart(", maxsplit=1
    )[0]
    minio_start = probe.split("def _start_minio(", maxsplit=1)[1].split(
        "def _verify_minio_after_restart(", maxsplit=1
    )[0]
    for start, container in (
        (postgres_start, "POSTGRES_PROBE_CONTAINER"),
        (minio_start, "MINIO_PROBE_CONTAINER"),
    ):
        tracked = start.index(f"created_containers.add({container})")
        create = start.index("executor.output(")
        if tracked >= create:
            raise AssertionError("a probe name must be tracked before docker create")
    if postgres_start.count("_revalidate_host_guards(mount_guard, layout)") != 4:
        raise AssertionError("the PostgreSQL create/dump child recheck count has drifted")
    if minio_start.count("_revalidate_host_guards(mount_guard, layout)") != 2:
        raise AssertionError("the MinIO create child recheck count has drifted")

    failure_cleanup = probe.split("def cleanup_failure(", maxsplit=1)[1].split(
        "def _cleanup_manifest(", maxsplit=1
    )[0]
    if failure_cleanup.count("_failure_probe_is_stopped(executor, name)") != 2:
        raise AssertionError("failure cleanup must perform one initial and one final inspect")
    if failure_cleanup.count('("docker", "stop", "--time", str(timeouts[name]), name)') != 1:
        raise AssertionError("failure cleanup must contain one bounded stop site")
    if failure_cleanup.count("mount_guard.revalidate(") != 1:
        raise AssertionError("failure cleanup must recheck the mount before secret unlink")
    mount_recheck = failure_cleanup.index("mount_guard.revalidate(")
    layout_recheck = failure_cleanup.index("layout.guard.revalidate(", mount_recheck)
    secret_presence = failure_cleanup.index("_secret_presence_count(layout)", layout_recheck)
    if not mount_recheck < layout_recheck < secret_presence:
        raise AssertionError("failure cleanup child recheck must precede secret observation")
    unlink = failure_cleanup.index("_remove_secret_file(")
    first_host_recheck = failure_cleanup.index(
        "_revalidate_host_guards(mount_guard, layout)",
        secret_presence,
    )
    second_host_recheck = failure_cleanup.index(
        "_revalidate_host_guards(mount_guard, layout)",
        first_host_recheck + 1,
    )
    if not first_host_recheck < unlink < second_host_recheck:
        raise AssertionError("every failure secret unlink must be bracketed by host guards")

    cleanup_manifest = probe.split("def _cleanup_manifest(", maxsplit=1)[1].split(
        "def _open_cleanup_parent(", maxsplit=1
    )[0]
    for fragment in (
        "names = sorted(os.listdir(directory_descriptor))",
        "dir_fd=directory_descriptor",
        "follow_symlinks=False",
        "os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW",
        "opened = os.fstat(child_descriptor)",
        "visit(child_descriptor, components)",
        "entries.append(CleanupEntry(components, identity, True))",
        "metadata.st_nlink == 1",
    ):
        if fragment not in cleanup_manifest:
            raise AssertionError("the exact leaf cleanup manifest contract has drifted")
    if "os.walk(" in probe or "glob(" in cleanup_manifest:
        raise AssertionError("the bind probe must not use generalized recursive cleanup")

    cleanup_remove = probe.split("def _open_cleanup_parent(", maxsplit=1)[1].split(
        "def cleanup_success(", maxsplit=1
    )[0]
    for fragment in (
        "descriptor = os.dup(root_descriptor)",
        "os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW",
        "linked = os.stat(name, dir_fd=descriptor, follow_symlinks=False)",
        "os.rmdir(entry.components[-1], dir_fd=parent_descriptor)",
        "os.unlink(entry.components[-1], dir_fd=parent_descriptor)",
        "os.fsync(parent_descriptor)",
    ):
        if fragment not in cleanup_remove:
            raise AssertionError("the manifest deletion dir-fd contract has drifted")

    success_cleanup = probe.split("def cleanup_success(", maxsplit=1)[1].split(
        "def _filesystem_noowners(", maxsplit=1
    )[0]
    for fragment in (
        'layout.guard.revalidate(classification="PROBE_LAYOUT_CHANGED")',
        "manifest = _cleanup_manifest(layout.guard.leaf.descriptor)",
        "_remove_cleanup_entry(",
        "dir_fd=layout.guard.parent.descriptor",
        "dir_fd=mount_guard.descriptor",
        "layout.guard.verify_removed(parent_created=layout.parent_created)",
    ):
        if fragment not in success_cleanup:
            raise AssertionError("the PASS cleanup identity lifecycle has drifted")
    if success_cleanup.count('layout.guard.revalidate(classification="PROBE_LAYOUT_CHANGED")') != 2:
        raise AssertionError("PASS cleanup must recheck children around manifest capture")

    execute = probe.split("def execute_probe(", maxsplit=1)[1].split(
        "def _parse_args(", maxsplit=1
    )[0]
    lock = execute.index("with exclusive_docker_workflow_lock(ROOT) as lock:")
    baseline = execute.index("baseline = capture_production_identity(executor)", lock)
    mount_capture = execute.index("mount_guard = capture_mount_root_guard(", baseline)
    host_mutation = execute.index(
        "layout = prepare_layout(data_parent, root_descriptor=mount_guard.descriptor)",
        mount_capture,
    )
    postgres = execute.index("_start_postgres(", host_mutation)
    minio = execute.index("_start_minio(", postgres)
    pass_cleanup = execute.index("cleanup_success(layout, mount_guard=mount_guard)", minio)
    final_identity = execute.rindex("require_production_unchanged(executor, baseline)")
    if execute.count("_revalidate_host_guards(mount_guard, layout)") != 1:
        raise AssertionError("PASS cleanup must have one combined host guard recheck")
    if execute.count("layout.guard.close()") != 1 or execute.count("mount_guard.close()") != 1:
        raise AssertionError("the outer probe finally must close both host guards")
    if (
        not lock
        < baseline
        < mount_capture
        < host_mutation
        < postgres
        < minio
        < pass_cleanup
        < final_identity
    ):
        raise AssertionError("the bind probe lock, identity and mutation order has drifted")

    container_contract = probe.split("def require_probe_container_contract(", maxsplit=1)[1].split(
        "def _wait_ready(", maxsplit=1
    )[0]
    environment_contract_fragments = (
        "expected_environment = dict(spec.image_environment)",
        "required_environment = dict(spec.required_environment)",
        "len(expected_environment) != len(spec.image_environment)",
        "len(required_environment) != len(spec.required_environment)",
        "frozenset(required_environment) != spec.reviewed_override_keys",
        ".intersection(required_environment)",
        ".issubset(spec.reviewed_override_keys)",
        "expected_environment.update(required_environment)",
        "if environment != expected_environment:",
    )
    positions = []
    for fragment in environment_contract_fragments:
        if container_contract.count(fragment) != 1:
            raise AssertionError(
                f"the probe container exact environment contract has drifted: {fragment}"
            )
        positions.append(container_contract.index(fragment))
    if positions != sorted(positions):
        raise AssertionError("the probe container baseline/override comparison order has drifted")

    for test_name in (
        "test_checked_in_image_references_remain_exactly_pinned",
        "test_postgres_create_argv_has_only_the_approved_capabilities_and_limits",
        "test_minio_create_argv_drops_all_capabilities_and_uses_file_only_server_secrets",
        "test_mc_alias_uses_exact_non_tty_stdin_credential_contract",
        "test_probe_secrets_use_csprng_lengths_and_private_files",
        "test_private_executor_never_exposes_a_secret_echo",
        "test_pg_dump_capture_is_binary_bounded_fsynced_and_hashed",
        "test_pg_dump_capture_never_writes_past_the_in_flight_limit",
        "test_pg_dump_overflow_terminates_and_reaps_the_child",
        "test_pg_dump_digest_is_streamed_without_reopening_the_destination",
        "test_pg_dump_capture_rejects_destination_path_replacement",
        "test_prepare_rejects_a_symlinked_parent",
        "test_exact_ssd_mount_root_accepts_only_path_scoped_mode_0775",
        "test_arbitrary_group_writable_root_remains_rejected",
        "test_exact_ssd_mount_root_rejects_every_mode_except_0775",
        "test_exact_ssd_mount_root_rejects_same_device_parent",
        "test_exact_ssd_mount_root_rejects_owner_or_group_drift",
        "test_exact_ssd_mount_root_rejects_symlinked_mountpoint",
        "test_exact_ssd_mount_root_requires_apfs_local_noowners",
        "test_mount_source_must_be_an_anchored_local_block_device",
        "test_mount_guard_rejects_mode_and_source_drift_without_raw_payload",
        "test_mount_guard_rejects_root_mode_drift",
        "test_mount_guard_rejects_block_device_identity_drift",
        "test_prepare_layout_uses_only_dir_fd_absent_creation",
        "test_prepare_layout_rejects_parent_replacement_between_mkdir_and_open",
        "test_prepare_layout_rejects_leaf_replacement_between_mkdir_and_open",
        "test_prepare_layout_rejects_precreated_or_symlinked_leaf",
        "test_prepare_layout_fails_closed_on_dir_fd_operation_error",
        "test_dir_fd_component_rejects_escape_names",
        "test_layout_guard_rejects_post_layout_child_path_replacement",
        "test_atomicity_and_secret_creation_are_directory_fd_relative",
        "test_success_cleanup_uses_a_held_leaf_fd_manifest",
        "test_probe_evidence_never_claims_apfs_noowners_as_ownership_enforcement",
        "test_probe_container_contract_rejects_postgres_capability_expansion",
        "test_probe_container_contract_rejects_a_nonzero_restart_count",
        "test_probe_container_contract_rejects_an_anonymous_volume",
        "test_image_environment_rejects_unreviewed_governed_keys_before_mutation",
        "test_pinned_minio_image_environment_accepts_only_the_reviewed_baseline_keys",
        "test_pinned_image_environment_rejects_any_key_set_drift",
        "test_pinned_image_environment_failure_never_exposes_opaque_values",
        "test_image_environment_rejects_malformed_entries",
        "test_probe_container_rejects_a_replaced_image_baseline_value",
        "test_probe_container_rejects_a_missing_image_baseline_key",
        "test_probe_container_rejects_a_changed_required_override",
        "test_probe_container_rejects_an_unreviewed_baseline_override_collision",
        "test_probe_container_applies_reviewed_overrides_without_duplicate_keys",
        "test_probe_container_contract_rejects_duplicate_environment_keys",
        "test_execute_probe_rejects_image_key_drift_before_any_mutation",
        "test_failure_cleanup_unlinks_secrets_only_after_both_containers_are_stopped",
        "test_failure_cleanup_retains_all_secrets_when_any_stop_fails",
        "test_failure_cleanup_never_unlinks_secrets_when_mount_recheck_is_unknown",
        "test_failure_cleanup_never_unlinks_secrets_when_child_identity_drifted",
        "test_failure_cleanup_stops_unlinking_after_mid_cleanup_child_drift",
        "test_failure_cleanup_never_unlinks_replaced_or_linked_secret_files",
        "test_secret_bundle_rejects_replacement_between_open_fd_and_post_fsync_check",
        "test_unknown_cleanup_evidence_omits_all_unobserved_numeric_claims",
        "test_failure_cleanup_continues_after_stop_inspect_exception_without_false_counts",
        "test_failure_cleanup_always_final_inspects_after_ambiguous_initial_or_stop",
        "test_minio_versioning_and_object_version_json_are_structured_and_exact",
        "test_execute_probe_records_exact_governed_order_and_success_cleanup",
        "test_execute_probe_revalidates_mount_before_each_create_and_pass_cleanup",
        "test_execute_probe_mount_drift_stops_before_the_next_bind_create",
        "test_execute_probe_child_replacement_stops_before_next_mutation_or_cleanup",
        "test_create_failure_still_runs_post_create_child_revalidation",
        "test_success_cleanup_refuses_post_layout_leaf_replacement",
        "test_success_cleanup_detects_replacement_after_manifest_before_unlink",
        "test_execute_probe_pre_mutation_gates_fail_before_any_create_or_host_write",
        "test_execute_probe_tracks_ambiguous_daemon_creation_before_client_error",
        "test_execute_probe_mutation_failures_use_one_cleanup_and_recheck_production",
        "test_execute_probe_recorder_covers_each_mutation_failure_stage",
        "test_execute_probe_host_pass_cleanup_failure_excludes_failure_cleanup_success",
        "test_execute_probe_cleanup_exception_after_partial_unlink_reports_unknown_counts",
        "test_main_maps_a_cleaned_operator_interrupt_to_a_fixed_safe_exit",
        "test_production_container_or_volume_identity_change_fails_closed",
    ):
        if test_name not in tests:
            raise AssertionError(f"the persistent-data bind direct test is missing: {test_name}")

    for fragment in (
        "runtime probe and migration open",
        "exact `/Volumes/SSD_Mac` mountpoint at mode `0775`",
        "does not persist or emit the source",
        "directory-descriptor-relative creation",
        "mkdir(..., dir_fd=...)",
        "mount_root_group_writable=true",
        "identity-checked manifest only beneath the exact leaf",
        "generalized recursive delete",
        "identity-pinned descriptors for the parent, leaf, evidence, secrets",
        "ownership_enforcement_claimed=false",
        "PROBE_SECRET_CLEANUP_REQUIRED",
        "creation-time",
        "duplicate-free `Config.Env` baseline",
        "never writes beyond 16 MiB",
        "exactly two distinct non-delete version IDs",
        "PROBE_OPERATOR_INTERRUPT",
        "original file descriptor",
        "never reopened after capture",
        "`*_known=false`",
        "possibly created before its `docker create`",
        "exactly one final inspect",
        "AppliedState.environment_key_hashes",
        "original named volumes remain untouched indefinitely",
        "OPEN_TARGET_GATE",
    ):
        if fragment not in adr:
            raise AssertionError(f"ADR-0114 omits persistent-data term: {fragment}")


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
    verify_datahub_mac_capacity_contract()
    verify_observability_contract()
    verify_build_context()
    verify_multiarch_release_contract()
    verify_datahub_release_contract()
    verify_identity_assurance_contract()
    verify_runtime_hardening()
    verify_host_development_ports()
    verify_readiness_contract()
    verify_browser_storage_boundary()
    verify_ci_supply_chain()
    verify_database_roles()
    verify_architecture_imports()
    verify_phase7_source_integrity()
    verify_tenant_referential_integrity()
    verify_seed()
    verify_amd64_source_readiness_contract()
    verify_governed_docker_build_capacity_contract()
    verify_governed_local_topology_contract()
    verify_transparent_gateway_contract()
    verify_gateway_auth_parity_fixture_contract()
    verify_governed_persistent_data_bind_probe_contract()
    verify_document_links()
    print(
        "static verification passed: compose, build/release context, DataHub release contract, "
        "identity assurance contract, "
        "runtime hardening/readiness/browser storage/web headers, "
        "CI supply chain, "
        "database roles, architecture, source integrity, tenant foreign keys, seed, "
        "amd64 source readiness, documentation"
    )


if __name__ == "__main__":
    main()
