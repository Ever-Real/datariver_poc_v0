from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from uuid import UUID
from zipfile import ZipFile

import pytest

from datariver.application.catalog_export_csv import CatalogExportCsvRow
from datariver.application.catalog_export_xlsx import (
    XLSX_SAFETY_VERSION,
    encode_catalog_export_xlsx,
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
