from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from datariver.application.errors import ExternalDependencyError
from datariver.application.ports import (
    DataHubGateway,
    GovernanceUnitOfWork,
    ObjectStore,
)
from datariver.domain.common import ConflictError, DomainError, canonical_json_hash
from datariver.domain.manual_metadata import ManualMetadataSubmission

MAXIMUM_MANUAL_RECEIPT_BYTES = 5 * 1024 * 1024


class ManualMetadataApplyUowFactory(Protocol):
    def __call__(self) -> GovernanceUnitOfWork: ...


@dataclass(frozen=True, slots=True)
class ManualMetadataApplyResult:
    processed: bool
    submission_id: UUID | None = None
    serial_number: int | None = None
    state: str | None = None


class ManualMetadataApplyService:
    """Apply one immutable MANUAL CSV receipt through a service-account-only worker boundary.

    The worker re-reads the private CSV from object storage, verifies its retained hash and shape,
    then read-merges only the typed five DataHub aspect families.  Each aspect has a stable
    idempotency key and a post-write read-back; partial external success can therefore resume
    without treating a provider acceptance as completion.
    """

    def __init__(
        self,
        *,
        datahub: DataHubGateway,
        object_store: ObjectStore,
        uow_factory: ManualMetadataApplyUowFactory,
        lease_seconds: int,
        maximum_attempts: int,
    ) -> None:
        self._datahub = datahub
        self._object_store = object_store
        self._uow_factory = uow_factory
        self._lease_seconds = lease_seconds
        self._maximum_attempts = maximum_attempts

    async def run_once(
        self, *, workspace_id: UUID, worker_subject_id: UUID
    ) -> ManualMetadataApplyResult:
        submission = await self._claim_next(
            workspace_id=workspace_id,
            worker_subject_id=worker_subject_id,
        )
        if submission is None:
            return ManualMetadataApplyResult(processed=False)
        try:
            await self._verify_csv_receipt(submission)
            await self._apply_submission(submission)
        except DomainError as error:
            await self._mark_failed(
                submission=submission,
                worker_subject_id=worker_subject_id,
                error_code=self._error_code(error),
                retryable=self._retryable(error),
            )
            return ManualMetadataApplyResult(
                processed=True,
                submission_id=submission.submission_id,
                serial_number=submission.serial_number,
                state="QUEUED" if self._retryable(error) else "FAILED",
            )
        except Exception as error:
            await self._mark_failed(
                submission=submission,
                worker_subject_id=worker_subject_id,
                error_code=f"UNEXPECTED_{type(error).__name__}"[:100],
                retryable=True,
            )
            return ManualMetadataApplyResult(
                processed=True,
                submission_id=submission.submission_id,
                serial_number=submission.serial_number,
                state="QUEUED",
            )
        await self._mark_applied(submission=submission, worker_subject_id=worker_subject_id)
        return ManualMetadataApplyResult(
            processed=True,
            submission_id=submission.submission_id,
            serial_number=submission.serial_number,
            state="APPLIED",
        )

    async def _claim_next(
        self, *, workspace_id: UUID, worker_subject_id: UUID
    ) -> ManualMetadataSubmission | None:
        async with self._uow_factory() as uow:
            await uow.set_security_context(workspace_id=workspace_id, subject_id=worker_subject_id)
            submission = await uow.manual_metadata_submissions.claim_next(
                workspace_id=workspace_id,
                now=self._now(),
                lease_seconds=self._lease_seconds,
                maximum_attempts=self._maximum_attempts,
            )
            await uow.commit()
            return submission

    async def _mark_applied(
        self, *, submission: ManualMetadataSubmission, worker_subject_id: UUID
    ) -> None:
        async with self._uow_factory() as uow:
            await uow.set_security_context(
                workspace_id=submission.workspace_id,
                subject_id=worker_subject_id,
            )
            current = await uow.manual_metadata_submissions.get(
                workspace_id=submission.workspace_id,
                submission_id=submission.submission_id,
            )
            if current is None:
                raise ConflictError("The claimed manual metadata submission disappeared.")
            current.mark_applied(now=self._now())
            await uow.manual_metadata_submissions.save(current)
            await uow.outbox.add_events(current.events)
            await uow.commit()

    async def _mark_failed(
        self,
        *,
        submission: ManualMetadataSubmission,
        worker_subject_id: UUID,
        error_code: str,
        retryable: bool,
    ) -> None:
        async with self._uow_factory() as uow:
            await uow.set_security_context(
                workspace_id=submission.workspace_id,
                subject_id=worker_subject_id,
            )
            current = await uow.manual_metadata_submissions.get(
                workspace_id=submission.workspace_id,
                submission_id=submission.submission_id,
            )
            if current is None:
                raise ConflictError("The claimed manual metadata submission disappeared.")
            current.mark_apply_failed(
                now=self._now(),
                error_code=error_code,
                retryable=retryable and current.attempts < self._maximum_attempts,
            )
            await uow.manual_metadata_submissions.save(current)
            await uow.commit()

    async def _verify_csv_receipt(self, submission: ManualMetadataSubmission) -> None:
        payload = await self._read_limited_object(
            bucket=submission.bucket,
            object_key=submission.object_key,
        )
        if len(payload) != submission.csv_size_bytes:
            raise ConflictError(
                "The manual metadata CSV receipt size does not reconcile.",
                details={"code": "CSV_RECEIPT_SIZE_MISMATCH"},
            )
        if hashlib.sha256(payload).hexdigest() != submission.csv_sha256:
            raise ConflictError(
                "The manual metadata CSV receipt hash does not reconcile.",
                details={"code": "CSV_RECEIPT_HASH_MISMATCH"},
            )
        try:
            rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8"))))
        except (UnicodeDecodeError, csv.Error) as error:
            raise ConflictError(
                "The manual metadata CSV receipt is invalid.",
                details={"code": "CSV_RECEIPT_INVALID"},
            ) from error
        if len(rows) != submission.row_count or not rows:
            raise ConflictError(
                "The manual metadata CSV receipt row count does not reconcile.",
                details={"code": "CSV_RECEIPT_ROW_COUNT_MISMATCH"},
            )
        table_rows = [row for row in rows if row.get("record_kind") == "TABLE"]
        column_rows = [row for row in rows if row.get("record_kind") == "COLUMN"]
        if len(table_rows) != 1 or len(column_rows) != len(submission.columns):
            raise ConflictError(
                "The manual metadata CSV receipt shape is invalid.",
                details={"code": "CSV_RECEIPT_SHAPE_MISMATCH"},
            )
        table = table_rows[0]
        if (
            table.get("external_urn") != submission.external_urn
            or table.get("source_version") != submission.source_version
            or table.get("description") != submission.description
            or table.get("domain", "") != (submission.domain or "")
            or tuple(self._csv_refs(table.get("tags"))) != submission.tags
            or tuple(self._csv_refs(table.get("terms"))) != submission.terms
        ):
            raise ConflictError(
                "The manual metadata CSV receipt does not match its immutable submission.",
                details={"code": "CSV_RECEIPT_PAYLOAD_MISMATCH"},
            )
        expected_columns = {
            column.field_path: (column.description, column.tags, column.terms)
            for column in submission.columns
        }
        actual_columns = {
            str(row.get("column_name", "")): (
                str(row.get("description", "")),
                tuple(self._csv_refs(row.get("tags"))),
                tuple(self._csv_refs(row.get("terms"))),
            )
            for row in column_rows
        }
        if actual_columns != expected_columns:
            raise ConflictError(
                "The manual metadata CSV column rows do not match their immutable submission.",
                details={"code": "CSV_RECEIPT_COLUMNS_MISMATCH"},
            )

    async def _read_limited_object(self, *, bucket: str, object_key: str) -> bytes:
        chunks: list[bytes] = []
        total = 0
        async for chunk in self._object_store.iter_object_chunks(
            bucket=bucket, object_key=object_key
        ):
            if not isinstance(chunk, bytes):
                raise ExternalDependencyError(
                    "Object storage returned an invalid manual metadata receipt.",
                    dependency="object_store",
                    retryable=False,
                    provider_code="INVALID_RESPONSE",
                )
            total += len(chunk)
            if total > MAXIMUM_MANUAL_RECEIPT_BYTES:
                raise ConflictError(
                    "The manual metadata CSV receipt exceeds the worker safety bound.",
                    details={"code": "CSV_RECEIPT_TOO_LARGE"},
                )
            chunks.append(chunk)
        if not chunks:
            raise ConflictError(
                "The manual metadata CSV receipt is missing.",
                details={"code": "CSV_RECEIPT_MISSING"},
            )
        return b"".join(chunks)

    async def _apply_submission(self, submission: ManualMetadataSubmission) -> None:
        await self._apply_aspect(
            submission=submission,
            aspect_name="datasetProperties",
            mutate=lambda document: self._set_description(document, submission.description),
        )
        await self._apply_aspect(
            submission=submission,
            aspect_name="domains",
            mutate=lambda document: self._set_controlled_refs(
                document,
                field="domains",
                nested="urn",
                refs=(() if submission.domain is None else (submission.domain,)),
            ),
        )
        await self._apply_aspect(
            submission=submission,
            aspect_name="globalTags",
            mutate=lambda document: self._set_controlled_refs(
                document,
                field="tags",
                nested="tag",
                refs=submission.tags,
            ),
        )
        await self._apply_aspect(
            submission=submission,
            aspect_name="glossaryTerms",
            mutate=lambda document: self._set_controlled_refs(
                document,
                field="terms",
                nested="urn",
                refs=submission.terms,
            ),
        )
        await self._apply_aspect(
            submission=submission,
            aspect_name="schemaMetadata",
            mutate=lambda document: self._set_schema_metadata(document, submission),
        )

    async def _apply_aspect(
        self,
        *,
        submission: ManualMetadataSubmission,
        aspect_name: str,
        mutate: Callable[[dict[str, Any]], None],
    ) -> None:
        current = await self._datahub.read_aspect(
            external_urn=submission.external_urn,
            aspect_name=aspect_name,
        )
        document = self._mutable_document(current.document)
        mutate(document)
        expected_hash = canonical_json_hash(document)
        if current.content_hash == expected_hash:
            return
        await self._datahub.apply_change(
            external_urn=submission.external_urn,
            aspect_name=aspect_name,
            document=document,
            idempotency_key=(
                f"manual-metadata:{submission.submission_id}:{aspect_name}:{expected_hash}"[:200]
            ),
        )
        observed = await self._datahub.read_aspect(
            external_urn=submission.external_urn,
            aspect_name=aspect_name,
        )
        if observed.content_hash != expected_hash:
            raise ConflictError(
                "DataHub did not reconcile to the manual metadata receipt.",
                details={"code": "AFTER_HASH_MISMATCH", "aspect": aspect_name},
            )

    @staticmethod
    def _set_description(document: dict[str, Any], description: str) -> None:
        if description:
            document["description"] = description
        else:
            document.pop("description", None)

    @staticmethod
    def _set_controlled_refs(
        document: dict[str, Any], *, field: str, nested: str, refs: tuple[str, ...]
    ) -> None:
        document[field] = [{nested: ref} for ref in refs]

    @staticmethod
    def _set_schema_metadata(
        document: dict[str, Any], submission: ManualMetadataSubmission
    ) -> None:
        fields = document.get("fields")
        if not isinstance(fields, list):
            raise ExternalDependencyError(
                "DataHub returned an invalid schemaMetadata fields document.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )
        by_path = {
            field.get("fieldPath"): field
            for field in fields
            if isinstance(field, dict) and isinstance(field.get("fieldPath"), str)
        }
        if len(by_path) != len(fields) or set(by_path) != {
            column.field_path for column in submission.columns
        }:
            raise ConflictError(
                "The DataHub schema changed after the manual submission was staged.",
                details={"code": "SCHEMA_FIELD_DRIFT"},
            )
        for column in submission.columns:
            field = by_path[column.field_path]
            if column.description:
                field["description"] = column.description
            else:
                field.pop("description", None)
            field["globalTags"] = {"tags": [{"tag": ref} for ref in column.tags]}
            field["glossaryTerms"] = {"terms": [{"urn": ref} for ref in column.terms]}

    @staticmethod
    def _mutable_document(value: Mapping[str, Any]) -> dict[str, Any]:
        def copy(item: Any) -> Any:
            if isinstance(item, Mapping):
                if any(not isinstance(key, str) for key in item):
                    raise ExternalDependencyError(
                        "DataHub returned an invalid metadata document.",
                        dependency="datahub",
                        retryable=False,
                        provider_code="INVALID_RESPONSE",
                    )
                return {key: copy(nested) for key, nested in item.items()}
            if isinstance(item, tuple | list):
                return [copy(nested) for nested in item]
            if item is None or isinstance(item, str | bool | int | float):
                return item
            raise ExternalDependencyError(
                "DataHub returned an invalid metadata document.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )

        copied = copy(value)
        if not isinstance(copied, dict):
            raise ExternalDependencyError(
                "DataHub returned an invalid metadata document.",
                dependency="datahub",
                retryable=False,
                provider_code="INVALID_RESPONSE",
            )
        return copied

    @staticmethod
    def _csv_refs(value: str | None) -> tuple[str, ...]:
        return tuple(item for item in (value or "").split(",") if item)

    @staticmethod
    def _retryable(error: DomainError) -> bool:
        return isinstance(error, ExternalDependencyError) and bool(error.details.get("retryable"))

    @staticmethod
    def _error_code(error: DomainError) -> str:
        return str(error.details.get("code") or error.details.get("provider_code") or error.code)[
            :100
        ]

    @staticmethod
    def _now() -> datetime:
        from datariver.domain.common import utc_now

        return utc_now()
