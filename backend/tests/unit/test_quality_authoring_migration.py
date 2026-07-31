from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "backend/alembic/versions/0071_quality_authoring_commands.py"


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("quality_authoring_0071", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_quality_authoring_migration_adds_only_server_derived_command_functions() -> None:
    migration = _load_migration()
    source = MIGRATION.read_text(encoding="utf-8")

    assert migration.revision == "0071"
    assert migration.down_revision == "0070"
    assert REQUIRED_DATABASE_REVISION == "0074"
    assert "review_rule_set_version_command_v2" in source
    assert "activate_rule_set_version_command_v2" in source
    assert "request_manual_validation_run_v1" in source
    assert "retention.resolve_quality_binding_v1" in source
    assert "quality.require_human_decision_v1" in source
    assert "quality.current_target_matches_v1" in source
    assert "quality.validation_run.queued.v1" in source
    assert "INSERT INTO integration.outbox_events" in source
    assert "GRANT EXECUTE" in source
    assert "GRANT INSERT" not in source


def test_quality_authoring_downgrade_removes_wrappers_in_reverse_dependency_order() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    downgrade = source.split("def downgrade()", maxsplit=1)[1]

    manual = downgrade.index("request_manual_validation_run_v1")
    activate = downgrade.index("activate_rule_set_version_command_v2")
    review = downgrade.index("review_rule_set_version_command_v2")
    assert manual < activate < review
