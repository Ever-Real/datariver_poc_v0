from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.dto import (
    IdempotencyRecord,
    KnowledgeStudioDomainOption,
    KnowledgeStudioDraftRecord,
)
from datariver.application.ports import KnowledgeStudioStore
from datariver.domain.authz import Classification
from datariver.domain.common import (
    ConflictError,
    NotFoundError,
    ValidationError,
    utc_now,
    uuid7,
)
from datariver.domain.knowledge_studio import (
    StudioDraftKind,
    StudioDraftState,
    StudioStep,
    require_studio_version,
    validate_endpoint_alias,
    validate_studio_name,
)
from datariver.infrastructure.db.governance import SqlIdempotencyStore
from datariver.infrastructure.db.models.catalog import CatalogVocabularyEntryModel
from datariver.infrastructure.db.models.knowledge import GraphModel
from datariver.infrastructure.db.models.knowledge_studio import KnowledgeStudioDraftModel

CREATE_OPERATION = "knowledge.studio_draft.create"


def _draft_record(model: KnowledgeStudioDraftModel) -> KnowledgeStudioDraftRecord:
    return KnowledgeStudioDraftRecord(
        draft_id=model.id,
        workspace_id=model.workspace_id,
        author_id=model.author_id,
        kind=model.kind,
        state=model.state,
        current_step=model.current_step,
        name=model.name,
        endpoint_alias=model.endpoint_alias,
        domain_id=model.domain_ref_id,
        domain_source_version=model.domain_source_version,
        classification=Classification(model.classification),
        base_graph_id=model.base_graph_id,
        base_ontology_version_id=model.base_ontology_version_id,
        base_release_id=model.base_release_id,
        last_autosaved_at=model.last_autosaved_at,
        version=model.version,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def studio_draft_result(record: KnowledgeStudioDraftRecord) -> dict[str, object]:
    return {
        "draft_id": str(record.draft_id),
        "workspace_id": str(record.workspace_id),
        "author_id": str(record.author_id),
        "kind": record.kind,
        "state": record.state,
        "current_step": record.current_step,
        "name": record.name,
        "endpoint_alias": record.endpoint_alias,
        "domain_id": str(record.domain_id),
        "domain_source_version": record.domain_source_version,
        "classification": int(record.classification),
        "base_graph_id": str(record.base_graph_id) if record.base_graph_id else None,
        "base_ontology_version_id": (
            str(record.base_ontology_version_id) if record.base_ontology_version_id else None
        ),
        "base_release_id": str(record.base_release_id) if record.base_release_id else None,
        "last_autosaved_at": record.last_autosaved_at.isoformat(),
        "version": record.version,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


def _required_str(result: dict[str, Any], key: str) -> str:
    value = result.get(key)
    if not isinstance(value, str) or not value:
        raise ConflictError("The idempotent Knowledge Studio result is invalid.")
    return value


def _required_int(result: dict[str, Any], key: str) -> int:
    value = result.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConflictError("The idempotent Knowledge Studio result is invalid.")
    return value


def _optional_uuid(result: dict[str, Any], key: str) -> UUID | None:
    value = result.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConflictError("The idempotent Knowledge Studio result is invalid.")
    try:
        return UUID(value)
    except ValueError as error:
        raise ConflictError("The idempotent Knowledge Studio result is invalid.") from error


def _required_datetime(result: dict[str, Any], key: str) -> datetime:
    value = datetime.fromisoformat(_required_str(result, key))
    if value.tzinfo is None:
        raise ConflictError("The idempotent Knowledge Studio result is invalid.")
    return value


def studio_draft_record_from_result(result: dict[str, Any]) -> KnowledgeStudioDraftRecord:
    try:
        version = _required_int(result, "version")
        if version < 1:
            raise ConflictError("The idempotent Knowledge Studio result is invalid.")
        name = validate_studio_name(_required_str(result, "name"))
        endpoint_alias = validate_endpoint_alias(_required_str(result, "endpoint_alias"))
        domain_source_version = _required_str(result, "domain_source_version")
        if len(domain_source_version) > 255:
            raise ConflictError("The idempotent Knowledge Studio result is invalid.")
        return KnowledgeStudioDraftRecord(
            draft_id=UUID(_required_str(result, "draft_id")),
            workspace_id=UUID(_required_str(result, "workspace_id")),
            author_id=UUID(_required_str(result, "author_id")),
            kind=StudioDraftKind(_required_str(result, "kind")).value,
            state=StudioDraftState(_required_str(result, "state")).value,
            current_step=StudioStep(_required_str(result, "current_step")).value,
            name=name,
            endpoint_alias=endpoint_alias,
            domain_id=UUID(_required_str(result, "domain_id")),
            domain_source_version=domain_source_version,
            classification=Classification(_required_int(result, "classification")),
            base_graph_id=_optional_uuid(result, "base_graph_id"),
            base_ontology_version_id=_optional_uuid(result, "base_ontology_version_id"),
            base_release_id=_optional_uuid(result, "base_release_id"),
            last_autosaved_at=_required_datetime(result, "last_autosaved_at"),
            version=version,
            created_at=_required_datetime(result, "created_at"),
            updated_at=_required_datetime(result, "updated_at"),
        )
    except (ValueError, TypeError, ValidationError) as error:
        raise ConflictError("The idempotent Knowledge Studio result is invalid.") from error


def resolve_studio_idempotent_replay(
    existing: IdempotencyRecord | None,
    *,
    workspace_id: UUID,
    author_id: UUID,
    request_hash: str,
) -> KnowledgeStudioDraftRecord | None:
    if existing is None:
        return None
    if existing.request_hash != request_hash:
        raise ConflictError("The idempotency key was used with a different request.")
    record = studio_draft_record_from_result(existing.result)
    if record.workspace_id != workspace_id or record.author_id != author_id:
        raise ConflictError("The idempotent Knowledge Studio result is bound to another author.")
    return record


class SqlKnowledgeStudioStore(KnowledgeStudioStore):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_domains(
        self,
        *,
        workspace_id: UUID,
        allowed_domain_ids: frozenset[UUID] | None,
        query: str | None,
        limit: int,
    ) -> tuple[KnowledgeStudioDomainOption, ...]:
        if allowed_domain_ids is not None and not allowed_domain_ids:
            return ()
        statement = (
            select(
                CatalogVocabularyEntryModel.id,
                CatalogVocabularyEntryModel.display_name,
                CatalogVocabularyEntryModel.source_version,
            )
            .where(
                CatalogVocabularyEntryModel.workspace_id == workspace_id,
                CatalogVocabularyEntryModel.kind == "DOMAIN",
                CatalogVocabularyEntryModel.lifecycle == "ACTIVE",
            )
            .order_by(
                CatalogVocabularyEntryModel.display_name,
                CatalogVocabularyEntryModel.id,
            )
            .limit(limit)
        )
        if allowed_domain_ids is not None:
            statement = statement.where(CatalogVocabularyEntryModel.id.in_(allowed_domain_ids))
        if query:
            statement = statement.where(
                CatalogVocabularyEntryModel.display_name.contains(query, autoescape=True)
            )
        rows = (await self._session.execute(statement)).all()
        return tuple(
            KnowledgeStudioDomainOption(
                domain_id=row.id,
                display_name=row.display_name,
                source_version=row.source_version,
            )
            for row in rows
        )

    async def get_draft(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
    ) -> KnowledgeStudioDraftRecord | None:
        model = (
            await self._session.scalars(
                select(KnowledgeStudioDraftModel).where(
                    KnowledgeStudioDraftModel.workspace_id == workspace_id,
                    KnowledgeStudioDraftModel.author_id == author_id,
                    KnowledgeStudioDraftModel.id == draft_id,
                )
            )
        ).one_or_none()
        return _draft_record(model) if model is not None else None

    async def create_draft(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        name: str,
        endpoint_alias: str,
        domain_id: UUID,
        domain_source_version: str,
        classification: int,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioDraftRecord:
        idempotency = SqlIdempotencyStore(self._session)
        await idempotency.acquire_key_lock(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=CREATE_OPERATION,
        )
        replay = await self._idempotent_replay(
            idempotency=idempotency,
            workspace_id=workspace_id,
            author_id=author_id,
            operation=CREATE_OPERATION,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if replay is not None:
            return replay
        await self._require_domain(
            workspace_id=workspace_id,
            domain_id=domain_id,
            domain_source_version=domain_source_version,
        )
        await self._require_alias_available(
            workspace_id=workspace_id,
            endpoint_alias=endpoint_alias,
        )
        now = utc_now()
        model = KnowledgeStudioDraftModel(
            id=uuid7(),
            workspace_id=workspace_id,
            author_id=author_id,
            kind="CREATE",
            state="DRAFT",
            current_step="BASIC",
            name=name,
            endpoint_alias=endpoint_alias,
            domain_ref_id=domain_id,
            domain_ref_kind="DOMAIN",
            domain_source_version=domain_source_version,
            classification=classification,
            last_autosaved_at=now,
            created_at=now,
            updated_at=now,
            version=1,
        )
        self._session.add(model)
        try:
            await self._session.flush()
            record = _draft_record(model)
            await idempotency.save_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=CREATE_OPERATION,
                request_hash=request_hash,
                result=studio_draft_result(record),
            )
            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()
            raise ConflictError(
                "A live Knowledge Studio draft or graph already uses this endpoint alias."
            ) from error
        return record

    async def autosave_draft(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
        name: str,
        endpoint_alias: str,
        domain_id: UUID,
        domain_source_version: str,
        classification: int,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioDraftRecord:
        operation = f"knowledge.studio_draft.autosave:{draft_id}"
        idempotency = SqlIdempotencyStore(self._session)
        await idempotency.acquire_key_lock(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
        )
        replay = await self._idempotent_replay(
            idempotency=idempotency,
            workspace_id=workspace_id,
            author_id=author_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if replay is not None:
            return replay
        model = await self._locked_draft(
            workspace_id=workspace_id,
            author_id=author_id,
            draft_id=draft_id,
        )
        self._require_expected_version(model, expected_version)
        self._require_mutable(model)
        await self._require_domain(
            workspace_id=workspace_id,
            domain_id=domain_id,
            domain_source_version=domain_source_version,
        )
        await self._require_alias_available(
            workspace_id=workspace_id,
            endpoint_alias=endpoint_alias,
        )
        now = utc_now()
        model.name = name
        model.endpoint_alias = endpoint_alias
        model.domain_ref_id = domain_id
        model.domain_source_version = domain_source_version
        model.classification = classification
        model.last_autosaved_at = now
        model.updated_at = now
        model.version += 1
        return await self._save_mutation(
            model=model,
            idempotency=idempotency,
            workspace_id=workspace_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def advance_to_tbox(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioDraftRecord:
        operation = f"knowledge.studio_draft.advance_tbox:{draft_id}"
        idempotency = SqlIdempotencyStore(self._session)
        await idempotency.acquire_key_lock(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
        )
        replay = await self._idempotent_replay(
            idempotency=idempotency,
            workspace_id=workspace_id,
            author_id=author_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if replay is not None:
            return replay
        model = await self._locked_draft(
            workspace_id=workspace_id,
            author_id=author_id,
            draft_id=draft_id,
        )
        self._require_expected_version(model, expected_version)
        self._require_mutable(model)
        if model.current_step not in {"BASIC", "TBOX"}:
            raise ConflictError("The Knowledge Studio draft cannot return to Graph Builder.")
        if model.current_step == "BASIC":
            model.current_step = "TBOX"
            model.updated_at = utc_now()
            model.version += 1
        return await self._save_mutation(
            model=model,
            idempotency=idempotency,
            workspace_id=workspace_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def _save_mutation(
        self,
        *,
        model: KnowledgeStudioDraftModel,
        idempotency: SqlIdempotencyStore,
        workspace_id: UUID,
        operation: str,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioDraftRecord:
        try:
            await self._session.flush()
            record = _draft_record(model)
            await idempotency.save_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                result=studio_draft_result(record),
            )
            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()
            raise ConflictError(
                "A live Knowledge Studio draft or graph already uses this endpoint alias."
            ) from error
        return record

    async def _locked_draft(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
    ) -> KnowledgeStudioDraftModel:
        model = (
            await self._session.scalars(
                select(KnowledgeStudioDraftModel)
                .where(
                    KnowledgeStudioDraftModel.workspace_id == workspace_id,
                    KnowledgeStudioDraftModel.author_id == author_id,
                    KnowledgeStudioDraftModel.id == draft_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        if model is None:
            raise NotFoundError("The Knowledge Studio draft does not exist.")
        return model

    async def _require_domain(
        self,
        *,
        workspace_id: UUID,
        domain_id: UUID,
        domain_source_version: str,
    ) -> None:
        current_version = await self._session.scalar(
            select(CatalogVocabularyEntryModel.source_version).where(
                CatalogVocabularyEntryModel.workspace_id == workspace_id,
                CatalogVocabularyEntryModel.id == domain_id,
                CatalogVocabularyEntryModel.kind == "DOMAIN",
                CatalogVocabularyEntryModel.lifecycle == "ACTIVE",
            )
        )
        if current_version is None:
            raise ConflictError("The selected domain is not active.")
        if current_version != domain_source_version:
            raise ConflictError("The selected domain source version is no longer current.")

    async def _require_alias_available(
        self,
        *,
        workspace_id: UUID,
        endpoint_alias: str,
    ) -> None:
        graph_id = await self._session.scalar(
            select(GraphModel.id).where(
                GraphModel.workspace_id == workspace_id,
                GraphModel.slug == endpoint_alias,
            )
        )
        if graph_id is not None:
            raise ConflictError("A knowledge graph already uses this endpoint alias.")

    @staticmethod
    def _require_expected_version(
        model: KnowledgeStudioDraftModel,
        expected_version: int,
    ) -> None:
        require_studio_version(model.version, expected_version)

    @staticmethod
    def _require_mutable(model: KnowledgeStudioDraftModel) -> None:
        if model.state != "DRAFT":
            raise ConflictError("Only a DRAFT Knowledge Studio draft can be edited.")

    @staticmethod
    async def _idempotent_replay(
        *,
        idempotency: SqlIdempotencyStore,
        workspace_id: UUID,
        author_id: UUID,
        operation: str,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioDraftRecord | None:
        existing = await idempotency.get_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
        )
        return resolve_studio_idempotent_replay(
            existing,
            workspace_id=workspace_id,
            author_id=author_id,
            request_hash=request_hash,
        )
