from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from datariver.application.dto import (
    ArchiveCapabilityEvidence,
    ArchiveCapabilityRecord,
    ArchiveReceiptEvidence,
    RetentionArchiveVerification,
    RetentionExecutionClaim,
)
from datariver.application.errors import ExternalDependencyError
from datariver.application.ports import ImmutableArchiveStore, RetentionExecutionStore
from datariver.domain.common import DomainError, canonical_json_hash, utc_now, uuid7
from datariver.domain.retention import (
    ArchiveRetentionMode,
    ArchiveSource,
    ImmutableArchiveReceipt,
)


class RetentionExecutionPlanner:
    def __init__(
        self,
        *,
        store: RetentionExecutionStore,
        execution_enabled: bool | Callable[[], bool],
        executor_id: UUID,
        archive_configuration_hash: str,
        maximum_attempts: int,
        batch_size: int,
    ) -> None:
        self._store = store
        self._execution_enabled = execution_enabled
        self._executor_id = executor_id
        self._archive_configuration_hash = archive_configuration_hash
        self._maximum_attempts = maximum_attempts
        self._batch_size = batch_size

    async def run_once(self, *, workspace_id: UUID) -> int:
        if not self._enabled():
            return 0
        planned = 0
        while planned < self._batch_size and await self._store.plan_next(
            workspace_id=workspace_id,
            executor_id=self._executor_id,
            archive_configuration_hash=self._archive_configuration_hash,
            maximum_attempts=self._maximum_attempts,
        ):
            planned += 1
        return planned

    def _enabled(self) -> bool:
        return (
            self._execution_enabled()
            if callable(self._execution_enabled)
            else self._execution_enabled
        )


class RetentionArchiveOutcome(StrEnum):
    ARCHIVED = "archived"
    RETRY_SCHEDULED = "retry"
    BLOCKED = "blocked"
    LEASE_LOST = "lease_lost"


class RetentionArchiveWorker:
    def __init__(
        self,
        *,
        store: RetentionExecutionStore,
        archive: ImmutableArchiveStore,
        execution_enabled: bool | Callable[[], bool],
        worker_id: str,
        worker_principal_fingerprint: str,
        lease_seconds: int,
    ) -> None:
        self._store = store
        self._archive = archive
        self._execution_enabled = execution_enabled
        self._worker_id = worker_id
        self._worker_principal_fingerprint = worker_principal_fingerprint
        self._lease_seconds = lease_seconds

    async def run_once(self, *, workspace_id: UUID) -> RetentionArchiveOutcome | None:
        if not self._enabled():
            return None
        claim = await self._store.claim_next(
            workspace_id=workspace_id,
            worker_id=self._worker_id,
            worker_principal_fingerprint=self._worker_principal_fingerprint,
            lease_seconds=self._lease_seconds,
        )
        if claim is None:
            return None
        verification: RetentionArchiveVerification | None = None
        try:
            if claim.recovery_only:
                verification = await self._archive_evidence(claim, write_if_absent=False)
                persisted = await self._store.mark_failed(
                    claim=claim,
                    error_code="POST_WRITE_RECEIPT_RECOVERED",
                    retryable=False,
                    orphan_verification=verification,
                )
                return self._failure_outcome(persisted_state=persisted)
            if not await self._store.revalidate_before_archive(claim=claim):
                raise _ArchiveGateError("PRE_ARCHIVE_REVALIDATION_FAILED", retryable=False)
            if not self._enabled():
                raise _ArchiveGateError("KILL_SWITCH_DISABLED", retryable=False)
            verification = await self._archive_evidence(claim, write_if_absent=True)
            if not self._enabled():
                persisted = await self._store.mark_failed(
                    claim=claim,
                    error_code="KILL_SWITCH_DISABLED_AFTER_WRITE",
                    retryable=False,
                    orphan_verification=verification,
                )
                return self._failure_outcome(persisted_state=persisted)
            await self._store.complete_archive(claim=claim, verification=verification)
            return RetentionArchiveOutcome.ARCHIVED
        except _ArchiveGateError as error:
            persisted = await self._store.mark_failed(
                claim=claim,
                error_code=error.code,
                retryable=error.retryable if verification is None else False,
                orphan_verification=verification,
            )
            return self._failure_outcome(persisted_state=persisted)
        except ExternalDependencyError as error:
            retryable = bool(error.details.get("retryable", False))
            provider_code = str(error.details.get("provider_code") or error.code)
            persisted = await self._store.mark_failed(
                claim=claim,
                error_code=(
                    f"POST_WRITE_RECEIPT_{error.details.get('provider_code') or error.code}"[:100]
                    if verification is not None
                    else (
                        f"ARCHIVE_RECOVERY_TRANSIENT_{provider_code}"[:100]
                        if claim.recovery_only and retryable
                        else (
                            f"ARCHIVE_RECOVERY_{provider_code}"[:100]
                            if claim.recovery_only
                            else provider_code[:100]
                        )
                    )
                ),
                retryable=retryable if verification is None else False,
                orphan_verification=verification,
            )
            return self._failure_outcome(persisted_state=persisted)
        except DomainError as error:
            domain_code = str(error.details.get("code") or error.code)
            persisted = await self._store.mark_failed(
                claim=claim,
                error_code=(
                    f"POST_WRITE_RECEIPT_{error.details.get('code') or error.code}"[:100]
                    if verification is not None
                    else (
                        f"ARCHIVE_RECOVERY_{domain_code}"[:100]
                        if claim.recovery_only
                        else domain_code[:100]
                    )
                ),
                retryable=False,
                orphan_verification=verification,
            )
            return self._failure_outcome(persisted_state=persisted)
        except Exception as error:
            persisted = await self._store.mark_failed(
                claim=claim,
                error_code=(
                    f"POST_WRITE_RECEIPT_{type(error).__name__}"[:100]
                    if verification is not None
                    else (
                        f"ARCHIVE_RECOVERY_TRANSIENT_UNEXPECTED_{type(error).__name__}"[:100]
                        if claim.recovery_only
                        else f"UNEXPECTED_{type(error).__name__}"[:100]
                    )
                ),
                retryable=verification is None,
                orphan_verification=verification,
            )
            return self._failure_outcome(persisted_state=persisted)

    @staticmethod
    def _failure_outcome(*, persisted_state: str | None) -> RetentionArchiveOutcome:
        if persisted_state == "RETRY_WAIT":
            return RetentionArchiveOutcome.RETRY_SCHEDULED
        if persisted_state == "BLOCKED":
            return RetentionArchiveOutcome.BLOCKED
        return RetentionArchiveOutcome.LEASE_LOST

    async def _archive_evidence(
        self, claim: RetentionExecutionClaim, *, write_if_absent: bool
    ) -> RetentionArchiveVerification:
        document = _manifest_document(claim)
        manifest_hash = canonical_json_hash(document)
        content = (
            json.dumps(
                document,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
        )
        content_sha256 = hashlib.sha256(content).hexdigest()
        object_key = (
            f"{claim.archive_prefix}/{claim.workspace_id}/{claim.job_id}/{manifest_hash}.jsonl"
        )
        command_metadata = {
            "command-hash": claim.command_hash,
            "manifest-hash": manifest_hash,
        }
        capability_record: ArchiveCapabilityRecord | None = None
        write_receipt = await self._archive.find_archive(
            object_key=object_key,
            size_bytes=len(content),
            sha256=content_sha256,
            retain_until=claim.archive_retain_until,
            expected_metadata=command_metadata,
        )
        if write_receipt is None:
            if not write_if_absent:
                raise _ArchiveGateError("ARCHIVE_RECOVERY_OBJECT_NOT_FOUND", retryable=True)
            capability = await self._archive.verify_capability()
            capability.assert_usable(now=utc_now())
            if capability.configuration_fingerprint != claim.archive_configuration_hash:
                raise _ArchiveGateError("ARCHIVE_CONFIGURATION_MISMATCH", retryable=False)
            capability_evidence = _capability_evidence(claim, capability.challenge_hash)
            capability_record = await self._store.record_archive_capability(
                claim=claim,
                capability=capability,
                evidence=capability_evidence,
            )
            if not self._enabled():
                raise _ArchiveGateError("KILL_SWITCH_DISABLED", retryable=False)
            try:
                write_receipt = await self._archive.write_archive(
                    object_key=object_key,
                    chunks=_single_chunk(content),
                    size_bytes=len(content),
                    sha256=content_sha256,
                    retain_until=claim.archive_retain_until,
                    metadata={
                        **command_metadata,
                        "capability-attestation-id": str(capability_record.attestation_id),
                    },
                )
            except ExternalDependencyError as error:
                # A timed-out PutObject may still have committed a locked version. Probe the
                # deterministic key before scheduling any retry so an ambiguous write is reused.
                try:
                    write_receipt = await self._archive.find_archive(
                        object_key=object_key,
                        size_bytes=len(content),
                        sha256=content_sha256,
                        retain_until=claim.archive_retain_until,
                        expected_metadata=command_metadata,
                    )
                except ExternalDependencyError as lookup_error:
                    lookup_code = str(
                        lookup_error.details.get("provider_code") or lookup_error.code
                    )
                    raise _ArchiveGateError(
                        f"ARCHIVE_RECOVERY_TRANSIENT_AMBIGUOUS_{lookup_code}"[:100],
                        retryable=True,
                    ) from lookup_error
                if write_receipt is None:
                    provider_code = str(error.details.get("provider_code") or error.code)
                    raise _ArchiveGateError(
                        f"ARCHIVE_RECOVERY_TRANSIENT_AMBIGUOUS_{provider_code}"[:100],
                        retryable=True,
                    ) from error
        if write_receipt.capability_attestation_id is None:
            raise _ArchiveGateError("ARCHIVE_CAPABILITY_AT_WRITE_NOT_FOUND", retryable=False)
        if not _capability_covers_write(
            capability_record,
            attestation_id=write_receipt.capability_attestation_id,
            written_at=write_receipt.observed_at,
        ):
            try:
                capability_record = await self._store.get_archive_capability_for_write(
                    claim=claim,
                    attestation_id=write_receipt.capability_attestation_id,
                    written_at=write_receipt.observed_at,
                )
            except ExternalDependencyError as error:
                raise _post_write_recovery_error(error) from error
        if capability_record is None:
            raise _ArchiveGateError("ARCHIVE_CAPABILITY_AT_WRITE_NOT_FOUND", retryable=False)
        capability = capability_record.capability
        capability_evidence = capability_record.evidence
        written_at = write_receipt.observed_at
        if (
            write_receipt.object_bucket != claim.archive_bucket
            or write_receipt.object_key != object_key
            or write_receipt.byte_count != len(content)
            or write_receipt.content_sha256 != content_sha256
        ):
            raise _ArchiveGateError("ARCHIVE_WRITE_CHECKSUM_MISMATCH", retryable=False)
        readback_hash = hashlib.sha256()
        readback_bytes = 0
        try:
            async for chunk in self._archive.iter_archive_chunks(
                object_key=object_key,
                version_id=write_receipt.object_version_id,
                chunk_size=1024 * 1024,
            ):
                readback_bytes += len(chunk)
                readback_hash.update(chunk)
        except ExternalDependencyError as error:
            raise _post_write_recovery_error(error) from error
        content_verified_at = utc_now()
        if readback_bytes != len(content) or readback_hash.hexdigest() != content_sha256:
            raise _ArchiveGateError("ARCHIVE_FULL_READBACK_MISMATCH", retryable=False)
        try:
            retention = await self._archive.read_retention(
                object_key=object_key, version_id=write_receipt.object_version_id
            )
        except ExternalDependencyError as error:
            raise _post_write_recovery_error(error) from error
        retention_verified_at = utc_now()
        if (
            write_receipt.retention_mode is not ArchiveRetentionMode.COMPLIANCE
            or retention.retention_mode is not ArchiveRetentionMode.COMPLIANCE
            or write_receipt.retention_until != claim.archive_retain_until
            or retention.retention_until != claim.archive_retain_until
        ):
            raise _ArchiveGateError("ARCHIVE_RETENTION_READBACK_MISMATCH", retryable=False)
        verified_at = utc_now()
        receipt = ImmutableArchiveReceipt(
            receipt_id=uuid7(),
            workspace_id=claim.workspace_id,
            source=ArchiveSource.ERASURE_EXECUTION_EVIDENCE,
            source_partition=(
                f"erasure_execution_evidence_{claim.request_decided_at.year:04d}_"
                f"{claim.request_decided_at.month:02d}"
            ),
            row_count=1,
            byte_count=len(content),
            content_sha256=content_sha256,
            provider_checksum=write_receipt.provider_checksum,
            object_bucket=write_receipt.object_bucket,
            object_key=write_receipt.object_key,
            object_version_id=write_receipt.object_version_id,
            retention_mode=ArchiveRetentionMode.COMPLIANCE,
            retention_until=claim.archive_retain_until,
            legal_hold=retention.legal_hold,
            verified_at=verified_at,
            capability_fingerprint=capability.configuration_fingerprint,
        )
        source_end = max(
            claim.planned_at,
            claim.request_decided_at + timedelta(microseconds=1),
        )
        return RetentionArchiveVerification(
            capability_attestation_id=capability_record.attestation_id,
            capability=capability,
            capability_evidence=capability_evidence,
            receipt=receipt,
            evidence=ArchiveReceiptEvidence(
                source_start=claim.request_decided_at,
                source_end=source_end,
                retention_policy_id=claim.retention_policy_id,
                retention_policy_hash=claim.retention_policy_hash,
                manifest_hash=manifest_hash,
                provider_checksum_algorithm="SHA256",
                provider_checksum_encoding="BASE64",
                provider_checksum_type="FULL_OBJECT",
                readback_sha256=content_sha256,
                readback_byte_count=len(content),
                requested_retention_until=claim.archive_retain_until,
                readback_retention_until=retention.retention_until,
                written_at=written_at,
                content_verified_at=content_verified_at,
                retention_verified_at=retention_verified_at,
                canonicalization_version="RFC8785-LIKE-V1",
                media_type="application/x-ndjson",
                media_type_version="v1",
                compression="none",
                compression_version="identity-v1",
                worker_principal_fingerprint=claim.worker_principal_fingerprint,
                correlation_id=claim.correlation_id,
                encryption_profile_fingerprint=claim.encryption_profile_fingerprint,
            ),
        )

    def _enabled(self) -> bool:
        return (
            self._execution_enabled()
            if callable(self._execution_enabled)
            else self._execution_enabled
        )


def _manifest_document(claim: RetentionExecutionClaim) -> dict[str, object]:
    return {
        "contract": "RETENTION_ERASURE_EVIDENCE_V1",
        "workspace_id": str(claim.workspace_id),
        "execution_job_id": str(claim.job_id),
        "erasure_request_id": str(claim.erasure_request_id),
        "erasure_request_version": claim.erasure_request_version,
        "erasure_request_payload_hash": claim.erasure_request_payload_hash,
        "command_hash": claim.command_hash,
        "target_type": claim.target_type,
        "target_id": str(claim.target_id),
        "target_version": claim.target_version,
        "target_snapshot_hash": claim.target_snapshot_hash,
        "classification": claim.classification,
        "retention_policy_id": str(claim.retention_policy_id),
        "retention_policy_hash": claim.retention_policy_hash,
        "policy_number": claim.policy_number,
        "request_decided_at": claim.request_decided_at.isoformat(),
        "planned_at": claim.planned_at.isoformat(),
        "destructive_effect_count": 0,
        "destructive_state": "DISABLED_NOT_READY",
    }


def _capability_evidence(
    claim: RetentionExecutionClaim, challenge_hash: str
) -> ArchiveCapabilityEvidence:
    return ArchiveCapabilityEvidence(
        encryption_profile_fingerprint=claim.encryption_profile_fingerprint,
        runtime_principal_fingerprint=claim.worker_principal_fingerprint,
        probe_contract_version="archive-probe-v1",
        challenge_hash=challenge_hash,
        object_bucket=claim.archive_bucket,
    )


def _capability_covers_write(
    record: ArchiveCapabilityRecord | None,
    *,
    attestation_id: UUID,
    written_at: datetime,
) -> bool:
    if record is None:
        return False
    write_interval_end = written_at + timedelta(seconds=1)
    return bool(
        record.attestation_id == attestation_id
        and record.capability.observed_at <= written_at
        and record.capability.expires_at >= write_interval_end
    )


def _post_write_recovery_error(error: ExternalDependencyError) -> _ArchiveGateError:
    provider_code = str(error.details.get("provider_code") or error.code)
    return _ArchiveGateError(
        f"ARCHIVE_RECOVERY_TRANSIENT_POST_WRITE_{provider_code}"[:100],
        retryable=True,
    )


async def _single_chunk(content: bytes) -> AsyncIterator[bytes]:
    yield content


@dataclass(frozen=True, slots=True)
class _ArchiveGateError(Exception):
    code: str
    retryable: bool
