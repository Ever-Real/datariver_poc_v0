from __future__ import annotations

import hashlib
from typing import Annotated, Literal
from uuid import UUID

import orjson
from fastapi import APIRouter, Header, Query, Request, Response, status
from fastapi.responses import JSONResponse

from datariver.application.catalog_export_csv import CSV_SAFETY_VERSION
from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.dto import CatalogExportRequest
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.catalog import CatalogService
from datariver.application.services.catalog_export import CatalogExportService
from datariver.application.services.catalog_sync import CatalogSyncService
from datariver.domain.authz import BuiltinPolicyEngine
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.catalog import SqlCatalogIndexReader, SqlCatalogProjectionWriter
from datariver.infrastructure.db.catalog_export import SqlCatalogExportStore
from datariver.infrastructure.db.classification_access import (
    SqlClassificationAccessSnapshotReader,
)
from datariver.interfaces.http.dependencies import ContextDep, SessionDep, get_container
from datariver.interfaces.http.presenters import catalog_detail, catalog_summary
from datariver.interfaces.http.schemas import (
    CatalogAssetResponse,
    CatalogDiscoveryPolicyMeta,
    CatalogExportCapabilityResponse,
    CatalogExportCreateRequest,
    CatalogExportCreateResponse,
    CatalogExportDownloadResponse,
    CatalogExportStatusResponse,
    CatalogFacetBucketResponse,
    CatalogFacetsResponse,
    CatalogLineageEdgeResponse,
    CatalogLineageResponse,
    CatalogPolicyMeta,
    CatalogSearchResponse,
    CatalogSuggestionResponse,
    CatalogSuggestionsResponse,
    CatalogSyncRequest,
    CatalogSyncResponse,
    CatalogTreeNodeResponse,
    CatalogTreeResponse,
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


def _export_service(request: Request, session: SessionDep) -> CatalogExportService:
    container = get_container(request)
    index = SqlCatalogIndexReader(session)
    return CatalogExportService(
        store=SqlCatalogExportStore(session),
        watermark=index,
        classification_access=ClassificationAccessResolver(
            SqlClassificationAccessSnapshotReader(session)
        ),
        authorization=AuthorizationService(
            decision_writer=SqlDecisionWriter(container.database.session_factory)
        ),
        object_store=container.object_store,
        minimum_query_length=container.settings.catalog_search_minimum_query_length,
        policy_version=BuiltinPolicyEngine.policy_version,
        csv_safety_version=CSV_SAFETY_VERSION,
        access_ttl_seconds=container.settings.catalog_export_access_ttl_seconds,
        download_ttl_seconds=container.settings.catalog_export_download_ttl_seconds,
        worker_enabled=container.settings.catalog_export_worker_enabled,
    )


def _export_filters(payload: CatalogExportCreateRequest) -> dict[str, str]:
    return {
        key: value
        for key, value in {
            "asset_type": payload.asset_type,
            "platform": payload.platform,
            "classification": payload.classification,
            "lifecycle": payload.lifecycle,
        }.items()
        if value is not None
    }


def _export_not_found(request: Request, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "type": "urn:datariver:problem:not_found",
            "title": "Not found",
            "status": 404,
            "detail": "The catalog export does not exist.",
            "instance": str(request.url.path),
            "code": "not_found",
            "request_id": request_id,
        },
    )


@router.get("/export-capability", response_model=CatalogExportCapabilityResponse)
async def catalog_export_capability(
    request: Request,
    context: ContextDep,
    session: SessionDep,
) -> CatalogExportCapabilityResponse:
    enabled = await _export_service(request, session).capability(
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return CatalogExportCapabilityResponse(enabled=enabled)


@router.post(
    "/exports",
    response_model=CatalogExportCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_catalog_export(
    payload: CatalogExportCreateRequest,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> CatalogExportCreateResponse:
    record = await _export_service(request, session).create(
        subject=context.subject,
        request=CatalogExportRequest(
            query=payload.q,
            filters=_export_filters(payload),
            sort=payload.sort,
            format=payload.format,
        ),
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
    )
    return CatalogExportCreateResponse(
        export_id=record.export_id,
        job_id=record.job_id,
        state=record.job_state,
    )


@router.get(
    "/exports/{export_id}",
    response_model=CatalogExportStatusResponse,
)
async def get_catalog_export(
    export_id: UUID,
    request: Request,
    context: ContextDep,
    session: SessionDep,
) -> CatalogExportStatusResponse | JSONResponse:
    record = await _export_service(request, session).get(
        subject=context.subject,
        export_id=export_id,
        environment=context.environment,
        request_id=context.request_id,
    )
    if record is None:
        return _export_not_found(request, context.request_id)
    return CatalogExportStatusResponse(
        export_id=record.export_id,
        job_id=record.job_id,
        state=record.job_state,
        last_error_code=record.last_error_code,
        row_count=record.row_count,
        size_bytes=record.size_bytes,
        content_sha256=record.content_sha256,
        display_name=record.display_name,
        created_at=record.created_at,
        completed_at=record.completed_at,
        access_until=record.access_until,
    )


@router.post(
    "/exports/{export_id}/download",
    response_model=CatalogExportDownloadResponse,
)
async def download_catalog_export(
    export_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> CatalogExportDownloadResponse | JSONResponse:
    download = await _export_service(request, session).download(
        subject=context.subject,
        export_id=export_id,
        environment=context.environment,
        request_id=context.request_id,
    )
    if download is None:
        return _export_not_found(request, context.request_id)
    response.headers["Cache-Control"] = "no-store"
    return CatalogExportDownloadResponse(
        url=download.url,
        expires_seconds=download.expires_seconds,
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


@router.get("/tree/nodes", response_model=CatalogTreeResponse)
async def catalog_tree_nodes(
    request: Request,
    context: ContextDep,
    session: SessionDep,
    q: Annotated[str, Query(max_length=500)] = "",
    parent_kind: Annotated[Literal["ROOT", "PLATFORM", "DATABASE", "SCHEMA"], Query()] = "ROOT",
    platform: Annotated[str | None, Query(max_length=100)] = None,
    database_name: Annotated[str | None, Query(alias="database", max_length=255)] = None,
    schema_name: Annotated[str | None, Query(alias="schema", max_length=255)] = None,
    cursor: Annotated[str | None, Query(max_length=2000)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> CatalogTreeResponse:
    page = await _service(request, session).tree_nodes(
        subject=context.subject,
        query=q,
        parent_kind=parent_kind,
        platform=platform,
        database_name=database_name,
        schema_name=schema_name,
        cursor=cursor,
        limit=limit,
        environment=context.environment,
        request_id=context.request_id,
    )
    return CatalogTreeResponse(
        items=[
            CatalogTreeNodeResponse(
                id=item.node_id,
                kind=item.kind,
                label=item.label,
                asset_count=item.asset_count,
                has_children=item.has_children,
                platform=item.platform,
                database_name=item.database_name,
                schema_name=item.schema_name,
                asset=catalog_summary(item.asset) if item.asset is not None else None,
            )
            for item in page.items
        ],
        page=PageMeta(next_cursor=page.next_cursor, limit=limit),
        meta=CatalogDiscoveryPolicyMeta(
            observed_at=page.observed_at,
            projection_version=page.projection_version,
            policy_version=page.policy_version,
            classification_policy_version=page.classification_policy_version,
            authorization_generation=page.authorization_generation,
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


@router.get("/assets/{asset_id}/lineage", response_model=CatalogLineageResponse)
async def get_asset_lineage(
    asset_id: UUID,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    direction: Annotated[Literal["UPSTREAM", "DOWNSTREAM", "BOTH"], Query()] = "BOTH",
    depth: Annotated[int, Query(ge=1, le=3)] = 2,
) -> CatalogLineageResponse | JSONResponse:
    lineage = await _service(request, session).lineage(
        subject=context.subject,
        asset_id=asset_id,
        direction=direction,
        depth=depth,
        environment=context.environment,
        request_id=context.request_id,
    )
    if lineage is None:
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
    return CatalogLineageResponse(
        center_asset_id=lineage.center_asset_id,
        nodes=[catalog_summary(item) for item in lineage.nodes],
        edges=[
            CatalogLineageEdgeResponse(
                source_asset_id=item.source_asset_id,
                target_asset_id=item.target_asset_id,
            )
            for item in lineage.edges
        ],
        direction=lineage.direction,
        depth=lineage.depth,
        truncated=lineage.truncated,
        meta=CatalogPolicyMeta(
            observed_at=lineage.observed_at,
            projection_version=lineage.projection_version,
            policy_version=lineage.policy_version,
            classification_policy_version=lineage.classification_policy_version,
            authorization_generation=lineage.authorization_generation,
        ),
    )
