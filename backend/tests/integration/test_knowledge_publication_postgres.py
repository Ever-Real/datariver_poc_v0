from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from datariver.domain.common import ConflictError, ValidationError
from datariver.domain.knowledge import (
    ChangeOperationType,
    ChangeSetState,
    GraphChangeOperation,
    GraphEntityKind,
    Provenance,
)
from datariver.domain.knowledge_pipeline import ProjectionReceipt
from datariver.infrastructure.db.governance import SqlIdempotencyStore
from datariver.infrastructure.db.knowledge import SqlKnowledgeStore
from datariver.infrastructure.db.knowledge_evidence import SqlKnowledgeEvidenceReader
from datariver.infrastructure.db.knowledge_pipeline import SqlKnowledgePipelineRepository
from datariver.infrastructure.db.revision import REQUIRED_DATABASE_REVISION
from datariver.infrastructure.db.sharing import SqlSharingStore
from datariver.infrastructure.secrets import SecretResolver

_DATABASE_URL_ENV = "DATARIVER_KNOWLEDGE_TEST_DATABASE_URL"
_SECRET_REF_ENV = "DATARIVER_KNOWLEDGE_TEST_DATABASE_SECRET_REF"
_CONFIRM_ISOLATED_ENV = "DATARIVER_KNOWLEDGE_TEST_CONFIRM_ISOLATED"
_POSTGRES_ENABLED = bool(os.getenv(_DATABASE_URL_ENV)) and os.getenv(_CONFIRM_ISOLATED_ENV) == "1"


def _engine() -> AsyncEngine:
    return create_async_engine(
        os.environ[_DATABASE_URL_ENV],
        connect_args={
            "password": SecretResolver().resolve(os.environ[_SECRET_REF_ENV]),
            "server_settings": {
                "application_name": f"datariver-knowledge-publication-{uuid4().hex}"
            },
        },
    )


async def _workspace(engine: AsyncEngine) -> UUID:
    workspace_id = uuid4()
    async with engine.begin() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert revision == REQUIRED_DATABASE_REVISION
        await connection.execute(
            text(
                """
                INSERT INTO platform.workspaces
                    (id, slug, name, status, settings, version)
                VALUES
                    (:workspace_id, :slug, 'Knowledge publication test',
                     'ACTIVE', '{}'::jsonb, 1)
                """
            ),
            {
                "workspace_id": workspace_id,
                "slug": f"knowledge-publication-{workspace_id.hex}",
            },
        )
    return workspace_id


def _operation(*, classification: int = 1) -> GraphChangeOperation:
    return GraphChangeOperation(
        sequence=1,
        operation=ChangeOperationType.UPSERT,
        entity_kind=GraphEntityKind.NODE,
        stable_entity_id=uuid4(),
        document={
            "entity_type": "Dataset",
            "properties": {"name": "governed_asset"},
            "classification": classification,
        },
        provenance=(
            Provenance(
                source_ref="test:knowledge-publication",
                source_locator="fixture://knowledge-publication",
                source_version="v1",
                method="deterministic_test",
                confidence=1.0,
            ),
        ),
        confidence=1.0,
    )


async def _approved_changeset(
    engine: AsyncEngine,
    *,
    workspace_id: UUID,
    classification: int = 1,
) -> tuple[UUID, UUID, UUID]:
    author_id = uuid4()
    reviewer_id = uuid4()
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        store = SqlKnowledgeStore(session)
        graph = await store.create_graph(
            workspace_id=workspace_id,
            actor_id=author_id,
            slug=f"graph-{uuid4().hex}",
            name="Atomic publication",
            graph_type="DOMAIN",
            classification=1,
            entity_types=frozenset({"Dataset"}),
            edge_types=frozenset(),
            idempotency_key=f"graph-create-{uuid4().hex}",
            request_hash="a" * 64,
        )
        changeset = await store.create_changeset(
            workspace_id=workspace_id,
            graph_id=graph.graph_id,
            title="Approved changeset",
            author_id=author_id,
            idempotency_key=f"changeset-create-{uuid4().hex}",
            request_hash="b" * 64,
        )
        changeset = await store.append_change_operation(
            workspace_id=workspace_id,
            graph_id=graph.graph_id,
            changeset_id=changeset.changeset_id,
            actor_id=author_id,
            expected_version=changeset.version,
            operation=_operation(classification=classification),
        )
        changeset = await store.submit_changeset(
            workspace_id=workspace_id,
            graph_id=graph.graph_id,
            changeset_id=changeset.changeset_id,
            actor_id=author_id,
            expected_version=changeset.version,
        )
        changeset = await store.review_changeset(
            workspace_id=workspace_id,
            graph_id=graph.graph_id,
            changeset_id=changeset.changeset_id,
            actor_id=reviewer_id,
            decision=ChangeSetState.APPROVED,
            reason="independent approval",
            expected_version=changeset.version,
        )
    return graph.graph_id, changeset.changeset_id, reviewer_id


@pytest.mark.skipif(not _POSTGRES_ENABLED, reason="isolated PostgreSQL evidence is not configured")
@pytest.mark.asyncio
async def test_changeset_publication_is_atomic_inactive_and_idempotent_until_activation() -> None:
    engine = _engine()
    workspace_id = await _workspace(engine)
    graph_id, changeset_id, publisher_id = await _approved_changeset(
        engine,
        workspace_id=workspace_id,
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            store = SqlKnowledgeStore(session)
            changeset, release = await store.publish_approved_changeset(
                workspace_id=workspace_id,
                graph_id=graph_id,
                changeset_id=changeset_id,
                published_by=publisher_id,
                idempotency_key="knowledge-publication-idempotency",
                request_hash="c" * 64,
            )
            replay_changeset, replay_release = await store.publish_approved_changeset(
                workspace_id=workspace_id,
                graph_id=graph_id,
                changeset_id=changeset_id,
                published_by=publisher_id,
                idempotency_key="knowledge-publication-idempotency",
                request_hash="c" * 64,
            )

        assert changeset.state == "PUBLISHED"
        assert changeset.published_release_id == release.release_id
        assert replay_changeset.changeset_id == changeset.changeset_id
        assert replay_release.release_id == release.release_id
        async with engine.connect() as connection:
            graph_row = (
                await connection.execute(
                    text(
                        """
                        SELECT active_release_id, status, version
                        FROM knowledge.graphs
                        WHERE workspace_id = :workspace_id AND id = :graph_id
                        """
                    ),
                    {"workspace_id": workspace_id, "graph_id": graph_id},
                )
            ).one()
            projection_state = await connection.scalar(
                text(
                    """
                    SELECT state
                    FROM knowledge.projection_deployments
                    WHERE workspace_id = :workspace_id AND release_id = :release_id
                    """
                ),
                {"workspace_id": workspace_id, "release_id": release.release_id},
            )
        assert tuple(graph_row) == (None, "DRAFT", 1)
        assert projection_state == "CANONICAL_VERIFIED"

        async with sessions() as session:
            activated = await SqlKnowledgeStore(session).activate_release(
                workspace_id=workspace_id,
                graph_id=graph_id,
                release_id=release.release_id,
                expected_graph_version=1,
            )
        assert activated.active_release_id == release.release_id
        assert activated.status == "PUBLISHED"
        assert activated.version == 2
    finally:
        await engine.dispose()


@pytest.mark.skipif(not _POSTGRES_ENABLED, reason="isolated PostgreSQL evidence is not configured")
@pytest.mark.asyncio
async def test_publication_fault_before_commit_leaves_no_partial_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    workspace_id = await _workspace(engine)
    graph_id, changeset_id, publisher_id = await _approved_changeset(
        engine,
        workspace_id=workspace_id,
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def fail_save_result(self: SqlIdempotencyStore, **kwargs: object) -> None:
        del self, kwargs
        raise RuntimeError("injected-before-commit")

    monkeypatch.setattr(SqlIdempotencyStore, "save_result", fail_save_result)
    try:
        async with sessions() as session:
            with pytest.raises(RuntimeError, match="injected-before-commit"):
                await SqlKnowledgeStore(session).publish_approved_changeset(
                    workspace_id=workspace_id,
                    graph_id=graph_id,
                    changeset_id=changeset_id,
                    published_by=publisher_id,
                    idempotency_key="knowledge-publication-fault",
                    request_hash="d" * 64,
                )
            await session.rollback()

        async with engine.connect() as connection:
            release_count = await connection.scalar(
                text(
                    """
                    SELECT count(*) FROM knowledge.releases
                    WHERE workspace_id = :workspace_id AND graph_id = :graph_id
                    """
                ),
                {"workspace_id": workspace_id, "graph_id": graph_id},
            )
            changeset_state = await connection.scalar(
                text(
                    """
                    SELECT state FROM knowledge.changesets
                    WHERE workspace_id = :workspace_id AND id = :changeset_id
                    """
                ),
                {"workspace_id": workspace_id, "changeset_id": changeset_id},
            )
            projection_count = await connection.scalar(
                text(
                    """
                    SELECT count(*) FROM knowledge.projection_deployments
                    WHERE workspace_id = :workspace_id AND graph_id = :graph_id
                    """
                ),
                {"workspace_id": workspace_id, "graph_id": graph_id},
            )
            node_count = await connection.scalar(
                text(
                    """
                    SELECT count(*) FROM knowledge.release_nodes
                    WHERE workspace_id = :workspace_id
                    """
                ),
                {"workspace_id": workspace_id},
            )
            edge_count = await connection.scalar(
                text(
                    """
                    SELECT count(*) FROM knowledge.release_edges
                    WHERE workspace_id = :workspace_id
                    """
                ),
                {"workspace_id": workspace_id},
            )
            outbox_count = await connection.scalar(
                text(
                    """
                    SELECT count(*) FROM integration.outbox_events
                    WHERE workspace_id = :workspace_id
                      AND event_type = 'knowledge.release.published.v2'
                    """
                ),
                {"workspace_id": workspace_id},
            )
            idempotency_count = await connection.scalar(
                text(
                    """
                    SELECT count(*) FROM integration.idempotency_keys
                    WHERE workspace_id = :workspace_id
                      AND operation = :operation
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "operation": f"knowledge.changeset.publish:{changeset_id}",
                },
            )
        assert release_count == 0
        assert changeset_state == "APPROVED"
        assert projection_count == 0
        assert node_count == 0
        assert edge_count == 0
        assert outbox_count == 0
        assert idempotency_count == 0
    finally:
        await engine.dispose()


@pytest.mark.skipif(not _POSTGRES_ENABLED, reason="isolated PostgreSQL evidence is not configured")
@pytest.mark.asyncio
async def test_concurrent_same_key_publication_returns_one_release() -> None:
    engine = _engine()
    workspace_id = await _workspace(engine)
    graph_id, changeset_id, publisher_id = await _approved_changeset(
        engine,
        workspace_id=workspace_id,
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def publish() -> UUID:
        async with sessions() as session:
            _, release = await SqlKnowledgeStore(session).publish_approved_changeset(
                workspace_id=workspace_id,
                graph_id=graph_id,
                changeset_id=changeset_id,
                published_by=publisher_id,
                idempotency_key="knowledge-publication-concurrent",
                request_hash="e" * 64,
            )
            return release.release_id

    try:
        release_ids = await asyncio.gather(publish(), publish())
        assert release_ids[0] == release_ids[1]
        async with engine.connect() as connection:
            release_count = await connection.scalar(
                text(
                    """
                    SELECT count(*) FROM knowledge.releases
                    WHERE workspace_id = :workspace_id AND graph_id = :graph_id
                    """
                ),
                {"workspace_id": workspace_id, "graph_id": graph_id},
            )
        assert release_count == 1
    finally:
        await engine.dispose()


@pytest.mark.skipif(not _POSTGRES_ENABLED, reason="isolated PostgreSQL evidence is not configured")
@pytest.mark.asyncio
async def test_classification_envelope_is_fail_closed_before_publication() -> None:
    engine = _engine()
    workspace_id = await _workspace(engine)
    author_id = uuid4()
    reviewer_id = uuid4()
    graph_idempotency_key = f"graph-create-{uuid4().hex}"
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            store = SqlKnowledgeStore(session)
            graph = await store.create_graph(
                workspace_id=workspace_id,
                actor_id=author_id,
                slug=f"graph-{uuid4().hex}",
                name="Public envelope",
                graph_type="DOMAIN",
                classification=0,
                entity_types=frozenset({"Dataset"}),
                edge_types=frozenset(),
                idempotency_key=graph_idempotency_key,
                request_hash="f" * 64,
            )
            with pytest.raises(ConflictError, match="bound to another actor"):
                await store.create_graph(
                    workspace_id=workspace_id,
                    actor_id=reviewer_id,
                    slug=graph.slug,
                    name=graph.name,
                    graph_type=graph.graph_type,
                    classification=0,
                    entity_types=frozenset({"Dataset"}),
                    edge_types=frozenset(),
                    idempotency_key=graph_idempotency_key,
                    request_hash="f" * 64,
                )
            changeset = await store.create_changeset(
                workspace_id=workspace_id,
                graph_id=graph.graph_id,
                title="Legacy unsafe draft",
                author_id=author_id,
                idempotency_key=f"changeset-create-{uuid4().hex}",
                request_hash="1" * 64,
            )
            with pytest.raises(ValidationError, match="exceeds the graph"):
                await store.append_change_operation(
                    workspace_id=workspace_id,
                    graph_id=graph.graph_id,
                    changeset_id=changeset.changeset_id,
                    actor_id=author_id,
                    expected_version=changeset.version,
                    operation=_operation(classification=1),
                )
            await session.rollback()

        unsafe_operation = _operation(classification=1)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO knowledge.change_operations
                        (id, workspace_id, changeset_id, sequence, operation,
                         entity_kind, stable_entity_id, document, provenance, confidence)
                    VALUES
                        (:id, :workspace_id, :changeset_id, 1, 'UPSERT',
                         'NODE', :stable_entity_id, CAST(:document AS JSONB),
                         CAST(:provenance AS JSONB), 1.0)
                    """
                ),
                {
                    "id": uuid4(),
                    "workspace_id": workspace_id,
                    "changeset_id": changeset.changeset_id,
                    "stable_entity_id": unsafe_operation.stable_entity_id,
                    "document": json.dumps(unsafe_operation.document),
                    "provenance": json.dumps(
                        [value.to_document() for value in unsafe_operation.provenance]
                    ),
                },
            )

        async with sessions() as session:
            store = SqlKnowledgeStore(session)
            with pytest.raises(ConflictError, match="legacy changeset"):
                await store.list_changesets(
                    workspace_id=workspace_id,
                    graph_id=graph.graph_id,
                )
            safe_operation = _operation(classification=0)
            with pytest.raises(ConflictError, match="legacy changeset"):
                await store.append_change_operation(
                    workspace_id=workspace_id,
                    graph_id=graph.graph_id,
                    changeset_id=changeset.changeset_id,
                    actor_id=author_id,
                    expected_version=changeset.version,
                    operation=safe_operation,
                )
            with pytest.raises(ValidationError, match="cannot enter review"):
                await store.submit_changeset(
                    workspace_id=workspace_id,
                    graph_id=graph.graph_id,
                    changeset_id=changeset.changeset_id,
                    actor_id=author_id,
                    expected_version=changeset.version,
                )
            await session.rollback()

        async with engine.connect() as connection:
            operation_count = await connection.scalar(
                text(
                    """
                    SELECT count(*) FROM knowledge.change_operations
                    WHERE workspace_id = :workspace_id AND changeset_id = :changeset_id
                    """
                ),
                {"workspace_id": workspace_id, "changeset_id": changeset.changeset_id},
            )
        assert operation_count == 1

        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE knowledge.changesets
                    SET state = 'REVIEW', version = 2
                    WHERE workspace_id = :workspace_id AND id = :changeset_id
                    """
                ),
                {"workspace_id": workspace_id, "changeset_id": changeset.changeset_id},
            )

        async with sessions() as session:
            store = SqlKnowledgeStore(session)
            with pytest.raises(ConflictError, match="violates the graph envelope"):
                await store.review_changeset(
                    workspace_id=workspace_id,
                    graph_id=graph.graph_id,
                    changeset_id=changeset.changeset_id,
                    actor_id=reviewer_id,
                    decision=ChangeSetState.APPROVED,
                    reason="must reject",
                    expected_version=2,
                )
            await session.rollback()

        async with sessions() as session:
            rejected = await SqlKnowledgeStore(session).review_changeset(
                workspace_id=workspace_id,
                graph_id=graph.graph_id,
                changeset_id=changeset.changeset_id,
                actor_id=reviewer_id,
                decision=ChangeSetState.REJECTED,
                reason="outside classification envelope",
                expected_version=2,
            )
        assert rejected.state == "REJECTED"
        assert rejected.operations == ()
        assert rejected.validations == ()
    finally:
        await engine.dispose()


@pytest.mark.skipif(not _POSTGRES_ENABLED, reason="isolated PostgreSQL evidence is not configured")
@pytest.mark.asyncio
async def test_publish_and_activation_revalidate_review_lineage_and_projection_receipt() -> None:
    engine = _engine()
    workspace_id = await _workspace(engine)
    graph_id, changeset_id, publisher_id = await _approved_changeset(
        engine,
        workspace_id=workspace_id,
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE knowledge.changesets
                    SET reviewed_by = author_id
                    WHERE workspace_id = :workspace_id AND id = :changeset_id
                    """
                ),
                {"workspace_id": workspace_id, "changeset_id": changeset_id},
            )
        async with sessions() as session:
            with pytest.raises(ConflictError, match="independent-review evidence"):
                await SqlKnowledgeStore(session).publish_approved_changeset(
                    workspace_id=workspace_id,
                    graph_id=graph_id,
                    changeset_id=changeset_id,
                    published_by=publisher_id,
                    idempotency_key="knowledge-publication-invalid-review",
                    request_hash="2" * 64,
                )
            await session.rollback()

        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE knowledge.changesets
                    SET reviewed_by = :reviewer_id
                    WHERE workspace_id = :workspace_id AND id = :changeset_id
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "changeset_id": changeset_id,
                    "reviewer_id": publisher_id,
                },
            )
        async with sessions() as session:
            _, release = await SqlKnowledgeStore(session).publish_approved_changeset(
                workspace_id=workspace_id,
                graph_id=graph_id,
                changeset_id=changeset_id,
                published_by=publisher_id,
                idempotency_key="knowledge-publication-valid-review",
                request_hash="3" * 64,
            )

        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE knowledge.changesets
                    SET published_release_id = NULL
                    WHERE workspace_id = :workspace_id AND id = :changeset_id
                    """
                ),
                {"workspace_id": workspace_id, "changeset_id": changeset_id},
            )
        async with sessions() as session:
            store = SqlKnowledgeStore(session)
            assert (
                await store.list_releases(
                    workspace_id=workspace_id,
                    graph_id=graph_id,
                )
                == ()
            )
            assert (
                await store.get_release_snapshot(
                    workspace_id=workspace_id,
                    graph_id=graph_id,
                    release_id=release.release_id,
                    clearance=3,
                    maximum_nodes=100,
                )
                is None
            )
            with pytest.raises(ConflictError, match="publication lineage"):
                await store.activate_release(
                    workspace_id=workspace_id,
                    graph_id=graph_id,
                    release_id=release.release_id,
                    expected_graph_version=1,
                )
            await session.rollback()

        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE knowledge.changesets
                    SET published_release_id = :release_id
                    WHERE workspace_id = :workspace_id AND id = :changeset_id
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "changeset_id": changeset_id,
                    "release_id": release.release_id,
                },
            )
            await connection.execute(
                text(
                    """
                    UPDATE knowledge.projection_deployments
                    SET verification_hash = :invalid_hash
                    WHERE workspace_id = :workspace_id AND release_id = :release_id
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "release_id": release.release_id,
                    "invalid_hash": "0" * 64,
                },
            )
        async with sessions() as session:
            with pytest.raises(ConflictError, match="no verified canonical"):
                await SqlKnowledgeStore(session).activate_release(
                    workspace_id=workspace_id,
                    graph_id=graph_id,
                    release_id=release.release_id,
                    expected_graph_version=1,
                )
    finally:
        await engine.dispose()


@pytest.mark.skipif(not _POSTGRES_ENABLED, reason="isolated PostgreSQL evidence is not configured")
@pytest.mark.asyncio
async def test_whitespace_review_reason_changes_no_state_or_version() -> None:
    engine = _engine()
    workspace_id = await _workspace(engine)
    author_id = uuid4()
    reviewer_id = uuid4()
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            store = SqlKnowledgeStore(session)
            graph = await store.create_graph(
                workspace_id=workspace_id,
                actor_id=author_id,
                slug=f"graph-{uuid4().hex}",
                name="Review reason",
                graph_type="DOMAIN",
                classification=1,
                entity_types=frozenset({"Dataset"}),
                edge_types=frozenset(),
                idempotency_key=f"graph-create-{uuid4().hex}",
                request_hash="4" * 64,
            )
            changeset = await store.create_changeset(
                workspace_id=workspace_id,
                graph_id=graph.graph_id,
                title="Review reason",
                author_id=author_id,
                idempotency_key=f"changeset-create-{uuid4().hex}",
                request_hash="5" * 64,
            )
            changeset = await store.append_change_operation(
                workspace_id=workspace_id,
                graph_id=graph.graph_id,
                changeset_id=changeset.changeset_id,
                actor_id=author_id,
                expected_version=changeset.version,
                operation=_operation(),
            )
            changeset = await store.submit_changeset(
                workspace_id=workspace_id,
                graph_id=graph.graph_id,
                changeset_id=changeset.changeset_id,
                actor_id=author_id,
                expected_version=changeset.version,
            )
            with pytest.raises(ValidationError, match="non-empty review reason"):
                await store.review_changeset(
                    workspace_id=workspace_id,
                    graph_id=graph.graph_id,
                    changeset_id=changeset.changeset_id,
                    actor_id=reviewer_id,
                    decision=ChangeSetState.APPROVED,
                    reason=" \t ",
                    expected_version=changeset.version,
                )
            await session.rollback()

        async with engine.connect() as connection:
            state_and_version = (
                await connection.execute(
                    text(
                        """
                        SELECT state, version FROM knowledge.changesets
                        WHERE workspace_id = :workspace_id AND id = :changeset_id
                        """
                    ),
                    {
                        "workspace_id": workspace_id,
                        "changeset_id": changeset.changeset_id,
                    },
                )
            ).one()
        assert tuple(state_and_version) == ("REVIEW", changeset.version)
    finally:
        await engine.dispose()


@pytest.mark.skipif(not _POSTGRES_ENABLED, reason="isolated PostgreSQL evidence is not configured")
@pytest.mark.asyncio
async def test_legacy_active_release_cannot_be_exposed_rebased_or_replayed() -> None:
    engine = _engine()
    workspace_id = await _workspace(engine)
    graph_id, changeset_id, reviewer_id = await _approved_changeset(
        engine,
        workspace_id=workspace_id,
    )
    author_id = uuid4()
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            store = SqlKnowledgeStore(session)
            changeset, release = await store.publish_approved_changeset(
                workspace_id=workspace_id,
                graph_id=graph_id,
                changeset_id=changeset_id,
                published_by=reviewer_id,
                idempotency_key="legacy-base-publication",
                request_hash="8" * 64,
            )
            await store.activate_release(
                workspace_id=workspace_id,
                graph_id=graph_id,
                release_id=release.release_id,
                expected_graph_version=1,
            )
            sharing = SqlSharingStore(session)
            product = await sharing.create_product(
                workspace_id=workspace_id,
                slug=f"legacy-release-{uuid4().hex}",
                name="Governed before lineage corruption",
                description="Must disappear if its pinned release loses lineage.",
                graph_id=graph_id,
                release_id=release.release_id,
                classification=1,
                owner_id=author_id,
                surface="NEIGHBORS",
                contract_document={
                    "scopes": ["neighbors.query"],
                    "response_schema": {"type": "object"},
                    "query_template": "neighbors-v1",
                },
                maximum_hops=2,
                maximum_nodes=100,
                timeout_ms=5000,
                idempotency_key="legacy-sharing-product",
                request_hash="c" * 64,
            )
            with pytest.raises(ConflictError, match="bound to another owner"):
                await sharing.create_product(
                    workspace_id=workspace_id,
                    slug=product.slug,
                    name=product.name,
                    description=product.description,
                    graph_id=graph_id,
                    release_id=release.release_id,
                    classification=1,
                    owner_id=reviewer_id,
                    surface="NEIGHBORS",
                    contract_document={
                        "scopes": ["neighbors.query"],
                        "response_schema": {"type": "object"},
                        "query_template": "neighbors-v1",
                    },
                    maximum_hops=2,
                    maximum_nodes=100,
                    timeout_ms=5000,
                    idempotency_key="legacy-sharing-product",
                    request_hash="c" * 64,
                )
            published_product = await sharing.publish_version(
                workspace_id=workspace_id,
                product_id=product.product_id,
                version_id=product.versions[0].version_id,
                actor_id=author_id,
                expected_version=1,
            )
            draft_version = await sharing.create_version(
                workspace_id=workspace_id,
                product_id=product.product_id,
                release_id=release.release_id,
                actor_id=author_id,
                surface="NEIGHBORS",
                contract_document={
                    "scopes": ["neighbors.query"],
                    "response_schema": {"type": "object"},
                    "query_template": "neighbors-v1",
                },
                maximum_hops=2,
                maximum_nodes=100,
                timeout_ms=5000,
                idempotency_key="legacy-sharing-version",
                request_hash="d" * 64,
            )
            other_product = await sharing.create_product(
                workspace_id=workspace_id,
                slug=f"other-release-{uuid4().hex}",
                name="Other owner product",
                description="Cross-resource idempotency negative.",
                graph_id=graph_id,
                release_id=release.release_id,
                classification=1,
                owner_id=reviewer_id,
                surface="NEIGHBORS",
                contract_document={
                    "scopes": ["neighbors.query"],
                    "response_schema": {"type": "object"},
                    "query_template": "neighbors-v1",
                },
                maximum_hops=2,
                maximum_nodes=100,
                timeout_ms=5000,
                idempotency_key="other-sharing-product",
                request_hash="f" * 64,
            )
            with pytest.raises(ConflictError, match="result is unavailable"):
                await sharing.create_version(
                    workspace_id=workspace_id,
                    product_id=other_product.product_id,
                    release_id=release.release_id,
                    actor_id=reviewer_id,
                    surface="NEIGHBORS",
                    contract_document={
                        "scopes": ["neighbors.query"],
                        "response_schema": {"type": "object"},
                        "query_template": "neighbors-v1",
                    },
                    maximum_hops=2,
                    maximum_nodes=100,
                    timeout_ms=5000,
                    idempotency_key="legacy-sharing-version",
                    request_hash="d" * 64,
                )
            now = datetime.now(UTC)
            consumer_subject_id = uuid4()
            await session.execute(
                text(
                    """
                    INSERT INTO iam.subjects (
                        id, issuer, external_subject, display_name, active
                    ) VALUES (
                        :subject_id, 'knowledge-publication-test', :external_subject,
                        'Sharing service consumer', true
                    )
                    """
                ),
                {
                    "subject_id": consumer_subject_id,
                    "external_subject": str(consumer_subject_id),
                },
            )
            await session.execute(
                text(
                    """
                    INSERT INTO iam.workspace_memberships (
                        workspace_id, subject_id, department_id, job_function,
                        clearance, attributes, active, access_expires_at, version
                    ) VALUES (
                        :workspace_id, :subject_id, NULL, 'SERVICE_ACCOUNT',
                        3, '{}'::jsonb, true, NULL, 1
                    )
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "subject_id": consumer_subject_id,
                },
            )
            await session.commit()
            grant = await sharing.create_grant(
                workspace_id=workspace_id,
                product_id=product.product_id,
                consumer_subject_id=consumer_subject_id,
                consumer_client_id="legacy-release-client",
                scopes=frozenset({"neighbors.query"}),
                maximum_classification=1,
                requests_per_minute=10,
                monthly_quota=100,
                valid_from=now - timedelta(minutes=1),
                expires_at=now + timedelta(hours=1),
                actor_id=author_id,
                idempotency_key="legacy-sharing-grant",
                request_hash="e" * 64,
            )
            with pytest.raises(ConflictError, match="result is unavailable"):
                await sharing.create_grant(
                    workspace_id=workspace_id,
                    product_id=other_product.product_id,
                    consumer_subject_id=consumer_subject_id,
                    consumer_client_id="legacy-release-client",
                    scopes=frozenset({"neighbors.query"}),
                    maximum_classification=1,
                    requests_per_minute=10,
                    monthly_quota=100,
                    valid_from=now - timedelta(minutes=1),
                    expires_at=now + timedelta(hours=1),
                    actor_id=reviewer_id,
                    idempotency_key="legacy-sharing-grant",
                    request_hash="e" * 64,
                )
            captured = await store.create_changeset(
                workspace_id=workspace_id,
                graph_id=graph_id,
                title="Captured governed base",
                author_id=author_id,
                idempotency_key="captured-governed-base",
                request_hash="9" * 64,
            )
            with pytest.raises(ConflictError, match="bound to another author"):
                await store.create_changeset(
                    workspace_id=workspace_id,
                    graph_id=graph_id,
                    title="Captured governed base",
                    author_id=reviewer_id,
                    idempotency_key="captured-governed-base",
                    request_hash="9" * 64,
                )
            assert captured.base_release_id == release.release_id
            assert changeset.published_release_id == release.release_id
            assert published_product.current_version_id == product.versions[0].version_id
            assert grant.product_version_id == product.versions[0].version_id

        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE knowledge.changesets
                    SET state = 'APPROVED', published_release_id = NULL
                    WHERE workspace_id = :workspace_id AND id = :changeset_id
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "changeset_id": changeset_id,
                },
            )

        async with sessions() as session:
            store = SqlKnowledgeStore(session)
            graph = await store.get_graph(
                workspace_id=workspace_id,
                graph_id=graph_id,
                clearance=3,
            )
            assert graph is not None
            assert graph.active_release_id is None
            listed = await store.list_graphs(
                workspace_id=workspace_id,
                clearance=3,
                allowed_domain_ids=frozenset(),
            )
            assert listed[0].active_release_id is None
            evidence = await SqlKnowledgeEvidenceReader(session).search_active_nodes(
                workspace_id=workspace_id,
                query="governed_asset",
                maximum_classification=3,
                limit=10,
            )
            assert evidence == ()
            sharing = SqlSharingStore(session)
            assert (
                await sharing.list_products(
                    workspace_id=workspace_id,
                    clearance=3,
                )
                == ()
            )
            assert (
                await sharing.get_product(
                    workspace_id=workspace_id,
                    product_id=product.product_id,
                    clearance=3,
                )
                is None
            )
            assert (
                await sharing.list_grants(
                    workspace_id=workspace_id,
                    product_id=product.product_id,
                )
                == ()
            )
            with pytest.raises(ConflictError, match="governed changeset base"):
                await sharing.create_version(
                    workspace_id=workspace_id,
                    product_id=product.product_id,
                    release_id=release.release_id,
                    actor_id=author_id,
                    surface="NEIGHBORS",
                    contract_document={
                        "scopes": ["neighbors.query"],
                        "response_schema": {"type": "object"},
                        "query_template": "neighbors-v1",
                    },
                    maximum_hops=2,
                    maximum_nodes=100,
                    timeout_ms=5000,
                    idempotency_key="legacy-sharing-version",
                    request_hash="d" * 64,
                )
            with pytest.raises(ConflictError, match="governed changeset base"):
                await sharing.publish_version(
                    workspace_id=workspace_id,
                    product_id=product.product_id,
                    version_id=draft_version.version_id,
                    actor_id=author_id,
                    expected_version=2,
                )
            with pytest.raises(ConflictError, match="governed changeset base"):
                await sharing.create_grant(
                    workspace_id=workspace_id,
                    product_id=product.product_id,
                    consumer_subject_id=consumer_subject_id,
                    consumer_client_id="legacy-release-client",
                    scopes=frozenset({"neighbors.query"}),
                    maximum_classification=1,
                    requests_per_minute=10,
                    monthly_quota=100,
                    valid_from=now - timedelta(minutes=1),
                    expires_at=now + timedelta(hours=1),
                    actor_id=author_id,
                    idempotency_key="legacy-sharing-grant",
                    request_hash="e" * 64,
                )
            with pytest.raises(ConflictError, match="governed changeset base"):
                await SqlSharingStore(session)._require_release(
                    workspace_id,
                    graph_id,
                    release.release_id,
                )
            with pytest.raises(ConflictError, match="governed changeset base"):
                await store.create_changeset(
                    workspace_id=workspace_id,
                    graph_id=graph_id,
                    title="Legacy active base",
                    author_id=author_id,
                    idempotency_key="legacy-active-base",
                    request_hash="a" * 64,
                )
            with pytest.raises(ConflictError, match="governed changeset base"):
                await store.publish_approved_changeset(
                    workspace_id=workspace_id,
                    graph_id=graph_id,
                    changeset_id=changeset_id,
                    published_by=reviewer_id,
                    idempotency_key="legacy-base-publication",
                    request_hash="8" * 64,
                )
            captured = await store.append_change_operation(
                workspace_id=workspace_id,
                graph_id=graph_id,
                changeset_id=captured.changeset_id,
                actor_id=author_id,
                expected_version=captured.version,
                operation=_operation(),
            )
            with pytest.raises(ConflictError, match="governed changeset base"):
                await store.submit_changeset(
                    workspace_id=workspace_id,
                    graph_id=graph_id,
                    changeset_id=captured.changeset_id,
                    actor_id=author_id,
                    expected_version=captured.version,
                )
    finally:
        await engine.dispose()


@pytest.mark.skipif(not _POSTGRES_ENABLED, reason="isolated PostgreSQL evidence is not configured")
@pytest.mark.asyncio
async def test_neo4j_projection_receipt_is_bound_to_the_governed_release_and_hash() -> None:
    engine = _engine()
    workspace_id = await _workspace(engine)
    graph_id, changeset_id, reviewer_id = await _approved_changeset(
        engine,
        workspace_id=workspace_id,
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            _, release = await SqlKnowledgeStore(session).publish_approved_changeset(
                workspace_id=workspace_id,
                graph_id=graph_id,
                changeset_id=changeset_id,
                published_by=reviewer_id,
                idempotency_key="shadow-receipt-publication",
                request_hash="b" * 64,
            )
            deployment_id = uuid4()
            repository = SqlKnowledgePipelineRepository(session)
            with pytest.raises(ConflictError, match="does not match"):
                await repository.record_projection(
                    receipt=ProjectionReceipt(
                        deployment_id=uuid4(),
                        workspace_id=workspace_id,
                        graph_id=graph_id,
                        release_id=release.release_id,
                        release_hash=release.content_hash,
                        node_count=release.node_count,
                        edge_count=release.edge_count,
                        verified=False,
                    )
                )
            await repository.record_projection(
                receipt=ProjectionReceipt(
                    deployment_id=deployment_id,
                    workspace_id=workspace_id,
                    graph_id=graph_id,
                    release_id=release.release_id,
                    release_hash=release.content_hash,
                    node_count=release.node_count,
                    edge_count=release.edge_count,
                    verified=True,
                )
            )
            await repository.require_verified_projection(
                workspace_id=workspace_id,
                graph_id=graph_id,
                release_id=release.release_id,
                release_hash=release.content_hash,
                node_count=release.node_count,
                edge_count=release.edge_count,
            )

        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE knowledge.projection_deployments
                    SET verification_hash = :invalid_hash
                    WHERE workspace_id = :workspace_id AND id = :deployment_id
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "deployment_id": deployment_id,
                    "invalid_hash": "0" * 64,
                },
            )

        async with sessions() as session:
            with pytest.raises(ConflictError, match="no verified Neo4j"):
                await SqlKnowledgePipelineRepository(session).require_verified_projection(
                    workspace_id=workspace_id,
                    graph_id=graph_id,
                    release_id=release.release_id,
                    release_hash=release.content_hash,
                    node_count=release.node_count,
                    edge_count=release.edge_count,
                )
    finally:
        await engine.dispose()


@pytest.mark.skipif(not _POSTGRES_ENABLED, reason="isolated PostgreSQL evidence is not configured")
@pytest.mark.asyncio
async def test_different_changesets_cannot_publish_the_same_snapshot_concurrently() -> None:
    engine = _engine()
    workspace_id = await _workspace(engine)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    shared_operation = _operation()
    try:
        async with sessions() as session:
            store = SqlKnowledgeStore(session)
            graph = await store.create_graph(
                workspace_id=workspace_id,
                actor_id=uuid4(),
                slug=f"graph-{uuid4().hex}",
                name="Duplicate snapshot",
                graph_type="DOMAIN",
                classification=1,
                entity_types=frozenset({"Dataset"}),
                edge_types=frozenset(),
                idempotency_key=f"graph-create-{uuid4().hex}",
                request_hash="6" * 64,
            )

        async def approve(title: str) -> tuple[UUID, UUID]:
            author_id = uuid4()
            reviewer_id = uuid4()
            async with sessions() as session:
                store = SqlKnowledgeStore(session)
                changeset = await store.create_changeset(
                    workspace_id=workspace_id,
                    graph_id=graph.graph_id,
                    title=title,
                    author_id=author_id,
                    idempotency_key=f"changeset-create-{uuid4().hex}",
                    request_hash="7" * 64,
                )
                changeset = await store.append_change_operation(
                    workspace_id=workspace_id,
                    graph_id=graph.graph_id,
                    changeset_id=changeset.changeset_id,
                    actor_id=author_id,
                    expected_version=changeset.version,
                    operation=shared_operation,
                )
                changeset = await store.submit_changeset(
                    workspace_id=workspace_id,
                    graph_id=graph.graph_id,
                    changeset_id=changeset.changeset_id,
                    actor_id=author_id,
                    expected_version=changeset.version,
                )
                changeset = await store.review_changeset(
                    workspace_id=workspace_id,
                    graph_id=graph.graph_id,
                    changeset_id=changeset.changeset_id,
                    actor_id=reviewer_id,
                    decision=ChangeSetState.APPROVED,
                    reason="independent approval",
                    expected_version=changeset.version,
                )
            return changeset.changeset_id, reviewer_id

        first, second = await asyncio.gather(approve("first"), approve("second"))

        async def publish(
            changeset_id: UUID,
            publisher_id: UUID,
            key: str,
        ) -> UUID:
            async with sessions() as session:
                _, release = await SqlKnowledgeStore(session).publish_approved_changeset(
                    workspace_id=workspace_id,
                    graph_id=graph.graph_id,
                    changeset_id=changeset_id,
                    published_by=publisher_id,
                    idempotency_key=key,
                    request_hash="8" * 64,
                )
                return release.release_id

        results = await asyncio.gather(
            publish(first[0], first[1], "duplicate-first-key"),
            publish(second[0], second[1], "duplicate-second-key"),
            return_exceptions=True,
        )
        assert sum(isinstance(value, UUID) for value in results) == 1
        conflicts = [value for value in results if isinstance(value, ConflictError)]
        assert len(conflicts) == 1
        assert "exact graph snapshot" in str(conflicts[0])

        async with engine.connect() as connection:
            release_count = await connection.scalar(
                text(
                    """
                    SELECT count(*) FROM knowledge.releases
                    WHERE workspace_id = :workspace_id AND graph_id = :graph_id
                    """
                ),
                {"workspace_id": workspace_id, "graph_id": graph.graph_id},
            )
            projection_count = await connection.scalar(
                text(
                    """
                    SELECT count(*) FROM knowledge.projection_deployments
                    WHERE workspace_id = :workspace_id AND graph_id = :graph_id
                    """
                ),
                {"workspace_id": workspace_id, "graph_id": graph.graph_id},
            )
            outbox_count = await connection.scalar(
                text(
                    """
                    SELECT count(*) FROM integration.outbox_events
                    WHERE workspace_id = :workspace_id
                      AND event_type = 'knowledge.release.published.v2'
                    """
                ),
                {"workspace_id": workspace_id},
            )
            publication_idempotency_count = await connection.scalar(
                text(
                    """
                    SELECT count(*) FROM integration.idempotency_keys
                    WHERE workspace_id = :workspace_id
                      AND operation LIKE 'knowledge.changeset.publish:%'
                    """
                ),
                {"workspace_id": workspace_id},
            )
            published_changeset_count = await connection.scalar(
                text(
                    """
                    SELECT count(*) FROM knowledge.changesets
                    WHERE workspace_id = :workspace_id AND graph_id = :graph_id
                      AND state = 'PUBLISHED' AND published_release_id IS NOT NULL
                    """
                ),
                {"workspace_id": workspace_id, "graph_id": graph.graph_id},
            )
        assert release_count == 1
        assert projection_count == 1
        assert outbox_count == 1
        assert publication_idempotency_count == 1
        assert published_changeset_count == 1
    finally:
        await engine.dispose()
