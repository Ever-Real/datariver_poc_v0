from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.quality_dispatch import QualityDispatchService
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.quality_execution import SqlQualityDispatchStore
from datariver.interfaces.http.dependencies import ContextDep, get_container

router = APIRouter(prefix="/quality/internal", tags=["quality-internal"])


class QualityDispatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: Annotated[str, Field(min_length=1, max_length=200)]


class QualityDispatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_run_ids: list[str]
    created_run_count: int
    skipped_window_count: int
    replayed: bool


@router.post("/dispatch", response_model=QualityDispatchResponse)
async def dispatch_due_quality_runs(
    payload: QualityDispatchRequest,
    request: Request,
    context: ContextDep,
) -> QualityDispatchResponse:
    container = get_container(request)
    max_due_schedules = container.settings.quality_dispatch_max_due_schedules
    max_created_runs = container.settings.quality_dispatch_max_created_runs
    if max_due_schedules is None or max_created_runs is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Quality dispatch capacity is not approved for this deployment.",
        )
    service = QualityDispatchService(
        store=SqlQualityDispatchStore(container.database.session_factory),
        authorization=AuthorizationService(
            decision_writer=SqlDecisionWriter(container.database.session_factory)
        ),
        max_due_schedules=max_due_schedules,
        max_created_runs=max_created_runs,
    )
    result = await service.dispatch(
        workspace_id=context.workspace_id,
        call_id=payload.call_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return QualityDispatchResponse.model_validate(result.document())
