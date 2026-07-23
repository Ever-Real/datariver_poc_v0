from __future__ import annotations

import re
from datetime import date
from typing import Protocol
from uuid import UUID

from datariver.application.change_numbers import change_request_number
from datariver.application.dto import (
    RegistrationCandidateBindingCommand,
    TypedBulkCandidatePreview,
)
from datariver.application.ports import DataHubGateway
from datariver.application.services.catalog_description import (
    DATASET_PROPERTIES_ASPECT,
    prepare_dataset_description_document,
)
from datariver.application.services.registration_candidates import (
    RegistrationCandidateQueryService,
    UploadPreparationEvidenceUnavailable,
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


class TypedBulkGovernanceCreator(Protocol):
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
        registration_candidate_binding: RegistrationCandidateBindingCommand | None = None,
        requested_due_date: date | None = None,
        priority: ChangePriority | None = None,
        urgency: ChangeUrgency | None = None,
    ) -> ChangeRequest: ...


class TypedBulkRegistrationService:
    """Preview and create exactly one governed CR from one immutable V2 candidate."""

    def __init__(
        self,
        *,
        candidates: RegistrationCandidateQueryService,
        datahub: DataHubGateway,
        governance: TypedBulkGovernanceCreator,
    ) -> None:
        self._candidates = candidates
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
    ) -> TypedBulkCandidatePreview:
        page = await self._candidates.get_candidate(
            workspace_id=workspace_id,
            upload_id=upload_id,
            preparation_id=preparation_id,
            candidate_id=candidate_id,
            subject=subject,
            environment=environment,
            request_id=request_id,
        )
        if len(page.items) != 1:
            raise UploadPreparationEvidenceUnavailable(
                "The typed BULK candidate evidence is unavailable."
            )
        receipt = page.receipt
        if (
            not receipt.object_locator_hash
            or re.fullmatch(r"[0-9a-f]{64}", receipt.object_locator_hash) is None
        ):
            raise UploadPreparationEvidenceUnavailable(
                "The typed BULK object identity evidence is unavailable."
            )
        view = page.items[0]
        candidate = view.evidence
        target = view.current_target
        identity = (
            candidate.submitted_platform,
            candidate.submitted_database_name,
            candidate.submitted_schema_name,
            candidate.submitted_table_name,
        )
        if any(not isinstance(value, str) or not value for value in identity):
            raise UploadPreparationEvidenceUnavailable(
                "The typed BULK submitted identity evidence is unavailable."
            )
        platform, database_name, schema_name, table_name = identity
        assert isinstance(platform, str)
        assert isinstance(database_name, str)
        assert isinstance(schema_name, str)
        assert isinstance(table_name, str)
        snapshot = await self._datahub.read_aspect(
            external_urn=target.external_urn,
            aspect_name=DATASET_PROPERTIES_ASPECT,
        )
        current_description, proposed_document = prepare_dataset_description_document(
            asset=target,
            snapshot=snapshot,
            proposed_description=candidate.proposed_description,
        )
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
        binding = RegistrationCandidateBindingCommand(
            workspace_id=workspace_id,
            upload_id=upload_id,
            preparation_id=preparation_id,
            receipt_id=receipt.receipt_id,
            receipt_hash=receipt.receipt_hash,
            candidate_id=candidate.candidate_id,
            candidate_hash=candidate.candidate_hash,
            target_asset_id=target.asset_id,
            target_source_version=target.source_version,
            target_binding_hash=target_binding_hash,
        )
        after_hash = canonical_json_hash(proposed_document)
        preview_hash = canonical_json_hash(
            {
                "accepted_etag": receipt.accepted_etag,
                "accepted_version_id": receipt.accepted_version_id,
                "after_hash": after_hash,
                "before_hash": snapshot.content_hash,
                "candidate_hash": candidate.candidate_hash,
                "candidate_id": str(candidate.candidate_id),
                "candidate_root_hash": receipt.candidate_root_hash,
                "configuration_hash": receipt.configuration_hash,
                "contract": "typed-bulk-description-preview-v1",
                "manifest_version": receipt.manifest_version,
                "object_locator_hash": receipt.object_locator_hash,
                "provider_source_version": snapshot.source_version,
                "receipt_hash": receipt.receipt_hash,
                "target_binding_hash": target_binding_hash,
                "target_source_version": target.source_version,
                "workspace_id": str(workspace_id),
            }
        )
        return TypedBulkCandidatePreview(
            candidate_id=candidate.candidate_id,
            target_asset_id=target.asset_id,
            target_ref=target.external_urn,
            platform=platform,
            database_name=database_name,
            schema_name=schema_name,
            table_name=table_name,
            classification=target.classification,
            current_description=current_description,
            proposed_description=candidate.proposed_description,
            before_hash=snapshot.content_hash,
            after_hash=after_hash,
            source_version=snapshot.source_version,
            observed_at=snapshot.observed_at,
            preview_etag=f'"{preview_hash}"',
            binding=binding,
            proposed_document=proposed_document,
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
                "The typed BULK candidate preview is stale.",
                details={"code": "PREVIEW_ETAG_MISMATCH"},
            )
        return await self._governance.create_change_request(
            workspace_id=workspace_id,
            number=change_request_number(preview.platform),
            request_type="BULK_DATASET_DESCRIPTION",
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
                    aspect_name=DATASET_PROPERTIES_ASPECT,
                    before_hash=preview.before_hash,
                    after_hash=preview.after_hash,
                )
            ],
            subject=subject,
            classification=preview.classification,
            environment=environment,
            request_id=request_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            require_raw_operator_gate=False,
            registration_candidate_binding=preview.binding,
        )
