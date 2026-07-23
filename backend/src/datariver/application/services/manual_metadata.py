from __future__ import annotations

import csv
import io
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import quote
from uuid import UUID

from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.dto import CatalogAssetIndex
from datariver.application.ports import (
    CatalogExportObjectStore,
    CatalogIndexReader,
    DataHubGateway,
    GovernanceUnitOfWork,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.catalog import is_dataset_asset_type
from datariver.domain.common import ConflictError, ValidationError
from datariver.domain.manual_metadata import (
    ManualColumnMetadata,
    ManualMetadataSubmission,
)

MAXIMUM_CSV_BYTES = 5 * 1024 * 1024


class ManualMetadataUowFactory(Protocol):
    def __call__(self) -> GovernanceUnitOfWork: ...


@dataclass(frozen=True, slots=True)
class _NormalizedManualMetadata:
    description: str
    domain: str | None
    tags: tuple[str, ...]
    terms: tuple[str, ...]
    columns: tuple[ManualColumnMetadata, ...]


class ManualMetadataSubmissionService:
    """Stage a typed manual metadata edit without coupling it to Change Requests.

    The service reads the provider only through the existing DataHub anti-corruption port to
    validate the selected schema fields.  The browser never sends aspect documents, a bucket/key,
    an Airflow URL, or a provider credential.
    """

    def __init__(
        self,
        *,
        index: CatalogIndexReader,
        classification_access: ClassificationAccessResolver,
        authorization: AuthorizationService,
        datahub: DataHubGateway,
        object_store: CatalogExportObjectStore,
        uow_factory: ManualMetadataUowFactory,
        infoschema_bucket: str | None,
    ) -> None:
        self._index = index
        self._classification_access = classification_access
        self._authorization = authorization
        self._datahub = datahub
        self._object_store = object_store
        self._uow_factory = uow_factory
        self._infoschema_bucket = infoschema_bucket

    async def submit(
        self,
        *,
        asset_id: UUID,
        source_version: str,
        description: str,
        domain: str | None,
        tags: tuple[str, ...],
        terms: tuple[str, ...],
        columns: tuple[ManualColumnMetadata, ...],
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> ManualMetadataSubmission:
        if not self._infoschema_bucket:
            raise ValidationError(
                "Manual metadata storage is not configured.",
                details={"code": "INFOSCHEMA_BUCKET_NOT_CONFIGURED"},
            )
        normalized = self._normalize(
            description=description,
            domain=domain,
            tags=tags,
            terms=terms,
            columns=columns,
        )
        access = await self._classification_access.resolve(
            workspace_id=subject.workspace_id,
            subject_id=subject.subject_id,
            now=environment.requested_at,
        )
        detail = await self._index.get_authorized_asset(
            subject=subject,
            access=access,
            asset_id=asset_id,
        )
        if detail is None or not is_dataset_asset_type(detail.index.asset_type):
            raise ValidationError(
                "The selected catalog asset is not available for manual registration."
            )
        asset = detail.index
        if source_version != asset.source_version:
            raise ConflictError(
                "The selected catalog asset changed. Reload its metadata before saving.",
                details={"code": "SOURCE_VERSION_MISMATCH"},
            )
        resource = ResourceAttributes(
            resource_id=asset.asset_id,
            workspace_id=asset.workspace_id,
            resource_type="manual_metadata_submission",
            owner_department_id=asset.owner_department_id,
            system_id=asset.system_id,
            domain_id=asset.domain_id,
            classification=asset.classification,
            lifecycle=asset.lifecycle,
        )
        await self._authorization.authorize(
            subject=subject,
            resource=resource,
            action=Action.CATALOG_READ,
            environment=environment,
            request_id=request_id,
        )
        await self._authorization.authorize(
            subject=subject,
            resource=resource,
            action=Action.REGISTRATION_CREATE,
            environment=environment,
            request_id=request_id,
        )
        enrichment = await self._datahub.get_asset(asset.external_urn)
        if enrichment.schema_fields_truncated or not enrichment.schema_fields_total_exact:
            raise ConflictError(
                "The provider schema exceeds the safe editable boundary.",
                details={"code": "SCHEMA_FIELDS_TRUNCATED"},
            )
        schema = self._schema_fields(enrichment.schema_fields)
        if set(column.field_path for column in normalized.columns) != set(schema):
            raise ConflictError(
                "The provider schema changed. Reload its metadata before saving.",
                details={"code": "SCHEMA_FIELD_DRIFT"},
            )

        artifact_written = False
        object_key = ""
        async with self._uow_factory() as uow:
            await uow.set_security_context(
                workspace_id=subject.workspace_id,
                subject_id=subject.subject_id,
            )
            operation = f"manual-metadata.submit:{asset_id}"
            existing = await uow.idempotency.get_result(
                workspace_id=subject.workspace_id,
                key=idempotency_key,
                operation=operation,
            )
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise ConflictError("The idempotency key was used with a different request.")
                submission_id = UUID(str(existing.result["submission_id"]))
                stored = await uow.manual_metadata_submissions.get(
                    workspace_id=subject.workspace_id,
                    submission_id=submission_id,
                )
                if stored is None or stored.requester_id != subject.subject_id:
                    raise ConflictError("The idempotent manual submission is unavailable.")
                return stored

            serial_number = await uow.manual_metadata_submissions.allocate_serial_number()
            object_key = self._object_key(serial_number=serial_number, now=environment.requested_at)
            csv_bytes, row_count = self._csv_document(
                asset=asset,
                schema=schema,
                description=normalized.description,
                domain=normalized.domain,
                tags=normalized.tags,
                terms=normalized.terms,
                columns=normalized.columns,
            )
            artifact = await self._object_store.write_export(
                bucket=self._infoschema_bucket,
                object_key=object_key,
                chunks=self._one_chunk(csv_bytes),
                metadata={
                    "workspace-id": str(subject.workspace_id),
                    "asset-id": str(asset.asset_id),
                    "source-version": asset.source_version,
                    "content-kind": "manual-metadata-csv-v1",
                },
                maximum_bytes=MAXIMUM_CSV_BYTES,
            )
            artifact_written = True
            if artifact.size_bytes != len(csv_bytes):
                raise ConflictError("Manual metadata CSV receipt did not reconcile.")
            submission = ManualMetadataSubmission.queue(
                workspace_id=subject.workspace_id,
                asset_id=asset.asset_id,
                external_urn=asset.external_urn,
                requester_id=subject.subject_id,
                source_version=asset.source_version,
                serial_number=serial_number,
                description=normalized.description,
                domain=normalized.domain,
                tags=normalized.tags,
                terms=normalized.terms,
                columns=normalized.columns,
                bucket=self._infoschema_bucket,
                object_key=object_key,
                csv_sha256=artifact.content_sha256,
                csv_size_bytes=artifact.size_bytes,
                row_count=row_count,
            )
            try:
                await uow.manual_metadata_submissions.add(submission)
                await uow.outbox.add_events(submission.events)
                await uow.idempotency.save_result(
                    workspace_id=subject.workspace_id,
                    key=idempotency_key,
                    operation=operation,
                    request_hash=request_hash,
                    result={"submission_id": str(submission.submission_id)},
                )
                await uow.commit()
            except Exception:
                if artifact_written:
                    await self._delete_or_raise(
                        bucket=self._infoschema_bucket,
                        object_key=object_key,
                    )
                raise
        submission.events.clear()
        return submission

    @staticmethod
    def _normalize(
        *,
        description: str,
        domain: str | None,
        tags: tuple[str, ...],
        terms: tuple[str, ...],
        columns: tuple[ManualColumnMetadata, ...],
    ) -> _NormalizedManualMetadata:
        normalized_columns = tuple(
            ManualColumnMetadata(
                field_path=column.field_path,
                description=column.description,
                tags=ManualMetadataSubmissionService._refs(column.tags, "urn:li:tag:"),
                terms=ManualMetadataSubmissionService._refs(column.terms, "urn:li:glossaryTerm:"),
            )
            for column in columns
        )
        return _NormalizedManualMetadata(
            description=description,
            domain=(
                ManualMetadataSubmissionService._refs((domain,), "urn:li:domain:")[0]
                if domain and domain.strip()
                else None
            ),
            tags=ManualMetadataSubmissionService._refs(tags, "urn:li:tag:"),
            terms=ManualMetadataSubmissionService._refs(terms, "urn:li:glossaryTerm:"),
            columns=normalized_columns,
        )

    @staticmethod
    def _refs(values: tuple[str, ...], prefix: str) -> tuple[str, ...]:
        normalized: list[str] = []
        for value in values:
            candidate = value.strip()
            if not candidate:
                continue
            if candidate.startswith("urn:li:"):
                if not candidate.startswith(prefix):
                    raise ValidationError("A controlled metadata reference has the wrong type.")
            else:
                candidate = prefix + quote(candidate, safe="._-~")
            if candidate not in normalized:
                normalized.append(candidate)
        return tuple(normalized)

    @staticmethod
    def _schema_fields(fields: tuple[dict[str, object], ...]) -> dict[str, str]:
        values: dict[str, str] = {}
        for field in fields:
            field_path = field.get("fieldPath")
            if not isinstance(field_path, str) or not field_path:
                continue
            data_type = field.get("nativeDataType")
            values[field_path] = data_type if isinstance(data_type, str) else ""
        return values

    @staticmethod
    def _object_key(*, serial_number: int, now: datetime) -> str:
        return f"UPLOAD_METADATA_MANUAL_{now.astimezone(UTC):%y%m%d}_{serial_number:06d}.csv"

    @staticmethod
    def _csv_document(
        *,
        asset: CatalogAssetIndex,
        schema: dict[str, str],
        description: str,
        domain: str | None,
        tags: tuple[str, ...],
        terms: tuple[str, ...],
        columns: tuple[ManualColumnMetadata, ...],
    ) -> tuple[bytes, int]:
        external_urn = asset.external_urn
        source_version = asset.source_version
        platform = asset.platform or ""
        database_name = asset.database_name or ""
        schema_name = asset.schema_name or ""
        table_name = asset.name
        buffer = io.StringIO(newline="")
        fieldnames = (
            "record_kind",
            "external_urn",
            "source_version",
            "platform",
            "database_name",
            "schema_name",
            "table_name",
            "column_name",
            "data_type",
            "description",
            "domain",
            "tags",
            "terms",
        )
        writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerow(
            {
                "record_kind": "TABLE",
                "external_urn": external_urn,
                "source_version": source_version,
                "platform": platform,
                "database_name": database_name,
                "schema_name": schema_name,
                "table_name": table_name,
                "column_name": "",
                "data_type": "",
                "description": description,
                "domain": domain or "",
                "tags": ",".join(tags),
                "terms": ",".join(terms),
            }
        )
        for column in columns:
            writer.writerow(
                {
                    "record_kind": "COLUMN",
                    "external_urn": external_urn,
                    "source_version": source_version,
                    "platform": platform,
                    "database_name": database_name,
                    "schema_name": schema_name,
                    "table_name": table_name,
                    "column_name": column.field_path,
                    "data_type": schema[column.field_path],
                    "description": column.description,
                    "domain": "",
                    "tags": ",".join(column.tags),
                    "terms": ",".join(column.terms),
                }
            )
        return buffer.getvalue().encode("utf-8"), len(columns) + 1

    @staticmethod
    async def _one_chunk(value: bytes) -> AsyncIterator[bytes]:
        yield value

    async def _delete_or_raise(self, *, bucket: str, object_key: str) -> None:
        try:
            await self._object_store.delete_export(bucket=bucket, object_key=object_key)
        except Exception as error:
            raise ConflictError(
                "Manual metadata persistence failed and its private CSV could not be cleaned up.",
                details={"code": "MANUAL_METADATA_ORPHANED", "cause": type(error).__name__},
            ) from error
