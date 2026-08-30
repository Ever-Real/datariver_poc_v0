from __future__ import annotations

import csv
from io import StringIO
from uuid import UUID

import pytest

from datariver.application.catalog_export_csv import (
    CATALOG_EXPORT_CSV_HEADERS,
    CSV_SAFETY_VERSION,
    MAXIMUM_CSV_RECORD_BYTES,
    CatalogExportCsvRow,
    catalog_export_csv_header,
    encode_catalog_export_csv_row,
    iter_catalog_export_csv,
)
from datariver.domain.common import ValidationError

ASSET_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def _row(**changes: object) -> CatalogExportCsvRow:
    values: dict[str, object] = {
        "asset_id": ASSET_ID,
        "external_urn": "urn:li:dataset:(urn:li:dataPlatform:postgres,core.wafer,PROD)",
        "platform": "postgres",
        "database_name": "core",
        "schema_name": "semiconductor",
        "name": "wafer",
        "asset_type": "DATASET",
        "classification": "INTERNAL",
        "lifecycle": "ACTIVE",
        "description": '웨이퍼, lot "A"\n두 번째 줄',
        "source_version": "v1",
        "observed_at": "2026-07-17T01:02:03Z",
    }
    values.update(changes)
    return CatalogExportCsvRow(**values)  # type: ignore[arg-type]


def _parse(chunks: list[bytes]) -> list[list[str]]:
    return list(csv.reader(StringIO(b"".join(chunks).decode("utf-8-sig"), newline="")))


def test_catalog_export_csv_has_fixed_schema_utf8_and_rfc4180_escaping() -> None:
    chunks = list(iter_catalog_export_csv([_row()]))

    assert CSV_SAFETY_VERSION == "csv-safe-v1"
    assert chunks[0] == b"\xef\xbb\xbf" + (
        ",".join(CATALOG_EXPORT_CSV_HEADERS) + "\r\n"
    ).encode()
    assert all(chunk.endswith(b"\r\n") for chunk in chunks)
    assert len(chunks) == 2
    assert _parse(chunks) == [
        list(CATALOG_EXPORT_CSV_HEADERS),
        [
            str(ASSET_ID),
            "urn:li:dataset:(urn:li:dataPlatform:postgres,core.wafer,PROD)",
            "postgres",
            "core",
            "semiconductor",
            "wafer",
            "DATASET",
            "INTERNAL",
            "ACTIVE",
            '웨이퍼, lot "A"\n두 번째 줄',
            "v1",
            "2026-07-17T01:02:03Z",
        ],
    ]


def test_catalog_export_csv_header_is_deterministic_crlf_record() -> None:
    first = catalog_export_csv_header()

    assert first == catalog_export_csv_header()
    assert first == (",".join(CATALOG_EXPORT_CSV_HEADERS) + "\r\n").encode("utf-8")
    assert first.endswith(b"\r\n")


def test_single_row_encoder_matches_iterator_formula_safety_and_crlf() -> None:
    row = _row(name='  =HYPERLINK("https://invalid.example")')

    encoded = encode_catalog_export_csv_row(row)

    assert encoded == encode_catalog_export_csv_row(row)
    assert encoded == list(iter_catalog_export_csv([row]))[1]
    assert encoded.endswith(b"\r\n")
    name_index = CATALOG_EXPORT_CSV_HEADERS.index("name")
    assert next(csv.reader(StringIO(encoded.decode("utf-8"), newline="")))[name_index] == (
        '\'  =HYPERLINK("https://invalid.example")'
    )


def test_single_row_encoder_rejects_nul() -> None:
    with pytest.raises(ValidationError, match="NUL") as error:
        encode_catalog_export_csv_row(_row(name="invalid\x00name"))
    assert error.value.details["code"] == "EXPORT_CSV_INVALID_VALUE"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ('=HYPERLINK("https://invalid.example")', '\'=HYPERLINK("https://invalid.example")'),
        ("  +cmd|' /C calc'!A0", "'  +cmd|' /C calc'!A0"),
        ("\t=1+1", "'\t=1+1"),
        ("\r-command", "'\r-command"),
        ("\n@SUM(A1:A2)", "'\n@SUM(A1:A2)"),
        ("ordinary - embedded", "ordinary - embedded"),
    ],
)
def test_catalog_export_csv_neutralizes_formula_capable_values(value: str, expected: str) -> None:
    parsed = _parse(list(iter_catalog_export_csv([_row(name=value)])))

    name_index = CATALOG_EXPORT_CSV_HEADERS.index("name")
    assert parsed[1][name_index] == expected


def test_catalog_export_csv_serializes_nullable_values_as_empty_cells() -> None:
    parsed = _parse(
        list(
            iter_catalog_export_csv(
                [_row(platform=None, database_name=None, schema_name=None, description=None)]
            )
        )
    )

    assert parsed[1][2:5] == ["", "", ""]
    assert parsed[1][9] == ""


def test_catalog_export_csv_rejects_nul_instead_of_sanitizing_it() -> None:
    chunks = iter_catalog_export_csv([_row(description="hidden\x00suffix")])

    assert next(chunks).startswith(b"\xef\xbb\xbfasset_id,")
    with pytest.raises(ValidationError, match="NUL"):
        next(chunks)


def test_catalog_export_csv_rejects_an_unbounded_individual_record() -> None:
    with pytest.raises(ValidationError, match="safety limit") as error:
        encode_catalog_export_csv_row(_row(description="x" * MAXIMUM_CSV_RECORD_BYTES))

    assert error.value.details["code"] == "EXPORT_CSV_RECORD_LIMIT"


def test_catalog_export_csv_output_and_row_chunking_are_deterministic() -> None:
    rows = [_row(name="first"), _row(name="second", platform=None)]

    first = list(iter_catalog_export_csv(rows))
    second = list(iter_catalog_export_csv(iter(rows)))

    assert first == second
    assert len(first) == 1 + len(rows)
    assert first[1] != first[2]
    assert first[0].startswith(b"\xef\xbb\xbf")
