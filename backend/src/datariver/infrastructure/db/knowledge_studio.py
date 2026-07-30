from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, cast, delete, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from datariver.application.dto import (
    IdempotencyRecord,
    KnowledgeGraphRecord,
    KnowledgeStudioABoxRecord,
    KnowledgeStudioBindingRecord,
    KnowledgeStudioDomainOption,
    KnowledgeStudioDraftRecord,
    KnowledgeStudioIngestionJobRecord,
    KnowledgeStudioManagedDomainRecord,
    KnowledgeStudioMappingRuleRecord,
    KnowledgeStudioPreflightRecord,
    KnowledgeStudioReleaseRecord,
    KnowledgeStudioTBoxBlockRecord,
    KnowledgeStudioTBoxElementRecord,
    KnowledgeStudioTBoxProposalConflictRecord,
    KnowledgeStudioTBoxProposalRecord,
    KnowledgeStudioTBoxRecord,
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
    DEFAULT_KNOWLEDGE_DOMAIN_SOURCE_VERSION,
    DEFAULT_KNOWLEDGE_DOMAINS,
    DEFAULT_TBOX_BLOCK_WEIGHT,
    ABoxBindingReadiness,
    ABoxMappingMethod,
    StudioDraftKind,
    StudioDraftState,
    StudioStep,
    TBoxElementInput,
    TBoxElementKind,
    default_knowledge_domain_id,
    require_studio_transition,
    require_studio_version,
    validate_endpoint_alias,
    validate_endpoint_aliases,
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
    KnowledgeStudioIngestionJobModel,
    KnowledgeStudioPreflightCheckModel,
    KnowledgeStudioReleaseModel,
    OntologyElementModel,
    TBoxClassModel,
    TBoxDraftBlockModel,
    TBoxDraftElementModel,
    TBoxPropertyModel,
    TBoxProposalModel,
    TBoxRelationshipModel,
)

CREATE_OPERATION = "knowledge.studio_draft.create"
PREFLIGHT_CONTRACT_VERSION = "KNOWLEDGE_STUDIO_PREFLIGHT_V1"
RELEASE_CONTRACT_VERSION = "KNOWLEDGE_STUDIO_RELEASE_V1"


def _optional_document_string(document: dict[str, object], key: str) -> str | None:
    value = document.get(key)
    return value if isinstance(value, str) else None


def _optional_document_bool(document: dict[str, object], key: str) -> bool | None:
    value = document.get(key)
    return value if isinstance(value, bool) else None


def _optional_document_number(document: dict[str, object], key: str) -> float | None:
    value = document.get(key)
    return float(value) if isinstance(value, int | float) else None


def _optional_document_uuid(document: dict[str, object], key: str) -> UUID | None:
    value = document.get(key)
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _document_string_list(document: dict[str, object], key: str) -> list[str]:
    value = document.get(key)
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _tbox_input_document(value: TBoxElementInput) -> dict[str, object]:
    return {
        "stable_element_id": value.stable_element_id,
        "kind": value.kind.value,
        "canonical_name": value.canonical_name,
        "display_name": value.display_name,
        "parent_stable_element_id": value.parent_stable_element_id,
        "hierarchy_relation": value.hierarchy_relation,
        "source_stable_element_id": value.source_stable_element_id,
        "target_stable_element_id": value.target_stable_element_id,
        "data_type": value.data_type,
        "nullable": value.nullable,
        "definition": value.definition,
        "aliases": list(value.aliases),
        "unit": value.unit,
        "vector_index_enabled": value.vector_index_enabled,
        "metadata_reference_id": (
            str(value.metadata_reference_id) if value.metadata_reference_id else None
        ),
        "metadata_reference_urn": value.metadata_reference_urn,
        "layout_x": value.layout_x,
        "layout_y": value.layout_y,
    }


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
        endpoint_aliases=tuple(model.endpoint_aliases),
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


def _managed_domain_record(
    model: CatalogVocabularyEntryModel,
    *,
    asset_count: int,
) -> KnowledgeStudioManagedDomainRecord:
    return KnowledgeStudioManagedDomainRecord(
        domain_id=model.id,
        workspace_id=model.workspace_id,
        display_name=model.display_name,
        source_version=model.source_version,
        created_by=model.created_by,
        asset_count=asset_count,
        lifecycle=model.lifecycle,
        version=model.version,
        created_at=model.observed_at,
        updated_at=model.updated_at,
    )


def _managed_domain_result(
    record: KnowledgeStudioManagedDomainRecord,
    *,
    actor_id: UUID,
) -> dict[str, object]:
    return {
        "domain_id": str(record.domain_id),
        "workspace_id": str(record.workspace_id),
        "display_name": record.display_name,
        "source_version": record.source_version,
        "created_by": str(record.created_by) if record.created_by else None,
        "asset_count": record.asset_count,
        "lifecycle": record.lifecycle,
        "version": record.version,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "actor_id": str(actor_id),
    }


def _managed_domain_record_from_result(
    result: dict[str, Any],
    *,
    workspace_id: UUID,
    actor_id: UUID,
) -> KnowledgeStudioManagedDomainRecord:
    if _required_str(result, "actor_id") != str(actor_id):
        raise ConflictError("The idempotent managed-domain result belongs to another actor.")
    record = KnowledgeStudioManagedDomainRecord(
        domain_id=UUID(_required_str(result, "domain_id")),
        workspace_id=UUID(_required_str(result, "workspace_id")),
        display_name=_required_str(result, "display_name"),
        source_version=_required_str(result, "source_version"),
        created_by=_optional_uuid(result, "created_by"),
        asset_count=_required_int(result, "asset_count"),
        lifecycle=_required_str(result, "lifecycle"),
        version=_required_int(result, "version"),
        created_at=_required_datetime(result, "created_at"),
        updated_at=_required_datetime(result, "updated_at"),
    )
    if record.workspace_id != workspace_id:
        raise ConflictError("The idempotent managed-domain result belongs to another workspace.")
    return record


def _tbox_element_record(
    model: TBoxDraftElementModel,
    *,
    class_detail: TBoxClassModel | None = None,
    property_detail: TBoxPropertyModel | None = None,
    relationship_detail: TBoxRelationshipModel | None = None,
) -> KnowledgeStudioTBoxElementRecord:
    parent_stable_element_id = (
        class_detail.parent_stable_class_id
        if class_detail is not None
        else property_detail.owner_stable_class_id
        if property_detail is not None
        else None
    )
    metadata_reference_id = (
        class_detail.metadata_reference_id
        if class_detail is not None
        else property_detail.metadata_reference_id
        if property_detail is not None
        else relationship_detail.metadata_reference_id
        if relationship_detail is not None
        else None
    )
    metadata_reference_urn = (
        class_detail.metadata_reference_urn
        if class_detail is not None
        else property_detail.metadata_reference_urn
        if property_detail is not None
        else relationship_detail.metadata_reference_urn
        if relationship_detail is not None
        else None
    )
    return KnowledgeStudioTBoxElementRecord(
        stable_element_id=model.stable_element_id,
        kind=model.kind,
        canonical_name=model.canonical_name,
        display_name=model.display_name,
        parent_stable_element_id=parent_stable_element_id,
        hierarchy_relation=(
            class_detail.hierarchy_relation
            if class_detail is not None and class_detail.parent_stable_class_id is not None
            else None
        ),
        source_stable_element_id=(
            relationship_detail.source_stable_class_id if relationship_detail is not None else None
        ),
        target_stable_element_id=(
            relationship_detail.target_stable_class_id if relationship_detail is not None else None
        ),
        data_type=property_detail.data_type if property_detail is not None else None,
        nullable=property_detail.nullable if property_detail is not None else None,
        ordinal=model.ordinal,
        version=model.version,
        block_id=model.block_id,
        definition=model.definition,
        aliases=tuple(model.aliases),
        unit=property_detail.unit if property_detail is not None else None,
        vector_index_enabled=(
            property_detail.vector_index_enabled if property_detail is not None else False
        ),
        metadata_reference_id=metadata_reference_id,
        metadata_reference_urn=metadata_reference_urn,
        layout_x=model.layout_x,
        layout_y=model.layout_y,
    )


def _tbox_record(
    draft: KnowledgeStudioDraftModel,
    blocks: Sequence[TBoxDraftBlockModel],
    elements: Sequence[KnowledgeStudioTBoxElementRecord],
) -> KnowledgeStudioTBoxRecord:
    block_ordinal = {block.id: block.ordinal for block in blocks}
    element_by_id = {element.stable_element_id: element for element in elements}
    referenced_from_later: set[str] = set()
    for element in elements:
        owner_ordinal = (
            block_ordinal.get(element.block_id, -1) if element.block_id is not None else -1
        )
        for reference in (
            element.parent_stable_element_id,
            element.source_stable_element_id,
            element.target_stable_element_id,
        ):
            if reference is None:
                continue
            target = element_by_id.get(reference)
            target_ordinal = (
                block_ordinal.get(target.block_id, -1)
                if target is not None and target.block_id is not None
                else -1
            )
            if target is not None and owner_ordinal > target_ordinal:
                referenced_from_later.add(reference)
    elements_by_block: dict[UUID, list[KnowledgeStudioTBoxElementRecord]] = {}
    for element in elements:
        if element.block_id is not None:
            elements_by_block.setdefault(element.block_id, []).append(
                replace(
                    element,
                    locked_by_later_block=element.stable_element_id in referenced_from_later,
                )
            )
    return KnowledgeStudioTBoxRecord(
        draft=_draft_record(draft),
        blocks=tuple(
            KnowledgeStudioTBoxBlockRecord(
                block_id=block.id,
                kind=block.kind,
                title=block.title,
                weight=block.weight,
                ordinal=block.ordinal,
                collapsed=block.collapsed,
                version=block.version,
                source_reference=block.source_reference,
                elements=tuple(elements_by_block.get(block.id, ())),
                created_at=block.created_at,
                updated_at=block.updated_at,
            )
            for block in blocks
        ),
    )


def _proposal_element_record(
    document: dict[str, object], ordinal: int
) -> KnowledgeStudioTBoxElementRecord:
    aliases = document.get("aliases")
    return KnowledgeStudioTBoxElementRecord(
        stable_element_id=str(document["stable_element_id"]),
        kind=str(document["kind"]),
        canonical_name=str(document["canonical_name"]),
        display_name=str(document["display_name"]),
        parent_stable_element_id=_optional_document_string(document, "parent_stable_element_id"),
        hierarchy_relation=_optional_document_string(document, "hierarchy_relation"),
        source_stable_element_id=_optional_document_string(document, "source_stable_element_id"),
        target_stable_element_id=_optional_document_string(document, "target_stable_element_id"),
        data_type=_optional_document_string(document, "data_type"),
        nullable=_optional_document_bool(document, "nullable"),
        ordinal=ordinal,
        version=1,
        definition=_optional_document_string(document, "definition"),
        aliases=tuple(item for item in aliases if isinstance(item, str))
        if isinstance(aliases, list)
        else (),
        unit=_optional_document_string(document, "unit"),
        vector_index_enabled=bool(document.get("vector_index_enabled", False)),
        metadata_reference_id=_optional_document_uuid(document, "metadata_reference_id"),
        metadata_reference_urn=_optional_document_string(
            document,
            "metadata_reference_urn",
        ),
        layout_x=_optional_document_number(document, "layout_x"),
        layout_y=_optional_document_number(document, "layout_y"),
    )


def _proposal_record(model: TBoxProposalModel) -> KnowledgeStudioTBoxProposalRecord:
    raw_elements = model.proposal_document.get("elements")
    elements = (
        tuple(
            _proposal_element_record(item, ordinal)
            for ordinal, item in enumerate(raw_elements)
            if isinstance(item, dict)
        )
        if isinstance(raw_elements, list)
        else ()
    )
    conflicts = tuple(
        KnowledgeStudioTBoxProposalConflictRecord(
            conflict_id=str(item.get("conflict_id", "")),
            kind=str(item.get("kind", "")),
            stable_element_id=str(item.get("stable_element_id", "")),
            field=str(item.get("field", "")),
            original_value=item.get("original_value"),
            proposed_value=item.get("proposed_value"),
        )
        for item in model.conflicts_document
    )
    return KnowledgeStudioTBoxProposalRecord(
        proposal_id=model.id,
        draft_id=model.draft_id,
        target_block_id=model.target_block_id,
        state=model.state,
        mode=model.mode,
        merge_strategy=model.merge_strategy,
        base_draft_version=model.base_draft_version,
        prompt=model.prompt,
        elements=elements,
        conflicts=conflicts,
        model_binding=model.model_binding_document,
        source_reference=model.source_reference_document,
        error_code=model.error_code,
        version=model.version,
        created_at=model.created_at,
        updated_at=model.updated_at,
        applied_at=model.applied_at,
        rejected_at=model.rejected_at,
    )


def _ingestion_job_record(
    model: KnowledgeStudioIngestionJobModel,
) -> KnowledgeStudioIngestionJobRecord:
    targets = model.vector_policy_document.get("targets")
    return KnowledgeStudioIngestionJobRecord(
        job_id=model.id,
        draft_id=model.draft_id,
        requested_by=model.requested_by,
        state=model.state,
        progress_percent=model.progress_percent,
        current_stage=model.current_stage,
        vector_target_count=len(targets) if isinstance(targets, list) else 0,
        result=model.result_document,
        error_code=model.error_code,
        error_message=model.error_message,
        version=model.version,
        created_at=model.created_at,
        updated_at=model.updated_at,
        started_at=model.started_at,
        finished_at=model.finished_at,
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


def _element_document(model: KnowledgeStudioTBoxElementRecord) -> dict[str, object]:
    return {
        "stable_element_id": model.stable_element_id,
        "kind": model.kind,
        "canonical_name": model.canonical_name,
        "display_name": model.display_name,
        "parent_stable_element_id": model.parent_stable_element_id,
        "hierarchy_relation": model.hierarchy_relation,
        "source_stable_element_id": model.source_stable_element_id,
        "target_stable_element_id": model.target_stable_element_id,
        "data_type": model.data_type,
        "nullable": model.nullable,
        "definition": model.definition,
        "aliases": list(model.aliases),
        "unit": model.unit,
        "vector_index_enabled": model.vector_index_enabled,
        "metadata_reference_id": (
            str(model.metadata_reference_id) if model.metadata_reference_id else None
        ),
        "metadata_reference_urn": model.metadata_reference_urn,
        "layout_x": model.layout_x,
        "layout_y": model.layout_y,
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
    elements: tuple[KnowledgeStudioTBoxElementRecord, ...]
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
        "endpoint_aliases": list(record.endpoint_aliases),
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
        raw_endpoint_aliases = result.get("endpoint_aliases", [endpoint_alias])
        if not isinstance(raw_endpoint_aliases, list) or not all(
            isinstance(item, str) for item in raw_endpoint_aliases
        ):
            raise ConflictError("The idempotent Knowledge Studio result is invalid.")
        endpoint_aliases = validate_endpoint_aliases(tuple(raw_endpoint_aliases))
        if endpoint_aliases[0] != endpoint_alias:
            raise ConflictError("The idempotent Knowledge Studio result is invalid.")
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
            endpoint_aliases=endpoint_aliases,
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
        creator_id: UUID | None,
        query: str | None,
        limit: int,
    ) -> tuple[KnowledgeStudioDomainOption, ...]:
        graph_count = (
            select(
                GraphModel.domain_ref_id.label("domain_id"),
                func.count(GraphModel.id).label("asset_count"),
            )
            .where(GraphModel.workspace_id == workspace_id)
            .group_by(GraphModel.domain_ref_id)
            .subquery()
        )
        statement = (
            select(
                CatalogVocabularyEntryModel,
                func.coalesce(graph_count.c.asset_count, 0),
            )
            .outerjoin(
                graph_count,
                graph_count.c.domain_id == CatalogVocabularyEntryModel.id,
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
            scope_filters: list[ColumnElement[bool]] = []
            if allowed_domain_ids:
                scope_filters.append(CatalogVocabularyEntryModel.id.in_(allowed_domain_ids))
            if creator_id is not None:
                scope_filters.append(
                    and_(
                        CatalogVocabularyEntryModel.created_by == creator_id,
                        CatalogVocabularyEntryModel.provider_ref.startswith(
                            "urn:li:domain:datariver-managed-"
                        ),
                    )
                )
            if not scope_filters:
                return ()
            statement = statement.where(or_(*scope_filters))
        if query:
            statement = statement.where(
                CatalogVocabularyEntryModel.display_name.contains(query, autoescape=True)
            )
        rows = (await self._session.execute(statement)).all()
        values = tuple(
            KnowledgeStudioDomainOption(
                domain_id=model.id,
                display_name=model.display_name,
                source_version=model.source_version,
                created_by=model.created_by,
                asset_count=int(asset_count),
                lifecycle=model.lifecycle,
                version=model.version,
                created_at=model.observed_at,
                updated_at=model.updated_at,
                managed=model.provider_ref.startswith("urn:li:domain:datariver-"),
            )
            for model, asset_count in rows
        )
        if values:
            return values
        normalized_query = query.casefold() if query else None
        fallback = (
            KnowledgeStudioDomainOption(
                domain_id=default_knowledge_domain_id(workspace_id, slug),
                display_name=display_name,
                source_version=DEFAULT_KNOWLEDGE_DOMAIN_SOURCE_VERSION,
            )
            for slug, display_name in DEFAULT_KNOWLEDGE_DOMAINS
        )
        return tuple(
            option
            for option in fallback
            if (allowed_domain_ids is None or option.domain_id in allowed_domain_ids)
            and (normalized_query is None or normalized_query in option.display_name.casefold())
        )[:limit]

    async def is_managed_domain_creator(
        self,
        *,
        workspace_id: UUID,
        domain_id: UUID,
        creator_id: UUID,
        source_version: str,
    ) -> bool:
        value = await self._session.scalar(
            select(CatalogVocabularyEntryModel.id).where(
                CatalogVocabularyEntryModel.workspace_id == workspace_id,
                CatalogVocabularyEntryModel.id == domain_id,
                CatalogVocabularyEntryModel.kind == "DOMAIN",
                CatalogVocabularyEntryModel.lifecycle == "ACTIVE",
                CatalogVocabularyEntryModel.created_by == creator_id,
                CatalogVocabularyEntryModel.source_version == source_version,
                CatalogVocabularyEntryModel.provider_ref.startswith(
                    "urn:li:domain:datariver-managed-"
                ),
            )
        )
        return value is not None

    async def list_managed_domains(
        self,
        *,
        workspace_id: UUID,
        limit: int,
    ) -> tuple[KnowledgeStudioManagedDomainRecord, ...]:
        graph_count = (
            select(
                GraphModel.domain_ref_id.label("domain_id"),
                func.count(GraphModel.id).label("asset_count"),
            )
            .where(GraphModel.workspace_id == workspace_id)
            .group_by(GraphModel.domain_ref_id)
            .subquery()
        )
        rows = (
            await self._session.execute(
                select(
                    CatalogVocabularyEntryModel,
                    func.coalesce(graph_count.c.asset_count, 0),
                )
                .outerjoin(
                    graph_count,
                    graph_count.c.domain_id == CatalogVocabularyEntryModel.id,
                )
                .where(
                    CatalogVocabularyEntryModel.workspace_id == workspace_id,
                    CatalogVocabularyEntryModel.kind == "DOMAIN",
                    CatalogVocabularyEntryModel.lifecycle == "ACTIVE",
                    CatalogVocabularyEntryModel.provider_ref.startswith("urn:li:domain:datariver-"),
                )
                .order_by(
                    CatalogVocabularyEntryModel.display_name,
                    CatalogVocabularyEntryModel.id,
                )
                .limit(limit)
            )
        ).all()
        return tuple(
            _managed_domain_record(model, asset_count=int(asset_count))
            for model, asset_count in rows
        )

    async def create_managed_domain(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        display_name: str,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioManagedDomainRecord:
        operation = "knowledge.managed_domain.create"
        idempotency = SqlIdempotencyStore(self._session)
        await idempotency.acquire_key_lock(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
        )
        replay = await idempotency.get_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
        )
        if replay is not None:
            if replay.request_hash != request_hash:
                raise ConflictError("The idempotency key was used with another request.")
            return _managed_domain_record_from_result(
                replay.result,
                workspace_id=workspace_id,
                actor_id=actor_id,
            )
        duplicate = await self._session.scalar(
            select(CatalogVocabularyEntryModel.id).where(
                CatalogVocabularyEntryModel.workspace_id == workspace_id,
                CatalogVocabularyEntryModel.kind == "DOMAIN",
                CatalogVocabularyEntryModel.lifecycle == "ACTIVE",
                func.lower(CatalogVocabularyEntryModel.display_name) == display_name.casefold(),
            )
        )
        if duplicate is not None:
            raise ConflictError("An active Knowledge domain already uses this name.")
        now = utc_now()
        domain_id = uuid7()
        version = 1
        source_version = canonical_json_hash(
            {
                "contract": "DATARIVER_MANAGED_DOMAIN_V1",
                "domain_id": str(domain_id),
                "display_name": display_name,
                "version": version,
            }
        )
        model = CatalogVocabularyEntryModel(
            id=domain_id,
            workspace_id=workspace_id,
            kind="DOMAIN",
            provider_ref=f"urn:li:domain:datariver-managed-{domain_id}",
            display_name=display_name,
            lifecycle="ACTIVE",
            source_version=source_version,
            observed_at=now,
            last_seen_sync_id=None,
            created_by=actor_id,
            version=version,
            updated_at=now,
        )
        self._session.add(model)
        record = _managed_domain_record(model, asset_count=0)
        await idempotency.save_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
            request_hash=request_hash,
            result=_managed_domain_result(record, actor_id=actor_id),
        )
        try:
            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()
            raise ConflictError("The managed Knowledge domain could not be created.") from error
        return record

    async def update_managed_domain(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        domain_id: UUID,
        display_name: str,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioManagedDomainRecord:
        return await self._mutate_managed_domain(
            workspace_id=workspace_id,
            actor_id=actor_id,
            domain_id=domain_id,
            display_name=display_name,
            lifecycle="ACTIVE",
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            operation=f"knowledge.managed_domain.update:{domain_id}",
        )

    async def archive_managed_domain(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        domain_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioManagedDomainRecord:
        return await self._mutate_managed_domain(
            workspace_id=workspace_id,
            actor_id=actor_id,
            domain_id=domain_id,
            display_name=None,
            lifecycle="INACTIVE",
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            operation=f"knowledge.managed_domain.archive:{domain_id}",
        )

    async def _mutate_managed_domain(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        domain_id: UUID,
        display_name: str | None,
        lifecycle: str,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
        operation: str,
    ) -> KnowledgeStudioManagedDomainRecord:
        idempotency = SqlIdempotencyStore(self._session)
        await idempotency.acquire_key_lock(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
        )
        replay = await idempotency.get_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
        )
        if replay is not None:
            if replay.request_hash != request_hash:
                raise ConflictError("The idempotency key was used with another request.")
            return _managed_domain_record_from_result(
                replay.result,
                workspace_id=workspace_id,
                actor_id=actor_id,
            )
        model = (
            await self._session.scalars(
                select(CatalogVocabularyEntryModel)
                .where(
                    CatalogVocabularyEntryModel.workspace_id == workspace_id,
                    CatalogVocabularyEntryModel.id == domain_id,
                    CatalogVocabularyEntryModel.kind == "DOMAIN",
                    CatalogVocabularyEntryModel.provider_ref.startswith("urn:li:domain:datariver-"),
                )
                .with_for_update()
            )
        ).one_or_none()
        if model is None:
            raise NotFoundError("The managed Knowledge domain does not exist.")
        require_studio_version(model.version, expected_version)
        if model.lifecycle != "ACTIVE":
            raise ConflictError("Only an active managed Knowledge domain can be changed.")
        if display_name is not None:
            duplicate = await self._session.scalar(
                select(CatalogVocabularyEntryModel.id).where(
                    CatalogVocabularyEntryModel.workspace_id == workspace_id,
                    CatalogVocabularyEntryModel.kind == "DOMAIN",
                    CatalogVocabularyEntryModel.lifecycle == "ACTIVE",
                    CatalogVocabularyEntryModel.id != domain_id,
                    func.lower(CatalogVocabularyEntryModel.display_name) == display_name.casefold(),
                )
            )
            if duplicate is not None:
                raise ConflictError("An active Knowledge domain already uses this name.")
            model.display_name = display_name
        model.lifecycle = lifecycle
        model.version += 1
        model.updated_at = utc_now()
        model.source_version = canonical_json_hash(
            {
                "contract": "DATARIVER_MANAGED_DOMAIN_V1",
                "domain_id": str(model.id),
                "display_name": model.display_name,
                "lifecycle": model.lifecycle,
                "version": model.version,
            }
        )
        asset_count = int(
            await self._session.scalar(
                select(func.count(GraphModel.id)).where(
                    GraphModel.workspace_id == workspace_id,
                    GraphModel.domain_ref_id == domain_id,
                )
            )
            or 0
        )
        record = _managed_domain_record(model, asset_count=asset_count)
        await idempotency.save_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
            request_hash=request_hash,
            result=_managed_domain_result(record, actor_id=actor_id),
        )
        await self._session.commit()
        return record

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

    async def get_owned_live_draft_by_endpoint_alias(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        endpoint_alias: str,
    ) -> KnowledgeStudioDraftRecord | None:
        model = (
            await self._session.scalars(
                select(KnowledgeStudioDraftModel).where(
                    KnowledgeStudioDraftModel.workspace_id == workspace_id,
                    KnowledgeStudioDraftModel.author_id == author_id,
                    KnowledgeStudioDraftModel.endpoint_alias == endpoint_alias,
                    KnowledgeStudioDraftModel.state == "DRAFT",
                )
            )
        ).one_or_none()
        return _draft_record(model) if model is not None else None

    async def get_tbox(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        draft_id: UUID,
    ) -> KnowledgeStudioTBoxRecord | None:
        draft = (
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
        if draft is None:
            return None
        blocks, elements = await self._load_tbox_models(
            workspace_id=workspace_id,
            draft_id=draft_id,
        )
        return _tbox_record(draft, blocks, elements)

    async def create_tbox_block(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
        kind: str,
        title: str,
        weight: int,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioTBoxRecord:
        operation = f"knowledge.studio_tbox.block.create:{draft_id}"
        replay = await self._tbox_mutation_replay(
            workspace_id=workspace_id,
            author_id=author_id,
            draft_id=draft_id,
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
        if draft.current_step != StudioStep.TBOX.value:
            raise ConflictError("T-Box blocks can be edited only in Graph Builder.")
        block_count = int(
            await self._session.scalar(
                select(func.count(TBoxDraftBlockModel.id)).where(
                    TBoxDraftBlockModel.workspace_id == workspace_id,
                    TBoxDraftBlockModel.draft_id == draft_id,
                )
            )
            or 0
        )
        if block_count >= 20:
            raise ConflictError("A T-Box Draft can contain at most 20 blocks.")
        now = utc_now()
        self._session.add(
            TBoxDraftBlockModel(
                id=uuid7(),
                workspace_id=workspace_id,
                draft_id=draft_id,
                kind=kind,
                title=title,
                weight=weight,
                ordinal=block_count,
                collapsed=False,
                source_reference=None,
                created_at=now,
                updated_at=now,
                version=1,
            )
        )
        draft.updated_at = now
        draft.last_autosaved_at = now
        draft.version += 1
        return await self._save_tbox_mutation(
            draft=draft,
            workspace_id=workspace_id,
            author_id=author_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def update_tbox_block(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
        block_id: UUID,
        title: str,
        weight: int,
        collapsed: bool,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioTBoxRecord:
        operation = f"knowledge.studio_tbox.block.update:{draft_id}:{block_id}"
        replay = await self._tbox_mutation_replay(
            workspace_id=workspace_id,
            author_id=author_id,
            draft_id=draft_id,
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
        block = (
            await self._session.scalars(
                select(TBoxDraftBlockModel)
                .where(
                    TBoxDraftBlockModel.workspace_id == workspace_id,
                    TBoxDraftBlockModel.draft_id == draft_id,
                    TBoxDraftBlockModel.id == block_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        if block is None:
            raise NotFoundError("The T-Box block does not exist.")
        now = utc_now()
        block.title = title
        block.weight = weight
        block.collapsed = collapsed
        block.updated_at = now
        block.version += 1
        draft.updated_at = now
        draft.last_autosaved_at = now
        draft.version += 1
        return await self._save_tbox_mutation(
            draft=draft,
            workspace_id=workspace_id,
            author_id=author_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def delete_tbox_block(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
        block_id: UUID,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioTBoxRecord:
        operation = f"knowledge.studio_tbox.block.delete:{draft_id}:{block_id}"
        replay = await self._tbox_mutation_replay(
            workspace_id=workspace_id,
            author_id=author_id,
            draft_id=draft_id,
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
        if draft.current_step != StudioStep.TBOX.value:
            raise ConflictError("T-Box blocks can be deleted only in Graph Builder.")
        blocks = tuple(
            (
                await self._session.scalars(
                    select(TBoxDraftBlockModel)
                    .where(
                        TBoxDraftBlockModel.workspace_id == workspace_id,
                        TBoxDraftBlockModel.draft_id == draft_id,
                    )
                    .order_by(TBoxDraftBlockModel.ordinal, TBoxDraftBlockModel.id)
                    .with_for_update()
                )
            ).all()
        )
        if not blocks or blocks[-1].id != block_id:
            raise ConflictError("Only the newest T-Box block can be deleted.")
        proposal_reference = await self._session.scalar(
            select(TBoxProposalModel.id)
            .where(
                TBoxProposalModel.workspace_id == workspace_id,
                TBoxProposalModel.draft_id == draft_id,
                TBoxProposalModel.target_block_id == block_id,
            )
            .limit(1)
        )
        if proposal_reference is not None:
            raise ConflictError(
                "The newest block has retained proposal evidence and cannot be deleted."
            )
        element_ids = tuple(
            (
                await self._session.scalars(
                    select(TBoxDraftElementModel.stable_element_id)
                    .where(
                        TBoxDraftElementModel.workspace_id == workspace_id,
                        TBoxDraftElementModel.draft_id == draft_id,
                        TBoxDraftElementModel.block_id == block_id,
                    )
                    .with_for_update()
                )
            ).all()
        )
        if element_ids:
            for model, field in (
                (TBoxRelationshipModel, TBoxRelationshipModel.stable_relationship_id),
                (TBoxPropertyModel, TBoxPropertyModel.stable_property_id),
                (TBoxClassModel, TBoxClassModel.stable_class_id),
            ):
                await self._session.execute(
                    delete(model).where(
                        model.workspace_id == workspace_id,
                        model.draft_id == draft_id,
                        field.in_(element_ids),
                    )
                )
            await self._session.execute(
                delete(TBoxDraftElementModel).where(
                    TBoxDraftElementModel.workspace_id == workspace_id,
                    TBoxDraftElementModel.draft_id == draft_id,
                    TBoxDraftElementModel.block_id == block_id,
                )
            )
        await self._session.delete(blocks[-1])
        now = utc_now()
        draft.updated_at = now
        draft.last_autosaved_at = now
        draft.version += 1
        return await self._save_tbox_mutation(
            draft=draft,
            workspace_id=workspace_id,
            author_id=author_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def save_tbox_block_elements(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
        block_id: UUID,
        elements_by_block: tuple[tuple[UUID, tuple[TBoxElementInput, ...]], ...],
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioTBoxRecord:
        operation = f"knowledge.studio_tbox.operations:{draft_id}:{block_id}"
        replay = await self._tbox_mutation_replay(
            workspace_id=workspace_id,
            author_id=author_id,
            draft_id=draft_id,
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
        if draft.current_step != StudioStep.TBOX.value:
            raise ConflictError("Typed T-Box operations require the Graph Builder step.")
        blocks = tuple(
            (
                await self._session.scalars(
                    select(TBoxDraftBlockModel)
                    .where(
                        TBoxDraftBlockModel.workspace_id == workspace_id,
                        TBoxDraftBlockModel.draft_id == draft_id,
                    )
                    .with_for_update()
                )
            ).all()
        )
        block_ids = {item.id for item in blocks}
        supplied_block_ids = {item[0] for item in elements_by_block}
        if block_id not in block_ids or supplied_block_ids != block_ids:
            raise ConflictError("The T-Box block set changed before the operation was saved.")
        now = utc_now()
        await self._replace_tbox_elements(
            workspace_id=workspace_id,
            draft_id=draft_id,
            elements_by_block=elements_by_block,
            now=now,
        )
        for block in blocks:
            if block.id == block_id:
                block.updated_at = now
                block.version += 1
        draft.updated_at = now
        draft.last_autosaved_at = now
        draft.version += 1
        return await self._save_tbox_mutation(
            draft=draft,
            workspace_id=workspace_id,
            author_id=author_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def save_tbox_proposal(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
        base_draft_version: int,
        target_block_id: UUID | None,
        mode: str,
        prompt: str,
        elements: tuple[TBoxElementInput, ...],
        conflicts: tuple[dict[str, object], ...],
        model_binding: dict[str, object],
        source_reference: dict[str, object] | None,
    ) -> KnowledgeStudioTBoxProposalRecord:
        draft = await self._locked_draft(
            workspace_id=workspace_id,
            author_id=author_id,
            draft_id=draft_id,
        )
        self._require_expected_version(draft, base_draft_version)
        self._require_mutable(draft)
        if draft.current_step != StudioStep.TBOX.value:
            raise ConflictError("LLM schema proposals require the Graph Builder step.")
        if target_block_id is not None:
            block_exists = await self._session.scalar(
                select(TBoxDraftBlockModel.id).where(
                    TBoxDraftBlockModel.workspace_id == workspace_id,
                    TBoxDraftBlockModel.draft_id == draft_id,
                    TBoxDraftBlockModel.id == target_block_id,
                )
            )
            if block_exists is None:
                raise NotFoundError("The proposal target block does not exist.")
        now = utc_now()
        model = TBoxProposalModel(
            id=uuid7(),
            workspace_id=workspace_id,
            draft_id=draft_id,
            target_block_id=target_block_id,
            created_by=author_id,
            state="READY",
            mode=mode,
            merge_strategy="KEEP_ORIGINAL",
            base_draft_version=draft.version,
            prompt=prompt,
            proposal_document={
                "contract_version": "KNOWLEDGE_STUDIO_TBOX_PROPOSAL_V1",
                "elements": [_tbox_input_document(item) for item in elements],
            },
            conflicts_document=list(conflicts),
            model_binding_document=model_binding,
            source_reference_document=source_reference,
            error_code=None,
            applied_at=None,
            rejected_at=None,
            created_at=now,
            updated_at=now,
            version=1,
        )
        self._session.add(model)
        try:
            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()
            raise ConflictError("The typed T-Box proposal could not be persisted.") from error
        return _proposal_record(model)

    async def get_tbox_proposal(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        draft_id: UUID,
        proposal_id: UUID,
    ) -> KnowledgeStudioTBoxProposalRecord | None:
        model = (
            await self._session.scalars(
                select(TBoxProposalModel)
                .join(
                    KnowledgeStudioDraftModel,
                    (KnowledgeStudioDraftModel.workspace_id == TBoxProposalModel.workspace_id)
                    & (KnowledgeStudioDraftModel.id == TBoxProposalModel.draft_id),
                )
                .where(
                    TBoxProposalModel.workspace_id == workspace_id,
                    TBoxProposalModel.draft_id == draft_id,
                    TBoxProposalModel.id == proposal_id,
                    or_(
                        KnowledgeStudioDraftModel.author_id == actor_id,
                        KnowledgeStudioDraftModel.state.in_(("REVIEW", "PUBLISHED")),
                    ),
                )
            )
        ).one_or_none()
        return _proposal_record(model) if model is not None else None

    async def apply_tbox_proposal(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
        proposal_id: UUID,
        target_block_id: UUID | None,
        elements_by_block: tuple[tuple[UUID, tuple[TBoxElementInput, ...]], ...],
        appended_elements: tuple[TBoxElementInput, ...],
        conflicts: tuple[dict[str, object], ...],
        merge_strategy: str,
        expected_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioTBoxRecord:
        operation = f"knowledge.studio_tbox.proposal.apply:{draft_id}:{proposal_id}"
        replay = await self._tbox_mutation_replay(
            workspace_id=workspace_id,
            author_id=author_id,
            draft_id=draft_id,
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
        proposal = (
            await self._session.scalars(
                select(TBoxProposalModel)
                .where(
                    TBoxProposalModel.workspace_id == workspace_id,
                    TBoxProposalModel.draft_id == draft_id,
                    TBoxProposalModel.id == proposal_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        if proposal is None:
            raise NotFoundError("The T-Box proposal does not exist.")
        if proposal.state != "READY":
            raise ConflictError("Only a READY T-Box proposal can be applied.")
        if proposal.base_draft_version != expected_version:
            raise ConflictError(
                "The T-Box Draft changed after the proposal was generated. Generate it again."
            )
        blocks = list(
            (
                await self._session.scalars(
                    select(TBoxDraftBlockModel)
                    .where(
                        TBoxDraftBlockModel.workspace_id == workspace_id,
                        TBoxDraftBlockModel.draft_id == draft_id,
                    )
                    .order_by(TBoxDraftBlockModel.ordinal, TBoxDraftBlockModel.id)
                    .with_for_update()
                )
            ).all()
        )
        known_block_ids = {block.id for block in blocks}
        if {item[0] for item in elements_by_block} != known_block_ids:
            raise ConflictError("The T-Box block set changed before proposal acceptance.")
        now = utc_now()
        if proposal.mode == "APPEND_LAYER":
            if target_block_id is not None or not appended_elements:
                raise ConflictError("APPEND_LAYER requires a new non-empty proposal block.")
            new_block = TBoxDraftBlockModel(
                id=uuid7(),
                workspace_id=workspace_id,
                draft_id=draft_id,
                kind="LLM_ASSISTANT",
                title="LLM 제안",
                weight=DEFAULT_TBOX_BLOCK_WEIGHT,
                ordinal=len(blocks),
                collapsed=False,
                source_reference={
                    "kind": "TBOX_PROPOSAL",
                    "proposal_id": str(proposal.id),
                },
                created_at=now,
                updated_at=now,
                version=1,
            )
            self._session.add(new_block)
            blocks.append(new_block)
            elements_by_block = (
                *elements_by_block,
                (new_block.id, appended_elements),
            )
        elif target_block_id is None or target_block_id not in known_block_ids:
            raise ConflictError("MERGE_INTO_CURRENT requires an existing target block.")
        await self._replace_tbox_elements(
            workspace_id=workspace_id,
            draft_id=draft_id,
            elements_by_block=elements_by_block,
            now=now,
        )
        proposal.state = "APPLIED"
        proposal.merge_strategy = merge_strategy
        proposal.conflicts_document = list(conflicts)
        proposal.applied_at = now
        proposal.updated_at = now
        proposal.version += 1
        draft.updated_at = now
        draft.last_autosaved_at = now
        draft.version += 1
        return await self._save_tbox_mutation(
            draft=draft,
            workspace_id=workspace_id,
            author_id=author_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    async def create_ingestion_job(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
        expected_version: int,
        embedding_binding: dict[str, object] | None,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioIngestionJobRecord:
        operation = f"knowledge.studio_ingestion.create:{draft_id}"
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
            raw_job_id = existing.result.get("job_id")
            if not isinstance(raw_job_id, str):
                raise ConflictError("The idempotent ingestion result is invalid.")
            replay = await self.get_ingestion_job(
                workspace_id=workspace_id,
                actor_id=author_id,
                draft_id=draft_id,
                job_id=UUID(raw_job_id),
            )
            if replay is None:
                raise ConflictError("The idempotent ingestion result is unavailable.")
            return replay
        draft = await self._locked_draft(
            workspace_id=workspace_id,
            author_id=author_id,
            draft_id=draft_id,
        )
        self._require_expected_version(draft, expected_version)
        self._require_mutable(draft)
        if draft.current_step != StudioStep.ABOX.value:
            raise ConflictError("A-Box ingestion requires the Data Enricher step.")
        bindings = tuple(
            (
                await self._session.scalars(
                    select(ABoxBindingDraftModel)
                    .where(
                        ABoxBindingDraftModel.workspace_id == workspace_id,
                        ABoxBindingDraftModel.draft_id == draft_id,
                    )
                    .order_by(ABoxBindingDraftModel.id)
                )
            ).all()
        )
        if not bindings:
            raise ConflictError("A-Box ingestion requires at least one persisted binding.")
        contract = await self._load_contract(
            workspace_id=workspace_id,
            draft=draft,
            lock=True,
        )
        preflight = (
            await self._session.scalars(
                select(KnowledgeStudioPreflightCheckModel)
                .where(
                    KnowledgeStudioPreflightCheckModel.workspace_id == workspace_id,
                    KnowledgeStudioPreflightCheckModel.draft_id == draft_id,
                    KnowledgeStudioPreflightCheckModel.draft_version == draft.version,
                    KnowledgeStudioPreflightCheckModel.contract_hash == contract.contract_hash,
                    KnowledgeStudioPreflightCheckModel.status == "PASS",
                    KnowledgeStudioPreflightCheckModel.valid.is_(True),
                    KnowledgeStudioPreflightCheckModel.checked_by == author_id,
                )
                .order_by(
                    KnowledgeStudioPreflightCheckModel.checked_at.desc(),
                    KnowledgeStudioPreflightCheckModel.id.desc(),
                )
                .limit(1)
                .with_for_update(read=True)
            )
        ).one_or_none()
        if preflight is None:
            raise ConflictError(
                "A-Box ingestion requires an exact current-Draft PASS pre-flight receipt."
            )
        vector_targets = tuple(
            (
                await self._session.execute(
                    select(TBoxDraftElementModel, TBoxPropertyModel)
                    .join(
                        TBoxPropertyModel,
                        (TBoxPropertyModel.workspace_id == TBoxDraftElementModel.workspace_id)
                        & (TBoxPropertyModel.draft_id == TBoxDraftElementModel.draft_id)
                        & (
                            TBoxPropertyModel.stable_property_id
                            == TBoxDraftElementModel.stable_element_id
                        ),
                    )
                    .where(
                        TBoxDraftElementModel.workspace_id == workspace_id,
                        TBoxDraftElementModel.draft_id == draft_id,
                        TBoxDraftElementModel.kind == "PROPERTY",
                        TBoxPropertyModel.vector_index_enabled.is_(True),
                    )
                    .order_by(TBoxDraftElementModel.stable_element_id)
                )
            ).all()
        )
        vector_rules: tuple[ABoxMappingRuleDraftModel, ...] = ()
        if vector_targets:
            vector_rules = tuple(
                (
                    await self._session.scalars(
                        select(ABoxMappingRuleDraftModel)
                        .where(
                            ABoxMappingRuleDraftModel.workspace_id == workspace_id,
                            ABoxMappingRuleDraftModel.draft_id == draft_id,
                            ABoxMappingRuleDraftModel.method == ABoxMappingMethod.PROPERTY.value,
                            ABoxMappingRuleDraftModel.target_stable_element_id.in_(
                                tuple(item[0].stable_element_id for item in vector_targets)
                            ),
                        )
                        .order_by(
                            ABoxMappingRuleDraftModel.target_stable_element_id,
                            ABoxMappingRuleDraftModel.id,
                        )
                    )
                ).all()
            )
        vector_rule_by_target = {item.target_stable_element_id: item for item in vector_rules}
        unmapped_vector_targets = [
            item[0].stable_element_id
            for item in vector_targets
            if item[0].stable_element_id not in vector_rule_by_target
        ]
        if unmapped_vector_targets:
            raise ConflictError("Every Vector Index Property requires an exact persisted mapping.")
        if vector_targets and embedding_binding is None:
            raise ConflictError("A Vector Index target requires the governed embedding runtime.")
        now = utc_now()
        job = KnowledgeStudioIngestionJobModel(
            id=uuid7(),
            workspace_id=workspace_id,
            draft_id=draft_id,
            requested_by=author_id,
            state="PENDING",
            progress_percent=0,
            current_stage="QUEUED",
            request_document={
                "contract_version": "KNOWLEDGE_STUDIO_INGESTION_V1",
                "draft_version": draft.version,
                "contract_hash": contract.contract_hash,
                "preflight_receipt_id": str(preflight.id),
                "binding_ids": [str(binding.id) for binding in bindings],
            },
            vector_policy_document={
                "contract_version": "KNOWLEDGE_STUDIO_VECTOR_POLICY_V1",
                "embedding_binding": embedding_binding,
                "targets": [
                    {
                        "stable_element_id": item[0].stable_element_id,
                        "parent_stable_element_id": item[1].owner_stable_class_id,
                        "data_type": item[1].data_type,
                        "binding_id": str(
                            vector_rule_by_target[item[0].stable_element_id].binding_id
                        ),
                        "source_field_path": vector_rule_by_target[
                            item[0].stable_element_id
                        ].source_field_path,
                    }
                    for item in vector_targets
                ],
            },
            result_document=None,
            error_code=None,
            error_message=None,
            started_at=None,
            finished_at=None,
            lease_epoch=0,
            lease_token_hash=None,
            lease_owner_fingerprint=None,
            lease_expires_at=None,
            created_at=now,
            updated_at=now,
            version=1,
        )
        self._session.add(job)
        await SqlOutboxWriter(self._session).add_events(
            [
                DomainEvent.create(
                    event_type="knowledge.studio_ingestion.queued.v1",
                    aggregate_type="knowledge_studio_ingestion",
                    aggregate_id=job.id,
                    workspace_id=workspace_id,
                    payload={
                        "job_id": str(job.id),
                        "draft_id": str(draft_id),
                        "draft_version": draft.version,
                    },
                )
            ]
        )
        await idempotency.save_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
            request_hash=request_hash,
            result={"job_id": str(job.id)},
        )
        try:
            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()
            raise ConflictError("The A-Box ingestion job could not be queued.") from error
        return _ingestion_job_record(job)

    async def get_ingestion_job(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        draft_id: UUID,
        job_id: UUID,
    ) -> KnowledgeStudioIngestionJobRecord | None:
        model = (
            await self._session.scalars(
                select(KnowledgeStudioIngestionJobModel)
                .join(
                    KnowledgeStudioDraftModel,
                    (
                        KnowledgeStudioDraftModel.workspace_id
                        == KnowledgeStudioIngestionJobModel.workspace_id
                    )
                    & (KnowledgeStudioDraftModel.id == KnowledgeStudioIngestionJobModel.draft_id),
                )
                .where(
                    KnowledgeStudioIngestionJobModel.workspace_id == workspace_id,
                    KnowledgeStudioIngestionJobModel.draft_id == draft_id,
                    KnowledgeStudioIngestionJobModel.id == job_id,
                    or_(
                        KnowledgeStudioDraftModel.author_id == actor_id,
                        KnowledgeStudioDraftModel.state.in_(("REVIEW", "PUBLISHED")),
                    ),
                )
            )
        ).one_or_none()
        return _ingestion_job_record(model) if model is not None else None

    async def list_ingestion_jobs(
        self,
        *,
        workspace_id: UUID,
        actor_id: UUID,
        draft_id: UUID,
        limit: int,
    ) -> tuple[KnowledgeStudioIngestionJobRecord, ...]:
        models = tuple(
            (
                await self._session.scalars(
                    select(KnowledgeStudioIngestionJobModel)
                    .join(
                        KnowledgeStudioDraftModel,
                        (
                            KnowledgeStudioDraftModel.workspace_id
                            == KnowledgeStudioIngestionJobModel.workspace_id
                        )
                        & (
                            KnowledgeStudioDraftModel.id
                            == KnowledgeStudioIngestionJobModel.draft_id
                        ),
                    )
                    .where(
                        KnowledgeStudioIngestionJobModel.workspace_id == workspace_id,
                        KnowledgeStudioIngestionJobModel.draft_id == draft_id,
                        or_(
                            KnowledgeStudioDraftModel.author_id == actor_id,
                            KnowledgeStudioDraftModel.state.in_(("REVIEW", "PUBLISHED")),
                        ),
                    )
                    .order_by(
                        KnowledgeStudioIngestionJobModel.created_at.desc(),
                        KnowledgeStudioIngestionJobModel.id.desc(),
                    )
                    .limit(limit)
                )
            ).all()
        )
        return tuple(_ingestion_job_record(model) for model in models)

    async def get_edit_graph(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        clearance: int,
    ) -> KnowledgeGraphRecord | None:
        model = (
            await self._session.scalars(
                select(GraphModel).where(
                    GraphModel.workspace_id == workspace_id,
                    GraphModel.id == graph_id,
                    GraphModel.classification <= clearance,
                    GraphModel.status != "ARCHIVED",
                )
            )
        ).one_or_none()
        if model is None:
            return None
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
            created_by=model.created_by,
            updated_by=model.updated_by,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    async def create_edit_draft(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        graph_id: UUID,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioDraftRecord:
        operation = f"knowledge.studio_draft.edit:{graph_id}"
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
        existing = (
            await self._session.scalars(
                select(KnowledgeStudioDraftModel)
                .where(
                    KnowledgeStudioDraftModel.workspace_id == workspace_id,
                    KnowledgeStudioDraftModel.author_id == author_id,
                    KnowledgeStudioDraftModel.kind == "EDIT",
                    KnowledgeStudioDraftModel.base_graph_id == graph_id,
                    KnowledgeStudioDraftModel.state.in_(("DRAFT", "REVIEW")),
                )
                .order_by(
                    KnowledgeStudioDraftModel.updated_at.desc(),
                    KnowledgeStudioDraftModel.id.desc(),
                )
                .limit(1)
            )
        ).one_or_none()
        if existing is not None:
            record = _draft_record(existing)
            await idempotency.save_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                result=studio_draft_result(record),
            )
            await self._session.commit()
            return record
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
        if (
            graph is None
            or graph.domain_ref_id is None
            or graph.domain_source_version is None
            or graph.active_studio_release_id is None
        ):
            raise ConflictError(
                "The Knowledge asset has no complete active Studio release to edit."
            )
        active_release = (
            await self._session.scalars(
                select(KnowledgeStudioReleaseModel).where(
                    KnowledgeStudioReleaseModel.workspace_id == workspace_id,
                    KnowledgeStudioReleaseModel.graph_id == graph_id,
                    KnowledgeStudioReleaseModel.id == graph.active_studio_release_id,
                    KnowledgeStudioReleaseModel.state == "ACTIVE",
                )
            )
        ).one_or_none()
        if active_release is None:
            raise ConflictError("The Knowledge asset active Studio release is unavailable.")
        now = utc_now()
        draft = KnowledgeStudioDraftModel(
            id=uuid7(),
            workspace_id=workspace_id,
            author_id=author_id,
            kind="EDIT",
            state="DRAFT",
            current_step="BASIC",
            name=graph.name,
            endpoint_alias=graph.slug,
            endpoint_aliases=[graph.slug],
            domain_ref_id=graph.domain_ref_id,
            domain_ref_kind="DOMAIN",
            domain_source_version=graph.domain_source_version,
            classification=graph.classification,
            base_graph_id=graph.id,
            base_ontology_version_id=active_release.ontology_version_id,
            base_release_id=graph.active_release_id,
            last_autosaved_at=now,
            created_at=now,
            updated_at=now,
            version=1,
        )
        self._session.add(draft)
        direct_block = TBoxDraftBlockModel(
            id=uuid7(),
            workspace_id=workspace_id,
            draft_id=draft.id,
            kind="DIRECT",
            title="직접 정의",
            weight=DEFAULT_TBOX_BLOCK_WEIGHT,
            ordinal=0,
            collapsed=False,
            source_reference=None,
            created_at=now,
            updated_at=now,
            version=1,
        )
        self._session.add(direct_block)
        elements = (
            await self._session.scalars(
                select(OntologyElementModel)
                .where(
                    OntologyElementModel.workspace_id == workspace_id,
                    OntologyElementModel.graph_id == graph_id,
                    OntologyElementModel.ontology_version_id == active_release.ontology_version_id,
                )
                .order_by(
                    OntologyElementModel.ordinal,
                    OntologyElementModel.stable_element_id,
                )
            )
        ).all()
        imported_elements: list[TBoxElementInput] = []
        for element in elements:
            document = element.element_document
            imported_elements.append(
                TBoxElementInput(
                    stable_element_id=element.stable_element_id,
                    kind=TBoxElementKind(element.kind),
                    canonical_name=element.canonical_name,
                    display_name=element.display_name,
                    parent_stable_element_id=_optional_document_string(
                        document,
                        "parent_stable_element_id",
                    ),
                    hierarchy_relation=_optional_document_string(
                        document,
                        "hierarchy_relation",
                    ),
                    source_stable_element_id=_optional_document_string(
                        document,
                        "source_stable_element_id",
                    ),
                    target_stable_element_id=_optional_document_string(
                        document,
                        "target_stable_element_id",
                    ),
                    data_type=_optional_document_string(document, "data_type"),
                    nullable=_optional_document_bool(document, "nullable"),
                    definition=_optional_document_string(document, "definition"),
                    aliases=tuple(_document_string_list(document, "aliases")),
                    unit=_optional_document_string(document, "unit"),
                    vector_index_enabled=bool(document.get("vector_index_enabled", False)),
                    metadata_reference_id=_optional_document_uuid(
                        document,
                        "metadata_reference_id",
                    ),
                    metadata_reference_urn=_optional_document_string(
                        document,
                        "metadata_reference_urn",
                    ),
                    layout_x=_optional_document_number(document, "layout_x"),
                    layout_y=_optional_document_number(document, "layout_y"),
                )
            )
        await self._replace_tbox_elements(
            workspace_id=workspace_id,
            draft_id=draft.id,
            elements_by_block=((direct_block.id, tuple(imported_elements)),),
            now=now,
        )
        await self._session.flush()
        binding_versions = tuple(
            (
                await self._session.scalars(
                    select(ABoxBindingVersionModel)
                    .where(
                        ABoxBindingVersionModel.workspace_id == workspace_id,
                        ABoxBindingVersionModel.studio_release_id == active_release.id,
                    )
                    .order_by(
                        ABoxBindingVersionModel.ordinal,
                        ABoxBindingVersionModel.id,
                    )
                )
            ).all()
        )
        rule_versions: tuple[ABoxMappingRuleVersionModel, ...] = ()
        if binding_versions:
            rule_versions = tuple(
                (
                    await self._session.scalars(
                        select(ABoxMappingRuleVersionModel)
                        .where(
                            ABoxMappingRuleVersionModel.workspace_id == workspace_id,
                            ABoxMappingRuleVersionModel.binding_version_id.in_(
                                tuple(binding.id for binding in binding_versions)
                            ),
                        )
                        .order_by(
                            ABoxMappingRuleVersionModel.binding_version_id,
                            ABoxMappingRuleVersionModel.ordinal,
                        )
                    )
                ).all()
            )
        rules_by_binding: dict[UUID, list[ABoxMappingRuleVersionModel]] = {}
        for rule in rule_versions:
            rules_by_binding.setdefault(rule.binding_version_id, []).append(rule)
        for binding_version in binding_versions:
            binding_id = uuid7()
            self._session.add(
                ABoxBindingDraftModel(
                    id=binding_id,
                    workspace_id=workspace_id,
                    draft_id=draft.id,
                    target_stable_element_id=binding_version.target_stable_element_id,
                    source_reference_id=binding_version.source_reference_id,
                    readiness="VALIDATED",
                    tbox_version=1,
                    created_by=author_id,
                    updated_by=author_id,
                    created_at=now,
                    updated_at=now,
                    version=1,
                )
            )
            self._session.add_all(
                [
                    ABoxMappingRuleDraftModel(
                        id=uuid7(),
                        workspace_id=workspace_id,
                        draft_id=draft.id,
                        binding_id=binding_id,
                        ordinal=rule.ordinal,
                        method=rule.method,
                        source_field_path=rule.source_field_path,
                        target_stable_element_id=rule.target_stable_element_id,
                        transform_id=rule.transform_id,
                        transform_version=rule.transform_version,
                        source_unit=rule.source_unit,
                        canonical_unit=rule.canonical_unit,
                        created_at=now,
                        updated_at=now,
                    )
                    for rule in rules_by_binding.get(binding_version.id, ())
                ]
            )
        record = _draft_record(draft)
        await idempotency.save_result(
            workspace_id=workspace_id,
            key=idempotency_key,
            operation=operation,
            request_hash=request_hash,
            result=studio_draft_result(record),
        )
        try:
            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()
            raise ConflictError(
                "A live Knowledge Studio edit Draft already exists for this endpoint."
            ) from error
        return record

    async def create_draft(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        name: str,
        endpoint_alias: str,
        endpoint_aliases: tuple[str, ...],
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
        for alias in endpoint_aliases:
            await self._require_alias_available(
                workspace_id=workspace_id,
                endpoint_alias=alias,
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
            endpoint_aliases=list(endpoint_aliases),
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
        endpoint_aliases: tuple[str, ...],
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
        for alias in endpoint_aliases:
            await self._require_alias_available(
                workspace_id=workspace_id,
                endpoint_alias=alias,
                exclude_draft_id=draft_id,
            )
        now = utc_now()
        model.name = name
        model.endpoint_alias = endpoint_alias
        model.endpoint_aliases = list(endpoint_aliases)
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
        await self._ensure_direct_block(
            workspace_id=workspace_id,
            draft_id=draft_id,
            now=model.updated_at,
        )
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
            await self._load_tbox_element_records(
                workspace_id=workspace_id,
                draft_id=draft_id,
                limit=501,
            )
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
            tbox_elements=tuple(element_models),
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
            for alias in draft.endpoint_aliases:
                await self._require_alias_available(
                    workspace_id=workspace_id,
                    endpoint_alias=alias,
                    exclude_draft_id=draft.id,
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
        if existing_graph is None or existing_graph.status == "ARCHIVED":
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
            bindings_statement = bindings_statement.with_for_update(read=True)
        elements = await self._load_tbox_element_records(
            workspace_id=workspace_id,
            draft_id=draft.id,
            lock=lock,
            limit=501,
        )
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
                "endpoint_aliases": list(draft.endpoint_aliases),
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

    async def _ensure_direct_block(
        self,
        *,
        workspace_id: UUID,
        draft_id: UUID,
        now: datetime,
    ) -> TBoxDraftBlockModel:
        existing = (
            await self._session.scalars(
                select(TBoxDraftBlockModel)
                .where(
                    TBoxDraftBlockModel.workspace_id == workspace_id,
                    TBoxDraftBlockModel.draft_id == draft_id,
                )
                .order_by(TBoxDraftBlockModel.ordinal, TBoxDraftBlockModel.id)
                .limit(1)
            )
        ).one_or_none()
        if existing is not None:
            return existing
        block = TBoxDraftBlockModel(
            id=uuid7(),
            workspace_id=workspace_id,
            draft_id=draft_id,
            kind="DIRECT",
            title="직접 정의",
            weight=DEFAULT_TBOX_BLOCK_WEIGHT,
            ordinal=0,
            collapsed=False,
            source_reference=None,
            created_at=now,
            updated_at=now,
            version=1,
        )
        self._session.add(block)
        await self._session.flush((block,))
        return block

    async def _load_tbox_element_records(
        self,
        *,
        workspace_id: UUID,
        draft_id: UUID,
        lock: bool = False,
        limit: int | None = None,
    ) -> tuple[KnowledgeStudioTBoxElementRecord, ...]:
        elements_statement = (
            select(TBoxDraftElementModel)
            .where(
                TBoxDraftElementModel.workspace_id == workspace_id,
                TBoxDraftElementModel.draft_id == draft_id,
            )
            .order_by(
                TBoxDraftElementModel.ordinal,
                TBoxDraftElementModel.stable_element_id,
            )
        )
        if limit is not None:
            elements_statement = elements_statement.limit(limit)
        if lock:
            elements_statement = elements_statement.with_for_update(read=True)
        elements = tuple((await self._session.scalars(elements_statement)).all())
        if not elements:
            return ()

        async def load_details(model: type[Any]) -> tuple[Any, ...]:
            statement = select(model).where(
                model.workspace_id == workspace_id,
                model.draft_id == draft_id,
            )
            if lock:
                statement = statement.with_for_update(read=True)
            return tuple((await self._session.scalars(statement)).all())

        classes = await load_details(TBoxClassModel)
        properties = await load_details(TBoxPropertyModel)
        relationships = await load_details(TBoxRelationshipModel)
        class_by_id = {item.stable_class_id: item for item in classes}
        property_by_id = {item.stable_property_id: item for item in properties}
        relationship_by_id = {item.stable_relationship_id: item for item in relationships}
        records: list[KnowledgeStudioTBoxElementRecord] = []
        for element in elements:
            class_detail = class_by_id.get(element.stable_element_id)
            property_detail = property_by_id.get(element.stable_element_id)
            relationship_detail = relationship_by_id.get(element.stable_element_id)
            detail_count = sum(
                detail is not None
                for detail in (class_detail, property_detail, relationship_detail)
            )
            expected_detail_present = (
                (element.kind == "CLASS" and class_detail is not None)
                or (element.kind == "PROPERTY" and property_detail is not None)
                or (element.kind == "RELATION" and relationship_detail is not None)
            )
            if detail_count != 1 or not expected_detail_present:
                raise ConflictError("The normalized T-Box element shape is incomplete.")
            records.append(
                _tbox_element_record(
                    element,
                    class_detail=class_detail,
                    property_detail=property_detail,
                    relationship_detail=relationship_detail,
                )
            )
        return tuple(records)

    async def _load_tbox_models(
        self,
        *,
        workspace_id: UUID,
        draft_id: UUID,
    ) -> tuple[
        tuple[TBoxDraftBlockModel, ...],
        tuple[KnowledgeStudioTBoxElementRecord, ...],
    ]:
        blocks = tuple(
            (
                await self._session.scalars(
                    select(TBoxDraftBlockModel)
                    .where(
                        TBoxDraftBlockModel.workspace_id == workspace_id,
                        TBoxDraftBlockModel.draft_id == draft_id,
                    )
                    .order_by(TBoxDraftBlockModel.ordinal, TBoxDraftBlockModel.id)
                )
            ).all()
        )
        elements = await self._load_tbox_element_records(
            workspace_id=workspace_id,
            draft_id=draft_id,
        )
        return blocks, elements

    async def _replace_tbox_elements(
        self,
        *,
        workspace_id: UUID,
        draft_id: UUID,
        elements_by_block: tuple[tuple[UUID, tuple[TBoxElementInput, ...]], ...],
        now: datetime,
    ) -> None:
        for model in (
            TBoxRelationshipModel,
            TBoxPropertyModel,
            TBoxClassModel,
            TBoxDraftElementModel,
        ):
            await self._session.execute(
                delete(model).where(
                    model.workspace_id == workspace_id,
                    model.draft_id == draft_id,
                )
            )
        ordinal = 0
        detail_rows: list[TBoxClassModel | TBoxPropertyModel | TBoxRelationshipModel] = []
        for block_id, elements in elements_by_block:
            for element in elements:
                self._session.add(
                    TBoxDraftElementModel(
                        id=uuid7(),
                        workspace_id=workspace_id,
                        draft_id=draft_id,
                        block_id=block_id,
                        stable_element_id=element.stable_element_id,
                        kind=element.kind.value,
                        canonical_name=element.canonical_name,
                        display_name=element.display_name,
                        definition=element.definition,
                        aliases=list(element.aliases),
                        layout_x=element.layout_x,
                        layout_y=element.layout_y,
                        ordinal=ordinal,
                        created_at=now,
                        updated_at=now,
                        version=1,
                    )
                )
                if element.kind.value == "CLASS":
                    detail_rows.append(
                        TBoxClassModel(
                            id=uuid7(),
                            workspace_id=workspace_id,
                            draft_id=draft_id,
                            stable_class_id=element.stable_element_id,
                            parent_stable_class_id=element.parent_stable_element_id,
                            hierarchy_relation=element.hierarchy_relation or "SUBCLASS_OF",
                            metadata_reference_id=element.metadata_reference_id,
                            metadata_reference_urn=element.metadata_reference_urn,
                            created_at=now,
                            updated_at=now,
                            version=1,
                        )
                    )
                elif element.kind.value == "PROPERTY":
                    assert element.parent_stable_element_id is not None
                    assert element.data_type is not None
                    assert element.nullable is not None
                    detail_rows.append(
                        TBoxPropertyModel(
                            id=uuid7(),
                            workspace_id=workspace_id,
                            draft_id=draft_id,
                            stable_property_id=element.stable_element_id,
                            owner_stable_class_id=element.parent_stable_element_id,
                            data_type=element.data_type,
                            nullable=element.nullable,
                            unit=element.unit,
                            vector_index_enabled=element.vector_index_enabled,
                            metadata_reference_id=element.metadata_reference_id,
                            metadata_reference_urn=element.metadata_reference_urn,
                            created_at=now,
                            updated_at=now,
                            version=1,
                        )
                    )
                else:
                    assert element.source_stable_element_id is not None
                    assert element.target_stable_element_id is not None
                    detail_rows.append(
                        TBoxRelationshipModel(
                            id=uuid7(),
                            workspace_id=workspace_id,
                            draft_id=draft_id,
                            stable_relationship_id=element.stable_element_id,
                            source_stable_class_id=element.source_stable_element_id,
                            target_stable_class_id=element.target_stable_element_id,
                            relationship_kind="ASSOCIATION",
                            metadata_reference_id=element.metadata_reference_id,
                            metadata_reference_urn=element.metadata_reference_urn,
                            created_at=now,
                            updated_at=now,
                            version=1,
                        )
                    )
                ordinal += 1
        await self._session.flush()
        self._session.add_all(detail_rows)

    async def _tbox_mutation_replay(
        self,
        *,
        workspace_id: UUID,
        author_id: UUID,
        draft_id: UUID,
        operation: str,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioTBoxRecord | None:
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
        if existing is None:
            return None
        if existing.request_hash != request_hash:
            raise ConflictError("The idempotency key was used with a different request.")
        raw_draft = existing.result.get("draft")
        if not isinstance(raw_draft, dict):
            raise ConflictError("The idempotent T-Box result is invalid.")
        replay_draft = studio_draft_record_from_result(raw_draft)
        if (
            replay_draft.workspace_id != workspace_id
            or replay_draft.author_id != author_id
            or replay_draft.draft_id != draft_id
        ):
            raise ConflictError("The idempotent T-Box result is bound to another Draft.")
        current = await self.get_tbox(
            workspace_id=workspace_id,
            actor_id=author_id,
            draft_id=draft_id,
        )
        if current is None or current.draft.version != replay_draft.version:
            raise ConflictError("The idempotent T-Box response is older than the current Draft.")
        return current

    async def _save_tbox_mutation(
        self,
        *,
        draft: KnowledgeStudioDraftModel,
        workspace_id: UUID,
        author_id: UUID,
        operation: str,
        idempotency_key: str,
        request_hash: str,
    ) -> KnowledgeStudioTBoxRecord:
        try:
            await self._session.flush()
            blocks, elements = await self._load_tbox_models(
                workspace_id=workspace_id,
                draft_id=draft.id,
            )
            record = _tbox_record(draft, blocks, elements)
            await SqlIdempotencyStore(self._session).save_result(
                workspace_id=workspace_id,
                key=idempotency_key,
                operation=operation,
                request_hash=request_hash,
                result={"draft": studio_draft_result(record.draft)},
            )
            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()
            raise ConflictError("The typed T-Box operation conflicts with the Draft.") from error
        if record.draft.author_id != author_id:
            raise ConflictError("The T-Box mutation result is bound to another author.")
        return record

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
        await self._ensure_default_domain(
            workspace_id=workspace_id,
            domain_id=domain_id,
        )
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

    async def _ensure_default_domain(
        self,
        *,
        workspace_id: UUID,
        domain_id: UUID,
    ) -> None:
        default = next(
            (
                (slug, display_name)
                for slug, display_name in DEFAULT_KNOWLEDGE_DOMAINS
                if default_knowledge_domain_id(workspace_id, slug) == domain_id
            ),
            None,
        )
        if default is None:
            return
        slug, display_name = default
        now = utc_now()
        statement = pg_insert(CatalogVocabularyEntryModel).values(
            id=domain_id,
            workspace_id=workspace_id,
            kind="DOMAIN",
            provider_ref=f"urn:li:domain:datariver-default-{slug}",
            display_name=display_name,
            lifecycle="ACTIVE",
            source_version=DEFAULT_KNOWLEDGE_DOMAIN_SOURCE_VERSION,
            observed_at=now,
            updated_at=now,
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=("workspace_id", "kind", "provider_ref"),
                set_={
                    "display_name": display_name,
                    "lifecycle": "ACTIVE",
                    "source_version": DEFAULT_KNOWLEDGE_DOMAIN_SOURCE_VERSION,
                    "observed_at": now,
                    "updated_at": now,
                },
            )
        )

    async def _require_alias_available(
        self,
        *,
        workspace_id: UUID,
        endpoint_alias: str,
        exclude_draft_id: UUID | None = None,
    ) -> None:
        await self._session.execute(
            select(
                func.pg_advisory_xact_lock(
                    func.hashtextextended(f"{workspace_id}:{endpoint_alias}", 0)
                )
            )
        )
        graph_id = await self._session.scalar(
            select(GraphModel.id).where(
                GraphModel.workspace_id == workspace_id,
                GraphModel.slug == endpoint_alias,
            )
        )
        if graph_id is not None:
            raise ConflictError("A knowledge graph already uses this endpoint alias.")
        statement = select(KnowledgeStudioDraftModel.id).where(
            KnowledgeStudioDraftModel.workspace_id == workspace_id,
            KnowledgeStudioDraftModel.state.in_(("DRAFT", "REVIEW")),
            cast(KnowledgeStudioDraftModel.endpoint_aliases, JSONB).contains([endpoint_alias]),
        )
        if exclude_draft_id is not None:
            statement = statement.where(KnowledgeStudioDraftModel.id != exclude_draft_id)
        if await self._session.scalar(statement) is not None:
            raise ConflictError("A live Knowledge Studio draft already uses this endpoint alias.")

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
