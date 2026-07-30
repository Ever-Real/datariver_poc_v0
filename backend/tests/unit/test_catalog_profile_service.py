from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from datariver.application.catalog_profile_contracts import (
    CatalogProfileProjectionCommand,
    CatalogProfileProjectionResult,
    CatalogProfileTarget,
    DataHubProfileObservation,
    ProfileCompleteness,
    ProfileKind,
)
from datariver.application.services.catalog_profile_collection import (
    CatalogProfileCollectionService,
)
from datariver.domain.authz import Classification
from datariver.domain.common import canonical_json_hash


class _Targets:
    def __init__(self, target: CatalogProfileTarget | None) -> None:
        self.target = target
        self.called = False

    async def get_target(
        self, *, workspace_id: object, asset_id: object
    ) -> CatalogProfileTarget | None:
        del workspace_id, asset_id
        self.called = True
        return self.target


class _Profiles:
    def __init__(self, observation: DataHubProfileObservation | None) -> None:
        self.observation = observation
        self.called = False

    async def get_profile(
        self, *, external_urn: str, workspace_id: object, asset_id: object
    ) -> DataHubProfileObservation | None:
        del external_urn, workspace_id, asset_id
        self.called = True
        return self.observation


class _Projection:
    def __init__(self) -> None:
        self.command: CatalogProfileProjectionCommand | None = None

    async def project(
        self, command: CatalogProfileProjectionCommand
    ) -> CatalogProfileProjectionResult:
        self.command = command
        return CatalogProfileProjectionResult(
            snapshot_id=uuid4(),
            snapshot_identity_hash="f" * 64,
            created=True,
            last_observed_at=datetime.now(tz=UTC),
        )


@pytest.mark.asyncio
async def test_collection_reads_authorized_target_before_provider_and_projects_watermark() -> None:
    workspace_id, asset_id = uuid4(), uuid4()
    now = datetime.now(tz=UTC)
    target = CatalogProfileTarget(
        workspace_id=workspace_id,
        asset_id=asset_id,
        external_urn="urn:li:dataset:test",
        source_version="source-v7",
        classification=Classification.CONFIDENTIAL,
        system_id=None,
        domain_id=None,
    )
    observation = DataHubProfileObservation(
        kind=ProfileKind.FULL,
        completeness=ProfileCompleteness.COMPLETE,
        profiled_at=now,
        observed_at=now,
        stale_at=now + timedelta(hours=1),
        row_count=1,
        column_count=0,
        size_bytes=1,
        columns=(),
        provenance_key_id=None,
        provenance_fingerprint=None,
        provider_version="v1.6.0",
        provider_contract_hash="a" * 64,
        query_hash="b" * 64,
        provider_config_hash="c" * 64,
        normalized_payload_hash="d" * 64,
    )
    targets = _Targets(target)
    profiles, projection = _Profiles(observation), _Projection()
    result = await CatalogProfileCollectionService(
        datahub=profiles,
        targets=targets,
        projection=projection,
    ).collect(
        workspace_id=workspace_id,
        asset_id=asset_id,
    )
    assert result.availability == "AVAILABLE"
    assert targets.called
    assert profiles.called
    assert projection.command is not None
    assert projection.command.source_watermark_hash == canonical_json_hash(
        {
            "asset_id": str(asset_id),
            "contract": "CATALOG_ASSET_SOURCE_WATERMARK_V1",
            "source_version": "source-v7",
            "workspace_id": str(workspace_id),
        }
    )


@pytest.mark.asyncio
async def test_unavailable_authorized_target_prevents_provider_call() -> None:
    workspace_id, asset_id = uuid4(), uuid4()
    profiles = _Profiles(None)
    result = await CatalogProfileCollectionService(
        datahub=profiles,
        targets=_Targets(None),
        projection=_Projection(),
    ).collect(
        workspace_id=workspace_id,
        asset_id=asset_id,
    )
    assert result.availability == "UNAVAILABLE"
    assert result.failure_code == "TARGET_UNAVAILABLE"
    assert not profiles.called
