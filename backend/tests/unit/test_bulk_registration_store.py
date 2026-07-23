from __future__ import annotations

import hashlib
import inspect
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.application.services.bulk_registration import BulkPreparationClaim
from datariver.application.typed_upload_profiles import (
    DATASET_DESCRIPTION_CSV_V1,
    DATASET_DESCRIPTION_XLSX_V1,
)
from datariver.domain.common import ConflictError
from datariver.domain.registration import UploadContentProfile
from datariver.domain.registration_worker import (
    RegistrationWorkerCallIdentity,
    RegistrationWorkerCallReplay,
)
from datariver.infrastructure.db import bulk_registration as bulk_registration_module
from datariver.infrastructure.db.bulk_registration import (
    SqlBulkPreparationExecutionStore,
    _claim_is_current,
    _retry_delay_seconds,
)
from datariver.infrastructure.db.models.integration import UploadPreparationJobModel

NOW = datetime(2026, 7, 23, tzinfo=UTC)


def _job(*, lease_until: datetime) -> UploadPreparationJobModel:
    return UploadPreparationJobModel(
        id=uuid4(),
        workspace_id=uuid4(),
        upload_id=uuid4(),
        requested_by=uuid4(),
        content_profile=UploadContentProfile.DATASET_DESCRIPTION_CSV_V1.value,
        source_manifest_version=1,
        source_sha256="a" * 64,
        configuration_hash="b" * 64,
        state="PREPARING",
        next_attempt_at=None,
        lease_token=uuid4(),
        lease_until=lease_until,
        attempts=2,
        rows_processed=0,
        total_rows=None,
        last_error_code=None,
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def _claim(job: UploadPreparationJobModel) -> BulkPreparationClaim:
    assert job.lease_token is not None
    return BulkPreparationClaim(
        workspace_id=job.workspace_id,
        preparation_id=job.id,
        upload_id=job.upload_id,
        requested_by=job.requested_by,
        content_profile=UploadContentProfile(job.content_profile),
        source_manifest_version=job.source_manifest_version,
        source_sha256=job.source_sha256,
        configuration_hash=job.configuration_hash,
        source_bucket="accepted",
        source_object_key="object.csv",
        source_size_bytes=10,
        source_content_type="text/csv",
        scanner_version="scanner-v1",
        lease_token=job.lease_token,
        attempt=job.attempts,
    )


def test_bulk_preparation_retry_backoff_is_bounded_and_monotonic() -> None:
    assert [_retry_delay_seconds(attempt) for attempt in range(1, 9)] == [
        2,
        4,
        8,
        16,
        32,
        60,
        60,
        60,
    ]


def test_typed_bulk_profiles_fit_the_api_spool_safety_budget() -> None:
    for definition in (DATASET_DESCRIPTION_CSV_V1, DATASET_DESCRIPTION_XLSX_V1):
        assert definition.maximum_file_bytes <= 16 * 1024 * 1024
        assert definition.maximum_rows <= 10_000
        assert definition.maximum_file_bytes * 2 <= 32 * 1024 * 1024


def test_bulk_publish_and_failure_require_an_unexpired_database_time_lease() -> None:
    current = _job(lease_until=NOW + timedelta(seconds=1))
    claim = _claim(current)

    assert _claim_is_current(current, claim, now=NOW)
    assert not _claim_is_current(current, claim, now=NOW + timedelta(seconds=1))

    current.lease_token = uuid4()
    assert not _claim_is_current(current, claim, now=NOW)


def test_bulk_claim_terminalizes_an_expired_final_attempt_before_scanning_onward() -> None:
    source = inspect.getsource(SqlBulkPreparationExecutionStore.claim_next)

    assert "UploadPreparationJobModel.lease_until <= now" in source
    assert "job.attempts >= maximum_attempts" in source
    assert 'job.last_error_code = "WORKER_LEASE_EXHAUSTED"' in source
    assert "_MAXIMUM_EXHAUSTED_BULK_RECOVERIES_PER_CLAIM" in source


class _Transaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_: object) -> None:
        return None


class _RowResult:
    def __init__(self, value: tuple[SimpleNamespace, object] | None) -> None:
        self._value = value

    def one_or_none(self) -> tuple[SimpleNamespace, object] | None:
        return self._value


class _BulkRecoverySession:
    def __init__(self, jobs: list[SimpleNamespace]) -> None:
        self.jobs = jobs
        self.select_count = 0
        self.flush_count = 0
        self.outbox_count = 0

    async def __aenter__(self) -> _BulkRecoverySession:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def begin(self) -> _Transaction:
        return _Transaction()

    async def execute(self, _statement: object) -> _RowResult:
        value = (
            (self.jobs[self.select_count], object()) if self.select_count < len(self.jobs) else None
        )
        self.select_count += 1
        return _RowResult(value)

    async def flush(self) -> None:
        self.flush_count += 1

    def add_all(self, values: list[object]) -> None:
        self.outbox_count += len(values)


@pytest.mark.asyncio
@pytest.mark.parametrize("exhausted_count", [100, 101])
async def test_bulk_exact_recovery_cap_returns_a_durable_bounded_result(
    monkeypatch: pytest.MonkeyPatch,
    exhausted_count: int,
) -> None:
    workspace_id = uuid4()
    worker_subject_id = uuid4()
    jobs = [
        SimpleNamespace(
            id=uuid4(),
            workspace_id=workspace_id,
            upload_id=uuid4(),
            state="PREPARING",
            attempts=3,
            next_attempt_at=None,
            lease_token=uuid4(),
            lease_until=NOW - timedelta(seconds=1),
            last_error_code=None,
            version=1,
            updated_at=NOW,
        )
        for _ in range(exhausted_count)
    ]
    session = _BulkRecoverySession(jobs)
    completed_results: list[dict[str, object]] = []

    class _Receipts:
        def __init__(self, _session: object) -> None:
            return None

        async def lock(self, **_: object) -> None:
            return None

        async def complete_no_work(
            self,
            *,
            result: dict[str, object],
            **_: object,
        ) -> RegistrationWorkerCallReplay:
            completed_results.append(result)
            return RegistrationWorkerCallReplay(result=result)

    async def _set_security_context(_session: object, **_: object) -> None:
        return None

    async def _database_now(_session: object) -> datetime:
        return NOW

    monkeypatch.setattr(
        bulk_registration_module,
        "SqlRegistrationWorkerCallReceipts",
        _Receipts,
    )
    monkeypatch.setattr(
        bulk_registration_module,
        "set_security_context",
        _set_security_context,
    )
    monkeypatch.setattr(bulk_registration_module, "_database_now", _database_now)
    store = SqlBulkPreparationExecutionStore(
        cast(
            async_sessionmaker[AsyncSession],
            cast(Any, lambda: session),
        )
    )
    run_call = RegistrationWorkerCallIdentity(
        operation="registration.bulk-preparation.execute-run.v1",
        key_hash="5" * 64,
        request_hash="6" * 64,
        worker_subject_id=worker_subject_id,
    )

    result = await store.claim_next(
        workspace_id=workspace_id,
        worker_subject_id=worker_subject_id,
        lease_seconds=60,
        maximum_attempts=3,
        run_call=run_call,
    )

    assert isinstance(result, RegistrationWorkerCallReplay)
    assert result.result == {
        "processed": False,
        "preparation_id": None,
        "state": "RECOVERY_LIMIT_REACHED",
        "item_count": None,
    }
    assert completed_results == [result.result]
    assert session.select_count == 100
    assert session.flush_count == 100
    assert session.outbox_count == 100
    assert [job.state for job in jobs[:100]] == ["FAILED"] * 100
    if exhausted_count == 101:
        assert jobs[100].state == "PREPARING"


@pytest.mark.asyncio
async def test_bulk_superseded_result_requires_the_old_receipt_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_subject_id = uuid4()
    run_call = RegistrationWorkerCallIdentity(
        operation="registration.bulk-preparation.execute-run.v1",
        key_hash="7" * 64,
        request_hash="8" * 64,
        worker_subject_id=worker_subject_id,
    )
    claim = cast(
        BulkPreparationClaim,
        SimpleNamespace(
            workspace_id=uuid4(),
            run_call=run_call,
            lease_token=uuid4(),
        ),
    )
    receipt = SimpleNamespace(
        state="RUNNING",
        claim_token_hash=hashlib.sha256(b"not-the-old-token").hexdigest(),
        result=None,
    )

    class _Receipts:
        def __init__(self, _session: object) -> None:
            return None

        async def lock(self, **_: object) -> SimpleNamespace:
            return receipt

        async def complete(self, **_: object) -> None:
            raise AssertionError("a superseded token must not complete the receipt")

    monkeypatch.setattr(
        bulk_registration_module,
        "SqlRegistrationWorkerCallReceipts",
        _Receipts,
    )
    store = SqlBulkPreparationExecutionStore(
        cast(async_sessionmaker[AsyncSession], cast(Any, object()))
    )

    with pytest.raises(ConflictError) as exc_info:
        await store._complete_worker_call(
            session=cast(AsyncSession, cast(Any, object())),
            claim=claim,
            result={
                "processed": True,
                "preparation_id": str(uuid4()),
                "state": "SUPERSEDED",
                "item_count": None,
            },
            now=NOW,
        )

    assert exc_info.value.details == {
        "code": "WORKER_RUN_TERMINAL_RETRY",
        "retryable": True,
    }


@pytest.mark.asyncio
async def test_bulk_superseded_result_completes_the_matching_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_subject_id = uuid4()
    run_call = RegistrationWorkerCallIdentity(
        operation="registration.bulk-preparation.execute-run.v1",
        key_hash="9" * 64,
        request_hash="a" * 64,
        worker_subject_id=worker_subject_id,
    )
    lease_token = uuid4()
    claim = cast(
        BulkPreparationClaim,
        SimpleNamespace(
            workspace_id=uuid4(),
            run_call=run_call,
            lease_token=lease_token,
        ),
    )
    result = {
        "processed": True,
        "preparation_id": str(uuid4()),
        "state": "SUPERSEDED",
        "item_count": None,
    }
    receipt = SimpleNamespace(
        state="RUNNING",
        claim_token_hash=hashlib.sha256(str(lease_token).encode()).hexdigest(),
        result=None,
    )
    completions: list[tuple[dict[str, object], str]] = []

    class _Receipts:
        def __init__(self, _session: object) -> None:
            return None

        async def lock(self, **_: object) -> SimpleNamespace:
            return receipt

        async def complete(
            self,
            *,
            result: dict[str, object],
            raw_claim_token: str,
            **_: object,
        ) -> None:
            completions.append((result, raw_claim_token))

    monkeypatch.setattr(
        bulk_registration_module,
        "SqlRegistrationWorkerCallReceipts",
        _Receipts,
    )
    store = SqlBulkPreparationExecutionStore(
        cast(async_sessionmaker[AsyncSession], cast(Any, object()))
    )

    await store._complete_worker_call(
        session=cast(AsyncSession, cast(Any, object())),
        claim=claim,
        result=result,
        now=NOW,
    )

    assert completions == [(result, str(lease_token))]
