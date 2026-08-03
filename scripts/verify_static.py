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
        '"docker",\n            "buildx",\n            "history",\n            "ls"',
        '"status=running"',
        '"docker",\n                    "buildx",\n                    "prune"',
        '"--all"',
        '"--reserved-space"',
        '"--max-used-space"',
        '"--min-free-space"',
        "reserve = (filesystem_total + 9) // 10",
        "cache_budget = (filesystem_total + 7) // 8",
        "reclaimable_before < required_cache_recovery",
        "free_before + recoverable_while_retaining_floor < required",
        "DOCKER_BUILD_CACHE_ACTION_FAILED_POST_MEASUREMENT_OK",
        "DOCKER_BUILD_CACHE_ACTION_FAILED_POST_MEASUREMENT_FAILED",
        "DOCKER_BUILD_CACHE_ACTION_SUCCEEDED_POST_MEASUREMENT_FAILED",
        '"action_attempts=1"',
        '"retry_count=0"',
        'f"cache_probe_ok={',
        'f"filesystem_probe_ok={',
        'f"cache_delta_signed={',
        'f"free_delta_signed={',
        'raise DockerCapacityError("DOCKER_BUILDER_MUST_HAVE_EXACTLY_ONE_NODE")',
        'raise DockerCapacityError("DOCKER_BUILDER_OVERRIDE_NOT_CURRENT")',
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
    for forbidden in (
        "docker system prune",
        "docker image prune",
        "docker container prune",
        "docker volume prune",
        "docker builder prune",
    ):
        if forbidden in capacity:
            raise AssertionError(f"the capacity gate contains a forbidden cleanup: {forbidden}")

    workflow = (ROOT / "scripts" / "workflow_update_restart.py").read_text(encoding="utf-8")
    main_source = workflow.split("def main() -> int:", maxsplit=1)[1]
    lock_start = main_source.index("capacity_lock = mutation_stack.enter_context")
    preflight = main_source.index("selected_builder = _preflight_build_capacity")
    reranker = main_source.index("_reconcile_local_reranker")
    if not lock_start < preflight < reranker:
        raise AssertionError("capacity lock/preflight must precede local reranker mutation")
    if main_source.count("_require_idle_builder(selected_builder, capacity_lock)") != 4:
        raise AssertionError("every update-workflow Compose build must recheck active builds")
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
    ):
        if test_name not in test_source:
            raise AssertionError(f"the Docker capacity direct test is missing: {test_name}")
    for test_name in (
        "test_update_capacity_lock_spans_preflight_build_mutation_and_state_write",
        "test_update_capacity_failure_releases_lock_before_any_docker_mutation",
        "test_docker_capacity_controller_is_operator_only",
        "test_update_reuses_existing_datahub_images_without_registry_pull",
        "test_offline_identity_build_keeps_existing_no_capacity_evidence_semantics",
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
    ):
        if fragment not in adr:
            raise AssertionError(f"ADR-0112 omits governed capacity term: {fragment}")


def verify_governed_local_topology_contract() -> None:
    platform_path = ROOT / "scripts" / "platform_workflow.py"
    platform = platform_path.read_text(encoding="utf-8")
    for fragment in (
        "class LocalTopologyAudit:",
        "class TopologyReconciliationPlan:",
        'LOCAL_TOPOLOGY_RECONCILIATION = "mac-development-graph-gateway-v1"',
        'expected_missing=("worker.governance-document",)',
        'unexpected_running=("gateway.apisix", "graph.neo4j")',
        "target_state=replace(state, local_gateway=True, local_graph=True)",
        "class TopologyReconciliationSecretGuard:",
        "TOPOLOGY_RECONCILIATION_SECRET_NAMES",
        "len(TOPOLOGY_RECONCILIATION_SECRET_NAMES) != 7",
        "def revalidate(self) -> None:",
        "_secret_guard_identity(opened) != self.file_identities[name]",
        'traversed == Path("/Volumes/SSD_Mac") and mode == 0o775',
        "opened_secret_dir.st_dev != opened_root.st_dev",
        "os.O_RDONLY | os.O_NOFOLLOW",
        "stat.S_IMODE(opened.st_mode) != 0o444",
        '"expected_missing"',
        '"unexpected_running"',
        '"selected_unhealthy"',
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
    if "set(os.listdir(secret_descriptor))" in platform:
        raise AssertionError("unrelated canonical secrets cannot influence topology selection")

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
        "test_topology_reconciliation_rejects_any_nonexact_prestate_or_finding",
        "test_topology_secret_preflight_accepts_selected_subset_of_canonical_metadata",
        "test_topology_secret_preflight_rejects_a_symlinked_root",
        "test_topology_secret_guard_detects_selected_file_replacement_after_preflight",
        "test_topology_secret_preflight_fails_closed_without_reading_values",
        "test_topology_reconciliation_mutation_order_is_worker_gateway_web_airflow",
        "test_worker_create_is_bracketed_by_retained_secret_guard_on_ambiguous_failure",
        "test_worker_create_stops_before_mutation_when_retained_secret_guard_drifted",
        "test_governance_document_role_and_backlog_are_separate_sanitized_queries",
        "test_topology_reconciliation_failure_stops_before_later_mutations",
        "test_gateway_live_auth_parity_unavailable_is_state_write_precondition",
        "test_unavailable_gateway_auth_parity_stops_under_lock_before_runtime_mutation",
        "test_gateway_log_probe_rejects_credential_persistence_without_raw_output",
    ):
        if test_name not in test_source:
            raise AssertionError(f"the local-topology direct test is missing: {test_name}")

    adr = (ROOT / "docs" / "adr" / "0113-governed-local-topology-drift.md").read_text(
        encoding="utf-8"
    )
    for fragment in (
        "LOCAL_TOPOLOGY_DRIFT",
        "expected-missing",
        "unexpected-running",
        "selected-unhealthy",
        "intent-mismatch",
        "no auto-stop",
        "mac-development-graph-gateway-v1",
        "governance-document-worker",
        "required subset",
        "GATEWAY_AUTH_PARITY_EVIDENCE_UNAVAILABLE",
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
        raise AssertionError(
            "gateway adoption must fail closed without governed live auth evidence"
        )
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
