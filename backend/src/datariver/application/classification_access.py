from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from datariver.domain.authz import Classification
from datariver.domain.classification_access import (
    ChatMode,
    ClassificationAccessRule,
    RestrictedSearchScope,
    SearchMode,
)


class ClassificationAccessPosture(StrEnum):
    GOVERNED = "GOVERNED"
    STATIC_FLOOR = "STATIC_FLOOR"


@dataclass(frozen=True, slots=True)
class ClassificationRuleRecord:
    classification: Classification
    search_mode: SearchMode
    chat_mode: ChatMode
    provider_profile_version_id: UUID | None


@dataclass(frozen=True, slots=True)
class RestrictedGrantRecord:
    policy_id: UUID
    policy_hash: str
    scope: RestrictedSearchScope
    scope_id: UUID
    valid_from: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ProviderProfileRecord:
    provider_profile_version_id: UUID
    state: str
    kind: str
    jurisdiction: str
    maximum_classification: Classification
    residency_attestation_observed_at: datetime
    residency_attestation_expires_at: datetime
    zero_retention_attestation_observed_at: datetime
    zero_retention_attestation_expires_at: datetime


@dataclass(frozen=True, slots=True)
class ClassificationAccessCandidate:
    policy_id: UUID
    policy_hash: str
    policy_version: int
    required_jurisdiction: str
    authorization_generation: int
    rules: tuple[ClassificationRuleRecord, ...]
    grants: tuple[RestrictedGrantRecord, ...]
    provider_profiles: tuple[ProviderProfileRecord, ...]


@dataclass(frozen=True, slots=True)
class ClassificationAccessSnapshot:
    posture: ClassificationAccessPosture
    policy_id: UUID | None
    policy_hash: str | None
    policy_version: int | None
    required_jurisdiction: str | None
    authorization_generation: int | None
    rules: tuple[ClassificationRuleRecord, ...]
    restricted_resource_ids: frozenset[UUID]
    restricted_system_ids: frozenset[UUID]
    restricted_domain_ids: frozenset[UUID]
    nearest_validity_boundary: datetime | None
    admin_quarantine_review: bool = False

    def rule_for(self, classification: Classification) -> ClassificationRuleRecord:
        return next(rule for rule in self.rules if rule.classification is classification)


class ClassificationAccessSnapshotReader(Protocol):
    async def read_candidate(
        self, *, workspace_id: UUID, subject_id: UUID, now: datetime
    ) -> ClassificationAccessCandidate | None: ...


class ClassificationAccessResolver:
    def __init__(self, reader: ClassificationAccessSnapshotReader) -> None:
        self._reader = reader

    async def resolve(
        self, *, workspace_id: UUID, subject_id: UUID, now: datetime
    ) -> ClassificationAccessSnapshot:
        if now.tzinfo is None or now.utcoffset() is None:
            return static_classification_access_floor()
        try:
            candidate = await self._reader.read_candidate(
                workspace_id=workspace_id,
                subject_id=subject_id,
                now=now,
            )
            if candidate is None:
                return static_classification_access_floor()
            return _governed_snapshot(candidate, now=now)
        except Exception:
            # Policy resolution is authorization-critical. Any unavailable, malformed or
            # inconsistent dependency is the portable static floor, never an allow fallback.
            return static_classification_access_floor()


def static_classification_access_floor() -> ClassificationAccessSnapshot:
    """Return the portable unconfigured ceiling without inventing a jurisdiction or route.

    INTERNAL_APPROVED_ONLY with no provider identifier represents the retrieval ceiling only;
    it cannot select an inference route. Provider routing therefore remains denied until a
    governed snapshot supplies an immutable provider-profile version.
    """

    rules = (
        ClassificationRuleRecord(
            classification=Classification.PUBLIC,
            search_mode=SearchMode.ABAC,
            chat_mode=ChatMode.INTERNAL_APPROVED_ONLY,
            provider_profile_version_id=None,
        ),
        ClassificationRuleRecord(
            classification=Classification.INTERNAL,
            search_mode=SearchMode.ABAC,
            chat_mode=ChatMode.INTERNAL_APPROVED_ONLY,
            provider_profile_version_id=None,
        ),
        ClassificationRuleRecord(
            classification=Classification.CONFIDENTIAL,
            search_mode=SearchMode.ABAC,
            chat_mode=ChatMode.DENY,
            provider_profile_version_id=None,
        ),
        ClassificationRuleRecord(
            classification=Classification.RESTRICTED,
            search_mode=SearchMode.DENY,
            chat_mode=ChatMode.DENY,
            provider_profile_version_id=None,
        ),
    )
    return ClassificationAccessSnapshot(
        posture=ClassificationAccessPosture.STATIC_FLOOR,
        policy_id=None,
        policy_hash=None,
        policy_version=None,
        required_jurisdiction=None,
        authorization_generation=None,
        rules=rules,
        restricted_resource_ids=frozenset(),
        restricted_system_ids=frozenset(),
        restricted_domain_ids=frozenset(),
        nearest_validity_boundary=None,
    )


def _governed_snapshot(
    candidate: ClassificationAccessCandidate, *, now: datetime
) -> ClassificationAccessSnapshot:
    if candidate.policy_version < 1 or candidate.authorization_generation < 0:
        raise ValueError("Invalid classification policy snapshot metadata.")
    if not _is_sha256(candidate.policy_hash):
        raise ValueError("Invalid classification policy hash.")
    jurisdiction = candidate.required_jurisdiction.strip()
    if not jurisdiction or len(jurisdiction) > 64 or "://" in jurisdiction:
        raise ValueError("Invalid governed jurisdiction.")
    if len(candidate.rules) != len(Classification):
        raise ValueError("A governed snapshot requires four rules.")
    if {record.classification for record in candidate.rules} != set(Classification):
        raise ValueError("A governed snapshot requires one rule per classification.")

    profile_records: dict[UUID, ProviderProfileRecord] = {}
    for provider_record in candidate.provider_profiles:
        existing = profile_records.get(provider_record.provider_profile_version_id)
        if existing is not None and existing != provider_record:
            raise ValueError("A provider profile has inconsistent snapshot rows.")
        profile_records[provider_record.provider_profile_version_id] = provider_record

    rules: list[ClassificationRuleRecord] = []
    provider_boundaries: list[datetime] = []
    for record in sorted(candidate.rules, key=lambda value: value.classification.value):
        rule = ClassificationAccessRule(
            classification=record.classification,
            search_mode=record.search_mode,
            chat_mode=record.chat_mode,
            provider_profile_version_id=record.provider_profile_version_id,
        )
        effective_chat_mode = rule.chat_mode
        effective_profile_id = rule.provider_profile_version_id
        profile = (
            profile_records.get(rule.provider_profile_version_id)
            if rule.provider_profile_version_id is not None
            else None
        )
        if rule.chat_mode is not ChatMode.DENY:
            if profile is None or not _provider_is_eligible(
                profile,
                rule=rule,
                required_jurisdiction=jurisdiction,
                now=now,
            ):
                effective_chat_mode = ChatMode.DENY
                effective_profile_id = None
            else:
                provider_boundaries.extend(
                    (
                        profile.residency_attestation_expires_at,
                        profile.zero_retention_attestation_expires_at,
                    )
                )
        rules.append(
            ClassificationRuleRecord(
                classification=rule.classification,
                search_mode=rule.search_mode,
                chat_mode=effective_chat_mode,
                provider_profile_version_id=effective_profile_id,
            )
        )

    resources: set[UUID] = set()
    systems: set[UUID] = set()
    domains: set[UUID] = set()
    boundaries: list[datetime] = list(provider_boundaries)
    for grant in candidate.grants:
        if grant.policy_id != candidate.policy_id or grant.policy_hash != candidate.policy_hash:
            raise ValueError("A grant does not bind the active classification policy.")
        if (
            grant.valid_from.tzinfo is None
            or grant.valid_from.utcoffset() is None
            or grant.expires_at.tzinfo is None
            or grant.expires_at.utcoffset() is None
            or not grant.valid_from <= now < grant.expires_at
        ):
            raise ValueError("A grant is outside its governed validity interval.")
        target = {
            RestrictedSearchScope.RESOURCE: resources,
            RestrictedSearchScope.SYSTEM: systems,
            RestrictedSearchScope.DOMAIN: domains,
        }[grant.scope]
        target.add(grant.scope_id)
        boundaries.append(grant.expires_at)

    return ClassificationAccessSnapshot(
        posture=ClassificationAccessPosture.GOVERNED,
        policy_id=candidate.policy_id,
        policy_hash=candidate.policy_hash,
        policy_version=candidate.policy_version,
        required_jurisdiction=jurisdiction,
        authorization_generation=candidate.authorization_generation,
        rules=tuple(rules),
        restricted_resource_ids=frozenset(resources),
        restricted_system_ids=frozenset(systems),
        restricted_domain_ids=frozenset(domains),
        nearest_validity_boundary=min(boundaries, default=None),
    )


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _provider_is_eligible(
    profile: ProviderProfileRecord,
    *,
    rule: ClassificationAccessRule,
    required_jurisdiction: str,
    now: datetime,
) -> bool:
    timestamps = (
        profile.residency_attestation_observed_at,
        profile.residency_attestation_expires_at,
        profile.zero_retention_attestation_observed_at,
        profile.zero_retention_attestation_expires_at,
    )
    if any(value.tzinfo is None or value.utcoffset() is None for value in timestamps):
        return False
    if profile.state != "APPROVED" or profile.jurisdiction != required_jurisdiction:
        return False
    if rule.classification > profile.maximum_classification:
        return False
    if rule.chat_mode is ChatMode.INTERNAL_APPROVED_ONLY and profile.kind != "INTERNAL":
        return False
    if profile.kind not in {"INTERNAL", "EXTERNAL"}:
        return False
    return (
        profile.residency_attestation_observed_at <= now < profile.residency_attestation_expires_at
        and profile.zero_retention_attestation_observed_at
        <= now
        < profile.zero_retention_attestation_expires_at
    )
