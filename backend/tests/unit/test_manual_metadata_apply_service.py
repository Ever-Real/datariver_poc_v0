from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, cast
from uuid import uuid4

import pytest

from datariver.application.dto import (
    DataHubApplyReceipt,
    DataHubAspectSnapshot,
    DataHubAssetEnrichment,
    ManualMetadataApplyAttemptEvidence,
    ManualMetadataAspectReportEvidence,
)
from datariver.application.errors import ExternalDependencyError
from datariver.application.ports import DataHubGateway, GovernanceUnitOfWork, ObjectStore
from datariver.application.services.manual_metadata_apply import (
    ManualMetadataApplyService,
    _encode_manual_provider_checkpoint,
)
from datariver.domain.common import DomainEvent, ForbiddenError, canonical_json_hash
from datariver.domain.manual_metadata import (
    ManualColumnMetadata,
    ManualMetadataApplyClaim,
    ManualMetadataAspectReport,
    ManualMetadataSubmission,
    ManualMetadataSubmissionState,
)
from datariver.domain.registration_worker import (
    RegistrationWorkerCallIdentity,
    RegistrationWorkerCallReplay,
)


class _ObjectStore:
    def __init__(self, document: bytes) -> None:
        self.document = document

    async def iter_object_chunks(self, **_: object) -> AsyncIterator[bytes]:
        yield self.document


class _Eligibility:
    def __init__(self, *, deny_on_call: int | None = None) -> None:
        self.calls: list[str] = []
        self.deny_on_call = deny_on_call

    async def authorize(self, **kwargs: object) -> None:
        self.calls.append(cast(str, kwargs["request_id"]))
        if self.deny_on_call == len(self.calls):
            raise ForbiddenError("requester access revoked")


class _ProviderMutationLock:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    @asynccontextmanager
    async def hold(self, **kwargs: object) -> AsyncIterator[None]:
        self.calls.append(kwargs)
        yield


class _DataHub:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {
            "datasetProperties": {"name": "wafer", "description": "legacy"},
            "domains": {"domains": []},
            "globalTags": {"tags": []},
            "glossaryTerms": {"terms": []},
            "schemaMetadata": {
                "fields": [
                    {
                        "fieldPath": "wafer_id",
                        "description": "legacy identifier",
                        "globalTags": {"tags": []},
                        "glossaryTerms": {
                            "auditStamp": {
                                "actor": "urn:li:corpuser:__datahub_system",
                                "time": 0,
                            },
                            "terms": [],
                        },
                    },
                    {
                        "fieldPath": "measured_at",
                        "description": "legacy time",
                        "globalTags": {"tags": []},
                        "glossaryTerms": {"terms": []},
                    },
                ]
            },
        }
        self.applied: list[str] = []
        self.get_asset_calls = 0
        self.raw_version = "b" * 64

    async def get_asset(self, external_urn: str) -> DataHubAssetEnrichment:
        del external_urn
        self.get_asset_calls += 1
        return DataHubAssetEnrichment(
            ownership=(),
            glossary_terms=(),
            tags=(),
            schema_fields=(),
            quality={},
            raw_version=self.raw_version,
            observed_at=datetime(2026, 7, 18, tzinfo=UTC),
        )

    async def read_aspect(self, *, external_urn: str, aspect_name: str) -> DataHubAspectSnapshot:
        document = self.documents[aspect_name]
        return DataHubAspectSnapshot(
            urn=external_urn,
            aspect_name=aspect_name,
            document=MappingProxyType(document),
            content_hash=canonical_json_hash(document),
            source_version="provider-v1",
            observed_at=datetime(2026, 7, 18, tzinfo=UTC),
        )

    async def apply_change(
        self, *, aspect_name: str, document: dict[str, Any], **_: object
    ) -> DataHubApplyReceipt:
        self.documents[aspect_name] = document
        self.applied.append(aspect_name)
        return DataHubApplyReceipt(
            operation_id=f"apply-{aspect_name}",
            accepted_at=datetime(2026, 7, 18, tzinfo=UTC),
            provider_version="v1.6.0",
            response_hash=canonical_json_hash(document),
        )


class _RetryableDataHub(_DataHub):
    async def read_aspect(self, *, external_urn: str, aspect_name: str) -> DataHubAspectSnapshot:
        del external_urn, aspect_name
        raise ExternalDependencyError(
            "temporary provider outage",
            dependency="datahub",
            retryable=True,
            provider_code="UNAVAILABLE",
        )


class _DriftedDataHub(_DataHub):
    async def get_asset(self, external_urn: str) -> DataHubAssetEnrichment:
        value = await super().get_asset(external_urn)
        return DataHubAssetEnrichment(
            ownership=value.ownership,
            glossary_terms=value.glossary_terms,
            tags=value.tags,
            schema_fields=value.schema_fields,
            quality=value.quality,
            raw_version="c" * 64,
            observed_at=value.observed_at,
        )


class _StaleReadbackDataHub(_DataHub):
    async def apply_change(
        self, *, aspect_name: str, document: dict[str, Any], **_: object
    ) -> DataHubApplyReceipt:
        self.applied.append(aspect_name)
        return DataHubApplyReceipt(
            operation_id=f"apply-{aspect_name}",
            accepted_at=datetime(2026, 7, 18, tzinfo=UTC),
            provider_version="v1.6.0",
            response_hash=canonical_json_hash(document),
        )


class _RejectedWriteDataHub(_DataHub):
    async def apply_change(self, **_: object) -> DataHubApplyReceipt:
        raise ExternalDependencyError(
            "provider rejected write",
            dependency="datahub",
            retryable=False,
            provider_code="FORBIDDEN",
        )


class _Repository:
    def __init__(self, submission: ManualMetadataSubmission) -> None:
        self.submission = submission
        self.reports: list[ManualMetadataAspectReport] = []
        self.previous_attempts: tuple[ManualMetadataApplyAttemptEvidence, ...] = ()
        self.lease_renewals = 0
        self.worker_results: dict[str, dict[str, object]] = {}

    async def claim_next(
        self, **kwargs: object
    ) -> ManualMetadataApplyClaim | RegistrationWorkerCallReplay | None:
        run_call = cast(RegistrationWorkerCallIdentity | None, kwargs.get("run_call"))
        if run_call is not None and run_call.key_hash in self.worker_results:
            return RegistrationWorkerCallReplay(result=dict(self.worker_results[run_call.key_hash]))
        if self.submission.state.value != "QUEUED":
            if run_call is not None:
                result: dict[str, object] = {
                    "processed": False,
                    "submission_id": None,
                    "serial_number": None,
                    "state": None,
                }
                self.worker_results[run_call.key_hash] = result
                return RegistrationWorkerCallReplay(result=result)
            return None
        worker_subject_id = kwargs["worker_subject_id"]
        assert not isinstance(worker_subject_id, str)
        self.submission.claim_for_apply(
            now=cast(datetime, kwargs["now"]),
            lease_seconds=cast(int, kwargs["lease_seconds"]),
            lease_token_hash=hashlib.sha256(b"lease-token").hexdigest(),
            lease_owner_id=cast(Any, worker_subject_id),
        )
        return ManualMetadataApplyClaim(
            submission=self.submission,
            attempt_id=uuid4(),
            attempt_no=self.submission.attempts,
            lease_epoch=self.submission.lease_epoch,
            lease_token="lease-token",
            worker_subject_id=cast(Any, worker_subject_id),
            run_call=run_call,
        )

    async def get(self, **_: object) -> ManualMetadataSubmission:
        return self.submission

    async def save(self, submission: ManualMetadataSubmission) -> None:
        self.submission = submission

    async def record_aspect_report(
        self, *, claim: ManualMetadataApplyClaim, report: ManualMetadataAspectReport
    ) -> bool:
        del claim
        self.reports.append(report)
        return True

    async def renew_lease(self, **_: object) -> bool:
        self.lease_renewals += 1
        return True

    async def list_attempts(self, **_: object) -> tuple[ManualMetadataApplyAttemptEvidence, ...]:
        return self.previous_attempts

    async def complete(
        self, *, claim: ManualMetadataApplyClaim, now: datetime
    ) -> ManualMetadataSubmission:
        self.submission.mark_applied(now=now)
        if claim.run_call is not None:
            self.worker_results[claim.run_call.key_hash] = {
                "processed": True,
                "submission_id": str(self.submission.submission_id),
                "serial_number": self.submission.serial_number,
                "state": "APPLIED",
            }
        return self.submission

    async def fail(
        self,
        *,
        claim: ManualMetadataApplyClaim,
        now: datetime,
        error_code: str,
        retryable: bool,
        maximum_attempts: int,
    ) -> str:
        self.submission.mark_apply_failed(
            now=now,
            error_code=error_code,
            retryable=retryable and self.submission.attempts < maximum_attempts,
        )
        if claim.run_call is not None:
            self.worker_results[claim.run_call.key_hash] = {
                "processed": True,
                "submission_id": str(self.submission.submission_id),
                "serial_number": self.submission.serial_number,
                "state": self.submission.state.value,
            }
        return self.submission.state.value


class _Outbox:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def add_events(self, events: list[DomainEvent]) -> None:
        self.events.extend(events)


class _Uow:
    def __init__(self, submission: ManualMetadataSubmission) -> None:
        self.manual_metadata_submissions = _Repository(submission)
        self.outbox = _Outbox()
        self.commits = 0

    async def __aenter__(self) -> _Uow:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def set_security_context(self, **_: object) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


def _csv_document(submission: ManualMetadataSubmission) -> bytes:
    buffer = io.StringIO(newline="")
    fields = (
        "record_kind",
        "external_urn",
        "source_version",
        "platform",
        "database_name",
        "schema_name",
        "table_name",
        "column_name",
        "data_type",
        "description",
        "domain",
        "tags",
        "terms",
    )
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerow(
        {
            "record_kind": "TABLE",
            "external_urn": submission.external_urn,
            "source_version": submission.source_version,
            "description": submission.description,
            "domain": submission.domain or "",
            "tags": ",".join(submission.tags),
            "terms": ",".join(submission.terms),
        }
    )
    for column in submission.columns:
        writer.writerow(
            {
                "record_kind": "COLUMN",
                "external_urn": submission.external_urn,
                "source_version": submission.source_version,
                "column_name": column.field_path,
                "description": column.description,
                "tags": ",".join(column.tags),
                "terms": ",".join(column.terms),
            }
        )
    return buffer.getvalue().encode()


def _submission() -> ManualMetadataSubmission:
    initial = ManualMetadataSubmission.queue(
        workspace_id=uuid4(),
        asset_id=uuid4(),
        external_urn="urn:li:dataset:(urn:li:dataPlatform:postgres,wafer,PROD)",
        requester_id=uuid4(),
        source_version="source-v1",
        provider_source_version="b" * 64,
        serial_number=17,
        description="Verified wafer measurements.",
        domain="urn:li:domain:manufacturing",
        tags=("urn:li:tag:tier%3Agold",),
        terms=("urn:li:glossaryTerm:wafer",),
        columns=(
            ManualColumnMetadata(
                "wafer_id",
                "Business identifier.",
                ("urn:li:tag:identifier",),
                ("urn:li:glossaryTerm:wafer",),
            ),
            ManualColumnMetadata("measured_at", "Observed time.", (), ()),
        ),
        bucket="datariver-infoschema",
        object_key="UPLOAD_METADATA_MANUAL_260718_000017.csv",
        csv_sha256="0" * 64,
        csv_size_bytes=1,
        row_count=3,
    )
    initial.events.clear()  # persisted queue events are not re-emitted by a later worker read.
    document = _csv_document(initial)
    initial.csv_sha256 = hashlib.sha256(document).hexdigest()
    initial.csv_size_bytes = len(document)
    return initial


def _apply_target_prefix(
    datahub: _DataHub,
    submission: ManualMetadataSubmission,
    *,
    count: int,
) -> None:
    if count >= 1:
        ManualMetadataApplyService._set_description(
            datahub.documents["datasetProperties"],
            submission.description,
        )
    if count >= 2:
        ManualMetadataApplyService._set_controlled_refs(
            datahub.documents["domains"],
            field="domains",
            nested=None,
            refs=(() if submission.domain is None else (submission.domain,)),
        )
    if count >= 3:
        ManualMetadataApplyService._set_controlled_refs(
            datahub.documents["globalTags"],
            field="tags",
            nested="tag",
            refs=submission.tags,
        )
    if count >= 4:
        ManualMetadataApplyService._set_controlled_refs(
            datahub.documents["glossaryTerms"],
            field="terms",
            nested="urn",
            refs=submission.terms,
        )
    if count >= 5:
        ManualMetadataApplyService._set_schema_metadata(
            datahub.documents["schemaMetadata"],
            submission,
        )


def _previous_attempt(
    *,
    submission: ManualMetadataSubmission,
    datahub: _DataHub,
    verified_count: int,
    checkpoint_source_version: str,
    failed_ordinal: int | None = None,
) -> ManualMetadataApplyAttemptEvidence:
    aspect_names = (
        "datasetProperties",
        "domains",
        "globalTags",
        "glossaryTerms",
        "schemaMetadata",
    )
    aspects: list[ManualMetadataAspectReportEvidence] = []
    for ordinal, aspect_name in enumerate(aspect_names[:verified_count], start=1):
        content_hash = canonical_json_hash(datahub.documents[aspect_name])
        aspects.append(
            ManualMetadataAspectReportEvidence(
                aspect_name=aspect_name,
                aspect_ordinal=ordinal,
                outcome="APPLIED_VERIFIED",
                before_hash="a" * 64,
                expected_hash=content_hash,
                observed_hash=content_hash,
                write_attempted=True,
                failure_code=None,
                provider_version=_encode_manual_provider_checkpoint(
                    source_version=checkpoint_source_version,
                    provider_version="v1.6.0",
                ),
                provider_response_hash="b" * 64,
                observed_at=datetime(2026, 7, 18, tzinfo=UTC),
            )
        )
    if failed_ordinal is not None:
        aspects.append(
            ManualMetadataAspectReportEvidence(
                aspect_name=aspect_names[failed_ordinal - 1],
                aspect_ordinal=failed_ordinal,
                outcome="WRITE_REJECTED",
                before_hash="c" * 64,
                expected_hash="d" * 64,
                observed_hash=None,
                write_attempted=True,
                failure_code="PROVIDER_UNAVAILABLE",
                provider_version=None,
                provider_response_hash=None,
                observed_at=datetime(2026, 7, 18, tzinfo=UTC),
            )
        )
    return ManualMetadataApplyAttemptEvidence(
        attempt_id=uuid4(),
        attempt_no=submission.attempts,
        lease_epoch=submission.lease_epoch,
        state="RETRY_WAIT",
        failure_code="PROVIDER_UNAVAILABLE" if failed_ordinal is not None else "PROCESS_CRASH",
        report_root_hash="e" * 64,
        started_at=datetime(2026, 7, 18, tzinfo=UTC),
        finished_at=datetime(2026, 7, 18, tzinfo=UTC),
        aspects=tuple(aspects),
    )


@pytest.mark.asyncio
async def test_airflow_apply_verifies_csv_then_merges_all_typed_aspects() -> None:
    submission = _submission()
    document = _csv_document(submission)
    uow = _Uow(submission)
    datahub = _DataHub()
    eligibility = _Eligibility()
    provider_lock = _ProviderMutationLock()
    service = ManualMetadataApplyService(
        datahub=cast(DataHubGateway, datahub),
        object_store=cast(ObjectStore, _ObjectStore(document)),
        uow_factory=lambda: cast(GovernanceUnitOfWork, uow),
        eligibility=cast(Any, eligibility),
        provider_mutation_lock=cast(Any, provider_lock),
        lease_seconds=60,
        maximum_attempts=3,
    )

    result = await service.run_once(
        workspace_id=submission.workspace_id,
        worker_subject_id=uuid4(),
        request_id="manual-apply",
    )

    assert result.state == "APPLIED"
    assert submission.state.value == "APPLIED"
    assert datahub.applied == [
        "datasetProperties",
        "domains",
        "globalTags",
        "glossaryTerms",
        "schemaMetadata",
    ]
    assert datahub.documents["datasetProperties"]["description"] == "Verified wafer measurements."
    assert datahub.documents["domains"]["domains"] == ["urn:li:domain:manufacturing"]
    assert datahub.documents["globalTags"]["tags"] == [{"tag": "urn:li:tag:tier%3Agold"}]
    wafer_id = datahub.documents["schemaMetadata"]["fields"][0]
    assert wafer_id["description"] == "Business identifier."
    assert wafer_id["globalTags"]["tags"] == [{"tag": "urn:li:tag:identifier"}]
    assert wafer_id["glossaryTerms"]["auditStamp"] == {
        "actor": "urn:li:corpuser:__datahub_system",
        "time": 0,
    }
    assert [event.event_type for event in uow.outbox.events] == [
        "registration.manual_metadata.applied.v1"
    ]
    assert uow.manual_metadata_submissions.lease_renewals >= 3 + (5 * 3)
    assert len(provider_lock.calls) == 1
    assert {key: value for key, value in provider_lock.calls[0].items() if key != "on_wait"} == {
        "workspace_id": submission.workspace_id,
        "provider": "DATAHUB",
        "target_ref": submission.external_urn,
        "aspect_name": "*",
    }
    assert callable(provider_lock.calls[0]["on_wait"])
    assert eligibility.calls == [
        "manual-apply:claim",
        "manual-apply:datasetProperties",
        "manual-apply:domains",
        "manual-apply:globalTags",
        "manual-apply:glossaryTerms",
        "manual-apply:schemaMetadata",
        "manual-apply:complete",
    ]
    assert len(provider_lock.calls) == 1
    assert provider_lock.calls[0]["aspect_name"] == "*"
    assert callable(provider_lock.calls[0]["on_wait"])


@pytest.mark.asyncio
async def test_provider_source_version_drift_fails_before_any_aspect_write() -> None:
    submission = _submission()
    datahub = _DriftedDataHub()
    uow = _Uow(submission)
    service = ManualMetadataApplyService(
        datahub=cast(DataHubGateway, datahub),
        object_store=cast(ObjectStore, _ObjectStore(_csv_document(submission))),
        uow_factory=lambda: cast(GovernanceUnitOfWork, uow),
        eligibility=cast(Any, _Eligibility()),
        provider_mutation_lock=cast(Any, _ProviderMutationLock()),
        lease_seconds=60,
        maximum_attempts=3,
    )

    result = await service.run_once(
        workspace_id=submission.workspace_id,
        worker_subject_id=uuid4(),
        request_id="manual-provider-drift",
    )

    assert result.state == "FAILED"
    assert submission.last_error_code == "PROVIDER_SOURCE_VERSION_MISMATCH"
    assert datahub.applied == []
    assert uow.manual_metadata_submissions.reports == []


@pytest.mark.asyncio
async def test_retry_resumes_after_a_persisted_verified_prefix_and_partial_failure() -> None:
    submission = _submission()
    submission.attempts = 1
    datahub = _DataHub()
    datahub.raw_version = "c" * 64
    _apply_target_prefix(datahub, submission, count=2)
    uow = _Uow(submission)
    uow.manual_metadata_submissions.previous_attempts = (
        _previous_attempt(
            submission=submission,
            datahub=datahub,
            verified_count=2,
            checkpoint_source_version=datahub.raw_version,
            failed_ordinal=3,
        ),
    )
    service = ManualMetadataApplyService(
        datahub=cast(DataHubGateway, datahub),
        object_store=cast(ObjectStore, _ObjectStore(_csv_document(submission))),
        uow_factory=lambda: cast(GovernanceUnitOfWork, uow),
        eligibility=cast(Any, _Eligibility()),
        provider_mutation_lock=cast(Any, _ProviderMutationLock()),
        lease_seconds=60,
        maximum_attempts=3,
    )

    result = await service.run_once(
        workspace_id=submission.workspace_id,
        worker_subject_id=uuid4(),
        request_id="manual-provider-prefix-resume",
    )

    assert result.state == "APPLIED"
    assert datahub.applied == ["globalTags", "glossaryTerms", "schemaMetadata"]


@pytest.mark.asyncio
async def test_retry_rejects_unrelated_drift_after_a_verified_prefix_checkpoint() -> None:
    submission = _submission()
    submission.attempts = 1
    datahub = _DataHub()
    _apply_target_prefix(datahub, submission, count=2)
    uow = _Uow(submission)
    uow.manual_metadata_submissions.previous_attempts = (
        _previous_attempt(
            submission=submission,
            datahub=datahub,
            verified_count=2,
            checkpoint_source_version="c" * 64,
            failed_ordinal=3,
        ),
    )
    datahub.raw_version = "d" * 64
    service = ManualMetadataApplyService(
        datahub=cast(DataHubGateway, datahub),
        object_store=cast(ObjectStore, _ObjectStore(_csv_document(submission))),
        uow_factory=lambda: cast(GovernanceUnitOfWork, uow),
        eligibility=cast(Any, _Eligibility()),
        provider_mutation_lock=cast(Any, _ProviderMutationLock()),
        lease_seconds=60,
        maximum_attempts=3,
    )

    result = await service.run_once(
        workspace_id=submission.workspace_id,
        worker_subject_id=uuid4(),
        request_id="manual-provider-unrelated-drift",
    )

    assert result.state == "FAILED"
    assert submission.last_error_code == "PROVIDER_SOURCE_VERSION_MISMATCH"
    assert datahub.applied == []


@pytest.mark.asyncio
async def test_retry_after_five_writes_and_pre_completion_crash_is_read_only() -> None:
    submission = _submission()
    submission.attempts = 1
    datahub = _DataHub()
    datahub.raw_version = "c" * 64
    _apply_target_prefix(datahub, submission, count=5)
    uow = _Uow(submission)
    uow.manual_metadata_submissions.previous_attempts = (
        _previous_attempt(
            submission=submission,
            datahub=datahub,
            verified_count=5,
            checkpoint_source_version=datahub.raw_version,
        ),
    )
    service = ManualMetadataApplyService(
        datahub=cast(DataHubGateway, datahub),
        object_store=cast(ObjectStore, _ObjectStore(_csv_document(submission))),
        uow_factory=lambda: cast(GovernanceUnitOfWork, uow),
        eligibility=cast(Any, _Eligibility()),
        provider_mutation_lock=cast(Any, _ProviderMutationLock()),
        lease_seconds=60,
        maximum_attempts=3,
    )

    result = await service.run_once(
        workspace_id=submission.workspace_id,
        worker_subject_id=uuid4(),
        request_id="manual-provider-post-write-crash",
    )

    assert result.state == "APPLIED"
    assert datahub.applied == []
    assert [report.outcome.value for report in uow.manual_metadata_submissions.reports] == [
        "ALREADY_MATCHED"
    ] * 5


@pytest.mark.asyncio
async def test_completed_worker_call_replays_without_a_second_provider_effect() -> None:
    submission = _submission()
    datahub = _DataHub()
    uow = _Uow(submission)
    service = ManualMetadataApplyService(
        datahub=cast(DataHubGateway, datahub),
        object_store=cast(ObjectStore, _ObjectStore(_csv_document(submission))),
        uow_factory=lambda: cast(GovernanceUnitOfWork, uow),
        eligibility=cast(Any, _Eligibility()),
        provider_mutation_lock=cast(Any, _ProviderMutationLock()),
        lease_seconds=60,
        maximum_attempts=3,
    )
    call = RegistrationWorkerCallIdentity(
        operation="registration.manual-metadata.apply-run.v1",
        key_hash="1" * 64,
        request_hash="2" * 64,
        worker_subject_id=uuid4(),
    )

    first = await service.run_once(
        workspace_id=submission.workspace_id,
        worker_subject_id=call.worker_subject_id,
        request_id="manual-replay",
        run_call=call,
    )
    replay = await service.run_once(
        workspace_id=submission.workspace_id,
        worker_subject_id=call.worker_subject_id,
        request_id="manual-replay",
        run_call=call,
    )

    assert replay == first
    assert datahub.get_asset_calls == 6
    assert len(datahub.applied) == 5


@pytest.mark.asyncio
async def test_no_work_worker_call_remains_false_after_work_appears() -> None:
    submission = _submission()
    submission.state = ManualMetadataSubmissionState.APPLIED
    uow = _Uow(submission)
    service = ManualMetadataApplyService(
        datahub=cast(DataHubGateway, _DataHub()),
        object_store=cast(ObjectStore, _ObjectStore(_csv_document(submission))),
        uow_factory=lambda: cast(GovernanceUnitOfWork, uow),
        eligibility=cast(Any, _Eligibility()),
        provider_mutation_lock=cast(Any, _ProviderMutationLock()),
        lease_seconds=60,
        maximum_attempts=3,
    )
    call = RegistrationWorkerCallIdentity(
        operation="registration.manual-metadata.apply-run.v1",
        key_hash="3" * 64,
        request_hash="4" * 64,
        worker_subject_id=uuid4(),
    )

    empty = await service.run_once(
        workspace_id=submission.workspace_id,
        worker_subject_id=call.worker_subject_id,
        request_id="manual-empty",
        run_call=call,
    )
    submission.state = ManualMetadataSubmissionState.QUEUED
    submission.next_attempt_at = datetime(2026, 7, 18, tzinfo=UTC)
    replay = await service.run_once(
        workspace_id=submission.workspace_id,
        worker_subject_id=call.worker_subject_id,
        request_id="manual-empty",
        run_call=call,
    )

    assert empty.processed is False
    assert replay == empty
    assert submission.state.value == "QUEUED"


@pytest.mark.asyncio
async def test_final_requester_reauthorization_is_required_before_applied_state() -> None:
    submission = _submission()
    document = _csv_document(submission)
    uow = _Uow(submission)
    eligibility = _Eligibility(deny_on_call=7)
    service = ManualMetadataApplyService(
        datahub=cast(DataHubGateway, _DataHub()),
        object_store=cast(ObjectStore, _ObjectStore(document)),
        uow_factory=lambda: cast(GovernanceUnitOfWork, uow),
        eligibility=cast(Any, eligibility),
        provider_mutation_lock=cast(Any, _ProviderMutationLock()),
        lease_seconds=60,
        maximum_attempts=3,
    )

    result = await service.run_once(
        workspace_id=submission.workspace_id,
        worker_subject_id=uuid4(),
        request_id="manual-apply-revoked",
    )

    assert result.state == "FAILED"
    assert submission.state.value == "FAILED"
    assert uow.outbox.events == []


def test_empty_controlled_refs_preserve_an_absent_optional_aspect() -> None:
    document: dict[str, Any] = {}

    ManualMetadataApplyService._set_controlled_refs(
        document,
        field="domains",
        nested=None,
        refs=(),
    )

    assert document == {}


def test_empty_controlled_refs_preserve_provider_empty_list_shape() -> None:
    document: dict[str, Any] = {"domains": []}

    ManualMetadataApplyService._set_controlled_refs(
        document,
        field="domains",
        nested=None,
        refs=(),
    )

    assert document == {"domains": []}


@pytest.mark.asyncio
async def test_airflow_apply_never_calls_datahub_when_the_csv_receipt_hash_is_wrong() -> None:
    submission = _submission()
    uow = _Uow(submission)
    datahub = _DataHub()
    service = ManualMetadataApplyService(
        datahub=cast(DataHubGateway, datahub),
        object_store=cast(ObjectStore, _ObjectStore(b"tampered")),
        uow_factory=lambda: cast(GovernanceUnitOfWork, uow),
        eligibility=cast(Any, _Eligibility()),
        provider_mutation_lock=cast(Any, _ProviderMutationLock()),
        lease_seconds=60,
        maximum_attempts=3,
    )

    result = await service.run_once(
        workspace_id=submission.workspace_id,
        worker_subject_id=uuid4(),
        request_id="manual-apply-tampered",
    )

    assert result.state == "FAILED"
    assert submission.state.value == "FAILED"
    assert datahub.applied == []


@pytest.mark.asyncio
async def test_retry_exhaustion_returns_the_persisted_failed_state_to_airflow() -> None:
    submission = _submission()
    submission.attempts = 2
    document = _csv_document(submission)
    uow = _Uow(submission)
    service = ManualMetadataApplyService(
        datahub=cast(DataHubGateway, _RetryableDataHub()),
        object_store=cast(ObjectStore, _ObjectStore(document)),
        uow_factory=lambda: cast(GovernanceUnitOfWork, uow),
        eligibility=cast(Any, _Eligibility()),
        provider_mutation_lock=cast(Any, _ProviderMutationLock()),
        lease_seconds=60,
        maximum_attempts=3,
    )

    result = await service.run_once(
        workspace_id=submission.workspace_id,
        worker_subject_id=uuid4(),
        request_id="manual-apply-exhausted",
    )

    assert result.state == "FAILED"
    assert submission.state.value == "FAILED"
    assert submission.attempts == 3
    assert len(uow.manual_metadata_submissions.reports) == 1
    failure = uow.manual_metadata_submissions.reports[0]
    assert failure.outcome.value == "FAILED_BEFORE_WRITE"
    assert failure.failure_code == "DATASETPROPERTIES_UNAVAILABLE"
    assert failure.before_hash is None
    assert failure.write_attempted is False


@pytest.mark.asyncio
async def test_provider_readback_mismatch_is_bounded_retryable_work() -> None:
    submission = _submission()
    document = _csv_document(submission)
    uow = _Uow(submission)
    datahub = _StaleReadbackDataHub()
    service = ManualMetadataApplyService(
        datahub=cast(DataHubGateway, datahub),
        object_store=cast(ObjectStore, _ObjectStore(document)),
        uow_factory=lambda: cast(GovernanceUnitOfWork, uow),
        eligibility=cast(Any, _Eligibility()),
        provider_mutation_lock=cast(Any, _ProviderMutationLock()),
        lease_seconds=60,
        maximum_attempts=3,
    )

    result = await service.run_once(
        workspace_id=submission.workspace_id,
        worker_subject_id=uuid4(),
        request_id="manual-apply-readback-lag",
    )

    assert result.state == "QUEUED"
    assert submission.state.value == "QUEUED"
    assert submission.last_error_code == "DATASETPROPERTIES_READBACK_MISMATCH"
    assert datahub.applied == ["datasetProperties"]
    assert len(uow.manual_metadata_submissions.reports) == 1
    failure = uow.manual_metadata_submissions.reports[0]
    assert failure.outcome.value == "READBACK_MISMATCH"
    assert failure.failure_code == "DATASETPROPERTIES_READBACK_MISMATCH"
    assert failure.expected_hash != failure.observed_hash
    assert failure.write_attempted is True


@pytest.mark.asyncio
async def test_provider_write_rejection_is_retained_as_sanitized_aspect_evidence() -> None:
    submission = _submission()
    document = _csv_document(submission)
    uow = _Uow(submission)
    service = ManualMetadataApplyService(
        datahub=cast(DataHubGateway, _RejectedWriteDataHub()),
        object_store=cast(ObjectStore, _ObjectStore(document)),
        uow_factory=lambda: cast(GovernanceUnitOfWork, uow),
        eligibility=cast(Any, _Eligibility()),
        provider_mutation_lock=cast(Any, _ProviderMutationLock()),
        lease_seconds=60,
        maximum_attempts=3,
    )

    result = await service.run_once(
        workspace_id=submission.workspace_id,
        worker_subject_id=uuid4(),
        request_id="manual-apply-rejected",
    )

    assert result.state == "FAILED"
    failure = uow.manual_metadata_submissions.reports[0]
    assert failure.outcome.value == "WRITE_REJECTED"
    assert failure.failure_code == "DATASETPROPERTIES_FORBIDDEN"
    assert failure.before_hash is not None
    assert failure.expected_hash is not None
    assert failure.observed_hash is None
