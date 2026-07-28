from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.dto import (
    IdempotencyRecord,
    KnowledgeStudioABoxRecord,
    KnowledgeStudioBindingRecord,
    KnowledgeStudioDomainOption,
    KnowledgeStudioDraftRecord,
    KnowledgeStudioMappingRuleRecord,
    KnowledgeStudioPreflightRecord,
    KnowledgeStudioReleaseRecord,
    KnowledgeStudioTBoxElementRecord,
    KnowledgeStudioValidationEvidence,
)
from datariver.application.ports import KnowledgeStudioStore
from datariver.domain.authz import Classification
from datariver.domain.catalog import DATASET_ASSET_TYPES
from datariver.domain.common import (
    ConflictError,
    DomainEvent,
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
    require_studio_transition,
    require_studio_version,
    validate_endpoint_alias,
    validate_source_field_path,
    validate_stable_element_id,
    validate_studio_name,
)
from datariver.infrastructure.db.governance import SqlIdempotencyStore, SqlOutboxWriter
from datariver.infrastructure.db.models.catalog import (
    AssetProjectionModel,
    CatalogVocabularyEntryModel,
)
from datariver.infrastructure.db.models.knowledge import GraphModel, OntologyVersionModel
from datariver.infrastructure.db.models.knowledge_studio import (
    ABoxBindingDraftModel,
    ABoxBindingVersionModel,
    ABoxMappingRuleDraftModel,
    ABoxMappingRuleVersionModel,
    KnowledgeSourceReferenceModel,
    KnowledgeStudioDraftModel,
    KnowledgeStudioPreflightCheckModel,
    KnowledgeStudioReleaseModel,
    OntologyElementModel,
    TBoxDraftElementModel,
)

CREATE_OPERATION = "knowledge.studio_draft.create"
PREFLIGHT_CONTRACT_VERSION = "KNOWLEDGE_STUDIO_PREFLIGHT_V1"
RELEASE_CONTRACT_VERSION = "KNOWLEDGE_STUDIO_RELEASE_V1"


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
        submitted_preflight_check_id=model.submitted_preflight_check_id,
        reviewed_by=model.reviewed_by,
        reviewed_at=model.reviewed_at,
        review_reason=model.review_reason,
        published_by=model.published_by,
        published_at=model.published_at,
        materialized_graph_id=model.materialized_graph_id,
        materialized_ontology_version_id=model.materialized_ontology_version_id,
        published_studio_release_id=model.published_studio_release_id,
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


def _preflight_record(
    model: KnowledgeStudioPreflightCheckModel,
) -> KnowledgeStudioPreflightRecord:
    return KnowledgeStudioPreflightRecord(
        status=model.status,
        valid=model.valid,
        draft_version=model.draft_version,
        checked_at=model.checked_at,
        evidence=tuple(
            KnowledgeStudioValidationEvidence(
                severity=str(item["severity"]),
                code=str(item["code"]),
                location=str(item["location"]),
                message=str(item["message"]),
            )
            for item in model.evidence_document
        ),
        receipt_id=model.id,
        contract_hash=model.contract_hash,
    )


def _studio_release_record(
    model: KnowledgeStudioReleaseModel,
    *,
    archived_studio_release_id: UUID | None,
) -> KnowledgeStudioReleaseRecord:
    return KnowledgeStudioReleaseRecord(
        studio_release_id=model.id,
        graph_id=model.graph_id,
        ontology_version_id=model.ontology_version_id,
        release_no=model.release_no,
        state=model.state,
        contract_version=model.contract_version,
        contract_hash=model.contract_hash,
        tbox_hash=model.tbox_hash,
        abox_hash=model.abox_hash,
        supersedes_studio_release_id=model.supersedes_studio_release_id,
        reviewed_by=model.reviewed_by,
        published_by=model.published_by,
        published_at=model.published_at,
        archived_studio_release_id=archived_studio_release_id,
    )


def _element_document(model: TBoxDraftElementModel) -> dict[str, object]:
    return {
        "stable_element_id": model.stable_element_id,
        "kind": model.kind,
        "canonical_name": model.canonical_name,
        "display_name": model.display_name,
        "parent_stable_element_id": model.parent_stable_element_id,
        "source_stable_element_id": model.source_stable_element_id,
        "target_stable_element_id": model.target_stable_element_id,
        "data_type": model.data_type,
        "nullable": model.nullable,
        "ordinal": model.ordinal,
    }


def _rule_document(model: ABoxMappingRuleDraftModel) -> dict[str, object]:
    return {
        "ordinal": model.ordinal,
        "method": model.method,
        "source_field_path": model.source_field_path,
        "target_stable_element_id": model.target_stable_element_id,
        "transform_id": model.transform_id,
        "transform_version": model.transform_version,
        "source_unit": model.source_unit,
        "canonical_unit": model.canonical_unit,
    }


def _binding_document(
    model: ABoxBindingDraftModel,
    source: KnowledgeSourceReferenceModel,
    rules: tuple[ABoxMappingRuleDraftModel, ...],
) -> dict[str, object]:
    return {
        "target_stable_element_id": model.target_stable_element_id,
        "source": {
            "source_reference_id": str(source.id),
            "kind": source.kind,
            "catalog_asset_id": str(source.catalog_asset_id),
            "source_version": source.source_version,
            "projection_source_version": source.projection_source_version,
            "classification": source.classification,
            "selection_hash": source.selection_hash,
        },
        "rules": [_rule_document(item) for item in rules],
    }


def _version_rule_document(model: ABoxMappingRuleVersionModel) -> dict[str, object]:
    return {
        "ordinal": model.ordinal,
        "method": model.method,
        "source_field_path": model.source_field_path,
        "target_stable_element_id": model.target_stable_element_id,
        "transform_id": model.transform_id,
        "transform_version": model.transform_version,
        "source_unit": model.source_unit,
        "canonical_unit": model.canonical_unit,
    }


def _version_binding_document(
    model: ABoxBindingVersionModel,
    source: KnowledgeSourceReferenceModel,
    rules: tuple[ABoxMappingRuleVersionModel, ...],
) -> dict[str, object]:
    return {
        "target_stable_element_id": model.target_stable_element_id,
        "source": {
            "source_reference_id": str(source.id),
            "kind": source.kind,
            "catalog_asset_id": str(source.catalog_asset_id),
            "source_version": source.source_version,
            "projection_source_version": source.projection_source_version,
            "classification": source.classification,
            "selection_hash": source.selection_hash,
        },
        "rules": [_version_rule_document(item) for item in rules],
    }


@dataclass(frozen=True, slots=True)
class _StudioContract:
    elements: tuple[TBoxDraftElementModel, ...]
    bindings: tuple[tuple[ABoxBindingDraftModel, KnowledgeSourceReferenceModel], ...]
    rules_by_binding: dict[UUID, tuple[ABoxMappingRuleDraftModel, ...]]
    tbox_document: dict[str, object]
    abox_document: dict[str, object]
    contract_document: dict[str, object]
    tbox_hash: str
    abox_hash: str
    contract_hash: str


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
        "submitted_preflight_check_id": (
            str(record.submitted_preflight_check_id)
            if record.submitted_preflight_check_id
            else None
        ),
        "reviewed_by": str(record.reviewed_by) if record.reviewed_by else None,
        "reviewed_at": record.reviewed_at.isoformat() if record.reviewed_at else None,
        "review_reason": record.review_reason,
        "published_by": str(record.published_by) if record.published_by else None,
        "published_at": record.published_at.isoformat() if record.published_at else None,
        "materialized_graph_id": (
            str(record.materialized_graph_id) if record.materialized_graph_id else None
        ),
        "materialized_ontology_version_id": (
            str(record.materialized_ontology_version_id)
            if record.materialized_ontology_version_id
            else None
        ),
        "published_studio_release_id": (
            str(record.published_studio_release_id) if record.published_studio_release_id else None
        ),
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


def _optional_bounded_str(
    result: dict[str, Any],
    key: str,
    *,
    maximum_length: int,
) -> str | None:
    value = result.get(key)
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not 1 <= len(value) <= maximum_length
    ):
        raise ConflictError("The idempotent Knowledge Studio result is invalid.")
    return value


def _required_datetime(result: dict[str, Any], key: str) -> datetime:
    value = datetime.fromisoformat(_required_str(result, key))
    if value.tzinfo is None:
        raise ConflictError("The idempotent Knowledge Studio result is invalid.")
    return value


def _optional_datetime(result: dict[str, Any], key: str) -> datetime | None:
    raw_value = result.get(key)
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise ConflictError("The idempotent Knowledge Studio result is invalid.")
    value = datetime.fromisoformat(raw_value)
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
            submitted_preflight_check_id=_optional_uuid(
                result,
                "submitted_preflight_check_id",
            ),
            reviewed_by=_optional_uuid(result, "reviewed_by"),
            reviewed_at=_optional_datetime(result, "reviewed_at"),
            review_reason=_optional_bounded_str(
                result,
                "review_reason",
                maximum_length=2_000,
            ),
            published_by=_optional_uuid(result, "published_by"),
            published_at=_optional_datetime(result, "published_at"),
            materialized_graph_id=_optional_uuid(result, "materialized_graph_id"),
            materialized_ontology_version_id=_optional_uuid(
                result,
                "materialized_ontology_version_id",
            ),
            published_studio_release_id=_optional_uuid(
                result,
                "published_studio_release_id",
            ),
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
        actor_id: UUID,
        draft_id: UUID,
    ) -> KnowledgeStudioDraftRecord | None:
        model = (
            await self._session.scalars(
                select(KnowledgeStudioDraftModel).where(
                    KnowledgeStudioDraftModel.workspace_id == workspace_id,
                    KnowledgeStudioDraftModel.id == draft_id,
                    or_(
                        KnowledgeStudioDraftModel.author_id == actor_id,
                        KnowledgeStudioDraftModel.state.in_(("REVIEW", "PUBLISHED")),
                    ),
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
        actor_id: UUID,
        draft_id: UUID,
    ) -> KnowledgeStudioABoxRecord | None:
        draft_model = (
            await self._session.scalars(
                select(KnowledgeStudioDraftModel).where(
                    KnowledgeStudioDraftModel.workspace_id == workspace_id,
                    KnowledgeStudioDraftModel.id == draft_id,
                    or_(
                        KnowledgeStudioDraftModel.author_id == actor_id,
                        KnowledgeStudioDraftModel.state.in_(("REVIEW", "PUBLISHED")),
                    ),
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

    async def record_preflight(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        draft_id: UUID,
        expected_version: int,
        status: str,
        valid: bool,
        evidence: tuple[KnowledgeStudioValidationEvidence, ...],
        checked_at: datetime,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioPreflightRecord:
        operation = f"knowledge.studio.preflight:{draft_id}"
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
            receipt_id = _optional_uuid(existing.result, "receipt_id")
            if receipt_id is None:
                raise ConflictError("The idempotent pre-flight result is invalid.")
            receipt = await self._session.get(KnowledgeStudioPreflightCheckModel, receipt_id)
            if (
                receipt is None
                or receipt.workspace_id != workspace_id
                or receipt.draft_id != draft_id
                or receipt.checked_by != actor_id
            ):
                raise ConflictError("The idempotent pre-flight result is unavailable.")
            return _preflight_record(receipt)

        draft = await self._locked_actor_draft(
            workspace_id=workspace_id,
            actor_id=actor_id,
            draft_id=draft_id,
        )
        self._require_expected_version(draft, expected_version)
        if draft.state not in {"DRAFT", "REVIEW"}:
            raise ConflictError("Only a DRAFT or REVIEW Studio contract can be pre-flight checked.")
        if draft.state == "REVIEW" and draft.author_id == actor_id:
            raise ConflictError("A Studio author cannot perform the independent review pre-flight.")
        contract = await self._load_contract(
            workspace_id=workspace_id,
            draft=draft,
            lock=True,
        )
        evidence_document = [
            {
                "severity": item.severity,
                "code": item.code,
                "location": item.location,
                "message": item.message,
            }
            for item in evidence
        ]
        if len(evidence_document) > 2_000:
            raise ConflictError("The pre-flight evidence exceeds the persistence bound.")
        if status not in {"PASS", "FAIL", "UNAVAILABLE"} or valid != (status == "PASS"):
            raise ConflictError("The pre-flight result shape is invalid.")
        receipt = KnowledgeStudioPreflightCheckModel(
            id=uuid7(),
            workspace_id=workspace_id,
            draft_id=draft_id,
            draft_version=draft.version,
            contract_hash=contract.contract_hash,
            status=status,
            valid=valid,
            validation_contract_version=PREFLIGHT_CONTRACT_VERSION,
            evidence_document=evidence_document,
            evidence_hash=canonical_json_hash(evidence_document),
            checked_by=actor_id,
            checked_at=checked_at,
        )
        self._session.add(receipt)
        try:
            await self._session.flush()
            await idempotency.save_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                result={"receipt_id": str(receipt.id)},
            )
            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()
            raise ConflictError(
                "The pre-flight receipt conflicts with current Draft state."
            ) from error
        return _preflight_record(receipt)

    async def submit_review(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioDraftRecord:
        operation = f"knowledge.studio.submit_review:{draft_id}"
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
        draft = await self._locked_draft(
            workspace_id=workspace_id,
            author_id=author_id,
            draft_id=draft_id,
        )
        self._require_expected_version(draft, expected_version)
        self._require_mutable(draft)
        if draft.current_step != "ABOX":
            raise ConflictError("Complete Data Enricher before requesting independent review.")
        await self._require_domain(
            workspace_id=workspace_id,
            domain_id=draft.domain_ref_id,
            domain_source_version=draft.domain_source_version,
        )
        contract = await self._load_contract(
            workspace_id=workspace_id,
            draft=draft,
            lock=True,
        )
        if not any(item.kind == "CLASS" for item in contract.elements):
            raise ConflictError("At least one accepted T-Box Class is required for review.")
        require_studio_transition(StudioDraftState.DRAFT, StudioDraftState.REVIEW)
        draft.state = StudioDraftState.REVIEW.value
        draft.review_requested_at = utc_now()
        draft.updated_at = utc_now()
        draft.version += 1
        return await self._save_mutation(
            model=draft,
            idempotency=idempotency,
            workspace_id=workspace_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def discard_draft(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioDraftRecord:
        operation = f"knowledge.studio.discard:{draft_id}"
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
        draft = await self._locked_draft(
            workspace_id=workspace_id,
            author_id=author_id,
            draft_id=draft_id,
        )
        self._require_expected_version(draft, expected_version)
        require_studio_transition(
            StudioDraftState(draft.state),
            StudioDraftState.DISCARDED,
        )
        now = utc_now()
        draft.state = StudioDraftState.DISCARDED.value
        draft.discarded_at = now
        draft.discarded_by = author_id
        draft.updated_at = now
        draft.version += 1
        return await self._save_mutation(
            model=draft,
            idempotency=idempotency,
            workspace_id=workspace_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def publish_draft(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        draft_id: UUID,
        review_reason: str,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> tuple[KnowledgeStudioDraftRecord, KnowledgeStudioReleaseRecord]:
        operation = f"knowledge.studio.publish:{draft_id}"
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
            return await self._published_replay(
                existing=existing,
                workspace_id=workspace_id,
                actor_id=actor_id,
                draft_id=draft_id,
                request_hash=request_hash,
            )

        reason = review_reason.strip()
        if not 1 <= len(reason) <= 2_000:
            raise ValidationError("An independent review reason is required.")
        draft = await self._locked_actor_draft(
            workspace_id=workspace_id,
            actor_id=actor_id,
            draft_id=draft_id,
        )
        self._require_expected_version(draft, expected_version)
        if draft.state != StudioDraftState.REVIEW.value:
            raise ConflictError("Only a REVIEW Knowledge Studio draft can be published.")
        if draft.author_id == actor_id:
            raise ConflictError("A Studio author cannot review or publish their own Draft.")
        await self._require_domain(
            workspace_id=workspace_id,
            domain_id=draft.domain_ref_id,
            domain_source_version=draft.domain_source_version,
        )
        contract = await self._load_contract(
            workspace_id=workspace_id,
            draft=draft,
            lock=True,
        )
        receipt = (
            await self._session.scalars(
                select(KnowledgeStudioPreflightCheckModel)
                .where(
                    KnowledgeStudioPreflightCheckModel.workspace_id == workspace_id,
                    KnowledgeStudioPreflightCheckModel.draft_id == draft_id,
                    KnowledgeStudioPreflightCheckModel.draft_version == draft.version,
                    KnowledgeStudioPreflightCheckModel.contract_hash == contract.contract_hash,
                    KnowledgeStudioPreflightCheckModel.status == "PASS",
                    KnowledgeStudioPreflightCheckModel.valid.is_(True),
                    KnowledgeStudioPreflightCheckModel.checked_by == actor_id,
                )
                .order_by(
                    KnowledgeStudioPreflightCheckModel.checked_at.desc(),
                    KnowledgeStudioPreflightCheckModel.id.desc(),
                )
                .limit(1)
                .with_for_update(read=True)
            )
        ).one_or_none()
        if receipt is None:
            raise ConflictError(
                "Publishing requires an exact PASS pre-flight receipt "
                "from the independent reviewer."
            )

        graph, previous_release = await self._materialization_target(
            workspace_id=workspace_id,
            draft=draft,
            actor_id=actor_id,
        )
        release_no = (
            int(
                (
                    await self._session.scalar(
                        select(
                            func.coalesce(
                                func.max(KnowledgeStudioReleaseModel.release_no),
                                0,
                            )
                        ).where(KnowledgeStudioReleaseModel.graph_id == graph.id)
                    )
                )
                or 0
            )
            + 1
        )
        now = utc_now()
        archived_release_id: UUID | None = None
        if previous_release is not None:
            previous_release.state = "ARCHIVED"
            previous_release.archived_at = now
            previous_release.archived_by = actor_id
            archived_release_id = previous_release.id
            await self._flush_publication((previous_release,))
        ontology = OntologyVersionModel(
            id=uuid7(),
            workspace_id=workspace_id,
            graph_id=graph.id,
            version=f"ks-{draft.id}",
            schema_document=contract.tbox_document,
            checksum=contract.tbox_hash,
            status="PUBLISHED",
            schema_contract_version="KNOWLEDGE_STUDIO_TBOX_V1",
            base_ontology_version_id=draft.base_ontology_version_id,
            created_by=draft.author_id,
            created_at=now,
            updated_at=now,
        )
        self._session.add(ontology)
        await self._flush_publication((ontology,))

        ontology_element_by_stable_id: dict[str, OntologyElementModel] = {}
        for element in contract.elements:
            document = _element_document(element)
            canonical_element = OntologyElementModel(
                id=uuid7(),
                workspace_id=workspace_id,
                graph_id=graph.id,
                ontology_version_id=ontology.id,
                stable_element_id=element.stable_element_id,
                kind=element.kind,
                canonical_name=element.canonical_name,
                display_name=element.display_name,
                ordinal=element.ordinal,
                element_document=document,
                element_hash=canonical_json_hash(document),
            )
            ontology_element_by_stable_id[element.stable_element_id] = canonical_element
            self._session.add(canonical_element)
        await self._flush_publication()

        studio_release = KnowledgeStudioReleaseModel(
            id=uuid7(),
            workspace_id=workspace_id,
            graph_id=graph.id,
            source_draft_id=draft.id,
            source_draft_version=draft.version,
            release_no=release_no,
            state="ACTIVE",
            ontology_version_id=ontology.id,
            preflight_check_id=receipt.id,
            supersedes_studio_release_id=previous_release.id if previous_release else None,
            contract_version=RELEASE_CONTRACT_VERSION,
            contract_hash=contract.contract_hash,
            tbox_hash=contract.tbox_hash,
            abox_hash=contract.abox_hash,
            author_id=draft.author_id,
            reviewed_by=actor_id,
            review_reason=reason,
            published_by=actor_id,
            published_at=now,
        )
        self._session.add(studio_release)
        await self._flush_publication((studio_release,))

        binding_versions: list[ABoxBindingVersionModel] = []
        rule_versions: list[ABoxMappingRuleVersionModel] = []
        for ordinal, (binding, source) in enumerate(contract.bindings):
            rules = contract.rules_by_binding.get(binding.id, ())
            binding_document = _binding_document(binding, source, rules)
            target_element = ontology_element_by_stable_id.get(binding.target_stable_element_id)
            if target_element is None:
                raise ConflictError("A published binding target is absent from the T-Box.")
            binding_version = ABoxBindingVersionModel(
                id=uuid7(),
                workspace_id=workspace_id,
                graph_id=graph.id,
                studio_release_id=studio_release.id,
                ontology_version_id=ontology.id,
                target_ontology_element_id=target_element.id,
                target_stable_element_id=binding.target_stable_element_id,
                source_reference_id=source.id,
                ordinal=ordinal,
                mapping_hash=canonical_json_hash(binding_document),
                created_by=draft.author_id,
                created_at=now,
            )
            binding_versions.append(binding_version)
            self._session.add(binding_version)
            for rule in rules:
                rule_target = ontology_element_by_stable_id.get(rule.target_stable_element_id)
                if rule_target is None:
                    raise ConflictError("A published mapping target is absent from the T-Box.")
                rule_versions.append(
                    ABoxMappingRuleVersionModel(
                        id=uuid7(),
                        workspace_id=workspace_id,
                        studio_release_id=studio_release.id,
                        binding_version_id=binding_version.id,
                        ontology_version_id=ontology.id,
                        target_ontology_element_id=rule_target.id,
                        ordinal=rule.ordinal,
                        method=rule.method,
                        source_field_path=rule.source_field_path,
                        target_stable_element_id=rule.target_stable_element_id,
                        transform_id=rule.transform_id,
                        transform_version=rule.transform_version,
                        source_unit=rule.source_unit,
                        canonical_unit=rule.canonical_unit,
                    )
                )
        self._session.add_all(rule_versions)

        graph.active_studio_release_id = studio_release.id
        graph.status = "PUBLISHED"
        graph.name = draft.name
        graph.classification = draft.classification
        graph.domain_ref_id = draft.domain_ref_id
        graph.domain_ref_kind = "DOMAIN"
        graph.domain_source_version = draft.domain_source_version
        graph.updated_by = actor_id
        graph.updated_at = now
        if previous_release is not None:
            graph.version += 1

        require_studio_transition(StudioDraftState.REVIEW, StudioDraftState.PUBLISHED)
        draft.state = StudioDraftState.PUBLISHED.value
        draft.submitted_preflight_check_id = receipt.id
        draft.reviewed_by = actor_id
        draft.reviewed_at = now
        draft.review_reason = reason
        draft.published_by = actor_id
        draft.published_at = now
        draft.materialized_graph_id = graph.id
        draft.materialized_ontology_version_id = ontology.id
        draft.published_studio_release_id = studio_release.id
        draft.updated_at = now
        draft.version += 1

        await self._flush_publication()
        await self._verify_materialized_contract(
            workspace_id=workspace_id,
            studio_release=studio_release,
            contract=contract,
        )
        await SqlOutboxWriter(self._session).add_events(
            [
                DomainEvent.create(
                    event_type="knowledge.studio_release.published.v1",
                    aggregate_type="knowledge_graph",
                    aggregate_id=graph.id,
                    workspace_id=workspace_id,
                    payload={
                        "draft_id": str(draft.id),
                        "graph_id": str(graph.id),
                        "ontology_version_id": str(ontology.id),
                        "studio_release_id": str(studio_release.id),
                        "contract_hash": contract.contract_hash,
                    },
                )
            ]
        )
        result: dict[str, object] = {
            "draft_id": str(draft.id),
            "studio_release_id": str(studio_release.id),
            "published_by": str(actor_id),
            "archived_studio_release_id": (
                str(archived_release_id) if archived_release_id else None
            ),
        }
        await idempotency.save_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
            request_hash=request_hash,
            result=result,
        )
        try:
            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()
            raise ConflictError(
                "The Studio Release conflicts with the current graph or Draft version."
            ) from error
        return (
            _draft_record(draft),
            _studio_release_record(
                studio_release,
                archived_studio_release_id=archived_release_id,
            ),
        )

    async def _materialization_target(
        self,
        *,
        workspace_id: UUID,
        draft: KnowledgeStudioDraftModel,
        actor_id: UUID,
    ) -> tuple[GraphModel, KnowledgeStudioReleaseModel | None]:
        if draft.kind == StudioDraftKind.CREATE.value:
            await self._require_alias_available(
                workspace_id=workspace_id,
                endpoint_alias=draft.endpoint_alias,
            )
            now = utc_now()
            graph = GraphModel(
                id=uuid7(),
                workspace_id=workspace_id,
                slug=draft.endpoint_alias,
                name=draft.name,
                graph_type="CURATED_KNOWLEDGE",
                status="PUBLISHED",
                active_release_id=None,
                active_studio_release_id=None,
                classification=draft.classification,
                domain_ref_id=draft.domain_ref_id,
                domain_ref_kind="DOMAIN",
                domain_source_version=draft.domain_source_version,
                created_by=draft.author_id,
                updated_by=actor_id,
                created_at=now,
                updated_at=now,
                version=1,
            )
            self._session.add(graph)
            await self._flush_publication((graph,))
            return graph, None
        if draft.base_graph_id is None or draft.base_ontology_version_id is None:
            raise ConflictError("The Studio EDIT Draft has no complete immutable base.")
        existing_graph = (
            await self._session.scalars(
                select(GraphModel)
                .where(
                    GraphModel.workspace_id == workspace_id,
                    GraphModel.id == draft.base_graph_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        if existing_graph is None:
            raise ConflictError("The Studio EDIT target graph is unavailable.")
        graph = existing_graph
        if graph.slug != draft.endpoint_alias:
            raise ConflictError("A published graph endpoint alias is immutable.")
        if graph.active_release_id != draft.base_release_id:
            raise ConflictError("The Studio EDIT instance Release base changed.")
        previous_release = (
            await self._session.scalars(
                select(KnowledgeStudioReleaseModel)
                .where(
                    KnowledgeStudioReleaseModel.workspace_id == workspace_id,
                    KnowledgeStudioReleaseModel.graph_id == graph.id,
                    KnowledgeStudioReleaseModel.id == graph.active_studio_release_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        if (
            previous_release is None
            or previous_release.state != "ACTIVE"
            or previous_release.ontology_version_id != draft.base_ontology_version_id
        ):
            raise ConflictError("The Studio EDIT schema base changed.")
        return graph, previous_release

    async def _load_contract(
        self,
        *,
        workspace_id: UUID,
        draft: KnowledgeStudioDraftModel,
        lock: bool,
    ) -> _StudioContract:
        elements_statement = (
            select(TBoxDraftElementModel)
            .where(
                TBoxDraftElementModel.workspace_id == workspace_id,
                TBoxDraftElementModel.draft_id == draft.id,
            )
            .order_by(
                TBoxDraftElementModel.ordinal,
                TBoxDraftElementModel.stable_element_id,
            )
            .limit(501)
        )
        bindings_statement = (
            select(ABoxBindingDraftModel, KnowledgeSourceReferenceModel)
            .join(
                KnowledgeSourceReferenceModel,
                (KnowledgeSourceReferenceModel.workspace_id == ABoxBindingDraftModel.workspace_id)
                & (KnowledgeSourceReferenceModel.id == ABoxBindingDraftModel.source_reference_id),
            )
            .where(
                ABoxBindingDraftModel.workspace_id == workspace_id,
                ABoxBindingDraftModel.draft_id == draft.id,
            )
            .order_by(ABoxBindingDraftModel.target_stable_element_id)
            .limit(501)
        )
        if lock:
            elements_statement = elements_statement.with_for_update(read=True)
            bindings_statement = bindings_statement.with_for_update(read=True)
        elements = tuple((await self._session.scalars(elements_statement)).all())
        binding_rows = tuple(
            (row[0], row[1]) for row in (await self._session.execute(bindings_statement)).all()
        )
        if len(elements) > 500 or len(binding_rows) > 500:
            raise ConflictError("The Studio contract exceeds the publication bound.")
        binding_ids = tuple(binding.id for binding, _source in binding_rows)
        rule_models: tuple[ABoxMappingRuleDraftModel, ...] = ()
        if binding_ids:
            rules_statement = (
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
            if lock:
                rules_statement = rules_statement.with_for_update(read=True)
            rule_models = tuple((await self._session.scalars(rules_statement)).all())
        if len(rule_models) > 2_000:
            raise ConflictError("The Studio mapping rule set exceeds the publication bound.")
        mutable_rules_by_binding: dict[UUID, list[ABoxMappingRuleDraftModel]] = {}
        for rule in rule_models:
            mutable_rules_by_binding.setdefault(rule.binding_id, []).append(rule)
        rules_by_binding = {
            binding_id: tuple(rules) for binding_id, rules in mutable_rules_by_binding.items()
        }
        element_documents = [_element_document(item) for item in elements]
        tbox_document: dict[str, object] = {
            "contract_version": "KNOWLEDGE_STUDIO_TBOX_V1",
            "entity_types": sorted(
                item.canonical_name for item in elements if item.kind == "CLASS"
            ),
            "edge_types": sorted(
                item.canonical_name for item in elements if item.kind == "RELATION"
            ),
            "elements": element_documents,
        }
        binding_documents = [
            _binding_document(
                binding,
                source,
                rules_by_binding.get(binding.id, ()),
            )
            for binding, source in binding_rows
        ]
        abox_document: dict[str, object] = {
            "contract_version": "KNOWLEDGE_STUDIO_ABOX_MAPPING_V1",
            "bindings": binding_documents,
        }
        tbox_hash = canonical_json_hash(tbox_document)
        abox_hash = canonical_json_hash(abox_document)
        contract_document: dict[str, object] = {
            "contract_version": RELEASE_CONTRACT_VERSION,
            "draft": {
                "draft_id": str(draft.id),
                "kind": draft.kind,
                "name": draft.name,
                "endpoint_alias": draft.endpoint_alias,
                "domain_id": str(draft.domain_ref_id),
                "domain_source_version": draft.domain_source_version,
                "classification": draft.classification,
                "base_graph_id": str(draft.base_graph_id) if draft.base_graph_id else None,
                "base_ontology_version_id": (
                    str(draft.base_ontology_version_id) if draft.base_ontology_version_id else None
                ),
                "base_release_id": str(draft.base_release_id) if draft.base_release_id else None,
            },
            "tbox_hash": tbox_hash,
            "abox_hash": abox_hash,
        }
        return _StudioContract(
            elements=elements,
            bindings=binding_rows,
            rules_by_binding=rules_by_binding,
            tbox_document=tbox_document,
            abox_document=abox_document,
            contract_document=contract_document,
            tbox_hash=tbox_hash,
            abox_hash=abox_hash,
            contract_hash=canonical_json_hash(contract_document),
        )

    async def _verify_materialized_contract(
        self,
        *,
        workspace_id: UUID,
        studio_release: KnowledgeStudioReleaseModel,
        contract: _StudioContract,
    ) -> None:
        element_models = tuple(
            (
                await self._session.scalars(
                    select(OntologyElementModel)
                    .where(
                        OntologyElementModel.workspace_id == workspace_id,
                        OntologyElementModel.ontology_version_id
                        == studio_release.ontology_version_id,
                    )
                    .order_by(
                        OntologyElementModel.ordinal,
                        OntologyElementModel.stable_element_id,
                    )
                    .execution_options(populate_existing=True)
                )
            ).all()
        )
        element_documents = [item.element_document for item in element_models]
        if any(
            item.element_hash != canonical_json_hash(item.element_document)
            for item in element_models
        ):
            raise ConflictError("The canonical T-Box element read-back hash is invalid.")
        persisted_tbox = dict(contract.tbox_document)
        persisted_tbox["elements"] = element_documents
        if canonical_json_hash(persisted_tbox) != studio_release.tbox_hash:
            raise ConflictError("The canonical T-Box read-back verification failed.")

        binding_rows = tuple(
            (
                await self._session.execute(
                    select(ABoxBindingVersionModel, KnowledgeSourceReferenceModel)
                    .join(
                        KnowledgeSourceReferenceModel,
                        (
                            KnowledgeSourceReferenceModel.workspace_id
                            == ABoxBindingVersionModel.workspace_id
                        )
                        & (
                            KnowledgeSourceReferenceModel.id
                            == ABoxBindingVersionModel.source_reference_id
                        ),
                    )
                    .where(
                        ABoxBindingVersionModel.workspace_id == workspace_id,
                        ABoxBindingVersionModel.studio_release_id == studio_release.id,
                    )
                    .order_by(ABoxBindingVersionModel.ordinal)
                    .execution_options(populate_existing=True)
                )
            ).all()
        )
        binding_ids = tuple(binding.id for binding, _source in binding_rows)
        rules: tuple[ABoxMappingRuleVersionModel, ...] = ()
        if binding_ids:
            rules = tuple(
                (
                    await self._session.scalars(
                        select(ABoxMappingRuleVersionModel)
                        .where(
                            ABoxMappingRuleVersionModel.workspace_id == workspace_id,
                            ABoxMappingRuleVersionModel.binding_version_id.in_(binding_ids),
                        )
                        .order_by(
                            ABoxMappingRuleVersionModel.binding_version_id,
                            ABoxMappingRuleVersionModel.ordinal,
                        )
                        .execution_options(populate_existing=True)
                    )
                ).all()
            )
        rules_by_binding: dict[UUID, list[ABoxMappingRuleVersionModel]] = {}
        for rule in rules:
            rules_by_binding.setdefault(rule.binding_version_id, []).append(rule)
        binding_documents = [
            _version_binding_document(
                binding,
                source,
                tuple(rules_by_binding.get(binding.id, ())),
            )
            for binding, source in binding_rows
        ]
        if any(
            binding.mapping_hash != canonical_json_hash(document)
            for (binding, _source), document in zip(
                binding_rows,
                binding_documents,
                strict=True,
            )
        ):
            raise ConflictError("The canonical Mapping Contract read-back hash is invalid.")
        persisted_abox: dict[str, object] = {
            "contract_version": "KNOWLEDGE_STUDIO_ABOX_MAPPING_V1",
            "bindings": binding_documents,
        }
        if canonical_json_hash(persisted_abox) != studio_release.abox_hash:
            raise ConflictError("The canonical A-Box mapping read-back verification failed.")
        if (
            studio_release.contract_hash != contract.contract_hash
            or studio_release.tbox_hash != contract.tbox_hash
            or studio_release.abox_hash != contract.abox_hash
        ):
            raise ConflictError("The Studio Release manifest read-back verification failed.")

    async def _published_replay(
        self,
        *,
        existing: IdempotencyRecord,
        workspace_id: UUID,
        actor_id: UUID,
        draft_id: UUID,
        request_hash: str,
    ) -> tuple[KnowledgeStudioDraftRecord, KnowledgeStudioReleaseRecord]:
        if existing.request_hash != request_hash:
            raise ConflictError("The idempotency key was used with a different request.")
        existing_draft_id = _optional_uuid(existing.result, "draft_id")
        studio_release_id = _optional_uuid(existing.result, "studio_release_id")
        published_by = _optional_uuid(existing.result, "published_by")
        archived_id = _optional_uuid(existing.result, "archived_studio_release_id")
        if existing_draft_id != draft_id or studio_release_id is None or published_by != actor_id:
            raise ConflictError("The idempotent Studio publication result is invalid.")
        draft = await self._session.get(KnowledgeStudioDraftModel, draft_id)
        release = await self._session.get(KnowledgeStudioReleaseModel, studio_release_id)
        if (
            draft is None
            or release is None
            or draft.workspace_id != workspace_id
            or release.workspace_id != workspace_id
            or draft.state != "PUBLISHED"
            or draft.published_studio_release_id != release.id
            or release.published_by != actor_id
            or release.reviewed_by == release.author_id
        ):
            raise ConflictError("The idempotent Studio publication result is unavailable.")
        return (
            _draft_record(draft),
            _studio_release_record(
                release,
                archived_studio_release_id=archived_id,
            ),
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

    async def _flush_publication(
        self,
        objects: Sequence[Any] | None = None,
    ) -> None:
        try:
            await self._session.flush(objects)
        except IntegrityError as error:
            await self._session.rollback()
            raise ConflictError(
                "The Studio Release conflicts with the current graph or Draft version."
            ) from error

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

    async def _locked_actor_draft(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        draft_id: UUID,
    ) -> KnowledgeStudioDraftModel:
        model = (
            await self._session.scalars(
                select(KnowledgeStudioDraftModel)
                .where(
                    KnowledgeStudioDraftModel.workspace_id == workspace_id,
                    KnowledgeStudioDraftModel.id == draft_id,
                    or_(
                        KnowledgeStudioDraftModel.author_id == actor_id,
                        KnowledgeStudioDraftModel.state.in_(("REVIEW", "PUBLISHED")),
                    ),
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
