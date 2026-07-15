from __future__ import annotations

from uuid import UUID

from datariver.application.dto import CatalogSyncResult
from datariver.application.ports import CatalogProjectionWriter, DataHubGateway
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)


class CatalogSyncService:
    def __init__(
        self,
        *,
        datahub: DataHubGateway,
        writer: CatalogProjectionWriter,
        authorization: AuthorizationService,
    ) -> None:
        self._datahub = datahub
        self._writer = writer
        self._authorization = authorization

    async def sync_page(
        self,
        *,
        workspace_id: UUID,
        sync_id: UUID,
        offset: int,
        limit: int,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> CatalogSyncResult:
        await self._authorization.authorize(
            subject=subject,
            resource=ResourceAttributes(
                resource_id=workspace_id,
                workspace_id=workspace_id,
                resource_type="catalog_projection",
                owner_department_id=None,
                system_id=None,
                domain_id=None,
                classification=Classification.RESTRICTED,
                lifecycle="ACTIVE",
            ),
            action=Action.CATALOG_SYNC,
            environment=environment,
            request_id=request_id,
        )
        page = await self._datahub.scan_assets(offset=offset, limit=limit)
        upserted, tombstoned = await self._writer.upsert_scan(
            workspace_id=workspace_id,
            sync_id=sync_id,
            offset=offset,
            next_offset=page.next_offset,
            items=page.items,
            observed_at=page.observed_at,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            operation=f"catalog.datahub.sync:{offset}:{limit}",
        )
        return CatalogSyncResult(
            upserted=upserted,
            tombstoned=tombstoned,
            next_offset=page.next_offset,
            total=page.total,
            observed_at=page.observed_at,
        )
