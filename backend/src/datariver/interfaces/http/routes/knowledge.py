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
from datariver.application.knowledge_source_job_contracts import KnowledgeSourceJobRecord
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.knowledge import KnowledgeService
from datariver.application.services.knowledge_pipeline import (
    KnowledgeGraphRagService,
    VerifiedProjectionService,
)
from datariver.domain.authz import Action, Classification
from datariver.domain.common import ConflictError, ValidationError, canonical_json_hash
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
from datariver.infrastructure.db.knowledge_pipeline import (
    SqlKnowledgePipelineRepository,
    SqlSemanticSeedSelector,
)
from datariver.infrastructure.db.knowledge_source_jobs import (
    SqlKnowledgeSourceJobStore,
    knowledge_requester_authorization_hash,
)
from datariver.infrastructure.knowledge.neo4j import (
    Neo4jKnowledgeProjectionAdapter,
    Neo4jScopedEvidenceRetriever,
)
from datariver.infrastructure.knowledge.runtime import (
    KnowledgeRuntimeAdapters,
    build_knowledge_runtime_adapters,
    resolve_knowledge_runtime_bindings,
)
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
    KnowledgeGraphArchiveRequest,
    KnowledgeGraphCreate,
    KnowledgeGraphRagCitationResponse,
    KnowledgeGraphRagRequest,
    KnowledgeGraphRagResponse,
    KnowledgeGraphResponse,
    KnowledgeModelAuditResponse,
    KnowledgeProjectionResponse,
    KnowledgeReleaseResponse,
    KnowledgeSnapshotResponse,
    KnowledgeSourceAnalyzeRequest,
    KnowledgeSourceJobCancelRequest,
    KnowledgeSourceJobPageResponse,
    KnowledgeSourceJobResponse,
    KnowledgeSourceJobResultResponse,
    KnowledgeValidationResponse,
    NeighborAnalysisRequest,
    NeighborAnalysisResponse,
    ProvenanceRequest,
)

router = APIRouter(prefix="/knowledge/graphs", tags=["knowledge"])


def _knowledge_adapters(request: Request) -> KnowledgeRuntimeAdapters:
    return build_knowledge_runtime_adapters(get_container(request).settings)


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
        domain_id=graph.domain_id,
        domain_name=graph.domain_name,
        domain_source_version=graph.domain_source_version,
        created_by=graph.created_by,
        updated_by=graph.updated_by,
        created_at=graph.created_at,
        updated_at=graph.updated_at,
    )


def _source_job_response(job: KnowledgeSourceJobRecord) -> KnowledgeSourceJobResponse:
    result = job.result
    return KnowledgeSourceJobResponse(
        id=job.job_id,
        graph_id=job.graph_id,
        source_snapshot_id=job.source_snapshot_id,
        upload_id=job.upload_id,
        title=job.title,
        state=job.state.value,
        stage=job.stage.value,
        progress=job.progress,
        attempt_count=job.attempt_count,
        maximum_attempts=job.maximum_attempts,
        next_attempt_at=job.next_attempt_at,
        last_failure_code=job.last_failure_code,
        version=job.version,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
        result=(
            KnowledgeSourceJobResultResponse(
                changeset_id=result.changeset_id,
                page_count=result.page_count,
                proposed_node_count=result.proposed_node_count,
                proposed_edge_count=result.proposed_edge_count,
                evidence_hash=result.evidence_hash,
                embedding_model=result.embedding_model,
                extraction_model=result.extraction_model,
            )
            if result is not None
            else None
        ),
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
        published_by=release.published_by,
        published_at=release.published_at,
        publisher_name=release.publisher_name,
        publisher_email=release.publisher_email,
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
        evidence_excerpt=item.evidence_excerpt,
        evidence_sha256=item.evidence_sha256,
        source_page_sha256=item.source_page_sha256,
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


@router.post("/{graph_id}/archive", response_model=KnowledgeGraphResponse)
async def archive_graph(
    graph_id: UUID,
    payload: KnowledgeGraphArchiveRequest,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=16, max_length=200),
    ],
) -> KnowledgeGraphResponse | JSONResponse:
    service = _service(request, session)
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "contract": "KNOWLEDGE_GRAPH_ARCHIVE_V1",
            "graph_id": str(graph_id),
            "expected_version": expected_version,
            "reason": payload.reason,
        }
    )
    archived = await service.archive_graph(
        workspace_id=context.workspace_id,
        graph_id=graph_id,
        subject=context.subject,
        expected_version=expected_version,
        reason=payload.reason,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        environment=context.environment,
        request_id=context.request_id,
    )
    return _graph_response(archived)


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


@router.post(
    "/{graph_id}/releases",
    status_code=410,
    response_model=None,
    deprecated=True,
)
async def retired_direct_release_publication(
    graph_id: UUID,
    context: ContextDep,
) -> JSONResponse:
    del graph_id, context
    return JSONResponse(
        status_code=410,
        media_type="application/problem+json",
        headers={"Cache-Control": "no-store"},
        content={
            "type": "https://datariver.invalid/problems/direct-release-retired",
            "title": "Direct release publication is retired",
            "status": 410,
            "detail": (
                "Submit and independently approve a typed changeset, then publish that "
                "approved changeset."
            ),
        },
    )


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


@router.post(
    "/{graph_id}/sources/{upload_id}/analyze",
    status_code=202,
    response_model=KnowledgeSourceJobResponse,
)
async def analyze_knowledge_pdf_source(
    graph_id: UUID,
    upload_id: UUID,
    payload: KnowledgeSourceAnalyzeRequest,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> KnowledgeSourceJobResponse | JSONResponse:
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
    await service.authorize_source_analysis(
        workspace_id=context.workspace_id,
        graph=graph,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    settings = get_container(request).settings
    if not settings.knowledge_source_worker_enabled:
        raise ConflictError(
            "Knowledge source analysis is disabled until its separately credentialed "
            "worker is provisioned."
        )
    bindings = resolve_knowledge_runtime_bindings(settings)
    request_hash = canonical_json_hash(
        {
            "contract": "KNOWLEDGE_SOURCE_ANALYSIS_ENQUEUE_V1",
            "workspace_id": str(context.workspace_id),
            "actor_id": str(context.subject.subject_id),
            "graph_id": str(graph_id),
            "upload_id": str(upload_id),
            "title": payload.title,
        }
    )
    job = await SqlKnowledgeSourceJobStore(session).enqueue(
        workspace_id=context.workspace_id,
        graph_id=graph_id,
        upload_id=upload_id,
        actor_id=context.subject.subject_id,
        title=payload.title,
        request_hash=request_hash,
        requester_authorization_hash=knowledge_requester_authorization_hash(context.subject),
        embedding_binding=bindings.embedding,
        extraction_binding=bindings.extraction,
        maximum_attempts=settings.knowledge_source_job_maximum_attempts,
        idempotency_key=idempotency_key,
    )
    return _source_job_response(job)


@router.get(
    "/{graph_id}/source-analysis-jobs",
    response_model=KnowledgeSourceJobPageResponse,
)
async def list_knowledge_source_jobs(
    graph_id: UUID,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=2000)] = None,
) -> KnowledgeSourceJobPageResponse | JSONResponse:
    graph = await _service(request, session).get_graph(
        workspace_id=context.workspace_id,
        graph_id=graph_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if graph is None:
        return _not_found(request, context.request_id)
    page = await SqlKnowledgeSourceJobStore(session).list_owned(
        workspace_id=context.workspace_id,
        graph_id=graph_id,
        actor_id=context.subject.subject_id,
        limit=limit,
        cursor=cursor,
    )
    return KnowledgeSourceJobPageResponse(
        items=[_source_job_response(item) for item in page.items],
        next_cursor=page.next_cursor,
    )


@router.get(
    "/{graph_id}/source-analysis-jobs/{job_id}",
    response_model=KnowledgeSourceJobResponse,
)
async def get_knowledge_source_job(
    graph_id: UUID,
    job_id: UUID,
    request: Request,
    context: ContextDep,
    session: SessionDep,
) -> KnowledgeSourceJobResponse | JSONResponse:
    graph = await _service(request, session).get_graph(
        workspace_id=context.workspace_id,
        graph_id=graph_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    if graph is None:
        return _not_found(request, context.request_id)
    job = await SqlKnowledgeSourceJobStore(session).get_owned(
        workspace_id=context.workspace_id,
        graph_id=graph_id,
        job_id=job_id,
        actor_id=context.subject.subject_id,
    )
    if job is None:
        return _not_found(request, context.request_id)
    return _source_job_response(job)


@router.post(
    "/{graph_id}/source-analysis-jobs/{job_id}/cancel",
    response_model=KnowledgeSourceJobResponse,
)
async def cancel_knowledge_source_job(
    graph_id: UUID,
    job_id: UUID,
    payload: KnowledgeSourceJobCancelRequest,
    request: Request,
    context: ContextDep,
    session: SessionDep,
    if_match: Annotated[str, Header(alias="If-Match", max_length=100)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> KnowledgeSourceJobResponse | JSONResponse:
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
    await service.authorize_source_analysis(
        workspace_id=context.workspace_id,
        graph=graph,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    expected_version = _expected_version(if_match)
    request_hash = canonical_json_hash(
        {
            "contract": "KNOWLEDGE_SOURCE_ANALYSIS_CANCEL_V1",
            "workspace_id": str(context.workspace_id),
            "actor_id": str(context.subject.subject_id),
            "graph_id": str(graph_id),
            "job_id": str(job_id),
            "expected_version": expected_version,
            "reason": payload.reason,
        }
    )
    job = await SqlKnowledgeSourceJobStore(session).cancel(
        workspace_id=context.workspace_id,
        graph_id=graph_id,
        job_id=job_id,
        actor_id=context.subject.subject_id,
        expected_version=expected_version,
        reason=payload.reason,
        request_hash=request_hash,
        idempotency_key=idempotency_key,
    )
    return _source_job_response(job)


@router.post(
    "/{graph_id}/releases/{release_id}/project",
    status_code=201,
    response_model=KnowledgeProjectionResponse,
)
async def project_knowledge_release(
    graph_id: UUID,
    release_id: UUID,
    request: Request,
    context: ContextDep,
    session: SessionDep,
) -> KnowledgeProjectionResponse | JSONResponse:
    container = get_container(request)
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
    await service.authorize_projection(
        workspace_id=context.workspace_id,
        graph=graph,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
    )
    release_snapshot = await SqlKnowledgeStore(session).get_release_snapshot(
        workspace_id=context.workspace_id,
        graph_id=graph_id,
        release_id=release_id,
        clearance=int(Classification.RESTRICTED),
        maximum_nodes=5_000,
    )
    if release_snapshot is None:
        return _not_found(request, context.request_id)
    release, snapshot = release_snapshot
    if any(
        node.classification > int(graph.classification) for node in snapshot.nodes.values()
    ) or any(edge.classification > int(graph.classification) for edge in snapshot.edges.values()):
        raise ConflictError("The release classification exceeds its knowledge graph envelope.")
    if container.knowledge_neo4j is None:
        raise ConflictError("The activated Neo4j projection adapter is unavailable.")
    receipt = await VerifiedProjectionService(
        writer=Neo4jKnowledgeProjectionAdapter(executor=container.knowledge_neo4j)
    ).project_shadow_release(
        workspace_id=context.workspace_id,
        graph_id=graph_id,
        release_id=release_id,
        release_hash=release.content_hash,
        snapshot=snapshot,
    )
    await SqlKnowledgePipelineRepository(session).record_projection(receipt=receipt)
    return KnowledgeProjectionResponse(
        deployment_id=receipt.deployment_id,
        release_id=receipt.release_id,
        release_hash=receipt.release_hash,
        node_count=receipt.node_count,
        edge_count=receipt.edge_count,
        state="SHADOW_VERIFIED",
    )


@router.post(
    "/{graph_id}/releases/{release_id}/graphrag",
    response_model=KnowledgeGraphRagResponse,
)
async def query_knowledge_release(
    graph_id: UUID,
    release_id: UUID,
    payload: KnowledgeGraphRagRequest,
    request: Request,
    context: ContextDep,
    session: SessionDep,
) -> KnowledgeGraphRagResponse | JSONResponse:
    container = get_container(request)
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
    release_result = await service.get_release_for_graphrag(
        workspace_id=context.workspace_id,
        graph=graph,
        release_id=release_id,
        subject=context.subject,
        environment=context.environment,
        request_id=context.request_id,
        maximum_nodes=2_000,
    )
    if release_result is None:
        return _not_found(request, context.request_id)
    release, snapshot = release_result
    repository = SqlKnowledgePipelineRepository(session)
    await repository.require_verified_projection(
        workspace_id=context.workspace_id,
        graph_id=graph_id,
        release_id=release_id,
        release_hash=release.content_hash,
        node_count=release.node_count,
        edge_count=release.edge_count,
    )
    # External embedding and composition calls must never hold a request-scoped
    # PostgreSQL transaction or consume a pool connection while inference runs.
    await session.commit()
    if container.knowledge_neo4j is None:
        raise ConflictError("The activated Neo4j query adapter is unavailable.")
    runtime = _knowledge_adapters(request)
    selector = SqlSemanticSeedSelector(
        session_factory=container.database.session_factory,
        subject_id=context.subject.subject_id,
        embedding=runtime.embedding,
        binding=runtime.bindings.embedding,
    )
    answer = await KnowledgeGraphRagService(
        retriever=Neo4jScopedEvidenceRetriever(
            executor=container.knowledge_neo4j,
            semantic_selector=selector,
        ),
        composer=runtime.composer,
        audit_writer=repository,
    ).answer(
        request_id=context.request_id,
        workspace_id=context.workspace_id,
        graph_id=graph_id,
        release_id=release_id,
        actor_id=context.subject.subject_id,
        question=payload.question,
        start_node_id=payload.start_node_id,
        direction=payload.direction,
        edge_types=frozenset(payload.edge_types),
        maximum_classification=min(
            int(context.subject.clearance),
            int(Classification.INTERNAL),
        ),
        maximum_hops=payload.maximum_hops,
        maximum_nodes=payload.maximum_nodes,
        canonical_snapshot=snapshot,
        binding=runtime.bindings.graphrag,
    )
    cited_node_ids = {
        citation.entity_id for citation in answer.citations if citation.entity_kind == "NODE"
    }
    cited_edge_ids = {
        citation.entity_id for citation in answer.citations if citation.entity_kind == "EDGE"
    }
    edge_endpoint_ids = {
        entity_id
        for citation in answer.citations
        if citation.entity_kind == "EDGE"
        for entity_id in (citation.source_entity_id, citation.target_entity_id)
        if entity_id is not None
    }
    visible_node_ids = cited_node_ids | edge_endpoint_ids
    visible_nodes = {
        entity_id: node
        for entity_id, node in snapshot.nodes.items()
        if entity_id in visible_node_ids
    }
    visible_edges = {
        edge_id: edge
        for edge_id, edge in snapshot.edges.items()
        if (
            edge_id in cited_edge_ids
            or (edge.source_entity_id in cited_node_ids and edge.target_entity_id in cited_node_ids)
        )
        and edge.source_entity_id in visible_nodes
        and edge.target_entity_id in visible_nodes
    }
    visible_snapshot = GraphSnapshot(nodes=visible_nodes, edges=visible_edges)
    visible_release = _scoped_release(release, visible_snapshot)
    return KnowledgeGraphRagResponse(
        release=_release_response(visible_release),
        nodes=[_node_response(node) for node in visible_nodes.values()],
        edges=[_edge_response(edge) for edge in visible_edges.values()],
        truncated=len(visible_nodes) != len(snapshot.nodes),
        answer=answer.answer,
        citations=[
            KnowledgeGraphRagCitationResponse(
                evidence_id=value.evidence_id,
                source_locator=value.source_locator,
                source_version=value.source_version,
                page_number=value.page_number,
                entity_kind=value.entity_kind,
                entity_id=value.entity_id,
                source_entity_id=value.source_entity_id,
                target_entity_id=value.target_entity_id,
                edge_type=value.edge_type,
                evidence_excerpt=value.evidence_excerpt,
                evidence_sha256=value.evidence_sha256,
                source_page_sha256=value.source_page_sha256,
            )
            for value in answer.citations
        ],
        model_audit=KnowledgeModelAuditResponse(
            provider=answer.binding.provider,
            model=answer.binding.model,
            prompt_version=answer.binding.prompt_version,
            tool_schema_version=answer.binding.tool_schema_version,
            configuration_source=answer.binding.configuration_source,
            configuration_version=answer.binding.configuration_version,
            configuration_hash=answer.binding.configuration_hash,
        ),
    )
