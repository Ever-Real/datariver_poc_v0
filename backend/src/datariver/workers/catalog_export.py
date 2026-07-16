from __future__ import annotations

import asyncio
import socket

import structlog

from datariver.application.services.catalog_export_worker import CatalogExportWorker
from datariver.config import get_settings
from datariver.infrastructure.db.catalog_export import SqlCatalogExportWorkerStore
from datariver.infrastructure.db.outbox import SqlInboxStore
from datariver.workers.container import build_catalog_export_container
from datariver.workers.event_signal import EventSignalConsumer

LOGGER = structlog.get_logger()


async def run() -> None:
    settings = get_settings()
    container = build_catalog_export_container(settings)
    consumer_name = f"catalog-export:{socket.gethostname()}"
    worker = CatalogExportWorker(
        store=SqlCatalogExportWorkerStore(container.database.session_factory),
        object_store=container.object_store,
        export_bucket=settings.s3_bucket_exports,
        worker_id=consumer_name,
        system_actor_id=settings.export_worker_subject_id,
        lease_seconds=settings.catalog_export_lease_seconds,
        maximum_attempts=settings.catalog_export_maximum_attempts,
        page_size=settings.catalog_export_page_size,
        maximum_rows=settings.catalog_export_maximum_rows,
        maximum_bytes=settings.catalog_export_maximum_bytes,
    )
    signals = EventSignalConsumer(
        delivery=container.event_delivery,
        inbox=SqlInboxStore(container.database.session_factory),
        group="catalog-export-v1",
        consumer=consumer_name,
        relevant_event_types=frozenset({"catalog.export.requested.v1"}),
        visibility_timeout_seconds=settings.catalog_export_lease_seconds,
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
                await LOGGER.aexception("catalog_export_worker_cycle_failed")
                await asyncio.sleep(min(settings.worker_poll_seconds * 4, 10))
    finally:
        await container.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
