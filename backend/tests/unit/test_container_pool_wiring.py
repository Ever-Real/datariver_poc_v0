from __future__ import annotations

from typing import Any

import pytest

from datariver.config import Settings
from datariver.interfaces.http import container as http_container
from datariver.workers import container as worker_container


def settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="postgresql+asyncpg://app@localhost/db",
        database_secret_ref="file:/run/secrets/postgres_app_password",
        migration_database_url="postgresql+asyncpg://owner@localhost/db",
        migration_database_secret_ref="file:/run/secrets/postgres_password",
        relay_database_url="postgresql+asyncpg://relay@localhost/db",
        relay_database_secret_ref="file:/run/secrets/postgres_relay_password",
        upload_database_url="postgresql+asyncpg://upload@localhost/db",
        upload_database_secret_ref="file:/run/secrets/postgres_upload_password",
        governance_database_url="postgresql+asyncpg://governance@localhost/db",
        governance_database_secret_ref="file:/run/secrets/postgres_governance_password",
        bootstrap_database_url="postgresql+asyncpg://bootstrap@localhost/db",
        bootstrap_database_secret_ref="file:/run/secrets/postgres_bootstrap_password",
        database_pool_size=7,
        database_pool_max_overflow=3,
        database_pool_timeout_seconds=9,
        worker_database_pool_size=4,
        worker_database_pool_max_overflow=2,
        worker_database_pool_timeout_seconds=8,
        oidc_issuer="http://idp/realms/test",
        oidc_audience="api",
        oidc_jwks_url="http://idp/jwks",
        datahub_base_url="http://datahub",
        datahub_secret_ref="file:/run/secrets/datahub_token",
        valkey_cache_url="redis://cache:6379/0",
        valkey_queue_url="redis://queue:6379/0",
        valkey_cache_secret_ref="file:/run/secrets/valkey_cache_password",
        valkey_queue_secret_ref="file:/run/secrets/valkey_queue_password",
        s3_endpoint_url="http://s3",
        s3_public_endpoint_url="http://localhost:8333",
        s3_bucket_quarantine="q",
        s3_bucket_accepted="a",
        s3_access_key_file="/run/secrets/s3_access_key",
        s3_secret_key_file="/run/secrets/s3_secret_key",
    )


class Resolver:
    def resolve(self, _: str) -> str:
        return "resolved-secret"


def test_api_container_passes_the_configured_pool_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    datahub_captured: dict[str, Any] = {}

    def database(url: str, **kwargs: Any) -> object:
        captured.update(url=url, **kwargs)
        return object()

    monkeypatch.setattr(http_container, "SecretResolver", Resolver)
    monkeypatch.setattr(http_container, "Database", database)
    monkeypatch.setattr(http_container, "ValkeyCache", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        http_container,
        "HttpDataHubGateway",
        lambda **kwargs: datahub_captured.update(kwargs) or object(),
    )
    monkeypatch.setattr(http_container, "OidcTokenVerifier", lambda **kwargs: object())
    monkeypatch.setattr(http_container, "S3ObjectStore", lambda **kwargs: object())

    http_container.build_container(settings())

    assert captured["pool_size"] == 7
    assert captured["max_overflow"] == 3
    assert captured["pool_timeout_seconds"] == 9
    assert datahub_captured["expected_version"] == "v1.6.0"
    assert datahub_captured["version_enforcement"] == "report"
    assert datahub_captured["version_probe_ttl_seconds"] == 300


def test_worker_container_passes_the_configured_pool_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def database(url: str, **kwargs: Any) -> object:
        captured.update(url=url, **kwargs)
        return object()

    monkeypatch.setattr(worker_container, "SecretResolver", Resolver)
    monkeypatch.setattr(worker_container, "Database", database)

    worker_container._database(settings(), role="relay")

    assert captured["pool_size"] == 4
    assert captured["max_overflow"] == 2
    assert captured["pool_timeout_seconds"] == 8
