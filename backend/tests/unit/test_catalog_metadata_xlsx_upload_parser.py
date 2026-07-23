# ruff: noqa: E501 -- OOXML fixture URIs are protocol literals and must not be wrapped.
from __future__ import annotations

import asyncio
import hashlib
import io
import zipfile
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from html import escape
from uuid import UUID, uuid4

import pytest

from datariver.application import typed_xlsx_upload_parser
from datariver.application.catalog_metadata_upload_parser import (
    CatalogMetadataAspect,
    CatalogMetadataCandidateDraft,
    CatalogMetadataParseError,
    CatalogMetadataParseFailureCode,
    CatalogMetadataParseSummary,
    compile_catalog_metadata_candidates,
)
from datariver.application.typed_upload_profiles import (
    CATALOG_METADATA_ROWS_CSV_V1,
    CATALOG_METADATA_ROWS_XLSX_V1,
    TypedUploadProfileDefinition,
)
from datariver.application.typed_xlsx_upload_parser import parse_catalog_metadata_rows_xlsx

HEADERS = CATALOG_METADATA_ROWS_XLSX_V1.headers
_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


async def _chunks(value: bytes, *, width: int = 19) -> AsyncIterator[bytes]:
    for offset in range(0, len(value), width):
        yield value[offset : offset + width]


def _row(
    *,
    record_kind: str,
    asset_id: UUID,
    field_path: str = "",
    operation: str,
    value_text: str = "",
    controlled_ref: str = "",
) -> list[str]:
    return [
        record_kind,
        str(asset_id),
        "postgres",
        "fab",
        "public",
        "wafer",
        field_path,
        operation,
        value_text,
        controlled_ref,
    ]


def _xlsx(
    rows: list[list[str]],
    *,
    sheet_state: str = "visible",
    formula_at: str | None = None,
    hidden_row: int | None = None,
    hidden_column: bool = False,
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
    columns = '<cols><col min="1" max="1" hidden="1"/></cols>' if hidden_column else ""
    worksheet = (
        f'<worksheet xmlns="{_NS}">{columns}<sheetData>{"".join(cells)}</sheetData></worksheet>'
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
  <sheets><sheet name="catalog_metadata" sheetId="1" state="{sheet_state}" r:id="rId1"/></sheets>
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
    definition: TypedUploadProfileDefinition = CATALOG_METADATA_ROWS_XLSX_V1,
) -> tuple[list[CatalogMetadataCandidateDraft], CatalogMetadataParseSummary]:
    candidates: list[CatalogMetadataCandidateDraft] = []

    async def consume(candidate: CatalogMetadataCandidateDraft) -> None:
        candidates.append(candidate)

    summary = await parse_catalog_metadata_rows_xlsx(
        workspace_id=workspace_id or uuid4(),
        chunks=_chunks(value),
        expected_source_sha256=expected_hash or hashlib.sha256(value).hexdigest(),
        consume_candidate=consume,
        definition=definition,
    )
    return candidates, summary


@pytest.mark.asyncio
async def test_xlsx_groups_ten_column_rows_after_complete_package_validation() -> None:
    workspace_id = uuid4()
    asset_id = uuid4()
    tag_id = uuid4()
    value = _xlsx(
        [
            list(HEADERS),
            _row(
                record_kind="COLUMN_DESCRIPTION",
                asset_id=asset_id,
                field_path="lot_id",
                operation="SET",
                value_text="lot description",
            ),
            _row(
                record_kind="COLUMN_DESCRIPTION",
                asset_id=asset_id,
                field_path="obsolete",
                operation="CLEAR",
            ),
            _row(
                record_kind="DATASET_TAG",
                asset_id=asset_id,
                operation="ADD",
                controlled_ref=str(tag_id),
            ),
        ]
    )

    candidates, summary = await _parse(value, workspace_id=workspace_id)
    repeated, repeated_summary = await _parse(value, workspace_id=workspace_id)

    assert candidates == repeated
    assert summary == repeated_summary
    assert [candidate.aspect_name for candidate in candidates] == [
        CatalogMetadataAspect.SCHEMA_METADATA,
        CatalogMetadataAspect.GLOBAL_TAGS,
    ]
    assert [len(candidate.rows) for candidate in candidates] == [2, 1]
    assert summary.item_count == 3
    assert summary.candidate_count == 2
    assert summary.source_sha256 == hashlib.sha256(value).hexdigest()


@pytest.mark.asyncio
async def test_xlsx_hashes_match_shared_xlsx_compiler_and_intentionally_differ_from_csv() -> None:
    workspace_id = UUID("00000000-0000-4000-8000-000000000001")
    asset_id = UUID("00000000-0000-4000-8000-000000000101")
    rows = [
        _row(
            record_kind="COLUMN_DESCRIPTION",
            asset_id=asset_id,
            field_path="lot_id",
            operation="SET",
            value_text="lot description",
        ),
        _row(
            record_kind="DATASET_TAG",
            asset_id=asset_id,
            operation="ADD",
            controlled_ref="00000000-0000-4000-8000-000000000201",
        ),
    ]
    value = _xlsx([list(HEADERS), *rows])

    actual, summary = await _parse(value, workspace_id=workspace_id)
    expected = compile_catalog_metadata_candidates(
        workspace_id=workspace_id,
        rows=[(ordinal, row) for ordinal, row in enumerate(rows, start=1)],
        definition=CATALOG_METADATA_ROWS_XLSX_V1,
    )
    csv_candidates = compile_catalog_metadata_candidates(
        workspace_id=workspace_id,
        rows=[(ordinal, row) for ordinal, row in enumerate(rows, start=1)],
        definition=CATALOG_METADATA_ROWS_CSV_V1,
    )

    assert tuple(actual) == expected
    assert [candidate.candidate_hash for candidate in actual] == [
        "cb0ae3fbe21e5037534e49b7cb907105c61cadae4c70225a120353aac149cea8",
        "dd64b27f0274be0e069d6f8b3e3e21eec0561c19fc0a780881e75d0c17851e16",
    ]
    assert (
        summary.candidate_root_hash
        == "2885bfd16cdf90cb8f3a7e8de77273d4e434636e269af6d48cd3827ddd5629d0"
    )
    assert [candidate.candidate_hash for candidate in actual] != [
        candidate.candidate_hash for candidate in csv_candidates
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value",
    [
        b"not-a-zip",
        _xlsx([list(HEADERS)], sheet_state="hidden"),
        _xlsx([list(HEADERS)], formula_at="A1"),
        _xlsx([list(HEADERS)], hidden_row=1),
        _xlsx([list(HEADERS)], hidden_column=True),
        _xlsx([list(HEADERS)], external_relationship=True),
        _xlsx([list(HEADERS)], extra_entries={"xl/vbaProject.bin": b"macro"}),
        _xlsx([list(HEADERS)], extra_entries={"xl/embeddings/oleObject1.bin": b"ole"}),
        _xlsx([list(HEADERS)], extra_entries={"xl/unsafe.xml": b"<!DOCTYPE x>"}),
        _xlsx(
            [list(HEADERS)],
            extra_entries={"xl/media/padding.bin": b"0" * (1024 * 1024)},
        ),
    ],
)
async def test_xlsx_rejects_unsafe_active_hidden_linked_or_zip_bomb_content(
    value: bytes,
) -> None:
    with pytest.raises(CatalogMetadataParseError) as captured:
        await _parse(value)

    assert captured.value.failure_code is CatalogMetadataParseFailureCode.INVALID_XLSX_PACKAGE


@pytest.mark.asyncio
async def test_xlsx_rejects_extra_columns_and_row_limit() -> None:
    extra_column = _xlsx([[*HEADERS, "unexpected"]])
    with pytest.raises(CatalogMetadataParseError) as captured:
        await _parse(extra_column)
    assert captured.value.failure_code is CatalogMetadataParseFailureCode.INVALID_XLSX_PACKAGE

    asset_id = uuid4()
    too_many = _xlsx(
        [
            list(HEADERS),
            _row(
                record_kind="TABLE_DESCRIPTION",
                asset_id=asset_id,
                operation="SET",
                value_text="one",
            ),
            _row(
                record_kind="DATASET_TAG",
                asset_id=asset_id,
                operation="ADD",
                controlled_ref=str(uuid4()),
            ),
        ]
    )
    with pytest.raises(CatalogMetadataParseError) as row_capture:
        await _parse(
            too_many,
            definition=replace(CATALOG_METADATA_ROWS_XLSX_V1, maximum_rows=1),
        )
    assert row_capture.value.failure_code is CatalogMetadataParseFailureCode.INVALID_XLSX_PACKAGE

    oversized_row = _xlsx(
        [
            list(HEADERS),
            _row(
                record_kind="TABLE_DESCRIPTION",
                asset_id=asset_id,
                operation="SET",
                value_text="description",
            ),
        ]
    )
    with pytest.raises(CatalogMetadataParseError) as size_capture:
        await _parse(
            oversized_row,
            definition=replace(
                CATALOG_METADATA_ROWS_XLSX_V1,
                maximum_row_bytes=100,
            ),
        )
    assert size_capture.value.failure_code is CatalogMetadataParseFailureCode.INVALID_XLSX_PACKAGE


@pytest.mark.asyncio
async def test_xlsx_calls_no_consumer_when_package_or_group_validation_fails() -> None:
    asset_id = uuid4()
    value = _xlsx(
        [
            list(HEADERS),
            _row(
                record_kind="DATASET_TAG",
                asset_id=asset_id,
                operation="ADD",
                controlled_ref="00000000-0000-4000-8000-000000000201",
            ),
            _row(
                record_kind="DATASET_TAG",
                asset_id=asset_id,
                operation="ADD",
                controlled_ref="00000000-0000-4000-8000-000000000201",
            ),
        ]
    )
    consumed: list[CatalogMetadataCandidateDraft] = []

    async def consume(candidate: CatalogMetadataCandidateDraft) -> None:
        consumed.append(candidate)

    with pytest.raises(CatalogMetadataParseError) as captured:
        await parse_catalog_metadata_rows_xlsx(
            workspace_id=uuid4(),
            chunks=_chunks(value),
            expected_source_sha256=hashlib.sha256(value).hexdigest(),
            consume_candidate=consume,
        )

    assert captured.value.failure_code is CatalogMetadataParseFailureCode.DUPLICATE_SEMANTIC_KEY
    assert consumed == []


@pytest.mark.asyncio
async def test_xlsx_fails_before_consumer_on_source_hash_or_header_mismatch() -> None:
    asset_id = uuid4()
    value = _xlsx(
        [
            list(HEADERS),
            _row(
                record_kind="TABLE_DESCRIPTION",
                asset_id=asset_id,
                operation="SET",
                value_text="description",
            ),
        ]
    )
    consumed: list[CatalogMetadataCandidateDraft] = []

    async def consume(candidate: CatalogMetadataCandidateDraft) -> None:
        consumed.append(candidate)

    with pytest.raises(CatalogMetadataParseError) as hash_capture:
        await parse_catalog_metadata_rows_xlsx(
            workspace_id=uuid4(),
            chunks=_chunks(value),
            expected_source_sha256="0" * 64,
            consume_candidate=consume,
        )
    assert hash_capture.value.failure_code is CatalogMetadataParseFailureCode.SOURCE_HASH_MISMATCH

    invalid_header = _xlsx([[*HEADERS[:-1], "not_controlled_ref"]])
    with pytest.raises(CatalogMetadataParseError) as header_capture:
        await parse_catalog_metadata_rows_xlsx(
            workspace_id=uuid4(),
            chunks=_chunks(invalid_header),
            expected_source_sha256=hashlib.sha256(invalid_header).hexdigest(),
            consume_candidate=consume,
        )
    assert header_capture.value.failure_code is CatalogMetadataParseFailureCode.INVALID_HEADER
    assert consumed == []


@pytest.mark.asyncio
async def test_xlsx_package_parsing_runs_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = _xlsx(
        [
            list(HEADERS),
            _row(
                record_kind="TABLE_DESCRIPTION",
                asset_id=uuid4(),
                operation="SET",
                value_text="description",
            ),
        ]
    )
    delegated: list[object] = []

    async def to_thread(function: Callable[..., object], *args: object) -> object:
        delegated.append(function)
        return function(*args)

    monkeypatch.setattr(asyncio, "to_thread", to_thread)

    candidates, summary = await _parse(value)

    assert delegated == [typed_xlsx_upload_parser._parse_catalog_metadata_xlsx_package]
    assert len(candidates) == 1
    assert summary.item_count == 1
