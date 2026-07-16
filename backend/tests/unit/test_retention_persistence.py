from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar, Protocol, cast

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, Table

from datariver.infrastructure.db.models.retention import (
    LegalHoldEventModel,
    LegalHoldModel,
    RetentionPolicyVersionModel,
)


class _TableModel(Protocol):
    __table__: ClassVar[Table]


def _table(model: type[object]) -> Table:
    return cast(type[_TableModel], model).__table__


def _constraint_names(model: type[object]) -> set[str]:
    table = _table(model)
    return {
        str(constraint.name) if constraint.name is not None else ""
        for constraint in table.constraints
    }


def _index(model: type[object], name: str) -> Index:
    table = _table(model)
    return next(index for index in table.indexes if index.name == name)


def test_retention_tables_have_tenant_keys_and_shape_constraints() -> None:
    assert {
        "uq_retention_policy_versions_workspace_id_id",
        "uq_retention_policy_versions_workspace_number",
        "fk_retention_policy_versions_requester_membership",
        "fk_retention_policy_versions_checker_membership",
        "fk_retention_policy_versions_superseder_membership",
        "ck_policy_versions_state_shape",
    } <= _constraint_names(RetentionPolicyVersionModel)
    assert {
        "uq_legal_holds_workspace_id_id",
        "fk_legal_holds_creator_membership",
        "fk_legal_holds_release_requester_membership",
        "fk_legal_holds_release_checker_membership",
        "ck_legal_holds_scope_shape",
        "ck_legal_holds_state_shape",
        "ck_legal_holds_payload_hash_sha256",
    } <= _constraint_names(LegalHoldModel)
    assert {
        "uq_legal_hold_events_hold_version",
        "fk_legal_hold_events_hold",
        "fk_legal_hold_events_actor_membership",
        "ck_legal_hold_events_action_version_shape",
    } <= _constraint_names(LegalHoldEventModel)

    for model in (RetentionPolicyVersionModel, LegalHoldModel, LegalHoldEventModel):
        table = _table(model)
        for constraint in table.constraints:
            if not isinstance(constraint, ForeignKeyConstraint):
                continue
            local_columns = {column.name for column in constraint.columns}
            referred_schema = next(iter(constraint.elements)).target_fullname.split(".", 1)[0]
            if referred_schema in {"iam", "retention"}:
                assert "workspace_id" in local_columns
            if referred_schema in {"platform", "retention"}:
                assert constraint.ondelete in {None, "NO ACTION", "RESTRICT"}


def test_active_policy_is_unique_and_every_nonreleased_hold_blocks() -> None:
    active = _index(
        RetentionPolicyVersionModel,
        "uq_retention_policy_versions_workspace_active",
    )
    assert active.unique
    assert str(active.dialect_options["postgresql"]["where"]) == "state = 'ACTIVE'"

    blocking = _index(LegalHoldModel, "ix_legal_holds_workspace_blocking_scope")
    assert not blocking.unique
    assert str(blocking.dialect_options["postgresql"]["where"]) == "state <> 'RELEASED'"

    state_shape = next(
        constraint
        for constraint in _table(LegalHoldModel).constraints
        if isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_legal_holds_state_shape"
    )
    expression = str(state_shape.sqltext)
    assert "RELEASE_REQUESTED" in expression
    assert "RELEASE_REJECTED" in expression
    assert "released_at IS NULL" in expression


def test_legal_hold_events_are_append_only_for_the_application_role() -> None:
    root = Path(__file__).resolve().parents[3]
    generator = (root / "scripts/generate_initial_migration.py").read_text(encoding="utf-8")
    migration = (root / "backend/alembic/versions/0008_retention_policy_legal_hold.py").read_text(
        encoding="utf-8"
    )

    for source in (generator, migration):
        assert "GRANT SELECT, INSERT ON retention.legal_hold_events TO datariver_app;" in source
        assert not re.search(
            r"GRANT[^;]*(?:UPDATE|DELETE)[^;]*retention\.legal_hold_events",
            source,
        )
    assert '("policy_versions", "legal_holds", "legal_hold_events")' in migration
    assert "ALTER TABLE retention.{table} FORCE ROW LEVEL SECURITY" in migration
    assert _table(LegalHoldEventModel).schema == "retention"


def test_retention_grants_cannot_mutate_policy_or_hold_identity() -> None:
    root = Path(__file__).resolve().parents[3]
    generator = (root / "scripts/generate_initial_migration.py").read_text(encoding="utf-8")
    app_block = generator.split("rolname = 'datariver_app'", maxsplit=1)[1].split(
        "END IF;", maxsplit=1
    )[0]

    assert "GRANT SELECT, INSERT ON retention.policy_versions" in app_block
    assert "GRANT SELECT, INSERT ON retention.legal_holds" in app_block
    assert not re.search(r"GRANT[^;]*DELETE[^;]*retention\.", app_block)
    assert "completed_operation_days" not in app_block
    assert "chat_content_days" not in app_block
    assert "audit_online_months" not in app_block
    assert "immutable_archive_years" not in app_block
    assert "data_class" not in app_block
    assert "scope_id" not in app_block
    assert "created_by" not in app_block
