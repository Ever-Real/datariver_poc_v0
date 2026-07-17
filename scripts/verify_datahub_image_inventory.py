from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

MAX_INVENTORY_BYTES = 5 * 1024 * 1024
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "infra" / "contracts" / "datahub-v1.6.0-images.json"


def _load_json_mapping(path: Path, *, description: str) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"{description} is not a regular file: {path}")
    size = path.stat().st_size
    if size <= 0 or size > MAX_INVENTORY_BYTES:
        raise ValueError(f"{description} size must be between 1 and {MAX_INVENTORY_BYTES} bytes")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{description} must be valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{description} root must be an object")
    return value


def approved_component_references(contract: dict[str, Any]) -> dict[str, str]:
    if contract.get("schema_version") != 1 or contract.get("release") != "v1.6.0":
        raise ValueError("DataHub contract must be the approved stable v1.6.0 release")
    components = contract.get("components")
    if not isinstance(components, dict) or not components:
        raise ValueError("DataHub contract components are missing")
    references: dict[str, str] = {}
    for component, entry in components.items():
        if not isinstance(component, str) or not isinstance(entry, dict):
            raise ValueError("DataHub contract component entries are invalid")
        image = entry.get("image")
        digest = entry.get("oci_index_digest")
        if not isinstance(image, str) or not isinstance(digest, str):
            raise ValueError(f"DataHub contract component {component} is incomplete")
        references[component] = f"{image}@{digest}"
    return references


def compose_service_images(rendered_compose: dict[str, Any]) -> dict[str, str]:
    services = rendered_compose.get("services")
    if not isinstance(services, dict) or not services:
        raise ValueError("rendered Compose inventory must contain services")
    images: dict[str, str] = {}
    for name, entry in services.items():
        if not isinstance(name, str) or not isinstance(entry, dict):
            raise ValueError("rendered Compose service entries are invalid")
        image = entry.get("image")
        if isinstance(image, str) and image:
            images[name] = image
    return images


def verify_inventory(rendered_compose: dict[str, Any], contract: dict[str, Any]) -> dict[str, str]:
    expected = approved_component_references(contract)
    service_images = compose_service_images(rendered_compose)
    matched: dict[str, str] = {}
    for component, reference in expected.items():
        image_name = reference.split("@", maxsplit=1)[0]
        component_services = {
            service: image
            for service, image in service_images.items()
            if image.split("@", maxsplit=1)[0].split(":", maxsplit=1)[0]
            == image_name.split(":", maxsplit=1)[0]
        }
        if not component_services:
            raise ValueError(
                f"rendered Compose inventory is missing DataHub component: {component}"
            )
        mismatched = {
            service: image for service, image in component_services.items() if image != reference
        }
        if mismatched:
            raise ValueError(
                f"DataHub component {component} is not digest-pinned to the approved reference"
            )
        matched[component] = reference
    return matched


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify a rendered external DataHub Docker Compose inventory against the approved "
            "v1.6.0 OCI digests."
        )
    )
    parser.add_argument(
        "inventory",
        type=Path,
        help=(
            "JSON emitted by `docker compose ... config --format json` for the external "
            "DataHub stack"
        ),
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        inventory = _load_json_mapping(args.inventory, description="rendered Compose inventory")
        contract = _load_json_mapping(args.contract, description="DataHub image contract")
        matched = verify_inventory(inventory, contract)
    except ValueError as error:
        print(f"DataHub image inventory verification failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"verified_components": matched}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
