from __future__ import annotations

from collections.abc import Callable
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

import pytest


def _load_migration(filename: str) -> ModuleType:
    root = Path(__file__).resolve().parents[3]
    path = root / "backend/alembic/versions" / filename
    spec = spec_from_file_location(f"test_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load migration: {path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _record(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    names: tuple[str, ...],
) -> tuple[list[str], Callable[[str], None]]:
    calls: list[str] = []

    def install(name: str) -> None:
        monkeypatch.setattr(module, name, lambda: calls.append(name))

    for name in names:
        install(name)
    return calls, install


@pytest.mark.parametrize("existing", (0, 4))
def test_0048_upgrade_installs_or_reasserts_all_security_contracts(
    monkeypatch: pytest.MonkeyPatch,
    existing: int,
) -> None:
    migration = _load_migration("0048_governance_apply_lease_fencing.py")
    monkeypatch.setattr(migration, "_column_count", lambda: existing)
    names = (
        "_add_columns",
        "_assert_columns_and_constraints",
        "_install_triggers",
        "_install_grants",
        "_assert_runtime_contract",
    )
    calls, _ = _record(monkeypatch, migration, names)

    migration.upgrade()

    expected = list(names if existing == 0 else names[1:])
    assert calls == expected


def test_0048_upgrade_fails_closed_for_partial_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_migration("0048_governance_apply_lease_fencing.py")
    monkeypatch.setattr(migration, "_column_count", lambda: 2)

    with pytest.raises(RuntimeError, match="partially present"):
        migration.upgrade()


def test_0048_worker_fence_is_role_scoped_revocation_safe_and_update_only_for_cr() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (
        root / "backend/alembic/versions/0048_governance_apply_lease_fencing.py"
    ).read_text(encoding="utf-8")

    assert "only the governance worker may mutate governance apply jobs" in migration
    assert "the governance worker cannot mutate another worker job" in migration
    assert "is_governance_apply_worker_eligible" in migration
    assert "SECURITY DEFINER" in migration
    assert "FOR UPDATE OF membership, subject, workspace" in migration
    assert "membership.job_function = 'SERVICE_ACCOUNT'" in migration
    assert "? 'registration-workers'" in migration
    assert "? 'catalog.sync'" in migration
    assert '"UPDATE",' in migration
    assert "19::smallint" in migration
    assert "grants are overbroad" in migration


@pytest.mark.parametrize("existing", (0, 1))
def test_0049_upgrade_installs_or_reasserts_attachment_identity(
    monkeypatch: pytest.MonkeyPatch,
    existing: int,
) -> None:
    migration = _load_migration("0049_change_request_attachment_object_identity.py")
    monkeypatch.setattr(migration, "_constraint_count", lambda: existing)
    names = ("_install_constraint", "_assert_constraint")
    calls, _ = _record(monkeypatch, migration, names)

    migration.upgrade()

    expected = list(names if existing == 0 else names[1:])
    assert calls == expected


def test_0049_upgrade_fails_closed_for_impossible_duplicate_constraint_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_migration("0049_change_request_attachment_object_identity.py")
    monkeypatch.setattr(migration, "_constraint_count", lambda: 2)

    with pytest.raises(RuntimeError, match="partially present"):
        migration.upgrade()


def test_0049_preflight_and_model_bind_global_object_identity() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (
        root / "backend/alembic/versions/0049_change_request_attachment_object_identity.py"
    ).read_text(encoding="utf-8")
    model = (root / "backend/src/datariver/infrastructure/db/models/governance.py").read_text(
        encoding="utf-8"
    )

    assert "GROUP BY bucket, object_key" in migration
    assert "HAVING count(*) > 1" in migration
    assert "UNIQUE (bucket, object_key)" in migration
    assert '"bucket",\n            "object_key"' in model
    assert 'name="uq_change_request_attachment_object"' in model


@pytest.mark.parametrize("exists", (False, True))
def test_0050_upgrade_creates_or_reasserts_attachment_upload_intent_contract(
    monkeypatch: pytest.MonkeyPatch,
    exists: bool,
) -> None:
    migration = _load_migration("0050_change_request_attachment_upload_intents.py")
    monkeypatch.setattr(migration, "_table_exists", lambda: exists)
    names = ("_create_table", "_install_security", "_assert_contract")
    calls, _ = _record(monkeypatch, migration, names)

    migration.upgrade()

    assert calls == list(names if not exists else names[1:])


def test_0050_model_and_migration_keep_upload_intents_reconcilable_and_monotonic() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (
        root / "backend/alembic/versions/0050_change_request_attachment_upload_intents.py"
    ).read_text(encoding="utf-8")
    model = (root / "backend/src/datariver/infrastructure/db/models/governance.py").read_text(
        encoding="utf-8"
    )

    for source in (migration, model):
        assert "change_request_attachment_upload_intents" in source
        assert "STARTED" in source
        assert "STORED" in source
        assert "FINALIZED" in source
        assert "FAILED" in source
        assert "expected_content_sha256" in source
        assert "uq_change_request_attachment_upload_intent_object" in source
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "AS RESTRICTIVE" in migration
    assert "guard_attachment_upload_intent" in migration
    assert "guard_change_request_attachment_insert" in migration
    assert "attachment insert requires matching STORED upload intent" in migration
    assert "OLD.state = 'STARTED'" in migration
    assert "OLD.state = 'STORED'" in migration
    assert "TG_OP = 'INSERT'" in migration
    assert "must begin with a current STARTED fence" in migration
    assert "claim_attachment_upload_reconciliation" in migration
    assert "FOR UPDATE SKIP LOCKED" in migration
    assert "attest_attachment_upload_object" in migration
    assert "finalize_attachment_upload_intent" in migration
    assert "fail_attachment_upload_intent" in migration
    assert "REVOKE ALL PRIVILEGES" in migration
    assert (
        "governance.attest_attachment_upload_object(uuid, uuid, integer, text, text)" in migration
    )
    assert "TO datariver_upload" in migration
    assert (
        "GRANT SELECT\n"
        "                    ON governance.change_request_attachment_upload_intents\n"
        "                    TO datariver_upload" not in migration
    )
    assert "governance.finalize_attachment_upload_intent(uuid, uuid, integer)" in migration
    assert "TO datariver_app" in migration
    assert "GRANT UPDATE (" not in migration
    assert "expected_indexes" in migration
    assert "actual_column_contract" in migration
    assert "delete_object" not in migration
