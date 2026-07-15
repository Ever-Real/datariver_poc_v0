from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import orjson
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from datariver.application.ports import Cache


class CacheValueTooLarge(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DeliveredEvent:
    message_id: str
    event_id: UUID
    event_type: str
    workspace_id: UUID
    aggregate_id: UUID


class ValkeyCache(Cache):
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


class ValkeyEventDelivery:
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
                raise ValueError(f"Valkey event field is missing: {name}")
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
