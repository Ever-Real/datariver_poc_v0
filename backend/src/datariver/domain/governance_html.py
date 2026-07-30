from __future__ import annotations

import hashlib
import html
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from typing import Final
from urllib.parse import urlsplit

from datariver.domain.common import ValidationError, canonical_json_hash

GOVERNANCE_HTML_SANITIZER_POLICY_VERSION: Final = "GOVERNANCE_HTML_SANITIZER_V1"

_ALLOWED_TAGS: Final = frozenset(
    {
        "a",
        "blockquote",
        "br",
        "code",
        "em",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "li",
        "ol",
        "p",
        "pre",
        "s",
        "strong",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "u",
        "ul",
    }
)
_TAG_ALIASES: Final = {"b": "strong", "i": "em"}
_ALLOWED_ATTRIBUTES: Final = {
    "a": frozenset({"href", "title"}),
    "ol": frozenset({"start"}),
    "td": frozenset({"colspan", "rowspan"}),
    "th": frozenset({"colspan", "rowspan", "scope"}),
}
_ALLOWED_URL_SCHEMES: Final = frozenset({"https"})
_DROP_CONTENT_TAGS: Final = frozenset(
    {
        "applet",
        "area",
        "audio",
        "base",
        "button",
        "canvas",
        "details",
        "dialog",
        "embed",
        "fieldset",
        "form",
        "frame",
        "frameset",
        "head",
        "iframe",
        "img",
        "input",
        "legend",
        "link",
        "map",
        "math",
        "meta",
        "noframes",
        "noscript",
        "object",
        "optgroup",
        "option",
        "picture",
        "plaintext",
        "script",
        "select",
        "source",
        "style",
        "summary",
        "svg",
        "template",
        "textarea",
        "track",
        "video",
        "xmp",
    }
)
_HTML_VOID_TAGS: Final = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
_OUTPUT_VOID_TAGS: Final = frozenset({"br", "hr"})
_BLOCKED_ATTRIBUTES: Final = frozenset({"id", "name", "src", "srcdoc", "style"})


class GovernanceHtmlSanitizationError(ValidationError):
    """A bounded, structured failure that never carries submitted HTML."""

    code = "governance_html_invalid"


@dataclass(frozen=True, slots=True)
class GovernanceHtmlLimits:
    max_input_bytes: int = 1_048_576
    max_output_bytes: int = 1024 * 1024
    max_nodes: int = 10_000
    max_depth: int = 32
    max_links: int = 512
    max_tables: int = 64
    max_table_cells: int = 4_096
    max_attribute_characters: int = 2_048

    def __post_init__(self) -> None:
        if any(value < 1 for value in asdict(self).values()):
            raise ValueError("Governance HTML limits must be positive.")


DEFAULT_GOVERNANCE_HTML_LIMITS: Final = GovernanceHtmlLimits()


@dataclass(frozen=True, slots=True)
class SanitizedGovernanceHtml:
    html: str
    content_sha256: str
    policy_version: str
    policy_sha256: str


def governance_html_sha256(canonical_html: str) -> str:
    """Hash canonical, sanitized UTF-8 HTML for DB/object reconciliation."""

    try:
        encoded = canonical_html.encode("utf-8")
    except UnicodeEncodeError:
        raise GovernanceHtmlSanitizationError(
            "Governance HTML is not valid UTF-8 text.",
            details={"code": "HTML_ENCODING_INVALID"},
        ) from None
    return hashlib.sha256(encoded).hexdigest()


def governance_html_policy_sha256(
    limits: GovernanceHtmlLimits = DEFAULT_GOVERNANCE_HTML_LIMITS,
) -> str:
    return canonical_json_hash(
        {
            "allowed_attributes": {
                tag: sorted(attributes) for tag, attributes in sorted(_ALLOWED_ATTRIBUTES.items())
            },
            "allowed_tags": sorted(_ALLOWED_TAGS),
            "allowed_url_schemes": sorted(_ALLOWED_URL_SCHEMES),
            "blocked_attributes": sorted(_BLOCKED_ATTRIBUTES),
            "drop_content_tags": sorted(_DROP_CONTENT_TAGS),
            "limits": asdict(limits),
            "policy_version": GOVERNANCE_HTML_SANITIZER_POLICY_VERSION,
            "tag_aliases": dict(sorted(_TAG_ALIASES.items())),
        }
    )


GOVERNANCE_HTML_SANITIZER_POLICY_SHA256: Final = governance_html_policy_sha256()


def sanitize_governance_html(
    raw_html: str,
    *,
    limits: GovernanceHtmlLimits = DEFAULT_GOVERNANCE_HTML_LIMITS,
) -> SanitizedGovernanceHtml:
    if not isinstance(raw_html, str):
        raise GovernanceHtmlSanitizationError(
            "Governance HTML must be text.",
            details={"code": "HTML_TYPE_INVALID"},
        )
    try:
        encoded = raw_html.encode("utf-8")
    except UnicodeEncodeError:
        raise GovernanceHtmlSanitizationError(
            "Governance HTML is not valid UTF-8 text.",
            details={"code": "HTML_ENCODING_INVALID"},
        ) from None
    if len(encoded) > limits.max_input_bytes:
        _raise_limit("HTML_INPUT_BYTE_LIMIT", limits.max_input_bytes)
    if any(_is_forbidden_control(character) for character in raw_html):
        raise GovernanceHtmlSanitizationError(
            "Governance HTML contains a prohibited control character.",
            details={"code": "HTML_CONTROL_CHARACTER"},
        )

    parser = _GovernanceHtmlCanonicalizer(limits)
    normalized = raw_html.replace("\r\n", "\n").replace("\r", "\n")
    try:
        parser.feed(normalized)
        parser.close()
    except GovernanceHtmlSanitizationError:
        raise
    except (AssertionError, ValueError):
        raise GovernanceHtmlSanitizationError(
            "Governance HTML could not be parsed.",
            details={"code": "HTML_PARSE_INVALID"},
        ) from None
    canonical = parser.canonical_html()
    return SanitizedGovernanceHtml(
        html=canonical,
        content_sha256=governance_html_sha256(canonical),
        policy_version=GOVERNANCE_HTML_SANITIZER_POLICY_VERSION,
        policy_sha256=governance_html_policy_sha256(limits),
    )


class _GovernanceHtmlCanonicalizer(HTMLParser):
    def __init__(self, limits: GovernanceHtmlLimits) -> None:
        super().__init__(convert_charrefs=True)
        self._limits = limits
        self._pieces: list[str] = []
        self._output_bytes = 0
        self._node_count = 0
        self._link_count = 0
        self._table_count = 0
        self._table_cell_count = 0
        self._input_stack: list[str] = []
        self._output_stack: list[str] = []
        self._drop_stack: list[str] = []
        self._finished = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self._start(tag, attrs, self_closing=False)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self._start(tag, attrs, self_closing=True)

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        self._close_input_tag(normalized_tag)
        if self._drop_stack:
            self._close_drop_tag(normalized_tag)
            return
        canonical_tag = _TAG_ALIASES.get(normalized_tag, normalized_tag)
        if canonical_tag not in _ALLOWED_TAGS or canonical_tag in _OUTPUT_VOID_TAGS:
            return
        self._close_output_tag(canonical_tag)

    def handle_data(self, data: str) -> None:
        if not data:
            return
        self._count_node()
        if self._drop_stack:
            return
        self._emit(html.escape(data, quote=False))

    def handle_comment(self, data: str) -> None:
        del data
        self._count_node()

    def handle_decl(self, decl: str) -> None:
        del decl
        self._count_node()

    def handle_pi(self, data: str) -> None:
        del data
        self._count_node()

    def unknown_decl(self, data: str) -> None:
        del data
        self._count_node()

    def canonical_html(self) -> str:
        if not self._finished:
            while self._output_stack:
                self._emit(f"</{self._output_stack.pop()}>")
            self._finished = True
        return "".join(self._pieces)

    def _start(
        self,
        tag: str,
        attrs: Sequence[tuple[str, str | None]],
        *,
        self_closing: bool,
    ) -> None:
        normalized_tag = tag.lower()
        is_void = normalized_tag in _HTML_VOID_TAGS
        self._count_node()
        if not self_closing and not is_void:
            self._input_stack.append(normalized_tag)
            if len(self._input_stack) > self._limits.max_depth:
                _raise_limit("HTML_DEPTH_LIMIT", self._limits.max_depth)

        if self._drop_stack:
            if not self_closing and not is_void:
                self._drop_stack.append(normalized_tag)
            return
        if normalized_tag in _DROP_CONTENT_TAGS:
            if not self_closing and not is_void:
                self._drop_stack.append(normalized_tag)
            return

        canonical_tag = _TAG_ALIASES.get(normalized_tag, normalized_tag)
        if canonical_tag not in _ALLOWED_TAGS:
            return
        self._count_special_tag(canonical_tag)
        serialized_attributes = self._sanitize_attributes(canonical_tag, attrs)
        opening = f"<{canonical_tag}{serialized_attributes}>"
        self._emit(opening)
        if canonical_tag in _OUTPUT_VOID_TAGS:
            return
        if self_closing:
            self._emit(f"</{canonical_tag}>")
            return
        self._output_stack.append(canonical_tag)

    def _sanitize_attributes(
        self,
        tag: str,
        attrs: Sequence[tuple[str, str | None]],
    ) -> str:
        allowed = _ALLOWED_ATTRIBUTES.get(tag, frozenset())
        occurrences: dict[str, int] = {}
        for raw_name, _ in attrs:
            name = raw_name.lower()
            occurrences[name] = occurrences.get(name, 0) + 1

        sanitized: dict[str, str] = {}
        for raw_name, raw_value in attrs:
            name = raw_name.lower()
            if (
                raw_value is None
                or occurrences[name] != 1
                or name.startswith("on")
                or name in _BLOCKED_ATTRIBUTES
                or name not in allowed
            ):
                continue
            value = _normalize_attribute_value(raw_value)
            if (
                not value
                or len(value) > self._limits.max_attribute_characters
                or any(_is_forbidden_control(character) for character in value)
            ):
                continue
            normalized_value = self._sanitize_attribute_value(tag, name, value)
            if normalized_value is not None:
                sanitized[name] = normalized_value
        return "".join(
            f' {name}="{html.escape(value, quote=True)}"'
            for name, value in sorted(sanitized.items())
        )

    @staticmethod
    def _sanitize_attribute_value(tag: str, name: str, value: str) -> str | None:
        if tag == "a" and name == "href":
            return _sanitize_href(value)
        if name in {"colspan", "rowspan"}:
            return _bounded_positive_integer(value, maximum=100)
        if tag == "ol" and name == "start":
            return _bounded_integer(value, minimum=-10_000, maximum=10_000)
        if tag == "th" and name == "scope":
            lowered = value.lower()
            return lowered if lowered in {"col", "colgroup", "row", "rowgroup"} else None
        return value

    def _count_node(self) -> None:
        self._node_count += 1
        if self._node_count > self._limits.max_nodes:
            _raise_limit("HTML_NODE_LIMIT", self._limits.max_nodes)

    def _count_special_tag(self, tag: str) -> None:
        if tag == "a":
            self._link_count += 1
            if self._link_count > self._limits.max_links:
                _raise_limit("HTML_LINK_LIMIT", self._limits.max_links)
        elif tag == "table":
            self._table_count += 1
            if self._table_count > self._limits.max_tables:
                _raise_limit("HTML_TABLE_LIMIT", self._limits.max_tables)
        elif tag in {"td", "th"}:
            self._table_cell_count += 1
            if self._table_cell_count > self._limits.max_table_cells:
                _raise_limit("HTML_TABLE_CELL_LIMIT", self._limits.max_table_cells)

    def _emit(self, value: str) -> None:
        encoded_length = len(value.encode("utf-8"))
        if self._output_bytes + encoded_length > self._limits.max_output_bytes:
            _raise_limit("HTML_OUTPUT_BYTE_LIMIT", self._limits.max_output_bytes)
        self._pieces.append(value)
        self._output_bytes += encoded_length

    def _close_input_tag(self, tag: str) -> None:
        if tag not in self._input_stack:
            return
        reverse_index = self._input_stack[::-1].index(tag)
        del self._input_stack[len(self._input_stack) - reverse_index - 1 :]

    def _close_drop_tag(self, tag: str) -> None:
        if tag not in self._drop_stack:
            return
        reverse_index = self._drop_stack[::-1].index(tag)
        del self._drop_stack[len(self._drop_stack) - reverse_index - 1 :]

    def _close_output_tag(self, tag: str) -> None:
        if tag not in self._output_stack:
            return
        while self._output_stack:
            current = self._output_stack.pop()
            self._emit(f"</{current}>")
            if current == tag:
                return


def _sanitize_href(value: str) -> str | None:
    candidate = value.strip()
    if (
        not candidate
        or candidate.startswith("//")
        or "\\" in candidate
        or any(ord(character) < 32 or ord(character) == 127 for character in candidate)
    ):
        return None
    try:
        parsed = urlsplit(candidate)
        _ = parsed.port
    except ValueError:
        return None
    if not parsed.scheme:
        colon_index = candidate.find(":")
        delimiter_indexes = [
            index for delimiter in ("/", "?", "#") if (index := candidate.find(delimiter)) >= 0
        ]
        first_delimiter = min(delimiter_indexes, default=len(candidate))
        if 0 <= colon_index < first_delimiter:
            return None
        return candidate if not parsed.netloc else None
    if (
        parsed.scheme.lower() not in _ALLOWED_URL_SCHEMES
        or not candidate.lower().startswith("https://")
        or not parsed.netloc
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return f"https{candidate[len(parsed.scheme) :]}"


def _normalize_attribute_value(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def _bounded_positive_integer(value: str, *, maximum: int) -> str | None:
    if not value.isascii() or not value.isdecimal():
        return None
    parsed = int(value)
    return str(parsed) if 1 <= parsed <= maximum else None


def _bounded_integer(value: str, *, minimum: int, maximum: int) -> str | None:
    try:
        parsed = int(value)
    except ValueError:
        return None
    if str(parsed) != value and str(parsed) != value.lstrip("+"):
        return None
    return str(parsed) if minimum <= parsed <= maximum else None


def _is_forbidden_control(character: str) -> bool:
    codepoint = ord(character)
    return (codepoint < 32 and character not in {"\t", "\n", "\r"}) or codepoint == 127


def _raise_limit(code: str, limit: int) -> None:
    raise GovernanceHtmlSanitizationError(
        "Governance HTML exceeds a configured security limit.",
        details={"code": code, "limit": limit},
    )
