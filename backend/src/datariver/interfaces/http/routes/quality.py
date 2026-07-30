from __future__ import annotations

from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.quality_read import QualityReadService
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.classification_access import (
    SqlClassificationAccessSnapshotReader,
)
from datariver.infrastructure.db.quality_read import SqlQualityReadRepository
from datariver.interfaces.http.dependencies import ContextDep, SessionDep, get_container
from datariver.interfaces.http.quality_presenters import (
    quality_asset_response,
    quality_issue_response,
    quality_overview_response,
    quality_result_response,
    quality_rule_set_detail_response,
    quality_rule_set_response,
    quality_run_response,
)
from datariver.interfaces.http.quality_schemas import (
    QualityAssetDetailResponse,
    QualityAssetListResponse,
    QualityCapabilityAxisResponse,
    QualityCapabilityResponse,
    QualityIssueListResponse,
    QualityOverviewResponse,
    QualityResultListResponse,
    QualityRuleDefinitionContractResponse,
    QualityRuleDefinitionContractsResponse,
    QualityRuleSetDetailResponse,
    QualityRuleSetListResponse,
    QualityRunDetailResponse,
    QualityRunListResponse,
)
from datariver.interfaces.http.schemas import PageMeta

router = APIRouter(prefix="/quality", tags=["quality"])


def _service(request: Request, session: SessionDep) -> QualityReadService:
    container = get_container(request)
    return QualityReadService(
        repository=SqlQualityReadRepository(session),
        authorization=AuthorizationService(
            decision_writer=SqlDecisionWriter(container.database.session_factory)
        ),
        classification_access=ClassificationAccessResolver(
            SqlClassificationAccessSnapshotReader(session)
        ),
    )


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization, X-Workspace-Id"


@router.get("/capability", response_model=QualityCapabilityResponse)
async def get_quality_capability(
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> QualityCapabilityResponse:
    _private(response)
    value = await _service(request, session).capability(
        subject=context.subject,
        environment=context.environment,
    )
    return QualityCapabilityResponse(
        observed_at=value.observed_at,
        valid_until=value.valid_until,
        cache_scope=value.cache_scope,
        axes=[QualityCapabilityAxisResponse.model_validate(asdict(axis)) for axis in value.axes],
    )


@router.get(
    "/rule-definitions",
    response_model=QualityRuleDefinitionContractsResponse,
)
async def get_quality_rule_definitions(
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> QualityRuleDefinitionContractsResponse:
    _private(response)
    values = await _service(request, session).rule_definitions(
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return QualityRuleDefinitionContractsResponse(
        items=[QualityRuleDefinitionContractResponse.model_validate(value) for value in values]
    )


@router.get("/overview", response_model=QualityOverviewResponse)
async def get_quality_overview(
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> QualityOverviewResponse:
    _private(response)
    value, _ = await _service(request, session).overview(
        days=days,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return quality_overview_response(value)


@router.get("/assets", response_model=QualityAssetListResponse)
async def list_quality_assets(
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=2_000)] = None,
) -> QualityAssetListResponse:
    _private(response)
    page, read_context = await _service(request, session).list_assets(
        limit=limit,
        cursor=cursor,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return QualityAssetListResponse(
        items=[quality_asset_response(value) for value in page.items],
        page=PageMeta(next_cursor=page.next_cursor, limit=limit),
        cache_scope=read_context.cache_scope,
        observed_at=read_context.observed_at,
        authorization_valid_until=read_context.authorization_valid_until,
    )


@router.get("/assets/{asset_id}", response_model=QualityAssetDetailResponse)
async def get_quality_asset(
    asset_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> QualityAssetDetailResponse:
    _private(response)
    value, read_context = await _service(request, session).get_asset(
        asset_id=asset_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return QualityAssetDetailResponse(
        item=quality_asset_response(value),
        cache_scope=read_context.cache_scope,
        observed_at=read_context.observed_at,
        authorization_valid_until=read_context.authorization_valid_until,
    )


@router.get("/rule-sets", response_model=QualityRuleSetListResponse)
async def list_quality_rule_sets(
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=2_000)] = None,
) -> QualityRuleSetListResponse:
    _private(response)
    page, read_context = await _service(request, session).list_rule_sets(
        limit=limit,
        cursor=cursor,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return QualityRuleSetListResponse(
        items=[quality_rule_set_response(value) for value in page.items],
        page=PageMeta(next_cursor=page.next_cursor, limit=limit),
        cache_scope=read_context.cache_scope,
        observed_at=read_context.observed_at,
        authorization_valid_until=read_context.authorization_valid_until,
    )


@router.get(
    "/rule-sets/{rule_set_id}",
    response_model=QualityRuleSetDetailResponse,
)
async def get_quality_rule_set(
    rule_set_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> QualityRuleSetDetailResponse:
    _private(response)
    value, read_context = await _service(request, session).get_rule_set(
        rule_set_id=rule_set_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["ETag"] = f'"{value.rule_set.version}"'
    return QualityRuleSetDetailResponse(
        item=quality_rule_set_detail_response(value),
        cache_scope=read_context.cache_scope,
        observed_at=read_context.observed_at,
        authorization_valid_until=read_context.authorization_valid_until,
    )


@router.get("/runs", response_model=QualityRunListResponse)
async def list_quality_runs(
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=2_000)] = None,
) -> QualityRunListResponse:
    _private(response)
    page, read_context = await _service(request, session).list_runs(
        limit=limit,
        cursor=cursor,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return QualityRunListResponse(
        items=[quality_run_response(value) for value in page.items],
        page=PageMeta(next_cursor=page.next_cursor, limit=limit),
        cache_scope=read_context.cache_scope,
        observed_at=read_context.observed_at,
        authorization_valid_until=read_context.authorization_valid_until,
    )


@router.get("/runs/{run_id}", response_model=QualityRunDetailResponse)
async def get_quality_run(
    run_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> QualityRunDetailResponse:
    _private(response)
    value, read_context = await _service(request, session).get_run(
        run_id=run_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["ETag"] = f'"{value.version}"'
    return QualityRunDetailResponse(
        item=quality_run_response(value),
        cache_scope=read_context.cache_scope,
        observed_at=read_context.observed_at,
        authorization_valid_until=read_context.authorization_valid_until,
    )


@router.get(
    "/runs/{run_id}/results",
    response_model=QualityResultListResponse,
)
async def list_quality_results(
    run_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=2_000)] = None,
) -> QualityResultListResponse:
    _private(response)
    page, read_context = await _service(request, session).list_results(
        run_id=run_id,
        limit=limit,
        cursor=cursor,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return QualityResultListResponse(
        items=[quality_result_response(value) for value in page.items],
        page=PageMeta(next_cursor=page.next_cursor, limit=limit),
        cache_scope=read_context.cache_scope,
        observed_at=read_context.observed_at,
        authorization_valid_until=read_context.authorization_valid_until,
    )


@router.get("/issues", response_model=QualityIssueListResponse)
async def list_quality_issues(
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=2_000)] = None,
) -> QualityIssueListResponse:
    _private(response)
    page, read_context = await _service(request, session).list_issues(
        limit=limit,
        cursor=cursor,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return QualityIssueListResponse(
        items=[quality_issue_response(value) for value in page.items],
        page=PageMeta(next_cursor=page.next_cursor, limit=limit),
        cache_scope=read_context.cache_scope,
        observed_at=read_context.observed_at,
        authorization_valid_until=read_context.authorization_valid_until,
    )
