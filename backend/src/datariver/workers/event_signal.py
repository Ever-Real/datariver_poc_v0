from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable

from datariver.infrastructure.cache.valkey import ValkeyEventDelivery
from datariver.infrastructure.db.outbox import SqlInboxStore


class EventSignalConsumer:
    """Uses Valkey for low-latency wakeups while PostgreSQL remains canonical."""

    def __init__(
        self,
        *,
        delivery: ValkeyEventDelivery,
        inbox: SqlInboxStore,
        group: str,
        consumer: str,
        relevant_event_types: frozenset[str],
        visibility_timeout_seconds: int = 60,
    ) -> None:
        self._delivery = delivery
        self._inbox = inbox
        self._group = group
        self._consumer = consumer
        self._relevant_event_types = relevant_event_types
        self._visibility_timeout_milliseconds = visibility_timeout_seconds * 1000

    async def wait_and_trigger(
        self, *, timeout_seconds: float, handler: Callable[[], Awaitable[bool]]
    ) -> int:
        events = await self._delivery.read_events(
            group=self._group,
            consumer=self._consumer,
            block_milliseconds=max(1, int(timeout_seconds * 1000)),
            visibility_timeout_milliseconds=self._visibility_timeout_milliseconds,
        )
        for event in events:
            should_process = await self._inbox.accept(
                consumer=self._group,
                event_id=event.event_id,
                workspace_id=event.workspace_id,
            )
            processed = False
            if should_process and event.event_type in self._relevant_event_types:
                processed = await handler()
            if should_process:
                result_hash = hashlib.sha256(f"{event.event_type}:{processed}".encode()).hexdigest()
                await self._inbox.complete(
                    consumer=self._group,
                    event_id=event.event_id,
                    result_hash=result_hash,
                )
            await self._delivery.acknowledge(
                group=self._group,
                message_id=event.message_id,
            )
        return len(events)
