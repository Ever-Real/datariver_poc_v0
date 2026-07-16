from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
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
from datariver.domain.common import ForbiddenError
from datariver.infrastructure.db.models.authz import PolicyDecisionModel
from datariver.infrastructure.db.models.platform import SubjectModel, WorkspaceMembershipModel
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
            )
        )
        row = (await self._session.execute(statement)).one_or_none()
        if row is None:
            raise ForbiddenError("No active workspace membership exists.")
        subject, membership = row
        return subject_attributes_from_models(subject=subject, membership=membership)


def subject_attributes_from_models(
    *, subject: SubjectModel, membership: WorkspaceMembershipModel
) -> SubjectAttributes:
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
        active=subject.active and membership.active,
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
