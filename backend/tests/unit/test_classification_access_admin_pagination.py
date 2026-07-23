from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ClauseElement

from datariver.domain.authz import Classification
from datariver.domain.classification_access import (
    ChatMode,
    ClassificationAccessPolicy,
    ClassificationAccessRule,
    RestrictedSearchGrant,
    RestrictedSearchScope,
    SearchMode,
)
from datariver.domain.common import ValidationError
from datariver.infrastructure.db.classification_access import (
    SqlClassificationPolicyRepository,
    SqlRestrictedSearchGrantRepository,
    _grant_model,
    _policy_model,
)
from datariver.infrastructure.db.models.classification_access import (
    ClassificationAccessPolicyRuleModel,
)

NOW = datetime(2035, 1, 1, 12, tzinfo=UTC)


class _Rows:
    def __init__(self, values: tuple[Any, ...]) -> None:
        self._values = values

    def all(self) -> tuple[Any, ...]:
        return self._values


class _Session:
    def __init__(
        self,
        *,
        scalar_rows: tuple[Any, ...] = (),
        execute_rows: tuple[Any, ...] = (),
    ) -> None:
        self.scalar_rows = scalar_rows
        self.execute_rows = execute_rows
        self.scalars_statements: list[object] = []
        self.execute_statements: list[object] = []

    async def scalars(self, statement: object) -> _Rows:
        self.scalars_statements.append(statement)
        return _Rows(self.scalar_rows)

    async def execute(self, statement: object) -> _Rows:
        self.execute_statements.append(statement)
        return _Rows(self.execute_rows)


def _rules() -> tuple[ClassificationAccessRule, ...]:
    return (
        ClassificationAccessRule(
            Classification.PUBLIC,
            SearchMode.ABAC,
            ChatMode.INTERNAL_APPROVED_ONLY,
            uuid4(),
        ),
        ClassificationAccessRule(
            Classification.INTERNAL,
            SearchMode.ABAC,
            ChatMode.INTERNAL_APPROVED_ONLY,
            uuid4(),
        ),
        ClassificationAccessRule(
            Classification.CONFIDENTIAL,
            SearchMode.DENY,
            ChatMode.INTERNAL_APPROVED_ONLY,
            uuid4(),
        ),
        ClassificationAccessRule(
            Classification.RESTRICTED,
            SearchMode.EXPLICIT_GRANT_ONLY,
            ChatMode.DENY,
            None,
        ),
    )


def _policy(*, workspace_id: UUID, policy_number: int) -> ClassificationAccessPolicy:
    return ClassificationAccessPolicy.propose(
        workspace_id=workspace_id,
        policy_number=policy_number,
        required_jurisdiction="JURISDICTION-A",
        restricted_search_grant_maximum_days=30,
        rules=_rules(),
        requester_id=uuid4(),
        reason="Governed classification policy",
        policy_decision_id=uuid4(),
    )


def _policy_rows(
    policy: ClassificationAccessPolicy,
) -> tuple[tuple[object, ClassificationAccessPolicyRuleModel], ...]:
    model = _policy_model(policy)
    return tuple(
        (
            model,
            ClassificationAccessPolicyRuleModel(
                id=uuid4(),
                workspace_id=policy.workspace_id,
                policy_id=policy.policy_id,
                policy_hash=policy.payload_hash,
                classification=int(rule.classification),
                search_mode=rule.search_mode.value,
                chat_mode=rule.chat_mode.value,
                provider_profile_version_id=rule.provider_profile_version_id,
            ),
        )
        for rule in policy.rules
    )


def _grant(*, workspace_id: UUID, created_at: datetime) -> RestrictedSearchGrant:
    grant = RestrictedSearchGrant.propose(
        workspace_id=workspace_id,
        classification_policy_id=uuid4(),
        classification_policy_hash="a" * 64,
        subject_id=uuid4(),
        scope=RestrictedSearchScope.RESOURCE,
        scope_id=uuid4(),
        purpose="Investigate one governed incident",
        valid_from=NOW,
        expires_at=NOW + timedelta(days=1),
        requester_id=uuid4(),
        reason="Time-bounded access",
        policy_decision_id=uuid4(),
        now=NOW,
        maximum_lifetime=timedelta(days=30),
    )
    model = _grant_model(grant)
    model.created_at = created_at
    return grant


@pytest.mark.asyncio
async def test_policy_history_uses_limit_plus_one_and_filter_bound_cursor() -> None:
    workspace_id = uuid4()
    first = _policy(workspace_id=workspace_id, policy_number=2)
    second = _policy(workspace_id=workspace_id, policy_number=1)
    session = _Session(
        scalar_rows=(first.policy_id, second.policy_id),
        execute_rows=_policy_rows(first),
    )
    repository = SqlClassificationPolicyRepository(cast(AsyncSession, session))

    page = await repository.list(
        workspace_id=workspace_id,
        state=None,
        limit=1,
        cursor=None,
    )

    assert len(page.items) == 1
    assert page.items[0].policy_id == first.policy_id
    assert page.items[0].payload_hash == first.payload_hash
    assert page.next_cursor is not None
    statement = cast(ClauseElement, session.scalars_statements[0])
    assert statement.compile().params["param_1"] == 2

    next_session = _Session()
    next_repository = SqlClassificationPolicyRepository(cast(AsyncSession, next_session))
    empty = await next_repository.list(
        workspace_id=workspace_id,
        state=None,
        limit=1,
        cursor=page.next_cursor,
    )
    assert empty.items == ()
    assert "policy_number <" in str(
        cast(ClauseElement, next_session.scalars_statements[0]).compile()
    )
    with pytest.raises(ValidationError, match="stale"):
        await next_repository.list(
            workspace_id=workspace_id,
            state="ACTIVE",
            limit=1,
            cursor=page.next_cursor,
        )


@pytest.mark.asyncio
async def test_grant_history_uses_created_at_and_id_cursor_bound_to_subject_filter() -> None:
    workspace_id = uuid4()
    first = _grant(workspace_id=workspace_id, created_at=NOW)
    second = _grant(workspace_id=workspace_id, created_at=NOW)
    first_model = _grant_model(first)
    first_model.created_at = NOW
    second_model = _grant_model(second)
    second_model.created_at = NOW
    session = _Session(scalar_rows=(first_model, second_model))
    repository = SqlRestrictedSearchGrantRepository(cast(AsyncSession, session))

    page = await repository.list(
        workspace_id=workspace_id,
        subject_id=None,
        state=None,
        limit=1,
        cursor=None,
    )

    assert len(page.items) == 1
    assert page.items[0].grant_id == first.grant_id
    assert page.next_cursor is not None
    statement = cast(ClauseElement, session.scalars_statements[0])
    assert statement.compile().params["param_1"] == 2

    next_session = _Session()
    next_repository = SqlRestrictedSearchGrantRepository(cast(AsyncSession, next_session))
    empty = await next_repository.list(
        workspace_id=workspace_id,
        subject_id=None,
        state=None,
        limit=1,
        cursor=page.next_cursor,
    )
    assert empty.items == ()
    sql = str(cast(ClauseElement, next_session.scalars_statements[0]).compile())
    assert "created_at <" in sql and "id >" in sql
    with pytest.raises(ValidationError, match="stale"):
        await next_repository.list(
            workspace_id=workspace_id,
            subject_id=uuid4(),
            state=None,
            limit=1,
            cursor=page.next_cursor,
        )


@pytest.mark.asyncio
async def test_classification_history_rejects_pages_larger_than_one_hundred() -> None:
    workspace_id = uuid4()
    session = _Session()
    with pytest.raises(ValidationError, match="limit"):
        await SqlClassificationPolicyRepository(cast(AsyncSession, session)).list(
            workspace_id=workspace_id,
            state=None,
            limit=101,
            cursor=None,
        )
    with pytest.raises(ValidationError, match="limit"):
        await SqlRestrictedSearchGrantRepository(cast(AsyncSession, session)).list(
            workspace_id=workspace_id,
            subject_id=None,
            state=None,
            limit=101,
            cursor=None,
        )
