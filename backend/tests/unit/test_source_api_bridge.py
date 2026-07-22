from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "source_api_bridge", ROOT / "scripts" / "source_api_bridge.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_source_api_bridge_accepts_only_rfc1918_ipv4_listeners() -> None:
    module = _module()

    assert module.private_ipv4("172.17.0.1") == "172.17.0.1"
    assert module.private_ipv4("10.10.0.1") == "10.10.0.1"
    assert module.private_ipv4("192.168.1.1") == "192.168.1.1"
    for value in ("127.0.0.1", "169.254.1.1", "100.64.0.1", "192.0.2.1", "8.8.8.8", "::1"):
        with pytest.raises(argparse.ArgumentTypeError, match="RFC1918"):
            module.private_ipv4(value)


@pytest.mark.parametrize("value", ("0", "-1", "65536", "not-a-port"))
def test_source_api_bridge_rejects_invalid_ports(value: str) -> None:
    module = _module()

    with pytest.raises(argparse.ArgumentTypeError):
        module.tcp_port(value)


def test_source_api_bridge_selects_ipv4_gateway_from_dual_stack_docker_ipam() -> None:
    module = _module()

    gateway = module.docker_bridge_gateway(
        json.dumps(
            [
                {"Subnet": "172.17.0.0/16", "Gateway": "172.17.0.1"},
                {"Subnet": "fd00::/64", "Gateway": "fd00::1"},
            ]
        )
    )

    assert gateway == "172.17.0.1"


def test_source_api_bridge_rejects_ipam_without_rfc1918_gateway() -> None:
    module = _module()

    with pytest.raises(ValueError, match="no RFC1918"):
        module.docker_bridge_gateway(json.dumps([{"Gateway": "fd00::1"}]))
