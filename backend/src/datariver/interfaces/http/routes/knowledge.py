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
from datariver.application.services.knowledge_pipeline import (
    KnowledgeGraphRagService,
    KnowledgeSourcePipeline,
    VerifiedProjectionService,
)
from datariver.domain.authz import Action, Classification
from datariver.domain.common import ConflictError, ValidationError
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
from datariver.domain.knowledge_pipeline import ModelBinding
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.knowledge import SqlKnowledgeStore
from datariver.infrastructure.db.knowledge_pipeline import (
    SqlKnowledgePipelineRepository,
    SqlSemanticSeedSelector,
)
from datariver.infrastructure.knowledge.neo4j import (
    Neo4jKnowledgeProjectionAdapter,
    Neo4jScopedEvidenceRetriever,
)
from datariver.infrastructure.knowledge.object_store import ObjectStoreKnowledgeSourceReader
from datariver.infrastructure.knowledge.openai_compatible import (
    HttpxOpenAIJsonTransport,
    OpenAICompatibleEmbeddingProvider,
    OpenAICompatibleKnowledgeAnswerComposer,
    OpenAICompatibleTypedKnowledgeExtractor,
)
from datariver.infrastructure.knowledge.pdf import PypdfPageAwareParser
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
    KnowledgeGraphRagCitationResponse,
    KnowledgeGraphRagRequest,
    KnowledgeGraphRagResponse,
    KnowledgeGraphResponse,
    KnowledgeModelAuditResponse,
    KnowledgeProjectionResponse,
    KnowledgeReleasePublish,
    KnowledgeReleaseResponse,
    KnowledgeSnapshotResponse,
    KnowledgeSourceAnalyzeRequest,
    KnowledgeSourceAnalyzeResponse,
    KnowledgeValidationResponse,
    NeighborAnalysisRequest,
    NeighborAnalysisResponse,
    ProvenanceRequest,
)

router = APIRouter(prefix="/knowledge/graphs", tags=["knowledge"])

_KNOWLEDGE_PROVIDER = "ollama-openai-compatible"
_EXTRACTION_PROMPT_VERSION = "knowledge-pdf-extraction-v1"
_EXTRACTION_SCHEMA_VERSION = "knowledge-extraction-schema-v1"
_GRAPHRAG_PROMPT_VERSION = "knowledge-graphrag-v1"
_GRAPHRAG_SCHEMA_VERSION = "knowledge-graphrag-schema-v1"
_EMBEDDING_ADAPTER_CONTRACT = "openai-compatible-embeddings-v1"
_CHAT_JSON_SCHEMA_ADAPTER_CONTRACT = "openai-compatible-chat-json-schema-v1"


def _activated_model_binding(
    *,
    settings: object,
    system_id: str,
    model: str,
    prompt_version: str,
    tool_schema_version: str,
    adapter_contract: str,
) -> ModelBinding:
    versions = getattr(settings, "system_configuration_runtime_versions", {})
    hashes = getattr(settings, "system_configuration_runtime_hashes", {})
    version = versions.get(system_id)
    configuration_hash = hashes.get(system_id)
    if version is not None and configuration_hash is None:
        raise ConflictError(
            "The activated model configuration is missing its immutable revision hash."
        )
    return ModelBinding.activated(
        provider=_KNOWLEDGE_PROVIDER,
        model=model,
        prompt_version=prompt_version,
        tool_schema_version=tool_schema_version,
        configuration_version=version,
        configuration_hash=configuration_hash,
        adapter_contract=adapter_contract,
    )


def _knowledge_adapters(
    request: Request,
) -> tuple[
    OpenAICompatibleEmbeddingProvider,
    OpenAICompatibleTypedKnowledgeExtractor,
    OpenAICompatibleKnowledgeAnswerComposer,
    ModelBinding,
    ModelBinding,
    ModelBinding,
]:
    settings = get_container(request).settings
    if not settings.knowledge_pipeline_enabled:
        raise ConflictError(
            "The Knowledge pipeline requires activated Chat, embedding, and Neo4j settings."
        )
    if (
        settings.local_ollama_chat_base_url is None
        or settings.local_ollama_chat_model is None
        or settings.local_ollama_embedding_base_url is None
        or settings.local_ollama_embedding_model is None
    ):
        raise ConflictError("The activated Knowledge model bindings are incomplete.")
    embedding_transport = HttpxOpenAIJsonTransport(
        base_url=str(settings.local_ollama_embedding_base_url),
        allowed_hosts=frozenset({"host.docker.internal"}),
        api_key=None,
        timeout_seconds=settings.local_ollama_embedding_timeout_seconds,
    )
    chat_transport = HttpxOpenAIJsonTransport(
        base_url=str(settings.local_ollama_chat_base_url),
        allowed_hosts=frozenset({"host.docker.internal"}),
        api_key=None,
        timeout_seconds=settings.local_ollama_chat_timeout_seconds,
    )
    embedding_binding = _activated_model_binding(
        settings=settings,
        system_id="LLM_EMBEDDING",
        model=settings.local_ollama_embedding_model,
        prompt_version="embedding-v1",
        tool_schema_version="openai-embeddings-v1",
        adapter_contract=_EMBEDDING_ADAPTER_CONTRACT,
    )
    extraction_binding = _activated_model_binding(
        settings=settings,
        system_id="LLM_CHAT_MODEL",
        model=settings.local_ollama_chat_model,
        prompt_version=_EXTRACTION_PROMPT_VERSION,
        tool_schema_version=_EXTRACTION_SCHEMA_VERSION,
        adapter_contract=_CHAT_JSON_SCHEMA_ADAPTER_CONTRACT,
    )
    graphrag_binding = _activated_model_binding(
        settings=settings,
        system_id="LLM_CHAT_MODEL",
        model=settings.local_ollama_chat_model,
        prompt_version=_GRAPHRAG_PROMPT_VERSION,
        tool_schema_version=_GRAPHRAG_SCHEMA_VERSION,
        adapter_contract=_CHAT_JSON_SCHEMA_ADAPTER_CONTRACT,
    )
    return (
        OpenAICompatibleEmbeddingProvider(transport=embedding_transport),
        OpenAICompatibleTypedKnowledgeExtractor(transport=chat_transport),
        OpenAICompatibleKnowledgeAnswerComposer(transport=chat_transport),
        embedding_binding,
        extraction_binding,
        graphrag_binding,
    )


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


@router.post(
    "/{graph_id}/sources/{upload_id}/analyze",
    status_code=201,
    response_model=KnowledgeSourceAnalyzeResponse,
)
async def analyze_knowledge_pdf_source(
    graph_id: UUID,
    upload_id: UUID,
    payload: KnowledgeSourceAnalyzeRequest,
    request: Request,
    context: ContextDep,
    session: SessionDep,
) -> KnowledgeSourceAnalyzeResponse | JSONResponse:
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
    embedding, extractor, _, embedding_binding, extraction_binding, _ = _knowledge_adapters(request)
    repository = SqlKnowledgePipelineRepository(session)
    source, entity_types, edge_types = await repository.prepare_source(
        workspace_id=context.workspace_id,
        graph_id=graph_id,
        upload_id=upload_id,
        actor_id=context.subject.subject_id,
    )
    pipeline = KnowledgeSourcePipeline(
        reader=ObjectStoreKnowledgeSourceReader(object_store=get_container(request).object_store),
        parser=PypdfPageAwareParser(),
        embedding=embedding,
        extractor=extractor,
    )
    analysis = await pipeline.analyze_pdf(
        source=source,
        entity_types=entity_types,
        edge_types=edge_types,
        embedding_binding=embedding_binding,
        extraction_binding=extraction_binding,
    )
    changeset_id = await repository.persist_analysis_as_draft(
        analysis=analysis,
        title=payload.title,
        actor_id=context.subject.subject_id,
    )
    return KnowledgeSourceAnalyzeResponse(
        source_snapshot_id=source.snapshot_id,
        changeset_id=changeset_id,
        page_count=len(analysis.pages),
        proposed_node_count=len(analysis.extraction.nodes),
        proposed_edge_count=len(analysis.extraction.edges),
        evidence_hash=analysis.evidence_hash(),
        embedding_model=embedding_binding.model,
        extraction_model=extraction_binding.model,
    )


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
    if not container.settings.knowledge_pipeline_enabled or container.knowledge_neo4j is None:
        raise ConflictError("The activated Neo4j projection adapter is unavailable.")
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
    if container.knowledge_neo4j is None:
        raise ConflictError("The activated Neo4j query adapter is unavailable.")
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
    )
    embedding, _, composer, embedding_binding, _, graphrag_binding = _knowledge_adapters(request)
    selector = SqlSemanticSeedSelector(
        session=session,
        embedding=embedding,
        binding=embedding_binding,
    )
    answer = await KnowledgeGraphRagService(
        retriever=Neo4jScopedEvidenceRetriever(
            executor=container.knowledge_neo4j,
            semantic_selector=selector,
        ),
        composer=composer,
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
        maximum_classification=int(context.subject.clearance),
        maximum_hops=payload.maximum_hops,
        maximum_nodes=payload.maximum_nodes,
        binding=graphrag_binding,
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
