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
from datariver.domain.common import ForbiddenError, ValidationError
from datariver.domain.governance import ChangeItem


class NoPolicySnapshot:
    async def read_candidate(self, **_: object) -> None:
        return None


class MemoryCatalogIndex:
    def __init__(self, assets: tuple[CatalogAssetIndex, ...]) -> None:
        self.assets = assets

    async def get_authorized_assets_by_external_urns(
        self, *, external_urns: tuple[str, ...], **_: object
    ) -> tuple[CatalogAssetIndex, ...]:
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


def subject(*, workspace_id: UUID, system_id: UUID | None = None) -> SubjectAttributes:
    return SubjectAttributes(
        subject_id=uuid4(),
        workspace_id=workspace_id,
        active=True,
        department_id=None,
        groups=frozenset(),
        job_function=None,
        clearance=Classification.CONFIDENTIAL,
        allowed_system_ids=frozenset({system_id}) if system_id is not None else frozenset(),
        allowed_actions=frozenset({Action.CHANGE_CREATE}),
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

    await authorizer((asset(workspace_id=workspace_id, system_id=system_id),)).authorize_targets(
        workspace_id=workspace_id,
        subject=subject(workspace_id=workspace_id, system_id=system_id),
        items=(item(),),
        request_classification=Classification.INTERNAL,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-1",
    )


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
