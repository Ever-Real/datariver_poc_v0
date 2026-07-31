from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[3]
PILOT = ROOT / "deploy" / "pilot"


def _compose() -> dict[str, Any]:
    document = yaml.safe_load((PILOT / "docker-compose.yaml").read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _contains_key(value: object, target: str) -> bool:
    if isinstance(value, dict):
        return target in value or any(_contains_key(child, target) for child in value.values())
    if isinstance(value, list):
        return any(_contains_key(child, target) for child in value)
    return False


def test_pilot_compose_is_image_only_and_never_pulls() -> None:
    compose = _compose()
    services = compose["services"]

    assert not _contains_key(compose, "build")
    assert services
    for service in services.values():
        assert service["image"].startswith("datariver-pilot-")
        assert service["pull_policy"] == "never"
    assert "latest" not in (PILOT / "docker-compose.yaml").read_text(encoding="utf-8")


def test_pilot_compose_publishes_only_loopback_web_and_oidc_upstreams() -> None:
    compose = _compose()
    services = compose["services"]

    published = {name for name, service in services.items() if "ports" in service}
    assert published == {"keycloak", "web"}
    assert "ports" not in services["api"]
    assert "ports" not in services["postgres"]
    assert "ports" not in services["redis-cache"]
    assert "ports" not in services["redis-delivery"]
    env_example = (PILOT / ".env.example").read_text(encoding="utf-8")
    assert "PILOT_BIND_ADDRESS=127.0.0.1" in env_example
    assert "PILOT_BIND_ADDRESS=0.0.0.0" not in env_example


def test_pilot_migration_and_bootstrap_are_explicit_one_shot_services() -> None:
    services = _compose()["services"]

    assert services["migrate"]["profiles"] == ["deploy-tools"]
    assert services["migrate"]["restart"] == "no"
    assert services["migrate"]["command"][-2:] == ["upgrade", "head"]
    assert services["local-bootstrap"]["profiles"] == ["deploy-tools"]
    assert services["local-bootstrap"]["restart"] == "no"
    assert services["storage-init"]["profiles"] == ["deploy-tools"]


def test_export_and_deploy_scripts_preserve_air_gap_and_host_state() -> None:
    exporter = (ROOT / "scripts" / "export_release.sh").read_text(encoding="utf-8")
    deployer = (ROOT / "scripts" / "deploy_pilot.sh").read_text(encoding="utf-8")

    assert "--commit FULL_SHA" in exporter
    assert "status --porcelain" in exporter
    assert "linux/amd64" in exporter
    assert "docker image save" in exporter
    assert "release.tar.gz" in exporter
    assert "backend_image=" in exporter
    assert "redis_source=" in exporter
    assert "standalone source checkout" in exporter
    assert 'install -m 0644 "$root/deploy/pilot/docker-compose.yaml"' in exporter

    assert "docker load --input" in deployer
    assert "docker pull" not in deployer
    assert "docker build" not in deployer
    assert "up -d --no-build" in deployer
    assert "run --rm --no-deps migrate" in deployer
    assert "operator_profile=$(env_value DATARIVER_OPERATOR_PROFILE)" in deployer
    assert '"$operator_profile" != source-free-pilot' in deployer
    assert deployer.index("run --rm --no-deps migrate") < deployer.index(
        '"${compose[@]}" up -d --no-build\n'
    )
    assert "docker volume rm" not in deployer
    assert "down -v" not in deployer
    assert "PILOT_BIND_ADDRESS must remain 127.0.0.1" in deployer


def test_pilot_environment_separates_configuration_and_secrets() -> None:
    env_example = (PILOT / ".env.example").read_text(encoding="utf-8")
    generated = set(
        (PILOT / "secrets.example" / "generated-files.txt").read_text(encoding="utf-8").splitlines()
    )
    operator = set(
        (PILOT / "secrets.example" / "operator-files.txt").read_text(encoding="utf-8").splitlines()
    )

    assert "DATABASE_SECRET_REF=file:/run/secrets/postgres_app_password" in env_example
    assert "DATARIVER_ENV_FILE=/home/datariver/.env" in env_example
    assert "DATARIVER_OPERATOR_PROFILE=source-free-pilot" in env_example
    assert "SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS=" in env_example
    assert "DATAHUB_SECRET_REF=file:/run/secrets/datahub_token" in env_example
    assert "REDIS_CACHE_SECRET_REF=file:/run/secrets/redis_cache_password" in env_example
    assert "POSTGRES_PASSWORD=" not in env_example
    assert "KEYCLOAK_ADMIN_PASSWORD=" not in env_example
    assert {"postgres_password", "redis_cache_password", "keycloak_admin_password"} <= generated
    assert {"datahub_token", "s3_access_key", "s3_secret_key"} <= operator
    assert not generated.intersection(operator)


def test_postgres_initialization_is_embedded_in_the_release_image() -> None:
    dockerfile = (ROOT / "infra" / "pilot" / "postgres" / "Dockerfile").read_text(encoding="utf-8")

    assert "pgvector/pgvector:0.8.2-pg17-bookworm@sha256:" in dockerfile
    assert "infra/postgres/init/" in dockerfile
    assert "/docker-entrypoint-initdb.d/" in dockerfile
