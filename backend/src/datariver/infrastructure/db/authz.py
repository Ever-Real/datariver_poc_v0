from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.application.dto import DecisionAuditItem
from datariver.application.ports import DecisionSetWriter, DecisionWriter, SubjectReader
from datariver.domain.authz import (
    Action,
    AuthenticationAssurance,
    Classification,
    Decision,
    SubjectAttributes,
)
from datariver.domain.capability_catalog import (
    CANONICAL_ADMIN_CAPABILITY_HASH,
    CANONICAL_ADMIN_ROLE_KEY,
    CAPABILITY_CATALOG_VERSION,
    DEFAULT_HUMAN_ADMIN_ACTIONS,
    AccessRoleKind,
    AccessRoleManagementSource,
)
from datariver.domain.common import ForbiddenError, canonical_json_hash, utc_now
from datariver.domain.profile_roles import (
    PROFILE_ROLE_BY_TIER,
    PROFILE_ROLE_POLICY_VERSION,
    EffectiveProfileRoleStatus,
    ProfileRoleTier,
)
from datariver.infrastructure.db.models.authz import PolicyDecisionModel
from datariver.infrastructure.db.models.platform import (
    AccessRoleModel,
    CanonicalAdminBindingModel,
    DataSystemModel,
    ProfileRoleAssignmentModel,
    SubjectModel,
    SystemAssigneeModel,
    WorkspaceMembershipModel,
)
from datariver.infrastructure.db.rls import set_security_context


class SqlDecisionWriter(DecisionWriter, DecisionSetWriter):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def append_decision(
        self,
        *,
        decision: Decision,
        subject_id: UUID,
        workspace_id: UUID,
        resource_id: UUID,
        action: str,
        request_id: str,
    ) -> None:
        async with self._session_factory() as session:
            await set_security_context(session, workspace_id=workspace_id, subject_id=subject_id)
            session.add(
                PolicyDecisionModel(
                    id=decision.decision_id,
                    workspace_id=workspace_id,
                    subject_id=subject_id,
                    resource_id=resource_id,
                    action=action,
                    effect=decision.effect.value,
                    reason_codes=list(decision.reason_codes),
                    policy_versions=list(decision.policy_versions),
                    evaluation_context={
                        "kind": "single",
                        "authentication_assurance": decision.authentication_assurance.value,
                        "authentication_time": (
                            decision.authentication_time.isoformat()
                            if decision.authentication_time is not None
                            else None
                        ),
                    },
                    request_id=request_id,
                    decided_at=datetime.now().astimezone(),
                )
            )
            await session.commit()

    async def append_decision_set(
        self,
        *,
        decision_id: UUID,
        items: Sequence[DecisionAuditItem],
        subject_id: UUID,
        workspace_id: UUID,
        parent_resource_id: UUID,
        action: str,
        request_id: str,
    ) -> None:
        allowed_count = sum(item.decision.allowed for item in items)
        reasons = sorted(
            {reason for item in items for reason in item.decision.reason_codes}
            or {"EMPTY_RESOURCE_SET"}
        )
        policy_versions = sorted(
            {version for item in items for version in item.decision.policy_versions}
            or {"builtin-abac-v2"}
        )
        async with self._session_factory() as session:
            await set_security_context(session, workspace_id=workspace_id, subject_id=subject_id)
            session.add(
                PolicyDecisionModel(
                    id=decision_id,
                    workspace_id=workspace_id,
                    subject_id=subject_id,
                    resource_id=parent_resource_id,
                    action=action,
                    effect="ALLOW" if allowed_count else "DENY",
                    reason_codes=reasons,
                    policy_versions=policy_versions,
                    evaluation_context={
                        "kind": "resource_set",
                        "evaluated_count": len(items),
                        "allowed_count": allowed_count,
                        "authentication_assurance": items[
                            0
                        ].decision.authentication_assurance.value,
                        "authentication_time": (
                            items[0].decision.authentication_time.isoformat()
                            if items[0].decision.authentication_time is not None
                            else None
                        ),
                        "items": [
                            {
                                "resource_id": str(item.resource_id),
                                "effect": item.decision.effect.value,
                                "reason_codes": list(item.decision.reason_codes),
                            }
                            for item in items
                        ],
                    },
                    request_id=request_id,
                    decided_at=datetime.now().astimezone(),
                )
            )
            await session.commit()


class SqlSubjectReader(SubjectReader):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_subject(
        self, *, issuer: str, external_subject: str, workspace_id: UUID
    ) -> SubjectAttributes:
        statement = (
            select(SubjectModel, WorkspaceMembershipModel)
            .join(
                WorkspaceMembershipModel,
                WorkspaceMembershipModel.subject_id == SubjectModel.id,
            )
            .where(
                SubjectModel.issuer == issuer,
                SubjectModel.external_subject == external_subject,
                SubjectModel.active.is_(True),
                WorkspaceMembershipModel.workspace_id == workspace_id,
                WorkspaceMembershipModel.active.is_(True),
                or_(
                    WorkspaceMembershipModel.access_expires_at.is_(None),
                    WorkspaceMembershipModel.access_expires_at > func.now(),
                ),
            )
        )
        row = (await self._session.execute(statement)).one_or_none()
        if row is None:
            raise ForbiddenError("No active workspace membership exists.")
        subject, membership = row
        return await self._effective_subject_attributes(
            subject=subject,
            membership=membership,
        )

    async def refresh_subject(
        self,
        *,
        subject: SubjectAttributes,
        now: datetime,
    ) -> SubjectAttributes:
        row = (
            await self._session.execute(
                select(SubjectModel, WorkspaceMembershipModel)
                .join(
                    WorkspaceMembershipModel,
                    WorkspaceMembershipModel.subject_id == SubjectModel.id,
                )
                .where(
                    SubjectModel.id == subject.subject_id,
                    WorkspaceMembershipModel.workspace_id == subject.workspace_id,
                )
            )
        ).one_or_none()
        if row is None:
            raise ForbiddenError("No current workspace membership exists.")
        subject_model, membership = row
        refreshed = await self._effective_subject_attributes(
            subject=subject_model,
            membership=membership,
            observed_at=now,
        )
        return with_authentication_context(
            refreshed,
            authentication_time=subject.authentication_time,
            authentication_assurance=subject.authentication_assurance,
        )

    async def get_default_workspace_id(self, *, issuer: str, external_subject: str) -> UUID | None:
        """Return only the caller's deterministic active-workspace selection.

        Authentication hydration has no `X-Workspace-Id` yet, while normal IAM
        reads are forced through workspace RLS.  The database function is a
        narrowly scoped SECURITY DEFINER boundary: it receives the verified
        issuer/subject pair, considers active memberships only, and returns one
        UUID.  It cannot enumerate memberships or grant any workspace access.
        """
        workspace_id = (
            await self._session.execute(
                text("SELECT iam.resolve_default_workspace(:issuer, :external_subject)"),
                {"issuer": issuer, "external_subject": external_subject},
            )
        ).scalar_one_or_none()
        return workspace_id if isinstance(workspace_id, UUID) else None

    async def _effective_subject_attributes(
        self,
        *,
        subject: SubjectModel,
        membership: WorkspaceMembershipModel,
        observed_at: datetime | None = None,
    ) -> SubjectAttributes:
        base = subject_attributes_from_models(
            subject=subject,
            membership=membership,
            observed_at=observed_at,
        )
        binding = await self._session.get(
            CanonicalAdminBindingModel,
            {"workspace_id": membership.workspace_id, "subject_id": subject.id},
        )
        if binding is not None:
            role = (
                await self._session.scalars(
                    select(AccessRoleModel).where(
                        AccessRoleModel.workspace_id == membership.workspace_id,
                        AccessRoleModel.id == binding.canonical_role_id,
                    )
                )
            ).one_or_none()
            if _canonical_admin_binding_is_current(
                subject=subject,
                membership=membership,
                binding=binding,
                role=role,
                now=observed_at or utc_now(),
            ):
                return replace(
                    base,
                    allowed_actions=DEFAULT_HUMAN_ADMIN_ACTIONS,
                    allowed_system_ids=await self._active_responsibility_system_ids(
                        workspace_id=membership.workspace_id,
                        subject_id=subject.id,
                    ),
                    effective_profile_role=ProfileRoleTier.ADMIN.value,
                )

        assignment = await self._session.get(
            ProfileRoleAssignmentModel,
            {"workspace_id": membership.workspace_id, "subject_id": subject.id},
        )
        if assignment is None:
            if binding is None:
                return base
            return replace(
                base,
                allowed_actions=frozenset(),
                allowed_system_ids=frozenset(),
                effective_profile_role=(
                    EffectiveProfileRoleStatus.REVOKED.value
                    if binding.state == "REVOKED"
                    else EffectiveProfileRoleStatus.STALE.value
                ),
            )
        if assignment.state != "ACTIVE":
            return replace(
                base,
                allowed_actions=frozenset(),
                allowed_system_ids=frozenset(),
                effective_profile_role=EffectiveProfileRoleStatus.REVOKED.value,
            )
        try:
            tier = ProfileRoleTier(assignment.tier)
            policy = PROFILE_ROLE_BY_TIER[tier]
        except (KeyError, ValueError):
            return replace(
                base,
                allowed_actions=frozenset(),
                allowed_system_ids=frozenset(),
                effective_profile_role=EffectiveProfileRoleStatus.STALE.value,
            )
        if (
            tier is ProfileRoleTier.ADMIN
            or assignment.policy_version != PROFILE_ROLE_POLICY_VERSION
            or assignment.materialized_actions_hash != policy.materialized_actions_hash
            or assignment.membership_version != membership.version
            or base.allowed_actions != policy.allowed_actions
            or base.allowed_system_ids
            or "security-administrators" in base.groups
            or any(group.startswith("datariver-role-") for group in base.groups)
        ):
            return replace(
                base,
                allowed_actions=frozenset(),
                allowed_system_ids=frozenset(),
                effective_profile_role=EffectiveProfileRoleStatus.STALE.value,
            )
        system_ids = (
            await self._active_responsibility_system_ids(
                workspace_id=membership.workspace_id,
                subject_id=subject.id,
            )
            if policy.assignable_to_system
            else frozenset()
        )
        return replace(
            base,
            allowed_actions=policy.allowed_actions,
            allowed_system_ids=system_ids,
            effective_profile_role=tier.value,
        )

    async def _active_responsibility_system_ids(
        self,
        *,
        workspace_id: UUID,
        subject_id: UUID,
    ) -> frozenset[UUID]:
        values = await self._session.scalars(
            select(SystemAssigneeModel.system_id)
            .join(
                DataSystemModel,
                and_(
                    DataSystemModel.workspace_id == SystemAssigneeModel.workspace_id,
                    DataSystemModel.id == SystemAssigneeModel.system_id,
                ),
            )
            .where(
                SystemAssigneeModel.workspace_id == workspace_id,
                SystemAssigneeModel.subject_id == subject_id,
                SystemAssigneeModel.active.is_(True),
                DataSystemModel.active.is_(True),
            )
        )
        return frozenset(values.all())

    async def record_authenticated_profile(
        self,
        *,
        issuer: str,
        external_subject: str,
        email: str | None,
        source_ip: str | None,
        observed_at: datetime,
    ) -> None:
        """Persist only token-sourced identity profile and ordinary access audit fields."""
        await self._session.execute(
            update(SubjectModel)
            .where(
                SubjectModel.issuer == issuer,
                SubjectModel.external_subject == external_subject,
            )
            .values(email=email, last_login_at=observed_at, last_login_ip=source_ip)
        )


def _canonical_admin_binding_is_current(
    *,
    subject: SubjectModel,
    membership: WorkspaceMembershipModel,
    binding: CanonicalAdminBindingModel,
    role: AccessRoleModel | None,
    now: datetime,
) -> bool:
    expected_actions = {action.value for action in DEFAULT_HUMAN_ADMIN_ACTIONS}
    attributes = membership.attributes
    try:
        groups = {str(value) for value in attributes.get("groups", [])}
        allowed = {str(value) for value in attributes.get("allowed_actions", [])}
        denied = {str(value) for value in attributes.get("denied_actions", [])}
        system_ids = sorted(
            str(UUID(str(value))) for value in attributes.get("allowed_system_ids", [])
        )
        domain_ids = sorted(
            str(UUID(str(value))) for value in attributes.get("allowed_domain_ids", [])
        )
        access_hash = canonical_json_hash(
            {
                "active": membership.active,
                "clearance": Classification(membership.clearance).name,
                "groups": sorted(groups),
                "allowed_actions": sorted(Action(value).value for value in allowed),
                "denied_actions": sorted(Action(value).value for value in denied),
                "allowed_system_ids": system_ids,
                "allowed_domain_ids": domain_ids,
            }
        )
    except (TypeError, ValueError):
        return False
    return bool(
        binding.state == "ACTIVE"
        and subject.active
        and membership.active
        and (membership.access_expires_at is None or membership.access_expires_at > now)
        and membership.job_function != "SERVICE_ACCOUNT"
        and membership.clearance == int(Classification.RESTRICTED)
        and "security-administrators" in groups
        and "service-accounts" not in groups
        and not any(group.startswith("datariver-role-") for group in groups)
        and allowed == expected_actions
        and not denied
        and not system_ids
        and role is not None
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
        and binding.capability_catalog_version == CAPABILITY_CATALOG_VERSION
        and binding.capability_hash == CANONICAL_ADMIN_CAPABILITY_HASH
        and binding.membership_version == membership.version
        and binding.membership_access_hash == access_hash
    )


def subject_attributes_from_models(
    *,
    subject: SubjectModel,
    membership: WorkspaceMembershipModel,
    observed_at: datetime | None = None,
) -> SubjectAttributes:
    effective_observed_at = observed_at or utc_now()
    attributes = membership.attributes
    try:
        allowed_actions = frozenset(
            Action(value) for value in attributes.get("allowed_actions", [])
        )
        denied_actions = frozenset(Action(value) for value in attributes.get("denied_actions", []))
        allowed_system_ids = frozenset(
            UUID(value) for value in attributes.get("allowed_system_ids", [])
        )
        allowed_domain_ids = frozenset(
            UUID(value) for value in attributes.get("allowed_domain_ids", [])
        )
        groups = frozenset(str(value) for value in attributes.get("groups", []))
        clearance = Classification(membership.clearance)
    except (TypeError, ValueError) as error:
        raise ForbiddenError("Workspace security attributes are invalid.") from error
    return SubjectAttributes(
        subject_id=subject.id,
        workspace_id=membership.workspace_id,
        active=(
            subject.active
            and membership.active
            and (
                membership.access_expires_at is None
                or membership.access_expires_at > effective_observed_at
            )
        ),
        department_id=membership.department_id,
        groups=groups,
        job_function=membership.job_function,
        clearance=clearance,
        allowed_system_ids=allowed_system_ids,
        allowed_domain_ids=allowed_domain_ids,
        allowed_actions=allowed_actions,
        denied_actions=denied_actions,
    )


def with_authentication_context(
    subject: SubjectAttributes,
    *,
    authentication_time: datetime | None,
    authentication_assurance: AuthenticationAssurance,
) -> SubjectAttributes:
    return replace(
        subject,
        authentication_time=authentication_time,
        authentication_assurance=authentication_assurance,
    )
