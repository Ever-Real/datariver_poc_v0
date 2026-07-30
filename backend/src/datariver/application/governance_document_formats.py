from __future__ import annotations

import html
import io
import re
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import PurePath
from xml.etree import ElementTree

from datariver.domain.common import ValidationError
from datariver.domain.governance_documents import (
    MAXIMUM_ATTACHMENT_BYTES,
    GovernanceDocumentSourceFormat,
)
from datariver.domain.governance_html import SanitizedGovernanceHtml, sanitize_governance_html

_DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_HTML_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_MARKDOWN_CONTENT_TYPES = frozenset(
    {"text/markdown", "text/x-markdown", "text/plain", "application/octet-stream"}
)
_MAXIMUM_OPENXML_ENTRIES = 5_000
_MAXIMUM_OPENXML_EXPANDED_BYTES = 64 * 1024 * 1024
_MAXIMUM_PLAIN_TEXT_CHARACTERS = 1_048_576


@dataclass(frozen=True, slots=True)
class PreparedGovernanceDocumentContent:
    source_format: GovernanceDocumentSourceFormat
    sanitized_html: str
    plain_text: str
    content_sha256: str
    sanitizer_policy_version: str
    sanitizer_policy_sha256: str


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"br", "hr"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {
            "p",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "li",
            "blockquote",
            "pre",
            "tr",
        }:
            self._parts.append("\n")
        elif tag in {"td", "th"}:
            self._parts.append(" | ")

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def value(self) -> str:
        text = "".join(self._parts)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def prepare_governance_document_html(raw_html: str) -> PreparedGovernanceDocumentContent:
    return _prepared(
        source_format=GovernanceDocumentSourceFormat.HTML,
        sanitized=sanitize_governance_html(raw_html),
    )


def prepare_governance_document_markdown(
    raw_markdown: str,
) -> PreparedGovernanceDocumentContent:
    if not isinstance(raw_markdown, str):
        raise ValidationError("Governance Markdown must be text.")
    try:
        size_bytes = len(raw_markdown.encode("utf-8"))
    except UnicodeEncodeError:
        raise ValidationError("Governance Markdown must be valid UTF-8.") from None
    if size_bytes > MAXIMUM_ATTACHMENT_BYTES:
        raise ValidationError("Governance Markdown exceeds its bounded input limit.")
    return _prepared(
        source_format=GovernanceDocumentSourceFormat.MARKDOWN,
        sanitized=sanitize_governance_html(_markdown_to_html(raw_markdown)),
    )


def prepare_governance_document_upload(
    *,
    filename: str | None,
    content_type: str | None,
    content: bytes,
) -> PreparedGovernanceDocumentContent:
    if filename is None:
        raise ValidationError("The Governance Document filename is required.")
    safe_name = PurePath(filename.replace("\\", "/")).name
    if (
        not safe_name
        or safe_name in {".", ".."}
        or len(safe_name) > 255
        or any(ord(character) < 32 or ord(character) == 127 for character in safe_name)
    ):
        raise ValidationError("The Governance Document filename is invalid.")
    if not 1 <= len(content) <= MAXIMUM_ATTACHMENT_BYTES:
        raise ValidationError("The Governance Document upload exceeds its bounded size.")
    suffix = PurePath(safe_name).suffix.lower()
    declared_type = (content_type or "").split(";", 1)[0].strip().lower()
    if suffix in {".html", ".htm"} and declared_type in _HTML_CONTENT_TYPES:
        try:
            raw_html = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ValidationError("Uploaded Governance HTML must be valid UTF-8.") from None
        return prepare_governance_document_html(raw_html)
    if suffix in {".md", ".markdown"} and declared_type in _MARKDOWN_CONTENT_TYPES:
        try:
            raw_markdown = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ValidationError("Uploaded Governance Markdown must be valid UTF-8.") from None
        return prepare_governance_document_markdown(raw_markdown)
    if suffix == ".docx" and declared_type == _DOCX_CONTENT_TYPE:
        return _prepared(
            source_format=GovernanceDocumentSourceFormat.DOCX,
            sanitized=sanitize_governance_html(_docx_to_html(content)),
        )
    raise ValidationError("The Governance Document upload type is not supported.")


def governance_document_plain_text(sanitized_html: str) -> str:
    parser = _PlainTextParser()
    parser.feed(sanitized_html)
    parser.close()
    value = parser.value()
    if not value:
        raise ValidationError("The Governance Document contains no readable text.")
    if len(value) > _MAXIMUM_PLAIN_TEXT_CHARACTERS:
        raise ValidationError("The Governance Document text exceeds its bounded contract.")
    return value


def _prepared(
    *,
    source_format: GovernanceDocumentSourceFormat,
    sanitized: SanitizedGovernanceHtml,
) -> PreparedGovernanceDocumentContent:
    return PreparedGovernanceDocumentContent(
        source_format=source_format,
        sanitized_html=sanitized.html,
        plain_text=governance_document_plain_text(sanitized.html),
        content_sha256=sanitized.content_sha256,
        sanitizer_policy_version=sanitized.policy_version,
        sanitizer_policy_sha256=sanitized.policy_sha256,
    )


def _markdown_to_html(raw: str) -> str:
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    output: list[str] = []
    paragraph: list[str] = []
    list_kind: str | None = None
    in_code = False
    code_lines: list[str] = []

    def close_paragraph() -> None:
        if paragraph:
            output.append(f"<p>{_inline_markdown(' '.join(paragraph))}</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_kind
        if list_kind is not None:
            output.append(f"</{list_kind}>")
            list_kind = None

    for line in lines:
        if line.strip().startswith("```"):
            close_paragraph()
            close_list()
            if in_code:
                output.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
                code_lines.clear()
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue
        heading = re.fullmatch(r"\s*(#{1,6})\s+(.+?)\s*", line)
        if heading is not None:
            close_paragraph()
            close_list()
            level = len(heading.group(1))
            output.append(f"<h{level}>{_inline_markdown(heading.group(2))}</h{level}>")
            continue
        list_item = re.fullmatch(r"\s*([-*+]|\d+[.)])\s+(.+?)\s*", line)
        if list_item is not None:
            close_paragraph()
            target = "ol" if list_item.group(1)[0].isdigit() else "ul"
            if list_kind != target:
                close_list()
                output.append(f"<{target}>")
                list_kind = target
            output.append(f"<li>{_inline_markdown(list_item.group(2))}</li>")
            continue
        quote = re.fullmatch(r"\s*>\s?(.*?)\s*", line)
        if quote is not None:
            close_paragraph()
            close_list()
            output.append(f"<blockquote>{_inline_markdown(quote.group(1))}</blockquote>")
            continue
        if not line.strip():
            close_paragraph()
            close_list()
            continue
        paragraph.append(line.strip())
    if in_code:
        output.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
    close_paragraph()
    close_list()
    return "".join(output)


def _inline_markdown(value: str) -> str:
    escaped = html.escape(value, quote=True)
    escaped = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"__([^_\n]+)__", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", escaped)
    escaped = re.sub(
        r"\[([^\]\n]+)\]\(([^)\n]+)\)",
        r'<a href="\2">\1</a>',
        escaped,
    )
    return escaped


def _docx_to_html(content: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > _MAXIMUM_OPENXML_ENTRIES:
                raise ValidationError("The DOCX package contains too many entries.")
            if any(
                item.filename.startswith("/")
                or ".." in PurePath(item.filename).parts
                or item.flag_bits & 0x1
                for item in entries
            ):
                raise ValidationError("The DOCX package contains an unsafe archive entry.")
            expanded = sum(item.file_size for item in entries)
            if expanded > _MAXIMUM_OPENXML_EXPANDED_BYTES:
                raise ValidationError("The DOCX package exceeds its expansion limit.")
            names = {item.filename.lower() for item in entries}
            if "word/document.xml" not in names or any(
                name.endswith((".bin", ".vba", ".exe", ".dll"))
                or "vbaproject" in name
                or "externallinks/" in name
                or name.startswith("word/embeddings/")
                for name in names
            ):
                raise ValidationError("The DOCX package contains unsupported active content.")
            document_name = next(
                item.filename for item in entries if item.filename.lower() == "word/document.xml"
            )
            document_xml = archive.read(document_name)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, KeyError):
        raise ValidationError("The Governance DOCX package is invalid.") from None
    lowered = document_xml[:16_384].lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise ValidationError("DTD and entity declarations are not accepted in DOCX.")
    try:
        root = ElementTree.fromstring(document_xml)  # noqa: S314 - DTD/entity rejected above
    except ElementTree.ParseError:
        raise ValidationError("The Governance DOCX document XML is invalid.") from None
    paragraphs: list[str] = []
    for paragraph in root.iter():
        if _local_name(paragraph.tag) != "p":
            continue
        values: list[str] = []
        for node in paragraph.iter():
            node_name = _local_name(node.tag)
            if node_name == "t":
                values.append(node.text or "")
            elif node_name == "tab":
                values.append("\t")
            elif node_name == "br":
                values.append("\n")
        text = "".join(values)
        normalized = re.sub(r"[ \t]+", " ", text).strip()
        if normalized:
            paragraphs.append(f"<p>{html.escape(normalized)}</p>")
    if not paragraphs:
        raise ValidationError("The Governance DOCX contains no extractable text.")
    return "".join(paragraphs)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()
