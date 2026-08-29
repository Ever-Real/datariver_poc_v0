from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.classification_access import static_classification_access_floor
from datariver.application.quality_read_contracts import QualityReadContext
from datariver.domain.authz import Classification, SubjectAttributes
from datariver.domain.common import ValidationError
from datariver.infrastructure.db.models.quality import (
    QualityExpectationResultModel,
    QualityRuleSetModel,
    QualityValidationRunModel,
)
from datariver.infrastructure.db.quality_read import (
    SqlQualityReadRepository,
    _asset_cursor_resource,
    _AssetQualityAggregate,
    _DashboardRuleMetric,
    _decode_cursor,
    _encode_cursor,
    _field_run_quality,
    _FieldQualityAggregate,
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


def test_quality_asset_cursor_is_bound_to_every_metadata_filter() -> None:
    base = _asset_cursor_resource(
        query="customer",
        platform="postgres",
        database_name="analytics",
        schema_name="public",
    )

    assert base != _asset_cursor_resource(
        query="orders",
        platform="postgres",
        database_name="analytics",
        schema_name="public",
    )
    assert base != _asset_cursor_resource(
        query="customer",
        platform="snowflake",
        database_name="analytics",
        schema_name="public",
    )
    assert base != _asset_cursor_resource(
        query="customer",
        platform="postgres",
        database_name="warehouse",
        schema_name="public",
    )
    assert base != _asset_cursor_resource(
        query="customer",
        platform="postgres",
        database_name="analytics",
        schema_name="reporting",
    )


def test_quality_asset_cursor_rejects_another_authorization_scope() -> None:
    workspace_id = uuid4()
    subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function="DATA_STEWARD",
        clearance=Classification.RESTRICTED,
    )
    now = datetime(2026, 7, 30, tzinfo=UTC)
    context = QualityReadContext(
        subject=subject,
        access=static_classification_access_floor(),
        observed_at=now,
        authorization_valid_until=now,
        cache_scope="a" * 64,
        profile_allowed=False,
    )
    cursor = _encode_cursor(
        resource=_asset_cursor_resource(
            query="orders",
            platform="postgres",
            database_name="analytics",
            schema_name="public",
        ),
        context=context,
        limit=25,
        boundary={"name": "orders", "id": str(uuid4())},
    )
    changed_scope = QualityReadContext(
        subject=subject,
        access=context.access,
        observed_at=now,
        authorization_valid_until=now,
        cache_scope="b" * 64,
        profile_allowed=False,
    )

    with pytest.raises(ValidationError, match="stale or does not match"):
        _decode_cursor(
            cursor,
            resource=_asset_cursor_resource(
                query="orders",
                platform="postgres",
                database_name="analytics",
                schema_name="public",
            ),
            context=changed_scope,
            limit=25,
        )


class _EmptyScalarRows:
    def all(self) -> list[Any]:
        return []


class _MetadataPreviewSession:
    def __init__(self) -> None:
        self.statement: Any = None
        self.count_statement: Any = None
        self.scalar_calls = 0
        self.scalars_calls = 0

    async def scalar(self, statement: Any) -> int:
        self.scalar_calls += 1
        self.count_statement = statement
        return 137

    async def scalars(self, statement: Any) -> _EmptyScalarRows:
        self.scalars_calls += 1
        self.statement = statement
        return _EmptyScalarRows()


@pytest.mark.asyncio
async def test_authorized_asset_preview_intersects_canonical_metadata_conditions() -> None:
    workspace_id = uuid4()
    subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function="DATA_STEWARD",
        clearance=Classification.RESTRICTED,
    )
    now = datetime(2026, 7, 30, tzinfo=UTC)
    context = QualityReadContext(
        subject=subject,
        access=static_classification_access_floor(),
        observed_at=now,
        authorization_valid_until=now,
        cache_scope="a" * 64,
        profile_allowed=False,
    )
    session = _MetadataPreviewSession()

    page = await SqlQualityReadRepository(cast(AsyncSession, session)).list_assets(
        context=context,
        limit=25,
        cursor=None,
        query="orders",
        platform="postgres",
        database_name="analytics",
        schema_name="public",
    )

    assert page.items == ()
    assert page.total_count == 137
    assert session.scalar_calls == 1
    assert session.scalars_calls == 1
    sql = " ".join(str(session.statement).split())
    count_sql = " ".join(str(session.count_statement).split())
    assert "lower(catalog.assets_projection.name) LIKE lower" in sql
    assert "catalog.assets_projection.platform =" in sql
    assert "catalog.assets_projection.database_name =" in sql
    assert "catalog.assets_projection.schema_name =" in sql
    assert "catalog.assets_projection.workspace_id =" in sql
    assert "catalog.assets_projection.platform =" in count_sql
    assert "catalog.assets_projection.database_name =" in count_sql
    assert "catalog.assets_projection.schema_name =" in count_sql
    assert "catalog.assets_projection.workspace_id =" in count_sql
    assert "lower(catalog.assets_projection.description)" not in sql
    assert "catalog.assets_projection.tags @>" not in sql
    assert "catalog.assets_projection.glossary_terms @>" not in sql


@pytest.mark.asyncio
async def test_authorized_asset_preview_next_page_does_not_recount() -> None:
    workspace_id = uuid4()
    subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function="DATA_STEWARD",
        clearance=Classification.RESTRICTED,
    )
    now = datetime(2026, 7, 30, tzinfo=UTC)
    context = QualityReadContext(
        subject=subject,
        access=static_classification_access_floor(),
        observed_at=now,
        authorization_valid_until=now,
        cache_scope="a" * 64,
        profile_allowed=False,
    )
    cursor = _encode_cursor(
        resource=_asset_cursor_resource(
            query="orders",
            platform="postgres",
            database_name="analytics",
            schema_name="public",
        ),
        context=context,
        limit=25,
        boundary={"name": "orders", "id": str(uuid4())},
    )
    session = _MetadataPreviewSession()

    page = await SqlQualityReadRepository(cast(AsyncSession, session)).list_assets(
        context=context,
        limit=25,
        cursor=cursor,
        query="orders",
        platform="postgres",
        database_name="analytics",
        schema_name="public",
    )

    assert page.items == ()
    assert page.total_count is None
    assert session.scalar_calls == 0
    assert session.scalars_calls == 1


@pytest.mark.asyncio
async def test_authorized_asset_preview_invalid_cursor_makes_no_database_calls() -> None:
    workspace_id = uuid4()
    subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function="DATA_STEWARD",
        clearance=Classification.RESTRICTED,
    )
    now = datetime(2026, 7, 30, tzinfo=UTC)
    context = QualityReadContext(
        subject=subject,
        access=static_classification_access_floor(),
        observed_at=now,
        authorization_valid_until=now,
        cache_scope="a" * 64,
        profile_allowed=False,
    )
    session = _MetadataPreviewSession()

    with pytest.raises(ValidationError, match="stale or does not match"):
        await SqlQualityReadRepository(cast(AsyncSession, session)).list_assets(
            context=context,
            limit=25,
            cursor="invalid",
            query="orders",
            platform="postgres",
            database_name="analytics",
            schema_name="public",
        )

    assert session.scalar_calls == 0
    assert session.scalars_calls == 0


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


@pytest.mark.parametrize(
    ("aggregate", "score", "outcome"),
    [
        (_FieldQualityAggregate(passed_count=3), 10_000, "PASS"),
        (
            _FieldQualityAggregate(passed_count=3, advisory_failed_count=1),
            7_500,
            "WARN",
        ),
        (
            _FieldQualityAggregate(passed_count=99, blocking_failed_count=1),
            9_900,
            "FAIL",
        ),
        (_FieldQualityAggregate(), None, "UNKNOWN"),
    ],
)
def test_field_score_uses_existing_unweighted_v1_policy(
    aggregate: _FieldQualityAggregate,
    score: int | None,
    outcome: str,
) -> None:
    assert aggregate.score_basis_points == score
    assert aggregate.outcome == outcome


def test_non_success_field_run_never_turns_partial_evidence_into_quality_outcome() -> None:
    assert _field_run_quality(
        state="FAILED",
        passed=9,
        advisory_failed=0,
        blocking_failed=1,
    ) == ("UNKNOWN", None)
    assert _field_run_quality(
        state="SUCCEEDED",
        passed=9,
        advisory_failed=1,
        blocking_failed=0,
    ) == ("WARN", 9_000)


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
        (
            "GET",
            "/quality/assets/{asset_id}/fields/{field_identifier}/workspace",
        ),
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
