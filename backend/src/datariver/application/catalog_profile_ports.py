from __future__ import annotations

from typing import Protocol
from uuid import UUID

from datariver.application.catalog_profile_contracts import (
    CatalogProfileProjectionCommand,
    CatalogProfileProjectionResult,
    CatalogProfileTarget,
    DataHubProfileObservation,
)


class DataHubProfileReader(Protocol):
    async def get_profile(
        self,
        *,
        external_urn: str,
        workspace_id: UUID,
        asset_id: UUID,
    ) -> DataHubProfileObservation | None: ...


class CatalogProfileTargetReader(Protocol):
    async def get_target(
        self,
        *,
        workspace_id: UUID,
        asset_id: UUID,
    ) -> CatalogProfileTarget | None: ...


class CatalogProfileProjection(Protocol):
    async def project(
        self,
        command: CatalogProfileProjectionCommand,
    ) -> CatalogProfileProjectionResult: ...
