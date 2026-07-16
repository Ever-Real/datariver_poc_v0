from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def _module() -> ModuleType:
    path = Path(__file__).resolve().parents[3] / "scripts" / "verify_datahub_contract.py"
    spec = importlib.util.spec_from_file_location("verify_datahub_contract", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extracts_the_approved_datahub_version_contract() -> None:
    module = _module()

    assert (
        module._reported_version({"versions": {"acryldata/datahub": {"version": "v1.6.0"}}})
        == "v1.6.0"
    )


@pytest.mark.parametrize("payload", [None, {}, {"versions": {}}, {"versions": []}])
def test_rejects_missing_datahub_version_contract(payload: object) -> None:
    module = _module()

    with pytest.raises(ValueError):
        module._reported_version(payload)
