from __future__ import annotations

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.services.authorization import AuthorizationService
from datariver.application.services.change_targets import CatalogChangeTargetAuthorizer
from datariver.application.services.governance import GovernanceService
from datariver.infrastructure.db.authz import SqlDecisionWriter
from datariver.infrastructure.db.catalog import SqlCatalogChangeTargetReader
from datariver.infrastructure.db.classification_access import (
    SqlClassificationAccessSnapshotReader,
)
from datariver.infrastructure.db.governance import SqlGovernanceUnitOfWork
from datariver.interfaces.http.dependencies import get_container


def governance_service(
    request: Request,
    session: AsyncSession | None = None,
) -> GovernanceService:
    """Construct the canonical Change Request service for authenticated HTTP reads."""

    container = get_container(request)
    authorization = AuthorizationService(
        decision_writer=SqlDecisionWriter(container.database.session_factory)
    )
    return GovernanceService(
        lambda: SqlGovernanceUnitOfWork(
            container.database.session_factory,
            session=session,
        ),
        authorization,
        target_authorizer=(
            CatalogChangeTargetAuthorizer(
                index=SqlCatalogChangeTargetReader(session),
                classification_access=ClassificationAccessResolver(
                    SqlClassificationAccessSnapshotReader(session)
                ),
                authorization=authorization,
            )
            if session is not None
            else None
        ),
    )
