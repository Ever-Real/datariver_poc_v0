from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Path, Query, Request, Response

from datariver.application.knowledge_asset_contracts import (
    KnowledgeAssetOperationalDetail,
    KnowledgeAssetSummary,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.knowledge_assets import KnowledgeAssetService
from datariver.domain.common import ValidationError, canonical_json_hash
from datariver.domain.knowledge_assets import KnowledgeDeliveryPolicy
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.knowledge_assets import SqlKnowledgeAssetRepository
from datariver.interfaces.http.dependencies import ContextDep, SessionDep, get_container
from datariver.interfaces.http.schemas import (
    KnowledgeAssetBindingSummaryResponse,
    KnowledgeAssetEndpointResponse,
    KnowledgeAssetOperationalDetailResponse,
    KnowledgeAssetPageResponse,
    KnowledgeAssetProjectionSummaryResponse,
    KnowledgeAssetSchemaElementSummaryResponse,
    KnowledgeAssetSummaryResponse,
    KnowledgeAssetVersionEventResponse,
    KnowledgeAssetVersionPageResponse,
    KnowledgeDeliveryPolicyResponse,
    KnowledgeDeliveryPolicyUpdate,
)

registry_router = APIRouter(prefix="/knowledge/registry", tags=["knowledge-registry"])
endpoint_router = APIRouter(prefix="/knowledge/assets", tags=["knowledge-assets"])


def _service(request: Request, session: SessionDep) -> KnowledgeAssetService:
    container = get_container(request)
    return KnowledgeAssetService(
        repository=SqlKnowledgeAssetRepository(session),
        authorization=AuthorizationService(
            decision_writer=SqlDecisionWriter(container.database.session_factory)
        ),
    )


def _policy_response(policy: KnowledgeDeliveryPolicy) -> KnowledgeDeliveryPolicyResponse:
    return KnowledgeDeliveryPolicyResponse(
        id=policy.policy_id,
        graph_id=policy.graph_id,
        api_enabled=policy.api_enabled,
        chat_enabled=policy.chat_enabled,
        priority=policy.priority,
        match_any_terms=list(policy.match_any_terms),
        match_all_terms=list(policy.match_all_terms),
        excluded_terms=list(policy.excluded_terms),
        version=policy.version,
        created_by=policy.created_by,
        updated_by=policy.updated_by,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


def _asset_response(asset: KnowledgeAssetSummary) -> KnowledgeAssetSummaryResponse:
    return KnowledgeAssetSummaryResponse(
        id=asset.graph_id,
        slug=asset.slug,
        name=asset.name,
        graph_type=asset.graph_type,
        status=asset.status,
        classification=asset.classification.name,
        domain_id=asset.domain_id,
        domain_name=asset.domain_name,
        creator_name=asset.creator_name,
        creator_email=asset.creator_email,
        editor_name=asset.editor_name,
        editor_email=asset.editor_email,
        active_studio_release_id=asset.active_studio_release_id,
        active_studio_release_no=asset.active_studio_release_no,
        active_release_id=asset.active_release_id,
        active_release_no=asset.active_release_no,
        class_count=asset.class_count,
        property_count=asset.property_count,
        relationship_count=asset.relationship_count,
        binding_count=asset.binding_count,
        source_count=asset.source_count,
        node_count=asset.node_count,
        edge_count=asset.edge_count,
        projection_state=asset.projection_state,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
        version=asset.version,
        delivery_policy=(
            _policy_response(asset.delivery_policy) if asset.delivery_policy is not None else None
        ),
    )


def _detail_response(
    detail: KnowledgeAssetOperationalDetail,
) -> KnowledgeAssetOperationalDetailResponse:
    return KnowledgeAssetOperationalDetailResponse(
        asset=_asset_response(detail.asset),
        schema_elements=[
            KnowledgeAssetSchemaElementSummaryResponse(
                stable_element_id=item.stable_element_id,
                kind=item.kind,
                display_name=item.display_name,
                canonical_name=item.canonical_name,
                data_type=item.data_type,
                source_stable_element_id=item.source_stable_element_id,
                target_stable_element_id=item.target_stable_element_id,
            )
            for item in detail.schema_elements
        ],
        bindings=[
            KnowledgeAssetBindingSummaryResponse(
                id=item.binding_id,
                target_stable_element_id=item.target_stable_element_id,
                source_reference_id=item.source_reference_id,
                source_kind=item.source_kind,
                source_name=item.source_name,
                source_version=item.source_version,
                mapping_rule_count=item.mapping_rule_count,
            )
            for item in detail.bindings
        ],
        projections=[
            KnowledgeAssetProjectionSummaryResponse(
                id=item.deployment_id,
                release_id=item.release_id,
                adapter=item.adapter,
                state=item.state,
                node_count=item.node_count,
                edge_count=item.edge_count,
                verified_at=item.verified_at,
                error_code=item.error_code,
                updated_at=item.updated_at,
            )
            for item in detail.projections
        ],
    )


def _expected_version(if_match: str | None) -> int | None:
    if if_match is None:
        return None
    value = if_match.strip()
    if len(value) < 3 or value[0] != '"' or value[-1] != '"' or not value[1:-1].isdigit():
        raise ValidationError("If-Match must contain a quoted integer version.")
    return int(value[1:-1])


@registry_router.get("/assets", response_model=KnowledgeAssetPageResponse)
async def list_knowledge_assets(
    request: Request,
    context: ContextDep,
    session: SessionDep,
    q: Annotated[str, Query(max_length=200)] = "",
    domain_id: Annotated[UUID | None, Query()] = None,
    sort: Annotated[str, Query(pattern="^(UPDATED_DESC|NAME_ASC)$")] = "UPDATED_DESC",
    cursor: Annotated[str | None, Query(max_length=2_000)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> KnowledgeAssetPageResponse:
    page = await _service(request, session).list_assets(
        workspace_id=context.workspace_id,
        subject=context.subject,
        query=q,
        domain_id=domain_id,
        sort=sort,
        cursor=cursor,
        limit=limit,
        environment=context.environment,
        request_id=context.request_id,
    )
    return KnowledgeAssetPageResponse(
        items=[_asset_response(item) for item in page.items],
        next_cursor=page.next_cursor,
        limit=limit,
    )


@registry_router.get(
    "/assets/{graph_id}/detail",
    response_model=KnowledgeAssetOperationalDetailResponse,
)
async def get_knowledge_asset_detail(
    graph_id: UUID,
    request: Request,
    context: ContextDep,
    session: SessionDep,
) -> KnowledgeAssetOperationalDetailResponse:
    detail = await _service(request, session).get_detail(
        workspace_id=context.workspace_id,
        graph_id=graph_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return _detail_response(detail)


@registry_router.get(
    "/assets/{graph_id}/versions",
    response_model=KnowledgeAssetVersionPageResponse,
)
async def list_knowledge_asset_versions(
    graph_id: UUID,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    cursor: Annotated[str | None, Query(max_length=2_000)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> KnowledgeAssetVersionPageResponse:
    page = await _service(request, session).list_versions(
        workspace_id=context.workspace_id,
        graph_id=graph_id,
        subject=context.subject,
        cursor=cursor,
        limit=limit,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return KnowledgeAssetVersionPageResponse(
        items=[
            KnowledgeAssetVersionEventResponse(
                id=item.event_id,
                kind=item.kind,
                version_label=item.version_label,
                title=item.title,
                status=item.status,
                author_id=item.author_id,
                author_name=item.author_name,
                author_email=item.author_email,
                reviewed_by=item.reviewed_by,
                reviewer_name=item.reviewer_name,
                reviewer_email=item.reviewer_email,
                published_by=item.published_by,
                publisher_name=item.publisher_name,
                publisher_email=item.publisher_email,
                created_at=item.created_at,
                is_current=item.is_current,
                studio_release_id=item.studio_release_id,
                instance_release_id=item.instance_release_id,
                changeset_id=item.changeset_id,
                content_hash=item.content_hash,
                node_count=item.node_count,
                edge_count=item.edge_count,
            )
            for item in page.items
        ],
        next_cursor=page.next_cursor,
        limit=limit,
    )


@registry_router.put(
    "/assets/{graph_id}/delivery-policy",
    response_model=KnowledgeDeliveryPolicyResponse,
)
async def save_knowledge_delivery_policy(
    graph_id: UUID,
    payload: KnowledgeDeliveryPolicyUpdate,
    request: Request,
    response: Response,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=16, max_length=200),
    ],
    if_match: Annotated[str | None, Header(alias="If-Match", max_length=100)] = None,
) -> KnowledgeDeliveryPolicyResponse:
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "contract": "KNOWLEDGE_DELIVERY_POLICY_V1",
            "graph_id": str(graph_id),
            "expected_version": expected_version,
            **payload.model_dump(mode="json"),
        }
    )
    policy = await _service(request, session).save_delivery_policy(
        workspace_id=context.workspace_id,
        graph_id=graph_id,
        subject=context.subject,
        api_enabled=payload.api_enabled,
        chat_enabled=payload.chat_enabled,
        priority=payload.priority,
        match_any_terms=tuple(payload.match_any_terms),
        match_all_terms=tuple(payload.match_all_terms),
        excluded_terms=tuple(payload.excluded_terms),
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    response.headers["ETag"] = f'"{policy.version}"'
    response.headers["Cache-Control"] = "no-store"
    return _policy_response(policy)


@endpoint_router.get(
    "/by-alias/{alias}",
    response_model=KnowledgeAssetEndpointResponse,
)
async def resolve_knowledge_asset_endpoint(
    alias: Annotated[str, Path(pattern="^[a-z][a-z0-9_-]{2,99}$")],
    request: Request,
    context: ContextDep,
    session: SessionDep,
) -> KnowledgeAssetEndpointResponse:
    asset = await _service(request, session).resolve_api_asset(
        workspace_id=context.workspace_id,
        alias=alias,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    graph_base = f"/api/v1/knowledge/graphs/{asset.graph_id}"
    release_base = (
        f"{graph_base}/releases/{asset.active_release_id}"
        if asset.active_release_id is not None
        else None
    )
    return KnowledgeAssetEndpointResponse(
        alias=alias,
        graph_id=asset.graph_id,
        active_studio_release_id=asset.active_studio_release_id,
        active_release_id=asset.active_release_id,
        contract_path=f"/api/v1/knowledge/registry/assets/{asset.graph_id}/detail",
        snapshot_path=f"{release_base}/snapshot" if release_base else None,
        graphrag_path=f"{release_base}/graphrag" if release_base else None,
        export_paths=(
            [
                f"{release_base}/export?format=json-ld",
                f"{release_base}/export?format=edge-list",
            ]
            if release_base
            else []
        ),
    )
