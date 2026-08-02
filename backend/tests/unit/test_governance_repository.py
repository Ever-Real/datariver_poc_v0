from __future__ import annotations

import hashlib
import inspect
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.domain.authz import Classification
from datariver.domain.common import ConflictError
from datariver.domain.governance import ChangeItem, ChangeRequest, change_target_binding_hash
from datariver.domain.manual_metadata import ManualMetadataApplyClaim
from datariver.domain.registration_worker import (
    RegistrationWorkerCallIdentity,
    RegistrationWorkerCallReplay,
)
from datariver.infrastructure.db import governance as governance_module
from datariver.infrastructure.db.governance import (
    SqlChangeRequestRepository,
    SqlManualMetadataSubmissionRepository,
)
from datariver.infrastructure.db.models.governance import (
    ChangeRequestModel,
    ChangeRequestRoundItemModel,
)


class RecordingSession:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    def add(self, value: object) -> None:
        self.events.append(("add", value))

    async def scalar(self, _statement: object) -> object:
        return uuid4()

    async def flush(self, values: list[object]) -> None:
        self.events.append(("flush", tuple(values)))

    def add_all(self, values: list[object]) -> None:
        self.events.append(("add_all", tuple(values)))


def make_request() -> ChangeRequest:
    workspace_id = uuid4()
    asset_id = uuid4()
    system_id = uuid4()
    target_ref = "urn:li:dataset:test"
    return ChangeRequest.create(
        workspace_id=workspace_id,
        number="CR-2026-000001",
        request_type="CHANGE_INTAKE",
        title="Repository insert ordering",
        description="Parent rows must exist before child rows are inserted.",
        requester_id=uuid4(),
        classification=Classification.CONFIDENTIAL,
        items=[
            ChangeItem(
                item_id=uuid4(),
                target_type="DATAHUB_INTAKE",
                target_ref=target_ref,
                operation="REVIEW",
                after_document={"contract": "change-intake-v1"},
                aspect_name="changeIntake",
                before_hash="a" * 64,
                target_asset_id=asset_id,
                target_asset_type="DATASET",
                target_system_id=system_id,
                target_classification=Classification.CONFIDENTIAL,
                target_lifecycle="ACTIVE",
                target_source_version="1",
                target_observed_at=datetime.now(UTC),
                target_binding_hash=change_target_binding_hash(
                    target_ref=target_ref,
                    asset_id=asset_id,
                    asset_type="DATASET",
                    system_id=system_id,
                    domain_id=None,
                    owner_department_id=None,
                    classification=Classification.CONFIDENTIAL,
                    lifecycle="ACTIVE",
                ),
                routing_system_id=system_id,
            )
        ],
    )


@pytest.mark.asyncio
async def test_new_change_request_flushes_parent_before_rounds_and_items() -> None:
    session = RecordingSession()
    repository = SqlChangeRequestRepository(cast(AsyncSession, cast(Any, session)))

    await repository.add(make_request())

    assert [event[0] for event in session.events] == [
        "add",
        "flush",
        "add_all",
        "flush",
        "add_all",
    ]
    parent = session.events[0][1]
    assert isinstance(parent, ChangeRequestModel)
    assert session.events[1][1] == (parent,)
    association = cast(tuple[object, ...], session.events[-1][1])[0]
    assert isinstance(association, ChangeRequestRoundItemModel)
    assert association.ordinal == 0


def test_change_request_hydration_bounds_every_child_collection_before_materialization() -> None:
    source = inspect.getsource(SqlChangeRequestRepository.get_for_update)

    for constant in (
        "MAX_CHANGE_ITEMS",
        "MAX_CHANGE_APPROVALS",
        "MAX_CHANGE_TRANSITIONS",
        "MAX_CHANGE_ROUNDS",
        "MAX_CHANGE_TEST_RUNS",
    ):
        assert f".limit({constant} + 1)" in source
    assert source.count("require_bounded(") == 6


def test_change_request_repository_reads_and_writes_only_current_round_items() -> None:
    hydrate_source = inspect.getsource(SqlChangeRequestRepository.get_for_update)
    summary_source = inspect.getsource(SqlChangeRequestRepository.list_summaries)
    save_source = inspect.getsource(SqlChangeRequestRepository.save)

    assert "ChangeRequestRoundItemModel.round_id == model.current_round_id" in hydrate_source
    assert "CHANGE_REQUEST_ROUND_ITEMS_MISSING" in hydrate_source
    assert "ChangeRequestModel.current_round_id" in summary_source
    assert "ChangeRequestRoundItemModel.round_id" in summary_source
    assert "stored_round.closed_at = round_value.closed_at" in save_source
    assert "newly minted immutable items" in save_source
    assert "ChangeRequestRoundItemModel(" in save_source
    assert "item.after_document =" not in save_source
    assert "item.target_ref =" not in save_source


def test_manual_claim_is_fifo_per_asset_and_recovers_expired_final_attempts() -> None:
    source = inspect.getsource(SqlManualMetadataSubmissionRepository.claim_next)

    assert "earlier.serial_number" in source
    assert "~exists(" in source
    assert "competing.state" in source
    assert "model.attempts >= maximum_attempts" in source
    assert "_terminalize_exhausted_apply" in source


class _FirstResult:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def first(self) -> object | None:
        return self._value


class _ManualRecoverySession:
    def __init__(self, models: list[SimpleNamespace]) -> None:
        self.models = models
        self.select_count = 0
        self.flush_count = 0

    async def scalars(self, _statement: object) -> _FirstResult:
        value = self.models[self.select_count] if self.select_count < len(self.models) else None
        self.select_count += 1
        return _FirstResult(value)

    async def flush(self) -> None:
        self.flush_count += 1


@pytest.mark.asyncio
@pytest.mark.parametrize("exhausted_count", [100, 101])
async def test_manual_exact_recovery_cap_returns_a_durable_bounded_result(
    monkeypatch: pytest.MonkeyPatch,
    exhausted_count: int,
) -> None:
    workspace_id = uuid4()
    worker_subject_id = uuid4()
    models = [
        SimpleNamespace(
            id=uuid4(),
            state="APPLYING",
            attempts=3,
        )
        for _ in range(exhausted_count)
    ]
    session = _ManualRecoverySession(models)
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

    async def _database_now(_self: object) -> datetime:
        return datetime(2026, 7, 23, tzinfo=UTC)

    async def _terminalize(
        _self: object,
        *,
        model: SimpleNamespace,
        now: datetime,
    ) -> None:
        del now
        model.state = "FAILED"

    monkeypatch.setattr(governance_module, "SqlRegistrationWorkerCallReceipts", _Receipts)
    monkeypatch.setattr(
        SqlManualMetadataSubmissionRepository,
        "_database_now",
        _database_now,
    )
    monkeypatch.setattr(
        SqlManualMetadataSubmissionRepository,
        "_terminalize_exhausted_apply",
        _terminalize,
    )
    repository = SqlManualMetadataSubmissionRepository(cast(AsyncSession, cast(Any, session)))
    run_call = RegistrationWorkerCallIdentity(
        operation="registration.manual-metadata.apply-run.v1",
        key_hash="1" * 64,
        request_hash="2" * 64,
        worker_subject_id=worker_subject_id,
    )

    result = await repository.claim_next(
        workspace_id=workspace_id,
        worker_subject_id=worker_subject_id,
        now=datetime(2026, 7, 23, tzinfo=UTC),
        lease_seconds=60,
        maximum_attempts=3,
        run_call=run_call,
    )

    assert isinstance(result, RegistrationWorkerCallReplay)
    assert result.result == {
        "processed": False,
        "submission_id": None,
        "serial_number": None,
        "state": "RECOVERY_LIMIT_REACHED",
    }
    assert completed_results == [result.result]
    assert session.select_count == 100
    assert session.flush_count == 100
    assert [model.state for model in models[:100]] == ["FAILED"] * 100
    if exhausted_count == 101:
        assert models[100].state == "APPLYING"


@pytest.mark.asyncio
async def test_manual_superseded_result_requires_the_old_receipt_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_subject_id = uuid4()
    run_call = RegistrationWorkerCallIdentity(
        operation="registration.manual-metadata.apply-run.v1",
        key_hash="3" * 64,
        request_hash="4" * 64,
        worker_subject_id=worker_subject_id,
    )
    claim = cast(
        ManualMetadataApplyClaim,
        SimpleNamespace(
            submission=SimpleNamespace(workspace_id=uuid4()),
            run_call=run_call,
            lease_token="old-token",
        ),
    )
    receipt = SimpleNamespace(
        state="RUNNING",
        claim_token_hash=hashlib.sha256(b"new-token").hexdigest(),
        result=None,
    )

    class _Receipts:
        def __init__(self, _session: object) -> None:
            return None

        async def lock(self, **_: object) -> SimpleNamespace:
            return receipt

        async def complete(self, **_: object) -> None:
            raise AssertionError("a superseded token must not complete the receipt")

    monkeypatch.setattr(governance_module, "SqlRegistrationWorkerCallReceipts", _Receipts)
    repository = SqlManualMetadataSubmissionRepository(cast(AsyncSession, cast(Any, object())))

    with pytest.raises(ConflictError) as exc_info:
        await repository._complete_worker_call(
            claim=claim,
            result={
                "processed": True,
                "submission_id": str(uuid4()),
                "serial_number": 1,
                "state": "SUPERSEDED",
            },
            now=datetime(2026, 7, 23, tzinfo=UTC),
        )

    assert exc_info.value.details == {
        "code": "WORKER_RUN_TERMINAL_RETRY",
        "retryable": True,
    }


@pytest.mark.asyncio
async def test_manual_superseded_result_completes_the_matching_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_subject_id = uuid4()
    run_call = RegistrationWorkerCallIdentity(
        operation="registration.manual-metadata.apply-run.v1",
        key_hash="5" * 64,
        request_hash="6" * 64,
        worker_subject_id=worker_subject_id,
    )
    claim = cast(
        ManualMetadataApplyClaim,
        SimpleNamespace(
            submission=SimpleNamespace(workspace_id=uuid4()),
            run_call=run_call,
            lease_token="old-token",
        ),
    )
    result = {
        "processed": True,
        "submission_id": str(uuid4()),
        "serial_number": 1,
        "state": "SUPERSEDED",
    }
    receipt = SimpleNamespace(
        state="RUNNING",
        claim_token_hash=hashlib.sha256(b"old-token").hexdigest(),
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

    monkeypatch.setattr(governance_module, "SqlRegistrationWorkerCallReceipts", _Receipts)
    repository = SqlManualMetadataSubmissionRepository(cast(AsyncSession, cast(Any, object())))

    await repository._complete_worker_call(
        claim=claim,
        result=result,
        now=datetime(2026, 7, 23, tzinfo=UTC),
    )

    assert completions == [(result, "old-token")]
