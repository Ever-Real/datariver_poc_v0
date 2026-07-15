from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from datariver.application.dto import DataHubScanAsset, DataHubScanPage
from datariver.application.ports import CatalogProjectionWriter, DataHubGateway
from datariver.application.services.authorization import AuthorizationService, NullDecisionWriter
from datariver.application.services.catalog_sync import CatalogSyncService
from datariver.domain.authz import Action, Classification, EnvironmentAttributes, SubjectAttributes
from datariver.domain.common import ForbiddenError


class ScanGateway:
    def __init__(self, page: DataHubScanPage) -> None:
        self.page = page
        self.calls = 0

    async def scan_assets(self, *, offset: int, limit: int) -> DataHubScanPage:
        assert (offset, limit) == (0, 100)
        self.calls += 1
        return self.page


class RecordingProjectionWriter:
    def __init__(self) -> None:
        self.arguments: dict[str, Any] | None = None

    async def upsert_scan(self, **arguments: Any) -> tuple[int, int]:
        self.arguments = arguments
        return 1, 2


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
        next_offset=None,
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
    assert writer.arguments["operation"] == "catalog.datahub.sync:0:100"


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
