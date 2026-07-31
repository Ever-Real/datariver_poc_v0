from __future__ import annotations

import asyncio
import socket

import structlog

from datariver.application.knowledge_pipeline_ports import KnowledgePipelineRuntime
from datariver.application.knowledge_source_job_contracts import KnowledgeSourceJobClaim
from datariver.application.services.knowledge_source_worker import KnowledgeSourceWorker
from datariver.config import get_settings
from datariver.infrastructure.db.knowledge_source_jobs import (
    SqlKnowledgeSourceJobWorkerStore,
)
from datariver.infrastructure.db.outbox import SqlInboxStore
from datariver.infrastructure.knowledge.document import BoundedKnowledgeDocumentParser
from datariver.infrastructure.knowledge.object_store import (
    ObjectStoreKnowledgeSourceReader,
)
from datariver.infrastructure.knowledge.runtime import build_knowledge_runtime_adapters
from datariver.workers.container import build_knowledge_source_container
from datariver.workers.event_signal import EventSignalConsumer

LOGGER = structlog.get_logger()


async def run() -> None:
    settings = get_settings()
    container = build_knowledge_source_container(settings)
    worker_name = f"knowledge-source:{socket.gethostname()}"

    async def resolve_runtime(_claim: KnowledgeSourceJobClaim) -> KnowledgePipelineRuntime:
        # The worker compares this deployment-owned binding with the immutable
        # claim pins before processing. Historical DB-profile pins therefore
        # fail closed instead of reviving a retired configuration source.
        return build_knowledge_runtime_adapters(settings)

    worker = KnowledgeSourceWorker(
        store=SqlKnowledgeSourceJobWorkerStore(
            container.database.session_factory,
            worker_subject_id=settings.knowledge_worker_subject_id,
        ),
        source_reader=ObjectStoreKnowledgeSourceReader(
            object_store=container.object_store,
            memory_spool_bytes=settings.knowledge_source_memory_spool_bytes,
            spool_directory=settings.knowledge_source_spool_directory,
        ),
        parser=BoundedKnowledgeDocumentParser(),
        runtime_resolver=resolve_runtime,
        worker_fingerprint=worker_name,
        lease_seconds=settings.knowledge_source_worker_lease_seconds,
        maximum_attempts=settings.knowledge_source_job_maximum_attempts,
    )
    signals = EventSignalConsumer(
        delivery=container.event_delivery,
        inbox=SqlInboxStore(container.database.session_factory),
        group="knowledge-source-analysis-v1",
        consumer=worker_name,
        relevant_event_types=frozenset({"knowledge.source-analysis.queued.v1"}),
        visibility_timeout_seconds=settings.knowledge_source_worker_lease_seconds,
    )
    try:
        while True:
            try:
                processed = await worker.run_once()
                if not processed:
                    await signals.wait_and_trigger(
                        timeout_seconds=settings.knowledge_source_worker_poll_seconds,
                        handler=worker.run_once,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                await LOGGER.aexception("knowledge_source_worker_cycle_failed")
                await asyncio.sleep(min(settings.knowledge_source_worker_poll_seconds * 4, 10))
    finally:
        await container.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
