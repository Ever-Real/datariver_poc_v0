from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Sequence
from datetime import datetime
from types import TracebackType
from typing import Any, cast
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from datariver.application.classification_access import (
    ClassificationAccessCandidate,
    ClassificationRuleRecord,
    ProviderProfileRecord,
    RestrictedGrantRecord,
)
from datariver.application.classification_access_admin import (
    ClassificationAccessAdminUnitOfWork,
    ClassificationPolicyPage,
    RestrictedSearchGrantPage,
)
from datariver.domain.authz import Classification
from datariver.domain.classification_access import (
    ChatMode,
    ClassificationAccessPolicy,
    ClassificationAccessPolicyState,
    ClassificationAccessRule,
    RestrictedSearchGrant,
    RestrictedSearchGrantState,
    RestrictedSearchScope,
    SearchMode,
)
from datariver.domain.common import (
    ConflictError,
    ValidationError,
    canonical_json_hash,
    uuid7,
)
from datariver.infrastructure.db.admin_access import SqlMembershipAccessRepository
from datariver.infrastructure.db.governance import SqlIdempotencyStore, SqlOutboxWriter
from datariver.infrastructure.db.models.classification_access import (
    ClassificationAccessGenerationModel,
    ClassificationAccessPolicyRuleModel,
    ClassificationAccessPolicyVersionModel,
    RestrictedSearchGrantEventModel,
    RestrictedSearchGrantModel,
)
from datariver.infrastructure.db.models.inference import InferenceProviderProfileVersionModel
from datariver.infrastructure.db.rls import set_security_context

_LIST_CURSOR_MAX_LENGTH = 2_000


def _encode_list_cursor(
    *,
    scope: str,
    workspace_id: UUID,
    filters: dict[str, str | None],
    boundary: dict[str, object],
) -> str:
    payload = json.dumps(
        {
            "v": 1,
            "scope": scope,
            "workspace_id": str(workspace_id),
            "filters": filters,
            "boundary": boundary,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_list_cursor(
    cursor: str,
    *,
    scope: str,
    workspace_id: UUID,
    filters: dict[str, str | None],
) -> dict[str, object]:
    try:
        if not cursor or len(cursor) > _LIST_CURSOR_MAX_LENGTH:
            raise ValueError
        payload = base64.b64decode(
            cursor + "=" * (-len(cursor) % 4),
            altchars=b"-_",
            validate=True,
        )
        document = json.loads(payload)
        if (
            not isinstance(document, dict)
            or frozenset(document)
            != frozenset({"v", "scope", "workspace_id", "filters", "boundary"})
            or document.get("v") != 1
            or document.get("scope") != scope
            or document.get("workspace_id") != str(workspace_id)
            or document.get("filters") != filters
            or not isinstance(document.get("boundary"), dict)
        ):
            raise ValueError
        boundary = cast(dict[str, object], document["boundary"])
        if cursor != _encode_list_cursor(
            scope=scope,
            workspace_id=workspace_id,
            filters=filters,
            boundary=boundary,
        ):
            raise ValueError
        return boundary
    except (
        ValueError,
        TypeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        binascii.Error,
    ) as error:
        raise ValidationError(
            "The classification governance cursor is stale or does not match this request."
        ) from error


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
        composition_profile = aliased(
            InferenceProviderProfileVersionModel,
            name="composition_profile",
        )
        embedding_profile = aliased(
            InferenceProviderProfileVersionModel,
            name="embedding_profile",
        )
        reranker_profile = aliased(
            InferenceProviderProfileVersionModel,
            name="reranker_profile",
        )

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
                rule.embedding_provider_profile_version_id.label(
                    "rule_embedding_provider_profile_id"
                ),
                rule.reranker_provider_profile_version_id.label(
                    "rule_reranker_provider_profile_id"
                ),
                *_profile_snapshot_columns(composition_profile, prefix="composition"),
                *_profile_snapshot_columns(embedding_profile, prefix="embedding"),
                *_profile_snapshot_columns(reranker_profile, prefix="reranker"),
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
                composition_profile,
                and_(
                    composition_profile.workspace_id == rule.workspace_id,
                    composition_profile.id == rule.provider_profile_version_id,
                ),
            )
            .outerjoin(
                embedding_profile,
                and_(
                    embedding_profile.workspace_id == rule.workspace_id,
                    embedding_profile.id == rule.embedding_provider_profile_version_id,
                ),
            )
            .outerjoin(
                reranker_profile,
                and_(
                    reranker_profile.workspace_id == rule.workspace_id,
                    reranker_profile.id == rule.reranker_provider_profile_version_id,
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


def _profile_snapshot_columns(profile: Any, *, prefix: str) -> tuple[Any, ...]:
    return (
        profile.id.label(f"{prefix}_profile_id"),
        profile.state.label(f"{prefix}_profile_state"),
        profile.kind.label(f"{prefix}_profile_kind"),
        profile.server_route_key.label(f"{prefix}_server_route_key"),
        profile.provider_identity.label(f"{prefix}_provider_identity"),
        profile.model_identity.label(f"{prefix}_model_identity"),
        profile.deployment_identity.label(f"{prefix}_deployment_identity"),
        profile.jurisdiction.label(f"{prefix}_profile_jurisdiction"),
        profile.maximum_classification.label(f"{prefix}_profile_maximum_classification"),
        profile.residency_attestation_observed_at.label(
            f"{prefix}_residency_attestation_observed_at"
        ),
        profile.residency_attestation_expires_at.label(
            f"{prefix}_residency_attestation_expires_at"
        ),
        profile.zero_retention_attestation_observed_at.label(
            f"{prefix}_zero_retention_attestation_observed_at"
        ),
        profile.zero_retention_attestation_expires_at.label(
            f"{prefix}_zero_retention_attestation_expires_at"
        ),
    )


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
            embedding_provider_profile_version_id=cast(
                UUID | None,
                row["rule_embedding_provider_profile_id"],
            ),
            reranker_provider_profile_version_id=cast(
                UUID | None,
                row["rule_reranker_provider_profile_id"],
            ),
        )
        existing_rule = rules.get(classification)
        if existing_rule is not None and existing_rule != rule_record:
            raise ConflictError("A classification rule has inconsistent snapshot rows.")
        rules[classification] = rule_record

        for prefix in ("composition", "embedding", "reranker"):
            profile_record = _profile_record_from_row(row, prefix=prefix)
            if profile_record is None:
                continue
            profile_id = profile_record.provider_profile_version_id
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


def _profile_record_from_row(
    row: dict[str, Any],
    *,
    prefix: str,
) -> ProviderProfileRecord | None:
    profile_id = cast(UUID | None, row[f"{prefix}_profile_id"])
    if profile_id is None:
        return None
    return ProviderProfileRecord(
        provider_profile_version_id=profile_id,
        state=str(row[f"{prefix}_profile_state"]),
        kind=str(row[f"{prefix}_profile_kind"]),
        server_route_key=str(row[f"{prefix}_server_route_key"]),
        provider_identity=str(row[f"{prefix}_provider_identity"]),
        model_identity=str(row[f"{prefix}_model_identity"]),
        deployment_identity=str(row[f"{prefix}_deployment_identity"]),
        jurisdiction=str(row[f"{prefix}_profile_jurisdiction"]),
        maximum_classification=Classification(int(row[f"{prefix}_profile_maximum_classification"])),
        residency_attestation_observed_at=cast(
            datetime,
            row[f"{prefix}_residency_attestation_observed_at"],
        ),
        residency_attestation_expires_at=cast(
            datetime,
            row[f"{prefix}_residency_attestation_expires_at"],
        ),
        zero_retention_attestation_observed_at=cast(
            datetime,
            row[f"{prefix}_zero_retention_attestation_observed_at"],
        ),
        zero_retention_attestation_expires_at=cast(
            datetime,
            row[f"{prefix}_zero_retention_attestation_expires_at"],
        ),
    )


class SqlClassificationPolicyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, policy: ClassificationAccessPolicy) -> None:
        self._session.add(_policy_model(policy))
        self._session.add_all(
            [
                ClassificationAccessPolicyRuleModel(
                    id=uuid7(),
                    workspace_id=policy.workspace_id,
                    policy_id=policy.policy_id,
                    policy_hash=policy.payload_hash,
                    classification=int(rule.classification),
                    search_mode=rule.search_mode.value,
                    chat_mode=rule.chat_mode.value,
                    provider_profile_version_id=rule.provider_profile_version_id,
                    embedding_provider_profile_version_id=(
                        rule.embedding_provider_profile_version_id
                    ),
                    reranker_provider_profile_version_id=(
                        rule.reranker_provider_profile_version_id
                    ),
                )
                for rule in policy.rules
            ]
        )

    async def save(self, policy: ClassificationAccessPolicy) -> None:
        result = await self._session.execute(
            update(ClassificationAccessPolicyVersionModel)
            .where(
                ClassificationAccessPolicyVersionModel.workspace_id == policy.workspace_id,
                ClassificationAccessPolicyVersionModel.id == policy.policy_id,
                ClassificationAccessPolicyVersionModel.version == policy.version - 1,
            )
            .values(
                state=policy.state.value,
                checker_id=policy.checker_id,
                decision_reason=policy.decision_reason,
                decision_policy_decision_id=policy.decision_policy_decision_id,
                decided_at=policy.decided_at,
                superseded_by=policy.superseded_by,
                supersede_reason=policy.supersede_reason,
                supersede_policy_decision_id=policy.supersede_policy_decision_id,
                superseded_at=policy.superseded_at,
                version=policy.version,
            )
        )
        if cast(CursorResult[Any], result).rowcount != 1:
            raise ConflictError("The classification policy was modified by another operation.")

    async def get(
        self, *, workspace_id: UUID, policy_id: UUID
    ) -> ClassificationAccessPolicy | None:
        return await self._one(workspace_id=workspace_id, policy_id=policy_id, lock=False)

    async def get_for_update(
        self, *, workspace_id: UUID, policy_id: UUID
    ) -> ClassificationAccessPolicy | None:
        return await self._one(workspace_id=workspace_id, policy_id=policy_id, lock=True)

    async def get_active(self, *, workspace_id: UUID) -> ClassificationAccessPolicy | None:
        values = await self._load(
            workspace_id=workspace_id,
            state=ClassificationAccessPolicyState.ACTIVE.value,
            limit=1,
            lock=False,
        )
        return values[0] if values else None

    async def get_active_for_update(
        self, *, workspace_id: UUID, excluding_policy_id: UUID | None = None
    ) -> ClassificationAccessPolicy | None:
        statement = _policy_rows_statement(workspace_id=workspace_id).where(
            ClassificationAccessPolicyVersionModel.state
            == ClassificationAccessPolicyState.ACTIVE.value
        )
        if excluding_policy_id is not None:
            statement = statement.where(
                ClassificationAccessPolicyVersionModel.id != excluding_policy_id
            )
        rows = (await self._session.execute(statement.with_for_update())).all()
        policies = _policies_from_rows(rows)
        if len(policies) > 1:
            raise ConflictError("Multiple active classification policies were found.")
        return policies[0] if policies else None

    async def list(
        self,
        *,
        workspace_id: UUID,
        state: str | None,
        limit: int,
        cursor: str | None,
    ) -> ClassificationPolicyPage:
        if limit < 1 or limit > 100:
            raise ValidationError("The classification policy list limit is invalid.")
        filters = {"state": state}
        boundary_number: int | None = None
        if cursor is not None:
            boundary = _decode_list_cursor(
                cursor,
                scope="classification-policy-history",
                workspace_id=workspace_id,
                filters=filters,
            )
            boundary_value = boundary.get("policy_number")
            if frozenset(boundary) != frozenset({"policy_number"}) or not isinstance(
                boundary_value, int
            ):
                raise ValidationError(
                    "The classification governance cursor is stale or does not match this request."
                )
            boundary_number = boundary_value
            if boundary_number < 1:
                raise ValidationError(
                    "The classification governance cursor is stale or does not match this request."
                )

        policy_ids = select(ClassificationAccessPolicyVersionModel.id).where(
            ClassificationAccessPolicyVersionModel.workspace_id == workspace_id
        )
        if state is not None:
            policy_ids = policy_ids.where(ClassificationAccessPolicyVersionModel.state == state)
        if boundary_number is not None:
            policy_ids = policy_ids.where(
                ClassificationAccessPolicyVersionModel.policy_number < boundary_number
            )
        policy_ids = policy_ids.order_by(
            ClassificationAccessPolicyVersionModel.policy_number.desc()
        ).limit(limit + 1)
        selected_ids = tuple((await self._session.scalars(policy_ids)).all())
        if not selected_ids:
            return ClassificationPolicyPage(items=(), next_cursor=None)
        visible_ids = selected_ids[:limit]
        statement = _policy_rows_statement(workspace_id=workspace_id).where(
            ClassificationAccessPolicyVersionModel.id.in_(visible_ids)
        )
        items = _policies_from_rows((await self._session.execute(statement)).all())
        return ClassificationPolicyPage(
            items=items,
            next_cursor=(
                _encode_list_cursor(
                    scope="classification-policy-history",
                    workspace_id=workspace_id,
                    filters=filters,
                    boundary={"policy_number": items[-1].policy_number},
                )
                if len(selected_ids) > limit
                else None
            ),
        )

    async def next_policy_number(self, *, workspace_id: UUID) -> int:
        maximum = await self._session.scalar(
            select(func.max(ClassificationAccessPolicyVersionModel.policy_number)).where(
                ClassificationAccessPolicyVersionModel.workspace_id == workspace_id
            )
        )
        return int(maximum or 0) + 1

    async def assert_provider_rules_eligible(
        self, *, policy: ClassificationAccessPolicy, now: datetime
    ) -> None:
        enabled = tuple(rule for rule in policy.rules if rule.chat_mode is not ChatMode.DENY)
        if any(rule.provider_profile_version_id is None for rule in enabled):
            raise ConflictError(
                "Every enabled Chat rule requires one composition provider profile."
            )
        profile_ids = frozenset(
            profile_id
            for rule in enabled
            for profile_id in (
                rule.provider_profile_version_id,
                rule.embedding_provider_profile_version_id,
                rule.reranker_provider_profile_version_id,
            )
            if profile_id is not None
        )
        profiles = (
            await self._session.scalars(
                select(InferenceProviderProfileVersionModel)
                .where(
                    InferenceProviderProfileVersionModel.workspace_id == policy.workspace_id,
                    InferenceProviderProfileVersionModel.id.in_(profile_ids),
                )
                .with_for_update()
            )
        ).all()
        by_id = {profile.id: profile for profile in profiles}
        for rule in enabled:
            for profile_id in (
                rule.provider_profile_version_id,
                rule.embedding_provider_profile_version_id,
                rule.reranker_provider_profile_version_id,
            ):
                if profile_id is None:
                    continue
                profile = by_id.get(profile_id)
                if (
                    profile is None
                    or profile.state != "APPROVED"
                    or profile.jurisdiction != policy.required_jurisdiction
                    or profile.maximum_classification < int(rule.classification)
                    or profile.residency_attestation_observed_at > now
                    or profile.residency_attestation_expires_at <= now
                    or profile.zero_retention_attestation_observed_at > now
                    or profile.zero_retention_attestation_expires_at <= now
                    or (
                        rule.chat_mode is ChatMode.INTERNAL_APPROVED_ONLY
                        and profile.kind != "INTERNAL"
                    )
                    or (
                        rule.classification is Classification.CONFIDENTIAL
                        and profile.kind != "INTERNAL"
                    )
                ):
                    raise ConflictError(
                        "The classification policy references an ineligible provider profile."
                    )

    async def _one(
        self, *, workspace_id: UUID, policy_id: UUID, lock: bool
    ) -> ClassificationAccessPolicy | None:
        statement = _policy_rows_statement(workspace_id=workspace_id).where(
            ClassificationAccessPolicyVersionModel.id == policy_id
        )
        if lock:
            statement = statement.with_for_update()
        policies = _policies_from_rows((await self._session.execute(statement)).all())
        return policies[0] if policies else None

    async def _load(
        self, *, workspace_id: UUID, state: str | None, limit: int, lock: bool
    ) -> tuple[ClassificationAccessPolicy, ...]:
        policy_ids = select(ClassificationAccessPolicyVersionModel.id).where(
            ClassificationAccessPolicyVersionModel.workspace_id == workspace_id
        )
        if state is not None:
            policy_ids = policy_ids.where(ClassificationAccessPolicyVersionModel.state == state)
        policy_ids = policy_ids.order_by(
            ClassificationAccessPolicyVersionModel.policy_number.desc()
        ).limit(limit)
        statement = _policy_rows_statement(workspace_id=workspace_id).where(
            ClassificationAccessPolicyVersionModel.id.in_(policy_ids)
        )
        if lock:
            statement = statement.with_for_update()
        return _policies_from_rows((await self._session.execute(statement)).all())


class SqlRestrictedSearchGrantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, grant: RestrictedSearchGrant) -> None:
        self._session.add(_grant_model(grant))
        self._session.add(_grant_event_model(grant))

    async def save(self, grant: RestrictedSearchGrant) -> None:
        result = await self._session.execute(
            update(RestrictedSearchGrantModel)
            .where(
                RestrictedSearchGrantModel.workspace_id == grant.workspace_id,
                RestrictedSearchGrantModel.id == grant.grant_id,
                RestrictedSearchGrantModel.version == grant.version - 1,
            )
            .values(
                state=grant.state.value,
                checker_id=grant.checker_id,
                decision_reason=grant.decision_reason,
                decision_policy_decision_id=grant.decision_policy_decision_id,
                decided_at=grant.decided_at,
                revoked_by=grant.revoked_by,
                revocation_reason=grant.revocation_reason,
                revocation_policy_decision_id=grant.revocation_policy_decision_id,
                revoked_at=grant.revoked_at,
                version=grant.version,
            )
        )
        if cast(CursorResult[Any], result).rowcount != 1:
            raise ConflictError("The RESTRICTED Search grant was modified by another operation.")
        self._session.add(_grant_event_model(grant))

    async def get(self, *, workspace_id: UUID, grant_id: UUID) -> RestrictedSearchGrant | None:
        return await self._one(workspace_id=workspace_id, grant_id=grant_id, lock=False)

    async def get_for_update(
        self, *, workspace_id: UUID, grant_id: UUID
    ) -> RestrictedSearchGrant | None:
        return await self._one(workspace_id=workspace_id, grant_id=grant_id, lock=True)

    async def list(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID | None,
        state: str | None,
        limit: int,
        cursor: str | None,
    ) -> RestrictedSearchGrantPage:
        if limit < 1 or limit > 100:
            raise ValidationError("The RESTRICTED Search grant list limit is invalid.")
        filters = {
            "state": state,
            "subject_id": str(subject_id) if subject_id is not None else None,
        }
        statement = (
            select(RestrictedSearchGrantModel)
            .where(RestrictedSearchGrantModel.workspace_id == workspace_id)
            .order_by(
                RestrictedSearchGrantModel.created_at.desc(),
                RestrictedSearchGrantModel.id,
            )
            .limit(limit + 1)
        )
        if subject_id is not None:
            statement = statement.where(RestrictedSearchGrantModel.subject_id == subject_id)
        if state is not None:
            statement = statement.where(RestrictedSearchGrantModel.state == state)
        if cursor is not None:
            boundary = _decode_list_cursor(
                cursor,
                scope="restricted-search-grant-history",
                workspace_id=workspace_id,
                filters=filters,
            )
            try:
                if frozenset(boundary) != frozenset({"created_at", "id"}):
                    raise ValueError
                boundary_created_at = datetime.fromisoformat(str(boundary["created_at"]))
                boundary_id = UUID(str(boundary["id"]))
                if boundary_created_at.tzinfo is None or boundary_created_at.utcoffset() is None:
                    raise ValueError
            except (KeyError, TypeError, ValueError) as error:
                raise ValidationError(
                    "The classification governance cursor is stale or does not match this request."
                ) from error
            statement = statement.where(
                or_(
                    RestrictedSearchGrantModel.created_at < boundary_created_at,
                    and_(
                        RestrictedSearchGrantModel.created_at == boundary_created_at,
                        RestrictedSearchGrantModel.id > boundary_id,
                    ),
                )
            )
        models = tuple((await self._session.scalars(statement)).all())
        visible = models[:limit]
        items = tuple(_hydrate_grant(model) for model in visible)
        return RestrictedSearchGrantPage(
            items=items,
            next_cursor=(
                _encode_list_cursor(
                    scope="restricted-search-grant-history",
                    workspace_id=workspace_id,
                    filters=filters,
                    boundary={
                        "created_at": visible[-1].created_at.isoformat(),
                        "id": str(visible[-1].id),
                    },
                )
                if len(models) > limit
                else None
            ),
        )

    async def _one(
        self, *, workspace_id: UUID, grant_id: UUID, lock: bool
    ) -> RestrictedSearchGrant | None:
        statement = select(RestrictedSearchGrantModel).where(
            RestrictedSearchGrantModel.workspace_id == workspace_id,
            RestrictedSearchGrantModel.id == grant_id,
        )
        if lock:
            statement = statement.with_for_update()
        model = (await self._session.scalars(statement)).one_or_none()
        return _hydrate_grant(model) if model is not None else None


class SqlClassificationAccessAdminUnitOfWork(ClassificationAccessAdminUnitOfWork):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self.policies: SqlClassificationPolicyRepository
        self.grants: SqlRestrictedSearchGrantRepository
        self.memberships: SqlMembershipAccessRepository
        self.idempotency: SqlIdempotencyStore
        self.outbox: SqlOutboxWriter
        self._committed = False

    async def __aenter__(self) -> SqlClassificationAccessAdminUnitOfWork:
        self._session = self._session_factory()
        self.policies = SqlClassificationPolicyRepository(self._session)
        self.grants = SqlRestrictedSearchGrantRepository(self._session)
        self.memberships = SqlMembershipAccessRepository(self._session)
        self.idempotency = SqlIdempotencyStore(self._session)
        self.outbox = SqlOutboxWriter(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_value, traceback
        if self._session is None:
            return
        if exc_type is not None or not self._committed:
            await self._session.rollback()
        await self._session.close()

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await set_security_context(self._session, workspace_id=workspace_id, subject_id=subject_id)

    async def lock_workspace(self, *, workspace_id: UUID) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"datariver:classification-access:{workspace_id}"},
        )

    async def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await self._session.commit()
        self._committed = True


def _policy_rows_statement(*, workspace_id: UUID) -> Any:
    return (
        select(ClassificationAccessPolicyVersionModel, ClassificationAccessPolicyRuleModel)
        .join(
            ClassificationAccessPolicyRuleModel,
            and_(
                ClassificationAccessPolicyRuleModel.workspace_id
                == ClassificationAccessPolicyVersionModel.workspace_id,
                ClassificationAccessPolicyRuleModel.policy_id
                == ClassificationAccessPolicyVersionModel.id,
                ClassificationAccessPolicyRuleModel.policy_hash
                == ClassificationAccessPolicyVersionModel.payload_hash,
            ),
        )
        .where(ClassificationAccessPolicyVersionModel.workspace_id == workspace_id)
        .order_by(
            ClassificationAccessPolicyVersionModel.policy_number.desc(),
            ClassificationAccessPolicyRuleModel.classification,
        )
    )


def _policies_from_rows(rows: Sequence[Any]) -> tuple[ClassificationAccessPolicy, ...]:
    grouped: dict[UUID, tuple[ClassificationAccessPolicyVersionModel, list[Any]]] = {}
    for policy_model, rule_model in rows:
        entry = grouped.setdefault(policy_model.id, (policy_model, []))
        entry[1].append(rule_model)
    return tuple(_hydrate_policy(model, rules) for model, rules in grouped.values())


def _hydrate_policy(
    model: ClassificationAccessPolicyVersionModel,
    rule_models: list[ClassificationAccessPolicyRuleModel],
) -> ClassificationAccessPolicy:
    try:
        rules = tuple(
            ClassificationAccessRule(
                classification=Classification(rule.classification),
                search_mode=SearchMode(rule.search_mode),
                chat_mode=ChatMode(rule.chat_mode),
                provider_profile_version_id=rule.provider_profile_version_id,
                embedding_provider_profile_version_id=(rule.embedding_provider_profile_version_id),
                reranker_provider_profile_version_id=(rule.reranker_provider_profile_version_id),
            )
            for rule in sorted(rule_models, key=lambda value: value.classification)
        )
        state = ClassificationAccessPolicyState(model.state)
    except ValueError as error:
        raise ConflictError("The stored classification policy is invalid.") from error
    if len(rules) != 4 or {rule.classification for rule in rules} != set(Classification):
        raise ConflictError("The stored classification policy rule set is incomplete.")
    document = {
        "required_jurisdiction": model.required_jurisdiction,
        "restricted_search_grant_maximum_days": model.restricted_search_grant_maximum_days,
        "rules": [rule.document() for rule in rules],
    }
    if canonical_json_hash(document) != model.payload_hash:
        raise ConflictError("The stored classification policy failed its integrity check.")
    return ClassificationAccessPolicy(
        policy_id=model.id,
        workspace_id=model.workspace_id,
        policy_number=model.policy_number,
        required_jurisdiction=model.required_jurisdiction,
        restricted_search_grant_maximum_days=model.restricted_search_grant_maximum_days,
        rules=rules,
        payload_hash=model.payload_hash,
        requester_id=model.requester_id,
        request_reason=model.request_reason,
        request_policy_decision_id=model.request_policy_decision_id,
        state=state,
        checker_id=model.checker_id,
        decision_reason=model.decision_reason,
        decision_policy_decision_id=model.decision_policy_decision_id,
        decided_at=model.decided_at,
        superseded_by=model.superseded_by,
        supersede_reason=model.supersede_reason,
        supersede_policy_decision_id=model.supersede_policy_decision_id,
        superseded_at=model.superseded_at,
        version=model.version,
    )


def _policy_model(policy: ClassificationAccessPolicy) -> ClassificationAccessPolicyVersionModel:
    return ClassificationAccessPolicyVersionModel(
        id=policy.policy_id,
        workspace_id=policy.workspace_id,
        policy_number=policy.policy_number,
        required_jurisdiction=policy.required_jurisdiction,
        restricted_search_grant_maximum_days=policy.restricted_search_grant_maximum_days,
        payload_hash=policy.payload_hash,
        requester_id=policy.requester_id,
        request_reason=policy.request_reason,
        request_policy_decision_id=policy.request_policy_decision_id,
        state=policy.state.value,
        checker_id=policy.checker_id,
        decision_reason=policy.decision_reason,
        decision_policy_decision_id=policy.decision_policy_decision_id,
        decided_at=policy.decided_at,
        superseded_by=policy.superseded_by,
        supersede_reason=policy.supersede_reason,
        supersede_policy_decision_id=policy.supersede_policy_decision_id,
        superseded_at=policy.superseded_at,
        version=policy.version,
    )


def _grant_model(grant: RestrictedSearchGrant) -> RestrictedSearchGrantModel:
    return RestrictedSearchGrantModel(
        id=grant.grant_id,
        workspace_id=grant.workspace_id,
        classification_policy_id=grant.classification_policy_id,
        classification_policy_hash=grant.classification_policy_hash,
        subject_id=grant.subject_id,
        scope=grant.scope.value,
        scope_id=grant.scope_id,
        purpose=grant.purpose,
        valid_from=grant.valid_from,
        expires_at=grant.expires_at,
        payload_hash=grant.payload_hash,
        requester_id=grant.requester_id,
        request_reason=grant.request_reason,
        request_policy_decision_id=grant.request_policy_decision_id,
        state=grant.state.value,
        checker_id=grant.checker_id,
        decision_reason=grant.decision_reason,
        decision_policy_decision_id=grant.decision_policy_decision_id,
        decided_at=grant.decided_at,
        revoked_by=grant.revoked_by,
        revocation_reason=grant.revocation_reason,
        revocation_policy_decision_id=grant.revocation_policy_decision_id,
        revoked_at=grant.revoked_at,
        version=grant.version,
    )


def _hydrate_grant(model: RestrictedSearchGrantModel) -> RestrictedSearchGrant:
    try:
        scope = RestrictedSearchScope(model.scope)
        state = RestrictedSearchGrantState(model.state)
    except ValueError as error:
        raise ConflictError("The stored RESTRICTED Search grant is invalid.") from error
    document = {
        "workspace_id": str(model.workspace_id),
        "classification_policy_id": str(model.classification_policy_id),
        "classification_policy_hash": model.classification_policy_hash,
        "subject_id": str(model.subject_id),
        "scope": scope.value,
        "scope_id": str(model.scope_id),
        "purpose": model.purpose,
        "valid_from": model.valid_from.isoformat(),
        "expires_at": model.expires_at.isoformat(),
    }
    if canonical_json_hash(document) != model.payload_hash:
        raise ConflictError("The stored RESTRICTED Search grant failed its integrity check.")
    return RestrictedSearchGrant(
        grant_id=model.id,
        workspace_id=model.workspace_id,
        classification_policy_id=model.classification_policy_id,
        classification_policy_hash=model.classification_policy_hash,
        subject_id=model.subject_id,
        scope=scope,
        scope_id=model.scope_id,
        purpose=model.purpose,
        valid_from=model.valid_from,
        expires_at=model.expires_at,
        payload_hash=model.payload_hash,
        requester_id=model.requester_id,
        request_reason=model.request_reason,
        request_policy_decision_id=model.request_policy_decision_id,
        state=state,
        checker_id=model.checker_id,
        decision_reason=model.decision_reason,
        decision_policy_decision_id=model.decision_policy_decision_id,
        decided_at=model.decided_at,
        revoked_by=model.revoked_by,
        revocation_reason=model.revocation_reason,
        revocation_policy_decision_id=model.revocation_policy_decision_id,
        revoked_at=model.revoked_at,
        version=model.version,
    )


def _grant_event_model(grant: RestrictedSearchGrant) -> RestrictedSearchGrantEventModel:
    if grant.version == 1:
        action = "PROPOSED"
        actor_id = grant.requester_id
        reason = grant.request_reason
        policy_decision_id = grant.request_policy_decision_id
    elif grant.version == 2:
        if grant.checker_id is None or grant.decision_reason is None:
            raise ConflictError("The RESTRICTED Search grant decision evidence is incomplete.")
        action = "APPROVED" if grant.state is RestrictedSearchGrantState.ACTIVE else "REJECTED"
        actor_id = grant.checker_id
        reason = grant.decision_reason
        policy_decision_id = cast(UUID, grant.decision_policy_decision_id)
    elif grant.version == 3:
        if grant.revoked_by is None or grant.revocation_reason is None:
            raise ConflictError("The RESTRICTED Search grant revocation evidence is incomplete.")
        action = "REVOKED"
        actor_id = grant.revoked_by
        reason = grant.revocation_reason
        policy_decision_id = cast(UUID, grant.revocation_policy_decision_id)
    else:
        raise ConflictError("The RESTRICTED Search grant version is invalid.")
    occurred_at = (
        grant.events[-1].occurred_at
        if grant.events
        else (grant.revoked_at or grant.decided_at or grant.valid_from)
    )
    return RestrictedSearchGrantEventModel(
        id=uuid7(),
        workspace_id=grant.workspace_id,
        grant_id=grant.grant_id,
        action=action,
        actor_id=actor_id,
        reason=reason,
        policy_decision_id=policy_decision_id,
        occurred_at=occurred_at,
        grant_version=grant.version,
        payload_hash=grant.payload_hash,
    )
