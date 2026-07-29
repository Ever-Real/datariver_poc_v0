from __future__ import annotations

import io
import zipfile

import pytest

from datariver.application.knowledge_studio_document import (
    MAXIMUM_STUDIO_DOCUMENT_BYTES,
    extract_studio_document_text,
    validate_studio_document_profile,
)
from datariver.domain.common import ValidationError


def test_document_profiles_are_allowlisted_and_strip_path_components() -> None:
    name, suffix = validate_studio_document_profile(
        filename="../../스키마.csv",
        content_type="text/csv",
        size_bytes=32,
    )

    assert name == "스키마.csv"
    assert suffix == ".csv"
    with pytest.raises(ValidationError, match="not supported"):
        validate_studio_document_profile(
            filename="legacy.xls",
            content_type="application/vnd.ms-excel",
            size_bytes=32,
        )
    with pytest.raises(ValidationError, match="bounded size"):
        validate_studio_document_profile(
            filename="schema.json",
            content_type="application/json",
            size_bytes=MAXIMUM_STUDIO_DOCUMENT_BYTES + 1,
        )


@pytest.mark.parametrize(
    ("filename", "content_type", "content", "expected"),
    [
        ("schema.csv", "text/csv", "이름,설명\n데이터셋,테이블".encode(), "데이터셋"),
        (
            "schema.json",
            "application/json",
            '{"class":"데이터 자산","type":"TEXT"}'.encode(),
            "데이터 자산",
        ),
        (
            "schema.html",
            "text/html",
            b"<h1>Dataset</h1><p>description</p>",
            "description",
        ),
        (
            "schema.xml",
            "application/xml",
            "<classes><class>데이터 자산</class></classes>".encode(),
            "데이터 자산",
        ),
    ],
)
def test_text_document_extraction_preserves_unicode(
    filename: str,
    content_type: str,
    content: bytes,
    expected: str,
) -> None:
    extracted = extract_studio_document_text(
        filename=filename,
        content_type=content_type,
        content=content,
    )

    assert expected in extracted


def test_openxml_extraction_rejects_macro_and_external_payloads() -> None:
    document = io.BytesIO()
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr(
            "word/document.xml",
            "<w:document><w:body><w:p><w:t>데이터 자산</w:t></w:p></w:body></w:document>",
        )
    assert "데이터 자산" in extract_studio_document_text(
        filename="schema.docx",
        content_type=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        content=document.getvalue(),
    )

    unsafe = io.BytesIO()
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("word/document.xml", "<w:t>Dataset</w:t>")
        archive.writestr("word/vbaProject.bin", b"macro")
    with pytest.raises(ValidationError, match="Executable or external"):
        extract_studio_document_text(
            filename="unsafe.docx",
            content_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            content=unsafe.getvalue(),
        )


def test_xml_dtd_and_binary_text_fail_closed() -> None:
    with pytest.raises(ValidationError, match="DTD and entity"):
        extract_studio_document_text(
            filename="unsafe.xml",
            content_type="application/xml",
            content=b'<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><foo>&xxe;</foo>',
        )
    with pytest.raises(ValidationError, match="binary"):
        extract_studio_document_text(
            filename="unsafe.txt",
            content_type="text/plain",
            content=b"schema\x00data",
        )
