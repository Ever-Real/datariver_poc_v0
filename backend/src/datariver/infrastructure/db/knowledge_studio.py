from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.dto import (
    IdempotencyRecord,
    KnowledgeStudioABoxRecord,
    KnowledgeStudioBindingRecord,
    KnowledgeStudioDomainOption,
    KnowledgeStudioDraftRecord,
    KnowledgeStudioMappingRuleRecord,
    KnowledgeStudioTBoxElementRecord,
)
from datariver.application.ports import KnowledgeStudioStore
from datariver.domain.authz import Classification
from datariver.domain.catalog import DATASET_ASSET_TYPES
from datariver.domain.common import (
    ConflictError,
    NotFoundError,
    ValidationError,
    canonical_json_hash,
    utc_now,
    uuid7,
)
from datariver.domain.knowledge_studio import (
    ABoxBindingReadiness,
    ABoxMappingMethod,
    StudioDraftKind,
    StudioDraftState,
    StudioStep,
    require_studio_version,
    validate_endpoint_alias,
    validate_source_field_path,
    validate_stable_element_id,
    validate_studio_name,
)
from datariver.infrastructure.db.governance import SqlIdempotencyStore
from datariver.infrastructure.db.models.catalog import (
    AssetProjectionModel,
    CatalogVocabularyEntryModel,
)
from datariver.infrastructure.db.models.knowledge import GraphModel
from datariver.infrastructure.db.models.knowledge_studio import (
    ABoxBindingDraftModel,
    ABoxMappingRuleDraftModel,
    KnowledgeSourceReferenceModel,
    KnowledgeStudioDraftModel,
    TBoxDraftElementModel,
)

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


def _tbox_element_record(model: TBoxDraftElementModel) -> KnowledgeStudioTBoxElementRecord:
    return KnowledgeStudioTBoxElementRecord(
        stable_element_id=model.stable_element_id,
        kind=model.kind,
        canonical_name=model.canonical_name,
        display_name=model.display_name,
        parent_stable_element_id=model.parent_stable_element_id,
        source_stable_element_id=model.source_stable_element_id,
        target_stable_element_id=model.target_stable_element_id,
        data_type=model.data_type,
        nullable=model.nullable,
        ordinal=model.ordinal,
        version=model.version,
    )


def _mapping_rule_record(
    model: ABoxMappingRuleDraftModel,
) -> KnowledgeStudioMappingRuleRecord:
    return KnowledgeStudioMappingRuleRecord(
        rule_id=model.id,
        ordinal=model.ordinal,
        method=model.method,
        source_field_path=model.source_field_path,
        target_stable_element_id=model.target_stable_element_id,
        transform_id=model.transform_id,
        transform_version=model.transform_version,
        source_unit=model.source_unit,
        canonical_unit=model.canonical_unit,
    )


def _binding_record(
    model: ABoxBindingDraftModel,
    *,
    source: KnowledgeSourceReferenceModel,
    source_name: str,
    rules: tuple[ABoxMappingRuleDraftModel, ...],
) -> KnowledgeStudioBindingRecord:
    return KnowledgeStudioBindingRecord(
        binding_id=model.id,
        target_stable_element_id=model.target_stable_element_id,
        source_reference_id=model.source_reference_id,
        source_asset_id=source.catalog_asset_id,
        source_name=source_name,
        source_version=source.source_version,
        projection_source_version=source.projection_source_version,
        source_classification=Classification(source.classification),
        readiness=model.readiness,
        tbox_version=model.tbox_version,
        version=model.version,
        rules=tuple(_mapping_rule_record(item) for item in rules),
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


def abox_binding_result(
    draft: KnowledgeStudioDraftRecord,
    binding: KnowledgeStudioBindingRecord,
) -> dict[str, object]:
    return {
        "draft": studio_draft_result(draft),
        "binding": {
            "binding_id": str(binding.binding_id),
            "target_stable_element_id": binding.target_stable_element_id,
            "source_reference_id": str(binding.source_reference_id),
            "source_asset_id": str(binding.source_asset_id),
            "source_name": binding.source_name,
            "source_version": binding.source_version,
            "projection_source_version": binding.projection_source_version,
            "source_classification": int(binding.source_classification),
            "readiness": binding.readiness,
            "tbox_version": binding.tbox_version,
            "version": binding.version,
            "rules": [
                {
                    "rule_id": str(rule.rule_id),
                    "ordinal": rule.ordinal,
                    "method": rule.method,
                    "source_field_path": rule.source_field_path,
                    "target_stable_element_id": rule.target_stable_element_id,
                    "transform_id": rule.transform_id,
                    "transform_version": rule.transform_version,
                    "source_unit": rule.source_unit,
                    "canonical_unit": rule.canonical_unit,
                }
                for rule in binding.rules
            ],
            "created_at": binding.created_at.isoformat(),
            "updated_at": binding.updated_at.isoformat(),
        },
    }


def _optional_str(result: dict[str, Any], key: str) -> str | None:
    value = result.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConflictError("The idempotent A-Box result is invalid.")
    return value


def _binding_record_from_result(result: dict[str, Any]) -> KnowledgeStudioBindingRecord:
    rules_value = result.get("rules")
    if not isinstance(rules_value, list) or not 1 <= len(rules_value) <= 200:
        raise ConflictError("The idempotent A-Box result is invalid.")
    rules: list[KnowledgeStudioMappingRuleRecord] = []
    for raw_rule in rules_value:
        if not isinstance(raw_rule, dict):
            raise ConflictError("The idempotent A-Box result is invalid.")
        try:
            ordinal = _required_int(raw_rule, "ordinal")
            method = ABoxMappingMethod(_required_str(raw_rule, "method")).value
            source_field_path = validate_source_field_path(
                _required_str(raw_rule, "source_field_path")
            )
            target_id = validate_stable_element_id(
                _required_str(raw_rule, "target_stable_element_id")
            )
            transform_id = _required_str(raw_rule, "transform_id")
            transform_version = _required_str(raw_rule, "transform_version")
            if ordinal < 0 or transform_id != "IDENTITY" or transform_version != "1":
                raise ValueError
            rules.append(
                KnowledgeStudioMappingRuleRecord(
                    rule_id=UUID(_required_str(raw_rule, "rule_id")),
                    ordinal=ordinal,
                    method=method,
                    source_field_path=source_field_path,
                    target_stable_element_id=target_id,
                    transform_id=transform_id,
                    transform_version=transform_version,
                    source_unit=_optional_str(raw_rule, "source_unit"),
                    canonical_unit=_optional_str(raw_rule, "canonical_unit"),
                )
            )
        except (TypeError, ValueError, ValidationError) as error:
            raise ConflictError("The idempotent A-Box result is invalid.") from error
    try:
        readiness = ABoxBindingReadiness(_required_str(result, "readiness")).value
        version = _required_int(result, "version")
        tbox_version = _required_int(result, "tbox_version")
        target_stable_element_id = validate_stable_element_id(
            _required_str(result, "target_stable_element_id")
        )
        source_name = _required_str(result, "source_name")
        source_version = _required_str(result, "source_version")
        projection_source_version = _required_str(
            result,
            "projection_source_version",
        )
        if version < 1 or tbox_version < 1:
            raise ValueError
        if (
            len(source_name) > 500
            or len(source_version) > 255
            or len(projection_source_version) > 255
        ):
            raise ValueError
        return KnowledgeStudioBindingRecord(
            binding_id=UUID(_required_str(result, "binding_id")),
            target_stable_element_id=target_stable_element_id,
            source_reference_id=UUID(_required_str(result, "source_reference_id")),
            source_asset_id=UUID(_required_str(result, "source_asset_id")),
            source_name=source_name,
            source_version=source_version,
            projection_source_version=projection_source_version,
            source_classification=Classification(_required_int(result, "source_classification")),
            readiness=readiness,
            tbox_version=tbox_version,
            version=version,
            rules=tuple(rules),
            created_at=_required_datetime(result, "created_at"),
            updated_at=_required_datetime(result, "updated_at"),
        )
    except (TypeError, ValueError) as error:
        raise ConflictError("The idempotent A-Box result is invalid.") from error


def resolve_abox_idempotent_replay(
    existing: IdempotencyRecord | None,
    *,
    workspace_id: UUID,
    author_id: UUID,
    request_hash: str,
) -> tuple[KnowledgeStudioDraftRecord, KnowledgeStudioBindingRecord] | None:
    if existing is None:
        return None
    if existing.request_hash != request_hash:
        raise ConflictError("The idempotency key was used with a different request.")
    raw_draft = existing.result.get("draft")
    raw_binding = existing.result.get("binding")
    if not isinstance(raw_draft, dict) or not isinstance(raw_binding, dict):
        raise ConflictError("The idempotent A-Box result is invalid.")
    try:
        draft = studio_draft_record_from_result(raw_draft)
        binding = _binding_record_from_result(raw_binding)
    except (TypeError, ValueError, ConflictError) as error:
        raise ConflictError("The idempotent A-Box result is invalid.") from error
    if draft.workspace_id != workspace_id or draft.author_id != author_id:
        raise ConflictError("The idempotent A-Box result is bound to another author.")
    return draft, binding


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

    async def advance_to_abox(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioDraftRecord:
        operation = f"knowledge.studio_draft.advance_abox:{draft_id}"
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
        if model.current_step not in {"TBOX", "ABOX"}:
            raise ConflictError("Complete Step 1 before opening Data Enricher.")
        selectable_element = await self._session.scalar(
            select(TBoxDraftElementModel.id)
            .where(
                TBoxDraftElementModel.workspace_id == workspace_id,
                TBoxDraftElementModel.draft_id == draft_id,
                TBoxDraftElementModel.kind.in_(("CLASS", "RELATION")),
            )
            .limit(1)
        )
        if selectable_element is None:
            raise ConflictError("An accepted T-Box Class or Relation is required.")
        if model.current_step == "TBOX":
            model.current_step = "ABOX"
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

    async def get_abox(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
    ) -> KnowledgeStudioABoxRecord | None:
        draft_model = (
            await self._session.scalars(
                select(KnowledgeStudioDraftModel).where(
                    KnowledgeStudioDraftModel.workspace_id == workspace_id,
                    KnowledgeStudioDraftModel.author_id == author_id,
                    KnowledgeStudioDraftModel.id == draft_id,
                )
            )
        ).one_or_none()
        if draft_model is None:
            return None
        element_models = list(
            (
                await self._session.scalars(
                    select(TBoxDraftElementModel)
                    .where(
                        TBoxDraftElementModel.workspace_id == workspace_id,
                        TBoxDraftElementModel.draft_id == draft_id,
                    )
                    .order_by(
                        TBoxDraftElementModel.ordinal,
                        TBoxDraftElementModel.stable_element_id,
                    )
                    .limit(501)
                )
            ).all()
        )
        if len(element_models) > 500:
            raise ConflictError("The accepted T-Box exceeds the Data Enricher display bound.")
        binding_rows = (
            await self._session.execute(
                select(
                    ABoxBindingDraftModel,
                    KnowledgeSourceReferenceModel,
                    AssetProjectionModel.name,
                )
                .join(
                    KnowledgeSourceReferenceModel,
                    (
                        KnowledgeSourceReferenceModel.workspace_id
                        == ABoxBindingDraftModel.workspace_id
                    )
                    & (
                        KnowledgeSourceReferenceModel.id
                        == ABoxBindingDraftModel.source_reference_id
                    ),
                )
                .join(
                    AssetProjectionModel,
                    (
                        AssetProjectionModel.workspace_id
                        == KnowledgeSourceReferenceModel.workspace_id
                    )
                    & (AssetProjectionModel.id == KnowledgeSourceReferenceModel.catalog_asset_id),
                )
                .where(
                    ABoxBindingDraftModel.workspace_id == workspace_id,
                    ABoxBindingDraftModel.draft_id == draft_id,
                )
                .order_by(ABoxBindingDraftModel.target_stable_element_id)
                .limit(501)
            )
        ).all()
        if len(binding_rows) > 500:
            raise ConflictError("The A-Box binding set exceeds the Data Enricher display bound.")
        binding_ids = tuple(row[0].id for row in binding_rows)
        rule_models: list[ABoxMappingRuleDraftModel] = []
        if binding_ids:
            rule_models = list(
                (
                    await self._session.scalars(
                        select(ABoxMappingRuleDraftModel)
                        .where(
                            ABoxMappingRuleDraftModel.workspace_id == workspace_id,
                            ABoxMappingRuleDraftModel.binding_id.in_(binding_ids),
                        )
                        .order_by(
                            ABoxMappingRuleDraftModel.binding_id,
                            ABoxMappingRuleDraftModel.ordinal,
                        )
                        .limit(2_001)
                    )
                ).all()
            )
            if len(rule_models) > 2_000:
                raise ConflictError("The A-Box rule set exceeds the Data Enricher display bound.")
        rules_by_binding: dict[UUID, list[ABoxMappingRuleDraftModel]] = {}
        for rule in rule_models:
            rules_by_binding.setdefault(rule.binding_id, []).append(rule)
        return KnowledgeStudioABoxRecord(
            draft=_draft_record(draft_model),
            tbox_elements=tuple(_tbox_element_record(item) for item in element_models),
            bindings=tuple(
                _binding_record(
                    binding,
                    source=source,
                    source_name=source_name,
                    rules=tuple(rules_by_binding.get(binding.id, ())),
                )
                for binding, source, source_name in binding_rows
            ),
        )

    async def save_abox_binding(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
        target_stable_element_id: str,
        source_asset_id: UUID,
        source_version: str,
        projection_source_version: str,
        source_classification: int,
        source_name: str,
        rules: tuple[tuple[str, str, str], ...],
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> tuple[KnowledgeStudioDraftRecord, KnowledgeStudioBindingRecord]:
        operation = f"knowledge.studio_draft.abox_binding:{draft_id}:{target_stable_element_id}"
        idempotency = SqlIdempotencyStore(self._session)
        await idempotency.acquire_key_lock(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
        )
        existing_result = await idempotency.get_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
        )
        replay = resolve_abox_idempotent_replay(
            existing_result,
            workspace_id=workspace_id,
            author_id=author_id,
            request_hash=request_hash,
        )
        if replay is not None:
            return replay
        draft_model = await self._locked_draft(
            workspace_id=workspace_id,
            author_id=author_id,
            draft_id=draft_id,
        )
        self._require_expected_version(draft_model, expected_version)
        self._require_mutable(draft_model)
        if draft_model.current_step != "ABOX":
            raise ConflictError("Open Data Enricher before saving an A-Box binding.")
        target = (
            await self._session.scalars(
                select(TBoxDraftElementModel)
                .where(
                    TBoxDraftElementModel.workspace_id == workspace_id,
                    TBoxDraftElementModel.draft_id == draft_id,
                    TBoxDraftElementModel.stable_element_id == target_stable_element_id,
                    TBoxDraftElementModel.kind.in_(("CLASS", "RELATION")),
                )
                .with_for_update(read=True)
            )
        ).one_or_none()
        if target is None:
            raise ConflictError("The selected T-Box binding target is no longer accepted.")
        source_asset = (
            await self._session.scalars(
                select(AssetProjectionModel)
                .where(
                    AssetProjectionModel.workspace_id == workspace_id,
                    AssetProjectionModel.id == source_asset_id,
                    AssetProjectionModel.asset_type.in_(tuple(sorted(DATASET_ASSET_TYPES))),
                    AssetProjectionModel.lifecycle == "ACTIVE",
                    AssetProjectionModel.deleted_at.is_(None),
                )
                .with_for_update(read=True)
            )
        ).one_or_none()
        if source_asset is None:
            raise ConflictError("The selected Dataset is no longer active.")
        if (
            source_asset.source_version != projection_source_version
            or source_asset.classification != source_classification
            or source_asset.name != source_name
        ):
            raise ConflictError("The selected Dataset changed before the binding was saved.")
        if source_asset.classification > draft_model.classification:
            raise ConflictError(
                "The Dataset classification exceeds the Knowledge graph classification envelope."
            )
        target_ids = tuple(dict.fromkeys(rule[2] for rule in rules))
        target_rows = (
            await self._session.scalars(
                select(TBoxDraftElementModel)
                .where(
                    TBoxDraftElementModel.workspace_id == workspace_id,
                    TBoxDraftElementModel.draft_id == draft_id,
                    TBoxDraftElementModel.stable_element_id.in_(target_ids),
                )
                .with_for_update(read=True)
            )
        ).all()
        if {item.stable_element_id for item in target_rows} != set(target_ids):
            raise ConflictError("A mapping target is no longer accepted in the T-Box.")
        selection_document: dict[str, object] = {
            "contract_version": "catalog-dataset-v1",
            "projection_source_version": projection_source_version,
            "field_paths": sorted({rule[1] for rule in rules}),
        }
        selection_hash = canonical_json_hash(selection_document)
        source_reference = (
            await self._session.scalars(
                select(KnowledgeSourceReferenceModel).where(
                    KnowledgeSourceReferenceModel.workspace_id == workspace_id,
                    KnowledgeSourceReferenceModel.created_by == author_id,
                    KnowledgeSourceReferenceModel.kind == "CATALOG_DATASET",
                    KnowledgeSourceReferenceModel.catalog_asset_id == source_asset_id,
                    KnowledgeSourceReferenceModel.source_version == source_version,
                    KnowledgeSourceReferenceModel.projection_source_version
                    == projection_source_version,
                    KnowledgeSourceReferenceModel.selection_hash == selection_hash,
                )
            )
        ).one_or_none()
        if source_reference is None:
            source_reference = KnowledgeSourceReferenceModel(
                id=uuid7(),
                workspace_id=workspace_id,
                kind="CATALOG_DATASET",
                catalog_asset_id=source_asset_id,
                source_version=source_version,
                projection_source_version=projection_source_version,
                classification=source_classification,
                selection_document=selection_document,
                selection_hash=selection_hash,
                created_by=author_id,
                created_at=utc_now(),
            )
            self._session.add(source_reference)
            await self._session.flush()
        binding = (
            await self._session.scalars(
                select(ABoxBindingDraftModel)
                .where(
                    ABoxBindingDraftModel.workspace_id == workspace_id,
                    ABoxBindingDraftModel.draft_id == draft_id,
                    ABoxBindingDraftModel.target_stable_element_id == target_stable_element_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        now = utc_now()
        if binding is None:
            binding = ABoxBindingDraftModel(
                id=uuid7(),
                workspace_id=workspace_id,
                draft_id=draft_id,
                target_stable_element_id=target_stable_element_id,
                source_reference_id=source_reference.id,
                readiness="DRAFT",
                tbox_version=target.version,
                created_by=author_id,
                updated_by=author_id,
                created_at=now,
                updated_at=now,
                version=1,
            )
            self._session.add(binding)
            await self._session.flush()
        else:
            binding.source_reference_id = source_reference.id
            binding.readiness = "DRAFT"
            binding.tbox_version = target.version
            binding.updated_by = author_id
            binding.updated_at = now
            binding.version += 1
            await self._session.execute(
                delete(ABoxMappingRuleDraftModel).where(
                    ABoxMappingRuleDraftModel.workspace_id == workspace_id,
                    ABoxMappingRuleDraftModel.draft_id == draft_id,
                    ABoxMappingRuleDraftModel.binding_id == binding.id,
                )
            )
        rule_models = tuple(
            ABoxMappingRuleDraftModel(
                id=uuid7(),
                workspace_id=workspace_id,
                draft_id=draft_id,
                binding_id=binding.id,
                ordinal=ordinal,
                method=method,
                source_field_path=source_field_path,
                target_stable_element_id=target_element_id,
                transform_id="IDENTITY",
                transform_version="1",
                created_at=now,
                updated_at=now,
            )
            for ordinal, (method, source_field_path, target_element_id) in enumerate(rules)
        )
        self._session.add_all(rule_models)
        draft_model.last_autosaved_at = now
        draft_model.updated_at = now
        draft_model.version += 1
        try:
            await self._session.flush()
            draft_record = _draft_record(draft_model)
            binding_record = _binding_record(
                binding,
                source=source_reference,
                source_name=source_asset.name,
                rules=rule_models,
            )
            await idempotency.save_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                result=abox_binding_result(draft_record, binding_record),
            )
            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()
            raise ConflictError("The A-Box binding conflicts with current Draft state.") from error
        return draft_record, binding_record

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
