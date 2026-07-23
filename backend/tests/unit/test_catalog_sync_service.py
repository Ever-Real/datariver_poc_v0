from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from datariver.application.dto import (
    CatalogSyncProgress,
    CatalogSyncReservation,
    CatalogSyncResult,
    DataHubScanAsset,
    DataHubScanPage,
)
from datariver.application.errors import ExternalDependencyError
from datariver.application.ports import CatalogProjectionWriter, DataHubGateway
from datariver.application.services.authorization import AuthorizationService, NullDecisionWriter
from datariver.application.services.catalog_sync import CatalogSyncService
from datariver.domain.authz import Action, Classification, EnvironmentAttributes, SubjectAttributes
from datariver.domain.common import ForbiddenError


class ScanGateway:
    def __init__(
        self,
        page: DataHubScanPage,
        *,
        expected_cursor: str | None = None,
        error: ExternalDependencyError | None = None,
    ) -> None:
        self.page = page
        self.expected_cursor = expected_cursor
        self.error = error
        self.calls = 0

    async def scan_assets(self, *, cursor: str | None, limit: int) -> DataHubScanPage:
        assert (cursor, limit) == (self.expected_cursor, 100)
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.page


class RecordingProjectionWriter:
    def __init__(
        self,
        *,
        replayed: CatalogSyncResult | None = None,
        expected_cursor_value: str | None = None,
    ) -> None:
        self.arguments: dict[str, Any] | None = None
        self.abandoned = False
        self.replayed = replayed
        self.expected_cursor_value = expected_cursor_value
        self.released = False
        self.reservations = 0

    async def reserve_scan(self, **arguments: Any) -> CatalogSyncReservation:
        self.reservations += 1
        expected_offset = 1 if self.expected_cursor_value is not None else 0
        assert arguments["offset"] == expected_offset
        return CatalogSyncReservation(
            cursor=self.expected_cursor_value,
            replayed=self.replayed,
        )

    async def release_scan(self) -> None:
        self.released = True

    async def abandon_scan(self, **arguments: Any) -> None:
        del arguments
        self.abandoned = True

    async def replay_scan(self, **arguments: Any) -> CatalogSyncResult | None:
        del arguments
        return self.replayed

    async def expected_cursor(
        self,
        *,
        workspace_id: UUID,
        sync_id: UUID,
        offset: int,
    ) -> str | None:
        del workspace_id, sync_id
        assert offset == (1 if self.expected_cursor_value is not None else 0)
        return self.expected_cursor_value

    async def scan_progress(self, **_: Any) -> CatalogSyncProgress:
        return CatalogSyncProgress("NOT_STARTED", 0, 0, None, False)

    async def upsert_scan(self, **arguments: Any) -> CatalogSyncResult:
        self.arguments = arguments
        return CatalogSyncResult(
            upserted=1,
            tombstoned=2,
            next_offset=cast(int | None, arguments["next_offset"]),
            total=cast(int, arguments["total"]),
            observed_at=cast(datetime, arguments["observed_at"]),
            tombstone_status="SUPPRESSED_UNVERIFIED_SNAPSHOT",
        )


def _subject(workspace_id: UUID, *, allowed: bool) -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function="catalog-sync",
        clearance=Classification.RESTRICTED,
        allowed_actions=frozenset({Action.CATALOG_SYNC}) if allowed else frozenset(),
    )


def test_catalog_sync_rejects_a_reservation_budget_above_the_database_boundary() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValueError, match="reservation provider budget"):
        CatalogSyncService(
            datahub=cast(DataHubGateway, ScanGateway(DataHubScanPage((), None, 0, now))),
            writer=cast(CatalogProjectionWriter, RecordingProjectionWriter()),
            authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
            reservation_provider_budget_seconds=10.01,
        )


@pytest.mark.asyncio
async def test_catalog_sync_passes_stable_run_identity_and_final_page_to_projection() -> None:
    observed_at = datetime.now(UTC)
    workspace_id = uuid4()
    sync_id = uuid4()
    page = DataHubScanPage(
        items=(
            DataHubScanAsset(
                external_urn="urn:li:dataset:(urn:li:dataPlatform:snowflake,wafer_events,PROD)",
                asset_type="DATASET",
                name="wafer_events",
                description="Synthetic test asset",
                platform="snowflake",
                domain_ref=None,
                system_ref=None,
                owner_ref=None,
                classification=Classification.CONFIDENTIAL,
                source_version="datahub-v1",
            ),
        ),
        next_cursor=None,
        total=1,
        observed_at=observed_at,
    )
    gateway = ScanGateway(page)
    writer = RecordingProjectionWriter()
    service = CatalogSyncService(
        datahub=cast(DataHubGateway, gateway),
        writer=cast(CatalogProjectionWriter, writer),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    )

    result = await service.sync_page(
        workspace_id=workspace_id,
        sync_id=sync_id,
        offset=0,
        limit=100,
        subject=_subject(workspace_id, allowed=True),
        environment=EnvironmentAttributes(requested_at=observed_at),
        request_id="sync-request",
        idempotency_key="catalog-sync-idempotency-key",
        request_hash="request-hash",
    )

    assert (result.upserted, result.tombstoned, result.next_offset) == (1, 2, None)
    assert writer.arguments is not None
    assert writer.arguments["sync_id"] == sync_id
    assert writer.arguments["next_offset"] is None
    assert writer.arguments["next_cursor"] is None
    assert writer.arguments["total"] == 1
    assert writer.arguments["snapshot_consistent"] is False
    assert writer.arguments["snapshot_evidence_reference"] is None
    assert writer.arguments["snapshot_contract_hash"] is None
    assert writer.arguments["snapshot_provider_version"] is None
    assert writer.arguments["operation"] == "catalog.datahub.sync:0:100"


@pytest.mark.asyncio
async def test_catalog_sync_replays_a_committed_page_before_reading_the_provider() -> None:
    now = datetime.now(UTC)
    workspace_id = uuid4()
    replayed = CatalogSyncResult(1, 0, 1, 200, now, "NOT_FINAL")
    writer = RecordingProjectionWriter(replayed=replayed)
    gateway = ScanGateway(DataHubScanPage((), None, 0, now))
    service = CatalogSyncService(
        datahub=cast(DataHubGateway, gateway),
        writer=cast(CatalogProjectionWriter, writer),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    )

    result = await service.sync_page(
        workspace_id=workspace_id,
        sync_id=uuid4(),
        offset=0,
        limit=100,
        subject=_subject(workspace_id, allowed=True),
        environment=EnvironmentAttributes(requested_at=now),
        request_id="replay-sync",
        idempotency_key="replay-sync-idempotency",
        request_hash="replay-hash",
    )

    assert result == replayed
    assert gateway.calls == 0
    assert writer.reservations == 1


@pytest.mark.asyncio
async def test_catalog_sync_abandons_an_expired_server_owned_cursor() -> None:
    now = datetime.now(UTC)
    workspace_id = uuid4()
    cursor = "server-owned-cursor"
    error = ExternalDependencyError(
        "DataHub rejected the scroll cursor.",
        dependency="datahub",
        retryable=False,
        provider_code="GRAPHQL_ERROR",
    )
    writer = RecordingProjectionWriter(expected_cursor_value=cursor)
    gateway = ScanGateway(
        DataHubScanPage((), None, 0, now),
        expected_cursor=cursor,
        error=error,
    )
    service = CatalogSyncService(
        datahub=cast(DataHubGateway, gateway),
        writer=cast(CatalogProjectionWriter, writer),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    )

    with pytest.raises(ExternalDependencyError):
        await service.sync_page(
            workspace_id=workspace_id,
            sync_id=uuid4(),
            offset=1,
            limit=100,
            subject=_subject(workspace_id, allowed=True),
            environment=EnvironmentAttributes(requested_at=now),
            request_id="expired-sync",
            idempotency_key="expired-sync-idempotency",
            request_hash="expired-hash",
        )

    assert writer.abandoned is True


@pytest.mark.asyncio
async def test_catalog_sync_reduces_provider_page_size_after_a_bounded_response_failure() -> None:
    now = datetime.now(UTC)
    workspace_id = uuid4()
    calls: list[int] = []
    page = DataHubScanPage((), None, 0, now)

    class AdaptiveGateway:
        async def scan_assets(self, *, cursor: str | None, limit: int) -> DataHubScanPage:
            assert cursor is None
            calls.append(limit)
            if limit > 25:
                raise ExternalDependencyError(
                    "bounded response exceeded",
                    dependency="datahub",
                    retryable=False,
                    provider_code="RESPONSE_TOO_LARGE",
                )
            return page

    writer = RecordingProjectionWriter()
    service = CatalogSyncService(
        datahub=cast(DataHubGateway, AdaptiveGateway()),
        writer=cast(CatalogProjectionWriter, writer),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    )

    await service.sync_page(
        workspace_id=workspace_id,
        sync_id=uuid4(),
        offset=0,
        limit=100,
        subject=_subject(workspace_id, allowed=True),
        environment=EnvironmentAttributes(requested_at=now),
        request_id="adaptive-sync",
        idempotency_key="adaptive-sync-idempotency",
        request_hash="adaptive-hash",
    )

    assert calls == [100, 50, 25]
    assert writer.released is False


@pytest.mark.asyncio
async def test_catalog_sync_releases_the_database_reservation_before_runtime_idle_timeout() -> None:
    now = datetime.now(UTC)
    workspace_id = uuid4()

    class SlowGateway:
        async def scan_assets(self, *, cursor: str | None, limit: int) -> DataHubScanPage:
            del cursor, limit
            await asyncio.sleep(1)
            raise AssertionError("The fixed reservation budget did not cancel the provider call.")

    writer = RecordingProjectionWriter()
    service = CatalogSyncService(
        datahub=cast(DataHubGateway, SlowGateway()),
        writer=cast(CatalogProjectionWriter, writer),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
        reservation_provider_budget_seconds=0.01,
    )

    with pytest.raises(ExternalDependencyError) as captured:
        await service.sync_page(
            workspace_id=workspace_id,
            sync_id=uuid4(),
            offset=0,
            limit=100,
            subject=_subject(workspace_id, allowed=True),
            environment=EnvironmentAttributes(requested_at=now),
            request_id="reservation-timeout",
            idempotency_key="reservation-timeout-idempotency",
            request_hash="reservation-timeout-hash",
        )

    assert captured.value.details["provider_code"] == "SYNC_RESERVATION_TIMEOUT"
    assert captured.value.details["retryable"] is True
    assert writer.released is True


@pytest.mark.asyncio
async def test_catalog_sync_denial_prevents_external_datahub_scan() -> None:
    now = datetime.now(UTC)
    workspace_id = uuid4()
    gateway = ScanGateway(DataHubScanPage((), None, 0, now))
    service = CatalogSyncService(
        datahub=cast(DataHubGateway, gateway),
        writer=cast(CatalogProjectionWriter, RecordingProjectionWriter()),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    )

    with pytest.raises(ForbiddenError):
        await service.sync_page(
            workspace_id=workspace_id,
            sync_id=uuid4(),
            offset=0,
            limit=100,
            subject=_subject(workspace_id, allowed=False),
            environment=EnvironmentAttributes(requested_at=now),
            request_id="denied-sync",
            idempotency_key="denied-sync-idempotency",
            request_hash="denied-hash",
        )

    assert gateway.calls == 0
