from __future__ import annotations

from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.interfaces.http.routes.operations import _catalog_coverage


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
        self.statements: list[object] = []

    async def execute(self, statement: object) -> FakeResult:
        self.statements.append(statement)
        return FakeResult(self.responses.pop(0))


@pytest.mark.asyncio
async def test_catalog_coverage_returns_only_aggregate_typed_projection_metrics() -> None:
    session = FakeCoverageSession(
        [
            (4, 2),
            [
                ("postgres", "warehouse", "core", 3, 2),
                (None, None, None, 1, 0),
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
        },
        {
            "platform": None,
            "database_name": None,
            "schema_name": None,
            "asset_count": 1,
            "described_asset_count": 0,
        },
    ]
    assert len(session.statements) == 2


@pytest.mark.asyncio
async def test_catalog_coverage_marks_the_dashboard_schema_limit_explicitly() -> None:
    rows = [("postgres", "warehouse", f"schema_{index}", 1, 1) for index in range(201)]
    session = FakeCoverageSession([(201, 201), rows])

    assets, described, metrics, truncated = await _catalog_coverage(
        cast(AsyncSession, session), uuid4()
    )

    assert (assets, described, truncated) == (201, 201, True)
    assert len(metrics) == 200
    assert metrics[-1].schema_name == "schema_199"
