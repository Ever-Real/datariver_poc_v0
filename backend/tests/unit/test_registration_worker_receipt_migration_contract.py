from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType


class _OperationRecorder:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: str) -> None:
        self.statements.append(statement)


def _load_migration() -> ModuleType:
    root = Path(__file__).resolve().parents[3]
    path = root / "backend/alembic/versions/0047_registration_worker_call_receipts.py"
    spec = spec_from_file_location("test_registration_worker_receipt_0047", path)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load migration 0047")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_receipt_security_installer_replaces_permissive_scope_and_fences_exact_results() -> None:
    migration = _load_migration()
    recorder = _OperationRecorder()
    migration.__dict__["op"] = recorder

    migration._install_security_contract()

    source = "\n".join(recorder.statements)
    assert "DROP POLICY IF EXISTS workspace_isolation" in source
    assert "FROM pg_policies" in source
    assert "DROP POLICY %I" in source
    assert "CREATE POLICY registration_worker_call_scope" in source
    assert "worker_subject_id =" in source
    assert "SET search_path = pg_catalog" in source
    assert "only datariver_app may mutate" in source
    assert "registration worker call no-work result is not canonical" in source
    assert "registration worker call terminal result is not canonical" in source
    assert "governance.manual_metadata_apply_attempts" in source
    assert "integration.upload_preparation_receipts" in source
    assert "'state', 'SUPERSEDED'" in source
    assert source.count("'state', 'RECOVERY_LIMIT_REACHED'") >= 2
    assert "preparation.attempts > OLD.claim_attempt" in source
    assert "submission.attempts > OLD.claim_attempt" in source
    assert "fixed_superseded_completion" in source
    assert "newer_attempt.attempt_no >" in source
    assert "AS newer_receipt" in source
    assert "newer_receipt.claim_attempt >" in source
    assert "newer_receipt.key_hash <> OLD.key_hash" in source
    assert "'WORKER_LEASE_EXHAUSTED'" in source
    assert "REVOKE ALL ON FUNCTION" in source
    assert "REVOKE ALL\n                ON integration.registration_worker_call_receipts" in source
    assert "GRANT UPDATE (" in source


def test_receipt_reentry_assertions_cover_complete_schema_runtime_and_effective_grants() -> None:
    migration = _load_migration()
    recorder = _OperationRecorder()
    migration.__dict__["op"] = recorder

    migration._assert_existing_contract()
    migration._assert_runtime_contract()

    source = "\n".join(recorder.statements)
    assert "relation.relpersistence = 'p'" in source
    assert ") <> 15" in source
    assert ") <> 7" in source
    assert "exact_definition" in source
    assert "check definitions are not canonical" in source
    assert "pk_registration_worker_call_receipts" in source
    assert "fk_registration_worker_call_receipts_subject" in source
    assert "confdeltype <> 'r'" in source
    assert "ix_registration_worker_call_receipts_running_lease" in source
    assert "index_contract.indisvalid" in source
    assert "relforcerowsecurity IS TRUE" in source
    assert "SELECT count(*)\n                FROM pg_policies" in source
    assert "procedure.proconfig IS NOT DISTINCT FROM" in source
    assert "trigger_contract" in source
    assert "lack canonical work evidence" in source
    assert "old_attempt.state = 'SUPERSEDED'" in source
    assert "old_attempt.state = 'RUNNING'" in source
    assert "submission.state = 'APPLIED'" in source
    assert "submission.state = 'FAILED'" in source
    assert "preparation.attempts = receipt.claim_attempt" in source
    assert "newer_receipt.key_hash <>" in source
    assert "has_table_privilege(" in source
    assert "has_column_privilege(" in source
    assert "aclexplode(" in source
    assert "has_function_privilege(" in source
