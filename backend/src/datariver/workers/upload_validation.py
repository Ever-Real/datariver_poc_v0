from __future__ import annotations

import asyncio
import socket

import structlog

from datariver.application.services.upload_validation import UploadValidationWorker
from datariver.config import get_settings
from datariver.infrastructure.db.outbox import SqlInboxStore
from datariver.infrastructure.db.registration import SqlUploadValidationStore
from datariver.workers.container import build_upload_container
from datariver.workers.event_signal import EventSignalConsumer

LOGGER = structlog.get_logger()


async def run() -> None:
    settings = get_settings()
    container = build_upload_container(settings)
    worker = UploadValidationWorker(
        store=SqlUploadValidationStore(container.database.session_factory),
        object_store=container.object_store,
        accepted_bucket=settings.s3_bucket_accepted,
        lease_seconds=settings.upload_validation_lease_seconds,
        maximum_attempts=settings.upload_validation_maximum_attempts,
    )
    signals = EventSignalConsumer(
        delivery=container.event_delivery,
        inbox=SqlInboxStore(container.database.session_factory),
        group="upload-validation-v1",
        consumer=f"upload-validation:{socket.gethostname()}",
        relevant_event_types=frozenset({"registration.upload.quarantined.v1"}),
        visibility_timeout_seconds=settings.upload_validation_lease_seconds,
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
                await LOGGER.aexception("upload_validation_worker_cycle_failed")
                await asyncio.sleep(min(settings.worker_poll_seconds * 4, 10))
    finally:
        await container.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
