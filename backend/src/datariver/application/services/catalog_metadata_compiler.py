from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from datariver.application.catalog_metadata_upload_parser import (
    CatalogMetadataCandidateDraft,
    CatalogMetadataOperation,
    CatalogMetadataRecordKind,
)
from datariver.application.dto import CatalogAssetIndex, DataHubAspectSnapshot
from datariver.application.services.catalog_description import (
    controlled_metadata_refs,
    prepare_column_descriptions_document,
    prepare_controlled_metadata_document,
    prepare_dataset_description_document,
)
from datariver.domain.common import ConflictError


@dataclass(frozen=True, slots=True)
class CatalogMetadataVocabularyReference:
    vocabulary_id: UUID
    kind: str
    provider_ref: str
    source_version: str


@dataclass(frozen=True, slots=True)
class CompiledCatalogMetadataMutation:
    current_descriptions: tuple[tuple[str | None, str | None], ...]
    current_refs: tuple[str, ...]
    proposed_refs: tuple[str, ...]
    proposed_document: Mapping[str, Any]


def compile_catalog_metadata_mutation(
    *,
    asset: CatalogAssetIndex,
    snapshot: DataHubAspectSnapshot,
    candidate: CatalogMetadataCandidateDraft,
    vocabulary: Mapping[UUID, CatalogMetadataVocabularyReference],
) -> CompiledCatalogMetadataMutation:
    """Compile only the fixed V3 discriminator; no caller chooses an Aspect or provider target."""

    if (
        candidate.workspace_id != asset.workspace_id
        or candidate.target_asset_id != asset.asset_id
        or snapshot.aspect_name != candidate.aspect_name.value
        or not candidate.rows
    ):
        raise ConflictError(
            "The typed catalog metadata candidate no longer matches its target.",
            details={"code": "CATALOG_METADATA_CANDIDATE_DRIFT"},
        )
    controlled_ids = tuple(
        row.controlled_ref for row in candidate.rows if row.controlled_ref is not None
    )
    if set(vocabulary) != set(controlled_ids):
        raise ConflictError(
            "The controlled vocabulary evidence is unavailable.",
            details={"code": "CATALOG_VOCABULARY_DRIFT"},
        )

    if candidate.record_kind is CatalogMetadataRecordKind.TABLE_DESCRIPTION:
        if len(candidate.rows) != 1:
            raise _candidate_shape_error()
        row = candidate.rows[0]
        description = row.value_text if row.operation is CatalogMetadataOperation.SET else ""
        current, document = prepare_dataset_description_document(
            asset=asset,
            snapshot=snapshot,
            proposed_description=description or "",
        )
        return CompiledCatalogMetadataMutation(
            current_descriptions=((None, current),),
            current_refs=(),
            proposed_refs=(),
            proposed_document=document,
        )

    if candidate.record_kind is CatalogMetadataRecordKind.COLUMN_DESCRIPTION:
        changes = tuple(
            (
                _required_field_path(row.field_path),
                _required_description(row.value_text)
                if row.operation is CatalogMetadataOperation.SET
                else "",
            )
            for row in candidate.rows
        )
        current_descriptions, document = prepare_column_descriptions_document(
            asset=asset,
            snapshot=snapshot,
            changes=changes,
        )
        return CompiledCatalogMetadataMutation(
            current_descriptions=tuple(
                (field_path, value) for field_path, value in current_descriptions
            ),
            current_refs=(),
            proposed_refs=(),
            proposed_document=document,
        )

    expected_kind = {
        CatalogMetadataRecordKind.DATASET_DOMAIN: "DOMAIN",
        CatalogMetadataRecordKind.DATASET_TERM: "TERM",
        CatalogMetadataRecordKind.DATASET_TAG: "TAG",
    }.get(candidate.record_kind)
    if expected_kind is None:
        raise _candidate_shape_error()
    resolved_refs: list[str] = []
    for controlled_id in controlled_ids:
        reference = vocabulary.get(controlled_id)
        if reference is None or reference.kind != expected_kind or not reference.source_version:
            raise ConflictError(
                "The controlled vocabulary evidence changed.",
                details={"code": "CATALOG_VOCABULARY_DRIFT"},
            )
        resolved_refs.append(reference.provider_ref)
    if candidate.record_kind is CatalogMetadataRecordKind.DATASET_DOMAIN:
        proposed_refs = tuple(resolved_refs)
    else:
        current_refs = controlled_metadata_refs(
            document=snapshot.document,
            aspect_name=candidate.aspect_name.value,
        )
        proposed_refs = tuple(sorted(set((*current_refs, *resolved_refs))))
    current_refs, document = prepare_controlled_metadata_document(
        asset=asset,
        snapshot=snapshot,
        aspect_name=candidate.aspect_name.value,
        refs=proposed_refs,
    )
    return CompiledCatalogMetadataMutation(
        current_descriptions=(),
        current_refs=current_refs,
        proposed_refs=proposed_refs,
        proposed_document=document,
    )


def _required_field_path(value: str | None) -> str:
    if value is None:
        raise _candidate_shape_error()
    return value


def _required_description(value: str | None) -> str:
    if value is None:
        raise _candidate_shape_error()
    return value


def _candidate_shape_error() -> ConflictError:
    return ConflictError(
        "The typed catalog metadata candidate shape is invalid.",
        details={"code": "CATALOG_METADATA_CANDIDATE_INVALID"},
    )
