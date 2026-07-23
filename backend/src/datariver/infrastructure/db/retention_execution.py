from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.application.dto import (
    ArchiveCapabilityEvidence,
    ArchiveCapabilityRecord,
    RetentionArchiveVerification,
    RetentionExecutionClaim,
)
from datariver.application.ports import RetentionExecutionStore
from datariver.domain.authz import Action, Classification
from datariver.domain.common import ConflictError, DomainError, canonical_json_hash, uuid7
from datariver.domain.retention import (
    AUTOMATION_DISABLED,
    ArchiveCapability,
    ArchiveRetentionMode,
    ArchiveSource,
    ErasureRequest,
    ErasureRequestState,
    ErasureTargetSnapshot,
    ErasureTargetType,
    RetentionArchiveDisposition,
    RetentionDataClass,
    RetentionExecutionCommand,
    RetentionExecutionState,
    RetentionPolicyState,
)
from datariver.infrastructure.db.models.assistant import ChatSessionModel
from datariver.infrastructure.db.models.authz import PolicyDecisionModel
from datariver.infrastructure.db.models.platform import (
    AccessRoleAssignmentModel,
    AccessRoleModel,
    SubjectModel,
    WorkspaceMembershipModel,
    WorkspaceModel,
)
from datariver.infrastructure.db.models.retention import (
    ErasureRequestModel,
    LegalHoldModel,
    RetentionExecutionAttemptModel,
    RetentionExecutionEventModel,
    RetentionExecutionJobModel,
)
from datariver.infrastructure.db.retention import (
    SqlArchiveEvidenceRepository,
    SqlErasureRequestRepository,
    SqlRetentionPolicyRepository,
)
from datariver.infrastructure.db.rls import set_security_context

_RECOVERY_TRANSIENT_PREFIX = "ARCHIVE_RECOVERY_TRANSIENT_"
_MAXIMUM_RECOVERY_FENCES = 3


class SqlRetentionExecutionStore(RetentionExecutionStore):
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        archive_bucket: str,
        archive_prefix: str,
        encryption_profile_fingerprint: str,
    ) -> None:
        self._session_factory = session_factory
        self._archive_bucket = archive_bucket
        self._archive_prefix = archive_prefix
        self._encryption_profile_fingerprint = encryption_profile_fingerprint
        self._planner_cursors: dict[UUID, tuple[datetime, UUID] | None] = {}

    async def plan_next(
        self,
        *,
        workspace_id: UUID,
        executor_id: UUID,
        archive_configuration_hash: str,
        maximum_attempts: int,
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            await self._prepare_workspace(session, workspace_id)
            now = await _db_now(session)
            cursor = self._planner_cursors.get(workspace_id)
            candidates = await _approved_request_page(
                session, workspace_id=workspace_id, cursor=cursor
            )
            if not candidates and cursor is not None:
                self._planner_cursors[workspace_id] = None
                candidates = await _approved_request_page(
                    session, workspace_id=workspace_id, cursor=None
                )
            for candidate in candidates:
                if candidate.decided_at is None:  # pragma: no cover - approved-state invariant
                    continue
                self._planner_cursors[workspace_id] = (candidate.decided_at, candidate.id)
                request = await SqlErasureRequestRepository(session).get(
                    workspace_id=workspace_id, erasure_request_id=candidate.id
                )
                if request is None:
                    continue
                policy = await SqlRetentionPolicyRepository(session).get_active(
                    workspace_id=workspace_id
                )
                target = await _locked_chat_target(
                    session, workspace_id=workspace_id, target_id=request.target_id
                )
                if policy is None or target is None:
                    continue
                maker_eligible = await _human_is_currently_eligible(
                    session,
                    request=request,
                    actor_id=request.requester_id,
                    action=Action.ERASURE_REQUEST,
                    policy_decision_id=request.request_policy_decision_id,
                    now=now,
                )
                checker_eligible = bool(
                    request.checker_id is not None
                    and request.decision_policy_decision_id is not None
                    and await _human_is_currently_eligible(
                        session,
                        request=request,
                        actor_id=request.checker_id,
                        action=Action.ERASURE_APPROVE,
                        policy_decision_id=request.decision_policy_decision_id,
                        now=now,
                    )
                )
                hold = await _chat_has_blocking_hold(
                    session,
                    workspace_id=workspace_id,
                    target_id=target.target_id,
                    owner_id=target.owner_id,
                )
                try:
                    command = RetentionExecutionCommand.plan(
                        request=request,
                        policy=policy,
                        target=target,
                        executor_id=executor_id,
                        active_legal_hold=hold,
                        maker_currently_eligible=maker_eligible,
                        checker_currently_eligible=checker_eligible,
                        now=now,
                    )
                    if policy.contract is None:  # pragma: no cover - domain already rejects
                        continue
                    audit_rule = policy.contract.rule_for(RetentionDataClass.AUDIT_EVIDENCE)
                    if (
                        audit_rule.archive_disposition
                        is not RetentionArchiveDisposition.EVIDENCE_ONLY
                    ):
                        continue
                    archive_retain_until = audit_rule.maximum_until(now)
                except DomainError:
                    continue
                session.add(
                    RetentionExecutionJobModel(
                        id=command.command_id,
                        workspace_id=workspace_id,
                        kind="EXPLICIT_ERASURE_EVIDENCE",
                        erasure_request_id=command.erasure_request_id,
                        erasure_request_version=command.erasure_request_version,
                        erasure_request_payload_hash=command.erasure_request_payload_hash,
                        target_type=command.target_type.value,
                        target_id=command.target_id,
                        target_version=command.target_version,
                        target_owner_id=command.target_owner_id,
                        classification=int(command.classification),
                        target_snapshot_hash=command.target_snapshot_hash,
                        retention_policy_id=command.retention_policy_id,
                        retention_policy_hash=command.retention_policy_hash,
                        policy_number=command.retention_policy_number,
                        requester_id=command.requester_id,
                        checker_id=command.checker_id,
                        executor_id=command.executor_id,
                        execution_authorization_valid_until=(
                            command.execution_authorization_valid_until
                        ),
                        archive_disposition=command.archive_disposition.value,
                        archive_configuration_hash=archive_configuration_hash,
                        command_hash=command.command_hash,
                        archive_retain_until=archive_retain_until,
                        state=RetentionExecutionState.PLANNED.value,
                        next_attempt_at=now,
                        attempt_count=0,
                        maximum_attempts=maximum_attempts,
                        lease_epoch=0,
                        lease_token_hash=None,
                        lease_owner_fingerprint=None,
                        lease_until=None,
                        archive_receipt_id=None,
                        archive_manifest_hash=None,
                        last_failure_code=None,
                        destructive_state=AUTOMATION_DISABLED,
                        created_at=command.planned_at,
                        updated_at=command.planned_at,
                        version=1,
                    )
                )
                # The event FK targets the new job, but the ORM models intentionally expose no
                # mutable relationship between append-only evidence and its aggregate. Flush the
                # aggregate explicitly so PostgreSQL never observes the event first.
                await session.flush()
                session.add(
                    RetentionExecutionEventModel(
                        id=uuid7(),
                        workspace_id=workspace_id,
                        execution_job_id=command.command_id,
                        sequence=1,
                        event_type=RetentionExecutionState.PLANNED.value,
                        attempt_no=None,
                        reason_code=None,
                        evidence_hash=command.command_hash,
                        occurred_at=now,
                    )
                )
                return True
            return False

    async def claim_next(
        self,
        *,
        workspace_id: UUID,
        worker_id: str,
        worker_principal_fingerprint: str,
        lease_seconds: int,
    ) -> RetentionExecutionClaim | None:
        async with self._session_factory() as session, session.begin():
            await self._prepare_workspace(session, workspace_id)
            now = await _db_now(session)
            job: RetentionExecutionJobModel | None = None
            recovery_only = False
            for _candidate_no in range(25):
                candidate = (
                    await session.scalars(
                        select(RetentionExecutionJobModel)
                        .where(
                            RetentionExecutionJobModel.workspace_id == workspace_id,
                            or_(
                                and_(
                                    RetentionExecutionJobModel.state.in_(
                                        (
                                            RetentionExecutionState.PLANNED.value,
                                            RetentionExecutionState.RETRY_WAIT.value,
                                        )
                                    ),
                                    RetentionExecutionJobModel.next_attempt_at <= now,
                                    RetentionExecutionJobModel.attempt_count
                                    < RetentionExecutionJobModel.maximum_attempts,
                                ),
                                and_(
                                    RetentionExecutionJobModel.state
                                    == RetentionExecutionState.LEASED.value,
                                    RetentionExecutionJobModel.lease_until <= now,
                                ),
                                and_(
                                    RetentionExecutionJobModel.state
                                    == RetentionExecutionState.RETRY_WAIT.value,
                                    RetentionExecutionJobModel.next_attempt_at <= now,
                                    func.left(
                                        func.coalesce(
                                            RetentionExecutionJobModel.last_failure_code, ""
                                        ),
                                        len(_RECOVERY_TRANSIENT_PREFIX),
                                    )
                                    == _RECOVERY_TRANSIENT_PREFIX,
                                ),
                            ),
                        )
                        .order_by(
                            RetentionExecutionJobModel.next_attempt_at,
                            RetentionExecutionJobModel.created_at,
                            RetentionExecutionJobModel.id,
                        )
                        .with_for_update(skip_locked=True)
                        .limit(1)
                    )
                ).one_or_none()
                if candidate is None:
                    return None
                if candidate.state == RetentionExecutionState.LEASED.value or (
                    candidate.state == RetentionExecutionState.RETRY_WAIT.value
                    and (candidate.last_failure_code or "").startswith(_RECOVERY_TRANSIENT_PREFIX)
                ):
                    # Any lost write lease may already have committed its deterministic object.
                    # Fence it with a read-only recovery claim before governance revalidation or
                    # another PutObject attempt. Transient read failures reuse the same bounded
                    # recovery lane without consuming the write-attempt budget.
                    recovery_fence_count = await _recovery_fence_count(session, candidate)
                    if not 0 <= recovery_fence_count < _MAXIMUM_RECOVERY_FENCES:
                        if candidate.state == RetentionExecutionState.LEASED.value:
                            await _finish_current_attempt(
                                session,
                                job=candidate,
                                now=now,
                                state=RetentionExecutionState.BLOCKED.value,
                                stage="RECOVERY_BUDGET_EXHAUSTED",
                                failure_code="ARCHIVE_RECOVERY_BUDGET_EXHAUSTED",
                            )
                        await _block_job(
                            session,
                            job=candidate,
                            now=now,
                            reason="ARCHIVE_RECOVERY_BUDGET_EXHAUSTED",
                            attempt_no=candidate.attempt_count,
                        )
                        continue
                    job = candidate
                    recovery_only = True
                    break
                if not await _job_is_current(session, job=candidate, now=now):
                    if candidate.state == RetentionExecutionState.LEASED.value:
                        await _finish_current_attempt(
                            session,
                            job=candidate,
                            now=now,
                            state=RetentionExecutionState.BLOCKED.value,
                            stage="CLAIM_REVALIDATION_FAILED",
                            failure_code="CLAIM_REVALIDATION_FAILED",
                        )
                    await _block_job(
                        session,
                        job=candidate,
                        now=now,
                        reason="CLAIM_REVALIDATION_FAILED",
                        attempt_no=(
                            candidate.attempt_count
                            if candidate.state == RetentionExecutionState.LEASED.value
                            else None
                        ),
                    )
                    continue
                job = candidate
                break
            if job is None:
                return None
            if job.state == RetentionExecutionState.LEASED.value:
                await _finish_current_attempt(
                    session,
                    job=job,
                    now=now,
                    state="SUPERSEDED",
                    stage="LEASE_EXPIRED_RECOVERY",
                    failure_code="LEASE_EXPIRED_RECOVERY",
                )
            raw_token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
            if not recovery_only:
                job.attempt_count += 1
            job.lease_epoch += 1
            job.state = RetentionExecutionState.LEASED.value
            job.lease_token_hash = token_hash
            job.lease_owner_fingerprint = worker_principal_fingerprint
            job.lease_until = now + timedelta(seconds=lease_seconds)
            job.last_failure_code = None
            job.version += 1
            job.updated_at = now
            correlation_id = f"retention-{job.id}-{job.lease_epoch}"[:100]
            attempt = RetentionExecutionAttemptModel(
                id=uuid7(),
                workspace_id=workspace_id,
                execution_job_id=job.id,
                attempt_no=job.attempt_count,
                lease_epoch=job.lease_epoch,
                lease_token_hash=token_hash,
                worker_principal_fingerprint=worker_principal_fingerprint,
                correlation_id=correlation_id,
                state="RUNNING",
                stage="RECOVERY_CLAIMED" if recovery_only else "CLAIMED",
                evidence_hash=canonical_json_hash(
                    {
                        "job_id": str(job.id),
                        "command_hash": job.command_hash,
                        "lease_epoch": job.lease_epoch,
                        "worker_id_hash": hashlib.sha256(worker_id.encode()).hexdigest(),
                    }
                ),
                external_response_hash=None,
                failure_code=None,
                destructive_effect_count=0,
                started_at=now,
                finished_at=None,
            )
            session.add(attempt)
            session.add(
                RetentionExecutionEventModel(
                    id=uuid7(),
                    workspace_id=workspace_id,
                    execution_job_id=job.id,
                    sequence=await _next_event_sequence(session, job.id),
                    event_type=RetentionExecutionState.LEASED.value,
                    attempt_no=job.attempt_count,
                    reason_code=None,
                    evidence_hash=attempt.evidence_hash,
                    occurred_at=now,
                )
            )
            request = await session.get(ErasureRequestModel, job.erasure_request_id)
            if request is None or request.decided_at is None:
                raise ConflictError("The claimed erasure request evidence disappeared.")
            return RetentionExecutionClaim(
                job_id=job.id,
                attempt_id=attempt.id,
                workspace_id=workspace_id,
                erasure_request_id=job.erasure_request_id,
                erasure_request_version=job.erasure_request_version,
                erasure_request_payload_hash=job.erasure_request_payload_hash,
                command_hash=job.command_hash,
                target_type=job.target_type,
                target_id=job.target_id,
                target_version=job.target_version,
                target_snapshot_hash=job.target_snapshot_hash,
                classification=Classification(job.classification).name,
                retention_policy_id=job.retention_policy_id,
                retention_policy_hash=job.retention_policy_hash,
                policy_number=job.policy_number,
                request_decided_at=request.decided_at,
                planned_at=job.created_at,
                archive_retain_until=job.archive_retain_until,
                lease_token=raw_token,
                lease_epoch=job.lease_epoch,
                attempt_count=job.attempt_count,
                maximum_attempts=job.maximum_attempts,
                worker_principal_fingerprint=worker_principal_fingerprint,
                archive_configuration_hash=job.archive_configuration_hash,
                encryption_profile_fingerprint=self._encryption_profile_fingerprint,
                archive_bucket=self._archive_bucket,
                archive_prefix=self._archive_prefix,
                correlation_id=correlation_id,
                recovery_only=recovery_only,
            )

    async def revalidate_before_archive(self, *, claim: RetentionExecutionClaim) -> bool:
        async with self._session_factory() as session, session.begin():
            await self._prepare_workspace(session, claim.workspace_id)
            now = await _db_now(session)
            job = await _locked_job(session, claim)
            return bool(
                job is not None
                and _lease_matches(job, claim, now)
                and await _job_is_current(session, job=job, now=now)
            )

    async def record_archive_capability(
        self,
        *,
        claim: RetentionExecutionClaim,
        capability: ArchiveCapability,
        evidence: ArchiveCapabilityEvidence,
    ) -> ArchiveCapabilityRecord:
        async with self._session_factory() as session, session.begin():
            await self._prepare_workspace(session, claim.workspace_id)
            now = await _db_now(session)
            job = await _locked_job(session, claim)
            if claim.recovery_only or job is None or not _lease_matches(job, claim, now):
                raise ConflictError("Archive capability requires a current write lease.")
            if not await _job_is_current(session, job=job, now=now):
                raise ConflictError("Retention governance changed before capability attestation.")
            if not _archive_capability_matches_claim(
                claim=claim,
                capability=capability,
                evidence=evidence,
                archive_bucket=self._archive_bucket,
                encryption_profile_fingerprint=self._encryption_profile_fingerprint,
            ):
                raise ConflictError("Archive capability lost its execution-command binding.")
            capability.assert_usable(now=now)
            attestation_id = await SqlArchiveEvidenceRepository(session).ensure_capability(
                workspace_id=claim.workspace_id,
                capability=capability,
                evidence=evidence,
            )
            return ArchiveCapabilityRecord(
                attestation_id=attestation_id,
                capability=capability,
                evidence=evidence,
            )

    async def get_archive_capability_for_write(
        self,
        *,
        claim: RetentionExecutionClaim,
        attestation_id: UUID,
        written_at: datetime,
    ) -> ArchiveCapabilityRecord | None:
        async with self._session_factory() as session, session.begin():
            await self._prepare_workspace(session, claim.workspace_id)
            now = await _db_now(session)
            job = await _locked_job(session, claim)
            if job is None or not _lease_matches(job, claim, now):
                return None
            return await SqlArchiveEvidenceRepository(session).get_capability_for_write(
                workspace_id=claim.workspace_id,
                attestation_id=attestation_id,
                configuration_fingerprint=claim.archive_configuration_hash,
                encryption_profile_fingerprint=self._encryption_profile_fingerprint,
                runtime_principal_fingerprint=claim.worker_principal_fingerprint,
                object_bucket=self._archive_bucket,
                written_at=written_at,
            )

    async def complete_archive(
        self,
        *,
        claim: RetentionExecutionClaim,
        verification: RetentionArchiveVerification,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            await self._prepare_workspace(session, claim.workspace_id)
            now = await _db_now(session)
            job = await _locked_job(session, claim)
            if job is None or not _lease_matches(job, claim, now):
                raise ConflictError("The retention execution lease was lost.")
            if not await _job_is_current(session, job=job, now=now):
                raise ConflictError("Retention governance changed before archive completion.")
            if not _archive_verification_matches_job(
                job=job,
                claim=claim,
                verification=verification,
                archive_bucket=self._archive_bucket,
                archive_prefix=self._archive_prefix,
                encryption_profile_fingerprint=self._encryption_profile_fingerprint,
            ):
                raise ConflictError("Archive verification lost its execution-command binding.")
            evidence_repository = SqlArchiveEvidenceRepository(session)
            await evidence_repository.add_receipt(
                capability_attestation_id=verification.capability_attestation_id,
                receipt=verification.receipt,
                evidence=verification.evidence,
            )
            await session.flush()
            attempt = await _current_attempt(session, job)
            if attempt is None or attempt.id != claim.attempt_id:
                raise ConflictError("The retention execution attempt was superseded.")
            job.state = RetentionExecutionState.ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED.value
            job.archive_receipt_id = verification.receipt.receipt_id
            job.archive_manifest_hash = verification.evidence.manifest_hash
            job.lease_token_hash = None
            job.lease_owner_fingerprint = None
            job.lease_until = None
            job.last_failure_code = None
            job.version += 1
            job.updated_at = now
            attempt.state = RetentionExecutionState.ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED.value
            attempt.stage = "ARCHIVE_VERIFIED"
            attempt.evidence_hash = verification.receipt.content_sha256
            attempt.external_response_hash = canonical_json_hash(
                {"provider_checksum": verification.receipt.provider_checksum}
            )
            attempt.finished_at = now
            session.add(
                RetentionExecutionEventModel(
                    id=uuid7(),
                    workspace_id=claim.workspace_id,
                    execution_job_id=job.id,
                    sequence=await _next_event_sequence(session, job.id),
                    event_type=(
                        RetentionExecutionState.ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED.value
                    ),
                    attempt_no=job.attempt_count,
                    reason_code="DESTRUCTIVE_GATE_CLOSED",
                    evidence_hash=verification.receipt.content_sha256,
                    occurred_at=now,
                )
            )

    async def mark_failed(
        self,
        *,
        claim: RetentionExecutionClaim,
        error_code: str,
        retryable: bool,
        orphan_verification: RetentionArchiveVerification | None = None,
    ) -> str | None:
        async with self._session_factory() as session, session.begin():
            await self._prepare_workspace(session, claim.workspace_id)
            now = await _db_now(session)
            job = await _locked_job(session, claim)
            if job is None or not _lease_matches(job, claim, now):
                return None
            attempt = await _current_attempt(session, job)
            if attempt is None or attempt.id != claim.attempt_id:
                return None
            bounded_code = error_code[:100] or "UNKNOWN_FAILURE"
            recovery_fence_count = await _recovery_fence_count(session, job)
            orphan_receipt_hash: str | None = None
            if orphan_verification is not None:
                if (
                    bounded_code != "KILL_SWITCH_DISABLED_AFTER_WRITE"
                    and not bounded_code.startswith("POST_WRITE_RECEIPT_")
                ) or retryable:
                    raise ConflictError("Orphan archive evidence has an invalid failure binding.")
                if not _archive_verification_matches_job(
                    job=job,
                    claim=claim,
                    verification=orphan_verification,
                    archive_bucket=self._archive_bucket,
                    archive_prefix=self._archive_prefix,
                    encryption_profile_fingerprint=self._encryption_profile_fingerprint,
                ):
                    raise ConflictError(
                        "Orphan archive evidence lost its execution-command binding."
                    )
                evidence_repository = SqlArchiveEvidenceRepository(session)
                await evidence_repository.add_receipt(
                    capability_attestation_id=orphan_verification.capability_attestation_id,
                    receipt=orphan_verification.receipt,
                    evidence=orphan_verification.evidence,
                )
                await session.flush()
                job.archive_receipt_id = orphan_verification.receipt.receipt_id
                job.archive_manifest_hash = orphan_verification.evidence.manifest_hash
                orphan_receipt_hash = canonical_json_hash(
                    {
                        "receipt_id": str(orphan_verification.receipt.receipt_id),
                        "object_bucket": orphan_verification.receipt.object_bucket,
                        "object_key": orphan_verification.receipt.object_key,
                        "object_version_id": orphan_verification.receipt.object_version_id,
                        "content_sha256": orphan_verification.receipt.content_sha256,
                        "manifest_hash": orphan_verification.evidence.manifest_hash,
                    }
                )
            can_retry_recovery = bool(
                retryable
                and bounded_code.startswith(_RECOVERY_TRANSIENT_PREFIX)
                and 0 <= recovery_fence_count < _MAXIMUM_RECOVERY_FENCES
            )
            can_retry = can_retry_recovery or (
                retryable and job.attempt_count < job.maximum_attempts
            )
            job.state = (
                RetentionExecutionState.RETRY_WAIT.value
                if can_retry
                else RetentionExecutionState.BLOCKED.value
            )
            job.next_attempt_at = now + timedelta(seconds=min(2 ** min(job.attempt_count, 6), 60))
            job.lease_token_hash = None
            job.lease_owner_fingerprint = None
            job.lease_until = None
            job.last_failure_code = bounded_code
            job.version += 1
            job.updated_at = now
            attempt.state = job.state
            attempt.stage = "FAILED"
            attempt.failure_code = bounded_code
            if orphan_receipt_hash is not None:
                attempt.external_response_hash = orphan_receipt_hash
            attempt.finished_at = now
            session.add(
                RetentionExecutionEventModel(
                    id=uuid7(),
                    workspace_id=claim.workspace_id,
                    execution_job_id=job.id,
                    sequence=await _next_event_sequence(session, job.id),
                    event_type=job.state,
                    attempt_no=job.attempt_count,
                    reason_code=bounded_code,
                    evidence_hash=orphan_receipt_hash
                    or canonical_json_hash(
                        {
                            "job_id": str(job.id),
                            "lease_epoch": claim.lease_epoch,
                            "failure_code": bounded_code,
                            "destructive_effect_count": 0,
                        }
                    ),
                    occurred_at=now,
                )
            )
            return job.state

    @staticmethod
    async def _prepare_workspace(session: AsyncSession, workspace_id: UUID) -> None:
        await set_security_context(session, workspace_id=workspace_id, subject_id=None)
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"datariver:retention:workspace:{workspace_id}"},
        )


async def _approved_request_page(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    cursor: tuple[datetime, UUID] | None,
) -> tuple[ErasureRequestModel, ...]:
    statement = (
        select(ErasureRequestModel)
        .outerjoin(
            RetentionExecutionJobModel,
            and_(
                RetentionExecutionJobModel.workspace_id == ErasureRequestModel.workspace_id,
                RetentionExecutionJobModel.erasure_request_id == ErasureRequestModel.id,
            ),
        )
        .where(
            ErasureRequestModel.workspace_id == workspace_id,
            ErasureRequestModel.state == ErasureRequestState.APPROVED.value,
            ErasureRequestModel.target_type == ErasureTargetType.CHAT_SESSION.value,
            ErasureRequestModel.decided_at.is_not(None),
            RetentionExecutionJobModel.id.is_(None),
        )
    )
    if cursor is not None:
        decided_at, request_id = cursor
        statement = statement.where(
            or_(
                ErasureRequestModel.decided_at > decided_at,
                and_(
                    ErasureRequestModel.decided_at == decided_at,
                    ErasureRequestModel.id > request_id,
                ),
            )
        )
    return tuple(
        await session.scalars(
            statement.order_by(ErasureRequestModel.decided_at, ErasureRequestModel.id).limit(25)
        )
    )


async def _locked_chat_target(
    session: AsyncSession, *, workspace_id: UUID, target_id: UUID
) -> ErasureTargetSnapshot | None:
    model = (
        await session.scalars(
            select(ChatSessionModel).where(
                ChatSessionModel.workspace_id == workspace_id,
                ChatSessionModel.id == target_id,
            )
        )
    ).one_or_none()
    if model is None:
        return None
    return ErasureTargetSnapshot(
        target_type=ErasureTargetType.CHAT_SESSION,
        target_id=model.id,
        version=model.version,
        owner_id=model.owner_id,
        classification=Classification.RESTRICTED,
        retention_basis_at=model.retention_basis_at,
        retention_until=model.retention_until,
    )


async def _human_is_currently_eligible(
    session: AsyncSession,
    *,
    request: ErasureRequest,
    actor_id: UUID,
    action: Action,
    policy_decision_id: UUID,
    now: datetime,
) -> bool:
    workspace = await session.get(WorkspaceModel, request.workspace_id)
    subject = await session.get(SubjectModel, actor_id)
    row = (
        await session.execute(
            select(WorkspaceMembershipModel, AccessRoleAssignmentModel, AccessRoleModel)
            .join(
                AccessRoleAssignmentModel,
                and_(
                    AccessRoleAssignmentModel.workspace_id == WorkspaceMembershipModel.workspace_id,
                    AccessRoleAssignmentModel.subject_id == WorkspaceMembershipModel.subject_id,
                ),
            )
            .join(
                AccessRoleModel,
                and_(
                    AccessRoleModel.workspace_id == AccessRoleAssignmentModel.workspace_id,
                    AccessRoleModel.id == AccessRoleAssignmentModel.role_id,
                ),
            )
            .where(
                WorkspaceMembershipModel.workspace_id == request.workspace_id,
                WorkspaceMembershipModel.subject_id == actor_id,
            )
        )
    ).one_or_none()
    if row is None:
        return False
    membership, assignment, role = row
    access = _current_membership_access(membership=membership, role=role)
    if access is None:
        return False
    groups, allowed_actions, denied_actions, access_payload_hash = access
    if (
        workspace is None
        or workspace.status != "ACTIVE"
        or subject is None
        or not subject.active
        or not membership.active
        or membership.clearance < int(Classification.RESTRICTED)
        or membership.job_function == "SERVICE_ACCOUNT"
        or (membership.access_expires_at is not None and membership.access_expires_at <= now)
        or not assignment.active
        or assignment.membership_version != membership.version
        or assignment.role_version != role.version
        or assignment.access_payload_hash != access_payload_hash
        or not role.active
        or "security-administrators" not in groups
        or "service-accounts" in groups
        or action.value not in allowed_actions
        or action.value in denied_actions
    ):
        return False
    decision = await session.get(PolicyDecisionModel, policy_decision_id)
    authentication_time: datetime | None = None
    if decision is not None:
        authentication_time_value = decision.evaluation_context.get("authentication_time")
        if isinstance(authentication_time_value, str):
            try:
                authentication_time = datetime.fromisoformat(authentication_time_value)
            except ValueError:
                authentication_time = None
    if (
        decision is None
        or decision.decided_at is None
        or request.decided_at is None
        or authentication_time is None
        or authentication_time.tzinfo is None
        or authentication_time.utcoffset() is None
    ):
        return False
    return bool(
        decision.workspace_id == request.workspace_id
        and decision.subject_id == actor_id
        and decision.resource_id == request.target_id
        and decision.action == action.value
        and decision.effect == "ALLOW"
        and decision.evaluation_context.get("authentication_assurance") == "HARDWARE_WEBAUTHN"
        and authentication_time <= decision.decided_at <= request.decided_at <= now
    )


def _current_membership_access(
    *, membership: WorkspaceMembershipModel, role: AccessRoleModel
) -> tuple[frozenset[str], frozenset[str], frozenset[str], str] | None:
    attributes = membership.attributes
    if not isinstance(attributes, dict):
        return None
    try:
        groups = _string_values(attributes, "groups")
        allowed_actions = _string_values(attributes, "allowed_actions")
        denied_actions = _string_values(attributes, "denied_actions")
        allowed_system_ids = _uuid_values(attributes, "allowed_system_ids")
        allowed_domain_ids = _uuid_values(attributes, "allowed_domain_ids")
        role_groups = frozenset(_required_string_list(role.groups))
        role_allowed_actions = frozenset(
            Action(value).value for value in _required_string_list(role.allowed_actions)
        )
        role_denied_actions = frozenset(
            Action(value).value for value in _required_string_list(role.denied_actions)
        )
        role_system_ids = frozenset(
            str(UUID(value)) for value in _required_string_list(role.allowed_system_ids)
        )
        role_domain_ids = frozenset(
            str(UUID(value)) for value in _required_string_list(role.allowed_domain_ids)
        )
        expected_groups = role_groups | {f"datariver-role-{role.role_key}"}
        if (
            membership.clearance != role.clearance
            or groups != expected_groups
            or allowed_actions != role_allowed_actions
            or denied_actions != role_denied_actions
            or allowed_system_ids != role_system_ids
            or allowed_domain_ids != role_domain_ids
        ):
            return None
        payload_hash = canonical_json_hash(
            {
                "active": membership.active,
                "clearance": Classification(membership.clearance).name,
                "groups": sorted(groups),
                "allowed_actions": sorted(allowed_actions),
                "denied_actions": sorted(denied_actions),
                "allowed_system_ids": sorted(allowed_system_ids),
                "allowed_domain_ids": sorted(allowed_domain_ids),
            }
        )
    except (KeyError, TypeError, ValueError):
        return None
    return groups, allowed_actions, denied_actions, payload_hash


def _string_values(document: dict[str, object], key: str) -> frozenset[str]:
    return frozenset(_required_string_list(document.get(key)))


def _uuid_values(document: dict[str, object], key: str) -> frozenset[str]:
    return frozenset(str(UUID(value)) for value in _required_string_list(document.get(key)))


def _required_string_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("Expected a string list.")
    return tuple(value)


async def _chat_has_blocking_hold(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    target_id: UUID,
    owner_id: UUID | None,
) -> bool:
    subject_ids = {target_id}
    if owner_id is not None:
        subject_ids.add(owner_id)
    return (
        await session.scalar(
            select(LegalHoldModel.id)
            .where(
                LegalHoldModel.workspace_id == workspace_id,
                LegalHoldModel.state != "RELEASED",
                LegalHoldModel.data_class.in_(
                    (RetentionDataClass.CHAT_CONTENT.value, RetentionDataClass.AUDIT_EVIDENCE.value)
                ),
                or_(
                    LegalHoldModel.scope == "WORKSPACE",
                    and_(LegalHoldModel.scope == "RESOURCE", LegalHoldModel.scope_id == target_id),
                    and_(
                        LegalHoldModel.scope == "SUBJECT",
                        LegalHoldModel.scope_id.in_(subject_ids),
                    ),
                ),
            )
            .limit(1)
        )
        is not None
    )


async def _job_is_current(
    session: AsyncSession, *, job: RetentionExecutionJobModel, now: datetime
) -> bool:
    if (
        job.destructive_state != AUTOMATION_DISABLED
        or job.execution_authorization_valid_until <= now
        or job.archive_disposition != RetentionArchiveDisposition.EVIDENCE_ONLY.value
    ):
        return False
    request = (
        await session.scalars(
            select(ErasureRequestModel).where(
                ErasureRequestModel.workspace_id == job.workspace_id,
                ErasureRequestModel.id == job.erasure_request_id,
            )
        )
    ).one_or_none()
    if (
        request is None
        or request.state != ErasureRequestState.APPROVED.value
        or request.version != job.erasure_request_version
        or request.payload_hash != job.erasure_request_payload_hash
        or request.requester_id != job.requester_id
        or request.checker_id != job.checker_id
    ):
        return False
    policy = await SqlRetentionPolicyRepository(session).get_active(workspace_id=job.workspace_id)
    if (
        policy is None
        or policy.state is not RetentionPolicyState.ACTIVE
        or policy.policy_id != job.retention_policy_id
        or policy.payload_hash != job.retention_policy_hash
        or policy.policy_number != job.policy_number
        or policy.contract is None
    ):
        return False
    try:
        policy.contract.assert_effective(now=now)
    except DomainError:
        return False
    target = await _locked_chat_target(
        session, workspace_id=job.workspace_id, target_id=job.target_id
    )
    if target is None or _target_snapshot_hash(target) != job.target_snapshot_hash:
        return False
    hydrated_request = await SqlErasureRequestRepository(session).get(
        workspace_id=job.workspace_id, erasure_request_id=job.erasure_request_id
    )
    if hydrated_request is None:
        return False
    maker_ok = await _human_is_currently_eligible(
        session,
        request=hydrated_request,
        actor_id=job.requester_id,
        action=Action.ERASURE_REQUEST,
        policy_decision_id=hydrated_request.request_policy_decision_id,
        now=now,
    )
    checker_ok = bool(
        hydrated_request.decision_policy_decision_id is not None
        and await _human_is_currently_eligible(
            session,
            request=hydrated_request,
            actor_id=job.checker_id,
            action=Action.ERASURE_APPROVE,
            policy_decision_id=hydrated_request.decision_policy_decision_id,
            now=now,
        )
    )
    if not maker_ok or not checker_ok:
        return False
    return not await _chat_has_blocking_hold(
        session,
        workspace_id=job.workspace_id,
        target_id=job.target_id,
        owner_id=job.target_owner_id,
    )


def _target_snapshot_hash(target: ErasureTargetSnapshot) -> str:
    return canonical_json_hash(
        {
            "target_type": target.target_type.value,
            "target_id": str(target.target_id),
            "target_version": target.version,
            "target_owner_id": str(target.owner_id) if target.owner_id is not None else None,
            "classification": target.classification.name,
            "retention_basis_at": (
                target.retention_basis_at.isoformat()
                if target.retention_basis_at is not None
                else None
            ),
            "retention_until": (
                target.retention_until.isoformat() if target.retention_until is not None else None
            ),
        }
    )


async def _locked_job(
    session: AsyncSession, claim: RetentionExecutionClaim
) -> RetentionExecutionJobModel | None:
    return (
        await session.scalars(
            select(RetentionExecutionJobModel)
            .where(
                RetentionExecutionJobModel.workspace_id == claim.workspace_id,
                RetentionExecutionJobModel.id == claim.job_id,
            )
            .with_for_update()
        )
    ).one_or_none()


def _lease_matches(
    job: RetentionExecutionJobModel, claim: RetentionExecutionClaim, now: datetime
) -> bool:
    return bool(
        job.state == RetentionExecutionState.LEASED.value
        and job.lease_epoch == claim.lease_epoch
        and job.lease_owner_fingerprint == claim.worker_principal_fingerprint
        and job.lease_until is not None
        and job.lease_until > now
        and job.lease_token_hash == hashlib.sha256(claim.lease_token.encode("utf-8")).hexdigest()
    )


async def _current_attempt(
    session: AsyncSession, job: RetentionExecutionJobModel
) -> RetentionExecutionAttemptModel | None:
    return (
        await session.scalars(
            select(RetentionExecutionAttemptModel)
            .where(
                RetentionExecutionAttemptModel.workspace_id == job.workspace_id,
                RetentionExecutionAttemptModel.execution_job_id == job.id,
                RetentionExecutionAttemptModel.lease_epoch == job.lease_epoch,
            )
            .with_for_update()
        )
    ).one_or_none()


async def _recovery_fence_count(session: AsyncSession, job: RetentionExecutionJobModel) -> int:
    attempts_for_write = await session.scalar(
        select(func.count(RetentionExecutionAttemptModel.id)).where(
            RetentionExecutionAttemptModel.workspace_id == job.workspace_id,
            RetentionExecutionAttemptModel.execution_job_id == job.id,
            RetentionExecutionAttemptModel.attempt_no == job.attempt_count,
        )
    )
    return max(int(attempts_for_write or 0) - 1, 0)


async def _finish_current_attempt(
    session: AsyncSession,
    *,
    job: RetentionExecutionJobModel,
    now: datetime,
    state: str,
    stage: str,
    failure_code: str,
) -> None:
    attempt = await _current_attempt(session, job)
    if attempt is None or attempt.finished_at is not None:
        return
    attempt.state = state
    attempt.stage = stage
    attempt.failure_code = failure_code
    attempt.finished_at = now


async def _next_event_sequence(session: AsyncSession, job_id: UUID) -> int:
    maximum = await session.scalar(
        select(func.max(RetentionExecutionEventModel.sequence)).where(
            RetentionExecutionEventModel.execution_job_id == job_id
        )
    )
    return int(maximum or 0) + 1


async def _block_job(
    session: AsyncSession,
    *,
    job: RetentionExecutionJobModel,
    now: datetime,
    reason: str,
    attempt_no: int | None = None,
) -> None:
    job.state = RetentionExecutionState.BLOCKED.value
    job.lease_token_hash = None
    job.lease_owner_fingerprint = None
    job.lease_until = None
    job.last_failure_code = reason
    job.version += 1
    job.updated_at = now
    session.add(
        RetentionExecutionEventModel(
            id=uuid7(),
            workspace_id=job.workspace_id,
            execution_job_id=job.id,
            sequence=await _next_event_sequence(session, job.id),
            event_type=RetentionExecutionState.BLOCKED.value,
            attempt_no=attempt_no,
            reason_code=reason,
            evidence_hash=canonical_json_hash(
                {"job_id": str(job.id), "reason": reason, "destructive_effect_count": 0}
            ),
            occurred_at=now,
        )
    )


async def _db_now(session: AsyncSession) -> datetime:
    value = await session.scalar(select(func.transaction_timestamp()))
    if not isinstance(value, datetime):  # pragma: no cover - PostgreSQL contract
        raise RuntimeError("PostgreSQL did not return a transaction timestamp.")
    return value


def _archive_verification_matches_job(
    *,
    job: RetentionExecutionJobModel,
    claim: RetentionExecutionClaim,
    verification: RetentionArchiveVerification,
    archive_bucket: str,
    archive_prefix: str,
    encryption_profile_fingerprint: str,
) -> bool:
    capability = verification.capability
    capability_evidence = verification.capability_evidence
    receipt = verification.receipt
    evidence = verification.evidence
    expected_key = (
        f"{archive_prefix}/{claim.workspace_id}/{claim.job_id}/{evidence.manifest_hash}.jsonl"
    )
    return bool(
        capability.configuration_fingerprint == job.archive_configuration_hash
        and receipt.capability_fingerprint == job.archive_configuration_hash
        and capability_evidence.runtime_principal_fingerprint == claim.worker_principal_fingerprint
        and capability_evidence.encryption_profile_fingerprint == encryption_profile_fingerprint
        and capability_evidence.object_bucket == archive_bucket
        and receipt.workspace_id == claim.workspace_id
        and receipt.source is ArchiveSource.ERASURE_EXECUTION_EVIDENCE
        and capability.challenge_hash == capability_evidence.challenge_hash
        and receipt.object_bucket == archive_bucket
        and receipt.object_key == expected_key
        and receipt.retention_mode is ArchiveRetentionMode.COMPLIANCE
        and receipt.retention_until == claim.archive_retain_until
        and receipt.content_sha256 == evidence.readback_sha256
        and receipt.byte_count == evidence.readback_byte_count
        and evidence.requested_retention_until == claim.archive_retain_until
        and evidence.readback_retention_until == claim.archive_retain_until
        and evidence.retention_policy_id == job.retention_policy_id
        and evidence.retention_policy_hash == job.retention_policy_hash
        and job.execution_authorization_valid_until >= evidence.written_at + timedelta(seconds=1)
        and evidence.worker_principal_fingerprint == claim.worker_principal_fingerprint
        and evidence.correlation_id == claim.correlation_id
        and evidence.encryption_profile_fingerprint == encryption_profile_fingerprint
        and re.fullmatch(r"[0-9a-f]{64}", evidence.manifest_hash) is not None
    )


def _archive_capability_matches_claim(
    *,
    claim: RetentionExecutionClaim,
    capability: ArchiveCapability,
    evidence: ArchiveCapabilityEvidence,
    archive_bucket: str,
    encryption_profile_fingerprint: str,
) -> bool:
    return bool(
        capability.configuration_fingerprint == claim.archive_configuration_hash
        and capability.challenge_hash == evidence.challenge_hash
        and evidence.encryption_profile_fingerprint == encryption_profile_fingerprint
        and evidence.encryption_profile_fingerprint == claim.encryption_profile_fingerprint
        and evidence.runtime_principal_fingerprint == claim.worker_principal_fingerprint
        and evidence.object_bucket == archive_bucket
        and evidence.object_bucket == claim.archive_bucket
        and evidence.failure_code is None
    )
