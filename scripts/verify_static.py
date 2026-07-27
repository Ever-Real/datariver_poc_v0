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
    ROOT / "compose.source-host.yaml",
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
    "local-bootstrap": {"postgres_bootstrap_password"},
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
    "knowledge-source-worker": {
        "postgres_knowledge_password",
        "redis_delivery_password",
        "s3_knowledge_access_key",
        "s3_knowledge_secret_key",
        "intranet_llm_chat_api_key",
        "intranet_llm_embedding_api_key",
    },
}
DATAHUB_CONTRACT_DIRECTORY = ROOT / "infra" / "contracts"
DATAHUB_COMPONENTS = {"actions", "frontend", "gms", "upgrade"}
IMMUTABLE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
EXACT_STABLE_RELEASE = re.compile(r"v\d+\.\d+\.\d+\Z")


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
            "postgres:17.10-bookworm@sha256:4f736ae292687621d4dbe0d499ffd024a36bd2ee7d8ca6f2ccd4c800f047b394",
        },
        ROOT / "compose.local-connectors.yaml": {
            "redis:8.2.6-bookworm@sha256:3055dc25265b0c19ec90a1756dad4e0faff6f79e2557a6ac3d1274e39ee906f6",
            "minio:RELEASE.2025-09-07T16-13-09Z@sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e",
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
            "${DATAHUB_EMBED_BASE_URL} ${GRAFANA_EMBED_BASE_URL}; form-action 'self' "
            '${OIDC_PUBLIC_ORIGIN}" always;'
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
            "stop_owned_vite_processes",
            "require_postgres_listener",
            "A container shown only as 5432/tcp is not published",
            "workflow_source_host_infra.py",
            'vite_entry="$root/frontend/node_modules/vite/bin/vite.js"',
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
            "--source-host-airflow-bridge",
            "set_env_value AIRFLOW_SOURCE_API_BRIDGE_PORT 38103",
            "--intranet-source-host",
            "set_env_value INTRANET_SOURCE_HOST_ENABLED",
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
            '"--build",',
            '"--no-build", "--pull", "never"',
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
    local_storage_files = [
        path.relative_to(ROOT)
        for path in source_files
        if "localStorage" in path.read_text(encoding="utf-8")
    ]
    if local_storage_files:
        raise AssertionError(
            "browser source must not persist security or tenant context in localStorage: "
            f"{local_storage_files}"
        )
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
    ):
        if re.search(rf"ALTER ROLE {role}[^;]*NOBYPASSRLS;", combined) is None:
            raise AssertionError(f"{role} must remain subject to workspace RLS")
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
    verify_tenant_referential_integrity()
    verify_seed()
    verify_document_links()
    print(
        "static verification passed: compose, build/release context, DataHub release contract, "
        "identity assurance contract, "
        "runtime hardening/readiness/browser storage/web headers, "
        "CI supply chain, "
        "database roles, architecture, tenant foreign keys, seed, documentation"
    )


if __name__ == "__main__":
    main()
