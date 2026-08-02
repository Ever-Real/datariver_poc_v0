import inspect
from pathlib import Path
from typing import cast

from sqlalchemy import CheckConstraint, Table, UniqueConstraint

from datariver.infrastructure.db.governance import SqlChangeRequestRepository
from datariver.infrastructure.db.models.governance import (
    ChangeItemModel,
    ChangeRequestRoundItemModel,
    ChangeRequestRoundModel,
)


def test_change_item_model_has_nullable_all_or_none_target_binding() -> None:
    table = cast(Table, ChangeItemModel.__table__)
    required = {
        "target_asset_id",
        "target_asset_type",
        "target_system_id",
        "target_domain_id",
        "target_owner_department_id",
        "target_classification",
        "target_lifecycle",
        "target_source_version",
        "target_observed_at",
        "target_binding_hash",
    }
    assert required <= set(table.columns.keys())
    assert all(table.c[name].nullable for name in required)
    checks = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {
        "ck_change_request_items_target_binding_shape",
        "ck_change_request_items_target_classification_range",
        "ck_change_request_items_target_binding_hash_sha256",
    } <= checks


def test_target_binding_migration_preserves_legacy_rows_without_backfill() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = (root / "backend/alembic/versions/0015_governance_target_bindings.py").read_text(
        encoding="utf-8"
    )
    assert "UPDATE governance.change_request_items" not in migration
    assert "target_binding_shape" in migration
    assert "pg_try_advisory_lock" not in migration


def test_change_request_summary_query_never_selects_mutable_documents() -> None:
    source = inspect.getsource(SqlChangeRequestRepository.list_summaries)
    assert "after_document" not in source
    assert ".limit(limit)" in source
    assert "ChangeRequestModel.created_at.desc()" in source
    assert "ChangeRequestModel.id.desc()" in source


def test_change_request_repository_round_trips_optional_item_contract_hash() -> None:
    item_model_source = inspect.getsource(SqlChangeRequestRepository._item_model)
    hydrate_source = inspect.getsource(SqlChangeRequestRepository.get_for_update)

    assert "item_contract_hash=item.item_contract_hash" in item_model_source
    assert "item_contract_hash=item.item_contract_hash" in hydrate_source


def test_change_request_round_snapshot_and_item_association_are_immutable_contracts() -> None:
    round_table = cast(Table, ChangeRequestRoundModel.__table__)
    association_table = cast(Table, ChangeRequestRoundItemModel.__table__)
    item_table = cast(Table, ChangeItemModel.__table__)

    assert {
        "revision_kind",
        "title",
        "request_date",
        "request_department",
        "request_reason",
        "request_content",
        "requested_due_date",
        "priority",
        "urgency",
        "classification",
        "selected_system_id",
    } <= set(round_table.columns.keys())
    assert "snapshot_hash" not in round_table.columns
    assert {
        "workspace_id",
        "change_request_id",
        "round_id",
        "item_id",
        "ordinal",
    } == set(association_table.columns.keys())
    association_uniques = {
        constraint.name
        for constraint in association_table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert "uq_change_request_round_items_ordinal" in association_uniques
    association_checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in association_table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert association_checks["ck_change_request_round_items_ordinal_non_negative"] == (
        "ordinal >= 0"
    )
    repository_add = inspect.getsource(SqlChangeRequestRepository.add)
    assert "for ordinal, item in enumerate(change_request.items)" in repository_add
    assert "enumerate(change_request.items, start=1)" not in repository_add
    item_uniques = {
        tuple(column.name for column in constraint.columns)
        for constraint in item_table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("change_request_id", "ordinal") not in item_uniques
