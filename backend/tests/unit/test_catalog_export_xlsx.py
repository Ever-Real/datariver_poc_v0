from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from io import BytesIO
from uuid import UUID
from zipfile import ZipFile

import pytest

from datariver.application.catalog_export_csv import CatalogExportCsvRow
from datariver.application.catalog_export_xlsx import (
    XLSX_SAFETY_VERSION,
    XLSX_STREAM_CHUNK_BYTES,
    encode_catalog_export_xlsx,
    iter_catalog_export_xlsx,
)
from datariver.domain.common import ValidationError


def _row(name: str) -> CatalogExportCsvRow:
    return CatalogExportCsvRow(
        asset_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        external_urn="urn:li:dataset:(urn:li:dataPlatform:postgres,core.schema.table,PROD)",
        platform="postgres",
        database_name="core",
        schema_name="schema",
        name=name,
        asset_type="TABLE",
        classification="INTERNAL",
        lifecycle="ACTIVE",
        description="A & B",
        source_version="v1",
        observed_at=datetime(2026, 7, 18, tzinfo=UTC).isoformat(),
    )


def test_xlsx_contains_fixed_catalog_sheet_with_safe_inline_strings() -> None:
    artifact = encode_catalog_export_xlsx([_row("=unsafe")], maximum_bytes=1_000_000)

    with ZipFile(BytesIO(artifact)) as workbook:
        assert "xl/workbook.xml" in workbook.namelist()
        sheet = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "asset_id" in sheet
    assert "'=unsafe" in sheet
    assert "A &amp; B" in sheet
    assert XLSX_SAFETY_VERSION == "xlsx-safe-v1"


def test_xlsx_fails_closed_when_the_bounded_artifact_is_too_large() -> None:
    with pytest.raises(ValidationError, match="byte limit"):
        encode_catalog_export_xlsx([_row("wafer")], maximum_bytes=1)


async def _async_rows(*names: str) -> AsyncIterator[CatalogExportCsvRow]:
    for name in names:
        yield _row(name)


@pytest.mark.asyncio
async def test_xlsx_stream_is_valid_formula_safe_and_bounded_in_upload_chunks() -> None:
    chunks = [
        chunk
        async for chunk in iter_catalog_export_xlsx(
            _async_rows("첫 번째", "=unsafe"), maximum_bytes=1_000_000
        )
    ]

    assert all(len(chunk) <= XLSX_STREAM_CHUNK_BYTES for chunk in chunks)
    with ZipFile(BytesIO(b"".join(chunks))) as workbook:
        assert workbook.testzip() is None
        sheet = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "첫 번째" in sheet
    assert "'=unsafe" in sheet


@pytest.mark.asyncio
async def test_xlsx_stream_rejects_the_configured_artifact_byte_limit() -> None:
    with pytest.raises(ValidationError, match="byte limit") as error:
        async for _ in iter_catalog_export_xlsx(_async_rows("wafer"), maximum_bytes=1):
            pass

    assert error.value.details["code"] == "EXPORT_BYTE_LIMIT"
