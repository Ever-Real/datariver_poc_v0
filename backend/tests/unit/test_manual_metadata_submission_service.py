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
from datariver.domain.common import ConflictError, DomainEvent, ForbiddenError, ValidationError
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
            raw_version="b" * 64,
            observed_at=datetime.now(UTC),
        )


class _TruncatedDataHub(_DataHub):
    async def get_asset(self, urn: str) -> DataHubAssetEnrichment:
        enrichment = await super().get_asset(urn)
        return DataHubAssetEnrichment(
            ownership=enrichment.ownership,
            glossary_terms=enrichment.glossary_terms,
            tags=enrichment.tags,
            schema_fields=enrichment.schema_fields,
            quality=enrichment.quality,
            raw_version=enrichment.raw_version,
            observed_at=enrichment.observed_at,
            schema_fields_total=1_001,
            schema_fields_truncated=True,
            schema_fields_total_exact=False,
        )


class _BaselineDataHub(_DataHub):
    def __init__(self) -> None:
        self.calls = 0
        self.fail = False

    async def get_asset(self, _: str) -> DataHubAssetEnrichment:
        self.calls += 1
        if self.fail:
            raise AssertionError("idempotent recovery must not call DataHub")
        return DataHubAssetEnrichment(
            ownership=(),
            glossary_terms=(),
            tags=(),
            schema_fields=(
                {
                    "fieldPath": "wafer_id",
                    "nativeDataType": "uuid",
                    "description": "provider identifier",
                    "globalTags": {"tags": [{"tag": "urn:li:tag:provider"}]},
                    "glossaryTerms": {"terms": [{"term": "urn:li:glossaryTerm:provider"}]},
                },
                {
                    "fieldPath": "measured_at",
                    "nativeDataType": "timestamp",
                    "description": "provider time",
                    "globalTags": {"tags": []},
                    "glossaryTerms": {"terms": []},
                },
            ),
            quality={},
            raw_version="c" * 64,
            observed_at=datetime.now(UTC),
        )


class _OversizedDataHub(_DataHub):
    async def get_asset(self, _: str) -> DataHubAssetEnrichment:
        return DataHubAssetEnrichment(
            ownership=(),
            glossary_terms=(),
            tags=(),
            schema_fields=tuple(
                {
                    "fieldPath": f"column_{index:04d}",
                    "nativeDataType": "varchar",
                    "description": "x" * 10_000,
                }
                for index in range(600)
            ),
            quality={},
            raw_version="b" * 64,
            observed_at=datetime.now(UTC),
        )


class _Store:
    def __init__(self) -> None:
        self.writes: list[tuple[str, str, bytes, dict[str, str]]] = []
        self.deleted: list[tuple[str, str]] = []

    async def write_immutable_receipt(self, **kwargs: Any) -> CatalogExportArtifact:
        value = cast(bytes, kwargs["content"])
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

    async def acquire_key_lock(self, **_: object) -> None:
        return None

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
    def __init__(
        self,
        *,
        commit_error: Exception | None = None,
        flush_error: Exception | None = None,
    ) -> None:
        self.manual_metadata_submissions = _ManualRepository()
        self.outbox = _Outbox()
        self.idempotency = _Idempotency()
        self.committed = False
        self.commit_error = commit_error
        self.flush_error = flush_error

    async def __aenter__(self) -> _Uow:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def set_security_context(self, **_: object) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True
        if self.commit_error is not None:
            raise self.commit_error

    async def flush(self) -> None:
        if self.flush_error is not None:
            raise self.flush_error
        return None

    async def rollback(self) -> None:
        return None


def _fixture(
    denied: Action | None = None,
    *,
    asset_type: str = "DATASET",
    datahub: DataHubGateway | None = None,
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
        asset_type=asset_type,
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
        datahub=datahub or cast(DataHubGateway, _DataHub()),
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
@pytest.mark.parametrize("asset_type", ["DATASET", "TABLE", "VIEW"])
async def test_manual_submission_writes_server_owned_csv_and_queues_an_independent_event(
    asset_type: str,
) -> None:
    service, store, uow, subject, environment, actions, asset_id = _fixture(asset_type=asset_type)

    submission = await service.submit(
        asset_id=asset_id,
        source_version="source-v1",
        provider_source_version="b" * 64,
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
    assert metadata["submission-id"] == str(submission.submission_id)
    assert metadata["serial-number"] == str(submission.serial_number)
    assert metadata["content-sha256"] == submission.csv_sha256
    assert metadata["content-size"] == str(submission.csv_size_bytes)
    assert b"urn:li:tag:quality%3Agold" in document
    assert b"urn:li:glossaryTerm:wafer" in document


@pytest.mark.asyncio
async def test_ambiguous_commit_failure_never_deletes_the_created_receipt() -> None:
    service, store, uow, subject, environment, _, asset_id = _fixture()
    uow.commit_error = ConnectionError("commit acknowledgement lost")

    with pytest.raises(ConnectionError, match="acknowledgement lost"):
        await service.submit(
            asset_id=asset_id,
            source_version="source-v1",
            provider_source_version="b" * 64,
            description="Updated wafer metadata",
            domain=None,
            tags=(),
            terms=(),
            columns=(
                ManualColumnMetadata("wafer_id", "Identifier", (), ()),
                ManualColumnMetadata("measured_at", "Observed time", (), ()),
            ),
            subject=subject,
            environment=environment,
            request_id="manual-ambiguous-commit",
            idempotency_key="manual-ambiguous-commit-key",
            request_hash="a" * 64,
        )

    assert uow.committed is True
    assert len(store.writes) == 1
    assert store.deleted == []


@pytest.mark.asyncio
async def test_deterministic_database_failure_occurs_before_receipt_creation() -> None:
    service, store, uow, subject, environment, _, asset_id = _fixture()
    uow.flush_error = ConflictError("duplicate idempotency result")

    with pytest.raises(ConflictError, match="duplicate idempotency"):
        await service.submit(
            asset_id=asset_id,
            source_version="source-v1",
            provider_source_version="b" * 64,
            description="Updated wafer metadata",
            domain=None,
            tags=(),
            terms=(),
            columns=(
                ManualColumnMetadata("wafer_id", "Identifier", (), ()),
                ManualColumnMetadata("measured_at", "Observed time", (), ()),
            ),
            subject=subject,
            environment=environment,
            request_id="manual-pre-write-failure",
            idempotency_key="manual-pre-write-failure-key",
            request_hash="b" * 64,
        )

    assert uow.committed is False
    assert store.writes == []
    assert store.deleted == []


@pytest.mark.asyncio
async def test_receipt_size_limit_fails_before_database_or_object_write() -> None:
    service, store, uow, subject, environment, _, asset_id = _fixture(
        datahub=cast(DataHubGateway, _OversizedDataHub())
    )

    with pytest.raises(ValidationError) as captured:
        await service.submit(
            asset_id=asset_id,
            source_version="source-v1",
            provider_source_version="b" * 64,
            description="updated",
            domain=None,
            tags=(),
            terms=(),
            columns=(),
            subject=subject,
            environment=environment,
            request_id="manual-receipt-limit",
            idempotency_key="manual-receipt-limit-key",
            request_hash="1" * 64,
        )

    assert captured.value.details == {"code": "MANUAL_METADATA_RECEIPT_TOO_LARGE"}
    assert uow.manual_metadata_submissions.values == {}
    assert store.writes == []
    assert uow.committed is False


@pytest.mark.asyncio
async def test_normalized_controlled_reference_limit_fails_before_provider_or_write() -> None:
    service, store, uow, subject, environment, _, asset_id = _fixture()

    with pytest.raises(ValidationError, match="exceeds the limit"):
        await service.submit(
            asset_id=asset_id,
            source_version="source-v1",
            provider_source_version="b" * 64,
            description="updated",
            domain=None,
            tags=("한" * 1_000,),
            terms=(),
            columns=(),
            subject=subject,
            environment=environment,
            request_id="manual-ref-limit",
            idempotency_key="manual-ref-limit-key",
            request_hash="2" * 64,
        )

    assert uow.manual_metadata_submissions.values == {}
    assert store.writes == []


@pytest.mark.asyncio
async def test_manual_submission_denial_never_writes_the_csv() -> None:
    service, store, uow, subject, environment, _, asset_id = _fixture(
        denied=Action.REGISTRATION_CREATE
    )

    with pytest.raises(ForbiddenError):
        await service.submit(
            asset_id=asset_id,
            source_version="source-v1",
            provider_source_version="b" * 64,
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


@pytest.mark.asyncio
async def test_sparse_column_edits_rehydrate_the_complete_fresh_provider_schema() -> None:
    datahub = _BaselineDataHub()
    service, store, _, subject, environment, _, asset_id = _fixture(
        datahub=cast(DataHubGateway, datahub)
    )

    submission = await service.submit(
        asset_id=asset_id,
        source_version="source-v1",
        provider_source_version="c" * 64,
        description="table-only update",
        domain=None,
        tags=(),
        terms=(),
        columns=(ManualColumnMetadata("wafer_id", "edited identifier", (), ()),),
        subject=subject,
        environment=environment,
        request_id="manual-sparse",
        idempotency_key="manual-sparse-idempotency",
        request_hash="d" * 64,
    )

    assert [(column.field_path, column.description) for column in submission.columns] == [
        ("wafer_id", "edited identifier"),
        ("measured_at", "provider time"),
    ]
    assert submission.columns[1].tags == ()
    assert submission.provider_source_version == "c" * 64
    assert store.writes[0][3]["provider-source-version"] == "c" * 64


@pytest.mark.asyncio
async def test_legacy_request_without_provider_version_pins_the_fresh_provider_version() -> None:
    service, store, _, subject, environment, _, asset_id = _fixture()

    submission = await service.submit(
        asset_id=asset_id,
        source_version="source-v1",
        provider_source_version=None,
        description="legacy-compatible",
        domain=None,
        tags=(),
        terms=(),
        columns=(
            ManualColumnMetadata("wafer_id", "Identifier", (), ()),
            ManualColumnMetadata("measured_at", "Observed time", (), ()),
        ),
        subject=subject,
        environment=environment,
        request_id="manual-legacy-compatible",
        idempotency_key="manual-legacy-compatible-key",
        request_hash="3" * 64,
    )

    assert submission.provider_source_version == "b" * 64
    assert store.writes[0][3]["provider-source-version"] == "b" * 64


@pytest.mark.asyncio
async def test_successful_idempotent_retry_recovers_before_provider_read() -> None:
    datahub = _BaselineDataHub()
    service, store, _, subject, environment, _, asset_id = _fixture(
        datahub=cast(DataHubGateway, datahub)
    )
    command: dict[str, Any] = {
        "asset_id": asset_id,
        "source_version": "source-v1",
        "provider_source_version": "c" * 64,
        "description": "table-only update",
        "domain": None,
        "tags": (),
        "terms": (),
        "columns": (),
        "subject": subject,
        "environment": environment,
        "request_id": "manual-replay",
        "idempotency_key": "manual-replay-idempotency",
        "request_hash": "e" * 64,
    }

    first = await service.submit(**command)
    datahub.fail = True
    second = await service.submit(**command)

    assert second.submission_id == first.submission_id
    assert datahub.calls == 1
    assert len(store.writes) == 1


@pytest.mark.asyncio
async def test_provider_source_drift_fails_before_database_or_object_write() -> None:
    datahub = _BaselineDataHub()
    service, store, uow, subject, environment, _, asset_id = _fixture(
        datahub=cast(DataHubGateway, datahub)
    )

    with pytest.raises(ConflictError) as captured:
        await service.submit(
            asset_id=asset_id,
            source_version="source-v1",
            provider_source_version="f" * 64,
            description="stale",
            domain=None,
            tags=(),
            terms=(),
            columns=(),
            subject=subject,
            environment=environment,
            request_id="manual-provider-drift",
            idempotency_key="manual-provider-drift-key",
            request_hash="f" * 64,
        )

    assert captured.value.details == {"code": "PROVIDER_SOURCE_VERSION_MISMATCH"}
    assert store.writes == []
    assert uow.committed is False


@pytest.mark.asyncio
async def test_manual_submission_rejects_a_truncated_provider_schema() -> None:
    service, store, uow, subject, environment, _, asset_id = _fixture(
        datahub=cast(DataHubGateway, _TruncatedDataHub())
    )

    with pytest.raises(ConflictError) as captured:
        await service.submit(
            asset_id=asset_id,
            source_version="source-v1",
            provider_source_version="b" * 64,
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
            request_id="manual-truncated-schema",
            idempotency_key="manual-submission-0003",
            request_hash="c" * 64,
        )

    assert captured.value.details == {"code": "PROVIDER_METADATA_TRUNCATED"}
    assert store.writes == []
    assert uow.committed is False
