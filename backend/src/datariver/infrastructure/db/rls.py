from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ANONYMOUS_SUBJECT_ID = UUID(int=0)


async def set_security_context(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    subject_id: UUID | None,
) -> None:
    """Set transaction-local attributes consumed by PostgreSQL RLS policies."""
    await session.execute(
        text(
            "SELECT "
            "set_config('app.workspace_id', :workspace_id, true), "
            "set_config('app.subject_id', :subject_id, true)"
        ),
        {
            "workspace_id": str(workspace_id),
            "subject_id": str(subject_id or ANONYMOUS_SUBJECT_ID),
        },
    )
