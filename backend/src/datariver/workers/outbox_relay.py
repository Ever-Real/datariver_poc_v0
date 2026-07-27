from __future__ import annotations

import asyncio

import structlog

from datariver.config import get_settings
from datariver.infrastructure.db.outbox import SqlOutboxRelayStore
from datariver.workers.container import build_relay_container

LOGGER = structlog.get_logger()


async def run() -> None:
    settings = get_settings()
    container = build_relay_container(settings)
    store = SqlOutboxRelayStore(container.database.session_factory)
    try:
        while True:
            try:
                events = await store.lease_batch(
                    limit=100, lease_seconds=settings.outbox_lease_seconds
                )
                for event in events:
                    try:
                        await container.event_delivery.publish_event_id(
                            event_id=event.event_id,
                            event_type=event.event_type,
                            workspace_id=event.workspace_id,
                            aggregate_id=event.aggregate_id,
                        )
                        await store.mark_published(event.event_id)
                    except asyncio.CancelledError:
                        raise
                    except Exception as error:
                        await store.mark_failed(
                            event.event_id,
                            error_code=type(error).__name__,
                            maximum_attempts=settings.outbox_maximum_attempts,
                        )
                        await LOGGER.aexception(
                            "outbox_event_delivery_failed", event_id=str(event.event_id)
                        )
                if not events:
                    await asyncio.sleep(settings.worker_poll_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                await LOGGER.aexception("outbox_relay_cycle_failed")
                await asyncio.sleep(min(settings.worker_poll_seconds * 4, 10))
    finally:
        await container.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
