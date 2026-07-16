from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from datariver.domain.authz import Classification
from datariver.domain.common import (
    ConflictError,
    DomainEvent,
    ValidationError,
    canonical_json_hash,
    uuid7,
)

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_REGISTRY_KEY_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?")
_RUNTIME_IDENTITY_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._:/-]{0,254}[A-Za-z0-9])?")


class ProviderKind(StrEnum):
    INTERNAL = "INTERNAL"
    EXTERNAL = "EXTERNAL"


class InferenceProviderProfileState(StrEnum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


@dataclass(frozen=True, slots=True)
class ProviderAttestation:
    """Opaque evidence reference; the evidence body remains in the governed registry."""

    fingerprint: str
    observed_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if not _SHA256_PATTERN.fullmatch(self.fingerprint):
            raise ValidationError("The provider attestation fingerprint is invalid.")
        _require_aware_datetime(self.observed_at, "provider attestation observation")
        _require_aware_datetime(self.expires_at, "provider attestation expiry")
        if self.expires_at <= self.observed_at:
            raise ValidationError("The provider attestation must expire after its observation.")

    def is_current(self, *, now: datetime) -> bool:
        return _is_aware_datetime(now) and self.observed_at <= now < self.expires_at

    def document(self) -> dict[str, str]:
        return {
            "fingerprint": self.fingerprint,
            "observed_at": _canonical_datetime(self.observed_at),
            "expires_at": _canonical_datetime(self.expires_at),
        }


@dataclass(frozen=True, slots=True)
class InferenceProviderProfile:
    """Immutable governed runtime profile without endpoints, credentials, or requests."""

    profile_key: str
    server_route_key: str
    kind: ProviderKind
    provider_identity: str
    model_identity: str
    deployment_identity: str
    jurisdiction: str
    region: str
    maximum_classification: Classification
    residency_attestation: ProviderAttestation
    zero_retention_attestation: ProviderAttestation

    def __post_init__(self) -> None:
        _validate_registry_key(self.profile_key, "provider profile key")
        _validate_registry_key(self.server_route_key, "server-side route key")
        _validate_runtime_identity(self.provider_identity, "provider identity")
        _validate_runtime_identity(self.model_identity, "model identity")
        _validate_runtime_identity(self.deployment_identity, "deployment identity")
        _validate_runtime_identity(self.jurisdiction, "provider jurisdiction", maximum=64)
        _validate_runtime_identity(self.region, "provider region", maximum=64)
        if not isinstance(self.kind, ProviderKind):
            raise ValidationError("The provider kind is invalid.")
        if not isinstance(self.maximum_classification, Classification):
            raise ValidationError("The provider maximum classification is invalid.")
        if self.maximum_classification is Classification.RESTRICTED:
            raise ValidationError("An inference provider cannot process RESTRICTED data.")
        if (
            self.kind is ProviderKind.EXTERNAL
            and self.maximum_classification > Classification.INTERNAL
        ):
            raise ValidationError(
                "An external inference provider cannot process data above INTERNAL."
            )

    def attestations_current(self, *, now: datetime) -> bool:
        return self.residency_attestation.is_current(
            now=now
        ) and self.zero_retention_attestation.is_current(now=now)

    def security_invariants_hold(self) -> bool:
        if not isinstance(self.kind, ProviderKind) or not isinstance(
            self.maximum_classification, Classification
        ):
            return False
        if self.maximum_classification is Classification.RESTRICTED:
            return False
        return not (
            self.kind is ProviderKind.EXTERNAL
            and self.maximum_classification > Classification.INTERNAL
        )

    def document(self) -> dict[str, object]:
        return {
            "profile_key": self.profile_key,
            "server_route_key": self.server_route_key,
            "kind": self.kind.value,
            "provider_identity": self.provider_identity,
            "model_identity": self.model_identity,
            "deployment_identity": self.deployment_identity,
            "jurisdiction": self.jurisdiction,
            "region": self.region,
            "maximum_classification": self.maximum_classification.name,
            "residency_attestation": self.residency_attestation.document(),
            "zero_retention_attestation": self.zero_retention_attestation.document(),
        }


@dataclass(slots=True)
class InferenceProviderProfileVersion:
    provider_profile_version_id: UUID
    workspace_id: UUID
    profile_version: int
    profile: InferenceProviderProfile
    payload_hash: str
    maker_id: UUID
    proposal_reason: str
    proposal_policy_decision_id: UUID
    proposed_at: datetime
    state: InferenceProviderProfileState = InferenceProviderProfileState.PROPOSED
    checker_id: UUID | None = None
    decision_reason: str | None = None
    decision_policy_decision_id: UUID | None = None
    decided_at: datetime | None = None
    revoked_by: UUID | None = None
    revocation_reason: str | None = None
    revocation_policy_decision_id: UUID | None = None
    revoked_at: datetime | None = None
    version: int = 1
    events: list[DomainEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.profile_version < 1:
            raise ValidationError("The provider profile version must be positive.")
        if self.version < 1:
            raise ValidationError("The provider profile optimistic version must be positive.")
        if not _SHA256_PATTERN.fullmatch(self.payload_hash):
            raise ValidationError("The provider profile payload hash is invalid.")
        _required_reason(self.proposal_reason, "A provider profile proposal reason is required.")
        _require_aware_datetime(self.proposed_at, "provider profile proposal")

    @classmethod
    def propose(
        cls,
        *,
        workspace_id: UUID,
        profile_version: int,
        profile: InferenceProviderProfile,
        maker_id: UUID,
        reason: str,
        policy_decision_id: UUID,
        now: datetime,
    ) -> InferenceProviderProfileVersion:
        if profile_version < 1:
            raise ValidationError("The provider profile version must be positive.")
        _require_aware_datetime(now, "provider profile proposal")
        cleaned_reason = _required_reason(reason, "A provider profile proposal reason is required.")
        payload_hash = canonical_json_hash(
            _payload_document(
                workspace_id=workspace_id,
                profile_version=profile_version,
                profile=profile,
            )
        )
        proposal = cls(
            provider_profile_version_id=uuid7(),
            workspace_id=workspace_id,
            profile_version=profile_version,
            profile=profile,
            payload_hash=payload_hash,
            maker_id=maker_id,
            proposal_reason=cleaned_reason,
            proposal_policy_decision_id=policy_decision_id,
            proposed_at=now,
        )
        proposal.events.append(proposal._event("proposed", actor_id=maker_id))
        return proposal

    def approve(
        self,
        *,
        checker_id: UUID,
        reason: str,
        policy_decision_id: UUID,
        expected_version: int,
        now: datetime,
    ) -> None:
        self._decide(
            target_state=InferenceProviderProfileState.APPROVED,
            checker_id=checker_id,
            reason=reason,
            policy_decision_id=policy_decision_id,
            expected_version=expected_version,
            now=now,
        )

    def reject(
        self,
        *,
        checker_id: UUID,
        reason: str,
        policy_decision_id: UUID,
        expected_version: int,
        now: datetime,
    ) -> None:
        self._decide(
            target_state=InferenceProviderProfileState.REJECTED,
            checker_id=checker_id,
            reason=reason,
            policy_decision_id=policy_decision_id,
            expected_version=expected_version,
            now=now,
        )

    def revoke(
        self,
        *,
        actor_id: UUID,
        reason: str,
        policy_decision_id: UUID,
        expected_version: int,
        now: datetime,
    ) -> None:
        _require_aware_datetime(now, "provider profile revocation")
        self._check_version(expected_version)
        if self.state is not InferenceProviderProfileState.APPROVED:
            raise ConflictError("Only an approved provider profile can be revoked.")
        cleaned_reason = _required_reason(
            reason, "A provider profile revocation reason is required."
        )
        self.state = InferenceProviderProfileState.REVOKED
        self.revoked_by = actor_id
        self.revocation_reason = cleaned_reason
        self.revocation_policy_decision_id = policy_decision_id
        self.revoked_at = now
        self.version += 1
        self.events.append(self._event("revoked", actor_id=actor_id))

    def eligible(
        self,
        *,
        now: datetime,
        effective_classification: Classification,
        required_jurisdiction: str,
        require_internal: bool,
    ) -> bool:
        """Return False for every missing, stale, revoked, or inconsistent condition."""

        if not _is_aware_datetime(now):
            return False
        if not isinstance(effective_classification, Classification):
            return False
        if not isinstance(required_jurisdiction, str) or not required_jurisdiction:
            return False
        if not isinstance(require_internal, bool):
            return False
        if self.state is not InferenceProviderProfileState.APPROVED:
            return False
        if not self._approval_evidence_complete():
            return False
        if any(
            value is not None
            for value in (
                self.revoked_by,
                self.revocation_reason,
                self.revocation_policy_decision_id,
                self.revoked_at,
            )
        ):
            return False
        if not self.integrity_valid() or not self.profile.security_invariants_hold():
            return False
        if required_jurisdiction != self.profile.jurisdiction:
            return False
        if require_internal and self.profile.kind is not ProviderKind.INTERNAL:
            return False
        if effective_classification > self.profile.maximum_classification:
            return False
        return self.profile.attestations_current(now=now)

    def integrity_valid(self) -> bool:
        return (
            canonical_json_hash(
                _payload_document(
                    workspace_id=self.workspace_id,
                    profile_version=self.profile_version,
                    profile=self.profile,
                )
            )
            == self.payload_hash
        )

    def assert_integrity(self) -> None:
        if not self.integrity_valid():
            raise ConflictError("The provider profile payload failed its integrity check.")

    def _decide(
        self,
        *,
        target_state: InferenceProviderProfileState,
        checker_id: UUID,
        reason: str,
        policy_decision_id: UUID,
        expected_version: int,
        now: datetime,
    ) -> None:
        _require_aware_datetime(now, "provider profile decision")
        self._check_version(expected_version)
        if self.state is not InferenceProviderProfileState.PROPOSED:
            raise ConflictError("The provider profile proposal has already been decided.")
        if checker_id == self.maker_id:
            raise ValidationError("The provider profile maker cannot be its checker.")
        self.assert_integrity()
        if target_state is InferenceProviderProfileState.APPROVED:
            if not self.profile.security_invariants_hold():
                raise ConflictError("The provider profile violates routing invariants.")
            if not self.profile.attestations_current(now=now):
                raise ConflictError("The provider profile attestations are not current.")
        cleaned_reason = _required_reason(reason, "A provider profile decision reason is required.")
        self.state = target_state
        self.checker_id = checker_id
        self.decision_reason = cleaned_reason
        self.decision_policy_decision_id = policy_decision_id
        self.decided_at = now
        self.version += 1
        self.events.append(self._event(target_state.value.lower(), actor_id=checker_id))

    def _approval_evidence_complete(self) -> bool:
        return (
            self.checker_id is not None
            and self.checker_id != self.maker_id
            and self.decision_reason is not None
            and self.decision_policy_decision_id is not None
            and self.decided_at is not None
            and _is_aware_datetime(self.decided_at)
        )

    def _check_version(self, expected_version: int) -> None:
        if expected_version != self.version:
            raise ConflictError(
                "The provider profile was modified by another operation.",
                details={"expected": expected_version, "actual": self.version},
            )

    def _event(self, action: str, *, actor_id: UUID) -> DomainEvent:
        payload: dict[str, object] = {
            "profile_key": self.profile.profile_key,
            "profile_version": self.profile_version,
            "payload_hash": self.payload_hash,
            "actor_id": str(actor_id),
            "version": self.version,
        }
        if action in {"approved", "rejected"}:
            payload["policy_decision_id"] = str(self.decision_policy_decision_id)
            payload["decided_at"] = (
                self.decided_at.isoformat() if self.decided_at is not None else None
            )
        elif action == "revoked":
            payload["policy_decision_id"] = str(self.revocation_policy_decision_id)
            payload["revoked_at"] = (
                self.revoked_at.isoformat() if self.revoked_at is not None else None
            )
        return DomainEvent.create(
            event_type=f"governance.inference_provider_profile.{action}.v1",
            aggregate_type="inference_provider_profile_version",
            aggregate_id=self.provider_profile_version_id,
            workspace_id=self.workspace_id,
            payload=payload,
        )


def _payload_document(
    *,
    workspace_id: UUID,
    profile_version: int,
    profile: InferenceProviderProfile,
) -> dict[str, object]:
    return {
        "workspace_id": str(workspace_id),
        "profile_version": profile_version,
        "profile": profile.document(),
    }


def _validate_registry_key(value: str, name: str) -> None:
    if not isinstance(value, str) or not _REGISTRY_KEY_PATTERN.fullmatch(value):
        raise ValidationError(f"The {name} is invalid.")


def _validate_runtime_identity(value: str, name: str, *, maximum: int = 256) -> None:
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or "://" in value
        or not _RUNTIME_IDENTITY_PATTERN.fullmatch(value)
    ):
        raise ValidationError(f"The {name} is invalid.")


def _required_reason(reason: str, message: str) -> str:
    cleaned = reason.strip()
    if not cleaned or len(cleaned) > 1_000:
        raise ValidationError(message)
    return cleaned


def _canonical_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _is_aware_datetime(value: object) -> bool:
    return (
        isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
    )


def _require_aware_datetime(value: datetime, name: str) -> None:
    if not _is_aware_datetime(value):
        raise ValidationError(f"The {name} timestamp must include a timezone.")
