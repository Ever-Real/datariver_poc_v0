from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ClauseElement

from datariver.application.classification_access import static_classification_access_floor
from datariver.domain.authz import Classification, SubjectAttributes
from datariver.infrastructure.db.catalog import SqlCatalogIndexReader


class _MappingResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self) -> _MappingResult:
        return self

    def all(self) -> list[dict[str, object]]:
        return self._rows


class _Session:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows
        self.statements: list[object] = []

    async def execute(self, statement: object) -> _MappingResult:
        self.statements.append(statement)
        return _MappingResult(self._rows)


@pytest.mark.asyncio
async def test_facets_normalizes_classification_for_postgresql_union() -> None:
    """Keep PostgreSQL's UNION type contract explicit for mixed facet columns."""
    workspace_id = uuid4()
    observed_at = datetime(2035, 1, 1, tzinfo=UTC)
    session = _Session(
        [
            {
                "facet": "asset_type",
                "value": "DATASET",
                "count": 2,
                "observed_at": observed_at,
            },
            {
                "facet": "platform",
                "value": "postgres",
                "count": 2,
                "observed_at": observed_at,
            },
            {
                "facet": "classification",
                "value": str(int(Classification.INTERNAL)),
                "count": 2,
                "observed_at": observed_at,
            },
        ]
    )
    reader = SqlCatalogIndexReader(cast(AsyncSession, session))
    subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function=None,
        clearance=Classification.INTERNAL,
    )

    facets = await reader.facets(
        subject=subject,
        access=static_classification_access_floor(),
        query="",
        filters={},
        limit=10,
    )

    assert len(session.statements) == 1
    statement = cast(ClauseElement, session.statements[0]).compile(dialect=postgresql.dialect())
    sql = str(statement)
    assert "UNION ALL" in sql
    assert "CAST(catalog.assets_projection.asset_type AS VARCHAR) AS value" in sql
    assert "CAST(catalog.assets_projection.platform AS VARCHAR) AS value" in sql
    assert "CAST(catalog.assets_projection.classification AS VARCHAR) AS value" in sql
    assert facets.classifications[0].value == "INTERNAL"
