from __future__ import annotations

# The OOXML relationship/content type literals are protocol identifiers and cannot
# be split without reducing their inspectability.
# ruff: noqa: E501
from collections.abc import AsyncIterable, AsyncIterator, Iterable
from io import BytesIO
from tempfile import SpooledTemporaryFile
from typing import Final
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from datariver.application.catalog_export_csv import (
    CATALOG_EXPORT_CSV_HEADERS,
    CatalogExportCsvRow,
    catalog_export_safe_cell,
)
from datariver.domain.common import ValidationError

XLSX_SAFETY_VERSION: Final = "xlsx-safe-v1"
XLSX_MEMORY_SPOOL_BYTES: Final = 8 * 1024 * 1024
XLSX_STREAM_CHUNK_BYTES: Final = 1024 * 1024


def encode_catalog_export_xlsx(rows: Iterable[CatalogExportCsvRow], *, maximum_bytes: int) -> bytes:
    """Build a fixed, formula-safe XLSX catalog export without client-side data.

    The worker already applies a strict row ceiling.  XLSX packages require a
    central directory, so the generated package is held once in the worker and
    rejected before it can be written when the configured object-size ceiling
    would be exceeded.
    """

    worksheet = _worksheet(rows)
    stream = BytesIO()
    with ZipFile(stream, mode="w", compression=ZIP_DEFLATED, compresslevel=9) as package:
        package.writestr("[Content_Types].xml", _CONTENT_TYPES)
        package.writestr("_rels/.rels", _ROOT_RELATIONSHIPS)
        package.writestr("xl/workbook.xml", _WORKBOOK)
        package.writestr("xl/_rels/workbook.xml.rels", _WORKBOOK_RELATIONSHIPS)
        package.writestr("xl/styles.xml", _STYLES)
        package.writestr("xl/worksheets/sheet1.xml", worksheet)
    value = stream.getvalue()
    if len(value) > maximum_bytes:
        raise ValidationError(
            "The catalog XLSX export exceeds the configured byte limit.",
            details={"code": "EXPORT_BYTE_LIMIT"},
        )
    return value


async def iter_catalog_export_xlsx(
    rows: AsyncIterable[CatalogExportCsvRow],
    *,
    maximum_bytes: int,
) -> AsyncIterator[bytes]:
    """Build a valid XLSX with bounded memory, then yield bounded upload chunks.

    OOXML needs a central directory, so the workbook is assembled in a spooled
    temporary file.  Only the first small fixed window remains in memory; larger
    workbooks spill to the worker's temporary disk and are rejected at the same
    configured artifact byte ceiling used by object storage.
    """

    spool_limit = min(maximum_bytes, XLSX_MEMORY_SPOOL_BYTES)
    with SpooledTemporaryFile(max_size=spool_limit, mode="w+b") as stream:
        with ZipFile(stream, mode="w", compression=ZIP_DEFLATED, compresslevel=9) as package:
            package.writestr("[Content_Types].xml", _CONTENT_TYPES)
            package.writestr("_rels/.rels", _ROOT_RELATIONSHIPS)
            package.writestr("xl/workbook.xml", _WORKBOOK)
            package.writestr("xl/_rels/workbook.xml.rels", _WORKBOOK_RELATIONSHIPS)
            package.writestr("xl/styles.xml", _STYLES)
            with package.open("xl/worksheets/sheet1.xml", mode="w") as worksheet:
                worksheet.write(_WORKSHEET_PREFIX.encode("utf-8"))
                worksheet.write(_row(1, CATALOG_EXPORT_CSV_HEADERS).encode("utf-8"))
                async for number, row in _enumerate_rows(rows, start=2):
                    worksheet.write(_xlsx_row(number, row).encode("utf-8"))
                    _validate_workbook_size(stream.tell(), maximum_bytes=maximum_bytes)
                worksheet.write(_WORKSHEET_SUFFIX.encode("utf-8"))
        size = stream.tell()
        _validate_workbook_size(size, maximum_bytes=maximum_bytes)
        stream.seek(0)
        while chunk := stream.read(XLSX_STREAM_CHUNK_BYTES):
            yield chunk


async def _enumerate_rows(
    rows: AsyncIterable[CatalogExportCsvRow],
    *,
    start: int,
) -> AsyncIterator[tuple[int, CatalogExportCsvRow]]:
    number = start
    async for row in rows:
        yield number, row
        number += 1


def _validate_workbook_size(size: int, *, maximum_bytes: int) -> None:
    if size > maximum_bytes:
        raise ValidationError(
            "The catalog XLSX export exceeds the configured byte limit.",
            details={"code": "EXPORT_BYTE_LIMIT"},
        )


def _worksheet(rows: Iterable[CatalogExportCsvRow]) -> str:
    lines = [
        _WORKSHEET_PREFIX,
        _row(1, CATALOG_EXPORT_CSV_HEADERS),
    ]
    for number, row in enumerate(rows, start=2):
        lines.append(_xlsx_row(number, row))
    lines.append(_WORKSHEET_SUFFIX)
    return "".join(lines)


def _xlsx_row(number: int, row: CatalogExportCsvRow) -> str:
    return _row(
        number,
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
        ),
    )


def _row(number: int, values: tuple[object | None, ...]) -> str:
    cells = "".join(
        f'<c r="{_column_name(index)}{number}" t="inlineStr"><is><t>{escape(catalog_export_safe_cell(value))}</t></is></c>'
        for index, value in enumerate(values, start=1)
    )
    return f'<row r="{number}">{cells}</row>'


def _column_name(index: int) -> str:
    value = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        value = chr(ord("A") + remainder) + value
    return value


_CONTENT_TYPES: Final = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>"""
_ROOT_RELATIONSHIPS: Final = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>"""
_WORKBOOK: Final = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Catalog" sheetId="1" r:id="rId1"/></sheets></workbook>"""
_WORKBOOK_RELATIONSHIPS: Final = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>"""
_STYLES: Final = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts><fills count="1"><fill><patternFill patternType="none"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="1"><xf xfId="0"/></cellXfs></styleSheet>"""
_WORKSHEET_PREFIX: Final = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>"""
_WORKSHEET_SUFFIX: Final = "</sheetData></worksheet>"
