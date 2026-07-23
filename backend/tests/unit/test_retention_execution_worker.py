import base64
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from datariver.application.dto import (
    ArchiveCapabilityEvidence,
    ArchiveCapabilityRecord,
    RetentionArchiveVerification,
    RetentionExecutionClaim,
)
from datariver.application.services.retention_execution import (
    RetentionArchiveOutcome,
    RetentionArchiveWorker,
)
from datariver.domain.retention import (
    ArchiveCapability,
    ArchiveRetentionMode,
    ArchiveRetentionObservation,
    ArchiveSource,
    ArchiveWriteReceipt,
)
from datariver.infrastructure.db.models.retention import RetentionExecutionJobModel
from datariver.infrastructure.db.retention_execution import (
    _archive_verification_matches_job,
)


class MemoryExecutionStore:
    def __init__(
        self,
        claim: RetentionExecutionClaim | None,
        *,
        revalidated: bool = True,
        complete_error: Exception | None = None,
        capabilities: dict[UUID, ArchiveCapabilityRecord] | None = None,
    ) -> None:
        self.claim = claim
        self.revalidated = revalidated
        self.complete_error = complete_error
        self.claim_calls = 0
        self.revalidation_calls = 0
        self.completed: list[RetentionArchiveVerification] = []
        self.failures: list[tuple[str, bool]] = []
        self.orphan_verifications: list[RetentionArchiveVerification] = []
        self.capabilities = capabilities if capabilities is not None else {}

    async def plan_next(self, **kwargs: object) -> bool:
        del kwargs
        return False

    async def claim_next(self, **kwargs: object) -> RetentionExecutionClaim | None:
        del kwargs
        self.claim_calls += 1
        return self.claim

    async def revalidate_before_archive(self, *, claim: RetentionExecutionClaim) -> bool:
        assert claim is self.claim
        self.revalidation_calls += 1
        return self.revalidated

    async def record_archive_capability(
        self,
        *,
        claim: RetentionExecutionClaim,
        capability: ArchiveCapability,
        evidence: ArchiveCapabilityEvidence,
    ) -> ArchiveCapabilityRecord:
        assert claim is self.claim
        record = ArchiveCapabilityRecord(
            attestation_id=uuid4(),
            capability=capability,
            evidence=evidence,
        )
        self.capabilities[record.attestation_id] = record
        return record

    async def get_archive_capability_for_write(
        self,
        *,
        claim: RetentionExecutionClaim,
        attestation_id: UUID,
        written_at: datetime,
    ) -> ArchiveCapabilityRecord | None:
        assert claim is self.claim
        record = self.capabilities.get(attestation_id)
        if record is None:
            return None
        if not (
            record.capability.observed_at <= written_at
            and record.capability.expires_at >= written_at + timedelta(seconds=1)
        ):
            return None
        return record

    async def complete_archive(
        self,
        *,
        claim: RetentionExecutionClaim,
        verification: RetentionArchiveVerification,
    ) -> None:
        assert claim is self.claim
        if self.complete_error is not None:
            raise self.complete_error
        self.completed.append(verification)

    async def mark_failed(
        self,
        *,
        claim: RetentionExecutionClaim,
        error_code: str,
        retryable: bool,
        orphan_verification: RetentionArchiveVerification | None = None,
    ) -> str:
        assert claim is self.claim
        self.failures.append((error_code, retryable))
        if orphan_verification is not None:
            self.orphan_verifications.append(orphan_verification)
        recovery_count = claim.lease_epoch - claim.attempt_count
        recovery_retry = (
            retryable
            and error_code.startswith("ARCHIVE_RECOVERY_TRANSIENT_")
            and 0 <= recovery_count < 3
        )
        return (
            "RETRY_WAIT"
            if recovery_retry or (retryable and claim.attempt_count < claim.maximum_attempts)
            else "BLOCKED"
        )


class MemoryArchiveStore:
    def __init__(self, *, mismatch: bool = False) -> None:
        self.mismatch = mismatch
        self.write_calls = 0
        self.verify_calls = 0
        self._content = b""
        self._now = datetime.now(UTC)
        self._retain_until = self._now + timedelta(days=1)
        self._object_key: str | None = None
        self._sha256: str | None = None
        self._capability_attestation_id: UUID | None = None

    async def find_archive(
        self,
        *,
        object_key: str,
        size_bytes: int,
        sha256: str,
        retain_until: datetime,
        expected_metadata: dict[str, str],
    ) -> ArchiveWriteReceipt | None:
        assert expected_metadata["command-hash"]
        assert expected_metadata["manifest-hash"]
        if self._object_key != object_key:
            return None
        assert len(self._content) == size_bytes
        assert self._sha256 == sha256
        assert self._retain_until == retain_until
        return ArchiveWriteReceipt(
            object_bucket="immutable-audit",
            object_key=object_key,
            object_version_id="version-1",
            byte_count=size_bytes,
            content_sha256=sha256,
            provider_checksum=base64.b64encode(bytes.fromhex(sha256)).decode("ascii"),
            retention_mode=ArchiveRetentionMode.COMPLIANCE,
            retention_until=retain_until,
            legal_hold=False,
            observed_at=self._now,
            capability_attestation_id=self._capability_attestation_id,
        )

    async def verify_capability(self) -> ArchiveCapability:
        self.verify_calls += 1
        return ArchiveCapability(
            configuration_fingerprint="a" * 64,
            challenge_hash="9" * 64,
            observed_at=self._now - timedelta(seconds=1),
            expires_at=self._now + timedelta(minutes=10),
            versioning_enabled=True,
            object_lock_enabled=True,
            compliance_retention_supported=True,
            checksum_sha256_supported=True,
            full_readback_verified=True,
            retention_shorten_denied=True,
            retained_version_delete_denied=True,
        )

    async def write_archive(
        self,
        *,
        object_key: str,
        chunks: AsyncIterator[bytes],
        size_bytes: int,
        sha256: str,
        retain_until: datetime,
        metadata: dict[str, str],
    ) -> ArchiveWriteReceipt:
        assert object_key.startswith("evidence/")
        assert metadata["command-hash"]
        self.write_calls += 1
        content = bytearray()
        async for chunk in chunks:
            content.extend(chunk)
        self._content = bytes(content)
        self._object_key = object_key
        self._sha256 = sha256
        self._retain_until = retain_until
        self._capability_attestation_id = uuid4()
        if "capability-attestation-id" in metadata:
            self._capability_attestation_id = UUID(metadata["capability-attestation-id"])
        assert len(self._content) == size_bytes
        return ArchiveWriteReceipt(
            object_bucket="immutable-audit",
            object_key=object_key,
            object_version_id="version-1",
            byte_count=size_bytes,
            content_sha256=("f" * 64 if self.mismatch else sha256),
            provider_checksum=base64.b64encode(bytes.fromhex(sha256)).decode("ascii"),
            retention_mode=ArchiveRetentionMode.COMPLIANCE,
            retention_until=retain_until,
            legal_hold=False,
            observed_at=self._now,
            capability_attestation_id=self._capability_attestation_id,
        )

    async def _chunks(self) -> AsyncIterator[bytes]:
        yield self._content[:7]
        yield self._content[7:]

    def iter_archive_chunks(
        self, *, object_key: str, version_id: str, chunk_size: int = 1024 * 1024
    ) -> AsyncIterator[bytes]:
        assert object_key
        assert version_id == "version-1"
        assert chunk_size <= 1024 * 1024
        return self._chunks()

    async def read_retention(
        self, *, object_key: str, version_id: str
    ) -> ArchiveRetentionObservation:
        assert object_key
        assert version_id == "version-1"
        return ArchiveRetentionObservation(
            retention_mode=ArchiveRetentionMode.COMPLIANCE,
            retention_until=self._retain_until,
            legal_hold=False,
            observed_at=self._now,
        )


def _claim() -> RetentionExecutionClaim:
    now = datetime.now(UTC)
    return RetentionExecutionClaim(
        job_id=uuid4(),
        attempt_id=uuid4(),
        workspace_id=uuid4(),
        erasure_request_id=uuid4(),
        erasure_request_version=2,
        erasure_request_payload_hash="b" * 64,
        command_hash="c" * 64,
        target_type="CHAT_SESSION",
        target_id=uuid4(),
        target_version=4,
        target_snapshot_hash="d" * 64,
        classification="CONFIDENTIAL",
        retention_policy_id=uuid4(),
        retention_policy_hash="e" * 64,
        policy_number=2,
        request_decided_at=now - timedelta(minutes=30),
        planned_at=now - timedelta(minutes=20),
        archive_retain_until=now + timedelta(days=3650),
        lease_token="f" * 64,
        lease_epoch=1,
        attempt_count=1,
        maximum_attempts=4,
        worker_principal_fingerprint="1" * 64,
        archive_configuration_hash="a" * 64,
        encryption_profile_fingerprint="2" * 64,
        archive_bucket="immutable-audit",
        archive_prefix="evidence",
        correlation_id="retention-test-1",
    )


@pytest.mark.asyncio
async def test_kill_switch_disabled_has_zero_claim_and_archive_effect() -> None:
    store = MemoryExecutionStore(_claim())
    archive = MemoryArchiveStore()
    worker = RetentionArchiveWorker(
        store=store,
        archive=archive,
        execution_enabled=False,
        worker_id="archive:test",
        worker_principal_fingerprint="1" * 64,
        lease_seconds=300,
    )

    assert await worker.run_once(workspace_id=uuid4()) is None
    assert store.claim_calls == 0
    assert archive.write_calls == 0


@pytest.mark.asyncio
async def test_stale_revalidation_has_zero_archive_effect() -> None:
    claim = _claim()
    store = MemoryExecutionStore(claim, revalidated=False)
    archive = MemoryArchiveStore()
    worker = RetentionArchiveWorker(
        store=store,
        archive=archive,
        execution_enabled=True,
        worker_id="archive:test",
        worker_principal_fingerprint="1" * 64,
        lease_seconds=300,
    )

    assert await worker.run_once(workspace_id=claim.workspace_id) is RetentionArchiveOutcome.BLOCKED
    assert archive.write_calls == 0
    assert store.failures == [("PRE_ARCHIVE_REVALIDATION_FAILED", False)]


@pytest.mark.asyncio
async def test_kill_switch_recheck_before_write_has_zero_archive_effect() -> None:
    claim = _claim()
    store = MemoryExecutionStore(claim)
    archive = MemoryArchiveStore()
    observations = iter((True, False))
    worker = RetentionArchiveWorker(
        store=store,
        archive=archive,
        execution_enabled=lambda: next(observations),
        worker_id="archive:test",
        worker_principal_fingerprint="1" * 64,
        lease_seconds=300,
    )

    assert await worker.run_once(workspace_id=claim.workspace_id) is RetentionArchiveOutcome.BLOCKED
    assert archive.write_calls == 0
    assert store.failures == [("KILL_SWITCH_DISABLED", False)]


@pytest.mark.asyncio
async def test_archive_worker_streams_full_readback_and_records_verified_evidence() -> None:
    claim = _claim()
    store = MemoryExecutionStore(claim)
    archive = MemoryArchiveStore()
    worker = RetentionArchiveWorker(
        store=store,
        archive=archive,
        execution_enabled=True,
        worker_id="archive:test",
        worker_principal_fingerprint="1" * 64,
        lease_seconds=300,
    )

    assert (
        await worker.run_once(workspace_id=claim.workspace_id) is RetentionArchiveOutcome.ARCHIVED
    )
    assert archive.write_calls == 1
    assert not store.failures
    assert len(store.completed) == 1
    verification = store.completed[0]
    assert verification.receipt.content_sha256 == verification.evidence.readback_sha256
    assert verification.receipt.byte_count == verification.evidence.readback_byte_count
    assert verification.receipt.object_version_id == "version-1"
    assert verification.receipt.source is ArchiveSource.ERASURE_EXECUTION_EVIDENCE
    assert verification.evidence.provider_checksum_encoding == "BASE64"
    assert verification.capability_evidence.challenge_hash == "9" * 64
    job = RetentionExecutionJobModel(
        archive_configuration_hash=claim.archive_configuration_hash,
        retention_policy_id=claim.retention_policy_id,
        retention_policy_hash=claim.retention_policy_hash,
        execution_authorization_valid_until=(
            verification.evidence.written_at + timedelta(seconds=2)
        ),
    )
    assert _archive_verification_matches_job(
        job=job,
        claim=claim,
        verification=verification,
        archive_bucket=claim.archive_bucket,
        archive_prefix=claim.archive_prefix,
        encryption_profile_fingerprint=claim.encryption_profile_fingerprint,
    )
    assert not _archive_verification_matches_job(
        job=job,
        claim=claim,
        verification=replace(
            verification,
            receipt=replace(verification.receipt, object_key="evidence/wrong.jsonl"),
        ),
        archive_bucket=claim.archive_bucket,
        archive_prefix=claim.archive_prefix,
        encryption_profile_fingerprint=claim.encryption_profile_fingerprint,
    )
    job.execution_authorization_valid_until = verification.evidence.written_at + timedelta(
        milliseconds=500
    )
    assert not _archive_verification_matches_job(
        job=job,
        claim=claim,
        verification=verification,
        archive_bucket=claim.archive_bucket,
        archive_prefix=claim.archive_prefix,
        encryption_profile_fingerprint=claim.encryption_profile_fingerprint,
    )


@pytest.mark.asyncio
async def test_archive_checksum_mismatch_never_completes_and_is_not_retried() -> None:
    claim = _claim()
    store = MemoryExecutionStore(claim)
    archive = MemoryArchiveStore(mismatch=True)
    worker = RetentionArchiveWorker(
        store=store,
        archive=archive,
        execution_enabled=True,
        worker_id="archive:test",
        worker_principal_fingerprint="1" * 64,
        lease_seconds=300,
    )

    assert await worker.run_once(workspace_id=claim.workspace_id) is RetentionArchiveOutcome.BLOCKED
    assert store.completed == []
    assert store.failures == [("ARCHIVE_WRITE_CHECKSUM_MISMATCH", False)]


@pytest.mark.asyncio
async def test_kill_switch_recheck_after_write_blocks_completion_and_records_orphan() -> None:
    claim = _claim()
    store = MemoryExecutionStore(claim)
    archive = MemoryArchiveStore()
    observations = iter((True, True, True, False))
    worker = RetentionArchiveWorker(
        store=store,
        archive=archive,
        execution_enabled=lambda: next(observations),
        worker_id="archive:test",
        worker_principal_fingerprint="1" * 64,
        lease_seconds=300,
    )

    assert await worker.run_once(workspace_id=claim.workspace_id) is RetentionArchiveOutcome.BLOCKED
    assert archive.write_calls == 1
    assert store.completed == []
    assert store.failures == [("KILL_SWITCH_DISABLED_AFTER_WRITE", False)]
    assert len(store.orphan_verifications) == 1
    orphan = store.orphan_verifications[0]
    assert orphan.receipt.object_key.endswith(f"/{orphan.evidence.manifest_hash}.jsonl")
    assert orphan.receipt.object_version_id == "version-1"


@pytest.mark.asyncio
async def test_retry_reuses_deterministic_locked_object_without_second_write() -> None:
    first_claim = _claim()
    archive = MemoryArchiveStore()
    first_store = MemoryExecutionStore(first_claim)
    first_worker = RetentionArchiveWorker(
        store=first_store,
        archive=archive,
        execution_enabled=True,
        worker_id="archive:first",
        worker_principal_fingerprint="1" * 64,
        lease_seconds=300,
    )
    assert (
        await first_worker.run_once(workspace_id=first_claim.workspace_id)
        is RetentionArchiveOutcome.ARCHIVED
    )

    retry_claim = replace(
        first_claim,
        attempt_id=uuid4(),
        lease_epoch=2,
        attempt_count=2,
        correlation_id="retention-test-2",
    )
    retry_store = MemoryExecutionStore(retry_claim, capabilities=first_store.capabilities)
    retry_worker = RetentionArchiveWorker(
        store=retry_store,
        archive=archive,
        execution_enabled=True,
        worker_id="archive:retry",
        worker_principal_fingerprint="1" * 64,
        lease_seconds=300,
    )

    assert (
        await retry_worker.run_once(workspace_id=retry_claim.workspace_id)
        is RetentionArchiveOutcome.ARCHIVED
    )
    assert archive.write_calls == 1
    assert len(retry_store.completed) == 1


@pytest.mark.asyncio
async def test_ambiguous_put_response_recovers_committed_version_without_retry_write() -> None:
    from datariver.application.errors import ExternalDependencyError

    claim = _claim()
    store = MemoryExecutionStore(claim)
    archive = MemoryArchiveStore()
    write = archive.write_archive

    async def ambiguous_write(**kwargs: object) -> ArchiveWriteReceipt:
        await write(**kwargs)  # type: ignore[arg-type]
        raise ExternalDependencyError(
            "PutObject response was lost",
            dependency="immutable_archive",
            retryable=True,
            provider_code="RequestTimeout",
        )

    archive.write_archive = ambiguous_write  # type: ignore[method-assign]
    worker = RetentionArchiveWorker(
        store=store,
        archive=archive,
        execution_enabled=True,
        worker_id="archive:ambiguous",
        worker_principal_fingerprint="1" * 64,
        lease_seconds=300,
    )

    assert (
        await worker.run_once(workspace_id=claim.workspace_id) is RetentionArchiveOutcome.ARCHIVED
    )
    assert archive.write_calls == 1
    assert len(store.completed) == 1
    assert not store.failures


@pytest.mark.asyncio
async def test_delayed_ambiguous_commit_is_found_by_read_only_recovery() -> None:
    from datariver.application.errors import ExternalDependencyError

    claim = replace(_claim(), attempt_count=4, maximum_attempts=4, lease_epoch=4)
    store = MemoryExecutionStore(claim)
    archive = MemoryArchiveStore()
    write = archive.write_archive
    captured: dict[str, object] = {}

    async def delayed_write(**kwargs: object) -> ArchiveWriteReceipt:
        captured.update(kwargs)
        raise ExternalDependencyError(
            "conditional response arrived before the committed version became visible",
            dependency="immutable_archive",
            retryable=False,
            provider_code="PreconditionFailed",
            ambiguous_commit=True,
        )

    archive.write_archive = delayed_write  # type: ignore[method-assign]
    worker = RetentionArchiveWorker(
        store=store,
        archive=archive,
        execution_enabled=True,
        worker_id="archive:delayed-response",
        worker_principal_fingerprint="1" * 64,
        lease_seconds=300,
    )
    assert (
        await worker.run_once(workspace_id=claim.workspace_id)
        is RetentionArchiveOutcome.RETRY_SCHEDULED
    )
    assert store.failures == [("ARCHIVE_RECOVERY_TRANSIENT_AMBIGUOUS_PreconditionFailed", True)]

    await write(**captured)  # type: ignore[arg-type]
    recovery_claim = replace(
        claim,
        attempt_id=uuid4(),
        recovery_only=True,
        lease_epoch=5,
        correlation_id="retention-delayed-recovery",
    )
    recovery_store = MemoryExecutionStore(
        recovery_claim,
        capabilities=store.capabilities,
    )
    archive.write_archive = _unexpected_archive_call  # type: ignore[method-assign]
    recovery_worker = RetentionArchiveWorker(
        store=recovery_store,
        archive=archive,
        execution_enabled=True,
        worker_id="archive:delayed-recovery",
        worker_principal_fingerprint="1" * 64,
        lease_seconds=300,
    )
    assert (
        await recovery_worker.run_once(workspace_id=claim.workspace_id)
        is RetentionArchiveOutcome.BLOCKED
    )
    assert archive.write_calls == 1
    assert recovery_store.failures == [("POST_WRITE_RECEIPT_RECOVERED", False)]


@pytest.mark.asyncio
async def test_ambiguous_put_and_failed_immediate_head_recover_later() -> None:
    from datariver.application.errors import ExternalDependencyError

    claim = replace(_claim(), attempt_count=4, maximum_attempts=4, lease_epoch=4)
    store = MemoryExecutionStore(claim)
    archive = MemoryArchiveStore()
    write = archive.write_archive
    find = archive.find_archive
    lookup_calls = 0

    async def committed_without_response(**kwargs: object) -> ArchiveWriteReceipt:
        await write(**kwargs)  # type: ignore[arg-type]
        raise ExternalDependencyError(
            "PutObject response was lost",
            dependency="immutable_archive",
            retryable=True,
            provider_code="RequestTimeout",
            ambiguous_commit=True,
        )

    async def immediate_head_unavailable(**kwargs: object) -> ArchiveWriteReceipt | None:
        nonlocal lookup_calls
        lookup_calls += 1
        if lookup_calls == 2:
            raise ExternalDependencyError(
                "HEAD temporarily unavailable",
                dependency="immutable_archive",
                retryable=True,
                provider_code="ServiceUnavailable",
            )
        return await find(**kwargs)  # type: ignore[arg-type]

    archive.write_archive = committed_without_response  # type: ignore[method-assign]
    archive.find_archive = immediate_head_unavailable  # type: ignore[method-assign]
    worker = RetentionArchiveWorker(
        store=store,
        archive=archive,
        execution_enabled=True,
        worker_id="archive:ambiguous-head-failure",
        worker_principal_fingerprint="1" * 64,
        lease_seconds=300,
    )
    assert (
        await worker.run_once(workspace_id=claim.workspace_id)
        is RetentionArchiveOutcome.RETRY_SCHEDULED
    )
    assert store.failures == [("ARCHIVE_RECOVERY_TRANSIENT_AMBIGUOUS_ServiceUnavailable", True)]

    recovery_claim = replace(
        claim,
        attempt_id=uuid4(),
        recovery_only=True,
        lease_epoch=5,
        correlation_id="retention-ambiguous-head-recovery",
    )
    recovery_store = MemoryExecutionStore(
        recovery_claim,
        capabilities=store.capabilities,
    )
    recovery_worker = RetentionArchiveWorker(
        store=recovery_store,
        archive=archive,
        execution_enabled=True,
        worker_id="archive:ambiguous-head-recovery",
        worker_principal_fingerprint="1" * 64,
        lease_seconds=300,
    )
    assert (
        await recovery_worker.run_once(workspace_id=claim.workspace_id)
        is RetentionArchiveOutcome.BLOCKED
    )
    assert archive.write_calls == 1
    assert recovery_store.failures == [("POST_WRITE_RECEIPT_RECOVERED", False)]


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_verification", ("readback", "retention"))
async def test_final_post_write_transient_verification_enters_read_only_recovery(
    failed_verification: str,
) -> None:
    from datariver.application.errors import ExternalDependencyError

    claim = replace(_claim(), attempt_count=4, maximum_attempts=4, lease_epoch=4)
    store = MemoryExecutionStore(claim)
    archive = MemoryArchiveStore()
    readback = archive.iter_archive_chunks
    retention = archive.read_retention

    async def unavailable_readback(**kwargs: object) -> AsyncIterator[bytes]:
        del kwargs
        raise ExternalDependencyError(
            "full readback temporarily unavailable",
            dependency="immutable_archive",
            retryable=True,
            provider_code="ServiceUnavailable",
        )
        yield b""  # pragma: no cover - keeps this an async iterator

    async def unavailable_retention(**kwargs: object) -> ArchiveRetentionObservation:
        del kwargs
        raise ExternalDependencyError(
            "retention readback temporarily unavailable",
            dependency="immutable_archive",
            retryable=True,
            provider_code="ServiceUnavailable",
        )

    if failed_verification == "readback":
        archive.iter_archive_chunks = unavailable_readback  # type: ignore[method-assign]
    else:
        archive.read_retention = unavailable_retention  # type: ignore[method-assign]
    worker = RetentionArchiveWorker(
        store=store,
        archive=archive,
        execution_enabled=True,
        worker_id="archive:post-write-transient",
        worker_principal_fingerprint="1" * 64,
        lease_seconds=300,
    )

    assert (
        await worker.run_once(workspace_id=claim.workspace_id)
        is RetentionArchiveOutcome.RETRY_SCHEDULED
    )
    assert store.failures == [("ARCHIVE_RECOVERY_TRANSIENT_POST_WRITE_ServiceUnavailable", True)]
    assert archive.write_calls == 1

    archive.iter_archive_chunks = readback  # type: ignore[method-assign]
    archive.read_retention = retention  # type: ignore[method-assign]
    recovery_claim = replace(
        claim,
        attempt_id=uuid4(),
        recovery_only=True,
        lease_epoch=5,
        correlation_id=f"retention-post-write-{failed_verification}-recovery",
    )
    recovery_store = MemoryExecutionStore(
        recovery_claim,
        capabilities=store.capabilities,
    )
    recovery_worker = RetentionArchiveWorker(
        store=recovery_store,
        archive=archive,
        execution_enabled=True,
        worker_id="archive:post-write-recovery",
        worker_principal_fingerprint="1" * 64,
        lease_seconds=300,
    )

    assert (
        await recovery_worker.run_once(workspace_id=claim.workspace_id)
        is RetentionArchiveOutcome.BLOCKED
    )
    assert archive.write_calls == 1
    assert recovery_store.failures == [("POST_WRITE_RECEIPT_RECOVERED", False)]


@pytest.mark.asyncio
async def test_completion_failure_persists_verified_object_as_blocked_orphan() -> None:
    claim = _claim()
    store = MemoryExecutionStore(claim, complete_error=RuntimeError("database unavailable"))
    archive = MemoryArchiveStore()
    worker = RetentionArchiveWorker(
        store=store,
        archive=archive,
        execution_enabled=True,
        worker_id="archive:test",
        worker_principal_fingerprint="1" * 64,
        lease_seconds=300,
    )

    assert await worker.run_once(workspace_id=claim.workspace_id) is RetentionArchiveOutcome.BLOCKED
    assert store.failures == [("POST_WRITE_RECEIPT_RuntimeError", False)]
    assert len(store.orphan_verifications) == 1


@pytest.mark.asyncio
async def test_final_expired_lease_recovery_is_read_only_and_records_existing_object() -> None:
    original = _claim()
    archive = MemoryArchiveStore()
    seed_store = MemoryExecutionStore(original)
    seed_worker = RetentionArchiveWorker(
        store=seed_store,
        archive=archive,
        execution_enabled=True,
        worker_id="archive:seed",
        worker_principal_fingerprint="1" * 64,
        lease_seconds=300,
    )
    assert (
        await seed_worker.run_once(workspace_id=original.workspace_id)
        is RetentionArchiveOutcome.ARCHIVED
    )
    archive.verify_capability = _unexpected_archive_call  # type: ignore[assignment]
    archive.write_archive = _unexpected_archive_call  # type: ignore[method-assign]
    recovery_claim = replace(
        original,
        attempt_id=uuid4(),
        recovery_only=True,
        attempt_count=original.maximum_attempts,
        lease_epoch=original.maximum_attempts + 1,
        correlation_id="retention-recovery",
    )
    recovery_store = MemoryExecutionStore(
        recovery_claim,
        revalidated=False,
        capabilities=seed_store.capabilities,
    )
    recovery_worker = RetentionArchiveWorker(
        store=recovery_store,
        archive=archive,
        execution_enabled=True,
        worker_id="archive:recovery",
        worker_principal_fingerprint="1" * 64,
        lease_seconds=300,
    )

    assert (
        await recovery_worker.run_once(workspace_id=recovery_claim.workspace_id)
        is RetentionArchiveOutcome.BLOCKED
    )
    assert recovery_store.revalidation_calls == 0
    assert archive.write_calls == 1
    assert recovery_store.failures == [("POST_WRITE_RECEIPT_RECOVERED", False)]
    assert len(recovery_store.orphan_verifications) == 1


@pytest.mark.asyncio
async def test_final_expired_lease_recovery_never_writes_when_object_is_absent() -> None:
    claim = replace(
        _claim(),
        recovery_only=True,
        attempt_count=4,
        maximum_attempts=4,
        lease_epoch=5,
    )
    store = MemoryExecutionStore(claim)
    archive = MemoryArchiveStore()
    worker = RetentionArchiveWorker(
        store=store,
        archive=archive,
        execution_enabled=True,
        worker_id="archive:recovery-missing",
        worker_principal_fingerprint="1" * 64,
        lease_seconds=300,
    )

    assert await worker.run_once(workspace_id=claim.workspace_id) is RetentionArchiveOutcome.BLOCKED
    assert archive.write_calls == 0
    assert store.failures == [("ARCHIVE_RECOVERY_OBJECT_NOT_FOUND", True)]
    assert not store.orphan_verifications


@pytest.mark.asyncio
async def test_nonfinal_recovery_without_object_returns_to_normal_write_budget() -> None:
    claim = replace(
        _claim(),
        recovery_only=True,
        attempt_count=1,
        maximum_attempts=4,
        lease_epoch=2,
    )
    store = MemoryExecutionStore(claim)
    archive = MemoryArchiveStore()
    worker = RetentionArchiveWorker(
        store=store,
        archive=archive,
        execution_enabled=True,
        worker_id="archive:recovery-missing-nonfinal",
        worker_principal_fingerprint="1" * 64,
        lease_seconds=300,
    )

    assert (
        await worker.run_once(workspace_id=claim.workspace_id)
        is RetentionArchiveOutcome.RETRY_SCHEDULED
    )
    assert archive.verify_calls == 0
    assert archive.write_calls == 0
    assert store.failures == [("ARCHIVE_RECOVERY_OBJECT_NOT_FOUND", True)]


@pytest.mark.asyncio
async def test_recovery_lookup_transient_is_normalized_and_bounded_without_writes() -> None:
    from datariver.application.errors import ExternalDependencyError

    claim = replace(
        _claim(),
        recovery_only=True,
        attempt_count=4,
        maximum_attempts=4,
        lease_epoch=5,
    )
    store = MemoryExecutionStore(claim)
    archive = MemoryArchiveStore()

    async def unavailable_lookup(**kwargs: object) -> ArchiveWriteReceipt | None:
        del kwargs
        raise ExternalDependencyError(
            "lookup unavailable",
            dependency="immutable_archive",
            retryable=True,
            provider_code="ServiceUnavailable",
        )

    archive.find_archive = unavailable_lookup  # type: ignore[method-assign]
    worker = RetentionArchiveWorker(
        store=store,
        archive=archive,
        execution_enabled=True,
        worker_id="archive:recovery-transient",
        worker_principal_fingerprint="1" * 64,
        lease_seconds=300,
    )

    assert (
        await worker.run_once(workspace_id=claim.workspace_id)
        is RetentionArchiveOutcome.RETRY_SCHEDULED
    )
    assert archive.verify_calls == 0
    assert archive.write_calls == 0
    assert store.failures == [("ARCHIVE_RECOVERY_TRANSIENT_ServiceUnavailable", True)]


@pytest.mark.asyncio
async def test_final_ambiguous_write_enters_bounded_recovery_lane() -> None:
    claim = replace(_claim(), attempt_count=4, maximum_attempts=4, lease_epoch=4)
    store = MemoryExecutionStore(claim)
    archive = MemoryArchiveStore()
    archive.write_archive = _raise_retryable_dependency  # type: ignore[method-assign]
    worker = RetentionArchiveWorker(
        store=store,
        archive=archive,
        execution_enabled=True,
        worker_id="archive:test",
        worker_principal_fingerprint="1" * 64,
        lease_seconds=300,
    )

    assert (
        await worker.run_once(workspace_id=claim.workspace_id)
        is RetentionArchiveOutcome.RETRY_SCHEDULED
    )
    assert store.failures == [("ARCHIVE_RECOVERY_TRANSIENT_AMBIGUOUS_ServiceUnavailable", True)]


async def _raise_retryable_dependency(**kwargs: object) -> ArchiveWriteReceipt:
    del kwargs
    from datariver.application.errors import ExternalDependencyError

    raise ExternalDependencyError(
        "temporary archive failure",
        dependency="immutable_archive",
        retryable=True,
        provider_code="ServiceUnavailable",
    )


async def _unexpected_archive_call(**kwargs: object) -> ArchiveWriteReceipt:
    del kwargs
    raise AssertionError("recovery-only claims must not call capability probe or PutObject")
