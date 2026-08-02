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
    AuthenticationAssurance,
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
        self.requested_external_urns: list[tuple[str, ...]] = []

    async def get_authorized_assets_by_external_urns(
        self, *, external_urns: tuple[str, ...], **_: object
    ) -> tuple[CatalogAssetIndex, ...]:
        self.calls += 1
        self.requested_external_urns.append(external_urns)
        allowed = set(external_urns)
        return tuple(asset for asset in self.assets if asset.external_urn in allowed)


def asset(
    *,
    workspace_id: UUID,
    classification: Classification = Classification.INTERNAL,
    system_id: UUID | None = None,
    domain_id: UUID | None = None,
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
        domain_id=domain_id,
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
    domain_id = uuid4()

    target = asset(
        workspace_id=workspace_id,
        system_id=system_id,
        domain_id=domain_id,
        asset_type="VIEW",
    )
    actor = replace(
        subject(workspace_id=workspace_id, system_id=system_id),
        allowed_domain_ids=frozenset(),
    )
    bound = await authorizer((target,)).authorize_targets(
        workspace_id=workspace_id,
        subject=actor,
        items=(item(),),
        request_classification=Classification.INTERNAL,
        action=Action.CHANGE_CREATE,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="request-1",
    )
    assert bound[0].target_asset_id == target.asset_id
    assert bound[0].target_system_id == system_id
    assert bound[0].target_domain_id == domain_id
    assert bound[0].target_classification is Classification.INTERNAL
    assert bound[0].target_binding_hash == bound[0].expected_target_binding_hash()


@pytest.mark.asyncio
async def test_revision_target_binding_uses_change_edit_without_change_create_fallback() -> None:
    workspace_id = uuid4()
    system_id = uuid4()
    target = asset(workspace_id=workspace_id, system_id=system_id)
    actor = replace(
        subject(workspace_id=workspace_id, system_id=system_id),
        allowed_actions=frozenset({Action.CHANGE_EDIT}),
    )

    bound = await authorizer((target,)).authorize_targets(
        workspace_id=workspace_id,
        subject=actor,
        items=(item(),),
        request_classification=Classification.INTERNAL,
        action=Action.CHANGE_EDIT,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="revision-edit-target",
    )

    assert bound[0].routing_system_id == system_id
    with pytest.raises(ForbiddenError, match="not available"):
        await authorizer((target,)).authorize_targets(
            workspace_id=workspace_id,
            subject=actor,
            items=(item(),),
            request_classification=Classification.INTERNAL,
            action=Action.CHANGE_CREATE,
            environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
            request_id="revision-must-not-fallback-to-create",
        )


@pytest.mark.asyncio
async def test_rejects_restricted_target_without_explicit_grant() -> None:
    workspace_id = uuid4()
    system_id = uuid4()
    domain_id = uuid4()
    target = asset(
        workspace_id=workspace_id,
        classification=Classification.RESTRICTED,
        system_id=system_id,
        domain_id=domain_id,
    )
    actor = replace(
        subject(workspace_id=workspace_id, system_id=system_id),
        clearance=Classification.RESTRICTED,
        allowed_domain_ids=frozenset({domain_id}),
    )

    with pytest.raises(ForbiddenError, match="not available"):
        await authorizer((target,)).authorize_targets(
            workspace_id=workspace_id,
            subject=actor,
            items=(item(),),
            request_classification=Classification.RESTRICTED,
            action=Action.CHANGE_CREATE,
            environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
            request_id="restricted-without-grant",
        )


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
        action=Action.CHANGE_CREATE,
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
        action=Action.CHANGE_CREATE,
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
async def test_approval_authorization_reads_only_the_actors_system_targets() -> None:
    workspace_id = uuid4()
    first_system = uuid4()
    second_system = uuid4()
    first_asset = asset(
        workspace_id=workspace_id,
        system_id=first_system,
        external_urn="urn:li:dataset:first-approval",
    )
    second_asset = asset(
        workspace_id=workspace_id,
        system_id=second_system,
        external_urn="urn:li:dataset:second-approval",
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
        action=Action.CHANGE_CREATE,
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="bind-approval-targets",
    )
    request = ChangeRequest.create(
        workspace_id=workspace_id,
        number="CR-APPROVAL-SCOPE",
        request_type="CATALOG_REVIEW",
        title="Scoped approval",
        description="",
        requester_id=uuid4(),
        items=[
            replace(
                binding,
                target_type="DATAHUB_INTAKE",
                operation="REVIEW",
                aspect_name="changeIntake",
            )
            for binding in bindings
        ],
    )
    index.calls = 0
    index.requested_external_urns.clear()
    actor = subject(
        workspace_id=workspace_id,
        system_id=first_system,
        action=Action.CHANGE_REVIEW,
    )

    visible_item_ids = await service.authorize_approval_targets(
        workspace_id=workspace_id,
        subject=actor,
        change_request=request,
        action=Action.CHANGE_REVIEW,
        approval_system_ids=frozenset({first_system}),
        environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
        request_id="approve-first-system",
    )

    assert visible_item_ids == frozenset({request.items[0].item_id})
    assert index.requested_external_urns == [(first_asset.external_urn,)]


@pytest.mark.asyncio
async def test_approval_filter_keeps_same_asset_self_approval_denied_per_request() -> None:
    now = datetime.now(UTC)
    workspace_id = uuid4()
    system_id = uuid4()
    target = asset(workspace_id=workspace_id, system_id=system_id)
    actor = replace(
        subject(
            workspace_id=workspace_id,
            system_id=system_id,
            action=Action.CHANGE_APPROVE,
        ),
        authentication_assurance=AuthenticationAssurance.HARDWARE_WEBAUTHN,
        authentication_time=now,
    )
    maker = replace(actor, allowed_actions=frozenset({Action.CHANGE_CREATE}))
    binding = (
        await authorizer((target,)).authorize_targets(
            workspace_id=workspace_id,
            subject=maker,
            items=(item(),),
            request_classification=Classification.INTERNAL,
            action=Action.CHANGE_CREATE,
            environment=EnvironmentAttributes(requested_at=now),
            request_id="bind-shared-target",
        )
    )[0]
    self_request = ChangeRequest.create(
        workspace_id=workspace_id,
        number="CR-SELF",
        request_type="CATALOG_METADATA",
        title="Self",
        description="",
        requester_id=actor.subject_id,
        items=[binding],
    )
    other_request = ChangeRequest.create(
        workspace_id=workspace_id,
        number="CR-OTHER",
        request_type="CATALOG_METADATA",
        title="Other",
        description="",
        requester_id=uuid4(),
        items=[binding],
    )

    visible = await authorizer((target,)).filter_authorized_change_requests(
        workspace_id=workspace_id,
        subject=actor,
        change_requests=(self_request, other_request),
        action=Action.CHANGE_APPROVE,
        environment=EnvironmentAttributes(requested_at=now),
        request_id="approval-self-check",
        strict_binding=True,
    )

    assert visible == (other_request,)


@pytest.mark.asyncio
async def test_rejects_target_missing_from_authorized_local_catalog() -> None:
    workspace_id = uuid4()

    with pytest.raises(ForbiddenError, match="not available"):
        await authorizer(()).authorize_targets(
            workspace_id=workspace_id,
            subject=subject(workspace_id=workspace_id),
            items=(item(),),
            request_classification=Classification.INTERNAL,
            action=Action.CHANGE_CREATE,
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
            action=Action.CHANGE_CREATE,
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
            action=Action.CHANGE_CREATE,
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
            action=Action.CHANGE_CREATE,
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
            action=Action.CHANGE_CREATE,
            environment=EnvironmentAttributes(requested_at=datetime.now(UTC)),
            request_id="request-4",
        )
