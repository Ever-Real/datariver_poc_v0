from __future__ import annotations

import csv
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from io import StringIO
from typing import Final
from uuid import UUID

from datariver.domain.common import ValidationError

CSV_SAFETY_VERSION: Final = "csv-safe-v1"
MAXIMUM_CSV_RECORD_BYTES: Final = 1_048_576

CATALOG_EXPORT_CSV_HEADERS: Final = (
    "asset_id",
    "external_urn",
    "platform",
    "database_name",
    "schema_name",
    "name",
    "asset_type",
    "classification",
    "lifecycle",
    "description",
    "source_version",
    "observed_at",
)

_FORMULA_PREFIXES: Final = frozenset("=+-@")
_LEADING_CONTROL_CHARACTERS: Final = frozenset("\t\r\n")


@dataclass(frozen=True, slots=True)
class CatalogExportCsvRow:
    """One already-authorized row in the fixed catalog export schema."""

    asset_id: UUID
    external_urn: str
    platform: str | None
    database_name: str | None
    schema_name: str | None
    name: str
    asset_type: str
    classification: str
    lifecycle: str
    description: str | None
    source_version: str
    observed_at: str


def iter_catalog_export_csv(rows: Iterable[CatalogExportCsvRow]) -> Iterator[bytes]:
    """Yield deterministic RFC 4180 UTF-8 header and row chunks."""

    yield catalog_export_csv_header()
    for row in rows:
        yield encode_catalog_export_csv_row(row)


def catalog_export_csv_header() -> bytes:
    """Return the fixed catalog export header as one UTF-8 RFC 4180 record."""

    return _encode_record(CATALOG_EXPORT_CSV_HEADERS)


def encode_catalog_export_csv_row(row: CatalogExportCsvRow) -> bytes:
    """Encode one typed catalog export row using the fixed safety policy."""

    return _encode_record(
        (
            row.asset_id,
            row.external_urn,
            row.platform,
            row.database_name,
            row.schema_name,
            row.name,
            row.asset_type,
            row.classification,
            row.lifecycle,
            row.description,
            row.source_version,
            row.observed_at,
        )
    )


def _encode_record(values: tuple[object | None, ...]) -> bytes:
    stream = StringIO(newline="")
    writer = csv.writer(
        stream,
        delimiter=",",
        quotechar='"',
        doublequote=True,
        escapechar=None,
        lineterminator="\r\n",
        quoting=csv.QUOTE_MINIMAL,
        strict=True,
    )
    writer.writerow(tuple(catalog_export_safe_cell(value) for value in values))
    encoded = stream.getvalue().encode("utf-8")
    if len(encoded) > MAXIMUM_CSV_RECORD_BYTES:
        raise ValidationError(
            "The catalog CSV record exceeds the configured safety limit.",
            details={"code": "EXPORT_CSV_RECORD_LIMIT"},
        )
    return encoded


def catalog_export_safe_cell(value: object | None) -> str:
    """Normalize a value for a spreadsheet-like catalog export cell.

    Both CSV and XLSX use this exact policy so a user cannot turn a catalog
    value into a formula merely by selecting a different download format.
    """
    text = "" if value is None else str(value)
    if "\x00" in text or any(
        ord(character) < 0x20 and character not in "\t\r\n" for character in text
    ):
        raise ValidationError(
            "Catalog export values must not contain NUL or prohibited control characters.",
            details={"code": "EXPORT_CSV_INVALID_VALUE"},
        )
    if text[:1] in _LEADING_CONTROL_CHARACTERS:
        return f"'{text}"

    first_non_whitespace = next((character for character in text if not character.isspace()), "")
    if first_non_whitespace in _FORMULA_PREFIXES:
        return f"'{text}"
    return text
