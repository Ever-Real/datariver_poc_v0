from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from types import TracebackType
from uuid import UUID

from sqlalchemy import and_, cast, func, or_, select, text, tuple_
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.application.dto import (
    AdminAccessRequestPage,
    MembershipRenewalPage,
    MembershipRenewalRecord,
    MembershipRoleAssignmentEvidence,
    SystemAssigneePage,
    SystemDirectoryAssignee,
    SystemDirectoryEntry,
    SystemDirectoryPage,
    WorkspaceMembershipAccessRecord,
    WorkspaceMembershipPage,
    WorkspaceMembershipSummary,
)
from datariver.application.identity_admin import ProvisionedWorkspaceUser
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
)
from datariver.domain.authz import Action, Classification
from datariver.domain.common import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
    canonical_json_hash,
    utc_now,
)
from datariver.domain.membership_renewal import MembershipRenewalRequest, MembershipRenewalState
from datariver.infrastructure.db.governance import SqlIdempotencyStore, SqlOutboxWriter
from datariver.infrastructure.db.models.catalog import AssetProjectionModel
from datariver.infrastructure.db.models.governance import ChangeRequestModel
from datariver.infrastructure.db.models.platform import (
    AccessRoleAssignmentEventModel,
    AccessRoleAssignmentModel,
    AccessRoleModel,
    AdminAccessApprovalModel,
    AdminAccessRequestModel,
    DataSystemModel,
    MembershipRenewalRequestModel,
    SubjectModel,
    SystemAssigneeModel,
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
        change_request_counts: dict[UUID, int] = {}
        for subject_id, count in (
            await self._session.execute(
                select(ChangeRequestModel.requester_id, func.count())
                .where(
                    ChangeRequestModel.workspace_id == workspace_id,
                    ChangeRequestModel.requester_id.in_(subject_ids),
                )
                .group_by(ChangeRequestModel.requester_id)
            )
        ).all():
            change_request_counts[subject_id] = int(count)
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
                    )
                    .group_by(AssetProjectionModel.owner_ref)
                )
            ).all():
                if owner_ref in owner_subjects:
                    owned_table_counts[owner_subjects[owner_ref]] = int(count)
        items = tuple(
            _membership_summary(
                subject,
                membership,
                owned_table_count=owned_table_counts[subject.id],
                change_request_count=int(change_request_counts.get(subject.id, 0)),
                pending_renewal_request_id=pending_renewals.get(subject.id),
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
        return _membership_access_record(subject, membership, role_assignment=evidence)

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
    ) -> ProvisionedWorkspaceUser:
        try:
            stored_subject_id = await self._session.scalar(
                text(
                    """
                    SELECT iam.provision_workspace_identity(
                        :subject_id, :workspace_id, :issuer, :external_subject,
                        :display_name, :email, :department_id, :job_function,
                        :role_id, :access_expires_at
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
        if role_id is not None:
            role = (
                await self._session.scalars(
                    select(AccessRoleModel).where(
                        AccessRoleModel.workspace_id == workspace_id,
                        AccessRoleModel.id == role_id,
                        AccessRoleModel.active.is_(True),
                    )
                )
            ).one_or_none()
            membership = (
                await self._session.scalars(
                    select(WorkspaceMembershipModel).where(
                        WorkspaceMembershipModel.workspace_id == workspace_id,
                        WorkspaceMembershipModel.subject_id == subject_id,
                    )
                )
            ).one_or_none()
            actor_id = await self._session.scalar(
                text("SELECT NULLIF(current_setting('app.subject_id', true), '')::uuid")
            )
            if role is None or membership is None or not isinstance(actor_id, UUID):
                raise ConflictError("The provisioned role-assignment evidence is incomplete.")
            membership_groups = _string_set(membership.attributes, "groups")
            if membership_groups is None:
                raise ConflictError("The provisioned role-assignment evidence is incomplete.")
            role_markers = tuple(
                group for group in membership_groups if group.startswith("datariver-role-")
            )
            await self.record_role_assignment(
                workspace_id=workspace_id,
                subject_id=subject_id,
                role_id=role.id,
                role_version=role.version,
                role_marker=role_markers[0] if len(role_markers) == 1 else None,
                membership_version=membership.version,
                access_payload_hash=_membership_access_payload_hash(membership),
                actor_id=actor_id,
            )
        return ProvisionedWorkspaceUser(
            subject_id=subject_id,
            external_subject=external_subject,
            username=username,
            display_name=display_name,
            email=email,
            workspace_id=workspace_id,
            role_id=role_id,
            access_expires_at=access_expires_at,
        )

    async def apply(self, command: MembershipAccessUpdate) -> int:
        membership = await self._membership_for_update(command)
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
                    )
                    .with_for_update()
                )
            ).one_or_none()
            if role is None:
                raise ConflictError("The selected access role changed before assignment.")
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

    async def _assert_assignable_subjects(
        self,
        *,
        workspace_id: UUID,
        subject_ids: frozenset[UUID],
    ) -> None:
        if not subject_ids:
            return
        active_subject_ids = set(
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
                    )
                )
            ).all()
        )
        if active_subject_ids != subject_ids:
            raise ValidationError("Every system assignee must be an active human workspace member.")


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


def _membership_access_payload_hash(membership: WorkspaceMembershipModel) -> str:
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
    )


def _membership_access_record(
    subject: SubjectModel,
    membership: WorkspaceMembershipModel,
    *,
    role_assignment: MembershipRoleAssignmentEvidence | None = None,
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
        summary=_membership_summary(subject, membership),
        groups=command.groups,
        allowed_actions=command.allowed_actions,
        denied_actions=command.denied_actions,
        allowed_system_ids=command.allowed_system_ids,
        allowed_domain_ids=command.allowed_domain_ids,
        role_assignment=role_assignment,
    )
