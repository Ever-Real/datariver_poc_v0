from __future__ import annotations

from datetime import timedelta
from types import TracebackType
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.application.dto import (
    CatalogMetadataCandidateEvidence,
    CatalogMetadataRowEvidenceRecord,
    ObjectMetadata,
    UploadPreparationReceiptEvidence,
    UploadRegistrationCandidateEvidence,
)
from datariver.application.ports import (
    CatalogMetadataCandidateReader,
    UploadCandidateReader,
    UploadCompletionStore,
    UploadPreparationRepository,
    UploadRepository,
    UploadUnitOfWork,
    UploadValidationStore,
)
from datariver.domain.authz import Classification
from datariver.domain.common import utc_now
from datariver.domain.registration import (
    CompletedUploadPart,
    UploadContentProfile,
    UploadManifest,
    UploadPreparation,
    UploadPreparationState,
    UploadState,
)
from datariver.infrastructure.db.governance import SqlIdempotencyStore, SqlOutboxWriter
from datariver.infrastructure.db.models.integration import (
    CatalogMetadataCandidateModel,
    CatalogMetadataCandidateRowModel,
    CatalogMetadataRowModel,
    ObjectManifestModel,
    UploadPreparationJobModel,
    UploadPreparationReceiptModel,
    UploadRegistrationCandidateModel,
)
from datariver.infrastructure.db.rls import set_security_context


class SqlUploadRepository(UploadRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tracked: dict[UUID, ObjectManifestModel] = {}

    async def add(self, manifest: UploadManifest) -> None:
        model = ObjectManifestModel(
            id=manifest.upload_id,
            workspace_id=manifest.workspace_id,
            bucket=manifest.bucket,
            object_key=manifest.object_key,
            display_name=manifest.display_name,
            multipart_upload_id=manifest.multipart_upload_id,
            size_bytes=manifest.declared_size_bytes,
            mime=manifest.declared_mime,
            sha256=manifest.declared_sha256,
            actual_size_bytes=manifest.actual_size_bytes,
            actual_mime=manifest.actual_mime,
            actual_sha256=manifest.actual_sha256,
            processing_lease_until=None,
            processing_attempts=manifest.processing_attempts,
            validation_attempts=manifest.validation_attempts,
            last_error_code=None,
            validation_summary=manifest.validation_summary,
            completion_parts=[],
            state=manifest.state.value,
            content_profile=manifest.content_profile.value,
            legacy_knowledge_source_eligible=False,
            knowledge_source_graph_id=manifest.knowledge_source_graph_id,
            classification=int(manifest.classification),
            owner_id=manifest.owner_id,
            retention_until=None,
            expires_at=manifest.expires_at,
            version=manifest.version,
        )
        self._session.add(model)
        self._tracked[manifest.upload_id] = model

    async def get_for_update(self, *, workspace_id: UUID, upload_id: UUID) -> UploadManifest | None:
        return await self._get(
            workspace_id=workspace_id,
            upload_id=upload_id,
            for_update=True,
        )

    async def get(self, *, workspace_id: UUID, upload_id: UUID) -> UploadManifest | None:
        return await self._get(
            workspace_id=workspace_id,
            upload_id=upload_id,
            for_update=False,
        )

    async def _get(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        for_update: bool,
    ) -> UploadManifest | None:
        statement = select(ObjectManifestModel).where(
            ObjectManifestModel.id == upload_id,
            ObjectManifestModel.workspace_id == workspace_id,
        )
        if for_update:
            statement = statement.with_for_update()
        model = (await self._session.scalars(statement)).one_or_none()
        if model is None or model.expires_at is None:
            return None
        if for_update:
            self._tracked[upload_id] = model
        return _to_domain(model)

    async def save(self, manifest: UploadManifest) -> None:
        model = self._tracked[manifest.upload_id]
        _apply_manifest(model, manifest)

    async def list(
        self,
        *,
        workspace_id: UUID,
        owner_id: UUID | None,
        maximum_classification: int,
        state: str | None,
        limit: int,
    ) -> list[UploadManifest]:
        statement = select(ObjectManifestModel.id).where(
            ObjectManifestModel.workspace_id == workspace_id,
            ObjectManifestModel.classification <= maximum_classification,
        )
        if owner_id is not None:
            statement = statement.where(ObjectManifestModel.owner_id == owner_id)
        if state is not None:
            statement = statement.where(ObjectManifestModel.state == state)
        ids = list(
            (
                await self._session.scalars(
                    statement.order_by(ObjectManifestModel.created_at.desc()).limit(limit)
                )
            ).all()
        )
        values: list[UploadManifest] = []
        for upload_id in ids:
            value = await self.get_for_update(workspace_id=workspace_id, upload_id=upload_id)
            if value is not None:
                values.append(value)
        return values


def _to_domain(model: ObjectManifestModel) -> UploadManifest:
    if model.expires_at is None:
        raise ValueError("An upload manifest must have an expiry timestamp.")
    return UploadManifest(
        upload_id=model.id,
        workspace_id=model.workspace_id,
        owner_id=model.owner_id,
        bucket=model.bucket,
        object_key=model.object_key,
        display_name=model.display_name,
        declared_size_bytes=model.size_bytes,
        declared_mime=model.mime,
        declared_sha256=model.sha256,
        classification=Classification(model.classification),
        multipart_upload_id=model.multipart_upload_id or "",
        expires_at=model.expires_at,
        content_profile=UploadContentProfile(model.content_profile),
        knowledge_source_graph_id=model.knowledge_source_graph_id,
        state=UploadState(model.state),
        version=model.version,
        completion_parts=[
            CompletedUploadPart(
                part_number=int(part["part_number"]),
                etag=str(part["etag"]),
                checksum_sha256=(
                    str(part["checksum_sha256"])
                    if part.get("checksum_sha256") is not None
                    else None
                ),
            )
            for part in model.completion_parts
        ],
        actual_size_bytes=model.actual_size_bytes,
        actual_mime=model.actual_mime,
        actual_sha256=model.actual_sha256,
        processing_attempts=model.processing_attempts,
        validation_attempts=model.validation_attempts,
        validation_summary=model.validation_summary,
        last_error_code=model.last_error_code,
        legacy_knowledge_source_eligible=model.legacy_knowledge_source_eligible,
    )


def _apply_manifest(model: ObjectManifestModel, manifest: UploadManifest) -> None:
    if (
        model.legacy_knowledge_source_eligible != manifest.legacy_knowledge_source_eligible
        or model.knowledge_source_graph_id != manifest.knowledge_source_graph_id
    ):
        raise ValueError("Server-owned Knowledge upload bindings are immutable.")
    model.state = manifest.state.value
    model.version = manifest.version
    model.actual_size_bytes = manifest.actual_size_bytes
    model.actual_mime = manifest.actual_mime
    model.actual_sha256 = manifest.actual_sha256
    model.processing_attempts = manifest.processing_attempts
    model.validation_attempts = manifest.validation_attempts
    model.validation_summary = manifest.validation_summary
    model.bucket = manifest.bucket
    model.object_key = manifest.object_key
    model.completion_parts = [
        {
            "part_number": part.part_number,
            "etag": part.etag,
            "checksum_sha256": part.checksum_sha256,
        }
        for part in manifest.completion_parts
    ]


class SqlUploadPreparationRepository(UploadPreparationRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, preparation: UploadPreparation) -> None:
        self._session.add(
            UploadPreparationJobModel(
                id=preparation.preparation_id,
                workspace_id=preparation.workspace_id,
                upload_id=preparation.upload_id,
                requested_by=preparation.requested_by,
                content_profile=preparation.content_profile.value,
                source_manifest_version=preparation.source_manifest_version,
                source_sha256=preparation.source_sha256,
                configuration_hash=preparation.configuration_hash,
                state=preparation.state.value,
                next_attempt_at=preparation.created_at,
                lease_token=None,
                lease_until=None,
                attempts=preparation.attempts,
                rows_processed=preparation.rows_processed,
                total_rows=preparation.total_rows,
                last_error_code=preparation.last_error_code,
                created_at=preparation.created_at,
                updated_at=preparation.updated_at,
                version=preparation.version,
            )
        )

    async def get(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        preparation_id: UUID,
    ) -> UploadPreparation | None:
        model = (
            await self._session.scalars(
                select(UploadPreparationJobModel).where(
                    UploadPreparationJobModel.id == preparation_id,
                    UploadPreparationJobModel.workspace_id == workspace_id,
                    UploadPreparationJobModel.upload_id == upload_id,
                )
            )
        ).one_or_none()
        return _to_preparation(model) if model is not None else None

    async def find_source_configuration(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        source_manifest_version: int,
        content_profile: str,
        configuration_hash: str,
    ) -> UploadPreparation | None:
        model = (
            await self._session.scalars(
                select(UploadPreparationJobModel).where(
                    UploadPreparationJobModel.workspace_id == workspace_id,
                    UploadPreparationJobModel.upload_id == upload_id,
                    UploadPreparationJobModel.source_manifest_version == source_manifest_version,
                    UploadPreparationJobModel.content_profile == content_profile,
                    UploadPreparationJobModel.configuration_hash == configuration_hash,
                )
            )
        ).one_or_none()
        return _to_preparation(model) if model is not None else None

    async def list(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        state: str | None,
        limit: int,
    ) -> list[UploadPreparation]:
        statement = select(UploadPreparationJobModel).where(
            UploadPreparationJobModel.workspace_id == workspace_id,
            UploadPreparationJobModel.upload_id == upload_id,
        )
        if state is not None:
            statement = statement.where(UploadPreparationJobModel.state == state)
        models = list(
            (
                await self._session.scalars(
                    statement.order_by(
                        UploadPreparationJobModel.created_at.desc(),
                        UploadPreparationJobModel.id.desc(),
                    ).limit(limit)
                )
            ).all()
        )
        return [_to_preparation(model) for model in models]


class SqlUploadCandidateReader(UploadCandidateReader):
    _V2 = "DATASET_DESCRIPTION_CANDIDATE_V2"

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_ready_receipt(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        preparation_id: UUID,
    ) -> UploadPreparationReceiptEvidence | None:
        candidates = UploadRegistrationCandidateModel
        candidate_stats = (
            select(
                candidates.receipt_id.label("receipt_id"),
                func.count(candidates.id).label("candidate_count"),
                func.min(candidates.ordinal).label("first_ordinal"),
                func.max(candidates.ordinal).label("last_ordinal"),
                func.count(candidates.id)
                .filter(candidates.evidence_version != self._V2)
                .label("legacy_candidate_count"),
            )
            .where(candidates.workspace_id == workspace_id)
            .group_by(candidates.receipt_id)
            .subquery()
        )
        receipts = UploadPreparationReceiptModel
        jobs = UploadPreparationJobModel
        statement = (
            select(
                receipts.id.label("receipt_id"),
                receipts.workspace_id,
                receipts.preparation_job_id.label("preparation_id"),
                receipts.upload_id,
                receipts.manifest_version,
                receipts.source_sha256,
                receipts.accepted_sha256,
                receipts.object_locator_hash,
                receipts.accepted_etag,
                receipts.accepted_version_id,
                receipts.content_profile,
                receipts.parser_version,
                receipts.scanner_version,
                receipts.schema_version,
                receipts.configuration_hash,
                receipts.item_count,
                receipts.rejected_count,
                receipts.candidate_root_hash,
                receipts.receipt_hash,
                receipts.observed_at,
                receipts.created_at,
                candidate_stats.c.candidate_count,
                candidate_stats.c.first_ordinal,
                candidate_stats.c.last_ordinal,
                candidate_stats.c.legacy_candidate_count,
            )
            .join(
                jobs,
                and_(
                    jobs.workspace_id == receipts.workspace_id,
                    jobs.id == receipts.preparation_job_id,
                    jobs.upload_id == receipts.upload_id,
                ),
            )
            .join(
                candidate_stats,
                candidate_stats.c.receipt_id == receipts.id,
            )
            .where(
                receipts.workspace_id == workspace_id,
                receipts.upload_id == upload_id,
                receipts.preparation_job_id == preparation_id,
                jobs.state == UploadPreparationState.READY.value,
            )
        )
        row = (await self._session.execute(statement)).mappings().one_or_none()
        if row is None:
            return None
        return UploadPreparationReceiptEvidence(
            receipt_id=row["receipt_id"],
            workspace_id=row["workspace_id"],
            preparation_id=row["preparation_id"],
            upload_id=row["upload_id"],
            manifest_version=row["manifest_version"],
            source_sha256=row["source_sha256"],
            accepted_sha256=row["accepted_sha256"],
            content_profile=row["content_profile"],
            parser_version=row["parser_version"],
            scanner_version=row["scanner_version"],
            schema_version=row["schema_version"],
            configuration_hash=row["configuration_hash"],
            item_count=row["item_count"],
            rejected_count=row["rejected_count"],
            candidate_root_hash=row["candidate_root_hash"],
            receipt_hash=row["receipt_hash"],
            observed_at=row["observed_at"],
            created_at=row["created_at"],
            candidate_count=row["candidate_count"],
            first_ordinal=row["first_ordinal"],
            last_ordinal=row["last_ordinal"],
            legacy_candidate_count=row["legacy_candidate_count"],
            object_locator_hash=row["object_locator_hash"],
            accepted_etag=row["accepted_etag"],
            accepted_version_id=row["accepted_version_id"],
        )

    async def get_candidate(
        self,
        *,
        workspace_id: UUID,
        receipt_id: UUID,
        candidate_id: UUID,
    ) -> UploadRegistrationCandidateEvidence | None:
        model = await self._session.scalar(
            select(UploadRegistrationCandidateModel).where(
                UploadRegistrationCandidateModel.workspace_id == workspace_id,
                UploadRegistrationCandidateModel.receipt_id == receipt_id,
                UploadRegistrationCandidateModel.id == candidate_id,
            )
        )
        return _to_candidate(model) if model is not None else None

    async def list_candidates(
        self,
        *,
        workspace_id: UUID,
        receipt_id: UUID,
        after_ordinal: int,
        limit: int,
    ) -> list[UploadRegistrationCandidateEvidence]:
        models = list(
            (
                await self._session.scalars(
                    select(UploadRegistrationCandidateModel)
                    .where(
                        UploadRegistrationCandidateModel.workspace_id == workspace_id,
                        UploadRegistrationCandidateModel.receipt_id == receipt_id,
                        UploadRegistrationCandidateModel.ordinal > after_ordinal,
                    )
                    .order_by(UploadRegistrationCandidateModel.ordinal.asc())
                    .limit(limit)
                )
            ).all()
        )
        return [_to_candidate(model) for model in models]


class SqlCatalogMetadataCandidateReader(CatalogMetadataCandidateReader):
    _V3 = "CATALOG_METADATA_CANDIDATE_V3"

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_ready_receipt(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        preparation_id: UUID,
    ) -> UploadPreparationReceiptEvidence | None:
        candidates = CatalogMetadataCandidateModel
        candidate_stats = (
            select(
                candidates.receipt_id.label("receipt_id"),
                func.count(candidates.id).label("candidate_count"),
                func.min(candidates.candidate_ordinal).label("first_ordinal"),
                func.max(candidates.candidate_ordinal).label("last_ordinal"),
                func.count(candidates.id)
                .filter(candidates.evidence_version != self._V3)
                .label("legacy_candidate_count"),
            )
            .where(candidates.workspace_id == workspace_id)
            .group_by(candidates.receipt_id)
            .subquery()
        )
        receipts = UploadPreparationReceiptModel
        jobs = UploadPreparationJobModel
        row = (
            (
                await self._session.execute(
                    select(
                        receipts.id.label("receipt_id"),
                        receipts.workspace_id,
                        receipts.preparation_job_id.label("preparation_id"),
                        receipts.upload_id,
                        receipts.manifest_version,
                        receipts.source_sha256,
                        receipts.accepted_sha256,
                        receipts.object_locator_hash,
                        receipts.accepted_etag,
                        receipts.accepted_version_id,
                        receipts.content_profile,
                        receipts.parser_version,
                        receipts.scanner_version,
                        receipts.schema_version,
                        receipts.configuration_hash,
                        receipts.item_count,
                        receipts.rejected_count,
                        receipts.candidate_root_hash,
                        receipts.receipt_hash,
                        receipts.observed_at,
                        receipts.created_at,
                        candidate_stats.c.candidate_count,
                        candidate_stats.c.first_ordinal,
                        candidate_stats.c.last_ordinal,
                        candidate_stats.c.legacy_candidate_count,
                    )
                    .join(
                        jobs,
                        and_(
                            jobs.workspace_id == receipts.workspace_id,
                            jobs.id == receipts.preparation_job_id,
                            jobs.upload_id == receipts.upload_id,
                        ),
                    )
                    .join(candidate_stats, candidate_stats.c.receipt_id == receipts.id)
                    .where(
                        receipts.workspace_id == workspace_id,
                        receipts.upload_id == upload_id,
                        receipts.preparation_job_id == preparation_id,
                        jobs.state == UploadPreparationState.READY.value,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return UploadPreparationReceiptEvidence(
            receipt_id=row["receipt_id"],
            workspace_id=row["workspace_id"],
            preparation_id=row["preparation_id"],
            upload_id=row["upload_id"],
            manifest_version=row["manifest_version"],
            source_sha256=row["source_sha256"],
            accepted_sha256=row["accepted_sha256"],
            content_profile=row["content_profile"],
            parser_version=row["parser_version"],
            scanner_version=row["scanner_version"],
            schema_version=row["schema_version"],
            configuration_hash=row["configuration_hash"],
            item_count=row["item_count"],
            rejected_count=row["rejected_count"],
            candidate_root_hash=row["candidate_root_hash"],
            receipt_hash=row["receipt_hash"],
            observed_at=row["observed_at"],
            created_at=row["created_at"],
            candidate_count=row["candidate_count"],
            first_ordinal=row["first_ordinal"],
            last_ordinal=row["last_ordinal"],
            legacy_candidate_count=row["legacy_candidate_count"],
            object_locator_hash=row["object_locator_hash"],
            accepted_etag=row["accepted_etag"],
            accepted_version_id=row["accepted_version_id"],
        )

    async def get_candidate(
        self,
        *,
        workspace_id: UUID,
        receipt_id: UUID,
        candidate_id: UUID,
    ) -> CatalogMetadataCandidateEvidence | None:
        values = await self._load(
            workspace_id=workspace_id,
            receipt_id=receipt_id,
            candidate_id=candidate_id,
            after_ordinal=None,
            limit=1,
        )
        return values[0] if len(values) == 1 else None

    async def list_candidates(
        self,
        *,
        workspace_id: UUID,
        receipt_id: UUID,
        after_ordinal: int,
        limit: int,
    ) -> list[CatalogMetadataCandidateEvidence]:
        return await self._load(
            workspace_id=workspace_id,
            receipt_id=receipt_id,
            candidate_id=None,
            after_ordinal=after_ordinal,
            limit=limit,
        )

    async def _load(
        self,
        *,
        workspace_id: UUID,
        receipt_id: UUID,
        candidate_id: UUID | None,
        after_ordinal: int | None,
        limit: int,
    ) -> list[CatalogMetadataCandidateEvidence]:
        candidate_statement = select(CatalogMetadataCandidateModel).where(
            CatalogMetadataCandidateModel.workspace_id == workspace_id,
            CatalogMetadataCandidateModel.receipt_id == receipt_id,
        )
        if candidate_id is not None:
            candidate_statement = candidate_statement.where(
                CatalogMetadataCandidateModel.id == candidate_id
            )
        else:
            assert after_ordinal is not None
            candidate_statement = candidate_statement.where(
                CatalogMetadataCandidateModel.candidate_ordinal > after_ordinal
            )
        models = list(
            (
                await self._session.scalars(
                    candidate_statement.order_by(
                        CatalogMetadataCandidateModel.candidate_ordinal.asc()
                    ).limit(limit)
                )
            ).all()
        )
        if not models:
            return []
        ids = tuple(model.id for model in models)
        joined_rows = (
            await self._session.execute(
                select(CatalogMetadataCandidateRowModel, CatalogMetadataRowModel)
                .join(
                    CatalogMetadataRowModel,
                    and_(
                        CatalogMetadataRowModel.workspace_id
                        == CatalogMetadataCandidateRowModel.workspace_id,
                        CatalogMetadataRowModel.receipt_id
                        == CatalogMetadataCandidateRowModel.receipt_id,
                        CatalogMetadataRowModel.id == CatalogMetadataCandidateRowModel.row_id,
                    ),
                )
                .where(
                    CatalogMetadataCandidateRowModel.workspace_id == workspace_id,
                    CatalogMetadataCandidateRowModel.receipt_id == receipt_id,
                    CatalogMetadataCandidateRowModel.candidate_id.in_(ids),
                )
                .order_by(
                    CatalogMetadataCandidateRowModel.candidate_id,
                    CatalogMetadataCandidateRowModel.member_ordinal,
                )
            )
        ).all()
        rows_by_candidate: dict[UUID, list[CatalogMetadataRowEvidenceRecord]] = {
            value: [] for value in ids
        }
        for membership, row in joined_rows:
            if membership.source_ordinal != row.ordinal or membership.row_hash != row.row_hash:
                return []
            rows_by_candidate[membership.candidate_id].append(
                CatalogMetadataRowEvidenceRecord(
                    row_id=row.id,
                    ordinal=row.ordinal,
                    record_kind=row.record_kind,
                    aspect_name=row.aspect_name,
                    operation=row.operation,
                    field_path=row.field_path,
                    value_text=row.value_text,
                    controlled_ref_id=row.controlled_ref_id,
                    controlled_kind=row.controlled_kind,
                    semantic_target_hash=row.semantic_target_hash,
                    row_hash=row.row_hash,
                )
            )
        values: list[CatalogMetadataCandidateEvidence] = []
        for model in models:
            rows = tuple(rows_by_candidate[model.id])
            first = rows[0] if rows else None
            source_row = next(
                (row for membership, row in joined_rows if membership.candidate_id == model.id),
                None,
            )
            if (
                first is None
                or source_row is None
                or len(rows) != model.row_count
                or first.ordinal != model.first_row_ordinal
                or rows[-1].ordinal != model.last_row_ordinal
            ):
                return []
            values.append(
                CatalogMetadataCandidateEvidence(
                    candidate_id=model.id,
                    workspace_id=model.workspace_id,
                    receipt_id=model.receipt_id,
                    ordinal=model.candidate_ordinal,
                    content_profile=model.content_profile,
                    evidence_version=model.evidence_version,
                    record_kind=model.record_kind,
                    candidate_kind=model.candidate_kind,
                    target_asset_id=model.target_asset_id,
                    aspect_name=model.aspect_name,
                    submitted_platform=source_row.submitted_platform,
                    submitted_database_name=source_row.submitted_database_name,
                    submitted_schema_name=source_row.submitted_schema_name,
                    submitted_table_name=source_row.submitted_table_name,
                    submitted_identity_hash=model.submitted_identity_hash,
                    row_root_hash=model.row_root_hash,
                    candidate_hash=model.candidate_hash,
                    rows=rows,
                    created_at=model.created_at,
                )
            )
        return values


def _to_candidate(model: UploadRegistrationCandidateModel) -> UploadRegistrationCandidateEvidence:
    return UploadRegistrationCandidateEvidence(
        candidate_id=model.id,
        workspace_id=model.workspace_id,
        receipt_id=model.receipt_id,
        ordinal=model.ordinal,
        target_asset_id=model.target_asset_id,
        candidate_kind=model.candidate_kind,
        proposed_description=model.proposed_description,
        evidence_version=model.evidence_version,
        submitted_platform=model.submitted_platform,
        submitted_database_name=model.submitted_database_name,
        submitted_schema_name=model.submitted_schema_name,
        submitted_table_name=model.submitted_table_name,
        submitted_identity_hash=model.submitted_identity_hash,
        candidate_hash=model.candidate_hash,
        created_at=model.created_at,
    )


def _to_preparation(model: UploadPreparationJobModel) -> UploadPreparation:
    return UploadPreparation(
        preparation_id=model.id,
        workspace_id=model.workspace_id,
        upload_id=model.upload_id,
        requested_by=model.requested_by,
        content_profile=UploadContentProfile(model.content_profile),
        source_manifest_version=model.source_manifest_version,
        source_sha256=model.source_sha256,
        configuration_hash=model.configuration_hash,
        state=UploadPreparationState(model.state),
        attempts=model.attempts,
        rows_processed=model.rows_processed,
        total_rows=model.total_rows,
        last_error_code=model.last_error_code,
        created_at=model.created_at,
        updated_at=model.updated_at,
        version=model.version,
    )


class SqlUploadCompletionStore(UploadCompletionStore):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def claim_next(
        self, *, lease_seconds: int, maximum_attempts: int
    ) -> UploadManifest | None:
        now = utc_now()
        async with self._session_factory() as session, session.begin():
            model = (
                await session.scalars(
                    select(ObjectManifestModel)
                    .where(
                        ObjectManifestModel.expires_at > now,
                        ObjectManifestModel.processing_attempts < maximum_attempts,
                        or_(
                            ObjectManifestModel.state == UploadState.COMPLETION_QUEUED.value,
                            and_(
                                ObjectManifestModel.state == UploadState.COMPLETING.value,
                                ObjectManifestModel.processing_lease_until < now,
                            ),
                        ),
                    )
                    .order_by(ObjectManifestModel.created_at)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
            ).one_or_none()
            if model is None:
                return None
            manifest = _to_domain(model)
            manifest.begin_completion(expected_version=manifest.version)
            _apply_manifest(model, manifest)
            model.processing_lease_until = now + timedelta(seconds=lease_seconds)
            model.last_error_code = None
        return manifest

    async def mark_quarantined(self, *, manifest: UploadManifest, metadata: ObjectMetadata) -> None:
        async with self._session_factory() as session, session.begin():
            model = await self._locked(session, manifest)
            if model is None or model.version != manifest.version:
                return
            current = _to_domain(model)
            current.mark_quarantined(
                actual_size_bytes=metadata.size_bytes,
                actual_mime=metadata.content_type,
                checksum_sha256=metadata.checksum_sha256,
                expected_version=current.version,
            )
            _apply_manifest(model, current)
            model.processing_lease_until = None
            model.last_error_code = None
            await SqlOutboxWriter(session).add_events(current.events)

    async def mark_failed(
        self,
        *,
        manifest: UploadManifest,
        error_code: str,
        retryable: bool,
        maximum_attempts: int,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            model = await self._locked(session, manifest)
            if model is None or model.version != manifest.version:
                return
            current = _to_domain(model)
            may_retry = retryable and current.processing_attempts < maximum_attempts
            current.mark_completion_failed(
                retryable=may_retry,
                expected_version=current.version,
            )
            _apply_manifest(model, current)
            model.processing_lease_until = None
            model.last_error_code = error_code
            await SqlOutboxWriter(session).add_events(current.events)

    @staticmethod
    async def _locked(
        session: AsyncSession, manifest: UploadManifest
    ) -> ObjectManifestModel | None:
        return (
            await session.scalars(
                select(ObjectManifestModel)
                .where(
                    ObjectManifestModel.id == manifest.upload_id,
                    ObjectManifestModel.workspace_id == manifest.workspace_id,
                )
                .with_for_update()
            )
        ).one_or_none()


class SqlUploadValidationStore(UploadValidationStore):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def claim_next(
        self, *, lease_seconds: int, maximum_attempts: int
    ) -> UploadManifest | None:
        now = utc_now()
        async with self._session_factory() as session, session.begin():
            model = (
                await session.scalars(
                    select(ObjectManifestModel)
                    .where(
                        ObjectManifestModel.expires_at > now,
                        ObjectManifestModel.validation_attempts < maximum_attempts,
                        or_(
                            ObjectManifestModel.state == UploadState.QUARANTINED.value,
                            and_(
                                ObjectManifestModel.state == UploadState.VALIDATING.value,
                                ObjectManifestModel.processing_lease_until < now,
                            ),
                        ),
                    )
                    .order_by(ObjectManifestModel.created_at)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
            ).one_or_none()
            if model is None:
                return None
            manifest = _to_domain(model)
            manifest.begin_validation(expected_version=manifest.version)
            _apply_manifest(model, manifest)
            model.processing_lease_until = now + timedelta(seconds=lease_seconds)
            model.last_error_code = None
        return manifest

    async def mark_accepted(
        self,
        *,
        manifest: UploadManifest,
        accepted_bucket: str,
        accepted_object_key: str,
        validated_sha256: str,
        validation_summary: dict[str, object],
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            model = await SqlUploadCompletionStore._locked(session, manifest)
            if model is None or model.version != manifest.version:
                return False
            current = _to_domain(model)
            current.mark_accepted(
                accepted_bucket=accepted_bucket,
                accepted_object_key=accepted_object_key,
                validated_sha256=validated_sha256,
                validation_summary=validation_summary,
                expected_version=current.version,
            )
            _apply_manifest(model, current)
            model.processing_lease_until = None
            model.last_error_code = None
            await SqlOutboxWriter(session).add_events(current.events)
        return True

    async def mark_failed(
        self,
        *,
        manifest: UploadManifest,
        error_code: str,
        retryable: bool,
        maximum_attempts: int,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            model = await SqlUploadCompletionStore._locked(session, manifest)
            if model is None or model.version != manifest.version:
                return
            current = _to_domain(model)
            may_retry = retryable and current.validation_attempts < maximum_attempts
            current.mark_validation_failed(
                retryable=may_retry,
                expected_version=current.version,
            )
            _apply_manifest(model, current)
            model.processing_lease_until = None
            model.last_error_code = error_code
            await SqlOutboxWriter(session).add_events(current.events)


class SqlUploadUnitOfWork(UploadUnitOfWork):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self.uploads: SqlUploadRepository
        self.preparations: SqlUploadPreparationRepository
        self.outbox: SqlOutboxWriter
        self.idempotency: SqlIdempotencyStore
        self._committed = False

    async def __aenter__(self) -> SqlUploadUnitOfWork:
        self._session = self._session_factory()
        self.uploads = SqlUploadRepository(self._session)
        self.preparations = SqlUploadPreparationRepository(self._session)
        self.outbox = SqlOutboxWriter(self._session)
        self.idempotency = SqlIdempotencyStore(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_value, traceback
        if self._session is None:
            return
        if exc_type is not None or not self._committed:
            await self._session.rollback()
        await self._session.close()

    async def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await self._session.commit()
        self._committed = True

    async def rollback(self) -> None:
        if self._session is not None:
            await self._session.rollback()

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await set_security_context(self._session, workspace_id=workspace_id, subject_id=subject_id)
