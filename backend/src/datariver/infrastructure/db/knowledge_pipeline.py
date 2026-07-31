from __future__ import annotations

import hashlib
import math
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.application.knowledge_pipeline_ports import KnowledgeEmbeddingProvider
from datariver.application.services.knowledge_pipeline import KnowledgeSourcePipeline
from datariver.domain.common import (
    ConflictError,
    ValidationError,
    canonical_json_hash,
    utc_now,
    uuid7,
)
from datariver.domain.knowledge import GraphChangeOperation
from datariver.domain.knowledge_pipeline import (
    GraphRagAuditRecord,
    KnowledgeSourceAnalysis,
    KnowledgeSourceSnapshot,
    ModelBinding,
    PdfPage,
    ProjectionReceipt,
    supported_knowledge_source_media_types,
)
from datariver.infrastructure.db.knowledge import require_governed_release_base
from datariver.infrastructure.db.models.integration import ObjectManifestModel
from datariver.infrastructure.db.models.knowledge import (
    ChangeOperationModel,
    ChangeSetModel,
    GraphModel,
    KnowledgeExtractionRunModel,
    KnowledgeGraphRagAuditModel,
    KnowledgePageEmbeddingModel,
    KnowledgeSourcePageModel,
    KnowledgeSourceSnapshotModel,
    OntologyVersionModel,
    ProjectionDeploymentModel,
    ReleaseNodeModel,
)
from datariver.infrastructure.db.rls import set_security_context

_PARSER_CONFIGURATION_HASH = hashlib.sha256(b"bounded-knowledge-document-parser-v1").hexdigest()


def _binding_document(binding: ModelBinding) -> dict[str, object]:
    document: dict[str, object] = {
        "provider": binding.provider,
        "model": binding.model,
        "prompt_version": binding.prompt_version,
        "tool_schema_version": binding.tool_schema_version,
    }
    if binding.configuration_source is not None:
        document.update(
            {
                "configuration_source": binding.configuration_source,
                "configuration_version": binding.configuration_version,
                "configuration_hash": binding.configuration_hash,
            }
        )
    return document


def _provenance_document(operation: GraphChangeOperation) -> list[dict[str, object]]:
    return [value.to_document() for value in operation.provenance]


class SqlKnowledgePipelineRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def prepare_source(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        upload_id: UUID,
        actor_id: UUID,
    ) -> tuple[KnowledgeSourceSnapshot, frozenset[str], frozenset[str]]:
        graph = (
            await self._session.scalars(
                select(GraphModel).where(
                    GraphModel.workspace_id == workspace_id,
                    GraphModel.id == graph_id,
                )
            )
        ).one_or_none()
        manifest = (
            await self._session.scalars(
                select(ObjectManifestModel).where(
                    ObjectManifestModel.workspace_id == workspace_id,
                    ObjectManifestModel.id == upload_id,
                )
            )
        ).one_or_none()
        if graph is None or manifest is None:
            raise ValidationError("The knowledge graph or source upload does not exist.")
        if (
            manifest.state != "ACCEPTED"
            or manifest.owner_id != actor_id
            or manifest.mime not in supported_knowledge_source_media_types()
            or manifest.actual_sha256 != manifest.sha256
            or manifest.actual_size_bytes != manifest.size_bytes
        ):
            raise ValidationError(
                "The source must be an integrity-verified accepted Knowledge document."
            )
        if manifest.classification > graph.classification:
            raise ValidationError(
                "The source classification exceeds the graph classification envelope."
            )
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
                    OntologyVersionModel.workspace_id == workspace_id,
                    OntologyVersionModel.graph_id == graph_id,
                    OntologyVersionModel.status == "ACTIVE",
                )
                .order_by(OntologyVersionModel.created_at.desc())
                .limit(1)
            )
        ).one_or_none()
        if ontology is None:
            raise ValidationError("The graph has no active ontology.")
        existing = (
            await self._session.scalars(
                select(KnowledgeSourceSnapshotModel).where(
                    KnowledgeSourceSnapshotModel.workspace_id == workspace_id,
                    KnowledgeSourceSnapshotModel.graph_id == graph_id,
                    KnowledgeSourceSnapshotModel.upload_id == upload_id,
                )
            )
        ).one_or_none()
        if existing is not None and existing.state == "ANALYZED":
            raise ConflictError("This immutable Knowledge source has already been analyzed.")
        if existing is None:
            existing = KnowledgeSourceSnapshotModel(
                id=uuid7(),
                workspace_id=workspace_id,
                graph_id=graph_id,
                upload_id=upload_id,
                bucket=manifest.bucket,
                object_key=manifest.object_key,
                storage_version=f"manifest-v{manifest.version}",
                media_type=manifest.mime,
                byte_size=manifest.size_bytes,
                content_sha256=manifest.sha256,
                classification=manifest.classification,
                state="PENDING",
                created_by=actor_id,
            )
            self._session.add(existing)
            await self._session.commit()
        schema = ontology.schema_document
        return (
            KnowledgeSourceSnapshot(
                snapshot_id=existing.id,
                workspace_id=existing.workspace_id,
                graph_id=existing.graph_id,
                bucket=existing.bucket,
                object_key=existing.object_key,
                storage_version=existing.storage_version,
                media_type=existing.media_type,
                byte_size=existing.byte_size,
                content_sha256=existing.content_sha256,
                classification=existing.classification,
            ),
            frozenset(str(value) for value in schema.get("entity_types", [])),
            frozenset(str(value) for value in schema.get("edge_types", [])),
        )

    async def persist_analysis_as_draft(
        self,
        *,
        analysis: KnowledgeSourceAnalysis,
        title: str,
        actor_id: UUID,
    ) -> UUID:
        await set_security_context(
            self._session,
            workspace_id=analysis.source.workspace_id,
            subject_id=actor_id,
        )
        source = (
            await self._session.scalars(
                select(KnowledgeSourceSnapshotModel)
                .where(
                    KnowledgeSourceSnapshotModel.workspace_id == analysis.source.workspace_id,
                    KnowledgeSourceSnapshotModel.id == analysis.source.snapshot_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        graph = (
            await self._session.scalars(
                select(GraphModel)
                .where(
                    GraphModel.workspace_id == analysis.source.workspace_id,
                    GraphModel.id == analysis.source.graph_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        if source is None or graph is None or source.state != "PENDING":
            raise ConflictError("The knowledge source is no longer available for analysis.")
        if (
            source.id != analysis.source.snapshot_id
            or source.workspace_id != analysis.source.workspace_id
            or source.graph_id != analysis.source.graph_id
            or source.bucket != analysis.source.bucket
            or source.object_key != analysis.source.object_key
            or source.storage_version != analysis.source.storage_version
            or source.media_type != analysis.source.media_type
            or source.byte_size != analysis.source.byte_size
            or source.classification != analysis.source.classification
            or source.content_sha256 != analysis.source.content_sha256
        ):
            raise ConflictError("The immutable knowledge source changed before persistence.")
        analysis.source.require_graph_envelope(
            graph_classification=graph.classification,
        )
        await require_governed_release_base(
            self._session,
            workspace_id=analysis.source.workspace_id,
            graph_id=analysis.source.graph_id,
            release_id=graph.active_release_id,
        )
        ontology = (
            await self._session.scalars(
                select(OntologyVersionModel)
                .where(
                    OntologyVersionModel.workspace_id == analysis.source.workspace_id,
                    OntologyVersionModel.graph_id == analysis.source.graph_id,
                    OntologyVersionModel.status == "ACTIVE",
                )
                .order_by(OntologyVersionModel.created_at.desc())
                .limit(1)
            )
        ).one_or_none()
        if ontology is None:
            raise ValidationError("The graph has no active ontology.")
        operations = KnowledgeSourcePipeline.to_typed_operations(analysis)
        if not operations:
            raise ValidationError("The model produced no typed knowledge proposal.")
        for operation in operations:
            operation.require_classification_ceiling(
                maximum_classification=graph.classification,
            )
        changeset_id = uuid7()
        self._session.add(
            ChangeSetModel(
                id=changeset_id,
                workspace_id=analysis.source.workspace_id,
                graph_id=analysis.source.graph_id,
                base_release_id=graph.active_release_id,
                ontology_version_id=ontology.id,
                title=title.strip()[:500],
                state="DRAFT",
                author_id=actor_id,
                version=1,
            )
        )
        self._session.add_all(
            [
                KnowledgeSourcePageModel(
                    workspace_id=analysis.source.workspace_id,
                    source_snapshot_id=analysis.source.snapshot_id,
                    page_number=page.page_number,
                    content_sha256=page.content_sha256,
                    content=page.text,
                )
                for page in analysis.pages
            ]
        )
        pages_by_number = {page.page_number: page for page in analysis.pages}
        self._session.add_all(
            [
                KnowledgePageEmbeddingModel(
                    id=uuid7(),
                    workspace_id=analysis.source.workspace_id,
                    source_snapshot_id=analysis.source.snapshot_id,
                    page_number=value.page_number,
                    provider=analysis.embeddings.binding.provider,
                    model_identity=analysis.embeddings.binding.model,
                    dimension=len(value.vector),
                    embedding=list(value.vector),
                    content_sha256=pages_by_number[value.page_number].content_sha256,
                )
                for value in analysis.embeddings.embeddings
            ]
        )
        self._session.add_all(
            [
                ChangeOperationModel(
                    id=uuid7(),
                    workspace_id=analysis.source.workspace_id,
                    changeset_id=changeset_id,
                    sequence=operation.sequence,
                    operation=operation.operation.value,
                    entity_kind=operation.entity_kind.value,
                    stable_entity_id=operation.stable_entity_id,
                    document=operation.document,
                    provenance=_provenance_document(operation),
                    confidence=operation.confidence,
                )
                for operation in operations
            ]
        )
        self._session.add(
            KnowledgeExtractionRunModel(
                id=uuid7(),
                workspace_id=analysis.source.workspace_id,
                graph_id=analysis.source.graph_id,
                source_snapshot_id=analysis.source.snapshot_id,
                proposed_changeset_id=changeset_id,
                state="SUCCEEDED",
                parser_config_hash=_PARSER_CONFIGURATION_HASH,
                embedding_binding=_binding_document(analysis.embeddings.binding),
                extraction_binding=_binding_document(analysis.extraction.binding),
                input_hash=analysis.source.content_sha256,
                output_hash=analysis.evidence_hash(),
                version=1,
            )
        )
        source.state = "ANALYZED"
        await self._session.commit()
        return changeset_id

    async def record_projection(self, *, receipt: ProjectionReceipt) -> None:
        release = await require_governed_release_base(
            self._session,
            workspace_id=receipt.workspace_id,
            graph_id=receipt.graph_id,
            release_id=receipt.release_id,
        )
        if (
            not receipt.verified
            or release is None
            or release.content_hash != receipt.release_hash
            or release.node_count != receipt.node_count
            or release.edge_count != receipt.edge_count
        ):
            raise ConflictError(
                "The Neo4j projection receipt does not match the governed canonical release."
            )
        verification_hash = canonical_json_hash(
            {
                "deployment_id": str(receipt.deployment_id),
                "edge_count": receipt.edge_count,
                "node_count": receipt.node_count,
                "release_hash": receipt.release_hash,
            }
        )
        self._session.add(
            ProjectionDeploymentModel(
                id=receipt.deployment_id,
                workspace_id=receipt.workspace_id,
                graph_id=receipt.graph_id,
                release_id=receipt.release_id,
                adapter="neo4j-bolt-shadow-v1",
                target_ref=f"neo4j://release/{receipt.release_id}",
                state="SHADOW_VERIFIED",
                content_hash=receipt.release_hash,
                verification_hash=verification_hash,
                node_count=receipt.node_count,
                edge_count=receipt.edge_count,
                verified_at=utc_now(),
            )
        )
        await self._session.commit()

    async def require_verified_projection(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        release_id: UUID,
        release_hash: str,
        node_count: int,
        edge_count: int,
    ) -> None:
        deployments = list(
            (
                await self._session.scalars(
                    select(ProjectionDeploymentModel)
                    .where(
                        ProjectionDeploymentModel.workspace_id == workspace_id,
                        ProjectionDeploymentModel.graph_id == graph_id,
                        ProjectionDeploymentModel.release_id == release_id,
                        ProjectionDeploymentModel.adapter == "neo4j-bolt-shadow-v1",
                        ProjectionDeploymentModel.target_ref == f"neo4j://release/{release_id}",
                        ProjectionDeploymentModel.content_hash == release_hash,
                        ProjectionDeploymentModel.node_count == node_count,
                        ProjectionDeploymentModel.edge_count == edge_count,
                        ProjectionDeploymentModel.state == "SHADOW_VERIFIED",
                        ProjectionDeploymentModel.verified_at.is_not(None),
                    )
                    .order_by(ProjectionDeploymentModel.created_at.desc())
                )
            ).all()
        )
        verified = any(
            deployment.verification_hash
            == canonical_json_hash(
                {
                    "deployment_id": str(deployment.id),
                    "edge_count": edge_count,
                    "node_count": node_count,
                    "release_hash": release_hash,
                }
            )
            for deployment in deployments
        )
        if not verified:
            raise ConflictError("The release has no verified Neo4j shadow projection.")

    async def record_success(self, *, record: GraphRagAuditRecord) -> None:
        await set_security_context(
            self._session,
            workspace_id=record.workspace_id,
            subject_id=record.actor_id,
        )
        self._session.add(
            KnowledgeGraphRagAuditModel(
                id=uuid7(),
                workspace_id=record.workspace_id,
                graph_id=record.graph_id,
                release_id=record.release_id,
                actor_id=record.actor_id,
                request_id=record.request_id,
                question_sha256=record.question_sha256,
                evidence_ids=list(record.evidence_ids),
                cited_evidence_ids=list(record.cited_evidence_ids),
                provider=record.binding.provider,
                model_identity=record.binding.model,
                prompt_version=record.binding.prompt_version,
                tool_schema_version=record.binding.tool_schema_version,
                configuration_source=record.binding.configuration_source,
                configuration_version=record.binding.configuration_version,
                configuration_hash=record.binding.configuration_hash,
                input_tokens=record.input_tokens,
                output_tokens=record.output_tokens,
            )
        )
        await self._session.commit()


class SqlSemanticSeedSelector:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        subject_id: UUID,
        embedding: KnowledgeEmbeddingProvider,
        binding: ModelBinding,
    ) -> None:
        self._session_factory = session_factory
        self._subject_id = subject_id
        self._embedding = embedding
        self._binding = binding

    async def select_seed_ids(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        release_id: UUID,
        question: str,
        maximum_classification: int,
        limit: int,
    ) -> tuple[UUID, ...]:
        question_batch = await self._embedding.embed_pages(
            pages=(PdfPage.create(page_number=1, text=question),),
            binding=self._binding,
        )
        if len(question_batch.embeddings) != 1:
            raise ValidationError("The question embedding provider returned an invalid batch.")
        question_vector = question_batch.embeddings[0].vector
        async with self._session_factory() as session:
            await set_security_context(
                session,
                workspace_id=workspace_id,
                subject_id=self._subject_id,
            )
            rows = (
                await session.execute(
                    select(KnowledgePageEmbeddingModel, KnowledgeSourceSnapshotModel)
                    .join(
                        KnowledgeSourceSnapshotModel,
                        KnowledgeSourceSnapshotModel.id
                        == KnowledgePageEmbeddingModel.source_snapshot_id,
                    )
                    .where(
                        KnowledgePageEmbeddingModel.workspace_id == workspace_id,
                        KnowledgeSourceSnapshotModel.graph_id == graph_id,
                        KnowledgePageEmbeddingModel.provider == self._binding.provider,
                        KnowledgePageEmbeddingModel.model_identity == self._binding.model,
                    )
                    .limit(2_000)
                )
            ).all()
            nodes = list(
                (
                    await session.scalars(
                        select(ReleaseNodeModel)
                        .where(
                            ReleaseNodeModel.workspace_id == workspace_id,
                            ReleaseNodeModel.release_id == release_id,
                            ReleaseNodeModel.classification <= maximum_classification,
                        )
                        .limit(2_000)
                    )
                ).all()
            )
        vectors: dict[tuple[str, int], tuple[float, ...]] = {}
        for embedding, source in rows:
            vector = tuple(float(value) for value in embedding.embedding)
            if len(vector) == len(question_vector):
                vectors[(source.content_sha256, embedding.page_number)] = vector
        scored: list[tuple[float, UUID]] = []
        for node in nodes:
            best: float | None = None
            for provenance in node.provenance:
                locator = str(provenance.get("source_locator", ""))
                version = str(provenance.get("source_version", ""))
                try:
                    page_number = int(locator.rsplit("#page=", maxsplit=1)[1])
                except (IndexError, ValueError):
                    continue
                candidate_vector = vectors.get((version, page_number))
                if candidate_vector is None:
                    continue
                score = self._cosine(question_vector, candidate_vector)
                best = score if best is None else max(best, score)
            if best is not None:
                scored.append((best, node.entity_id))
        scored.sort(key=lambda value: (-value[0], value[1].int))
        return tuple(entity_id for _, entity_id in scored[:limit])

    @staticmethod
    def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if not left_norm or not right_norm:
            return 0.0
        return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)
