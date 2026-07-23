from __future__ import annotations

from types import MappingProxyType
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from datariver.application.catalog_metadata_upload_parser import (
    CatalogMetadataCandidateDraft,
    catalog_metadata_row_root,
    compile_catalog_metadata_candidates,
)
from datariver.application.dto import (
    CatalogAssetIndex,
    CatalogMetadataCandidateEvidence,
    CatalogMetadataCandidatePage,
    CatalogMetadataCandidateView,
    CatalogMetadataRowEvidenceRecord,
    DataHubAspectSnapshot,
    UploadPreparationReceiptEvidence,
)
from datariver.application.services.catalog_metadata_compiler import (
    CatalogMetadataVocabularyReference,
)
from datariver.application.services.typed_catalog_metadata_registration import (
    TypedCatalogMetadataRegistrationService,
)
from datariver.application.typed_upload_profiles import CATALOG_METADATA_ROWS_CSV_V1
from datariver.domain.authz import Classification, EnvironmentAttributes, SubjectAttributes
from datariver.domain.common import ConflictError, canonical_json_hash, utc_now
from datariver.domain.governance import ChangeRequest


class _Candidates:
    def __init__(self, page: CatalogMetadataCandidatePage) -> None:
        self.page = page
        self.calls = 0

    async def get_candidate_for_execution(self, **_: object) -> CatalogMetadataCandidatePage:
        self.calls += 1
        return self.page


class _Vocabulary:
    def __init__(self, values: dict[UUID, CatalogMetadataVocabularyReference]) -> None:
        self.values = values
        self.calls: list[tuple[tuple[UUID, ...], str]] = []

    async def resolve(
        self,
        *,
        workspace_id: UUID,
        vocabulary_ids: tuple[UUID, ...],
        expected_kind: str,
    ) -> dict[UUID, CatalogMetadataVocabularyReference]:
        del workspace_id
        self.calls.append((vocabulary_ids, expected_kind))
        return {value: self.values[value] for value in vocabulary_ids}


class _DataHub:
    def __init__(self, snapshot: DataHubAspectSnapshot) -> None:
        self.snapshot = snapshot
        self.reads: list[tuple[str, str]] = []

    async def read_aspect(self, *, external_urn: str, aspect_name: str) -> DataHubAspectSnapshot:
        self.reads.append((external_urn, aspect_name))
        return self.snapshot


class _Governance:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.existing: ChangeRequest | None = None
        self.result = cast(ChangeRequest, object())

    async def find_idempotent_create(self, **_: object) -> ChangeRequest | None:
        return self.existing

    async def create_change_request(self, **kwargs: Any) -> ChangeRequest:
        self.calls.append(kwargs)
        return self.result


def _page(candidate: CatalogMetadataCandidateDraft) -> CatalogMetadataCandidatePage:
    now = utc_now()
    receipt_id = uuid4()
    asset = CatalogAssetIndex(
        asset_id=candidate.target_asset_id,
        workspace_id=candidate.workspace_id,
        external_urn=f"urn:li:dataset:{candidate.target_asset_id}",
        asset_type="DATASET",
        name=candidate.table_name,
        description="old",
        platform=candidate.platform,
        database_name=candidate.database_name,
        schema_name=candidate.schema_name,
        domain_id=None,
        system_id=uuid4(),
        owner_department_id=uuid4(),
        classification=Classification.CONFIDENTIAL,
        lifecycle="ACTIVE",
        source_version="projection-7",
        observed_at=now,
        column_names=("id", "amount"),
    )
    evidence = CatalogMetadataCandidateEvidence(
        candidate_id=uuid4(),
        workspace_id=candidate.workspace_id,
        receipt_id=receipt_id,
        ordinal=candidate.ordinal,
        content_profile=CATALOG_METADATA_ROWS_CSV_V1.content_profile.value,
        evidence_version=candidate.evidence_version,
        record_kind=candidate.record_kind.value,
        candidate_kind=candidate.candidate_kind.value,
        target_asset_id=candidate.target_asset_id,
        aspect_name=candidate.aspect_name.value,
        submitted_platform=candidate.platform,
        submitted_database_name=candidate.database_name,
        submitted_schema_name=candidate.schema_name,
        submitted_table_name=candidate.table_name,
        submitted_identity_hash=candidate.submitted_identity_hash,
        row_root_hash=catalog_metadata_row_root(tuple(row.row_hash for row in candidate.rows)),
        candidate_hash=candidate.candidate_hash,
        rows=tuple(
            CatalogMetadataRowEvidenceRecord(
                row_id=uuid4(),
                ordinal=row.ordinal,
                record_kind=row.record_kind.value,
                aspect_name=row.aspect_name.value,
                operation=row.operation.value,
                field_path=row.field_path,
                value_text=row.value_text,
                controlled_ref_id=row.controlled_ref,
                controlled_kind=(
                    {
                        "DATASET_DOMAIN": "DOMAIN",
                        "DATASET_TERM": "TERM",
                        "DATASET_TAG": "TAG",
                    }.get(row.record_kind.value)
                    if row.controlled_ref is not None
                    else None
                ),
                semantic_target_hash="1" * 64,
                row_hash=row.row_hash,
            )
            for row in candidate.rows
        ),
        created_at=now,
    )
    receipt = UploadPreparationReceiptEvidence(
        receipt_id=receipt_id,
        workspace_id=candidate.workspace_id,
        preparation_id=uuid4(),
        upload_id=uuid4(),
        manifest_version=3,
        source_sha256="a" * 64,
        accepted_sha256="a" * 64,
        content_profile=CATALOG_METADATA_ROWS_CSV_V1.content_profile.value,
        parser_version=CATALOG_METADATA_ROWS_CSV_V1.parser_version,
        scanner_version="scanner-v1",
        schema_version=CATALOG_METADATA_ROWS_CSV_V1.schema_version,
        configuration_hash=CATALOG_METADATA_ROWS_CSV_V1.configuration_hash,
        item_count=len(candidate.rows),
        rejected_count=0,
        candidate_root_hash="b" * 64,
        receipt_hash="c" * 64,
        observed_at=now,
        created_at=now,
        candidate_count=1,
        first_ordinal=1,
        last_ordinal=1,
        legacy_candidate_count=0,
        object_locator_hash="d" * 64,
        accepted_etag="etag",
        accepted_version_id="version",
    )
    return CatalogMetadataCandidatePage(
        items=(CatalogMetadataCandidateView(evidence=evidence, current_target=asset),),
        next_cursor=None,
        receipt=receipt,
        projection_version=4,
        policy_version="builtin-abac-v2",
        classification_policy_version=2,
        authorization_generation=9,
    )


def _fixture(
    *,
    record_kind: str = "TABLE_DESCRIPTION",
    operation: str = "SET",
    value_text: str = "new",
    controlled_ref: UUID | None = None,
) -> tuple[
    TypedCatalogMetadataRegistrationService,
    _Candidates,
    _Vocabulary,
    _DataHub,
    _Governance,
    SubjectAttributes,
    EnvironmentAttributes,
    CatalogMetadataCandidatePage,
]:
    workspace_id = uuid4()
    asset_id = uuid4()
    values = [
        (
            1,
            (
                record_kind,
                str(asset_id),
                "postgres",
                "warehouse",
                "public",
                "orders",
                "",
                operation,
                value_text,
                str(controlled_ref) if controlled_ref is not None else "",
            ),
        )
    ]
    candidate = compile_catalog_metadata_candidates(
        workspace_id=workspace_id,
        rows=values,
        definition=CATALOG_METADATA_ROWS_CSV_V1,
    )[0]
    page = _page(candidate)
    target = page.items[0].current_target
    document: dict[str, object]
    if candidate.aspect_name.value == "datasetProperties":
        document = {"description": "old", "custom": {"preserved": True}}
    elif candidate.aspect_name.value == "globalTags":
        document = {"tags": [{"tag": "urn:li:tag:existing"}], "custom": True}
    else:
        document = {}
    snapshot = DataHubAspectSnapshot(
        urn=target.external_urn,
        aspect_name=candidate.aspect_name.value,
        content_hash=canonical_json_hash(document),
        source_version="provider-2",
        observed_at=utc_now(),
        document=MappingProxyType(document),
    )
    vocabulary_values = (
        {
            controlled_ref: CatalogMetadataVocabularyReference(
                vocabulary_id=controlled_ref,
                kind="TAG",
                provider_ref="urn:li:tag:new",
                source_version="tag-3",
            )
        }
        if controlled_ref is not None
        else {}
    )
    candidates = _Candidates(page)
    vocabulary = _Vocabulary(vocabulary_values)
    datahub = _DataHub(snapshot)
    governance = _Governance()
    service = TypedCatalogMetadataRegistrationService(
        candidates=candidates,
        vocabulary=vocabulary,
        datahub=cast(Any, datahub),
        governance=governance,
    )
    subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=uuid4(),
        groups=frozenset({"data-stewards"}),
        job_function="DATA_STEWARD",
        clearance=Classification.RESTRICTED,
    )
    return (
        service,
        candidates,
        vocabulary,
        datahub,
        governance,
        subject,
        EnvironmentAttributes(requested_at=utc_now()),
        page,
    )


@pytest.mark.asyncio
async def test_preview_compiles_fixed_aspect_without_exposing_provider_references() -> None:
    service, _, vocabulary, datahub, _, subject, environment, page = _fixture()
    evidence = page.items[0].evidence

    preview = await service.preview(
        workspace_id=subject.workspace_id,
        upload_id=page.receipt.upload_id,
        preparation_id=page.receipt.preparation_id,
        candidate_id=evidence.candidate_id,
        subject=subject,
        environment=environment,
        request_id="metadata-preview",
    )

    assert vocabulary.calls == []
    assert datahub.reads == [(page.items[0].current_target.external_urn, "datasetProperties")]
    assert preview.aspect_name == "datasetProperties"
    assert preview.operation_count == 1
    assert preview.proposed_document == {
        "custom": {"preserved": True},
        "description": "new",
    }
    assert not hasattr(preview, "current_refs")
    assert preview.binding.item_contract_hash


@pytest.mark.asyncio
async def test_controlled_tag_is_server_resolved_and_only_counts_are_returned() -> None:
    controlled_ref = uuid4()
    service, _, vocabulary, _, _, subject, environment, page = _fixture(
        record_kind="DATASET_TAG",
        operation="ADD",
        value_text="",
        controlled_ref=controlled_ref,
    )
    evidence = page.items[0].evidence

    preview = await service.preview(
        workspace_id=subject.workspace_id,
        upload_id=page.receipt.upload_id,
        preparation_id=page.receipt.preparation_id,
        candidate_id=evidence.candidate_id,
        subject=subject,
        environment=environment,
        request_id="tag-preview",
    )

    assert vocabulary.calls == [((controlled_ref,), "TAG")]
    assert preview.current_reference_count == 1
    assert preview.proposed_reference_count == 2
    assert "urn:li:tag:new" not in repr(preview)


@pytest.mark.asyncio
async def test_create_binds_one_candidate_item_contract_and_rejects_stale_etag() -> None:
    service, _, _, _, governance, subject, environment, page = _fixture()
    evidence = page.items[0].evidence
    preview = await service.preview(
        workspace_id=subject.workspace_id,
        upload_id=page.receipt.upload_id,
        preparation_id=page.receipt.preparation_id,
        candidate_id=evidence.candidate_id,
        subject=subject,
        environment=environment,
        request_id="metadata-preview",
    )

    with pytest.raises(ConflictError, match="preview is stale"):
        await service.create_change_request(
            workspace_id=subject.workspace_id,
            upload_id=page.receipt.upload_id,
            preparation_id=page.receipt.preparation_id,
            candidate_id=evidence.candidate_id,
            expected_preview_etag=f'"{"0" * 64}"',
            title="Metadata update",
            reason="approved",
            subject=subject,
            environment=environment,
            request_id="metadata-stale",
            idempotency_key="metadata-stale-key",
            request_hash="e" * 64,
        )
    assert governance.calls == []

    result = await service.create_change_request(
        workspace_id=subject.workspace_id,
        upload_id=page.receipt.upload_id,
        preparation_id=page.receipt.preparation_id,
        candidate_id=evidence.candidate_id,
        expected_preview_etag=preview.preview_etag,
        title="Metadata update",
        reason="approved",
        subject=subject,
        environment=environment,
        request_id="metadata-create",
        idempotency_key="metadata-create-key",
        request_hash="f" * 64,
    )

    assert result is governance.result
    call = governance.calls[0]
    assert call["request_type"] == "BULK_CATALOG_METADATA"
    assert call["registration_metadata_binding"] == preview.binding
    assert call["require_raw_operator_gate"] is False
    item = call["items"][0]
    assert item.item_contract_hash == preview.binding.item_contract_hash
    assert item.aspect_name == "datasetProperties"


@pytest.mark.asyncio
async def test_idempotent_recovery_precedes_candidate_and_provider_reads() -> None:
    service, candidates, _, datahub, governance, subject, environment, page = _fixture()
    existing = cast(ChangeRequest, object())
    governance.existing = existing
    evidence = page.items[0].evidence

    result = await service.create_change_request(
        workspace_id=subject.workspace_id,
        upload_id=page.receipt.upload_id,
        preparation_id=page.receipt.preparation_id,
        candidate_id=evidence.candidate_id,
        expected_preview_etag=f'"{"0" * 64}"',
        title="Metadata update",
        reason="approved",
        subject=subject,
        environment=environment,
        request_id="metadata-recover",
        idempotency_key="metadata-recover-key",
        request_hash="a" * 64,
    )

    assert result is existing
    assert candidates.calls == 0
    assert datahub.reads == []
