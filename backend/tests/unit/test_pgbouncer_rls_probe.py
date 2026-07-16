from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest


def _module() -> ModuleType:
    path = Path(__file__).resolve().parents[3] / "scripts" / "probe_pgbouncer_rls.py"
    spec = importlib.util.spec_from_file_location("probe_pgbouncer_rls", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_requires_passwordless_postgresql_urls() -> None:
    module = _module()

    assert (
        module._connection_url("postgresql+asyncpg://app@pooler:6432/datariver")
        == "postgresql://app@pooler:6432/datariver"
    )
    with pytest.raises(ValueError, match="embed passwords"):
        module._connection_url("postgresql://app:secret@pooler:6432/datariver")
    with pytest.raises(ValueError, match="PostgreSQL scheme"):
        module._connection_url("http://pooler:6432/datariver")


def test_requires_single_server_transaction_pool() -> None:
    module = _module()

    module._validate_transaction_pool_config({"pool_mode": "transaction", "default_pool_size": "1"})
    with pytest.raises(RuntimeError, match="transaction mode"):
        module._validate_transaction_pool_config({"pool_mode": "session", "default_pool_size": "1"})
    with pytest.raises(RuntimeError, match="default_pool_size=1"):
        module._validate_transaction_pool_config(
            {"pool_mode": "transaction", "default_pool_size": "2"}
        )


def test_rejects_empty_or_cross_workspace_rls_results() -> None:
    module = _module()
    expected, other = uuid4(), uuid4()

    module._validate_visible_workspaces(
        expected=expected,
        other=other,
        rows=({"workspace_id": expected, "asset_count": 1},),
    )
    with pytest.raises(RuntimeError, match="at least one visible fixture"):
        module._validate_visible_workspaces(expected=expected, other=other, rows=())
    with pytest.raises(RuntimeError, match="expected workspace"):
        module._validate_visible_workspaces(
            expected=expected,
            other=other,
            rows=(
                {"workspace_id": expected, "asset_count": 1},
                {"workspace_id": other, "asset_count": 1},
            ),
        )


def test_requires_file_backed_nonempty_secret(tmp_path: Path) -> None:
    module = _module()
    secret = tmp_path / "password"
    secret.write_text("pool-secret\n", encoding="utf-8")

    assert module._read_secret(f"file:{secret}") == "pool-secret"
    with pytest.raises(ValueError, match="file: references"):
        module._read_secret("env:PGPASSWORD")
