from __future__ import annotations

import asyncio
import socket

import structlog

from datariver.application.knowledge_studio_proposal_job_contracts import (
    KnowledgeStudioProposalJobClaim,
    KnowledgeStudioProposalRuntime,
)
from datariver.application.services.knowledge_studio_proposal_worker import (
    KnowledgeStudioProposalWorker,
)
from datariver.config import get_settings
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
        "knowledge.tbox-proposal.queued.v1",
        "knowledge.tbox-proposal.retry-wait.v1",
    }
)


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
                if await worker.run_once():
                    continue
                events = await container.event_delivery.read_events(
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
                for event in events:
                    if (
                        event.workspace_id == workspace_id
                        and event.event_type in SIGNAL_EVENT_TYPES
                    ):
                        await worker.run_once()
                    await container.event_delivery.acknowledge(
                        group=group,
                        message_id=event.message_id,
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
    asyncio.run(run())


if __name__ == "__main__":
    main()
