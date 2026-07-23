import inspect
from pathlib import Path
from typing import cast

from sqlalchemy import CheckConstraint, Table

from datariver.infrastructure.db.governance import SqlChangeRequestRepository
from datariver.infrastructure.db.models.governance import ChangeItemModel
from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION


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
    assert REQUIRED_DATABASE_REVISION == "0050"
    assert "UPDATE governance.change_request_items" not in migration
    assert "target_binding_shape" in migration
    assert "pg_try_advisory_lock" not in migration


def test_change_request_summary_query_never_selects_mutable_documents() -> None:
    source = inspect.getsource(SqlChangeRequestRepository.list_summaries)
    assert "after_document" not in source
    assert ".limit(limit)" in source
    assert "ChangeRequestModel.created_at.desc()" in source
    assert "ChangeRequestModel.id.desc()" in source
