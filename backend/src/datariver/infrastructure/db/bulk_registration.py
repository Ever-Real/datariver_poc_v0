from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from typing import TypeGuard
from uuid import UUID

from sqlalchemy import and_, func, insert, or_, select, true
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.application.dto import ObjectMetadata
from datariver.application.services.bulk_registration import (
    BulkPreparationClaim,
    BulkPreparationExecutionStore,
)
from datariver.application.typed_upload_parser import (
    DATASET_DESCRIPTION_CANDIDATE_EVIDENCE_VERSION,
    DATASET_DESCRIPTION_CANDIDATE_KIND,
    DatasetDescriptionCandidateDraft,
    DatasetDescriptionParseSummary,
    advance_dataset_description_candidate_root,
    dataset_description_candidate_hash,
    dataset_description_candidate_root_seed,
    dataset_description_submitted_identity_hash,
)
from datariver.application.typed_upload_profiles import typed_profile_definition
from datariver.domain.catalog import DATASET_ASSET_TYPES
from datariver.domain.common import (
    ConflictError,
    DomainEvent,
    canonical_json_hash,
    uuid7,
)
from datariver.domain.registration import UploadContentProfile
from datariver.domain.registration_worker import (
    RegistrationWorkerCallIdentity,
    RegistrationWorkerCallReplay,
)
from datariver.infrastructure.db.governance import SqlOutboxWriter
from datariver.infrastructure.db.models.catalog import AssetProjectionModel
from datariver.infrastructure.db.models.integration import (
    ObjectManifestModel,
    RegistrationWorkerCallReceiptModel,
    UploadPreparationJobModel,
    UploadPreparationReceiptModel,
    UploadRegistrationCandidateModel,
)
from datariver.infrastructure.db.registration_worker_receipts import (
    SqlRegistrationWorkerCallReceipts,
)
from datariver.infrastructure.db.rls import set_security_context

_CANDIDATE_BATCH_SIZE = 500
_MAXIMUM_EXHAUSTED_BULK_RECOVERIES_PER_CLAIM = 100
_REGISTRATION_RECOVERY_LIMIT_STATE = "RECOVERY_LIMIT_REACHED"


class SqlBulkPreparationExecutionStore(BulkPreparationExecutionStore):
    """Lease and atomically publish typed preparation evidence.

    The parser writes only to attempt-local storage. This store is the sole publication boundary:
    the current lease token, immutable manifest evidence, active catalog identity, receipt,
    candidates and terminal READY transition are checked/written in one transaction.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def claim_next(
        self,
        *,
        workspace_id: UUID,
        worker_subject_id: UUID,
        lease_seconds: int,
        maximum_attempts: int,
        run_call: RegistrationWorkerCallIdentity | None = None,
    ) -> BulkPreparationClaim | RegistrationWorkerCallReplay | None:
        async with self._session_factory() as session, session.begin():
            await set_security_context(
                session,
                workspace_id=workspace_id,
                subject_id=worker_subject_id,
            )
            now = await _database_now(session)
            receipts = SqlRegistrationWorkerCallReceipts(session)
            call_receipt = (
                await receipts.lock(workspace_id=workspace_id, identity=run_call)
                if run_call is not None
                else None
            )
            if call_receipt is not None:
                if call_receipt.state == "COMPLETED":
                    return receipts.replay(call_receipt)
                receipts.require_reclaimable(call_receipt, now=now)
                if (
                    call_receipt.work_kind == "BULK"
                    and call_receipt.work_id is not None
                    and call_receipt.claim_attempt is not None
                ):
                    superseded = await session.scalar(
                        select(UploadPreparationJobModel)
                        .where(
                            UploadPreparationJobModel.workspace_id == workspace_id,
                            UploadPreparationJobModel.id == call_receipt.work_id,
                            UploadPreparationJobModel.attempts > call_receipt.claim_attempt,
                        )
                        .with_for_update()
                    )
                    newer_canonical_receipt = await session.scalar(
                        select(RegistrationWorkerCallReceiptModel.key_hash)
                        .where(
                            RegistrationWorkerCallReceiptModel.workspace_id == workspace_id,
                            RegistrationWorkerCallReceiptModel.worker_subject_id
                            == worker_subject_id,
                            RegistrationWorkerCallReceiptModel.work_kind == "BULK",
                            RegistrationWorkerCallReceiptModel.work_id == call_receipt.work_id,
                            RegistrationWorkerCallReceiptModel.claim_attempt
                            > call_receipt.claim_attempt,
                            RegistrationWorkerCallReceiptModel.key_hash != call_receipt.key_hash,
                        )
                        .limit(1)
                    )
                    if superseded is not None and newer_canonical_receipt is not None:
                        result = {
                            "processed": True,
                            "preparation_id": str(superseded.id),
                            "state": "SUPERSEDED",
                            "item_count": None,
                        }
                        await receipts.complete(
                            receipt=call_receipt,
                            result=result,
                            now=now,
                        )
                        return RegistrationWorkerCallReplay(result=result)
            preferred_preparation_id = (
                call_receipt.work_id
                if call_receipt is not None and call_receipt.work_kind == "BULK"
                else None
            )
            row: Row[tuple[UploadPreparationJobModel, ObjectManifestModel]] | None = None
            for _ in range(_MAXIMUM_EXHAUSTED_BULK_RECOVERIES_PER_CLAIM):
                row = (
                    await session.execute(
                        select(UploadPreparationJobModel, ObjectManifestModel)
                        .join(
                            ObjectManifestModel,
                            and_(
                                ObjectManifestModel.workspace_id
                                == UploadPreparationJobModel.workspace_id,
                                ObjectManifestModel.id == UploadPreparationJobModel.upload_id,
                            ),
                        )
                        .where(
                            UploadPreparationJobModel.workspace_id == workspace_id,
                            (
                                UploadPreparationJobModel.id == preferred_preparation_id
                                if preferred_preparation_id is not None
                                else true()
                            ),
                            or_(
                                and_(
                                    UploadPreparationJobModel.state == "QUEUED",
                                    UploadPreparationJobModel.attempts < maximum_attempts,
                                    UploadPreparationJobModel.next_attempt_at.is_not(None),
                                    UploadPreparationJobModel.next_attempt_at <= now,
                                ),
                                and_(
                                    UploadPreparationJobModel.state == "PREPARING",
                                    UploadPreparationJobModel.lease_until <= now,
                                ),
                            ),
                        )
                        .order_by(
                            UploadPreparationJobModel.created_at,
                            UploadPreparationJobModel.id,
                        )
                        .with_for_update(of=UploadPreparationJobModel, skip_locked=True)
                        .limit(1)
                    )
                ).one_or_none()
                if row is None:
                    if call_receipt is not None:
                        raise ConflictError(
                            "The previous worker claim is not yet safely reclaimable.",
                            details={
                                "code": "WORKER_RUN_RECOVERY_PENDING",
                                "retryable": True,
                            },
                        )
                    if run_call is None:
                        return None
                    return await receipts.complete_no_work(
                        workspace_id=workspace_id,
                        identity=run_call,
                        existing=None,
                        result={
                            "processed": False,
                            "preparation_id": None,
                            "state": None,
                            "item_count": None,
                        },
                        now=now,
                    )
                job, _ = row
                if job.state == "PREPARING" and job.attempts >= maximum_attempts:
                    job.state = "FAILED"
                    job.next_attempt_at = None
                    job.lease_token = None
                    job.lease_until = None
                    job.last_error_code = "WORKER_LEASE_EXHAUSTED"
                    job.version += 1
                    job.updated_at = now
                    await SqlOutboxWriter(session).add_events(
                        (
                            DomainEvent.create(
                                event_type="registration.upload.preparation_failed.v1",
                                aggregate_type="upload_preparation",
                                aggregate_id=job.id,
                                workspace_id=job.workspace_id,
                                payload={
                                    "error_code": "WORKER_LEASE_EXHAUSTED",
                                    "preparation_id": str(job.id),
                                    "upload_id": str(job.upload_id),
                                },
                            ),
                        )
                    )
                    # The session is configured with autoflush disabled. Make
                    # the terminal state visible before the next claim scan.
                    await session.flush()
                    if (
                        call_receipt is not None
                        and call_receipt.work_id == job.id
                        and run_call is not None
                    ):
                        result = {
                            "processed": True,
                            "preparation_id": str(job.id),
                            "state": "FAILED",
                            "item_count": None,
                        }
                        await receipts.complete(receipt=call_receipt, result=result, now=now)
                        return RegistrationWorkerCallReplay(result=result)
                    row = None
                    continue
                break
            if row is None:
                if run_call is not None:
                    if call_receipt is not None:
                        raise ConflictError(
                            "The previous worker claim still requires a terminal replay.",
                            details={
                                "code": "WORKER_RUN_TERMINAL_RETRY",
                                "retryable": True,
                            },
                        )
                    return await receipts.complete_no_work(
                        workspace_id=workspace_id,
                        identity=run_call,
                        existing=None,
                        result={
                            "processed": False,
                            "preparation_id": None,
                            "state": _REGISTRATION_RECOVERY_LIMIT_STATE,
                            "item_count": None,
                        },
                        now=now,
                    )
                return None
            job, manifest = row
            lease_token = uuid7()
            job.state = "PREPARING"
            job.next_attempt_at = None
            job.lease_token = lease_token
            job.lease_until = now + timedelta(seconds=lease_seconds)
            job.attempts += 1
            job.rows_processed = 0
            job.total_rows = None
            job.last_error_code = None
            job.version += 1
            job.updated_at = now
            assert job.lease_until is not None
            if run_call is not None:
                # The receipt trigger verifies its hash/expiry against this canonical claim.
                await session.flush()
                await receipts.start(
                    workspace_id=workspace_id,
                    identity=run_call,
                    existing=call_receipt,
                    work_kind="BULK",
                    work_id=job.id,
                    claim_attempt=job.attempts,
                    raw_claim_token=str(lease_token),
                    lease_expires_at=job.lease_until,
                    now=now,
                )
                await session.flush()
                await receipts.complete_superseded_for_newer_claim(
                    workspace_id=workspace_id,
                    worker_subject_id=worker_subject_id,
                    work_kind="BULK",
                    work_id=job.id,
                    newer_claim_attempt=job.attempts,
                    newer_key_hash=run_call.key_hash,
                    result={
                        "processed": True,
                        "preparation_id": str(job.id),
                        "state": "SUPERSEDED",
                        "item_count": None,
                    },
                    now=now,
                )
            scanner_version = manifest.validation_summary.get("validator_version")
            return BulkPreparationClaim(
                workspace_id=job.workspace_id,
                preparation_id=job.id,
                upload_id=job.upload_id,
                requested_by=job.requested_by,
                content_profile=UploadContentProfile(job.content_profile),
                source_manifest_version=job.source_manifest_version,
                source_sha256=job.source_sha256,
                configuration_hash=job.configuration_hash,
                source_bucket=manifest.bucket,
                source_object_key=manifest.object_key,
                source_size_bytes=manifest.actual_size_bytes or manifest.size_bytes,
                source_content_type=manifest.actual_mime or manifest.mime,
                scanner_version=(scanner_version if isinstance(scanner_version, str) else ""),
                lease_token=lease_token,
                attempt=job.attempts,
                run_call=run_call,
            )

    async def publish(
        self,
        *,
        claim: BulkPreparationClaim,
        object_metadata: ObjectMetadata,
        summary: DatasetDescriptionParseSummary,
        candidates: Callable[[], Iterator[DatasetDescriptionCandidateDraft]],
    ) -> bool:
        receipt_id = uuid7()
        async with self._session_factory() as session, session.begin():
            await set_security_context(
                session,
                workspace_id=claim.workspace_id,
                subject_id=(
                    claim.run_call.worker_subject_id
                    if claim.run_call is not None
                    else claim.requested_by
                ),
            )
            now = await _database_now(session)
            job = await session.scalar(
                select(UploadPreparationJobModel)
                .where(
                    UploadPreparationJobModel.workspace_id == claim.workspace_id,
                    UploadPreparationJobModel.id == claim.preparation_id,
                    UploadPreparationJobModel.upload_id == claim.upload_id,
                )
                .with_for_update()
            )
            if not _claim_is_current(job, claim, now=now):
                await self._complete_worker_call(
                    session=session,
                    claim=claim,
                    result={
                        "processed": True,
                        "preparation_id": str(claim.preparation_id),
                        "state": "SUPERSEDED",
                        "item_count": None,
                    },
                    now=now,
                )
                return False
            manifest = await session.scalar(
                select(ObjectManifestModel)
                .where(
                    ObjectManifestModel.workspace_id == claim.workspace_id,
                    ObjectManifestModel.id == claim.upload_id,
                )
                .with_for_update(read=True)
            )
            if not _manifest_is_current(manifest=manifest, claim=claim):
                raise ConflictError(
                    "The accepted BULK manifest evidence changed during preparation."
                )
            if (
                summary.source_sha256 != claim.source_sha256
                or summary.configuration_hash != claim.configuration_hash
                or not claim.scanner_version.strip()
                or object_metadata.bucket != claim.source_bucket
                or object_metadata.object_key != claim.source_object_key
                or object_metadata.size_bytes != claim.source_size_bytes
            ):
                raise ConflictError("The BULK preparation result evidence does not reconcile.")

            item_count = await self._verify_current_targets(
                session=session,
                claim=claim,
                candidates=candidates,
            )
            if item_count != summary.item_count or item_count < 1:
                raise ConflictError("The BULK preparation candidate count does not reconcile.")

            locator_hash = canonical_json_hash(
                {
                    "bucket": claim.source_bucket,
                    "contract": "bulk-preparation-object-locator-v1",
                    "object_key": claim.source_object_key,
                    "workspace_id": str(claim.workspace_id),
                }
            )
            receipt_hash = canonical_json_hash(
                {
                    "accepted_etag": object_metadata.etag or None,
                    "candidate_root_hash": summary.candidate_root_hash,
                    "configuration_hash": summary.configuration_hash,
                    "content_profile": claim.content_profile.value,
                    "contract": "bulk-preparation-receipt-v1",
                    "item_count": item_count,
                    "manifest_version": claim.source_manifest_version,
                    "object_locator_hash": locator_hash,
                    "parser_version": summary.parser_version,
                    "preparation_id": str(claim.preparation_id),
                    "scanner_version": claim.scanner_version,
                    "schema_version": summary.schema_version,
                    "source_sha256": claim.source_sha256,
                    "upload_id": str(claim.upload_id),
                    "workspace_id": str(claim.workspace_id),
                }
            )
            session.add(
                UploadPreparationReceiptModel(
                    id=receipt_id,
                    workspace_id=claim.workspace_id,
                    preparation_job_id=claim.preparation_id,
                    upload_id=claim.upload_id,
                    manifest_version=claim.source_manifest_version,
                    source_sha256=claim.source_sha256,
                    accepted_sha256=claim.source_sha256,
                    object_locator_hash=locator_hash,
                    accepted_etag=object_metadata.etag or None,
                    accepted_version_id=None,
                    content_profile=claim.content_profile.value,
                    parser_version=summary.parser_version,
                    scanner_version=claim.scanner_version,
                    schema_version=summary.schema_version,
                    configuration_hash=summary.configuration_hash,
                    item_count=item_count,
                    rejected_count=summary.rejected_count,
                    candidate_root_hash=summary.candidate_root_hash,
                    receipt_hash=receipt_hash,
                    observed_at=now,
                    created_at=now,
                )
            )
            # Candidate rows use a Core bulk INSERT below. Flush the ORM receipt first so the
            # composite receipt foreign key is visible before those rows are checked.
            await session.flush()
            inserted_count, inserted_root_hash = await self._insert_candidates(
                session=session,
                receipt_id=receipt_id,
                claim=claim,
                candidates=candidates,
                created_at=now,
            )
            if inserted_count != item_count or inserted_root_hash != summary.candidate_root_hash:
                raise ConflictError("The published BULK candidate root does not reconcile.")
            job.state = "READY"
            job.next_attempt_at = None
            job.lease_token = None
            job.lease_until = None
            job.rows_processed = item_count
            job.total_rows = item_count
            job.last_error_code = None
            job.version += 1
            job.updated_at = now
            await SqlOutboxWriter(session).add_events(
                (
                    DomainEvent.create(
                        event_type="registration.upload.preparation_ready.v1",
                        aggregate_type="upload_preparation",
                        aggregate_id=claim.preparation_id,
                        workspace_id=claim.workspace_id,
                        payload={
                            "content_profile": claim.content_profile.value,
                            "item_count": item_count,
                            "preparation_id": str(claim.preparation_id),
                            "upload_id": str(claim.upload_id),
                        },
                    ),
                )
            )
            await self._complete_worker_call(
                session=session,
                claim=claim,
                result={
                    "processed": True,
                    "preparation_id": str(claim.preparation_id),
                    "state": "READY",
                    "item_count": item_count,
                },
                now=now,
            )
            return True

    async def mark_failed(
        self,
        *,
        claim: BulkPreparationClaim,
        error_code: str,
        retryable: bool,
        maximum_attempts: int,
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            await set_security_context(
                session,
                workspace_id=claim.workspace_id,
                subject_id=(
                    claim.run_call.worker_subject_id
                    if claim.run_call is not None
                    else claim.requested_by
                ),
            )
            now = await _database_now(session)
            job = await session.scalar(
                select(UploadPreparationJobModel)
                .where(
                    UploadPreparationJobModel.workspace_id == claim.workspace_id,
                    UploadPreparationJobModel.id == claim.preparation_id,
                )
                .with_for_update()
            )
            if not _claim_is_current(job, claim, now=now):
                await self._complete_worker_call(
                    session=session,
                    claim=claim,
                    result={
                        "processed": True,
                        "preparation_id": str(claim.preparation_id),
                        "state": "SUPERSEDED",
                        "item_count": None,
                    },
                    now=now,
                )
                return False
            will_retry = retryable and job.attempts < maximum_attempts
            job.state = "QUEUED" if will_retry else "FAILED"
            job.next_attempt_at = (
                now + timedelta(seconds=_retry_delay_seconds(job.attempts)) if will_retry else None
            )
            job.lease_token = None
            job.lease_until = None
            job.last_error_code = error_code[:100]
            job.version += 1
            job.updated_at = now
            await SqlOutboxWriter(session).add_events(
                (
                    DomainEvent.create(
                        event_type="registration.upload.preparation_retry_queued.v1"
                        if will_retry
                        else "registration.upload.preparation_failed.v1",
                        aggregate_type="upload_preparation",
                        aggregate_id=claim.preparation_id,
                        workspace_id=claim.workspace_id,
                        payload={
                            "error_code": error_code[:100],
                            "preparation_id": str(claim.preparation_id),
                            "upload_id": str(claim.upload_id),
                        },
                    ),
                )
            )
            await self._complete_worker_call(
                session=session,
                claim=claim,
                result={
                    "processed": True,
                    "preparation_id": str(claim.preparation_id),
                    "state": "QUEUED" if will_retry else "FAILED",
                    "item_count": None,
                },
                now=now,
            )
            return True

    async def _complete_worker_call(
        self,
        *,
        session: AsyncSession,
        claim: BulkPreparationClaim,
        result: dict[str, object],
        now: datetime,
    ) -> None:
        if claim.run_call is None:
            return
        receipts = SqlRegistrationWorkerCallReceipts(session)
        receipt = await receipts.lock(workspace_id=claim.workspace_id, identity=claim.run_call)
        if receipt is None:
            raise ConflictError(
                "The durable worker run receipt is unavailable.",
                details={
                    "code": "WORKER_RUN_TERMINAL_RETRY",
                    "retryable": True,
                },
            )
        if receipt.state == "COMPLETED":
            if receipt.result == result:
                return
            raise ConflictError(
                "The worker run terminal result must be replayed.",
                details={
                    "code": "WORKER_RUN_TERMINAL_RETRY",
                    "retryable": True,
                },
            )
        expected_token_hash = hashlib.sha256(str(claim.lease_token).encode()).hexdigest()
        if receipt.state != "RUNNING" or receipt.claim_token_hash != expected_token_hash:
            raise ConflictError(
                "The worker run terminal claim is no longer current.",
                details={
                    "code": "WORKER_RUN_TERMINAL_RETRY",
                    "retryable": True,
                },
            )
        await receipts.complete(
            receipt=receipt,
            result=result,
            now=now,
            raw_claim_token=str(claim.lease_token),
        )

    async def _verify_current_targets(
        self,
        *,
        session: AsyncSession,
        claim: BulkPreparationClaim,
        candidates: Callable[[], Iterator[DatasetDescriptionCandidateDraft]],
    ) -> int:
        count = 0
        batch: list[DatasetDescriptionCandidateDraft] = []
        for candidate in candidates():
            batch.append(candidate)
            if len(batch) == _CANDIDATE_BATCH_SIZE:
                await _verify_target_batch(session=session, claim=claim, values=batch)
                count += len(batch)
                batch.clear()
        if batch:
            await _verify_target_batch(session=session, claim=claim, values=batch)
            count += len(batch)
        return count

    async def _insert_candidates(
        self,
        *,
        session: AsyncSession,
        receipt_id: UUID,
        claim: BulkPreparationClaim,
        candidates: Callable[[], Iterator[DatasetDescriptionCandidateDraft]],
        created_at: datetime,
    ) -> tuple[int, str]:
        batch: list[dict[str, object]] = []
        expected_ordinal = 1
        candidate_root = dataset_description_candidate_root_seed()
        definition = typed_profile_definition(claim.content_profile)
        for candidate in candidates():
            submitted_identity_hash = dataset_description_submitted_identity_hash(
                workspace_id=claim.workspace_id,
                target_asset_id=candidate.target_asset_id,
                platform=candidate.platform,
                database_name=candidate.database_name,
                schema_name=candidate.schema_name,
                table_name=candidate.table_name,
            )
            candidate_hash = dataset_description_candidate_hash(
                workspace_id=claim.workspace_id,
                target_asset_id=candidate.target_asset_id,
                proposed_description=candidate.proposed_description,
                submitted_identity_hash=submitted_identity_hash,
                definition=definition,
            )
            if (
                candidate.workspace_id != claim.workspace_id
                or candidate.ordinal != expected_ordinal
                or candidate.candidate_kind != DATASET_DESCRIPTION_CANDIDATE_KIND
                or candidate.evidence_version != DATASET_DESCRIPTION_CANDIDATE_EVIDENCE_VERSION
                or candidate.submitted_identity_hash != submitted_identity_hash
                or candidate.candidate_hash != candidate_hash
            ):
                raise ConflictError("The staged BULK candidate evidence is invalid.")
            candidate_root = advance_dataset_description_candidate_root(
                current=candidate_root,
                ordinal=candidate.ordinal,
                candidate_hash=candidate_hash,
            )
            batch.append(
                {
                    "id": uuid7(),
                    "workspace_id": claim.workspace_id,
                    "receipt_id": receipt_id,
                    "ordinal": candidate.ordinal,
                    "target_asset_id": candidate.target_asset_id,
                    "candidate_kind": candidate.candidate_kind,
                    "proposed_description": candidate.proposed_description,
                    "evidence_version": candidate.evidence_version,
                    "submitted_platform": candidate.platform,
                    "submitted_database_name": candidate.database_name,
                    "submitted_schema_name": candidate.schema_name,
                    "submitted_table_name": candidate.table_name,
                    "submitted_identity_hash": candidate.submitted_identity_hash,
                    "candidate_hash": candidate.candidate_hash,
                    "created_at": created_at,
                }
            )
            expected_ordinal += 1
            if len(batch) == _CANDIDATE_BATCH_SIZE:
                await session.execute(insert(UploadRegistrationCandidateModel), batch)
                batch.clear()
        if batch:
            await session.execute(insert(UploadRegistrationCandidateModel), batch)
        return expected_ordinal - 1, candidate_root.hex()


async def _verify_target_batch(
    *,
    session: AsyncSession,
    claim: BulkPreparationClaim,
    values: list[DatasetDescriptionCandidateDraft],
) -> None:
    if any(value.workspace_id != claim.workspace_id for value in values):
        raise ConflictError("The staged BULK candidate crossed a workspace boundary.")
    models = list(
        (
            await session.scalars(
                select(AssetProjectionModel)
                .where(
                    AssetProjectionModel.workspace_id == claim.workspace_id,
                    AssetProjectionModel.id.in_(tuple(value.target_asset_id for value in values)),
                    AssetProjectionModel.asset_type.in_(tuple(sorted(DATASET_ASSET_TYPES))),
                    AssetProjectionModel.lifecycle == "ACTIVE",
                    AssetProjectionModel.deleted_at.is_(None),
                )
                .with_for_update(read=True)
            )
        ).all()
    )
    by_id = {model.id: model for model in models}
    if len(by_id) != len(values):
        raise ConflictError("A BULK candidate target is unavailable or inactive.")
    for value in values:
        model = by_id.get(value.target_asset_id)
        if model is None or (
            model.platform,
            model.database_name,
            model.schema_name,
            model.name,
        ) != (
            value.platform,
            value.database_name,
            value.schema_name,
            value.table_name,
        ):
            raise ConflictError("A BULK candidate target identity changed during preparation.")


def _claim_is_current(
    job: UploadPreparationJobModel | None,
    claim: BulkPreparationClaim,
    *,
    now: datetime,
) -> TypeGuard[UploadPreparationJobModel]:
    return bool(
        job is not None
        and job.state == "PREPARING"
        and job.lease_token == claim.lease_token
        and job.attempts == claim.attempt
        and job.lease_until is not None
        and job.lease_until > now
    )


def _retry_delay_seconds(attempt: int) -> int:
    return int(min(2 ** min(max(attempt, 1), 6), 60))


async def _database_now(session: AsyncSession) -> datetime:
    value = await session.scalar(select(func.clock_timestamp()))
    if not isinstance(value, datetime):
        raise RuntimeError("PostgreSQL clock_timestamp() did not return a timestamp.")
    return value


def _manifest_is_current(
    *,
    manifest: ObjectManifestModel | None,
    claim: BulkPreparationClaim,
) -> bool:
    return bool(
        manifest is not None
        and manifest.state == "ACCEPTED"
        and manifest.version == claim.source_manifest_version
        and manifest.content_profile == claim.content_profile.value
        and manifest.sha256 == claim.source_sha256
        and manifest.actual_sha256 == claim.source_sha256
        and manifest.bucket == claim.source_bucket
        and manifest.object_key == claim.source_object_key
        and (manifest.actual_size_bytes or manifest.size_bytes) == claim.source_size_bytes
        and (manifest.actual_mime or manifest.mime) == claim.source_content_type
    )
