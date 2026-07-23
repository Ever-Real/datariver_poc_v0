from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from typing import Protocol
from uuid import UUID

from datariver.application.catalog_metadata_upload_parser import (
    CatalogMetadataAspect,
    CatalogMetadataCandidateDraft,
    CatalogMetadataCandidateKind,
    CatalogMetadataOperation,
    CatalogMetadataRecordKind,
    CatalogMetadataRowEvidence,
)
from datariver.application.change_numbers import change_request_number
from datariver.application.dto import (
    CatalogMetadataBindingCommand,
    CatalogMetadataCandidatePage,
    TypedCatalogMetadataPreview,
)
from datariver.application.ports import DataHubGateway
from datariver.application.services.catalog_metadata_compiler import (
    CatalogMetadataVocabularyReference,
    compile_catalog_metadata_mutation,
)
from datariver.domain.authz import Classification, EnvironmentAttributes, SubjectAttributes
from datariver.domain.common import ConflictError, canonical_json_hash, uuid7
from datariver.domain.governance import (
    ChangeItem,
    ChangePriority,
    ChangeRequest,
    ChangeUrgency,
    change_target_binding_hash,
)

_MAXIMUM_DESCRIPTION_PREVIEW_ITEMS = 20


class CatalogMetadataCandidateQuery(Protocol):
    async def get_candidate_for_execution(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        preparation_id: UUID,
        candidate_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> CatalogMetadataCandidatePage: ...


class CatalogMetadataVocabularyResolver(Protocol):
    async def resolve(
        self,
        *,
        workspace_id: UUID,
        vocabulary_ids: tuple[UUID, ...],
        expected_kind: str,
    ) -> Mapping[UUID, CatalogMetadataVocabularyReference]: ...


class TypedCatalogMetadataGovernanceCreator(Protocol):
    async def find_idempotent_create(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> ChangeRequest | None: ...

    async def create_change_request(
        self,
        *,
        workspace_id: UUID,
        number: str,
        request_type: str,
        title: str,
        description: str,
        requester_id: UUID,
        items: list[ChangeItem],
        subject: SubjectAttributes,
        classification: Classification,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
        require_raw_operator_gate: bool,
        registration_metadata_binding: CatalogMetadataBindingCommand,
        requested_due_date: date | None = None,
        priority: ChangePriority | None = None,
        urgency: ChangeUrgency | None = None,
    ) -> ChangeRequest: ...


def catalog_metadata_item_contract_hash(
    *,
    workspace_id: UUID,
    candidate_id: UUID,
    content_profile: str,
    candidate_kind: str,
    candidate_hash: str,
    row_root_hash: str,
    aspect_name: str,
    target_asset_id: UUID,
    target_binding_hash: str,
    before_hash: str,
    after_hash: str,
) -> str:
    return canonical_json_hash(
        {
            "after_hash": after_hash,
            "aspect_name": aspect_name,
            "before_hash": before_hash,
            "candidate_hash": candidate_hash,
            "candidate_id": str(candidate_id),
            "candidate_kind": candidate_kind,
            "content_profile": content_profile,
            "contract": "catalog-metadata-change-item-v1",
            "row_root_hash": row_root_hash,
            "target_asset_id": str(target_asset_id),
            "target_binding_hash": target_binding_hash,
            "workspace_id": str(workspace_id),
        }
    )


class TypedCatalogMetadataRegistrationService:
    """Preview and create one fixed-Aspect CR from one immutable V3 group."""

    def __init__(
        self,
        *,
        candidates: CatalogMetadataCandidateQuery,
        vocabulary: CatalogMetadataVocabularyResolver,
        datahub: DataHubGateway,
        governance: TypedCatalogMetadataGovernanceCreator,
    ) -> None:
        self._candidates = candidates
        self._vocabulary = vocabulary
        self._datahub = datahub
        self._governance = governance

    async def preview(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        preparation_id: UUID,
        candidate_id: UUID,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> TypedCatalogMetadataPreview:
        page = await self._candidates.get_candidate_for_execution(
            workspace_id=workspace_id,
            upload_id=upload_id,
            preparation_id=preparation_id,
            candidate_id=candidate_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        if len(page.items) != 1:
            raise ConflictError(
                "The typed catalog metadata candidate evidence is unavailable.",
                details={"code": "CATALOG_METADATA_CANDIDATE_UNAVAILABLE"},
            )
        receipt = page.receipt
        if (
            not receipt.object_locator_hash
            or re.fullmatch(r"[0-9a-f]{64}", receipt.object_locator_hash) is None
        ):
            raise ConflictError(
                "The typed catalog metadata object identity evidence is unavailable.",
                details={"code": "CATALOG_METADATA_CANDIDATE_UNAVAILABLE"},
            )
        view = page.items[0]
        evidence = view.evidence
        target = view.current_target
        candidate = _to_candidate_draft(page)
        expected_kind = _controlled_kind(candidate.record_kind)
        controlled_ids = tuple(
            row.controlled_ref for row in candidate.rows if row.controlled_ref is not None
        )
        vocabulary: Mapping[UUID, CatalogMetadataVocabularyReference]
        if expected_kind is None:
            vocabulary = {}
        else:
            vocabulary = await self._vocabulary.resolve(
                workspace_id=workspace_id,
                vocabulary_ids=controlled_ids,
                expected_kind=expected_kind,
            )
        snapshot = await self._datahub.read_aspect(
            external_urn=target.external_urn,
            aspect_name=evidence.aspect_name,
        )
        compiled = compile_catalog_metadata_mutation(
            asset=target,
            snapshot=snapshot,
            candidate=candidate,
            vocabulary=vocabulary,
        )
        after_hash = canonical_json_hash(compiled.proposed_document)
        target_binding_hash = change_target_binding_hash(
            target_ref=target.external_urn,
            asset_id=target.asset_id,
            asset_type=target.asset_type,
            system_id=target.system_id,
            domain_id=target.domain_id,
            owner_department_id=target.owner_department_id,
            classification=target.classification,
            lifecycle=target.lifecycle,
        )
        item_contract_hash = catalog_metadata_item_contract_hash(
            workspace_id=workspace_id,
            candidate_id=evidence.candidate_id,
            content_profile=evidence.content_profile,
            candidate_kind=evidence.candidate_kind,
            candidate_hash=evidence.candidate_hash,
            row_root_hash=evidence.row_root_hash,
            aspect_name=evidence.aspect_name,
            target_asset_id=target.asset_id,
            target_binding_hash=target_binding_hash,
            before_hash=snapshot.content_hash,
            after_hash=after_hash,
        )
        vocabulary_versions_hash = canonical_json_hash(
            [
                {
                    "id": str(value.vocabulary_id),
                    "kind": value.kind,
                    "source_version": value.source_version,
                }
                for _, value in sorted(vocabulary.items(), key=lambda pair: str(pair[0]))
            ]
        )
        preview_hash = canonical_json_hash(
            {
                "accepted_etag": receipt.accepted_etag,
                "accepted_version_id": receipt.accepted_version_id,
                "candidate_root_hash": receipt.candidate_root_hash,
                "contract": "typed-catalog-metadata-preview-v1",
                "item_contract_hash": item_contract_hash,
                "manifest_version": receipt.manifest_version,
                "object_locator_hash": receipt.object_locator_hash,
                "provider_source_version": snapshot.source_version,
                "receipt_hash": receipt.receipt_hash,
                "target_source_version": target.source_version,
                "vocabulary_versions_hash": vocabulary_versions_hash,
                "workspace_id": str(workspace_id),
            }
        )
        binding = CatalogMetadataBindingCommand(
            workspace_id=workspace_id,
            upload_id=upload_id,
            preparation_id=preparation_id,
            receipt_id=receipt.receipt_id,
            receipt_hash=receipt.receipt_hash,
            content_profile=evidence.content_profile,
            candidate_id=evidence.candidate_id,
            candidate_kind=evidence.candidate_kind,
            candidate_hash=evidence.candidate_hash,
            aspect_name=evidence.aspect_name,
            before_hash=snapshot.content_hash,
            after_hash=after_hash,
            item_contract_hash=item_contract_hash,
            target_asset_id=target.asset_id,
            target_source_version=target.source_version,
            target_binding_hash=target_binding_hash,
        )
        description_changes = (
            tuple(
                (
                    field_path,
                    current_value,
                    row.value_text if row.operation is CatalogMetadataOperation.SET else None,
                )
                for (field_path, current_value), row in zip(
                    compiled.current_descriptions,
                    candidate.rows,
                    strict=True,
                )
            )
            if compiled.current_descriptions
            else ()
        )
        return TypedCatalogMetadataPreview(
            candidate_id=evidence.candidate_id,
            target_asset_id=target.asset_id,
            target_ref=target.external_urn,
            platform=evidence.submitted_platform,
            database_name=evidence.submitted_database_name,
            schema_name=evidence.submitted_schema_name,
            table_name=evidence.submitted_table_name,
            classification=target.classification,
            record_kind=evidence.record_kind,
            candidate_kind=evidence.candidate_kind,
            aspect_name=evidence.aspect_name,
            operation_count=len(evidence.rows),
            description_change_count=len(description_changes),
            description_change_sample=description_changes[:_MAXIMUM_DESCRIPTION_PREVIEW_ITEMS],
            description_changes_truncated=(
                len(description_changes) > _MAXIMUM_DESCRIPTION_PREVIEW_ITEMS
            ),
            current_reference_count=len(compiled.current_refs),
            proposed_reference_count=len(compiled.proposed_refs),
            before_hash=snapshot.content_hash,
            after_hash=after_hash,
            source_version=snapshot.source_version,
            observed_at=snapshot.observed_at,
            preview_etag=f'"{preview_hash}"',
            binding=binding,
            proposed_document=compiled.proposed_document,
        )

    async def create_change_request(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        preparation_id: UUID,
        candidate_id: UUID,
        expected_preview_etag: str,
        title: str,
        reason: str,
        subject: SubjectAttributes,
        environment: EnvironmentAttributes,
        request_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> ChangeRequest:
        existing = await self._governance.find_idempotent_create(
            workspace_id=workspace_id,
            subject=subject,
            environment=environment,
            request_id=f"{request_id}:idempotent-recovery",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if existing is not None:
            return existing
        preview = await self.preview(
            workspace_id=workspace_id,
            upload_id=upload_id,
            preparation_id=preparation_id,
            candidate_id=candidate_id,
            subject=subject,
            environment=environment,
            request_id=f"{request_id}:fresh-preview",
        )
        if preview.preview_etag != expected_preview_etag:
            raise ConflictError(
                "The typed catalog metadata preview is stale.",
                details={"code": "PREVIEW_ETAG_MISMATCH"},
            )
        return await self._governance.create_change_request(
            workspace_id=workspace_id,
            number=change_request_number(preview.platform),
            request_type="BULK_CATALOG_METADATA",
            title=title,
            description=reason,
            requester_id=subject.subject_id,
            items=[
                ChangeItem(
                    item_id=uuid7(),
                    target_type="DATAHUB_ASPECT",
                    target_ref=preview.target_ref,
                    operation="UPSERT",
                    after_document=dict(preview.proposed_document),
                    aspect_name=preview.aspect_name,
                    before_hash=preview.before_hash,
                    after_hash=preview.after_hash,
                    item_contract_hash=preview.binding.item_contract_hash,
                )
            ],
            subject=subject,
            classification=preview.classification,
            environment=environment,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            require_raw_operator_gate=False,
            registration_metadata_binding=preview.binding,
        )


def _to_candidate_draft(page: CatalogMetadataCandidatePage) -> CatalogMetadataCandidateDraft:
    evidence = page.items[0].evidence
    record_kind = CatalogMetadataRecordKind(evidence.record_kind)
    aspect_name = CatalogMetadataAspect(evidence.aspect_name)
    rows = tuple(
        CatalogMetadataRowEvidence(
            workspace_id=evidence.workspace_id,
            ordinal=row.ordinal,
            target_asset_id=evidence.target_asset_id,
            platform=evidence.submitted_platform,
            database_name=evidence.submitted_database_name,
            schema_name=evidence.submitted_schema_name,
            table_name=evidence.submitted_table_name,
            record_kind=CatalogMetadataRecordKind(row.record_kind),
            aspect_name=CatalogMetadataAspect(row.aspect_name),
            operation=CatalogMetadataOperation(row.operation),
            field_path=row.field_path,
            value_text=row.value_text,
            controlled_ref=row.controlled_ref_id,
            semantic_key=_semantic_key(
                record_kind=CatalogMetadataRecordKind(row.record_kind),
                field_path=row.field_path,
                controlled_ref=row.controlled_ref_id,
            ),
            row_hash=row.row_hash,
        )
        for row in evidence.rows
    )
    return CatalogMetadataCandidateDraft(
        workspace_id=evidence.workspace_id,
        ordinal=evidence.ordinal,
        target_asset_id=evidence.target_asset_id,
        platform=evidence.submitted_platform,
        database_name=evidence.submitted_database_name,
        schema_name=evidence.submitted_schema_name,
        table_name=evidence.submitted_table_name,
        record_kind=record_kind,
        candidate_kind=CatalogMetadataCandidateKind(evidence.candidate_kind),
        aspect_name=aspect_name,
        rows=rows,
        submitted_identity_hash=evidence.submitted_identity_hash,
        candidate_hash=evidence.candidate_hash,
    )


def _semantic_key(
    *,
    record_kind: CatalogMetadataRecordKind,
    field_path: str | None,
    controlled_ref: UUID | None,
) -> str:
    if record_kind is CatalogMetadataRecordKind.COLUMN_DESCRIPTION:
        if field_path is None:
            raise ValueError("Column metadata evidence requires a field path.")
        return f"{record_kind.value}:{field_path}"
    if record_kind in {
        CatalogMetadataRecordKind.DATASET_TAG,
        CatalogMetadataRecordKind.DATASET_TERM,
    }:
        if controlled_ref is None:
            raise ValueError("Additive metadata evidence requires a controlled reference.")
        return f"{record_kind.value}:{controlled_ref}"
    return record_kind.value


def _controlled_kind(record_kind: CatalogMetadataRecordKind) -> str | None:
    return {
        CatalogMetadataRecordKind.DATASET_DOMAIN: "DOMAIN",
        CatalogMetadataRecordKind.DATASET_TERM: "TERM",
        CatalogMetadataRecordKind.DATASET_TAG: "TAG",
    }.get(record_kind)
