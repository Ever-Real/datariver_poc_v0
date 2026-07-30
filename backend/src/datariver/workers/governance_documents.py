from __future__ import annotations

import asyncio
import socket

import structlog

from datariver.application.services.governance_document_projection import (
    GovernanceDocumentProjectionService,
)
from datariver.config import get_settings
from datariver.infrastructure.db.governance_documents import (
    SqlGovernanceDocumentRepository,
)
from datariver.infrastructure.knowledge.governance_documents import (
    Neo4jGovernanceDocumentProjector,
)
from datariver.infrastructure.knowledge.runtime import build_knowledge_runtime_adapters
from datariver.workers.container import build_governance_document_container

LOGGER = structlog.get_logger()
_SIGNAL_TYPES = frozenset(
    {
        "governance.document-version.created.v1",
        "governance.document-version.published.v1",
    }
)
_MAX_EVENT_BLOCK_MILLISECONDS = 1_000


async def run() -> None:
    settings = get_settings()
    container = build_governance_document_container(settings)
    runtime = build_knowledge_runtime_adapters(settings)
    worker_name = f"governance-document:{socket.gethostname()}"
    graph = Neo4jGovernanceDocumentProjector(container.neo4j)

    async def process_once() -> bool:
        async with container.database.session_factory() as session:
            return await GovernanceDocumentProjectionService(
                repository=SqlGovernanceDocumentRepository(session),
                artifact_store=container.artifacts,
                embedding=runtime.embedding,
                embedding_binding=runtime.bindings.embedding,
                graph=graph,
                worker_id=worker_name,
                lease_seconds=settings.governance_document_worker_lease_seconds,
            ).run_once()

    group = "governance-document-projection-v1"
    try:
        while True:
            try:
                if await process_once():
                    continue
                events = await container.event_delivery.read_events(
                    group=group,
                    consumer=worker_name,
                    block_milliseconds=min(
                        _MAX_EVENT_BLOCK_MILLISECONDS,
                        max(
                            1,
                            int(settings.governance_document_worker_poll_seconds * 1_000),
                        ),
                    ),
                    visibility_timeout_milliseconds=(
                        settings.governance_document_worker_lease_seconds * 1_000
                    ),
                )
                for event in events:
                    if event.event_type in _SIGNAL_TYPES:
                        await process_once()
                    await container.event_delivery.acknowledge(
                        group=group,
                        message_id=event.message_id,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                await LOGGER.aexception("governance_document_worker_cycle_failed")
                await asyncio.sleep(min(settings.governance_document_worker_poll_seconds * 4, 10))
    finally:
        await container.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
