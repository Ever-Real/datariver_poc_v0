from __future__ import annotations

import asyncio
from uuid import UUID

from datariver.application.dto import CatalogSyncProgress, CatalogSyncResult
from datariver.application.errors import ExternalDependencyError
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
        reservation_provider_budget_seconds: float = 10.0,
    ) -> None:
        if not 0 < reservation_provider_budget_seconds <= 10:
            raise ValueError("The catalog sync reservation provider budget is invalid.")
        self._datahub = datahub
        self._writer = writer
        self._authorization = authorization
        self._reservation_provider_budget_seconds = reservation_provider_budget_seconds

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
        operation = f"catalog.datahub.sync:{offset}:{limit}"
        reservation = await self._writer.reserve_scan(
            workspace_id=workspace_id,
            sync_id=sync_id,
            offset=offset,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            operation=operation,
        )
        if reservation.replayed is not None:
            return reservation.replayed
        cursor = reservation.cursor
        effective_limit = limit
        try:
            try:
                async with asyncio.timeout(self._reservation_provider_budget_seconds):
                    while True:
                        try:
                            page = await self._datahub.scan_assets(
                                cursor=cursor,
                                limit=effective_limit,
                            )
                            break
                        except ExternalDependencyError as error:
                            if (
                                error.details.get("provider_code") == "RESPONSE_TOO_LARGE"
                                and effective_limit > 1
                            ):
                                effective_limit = max(1, effective_limit // 2)
                                continue
                            raise
            except TimeoutError as error:
                raise ExternalDependencyError(
                    "DataHub exceeded the catalog sync reservation provider budget.",
                    dependency="datahub",
                    retryable=True,
                    provider_code="SYNC_RESERVATION_TIMEOUT",
                ) from error
        except ExternalDependencyError as error:
            if cursor is not None and not error.details.get("retryable", False):
                await self._writer.abandon_scan(
                    workspace_id=workspace_id,
                    sync_id=sync_id,
                )
            else:
                await self._writer.release_scan()
            raise
        except BaseException:
            await self._writer.release_scan()
            raise
        next_offset = offset + 1 if page.next_cursor is not None else None
        try:
            return await self._writer.upsert_scan(
                workspace_id=workspace_id,
                sync_id=sync_id,
                offset=offset,
                cursor=cursor,
                next_offset=next_offset,
                next_cursor=page.next_cursor,
                total=page.total,
                snapshot_consistent=page.snapshot_consistent,
                snapshot_evidence_reference=page.snapshot_evidence_reference,
                snapshot_contract_hash=page.snapshot_contract_hash,
                snapshot_provider_version=page.snapshot_provider_version,
                items=page.items,
                observed_at=page.observed_at,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                operation=operation,
            )
        except BaseException:
            await self._writer.release_scan()
            raise

    async def progress(
        self,
        *,
        workspace_id: UUID,
        sync_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> CatalogSyncProgress:
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
        return await self._writer.scan_progress(
            workspace_id=workspace_id,
            sync_id=sync_id,
        )
