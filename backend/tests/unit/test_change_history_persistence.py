from __future__ import annotations

import importlib.util
import inspect
from datetime import UTC, date, datetime
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint

from datariver.domain.common import ValidationError
from datariver.infrastructure.db import models as _models  # noqa: F401
from datariver.infrastructure.db.base import Base
from datariver.infrastructure.db.change_history import (
    NormalizedLedgerEvent,
    SqlChangeHistoryStore,
    _validate_event,
)
from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "backend/alembic/versions/0096_change_history_persistence.py"
EXPECTED_TABLES = {
    "change_history.sources",
    "change_history.ledger_events",
    "change_history.checkpoints",
    "change_history.cr_link_events",
}


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("test_change_history_0096", MIGRATION)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _event(**overrides: object) -> NormalizedLedgerEvent:
    values: dict[str, object] = {
        "workspace_id": uuid4(),
        "source_id": uuid4(),
        "event_identity": "a" * 64,
        "source_event_identity": "b" * 64,
        "normalized_change_transaction_id": "c" * 64,
        "deterministic_ordinal": 0,
        "source_kind": "MCL",
        "topic_contract": "MetadataChangeLog_Versioned_v1@contract",
        "source_partition": 0,
        "source_offset": 10,
        "asset_id": None,
        "entity_urn": "urn:li:dataset:(urn:li:dataPlatform:test,db.schema.table,PROD)",
        "entity_urn_hash": "d" * 64,
        "entity_type": "dataset",
        "platform": "test",
        "database_name": "db",
        "schema_name": "schema",
        "table_or_view_name": "table",
        "field_path": "column",
        "normalized_entity_key": "db.schema.table.column",
        "system_id": None,
        "category": "TECHNICAL_SCHEMA",
        "source_aspect": "schemaMetadata",
        "operation": "UPDATE",
        "before_data": {"field_type": "string"},
        "after_data": {"field_type": "integer"},
        "before_hash": "e" * 64,
        "after_hash": "f" * 64,
        "actor_ref": "urn:li:corpuser:test",
        "source_occurred_at": datetime(2026, 8, 13, tzinfo=UTC),
        "detected_at": datetime(2026, 8, 13, tzinfo=UTC),
        "captured_at": datetime(2026, 8, 13, tzinfo=UTC),
        "effective_week_start": date(2026, 8, 10),
        "precision": "EXACT_MCL",
        "tombstone": False,
        "source_metadata": {"schema_contract_version": "v1"},
    }
    values.update(overrides)
    return NormalizedLedgerEvent(**values)  # type: ignore[arg-type]


def test_change_history_metadata_is_the_minimal_t03_contract() -> None:
    assert EXPECTED_TABLES <= set(Base.metadata.tables)
    assert "change_history.source_events" not in Base.metadata.tables
    assert REQUIRED_DATABASE_REVISION == "0096"

    for name in EXPECTED_TABLES:
        table = Base.metadata.tables[name]
        assert "workspace_id" in table.c
        assert any(
            isinstance(constraint, ForeignKeyConstraint)
            and any(
                element.target_fullname == "platform.workspaces.id"
                for element in constraint.elements
            )
            for constraint in table.foreign_key_constraints
        )
        assert all(
            (element.ondelete or "").upper() != "CASCADE"
            for constraint in table.foreign_key_constraints
            for element in constraint.elements
        )


def test_ledger_fanout_dedup_and_keyset_indices_are_explicit() -> None:
    ledger = Base.metadata.tables["change_history.ledger_events"]
    unique_columns = {
        tuple(constraint.columns.keys())
        for constraint in ledger.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert (
        "workspace_id",
        "source_id",
        "source_event_identity",
        "deterministic_ordinal",
    ) in unique_columns
    index_names = {index.name for index in ledger.indexes if isinstance(index, Index)}
    assert {
        "ix_change_history_ledger_keyset",
        "ix_change_history_ledger_asset_history",
        "ix_change_history_ledger_filters",
        "ix_change_history_ledger_transaction",
    } <= index_names


def test_closed_precision_allowlist_and_raw_document_guards_exist() -> None:
    ledger = Base.metadata.tables["change_history.ledger_events"]
    checks = "\n".join(
        str(constraint.sqltext)
        for constraint in ledger.constraints
        if isinstance(constraint, CheckConstraint)
    )
    assert "EXACT_TIMELINE" in checks
    assert "EXACT_MCL" in checks
    assert "DRIFT_DETECTED" in checks
    assert "BACKFILLED_BEST_EFFORT" in checks
    assert "INITIAL_BASELINE" in checks
    assert "GUARANTEED_FORWARD" not in checks
    assert "source_metadata ?| ARRAY" in checks
    assert "octet_length(before_data::text) <= 16384" in checks
    assert "jsonb_path_exists(before_data" in checks
    assert "jsonb_path_exists(after_data" in checks
    assert "jsonb_path_exists(source_metadata" in checks

    _validate_event(_event())
    with pytest.raises(ValidationError, match="raw provider-document key"):
        _validate_event(_event(after_data={"schemaMetadata": {"fields": []}}))
    with pytest.raises(ValidationError, match="normalized persistence bound"):
        _validate_event(_event(before_data={"summary": "x" * 17_000}))


def test_checkpoint_and_link_contracts_are_fenced_and_append_only() -> None:
    migration = _migration()
    source = MIGRATION.read_text(encoding="utf-8")
    security = "\n".join(migration.security_statements())

    assert 'revision: str = "0096"' in source
    assert 'down_revision: str | Sequence[str] | None = "0095"' in source
    assert "NEW.next_offset < OLD.next_offset" in security
    assert "NEW.fence_epoch > OLD.fence_epoch + 1" in security
    assert "checkpoint advancement requires the current unexpired fence" in security
    assert "link.link_version = NEW.link_version" in security
    assert "link.event_hash = NEW.event_hash" in security
    assert "CR link event has a stale version or prior hash" in security
    assert "candidate events cannot change the current primary CR round" in security
    assert security.count("reject_append_only_mutation") >= 3
    assert "GRANT SELECT ON change_history.checkpoints TO datariver_app" in security
    assert "GRANT UPDATE" not in migration._GRANTS_SQL
    assert "REVOKE UPDATE, DELETE ON change_history.sources" in security
    assert "0096 downgrade refuses to delete change-history evidence" in source


def test_checkpoint_lease_clock_is_database_authoritative() -> None:
    migration = _migration()
    claim_sql = migration._CLAIM_CHECKPOINT_SQL
    advance_sql = migration._ADVANCE_CHECKPOINT_SQL
    parameters = inspect.signature(SqlChangeHistoryStore.acquire_checkpoint_lease).parameters

    assert "p_acquired_at" not in claim_sql
    assert "p_expires_at" not in claim_sql
    assert "lease_now timestamptz := clock_timestamp()" in claim_sql
    assert "checkpoint.lease_expires_at > lease_now" in claim_sql
    assert "lease_now + make_interval(secs => p_lease_duration_seconds)" in claim_sql
    assert "checkpoint.lease_expires_at <= clock_timestamp()" in advance_sql
    assert "acquired_at" not in parameters
    assert "expires_at" not in parameters
    assert "lease_duration_seconds" in parameters


def test_all_change_history_constraints_are_named() -> None:
    for name in EXPECTED_TABLES:
        table = Base.metadata.tables[name]
        for constraint in table.constraints:
            if isinstance(constraint, (CheckConstraint, UniqueConstraint)):
                assert constraint.name
