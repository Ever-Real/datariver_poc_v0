# ruff: noqa: E501 -- OOXML fixture URIs are protocol literals and must not be wrapped.
from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from datariver.application.catalog_metadata_upload_parser import (
    CatalogMetadataParseSummary,
    compile_catalog_metadata_candidates,
)
from datariver.application.dto import ObjectMetadata
from datariver.application.errors import ExternalDependencyError
from datariver.application.services.bulk_registration import (
    AttemptCandidateSpool,
    BulkCandidateDraft,
    BulkParseSummary,
    BulkPreparationClaim,
    BulkRegistrationPreparationService,
)
from datariver.application.typed_upload_parser import (
    DatasetDescriptionCandidateDraft,
    TypedUploadParseError,
    TypedUploadParseFailureCode,
)
from datariver.application.typed_upload_profiles import (
    CATALOG_METADATA_ROWS_CSV_V1,
    CATALOG_METADATA_ROWS_XLSX_V1,
    typed_profile_definition,
)
from datariver.domain.registration import UploadContentProfile
from datariver.domain.registration_worker import (
    RegistrationWorkerCallIdentity,
    RegistrationWorkerCallReplay,
)


class FakeObjectStore:
    def __init__(
        self,
        value: bytes,
        *,
        content_type: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        unavailable: bool = False,
        chunk_width: int = 17,
    ) -> None:
        self.value = value
        self.content_type = content_type
        self.unavailable = unavailable
        self.chunk_width = chunk_width
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
            content_type=self.content_type,
            etag="test-etag",
            checksum_sha256=None,
            user_metadata={},
        )

    async def iter_object_chunks(
        self, *, bucket: str, object_key: str, chunk_size: int = 1024 * 1024
    ) -> AsyncIterator[bytes]:
        del bucket, object_key, chunk_size
        for offset in range(0, len(self.value), self.chunk_width):
            yield self.value[offset : offset + self.chunk_width]


class FakeStore:
    def __init__(self, claim: BulkPreparationClaim | None, *, publish_current: bool = True) -> None:
        self.claim = claim
        self.publish_current = publish_current
        self.published: tuple[BulkCandidateDraft, ...] = ()
        self.summary: BulkParseSummary | None = None
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
        summary: BulkParseSummary,
        candidates: Callable[[], Iterator[BulkCandidateDraft]],
    ) -> bool:
        del object_metadata
        self.summary = summary
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


def _workbook(
    rows: tuple[tuple[str, ...], ...],
    *,
    formula_at: str | None = None,
) -> bytes:
    row_xml: list[str] = []
    for row_number, row in enumerate(rows, start=1):
        cells = []
        for column, value in enumerate(row, start=1):
            reference = f"{chr(64 + column)}{row_number}"
            formula_xml = "<f>1+1</f>" if formula_at == reference else ""
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
    return _workbook(
        rows,
        formula_at="F2" if formula else None,
    )


def _catalog_rows() -> tuple[tuple[str, ...], ...]:
    asset_id = UUID("00000000-0000-4000-8000-000000000101")
    return (
        CATALOG_METADATA_ROWS_CSV_V1.headers,
        (
            "COLUMN_DESCRIPTION",
            str(asset_id),
            "postgres",
            "fab",
            "public",
            "wafer",
            "lot_id",
            "SET",
            "lot description",
            "",
        ),
        (
            "COLUMN_DESCRIPTION",
            str(asset_id),
            "postgres",
            "fab",
            "public",
            "wafer",
            "obsolete",
            "CLEAR",
            "",
            "",
        ),
        (
            "DATASET_TAG",
            str(asset_id),
            "postgres",
            "fab",
            "public",
            "wafer",
            "",
            "ADD",
            "",
            "00000000-0000-4000-8000-000000000201",
        ),
    )


def _catalog_csv() -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerows(_catalog_rows())
    return output.getvalue().encode()


def _catalog_xlsx() -> bytes:
    return _workbook(_catalog_rows())


def _claim(
    value: bytes,
    *,
    attempt: int = 1,
    content_profile: UploadContentProfile = UploadContentProfile.DATASET_DESCRIPTION_XLSX_V1,
) -> BulkPreparationClaim:
    definition = typed_profile_definition(content_profile)
    return BulkPreparationClaim(
        workspace_id=uuid4(),
        preparation_id=uuid4(),
        upload_id=uuid4(),
        requested_by=uuid4(),
        content_profile=content_profile,
        source_manifest_version=3,
        source_sha256=hashlib.sha256(value).hexdigest(),
        configuration_hash=definition.configuration_hash,
        source_bucket="accepted",
        source_object_key=f"accepted/test{definition.filename_suffix}",
        source_size_bytes=len(value),
        source_content_type=definition.content_type,
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
    candidate = store.published[0]
    assert isinstance(candidate, DatasetDescriptionCandidateDraft)
    assert candidate.proposed_description == "bulk text"
    assert store.failure is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content_profile", "value_factory"),
    [
        (UploadContentProfile.CATALOG_METADATA_ROWS_CSV_V1, _catalog_csv),
        (UploadContentProfile.CATALOG_METADATA_ROWS_XLSX_V1, _catalog_xlsx),
    ],
)
async def test_service_preserves_v3_rows_groups_and_summary_through_bounded_spool(
    content_profile: UploadContentProfile,
    value_factory: Callable[[], bytes],
) -> None:
    value = value_factory()
    claim = _claim(value, content_profile=content_profile)
    definition = typed_profile_definition(content_profile)
    store = FakeStore(claim)
    service = BulkRegistrationPreparationService(
        store=store,
        object_store=FakeObjectStore(value, content_type=definition.content_type),
        lease_seconds=300,
        maximum_attempts=4,
    )

    result = await service.run_once(workspace_id=uuid4(), worker_subject_id=uuid4())
    expected = compile_catalog_metadata_candidates(
        workspace_id=claim.workspace_id,
        rows=[(ordinal, row) for ordinal, row in enumerate(_catalog_rows()[1:], start=1)],
        definition=definition,
    )

    assert result.processed is True
    assert result.state == "READY"
    assert result.item_count == 3
    assert store.published == expected
    assert isinstance(store.summary, CatalogMetadataParseSummary)
    assert store.summary.item_count == 3
    assert store.summary.candidate_count == 2
    assert [len(candidate.rows) for candidate in expected] == [2, 1]
    assert store.failure is None


@pytest.mark.asyncio
async def test_attempt_spool_round_trips_v2_and_nested_v3_and_enforces_byte_budget() -> None:
    workspace_id = UUID("00000000-0000-4000-8000-000000000001")
    definition = CATALOG_METADATA_ROWS_XLSX_V1
    catalog_candidates = compile_catalog_metadata_candidates(
        workspace_id=workspace_id,
        rows=[(ordinal, row) for ordinal, row in enumerate(_catalog_rows()[1:], start=1)],
        definition=definition,
    )
    v2_candidate = DatasetDescriptionCandidateDraft(
        workspace_id=workspace_id,
        ordinal=1,
        target_asset_id=UUID("00000000-0000-4000-8000-000000000301"),
        platform="postgres",
        database_name="fab",
        schema_name="public",
        table_name="legacy",
        proposed_description="legacy description",
        submitted_identity_hash="a" * 64,
        candidate_hash="b" * 64,
    )

    with AttemptCandidateSpool(maximum_bytes=1024 * 1024) as spool:
        await spool.append(v2_candidate)
        for candidate in catalog_candidates:
            await spool.append(candidate)
        spool.seal()
        assert tuple(spool.iter_candidates()) == (v2_candidate, *catalog_candidates)

    with AttemptCandidateSpool(maximum_bytes=1) as bounded:
        with pytest.raises(TypedUploadParseError, match="bounded size") as captured:
            await bounded.append(catalog_candidates[0])
    assert captured.value.failure_code is TypedUploadParseFailureCode.EVIDENCE_TOO_LARGE


@pytest.mark.asyncio
async def test_service_accepts_parser_valid_v3_boundary_that_exceeds_legacy_2x_spool() -> None:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(CATALOG_METADATA_ROWS_CSV_V1.headers)
    for ordinal in range(1, 1_601):
        writer.writerow(
            (
                "TABLE_DESCRIPTION",
                f"00000000-0000-4000-8000-{ordinal:012d}",
                "postgres",
                "fab",
                "public",
                f"table_{ordinal}",
                "",
                "SET",
                "\\" * 10_000,
                "",
            )
        )
    value = output.getvalue().encode()
    assert len(value) <= CATALOG_METADATA_ROWS_CSV_V1.maximum_file_bytes
    claim = _claim(
        value,
        content_profile=UploadContentProfile.CATALOG_METADATA_ROWS_CSV_V1,
    )
    store = FakeStore(claim)
    service = BulkRegistrationPreparationService(
        store=store,
        object_store=FakeObjectStore(
            value,
            content_type=CATALOG_METADATA_ROWS_CSV_V1.content_type,
            chunk_width=64 * 1024,
        ),
        lease_seconds=300,
        maximum_attempts=4,
    )

    result = await service.run_once(workspace_id=uuid4(), worker_subject_id=uuid4())

    assert result.state == "READY"
    assert result.item_count == 1_600
    assert len(store.published) == 1_600
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
