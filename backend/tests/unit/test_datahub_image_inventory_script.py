from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "verify_datahub_image_inventory", ROOT / "scripts" / "verify_datahub_image_inventory.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _contract() -> dict[str, object]:
    value = json.loads(
        (ROOT / "infra" / "contracts" / "datahub-v1.6.0-images.json").read_text(encoding="utf-8")
    )
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _inventory(module: ModuleType) -> dict[str, object]:
    references = module.approved_component_references(_contract())
    return {
        "services": {
            f"datahub-{component}": {"image": reference}
            for component, reference in references.items()
        }
    }


def test_accepts_a_rendered_compose_inventory_with_exact_approved_digests() -> None:
    module = _module()

    verified = module.verify_inventory(_inventory(module), _contract())

    assert set(verified) == {"actions", "frontend", "gms", "upgrade"}
    assert all("@sha256:" in reference for reference in verified.values())


def test_rejects_a_tag_only_or_wrong_digest_component() -> None:
    module = _module()
    inventory = _inventory(module)
    services = inventory["services"]
    assert isinstance(services, dict)
    services["datahub-gms"] = {"image": "acryldata/datahub-gms:v1.6.0"}

    with pytest.raises(ValueError, match="not digest-pinned"):
        module.verify_inventory(inventory, _contract())


def test_rejects_missing_required_datahub_component() -> None:
    module = _module()
    inventory = _inventory(module)
    services = inventory["services"]
    assert isinstance(services, dict)
    services.pop("datahub-actions")

    with pytest.raises(ValueError, match="missing DataHub component: actions"):
        module.verify_inventory(inventory, _contract())
