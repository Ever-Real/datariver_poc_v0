from __future__ import annotations

from datariver.interfaces.http.routes.admin import (
    _MASKED_VALUE,
    _mask_configuration,
    _merge_masked_configuration,
    _render_yaml,
    _yaml_document,
)


def test_masked_yaml_preserves_existing_sensitive_values_on_incremental_save() -> None:
    stored = _yaml_document(
        "url: http://grafana.local:3000\nauth:\n  password: original-secret\n"
    )
    browser_document = _mask_configuration(stored)

    assert browser_document == {
        "url": "http://grafana.local:3000",
        "auth": {"password": _MASKED_VALUE},
    }
    incoming = _yaml_document(
        "url: http://grafana.local:3000/d/overview\nauth:\n  password: '********'\n"
    )

    merged = _merge_masked_configuration(incoming, stored)

    assert merged == {
        "url": "http://grafana.local:3000/d/overview",
        "auth": {"password": "original-secret"},
    }
    masked = _yaml_document(_render_yaml(_mask_configuration(merged)))
    assert masked["auth"]["password"] == _MASKED_VALUE
