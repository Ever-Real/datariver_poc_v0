from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _module(name: str) -> ModuleType:
    path = Path(__file__).resolve().parents[3] / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("script", ["migrate_s3_objects.py", "probe_s3_contract.py"])
@pytest.mark.parametrize(
    "endpoint",
    [
        "file:///tmp/objects",
        "http://user@example.invalid",
        "http://:secret@example.invalid",
        "http://example.invalid/path",
        "http://example.invalid?secret=value",
    ],
)
def test_s3_script_endpoint_rejects_non_origin_or_embedded_credentials(
    script: str, endpoint: str
) -> None:
    with pytest.raises(ValueError, match="endpoint"):
        _module(script)._endpoint(endpoint)


@pytest.mark.parametrize("script", ["migrate_s3_objects.py", "probe_s3_contract.py"])
def test_s3_script_endpoint_accepts_credential_free_http_origin(script: str) -> None:
    assert _module(script)._endpoint("https://objects.example.internal:9443/") == (
        "https://objects.example.internal:9443"
    )


def test_s3_probe_cors_header_tokens_require_exact_comma_separated_values() -> None:
    tokens = _module("probe_s3_contract.py")._header_tokens(
        " GET, Put-Object, x-amz-checksum-sha256-extra "
    )

    assert "get" in tokens
    assert "put" not in tokens
    assert "x-amz-checksum-sha256" not in tokens
