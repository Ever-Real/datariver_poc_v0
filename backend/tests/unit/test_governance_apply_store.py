from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from datariver.application.dto import GovernanceApplyClaim
from datariver.infrastructure.db.governance_apply import SqlGovernanceApplyStore
from datariver.infrastructure.db.models.integration import JobAttemptModel, JobModel

NOW = datetime(2026, 7, 23, tzinfo=UTC)


def _job(*, attempts: int = 2, state: str = "RUNNING") -> JobModel:
    lease_owner_id = uuid4()
    return JobModel(
        id=uuid4(),
        workspace_id=uuid4(),
        job_type=SqlGovernanceApplyStore.job_type,
        causation_id=uuid4(),
        state=state,
        requested_by=uuid4(),
        progress={},
        result_ref=None,
        lease_until=NOW + timedelta(minutes=5),
        attempts=attempts,
        attempt_cycle=1,
        cycle_attempts=attempts,
        lease_token_hash=(
            "2c80af130e7c29586a8e40b306691fd9726d60daa488ff3580121f95a823fc38"
            if state == "RUNNING"
            else None
        ),
        lease_owner_id=lease_owner_id if state == "RUNNING" else None,
        last_error_code=None,
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def _attempt(job: JobModel, *, attempt_no: int = 2, state: str = "RUNNING") -> JobAttemptModel:
    return JobAttemptModel(
        id=uuid4(),
        workspace_id=job.workspace_id,
        job_id=job.id,
        attempt_no=attempt_no,
        worker_id="worker",
        state=state,
        error_class=None,
        external_response_hash=None,
        started_at=NOW,
        finished_at=None,
    )


def test_only_current_running_governance_attempt_may_complete() -> None:
    job = _job()
    attempt = _attempt(job)
    claim = GovernanceApplyClaim(
        change_request=None,  # type: ignore[arg-type]
        job_id=job.id,
        attempt_id=attempt.id,
        attempt_no=2,
        lease_token="lease-token",
        worker_subject_id=job.lease_owner_id or uuid4(),
    )

    assert SqlGovernanceApplyStore._claim_is_current(job=job, attempt=attempt, claim=claim, now=NOW)

    stale_claim = GovernanceApplyClaim(
        change_request=None,  # type: ignore[arg-type]
        job_id=job.id,
        attempt_id=attempt.id,
        attempt_no=1,
        lease_token="lease-token",
        worker_subject_id=job.lease_owner_id or uuid4(),
    )
    assert not SqlGovernanceApplyStore._claim_is_current(
        job=job, attempt=attempt, claim=stale_claim, now=NOW
    )

    attempt.attempt_no = 1
    assert not SqlGovernanceApplyStore._claim_is_current(
        job=job, attempt=attempt, claim=claim, now=NOW
    )
    attempt.attempt_no = 2
    attempt.state = "FAILED"
    assert not SqlGovernanceApplyStore._claim_is_current(
        job=job, attempt=attempt, claim=claim, now=NOW
    )
    attempt.state = "RUNNING"
    job.state = "RETRY_WAIT"
    assert not SqlGovernanceApplyStore._claim_is_current(
        job=job, attempt=attempt, claim=claim, now=NOW
    )


def test_cross_job_or_workspace_attempt_never_matches_a_claim() -> None:
    job = _job()
    attempt = _attempt(job)
    claim = GovernanceApplyClaim(
        change_request=None,  # type: ignore[arg-type]
        job_id=job.id,
        attempt_id=attempt.id,
        attempt_no=2,
        lease_token="lease-token",
        worker_subject_id=job.lease_owner_id or uuid4(),
    )

    attempt.job_id = uuid4()
    assert not SqlGovernanceApplyStore._claim_is_current(
        job=job, attempt=attempt, claim=claim, now=NOW
    )
    attempt.job_id = job.id
    attempt.workspace_id = uuid4()
    assert not SqlGovernanceApplyStore._claim_is_current(
        job=job, attempt=attempt, claim=claim, now=NOW
    )


def test_expired_governance_lease_never_completes() -> None:
    job = _job()
    attempt = _attempt(job)
    claim = GovernanceApplyClaim(
        change_request=None,  # type: ignore[arg-type]
        job_id=job.id,
        attempt_id=attempt.id,
        attempt_no=2,
        lease_token="lease-token",
        worker_subject_id=job.lease_owner_id or uuid4(),
    )

    assert not SqlGovernanceApplyStore._claim_is_current(
        job=job,
        attempt=attempt,
        claim=claim,
        now=job.lease_until or NOW,
    )


def test_governance_claim_terminalizes_expired_final_attempt_and_supersedes_reclaims() -> None:
    source = inspect.getsource(SqlGovernanceApplyStore.claim_next)
    recovery = inspect.getsource(SqlGovernanceApplyStore._terminalize_exhausted_job)

    assert "job.cycle_attempts >= maximum_attempts" in source
    assert 'previous.state = "SUPERSEDED"' in source
    assert 'previous.error_class = "LEASE_EXPIRED"' in source
    assert 'previous.error_class = "WORKER_LEASE_EXHAUSTED"' in recovery
    assert "target=ChangeState.APPLY_FAILED" in recovery


def test_completed_governance_apply_work_is_never_claimable_again() -> None:
    source = inspect.getsource(SqlGovernanceApplyStore.claim_next)

    assert 'JobModel.state != "COMPLETED"' in source
    assert '"A completed governance apply job cannot be claimed again."' in source


def test_governance_apply_migration_fences_terminal_states_and_exact_drift() -> None:
    root = Path(__file__).resolve().parents[3]
    source = (root / "backend/alembic/versions/0048_governance_apply_lease_fencing.py").read_text(
        encoding="utf-8"
    )

    assert "OLD.state NOT IN ('RETRY_WAIT', 'FAILED')" in source
    assert "OLD.state IN ('APPLYING', 'APPLIED', 'APPLY_FAILED')" in source
    assert "governance apply job check definitions are not canonical" in source
    assert "completed governance apply job is not bound to an applied request" in source
    assert source.count("has_column_privilege(") >= 3
