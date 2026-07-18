from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from datariver.application.classification_access import (
    ClassificationAccessResolver,
    ClassificationAccessSnapshot,
    static_classification_access_floor,
)
from datariver.application.dto import (
    CatalogAssetDetail,
    CatalogAssetIndex,
    CatalogExportArtifact,
    DataHubAssetEnrichment,
    IdempotencyRecord,
)
from datariver.application.ports import (
    CatalogExportObjectStore,
    CatalogIndexReader,
    DataHubGateway,
    GovernanceUnitOfWork,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.manual_metadata import ManualMetadataSubmissionService
from datariver.domain.authz import Action, Classification, EnvironmentAttributes, SubjectAttributes
from datariver.domain.common import DomainEvent, ForbiddenError
from datariver.domain.manual_metadata import ManualColumnMetadata, ManualMetadataSubmission


class _Access:
    async def resolve(self, **_: object) -> ClassificationAccessSnapshot:
        return static_classification_access_floor()


class _Index:
    def __init__(self, detail: CatalogAssetDetail) -> None:
        self.detail = detail

    async def get_authorized_asset(self, **_: object) -> CatalogAssetDetail:
        return self.detail


class _Authorization:
    def __init__(self, actions: list[Action], denied: Action | None = None) -> None:
        self.actions = actions
        self.denied = denied

    async def authorize(self, *, action: Action, **_: object) -> None:
        self.actions.append(action)
        if action is self.denied:
            raise ForbiddenError("denied")


class _DataHub:
    async def get_asset(self, _: str) -> DataHubAssetEnrichment:
        return DataHubAssetEnrichment(
            ownership=(),
            glossary_terms=(),
            tags=(),
            schema_fields=(
                {"fieldPath": "wafer_id", "nativeDataType": "uuid"},
                {"fieldPath": "measured_at", "nativeDataType": "timestamp"},
            ),
            quality={},
            raw_version="provider-v1",
            observed_at=datetime.now(UTC),
        )


class _Store:
    def __init__(self) -> None:
        self.writes: list[tuple[str, str, bytes, dict[str, str]]] = []
        self.deleted: list[tuple[str, str]] = []

    async def write_export(self, **kwargs: Any) -> CatalogExportArtifact:
        chunks = [chunk async for chunk in kwargs["chunks"]]
        value = b"".join(chunks)
        self.writes.append((kwargs["bucket"], kwargs["object_key"], value, kwargs["metadata"]))
        import hashlib

        return CatalogExportArtifact(
            size_bytes=len(value),
            content_sha256=hashlib.sha256(value).hexdigest(),
            provider_checksum="etag:test",
        )

    async def delete_export(self, *, bucket: str, object_key: str) -> None:
        self.deleted.append((bucket, object_key))


class _ManualRepository:
    def __init__(self) -> None:
        self.serial = 41
        self.values: dict[object, ManualMetadataSubmission] = {}

    async def allocate_serial_number(self) -> int:
        self.serial += 1
        return self.serial

    async def add(self, submission: ManualMetadataSubmission) -> None:
        self.values[submission.submission_id] = submission

    async def get(self, *, submission_id: object, **_: object) -> ManualMetadataSubmission | None:
        return self.values.get(submission_id)


class _Outbox:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def add_events(self, events: list[DomainEvent]) -> None:
        self.events.extend(events)


class _Idempotency:
    def __init__(self) -> None:
        self.records: dict[tuple[object, str, str], IdempotencyRecord] = {}

    async def get_result(
        self, *, workspace_id: object, key: str, operation: str
    ) -> IdempotencyRecord | None:
        return self.records.get((workspace_id, key, operation))

    async def save_result(
        self,
        *,
        workspace_id: object,
        key: str,
        operation: str,
        request_hash: str,
        result: dict[str, object],
    ) -> None:
        self.records[(workspace_id, key, operation)] = IdempotencyRecord(
            request_hash=request_hash,
            result=result,
        )


class _Uow:
    def __init__(self) -> None:
        self.manual_metadata_submissions = _ManualRepository()
        self.outbox = _Outbox()
        self.idempotency = _Idempotency()
        self.committed = False

    async def __aenter__(self) -> _Uow:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def set_security_context(self, **_: object) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        return None


def _fixture(
    denied: Action | None = None,
) -> tuple[
    ManualMetadataSubmissionService,
    _Store,
    _Uow,
    SubjectAttributes,
    EnvironmentAttributes,
    list[Action],
    UUID,
]:
    now = datetime(2026, 7, 18, tzinfo=UTC)
    workspace_id = uuid4()
    index = CatalogAssetIndex(
        asset_id=uuid4(),
        workspace_id=workspace_id,
        external_urn="urn:li:dataset:(urn:li:dataPlatform:postgres,wafer,PROD)",
        asset_type="DATASET",
        name="wafer",
        description="Current wafer metadata",
        platform="postgres",
        database_name="fab",
        schema_name="manufacturing",
        domain_id=uuid4(),
        system_id=uuid4(),
        owner_department_id=uuid4(),
        classification=Classification.INTERNAL,
        lifecycle="ACTIVE",
        source_version="source-v1",
        observed_at=now,
    )
    detail = CatalogAssetDetail(index, (), (), (), (), {}, "source-v1", now)
    actions: list[Action] = []
    store = _Store()
    uow = _Uow()
    service = ManualMetadataSubmissionService(
        index=cast(CatalogIndexReader, _Index(detail)),
        classification_access=cast(ClassificationAccessResolver, _Access()),
        authorization=cast(AuthorizationService, _Authorization(actions, denied)),
        datahub=cast(DataHubGateway, _DataHub()),
        object_store=cast(CatalogExportObjectStore, store),
        uow_factory=lambda: cast(GovernanceUnitOfWork, uow),
        infoschema_bucket="datariver-infoschema",
    )
    subject = SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset({"data-stewards"}),
        job_function="DATA_STEWARD",
        clearance=Classification.INTERNAL,
    )
    return service, store, uow, subject, EnvironmentAttributes(now), actions, index.asset_id


@pytest.mark.asyncio
async def test_manual_submission_writes_server_owned_csv_and_queues_an_independent_event() -> None:
    service, store, uow, subject, environment, actions, asset_id = _fixture()

    submission = await service.submit(
        asset_id=asset_id,
        source_version="source-v1",
        description="Updated wafer metadata",
        domain="Semiconductor",
        tags=("quality:gold",),
        terms=("wafer",),
        columns=(
            ManualColumnMetadata("wafer_id", "Identifier", ("identifier",), ("wafer",)),
            ManualColumnMetadata("measured_at", "Observed time", (), ()),
        ),
        subject=subject,
        environment=environment,
        request_id="manual-1",
        idempotency_key="manual-submission-0001",
        request_hash="a" * 64,
    )

    assert actions == [Action.CATALOG_READ, Action.REGISTRATION_CREATE]
    assert submission.state.value == "QUEUED"
    assert submission.row_count == 3
    assert uow.committed is True
    assert [event.event_type for event in uow.outbox.events] == [
        "registration.manual_metadata.queued.v1"
    ]
    bucket, object_key, document, metadata = store.writes[0]
    assert bucket == "datariver-infoschema"
    assert object_key == "UPLOAD_METADATA_MANUAL_260718_000042.csv"
    assert metadata["asset-id"] == str(submission.asset_id)
    assert b"urn:li:tag:quality%3Agold" in document
    assert b"urn:li:glossaryTerm:wafer" in document


@pytest.mark.asyncio
async def test_manual_submission_denial_never_writes_the_csv() -> None:
    service, store, uow, subject, environment, _, asset_id = _fixture(
        denied=Action.REGISTRATION_CREATE
    )

    with pytest.raises(ForbiddenError):
        await service.submit(
            asset_id=asset_id,
            source_version="source-v1",
            description="updated",
            domain=None,
            tags=(),
            terms=(),
            columns=(
                ManualColumnMetadata("wafer_id", "Identifier", (), ()),
                ManualColumnMetadata("measured_at", "Observed time", (), ()),
            ),
            subject=subject,
            environment=environment,
            request_id="manual-denied",
            idempotency_key="manual-submission-0002",
            request_hash="b" * 64,
        )
    assert store.writes == []
    assert uow.committed is False
