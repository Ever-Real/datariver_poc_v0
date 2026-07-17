from __future__ import annotations

from collections.abc import Callable
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from typing import Never, cast

import pytest

MigrationCase = tuple[str, str, str | None]
MIGRATIONS: tuple[MigrationCase, ...] = (
    ("0013_catalog_hierarchy_projection.py", "add_column", None),
    ("0014_catalog_exports.py", "create_table", "_install_security_contract"),
    ("0015_governance_target_bindings.py", "add_column", None),
    ("0016_typed_bulk_registration_foundation.py", "add_column", "_install_security_contract"),
    (
        "0017_candidate_submitted_identity_evidence.py",
        "add_column",
        "_install_immutability_contract",
    ),
)


class _LegacyPathEntered(Exception):
    pass


class _LegacyPathProbe:
    def __init__(self, expected_operation: str) -> None:
        self._expected_operation = expected_operation

    def __getattr__(self, operation: str) -> Callable[..., object]:
        if operation == "f":
            return lambda value: value
        if operation != self._expected_operation:
            raise AssertionError(f"unexpected legacy operation: {operation}")

        def entered(*args: object, **kwargs: object) -> Never:
            del args, kwargs
            raise _LegacyPathEntered

        return entered


class _RejectingOperations:
    def __getattr__(self, operation: str) -> Never:
        raise AssertionError(f"migration unexpectedly executed Alembic operation: {operation}")


def _load_migration(filename: str) -> ModuleType:
    root = Path(__file__).resolve().parents[3]
    path = root / "backend/alembic/versions" / filename
    spec = spec_from_file_location(f"test_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load migration: {path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _callable(module: ModuleType, name: str) -> Callable[[], None]:
    value = getattr(module, name)
    if not callable(value):
        raise AssertionError(f"{module.__name__}.{name} is not callable")
    return cast("Callable[[], None]", value)


def _expected_count(module: ModuleType) -> int:
    value = module.__dict__.get("EXPECTED_OBJECT_COUNT")
    if not isinstance(value, int):
        raise AssertionError(f"{module.__name__}.EXPECTED_OBJECT_COUNT is not an integer")
    return value


@pytest.mark.parametrize(("filename", "first_operation", "installer_name"), MIGRATIONS)
def test_post_baseline_upgrade_uses_legacy_path_when_objects_are_absent(
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    first_operation: str,
    installer_name: str | None,
) -> None:
    del installer_name
    module = _load_migration(filename)
    monkeypatch.setattr(module, "_existing_object_count", lambda: 0)
    monkeypatch.setattr(module, "op", _LegacyPathProbe(first_operation))

    with pytest.raises(_LegacyPathEntered):
        _callable(module, "upgrade")()


@pytest.mark.parametrize(("filename", "first_operation", "installer_name"), MIGRATIONS)
def test_post_baseline_upgrade_accepts_complete_canonical_schema(
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    first_operation: str,
    installer_name: str | None,
) -> None:
    del first_operation
    module = _load_migration(filename)
    monkeypatch.setattr(module, "_existing_object_count", lambda: _expected_count(module))
    monkeypatch.setattr(module, "op", _RejectingOperations())
    installer_calls = 0

    if installer_name is not None:

        def record_installer() -> None:
            nonlocal installer_calls
            installer_calls += 1

        monkeypatch.setattr(module, installer_name, record_installer)

    _callable(module, "upgrade")()

    assert installer_calls == (1 if installer_name is not None else 0)


@pytest.mark.parametrize(("filename", "first_operation", "installer_name"), MIGRATIONS)
def test_post_baseline_upgrade_fails_closed_for_partial_schema(
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    first_operation: str,
    installer_name: str | None,
) -> None:
    del first_operation, installer_name
    module = _load_migration(filename)
    monkeypatch.setattr(module, "_existing_object_count", lambda: 1)
    monkeypatch.setattr(module, "op", _RejectingOperations())

    with pytest.raises(RuntimeError, match="partially present"):
        _callable(module, "upgrade")()


@pytest.mark.parametrize(("filename", "first_operation", "installer_name"), MIGRATIONS)
def test_post_baseline_downgrade_is_compatibility_no_op(
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    first_operation: str,
    installer_name: str | None,
) -> None:
    del first_operation, installer_name
    module = _load_migration(filename)
    monkeypatch.setattr(module, "op", _RejectingOperations())

    _callable(module, "downgrade")()


def test_complete_schema_reinstalls_mutable_security_contracts_idempotently() -> None:
    root = Path(__file__).resolve().parents[3]
    migration_root = root / "backend/alembic/versions"
    catalog_export = (migration_root / "0014_catalog_exports.py").read_text(encoding="utf-8")
    typed_bulk = (migration_root / "0016_typed_bulk_registration_foundation.py").read_text(
        encoding="utf-8"
    )
    candidate_evidence = (
        migration_root / "0017_candidate_submitted_identity_evidence.py"
    ).read_text(encoding="utf-8")

    assert "IF NOT EXISTS" in catalog_export
    assert "FORCE ROW LEVEL SECURITY" in catalog_export
    assert "AS RESTRICTIVE FOR SELECT" in catalog_export
    assert "GRANT SELECT, INSERT ON catalog.export_requests" in catalog_export

    assert "CREATE OR REPLACE FUNCTION" in typed_bulk
    assert "DROP TRIGGER IF EXISTS" in typed_bulk
    assert "IF NOT EXISTS" in typed_bulk
    assert "FORCE ROW LEVEL SECURITY" in typed_bulk
    assert "GRANT SELECT, INSERT ON integration.upload_preparation_jobs" in typed_bulk

    assert "CREATE OR REPLACE FUNCTION" in candidate_evidence
    assert "DROP TRIGGER IF EXISTS" in candidate_evidence
