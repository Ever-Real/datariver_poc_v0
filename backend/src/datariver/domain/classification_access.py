from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
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

_TEXT_LIMIT = 4000
_JURISDICTION_LIMIT = 64


class ClassificationAccessPolicyState(StrEnum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class PolicyDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class SearchMode(StrEnum):
    ABAC = "ABAC"
    DENY = "DENY"
    EXPLICIT_GRANT_ONLY = "EXPLICIT_GRANT_ONLY"


class ChatMode(StrEnum):
    DENY = "DENY"
    INTERNAL_APPROVED_ONLY = "INTERNAL_APPROVED_ONLY"
    APPROVED_PROVIDER_ONLY = "APPROVED_PROVIDER_ONLY"


class RestrictedSearchScope(StrEnum):
    RESOURCE = "RESOURCE"
    SYSTEM = "SYSTEM"
    DOMAIN = "DOMAIN"


class RestrictedSearchGrantState(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class GrantDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class ClassificationAccessRule:
    classification: Classification
    search_mode: SearchMode
    chat_mode: ChatMode
    provider_profile_version_id: UUID | None = None
    embedding_provider_profile_version_id: UUID | None = None
    reranker_provider_profile_version_id: UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.classification, Classification):
            raise ValidationError("The classification access rule classification is invalid.")
        if not isinstance(self.search_mode, SearchMode):
            raise ValidationError("The classification Search mode is invalid.")
        if not isinstance(self.chat_mode, ChatMode):
            raise ValidationError("The classification Chat mode is invalid.")
        for label, profile_id in (
            ("Chat composition", self.provider_profile_version_id),
            ("embedding", self.embedding_provider_profile_version_id),
            ("reranker", self.reranker_provider_profile_version_id),
        ):
            if profile_id is not None and not isinstance(profile_id, UUID):
                raise ValidationError(
                    f"The {label} provider-profile version identifier is invalid."
                )
        _lint_rule_security_floor(self)

    def document(self) -> dict[str, object]:
        document: dict[str, object] = {
            "classification": self.classification.name,
            "search_mode": self.search_mode.value,
            "chat_mode": self.chat_mode.value,
            "provider_profile_version_id": (
                str(self.provider_profile_version_id)
                if self.provider_profile_version_id is not None
                else None
            ),
        }
        # Preserve the payload shape and hash of policies created before staged
        # interactive inference bindings existed. New stage bindings become part
        # of the immutable policy payload as soon as either is supplied.
        if (
            self.embedding_provider_profile_version_id is not None
            or self.reranker_provider_profile_version_id is not None
        ):
            document["embedding_provider_profile_version_id"] = (
                str(self.embedding_provider_profile_version_id)
                if self.embedding_provider_profile_version_id is not None
                else None
            )
            document["reranker_provider_profile_version_id"] = (
                str(self.reranker_provider_profile_version_id)
                if self.reranker_provider_profile_version_id is not None
                else None
            )
        return document


@dataclass(slots=True)
class ClassificationAccessPolicy:
    policy_id: UUID
    workspace_id: UUID
    policy_number: int
    required_jurisdiction: str
    restricted_search_grant_maximum_days: int
    rules: tuple[ClassificationAccessRule, ...]
    payload_hash: str
    requester_id: UUID
    request_reason: str
    request_policy_decision_id: UUID
    state: ClassificationAccessPolicyState = ClassificationAccessPolicyState.PROPOSED
    checker_id: UUID | None = None
    decision_reason: str | None = None
    decision_policy_decision_id: UUID | None = None
    decided_at: datetime | None = None
    superseded_by: UUID | None = None
    supersede_reason: str | None = None
    supersede_policy_decision_id: UUID | None = None
    superseded_at: datetime | None = None
    version: int = 1
    events: list[DomainEvent] = field(default_factory=list)

    @classmethod
    def propose(
        cls,
        *,
        workspace_id: UUID,
        policy_number: int,
        required_jurisdiction: str,
        restricted_search_grant_maximum_days: int,
        rules: tuple[ClassificationAccessRule, ...],
        requester_id: UUID,
        reason: str,
        policy_decision_id: UUID,
    ) -> ClassificationAccessPolicy:
        if policy_number < 1:
            raise ValidationError("The classification policy number must be positive.")
        jurisdiction = _required_jurisdiction(required_jurisdiction)
        if not 1 <= restricted_search_grant_maximum_days <= 365:
            raise ValidationError(
                "The RESTRICTED Search grant maximum must be between 1 and 365 days."
            )
        validated_rules = _validated_rules(rules)
        request_reason = _required_text(reason, "A classification policy reason is required.")
        payload_hash = canonical_json_hash(
            _policy_document(
                required_jurisdiction=jurisdiction,
                restricted_search_grant_maximum_days=restricted_search_grant_maximum_days,
                rules=validated_rules,
            )
        )
        policy = cls(
            policy_id=uuid7(),
            workspace_id=workspace_id,
            policy_number=policy_number,
            required_jurisdiction=jurisdiction,
            restricted_search_grant_maximum_days=restricted_search_grant_maximum_days,
            rules=validated_rules,
            payload_hash=payload_hash,
            requester_id=requester_id,
            request_reason=request_reason,
            request_policy_decision_id=policy_decision_id,
        )
        policy.events.append(
            DomainEvent.create(
                event_type="authz.classification_access_policy.proposed.v1",
                aggregate_type="classification_access_policy",
                aggregate_id=policy.policy_id,
                workspace_id=workspace_id,
                payload={
                    "policy_number": policy_number,
                    "payload_hash": payload_hash,
                    "version": policy.version,
                },
            )
        )
        return policy

    def decide(
        self,
        *,
        decision: PolicyDecision,
        actor_id: UUID,
        reason: str,
        policy_decision_id: UUID,
        expected_version: int,
        now: datetime,
    ) -> None:
        self._check_version(expected_version)
        _require_aware_datetime(now, "classification policy decision")
        if not isinstance(decision, PolicyDecision):
            raise ValidationError("The classification policy decision is invalid.")
        if self.state is not ClassificationAccessPolicyState.PROPOSED:
            raise ConflictError("The classification policy proposal has already been decided.")
        if actor_id == self.requester_id:
            raise ValidationError("The classification policy maker cannot be its checker.")
        self._assert_payload_integrity()
        decision_reason = _required_text(
            reason, "A classification policy decision reason is required."
        )
        self.state = (
            ClassificationAccessPolicyState.ACTIVE
            if decision is PolicyDecision.APPROVED
            else ClassificationAccessPolicyState.REJECTED
        )
        self.checker_id = actor_id
        self.decision_reason = decision_reason
        self.decision_policy_decision_id = policy_decision_id
        self.decided_at = now
        self.version += 1
        self.events.append(
            DomainEvent.create(
                event_type=f"authz.classification_access_policy.{decision.value.lower()}.v1",
                aggregate_type="classification_access_policy",
                aggregate_id=self.policy_id,
                workspace_id=self.workspace_id,
                payload={
                    "policy_number": self.policy_number,
                    "checker_id": str(actor_id),
                    "payload_hash": self.payload_hash,
                    "version": self.version,
                },
            )
        )

    def supersede(
        self,
        *,
        actor_id: UUID,
        reason: str,
        policy_decision_id: UUID,
        expected_version: int,
        now: datetime,
    ) -> None:
        self._check_version(expected_version)
        _require_aware_datetime(now, "classification policy supersession")
        if self.state is not ClassificationAccessPolicyState.ACTIVE:
            raise ConflictError("Only an active classification policy can be superseded.")
        self._assert_payload_integrity()
        supersede_reason = _required_text(
            reason, "A classification policy supersession reason is required."
        )
        self.state = ClassificationAccessPolicyState.SUPERSEDED
        self.superseded_by = actor_id
        self.supersede_reason = supersede_reason
        self.supersede_policy_decision_id = policy_decision_id
        self.superseded_at = now
        self.version += 1
        self.events.append(
            DomainEvent.create(
                event_type="authz.classification_access_policy.superseded.v1",
                aggregate_type="classification_access_policy",
                aggregate_id=self.policy_id,
                workspace_id=self.workspace_id,
                payload={
                    "actor_id": str(actor_id),
                    "policy_number": self.policy_number,
                    "payload_hash": self.payload_hash,
                    "version": self.version,
                },
            )
        )

    def rule_for(self, classification: Classification) -> ClassificationAccessRule:
        return next(rule for rule in self.rules if rule.classification is classification)

    def _assert_payload_integrity(self) -> None:
        rules = _validated_rules(self.rules)
        document = _policy_document(
            required_jurisdiction=_required_jurisdiction(self.required_jurisdiction),
            restricted_search_grant_maximum_days=(self.restricted_search_grant_maximum_days),
            rules=rules,
        )
        if canonical_json_hash(document) != self.payload_hash:
            raise ConflictError("The classification policy payload failed its integrity check.")

    def _check_version(self, expected_version: int) -> None:
        if expected_version != self.version:
            raise ConflictError(
                "The classification policy was modified by another operation.",
                details={"expected": expected_version, "actual": self.version},
            )


@dataclass(slots=True)
class RestrictedSearchGrant:
    grant_id: UUID
    workspace_id: UUID
    classification_policy_id: UUID
    classification_policy_hash: str
    subject_id: UUID
    scope: RestrictedSearchScope
    scope_id: UUID
    purpose: str
    valid_from: datetime
    expires_at: datetime
    payload_hash: str
    requester_id: UUID
    request_reason: str
    request_policy_decision_id: UUID
    state: RestrictedSearchGrantState = RestrictedSearchGrantState.PENDING
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

    @classmethod
    def propose(
        cls,
        *,
        workspace_id: UUID,
        classification_policy_id: UUID,
        classification_policy_hash: str,
        subject_id: UUID,
        scope: RestrictedSearchScope,
        scope_id: UUID,
        purpose: str,
        valid_from: datetime,
        expires_at: datetime,
        requester_id: UUID,
        reason: str,
        policy_decision_id: UUID,
        now: datetime,
        maximum_lifetime: timedelta,
    ) -> RestrictedSearchGrant:
        _validate_grant_interval(
            valid_from=valid_from,
            expires_at=expires_at,
            now=now,
            maximum_lifetime=maximum_lifetime,
        )
        if not isinstance(classification_policy_id, UUID) or not _is_sha256(
            classification_policy_hash
        ):
            raise ValidationError("The governing classification policy binding is invalid.")
        if not isinstance(scope, RestrictedSearchScope) or not isinstance(scope_id, UUID):
            raise ValidationError("The RESTRICTED Search grant scope is invalid.")
        cleaned_purpose = _required_text(purpose, "A RESTRICTED Search purpose is required.")
        request_reason = _required_text(reason, "A RESTRICTED Search grant reason is required.")
        document = _grant_document(
            workspace_id=workspace_id,
            classification_policy_id=classification_policy_id,
            classification_policy_hash=classification_policy_hash,
            subject_id=subject_id,
            scope=scope,
            scope_id=scope_id,
            purpose=cleaned_purpose,
            valid_from=valid_from,
            expires_at=expires_at,
        )
        grant = cls(
            grant_id=uuid7(),
            workspace_id=workspace_id,
            classification_policy_id=classification_policy_id,
            classification_policy_hash=classification_policy_hash,
            subject_id=subject_id,
            scope=scope,
            scope_id=scope_id,
            purpose=cleaned_purpose,
            valid_from=valid_from,
            expires_at=expires_at,
            payload_hash=canonical_json_hash(document),
            requester_id=requester_id,
            request_reason=request_reason,
            request_policy_decision_id=policy_decision_id,
        )
        grant.events.append(
            DomainEvent.create(
                event_type="authz.restricted_search_grant.proposed.v1",
                aggregate_type="restricted_search_grant",
                aggregate_id=grant.grant_id,
                workspace_id=workspace_id,
                payload={
                    "subject_id": str(subject_id),
                    "scope": scope.value,
                    "scope_id": str(scope_id),
                    "payload_hash": grant.payload_hash,
                    "version": grant.version,
                },
            )
        )
        return grant

    def decide(
        self,
        *,
        decision: GrantDecision,
        actor_id: UUID,
        reason: str,
        policy_decision_id: UUID,
        expected_version: int,
        now: datetime,
    ) -> None:
        self._check_version(expected_version)
        _require_aware_datetime(now, "RESTRICTED Search grant decision")
        if not isinstance(decision, GrantDecision):
            raise ValidationError("The RESTRICTED Search grant decision is invalid.")
        if self.state is not RestrictedSearchGrantState.PENDING:
            raise ConflictError("The RESTRICTED Search grant has already been decided.")
        if actor_id == self.requester_id:
            raise ValidationError("The RESTRICTED Search grant maker cannot be its checker.")
        if actor_id == self.subject_id:
            raise ValidationError("The grant subject cannot approve their own RESTRICTED access.")
        if decision is GrantDecision.APPROVED and now >= self.expires_at:
            raise ConflictError("An expired RESTRICTED Search grant cannot be approved.")
        self._assert_payload_integrity()
        decision_reason = _required_text(reason, "A RESTRICTED Search decision reason is required.")
        self.state = (
            RestrictedSearchGrantState.ACTIVE
            if decision is GrantDecision.APPROVED
            else RestrictedSearchGrantState.REJECTED
        )
        self.checker_id = actor_id
        self.decision_reason = decision_reason
        self.decision_policy_decision_id = policy_decision_id
        self.decided_at = now
        self.version += 1
        self.events.append(
            DomainEvent.create(
                event_type=f"authz.restricted_search_grant.{decision.value.lower()}.v1",
                aggregate_type="restricted_search_grant",
                aggregate_id=self.grant_id,
                workspace_id=self.workspace_id,
                payload={
                    "subject_id": str(self.subject_id),
                    "checker_id": str(actor_id),
                    "payload_hash": self.payload_hash,
                    "version": self.version,
                },
            )
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
        self._check_version(expected_version)
        _require_aware_datetime(now, "RESTRICTED Search grant revocation")
        if self.state is not RestrictedSearchGrantState.ACTIVE:
            raise ConflictError("Only an active RESTRICTED Search grant can be revoked.")
        revocation_reason = _required_text(
            reason, "A RESTRICTED Search revocation reason is required."
        )
        self.state = RestrictedSearchGrantState.REVOKED
        self.revoked_by = actor_id
        self.revocation_reason = revocation_reason
        self.revocation_policy_decision_id = policy_decision_id
        self.revoked_at = now
        self.version += 1
        self.events.append(
            DomainEvent.create(
                event_type="authz.restricted_search_grant.revoked.v1",
                aggregate_type="restricted_search_grant",
                aggregate_id=self.grant_id,
                workspace_id=self.workspace_id,
                payload={
                    "subject_id": str(self.subject_id),
                    "actor_id": str(actor_id),
                    "payload_hash": self.payload_hash,
                    "version": self.version,
                },
            )
        )

    def is_active_at(self, now: datetime) -> bool:
        _require_aware_datetime(now, "RESTRICTED Search grant evaluation")
        return (
            self.state is RestrictedSearchGrantState.ACTIVE
            and self.valid_from <= now < self.expires_at
        )

    def _assert_payload_integrity(self) -> None:
        document = _grant_document(
            workspace_id=self.workspace_id,
            classification_policy_id=self.classification_policy_id,
            classification_policy_hash=self.classification_policy_hash,
            subject_id=self.subject_id,
            scope=self.scope,
            scope_id=self.scope_id,
            purpose=self.purpose,
            valid_from=self.valid_from,
            expires_at=self.expires_at,
        )
        if canonical_json_hash(document) != self.payload_hash:
            raise ConflictError("The RESTRICTED Search grant payload failed its integrity check.")

    def _check_version(self, expected_version: int) -> None:
        if expected_version != self.version:
            raise ConflictError(
                "The RESTRICTED Search grant was modified by another operation.",
                details={"expected": expected_version, "actual": self.version},
            )


def _validated_rules(
    rules: tuple[ClassificationAccessRule, ...],
) -> tuple[ClassificationAccessRule, ...]:
    if not isinstance(rules, tuple) or len(rules) != len(Classification):
        raise ValidationError("A classification policy requires exactly four typed rules.")
    if any(not isinstance(rule, ClassificationAccessRule) for rule in rules):
        raise ValidationError("A classification policy accepts typed rules only.")
    if {rule.classification for rule in rules} != set(Classification):
        raise ValidationError("A classification policy requires one rule per classification.")
    return tuple(sorted(rules, key=lambda rule: rule.classification.value))


def _policy_document(
    *,
    required_jurisdiction: str,
    restricted_search_grant_maximum_days: int,
    rules: tuple[ClassificationAccessRule, ...],
) -> dict[str, object]:
    return {
        "required_jurisdiction": required_jurisdiction,
        "restricted_search_grant_maximum_days": restricted_search_grant_maximum_days,
        "rules": [rule.document() for rule in rules],
    }


def _lint_rule_security_floor(rule: ClassificationAccessRule) -> None:
    profile_ids = (
        rule.provider_profile_version_id,
        rule.embedding_provider_profile_version_id,
        rule.reranker_provider_profile_version_id,
    )
    if rule.chat_mode is ChatMode.DENY:
        if any(profile_id is not None for profile_id in profile_ids):
            raise ValidationError("A denied Chat rule cannot reference an inference profile.")
    elif rule.provider_profile_version_id is None:
        raise ValidationError(
            "An enabled Chat rule requires a provider-profile version for composition."
        )

    if rule.classification is Classification.RESTRICTED:
        if rule.chat_mode is not ChatMode.DENY:
            raise ValidationError("RESTRICTED Chat must remain denied.")
        if rule.search_mode not in {SearchMode.DENY, SearchMode.EXPLICIT_GRANT_ONLY}:
            raise ValidationError("RESTRICTED Search requires deny or an explicit grant.")
        return

    if rule.search_mode is SearchMode.EXPLICIT_GRANT_ONLY:
        raise ValidationError("Explicit Search grants are available only for RESTRICTED data.")
    if rule.classification is Classification.CONFIDENTIAL and rule.chat_mode not in {
        ChatMode.DENY,
        ChatMode.INTERNAL_APPROVED_ONLY,
    }:
        raise ValidationError(
            "CONFIDENTIAL Chat requires a specifically approved internal profile."
        )


def _validate_grant_interval(
    *,
    valid_from: datetime,
    expires_at: datetime,
    now: datetime,
    maximum_lifetime: timedelta,
) -> None:
    _require_aware_datetime(now, "RESTRICTED Search grant proposal")
    _require_aware_datetime(valid_from, "RESTRICTED Search grant start")
    _require_aware_datetime(expires_at, "RESTRICTED Search grant expiry")
    if valid_from < now:
        raise ValidationError("A RESTRICTED Search grant cannot be backdated.")
    if expires_at <= valid_from:
        raise ValidationError("A RESTRICTED Search grant expiry must follow its start.")
    if maximum_lifetime <= timedelta(0):
        raise ValidationError("The RESTRICTED Search grant maximum lifetime is invalid.")
    if expires_at - valid_from > maximum_lifetime:
        raise ValidationError("A RESTRICTED Search grant cannot exceed the active policy maximum.")


def _grant_document(
    *,
    workspace_id: UUID,
    classification_policy_id: UUID,
    classification_policy_hash: str,
    subject_id: UUID,
    scope: RestrictedSearchScope,
    scope_id: UUID,
    purpose: str,
    valid_from: datetime,
    expires_at: datetime,
) -> dict[str, object]:
    return {
        "workspace_id": str(workspace_id),
        "classification_policy_id": str(classification_policy_id),
        "classification_policy_hash": classification_policy_hash,
        "subject_id": str(subject_id),
        "scope": scope.value,
        "scope_id": str(scope_id),
        "purpose": purpose,
        "valid_from": valid_from.isoformat(),
        "expires_at": expires_at.isoformat(),
    }


def _required_text(value: str, message: str) -> str:
    cleaned = value.strip()
    if not cleaned or len(cleaned) > _TEXT_LIMIT:
        raise ValidationError(message)
    return cleaned


def _required_jurisdiction(value: str) -> str:
    cleaned = value.strip()
    if not cleaned or len(cleaned) > _JURISDICTION_LIMIT or "://" in cleaned:
        raise ValidationError("A governed jurisdiction identifier is required.")
    return cleaned


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _require_aware_datetime(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError(f"The {name} timestamp must include a timezone.")
