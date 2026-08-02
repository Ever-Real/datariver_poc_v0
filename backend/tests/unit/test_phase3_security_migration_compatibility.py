from __future__ import annotations

from collections.abc import Callable
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from textwrap import dedent
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


def _load_source_module(path: Path) -> ModuleType:
    spec = spec_from_file_location(f"test_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load source module: {path}")
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


def test_0091_upgrade_and_downgrade_replace_only_the_finalize_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_migration("0091_align_governance_attachment_authorization.py")
    executed: list[str] = []
    monkeypatch.setattr(migration.op, "execute", executed.append)

    migration.upgrade()
    migration.downgrade()

    assert migration.revision == "0091"
    assert migration.down_revision == "0090"
    assert executed == [
        migration.FINALIZE_ATTACHMENT_UPLOAD_INTENT_FUNCTION_SQL,
        migration.LEGACY_FINALIZE_ATTACHMENT_UPLOAD_INTENT_FUNCTION_SQL,
    ]
    for statement in executed:
        assert statement.count("CREATE OR REPLACE FUNCTION") == 1
        assert "CREATE TABLE" not in statement
        assert "ALTER TABLE" not in statement
        assert "GRANT " not in statement


def test_0091_downgrade_restores_the_exact_0050_legacy_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy = _load_migration("0050_change_request_attachment_upload_intents.py")
    current = _load_migration("0091_align_governance_attachment_authorization.py")
    executed: list[str] = []
    monkeypatch.setattr(legacy.op, "execute", executed.append)

    legacy._install_security()

    original = next(
        statement
        for statement in executed
        if "CREATE OR REPLACE FUNCTION governance.finalize_attachment_upload_intent" in statement
    )
    assert " ".join(current.LEGACY_FINALIZE_ATTACHMENT_UPLOAD_INTENT_FUNCTION_SQL.split()) == (
        " ".join(dedent(original).split())
    )


def test_0091_finalize_uses_current_profile_responsibility_and_routed_target_authority() -> None:
    migration = _load_migration("0091_align_governance_attachment_authorization.py")
    sql = migration.FINALIZE_ATTACHMENT_UPLOAD_INTENT_FUNCTION_SQL

    for required in (
        "SECURITY DEFINER",
        "SET search_path = pg_catalog, governance, iam, platform, catalog, authz",
        "FOR UPDATE OF membership, subject, workspace",
        "iam.profile_role_assignments",
        "PROFILE_ROLE_POLICY_V1",
        "materialized_actions_hash",
        "iam.canonical_admin_bindings",
        "membership_access_hash",
        "platform.system_assignees",
        "assignee.active IS TRUE",
        "platform.data_systems",
        "system.active IS TRUE",
        "platform.system_schema_scopes",
        "current_mapping.active IS NOT TRUE",
        "target.current_native_system_id IS NOT NULL",
        "IS DISTINCT FROM current_mapping.system_id",
        "effective_system_id IS DISTINCT FROM expected_system_id",
        "intent.kind = 'TEST'",
        "assignee.responsibility = 'DEVELOPER'",
        "target.current_classification = 3",
        "rule.search_mode = 'EXPLICIT_GRANT_ONLY'",
        "authz.restricted_search_grants",
        "grant_row.scope = 'RESOURCE'",
        "grant_row.scope = 'SYSTEM'",
        "grant_row.scope = 'DOMAIN'",
        "IF intent.state = 'FINALIZED' THEN",
    ):
        assert required in sql

    assert "asset.system_id IS DISTINCT FROM item.target_system_id" not in sql
    assert "target_source_version" not in sql
    assert "target_observed_at" not in sql
    assert "source_version" not in sql
    assert "observed_at" not in sql
    assert sql.index("FROM iam.workspace_memberships") < sql.index(
        "FROM governance.change_request_attachment_upload_intents"
    )
    assert sql.index("FROM platform.system_schema_scopes") < sql.index("FOR target IN")
    assert sql.index("FROM authz.restricted_search_grants") < sql.index("FOR target IN")
    finalized_branch = sql.index("IF intent.state = 'FINALIZED' THEN")
    finalized_return = sql.index("RETURN intent.id;", finalized_branch)
    request_lock = sql.index("FROM governance.change_requests", finalized_branch)
    assert finalized_branch < finalized_return < request_lock
    assert (
        sql.index(
            "RAISE EXCEPTION 'finalized attachment evidence is inconsistent'",
            finalized_branch,
        )
        < request_lock
    )


def test_0092_scopes_current_attachment_authorization_to_current_round_items() -> None:
    previous = _load_migration("0091_align_governance_attachment_authorization.py")
    current = _load_migration("0092_change_request_editable_revisions.py")
    sql = current.FINALIZE_ATTACHMENT_UPLOAD_INTENT_FUNCTION_SQL

    assert current.revision == "0092"
    assert current.down_revision == "0091"
    assert current.PREVIOUS_FINALIZE_ATTACHMENT_UPLOAD_INTENT_FUNCTION_SQL == (
        previous.FINALIZE_ATTACHMENT_UPLOAD_INTENT_FUNCTION_SQL
    )
    assert sql.count("FROM governance.change_request_round_items AS round_item") == 8
    assert sql.count("round_item.round_id = request.current_round_id") == 8
    assert "governance.change_request_round_items" not in (
        current.PREVIOUS_FINALIZE_ATTACHMENT_UPLOAD_INTENT_FUNCTION_SQL
    )
    finalized_branch = sql.index("IF intent.state = 'FINALIZED' THEN")
    finalized_return = sql.index("RETURN intent.id;", finalized_branch)
    request_lock = sql.index("FROM governance.change_requests", finalized_branch)
    assert finalized_branch < finalized_return < request_lock


def test_0092_is_the_canonical_generated_attachment_authorization() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = _load_migration("0092_change_request_editable_revisions.py")
    generator = _load_source_module(root / "scripts/generate_initial_migration.py")
    initial = (root / "backend/alembic/versions/0001_initial_schema.py").read_text(encoding="utf-8")

    operation = generator.build_upgrade().ops[-1]
    assert operation.sqltext == migration.FINALIZE_ATTACHMENT_UPLOAD_INTENT_FUNCTION_SQL
    assert (
        initial.count("CREATE OR REPLACE FUNCTION governance.finalize_attachment_upload_intent")
        == 1
    )
    assert "attachment catalog target binding is stale" in initial
    assert "governance.change_request_round_items" in initial
