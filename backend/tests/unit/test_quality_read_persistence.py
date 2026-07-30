from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import cast

from fastapi.routing import APIRoute
from sqlalchemy import Table

from datariver.infrastructure.db.models.quality import (
    QualityExpectationResultModel,
    QualityRuleSetModel,
    QualityValidationRunModel,
)
from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION
from datariver.interfaces.http.routes.quality import router as quality_router

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "backend/alembic/versions/0070_quality_read_model_indexes.py"
CANONICAL = ROOT / "backend/alembic/versions/0001_initial_schema.py"


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("quality_read_0070", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_quality_read_indexes_are_metadata_migration_and_baseline_consistent() -> None:
    migration = _load_migration()
    assert migration.revision == "0070"
    assert migration.down_revision == "0069"
    assert REQUIRED_DATABASE_REVISION == "0071"

    expected = {
        "ix_quality_rule_sets_list",
        "ix_quality_validation_runs_list",
        "ix_quality_expectation_results_issues",
    }
    metadata_indexes = {
        index.name
        for table in (
            QualityRuleSetModel.__table__,
            QualityValidationRunModel.__table__,
            QualityExpectationResultModel.__table__,
        )
        for index in cast(Table, table).indexes
    }
    assert expected <= metadata_indexes
    migration_source = MIGRATION.read_text(encoding="utf-8")
    canonical_source = CANONICAL.read_text(encoding="utf-8")
    for name in expected:
        assert name in migration_source
        assert name in canonical_source


def test_quality_issue_index_remains_failure_only() -> None:
    migration_source = MIGRATION.read_text(encoding="utf-8")
    canonical_source = CANONICAL.read_text(encoding="utf-8")
    predicate = "outcome IN ('ADVISORY_FAIL','BLOCKING_FAIL')"
    assert predicate in migration_source
    assert predicate in canonical_source


def test_public_quality_surface_exposes_only_bounded_quality_commands() -> None:
    routes = {
        (method, route.path)
        for route in quality_router.routes
        if isinstance(route, APIRoute)
        for method in getattr(route, "methods", set())
        if route.path.startswith("/quality")
    }
    assert {
        ("GET", "/quality/capability"),
        ("GET", "/quality/rule-definitions"),
        ("GET", "/quality/overview"),
        ("GET", "/quality/assets"),
        ("GET", "/quality/assets/{asset_id}"),
        ("GET", "/quality/rule-sets"),
        ("GET", "/quality/rule-sets/{rule_set_id}"),
        ("GET", "/quality/runs"),
        ("GET", "/quality/runs/{run_id}"),
        ("GET", "/quality/runs/{run_id}/results"),
        ("GET", "/quality/issues"),
    } <= routes
    assert {
        ("POST", "/quality/rule-sets"),
        (
            "POST",
            "/quality/rule-sets/{rule_set_id}/versions/{version_id}/reviews",
        ),
        (
            "POST",
            "/quality/rule-sets/{rule_set_id}/versions/{version_id}/activations",
        ),
        ("POST", "/quality/runs"),
    } <= routes
    assert not {
        (method, path)
        for method, path in routes
        if method not in {"GET", "POST"} and not path.startswith("/quality/internal/")
    }
