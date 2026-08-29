from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from datariver.infrastructure.db import models  # noqa: F401
from datariver.infrastructure.db.base import Base

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "backend/alembic/versions/0101_catalog_metadata_recommendations.py"


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("catalog_recommendations_0101", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_recommendation_migration_is_one_forward_head_with_workspace_rls() -> None:
    migration = _load_migration()
    source = MIGRATION.read_text(encoding="utf-8")

    assert migration.revision == "0101"
    assert migration.down_revision == "0100"
    assert source.count('op.create_table(\n        "metadata_recommendations"') == 1
    assert source.count('op.create_table(\n        "metadata_recommendation_events"') == 1
    assert "IF NOT EXISTS" not in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert source.count("CREATE POLICY workspace_isolation") == 1
    assert "for table in" in source
    assert "metadata recommendation events are append-only" in source
    assert "GRANT SELECT, INSERT ON catalog.metadata_recommendation_events" in source
    assert "GRANT UPDATE" in source
    assert "ON catalog.metadata_recommendation_events TO datariver_app" in source
    assert "UPDATE ON catalog.metadata_recommendation_events" not in source
    with pytest.raises(RuntimeError, match="forward-only"):
        migration.downgrade()


def test_recommendation_metadata_matches_new_migration_tables() -> None:
    recommendation = Base.metadata.tables["catalog.metadata_recommendations"]
    events = Base.metadata.tables["catalog.metadata_recommendation_events"]

    assert {
        "workspace_id",
        "asset_id",
        "field_path_key",
        "vocabulary_id",
        "kind",
        "source_version",
        "provider_source_version",
        "vocabulary_source_version",
        "aspect_name",
        "aspect_source_version",
        "aspect_content_hash",
        "target_binding_hash",
        "input_context_hash",
        "confidence",
        "reason",
        "evidence",
        "provider",
        "model",
        "prompt_version",
        "rule_version",
        "state",
        "version",
        "created_by",
        "decision_actor_id",
        "change_request_id",
        "decision_key_hash",
        "decision_request_hash",
        "decision_kind",
        "decision_expected_version",
        "id",
        "created_at",
        "updated_at",
    } == set(recommendation.columns.keys())
    assert {
        "workspace_id",
        "recommendation_id",
        "recommendation_version",
        "decision",
        "actor_id",
        "reason",
        "change_request_id",
        "request_hash",
        "occurred_at",
        "id",
    } == set(events.columns.keys())


def test_migration_complete_contract_matches_imported_model_names() -> None:
    migration = _load_migration()
    for table_name in ("metadata_recommendations", "metadata_recommendation_events"):
        table = Base.metadata.tables[f"catalog.{table_name}"]
        assert migration._EXPECTED_CONSTRAINTS[table_name] == {
            str(value.name) for value in table.constraints
        }
        assert migration._EXPECTED_INDEXES[table_name] == {
            str(value.name) for value in table.indexes
        } | {
            str(value.name)
            for value in table.constraints
            if value.__class__.__name__ in {"PrimaryKeyConstraint", "UniqueConstraint"}
        }


class _OwnedResult:
    def __init__(self, value: int) -> None:
        self.value = value

    def scalar_one(self) -> int:
        return self.value


class _OwnedBind:
    def __init__(self, value: int) -> None:
        self.value = value

    def execute(self, *_: Any, **__: Any) -> _OwnedResult:
        return _OwnedResult(self.value)


@pytest.mark.parametrize(
    ("owned", "error_kind", "expected"),
    [
        (0, None, "ABSENT"),
        (8, None, "COMPLETE"),
        (1, "mismatch", None),
        (8, "malformed", None),
    ],
)
def test_migration_classifies_absent_complete_partial_and_malformed_exactly(
    monkeypatch: pytest.MonkeyPatch,
    owned: int,
    error_kind: str | None,
    expected: str | None,
) -> None:
    migration = _load_migration()
    monkeypatch.setattr(migration.op, "get_context", lambda: SimpleNamespace(as_sql=False))
    monkeypatch.setattr(migration.op, "get_bind", lambda: _OwnedBind(owned))

    def assert_complete(_: object) -> None:
        if error_kind == "mismatch":
            raise migration._CompleteStateMismatch("partial")
        if error_kind == "malformed":
            raise ValueError("malformed")

    monkeypatch.setattr(migration, "_assert_complete_state", assert_complete)
    if expected is not None:
        assert migration._schema_state() == expected
    else:
        with pytest.raises(RuntimeError, match="partial or malformed"):
            migration._schema_state()


def test_migration_fails_closed_without_rewrite_or_bypass_markers() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    # ABSENT receives normal DDL, exact COMPLETE returns, and every other owned shape raises.
    upgrade = source.split("def upgrade()", maxsplit=1)[1].split("def install_guards", maxsplit=1)[
        0
    ]
    assert "op.create_table" in upgrade
    assert '_schema_state() == "COMPLETE"' in upgrade
    assert "partial or malformed" in source
    assert "DROP TABLE" not in upgrade
    assert "bypass" not in source.lower()
    assert "rewrite" not in source.lower()


def test_complete_verifier_remains_fail_closed_under_python_optimized_mode() -> None:
    migration = _load_migration()
    verifier_source = (
        MIGRATION.read_text(encoding="utf-8")
        .split("def _assert_complete_state", maxsplit=1)[1]
        .split("def upgrade", maxsplit=1)[0]
    )
    assert "assert " not in verifier_source
    assert issubclass(migration._CompleteStateMismatch, RuntimeError)

    program = """
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("catalog_recommendations_0101_optimized", sys.argv[1])
if spec is None or spec.loader is None:
    raise SystemExit(2)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class EmptyResult:
    def all(self):
        return []

class EmptyBind:
    def execute(self, *args, **kwargs):
        return EmptyResult()

try:
    module._assert_complete_state(EmptyBind())
except RuntimeError:
    raise SystemExit(0)
raise SystemExit(3)
"""
    completed = subprocess.run(  # noqa: S603 -- fixed interpreter and repository migration path
        [sys.executable, "-O", "-c", program, str(MIGRATION)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_regenerated_initial_schema_contains_exact_recommendation_contract() -> None:
    initial = (ROOT / "backend/alembic/versions/0001_initial_schema.py").read_text(encoding="utf-8")
    assert initial.count("op.create_table('metadata_recommendations'") == 1
    assert initial.count("op.create_table('metadata_recommendation_events'") == 1
    assert "guard_metadata_recommendation_mutation" in initial
    assert "decision_actor_id" in initial
