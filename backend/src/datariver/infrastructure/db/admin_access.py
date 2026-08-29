from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from types import TracebackType
from typing import Any
from uuid import UUID

from sqlalchemy import and_, cast, exists, func, or_, select, text, tuple_
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.application.dto import (
    AdminAccessRequestPage,
    CanonicalAdminBindingEvidence,
    MembershipChangeRequestActivity,
    MembershipChangeRequestActivityPage,
    MembershipOwnedTable,
    MembershipOwnedTablePage,
    MembershipRenewalPage,
    MembershipRenewalRecord,
    MembershipRoleAssignmentEvidence,
    ProfileRoleAssignmentEvidence,
    ProfileRoleTransitionResult,
    SystemAssigneeCandidate,
    SystemAssigneeCandidatePage,
    SystemAssigneePage,
    SystemDirectoryAssignee,
    SystemDirectoryEntry,
    SystemDirectoryPage,
    SystemSchemaScope,
    SystemSchemaScopeCandidate,
    SystemSchemaScopeCandidatePage,
    SystemSchemaScopePage,
    WorkspaceMembershipAccessRecord,
    WorkspaceMembershipPage,
    WorkspaceMembershipSummary,
)
from datariver.application.identity_admin import IdentityProfileTarget, ProvisionedWorkspaceUser
from datariver.application.ports import (
    AdminAccessRequestRepository,
    AdminAccessUnitOfWork,
    MembershipAccessRepository,
    MembershipRenewalRepository,
    SystemDirectoryRepository,
)
from datariver.domain.admin_access import (
    MEMBERSHIP_ACCESS_COMMAND,
    AdminAccessApproval,
    AdminAccessDecision,
    AdminAccessRequest,
    AdminAccessRequestState,
    MembershipAccessUpdate,
    SystemAssigneePatchCommand,
    SystemAssigneeUpdateCommand,
    SystemSchemaScopePatchCommand,
)
from datariver.domain.authz import SERVICE_ONLY_ACTIONS, Action, Classification, SubjectAttributes
from datariver.domain.capability_catalog import (
    CANONICAL_ADMIN_CAPABILITY_HASH,
    CANONICAL_ADMIN_ROLE_KEY,
    CAPABILITY_CATALOG_VERSION,
    DEFAULT_HUMAN_ADMIN_ACTIONS,
    AccessRoleKind,
    AccessRoleManagementSource,
)
from datariver.domain.catalog import DATASET_ASSET_TYPES
from datariver.domain.common import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
    canonical_json_hash,
    utc_now,
)
from datariver.domain.membership_renewal import MembershipRenewalRequest, MembershipRenewalState
from datariver.domain.profile_roles import (
    PROFILE_ROLE_BY_TIER,
    PROFILE_ROLE_POLICY_VERSION,
    EffectiveProfileRoleStatus,
    ProfileRoleTier,
)
from datariver.infrastructure.db.governance import SqlIdempotencyStore, SqlOutboxWriter
from datariver.infrastructure.db.models.catalog import AssetProjectionModel
from datariver.infrastructure.db.models.governance import ApprovalModel, ChangeRequestModel
from datariver.infrastructure.db.models.platform import (
    AccessRoleAssignmentEventModel,
    AccessRoleAssignmentModel,
    AccessRoleModel,
    AdminAccessApprovalModel,
    AdminAccessRequestModel,
    CanonicalAdminBindingModel,
    DataSystemModel,
    MembershipRenewalRequestModel,
    ProfileRoleAssignmentModel,
    SubjectModel,
    SystemAssigneeModel,
    SystemSchemaScopeModel,
    WorkspaceMembershipModel,
)
from datariver.infrastructure.db.rls import set_security_context

_ADMIN_LIST_CURSOR_KEYS = frozenset({"v", "scope", "workspace_id", "filters", "boundary_id"})
_MEMBERSHIP_CURSOR_KEYS = frozenset(
    {"v", "workspace_id", "query", "active", "display_name", "subject_id"}
)


def _validate_admin_list_limit(limit: int) -> None:
    if limit < 1 or limit > 100:
        raise ValidationError("An administrator list page must contain between 1 and 100 items.")


def encode_admin_list_cursor(
    *,
    scope: str,
    workspace_id: UUID,
    filters: Mapping[str, str | bool | None],
    boundary_id: UUID,
) -> str:
    payload = json.dumps(
        {
            "v": 1,
            "scope": scope,
            "workspace_id": str(workspace_id),
            "filters": dict(filters),
            "boundary_id": str(boundary_id),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_admin_list_cursor(
    cursor: str,
    *,
    scope: str,
    workspace_id: UUID,
    filters: Mapping[str, str | bool | None],
) -> UUID:
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
            or frozenset(document) != _ADMIN_LIST_CURSOR_KEYS
            or document.get("v") != 1
            or document.get("scope") != scope
            or document.get("workspace_id") != str(workspace_id)
            or document.get("filters") != dict(filters)
        ):
            raise ValueError
        boundary_id = UUID(str(document["boundary_id"]))
        if cursor != encode_admin_list_cursor(
            scope=scope,
            workspace_id=workspace_id,
            filters=filters,
            boundary_id=boundary_id,
        ):
            raise ValueError
        return boundary_id
    except (
        ValueError,
        TypeError,
        KeyError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        binascii.Error,
    ) as error:
        raise ValidationError(
            "The administrator list cursor is stale or does not match this request."
        ) from error


class SqlAdminAccessRequestRepository(AdminAccessRequestRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, request: AdminAccessRequest) -> None:
        self._session.add(_request_model(request))

    async def get_for_update(
        self, *, workspace_id: UUID, access_request_id: UUID
    ) -> AdminAccessRequest | None:
        model = (
            await self._session.scalars(
                select(AdminAccessRequestModel)
                .where(
                    AdminAccessRequestModel.workspace_id == workspace_id,
                    AdminAccessRequestModel.id == access_request_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        return await self._hydrate(model)

    async def get(
        self, *, workspace_id: UUID, access_request_id: UUID
    ) -> AdminAccessRequest | None:
        model = (
            await self._session.scalars(
                select(AdminAccessRequestModel).where(
                    AdminAccessRequestModel.workspace_id == workspace_id,
                    AdminAccessRequestModel.id == access_request_id,
                )
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
    ) -> AdminAccessRequestPage:
        _validate_admin_list_limit(limit)
        statement = (
            select(AdminAccessRequestModel)
            .where(AdminAccessRequestModel.workspace_id == workspace_id)
            .order_by(AdminAccessRequestModel.id.desc())
            .limit(limit + 1)
        )
        if state is not None:
            statement = statement.where(AdminAccessRequestModel.state == state)
        if cursor is not None:
            boundary_id = decode_admin_list_cursor(
                cursor,
                scope="ADMIN_FALLBACK_REQUESTS",
                workspace_id=workspace_id,
                filters={"state": state},
            )
            statement = statement.where(AdminAccessRequestModel.id < boundary_id)
        models = (await self._session.scalars(statement)).all()
        has_more = len(models) > limit
        visible_models = models[:limit]
        approvals_by_request: dict[UUID, list[AdminAccessApprovalModel]] = {
            model.id: [] for model in visible_models
        }
        if visible_models:
            approval_models = (
                await self._session.scalars(
                    select(AdminAccessApprovalModel)
                    .where(
                        AdminAccessApprovalModel.workspace_id == workspace_id,
                        AdminAccessApprovalModel.access_request_id.in_(
                            [model.id for model in visible_models]
                        ),
                    )
                    .order_by(
                        AdminAccessApprovalModel.access_request_id,
                        AdminAccessApprovalModel.occurred_at,
                    )
                )
            ).all()
            for approval in approval_models:
                approvals_by_request[approval.access_request_id].append(approval)
        values = [
            value
            for model in visible_models
            if (
                value := await self._hydrate(
                    model,
                    approval_models=approvals_by_request[model.id],
                )
            )
            is not None
        ]
        return AdminAccessRequestPage(
            items=tuple(values),
            next_cursor=(
                encode_admin_list_cursor(
                    scope="ADMIN_FALLBACK_REQUESTS",
                    workspace_id=workspace_id,
                    filters={"state": state},
                    boundary_id=visible_models[-1].id,
                )
                if has_more
                else None
            ),
        )

    async def save(self, request: AdminAccessRequest) -> None:
        model = await self._session.get(AdminAccessRequestModel, request.access_request_id)
        if model is None or model.workspace_id != request.workspace_id:
            raise NotFoundError("The administrator fallback request does not exist.")
        model.state = request.state.value
        model.version = request.version
        model.checker_id = request.checker_id
        model.consumed_by = request.consumed_by
        model.consumed_at = request.consumed_at
        model.consume_policy_decision_id = request.consume_policy_decision_id
        stored_ids = set(
            (
                await self._session.scalars(
                    select(AdminAccessApprovalModel.id).where(
                        AdminAccessApprovalModel.workspace_id == request.workspace_id,
                        AdminAccessApprovalModel.access_request_id == request.access_request_id,
                    )
                )
            ).all()
        )
        self._session.add_all(
            [
                AdminAccessApprovalModel(
                    id=approval.approval_id,
                    workspace_id=request.workspace_id,
                    access_request_id=request.access_request_id,
                    actor_id=approval.actor_id,
                    decision=approval.decision.value,
                    reason=approval.reason,
                    policy_decision_id=approval.policy_decision_id,
                    payload_hash=approval.payload_hash,
                    request_version=approval.request_version,
                    occurred_at=approval.occurred_at,
                )
                for approval in request.approvals
                if approval.approval_id not in stored_ids
            ]
        )

    async def _hydrate(
        self,
        model: AdminAccessRequestModel | None,
        *,
        approval_models: Sequence[AdminAccessApprovalModel] | None = None,
    ) -> AdminAccessRequest | None:
        if model is None:
            return None
        command = MembershipAccessUpdate.from_command_document(model.command_document)
        if (
            command.payload_hash != model.payload_hash
            or model.command_type != MEMBERSHIP_ACCESS_COMMAND
        ):
            raise ConflictError(
                "The stored administrator fallback command failed integrity checks."
            )
        if approval_models is None:
            approval_models = (
                await self._session.scalars(
                    select(AdminAccessApprovalModel)
                    .where(
                        AdminAccessApprovalModel.workspace_id == model.workspace_id,
                        AdminAccessApprovalModel.access_request_id == model.id,
                    )
                    .order_by(AdminAccessApprovalModel.occurred_at)
                )
            ).all()
        if command.workspace_id != model.workspace_id or command.target_subject_id != (
            model.target_subject_id
        ):
            raise ConflictError(
                "The stored administrator fallback command does not match its envelope."
            )
        if any(approval.payload_hash != model.payload_hash for approval in approval_models):
            raise ConflictError(
                "The stored administrator fallback approval failed integrity checks."
            )
        if model.state == AdminAccessRequestState.PENDING.value:
            valid_state_shape = (
                not approval_models and model.checker_id is None and model.version == 1
            )
        else:
            expected_decision = (
                AdminAccessDecision.REJECTED.value
                if model.state == AdminAccessRequestState.REJECTED.value
                else AdminAccessDecision.APPROVED.value
            )
            expected_version = 3 if model.state == AdminAccessRequestState.CONSUMED.value else 2
            valid_state_shape = (
                len(approval_models) == 1
                and model.checker_id == approval_models[0].actor_id
                and approval_models[0].request_version == 2
                and approval_models[0].decision == expected_decision
                and model.version == expected_version
            )
        if not valid_state_shape:
            raise ConflictError(
                "The stored administrator fallback approval state failed integrity checks."
            )
        return AdminAccessRequest(
            access_request_id=model.id,
            workspace_id=model.workspace_id,
            requester_id=model.requester_id,
            request_reason=model.request_reason,
            request_policy_decision_id=model.request_policy_decision_id,
            command=command,
            payload_hash=model.payload_hash,
            expires_at=model.expires_at,
            state=AdminAccessRequestState(model.state),
            version=model.version,
            approvals=[
                AdminAccessApproval(
                    approval_id=approval.id,
                    decision=AdminAccessDecision(approval.decision),
                    actor_id=approval.actor_id,
                    reason=approval.reason,
                    policy_decision_id=approval.policy_decision_id,
                    payload_hash=approval.payload_hash,
                    request_version=approval.request_version,
                    occurred_at=approval.occurred_at,
                )
                for approval in approval_models
            ],
            checker_id=model.checker_id,
            consumed_by=model.consumed_by,
            consumed_at=model.consumed_at,
            consume_policy_decision_id=model.consume_policy_decision_id,
        )


class SqlMembershipRenewalRepository(MembershipRenewalRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, request: MembershipRenewalRequest) -> None:
        self._session.add(
            MembershipRenewalRequestModel(
                id=request.renewal_request_id,
                workspace_id=request.workspace_id,
                target_subject_id=request.target_subject_id,
                requester_id=request.requester_id,
                reason=request.reason,
                current_expires_at=request.current_expires_at,
                requested_expires_at=request.requested_expires_at,
                state=request.state.value,
                checker_id=request.checker_id,
                decision_reason=request.decision_reason,
                decision_policy_decision_id=request.decision_policy_decision_id,
                decided_at=request.decided_at,
                created_at=request.created_at,
                version=request.version,
            )
        )

    async def get_for_update(
        self, *, workspace_id: UUID, renewal_request_id: UUID
    ) -> MembershipRenewalRequest | None:
        model = (
            await self._session.scalars(
                select(MembershipRenewalRequestModel)
                .where(
                    MembershipRenewalRequestModel.workspace_id == workspace_id,
                    MembershipRenewalRequestModel.id == renewal_request_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        return _membership_renewal(model) if model is not None else None

    async def list_records(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID | None,
        state: str | None,
        limit: int,
        cursor: str | None = None,
    ) -> MembershipRenewalPage:
        _validate_admin_list_limit(limit)
        statement = (
            select(MembershipRenewalRequestModel)
            .where(MembershipRenewalRequestModel.workspace_id == workspace_id)
            .order_by(MembershipRenewalRequestModel.id.desc())
            .limit(limit + 1)
        )
        if subject_id is not None:
            statement = statement.where(
                MembershipRenewalRequestModel.target_subject_id == subject_id
            )
        if state is not None:
            statement = statement.where(MembershipRenewalRequestModel.state == state)
        filters = {
            "subject_id": str(subject_id) if subject_id is not None else None,
            "state": state,
        }
        if cursor is not None:
            boundary_id = decode_admin_list_cursor(
                cursor,
                scope="MEMBERSHIP_RENEWALS",
                workspace_id=workspace_id,
                filters=filters,
            )
            statement = statement.where(MembershipRenewalRequestModel.id < boundary_id)
        models = (await self._session.scalars(statement)).all()
        has_more = len(models) > limit
        visible_models = models[:limit]
        return MembershipRenewalPage(
            items=await self._records(visible_models),
            next_cursor=(
                encode_admin_list_cursor(
                    scope="MEMBERSHIP_RENEWALS",
                    workspace_id=workspace_id,
                    filters=filters,
                    boundary_id=visible_models[-1].id,
                )
                if has_more
                else None
            ),
        )

    async def get_record(
        self, *, workspace_id: UUID, renewal_request_id: UUID
    ) -> MembershipRenewalRecord | None:
        model = (
            await self._session.scalars(
                select(MembershipRenewalRequestModel).where(
                    MembershipRenewalRequestModel.workspace_id == workspace_id,
                    MembershipRenewalRequestModel.id == renewal_request_id,
                )
            )
        ).one_or_none()
        if model is None:
            return None
        records = await self._records([model])
        return records[0]

    async def _records(
        self, models: Sequence[MembershipRenewalRequestModel]
    ) -> tuple[MembershipRenewalRecord, ...]:
        if not models:
            return ()
        subject_ids = {
            value
            for model in models
            for value in (model.requester_id, model.checker_id)
            if value is not None
        }
        names: dict[UUID, str] = {
            subject_id: display_name
            for subject_id, display_name in (
                await self._session.execute(
                    select(SubjectModel.id, SubjectModel.display_name).where(
                        SubjectModel.id.in_(subject_ids)
                    )
                )
            ).all()
        }
        return tuple(
            MembershipRenewalRecord(
                renewal_request_id=model.id,
                workspace_id=model.workspace_id,
                target_subject_id=model.target_subject_id,
                requester_id=model.requester_id,
                requester_display_name=names.get(model.requester_id, str(model.requester_id)),
                reason=model.reason,
                current_expires_at=model.current_expires_at,
                requested_expires_at=model.requested_expires_at,
                state=model.state,
                version=model.version,
                created_at=model.created_at,
                checker_id=model.checker_id,
                checker_display_name=(names.get(model.checker_id) if model.checker_id else None),
                decision_reason=model.decision_reason,
                decided_at=model.decided_at,
            )
            for model in models
        )

    async def save(self, request: MembershipRenewalRequest) -> None:
        model = await self._session.get(MembershipRenewalRequestModel, request.renewal_request_id)
        if model is None or model.workspace_id != request.workspace_id:
            raise NotFoundError("The membership renewal request does not exist.")
        model.state = request.state.value
        model.checker_id = request.checker_id
        model.decision_reason = request.decision_reason
        model.decision_policy_decision_id = request.decision_policy_decision_id
        model.decided_at = request.decided_at
        model.version = request.version


def _membership_renewal(model: MembershipRenewalRequestModel) -> MembershipRenewalRequest:
    return MembershipRenewalRequest(
        renewal_request_id=model.id,
        workspace_id=model.workspace_id,
        target_subject_id=model.target_subject_id,
        requester_id=model.requester_id,
        reason=model.reason,
        current_expires_at=model.current_expires_at,
        requested_expires_at=model.requested_expires_at,
        state=MembershipRenewalState(model.state),
        version=model.version,
        created_at=model.created_at,
        checker_id=model.checker_id,
        decision_reason=model.decision_reason,
        decision_policy_decision_id=model.decision_policy_decision_id,
        decided_at=model.decided_at,
    )


def _encode_membership_cursor(
    *,
    workspace_id: UUID,
    query: str | None,
    active: bool | None,
    display_name: str,
    subject_id: UUID,
) -> str:
    payload = json.dumps(
        {
            "v": 1,
            "workspace_id": str(workspace_id),
            "query": query,
            "active": active,
            "display_name": display_name,
            "subject_id": str(subject_id),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_membership_cursor(
    cursor: str,
    *,
    workspace_id: UUID,
    query: str | None,
    active: bool | None,
) -> tuple[str, UUID]:
    try:
        if not cursor or len(cursor) > 2_000:
            raise ValueError
        payload = base64.b64decode(
            cursor + "=" * (-len(cursor) % 4),
            altchars=b"-_",
            validate=True,
        )
        document = json.loads(payload)
        if not isinstance(document, dict) or frozenset(document) != _MEMBERSHIP_CURSOR_KEYS:
            raise ValueError
        display_name = document.get("display_name")
        if (
            document.get("v") != 1
            or document.get("workspace_id") != str(workspace_id)
            or document.get("query") != query
            or document.get("active") is not active
            or not isinstance(display_name, str)
            or not display_name
        ):
            raise ValueError
        subject_id = UUID(str(document["subject_id"]))
        if cursor != _encode_membership_cursor(
            workspace_id=workspace_id,
            query=query,
            active=active,
            display_name=display_name,
            subject_id=subject_id,
        ):
            raise ValueError
        return display_name, subject_id
    except (
        ValueError,
        TypeError,
        KeyError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        binascii.Error,
    ) as error:
        raise ValidationError(
            "The membership cursor is stale or does not match this request."
        ) from error


class SqlMembershipAccessRepository(MembershipAccessRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(
        self,
        *,
        workspace_id: UUID,
        limit: int,
        query: str | None = None,
        active: bool | None = None,
        cursor: str | None = None,
    ) -> WorkspaceMembershipPage:
        _validate_admin_list_limit(limit)
        statement = (
            select(SubjectModel, WorkspaceMembershipModel)
            .join(
                WorkspaceMembershipModel,
                WorkspaceMembershipModel.subject_id == SubjectModel.id,
            )
            .where(WorkspaceMembershipModel.workspace_id == workspace_id)
            .order_by(func.lower(SubjectModel.display_name), SubjectModel.id)
            .limit(limit + 1)
        )
        if query is not None:
            escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped_query}%"
            statement = statement.where(
                or_(
                    SubjectModel.display_name.ilike(pattern, escape="\\"),
                    SubjectModel.email.ilike(pattern, escape="\\"),
                )
            )
        if active is not None:
            statement = statement.where(WorkspaceMembershipModel.active.is_(active))
        if cursor is not None:
            cursor_name, cursor_id = _decode_membership_cursor(
                cursor,
                workspace_id=workspace_id,
                query=query,
                active=active,
            )
            normalized_name = func.lower(SubjectModel.display_name)
            statement = statement.where(
                or_(
                    normalized_name > cursor_name,
                    and_(normalized_name == cursor_name, SubjectModel.id > cursor_id),
                )
            )
        rows = (await self._session.execute(statement)).all()
        if not rows:
            return WorkspaceMembershipPage(items=(), next_cursor=None)
        has_more = len(rows) > limit
        visible_rows = rows[:limit]
        subject_ids = [subject.id for subject, _ in visible_rows]
        pending_renewals: dict[UUID, UUID] = {
            subject_id: renewal_request_id
            for subject_id, renewal_request_id in (
                await self._session.execute(
                    select(
                        MembershipRenewalRequestModel.target_subject_id,
                        MembershipRenewalRequestModel.id,
                    ).where(
                        MembershipRenewalRequestModel.workspace_id == workspace_id,
                        MembershipRenewalRequestModel.target_subject_id.in_(subject_ids),
                        MembershipRenewalRequestModel.state == MembershipRenewalState.PENDING.value,
                    )
                )
            ).all()
        }
        change_request_ids: dict[UUID, set[UUID]] = {
            subject_id: set() for subject_id in subject_ids
        }
        for request_id, requester_id in (
            await self._session.execute(
                select(ChangeRequestModel.id, ChangeRequestModel.requester_id).where(
                    ChangeRequestModel.workspace_id == workspace_id,
                    ChangeRequestModel.requester_id.in_(subject_ids),
                )
            )
        ).all():
            change_request_ids[requester_id].add(request_id)
        for request_id, actor_id in (
            await self._session.execute(
                select(ApprovalModel.change_request_id, ApprovalModel.actor_id)
                .where(
                    ApprovalModel.workspace_id == workspace_id,
                    ApprovalModel.actor_id.in_(subject_ids),
                )
                .distinct()
            )
        ).all():
            change_request_ids[actor_id].add(request_id)
        owner_subjects = {
            f"urn:li:corpuser:{subject.external_subject}": subject.id for subject, _ in visible_rows
        }
        owned_table_counts = {subject_id: 0 for subject_id in subject_ids}
        if owner_subjects:
            for owner_ref, count in (
                await self._session.execute(
                    select(AssetProjectionModel.owner_ref, func.count())
                    .where(
                        AssetProjectionModel.workspace_id == workspace_id,
                        AssetProjectionModel.owner_ref.in_(owner_subjects),
                        AssetProjectionModel.asset_type == "TABLE",
                        AssetProjectionModel.lifecycle == "ACTIVE",
                        AssetProjectionModel.deleted_at.is_(None),
                    )
                    .group_by(AssetProjectionModel.owner_ref)
                )
            ).all():
                if owner_ref in owner_subjects:
                    owned_table_counts[owner_subjects[owner_ref]] = int(count)
        profile_assignments = {
            assignment.subject_id: assignment
            for assignment in (
                await self._session.scalars(
                    select(ProfileRoleAssignmentModel).where(
                        ProfileRoleAssignmentModel.workspace_id == workspace_id,
                        ProfileRoleAssignmentModel.subject_id.in_(subject_ids),
                    )
                )
            ).all()
        }
        canonical_rows = {
            binding.subject_id: (binding, role)
            for binding, role in (
                await self._session.execute(
                    select(CanonicalAdminBindingModel, AccessRoleModel)
                    .join(
                        AccessRoleModel,
                        and_(
                            AccessRoleModel.workspace_id == CanonicalAdminBindingModel.workspace_id,
                            AccessRoleModel.id == CanonicalAdminBindingModel.canonical_role_id,
                        ),
                    )
                    .where(
                        CanonicalAdminBindingModel.workspace_id == workspace_id,
                        CanonicalAdminBindingModel.subject_id.in_(subject_ids),
                    )
                )
            ).all()
        }

        def effective_profile_role(
            subject: SubjectModel, membership: WorkspaceMembershipModel
        ) -> str:
            binding_row = canonical_rows.get(subject.id)
            canonical_evidence = (
                _canonical_admin_binding_evidence(
                    subject=subject,
                    membership=membership,
                    binding=binding_row[0],
                    role=binding_row[1],
                )
                if binding_row is not None
                else None
            )
            return _effective_profile_role_label(
                _profile_role_assignment_evidence(
                    subject=subject,
                    membership=membership,
                    assignment=profile_assignments.get(subject.id),
                    canonical_admin_binding=canonical_evidence,
                )
            )

        items = tuple(
            _membership_summary(
                subject,
                membership,
                owned_table_count=owned_table_counts[subject.id],
                change_request_count=len(change_request_ids[subject.id]),
                pending_renewal_request_id=pending_renewals.get(subject.id),
                effective_profile_role=effective_profile_role(subject, membership),
            )
            for subject, membership in visible_rows
        )
        next_cursor = (
            _encode_membership_cursor(
                workspace_id=workspace_id,
                query=query,
                active=active,
                display_name=visible_rows[-1][0].display_name.lower(),
                subject_id=visible_rows[-1][0].id,
            )
            if has_more
            else None
        )
        return WorkspaceMembershipPage(items=items, next_cursor=next_cursor)

    async def get_access(
        self, *, workspace_id: UUID, subject_id: UUID
    ) -> WorkspaceMembershipAccessRecord | None:
        row = (
            await self._session.execute(
                select(SubjectModel, WorkspaceMembershipModel)
                .join(
                    WorkspaceMembershipModel,
                    WorkspaceMembershipModel.subject_id == SubjectModel.id,
                )
                .where(
                    WorkspaceMembershipModel.workspace_id == workspace_id,
                    WorkspaceMembershipModel.subject_id == subject_id,
                )
            )
        ).one_or_none()
        if row is None:
            return None
        subject, membership = row
        assignment = (
            await self._session.scalars(
                select(AccessRoleAssignmentModel).where(
                    AccessRoleAssignmentModel.workspace_id == workspace_id,
                    AccessRoleAssignmentModel.subject_id == subject_id,
                    AccessRoleAssignmentModel.active.is_(True),
                )
            )
        ).one_or_none()
        evidence = (
            MembershipRoleAssignmentEvidence(
                workspace_id=assignment.workspace_id,
                subject_id=assignment.subject_id,
                role_id=assignment.role_id,
                role_version=assignment.role_version,
                membership_version=assignment.membership_version,
                access_payload_hash=assignment.access_payload_hash,
                assigned_by=assignment.assigned_by,
                assignment_version=assignment.version,
                updated_at=assignment.updated_at,
            )
            if assignment is not None
            else None
        )
        binding = await self._session.get(
            CanonicalAdminBindingModel,
            {"workspace_id": workspace_id, "subject_id": subject_id},
        )
        canonical_evidence: CanonicalAdminBindingEvidence | None = None
        if binding is not None:
            canonical_role = (
                await self._session.scalars(
                    select(AccessRoleModel).where(
                        AccessRoleModel.workspace_id == workspace_id,
                        AccessRoleModel.id == binding.canonical_role_id,
                    )
                )
            ).one_or_none()
            canonical_evidence = _canonical_admin_binding_evidence(
                subject=subject,
                membership=membership,
                binding=binding,
                role=canonical_role,
            )
        profile_assignment = await self._session.get(
            ProfileRoleAssignmentModel,
            {"workspace_id": workspace_id, "subject_id": subject_id},
        )
        profile_evidence = _profile_role_assignment_evidence(
            subject=subject,
            membership=membership,
            assignment=profile_assignment,
            canonical_admin_binding=canonical_evidence,
        )
        return _membership_access_record(
            subject,
            membership,
            role_assignment=evidence,
            canonical_admin_binding=canonical_evidence,
            profile_role=profile_evidence,
        )

    async def assert_assignable_human_role(self, *, workspace_id: UUID, role_id: UUID) -> None:
        role = (
            await self._session.scalars(
                select(AccessRoleModel).where(
                    AccessRoleModel.workspace_id == workspace_id,
                    AccessRoleModel.id == role_id,
                    AccessRoleModel.active.is_(True),
                )
            )
        ).one_or_none()
        if role is None:
            raise ValidationError("The active access role does not exist in this workspace.")
        if role.role_kind != AccessRoleKind.HUMAN_ROLE.value:
            raise ValidationError("Canonical Admin cannot be assigned through a generic Role path.")

    async def get_identity_profile_target(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        for_update: bool = False,
    ) -> IdentityProfileTarget | None:
        statement = (
            select(SubjectModel, WorkspaceMembershipModel)
            .join(
                WorkspaceMembershipModel,
                WorkspaceMembershipModel.subject_id == SubjectModel.id,
            )
            .where(
                WorkspaceMembershipModel.workspace_id == workspace_id,
                WorkspaceMembershipModel.subject_id == subject_id,
            )
        )
        if for_update:
            statement = statement.with_for_update()
        row = (await self._session.execute(statement)).one_or_none()
        if row is None:
            return None
        subject, membership = row
        return IdentityProfileTarget(
            subject_id=subject.id,
            workspace_id=membership.workspace_id,
            issuer=subject.issuer,
            external_subject=subject.external_subject,
            display_name=subject.display_name,
            email=subject.email,
            department_id=membership.department_id,
            job_function=membership.job_function,
            membership_version=membership.version,
            subject_active=subject.active,
            membership_active=membership.active,
            service_account=(
                membership.job_function == "SERVICE_ACCOUNT"
                or "service-accounts" in (_string_set(membership.attributes, "groups") or set())
            ),
            access_expires_at=membership.access_expires_at,
        )

    async def update_identity_profile(
        self,
        *,
        target: IdentityProfileTarget,
        expected_membership_version: int,
        display_name: str,
        email: str,
        department_id: UUID | None,
        job_function: str | None,
    ) -> int:
        try:
            next_version = await self._session.scalar(
                text(
                    """
                    SELECT iam.update_workspace_identity_profile(
                        :workspace_id, :subject_id, :expected_membership_version,
                        :display_name, :email, :department_id, :job_function
                    )
                    """
                ),
                {
                    "workspace_id": target.workspace_id,
                    "subject_id": target.subject_id,
                    "expected_membership_version": expected_membership_version,
                    "display_name": display_name,
                    "email": email,
                    "department_id": department_id,
                    "job_function": job_function,
                },
            )
        except DBAPIError as error:
            sqlstate = getattr(error.orig, "sqlstate", None)
            if sqlstate == "42501":
                raise ForbiddenError("Identity profile administration lost authority.") from error
            if sqlstate == "P0002":
                raise NotFoundError("The target workspace identity does not exist.") from error
            if sqlstate == "40001":
                raise ConflictError(
                    "The target workspace identity changed during the operation."
                ) from error
            if sqlstate == "23514":
                raise ValidationError("The identity profile update violates policy.") from error
            raise
        if not isinstance(next_version, int) or next_version <= expected_membership_version:
            raise ConflictError("The identity profile update returned invalid evidence.")
        return next_version

    async def list_change_request_activity(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        limit: int,
        cursor: str | None = None,
    ) -> MembershipChangeRequestActivityPage:
        _validate_admin_list_limit(limit)
        if not await self._session.scalar(
            select(WorkspaceMembershipModel.subject_id).where(
                WorkspaceMembershipModel.workspace_id == workspace_id,
                WorkspaceMembershipModel.subject_id == subject_id,
            )
        ):
            raise NotFoundError("The target workspace membership does not exist.")
        participated = or_(
            ChangeRequestModel.requester_id == subject_id,
            exists(
                select(ApprovalModel.id).where(
                    ApprovalModel.workspace_id == workspace_id,
                    ApprovalModel.change_request_id == ChangeRequestModel.id,
                    ApprovalModel.actor_id == subject_id,
                )
            ),
        )
        statement = (
            select(ChangeRequestModel)
            .where(
                ChangeRequestModel.workspace_id == workspace_id,
                participated,
            )
            .order_by(ChangeRequestModel.id.desc())
            .limit(limit + 1)
        )
        filters = {"subject_id": str(subject_id)}
        if cursor is not None:
            boundary_id = decode_admin_list_cursor(
                cursor,
                scope="MEMBERSHIP_CHANGE_REQUEST_ACTIVITY",
                workspace_id=workspace_id,
                filters=filters,
            )
            statement = statement.where(ChangeRequestModel.id < boundary_id)
        models = list((await self._session.scalars(statement)).all())
        has_more = len(models) > limit
        visible = models[:limit]
        approved_ids = frozenset(
            (
                await self._session.scalars(
                    select(ApprovalModel.change_request_id)
                    .where(
                        ApprovalModel.workspace_id == workspace_id,
                        ApprovalModel.actor_id == subject_id,
                        ApprovalModel.change_request_id.in_([item.id for item in visible]),
                    )
                    .distinct()
                )
            ).all()
        )
        return MembershipChangeRequestActivityPage(
            items=tuple(
                MembershipChangeRequestActivity(
                    change_request_id=item.id,
                    number=item.number,
                    title=item.title,
                    request_type=item.request_type,
                    state=item.state,
                    relationship=(
                        "REQUESTER_AND_APPROVER"
                        if item.requester_id == subject_id and item.id in approved_ids
                        else "REQUESTER"
                        if item.requester_id == subject_id
                        else "APPROVER"
                    ),
                    classification=Classification(item.classification),
                    requester_id=item.requester_id,
                    updated_at=item.updated_at,
                )
                for item in visible
            ),
            next_cursor=(
                encode_admin_list_cursor(
                    scope="MEMBERSHIP_CHANGE_REQUEST_ACTIVITY",
                    workspace_id=workspace_id,
                    filters=filters,
                    boundary_id=visible[-1].id,
                )
                if has_more and visible
                else None
            ),
        )

    async def list_owned_tables(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        limit: int,
        cursor: str | None = None,
    ) -> MembershipOwnedTablePage:
        _validate_admin_list_limit(limit)
        external_subject = await self._session.scalar(
            select(SubjectModel.external_subject)
            .join(
                WorkspaceMembershipModel,
                and_(
                    WorkspaceMembershipModel.workspace_id == workspace_id,
                    WorkspaceMembershipModel.subject_id == SubjectModel.id,
                ),
            )
            .where(SubjectModel.id == subject_id)
        )
        if external_subject is None:
            raise NotFoundError("The target workspace membership does not exist.")
        statement = (
            select(AssetProjectionModel)
            .where(
                AssetProjectionModel.workspace_id == workspace_id,
                AssetProjectionModel.owner_ref == f"urn:li:corpuser:{external_subject}",
                AssetProjectionModel.asset_type == "TABLE",
                AssetProjectionModel.lifecycle == "ACTIVE",
                AssetProjectionModel.deleted_at.is_(None),
            )
            .order_by(AssetProjectionModel.id.desc())
            .limit(limit + 1)
        )
        filters = {"subject_id": str(subject_id)}
        if cursor is not None:
            boundary_id = decode_admin_list_cursor(
                cursor,
                scope="MEMBERSHIP_OWNED_TABLES",
                workspace_id=workspace_id,
                filters=filters,
            )
            statement = statement.where(AssetProjectionModel.id < boundary_id)
        models = list((await self._session.scalars(statement)).all())
        has_more = len(models) > limit
        visible = models[:limit]
        return MembershipOwnedTablePage(
            items=tuple(
                MembershipOwnedTable(
                    asset_id=item.id,
                    name=item.name,
                    platform=item.platform,
                    database_name=item.database_name,
                    schema_name=item.schema_name,
                    classification=Classification(item.classification),
                    system_id=item.system_id,
                    domain_id=item.domain_id,
                    owner_department_id=item.owner_department_id,
                    source_version=item.source_version,
                    observed_at=item.observed_at,
                )
                for item in visible
            ),
            next_cursor=(
                encode_admin_list_cursor(
                    scope="MEMBERSHIP_OWNED_TABLES",
                    workspace_id=workspace_id,
                    filters=filters,
                    boundary_id=visible[-1].id,
                )
                if has_more and visible
                else None
            ),
        )

    async def provision_identity_membership(
        self,
        *,
        subject_id: UUID,
        workspace_id: UUID,
        issuer: str,
        external_subject: str,
        username: str,
        display_name: str,
        email: str,
        department_id: UUID | None,
        job_function: str | None,
        role_id: UUID | None,
        access_expires_at: datetime,
        assurance: str,
        policy_decision_id: UUID,
    ) -> ProvisionedWorkspaceUser:
        try:
            stored_subject_id = await self._session.scalar(
                text(
                    """
                    SELECT iam.provision_workspace_identity(
                        :subject_id, :workspace_id, :issuer, :external_subject,
                        :display_name, :email, :department_id, :job_function,
                        :role_id, :access_expires_at, :assurance, :policy_decision_id
                    )
                    """
                ),
                {
                    "subject_id": subject_id,
                    "workspace_id": workspace_id,
                    "issuer": issuer,
                    "external_subject": external_subject,
                    "display_name": display_name,
                    "email": email,
                    "department_id": department_id,
                    "job_function": job_function,
                    "role_id": role_id,
                    "access_expires_at": access_expires_at,
                    "assurance": assurance,
                    "policy_decision_id": policy_decision_id,
                },
            )
        except DBAPIError as error:
            sqlstate = getattr(error.orig, "sqlstate", None)
            if sqlstate == "42501":
                raise ForbiddenError(
                    "Identity provisioning lost administrator authority."
                ) from error
            if sqlstate in {"23503", "23505"}:
                raise ConflictError(
                    "The identity or selected role changed during provisioning."
                ) from error
            if sqlstate == "23514":
                raise ValidationError(
                    "The identity provisioning request violates policy."
                ) from error
            raise
        if stored_subject_id != subject_id:
            raise ConflictError("The provisioned identity does not match the requested subject.")
        return ProvisionedWorkspaceUser(
            subject_id=subject_id,
            external_subject=external_subject,
            username=username,
            display_name=display_name,
            email=email,
            workspace_id=workspace_id,
            role_id=None,
            access_expires_at=access_expires_at,
        )

    async def apply(self, command: MembershipAccessUpdate) -> int:
        membership = await self._membership_for_update(command)
        profile_assignment = (
            await self._session.scalars(
                select(ProfileRoleAssignmentModel)
                .where(
                    ProfileRoleAssignmentModel.workspace_id == command.workspace_id,
                    ProfileRoleAssignmentModel.subject_id == command.target_subject_id,
                    ProfileRoleAssignmentModel.state == "ACTIVE",
                )
                .with_for_update()
            )
        ).one_or_none()
        if profile_assignment is not None:
            try:
                profile_policy = PROFILE_ROLE_BY_TIER[ProfileRoleTier(profile_assignment.tier)]
            except (KeyError, ValueError) as error:
                raise ConflictError("The active profile Role evidence is malformed.") from error
            current_groups = _string_set(membership.attributes, "groups")
            current_denied = _string_set(membership.attributes, "denied_actions")
            current_domains = _string_set(membership.attributes, "allowed_domain_ids")
            if current_groups is None or current_denied is None or current_domains is None:
                raise ConflictError("The profile-bound membership access is malformed.")
            try:
                current_denied_actions = frozenset(Action(value) for value in current_denied)
                current_domain_ids = frozenset(UUID(value) for value in current_domains)
            except ValueError as error:
                raise ConflictError("The profile-bound membership access is malformed.") from error
            if (
                profile_assignment.policy_version != PROFILE_ROLE_POLICY_VERSION
                or profile_assignment.materialized_actions_hash
                != profile_policy.materialized_actions_hash
                or profile_assignment.membership_version != membership.version
                or profile_policy.tier is ProfileRoleTier.ADMIN
                or not command.active
                or command.groups != frozenset(current_groups)
                or command.allowed_actions != profile_policy.allowed_actions
                or command.denied_actions != current_denied_actions
                or command.allowed_system_ids
                or command.allowed_domain_ids != current_domain_ids
            ):
                raise ValidationError(
                    "A profile-bound membership update may change only its data clearance."
                )
        membership.active = command.active
        membership.clearance = int(command.clearance)
        membership.attributes = {
            "groups": sorted(command.groups),
            "allowed_actions": sorted(action.value for action in command.allowed_actions),
            "denied_actions": sorted(action.value for action in command.denied_actions),
            "allowed_system_ids": sorted(str(value) for value in command.allowed_system_ids),
            "allowed_domain_ids": sorted(str(value) for value in command.allowed_domain_ids),
            "managed_by": MEMBERSHIP_ACCESS_COMMAND,
        }
        membership.version += 1
        if profile_assignment is not None:
            profile_assignment.membership_version = membership.version
        await self._session.flush()
        administrator_count = await self._session.scalar(
            select(func.count())
            .select_from(WorkspaceMembershipModel)
            .join(SubjectModel, SubjectModel.id == WorkspaceMembershipModel.subject_id)
            .where(
                WorkspaceMembershipModel.workspace_id == command.workspace_id,
                SubjectModel.active.is_(True),
                WorkspaceMembershipModel.active.is_(True),
                or_(
                    WorkspaceMembershipModel.access_expires_at.is_(None),
                    WorkspaceMembershipModel.access_expires_at > func.now(),
                ),
                or_(
                    WorkspaceMembershipModel.job_function.is_(None),
                    WorkspaceMembershipModel.job_function != "SERVICE_ACCOUNT",
                ),
                WorkspaceMembershipModel.clearance >= int(Classification.RESTRICTED),
                func.jsonb_path_exists(
                    WorkspaceMembershipModel.attributes,
                    cast(
                        '$.groups[*] ? (@ == "security-administrators")',
                        postgresql.JSONPATH,
                    ),
                ),
                ~func.jsonb_path_exists(
                    WorkspaceMembershipModel.attributes,
                    cast('$.groups[*] ? (@ == "service-accounts")', postgresql.JSONPATH),
                ),
                func.jsonb_path_exists(
                    WorkspaceMembershipModel.attributes,
                    cast(
                        '$.allowed_actions[*] ? (@ == "admin.manage")',
                        postgresql.JSONPATH,
                    ),
                ),
                ~func.jsonb_path_exists(
                    WorkspaceMembershipModel.attributes,
                    cast(
                        '$.denied_actions[*] ? (@ == "admin.manage")',
                        postgresql.JSONPATH,
                    ),
                ),
            )
        )
        if int(administrator_count or 0) < 2:
            raise ConflictError(
                "At least two active security administrators must remain in the workspace."
            )
        return membership.version

    async def record_role_assignment(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        role_id: UUID | None,
        role_version: int | None,
        role_marker: str | None,
        membership_version: int,
        access_payload_hash: str,
        actor_id: UUID,
    ) -> None:
        current = (
            await self._session.scalars(
                select(AccessRoleAssignmentModel)
                .where(
                    AccessRoleAssignmentModel.workspace_id == workspace_id,
                    AccessRoleAssignmentModel.subject_id == subject_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        previous_role_id = current.role_id if current is not None and current.active else None
        previous_role_version = (
            current.role_version if current is not None and current.active else None
        )
        if role_id is None:
            if role_marker is not None:
                raise ValidationError("A Role removal cannot retain a reserved role marker.")
            if current is None or not current.active:
                return
            current.active = False
            current.membership_version = membership_version
            current.access_payload_hash = access_payload_hash
            current.assigned_by = actor_id
            current.version += 1
            event_type = "REMOVED"
        else:
            if role_version is None:
                raise ValidationError("A role assignment requires an exact role version.")
            role = (
                await self._session.scalars(
                    select(AccessRoleModel)
                    .where(
                        AccessRoleModel.workspace_id == workspace_id,
                        AccessRoleModel.id == role_id,
                        AccessRoleModel.version == role_version,
                        AccessRoleModel.active.is_(True),
                        AccessRoleModel.role_kind == AccessRoleKind.HUMAN_ROLE.value,
                    )
                    .with_for_update()
                )
            ).one_or_none()
            if role is None:
                raise ConflictError("The selected access role changed before assignment.")
            if role.role_kind != AccessRoleKind.HUMAN_ROLE.value:
                raise ValidationError("Canonical Admin cannot be assigned through a generic path.")
            if role_marker != f"datariver-role-{role.role_key}":
                raise ConflictError("The membership role marker does not match the selected role.")
            if (
                current is not None
                and current.active
                and current.role_id == role_id
                and current.role_version == role_version
                and current.access_payload_hash == access_payload_hash
            ):
                raise ConflictError("The membership already has this exact access role.")
            event_type = "REASSIGNED" if previous_role_id is not None else "ASSIGNED"
            if current is None:
                current = AccessRoleAssignmentModel(
                    workspace_id=workspace_id,
                    subject_id=subject_id,
                    role_id=role_id,
                    role_kind=AccessRoleKind.HUMAN_ROLE.value,
                    role_version=role_version,
                    membership_version=membership_version,
                    access_payload_hash=access_payload_hash,
                    assigned_by=actor_id,
                    active=True,
                )
                self._session.add(current)
            else:
                current.role_id = role_id
                current.role_version = role_version
                current.membership_version = membership_version
                current.access_payload_hash = access_payload_hash
                current.assigned_by = actor_id
                current.active = True
                current.version += 1
        self._session.add(
            AccessRoleAssignmentEventModel(
                workspace_id=workspace_id,
                subject_id=subject_id,
                event_type=event_type,
                previous_role_id=previous_role_id,
                previous_role_version=previous_role_version,
                role_id=role_id,
                role_version=role_version,
                membership_version=membership_version,
                access_payload_hash=access_payload_hash,
                actor_id=actor_id,
            )
        )
        await self._session.flush()

    async def assert_current_version(self, command: MembershipAccessUpdate) -> None:
        await self._membership_for_update(command)

    async def assert_manual_access_update_allowed(
        self, *, workspace_id: UUID, subject_id: UUID
    ) -> None:
        membership = (
            await self._session.scalars(
                select(WorkspaceMembershipModel)
                .where(
                    WorkspaceMembershipModel.workspace_id == workspace_id,
                    WorkspaceMembershipModel.subject_id == subject_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        if membership is None:
            raise NotFoundError("The workspace membership does not exist.")
        groups = _string_set(membership.attributes, "groups")
        if groups is None:
            raise ConflictError("The workspace membership access document is malformed.")
        assignment = (
            await self._session.scalars(
                select(AccessRoleAssignmentModel)
                .where(
                    AccessRoleAssignmentModel.workspace_id == workspace_id,
                    AccessRoleAssignmentModel.subject_id == subject_id,
                    AccessRoleAssignmentModel.active.is_(True),
                )
                .with_for_update()
            )
        ).one_or_none()
        if assignment is not None or any(group.startswith("datariver-role-") for group in groups):
            raise ConflictError(
                "Role-bound access must be changed through the dedicated Role assignment route."
            )
        canonical_binding = await self._session.get(
            CanonicalAdminBindingModel,
            {"workspace_id": workspace_id, "subject_id": subject_id},
        )
        if canonical_binding is not None and canonical_binding.state == "ACTIVE":
            raise ConflictError(
                "Canonical Admin access must be changed through the protected profile route."
            )

    async def apply_profile_role(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        tier: str,
        expected_membership_version: int,
        reason: str,
        assurance: str,
        access_payload_hash: str,
        policy_decision_id: UUID,
    ) -> ProfileRoleTransitionResult:
        try:
            row = (
                await self._session.execute(
                    text(
                        """
                        SELECT membership_version, assignment_version
                        FROM iam.assign_profile_role(
                            :workspace_id, :subject_id, :tier,
                            :expected_membership_version, :reason, :assurance,
                            :access_payload_hash, :policy_decision_id
                        )
                        """
                    ),
                    {
                        "workspace_id": workspace_id,
                        "subject_id": subject_id,
                        "tier": tier,
                        "expected_membership_version": expected_membership_version,
                        "reason": reason,
                        "assurance": assurance,
                        "access_payload_hash": access_payload_hash,
                        "policy_decision_id": policy_decision_id,
                    },
                )
            ).one()
        except DBAPIError as error:
            _raise_profile_role_database_error(error)
            raise
        return ProfileRoleTransitionResult(
            subject_id=subject_id,
            tier=tier,
            membership_version=int(row.membership_version),
            assignment_version=int(row.assignment_version),
        )

    async def transition_canonical_admin_profile(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
        tier: str,
        expected_membership_version: int,
        expected_binding_version: int,
        reason: str,
        assurance: str,
        access_payload_hash: str,
        policy_decision_id: UUID,
    ) -> ProfileRoleTransitionResult:
        try:
            row = (
                await self._session.execute(
                    text(
                        """
                        SELECT membership_version, assignment_version, binding_version
                        FROM iam.transition_canonical_admin_profile(
                            :workspace_id, :subject_id, :tier,
                            :expected_membership_version, :expected_binding_version,
                            :reason, :assurance, :access_payload_hash, :policy_decision_id
                        )
                        """
                    ),
                    {
                        "workspace_id": workspace_id,
                        "subject_id": subject_id,
                        "tier": tier,
                        "expected_membership_version": expected_membership_version,
                        "expected_binding_version": expected_binding_version,
                        "reason": reason,
                        "assurance": assurance,
                        "access_payload_hash": access_payload_hash,
                        "policy_decision_id": policy_decision_id,
                    },
                )
            ).one()
        except DBAPIError as error:
            _raise_profile_role_database_error(error)
            raise
        return ProfileRoleTransitionResult(
            subject_id=subject_id,
            tier=tier,
            membership_version=int(row.membership_version),
            assignment_version=int(row.assignment_version),
            binding_version=int(row.binding_version),
        )

    async def count_verified_canonical_admins(self, *, workspace_id: UUID) -> int:
        rows = (
            await self._session.execute(
                select(
                    SubjectModel,
                    WorkspaceMembershipModel,
                    CanonicalAdminBindingModel,
                    AccessRoleModel,
                )
                .join(
                    WorkspaceMembershipModel,
                    WorkspaceMembershipModel.subject_id == SubjectModel.id,
                )
                .join(
                    CanonicalAdminBindingModel,
                    and_(
                        CanonicalAdminBindingModel.workspace_id
                        == WorkspaceMembershipModel.workspace_id,
                        CanonicalAdminBindingModel.subject_id
                        == WorkspaceMembershipModel.subject_id,
                    ),
                )
                .join(
                    AccessRoleModel,
                    and_(
                        AccessRoleModel.workspace_id == CanonicalAdminBindingModel.workspace_id,
                        AccessRoleModel.id == CanonicalAdminBindingModel.canonical_role_id,
                    ),
                )
                .where(
                    WorkspaceMembershipModel.workspace_id == workspace_id,
                    CanonicalAdminBindingModel.state == "ACTIVE",
                )
            )
        ).all()
        return sum(
            _canonical_admin_binding_evidence(
                subject=target_subject,
                membership=membership,
                binding=binding,
                role=role,
            ).status
            == "VERIFIED"
            for target_subject, membership, binding, role in rows
        )

    async def get_expiration_for_update(self, *, workspace_id: UUID, subject_id: UUID) -> datetime:
        membership = (
            await self._session.scalars(
                select(WorkspaceMembershipModel)
                .where(
                    WorkspaceMembershipModel.workspace_id == workspace_id,
                    WorkspaceMembershipModel.subject_id == subject_id,
                    WorkspaceMembershipModel.active.is_(True),
                    WorkspaceMembershipModel.job_function != "SERVICE_ACCOUNT",
                )
                .with_for_update()
            )
        ).one_or_none()
        if membership is None or membership.access_expires_at is None:
            raise ForbiddenError("A renewable human workspace membership is not available.")
        return membership.access_expires_at

    async def extend_expiration(
        self, *, workspace_id: UUID, subject_id: UUID, expected: datetime, extended: datetime
    ) -> int:
        membership = (
            await self._session.scalars(
                select(WorkspaceMembershipModel)
                .where(
                    WorkspaceMembershipModel.workspace_id == workspace_id,
                    WorkspaceMembershipModel.subject_id == subject_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        if membership is None or membership.access_expires_at != expected:
            raise ConflictError("The workspace membership expiration changed.")
        if extended <= expected:
            raise ValidationError("The renewed membership expiration must increase.")
        membership.access_expires_at = extended
        membership.version += 1
        await self._session.flush()
        return membership.version

    async def _membership_for_update(
        self, command: MembershipAccessUpdate
    ) -> WorkspaceMembershipModel:
        membership = (
            await self._session.scalars(
                select(WorkspaceMembershipModel)
                .where(
                    WorkspaceMembershipModel.workspace_id == command.workspace_id,
                    WorkspaceMembershipModel.subject_id == command.target_subject_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        if membership is None:
            raise NotFoundError("The target workspace membership does not exist.")
        if membership.version != command.expected_membership_version:
            raise ConflictError(
                "The target membership was modified by another operation.",
                details={
                    "expected": command.expected_membership_version,
                    "actual": membership.version,
                },
            )
        return membership

    async def assert_eligible_human_administrators(
        self, *, workspace_id: UUID, subject_ids: frozenset[UUID]
    ) -> None:
        if not subject_ids:
            raise ForbiddenError("At least one administrator identity is required.")
        rows = (
            await self._session.execute(
                select(SubjectModel, WorkspaceMembershipModel)
                .join(
                    WorkspaceMembershipModel,
                    WorkspaceMembershipModel.subject_id == SubjectModel.id,
                )
                .where(
                    WorkspaceMembershipModel.workspace_id == workspace_id,
                    WorkspaceMembershipModel.subject_id.in_(subject_ids),
                )
                .order_by(WorkspaceMembershipModel.subject_id)
                .with_for_update(of=WorkspaceMembershipModel)
            )
        ).all()
        if len(rows) != len(subject_ids):
            raise ForbiddenError("An administrator membership is no longer available.")
        for subject, membership in rows:
            attributes = membership.attributes
            groups = _string_set(attributes, "groups")
            allowed = _string_set(attributes, "allowed_actions")
            denied = _string_set(attributes, "denied_actions")
            if (
                groups is None
                or allowed is None
                or denied is None
                or not subject.active
                or not membership.active
                or (
                    membership.access_expires_at is not None
                    and membership.access_expires_at <= utc_now()
                )
                or membership.job_function == "SERVICE_ACCOUNT"
                or "service-accounts" in groups
                or "security-administrators" not in groups
                or Action.ADMIN_MANAGE.value not in allowed
                or Action.ADMIN_MANAGE.value in denied
                or membership.clearance < int(Classification.RESTRICTED)
            ):
                raise ForbiddenError("An administrator is no longer eligible for this workflow.")


class SqlSystemDirectoryRepository(SystemDirectoryRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def code_exists(self, *, workspace_id: UUID, code: str) -> bool:
        return bool(
            await self._session.scalar(
                select(
                    exists().where(
                        DataSystemModel.workspace_id == workspace_id,
                        func.lower(DataSystemModel.code) == code.casefold(),
                    )
                )
            )
        )

    @staticmethod
    def _schema_scope_asset_conditions(
        *,
        workspace_id: UUID,
        system_id: UUID,
        subject: SubjectAttributes,
    ) -> tuple[Any, ...]:
        if (
            not subject.active
            or subject.workspace_id != workspace_id
            or subject.job_function == "SERVICE_ACCOUNT"
            or "service-accounts" in subject.groups
        ):
            raise ForbiddenError("An active human administrator is required.")
        return (
            AssetProjectionModel.workspace_id == workspace_id,
            AssetProjectionModel.asset_type.in_(tuple(DATASET_ASSET_TYPES)),
            AssetProjectionModel.lifecycle == "ACTIVE",
            AssetProjectionModel.deleted_at.is_(None),
            AssetProjectionModel.platform.is_not(None),
            AssetProjectionModel.database_name.is_not(None),
            AssetProjectionModel.schema_name.is_not(None),
            or_(
                AssetProjectionModel.classification == int(Classification.PUBLIC),
                and_(
                    AssetProjectionModel.classification.in_(
                        (
                            int(Classification.INTERNAL),
                            int(Classification.CONFIDENTIAL),
                        )
                    ),
                    AssetProjectionModel.classification <= int(subject.clearance),
                    AssetProjectionModel.domain_id.is_not(None),
                    AssetProjectionModel.domain_id.in_(subject.allowed_domain_ids),
                ),
            ),
            or_(
                AssetProjectionModel.system_id.is_(None),
                AssetProjectionModel.system_id == system_id,
            ),
        )

    async def list(
        self,
        *,
        workspace_id: UUID,
        limit: int,
        query: str | None = None,
        active: bool | None = None,
        cursor: str | None = None,
    ) -> SystemDirectoryPage:
        _validate_admin_list_limit(limit)
        assignment_count = (
            select(func.count(SystemAssigneeModel.id))
            .where(
                SystemAssigneeModel.workspace_id == workspace_id,
                SystemAssigneeModel.system_id == DataSystemModel.id,
            )
            .correlate(DataSystemModel)
            .scalar_subquery()
        )
        statement = (
            select(DataSystemModel, assignment_count)
            .where(DataSystemModel.workspace_id == workspace_id)
            .order_by(DataSystemModel.id.desc())
            .limit(limit + 1)
        )
        if query is not None:
            escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped_query}%"
            statement = statement.where(
                or_(
                    DataSystemModel.name.ilike(pattern, escape="\\"),
                    DataSystemModel.code.ilike(pattern, escape="\\"),
                )
            )
        if active is not None:
            statement = statement.where(DataSystemModel.active.is_(active))
        filters = {"query": query, "active": active}
        if cursor is not None:
            boundary_id = decode_admin_list_cursor(
                cursor,
                scope="SYSTEM_DIRECTORY",
                workspace_id=workspace_id,
                filters=filters,
            )
            statement = statement.where(DataSystemModel.id < boundary_id)
        system_rows = (await self._session.execute(statement)).all()
        has_more = len(system_rows) > limit
        systems = system_rows[:limit]
        if not systems:
            return SystemDirectoryPage(items=(), next_cursor=None)
        return SystemDirectoryPage(
            items=tuple(
                SystemDirectoryEntry(
                    system_id=system.id,
                    code=system.code,
                    name=system.name,
                    description=system.description,
                    active=system.active,
                    version=system.version,
                    assignee_count=int(count),
                )
                for system, count in systems
            ),
            next_cursor=(
                encode_admin_list_cursor(
                    scope="SYSTEM_DIRECTORY",
                    workspace_id=workspace_id,
                    filters=filters,
                    boundary_id=systems[-1][0].id,
                )
                if has_more
                else None
            ),
        )

    async def list_assignees(
        self,
        *,
        workspace_id: UUID,
        system_id: UUID,
        limit: int,
        cursor: str | None = None,
    ) -> SystemAssigneePage:
        _validate_admin_list_limit(limit)
        system = (
            await self._session.scalars(
                select(DataSystemModel)
                .where(
                    DataSystemModel.workspace_id == workspace_id,
                    DataSystemModel.id == system_id,
                )
                .with_for_update(read=True)
            )
        ).one_or_none()
        if system is None:
            raise NotFoundError("The data system does not exist.")
        filters: dict[str, str | bool | None] = {
            "system_id": str(system_id),
            "system_version": str(system.version),
        }
        statement = (
            select(SystemAssigneeModel, SubjectModel, WorkspaceMembershipModel)
            .join(SubjectModel, SubjectModel.id == SystemAssigneeModel.subject_id)
            .join(
                WorkspaceMembershipModel,
                and_(
                    WorkspaceMembershipModel.workspace_id == SystemAssigneeModel.workspace_id,
                    WorkspaceMembershipModel.subject_id == SystemAssigneeModel.subject_id,
                ),
            )
            .where(
                SystemAssigneeModel.workspace_id == workspace_id,
                SystemAssigneeModel.system_id == system_id,
                SystemAssigneeModel.active.is_(True),
            )
            .order_by(SystemAssigneeModel.id.desc())
            .limit(limit + 1)
        )
        if cursor is not None:
            boundary_id = decode_admin_list_cursor(
                cursor,
                scope="SYSTEM_ASSIGNEES",
                workspace_id=workspace_id,
                filters=filters,
            )
            statement = statement.where(SystemAssigneeModel.id < boundary_id)
        rows = (await self._session.execute(statement)).all()
        has_more = len(rows) > limit
        visible_rows = rows[:limit]
        return SystemAssigneePage(
            items=tuple(
                SystemDirectoryAssignee(
                    subject_id=subject.id,
                    display_name=subject.display_name,
                    responsibility=assignment.responsibility,
                    priority=assignment.priority,
                    active=(
                        assignment.active
                        and subject.active
                        and membership.active
                        and (
                            membership.access_expires_at is None
                            or membership.access_expires_at > utc_now()
                        )
                    ),
                )
                for assignment, subject, membership in visible_rows
            ),
            system_version=system.version,
            next_cursor=(
                encode_admin_list_cursor(
                    scope="SYSTEM_ASSIGNEES",
                    workspace_id=workspace_id,
                    filters=filters,
                    boundary_id=visible_rows[-1][0].id,
                )
                if has_more
                else None
            ),
        )

    async def list_assignee_candidates(
        self,
        *,
        workspace_id: UUID,
        limit: int,
        query: str | None = None,
        cursor: str | None = None,
    ) -> SystemAssigneeCandidatePage:
        _validate_admin_list_limit(limit)
        scan_limit = min(500, limit * 5 + 1)
        statement = (
            select(SubjectModel, WorkspaceMembershipModel)
            .join(
                WorkspaceMembershipModel,
                WorkspaceMembershipModel.subject_id == SubjectModel.id,
            )
            .where(
                WorkspaceMembershipModel.workspace_id == workspace_id,
                WorkspaceMembershipModel.active.is_(True),
                SubjectModel.active.is_(True),
                or_(
                    WorkspaceMembershipModel.access_expires_at.is_(None),
                    WorkspaceMembershipModel.access_expires_at > func.now(),
                ),
                or_(
                    WorkspaceMembershipModel.job_function.is_(None),
                    WorkspaceMembershipModel.job_function != "SERVICE_ACCOUNT",
                ),
            )
            .order_by(func.lower(SubjectModel.display_name), SubjectModel.id)
            .limit(scan_limit)
        )
        if query is not None:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            statement = statement.where(
                or_(
                    SubjectModel.display_name.ilike(pattern, escape="\\"),
                    SubjectModel.email.ilike(pattern, escape="\\"),
                )
            )
        if cursor is not None:
            cursor_name, cursor_id = _decode_membership_cursor(
                cursor,
                workspace_id=workspace_id,
                query=query,
                active=True,
            )
            normalized_name = func.lower(SubjectModel.display_name)
            statement = statement.where(
                or_(
                    normalized_name > cursor_name,
                    and_(normalized_name == cursor_name, SubjectModel.id > cursor_id),
                )
            )
        rows = (await self._session.execute(statement)).all()
        candidates: list[SystemAssigneeCandidate] = []
        membership_repository = SqlMembershipAccessRepository(self._session)
        last_scanned: tuple[SubjectModel, WorkspaceMembershipModel] | None = None
        for target_subject, membership in rows:
            last_scanned = (target_subject, membership)
            access = await membership_repository.get_access(
                workspace_id=workspace_id,
                subject_id=target_subject.id,
            )
            if access is None or access.summary.effective_profile_role not in {
                ProfileRoleTier.ENGINEER_STEWARD.value,
                ProfileRoleTier.MANAGER.value,
                ProfileRoleTier.ADMIN.value,
            }:
                continue
            candidates.append(
                SystemAssigneeCandidate(
                    subject_id=target_subject.id,
                    display_name=target_subject.display_name,
                    email=target_subject.email,
                    tier=access.summary.effective_profile_role,
                )
            )
            if len(candidates) > limit:
                break
        has_extra_candidate = len(candidates) > limit
        has_more = has_extra_candidate or len(rows) == scan_limit
        visible = candidates[:limit]
        boundary_name: str | None = None
        boundary_id: UUID | None = None
        if has_extra_candidate and visible:
            boundary_name = visible[-1].display_name.lower()
            boundary_id = visible[-1].subject_id
        elif has_more and last_scanned is not None:
            boundary_name = last_scanned[0].display_name.lower()
            boundary_id = last_scanned[0].id
        return SystemAssigneeCandidatePage(
            items=tuple(visible),
            next_cursor=(
                _encode_membership_cursor(
                    workspace_id=workspace_id,
                    query=query,
                    active=True,
                    display_name=boundary_name,
                    subject_id=boundary_id,
                )
                if boundary_name is not None and boundary_id is not None
                else None
            ),
        )

    async def list_schema_scopes(
        self,
        *,
        workspace_id: UUID,
        system_id: UUID,
        limit: int,
        cursor: str | None = None,
    ) -> SystemSchemaScopePage:
        _validate_admin_list_limit(limit)
        system = await self._system_for_read(
            workspace_id=workspace_id,
            system_id=system_id,
        )
        filters = {
            "system_id": str(system_id),
            "system_version": str(system.version),
        }
        statement = (
            select(SystemSchemaScopeModel)
            .where(
                SystemSchemaScopeModel.workspace_id == workspace_id,
                SystemSchemaScopeModel.system_id == system_id,
            )
            .order_by(SystemSchemaScopeModel.id.desc())
            .limit(limit + 1)
        )
        if cursor is not None:
            boundary_id = decode_admin_list_cursor(
                cursor,
                scope="SYSTEM_SCHEMA_SCOPES",
                workspace_id=workspace_id,
                filters=filters,
            )
            statement = statement.where(SystemSchemaScopeModel.id < boundary_id)
        rows = list((await self._session.scalars(statement)).all())
        has_more = len(rows) > limit
        visible = rows[:limit]
        return SystemSchemaScopePage(
            items=tuple(
                SystemSchemaScope(
                    scope_id=item.id,
                    system_id=item.system_id,
                    platform=item.platform,
                    database_name=item.database_name,
                    schema_name=item.schema_name,
                    active=item.active,
                    version=item.version,
                )
                for item in visible
            ),
            system_version=system.version,
            next_cursor=(
                encode_admin_list_cursor(
                    scope="SYSTEM_SCHEMA_SCOPES",
                    workspace_id=workspace_id,
                    filters=filters,
                    boundary_id=visible[-1].id,
                )
                if has_more and visible
                else None
            ),
        )

    async def list_schema_scope_candidates(
        self,
        *,
        workspace_id: UUID,
        system_id: UUID,
        subject: SubjectAttributes,
        limit: int,
        query: str | None = None,
        cursor: str | None = None,
    ) -> SystemSchemaScopeCandidatePage:
        _validate_admin_list_limit(limit)
        asset_conditions = self._schema_scope_asset_conditions(
            workspace_id=workspace_id,
            system_id=system_id,
            subject=subject,
        )
        await self._system_for_read(workspace_id=workspace_id, system_id=system_id)
        mapped_system_id = (
            select(SystemSchemaScopeModel.system_id)
            .where(
                SystemSchemaScopeModel.workspace_id == AssetProjectionModel.workspace_id,
                SystemSchemaScopeModel.platform == AssetProjectionModel.platform,
                SystemSchemaScopeModel.database_name == AssetProjectionModel.database_name,
                SystemSchemaScopeModel.schema_name == AssetProjectionModel.schema_name,
                SystemSchemaScopeModel.active.is_(True),
            )
            .correlate(AssetProjectionModel)
            .scalar_subquery()
        )
        filters = {"system_id": str(system_id), "query": query}
        statement = (
            select(AssetProjectionModel, mapped_system_id.label("mapped_system_id"))
            .where(*asset_conditions)
            .order_by(AssetProjectionModel.id.desc())
            .limit(limit + 1)
        )
        if query is not None:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            statement = statement.where(
                or_(
                    AssetProjectionModel.name.ilike(pattern, escape="\\"),
                    AssetProjectionModel.platform.ilike(pattern, escape="\\"),
                    AssetProjectionModel.database_name.ilike(pattern, escape="\\"),
                    AssetProjectionModel.schema_name.ilike(pattern, escape="\\"),
                )
            )
        if cursor is not None:
            boundary_id = decode_admin_list_cursor(
                cursor,
                scope="SYSTEM_SCHEMA_SCOPE_CANDIDATES",
                workspace_id=workspace_id,
                filters=filters,
            )
            statement = statement.where(AssetProjectionModel.id < boundary_id)
        rows = list((await self._session.execute(statement)).all())
        has_more = len(rows) > limit
        visible = rows[:limit]
        return SystemSchemaScopeCandidatePage(
            items=tuple(
                SystemSchemaScopeCandidate(
                    asset_id=asset.id,
                    asset_name=asset.name,
                    asset_type=asset.asset_type,
                    platform=str(asset.platform),
                    database_name=str(asset.database_name),
                    schema_name=str(asset.schema_name),
                    classification=Classification(asset.classification),
                    mapped_system_id=(
                        UUID(str(candidate_system_id)) if candidate_system_id is not None else None
                    ),
                )
                for asset, candidate_system_id in visible
            ),
            next_cursor=(
                encode_admin_list_cursor(
                    scope="SYSTEM_SCHEMA_SCOPE_CANDIDATES",
                    workspace_id=workspace_id,
                    filters=filters,
                    boundary_id=visible[-1][0].id,
                )
                if has_more and visible
                else None
            ),
        )

    async def patch_schema_scopes(
        self,
        command: SystemSchemaScopePatchCommand,
        *,
        subject: SubjectAttributes,
    ) -> int:
        asset_conditions = self._schema_scope_asset_conditions(
            workspace_id=command.workspace_id,
            system_id=command.system_id,
            subject=subject,
        )
        system = await self._system_for_update(
            workspace_id=command.workspace_id,
            system_id=command.system_id,
            expected_version=command.expected_system_version,
        )
        if not system.active:
            raise NotFoundError("The active data system does not exist.")
        assets = {
            item.id: item
            for item in (
                await self._session.scalars(
                    select(AssetProjectionModel)
                    .where(
                        AssetProjectionModel.id.in_(command.upsert_asset_ids),
                        *asset_conditions,
                    )
                    .with_for_update(read=True)
                )
            ).all()
        }
        if len(assets) != len(command.upsert_asset_ids):
            raise NotFoundError("A selected Catalog asset is no longer active or available.")
        coordinates: dict[UUID, tuple[str, str, str]] = {}
        for asset_id in command.upsert_asset_ids:
            asset = assets[asset_id]
            if asset.platform is None or asset.database_name is None or asset.schema_name is None:
                raise ValidationError("A selected Catalog asset has no complete schema locator.")
            if asset.system_id is not None and asset.system_id != command.system_id:
                raise ConflictError(
                    "The selected Catalog asset has a conflicting native System binding."
                )
            coordinates[asset_id] = (
                asset.platform,
                asset.database_name,
                asset.schema_name,
            )
        if len(set(coordinates.values())) != len(coordinates):
            raise ValidationError("Select at most one Catalog asset from each schema.")

        deactivations = {
            item.id: item
            for item in (
                await self._session.scalars(
                    select(SystemSchemaScopeModel)
                    .where(
                        SystemSchemaScopeModel.workspace_id == command.workspace_id,
                        SystemSchemaScopeModel.id.in_(command.deactivate_scope_ids),
                    )
                    .with_for_update()
                )
            ).all()
        }
        if len(deactivations) != len(command.deactivate_scope_ids) or any(
            item.system_id != command.system_id or not item.active
            for item in deactivations.values()
        ):
            raise ConflictError("A selected schema mapping is stale or belongs to another System.")
        if set(coordinates.values()) & {
            (item.platform, item.database_name, item.schema_name) for item in deactivations.values()
        }:
            raise ValidationError(
                "A schema mapping cannot be activated and deactivated in the same patch."
            )

        existing = {
            (item.platform, item.database_name, item.schema_name): item
            for item in (
                await self._session.scalars(
                    select(SystemSchemaScopeModel)
                    .where(
                        SystemSchemaScopeModel.workspace_id == command.workspace_id,
                        tuple_(
                            SystemSchemaScopeModel.platform,
                            SystemSchemaScopeModel.database_name,
                            SystemSchemaScopeModel.schema_name,
                        ).in_(tuple(coordinates.values())),
                    )
                    .with_for_update()
                )
            ).all()
        }
        effective_changes = bool(deactivations)
        for coordinate in coordinates.values():
            current = existing.get(coordinate)
            if current is not None and current.active and current.system_id != command.system_id:
                raise ConflictError("The selected schema is already mapped to another System.")
            if current is None:
                self._session.add(
                    SystemSchemaScopeModel(
                        workspace_id=command.workspace_id,
                        system_id=command.system_id,
                        platform=coordinate[0],
                        database_name=coordinate[1],
                        schema_name=coordinate[2],
                        active=True,
                    )
                )
                effective_changes = True
            elif not current.active or current.system_id != command.system_id:
                current.system_id = command.system_id
                current.active = True
                current.version += 1
                effective_changes = True
        if not effective_changes:
            raise ConflictError("The schema-scope patch contains no effective changes.")
        for item in deactivations.values():
            item.active = False
            item.version += 1
        system.version += 1
        await self._session.flush()
        return system.version

    async def patch_assignees(self, command: SystemAssigneePatchCommand) -> int:
        system = await self._system_for_update(
            workspace_id=command.workspace_id,
            system_id=command.system_id,
            expected_version=command.expected_system_version,
        )
        await self._assert_assignable_subjects(
            workspace_id=command.workspace_id,
            subject_ids=frozenset(item.subject_id for item in command.upserts),
        )
        removal_keys = [(item.subject_id, item.responsibility) for item in command.removals]
        upsert_keys = [(item.subject_id, item.responsibility) for item in command.upserts]
        target_keys = removal_keys + upsert_keys
        existing = {
            (item.subject_id, item.responsibility): item
            for item in (
                await self._session.scalars(
                    select(SystemAssigneeModel)
                    .where(
                        SystemAssigneeModel.workspace_id == command.workspace_id,
                        SystemAssigneeModel.system_id == command.system_id,
                        tuple_(
                            SystemAssigneeModel.subject_id,
                            SystemAssigneeModel.responsibility,
                        ).in_(target_keys),
                    )
                    .with_for_update()
                )
            ).all()
        }
        missing_removals = [
            key for key in removal_keys if key not in existing or not existing[key].active
        ]
        if missing_removals:
            raise ConflictError(
                "A system assignee selected for removal no longer exists.",
                details={
                    "missing": [
                        {"subject_id": str(subject_id), "responsibility": responsibility}
                        for subject_id, responsibility in missing_removals
                    ]
                },
            )
        effective_upserts = [
            item
            for item in command.upserts
            if (current := existing.get((item.subject_id, item.responsibility))) is None
            or current.priority != item.priority
            or not current.active
        ]
        if not removal_keys and not effective_upserts:
            raise ConflictError("The system-assignee patch contains no effective changes.")
        for removal_key in removal_keys:
            current = existing[removal_key]
            current.active = False
            current.version += 1
        for item in effective_upserts:
            current = existing.get((item.subject_id, item.responsibility))
            if current is None:
                self._session.add(
                    SystemAssigneeModel(
                        workspace_id=command.workspace_id,
                        system_id=command.system_id,
                        subject_id=item.subject_id,
                        responsibility=item.responsibility,
                        priority=item.priority,
                        active=True,
                    )
                )
            else:
                current.priority = item.priority
                current.active = True
                current.version += 1
        await self._session.flush()
        lane_rows = (
            await self._session.execute(
                select(
                    SystemAssigneeModel.responsibility,
                    func.count(SystemAssigneeModel.id),
                    func.min(SystemAssigneeModel.priority),
                    func.count(func.distinct(SystemAssigneeModel.priority)),
                )
                .where(
                    SystemAssigneeModel.workspace_id == command.workspace_id,
                    SystemAssigneeModel.system_id == command.system_id,
                    SystemAssigneeModel.active.is_(True),
                )
                .group_by(SystemAssigneeModel.responsibility)
            )
        ).all()
        lanes = {
            responsibility: (int(count), int(minimum_priority), int(distinct_priorities))
            for responsibility, count, minimum_priority, distinct_priorities in lane_rows
        }
        if set(lanes) != {"DEVELOPER", "DATA_STEWARD"} or any(
            count < 1 or minimum_priority != 1 or distinct_priorities != count
            for count, minimum_priority, distinct_priorities in lanes.values()
        ):
            raise ValidationError(
                "Every system must retain both responsibility lanes with unique priorities "
                "starting at 1."
            )
        system.version += 1
        await self._session.flush()
        return system.version

    async def replace_assignees(self, command: SystemAssigneeUpdateCommand) -> int:
        system = await self._system_for_update(
            workspace_id=command.workspace_id,
            system_id=command.system_id,
            expected_version=command.expected_system_version,
        )
        subject_ids = frozenset(item.subject_id for item in command.assignees)
        await self._assert_assignable_subjects(
            workspace_id=command.workspace_id,
            subject_ids=subject_ids,
        )
        existing = {
            (item.subject_id, item.responsibility): item
            for item in (
                await self._session.scalars(
                    select(SystemAssigneeModel)
                    .where(
                        SystemAssigneeModel.workspace_id == command.workspace_id,
                        SystemAssigneeModel.system_id == command.system_id,
                    )
                    .with_for_update()
                )
            ).all()
        }
        desired = {(item.subject_id, item.responsibility): item for item in command.assignees}
        for key, current in existing.items():
            replacement = desired.get(key)
            if replacement is None:
                if current.active:
                    current.active = False
                    current.version += 1
                continue
            if current.priority != replacement.priority or not current.active:
                current.priority = replacement.priority
                current.active = True
                current.version += 1
        self._session.add_all(
            [
                SystemAssigneeModel(
                    workspace_id=command.workspace_id,
                    system_id=command.system_id,
                    subject_id=item.subject_id,
                    responsibility=item.responsibility,
                    priority=item.priority,
                    active=True,
                )
                for key, item in desired.items()
                if key not in existing
            ]
        )
        system.version += 1
        await self._session.flush()
        return system.version

    async def create(
        self,
        *,
        workspace_id: UUID,
        code: str,
        name: str,
        description: str,
    ) -> SystemDirectoryEntry:
        from datariver.domain.common import ConflictError
        from datariver.infrastructure.db.models.platform import DataSystemModel

        existing = await self._session.scalar(
            select(DataSystemModel).where(
                DataSystemModel.workspace_id == workspace_id,
                DataSystemModel.code == code,
            )
        )
        if existing is not None:
            raise ConflictError(f"System code '{code}' is already in use in this workspace.")
        model = DataSystemModel(
            workspace_id=workspace_id,
            code=code,
            name=name,
            description=description,
            active=True,
        )
        self._session.add(model)
        await self._session.flush()
        return SystemDirectoryEntry(
            system_id=model.id,
            code=model.code,
            name=model.name,
            description=model.description,
            active=model.active,
            version=model.version,
            assignees=(),
            assignee_count=0,
        )

    async def _system_for_update(
        self,
        *,
        workspace_id: UUID,
        system_id: UUID,
        expected_version: int,
    ) -> DataSystemModel:
        system = (
            await self._session.scalars(
                select(DataSystemModel)
                .where(
                    DataSystemModel.workspace_id == workspace_id,
                    DataSystemModel.id == system_id,
                )
                .with_for_update()
            )
        ).one_or_none()
        if system is None:
            raise NotFoundError("The data system does not exist.")
        if system.version != expected_version:
            raise ConflictError("The data system was modified by another operation.")
        return system

    async def _system_for_read(
        self,
        *,
        workspace_id: UUID,
        system_id: UUID,
    ) -> DataSystemModel:
        system = await self._session.scalar(
            select(DataSystemModel).where(
                DataSystemModel.workspace_id == workspace_id,
                DataSystemModel.id == system_id,
                DataSystemModel.active.is_(True),
            )
        )
        if system is None:
            raise NotFoundError("The active data system does not exist.")
        return system

    async def _assert_assignable_subjects(
        self,
        *,
        workspace_id: UUID,
        subject_ids: frozenset[UUID],
    ) -> None:
        if not subject_ids:
            return
        membership_actions = WorkspaceMembershipModel.attributes["allowed_actions"]
        membership_groups = WorkspaceMembershipModel.attributes
        profile_is_current = exists(
            select(ProfileRoleAssignmentModel.subject_id).where(
                ProfileRoleAssignmentModel.workspace_id == workspace_id,
                ProfileRoleAssignmentModel.subject_id == WorkspaceMembershipModel.subject_id,
                ProfileRoleAssignmentModel.state == "ACTIVE",
                ProfileRoleAssignmentModel.policy_version == PROFILE_ROLE_POLICY_VERSION,
                ProfileRoleAssignmentModel.membership_version == WorkspaceMembershipModel.version,
                or_(
                    and_(
                        ProfileRoleAssignmentModel.tier == ProfileRoleTier.ENGINEER_STEWARD.value,
                        ProfileRoleAssignmentModel.materialized_actions_hash
                        == PROFILE_ROLE_BY_TIER[
                            ProfileRoleTier.ENGINEER_STEWARD
                        ].materialized_actions_hash,
                        membership_actions
                        == cast(
                            json.dumps(
                                sorted(
                                    action.value
                                    for action in PROFILE_ROLE_BY_TIER[
                                        ProfileRoleTier.ENGINEER_STEWARD
                                    ].allowed_actions
                                )
                            ),
                            postgresql.JSONB,
                        ),
                    ),
                    and_(
                        ProfileRoleAssignmentModel.tier == ProfileRoleTier.MANAGER.value,
                        ProfileRoleAssignmentModel.materialized_actions_hash
                        == PROFILE_ROLE_BY_TIER[ProfileRoleTier.MANAGER].materialized_actions_hash,
                        membership_actions
                        == cast(
                            json.dumps(
                                sorted(
                                    action.value
                                    for action in PROFILE_ROLE_BY_TIER[
                                        ProfileRoleTier.MANAGER
                                    ].allowed_actions
                                )
                            ),
                            postgresql.JSONB,
                        ),
                    ),
                ),
                ~func.jsonb_path_exists(
                    membership_groups,
                    cast(
                        '$.groups[*] ? (@ == "security-administrators" || '
                        '@ == "service-accounts" || @ like_regex "^datariver-role-")',
                        postgresql.JSONPATH,
                    ),
                ),
                WorkspaceMembershipModel.attributes["allowed_system_ids"]
                == cast("[]", postgresql.JSONB),
            )
        )
        canonical_is_current = exists(
            select(CanonicalAdminBindingModel.subject_id)
            .join(
                AccessRoleModel,
                and_(
                    AccessRoleModel.workspace_id == CanonicalAdminBindingModel.workspace_id,
                    AccessRoleModel.id == CanonicalAdminBindingModel.canonical_role_id,
                ),
            )
            .where(
                CanonicalAdminBindingModel.workspace_id == workspace_id,
                CanonicalAdminBindingModel.subject_id == WorkspaceMembershipModel.subject_id,
                CanonicalAdminBindingModel.state == "ACTIVE",
                CanonicalAdminBindingModel.membership_version == WorkspaceMembershipModel.version,
                CanonicalAdminBindingModel.capability_catalog_version == CAPABILITY_CATALOG_VERSION,
                CanonicalAdminBindingModel.capability_hash == CANONICAL_ADMIN_CAPABILITY_HASH,
                AccessRoleModel.active.is_(True),
                AccessRoleModel.role_kind == AccessRoleKind.CANONICAL_ADMIN.value,
                AccessRoleModel.management_source
                == AccessRoleManagementSource.SERVER_CANONICAL.value,
                AccessRoleModel.version == CanonicalAdminBindingModel.canonical_role_version,
                AccessRoleModel.capability_catalog_version == CAPABILITY_CATALOG_VERSION,
                WorkspaceMembershipModel.clearance == int(Classification.RESTRICTED),
                membership_actions
                == cast(
                    json.dumps(sorted(action.value for action in DEFAULT_HUMAN_ADMIN_ACTIONS)),
                    postgresql.JSONB,
                ),
                WorkspaceMembershipModel.attributes["denied_actions"]
                == cast("[]", postgresql.JSONB),
                func.jsonb_path_exists(
                    membership_groups,
                    cast(
                        '$.groups[*] ? (@ == "security-administrators")',
                        postgresql.JSONPATH,
                    ),
                ),
                ~func.jsonb_path_exists(
                    membership_groups,
                    cast(
                        '$.groups[*] ? (@ == "service-accounts")',
                        postgresql.JSONPATH,
                    ),
                ),
            )
        )
        eligible_subject_ids = set(
            (
                await self._session.scalars(
                    select(WorkspaceMembershipModel.subject_id)
                    .join(SubjectModel, SubjectModel.id == WorkspaceMembershipModel.subject_id)
                    .where(
                        WorkspaceMembershipModel.workspace_id == workspace_id,
                        WorkspaceMembershipModel.subject_id.in_(subject_ids),
                        WorkspaceMembershipModel.active.is_(True),
                        SubjectModel.active.is_(True),
                        or_(
                            WorkspaceMembershipModel.access_expires_at.is_(None),
                            WorkspaceMembershipModel.access_expires_at > func.now(),
                        ),
                        or_(
                            WorkspaceMembershipModel.job_function.is_(None),
                            WorkspaceMembershipModel.job_function != "SERVICE_ACCOUNT",
                        ),
                        or_(profile_is_current, canonical_is_current),
                    )
                )
            ).all()
        )
        if eligible_subject_ids != subject_ids:
            raise ValidationError(
                "Every system assignee must have a current Engineer/Steward, Manager, "
                "or Canonical Admin profile Role."
            )


class SqlAdminAccessUnitOfWork(AdminAccessUnitOfWork):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self.requests: SqlAdminAccessRequestRepository
        self.renewals: SqlMembershipRenewalRepository
        self.memberships: SqlMembershipAccessRepository
        self.systems: SqlSystemDirectoryRepository
        self.outbox: SqlOutboxWriter
        self.idempotency: SqlIdempotencyStore
        self._committed = False

    async def __aenter__(self) -> SqlAdminAccessUnitOfWork:
        self._session = self._session_factory()
        self.requests = SqlAdminAccessRequestRepository(self._session)
        self.renewals = SqlMembershipRenewalRepository(self._session)
        self.memberships = SqlMembershipAccessRepository(self._session)
        self.systems = SqlSystemDirectoryRepository(self._session)
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

    async def lock_workspace_access(self, *, workspace_id: UUID) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"datariver:iam:workspace-access:{workspace_id}"},
        )

    async def set_security_context(self, *, workspace_id: UUID, subject_id: UUID) -> None:
        if self._session is None:
            raise RuntimeError("Unit of work has not been entered.")
        await set_security_context(self._session, workspace_id=workspace_id, subject_id=subject_id)


def _request_model(request: AdminAccessRequest) -> AdminAccessRequestModel:
    return AdminAccessRequestModel(
        id=request.access_request_id,
        workspace_id=request.workspace_id,
        requester_id=request.requester_id,
        request_reason=request.request_reason,
        request_policy_decision_id=request.request_policy_decision_id,
        target_subject_id=request.command.target_subject_id,
        command_type=MEMBERSHIP_ACCESS_COMMAND,
        command_document=request.command.command_document(),
        payload_hash=request.payload_hash,
        state=request.state.value,
        expires_at=request.expires_at,
        checker_id=request.checker_id,
        consumed_by=request.consumed_by,
        consumed_at=request.consumed_at,
        consume_policy_decision_id=request.consume_policy_decision_id,
        version=request.version,
    )


def _string_set(document: object, key: str) -> set[str] | None:
    if not isinstance(document, dict):
        return None
    value = document.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return None
    return set(value)


def _raise_profile_role_database_error(error: DBAPIError) -> None:
    sqlstate = getattr(error.orig, "sqlstate", None)
    message = str(error.orig)
    if sqlstate == "42501":
        raise ForbiddenError("Profile Role authority is no longer current.") from error
    if sqlstate == "40001":
        raise ConflictError("Profile Role evidence changed before the update.") from error
    if sqlstate in {"23503", "23505"}:
        raise ConflictError("Profile Role state changed before the update.") from error
    if sqlstate == "23514":
        if "last Canonical Admin" in message:
            raise ConflictError("The last verified Canonical Admin cannot be demoted.") from error
        raise ValidationError("The profile Role transition violates policy.") from error


def membership_access_payload_hash(membership: WorkspaceMembershipModel) -> str:
    groups = _string_set(membership.attributes, "groups")
    allowed = _string_set(membership.attributes, "allowed_actions")
    denied = _string_set(membership.attributes, "denied_actions")
    system_ids = _string_set(membership.attributes, "allowed_system_ids")
    domain_ids = _string_set(membership.attributes, "allowed_domain_ids")
    if (
        groups is None
        or allowed is None
        or denied is None
        or system_ids is None
        or domain_ids is None
    ):
        raise ConflictError("The stored workspace membership access is invalid.")
    try:
        document: dict[str, object] = {
            "active": membership.active,
            "clearance": Classification(membership.clearance).name,
            "groups": sorted(groups),
            "allowed_actions": sorted(Action(value).value for value in allowed),
            "denied_actions": sorted(Action(value).value for value in denied),
            "allowed_system_ids": sorted(str(UUID(value)) for value in system_ids),
            "allowed_domain_ids": sorted(str(UUID(value)) for value in domain_ids),
        }
    except (TypeError, ValueError) as error:
        raise ConflictError("The stored workspace membership access is invalid.") from error
    return canonical_json_hash(document)


def _membership_summary(
    subject: SubjectModel,
    membership: WorkspaceMembershipModel,
    *,
    owned_table_count: int = 0,
    change_request_count: int = 0,
    pending_renewal_request_id: UUID | None = None,
    effective_profile_role: str = EffectiveProfileRoleStatus.UNASSIGNED.value,
) -> WorkspaceMembershipSummary:
    try:
        clearance = Classification(membership.clearance)
    except ValueError as error:
        raise ConflictError("The stored workspace membership access is invalid.") from error
    if membership.version < 1:
        raise ConflictError("The stored workspace membership version is invalid.")
    now = utc_now()
    access_expires_at = membership.access_expires_at
    return WorkspaceMembershipSummary(
        subject_id=subject.id,
        display_name=subject.display_name,
        email=subject.email,
        last_login_at=subject.last_login_at,
        last_login_ip=subject.last_login_ip,
        owned_table_count=owned_table_count,
        change_request_count=change_request_count,
        joined_at=membership.created_at,
        access_expires_at=access_expires_at,
        renewal_eligible_at=(
            access_expires_at - timedelta(days=30) if access_expires_at is not None else None
        ),
        access_expired=access_expires_at is not None and access_expires_at <= now,
        renewal_request_eligible=(
            access_expires_at is not None
            and access_expires_at > now
            and now >= access_expires_at - timedelta(days=30)
            and pending_renewal_request_id is None
        ),
        pending_renewal_request_id=pending_renewal_request_id,
        subject_active=subject.active,
        membership_active=membership.active,
        department_id=membership.department_id,
        job_function=membership.job_function,
        clearance=clearance,
        membership_version=membership.version,
        effective_profile_role=effective_profile_role,
    )


def _membership_access_record(
    subject: SubjectModel,
    membership: WorkspaceMembershipModel,
    *,
    role_assignment: MembershipRoleAssignmentEvidence | None = None,
    canonical_admin_binding: CanonicalAdminBindingEvidence | None = None,
    profile_role: ProfileRoleAssignmentEvidence | None = None,
) -> WorkspaceMembershipAccessRecord:
    attributes = membership.attributes
    groups = _string_set(attributes, "groups")
    allowed = _string_set(attributes, "allowed_actions")
    denied = _string_set(attributes, "denied_actions")
    system_ids = _string_set(attributes, "allowed_system_ids")
    domain_ids = _string_set(attributes, "allowed_domain_ids")
    if (
        groups is None
        or allowed is None
        or denied is None
        or system_ids is None
        or domain_ids is None
    ):
        raise ConflictError("The stored workspace membership access is invalid.")
    try:
        command = MembershipAccessUpdate(
            workspace_id=membership.workspace_id,
            target_subject_id=membership.subject_id,
            expected_membership_version=membership.version,
            active=membership.active,
            clearance=Classification(membership.clearance),
            groups=frozenset(groups),
            allowed_actions=frozenset(Action(value) for value in allowed),
            denied_actions=frozenset(Action(value) for value in denied),
            allowed_system_ids=frozenset(UUID(value) for value in system_ids),
            allowed_domain_ids=frozenset(UUID(value) for value in domain_ids),
        )
    except (TypeError, ValueError, ValidationError) as error:
        raise ConflictError("The stored workspace membership access is invalid.") from error
    return WorkspaceMembershipAccessRecord(
        summary=_membership_summary(
            subject,
            membership,
            effective_profile_role=_effective_profile_role_label(profile_role),
        ),
        groups=command.groups,
        allowed_actions=command.allowed_actions,
        denied_actions=command.denied_actions,
        allowed_system_ids=command.allowed_system_ids,
        allowed_domain_ids=command.allowed_domain_ids,
        role_assignment=role_assignment,
        canonical_admin_binding=canonical_admin_binding,
        profile_role=profile_role,
    )


def _effective_profile_role_label(
    evidence: ProfileRoleAssignmentEvidence | None,
) -> str:
    if evidence is None:
        return EffectiveProfileRoleStatus.UNASSIGNED.value
    if evidence.status == EffectiveProfileRoleStatus.VERIFIED.value and evidence.tier is not None:
        return evidence.tier
    return evidence.status


def _profile_role_assignment_evidence(
    *,
    subject: SubjectModel,
    membership: WorkspaceMembershipModel,
    assignment: ProfileRoleAssignmentModel | None,
    canonical_admin_binding: CanonicalAdminBindingEvidence | None,
) -> ProfileRoleAssignmentEvidence | None:
    if canonical_admin_binding is not None and canonical_admin_binding.status != "REVOKED":
        return ProfileRoleAssignmentEvidence(
            status=canonical_admin_binding.status,
            tier=ProfileRoleTier.ADMIN.value,
            policy_version=PROFILE_ROLE_POLICY_VERSION,
            membership_version=canonical_admin_binding.membership_version,
            assignment_version=canonical_admin_binding.binding_version,
            updated_at=canonical_admin_binding.updated_at,
        )
    if assignment is None:
        return None
    status = EffectiveProfileRoleStatus.REVOKED.value
    if assignment.state == "ACTIVE":
        status = EffectiveProfileRoleStatus.STALE.value
        tier: ProfileRoleTier | None = None
        try:
            tier = ProfileRoleTier(assignment.tier)
            policy = PROFILE_ROLE_BY_TIER[tier]
        except (KeyError, ValueError):
            policy = None
        allowed = _string_set(membership.attributes, "allowed_actions")
        stored_system_ids = _string_set(membership.attributes, "allowed_system_ids")
        groups = _string_set(membership.attributes, "groups")
        now = utc_now()
        if (
            policy is not None
            and tier is not ProfileRoleTier.ADMIN
            and assignment.policy_version == PROFILE_ROLE_POLICY_VERSION
            and assignment.materialized_actions_hash == policy.materialized_actions_hash
            and assignment.membership_version == membership.version
            and subject.active
            and membership.active
            and (membership.access_expires_at is None or membership.access_expires_at > now)
            and membership.job_function != "SERVICE_ACCOUNT"
            and allowed == {action.value for action in policy.allowed_actions}
            and stored_system_ids == set()
            and groups is not None
            and "service-accounts" not in groups
            and "security-administrators" not in groups
            and not any(group.startswith("datariver-role-") for group in groups)
        ):
            status = EffectiveProfileRoleStatus.VERIFIED.value
    return ProfileRoleAssignmentEvidence(
        status=status,
        tier=assignment.tier,
        policy_version=assignment.policy_version,
        membership_version=assignment.membership_version,
        assignment_version=assignment.version,
        updated_at=assignment.updated_at,
    )


def _canonical_admin_binding_evidence(
    *,
    subject: SubjectModel,
    membership: WorkspaceMembershipModel,
    binding: CanonicalAdminBindingModel,
    role: AccessRoleModel | None,
) -> CanonicalAdminBindingEvidence:
    status = "REVOKED" if binding.state == "REVOKED" else "STALE"
    allowed = _string_set(membership.attributes, "allowed_actions")
    denied = _string_set(membership.attributes, "denied_actions")
    groups = _string_set(membership.attributes, "groups")
    expected_actions = {action.value for action in DEFAULT_HUMAN_ADMIN_ACTIONS}
    now = utc_now()
    membership_is_current = (
        subject.active
        and membership.active
        and (membership.access_expires_at is None or membership.access_expires_at > now)
        and membership.job_function != "SERVICE_ACCOUNT"
        and membership.clearance == int(Classification.RESTRICTED)
        and groups is not None
        and "security-administrators" in groups
        and "service-accounts" not in groups
        and not any(group.startswith("datariver-role-") for group in groups)
        and allowed == expected_actions
        and denied is not None
        and not denied
        and allowed.isdisjoint(action.value for action in SERVICE_ONLY_ACTIONS)
    )
    role_is_current = (
        role is not None
        and role.active
        and role.role_key == CANONICAL_ADMIN_ROLE_KEY
        and role.role_kind == AccessRoleKind.CANONICAL_ADMIN.value
        and role.management_source == AccessRoleManagementSource.SERVER_CANONICAL.value
        and role.version == binding.canonical_role_version
        and role.capability_catalog_version == CAPABILITY_CATALOG_VERSION
        and role.allowed_actions == sorted(expected_actions)
        and role.denied_actions == []
        and role.groups == ["security-administrators"]
        and role.allowed_system_ids == []
        and role.allowed_domain_ids == []
        and role.clearance == int(Classification.RESTRICTED)
    )
    if (
        binding.state == "ACTIVE"
        and membership_is_current
        and role_is_current
        and binding.capability_catalog_version == CAPABILITY_CATALOG_VERSION
        and binding.capability_hash == CANONICAL_ADMIN_CAPABILITY_HASH
        and binding.membership_version == membership.version
        and binding.membership_access_hash == membership_access_payload_hash(membership)
    ):
        status = "VERIFIED"
    return CanonicalAdminBindingEvidence(
        status=status,
        role_version=binding.canonical_role_version,
        catalog_version=binding.capability_catalog_version,
        membership_version=binding.membership_version,
        binding_version=binding.version,
        updated_at=binding.updated_at,
    )
