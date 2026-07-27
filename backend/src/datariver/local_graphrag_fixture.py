from __future__ import annotations

import asyncio
import hashlib
import json
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.dto import KnowledgeReleaseRecord
from datariver.application.services.knowledge_pipeline import VerifiedProjectionService
from datariver.bootstrap import (
    LOCAL_DEMO_IDENTITIES,
    LOCAL_SUBJECT_ID,
    LOCAL_WORKSPACE_ID,
)
from datariver.config import get_settings
from datariver.domain.authz import Classification
from datariver.domain.common import canonical_json_hash
from datariver.domain.knowledge import (
    ChangeOperationType,
    ChangeSetState,
    GraphChangeOperation,
    GraphEntityKind,
    Provenance,
)
from datariver.infrastructure.db.knowledge import SqlKnowledgeStore
from datariver.infrastructure.db.knowledge_pipeline import SqlKnowledgePipelineRepository
from datariver.infrastructure.db.models.knowledge import GraphModel, ProjectionDeploymentModel
from datariver.infrastructure.db.models.platform import WorkspaceMembershipModel
from datariver.infrastructure.db.rls import set_security_context
from datariver.infrastructure.db.session import Database
from datariver.infrastructure.knowledge.neo4j import (
    BoltNeo4jQueryExecutor,
    Neo4jKnowledgeProjectionAdapter,
)
from datariver.infrastructure.secrets import SecretResolver

_GRAPH_SLUG = "test"
_CHANGESET_TITLE = "Local GraphRAG runtime fixture v1"
_SOURCE_REF = "urn:datariver:local-graphrag-fixture:v1"
_FIXTURE_NAMESPACE = "urn:datariver:local-graphrag-fixture:v1"
_CHECKER_SUBJECT_ID = next(
    identity.subject_id for identity in LOCAL_DEMO_IDENTITIES if identity.username == "sua.han"
)


def _stable_id(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"{_FIXTURE_NAMESPACE}:{name}")


def _provenance(*, locator: str, excerpt: str) -> Provenance:
    normalized_excerpt = " ".join(excerpt.split())
    source_page = (
        "Local synthetic GraphRAG fixture. "
        "Silicon wafers are processed by photolithography to manufacture semiconductor devices."
    )
    return Provenance(
        source_ref=_SOURCE_REF,
        source_locator=f"local-fixture://knowledge/test/{locator}#page=1",
        source_version=hashlib.sha256(source_page.encode()).hexdigest(),
        method="LOCAL_DEVELOPMENT_SYNTHETIC_FIXTURE_V1",
        confidence=1.0,
        evidence_excerpt=normalized_excerpt,
        evidence_sha256=hashlib.sha256(normalized_excerpt.encode()).hexdigest(),
        source_page_sha256=hashlib.sha256(source_page.encode()).hexdigest(),
    )


def fixture_operations() -> tuple[GraphChangeOperation, ...]:
    wafer_id = _stable_id("node:silicon-wafer")
    lithography_id = _stable_id("node:photolithography")
    device_id = _stable_id("node:semiconductor-device")
    return (
        GraphChangeOperation(
            sequence=1,
            operation=ChangeOperationType.UPSERT,
            entity_kind=GraphEntityKind.NODE,
            stable_entity_id=wafer_id,
            document={
                "entity_type": "d",
                "properties": {
                    "name": "Silicon Wafer",
                    "description": "A silicon substrate used as the starting material.",
                },
                "classification": int(Classification.INTERNAL),
            },
            provenance=(
                _provenance(
                    locator="silicon-wafer",
                    excerpt=(
                        "A silicon wafer is the starting substrate for semiconductor fabrication."
                    ),
                ),
            ),
            confidence=1.0,
        ),
        GraphChangeOperation(
            sequence=2,
            operation=ChangeOperationType.UPSERT,
            entity_kind=GraphEntityKind.NODE,
            stable_entity_id=lithography_id,
            document={
                "entity_type": "e",
                "properties": {
                    "name": "Photolithography",
                    "description": (
                        "A pattern-transfer process used during semiconductor fabrication."
                    ),
                },
                "classification": int(Classification.INTERNAL),
            },
            provenance=(
                _provenance(
                    locator="photolithography",
                    excerpt="Photolithography transfers circuit patterns onto a silicon wafer.",
                ),
            ),
            confidence=1.0,
        ),
        GraphChangeOperation(
            sequence=3,
            operation=ChangeOperationType.UPSERT,
            entity_kind=GraphEntityKind.NODE,
            stable_entity_id=device_id,
            document={
                "entity_type": "f",
                "properties": {
                    "name": "Semiconductor Device",
                    "description": "A device manufactured through patterned wafer processing.",
                },
                "classification": int(Classification.INTERNAL),
            },
            provenance=(
                _provenance(
                    locator="semiconductor-device",
                    excerpt="Patterned wafer processing produces semiconductor devices.",
                ),
            ),
            confidence=1.0,
        ),
        GraphChangeOperation(
            sequence=4,
            operation=ChangeOperationType.UPSERT,
            entity_kind=GraphEntityKind.EDGE,
            stable_entity_id=_stable_id("edge:wafer-to-lithography"),
            document={
                "source_id": str(wafer_id),
                "target_id": str(lithography_id),
                "edge_type": "a",
                "properties": {
                    "name": "INPUT_TO",
                    "description": "The silicon wafer is an input to photolithography.",
                },
                "classification": int(Classification.INTERNAL),
            },
            provenance=(
                _provenance(
                    locator="wafer-to-lithography",
                    excerpt="The silicon wafer is processed during photolithography.",
                ),
            ),
            confidence=1.0,
        ),
        GraphChangeOperation(
            sequence=5,
            operation=ChangeOperationType.UPSERT,
            entity_kind=GraphEntityKind.EDGE,
            stable_entity_id=_stable_id("edge:lithography-to-device"),
            document={
                "source_id": str(lithography_id),
                "target_id": str(device_id),
                "edge_type": "b",
                "properties": {
                    "name": "CONTRIBUTES_TO",
                    "description": (
                        "Photolithography contributes to semiconductor device fabrication."
                    ),
                },
                "classification": int(Classification.INTERNAL),
            },
            provenance=(
                _provenance(
                    locator="lithography-to-device",
                    excerpt="Photolithography contributes to manufacturing a semiconductor device.",
                ),
            ),
            confidence=1.0,
        ),
    )


def _operation_matches(
    *,
    actual: object,
    expected: GraphChangeOperation,
) -> bool:
    return (
        getattr(actual, "sequence", None) == expected.sequence
        and getattr(actual, "operation", None) == expected.operation.value
        and getattr(actual, "entity_kind", None) == expected.entity_kind.value
        and getattr(actual, "stable_entity_id", None) == expected.stable_entity_id
        and getattr(actual, "document", None) == expected.document
        and getattr(actual, "provenance", None)
        == tuple(item.to_document() for item in expected.provenance)
        and getattr(actual, "confidence", None) == expected.confidence
    )


async def _set_actor(session: AsyncSession, *, subject_id: UUID) -> None:
    await set_security_context(
        session,
        workspace_id=LOCAL_WORKSPACE_ID,
        subject_id=subject_id,
    )


async def _run() -> dict[str, object]:
    settings = get_settings()
    if settings.app_env != "development":
        raise RuntimeError("The local GraphRAG fixture is development-only.")
    if not settings.neo4j_projection_enabled:
        raise RuntimeError("The local GraphRAG fixture requires Neo4j projection.")
    if settings.neo4j_uri is None or settings.neo4j_auth_secret_ref is None:
        raise RuntimeError("The local GraphRAG fixture has incomplete Neo4j settings.")
    resolver = SecretResolver(virtual_secret_root=settings.system_configuration_secret_root)
    database = Database(
        settings.database_url,
        password=resolver.resolve(settings.database_secret_ref),
        pool_size=1,
        max_overflow=0,
        application_name="datariver-local-graphrag-fixture",
    )
    credential = resolver.resolve(settings.neo4j_auth_secret_ref).strip()
    username, separator, password = credential.partition("/")
    if not separator or not username or not password:
        await database.close()
        raise RuntimeError("The Neo4j credential must use the username/password format.")
    neo4j = BoltNeo4jQueryExecutor(
        uri=settings.neo4j_uri,
        username=username,
        password=password,
        database=settings.neo4j_database,
        connection_timeout_seconds=settings.neo4j_connection_timeout_seconds,
        maximum_connection_pool_size=1,
    )
    try:
        async with database.session_factory() as session:
            await _set_actor(session, subject_id=LOCAL_SUBJECT_ID)
            memberships = list(
                (
                    await session.scalars(
                        select(WorkspaceMembershipModel).where(
                            WorkspaceMembershipModel.workspace_id == LOCAL_WORKSPACE_ID,
                            WorkspaceMembershipModel.subject_id.in_(
                                (LOCAL_SUBJECT_ID, _CHECKER_SUBJECT_ID)
                            ),
                            WorkspaceMembershipModel.active.is_(True),
                        )
                    )
                ).all()
            )
            if {membership.subject_id for membership in memberships} != {
                LOCAL_SUBJECT_ID,
                _CHECKER_SUBJECT_ID,
            }:
                raise RuntimeError("The local GraphRAG fixture requires two active human actors.")
            graph_model = (
                await session.scalars(
                    select(GraphModel).where(
                        GraphModel.workspace_id == LOCAL_WORKSPACE_ID,
                        GraphModel.slug == _GRAPH_SLUG,
                    )
                )
            ).one_or_none()
            if graph_model is None:
                raise RuntimeError("The local GraphRAG fixture graph does not exist.")
            if graph_model.classification != int(Classification.INTERNAL):
                raise RuntimeError("The local GraphRAG fixture graph must remain INTERNAL.")
            store = SqlKnowledgeStore(session)
            graph = await store.get_graph(
                workspace_id=LOCAL_WORKSPACE_ID,
                graph_id=graph_model.id,
                clearance=int(Classification.RESTRICTED),
            )
            if graph is None:
                raise RuntimeError("The local GraphRAG fixture graph is unavailable.")
            if graph.active_release_id is not None:
                verified_count = int(
                    (
                        await session.scalar(
                            select(ProjectionDeploymentModel)
                            .where(
                                ProjectionDeploymentModel.workspace_id == LOCAL_WORKSPACE_ID,
                                ProjectionDeploymentModel.graph_id == graph.graph_id,
                                ProjectionDeploymentModel.release_id == graph.active_release_id,
                                ProjectionDeploymentModel.state == "SHADOW_VERIFIED",
                            )
                            .limit(1)
                        )
                    )
                    is not None
                )
                if verified_count:
                    active_release_snapshot = await store.get_release_snapshot(
                        workspace_id=LOCAL_WORKSPACE_ID,
                        graph_id=graph.graph_id,
                        release_id=graph.active_release_id,
                        clearance=int(Classification.RESTRICTED),
                        maximum_nodes=100,
                    )
                    if active_release_snapshot is None:
                        raise RuntimeError("The active local GraphRAG release is unavailable.")
                    return {
                        "workspace_id": str(LOCAL_WORKSPACE_ID),
                        "graph_id": str(graph.graph_id),
                        "release_id": str(graph.active_release_id),
                        "graph_status": graph.status,
                        "node_count": len(active_release_snapshot[1].nodes),
                        "edge_count": len(active_release_snapshot[1].edges),
                        "projection_state": "SHADOW_VERIFIED",
                        "already_completed": True,
                    }

            await _set_actor(session, subject_id=LOCAL_SUBJECT_ID)
            changeset = await store.create_changeset(
                workspace_id=LOCAL_WORKSPACE_ID,
                graph_id=graph.graph_id,
                title=_CHANGESET_TITLE,
                author_id=LOCAL_SUBJECT_ID,
                idempotency_key="local-graphrag-fixture-changeset-v1",
                request_hash=canonical_json_hash(
                    {
                        "graph_id": str(graph.graph_id),
                        "title": _CHANGESET_TITLE,
                        "operations": [
                            {
                                "sequence": operation.sequence,
                                "operation": operation.operation.value,
                                "entity_kind": operation.entity_kind.value,
                                "stable_entity_id": str(operation.stable_entity_id),
                                "document": operation.document,
                                "provenance": [item.to_document() for item in operation.provenance],
                                "confidence": operation.confidence,
                            }
                            for operation in fixture_operations()
                        ],
                    }
                ),
            )
            expected_operations = fixture_operations()
            actual_by_sequence = {item.sequence: item for item in changeset.operations}
            for operation in expected_operations:
                actual = actual_by_sequence.get(operation.sequence)
                if actual is not None:
                    if not _operation_matches(actual=actual, expected=operation):
                        raise RuntimeError(
                            "The local GraphRAG fixture changeset has conflicting operations."
                        )
                    continue
                if changeset.state != ChangeSetState.DRAFT.value:
                    raise RuntimeError("The local GraphRAG fixture changeset is incomplete.")
                await _set_actor(session, subject_id=LOCAL_SUBJECT_ID)
                changeset = await store.append_change_operation(
                    workspace_id=LOCAL_WORKSPACE_ID,
                    graph_id=graph.graph_id,
                    changeset_id=changeset.changeset_id,
                    actor_id=LOCAL_SUBJECT_ID,
                    expected_version=changeset.version,
                    operation=operation,
                )
            if changeset.state == ChangeSetState.DRAFT.value:
                await _set_actor(session, subject_id=LOCAL_SUBJECT_ID)
                changeset = await store.submit_changeset(
                    workspace_id=LOCAL_WORKSPACE_ID,
                    graph_id=graph.graph_id,
                    changeset_id=changeset.changeset_id,
                    actor_id=LOCAL_SUBJECT_ID,
                    expected_version=changeset.version,
                )
            if changeset.state == ChangeSetState.REVIEW.value:
                await _set_actor(session, subject_id=_CHECKER_SUBJECT_ID)
                changeset = await store.review_changeset(
                    workspace_id=LOCAL_WORKSPACE_ID,
                    graph_id=graph.graph_id,
                    changeset_id=changeset.changeset_id,
                    actor_id=_CHECKER_SUBJECT_ID,
                    decision=ChangeSetState.APPROVED,
                    reason="Approve the bounded local synthetic GraphRAG runtime fixture.",
                    expected_version=changeset.version,
                )
            published_release: KnowledgeReleaseRecord
            if changeset.state == ChangeSetState.APPROVED.value:
                await _set_actor(session, subject_id=LOCAL_SUBJECT_ID)
                changeset, published_release = await store.publish_approved_changeset(
                    workspace_id=LOCAL_WORKSPACE_ID,
                    graph_id=graph.graph_id,
                    changeset_id=changeset.changeset_id,
                    published_by=LOCAL_SUBJECT_ID,
                    idempotency_key="local-graphrag-fixture-publication-v1",
                    request_hash=canonical_json_hash(
                        {
                            "changeset_id": str(changeset.changeset_id),
                            "contract": "LOCAL_GRAPHRAG_FIXTURE_PUBLICATION_V1",
                        }
                    ),
                )
            elif changeset.state == ChangeSetState.PUBLISHED.value:
                if changeset.published_release_id is None:
                    raise RuntimeError("The local GraphRAG fixture publication is incomplete.")
                release_snapshot = await store.get_release_snapshot(
                    workspace_id=LOCAL_WORKSPACE_ID,
                    graph_id=graph.graph_id,
                    release_id=changeset.published_release_id,
                    clearance=int(Classification.RESTRICTED),
                    maximum_nodes=100,
                )
                if release_snapshot is None:
                    raise RuntimeError("The local GraphRAG fixture release is unavailable.")
                published_release = release_snapshot[0]
            else:
                raise RuntimeError("The local GraphRAG fixture changeset cannot be published.")

            await _set_actor(session, subject_id=LOCAL_SUBJECT_ID)
            release_snapshot = await store.get_release_snapshot(
                workspace_id=LOCAL_WORKSPACE_ID,
                graph_id=graph.graph_id,
                release_id=published_release.release_id,
                clearance=int(Classification.RESTRICTED),
                maximum_nodes=100,
            )
            if release_snapshot is None:
                raise RuntimeError("The local GraphRAG fixture release is unavailable.")
            _, snapshot = release_snapshot
            receipt = await VerifiedProjectionService(
                writer=Neo4jKnowledgeProjectionAdapter(executor=neo4j)
            ).project_shadow_release(
                workspace_id=LOCAL_WORKSPACE_ID,
                graph_id=graph.graph_id,
                release_id=published_release.release_id,
                release_hash=published_release.content_hash,
                snapshot=snapshot,
            )
            await _set_actor(session, subject_id=LOCAL_SUBJECT_ID)
            await SqlKnowledgePipelineRepository(session).record_projection(receipt=receipt)
            await _set_actor(session, subject_id=LOCAL_SUBJECT_ID)
            graph = await store.get_graph(
                workspace_id=LOCAL_WORKSPACE_ID,
                graph_id=graph.graph_id,
                clearance=int(Classification.RESTRICTED),
            )
            if graph is None:
                raise RuntimeError("The local GraphRAG fixture graph is unavailable.")
            if graph.active_release_id != published_release.release_id:
                graph = await store.activate_release(
                    workspace_id=LOCAL_WORKSPACE_ID,
                    graph_id=graph.graph_id,
                    release_id=published_release.release_id,
                    expected_graph_version=graph.version,
                )
            return {
                "workspace_id": str(LOCAL_WORKSPACE_ID),
                "graph_id": str(graph.graph_id),
                "release_id": str(published_release.release_id),
                "graph_status": graph.status,
                "node_count": len(snapshot.nodes),
                "edge_count": len(snapshot.edges),
                "projection_state": "SHADOW_VERIFIED",
                "already_completed": False,
            }
    finally:
        await neo4j.close()
        await database.close()


def main() -> None:
    print(json.dumps(asyncio.run(_run()), sort_keys=True))


if __name__ == "__main__":
    main()
