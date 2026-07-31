from __future__ import annotations

import asyncio
import socket

import structlog

from datariver.application.services.knowledge_studio_ingestion_worker import (
    KnowledgeStudioIngestionWorker,
)
from datariver.config import get_settings
from datariver.domain.common import ConflictError
from datariver.domain.knowledge_pipeline import ModelBinding
from datariver.infrastructure.db.knowledge_studio_ingestion import (
    SqlKnowledgeStudioIngestionWorkerStore,
)
from datariver.infrastructure.knowledge.runtime import (
    build_knowledge_embedding_runtime,
)
from datariver.infrastructure.knowledge_studio.postgres_source import (
    KnowledgeStudioSourceSecretReader,
    PostgresKnowledgeStudioBatchSourceReader,
    load_knowledge_studio_source_manifest,
)
from datariver.workers.container import (
    build_knowledge_studio_ingestion_container,
)

LOGGER = structlog.get_logger()
_SIGNAL_TYPES = frozenset(
    {
        "knowledge.studio-ingestion.pending.v1",
        "knowledge.studio-ingestion.retry_wait.v1",
    }
)


async def run() -> None:
    settings = get_settings()
    container = build_knowledge_studio_ingestion_container(settings)
    workspace_id = settings.knowledge_studio_ingestion_workspace_id
    worker_subject_id = settings.knowledge_studio_ingestion_worker_subject_id
    worker_fingerprint = settings.knowledge_studio_ingestion_worker_fingerprint
    manifest_file = settings.knowledge_studio_source_manifest_file
    assert workspace_id is not None
    assert worker_subject_id is not None
    assert worker_fingerprint is not None
    assert manifest_file is not None

    embedding_provider = None
    embedding_binding: ModelBinding | None = None
    try:
        runtime = build_knowledge_embedding_runtime(settings)
        embedding_provider = runtime.embedding
        embedding_binding = runtime.binding
    except ConflictError:
        pass

    worker = KnowledgeStudioIngestionWorker(
        store=SqlKnowledgeStudioIngestionWorkerStore(container.database.session_factory),
        source_reader=PostgresKnowledgeStudioBatchSourceReader(
            manifest=load_knowledge_studio_source_manifest(manifest_file),
            secret_reader=KnowledgeStudioSourceSecretReader(
                settings.knowledge_studio_source_secret_root
            ),
        ),
        embedding_provider=embedding_provider,
        current_embedding_binding=lambda: embedding_binding,
        workspace_id=workspace_id,
        worker_subject_id=worker_subject_id,
        worker_fingerprint=worker_fingerprint,
        lease_seconds=settings.knowledge_studio_ingestion_worker_lease_seconds,
        source_hard_timeout_seconds=(
            settings.knowledge_studio_ingestion_source_hard_timeout_seconds
        ),
        completion_margin_seconds=(settings.knowledge_studio_ingestion_completion_margin_seconds),
    )
    consumer = f"knowledge-studio-ingestion:{worker_fingerprint}:{socket.gethostname()}"
    group = "knowledge-studio-ingestion-v1"
    try:
        while True:
            try:
                if await worker.run_once():
                    continue
                events = await container.event_delivery.read_events(
                    group=group,
                    consumer=consumer,
                    block_milliseconds=max(
                        1,
                        int(settings.knowledge_studio_ingestion_worker_poll_seconds * 1000),
                    ),
                    visibility_timeout_milliseconds=(
                        settings.knowledge_studio_ingestion_worker_lease_seconds * 1000
                    ),
                )
                for event in events:
                    if event.workspace_id == workspace_id and event.event_type in _SIGNAL_TYPES:
                        await worker.run_once()
                    await container.event_delivery.acknowledge(
                        group=group,
                        message_id=event.message_id,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                await LOGGER.aexception("knowledge_studio_ingestion_worker_cycle_failed")
                await asyncio.sleep(
                    min(
                        settings.knowledge_studio_ingestion_worker_poll_seconds * 4,
                        10,
                    )
                )
    finally:
        await container.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
