from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[3]
POC_COMPOSE = ROOT / "deploy" / "poc" / "docker-compose.poc.yaml"
AIRFLOW_COMPOSE = ROOT / "deploy" / "poc" / "docker-compose.airflow.yaml"


def _document(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_poc_web_publish_is_loopback_while_container_listener_remains_reachable() -> None:
    compose = _document(POC_COMPOSE)
    services = compose["services"]
    web = services["web"]

    assert web["ports"] == ["${POC_BIND_HOST:-127.0.0.1}:${POC_PORT:-39080}:8080"]
    assert web["environment"]["POC_SERVER_HOST"] == "0.0.0.0"  # noqa: S104
    assert web["networks"] == ["poc-services"]

    assert services["neo4j"]["ports"] == [
        "${POC_STATE_BIND_HOST:-127.0.0.1}:${POC_NEO4J_HTTP_PORT:-17475}:7474"
    ]
    assert services["pgvector"]["ports"] == [
        "${POC_STATE_BIND_HOST:-127.0.0.1}:${POC_POSTGRES_HOST_PORT:-15432}:5432"
    ]
    assert services["redis"]["ports"] == [
        "${POC_STATE_BIND_HOST:-127.0.0.1}:${POC_REDIS_PORT:-16379}:6379"
    ]


def test_optional_airflow_uses_loopback_publish_and_shared_web_network() -> None:
    compose = _document(AIRFLOW_COMPOSE)
    airflow = compose["services"]["airflow"]
    environment = airflow["environment"]

    assert airflow["ports"] == [
        "${AIRFLOW_BIND_HOST:-127.0.0.1}:${AIRFLOW_PORT:-18888}:8080"
    ]
    assert airflow["networks"] == ["poc-services"]
    assert environment["DATARIVER_API_BASE_URL"] == (
        "${AIRFLOW_DATARIVER_URL:-http://web:8080}"
    )
    assert "web" in environment["NO_PROXY"].split(",")
    assert "web" in environment["no_proxy"].split(",")
    assert compose["networks"]["poc-services"] == {
        "external": True,
        "name": "${POC_SHARED_NETWORK:-datariver-poc-services}",
    }
