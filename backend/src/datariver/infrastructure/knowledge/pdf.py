from __future__ import annotations

import importlib
from collections.abc import Callable, Sequence
from io import BytesIO
from typing import BinaryIO, Protocol, cast

from datariver.domain.common import ValidationError
from datariver.domain.knowledge_pipeline import MAX_PDF_PAGES, PdfPage


class PdfLibraryPage(Protocol):
    def extract_text(self) -> str | None: ...


class PdfLibraryReader(Protocol):
    @property
    def is_encrypted(self) -> bool: ...

    @property
    def pages(self) -> Sequence[PdfLibraryPage]: ...


ReaderFactory = Callable[[BinaryIO], PdfLibraryReader]


def _pypdf_reader(source: BinaryIO) -> PdfLibraryReader:
    try:
        module = importlib.import_module("pypdf")
    except ModuleNotFoundError as error:
        raise RuntimeError("The pypdf runtime dependency is required for PDF ingestion.") from error
    reader_type = getattr(module, "PdfReader", None)
    if reader_type is None:
        raise RuntimeError("The installed pypdf package does not provide PdfReader.")
    return cast(PdfLibraryReader, reader_type(source, strict=True))


class PypdfPageAwareParser:
    """Extracts ordered page text without fetching URLs or executing document content."""

    def __init__(
        self,
        *,
        reader_factory: ReaderFactory = _pypdf_reader,
        maximum_pages: int = MAX_PDF_PAGES,
    ) -> None:
        if not 1 <= maximum_pages <= MAX_PDF_PAGES:
            raise ValueError("maximum_pages is outside the governed PDF limit")
        self._reader_factory = reader_factory
        self._maximum_pages = maximum_pages

    def parse(self, payload: bytes) -> tuple[PdfPage, ...]:
        return self.parse_stream(BytesIO(payload))

    def parse_stream(self, source: BinaryIO) -> tuple[PdfPage, ...]:
        source.seek(0)
        if source.read(5) != b"%PDF-":
            raise ValidationError("The knowledge source is not a PDF document.")
        source.seek(0)
        try:
            reader = self._reader_factory(source)
        except ValidationError:
            raise
        except Exception as error:
            raise ValidationError("The PDF document could not be parsed safely.") from error
        if reader.is_encrypted:
            raise ValidationError(
                "Encrypted PDF documents are not accepted for knowledge ingestion."
            )
        if not reader.pages or len(reader.pages) > self._maximum_pages:
            raise ValidationError("The PDF page count is outside the governed limit.")
        pages: list[PdfPage] = []
        for index, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as error:
                raise ValidationError(f"PDF page {index} text extraction failed.") from error
            pages.append(PdfPage.create(page_number=index, text=text))
        if not any(page.text for page in pages):
            raise ValidationError("The PDF contains no extractable text.")
        return tuple(pages)
