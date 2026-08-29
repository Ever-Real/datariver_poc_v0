from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import cast
from uuid import UUID, uuid4
from zipfile import ZipFile

import pytest

from datariver.application.catalog_security import (
    catalog_classification_access_hash,
    catalog_permission_scope_hash,
)
from datariver.application.classification_access import static_classification_access_floor
from datariver.application.dto import (
    CatalogAssetIndex,
    CatalogExportArtifact,
    CatalogExportClaim,
    CatalogExportRecord,
    CatalogExportRequest,
    CatalogPage,
)
from datariver.application.ports import CatalogExportObjectStore, CatalogExportWorkerStore
from datariver.application.services.catalog_export_worker import CatalogExportWorker
from datariver.domain.authz import Action, BuiltinPolicyEngine, Classification, SubjectAttributes
from datariver.infrastructure.db.catalog_export import _claim_can_complete, _claim_is_current
from datariver.infrastructure.db.models.integration import JobAttemptModel, JobModel

NOW = datetime(2026, 7, 17, 4, tzinfo=UTC)
WORKSPACE_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
SUBJECT_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def _subject() -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=SUBJECT_ID,
        workspace_id=WORKSPACE_ID,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function="ENGINEER",
        clearance=Classification.CONFIDENTIAL,
        allowed_actions=frozenset({Action.CATALOG_EXPORT}),
    )


def _claim(
    *,
    snapshot_valid: bool = True,
    format_name: str = "CSV",
    filters: dict[str, str] | None = None,
    query: str = "wafer",
) -> CatalogExportClaim:
    subject = _subject()
    access = static_classification_access_floor()
    export_id = uuid4()
    return CatalogExportClaim(
        export=CatalogExportRecord(
            export_id=export_id,
            workspace_id=WORKSPACE_ID,
            job_id=uuid4(),
            requested_by=SUBJECT_ID,
            request=CatalogExportRequest(
                query=query,
                filters=filters or {},
                format=format_name,
            ),
            request_hash="a" * 64,
            permission_scope_hash=catalog_permission_scope_hash(subject),
            classification_access_hash=catalog_classification_access_hash(access),
            builtin_policy_version=BuiltinPolicyEngine.policy_version,
            classification_policy_id=None,
            classification_policy_hash=None,
            classification_policy_version=None,
            authorization_generation=None,
            source_projection_version=7,
            classification_ceiling=Classification.CONFIDENTIAL,
            csv_safety_version="xlsx-safe-v1" if format_name == "XLSX" else "csv-safe-v1",
            display_name=f"catalog-export-{export_id}.{format_name.lower()}",
            mime=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                if format_name == "XLSX"
                else "text/csv; charset=utf-8"
            ),
            job_state="RUNNING",
            last_error_code=None,
            row_count=None,
            size_bytes=None,
            content_sha256=None,
            provider_checksum=None,
            object_bucket=None,
            object_key=None,
            created_at=NOW,
            completed_at=None,
            access_until=NOW + timedelta(hours=1),
        ),
        attempt_id=uuid4(),
        attempt_no=1,
        subject=subject,
        access=access,
        snapshot_valid=snapshot_valid,
    )


def _asset(name: str) -> CatalogAssetIndex:
    return CatalogAssetIndex(
        asset_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        external_urn=f"urn:li:dataset:{name}",
        asset_type="DATASET",
        name=name,
        description=f"{name} description",
        platform="postgres",
        domain_id=None,
        system_id=None,
        owner_department_id=None,
        classification=Classification.INTERNAL,
        lifecycle="ACTIVE",
        source_version="v1",
        observed_at=NOW,
        database_name="core",
        schema_name="semiconductor",
    )


class FakeWorkerStore:
    def __init__(
        self,
        claim: CatalogExportClaim,
        *,
        pages: tuple[CatalogPage, ...] = (),
        current_after_write: bool = True,
    ) -> None:
        self.claim = claim
        self.pages = list(pages)
        self.current_after_write = current_after_write
        self.completed: list[dict[str, object]] = []
        self.failed: list[dict[str, object]] = []
        self.read_cursors: list[str | None] = []
        self.read_requests: list[CatalogExportRequest] = []

    async def claim_next(self, **_: object) -> CatalogExportClaim | None:
        return self.claim

    async def read_page(self, **values: object) -> CatalogPage:
        self.read_cursors.append(cast(str | None, values.get("cursor")))
        read_claim = cast(CatalogExportClaim, values["claim"])
        self.read_requests.append(read_claim.export.request)
        return self.pages.pop(0)

    async def snapshot_is_current(self, **_: object) -> bool:
        return self.current_after_write

    async def mark_completed(self, **values: object) -> None:
        self.completed.append(values)

    async def mark_failed(self, **values: object) -> None:
        self.failed.append(values)


class FakeExportObjects:
    def __init__(self) -> None:
        self.content = b""
        self.deleted: list[tuple[str, str]] = []
        self.written_object_key: str | None = None
        self.content_type: str | None = None

    async def write_export(
        self,
        *,
        object_key: str,
        chunks: AsyncIterator[bytes],
        content_type: str,
        **_: object,
    ) -> CatalogExportArtifact:
        self.written_object_key = object_key
        self.content_type = content_type
        content = bytearray()
        async for chunk in chunks:
            content.extend(chunk)
        self.content = bytes(content)
        return CatalogExportArtifact(
            size_bytes=len(self.content),
            content_sha256=hashlib.sha256(self.content).hexdigest(),
            provider_checksum="etag:test",
        )

    async def delete_export(self, *, bucket: str, object_key: str) -> None:
        self.deleted.append((bucket, object_key))


def _worker(
    store: FakeWorkerStore,
    objects: FakeExportObjects,
    *,
    maximum_rows: int = 100,
) -> CatalogExportWorker:
    return CatalogExportWorker(
        store=cast(CatalogExportWorkerStore, store),
        object_store=cast(CatalogExportObjectStore, objects),
        export_bucket="exports",
        worker_id="worker-1",
        system_actor_id=uuid4(),
        lease_seconds=300,
        maximum_attempts=4,
        page_size=1000,
        maximum_rows=maximum_rows,
        maximum_bytes=1024 * 1024,
    )


@pytest.mark.asyncio
async def test_worker_streams_fixed_csv_and_completes_verified_artifact() -> None:
    page = CatalogPage(
        items=(_asset("wafer"), _asset("yield")),
        next_cursor=None,
        observed_at=NOW,
    )
    store = FakeWorkerStore(_claim(), pages=(page,))
    objects = FakeExportObjects()

    assert await _worker(store, objects).run_once()

    assert objects.content.startswith(b"asset_id,external_urn,platform")
    assert b"wafer" in objects.content and b"yield" in objects.content
    assert len(store.completed) == 1
    assert store.completed[0]["row_count"] == 2
    assert objects.written_object_key is not None
    assert f"/attempts/{store.claim.attempt_id}/" in objects.written_object_key
    assert store.failed == []


@pytest.mark.asyncio
@pytest.mark.parametrize("format_name", ["CSV", "XLSX"])
async def test_worker_exports_every_authorized_page_in_canonical_cursor_order(
    format_name: str,
) -> None:
    store = FakeWorkerStore(
        _claim(
            format_name=format_name,
            filters={"platform": "generic-platform", "schema_name": "generic-schema"},
            query="synthetic-asset",
        ),
        pages=(
            CatalogPage(items=(_asset("first"),), next_cursor="next-page", observed_at=NOW),
            CatalogPage(items=(_asset("second"),), next_cursor=None, observed_at=NOW),
        ),
    )
    objects = FakeExportObjects()

    assert await _worker(store, objects).run_once()

    assert store.read_cursors == [None, "next-page"]
    assert [request.document() for request in store.read_requests] == [
        {
            "query": "synthetic-asset",
            "filters": {"platform": "generic-platform", "schema_name": "generic-schema"},
            "sort": "NAME_ASC",
            "format": format_name,
        },
    ] * 2
    assert store.completed[0]["row_count"] == 2
    if format_name == "CSV":
        assert b"first" in objects.content and b"second" in objects.content
        assert objects.content_type == "text/csv; charset=utf-8"
    else:
        with ZipFile(BytesIO(objects.content)) as workbook:
            sheet = workbook.read("xl/worksheets/sheet1.xml")
        assert b"first" in sheet and b"second" in sheet
        assert objects.content_type == (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )


@pytest.mark.asyncio
async def test_worker_generates_formula_safe_xlsx_and_completes_verified_artifact() -> None:
    page = CatalogPage(items=(_asset("=formula"),), next_cursor=None, observed_at=NOW)
    store = FakeWorkerStore(_claim(format_name="XLSX"), pages=(page,))
    objects = FakeExportObjects()

    assert await _worker(store, objects).run_once()

    with ZipFile(BytesIO(objects.content)) as workbook:
        sheet = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "asset_id" in sheet
    assert "'=formula" in sheet
    assert objects.written_object_key is not None and objects.written_object_key.endswith(".xlsx")
    assert store.completed[0]["row_count"] == 1


def test_only_the_current_unexpired_attempt_can_complete() -> None:
    claim = _claim()
    job = JobModel(
        id=claim.export.job_id,
        workspace_id=WORKSPACE_ID,
        job_type="CATALOG_EXPORT",
        causation_id=claim.export.export_id,
        state="RUNNING",
        requested_by=SUBJECT_ID,
        progress={},
        result_ref=None,
        lease_until=NOW + timedelta(minutes=5),
        attempts=claim.attempt_no,
        last_error_code=None,
        version=1,
    )
    attempt = JobAttemptModel(
        id=claim.attempt_id,
        workspace_id=WORKSPACE_ID,
        job_id=claim.export.job_id,
        attempt_no=claim.attempt_no,
        worker_id="worker-1",
        state="RUNNING",
        error_class=None,
        external_response_hash=None,
        started_at=NOW,
        finished_at=None,
    )

    assert _claim_is_current(job=job, attempt=attempt, claim=claim)
    assert _claim_can_complete(job=job, attempt=attempt, claim=claim, now=NOW)

    job.attempts += 1
    assert not _claim_is_current(job=job, attempt=attempt, claim=claim)
    job.attempts = claim.attempt_no
    job.lease_until = NOW
    assert not _claim_can_complete(job=job, attempt=attempt, claim=claim, now=NOW)


@pytest.mark.asyncio
async def test_worker_rejects_stale_snapshot_before_object_write() -> None:
    store = FakeWorkerStore(_claim(snapshot_valid=False))
    objects = FakeExportObjects()

    assert await _worker(store, objects).run_once()

    assert objects.content == b""
    assert store.completed == []
    assert store.failed[0]["error_code"] == "SOURCE_OR_POLICY_SNAPSHOT_STALE"
    assert store.failed[0]["retryable"] is False


@pytest.mark.asyncio
async def test_worker_deletes_private_artifact_if_snapshot_changes_before_completion() -> None:
    page = CatalogPage(items=(_asset("wafer"),), next_cursor=None, observed_at=NOW)
    store = FakeWorkerStore(_claim(), pages=(page,), current_after_write=False)
    objects = FakeExportObjects()

    assert await _worker(store, objects).run_once()

    assert store.completed == []
    assert store.failed[0]["error_code"] == "conflict"
    assert len(objects.deleted) == 1


@pytest.mark.asyncio
async def test_worker_fails_closed_when_row_limit_is_exceeded() -> None:
    page = CatalogPage(
        items=(_asset("first"), _asset("second")),
        next_cursor=None,
        observed_at=NOW,
    )
    store = FakeWorkerStore(_claim(), pages=(page,))
    objects = FakeExportObjects()

    assert await _worker(store, objects, maximum_rows=1).run_once()

    assert store.completed == []
    assert store.failed[0]["error_code"] == "EXPORT_ROW_LIMIT"
    assert store.failed[0]["retryable"] is False


@pytest.mark.asyncio
async def test_worker_does_not_retry_a_csv_safety_rejection() -> None:
    page = CatalogPage(items=(_asset("invalid\x00name"),), next_cursor=None, observed_at=NOW)
    store = FakeWorkerStore(_claim(), pages=(page,))
    objects = FakeExportObjects()

    assert await _worker(store, objects).run_once()

    assert store.completed == []
    assert store.failed[0]["error_code"] == "EXPORT_CSV_INVALID_VALUE"
    assert store.failed[0]["retryable"] is False
