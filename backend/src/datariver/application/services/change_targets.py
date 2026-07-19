from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from uuid import UUID

from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.dto import CatalogAssetIndex
from datariver.application.ports import CatalogChangeTargetReader
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ConflictError, ForbiddenError, ValidationError
from datariver.domain.governance import (
    DATAHUB_INTAKE_TARGET,
    MANUAL_DATASET_INTAKE_TARGET,
    ChangeItem,
    ChangeRequest,
    change_target_binding_hash,
)


class CatalogChangeTargetAuthorizer:
    """Bind provider-shaped change items to authorized local catalog assets."""

    def __init__(
        self,
        *,
        index: CatalogChangeTargetReader,
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
    ) -> tuple[ChangeItem, ...]:
        external_urns = tuple(
            dict.fromkeys(
                item.target_ref
                for item in items
                if item.target_type in {"DATAHUB_ASPECT", DATAHUB_INTAKE_TARGET}
            )
        )
        manual_items = tuple(
            item for item in items if item.target_type == MANUAL_DATASET_INTAKE_TARGET
        )
        if len(external_urns) + len(manual_items) != len(items):
            raise ValidationError("A change item target type is not governed.")
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
                lock_for_share=True,
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
        assets_by_urn = {asset.external_urn: asset for asset in assets}
        return tuple(
            (
                self._bind(item, assets_by_urn[item.target_ref])
                if item.target_type in {"DATAHUB_ASPECT", DATAHUB_INTAKE_TARGET}
                else item
            )
            for item in items
        )

    async def filter_authorized_change_requests(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        change_requests: Sequence[ChangeRequest],
        action: Action,
        environment: EnvironmentAttributes,
        request_id: str,
        strict_binding: bool,
    ) -> tuple[ChangeRequest, ...]:
        if not change_requests:
            return ()
        external_urns = tuple(
            dict.fromkeys(
                item.target_ref
                for change_request in change_requests
                for item in change_request.items
                if item.target_type in {"DATAHUB_ASPECT", DATAHUB_INTAKE_TARGET}
            )
        )
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
                lock_for_share=strict_binding,
            )
        )
        assets_by_urn = {asset.external_urn: asset for asset in assets}
        candidates: list[tuple[ChangeRequest, list[ResourceAttributes]]] = []
        for change_request in change_requests:
            resources: list[ResourceAttributes] = []
            drifted = False
            for item in change_request.items:
                if item.target_type == MANUAL_DATASET_INTAKE_TARGET:
                    continue
                asset = assets_by_urn.get(item.target_ref)
                if asset is None or not self._binding_is_current(
                    workspace_id=workspace_id,
                    item=item,
                    asset=asset,
                    strict_binding=strict_binding,
                ):
                    drifted = True
                    break
                if change_request.classification < asset.classification:
                    drifted = True
                    break
                resources.append(
                    ResourceAttributes(
                        resource_id=asset.asset_id,
                        workspace_id=workspace_id,
                        resource_type="catalog_asset_change_target",
                        owner_department_id=asset.owner_department_id,
                        system_id=asset.system_id,
                        domain_id=asset.domain_id,
                        classification=asset.classification,
                        lifecycle=asset.lifecycle,
                        requester_id=change_request.requester_id,
                    )
                )
            if drifted or len(resources) != len(change_request.items):
                if strict_binding:
                    raise ConflictError(
                        "The catalog target binding changed after this request was prepared.",
                        details={"code": "TARGET_BINDING_DRIFT"},
                    )
                continue
            candidates.append((change_request, resources))

        flattened = tuple(resource for _, resources in candidates for resource in resources)
        authorized = await self._authorization.filter_authorized(
            subject=subject,
            resources=flattened,
            action=action,
            environment=environment,
            request_id=request_id,
            parent_resource_id=workspace_id,
        )
        authorized_ids = {resource.resource_id for resource in authorized}
        return tuple(
            change_request
            for change_request, resources in candidates
            if all(resource.resource_id in authorized_ids for resource in resources)
        )

    @staticmethod
    def _bind(item: ChangeItem, asset: CatalogAssetIndex) -> ChangeItem:
        binding_hash = change_target_binding_hash(
            target_ref=item.target_ref,
            asset_id=asset.asset_id,
            asset_type=asset.asset_type,
            system_id=asset.system_id,
            domain_id=asset.domain_id,
            owner_department_id=asset.owner_department_id,
            classification=asset.classification,
            lifecycle=asset.lifecycle,
        )
        return replace(
            item,
            target_asset_id=asset.asset_id,
            target_asset_type=asset.asset_type,
            target_system_id=asset.system_id,
            target_domain_id=asset.domain_id,
            target_owner_department_id=asset.owner_department_id,
            target_classification=asset.classification,
            target_lifecycle=asset.lifecycle,
            target_source_version=asset.source_version,
            target_observed_at=asset.observed_at,
            target_binding_hash=binding_hash,
        )

    @staticmethod
    def _binding_is_current(
        *, workspace_id: UUID, item: ChangeItem, asset: CatalogAssetIndex, strict_binding: bool
    ) -> bool:
        if (
            not item.has_complete_target_binding
            or item.expected_target_binding_hash() != item.target_binding_hash
            or asset.workspace_id != workspace_id
            or asset.asset_id != item.target_asset_id
            or asset.asset_type != "DATASET"
            or asset.external_urn != item.target_ref
            or asset.lifecycle != "ACTIVE"
        ):
            return False
        if not strict_binding:
            return True
        current_hash = change_target_binding_hash(
            target_ref=item.target_ref,
            asset_id=asset.asset_id,
            asset_type=asset.asset_type,
            system_id=asset.system_id,
            domain_id=asset.domain_id,
            owner_department_id=asset.owner_department_id,
            classification=asset.classification,
            lifecycle=asset.lifecycle,
        )
        return current_hash == item.target_binding_hash
