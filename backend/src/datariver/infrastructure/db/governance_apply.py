from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.application.dto import GovernanceApplyClaim
from datariver.application.ports import GovernanceApplyStore
from datariver.domain.common import Effect, utc_now, uuid7
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
        now = utc_now()
        async with self._session_factory() as session, session.begin():
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
                        ChangeRequestModel.state == ChangeState.APPLY_QUEUED.value,
                        and_(
                            ChangeRequestModel.state == ChangeState.APPLYING.value,
                            JobModel.attempts < maximum_attempts,
                            or_(JobModel.lease_until.is_(None), JobModel.lease_until <= now),
                        ),
                    )
                )
                .order_by(ChangeRequestModel.created_at)
                .with_for_update(of=ChangeRequestModel, skip_locked=True)
                .limit(1)
            )
            model = (await session.scalars(statement)).one_or_none()
            if model is None:
                return None
            repository = SqlChangeRequestRepository(session)
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
                    lease_until=None,
                    attempts=0,
                    last_error_code=None,
                    version=1,
                )
                session.add(job)
                await session.flush()
            elif change_request.state is ChangeState.APPLY_QUEUED and job.state == "FAILED":
                # An authorized APPLY_FAILED -> APPLY_QUEUED transition starts a new retry budget.
                job.attempts = 0
                job.version += 1
            if change_request.state is ChangeState.APPLY_QUEUED:
                decision_id = self._append_system_decision(
                    session=session,
                    workspace_id=change_request.workspace_id,
                    subject_id=system_actor_id,
                    resource_id=change_request.change_request_id,
                    action="system.change.apply",
                    request_id=str(job.id),
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
            job.attempts += 1
            job.state = "RUNNING"
            job.lease_until = now + timedelta(seconds=lease_seconds)
            job.last_error_code = None
            job.updated_at = now
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
        change_request.events.clear()
        return GovernanceApplyClaim(
            change_request=change_request,
            job_id=job.id,
            attempt_id=attempt.id,
            attempt_no=attempt.attempt_no,
        )

    async def mark_applied(
        self,
        *,
        claim: GovernanceApplyClaim,
        system_actor_id: UUID,
        expected_hash: str,
        observed_hash: str,
        item_results: Sequence[dict[str, Any]],
    ) -> None:
        now = utc_now()
        async with self._session_factory() as session, session.begin():
            repository = SqlChangeRequestRepository(session)
            current = await repository.get_for_update(
                workspace_id=claim.change_request.workspace_id,
                change_request_id=claim.change_request.change_request_id,
            )
            job, attempt = await self._job_and_attempt(session, claim)
            if current is None or job is None or attempt is None:
                return
            if current.state is ChangeState.APPLIED:
                attempt.state = "SUPERSEDED"
                attempt.finished_at = now
                return
            decision_id = self._append_system_decision(
                session=session,
                workspace_id=current.workspace_id,
                subject_id=system_actor_id,
                resource_id=current.change_request_id,
                action="system.change.reconcile",
                request_id=str(job.id),
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
            job.state = "COMPLETED"
            job.progress = {"items": list(item_results), "content_hash": observed_hash}
            job.result_ref = f"change-request:{current.change_request_id}"
            job.lease_until = None
            job.last_error_code = None
            job.version += 1
            job.updated_at = now
            attempt.state = "COMPLETED"
            attempt.external_response_hash = observed_hash
            attempt.finished_at = now

    async def mark_failed(
        self,
        *,
        claim: GovernanceApplyClaim,
        system_actor_id: UUID,
        error_code: str,
        retryable: bool,
        maximum_attempts: int,
    ) -> None:
        now = utc_now()
        async with self._session_factory() as session, session.begin():
            repository = SqlChangeRequestRepository(session)
            current = await repository.get_for_update(
                workspace_id=claim.change_request.workspace_id,
                change_request_id=claim.change_request.change_request_id,
            )
            job, attempt = await self._job_and_attempt(session, claim)
            if current is None or job is None or attempt is None:
                return
            if current.state is ChangeState.APPLIED:
                attempt.state = "SUPERSEDED"
                attempt.finished_at = now
                return
            attempt.state = "FAILED"
            attempt.error_class = error_code
            attempt.finished_at = now
            job.last_error_code = error_code
            job.updated_at = now
            job.version += 1
            if retryable and job.attempts < maximum_attempts:
                delay = min(2 ** min(job.attempts, 6), 60)
                job.state = "RETRY_WAIT"
                job.lease_until = now + timedelta(seconds=delay)
                return
            if current.state is ChangeState.APPLYING:
                decision_id = self._append_system_decision(
                    session=session,
                    workspace_id=current.workspace_id,
                    subject_id=system_actor_id,
                    resource_id=current.change_request_id,
                    action="system.change.fail",
                    request_id=str(job.id),
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
            job.state = "FAILED"
            job.lease_until = None

    @staticmethod
    async def _job_and_attempt(
        session: AsyncSession, claim: GovernanceApplyClaim
    ) -> tuple[JobModel | None, JobAttemptModel | None]:
        job = await session.get(JobModel, claim.job_id, with_for_update=True)
        attempt = await session.get(JobAttemptModel, claim.attempt_id, with_for_update=True)
        return job, attempt

    @staticmethod
    def _append_system_decision(
        *,
        session: AsyncSession,
        workspace_id: UUID,
        subject_id: UUID,
        resource_id: UUID,
        action: str,
        request_id: str,
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
                decided_at=utc_now(),
            )
        )
        return decision_id
