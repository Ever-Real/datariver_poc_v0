from __future__ import annotations

from types import MappingProxyType
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from datariver.application.dto import (
    CatalogAssetIndex,
    DataHubAspectSnapshot,
    RegistrationCandidateBindingCommand,
    UploadPreparationReceiptEvidence,
    UploadRegistrationCandidateEvidence,
    UploadRegistrationCandidatePage,
    UploadRegistrationCandidateView,
)
from datariver.application.ports import DataHubGateway
from datariver.application.services.registration_candidates import (
    RegistrationCandidateQueryService,
    UploadPreparationEvidenceUnavailable,
)
from datariver.application.services.typed_bulk_registration import (
    TypedBulkGovernanceCreator,
    TypedBulkRegistrationService,
)
from datariver.application.typed_upload_parser import (
    DATASET_DESCRIPTION_CANDIDATE_EVIDENCE_VERSION,
    DATASET_DESCRIPTION_CANDIDATE_KIND,
    dataset_description_candidate_hash,
    dataset_description_submitted_identity_hash,
)
from datariver.application.typed_upload_profiles import DATASET_DESCRIPTION_CSV_V1
from datariver.domain.authz import Classification, EnvironmentAttributes, SubjectAttributes
from datariver.domain.common import ConflictError, ValidationError, canonical_json_hash, utc_now
from datariver.domain.governance import ChangeRequest
from datariver.domain.registration import UploadContentProfile


class FakeCandidateQuery:
    def __init__(self, page: UploadRegistrationCandidatePage) -> None:
        self.page = page
        self.calls = 0

    async def get_candidate(self, **_: object) -> UploadRegistrationCandidatePage:
        self.calls += 1
        return self.page


class FakeDataHub:
    def __init__(self, snapshot: DataHubAspectSnapshot) -> None:
        self.snapshot = snapshot
        self.reads: list[tuple[str, str]] = []

    async def read_aspect(self, *, external_urn: str, aspect_name: str) -> DataHubAspectSnapshot:
        self.reads.append((external_urn, aspect_name))
        return self.snapshot


class FakeGovernance:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.result = cast(ChangeRequest, object())
        self.existing: ChangeRequest | None = None

    async def find_idempotent_create(self, **_: Any) -> ChangeRequest | None:
        return self.existing

    async def create_change_request(self, **kwargs: Any) -> ChangeRequest:
        self.calls.append(kwargs)
        return self.result


def _fixture(
    *,
    current_description: str | None = "old description",
    proposed_description: str = "new description",
    object_locator_hash: str = "d" * 64,
) -> tuple[
    TypedBulkRegistrationService,
    FakeCandidateQuery,
    FakeDataHub,
    FakeGovernance,
    SubjectAttributes,
    EnvironmentAttributes,
    UUID,
    UUID,
    UUID,
    UUID,
]:
    now = utc_now()
    workspace_id = uuid4()
    upload_id = uuid4()
    preparation_id = uuid4()
    receipt_id = uuid4()
    candidate_id = uuid4()
    asset_id = uuid4()
    platform = "oracle"
    database_name = "fab"
    schema_name = "mes"
    table_name = "wafer_events"
    external_urn = f"urn:li:dataset:{asset_id}"
    identity_hash = dataset_description_submitted_identity_hash(
        workspace_id=workspace_id,
        target_asset_id=asset_id,
        platform=platform,
        database_name=database_name,
        schema_name=schema_name,
        table_name=table_name,
    )
    candidate = UploadRegistrationCandidateEvidence(
        candidate_id=candidate_id,
        workspace_id=workspace_id,
        receipt_id=receipt_id,
        ordinal=1,
        target_asset_id=asset_id,
        candidate_kind=DATASET_DESCRIPTION_CANDIDATE_KIND,
        proposed_description=proposed_description,
        evidence_version=DATASET_DESCRIPTION_CANDIDATE_EVIDENCE_VERSION,
        submitted_platform=platform,
        submitted_database_name=database_name,
        submitted_schema_name=schema_name,
        submitted_table_name=table_name,
        submitted_identity_hash=identity_hash,
        candidate_hash=dataset_description_candidate_hash(
            workspace_id=workspace_id,
            target_asset_id=asset_id,
            proposed_description=proposed_description,
            submitted_identity_hash=identity_hash,
        ),
        created_at=now,
    )
    target = CatalogAssetIndex(
        asset_id=asset_id,
        workspace_id=workspace_id,
        external_urn=external_urn,
        asset_type="DATASET",
        name=table_name,
        description=current_description,
        platform=platform,
        database_name=database_name,
        schema_name=schema_name,
        domain_id=None,
        system_id=uuid4(),
        owner_department_id=uuid4(),
        classification=Classification.CONFIDENTIAL,
        lifecycle="ACTIVE",
        source_version="projection-7",
        observed_at=now,
    )
    receipt = UploadPreparationReceiptEvidence(
        receipt_id=receipt_id,
        workspace_id=workspace_id,
        preparation_id=preparation_id,
        upload_id=upload_id,
        manifest_version=7,
        source_sha256="a" * 64,
        accepted_sha256="a" * 64,
        content_profile=UploadContentProfile.DATASET_DESCRIPTION_CSV_V1.value,
        parser_version=DATASET_DESCRIPTION_CSV_V1.parser_version,
        scanner_version="scanner-v1",
        schema_version=DATASET_DESCRIPTION_CSV_V1.schema_version,
        configuration_hash=DATASET_DESCRIPTION_CSV_V1.configuration_hash,
        item_count=1,
        rejected_count=0,
        candidate_root_hash="b" * 64,
        receipt_hash="c" * 64,
        observed_at=now,
        created_at=now,
        candidate_count=1,
        first_ordinal=1,
        last_ordinal=1,
        legacy_candidate_count=0,
        object_locator_hash=object_locator_hash,
        accepted_etag="provider-etag",
        accepted_version_id="provider-version",
    )
    page = UploadRegistrationCandidatePage(
        items=(UploadRegistrationCandidateView(evidence=candidate, current_target=target),),
        next_cursor=None,
        receipt=receipt,
        projection_version=11,
        policy_version="builtin-abac-v2",
        classification_policy_version=3,
        authorization_generation=9,
    )
    document: dict[str, object] = {"custom": {"preserved": True}}
    if current_description is not None:
        document["description"] = current_description
    snapshot = DataHubAspectSnapshot(
        urn=external_urn,
        aspect_name="datasetProperties",
        content_hash=canonical_json_hash(document),
        source_version="provider-12",
        observed_at=now,
        document=MappingProxyType(document),
    )
    query = FakeCandidateQuery(page)
    datahub = FakeDataHub(snapshot)
    governance = FakeGovernance()
    service = TypedBulkRegistrationService(
        candidates=cast(RegistrationCandidateQueryService, query),
        datahub=cast(DataHubGateway, datahub),
        governance=cast(TypedBulkGovernanceCreator, governance),
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
        query,
        datahub,
        governance,
        subject,
        EnvironmentAttributes(requested_at=now),
        upload_id,
        preparation_id,
        candidate_id,
        asset_id,
    )


@pytest.mark.asyncio
async def test_preview_binds_all_evidence_and_preserves_unknown_provider_fields() -> None:
    (
        service,
        query,
        datahub,
        governance,
        subject,
        environment,
        upload_id,
        preparation_id,
        candidate_id,
        asset_id,
    ) = _fixture()

    preview = await service.preview(
        workspace_id=subject.workspace_id,
        upload_id=upload_id,
        preparation_id=preparation_id,
        candidate_id=candidate_id,
        subject=subject,
        environment=environment,
        request_id="typed-bulk-preview",
    )

    assert query.calls == 1
    assert datahub.reads == [(preview.target_ref, "datasetProperties")]
    assert governance.calls == []
    assert preview.candidate_id == candidate_id
    assert preview.target_asset_id == asset_id
    assert preview.current_description == "old description"
    assert preview.proposed_document == {
        "custom": {"preserved": True},
        "description": "new description",
    }
    assert preview.preview_etag.startswith('"') and len(preview.preview_etag) == 66
    assert preview.binding == RegistrationCandidateBindingCommand(
        workspace_id=subject.workspace_id,
        upload_id=upload_id,
        preparation_id=preparation_id,
        receipt_id=preview.binding.receipt_id,
        receipt_hash="c" * 64,
        candidate_id=candidate_id,
        candidate_hash=preview.binding.candidate_hash,
        target_asset_id=asset_id,
        target_source_version="projection-7",
        target_binding_hash=preview.binding.target_binding_hash,
    )


@pytest.mark.asyncio
async def test_create_rejects_stale_preview_before_any_database_mutation() -> None:
    service, _, _, governance, subject, environment, upload_id, preparation_id, candidate_id, _ = (
        _fixture()
    )

    with pytest.raises(ConflictError, match="preview is stale"):
        await service.create_change_request(
            workspace_id=subject.workspace_id,
            upload_id=upload_id,
            preparation_id=preparation_id,
            candidate_id=candidate_id,
            expected_preview_etag=f'"{"0" * 64}"',
            title="Governed bulk update",
            reason="Approved source file",
            subject=subject,
            environment=environment,
            request_id="typed-bulk-create-stale",
            idempotency_key="typed-bulk-stale-key",
            request_hash="e" * 64,
        )

    assert governance.calls == []


@pytest.mark.asyncio
async def test_create_passes_only_one_server_authored_item_and_binding() -> None:
    service, _, _, governance, subject, environment, upload_id, preparation_id, candidate_id, _ = (
        _fixture()
    )
    preview = await service.preview(
        workspace_id=subject.workspace_id,
        upload_id=upload_id,
        preparation_id=preparation_id,
        candidate_id=candidate_id,
        subject=subject,
        environment=environment,
        request_id="typed-bulk-preview",
    )

    result = await service.create_change_request(
        workspace_id=subject.workspace_id,
        upload_id=upload_id,
        preparation_id=preparation_id,
        candidate_id=candidate_id,
        expected_preview_etag=preview.preview_etag,
        title="Governed bulk update",
        reason="Approved source file",
        subject=subject,
        environment=environment,
        request_id="typed-bulk-create",
        idempotency_key="typed-bulk-create-key",
        request_hash="f" * 64,
    )

    assert result is governance.result
    assert len(governance.calls) == 1
    call = governance.calls[0]
    assert call["require_raw_operator_gate"] is False
    assert call["registration_candidate_binding"] == preview.binding
    items = cast(list[object], call["items"])
    assert len(items) == 1
    item = cast(Any, items[0])
    assert item.target_ref == preview.target_ref
    assert item.aspect_name == "datasetProperties"
    assert item.after_document == preview.proposed_document
    assert item.before_hash == preview.before_hash
    assert item.after_hash == preview.after_hash


@pytest.mark.asyncio
async def test_idempotent_create_recovery_precedes_candidate_and_provider_reads() -> None:
    (
        service,
        candidates,
        datahub,
        governance,
        subject,
        environment,
        upload_id,
        preparation_id,
        candidate_id,
        _,
    ) = _fixture()
    existing = cast(ChangeRequest, object())
    governance.existing = existing

    result = await service.create_change_request(
        workspace_id=subject.workspace_id,
        upload_id=upload_id,
        preparation_id=preparation_id,
        candidate_id=candidate_id,
        expected_preview_etag=f'"{"0" * 64}"',
        title="Governed bulk update",
        reason="Approved source file",
        subject=subject,
        environment=environment,
        request_id="typed-bulk-recovery",
        idempotency_key="typed-bulk-recovery-key",
        request_hash="a" * 64,
    )

    assert result is existing
    assert candidates.calls == 0
    assert datahub.reads == []
    assert governance.calls == []


@pytest.mark.asyncio
async def test_unchanged_description_fails_without_governance_mutation() -> None:
    service, _, _, governance, subject, environment, upload_id, preparation_id, candidate_id, _ = (
        _fixture(current_description="same", proposed_description="same")
    )

    with pytest.raises(ValidationError, match="does not change"):
        await service.preview(
            workspace_id=subject.workspace_id,
            upload_id=upload_id,
            preparation_id=preparation_id,
            candidate_id=candidate_id,
            subject=subject,
            environment=environment,
            request_id="typed-bulk-unchanged",
        )

    assert governance.calls == []


@pytest.mark.asyncio
async def test_malformed_object_locator_hash_fails_before_provider_read() -> None:
    (
        service,
        _,
        datahub,
        governance,
        subject,
        environment,
        upload_id,
        preparation_id,
        candidate_id,
        _,
    ) = _fixture(object_locator_hash="NOT-A-SHA256")

    with pytest.raises(
        UploadPreparationEvidenceUnavailable,
        match="object identity evidence is unavailable",
    ):
        await service.preview(
            workspace_id=subject.workspace_id,
            upload_id=upload_id,
            preparation_id=preparation_id,
            candidate_id=candidate_id,
            subject=subject,
            environment=environment,
            request_id="typed-bulk-malformed-locator",
        )

    assert datahub.reads == []
    assert governance.calls == []
