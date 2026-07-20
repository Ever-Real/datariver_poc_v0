from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, cast
from uuid import uuid4

import pytest

from datariver.application.dto import DataHubApplyReceipt, DataHubAspectSnapshot
from datariver.application.ports import DataHubGateway, GovernanceUnitOfWork, ObjectStore
from datariver.application.services.manual_metadata_apply import ManualMetadataApplyService
from datariver.domain.common import DomainEvent, canonical_json_hash
from datariver.domain.manual_metadata import ManualColumnMetadata, ManualMetadataSubmission


class _ObjectStore:
    def __init__(self, document: bytes) -> None:
        self.document = document

    async def iter_object_chunks(self, **_: object) -> AsyncIterator[bytes]:
        yield self.document


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
                        "glossaryTerms": {"terms": []},
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


class _Repository:
    def __init__(self, submission: ManualMetadataSubmission) -> None:
        self.submission = submission

    async def claim_next(self, **kwargs: object) -> ManualMetadataSubmission | None:
        if self.submission.state.value != "QUEUED":
            return None
        self.submission.claim_for_apply(
            now=cast(datetime, kwargs["now"]),
            lease_seconds=cast(int, kwargs["lease_seconds"]),
        )
        return self.submission

    async def get(self, **_: object) -> ManualMetadataSubmission:
        return self.submission

    async def save(self, submission: ManualMetadataSubmission) -> None:
        self.submission = submission


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


@pytest.mark.asyncio
async def test_airflow_apply_verifies_csv_then_merges_all_typed_aspects() -> None:
    submission = _submission()
    document = _csv_document(submission)
    uow = _Uow(submission)
    datahub = _DataHub()
    service = ManualMetadataApplyService(
        datahub=cast(DataHubGateway, datahub),
        object_store=cast(ObjectStore, _ObjectStore(document)),
        uow_factory=lambda: cast(GovernanceUnitOfWork, uow),
        lease_seconds=60,
        maximum_attempts=3,
    )

    result = await service.run_once(
        workspace_id=submission.workspace_id,
        worker_subject_id=uuid4(),
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
    assert datahub.documents["globalTags"]["tags"] == [{"tag": "urn:li:tag:tier%3Agold"}]
    wafer_id = datahub.documents["schemaMetadata"]["fields"][0]
    assert wafer_id["description"] == "Business identifier."
    assert wafer_id["globalTags"]["tags"] == [{"tag": "urn:li:tag:identifier"}]
    assert [event.event_type for event in uow.outbox.events] == [
        "registration.manual_metadata.applied.v1"
    ]


@pytest.mark.asyncio
async def test_airflow_apply_never_calls_datahub_when_the_csv_receipt_hash_is_wrong() -> None:
    submission = _submission()
    uow = _Uow(submission)
    datahub = _DataHub()
    service = ManualMetadataApplyService(
        datahub=cast(DataHubGateway, datahub),
        object_store=cast(ObjectStore, _ObjectStore(b"tampered")),
        uow_factory=lambda: cast(GovernanceUnitOfWork, uow),
        lease_seconds=60,
        maximum_attempts=3,
    )

    result = await service.run_once(
        workspace_id=submission.workspace_id,
        worker_subject_id=uuid4(),
    )

    assert result.state == "FAILED"
    assert submission.state.value == "FAILED"
    assert datahub.applied == []
