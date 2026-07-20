from __future__ import annotations

import asyncio
import socket

import structlog

from datariver.application.services.upload_completion import UploadCompletionWorker
from datariver.config import get_settings
from datariver.infrastructure.db.outbox import SqlInboxStore
from datariver.infrastructure.db.registration import SqlUploadCompletionStore
from datariver.infrastructure.system_configuration_runtime import (
    resolve_activated_system_configuration,
)
from datariver.workers.container import build_upload_container
from datariver.workers.event_signal import EventSignalConsumer

LOGGER = structlog.get_logger()


async def run() -> None:
    settings = await resolve_activated_system_configuration(get_settings(), database_role="upload")
    container = build_upload_container(settings)
    worker = UploadCompletionWorker(
        store=SqlUploadCompletionStore(container.database.session_factory),
        object_store=container.object_store,
        lease_seconds=settings.upload_lease_seconds,
        maximum_attempts=settings.upload_maximum_attempts,
    )
    signals = EventSignalConsumer(
        delivery=container.event_delivery,
        inbox=SqlInboxStore(container.database.session_factory),
        group="upload-completion-v1",
        consumer=f"upload-completion:{socket.gethostname()}",
        relevant_event_types=frozenset({"registration.upload.completion_queued.v1"}),
        visibility_timeout_seconds=settings.upload_lease_seconds,
    )
    try:
        while True:
            try:
                processed = await worker.run_once()
                if not processed:
                    await signals.wait_and_trigger(
                        timeout_seconds=settings.worker_poll_seconds,
                        handler=worker.run_once,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                await LOGGER.aexception("upload_worker_cycle_failed")
                await asyncio.sleep(min(settings.worker_poll_seconds * 4, 10))
    finally:
        await container.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
