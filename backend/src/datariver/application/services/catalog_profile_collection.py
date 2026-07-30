from __future__ import annotations

from uuid import UUID

from datariver.application.catalog_profile_contracts import (
    CatalogProfileCollectionResult,
    CatalogProfileProjectionCommand,
)
from datariver.application.catalog_profile_ports import (
    CatalogProfileProjection,
    CatalogProfileTargetReader,
    DataHubProfileReader,
)
from datariver.domain.common import canonical_json_hash


class CatalogProfileCollectionService:
    def __init__(
        self,
        *,
        datahub: DataHubProfileReader,
        targets: CatalogProfileTargetReader,
        projection: CatalogProfileProjection,
    ) -> None:
        self._datahub = datahub
        self._targets = targets
        self._projection = projection

    async def collect(
        self,
        *,
        workspace_id: UUID,
        asset_id: UUID,
    ) -> CatalogProfileCollectionResult:
        # The target port is an authorized boundary, not a generic repository read. Its
        # PostgreSQL implementation is a fixed SECURITY DEFINER function that checks the
        # transaction-local subject, exact service group/Action and target scope before a
        # provider request can occur. Projection repeats those checks under the same transaction.
        target = await self._targets.get_target(
            workspace_id=workspace_id,
            asset_id=asset_id,
        )
        if target is None:
            return CatalogProfileCollectionResult(
                availability="UNAVAILABLE",
                failure_code="TARGET_UNAVAILABLE",
                projection=None,
            )
        observation = await self._datahub.get_profile(
            external_urn=target.external_urn,
            workspace_id=workspace_id,
            asset_id=asset_id,
        )
        if observation is None:
            return CatalogProfileCollectionResult(
                availability="UNAVAILABLE",
                failure_code="PROFILE_UNAVAILABLE",
                projection=None,
            )
        source_watermark_hash = canonical_json_hash(
            {
                "asset_id": str(target.asset_id),
                "contract": "CATALOG_ASSET_SOURCE_WATERMARK_V1",
                "source_version": target.source_version,
                "workspace_id": str(target.workspace_id),
            }
        )
        projected = await self._projection.project(
            CatalogProfileProjectionCommand(
                target=target,
                observation=observation,
                source_watermark_hash=source_watermark_hash,
            )
        )
        return CatalogProfileCollectionResult(
            availability="AVAILABLE",
            failure_code=None,
            projection=projected,
        )
