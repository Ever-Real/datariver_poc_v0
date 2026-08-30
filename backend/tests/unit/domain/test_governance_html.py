from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Any, cast

import pytest

from datariver.domain.governance_html import (
    DEFAULT_GOVERNANCE_HTML_LIMITS,
    GOVERNANCE_HTML_SANITIZER_POLICY_SHA256,
    GOVERNANCE_HTML_SANITIZER_POLICY_VERSION,
    GovernanceHtmlLimits,
    GovernanceHtmlSanitizationError,
    governance_html_policy_sha256,
    governance_html_sha256,
    sanitize_governance_html,
)


def test_sanitizer_canonicalizes_safe_policy_markup_and_attributes() -> None:
    raw = (
        "<H2>Policy &amp; Scope</H2>"
        "<b>bold</b><i>italics</i>"
        '<a title=\'A "quote"\' href="/docs?a=1&amp;b=2">link</a>'
        '<table><tr><th scope="COL" colspan="02">Name</th>'
        '<td rowspan="2" colspan="3">Value</td></tr></table>'
    )

    result = sanitize_governance_html(raw)

    assert result.html == (
        "<h2>Policy &amp; Scope</h2>"
        "<strong>bold</strong><em>italics</em>"
        '<a href="/docs?a=1&amp;b=2" title="A &quot;quote&quot;">link</a>'
        '<table><tbody><tr><th colspan="2" scope="col">Name</th>'
        '<td colspan="3" rowspan="2">Value</td></tr></tbody></table>'
    )
    assert result.content_sha256 == hashlib.sha256(result.html.encode("utf-8")).hexdigest()
    assert result.policy_version == GOVERNANCE_HTML_SANITIZER_POLICY_VERSION
    assert result.policy_sha256 == GOVERNANCE_HTML_SANITIZER_POLICY_SHA256


def test_sanitizer_persists_only_static_presentation_tokens_without_inline_style() -> None:
    result = sanitize_governance_html(
        '<p style="font-size:32px" '
        'data-governance-style="text-align:CENTER;position:fixed;font-size:18px;'
        'padding-left:2em;background:url(https://evil.test/x)">Policy</p>'
        '<table><tr><td data-governance-style="font-size:18px;'
        'background-color:#f4f8fa">Cell</td></tr></table>'
    )

    assert result.html == (
        '<p data-governance-style="font-size:18px;padding-left:2em;text-align:center">Policy</p>'
        '<table><tbody><tr><td data-governance-style="font-size:18px;'
        'background-color:#f4f8fa">Cell</td></tr></tbody></table>'
    )
    assert " style=" not in result.html
    assert "position" not in result.html
    assert "url(" not in result.html


@pytest.mark.parametrize(
    ("presentation", "expected"),
    [
        ("font-size:10px", "font-size:10px"),
        ("font-size:12px", "font-size:12px"),
        ("font-size:14px", "font-size:14px"),
        ("font-size:16px", "font-size:16px"),
        ("font-size:18px", "font-size:18px"),
        ("font-size:24px", "font-size:24px"),
        ("font-size:32px", "font-size:32px"),
        ("padding-left:2em", "padding-left:2em"),
        ("padding-left:4em", "padding-left:4em"),
        ("padding-left:6em", "padding-left:6em"),
        ("padding-left:8em", "padding-left:8em"),
        ("padding-left:10em", "padding-left:10em"),
        ("padding-left:12em", "padding-left:12em"),
        ("text-align:center", "text-align:center"),
        ("text-align:right", "text-align:right"),
        ("background-color:#f4f8fa", None),
        ("font-size:11px", None),
        ("padding-left:3em", None),
        ("text-align:justify", None),
    ],
)
def test_presentation_token_contract_is_exact(
    presentation: str,
    expected: str | None,
) -> None:
    result = sanitize_governance_html(
        f'<p data-governance-style="{presentation}">Policy</p>'
    )

    attribute = f' data-governance-style="{expected}"' if expected else ""
    assert result.html == f"<p{attribute}>Policy</p>"


def test_table_cell_background_presentation_is_bounded_and_persists() -> None:
    result = sanitize_governance_html(
        '<table><tr><th data-governance-style="background-color:#f4f8fa">H</th>'
        '<td data-governance-style="background-color:#fff3f2;position:fixed">V</td></tr></table>'
    )

    assert result.html == (
        '<table><tbody><tr><th data-governance-style="background-color:#f4f8fa">H</th>'
        '<td data-governance-style="background-color:#fff3f2">V</td></tr></tbody></table>'
    )


def test_legacy_v2_canonical_html_remains_safe_when_resanitized_by_v3() -> None:
    legacy_v2_html = (
        '<h2>Legacy policy</h2><p><strong>Approved</strong> body</p>'
        '<a href="/governance/policy">Evidence</a>'
    )

    result = sanitize_governance_html(legacy_v2_html)

    assert result.html == legacy_v2_html
    assert result.policy_version == GOVERNANCE_HTML_SANITIZER_POLICY_VERSION
    assert sanitize_governance_html(result.html) == result


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("<script>alert(1)</script><p>safe</p>", "<p>safe</p>"),
        ("<STYLE>body{display:none}</STYLE><p>safe</p>", "<p>safe</p>"),
        ('<iframe srcdoc="<script>alert(1)</script>">inside</iframe><p>safe</p>', "<p>safe</p>"),
        ('<svg><a xlink:href="javascript:alert(1)">bad</a></svg><p>safe</p>', "<p>safe</p>"),
        ("<math><mtext>bad</mtext></math><p>safe</p>", "<p>safe</p>"),
        ("<template><img src=x onerror=alert(1)>bad</template><p>safe</p>", "<p>safe</p>"),
        ('<object data="data:text/html,bad">bad</object><p>safe</p>', "<p>safe</p>"),
        ("<form><button formaction=x>bad</button></form><p>safe</p>", "<p>safe</p>"),
        ('<img src=x onerror="alert(1)"><p>safe</p>', "<p>safe</p>"),
        ("<plaintext><script>alert(1)</script><p>not visible</p>", ""),
        ('<marquee onclick="alert(1)">text survives as text</marquee>', "text survives as text"),
        (
            '<p onclick="alert(1)" style="background:url(javascript:x)" '
            'id="x" name="y" src="z" data-secret="v">safe</p>',
            "<p>safe</p>",
        ),
    ],
)
def test_sanitizer_drops_active_content_and_prohibited_attributes(
    raw: str,
    expected: str,
) -> None:
    assert sanitize_governance_html(raw).html == expected


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        "jav&#x61;script:alert(1)",
        "java&#10;script:alert(1)",
        "vbscript:msgbox(1)",
        "data:text/html,<script>alert(1)</script>",
        "blob:https://example.test/id",
        "file:///etc/passwd",
        "http://example.test/policy",
        "//example.test/policy",
        r"\\example.test\\policy",
        "https://user:password@example.test/policy",
        "https:javascript:alert(1)",
        "custom:payload",
        "jav&#0;ascript:alert(1)",
    ],
)
def test_sanitizer_removes_disallowed_or_ambiguous_link_urls(href: str) -> None:
    result = sanitize_governance_html(f'<a href="{href}">link</a>')

    assert result.html == "<a>link</a>"


@pytest.mark.parametrize(
    ("href", "expected"),
    [
        ("HTTPS://Example.test/policy", "https://Example.test/policy"),
        ("/governance/policy?version=2", "/governance/policy?version=2"),
        ("docs/policy", "docs/policy"),
        ("../policy", "../policy"),
        ("#section-1", "#section-1"),
        ("?version=2", "?version=2"),
    ],
)
def test_sanitizer_allows_https_and_same_origin_relative_links(
    href: str,
    expected: str,
) -> None:
    assert sanitize_governance_html(f'<a href="{href}">link</a>').html == (
        f'<a href="{expected}">link</a>'
    )


def test_duplicate_href_is_removed_to_avoid_parser_differentials() -> None:
    result = sanitize_governance_html(
        '<a href="/safe" href="javascript:alert(1)" title="safe">link</a>'
    )

    assert result.html == '<a title="safe">link</a>'


def test_sanitizer_balances_allowed_markup_and_drops_document_directives() -> None:
    result = sanitize_governance_html(
        "<!doctype html><!-- hidden --><p><strong>value</p>tail<?ignored value>"
    )

    assert result.html == "<p><strong>value</strong></p>tail"
    assert sanitize_governance_html(result.html) == result


@pytest.mark.parametrize(
    ("raw", "limits", "code"),
    [
        (
            "가나",
            replace(DEFAULT_GOVERNANCE_HTML_LIMITS, max_input_bytes=5),
            "HTML_INPUT_BYTE_LIMIT",
        ),
        (
            "&&",
            replace(DEFAULT_GOVERNANCE_HTML_LIMITS, max_output_bytes=8),
            "HTML_OUTPUT_BYTE_LIMIT",
        ),
        (
            "<p>text</p>",
            replace(DEFAULT_GOVERNANCE_HTML_LIMITS, max_nodes=1),
            "HTML_NODE_LIMIT",
        ),
        (
            "<p><strong><em>deep</em></strong></p>",
            replace(DEFAULT_GOVERNANCE_HTML_LIMITS, max_depth=2),
            "HTML_DEPTH_LIMIT",
        ),
        (
            '<a href="/1">one</a><a href="/2">two</a>',
            replace(DEFAULT_GOVERNANCE_HTML_LIMITS, max_links=1),
            "HTML_LINK_LIMIT",
        ),
        (
            "<table></table><table></table>",
            replace(DEFAULT_GOVERNANCE_HTML_LIMITS, max_tables=1),
            "HTML_TABLE_LIMIT",
        ),
        (
            "<table><tr><td>1</td><td>2</td></tr></table>",
            replace(DEFAULT_GOVERNANCE_HTML_LIMITS, max_table_cells=1),
            "HTML_TABLE_CELL_LIMIT",
        ),
    ],
)
def test_sanitizer_fails_closed_on_security_limits(
    raw: str,
    limits: GovernanceHtmlLimits,
    code: str,
) -> None:
    with pytest.raises(GovernanceHtmlSanitizationError) as caught:
        sanitize_governance_html(raw, limits=limits)

    assert caught.value.details["code"] == code
    assert "limit" in caught.value.details
    assert raw not in caught.value.message


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("<p>secret\x00value</p>", "HTML_CONTROL_CHARACTER"),
        ("\ud800", "HTML_ENCODING_INVALID"),
    ],
)
def test_sanitizer_reports_only_structured_errors_without_raw_html(
    raw: str,
    code: str,
) -> None:
    with pytest.raises(GovernanceHtmlSanitizationError) as caught:
        sanitize_governance_html(raw)

    assert caught.value.details == {"code": code}
    assert "secret" not in caught.value.message
    assert raw not in caught.value.message


def test_sanitizer_rejects_non_text_without_echoing_value() -> None:
    raw = cast(Any, b"<script>secret</script>")

    with pytest.raises(GovernanceHtmlSanitizationError) as caught:
        sanitize_governance_html(raw)

    assert caught.value.details == {"code": "HTML_TYPE_INVALID"}
    assert "secret" not in caught.value.message


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "<p>plain &amp; escaped</p>",
        "<p><strong>unclosed",
        '<a href="jav&#x61;script:alert(1)" onclick="bad()">link</a>',
        "<svg><foreignObject><p>bad</p></foreignObject></svg><p>good</p>",
        '<table><tr><th scope="ROW">A</th><td colspan="2">B</td></tr></table>',
    ],
)
def test_sanitizer_is_idempotent_for_safe_and_hostile_inputs(raw: str) -> None:
    first = sanitize_governance_html(raw)
    second = sanitize_governance_html(first.html)

    assert second == first


def test_policy_and_content_hash_helpers_are_deterministic_and_scope_limits() -> None:
    canonical = "<p>정책</p>"
    narrower = replace(DEFAULT_GOVERNANCE_HTML_LIMITS, max_links=1)

    assert (
        governance_html_sha256(canonical) == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    )
    assert governance_html_policy_sha256() == GOVERNANCE_HTML_SANITIZER_POLICY_SHA256
    assert governance_html_policy_sha256(narrower) != GOVERNANCE_HTML_SANITIZER_POLICY_SHA256
    assert len(GOVERNANCE_HTML_SANITIZER_POLICY_SHA256) == 64


def test_hash_helper_rejects_non_utf8_text_without_echoing_it() -> None:
    with pytest.raises(GovernanceHtmlSanitizationError) as caught:
        governance_html_sha256("\ud800")

    assert caught.value.details == {"code": "HTML_ENCODING_INVALID"}


@pytest.mark.parametrize("invalid", [0, -1])
def test_limits_must_be_positive(invalid: int) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        GovernanceHtmlLimits(max_links=invalid)
