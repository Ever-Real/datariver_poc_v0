from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from datariver.application.catalog_security import (
    catalog_classification_access_hash,
    catalog_permission_scope_hash,
)
from datariver.application.classification_access import (
    ClassificationAccessResolver,
    static_classification_access_floor,
)
from datariver.application.dto import CatalogExportRecord, CatalogExportRequest, ObjectMetadata
from datariver.application.ports import (
    CatalogExportStore,
    CatalogWatermarkReader,
    DecisionWriter,
    ObjectStore,
)
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.catalog_export import CatalogExportService
from datariver.domain.authz import (
    Action,
    BuiltinPolicyEngine,
    Classification,
    Decision,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ConflictError, ForbiddenError, ValidationError

NOW = datetime(2026, 7, 17, 3, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-4111-8111-111111111111")
SUBJECT_ID = UUID("22222222-2222-4222-8222-222222222222")


class FakeDecisionWriter:
    def __init__(self) -> None:
        self.decisions: list[Decision] = []

    async def append_decision(self, *, decision: Decision, **_: object) -> None:
        self.decisions.append(decision)


class EmptyClassificationReader:
    async def read_candidate(self, **_: object) -> None:
        return None


class FakeWatermark:
    def __init__(self, value: int = 7) -> None:
        self.value = value

    async def get_search_watermark(self, *, workspace_id: UUID) -> int:
        assert workspace_id == WORKSPACE_ID
        return self.value


class FakeExportStore:
    def __init__(self) -> None:
        self.created: dict[str, Any] | None = None
        self.record: CatalogExportRecord | None = None

    async def create(self, **values: Any) -> CatalogExportRecord:
        self.created = values
        self.record = _record(
            request=values["request"],
            request_hash=values["request_hash"],
            permission_scope_hash=values["permission_scope_hash"],
            classification_access_hash=values["classification_access_hash"],
            source_projection_version=values["source_projection_version"],
            job_state="QUEUED",
        )
        return self.record

    async def get_owned(self, **_: object) -> CatalogExportRecord | None:
        return self.record


class FakeObjectStore:
    def __init__(self) -> None:
        self.presigned = False
        self.metadata = ObjectMetadata(
            bucket="exports",
            object_key="exports/file.csv",
            size_bytes=10,
            content_type="text/csv; charset=utf-8",
            etag="provider-etag",
            checksum_sha256=None,
            user_metadata={},
        )

    async def head_object(self, **_: object) -> ObjectMetadata:
        return self.metadata

    async def presign_download(self, **_: object) -> str:
        self.presigned = True
        return "https://objects.example.invalid/presigned"


def _subject(
    *,
    clearance: Classification = Classification.CONFIDENTIAL,
    export_allowed: bool = True,
) -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=SUBJECT_ID,
        workspace_id=WORKSPACE_ID,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function="ENGINEER",
        clearance=clearance,
        allowed_actions=frozenset({Action.CATALOG_EXPORT}) if export_allowed else frozenset(),
    )


def _record(
    *,
    request: CatalogExportRequest | None = None,
    request_hash: str = "a" * 64,
    permission_scope_hash: str | None = None,
    classification_access_hash: str | None = None,
    source_projection_version: int = 7,
    job_state: str = "COMPLETED",
) -> CatalogExportRecord:
    subject = _subject()
    access = static_classification_access_floor()
    return CatalogExportRecord(
        export_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        job_id=uuid4(),
        requested_by=SUBJECT_ID,
        request=request or CatalogExportRequest(query="wafer", filters={}),
        request_hash=request_hash,
        permission_scope_hash=permission_scope_hash or catalog_permission_scope_hash(subject),
        classification_access_hash=(
            classification_access_hash or catalog_classification_access_hash(access)
        ),
        builtin_policy_version=BuiltinPolicyEngine.policy_version,
        classification_policy_id=None,
        classification_policy_hash=None,
        classification_policy_version=None,
        authorization_generation=None,
        source_projection_version=source_projection_version,
        classification_ceiling=Classification.CONFIDENTIAL,
        csv_safety_version="csv-safe-v1",
        display_name="catalog-export.csv",
        mime="text/csv; charset=utf-8",
        job_state=job_state,
        last_error_code=None,
        row_count=1,
        size_bytes=10,
        content_sha256="b" * 64,
        provider_checksum="etag:provider-etag",
        object_bucket="exports",
        object_key="exports/file.csv",
        created_at=NOW,
        completed_at=NOW,
        access_until=NOW + timedelta(hours=1),
    )


def _service(
    *,
    store: FakeExportStore,
    watermark: FakeWatermark | None = None,
    object_store: FakeObjectStore | None = None,
    worker_enabled: bool = True,
) -> tuple[CatalogExportService, FakeDecisionWriter, FakeObjectStore]:
    decisions = FakeDecisionWriter()
    objects = object_store or FakeObjectStore()
    service = CatalogExportService(
        store=cast(CatalogExportStore, store),
        watermark=cast(CatalogWatermarkReader, watermark or FakeWatermark()),
        classification_access=ClassificationAccessResolver(EmptyClassificationReader()),
        authorization=AuthorizationService(decision_writer=cast(DecisionWriter, decisions)),
        object_store=cast(ObjectStore, objects),
        minimum_query_length=2,
        policy_version=BuiltinPolicyEngine.policy_version,
        access_ttl_seconds=3600,
        download_ttl_seconds=60,
        worker_enabled=worker_enabled,
    )
    return service, decisions, objects


@pytest.mark.asyncio
async def test_export_create_binds_normalized_request_and_security_snapshot() -> None:
    store = FakeExportStore()
    service, decisions, _ = _service(store=store)

    record = await service.create(
        subject=_subject(),
        request=CatalogExportRequest(
            query="  wafer   yield  ",
            filters={"platform": " postgres ", "classification": "INTERNAL"},
        ),
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request-1",
        idempotency_key="idempotency-key-1234",
    )

    assert record.job_state == "QUEUED"
    assert store.created is not None
    assert store.created["request"].document() == {
        "query": "wafer   yield",
        "filters": {"classification": "INTERNAL", "platform": "postgres"},
        "sort": "NAME_ASC",
        "format": "CSV",
    }
    assert store.created["classification_ceiling"] == int(Classification.INTERNAL)
    assert store.created["source_projection_version"] == 7
    assert decisions.decisions[-1].allowed


@pytest.mark.asyncio
async def test_export_capability_uses_catalog_export_permission_not_operations_permission() -> None:
    service, decisions, _ = _service(store=FakeExportStore(), worker_enabled=False)

    assert not await service.capability(
        subject=_subject(),
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="capability-allowed",
    )
    assert decisions.decisions[-1].allowed

    with pytest.raises(ForbiddenError):
        await service.capability(
            subject=_subject(export_allowed=False),
            environment=EnvironmentAttributes(requested_at=NOW),
            request_id="capability-denied",
        )
    assert "ACTION_NOT_GRANTED" in decisions.decisions[-1].reason_codes


@pytest.mark.asyncio
async def test_restricted_export_is_denied_even_with_clearance_and_explicit_action() -> None:
    store = FakeExportStore()
    service, decisions, _ = _service(store=store)

    with pytest.raises(ForbiddenError):
        await service.create(
            subject=_subject(clearance=Classification.RESTRICTED),
            request=CatalogExportRequest(query="wafer", filters={"classification": "RESTRICTED"}),
            environment=EnvironmentAttributes(requested_at=NOW),
            request_id="request-2",
            idempotency_key="idempotency-key-5678",
        )

    assert store.created is None
    assert "RESTRICTED_EXPORT_DENIED" in decisions.decisions[-1].reason_codes


@pytest.mark.asyncio
async def test_export_create_is_disabled_without_isolated_worker_credentials() -> None:
    store = FakeExportStore()
    service, _, _ = _service(store=store, worker_enabled=False)

    with pytest.raises(ConflictError, match="separately credentialed"):
        await service.create(
            subject=_subject(),
            request=CatalogExportRequest(query="wafer", filters={}),
            environment=EnvironmentAttributes(requested_at=NOW),
            request_id="request-3",
            idempotency_key="idempotency-key-9012",
        )


@pytest.mark.asyncio
async def test_export_create_rejects_non_active_lifecycle_for_non_http_callers() -> None:
    store = FakeExportStore()
    service, _, _ = _service(store=store)

    with pytest.raises(ValidationError, match="active assets only"):
        await service.create(
            subject=_subject(),
            request=CatalogExportRequest(query="wafer", filters={"lifecycle": "DELETED"}),
            environment=EnvironmentAttributes(requested_at=NOW),
            request_id="request-lifecycle",
            idempotency_key="idempotency-key-lifecycle",
        )

    assert store.created is None


@pytest.mark.asyncio
async def test_download_revalidates_snapshot_and_artifact_before_presigning() -> None:
    store = FakeExportStore()
    store.record = _record()
    service, _, objects = _service(store=store)
    objects.metadata = ObjectMetadata(
        bucket="exports",
        object_key="exports/file.csv",
        size_bytes=10,
        content_type="text/csv; charset=utf-8",
        etag="provider-etag",
        checksum_sha256=None,
        user_metadata={
            "export-id": str(store.record.export_id),
            "request-hash": store.record.request_hash,
            "export-safety-version": "csv-safe-v1",
        },
    )

    download = await service.download(
        subject=_subject(),
        export_id=store.record.export_id,
        environment=EnvironmentAttributes(requested_at=NOW),
        request_id="request-4",
    )

    assert download is not None and download.expires_seconds == 60
    assert objects.presigned


@pytest.mark.asyncio
async def test_download_fails_closed_after_projection_change() -> None:
    store = FakeExportStore()
    store.record = _record()
    service, _, objects = _service(store=store, watermark=FakeWatermark(8))

    with pytest.raises(ForbiddenError, match="no longer current"):
        await service.download(
            subject=_subject(),
            export_id=store.record.export_id,
            environment=EnvironmentAttributes(requested_at=NOW),
            request_id="request-5",
        )

    assert not objects.presigned
