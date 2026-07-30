from __future__ import annotations

import asyncio
import socket
from typing import cast
from uuid import uuid4

import structlog

from datariver.application.quality_worker_contracts import QualitySourceResolverPort
from datariver.application.services.quality_execution import QualityExecutionWorker
from datariver.config import get_settings
from datariver.infrastructure.db.quality_execution import SqlQualityExecutionStore
from datariver.infrastructure.quality.asyncpg_executor import AsyncpgGxAggregateExecutor
from datariver.infrastructure.quality.gx_compiler import FixedGxExpectationCompiler
from datariver.infrastructure.quality.result_sanitizer import StrictGxResultSanitizer
from datariver.infrastructure.quality.source_manifest import (
    QualitySourceSecretReader,
    load_quality_source_manifest,
)
from datariver.workers.container import build_quality_container

LOGGER = structlog.get_logger()
_QUALITY_SIGNAL_TYPES = frozenset(
    {
        "quality.validation_run.queued.v1",
        "quality.validation_run.retry_wait.v1",
    }
)


async def run() -> None:
    settings = get_settings()
    container = build_quality_container(settings)
    workspace_id = settings.quality_worker_workspace_id
    worker_subject_id = settings.quality_worker_subject_id
    manifest_file = settings.quality_source_manifest_file
    fingerprint = settings.quality_worker_fingerprint
    assert workspace_id is not None
    assert worker_subject_id is not None
    assert manifest_file is not None
    assert fingerprint is not None
    worker_name = f"quality:{fingerprint}:{socket.gethostname()}"
    worker = QualityExecutionWorker(
        store=SqlQualityExecutionStore(container.database.session_factory),
        manifest=cast(
            QualitySourceResolverPort,
            load_quality_source_manifest(manifest_file),
        ),
        compiler=FixedGxExpectationCompiler(),
        sanitizer=StrictGxResultSanitizer(),
        executor=AsyncpgGxAggregateExecutor(
            secret_reader=QualitySourceSecretReader(settings.quality_source_secret_root)
        ),
        workspace_id=workspace_id,
        worker_subject_id=worker_subject_id,
        worker_fingerprint=fingerprint,
        lease_seconds=settings.quality_worker_lease_seconds,
        call_id_factory=lambda: str(uuid4()),
    )
    group = "quality-execution-v1"
    try:
        while True:
            try:
                processed = await worker.run_once()
                if processed:
                    continue
                events = await container.event_delivery.read_events(
                    group=group,
                    consumer=worker_name,
                    block_milliseconds=max(1, int(settings.worker_poll_seconds * 1000)),
                    visibility_timeout_milliseconds=(settings.quality_worker_lease_seconds * 1000),
                )
                for event in events:
                    if (
                        event.workspace_id == workspace_id
                        and event.event_type in _QUALITY_SIGNAL_TYPES
                    ):
                        await worker.run_once()
                    await container.event_delivery.acknowledge(
                        group=group,
                        message_id=event.message_id,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                await LOGGER.aexception("quality_worker_cycle_failed")
                await asyncio.sleep(min(settings.worker_poll_seconds * 4, 10))
    finally:
        await container.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
