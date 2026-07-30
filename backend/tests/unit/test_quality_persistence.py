from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint

from datariver.infrastructure.db import models as _models  # noqa: F401
from datariver.infrastructure.db.base import Base
from datariver.infrastructure.db.migration_scope import MANAGED_DATABASE_SCHEMAS
from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "backend/alembic/versions/0067_quality_control_plane.py"
CANONICAL_GENERATOR = ROOT / "scripts/generate_initial_migration.py"

EXPECTED_TABLES = {
    "quality.rule_sets",
    "quality.rule_set_versions",
    "quality.rule_definitions",
    "quality.rule_reviews",
    "quality.rule_command_events",
    "quality.rule_schedules",
    "quality.validation_runs",
    "quality.validation_attempts",
    "quality.expectation_results",
    "quality.run_events",
    "quality.dispatch_call_receipts",
    "quality.dispatch_run_links",
    "quality.execution_call_receipts",
}


def test_quality_metadata_and_revision_are_complete() -> None:
    assert REQUIRED_DATABASE_REVISION == "0070"
    assert "quality" in MANAGED_DATABASE_SCHEMAS
    assert EXPECTED_TABLES <= set(Base.metadata.tables)
    assert "retention.legal_hold_generations" in Base.metadata.tables
    for name in EXPECTED_TABLES:
        table = Base.metadata.tables[name]
        assert "workspace_id" in table.c
        assert any(
            isinstance(constraint, ForeignKeyConstraint)
            and any(
                element.target_fullname == "platform.workspaces.id"
                for element in constraint.elements
            )
            for constraint in table.constraints
        )
        assert all(
            (element.ondelete or "").upper() != "CASCADE"
            for constraint in table.foreign_key_constraints
            for element in constraint.elements
        )


def test_quality_access_path_indices_match_the_contract() -> None:
    version_indices = Base.metadata.tables["quality.rule_set_versions"].indexes
    schedule_indices = Base.metadata.tables["quality.rule_schedules"].indexes
    run_indices = Base.metadata.tables["quality.validation_runs"].indexes
    expected = {
        "uq_quality_rule_set_versions_active",
        "uq_quality_rule_schedules_active",
        "ix_quality_rule_schedules_due",
        "ix_quality_validation_runs_runnable",
        "ix_quality_validation_runs_terminal_dashboard",
    }
    actual = {index.name for index in (*version_indices, *schedule_indices, *run_indices)}
    assert expected <= actual
    for index in (*version_indices, *schedule_indices, *run_indices):
        if index.name in expected:
            assert isinstance(index, Index)
            assert index.dialect_options["postgresql"].get("where") is not None


def test_quality_constraints_are_tenant_safe_and_closed() -> None:
    for name in EXPECTED_TABLES:
        table = Base.metadata.tables[name]
        for constraint in table.constraints:
            if isinstance(constraint, ForeignKeyConstraint):
                targets = {element.target_fullname for element in constraint.elements}
                target_schemas = {target.split(".", 1)[0] for target in targets}
                if target_schemas & {"quality", "iam", "catalog", "retention"}:
                    assert "workspace_id" in constraint.column_keys
            if isinstance(constraint, (CheckConstraint, UniqueConstraint)):
                assert constraint.name


def test_quality_rule_parameters_and_command_replay_are_database_closed() -> None:
    definitions = Base.metadata.tables["quality.rule_definitions"]
    definition_checks = "\n".join(
        str(constraint.sqltext)
        for constraint in definitions.constraints
        if isinstance(constraint, CheckConstraint)
    )
    assert "kind IN ('NOT_NULL', 'RANGE')" in definition_checks
    assert "parameters = '{}'::jsonb" in definition_checks
    assert "parameters = jsonb_build_object" in definition_checks
    assert "'min_value', parameters -> 'min_value'" in definition_checks
    assert "'inclusive_min', parameters -> 'inclusive_min'" in definition_checks
    assert "value_type' IN ('DECIMAL','DATE','TIMESTAMP')" in definition_checks
    assert "'REGEX'" not in definition_checks

    commands = Base.metadata.tables["quality.rule_command_events"]
    assert commands.c.request_hash.nullable is False
    command_checks = "\n".join(
        str(constraint.sqltext)
        for constraint in commands.constraints
        if isinstance(constraint, CheckConstraint)
    )
    assert "request_hash ~ '^[0-9a-f]{64}$'" in command_checks


def test_quality_run_attempt_and_receipt_evidence_use_composite_foreign_keys() -> None:
    runs = Base.metadata.tables["quality.validation_runs"]
    run_current_attempt = next(
        constraint
        for constraint in runs.foreign_key_constraints
        if constraint.name == "fk_quality_runs_current_attempt"
    )
    assert tuple(run_current_attempt.column_keys) == (
        "workspace_id",
        "id",
        "current_attempt_id",
    )
    assert tuple(element.target_fullname for element in run_current_attempt.elements) == (
        "quality.validation_attempts.workspace_id",
        "quality.validation_attempts.run_id",
        "quality.validation_attempts.id",
    )
    assert run_current_attempt.use_alter is True
    assert run_current_attempt.deferrable is True
    assert run_current_attempt.initially == "DEFERRED"

    links = Base.metadata.tables["quality.dispatch_run_links"]
    receipt_link = next(
        constraint
        for constraint in links.foreign_key_constraints
        if constraint.name == "fk_quality_dispatch_links_receipt"
    )
    run_link = next(
        constraint
        for constraint in links.foreign_key_constraints
        if constraint.name == "fk_quality_dispatch_links_run"
    )
    execution = Base.metadata.tables["quality.execution_call_receipts"]
    execution_attempt = next(
        constraint
        for constraint in execution.foreign_key_constraints
        if constraint.name == "fk_quality_execution_attempt"
    )
    assert len(receipt_link.column_keys) == 8
    assert len(run_link.column_keys) == 14
    assert len(execution_attempt.column_keys) == 11
    assert {
        "lease_epoch",
        "lease_token_hash",
        "audit_retention_policy_hash",
        "audit_hold_hash",
    } <= set(execution_attempt.column_keys)

    results = Base.metadata.tables["quality.expectation_results"]
    result_rule = next(
        constraint
        for constraint in results.foreign_key_constraints
        if constraint.name == "fk_quality_results_rule"
    )
    result_run = next(
        constraint
        for constraint in results.foreign_key_constraints
        if constraint.name == "fk_quality_results_run"
    )
    assert tuple(result_rule.column_keys) == (
        "workspace_id",
        "rule_definition_id",
        "rule_set_version_id",
    )
    assert {
        "run_id",
        "attempt_id",
        "run_state",
        "rule_set_version_id",
        "result_retention_policy_hash",
        "result_hold_hash",
    } <= set(result_run.column_keys)
    assert result_run.deferrable is True
    assert result_run.initially == "DEFERRED"


def test_incremental_and_canonical_contract_include_security_fences() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    generator = CANONICAL_GENERATOR.read_text(encoding="utf-8")
    for marker in (
        "FORCE ROW LEVEL SECURITY",
        "datariver_quality",
        "NOBYPASSRLS",
        "resolve_quality_binding_v1",
        "review_rule_set_version_v1",
        "activate_rule_set_version_v1",
        "revoke_rule_set_version_v1",
        "archive_rule_set_v1",
        "current_target_matches_v1",
        "decision_evidence.authorization_hash",
        "decision_evidence.assurance_hash",
        "calculated_request_hash",
        "_QUALITY_CATALOG_CONTRACT_HASH",
        "role_membership",
        "schema_grant",
        "reject_evidence_mutation",
        "ck_policy_versions_ck_policy_versions_contract_shape",
        "ck_policy_class_rules_ck_policy_class_rules_data_class",
        "0067 downgrade refuses non-empty immutable Quality evidence",
    ):
        assert marker in migration
    assert "_load_quality_phase1_revision" in generator
    assert "_RLS_AND_GRANTS_SQL" in generator


def test_incremental_revision_is_importable_and_single_parented() -> None:
    spec = importlib.util.spec_from_file_location("quality_0067_test", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0067"
    assert module.down_revision == "0066"
