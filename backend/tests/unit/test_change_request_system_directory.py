from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.domain.authz import Action, Classification, SubjectAttributes
from datariver.interfaces.http.dependencies import RequestContext
from datariver.interfaces.http.routes.governance import (
    _change_request_system_scope,
    list_change_request_systems,
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

    assert _change_request_system_scope(
        _subject(allowed_system_ids=system_ids)
    ) == system_ids


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
