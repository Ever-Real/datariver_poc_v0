from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.classification_access import (
    ClassificationAccessCandidate,
    ClassificationRuleRecord,
    ProviderProfileRecord,
    RestrictedGrantRecord,
)
from datariver.domain.authz import Classification
from datariver.domain.classification_access import ChatMode, RestrictedSearchScope, SearchMode
from datariver.domain.common import ConflictError
from datariver.infrastructure.db.models.classification_access import (
    ClassificationAccessGenerationModel,
    ClassificationAccessPolicyRuleModel,
    ClassificationAccessPolicyVersionModel,
    RestrictedSearchGrantModel,
)
from datariver.infrastructure.db.models.inference import InferenceProviderProfileVersionModel


class SqlClassificationAccessSnapshotReader:
    """Read one authorization snapshot with one workspace/subject set query."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def read_candidate(
        self, *, workspace_id: UUID, subject_id: UUID, now: datetime
    ) -> ClassificationAccessCandidate | None:
        policy = ClassificationAccessPolicyVersionModel
        rule = ClassificationAccessPolicyRuleModel
        generation = ClassificationAccessGenerationModel
        grant = RestrictedSearchGrantModel
        profile = InferenceProviderProfileVersionModel

        statement = (
            select(
                policy.id.label("policy_id"),
                policy.payload_hash.label("policy_hash"),
                policy.version.label("policy_version"),
                policy.required_jurisdiction.label("required_jurisdiction"),
                generation.generation.label("authorization_generation"),
                rule.classification.label("classification"),
                rule.search_mode.label("search_mode"),
                rule.chat_mode.label("chat_mode"),
                rule.provider_profile_version_id.label("rule_provider_profile_id"),
                profile.id.label("profile_id"),
                profile.state.label("profile_state"),
                profile.kind.label("profile_kind"),
                profile.jurisdiction.label("profile_jurisdiction"),
                profile.maximum_classification.label("profile_maximum_classification"),
                profile.residency_attestation_observed_at.label(
                    "residency_attestation_observed_at"
                ),
                profile.residency_attestation_expires_at.label("residency_attestation_expires_at"),
                profile.zero_retention_attestation_observed_at.label(
                    "zero_retention_attestation_observed_at"
                ),
                profile.zero_retention_attestation_expires_at.label(
                    "zero_retention_attestation_expires_at"
                ),
                grant.id.label("grant_id"),
                grant.classification_policy_id.label("grant_policy_id"),
                grant.classification_policy_hash.label("grant_policy_hash"),
                grant.scope.label("grant_scope"),
                grant.scope_id.label("grant_scope_id"),
                grant.valid_from.label("grant_valid_from"),
                grant.expires_at.label("grant_expires_at"),
            )
            .select_from(policy)
            .join(
                rule,
                and_(
                    rule.workspace_id == policy.workspace_id,
                    rule.policy_id == policy.id,
                    rule.policy_hash == policy.payload_hash,
                ),
            )
            .outerjoin(generation, generation.workspace_id == policy.workspace_id)
            .outerjoin(
                profile,
                and_(
                    profile.workspace_id == rule.workspace_id,
                    profile.id == rule.provider_profile_version_id,
                ),
            )
            .outerjoin(
                grant,
                and_(
                    grant.workspace_id == policy.workspace_id,
                    grant.classification_policy_id == policy.id,
                    grant.classification_policy_hash == policy.payload_hash,
                    grant.subject_id == subject_id,
                    grant.state == "ACTIVE",
                    grant.valid_from <= now,
                    grant.expires_at > now,
                ),
            )
            .where(
                policy.workspace_id == workspace_id,
                policy.state == "ACTIVE",
            )
            .order_by(rule.classification, grant.id)
        )
        rows = (await self._session.execute(statement)).mappings().all()
        if not rows:
            return None
        return _candidate_from_rows([dict(row) for row in rows])


def _candidate_from_rows(rows: list[dict[str, Any]]) -> ClassificationAccessCandidate:
    first = rows[0]
    policy_id = cast(UUID, first["policy_id"])
    policy_hash = cast(str, first["policy_hash"])
    policy_version = cast(int, first["policy_version"])
    jurisdiction = cast(str, first["required_jurisdiction"])
    generation = first["authorization_generation"]
    if generation is None:
        raise ConflictError("The classification authorization generation is unavailable.")

    rules: dict[Classification, ClassificationRuleRecord] = {}
    grants: dict[UUID, RestrictedGrantRecord] = {}
    profiles: dict[UUID, ProviderProfileRecord] = {}
    expected_metadata = (policy_id, policy_hash, policy_version, jurisdiction, generation)
    for row in rows:
        metadata = (
            row["policy_id"],
            row["policy_hash"],
            row["policy_version"],
            row["required_jurisdiction"],
            row["authorization_generation"],
        )
        if metadata != expected_metadata:
            raise ConflictError("The classification policy snapshot rows are inconsistent.")

        classification = Classification(int(row["classification"]))
        rule_record = ClassificationRuleRecord(
            classification=classification,
            search_mode=SearchMode(str(row["search_mode"])),
            chat_mode=ChatMode(str(row["chat_mode"])),
            provider_profile_version_id=cast(UUID | None, row["rule_provider_profile_id"]),
        )
        existing_rule = rules.get(classification)
        if existing_rule is not None and existing_rule != rule_record:
            raise ConflictError("A classification rule has inconsistent snapshot rows.")
        rules[classification] = rule_record

        profile_id = cast(UUID | None, row["profile_id"])
        if profile_id is not None:
            profile_record = ProviderProfileRecord(
                provider_profile_version_id=profile_id,
                state=str(row["profile_state"]),
                kind=str(row["profile_kind"]),
                jurisdiction=str(row["profile_jurisdiction"]),
                maximum_classification=Classification(int(row["profile_maximum_classification"])),
                residency_attestation_observed_at=cast(
                    datetime, row["residency_attestation_observed_at"]
                ),
                residency_attestation_expires_at=cast(
                    datetime, row["residency_attestation_expires_at"]
                ),
                zero_retention_attestation_observed_at=cast(
                    datetime, row["zero_retention_attestation_observed_at"]
                ),
                zero_retention_attestation_expires_at=cast(
                    datetime, row["zero_retention_attestation_expires_at"]
                ),
            )
            existing_profile = profiles.get(profile_id)
            if existing_profile is not None and existing_profile != profile_record:
                raise ConflictError("A provider profile has inconsistent snapshot rows.")
            profiles[profile_id] = profile_record

        grant_id = cast(UUID | None, row["grant_id"])
        if grant_id is not None:
            grant_record = RestrictedGrantRecord(
                policy_id=cast(UUID, row["grant_policy_id"]),
                policy_hash=str(row["grant_policy_hash"]),
                scope=RestrictedSearchScope(str(row["grant_scope"])),
                scope_id=cast(UUID, row["grant_scope_id"]),
                valid_from=cast(datetime, row["grant_valid_from"]),
                expires_at=cast(datetime, row["grant_expires_at"]),
            )
            existing_grant = grants.get(grant_id)
            if existing_grant is not None and existing_grant != grant_record:
                raise ConflictError("A RESTRICTED grant has inconsistent snapshot rows.")
            grants[grant_id] = grant_record

    return ClassificationAccessCandidate(
        policy_id=policy_id,
        policy_hash=policy_hash,
        policy_version=policy_version,
        required_jurisdiction=jurisdiction,
        authorization_generation=int(generation),
        rules=tuple(rules[key] for key in sorted(rules, key=lambda value: value.value)),
        grants=tuple(grants[key] for key in sorted(grants, key=lambda value: value.int)),
        provider_profiles=tuple(
            profiles[key] for key in sorted(profiles, key=lambda value: value.int)
        ),
    )
