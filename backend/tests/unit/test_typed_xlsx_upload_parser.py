# ruff: noqa: E501 -- OOXML fixture URIs are protocol literals and must not be wrapped.
from __future__ import annotations

import hashlib
import io
import zipfile
from collections.abc import AsyncIterator
from html import escape
from uuid import UUID, uuid4

import pytest

from datariver.application.typed_upload_parser import (
    DatasetDescriptionCandidateDraft,
    DatasetDescriptionParseSummary,
    TypedUploadParseError,
    TypedUploadParseFailureCode,
)
from datariver.application.typed_xlsx_upload_parser import parse_dataset_description_xlsx

HEADERS = (
    "asset_id",
    "platform",
    "database_name",
    "schema_name",
    "table_name",
    "description",
)
_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


async def _chunks(value: bytes, *, width: int = 19) -> AsyncIterator[bytes]:
    for offset in range(0, len(value), width):
        yield value[offset : offset + width]


def _xlsx(
    rows: list[list[str]],
    *,
    sheet_state: str = "visible",
    formula_at: str | None = None,
    hidden_row: int | None = None,
    external_relationship: bool = False,
    extra_entries: dict[str, bytes] | None = None,
) -> bytes:
    cells: list[str] = []
    for row_number, row in enumerate(rows, start=1):
        values: list[str] = []
        for column_number, value in enumerate(row, start=1):
            reference = f"{chr(64 + column_number)}{row_number}"
            formula = "<f>1+1</f>" if formula_at == reference else ""
            values.append(
                f'<c r="{reference}" t="inlineStr">{formula}<is><t>{escape(value)}</t></is></c>'
            )
        hidden = ' hidden="1"' if hidden_row == row_number else ""
        cells.append(f'<row r="{row_number}"{hidden}>{"".join(values)}</row>')
    worksheet = (
        f'<worksheet xmlns="{_NS}"><sheetData>{"".join(cells)}</sheetData></worksheet>'
    ).encode()
    content_types = b"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""
    workbook = f"""<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="{_NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="dataset_descriptions" sheetId="1" state="{sheet_state}" r:id="rId1"/></sheets>
</workbook>""".encode()
    workbook_rels = b"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""
    root_rels = (
        b"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rExternal" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.invalid/" TargetMode="External"/>
</Relationships>"""
        if external_relationship
        else b"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>"""
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", content_types)
        package.writestr("_rels/.rels", root_rels)
        package.writestr("xl/workbook.xml", workbook)
        package.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        package.writestr("xl/worksheets/sheet1.xml", worksheet)
        for name, entry_value in (extra_entries or {}).items():
            package.writestr(name, entry_value)
    return output.getvalue()


async def _parse(
    value: bytes,
    *,
    workspace_id: UUID | None = None,
    expected_hash: str | None = None,
) -> tuple[list[DatasetDescriptionCandidateDraft], DatasetDescriptionParseSummary]:
    candidates: list[DatasetDescriptionCandidateDraft] = []

    async def consume(candidate: DatasetDescriptionCandidateDraft) -> None:
        candidates.append(candidate)

    summary = await parse_dataset_description_xlsx(
        workspace_id=workspace_id or uuid4(),
        chunks=_chunks(value),
        expected_source_sha256=expected_hash or hashlib.sha256(value).hexdigest(),
        consume_candidate=consume,
    )
    return candidates, summary


@pytest.mark.asyncio
async def test_xlsx_parser_streams_rows_and_produces_deterministic_candidate_evidence() -> None:
    workspace_id = uuid4()
    first_id = uuid4()
    second_id = uuid4()
    value = _xlsx(
        [
            list(HEADERS),
            [str(first_id), "postgres", "fab", "public", "wafer", "first"],
            [str(second_id), "oracle", "mes", "core", "lot", ""],
        ]
    )

    candidates, summary = await _parse(value, workspace_id=workspace_id)
    repeated, repeated_summary = await _parse(value, workspace_id=workspace_id)

    assert candidates == repeated
    assert summary == repeated_summary
    assert [candidate.target_asset_id for candidate in candidates] == [first_id, second_id]
    assert candidates[1].proposed_description == ""
    assert summary.item_count == 2
    assert summary.source_sha256 == hashlib.sha256(value).hexdigest()
    assert len(summary.candidate_root_hash) == 64


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value",
    [
        b"not-a-zip",
        _xlsx([list(HEADERS)], sheet_state="hidden"),
        _xlsx([list(HEADERS)], formula_at="A1"),
        _xlsx([list(HEADERS)], hidden_row=1),
        _xlsx([list(HEADERS)], external_relationship=True),
        _xlsx([list(HEADERS)], extra_entries={"xl/vbaProject.bin": b"macro"}),
        _xlsx([list(HEADERS)], extra_entries={"xl/embeddings/oleObject1.bin": b"ole"}),
        _xlsx([list(HEADERS)], extra_entries={"xl/unsafe.xml": b"<!DOCTYPE x>"}),
    ],
)
async def test_xlsx_parser_rejects_unsafe_active_or_hidden_package_content(value: bytes) -> None:
    with pytest.raises(TypedUploadParseError) as captured:
        await _parse(value)

    assert captured.value.failure_code is TypedUploadParseFailureCode.INVALID_XLSX_PACKAGE


@pytest.mark.asyncio
async def test_xlsx_parser_rejects_wrong_header_duplicate_asset_and_source_hash() -> None:
    asset_id = uuid4()
    invalid_header = _xlsx([[*HEADERS[:-1], "wrong"]])
    with pytest.raises(TypedUploadParseError) as captured:
        await _parse(invalid_header)
    assert captured.value.failure_code is TypedUploadParseFailureCode.INVALID_HEADER

    duplicate = _xlsx(
        [
            list(HEADERS),
            [str(asset_id), "p", "d", "s", "t", "one"],
            [str(asset_id), "p", "d", "s", "t", "two"],
        ]
    )
    with pytest.raises(TypedUploadParseError) as captured:
        await _parse(duplicate)
    assert captured.value.failure_code is TypedUploadParseFailureCode.DUPLICATE_ASSET

    valid = _xlsx([list(HEADERS), [str(uuid4()), "p", "d", "s", "t", "text"]])
    with pytest.raises(TypedUploadParseError) as captured:
        await _parse(valid, expected_hash="0" * 64)
    assert captured.value.failure_code is TypedUploadParseFailureCode.SOURCE_HASH_MISMATCH


@pytest.mark.asyncio
async def test_xlsx_parser_rejects_zip_bomb_compression_ratio() -> None:
    value = _xlsx(
        [list(HEADERS)],
        extra_entries={"xl/media/padding.bin": b"0" * (1024 * 1024)},
    )
    with pytest.raises(TypedUploadParseError) as captured:
        await _parse(value)

    assert captured.value.failure_code is TypedUploadParseFailureCode.INVALID_XLSX_PACKAGE
