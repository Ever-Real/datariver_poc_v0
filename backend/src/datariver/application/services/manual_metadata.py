from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import quote
from uuid import UUID

from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.dto import CatalogAssetIndex, IdempotencyRecord
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


class _BoundedTextBuffer:
    """Accumulate a UTF-8 CSV only while it remains inside the accepted receipt budget."""

    def __init__(self, *, maximum_bytes: int) -> None:
        self._buffer = io.StringIO(newline="")
        self._maximum_bytes = maximum_bytes
        self._size_bytes = 0

    def write(self, value: str) -> int:
        size_bytes = len(value.encode("utf-8"))
        if self._size_bytes + size_bytes > self._maximum_bytes:
            raise ValidationError(
                "Manual metadata CSV exceeds the accepted receipt size.",
                details={"code": "MANUAL_METADATA_RECEIPT_TOO_LARGE"},
            )
        self._size_bytes += size_bytes
        return self._buffer.write(value)

    def getvalue(self) -> str:
        return self._buffer.getvalue()


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
        provider_source_version: str | None,
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
        operation = f"manual-metadata.submit:{asset_id}"
        async with self._uow_factory() as replay_uow:
            await replay_uow.set_security_context(
                workspace_id=subject.workspace_id,
                subject_id=subject.subject_id,
            )
            await replay_uow.idempotency.acquire_key_lock(
                workspace_id=subject.workspace_id,
                key=idempotency_key,
                operation=operation,
            )
            existing = await replay_uow.idempotency.get_result(
                workspace_id=subject.workspace_id,
                key=idempotency_key,
                operation=operation,
            )
            if existing is not None:
                return await self._existing_submission(
                    uow=replay_uow,
                    workspace_id=subject.workspace_id,
                    requester_id=subject.subject_id,
                    request_hash=request_hash,
                    existing=existing,
                )

        enrichment = await self._datahub.get_asset(asset.external_urn)
        if (
            provider_source_version is not None
            and enrichment.raw_version != provider_source_version
        ):
            raise ConflictError(
                "The provider metadata changed. Reload it before saving.",
                details={"code": "PROVIDER_SOURCE_VERSION_MISMATCH"},
            )
        resolved_provider_source_version = enrichment.raw_version
        if (
            enrichment.schema_fields_truncated
            or not enrichment.schema_fields_total_exact
            or enrichment.description_truncated
            or enrichment.tags_truncated
            or enrichment.glossary_terms_truncated
        ):
            raise ConflictError(
                "The provider metadata exceeds the safe editable boundary.",
                details={"code": "PROVIDER_METADATA_TRUNCATED"},
            )
        schema, final_columns = self._rehydrate_columns(
            fields=enrichment.schema_fields,
            edits=normalized.columns,
        )

        object_key = ""
        async with self._uow_factory() as uow:
            await uow.set_security_context(
                workspace_id=subject.workspace_id,
                subject_id=subject.subject_id,
            )
            await uow.idempotency.acquire_key_lock(
                workspace_id=subject.workspace_id,
                key=idempotency_key,
                operation=operation,
            )
            existing = await uow.idempotency.get_result(
                workspace_id=subject.workspace_id,
                key=idempotency_key,
                operation=operation,
            )
            if existing is not None:
                return await self._existing_submission(
                    uow=uow,
                    workspace_id=subject.workspace_id,
                    requester_id=subject.subject_id,
                    request_hash=request_hash,
                    existing=existing,
                )

            serial_number = await uow.manual_metadata_submissions.allocate_serial_number()
            object_key = self._object_key(serial_number=serial_number, now=environment.requested_at)
            csv_bytes, row_count = self._csv_document(
                asset=asset,
                schema=schema,
                description=normalized.description,
                domain=normalized.domain,
                tags=normalized.tags,
                terms=normalized.terms,
                columns=final_columns,
            )
            if len(csv_bytes) > MAXIMUM_CSV_BYTES:
                raise ValidationError(
                    "Manual metadata CSV exceeds the accepted receipt size.",
                    details={"code": "MANUAL_METADATA_RECEIPT_TOO_LARGE"},
                )
            csv_sha256 = hashlib.sha256(csv_bytes).hexdigest()
            submission = ManualMetadataSubmission.queue(
                workspace_id=subject.workspace_id,
                asset_id=asset.asset_id,
                external_urn=asset.external_urn,
                requester_id=subject.subject_id,
                source_version=asset.source_version,
                provider_source_version=resolved_provider_source_version,
                serial_number=serial_number,
                description=normalized.description,
                domain=normalized.domain,
                tags=normalized.tags,
                terms=normalized.terms,
                columns=final_columns,
                bucket=self._infoschema_bucket,
                object_key=object_key,
                csv_sha256=csv_sha256,
                csv_size_bytes=len(csv_bytes),
                row_count=row_count,
            )
            await uow.manual_metadata_submissions.add(submission)
            await uow.outbox.add_events(submission.events)
            await uow.idempotency.save_result(
                workspace_id=subject.workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                result={"submission_id": str(submission.submission_id)},
            )
            # Flush every deterministic database constraint before creating the external
            # immutable object. After the create begins, deletion is never a safe compensation
            # because commit outcome and object replacement can be ambiguous.
            await uow.flush()
            artifact = await self._object_store.write_immutable_receipt(
                bucket=self._infoschema_bucket,
                object_key=object_key,
                content=csv_bytes,
                metadata={
                    "workspace-id": str(subject.workspace_id),
                    "asset-id": str(asset.asset_id),
                    "submission-id": str(submission.submission_id),
                    "serial-number": str(serial_number),
                    "content-sha256": csv_sha256,
                    "content-size": str(len(csv_bytes)),
                    "source-version": asset.source_version,
                    "provider-source-version": resolved_provider_source_version,
                    "content-kind": "manual-metadata-csv-v1",
                },
                maximum_bytes=MAXIMUM_CSV_BYTES,
            )
            if artifact.size_bytes != len(csv_bytes) or artifact.content_sha256 != csv_sha256:
                raise ConflictError("Manual metadata CSV receipt did not reconcile.")
            # A COMMIT transport error is outcome-ambiguous: PostgreSQL may already have
            # committed the row. Never delete the receipt after commit has been attempted,
            # because doing so could corrupt that durable submission. An unreferenced object is
            # reconciled by operations instead.
            await uow.commit()
        submission.events.clear()
        return submission

    @staticmethod
    async def _existing_submission(
        *,
        uow: GovernanceUnitOfWork,
        workspace_id: UUID,
        requester_id: UUID,
        request_hash: str,
        existing: IdempotencyRecord,
    ) -> ManualMetadataSubmission:
        if existing.request_hash != request_hash:
            raise ConflictError("The idempotency key was used with a different request.")
        submission_id = UUID(str(existing.result["submission_id"]))
        stored = await uow.manual_metadata_submissions.get(
            workspace_id=workspace_id,
            submission_id=submission_id,
        )
        if stored is None or stored.requester_id != requester_id:
            raise ConflictError("The idempotent manual submission is unavailable.")
        return stored

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
            if len(candidate) > 1_000:
                raise ValidationError("A controlled metadata reference exceeds the limit.")
            if candidate not in normalized:
                normalized.append(candidate)
        return tuple(normalized)

    @staticmethod
    def _rehydrate_columns(
        *,
        fields: tuple[dict[str, object], ...],
        edits: tuple[ManualColumnMetadata, ...],
    ) -> tuple[dict[str, str], tuple[ManualColumnMetadata, ...]]:
        schema: dict[str, str] = {}
        baseline: dict[str, ManualColumnMetadata] = {}
        for field in fields:
            field_path = field.get("fieldPath")
            if (
                not isinstance(field_path, str)
                or not field_path
                or len(field_path) > 2_000
                or field_path in schema
            ):
                raise ConflictError(
                    "The provider schema contains an invalid field path.",
                    details={"code": "SCHEMA_FIELD_INVALID"},
                )
            if any(
                field.get(flag) is True
                for flag in (
                    "type_truncated",
                    "nativeDataType_truncated",
                    "label_truncated",
                    "description_truncated",
                    "tags_truncated",
                    "terms_truncated",
                )
            ):
                raise ConflictError(
                    "A provider schema field exceeds the safe editable boundary.",
                    details={"code": "SCHEMA_FIELD_TRUNCATED"},
                )
            data_type = field.get("nativeDataType")
            schema[field_path] = data_type if isinstance(data_type, str) else ""
            description = field.get("description")
            baseline[field_path] = ManualColumnMetadata(
                field_path=field_path,
                description=description if isinstance(description, str) else "",
                tags=ManualMetadataSubmissionService._field_refs(
                    field.get("globalTags"),
                    collection="tags",
                    nested="tag",
                    prefix="urn:li:tag:",
                ),
                terms=ManualMetadataSubmissionService._field_refs(
                    field.get("glossaryTerms"),
                    collection="terms",
                    nested="term",
                    prefix="urn:li:glossaryTerm:",
                ),
            )
        edit_paths = {edit.field_path for edit in edits}
        if len(edit_paths) != len(edits) or not edit_paths.issubset(schema):
            raise ConflictError(
                "The provider schema changed. Reload its metadata before saving.",
                details={"code": "SCHEMA_FIELD_DRIFT"},
            )
        by_path = {edit.field_path: edit for edit in edits}
        final_columns = tuple(
            by_path.get(field_path, baseline[field_path]) for field_path in schema
        )
        return schema, final_columns

    @staticmethod
    def _field_refs(
        value: object,
        *,
        collection: str,
        nested: str,
        prefix: str,
    ) -> tuple[str, ...]:
        document = value if isinstance(value, dict) else {}
        items = document.get(collection)
        if items is None:
            return ()
        if not isinstance(items, list) or len(items) > 100:
            raise ConflictError(
                "A provider controlled metadata field is invalid.",
                details={"code": "SCHEMA_FIELD_METADATA_INVALID"},
            )
        references: list[str] = []
        for item in items:
            candidate = item.get(nested) if isinstance(item, dict) else None
            if isinstance(candidate, dict):
                candidate = candidate.get("urn") or candidate.get("name")
            if not isinstance(candidate, str) or not candidate:
                raise ConflictError(
                    "A provider controlled metadata reference is invalid.",
                    details={"code": "SCHEMA_FIELD_METADATA_INVALID"},
                )
            normalized = ManualMetadataSubmissionService._refs((candidate,), prefix)[0]
            if normalized not in references:
                references.append(normalized)
        return tuple(references)

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
        buffer = _BoundedTextBuffer(maximum_bytes=MAXIMUM_CSV_BYTES)
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
