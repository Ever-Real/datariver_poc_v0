from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.ports import CatalogReaderMode
from datariver.domain.authz import Action, Classification, SubjectAttributes
from datariver.interfaces.http.dependencies import RequestContext
from datariver.interfaces.http.routes import governance as governance_routes
from datariver.interfaces.http.routes.governance import (
    _catalog_service,
    _change_request_system_scope,
    _change_target_catalog_service,
    list_change_request_systems,
    search_change_request_targets,
)


def _subject(
    *,
    groups: frozenset[str] = frozenset(),
    allowed_actions: frozenset[Action] = frozenset({Action.CHANGE_CREATE}),
    denied_actions: frozenset[Action] = frozenset(),
    allowed_system_ids: frozenset[UUID] = frozenset(),
    job_function: str | None = "DATA_STEWARD",
    active: bool = True,
    clearance: Classification = Classification.INTERNAL,
) -> SubjectAttributes:
    workspace_id = uuid4()
    return SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=active,
        department_id=None,
        groups=groups,
        job_function=job_function,
        clearance=clearance,
        allowed_actions=allowed_actions,
        denied_actions=denied_actions,
        allowed_system_ids=allowed_system_ids,
    )


def test_eligible_human_security_administrator_reads_all_active_systems() -> None:
    subject = _subject(
        groups=frozenset({"security-administrators"}),
        allowed_actions=frozenset({Action.ADMIN_MANAGE, Action.CHANGE_CREATE}),
        clearance=Classification.RESTRICTED,
    )

    assert _change_request_system_scope(subject) is None


def test_regular_subject_reads_only_explicitly_allowed_systems() -> None:
    system_ids = frozenset({uuid4(), uuid4()})

    assert _change_request_system_scope(_subject(allowed_system_ids=system_ids)) == system_ids


@pytest.mark.parametrize(
    "subject",
    [
        _subject(),
        _subject(allowed_actions=frozenset(), allowed_system_ids=frozenset({uuid4()})),
        _subject(
            denied_actions=frozenset({Action.CHANGE_CREATE}),
            allowed_system_ids=frozenset({uuid4()}),
        ),
        _subject(groups=frozenset({"security-administrators"})),
        _subject(
            groups=frozenset({"security-administrators"}),
            allowed_actions=frozenset({Action.ADMIN_MANAGE, Action.CHANGE_CREATE}),
            denied_actions=frozenset({Action.ADMIN_MANAGE}),
            clearance=Classification.RESTRICTED,
        ),
        _subject(
            groups=frozenset({"security-administrators", "service-accounts"}),
            allowed_actions=frozenset({Action.ADMIN_MANAGE, Action.CHANGE_CREATE}),
            allowed_system_ids=frozenset({uuid4()}),
            clearance=Classification.RESTRICTED,
        ),
        _subject(
            groups=frozenset({"security-administrators"}),
            allowed_actions=frozenset({Action.ADMIN_MANAGE, Action.CHANGE_CREATE}),
            allowed_system_ids=frozenset({uuid4()}),
            job_function="SERVICE_ACCOUNT",
            clearance=Classification.RESTRICTED,
        ),
        _subject(
            groups=frozenset({"security-administrators"}),
            allowed_actions=frozenset({Action.ADMIN_MANAGE, Action.CHANGE_CREATE}),
            allowed_system_ids=frozenset({uuid4()}),
            active=False,
            clearance=Classification.RESTRICTED,
        ),
    ],
)
def test_non_administrator_without_system_scope_reads_zero_systems(
    subject: SubjectAttributes,
) -> None:
    assert _change_request_system_scope(subject) == frozenset()


@pytest.mark.asyncio
async def test_empty_system_scope_returns_zero_without_querying_directory() -> None:
    subject = _subject()
    context = cast(
        RequestContext,
        SimpleNamespace(workspace_id=subject.workspace_id, subject=subject),
    )
    session = AsyncMock(spec=AsyncSession)

    response = await list_change_request_systems(
        context=context,
        session=cast(AsyncSession, session),
    )

    assert response.items == []
    session.scalars.assert_not_awaited()


def test_change_request_catalog_service_keeps_the_default_scoped_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = SimpleNamespace(
        datahub=object(),
        cache=object(),
        database=SimpleNamespace(session_factory=object()),
        metrics=None,
        settings=SimpleNamespace(
            cache_default_ttl_seconds=60,
            datahub_stale_ttl_seconds=900,
            catalog_search_cache_ttl_seconds=30,
            catalog_search_minimum_query_length=2,
        ),
    )
    monkeypatch.setattr(governance_routes, "get_container", lambda _: container)

    service = _catalog_service(cast(Any, object()), cast(Any, object()))
    change_service, change_reader = _change_target_catalog_service(
        cast(Any, object()), cast(Any, object())
    )

    assert service._reader_mode is CatalogReaderMode.SCOPED
    assert cast(Any, service._index)._reader_mode is CatalogReaderMode.SCOPED
    assert change_service._reader_mode is CatalogReaderMode.SCOPED
    assert change_service._index is change_reader
    assert change_service._search_cache_ttl_seconds == 0


def _context(subject: SubjectAttributes) -> RequestContext:
    return cast(
        RequestContext,
        SimpleNamespace(
            workspace_id=subject.workspace_id,
            subject=subject,
            environment=SimpleNamespace(requested_at=datetime(2026, 8, 2, tzinfo=UTC)),
            request_id="cr-target-directory-test",
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "subject",
    [
        _subject(),
        _subject(
            allowed_actions=frozenset(),
            allowed_system_ids=frozenset({uuid4()}),
        ),
        _subject(
            allowed_system_ids=frozenset({uuid4()}),
            job_function="SERVICE_ACCOUNT",
        ),
        _subject(
            groups=frozenset({"service-accounts"}),
            allowed_system_ids=frozenset({uuid4()}),
        ),
    ],
)
async def test_change_target_search_returns_zero_without_catalog_read_for_ineligible_subject(
    subject: SubjectAttributes,
) -> None:
    session = AsyncMock(spec=AsyncSession)

    response = await search_change_request_targets(
        request=cast(Any, object()),
        context=_context(subject),
        session=cast(AsyncSession, session),
        system_id=uuid4(),
        q="wafer",
        cursor=None,
        limit=12,
    )

    assert response.items == []
    assert response.total == 0
    session.scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_change_target_search_returns_zero_when_selected_system_is_inactive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system_id = uuid4()
    subject = _subject(allowed_system_ids=frozenset({system_id}))
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None
    catalog = AsyncMock()
    monkeypatch.setattr(
        governance_routes,
        "_change_target_catalog_service",
        lambda *_: (catalog, AsyncMock()),
    )

    response = await search_change_request_targets(
        request=cast(Any, object()),
        context=_context(subject),
        session=cast(AsyncSession, session),
        system_id=system_id,
        q="wafer",
        cursor=None,
        limit=12,
    )

    assert response.items == []
    session.scalar.assert_awaited_once()
    catalog.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_change_target_search_uses_selected_system_and_dataset_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system_id = uuid4()
    subject = _subject(allowed_system_ids=frozenset({system_id}))
    context = _context(subject)
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = system_id
    catalog = AsyncMock()
    catalog.search.return_value = SimpleNamespace(
        items=(),
        next_cursor=None,
        total=0,
        total_exact=True,
        observed_at=context.environment.requested_at,
        stale_at=None,
        projection_version=7,
        policy_version="policy-test",
        classification_policy_version=3,
        authorization_generation=9,
    )
    monkeypatch.setattr(
        governance_routes,
        "_change_target_catalog_service",
        lambda *_: (catalog, AsyncMock()),
    )

    response = await search_change_request_targets(
        request=cast(Any, object()),
        context=context,
        session=cast(AsyncSession, session),
        system_id=system_id,
        q="wafer",
        cursor=None,
        limit=12,
    )

    assert response.total == 0
    catalog.search.assert_awaited_once_with(
        subject=subject,
        query="wafer",
        filters={
            "asset_types": ("DATASET", "TABLE", "VIEW"),
            "routing_system_id": system_id,
        },
        cursor=None,
        limit=12,
        environment=context.environment,
        request_id=context.request_id,
    )
