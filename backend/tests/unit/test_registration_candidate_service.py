from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest

from datariver.application.classification_access import (
    ClassificationAccessResolver,
    static_classification_access_floor,
)
from datariver.application.dto import (
    CatalogAssetIndex,
    UploadPreparationReceiptEvidence,
    UploadRegistrationCandidateEvidence,
)
from datariver.application.ports import (
    CatalogCandidateTargetReader,
    CatalogWatermarkReader,
    UploadCandidateReader,
    UploadPreparationRepository,
    UploadRepository,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.registration_candidates import (
    RegistrationCandidateQueryService,
    UploadCandidatePageUnavailable,
    UploadPreparationEvidenceUnavailable,
    UploadPreparationNotReady,
)
from datariver.application.typed_upload_parser import (
    DATASET_DESCRIPTION_CANDIDATE_EVIDENCE_VERSION,
    DATASET_DESCRIPTION_CANDIDATE_KIND,
    dataset_description_candidate_hash,
    dataset_description_submitted_identity_hash,
)
from datariver.application.typed_upload_profiles import DATASET_DESCRIPTION_CSV_V1
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ValidationError, utc_now
from datariver.domain.registration import (
    UploadContentProfile,
    UploadManifest,
    UploadPreparation,
    UploadPreparationState,
    UploadState,
)


class FakeUploads:
    def __init__(self, manifest: UploadManifest) -> None:
        self.manifest = manifest

    async def get(self, *, workspace_id: UUID, upload_id: UUID) -> UploadManifest | None:
        if workspace_id == self.manifest.workspace_id and upload_id == self.manifest.upload_id:
            return self.manifest
        return None


class FakePreparations:
    def __init__(self, preparation: UploadPreparation) -> None:
        self.preparation = preparation

    async def get(
        self,
        *,
        workspace_id: UUID,
        upload_id: UUID,
        preparation_id: UUID,
    ) -> UploadPreparation | None:
        value = self.preparation
        if (
            workspace_id == value.workspace_id
            and upload_id == value.upload_id
            and preparation_id == value.preparation_id
        ):
            return value
        return None


class FakeCandidates:
    def __init__(
        self,
        receipt: UploadPreparationReceiptEvidence,
        candidates: tuple[UploadRegistrationCandidateEvidence, ...],
    ) -> None:
        self.receipt = receipt
        self.candidates = candidates
        self.receipt_reads = 0
        self.page_reads = 0

    async def get_ready_receipt(self, **_: object) -> UploadPreparationReceiptEvidence | None:
        self.receipt_reads += 1
        return self.receipt

    async def list_candidates(
        self, *, after_ordinal: int, limit: int, **_: object
    ) -> tuple[UploadRegistrationCandidateEvidence, ...]:
        self.page_reads += 1
        return tuple(value for value in self.candidates if value.ordinal > after_ordinal)[:limit]


class FakeCatalog:
    def __init__(self, targets: tuple[CatalogAssetIndex, ...]) -> None:
        self.targets = targets
        self.projection_version = 11
        self.batch_calls = 0

    async def get_search_watermark(self, **_: object) -> int:
        return self.projection_version

    async def get_authorized_assets_by_ids(
        self, *, asset_ids: tuple[UUID, ...], **_: object
    ) -> tuple[CatalogAssetIndex, ...]:
        self.batch_calls += 1
        requested = set(asset_ids)
        return tuple(target for target in self.targets if target.asset_id in requested)


class FakeClassificationAccess:
    async def resolve(self, **_: object) -> object:
        return static_classification_access_floor()


class FakeAuthorization:
    def __init__(self) -> None:
        self.actions: list[Action] = []
        self.denied_action: Action | None = None

    async def authorize(self, *, action: Action, **_: object) -> None:
        self.actions.append(action)

    async def filter_authorized(
        self,
        *,
        action: Action,
        resources: tuple[ResourceAttributes, ...],
        **_: object,
    ) -> tuple[ResourceAttributes, ...]:
        self.actions.append(action)
        return () if action is self.denied_action else resources


def _fixture() -> tuple[
    RegistrationCandidateQueryService,
    UploadManifest,
    UploadPreparation,
    UploadPreparationReceiptEvidence,
    tuple[UploadRegistrationCandidateEvidence, ...],
    FakeCandidates,
    FakeCatalog,
    FakeAuthorization,
    SubjectAttributes,
    EnvironmentAttributes,
]:
    now = utc_now()
    workspace_id = uuid4()
    upload_id = uuid4()
    owner_id = uuid4()
    preparation_id = uuid4()
    receipt_id = uuid4()
    manifest = UploadManifest(
        upload_id=upload_id,
        workspace_id=workspace_id,
        owner_id=owner_id,
        bucket="accepted",
        object_key=f"accepted/{workspace_id}/{upload_id}",
        display_name="dataset-descriptions.csv",
        declared_size_bytes=1024,
        declared_mime="text/csv",
        declared_sha256="a" * 64,
        classification=Classification.INTERNAL,
        multipart_upload_id="complete",
        expires_at=now + timedelta(hours=1),
        content_profile=UploadContentProfile.DATASET_DESCRIPTION_CSV_V1,
        state=UploadState.ACCEPTED,
        version=7,
        actual_size_bytes=1024,
        actual_mime="text/csv",
        actual_sha256="a" * 64,
    )
    preparation = UploadPreparation(
        preparation_id=preparation_id,
        workspace_id=workspace_id,
        upload_id=upload_id,
        requested_by=owner_id,
        content_profile=UploadContentProfile.DATASET_DESCRIPTION_CSV_V1,
        source_manifest_version=7,
        source_sha256="a" * 64,
        configuration_hash=DATASET_DESCRIPTION_CSV_V1.configuration_hash,
        state=UploadPreparationState.READY,
        attempts=1,
        rows_processed=2,
        total_rows=2,
        last_error_code=None,
        created_at=now,
        updated_at=now,
        version=3,
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
        item_count=2,
        rejected_count=0,
        candidate_root_hash="b" * 64,
        receipt_hash="c" * 64,
        observed_at=now,
        created_at=now,
        candidate_count=2,
        first_ordinal=1,
        last_ordinal=2,
        legacy_candidate_count=0,
    )
    identities = (
        ("oracle", "fab", "mes", "wafer_events"),
        ("oracle", "fab", "mes", "lot_events"),
    )
    candidate_values: list[UploadRegistrationCandidateEvidence] = []
    targets: list[CatalogAssetIndex] = []
    for ordinal, identity in enumerate(identities, start=1):
        platform, database_name, schema_name, table_name = identity
        asset_id = uuid4()
        identity_hash = dataset_description_submitted_identity_hash(
            workspace_id=workspace_id,
            target_asset_id=asset_id,
            platform=platform,
            database_name=database_name,
            schema_name=schema_name,
            table_name=table_name,
        )
        description = f"description-{ordinal}"
        candidate_values.append(
            UploadRegistrationCandidateEvidence(
                candidate_id=uuid4(),
                workspace_id=workspace_id,
                receipt_id=receipt_id,
                ordinal=ordinal,
                target_asset_id=asset_id,
                candidate_kind=DATASET_DESCRIPTION_CANDIDATE_KIND,
                proposed_description=description,
                evidence_version=DATASET_DESCRIPTION_CANDIDATE_EVIDENCE_VERSION,
                submitted_platform=platform,
                submitted_database_name=database_name,
                submitted_schema_name=schema_name,
                submitted_table_name=table_name,
                submitted_identity_hash=identity_hash,
                candidate_hash=dataset_description_candidate_hash(
                    workspace_id=workspace_id,
                    target_asset_id=asset_id,
                    proposed_description=description,
                    submitted_identity_hash=identity_hash,
                ),
                created_at=now,
            )
        )
        targets.append(
            CatalogAssetIndex(
                asset_id=asset_id,
                workspace_id=workspace_id,
                external_urn=f"urn:li:dataset:{asset_id}",
                asset_type="DATASET",
                name=table_name,
                description=None,
                platform=platform,
                database_name=database_name,
                schema_name=schema_name,
                domain_id=None,
                system_id=None,
                owner_department_id=None,
                classification=Classification.PUBLIC,
                lifecycle="ACTIVE",
                source_version=f"projection-{ordinal}",
                observed_at=now,
            )
        )
    candidates = tuple(candidate_values)
    candidate_reader = FakeCandidates(receipt, candidates)
    catalog = FakeCatalog(tuple(targets))
    authorization = FakeAuthorization()
    service = RegistrationCandidateQueryService(
        uploads=cast(UploadRepository, FakeUploads(manifest)),
        preparations=cast(UploadPreparationRepository, FakePreparations(preparation)),
        candidates=cast(UploadCandidateReader, candidate_reader),
        catalog=cast(CatalogCandidateTargetReader, catalog),
        watermark=cast(CatalogWatermarkReader, catalog),
        classification_access=cast(ClassificationAccessResolver, FakeClassificationAccess()),
        authorization=cast(AuthorizationService, authorization),
        policy_version="builtin-abac-v2",
    )
    subject = SubjectAttributes(
        subject_id=owner_id,
        workspace_id=workspace_id,
        active=True,
        department_id=uuid4(),
        groups=frozenset({"data-stewards"}),
        job_function="DATA_STEWARD",
        clearance=Classification.RESTRICTED,
        allowed_actions=frozenset(
            {Action.REGISTRATION_READ, Action.CATALOG_READ, Action.CHANGE_CREATE}
        ),
    )
    return (
        service,
        manifest,
        preparation,
        receipt,
        candidates,
        candidate_reader,
        catalog,
        authorization,
        subject,
        EnvironmentAttributes(requested_at=now),
    )


@pytest.mark.asyncio
async def test_candidate_page_reauthorizes_in_sets_and_uses_bound_cursor() -> None:
    service, manifest, preparation, _, _, reader, catalog, authorization, subject, environment = (
        _fixture()
    )
    first = await service.list_candidates(
        workspace_id=manifest.workspace_id,
        upload_id=manifest.upload_id,
        preparation_id=preparation.preparation_id,
        subject=subject,
        environment=environment,
        request_id="candidate-first",
        cursor=None,
        limit=1,
    )

    assert len(first.items) == 1
    assert first.next_cursor is not None
    assert first.items[0].evidence.submitted_table_name == "wafer_events"
    assert first.items[0].current_target.name == "wafer_events"
    assert authorization.actions == [
        Action.REGISTRATION_READ,
        Action.CATALOG_READ,
        Action.CHANGE_CREATE,
    ]
    assert reader.page_reads == 1
    assert catalog.batch_calls == 1

    second = await service.list_candidates(
        workspace_id=manifest.workspace_id,
        upload_id=manifest.upload_id,
        preparation_id=preparation.preparation_id,
        subject=subject,
        environment=environment,
        request_id="candidate-second",
        cursor=first.next_cursor,
        limit=1,
    )
    assert [item.evidence.ordinal for item in second.items] == [2]
    assert second.next_cursor is None


@pytest.mark.asyncio
async def test_candidate_cursor_rejects_projection_or_request_snapshot_change() -> None:
    service, manifest, preparation, _, _, _, catalog, _, subject, environment = _fixture()
    first = await service.list_candidates(
        workspace_id=manifest.workspace_id,
        upload_id=manifest.upload_id,
        preparation_id=preparation.preparation_id,
        subject=subject,
        environment=environment,
        request_id="candidate-first",
        cursor=None,
        limit=1,
    )
    catalog.projection_version += 1
    with pytest.raises(ValidationError, match="stale or does not match"):
        await service.list_candidates(
            workspace_id=manifest.workspace_id,
            upload_id=manifest.upload_id,
            preparation_id=preparation.preparation_id,
            subject=subject,
            environment=environment,
            request_id="candidate-stale",
            cursor=first.next_cursor,
            limit=1,
        )


@pytest.mark.asyncio
async def test_candidate_cursor_rejects_non_json_bytes_without_internal_error() -> None:
    service, manifest, preparation, _, _, _, _, _, subject, environment = _fixture()

    with pytest.raises(ValidationError, match="stale or does not match"):
        await service.list_candidates(
            workspace_id=manifest.workspace_id,
            upload_id=manifest.upload_id,
            preparation_id=preparation.preparation_id,
            subject=subject,
            environment=environment,
            request_id="candidate-malformed-cursor",
            cursor="____",
            limit=1,
        )


@pytest.mark.asyncio
async def test_non_ready_or_legacy_receipt_fails_before_candidate_disclosure() -> None:
    service, manifest, preparation, receipt, _, reader, _, _, subject, environment = _fixture()
    preparation.state = UploadPreparationState.PREPARING
    with pytest.raises(UploadPreparationNotReady):
        await service.list_candidates(
            workspace_id=manifest.workspace_id,
            upload_id=manifest.upload_id,
            preparation_id=preparation.preparation_id,
            subject=subject,
            environment=environment,
            request_id="candidate-not-ready",
            cursor=None,
            limit=20,
        )
    assert reader.receipt_reads == 0

    preparation.state = UploadPreparationState.READY
    reader.receipt = replace(receipt, legacy_candidate_count=1)
    with pytest.raises(UploadPreparationEvidenceUnavailable):
        await service.list_candidates(
            workspace_id=manifest.workspace_id,
            upload_id=manifest.upload_id,
            preparation_id=preparation.preparation_id,
            subject=subject,
            environment=environment,
            request_id="candidate-legacy",
            cursor=None,
            limit=20,
        )
    assert reader.page_reads == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["hash", "missing", "drift", "deny"])
async def test_candidate_evidence_or_current_scope_failure_returns_no_partial_page(
    failure: str,
) -> None:
    fixture = _fixture()
    service, manifest, preparation, _, candidates = fixture[:5]
    reader, catalog, authorization, subject, environment = fixture[5:]
    expected: type[Exception]
    if failure == "hash":
        reader.candidates = (replace(candidates[0], candidate_hash="f" * 64), candidates[1])
        expected = UploadPreparationEvidenceUnavailable
    elif failure == "missing":
        catalog.targets = catalog.targets[:1]
        expected = UploadCandidatePageUnavailable
    elif failure == "drift":
        catalog.targets = (replace(catalog.targets[0], name="renamed"), catalog.targets[1])
        expected = UploadCandidatePageUnavailable
    else:
        authorization.denied_action = Action.CHANGE_CREATE
        expected = UploadCandidatePageUnavailable

    with pytest.raises(expected):
        await service.list_candidates(
            workspace_id=manifest.workspace_id,
            upload_id=manifest.upload_id,
            preparation_id=preparation.preparation_id,
            subject=subject,
            environment=environment,
            request_id=f"candidate-{failure}",
            cursor=None,
            limit=20,
        )
