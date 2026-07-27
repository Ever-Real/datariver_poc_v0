from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from typing import IO, Protocol
from uuid import UUID

import orjson

from datariver.application.catalog_metadata_upload_parser import (
    CatalogMetadataAspect,
    CatalogMetadataCandidateDraft,
    CatalogMetadataCandidateKind,
    CatalogMetadataOperation,
    CatalogMetadataParseSummary,
    CatalogMetadataRecordKind,
    CatalogMetadataRowEvidence,
    parse_catalog_metadata_rows_csv,
)
from datariver.application.dto import ObjectMetadata
from datariver.application.errors import ExternalDependencyError
from datariver.application.typed_upload_parser import (
    DatasetDescriptionCandidateDraft,
    DatasetDescriptionParseSummary,
    TypedUploadParseError,
    TypedUploadParseFailureCode,
    parse_dataset_description_csv,
)
from datariver.application.typed_upload_profiles import typed_profile_definition
from datariver.application.typed_xlsx_upload_parser import (
    parse_catalog_metadata_rows_xlsx,
    parse_dataset_description_xlsx,
)
from datariver.domain.common import DomainError
from datariver.domain.registration import UploadContentProfile
from datariver.domain.registration_worker import (
    RegistrationWorkerCallIdentity,
    RegistrationWorkerCallReplay,
)

BulkCandidateDraft = DatasetDescriptionCandidateDraft | CatalogMetadataCandidateDraft
BulkParseSummary = DatasetDescriptionParseSummary | CatalogMetadataParseSummary
_DATASET_DESCRIPTION_SPOOL_CONTRACT = "dataset-description-candidate-spool-v2"
_CATALOG_METADATA_SPOOL_CONTRACT = "catalog-metadata-candidate-spool-v3"
_MAXIMUM_CANDIDATE_SPOOL_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class BulkPreparationClaim:
    workspace_id: UUID
    preparation_id: UUID
    upload_id: UUID
    requested_by: UUID
    content_profile: UploadContentProfile
    source_manifest_version: int
    source_sha256: str
    configuration_hash: str
    source_bucket: str
    source_object_key: str
    source_size_bytes: int
    source_content_type: str
    scanner_version: str
    lease_token: UUID
    attempt: int
    run_call: RegistrationWorkerCallIdentity | None = None


@dataclass(frozen=True, slots=True)
class BulkPreparationRunResult:
    processed: bool
    preparation_id: UUID | None = None
    state: str | None = None
    item_count: int | None = None


class BulkPreparationObjectStore(Protocol):
    async def head_object(self, *, bucket: str, object_key: str) -> ObjectMetadata: ...

    def iter_object_chunks(
        self, *, bucket: str, object_key: str, chunk_size: int = 1024 * 1024
    ) -> AsyncIterator[bytes]: ...


class BulkPreparationExecutionStore(Protocol):
    async def claim_next(
        self,
        *,
        workspace_id: UUID,
        worker_subject_id: UUID,
        lease_seconds: int,
        maximum_attempts: int,
        run_call: RegistrationWorkerCallIdentity | None = None,
    ) -> BulkPreparationClaim | RegistrationWorkerCallReplay | None: ...

    async def publish(
        self,
        *,
        claim: BulkPreparationClaim,
        object_metadata: ObjectMetadata,
        summary: BulkParseSummary,
        candidates: Callable[[], Iterator[BulkCandidateDraft]],
    ) -> bool: ...

    async def mark_failed(
        self,
        *,
        claim: BulkPreparationClaim,
        error_code: str,
        retryable: bool,
        maximum_attempts: int,
    ) -> bool: ...


class BulkRegistrationPreparationService:
    """Execute one immutable BULK preparation behind a lease-token fence.

    Airflow calls the API only. This service owns object-store access and emits no DataHub
    operation. Parsed candidates remain in an attempt-local spooled file until the store performs
    one atomic receipt/candidate publication transaction under the current lease token.
    """

    def __init__(
        self,
        *,
        store: BulkPreparationExecutionStore,
        object_store: BulkPreparationObjectStore,
        lease_seconds: int,
        maximum_attempts: int,
    ) -> None:
        if not 30 <= lease_seconds <= 3600:
            raise ValueError("The BULK preparation lease must be between 30 and 3600 seconds.")
        if not 1 <= maximum_attempts <= 20:
            raise ValueError("The BULK preparation attempt limit must be between 1 and 20.")
        self._store = store
        self._object_store = object_store
        self._lease_seconds = lease_seconds
        self._maximum_attempts = maximum_attempts

    async def run_once(
        self,
        *,
        workspace_id: UUID,
        worker_subject_id: UUID,
        run_call: RegistrationWorkerCallIdentity | None = None,
    ) -> BulkPreparationRunResult:
        if run_call is None:
            claim = await self._store.claim_next(
                workspace_id=workspace_id,
                worker_subject_id=worker_subject_id,
                lease_seconds=self._lease_seconds,
                maximum_attempts=self._maximum_attempts,
            )
        else:
            claim = await self._store.claim_next(
                workspace_id=workspace_id,
                worker_subject_id=worker_subject_id,
                lease_seconds=self._lease_seconds,
                maximum_attempts=self._maximum_attempts,
                run_call=run_call,
            )
        if claim is None:
            return BulkPreparationRunResult(processed=False)
        if isinstance(claim, RegistrationWorkerCallReplay):
            return BulkPreparationRunResult(
                processed=bool(claim.result["processed"]),
                preparation_id=(
                    UUID(str(claim.result["preparation_id"]))
                    if claim.result.get("preparation_id") is not None
                    else None
                ),
                state=(
                    str(claim.result["state"]) if claim.result.get("state") is not None else None
                ),
                item_count=(
                    int(claim.result["item_count"])
                    if claim.result.get("item_count") is not None
                    else None
                ),
            )
        try:
            metadata = await self._object_store.head_object(
                bucket=claim.source_bucket,
                object_key=claim.source_object_key,
            )
            if (
                metadata.size_bytes != claim.source_size_bytes
                or metadata.content_type != claim.source_content_type
            ):
                raise TypedUploadParseError(
                    failure_code=TypedUploadParseFailureCode.SOURCE_HASH_MISMATCH,
                    message="The accepted BULK object metadata no longer matches its manifest.",
                )
            with AttemptCandidateSpool(maximum_bytes=_MAXIMUM_CANDIDATE_SPOOL_BYTES) as spool:
                summary = await self._parse(claim=claim, spool=spool)
                spool.seal()
                published = await self._store.publish(
                    claim=claim,
                    object_metadata=metadata,
                    summary=summary,
                    candidates=spool.iter_candidates,
                )
            return BulkPreparationRunResult(
                processed=True,
                preparation_id=claim.preparation_id,
                state="READY" if published else "SUPERSEDED",
                item_count=summary.item_count if published else None,
            )
        except DomainError as error:
            retryable = isinstance(error, ExternalDependencyError) and bool(
                error.details.get("retryable", False)
            )
            state = "QUEUED" if retryable and claim.attempt < self._maximum_attempts else "FAILED"
            current = await self._store.mark_failed(
                claim=claim,
                error_code=_error_code(error),
                retryable=retryable,
                maximum_attempts=self._maximum_attempts,
            )
            return BulkPreparationRunResult(
                processed=True,
                preparation_id=claim.preparation_id,
                state=state if current else "SUPERSEDED",
            )
        except Exception as error:
            current = await self._store.mark_failed(
                claim=claim,
                error_code=f"UNEXPECTED_{type(error).__name__}"[:100],
                retryable=True,
                maximum_attempts=self._maximum_attempts,
            )
            state = "QUEUED" if claim.attempt < self._maximum_attempts else "FAILED"
            return BulkPreparationRunResult(
                processed=True,
                preparation_id=claim.preparation_id,
                state=state if current else "SUPERSEDED",
            )

    async def _parse(
        self,
        *,
        claim: BulkPreparationClaim,
        spool: AttemptCandidateSpool,
    ) -> BulkParseSummary:
        chunks = self._object_store.iter_object_chunks(
            bucket=claim.source_bucket,
            object_key=claim.source_object_key,
        )
        definition = typed_profile_definition(claim.content_profile)
        if definition.configuration_hash != claim.configuration_hash:
            raise TypedUploadParseError(
                failure_code=TypedUploadParseFailureCode.SOURCE_HASH_MISMATCH,
                message="The BULK preparation parser configuration no longer matches its job.",
            )

        if claim.content_profile is UploadContentProfile.DATASET_DESCRIPTION_CSV_V1:
            return await parse_dataset_description_csv(
                workspace_id=claim.workspace_id,
                chunks=chunks,
                expected_source_sha256=claim.source_sha256,
                consume_candidate=spool.append,
                definition=definition,
            )
        if claim.content_profile is UploadContentProfile.DATASET_DESCRIPTION_XLSX_V1:
            return await parse_dataset_description_xlsx(
                workspace_id=claim.workspace_id,
                chunks=chunks,
                expected_source_sha256=claim.source_sha256,
                consume_candidate=spool.append,
                definition=definition,
            )
        if claim.content_profile is UploadContentProfile.CATALOG_METADATA_ROWS_CSV_V1:
            return await parse_catalog_metadata_rows_csv(
                workspace_id=claim.workspace_id,
                chunks=chunks,
                expected_source_sha256=claim.source_sha256,
                consume_candidate=spool.append,
                definition=definition,
            )
        if claim.content_profile is UploadContentProfile.CATALOG_METADATA_ROWS_XLSX_V1:
            return await parse_catalog_metadata_rows_xlsx(
                workspace_id=claim.workspace_id,
                chunks=chunks,
                expected_source_sha256=claim.source_sha256,
                consume_candidate=spool.append,
                definition=definition,
            )
        raise ValueError("The claimed upload has no executable BULK preparation profile.")


class AttemptCandidateSpool:
    """Bounded attempt-local storage; it never exposes a filesystem path."""

    def __init__(self, *, maximum_bytes: int) -> None:
        if not 1 <= maximum_bytes <= 1024 * 1024 * 1024:
            raise ValueError("The candidate spool byte limit is outside the safe range.")
        self._maximum_bytes = maximum_bytes
        self._bytes_written = 0
        self._count = 0
        self._sealed = False
        self._file: IO[bytes] | None = None

    def __enter__(self) -> AttemptCandidateSpool:
        self._file = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
        return self

    def __exit__(self, *_args: object) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    async def append(self, candidate: BulkCandidateDraft) -> None:
        if self._file is None or self._sealed:
            raise RuntimeError("The candidate spool is not writable.")
        record = (
            orjson.dumps(
                _candidate_spool_record(candidate),
                option=orjson.OPT_SORT_KEYS,
            )
            + b"\n"
        )
        updated_size = self._bytes_written + len(record)
        if updated_size > self._maximum_bytes:
            raise TypedUploadParseError(
                failure_code=TypedUploadParseFailureCode.EVIDENCE_TOO_LARGE,
                message="The typed candidate staging evidence exceeds its bounded size.",
            )
        self._bytes_written = updated_size
        self._file.write(record)
        self._count += 1

    def seal(self) -> None:
        if self._file is None or self._sealed or self._count < 1:
            raise RuntimeError("The candidate spool cannot be sealed.")
        self._file.flush()
        self._sealed = True

    def iter_candidates(self) -> Iterator[BulkCandidateDraft]:
        if self._file is None or not self._sealed:
            raise RuntimeError("The candidate spool is not readable.")
        self._file.seek(0)
        for line in self._file:
            yield _candidate_from_spool_record(line)


def _candidate_spool_record(candidate: BulkCandidateDraft) -> dict[str, object]:
    common: dict[str, object] = {
        "candidate_hash": candidate.candidate_hash,
        "candidate_kind": candidate.candidate_kind,
        "database_name": candidate.database_name,
        "evidence_version": candidate.evidence_version,
        "ordinal": candidate.ordinal,
        "platform": candidate.platform,
        "schema_name": candidate.schema_name,
        "submitted_identity_hash": candidate.submitted_identity_hash,
        "table_name": candidate.table_name,
        "target_asset_id": str(candidate.target_asset_id),
        "workspace_id": str(candidate.workspace_id),
    }
    if isinstance(candidate, DatasetDescriptionCandidateDraft):
        common.update(
            {
                "proposed_description": candidate.proposed_description,
                "spool_contract": _DATASET_DESCRIPTION_SPOOL_CONTRACT,
            }
        )
        return common
    common.update(
        {
            "aspect_name": candidate.aspect_name.value,
            "record_kind": candidate.record_kind.value,
            "rows": [_catalog_metadata_row_record(row) for row in candidate.rows],
            "spool_contract": _CATALOG_METADATA_SPOOL_CONTRACT,
        }
    )
    return common


def _catalog_metadata_row_record(row: CatalogMetadataRowEvidence) -> dict[str, object]:
    return {
        "aspect_name": row.aspect_name.value,
        "controlled_ref": str(row.controlled_ref) if row.controlled_ref is not None else None,
        "database_name": row.database_name,
        "evidence_version": row.evidence_version,
        "field_path": row.field_path,
        "operation": row.operation.value,
        "ordinal": row.ordinal,
        "platform": row.platform,
        "record_kind": row.record_kind.value,
        "row_hash": row.row_hash,
        "schema_name": row.schema_name,
        "semantic_key": row.semantic_key,
        "table_name": row.table_name,
        "target_asset_id": str(row.target_asset_id),
        "value_text": row.value_text,
        "workspace_id": str(row.workspace_id),
    }


def _candidate_from_spool_record(record: bytes) -> BulkCandidateDraft:
    value = _spool_mapping(orjson.loads(record))
    contract = _spool_string(value, "spool_contract")
    if contract == _DATASET_DESCRIPTION_SPOOL_CONTRACT:
        return DatasetDescriptionCandidateDraft(
            workspace_id=UUID(_spool_string(value, "workspace_id")),
            ordinal=_spool_positive_integer(value, "ordinal"),
            target_asset_id=UUID(_spool_string(value, "target_asset_id")),
            platform=_spool_string(value, "platform"),
            database_name=_spool_string(value, "database_name"),
            schema_name=_spool_string(value, "schema_name"),
            table_name=_spool_string(value, "table_name"),
            proposed_description=_spool_string(value, "proposed_description"),
            submitted_identity_hash=_spool_string(value, "submitted_identity_hash"),
            candidate_hash=_spool_string(value, "candidate_hash"),
            candidate_kind=_spool_string(value, "candidate_kind"),
            evidence_version=_spool_string(value, "evidence_version"),
        )
    if contract != _CATALOG_METADATA_SPOOL_CONTRACT:
        raise RuntimeError("The candidate spool record has an unknown contract.")
    rows_value = value.get("rows")
    if not isinstance(rows_value, list) or not rows_value:
        raise RuntimeError("The catalog-metadata candidate spool rows are invalid.")
    rows = tuple(_catalog_metadata_row_from_record(row) for row in rows_value)
    return CatalogMetadataCandidateDraft(
        workspace_id=UUID(_spool_string(value, "workspace_id")),
        ordinal=_spool_positive_integer(value, "ordinal"),
        target_asset_id=UUID(_spool_string(value, "target_asset_id")),
        platform=_spool_string(value, "platform"),
        database_name=_spool_string(value, "database_name"),
        schema_name=_spool_string(value, "schema_name"),
        table_name=_spool_string(value, "table_name"),
        record_kind=CatalogMetadataRecordKind(_spool_string(value, "record_kind")),
        candidate_kind=CatalogMetadataCandidateKind(_spool_string(value, "candidate_kind")),
        aspect_name=CatalogMetadataAspect(_spool_string(value, "aspect_name")),
        rows=rows,
        submitted_identity_hash=_spool_string(value, "submitted_identity_hash"),
        candidate_hash=_spool_string(value, "candidate_hash"),
        evidence_version=_spool_string(value, "evidence_version"),
    )


def _catalog_metadata_row_from_record(value: object) -> CatalogMetadataRowEvidence:
    row = _spool_mapping(value)
    controlled_ref_value = row.get("controlled_ref")
    field_path_value = row.get("field_path")
    value_text_value = row.get("value_text")
    return CatalogMetadataRowEvidence(
        workspace_id=UUID(_spool_string(row, "workspace_id")),
        ordinal=_spool_positive_integer(row, "ordinal"),
        target_asset_id=UUID(_spool_string(row, "target_asset_id")),
        platform=_spool_string(row, "platform"),
        database_name=_spool_string(row, "database_name"),
        schema_name=_spool_string(row, "schema_name"),
        table_name=_spool_string(row, "table_name"),
        record_kind=CatalogMetadataRecordKind(_spool_string(row, "record_kind")),
        aspect_name=CatalogMetadataAspect(_spool_string(row, "aspect_name")),
        operation=CatalogMetadataOperation(_spool_string(row, "operation")),
        field_path=_spool_optional_string(field_path_value),
        value_text=_spool_optional_string(value_text_value),
        controlled_ref=_spool_optional_uuid(controlled_ref_value),
        semantic_key=_spool_string(row, "semantic_key"),
        row_hash=_spool_string(row, "row_hash"),
        evidence_version=_spool_string(row, "evidence_version"),
    )


def _spool_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise RuntimeError("The candidate spool record is invalid.")
    return value


def _spool_string(value: dict[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise RuntimeError("The candidate spool record has an invalid string field.")
    return item


def _spool_optional_string(value: object) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise RuntimeError("The candidate spool record has an invalid optional string field.")


def _spool_optional_uuid(value: object) -> UUID | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError("The candidate spool record has an invalid optional UUID field.")
    return UUID(value)


def _spool_positive_integer(value: dict[str, object], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item < 1:
        raise RuntimeError("The candidate spool record has an invalid ordinal.")
    return item


def _error_code(error: DomainError) -> str:
    return str(error.details.get("failure_code") or error.details.get("code") or error.code)[:100]
