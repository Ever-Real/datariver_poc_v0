from __future__ import annotations

import hashlib
import secrets
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.application.dto import GovernanceApplyClaim
from datariver.application.ports import GovernanceApplyStore
from datariver.domain.common import Effect, uuid7
from datariver.domain.governance import ChangeState
from datariver.infrastructure.db.governance import (
    SqlChangeRequestRepository,
    SqlOutboxWriter,
)
from datariver.infrastructure.db.models.authz import PolicyDecisionModel
from datariver.infrastructure.db.models.governance import ChangeRequestModel
from datariver.infrastructure.db.models.integration import JobAttemptModel, JobModel


class SqlGovernanceApplyStore(GovernanceApplyStore):
    job_type = "DATAHUB_CHANGE_APPLY"
    _maximum_exhausted_recoveries_per_claim = 100

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def claim_next(
        self,
        *,
        worker_id: str,
        system_actor_id: UUID,
        lease_seconds: int,
        maximum_attempts: int,
    ) -> GovernanceApplyClaim | None:
        async with self._session_factory() as session, session.begin():
            now = await _database_now(session)
            change_request = None
            job: JobModel | None = None
            repository = SqlChangeRequestRepository(session)
            for _ in range(self._maximum_exhausted_recoveries_per_claim):
                statement = (
                    select(ChangeRequestModel)
                    .outerjoin(
                        JobModel,
                        and_(
                            JobModel.causation_id == ChangeRequestModel.id,
                            JobModel.job_type == self.job_type,
                        ),
                    )
                    .where(
                        or_(
                            JobModel.id.is_(None),
                            JobModel.state != "COMPLETED",
                        ),
                        or_(
                            ChangeRequestModel.state == ChangeState.APPLY_QUEUED.value,
                            and_(
                                ChangeRequestModel.state == ChangeState.APPLYING.value,
                                or_(
                                    JobModel.lease_until.is_(None),
                                    JobModel.lease_until <= now,
                                ),
                            ),
                        ),
                    )
                    .order_by(ChangeRequestModel.created_at)
                    .with_for_update(of=ChangeRequestModel, skip_locked=True)
                    .limit(1)
                )
                model = (await session.scalars(statement)).one_or_none()
                if model is None:
                    return None
                change_request = await repository.get_for_update(
                    workspace_id=model.workspace_id, change_request_id=model.id
                )
                if change_request is None:
                    return None
                job = (
                    await session.scalars(
                        select(JobModel)
                        .where(
                            JobModel.job_type == self.job_type,
                            JobModel.causation_id == change_request.change_request_id,
                        )
                        .with_for_update()
                    )
                ).one_or_none()
                if job is not None and job.state == "COMPLETED":
                    raise RuntimeError("A completed governance apply job cannot be claimed again.")
                if (
                    job is not None
                    and change_request.state is ChangeState.APPLY_QUEUED
                    and job.state == "FAILED"
                ):
                    # Keep the evidence ordinal monotonic while an authorized requeue starts a
                    # fresh bounded retry cycle.
                    job.attempt_cycle += 1
                    job.cycle_attempts = 0
                if (
                    job is not None
                    and change_request.state is ChangeState.APPLYING
                    and job.cycle_attempts >= maximum_attempts
                ):
                    await self._terminalize_exhausted_job(
                        session=session,
                        repository=repository,
                        change_request=change_request,
                        job=job,
                        system_actor_id=system_actor_id,
                        now=now,
                    )
                    change_request.events.clear()
                    # The session is configured with autoflush disabled. Make
                    # the terminal CR/job/attempt visible before rescanning.
                    await session.flush()
                    change_request = None
                    job = None
                    continue
                break
            if change_request is None:
                return None
            was_queued = change_request.state is ChangeState.APPLY_QUEUED
            if job is not None and not was_queued:
                previous = await session.scalar(
                    select(JobAttemptModel)
                    .where(
                        JobAttemptModel.workspace_id == job.workspace_id,
                        JobAttemptModel.job_id == job.id,
                        JobAttemptModel.state == "RUNNING",
                    )
                    .order_by(JobAttemptModel.attempt_no.desc())
                    .with_for_update()
                )
                if previous is not None:
                    previous.state = "SUPERSEDED"
                    previous.error_class = "LEASE_EXPIRED"
                    previous.finished_at = now
                    await session.flush()
            lease_token = secrets.token_urlsafe(32)
            lease_token_hash = hashlib.sha256(lease_token.encode()).hexdigest()
            await _set_claim_context(
                session,
                subject_id=system_actor_id,
                raw_token=lease_token,
            )
            if job is None:
                job = JobModel(
                    id=uuid7(),
                    workspace_id=change_request.workspace_id,
                    job_type=self.job_type,
                    causation_id=change_request.change_request_id,
                    state="RUNNING",
                    requested_by=change_request.requester_id,
                    progress={},
                    result_ref=None,
                    lease_until=now + timedelta(seconds=lease_seconds),
                    attempts=1,
                    attempt_cycle=1,
                    cycle_attempts=1,
                    lease_token_hash=lease_token_hash,
                    lease_owner_id=system_actor_id,
                    last_error_code=None,
                    version=1,
                )
                session.add(job)
            else:
                job.attempts += 1
                job.cycle_attempts += 1
                job.state = "RUNNING"
                job.lease_until = now + timedelta(seconds=lease_seconds)
                job.lease_token_hash = lease_token_hash
                job.lease_owner_id = system_actor_id
                job.last_error_code = None
                job.version += 1
                job.updated_at = now
            await session.flush()
            attempt = JobAttemptModel(
                id=uuid7(),
                workspace_id=change_request.workspace_id,
                job_id=job.id,
                attempt_no=job.attempts,
                worker_id=worker_id,
                state="RUNNING",
                error_class=None,
                external_response_hash=None,
                started_at=now,
                finished_at=None,
            )
            session.add(attempt)
            await session.flush()
            if was_queued:
                decision_id = self._append_system_decision(
                    session=session,
                    workspace_id=change_request.workspace_id,
                    subject_id=system_actor_id,
                    resource_id=change_request.change_request_id,
                    action="system.change.apply",
                    request_id=str(job.id),
                    decided_at=now,
                )
                change_request.transition(
                    target=ChangeState.APPLYING,
                    actor_id=system_actor_id,
                    reason="Durable DataHub application worker claimed the request.",
                    policy_decision_id=decision_id,
                    expected_version=change_request.version,
                )
                await repository.save(change_request)
                await SqlOutboxWriter(session).add_events(change_request.events)
                await session.flush()
        change_request.events.clear()
        return GovernanceApplyClaim(
            change_request=change_request,
            job_id=job.id,
            attempt_id=attempt.id,
            attempt_no=attempt.attempt_no,
            lease_token=lease_token,
            worker_subject_id=system_actor_id,
        )

    async def _terminalize_exhausted_job(
        self,
        *,
        session: AsyncSession,
        repository: SqlChangeRequestRepository,
        change_request: Any,
        job: JobModel,
        system_actor_id: UUID,
        now: datetime,
    ) -> None:
        await _set_claim_context(
            session,
            subject_id=system_actor_id,
            raw_token=None,
        )
        previous = await session.scalar(
            select(JobAttemptModel)
            .where(
                JobAttemptModel.workspace_id == job.workspace_id,
                JobAttemptModel.job_id == job.id,
                JobAttemptModel.state == "RUNNING",
            )
            .order_by(JobAttemptModel.attempt_no.desc())
            .with_for_update()
        )
        if previous is not None:
            previous.state = "FAILED"
            previous.error_class = "WORKER_LEASE_EXHAUSTED"
            previous.finished_at = now
            await session.flush()
        decision_id = self._append_system_decision(
            session=session,
            workspace_id=change_request.workspace_id,
            subject_id=system_actor_id,
            resource_id=change_request.change_request_id,
            action="system.change.fail",
            request_id=str(job.id),
            decided_at=now,
        )
        change_request.transition(
            target=ChangeState.APPLY_FAILED,
            actor_id=system_actor_id,
            reason="DataHub application worker lease exhausted.",
            policy_decision_id=decision_id,
            expected_version=change_request.version,
        )
        await repository.save(change_request)
        await SqlOutboxWriter(session).add_events(change_request.events)
        await session.flush()
        job.state = "FAILED"
        job.lease_until = None
        job.lease_token_hash = None
        job.lease_owner_id = None
        job.last_error_code = "WORKER_LEASE_EXHAUSTED"
        job.version += 1
        job.updated_at = now

    async def mark_applied(
        self,
        *,
        claim: GovernanceApplyClaim,
        system_actor_id: UUID,
        expected_hash: str,
        observed_hash: str,
        item_results: Sequence[dict[str, Any]],
    ) -> None:
        async with self._session_factory() as session, session.begin():
            await _set_claim_context(
                session,
                subject_id=claim.worker_subject_id,
                raw_token=claim.lease_token,
            )
            now = await _database_now(session)
            repository = SqlChangeRequestRepository(session)
            current = await repository.get_for_update(
                workspace_id=claim.change_request.workspace_id,
                change_request_id=claim.change_request.change_request_id,
            )
            job, attempt = await self._job_and_attempt(session, claim)
            if current is None or job is None or attempt is None:
                return
            if not self._claim_is_current(job=job, attempt=attempt, claim=claim, now=now):
                return
            if current.state is ChangeState.APPLIED:
                return
            decision_id = self._append_system_decision(
                session=session,
                workspace_id=current.workspace_id,
                subject_id=system_actor_id,
                resource_id=current.change_request_id,
                action="system.change.reconcile",
                request_id=str(job.id),
                decided_at=now,
            )
            current.mark_applied(
                actor_id=system_actor_id,
                policy_decision_id=decision_id,
                expected_version=current.version,
                expected_hash=expected_hash,
                observed_hash=observed_hash,
                reconciled=True,
            )
            await repository.save(current)
            await SqlOutboxWriter(session).add_events(current.events)
            attempt.state = "COMPLETED"
            attempt.external_response_hash = observed_hash
            attempt.finished_at = now
            await session.flush()
            job.state = "COMPLETED"
            job.progress = {"items": list(item_results), "content_hash": observed_hash}
            job.result_ref = f"change-request:{current.change_request_id}"
            job.lease_until = None
            job.lease_token_hash = None
            job.lease_owner_id = None
            job.last_error_code = None
            job.version += 1
            job.updated_at = now

    async def mark_failed(
        self,
        *,
        claim: GovernanceApplyClaim,
        system_actor_id: UUID,
        error_code: str,
        retryable: bool,
        maximum_attempts: int,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            await _set_claim_context(
                session,
                subject_id=claim.worker_subject_id,
                raw_token=claim.lease_token,
            )
            now = await _database_now(session)
            repository = SqlChangeRequestRepository(session)
            current = await repository.get_for_update(
                workspace_id=claim.change_request.workspace_id,
                change_request_id=claim.change_request.change_request_id,
            )
            job, attempt = await self._job_and_attempt(session, claim)
            if current is None or job is None or attempt is None:
                return
            if not self._claim_is_current(job=job, attempt=attempt, claim=claim, now=now):
                return
            if current.state is ChangeState.APPLIED:
                return
            attempt.state = "FAILED"
            attempt.error_class = error_code
            attempt.finished_at = now
            if retryable and job.cycle_attempts < maximum_attempts:
                await session.flush()
                delay = min(2 ** min(job.attempts, 6), 60)
                job.state = "RETRY_WAIT"
                job.lease_until = now + timedelta(seconds=delay)
                job.lease_token_hash = None
                job.lease_owner_id = None
                job.last_error_code = error_code
                job.updated_at = now
                job.version += 1
                return
            if current.state is ChangeState.APPLYING:
                decision_id = self._append_system_decision(
                    session=session,
                    workspace_id=current.workspace_id,
                    subject_id=system_actor_id,
                    resource_id=current.change_request_id,
                    action="system.change.fail",
                    request_id=str(job.id),
                    decided_at=now,
                )
                current.transition(
                    target=ChangeState.APPLY_FAILED,
                    actor_id=system_actor_id,
                    reason=f"DataHub application failed: {error_code}",
                    policy_decision_id=decision_id,
                    expected_version=current.version,
                )
                await repository.save(current)
                await SqlOutboxWriter(session).add_events(current.events)
            await session.flush()
            job.state = "FAILED"
            job.lease_until = None
            job.lease_token_hash = None
            job.lease_owner_id = None
            job.last_error_code = error_code
            job.updated_at = now
            job.version += 1

    async def renew_lease(
        self,
        *,
        claim: GovernanceApplyClaim,
        lease_seconds: int,
    ) -> bool:
        if lease_seconds < 1:
            raise ValueError("The governance apply lease is invalid.")
        async with self._session_factory() as session, session.begin():
            await _set_claim_context(
                session,
                subject_id=claim.worker_subject_id,
                raw_token=claim.lease_token,
            )
            now = await _database_now(session)
            job, attempt = await self._job_and_attempt(session, claim)
            if job is None or attempt is None:
                return False
            if not self._claim_is_current(job=job, attempt=attempt, claim=claim, now=now):
                return False
            job.lease_until = now + timedelta(seconds=lease_seconds)
            job.updated_at = now
            return True

    @staticmethod
    async def _job_and_attempt(
        session: AsyncSession, claim: GovernanceApplyClaim
    ) -> tuple[JobModel | None, JobAttemptModel | None]:
        job = await session.get(JobModel, claim.job_id, with_for_update=True)
        attempt = await session.get(JobAttemptModel, claim.attempt_id, with_for_update=True)
        return job, attempt

    @staticmethod
    def _claim_is_current(
        *,
        job: JobModel,
        attempt: JobAttemptModel,
        claim: GovernanceApplyClaim,
        now: datetime,
    ) -> bool:
        """Fence a late worker after another attempt has reclaimed the same job."""

        return (
            job.id == claim.job_id
            and attempt.id == claim.attempt_id
            and attempt.job_id == job.id
            and attempt.workspace_id == job.workspace_id
            and claim.attempt_no == job.attempts == attempt.attempt_no
            and job.state == "RUNNING"
            and attempt.state == "RUNNING"
            and job.lease_until is not None
            and job.lease_until > now
            and job.lease_owner_id == claim.worker_subject_id
            and job.lease_token_hash == hashlib.sha256(claim.lease_token.encode()).hexdigest()
        )

    @staticmethod
    def _append_system_decision(
        *,
        session: AsyncSession,
        workspace_id: UUID,
        subject_id: UUID,
        resource_id: UUID,
        action: str,
        request_id: str,
        decided_at: datetime,
    ) -> UUID:
        decision_id = uuid7()
        session.add(
            PolicyDecisionModel(
                id=decision_id,
                workspace_id=workspace_id,
                subject_id=subject_id,
                resource_id=resource_id,
                action=action,
                effect=Effect.ALLOW.value,
                reason_codes=["SCOPED_SYSTEM_WORKER"],
                policy_versions=["system-worker-v1"],
                evaluation_context={
                    "kind": "system_worker",
                    "workspace_id": str(workspace_id),
                    "correlation_id": request_id,
                },
                request_id=request_id,
                decided_at=decided_at,
            )
        )
        return decision_id


async def _database_now(session: AsyncSession) -> datetime:
    value = await session.scalar(select(func.clock_timestamp()))
    if not isinstance(value, datetime):
        raise RuntimeError("PostgreSQL clock_timestamp() did not return a timestamp.")
    return value


async def _set_claim_context(
    session: AsyncSession,
    *,
    subject_id: UUID,
    raw_token: str | None,
) -> None:
    await session.scalar(
        select(
            func.set_config(
                "app.subject_id",
                str(subject_id),
                True,
            )
        )
    )
    await session.scalar(
        select(
            func.set_config(
                "app.governance_apply_lease_token",
                raw_token or "",
                True,
            )
        )
    )
