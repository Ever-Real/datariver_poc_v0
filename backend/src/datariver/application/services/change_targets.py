from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.ports import CatalogIndexReader
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ForbiddenError, ValidationError
from datariver.domain.governance import ChangeItem


class CatalogChangeTargetAuthorizer:
    """Bind provider-shaped change items to authorized local catalog assets."""

    def __init__(
        self,
        *,
        index: CatalogIndexReader,
        classification_access: ClassificationAccessResolver,
        authorization: AuthorizationService,
    ) -> None:
        self._index = index
        self._classification_access = classification_access
        self._authorization = authorization

    async def authorize_targets(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        items: Sequence[ChangeItem],
        request_classification: Classification,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> None:
        external_urns = tuple(dict.fromkeys(item.target_ref for item in items))
        access = await self._classification_access.resolve(
            workspace_id=workspace_id,
            subject_id=subject.subject_id,
            now=environment.requested_at,
        )
        assets = tuple(
            await self._index.get_authorized_assets_by_external_urns(
                subject=subject,
                access=access,
                external_urns=external_urns,
            )
        )
        assets_by_urn = {asset.external_urn: asset for asset in assets}
        if (
            len(assets) != len(external_urns)
            or set(assets_by_urn) != set(external_urns)
            or any(asset.workspace_id != workspace_id for asset in assets)
            or any(asset.asset_type != "DATASET" for asset in assets)
            or any(not asset.external_urn.startswith("urn:li:dataset:") for asset in assets)
        ):
            raise ForbiddenError("One or more change targets are not available.")

        maximum_target_classification = max(
            (asset.classification for asset in assets),
            default=Classification.PUBLIC,
        )
        if request_classification < maximum_target_classification:
            raise ValidationError(
                "The change-request classification cannot be lower than its target.",
                details={"minimum_classification": maximum_target_classification.name},
            )

        resources = tuple(
            ResourceAttributes(
                resource_id=asset.asset_id,
                workspace_id=workspace_id,
                resource_type="catalog_asset_change_target",
                owner_department_id=asset.owner_department_id,
                system_id=asset.system_id,
                domain_id=asset.domain_id,
                classification=asset.classification,
                lifecycle=asset.lifecycle,
            )
            for asset in assets
        )
        authorized = await self._authorization.filter_authorized(
            subject=subject,
            resources=resources,
            action=Action.CHANGE_CREATE,
            environment=environment,
            request_id=request_id,
            parent_resource_id=workspace_id,
        )
        if len(authorized) != len(resources):
            raise ForbiddenError("One or more change targets are not available.")
