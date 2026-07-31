from __future__ import annotations

import io
import zipfile

import pytest

from datariver.application.governance_document_formats import (
    prepare_governance_document_upload,
)
from datariver.domain.common import ValidationError
from datariver.domain.governance_documents import GovernanceDocumentSourceFormat

DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_html_upload_is_sanitized_and_keeps_only_readable_content() -> None:
    prepared = prepare_governance_document_upload(
        filename="policy.html",
        content_type="text/html; charset=utf-8",
        content=(b"<script>alert('xss')</script><h2 onclick=\"bad()\">Policy</h2><p>safe</p>"),
    )

    assert prepared.source_format is GovernanceDocumentSourceFormat.HTML
    assert prepared.sanitized_html == "<h2>Policy</h2><p>safe</p>"
    assert prepared.plain_text == "Policy\nsafe"
    assert "script" not in prepared.sanitized_html
    assert "onclick" not in prepared.sanitized_html


def test_markdown_upload_converts_bounded_markup_before_sanitization() -> None:
    prepared = prepare_governance_document_upload(
        filename="policy.md",
        content_type="text/markdown",
        content=(
            b"# Retention\n\n"
            b"**Orders** are retained for 730 days. "
            b"[unsafe link](http://example.invalid)"
        ),
    )

    assert prepared.source_format is GovernanceDocumentSourceFormat.MARKDOWN
    assert prepared.sanitized_html == (
        "<h1>Retention</h1><p><strong>Orders</strong> are retained for 730 days. "
        "<a>unsafe link</a></p>"
    )
    assert prepared.plain_text == ("Retention\nOrders are retained for 730 days. unsafe link")


def test_docx_upload_extracts_text_and_escapes_document_xml_values() -> None:
    prepared = prepare_governance_document_upload(
        filename="policy.docx",
        content_type=DOCX_CONTENT_TYPE,
        content=_docx(
            """
            <w:p><w:r><w:t>Policy &amp; &lt;scope&gt;</w:t></w:r></w:p>
            <w:p><w:r><w:t>730 days</w:t></w:r></w:p>
            """
        ),
    )

    assert prepared.source_format is GovernanceDocumentSourceFormat.DOCX
    assert prepared.sanitized_html == ("<p>Policy &amp; &lt;scope&gt;</p><p>730 days</p>")
    assert prepared.plain_text == "Policy & <scope>\n730 days"


def test_docx_upload_rejects_active_content() -> None:
    with pytest.raises(ValidationError, match="unsupported active content"):
        prepare_governance_document_upload(
            filename="policy.docx",
            content_type=DOCX_CONTENT_TYPE,
            content=_docx(
                "<w:p><w:r><w:t>Policy</w:t></w:r></w:p>",
                active_content=True,
            ),
        )


def _docx(body: str, *, active_content: bool = False) -> bytes:
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body>"
        "</w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document)
        if active_content:
            archive.writestr("word/vbaProject.bin", b"active-content")
    return buffer.getvalue()
