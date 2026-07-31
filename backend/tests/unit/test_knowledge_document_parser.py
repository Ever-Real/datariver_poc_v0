from __future__ import annotations

import io
import zipfile

import pytest

from datariver.domain.common import ValidationError
from datariver.infrastructure.knowledge.document import BoundedKnowledgeDocumentParser


def test_text_document_is_split_into_ordered_bounded_evidence_segments() -> None:
    parser = BoundedKnowledgeDocumentParser()
    content = ("데이터 자산 설명\n" * 12_000).encode()

    pages = parser.parse(content, media_type="text/plain")

    assert len(pages) >= 2
    assert tuple(page.page_number for page in pages) == tuple(range(1, len(pages) + 1))
    assert all(len(page.text) <= 80_000 for page in pages)
    assert "데이터 자산" in pages[0].text


def test_docx_source_uses_safe_openxml_text_extraction() -> None:
    document = io.BytesIO()
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr(
            "word/document.xml",
            "<w:document><w:body><w:p><w:t>고객 자산</w:t></w:p></w:body></w:document>",
        )

    pages = BoundedKnowledgeDocumentParser().parse(
        document.getvalue(),
        media_type=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    )

    assert len(pages) == 1
    assert "고객 자산" in pages[0].text


def test_document_parser_rejects_unsupported_or_unsafe_sources() -> None:
    parser = BoundedKnowledgeDocumentParser()

    with pytest.raises(ValidationError, match="not supported"):
        parser.parse(b"legacy", media_type="application/msword")
    with pytest.raises(ValidationError, match="DTD and entity"):
        parser.parse(
            b'<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><foo>&xxe;</foo>',
            media_type="application/xml",
        )
