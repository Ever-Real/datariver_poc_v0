from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from uuid import UUID

from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.dto import (
    CatalogAssetIndex,
    ChangeRequestSummaryRecord,
    ChangeRequestSummaryTarget,
)
from datariver.application.ports import CatalogChangeTargetReader
from datariver.application.services.authorization import AuthorizationService
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    ResourceAttributes,
    SubjectAttributes,
)
from datariver.domain.catalog import is_dataset_asset_type
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
            or any(not is_dataset_asset_type(asset.asset_type) for asset in assets)
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
        bound = tuple(
            (
                self._bind(item, assets_by_urn[item.target_ref])
                if item.target_type in {"DATAHUB_ASPECT", DATAHUB_INTAKE_TARGET}
                else item
            )
            for item in items
        )
        if any(item.routing_system_id is None for item in bound):
            raise ValidationError(
                "Every change target must resolve to a canonical active data system."
            )
        return bound

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
                    if item.routing_system_id is None:
                        drifted = True
                        break
                    resources.append(
                        ResourceAttributes(
                            resource_id=item.item_id,
                            workspace_id=workspace_id,
                            resource_type="manual_change_target",
                            owner_department_id=None,
                            system_id=item.routing_system_id,
                            domain_id=None,
                            classification=change_request.classification,
                            lifecycle=change_request.state.value,
                            requester_id=change_request.requester_id,
                        )
                    )
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

    async def filter_authorized_summaries(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        summaries: Sequence[ChangeRequestSummaryRecord],
        action: Action,
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> tuple[ChangeRequestSummaryRecord, ...]:
        """Authorize a bounded list projection without hydrating provider documents."""

        if not summaries:
            return ()
        external_urns = tuple(
            dict.fromkeys(
                target.target_ref
                for summary in summaries
                for target in summary.targets
                if target.target_type in {"DATAHUB_ASPECT", DATAHUB_INTAKE_TARGET}
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
                lock_for_share=False,
            )
        )
        assets_by_urn = {asset.external_urn: asset for asset in assets}
        candidates: list[tuple[ChangeRequestSummaryRecord, tuple[ResourceAttributes, ...]]] = []
        for summary in summaries:
            resources: list[ResourceAttributes] = []
            for target in summary.targets:
                if target.target_type == MANUAL_DATASET_INTAKE_TARGET:
                    if target.routing_system_id is None:
                        resources = []
                        break
                    resources.append(
                        ResourceAttributes(
                            resource_id=target.item_id,
                            workspace_id=workspace_id,
                            resource_type="manual_change_target",
                            owner_department_id=None,
                            system_id=target.routing_system_id,
                            domain_id=None,
                            classification=summary.classification,
                            lifecycle=summary.state.value,
                            requester_id=summary.requester_id,
                        )
                    )
                    continue
                asset = assets_by_urn.get(target.target_ref)
                if (
                    asset is None
                    or not self._summary_binding_is_current(
                        workspace_id=workspace_id,
                        target=target,
                        asset=asset,
                    )
                    or summary.classification < asset.classification
                ):
                    resources = []
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
                        requester_id=summary.requester_id,
                    )
                )
            if resources and len(resources) == len(summary.targets):
                candidates.append((summary, tuple(resources)))

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
            summary
            for summary, resources in candidates
            if all(resource.resource_id in authorized_ids for resource in resources)
        )

    async def authorize_approval_targets(
        self,
        *,
        workspace_id: UUID,
        subject: SubjectAttributes,
        change_request: ChangeRequest,
        action: Action,
        approval_system_ids: frozenset[UUID],
        environment: EnvironmentAttributes,
        request_id: str,
    ) -> frozenset[UUID]:
        """Authorize only the targets covered by the actor's current workflow authority.

        Multi-system approval is deliberately different from aggregate CR access. The
        workflow authority reader establishes which systems the actor can represent;
        this method then verifies and authorizes only those target resources. It never
        reads unrelated provider URNs, so a system-scoped approver cannot infer them
        through an approval response or authorization side effect.
        """

        if not approval_system_ids:
            return frozenset()
        scoped_items = tuple(
            item
            for item in change_request.items
            if (item.routing_system_id or item.target_system_id) in approval_system_ids
        )
        if not scoped_items:
            raise ForbiddenError("No change target is covered by the actor's authority.")
        external_urns = tuple(
            dict.fromkeys(
                item.target_ref
                for item in scoped_items
                if item.target_type in {"DATAHUB_ASPECT", DATAHUB_INTAKE_TARGET}
            )
        )
        assets: tuple[CatalogAssetIndex, ...] = ()
        if external_urns:
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
            if (
                len(assets) != len(external_urns)
                or {asset.external_urn for asset in assets} != set(external_urns)
                or any(asset.workspace_id != workspace_id for asset in assets)
                or any(not is_dataset_asset_type(asset.asset_type) for asset in assets)
            ):
                raise ConflictError(
                    "The catalog target binding changed after this request was prepared.",
                    details={"code": "TARGET_BINDING_DRIFT"},
                )
        assets_by_urn = {asset.external_urn: asset for asset in assets}
        resources: list[ResourceAttributes] = []
        for item in scoped_items:
            if item.target_type == MANUAL_DATASET_INTAKE_TARGET:
                if item.routing_system_id not in approval_system_ids:
                    raise ForbiddenError("The change target is not available.")
                resources.append(
                    ResourceAttributes(
                        resource_id=item.item_id,
                        workspace_id=workspace_id,
                        resource_type="manual_change_target",
                        owner_department_id=None,
                        system_id=item.routing_system_id,
                        domain_id=None,
                        classification=change_request.classification,
                        lifecycle=change_request.state.value,
                        requester_id=change_request.requester_id,
                    )
                )
                continue
            asset = assets_by_urn.get(item.target_ref)
            if asset is None or not self._binding_is_current(
                workspace_id=workspace_id,
                item=item,
                asset=asset,
                strict_binding=True,
            ):
                raise ConflictError(
                    "The catalog target binding changed after this request was prepared.",
                    details={"code": "TARGET_BINDING_DRIFT"},
                )
            if change_request.classification < asset.classification:
                raise ConflictError(
                    "The catalog target binding changed after this request was prepared.",
                    details={"code": "TARGET_BINDING_DRIFT"},
                )
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
        authorized = await self._authorization.filter_authorized(
            subject=subject,
            resources=resources,
            action=action,
            environment=environment,
            request_id=request_id,
            parent_resource_id=workspace_id,
        )
        if len(authorized) != len(resources):
            raise ForbiddenError("The change target is not available.")
        return frozenset(item.item_id for item in scoped_items)

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
            routing_system_id=asset.system_id,
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
            or not is_dataset_asset_type(asset.asset_type)
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

    @staticmethod
    def _summary_binding_is_current(
        *,
        workspace_id: UUID,
        target: ChangeRequestSummaryTarget,
        asset: CatalogAssetIndex,
    ) -> bool:
        if (
            target.target_asset_id is None
            or target.target_asset_type is None
            or target.target_classification is None
            or target.target_lifecycle is None
            or target.target_source_version is None
            or target.target_observed_at is None
            or target.target_binding_hash is None
            or asset.workspace_id != workspace_id
            or asset.asset_id != target.target_asset_id
            or not is_dataset_asset_type(asset.asset_type)
            or asset.external_urn != target.target_ref
            or asset.lifecycle != "ACTIVE"
        ):
            return False
        expected = change_target_binding_hash(
            target_ref=target.target_ref,
            asset_id=target.target_asset_id,
            asset_type=target.target_asset_type,
            system_id=target.target_system_id,
            domain_id=target.target_domain_id,
            owner_department_id=target.target_owner_department_id,
            classification=target.target_classification,
            lifecycle=target.target_lifecycle,
        )
        return expected == target.target_binding_hash
