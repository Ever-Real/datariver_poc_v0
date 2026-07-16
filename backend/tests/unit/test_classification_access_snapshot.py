from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ClauseElement

from datariver.application.classification_access import (
    ClassificationAccessCandidate,
    ClassificationAccessPosture,
    ClassificationAccessResolver,
    ClassificationRuleRecord,
    ProviderProfileRecord,
    RestrictedGrantRecord,
)
from datariver.domain.authz import Classification
from datariver.domain.classification_access import ChatMode, RestrictedSearchScope, SearchMode
from datariver.domain.common import ConflictError
from datariver.infrastructure.db.classification_access import (
    SqlClassificationAccessSnapshotReader,
    _candidate_from_rows,
)


class _Reader:
    def __init__(
        self, candidate: ClassificationAccessCandidate | None = None, error: Exception | None = None
    ) -> None:
        self.candidate = candidate
        self.error = error

    async def read_candidate(
        self, *, workspace_id: UUID, subject_id: UUID, now: datetime
    ) -> ClassificationAccessCandidate | None:
        del workspace_id, subject_id, now
        if self.error is not None:
            raise self.error
        return self.candidate


class _Mappings:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _Mappings:
        return _Mappings(self._rows)


class _Session:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.statements: list[object] = []

    async def execute(self, statement: object) -> _Result:
        self.statements.append(statement)
        return _Result(self.rows)


def _rule(
    classification: Classification,
    *,
    chat_mode: ChatMode,
    profile_id: UUID | None,
    search_mode: SearchMode = SearchMode.ABAC,
) -> ClassificationRuleRecord:
    return ClassificationRuleRecord(
        classification=classification,
        search_mode=search_mode,
        chat_mode=chat_mode,
        provider_profile_version_id=profile_id,
    )


def _profile(
    *,
    profile_id: UUID,
    now: datetime,
    kind: str,
    maximum: Classification,
    state: str = "APPROVED",
    jurisdiction: str = "jurisdiction-x",
    observed_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> ProviderProfileRecord:
    observed = observed_at or now - timedelta(hours=1)
    expires = expires_at or now + timedelta(hours=8)
    return ProviderProfileRecord(
        provider_profile_version_id=profile_id,
        state=state,
        kind=kind,
        jurisdiction=jurisdiction,
        maximum_classification=maximum,
        residency_attestation_observed_at=observed,
        residency_attestation_expires_at=expires,
        zero_retention_attestation_observed_at=observed,
        zero_retention_attestation_expires_at=expires,
    )


def _candidate(*, now: datetime) -> ClassificationAccessCandidate:
    public_profile = uuid4()
    internal_profile = uuid4()
    confidential_profile = uuid4()
    policy_id = uuid4()
    policy_hash = "a" * 64
    return ClassificationAccessCandidate(
        policy_id=policy_id,
        policy_hash=policy_hash,
        policy_version=2,
        required_jurisdiction="jurisdiction-x",
        authorization_generation=12,
        rules=(
            _rule(
                Classification.PUBLIC,
                chat_mode=ChatMode.APPROVED_PROVIDER_ONLY,
                profile_id=public_profile,
            ),
            _rule(
                Classification.INTERNAL,
                chat_mode=ChatMode.INTERNAL_APPROVED_ONLY,
                profile_id=internal_profile,
            ),
            _rule(
                Classification.CONFIDENTIAL,
                search_mode=SearchMode.DENY,
                chat_mode=ChatMode.INTERNAL_APPROVED_ONLY,
                profile_id=confidential_profile,
            ),
            _rule(
                Classification.RESTRICTED,
                search_mode=SearchMode.EXPLICIT_GRANT_ONLY,
                chat_mode=ChatMode.DENY,
                profile_id=None,
            ),
        ),
        grants=(
            RestrictedGrantRecord(
                policy_id=policy_id,
                policy_hash=policy_hash,
                scope=RestrictedSearchScope.RESOURCE,
                scope_id=uuid4(),
                valid_from=now - timedelta(minutes=1),
                expires_at=now + timedelta(hours=3),
            ),
            RestrictedGrantRecord(
                policy_id=policy_id,
                policy_hash=policy_hash,
                scope=RestrictedSearchScope.SYSTEM,
                scope_id=uuid4(),
                valid_from=now,
                expires_at=now + timedelta(hours=4),
            ),
            RestrictedGrantRecord(
                policy_id=policy_id,
                policy_hash=policy_hash,
                scope=RestrictedSearchScope.DOMAIN,
                scope_id=uuid4(),
                valid_from=now - timedelta(minutes=2),
                expires_at=now + timedelta(hours=5),
            ),
        ),
        provider_profiles=(
            _profile(
                profile_id=public_profile,
                now=now,
                kind="EXTERNAL",
                maximum=Classification.INTERNAL,
            ),
            _profile(
                profile_id=internal_profile,
                now=now,
                kind="INTERNAL",
                maximum=Classification.INTERNAL,
            ),
            _profile(
                profile_id=confidential_profile,
                now=now,
                kind="INTERNAL",
                maximum=Classification.CONFIDENTIAL,
                expires_at=now + timedelta(hours=1),
            ),
        ),
    )


@pytest.mark.asyncio
async def test_missing_or_unavailable_policy_uses_static_ceiling_without_runtime_defaults() -> None:
    now = datetime.now(UTC)
    for reader in (_Reader(), _Reader(error=RuntimeError("database unavailable"))):
        snapshot = await ClassificationAccessResolver(reader).resolve(
            workspace_id=uuid4(), subject_id=uuid4(), now=now
        )
        assert snapshot.posture is ClassificationAccessPosture.STATIC_FLOOR
        assert snapshot.required_jurisdiction is None
        assert snapshot.authorization_generation is None
        assert snapshot.restricted_resource_ids == frozenset()
        assert snapshot.rule_for(Classification.PUBLIC).search_mode is SearchMode.ABAC
        assert snapshot.rule_for(Classification.CONFIDENTIAL).search_mode is SearchMode.ABAC
        assert snapshot.rule_for(Classification.CONFIDENTIAL).chat_mode is ChatMode.DENY
        assert snapshot.rule_for(Classification.RESTRICTED).search_mode is SearchMode.DENY
        assert snapshot.rule_for(Classification.RESTRICTED).chat_mode is ChatMode.DENY
        for classification in (Classification.PUBLIC, Classification.INTERNAL):
            rule = snapshot.rule_for(classification)
            assert rule.chat_mode is ChatMode.INTERNAL_APPROVED_ONLY
            assert rule.provider_profile_version_id is None


@pytest.mark.asyncio
async def test_governed_snapshot_contains_rules_scopes_generation_and_nearest_boundary() -> None:
    now = datetime.now(UTC)
    candidate = _candidate(now=now)
    snapshot = await ClassificationAccessResolver(_Reader(candidate)).resolve(
        workspace_id=uuid4(), subject_id=uuid4(), now=now
    )
    assert snapshot.posture is ClassificationAccessPosture.GOVERNED
    assert snapshot.policy_id == candidate.policy_id
    assert snapshot.policy_hash == candidate.policy_hash
    assert snapshot.policy_version == 2
    assert snapshot.required_jurisdiction == "jurisdiction-x"
    assert snapshot.authorization_generation == 12
    assert len(snapshot.restricted_resource_ids) == 1
    assert len(snapshot.restricted_system_ids) == 1
    assert len(snapshot.restricted_domain_ids) == 1
    assert snapshot.nearest_validity_boundary == now + timedelta(hours=1)
    assert snapshot.rule_for(Classification.CONFIDENTIAL).chat_mode is (
        ChatMode.INTERNAL_APPROVED_ONLY
    )
    assert snapshot.rule_for(Classification.RESTRICTED).chat_mode is ChatMode.DENY


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "replacement",
    [
        {"missing": True},
        {"state": "REVOKED"},
        {"jurisdiction": "other-jurisdiction"},
        {"maximum": Classification.PUBLIC},
        {"kind": "EXTERNAL"},
        {"expires_at": datetime(2020, 1, 1, tzinfo=UTC)},
        {"observed_at": datetime(2100, 1, 1, tzinfo=UTC)},
    ],
)
async def test_ineligible_provider_downgrades_only_the_referencing_chat_rule(
    replacement: dict[str, object],
) -> None:
    now = datetime.now(UTC)
    candidate = _candidate(now=now)
    internal_rule = candidate.rules[1]
    assert internal_rule.provider_profile_version_id is not None
    profiles = list(candidate.provider_profiles)
    if replacement.get("missing"):
        profiles.pop(1)
    else:
        profiles[1] = _profile(
            profile_id=internal_rule.provider_profile_version_id,
            now=now,
            kind=cast(str, replacement.get("kind", "INTERNAL")),
            maximum=cast(
                Classification,
                replacement.get("maximum", Classification.INTERNAL),
            ),
            state=cast(str, replacement.get("state", "APPROVED")),
            jurisdiction=cast(str, replacement.get("jurisdiction", "jurisdiction-x")),
            observed_at=cast(datetime | None, replacement.get("observed_at")),
            expires_at=cast(datetime | None, replacement.get("expires_at")),
        )
    candidate = ClassificationAccessCandidate(
        policy_id=candidate.policy_id,
        policy_hash=candidate.policy_hash,
        policy_version=candidate.policy_version,
        required_jurisdiction=candidate.required_jurisdiction,
        authorization_generation=candidate.authorization_generation,
        rules=candidate.rules,
        grants=candidate.grants,
        provider_profiles=tuple(profiles),
    )

    snapshot = await ClassificationAccessResolver(_Reader(candidate)).resolve(
        workspace_id=uuid4(), subject_id=uuid4(), now=now
    )
    assert snapshot.posture is ClassificationAccessPosture.GOVERNED
    internal = snapshot.rule_for(Classification.INTERNAL)
    assert internal.chat_mode is ChatMode.DENY
    assert internal.provider_profile_version_id is None
    assert snapshot.rule_for(Classification.PUBLIC).chat_mode is (ChatMode.APPROVED_PROVIDER_ONLY)


@pytest.mark.asyncio
async def test_malformed_rule_or_grant_binding_falls_back_to_static_floor() -> None:
    now = datetime.now(UTC)
    candidate = _candidate(now=now)
    malformed_rules = ClassificationAccessCandidate(
        policy_id=candidate.policy_id,
        policy_hash=candidate.policy_hash,
        policy_version=candidate.policy_version,
        required_jurisdiction=candidate.required_jurisdiction,
        authorization_generation=candidate.authorization_generation,
        rules=candidate.rules[:-1],
        grants=candidate.grants,
        provider_profiles=candidate.provider_profiles,
    )
    wrong_policy_grant = candidate.grants[0]
    mismatched_grants = ClassificationAccessCandidate(
        policy_id=candidate.policy_id,
        policy_hash=candidate.policy_hash,
        policy_version=candidate.policy_version,
        required_jurisdiction=candidate.required_jurisdiction,
        authorization_generation=candidate.authorization_generation,
        rules=candidate.rules,
        grants=(
            RestrictedGrantRecord(
                policy_id=uuid4(),
                policy_hash=wrong_policy_grant.policy_hash,
                scope=wrong_policy_grant.scope,
                scope_id=wrong_policy_grant.scope_id,
                valid_from=wrong_policy_grant.valid_from,
                expires_at=wrong_policy_grant.expires_at,
            ),
        ),
        provider_profiles=candidate.provider_profiles,
    )
    restricted_widening = ClassificationAccessCandidate(
        policy_id=candidate.policy_id,
        policy_hash=candidate.policy_hash,
        policy_version=candidate.policy_version,
        required_jurisdiction=candidate.required_jurisdiction,
        authorization_generation=candidate.authorization_generation,
        rules=(
            *candidate.rules[:-1],
            _rule(
                Classification.RESTRICTED,
                search_mode=SearchMode.ABAC,
                chat_mode=ChatMode.DENY,
                profile_id=None,
            ),
        ),
        grants=(),
        provider_profiles=candidate.provider_profiles,
    )
    for invalid in (malformed_rules, mismatched_grants, restricted_widening):
        snapshot = await ClassificationAccessResolver(_Reader(invalid)).resolve(
            workspace_id=uuid4(), subject_id=uuid4(), now=now
        )
        assert snapshot.posture is ClassificationAccessPosture.STATIC_FLOOR


def _database_rows(*, now: datetime) -> list[dict[str, Any]]:
    policy_id = uuid4()
    provider_ids = (uuid4(), uuid4(), uuid4())
    grant_id = uuid4()
    grant_scope_id = uuid4()
    rows: list[dict[str, Any]] = []
    configurations = (
        (0, "ABAC", "APPROVED_PROVIDER_ONLY", provider_ids[0], "EXTERNAL", 1),
        (1, "ABAC", "INTERNAL_APPROVED_ONLY", provider_ids[1], "INTERNAL", 1),
        (2, "DENY", "INTERNAL_APPROVED_ONLY", provider_ids[2], "INTERNAL", 2),
        (3, "EXPLICIT_GRANT_ONLY", "DENY", None, None, None),
    )
    for classification, search, chat, profile_id, kind, maximum in configurations:
        rows.append(
            {
                "policy_id": policy_id,
                "policy_hash": "b" * 64,
                "policy_version": 2,
                "required_jurisdiction": "jurisdiction-y",
                "authorization_generation": 7,
                "classification": classification,
                "search_mode": search,
                "chat_mode": chat,
                "rule_provider_profile_id": profile_id,
                "profile_id": profile_id,
                "profile_state": "APPROVED" if profile_id else None,
                "profile_kind": kind,
                "profile_jurisdiction": "jurisdiction-y" if profile_id else None,
                "profile_maximum_classification": maximum,
                "residency_attestation_observed_at": now - timedelta(hours=1),
                "residency_attestation_expires_at": now + timedelta(hours=4),
                "zero_retention_attestation_observed_at": now - timedelta(hours=1),
                "zero_retention_attestation_expires_at": now + timedelta(hours=3),
                "grant_id": grant_id,
                "grant_policy_id": policy_id,
                "grant_policy_hash": "b" * 64,
                "grant_scope": "RESOURCE",
                "grant_scope_id": grant_scope_id,
                "grant_valid_from": now - timedelta(minutes=1),
                "grant_expires_at": now + timedelta(hours=2),
            }
        )
    return rows


@pytest.mark.asyncio
async def test_sql_reader_uses_one_workspace_subject_set_query_and_deduplicates_rows() -> None:
    now = datetime.now(UTC)
    session = _Session(_database_rows(now=now))
    reader = SqlClassificationAccessSnapshotReader(cast(AsyncSession, session))
    candidate = await reader.read_candidate(workspace_id=uuid4(), subject_id=uuid4(), now=now)
    assert candidate is not None
    assert len(session.statements) == 1
    assert len(candidate.rules) == 4
    assert len(candidate.grants) == 1
    assert len(candidate.provider_profiles) == 3

    compiled = cast(ClauseElement, session.statements[0]).compile()
    sql = str(compiled)
    values = set(compiled.params.values())
    assert "classification_access_policy_rules" in sql
    assert "classification_access_generations" in sql
    assert "restricted_search_grants.subject_id" in sql
    assert "restricted_search_grants.valid_from <=" in sql
    assert "restricted_search_grants.expires_at >" in sql
    assert "restricted_search_grants.classification_policy_hash" in sql
    assert "inference_provider_profile_versions" in sql
    assert {"ACTIVE", "APPROVED"}.intersection(values) == {"ACTIVE"}
    assert "assets_projection" not in sql


def test_database_row_integrity_mismatch_fails_closed_before_snapshot_creation() -> None:
    now = datetime.now(UTC)
    rows = _database_rows(now=now)
    rows[1]["policy_hash"] = "c" * 64
    with pytest.raises(ConflictError, match="inconsistent"):
        _candidate_from_rows(rows)

    rows = _database_rows(now=now)
    rows[0]["authorization_generation"] = None
    with pytest.raises(ConflictError, match="generation"):
        _candidate_from_rows(rows)
