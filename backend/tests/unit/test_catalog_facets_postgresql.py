from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ClauseElement

from datariver.application.classification_access import static_classification_access_floor
from datariver.domain.authz import Classification, SubjectAttributes
from datariver.infrastructure.db.catalog import SqlCatalogIndexReader, _encode_cursor
from datariver.infrastructure.db.models.catalog import AssetProjectionModel


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


class _ScalarResult:
    def all(self) -> list[object]:
        return []


class _SearchSession:
    def __init__(self) -> None:
        self.statements: list[object] = []

    async def scalars(self, statement: object) -> _ScalarResult:
        self.statements.append(statement)
        return _ScalarResult()


def _compile_postgresql(statement: ClauseElement) -> str:
    compiler = cast(Any, statement).compile
    dialect = cast(Any, postgresql).dialect()
    return str(compiler(dialect=dialect))


@pytest.mark.asyncio
async def test_facets_use_one_bounded_grouping_sets_query() -> None:
    """Keep mixed facet values typed while avoiding seven repeated base scans."""
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
                "facet": "database",
                "value": "manufacturing",
                "count": 2,
                "observed_at": observed_at,
            },
            {
                "facet": "schema",
                "value": "yield",
                "count": 2,
                "observed_at": observed_at,
            },
            {
                "facet": "domain",
                "value": "urn:li:domain:semiconductor",
                "count": 2,
                "observed_at": observed_at,
            },
            {
                "facet": "classification",
                "value": str(int(Classification.INTERNAL)),
                "count": 2,
                "observed_at": observed_at,
            },
            {
                "facet": "lifecycle",
                "value": "ACTIVE",
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
    sql = _compile_postgresql(cast(ClauseElement, session.statements[0]))
    assert "UNION ALL" not in sql
    assert "GROUPING SETS" in sql
    assert "row_number() OVER (PARTITION BY" in sql
    assert "facet_rank <=" in sql
    for column in (
        "asset_type",
        "platform",
        "database_name",
        "schema_name",
        "domain_ref",
        "classification",
        "lifecycle",
    ):
        assert f"CAST(catalog.assets_projection.{column} AS VARCHAR)" in sql
    assert facets.classifications[0].value == "INTERNAL"
    assert facets.databases[0].value == "manufacturing"
    assert facets.schemas[0].value == "yield"
    assert facets.domains[0].value == "urn:li:domain:semiconductor"
    assert facets.lifecycles[0].value == "ACTIVE"


@pytest.mark.asyncio
async def test_search_uses_only_the_bounded_page_query_and_declares_exactness() -> None:
    workspace_id = uuid4()
    subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function=None,
        clearance=Classification.INTERNAL,
    )
    session = _SearchSession()
    reader = SqlCatalogIndexReader(cast(AsyncSession, session))

    first = await reader.search(
        subject=subject,
        access=static_classification_access_floor(),
        query="",
        filters={},
        cursor=None,
        limit=25,
    )
    continuation = await reader.search(
        subject=subject,
        access=static_classification_access_floor(),
        query="",
        filters={},
        cursor=_encode_cursor("asset", uuid4()),
        limit=25,
    )

    assert len(session.statements) == 2
    assert first.total == 0
    assert first.total_exact is True
    assert continuation.total_exact is False


def test_quarantine_review_scope_keeps_workspace_and_tombstone_boundaries() -> None:
    workspace_id = uuid4()
    subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset({"security-administrators"}),
        job_function="SECURITY_ADMINISTRATOR",
        clearance=Classification.RESTRICTED,
    )
    reader = SqlCatalogIndexReader(cast(AsyncSession, _Session([])))
    standard = _compile_postgresql(
        select(AssetProjectionModel.id).where(
            *reader._scope_conditions(subject, static_classification_access_floor())
        )
    )
    review_access = replace(static_classification_access_floor(), admin_quarantine_review=True)
    review = _compile_postgresql(
        select(AssetProjectionModel.id).where(*reader._scope_conditions(subject, review_access))
    )

    assert "workspace_id" in review
    assert "deleted_at" in review
    assert "lifecycle" in standard
    assert "classification" in standard
    assert "lifecycle" not in review
    assert "classification" not in review
