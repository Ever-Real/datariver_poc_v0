from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.infrastructure.db.authz import SqlSubjectReader


@pytest.mark.asyncio
async def test_default_workspace_lookup_uses_only_the_bounded_database_function() -> None:
    workspace_id = UUID("00000000-0000-4000-8000-000000000100")
    result = Mock()
    result.scalar_one_or_none.return_value = workspace_id
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = result

    value = await SqlSubjectReader(session).get_default_workspace_id(
        issuer="https://idp.example.test/realms/datariver",
        external_subject="subject-one",
    )

    assert value == workspace_id
    statement, parameters = session.execute.await_args.args
    assert "iam.resolve_default_workspace" in str(statement)
    assert parameters == {
        "issuer": "https://idp.example.test/realms/datariver",
        "external_subject": "subject-one",
    }


@pytest.mark.asyncio
async def test_default_workspace_lookup_does_not_substitute_a_workspace() -> None:
    result = Mock()
    result.scalar_one_or_none.return_value = None
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = result

    value = await SqlSubjectReader(session).get_default_workspace_id(
        issuer="https://idp.example.test/realms/datariver",
        external_subject="unknown-subject",
    )

    assert value is None
