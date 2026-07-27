from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx
import pytest

from datariver.domain.common import ValidationError
from datariver.infrastructure.system_configuration_probe import (
    probe_oidc_jwks,
    probe_system_configuration,
)


@pytest.mark.asyncio
async def test_oidc_jwks_probe_uses_fixed_allowlisted_bounded_document() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/realms/datariver/protocol/openid-connect/certs"
        return httpx.Response(
            200,
            request=request,
            json={"keys": [{"kty": "RSA", "kid": "test-key"}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await probe_oidc_jwks(
            jwks_url=("http://127.0.0.1:8081/realms/datariver/protocol/openid-connect/certs"),
            allowed_hosts=("127.0.0.1",),
            client=client,
        )

    assert result.status == "AVAILABLE"
    assert result.scope == "HTTP_HEALTH"


@pytest.mark.asyncio
async def test_oidc_jwks_probe_rejects_unallowlisted_and_link_local_destinations() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                request=request,
                json={"keys": [{"kty": "RSA"}]},
            )
        )
    ) as client:
        with pytest.raises(ValidationError, match="operator probe allowlist"):
            await probe_oidc_jwks(
                jwks_url="http://127.0.0.1:8081/certs",
                allowed_hosts=(),
                client=client,
            )
        with pytest.raises(ValidationError, match="forbidden network range"):
            await probe_oidc_jwks(
                jwks_url="http://169.254.169.254/latest/meta-data",
                allowed_hosts=("169.254.169.254",),
                client=client,
            )


@pytest.mark.asyncio
async def test_local_chat_model_probe_uses_native_ollama_context_bound() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        body = json.loads(request.content)
        assert body["model"] == "gemma4:latest"
        assert body["think"] is False
        assert body["format"]["type"] == "object"
        assert body["options"] == {
            "temperature": 0,
            "num_ctx": 8192,
            "num_predict": 32,
        }
        return httpx.Response(
            200,
            request=request,
            json={"message": {"content": '{"status":"ok"}'}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await probe_system_configuration(
            system_id="LLM_CHAT_MODEL",
            document={
                "base_url": "http://10.42.0.15:11434/v1",
                "connection_mode": "LOCAL_OLLAMA",
                "model": "gemma4:latest",
                "options": {"context_tokens": 8192},
            },
            client=client,
            allowed_hosts=("10.42.0.15",),
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
            allowed_hosts=("127.0.0.1",),
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
            document={
                "base_url": "http://127.0.0.1:8080",
                "secret_references": {"token": "file:/run/secrets/datahub_token"},
            },
            client=client,
            allowed_hosts=("127.0.0.1",),
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
                document={
                    "base_url": "http://169.254.169.254",
                    "secret_references": {"token": "file:/run/secrets/datahub_token"},
                },
                client=client,
                allowed_hosts=("169.254.169.254",),
            )


@pytest.mark.asyncio
async def test_probe_requires_operator_host_allowlist_and_bounds_decoded_body() -> None:
    document = {
        "base_url": "http://127.0.0.1:8080",
        "secret_references": {"token": "file:/run/secrets/datahub_token"},
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                request=request,
                content=b"x" * (1024 * 1024 + 1),
            )
        )
    ) as client:
        with pytest.raises(ValidationError, match="operator probe allowlist"):
            await probe_system_configuration(
                system_id="DATAHUB_GMS",
                document=document,
                client=client,
            )
        with pytest.raises(ValidationError, match="one MiB"):
            await probe_system_configuration(
                system_id="DATAHUB_GMS",
                document=document,
                client=client,
                allowed_hosts=("127.0.0.1",),
            )


@pytest.mark.asyncio
async def test_probe_rejects_an_unallowlisted_hostname_before_dns_resolution() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: pytest.fail(f"unexpected HTTP request: {request.url}")
        )
    ) as client:
        with pytest.raises(ValidationError, match="operator probe allowlist"):
            await probe_system_configuration(
                system_id="DATAHUB_GMS",
                document={
                    "base_url": "https://must-not-resolve.invalid",
                    "secret_references": {"token": "file:/run/secrets/datahub_token"},
                },
                client=client,
                allowed_hosts=("approved.internal",),
            )


@pytest.mark.asyncio
async def test_probe_requires_tls_for_an_allowlisted_nonlocal_host() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, request=request))
    ) as client:
        with pytest.raises(ValidationError, match="Plaintext system probes"):
            await probe_system_configuration(
                system_id="DATAHUB_GMS",
                document={
                    "base_url": "http://10.42.0.15:8080",
                    "secret_references": {"token": "file:/run/secrets/datahub_token"},
                },
                client=client,
                allowed_hosts=("10.42.0.15",),
            )

        result = await probe_system_configuration(
            system_id="DATAHUB_GMS",
            document={
                "base_url": "https://10.42.0.15",
                "secret_references": {"token": "file:/run/secrets/datahub_token"},
            },
            client=client,
            allowed_hosts=("10.42.0.15",),
        )

    assert result.status == "AVAILABLE"


class _SecretResolver:
    def resolve(self, reference: str) -> str:
        assert reference == "file:/run/secrets/neo4j_auth"
        return "neo4j/secret-from-file"


class _IntranetLlmSecretResolver:
    def resolve(self, reference: str) -> str:
        assert reference == "file:/run/secrets/intranet_llm_chat_api_key"
        return "intranet-api-key"


class _IntranetRerankerSecretResolver:
    def resolve(self, reference: str) -> str:
        assert reference == "file:/run/secrets/intranet_llm_reranker_api_key"
        return "reranker-api-key"


class _RedisSecretResolver:
    def resolve(self, reference: str) -> str:
        assert reference in {
            "file:/run/secrets/redis_cache_password",
            "file:/run/secrets/redis_delivery_password",
        }
        return "redis-password"


class _S3SecretResolver:
    def resolve(self, reference: str) -> str:
        values = {
            "file:/run/secrets/s3_access_key": "access-key",
            "file:/run/secrets/s3_secret_key": "secret-key",
        }
        return values[reference]


class _RedisClient:
    def __init__(self, *, policy: str = "allkeys-lfu", appendonly: str = "no") -> None:
        self.closed = False
        self.policy = policy
        self.appendonly = appendonly

    async def ping(self) -> bool:
        return True

    async def config_get(self, key: str) -> dict[str, str]:
        return {key: self.policy if key == "maxmemory-policy" else self.appendonly}

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_redis_cache_probe_uses_mounted_credential_and_role_policy() -> None:
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
        allowed_hosts=("127.0.0.1",),
    )

    assert result.status == "AVAILABLE"
    assert result.scope == "REDIS_POLICY"
    assert calls[0][0] == "redis://127.0.0.1:6379/0"
    assert calls[0][1]["password"] == "redis-password"
    assert client.closed is True


@pytest.mark.asyncio
async def test_redis_delivery_probe_requires_noeviction_and_aof() -> None:
    client = _RedisClient(policy="noeviction", appendonly="yes")

    result = await probe_system_configuration(
        system_id="REDIS_DELIVERY",
        document={
            "url": "redis://127.0.0.1:6380/0",
            "secret_references": {"password": "file:/run/secrets/redis_delivery_password"},
        },
        secret_resolver=_RedisSecretResolver(),  # type: ignore[arg-type]
        redis_factory=lambda *_args, **_kwargs: client,  # type: ignore[arg-type]
        allowed_hosts=("127.0.0.1",),
    )

    assert result.status == "AVAILABLE"
    assert result.scope == "REDIS_POLICY"
    assert client.closed is True


@pytest.mark.asyncio
async def test_s3_probe_authenticates_against_one_fixed_bucket() -> None:
    calls: list[tuple[object, ...]] = []

    async def head_bucket(*arguments: object) -> None:
        calls.append(arguments)

    result = await probe_system_configuration(
        system_id="S3_STORAGE",
        document={
            "endpoint": "http://127.0.0.1:9000",
            "public_endpoint": "http://localhost:9000",
            "region": "us-east-1",
            "buckets": {
                "accepted": "datariver-accepted",
                "exports": "datariver-exports",
                "quarantine": "datariver-quarantine",
            },
            "secret_references": {
                "access_key": "file:/run/secrets/s3_access_key",
                "secret_key": "file:/run/secrets/s3_secret_key",
            },
            "options": {"timeout_seconds": 3},
        },
        secret_resolver=_S3SecretResolver(),  # type: ignore[arg-type]
        s3_head_bucket=head_bucket,
        allowed_hosts=("127.0.0.1",),
    )

    assert result.status == "AVAILABLE"
    assert result.scope == "S3_HEAD_BUCKET"
    assert calls == [
        (
            "http://127.0.0.1:9000",
            "us-east-1",
            "access-key",
            "secret-key",
            "datariver-quarantine",
            3.0,
        )
    ]


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
            allowed_hosts=("10.42.0.15",),
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
            allowed_hosts=("10.42.0.15",),
        )
    assert rejected.status == "UNAVAILABLE"


@pytest.mark.asyncio
async def test_private_reranker_probe_executes_fixed_rank_request() -> None:
    def accepted_handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url == httpx.URL("https://10.42.0.16/v1/rerank")
        assert request.headers["Authorization"] == "Bearer reranker-api-key"
        document = json.loads(request.content)
        assert document == {
            "model": "bge-reranker-v2-m3",
            "query": "governed data catalog metadata",
            "documents": [
                "Data catalog metadata and governed lineage",
                "Unrelated weather forecast",
            ],
            "top_n": 2,
        }
        return httpx.Response(
            200,
            request=request,
            json={
                "results": [
                    {"index": 0, "relevance_score": 0.95},
                    {"index": 1, "relevance_score": 0.05},
                ]
            },
        )

    document = {
        "connection_mode": "INTRANET_RERANK_V1",
        "base_url": "https://10.42.0.16/v1",
        "model": "bge-reranker-v2-m3",
        "secret_references": {"api_key": "file:/run/secrets/intranet_llm_reranker_api_key"},
        "options": {"api_style": "rerank_v1", "timeout_seconds": 60, "top_n": 10},
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(accepted_handler)) as client:
        result = await probe_system_configuration(
            system_id="LLM_RERANKER",
            document=document,
            client=client,
            secret_resolver=_IntranetRerankerSecretResolver(),  # type: ignore[arg-type]
            allowed_hosts=("10.42.0.16",),
        )

    assert result.status == "AVAILABLE"
    assert result.scope == "RERANKING_INFERENCE"


@pytest.mark.asyncio
async def test_local_llama_cpp_reranker_accepts_ordered_finite_raw_logits() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("http://127.0.0.1:11435/v1/rerank")
        assert "Authorization" not in request.headers
        return httpx.Response(
            200,
            request=request,
            json={
                "results": [
                    {"index": 0, "relevance_score": 2.6107},
                    {"index": 1, "relevance_score": -10.9971},
                ]
            },
        )

    document = {
        "connection_mode": "LOCAL_LLAMA_CPP",
        "base_url": "http://127.0.0.1:11435/v1",
        "model": "qllama/bge-reranker-v2-m3:q4_k_m",
        "secret_references": {},
        "options": {"api_style": "rerank_v1", "timeout_seconds": 60, "top_n": 2},
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await probe_system_configuration(
            system_id="LLM_RERANKER",
            document=document,
            client=client,
            allowed_hosts=("127.0.0.1",),
        )

    assert result.status == "AVAILABLE"
    assert result.scope == "RERANKING_INFERENCE"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "results",
    [
        [
            {"index": 0, "relevance_score": 0.1},
            {"index": 1, "relevance_score": 0.9},
        ],
        [
            {"index": 0, "relevance_score": 0.9},
            {"index": 0, "relevance_score": 0.8},
        ],
        [{"index": 2, "relevance_score": 0.9}],
        [{"index": 0, "relevance_score": 1.1}],
        [{"index": True, "relevance_score": 0.9}],
    ],
)
async def test_private_reranker_probe_rejects_invalid_rank_results(
    results: list[dict[str, object]],
) -> None:
    document = {
        "connection_mode": "INTRANET_RERANK_V1",
        "base_url": "https://10.42.0.16/v1",
        "model": "bge-reranker-v2-m3",
        "secret_references": {"api_key": "file:/run/secrets/intranet_llm_reranker_api_key"},
        "options": {"api_style": "rerank_v1", "timeout_seconds": 60, "top_n": 2},
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                request=request,
                json={"results": results},
            )
        )
    ) as client:
        result = await probe_system_configuration(
            system_id="LLM_RERANKER",
            document=document,
            client=client,
            secret_resolver=_IntranetRerankerSecretResolver(),  # type: ignore[arg-type]
            allowed_hosts=("10.42.0.16",),
        )

    assert result.status == "UNAVAILABLE"
    assert result.scope == "RERANKING_INFERENCE"


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 404])
async def test_private_reranker_probe_never_claims_auth_or_route_failure_ready(
    status_code: int,
) -> None:
    document = {
        "connection_mode": "INTRANET_RERANK_V1",
        "base_url": "https://10.42.0.16/v1",
        "model": "bge-reranker-v2-m3",
        "secret_references": {"api_key": "file:/run/secrets/intranet_llm_reranker_api_key"},
        "options": {"api_style": "rerank_v1", "timeout_seconds": 60, "top_n": 2},
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(status_code, request=request))
    ) as client:
        result = await probe_system_configuration(
            system_id="LLM_RERANKER",
            document=document,
            client=client,
            secret_resolver=_IntranetRerankerSecretResolver(),  # type: ignore[arg-type]
            allowed_hosts=("10.42.0.16",),
        )

    assert result.status == "UNAVAILABLE"
    assert result.scope == "RERANKING_INFERENCE"
    if status_code == 401:
        assert "private reranking credential" in result.detail
    else:
        assert result.detail == "The fixed probe route returned HTTP 404."


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
        allowed_hosts=("127.0.0.1",),
    )

    assert result.status == "AVAILABLE"
    assert result.scope == "AUTHENTICATED_QUERY"
    assert calls == [("bolt://127.0.0.1:7688", "neo4j", "secret-from-file", "neo4j", 3.0)]


@pytest.mark.asyncio
async def test_neo4j_probe_cancels_a_stalled_provider_with_sanitized_error() -> None:
    cancelled = False

    async def stalled_query(
        endpoint: str,
        username: str,
        password: str,
        database: str,
        timeout_seconds: float,
    ) -> int:
        nonlocal cancelled
        try:
            await asyncio.Event().wait()
        finally:
            cancelled = True
        return 1

    started = time.monotonic()
    with pytest.raises(
        ValidationError,
        match="saved Neo4j credentials or database are unavailable",
    ) as caught:
        await probe_system_configuration(
            system_id="NEO4J",
            document={
                "uri": "bolt://127.0.0.1:7688",
                "database": "neo4j",
                "secret_references": {"credential": "file:/run/secrets/neo4j_auth"},
                "options": {"connection_timeout_seconds": 1},
            },
            secret_resolver=_SecretResolver(),  # type: ignore[arg-type]
            neo4j_query=stalled_query,
            allowed_hosts=("127.0.0.1",),
        )

    assert time.monotonic() - started < 1.5
    assert cancelled is True
    assert "secret-from-file" not in str(caught.value)
