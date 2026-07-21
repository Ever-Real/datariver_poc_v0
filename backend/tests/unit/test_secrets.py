from __future__ import annotations

from pathlib import Path

import pytest

from datariver.infrastructure.secrets import SecretResolutionError, SecretResolver


def test_virtual_docker_secret_reference_maps_only_one_safe_name(tmp_path: Path) -> None:
    secret_root = tmp_path / "secrets"
    secret_root.mkdir()
    (secret_root / "intranet_llm_chat_api_key").write_text("private-token\n")
    resolver = SecretResolver(virtual_secret_root=str(secret_root))

    assert resolver.resolve("file:/run/secrets/intranet_llm_chat_api_key") == "private-token"

    with pytest.raises(SecretResolutionError, match="virtual secret reference"):
        resolver.resolve("file:/run/secrets/../outside")
