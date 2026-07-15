from __future__ import annotations

import asyncio
import socket

import structlog

from datariver.application.services.governance_apply import GovernanceApplyWorker
from datariver.config import get_settings
from datariver.infrastructure.db.governance_apply import SqlGovernanceApplyStore
from datariver.infrastructure.db.outbox import SqlInboxStore
from datariver.workers.container import build_governance_container
from datariver.workers.event_signal import EventSignalConsumer

LOGGER = structlog.get_logger()


async def run() -> None:
    settings = get_settings()
    container = build_governance_container(settings)
    consumer_name = f"governance-apply:{socket.gethostname()}"
    worker = GovernanceApplyWorker(
        store=SqlGovernanceApplyStore(container.database.session_factory),
        datahub=container.datahub,
        worker_id=consumer_name,
        system_actor_id=settings.governance_worker_subject_id,
        lease_seconds=settings.governance_apply_lease_seconds,
        maximum_attempts=settings.governance_apply_maximum_attempts,
    )
    signals = EventSignalConsumer(
        delivery=container.event_delivery,
        inbox=SqlInboxStore(container.database.session_factory),
        group="governance-apply-v1",
        consumer=consumer_name,
        relevant_event_types=frozenset({"governance.change_request.apply_queued.v1"}),
        visibility_timeout_seconds=settings.governance_apply_lease_seconds,
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
                await LOGGER.aexception("governance_apply_worker_cycle_failed")
                await asyncio.sleep(min(settings.worker_poll_seconds * 4, 10))
    finally:
        await container.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
