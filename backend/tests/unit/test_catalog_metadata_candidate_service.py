from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest

from datariver.application.catalog_metadata_upload_parser import (
    CatalogMetadataCandidateDraft,
    CatalogMetadataOperation,
    CatalogMetadataRecordKind,
    CatalogMetadataRowEvidence,
    catalog_metadata_candidate_root,
    catalog_metadata_row_root,
    catalog_metadata_semantic_target_hash,
    compile_catalog_metadata_candidates,
)
from datariver.application.classification_access import (
    ClassificationAccessResolver,
    ClassificationAccessSnapshot,
    static_classification_access_floor,
)
from datariver.application.dto import (
    CatalogAssetIndex,
    CatalogMetadataCandidateEvidence,
    CatalogMetadataRowEvidenceRecord,
    UploadPreparationReceiptEvidence,
)
from datariver.application.ports import (
    CatalogCandidateTargetReader,
    CatalogMetadataCandidateReader,
    CatalogWatermarkReader,
    UploadPreparationRepository,
    UploadRepository,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.catalog_metadata_candidates import (
    CatalogMetadataCandidateQueryService,
)
from datariver.application.services.registration_candidates import (
    UploadCandidatePageUnavailable,
    UploadPreparationEvidenceUnavailable,
)
from datariver.application.typed_upload_profiles import CATALOG_METADATA_ROWS_CSV_V1
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
        candidates: tuple[CatalogMetadataCandidateEvidence, ...],
    ) -> None:
        self.receipt = receipt
        self.candidates = candidates
        self.page_reads = 0
        self.receipt_reads = 0

    async def get_ready_receipt(self, **_: object) -> UploadPreparationReceiptEvidence | None:
        self.receipt_reads += 1
        return self.receipt

    async def list_candidates(
        self,
        *,
        after_ordinal: int,
        limit: int,
        **_: object,
    ) -> tuple[CatalogMetadataCandidateEvidence, ...]:
        self.page_reads += 1
        return tuple(
            candidate for candidate in self.candidates if candidate.ordinal > after_ordinal
        )[:limit]

    async def get_candidate(
        self,
        *,
        candidate_id: UUID,
        **_: object,
    ) -> CatalogMetadataCandidateEvidence | None:
        return next(
            (candidate for candidate in self.candidates if candidate.candidate_id == candidate_id),
            None,
        )


class FakeCatalog:
    def __init__(self, targets: tuple[CatalogAssetIndex, ...]) -> None:
        self.targets = targets
        self.projection_version = 41
        self.batch_calls = 0

    async def get_authorized_assets_by_ids(
        self,
        *,
        asset_ids: tuple[UUID, ...],
        **_: object,
    ) -> tuple[CatalogAssetIndex, ...]:
        self.batch_calls += 1
        requested = set(asset_ids)
        return tuple(target for target in self.targets if target.asset_id in requested)

    async def get_search_watermark(self, **_: object) -> int:
        return self.projection_version


class FakeClassificationAccess:
    async def resolve(self, **_: object) -> ClassificationAccessSnapshot:
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


@dataclass(slots=True)
class Fixture:
    service: CatalogMetadataCandidateQueryService
    manifest: UploadManifest
    preparation: UploadPreparation
    receipt: UploadPreparationReceiptEvidence
    candidates: tuple[CatalogMetadataCandidateEvidence, ...]
    reader: FakeCandidates
    catalog: FakeCatalog
    authorization: FakeAuthorization
    subject: SubjectAttributes
    environment: EnvironmentAttributes


def _rows(asset_id: UUID) -> list[tuple[int, list[str]]]:
    identity = [str(asset_id), "postgres", "fab", "public", "wafer"]
    return [
        (
            1,
            [
                "COLUMN_DESCRIPTION",
                *identity,
                "lot_id",
                "SET",
                "lot description",
                "",
            ],
        ),
        (
            2,
            [
                "COLUMN_DESCRIPTION",
                *identity,
                "obsolete",
                "CLEAR",
                "",
                "",
            ],
        ),
        (
            3,
            [
                "DATASET_TAG",
                *identity,
                "",
                "ADD",
                "",
                "00000000-0000-4000-8000-000000000201",
            ],
        ),
    ]


def _controlled_kind(
    record_kind: CatalogMetadataRecordKind, operation: CatalogMetadataOperation
) -> str | None:
    if record_kind is CatalogMetadataRecordKind.DATASET_DOMAIN:
        return "DOMAIN" if operation is CatalogMetadataOperation.SET else None
    if record_kind is CatalogMetadataRecordKind.DATASET_TERM:
        return "TERM"
    if record_kind is CatalogMetadataRecordKind.DATASET_TAG:
        return "TAG"
    return None


def _semantic_key(row: CatalogMetadataRowEvidence) -> str:
    if row.record_kind in {
        CatalogMetadataRecordKind.TABLE_DESCRIPTION,
        CatalogMetadataRecordKind.DATASET_DOMAIN,
    }:
        return row.record_kind.value
    if row.record_kind is CatalogMetadataRecordKind.COLUMN_DESCRIPTION:
        return f"{row.record_kind.value}:{row.field_path}"
    return f"{row.record_kind.value}:{row.controlled_ref}"


def _evidence(
    drafts: tuple[CatalogMetadataCandidateDraft, ...],
    *,
    receipt_id: UUID,
) -> tuple[CatalogMetadataCandidateEvidence, ...]:
    values: list[CatalogMetadataCandidateEvidence] = []
    for draft in drafts:
        rows = tuple(
            CatalogMetadataRowEvidenceRecord(
                row_id=uuid4(),
                ordinal=row.ordinal,
                record_kind=row.record_kind.value,
                aspect_name=row.aspect_name.value,
                operation=row.operation.value,
                field_path=row.field_path,
                value_text=row.value_text,
                controlled_ref_id=row.controlled_ref,
                controlled_kind=_controlled_kind(row.record_kind, row.operation),
                semantic_target_hash=catalog_metadata_semantic_target_hash(
                    workspace_id=row.workspace_id,
                    target_asset_id=row.target_asset_id,
                    aspect_name=row.aspect_name,
                    semantic_key=_semantic_key(row),
                ),
                row_hash=row.row_hash,
            )
            for row in draft.rows
        )
        values.append(
            CatalogMetadataCandidateEvidence(
                candidate_id=uuid4(),
                workspace_id=draft.workspace_id,
                receipt_id=receipt_id,
                ordinal=draft.ordinal,
                content_profile=CATALOG_METADATA_ROWS_CSV_V1.content_profile.value,
                evidence_version=draft.evidence_version,
                record_kind=draft.record_kind.value,
                candidate_kind=draft.candidate_kind.value,
                target_asset_id=draft.target_asset_id,
                aspect_name=draft.aspect_name.value,
                submitted_platform=draft.platform,
                submitted_database_name=draft.database_name,
                submitted_schema_name=draft.schema_name,
                submitted_table_name=draft.table_name,
                submitted_identity_hash=draft.submitted_identity_hash,
                row_root_hash=catalog_metadata_row_root(tuple(row.row_hash for row in draft.rows)),
                candidate_hash=draft.candidate_hash,
                rows=rows,
                created_at=utc_now(),
            )
        )
    return tuple(values)


def _fixture() -> Fixture:
    now = utc_now()
    workspace_id = uuid4()
    upload_id = uuid4()
    owner_id = uuid4()
    preparation_id = uuid4()
    receipt_id = uuid4()
    asset_id = uuid4()
    drafts = compile_catalog_metadata_candidates(
        workspace_id=workspace_id,
        rows=_rows(asset_id),
        definition=CATALOG_METADATA_ROWS_CSV_V1,
    )
    candidates = _evidence(drafts, receipt_id=receipt_id)
    manifest = UploadManifest(
        upload_id=upload_id,
        workspace_id=workspace_id,
        owner_id=owner_id,
        bucket="accepted",
        object_key=f"accepted/{workspace_id}/{upload_id}",
        display_name="catalog-metadata.csv",
        declared_size_bytes=1_024,
        declared_mime=CATALOG_METADATA_ROWS_CSV_V1.content_type,
        declared_sha256="a" * 64,
        classification=Classification.INTERNAL,
        multipart_upload_id="complete",
        expires_at=now + timedelta(hours=1),
        content_profile=UploadContentProfile.CATALOG_METADATA_ROWS_CSV_V1,
        state=UploadState.ACCEPTED,
        version=7,
        actual_size_bytes=1_024,
        actual_mime=CATALOG_METADATA_ROWS_CSV_V1.content_type,
        actual_sha256="a" * 64,
    )
    preparation = UploadPreparation(
        preparation_id=preparation_id,
        workspace_id=workspace_id,
        upload_id=upload_id,
        requested_by=owner_id,
        content_profile=UploadContentProfile.CATALOG_METADATA_ROWS_CSV_V1,
        source_manifest_version=7,
        source_sha256="a" * 64,
        configuration_hash=CATALOG_METADATA_ROWS_CSV_V1.configuration_hash,
        state=UploadPreparationState.READY,
        attempts=1,
        rows_processed=3,
        total_rows=3,
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
        content_profile=CATALOG_METADATA_ROWS_CSV_V1.content_profile.value,
        parser_version=CATALOG_METADATA_ROWS_CSV_V1.parser_version,
        scanner_version="scanner-v3",
        schema_version=CATALOG_METADATA_ROWS_CSV_V1.schema_version,
        configuration_hash=CATALOG_METADATA_ROWS_CSV_V1.configuration_hash,
        item_count=3,
        rejected_count=0,
        candidate_root_hash=catalog_metadata_candidate_root(
            workspace_id=workspace_id,
            candidates=drafts,
            definition=CATALOG_METADATA_ROWS_CSV_V1,
        ).hex(),
        receipt_hash="c" * 64,
        observed_at=now,
        created_at=now,
        candidate_count=2,
        first_ordinal=1,
        last_ordinal=2,
        legacy_candidate_count=0,
    )
    target = CatalogAssetIndex(
        asset_id=asset_id,
        workspace_id=workspace_id,
        external_urn=f"urn:li:dataset:{asset_id}",
        asset_type="DATASET",
        name="wafer",
        description="provider description",
        platform="postgres",
        database_name="fab",
        schema_name="public",
        owner="urn:li:corpuser:owner",
        domain="urn:li:domain:fabrication",
        tags=("urn:li:tag:critical",),
        glossary_terms=("urn:li:glossaryTerm:wafer",),
        column_names=("lot_id", "obsolete"),
        domain_id=None,
        system_id=None,
        owner_department_id=None,
        classification=Classification.INTERNAL,
        lifecycle="ACTIVE",
        source_version="projection-41",
        observed_at=now,
    )
    reader = FakeCandidates(receipt, candidates)
    catalog = FakeCatalog((target,))
    authorization = FakeAuthorization()
    service = CatalogMetadataCandidateQueryService(
        uploads=cast(UploadRepository, FakeUploads(manifest)),
        preparations=cast(UploadPreparationRepository, FakePreparations(preparation)),
        candidates=cast(CatalogMetadataCandidateReader, reader),
        catalog=cast(CatalogCandidateTargetReader, catalog),
        watermark=cast(CatalogWatermarkReader, catalog),
        classification_access=cast(
            ClassificationAccessResolver,
            FakeClassificationAccess(),
        ),
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
            {
                Action.REGISTRATION_READ,
                Action.CATALOG_READ,
                Action.CHANGE_CREATE,
            }
        ),
    )
    return Fixture(
        service=service,
        manifest=manifest,
        preparation=preparation,
        receipt=receipt,
        candidates=candidates,
        reader=reader,
        catalog=catalog,
        authorization=authorization,
        subject=subject,
        environment=EnvironmentAttributes(requested_at=now),
    )


@pytest.mark.asyncio
async def test_list_uses_group_count_keyset_and_returns_no_provider_identifiers() -> None:
    fixture = _fixture()

    first = await fixture.service.list_candidates(
        workspace_id=fixture.manifest.workspace_id,
        upload_id=fixture.manifest.upload_id,
        preparation_id=fixture.preparation.preparation_id,
        subject=fixture.subject,
        environment=fixture.environment,
        request_id="v3-first",
        cursor=None,
        limit=1,
    )

    assert first.receipt.item_count == 3
    assert first.receipt.candidate_count == 2
    assert len(first.items) == 1
    assert first.next_cursor is not None
    assert first.items[0].evidence.ordinal == 1
    assert [row.ordinal for row in first.items[0].evidence.rows] == [1, 2]
    public_target = first.items[0].current_target
    assert public_target.external_urn == ""
    assert public_target.owner is None
    assert public_target.domain is None
    assert public_target.tags == ()
    assert public_target.glossary_terms == ()
    assert public_target.column_names == ("lot_id", "obsolete")
    assert fixture.authorization.actions == [
        Action.REGISTRATION_READ,
        Action.CATALOG_READ,
        Action.CHANGE_CREATE,
    ]

    second = await fixture.service.list_candidates(
        workspace_id=fixture.manifest.workspace_id,
        upload_id=fixture.manifest.upload_id,
        preparation_id=fixture.preparation.preparation_id,
        subject=fixture.subject,
        environment=fixture.environment,
        request_id="v3-second",
        cursor=first.next_cursor,
        limit=1,
    )
    assert [item.evidence.ordinal for item in second.items] == [2]
    assert second.next_cursor is None


@pytest.mark.asyncio
async def test_get_candidate_reauthorizes_and_revalidates_exact_rows() -> None:
    fixture = _fixture()

    page = await fixture.service.get_candidate(
        workspace_id=fixture.manifest.workspace_id,
        upload_id=fixture.manifest.upload_id,
        preparation_id=fixture.preparation.preparation_id,
        candidate_id=fixture.candidates[1].candidate_id,
        subject=fixture.subject,
        environment=fixture.environment,
        request_id="v3-get",
    )

    assert len(page.items) == 1
    assert page.items[0].evidence == fixture.candidates[1]
    assert page.next_cursor is None


@pytest.mark.asyncio
async def test_cursor_binds_projection_root_and_permission_snapshot() -> None:
    fixture = _fixture()
    first = await fixture.service.list_candidates(
        workspace_id=fixture.manifest.workspace_id,
        upload_id=fixture.manifest.upload_id,
        preparation_id=fixture.preparation.preparation_id,
        subject=fixture.subject,
        environment=fixture.environment,
        request_id="v3-first",
        cursor=None,
        limit=1,
    )
    fixture.catalog.projection_version += 1

    with pytest.raises(ValidationError, match="stale or does not match"):
        await fixture.service.list_candidates(
            workspace_id=fixture.manifest.workspace_id,
            upload_id=fixture.manifest.upload_id,
            preparation_id=fixture.preparation.preparation_id,
            subject=fixture.subject,
            environment=fixture.environment,
            request_id="v3-stale",
            cursor=first.next_cursor,
            limit=1,
        )

    fixture.catalog.projection_version -= 1
    fixture.reader.receipt = replace(fixture.receipt, candidate_root_hash="d" * 64)
    with pytest.raises(ValidationError, match="stale or does not match"):
        await fixture.service.list_candidates(
            workspace_id=fixture.manifest.workspace_id,
            upload_id=fixture.manifest.upload_id,
            preparation_id=fixture.preparation.preparation_id,
            subject=fixture.subject,
            environment=fixture.environment,
            request_id="v3-root-change",
            cursor=first.next_cursor,
            limit=1,
        )

    fixture.reader.receipt = fixture.receipt
    changed_scope = replace(
        fixture.subject,
        allowed_system_ids=frozenset({uuid4()}),
    )
    with pytest.raises(ValidationError, match="stale or does not match"):
        await fixture.service.list_candidates(
            workspace_id=fixture.manifest.workspace_id,
            upload_id=fixture.manifest.upload_id,
            preparation_id=fixture.preparation.preparation_id,
            subject=changed_scope,
            environment=fixture.environment,
            request_id="v3-permission-change",
            cursor=first.next_cursor,
            limit=1,
        )


@pytest.mark.asyncio
async def test_tampered_row_group_or_identity_evidence_returns_no_partial_page() -> None:
    fixture = _fixture()
    column, tag = fixture.candidates
    tampered_values = (
        replace(column, submitted_identity_hash="0" * 64),
        replace(column, row_root_hash="0" * 64),
        replace(column, candidate_hash="0" * 64),
        replace(column, aspect_name="globalTags"),
        replace(
            column,
            rows=(replace(column.rows[0], row_hash="0" * 64), *column.rows[1:]),
        ),
        replace(
            column,
            rows=(
                replace(column.rows[0], semantic_target_hash="0" * 64),
                *column.rows[1:],
            ),
        ),
        replace(column, rows=tuple(reversed(column.rows))),
        replace(
            column,
            rows=(
                replace(
                    column.rows[0],
                    operation=CatalogMetadataOperation.CLEAR.value,
                ),
                *column.rows[1:],
            ),
        ),
        replace(
            tag,
            rows=(replace(tag.rows[0], controlled_kind="DOMAIN"),),
        ),
    )

    for tampered in tampered_values:
        fixture.reader.candidates = (tampered, tag) if tampered.ordinal == 1 else (column, tampered)
        with pytest.raises(UploadPreparationEvidenceUnavailable):
            await fixture.service.list_candidates(
                workspace_id=fixture.manifest.workspace_id,
                upload_id=fixture.manifest.upload_id,
                preparation_id=fixture.preparation.preparation_id,
                subject=fixture.subject,
                environment=fixture.environment,
                request_id="v3-tampered",
                cursor=None,
                limit=1,
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["truncated", "missing_column", "hierarchy", "deny"])
async def test_current_target_or_authorization_drift_returns_no_candidate_page(
    failure: str,
) -> None:
    fixture = _fixture()
    target = fixture.catalog.targets[0]
    if failure == "truncated":
        fixture.catalog.targets = (replace(target, column_names_truncated=True),)
    elif failure == "missing_column":
        fixture.catalog.targets = (replace(target, column_names=("lot_id",)),)
    elif failure == "hierarchy":
        fixture.catalog.targets = (replace(target, schema_name="drifted"),)
    else:
        fixture.authorization.denied_action = Action.CHANGE_CREATE

    with pytest.raises(UploadCandidatePageUnavailable):
        await fixture.service.list_candidates(
            workspace_id=fixture.manifest.workspace_id,
            upload_id=fixture.manifest.upload_id,
            preparation_id=fixture.preparation.preparation_id,
            subject=fixture.subject,
            environment=fixture.environment,
            request_id="v3-current-drift",
            cursor=None,
            limit=10,
        )


@pytest.mark.asyncio
async def test_receipt_distinguishes_row_and_group_counts_before_candidate_read() -> None:
    fixture = _fixture()
    fixture.reader.receipt = replace(fixture.receipt, candidate_count=4)

    with pytest.raises(UploadPreparationEvidenceUnavailable):
        await fixture.service.list_candidates(
            workspace_id=fixture.manifest.workspace_id,
            upload_id=fixture.manifest.upload_id,
            preparation_id=fixture.preparation.preparation_id,
            subject=fixture.subject,
            environment=fixture.environment,
            request_id="v3-invalid-counts",
            cursor=None,
            limit=10,
        )
    assert fixture.reader.page_reads == 0
