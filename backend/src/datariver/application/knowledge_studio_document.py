from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from html.parser import HTMLParser
from pathlib import PurePath

from pypdf import PdfReader

from datariver.domain.common import ValidationError

MAXIMUM_STUDIO_DOCUMENT_BYTES = 10 * 1024 * 1024
MAXIMUM_STUDIO_DOCUMENT_EXTRACTED_CHARACTERS = 3_200
MAXIMUM_OPENXML_ENTRIES = 5_000
MAXIMUM_OPENXML_EXPANDED_BYTES = 64 * 1024 * 1024

_PROFILES: dict[str, frozenset[str]] = {
    ".pdf": frozenset({"application/pdf"}),
    ".csv": frozenset({"text/csv", "application/csv", "text/plain"}),
    ".txt": frozenset({"text/plain"}),
    ".xlsx": frozenset({"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}),
    ".docx": frozenset({"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}),
    ".pptx": frozenset(
        {"application/vnd.openxmlformats-officedocument.presentationml.presentation"}
    ),
    ".html": frozenset({"text/html", "application/xhtml+xml"}),
    ".htm": frozenset({"text/html", "application/xhtml+xml"}),
    ".xml": frozenset({"application/xml", "text/xml"}),
    ".json": frozenset({"application/json", "text/json"}),
}


class _TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.values: list[str] = []

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if value:
            self.values.append(value)


def validate_studio_document_profile(
    *,
    filename: str | None,
    content_type: str | None,
    size_bytes: int,
    maximum_bytes: int = MAXIMUM_STUDIO_DOCUMENT_BYTES,
) -> tuple[str, str]:
    if not 1 <= maximum_bytes <= 50 * 1024 * 1024:
        raise ValidationError("The Studio document size bound is invalid.")
    if filename is None:
        raise ValidationError("The Studio document filename is required.")
    safe_name = PurePath(filename.replace("\\", "/")).name
    if (
        not safe_name
        or safe_name in {".", ".."}
        or len(safe_name) > 255
        or any(ord(character) < 32 or ord(character) == 127 for character in safe_name)
    ):
        raise ValidationError("The Studio document filename is invalid.")
    suffix = PurePath(safe_name).suffix.lower()
    accepted_types = _PROFILES.get(suffix)
    declared_type = (content_type or "").split(";", 1)[0].strip().lower()
    if accepted_types is None or declared_type not in accepted_types:
        raise ValidationError("The Studio document type is not supported.")
    if not 1 <= size_bytes <= maximum_bytes:
        raise ValidationError("The Studio document exceeds its bounded size profile.")
    return safe_name, suffix


def extract_studio_document_text(
    *,
    filename: str,
    content_type: str,
    content: bytes,
    maximum_characters: int = MAXIMUM_STUDIO_DOCUMENT_EXTRACTED_CHARACTERS,
    maximum_bytes: int = MAXIMUM_STUDIO_DOCUMENT_BYTES,
) -> str:
    if not 1 <= maximum_characters <= 5_000_000:
        raise ValidationError("The Studio document extraction bound is invalid.")
    _, suffix = validate_studio_document_profile(
        filename=filename,
        content_type=content_type,
        size_bytes=len(content),
        maximum_bytes=maximum_bytes,
    )
    try:
        if suffix == ".pdf":
            text = _extract_pdf(content)
        elif suffix in {".docx", ".xlsx", ".pptx"}:
            text = _extract_openxml(content, suffix)
        elif suffix in {".html", ".htm"}:
            parser = _TextHTMLParser()
            parser.feed(_decode_text(content))
            text = "\n".join(parser.values)
        elif suffix == ".xml":
            text = _extract_xml_text(content)
        elif suffix == ".json":
            document = json.loads(_decode_text(content))
            text = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
        elif suffix == ".csv":
            rows = csv.reader(io.StringIO(_decode_text(content)))
            text = "\n".join(" | ".join(cell.strip() for cell in row) for row in rows)
        else:
            text = _decode_text(content)
    except (UnicodeDecodeError, ValueError, zipfile.BadZipFile) as error:
        raise ValidationError("The Studio document could not be parsed safely.") from error
    normalized = re.sub(r"[ \t]+", " ", text)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    if not normalized:
        raise ValidationError("The Studio document contains no extractable text.")
    return normalized[:maximum_characters]


def _decode_text(content: bytes) -> str:
    if b"\x00" in content:
        raise ValidationError("The Studio text document contains binary content.")
    return content.decode("utf-8-sig")


def _extract_pdf(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    if len(reader.pages) > 500:
        raise ValidationError("The Studio PDF exceeds the governed page limit.")
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _extract_xml_text(content: bytes) -> str:
    lowered = content[:8_192].lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise ValidationError("DTD and entity declarations are not accepted.")
    parser = _TextHTMLParser()
    parser.feed(_decode_text(content))
    return "\n".join(parser.values)


def _extract_openxml(content: bytes, suffix: str) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        entries = archive.infolist()
        if len(entries) > MAXIMUM_OPENXML_ENTRIES:
            raise ValidationError("The OpenXML document contains too many archive entries.")
        expanded = sum(item.file_size for item in entries)
        if expanded > MAXIMUM_OPENXML_EXPANDED_BYTES:
            raise ValidationError("The OpenXML document exceeds its expansion limit.")
        lowered_names = {item.filename.lower() for item in entries}
        if any(
            name.endswith((".bin", ".vba", ".exe", ".dll"))
            or "vbaproject" in name
            or "externallinks/" in name
            for name in lowered_names
        ):
            raise ValidationError("Executable or external OpenXML content is not accepted.")
        prefixes = {
            ".docx": ("word/document.xml", "word/header", "word/footer"),
            ".xlsx": ("xl/sharedstrings.xml", "xl/worksheets/"),
            ".pptx": ("ppt/slides/", "ppt/notesSlides/"),
        }[suffix]
        values: list[str] = []
        read_bytes = 0
        for item in entries:
            name = item.filename.lower()
            if not any(name.startswith(prefix.lower()) for prefix in prefixes):
                continue
            read_bytes += item.file_size
            if read_bytes > MAXIMUM_OPENXML_EXPANDED_BYTES:
                raise ValidationError("The OpenXML text payload exceeds its bounded limit.")
            values.append(_extract_xml_text(archive.read(item)))
        return "\n".join(values)
