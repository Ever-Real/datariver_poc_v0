from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import Action, Classification, ResourceAttributes
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.models.governance import ChangeRequestModel
from datariver.infrastructure.db.models.integration import (
    JobModel,
    ObjectManifestModel,
    OutboxEventModel,
)
from datariver.interfaces.http.dependencies import ContextDep, SessionDep, get_container
from datariver.interfaces.http.schemas import OperationsSummaryResponse

router = APIRouter(prefix="/operations", tags=["operations"])


async def _authorize_operations(request: Request, context: ContextDep) -> None:
    container = get_container(request)
    await AuthorizationService(
        decision_writer=SqlDecisionWriter(container.database.session_factory)
    ).authorize(
        subject=context.subject,
        resource=ResourceAttributes(
            resource_id=context.workspace_id,
            workspace_id=context.workspace_id,
            resource_type="operations",
            owner_department_id=None,
            system_id=None,
            domain_id=None,
            classification=Classification.INTERNAL,
            lifecycle="ACTIVE",
        ),
        action=Action.OPERATIONS_READ,
        environment=context.environment,
        request_id=context.request_id,
    )


async def _state_counts(
    session: AsyncSession,
    state: InstrumentedAttribute[str],
    workspace: InstrumentedAttribute[UUID],
    workspace_id: UUID,
) -> dict[str, int]:
    rows = (
        await session.execute(
            select(state, func.count()).where(workspace == workspace_id).group_by(state)
        )
    ).all()
    return {str(name): int(count) for name, count in rows}


@router.get("/summary", response_model=OperationsSummaryResponse)
async def summary(
    request: Request,
    context: ContextDep,
    session: SessionDep,
) -> OperationsSummaryResponse:
    await _authorize_operations(request, context)
    observed_at = datetime.now(UTC)
    outbox_count, oldest = (
        await session.execute(
            select(func.count(), func.min(OutboxEventModel.created_at)).where(
                OutboxEventModel.workspace_id == context.workspace_id,
                OutboxEventModel.published_at.is_(None),
                OutboxEventModel.dead_lettered_at.is_(None),
            )
        )
    ).one()
    dead_letter_count = await session.scalar(
        select(func.count()).where(
            OutboxEventModel.workspace_id == context.workspace_id,
            OutboxEventModel.dead_lettered_at.is_not(None),
        )
    )
    return OperationsSummaryResponse(
        observed_at=observed_at,
        jobs_by_state=await _state_counts(
            session, JobModel.state, JobModel.workspace_id, context.workspace_id
        ),
        uploads_by_state=await _state_counts(
            session,
            ObjectManifestModel.state,
            ObjectManifestModel.workspace_id,
            context.workspace_id,
        ),
        changes_by_state=await _state_counts(
            session,
            ChangeRequestModel.state,
            ChangeRequestModel.workspace_id,
            context.workspace_id,
        ),
        unpublished_outbox_events=int(outbox_count),
        dead_lettered_outbox_events=int(dead_letter_count or 0),
        oldest_unpublished_age_seconds=(
            max(0, int((observed_at - oldest).total_seconds())) if oldest is not None else None
        ),
        retention_automation_state="DISABLED_NOT_READY",
    )


@router.get("/metrics", response_class=Response)
async def metrics(request: Request, context: ContextDep) -> Response:
    await _authorize_operations(request, context)
    telemetry = get_container(request).metrics
    return Response(content=telemetry.render(), headers={"Content-Type": telemetry.content_type})
