from __future__ import annotations

import base64
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.dto import ArchiveCapabilityEvidence, ArchiveReceiptEvidence
from datariver.domain.common import ConflictError, ValidationError
from datariver.domain.retention import (
    ArchiveCapability,
    ArchiveRetentionMode,
    ArchiveSource,
    GovernanceDecision,
    ImmutableArchiveReceipt,
    RetentionPolicyVersion,
    RetentionRules,
)
from datariver.infrastructure.db.models.retention import (
    ImmutableArchiveReceiptModel,
    RetentionPolicyVersionModel,
)
from datariver.infrastructure.db.retention import (
    SqlArchiveEvidenceRepository,
    _archive_capability_model,
    _archive_receipt_model,
    _hydrate_archive_receipt,
    _normalized_provider_checksum,
    _policy_model,
    _required_archive_capability,
)


class _AddSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)


class _ScalarRows:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def one_or_none(self) -> object | None:
        return self._value

    def __iter__(self) -> Iterator[object]:
        if self._value is None:
            return iter(())
        if isinstance(self._value, (list, tuple)):
            return iter(self._value)
        return iter((self._value,))


class _SequenceSession(_AddSession):
    def __init__(self, values: list[object | None]) -> None:
        super().__init__()
        self._values = iter(values)

    async def scalars(self, statement: object) -> _ScalarRows:
        del statement
        return _ScalarRows(next(self._values))


def _capability(*, now: datetime, enabled: bool = True) -> ArchiveCapability:
    return ArchiveCapability(
        configuration_fingerprint="a" * 64,
        challenge_hash="d" * 64,
        observed_at=now,
        expires_at=now + timedelta(minutes=15),
        versioning_enabled=enabled,
        object_lock_enabled=enabled,
        compliance_retention_supported=enabled,
        checksum_sha256_supported=enabled,
        full_readback_verified=enabled,
        retention_shorten_denied=enabled,
        retained_version_delete_denied=enabled,
    )


def _capability_evidence(*, failure_code: str | None = None) -> ArchiveCapabilityEvidence:
    return ArchiveCapabilityEvidence(
        encryption_profile_fingerprint="b" * 64,
        runtime_principal_fingerprint="c" * 64,
        probe_contract_version="archive-probe-v1",
        challenge_hash="d" * 64,
        object_bucket="immutable-audit",
        failure_code=failure_code,
    )


def _receipt(*, now: datetime, provider_checksum: str = "e" * 64) -> ImmutableArchiveReceipt:
    return ImmutableArchiveReceipt(
        receipt_id=uuid4(),
        workspace_id=uuid4(),
        source=ArchiveSource.POLICY_DECISIONS,
        source_partition="policy_decisions_2026_07",
        row_count=10,
        byte_count=128,
        content_sha256="e" * 64,
        provider_checksum=provider_checksum,
        object_bucket="immutable-audit",
        object_key="policy/2026/07/manifest.jsonl",
        object_version_id="version-1",
        retention_mode=ArchiveRetentionMode.COMPLIANCE,
        retention_until=now + timedelta(days=365),
        legal_hold=False,
        verified_at=now,
        capability_fingerprint="a" * 64,
    )


def _receipt_evidence(*, now: datetime) -> ArchiveReceiptEvidence:
    return ArchiveReceiptEvidence(
        source_start=now - timedelta(days=1),
        source_end=now,
        retention_policy_id=uuid4(),
        retention_policy_hash="f" * 64,
        manifest_hash="1" * 64,
        provider_checksum_algorithm="SHA256",
        provider_checksum_encoding="HEX",
        provider_checksum_type="FULL_OBJECT",
        readback_sha256="e" * 64,
        readback_byte_count=128,
        requested_retention_until=now + timedelta(days=365),
        readback_retention_until=now + timedelta(days=365),
        written_at=now - timedelta(seconds=3),
        content_verified_at=now - timedelta(seconds=2),
        retention_verified_at=now - timedelta(seconds=1),
        canonicalization_version="rfc8785-v1",
        media_type="application/x-ndjson",
        media_type_version="v1",
        compression="zstd",
        compression_version="1.5",
        worker_principal_fingerprint="2" * 64,
        correlation_id="archive-2026-07-policy",
        encryption_profile_fingerprint="b" * 64,
    )


def _active_policy_model(*, workspace_id: UUID, now: datetime) -> RetentionPolicyVersionModel:
    policy = RetentionPolicyVersion.propose(
        workspace_id=workspace_id,
        policy_number=1,
        rules=RetentionRules(11, 22, 9, 3),
        requester_id=uuid4(),
        reason="Retention policy",
        policy_decision_id=uuid4(),
    )
    policy.decide(
        decision=GovernanceDecision.APPROVED,
        actor_id=uuid4(),
        reason="Approved",
        policy_decision_id=uuid4(),
        expected_version=1,
        now=now - timedelta(days=1),
    )
    return _policy_model(policy)


def test_capability_hash_covers_runtime_and_encryption_evidence() -> None:
    now = datetime.now(UTC) - timedelta(seconds=1)
    model = _archive_capability_model(
        workspace_id=uuid4(),
        capability=_capability(now=now),
        evidence=_capability_evidence(),
    )
    assert _required_archive_capability(model).configuration_fingerprint == "a" * 64

    model.encryption_profile_fingerprint = "9" * 64
    with pytest.raises(ConflictError, match="integrity"):
        _required_archive_capability(model)


def test_capability_rejects_challenge_unrelated_to_actual_probe() -> None:
    now = datetime.now(UTC) - timedelta(seconds=1)
    capability = _capability(now=now)
    object.__setattr__(capability, "challenge_hash", "9" * 64)

    with pytest.raises(ValidationError, match="probe binding"):
        _archive_capability_model(
            workspace_id=uuid4(),
            capability=capability,
            evidence=_capability_evidence(),
        )


def test_failed_capability_is_recorded_but_cannot_be_hydrated_as_usable() -> None:
    now = datetime.now(UTC) - timedelta(seconds=1)
    model = _archive_capability_model(
        workspace_id=uuid4(),
        capability=_capability(now=now, enabled=False),
        evidence=_capability_evidence(failure_code="OBJECT_LOCK_DISABLED"),
    )
    assert model.state == "FAILED"
    with pytest.raises(ConflictError, match="not verified"):
        _required_archive_capability(model)


@pytest.mark.asyncio
async def test_capability_repository_rejects_future_or_excessive_attestation() -> None:
    session = _AddSession()
    repository = SqlArchiveEvidenceRepository(cast(AsyncSession, session))
    now = datetime.now(UTC)
    with pytest.raises(ValidationError, match="future"):
        await repository.add_capability(
            workspace_id=uuid4(),
            capability=_capability(now=now + timedelta(minutes=1)),
            evidence=_capability_evidence(),
        )

    excessive = _capability(now=now - timedelta(seconds=1))
    object.__setattr__(excessive, "expires_at", excessive.observed_at + timedelta(days=2))
    with pytest.raises(ValidationError, match="24 hours"):
        await repository.add_capability(
            workspace_id=uuid4(), capability=excessive, evidence=_capability_evidence()
        )
    assert session.added == []


@pytest.mark.asyncio
async def test_capability_repository_reuses_identical_cached_observation() -> None:
    workspace_id = uuid4()
    now = datetime.now(UTC) - timedelta(seconds=1)
    capability = _capability(now=now)
    evidence = _capability_evidence()
    existing = _archive_capability_model(
        workspace_id=workspace_id,
        capability=capability,
        evidence=evidence,
    )
    session = _SequenceSession([existing])
    repository = SqlArchiveEvidenceRepository(cast(AsyncSession, session))

    attestation_id = await repository.ensure_capability(
        workspace_id=workspace_id,
        capability=capability,
        evidence=evidence,
    )

    assert attestation_id == existing.id
    assert session.added == []


@pytest.mark.asyncio
async def test_receipt_rejects_a_different_runtime_principal() -> None:
    now = datetime.now(UTC) - timedelta(seconds=1)
    attestation = _archive_capability_model(
        workspace_id=uuid4(),
        capability=_capability(now=now - timedelta(seconds=1)),
        evidence=_capability_evidence(),
    )
    session = _SequenceSession([None])
    repository = SqlArchiveEvidenceRepository(cast(AsyncSession, session))

    with pytest.raises(ConflictError, match="exact archive capability"):
        await repository.add_receipt(
            capability_attestation_id=attestation.id,
            receipt=_receipt(now=now),
            evidence=_receipt_evidence(now=now),
        )
    assert attestation.runtime_principal_fingerprint == "c" * 64
    assert _receipt_evidence(now=now).worker_principal_fingerprint == "2" * 64
    assert session.added == []


@pytest.mark.asyncio
async def test_receipt_retention_must_cover_active_policy_calendar_years() -> None:
    now = datetime.now(UTC) - timedelta(seconds=1)
    receipt = _receipt(now=now)
    capability_evidence = _capability_evidence()
    object.__setattr__(capability_evidence, "runtime_principal_fingerprint", "2" * 64)
    attestation = _archive_capability_model(
        workspace_id=receipt.workspace_id,
        capability=_capability(now=now - timedelta(seconds=10)),
        evidence=capability_evidence,
    )
    policy = _active_policy_model(workspace_id=receipt.workspace_id, now=now)
    evidence = _receipt_evidence(now=now)
    object.__setattr__(evidence, "retention_policy_id", policy.id)
    object.__setattr__(evidence, "retention_policy_hash", policy.payload_hash)
    session = _SequenceSession([attestation, policy, ()])
    repository = SqlArchiveEvidenceRepository(cast(AsyncSession, session))

    with pytest.raises(ConflictError, match="shorter than the active policy"):
        await repository.add_receipt(
            capability_attestation_id=attestation.id,
            receipt=receipt,
            evidence=evidence,
        )
    assert session.added == []


@pytest.mark.asyncio
async def test_receipt_accepts_exact_capability_and_policy_superseded_after_write() -> None:
    now = datetime.now(UTC) - timedelta(seconds=1)
    receipt = _receipt(now=now)
    evidence = _receipt_evidence(now=now)
    capability_evidence = _capability_evidence()
    object.__setattr__(capability_evidence, "runtime_principal_fingerprint", "2" * 64)
    attestation = _archive_capability_model(
        workspace_id=receipt.workspace_id,
        capability=_capability(now=now - timedelta(seconds=10)),
        evidence=capability_evidence,
    )
    policy = _active_policy_model(workspace_id=receipt.workspace_id, now=now)
    policy.state = "SUPERSEDED"
    policy.superseded_by = uuid4()
    policy.supersede_reason = "Replaced after evidence write"
    policy.supersede_policy_decision_id = uuid4()
    policy.superseded_at = now - timedelta(seconds=1)
    object.__setattr__(evidence, "retention_policy_id", policy.id)
    object.__setattr__(evidence, "retention_policy_hash", policy.payload_hash)
    long_retention = now + timedelta(days=365 * 4)
    object.__setattr__(receipt, "retention_until", long_retention)
    object.__setattr__(evidence, "requested_retention_until", long_retention)
    object.__setattr__(evidence, "readback_retention_until", long_retention)
    session = _SequenceSession([attestation, policy, ()])
    repository = SqlArchiveEvidenceRepository(cast(AsyncSession, session))

    await repository.add_receipt(
        capability_attestation_id=attestation.id,
        receipt=receipt,
        evidence=evidence,
    )

    stored = next(
        value for value in session.added if isinstance(value, ImmutableArchiveReceiptModel)
    )
    assert stored.capability_attestation_id == attestation.id


@pytest.mark.asyncio
async def test_receipt_rejects_policy_superseded_before_write() -> None:
    now = datetime.now(UTC) - timedelta(seconds=1)
    receipt = _receipt(now=now)
    evidence = _receipt_evidence(now=now)
    capability_evidence = _capability_evidence()
    object.__setattr__(capability_evidence, "runtime_principal_fingerprint", "2" * 64)
    attestation = _archive_capability_model(
        workspace_id=receipt.workspace_id,
        capability=_capability(now=now - timedelta(seconds=10)),
        evidence=capability_evidence,
    )
    policy = _active_policy_model(workspace_id=receipt.workspace_id, now=now)
    policy.state = "SUPERSEDED"
    policy.superseded_by = uuid4()
    policy.supersede_reason = "Replaced before evidence write"
    policy.supersede_policy_decision_id = uuid4()
    policy.superseded_at = evidence.written_at - timedelta(seconds=1)
    object.__setattr__(evidence, "retention_policy_id", policy.id)
    object.__setattr__(evidence, "retention_policy_hash", policy.payload_hash)
    session = _SequenceSession([attestation, policy])
    repository = SqlArchiveEvidenceRepository(cast(AsyncSession, session))

    with pytest.raises(ConflictError, match="not active at write time"):
        await repository.add_receipt(
            capability_attestation_id=attestation.id,
            receipt=receipt,
            evidence=evidence,
        )
    assert session.added == []


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ("activated", "superseded"))
async def test_receipt_rejects_policy_transition_inside_provider_write_interval(
    boundary: str,
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    receipt = _receipt(now=now)
    evidence = _receipt_evidence(now=now)
    capability_evidence = _capability_evidence()
    object.__setattr__(capability_evidence, "runtime_principal_fingerprint", "2" * 64)
    attestation = _archive_capability_model(
        workspace_id=receipt.workspace_id,
        capability=_capability(now=evidence.written_at - timedelta(seconds=10)),
        evidence=capability_evidence,
    )
    policy = _active_policy_model(workspace_id=receipt.workspace_id, now=now)
    transition_at = evidence.written_at + timedelta(milliseconds=500)
    if boundary == "activated":
        policy.decided_at = transition_at
    else:
        policy.state = "SUPERSEDED"
        policy.superseded_by = uuid4()
        policy.supersede_reason = "Replaced during provider write-time interval"
        policy.supersede_policy_decision_id = uuid4()
        policy.superseded_at = transition_at
    object.__setattr__(evidence, "retention_policy_id", policy.id)
    object.__setattr__(evidence, "retention_policy_hash", policy.payload_hash)
    session = _SequenceSession([attestation, policy])
    repository = SqlArchiveEvidenceRepository(cast(AsyncSession, session))

    with pytest.raises(ConflictError, match="not active at write time"):
        await repository.add_receipt(
            capability_attestation_id=attestation.id,
            receipt=receipt,
            evidence=evidence,
        )
    assert session.added == []


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ("effective_from", "effective_until"))
async def test_receipt_rejects_v2_effective_boundary_inside_provider_write_interval(
    boundary: str,
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    receipt = _receipt(now=now)
    evidence = _receipt_evidence(now=now)
    capability_evidence = _capability_evidence()
    object.__setattr__(capability_evidence, "runtime_principal_fingerprint", "2" * 64)
    attestation = _archive_capability_model(
        workspace_id=receipt.workspace_id,
        capability=_capability(now=evidence.written_at - timedelta(seconds=10)),
        evidence=capability_evidence,
    )
    policy = _active_policy_model(workspace_id=receipt.workspace_id, now=now)
    policy.contract_version = "POLICY_BOOK_V2"
    policy.effective_from = evidence.written_at - timedelta(days=1)
    policy.effective_until = None
    policy.execution_authorization_hours = 24
    transition_at = evidence.written_at + timedelta(milliseconds=500)
    if boundary == "effective_from":
        policy.effective_from = transition_at
    else:
        policy.effective_until = transition_at
    object.__setattr__(evidence, "retention_policy_id", policy.id)
    object.__setattr__(evidence, "retention_policy_hash", policy.payload_hash)
    session = _SequenceSession([attestation, policy])
    repository = SqlArchiveEvidenceRepository(cast(AsyncSession, session))

    with pytest.raises(ConflictError, match=r"not effective.*write-time interval"):
        await repository.add_receipt(
            capability_attestation_id=attestation.id,
            receipt=receipt,
            evidence=evidence,
        )
    assert session.added == []


@pytest.mark.asyncio
async def test_receipt_rejects_capability_expiring_inside_provider_write_interval() -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    receipt = _receipt(now=now)
    evidence = _receipt_evidence(now=now)
    capability_evidence = _capability_evidence()
    object.__setattr__(capability_evidence, "runtime_principal_fingerprint", "2" * 64)
    capability = _capability(now=evidence.written_at - timedelta(seconds=10))
    object.__setattr__(
        capability,
        "expires_at",
        evidence.written_at + timedelta(milliseconds=500),
    )
    attestation = _archive_capability_model(
        workspace_id=receipt.workspace_id,
        capability=capability,
        evidence=capability_evidence,
    )
    session = _SequenceSession([attestation])
    repository = SqlArchiveEvidenceRepository(cast(AsyncSession, session))

    with pytest.raises(ConflictError, match="write-time interval"):
        await repository.add_receipt(
            capability_attestation_id=attestation.id,
            receipt=receipt,
            evidence=evidence,
        )
    assert session.added == []


def test_provider_checksum_is_typed_and_normalized() -> None:
    raw = bytes.fromhex("e" * 64)
    encoded = base64.b64encode(raw).decode("ascii")
    assert (
        _normalized_provider_checksum(
            value=encoded,
            algorithm="SHA256",
            encoding="BASE64",
            checksum_type="FULL_OBJECT",
        )
        == "e" * 64
    )
    with pytest.raises(ValidationError, match="full-object SHA-256"):
        _normalized_provider_checksum(
            value="e" * 64,
            algorithm="MD5",
            encoding="HEX",
            checksum_type="FULL_OBJECT",
        )


def test_receipt_hash_covers_readback_policy_capability_and_format_evidence() -> None:
    now = datetime.now(UTC) - timedelta(seconds=1)
    receipt = _receipt(now=now)
    evidence = _receipt_evidence(now=now)
    model = _archive_receipt_model(
        receipt=receipt,
        evidence=evidence,
        capability_attestation_id=uuid4(),
    )
    assert _hydrate_archive_receipt(model) == receipt

    model.readback_byte_count += 1
    with pytest.raises(ConflictError, match="invalid"):
        _hydrate_archive_receipt(model)


@pytest.mark.asyncio
async def test_receipt_rejects_mismatched_readback_and_literal_null_version() -> None:
    now = datetime.now(UTC) - timedelta(seconds=1)
    receipt = _receipt(now=now)
    evidence = _receipt_evidence(now=now)
    object.__setattr__(evidence, "readback_sha256", "0" * 64)
    with pytest.raises(ValidationError, match="must match"):
        _archive_receipt_model(
            receipt=receipt,
            evidence=evidence,
            capability_attestation_id=uuid4(),
        )

    literal_null = _receipt(now=now)
    object.__setattr__(literal_null, "object_version_id", "null")
    session = _AddSession()
    repository = SqlArchiveEvidenceRepository(cast(AsyncSession, session))
    with pytest.raises(ValidationError, match="literal null"):
        # Rejection occurs before any database lookup or mutation.
        await repository.add_receipt(
            capability_attestation_id=uuid4(),
            receipt=literal_null,
            evidence=_receipt_evidence(now=now),
        )
