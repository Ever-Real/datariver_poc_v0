from __future__ import annotations

import re
from dataclasses import asdict
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response

from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.quality_commands import QualityCommandService
from datariver.application.services.quality_read import QualityReadService
from datariver.domain.common import PreconditionRequiredError, ValidationError
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.classification_access import (
    SqlClassificationAccessSnapshotReader,
)
from datariver.infrastructure.db.quality_commands import SqlQualityCommandRepository
from datariver.infrastructure.db.quality_read import SqlQualityReadRepository
from datariver.infrastructure.quality.authoring_directory import (
    ManifestQualityDeploymentDirectory,
)
from datariver.infrastructure.quality.source_manifest import (
    QualitySourceManifest,
    QualitySourceManifestError,
    load_quality_source_manifest,
)
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
    QualityAssetAuthoringResponse,
    QualityAssetDetailResponse,
    QualityAssetListResponse,
    QualityAuthoringFieldResponse,
    QualityCapabilityAxisResponse,
    QualityCapabilityResponse,
    QualityIssueListResponse,
    QualityManualRunRequest,
    QualityManualRunResponse,
    QualityOverviewResponse,
    QualityResultListResponse,
    QualityRuleBatchProposalRequest,
    QualityRuleBatchProposalResponse,
    QualityRuleDefinitionContractResponse,
    QualityRuleDefinitionContractsResponse,
    QualityRuleProposalItemResponse,
    QualityRuleReviewRequest,
    QualityRuleSetDetailResponse,
    QualityRuleSetListResponse,
    QualityRuleVersionCommandResponse,
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


@lru_cache(maxsize=16)
def _load_manifest(path: str | None) -> QualitySourceManifest | None:
    if path is None:
        return None
    try:
        return load_quality_source_manifest(path)
    except QualitySourceManifestError:
        return None


def _command_service(request: Request, session: SessionDep) -> QualityCommandService:
    container = get_container(request)
    return QualityCommandService(
        repository=SqlQualityCommandRepository(session),
        directory=ManifestQualityDeploymentDirectory(
            _load_manifest(container.settings.quality_source_manifest_file)
        ),
        authorization=AuthorizationService(
            decision_writer=SqlDecisionWriter(container.database.session_factory)
        ),
        worker_enabled=container.settings.quality_worker_enabled,
    )


def _expected_version(if_match: str | None) -> int:
    if if_match is None:
        raise PreconditionRequiredError("If-Match is required for this Quality command.")
    match = re.fullmatch(r'"([1-9][0-9]*)"', if_match.strip())
    if match is None:
        raise ValidationError("If-Match must contain a quoted positive version.")
    return int(match.group(1))


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
    command_service = _command_service(request, session)
    authoring_ready = await command_service.authoring_ready(workspace_id=context.workspace_id)
    value = await _service(request, session).capability(
        subject=context.subject,
        environment=context.environment,
        authoring_ready=authoring_ready,
        manual_execution_ready=(
            get_container(request).settings.quality_worker_enabled and authoring_ready
        ),
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
    authoring = await _command_service(request, session).asset_detail(
        workspace_id=context.workspace_id,
        asset_id=asset_id,
    )
    return QualityAssetDetailResponse(
        item=quality_asset_response(value),
        authoring=QualityAssetAuthoringResponse(
            state=authoring.state,
            reason_code=authoring.reason_code,
            source_version=authoring.source_version,
            schema_hash=authoring.schema_hash,
            fields=[
                QualityAuthoringFieldResponse(
                    field_identifier=field.field_identifier,
                    display_path=field.display_path,
                    logical_type=field.logical_type,
                    supported_rule_kinds=field.supported_rule_kinds,
                )
                for field in authoring.fields
            ],
        ),
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


@router.post(
    "/rule-sets",
    response_model=QualityRuleBatchProposalResponse,
    status_code=201,
)
async def propose_quality_rule_sets(
    payload: QualityRuleBatchProposalRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=16, max_length=200),
    ],
) -> QualityRuleBatchProposalResponse:
    _private(response)
    result = await _command_service(request, session).propose_rule_sets(
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        name_prefix=payload.name_prefix,
        asset_ids=payload.asset_ids,
        rules=[rule.model_dump() for rule in payload.rules],
    )
    response.headers["Location"] = "/api/v1/quality/rule-sets"
    return QualityRuleBatchProposalResponse(
        items=[
            QualityRuleProposalItemResponse(
                asset_id=item.asset_id,
                rule_set_id=item.rule_set_id,
                version_id=item.version_id,
                version=item.version,
            )
            for item in result.items
        ],
        replayed=result.replayed,
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


@router.post(
    "/rule-sets/{rule_set_id}/versions/{version_id}/reviews",
    response_model=QualityRuleVersionCommandResponse,
    status_code=201,
)
async def review_quality_rule_set_version(
    rule_set_id: UUID,
    version_id: UUID,
    payload: QualityRuleReviewRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=16, max_length=200),
    ],
    if_match: Annotated[str | None, Header(alias="If-Match", max_length=100)] = None,
) -> QualityRuleVersionCommandResponse:
    _private(response)
    value = await _command_service(request, session).review_rule_set_version(
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        rule_set_id=rule_set_id,
        version_id=version_id,
        decision=payload.decision,
        reason=payload.reason,
        expected_version=_expected_version(if_match),
    )
    response.headers["ETag"] = f'"{value.version}"'
    response.headers["Location"] = f"/api/v1/quality/rule-sets/{rule_set_id}"
    return QualityRuleVersionCommandResponse(
        rule_set_id=value.rule_set_id,
        version_id=value.version_id,
        state=value.state,
        version=value.version,
    )


@router.post(
    "/rule-sets/{rule_set_id}/versions/{version_id}/activations",
    response_model=QualityRuleVersionCommandResponse,
)
async def activate_quality_rule_set_version(
    rule_set_id: UUID,
    version_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=16, max_length=200),
    ],
    if_match: Annotated[str | None, Header(alias="If-Match", max_length=100)] = None,
) -> QualityRuleVersionCommandResponse:
    _private(response)
    value = await _command_service(request, session).activate_rule_set_version(
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        rule_set_id=rule_set_id,
        version_id=version_id,
        expected_version=_expected_version(if_match),
    )
    response.headers["ETag"] = f'"{value.version}"'
    return QualityRuleVersionCommandResponse(
        rule_set_id=value.rule_set_id,
        version_id=value.version_id,
        state=value.state,
        version=value.version,
    )


@router.post("/runs", response_model=QualityManualRunResponse, status_code=202)
async def request_quality_manual_run(
    payload: QualityManualRunRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=16, max_length=200),
    ],
) -> QualityManualRunResponse:
    _private(response)
    value = await _command_service(request, session).request_manual_run(
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        rule_set_id=payload.rule_set_id,
    )
    response.headers["Location"] = f"/api/v1/quality/runs/{value.run_id}"
    return QualityManualRunResponse(
        run_id=value.run_id,
        state=value.state,
        created_at=value.created_at,
        replayed=value.replayed,
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
