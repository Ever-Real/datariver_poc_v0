from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from datariver.application.classification_access import ClassificationAccessResolver
from datariver.application.dto import CatalogAssetIndex
from datariver.application.services.authorization import AuthorizationService, NullDecisionWriter
from datariver.application.services.change_targets import CatalogChangeTargetAuthorizer
from datariver.domain.authz import (
    Action,
    Classification,
    EnvironmentAttributes,
    SubjectAttributes,
)
from datariver.domain.common import ConflictError, ForbiddenError, ValidationError
from datariver.domain.governance import ChangeItem, ChangeRequest


class NoPolicySnapshot:
    async def read_candidate(self, **_: object) -> None:
        return None


class MemoryCatalogIndex:
    def __init__(self, assets: tuple[CatalogAssetIndex, ...]) -> None:
        self.assets = assets
        self.calls = 0

    async def get_authorized_assets_by_external_urns(
        self, *, external_urns: tuple[str, ...], **_: object
    ) -> tuple[CatalogAssetIndex, ...]:
        self.calls += 1
        allowed = set(external_urns)
        return tuple(asset for asset in self.assets if asset.external_urn in allowed)


def asset(
    *,
    workspace_id: UUID,
    classification: Classification = Classification.INTERNAL,
    system_id: UUID | None = None,
    asset_type: str = "DATASET",
    external_urn: str = "urn:li:dataset:test",
) -> CatalogAssetIndex:
    return CatalogAssetIndex(
        asset_id=uuid4(),
        workspace_id=workspace_id,
        external_urn=external_urn,
        asset_type=asset_type,
        name="orders",
        description=None,
        platform="postgres",
        domain_id=None,
        system_id=system_id,
        owner_department_id=None,
        classification=classification,
        lifecycle="ACTIVE",
        source_version="1",
        observed_at=datetime.now(UTC),
    )


def item(*, target_ref: str = "urn:li:dataset:test") -> ChangeItem:
    return ChangeItem(
        item_id=uuid4(),
        target_type="DATAHUB_ASPECT",
        target_ref=target_ref,
        operation="UPSERT",
        after_document={"description": "governed"},
        aspect_name="datasetProperties",
        before_hash="b" * 64,
    )


def subject(
    *,
    workspace_id: UUID,
    system_id: UUID | None = None,
    action: Action = Action.CHANGE_CREATE,
) -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function=None,
        clearance=Classification.CONFIDENTIAL,
        allowed_system_ids=frozenset({system_id}) if system_id is not None else frozenset(),
        allowed_actions=frozenset({action}),
    )


def authorizer(assets: tuple[CatalogAssetIndex, ...]) -> CatalogChangeTargetAuthorizer:
    return CatalogChangeTargetAuthorizer(
        index=MemoryCatalogIndex(assets),  # type: ignore[arg-type]
        classification_access=ClassificationAccessResolver(NoPolicySnapshot()),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    )


@pytest.mark.asyncio
async def test_authorizes_local_target_with_actual_asset_scope() -> None:
    workspace_id = uuid4()
    system_id = uuid4()

    target = asset(workspace_id=workspace_id, system_id=system_id)
    bound = await authorizer((target,)).authorize_targets(
        workspace_id=workspace_id,
        subject=subject(workspace_id=workspace_id, system_id=system_id),
        items=(item(),),
        request_classification=Classification.INTERNAL,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-1",
    )
    assert bound[0].target_asset_id == target.asset_id
    assert bound[0].target_system_id == system_id
    assert bound[0].target_classification is Classification.INTERNAL
    assert bound[0].target_binding_hash == bound[0].expected_target_binding_hash()


@pytest.mark.asyncio
async def test_current_target_authorization_ignores_source_only_drift_but_rejects_scope_drift() -> (
    None
):
    workspace_id = uuid4()
    system_id = uuid4()
    target = asset(workspace_id=workspace_id, system_id=system_id)
    service = authorizer((target,))
    actor = subject(
        workspace_id=workspace_id,
        system_id=system_id,
        action=Action.CHANGE_REVIEW,
    )
    bound = await service.authorize_targets(
        workspace_id=workspace_id,
        subject=replace(actor, allowed_actions=frozenset({Action.CHANGE_CREATE})),
        items=(item(),),
        request_classification=Classification.INTERNAL,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="bind",
    )
    request = ChangeRequest.create(
        workspace_id=workspace_id,
        number="CR-1",
        request_type="CATALOG_METADATA",
        title="Update",
        description="",
        requester_id=uuid4(),
        items=list(bound),
    )
    source_only = replace(target, source_version="2", observed_at=datetime.now(UTC))
    service._index.assets = (source_only,)  # type: ignore[attr-defined]
    assert await service.filter_authorized_change_requests(
        workspace_id=workspace_id,
        subject=actor,
        change_requests=(request,),
        action=Action.CHANGE_REVIEW,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="review-source-only",
        strict_binding=True,
    ) == (request,)

    service._index.assets = (replace(source_only, system_id=uuid4()),)  # type: ignore[attr-defined]
    with pytest.raises(ConflictError, match="binding changed"):
        await service.filter_authorized_change_requests(
            workspace_id=workspace_id,
            subject=actor,
            change_requests=(request,),
            action=Action.CHANGE_REVIEW,
            environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
            request_id="review-scope-drift",
            strict_binding=True,
        )


@pytest.mark.asyncio
async def test_list_resolves_targets_once_and_omits_any_request_outside_current_scope() -> None:
    workspace_id = uuid4()
    first_system = uuid4()
    second_system = uuid4()
    first_asset = asset(
        workspace_id=workspace_id,
        system_id=first_system,
        external_urn="urn:li:dataset:first",
    )
    second_asset = asset(
        workspace_id=workspace_id,
        system_id=second_system,
        external_urn="urn:li:dataset:second",
    )
    index = MemoryCatalogIndex((first_asset, second_asset))
    service = CatalogChangeTargetAuthorizer(
        index=index,  # type: ignore[arg-type]
        classification_access=ClassificationAccessResolver(NoPolicySnapshot()),
        authorization=AuthorizationService(decision_writer=NullDecisionWriter()),
    )
    maker = replace(
        subject(workspace_id=workspace_id, system_id=first_system),
        allowed_system_ids=frozenset({first_system, second_system}),
    )
    bindings = await service.authorize_targets(
        workspace_id=workspace_id,
        subject=maker,
        items=(
            item(target_ref=first_asset.external_urn),
            item(target_ref=second_asset.external_urn),
        ),
        request_classification=Classification.INTERNAL,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="bind-list",
    )
    requests = tuple(
        ChangeRequest.create(
            workspace_id=workspace_id,
            number=f"CR-{ordinal}",
            request_type="CATALOG_METADATA",
            title="Update",
            description="",
            requester_id=uuid4(),
            items=[binding],
        )
        for ordinal, binding in enumerate(bindings, start=1)
    )
    index.calls = 0
    reader = subject(
        workspace_id=workspace_id,
        system_id=first_system,
        action=Action.CHANGE_READ,
    )
    visible = await service.filter_authorized_change_requests(
        workspace_id=workspace_id,
        subject=reader,
        change_requests=requests,
        action=Action.CHANGE_READ,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="list",
        strict_binding=False,
    )
    assert visible == (requests[0],)
    assert index.calls == 1


@pytest.mark.asyncio
async def test_rejects_target_missing_from_authorized_local_catalog() -> None:
    workspace_id = uuid4()

    with pytest.raises(ForbiddenError, match="not available"):
        await authorizer(()).authorize_targets(
            workspace_id=workspace_id,
            subject=subject(workspace_id=workspace_id),
            items=(item(),),
            request_classification=Classification.INTERNAL,
            environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
            request_id="request-2",
        )


@pytest.mark.asyncio
async def test_rejects_catalog_adapter_result_from_another_workspace() -> None:
    workspace_id = uuid4()
    cross_workspace_target = asset(workspace_id=uuid4())

    with pytest.raises(ForbiddenError, match="not available"):
        await authorizer((cross_workspace_target,)).authorize_targets(
            workspace_id=workspace_id,
            subject=subject(workspace_id=workspace_id),
            items=(item(),),
            request_classification=Classification.INTERNAL,
            environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
            request_id="request-cross-workspace",
        )


@pytest.mark.asyncio
async def test_rejects_non_dataset_provider_target() -> None:
    workspace_id = uuid4()
    target = asset(
        workspace_id=workspace_id,
        asset_type="CONTAINER",
        external_urn="urn:li:dataset:test",
    )

    with pytest.raises(ForbiddenError, match="not available"):
        await authorizer((target,)).authorize_targets(
            workspace_id=workspace_id,
            subject=subject(workspace_id=workspace_id),
            items=(item(),),
            request_classification=Classification.INTERNAL,
            environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
            request_id="request-non-dataset",
        )


@pytest.mark.asyncio
async def test_rejects_request_classification_below_target() -> None:
    workspace_id = uuid4()
    target = asset(
        workspace_id=workspace_id,
        classification=Classification.CONFIDENTIAL,
    )

    with pytest.raises(ValidationError, match="cannot be lower") as error:
        await authorizer((target,)).authorize_targets(
            workspace_id=workspace_id,
            subject=subject(workspace_id=workspace_id),
            items=(item(),),
            request_classification=Classification.INTERNAL,
            environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
            request_id="request-3",
        )

    assert error.value.details == {"minimum_classification": "CONFIDENTIAL"}


@pytest.mark.asyncio
async def test_rejects_target_outside_subject_system_scope() -> None:
    workspace_id = uuid4()
    target = asset(workspace_id=workspace_id, system_id=uuid4())
    actor = replace(subject(workspace_id=workspace_id), allowed_system_ids=frozenset())

    with pytest.raises(ForbiddenError, match="not available"):
        await authorizer((target,)).authorize_targets(
            workspace_id=workspace_id,
            subject=actor,
            items=(item(),),
            request_classification=Classification.INTERNAL,
            environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
            request_id="request-4",
        )
