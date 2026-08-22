from __future__ import annotations

import inspect
from collections.abc import Callable
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from typing import Never, cast

import pytest

from datariver.infrastructure.db.governance import SqlChangeRequestRepository

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
    (
        "0018_chat_retention_policy_binding.py",
        "add_column",
        "_assert_chat_retention_binding_contract",
    ),
    ("0019_catalog_display_metadata_projection.py", "add_column", None),
    ("0021_catalog_column_name_projection.py", "add_column", None),
    ("0022_cr_schedule_and_system_master.py", "add_column", "_install_security_contract"),
    (
        "0023_manual_metadata_submissions.py",
        "create_unique_constraint",
        "_install_security_contract",
    ),
    ("0024_manual_metadata_apply_leases.py", "add_column", None),
    (
        "0027_change_request_attachments.py",
        "create_table",
        "_install_security_contract",
    ),
    ("0031_workspace_access_roles.py", "create_table", None),
    (
        "0032_membership_renewal_workflow.py",
        "add_column",
        "_install_security_contract",
    ),
    ("0033_change_workflow_role_evidence.py", "add_column", None),
    (
        "0034_system_configuration_activation.py",
        "add_column",
        "_install_security_contract",
    ),
    (
        "0035_change_request_rounds_and_test_evidence.py",
        "create_table",
        "_install_security_contract",
    ),
    (
        "0036_typed_xlsx_bulk_registration.py",
        "drop_constraint",
        "_install_security_contract",
    ),
    (
        "0037_knowledge_source_graphrag_projection.py",
        "add_column",
        "_install_security_contract",
    ),
    (
        "0046_registration_execution_controls.py",
        "get_bind",
        "_install_security_contract",
    ),
    (
        "0047_registration_worker_call_receipts.py",
        "create_table",
        "_install_security_contract",
    ),
    (
        "0096_change_history_persistence.py",
        "execute",
        None,
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
    secondary_installer_calls = 0
    assertion_calls = 0

    if installer_name is not None:

        def record_installer() -> None:
            nonlocal installer_calls
            installer_calls += 1

        monkeypatch.setattr(module, installer_name, record_installer)

    if filename in {
        "0046_registration_execution_controls.py",
        "0047_registration_worker_call_receipts.py",
    }:

        def record_secondary_installer() -> None:
            nonlocal secondary_installer_calls
            secondary_installer_calls += 1

        def record_assertion() -> None:
            nonlocal assertion_calls
            assertion_calls += 1

        if filename == "0046_registration_execution_controls.py":
            monkeypatch.setattr(
                module,
                "_install_typed_bulk_binding_contract",
                record_secondary_installer,
            )
        monkeypatch.setattr(module, "_assert_existing_contract", record_assertion)
        monkeypatch.setattr(module, "_assert_runtime_contract", record_assertion)

    _callable(module, "upgrade")()

    assert installer_calls == (1 if installer_name is not None else 0)
    assert secondary_installer_calls == (
        1 if filename == "0046_registration_execution_controls.py" else 0
    )
    assert assertion_calls == (
        2
        if filename
        in {
            "0046_registration_execution_controls.py",
            "0047_registration_worker_call_receipts.py",
        }
        else 0
    )


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


def test_0090_profile_role_migration_is_linear_and_has_no_legacy_auto_escalation() -> None:
    root = Path(__file__).resolve().parents[3]
    path = root / "backend/alembic/versions/0090_profile_role_authority.py"
    source = path.read_text(encoding="utf-8")
    module = _load_migration(path.name)

    assert module.revision == "0090"
    assert module.down_revision == "0089"
    assert 'op.create_table(\n        "profile_role_assignments"' in source
    assert 'op.create_table(\n        "profile_role_assignment_events"' in source
    assert 'sa.Column("policy_decision_id", sa.Uuid(), nullable=False)' in source
    assert "IDENTITY_PROVISIONING_FUNCTION_SQL_V3" in source
    assert "UPDATE iam.workspace_memberships" not in source
    assert "GOVERNED_ADMIN_ASSIGNMENT" in source
    assert "0090 downgrade is blocked by profile Role or governed Admin history" in source
    assert source.index('op.drop_table("profile_role_assignment_events"') < source.index(
        'op.drop_table("profile_role_assignments"'
    )


def test_0092_editable_change_request_revision_migration_is_additive_and_fail_closed() -> None:
    root = Path(__file__).resolve().parents[3]
    path = root / "backend/alembic/versions/0092_change_request_editable_revisions.py"
    source = path.read_text(encoding="utf-8")
    module = _load_migration(path.name)

    assert module.revision == "0092"
    assert module.down_revision == "0091"
    assert "0092 found a partial editable Change Request revision schema" in source
    assert "0092 forbids a second round snapshot hash" in source
    assert '"change_request_round_items"' in source
    assert "revision_kind = 'LEGACY'" in source
    assert "request_date = NULL" in source
    assert "request_date = request.created_at::date" not in source
    assert "UPDATE governance.change_request_rounds AS round" in source
    assert "JOIN governance.change_request_items AS item" in source
    assert "round.id" in source
    assert "item.id" in source
    assert "item.ordinal" in source
    assert '"ordinal >= 0"' in source
    assert "ck_change_request_round_items_ordinal_non_negative" in source
    assert source.index("INSERT INTO governance.change_request_round_items") < source.index(
        "op.drop_constraint(\n        _LEGACY_ITEM_ORDINAL_CONSTRAINT"
    )
    assert "UPDATE governance.change_request_items" not in source
    assert "SET evidence_hash" not in source
    assert "DROP TABLE governance.change_request_items" not in source
    assert "REVOKE UPDATE ON governance.change_request_rounds" in source
    assert "GRANT UPDATE (closed_at)" in source
    assert "GRANT SELECT, INSERT ON governance.change_request_round_items" in source
    assert "GRANT UPDATE, DELETE ON governance.change_request_round_items" not in source
    assert "REVOKE UPDATE, DELETE ON governance.change_request_round_items" in source
    assert "0092 downgrade is blocked by editable Change Request history" in source
    assert "0092 current round item association is incomplete" in source
    downgrade = source.index("def downgrade() -> None:")
    assert source.index("_assert_downgrade_preconditions()", downgrade) < source.index(
        'op.drop_table("change_request_round_items"'
    )
    assert "0052_governance_apply_reauthorization.py" not in source
    repository_add = inspect.getsource(SqlChangeRequestRepository.add)
    assert "for ordinal, item in enumerate(change_request.items)" in repository_add
    assert "enumerate(change_request.items, start=1)" not in repository_add
    assert "item.ordinal" in source
    assert '"ordinal >= 0"' in source


def test_0092_canonical_reentry_only_reasserts_current_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_migration("0092_change_request_editable_revisions.py")
    calls: list[str] = []

    monkeypatch.setattr(module, "_schema_state", lambda: "CURRENT")
    monkeypatch.setattr(module, "_assert_current_contract", lambda: calls.append("assert"))
    monkeypatch.setattr(module, "_install_security_contract", lambda: calls.append("grants"))
    monkeypatch.setattr(module.op, "execute", lambda sql: calls.append(str(sql)))

    module.upgrade()

    assert calls[:2] == ["assert", "grants"]
    assert calls[2:] == [module.FINALIZE_ATTACHMENT_UPLOAD_INTENT_FUNCTION_SQL]


def test_0052_raw_single_item_apply_stays_outside_editable_intake_revisions() -> None:
    root = Path(__file__).resolve().parents[3]
    path = root / "backend/alembic/versions/0052_governance_apply_reauthorization.py"
    source = path.read_text(encoding="utf-8")
    module = _load_migration(path.name)

    assert module.revision == "0052"
    assert "CREATE OR REPLACE FUNCTION governance.reauthorize_datahub_apply(" in source
    assert "p_target_type <> 'DATAHUB_ASPECT'" in source
    assert "request.request_type = p_request_type" in source
    assert "item.id = p_item_id" in source
    assert "change_request_round_items" not in source


def test_registration_execution_bridge_validates_definitions_not_only_names() -> None:
    source = (
        Path(__file__).resolve().parents[3]
        / "backend/alembic/versions/0046_registration_execution_controls.py"
    ).read_text(encoding="utf-8")

    assert "_assert_existing_contract()" in source
    assert "actual.data_type <> expected.data_type" in source
    assert "pg_get_constraintdef(oid)" in source
    assert "relforcerowsecurity IS NOT TRUE" in source
    assert "manual_metadata_attempt_reader_scope" in source
    assert "policy.qual IS DISTINCT FROM" in source
    assert "pg_get_expr(" in source
    assert "expected_predicate" in source
    assert "tgtype = 31" in source
    assert "OLD.provider_source_version <> NEW.provider_source_version" in source
    assert "ck_manual_metadata_submissions_provider_source_version_valid" in source
    assert "'governance.manual_metadata_submissions'," in source
    assert "policy.with_check IS DISTINCT FROM" in source
    assert "BEFORE INSERT OR UPDATE OR DELETE" in source
    assert "manual aspect report requires the current running attempt" in source
    assert "has_table_privilege(" in source
