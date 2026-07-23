from __future__ import annotations

import base64
import binascii
import json
import re
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.services.inference_admin import InferenceProviderProfilePage
from datariver.domain.authz import Classification
from datariver.domain.common import ConflictError, ValidationError, utc_now
from datariver.domain.inference_provider import (
    InferenceProviderProfile,
    InferenceProviderProfileState,
    InferenceProviderProfileVersion,
    ProviderAttestation,
    ProviderKind,
)
from datariver.infrastructure.db.models.inference import InferenceProviderProfileVersionModel

_PROFILE_KEY_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?")
_PROFILE_LIST_CURSOR_KEYS = frozenset(
    {"v", "scope", "workspace_id", "filters", "profile_key", "profile_version", "id"}
)


def _profile_cursor_filters(
    *,
    profile_key: str | None,
    state: InferenceProviderProfileState | None,
) -> dict[str, str | None]:
    return {
        "profile_key": profile_key,
        "state": state.value if state is not None else None,
    }


def _encode_profile_cursor(
    *,
    workspace_id: UUID,
    filters: dict[str, str | None],
    profile_key: str,
    profile_version: int,
    profile_version_id: UUID,
) -> str:
    payload = json.dumps(
        {
            "v": 1,
            "scope": "inference-provider-profile-history",
            "workspace_id": str(workspace_id),
            "filters": filters,
            "profile_key": profile_key,
            "profile_version": profile_version,
            "id": str(profile_version_id),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_profile_cursor(
    cursor: str,
    *,
    workspace_id: UUID,
    filters: dict[str, str | None],
) -> tuple[str, int, UUID]:
    try:
        if not cursor or len(cursor) > 2_000:
            raise ValueError
        payload = base64.b64decode(
            cursor + "=" * (-len(cursor) % 4),
            altchars=b"-_",
            validate=True,
        )
        document = json.loads(payload)
        if (
            not isinstance(document, dict)
            or frozenset(document) != _PROFILE_LIST_CURSOR_KEYS
            or document.get("v") != 1
            or document.get("scope") != "inference-provider-profile-history"
            or document.get("workspace_id") != str(workspace_id)
            or document.get("filters") != filters
            or not isinstance(document.get("profile_key"), str)
            or not isinstance(document.get("profile_version"), int)
        ):
            raise ValueError
        boundary_key = str(document["profile_key"])
        boundary_version = int(document["profile_version"])
        boundary_id = UUID(str(document["id"]))
        _validate_profile_key(boundary_key)
        if boundary_version < 1 or cursor != _encode_profile_cursor(
            workspace_id=workspace_id,
            filters=filters,
            profile_key=boundary_key,
            profile_version=boundary_version,
            profile_version_id=boundary_id,
        ):
            raise ValueError
        return boundary_key, boundary_version, boundary_id
    except (
        ValueError,
        TypeError,
        KeyError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        binascii.Error,
        ValidationError,
    ) as error:
        raise ValidationError(
            "The provider profile cursor is stale or does not match this request."
        ) from error


class SqlInferenceProviderProfileRepository:
    """Workspace-scoped provider profile persistence; transaction ownership stays external."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, *, workspace_id: UUID, profile_version_id: UUID
    ) -> InferenceProviderProfileVersion | None:
        model = (
            await self._session.scalars(
                select(InferenceProviderProfileVersionModel).where(
                    InferenceProviderProfileVersionModel.workspace_id == workspace_id,
                    InferenceProviderProfileVersionModel.id == profile_version_id,
                )
            )
        ).one_or_none()
        return _hydrate_profile(model)

    async def list(
        self,
        *,
        workspace_id: UUID,
        profile_key: str | None = None,
        state: InferenceProviderProfileState | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> InferenceProviderProfilePage:
        if not 1 <= limit <= 100:
            raise ValidationError("The provider profile list limit is invalid.")
        filters = _profile_cursor_filters(profile_key=profile_key, state=state)
        statement = (
            select(InferenceProviderProfileVersionModel)
            .where(InferenceProviderProfileVersionModel.workspace_id == workspace_id)
            .order_by(
                InferenceProviderProfileVersionModel.profile_key,
                InferenceProviderProfileVersionModel.profile_version.desc(),
                InferenceProviderProfileVersionModel.id,
            )
            .limit(limit + 1)
        )
        if profile_key is not None:
            _validate_profile_key(profile_key)
            statement = statement.where(
                InferenceProviderProfileVersionModel.profile_key == profile_key
            )
        if state is not None:
            if not isinstance(state, InferenceProviderProfileState):
                raise ValidationError("The provider profile state filter is invalid.")
            statement = statement.where(InferenceProviderProfileVersionModel.state == state.value)
        if cursor is not None:
            boundary_key, boundary_version, boundary_id = _decode_profile_cursor(
                cursor,
                workspace_id=workspace_id,
                filters=filters,
            )
            statement = statement.where(
                or_(
                    InferenceProviderProfileVersionModel.profile_key > boundary_key,
                    and_(
                        InferenceProviderProfileVersionModel.profile_key == boundary_key,
                        or_(
                            InferenceProviderProfileVersionModel.profile_version < boundary_version,
                            and_(
                                InferenceProviderProfileVersionModel.profile_version
                                == boundary_version,
                                InferenceProviderProfileVersionModel.id > boundary_id,
                            ),
                        ),
                    ),
                )
            )
        models = (await self._session.scalars(statement)).all()
        visible = models[:limit]
        return InferenceProviderProfilePage(
            items=tuple(_required_profile(model) for model in visible),
            next_cursor=(
                _encode_profile_cursor(
                    workspace_id=workspace_id,
                    filters=filters,
                    profile_key=visible[-1].profile_key,
                    profile_version=visible[-1].profile_version,
                    profile_version_id=visible[-1].id,
                )
                if len(models) > limit
                else None
            ),
        )

    async def get_approved_exact(
        self,
        *,
        workspace_id: UUID,
        profile_version_id: UUID,
        now: datetime,
    ) -> InferenceProviderProfileVersion | None:
        _require_aware_datetime(now, "provider profile resolution")
        model = (
            await self._session.scalars(
                select(InferenceProviderProfileVersionModel).where(
                    InferenceProviderProfileVersionModel.workspace_id == workspace_id,
                    InferenceProviderProfileVersionModel.id == profile_version_id,
                    InferenceProviderProfileVersionModel.state
                    == InferenceProviderProfileState.APPROVED.value,
                    InferenceProviderProfileVersionModel.residency_attestation_observed_at <= now,
                    InferenceProviderProfileVersionModel.residency_attestation_expires_at > now,
                    InferenceProviderProfileVersionModel.zero_retention_attestation_observed_at
                    <= now,
                    InferenceProviderProfileVersionModel.zero_retention_attestation_expires_at
                    > now,
                )
            )
        ).one_or_none()
        profile = _hydrate_profile(model)
        if profile is None:
            return None
        if (
            profile.state is not InferenceProviderProfileState.APPROVED
            or not profile.profile.attestations_current(now=now)
        ):
            return None
        return profile

    async def next_profile_version(self, *, workspace_id: UUID, profile_key: str) -> int:
        _validate_profile_key(profile_key)
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"datariver:integration:inference-provider:{workspace_id}"},
        )
        maximum = await self._session.scalar(
            select(func.max(InferenceProviderProfileVersionModel.profile_version)).where(
                InferenceProviderProfileVersionModel.workspace_id == workspace_id,
                InferenceProviderProfileVersionModel.profile_key == profile_key,
            )
        )
        return int(maximum or 0) + 1

    async def add(self, profile: InferenceProviderProfileVersion) -> None:
        if not _is_pristine_proposal(profile):
            raise ValidationError("Only a pristine provider profile proposal can be added.")
        profile.assert_integrity()
        self._session.add(_profile_model(profile))

    async def approve(self, profile: InferenceProviderProfileVersion) -> None:
        _validate_decision(profile, expected_state=InferenceProviderProfileState.APPROVED)
        await self._save_decision(profile)

    async def reject(self, profile: InferenceProviderProfileVersion) -> None:
        _validate_decision(profile, expected_state=InferenceProviderProfileState.REJECTED)
        await self._save_decision(profile)

    async def revoke(self, profile: InferenceProviderProfileVersion) -> None:
        if not _is_complete_revocation(profile):
            raise ValidationError("The provider profile revocation evidence is incomplete.")
        result = await self._session.execute(
            update(InferenceProviderProfileVersionModel)
            .where(
                InferenceProviderProfileVersionModel.workspace_id == profile.workspace_id,
                InferenceProviderProfileVersionModel.id == profile.provider_profile_version_id,
                InferenceProviderProfileVersionModel.payload_hash == profile.payload_hash,
                InferenceProviderProfileVersionModel.state
                == InferenceProviderProfileState.APPROVED.value,
                InferenceProviderProfileVersionModel.version == profile.version - 1,
            )
            .values(
                state=InferenceProviderProfileState.REVOKED.value,
                revoked_by=profile.revoked_by,
                revocation_reason=profile.revocation_reason,
                revocation_policy_decision_id=profile.revocation_policy_decision_id,
                revoked_at=profile.revoked_at,
                version=profile.version,
                updated_at=utc_now(),
            )
        )
        _require_single_update(result, "The provider profile revocation conflicted.")

    async def _save_decision(self, profile: InferenceProviderProfileVersion) -> None:
        result = await self._session.execute(
            update(InferenceProviderProfileVersionModel)
            .where(
                InferenceProviderProfileVersionModel.workspace_id == profile.workspace_id,
                InferenceProviderProfileVersionModel.id == profile.provider_profile_version_id,
                InferenceProviderProfileVersionModel.payload_hash == profile.payload_hash,
                InferenceProviderProfileVersionModel.state
                == InferenceProviderProfileState.PROPOSED.value,
                InferenceProviderProfileVersionModel.version == profile.version - 1,
            )
            .values(
                state=profile.state.value,
                checker_id=profile.checker_id,
                decision_reason=profile.decision_reason,
                decision_policy_decision_id=profile.decision_policy_decision_id,
                decided_at=profile.decided_at,
                version=profile.version,
                updated_at=utc_now(),
            )
        )
        _require_single_update(result, "The provider profile decision conflicted.")


def _profile_model(
    profile: InferenceProviderProfileVersion,
) -> InferenceProviderProfileVersionModel:
    value = profile.profile
    return InferenceProviderProfileVersionModel(
        id=profile.provider_profile_version_id,
        workspace_id=profile.workspace_id,
        profile_key=value.profile_key,
        profile_version=profile.profile_version,
        server_route_key=value.server_route_key,
        kind=value.kind.value,
        provider_identity=value.provider_identity,
        model_identity=value.model_identity,
        deployment_identity=value.deployment_identity,
        jurisdiction=value.jurisdiction,
        region=value.region,
        maximum_classification=int(value.maximum_classification),
        residency_attestation_fingerprint=value.residency_attestation.fingerprint,
        residency_attestation_observed_at=value.residency_attestation.observed_at,
        residency_attestation_expires_at=value.residency_attestation.expires_at,
        zero_retention_attestation_fingerprint=value.zero_retention_attestation.fingerprint,
        zero_retention_attestation_observed_at=value.zero_retention_attestation.observed_at,
        zero_retention_attestation_expires_at=value.zero_retention_attestation.expires_at,
        payload_hash=profile.payload_hash,
        maker_id=profile.maker_id,
        proposal_reason=profile.proposal_reason,
        proposal_policy_decision_id=profile.proposal_policy_decision_id,
        proposed_at=profile.proposed_at,
        state=profile.state.value,
        checker_id=profile.checker_id,
        decision_reason=profile.decision_reason,
        decision_policy_decision_id=profile.decision_policy_decision_id,
        decided_at=profile.decided_at,
        revoked_by=profile.revoked_by,
        revocation_reason=profile.revocation_reason,
        revocation_policy_decision_id=profile.revocation_policy_decision_id,
        revoked_at=profile.revoked_at,
        version=profile.version,
    )


def _hydrate_profile(
    model: InferenceProviderProfileVersionModel | None,
) -> InferenceProviderProfileVersion | None:
    if model is None:
        return None
    return _required_profile(model)


def _required_profile(
    model: InferenceProviderProfileVersionModel,
) -> InferenceProviderProfileVersion:
    try:
        profile = InferenceProviderProfile(
            profile_key=model.profile_key,
            server_route_key=model.server_route_key,
            kind=ProviderKind(model.kind),
            provider_identity=model.provider_identity,
            model_identity=model.model_identity,
            deployment_identity=model.deployment_identity,
            jurisdiction=model.jurisdiction,
            region=model.region,
            maximum_classification=Classification(model.maximum_classification),
            residency_attestation=ProviderAttestation(
                fingerprint=model.residency_attestation_fingerprint,
                observed_at=model.residency_attestation_observed_at,
                expires_at=model.residency_attestation_expires_at,
            ),
            zero_retention_attestation=ProviderAttestation(
                fingerprint=model.zero_retention_attestation_fingerprint,
                observed_at=model.zero_retention_attestation_observed_at,
                expires_at=model.zero_retention_attestation_expires_at,
            ),
        )
        state = InferenceProviderProfileState(model.state)
        aggregate = InferenceProviderProfileVersion(
            provider_profile_version_id=model.id,
            workspace_id=model.workspace_id,
            profile_version=model.profile_version,
            profile=profile,
            payload_hash=model.payload_hash,
            maker_id=model.maker_id,
            proposal_reason=model.proposal_reason,
            proposal_policy_decision_id=model.proposal_policy_decision_id,
            proposed_at=model.proposed_at,
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
    except (TypeError, ValueError, ValidationError) as error:
        raise ConflictError("The stored provider profile is invalid.") from error
    if not aggregate.integrity_valid():
        raise ConflictError("The stored provider profile payload failed its integrity check.")
    if not _stored_state_shape_valid(aggregate):
        raise ConflictError("The stored provider profile approval state is invalid.")
    return aggregate


def _is_pristine_proposal(profile: InferenceProviderProfileVersion) -> bool:
    return (
        profile.state is InferenceProviderProfileState.PROPOSED
        and profile.version == 1
        and profile.checker_id is None
        and profile.decision_reason is None
        and profile.decision_policy_decision_id is None
        and profile.decided_at is None
        and profile.revoked_by is None
        and profile.revocation_reason is None
        and profile.revocation_policy_decision_id is None
        and profile.revoked_at is None
    )


def _validate_decision(
    profile: InferenceProviderProfileVersion,
    *,
    expected_state: InferenceProviderProfileState,
) -> None:
    if profile.state is not expected_state or not _is_complete_decision(profile):
        raise ValidationError("The provider profile decision evidence is incomplete.")
    profile.assert_integrity()
    if expected_state is InferenceProviderProfileState.APPROVED:
        if profile.decided_at is None or not profile.profile.attestations_current(
            now=profile.decided_at
        ):
            raise ValidationError("Approved provider attestations must be current.")


def _is_complete_decision(profile: InferenceProviderProfileVersion) -> bool:
    return (
        profile.state
        in {
            InferenceProviderProfileState.APPROVED,
            InferenceProviderProfileState.REJECTED,
        }
        and profile.version == 2
        and profile.checker_id is not None
        and profile.checker_id != profile.maker_id
        and profile.decision_reason is not None
        and profile.decision_policy_decision_id is not None
        and profile.decided_at is not None
        and profile.revoked_by is None
        and profile.revocation_reason is None
        and profile.revocation_policy_decision_id is None
        and profile.revoked_at is None
    )


def _is_complete_revocation(profile: InferenceProviderProfileVersion) -> bool:
    return (
        profile.state is InferenceProviderProfileState.REVOKED
        and profile.version == 3
        and profile.checker_id is not None
        and profile.checker_id != profile.maker_id
        and profile.decision_reason is not None
        and profile.decision_policy_decision_id is not None
        and profile.decided_at is not None
        and profile.revoked_by is not None
        and profile.revocation_reason is not None
        and profile.revocation_policy_decision_id is not None
        and profile.revoked_at is not None
    )


def _stored_state_shape_valid(profile: InferenceProviderProfileVersion) -> bool:
    if profile.state is InferenceProviderProfileState.PROPOSED:
        return _is_pristine_proposal(profile)
    if profile.state in {
        InferenceProviderProfileState.APPROVED,
        InferenceProviderProfileState.REJECTED,
    }:
        return _is_complete_decision(profile)
    return _is_complete_revocation(profile)


def _require_single_update(result: object, message: str) -> None:
    if getattr(result, "rowcount", None) != 1:
        raise ConflictError(message)


def _validate_profile_key(profile_key: str) -> None:
    if not isinstance(profile_key, str) or not _PROFILE_KEY_PATTERN.fullmatch(profile_key):
        raise ValidationError("The provider profile key is invalid.")


def _require_aware_datetime(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError(f"The {name} timestamp must include a timezone.")
