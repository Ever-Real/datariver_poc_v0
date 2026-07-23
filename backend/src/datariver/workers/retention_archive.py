from __future__ import annotations

import asyncio
import socket
from time import monotonic

import structlog

from datariver.application.services.retention_execution import (
    RetentionArchiveOutcome,
    RetentionArchiveWorker,
)
from datariver.config import get_settings
from datariver.infrastructure.db.retention_execution import SqlRetentionExecutionStore
from datariver.infrastructure.observability.metrics import RetentionWorkerMetrics
from datariver.workers.container import build_retention_archive_container
from datariver.workers.retention_switch import ReloadableRetentionSwitch

LOGGER = structlog.get_logger()


async def run() -> None:
    settings = get_settings()
    container = build_retention_archive_container(settings)
    assert settings.s3_archive_bucket is not None
    assert settings.s3_archive_prefix is not None
    assert settings.s3_archive_encryption_profile_fingerprint is not None
    assert settings.s3_archive_worker_principal_fingerprint is not None
    store = SqlRetentionExecutionStore(
        container.database.session_factory,
        archive_bucket=settings.s3_archive_bucket,
        archive_prefix=settings.s3_archive_prefix,
        encryption_profile_fingerprint=settings.s3_archive_encryption_profile_fingerprint,
    )
    worker_id = f"retention-archive:{socket.gethostname()}"
    execution_switch = ReloadableRetentionSwitch(
        deployment_enabled=settings.retention_archive_execution_enabled,
        control_file=settings.retention_execution_control_file,
    )
    worker = RetentionArchiveWorker(
        store=store,
        archive=container.archive,
        execution_enabled=execution_switch.enabled,
        worker_id=worker_id,
        worker_principal_fingerprint=settings.s3_archive_worker_principal_fingerprint,
        lease_seconds=settings.retention_lease_seconds,
    )
    metrics = RetentionWorkerMetrics(worker="archive")
    metrics.kill_switch_observed(enabled=execution_switch.enabled())
    metrics_server = metrics.start_http_server(port=settings.retention_metrics_port)
    try:
        while True:
            started_at = monotonic()
            try:
                switch_enabled = execution_switch.enabled()
                metrics.kill_switch_observed(enabled=switch_enabled)
                if not switch_enabled:
                    metrics.cycle_finished(
                        outcome="disabled",
                        duration_seconds=monotonic() - started_at,
                        command_count=0,
                    )
                    await asyncio.sleep(settings.worker_poll_seconds)
                    continue
                outcomes: list[RetentionArchiveOutcome] = []
                for workspace_id in settings.retention_workspace_ids:
                    outcome = await worker.run_once(workspace_id=workspace_id)
                    if outcome is not None:
                        outcomes.append(outcome)
                if outcomes:
                    cycle_outcome = (
                        RetentionArchiveOutcome.BLOCKED
                        if RetentionArchiveOutcome.BLOCKED in outcomes
                        else RetentionArchiveOutcome.LEASE_LOST
                        if RetentionArchiveOutcome.LEASE_LOST in outcomes
                        else RetentionArchiveOutcome.RETRY_SCHEDULED
                        if RetentionArchiveOutcome.RETRY_SCHEDULED in outcomes
                        else RetentionArchiveOutcome.ARCHIVED
                    )
                    metrics.cycle_finished(
                        outcome=cycle_outcome.value,
                        duration_seconds=monotonic() - started_at,
                        command_count=len(outcomes),
                    )
                else:
                    metrics.cycle_finished(
                        outcome="idle",
                        duration_seconds=monotonic() - started_at,
                        command_count=0,
                    )
                    await asyncio.sleep(settings.worker_poll_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                metrics.cycle_finished(
                    outcome="failed",
                    duration_seconds=monotonic() - started_at,
                    command_count=0,
                )
                await LOGGER.aexception("retention_archive_cycle_failed")
                await asyncio.sleep(min(settings.worker_poll_seconds * 4, 10))
    finally:
        metrics_server.shutdown()
        metrics_server.server_close()
        await container.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
