from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.infrastructure.db.models.quality import (
    QualityExpectationResultModel,
    QualityRuleSetModel,
    QualityValidationRunModel,
)
from datariver.infrastructure.db.quality_read import (
    SqlQualityReadRepository,
    _AssetQualityAggregate,
    _DashboardRuleMetric,
    _managed_rule_sets,
    _rule_dashboard_indicator,
)
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


class _AggregateRows:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows

    def all(self) -> list[SimpleNamespace]:
        return self._rows


class _AggregateSession:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows
        self.statement: Any = None

    async def execute(self, statement: Any) -> _AggregateRows:
        self.statement = statement
        return _AggregateRows(self._rows)


@pytest.mark.asyncio
async def test_asset_score_pools_latest_successful_active_rule_set_results() -> None:
    workspace_id, asset_id = uuid4(), uuid4()
    session = _AggregateSession(
        [
            SimpleNamespace(
                asset_id=asset_id,
                passed=13,
                advisory=1,
                blocking=0,
            )
        ]
    )
    repository = SqlQualityReadRepository(cast(AsyncSession, session))

    aggregates = await repository._latest_active_rule_set_aggregates(
        workspace_id=workspace_id,
        asset_ids=(asset_id,),
    )

    aggregate = aggregates[asset_id]
    assert aggregate.evaluated_rule_count == 14
    assert aggregate.score_basis_points == 9_286
    assert aggregate.outcome == "WARN"

    sql = " ".join(
        str(
            session.statement.compile(
                compile_kwargs={"literal_binds": True},
            )
        ).split()
    )
    assert "quality.rule_sets.state = 'ACTIVE'" in sql
    assert "quality.rule_set_versions.state = 'ACTIVE'" in sql
    assert "quality.validation_runs.state = 'SUCCEEDED'" in sql
    assert (
        "row_number() OVER (PARTITION BY active_asset_quality_versions.asset_id, "
        "active_asset_quality_versions.rule_set_id "
        "ORDER BY quality.validation_runs.completed_at DESC, "
        "quality.validation_runs.id DESC)"
    ) in sql
    assert "ranked_active_asset_quality_runs.ordinal = 1" in sql
    assert "GROUP BY ranked_active_asset_quality_runs.asset_id" in sql


def test_asset_score_uses_blocking_failure_precedence() -> None:
    aggregate = _AssetQualityAggregate(
        passed_count=99,
        advisory_failed_count=0,
        blocking_failed_count=1,
    )

    assert aggregate.score_basis_points == 9_900
    assert aggregate.outcome == "FAIL"


def test_dashboard_indicator_uses_value_weighted_latest_success_evidence() -> None:
    metric = _DashboardRuleMetric(
        counted_target_count=3,
        target_count=4,
        valid_value_count=95,
        evaluated_value_count=100,
        advisory_failed_count=1,
        blocking_failed_count=0,
        risk_count=1,
    )

    indicator = _rule_dashboard_indicator(
        indicator_id="COMPLETENESS",
        metric=metric,
        risks=(),
    )

    assert indicator.coverage_basis_points == 7_500
    assert indicator.score_basis_points == 9_500
    assert indicator.outcome == "WARN"
    assert indicator.report_state == "FACTS_ONLY"
    assert indicator.report_reason_code == "QUALITY_LLM_REPORT_ROUTE_UNAVAILABLE"


def test_dashboard_managed_indicators_are_versioned_and_complete() -> None:
    definitions = _managed_rule_sets()

    assert {definition.indicator_id for definition in definitions} == {
        "ACCURACY",
        "COMPLETENESS",
        "TIMELINESS",
    }
    assert {definition.contract_version for definition in definitions} == {
        "QUALITY_MANAGED_INDICATORS_V1"
    }
    assert (
        next(
            definition for definition in definitions if definition.indicator_id == "TIMELINESS"
        ).rule_kinds
        == ()
    )


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
        ("GET", "/quality/dashboard"),
        ("GET", "/quality/assets"),
        ("POST", "/quality/assets/summary-batch"),
        ("GET", "/quality/assets/{asset_id}"),
        ("GET", "/quality/assets/{asset_id}/workspace"),
        ("GET", "/quality/common-rule-templates"),
        ("GET", "/quality/common-rule-templates/{template_id}"),
        ("GET", "/quality/rule-sets"),
        ("GET", "/quality/rule-sets/{rule_set_id}"),
        ("GET", "/quality/runs"),
        ("GET", "/quality/runs/{run_id}"),
        ("GET", "/quality/runs/{run_id}/results"),
        ("GET", "/quality/issues"),
    } <= routes
    assert {
        ("POST", "/quality/rule-sets"),
        ("POST", "/quality/common-rule-templates"),
        (
            "POST",
            "/quality/common-rule-templates/{template_id}/mappings",
        ),
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
