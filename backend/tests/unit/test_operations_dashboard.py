from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ClauseElement

from datariver.interfaces.http.routes.operations import (
    _catalog_coverage,
    _catalog_glossary_term_count,
)


class FakeResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def one(self) -> tuple[object, ...]:
        assert isinstance(self.value, tuple)
        return self.value

    def all(self) -> list[tuple[object, ...]]:
        assert isinstance(self.value, list)
        return self.value


class FakeCoverageSession:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.statements: list[ClauseElement] = []

    async def execute(self, statement: ClauseElement) -> FakeResult:
        self.statements.append(statement)
        return FakeResult(self.responses.pop(0))

    async def scalar(self, statement: ClauseElement) -> object:
        self.statements.append(statement)
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_catalog_coverage_returns_only_aggregate_typed_projection_metrics() -> None:
    session = FakeCoverageSession(
        [
            (4, 2),
            [
                ("postgres", "warehouse", "core", 3, 2, 1, 0),
                (None, None, None, 1, 0, 0, 1),
            ],
        ]
    )

    assets, described, metrics, truncated = await _catalog_coverage(
        cast(AsyncSession, session), uuid4()
    )

    assert (assets, described, truncated) == (4, 2, False)
    assert [metric.model_dump() for metric in metrics] == [
        {
            "platform": "postgres",
            "database_name": "warehouse",
            "schema_name": "core",
            "asset_count": 3,
            "described_asset_count": 2,
            "tagged_asset_count": 1,
            "term_asset_count": 0,
        },
        {
            "platform": None,
            "database_name": None,
            "schema_name": None,
            "asset_count": 1,
            "described_asset_count": 0,
            "tagged_asset_count": 0,
            "term_asset_count": 1,
        },
    ]
    assert all("external_urn" not in metric.model_dump() for metric in metrics)
    assert all("name" not in metric.model_dump() for metric in metrics)
    assert len(session.statements) == 2


@pytest.mark.asyncio
async def test_catalog_coverage_excludes_deleted_and_inactive_assets_from_denominators() -> None:
    workspace_id = uuid4()
    session = FakeCoverageSession([(0, 0), []])

    await _catalog_coverage(cast(AsyncSession, session), workspace_id)

    dialect = cast(Any, postgresql.dialect)()
    statements = [
        str(
            statement.compile(
                dialect=dialect,
                compile_kwargs={"literal_binds": True},
            )
        )
        for statement in session.statements
    ]
    assert len(statements) == 2
    for sql in statements:
        assert str(workspace_id) in sql
        assert "assets_projection.deleted_at IS NULL" in sql
        assert "assets_projection.lifecycle = 'ACTIVE'" in sql
        assert "assets_projection.external_urn" not in sql
        assert "assets_projection.name," not in sql

    metric_sql = statements[1]
    assert "jsonb_array_length(catalog.assets_projection.tags) > 0" in metric_sql
    assert "jsonb_array_length(catalog.assets_projection.glossary_terms) > 0" in metric_sql


@pytest.mark.asyncio
async def test_catalog_coverage_marks_the_dashboard_schema_limit_explicitly() -> None:
    rows = [("postgres", "warehouse", f"schema_{index}", 1, 1, 0, 0) for index in range(201)]
    session = FakeCoverageSession([(201, 201), rows])

    assets, described, metrics, truncated = await _catalog_coverage(
        cast(AsyncSession, session), uuid4()
    )

    assert (assets, described, truncated) == (201, 201, True)
    assert len(metrics) == 200
    assert metrics[-1].schema_name == "schema_199"


@pytest.mark.asyncio
async def test_glossary_count_uses_active_typed_term_vocabulary() -> None:
    session = FakeCoverageSession([7])

    count = await _catalog_glossary_term_count(cast(AsyncSession, session), uuid4())

    assert count == 7
    sql = str(session.statements[0])
    assert "catalog.vocabulary_entries" in sql
    assert "vocabulary_entries.kind" in sql
    assert "vocabulary_entries.lifecycle" in sql
