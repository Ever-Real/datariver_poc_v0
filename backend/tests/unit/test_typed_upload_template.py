import csv
import re
from io import BytesIO, TextIOWrapper
from zipfile import ZipFile

import pytest

from datariver.application.typed_upload_profiles import (
    CATALOG_METADATA_ROWS_CSV_V1,
    CATALOG_METADATA_ROWS_XLSX_V1,
)
from datariver.application.typed_upload_template import encode_typed_upload_template


def test_csv_template_is_bom_prefixed_and_uses_the_registered_exact_header() -> None:
    content, filename = encode_typed_upload_template(CATALOG_METADATA_ROWS_CSV_V1)

    assert content.startswith(b"\xef\xbb\xbf")
    reader = csv.reader(TextIOWrapper(BytesIO(content), encoding="utf-8-sig", newline=""))
    assert tuple(next(reader)) == CATALOG_METADATA_ROWS_CSV_V1.headers
    with pytest.raises(StopIteration):
        next(reader)
    assert filename.endswith(".csv")


def test_xlsx_template_is_deterministic_header_only_registered_workbook() -> None:
    first, filename = encode_typed_upload_template(CATALOG_METADATA_ROWS_XLSX_V1)
    second, _ = encode_typed_upload_template(CATALOG_METADATA_ROWS_XLSX_V1)

    assert first == second
    assert filename.endswith(".xlsx")
    with ZipFile(BytesIO(first)) as package:
        worksheet = package.read("xl/worksheets/sheet1.xml").decode("utf-8")
    values = re.findall(r"<t>([^<]*)</t>", worksheet)
    assert worksheet.count("<row ") == 1
    assert tuple(values) == CATALOG_METADATA_ROWS_XLSX_V1.headers
