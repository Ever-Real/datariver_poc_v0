from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import CheckConstraint

from datariver.domain.knowledge_pipeline import KNOWLEDGE_SOURCE_MEDIA_TYPES
from datariver.infrastructure.db import models  # noqa: F401
from datariver.infrastructure.db.base import Base

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "backend/alembic/versions/0082_knowledge_source_media_type_vocabulary.py"

_LEGACY_AND_MACRO_MEDIA_TYPES = frozenset(
    {
        "application/msword",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
        "application/vnd.ms-word.document.macroEnabled.12",
        "application/vnd.ms-excel.sheet.macroEnabled.12",
        "application/vnd.ms-powerpoint.presentation.macroEnabled.12",
        "application/octet-stream",
    }
)


def test_source_snapshot_model_uses_the_exact_governed_media_vocabulary() -> None:
    table = Base.metadata.tables["knowledge.source_snapshots"]
    constraints = {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }

    media_check = constraints["ck_source_snapshots_media_type_vocabulary"]
    assert "ck_source_snapshots_pdf_media_type" not in constraints
    for media_type in KNOWLEDGE_SOURCE_MEDIA_TYPES:
        assert f"'{media_type}'" in media_check
    for media_type in _LEGACY_AND_MACRO_MEDIA_TYPES:
        assert f"'{media_type}'" not in media_check
    assert media_check.count("'") == len(KNOWLEDGE_SOURCE_MEDIA_TYPES) * 2


def test_0082_migration_snapshots_the_domain_vocabulary_and_safe_downgrade() -> None:
    migration = _load_migration()

    assert migration["revision"] == "0082"
    assert migration["down_revision"] == "0081"
    assert frozenset(migration["_SOURCE_MEDIA_TYPES"]) == KNOWLEDGE_SOURCE_MEDIA_TYPES
    assert "media_type IN (" in migration["_media_type_check"]()

    source = MIGRATION.read_text(encoding="utf-8")
    assert "ck_source_snapshots_pdf_media_type" in source
    assert "ck_source_snapshots_media_type_vocabulary" in source
    assert "WHERE media_type <> 'application/pdf'" in source
    assert "explicit reconciliation of non-PDF source snapshots" in source


def _load_migration() -> dict[str, Any]:
    return runpy.run_path(str(MIGRATION))


def _constraint(migration: dict[str, Any], name: str, definition: str) -> Any:
    constraint_type = migration["_SourceSnapshotConstraint"]
    return constraint_type(name=name, definition=definition)


def _legacy_pdf_definition() -> str:
    return "CHECK ((media_type)::text = 'application/pdf'::text)"


def _current_vocabulary_definition(migration: dict[str, Any]) -> str:
    media_type_check = migration["_media_type_check"]
    return f"CHECK ({media_type_check()})"


@pytest.mark.parametrize(
    ("name", "definition", "current", "legacy_name"),
    (
        (
            "ck_source_snapshots_pdf_media_type",
            _legacy_pdf_definition(),
            False,
            "ck_source_snapshots_pdf_media_type",
        ),
        (
            "ck_source_snapshots_ck_source_snapshots_pdf_media_type",
            _legacy_pdf_definition(),
            False,
            "ck_source_snapshots_ck_source_snapshots_pdf_media_type",
        ),
        (
            "ck_source_snapshots_media_type_vocabulary",
            "current",
            True,
            None,
        ),
    ),
)
def test_0082_classifies_only_supported_source_snapshot_constraint_states(
    name: str,
    definition: str,
    current: bool,
    legacy_name: str | None,
) -> None:
    migration = _load_migration()
    if definition == "current":
        definition = _current_vocabulary_definition(migration)
    classify = migration["_classify_source_snapshot_constraint"]

    state = classify((_constraint(migration, name, definition),))

    assert state.current is current
    assert state.legacy_name == legacy_name


@pytest.mark.parametrize(
    "definitions",
    (
        (),
        (("ck_source_snapshots_pdf_media_type", "CHECK (media_type <> 'application/pdf')"),),
        (
            ("ck_source_snapshots_pdf_media_type", _legacy_pdf_definition()),
            (
                "ck_source_snapshots_ck_source_snapshots_pdf_media_type",
                _legacy_pdf_definition(),
            ),
        ),
        (
            ("ck_source_snapshots_pdf_media_type", _legacy_pdf_definition()),
            ("ck_source_snapshots_media_type_vocabulary", "current"),
        ),
        (("unexpected_source_media_type", _legacy_pdf_definition()),),
    ),
)
def test_0082_rejects_missing_malformed_or_mixed_source_snapshot_constraint_states(
    definitions: tuple[tuple[str, str], ...],
) -> None:
    migration = _load_migration()
    classify = migration["_classify_source_snapshot_constraint"]
    constraints = tuple(
        _constraint(
            migration,
            name,
            _current_vocabulary_definition(migration) if definition == "current" else definition,
        )
        for name, definition in definitions
    )

    with pytest.raises(RuntimeError, match="Source snapshot media-type constraint"):
        classify(constraints)


class _ConstraintCatalogResult:
    def __init__(self, definitions: tuple[tuple[str, str], ...]) -> None:
        self._definitions = definitions

    def mappings(self) -> tuple[dict[str, str], ...]:
        return tuple(
            {"conname": name, "definition": definition} for name, definition in self._definitions
        )


class _ConstraintCatalogBind:
    def __init__(self, definitions: tuple[tuple[str, str], ...]) -> None:
        self._definitions = definitions
        self.statement: object | None = None

    def execute(self, statement: object) -> _ConstraintCatalogResult:
        self.statement = statement
        return _ConstraintCatalogResult(self._definitions)


class _RecordingOperations:
    def __init__(self, definitions: tuple[tuple[str, str], ...]) -> None:
        self.bind = _ConstraintCatalogBind(definitions)
        self.actions: list[tuple[object, ...]] = []

    def get_bind(self) -> _ConstraintCatalogBind:
        return self.bind

    def f(self, constraint_name: str) -> str:
        return f"fixed:{constraint_name}"

    def drop_constraint(
        self,
        constraint_name: str,
        table_name: str,
        *,
        schema: str,
        type_: str,
    ) -> None:
        self.actions.append(("drop", constraint_name, table_name, schema, type_))

    def create_check_constraint(
        self,
        constraint_name: str,
        table_name: str,
        condition: str,
        *,
        schema: str,
    ) -> None:
        self.actions.append(("create", constraint_name, table_name, condition, schema))

    def execute(self, statement: str) -> None:
        self.actions.append(("execute", statement))


def _recording_operations(
    migration: dict[str, Any], definitions: tuple[tuple[str, str], ...]
) -> _RecordingOperations:
    operations = _RecordingOperations(definitions)
    migration["upgrade"].__globals__["op"] = operations
    return operations


@pytest.mark.parametrize(
    "legacy_name",
    (
        "ck_source_snapshots_pdf_media_type",
        "ck_source_snapshots_ck_source_snapshots_pdf_media_type",
    ),
)
def test_0082_upgrade_transitions_each_verified_legacy_constraint_with_fixed_names(
    legacy_name: str,
) -> None:
    migration = _load_migration()
    operations = _recording_operations(migration, ((legacy_name, _legacy_pdf_definition()),))

    migration["upgrade"]()

    assert "pg_catalog.pg_constraint" in str(operations.bind.statement)
    assert "pg_get_constraintdef" in str(operations.bind.statement)
    assert operations.actions == [
        ("drop", f"fixed:{legacy_name}", "source_snapshots", "knowledge", "check"),
        (
            "create",
            "fixed:ck_source_snapshots_media_type_vocabulary",
            "source_snapshots",
            migration["_media_type_check"](),
            "knowledge",
        ),
    ]


def test_0082_upgrade_is_idempotent_only_for_the_verified_current_constraint() -> None:
    migration = _load_migration()
    operations = _recording_operations(
        migration,
        (("ck_source_snapshots_media_type_vocabulary", _current_vocabulary_definition(migration)),),
    )

    migration["upgrade"]()

    assert operations.actions == []


def test_0082_downgrade_restores_only_the_canonical_legacy_constraint_after_guard() -> None:
    migration = _load_migration()
    operations = _recording_operations(
        migration,
        (("ck_source_snapshots_media_type_vocabulary", _current_vocabulary_definition(migration)),),
    )

    migration["downgrade"]()

    assert operations.actions[0][0] == "execute"
    assert "explicit reconciliation of non-PDF source snapshots" in str(operations.actions[0][1])
    assert operations.actions[1:] == [
        (
            "drop",
            "fixed:ck_source_snapshots_media_type_vocabulary",
            "source_snapshots",
            "knowledge",
            "check",
        ),
        (
            "create",
            "fixed:ck_source_snapshots_pdf_media_type",
            "source_snapshots",
            "media_type = 'application/pdf'",
            "knowledge",
        ),
    ]


@pytest.mark.parametrize(
    "legacy_name",
    (
        "ck_source_snapshots_pdf_media_type",
        "ck_source_snapshots_ck_source_snapshots_pdf_media_type",
    ),
)
def test_0082_downgrade_leaves_an_already_legacy_constraint_unchanged(legacy_name: str) -> None:
    migration = _load_migration()
    operations = _recording_operations(migration, ((legacy_name, _legacy_pdf_definition()),))

    migration["downgrade"]()

    assert operations.actions == []
