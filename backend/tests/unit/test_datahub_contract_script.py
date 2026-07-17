from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "verify_datahub_contract", ROOT / "scripts" / "verify_datahub_contract.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_requires_a_deployment_supplied_expected_version() -> None:
    module = _module()

    with pytest.raises(SystemExit):
        module._parser().parse_args(["--base-url", "https://datahub.example.com"])


@pytest.mark.parametrize("version", ("v1.6.0rc1", "v1.6", "latest"))
def test_rejects_prerelease_or_partial_expected_version(version: str) -> None:
    module = _module()

    with pytest.raises(SystemExit):
        module._parser().parse_args(
            ["--base-url", "https://datahub.example.com", "--expected-version", version]
        )
