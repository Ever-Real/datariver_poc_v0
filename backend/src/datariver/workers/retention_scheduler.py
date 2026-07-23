from __future__ import annotations

import asyncio
from time import monotonic

import structlog

from datariver.application.services.retention_execution import RetentionExecutionPlanner
from datariver.config import get_settings
from datariver.infrastructure.db.retention_execution import SqlRetentionExecutionStore
from datariver.infrastructure.observability.metrics import RetentionWorkerMetrics
from datariver.workers.container import (
    build_retention_scheduler_container,
    retention_archive_configuration_fingerprint,
)
from datariver.workers.retention_switch import ReloadableRetentionSwitch

LOGGER = structlog.get_logger()


async def run() -> None:
    settings = get_settings()
    container = build_retention_scheduler_container(settings)
    assert settings.s3_archive_bucket is not None
    assert settings.s3_archive_prefix is not None
    assert settings.s3_archive_encryption_profile_fingerprint is not None
    store = SqlRetentionExecutionStore(
        container.database.session_factory,
        archive_bucket=settings.s3_archive_bucket,
        archive_prefix=settings.s3_archive_prefix,
        encryption_profile_fingerprint=settings.s3_archive_encryption_profile_fingerprint,
    )
    execution_switch = ReloadableRetentionSwitch(
        deployment_enabled=settings.retention_archive_execution_enabled,
        control_file=settings.retention_execution_control_file,
    )
    planner = RetentionExecutionPlanner(
        store=store,
        execution_enabled=execution_switch.enabled,
        executor_id=settings.retention_worker_subject_id,
        archive_configuration_hash=retention_archive_configuration_fingerprint(settings),
        maximum_attempts=settings.retention_maximum_attempts,
        batch_size=settings.retention_claim_batch_size,
    )
    metrics = RetentionWorkerMetrics(worker="scheduler")
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
                planned = 0
                for workspace_id in settings.retention_workspace_ids:
                    planned += await planner.run_once(workspace_id=workspace_id)
                if planned:
                    metrics.cycle_finished(
                        outcome="planned",
                        duration_seconds=monotonic() - started_at,
                        command_count=planned,
                    )
                    await LOGGER.ainfo(
                        "retention_execution_commands_planned", command_count=planned
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
                await LOGGER.aexception("retention_scheduler_cycle_failed")
                await asyncio.sleep(min(settings.worker_poll_seconds * 4, 10))
    finally:
        metrics_server.shutdown()
        metrics_server.server_close()
        await container.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
