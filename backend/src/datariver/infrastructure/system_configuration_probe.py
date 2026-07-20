from __future__ import annotations

import asyncio
import ipaddress
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

import httpx
from neo4j import AsyncGraphDatabase

from datariver.domain.common import ValidationError
from datariver.infrastructure.secrets import SecretResolver

ProbeStatus = Literal["AVAILABLE", "AUTHENTICATION_REQUIRED", "UNAVAILABLE"]
ProbeScope = Literal[
    "HTTP_HEALTH",
    "MODEL_DISCOVERY",
    "MODEL_INFERENCE",
    "EMBEDDING_INFERENCE",
    "AUTHENTICATED_QUERY",
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
    "S3_STORAGE": ("/", "HTTP_HEALTH"),
    "LLM_RERANKER": ("/models", "MODEL_DISCOVERY"),
    "PROMETHEUS": ("/-/healthy", "HTTP_HEALTH"),
    "GRAFANA_DASHBOARD": ("/api/health", "HTTP_HEALTH"),
}


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
    if parsed.scheme in {"bolt", "neo4j"}:
        default_port = 7687
    return endpoint, parsed.hostname, parsed.port or default_port


async def _reject_unsafe_destination(host: str, port: int) -> None:
    try:
        addresses = await asyncio.get_running_loop().getaddrinfo(
            host,
            port,
            type=0,
        )
    except OSError as error:
        raise ValidationError("The saved system host could not be resolved.") from error
    if not addresses:
        raise ValidationError("The saved system host could not be resolved.")
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


def _available_model_ids(payload: object) -> set[str]:
    if not isinstance(payload, Mapping):
        return set()
    data = payload.get("data")
    if not isinstance(data, list):
        return set()
    return {
        str(item["id"])
        for item in data
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }


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
        await driver.close()


async def probe_system_configuration(
    *,
    system_id: str,
    document: Mapping[str, Any],
    client: httpx.AsyncClient | None = None,
    secret_resolver: SecretResolver | None = None,
    neo4j_query: Callable[[str, str, str, str, float], Awaitable[int]] = (
        _authenticated_neo4j_probe
    ),
) -> SystemConfigurationProbeResult:
    """Probe one saved, allowlisted development profile without accepting a request URL.

    HTTP systems use fixed routes owned by the server. Activated inference profiles execute one
    bounded request, and Neo4j executes an authenticated constant query. Request-supplied paths or
    query text are never accepted.
    """

    started = time.monotonic()
    endpoint = _endpoint(document)
    if system_id == "NEO4J":
        _, host, port = _validated_url(endpoint, schemes={"bolt", "neo4j"})
        await _reject_unsafe_destination(host, port)
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

    inference_probe = system_id in {"LLM_CHAT_MODEL", "LLM_EMBEDDING"}
    path_and_scope: tuple[str, ProbeScope] | None = (
        ("/chat/completions", "MODEL_INFERENCE")
        if system_id == "LLM_CHAT_MODEL"
        else ("/embeddings", "EMBEDDING_INFERENCE")
        if system_id == "LLM_EMBEDDING"
        else _HTTP_PROBE_PATHS.get(system_id)
    )
    if path_and_scope is None:
        raise ValidationError("The system configuration identifier is not probeable.")
    path, scope = path_and_scope
    _, host, port = _validated_url(endpoint, schemes={"http", "https"})
    await _reject_unsafe_destination(host, port)
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
            response = await active_client.post(
                request_url,
                json={
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
            response = await active_client.post(
                request_url,
                json={"model": model, "input": ["DataRiver connectivity probe"]},
            )
        else:
            response = await active_client.get(request_url)
    except httpx.HTTPError as error:
        raise ValidationError("The saved system endpoint is not reachable.") from error
    finally:
        if owns_client:
            await active_client.aclose()
    latency_ms = max(0, round((time.monotonic() - started) * 1000))
    if response.status_code in {401, 403}:
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
    if scope == "MODEL_DISCOVERY":
        configured_model = _configured_model(document)
        if configured_model is None:
            return SystemConfigurationProbeResult(
                status="UNAVAILABLE",
                scope=scope,
                latency_ms=latency_ms,
                detail="The saved LLM profile has no model identity.",
            )
        try:
            model_ids = _available_model_ids(response_payload)
        except (TypeError, ValueError):
            model_ids = set()
        if configured_model not in model_ids:
            return SystemConfigurationProbeResult(
                status="UNAVAILABLE",
                scope=scope,
                latency_ms=latency_ms,
                detail="The configured model was not returned by the fixed model discovery route.",
            )
    return SystemConfigurationProbeResult(
        status="AVAILABLE",
        scope=scope,
        latency_ms=latency_ms,
        detail="The saved configuration passed its fixed server-side probe.",
    )
