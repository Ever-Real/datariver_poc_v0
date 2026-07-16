from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC
from uuid import UUID

from datariver.application.catalog_export_csv import (
    CatalogExportCsvRow,
    catalog_export_csv_header,
    encode_catalog_export_csv_row,
)
from datariver.application.dto import CatalogExportClaim
from datariver.application.errors import ExternalDependencyError
from datariver.application.ports import CatalogExportObjectStore, CatalogExportWorkerStore
from datariver.domain.common import ConflictError, DomainError, ValidationError


class CatalogExportWorker:
    def __init__(
        self,
        *,
        store: CatalogExportWorkerStore,
        object_store: CatalogExportObjectStore,
        export_bucket: str,
        worker_id: str,
        system_actor_id: UUID,
        lease_seconds: int,
        maximum_attempts: int,
        page_size: int,
        maximum_rows: int,
        maximum_bytes: int,
    ) -> None:
        self._store = store
        self._object_store = object_store
        self._export_bucket = export_bucket
        self._worker_id = worker_id
        self._system_actor_id = system_actor_id
        self._lease_seconds = lease_seconds
        self._maximum_attempts = maximum_attempts
        self._page_size = page_size
        self._maximum_rows = maximum_rows
        self._maximum_bytes = maximum_bytes

    async def run_once(self) -> bool:
        claim = await self._store.claim_next(
            worker_id=self._worker_id,
            system_actor_id=self._system_actor_id,
            lease_seconds=self._lease_seconds,
            maximum_attempts=self._maximum_attempts,
        )
        if claim is None:
            return False
        if not claim.snapshot_valid:
            await self._fail(
                claim=claim,
                error_code="SOURCE_OR_POLICY_SNAPSHOT_STALE",
                retryable=False,
            )
            return True

        object_key = (
            f"exports/{claim.export.workspace_id}/{claim.export.export_id}/"
            f"attempts/{claim.attempt_id}/catalog.csv"
        )
        count = [0]

        async def chunks() -> AsyncIterator[bytes]:
            yield catalog_export_csv_header()
            cursor: str | None = None
            while True:
                page = await self._store.read_page(
                    claim=claim,
                    cursor=cursor,
                    limit=self._page_size,
                )
                for asset in page.items:
                    if count[0] >= self._maximum_rows:
                        raise ValidationError(
                            "The catalog export exceeds the configured row limit.",
                            details={"code": "EXPORT_ROW_LIMIT"},
                        )
                    yield encode_catalog_export_csv_row(
                        CatalogExportCsvRow(
                            asset_id=asset.asset_id,
                            external_urn=asset.external_urn,
                            platform=asset.platform,
                            database_name=asset.database_name,
                            schema_name=asset.schema_name,
                            name=asset.name,
                            asset_type=asset.asset_type,
                            classification=asset.classification.name,
                            lifecycle=asset.lifecycle,
                            description=asset.description,
                            source_version=asset.source_version,
                            observed_at=asset.observed_at.astimezone(UTC).isoformat(),
                        )
                    )
                    count[0] += 1
                if page.next_cursor is None:
                    return
                cursor = page.next_cursor

        completed_object = False
        try:
            artifact = await self._object_store.write_export(
                bucket=self._export_bucket,
                object_key=object_key,
                chunks=chunks(),
                metadata={
                    "export-id": str(claim.export.export_id),
                    "request-hash": claim.export.request_hash,
                    "csv-safety-version": claim.export.csv_safety_version,
                },
                maximum_bytes=self._maximum_bytes,
            )
            completed_object = True
            if not await self._store.snapshot_is_current(claim=claim):
                raise ConflictError("The catalog export snapshot changed before completion.")
            await self._store.mark_completed(
                claim=claim,
                system_actor_id=self._system_actor_id,
                bucket=self._export_bucket,
                object_key=object_key,
                artifact=artifact,
                row_count=count[0],
            )
        except DomainError as error:
            if completed_object:
                await self._best_effort_delete(object_key=object_key)
            await self._fail(
                claim=claim,
                error_code=self._error_code(error),
                retryable=self._retryable(error),
            )
        except Exception as error:
            if completed_object:
                await self._best_effort_delete(object_key=object_key)
            await self._fail(
                claim=claim,
                error_code=f"UNEXPECTED_{type(error).__name__}"[:100],
                retryable=True,
            )
        return True

    async def _fail(self, *, claim: CatalogExportClaim, error_code: str, retryable: bool) -> None:
        await self._store.mark_failed(
            claim=claim,
            system_actor_id=self._system_actor_id,
            error_code=error_code,
            retryable=retryable,
            maximum_attempts=self._maximum_attempts,
        )

    async def _best_effort_delete(self, *, object_key: str) -> None:
        try:
            await self._object_store.delete_export(
                bucket=self._export_bucket,
                object_key=object_key,
            )
        except DomainError:
            # The object is private and never became a downloadable completed record.
            pass

    @staticmethod
    def _retryable(error: DomainError) -> bool:
        return isinstance(error, ExternalDependencyError) and bool(
            error.details.get("retryable", False)
        )

    @staticmethod
    def _error_code(error: DomainError) -> str:
        return str(error.details.get("code") or error.details.get("provider_code") or error.code)[
            :100
        ]
