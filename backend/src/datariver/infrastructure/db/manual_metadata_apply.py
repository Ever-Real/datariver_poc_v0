from __future__ import annotations

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.manual_metadata_apply import ManualMetadataApplyEligibility
from datariver.application.services.registration_worker import (
    require_registration_operator_identity,
)
from datariver.domain.authz import Action, EnvironmentAttributes, ResourceAttributes
from datariver.domain.catalog import is_dataset_asset_type
from datariver.domain.common import ConflictError, ForbiddenError, utc_now
from datariver.domain.manual_metadata import ManualMetadataSubmission
from datariver.infrastructure.db.authz import SqlDecisionWriter, subject_attributes_from_models
from datariver.infrastructure.db.catalog import SqlCatalogIndexReader
from datariver.infrastructure.db.classification_access import (
    SqlClassificationAccessSnapshotReader,
)
from datariver.infrastructure.db.models.platform import SubjectModel, WorkspaceMembershipModel
from datariver.infrastructure.db.rls import set_security_context


class SqlManualMetadataApplyEligibility(ManualMetadataApplyEligibility):
    """Re-evaluate requester membership, policy scope and the canonical local target."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._authorization = AuthorizationService(
            decision_writer=SqlDecisionWriter(session_factory)
        )

    async def authorize(
        self,
        *,
        submission: ManualMetadataSubmission,
        request_id: str,
    ) -> None:
        now = utc_now()
        async with self._session_factory() as session:
            await set_security_context(
                session,
                workspace_id=submission.workspace_id,
                subject_id=submission.requester_id,
            )
            row = (
                await session.execute(
                    select(SubjectModel, WorkspaceMembershipModel)
                    .join(
                        WorkspaceMembershipModel,
                        and_(
                            WorkspaceMembershipModel.subject_id == SubjectModel.id,
                            WorkspaceMembershipModel.workspace_id == submission.workspace_id,
                        ),
                    )
                    .where(
                        SubjectModel.id == submission.requester_id,
                        SubjectModel.active.is_(True),
                        WorkspaceMembershipModel.active.is_(True),
                        or_(
                            WorkspaceMembershipModel.access_expires_at.is_(None),
                            WorkspaceMembershipModel.access_expires_at > func.now(),
                        ),
                    )
                )
            ).one_or_none()
            if row is None:
                raise ForbiddenError("The manual metadata requester is no longer active.")
            subject_model, membership = row
            subject = subject_attributes_from_models(
                subject=subject_model,
                membership=membership,
            )
            require_registration_operator_identity(subject)
            access = await ClassificationAccessResolver(
                SqlClassificationAccessSnapshotReader(session)
            ).resolve(
                workspace_id=submission.workspace_id,
                subject_id=submission.requester_id,
                now=now,
            )
            detail = await SqlCatalogIndexReader(session).get_authorized_asset(
                subject=subject,
                access=access,
                asset_id=submission.asset_id,
            )
            if (
                detail is None
                or not is_dataset_asset_type(detail.index.asset_type)
                or detail.index.lifecycle != "ACTIVE"
                or detail.index.external_urn != submission.external_urn
                or detail.index.source_version != submission.source_version
            ):
                raise ConflictError(
                    "The manual metadata target changed before apply.",
                    details={"code": "APPLY_TARGET_DRIFT"},
                )
            resource = ResourceAttributes(
                resource_id=detail.index.asset_id,
                workspace_id=detail.index.workspace_id,
                resource_type="manual_metadata_apply_target",
                owner_department_id=detail.index.owner_department_id,
                system_id=detail.index.system_id,
                domain_id=detail.index.domain_id,
                classification=detail.index.classification,
                lifecycle=detail.index.lifecycle,
            )
        environment = EnvironmentAttributes(
            requested_at=now,
            purpose="manual_metadata_apply",
            client_type="worker",
        )
        await self._authorization.authorize(
            subject=subject,
            resource=resource,
            action=Action.CATALOG_READ,
            environment=environment,
            request_id=request_id,
        )
        await self._authorization.authorize(
            subject=subject,
            resource=resource,
            action=Action.REGISTRATION_CREATE,
            environment=environment,
            request_id=request_id,
        )
