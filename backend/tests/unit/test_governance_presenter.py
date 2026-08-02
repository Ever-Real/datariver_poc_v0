from datetime import UTC, date, datetime
from uuid import uuid4

from datariver.domain.authz import Classification
from datariver.domain.governance import (
    ChangeItem,
    ChangePriority,
    ChangeRequest,
    ChangeState,
    ChangeUrgency,
    change_target_binding_hash,
)
from datariver.interfaces.http.presenters import (
    change_request_response,
    public_change_item_identity,
)


def _request(*, request_type: str) -> ChangeRequest:
    workspace_id = uuid4()
    asset_id = uuid4()
    system_id = uuid4()
    target_ref = "urn:li:dataset:(urn:li:dataPlatform:postgres,db.public.events,PROD)"
    target_binding_hash = change_target_binding_hash(
        target_ref=target_ref,
        asset_id=asset_id,
        asset_type="DATASET",
        system_id=system_id,
        domain_id=None,
        owner_department_id=None,
        classification=Classification.INTERNAL,
        lifecycle="ACTIVE",
    )
    return ChangeRequest.create(
        workspace_id=workspace_id,
        number="CR-2026-000001",
        request_type=request_type,
        title="Governed metadata",
        description="Change controlled metadata.",
        requester_id=uuid4(),
        classification=Classification.INTERNAL,
        items=[
            ChangeItem(
                item_id=uuid4(),
                target_type="DATAHUB_ASPECT",
                target_ref=target_ref,
                operation="UPSERT",
                aspect_name="globalTags",
                before_hash="a" * 64,
                after_hash="b" * 64,
                after_document={"tags": [{"tag": "urn:li:tag:restricted"}]},
                target_asset_id=asset_id,
                target_asset_type="DATASET",
                target_system_id=system_id,
                target_classification=Classification.INTERNAL,
                target_lifecycle="ACTIVE",
                target_source_version="provider-v1",
                target_observed_at=datetime.now(UTC),
                target_binding_hash=target_binding_hash,
                routing_system_id=system_id,
            )
        ],
    )


def test_typed_catalog_metadata_change_response_redacts_provider_routing_and_document() -> None:
    response = change_request_response(_request(request_type="BULK_CATALOG_METADATA"))

    assert len(response.items) == 1
    item = response.items[0]
    assert item.target_type == "CATALOG_ASSET_METADATA"
    assert item.target_ref == f"datariver:catalog-asset:{item.target_asset_id}"
    assert item.aspect_name == "GOVERNED_CATALOG_METADATA"
    assert item.after_document == {}
    serialized = response.model_dump_json()
    assert "urn:li:" not in serialized
    assert "globalTags" not in serialized
    assert "restricted" not in serialized


def test_existing_change_response_and_summary_identity_remain_compatible() -> None:
    request = _request(request_type="CATALOG_CONTROLLED_METADATA")
    response = change_request_response(request)
    item = response.items[0]

    assert item.target_type == "DATAHUB_ASPECT"
    assert item.target_ref == request.items[0].target_ref
    assert item.aspect_name == "globalTags"
    assert item.after_document == request.items[0].after_document
    assert public_change_item_identity(
        request_type=request.request_type,
        target_ref=item.target_ref,
        aspect_name=item.aspect_name,
        target_asset_id=item.target_asset_id,
    ) == (item.target_ref, item.aspect_name)


def test_change_intake_response_requires_an_explicit_authorized_revision_hint() -> None:
    request = _request(request_type="CHANGE_INTAKE")
    current_round = request.rounds[0]
    current_round.request_date = date(2026, 8, 2)
    current_round.request_department = "Engineering"
    current_round.request_reason = "Correct the requested table."
    current_round.request_content = "Add the missing owner field."
    current_round.priority = ChangePriority.HIGH
    current_round.urgency = ChangeUrgency.URGENT
    request.state = ChangeState.CHANGES_REQUESTED

    response = change_request_response(request)

    assert response.revision_allowed is False
    assert response.rounds[0].request_date == date(2026, 8, 2)
    assert response.rounds[0].request_department == "Engineering"
    assert response.rounds[0].request_reason == "Correct the requested table."
    assert response.rounds[0].request_content == "Add the missing owner field."
    assert response.rounds[0].priority == "HIGH"
    assert response.rounds[0].urgency == "URGENT"
    assert change_request_response(request, revision_allowed=True).revision_allowed is True
    request.state = ChangeState.REJECTED
    assert change_request_response(request, revision_allowed=True).revision_allowed is False
