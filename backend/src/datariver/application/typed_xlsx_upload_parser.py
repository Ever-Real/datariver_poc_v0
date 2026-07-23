from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import re
import tempfile
import zipfile
from collections.abc import AsyncIterable, Awaitable, Callable, Generator, Iterator
from itertools import islice
from pathlib import PurePosixPath
from typing import IO
from uuid import UUID
from xml.etree import ElementTree
from xml.parsers import expat

from datariver.application.typed_upload_parser import (
    DatasetDescriptionCandidateDraft,
    DatasetDescriptionParseSummary,
    TypedUploadParseError,
    TypedUploadParseFailureCode,
    advance_dataset_description_candidate_root,
    dataset_description_candidate_from_values,
    dataset_description_candidate_root_seed,
)
from datariver.application.typed_upload_profiles import (
    DATASET_DESCRIPTION_XLSX_V1,
    TypedUploadProfileDefinition,
)
from datariver.domain.registration import UploadContentProfile

_CONTENT_TYPES = "[Content_Types].xml"
_WORKBOOK = "xl/workbook.xml"
_WORKBOOK_RELS = "xl/_rels/workbook.xml.rels"
_SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_WORKSHEET_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
_SHARED_STRINGS = "xl/sharedStrings.xml"
_CELL_REFERENCE = re.compile(r"^([A-Z]{1,3})([1-9][0-9]*)$")
_SAFE_ZIP_METHODS = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
_MAXIMUM_ZIP_ENTRIES = 512
_MAXIMUM_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
_MAXIMUM_SINGLE_ENTRY_BYTES = 32 * 1024 * 1024
_MAXIMUM_COMPRESSION_RATIO = 100
_MAXIMUM_SHARED_STRINGS = 20_000
_MAXIMUM_SHARED_STRING_BYTES = 16 * 1024 * 1024
_MAXIMUM_METADATA_XML_BYTES = 2 * 1024 * 1024
_MEMORY_SPOOL_BYTES = 8 * 1024 * 1024
_CANDIDATE_MEMORY_SPOOL_BYTES = 256 * 1024
_MAXIMUM_CANDIDATE_SPOOL_BYTES = 64 * 1024 * 1024
_CANDIDATE_REPLAY_BATCH_SIZE = 16
_FORBIDDEN_XML_MARKERS = (b"<!doctype", b"<!entity")

CandidateConsumer = Callable[[DatasetDescriptionCandidateDraft], Awaitable[None]]


async def parse_dataset_description_xlsx(
    *,
    workspace_id: UUID,
    chunks: AsyncIterable[bytes],
    expected_source_sha256: str,
    consume_candidate: CandidateConsumer,
    definition: TypedUploadProfileDefinition = DATASET_DESCRIPTION_XLSX_V1,
) -> DatasetDescriptionParseSummary:
    """Parse the registered XLSX profile without trusting workbook active content.

    The package is streamed to a bounded spooled file because ZIP central-directory access is
    random. Worksheet XML and shared strings are then iterated without constructing a workbook
    object model. As with the CSV parser, ``consume_candidate`` is attempt-local: publication must
    remain fenced until the source hash and the complete workbook have reconciled.
    """

    _validate_expected_hash(expected_source_sha256)
    if definition.content_profile is not UploadContentProfile.DATASET_DESCRIPTION_XLSX_V1:
        raise ValueError("The XLSX parser requires its exact registered content profile.")

    source_hasher = hashlib.sha256()
    total_bytes = 0
    with tempfile.SpooledTemporaryFile(max_size=_MEMORY_SPOOL_BYTES, mode="w+b") as package_file:
        async for chunk in chunks:
            if not isinstance(chunk, bytes):
                raise TypeError("Typed upload chunks must be bytes.")
            if not chunk:
                continue
            total_bytes += len(chunk)
            if total_bytes > definition.maximum_file_bytes:
                raise TypedUploadParseError(
                    TypedUploadParseFailureCode.FILE_TOO_LARGE,
                    "The XLSX upload exceeds its bounded file-size limit.",
                )
            source_hasher.update(chunk)
            package_file.write(chunk)
        if total_bytes == 0:
            raise TypedUploadParseError(
                TypedUploadParseFailureCode.EMPTY_FILE,
                "The XLSX upload is empty.",
            )
        source_sha256 = source_hasher.hexdigest()
        if source_sha256 != expected_source_sha256:
            raise TypedUploadParseError(
                TypedUploadParseFailureCode.SOURCE_HASH_MISMATCH,
                "The XLSX upload bytes do not match the accepted source hash.",
            )
        package_file.seek(0)
        item_count, candidate_root, candidates = await asyncio.to_thread(
            _parse_xlsx_package,
            package_file,
            workspace_id,
            definition,
        )
        with candidates:
            replay = candidates.replay()
            try:
                while batch := await asyncio.to_thread(
                    _read_candidate_batch,
                    replay,
                    _CANDIDATE_REPLAY_BATCH_SIZE,
                ):
                    for candidate in batch:
                        await consume_candidate(candidate)
            finally:
                replay.close()

    if item_count == 0:
        raise TypedUploadParseError(
            TypedUploadParseFailureCode.EMPTY_DATASET,
            "The XLSX upload contains no candidate rows.",
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


def _parse_xlsx_package(
    package_file: IO[bytes],
    workspace_id: UUID,
    definition: TypedUploadProfileDefinition,
) -> tuple[int, bytes, _ReplayableCandidateSpool]:
    """Run ZIP/XML work off the API event loop within strict decompression/object budgets."""

    candidates = _ReplayableCandidateSpool()
    try:
        with zipfile.ZipFile(package_file) as package:
            entries = _validate_package(package)
            shared_strings = _read_shared_strings(package, entries)
            worksheet_name = _resolve_single_visible_worksheet(package, entries)
            item_count = 0
            seen_assets: set[UUID] = set()
            candidate_root = dataset_description_candidate_root_seed()
            for row_number, fields in _iter_worksheet_rows(
                package,
                worksheet_name=worksheet_name,
                shared_strings=shared_strings,
                maximum_rows=definition.maximum_rows,
            ):
                if row_number == 1:
                    if tuple(fields) != definition.headers:
                        raise TypedUploadParseError(
                            TypedUploadParseFailureCode.INVALID_HEADER,
                            "The XLSX header does not match the registered schema.",
                        )
                    continue
                item_count += 1
                candidate = dataset_description_candidate_from_values(
                    workspace_id=workspace_id,
                    ordinal=item_count,
                    values=fields,
                    definition=definition,
                )
                if candidate.target_asset_id in seen_assets:
                    raise TypedUploadParseError(
                        TypedUploadParseFailureCode.DUPLICATE_ASSET,
                        "The XLSX upload contains more than one row for the same asset.",
                        ordinal=item_count,
                    )
                seen_assets.add(candidate.target_asset_id)
                candidate_root = advance_dataset_description_candidate_root(
                    current=candidate_root,
                    ordinal=item_count,
                    candidate_hash=candidate.candidate_hash,
                )
                candidates.append(candidate)
        candidates.finalize()
    except (zipfile.BadZipFile, zipfile.LargeZipFile) as error:
        candidates.close()
        raise TypedUploadParseError(
            TypedUploadParseFailureCode.INVALID_XLSX_PACKAGE,
            "The XLSX package is not a valid ZIP container.",
        ) from error
    except BaseException:
        candidates.close()
        raise
    return item_count, candidate_root, candidates


class _ReplayableCandidateSpool:
    """Attempt-local, repeatable candidate storage with a small fixed RAM threshold."""

    def __init__(self) -> None:
        self._file = tempfile.SpooledTemporaryFile(
            max_size=_CANDIDATE_MEMORY_SPOOL_BYTES,
            mode="w+b",
        )
        self._writer: gzip.GzipFile | None = gzip.GzipFile(
            fileobj=self._file,
            mode="wb",
            compresslevel=1,
        )
        self._finalized = False
        self._closed = False
        self._storage_bytes = 0

    def __enter__(self) -> _ReplayableCandidateSpool:
        if self._closed:
            raise RuntimeError("The XLSX candidate spool is closed.")
        return self

    def __exit__(self, *_error: object) -> None:
        self.close()

    @property
    def rolled_to_disk(self) -> bool:
        return bool(getattr(self._file, "_rolled", False))

    @property
    def storage_bytes(self) -> int:
        if not self._finalized:
            raise RuntimeError("The XLSX candidate spool has not been finalized.")
        return self._storage_bytes

    def append(self, candidate: DatasetDescriptionCandidateDraft) -> None:
        if self._finalized or self._closed or self._writer is None:
            raise RuntimeError("The XLSX candidate spool is not writable.")
        record = json.dumps(
            [
                str(candidate.workspace_id),
                candidate.ordinal,
                str(candidate.target_asset_id),
                candidate.platform,
                candidate.database_name,
                candidate.schema_name,
                candidate.table_name,
                candidate.proposed_description,
                candidate.submitted_identity_hash,
                candidate.candidate_hash,
                candidate.candidate_kind,
                candidate.evidence_version,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self._writer.write(record)
        self._writer.write(b"\n")

    def finalize(self) -> None:
        if self._closed or self._writer is None:
            raise RuntimeError("The XLSX candidate spool is closed.")
        if self._finalized:
            return
        self._writer.close()
        self._writer = None
        self._file.seek(0, 2)
        self._storage_bytes = self._file.tell()
        if self._storage_bytes > _MAXIMUM_CANDIDATE_SPOOL_BYTES:
            self.close()
            raise _xlsx_error("The XLSX candidate spool exceeds its bounded storage limit.")
        self._finalized = True

    def replay(self) -> Generator[DatasetDescriptionCandidateDraft, None, None]:
        if not self._finalized or self._closed:
            raise RuntimeError("The XLSX candidate spool is not available for replay.")
        self._file.seek(0)
        with gzip.GzipFile(fileobj=self._file, mode="rb") as reader:
            while record := reader.readline():
                yield _candidate_from_spool_record(record)

    def close(self) -> None:
        if self._closed:
            return
        if self._writer is not None:
            self._writer.close()
            self._writer = None
        self._file.close()
        self._closed = True


def _read_candidate_batch(
    candidates: Iterator[DatasetDescriptionCandidateDraft],
    maximum_items: int,
) -> tuple[DatasetDescriptionCandidateDraft, ...]:
    return tuple(islice(candidates, maximum_items))


def _candidate_from_spool_record(record: bytes) -> DatasetDescriptionCandidateDraft:
    try:
        decoded: object = json.loads(record)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("The XLSX candidate spool is corrupt.") from error
    if not isinstance(decoded, list) or len(decoded) != 12:
        raise RuntimeError("The XLSX candidate spool has an invalid record.")
    return DatasetDescriptionCandidateDraft(
        workspace_id=UUID(_spooled_string(decoded[0])),
        ordinal=_spooled_ordinal(decoded[1]),
        target_asset_id=UUID(_spooled_string(decoded[2])),
        platform=_spooled_string(decoded[3]),
        database_name=_spooled_string(decoded[4]),
        schema_name=_spooled_string(decoded[5]),
        table_name=_spooled_string(decoded[6]),
        proposed_description=_spooled_string(decoded[7]),
        submitted_identity_hash=_spooled_string(decoded[8]),
        candidate_hash=_spooled_string(decoded[9]),
        candidate_kind=_spooled_string(decoded[10]),
        evidence_version=_spooled_string(decoded[11]),
    )


def _spooled_string(value: object) -> str:
    if not isinstance(value, str):
        raise RuntimeError("The XLSX candidate spool has an invalid string field.")
    return value


def _spooled_ordinal(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RuntimeError("The XLSX candidate spool has an invalid ordinal.")
    return value


def _validate_package(package: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    infos = package.infolist()
    if not infos or len(infos) > _MAXIMUM_ZIP_ENTRIES:
        raise _xlsx_error("The XLSX package has an invalid number of entries.")
    entries: dict[str, zipfile.ZipInfo] = {}
    total_uncompressed = 0
    for info in infos:
        name = info.filename.replace("\\", "/")
        path = PurePosixPath(name)
        if (
            not name
            or name.startswith("/")
            or ".." in path.parts
            or path.is_absolute()
            or name in entries
        ):
            raise _xlsx_error("The XLSX package contains an unsafe or duplicate path.")
        if info.flag_bits & 0x1 or info.compress_type not in _SAFE_ZIP_METHODS:
            raise _xlsx_error("The XLSX package uses encryption or an unsupported compression.")
        mode = (info.external_attr >> 16) & 0o170000
        if mode not in {0, 0o100000, 0o040000}:
            raise _xlsx_error("The XLSX package contains a non-regular entry.")
        if info.file_size > _MAXIMUM_SINGLE_ENTRY_BYTES:
            raise _xlsx_error("An XLSX package entry exceeds its uncompressed size limit.")
        total_uncompressed += info.file_size
        if total_uncompressed > _MAXIMUM_UNCOMPRESSED_BYTES:
            raise _xlsx_error("The XLSX package exceeds its total uncompressed size limit.")
        if info.file_size and (
            info.compress_size == 0
            or info.file_size > max(info.compress_size, 1) * _MAXIMUM_COMPRESSION_RATIO
        ):
            raise _xlsx_error("The XLSX package exceeds its compression-ratio limit.")
        lowered = name.lower()
        if (
            "vbaproject" in lowered
            or lowered.startswith("xl/externallinks/")
            or lowered.startswith("xl/embeddings/")
            or lowered.startswith("xl/activex/")
            or lowered.startswith("xl/connections")
        ):
            raise _xlsx_error("The XLSX package contains active or externally linked content.")
        entries[name] = info
    for required in (_CONTENT_TYPES, _WORKBOOK, _WORKBOOK_RELS):
        if required not in entries:
            raise _xlsx_error("The XLSX package is missing a required workbook part.")
    _reject_forbidden_xml(package, entries)
    _reject_external_relationships(package, entries)
    content_types = _read_bounded_entry(package, entries[_CONTENT_TYPES], 2 * 1024 * 1024)
    lowered_types = content_types.lower()
    if b"macroenabled" in lowered_types or b"vbaproject" in lowered_types:
        raise _xlsx_error("The XLSX package declares macro-enabled content.")
    return entries


def _reject_forbidden_xml(
    package: zipfile.ZipFile,
    entries: dict[str, zipfile.ZipInfo],
) -> None:
    for name, info in entries.items():
        if not (name.endswith(".xml") or name.endswith(".rels")):
            continue
        with package.open(info) as stream:
            marker_window = b""
            while chunk := stream.read(64 * 1024):
                lowered = (marker_window + chunk).lower()
                if any(marker in lowered for marker in _FORBIDDEN_XML_MARKERS):
                    raise _xlsx_error("The XLSX package contains a forbidden XML declaration.")
                marker_window = lowered[-32:]


def _reject_external_relationships(
    package: zipfile.ZipFile,
    entries: dict[str, zipfile.ZipInfo],
) -> None:
    for name, info in entries.items():
        if not name.endswith(".rels"):
            continue
        with package.open(info) as stream:
            for _event, element in _safe_iterparse(stream, tag="Relationship"):
                if element.attrib.get("TargetMode", "").lower() == "external":
                    raise _xlsx_error("The XLSX package contains an external relationship.")
                element.clear()


def _resolve_single_visible_worksheet(
    package: zipfile.ZipFile,
    entries: dict[str, zipfile.ZipInfo],
) -> str:
    if (
        entries[_WORKBOOK].file_size > _MAXIMUM_METADATA_XML_BYTES
        or entries[_WORKBOOK_RELS].file_size > _MAXIMUM_METADATA_XML_BYTES
    ):
        raise _xlsx_error("The XLSX workbook metadata exceeds its size limit.")
    relationships: dict[str, str] = {}
    with package.open(entries[_WORKBOOK_RELS]) as stream:
        for _event, element in _safe_iterparse(stream, tag="Relationship"):
            if element.attrib.get("TargetMode", "").lower() == "external":
                raise _xlsx_error("The XLSX workbook contains an external relationship.")
            relationship_id = element.attrib.get("Id")
            relationship_type = element.attrib.get("Type")
            target = element.attrib.get("Target")
            if relationship_id and relationship_type == _WORKSHEET_REL and target:
                relationships[relationship_id] = _normalize_workbook_target(target)
            element.clear()

    worksheets: list[str] = []
    with package.open(entries[_WORKBOOK]) as stream:
        for _event, element in _safe_iterparse(stream, tag="sheet"):
            if element.attrib.get("state", "visible") != "visible":
                raise _xlsx_error("The XLSX workbook contains a hidden worksheet.")
            relationship_id = element.attrib.get(f"{{{_REL_NS}}}id")
            if not relationship_id or relationship_id not in relationships:
                raise _xlsx_error("The XLSX worksheet relationship is invalid.")
            worksheets.append(relationships[relationship_id])
            element.clear()
    if len(worksheets) != 1 or worksheets[0] not in entries:
        raise _xlsx_error("The XLSX profile requires exactly one visible worksheet.")
    return worksheets[0]


def _normalize_workbook_target(target: str) -> str:
    normalized = target.replace("\\", "/")
    if normalized.startswith("/"):
        normalized = normalized[1:]
    elif not normalized.startswith("xl/"):
        normalized = f"xl/{normalized}"
    path = PurePosixPath(normalized)
    if ".." in path.parts or path.is_absolute():
        raise _xlsx_error("The XLSX worksheet target is unsafe.")
    return str(path)


def _read_shared_strings(
    package: zipfile.ZipFile,
    entries: dict[str, zipfile.ZipInfo],
) -> tuple[str, ...]:
    info = entries.get(_SHARED_STRINGS)
    if info is None:
        return ()
    if info.file_size > _MAXIMUM_SHARED_STRING_BYTES:
        raise _xlsx_error("The XLSX shared-string table exceeds its size limit.")
    reader = _SharedStringReader()
    with package.open(info) as stream:
        reader.parse(stream)
    return tuple(reader.values)


def _iter_worksheet_rows(
    package: zipfile.ZipFile,
    *,
    worksheet_name: str,
    shared_strings: tuple[str, ...],
    maximum_rows: int,
) -> Iterator[tuple[int, list[str]]]:
    reader = _WorksheetRowReader(
        shared_strings=shared_strings,
        maximum_rows=maximum_rows,
        maximum_row_bytes=64 * 1024,
    )
    with package.open(worksheet_name) as stream:
        yield from reader.parse(stream)


class _SharedStringReader:
    def __init__(self) -> None:
        self.values: list[str] = []
        self._inside_item = False
        self._capture_text = False
        self._parts: list[str] = []
        self._characters = 0

    def parse(self, stream: IO[bytes]) -> None:
        parser = _expat_parser()
        parser.StartElementHandler = self._start
        parser.EndElementHandler = self._end
        parser.CharacterDataHandler = self._characters_seen
        _feed_expat(parser, stream)

    def _start(self, name: str, _attributes: dict[str, str]) -> None:
        local = _local_name(name)
        if local == "si":
            if self._inside_item:
                raise _xlsx_error("The XLSX shared-string table is malformed.")
            self._inside_item = True
            self._parts = []
            self._characters = 0
        elif local == "t" and self._inside_item:
            self._capture_text = True
        elif local in {"rPh", "phoneticPr"}:
            raise _xlsx_error("The XLSX shared-string table contains unsupported phonetics.")

    def _end(self, name: str) -> None:
        local = _local_name(name)
        if local == "t":
            self._capture_text = False
        elif local == "si":
            if not self._inside_item:
                raise _xlsx_error("The XLSX shared-string table is malformed.")
            self.values.append("".join(self._parts))
            if len(self.values) > _MAXIMUM_SHARED_STRINGS:
                raise _xlsx_error("The XLSX shared-string table exceeds its item limit.")
            self._inside_item = False
            self._parts = []

    def _characters_seen(self, value: str) -> None:
        if not self._capture_text:
            return
        self._characters += len(value)
        if self._characters > 10_000:
            raise _xlsx_error("An XLSX shared string exceeds its character limit.")
        self._parts.append(value)


class _WorksheetRowReader:
    def __init__(
        self,
        *,
        shared_strings: tuple[str, ...],
        maximum_rows: int,
        maximum_row_bytes: int,
    ) -> None:
        self._shared_strings = shared_strings
        self._maximum_rows = maximum_rows
        self._maximum_row_bytes = maximum_row_bytes
        self._expected_row = 1
        self._row_number: int | None = None
        self._row_start_byte: int | None = None
        self._fields: list[str] = []
        self._seen_columns: set[int] = set()
        self._cell_column: int | None = None
        self._cell_type = ""
        self._cell_parts: list[str] = []
        self._cell_characters = 0
        self._capture_text = False
        self._completed: list[tuple[int, list[str]]] = []
        self._parser: expat.XMLParserType | None = None

    def parse(self, stream: IO[bytes]) -> Iterator[tuple[int, list[str]]]:
        parser = _expat_parser()
        self._parser = parser
        parser.StartElementHandler = self._start
        parser.EndElementHandler = self._end
        parser.CharacterDataHandler = self._characters_seen
        try:
            while chunk := stream.read(64 * 1024):
                parser.Parse(chunk, False)
                yield from self._drain()
            parser.Parse(b"", True)
            yield from self._drain()
        except expat.ExpatError as error:
            raise _xlsx_error("The XLSX package contains malformed worksheet XML.") from error
        finally:
            self._parser = None

    def _start(self, name: str, attributes: dict[str, str]) -> None:
        local = _local_name(name)
        if local == "col" and attributes.get("hidden") in {"1", "true"}:
            raise _xlsx_error("The XLSX worksheet contains a hidden column.")
        if local in {"mergeCell", "hyperlink"}:
            raise _xlsx_error("The XLSX worksheet contains an unsupported merged or linked cell.")
        if local == "row":
            if self._row_number is not None:
                raise _xlsx_error("The XLSX worksheet contains nested rows.")
            try:
                row_number = int(attributes.get("r", "0"))
            except ValueError as error:
                raise _xlsx_error("The XLSX worksheet contains an invalid row number.") from error
            if (
                row_number != self._expected_row
                or row_number > self._maximum_rows + 1
                or attributes.get("hidden") in {"1", "true"}
            ):
                raise _xlsx_error(
                    "The XLSX worksheet rows must be visible, contiguous and bounded."
                )
            self._row_number = row_number
            self._row_start_byte = self._current_byte_index()
            self._fields = [""] * 6
            self._seen_columns = set()
            return
        if local == "c":
            if self._row_number is None or self._cell_column is not None:
                raise _xlsx_error("The XLSX worksheet contains an invalid cell position.")
            reference = attributes.get("r", "")
            match = _CELL_REFERENCE.fullmatch(reference)
            if match is None or int(match.group(2)) != self._row_number:
                raise _xlsx_error("The XLSX worksheet contains an invalid cell reference.")
            column = _column_number(match.group(1))
            if column > 6 or column in self._seen_columns:
                raise _xlsx_error("The XLSX worksheet contains extra or duplicate columns.")
            self._seen_columns.add(column)
            self._cell_column = column
            self._cell_type = attributes.get("t", "")
            self._cell_parts = []
            self._cell_characters = 0
            return
        if local == "f":
            raise _xlsx_error("The XLSX worksheet contains a formula.")
        if local in {"t", "v"} and self._cell_column is not None:
            self._capture_text = True

    def _end(self, name: str) -> None:
        local = _local_name(name)
        if local in {"t", "v"}:
            self._capture_text = False
        elif local == "c":
            if self._cell_column is None:
                raise _xlsx_error("The XLSX worksheet contains an invalid cell boundary.")
            self._fields[self._cell_column - 1] = self._resolve_cell_text()
            self._cell_column = None
            self._cell_parts = []
        elif local == "row":
            if self._row_number is None or self._row_start_byte is None:
                raise _xlsx_error("The XLSX worksheet contains an invalid row boundary.")
            if self._current_byte_index() - self._row_start_byte > self._maximum_row_bytes:
                raise _xlsx_error("An XLSX worksheet row exceeds its byte limit.")
            self._completed.append((self._row_number, self._fields))
            self._expected_row += 1
            self._row_number = None
            self._row_start_byte = None
            self._fields = []

    def _characters_seen(self, value: str) -> None:
        if not self._capture_text:
            return
        self._cell_characters += len(value)
        if self._cell_characters > 10_000:
            raise _xlsx_error("An XLSX cell exceeds its character limit.")
        self._cell_parts.append(value)

    def _resolve_cell_text(self) -> str:
        value = "".join(self._cell_parts)
        if self._cell_type == "s":
            try:
                return self._shared_strings[int(value)]
            except (ValueError, IndexError) as error:
                raise _xlsx_error(
                    "The XLSX worksheet has an invalid shared-string reference."
                ) from error
        if self._cell_type not in {"", "str", "inlineStr"}:
            raise _xlsx_error("The XLSX worksheet contains an unsupported cell type.")
        return value

    def _current_byte_index(self) -> int:
        if self._parser is None:
            raise RuntimeError("The worksheet parser is not active.")
        return int(self._parser.CurrentByteIndex)

    def _drain(self) -> Iterator[tuple[int, list[str]]]:
        while self._completed:
            yield self._completed.pop(0)


def _expat_parser() -> expat.XMLParserType:
    # DTD/entity markers are rejected package-wide before parsing. Expat parameter entities are
    # additionally disabled so the streaming worksheet/shared-string parser has no external I/O.
    parser = expat.ParserCreate(namespace_separator="}")
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    return parser


def _feed_expat(parser: expat.XMLParserType, stream: IO[bytes]) -> None:
    try:
        while chunk := stream.read(64 * 1024):
            parser.Parse(chunk, False)
        parser.Parse(b"", True)
    except expat.ExpatError as error:
        raise _xlsx_error("The XLSX package contains malformed XML.") from error


def _local_name(name: str) -> str:
    return name.rsplit("}", maxsplit=1)[-1]


def _safe_iterparse(stream: IO[bytes], *, tag: str) -> Iterator[tuple[str, ElementTree.Element]]:
    try:
        # Package-wide DTD/entity rejection runs before every bounded XML parse.
        for event, element in ElementTree.iterparse(stream, events=("end",)):  # noqa: S314
            if element.tag == _xlsx_tag(tag) or element.tag == f"{{{_PACKAGE_REL_NS}}}{tag}":
                yield event, element
    except ElementTree.ParseError as error:
        raise _xlsx_error("The XLSX package contains malformed XML.") from error


def _read_bounded_entry(
    package: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    maximum_bytes: int,
) -> bytes:
    if info.file_size > maximum_bytes:
        raise _xlsx_error("An XLSX metadata part exceeds its size limit.")
    with package.open(info) as stream:
        value = stream.read(maximum_bytes + 1)
    if len(value) > maximum_bytes:
        raise _xlsx_error("An XLSX metadata part exceeds its size limit.")
    return value


def _column_number(value: str) -> int:
    number = 0
    for character in value:
        number = number * 26 + (ord(character) - ord("A") + 1)
    return number


def _xlsx_tag(value: str) -> str:
    return f"{{{_SPREADSHEET_NS}}}{value}"


def _validate_expected_hash(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("The expected source SHA-256 must be lowercase hexadecimal.")


def _xlsx_error(message: str) -> TypedUploadParseError:
    return TypedUploadParseError(TypedUploadParseFailureCode.INVALID_XLSX_PACKAGE, message)
