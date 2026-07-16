from __future__ import annotations

import hashlib
from typing import Annotated
from uuid import UUID

import orjson
from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse

from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.catalog import CatalogService
from datariver.application.services.catalog_sync import CatalogSyncService
from datariver.domain.authz import BuiltinPolicyEngine
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.catalog import SqlCatalogIndexReader, SqlCatalogProjectionWriter
from datariver.infrastructure.db.classification_access import (
    SqlClassificationAccessSnapshotReader,
)
from datariver.interfaces.http.dependencies import ContextDep, SessionDep, get_container
from datariver.interfaces.http.presenters import catalog_detail, catalog_summary
from datariver.interfaces.http.schemas import (
    CatalogAssetResponse,
    CatalogDiscoveryPolicyMeta,
    CatalogFacetBucketResponse,
    CatalogFacetsResponse,
    CatalogPolicyMeta,
    CatalogSearchResponse,
    CatalogSuggestionResponse,
    CatalogSuggestionsResponse,
    CatalogSyncRequest,
    CatalogSyncResponse,
    PageMeta,
)

router = APIRouter(prefix="/catalog", tags=["catalog"])


def _service(request: Request, session: SessionDep) -> CatalogService:
    container = get_container(request)
    index = SqlCatalogIndexReader(session)
    return CatalogService(
        index=index,
        discovery=index,
        watermark=index,
        datahub=container.datahub,
        cache=container.cache,
        authorization=AuthorizationService(
            decision_writer=SqlDecisionWriter(container.database.session_factory)
        ),
        detail_cache_ttl_seconds=container.settings.cache_default_ttl_seconds,
        stale_detail_ttl_seconds=container.settings.datahub_stale_ttl_seconds,
        search_cache_ttl_seconds=container.settings.catalog_search_cache_ttl_seconds,
        minimum_query_length=container.settings.catalog_search_minimum_query_length,
        policy_version=BuiltinPolicyEngine.policy_version,
        classification_access=ClassificationAccessResolver(
            SqlClassificationAccessSnapshotReader(session)
        ),
        telemetry=container.metrics,
    )


def _sync_service(request: Request, session: SessionDep) -> CatalogSyncService:
    container = get_container(request)
    return CatalogSyncService(
        datahub=container.datahub,
        writer=SqlCatalogProjectionWriter(session),
        authorization=AuthorizationService(
            decision_writer=SqlDecisionWriter(container.database.session_factory)
        ),
    )


@router.post("/sync/datahub", response_model=CatalogSyncResponse)
async def sync_datahub_catalog(
    payload: CatalogSyncRequest,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> CatalogSyncResponse:
    request_hash = hashlib.sha256(
        orjson.dumps(payload.model_dump(mode="json"), option=orjson.OPT_SORT_KEYS)
    ).hexdigest()
    result = await _sync_service(request, session).sync_page(
        workspace_id=context.workspace_id,
        sync_id=payload.sync_id,
        offset=payload.offset,
        limit=payload.limit,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    return CatalogSyncResponse(
        upserted=result.upserted,
        tombstoned=result.tombstoned,
        next_offset=result.next_offset,
        total=result.total,
        observed_at=result.observed_at,
    )


@router.get("/assets", response_model=CatalogSearchResponse)
async def search_assets(
    request: Request,
    context: ContextDep,
    session: SessionDep,
    q: Annotated[str, Query(max_length=500)] = "",
    asset_type: Annotated[str | None, Query(max_length=100)] = None,
    platform: Annotated[str | None, Query(max_length=100)] = None,
    lifecycle: Annotated[str | None, Query(max_length=50)] = None,
    classification: Annotated[
        str | None,
        Query(pattern="^(PUBLIC|INTERNAL|CONFIDENTIAL|RESTRICTED)$"),
    ] = None,
    cursor: Annotated[str | None, Query(max_length=2000)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> CatalogSearchResponse:
    filters = {
        name: value
        for name, value in {
            "asset_type": asset_type,
            "platform": platform,
            "lifecycle": lifecycle,
            "classification": classification,
        }.items()
        if value is not None
    }
    page = await _service(request, session).search(
        subject=context.subject,
        query=q,
        filters=filters,
        cursor=cursor,
        limit=limit,
        environment=context.environment,
        request_id=context.request_id,
    )
    return CatalogSearchResponse(
        items=[catalog_summary(item) for item in page.items],
        page=PageMeta(next_cursor=page.next_cursor, limit=limit),
        meta=CatalogPolicyMeta(
            observed_at=page.observed_at,
            stale_at=page.stale_at,
            projection_version=page.projection_version,
            policy_version=page.policy_version,
            classification_policy_version=page.classification_policy_version,
            authorization_generation=page.authorization_generation,
        ),
    )


@router.get("/facets", response_model=CatalogFacetsResponse)
async def catalog_facets(
    request: Request,
    context: ContextDep,
    session: SessionDep,
    q: Annotated[str, Query(max_length=500)] = "",
    asset_type: Annotated[str | None, Query(max_length=100)] = None,
    platform: Annotated[str | None, Query(max_length=100)] = None,
    lifecycle: Annotated[str | None, Query(max_length=50)] = None,
    classification: Annotated[
        str | None,
        Query(pattern="^(PUBLIC|INTERNAL|CONFIDENTIAL|RESTRICTED)$"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> CatalogFacetsResponse:
    filters = {
        name: value
        for name, value in {
            "asset_type": asset_type,
            "platform": platform,
            "lifecycle": lifecycle,
            "classification": classification,
        }.items()
        if value is not None
    }
    facets = await _service(request, session).facets(
        subject=context.subject,
        query=q,
        filters=filters,
        limit=limit,
        environment=context.environment,
        request_id=context.request_id,
    )
    return CatalogFacetsResponse(
        asset_types=[
            CatalogFacetBucketResponse(value=item.value, count=item.count)
            for item in facets.asset_types
        ],
        platforms=[
            CatalogFacetBucketResponse(value=item.value, count=item.count)
            for item in facets.platforms
        ],
        classifications=[
            CatalogFacetBucketResponse(value=item.value, count=item.count)
            for item in facets.classifications
        ],
        meta=CatalogDiscoveryPolicyMeta(
            observed_at=facets.observed_at,
            projection_version=facets.projection_version,
            policy_version=facets.policy_version,
            classification_policy_version=facets.classification_policy_version,
            authorization_generation=facets.authorization_generation,
        ),
    )


@router.get("/suggestions", response_model=CatalogSuggestionsResponse)
async def catalog_suggestions(
    request: Request,
    context: ContextDep,
    session: SessionDep,
    q: Annotated[str, Query(min_length=1, max_length=500)],
    limit: Annotated[int, Query(ge=1, le=20)] = 8,
) -> CatalogSuggestionsResponse:
    suggestions = await _service(request, session).suggestions(
        subject=context.subject,
        query=q,
        limit=limit,
        environment=context.environment,
        request_id=context.request_id,
    )
    return CatalogSuggestionsResponse(
        items=[
            CatalogSuggestionResponse(
                id=item.asset_id,
                name=item.name,
                asset_type=item.asset_type,
                platform=item.platform,
            )
            for item in suggestions.items
        ],
        meta=CatalogDiscoveryPolicyMeta(
            observed_at=suggestions.observed_at,
            projection_version=suggestions.projection_version,
            policy_version=suggestions.policy_version,
            classification_policy_version=suggestions.classification_policy_version,
            authorization_generation=suggestions.authorization_generation,
        ),
    )


@router.get("/assets/{asset_id}", response_model=CatalogAssetResponse)
async def get_asset(
    asset_id: UUID,
    request: Request,
    context: ContextDep,
    session: SessionDep,
) -> CatalogAssetResponse | JSONResponse:
    asset = await _service(request, session).get_asset(
        subject=context.subject,
        asset_id=asset_id,
        environment=context.environment,
        request_id=context.request_id,
    )
    if asset is None:
        return JSONResponse(
            status_code=404,
            content={
                "type": "urn:datariver:problem:not_found",
                "title": "Not found",
                "status": 404,
                "detail": "The catalog asset does not exist.",
                "instance": str(request.url.path),
                "code": "not_found",
                "request_id": context.request_id,
            },
        )
    return catalog_detail(asset)
