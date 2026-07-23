from __future__ import annotations

# OOXML relationship and content-type identifiers are protocol literals.
# ruff: noqa: E501
import csv
from io import BytesIO, StringIO
from typing import Final
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from datariver.application.typed_upload_profiles import TypedUploadProfileDefinition
from datariver.domain.common import ValidationError

_MAXIMUM_TEMPLATE_BYTES: Final = 64 * 1024
_FIXED_ZIP_TIMESTAMP: Final = (1980, 1, 1, 0, 0, 0)


def encode_typed_upload_template(
    definition: TypedUploadProfileDefinition,
) -> tuple[bytes, str]:
    """Render the exact registered header in its selected transport format."""

    if definition.filename_suffix == ".csv":
        stream = StringIO(newline="")
        csv.writer(stream, lineterminator="\r\n").writerow(definition.headers)
        content = b"\xef\xbb\xbf" + stream.getvalue().encode("utf-8")
    elif definition.filename_suffix == ".xlsx":
        content = _encode_header_only_xlsx(definition.headers)
    else:
        raise ValidationError("The typed upload profile has no supported template format.")
    if len(content) > _MAXIMUM_TEMPLATE_BYTES:
        raise RuntimeError("The registered upload template exceeds its fixed byte boundary.")
    filename = (
        f"datariver-{definition.content_profile.value.casefold()}{definition.filename_suffix}"
    )
    return content, filename


def _encode_header_only_xlsx(headers: tuple[str, ...]) -> bytes:
    cells = "".join(
        (f'<c r="{_column_name(index)}1" t="inlineStr"><is><t>{escape(value)}</t></is></c>')
        for index, value in enumerate(headers, start=1)
    )
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData><row r="1">{cells}</row></sheetData></worksheet>'
    )
    stream = BytesIO()
    with ZipFile(stream, mode="w", compression=ZIP_DEFLATED, compresslevel=9) as package:
        for path, content in (
            ("[Content_Types].xml", _CONTENT_TYPES),
            ("_rels/.rels", _ROOT_RELATIONSHIPS),
            ("xl/workbook.xml", _WORKBOOK),
            ("xl/_rels/workbook.xml.rels", _WORKBOOK_RELATIONSHIPS),
            ("xl/styles.xml", _STYLES),
            ("xl/worksheets/sheet1.xml", worksheet),
        ):
            info = ZipInfo(path, date_time=_FIXED_ZIP_TIMESTAMP)
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            package.writestr(info, content)
    return stream.getvalue()


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
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="DataRiver Metadata" sheetId="1" r:id="rId1"/></sheets></workbook>"""
_WORKBOOK_RELATIONSHIPS: Final = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>"""
_STYLES: Final = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts><fills count="1"><fill><patternFill patternType="none"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="1"><xf xfId="0"/></cellXfs></styleSheet>"""
