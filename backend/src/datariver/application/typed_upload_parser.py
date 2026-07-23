from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import AsyncIterable, Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from datariver.application.typed_upload_profiles import (
    DATASET_DESCRIPTION_CSV_V1,
    TypedUploadProfileDefinition,
)
from datariver.domain.common import ValidationError, canonical_json_hash
from datariver.domain.registration import UploadContentProfile

DATASET_DESCRIPTION_CANDIDATE_KIND = "DATASET_DESCRIPTION_UPDATE"
DATASET_DESCRIPTION_CANDIDATE_EVIDENCE_VERSION = "DATASET_DESCRIPTION_CANDIDATE_V2"
_CANDIDATE_IDENTITY_HASH_CONTRACT = "dataset-description-submitted-identity-v1"
_CANDIDATE_HASH_CONTRACT = "dataset-description-candidate-v2"
_CANDIDATE_ROOT_CONTRACT = b"datariver-dataset-description-root-v2\0"
_UTF8_BOM = b"\xef\xbb\xbf"


class TypedUploadParseFailureCode(StrEnum):
    EMPTY_FILE = "EMPTY_FILE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    ROW_TOO_LARGE = "ROW_TOO_LARGE"
    INVALID_UTF8 = "INVALID_UTF8"
    INVALID_CSV = "INVALID_CSV"
    INVALID_HEADER = "INVALID_HEADER"
    INVALID_COLUMN_COUNT = "INVALID_COLUMN_COUNT"
    INVALID_ASSET_ID = "INVALID_ASSET_ID"
    INVALID_IDENTITY_FIELD = "INVALID_IDENTITY_FIELD"
    INVALID_DESCRIPTION = "INVALID_DESCRIPTION"
    DUPLICATE_ASSET = "DUPLICATE_ASSET"
    TOO_MANY_ROWS = "TOO_MANY_ROWS"
    EMPTY_DATASET = "EMPTY_DATASET"
    SOURCE_HASH_MISMATCH = "SOURCE_HASH_MISMATCH"
    EVIDENCE_TOO_LARGE = "EVIDENCE_TOO_LARGE"
    INVALID_XLSX_PACKAGE = "INVALID_XLSX_PACKAGE"


class _CsvScanState(StrEnum):
    START_FIELD = "START_FIELD"
    UNQUOTED = "UNQUOTED"
    QUOTED = "QUOTED"
    AFTER_QUOTE = "AFTER_QUOTE"
    AFTER_CR = "AFTER_CR"


class TypedUploadParseError(ValidationError):
    code = "typed_upload_parse_failed"

    def __init__(
        self,
        failure_code: TypedUploadParseFailureCode,
        message: str,
        *,
        ordinal: int | None = None,
    ) -> None:
        details: dict[str, object] = {"failure_code": failure_code.value}
        if ordinal is not None:
            details["ordinal"] = ordinal
        super().__init__(message, details=details)
        self.failure_code = failure_code
        self.ordinal = ordinal


@dataclass(frozen=True, slots=True)
class DatasetDescriptionCandidateDraft:
    workspace_id: UUID
    ordinal: int
    target_asset_id: UUID
    platform: str
    database_name: str
    schema_name: str
    table_name: str
    proposed_description: str
    submitted_identity_hash: str
    candidate_hash: str
    candidate_kind: str = DATASET_DESCRIPTION_CANDIDATE_KIND
    evidence_version: str = DATASET_DESCRIPTION_CANDIDATE_EVIDENCE_VERSION


@dataclass(frozen=True, slots=True)
class DatasetDescriptionParseSummary:
    source_sha256: str
    total_bytes: int
    item_count: int
    rejected_count: int
    candidate_root_hash: str
    parser_version: str
    schema_version: str
    configuration_hash: str


CandidateConsumer = Callable[[DatasetDescriptionCandidateDraft], Awaitable[None]]


async def parse_dataset_description_csv(
    *,
    workspace_id: UUID,
    chunks: AsyncIterable[bytes],
    expected_source_sha256: str,
    consume_candidate: CandidateConsumer,
    definition: TypedUploadProfileDefinition = DATASET_DESCRIPTION_CSV_V1,
) -> DatasetDescriptionParseSummary:
    """Parse one immutable typed upload with bounded memory.

    The consumer may be called before the final source hash is known. It must therefore write only
    to attempt-local staging that is discarded unless the caller atomically publishes this summary.
    It must never append directly to canonical receipt or candidate tables.
    """

    _validate_expected_hash(expected_source_sha256)
    if definition.content_profile is not UploadContentProfile.DATASET_DESCRIPTION_CSV_V1:
        raise ValueError("The dataset-description parser requires its exact typed content profile.")
    source_hasher = hashlib.sha256()
    total_bytes = 0

    async def observed_chunks() -> AsyncIterable[bytes]:
        nonlocal total_bytes
        async for chunk in chunks:
            if not isinstance(chunk, bytes):
                raise TypeError("Typed upload chunks must be bytes.")
            if not chunk:
                continue
            total_bytes += len(chunk)
            if total_bytes > definition.maximum_file_bytes:
                raise TypedUploadParseError(
                    TypedUploadParseFailureCode.FILE_TOO_LARGE,
                    "The typed upload exceeds its bounded file-size limit.",
                )
            source_hasher.update(chunk)
            yield chunk

    header_seen = False
    item_count = 0
    seen_assets: set[UUID] = set()
    candidate_root = dataset_description_candidate_root_seed()

    async for record_number, record in _iter_logical_records(
        observed_chunks(),
        maximum_row_bytes=definition.maximum_row_bytes,
    ):
        fields = _parse_record(record, record_number=record_number)
        if not header_seen:
            header_seen = True
            if tuple(fields) != definition.headers:
                raise TypedUploadParseError(
                    TypedUploadParseFailureCode.INVALID_HEADER,
                    "The typed upload header does not match the registered schema.",
                )
            continue

        item_count += 1
        if item_count > definition.maximum_rows:
            raise TypedUploadParseError(
                TypedUploadParseFailureCode.TOO_MANY_ROWS,
                "The typed upload exceeds its bounded row limit.",
                ordinal=item_count,
            )
        candidate = dataset_description_candidate_from_values(
            workspace_id=workspace_id,
            ordinal=item_count,
            values=fields,
            definition=definition,
        )
        if candidate.target_asset_id in seen_assets:
            raise TypedUploadParseError(
                TypedUploadParseFailureCode.DUPLICATE_ASSET,
                "The typed upload contains more than one row for the same asset.",
                ordinal=item_count,
            )
        seen_assets.add(candidate.target_asset_id)
        candidate_root = advance_dataset_description_candidate_root(
            current=candidate_root,
            ordinal=item_count,
            candidate_hash=candidate.candidate_hash,
        )
        await consume_candidate(candidate)

    if not header_seen:
        raise TypedUploadParseError(
            TypedUploadParseFailureCode.EMPTY_FILE,
            "The typed upload is empty.",
        )
    if item_count == 0:
        raise TypedUploadParseError(
            TypedUploadParseFailureCode.EMPTY_DATASET,
            "The typed upload contains no candidate rows.",
        )
    source_sha256 = source_hasher.hexdigest()
    if source_sha256 != expected_source_sha256:
        raise TypedUploadParseError(
            TypedUploadParseFailureCode.SOURCE_HASH_MISMATCH,
            "The typed upload bytes do not match the accepted source hash.",
        )
    return DatasetDescriptionParseSummary(
        source_sha256=source_sha256,
        total_bytes=total_bytes,
        item_count=item_count,
        rejected_count=0,
        candidate_root_hash=candidate_root.hex(),
        parser_version=definition.parser_version,
        schema_version=definition.schema_version,
        configuration_hash=definition.configuration_hash,
    )


async def _iter_logical_records(
    chunks: AsyncIterable[bytes],
    *,
    maximum_row_bytes: int,
) -> AsyncIterable[tuple[int, bytes]]:
    buffer = bytearray()
    state = _CsvScanState.START_FIELD
    record_number = 0
    async for chunk in chunks:
        for value in chunk:
            buffer.append(value)
            if len(buffer) > maximum_row_bytes:
                raise TypedUploadParseError(
                    TypedUploadParseFailureCode.ROW_TOO_LARGE,
                    "A typed upload row exceeds its bounded byte limit.",
                    ordinal=max(record_number, 1),
                )

            if state is _CsvScanState.AFTER_CR:
                if value != ord("\n"):
                    raise TypedUploadParseError(
                        TypedUploadParseFailureCode.INVALID_CSV,
                        "A carriage return outside a quoted field must be followed by a line feed.",
                        ordinal=max(record_number, 1),
                    )
                state = _CsvScanState.START_FIELD
                record_number += 1
                yield record_number, bytes(buffer)
                buffer.clear()
                continue

            if state is _CsvScanState.QUOTED:
                if value == ord('"'):
                    state = _CsvScanState.AFTER_QUOTE
                continue

            if state is _CsvScanState.AFTER_QUOTE:
                if value == ord('"'):
                    state = _CsvScanState.QUOTED
                    continue
                if value == ord(","):
                    state = _CsvScanState.START_FIELD
                    continue
                if value == ord("\r"):
                    state = _CsvScanState.AFTER_CR
                    continue
                if value != ord("\n"):
                    raise TypedUploadParseError(
                        TypedUploadParseFailureCode.INVALID_CSV,
                        "A quoted field has invalid trailing data.",
                        ordinal=max(record_number, 1),
                    )
                state = _CsvScanState.START_FIELD
                record_number += 1
                yield record_number, bytes(buffer)
                buffer.clear()
                continue

            if value == ord('"'):
                if state is not _CsvScanState.START_FIELD:
                    raise TypedUploadParseError(
                        TypedUploadParseFailureCode.INVALID_CSV,
                        "A quote may appear only at the start of a quoted field.",
                        ordinal=max(record_number, 1),
                    )
                state = _CsvScanState.QUOTED
            elif value == ord(","):
                state = _CsvScanState.START_FIELD
            elif value == ord("\r"):
                state = _CsvScanState.AFTER_CR
            elif value == ord("\n"):
                state = _CsvScanState.START_FIELD
                record_number += 1
                yield record_number, bytes(buffer)
                buffer.clear()
            else:
                state = _CsvScanState.UNQUOTED

    if state is _CsvScanState.QUOTED:
        raise TypedUploadParseError(
            TypedUploadParseFailureCode.INVALID_CSV,
            "The typed upload contains an unterminated quoted field.",
            ordinal=max(record_number, 1),
        )
    if state is _CsvScanState.AFTER_CR:
        raise TypedUploadParseError(
            TypedUploadParseFailureCode.INVALID_CSV,
            "The typed upload contains a bare carriage return.",
            ordinal=max(record_number, 1),
        )
    if buffer:
        record_number += 1
        yield record_number, bytes(buffer)


def _parse_record(record: bytes, *, record_number: int) -> list[str]:
    if record.endswith(b"\n"):
        record = record[:-1]
    if record.endswith(b"\r"):
        record = record[:-1]
    if record_number == 1 and record.startswith(_UTF8_BOM):
        record = record[len(_UTF8_BOM) :]
    try:
        text = record.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise TypedUploadParseError(
            TypedUploadParseFailureCode.INVALID_UTF8,
            "The typed upload is not valid UTF-8.",
            ordinal=max(record_number - 1, 1),
        ) from error
    if "\x00" in text or "\ufeff" in text:
        raise TypedUploadParseError(
            TypedUploadParseFailureCode.INVALID_CSV,
            "The typed upload contains a forbidden control marker.",
            ordinal=max(record_number - 1, 1),
        )
    try:
        rows = list(
            csv.reader(
                io.StringIO(text, newline=""),
                delimiter=",",
                quotechar='"',
                doublequote=True,
                strict=True,
            )
        )
    except csv.Error as error:
        raise TypedUploadParseError(
            TypedUploadParseFailureCode.INVALID_CSV,
            "The typed upload contains invalid CSV syntax.",
            ordinal=max(record_number - 1, 1),
        ) from error
    if len(rows) != 1:
        raise TypedUploadParseError(
            TypedUploadParseFailureCode.INVALID_CSV,
            "The typed upload record boundary is invalid.",
            ordinal=max(record_number - 1, 1),
        )
    return rows[0]


def dataset_description_candidate_from_values(
    *,
    workspace_id: UUID,
    ordinal: int,
    values: list[str],
    definition: TypedUploadProfileDefinition,
) -> DatasetDescriptionCandidateDraft:
    """Build the shared typed candidate from one server-parsed tabular row."""

    if len(values) != len(definition.headers):
        raise TypedUploadParseError(
            TypedUploadParseFailureCode.INVALID_COLUMN_COUNT,
            "The typed upload row has an invalid column count.",
            ordinal=ordinal,
        )
    asset_id_text, platform, database_name, schema_name, table_name, description = values
    try:
        target_asset_id = UUID(asset_id_text)
    except ValueError as error:
        raise TypedUploadParseError(
            TypedUploadParseFailureCode.INVALID_ASSET_ID,
            "The typed upload asset ID is invalid.",
            ordinal=ordinal,
        ) from error
    if asset_id_text != str(target_asset_id):
        raise TypedUploadParseError(
            TypedUploadParseFailureCode.INVALID_ASSET_ID,
            "The typed upload asset ID must use canonical lowercase UUID form.",
            ordinal=ordinal,
        )
    identity_values = (
        (platform, definition.maximum_platform_characters),
        (database_name, definition.maximum_database_name_characters),
        (schema_name, definition.maximum_schema_name_characters),
        (table_name, definition.maximum_table_name_characters),
    )
    if any(
        not value
        or value != value.strip()
        or len(value) > maximum_characters
        or _contains_forbidden_identity_control(value)
        for value, maximum_characters in identity_values
    ):
        raise TypedUploadParseError(
            TypedUploadParseFailureCode.INVALID_IDENTITY_FIELD,
            "The typed upload identity fields are invalid.",
            ordinal=ordinal,
        )
    if len(
        description
    ) > definition.maximum_description_characters or _contains_forbidden_description_control(
        description
    ):
        raise TypedUploadParseError(
            TypedUploadParseFailureCode.INVALID_DESCRIPTION,
            "The typed upload description is invalid.",
            ordinal=ordinal,
        )
    submitted_identity_hash = dataset_description_submitted_identity_hash(
        workspace_id=workspace_id,
        target_asset_id=target_asset_id,
        platform=platform,
        database_name=database_name,
        schema_name=schema_name,
        table_name=table_name,
    )
    candidate_hash = dataset_description_candidate_hash(
        workspace_id=workspace_id,
        target_asset_id=target_asset_id,
        proposed_description=description,
        submitted_identity_hash=submitted_identity_hash,
        definition=definition,
    )
    return DatasetDescriptionCandidateDraft(
        workspace_id=workspace_id,
        ordinal=ordinal,
        target_asset_id=target_asset_id,
        platform=platform,
        database_name=database_name,
        schema_name=schema_name,
        table_name=table_name,
        proposed_description=description,
        submitted_identity_hash=submitted_identity_hash,
        candidate_hash=candidate_hash,
    )


def dataset_description_submitted_identity_hash(
    *,
    workspace_id: UUID,
    target_asset_id: UUID,
    platform: str,
    database_name: str,
    schema_name: str,
    table_name: str,
) -> str:
    """Rebuild the immutable V2 submitted-identity digest for read-time verification."""

    return canonical_json_hash(
        {
            "contract": _CANDIDATE_IDENTITY_HASH_CONTRACT,
            "database_name": database_name,
            "platform": platform,
            "schema_name": schema_name,
            "table_name": table_name,
            "target_asset_id": str(target_asset_id),
            "workspace_id": str(workspace_id),
        }
    )


def dataset_description_candidate_hash(
    *,
    workspace_id: UUID,
    target_asset_id: UUID,
    proposed_description: str,
    submitted_identity_hash: str,
    definition: TypedUploadProfileDefinition = DATASET_DESCRIPTION_CSV_V1,
) -> str:
    """Rebuild the immutable V2 candidate digest without accepting provider-shaped input."""

    return canonical_json_hash(
        {
            "candidate_kind": DATASET_DESCRIPTION_CANDIDATE_KIND,
            "content_profile": definition.content_profile.value,
            "contract": _CANDIDATE_HASH_CONTRACT,
            "evidence_version": DATASET_DESCRIPTION_CANDIDATE_EVIDENCE_VERSION,
            "proposed_description": proposed_description,
            "schema_version": definition.schema_version,
            "submitted_identity_hash": submitted_identity_hash,
            "target_asset_id": str(target_asset_id),
            "workspace_id": str(workspace_id),
        }
    )


def dataset_description_candidate_root_seed() -> bytes:
    """Return the frozen V2 ordered-result seed shared by every tabular encoding."""

    return hashlib.sha256(_CANDIDATE_ROOT_CONTRACT).digest()


def advance_dataset_description_candidate_root(
    *, current: bytes, ordinal: int, candidate_hash: str
) -> bytes:
    """Advance the frozen V2 ordered-result chain for one validated candidate."""

    return hashlib.sha256(
        _CANDIDATE_ROOT_CONTRACT
        + current
        + ordinal.to_bytes(8, byteorder="big", signed=False)
        + bytes.fromhex(candidate_hash)
    ).digest()


def _validate_expected_hash(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("The expected source SHA-256 must be lowercase hexadecimal.")


def _contains_forbidden_identity_control(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _contains_forbidden_description_control(value: str) -> bool:
    return any(
        (ord(character) < 32 and character not in {"\t", "\r", "\n"}) or ord(character) == 127
        for character in value
    )
