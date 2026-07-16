from __future__ import annotations

import hashlib
import re
from typing import Annotated, Protocol, cast
from uuid import UUID

import orjson
from fastapi import APIRouter, Header, Request
from pydantic import BaseModel

from datariver.application.dto import (
    ApiProductRecord,
    ApiProductVersionRecord,
    ConsumerGrantRecord,
    InvocationAuthorizationRecord,
)
from datariver.application.errors import AuthenticationError
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.knowledge import KnowledgeService
from datariver.application.services.sharing import SharingService
from datariver.domain.authz import Action, Classification
from datariver.domain.classification_policy import unconfigured_chat_ceiling
from datariver.domain.common import NotFoundError, ValidationError
from datariver.domain.knowledge import GraphEdge, GraphNode, Provenance
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.knowledge import SqlKnowledgeStore
from datariver.infrastructure.db.sharing import SqlSharingStore
from datariver.interfaces.http.dependencies import ContextDep, SessionDep, get_container
from datariver.interfaces.http.schemas import (
    ApiInvocationAuthorizationResponse,
    ApiInvocationAuthorizeRequest,
    ApiProductChatEvidenceResponse,
    ApiProductChatInvokeRequest,
    ApiProductChatInvokeResponse,
    ApiProductCreate,
    ApiProductResponse,
    ApiProductVersionCreate,
    ApiProductVersionResponse,
    ApiSnapshotInvokeRequest,
    ConsumerGrantCreate,
    ConsumerGrantResponse,
    GraphEdgeResponse,
    GraphNodeResponse,
    KnowledgeReleaseResponse,
    KnowledgeSnapshotResponse,
    NeighborAnalysisRequest,
    NeighborAnalysisResponse,
    ProvenanceRequest,
)

router = APIRouter(prefix="/api-products", tags=["sharing"])


class _Serializable(Protocol):
    def model_dump(self, *, mode: str) -> dict[str, object]: ...


def _authorization(request: Request) -> AuthorizationService:
    container = get_container(request)
    return AuthorizationService(
        decision_writer=SqlDecisionWriter(container.database.session_factory)
    )


def _service(request: Request, session: SessionDep) -> SharingService:
    return SharingService(store=SqlSharingStore(session), authorization=_authorization(request))


def _knowledge_service(request: Request, session: SessionDep) -> KnowledgeService:
    return KnowledgeService(store=SqlKnowledgeStore(session), authorization=_authorization(request))


def _version_response(value: ApiProductVersionRecord) -> ApiProductVersionResponse:
    return ApiProductVersionResponse(
        id=value.version_id,
        product_id=value.product_id,
        graph_id=value.graph_id,
        release_id=value.release_id,
        version_no=value.version_no,
        surface=value.surface,
        contract=value.contract_document,
        maximum_hops=value.maximum_hops,
        maximum_nodes=value.maximum_nodes,
        timeout_ms=value.timeout_ms,
        state=value.state,
        published_at=value.published_at,
    )


def _product_response(value: ApiProductRecord) -> ApiProductResponse:
    return ApiProductResponse(
        id=value.product_id,
        slug=value.slug,
        name=value.name,
        description=value.description,
        graph_id=value.graph_id,
        classification=value.classification.name,
        owner_id=value.owner_id,
        state=value.state,
        current_version_id=value.current_version_id,
        version=value.version,
        versions=[_version_response(version) for version in value.versions],
    )


def _grant_response(value: ConsumerGrantRecord) -> ConsumerGrantResponse:
    return ConsumerGrantResponse(
        id=value.grant_id,
        product_id=value.product_id,
        product_version_id=value.product_version_id,
        consumer_client_id=value.consumer_client_id,
        scopes=list(value.scopes),
        maximum_classification=value.maximum_classification.name,
        requests_per_minute=value.requests_per_minute,
        monthly_quota=value.monthly_quota,
        valid_from=value.valid_from,
        expires_at=value.expires_at,
        state=value.state,
        version=value.version,
    )


def _invocation_response(
    value: InvocationAuthorizationRecord,
) -> ApiInvocationAuthorizationResponse:
    return ApiInvocationAuthorizationResponse(
        invocation_id=value.invocation_id,
        grant_id=value.grant_id,
        product_id=value.product_id,
        product_version_id=value.product_version_id,
        graph_id=value.graph_id,
        release_id=value.release_id,
        surface=value.surface,
        requested_scope=value.requested_scope,
        maximum_classification=value.maximum_classification.name,
        maximum_hops=value.maximum_hops,
        maximum_nodes=value.maximum_nodes,
        timeout_ms=value.timeout_ms,
    )


def _provenance_response(value: Provenance) -> ProvenanceRequest:
    return ProvenanceRequest(
        source_ref=value.source_ref,
        source_locator=value.source_locator,
        source_version=value.source_version,
        method=value.method,
        confidence=value.confidence,
    )


def _node_response(value: GraphNode) -> GraphNodeResponse:
    return GraphNodeResponse(
        id=value.entity_id,
        entity_type=value.entity_type,
        properties=value.properties,
        classification=value.classification,
        provenance=[_provenance_response(item) for item in value.provenance],
    )


def _edge_response(value: GraphEdge) -> GraphEdgeResponse:
    return GraphEdgeResponse(
        id=value.edge_id,
        source_id=value.source_entity_id,
        target_id=value.target_entity_id,
        edge_type=value.edge_type,
        properties=value.properties,
        classification=value.classification,
        provenance=[_provenance_response(item) for item in value.provenance],
    )


def _request_hash(payload: BaseModel) -> str:
    value = cast(_Serializable, payload).model_dump(mode="json")
    return hashlib.sha256(orjson.dumps(value, option=orjson.OPT_SORT_KEYS)).hexdigest()


def _expected_version(if_match: str) -> int:
    try:
        value = int(if_match.strip().strip('"'))
    except ValueError as error:
        raise ValidationError("If-Match must contain a positive integer version.") from error
    if value < 1:
        raise ValidationError("If-Match must contain a positive integer version.")
    return value


def _client_id(claims: dict[str, object]) -> str:
    value = claims.get("azp", claims.get("client_id"))
    if not isinstance(value, str) or not value:
        raise AuthenticationError("The access token has no authorized-party client identifier.")
    return value


async def _product_or_404(
    *,
    service: SharingService,
    product_id: UUID,
    context: ContextDep,
    action: Action = Action.SHARING_MANAGE,
) -> ApiProductRecord:
    product = await service.get_product(
        workspace_id=context.workspace_id,
        product_id=product_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        action=action,
    )
    if product is None:
        raise NotFoundError("The API product does not exist.")
    return product


@router.post("", status_code=201, response_model=ApiProductResponse)
async def create_product(
    payload: ApiProductCreate,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> ApiProductResponse:
    knowledge = _knowledge_service(request, session)
    graph = await knowledge.get_graph(
        workspace_id=context.workspace_id,
        graph_id=payload.graph_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if graph is None:
        raise NotFoundError("The graph selected for the API product does not exist.")
    releases = await knowledge.list_releases(
        workspace_id=context.workspace_id,
        graph=graph,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if not any(release.release_id == payload.release_id for release in releases):
        raise ValidationError("The selected immutable release does not belong to the graph.")
    product = await _service(request, session).create_product(
        workspace_id=context.workspace_id,
        subject=context.subject,
        graph_id=payload.graph_id,
        release_id=payload.release_id,
        classification=graph.classification,
        slug=payload.slug,
        name=payload.name,
        description=payload.description,
        surface=payload.surface,
        contract_document=payload.contract.model_dump(mode="json"),
        maximum_hops=payload.maximum_hops,
        maximum_nodes=payload.maximum_nodes,
        timeout_ms=payload.timeout_ms,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=_request_hash(payload),
    )
    return _product_response(product)


@router.get("", response_model=list[ApiProductResponse])
async def list_products(
    request: Request, context: ContextDep, session: SessionDep
) -> list[ApiProductResponse]:
    products = await _service(request, session).list_products(
        workspace_id=context.workspace_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return [_product_response(product) for product in products]


@router.post("/{product_id}/versions", status_code=201, response_model=ApiProductVersionResponse)
async def create_product_version(
    product_id: UUID,
    payload: ApiProductVersionCreate,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> ApiProductVersionResponse:
    service = _service(request, session)
    product = await _product_or_404(service=service, product_id=product_id, context=context)
    version = await service.create_version(
        product=product,
        workspace_id=context.workspace_id,
        subject=context.subject,
        release_id=payload.release_id,
        surface=payload.surface,
        contract_document=payload.contract.model_dump(mode="json"),
        maximum_hops=payload.maximum_hops,
        maximum_nodes=payload.maximum_nodes,
        timeout_ms=payload.timeout_ms,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=_request_hash(payload),
    )
    return _version_response(version)


@router.post("/{product_id}/versions/{version_id}/publish", response_model=ApiProductResponse)
async def publish_product_version(
    product_id: UUID,
    version_id: UUID,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    if_match: Annotated[str, Header(alias="If-Match")],
) -> ApiProductResponse:
    service = _service(request, session)
    product = await _product_or_404(
        service=service,
        product_id=product_id,
        context=context,
        action=Action.SHARING_PUBLISH,
    )
    updated = await service.publish_version(
        product=product,
        workspace_id=context.workspace_id,
        version_id=version_id,
        expected_version=_expected_version(if_match),
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return _product_response(updated)


@router.post("/{product_id}/grants", status_code=201, response_model=ConsumerGrantResponse)
async def create_consumer_grant(
    product_id: UUID,
    payload: ConsumerGrantCreate,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> ConsumerGrantResponse:
    service = _service(request, session)
    product = await _product_or_404(service=service, product_id=product_id, context=context)
    grant = await service.create_grant(
        product=product,
        workspace_id=context.workspace_id,
        consumer_client_id=payload.consumer_client_id,
        scopes=frozenset(payload.scopes),
        maximum_classification=Classification[payload.maximum_classification],
        requests_per_minute=payload.requests_per_minute,
        monthly_quota=payload.monthly_quota,
        valid_from=payload.valid_from,
        expires_at=payload.expires_at,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=_request_hash(payload),
    )
    return _grant_response(grant)


@router.get("/{product_id}/grants", response_model=list[ConsumerGrantResponse])
async def list_consumer_grants(
    product_id: UUID, request: Request, context: ContextDep, session: SessionDep
) -> list[ConsumerGrantResponse]:
    service = _service(request, session)
    product = await _product_or_404(service=service, product_id=product_id, context=context)
    grants = await service.list_grants(
        product=product,
        workspace_id=context.workspace_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return [_grant_response(grant) for grant in grants]


@router.post("/{product_id}/grants/{grant_id}/revoke", response_model=ConsumerGrantResponse)
async def revoke_consumer_grant(
    product_id: UUID,
    grant_id: UUID,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    if_match: Annotated[str, Header(alias="If-Match")],
) -> ConsumerGrantResponse:
    service = _service(request, session)
    product = await _product_or_404(service=service, product_id=product_id, context=context)
    grant = await service.revoke_grant(
        product=product,
        workspace_id=context.workspace_id,
        grant_id=grant_id,
        expected_version=_expected_version(if_match),
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return _grant_response(grant)


@router.post(
    "/{product_id}/authorize-invocation",
    response_model=ApiInvocationAuthorizationResponse,
)
async def authorize_invocation(
    product_id: UUID,
    payload: ApiInvocationAuthorizeRequest,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    invocation_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> ApiInvocationAuthorizationResponse:
    service = _service(request, session)
    product = await _product_or_404(
        service=service,
        product_id=product_id,
        context=context,
        action=Action.SHARING_INVOKE,
    )
    authorization = await service.authorize_invocation(
        product=product,
        workspace_id=context.workspace_id,
        consumer_client_id=_client_id(context.identity.claims),
        requested_scope=payload.requested_scope,
        invocation_key=invocation_key,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return _invocation_response(authorization)


@router.post(
    "/{product_id}/invoke/neighbors",
    response_model=NeighborAnalysisResponse,
)
async def invoke_neighbor_analysis(
    product_id: UUID,
    payload: NeighborAnalysisRequest,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    invocation_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> NeighborAnalysisResponse:
    service = _service(request, session)
    product = await _product_or_404(
        service=service,
        product_id=product_id,
        context=context,
        action=Action.SHARING_INVOKE,
    )
    authorization = await service.authorize_invocation(
        product=product,
        workspace_id=context.workspace_id,
        consumer_client_id=_client_id(context.identity.claims),
        requested_scope="neighbors.query",
        invocation_key=invocation_key,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if authorization.surface != "NEIGHBORS":
        raise ValidationError("This API product does not expose neighbor analysis.")
    if payload.maximum_hops > authorization.maximum_hops:
        raise ValidationError("The requested hop count exceeds the API product contract.")
    if payload.maximum_nodes > authorization.maximum_nodes:
        raise ValidationError("The requested node count exceeds the API product contract.")
    stored = await SqlKnowledgeStore(session).get_release_snapshot(
        workspace_id=context.workspace_id,
        graph_id=authorization.graph_id,
        release_id=authorization.release_id,
        clearance=min(int(context.subject.clearance), int(authorization.maximum_classification)),
        maximum_nodes=2000,
    )
    if stored is None:
        raise NotFoundError("The API product's pinned graph release is unavailable.")
    release, snapshot = stored
    view, truncated = snapshot.bounded_neighbors(
        node_id=payload.node_id,
        direction=payload.direction,
        edge_types=frozenset(payload.edge_types),
        maximum_hops=payload.maximum_hops,
        maximum_nodes=payload.maximum_nodes,
    )
    return NeighborAnalysisResponse(
        release=KnowledgeReleaseResponse(
            id=release.release_id,
            graph_id=release.graph_id,
            release_no=release.release_no,
            ontology_version_id=release.ontology_version_id,
            content_hash=view.content_hash(),
            node_count=len(view.nodes),
            edge_count=len(view.edges),
            published_at=release.published_at,
        ),
        nodes=[_node_response(node) for node in view.nodes.values()],
        edges=[_edge_response(edge) for edge in view.edges.values()],
        truncated=truncated,
    )


@router.post(
    "/{product_id}/invoke/snapshot",
    response_model=KnowledgeSnapshotResponse,
)
async def invoke_snapshot(
    product_id: UUID,
    payload: ApiSnapshotInvokeRequest,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    invocation_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> KnowledgeSnapshotResponse:
    service = _service(request, session)
    product = await _product_or_404(
        service=service,
        product_id=product_id,
        context=context,
        action=Action.SHARING_INVOKE,
    )
    authorization = await service.authorize_invocation(
        product=product,
        workspace_id=context.workspace_id,
        consumer_client_id=_client_id(context.identity.claims),
        requested_scope="snapshot.read",
        invocation_key=invocation_key,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if authorization.surface != "SNAPSHOT":
        raise ValidationError("This API product does not expose release snapshots.")
    if payload.maximum_nodes > authorization.maximum_nodes:
        raise ValidationError("The requested node count exceeds the API product contract.")
    stored = await SqlKnowledgeStore(session).get_release_snapshot(
        workspace_id=context.workspace_id,
        graph_id=authorization.graph_id,
        release_id=authorization.release_id,
        clearance=min(int(context.subject.clearance), int(authorization.maximum_classification)),
        maximum_nodes=payload.maximum_nodes,
    )
    if stored is None:
        raise NotFoundError("The API product's pinned graph release is unavailable.")
    release, snapshot = stored
    return KnowledgeSnapshotResponse(
        release=KnowledgeReleaseResponse(
            id=release.release_id,
            graph_id=release.graph_id,
            release_no=release.release_no,
            ontology_version_id=release.ontology_version_id,
            content_hash=snapshot.content_hash(),
            node_count=len(snapshot.nodes),
            edge_count=len(snapshot.edges),
            published_at=release.published_at,
        ),
        nodes=[_node_response(node) for node in snapshot.nodes.values()],
        edges=[_edge_response(edge) for edge in snapshot.edges.values()],
        filtered=(
            len(snapshot.nodes) != release.node_count or len(snapshot.edges) != release.edge_count
        ),
    )


@router.post(
    "/{product_id}/invoke/chat",
    response_model=ApiProductChatInvokeResponse,
)
async def invoke_chat(
    product_id: UUID,
    payload: ApiProductChatInvokeRequest,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    invocation_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> ApiProductChatInvokeResponse:
    service = _service(request, session)
    product = await _product_or_404(
        service=service,
        product_id=product_id,
        context=context,
        action=Action.SHARING_INVOKE,
    )
    authorization = await service.authorize_invocation(
        product=product,
        workspace_id=context.workspace_id,
        consumer_client_id=_client_id(context.identity.claims),
        requested_scope="chat.query",
        invocation_key=invocation_key,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if authorization.surface != "CHAT":
        raise ValidationError("This API product does not expose pinned-release Chat.")
    stored = await SqlKnowledgeStore(session).get_release_snapshot(
        workspace_id=context.workspace_id,
        graph_id=authorization.graph_id,
        release_id=authorization.release_id,
        clearance=min(
            int(unconfigured_chat_ceiling(context.subject.clearance)),
            int(authorization.maximum_classification),
        ),
        maximum_nodes=authorization.maximum_nodes,
    )
    if stored is None:
        raise NotFoundError("The API product's pinned graph release is unavailable.")
    release, snapshot = stored
    terms = {
        token
        for token in re.findall(r"[0-9A-Za-z가-힣_-]+", payload.question.lower())
        if len(token) > 1
    }
    ranked: list[tuple[int, str, GraphNode]] = []
    for node in snapshot.nodes.values():
        name = str(node.properties.get("name", node.entity_type))
        searchable = " ".join(
            (name, node.entity_type, str(node.properties.get("description", "")))
        ).lower()
        score = sum(term in searchable for term in terms)
        if score:
            ranked.append((score, str(node.entity_id), node))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected = [item[2] for item in ranked[: payload.maximum_evidence]]
    evidence = [
        ApiProductChatEvidenceResponse(
            entity_id=node.entity_id,
            entity_type=node.entity_type,
            name=str(node.properties.get("name", node.entity_type)),
            source_locator=(
                f"urn:datariver:graph:{authorization.graph_id}:release:"
                f"{authorization.release_id}:node:{node.entity_id}"
            ),
            source_version=release.content_hash,
        )
        for node in selected
    ]
    names = ", ".join(item.name for item in evidence)
    answer = (
        f"고정 릴리스의 권한 내 근거 {len(evidence)}건을 찾았습니다: {names}."
        if evidence
        else "고정 릴리스의 권한 내에서 질문과 일치하는 근거를 찾지 못했습니다."
    )
    return ApiProductChatInvokeResponse(
        invocation_id=authorization.invocation_id,
        answer=answer,
        evidence=evidence,
    )
