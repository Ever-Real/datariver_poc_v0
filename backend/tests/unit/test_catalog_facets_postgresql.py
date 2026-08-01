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
from datariver.application.ports import CatalogReaderMode
from datariver.domain.authz import Classification, SubjectAttributes
from datariver.domain.classification_access import SearchMode
from datariver.domain.common import ValidationError
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


def test_catalog_system_filter_is_uuid_typed_and_applied_before_paging() -> None:
    system_id = uuid4()
    conditions = SqlCatalogIndexReader._filter_conditions(
        {"asset_types": ("DATASET", "TABLE", "VIEW"), "system_id": system_id}
    )
    statement = select(AssetProjectionModel.id).where(*conditions)
    dialect = cast(Any, postgresql).dialect()
    compiled = cast(Any, statement).compile(dialect=dialect)

    assert "catalog.assets_projection.system_id =" in str(compiled)
    assert system_id in compiled.params.values()
    assert "catalog.assets_projection.asset_type IN" in str(compiled)


@pytest.mark.parametrize("system_id", ["not-a-uuid", "", 1, True])
def test_catalog_system_filter_rejects_non_uuid_values(system_id: object) -> None:
    with pytest.raises(ValidationError, match="Unsupported catalog System filter"):
        SqlCatalogIndexReader._filter_conditions({"system_id": system_id})


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


def test_workspace_discovery_omits_nonrestricted_system_and_domain_predicates() -> None:
    workspace_id = uuid4()
    subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function="USER",
        clearance=Classification.CONFIDENTIAL,
        allowed_system_ids=frozenset(),
        allowed_domain_ids=frozenset(),
    )
    reader = SqlCatalogIndexReader(cast(AsyncSession, _Session([])))
    scoped = _compile_postgresql(
        select(AssetProjectionModel.id).where(
            *reader._scope_conditions(subject, static_classification_access_floor())
        )
    )
    discovery = _compile_postgresql(
        select(AssetProjectionModel.id).where(
            *reader._scope_conditions(
                subject,
                static_classification_access_floor(),
                CatalogReaderMode.WORKSPACE_DISCOVERY,
            )
        )
    )

    assert "workspace_id" in discovery
    assert "deleted_at" in discovery
    assert "lifecycle" in discovery
    assert "classification" in discovery
    assert "system_id" in scoped
    assert "domain_id" in scoped
    assert "system_id" not in discovery
    assert "domain_id" not in discovery


@pytest.mark.parametrize(
    ("active", "job_function", "groups"),
    [
        (False, "USER", frozenset()),
        (True, "SERVICE_ACCOUNT", frozenset({"service-accounts"})),
    ],
)
def test_workspace_discovery_rejects_inactive_and_service_subjects_before_read(
    active: bool,
    job_function: str,
    groups: frozenset[str],
) -> None:
    subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=uuid4(),
        active=active,
        department_id=None,
        groups=groups,
        job_function=job_function,
        clearance=Classification.CONFIDENTIAL,
    )
    reader = SqlCatalogIndexReader(cast(AsyncSession, _Session([])))
    discovery = _compile_postgresql(
        select(AssetProjectionModel.id).where(
            *reader._scope_conditions(
                subject,
                static_classification_access_floor(),
                CatalogReaderMode.WORKSPACE_DISCOVERY,
            )
        )
    )

    assert "WHERE false" in discovery


def test_workspace_discovery_restricted_branch_keeps_grant_and_scope_intersection() -> None:
    workspace_id = uuid4()
    system_id, domain_id, asset_id = uuid4(), uuid4(), uuid4()
    subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function="USER",
        clearance=Classification.RESTRICTED,
        allowed_system_ids=frozenset({system_id}),
        allowed_domain_ids=frozenset({domain_id}),
    )
    access = static_classification_access_floor()
    access = replace(
        access,
        rules=tuple(
            replace(rule, search_mode=SearchMode.EXPLICIT_GRANT_ONLY)
            if rule.classification is Classification.RESTRICTED
            else rule
            for rule in access.rules
        ),
        restricted_resource_ids=frozenset({asset_id}),
    )
    reader = SqlCatalogIndexReader(cast(AsyncSession, _Session([])))

    sql = _compile_postgresql(
        select(AssetProjectionModel.id).where(
            *reader._scope_conditions(
                subject,
                access,
                CatalogReaderMode.WORKSPACE_DISCOVERY,
            )
        )
    )

    assert "classification" in sql
    assert "catalog.assets_projection.id IN" in sql
    assert "system_id IN" in sql
    assert "domain_id IN" in sql
