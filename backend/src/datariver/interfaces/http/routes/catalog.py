from __future__ import annotations

import hashlib
import re
from typing import Annotated, Literal, cast
from uuid import UUID

import orjson
from fastapi import APIRouter, Header, Query, Request, Response, status
from fastapi.responses import JSONResponse

from datariver.application.change_numbers import change_request_number
from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.dto import CatalogExportRequest
from datariver.application.ports import CatalogReaderMode
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.catalog import CatalogService
from datariver.application.services.catalog_description import CatalogDescriptionService
from datariver.application.services.catalog_export import CatalogExportService
from datariver.application.services.catalog_recommendations import (
    CatalogRecommendationApprovalTarget,
    CatalogRecommendationProvider,
    CatalogRecommendationService,
    UnavailableCatalogRecommendationProvider,
)
from datariver.application.services.catalog_sync import CatalogSyncService
from datariver.application.services.change_targets import CatalogChangeTargetAuthorizer
from datariver.application.services.governance import GovernanceService
from datariver.domain.authz import BuiltinPolicyEngine
from datariver.domain.catalog_recommendations import CatalogRecommendation
from datariver.domain.common import ConflictError, ValidationError
from datariver.domain.governance import ChangePriority, ChangeUrgency
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.catalog import SqlCatalogIndexReader, SqlCatalogProjectionWriter
from datariver.infrastructure.db.catalog_export import SqlCatalogExportStore
from datariver.infrastructure.db.catalog_metadata import SqlCatalogMetadataVocabularyResolver
from datariver.infrastructure.db.catalog_recommendations import SqlCatalogRecommendationStore
from datariver.infrastructure.db.classification_access import (
    SqlClassificationAccessSnapshotReader,
)
from datariver.infrastructure.db.governance import SqlGovernanceUnitOfWork
from datariver.interfaces.http.dependencies import ContextDep, SessionDep, get_container
from datariver.interfaces.http.presenters import (
    catalog_detail,
    catalog_summary,
    change_request_response,
)
from datariver.interfaces.http.schemas import (
    CatalogAssetResponse,
    CatalogColumnDescriptionChangeRequest,
    CatalogColumnDescriptionPreviewRequest,
    CatalogColumnDescriptionPreviewResponse,
    CatalogControlledMetadataChangeRequest,
    CatalogControlledMetadataPreviewRequest,
    CatalogControlledMetadataPreviewResponse,
    CatalogDataHubEmbedResponse,
    CatalogDescriptionChangeRequest,
    CatalogDescriptionPreviewRequest,
    CatalogDescriptionPreviewResponse,
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
    CatalogMatchFragmentResponse,
    CatalogPolicyMeta,
    CatalogRecommendationApprovalResponse,
    CatalogRecommendationApproveRequest,
    CatalogRecommendationPreviewRequest,
    CatalogRecommendationPreviewResponse,
    CatalogRecommendationRejectRequest,
    CatalogRecommendationResponse,
    CatalogSearchResponse,
    CatalogSuggestionResponse,
    CatalogSuggestionsResponse,
    CatalogSyncProgressResponse,
    CatalogSyncRequest,
    CatalogSyncResponse,
    CatalogTreeNodeResponse,
    CatalogTreeResponse,
    CatalogVocabularyResponse,
    ChangeRequestResponse,
    PageMeta,
)

router = APIRouter(prefix="/catalog", tags=["catalog"])


def _service(request: Request, session: SessionDep) -> CatalogService:
    container = get_container(request)
    index = SqlCatalogIndexReader(
        session,
        reader_mode=CatalogReaderMode.WORKSPACE_DISCOVERY,
    )
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
        reader_mode=CatalogReaderMode.WORKSPACE_DISCOVERY,
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


def _description_service(request: Request, session: SessionDep) -> CatalogDescriptionService:
    container = get_container(request)
    index = SqlCatalogIndexReader(session)
    classification_access = ClassificationAccessResolver(
        SqlClassificationAccessSnapshotReader(session)
    )
    authorization = AuthorizationService(
        decision_writer=SqlDecisionWriter(container.database.session_factory)
    )
    governance = GovernanceService(
        lambda: SqlGovernanceUnitOfWork(container.database.session_factory, session=session),
        authorization,
        target_authorizer=CatalogChangeTargetAuthorizer(
            index=index,
            classification_access=classification_access,
            authorization=authorization,
        ),
    )
    return CatalogDescriptionService(
        index=index,
        target_reader=index,
        classification_access=classification_access,
        authorization=authorization,
        datahub=container.datahub,
        governance=governance,
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
        access_ttl_seconds=container.settings.catalog_export_access_ttl_seconds,
        download_ttl_seconds=container.settings.catalog_export_download_ttl_seconds,
        worker_enabled=container.settings.catalog_export_worker_enabled,
    )


def _recommendation_service(
    request: Request,
    session: SessionDep,
) -> CatalogRecommendationService:
    container = get_container(request)
    # The Catalog-specific Governance extension and recommendation store intentionally receive
    # this exact request-scoped AsyncSession. Their row locks, CR/idempotency/outbox writes and
    # decision/event finalization therefore share one PostgreSQL transaction and rollback boundary.
    transaction_session = session
    index = SqlCatalogIndexReader(transaction_session)
    classification_access = ClassificationAccessResolver(
        SqlClassificationAccessSnapshotReader(session)
    )
    authorization = AuthorizationService(
        decision_writer=SqlDecisionWriter(container.database.session_factory)
    )
    governance = GovernanceService(
        lambda: SqlGovernanceUnitOfWork(
            container.database.session_factory,
            session=transaction_session,
        ),
        authorization,
        target_authorizer=CatalogChangeTargetAuthorizer(
            index=index,
            classification_access=classification_access,
            authorization=authorization,
        ),
    )
    provider = cast(
        CatalogRecommendationProvider,
        getattr(
            request.app.state,
            "catalog_recommendation_provider",
            UnavailableCatalogRecommendationProvider(),
        ),
    )
    return CatalogRecommendationService(
        index=index,
        classification_access=classification_access,
        authorization=authorization,
        datahub=container.datahub,
        vocabulary=SqlCatalogMetadataVocabularyResolver(transaction_session),
        provider=provider,
        store=SqlCatalogRecommendationStore(transaction_session),
        governance=governance,
    )


def _recommendation_response(
    recommendation: CatalogRecommendation,
) -> CatalogRecommendationResponse:
    return CatalogRecommendationResponse(
        recommendation_id=recommendation.recommendation_id,
        asset_id=recommendation.asset_id,
        field_path=recommendation.field_path,
        vocabulary_id=recommendation.vocabulary_id,
        kind=recommendation.kind.value,
        source_version=recommendation.source_version,
        confidence=recommendation.confidence,
        reason=recommendation.reason,
        evidence=list(recommendation.evidence),
        provider=recommendation.provider,
        model=recommendation.model,
        prompt_version=recommendation.prompt_version,
        rule_version=recommendation.rule_version,
        state=recommendation.state.value,
        version=recommendation.version,
        change_request_id=recommendation.change_request_id,
        created_at=recommendation.created_at,
        updated_at=recommendation.updated_at,
    )


def _export_filters(payload: CatalogExportCreateRequest) -> dict[str, str]:
    return {
        key: value
        for key, value in {
            "asset_type": payload.asset_type,
            "platform": payload.platform,
            "classification": payload.classification,
            "lifecycle": payload.lifecycle,
            "database_name": payload.database_name,
            "schema_name": payload.schema_name,
            "domain": payload.domain,
            "search_fields": payload.search_fields,
        }.items()
        if value is not None
    }


def _description_preview_etag(if_match: str) -> str:
    if re.fullmatch(r'"[0-9a-f]{64}"', if_match) is None:
        raise ValidationError("If-Match must contain the quoted preview_etag.")
    return if_match


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
    return CatalogExportCapabilityResponse(
        enabled=enabled,
        maximum_rows=get_container(request).settings.catalog_export_maximum_rows,
    )


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
        tombstone_status=result.tombstone_status,
    )


@router.get(
    "/sync/datahub/{sync_id}",
    response_model=CatalogSyncProgressResponse,
)
async def get_datahub_catalog_sync_progress(
    sync_id: UUID,
    request: Request,
    context: ContextDep,
    session: SessionDep,
) -> CatalogSyncProgressResponse:
    progress = await _sync_service(request, session).progress(
        workspace_id=context.workspace_id,
        sync_id=sync_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return CatalogSyncProgressResponse(
        state=progress.state,
        next_offset=progress.next_offset,
        seen_count=progress.seen_count,
        expected_total=progress.expected_total,
        snapshot_consistent=progress.snapshot_consistent,
    )


@router.get("/assets", response_model=CatalogSearchResponse)
async def search_assets(
    request: Request,
    context: ContextDep,
    session: SessionDep,
    q: Annotated[str, Query(max_length=500)] = "",
    asset_type: Annotated[str | None, Query(max_length=100)] = None,
    platform: Annotated[str | None, Query(max_length=100)] = None,
    database_name: Annotated[str | None, Query(alias="database", max_length=255)] = None,
    schema_name: Annotated[str | None, Query(alias="schema", max_length=255)] = None,
    domain: Annotated[str | None, Query(max_length=1000)] = None,
    search_fields: Annotated[str | None, Query(max_length=100)] = None,
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
            "database_name": database_name,
            "schema_name": schema_name,
            "domain": domain,
            "search_fields": search_fields,
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
        total=page.total,
        total_exact=page.total_exact,
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
    database_name: Annotated[str | None, Query(alias="database", max_length=255)] = None,
    schema_name: Annotated[str | None, Query(alias="schema", max_length=255)] = None,
    domain: Annotated[str | None, Query(max_length=1000)] = None,
    search_fields: Annotated[str | None, Query(max_length=100)] = None,
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
            "database_name": database_name,
            "schema_name": schema_name,
            "domain": domain,
            "search_fields": search_fields,
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
        databases=[
            CatalogFacetBucketResponse(value=item.value, count=item.count)
            for item in facets.databases
        ],
        schemas=[
            CatalogFacetBucketResponse(value=item.value, count=item.count)
            for item in facets.schemas
        ],
        domains=[
            CatalogFacetBucketResponse(value=item.value, count=item.count)
            for item in facets.domains
        ],
        lifecycles=[
            CatalogFacetBucketResponse(value=item.value, count=item.count)
            for item in facets.lifecycles
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
                database_name=item.database_name,
                schema_name=item.schema_name,
                matches=[
                    CatalogMatchFragmentResponse(
                        field=match.field,
                        text=match.text,
                        matched_terms=list(match.matched_terms),
                    )
                    for match in item.matches
                ],
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


@router.get("/vocabulary", response_model=CatalogVocabularyResponse)
async def catalog_vocabulary(
    request: Request,
    context: ContextDep,
    session: SessionDep,
    kind: Annotated[Literal["TAG", "TERM", "DOMAIN"], Query()],
    q: Annotated[str, Query(max_length=500)] = "",
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> CatalogVocabularyResponse:
    vocabulary = await _service(request, session).vocabulary(
        subject=context.subject,
        kind=kind,
        query=q,
        limit=limit,
        environment=context.environment,
        request_id=context.request_id,
    )
    return CatalogVocabularyResponse(
        items=list(vocabulary.items),
        meta=CatalogDiscoveryPolicyMeta(
            observed_at=vocabulary.observed_at,
            projection_version=vocabulary.projection_version,
            policy_version=vocabulary.policy_version,
            classification_policy_version=vocabulary.classification_policy_version,
            authorization_generation=vocabulary.authorization_generation,
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
    field_offset: Annotated[int, Query(ge=0, le=1_000)] = 0,
    field_limit: Annotated[int, Query(ge=1, le=200)] = 100,
    field_source_version: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
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
    if field_source_version is not None and field_source_version != asset.raw_version:
        raise ConflictError("The catalog schema changed during field pagination.")
    return catalog_detail(asset, field_offset=field_offset, field_limit=field_limit)


@router.get(
    "/assets/{asset_id}/datahub-lineage-embed",
    response_model=CatalogDataHubEmbedResponse,
)
async def get_asset_datahub_lineage_embed(
    asset_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> CatalogDataHubEmbedResponse | JSONResponse:
    """Return a server-built, allowlisted DataHub lineage frame for an authorized asset only."""
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
    url = get_container(request).settings.datahub_lineage_embed_url(asset.index.external_urn)
    response.headers["Cache-Control"] = "no-store, private"
    if url is None:
        settings = get_container(request).settings
        return CatalogDataHubEmbedResponse(
            state="UNAVAILABLE",
            reason_code=("NOT_CONFIGURED" if settings.datahub_embed_enabled else "DISABLED"),
        )
    return CatalogDataHubEmbedResponse(state="AVAILABLE", url=url)


@router.post(
    "/assets/{asset_id}/description-previews",
    response_model=CatalogDescriptionPreviewResponse,
)
async def preview_asset_description(
    asset_id: UUID,
    payload: CatalogDescriptionPreviewRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> CatalogDescriptionPreviewResponse:
    preview = await _description_service(request, session).preview(
        asset_id=asset_id,
        description=payload.description,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["ETag"] = preview.preview_etag
    response.headers["Cache-Control"] = "no-store, private"
    return CatalogDescriptionPreviewResponse(
        asset_id=preview.asset_id,
        target_ref=preview.target_ref,
        aspect_name="datasetProperties",
        current_description=preview.current_description,
        proposed_description=preview.proposed_description,
        before_hash=preview.before_hash,
        after_hash=preview.after_hash,
        preview_etag=preview.preview_etag,
        source_version=preview.source_version,
        observed_at=preview.observed_at,
    )


@router.post(
    "/assets/{asset_id}/description-change-requests",
    response_model=ChangeRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_asset_description_change_request(
    asset_id: UUID,
    payload: CatalogDescriptionChangeRequest,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    if_match: Annotated[str, Header(alias="If-Match", min_length=66, max_length=66)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> ChangeRequestResponse | JSONResponse:
    expected_preview_etag = _description_preview_etag(if_match)
    request_hash = hashlib.sha256(
        orjson.dumps(
            {
                "operation": "catalog.description-change-request.v1",
                "asset_id": str(asset_id),
                "expected_preview_etag": expected_preview_etag,
                "description": payload.description,
                "title": payload.title,
                "change_description": payload.change_description,
                "requested_due_date": payload.requested_due_date,
                "priority": payload.priority,
                "urgency": payload.urgency,
            },
            option=orjson.OPT_SORT_KEYS,
        )
    ).hexdigest()
    current_target = await _service(request, session).get_asset(
        subject=context.subject,
        asset_id=asset_id,
        environment=context.environment,
        request_id=context.request_id,
    )
    if current_target is None:
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
    number = change_request_number(current_target.index.platform)
    change_request = await _description_service(request, session).create_change_request(
        asset_id=asset_id,
        expected_preview_etag=expected_preview_etag,
        description=payload.description,
        title=payload.title,
        change_description=payload.change_description,
        number=number,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        requested_due_date=payload.requested_due_date,
        priority=ChangePriority(payload.priority) if payload.priority is not None else None,
        urgency=ChangeUrgency(payload.urgency) if payload.urgency is not None else None,
    )
    return change_request_response(change_request)


@router.post(
    "/assets/{asset_id}/column-description-previews",
    response_model=CatalogColumnDescriptionPreviewResponse,
)
async def preview_asset_column_description(
    asset_id: UUID,
    payload: CatalogColumnDescriptionPreviewRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> CatalogColumnDescriptionPreviewResponse:
    preview = await _description_service(request, session).preview_column_description(
        asset_id=asset_id,
        field_path=payload.field_path,
        description=payload.description,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["ETag"] = preview.preview_etag
    response.headers["Cache-Control"] = "no-store, private"
    return CatalogColumnDescriptionPreviewResponse(
        asset_id=preview.asset_id,
        target_ref=preview.target_ref,
        aspect_name="schemaMetadata",
        field_path=preview.field_path,
        current_description=preview.current_description,
        proposed_description=preview.proposed_description,
        before_hash=preview.before_hash,
        after_hash=preview.after_hash,
        preview_etag=preview.preview_etag,
        source_version=preview.source_version,
        observed_at=preview.observed_at,
    )


@router.post(
    "/assets/{asset_id}/column-description-change-requests",
    response_model=ChangeRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_asset_column_description_change_request(
    asset_id: UUID,
    payload: CatalogColumnDescriptionChangeRequest,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    if_match: Annotated[str, Header(alias="If-Match", min_length=66, max_length=66)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> ChangeRequestResponse | JSONResponse:
    expected_preview_etag = _description_preview_etag(if_match)
    request_hash = hashlib.sha256(
        orjson.dumps(
            {
                "operation": "catalog.column-description-change-request.v1",
                "asset_id": str(asset_id),
                "expected_preview_etag": expected_preview_etag,
                "field_path": payload.field_path,
                "description": payload.description,
                "title": payload.title,
                "change_description": payload.change_description,
            },
            option=orjson.OPT_SORT_KEYS,
        )
    ).hexdigest()
    current_target = await _service(request, session).get_asset(
        subject=context.subject,
        asset_id=asset_id,
        environment=context.environment,
        request_id=context.request_id,
    )
    if current_target is None:
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
    change_request = await _description_service(
        request, session
    ).create_column_description_change_request(
        asset_id=asset_id,
        expected_preview_etag=expected_preview_etag,
        field_path=payload.field_path,
        description=payload.description,
        title=payload.title,
        change_description=payload.change_description,
        number=change_request_number(current_target.index.platform),
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    return change_request_response(change_request)


@router.post(
    "/assets/{asset_id}/controlled-metadata-previews",
    response_model=CatalogControlledMetadataPreviewResponse,
)
async def preview_asset_controlled_metadata(
    asset_id: UUID,
    payload: CatalogControlledMetadataPreviewRequest,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
) -> CatalogControlledMetadataPreviewResponse:
    preview = await _description_service(request, session).preview_controlled_metadata(
        asset_id=asset_id,
        aspect_name=payload.aspect_name,
        refs=tuple(payload.refs),
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["ETag"] = preview.preview_etag
    response.headers["Cache-Control"] = "no-store, private"
    return CatalogControlledMetadataPreviewResponse(
        asset_id=preview.asset_id,
        target_ref=preview.target_ref,
        aspect_name=preview.aspect_name,
        current_refs=list(preview.current_refs),
        proposed_refs=list(preview.proposed_refs),
        before_hash=preview.before_hash,
        after_hash=preview.after_hash,
        preview_etag=preview.preview_etag,
        source_version=preview.source_version,
        observed_at=preview.observed_at,
    )


@router.post(
    "/assets/{asset_id}/controlled-metadata-change-requests",
    response_model=ChangeRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_asset_controlled_metadata_change_request(
    asset_id: UUID,
    payload: CatalogControlledMetadataChangeRequest,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    if_match: Annotated[str, Header(alias="If-Match", min_length=66, max_length=66)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> ChangeRequestResponse | JSONResponse:
    expected_preview_etag = _description_preview_etag(if_match)
    request_hash = hashlib.sha256(
        orjson.dumps(
            {
                "operation": "catalog.controlled-metadata-change-request.v1",
                "asset_id": str(asset_id),
                "expected_preview_etag": expected_preview_etag,
                "aspect_name": payload.aspect_name,
                "refs": payload.refs,
                "title": payload.title,
                "change_description": payload.change_description,
            },
            option=orjson.OPT_SORT_KEYS,
        )
    ).hexdigest()
    current_target = await _service(request, session).get_asset(
        subject=context.subject,
        asset_id=asset_id,
        environment=context.environment,
        request_id=context.request_id,
    )
    if current_target is None:
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
    change_request = await _description_service(
        request, session
    ).create_controlled_metadata_change_request(
        asset_id=asset_id,
        aspect_name=payload.aspect_name,
        refs=tuple(payload.refs),
        expected_preview_etag=expected_preview_etag,
        title=payload.title,
        change_description=payload.change_description,
        number=change_request_number(current_target.index.platform),
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    return change_request_response(change_request)


@router.post(
    "/assets/{asset_id}/metadata-recommendation-previews",
    response_model=CatalogRecommendationPreviewResponse,
    status_code=status.HTTP_201_CREATED,
)
async def preview_catalog_metadata_recommendations(
    asset_id: UUID,
    payload: CatalogRecommendationPreviewRequest,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=16, max_length=200),
    ],
) -> CatalogRecommendationPreviewResponse:
    request_hash = hashlib.sha256(
        orjson.dumps(
            {
                "operation": "catalog.metadata-recommendation-preview.v1",
                "workspace_id": str(context.workspace_id),
                "asset_id": str(asset_id),
                "field_path": payload.field_path,
                "source_version": payload.source_version,
                "vocabulary_ids": [str(value) for value in payload.vocabulary_ids],
            },
            option=orjson.OPT_SORT_KEYS,
        )
    ).hexdigest()
    values = await _recommendation_service(request, session).preview(
        workspace_id=context.workspace_id,
        asset_id=asset_id,
        field_path=payload.field_path,
        source_version=payload.source_version,
        vocabulary_ids=tuple(payload.vocabulary_ids),
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    return CatalogRecommendationPreviewResponse(
        items=[_recommendation_response(value) for value in values]
    )


@router.post(
    "/metadata-recommendations/approve",
    response_model=CatalogRecommendationApprovalResponse,
    status_code=status.HTTP_201_CREATED,
)
async def approve_catalog_metadata_recommendations(
    payload: CatalogRecommendationApproveRequest,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=16, max_length=200),
    ],
) -> CatalogRecommendationApprovalResponse:
    request_hash = hashlib.sha256(
        orjson.dumps(
            {
                "operation": "catalog.metadata-recommendation-approve.v1",
                "workspace_id": str(context.workspace_id),
                "targets": [
                    {
                        "recommendation_id": str(value.recommendation_id),
                        "expected_version": value.expected_version,
                    }
                    for value in payload.targets
                ],
                "title": payload.title,
                "reason": payload.reason,
            },
            option=orjson.OPT_SORT_KEYS,
        )
    ).hexdigest()
    result = await _recommendation_service(request, session).approve(
        workspace_id=context.workspace_id,
        targets=tuple(
            CatalogRecommendationApprovalTarget(
                recommendation_id=value.recommendation_id,
                expected_version=value.expected_version,
            )
            for value in payload.targets
        ),
        title=payload.title,
        reason=payload.reason,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    return CatalogRecommendationApprovalResponse(
        change_request_id=result.change_request_id,
        items=[_recommendation_response(value) for value in result.recommendations],
    )


@router.post(
    "/metadata-recommendations/{recommendation_id}/reject",
    response_model=CatalogRecommendationResponse,
)
async def reject_catalog_metadata_recommendation(
    recommendation_id: UUID,
    payload: CatalogRecommendationRejectRequest,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=16, max_length=200),
    ],
) -> CatalogRecommendationResponse:
    request_hash = hashlib.sha256(
        orjson.dumps(
            {
                "operation": "catalog.metadata-recommendation-reject.v1",
                "workspace_id": str(context.workspace_id),
                "recommendation_id": str(recommendation_id),
                "expected_version": payload.expected_version,
                "reason": payload.reason,
            },
            option=orjson.OPT_SORT_KEYS,
        )
    ).hexdigest()
    value = await _recommendation_service(request, session).reject(
        workspace_id=context.workspace_id,
        recommendation_id=recommendation_id,
        expected_version=payload.expected_version,
        reason=payload.reason,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    return _recommendation_response(value)


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
