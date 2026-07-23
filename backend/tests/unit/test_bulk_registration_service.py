# ruff: noqa: E501 -- OOXML fixture URIs are protocol literals and must not be wrapped.
from __future__ import annotations

import hashlib
import io
import zipfile
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import replace
from uuid import uuid4

import pytest

from datariver.application.dto import ObjectMetadata
from datariver.application.errors import ExternalDependencyError
from datariver.application.services.bulk_registration import (
    BulkPreparationClaim,
    BulkRegistrationPreparationService,
)
from datariver.application.typed_upload_parser import (
    DatasetDescriptionCandidateDraft,
    DatasetDescriptionParseSummary,
)
from datariver.application.typed_upload_profiles import DATASET_DESCRIPTION_XLSX_V1
from datariver.domain.registration import UploadContentProfile
from datariver.domain.registration_worker import (
    RegistrationWorkerCallIdentity,
    RegistrationWorkerCallReplay,
)


class FakeObjectStore:
    def __init__(self, value: bytes, *, unavailable: bool = False) -> None:
        self.value = value
        self.unavailable = unavailable
        self.head_calls = 0

    async def head_object(self, *, bucket: str, object_key: str) -> ObjectMetadata:
        self.head_calls += 1
        if self.unavailable:
            raise ExternalDependencyError(
                "unavailable",
                dependency="object_store",
                retryable=True,
                provider_code="SLOW_DOWN",
            )
        return ObjectMetadata(
            bucket=bucket,
            object_key=object_key,
            size_bytes=len(self.value),
            content_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            etag="test-etag",
            checksum_sha256=None,
            user_metadata={},
        )

    async def iter_object_chunks(
        self, *, bucket: str, object_key: str, chunk_size: int = 1024 * 1024
    ) -> AsyncIterator[bytes]:
        del bucket, object_key, chunk_size
        for offset in range(0, len(self.value), 17):
            yield self.value[offset : offset + 17]


class FakeStore:
    def __init__(self, claim: BulkPreparationClaim | None, *, publish_current: bool = True) -> None:
        self.claim = claim
        self.publish_current = publish_current
        self.published: tuple[DatasetDescriptionCandidateDraft, ...] = ()
        self.failure: tuple[str, bool] | None = None
        self.worker_results: dict[str, dict[str, object]] = {}

    async def claim_next(
        self,
        *,
        workspace_id: object,
        worker_subject_id: object,
        lease_seconds: int,
        maximum_attempts: int,
        run_call: RegistrationWorkerCallIdentity | None = None,
    ) -> BulkPreparationClaim | RegistrationWorkerCallReplay | None:
        del workspace_id, worker_subject_id, lease_seconds, maximum_attempts
        if run_call is not None and run_call.key_hash in self.worker_results:
            return RegistrationWorkerCallReplay(result=dict(self.worker_results[run_call.key_hash]))
        value, self.claim = self.claim, None
        if value is None and run_call is not None:
            result: dict[str, object] = {
                "processed": False,
                "preparation_id": None,
                "state": None,
                "item_count": None,
            }
            self.worker_results[run_call.key_hash] = result
            return RegistrationWorkerCallReplay(result=result)
        if value is not None and run_call is not None:
            value = replace(value, run_call=run_call)
        return value

    async def publish(
        self,
        *,
        claim: BulkPreparationClaim,
        object_metadata: ObjectMetadata,
        summary: DatasetDescriptionParseSummary,
        candidates: Callable[[], Iterator[DatasetDescriptionCandidateDraft]],
    ) -> bool:
        del object_metadata
        self.published = tuple(candidates())
        if claim.run_call is not None:
            self.worker_results[claim.run_call.key_hash] = {
                "processed": True,
                "preparation_id": str(claim.preparation_id),
                "state": "READY" if self.publish_current else "SUPERSEDED",
                "item_count": summary.item_count if self.publish_current else None,
            }
        return self.publish_current

    async def mark_failed(
        self,
        *,
        claim: BulkPreparationClaim,
        error_code: str,
        retryable: bool,
        maximum_attempts: int,
    ) -> bool:
        del maximum_attempts
        self.failure = (error_code, retryable)
        if claim.run_call is not None:
            self.worker_results[claim.run_call.key_hash] = {
                "processed": True,
                "preparation_id": str(claim.preparation_id),
                "state": "QUEUED" if retryable else "FAILED",
                "item_count": None,
            }
        return True


def _xlsx(*, formula: bool = False) -> bytes:
    asset_id = uuid4()
    rows = (
        (
            "asset_id",
            "platform",
            "database_name",
            "schema_name",
            "table_name",
            "description",
        ),
        (str(asset_id), "postgres", "fab", "public", "wafer", "bulk text"),
    )
    row_xml: list[str] = []
    for row_number, row in enumerate(rows, start=1):
        cells = []
        for column, value in enumerate(row, start=1):
            reference = f"{chr(64 + column)}{row_number}"
            formula_xml = "<f>1+1</f>" if formula and reference == "F2" else ""
            cells.append(
                f'<c r="{reference}" t="inlineStr">{formula_xml}<is><t>{value}</t></is></c>'
            )
        row_xml.append(f'<row r="{row_number}">{"".join(cells)}</row>')
    worksheet = (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(row_xml)}</sheetData></worksheet>"
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr(
            "[Content_Types].xml",
            """<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>""",
        )
        package.writestr(
            "xl/workbook.xml",
            """<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="dataset_descriptions" sheetId="1" r:id="rId1"/></sheets></workbook>""",
        )
        package.writestr(
            "xl/_rels/workbook.xml.rels",
            """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>""",
        )
        package.writestr("xl/worksheets/sheet1.xml", worksheet)
    return output.getvalue()


def _claim(value: bytes, *, attempt: int = 1) -> BulkPreparationClaim:
    return BulkPreparationClaim(
        workspace_id=uuid4(),
        preparation_id=uuid4(),
        upload_id=uuid4(),
        requested_by=uuid4(),
        content_profile=UploadContentProfile.DATASET_DESCRIPTION_XLSX_V1,
        source_manifest_version=3,
        source_sha256=hashlib.sha256(value).hexdigest(),
        configuration_hash=DATASET_DESCRIPTION_XLSX_V1.configuration_hash,
        source_bucket="accepted",
        source_object_key="accepted/test.xlsx",
        source_size_bytes=len(value),
        source_content_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        scanner_version="integrity-format-v1",
        lease_token=uuid4(),
        attempt=attempt,
    )


@pytest.mark.asyncio
async def test_service_publishes_xlsx_candidates_only_after_complete_parse() -> None:
    value = _xlsx()
    store = FakeStore(_claim(value))
    service = BulkRegistrationPreparationService(
        store=store,
        object_store=FakeObjectStore(value),
        lease_seconds=300,
        maximum_attempts=4,
    )

    result = await service.run_once(workspace_id=uuid4(), worker_subject_id=uuid4())

    assert result.processed is True
    assert result.state == "READY"
    assert result.item_count == 1
    assert len(store.published) == 1
    assert store.published[0].proposed_description == "bulk text"
    assert store.failure is None


@pytest.mark.asyncio
async def test_service_marks_formula_workbook_terminal_without_publishing() -> None:
    value = _xlsx(formula=True)
    store = FakeStore(_claim(value))
    service = BulkRegistrationPreparationService(
        store=store,
        object_store=FakeObjectStore(value),
        lease_seconds=300,
        maximum_attempts=4,
    )

    result = await service.run_once(workspace_id=uuid4(), worker_subject_id=uuid4())

    assert result.state == "FAILED"
    assert store.published == ()
    assert store.failure == ("INVALID_XLSX_PACKAGE", False)


@pytest.mark.asyncio
async def test_service_requeues_retryable_object_store_failure() -> None:
    value = _xlsx()
    store = FakeStore(_claim(value))
    service = BulkRegistrationPreparationService(
        store=store,
        object_store=FakeObjectStore(value, unavailable=True),
        lease_seconds=300,
        maximum_attempts=4,
    )

    result = await service.run_once(workspace_id=uuid4(), worker_subject_id=uuid4())

    assert result.state == "QUEUED"
    assert store.failure == ("external_dependency_error", True)


@pytest.mark.asyncio
async def test_service_reports_superseded_fence_without_ready_claim() -> None:
    value = _xlsx()
    store = FakeStore(_claim(value), publish_current=False)
    service = BulkRegistrationPreparationService(
        store=store,
        object_store=FakeObjectStore(value),
        lease_seconds=300,
        maximum_attempts=4,
    )

    result = await service.run_once(workspace_id=uuid4(), worker_subject_id=uuid4())

    assert result.state == "SUPERSEDED"
    assert result.item_count is None


@pytest.mark.asyncio
async def test_completed_bulk_worker_call_replays_without_a_second_parse() -> None:
    value = _xlsx()
    object_store = FakeObjectStore(value)
    store = FakeStore(_claim(value))
    service = BulkRegistrationPreparationService(
        store=store,
        object_store=object_store,
        lease_seconds=300,
        maximum_attempts=4,
    )
    call = RegistrationWorkerCallIdentity(
        operation="registration.bulk-preparation.execute-run.v1",
        key_hash="5" * 64,
        request_hash="6" * 64,
        worker_subject_id=uuid4(),
    )

    first = await service.run_once(
        workspace_id=uuid4(),
        worker_subject_id=call.worker_subject_id,
        run_call=call,
    )
    replay = await service.run_once(
        workspace_id=uuid4(),
        worker_subject_id=call.worker_subject_id,
        run_call=call,
    )

    assert replay == first
    assert object_store.head_calls == 1
    assert len(store.published) == 1


@pytest.mark.asyncio
async def test_no_work_bulk_call_does_not_consume_later_work_on_replay() -> None:
    value = _xlsx()
    store = FakeStore(None)
    service = BulkRegistrationPreparationService(
        store=store,
        object_store=FakeObjectStore(value),
        lease_seconds=300,
        maximum_attempts=4,
    )
    call = RegistrationWorkerCallIdentity(
        operation="registration.bulk-preparation.execute-run.v1",
        key_hash="7" * 64,
        request_hash="8" * 64,
        worker_subject_id=uuid4(),
    )

    empty = await service.run_once(
        workspace_id=uuid4(),
        worker_subject_id=call.worker_subject_id,
        run_call=call,
    )
    store.claim = _claim(value)
    replay = await service.run_once(
        workspace_id=uuid4(),
        worker_subject_id=call.worker_subject_id,
        run_call=call,
    )

    assert replay == empty
    assert empty.processed is False
    assert store.claim is not None
