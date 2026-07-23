from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from types import TracebackType
from typing import cast
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.application.dto import (
    ArchiveCapabilityEvidence,
    ArchiveCapabilityRecord,
    ArchiveReceiptEvidence,
    RetentionArchiveReceiptEvidenceSummary,
    RetentionExecutionAttemptEvidence,
    RetentionExecutionEventEvidence,
    RetentionExecutionEvidence,
)
from datariver.application.ports import (
    ErasureRequestPage,
    ErasureRequestRepository,
    ErasureTargetReader,
    LegalHoldPage,
    LegalHoldRepository,
    RetentionPolicyPage,
    RetentionPolicyRepository,
    RetentionUnitOfWork,
)
from datariver.domain.authz import Classification
from datariver.domain.common import (
    ConflictError,
    ForbiddenError,
    ValidationError,
    canonical_json_hash,
    utc_now,
    uuid7,
)
from datariver.domain.retention import (
    ArchiveCapability,
    ArchiveRetentionMode,
    ArchiveSource,
    ErasureApproval,
    ErasureRequest,
    ErasureRequestState,
    ErasureTargetSnapshot,
    ErasureTargetType,
    GovernanceDecision,
    ImmutableArchiveReceipt,
    LegalHold,
    LegalHoldAction,
    LegalHoldActionType,
    LegalHoldScope,
    LegalHoldState,
    RetentionArchiveDisposition,
    RetentionClassRule,
    RetentionDataClass,
    RetentionPeriodUnit,
    RetentionPolicyContract,
    RetentionPolicyState,
    RetentionPolicyVersion,
    RetentionRules,
)
from datariver.infrastructure.db.governance import SqlIdempotencyStore, SqlOutboxWriter
from datariver.infrastructure.db.models.assistant import ChatSessionModel
from datariver.infrastructure.db.models.integration import ObjectManifestModel
from datariver.infrastructure.db.models.platform import SubjectModel, WorkspaceMembershipModel
from datariver.infrastructure.db.models.retention import (
    ArchiveCapabilityAttestationModel,
    ErasureRequestEventModel,
    ErasureRequestModel,
    ImmutableArchiveReceiptModel,
    LegalHoldEventModel,
    LegalHoldModel,
    RetentionExecutionAttemptModel,
    RetentionExecutionEventModel,
    RetentionExecutionJobModel,
    RetentionPolicyClassRuleModel,
    RetentionPolicyVersionModel,
)
from datariver.infrastructure.db.rls import set_security_context

MAXIMUM_ARCHIVE_CAPABILITY_LIFETIME = timedelta(hours=24)
_RETENTION_LIST_CURSOR_KEYS = frozenset({"v", "scope", "workspace_id", "state", "boundary"})
_RETENTION_LIST_CURSOR_MAX_LENGTH = 2_000


def _validate_retention_list_limit(limit: int) -> None:
    if limit < 1 or limit > 100:
        raise ValidationError("A retention list page must contain between 1 and 100 items.")


def _encode_retention_list_cursor(
    *,
    scope: str,
    workspace_id: UUID,
    state: str | None,
    boundary: Mapping[str, str | int],
) -> str:
    payload = json.dumps(
        {
            "v": 1,
            "scope": scope,
            "workspace_id": str(workspace_id),
            "state": state,
            "boundary": dict(boundary),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_retention_list_cursor(
    cursor: str,
    *,
    scope: str,
    workspace_id: UUID,
    state: str | None,
) -> Mapping[str, str | int]:
    try:
        if not cursor or len(cursor) > _RETENTION_LIST_CURSOR_MAX_LENGTH:
            raise ValueError
        payload = base64.b64decode(
            cursor + "=" * (-len(cursor) % 4),
            altchars=b"-_",
            validate=True,
        )
        document = json.loads(payload)
        if (
            not isinstance(document, dict)
            or frozenset(document) != _RETENTION_LIST_CURSOR_KEYS
            or document.get("v") != 1
            or document.get("scope") != scope
            or document.get("workspace_id") != str(workspace_id)
            or document.get("state") != state
            or not isinstance(document.get("boundary"), dict)
        ):
            raise ValueError
        boundary = cast(dict[str, str | int], document["boundary"])
        if cursor != _encode_retention_list_cursor(
            scope=scope,
            workspace_id=workspace_id,
            state=state,
            boundary=boundary,
        ):
            raise ValueError
        return boundary
    except (
        ValueError,
        TypeError,
        KeyError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        binascii.Error,
    ) as error:
        raise ValidationError(
            "The retention list cursor is stale or does not match this request."
        ) from error


def _policy_cursor_boundary(
    cursor: str,
    *,
    workspace_id: UUID,
    state: str | None,
) -> int:
    boundary = _decode_retention_list_cursor(
        cursor,
        scope="retention-policies",
        workspace_id=workspace_id,
        state=state,
    )
    if frozenset(boundary) != {"policy_number"}:
        raise ValidationError("The retention list cursor has an invalid boundary.")
    policy_number = boundary.get("policy_number")
    if not isinstance(policy_number, int) or isinstance(policy_number, bool) or policy_number < 1:
        raise ValidationError("The retention list cursor has an invalid boundary.")
    return policy_number


def _temporal_cursor_boundary(
    cursor: str,
    *,
    scope: str,
    workspace_id: UUID,
    state: str | None,
) -> tuple[datetime, UUID]:
    boundary = _decode_retention_list_cursor(
        cursor,
        scope=scope,
        workspace_id=workspace_id,
        state=state,
    )
    try:
        if frozenset(boundary) != {"created_at", "id"}:
            raise ValueError
        created_at = datetime.fromisoformat(str(boundary["created_at"]))
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError
        boundary_id = UUID(str(boundary["id"]))
    except (ValueError, TypeError, KeyError) as error:
        raise ValidationError("The retention list cursor has an invalid boundary.") from error
    return created_at, boundary_id


class SqlRetentionPolicyRepository(RetentionPolicyRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, policy: RetentionPolicyVersion) -> None:
        self._session.add(_policy_model(policy))
        self._session.add_all(_policy_class_rule_models(policy))

    async def get(self, *, workspace_id: UUID, policy_id: UUID) -> RetentionPolicyVersion | None:
        model = (
            await self._session.scalars(
                select(RetentionPolicyVersionModel).where(
                    RetentionPolicyVersionModel.workspace_id == workspace_id,
                    RetentionPolicyVersionModel.id == policy_id,
                )
            )
        ).one_or_none()
        return await self._hydrate(model)

    async def get_for_update(
        self, *, workspace_id: UUID, policy_id: UUID
    ) -> RetentionPolicyVersion | None:
        model = (
            await self._session.scalars(
                select(RetentionPolicyVersionModel)
                .where(
                    RetentionPolicyVersionModel.workspace_id == workspace_id,
                    RetentionPolicyVersionModel.id == policy_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        return await self._hydrate(model)

    async def get_active(self, *, workspace_id: UUID) -> RetentionPolicyVersion | None:
        model = (
            await self._session.scalars(
                select(RetentionPolicyVersionModel).where(
                    RetentionPolicyVersionModel.workspace_id == workspace_id,
                    RetentionPolicyVersionModel.state == RetentionPolicyState.ACTIVE.value,
                )
            )
        ).one_or_none()
        return await self._hydrate(model)

    async def get_active_for_update(
        self, *, workspace_id: UUID, excluding_policy_id: UUID | None = None
    ) -> RetentionPolicyVersion | None:
        statement = (
            select(RetentionPolicyVersionModel)
            .where(
                RetentionPolicyVersionModel.workspace_id == workspace_id,
                RetentionPolicyVersionModel.state == RetentionPolicyState.ACTIVE.value,
            )
            .with_for_update()
        )
        if excluding_policy_id is not None:
            statement = statement.where(RetentionPolicyVersionModel.id != excluding_policy_id)
        model = (await self._session.scalars(statement)).one_or_none()
        return await self._hydrate(model)

    async def list(
        self,
        *,
        workspace_id: UUID,
        state: str | None,
        limit: int,
        cursor: str | None = None,
    ) -> RetentionPolicyPage:
        _validate_retention_list_limit(limit)
        statement = (
            select(RetentionPolicyVersionModel)
            .where(RetentionPolicyVersionModel.workspace_id == workspace_id)
            .order_by(RetentionPolicyVersionModel.policy_number.desc())
            .limit(limit + 1)
        )
        if state is not None:
            statement = statement.where(RetentionPolicyVersionModel.state == state)
        if cursor is not None:
            statement = statement.where(
                RetentionPolicyVersionModel.policy_number
                < _policy_cursor_boundary(
                    cursor,
                    workspace_id=workspace_id,
                    state=state,
                )
            )
        fetched = tuple(await self._session.scalars(statement))
        has_more = len(fetched) > limit
        models = fetched[:limit]
        if not models:
            return RetentionPolicyPage(items=(), next_cursor=None)
        rules = tuple(
            await self._session.scalars(
                select(RetentionPolicyClassRuleModel).where(
                    RetentionPolicyClassRuleModel.workspace_id == workspace_id,
                    RetentionPolicyClassRuleModel.policy_id.in_(model.id for model in models),
                )
            )
        )
        by_policy: dict[UUID, list[RetentionPolicyClassRuleModel]] = {}
        for rule in rules:
            by_policy.setdefault(rule.policy_id, []).append(rule)
        items = tuple(
            _required_policy(model, tuple(by_policy.get(model.id, ()))) for model in models
        )
        return RetentionPolicyPage(
            items=items,
            next_cursor=(
                _encode_retention_list_cursor(
                    scope="retention-policies",
                    workspace_id=workspace_id,
                    state=state,
                    boundary={"policy_number": models[-1].policy_number},
                )
                if has_more
                else None
            ),
        )

    async def next_policy_number(self, *, workspace_id: UUID) -> int:
        maximum = await self._session.scalar(
            select(func.max(RetentionPolicyVersionModel.policy_number)).where(
                RetentionPolicyVersionModel.workspace_id == workspace_id
            )
        )
        return int(maximum or 0) + 1

    async def save(self, policy: RetentionPolicyVersion) -> None:
        result = await self._session.execute(
            update(RetentionPolicyVersionModel)
            .where(
                RetentionPolicyVersionModel.workspace_id == policy.workspace_id,
                RetentionPolicyVersionModel.id == policy.policy_id,
                RetentionPolicyVersionModel.version == policy.version - 1,
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
                updated_at=utc_now(),
            )
        )
        if getattr(result, "rowcount", None) != 1:
            raise ConflictError("The retention policy was modified by another operation.")

    async def _hydrate(
        self, model: RetentionPolicyVersionModel | None
    ) -> RetentionPolicyVersion | None:
        if model is None:
            return None
        rules = tuple(
            await self._session.scalars(
                select(RetentionPolicyClassRuleModel)
                .where(
                    RetentionPolicyClassRuleModel.workspace_id == model.workspace_id,
                    RetentionPolicyClassRuleModel.policy_id == model.id,
                )
                .order_by(RetentionPolicyClassRuleModel.data_class)
            )
        )
        return _required_policy(model, rules)


class SqlLegalHoldRepository(LegalHoldRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, hold: LegalHold) -> None:
        self._session.add(_hold_model(hold))
        self._session.add_all(_hold_event_model(hold, action) for action in hold.actions)

    async def get(self, *, workspace_id: UUID, hold_id: UUID) -> LegalHold | None:
        model = (
            await self._session.scalars(
                select(LegalHoldModel).where(
                    LegalHoldModel.workspace_id == workspace_id,
                    LegalHoldModel.id == hold_id,
                )
            )
        ).one_or_none()
        return await self._hydrate(model)

    async def get_for_update(self, *, workspace_id: UUID, hold_id: UUID) -> LegalHold | None:
        model = (
            await self._session.scalars(
                select(LegalHoldModel)
                .where(
                    LegalHoldModel.workspace_id == workspace_id,
                    LegalHoldModel.id == hold_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        return await self._hydrate(model)

    async def list(
        self,
        *,
        workspace_id: UUID,
        state: str | None,
        limit: int,
        cursor: str | None = None,
    ) -> LegalHoldPage:
        _validate_retention_list_limit(limit)
        statement = (
            select(LegalHoldModel)
            .where(LegalHoldModel.workspace_id == workspace_id)
            .order_by(LegalHoldModel.created_at.desc(), LegalHoldModel.id)
            .limit(limit + 1)
        )
        if state is not None:
            statement = statement.where(LegalHoldModel.state == state)
        if cursor is not None:
            boundary_at, boundary_id = _temporal_cursor_boundary(
                cursor,
                scope="legal-holds",
                workspace_id=workspace_id,
                state=state,
            )
            statement = statement.where(
                or_(
                    LegalHoldModel.created_at < boundary_at,
                    and_(
                        LegalHoldModel.created_at == boundary_at,
                        LegalHoldModel.id > boundary_id,
                    ),
                )
            )
        fetched = tuple(await self._session.scalars(statement))
        has_more = len(fetched) > limit
        models = fetched[:limit]
        values = [_hydrate_hold(model, (), history_summary=True) for model in models]
        return LegalHoldPage(
            items=tuple(values),
            next_cursor=(
                _encode_retention_list_cursor(
                    scope="legal-holds",
                    workspace_id=workspace_id,
                    state=state,
                    boundary={
                        "created_at": models[-1].created_at.isoformat(),
                        "id": str(models[-1].id),
                    },
                )
                if has_more
                else None
            ),
        )

    async def save(self, hold: LegalHold) -> None:
        result = await self._session.execute(
            update(LegalHoldModel)
            .where(
                LegalHoldModel.workspace_id == hold.workspace_id,
                LegalHoldModel.id == hold.hold_id,
                LegalHoldModel.version == hold.version - 1,
            )
            .values(
                state=hold.state.value,
                release_requested_by=hold.release_requested_by,
                release_request_reason=hold.release_request_reason,
                release_request_policy_decision_id=hold.release_request_policy_decision_id,
                release_checker_id=hold.release_checker_id,
                release_decision_reason=hold.release_decision_reason,
                release_decision_policy_decision_id=hold.release_decision_policy_decision_id,
                released_at=hold.released_at,
                version=hold.version,
                updated_at=utc_now(),
            )
        )
        if getattr(result, "rowcount", None) != 1:
            raise ConflictError("The Legal Hold was modified by another operation.")
        matching = tuple(action for action in hold.actions if action.hold_version == hold.version)
        if len(matching) != 1:
            raise ConflictError("The Legal Hold mutation has no unique append-only action.")
        self._session.add(_hold_event_model(hold, matching[0]))

    async def has_active_for_erasure_target(
        self,
        *,
        workspace_id: UUID,
        target_type: ErasureTargetType,
        target_id: UUID,
        target_owner_id: UUID | None,
    ) -> bool:
        subject_scope_ids = {target_id}
        if target_owner_id is not None:
            subject_scope_ids.add(target_owner_id)
        scope_predicate = or_(
            LegalHoldModel.scope == LegalHoldScope.WORKSPACE.value,
            and_(
                LegalHoldModel.scope == LegalHoldScope.RESOURCE.value,
                LegalHoldModel.scope_id == target_id,
            ),
            and_(
                LegalHoldModel.scope == LegalHoldScope.SUBJECT.value,
                LegalHoldModel.scope_id.in_(subject_scope_ids),
            ),
        )
        statement = select(LegalHoldModel.id).where(
            LegalHoldModel.workspace_id == workspace_id,
            LegalHoldModel.state != LegalHoldState.RELEASED.value,
            scope_predicate,
        )
        target_data_class = {
            ErasureTargetType.CHAT_SESSION: RetentionDataClass.CHAT_CONTENT,
            ErasureTargetType.UPLOAD_OBJECT: RetentionDataClass.OBJECT_DATA,
        }.get(target_type)
        if target_data_class is not None:
            statement = statement.where(LegalHoldModel.data_class == target_data_class.value)
        return await self._session.scalar(statement.limit(1)) is not None

    async def _hydrate(self, model: LegalHoldModel | None) -> LegalHold | None:
        if model is None:
            return None
        fetched = tuple(
            await self._session.scalars(
                select(LegalHoldEventModel)
                .where(
                    LegalHoldEventModel.workspace_id == model.workspace_id,
                    LegalHoldEventModel.hold_id == model.id,
                )
                .order_by(LegalHoldEventModel.hold_version.desc())
                .limit(101)
            )
        )
        events = tuple(reversed(fetched[:100]))
        return _hydrate_hold(
            model,
            events,
            history_truncated=len(fetched) > 100,
        )


class SqlErasureRequestRepository(ErasureRequestRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, request: ErasureRequest) -> None:
        self._session.add(_erasure_request_model(request))
        self._session.add(_erasure_created_event_model(request))

    async def get(self, *, workspace_id: UUID, erasure_request_id: UUID) -> ErasureRequest | None:
        model = (
            await self._session.scalars(
                select(ErasureRequestModel).where(
                    ErasureRequestModel.workspace_id == workspace_id,
                    ErasureRequestModel.id == erasure_request_id,
                )
            )
        ).one_or_none()
        return await self._hydrate(model)

    async def get_for_update(
        self, *, workspace_id: UUID, erasure_request_id: UUID
    ) -> ErasureRequest | None:
        model = (
            await self._session.scalars(
                select(ErasureRequestModel)
                .where(
                    ErasureRequestModel.workspace_id == workspace_id,
                    ErasureRequestModel.id == erasure_request_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        return await self._hydrate(model)

    async def list(
        self,
        *,
        workspace_id: UUID,
        state: str | None,
        limit: int,
        cursor: str | None = None,
    ) -> ErasureRequestPage:
        _validate_retention_list_limit(limit)
        statement = (
            select(ErasureRequestModel)
            .where(ErasureRequestModel.workspace_id == workspace_id)
            .order_by(ErasureRequestModel.created_at.desc(), ErasureRequestModel.id)
            .limit(limit + 1)
        )
        if state is not None:
            statement = statement.where(ErasureRequestModel.state == state)
        if cursor is not None:
            boundary_at, boundary_id = _temporal_cursor_boundary(
                cursor,
                scope="erasure-requests",
                workspace_id=workspace_id,
                state=state,
            )
            statement = statement.where(
                or_(
                    ErasureRequestModel.created_at < boundary_at,
                    and_(
                        ErasureRequestModel.created_at == boundary_at,
                        ErasureRequestModel.id > boundary_id,
                    ),
                )
            )
        fetched = tuple(await self._session.scalars(statement))
        has_more = len(fetched) > limit
        models = fetched[:limit]
        values = [_hydrate_erasure_request(model, (), history_summary=True) for model in models]
        return ErasureRequestPage(
            items=tuple(values),
            next_cursor=(
                _encode_retention_list_cursor(
                    scope="erasure-requests",
                    workspace_id=workspace_id,
                    state=state,
                    boundary={
                        "created_at": models[-1].created_at.isoformat(),
                        "id": str(models[-1].id),
                    },
                )
                if has_more
                else None
            ),
        )

    async def save(self, request: ErasureRequest) -> None:
        result = await self._session.execute(
            update(ErasureRequestModel)
            .where(
                ErasureRequestModel.workspace_id == request.workspace_id,
                ErasureRequestModel.id == request.erasure_request_id,
                ErasureRequestModel.version == request.version - 1,
            )
            .values(
                state=request.state.value,
                checker_id=request.checker_id,
                decision_reason=request.decision_reason,
                decision_policy_decision_id=request.decision_policy_decision_id,
                decided_at=request.decided_at,
                version=request.version,
                updated_at=utc_now(),
            )
        )
        if getattr(result, "rowcount", None) != 1:
            raise ConflictError("The erasure request was modified by another operation.")
        matching = tuple(
            approval
            for approval in request.approvals
            if approval.request_version == request.version
        )
        if len(matching) != 1:
            raise ConflictError("The erasure decision has no unique append-only approval event.")
        self._session.add(_erasure_approval_event_model(request, matching[0]))

    async def _hydrate(self, model: ErasureRequestModel | None) -> ErasureRequest | None:
        if model is None:
            return None
        events = tuple(
            await self._session.scalars(
                select(ErasureRequestEventModel)
                .where(
                    ErasureRequestEventModel.workspace_id == model.workspace_id,
                    ErasureRequestEventModel.erasure_request_id == model.id,
                )
                .order_by(ErasureRequestEventModel.request_version)
            )
        )
        return _hydrate_erasure_request(model, events)


class SqlErasureTargetReader(ErasureTargetReader):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_erasure_target_snapshot(
        self,
        *,
        workspace_id: UUID,
        target_type: ErasureTargetType,
        target_id: UUID,
    ) -> ErasureTargetSnapshot | None:
        if target_type is ErasureTargetType.SUBJECT_DATA:
            membership = (
                await self._session.scalars(
                    select(WorkspaceMembershipModel).where(
                        WorkspaceMembershipModel.workspace_id == workspace_id,
                        WorkspaceMembershipModel.subject_id == target_id,
                    )
                )
            ).one_or_none()
            if membership is None:
                return None
            return ErasureTargetSnapshot(
                target_type=target_type,
                target_id=target_id,
                version=membership.version,
                owner_id=target_id,
                classification=Classification.RESTRICTED,
                retention_basis_at=None,
                retention_until=None,
            )

        if target_type is ErasureTargetType.CHAT_SESSION:
            session = (
                await self._session.scalars(
                    select(ChatSessionModel).where(
                        ChatSessionModel.workspace_id == workspace_id,
                        ChatSessionModel.id == target_id,
                    )
                )
            ).one_or_none()
            if session is None:
                return None
            return ErasureTargetSnapshot(
                target_type=target_type,
                target_id=target_id,
                version=session.version,
                owner_id=session.owner_id,
                classification=Classification.RESTRICTED,
                retention_basis_at=session.retention_basis_at,
                retention_until=session.retention_until,
            )

        manifest = (
            await self._session.scalars(
                select(ObjectManifestModel).where(
                    ObjectManifestModel.workspace_id == workspace_id,
                    ObjectManifestModel.id == target_id,
                )
            )
        ).one_or_none()
        if manifest is None:
            return None
        return ErasureTargetSnapshot(
            target_type=target_type,
            target_id=target_id,
            version=manifest.version,
            owner_id=manifest.owner_id,
            classification=_classification_or_restricted(manifest.classification),
            retention_basis_at=manifest.created_at,
            retention_until=manifest.retention_until,
        )


class SqlArchiveEvidenceRepository:
    """Owner-only persistence for verified, append-only archive evidence.

    This repository is deliberately not exposed by the application unit of work. The normal
    application role has SELECT-only database privileges for these records; a future dedicated
    archive worker role may call these methods after its operational boundary is approved.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_capability(
        self,
        *,
        workspace_id: UUID,
        capability: ArchiveCapability,
        evidence: ArchiveCapabilityEvidence,
    ) -> UUID:
        now = utc_now()
        if capability.observed_at > now:
            raise ValidationError("Archive capability observations cannot be in the future.")
        if capability.expires_at - capability.observed_at > MAXIMUM_ARCHIVE_CAPABILITY_LIFETIME:
            raise ValidationError("Archive capability attestations cannot exceed 24 hours.")
        model = _archive_capability_model(
            workspace_id=workspace_id,
            capability=capability,
            evidence=evidence,
        )
        self._session.add(model)
        return model.id

    async def ensure_capability(
        self,
        *,
        workspace_id: UUID,
        capability: ArchiveCapability,
        evidence: ArchiveCapabilityEvidence,
    ) -> UUID:
        existing = (
            await self._session.scalars(
                select(ArchiveCapabilityAttestationModel).where(
                    ArchiveCapabilityAttestationModel.workspace_id == workspace_id,
                    ArchiveCapabilityAttestationModel.configuration_fingerprint
                    == capability.configuration_fingerprint,
                    ArchiveCapabilityAttestationModel.observed_at == capability.observed_at,
                )
            )
        ).one_or_none()
        if existing is None:
            return await self.add_capability(
                workspace_id=workspace_id,
                capability=capability,
                evidence=evidence,
            )
        stored_capability, stored_evidence = _required_archive_capability_parts(existing)
        if stored_capability != capability or stored_evidence != evidence:
            raise ConflictError(
                "An archive capability observation conflicts with its stored evidence."
            )
        return existing.id

    async def get_latest_capability(
        self, *, workspace_id: UUID, configuration_fingerprint: str
    ) -> ArchiveCapability | None:
        now = utc_now()
        model = (
            await self._session.scalars(
                select(ArchiveCapabilityAttestationModel)
                .where(
                    ArchiveCapabilityAttestationModel.workspace_id == workspace_id,
                    ArchiveCapabilityAttestationModel.configuration_fingerprint
                    == configuration_fingerprint,
                    ArchiveCapabilityAttestationModel.state == "VERIFIED",
                    ArchiveCapabilityAttestationModel.observed_at <= now,
                    ArchiveCapabilityAttestationModel.expires_at > now,
                )
                .order_by(ArchiveCapabilityAttestationModel.observed_at.desc())
                .limit(1)
            )
        ).one_or_none()
        return _hydrate_archive_capability(model)

    async def get_capability_for_write(
        self,
        *,
        workspace_id: UUID,
        attestation_id: UUID,
        configuration_fingerprint: str,
        encryption_profile_fingerprint: str,
        runtime_principal_fingerprint: str,
        object_bucket: str,
        written_at: datetime,
    ) -> ArchiveCapabilityRecord | None:
        write_interval_end = written_at + timedelta(seconds=1)
        model = (
            await self._session.scalars(
                select(ArchiveCapabilityAttestationModel)
                .where(
                    ArchiveCapabilityAttestationModel.workspace_id == workspace_id,
                    ArchiveCapabilityAttestationModel.id == attestation_id,
                    ArchiveCapabilityAttestationModel.configuration_fingerprint
                    == configuration_fingerprint,
                    ArchiveCapabilityAttestationModel.encryption_profile_fingerprint
                    == encryption_profile_fingerprint,
                    ArchiveCapabilityAttestationModel.runtime_principal_fingerprint
                    == runtime_principal_fingerprint,
                    ArchiveCapabilityAttestationModel.object_bucket == object_bucket,
                    ArchiveCapabilityAttestationModel.state == "VERIFIED",
                    ArchiveCapabilityAttestationModel.observed_at <= written_at,
                    ArchiveCapabilityAttestationModel.expires_at >= write_interval_end,
                )
                .order_by(ArchiveCapabilityAttestationModel.observed_at.desc())
                .limit(1)
            )
        ).one_or_none()
        return _hydrate_archive_capability_record(model)

    async def add_receipt(
        self,
        *,
        capability_attestation_id: UUID,
        receipt: ImmutableArchiveReceipt,
        evidence: ArchiveReceiptEvidence,
    ) -> None:
        if receipt.verified_at > utc_now():
            raise ValidationError("Archive receipt verification cannot be in the future.")
        if receipt.object_version_id.strip().lower() == "null":
            raise ValidationError("The archive object version cannot be the literal null value.")
        write_interval_end = evidence.written_at + timedelta(seconds=1)
        attestation = (
            await self._session.scalars(
                select(ArchiveCapabilityAttestationModel).where(
                    ArchiveCapabilityAttestationModel.workspace_id == receipt.workspace_id,
                    ArchiveCapabilityAttestationModel.id == capability_attestation_id,
                    ArchiveCapabilityAttestationModel.configuration_fingerprint
                    == receipt.capability_fingerprint,
                    ArchiveCapabilityAttestationModel.encryption_profile_fingerprint
                    == evidence.encryption_profile_fingerprint,
                    ArchiveCapabilityAttestationModel.runtime_principal_fingerprint
                    == evidence.worker_principal_fingerprint,
                    ArchiveCapabilityAttestationModel.object_bucket == receipt.object_bucket,
                    ArchiveCapabilityAttestationModel.state == "VERIFIED",
                    ArchiveCapabilityAttestationModel.observed_at <= evidence.written_at,
                    ArchiveCapabilityAttestationModel.expires_at >= write_interval_end,
                )
            )
        ).one_or_none()
        if attestation is None:
            raise ConflictError(
                "The exact archive capability does not match the receipt write evidence."
            )
        capability = _required_archive_capability(attestation)
        capability.assert_usable(now=evidence.written_at)
        if (
            capability.observed_at > evidence.written_at
            or capability.expires_at < write_interval_end
        ):
            raise ConflictError(
                "The exact archive capability does not cover the provider write-time interval."
            )

        policy = (
            await self._session.scalars(
                select(RetentionPolicyVersionModel).where(
                    RetentionPolicyVersionModel.workspace_id == receipt.workspace_id,
                    RetentionPolicyVersionModel.id == evidence.retention_policy_id,
                    RetentionPolicyVersionModel.payload_hash == evidence.retention_policy_hash,
                    RetentionPolicyVersionModel.state.in_(
                        (
                            RetentionPolicyState.ACTIVE.value,
                            RetentionPolicyState.SUPERSEDED.value,
                        )
                    ),
                    RetentionPolicyVersionModel.decided_at <= evidence.written_at,
                    or_(
                        RetentionPolicyVersionModel.superseded_at.is_(None),
                        RetentionPolicyVersionModel.superseded_at >= write_interval_end,
                    ),
                )
            )
        ).one_or_none()
        if policy is None:
            raise ConflictError(
                "The immutable archive receipt must bind the policy active at write time."
            )
        if (
            policy.decided_at is None
            or policy.decided_at > evidence.written_at
            or (policy.superseded_at is not None and policy.superseded_at < write_interval_end)
        ):
            raise ConflictError(
                "The immutable archive receipt policy was not active at write time."
            )
        if policy.contract_version == "POLICY_BOOK_V2" and (
            policy.effective_from is None
            or policy.effective_from > evidence.written_at
            or (policy.effective_until is not None and policy.effective_until < write_interval_end)
        ):
            raise ConflictError(
                "The immutable archive receipt policy was not effective for the provider "
                "write-time interval."
            )
        class_rules = tuple(
            await self._session.scalars(
                select(RetentionPolicyClassRuleModel).where(
                    RetentionPolicyClassRuleModel.workspace_id == receipt.workspace_id,
                    RetentionPolicyClassRuleModel.policy_id == policy.id,
                )
            )
        )
        active_policy = _required_policy(policy, class_rules)
        if active_policy.contract is None:
            minimum_retention_until = _advance_calendar_years(
                evidence.source_end, active_policy.rules.immutable_archive_years
            )
            if receipt.retention_until < minimum_retention_until:
                raise ConflictError(
                    "The archive retention deadline is shorter than the active policy."
                )
        else:
            audit_rule = active_policy.contract.rule_for(RetentionDataClass.AUDIT_EVIDENCE)
            if (
                audit_rule.archive_disposition is not RetentionArchiveDisposition.EVIDENCE_ONLY
                or receipt.retention_until != audit_rule.maximum_until(evidence.source_end)
            ):
                raise ConflictError(
                    "The archive retention deadline does not match the V2 audit policy."
                )

        self._session.add(
            _archive_receipt_model(
                receipt=receipt,
                evidence=evidence,
                capability_attestation_id=attestation.id,
            )
        )

    async def get_receipt(
        self, *, workspace_id: UUID, receipt_id: UUID
    ) -> ImmutableArchiveReceipt | None:
        model = (
            await self._session.scalars(
                select(ImmutableArchiveReceiptModel).where(
                    ImmutableArchiveReceiptModel.workspace_id == workspace_id,
                    ImmutableArchiveReceiptModel.id == receipt_id,
                )
            )
        ).one_or_none()
        return _hydrate_archive_receipt(model)


class SqlRetentionExecutionEvidenceReader:
    """SELECT-only, sanitized projection for the Admin archive-evidence surface."""

    _ATTEMPT_LIMIT = 20
    _EVENT_LIMIT = 100

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def assert_admin_reader_eligible(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
    ) -> None:
        row = (
            await self._session.execute(
                select(SubjectModel.active, WorkspaceMembershipModel)
                .join(
                    WorkspaceMembershipModel,
                    WorkspaceMembershipModel.subject_id == SubjectModel.id,
                )
                .where(
                    WorkspaceMembershipModel.workspace_id == workspace_id,
                    WorkspaceMembershipModel.subject_id == subject_id,
                )
                .with_for_update(read=True)
            )
        ).one_or_none()
        if row is None:
            raise ForbiddenError("The administrator membership is no longer available.")
        subject_active, membership = row
        groups = _bounded_string_set(membership.attributes, "groups")
        allowed = _bounded_string_set(membership.attributes, "allowed_actions")
        denied = _bounded_string_set(membership.attributes, "denied_actions")
        if (
            not subject_active
            or not membership.active
            or (
                membership.access_expires_at is not None
                and membership.access_expires_at <= utc_now()
            )
            or membership.job_function == "SERVICE_ACCOUNT"
            or groups is None
            or allowed is None
            or denied is None
            or "security-administrators" not in groups
            or "service-accounts" in groups
            or "admin.manage" not in allowed
            or "admin.manage" in denied
            or "retention.read" not in allowed
            or "retention.read" in denied
            or membership.clearance < int(Classification.RESTRICTED)
        ):
            raise ForbiddenError("The administrator is no longer eligible to read this evidence.")

    async def get_for_erasure_request(
        self,
        *,
        workspace_id: UUID,
        erasure_request_id: UUID,
    ) -> RetentionExecutionEvidence | None:
        job = (
            await self._session.execute(
                select(
                    RetentionExecutionJobModel.id.label("job_id"),
                    RetentionExecutionJobModel.erasure_request_id,
                    RetentionExecutionJobModel.erasure_request_version,
                    RetentionExecutionJobModel.erasure_request_payload_hash,
                    RetentionExecutionJobModel.target_type,
                    RetentionExecutionJobModel.target_id,
                    RetentionExecutionJobModel.target_version,
                    RetentionExecutionJobModel.classification,
                    RetentionExecutionJobModel.retention_policy_id,
                    RetentionExecutionJobModel.retention_policy_hash,
                    RetentionExecutionJobModel.policy_number,
                    RetentionExecutionJobModel.requester_id,
                    RetentionExecutionJobModel.checker_id,
                    RetentionExecutionJobModel.executor_id,
                    RetentionExecutionJobModel.target_owner_id,
                    RetentionExecutionJobModel.execution_authorization_valid_until,
                    RetentionExecutionJobModel.archive_disposition,
                    RetentionExecutionJobModel.command_hash,
                    RetentionExecutionJobModel.archive_retain_until,
                    RetentionExecutionJobModel.state,
                    RetentionExecutionJobModel.next_attempt_at,
                    RetentionExecutionJobModel.attempt_count,
                    RetentionExecutionJobModel.maximum_attempts,
                    RetentionExecutionJobModel.archive_receipt_id,
                    RetentionExecutionJobModel.archive_manifest_hash,
                    RetentionExecutionJobModel.destructive_state,
                    RetentionExecutionJobModel.version,
                    RetentionExecutionJobModel.created_at,
                    RetentionExecutionJobModel.updated_at,
                )
                .where(
                    RetentionExecutionJobModel.workspace_id == workspace_id,
                    RetentionExecutionJobModel.erasure_request_id == erasure_request_id,
                )
                .with_for_update(read=True)
            )
        ).one_or_none()
        if job is None:
            return None

        attempts = (
            await self._session.execute(
                select(
                    RetentionExecutionAttemptModel.attempt_no,
                    RetentionExecutionAttemptModel.state,
                    RetentionExecutionAttemptModel.stage,
                    RetentionExecutionAttemptModel.evidence_hash,
                    RetentionExecutionAttemptModel.destructive_effect_count,
                    RetentionExecutionAttemptModel.started_at,
                    RetentionExecutionAttemptModel.finished_at,
                )
                .where(
                    RetentionExecutionAttemptModel.workspace_id == workspace_id,
                    RetentionExecutionAttemptModel.execution_job_id == job.job_id,
                )
                .order_by(RetentionExecutionAttemptModel.attempt_no.desc())
                .limit(self._ATTEMPT_LIMIT + 1)
            )
        ).all()
        events = (
            await self._session.execute(
                select(
                    RetentionExecutionEventModel.sequence,
                    RetentionExecutionEventModel.event_type,
                    RetentionExecutionEventModel.attempt_no,
                    RetentionExecutionEventModel.evidence_hash,
                    RetentionExecutionEventModel.occurred_at,
                )
                .where(
                    RetentionExecutionEventModel.workspace_id == workspace_id,
                    RetentionExecutionEventModel.execution_job_id == job.job_id,
                )
                .order_by(RetentionExecutionEventModel.sequence.desc())
                .limit(self._EVENT_LIMIT + 1)
            )
        ).all()

        receipt: RetentionArchiveReceiptEvidenceSummary | None = None
        if (job.archive_receipt_id is None) is not (job.archive_manifest_hash is None):
            raise ConflictError("The archive evidence link is incomplete.")
        if job.archive_receipt_id is not None and job.archive_manifest_hash is not None:
            receipt_row = (
                await self._session.execute(
                    select(
                        ImmutableArchiveReceiptModel.id.label("receipt_id"),
                        ImmutableArchiveReceiptModel.manifest_hash,
                        ImmutableArchiveReceiptModel.content_sha256,
                        ImmutableArchiveReceiptModel.row_count,
                        ImmutableArchiveReceiptModel.byte_count,
                        ImmutableArchiveReceiptModel.retention_until,
                        ImmutableArchiveReceiptModel.legal_hold,
                        ImmutableArchiveReceiptModel.content_verified_at,
                        ImmutableArchiveReceiptModel.retention_verified_at,
                        ImmutableArchiveReceiptModel.verified_at,
                        ImmutableArchiveReceiptModel.payload_hash,
                    ).where(
                        ImmutableArchiveReceiptModel.workspace_id == workspace_id,
                        ImmutableArchiveReceiptModel.id == job.archive_receipt_id,
                        ImmutableArchiveReceiptModel.manifest_hash == job.archive_manifest_hash,
                    )
                )
            ).one_or_none()
            if receipt_row is None:
                raise ConflictError("The exact immutable archive receipt is unavailable.")
            receipt = RetentionArchiveReceiptEvidenceSummary(
                receipt_id=receipt_row.receipt_id,
                manifest_hash=receipt_row.manifest_hash,
                content_sha256=receipt_row.content_sha256,
                row_count=int(receipt_row.row_count),
                byte_count=int(receipt_row.byte_count),
                retention_until=receipt_row.retention_until,
                legal_hold=receipt_row.legal_hold,
                content_verified_at=receipt_row.content_verified_at,
                retention_verified_at=receipt_row.retention_verified_at,
                verified_at=receipt_row.verified_at,
                payload_hash=receipt_row.payload_hash,
            )
        if job.state == "ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED" and receipt is None:
            raise ConflictError("The terminal archive evidence is incomplete.")
        if job.state not in {"ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED", "BLOCKED"} and (
            receipt is not None
        ):
            raise ConflictError("The archive evidence state is inconsistent.")

        separation_verified = (
            job.requester_id != job.checker_id
            and job.checker_id != job.target_owner_id
            and job.executor_id not in {job.requester_id, job.checker_id, job.target_owner_id}
        )
        if not separation_verified:
            raise ConflictError("The execution separation-of-duties evidence is invalid.")

        return RetentionExecutionEvidence(
            job_id=job.job_id,
            erasure_request_id=job.erasure_request_id,
            erasure_request_version=job.erasure_request_version,
            erasure_request_payload_hash=job.erasure_request_payload_hash,
            target_type=job.target_type,
            target_id=job.target_id,
            target_version=job.target_version,
            classification=Classification(job.classification),
            retention_policy_id=job.retention_policy_id,
            retention_policy_hash=job.retention_policy_hash,
            policy_number=job.policy_number,
            execution_authorization_valid_until=job.execution_authorization_valid_until,
            archive_disposition=job.archive_disposition,
            command_hash=job.command_hash,
            archive_retain_until=job.archive_retain_until,
            state=job.state,
            next_attempt_at=job.next_attempt_at,
            attempt_count=job.attempt_count,
            maximum_attempts=job.maximum_attempts,
            archive_manifest_hash=job.archive_manifest_hash,
            destructive_state=job.destructive_state,
            separation_of_duties_verified=separation_verified,
            version=job.version,
            created_at=job.created_at,
            updated_at=job.updated_at,
            attempts=tuple(
                RetentionExecutionAttemptEvidence(
                    attempt_no=row.attempt_no,
                    state=row.state,
                    stage=row.stage,
                    evidence_hash=row.evidence_hash,
                    destructive_effect_count=row.destructive_effect_count,
                    started_at=row.started_at,
                    finished_at=row.finished_at,
                )
                for row in attempts[: self._ATTEMPT_LIMIT]
            ),
            attempts_truncated=len(attempts) > self._ATTEMPT_LIMIT,
            events=tuple(
                RetentionExecutionEventEvidence(
                    sequence=row.sequence,
                    event_type=row.event_type,
                    attempt_no=row.attempt_no,
                    evidence_hash=row.evidence_hash,
                    occurred_at=row.occurred_at,
                )
                for row in events[: self._EVENT_LIMIT]
            ),
            events_truncated=len(events) > self._EVENT_LIMIT,
            receipt=receipt,
        )


class SqlRetentionUnitOfWork(RetentionUnitOfWork):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self.policies: SqlRetentionPolicyRepository
        self.legal_holds: SqlLegalHoldRepository
        self.erasure_requests: SqlErasureRequestRepository
        self.erasure_targets: SqlErasureTargetReader
        self.execution_evidence: SqlRetentionExecutionEvidenceReader
        self.outbox: SqlOutboxWriter
        self.idempotency: SqlIdempotencyStore
        self._committed = False

    async def __aenter__(self) -> SqlRetentionUnitOfWork:
        self._session = self._session_factory()
        self.policies = SqlRetentionPolicyRepository(self._session)
        self.legal_holds = SqlLegalHoldRepository(self._session)
        self.erasure_requests = SqlErasureRequestRepository(self._session)
        self.erasure_targets = SqlErasureTargetReader(self._session)
        self.execution_evidence = SqlRetentionExecutionEvidenceReader(self._session)
        self.outbox = SqlOutboxWriter(self._session)
        self.idempotency = SqlIdempotencyStore(self._session)
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

    async def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await self._session.commit()
        self._committed = True

    async def lock_workspace(self, *, workspace_id: UUID) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"datariver:retention:workspace:{workspace_id}"},
        )

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await set_security_context(self._session, workspace_id=workspace_id, subject_id=subject_id)


def _policy_model(policy: RetentionPolicyVersion) -> RetentionPolicyVersionModel:
    return RetentionPolicyVersionModel(
        id=policy.policy_id,
        workspace_id=policy.workspace_id,
        policy_number=policy.policy_number,
        completed_operation_days=policy.rules.completed_operation_days,
        chat_content_days=policy.rules.chat_content_days,
        audit_online_months=policy.rules.audit_online_months,
        immutable_archive_years=policy.rules.immutable_archive_years,
        contract_version=policy.contract_version,
        effective_from=(policy.contract.effective_from if policy.contract is not None else None),
        effective_until=(policy.contract.effective_until if policy.contract is not None else None),
        execution_authorization_hours=(
            policy.contract.execution_authorization_hours if policy.contract is not None else None
        ),
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


def _policy_class_rule_models(
    policy: RetentionPolicyVersion,
) -> tuple[RetentionPolicyClassRuleModel, ...]:
    if policy.contract is None:
        return ()
    return tuple(
        RetentionPolicyClassRuleModel(
            id=uuid7(),
            workspace_id=policy.workspace_id,
            policy_id=policy.policy_id,
            policy_hash=policy.payload_hash,
            policy_number=policy.policy_number,
            data_class=rule.data_class.value,
            unit=rule.unit.value,
            minimum_value=rule.minimum,
            maximum_value=rule.maximum,
            archive_disposition=rule.archive_disposition.value,
            payload_hash=canonical_json_hash(rule.document()),
        )
        for rule in policy.contract.class_rules
    )


def _hydrate_policy(model: RetentionPolicyVersionModel | None) -> RetentionPolicyVersion | None:
    if model is None:
        return None
    return _required_policy(model)


def _required_policy(
    model: RetentionPolicyVersionModel,
    class_rule_models: tuple[RetentionPolicyClassRuleModel, ...] = (),
) -> RetentionPolicyVersion:
    try:
        rules = RetentionRules(
            completed_operation_days=model.completed_operation_days,
            chat_content_days=model.chat_content_days,
            audit_online_months=model.audit_online_months,
            immutable_archive_years=model.immutable_archive_years,
        )
        state = RetentionPolicyState(model.state)
        contract = _policy_contract(model, class_rule_models)
    except (ValueError, ValidationError) as error:
        raise ConflictError("The stored retention policy is invalid.") from error
    policy = RetentionPolicyVersion(
        policy_id=model.id,
        workspace_id=model.workspace_id,
        policy_number=model.policy_number,
        rules=rules,
        payload_hash=model.payload_hash,
        requester_id=model.requester_id,
        request_reason=model.request_reason,
        request_policy_decision_id=model.request_policy_decision_id,
        contract=contract,
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
    policy.assert_integrity()
    return policy


def _policy_contract(
    model: RetentionPolicyVersionModel,
    class_rule_models: tuple[RetentionPolicyClassRuleModel, ...],
) -> RetentionPolicyContract | None:
    contract_version = model.contract_version or "SINGLE_DEADLINE_V1"
    if contract_version == "SINGLE_DEADLINE_V1":
        if class_rule_models:
            raise ConflictError("A legacy retention policy contains unexpected class rules.")
        return None
    if contract_version != "POLICY_BOOK_V2":
        raise ConflictError("The retention policy contract version is unsupported.")
    if model.effective_from is None or model.execution_authorization_hours is None:
        raise ConflictError("The POLICY_BOOK_V2 contract metadata is incomplete.")
    class_rules: list[RetentionClassRule] = []
    for stored in class_rule_models:
        rule = RetentionClassRule(
            data_class=RetentionDataClass(stored.data_class),
            unit=RetentionPeriodUnit(stored.unit),
            minimum=stored.minimum_value,
            maximum=stored.maximum_value,
            archive_disposition=RetentionArchiveDisposition(stored.archive_disposition),
        )
        if (
            stored.workspace_id != model.workspace_id
            or stored.policy_id != model.id
            or stored.policy_hash != model.payload_hash
            or stored.policy_number != model.policy_number
            or canonical_json_hash(rule.document()) != stored.payload_hash
        ):
            raise ConflictError("A stored retention class rule failed its integrity check.")
        class_rules.append(rule)
    return RetentionPolicyContract(
        effective_from=model.effective_from,
        effective_until=model.effective_until,
        execution_authorization_hours=model.execution_authorization_hours,
        class_rules=tuple(class_rules),
    )


def _hold_model(hold: LegalHold) -> LegalHoldModel:
    return LegalHoldModel(
        id=hold.hold_id,
        workspace_id=hold.workspace_id,
        data_class=hold.data_class.value,
        scope=hold.scope.value,
        scope_id=hold.scope_id,
        reason=hold.reason,
        payload_hash=hold.payload_hash,
        created_by=hold.created_by,
        create_policy_decision_id=hold.create_policy_decision_id,
        state=hold.state.value,
        release_requested_by=hold.release_requested_by,
        release_request_reason=hold.release_request_reason,
        release_request_policy_decision_id=hold.release_request_policy_decision_id,
        release_checker_id=hold.release_checker_id,
        release_decision_reason=hold.release_decision_reason,
        release_decision_policy_decision_id=hold.release_decision_policy_decision_id,
        released_at=hold.released_at,
        version=hold.version,
    )


def _hold_event_model(hold: LegalHold, action: LegalHoldAction) -> LegalHoldEventModel:
    return LegalHoldEventModel(
        id=action.action_id,
        workspace_id=hold.workspace_id,
        hold_id=hold.hold_id,
        action=action.action.value,
        actor_id=action.actor_id,
        reason=action.reason,
        policy_decision_id=action.policy_decision_id,
        occurred_at=action.occurred_at,
        hold_version=action.hold_version,
        payload_hash=action.payload_hash,
    )


def _hydrate_hold(
    model: LegalHoldModel,
    events: tuple[LegalHoldEventModel, ...],
    *,
    history_summary: bool = False,
    history_truncated: bool = False,
) -> LegalHold:
    try:
        data_class = RetentionDataClass(model.data_class)
        scope = LegalHoldScope(model.scope)
        state = LegalHoldState(model.state)
        actions = [] if history_summary else [_hydrate_action(model, event) for event in events]
    except (ValueError, ValidationError) as error:
        raise ConflictError("The stored Legal Hold is invalid.") from error
    placement_document = {
        "workspace_id": str(model.workspace_id),
        "data_class": data_class.value,
        "scope": scope.value,
        "scope_id": str(model.scope_id) if model.scope_id else None,
        "reason": model.reason,
    }
    if canonical_json_hash(placement_document) != model.payload_hash:
        raise ConflictError("The stored Legal Hold payload failed its integrity check.")
    if not history_summary:
        expected_first_version = model.version - len(actions) + 1 if history_truncated else 1
        expected_versions = list(range(expected_first_version, model.version + 1))
        if [action.hold_version for action in actions] != expected_versions:
            raise ConflictError("The stored Legal Hold action history is incomplete.")
        expected_last_action = {
            LegalHoldState.ACTIVE: LegalHoldActionType.PLACED,
            LegalHoldState.RELEASE_REQUESTED: LegalHoldActionType.RELEASE_REQUESTED,
            LegalHoldState.RELEASE_REJECTED: LegalHoldActionType.RELEASE_REJECTED,
            LegalHoldState.RELEASED: LegalHoldActionType.RELEASE_APPROVED,
        }[state]
        if not actions or actions[-1].action is not expected_last_action:
            raise ConflictError("The stored Legal Hold state and history do not match.")
    return LegalHold(
        hold_id=model.id,
        workspace_id=model.workspace_id,
        data_class=data_class,
        scope=scope,
        scope_id=model.scope_id,
        reason=model.reason,
        payload_hash=model.payload_hash,
        created_by=model.created_by,
        create_policy_decision_id=model.create_policy_decision_id,
        state=state,
        release_requested_by=model.release_requested_by,
        release_request_reason=model.release_request_reason,
        release_request_policy_decision_id=model.release_request_policy_decision_id,
        release_checker_id=model.release_checker_id,
        release_decision_reason=model.release_decision_reason,
        release_decision_policy_decision_id=model.release_decision_policy_decision_id,
        released_at=model.released_at,
        version=model.version,
        actions=actions,
        action_history_truncated=history_summary or history_truncated,
    )


def _hydrate_action(model: LegalHoldModel, event: LegalHoldEventModel) -> LegalHoldAction:
    action = LegalHoldActionType(event.action)
    payload_hash = canonical_json_hash(
        {
            "hold_id": str(model.id),
            "action": action.value,
            "actor_id": str(event.actor_id),
            "reason": event.reason,
            "policy_decision_id": str(event.policy_decision_id),
            "hold_version": event.hold_version,
            "placement_payload_hash": model.payload_hash,
        }
    )
    if payload_hash != event.payload_hash:
        raise ConflictError("The stored Legal Hold action failed its integrity check.")
    return LegalHoldAction(
        action_id=event.id,
        action=action,
        actor_id=event.actor_id,
        reason=event.reason,
        policy_decision_id=event.policy_decision_id,
        occurred_at=event.occurred_at,
        hold_version=event.hold_version,
        payload_hash=event.payload_hash,
    )


def _erasure_request_model(request: ErasureRequest) -> ErasureRequestModel:
    return ErasureRequestModel(
        id=request.erasure_request_id,
        workspace_id=request.workspace_id,
        target_type=request.target_type.value,
        target_id=request.target_id,
        target_version=request.target_version,
        target_owner_id=request.target_owner_id,
        classification=int(request.classification),
        retention_policy_id=request.retention_policy_id,
        retention_policy_hash=request.retention_policy_hash,
        requester_id=request.requester_id,
        request_reason=request.request_reason,
        request_policy_decision_id=request.request_policy_decision_id,
        payload_hash=request.payload_hash,
        expires_at=request.expires_at,
        state=request.state.value,
        checker_id=request.checker_id,
        decision_reason=request.decision_reason,
        decision_policy_decision_id=request.decision_policy_decision_id,
        decided_at=request.decided_at,
        version=request.version,
    )


def _erasure_created_event_model(request: ErasureRequest) -> ErasureRequestEventModel:
    return ErasureRequestEventModel(
        id=uuid7(),
        workspace_id=request.workspace_id,
        erasure_request_id=request.erasure_request_id,
        action="CREATED",
        actor_id=request.requester_id,
        reason=request.request_reason,
        policy_decision_id=request.request_policy_decision_id,
        occurred_at=utc_now(),
        request_version=1,
        payload_hash=request.payload_hash,
    )


def _erasure_approval_event_model(
    request: ErasureRequest, approval: ErasureApproval
) -> ErasureRequestEventModel:
    return ErasureRequestEventModel(
        id=approval.approval_id,
        workspace_id=request.workspace_id,
        erasure_request_id=request.erasure_request_id,
        action=approval.decision.value,
        actor_id=approval.actor_id,
        reason=approval.reason,
        policy_decision_id=approval.policy_decision_id,
        occurred_at=approval.occurred_at,
        request_version=approval.request_version,
        payload_hash=approval.payload_hash,
    )


def _hydrate_erasure_request(
    model: ErasureRequestModel,
    events: tuple[ErasureRequestEventModel, ...],
    *,
    history_summary: bool = False,
) -> ErasureRequest:
    try:
        target_type = ErasureTargetType(model.target_type)
        classification = Classification(model.classification)
        state = ErasureRequestState(model.state)
    except ValueError as error:
        raise ConflictError("The stored erasure request is invalid.") from error
    document = {
        "workspace_id": str(model.workspace_id),
        "target_type": target_type.value,
        "target_id": str(model.target_id),
        "target_version": model.target_version,
        "target_owner_id": str(model.target_owner_id) if model.target_owner_id else None,
        "classification": classification.name,
        "retention_policy_id": str(model.retention_policy_id),
        "retention_policy_hash": model.retention_policy_hash,
        "requester_id": str(model.requester_id),
        "request_reason": model.request_reason,
        "request_policy_decision_id": str(model.request_policy_decision_id),
        "expires_at": model.expires_at.isoformat(),
    }
    if canonical_json_hash(document) != model.payload_hash:
        raise ConflictError("The stored erasure request payload failed its integrity check.")
    approvals: list[ErasureApproval] = []
    if not history_summary:
        if [event.request_version for event in events] != list(range(1, model.version + 1)):
            raise ConflictError("The stored erasure request event history is incomplete.")
        if not events or not _created_event_matches(model, events[0]):
            raise ConflictError("The stored erasure request creation event is invalid.")

        approvals = [_approval_from_event(model, event) for event in events[1:]]
        expected_action = {
            ErasureRequestState.PENDING: "CREATED",
            ErasureRequestState.APPROVED: GovernanceDecision.APPROVED.value,
            ErasureRequestState.REJECTED: GovernanceDecision.REJECTED.value,
        }[state]
        if events[-1].action != expected_action:
            raise ConflictError("The stored erasure request state and history do not match.")
    return ErasureRequest(
        erasure_request_id=model.id,
        workspace_id=model.workspace_id,
        target_type=target_type,
        target_id=model.target_id,
        target_version=model.target_version,
        target_owner_id=model.target_owner_id,
        classification=classification,
        retention_policy_id=model.retention_policy_id,
        retention_policy_hash=model.retention_policy_hash,
        requester_id=model.requester_id,
        request_reason=model.request_reason,
        request_policy_decision_id=model.request_policy_decision_id,
        payload_hash=model.payload_hash,
        expires_at=model.expires_at,
        state=state,
        checker_id=model.checker_id,
        decision_reason=model.decision_reason,
        decision_policy_decision_id=model.decision_policy_decision_id,
        decided_at=model.decided_at,
        version=model.version,
        approvals=approvals,
        approval_history_truncated=history_summary,
    )


def _created_event_matches(model: ErasureRequestModel, event: ErasureRequestEventModel) -> bool:
    return (
        event.action == "CREATED"
        and event.actor_id == model.requester_id
        and event.reason == model.request_reason
        and event.policy_decision_id == model.request_policy_decision_id
        and event.payload_hash == model.payload_hash
        and event.request_version == 1
    )


def _approval_from_event(
    model: ErasureRequestModel, event: ErasureRequestEventModel
) -> ErasureApproval:
    try:
        decision = GovernanceDecision(event.action)
    except ValueError as error:
        raise ConflictError("The stored erasure approval action is invalid.") from error
    if event.payload_hash != model.payload_hash:
        raise ConflictError("The stored erasure approval lost its target binding.")
    if (
        event.actor_id != model.checker_id
        or event.reason != model.decision_reason
        or event.policy_decision_id != model.decision_policy_decision_id
        or event.occurred_at != model.decided_at
    ):
        raise ConflictError("The stored erasure approval does not match its request.")
    return ErasureApproval(
        approval_id=event.id,
        decision=decision,
        actor_id=event.actor_id,
        reason=event.reason,
        policy_decision_id=event.policy_decision_id,
        payload_hash=event.payload_hash,
        request_version=event.request_version,
        occurred_at=event.occurred_at,
    )


def _classification_or_restricted(value: int | None) -> Classification:
    if value is None:
        return Classification.RESTRICTED
    try:
        return Classification(value)
    except ValueError:
        return Classification.RESTRICTED


def _archive_capability_model(
    *,
    workspace_id: UUID,
    capability: ArchiveCapability,
    evidence: ArchiveCapabilityEvidence,
) -> ArchiveCapabilityAttestationModel:
    _require_archive_hash(
        evidence.encryption_profile_fingerprint, "archive encryption profile fingerprint"
    )
    _require_archive_hash(
        evidence.runtime_principal_fingerprint, "archive runtime principal fingerprint"
    )
    _require_archive_hash(evidence.challenge_hash, "archive capability challenge")
    if capability.challenge_hash != evidence.challenge_hash:
        raise ValidationError("The archive capability challenge lost its probe binding.")
    _require_archive_text(evidence.probe_contract_version, 100, "probe contract version")
    _require_archive_bucket(evidence.object_bucket)
    controls_verified = all(
        (
            capability.versioning_enabled,
            capability.object_lock_enabled,
            capability.compliance_retention_supported,
            capability.checksum_sha256_supported,
            capability.full_readback_verified,
            capability.retention_shorten_denied,
            capability.retained_version_delete_denied,
        )
    )
    if controls_verified and evidence.failure_code is None:
        state = "VERIFIED"
    else:
        _require_archive_text(evidence.failure_code, 100, "capability failure code")
        state = "FAILED"

    attestation_id = uuid7()
    document = _archive_capability_document(
        attestation_id=attestation_id,
        workspace_id=workspace_id,
        capability=capability,
        evidence=evidence,
        state=state,
    )
    return ArchiveCapabilityAttestationModel(
        id=attestation_id,
        workspace_id=workspace_id,
        configuration_fingerprint=capability.configuration_fingerprint,
        encryption_profile_fingerprint=evidence.encryption_profile_fingerprint,
        runtime_principal_fingerprint=evidence.runtime_principal_fingerprint,
        probe_contract_version=evidence.probe_contract_version,
        challenge_hash=evidence.challenge_hash,
        object_bucket=evidence.object_bucket,
        observed_at=capability.observed_at,
        expires_at=capability.expires_at,
        versioning_enabled=capability.versioning_enabled,
        object_lock_enabled=capability.object_lock_enabled,
        compliance_retention_supported=capability.compliance_retention_supported,
        checksum_sha256_supported=capability.checksum_sha256_supported,
        full_readback_verified=capability.full_readback_verified,
        retention_shorten_denied=capability.retention_shorten_denied,
        retained_version_delete_denied=capability.retained_version_delete_denied,
        state=state,
        failure_code=evidence.failure_code,
        payload_hash=canonical_json_hash(document),
    )


def _archive_capability_document(
    *,
    attestation_id: UUID,
    workspace_id: UUID,
    capability: ArchiveCapability,
    evidence: ArchiveCapabilityEvidence,
    state: str,
) -> dict[str, object]:
    return {
        "attestation_id": str(attestation_id),
        "workspace_id": str(workspace_id),
        "configuration_fingerprint": capability.configuration_fingerprint,
        "encryption_profile_fingerprint": evidence.encryption_profile_fingerprint,
        "runtime_principal_fingerprint": evidence.runtime_principal_fingerprint,
        "probe_contract_version": evidence.probe_contract_version,
        "challenge_hash": evidence.challenge_hash,
        "object_bucket": evidence.object_bucket,
        "observed_at": capability.observed_at.isoformat(),
        "expires_at": capability.expires_at.isoformat(),
        "versioning_enabled": capability.versioning_enabled,
        "object_lock_enabled": capability.object_lock_enabled,
        "compliance_retention_supported": capability.compliance_retention_supported,
        "checksum_sha256_supported": capability.checksum_sha256_supported,
        "full_readback_verified": capability.full_readback_verified,
        "retention_shorten_denied": capability.retention_shorten_denied,
        "retained_version_delete_denied": capability.retained_version_delete_denied,
        "state": state,
        "failure_code": evidence.failure_code,
    }


def _hydrate_archive_capability(
    model: ArchiveCapabilityAttestationModel | None,
) -> ArchiveCapability | None:
    if model is None:
        return None
    return _required_archive_capability(model)


def _hydrate_archive_capability_record(
    model: ArchiveCapabilityAttestationModel | None,
) -> ArchiveCapabilityRecord | None:
    if model is None:
        return None
    capability, evidence = _required_archive_capability_parts(model)
    return ArchiveCapabilityRecord(
        attestation_id=model.id,
        capability=capability,
        evidence=evidence,
    )


def _required_archive_capability(
    model: ArchiveCapabilityAttestationModel,
) -> ArchiveCapability:
    capability, _evidence = _required_archive_capability_parts(model)
    return capability


def _required_archive_capability_parts(
    model: ArchiveCapabilityAttestationModel,
) -> tuple[ArchiveCapability, ArchiveCapabilityEvidence]:
    if model.state != "VERIFIED" or model.failure_code is not None:
        raise ConflictError("The stored archive capability is not verified.")
    try:
        capability = ArchiveCapability(
            configuration_fingerprint=model.configuration_fingerprint,
            challenge_hash=model.challenge_hash,
            observed_at=model.observed_at,
            expires_at=model.expires_at,
            versioning_enabled=model.versioning_enabled,
            object_lock_enabled=model.object_lock_enabled,
            compliance_retention_supported=model.compliance_retention_supported,
            checksum_sha256_supported=model.checksum_sha256_supported,
            full_readback_verified=model.full_readback_verified,
            retention_shorten_denied=model.retention_shorten_denied,
            retained_version_delete_denied=model.retained_version_delete_denied,
        )
        evidence = ArchiveCapabilityEvidence(
            encryption_profile_fingerprint=model.encryption_profile_fingerprint,
            runtime_principal_fingerprint=model.runtime_principal_fingerprint,
            probe_contract_version=model.probe_contract_version,
            challenge_hash=model.challenge_hash,
            object_bucket=model.object_bucket,
            failure_code=model.failure_code,
        )
    except (ValueError, ValidationError) as error:
        raise ConflictError("The stored archive capability evidence is invalid.") from error
    document = _archive_capability_document(
        attestation_id=model.id,
        workspace_id=model.workspace_id,
        capability=capability,
        evidence=evidence,
        state=model.state,
    )
    if canonical_json_hash(document) != model.payload_hash:
        raise ConflictError("The stored archive capability failed its integrity check.")
    return capability, evidence


def _archive_receipt_model(
    *,
    receipt: ImmutableArchiveReceipt,
    evidence: ArchiveReceiptEvidence,
    capability_attestation_id: UUID,
) -> ImmutableArchiveReceiptModel:
    normalized_provider_checksum = _normalized_provider_checksum(
        value=receipt.provider_checksum,
        algorithm=evidence.provider_checksum_algorithm,
        encoding=evidence.provider_checksum_encoding,
        checksum_type=evidence.provider_checksum_type,
    )
    _validate_archive_receipt_evidence(
        receipt=receipt,
        evidence=evidence,
        normalized_provider_checksum=normalized_provider_checksum,
    )
    document = _archive_receipt_document(
        receipt=receipt,
        evidence=evidence,
        capability_attestation_id=capability_attestation_id,
        normalized_provider_checksum=normalized_provider_checksum,
    )
    return ImmutableArchiveReceiptModel(
        id=receipt.receipt_id,
        workspace_id=receipt.workspace_id,
        source=receipt.source.value,
        source_partition=receipt.source_partition,
        source_start=evidence.source_start,
        source_end=evidence.source_end,
        retention_policy_id=evidence.retention_policy_id,
        retention_policy_hash=evidence.retention_policy_hash,
        row_count=receipt.row_count,
        byte_count=receipt.byte_count,
        manifest_hash=evidence.manifest_hash,
        content_sha256=receipt.content_sha256,
        provider_checksum=receipt.provider_checksum,
        provider_checksum_algorithm=evidence.provider_checksum_algorithm,
        provider_checksum_encoding=evidence.provider_checksum_encoding,
        provider_checksum_type=evidence.provider_checksum_type,
        provider_checksum_normalized_sha256=normalized_provider_checksum,
        readback_sha256=evidence.readback_sha256,
        readback_byte_count=evidence.readback_byte_count,
        object_bucket=receipt.object_bucket,
        object_key=receipt.object_key,
        object_version_id=receipt.object_version_id,
        retention_mode=receipt.retention_mode.value,
        retention_until=receipt.retention_until,
        requested_retention_until=evidence.requested_retention_until,
        readback_retention_until=evidence.readback_retention_until,
        legal_hold=receipt.legal_hold,
        written_at=evidence.written_at,
        content_verified_at=evidence.content_verified_at,
        retention_verified_at=evidence.retention_verified_at,
        verified_at=receipt.verified_at,
        canonicalization_version=evidence.canonicalization_version,
        media_type=evidence.media_type,
        media_type_version=evidence.media_type_version,
        compression=evidence.compression,
        compression_version=evidence.compression_version,
        worker_principal_fingerprint=evidence.worker_principal_fingerprint,
        correlation_id=evidence.correlation_id,
        capability_attestation_id=capability_attestation_id,
        capability_fingerprint=receipt.capability_fingerprint,
        encryption_profile_fingerprint=evidence.encryption_profile_fingerprint,
        payload_hash=canonical_json_hash(document),
    )


def _validate_archive_receipt_evidence(
    *,
    receipt: ImmutableArchiveReceipt,
    evidence: ArchiveReceiptEvidence,
    normalized_provider_checksum: str,
) -> None:
    for timestamp, name in (
        (evidence.source_start, "archive source start"),
        (evidence.source_end, "archive source end"),
        (evidence.requested_retention_until, "requested archive retention"),
        (evidence.readback_retention_until, "read-back archive retention"),
        (evidence.written_at, "archive write"),
        (evidence.content_verified_at, "archive content verification"),
        (evidence.retention_verified_at, "archive retention verification"),
    ):
        _require_archive_timestamp(timestamp, name)
    if evidence.source_end <= evidence.source_start:
        raise ValidationError("The archive source range must be positive.")
    for value, name in (
        (evidence.retention_policy_hash, "retention policy hash"),
        (evidence.manifest_hash, "archive manifest hash"),
        (evidence.readback_sha256, "archive read-back hash"),
        (evidence.worker_principal_fingerprint, "archive worker principal fingerprint"),
        (evidence.encryption_profile_fingerprint, "archive encryption profile fingerprint"),
    ):
        _require_archive_hash(value, name)
    if evidence.readback_byte_count < 1:
        raise ValidationError("The archive read-back byte count must be positive.")
    if not (
        receipt.content_sha256 == normalized_provider_checksum == evidence.readback_sha256
        and receipt.byte_count == evidence.readback_byte_count
    ):
        raise ValidationError("Provider and full read-back evidence must match the archive.")
    if not (
        receipt.retention_until
        == evidence.requested_retention_until
        == evidence.readback_retention_until
    ):
        raise ValidationError("Requested and read-back retention evidence must match.")
    if not (
        evidence.written_at <= evidence.content_verified_at <= receipt.verified_at
        and evidence.written_at <= evidence.retention_verified_at <= receipt.verified_at
    ):
        raise ValidationError("The immutable archive verification timeline is invalid.")
    _require_archive_text(evidence.canonicalization_version, 100, "canonicalization version")
    _require_archive_text(evidence.media_type, 255, "archive media type")
    _require_archive_text(evidence.media_type_version, 100, "archive media type version")
    _require_archive_text(evidence.compression, 50, "archive compression")
    _require_archive_text(evidence.compression_version, 100, "archive compression version")
    _require_archive_text(evidence.correlation_id, 100, "archive correlation identifier")


def _archive_receipt_document(
    *,
    receipt: ImmutableArchiveReceipt,
    evidence: ArchiveReceiptEvidence,
    capability_attestation_id: UUID,
    normalized_provider_checksum: str,
) -> dict[str, object]:
    return {
        "receipt_id": str(receipt.receipt_id),
        "workspace_id": str(receipt.workspace_id),
        "source": receipt.source.value,
        "source_partition": receipt.source_partition,
        "source_start": evidence.source_start.isoformat(),
        "source_end": evidence.source_end.isoformat(),
        "retention_policy_id": str(evidence.retention_policy_id),
        "retention_policy_hash": evidence.retention_policy_hash,
        "row_count": receipt.row_count,
        "byte_count": receipt.byte_count,
        "manifest_hash": evidence.manifest_hash,
        "content_sha256": receipt.content_sha256,
        "provider_checksum": receipt.provider_checksum,
        "provider_checksum_algorithm": evidence.provider_checksum_algorithm,
        "provider_checksum_encoding": evidence.provider_checksum_encoding,
        "provider_checksum_type": evidence.provider_checksum_type,
        "provider_checksum_normalized_sha256": normalized_provider_checksum,
        "readback_sha256": evidence.readback_sha256,
        "readback_byte_count": evidence.readback_byte_count,
        "object_bucket": receipt.object_bucket,
        "object_key": receipt.object_key,
        "object_version_id": receipt.object_version_id,
        "retention_mode": receipt.retention_mode.value,
        "retention_until": receipt.retention_until.isoformat(),
        "requested_retention_until": evidence.requested_retention_until.isoformat(),
        "readback_retention_until": evidence.readback_retention_until.isoformat(),
        "legal_hold": receipt.legal_hold,
        "written_at": evidence.written_at.isoformat(),
        "content_verified_at": evidence.content_verified_at.isoformat(),
        "retention_verified_at": evidence.retention_verified_at.isoformat(),
        "verified_at": receipt.verified_at.isoformat(),
        "canonicalization_version": evidence.canonicalization_version,
        "media_type": evidence.media_type,
        "media_type_version": evidence.media_type_version,
        "compression": evidence.compression,
        "compression_version": evidence.compression_version,
        "worker_principal_fingerprint": evidence.worker_principal_fingerprint,
        "correlation_id": evidence.correlation_id,
        "capability_attestation_id": str(capability_attestation_id),
        "capability_fingerprint": receipt.capability_fingerprint,
        "encryption_profile_fingerprint": evidence.encryption_profile_fingerprint,
    }


def _hydrate_archive_receipt(
    model: ImmutableArchiveReceiptModel | None,
) -> ImmutableArchiveReceipt | None:
    if model is None:
        return None
    try:
        receipt = ImmutableArchiveReceipt(
            receipt_id=model.id,
            workspace_id=model.workspace_id,
            source=ArchiveSource(model.source),
            source_partition=model.source_partition,
            row_count=model.row_count,
            byte_count=model.byte_count,
            content_sha256=model.content_sha256,
            provider_checksum=model.provider_checksum,
            object_bucket=model.object_bucket,
            object_key=model.object_key,
            object_version_id=model.object_version_id,
            retention_mode=ArchiveRetentionMode(model.retention_mode),
            retention_until=model.retention_until,
            legal_hold=model.legal_hold,
            verified_at=model.verified_at,
            capability_fingerprint=model.capability_fingerprint,
        )
        evidence = ArchiveReceiptEvidence(
            source_start=model.source_start,
            source_end=model.source_end,
            retention_policy_id=model.retention_policy_id,
            retention_policy_hash=model.retention_policy_hash,
            manifest_hash=model.manifest_hash,
            provider_checksum_algorithm=model.provider_checksum_algorithm,
            provider_checksum_encoding=model.provider_checksum_encoding,
            provider_checksum_type=model.provider_checksum_type,
            readback_sha256=model.readback_sha256,
            readback_byte_count=model.readback_byte_count,
            requested_retention_until=model.requested_retention_until,
            readback_retention_until=model.readback_retention_until,
            written_at=model.written_at,
            content_verified_at=model.content_verified_at,
            retention_verified_at=model.retention_verified_at,
            canonicalization_version=model.canonicalization_version,
            media_type=model.media_type,
            media_type_version=model.media_type_version,
            compression=model.compression,
            compression_version=model.compression_version,
            worker_principal_fingerprint=model.worker_principal_fingerprint,
            correlation_id=model.correlation_id,
            encryption_profile_fingerprint=model.encryption_profile_fingerprint,
        )
        _validate_archive_receipt_evidence(
            receipt=receipt,
            evidence=evidence,
            normalized_provider_checksum=model.provider_checksum_normalized_sha256,
        )
    except (ValueError, ValidationError) as error:
        raise ConflictError("The stored immutable archive receipt is invalid.") from error
    document = _archive_receipt_document(
        receipt=receipt,
        evidence=evidence,
        capability_attestation_id=model.capability_attestation_id,
        normalized_provider_checksum=model.provider_checksum_normalized_sha256,
    )
    if canonical_json_hash(document) != model.payload_hash:
        raise ConflictError("The stored immutable archive receipt failed its integrity check.")
    return receipt


def _normalized_provider_checksum(
    *, value: str, algorithm: str, encoding: str, checksum_type: str
) -> str:
    if algorithm != "SHA256" or checksum_type != "FULL_OBJECT":
        raise ValidationError("Immutable archives require a full-object SHA-256 checksum.")
    if encoding == "HEX":
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValidationError("The provider SHA-256 hex checksum is invalid.")
        return value
    if encoding != "BASE64":
        raise ValidationError("The provider checksum encoding is unsupported.")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValidationError("The provider SHA-256 base64 checksum is invalid.") from error
    if len(decoded) != 32:
        raise ValidationError("The provider SHA-256 base64 checksum is invalid.")
    return decoded.hex()


def _advance_calendar_years(value: datetime, years: int) -> datetime:
    """Advance a policy deadline by calendar years; Feb-29 becomes Feb-28."""
    _require_archive_timestamp(value, "archive retention basis")
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, month=2, day=28)


def _require_archive_hash(value: str, name: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValidationError(f"The {name} is invalid.")


def _require_archive_text(value: str | None, maximum: int, name: str) -> None:
    if value is None or not value.strip() or len(value) > maximum:
        raise ValidationError(f"The {name} is invalid.")


def _require_archive_bucket(value: str) -> None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", value):
        raise ValidationError("The immutable archive bucket name is invalid.")


def _require_archive_timestamp(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError(f"The {name} timestamp must include a timezone.")


def _bounded_string_set(document: object, key: str) -> frozenset[str] | None:
    if not isinstance(document, dict):
        return None
    values = document.get(key)
    if not isinstance(values, list) or len(values) > 100:
        return None
    if any(not isinstance(value, str) or not value or len(value) > 200 for value in values):
        return None
    return frozenset(values)
