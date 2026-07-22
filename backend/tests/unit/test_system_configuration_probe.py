from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from datariver.domain.common import ValidationError
from datariver.infrastructure.system_configuration_probe import probe_system_configuration


@pytest.mark.asyncio
async def test_chat_model_probe_executes_a_strict_json_completion() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == "gemma4:latest"
        assert body["response_format"]["type"] == "json_schema"
        return httpx.Response(
            200,
            request=request,
            json={"choices": [{"message": {"content": '{"status":"ok"}'}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await probe_system_configuration(
            system_id="LLM_CHAT_MODEL",
            document={"base_url": "http://127.0.0.1:11434/v1", "model": "gemma4:latest"},
            client=client,
        )

    assert result.status == "AVAILABLE"
    assert result.scope == "MODEL_INFERENCE"


@pytest.mark.asyncio
async def test_embedding_probe_executes_and_validates_one_vector() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                request=request,
                json={"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]},
            )
        )
    ) as client:
        result = await probe_system_configuration(
            system_id="LLM_EMBEDDING",
            document={"base_url": "http://127.0.0.1:11434/v1", "model": "bge-m3:latest"},
            client=client,
        )

    assert result.status == "AVAILABLE"
    assert result.scope == "EMBEDDING_INFERENCE"


@pytest.mark.asyncio
async def test_http_probe_reports_authentication_without_claiming_readiness() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(401, request=request))
    ) as client:
        result = await probe_system_configuration(
            system_id="DATAHUB_GMS",
            document={"base_url": "http://127.0.0.1:8080"},
            client=client,
        )

    assert result.status == "AUTHENTICATION_REQUIRED"
    assert result.scope == "HTTP_HEALTH"


@pytest.mark.asyncio
async def test_probe_rejects_link_local_metadata_destinations() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, request=request))
    ) as client:
        with pytest.raises(ValidationError, match="forbidden network range"):
            await probe_system_configuration(
                system_id="DATAHUB_GMS",
                document={"base_url": "http://169.254.169.254"},
                client=client,
            )


class _SecretResolver:
    def resolve(self, reference: str) -> str:
        assert reference == "file:/run/secrets/neo4j_auth"
        return "neo4j/secret-from-file"


class _IntranetLlmSecretResolver:
    def resolve(self, reference: str) -> str:
        assert reference == "file:/run/secrets/intranet_llm_chat_api_key"
        return "intranet-api-key"


class _RedisSecretResolver:
    def resolve(self, reference: str) -> str:
        assert reference == "file:/run/secrets/redis_cache_password"
        return "redis-password"


class _RedisClient:
    def __init__(self) -> None:
        self.closed = False

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_redis_probe_uses_mounted_credential_and_ping_only() -> None:
    client = _RedisClient()
    calls: list[tuple[str, dict[str, object]]] = []

    def redis_factory(url: str, **kwargs: object) -> _RedisClient:
        calls.append((url, kwargs))
        return client

    result = await probe_system_configuration(
        system_id="REDIS_CACHE",
        document={
            "url": "redis://127.0.0.1:6379/0",
            "secret_references": {"password": "file:/run/secrets/redis_cache_password"},
        },
        secret_resolver=_RedisSecretResolver(),  # type: ignore[arg-type]
        redis_factory=redis_factory,  # type: ignore[arg-type]
    )

    assert result.status == "AVAILABLE"
    assert result.scope == "REDIS_PING"
    assert calls[0][0] == "redis://127.0.0.1:6379/0"
    assert calls[0][1]["password"] == "redis-password"
    assert client.closed is True


@pytest.mark.asyncio
async def test_intranet_llm_probe_uses_the_operator_secret_and_rejects_bad_credentials() -> None:
    def accepted_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer intranet-api-key"
        return httpx.Response(
            200,
            request=request,
            json={"choices": [{"message": {"content": '{"status":"ok"}'}}]},
        )

    document = {
        "connection_mode": "INTRANET_OPENAI_COMPATIBLE",
        "base_url": "https://10.42.0.15/v1",
        "model": "gemma4:latest",
        "secret_references": {"api_key": "file:/run/secrets/intranet_llm_chat_api_key"},
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(accepted_handler)) as client:
        accepted = await probe_system_configuration(
            system_id="LLM_CHAT_MODEL",
            document=document,
            client=client,
            secret_resolver=_IntranetLlmSecretResolver(),  # type: ignore[arg-type]
        )
    assert accepted.status == "AVAILABLE"

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(401, request=request))
    ) as client:
        rejected = await probe_system_configuration(
            system_id="LLM_CHAT_MODEL",
            document=document,
            client=client,
            secret_resolver=_IntranetLlmSecretResolver(),  # type: ignore[arg-type]
        )
    assert rejected.status == "UNAVAILABLE"


@pytest.mark.asyncio
async def test_neo4j_probe_authenticates_and_executes_fixed_query() -> None:
    calls: list[tuple[Any, ...]] = []

    async def neo4j_query(
        endpoint: str,
        username: str,
        password: str,
        database: str,
        timeout_seconds: float,
    ) -> int:
        calls.append((endpoint, username, password, database, timeout_seconds))
        return 1

    result = await probe_system_configuration(
        system_id="NEO4J",
        document={
            "uri": "bolt://127.0.0.1:7688",
            "database": "neo4j",
            "secret_references": {"credential": "file:/run/secrets/neo4j_auth"},
        },
        secret_resolver=_SecretResolver(),  # type: ignore[arg-type]
        neo4j_query=neo4j_query,
    )

    assert result.status == "AVAILABLE"
    assert result.scope == "AUTHENTICATED_QUERY"
    assert calls == [("bolt://127.0.0.1:7688", "neo4j", "secret-from-file", "neo4j", 3.0)]
