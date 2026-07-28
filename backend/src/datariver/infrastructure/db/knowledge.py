from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from datariver.application.dto import (
    KnowledgeChangeOperationRecord,
    KnowledgeChangeSetRecord,
    KnowledgeGraphRecord,
    KnowledgeReleaseRecord,
    KnowledgeValidationRecord,
)
from datariver.application.ports import KnowledgeStore
from datariver.domain.authz import Classification
from datariver.domain.common import (
    ConflictError,
    DomainEvent,
    ValidationError,
    canonical_json_hash,
    utc_now,
    uuid7,
)
from datariver.domain.knowledge import (
    ChangeOperationType,
    ChangeSetState,
    GraphChangeOperation,
    GraphChangeSet,
    GraphEdge,
    GraphEntityKind,
    GraphNode,
    GraphRelease,
    GraphSnapshot,
    Ontology,
    Provenance,
    apply_change_operations,
)
from datariver.infrastructure.db.governance import SqlIdempotencyStore, SqlOutboxWriter
from datariver.infrastructure.db.models.catalog import CatalogVocabularyEntryModel
from datariver.infrastructure.db.models.knowledge import (
    ChangeOperationModel,
    ChangeSetModel,
    GraphModel,
    OntologyVersionModel,
    ProjectionDeploymentModel,
    ReleaseEdgeModel,
    ReleaseModel,
    ReleaseNodeModel,
    ValidationResultModel,
)


def _graph_record(
    model: GraphModel,
    *,
    domain_name: str | None = None,
) -> KnowledgeGraphRecord:
    return KnowledgeGraphRecord(
        graph_id=model.id,
        workspace_id=model.workspace_id,
        slug=model.slug,
        name=model.name,
        graph_type=model.graph_type,
        status=model.status,
        classification=Classification(model.classification),
        active_release_id=model.active_release_id,
        version=model.version,
        active_studio_release_id=model.active_studio_release_id,
        domain_id=model.domain_ref_id,
        domain_source_version=model.domain_source_version,
        domain_name=domain_name,
        created_by=model.created_by,
        updated_by=model.updated_by,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _release_record(model: ReleaseModel) -> KnowledgeReleaseRecord:
    return KnowledgeReleaseRecord(
        release_id=model.id,
        graph_id=model.graph_id,
        release_no=model.release_no,
        ontology_version_id=model.ontology_version_id,
        content_hash=model.content_hash,
        node_count=model.node_count,
        edge_count=model.edge_count,
        published_by=model.published_by,
        published_at=model.published_at,
    )


def _operation_record(model: ChangeOperationModel) -> KnowledgeChangeOperationRecord:
    return KnowledgeChangeOperationRecord(
        operation_id=model.id,
        sequence=model.sequence,
        operation=model.operation,
        entity_kind=model.entity_kind,
        stable_entity_id=model.stable_entity_id,
        document=model.document,
        provenance=tuple(model.provenance),
        confidence=model.confidence,
    )


def _validation_record(model: ValidationResultModel) -> KnowledgeValidationRecord:
    return KnowledgeValidationRecord(
        validation_id=model.id,
        severity=model.severity,
        code=model.code,
        location=model.location,
        message=model.message,
        validator=model.validator,
        validator_version=model.validator_version,
    )


def _domain_changeset(model: ChangeSetModel) -> GraphChangeSet:
    return GraphChangeSet(
        changeset_id=model.id,
        graph_id=model.graph_id,
        author_id=model.author_id,
        state=ChangeSetState(model.state),
        version=model.version,
    )


def _domain_operation(model: ChangeOperationModel) -> GraphChangeOperation:
    return GraphChangeOperation(
        sequence=model.sequence,
        operation=ChangeOperationType(model.operation),
        entity_kind=GraphEntityKind(model.entity_kind),
        stable_entity_id=model.stable_entity_id,
        document=model.document,
        provenance=_provenance(model.provenance),
        confidence=model.confidence,
    )


def governed_release_ids(
    *,
    workspace_id: UUID,
    graph_id: Any,
) -> Select[tuple[UUID | None]]:
    """Release ids backed by exactly one complete independent-review lineage."""

    return (
        select(ChangeSetModel.published_release_id)
        .where(
            ChangeSetModel.workspace_id == workspace_id,
            ChangeSetModel.graph_id == graph_id,
            ChangeSetModel.state == ChangeSetState.PUBLISHED.value,
            ChangeSetModel.published_release_id.is_not(None),
            ChangeSetModel.reviewed_by.is_not(None),
            ChangeSetModel.reviewed_by != ChangeSetModel.author_id,
            ChangeSetModel.reviewed_at.is_not(None),
            ChangeSetModel.review_reason.is_not(None),
            func.length(func.btrim(ChangeSetModel.review_reason)) > 0,
        )
        .group_by(ChangeSetModel.published_release_id)
        .having(func.count(ChangeSetModel.id) == 1)
    )


async def require_governed_release_base(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    graph_id: UUID,
    release_id: UUID | None,
) -> ReleaseModel | None:
    """Return an exact independently reviewed base release or fail closed."""

    if release_id is None:
        return None
    release = (
        await session.scalars(
            select(ReleaseModel).where(
                ReleaseModel.id == release_id,
                ReleaseModel.workspace_id == workspace_id,
                ReleaseModel.graph_id == graph_id,
                ReleaseModel.id.in_(
                    governed_release_ids(
                        workspace_id=workspace_id,
                        graph_id=graph_id,
                    )
                ),
            )
        )
    ).one_or_none()
    if release is None:
        raise ConflictError(
            "The active knowledge release cannot be used as a governed changeset base."
        )
    return release


class SqlKnowledgeStore(KnowledgeStore):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _governed_graph_record(
        self,
        model: GraphModel,
        *,
        domain_name: str | None = None,
    ) -> KnowledgeGraphRecord:
        record = _graph_record(model, domain_name=domain_name)
        if model.active_release_id is None:
            return record
        try:
            await require_governed_release_base(
                self._session,
                workspace_id=model.workspace_id,
                graph_id=model.id,
                release_id=model.active_release_id,
            )
        except ConflictError:
            return replace(record, active_release_id=None)
        return record

    async def create_graph(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        slug: str,
        name: str,
        graph_type: str,
        classification: int,
        entity_types: frozenset[str],
        edge_types: frozenset[str],
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeGraphRecord:
        idempotency = SqlIdempotencyStore(self._session)
        existing = await idempotency.get_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation="knowledge.graph.create",
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ConflictError("The idempotency key was used with a different request.")
            if str(existing.result.get("actor_id", "")) != str(actor_id):
                raise ConflictError(
                    "The idempotent knowledge graph result is bound to another actor."
                )
            graph = await self.get_graph(
                workspace_id=workspace_id,
                graph_id=UUID(existing.result["graph_id"]),
                clearance=int(Classification.RESTRICTED),
            )
            if graph is None:
                raise ConflictError("The idempotent graph result is unavailable.")
            return graph

        graph_id = uuid7()
        ontology_id = uuid7()
        ontology_document = {
            "entity_types": sorted(entity_types),
            "edge_types": sorted(edge_types),
        }
        checksum = hashlib.sha256(
            json.dumps(ontology_document, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        model = GraphModel(
            id=graph_id,
            workspace_id=workspace_id,
            slug=slug,
            name=name,
            graph_type=graph_type,
            status="DRAFT",
            classification=classification,
            version=1,
        )
        self._session.add(model)
        self._session.add(
            OntologyVersionModel(
                id=ontology_id,
                workspace_id=workspace_id,
                graph_id=graph_id,
                version="1.0.0",
                schema_document=ontology_document,
                checksum=checksum,
                status="ACTIVE",
            )
        )
        await idempotency.save_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation="knowledge.graph.create",
            request_hash=request_hash,
            result={"graph_id": str(graph_id), "actor_id": str(actor_id)},
        )
        try:
            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()
            raise ConflictError("A knowledge graph with this slug already exists.") from error
        return _graph_record(model)

    async def list_graphs(
        self,
        *,
        workspace_id: UUID,
        clearance: int,
        allowed_domain_ids: frozenset[UUID],
    ) -> tuple[KnowledgeGraphRecord, ...]:
        rows = (
            await self._session.execute(
                select(GraphModel, CatalogVocabularyEntryModel.display_name)
                .outerjoin(
                    CatalogVocabularyEntryModel,
                    (CatalogVocabularyEntryModel.workspace_id == GraphModel.workspace_id)
                    & (CatalogVocabularyEntryModel.id == GraphModel.domain_ref_id)
                    & (CatalogVocabularyEntryModel.kind == "DOMAIN"),
                )
                .where(
                    GraphModel.workspace_id == workspace_id,
                    GraphModel.classification <= clearance,
                    GraphModel.status != "ARCHIVED",
                    (
                        (GraphModel.classification == int(Classification.PUBLIC))
                        | GraphModel.domain_ref_id.is_(None)
                        | GraphModel.domain_ref_id.in_(allowed_domain_ids)
                    ),
                )
                .order_by(GraphModel.name, GraphModel.id)
            )
        ).all()
        return tuple(
            [
                await self._governed_graph_record(
                    model,
                    domain_name=domain_name,
                )
                for model, domain_name in rows
            ]
        )

    async def get_graph(
        self, *, workspace_id: UUID, graph_id: UUID, clearance: int
    ) -> KnowledgeGraphRecord | None:
        row = (
            await self._session.execute(
                select(GraphModel, CatalogVocabularyEntryModel.display_name)
                .outerjoin(
                    CatalogVocabularyEntryModel,
                    (CatalogVocabularyEntryModel.workspace_id == GraphModel.workspace_id)
                    & (CatalogVocabularyEntryModel.id == GraphModel.domain_ref_id)
                    & (CatalogVocabularyEntryModel.kind == "DOMAIN"),
                )
                .where(
                    GraphModel.id == graph_id,
                    GraphModel.workspace_id == workspace_id,
                    GraphModel.classification <= clearance,
                    GraphModel.status != "ARCHIVED",
                )
            )
        ).one_or_none()
        if row is None:
            return None
        model, domain_name = row
        return await self._governed_graph_record(model, domain_name=domain_name)

    async def get_graph_for_archive(
        self, *, workspace_id: UUID, graph_id: UUID, clearance: int
    ) -> KnowledgeGraphRecord | None:
        row = (
            await self._session.execute(
                select(GraphModel, CatalogVocabularyEntryModel.display_name)
                .outerjoin(
                    CatalogVocabularyEntryModel,
                    (CatalogVocabularyEntryModel.workspace_id == GraphModel.workspace_id)
                    & (CatalogVocabularyEntryModel.id == GraphModel.domain_ref_id)
                    & (CatalogVocabularyEntryModel.kind == "DOMAIN"),
                )
                .where(
                    GraphModel.id == graph_id,
                    GraphModel.workspace_id == workspace_id,
                    GraphModel.classification <= clearance,
                )
            )
        ).one_or_none()
        if row is None:
            return None
        model, domain_name = row
        return _graph_record(model, domain_name=domain_name)

    async def archive_graph(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        actor_id: UUID,
        expected_version: int,
        reason: str,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeGraphRecord:
        operation = f"knowledge.graph.archive:{graph_id}"
        idempotency = SqlIdempotencyStore(self._session)
        await idempotency.acquire_key_lock(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
        )
        existing = await idempotency.get_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ConflictError("The idempotency key was used with a different request.")
            if str(existing.result.get("actor_id", "")) != str(actor_id):
                raise ConflictError("The idempotent graph archive is bound to another actor.")
            replay = (
                await self._session.scalars(
                    select(GraphModel).where(
                        GraphModel.workspace_id == workspace_id,
                        GraphModel.id == graph_id,
                        GraphModel.status == "ARCHIVED",
                    )
                )
            ).one_or_none()
            if replay is None:
                raise ConflictError("The idempotent graph archive result is unavailable.")
            return _graph_record(replay)
        graph = (
            await self._session.scalars(
                select(GraphModel)
                .where(
                    GraphModel.workspace_id == workspace_id,
                    GraphModel.id == graph_id,
                    GraphModel.status != "ARCHIVED",
                )
                .with_for_update()
            )
        ).one_or_none()
        if graph is None:
            raise ValidationError("The knowledge graph does not exist.")
        if graph.version != expected_version:
            raise ConflictError("The knowledge graph version is stale.")
        now = utc_now()
        graph.status = "ARCHIVED"
        graph.archived_at = now
        graph.archived_by = actor_id
        graph.updated_by = actor_id
        graph.updated_at = now
        graph.version += 1
        await SqlOutboxWriter(self._session).add_events(
            [
                DomainEvent.create(
                    event_type="knowledge.graph.archived.v1",
                    aggregate_type="knowledge_graph",
                    aggregate_id=graph.id,
                    workspace_id=workspace_id,
                    payload={
                        "actor_id": str(actor_id),
                        "graph_id": str(graph.id),
                        "reason": reason,
                        "version": graph.version,
                    },
                )
            ]
        )
        await idempotency.save_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
            request_hash=request_hash,
            result={
                "actor_id": str(actor_id),
                "graph_id": str(graph.id),
                "version": graph.version,
            },
        )
        await self._session.commit()
        return _graph_record(graph)

    async def create_changeset(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        title: str,
        author_id: UUID,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeChangeSetRecord:
        idempotency = SqlIdempotencyStore(self._session)
        operation_name = f"knowledge.changeset.create:{graph_id}"
        existing = await idempotency.get_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation_name,
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ConflictError("The idempotency key was used with a different request.")
            if str(existing.result.get("author_id", "")) != str(author_id):
                raise ConflictError("The idempotent changeset result is bound to another author.")
            value = await self.get_changeset(
                workspace_id=workspace_id,
                graph_id=graph_id,
                changeset_id=UUID(existing.result["changeset_id"]),
            )
            if value is None:
                raise ConflictError("The idempotent changeset result is unavailable.")
            if value.author_id != author_id:
                raise ConflictError("The idempotent changeset result is bound to another author.")
            await require_governed_release_base(
                self._session,
                workspace_id=workspace_id,
                graph_id=graph_id,
                release_id=value.base_release_id,
            )
            return value
        graph = (
            await self._session.scalars(
                select(GraphModel)
                .where(GraphModel.id == graph_id, GraphModel.workspace_id == workspace_id)
                .with_for_update()
            )
        ).one_or_none()
        if graph is None:
            raise ValidationError("The knowledge graph does not exist.")
        await require_governed_release_base(
            self._session,
            workspace_id=workspace_id,
            graph_id=graph_id,
            release_id=graph.active_release_id,
        )
        ontology = (
            await self._session.scalars(
                select(OntologyVersionModel)
                .where(
                    OntologyVersionModel.graph_id == graph_id,
                    OntologyVersionModel.status == "ACTIVE",
                )
                .order_by(OntologyVersionModel.created_at.desc())
                .limit(1)
            )
        ).one_or_none()
        if ontology is None:
            raise ValidationError("The graph has no active ontology.")
        aggregate = GraphChangeSet.create(graph_id=graph_id, author_id=author_id)
        model = ChangeSetModel(
            id=aggregate.changeset_id,
            workspace_id=workspace_id,
            graph_id=graph_id,
            base_release_id=graph.active_release_id,
            ontology_version_id=ontology.id,
            title=title,
            state=aggregate.state.value,
            author_id=author_id,
            version=aggregate.version,
        )
        self._session.add(model)
        await idempotency.save_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation_name,
            request_hash=request_hash,
            result={"changeset_id": str(model.id), "author_id": str(author_id)},
        )
        await self._session.commit()
        return await self._changeset_record(model)

    async def list_changesets(
        self, *, workspace_id: UUID, graph_id: UUID
    ) -> tuple[KnowledgeChangeSetRecord, ...]:
        graph = await self._graph_for_envelope(
            workspace_id=workspace_id,
            graph_id=graph_id,
        )
        models = list(
            (
                await self._session.scalars(
                    select(ChangeSetModel)
                    .where(
                        ChangeSetModel.workspace_id == workspace_id,
                        ChangeSetModel.graph_id == graph_id,
                    )
                    .order_by(ChangeSetModel.created_at.desc(), ChangeSetModel.id)
                )
            ).all()
        )
        for model in models:
            await self._require_operation_envelope(
                model=model,
                maximum_classification=graph.classification,
            )
        return tuple([await self._changeset_record(model) for model in models])

    async def get_changeset(
        self, *, workspace_id: UUID, graph_id: UUID, changeset_id: UUID
    ) -> KnowledgeChangeSetRecord | None:
        model = (
            await self._session.scalars(
                select(ChangeSetModel).where(
                    ChangeSetModel.id == changeset_id,
                    ChangeSetModel.workspace_id == workspace_id,
                    ChangeSetModel.graph_id == graph_id,
                )
            )
        ).one_or_none()
        if model is not None:
            graph = await self._graph_for_envelope(
                workspace_id=workspace_id,
                graph_id=graph_id,
            )
            await self._require_operation_envelope(
                model=model,
                maximum_classification=graph.classification,
            )
        return await self._changeset_record(model) if model is not None else None

    async def append_change_operation(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        changeset_id: UUID,
        actor_id: UUID,
        expected_version: int,
        operation: GraphChangeOperation,
    ) -> KnowledgeChangeSetRecord:
        graph = await self._graph_for_envelope(
            workspace_id=workspace_id,
            graph_id=graph_id,
            lock=True,
        )
        operation.require_classification_ceiling(
            maximum_classification=graph.classification,
        )
        model = await self._lock_changeset(
            workspace_id=workspace_id, graph_id=graph_id, changeset_id=changeset_id
        )
        await self._require_operation_envelope(
            model=model,
            maximum_classification=graph.classification,
        )
        aggregate = _domain_changeset(model)
        aggregate.add_operation(
            actor_id=actor_id,
            expected_version=expected_version,
            operation=operation,
        )
        model.version = aggregate.version
        self._session.add(
            ChangeOperationModel(
                id=uuid7(),
                workspace_id=workspace_id,
                changeset_id=changeset_id,
                sequence=operation.sequence,
                operation=operation.operation.value,
                entity_kind=operation.entity_kind.value,
                stable_entity_id=operation.stable_entity_id,
                document=operation.document,
                provenance=[_provenance_document(item) for item in operation.provenance],
                confidence=operation.confidence,
            )
        )
        await self._session.execute(
            delete(ValidationResultModel).where(ValidationResultModel.changeset_id == changeset_id)
        )
        try:
            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()
            raise ConflictError("The changeset operation sequence already exists.") from error
        return await self._changeset_record(model)

    async def submit_changeset(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        changeset_id: UUID,
        actor_id: UUID,
        expected_version: int,
    ) -> KnowledgeChangeSetRecord:
        graph = await self._graph_for_envelope(
            workspace_id=workspace_id,
            graph_id=graph_id,
            lock=True,
        )
        model = await self._lock_changeset(
            workspace_id=workspace_id, graph_id=graph_id, changeset_id=changeset_id
        )
        if model.version != expected_version:
            raise ConflictError("The changeset version is stale.")
        if model.author_id != actor_id:
            raise ValidationError("Only the changeset author can submit it for review.")
        if ChangeSetState(model.state) is not ChangeSetState.DRAFT:
            raise ValidationError("Only a draft changeset can be submitted.")
        snapshot, ontology = await self._build_changeset_snapshot(model)
        violations = snapshot.validate(
            ontology,
            maximum_classification=graph.classification,
        )
        await self._session.execute(
            delete(ValidationResultModel).where(ValidationResultModel.changeset_id == changeset_id)
        )
        self._session.add_all(
            [
                ValidationResultModel(
                    id=uuid7(),
                    workspace_id=workspace_id,
                    changeset_id=changeset_id,
                    validator="builtin-graph",
                    validator_version="1",
                    severity="ERROR",
                    code=value.split(":", 1)[0],
                    location=value.partition(":")[2],
                    message=value,
                )
                for value in violations
            ]
        )
        if violations:
            await self._session.commit()
            raise ValidationError(
                "The changeset cannot enter review.", details={"violations": violations}
            )
        aggregate = _domain_changeset(model)
        aggregate.submit(
            actor_id=actor_id,
            expected_version=expected_version,
            snapshot=snapshot,
            ontology=ontology,
            maximum_classification=graph.classification,
        )
        model.state = aggregate.state.value
        model.version = aggregate.version
        await self._session.commit()
        return await self._changeset_record(model)

    async def review_changeset(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        changeset_id: UUID,
        actor_id: UUID,
        decision: ChangeSetState,
        reason: str,
        expected_version: int,
    ) -> KnowledgeChangeSetRecord:
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValidationError("A non-empty review reason is required.")
        graph = await self._graph_for_envelope(
            workspace_id=workspace_id,
            graph_id=graph_id,
            lock=True,
        )
        model = await self._lock_changeset(
            workspace_id=workspace_id, graph_id=graph_id, changeset_id=changeset_id
        )
        snapshot, ontology = await self._build_changeset_snapshot(model)
        violations = snapshot.validate(
            ontology,
            maximum_classification=graph.classification,
        )
        if violations and decision is ChangeSetState.APPROVED:
            raise ConflictError(
                "The changeset cannot be approved because it violates the graph envelope."
            )
        aggregate = _domain_changeset(model)
        aggregate.review(
            actor_id=actor_id,
            decision=decision,
            expected_version=expected_version,
        )
        model.state = aggregate.state.value
        model.version = aggregate.version
        model.reviewed_by = actor_id
        model.reviewed_at = utc_now()
        model.review_reason = normalized_reason
        await self._session.commit()
        result = await self._changeset_record(model)
        if violations:
            # A reviewer can terminate a legacy invalid review item without
            # receiving its over-envelope operation documents or validation
            # coordinates in the response.
            return replace(result, operations=(), validations=())
        return result

    async def publish_approved_changeset(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        changeset_id: UUID,
        published_by: UUID,
        idempotency_key: str,
        request_hash: str,
    ) -> tuple[KnowledgeChangeSetRecord, KnowledgeReleaseRecord]:
        """Publish one independently approved changeset in exactly one DB transaction.

        The release, immutable rows, canonical PostgreSQL projection receipt,
        changeset state, outbox event and idempotency result become visible
        together. Publication deliberately does not activate the graph.
        """

        idempotency = SqlIdempotencyStore(self._session)
        # integration.idempotency_keys.operation is intentionally bounded to
        # 100 characters. A changeset UUID is globally unique and the
        # workspace remains a separate key component.
        operation = f"knowledge.changeset.publish:{changeset_id}"
        await idempotency.acquire_key_lock(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
        )
        existing = await idempotency.get_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ConflictError("The idempotency key was used with a different request.")
            existing_release = await require_governed_release_base(
                self._session,
                workspace_id=workspace_id,
                graph_id=graph_id,
                release_id=UUID(existing.result["release_id"]),
            )
            changeset = (
                await self._session.scalars(
                    select(ChangeSetModel).where(
                        ChangeSetModel.workspace_id == workspace_id,
                        ChangeSetModel.graph_id == graph_id,
                        ChangeSetModel.id == changeset_id,
                    )
                )
            ).one_or_none()
            if (
                existing_release is None
                or changeset is None
                or changeset.state != ChangeSetState.PUBLISHED.value
                or changeset.published_release_id != existing_release.id
                or changeset.reviewed_by is None
                or changeset.reviewed_by == changeset.author_id
                or changeset.reviewed_at is None
                or not (changeset.review_reason or "").strip()
            ):
                raise ConflictError("The idempotent changeset publication is unavailable.")
            return await self._changeset_record(changeset), _release_record(existing_release)

        graph = (
            await self._session.scalars(
                select(GraphModel)
                .where(GraphModel.id == graph_id, GraphModel.workspace_id == workspace_id)
                .with_for_update()
            )
        ).one_or_none()
        if graph is None:
            raise ValidationError("The knowledge graph does not exist.")
        changeset = await self._lock_changeset(
            workspace_id=workspace_id,
            graph_id=graph_id,
            changeset_id=changeset_id,
        )
        aggregate = _domain_changeset(changeset)
        if aggregate.state is not ChangeSetState.APPROVED:
            raise ValidationError("Only an approved changeset can be published.")
        if (
            changeset.reviewed_by is None
            or changeset.reviewed_by == changeset.author_id
            or changeset.reviewed_at is None
            or not (changeset.review_reason or "").strip()
        ):
            raise ConflictError("The approved changeset has no valid independent-review evidence.")

        snapshot, ontology = await self._build_changeset_snapshot(changeset)
        violations = snapshot.validate(
            ontology,
            maximum_classification=graph.classification,
        )
        if violations:
            raise ConflictError("The approved changeset is no longer valid for this graph.")
        base_release = (
            await self._session.get(ReleaseModel, changeset.base_release_id)
            if changeset.base_release_id is not None
            else None
        )
        current_release = (
            await self._session.get(ReleaseModel, graph.active_release_id)
            if graph.active_release_id is not None
            else None
        )
        release_no = (
            int(
                (
                    await self._session.scalar(
                        select(func.coalesce(func.max(ReleaseModel.release_no), 0)).where(
                            ReleaseModel.graph_id == graph_id
                        )
                    )
                )
                or 0
            )
            + 1
        )
        graph_release = GraphRelease.publish(
            graph_id=graph_id,
            release_no=release_no,
            ontology=ontology,
            snapshot=snapshot,
            expected_base_hash=base_release.content_hash if base_release is not None else None,
            actual_base_hash=current_release.content_hash if current_release is not None else None,
            maximum_classification=graph.classification,
        )
        duplicate_release_id = await self._session.scalar(
            select(ReleaseModel.id).where(
                ReleaseModel.workspace_id == workspace_id,
                ReleaseModel.graph_id == graph_id,
                ReleaseModel.content_hash == graph_release.content_hash,
            )
        )
        if duplicate_release_id is not None:
            raise ConflictError("An immutable release already contains this exact graph snapshot.")
        published_at = utc_now()
        release_model = ReleaseModel(
            id=graph_release.release_id,
            workspace_id=workspace_id,
            graph_id=graph_id,
            release_no=graph_release.release_no,
            ontology_version_id=graph_release.ontology_version_id,
            content_hash=graph_release.content_hash,
            node_count=graph_release.node_count,
            edge_count=graph_release.edge_count,
            published_by=published_by,
            published_at=published_at,
        )
        self._session.add(release_model)
        # There are no ORM relationships between the immutable release and
        # changeset models, so SQLAlchemy cannot infer the FK flush order.
        # Flush only the release identity first; it remains uncommitted and is
        # rolled back with every later publication effect on failure.
        await self._session.flush((release_model,))
        self._session.add_all(
            [
                ReleaseNodeModel(
                    workspace_id=workspace_id,
                    release_id=graph_release.release_id,
                    entity_id=node.entity_id,
                    entity_type=node.entity_type,
                    properties=node.properties,
                    classification=node.classification,
                    provenance=[_provenance_document(item) for item in node.provenance],
                )
                for node in snapshot.nodes.values()
            ]
        )
        self._session.add_all(
            [
                ReleaseEdgeModel(
                    workspace_id=workspace_id,
                    release_id=graph_release.release_id,
                    edge_id=edge.edge_id,
                    source_entity_id=edge.source_entity_id,
                    target_entity_id=edge.target_entity_id,
                    edge_type=edge.edge_type,
                    properties=edge.properties,
                    classification=edge.classification,
                    provenance=[_provenance_document(item) for item in edge.provenance],
                )
                for edge in snapshot.edges.values()
            ]
        )
        # A canonical verification receipt must be derived from rows read back
        # from PostgreSQL, not from the in-memory publication proposal.
        await self._session.flush()
        persisted_node_models = list(
            (
                await self._session.scalars(
                    select(ReleaseNodeModel)
                    .where(
                        ReleaseNodeModel.workspace_id == workspace_id,
                        ReleaseNodeModel.release_id == graph_release.release_id,
                    )
                    .order_by(ReleaseNodeModel.entity_id)
                    .execution_options(populate_existing=True)
                )
            ).all()
        )
        persisted_edge_models = list(
            (
                await self._session.scalars(
                    select(ReleaseEdgeModel)
                    .where(
                        ReleaseEdgeModel.workspace_id == workspace_id,
                        ReleaseEdgeModel.release_id == graph_release.release_id,
                    )
                    .order_by(ReleaseEdgeModel.edge_id)
                    .execution_options(populate_existing=True)
                )
            ).all()
        )
        persisted_snapshot = GraphSnapshot(
            nodes={model.entity_id: _node(model) for model in persisted_node_models},
            edges={model.edge_id: _edge(model) for model in persisted_edge_models},
        )
        persisted_violations = persisted_snapshot.validate(
            ontology,
            maximum_classification=graph.classification,
        )
        if (
            persisted_violations
            or persisted_snapshot.content_hash() != graph_release.content_hash
            or len(persisted_snapshot.nodes) != graph_release.node_count
            or len(persisted_snapshot.edges) != graph_release.edge_count
        ):
            raise ConflictError("The canonical release read-back verification failed.")
        verification_hash = canonical_json_hash(
            {
                "adapter": "postgres-adjacency-v1",
                "edge_count": graph_release.edge_count,
                "node_count": graph_release.node_count,
                "release_hash": graph_release.content_hash,
                "release_id": str(graph_release.release_id),
            }
        )
        self._session.add(
            ProjectionDeploymentModel(
                id=uuid7(),
                workspace_id=workspace_id,
                graph_id=graph_id,
                release_id=graph_release.release_id,
                adapter="postgres-adjacency-v1",
                target_ref=f"postgresql://knowledge/releases/{graph_release.release_id}",
                state="CANONICAL_VERIFIED",
                content_hash=graph_release.content_hash,
                verification_hash=verification_hash,
                node_count=graph_release.node_count,
                edge_count=graph_release.edge_count,
                verified_at=published_at,
            )
        )

        aggregate.mark_published(expected_version=aggregate.version)
        changeset.state = aggregate.state.value
        changeset.version = aggregate.version
        changeset.published_release_id = graph_release.release_id
        await SqlOutboxWriter(self._session).add_events(
            [
                DomainEvent.create(
                    event_type="knowledge.release.published.v2",
                    aggregate_type="knowledge_graph",
                    aggregate_id=graph_id,
                    workspace_id=workspace_id,
                    payload={
                        "changeset_id": str(changeset_id),
                        "content_hash": graph_release.content_hash,
                        "graph_id": str(graph_id),
                        "release_id": str(graph_release.release_id),
                    },
                )
            ]
        )
        await idempotency.save_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
            request_hash=request_hash,
            result={"release_id": str(graph_release.release_id)},
        )
        await self._session.commit()
        return await self._changeset_record(changeset), _release_record(release_model)

    async def list_releases(
        self, *, workspace_id: UUID, graph_id: UUID
    ) -> tuple[KnowledgeReleaseRecord, ...]:
        models = list(
            (
                await self._session.scalars(
                    select(ReleaseModel)
                    .where(
                        ReleaseModel.workspace_id == workspace_id,
                        ReleaseModel.graph_id == graph_id,
                        ReleaseModel.id.in_(
                            governed_release_ids(
                                workspace_id=workspace_id,
                                graph_id=graph_id,
                            )
                        ),
                    )
                    .order_by(ReleaseModel.release_no.desc())
                )
            ).all()
        )
        return tuple(_release_record(model) for model in models)

    async def activate_release(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        release_id: UUID,
        expected_graph_version: int,
    ) -> KnowledgeGraphRecord:
        graph = (
            await self._session.scalars(
                select(GraphModel)
                .where(GraphModel.id == graph_id, GraphModel.workspace_id == workspace_id)
                .with_for_update()
            )
        ).one_or_none()
        if graph is None:
            raise ValidationError("The knowledge graph does not exist.")
        if graph.version != expected_graph_version:
            raise ConflictError("The knowledge graph version is stale.")
        release = await self._session.get(ReleaseModel, release_id)
        if release is None or release.graph_id != graph_id or release.workspace_id != workspace_id:
            raise ValidationError("The release does not belong to this knowledge graph.")
        publication_lineage = list(
            (
                await self._session.scalars(
                    select(ChangeSetModel).where(
                        ChangeSetModel.workspace_id == workspace_id,
                        ChangeSetModel.graph_id == graph_id,
                        ChangeSetModel.published_release_id == release_id,
                        ChangeSetModel.state == ChangeSetState.PUBLISHED.value,
                    )
                )
            ).all()
        )
        if (
            len(publication_lineage) != 1
            or publication_lineage[0].reviewed_by is None
            or publication_lineage[0].reviewed_by == publication_lineage[0].author_id
            or publication_lineage[0].reviewed_at is None
            or not (publication_lineage[0].review_reason or "").strip()
        ):
            raise ConflictError(
                "The release has no valid independently reviewed publication lineage."
            )
        projections = list(
            (
                await self._session.scalars(
                    select(ProjectionDeploymentModel).where(
                        ProjectionDeploymentModel.workspace_id == workspace_id,
                        ProjectionDeploymentModel.graph_id == graph_id,
                        ProjectionDeploymentModel.release_id == release_id,
                        ProjectionDeploymentModel.content_hash == release.content_hash,
                        ProjectionDeploymentModel.node_count == release.node_count,
                        ProjectionDeploymentModel.edge_count == release.edge_count,
                        ProjectionDeploymentModel.state.in_(
                            ("CANONICAL_VERIFIED", "SHADOW_VERIFIED")
                        ),
                    )
                )
            ).all()
        )
        verified_projection = any(
            self._projection_receipt_is_valid(
                projection=projection,
                release=release,
            )
            for projection in projections
        )
        if not verified_projection:
            raise ConflictError("The release has no verified canonical or Neo4j projection.")
        graph.active_release_id = release_id
        graph.status = "PUBLISHED"
        graph.version += 1
        await SqlOutboxWriter(self._session).add_events(
            [
                DomainEvent.create(
                    event_type="knowledge.release.activated.v1",
                    aggregate_type="knowledge_graph",
                    aggregate_id=graph_id,
                    workspace_id=workspace_id,
                    payload={"graph_id": str(graph_id), "release_id": str(release_id)},
                )
            ]
        )
        await self._session.commit()
        return _graph_record(graph)

    async def get_release_snapshot(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        release_id: UUID,
        clearance: int,
        maximum_nodes: int,
    ) -> tuple[KnowledgeReleaseRecord, GraphSnapshot] | None:
        release = (
            await self._session.scalars(
                select(ReleaseModel).where(
                    ReleaseModel.id == release_id,
                    ReleaseModel.graph_id == graph_id,
                    ReleaseModel.workspace_id == workspace_id,
                    ReleaseModel.id.in_(
                        governed_release_ids(
                            workspace_id=workspace_id,
                            graph_id=graph_id,
                        )
                    ),
                )
            )
        ).one_or_none()
        if release is None:
            return None
        node_models = list(
            (
                await self._session.scalars(
                    select(ReleaseNodeModel)
                    .where(
                        ReleaseNodeModel.release_id == release_id,
                        ReleaseNodeModel.classification <= clearance,
                    )
                    .order_by(ReleaseNodeModel.entity_id)
                    .limit(maximum_nodes + 1)
                )
            ).all()
        )
        if len(node_models) > maximum_nodes:
            raise ValidationError("The requested graph view exceeds the node limit.")
        visible_ids = {model.entity_id for model in node_models}
        edge_models = (
            list(
                (
                    await self._session.scalars(
                        select(ReleaseEdgeModel).where(
                            ReleaseEdgeModel.release_id == release_id,
                            ReleaseEdgeModel.classification <= clearance,
                            ReleaseEdgeModel.source_entity_id.in_(visible_ids),
                            ReleaseEdgeModel.target_entity_id.in_(visible_ids),
                        )
                    )
                ).all()
            )
            if visible_ids
            else []
        )
        snapshot = GraphSnapshot(
            nodes={model.entity_id: _node(model) for model in node_models},
            edges={model.edge_id: _edge(model) for model in edge_models},
        )
        return _release_record(release), snapshot

    async def _lock_changeset(
        self, *, workspace_id: UUID, graph_id: UUID, changeset_id: UUID
    ) -> ChangeSetModel:
        model = (
            await self._session.scalars(
                select(ChangeSetModel)
                .where(
                    ChangeSetModel.id == changeset_id,
                    ChangeSetModel.workspace_id == workspace_id,
                    ChangeSetModel.graph_id == graph_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        if model is None:
            raise ValidationError("The knowledge changeset does not exist.")
        return model

    async def _graph_for_envelope(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        lock: bool = False,
    ) -> GraphModel:
        statement = select(GraphModel).where(
            GraphModel.id == graph_id,
            GraphModel.workspace_id == workspace_id,
        )
        if lock:
            statement = statement.with_for_update()
        graph = (await self._session.scalars(statement)).one_or_none()
        if graph is None:
            raise ValidationError("The knowledge graph does not exist.")
        return graph

    @staticmethod
    def _projection_receipt_is_valid(
        *,
        projection: ProjectionDeploymentModel,
        release: ReleaseModel,
    ) -> bool:
        if projection.verified_at is None or projection.verification_hash is None:
            return False
        if (
            projection.adapter == "postgres-adjacency-v1"
            and projection.state == "CANONICAL_VERIFIED"
            and projection.target_ref == f"postgresql://knowledge/releases/{release.id}"
        ):
            expected = canonical_json_hash(
                {
                    "adapter": projection.adapter,
                    "edge_count": release.edge_count,
                    "node_count": release.node_count,
                    "release_hash": release.content_hash,
                    "release_id": str(release.id),
                }
            )
            return projection.verification_hash == expected
        if (
            projection.adapter == "neo4j-bolt-shadow-v1"
            and projection.state == "SHADOW_VERIFIED"
            and projection.target_ref == f"neo4j://release/{release.id}"
        ):
            expected = canonical_json_hash(
                {
                    "deployment_id": str(projection.id),
                    "edge_count": release.edge_count,
                    "node_count": release.node_count,
                    "release_hash": release.content_hash,
                }
            )
            return projection.verification_hash == expected
        return False

    async def _require_operation_envelope(
        self,
        *,
        model: ChangeSetModel,
        maximum_classification: int,
    ) -> None:
        operation_models = list(
            (
                await self._session.scalars(
                    select(ChangeOperationModel)
                    .where(ChangeOperationModel.changeset_id == model.id)
                    .order_by(ChangeOperationModel.sequence)
                )
            ).all()
        )
        try:
            for operation_model in operation_models:
                _domain_operation(operation_model).require_classification_ceiling(
                    maximum_classification=maximum_classification,
                )
        except ValidationError as error:
            raise ConflictError(
                "A legacy changeset is outside the graph classification envelope."
            ) from error

    async def _changeset_record(self, model: ChangeSetModel) -> KnowledgeChangeSetRecord:
        operations = list(
            (
                await self._session.scalars(
                    select(ChangeOperationModel)
                    .where(ChangeOperationModel.changeset_id == model.id)
                    .order_by(ChangeOperationModel.sequence)
                )
            ).all()
        )
        validations = list(
            (
                await self._session.scalars(
                    select(ValidationResultModel)
                    .where(ValidationResultModel.changeset_id == model.id)
                    .order_by(ValidationResultModel.severity, ValidationResultModel.code)
                )
            ).all()
        )
        return KnowledgeChangeSetRecord(
            changeset_id=model.id,
            graph_id=model.graph_id,
            base_release_id=model.base_release_id,
            ontology_version_id=model.ontology_version_id,
            title=model.title,
            state=model.state,
            author_id=model.author_id,
            reviewed_by=model.reviewed_by,
            review_reason=model.review_reason,
            published_release_id=model.published_release_id,
            version=model.version,
            created_at=model.created_at,
            updated_at=model.updated_at,
            operations=tuple(_operation_record(item) for item in operations),
            validations=tuple(_validation_record(item) for item in validations),
        )

    async def _build_changeset_snapshot(
        self, model: ChangeSetModel
    ) -> tuple[GraphSnapshot, Ontology]:
        ontology_model = await self._session.get(OntologyVersionModel, model.ontology_version_id)
        if ontology_model is None or ontology_model.graph_id != model.graph_id:
            raise ValidationError("The changeset ontology is unavailable.")
        schema = ontology_model.schema_document
        ontology = Ontology(
            version_id=ontology_model.id,
            entity_types=frozenset(str(value) for value in schema.get("entity_types", [])),
            edge_types=frozenset(str(value) for value in schema.get("edge_types", [])),
        )
        base = GraphSnapshot()
        if model.base_release_id is not None:
            await require_governed_release_base(
                self._session,
                workspace_id=model.workspace_id,
                graph_id=model.graph_id,
                release_id=model.base_release_id,
            )
            node_models = list(
                (
                    await self._session.scalars(
                        select(ReleaseNodeModel).where(
                            ReleaseNodeModel.release_id == model.base_release_id
                        )
                    )
                ).all()
            )
            edge_models = list(
                (
                    await self._session.scalars(
                        select(ReleaseEdgeModel).where(
                            ReleaseEdgeModel.release_id == model.base_release_id
                        )
                    )
                ).all()
            )
            base = GraphSnapshot(
                nodes={item.entity_id: _node(item) for item in node_models},
                edges={item.edge_id: _edge(item) for item in edge_models},
            )
        operation_models = list(
            (
                await self._session.scalars(
                    select(ChangeOperationModel)
                    .where(ChangeOperationModel.changeset_id == model.id)
                    .order_by(ChangeOperationModel.sequence)
                )
            ).all()
        )
        if not operation_models:
            raise ValidationError("A changeset must contain at least one operation.")
        snapshot = apply_change_operations(
            base, tuple(_domain_operation(item) for item in operation_models)
        )
        return snapshot, ontology


def _provenance_document(item: Provenance) -> dict[str, object]:
    return item.to_document()


def _provenance(items: list[dict[str, Any]]) -> tuple[Provenance, ...]:
    return tuple(Provenance.from_document(item) for item in items)


def _node(model: ReleaseNodeModel) -> GraphNode:
    return GraphNode(
        entity_id=model.entity_id,
        entity_type=model.entity_type,
        properties=model.properties,
        classification=model.classification,
        provenance=_provenance(model.provenance),
    )


def _edge(model: ReleaseEdgeModel) -> GraphEdge:
    return GraphEdge(
        edge_id=model.edge_id,
        source_entity_id=model.source_entity_id,
        target_entity_id=model.target_entity_id,
        edge_type=model.edge_type,
        properties=model.properties,
        classification=model.classification,
        provenance=_provenance(model.provenance),
    )
