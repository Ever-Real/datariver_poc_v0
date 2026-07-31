from __future__ import annotations

from typing import Any

import pytest

from datariver.config import Settings
from datariver.infrastructure.knowledge import runtime as knowledge_runtime
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
        datahub_expected_version="v1.6.0",
        datahub_allowed_versions=(),
        local_ollama_chat_enabled=False,
        local_ollama_embedding_enabled=False,
        neo4j_projection_enabled=False,
        knowledge_pipeline_enabled=False,
        system_configuration_runtime_activation_enabled=False,
        redis_cache_url="redis://cache:6379/0",
        redis_delivery_url="redis://delivery:6379/0",
        redis_cache_secret_ref="file:/run/secrets/redis_cache_password",
        redis_delivery_secret_ref="file:/run/secrets/redis_delivery_password",
        s3_endpoint_url="http://s3",
        s3_public_endpoint_url="http://localhost:8333",
        s3_bucket_quarantine="q",
        s3_bucket_accepted="a",
        s3_access_key_file="/run/secrets/s3_access_key",
        s3_secret_key_file="/run/secrets/s3_secret_key",
    )


class Resolver:
    def __init__(self, **_: object) -> None:
        pass

    def resolve(self, _: str) -> str:
        return "resolved-secret"


def test_embedding_only_runtime_never_resolves_the_chat_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved: list[str] = []

    class RecordingResolver:
        def __init__(self, **_: object) -> None:
            pass

        def resolve(self, reference: str) -> str:
            resolved.append(reference)
            return "embedding-secret"

    monkeypatch.setattr(
        "datariver.config.socket.getaddrinfo",
        lambda *_args, **_kwargs: [
            (2, 1, 6, "", ("10.20.30.40", 443)),
        ],
    )
    configured = Settings(
        **(
            settings().model_dump()
            | {
                "app_env": "development",
                "intranet_openai_compatible_allowed_hosts": ("models.internal",),
                "intranet_openai_compatible_chat_enabled": True,
                "intranet_openai_compatible_chat_base_url": ("https://models.internal/v1"),
                "intranet_openai_compatible_chat_model": "chat-v1",
                "intranet_openai_compatible_chat_api_key_secret_ref": (
                    "file:/run/secrets/chat_api_key"
                ),
                "intranet_openai_compatible_embedding_enabled": True,
                "intranet_openai_compatible_embedding_base_url": ("https://models.internal/v1"),
                "intranet_openai_compatible_embedding_model": "embedding-v1",
                "intranet_openai_compatible_embedding_api_key_secret_ref": (
                    "file:/run/secrets/embedding_api_key"
                ),
            }
        )
    )
    monkeypatch.setattr(knowledge_runtime, "SecretResolver", RecordingResolver)

    runtime = knowledge_runtime.build_knowledge_embedding_runtime(configured)

    assert runtime.binding.model == "embedding-v1"
    assert resolved == ["file:/run/secrets/embedding_api_key"]


def test_api_container_passes_the_configured_pool_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    budget_captured: dict[str, Any] = {}
    datahub_captured: dict[str, Any] = {}
    oidc_captured: dict[str, Any] = {}

    def database(url: str, **kwargs: Any) -> object:
        captured.update(url=url, **kwargs)
        return object()

    monkeypatch.setattr(http_container, "SecretResolver", Resolver)
    monkeypatch.setattr(http_container, "Database", database)
    monkeypatch.setattr(http_container, "RedisCache", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        http_container,
        "RedisChatRequestBudgetGuard",
        lambda url, **kwargs: budget_captured.update(url=url, **kwargs) or object(),
    )
    monkeypatch.setattr(
        http_container,
        "HttpDataHubGateway",
        lambda **kwargs: datahub_captured.update(kwargs) or object(),
    )
    monkeypatch.setattr(
        http_container,
        "OidcTokenVerifier",
        lambda **kwargs: oidc_captured.update(kwargs) or object(),
    )
    monkeypatch.setattr(http_container, "S3ObjectStore", lambda **kwargs: object())

    http_container.build_container(settings())

    assert captured["pool_size"] == 7
    assert captured["max_overflow"] == 3
    assert captured["pool_timeout_seconds"] == 9
    assert datahub_captured["expected_version"] == "v1.6.0"
    assert datahub_captured["allowed_versions"] == ()
    assert datahub_captured["version_enforcement"] == "report"
    assert datahub_captured["version_probe_ttl_seconds"] == 300
    assert oidc_captured["hardware_acr_values"] == ("2",)
    assert oidc_captured["hardware_amr_values"] == ("webauthn", "hwk")
    assert oidc_captured["password_reauth_acr_values"] == ("1",)
    assert oidc_captured["password_amr_values"] == ("pwd",)
    assert budget_captured == {
        "url": "redis://delivery:6379/0",
        "password": "resolved-secret",
    }


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


def test_retention_workers_use_the_isolated_one_connection_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def database(url: str, **kwargs: Any) -> object:
        captured.update(url=url, **kwargs)
        return object()

    configured = Settings(
        **(
            settings().model_dump()
            | {
                "retention_scheduler_database_url": (
                    "postgresql+asyncpg://retention_scheduler@localhost/db"
                ),
                "retention_scheduler_database_secret_ref": (
                    "file:/run/secrets/postgres_retention_scheduler_password"
                ),
                "retention_worker_database_pool_size": 1,
                "retention_worker_database_pool_max_overflow": 0,
            }
        )
    )
    monkeypatch.setattr(worker_container, "SecretResolver", Resolver)
    monkeypatch.setattr(worker_container, "Database", database)

    worker_container._database(configured, role="retention_scheduler")

    assert captured["pool_size"] == 1
    assert captured["max_overflow"] == 0
    assert captured["application_name"] == "datariver-next-retention_scheduler"
