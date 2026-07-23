import re
from pathlib import Path
from typing import ClassVar, Protocol, cast

from sqlalchemy import ForeignKeyConstraint, Table

from datariver.infrastructure.db.models.retention import (
    RetentionExecutionAttemptModel,
    RetentionExecutionEventModel,
    RetentionExecutionJobModel,
    RetentionPolicyClassRuleModel,
    RetentionPolicyVersionModel,
)


class _TableModel(Protocol):
    __table__: ClassVar[Table]


def _table(model: type[object]) -> Table:
    return cast(type[_TableModel], model).__table__


def _constraint_names(model: type[object]) -> set[str]:
    return {
        str(constraint.name) if constraint.name is not None else ""
        for constraint in _table(model).constraints
    }


def test_policy_v2_contract_and_class_rules_are_exact_and_immutable() -> None:
    assert {
        "ck_policy_versions_contract_shape",
        "uq_retention_policy_versions_workspace_id_hash_number",
    } <= _constraint_names(RetentionPolicyVersionModel)
    assert {
        "uq_retention_policy_class_rules_workspace_policy_class",
        "fk_retention_policy_class_rules_policy",
        "ck_policy_class_rules_bounds",
        "ck_policy_class_rules_unit",
        "ck_policy_class_rules_archive_disposition",
        "ck_policy_class_rules_payload_hash_sha256",
    } <= _constraint_names(RetentionPolicyClassRuleModel)

    policy_fk = next(
        constraint
        for constraint in _table(RetentionPolicyClassRuleModel).constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and constraint.name == "fk_retention_policy_class_rules_policy"
    )
    assert [column.name for column in policy_fk.columns] == [
        "workspace_id",
        "policy_id",
        "policy_hash",
        "policy_number",
    ]
    assert policy_fk.ondelete in {None, "RESTRICT", "NO ACTION"}


def test_execution_control_plane_has_one_time_command_and_fenced_append_only_evidence() -> None:
    assert {
        "uq_retention_execution_jobs_workspace_id_id",
        "uq_retention_execution_jobs_erasure_request",
        "fk_retention_execution_jobs_erasure_request",
        "fk_retention_execution_jobs_policy",
        "fk_retention_execution_jobs_archive_receipt",
        "ck_execution_jobs_target_shape",
        "ck_execution_jobs_lease_shape",
        "ck_execution_jobs_state",
        "ck_execution_jobs_destructive_disabled",
        "ck_execution_jobs_separation_of_duties",
        "fk_retention_execution_jobs_executor",
    } <= _constraint_names(RetentionExecutionJobModel)
    assert {
        "uq_retention_execution_attempts_job_fence",
        "fk_retention_execution_attempts_job",
        "ck_execution_attempts_lease_token_hash",
        "ck_execution_attempts_destructive_effect_zero",
    } <= _constraint_names(RetentionExecutionAttemptModel)
    assert {
        "uq_retention_execution_events_job_sequence",
        "fk_retention_execution_events_job",
        "ck_execution_events_evidence_hash_sha256",
    } <= _constraint_names(RetentionExecutionEventModel)

    claim_index = next(
        index
        for index in _table(RetentionExecutionJobModel).indexes
        if index.name == "ix_retention_execution_jobs_claim"
    )
    assert [column.name for column in claim_index.columns] == [
        "workspace_id",
        "next_attempt_at",
        "created_at",
        "id",
    ]
    assert "PLANNED" in str(claim_index.dialect_options["postgresql"]["where"])
    assert "RETRY_WAIT" in str(claim_index.dialect_options["postgresql"]["where"])


def test_phase2_roles_and_migration_have_no_destructive_privilege_or_state() -> None:
    root = Path(__file__).resolve().parents[3]
    generator = (root / "scripts/generate_initial_migration.py").read_text(encoding="utf-8")
    canonical = (root / "backend/alembic/versions/0001_initial_schema.py").read_text(
        encoding="utf-8"
    )
    migration = (
        root / "backend/alembic/versions/0042_retention_execution_control_plane.py"
    ).read_text(encoding="utf-8")
    roles = (root / "infra/postgres/init/010_roles.sh").read_text(encoding="utf-8")
    reconcile_sh = (root / "scripts/reconcile-postgres-roles.sh").read_text(encoding="utf-8")
    reconcile_ps1 = (root / "scripts/reconcile-postgres-roles.ps1").read_text(encoding="utf-8")

    for role in ("datariver_retention_scheduler", "datariver_archive"):
        assert role in roles
        role_block = roles.split(f"ALTER ROLE {role}", maxsplit=1)[1].split(";", maxsplit=1)[0]
        assert "NOBYPASSRLS" in role_block
    role_sql = roles.split("<<'SQL'", maxsplit=1)[1].rsplit("\nSQL", maxsplit=1)[0]
    assert not any(line.lstrip().startswith("#") for line in role_sql.splitlines())
    for source in (canonical, migration):
        assert "ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED" in source
        assert "ERASURE_EXECUTION_EVIDENCE" in source
        assert "ck_execution_jobs_separation_of_duties" in source
        assert "GRANT SELECT ON retention.execution_jobs TO datariver_app" in source
        assert not re.search(
            r"(?:^|\n)\s*GRANT\s[^;]*(?:DELETE|TRUNCATE)[^;]*"
            r"retention\.(?:execution|immutable_archive)",
            source,
            flags=re.IGNORECASE,
        )
        for forbidden_state in ("DELETED", "PURGED", "PARTITION_DROPPED"):
            assert forbidden_state not in source
    assert "retention.execution_jobs TO datariver_app" in generator
    assert "ordinal_position" not in migration
    assert "e7d66e854560db29c126f3768a3eb2d3b635c9a1f6b291bf7255b72149b75478" in migration
    assert "0dcf7a560a9c9ccd090b4178c63af942283df77e1eae5e6f6841e9976dc16ae2" in migration
    assert "0a6f12b6ee2ffbb7b6e7d11ba22aa651cdc9831b22194fa34b83922a578986d4" in migration
    assert "_ARCHIVE_SOURCE_LEGACY_DEFINITION" in migration
    assert 'op.f("ck_immutable_archive_receipts_source")' in migration
    assert "/docker-entrypoint-initdb.d/010_roles.sh" in reconcile_sh
    assert "/docker-entrypoint-initdb.d/010_roles.sh" in reconcile_ps1


def test_execution_evidence_tables_are_forced_rls_and_events_are_append_only() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (
        root / "backend/alembic/versions/0042_retention_execution_control_plane.py"
    ).read_text(encoding="utf-8")
    tables = (
        "policy_class_rules",
        "execution_jobs",
        "execution_attempts",
        "execution_events",
    )
    assert all(f'"{table}"' in migration for table in tables)
    assert 'f"ALTER TABLE retention.{table} FORCE ROW LEVEL SECURITY"' in migration
    assert "GRANT SELECT, INSERT ON retention.execution_events TO datariver_archive" in migration
    assert not re.search(
        r"GRANT[^;]*(?:UPDATE|DELETE)[^;]*retention\.execution_events",
        migration,
        flags=re.IGNORECASE,
    )


def test_execution_table_foreign_keys_do_not_cascade() -> None:
    for model in (
        RetentionPolicyClassRuleModel,
        RetentionExecutionJobModel,
        RetentionExecutionAttemptModel,
        RetentionExecutionEventModel,
    ):
        for constraint in _table(model).constraints:
            if isinstance(constraint, ForeignKeyConstraint):
                assert constraint.ondelete in {None, "RESTRICT", "NO ACTION"}
