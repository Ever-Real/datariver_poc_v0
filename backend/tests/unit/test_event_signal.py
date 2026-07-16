from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import cast
from uuid import UUID, uuid4

import pytest

from datariver.infrastructure.cache.valkey import DeliveredEvent, ValkeyEventDelivery
from datariver.infrastructure.db.outbox import SqlInboxStore
from datariver.workers.event_signal import EventSignalConsumer


class FakeDelivery:
    def __init__(self, event: DeliveredEvent) -> None:
        self.event = event
        self.acknowledged: list[tuple[str, str]] = []

    async def read_events(self, **_: object) -> tuple[DeliveredEvent, ...]:
        return (self.event,)

    async def acknowledge(self, *, group: str, message_id: str) -> None:
        self.acknowledged.append((group, message_id))


class FakeInbox:
    def __init__(self) -> None:
        self.completed: list[tuple[str, UUID, str]] = []

    async def accept(self, *, consumer: str, event_id: UUID, workspace_id: UUID) -> bool:
        return True

    async def complete(
        self, *, consumer: str, event_id: UUID, workspace_id: UUID, result_hash: str
    ) -> None:
        del workspace_id
        self.completed.append((consumer, event_id, result_hash))


@pytest.mark.asyncio
async def test_relevant_event_is_deduplicated_completed_and_acknowledged() -> None:
    event = DeliveredEvent(
        message_id="1-0",
        event_id=uuid4(),
        event_type="registration.upload.completion_queued.v1",
        workspace_id=uuid4(),
        aggregate_id=uuid4(),
    )
    delivery = FakeDelivery(event)
    inbox = FakeInbox()
    calls = 0

    async def handler() -> bool:
        nonlocal calls
        calls += 1
        return True

    consumer = EventSignalConsumer(
        delivery=cast(ValkeyEventDelivery, delivery),
        inbox=cast(SqlInboxStore, inbox),
        group="upload-completion-v1",
        consumer="worker-1",
        relevant_event_types=frozenset({event.event_type}),
    )

    count = await consumer.wait_and_trigger(timeout_seconds=1, handler=handler)

    assert count == 1
    assert calls == 1
    assert len(inbox.completed) == 1
    assert delivery.acknowledged == [("upload-completion-v1", "1-0")]


@pytest.mark.asyncio
async def test_irrelevant_event_is_drained_without_running_handler() -> None:
    event = DeliveredEvent("2-0", uuid4(), "other.v1", uuid4(), uuid4())
    delivery = FakeDelivery(event)
    inbox = FakeInbox()

    async def fail_if_called() -> bool:
        raise AssertionError("irrelevant event invoked the business handler")

    handler: Callable[[], Awaitable[bool]] = fail_if_called
    consumer = EventSignalConsumer(
        delivery=cast(ValkeyEventDelivery, delivery),
        inbox=cast(SqlInboxStore, inbox),
        group="upload-completion-v1",
        consumer="worker-1",
        relevant_event_types=frozenset({"registration.upload.completion_queued.v1"}),
    )

    assert await consumer.wait_and_trigger(timeout_seconds=1, handler=handler) == 1
    assert len(inbox.completed) == 1
