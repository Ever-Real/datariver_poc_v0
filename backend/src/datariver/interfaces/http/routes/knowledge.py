from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Annotated
from uuid import UUID

import orjson
from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse

from datariver.application.dto import (
    KnowledgeChangeSetRecord,
    KnowledgeGraphRecord,
    KnowledgeReleaseRecord,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.knowledge import KnowledgeService
from datariver.domain.authz import Action, Classification
from datariver.domain.common import ValidationError
from datariver.domain.knowledge import (
    ChangeOperationType,
    ChangeSetState,
    GraphChangeOperation,
    GraphEdge,
    GraphEntityKind,
    GraphNode,
    GraphSnapshot,
    Provenance,
)
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.knowledge import SqlKnowledgeStore
from datariver.interfaces.http.dependencies import ContextDep, SessionDep, get_container
from datariver.interfaces.http.schemas import (
    GraphEdgeResponse,
    GraphNodeResponse,
    KnowledgeChangeOperationCreate,
    KnowledgeChangeOperationResponse,
    KnowledgeChangeSetCreate,
    KnowledgeChangeSetPublishResponse,
    KnowledgeChangeSetResponse,
    KnowledgeChangeSetReview,
    KnowledgeGraphCreate,
    KnowledgeGraphResponse,
    KnowledgeReleasePublish,
    KnowledgeReleaseResponse,
    KnowledgeSnapshotResponse,
    KnowledgeValidationResponse,
    NeighborAnalysisRequest,
    NeighborAnalysisResponse,
    ProvenanceRequest,
)

router = APIRouter(prefix="/knowledge/graphs", tags=["knowledge"])


def _service(request: Request, session: SessionDep) -> KnowledgeService:
    container = get_container(request)
    return KnowledgeService(
        store=SqlKnowledgeStore(session),
        authorization=AuthorizationService(
            decision_writer=SqlDecisionWriter(container.database.session_factory)
        ),
    )


def _graph_response(graph: KnowledgeGraphRecord) -> KnowledgeGraphResponse:
    return KnowledgeGraphResponse(
        id=graph.graph_id,
        slug=graph.slug,
        name=graph.name,
        graph_type=graph.graph_type,
        status=graph.status,
        classification=graph.classification.name,
        active_release_id=graph.active_release_id,
        version=graph.version,
    )


def _release_response(release: KnowledgeReleaseRecord) -> KnowledgeReleaseResponse:
    return KnowledgeReleaseResponse(
        id=release.release_id,
        graph_id=release.graph_id,
        release_no=release.release_no,
        ontology_version_id=release.ontology_version_id,
        content_hash=release.content_hash,
        node_count=release.node_count,
        edge_count=release.edge_count,
        published_at=release.published_at,
    )


def _scoped_release(
    release: KnowledgeReleaseRecord, snapshot: GraphSnapshot
) -> KnowledgeReleaseRecord:
    return replace(
        release,
        content_hash=snapshot.content_hash(),
        node_count=len(snapshot.nodes),
        edge_count=len(snapshot.edges),
    )


def _changeset_response(changeset: KnowledgeChangeSetRecord) -> KnowledgeChangeSetResponse:
    return KnowledgeChangeSetResponse(
        id=changeset.changeset_id,
        graph_id=changeset.graph_id,
        base_release_id=changeset.base_release_id,
        ontology_version_id=changeset.ontology_version_id,
        title=changeset.title,
        state=changeset.state,
        author_id=changeset.author_id,
        reviewed_by=changeset.reviewed_by,
        review_reason=changeset.review_reason,
        published_release_id=changeset.published_release_id,
        version=changeset.version,
        created_at=changeset.created_at,
        updated_at=changeset.updated_at,
        operations=[
            KnowledgeChangeOperationResponse(
                id=item.operation_id,
                sequence=item.sequence,
                operation=item.operation,
                entity_kind=item.entity_kind,
                stable_entity_id=item.stable_entity_id,
                document=item.document,
                provenance=[ProvenanceRequest(**value) for value in item.provenance],
                confidence=item.confidence,
            )
            for item in changeset.operations
        ],
        validations=[
            KnowledgeValidationResponse(
                id=item.validation_id,
                severity=item.severity,
                code=item.code,
                location=item.location,
                message=item.message,
                validator=item.validator,
                validator_version=item.validator_version,
            )
            for item in changeset.validations
        ],
    )


def _provenance(items: list[ProvenanceRequest]) -> tuple[Provenance, ...]:
    return tuple(Provenance(**item.model_dump()) for item in items)


def _provenance_response(item: Provenance) -> ProvenanceRequest:
    return ProvenanceRequest(
        source_ref=item.source_ref,
        source_locator=item.source_locator,
        source_version=item.source_version,
        method=item.method,
        confidence=item.confidence,
    )


def _node_response(node: GraphNode) -> GraphNodeResponse:
    return GraphNodeResponse(
        id=node.entity_id,
        entity_type=node.entity_type,
        properties=node.properties,
        classification=node.classification,
        provenance=[_provenance_response(item) for item in node.provenance],
    )


def _edge_response(edge: GraphEdge) -> GraphEdgeResponse:
    return GraphEdgeResponse(
        id=edge.edge_id,
        source_id=edge.source_entity_id,
        target_id=edge.target_entity_id,
        edge_type=edge.edge_type,
        properties=edge.properties,
        classification=edge.classification,
        provenance=[_provenance_response(item) for item in edge.provenance],
    )


def _snapshot(payload: KnowledgeReleasePublish) -> GraphSnapshot:
    nodes = {
        item.id: GraphNode(
            entity_id=item.id,
            entity_type=item.entity_type,
            properties=item.properties,
            classification=item.classification,
            provenance=_provenance(item.provenance),
        )
        for item in payload.nodes
    }
    if len(nodes) != len(payload.nodes):
        raise ValidationError("Knowledge graph node identifiers must be unique.")
    edges = {
        item.id: GraphEdge(
            edge_id=item.id,
            source_entity_id=item.source_id,
            target_entity_id=item.target_id,
            edge_type=item.edge_type,
            properties=item.properties,
            classification=item.classification,
            provenance=_provenance(item.provenance),
        )
        for item in payload.edges
    }
    if len(edges) != len(payload.edges):
        raise ValidationError("Knowledge graph edge identifiers must be unique.")
    return GraphSnapshot(nodes=nodes, edges=edges)


def _base_hash(if_match: str) -> str | None:
    value = if_match.strip().strip('"')
    if value == "none":
        return None
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValidationError('If-Match must be "none" or a quoted SHA-256 release hash.')
    return value


def _expected_version(if_match: str) -> int:
    value = if_match.strip().strip('"')
    try:
        version = int(value)
    except ValueError as error:
        raise ValidationError("If-Match must contain a positive integer version.") from error
    if version < 1:
        raise ValidationError("If-Match must contain a positive integer version.")
    return version


def _not_found(request: Request, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "type": "urn:datariver:problem:not_found",
            "title": "Not found",
            "status": 404,
            "detail": "The knowledge graph or release does not exist.",
            "instance": str(request.url.path),
            "code": "not_found",
            "request_id": request_id,
        },
    )


@router.post("", status_code=201, response_model=KnowledgeGraphResponse)
async def create_graph(
    payload: KnowledgeGraphCreate,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> KnowledgeGraphResponse:
    request_hash = hashlib.sha256(
        orjson.dumps(payload.model_dump(mode="json"), option=orjson.OPT_SORT_KEYS)
    ).hexdigest()
    graph = await _service(request, session).create_graph(
        workspace_id=context.workspace_id,
        subject=context.subject,
        slug=payload.slug,
        name=payload.name,
        graph_type=payload.graph_type,
        classification=Classification[payload.classification],
        entity_types=frozenset(payload.ontology.entity_types),
        edge_types=frozenset(payload.ontology.edge_types),
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    return _graph_response(graph)


@router.get("", response_model=list[KnowledgeGraphResponse])
async def list_graphs(
    request: Request,
    context: ContextDep,
    session: SessionDep,
) -> list[KnowledgeGraphResponse]:
    graphs = await _service(request, session).list_graphs(
        workspace_id=context.workspace_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return [_graph_response(graph) for graph in graphs]


@router.post("/{graph_id}/changesets", status_code=201, response_model=KnowledgeChangeSetResponse)
async def create_changeset(
    graph_id: UUID,
    payload: KnowledgeChangeSetCreate,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> KnowledgeChangeSetResponse | JSONResponse:
    service = _service(request, session)
    graph = await service.get_graph(
        workspace_id=context.workspace_id,
        graph_id=graph_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if graph is None:
        return _not_found(request, context.request_id)
    request_hash = hashlib.sha256(
        orjson.dumps(payload.model_dump(mode="json"), option=orjson.OPT_SORT_KEYS)
    ).hexdigest()
    changeset = await service.create_changeset(
        workspace_id=context.workspace_id,
        graph=graph,
        title=payload.title,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    return _changeset_response(changeset)


@router.get("/{graph_id}/changesets", response_model=list[KnowledgeChangeSetResponse])
async def list_changesets(
    graph_id: UUID,
    request: Request,
    context: ContextDep,
    session: SessionDep,
) -> list[KnowledgeChangeSetResponse] | JSONResponse:
    service = _service(request, session)
    graph = await service.get_graph(
        workspace_id=context.workspace_id,
        graph_id=graph_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if graph is None:
        return _not_found(request, context.request_id)
    values = await service.list_changesets(
        workspace_id=context.workspace_id,
        graph=graph,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return [_changeset_response(value) for value in values]


@router.post(
    "/{graph_id}/changesets/{changeset_id}/operations",
    response_model=KnowledgeChangeSetResponse,
)
async def append_change_operation(
    graph_id: UUID,
    changeset_id: UUID,
    payload: KnowledgeChangeOperationCreate,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
) -> KnowledgeChangeSetResponse | JSONResponse:
    service = _service(request, session)
    graph = await service.get_graph(
        workspace_id=context.workspace_id,
        graph_id=graph_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if graph is None:
        return _not_found(request, context.request_id)
    operation = GraphChangeOperation(
        sequence=payload.sequence,
        operation=ChangeOperationType(payload.operation),
        entity_kind=GraphEntityKind(payload.entity_kind),
        stable_entity_id=payload.stable_entity_id,
        document=payload.document,
        provenance=_provenance(payload.provenance),
        confidence=payload.confidence,
    )
    changeset = await service.append_change_operation(
        workspace_id=context.workspace_id,
        graph=graph,
        changeset_id=changeset_id,
        operation=operation,
        expected_version=_expected_version(if_match),
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return _changeset_response(changeset)


@router.post(
    "/{graph_id}/changesets/{changeset_id}/submit",
    response_model=KnowledgeChangeSetResponse,
)
async def submit_changeset(
    graph_id: UUID,
    changeset_id: UUID,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
) -> KnowledgeChangeSetResponse | JSONResponse:
    service = _service(request, session)
    graph = await service.get_graph(
        workspace_id=context.workspace_id,
        graph_id=graph_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if graph is None:
        return _not_found(request, context.request_id)
    changeset = await service.submit_changeset(
        workspace_id=context.workspace_id,
        graph=graph,
        changeset_id=changeset_id,
        expected_version=_expected_version(if_match),
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return _changeset_response(changeset)


@router.post(
    "/{graph_id}/changesets/{changeset_id}/reviews",
    response_model=KnowledgeChangeSetResponse,
)
async def review_changeset(
    graph_id: UUID,
    changeset_id: UUID,
    payload: KnowledgeChangeSetReview,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
) -> KnowledgeChangeSetResponse | JSONResponse:
    service = _service(request, session)
    graph = await service.get_graph(
        workspace_id=context.workspace_id,
        graph_id=graph_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if graph is None:
        return _not_found(request, context.request_id)
    changeset = await service.review_changeset(
        workspace_id=context.workspace_id,
        graph=graph,
        changeset_id=changeset_id,
        decision=ChangeSetState(payload.decision),
        reason=payload.reason,
        expected_version=_expected_version(if_match),
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return _changeset_response(changeset)


@router.post(
    "/{graph_id}/changesets/{changeset_id}/publish",
    response_model=KnowledgeChangeSetPublishResponse,
)
async def publish_changeset(
    graph_id: UUID,
    changeset_id: UUID,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> KnowledgeChangeSetPublishResponse | JSONResponse:
    service = _service(request, session)
    graph = await service.get_graph(
        workspace_id=context.workspace_id,
        graph_id=graph_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if graph is None:
        return _not_found(request, context.request_id)
    request_hash = hashlib.sha256(f"changeset:{changeset_id}".encode()).hexdigest()
    changeset, release = await service.publish_changeset(
        workspace_id=context.workspace_id,
        graph=graph,
        changeset_id=changeset_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    return KnowledgeChangeSetPublishResponse(
        changeset=_changeset_response(changeset), release=_release_response(release)
    )


@router.get("/{graph_id}/releases", response_model=list[KnowledgeReleaseResponse])
async def list_releases(
    graph_id: UUID,
    request: Request,
    context: ContextDep,
    session: SessionDep,
) -> list[KnowledgeReleaseResponse] | JSONResponse:
    service = _service(request, session)
    graph = await service.get_graph(
        workspace_id=context.workspace_id,
        graph_id=graph_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if graph is None:
        return _not_found(request, context.request_id)
    releases = await service.list_releases(
        workspace_id=context.workspace_id,
        graph=graph,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return [_release_response(release) for release in releases]


@router.post("/{graph_id}/releases/{release_id}/activate", response_model=KnowledgeGraphResponse)
async def activate_release(
    graph_id: UUID,
    release_id: UUID,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
) -> KnowledgeGraphResponse | JSONResponse:
    service = _service(request, session)
    graph = await service.get_graph(
        workspace_id=context.workspace_id,
        graph_id=graph_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if graph is None:
        return _not_found(request, context.request_id)
    activated = await service.activate_release(
        workspace_id=context.workspace_id,
        graph=graph,
        release_id=release_id,
        expected_graph_version=_expected_version(if_match),
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    return _graph_response(activated)


@router.post("/{graph_id}/releases", status_code=201, response_model=KnowledgeReleaseResponse)
async def publish_release(
    graph_id: UUID,
    payload: KnowledgeReleasePublish,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> KnowledgeReleaseResponse | JSONResponse:
    service = _service(request, session)
    graph = await service.get_graph(
        workspace_id=context.workspace_id,
        graph_id=graph_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if graph is None:
        return _not_found(request, context.request_id)
    expected_base_hash = _base_hash(if_match)
    request_hash = hashlib.sha256(
        orjson.dumps(
            {"base_hash": expected_base_hash, "snapshot": payload.model_dump(mode="json")},
            option=orjson.OPT_SORT_KEYS,
        )
    ).hexdigest()
    release = await service.publish_release(
        workspace_id=context.workspace_id,
        graph=graph,
        snapshot=_snapshot(payload),
        expected_base_hash=expected_base_hash,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    return _release_response(release)


@router.get(
    "/{graph_id}/releases/{release_id}/snapshot",
    response_model=KnowledgeSnapshotResponse,
)
async def get_release_snapshot(
    graph_id: UUID,
    release_id: UUID,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    maximum_nodes: Annotated[int, Query(ge=1, le=500)] = 200,
) -> KnowledgeSnapshotResponse | JSONResponse:
    service = _service(request, session)
    graph = await service.get_graph(
        workspace_id=context.workspace_id,
        graph_id=graph_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if graph is None:
        return _not_found(request, context.request_id)
    result = await service.get_release_snapshot(
        workspace_id=context.workspace_id,
        graph=graph,
        release_id=release_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        maximum_nodes=maximum_nodes,
    )
    if result is None:
        return _not_found(request, context.request_id)
    release, snapshot = result
    visible_release = _scoped_release(release, snapshot)
    nodes = [_node_response(node) for node in snapshot.nodes.values()]
    edges = [_edge_response(edge) for edge in snapshot.edges.values()]
    return KnowledgeSnapshotResponse(
        release=_release_response(visible_release),
        nodes=nodes,
        edges=edges,
        filtered=len(nodes) != release.node_count or len(edges) != release.edge_count,
    )


@router.get("/{graph_id}/releases/{release_id}/export")
async def export_release(
    graph_id: UUID,
    release_id: UUID,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    export_format: Annotated[
        str, Query(alias="format", pattern="^(json-ld|edge-list)$")
    ] = "json-ld",
) -> JSONResponse:
    service = _service(request, session)
    graph = await service.get_graph(
        workspace_id=context.workspace_id,
        graph_id=graph_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if graph is None:
        return _not_found(request, context.request_id)
    result = await service.get_release_for_action(
        workspace_id=context.workspace_id,
        graph=graph,
        release_id=release_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        action=Action.KG_EXPORT,
        maximum_nodes=2000,
    )
    if result is None:
        return _not_found(request, context.request_id)
    release, snapshot = result
    release = _scoped_release(release, snapshot)
    release_document = {
        "id": str(release.release_id),
        "graph_id": str(release.graph_id),
        "release_no": release.release_no,
        "content_hash": release.content_hash,
    }
    if export_format == "edge-list":
        content = {
            "release": release_document,
            "nodes": [
                {
                    "id": str(node.entity_id),
                    "type": node.entity_type,
                    "properties": node.properties,
                }
                for node in snapshot.nodes.values()
            ],
            "edges": [
                {
                    "id": str(edge.edge_id),
                    "source": str(edge.source_entity_id),
                    "target": str(edge.target_entity_id),
                    "type": edge.edge_type,
                    "properties": edge.properties,
                }
                for edge in snapshot.edges.values()
            ],
        }
    else:
        content = {
            "@context": {
                "type": "@type",
                "source": {"@type": "@id"},
                "target": {"@type": "@id"},
            },
            "release": release_document,
            "@graph": [
                {
                    "@id": f"urn:datariver:entity:{node.entity_id}",
                    "type": node.entity_type,
                    "properties": node.properties,
                }
                for node in snapshot.nodes.values()
            ]
            + [
                {
                    "@id": f"urn:datariver:edge:{edge.edge_id}",
                    "type": edge.edge_type,
                    "source": f"urn:datariver:entity:{edge.source_entity_id}",
                    "target": f"urn:datariver:entity:{edge.target_entity_id}",
                    "properties": edge.properties,
                }
                for edge in snapshot.edges.values()
            ],
        }
    return JSONResponse(content=content, headers={"ETag": f'"{release.content_hash}"'})


@router.post(
    "/{graph_id}/releases/{release_id}/analysis/neighbors",
    response_model=NeighborAnalysisResponse,
)
async def analyze_neighbors(
    graph_id: UUID,
    release_id: UUID,
    payload: NeighborAnalysisRequest,
    request: Request,
    context: ContextDep,
    session: SessionDep,
) -> NeighborAnalysisResponse | JSONResponse:
    service = _service(request, session)
    graph = await service.get_graph(
        workspace_id=context.workspace_id,
        graph_id=graph_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if graph is None:
        return _not_found(request, context.request_id)
    result = await service.get_release_for_action(
        workspace_id=context.workspace_id,
        graph=graph,
        release_id=release_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        action=Action.SHARING_INVOKE,
        maximum_nodes=2000,
    )
    if result is None:
        return _not_found(request, context.request_id)
    release, snapshot = result
    visible_release = _scoped_release(release, snapshot)
    view, truncated = snapshot.bounded_neighbors(
        node_id=payload.node_id,
        direction=payload.direction,
        edge_types=frozenset(payload.edge_types),
        maximum_hops=payload.maximum_hops,
        maximum_nodes=payload.maximum_nodes,
    )
    return NeighborAnalysisResponse(
        release=_release_response(visible_release),
        nodes=[_node_response(node) for node in view.nodes.values()],
        edges=[_edge_response(edge) for edge in view.edges.values()],
        truncated=truncated,
    )
