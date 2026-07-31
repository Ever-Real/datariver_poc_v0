from __future__ import annotations

from typing import BinaryIO

from datariver.application.knowledge_studio_document import (
    extract_studio_document_text,
)
from datariver.domain.common import ValidationError
from datariver.domain.knowledge_pipeline import (
    MAX_PAGE_CHARACTERS,
    MAX_SOURCE_BYTES,
    MAX_TOTAL_PAGE_CHARACTERS,
    PdfPage,
    supported_knowledge_source_media_types,
)
from datariver.infrastructure.knowledge.pdf import PypdfPageAwareParser

_FILENAME_BY_MEDIA_TYPE = {
    "text/csv": "source.csv",
    "text/plain": "source.txt",
    "application/json": "source.json",
    "text/json": "source.json",
    "application/xml": "source.xml",
    "text/xml": "source.xml",
    "text/html": "source.html",
    "application/xhtml+xml": "source.html",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "source.docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "source.xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "source.pptx",
}
_CHUNK_CHARACTERS = min(80_000, MAX_PAGE_CHARACTERS)


class BoundedKnowledgeDocumentParser:
    """Parse an allowlisted immutable source into bounded evidence segments.

    PDF keeps physical page boundaries. Other accepted formats are converted to
    deterministic text segments; no browser-supplied parser, URL or query reaches
    this adapter.
    """

    def __init__(self) -> None:
        self._pdf = PypdfPageAwareParser()

    def parse(self, payload: bytes, *, media_type: str) -> tuple[PdfPage, ...]:
        if media_type not in supported_knowledge_source_media_types():
            raise ValidationError("The Knowledge source document type is not supported.")
        if not 0 < len(payload) <= MAX_SOURCE_BYTES:
            raise ValidationError("The Knowledge source document exceeds its bounded size.")
        if media_type == "application/pdf":
            return self._pdf.parse(payload)
        filename = _FILENAME_BY_MEDIA_TYPE.get(media_type)
        if filename is None:
            raise ValidationError("The Knowledge source document type is not supported.")
        text = extract_studio_document_text(
            filename=filename,
            content_type=media_type,
            content=payload,
            maximum_characters=MAX_TOTAL_PAGE_CHARACTERS,
            maximum_bytes=MAX_SOURCE_BYTES,
        )
        pages = tuple(
            PdfPage.create(
                page_number=index + 1,
                text=text[offset : offset + _CHUNK_CHARACTERS],
            )
            for index, offset in enumerate(range(0, len(text), _CHUNK_CHARACTERS))
        )
        if not pages:
            raise ValidationError("The Knowledge source document contains no extractable text.")
        return pages

    def parse_stream(
        self,
        source: BinaryIO,
        *,
        media_type: str,
    ) -> tuple[PdfPage, ...]:
        payload = source.read(MAX_SOURCE_BYTES + 1)
        if len(payload) > MAX_SOURCE_BYTES or source.read(1):
            raise ValidationError("The Knowledge source document exceeds its bounded size.")
        return self.parse(payload, media_type=media_type)
