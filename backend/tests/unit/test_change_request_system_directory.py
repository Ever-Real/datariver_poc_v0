from __future__ import annotations

import inspect
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import Response
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.ports import CatalogReaderMode
from datariver.domain.authz import Action, Classification, SubjectAttributes
from datariver.domain.common import ForbiddenError, NotFoundError
from datariver.domain.governance import (
    CHANGE_INTAKE_ASPECT,
    MANUAL_DATASET_INTAKE_TARGET,
    ChangeItem,
    ChangeRequest,
    ChangeState,
)
from datariver.interfaces.http.dependencies import RequestContext
from datariver.interfaces.http.routes import governance as governance_routes
from datariver.interfaces.http.routes.governance import (
    _catalog_service,
    _change_intake_items,
    _change_request_system_scope,
    _change_target_catalog_service,
    create_change_request_intake,
    get_change_request,
    get_change_request_revision_target,
    get_change_request_target,
    list_change_request_systems,
    revise_change_request_intake,
    search_change_request_revision_targets,
    search_change_request_targets,
)
from datariver.interfaces.http.schemas import ChangeRequestRevisionCreate


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


def test_change_request_catalog_service_uses_only_the_change_target_reader_mode(
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
    assert change_service._reader_mode is CatalogReaderMode.CHANGE_TARGET
    assert cast(Any, change_service._index)._reader_mode is CatalogReaderMode.CHANGE_TARGET
    assert change_service._index is change_reader
    assert change_service._search_cache_ttl_seconds == 0


def test_change_target_detail_and_intake_share_the_routed_cr_catalog_boundary() -> None:
    detail_source = inspect.getsource(get_change_request_target)
    intake_builder_source = inspect.getsource(_change_intake_items)

    for source in (detail_source, intake_builder_source):
        assert "_change_target_catalog_service" in source
        assert "route_authorized_detail" in source
    assert "_change_intake_items" in inspect.getsource(create_change_request_intake)
    assert "_change_intake_items" in inspect.getsource(revise_change_request_intake)


def test_revision_target_directory_is_request_anchored_and_has_no_create_scope_fallback() -> None:
    search_source = inspect.getsource(search_change_request_revision_targets)
    detail_source = inspect.getsource(get_change_request_revision_target)
    system_source = inspect.getsource(governance_routes._revision_system_id)

    assert "_revision_system_id" in search_source
    assert "_revision_system_id" in detail_source
    assert "get_change_request_for_revision" in system_source
    assert "_change_request_system_scope" not in search_source
    assert "_change_request_system_scope" not in detail_source
    assert "action=Action.CHANGE_CREATE" not in search_source + detail_source + system_source


def _editable_request(*, subject: SubjectAttributes, system_id: UUID) -> ChangeRequest:
    item_id = uuid4()
    value = ChangeRequest.create(
        workspace_id=subject.workspace_id,
        number="CR-REVISION-PREFLIGHT",
        request_type="CHANGE_INTAKE",
        title="Editable request",
        description="Correct the requested table.",
        requester_id=subject.subject_id,
        items=[
            ChangeItem(
                item_id=item_id,
                target_type=MANUAL_DATASET_INTAKE_TARGET,
                target_ref=f"urn:datariver:proposed-dataset:{item_id}",
                operation="CREATE",
                aspect_name=CHANGE_INTAKE_ASPECT,
                after_document={"contract": "change-intake-v1"},
                routing_system_id=system_id,
            )
        ],
        request_reason="Correct the requested table.",
        selected_system_id=system_id,
    )
    value.state = ChangeState.CHANGES_REQUESTED
    value.events.clear()
    return value


@pytest.mark.asyncio
async def test_revision_system_restores_rls_before_active_system_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system_id = uuid4()
    subject = _subject(
        allowed_actions=frozenset({Action.CHANGE_EDIT}),
        allowed_system_ids=frozenset({system_id}),
    )
    value = _editable_request(subject=subject, system_id=system_id)
    events: list[str] = []
    service = SimpleNamespace(get_change_request_for_revision=AsyncMock())

    async def preflight(**_: object) -> ChangeRequest:
        events.append("service-commit")
        return value

    async def restore_context(*_: object, **__: object) -> None:
        events.append("security-context")

    async def read_system(_: object) -> UUID:
        events.append("system-read")
        return system_id

    service.get_change_request_for_revision.side_effect = preflight
    session = AsyncMock(spec=AsyncSession)
    session.scalar.side_effect = read_system
    monkeypatch.setattr(governance_routes, "_service", lambda *_: service)
    monkeypatch.setattr(governance_routes, "set_security_context", restore_context)

    observed = await governance_routes._revision_system_id(
        change_request_id=value.change_request_id,
        request=cast(Any, object()),
        context=_context(subject),
        session=cast(AsyncSession, session),
    )

    assert observed == system_id
    assert events == ["service-commit", "security-context", "system-read"]


@pytest.mark.asyncio
async def test_change_request_detail_only_claims_revision_for_authorized_requester(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system_id = uuid4()
    requester = _subject(
        allowed_actions=frozenset({Action.CHANGE_EDIT}),
        allowed_system_ids=frozenset({system_id}),
    )
    value = _editable_request(subject=requester, system_id=system_id)
    other = replace(
        _subject(allowed_actions=frozenset({Action.CHANGE_READ})),
        workspace_id=requester.workspace_id,
    )
    service = SimpleNamespace(
        get_change_request=AsyncMock(return_value=value),
        get_change_request_for_revision=AsyncMock(return_value=value),
    )
    monkeypatch.setattr(governance_routes, "_service", lambda *_: service)

    other_response = await get_change_request(
        change_request_id=value.change_request_id,
        request=cast(Any, object()),
        response=Response(),
        context=_context(other),
        session=cast(AsyncSession, AsyncMock(spec=AsyncSession)),
    )

    assert other_response.revision_allowed is False
    service.get_change_request_for_revision.assert_not_awaited()

    service.get_change_request_for_revision.side_effect = ForbiddenError(
        "The requested action is not permitted."
    )
    denied_response = await get_change_request(
        change_request_id=value.change_request_id,
        request=cast(Any, object()),
        response=Response(),
        context=_context(requester),
        session=cast(AsyncSession, AsyncMock(spec=AsyncSession)),
    )

    assert denied_response.revision_allowed is False

    service.get_change_request_for_revision.reset_mock(side_effect=True)
    service.get_change_request_for_revision.return_value = value
    requester_response = await get_change_request(
        change_request_id=value.change_request_id,
        request=cast(Any, object()),
        response=Response(),
        context=_context(requester),
        session=cast(AsyncSession, AsyncMock(spec=AsyncSession)),
    )

    assert requester_response.revision_allowed is True
    service.get_change_request_for_revision.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["non-requester", "rejected", "stale-target"])
async def test_revision_post_stops_before_system_or_provider_resolution_on_preflight_failure(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    system_id = uuid4()
    subject = _subject(
        allowed_actions=frozenset({Action.CHANGE_EDIT}),
        allowed_system_ids=frozenset({system_id}),
    )
    service = SimpleNamespace(
        get_change_request_for_revision=AsyncMock(
            side_effect=NotFoundError(f"revision preflight rejected: {failure}")
        ),
        revise_change_request=AsyncMock(),
    )
    item_builder = AsyncMock()
    session = AsyncMock(spec=AsyncSession)
    monkeypatch.setattr(governance_routes, "_service", lambda *_: service)
    monkeypatch.setattr(governance_routes, "_change_intake_items", item_builder)

    payload = ChangeRequestRevisionCreate(
        title="Corrected request",
        system_id=system_id,
        request_reason="Correct the requested table.",
        targets=[{"kind": "MANUAL", "table_name": "new_table"}],
    )
    with pytest.raises(NotFoundError, match=failure):
        await revise_change_request_intake(
            change_request_id=uuid4(),
            payload=payload,
            request=cast(Any, object()),
            context=_context(subject),
            session=cast(AsyncSession, session),
            if_match='"3"',
            idempotency_key="revision-preflight-idempotency",
        )

    session.scalars.assert_not_awaited()
    item_builder.assert_not_awaited()
    service.revise_change_request.assert_not_awaited()


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
