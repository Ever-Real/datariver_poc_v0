from __future__ import annotations

import argparse
import asyncio
import socket
from uuid import UUID

import structlog
from sqlalchemy import text

from datariver.application.knowledge_studio_proposal_job_contracts import (
    KnowledgeStudioProposalJobClaim,
    KnowledgeStudioProposalRuntime,
)
from datariver.application.services.knowledge_studio_proposal_worker import (
    KnowledgeStudioProposalWorker,
)
from datariver.config import get_settings
from datariver.infrastructure.cache.redis import RedisEventDelivery
from datariver.infrastructure.db.knowledge_studio_proposal_jobs import (
    SqlKnowledgeStudioProposalJobWorkerStore,
)
from datariver.infrastructure.knowledge.proposal_document import (
    ObjectStoreKnowledgeStudioProposalDocumentReader,
)
from datariver.infrastructure.knowledge.runtime import (
    build_knowledge_tbox_schema_runtime,
)
from datariver.workers.container import build_knowledge_tbox_proposal_container

LOGGER = structlog.get_logger()
SIGNAL_EVENT_TYPES = frozenset(
    {
        "knowledge.tbox-proposal-job.queued.v1",
        "knowledge.tbox-proposal-job.retry_wait.v1",
    }
)


async def _run_cycle(
    *,
    worker: KnowledgeStudioProposalWorker,
    event_delivery: RedisEventDelivery,
    workspace_id: UUID,
    group: str,
    consumer: str,
    block_milliseconds: int,
    visibility_timeout_milliseconds: int,
) -> None:
    if await worker.run_once():
        return
    events = await event_delivery.read_events(
        group=group,
        consumer=consumer,
        block_milliseconds=block_milliseconds,
        visibility_timeout_milliseconds=visibility_timeout_milliseconds,
    )
    for event in events:
        if event.workspace_id == workspace_id and event.event_type in SIGNAL_EVENT_TYPES:
            await worker.run_once()
        await event_delivery.acknowledge(
            group=group,
            message_id=event.message_id,
        )


async def healthcheck() -> None:
    settings = get_settings()
    container = build_knowledge_tbox_proposal_container(settings)
    try:
        async with container.database.session_factory() as session:
            if await session.scalar(text("SELECT 1")) != 1:
                raise RuntimeError("Knowledge Proposal database health check failed.")
        if not await container.event_delivery.ping():
            raise RuntimeError("Knowledge Proposal Redis delivery health check failed.")
    finally:
        await container.close()


async def run() -> None:
    settings = get_settings()
    container = build_knowledge_tbox_proposal_container(settings)
    workspace_id = settings.knowledge_studio_proposal_workspace_id
    worker_subject_id = settings.knowledge_studio_proposal_worker_subject_id
    configured_fingerprint = settings.knowledge_studio_proposal_worker_fingerprint
    assert workspace_id is not None
    assert worker_subject_id is not None
    assert configured_fingerprint is not None

    runtime = build_knowledge_tbox_schema_runtime(settings)

    async def resolve_runtime(
        _claim: KnowledgeStudioProposalJobClaim,
    ) -> KnowledgeStudioProposalRuntime:
        return KnowledgeStudioProposalRuntime(
            assistant=runtime.assistant,
            binding=runtime.binding,
        )

    worker = KnowledgeStudioProposalWorker(
        store=SqlKnowledgeStudioProposalJobWorkerStore(
            container.database.session_factory,
        ),
        document_reader=ObjectStoreKnowledgeStudioProposalDocumentReader(
            object_store=container.object_store,
            memory_spool_bytes=settings.knowledge_studio_proposal_memory_spool_bytes,
            spool_directory=settings.knowledge_studio_proposal_spool_directory,
        ),
        runtime_resolver=resolve_runtime,
        workspace_id=workspace_id,
        worker_subject_id=worker_subject_id,
        worker_fingerprint=configured_fingerprint,
        lease_seconds=settings.knowledge_studio_proposal_worker_lease_seconds,
    )
    consumer = f"knowledge-tbox-proposal:{configured_fingerprint}:{socket.gethostname()}"
    group = "knowledge-tbox-proposal-v1"
    try:
        while True:
            try:
                await _run_cycle(
                    worker=worker,
                    event_delivery=container.event_delivery,
                    workspace_id=workspace_id,
                    group=group,
                    consumer=consumer,
                    block_milliseconds=max(
                        1,
                        int(settings.knowledge_studio_proposal_worker_poll_seconds * 1_000),
                    ),
                    visibility_timeout_milliseconds=(
                        settings.knowledge_studio_proposal_worker_lease_seconds * 1_000
                    ),
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                await LOGGER.aexception("knowledge_tbox_proposal_worker_cycle_failed")
                await asyncio.sleep(
                    min(
                        settings.knowledge_studio_proposal_worker_poll_seconds * 4,
                        10,
                    )
                )
    finally:
        await container.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--healthcheck", action="store_true")
    arguments = parser.parse_args()
    asyncio.run(healthcheck() if arguments.healthcheck else run())


if __name__ == "__main__":
    main()
