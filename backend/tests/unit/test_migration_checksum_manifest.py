from __future__ import annotations

import hashlib
import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _load_source(path: Path, name: str) -> ModuleType:
    spec = spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load source: {path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify_static = _load_source(ROOT / "scripts/verify_static.py", "test_checksum_verify_static")


def _static_fixture(tmp_path: Path) -> Path:
    migration_root = tmp_path / "backend/alembic/versions"
    migration_root.mkdir(parents=True)
    (migration_root / "0001.py").write_text("revision = '0001'\n", encoding="utf-8")
    return migration_root


def _write_accepted_migration_manifest(root: Path) -> Path:
    migration_root = root / "backend/alembic/versions"
    files = {
        path.relative_to(migration_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(migration_root.rglob("*.py"))
    }
    manifest_path = root / "backend/alembic/accepted_migration_checksums.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "algorithm": "sha256",
                "accepted_through_revision": "0100",
                "files": files,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest_path


def _select_fixture_manifest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(verify_static, "ROOT", tmp_path)
    monkeypatch.setattr(
        verify_static,
        "ACCEPTED_MIGRATION_CHECKSUM_MANIFEST",
        tmp_path / "backend/alembic/accepted_migration_checksums.json",
    )


def test_static_gate_accepts_exact_historical_migration_inventory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    migration_root = _static_fixture(tmp_path)
    _write_accepted_migration_manifest(tmp_path)
    _select_fixture_manifest(monkeypatch, tmp_path)

    verify_static.verify_accepted_migration_checksums()

    (migration_root / "0001.py").write_text("revision = 'changed'\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="checksum drifted"):
        verify_static.verify_accepted_migration_checksums()


def test_static_gate_rejects_missing_or_unaccepted_migration_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    migration_root = _static_fixture(tmp_path)
    _write_accepted_migration_manifest(tmp_path)
    _select_fixture_manifest(monkeypatch, tmp_path)

    (migration_root / "0002.py").write_text("revision = '0002'\n", encoding="utf-8")
    with pytest.raises(AssertionError, match=r"unaccepted=.*0002\.py"):
        verify_static.verify_accepted_migration_checksums()
    (migration_root / "0002.py").unlink()
    (migration_root / "0001.py").unlink()
    with pytest.raises(AssertionError, match=r"missing=.*0001\.py"):
        verify_static.verify_accepted_migration_checksums()
