from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.domain.authz import Classification
from datariver.domain.common import ConflictError, canonical_json_hash
from datariver.domain.governance import ChangeItem, ChangeRequest, ChangeState
from datariver.infrastructure.db.governance_apply import SqlGovernanceApplyStore
from datariver.infrastructure.db.governance_apply_report import (
    SqlGovernanceApplyReportReader,
)
from datariver.infrastructure.db.models.integration import JobAttemptModel, JobModel

NOW = datetime(2026, 7, 23, tzinfo=UTC)


class ScalarRows:
    def __init__(self, values: list[JobAttemptModel]) -> None:
        self._values = values

    def all(self) -> list[JobAttemptModel]:
        return self._values


class FakeSession:
    def __init__(self, job: JobModel | None, attempts: list[JobAttemptModel]) -> None:
        self.job = job
        self.attempts = attempts

    async def scalar(self, _: object) -> JobModel | None:
        return self.job

    async def scalars(self, _: object) -> ScalarRows:
        return ScalarRows(self.attempts)


def _change_request() -> ChangeRequest:
    workspace_id = uuid4()
    item_id = uuid4()
    return ChangeRequest(
        change_request_id=uuid4(),
        workspace_id=workspace_id,
        number="CR-REPORT-1",
        request_type="BULK_DATASET_DESCRIPTION",
        title="Apply report",
        description="Read-back evidence",
        requester_id=uuid4(),
        requester_department_id=None,
        current_round_id=uuid4(),
        current_round_number=1,
        created_at=NOW,
        classification=Classification.INTERNAL,
        state=ChangeState.APPLIED,
        items=[
            ChangeItem(
                item_id=item_id,
                target_type="DATAHUB_ASPECT",
                target_ref="urn:li:dataset:report",
                operation="UPSERT",
                after_document={"description": "updated"},
                aspect_name="datasetProperties",
                before_hash="a" * 64,
                after_hash="b" * 64,
            )
        ],
    )


@pytest.mark.asyncio
async def test_apply_report_redacts_provider_operation_and_reconciles_hashes() -> None:
    change_request = _change_request()
    item = change_request.items[0]
    expected_hash = canonical_json_hash(
        ({"item_id": str(item.item_id), "content_hash": item.after_hash},)
    )
    job = JobModel(
        id=uuid4(),
        workspace_id=change_request.workspace_id,
        job_type=SqlGovernanceApplyStore.job_type,
        causation_id=change_request.change_request_id,
        state="COMPLETED",
        requested_by=change_request.requester_id,
        progress={
            "items": [
                {
                    "item_id": str(item.item_id),
                    "operation_id": "must-not-be-returned",
                    "provider_version": "datahub-1",
                    "source_version": "provider-source-7",
                    "content_hash": item.after_hash,
                }
            ],
            "content_hash": expected_hash,
        },
        result_ref=f"change-request:{change_request.change_request_id}",
        lease_until=None,
        attempts=1,
        last_error_code=None,
        version=2,
        created_at=NOW,
        updated_at=NOW,
    )
    attempt = JobAttemptModel(
        id=uuid4(),
        workspace_id=change_request.workspace_id,
        job_id=job.id,
        attempt_no=1,
        worker_id="governance-worker",
        state="COMPLETED",
        error_class=None,
        external_response_hash=expected_hash,
        started_at=NOW,
        finished_at=NOW,
    )
    reader = SqlGovernanceApplyReportReader(cast(AsyncSession, FakeSession(job, [attempt])))

    report = await reader.get(
        workspace_id=change_request.workspace_id,
        change_request=change_request,
    )

    assert report.reconciled is True
    assert report.expected_hash == expected_hash
    assert report.observed_hash == expected_hash
    assert report.items[0].observed_hash == item.after_hash
    assert report.items[0].provider_version == "datahub-1"
    assert "operation" not in repr(report)
    assert len(report.attempts) == 1


@pytest.mark.asyncio
async def test_apply_report_rejects_unknown_or_malformed_item_evidence() -> None:
    change_request = _change_request()
    job = JobModel(
        id=uuid4(),
        workspace_id=change_request.workspace_id,
        job_type=SqlGovernanceApplyStore.job_type,
        causation_id=change_request.change_request_id,
        state="COMPLETED",
        requested_by=change_request.requester_id,
        progress={
            "items": [{"item_id": str(uuid4()), "content_hash": "x"}],
            "content_hash": "b" * 64,
        },
        result_ref=None,
        lease_until=None,
        attempts=1,
        last_error_code=None,
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    reader = SqlGovernanceApplyReportReader(cast(AsyncSession, FakeSession(job, [])))

    with pytest.raises(ConflictError, match="apply report is invalid"):
        await reader.get(
            workspace_id=change_request.workspace_id,
            change_request=change_request,
        )
