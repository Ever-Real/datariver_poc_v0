from __future__ import annotations

import re
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

import orjson
from redis.asyncio import Redis
from redis.exceptions import RedisError, ResponseError

from datariver.application.errors import ExternalDependencyError
from datariver.application.ports import Cache, ChatRequestBudgetGuard
from datariver.domain.common import RateLimitError


class CacheValueTooLarge(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DeliveredEvent:
    message_id: str
    event_id: UUID
    event_type: str
    workspace_id: UUID
    aggregate_id: UUID


_CHAT_BUDGET_SCRIPT = """
local requests = tonumber(redis.call('GET', KEYS[1]) or '0')
local tokens = tonumber(redis.call('GET', KEYS[2]) or '0')
local requested_tokens = tonumber(ARGV[1])
local request_limit = tonumber(ARGV[2])
local token_limit = tonumber(ARGV[3])
local window_seconds = tonumber(ARGV[4])
if requests + 1 > request_limit or tokens + requested_tokens > token_limit then
  local request_ttl = redis.call('TTL', KEYS[1])
  local token_ttl = redis.call('TTL', KEYS[2])
  return {0, math.max(request_ttl, token_ttl, 1)}
end
local next_requests = redis.call('INCR', KEYS[1])
local next_tokens = redis.call('INCRBY', KEYS[2], requested_tokens)
if next_requests == 1 then redis.call('EXPIRE', KEYS[1], window_seconds) end
if next_tokens == requested_tokens then redis.call('EXPIRE', KEYS[2], window_seconds) end
return {1, window_seconds}
"""


class RedisCache(Cache):
    """Redis-protocol cache adapter; the cache never owns canonical state."""

    def __init__(self, url: str, *, password: str, maximum_value_bytes: int) -> None:
        self._client: Redis = Redis.from_url(
            url,
            password=password,
            decode_responses=False,
            socket_connect_timeout=1,
            socket_timeout=2,
            health_check_interval=30,
        )
        self._maximum_value_bytes = maximum_value_bytes

    async def get_json(self, key: str) -> dict[str, Any] | list[Any] | None:
        value = await self._client.get(key)
        if value is None:
            return None
        if len(value) > self._maximum_value_bytes:
            await self._client.delete(key)
            return None
        result: object = orjson.loads(value)
        if not isinstance(result, (dict, list)):
            await self._client.delete(key)
            return None
        return result

    async def set_json(
        self, key: str, value: dict[str, Any] | list[Any], *, ttl_seconds: int
    ) -> None:
        encoded = orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
        if len(encoded) > self._maximum_value_bytes:
            raise CacheValueTooLarge("The cache value exceeds the configured maximum.")
        await self._client.set(key, encoded, ex=ttl_seconds)

    async def delete(self, *keys: str) -> int:
        if not keys:
            return 0
        result = await self._client.delete(*keys)
        return int(result)

    async def ping(self) -> bool:
        return bool(await self._client.ping())

    async def close(self) -> None:
        await self._client.aclose()


class RedisChatRequestBudgetGuard(ChatRequestBudgetGuard):
    """Atomic Chat admission guard on the deployment's no-eviction delivery Redis."""

    def __init__(self, url: str, *, password: str) -> None:
        self._client: Redis = Redis.from_url(
            url,
            password=password,
            decode_responses=False,
            socket_connect_timeout=1,
            socket_timeout=2,
            health_check_interval=30,
        )

    async def reserve(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        policy_scope: str,
        estimated_tokens: int,
        request_limit: int,
        token_limit: int,
        window_seconds: int,
    ) -> None:
        if (
            estimated_tokens < 1
            or request_limit < 1
            or token_limit < 1
            or window_seconds < 1
            or re.fullmatch(
                r"(?:static-floor-v1|governed-[0-9a-f]{8}-[0-9a-f]{4}-"
                r"[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}-"
                r"[1-9][0-9]*-[0-9]+-[0-9a-f]{64})",
                policy_scope,
            )
            is None
        ):
            raise ValueError("The Chat budget reservation bounds are invalid.")
        scope = f"{{{workspace_id}:{subject_id}}}"
        try:
            raw_result = await cast(
                Awaitable[Any],
                self._client.eval(
                    _CHAT_BUDGET_SCRIPT,
                    2,
                    f"datariver:chat-budget:v1:{scope}:policy-{policy_scope}:requests",
                    f"datariver:chat-budget:v1:{scope}:policy-{policy_scope}:tokens",
                    str(estimated_tokens),
                    str(request_limit),
                    str(token_limit),
                    str(window_seconds),
                ),
            )
        except RedisError as error:
            raise ExternalDependencyError(
                "The Chat rate and token budget guard is unavailable.",
                dependency="redis-delivery",
                retryable=True,
                provider_code="CHAT_BUDGET_UNAVAILABLE",
            ) from error
        if (
            not isinstance(raw_result, list)
            or len(raw_result) != 2
            or not all(isinstance(item, int) for item in raw_result)
        ):
            raise ExternalDependencyError(
                "The Chat rate and token budget guard returned an invalid result.",
                dependency="redis-delivery",
                retryable=True,
                provider_code="CHAT_BUDGET_INVALID_RESULT",
            )
        if raw_result[0] != 1:
            raise RateLimitError(
                "The Chat request or token budget for this user is exhausted.",
                details={"retry_after_seconds": max(1, raw_result[1])},
            )

    async def close(self) -> None:
        await self._client.aclose()


class RedisEventDelivery:
    """Short-lived Redis Streams delivery; PostgreSQL outbox/inbox stays canonical."""

    def __init__(self, url: str, *, password: str, stream_name: str = "datariver:events") -> None:
        self._client: Redis = Redis.from_url(
            url,
            password=password,
            decode_responses=False,
            socket_connect_timeout=1,
            socket_timeout=2,
            health_check_interval=30,
        )
        self._stream_name = stream_name

    async def publish_event_id(
        self,
        *,
        event_id: UUID,
        event_type: str,
        workspace_id: UUID,
        aggregate_id: UUID,
    ) -> str:
        message_id = await self._client.xadd(
            self._stream_name,
            {
                "event_id": str(event_id),
                "event_type": event_type,
                "workspace_id": str(workspace_id),
                "aggregate_id": str(aggregate_id),
            },
            maxlen=100_000,
            approximate=True,
        )
        return message_id.decode() if isinstance(message_id, bytes) else str(message_id)

    async def read_events(
        self,
        *,
        group: str,
        consumer: str,
        block_milliseconds: int,
        visibility_timeout_milliseconds: int,
        count: int = 20,
    ) -> tuple[DeliveredEvent, ...]:
        await self._ensure_group(group)
        claimed = await self._client.xautoclaim(
            self._stream_name,
            group,
            consumer,
            min_idle_time=visibility_timeout_milliseconds,
            start_id="0-0",
            count=count,
        )
        messages = claimed[1] if len(claimed) > 1 else []
        if not messages:
            streams = await self._client.xreadgroup(
                group,
                consumer,
                {self._stream_name: ">"},
                count=count,
                block=block_milliseconds,
            )
            messages = streams[0][1] if streams else []
        return tuple(self._event(message_id, fields) for message_id, fields in messages)

    async def acknowledge(self, *, group: str, message_id: str) -> None:
        await self._client.xack(self._stream_name, group, message_id)

    async def _ensure_group(self, group: str) -> None:
        try:
            await self._client.xgroup_create(self._stream_name, group, id="0", mkstream=True)
        except ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise

    @staticmethod
    def _event(message_id: bytes | str, fields: dict[bytes | str, bytes | str]) -> DeliveredEvent:
        def value(name: str) -> str:
            raw = fields.get(name.encode(), fields.get(name))
            if raw is None:
                raise ValueError(f"Redis event field is missing: {name}")
            return raw.decode() if isinstance(raw, bytes) else str(raw)

        return DeliveredEvent(
            message_id=message_id.decode() if isinstance(message_id, bytes) else str(message_id),
            event_id=UUID(value("event_id")),
            event_type=value("event_type"),
            workspace_id=UUID(value("workspace_id")),
            aggregate_id=UUID(value("aggregate_id")),
        )

    async def ping(self) -> bool:
        return bool(await self._client.ping())

    async def close(self) -> None:
        await self._client.aclose()
