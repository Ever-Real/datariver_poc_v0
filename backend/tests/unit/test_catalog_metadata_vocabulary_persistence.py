from __future__ import annotations

import inspect
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import CheckConstraint, Table

from datariver.domain.common import ValidationError
from datariver.infrastructure.db.catalog_metadata import (
    SqlCatalogMetadataVocabularyProjection,
    _decode_vocabulary_cursor,
    _encode_vocabulary_cursor,
)
from datariver.infrastructure.db.models.catalog import (
    CatalogVocabularyEntryModel,
    CatalogVocabularySyncRunModel,
)


def _check_sql(table: Table) -> str:
    return " ".join(
        str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    )


def test_vocabulary_projection_model_has_workspace_kind_run_and_snapshot_evidence() -> None:
    entries = cast(Table, CatalogVocabularyEntryModel.__table__)
    runs = cast(Table, CatalogVocabularySyncRunModel.__table__)

    assert "last_seen_sync_id" in entries.c
    assert set(runs.primary_key.columns.keys()) == {"workspace_id", "sync_id", "kind"}
    checks = _check_sql(runs)
    for token in (
        "DOMAIN",
        "TAG",
        "TERM",
        "ACTIVE",
        "COMPLETED",
        "ABANDONED",
        "snapshot_consistent",
        "snapshot_evidence_reference",
        "snapshot_contract_hash",
        "snapshot_provider_version",
    ):
        assert token in checks
    active = next(
        index
        for index in runs.indexes
        if index.name == "uq_vocabulary_sync_runs_active_workspace_kind"
    )
    assert active.unique is True
    assert str(active.dialect_options["postgresql"]["where"]) == "state = 'ACTIVE'"


def test_vocabulary_upsert_preserves_local_uuid_and_only_verified_full_run_inactivates() -> None:
    source = inspect.getsource(SqlCatalogMetadataVocabularyProjection.upsert_scan)
    conflict = source[source.index("statement = statement.on_conflict_do_update") :]
    update_values = conflict[
        conflict.index("set_={") : conflict.index("await self._session.execute")
    ]

    assert "CatalogVocabularyEntryModel.workspace_id" in conflict
    assert "CatalogVocabularyEntryModel.kind" in conflict
    assert "CatalogVocabularyEntryModel.provider_ref" in conflict
    assert '"id"' not in update_values
    assert "seen_count != expected_total" in source
    inactivation_gate = source.index("if active.snapshot_consistent:")
    inactive_update = source.index('lifecycle="INACTIVE"')
    assert inactivation_gate < inactive_update
    assert "SUPPRESSED_UNVERIFIED_SNAPSHOT" in source
    assert "last_seen_sync_id.is_distinct_from" in source


def test_vocabulary_query_cursor_binds_workspace_kind_and_filter() -> None:
    module = inspect.getsource(
        __import__(
            "datariver.infrastructure.db.catalog_metadata",
            fromlist=["_encode_vocabulary_cursor"],
        )
    )
    for token in (
        '"scope": "catalog-metadata-vocabulary"',
        '"workspace_id": str(workspace_id)',
        '"kind": kind',
        '"query": query',
        'CatalogVocabularyEntryModel.lifecycle == "ACTIVE"',
        "CatalogVocabularyEntryModel.workspace_id == workspace_id",
    ):
        assert token in module


def test_vocabulary_query_cursor_rejects_scope_kind_filter_and_tampering() -> None:
    workspace_id = uuid4()
    cursor = _encode_vocabulary_cursor(
        workspace_id=workspace_id,
        kind="TAG",
        query="critical",
        sort_name="business critical",
        vocabulary_id=uuid4(),
    )

    for scoped_workspace_id, scoped_kind, scoped_query in (
        (uuid4(), "TAG", "critical"),
        (workspace_id, "TERM", "critical"),
        (workspace_id, "TAG", "revenue"),
    ):
        with pytest.raises(ValidationError, match="cursor"):
            _decode_vocabulary_cursor(
                cursor,
                workspace_id=scoped_workspace_id,
                kind=scoped_kind,
                query=scoped_query,
            )
    with pytest.raises(ValidationError, match="cursor"):
        _decode_vocabulary_cursor(
            f"{cursor}A",
            workspace_id=workspace_id,
            kind="TAG",
            query="critical",
        )
