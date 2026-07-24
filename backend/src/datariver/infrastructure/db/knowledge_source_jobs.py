from __future__ import annotations

import base64
import binascii
import hashlib
import json
import secrets
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.application.knowledge_source_job_contracts import (
    KnowledgeSourceJobClaim,
    KnowledgeSourceJobPage,
    KnowledgeSourceJobRecord,
    KnowledgeSourceJobResult,
)
from datariver.application.knowledge_source_job_ports import (
    KnowledgeSourceJobStore,
    KnowledgeSourceJobWorkerStore,
)
from datariver.application.services.knowledge_pipeline import KnowledgeSourcePipeline
from datariver.domain.authz import (
    Action,
    BuiltinPolicyEngine,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import (
    ConflictError,
    DomainEvent,
    ForbiddenError,
    ValidationError,
    canonical_json_hash,
    uuid7,
)
from datariver.domain.knowledge import GraphChangeOperation
from datariver.domain.knowledge_pipeline import (
    MAX_SOURCE_BYTES,
    KnowledgeSourceAnalysis,
    KnowledgeSourceSnapshot,
    ModelBinding,
)
from datariver.domain.knowledge_source_jobs import (
    KnowledgeSourceJobPins,
    KnowledgeSourceJobStage,
    KnowledgeSourceJobState,
)
from datariver.infrastructure.db.authz import subject_attributes_from_models
from datariver.infrastructure.db.governance import SqlIdempotencyStore, SqlOutboxWriter
from datariver.infrastructure.db.knowledge import require_governed_release_base
from datariver.infrastructure.db.models.authz import PolicyDecisionModel
from datariver.infrastructure.db.models.integration import ObjectManifestModel
from datariver.infrastructure.db.models.knowledge import (
    ChangeOperationModel,
    ChangeSetModel,
    GraphModel,
    KnowledgeExtractionRunModel,
    KnowledgePageEmbeddingModel,
    KnowledgeSourceAnalysisAttemptModel,
    KnowledgeSourceAnalysisEventModel,
    KnowledgeSourceAnalysisJobModel,
    KnowledgeSourcePageModel,
    KnowledgeSourceSnapshotModel,
    OntologyVersionModel,
)
from datariver.infrastructure.db.models.platform import (
    ExternalServiceProfileModel,
    ExternalServiceProfileVersionModel,
    SubjectModel,
    WorkspaceMembershipModel,
)
from datariver.infrastructure.db.rls import set_security_context

PARSER_CONFIGURATION_HASH = hashlib.sha256(b"pypdf-strict-page-aware-v1").hexdigest()
_ENQUEUE_OPERATION = "knowledge.source-analysis.enqueue"
_CANCEL_OPERATION = "knowledge.source-analysis.cancel"
MAX_ACTIVE_SOURCE_JOBS_PER_OWNER_GRAPH = 20
_TERMINAL_JOB_STATES = tuple(state.value for state in KnowledgeSourceJobState if state.terminal)
_CURSOR_KEYS = frozenset(
    {
        "v",
        "scope",
        "workspace_id",
        "graph_id",
        "actor_id",
        "state_rank",
        "created_at",
        "id",
    }
)


def knowledge_requester_authorization_hash(subject: SubjectAttributes) -> str:
    return canonical_json_hash(
        {
            "contract": "KNOWLEDGE_SOURCE_REQUESTER_AUTHORIZATION_V1",
            "subject_id": str(subject.subject_id),
            "workspace_id": str(subject.workspace_id),
            "active": subject.active,
            "department_id": (
                str(subject.department_id) if subject.department_id is not None else None
            ),
            "groups": sorted(subject.groups),
            "job_function": subject.job_function,
            "clearance": int(subject.clearance),
            "allowed_system_ids": sorted(str(value) for value in subject.allowed_system_ids),
            "allowed_domain_ids": sorted(str(value) for value in subject.allowed_domain_ids),
            "allowed_actions": sorted(value.value for value in subject.allowed_actions),
            "denied_actions": sorted(value.value for value in subject.denied_actions),
            "builtin_policy_version": BuiltinPolicyEngine.policy_version,
        }
    )


def _binding_hash(binding: ModelBinding) -> str:
    binding.validate()
    return canonical_json_hash(binding.to_document())


def _binding_from_document(document: dict[str, object]) -> ModelBinding:
    try:
        configuration_version_value = document.get("configuration_version")
        if configuration_version_value is not None and (
            not isinstance(configuration_version_value, int)
            or isinstance(configuration_version_value, bool)
        ):
            raise TypeError
        binding = ModelBinding(
            provider=str(document["provider"]),
            model=str(document["model"]),
            prompt_version=str(document["prompt_version"]),
            tool_schema_version=str(document["tool_schema_version"]),
            configuration_source=(
                str(document["configuration_source"])
                if document.get("configuration_source") is not None
                else None
            ),
            configuration_version=(
                configuration_version_value if configuration_version_value is not None else None
            ),
            configuration_hash=(
                str(document["configuration_hash"])
                if document.get("configuration_hash") is not None
                else None
            ),
        )
        binding.validate()
    except (KeyError, TypeError, ValueError, ValidationError) as error:
        raise ConflictError("The stored Knowledge model binding is invalid.") from error
    if binding.to_document() != document:
        raise ConflictError("The stored Knowledge model binding is not canonical.")
    return binding


async def _activated_binding_is_current(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    service_key: str,
    binding: ModelBinding,
) -> bool:
    if binding.configuration_source != "SYSTEM_CONFIGURATION":
        return binding.configuration_source == "DEPLOYMENT"
    if binding.configuration_version is None or binding.configuration_hash is None:
        return False
    row = (
        await session.execute(
            select(ExternalServiceProfileModel, ExternalServiceProfileVersionModel)
            .join(
                ExternalServiceProfileVersionModel,
                and_(
                    ExternalServiceProfileVersionModel.workspace_id
                    == ExternalServiceProfileModel.workspace_id,
                    ExternalServiceProfileVersionModel.profile_id == ExternalServiceProfileModel.id,
                    ExternalServiceProfileVersionModel.configuration_version
                    == ExternalServiceProfileModel.activated_version,
                ),
            )
            .where(
                ExternalServiceProfileModel.workspace_id == workspace_id,
                ExternalServiceProfileModel.service_key == service_key,
                ExternalServiceProfileModel.active.is_(True),
                ExternalServiceProfileModel.activated_version == binding.configuration_version,
                ExternalServiceProfileVersionModel.configuration_hash == binding.configuration_hash,
                ExternalServiceProfileVersionModel.test_status == "AVAILABLE",
            )
        )
    ).one_or_none()
    return row is not None


def _encode_cursor(
    *,
    workspace_id: UUID,
    graph_id: UUID,
    actor_id: UUID,
    state_rank: int,
    created_at: datetime,
    job_id: UUID,
) -> str:
    payload = json.dumps(
        {
            "v": 2,
            "scope": "knowledge-source-analysis-owner-list",
            "workspace_id": str(workspace_id),
            "graph_id": str(graph_id),
            "actor_id": str(actor_id),
            "state_rank": state_rank,
            "created_at": created_at.isoformat(),
            "id": str(job_id),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(
    cursor: str,
    *,
    workspace_id: UUID,
    graph_id: UUID,
    actor_id: UUID,
) -> tuple[int, datetime, UUID]:
    try:
        if not cursor or len(cursor) > 2_000:
            raise ValueError
        payload = base64.b64decode(
            cursor + "=" * (-len(cursor) % 4),
            altchars=b"-_",
            validate=True,
        )
        document = json.loads(payload)
        if (
            not isinstance(document, dict)
            or frozenset(document) != _CURSOR_KEYS
            or document["v"] != 2
            or document["scope"] != "knowledge-source-analysis-owner-list"
            or document["workspace_id"] != str(workspace_id)
            or document["graph_id"] != str(graph_id)
            or document["actor_id"] != str(actor_id)
        ):
            raise ValueError
        state_rank = int(document["state_rank"])
        created_at = datetime.fromisoformat(str(document["created_at"]))
        job_id = UUID(str(document["id"]))
        if (
            created_at.tzinfo is None
            or created_at.utcoffset() is None
            or state_rank not in {0, 1}
            or cursor
            != _encode_cursor(
                workspace_id=workspace_id,
                graph_id=graph_id,
                actor_id=actor_id,
                state_rank=state_rank,
                created_at=created_at,
                job_id=job_id,
            )
        ):
            raise ValueError
        return state_rank, created_at, job_id
    except (
        ValueError,
        TypeError,
        KeyError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        binascii.Error,
    ) as error:
        raise ValidationError(
            "The Knowledge source job cursor is stale or does not match this request."
        ) from error


class SqlKnowledgeSourceJobStore(KnowledgeSourceJobStore):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        upload_id: UUID,
        actor_id: UUID,
        title: str,
        request_hash: str,
        requester_authorization_hash: str,
        embedding_binding: ModelBinding,
        extraction_binding: ModelBinding,
        maximum_attempts: int,
        idempotency_key: str,
    ) -> KnowledgeSourceJobRecord:
        if not 1 <= maximum_attempts <= 20:
            raise ValidationError("The Knowledge source job attempt limit is invalid.")
        normalized_title = " ".join(title.split())
        if not normalized_title or len(normalized_title) > 500:
            raise ValidationError("The Knowledge source job title is invalid.")
        await set_security_context(
            self._session,
            workspace_id=workspace_id,
            subject_id=actor_id,
        )
        if not await _activated_binding_is_current(
            self._session,
            workspace_id=workspace_id,
            service_key="LLM_EMBEDDING",
            binding=embedding_binding,
        ) or not await _activated_binding_is_current(
            self._session,
            workspace_id=workspace_id,
            service_key="LLM_CHAT_MODEL",
            binding=extraction_binding,
        ):
            raise ConflictError(
                "The Knowledge model configuration is no longer the activated tested revision."
            )
        idempotency = SqlIdempotencyStore(self._session)
        await idempotency.acquire_key_lock(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=_ENQUEUE_OPERATION,
        )
        existing_result = await idempotency.get_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=_ENQUEUE_OPERATION,
        )
        if existing_result is not None:
            if (
                existing_result.request_hash != request_hash
                or str(existing_result.result.get("actor_id", "")) != str(actor_id)
                or str(existing_result.result.get("graph_id", "")) != str(graph_id)
                or str(existing_result.result.get("upload_id", "")) != str(upload_id)
            ):
                raise ConflictError(
                    "The idempotency key was reused with a different Knowledge source request."
                )
            existing_job = await self.get_owned(
                workspace_id=workspace_id,
                graph_id=graph_id,
                job_id=UUID(str(existing_result.result["job_id"])),
                actor_id=actor_id,
            )
            if existing_job is None:
                raise ConflictError("The idempotent Knowledge source job is unavailable.")
            return existing_job

        graph = (
            await self._session.scalars(
                select(GraphModel)
                .where(
                    GraphModel.workspace_id == workspace_id,
                    GraphModel.id == graph_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        manifest = (
            await self._session.scalars(
                select(ObjectManifestModel)
                .where(
                    ObjectManifestModel.workspace_id == workspace_id,
                    ObjectManifestModel.id == upload_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        if graph is None or manifest is None:
            raise ValidationError("The knowledge graph or source upload does not exist.")
        active_job_count = await self._session.scalar(
            select(func.count(KnowledgeSourceAnalysisJobModel.id)).where(
                KnowledgeSourceAnalysisJobModel.workspace_id == workspace_id,
                KnowledgeSourceAnalysisJobModel.graph_id == graph_id,
                KnowledgeSourceAnalysisJobModel.requested_by == actor_id,
                KnowledgeSourceAnalysisJobModel.state.not_in(_TERMINAL_JOB_STATES),
            )
        )
        if int(active_job_count or 0) >= MAX_ACTIVE_SOURCE_JOBS_PER_OWNER_GRAPH:
            raise ConflictError(
                "The owner already has the maximum number of active Knowledge source jobs."
            )
        if (
            manifest.state != "ACCEPTED"
            or manifest.owner_id != actor_id
            or manifest.mime != "application/pdf"
            or manifest.actual_sha256 != manifest.sha256
            or manifest.actual_size_bytes != manifest.size_bytes
            or not 0 < manifest.size_bytes <= MAX_SOURCE_BYTES
        ):
            raise ValidationError(
                "The source must be an integrity-verified accepted PDF upload within 50 MiB."
            )
        if manifest.classification > graph.classification:
            raise ValidationError(
                "The source classification exceeds the graph classification envelope."
            )
        if manifest.classification > int(Classification.INTERNAL):
            raise ValidationError(
                "The knowledge source classification is not eligible for this inference route."
            )
        base = await require_governed_release_base(
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
        prepared_at = await self._database_now()
        source = (
            await self._session.scalars(
                select(KnowledgeSourceSnapshotModel)
                .where(
                    KnowledgeSourceSnapshotModel.workspace_id == workspace_id,
                    KnowledgeSourceSnapshotModel.graph_id == graph_id,
                    KnowledgeSourceSnapshotModel.upload_id == upload_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        if source is not None and source.state == "ANALYZED":
            raise ConflictError("This immutable PDF source has already been analyzed.")
        if source is not None and (
            source.created_by != actor_id
            or source.bucket != manifest.bucket
            or source.object_key != manifest.object_key
            or source.storage_version != f"manifest-v{manifest.version}"
            or source.media_type != manifest.mime
            or source.byte_size != manifest.size_bytes
            or source.content_sha256 != manifest.sha256
            or source.classification != manifest.classification
        ):
            raise ConflictError("The existing Knowledge source snapshot is not reusable.")
        if source is None:
            source = KnowledgeSourceSnapshotModel(
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
            self._session.add(source)
            await self._session.flush((source,))
        existing_job_id = await self._session.scalar(
            select(KnowledgeSourceAnalysisJobModel.id).where(
                KnowledgeSourceAnalysisJobModel.workspace_id == workspace_id,
                KnowledgeSourceAnalysisJobModel.source_snapshot_id == source.id,
            )
        )
        if existing_job_id is not None:
            raise ConflictError("This immutable PDF source already has an analysis job.")

        pins = KnowledgeSourceJobPins(
            workspace_id=workspace_id,
            graph_id=graph_id,
            source_snapshot_id=source.id,
            upload_id=upload_id,
            source_storage_version=source.storage_version,
            source_content_sha256=source.content_sha256,
            source_classification=source.classification,
            graph_version=graph.version,
            base_release_id=base.id if base is not None else None,
            base_release_hash=base.content_hash if base is not None else None,
            ontology_version_id=ontology.id,
            ontology_checksum=ontology.checksum,
            parser_configuration_hash=PARSER_CONFIGURATION_HASH,
            embedding_binding=embedding_binding,
            extraction_binding=extraction_binding,
            prepared_at=prepared_at,
        )
        pins.validate()
        job_id = uuid7()
        job = KnowledgeSourceAnalysisJobModel(
            id=job_id,
            workspace_id=workspace_id,
            graph_id=graph_id,
            source_snapshot_id=source.id,
            requested_by=actor_id,
            title=normalized_title,
            request_hash=request_hash,
            requester_authorization_hash=requester_authorization_hash,
            source_storage_version=source.storage_version,
            source_content_sha256=source.content_sha256,
            source_classification=source.classification,
            graph_version=graph.version,
            base_kind="RELEASE" if base is not None else "EMPTY",
            base_release_id=base.id if base is not None else None,
            base_release_hash=base.content_hash if base is not None else None,
            ontology_version_id=ontology.id,
            ontology_checksum=ontology.checksum,
            parser_config_hash=PARSER_CONFIGURATION_HASH,
            embedding_binding=embedding_binding.to_document(),
            embedding_binding_hash=_binding_hash(embedding_binding),
            extraction_binding=extraction_binding.to_document(),
            extraction_binding_hash=_binding_hash(extraction_binding),
            pin_hash=pins.evidence_hash(),
            prepared_at=prepared_at,
            state=KnowledgeSourceJobState.QUEUED.value,
            stage=KnowledgeSourceJobStage.QUEUED.value,
            progress={},
            next_attempt_at=prepared_at,
            attempt_count=0,
            maximum_attempts=maximum_attempts,
            lease_epoch=0,
            lease_token_hash=None,
            lease_owner_fingerprint=None,
            lease_started_at=None,
            lease_expires_at=None,
            cancel_requested_by=None,
            cancel_requested_at=None,
            cancel_reason=None,
            result_changeset_id=None,
            result_evidence_hash=None,
            last_failure_code=None,
            completed_at=None,
            created_at=prepared_at,
            updated_at=prepared_at,
            version=1,
        )
        self._session.add(job)
        await self._append_event(
            job=job,
            attempt_id=None,
            event_type="QUEUED",
            actor_ref=f"subject:{actor_id}",
            reason_code=None,
            details={"pin_hash": job.pin_hash, "request_hash": request_hash},
            now=prepared_at,
        )
        event = DomainEvent.create(
            event_type="knowledge.source-analysis.queued.v1",
            aggregate_type="knowledge_source_analysis_job",
            aggregate_id=job_id,
            workspace_id=workspace_id,
            payload={
                "job_id": str(job_id),
                "graph_id": str(graph_id),
                "source_snapshot_id": str(source.id),
                "pin_hash": job.pin_hash,
                "state": job.state,
                "version": job.version,
            },
        )
        await SqlOutboxWriter(self._session).add_events((event,))
        await idempotency.save_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=_ENQUEUE_OPERATION,
            request_hash=request_hash,
            result={
                "job_id": str(job_id),
                "actor_id": str(actor_id),
                "graph_id": str(graph_id),
                "upload_id": str(upload_id),
            },
        )
        await self._session.flush()
        record = _record(job, source)
        await self._session.commit()
        return record

    async def get_owned(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        job_id: UUID,
        actor_id: UUID,
    ) -> KnowledgeSourceJobRecord | None:
        await set_security_context(
            self._session,
            workspace_id=workspace_id,
            subject_id=actor_id,
        )
        row = (
            await self._session.execute(
                select(KnowledgeSourceAnalysisJobModel, KnowledgeSourceSnapshotModel)
                .join(
                    KnowledgeSourceSnapshotModel,
                    and_(
                        KnowledgeSourceSnapshotModel.workspace_id
                        == KnowledgeSourceAnalysisJobModel.workspace_id,
                        KnowledgeSourceSnapshotModel.id
                        == KnowledgeSourceAnalysisJobModel.source_snapshot_id,
                    ),
                )
                .where(
                    KnowledgeSourceAnalysisJobModel.workspace_id == workspace_id,
                    KnowledgeSourceAnalysisJobModel.graph_id == graph_id,
                    KnowledgeSourceAnalysisJobModel.id == job_id,
                    KnowledgeSourceAnalysisJobModel.requested_by == actor_id,
                )
            )
        ).one_or_none()
        return _record(*row) if row is not None else None

    async def list_owned(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        actor_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> KnowledgeSourceJobPage:
        if not 1 <= limit <= 100:
            raise ValidationError("The Knowledge source job list limit is invalid.")
        await set_security_context(
            self._session,
            workspace_id=workspace_id,
            subject_id=actor_id,
        )
        state_rank = case(
            (
                KnowledgeSourceAnalysisJobModel.state.in_(_TERMINAL_JOB_STATES),
                1,
            ),
            else_=0,
        )
        statement = (
            select(KnowledgeSourceAnalysisJobModel, KnowledgeSourceSnapshotModel)
            .join(
                KnowledgeSourceSnapshotModel,
                and_(
                    KnowledgeSourceSnapshotModel.workspace_id
                    == KnowledgeSourceAnalysisJobModel.workspace_id,
                    KnowledgeSourceSnapshotModel.id
                    == KnowledgeSourceAnalysisJobModel.source_snapshot_id,
                ),
            )
            .where(
                KnowledgeSourceAnalysisJobModel.workspace_id == workspace_id,
                KnowledgeSourceAnalysisJobModel.graph_id == graph_id,
                KnowledgeSourceAnalysisJobModel.requested_by == actor_id,
            )
            .order_by(
                state_rank.asc(),
                KnowledgeSourceAnalysisJobModel.created_at.desc(),
                KnowledgeSourceAnalysisJobModel.id.desc(),
            )
            .limit(limit + 1)
        )
        if cursor is not None:
            before_state_rank, before_created_at, before_id = _decode_cursor(
                cursor,
                workspace_id=workspace_id,
                graph_id=graph_id,
                actor_id=actor_id,
            )
            statement = statement.where(
                or_(
                    state_rank > before_state_rank,
                    and_(
                        state_rank == before_state_rank,
                        or_(
                            KnowledgeSourceAnalysisJobModel.created_at < before_created_at,
                            and_(
                                KnowledgeSourceAnalysisJobModel.created_at == before_created_at,
                                KnowledgeSourceAnalysisJobModel.id < before_id,
                            ),
                        ),
                    ),
                )
            )
        rows = list((await self._session.execute(statement)).all())
        has_more = len(rows) > limit
        visible = rows[:limit]
        items = tuple(_record(*row) for row in visible)
        boundary = visible[-1][0] if has_more else None
        return KnowledgeSourceJobPage(
            items=items,
            next_cursor=(
                _encode_cursor(
                    workspace_id=workspace_id,
                    graph_id=graph_id,
                    actor_id=actor_id,
                    state_rank=(1 if boundary.state in _TERMINAL_JOB_STATES else 0),
                    created_at=boundary.created_at,
                    job_id=boundary.id,
                )
                if boundary is not None
                else None
            ),
        )

    async def cancel(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        job_id: UUID,
        actor_id: UUID,
        expected_version: int,
        reason: str,
        request_hash: str,
        idempotency_key: str,
    ) -> KnowledgeSourceJobRecord:
        normalized_reason = " ".join(reason.split())
        if not normalized_reason or len(normalized_reason) > 1_000:
            raise ValidationError("The Knowledge source cancellation reason is invalid.")
        await set_security_context(
            self._session,
            workspace_id=workspace_id,
            subject_id=actor_id,
        )
        idempotency = SqlIdempotencyStore(self._session)
        await idempotency.acquire_key_lock(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=_CANCEL_OPERATION,
        )
        existing_result = await idempotency.get_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=_CANCEL_OPERATION,
        )
        if existing_result is not None:
            if (
                existing_result.request_hash != request_hash
                or str(existing_result.result.get("actor_id", "")) != str(actor_id)
                or str(existing_result.result.get("job_id", "")) != str(job_id)
            ):
                raise ConflictError("The idempotency key was reused with a different cancellation.")
            record = await self.get_owned(
                workspace_id=workspace_id,
                graph_id=graph_id,
                job_id=job_id,
                actor_id=actor_id,
            )
            if record is None:
                raise ConflictError("The idempotent Knowledge source job is unavailable.")
            return record
        row = (
            await self._session.execute(
                select(KnowledgeSourceAnalysisJobModel, KnowledgeSourceSnapshotModel)
                .join(
                    KnowledgeSourceSnapshotModel,
                    and_(
                        KnowledgeSourceSnapshotModel.workspace_id
                        == KnowledgeSourceAnalysisJobModel.workspace_id,
                        KnowledgeSourceSnapshotModel.id
                        == KnowledgeSourceAnalysisJobModel.source_snapshot_id,
                    ),
                )
                .where(
                    KnowledgeSourceAnalysisJobModel.workspace_id == workspace_id,
                    KnowledgeSourceAnalysisJobModel.graph_id == graph_id,
                    KnowledgeSourceAnalysisJobModel.id == job_id,
                    KnowledgeSourceAnalysisJobModel.requested_by == actor_id,
                )
                .with_for_update(of=KnowledgeSourceAnalysisJobModel)
            )
        ).one_or_none()
        if row is None:
            raise ForbiddenError("The Knowledge source job is unavailable.")
        job, source = row
        if job.version != expected_version:
            raise ConflictError("The Knowledge source job version changed.")
        state = KnowledgeSourceJobState(job.state)
        if state.terminal:
            raise ConflictError("A terminal Knowledge source job cannot be cancelled.")
        now = await self._database_now()
        job.cancel_requested_by = actor_id
        job.cancel_requested_at = now
        job.cancel_reason = normalized_reason
        if state in {KnowledgeSourceJobState.QUEUED, KnowledgeSourceJobState.RETRY_WAIT}:
            job.state = KnowledgeSourceJobState.CANCELLED.value
            job.stage = KnowledgeSourceJobStage.COMPLETED.value
            job.completed_at = now
            event_type = "CANCELLED"
        else:
            job.state = KnowledgeSourceJobState.CANCEL_REQUESTED.value
            event_type = "CANCEL_REQUESTED"
        job.version += 1
        job.updated_at = now
        await self._append_event(
            job=job,
            attempt_id=None,
            event_type=event_type,
            actor_ref=f"subject:{actor_id}",
            reason_code="USER_REQUEST",
            details={},
            now=now,
        )
        await SqlOutboxWriter(self._session).add_events(
            (
                DomainEvent.create(
                    event_type=f"knowledge.source-analysis.{event_type.lower()}.v1",
                    aggregate_type="knowledge_source_analysis_job",
                    aggregate_id=job.id,
                    workspace_id=workspace_id,
                    payload={
                        "job_id": str(job.id),
                        "graph_id": str(job.graph_id),
                        "state": job.state,
                        "version": job.version,
                    },
                ),
            )
        )
        await idempotency.save_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=_CANCEL_OPERATION,
            request_hash=request_hash,
            result={"job_id": str(job.id), "actor_id": str(actor_id)},
        )
        await self._session.flush()
        record = _record(job, source)
        await self._session.commit()
        return record

    async def _append_event(
        self,
        *,
        job: KnowledgeSourceAnalysisJobModel,
        attempt_id: UUID | None,
        event_type: str,
        actor_ref: str,
        reason_code: str | None,
        details: dict[str, object],
        now: datetime,
    ) -> None:
        sequence = (
            await self._session.scalar(
                select(func.max(KnowledgeSourceAnalysisEventModel.sequence)).where(
                    KnowledgeSourceAnalysisEventModel.workspace_id == job.workspace_id,
                    KnowledgeSourceAnalysisEventModel.job_id == job.id,
                )
            )
            or 0
        ) + 1
        evidence_hash = canonical_json_hash(
            {
                "job_id": str(job.id),
                "sequence": sequence,
                "attempt_id": str(attempt_id) if attempt_id is not None else None,
                "event_type": event_type,
                "actor_ref": actor_ref,
                "reason_code": reason_code,
                "details": details,
                "occurred_at": now.isoformat(),
            }
        )
        self._session.add(
            KnowledgeSourceAnalysisEventModel(
                id=uuid7(),
                workspace_id=job.workspace_id,
                job_id=job.id,
                sequence=sequence,
                attempt_id=attempt_id,
                event_type=event_type,
                actor_ref=actor_ref,
                reason_code=reason_code,
                evidence_hash=evidence_hash,
                details=details,
                occurred_at=now,
            )
        )

    async def _database_now(self) -> datetime:
        value = await self._session.scalar(select(func.clock_timestamp()))
        if not isinstance(value, datetime):
            raise RuntimeError("The database clock is unavailable.")
        return value


class SqlKnowledgeSourceJobWorkerStore(KnowledgeSourceJobWorkerStore):
    """Fenced worker persistence is implemented below the API-owned submission store."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        worker_subject_id: UUID,
    ) -> None:
        self._session_factory = session_factory
        self._worker_subject_id = worker_subject_id

    async def claim_next(
        self,
        *,
        worker_fingerprint: str,
        lease_seconds: int,
        maximum_attempts: int,
    ) -> KnowledgeSourceJobClaim | None:
        if (
            not worker_fingerprint
            or len(worker_fingerprint) > 255
            or any(character in worker_fingerprint for character in "\r\n\x00")
            or not 30 <= lease_seconds <= 3_600
            or not 1 <= maximum_attempts <= 20
        ):
            raise ValueError("The Knowledge source worker claim settings are invalid.")
        async with self._session_factory() as discovery:
            workspace_ids = tuple(
                UUID(str(value))
                for value in (
                    await discovery.scalars(
                        select(func.knowledge.list_knowledge_worker_workspaces()).limit(10_000)
                    )
                ).all()
            )
        for workspace_id in workspace_ids:
            recovered = await self._recover_one_expired(
                workspace_id=workspace_id,
                maximum_attempts=maximum_attempts,
            )
            if recovered:
                continue
            claim = await self._claim_in_workspace(
                workspace_id=workspace_id,
                worker_fingerprint=worker_fingerprint,
                lease_seconds=lease_seconds,
                maximum_attempts=maximum_attempts,
            )
            if claim is not None:
                return claim
        return None

    async def renew(
        self,
        *,
        claim: KnowledgeSourceJobClaim,
        lease_seconds: int,
        stage: str,
        progress: dict[str, int],
    ) -> datetime:
        try:
            stage_value = KnowledgeSourceJobStage(stage)
        except ValueError as error:
            raise ValidationError("The Knowledge source job stage is invalid.") from error
        if stage_value in {KnowledgeSourceJobStage.QUEUED, KnowledgeSourceJobStage.COMPLETED}:
            raise ValidationError("The Knowledge source job cannot renew at this stage.")
        bounded_progress = _bounded_progress(progress)
        async with self._session_factory() as session, session.begin():
            locked = await self._locked_claim(
                session=session,
                claim=claim,
                allow_cancel_requested=False,
            )
            if locked is None:
                raise ConflictError(
                    "The Knowledge source job lease is no longer current.",
                    details={"code": "LEASE_SUPERSEDED", "retryable": False},
                )
            job, attempt, _, now = locked
            await self._set_raw_lease_token(session, claim.lease_token, job_id=claim.job.job_id)
            job.stage = stage_value.value
            job.progress = bounded_progress
            job.lease_expires_at = now + timedelta(seconds=lease_seconds)
            job.updated_at = now
            job.version += 1
            attempt.stage = stage_value.value
            await self._append_worker_event(
                session=session,
                job=job,
                attempt_id=attempt.id,
                event_type="LEASE_RENEWED",
                actor_ref=f"worker:{claim.worker_fingerprint}",
                reason_code=None,
                details={"stage": stage_value.value, "progress": bounded_progress},
                now=now,
            )
            assert job.lease_expires_at is not None
            return job.lease_expires_at

    async def ensure_current(
        self,
        *,
        claim: KnowledgeSourceJobClaim,
        current_embedding_binding: ModelBinding,
        current_extraction_binding: ModelBinding,
    ) -> str | None:
        async with self._session_factory() as session, session.begin():
            locked = await self._locked_claim(
                session=session,
                claim=claim,
                allow_cancel_requested=True,
            )
            if locked is None:
                raise ConflictError(
                    "The Knowledge source job lease is no longer current.",
                    details={"code": "LEASE_SUPERSEDED", "retryable": False},
                )
            job, _, source, now = locked
            if job.state == KnowledgeSourceJobState.CANCEL_REQUESTED.value:
                raise ConflictError(
                    "Knowledge source job cancellation was requested.",
                    details={"code": "CANCEL_REQUESTED", "retryable": False},
                )
            return await self._preflight_drift_code(
                session=session,
                job=job,
                source=source,
                current_embedding_binding=current_embedding_binding,
                current_extraction_binding=current_extraction_binding,
                now=now,
                record_decision=False,
            )

    async def mark_cancelled(self, *, claim: KnowledgeSourceJobClaim) -> None:
        async with self._session_factory() as session, session.begin():
            locked = await self._locked_claim(
                session=session,
                claim=claim,
                allow_cancel_requested=True,
            )
            if locked is None:
                return
            job, attempt, _, now = locked
            if job.state != KnowledgeSourceJobState.CANCEL_REQUESTED.value:
                raise ConflictError("The Knowledge source job has no cancellation request.")
            await self._set_raw_lease_token(session, claim.lease_token, job_id=claim.job.job_id)
            attempt.state = "CANCELLED"
            attempt.stage = KnowledgeSourceJobStage.COMPLETED.value
            attempt.finished_at = now
            await session.flush()
            _clear_lease(job)
            job.state = KnowledgeSourceJobState.CANCELLED.value
            job.stage = KnowledgeSourceJobStage.COMPLETED.value
            job.completed_at = now
            job.updated_at = now
            job.version += 1
            await self._append_worker_event(
                session=session,
                job=job,
                attempt_id=attempt.id,
                event_type="CANCELLED",
                actor_ref=f"worker:{claim.worker_fingerprint}",
                reason_code="USER_REQUEST",
                details={},
                now=now,
            )
            await self._write_worker_outbox(
                session=session,
                job=job,
                event_type="knowledge.source-analysis.cancelled.v1",
            )

    async def mark_failed(
        self,
        *,
        claim: KnowledgeSourceJobClaim,
        failure_code: str,
        retryable: bool,
    ) -> None:
        normalized_code = _failure_code(failure_code)
        async with self._session_factory() as session, session.begin():
            locked = await self._locked_claim(
                session=session,
                claim=claim,
                allow_cancel_requested=True,
            )
            if locked is None:
                return
            job, attempt, _, now = locked
            if job.state == KnowledgeSourceJobState.CANCEL_REQUESTED.value:
                await self._set_raw_lease_token(session, claim.lease_token, job_id=claim.job.job_id)
                attempt.state = "CANCELLED"
                attempt.stage = KnowledgeSourceJobStage.COMPLETED.value
                attempt.finished_at = now
                await session.flush()
                _clear_lease(job)
                job.state = KnowledgeSourceJobState.CANCELLED.value
                job.stage = KnowledgeSourceJobStage.COMPLETED.value
                job.completed_at = now
                job.updated_at = now
                job.version += 1
                await self._append_worker_event(
                    session=session,
                    job=job,
                    attempt_id=attempt.id,
                    event_type="CANCELLED",
                    actor_ref=f"worker:{claim.worker_fingerprint}",
                    reason_code="USER_REQUEST",
                    details={},
                    now=now,
                )
                await self._write_worker_outbox(
                    session=session,
                    job=job,
                    event_type="knowledge.source-analysis.cancelled.v1",
                )
                return
            await self._set_raw_lease_token(session, claim.lease_token, job_id=claim.job.job_id)
            attempt.state = "FAILED"
            attempt.retryable = retryable
            attempt.failure_code = normalized_code
            attempt.stage = KnowledgeSourceJobStage.COMPLETED.value
            attempt.finished_at = now
            await session.flush()
            _clear_lease(job)
            if retryable and job.attempt_count < job.maximum_attempts:
                job.state = KnowledgeSourceJobState.RETRY_WAIT.value
                job.stage = KnowledgeSourceJobStage.QUEUED.value
                job.next_attempt_at = now + timedelta(
                    seconds=min(2 ** min(job.attempt_count, 6), 60)
                )
                job.completed_at = None
                event_type = "RETRY_WAIT"
            else:
                job.state = KnowledgeSourceJobState.FAILED.value
                job.stage = KnowledgeSourceJobStage.COMPLETED.value
                job.completed_at = now
                event_type = "FAILED"
            job.last_failure_code = normalized_code
            job.updated_at = now
            job.version += 1
            await self._append_worker_event(
                session=session,
                job=job,
                attempt_id=attempt.id,
                event_type=event_type,
                actor_ref=f"worker:{claim.worker_fingerprint}",
                reason_code=normalized_code,
                details={"retryable": retryable},
                now=now,
            )
            await self._write_worker_outbox(
                session=session,
                job=job,
                event_type=f"knowledge.source-analysis.{event_type.lower()}.v1",
            )

    async def mark_stale(
        self,
        *,
        claim: KnowledgeSourceJobClaim,
        failure_code: str,
    ) -> None:
        normalized_code = _failure_code(failure_code)
        if not normalized_code.startswith("STALE_"):
            raise ValueError("A stale Knowledge source failure code must start with STALE_.")
        async with self._session_factory() as session, session.begin():
            locked = await self._locked_claim(
                session=session,
                claim=claim,
                allow_cancel_requested=True,
            )
            if locked is None:
                return
            job, attempt, _, now = locked
            if job.state == KnowledgeSourceJobState.CANCEL_REQUESTED.value:
                await self._set_raw_lease_token(session, claim.lease_token, job_id=claim.job.job_id)
                attempt.state = "CANCELLED"
                attempt.stage = KnowledgeSourceJobStage.COMPLETED.value
                attempt.finished_at = now
                await session.flush()
                _clear_lease(job)
                job.state = KnowledgeSourceJobState.CANCELLED.value
                job.stage = KnowledgeSourceJobStage.COMPLETED.value
                job.completed_at = now
                job.updated_at = now
                job.version += 1
                await self._append_worker_event(
                    session=session,
                    job=job,
                    attempt_id=attempt.id,
                    event_type="CANCELLED",
                    actor_ref=f"worker:{claim.worker_fingerprint}",
                    reason_code="USER_REQUEST",
                    details={},
                    now=now,
                )
                await self._write_worker_outbox(
                    session=session,
                    job=job,
                    event_type="knowledge.source-analysis.cancelled.v1",
                )
                return
            await self._set_raw_lease_token(session, claim.lease_token, job_id=claim.job.job_id)
            attempt.state = "STALE"
            attempt.failure_code = normalized_code
            attempt.stage = KnowledgeSourceJobStage.COMPLETED.value
            attempt.finished_at = now
            await session.flush()
            _clear_lease(job)
            job.state = KnowledgeSourceJobState.STALE.value
            job.stage = KnowledgeSourceJobStage.COMPLETED.value
            job.last_failure_code = normalized_code
            job.completed_at = now
            job.updated_at = now
            job.version += 1
            await self._append_worker_event(
                session=session,
                job=job,
                attempt_id=attempt.id,
                event_type="STALE",
                actor_ref=f"worker:{claim.worker_fingerprint}",
                reason_code=normalized_code,
                details={},
                now=now,
            )
            await self._write_worker_outbox(
                session=session,
                job=job,
                event_type="knowledge.source-analysis.stale.v1",
            )

    async def finalize(
        self,
        *,
        claim: KnowledgeSourceJobClaim,
        analysis: KnowledgeSourceAnalysis,
        current_embedding_binding: ModelBinding,
        current_extraction_binding: ModelBinding,
    ) -> KnowledgeSourceJobRecord:
        operations = KnowledgeSourcePipeline.to_typed_operations(analysis)
        if not operations:
            raise ValidationError("The model produced no typed knowledge proposal.")
        if len(operations) > 10_000:
            raise ValidationError("The Knowledge source proposal exceeds the operation limit.")
        async with self._session_factory() as session, session.begin():
            locked = await self._locked_claim(
                session=session,
                claim=claim,
                allow_cancel_requested=True,
            )
            if locked is None:
                raise ConflictError(
                    "The Knowledge source job lease is no longer current.",
                    details={"code": "LEASE_SUPERSEDED", "retryable": False},
                )
            job, attempt, source, now = locked
            if job.state == KnowledgeSourceJobState.CANCEL_REQUESTED.value:
                await self._set_raw_lease_token(session, claim.lease_token, job_id=claim.job.job_id)
                attempt.state = "CANCELLED"
                attempt.stage = KnowledgeSourceJobStage.COMPLETED.value
                attempt.finished_at = now
                await session.flush()
                _clear_lease(job)
                job.state = KnowledgeSourceJobState.CANCELLED.value
                job.stage = KnowledgeSourceJobStage.COMPLETED.value
                job.completed_at = now
                job.updated_at = now
                job.version += 1
                await self._append_worker_event(
                    session=session,
                    job=job,
                    attempt_id=attempt.id,
                    event_type="CANCELLED",
                    actor_ref=f"worker:{claim.worker_fingerprint}",
                    reason_code="USER_REQUEST",
                    details={},
                    now=now,
                )
                await self._write_worker_outbox(
                    session=session,
                    job=job,
                    event_type="knowledge.source-analysis.cancelled.v1",
                )
                return _record(job, source)
            await self._set_raw_lease_token(session, claim.lease_token, job_id=claim.job.job_id)
            await session.scalar(select(func.knowledge.lock_source_analysis_finalization()))
            drift_code = await self._binding_drift_code(
                session=session,
                job=job,
                source=source,
                analysis=analysis,
                current_embedding_binding=current_embedding_binding,
                current_extraction_binding=current_extraction_binding,
                now=now,
            )
            if drift_code is not None:
                attempt.state = "STALE"
                attempt.failure_code = drift_code
                attempt.stage = KnowledgeSourceJobStage.COMPLETED.value
                attempt.finished_at = now
                await session.flush()
                _clear_lease(job)
                job.state = KnowledgeSourceJobState.STALE.value
                job.stage = KnowledgeSourceJobStage.COMPLETED.value
                job.last_failure_code = drift_code
                job.completed_at = now
                job.updated_at = now
                job.version += 1
                await self._append_worker_event(
                    session=session,
                    job=job,
                    attempt_id=attempt.id,
                    event_type="STALE",
                    actor_ref=f"worker:{claim.worker_fingerprint}",
                    reason_code=drift_code,
                    details={},
                    now=now,
                )
                await self._write_worker_outbox(
                    session=session,
                    job=job,
                    event_type="knowledge.source-analysis.stale.v1",
                )
                return _record(job, source)

            graph = await session.scalar(
                select(GraphModel).where(
                    GraphModel.workspace_id == job.workspace_id,
                    GraphModel.id == job.graph_id,
                )
            )
            if graph is None:
                raise ConflictError("The pinned Knowledge graph is unavailable.")
            for operation in operations:
                operation.require_classification_ceiling(
                    maximum_classification=graph.classification,
                )
            changeset_id = uuid7()
            changeset = ChangeSetModel(
                id=changeset_id,
                workspace_id=job.workspace_id,
                graph_id=job.graph_id,
                base_release_id=job.base_release_id,
                ontology_version_id=job.ontology_version_id,
                title=job.title,
                state="DRAFT",
                author_id=job.requested_by,
                source_analysis_job_id=job.id,
                version=1,
            )
            session.add(changeset)
            await session.flush((changeset,))
            page_models = [
                KnowledgeSourcePageModel(
                    workspace_id=job.workspace_id,
                    source_snapshot_id=source.id,
                    page_number=page.page_number,
                    content_sha256=page.content_sha256,
                    content=page.text,
                )
                for page in analysis.pages
            ]
            session.add_all(page_models)
            # Embeddings reference the page composite key, but these immutable
            # evidence models intentionally have no ORM relationship.  Flush the
            # parent rows explicitly so the database FK never depends on UOW order.
            await session.flush(page_models)
            pages_by_number = {page.page_number: page for page in analysis.pages}
            session.add_all(
                [
                    KnowledgePageEmbeddingModel(
                        id=uuid7(),
                        workspace_id=job.workspace_id,
                        source_snapshot_id=source.id,
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
            session.add_all(
                [
                    ChangeOperationModel(
                        id=uuid7(),
                        workspace_id=job.workspace_id,
                        changeset_id=changeset_id,
                        sequence=operation.sequence,
                        operation=operation.operation.value,
                        entity_kind=operation.entity_kind.value,
                        stable_entity_id=operation.stable_entity_id,
                        document=operation.document,
                        provenance=_provenance_documents(operation),
                        confidence=operation.confidence,
                    )
                    for operation in operations
                ]
            )
            result_hash = _durable_result_hash(
                pin_hash=job.pin_hash,
                analysis=analysis,
                operations=operations,
            )
            session.add(
                KnowledgeExtractionRunModel(
                    id=uuid7(),
                    workspace_id=job.workspace_id,
                    graph_id=job.graph_id,
                    source_snapshot_id=source.id,
                    proposed_changeset_id=changeset_id,
                    source_analysis_job_id=job.id,
                    source_analysis_attempt_id=attempt.id,
                    contract_version="DURABLE_SOURCE_V1",
                    state="SUCCEEDED",
                    parser_config_hash=job.parser_config_hash,
                    embedding_binding=analysis.embeddings.binding.to_document(),
                    extraction_binding=analysis.extraction.binding.to_document(),
                    input_hash=source.content_sha256,
                    output_hash=result_hash,
                    version=1,
                )
            )
            source.state = "ANALYZED"
            await session.flush()
            attempt.state = "SUCCEEDED"
            attempt.stage = KnowledgeSourceJobStage.COMPLETED.value
            attempt.output_hash = result_hash
            attempt.finished_at = now
            await session.flush()
            _clear_lease(job)
            job.state = KnowledgeSourceJobState.SUCCEEDED.value
            job.stage = KnowledgeSourceJobStage.COMPLETED.value
            job.progress = {
                "page_count": len(analysis.pages),
                "proposed_node_count": len(analysis.extraction.nodes),
                "proposed_edge_count": len(analysis.extraction.edges),
                "embedding_model": analysis.embeddings.binding.model,
                "extraction_model": analysis.extraction.binding.model,
            }
            job.result_changeset_id = changeset_id
            job.result_evidence_hash = result_hash
            job.last_failure_code = None
            job.completed_at = now
            job.updated_at = now
            job.version += 1
            await self._append_worker_event(
                session=session,
                job=job,
                attempt_id=attempt.id,
                event_type="SUCCEEDED",
                actor_ref=f"worker:{claim.worker_fingerprint}",
                reason_code=None,
                details={
                    "changeset_id": str(changeset_id),
                    "result_evidence_hash": result_hash,
                },
                now=now,
            )
            await self._write_worker_outbox(
                session=session,
                job=job,
                event_type="knowledge.source-analysis.succeeded.v1",
            )
            await session.flush()
            return _record(job, source)

    async def _claim_in_workspace(
        self,
        *,
        workspace_id: UUID,
        worker_fingerprint: str,
        lease_seconds: int,
        maximum_attempts: int,
    ) -> KnowledgeSourceJobClaim | None:
        async with self._session_factory() as session, session.begin():
            await set_security_context(
                session,
                workspace_id=workspace_id,
                subject_id=self._worker_subject_id,
            )
            now = await _database_now(session)
            job = await session.scalar(
                select(KnowledgeSourceAnalysisJobModel)
                .where(
                    KnowledgeSourceAnalysisJobModel.workspace_id == workspace_id,
                    KnowledgeSourceAnalysisJobModel.state.in_(
                        (
                            KnowledgeSourceJobState.QUEUED.value,
                            KnowledgeSourceJobState.RETRY_WAIT.value,
                        )
                    ),
                    KnowledgeSourceAnalysisJobModel.next_attempt_at <= now,
                    KnowledgeSourceAnalysisJobModel.attempt_count
                    < KnowledgeSourceAnalysisJobModel.maximum_attempts,
                    KnowledgeSourceAnalysisJobModel.attempt_count < maximum_attempts,
                )
                .order_by(
                    KnowledgeSourceAnalysisJobModel.next_attempt_at,
                    KnowledgeSourceAnalysisJobModel.created_at,
                    KnowledgeSourceAnalysisJobModel.id,
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job is None:
                return None
            raw_token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
            await self._set_raw_lease_token(session, raw_token, job_id=job.id)
            job.attempt_count += 1
            job.lease_epoch += 1
            job.state = KnowledgeSourceJobState.RUNNING.value
            job.stage = KnowledgeSourceJobStage.SOURCE_READ.value
            job.progress = {}
            job.next_attempt_at = now
            job.lease_token_hash = token_hash
            job.lease_owner_fingerprint = worker_fingerprint
            job.lease_started_at = now
            job.lease_expires_at = now + timedelta(seconds=lease_seconds)
            job.last_failure_code = None
            job.updated_at = now
            job.version += 1
            await session.flush()
            attempt = KnowledgeSourceAnalysisAttemptModel(
                id=uuid7(),
                workspace_id=workspace_id,
                job_id=job.id,
                attempt_no=job.attempt_count,
                lease_epoch=job.lease_epoch,
                lease_token_hash=token_hash,
                worker_fingerprint=worker_fingerprint,
                state="RUNNING",
                stage=KnowledgeSourceJobStage.SOURCE_READ.value,
                input_hash=job.pin_hash,
                output_hash=None,
                external_response_hash=None,
                retryable=False,
                failure_code=None,
                started_at=now,
                finished_at=None,
            )
            session.add(attempt)
            # Claim-scoped RLS intentionally hides source, manifest, identity,
            # graph and ontology rows until both the current job and attempt
            # have been durably staged with the exact raw-token hash. Any later
            # integrity failure rolls this transaction back to QUEUED.
            await session.flush()
            source = await session.scalar(
                select(KnowledgeSourceSnapshotModel)
                .where(
                    KnowledgeSourceSnapshotModel.workspace_id == workspace_id,
                    KnowledgeSourceSnapshotModel.id == job.source_snapshot_id,
                )
                .with_for_update()
            )
            ontology = await session.scalar(
                select(OntologyVersionModel).where(
                    OntologyVersionModel.workspace_id == workspace_id,
                    OntologyVersionModel.graph_id == job.graph_id,
                    OntologyVersionModel.id == job.ontology_version_id,
                )
            )
            if source is None or ontology is None:
                raise ConflictError(
                    "The queued Knowledge source job has broken foreign-key evidence.",
                    details={
                        "code": "PINNED_INPUT_INTEGRITY_ERROR",
                        "retryable": False,
                    },
                )
            await self._append_worker_event(
                session=session,
                job=job,
                attempt_id=attempt.id,
                event_type="CLAIMED",
                actor_ref=f"worker:{worker_fingerprint}",
                reason_code=None,
                details={"attempt_no": attempt.attempt_no, "lease_epoch": attempt.lease_epoch},
                now=now,
            )
            await session.flush()
            pins = _pins(job, source)
            if pins.evidence_hash() != job.pin_hash:
                raise ConflictError("The Knowledge source job pin evidence is corrupted.")
            schema = ontology.schema_document
            record = _record(job, source)
            return KnowledgeSourceJobClaim(
                job=record,
                pins=pins,
                source=_source_snapshot(source),
                entity_types=frozenset(str(value) for value in schema.get("entity_types", [])),
                edge_types=frozenset(str(value) for value in schema.get("edge_types", [])),
                attempt_id=attempt.id,
                attempt_no=attempt.attempt_no,
                lease_epoch=attempt.lease_epoch,
                worker_fingerprint=worker_fingerprint,
                lease_token=raw_token,
            )

    async def _recover_one_expired(
        self,
        *,
        workspace_id: UUID,
        maximum_attempts: int,
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            await set_security_context(
                session,
                workspace_id=workspace_id,
                subject_id=self._worker_subject_id,
            )
            now = await _database_now(session)
            job = await session.scalar(
                select(KnowledgeSourceAnalysisJobModel)
                .where(
                    KnowledgeSourceAnalysisJobModel.workspace_id == workspace_id,
                    KnowledgeSourceAnalysisJobModel.state.in_(
                        (
                            KnowledgeSourceJobState.RUNNING.value,
                            KnowledgeSourceJobState.CANCEL_REQUESTED.value,
                        )
                    ),
                    KnowledgeSourceAnalysisJobModel.lease_expires_at <= now,
                )
                .order_by(
                    KnowledgeSourceAnalysisJobModel.lease_expires_at,
                    KnowledgeSourceAnalysisJobModel.id,
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job is None:
                return False
            await self._set_job_scope(session, job_id=job.id)
            attempt = await session.scalar(
                select(KnowledgeSourceAnalysisAttemptModel)
                .where(
                    KnowledgeSourceAnalysisAttemptModel.workspace_id == workspace_id,
                    KnowledgeSourceAnalysisAttemptModel.job_id == job.id,
                    KnowledgeSourceAnalysisAttemptModel.lease_epoch == job.lease_epoch,
                    KnowledgeSourceAnalysisAttemptModel.state == "RUNNING",
                )
                .with_for_update()
            )
            if attempt is None:
                raise ConflictError("The expired Knowledge source job has no current attempt.")
            attempt.state = "SUPERSEDED"
            attempt.stage = KnowledgeSourceJobStage.COMPLETED.value
            attempt.failure_code = "LEASE_EXPIRED"
            attempt.finished_at = now
            await session.flush()
            _clear_lease(job)
            if job.state == KnowledgeSourceJobState.CANCEL_REQUESTED.value:
                job.state = KnowledgeSourceJobState.CANCELLED.value
                job.stage = KnowledgeSourceJobStage.COMPLETED.value
                job.completed_at = now
                event_type = "CANCELLED"
                reason = "CANCELLED_AFTER_LEASE_EXPIRY"
            elif job.attempt_count >= min(job.maximum_attempts, maximum_attempts):
                job.state = KnowledgeSourceJobState.FAILED.value
                job.stage = KnowledgeSourceJobStage.COMPLETED.value
                job.last_failure_code = "WORKER_LEASE_EXHAUSTED"
                job.completed_at = now
                event_type = "FAILED"
                reason = "WORKER_LEASE_EXHAUSTED"
            else:
                job.state = KnowledgeSourceJobState.RETRY_WAIT.value
                job.stage = KnowledgeSourceJobStage.QUEUED.value
                job.last_failure_code = "LEASE_EXPIRED"
                job.next_attempt_at = now + timedelta(
                    seconds=min(2 ** min(job.attempt_count, 6), 60)
                )
                event_type = "RETRY_WAIT"
                reason = "LEASE_EXPIRED"
            job.updated_at = now
            job.version += 1
            await self._append_worker_event(
                session=session,
                job=job,
                attempt_id=attempt.id,
                event_type=event_type,
                actor_ref="system:lease-recovery",
                reason_code=reason,
                details={"expired_lease_epoch": attempt.lease_epoch},
                now=now,
            )
            await self._write_worker_outbox(
                session=session,
                job=job,
                event_type=f"knowledge.source-analysis.{event_type.lower()}.v1",
            )
            return True

    async def _locked_claim(
        self,
        *,
        session: AsyncSession,
        claim: KnowledgeSourceJobClaim,
        allow_cancel_requested: bool,
    ) -> (
        tuple[
            KnowledgeSourceAnalysisJobModel,
            KnowledgeSourceAnalysisAttemptModel,
            KnowledgeSourceSnapshotModel,
            datetime,
        ]
        | None
    ):
        await set_security_context(
            session,
            workspace_id=claim.job.workspace_id,
            subject_id=self._worker_subject_id,
        )
        # Install only the opaque job id and raw token supplied by the already
        # fenced claim. Claim-scoped RLS independently verifies both against
        # the current live job/attempt before revealing any source or policy
        # row, so a forged GUC returns no scoped data.
        await self._set_raw_lease_token(
            session,
            claim.lease_token,
            job_id=claim.job.job_id,
        )
        now = await _database_now(session)
        job = await session.scalar(
            select(KnowledgeSourceAnalysisJobModel)
            .where(
                KnowledgeSourceAnalysisJobModel.workspace_id == claim.job.workspace_id,
                KnowledgeSourceAnalysisJobModel.id == claim.job.job_id,
            )
            .with_for_update()
        )
        attempt = await session.scalar(
            select(KnowledgeSourceAnalysisAttemptModel)
            .where(
                KnowledgeSourceAnalysisAttemptModel.workspace_id == claim.job.workspace_id,
                KnowledgeSourceAnalysisAttemptModel.id == claim.attempt_id,
            )
            .with_for_update()
        )
        source = await session.scalar(
            select(KnowledgeSourceSnapshotModel)
            .where(
                KnowledgeSourceSnapshotModel.workspace_id == claim.job.workspace_id,
                KnowledgeSourceSnapshotModel.id == claim.job.source_snapshot_id,
            )
            .with_for_update()
        )
        expected_token_hash = hashlib.sha256(claim.lease_token.encode()).hexdigest()
        permitted_states = {KnowledgeSourceJobState.RUNNING.value}
        if allow_cancel_requested:
            permitted_states.add(KnowledgeSourceJobState.CANCEL_REQUESTED.value)
        if (
            job is None
            or attempt is None
            or source is None
            or job.state not in permitted_states
            or job.attempt_count != claim.attempt_no
            or job.lease_epoch != claim.lease_epoch
            or job.lease_token_hash != expected_token_hash
            or job.lease_owner_fingerprint != claim.worker_fingerprint
            or job.lease_expires_at is None
            or job.lease_expires_at <= now
            or attempt.job_id != job.id
            or attempt.attempt_no != claim.attempt_no
            or attempt.lease_epoch != claim.lease_epoch
            or attempt.lease_token_hash != expected_token_hash
            or attempt.worker_fingerprint != claim.worker_fingerprint
            or attempt.state != "RUNNING"
        ):
            return None
        return job, attempt, source, now

    async def _binding_drift_code(
        self,
        *,
        session: AsyncSession,
        job: KnowledgeSourceAnalysisJobModel,
        source: KnowledgeSourceSnapshotModel,
        analysis: KnowledgeSourceAnalysis,
        current_embedding_binding: ModelBinding,
        current_extraction_binding: ModelBinding,
        now: datetime,
    ) -> str | None:
        if (
            analysis.embeddings.binding.to_document() != job.embedding_binding
            or analysis.extraction.binding.to_document() != job.extraction_binding
        ):
            return "STALE_MODEL_BINDING"
        if (
            analysis.source.snapshot_id != source.id
            or analysis.source.workspace_id != source.workspace_id
            or analysis.source.graph_id != source.graph_id
            or analysis.source.bucket != source.bucket
            or analysis.source.object_key != source.object_key
            or analysis.source.storage_version != source.storage_version
            or analysis.source.media_type != source.media_type
            or analysis.source.byte_size != source.byte_size
            or analysis.source.content_sha256 != source.content_sha256
            or analysis.source.classification != source.classification
        ):
            return "STALE_SOURCE_BINDING"
        return await self._preflight_drift_code(
            session=session,
            job=job,
            source=source,
            current_embedding_binding=current_embedding_binding,
            current_extraction_binding=current_extraction_binding,
            now=now,
            record_decision=True,
        )

    async def _preflight_drift_code(
        self,
        *,
        session: AsyncSession,
        job: KnowledgeSourceAnalysisJobModel,
        source: KnowledgeSourceSnapshotModel,
        current_embedding_binding: ModelBinding,
        current_extraction_binding: ModelBinding,
        now: datetime,
        record_decision: bool,
    ) -> str | None:
        if (
            _binding_hash(current_embedding_binding) != job.embedding_binding_hash
            or current_embedding_binding.to_document() != job.embedding_binding
            or _binding_hash(current_extraction_binding) != job.extraction_binding_hash
            or current_extraction_binding.to_document() != job.extraction_binding
        ):
            return "STALE_MODEL_BINDING"
        if not await _activated_binding_is_current(
            session,
            workspace_id=job.workspace_id,
            service_key="LLM_EMBEDDING",
            binding=current_embedding_binding,
        ) or not await _activated_binding_is_current(
            session,
            workspace_id=job.workspace_id,
            service_key="LLM_CHAT_MODEL",
            binding=current_extraction_binding,
        ):
            return "STALE_MODEL_CONFIGURATION"
        if (
            source.storage_version != job.source_storage_version
            or source.content_sha256 != job.source_content_sha256
            or source.classification != job.source_classification
            or source.state != "PENDING"
        ):
            return "STALE_SOURCE_BINDING"
        manifest = await session.scalar(
            select(ObjectManifestModel).where(
                ObjectManifestModel.workspace_id == job.workspace_id,
                ObjectManifestModel.id == source.upload_id,
            )
        )
        if (
            manifest is None
            or manifest.state != "ACCEPTED"
            or manifest.owner_id != job.requested_by
            or manifest.mime != source.media_type
            or manifest.bucket != source.bucket
            or manifest.object_key != source.object_key
            or f"manifest-v{manifest.version}" != source.storage_version
            or manifest.sha256 != source.content_sha256
            or manifest.actual_sha256 != source.content_sha256
            or manifest.size_bytes != source.byte_size
            or manifest.actual_size_bytes != source.byte_size
            or manifest.classification != source.classification
        ):
            return "STALE_SOURCE_MANIFEST"
        graph = await session.scalar(
            select(GraphModel).where(
                GraphModel.workspace_id == job.workspace_id,
                GraphModel.id == job.graph_id,
            )
        )
        if graph is None or graph.version != job.graph_version:
            return "STALE_GRAPH_VERSION"
        if graph.active_release_id != job.base_release_id:
            return "STALE_BASE_BINDING"
        try:
            base = await require_governed_release_base(
                session,
                workspace_id=job.workspace_id,
                graph_id=job.graph_id,
                release_id=graph.active_release_id,
            )
        except ConflictError:
            return "STALE_BASE_BINDING"
        if (job.base_kind == "EMPTY" and base is not None) or (
            job.base_kind == "RELEASE"
            and (
                base is None
                or base.id != job.base_release_id
                or base.content_hash != job.base_release_hash
            )
        ):
            return "STALE_BASE_BINDING"
        ontology = await session.scalar(
            select(OntologyVersionModel).where(
                OntologyVersionModel.workspace_id == job.workspace_id,
                OntologyVersionModel.graph_id == job.graph_id,
                OntologyVersionModel.id == job.ontology_version_id,
            )
        )
        active_ontology_id = await session.scalar(
            select(OntologyVersionModel.id)
            .where(
                OntologyVersionModel.workspace_id == job.workspace_id,
                OntologyVersionModel.graph_id == job.graph_id,
                OntologyVersionModel.status == "ACTIVE",
            )
            .order_by(OntologyVersionModel.created_at.desc())
            .limit(1)
        )
        if (
            ontology is None
            or ontology.status != "ACTIVE"
            or ontology.id != active_ontology_id
            or ontology.checksum != job.ontology_checksum
        ):
            return "STALE_ONTOLOGY_BINDING"
        row = (
            await session.execute(
                select(SubjectModel, WorkspaceMembershipModel)
                .join(
                    WorkspaceMembershipModel,
                    and_(
                        WorkspaceMembershipModel.subject_id == SubjectModel.id,
                        WorkspaceMembershipModel.workspace_id == job.workspace_id,
                    ),
                )
                .where(SubjectModel.id == job.requested_by)
            )
        ).one_or_none()
        if row is None:
            return "STALE_REQUESTER_AUTHORIZATION"
        try:
            subject = subject_attributes_from_models(
                subject=row[0],
                membership=row[1],
                observed_at=now,
            )
        except ForbiddenError:
            return "STALE_REQUESTER_AUTHORIZATION"
        if knowledge_requester_authorization_hash(subject) != job.requester_authorization_hash:
            return "STALE_REQUESTER_AUTHORIZATION"
        decision = BuiltinPolicyEngine().decide(
            subject=subject,
            resource=ResourceAttributes(
                resource_id=graph.id,
                workspace_id=graph.workspace_id,
                resource_type="knowledge_graph",
                owner_department_id=None,
                system_id=None,
                domain_id=None,
                classification=Classification(graph.classification),
                lifecycle=graph.status,
            ),
            action=Action.KG_EDIT,
            environment=EnvironmentAttributes(requested_at=now),
        )
        if record_decision:
            session.add(
                PolicyDecisionModel(
                    id=decision.decision_id,
                    workspace_id=job.workspace_id,
                    subject_id=job.requested_by,
                    resource_id=graph.id,
                    action=Action.KG_EDIT.value,
                    effect=decision.effect.value,
                    reason_codes=list(decision.reason_codes),
                    policy_versions=list(decision.policy_versions),
                    evaluation_context={
                        "kind": "knowledge_source_job_finalization",
                        "job_id": str(job.id),
                        "pin_hash": job.pin_hash,
                    },
                    request_id=str(job.id),
                    decided_at=now,
                )
            )
        if not decision.allowed:
            return "STALE_REQUESTER_AUTHORIZATION"
        if source.classification > graph.classification or source.classification > 1:
            return "STALE_CLASSIFICATION_ENVELOPE"
        return None

    async def _append_worker_event(
        self,
        *,
        session: AsyncSession,
        job: KnowledgeSourceAnalysisJobModel,
        attempt_id: UUID | None,
        event_type: str,
        actor_ref: str,
        reason_code: str | None,
        details: dict[str, object],
        now: datetime,
    ) -> None:
        sequence = (
            await session.scalar(
                select(func.max(KnowledgeSourceAnalysisEventModel.sequence)).where(
                    KnowledgeSourceAnalysisEventModel.workspace_id == job.workspace_id,
                    KnowledgeSourceAnalysisEventModel.job_id == job.id,
                )
            )
            or 0
        ) + 1
        evidence_hash = canonical_json_hash(
            {
                "job_id": str(job.id),
                "sequence": sequence,
                "attempt_id": str(attempt_id) if attempt_id is not None else None,
                "event_type": event_type,
                "actor_ref": actor_ref,
                "reason_code": reason_code,
                "details": details,
                "occurred_at": now.isoformat(),
            }
        )
        session.add(
            KnowledgeSourceAnalysisEventModel(
                id=uuid7(),
                workspace_id=job.workspace_id,
                job_id=job.id,
                sequence=sequence,
                attempt_id=attempt_id,
                event_type=event_type,
                actor_ref=actor_ref,
                reason_code=reason_code,
                evidence_hash=evidence_hash,
                details=details,
                occurred_at=now,
            )
        )

    async def _write_worker_outbox(
        self,
        *,
        session: AsyncSession,
        job: KnowledgeSourceAnalysisJobModel,
        event_type: str,
    ) -> None:
        await SqlOutboxWriter(session).add_events(
            (
                DomainEvent.create(
                    event_type=event_type,
                    aggregate_type="knowledge_source_analysis_job",
                    aggregate_id=job.id,
                    workspace_id=job.workspace_id,
                    payload={
                        "job_id": str(job.id),
                        "graph_id": str(job.graph_id),
                        "state": job.state,
                        "version": job.version,
                    },
                ),
            )
        )

    @staticmethod
    async def _set_raw_lease_token(
        session: AsyncSession,
        raw_token: str,
        *,
        job_id: UUID,
    ) -> None:
        await session.scalar(
            select(func.set_config("app.knowledge_source_lease_token", raw_token, True))
        )
        await session.scalar(
            select(
                func.set_config(
                    "app.knowledge_source_job_id",
                    str(job_id),
                    True,
                )
            )
        )

    @staticmethod
    async def _set_job_scope(
        session: AsyncSession,
        *,
        job_id: UUID,
    ) -> None:
        await session.scalar(
            select(
                func.set_config(
                    "app.knowledge_source_job_id",
                    str(job_id),
                    True,
                )
            )
        )


def _record(
    job: KnowledgeSourceAnalysisJobModel,
    source: KnowledgeSourceSnapshotModel,
) -> KnowledgeSourceJobRecord:
    result: KnowledgeSourceJobResult | None = None
    if job.state == KnowledgeSourceJobState.SUCCEEDED.value:
        progress = job.progress
        if job.result_changeset_id is None or job.result_evidence_hash is None:
            raise ConflictError("The successful Knowledge source job has incomplete evidence.")
        try:
            result = KnowledgeSourceJobResult(
                changeset_id=job.result_changeset_id,
                page_count=int(progress["page_count"]),
                proposed_node_count=int(progress["proposed_node_count"]),
                proposed_edge_count=int(progress["proposed_edge_count"]),
                evidence_hash=job.result_evidence_hash,
                embedding_model=str(progress["embedding_model"]),
                extraction_model=str(progress["extraction_model"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ConflictError("The successful Knowledge source job result is invalid.") from error
    progress_values = {
        key: value
        for key, value in job.progress.items()
        if key in {"completed_pages", "total_pages"} and isinstance(value, int)
    }
    return KnowledgeSourceJobRecord(
        job_id=job.id,
        workspace_id=job.workspace_id,
        graph_id=job.graph_id,
        source_snapshot_id=job.source_snapshot_id,
        upload_id=source.upload_id,
        requested_by=job.requested_by,
        title=job.title,
        state=KnowledgeSourceJobState(job.state),
        stage=KnowledgeSourceJobStage(job.stage),
        progress=progress_values,
        attempt_count=job.attempt_count,
        maximum_attempts=job.maximum_attempts,
        next_attempt_at=job.next_attempt_at,
        last_failure_code=job.last_failure_code,
        version=job.version,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
        result=result,
    )


def _source_snapshot(source: KnowledgeSourceSnapshotModel) -> KnowledgeSourceSnapshot:
    return KnowledgeSourceSnapshot(
        snapshot_id=source.id,
        workspace_id=source.workspace_id,
        graph_id=source.graph_id,
        bucket=source.bucket,
        object_key=source.object_key,
        storage_version=source.storage_version,
        media_type=source.media_type,
        byte_size=source.byte_size,
        content_sha256=source.content_sha256,
        classification=source.classification,
    )


def _pins(
    job: KnowledgeSourceAnalysisJobModel,
    source: KnowledgeSourceSnapshotModel,
) -> KnowledgeSourceJobPins:
    return KnowledgeSourceJobPins(
        workspace_id=job.workspace_id,
        graph_id=job.graph_id,
        source_snapshot_id=source.id,
        upload_id=source.upload_id,
        source_storage_version=job.source_storage_version,
        source_content_sha256=job.source_content_sha256,
        source_classification=job.source_classification,
        graph_version=job.graph_version,
        base_release_id=job.base_release_id,
        base_release_hash=job.base_release_hash,
        ontology_version_id=job.ontology_version_id,
        ontology_checksum=job.ontology_checksum,
        parser_configuration_hash=job.parser_config_hash,
        embedding_binding=_binding_from_document(job.embedding_binding),
        extraction_binding=_binding_from_document(job.extraction_binding),
        prepared_at=job.prepared_at,
    )


def _clear_lease(job: KnowledgeSourceAnalysisJobModel) -> None:
    job.lease_token_hash = None
    job.lease_owner_fingerprint = None
    job.lease_started_at = None
    job.lease_expires_at = None


def _bounded_progress(progress: dict[str, int]) -> dict[str, int]:
    if (
        len(progress) > 2
        or any(key not in {"completed_pages", "total_pages"} for key in progress)
        or any(
            not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 10_000
            for value in progress.values()
        )
        or (
            "completed_pages" in progress
            and "total_pages" in progress
            and progress["completed_pages"] > progress["total_pages"]
        )
    ):
        raise ValidationError("The Knowledge source job progress is invalid.")
    return dict(sorted(progress.items()))


def _failure_code(value: str) -> str:
    normalized = value.strip().upper()
    if (
        not normalized
        or len(normalized) > 100
        or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for character in normalized)
    ):
        raise ValueError("The Knowledge source job failure code is invalid.")
    return normalized


def _provenance_documents(operation: GraphChangeOperation) -> list[dict[str, object]]:
    return [value.to_document() for value in operation.provenance]


def _durable_result_hash(
    *,
    pin_hash: str,
    analysis: KnowledgeSourceAnalysis,
    operations: tuple[GraphChangeOperation, ...],
) -> str:
    return canonical_json_hash(
        {
            "contract": "DURABLE_KNOWLEDGE_SOURCE_RESULT_V1",
            "pin_hash": pin_hash,
            "analysis_hash": analysis.evidence_hash(),
            "operations": [
                {
                    "sequence": operation.sequence,
                    "operation": operation.operation.value,
                    "entity_kind": operation.entity_kind.value,
                    "stable_entity_id": str(operation.stable_entity_id),
                    "document": operation.document,
                    "provenance": _provenance_documents(operation),
                    "confidence": operation.confidence,
                }
                for operation in sorted(operations, key=lambda value: value.sequence)
            ],
        }
    )


async def _database_now(session: AsyncSession) -> datetime:
    value = await session.scalar(select(func.clock_timestamp()))
    if not isinstance(value, datetime):
        raise RuntimeError("The database clock is unavailable.")
    return value
