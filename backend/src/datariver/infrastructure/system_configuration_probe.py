from __future__ import annotations

import asyncio
import ipaddress
import json
import math
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

import boto3
import httpx
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from neo4j import AsyncGraphDatabase
from redis.asyncio import Redis

from datariver.domain.common import ValidationError
from datariver.domain.system_configuration import require_canonical_secret_references
from datariver.infrastructure.secrets import SecretResolver

ProbeStatus = Literal["AVAILABLE", "AUTHENTICATION_REQUIRED", "UNAVAILABLE"]
ProbeScope = Literal[
    "HTTP_HEALTH",
    "MODEL_DISCOVERY",
    "MODEL_INFERENCE",
    "EMBEDDING_INFERENCE",
    "RERANKING_INFERENCE",
    "AUTHENTICATED_QUERY",
    "REDIS_POLICY",
    "S3_HEAD_BUCKET",
]


@dataclass(frozen=True, slots=True)
class SystemConfigurationProbeResult:
    status: ProbeStatus
    scope: ProbeScope
    latency_ms: int
    detail: str


_HTTP_PROBE_PATHS: dict[str, tuple[str, ProbeScope]] = {
    "DATAHUB_GMS": ("/health", "HTTP_HEALTH"),
    "DATAHUB_FRONTEND": ("/", "HTTP_HEALTH"),
    "AIRFLOW": ("/api/v2/monitor/health", "HTTP_HEALTH"),
    "PROMETHEUS": ("/-/healthy", "HTTP_HEALTH"),
    "GRAFANA_DASHBOARD": ("/api/health", "HTTP_HEALTH"),
}

_PLAINTEXT_DEVELOPMENT_HOSTS = frozenset(
    {
        "127.0.0.1",
        "localhost",
        "host.docker.internal",
        "datahub-gms",
        "datahub-frontend",
        "airflow",
        "redis-cache",
        "redis-delivery",
        "s3",
        "minio",
        "neo4j",
        "prometheus",
        "grafana",
    }
)


def _endpoint(document: Mapping[str, Any]) -> str:
    for key in ("base_url", "endpoint", "url", "uri"):
        value = document.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise ValidationError("The saved system configuration has no endpoint.")


def _validated_url(endpoint: str, *, schemes: set[str]) -> tuple[str, str, int]:
    parsed = urlsplit(endpoint)
    if parsed.scheme not in schemes or parsed.hostname is None:
        raise ValidationError("The saved system endpoint uses an unsupported URL scheme.")
    if parsed.username is not None or parsed.password is not None:
        raise ValidationError("Credentials must not be embedded in a system endpoint URL.")
    if parsed.query or parsed.fragment:
        raise ValidationError("A system endpoint must not contain a query or fragment.")
    default_port = 443 if parsed.scheme == "https" else 80
    if parsed.scheme in {"bolt", "neo4j", "bolt+s", "neo4j+s"}:
        default_port = 7687
    if parsed.scheme in {"redis", "rediss"}:
        default_port = 6379
    return endpoint, parsed.hostname, parsed.port or default_port


def _require_tls_for_nonlocal_endpoint(endpoint: str) -> None:
    parsed = urlsplit(endpoint)
    host = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme in {"https", "rediss", "bolt+s", "neo4j+s"}:
        return
    if host not in _PLAINTEXT_DEVELOPMENT_HOSTS:
        raise ValidationError(
            "Plaintext system probes are restricted to fixed local development hosts."
        )


async def _reject_unsafe_destination(
    host: str,
    port: int,
    *,
    allowed_hosts: tuple[str, ...],
) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
    normalized_host = host.rstrip(".").lower()
    if normalized_host not in allowed_hosts:
        raise ValidationError("The saved system host is not in the operator probe allowlist.")
    try:
        async with asyncio.timeout(2.0):
            addresses = await asyncio.get_running_loop().getaddrinfo(
                host,
                port,
                type=0,
            )
    except (TimeoutError, OSError) as error:
        raise ValidationError("The saved system host could not be resolved.") from error
    if not addresses:
        raise ValidationError("The saved system host could not be resolved.")
    validated: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for address in addresses:
        raw = address[4][0]
        try:
            value = ipaddress.ip_address(raw)
        except ValueError as error:
            raise ValidationError(
                "The saved system host resolved to an invalid address."
            ) from error
        if value.is_link_local or value.is_multicast or value.is_unspecified or value.is_reserved:
            raise ValidationError("The saved system host resolves to a forbidden network range.")
        validated.append(value)
    return tuple(validated)


def _require_private_intranet_destination(
    addresses: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...],
) -> None:
    """Require an operator-selected LLM endpoint to stay inside the private network."""

    if not addresses:
        raise ValidationError("The intranet LLM host could not be resolved.")
    for value in addresses:
        if not value.is_private or value.is_loopback or value.is_link_local:
            raise ValidationError(
                "The intranet LLM host must resolve only to private non-loopback addresses."
            )


def _probe_url(endpoint: str, path: str) -> str:
    parsed = urlsplit(endpoint)
    base_path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, f"{base_path}{path}", "", ""))


def _configured_model(document: Mapping[str, Any]) -> str | None:
    direct = document.get("model")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    options = document.get("options")
    if isinstance(options, Mapping):
        model_name = options.get("model_name")
        if isinstance(model_name, str) and model_name.strip():
            return model_name.strip()
    return None


def _llm_connection_mode(
    document: Mapping[str, Any],
) -> Literal["LOCAL_OLLAMA", "INTRANET_OPENAI_COMPATIBLE"]:
    value = document.get("connection_mode", "LOCAL_OLLAMA")
    if value == "LOCAL_OLLAMA":
        return "LOCAL_OLLAMA"
    if value == "INTRANET_OPENAI_COMPATIBLE":
        return "INTRANET_OPENAI_COMPATIBLE"
    raise ValidationError("The saved LLM connection mode is invalid.")


def _secret_reference(document: Mapping[str, Any], key: str) -> str:
    references = document.get("secret_references")
    if not isinstance(references, Mapping):
        raise ValidationError("The saved system configuration has no secret references.")
    value = references.get(key)
    if not isinstance(value, str) or not value.startswith("file:/run/secrets/"):
        raise ValidationError("System credentials must use a Docker secret file reference.")
    return value


def _neo4j_credentials(raw: str) -> tuple[str, str]:
    username, separator, password = raw.strip().partition("/")
    if separator != "/" or not username or not password:
        raise ValidationError("The Neo4j credential secret must contain username/password.")
    return username, password


def _redis_config_value(document: Mapping[object, object], key: str) -> str:
    for raw_key, raw_value in document.items():
        normalized_key = raw_key.decode() if isinstance(raw_key, bytes) else str(raw_key)
        if normalized_key == key:
            return raw_value.decode() if isinstance(raw_value, bytes) else str(raw_value)
    return ""


def _validated_embedding(payload: object) -> bool:
    if not isinstance(payload, Mapping):
        return False
    rows = payload.get("data")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
        return False
    vector = rows[0].get("embedding")
    if not isinstance(vector, list) or not 0 < len(vector) <= 16_384:
        return False
    for value in vector:
        if not isinstance(value, int | float) or not -1_000_000 < value < 1_000_000:
            return False
    return True


def _validated_chat_completion(payload: object) -> bool:
    if not isinstance(payload, Mapping):
        return False
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], Mapping):
        return False
    message = choices[0].get("message")
    if not isinstance(message, Mapping):
        return False
    content_text = message.get("content")
    if not isinstance(content_text, str):
        return False
    try:
        content = json.loads(content_text)
    except ValueError:
        return False
    return isinstance(content, dict) and set(content) == {"status"} and content["status"] == "ok"


def _validated_reranking(payload: object, *, document_count: int, top_n: int) -> bool:
    if not isinstance(payload, Mapping):
        return False
    results = payload.get("results")
    if not isinstance(results, list) or not 0 < len(results) <= top_n:
        return False
    indexes: list[int] = []
    scores: list[float] = []
    for item in results:
        if not isinstance(item, Mapping):
            return False
        index = item.get("index")
        score = item.get("relevance_score")
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or not 0 <= index < document_count
            or not isinstance(score, int | float)
            or isinstance(score, bool)
            or not math.isfinite(float(score))
            or not 0 <= float(score) <= 1
        ):
            return False
        indexes.append(index)
        scores.append(float(score))
    return len(set(indexes)) == len(indexes) and scores == sorted(scores, reverse=True)


async def _bounded_http_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    timeout_seconds: float,
    headers: Mapping[str, str] | None = None,
    json_document: object = None,
) -> httpx.Response:
    maximum_bytes = 1024 * 1024
    async with asyncio.timeout(timeout_seconds):
        async with client.stream(
            method,
            url,
            headers=headers,
            json=json_document,
        ) as response:
            raw_length = response.headers.get("content-length")
            if raw_length is not None:
                try:
                    content_length = int(raw_length)
                except ValueError as error:
                    raise ValidationError(
                        "The saved system endpoint returned an invalid response length."
                    ) from error
                if content_length > maximum_bytes:
                    raise ValidationError(
                        "The saved system endpoint response exceeded the one MiB limit."
                    )
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > maximum_bytes:
                    raise ValidationError(
                        "The saved system endpoint response exceeded the one MiB limit."
                    )
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                content=bytes(body),
                request=response.request,
            )


async def _authenticated_neo4j_probe(
    endpoint: str,
    username: str,
    password: str,
    database: str,
    timeout_seconds: float,
) -> int:
    driver = AsyncGraphDatabase.driver(
        endpoint,
        auth=(username, password),
        connection_timeout=timeout_seconds,
        max_connection_pool_size=1,
    )
    try:
        await driver.verify_connectivity()

        async def query(transaction: Any) -> int:
            result = await transaction.run("RETURN 1 AS probe")
            row = await result.single(strict=True)
            return int(row["probe"])

        async with driver.session(database=database) as session:
            return await session.execute_read(query)
    finally:
        try:
            async with asyncio.timeout(min(timeout_seconds, 1.0)):
                await driver.close()
        except TimeoutError:
            pass


async def _authenticated_s3_head_bucket(
    endpoint: str,
    region: str,
    access_key: str,
    secret_key: str,
    bucket: str,
    timeout_seconds: float,
) -> None:
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(
            signature_version="s3v4",
            connect_timeout=timeout_seconds,
            read_timeout=timeout_seconds,
            retries={"max_attempts": 1, "mode": "standard"},
            s3={"addressing_style": "path"},
        ),
    )
    try:
        await asyncio.to_thread(client.head_bucket, Bucket=bucket)
    finally:
        client.close()


async def probe_system_configuration(
    *,
    system_id: str,
    document: Mapping[str, Any],
    client: httpx.AsyncClient | None = None,
    secret_resolver: SecretResolver | None = None,
    neo4j_query: Callable[[str, str, str, str, float], Awaitable[int]] = (
        _authenticated_neo4j_probe
    ),
    redis_factory: Callable[..., Redis] = Redis.from_url,
    s3_head_bucket: Callable[[str, str, str, str, str, float], Awaitable[None]] = (
        _authenticated_s3_head_bucket
    ),
    allowed_hosts: tuple[str, ...] = (),
) -> SystemConfigurationProbeResult:
    """Probe one saved, allowlisted development profile without accepting a request URL.

    HTTP systems use fixed routes owned by the server. Activated inference profiles execute one
    bounded request, and Neo4j executes an authenticated constant query. Request-supplied paths or
    query text are never accepted.
    """

    started = time.monotonic()
    endpoint = _endpoint(document)
    connection_mode: object = (
        document.get("connection_mode", "LOCAL_OLLAMA")
        if system_id in {"LLM_CHAT_MODEL", "LLM_EMBEDDING", "LLM_RERANKER"}
        else None
    )
    references = document.get("secret_references", {})
    if not isinstance(references, Mapping):
        raise ValidationError("The saved system secret references are invalid.")
    try:
        require_canonical_secret_references(
            system_id,
            {str(key): str(value) for key, value in references.items()},
            connection_mode=connection_mode,
        )
    except ValueError as error:
        raise ValidationError(str(error)) from error
    normalized_allowed_hosts = tuple(value.rstrip(".").lower() for value in allowed_hosts)
    if system_id in {"REDIS_CACHE", "REDIS_DELIVERY"}:
        _, host, port = _validated_url(endpoint, schemes={"redis", "rediss"})
        await _reject_unsafe_destination(
            host,
            port,
            allowed_hosts=normalized_allowed_hosts,
        )
        _require_tls_for_nonlocal_endpoint(endpoint)
        password = (secret_resolver or SecretResolver()).resolve(
            _secret_reference(document, "password")
        )
        redis_client = redis_factory(
            endpoint,
            password=password,
            decode_responses=False,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        try:
            if not await redis_client.ping():
                raise ValidationError("The saved Redis endpoint did not return PONG.")
            policy_document = await redis_client.config_get("maxmemory-policy")
            policy = _redis_config_value(policy_document, "maxmemory-policy")
            expected_policy = "allkeys-lfu" if system_id == "REDIS_CACHE" else "noeviction"
            if policy != expected_policy:
                raise ValidationError(
                    f"The saved Redis endpoint requires maxmemory-policy={expected_policy}."
                )
            if system_id == "REDIS_DELIVERY":
                appendonly_document = await redis_client.config_get("appendonly")
                if _redis_config_value(appendonly_document, "appendonly") != "yes":
                    raise ValidationError("The delivery Redis endpoint requires appendonly=yes.")
        except ValidationError:
            raise
        except Exception as error:
            raise ValidationError(
                "The saved Redis endpoint or credential is unavailable."
            ) from error
        finally:
            await redis_client.aclose()
        return SystemConfigurationProbeResult(
            status="AVAILABLE",
            scope="REDIS_POLICY",
            latency_ms=max(0, round((time.monotonic() - started) * 1000)),
            detail="Redis accepted the credential and passed its fixed role-policy probe.",
        )
    if system_id == "S3_STORAGE":
        _, host, port = _validated_url(endpoint, schemes={"http", "https"})
        await _reject_unsafe_destination(
            host,
            port,
            allowed_hosts=normalized_allowed_hosts,
        )
        _require_tls_for_nonlocal_endpoint(endpoint)
        region = document.get("region")
        buckets = document.get("buckets")
        if not isinstance(region, str) or not region.strip():
            raise ValidationError("The saved S3 configuration has no region.")
        if not isinstance(buckets, Mapping):
            raise ValidationError("The saved S3 configuration has no buckets mapping.")
        bucket = buckets.get("quarantine")
        if not isinstance(bucket, str) or not bucket.strip():
            raise ValidationError("The saved S3 configuration has no quarantine bucket.")
        resolver = secret_resolver or SecretResolver()
        access_key = resolver.resolve(_secret_reference(document, "access_key"))
        secret_key = resolver.resolve(_secret_reference(document, "secret_key"))
        options = document.get("options")
        configured_timeout = (
            options.get("timeout_seconds") if isinstance(options, Mapping) else None
        )
        timeout = (
            min(max(float(configured_timeout), 1.0), 15.0)
            if isinstance(configured_timeout, int | float)
            else 5.0
        )
        try:
            await s3_head_bucket(
                endpoint,
                region.strip(),
                access_key,
                secret_key,
                bucket.strip(),
                timeout,
            )
        except ValidationError:
            raise
        except (BotoCoreError, ClientError, OSError) as error:
            raise ValidationError(
                "The saved S3 bucket or mounted credentials are unavailable."
            ) from error
        return SystemConfigurationProbeResult(
            status="AVAILABLE",
            scope="S3_HEAD_BUCKET",
            latency_ms=max(0, round((time.monotonic() - started) * 1000)),
            detail="S3 accepted the mounted credential for the fixed quarantine bucket probe.",
        )
    if system_id == "NEO4J":
        _, host, port = _validated_url(
            endpoint,
            schemes={"bolt", "neo4j", "bolt+s", "neo4j+s"},
        )
        await _reject_unsafe_destination(
            host,
            port,
            allowed_hosts=normalized_allowed_hosts,
        )
        _require_tls_for_nonlocal_endpoint(endpoint)
        resolver = secret_resolver or SecretResolver()
        username, password = _neo4j_credentials(
            resolver.resolve(_secret_reference(document, "credential"))
        )
        options = document.get("options")
        timeout = 3.0
        if isinstance(options, Mapping) and isinstance(
            options.get("connection_timeout_seconds"), int | float
        ):
            timeout = min(max(float(options["connection_timeout_seconds"]), 1.0), 30.0)
        database = document.get("database")
        if not isinstance(database, str) or not database.strip():
            raise ValidationError("The saved Neo4j configuration has no database name.")
        try:
            async with asyncio.timeout(timeout):
                result = await neo4j_query(
                    endpoint,
                    username,
                    password,
                    database.strip(),
                    timeout,
                )
            if result != 1:
                raise ValidationError("The authenticated Neo4j probe returned invalid data.")
        except ValidationError:
            raise
        except Exception as error:
            raise ValidationError(
                "The saved Neo4j credentials or database are unavailable."
            ) from error
        return SystemConfigurationProbeResult(
            status="AVAILABLE",
            scope="AUTHENTICATED_QUERY",
            latency_ms=max(0, round((time.monotonic() - started) * 1000)),
            detail=(
                "Neo4j accepted the Docker secret credential and returned the fixed query result."
            ),
        )

    inference_probe = system_id in {
        "LLM_CHAT_MODEL",
        "LLM_EMBEDDING",
        "LLM_RERANKER",
    }
    path_and_scope: tuple[str, ProbeScope] | None = (
        ("/chat/completions", "MODEL_INFERENCE")
        if system_id == "LLM_CHAT_MODEL"
        else ("/embeddings", "EMBEDDING_INFERENCE")
        if system_id == "LLM_EMBEDDING"
        else ("/rerank", "RERANKING_INFERENCE")
        if system_id == "LLM_RERANKER"
        else _HTTP_PROBE_PATHS.get(system_id)
    )
    if path_and_scope is None:
        raise ValidationError("The system configuration identifier is not probeable.")
    path, scope = path_and_scope
    _, host, port = _validated_url(endpoint, schemes={"http", "https"})
    validated_addresses = await _reject_unsafe_destination(
        host,
        port,
        allowed_hosts=normalized_allowed_hosts,
    )
    _require_tls_for_nonlocal_endpoint(endpoint)
    if system_id == "LLM_RERANKER":
        if document.get("connection_mode") != "INTRANET_RERANK_V1":
            raise ValidationError("The saved reranker connection mode is invalid.")
        connection_mode = "INTRANET_RERANK_V1"
    else:
        connection_mode = _llm_connection_mode(document) if inference_probe else "LOCAL_OLLAMA"
    api_key: str | None = None
    if connection_mode in {"INTRANET_OPENAI_COMPATIBLE", "INTRANET_RERANK_V1"}:
        parsed_endpoint = urlsplit(endpoint)
        if parsed_endpoint.scheme != "https" or parsed_endpoint.path.rstrip("/") != "/v1":
            probe_name = (
                "Private reranking probes"
                if system_id == "LLM_RERANKER"
                else "Intranet OpenAI-compatible probes"
            )
            raise ValidationError(f"{probe_name} require an HTTPS endpoint ending in /v1.")
        _require_private_intranet_destination(validated_addresses)
        api_key = (secret_resolver or SecretResolver()).resolve(
            _secret_reference(document, "api_key")
        )
    request_url = _probe_url(endpoint, path)
    owns_client = client is None
    options = document.get("options")
    configured_timeout = options.get("timeout_seconds") if isinstance(options, Mapping) else None
    timeout_seconds = (
        min(max(float(configured_timeout), 5.0), 120.0)
        if isinstance(configured_timeout, int | float)
        else 60.0
        if inference_probe
        else 5.0
    )
    active_client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_seconds, connect=3.0),
        follow_redirects=False,
        trust_env=False,
    )
    try:
        model = _configured_model(document)
        if system_id == "LLM_CHAT_MODEL":
            response = await _bounded_http_request(
                active_client,
                "POST",
                request_url,
                timeout_seconds=timeout_seconds,
                headers={"Authorization": f"Bearer {api_key}"} if api_key else None,
                json_document={
                    "model": model,
                    "temperature": 0,
                    "messages": [
                        {
                            "role": "system",
                            "content": "Return exactly the requested JSON object.",
                        },
                        {"role": "user", "content": 'Return {"status":"ok"}.'},
                    ],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "datariver_system_probe_v1",
                            "strict": True,
                            "schema": {
                                "type": "object",
                                "properties": {"status": {"type": "string", "enum": ["ok"]}},
                                "required": ["status"],
                                "additionalProperties": False,
                            },
                        },
                    },
                },
            )
        elif system_id == "LLM_EMBEDDING":
            response = await _bounded_http_request(
                active_client,
                "POST",
                request_url,
                timeout_seconds=timeout_seconds,
                headers={"Authorization": f"Bearer {api_key}"} if api_key else None,
                json_document={"model": model, "input": ["DataRiver connectivity probe"]},
            )
        elif system_id == "LLM_RERANKER":
            probe_documents = [
                "Data catalog metadata and governed lineage",
                "Unrelated weather forecast",
            ]
            top_n = 2
            if isinstance(options, Mapping) and isinstance(options.get("top_n"), int):
                top_n = min(max(int(options["top_n"]), 1), len(probe_documents))
            response = await _bounded_http_request(
                active_client,
                "POST",
                request_url,
                timeout_seconds=timeout_seconds,
                headers={"Authorization": f"Bearer {api_key}"} if api_key else None,
                json_document={
                    "model": model,
                    "query": "governed data catalog metadata",
                    "documents": probe_documents,
                    "top_n": top_n,
                },
            )
        else:
            response = await _bounded_http_request(
                active_client,
                "GET",
                request_url,
                timeout_seconds=timeout_seconds,
            )
    except (TimeoutError, httpx.HTTPError) as error:
        raise ValidationError("The saved system endpoint is not reachable.") from error
    finally:
        if owns_client:
            await active_client.aclose()
    latency_ms = max(0, round((time.monotonic() - started) * 1000))
    if response.status_code in {401, 403}:
        if api_key is not None:
            credential_name = (
                "private reranking credential"
                if system_id == "LLM_RERANKER"
                else "intranet LLM credential"
            )
            return SystemConfigurationProbeResult(
                status="UNAVAILABLE",
                scope=scope,
                latency_ms=latency_ms,
                detail=f"The configured {credential_name} was rejected by the fixed probe.",
            )
        return SystemConfigurationProbeResult(
            status="AUTHENTICATION_REQUIRED",
            scope=scope,
            latency_ms=latency_ms,
            detail="The endpoint is reachable but did not accept an unauthenticated health probe.",
        )
    if not 200 <= response.status_code < 300:
        return SystemConfigurationProbeResult(
            status="UNAVAILABLE",
            scope=scope,
            latency_ms=latency_ms,
            detail=f"The fixed probe route returned HTTP {response.status_code}.",
        )
    try:
        response_payload: object = response.json()
    except ValueError:
        response_payload = None
    if scope == "MODEL_INFERENCE" and not _validated_chat_completion(response_payload):
        return SystemConfigurationProbeResult(
            status="UNAVAILABLE",
            scope=scope,
            latency_ms=latency_ms,
            detail="The configured chat model did not satisfy the fixed strict JSON probe.",
        )
    if scope == "EMBEDDING_INFERENCE" and not _validated_embedding(response_payload):
        return SystemConfigurationProbeResult(
            status="UNAVAILABLE",
            scope=scope,
            latency_ms=latency_ms,
            detail="The configured embedding model returned an invalid vector.",
        )
    if scope == "RERANKING_INFERENCE":
        options = document.get("options")
        configured_top_n = options.get("top_n") if isinstance(options, Mapping) else None
        top_n = min(max(int(configured_top_n), 1), 2) if isinstance(configured_top_n, int) else 2
        if not _validated_reranking(
            response_payload,
            document_count=2,
            top_n=top_n,
        ):
            return SystemConfigurationProbeResult(
                status="UNAVAILABLE",
                scope=scope,
                latency_ms=latency_ms,
                detail="The configured reranker returned an invalid ordered score result.",
            )
    return SystemConfigurationProbeResult(
        status="AVAILABLE",
        scope=scope,
        latency_ms=latency_ms,
        detail="The saved configuration passed its fixed server-side probe.",
    )
